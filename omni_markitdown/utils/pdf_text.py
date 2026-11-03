"""PDF の文字を、行 → 段落へ組み立て直す

PDF の中では、文字は「どこに何を描くか」の命令でしかなく、PyMuPDF の行・ブロックは
作り手のアプリ次第でばらばらになる。特に日本の官公庁PDFでは次のことが起きる:

- 句読点（，。）だけが別の命令で後から重ね打ちされ、行の外に浮く
  （例: 官公庁のPDF。本文行の x=282 と行末 x=519 に「，」が別ブロックで置かれる）
- 1行ごとに別ブロックになり、段落としてつながらない
- 太字を「同じ文字を少しずらして2回描く」ことで表現している

そこで、文字1つ1つの座標から行を作り直し、字下げや行末の余りで段落を判定する。
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from typing import List, Optional, Sequence, Tuple

import pymupdf

from omni_markitdown.utils.reading_order import xy_cut_order

BBox = Tuple[float, float, float, float]

# 行頭がこれなら新しい段落（報告書・論文などの見出し記号）
PARA_START_RE = re.compile(
    r"^(【|〔|＜|<|#|第[0-9０-９一二三四五六七八九十百]+[問章節款条項編部]|"
    r"[(（][0-9０-９一二三四五六七八九十ア-ンａ-ｚa-z]{1,3}[)）]|"
    r"[0-9０-９]{1,2}[．.、]|[一二三四五六七八九十]{1,3}[、．]|[①-⑳]|[ア-ン][　 ]|[・•●■◆□○])"
)
EMPHASIS_DOTS_RE = re.compile(r"^[．・﹅﹆•◦·.\s]{2,}$")
BULLET_RE = re.compile(r"^\s*[・•●◦▪■◆○]\s*")
_CJK = r"　-〿぀-ヿ㐀-鿿豈-﫿＀-￯"
_SPACE_BETWEEN_CJK = re.compile(rf"(?<=[{_CJK}])[ \t ]+(?=[{_CJK}])")


@dataclass
class PLine:
    """組み立て直した1行"""
    text: str
    bbox: BBox
    size: float
    vertical: bool = False


@dataclass
class Paragraph:
    lines: List[PLine] = field(default_factory=list)

    @property
    def bbox(self) -> BBox:
        xs0, ys0, xs1, ys1 = zip(*(l.bbox for l in self.lines))
        return (min(xs0), min(ys0), max(xs1), max(ys1))

    @property
    def size(self) -> float:
        return max(l.size for l in self.lines)

    @property
    def text(self) -> str:
        return join_lines([l.text for l in self.lines])


# 康熙部首・CJK部首補助（⾒ ⾏ ⼈ ⻑ など）は見た目が漢字でも別の文字コード。検索・照合で一致しないので通常の漢字に戻す
_RADICAL_RE = re.compile(r"[⺀-⻿⼀-⿟]")
_RADICAL_SUPPLEMENT = {"⺟": "母", "⻑": "長", "⻘": "青", "⻝": "食", "⻤": "鬼", "⻄": "西", "⻁": "虎", "⻆": "角", "⻩": "黄", "⻭": "歯", "⻲": "亀", "⻫": "斉", "⻨": "麦", "⻯": "竜", "⻑": "長"}


def normalize_radicals(text: str) -> str:
    def repl(m):
        ch = m.group(0)
        if ch in _RADICAL_SUPPLEMENT:
            return _RADICAL_SUPPLEMENT[ch]
        n = unicodedata.normalize("NFKC", ch)
        return n if n != ch else ch
    return _RADICAL_RE.sub(repl, text)


SENTENCE_END_RE = re.compile(r"[。．.!?！？」』）)\]】:：]$")


def ends_sentence(text: str) -> bool:
    return bool(SENTENCE_END_RE.search(text.strip()))


def merge_broken_paragraphs(paras: List[str]) -> List[str]:
    """文の途中で切れた段落（段・ページの境目など）を前の段落につなぎ直す。
    見出し・表・画像・引用・リスト・見出し記号で始まる段落にはつながない"""
    special = ("#", "|", "!", ">", "- ", "```")
    out: List[str] = []
    for p in paras:
        if (out and not out[-1].startswith(special) and not p.startswith(special)
                and not ends_sentence(out[-1]) and not PARA_START_RE.match(p)):
            out[-1] = join_lines([out[-1], p])
        else:
            out.append(p)
    return out


_JA = r"\u3000-\u30ff\u3400-\u9fff\uff00-\uffef"
_PAREN_RE = re.compile(r"\(([^()\n]{0,60})\)")


def normalize_ocr_punctuation(text: str) -> str:
    """OCR が半角で読んだ句読点・かっこを、日本語の文脈では全角に戻す。
    - 日本語の句読点・閉じかっこの直後の空白を取る
    - 日本語の間の「,」→「，」
    - 日本語の間の「.」→ そのページで「。」を使っていれば読点の読み違いとして「，」、使っていなければ「．」
    - 中に日本語を含むかっこ・(1) のような番号のかっこ →（）。英語だけのかっこはそのまま
    """
    # 日本語の句読点・閉じかっこの直後に OCR が入れる空白（「担当、 その他」）を取る。英文の空白は残す
    text = re.sub(rf"(?<=[、。，．・：；！？」』）】〕])[ 　]+(?=[{_JA}0-9０-９A-Za-zＡ-Ｚａ-ｚ（「『【〔])", "", text)
    # 漢数字の〇を記号の「○」で読むことがある（「二○条」）。漢数字・単位に挟まれたものは〇に戻す
    text = re.sub(r"(?<=[〇一二三四五六七八九十百千])○|○(?=[〇一二三四五六七八九十百千万条項号年月日円])", "〇", text)
    text = re.sub(rf"(?<=[{_JA}]),\s?(?=[{_JA}0-9(（「『]|$)", "，", text, flags=re.M)
    period = "，" if "。" in text else "．"
    text = re.sub(rf"(?<=[{_JA}])\.(?=[{_JA}(（「『])", period, text)

    def paren(m):
        inner = m.group(1)
        if re.search(rf"[{_JA}]", inner) or re.fullmatch(r"[0-9０-９a-zA-Zａ-ｚア-ン]{1,3}", inner):
            return f"（{inner}）"
        return m.group(0)
    return _PAREN_RE.sub(paren, text)


def clean_inline(text: str) -> str:
    """部首文字を通常の漢字に戻し、日本語の文字の間に入った空白（両端揃え・抽出の癖）を詰める"""
    text = normalize_radicals(text)
    # 「本 問 は 、」のように文字ごとに空白が入った行（字間を空けた組み方・抽出の癖）だけ詰める。
    # 「第1回 講義ノート」のような意図した区切りの空白は残す
    gaps = len(_SPACE_BETWEEN_CJK.findall(text))
    cjk = len(re.findall(rf"[{_CJK}]", text))
    if gaps and (gaps >= 3 and gaps >= cjk * 0.3):
        text = _SPACE_BETWEEN_CJK.sub("", text)
    return text.strip()


def join_lines(lines: Sequence[str]) -> str:
    """行をつなぐ。英数字どうしの間だけ空白を1つ入れる"""
    out = ""
    for ln in (l.strip() for l in lines):
        if not ln:
            continue
        if out and out[-1].isascii() and out[-1].isalnum() and ln[0].isascii() and ln[0].isalnum():
            out += " "
        out += ln
    return clean_inline(out)


# ----------------------------------------------------------------------
# 文字 → 行
# ----------------------------------------------------------------------

def assemble_lines(page, exclude: Sequence[BBox] = ()) -> List[PLine]:
    """ページの全文字を座標で行に組み立て直す（exclude の矩形内の文字は除く）"""
    raw = page.get_text("rawdict", flags=pymupdf.TEXT_PRESERVE_WHITESPACE | pymupdf.TEXT_PRESERVE_LIGATURES)
    chars: List[Tuple[BBox, str, float]] = []
    others: List[PLine] = []

    def excluded(bb: BBox) -> bool:
        cx, cy = (bb[0] + bb[2]) / 2, (bb[1] + bb[3]) / 2
        return any(e[0] - 1 <= cx <= e[2] + 1 and e[1] - 1 <= cy <= e[3] + 1 for e in exclude)

    for b in raw.get("blocks", []):
        if b.get("type") != 0:
            continue
        for ln in b["lines"]:
            dx, dy = ln.get("dir", (1, 0))
            if abs(dy) > 0.3 or dx < 0:
                # 縦書き・回転した行は、行のまま扱う
                text = "".join(c["c"] for sp in ln["spans"] for c in sp["chars"])
                if text.strip() and not excluded(tuple(ln["bbox"])):
                    size = max(sp["size"] for sp in ln["spans"])
                    others.append(PLine(clean_inline(text), tuple(ln["bbox"]), size, vertical=True))
                continue
            for sp in ln["spans"]:
                for c in sp["chars"]:
                    bb = tuple(c["bbox"])
                    if bb[2] - bb[0] <= 0 and c["c"].isspace():
                        continue
                    if not excluded(bb):
                        chars.append((bb, c["c"], sp["size"]))

    # 同じ高さ（文字の縦の中心が近い）の文字を1行に集める
    chars.sort(key=lambda t: ((t[0][1] + t[0][3]) / 2, t[0][0]))
    rows: List[List[Tuple[BBox, str, float]]] = []
    for ch in chars:
        cy = (ch[0][1] + ch[0][3]) / 2
        if rows:
            last = rows[-1]
            ry = sum((c[0][1] + c[0][3]) / 2 for c in last) / len(last)
            if abs(cy - ry) <= max(ch[2], last[0][2]) * 0.35:
                last.append(ch)
                continue
        rows.append([ch])

    lines: List[PLine] = []
    for row in rows:
        row.sort(key=lambda t: t[0][0])
        size = Counter(round(c[2], 1) for c in row if not c[1].isspace()).most_common(1)
        size = size[0][0] if size else row[0][2]
        # 段の溝（大きな空き）で行を分ける
        seg: List[Tuple[BBox, str, float]] = []
        for ch in row:
            if seg and ch[0][0] - max(c[0][2] for c in seg) > max(size * 1.8, 8):
                lines.append(_make_line(seg, size))
                seg = []
            # 太字の重ね打ち（同じ文字がほぼ同じ位置に2回）は1文字にする。
            # 判定は「その文字の幅の半分以上重なっているか」。文字サイズで測ると、
            # 「//」「ii」「ll」のような幅の狭い文字が並んだだけで1つ消える（URL で発生）
            if seg and seg[-1][1] == ch[1] and not ch[1].isspace():
                prev_bb = seg[-1][0]
                width = max(prev_bb[2] - prev_bb[0], ch[0][2] - ch[0][0], 0.1)
                if abs(prev_bb[0] - ch[0][0]) < width * 0.5:
                    continue
            seg.append(ch)
        if seg:
            lines.append(_make_line(seg, size))
    # 点だけの行は傍点（強調の点）なので捨てる（例: 官公庁のPDFで強調語の上に打たれた「．．．．．」）
    lines = [l for l in lines if l.text and not EMPHASIS_DOTS_RE.match(l.text)]
    return lines + others


def _make_line(seg, size: float) -> PLine:
    text = clean_inline("".join(c[1] for c in seg))
    bb = (min(c[0][0] for c in seg), min(c[0][1] for c in seg),
          max(c[0][2] for c in seg), max(c[0][3] for c in seg))
    return PLine(text, bb, size)


# ----------------------------------------------------------------------
# 行 → 段落
# ----------------------------------------------------------------------

def _column_edges(line: PLine, lines: Sequence[PLine]) -> Tuple[float, float]:
    """その行と同じ段にある行の、最も多い左端・右端"""
    lo, hi = line.bbox[0] - line.size, line.bbox[2] + line.size
    same = [l for l in lines if not l.vertical and lo <= (l.bbox[0] + l.bbox[2]) / 2 <= hi]
    if not same:
        return line.bbox[0], line.bbox[2]
    # ある程度の数（最多の4分の1以上）の行がそろう位置のうち、最も外側を段の端とする。
    # 字下げした段落頭や、飛び出した見出し（【公法系科目】など）1〜2行には引っ張られない
    def edge(values, pick):
        cnt = Counter(round(v) for v in values)
        top = max(cnt.values())
        return float(pick(v for v, c in cnt.items() if c >= max(1, top * 0.25)))
    return edge((l.bbox[0] for l in same), min), edge((l.bbox[2] for l in same), max)


def build_paragraphs(lines: Sequence[PLine]) -> List[Paragraph]:
    """読み順に並べた行を段落にまとめる"""
    ordered = xy_cut_order(list(lines), lambda l: l.bbox, vertical=False)
    edges = {id(l): _column_edges(l, lines) for l in ordered}
    paras: List[Paragraph] = []
    prev: Optional[PLine] = None
    for ln in ordered:
        new = prev is None or ln.vertical or prev.vertical
        if not new:
            left, right = edges[id(ln)]
            _, prev_right = edges[id(prev)]
            size = max(ln.size, prev.size)
            gap = ln.bbox[1] - prev.bbox[3]
            new = (
                abs(ln.size - prev.size) > min(ln.size, prev.size) * 0.15   # 文字サイズが変わった
                or gap > size * 1.2                                         # 行間が広い（空行）
                or ln.bbox[0] > left + size * 0.6                           # 字下げ
                or prev.bbox[2] < prev_right - size * 1.5                   # 前の行が途中で終わった
                or bool(PARA_START_RE.match(ln.text))                       # 見出し記号で始まる
                # 段の先頭へ戻ったとき（次の段へ移った）は、前の行が文の終わりなら新しい段落
                or (ln.bbox[1] < prev.bbox[1] - size and ends_sentence(prev.text))
            )
        if new:
            paras.append(Paragraph([ln]))
        else:
            paras[-1].lines.append(ln)
        prev = ln
    return paras
