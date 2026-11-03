"""PDF の注釈（ハイライト・コメント・書き込み）を取り出し、対象の段落の直後に置く

- ハイライト・下線・波線・取り消し線: 1行ごとの線の位置（四角の頂点）の中にある文字だけを取る
  （注釈の外枠でまとめて切り出すと、2行にまたがるとき前後の線を引いていない文まで入る）
- 四角・丸の囲み: 囲みの中の文字を取る
- 付箋（テキスト注釈）: コメント。返信（IRT）は元のコメントの下にまとめる
- フリーテキスト（ページに直接打ち込んだ文字）: 本文の文字としても抽出されてしまうので、
  本文からは除き（exclude_rects）、注釈としてだけ出す
- インク（手書きの線）・スタンプ: 文章が無くても「あった」ことを残す
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

import pymupdf

from omni_markitdown.core.models import ExtractedNote
from omni_markitdown.utils.pdf_text import clean_inline

BBox = Tuple[float, float, float, float]

_MARKUP = {
    pymupdf.PDF_ANNOT_HIGHLIGHT: "🖍️ ハイライト",
    pymupdf.PDF_ANNOT_UNDERLINE: "🖍️ 下線",
    pymupdf.PDF_ANNOT_SQUIGGLY: "🖍️ 波線",
    pymupdf.PDF_ANNOT_STRIKE_OUT: "✂️ 取り消し線",
}
_ENCLOSE = {
    pymupdf.PDF_ANNOT_SQUARE: "⭕ 囲み（四角）",
    pymupdf.PDF_ANNOT_CIRCLE: "⭕ 囲み（丸）",
}
_SKIP = {pymupdf.PDF_ANNOT_POPUP, pymupdf.PDF_ANNOT_LINK, pymupdf.PDF_ANNOT_WIDGET}


@dataclass
class PdfAnnotation:
    bbox: BBox
    markdown: str
    notes: List[ExtractedNote] = field(default_factory=list)


def _chars(page) -> List[Tuple[BBox, str]]:
    raw = page.get_text("rawdict", flags=pymupdf.TEXT_PRESERVE_WHITESPACE)
    out = []
    for b in raw.get("blocks", []):
        for ln in b.get("lines", []):
            for sp in ln["spans"]:
                for c in sp["chars"]:
                    out.append((tuple(c["bbox"]), c["c"]))
    return out


def _text_in(chars: Sequence[Tuple[BBox, str]], rect: BBox) -> str:
    """矩形の中に中心がある文字を、上から下・左から右に並べてつなぐ"""
    x0, y0, x1, y1 = rect
    hit = [(bb, c) for bb, c in chars
           if x0 - 0.5 <= (bb[0] + bb[2]) / 2 <= x1 + 0.5 and y0 - 0.5 <= (bb[1] + bb[3]) / 2 <= y1 + 0.5]
    hit.sort(key=lambda t: (round((t[0][1] + t[0][3]) / 2), t[0][0]))
    return clean_inline("".join(c for _, c in hit))


def _quad_rects(annot) -> List[BBox]:
    """マークアップ注釈の1行ごとの四角（頂点4つずつ）"""
    pts = annot.vertices or []
    rects = []
    for i in range(0, len(pts) - 3, 4):
        xs = [p[0] for p in pts[i:i + 4]]
        ys = [p[1] for p in pts[i:i + 4]]
        rects.append((min(xs), min(ys), max(xs), max(ys)))
    return rects or [tuple(annot.rect)]


def free_text_rects(page) -> List[BBox]:
    """本文から除くべき矩形（フリーテキスト・スタンプは見た目の文字が本文として抽出されるため）"""
    out = []
    for a in page.annots() or []:
        if a.type[0] in (pymupdf.PDF_ANNOT_FREE_TEXT, pymupdf.PDF_ANNOT_STAMP):
            out.append(tuple(a.rect))
    return out


def collect_annotations(page, page_num: int) -> List[PdfAnnotation]:
    annots = [a for a in (page.annots() or []) if a.type[0] not in _SKIP]
    if not annots:
        return []
    chars = _chars(page)

    by_xref: Dict[int, dict] = {}
    order: List[int] = []
    for a in annots:
        info = a.info or {}
        kind = a.type[0]
        content = (info.get("content") or "").strip()
        author = (info.get("title") or "").strip()
        marked = ""
        bbox: BBox = tuple(a.rect)
        if kind in _MARKUP:
            rects = _quad_rects(a)
            marked = "".join(_text_in(chars, r) for r in rects)
            bbox = (min(r[0] for r in rects), min(r[1] for r in rects),
                    max(r[2] for r in rects), max(r[3] for r in rects))
            label = _MARKUP[kind]
        elif kind in _ENCLOSE:
            marked = _text_in(chars, bbox)
            label = _ENCLOSE[kind]
        elif kind == pymupdf.PDF_ANNOT_FREE_TEXT:
            label = "📝 書き込み"
        elif kind == pymupdf.PDF_ANNOT_INK:
            label = "✍️ 手書きの書き込み"
        elif kind == pymupdf.PDF_ANNOT_STAMP:
            label = "📌 スタンプ"
            content = content or (info.get("name") or "").strip()
        elif kind == pymupdf.PDF_ANNOT_FILE_ATTACHMENT:
            label = "📎 添付ファイル"
            try:
                content = content or a.file_info.get("filename", "")
            except Exception:
                pass
        elif kind == pymupdf.PDF_ANNOT_TEXT:
            label = "💬 コメント"
        else:
            label = "💬 注釈"

        # 文章も対象の文字も無い図形・線は、手書き・スタンプ以外は捨てる
        if not content and not marked and kind not in (pymupdf.PDF_ANNOT_INK, pymupdf.PDF_ANNOT_STAMP):
            continue

        who = f" [{author}]" if author else ""
        body = []
        if marked:
            body.append(f"「{marked}」")
        if content:
            body.append(content)
        text = " — ".join(body) if body else f"（p.{page_num} に{label.split(' ', 1)[1]}あり）"
        by_xref[a.xref] = {
            "line": f"> {label}{who}: {text}",
            "bbox": bbox,
            "irt": getattr(a, "irt_xref", 0) or 0,
            "note": ExtractedNote(
                note_type="comment" if kind == pymupdf.PDF_ANNOT_TEXT else "annotation",
                note_id=f"p{page_num}_{a.xref}",
                author=author or None,
                content=content or marked or label,
                page_number=page_num,
            ),
            "author": author,
            "content": content,
            "replies": [],
        }
        order.append(a.xref)

    # 返信を元のコメントの下にまとめる
    roots: List[int] = []
    for x in order:
        d = by_xref[x]
        parent = d["irt"]
        if parent and parent in by_xref and parent != x:
            by_xref[parent]["replies"].append(x)
        else:
            roots.append(x)

    def render(x: int, depth: int = 0) -> Tuple[List[str], List[ExtractedNote]]:
        d = by_xref[x]
        if depth == 0:
            lines = [d["line"]]
        else:
            who = f" [{d['author']}]" if d["author"] else ""
            lines = [">" + "  " * depth + f" ↳ 返信{who}: {d['content']}"]
        notes = [d["note"]]
        for r in d["replies"]:
            l2, n2 = render(r, depth + 1)
            lines += [">"] + l2 if depth == 0 else l2
            notes += n2
        return lines, notes

    out: List[PdfAnnotation] = []
    for x in roots:
        lines, notes = render(x)
        out.append(PdfAnnotation(bbox=by_xref[x]["bbox"], markdown="\n".join(lines), notes=notes))
    return out


def _overlap(a: BBox, b: BBox) -> float:
    w = min(a[2], b[2]) - max(a[0], b[0])
    h = min(a[3], b[3]) - max(a[1], b[1])
    return w * h if w > 0 and h > 0 else 0.0


def attach_annotations(parts: Sequence[Tuple[Optional[BBox], str]], annots: Sequence[PdfAnnotation]) -> List[str]:
    """各注釈を、重なりが最も大きい（無ければ縦方向に最も近い）段落の直後に置く"""
    if not annots:
        return [md for _, md in parts]
    targets: Dict[int, List[PdfAnnotation]] = {}
    tail: List[PdfAnnotation] = []
    candidates = [(i, bb) for i, (bb, _) in enumerate(parts) if bb is not None]
    for an in annots:
        if not candidates:
            tail.append(an)
            continue
        best = max(candidates, key=lambda c: _overlap(c[1], an.bbox))
        if _overlap(best[1], an.bbox) <= 0:
            cy = (an.bbox[1] + an.bbox[3]) / 2

            def dist(c):
                bb = c[1]
                dy = 0 if bb[1] <= cy <= bb[3] else min(abs(cy - bb[1]), abs(cy - bb[3]))
                dx = max(0.0, bb[0] - an.bbox[2], an.bbox[0] - bb[2])
                return (dy, dx)
            best = min(candidates, key=dist)
        targets.setdefault(best[0], []).append(an)

    out: List[str] = []
    for i, (_, md) in enumerate(parts):
        out.append(md)
        for an in sorted(targets.get(i, []), key=lambda a: (a.bbox[1], a.bbox[0])):
            out.append(an.markdown)
    out += [an.markdown for an in tail]
    return out
