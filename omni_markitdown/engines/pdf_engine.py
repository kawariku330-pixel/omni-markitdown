"""PdfEngine: PyMuPDF による PDF → Markdown 変換

- 見出し: 本文より大きい文字サイズの行を、大きい順に # / ## / ### にする
- 表: PyMuPDF の表検出で Markdown の表にする（表の中の文字は本文から外す）
- 段組: XY-cut で読み順を復元する（2段組は左段 → 右段）
- ヘッダー・フッター: 複数ページで同じ位置に繰り返す行と、余白のページ番号を除く
- 画像: 元の位置に `![...](_assets/...)` を置く。同じ画像は1回だけ保存し、小さなアイコンは除く
- 注釈: コメント付き注釈とハイライト（線を引いた本文）を、そのページの最後に引用で出す
- スキャンページ: 文字がほぼ無いページは ndlocr-lite で OCR する
"""

from __future__ import annotations

import hashlib
import logging
import re
import tempfile
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pymupdf

from omni_markitdown.core.models import ConversionConfig, ConversionResult, ExtractedNote, VisualAsset
from omni_markitdown.engines.base import BaseEngine
from omni_markitdown.engines.ocr_engine import (
    INSTALL_HINT,
    OcrUnavailableError,
    is_ocr_available,
    ocr_images_to_markdown,
)
from omni_markitdown.utils.assets import save_visual_asset
from omni_markitdown.utils.file_guard import verify_file_readable
from omni_markitdown.utils.pdf_text import (
    BULLET_RE,
    Paragraph,
    PLine,
    assemble_lines,
    build_paragraphs,
    merge_broken_paragraphs,
)
from omni_markitdown.utils.ocr_check import extract_check_items
from omni_markitdown.utils.pdf_annotations import attach_annotations, collect_annotations, free_text_rects
from omni_markitdown.utils.reading_order import xy_cut_order

BBox = Tuple[float, float, float, float]
logger = logging.getLogger("omni_markitdown")

PAGE_NUMBER_RE = re.compile(
    r"^[\s\-–—－‐(（\[]*(p\.?\s*)?(\d{1,4}|[ivxlcdm]{1,6})(\s*[/／]\s*\d{1,4})?[\s\-–—－‐)）\]]*$",
    re.IGNORECASE,
)
MIN_IMAGE_PX = 24          # これより小さい画像はアイコン・飾りとみなして捨てる
MARGIN_RATIO = 0.08        # ページ上下 8% をヘッダー・フッターの候補領域とする


@dataclass
class _Item:
    """ページ上に置く要素（段落・表・画像）"""
    kind: str  # text / table / image
    bbox: BBox
    markdown: str
    size: float = 0.0
    para: Optional[Paragraph] = None


def _norm_repeat_key(text: str) -> str:
    """ヘッダー・フッター判定用に、数字を伏せて比較できる形にする"""
    return re.sub(r"\d+", "#", re.sub(r"\s+", "", text))


def _cell(v) -> str:
    return ("" if v is None else str(v)).strip().replace("\n", "<br>").replace("|", "\\|")


def _table_to_markdown(rows) -> str:
    """表のセル配列を Markdown の表にする。全行が空の列・行は捨てる"""
    rows = [[_cell(c) for c in r] for r in rows if r]
    rows = [r for r in rows if any(r)]
    if len(rows) < 2:
        return ""
    width = max(len(r) for r in rows)
    rows = [r + [""] * (width - len(r)) for r in rows]
    keep = [j for j in range(width) if any(r[j] for r in rows)]
    if len(keep) < 2:
        return ""
    rows = [[r[j] for j in keep] for r in rows]
    out = ["| " + " | ".join(rows[0]) + " |", "| " + " | ".join("---" for _ in keep) + " |"]
    out += ["| " + " | ".join(r) + " |" for r in rows[1:]]
    return "\n".join(out)


def _ocr_dpi(page, config: ConversionConfig) -> int:
    """OCRに渡す解像度。元のスキャンが細かくても上げない。
    ndlocr-lite は画像を 1024px / 行の高さ24px に縮めて読むため、細かくしても得にならず、
    実測では 320dpi で誤りが増えた（官公庁のPDFで 150dpi 0.38% / 200dpi 0.40% / 320dpi 1.37%）"""
    return config.pdf_ocr_dpi


def _drop_repeated_paragraphs(pages: Dict[int, str]) -> Dict[int, str]:
    """半分以上のページに出る段落（透かし・柱・ページ番号）を取り除く（3ページ以上のとき）"""
    if len(pages) < 3:
        return pages
    sep = "\n\n"
    key = lambda p: re.sub(r"[\d０-９\s]", "", p)
    counts: Counter = Counter()
    for md in pages.values():
        counts.update({key(p) for p in md.split(sep) if key(p)})
    limit = max(3, len(pages) // 2)
    # 長い段落は本文なので消さない（透かし・柱・ページ番号は短い）
    frequent = {k for k, c in counts.items() if c >= limit and len(k) <= 80}
    if not frequent:
        return pages
    return {i: sep.join(p for p in md.split(sep) if key(p) not in frequent) for i, md in pages.items()}


PAGE_LINK_PREFIX = "[📄 原本"


def _stitch_pages(pages: List[str]) -> List[str]:
    """前のページが文の途中で終わっていたら、次のページの最初の段落を前のページへ戻してつなぐ。
    ページ区切り（---）はそのまま残す"""
    out: List[str] = []
    for md in pages:
        paras = md.split("\n\n")
        # 先頭の「原本ページへのリンク」はつなぎ判定から外して、そのまま先頭に残す
        lead = []
        while paras and paras[0].startswith(PAGE_LINK_PREFIX):
            lead.append(paras.pop(0))
        if out and paras:
            prev = out[-1].split("\n\n")
            merged = merge_broken_paragraphs([prev[-1], paras[0]])
            if len(merged) == 1:
                out[-1] = "\n\n".join(prev[:-1] + merged)
                paras = paras[1:]
        if lead or paras:
            out.append("\n\n".join(lead + paras))
    return out


def _looks_like_scan(page) -> bool:
    """ページの大半を覆う画像があるか、文字を図形で描いている（線が非常に多い）か"""
    try:
        area = page.rect.width * page.rect.height
        for info in page.get_image_info():
            x0, y0, x1, y1 = info["bbox"]
            if (x1 - x0) * (y1 - y0) >= area * 0.5:
                return True
        return len(page.get_drawings()) >= 200
    except Exception:
        return False


def _is_garbage(text: str) -> bool:
    """制御文字・置換文字・私用領域の文字が3割を超えるなら、壊れた文字の層とみなす"""
    t = text.replace("\n", "").replace(" ", "")
    if len(t) < 20:
        return False
    bad = sum(1 for c in t if ord(c) < 0x20 or c == "�" or 0xE000 <= ord(c) <= 0xF8FF)
    return bad / len(t) > 0.3


class PdfEngine(BaseEngine):
    """PDFファイルから本文・見出し・表・画像・注釈を取り出すエンジン"""

    SUPPORTED_EXTENSIONS = {".pdf"}

    def can_handle(self, path: Path) -> bool:
        return path.suffix.lower() in self.SUPPORTED_EXTENSIONS

    # ------------------------------------------------------------------
    def convert(self, path: Path, config: ConversionConfig, output_dir: Path) -> ConversionResult:
        verify_file_readable(path, config.max_file_size_mb)

        doc = pymupdf.open(str(path))
        try:
            return self._convert_doc(doc, path, config, output_dir)
        finally:
            doc.close()

    def _convert_doc(self, doc, path: Path, config: ConversionConfig, output_dir: Path) -> ConversionResult:
        with open(path, "rb") as f:
            doc_hash = hashlib.sha256(f.read()).hexdigest()[:8]
        total_pages = len(doc)
        warnings: List[str] = []

        # 1回目: 表を見つけ、文字を行に組み立て直し、文字サイズ・余白の行を集める
        page_text_len: List[int] = []
        size_counter: Counter = Counter()
        margin_keys: Counter = Counter()
        page_lines: List[List[PLine]] = []
        page_tables: List[List[Tuple[BBox, str]]] = []
        garbage_pages: List[int] = []
        page_looks_scanned: List[bool] = []
        for page in doc:
            tables = self._find_tables(page)
            exclude = [bb for bb, _ in tables]
            if config.extract_notes:
                # フリーテキスト注釈・スタンプの文字は本文に混ぜない（注釈として別に出す）
                exclude += free_text_rects(page)
            lines = assemble_lines(page, exclude=exclude)
            if _is_garbage("".join(l.text for l in lines)):
                # 壊れた文字の層（前のOCRの失敗などで制御文字だらけ）は無いものとして扱う
                garbage_pages.append(len(page_lines))
                lines, tables = [], []
            page_tables.append(tables)
            page_lines.append(lines)
            h = page.rect.height
            n = 0
            seen_keys = set()
            for ln in lines:
                k = len(ln.text.replace(" ", ""))
                n += k
                size_counter[round(ln.size * 2) / 2] += k
                if ln.bbox[3] <= h * MARGIN_RATIO or ln.bbox[1] >= h * (1 - MARGIN_RATIO):
                    seen_keys.add(_norm_repeat_key(ln.text))
            n += sum(len(md) for _, md in tables)
            margin_keys.update(seen_keys)
            page_text_len.append(n)
            page_looks_scanned.append(_looks_like_scan(page))

        body_size = size_counter.most_common(1)[0][0] if size_counter else 10.0
        heading_sizes = sorted({s for s in size_counter if s >= body_size * 1.15}, reverse=True)
        heading_level = {s: min(i + 1, 3) for i, s in enumerate(heading_sizes)}
        # 3ページ以上あって半分以上のページの余白に出る行はヘッダー・フッター
        repeat_keys = (
            {k for k, c in margin_keys.items() if c >= max(2, total_pages // 2)} if total_pages >= 3 else set()
        )

        # どのページをOCRするか
        # 文字が少なくても、文字の層があってスキャン画像が無いページ（章の扉など）は OCR しない。
        # OCR すると正しい文字を OCR の推測で上書きしてしまうため
        scanned = [
            n == 0 or (n < config.scanned_text_threshold and page_looks_scanned[i])
            for i, n in enumerate(page_text_len)
        ]
        ocr_targets = [i for i in range(total_pages) if config.enable_ocr or (config.auto_ocr and scanned[i])]
        ocr_ok = is_ocr_available(config)
        if ocr_targets and not ocr_ok:
            if config.enable_ocr:
                raise OcrUnavailableError(INSTALL_HINT)
            if any(scanned) and config.auto_ocr:
                warnings.append(
                    f"文字の無いページ（スキャン）が {sum(scanned)} ページありますが、"
                    f"OCRエンジンが無いため読み取っていません。{INSTALL_HINT}"
                )
            ocr_targets = []
        ocr_md: Dict[int, str] = {}
        if ocr_targets:
            ocr_md = self._ocr_pages(doc, ocr_targets, config)

        pages_md: List[str] = []
        all_assets: List[VisualAsset] = []
        all_notes: List[ExtractedNote] = []
        saved_xrefs: Dict[int, VisualAsset] = {}
        check_items: List[Dict] = []

        for page_idx, page in enumerate(doc):
            page_num = page_idx + 1
            prect = page.rect
            items: List[_Item] = []

            # 表
            if page_idx not in ocr_md:
                for bb, md in page_tables[page_idx]:
                    items.append(_Item("table", bb, md))

            # 本文
            if page_idx in ocr_md:
                if ocr_md[page_idx]:
                    items.append(_Item("text", (0, 0, prect.width, prect.height), ocr_md[page_idx]))
            else:
                h = prect.height
                kept = []
                for ln in page_lines[page_idx]:
                    in_margin = ln.bbox[3] <= h * MARGIN_RATIO or ln.bbox[1] >= h * (1 - MARGIN_RATIO)
                    if in_margin and (_norm_repeat_key(ln.text) in repeat_keys or PAGE_NUMBER_RE.match(ln.text)):
                        continue  # ヘッダー・フッター・ページ番号
                    kept.append(ln)
                for para in build_paragraphs(kept):
                    items.append(_Item("text", para.bbox, "", size=para.size, para=para))

            # 画像（位置つき）
            if config.extract_images:
                for info in page.get_image_info(xrefs=True):
                    xref = info.get("xref") or 0
                    bb = tuple(info["bbox"])
                    w_pt, h_pt = bb[2] - bb[0], bb[3] - bb[1]
                    if xref <= 0 or w_pt < MIN_IMAGE_PX or h_pt < MIN_IMAGE_PX:
                        continue
                    # OCRしたページの全面スキャン画像は保存しない
                    if page_idx in ocr_md and w_pt * h_pt > prect.width * prect.height * 0.5:
                        continue
                    asset = saved_xrefs.get(xref)
                    if asset is None:
                        try:
                            base = doc.extract_image(xref)
                        except Exception:
                            continue
                        if not base or base.get("width", 0) < MIN_IMAGE_PX or base.get("height", 0) < MIN_IMAGE_PX:
                            continue
                        asset = save_visual_asset(
                            image_bytes=base["image"], doc_hash=doc_hash, page_number=page_num,
                            image_index=len([a for a in all_assets if a.page_number == page_num]) + 1,
                            output_dir=output_dir, assets_dir_name=config.assets_dir,
                            ext=base.get("ext", "png"), bbox=bb,
                            width=base.get("width"), height=base.get("height"),
                        )
                        saved_xrefs[xref] = asset
                        all_assets.append(asset)
                    items.append(_Item("image", bb, f"![{asset.asset_id}]({asset.rel_path})"))

            # 読み順に並べて Markdown 化
            ordered = xy_cut_order(items, lambda it: it.bbox, vertical=False)
            parts = [(it.bbox, self._render_item(it, heading_level, body_size)) for it in ordered]
            parts = [(bb, md) for bb, md in parts if md]

            # 注釈: 対象の段落（重なる、または縦に最も近い段落）の直後に置く
            if config.extract_notes:
                annots = collect_annotations(page, page_num)
                for an in annots:
                    all_notes.extend(an.notes)
                page_parts = attach_annotations(parts, annots)
            else:
                page_parts = [md for _, md in parts]

            # OCRしたページ: 原本ページ画像へのリンクと、照合リストの項目
            if page_idx in ocr_md:
                if config.ocr_page_links:
                    link = self._save_page_image(page, page_num, doc_hash, output_dir, config)
                    if link:
                        page_parts.insert(0, link)
                check_items.extend(extract_check_items(ocr_md[page_idx], page_num))

            pages_md.append("\n\n".join(page_parts))

        full_markdown = "\n\n---\n\n".join(_stitch_pages([p for p in pages_md if p.strip()])).strip()
        if garbage_pages:
            warnings.append(f"{len(garbage_pages)} ページの文字の層が壊れていた（制御文字など）ため、使わずに捨てました。")
        if warnings:
            full_markdown = "\n".join(f"> ⚠️ {w}" for w in warnings) + "\n\n" + full_markdown

        return ConversionResult(
            markdown=full_markdown,
            assets=all_assets,
            notes=all_notes,
            source_path=path,
            metadata={
                "format": "pdf",
                "pages_count": total_pages,
                "is_scanned_likely": any(scanned),
                "scanned_pages": [i + 1 for i, s in enumerate(scanned) if s],
                "ocr_pages": sorted(i + 1 for i in ocr_md),
                "text_length": sum(page_text_len),
                "garbage_text_pages": [i + 1 for i in garbage_pages],
                "warnings": warnings,
                "ocr_check": check_items,
            },
        )

    # ------------------------------------------------------------------
    @staticmethod
    def _save_page_image(page, page_num: int, doc_hash: str, output_dir: Path, config: ConversionConfig) -> str:
        """照合用に原本ページを JPEG（120dpi）で保存し、Markdown のリンクを返す"""
        try:
            folder = output_dir / config.assets_dir
            folder.mkdir(parents=True, exist_ok=True)
            name = f"page_p{page_num:03d}_{doc_hash}.jpg"
            target = folder / name
            if not target.exists():
                target.write_bytes(page.get_pixmap(dpi=120).tobytes(output="jpg", jpg_quality=75))
            return f"{PAGE_LINK_PREFIX} p.{page_num}]({config.assets_dir}/{name})"
        except Exception as e:
            logger.warning("原本ページ画像を保存できませんでした (p.%d): %s", page_num, e)
            return ""

    @staticmethod
    def _find_tables(page) -> List[Tuple[BBox, str]]:
        """罫線のあるページだけ表を探す（表検出は重いため）"""
        try:
            if len(page.get_drawings()) < 4:
                return []
            found = page.find_tables().tables
        except Exception:
            return []
        out = []
        for t in found:
            try:
                md = _table_to_markdown(t.extract())
            except Exception:
                continue
            if md and len(t.rows) >= 2:
                out.append((tuple(t.bbox), md))
        return out

    @staticmethod
    def _render_item(it: _Item, heading_level: Dict[float, int], body_size: float) -> str:
        if it.kind != "text" or it.para is None:
            return it.markdown

        text = it.para.text
        size_key = round(it.size * 2) / 2
        # 見出し: 本文より大きい文字の短い段落
        if size_key in heading_level and len(text) <= 80:
            return "#" * heading_level[size_key] + " " + text
        if BULLET_RE.match(text):
            return "- " + BULLET_RE.sub("", text, count=1)
        return text

    @staticmethod
    def _ocr_pages(doc, targets: List[int], config: ConversionConfig) -> Dict[int, str]:
        """指定ページを画像にして ndlocr-lite で OCR する（16ページずつ。進み具合をログに出す）"""
        result: Dict[int, str] = {}
        chunk = 16
        for start in range(0, len(targets), chunk):
            part = targets[start:start + chunk]
            with tempfile.TemporaryDirectory(prefix="omni_pdfocr_") as tmp:
                imgs = []
                for i in part:
                    p = Path(tmp) / f"page{i + 1:05d}.png"
                    doc[i].get_pixmap(dpi=_ocr_dpi(doc[i], config)).save(str(p))
                    imgs.append(p)
                mds = ocr_images_to_markdown(imgs, config)
            result.update(zip(part, mds))
            logger.info("OCR %d / %d ページ", min(start + chunk, len(targets)), len(targets))
        return _drop_repeated_paragraphs(result)
