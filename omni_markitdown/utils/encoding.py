"""Windows / PowerShell 環境のエンコーディング保護
"""

import sys


def setup_utf8_encoding() -> None:
    """標準入出力を UTF-8 に再設定（CP932文字化け・クラッシュ防止）"""
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass
    if hasattr(sys.stderr, "reconfigure"):
        try:
            sys.stderr.reconfigure(encoding="utf-8")
        except Exception:
            pass
