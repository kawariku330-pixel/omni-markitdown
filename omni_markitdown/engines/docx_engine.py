"""DocxEngine: Word (.docx) → Markdown 変換

- 見出し（見出し1〜6 / Title）、太字・斜体・取り消し線、ハイパーリンク
- 箇条書き・番号付きリスト（入れ子の深さも反映）
- 表（横結合は空セル、縦結合は2行目以降を空にして、文字の重複を防ぐ）
- 画像（`_assets/` に保存してリンクを埋め込む）
- 脚注・文末脚注・コメントを本文直下に引用で差し込む
"""

from __future__ import annotations

import hashlib
import re
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

import docx
from docx.table import Table
from docx.text.paragraph import Paragraph

from omni_markitdown.core.models import ConversionConfig, ConversionResult, ExtractedNote, VisualAsset
from omni_markitdown.engines.base import BaseEngine
from omni_markitdown.utils.assets import save_visual_asset
from omni_markitdown.utils.file_guard import verify_file_readable

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
A = "http://schemas.openxmlformats.org/drawingml/2006/main"
NS = {"w": W, "r": R, "a": A}


def _q(tag: str) -> str:
    prefix, local = tag.split(":")
    return f"{{{NS[prefix]}}}{local}"


HEADING_RE = re.compile(r"(?:見出し|Heading)\s*([1-6])", re.IGNORECASE)
TITLE_RE = re.compile(r"^(Title|表題)$", re.IGNORECASE)
SUBTITLE_RE = re.compile(r"^(Subtitle|副題)$", re.IGNORECASE)
BULLET_STYLE_RE = re.compile(r"(List Bullet|箇条書き)", re.IGNORECASE)
NUMBER_STYLE_RE = re.compile(r"(List Number|段落番号|番号付き)", re.IGNORECASE)


def _md_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("*", "\\*").replace("_", "\\_")


class DocxEngine(BaseEngine):
    """Word (.docx) から本文・見出し・リスト・表・画像・脚注・コメントを取り出すエンジン"""

    SUPPORTED_EXTENSIONS = {".docx"}

    def can_handle(self, path: Path) -> bool:
        return path.suffix.lower() in self.SUPPORTED_EXTENSIONS

    def convert(self, path: Path, config: ConversionConfig, output_dir: Path) -> ConversionResult:
        verify_file_readable(path, config.max_file_size_mb)

        doc = docx.Document(str(path))
        self._doc = doc
        self._config = config
        self._output_dir = output_dir
        with open(path, "rb") as f:
            self._doc_hash = hashlib.sha256(f.read()).hexdigest()[:8]
        self._assets: List[VisualAsset] = []
        self._saved_rids: Dict[str, VisualAsset] = {}
        self._num_formats = self._load_numbering_formats(doc)
        self._list_counters: Dict[Tuple[str, int], int] = {}

        if config.extract_notes:
            self._comments = self._extract_comments(path)
            self._footnotes = self._extract_notes_xml(path, "word/footnotes.xml", "footnote")
            self._endnotes = self._extract_notes_xml(path, "word/endnotes.xml", "endnote")
        else:
            self._comments, self._footnotes, self._endnotes = {}, {}, {}
        self._notes: List[ExtractedNote] = []
        self._emitted_comments: Set[str] = set()

        blocks: List[str] = []
        self._walk(doc.element.body, blocks)

        # 連続するリスト項目は空行を挟まずにまとめる
        out: List[str] = []
        for b in blocks:
            kind = self._list_kind(b)
            prev = self._list_kind(out[-1].split("\n", 1)[0]) if out else None
            last = self._list_kind(out[-1].rsplit("\n", 1)[-1]) if out else None
            # 同じ種類のリスト、または前のリストにぶら下がる子項目ならつなげる
            if kind and prev and (kind == prev or kind == "nested" or (last == "nested" and kind == prev)):
                out[-1] = out[-1] + "\n" + b
            else:
                out.append(b)
        markdown_text = "\n\n".join(x for x in out if x.strip()).strip()

        return ConversionResult(
            markdown=markdown_text,
            assets=self._assets,
            notes=self._notes,
            source_path=path,
            metadata={"format": "docx", "paragraphs_count": len(doc.paragraphs)},
        )

    # ------------------------------------------------------------------
    @staticmethod
    def _list_kind(s: str) -> Optional[str]:
        """リスト行なら "bullet" / "number"、それ以外は None（字下げした子項目は親と同じ扱い）"""
        first = s.split("\n", 1)[0]
        if re.match(r"^- ", first):
            return "bullet"
        if re.match(r"^\d+\. ", first):
            return "number"
        if re.match(r"^\s+(- |\d+\. )", first):
            return "nested"
        return None

    def _walk(self, parent, blocks: List[str]) -> None:
        for el in parent:
            tag = el.tag.split("}")[-1]
            if tag == "p":
                blocks.extend(self._paragraph(Paragraph(el, self._doc)))
            elif tag == "tbl":
                md = self._format_table(Table(el, self._doc))
                if md:
                    blocks.append(md)
            elif tag == "sdt":
                content = el.find(_q("w:sdtContent"))
                if content is not None:
                    self._walk(content, blocks)

    # ------------------------------------------------------------------
    def _paragraph(self, para: Paragraph) -> List[str]:
        text = self._inline_text(para._p).strip()
        notes_md = self._paragraph_notes(para._p) if self._config.extract_notes else []

        if not text:
            return notes_md

        style_name = para.style.name if para.style is not None else ""
        m = HEADING_RE.search(style_name)
        if m:
            line = "#" * int(m.group(1)) + " " + self._strip_emphasis(text)
        elif TITLE_RE.match(style_name):
            line = "# " + self._strip_emphasis(text)
        elif SUBTITLE_RE.match(style_name):
            line = "## " + self._strip_emphasis(text)
        else:
            line = self._list_prefix(para, style_name) + text
        return [line] + notes_md

    @staticmethod
    def _strip_emphasis(text: str) -> str:
        # 見出しの中の ** は不要
        return re.sub(r"\*\*(.+?)\*\*", r"\1", text)

    def _list_prefix(self, para: Paragraph, style_name: str) -> str:
        """箇条書き・番号付きリストなら "- " / "1. " を（字下げ付きで）返す"""
        num_id, ilvl = None, 0
        for pPr in (para._p.pPr, getattr(para.style.element, "pPr", None) if para.style is not None else None):
            if pPr is None:
                continue
            numPr = pPr.find(_q("w:numPr"))
            if numPr is not None:
                nid = numPr.find(_q("w:numId"))
                lvl = numPr.find(_q("w:ilvl"))
                if nid is not None and num_id is None:
                    num_id = nid.get(_q("w:val"))
                if lvl is not None:
                    ilvl = int(lvl.get(_q("w:val")) or 0)
        if num_id in (None, "0"):
            if BULLET_STYLE_RE.search(style_name):
                return "- "
            if NUMBER_STYLE_RE.search(style_name):
                return self._next_number(f"style:{style_name}", 0)
            return ""
        fmt = self._num_formats.get((num_id, ilvl), "bullet")
        indent = "   " * ilvl
        if fmt in ("bullet", "none"):
            return indent + "- "
        return indent + self._next_number(num_id, ilvl)

    def _next_number(self, key: str, ilvl: int) -> str:
        n = self._list_counters.get((key, ilvl), 0) + 1
        self._list_counters[(key, ilvl)] = n
        # 上位レベルが進んだら下位レベルの番号は振り直す
        for k in list(self._list_counters):
            if k[0] == key and k[1] > ilvl:
                del self._list_counters[k]
        return f"{n}. "

    @staticmethod
    def _load_numbering_formats(doc) -> Dict[Tuple[str, int], str]:
        """numbering.xml から (numId, ilvl) → numFmt（bullet / decimal など）を作る"""
        result: Dict[Tuple[str, int], str] = {}
        try:
            numbering = doc.part.numbering_part.element
        except Exception:
            return result
        abstract: Dict[str, Dict[int, str]] = {}
        for an in numbering.findall(_q("w:abstractNum")):
            aid = an.get(_q("w:abstractNumId"))
            levels = {}
            for lvl in an.findall(_q("w:lvl")):
                fmt = lvl.find(_q("w:numFmt"))
                levels[int(lvl.get(_q("w:ilvl")) or 0)] = fmt.get(_q("w:val")) if fmt is not None else "decimal"
            abstract[aid] = levels
        for num in numbering.findall(_q("w:num")):
            nid = num.get(_q("w:numId"))
            ref = num.find(_q("w:abstractNumId"))
            if ref is None:
                continue
            for ilvl, fmt in abstract.get(ref.get(_q("w:val")), {}).items():
                result[(nid, ilvl)] = fmt
        return result

    # ------------------------------------------------------------------
    def _inline_text(self, p_el) -> str:
        """段落内の文字を、太字・斜体・リンク・画像・脚注番号つきで組み立てる"""
        parts: List[str] = []
        for child in p_el:
            tag = child.tag.split("}")[-1]
            if tag == "r":
                parts.append(self._run_text(child))
            elif tag == "hyperlink":
                inner = "".join(self._run_text(r) for r in child.findall(_q("w:r")))
                rid = child.get(_q("r:id"))
                url = None
                if rid:
                    rel = self._doc.part.rels.get(rid)
                    if rel is not None and rel.is_external:
                        url = rel.target_ref
                parts.append(f"[{inner}]({url})" if url and inner.strip() else inner)
            elif tag in ("ins", "smartTag", "customXml", "fldSimple"):
                parts.append(self._inline_text(child))
            # w:del（削除された文字）は出さない
        return self._merge_emphasis("".join(parts))

    @staticmethod
    def _merge_emphasis(s: str) -> str:
        # 隣り合う同じ装飾 "**a****b**" → "**ab**"
        return s.replace("****", "").replace("~~~~", "")

    def _run_text(self, r_el) -> str:
        rPr = r_el.find(_q("w:rPr"))

        def on(name: str) -> bool:
            if rPr is None:
                return False
            e = rPr.find(_q(f"w:{name}"))
            return e is not None and e.get(_q("w:val")) not in ("0", "false", "none")

        buf: List[str] = []
        for c in r_el:
            tag = c.tag.split("}")[-1]
            if tag == "t":
                buf.append(_md_escape(c.text or ""))
            elif tag == "tab":
                buf.append(" ")
            elif tag in ("br", "cr"):
                buf.append("  \n")
            elif tag == "footnoteReference":
                fid = c.get(_q("w:id"))
                buf.append(f"[^{fid}]" if fid in self._footnotes else "")
            elif tag == "endnoteReference":
                eid = c.get(_q("w:id"))
                buf.append(f"[^e{eid}]" if eid in self._endnotes else "")
            elif tag in ("drawing", "pict"):
                buf.append(self._images_in(c))
        text = "".join(buf)
        core = text.strip()
        if not core or core.startswith("!["):
            return text
        lead = text[: len(text) - len(text.lstrip())]
        trail = text[len(text.rstrip()):]
        if on("strike") or on("dstrike"):
            core = f"~~{core}~~"
        if on("i"):
            core = f"*{core}*"
        if on("b"):
            core = f"**{core}**"
        return lead + core + trail

    def _images_in(self, el) -> str:
        if not self._config.extract_images:
            return ""
        links = []
        rids = [b.get(_q("r:embed")) for b in el.iter(_q("a:blip"))]
        rids += [d.get(_q("r:id")) for d in el.iter("{urn:schemas-microsoft-com:vml}imagedata")]
        for rid in filter(None, rids):
            asset = self._saved_rids.get(rid)
            if asset is None:
                try:
                    part = self._doc.part.related_parts[rid]
                except KeyError:
                    continue
                ext = Path(str(part.partname)).suffix.lstrip(".").lower() or "png"
                asset = save_visual_asset(
                    image_bytes=part.blob, doc_hash=self._doc_hash, page_number=0,
                    image_index=len(self._assets) + 1, output_dir=self._output_dir,
                    assets_dir_name=self._config.assets_dir, ext=ext,
                )
                self._saved_rids[rid] = asset
                self._assets.append(asset)
            links.append(f"![{asset.asset_id}]({asset.rel_path})")
        return "\n\n".join(links)

    # ------------------------------------------------------------------
    def _paragraph_notes(self, p_el) -> List[str]:
        out: List[str] = []
        for ref in p_el.iter(_q("w:footnoteReference")):
            fid = ref.get(_q("w:id"))
            if fid in self._footnotes:
                content = self._footnotes[fid]
                out.append(f"> 📝 脚注 [^{fid}]: {content}")
                self._notes.append(ExtractedNote(note_type="footnote", note_id=fid, content=content))
        for ref in p_el.iter(_q("w:endnoteReference")):
            eid = ref.get(_q("w:id"))
            if eid in self._endnotes:
                content = self._endnotes[eid]
                out.append(f"> 📝 文末脚注 [^e{eid}]: {content}")
                self._notes.append(ExtractedNote(note_type="footnote", note_id=f"e{eid}", content=content))
        cids = [c.get(_q("w:id")) for c in p_el.iter(_q("w:commentRangeStart"))]
        cids += [c.get(_q("w:id")) for c in p_el.iter(_q("w:commentReference"))]
        for cid in cids:
            if cid in self._comments and cid not in self._emitted_comments:
                self._emitted_comments.add(cid)
                author, content = self._comments[cid]
                out.append(f"> 💬 コメント [{author}]: {content}")
                self._notes.append(ExtractedNote(note_type="comment", note_id=cid, author=author, content=content))
        return out

    # ------------------------------------------------------------------
    def _format_table(self, table: Table) -> str:
        """表を GitHub 形式の Markdown 表にする（結合セルの文字は1回だけ出す）"""
        grid: List[List[str]] = []
        for tr in table._tbl.tr_lst:
            row: List[str] = []
            for tc in tr.tc_lst:
                span = tc.grid_span or 1
                if tc.vMerge == "continue":
                    text = ""
                else:
                    paras = [self._inline_text(p).strip() for p in tc.iter(_q("w:p"))]
                    text = "<br>".join(p for p in paras if p).replace("|", "\\|").replace("\n", " ")
                row.append(text)
                row.extend([""] * (span - 1))
            grid.append(row)
        if not grid:
            return ""
        width = max(len(r) for r in grid)
        grid = [r + [""] * (width - len(r)) for r in grid]
        lines = ["| " + " | ".join(grid[0]) + " |", "| " + " | ".join(["---"] * width) + " |"]
        lines += ["| " + " | ".join(r) + " |" for r in grid[1:]]
        return "\n".join(lines)

    # ------------------------------------------------------------------
    @staticmethod
    def _xml_text(el) -> str:
        return "".join(t.text for t in el.iter(_q("w:t")) if t.text).strip()

    def _extract_comments(self, file_path: Path) -> Dict[str, Tuple[str, str]]:
        result: Dict[str, Tuple[str, str]] = {}
        try:
            with zipfile.ZipFile(str(file_path)) as zf:
                if "word/comments.xml" in zf.namelist():
                    root = ET.fromstring(zf.read("word/comments.xml"))
                    for c in root.iter(_q("w:comment")):
                        cid = c.get(_q("w:id"))
                        text = self._xml_text(c)
                        if cid and text:
                            result[cid] = (c.get(_q("w:author"), "作成者不明"), text)
        except (zipfile.BadZipFile, ET.ParseError, KeyError):
            pass
        return result

    def _extract_notes_xml(self, file_path: Path, part: str, tag: str) -> Dict[str, str]:
        result: Dict[str, str] = {}
        try:
            with zipfile.ZipFile(str(file_path)) as zf:
                if part in zf.namelist():
                    root = ET.fromstring(zf.read(part))
                    for n in root.iter(_q(f"w:{tag}")):
                        nid = n.get(_q("w:id"))
                        # -1 / 0 は区切り線などの特殊な脚注
                        if nid in (None, "-1", "0") or n.get(_q("w:type")) in ("separator", "continuationSeparator"):
                            continue
                        text = self._xml_text(n)
                        if text:
                            result[nid] = text
        except (zipfile.BadZipFile, ET.ParseError, KeyError):
            pass
        return result
