"""OmniConverter: フォーマット自動判定と最適エンジンディスパッチ
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterator, List, Optional, Set

from omni_markitdown.core.models import ConversionConfig, ConversionResult
from omni_markitdown.engines.base import BaseEngine
from omni_markitdown.engines.docx_engine import DocxEngine
from omni_markitdown.engines.pdf_engine import PdfEngine
from omni_markitdown.engines.audio_engine import AudioEngine
from omni_markitdown.engines.office_engine import OfficeEngine
from omni_markitdown.engines.ocr_engine import OcrEngine
from omni_markitdown.utils.encoding import setup_utf8_encoding
from omni_markitdown.utils.file_guard import verify_file_readable
from omni_markitdown.utils.ocr_check import check_list_markdown

TEXT_EXTENSIONS = {".txt", ".md", ".markdown", ".text", ".log"}


def _read_text_any_encoding(path: Path) -> str:
    """UTF-8 → UTF-16(BOM) → CP932 の順に試して読む（Windows の Shift_JIS テキスト対策）"""
    data = path.read_bytes()
    if data.startswith(b"\xef\xbb\xbf"):
        return data[3:].decode("utf-8", errors="replace")
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16", errors="replace")
    for enc in ("utf-8", "cp932"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


class OmniConverter:
    """万能Markdown変換オーケストレーター"""

    def __init__(self, config: Optional[ConversionConfig] = None):
        setup_utf8_encoding()
        self.config = config or ConversionConfig()
        # 優先度順にエンジンを登録
        self.engines: List[BaseEngine] = [
            DocxEngine(),
            PdfEngine(),
            AudioEngine(),
            OfficeEngine(),
            OcrEngine(),
        ]

    def supported_extensions(self) -> Set[str]:
        exts: Set[str] = set(TEXT_EXTENSIONS)
        for e in self.engines:
            exts |= set(getattr(e, "SUPPORTED_EXTENSIONS", ()))
        return exts

    def convert(self, file_path: str | Path, output_dir: Optional[str | Path] = None) -> ConversionResult:
        """指定されたファイルを最適なエンジンで変換して結果を返す"""
        path = Path(file_path).resolve()
        verify_file_readable(path, self.config.max_file_size_mb)

        out_dir = Path(output_dir).resolve() if output_dir else path.parent

        for engine in self.engines:
            if engine.can_handle(path):
                return engine.convert(path, self.config, out_dir)

        # プレーンテキスト/Markdownフォールバック。
        # 対応していないバイナリ（.doc / .ppt など）を文字として読むと意味のない文字が出るので、エラーにする
        if path.suffix.lower() not in TEXT_EXTENSIONS:
            with open(path, "rb") as f:
                head = f.read(8192)
            if b"\x00" in head:
                hint = ""
                if path.suffix.lower() in (".doc", ".ppt", ".xls"):
                    hint = "（Word / PowerPoint で .docx / .pptx に保存し直してください）" if path.suffix.lower() != ".xls" else ""
                raise ValueError(f"対応していない形式です: {path.suffix or '(拡張子なし)'}{hint}")
        return ConversionResult(
            markdown=_read_text_any_encoding(path),
            source_path=path,
            metadata={"format": "plain_text"}
        )

    def iter_supported_files(self, folder: str | Path) -> Iterator[Path]:
        """フォルダ内の変換対象ファイルを順に返す（隠しファイル・Markdown・_assets は除く）"""
        exts = self.supported_extensions() - {".md", ".markdown"}
        root = Path(folder).resolve()
        for p in sorted(root.rglob("*")):
            rel = p.relative_to(root)
            if any(part.startswith((".", "~$")) or part == self.config.assets_dir for part in rel.parts):
                continue
            if p.is_file() and p.suffix.lower() in exts:
                yield p


def convert(file_path: str | Path, output_path: Optional[str | Path] = None, **kwargs) -> ConversionResult:
    """簡易変換関数"""
    config = ConversionConfig(**kwargs)
    converter = OmniConverter(config=config)

    src = Path(file_path).resolve()
    if output_path and Path(output_path).resolve() == src:
        raise ValueError(f"出力先が入力ファイルと同じです（原本を上書きしません）: {src}")

    out_dir = Path(output_path).resolve().parent if output_path else None
    result = converter.convert(src, output_dir=out_dir)

    if output_path:
        out_p = Path(output_path).resolve()
        out_p.parent.mkdir(parents=True, exist_ok=True)
        with open(out_p, "w", encoding="utf-8", newline="\n") as f:
            f.write(result.markdown)
        # OCRしたページがあれば、照合リストを別ファイルに書く（本文には混ぜない）
        items = result.metadata.get("ocr_check") or []
        if items and config.ocr_check_list:
            check_p = out_p.with_name(out_p.stem + ".ocr_check.md")
            with open(check_p, "w", encoding="utf-8", newline="\n") as f:
                f.write(check_list_markdown(items, src.name))
            result.metadata["ocr_check_path"] = str(check_p)

    return result
