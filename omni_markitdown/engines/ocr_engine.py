"""OcrEngine: ndlocr-lite (国立国会図書館) による日本語文献・縦書き・多段組OCR

ndlocr-lite の読み取り部分とモデルを omni_markitdown/_vendor/ndlocr_lite に同封している
（CC BY 4.0。ライセンスは同フォルダの LICENCE / LICENCE_DEPENDENCIES / NOTICE.md）。

    pip install -e ".[ocr]"   # 同封版が使う部品（opencv など）を入れる

同封版は外部プロセス（本体と同じ Python）で動かす。ndlocr-lite のモジュール名（ocr, config, model）が
一般的なので、本体のプロセスに読み込むと名前がぶつかるため。部品が無いときは、別に入れた
`ndlocr-lite` コマンド（uv tool install git+https://github.com/ndl-lab/ndlocr-lite）も使える。

出力XMLの LINE 要素（STRING / TYPE / ORDER / X / Y / WIDTH / HEIGHT）を読み、
ORDER（ndlocr-lite の XY-cut による読み順）に並べて Markdown にする。
"""

from __future__ import annotations

import importlib.util
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from omni_markitdown.core.models import ConversionConfig, ConversionResult
from omni_markitdown.engines.base import BaseEngine
from omni_markitdown.utils.file_guard import verify_file_readable
from omni_markitdown.utils.ocr_check import extract_check_items
from omni_markitdown.utils.pdf_text import merge_broken_paragraphs, normalize_ocr_punctuation
from omni_markitdown.utils.reading_order import xy_cut_order

INSTALL_HINT = (
    "OCRエンジン（ndlocr-lite）が使えません。同封版を使うには "
    "pip install -e \".[ocr]\" で部品を入れてください"
    "（または uv tool install git+https://github.com/ndl-lab/ndlocr-lite / 環境変数 OMNI_NDLOCR_CMD）"
)

# 本文として出さない領域（柱=欄外の書名・章名、ノンブル=ページ番号、ルビ）
SKIP_TYPES = {"柱", "ノンブル", "ルビ", "block_pillar", "block_folio", "block_rubi"}
TITLE_TYPES = {"タイトル本文", "line_title", "title"}
# 「。」の直後の 1〜2桁の数字＋日本語（数字の後が年・条・円などの単位なら段落番号ではない）
SECTION_NUMBER_SPLIT_RE = re.compile(
    r"(?<=。)(?=[0-9０-９]{1,2}(?![0-9０-９年月日条項号巻頁人円万千百件回名歳時分秒％%・.．,，])[぀-ヿ㐀-鿿（(「])"
)


class OcrUnavailableError(RuntimeError):
    """OCRエンジンが使えないときのエラー"""


@dataclass
class TextBlock:
    """OCRで読み取った1行（または1ブロック）"""
    text: str
    bbox: Tuple[float, float, float, float]  # (x0, y0, x1, y1)
    is_vertical: bool = False
    confidence: float = 1.0
    kind: str = "body"  # body / title
    order: Optional[float] = None
    group: Optional[int] = None  # 同じ本文ブロックに属する行は同じ番号


def sort_blocks_reading_order(blocks: List[TextBlock], is_vertical: Optional[bool] = None) -> List[TextBlock]:
    """ブロックを読み順に並べる

    ndlocr-lite が読み順（ORDER）を付けていればそれに従う。
    無ければ XY-cut で段組・縦書きを考慮して並べる。
    is_vertical を省略すると、縦長の行が過半数かどうかで判定する。
    """
    if not blocks:
        return []
    if all(b.order is not None for b in blocks):
        return sorted(blocks, key=lambda b: b.order)
    if is_vertical is None:
        is_vertical = sum(1 for b in blocks if b.is_vertical) > len(blocks) / 2
    return xy_cut_order(blocks, lambda b: b.bbox, vertical=is_vertical)


# --------------------------------------------------------------------------
# ndlocr-lite の呼び出し
# --------------------------------------------------------------------------

BUNDLED_OCR_SCRIPT = Path(__file__).resolve().parent.parent / "_vendor" / "ndlocr_lite" / "ocr.py"
BUNDLED_MODEL_FILES = {
    "--det-weights": ("model", "deim-s-1024x1024.onnx"),
    "--det-classes": ("config", "ndl.yaml"),
    "--rec-weights30": ("model", "parseq-ndl-24x256-30-tiny-189epoch-tegaki3-r8data-202604.onnx"),
    "--rec-weights50": ("model", "parseq-ndl-24x384-50-tiny-300epoch-tegaki3-r8data-202604.onnx"),
    "--rec-weights": ("model", "parseq-ndl-24x768-100-tiny-153epoch-tegaki3-r8data-202604.onnx"),
    "--rec-classes": ("config", "NDLmoji.yaml"),
}
# Windows は長いパスの許可が無いと、260文字を超えるパスのファイルを開けない。
# モデル名が長いので、深いフォルダ（OneDrive の下など）に置くと超えやすい
WINDOWS_MAX_PATH = 259


def windows_long_path(path: Path) -> str:
    """Windows で 260 文字を超えるパスに \\\\?\\ を付けて、上限なしで開けるようにする"""
    s = str(path)
    if os.name == "nt" and len(s) > WINDOWS_MAX_PATH and not s.startswith("\\\\?\\"):
        if s.startswith("\\\\"):  # ネットワークドライブ \\server\share
            return "\\\\?\\UNC\\" + s[2:]
        return "\\\\?\\" + s
    return s


def bundled_model_args() -> List[str]:
    """同封のモデル・設定ファイルを、長いパス対策をしたうえで明示的に渡す"""
    base = BUNDLED_OCR_SCRIPT.parent
    args: List[str] = []
    for flag, parts in BUNDLED_MODEL_FILES.items():
        args += [flag, windows_long_path(base.joinpath(*parts))]
    return args
# 同封版の ndlocr-lite（画像の読み取り部分）が使う外部パッケージ
BUNDLED_OCR_MODULES = ("numpy", "onnxruntime", "cv2", "PIL", "yaml", "lxml", "tqdm", "networkx")


def bundled_ocr_ready() -> bool:
    """同封版を動かせるか（スクリプトと部品がそろっているか）"""
    if not BUNDLED_OCR_SCRIPT.exists():
        return False
    return all(importlib.util.find_spec(m) is not None for m in BUNDLED_OCR_MODULES)


def find_ndlocr_command(config: Optional[ConversionConfig] = None) -> Optional[List[str]]:
    """ndlocr-lite の実行コマンドを探す。見つからなければ None

    優先順: 設定 ndlocr_command → 環境変数 OMNI_NDLOCR_CMD → 同封版 → PATH 上の ndlocr-lite
    """
    raw = (config.ndlocr_command if config else None) or os.environ.get("OMNI_NDLOCR_CMD")
    if raw:
        parts = shlex.split(raw, posix=(os.name != "nt"))
        # Windows では posix=False のため "..." の引用符が残るので外す
        return [p[1:-1] if len(p) >= 2 and p[0] == p[-1] and p[0] in "\"'" else p for p in parts]
    # 同封版: `pip install omni-markitdown[ocr]` で部品がそろっていれば、本体と同じ Python で動かす
    if bundled_ocr_ready():
        return [sys.executable, str(BUNDLED_OCR_SCRIPT)] + bundled_model_args()
    exe = shutil.which("ndlocr-lite")
    if exe:
        return [exe]
    return None


def is_ocr_available(config: Optional[ConversionConfig] = None) -> bool:
    return find_ndlocr_command(config) is not None


def _is_cjk(ch: str) -> bool:
    cp = ord(ch)
    return (0x3040 <= cp <= 0x30FF or 0x3400 <= cp <= 0x9FFF
            or 0xF900 <= cp <= 0xFAFF or 0xFF00 <= cp <= 0xFFEF or 0x3000 <= cp <= 0x303F)


def _join_lines(lines: Sequence[str]) -> str:
    """同じ段落の行をつなぐ。日本語どうしは空白なし、英単語どうしは空白1つ"""
    out = ""
    for ln in (l.strip() for l in lines):
        if not ln:
            continue
        if out and not _is_cjk(out[-1]) and not _is_cjk(ln[0]) and out[-1].isalnum() and ln[0].isalnum():
            out += " "
        out += ln
    return out


def parse_ndlocr_xml(xml_text: str) -> List[TextBlock]:
    """ndlocr-lite の出力XMLから行を取り出す"""
    root = ET.fromstring(xml_text)
    parent: Dict[ET.Element, ET.Element] = {c: p for p in root.iter() for c in p}
    group_ids: Dict[int, int] = {}
    blocks: List[TextBlock] = []

    for line in root.iter("LINE"):
        text = (line.get("STRING") or "").strip()
        if not text:
            continue
        line_type = (line.get("TYPE") or "").strip()

        # 祖先のブロックの種類も見る（柱・ノンブルの中の行は捨てる）
        anc = parent.get(line)
        container = None
        skip = line_type in SKIP_TYPES
        while anc is not None and anc.tag not in ("PAGE", "OCRDATASET"):
            if (anc.get("TYPE") or "") in SKIP_TYPES:
                skip = True
            if container is None and anc.tag in ("TEXTBLOCK", "BLOCK"):
                container = anc
            anc = parent.get(anc)
        if skip:
            continue

        try:
            x, y = float(line.get("X")), float(line.get("Y"))
            w, h = float(line.get("WIDTH")), float(line.get("HEIGHT"))
        except (TypeError, ValueError):
            continue
        try:
            order = float(line.get("ORDER")) if line.get("ORDER") is not None else None
        except ValueError:
            order = None
        try:
            conf = float(line.get("CONF") or 1.0)
        except ValueError:
            conf = 1.0

        kind = "title" if (line_type in TITLE_TYPES or "タイトル" in line_type) else "body"
        group = group_ids.setdefault(id(container), len(group_ids)) if container is not None else None
        blocks.append(TextBlock(text=text, bbox=(x, y, x + w, y + h), is_vertical=h > w,
                                confidence=conf, kind=kind, order=order, group=group))
    return blocks


def blocks_to_markdown(blocks: List[TextBlock]) -> str:
    """読み順に並んだ行を、見出しと段落にまとめて Markdown にする"""
    paras: List[str] = []
    cur: List[str] = []
    cur_key = None

    def flush():
        if cur:
            text = _join_lines(cur)
            if text:
                paras.append(f"## {text}" if cur_key and cur_key[0] == "title" else text)
        cur.clear()

    for b in blocks:
        # 本文ブロックに属さない行は1行ずつ別の段落にする
        key = (b.kind, b.group if b.group is not None else f"solo{id(b)}")
        if key != cur_key:
            flush()
            cur_key = key
        cur.append(b.text)
    flush()
    paras = merge_broken_paragraphs([normalize_ocr_punctuation(p) for p in paras])
    # 「…注目される。2本件の事案は」のように、文末の直後に段落番号が来たらそこで段落を分ける
    split: List[str] = []
    for p in paras:
        split.extend(x for x in SECTION_NUMBER_SPLIT_RE.split(p) if x)
    paras = split
    return "\n\n".join(paras)


def run_ndlocr(images: Sequence[Path], config: ConversionConfig, timeout: Optional[int] = None) -> Dict[Path, List[TextBlock]]:
    """画像をまとめて ndlocr-lite にかけ、画像ごとの行リストを返す（モデルの読み込みは1回）"""
    cmd = find_ndlocr_command(config)
    if cmd is None:
        raise OcrUnavailableError(INSTALL_HINT)

    if timeout is None:
        timeout = 300 + 120 * len(images)  # モデル読み込み + 1枚あたり最大2分
    results: Dict[Path, List[TextBlock]] = {}
    with tempfile.TemporaryDirectory(prefix="omni_ocr_") as tmp:
        tmp_p = Path(tmp)
        src = tmp_p / "src"
        out = tmp_p / "out"
        src.mkdir()
        out.mkdir()
        # ファイル名の重複・全角文字を避けるため、連番の名前でコピーしてから渡す
        names: Dict[str, Path] = {}
        for i, img in enumerate(images):
            name = f"img{i:05d}{img.suffix.lower()}"
            shutil.copyfile(img, src / name)
            names[Path(name).stem] = img

        proc = subprocess.run(
            cmd + ["--sourcedir", str(src), "--output", str(out)],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout,
        )
        if proc.returncode != 0:
            tail = (proc.stderr or proc.stdout or "").strip()[-800:]
            raise RuntimeError(f"ndlocr-lite の実行に失敗しました (exit {proc.returncode}): {tail}")

        for stem, original in names.items():
            xml_p = out / f"{stem}.xml"
            if xml_p.exists():
                results[original] = parse_ndlocr_xml(xml_p.read_text(encoding="utf-8"))
            else:
                results[original] = []
    return results


def ocr_images_to_markdown(images: Sequence[Path], config: ConversionConfig) -> List[str]:
    """画像ごとに OCR した Markdown を返す（images と同じ順）"""
    raw = run_ndlocr(images, config)
    return [blocks_to_markdown(sort_blocks_reading_order(raw.get(img, []))) for img in images]


# --------------------------------------------------------------------------
# 画像ファイル用エンジン
# --------------------------------------------------------------------------

class OcrEngine(BaseEngine):
    """画像ファイル（スキャン画像・写真）を ndlocr-lite で文字にするエンジン"""

    SUPPORTED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"}

    def can_handle(self, path: Path) -> bool:
        return path.suffix.lower() in self.SUPPORTED_EXTENSIONS

    def convert(self, path: Path, config: ConversionConfig, output_dir: Path) -> ConversionResult:
        verify_file_readable(path, config.max_file_size_mb)

        if not is_ocr_available(config) or not (config.enable_ocr or config.auto_ocr):
            if config.enable_ocr:
                raise OcrUnavailableError(INSTALL_HINT)
            # OCRが無いときは、偽の文字を出さず、画像の参照と警告だけを返す
            warning = "OCRエンジン（ndlocr-lite）が無いため、画像内の文字は読み取っていません。"
            try:
                rel = Path(os.path.relpath(path, output_dir)).as_posix()
            except ValueError:  # Windows でドライブが違う場合
                rel = path.as_uri()
            md = f"![{path.stem}]({rel})\n\n> ⚠️ {warning}"
            return ConversionResult(
                markdown=md, source_path=path,
                metadata={"format": "image", "ocr": False, "warnings": [warning + " " + INSTALL_HINT]},
            )

        blocks = sort_blocks_reading_order(run_ndlocr([path], config).get(path, []))
        md = blocks_to_markdown(blocks)
        if config.ocr_page_links:
            try:
                rel = Path(os.path.relpath(path, output_dir)).as_posix()
            except ValueError:
                rel = path.as_uri()
            md = f"[📄 原本]({rel})\n\n" + md
        return ConversionResult(
            markdown=md,
            source_path=path,
            metadata={
                "format": "ocr",
                "ocr": True,
                "engine": "ndlocr-lite",
                "lines_count": len(blocks),
                "ocr_check": extract_check_items(md, 1),
                "vertical": sum(1 for b in blocks if b.is_vertical) > len(blocks) / 2 if blocks else False,
            },
        )
