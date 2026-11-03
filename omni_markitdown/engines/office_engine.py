"""OfficeEngine: Microsoft MarkItDown 委譲エンジン (LLM外部通信完全無効化)
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from omni_markitdown.core.models import ConversionConfig, ConversionResult
from omni_markitdown.engines.base import BaseEngine
from omni_markitdown.utils.file_guard import verify_file_readable


class OfficeEngine(BaseEngine):
    """MarkItDown を活用して XLSX, PPTX, HTML, EPUB, CSV, JSON 等を処理するエンジン"""

    SUPPORTED_EXTENSIONS = {
        ".pptx",
        ".xlsx", ".xls", ".csv",
        ".html", ".htm",
        ".epub",
        ".json", ".xml",
        ".zip"
    }

    def __init__(self):
        self._md_instance = None

    def _get_markitdown(self):
        if self._md_instance is None:
            from markitdown import MarkItDown
            # 外部LLM連携は完全無効化 (llm_client=None)
            self._md_instance = MarkItDown(llm_client=None)
        return self._md_instance

    def can_handle(self, path: Path) -> bool:
        return path.suffix.lower() in self.SUPPORTED_EXTENSIONS

    def convert(self, path: Path, config: ConversionConfig, output_dir: Path) -> ConversionResult:
        verify_file_readable(path, config.max_file_size_mb)

        md = self._get_markitdown()
        converted = md.convert(str(path))

        text_content = converted.text_content if hasattr(converted, "text_content") else str(converted)

        return ConversionResult(
            markdown=text_content.strip(),
            source_path=path,
            metadata={
                "format": path.suffix.lower().replace(".", ""),
                "title": getattr(converted, "title", None)
            }
        )
