"""ファイル保護・原本保護ユーティリティ
"""

import os
from pathlib import Path


def verify_file_readable(path: Path, max_size_mb: int = 100) -> None:
    """ファイルの存在、読み取り権限、ファイルサイズ上限を検証"""
    if not path.exists():
        raise FileNotFoundError(f"ファイルが見つかりません: {path}")
    if not path.is_file():
        raise ValueError(f"指定されたパスは通常のファイルではありません: {path}")
    
    # サイズチェック
    size_bytes = path.stat().st_size
    max_bytes = max_size_mb * 1024 * 1024
    if size_bytes > max_bytes:
        raise ValueError(f"ファイルサイズが上限（{max_size_mb}MB）を超過しています: {size_bytes / (1024*1024):.2f}MB")
