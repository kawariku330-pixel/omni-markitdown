"""エンジン基底クラス定義
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import List

from omni_markitdown.core.models import ConversionConfig, ConversionResult


class BaseEngine(ABC):
    """フォーマット別変換エンジンの抽象基底クラス"""

    @abstractmethod
    def can_handle(self, path: Path) -> bool:
        """指定されたファイルを処理可能か判定"""
        pass

    @abstractmethod
    def convert(self, path: Path, config: ConversionConfig, output_dir: Path) -> ConversionResult:
        """ファイルをMarkdownに変換"""
        pass
