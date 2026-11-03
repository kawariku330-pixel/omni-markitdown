"""omni-markitdown Stdio MCP サーバー (MCP 2.x MCPServer 準拠)
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Optional

from mcp.server.mcpserver import MCPServer

from omni_markitdown import __version__
from omni_markitdown.core.converter import OmniConverter
from omni_markitdown.core.models import ConversionConfig

# MCP 2.x サーバーインスタンス
server = MCPServer("omni-markitdown", version=__version__)


@server.tool()
def convert_to_markdown(
    file_path: str,
    extract_images: bool = True,
    extract_notes: bool = True,
    transcribe_audio: bool = False,
    ocr: bool = False,
) -> str:
    """あらゆるファイル（Word, PDF, Excel, PPTX, 音声, 画像, 日本語スキャン文献）を高精度なMarkdownに変換します。

    Args:
        file_path: 変換対象のファイルパス（絶対パスまたは相対パス）
        extract_images: 画像アセットを切り出してMarkdownにリンクするかどうか (デフォルト: True)
        extract_notes: Word/PDFの脚注・コメント・注釈をインライン展開するかどうか (デフォルト: True)
        transcribe_audio: 音声ファイルのローカル文字起こしを行うかどうか (デフォルト: False)
        ocr: 画像・PDFを必ず ndlocr-lite でOCRするかどうか。False でもスキャンページは OCR が使えれば自動でOCRする (デフォルト: False)
    """
    path = Path(file_path).resolve()
    if not path.exists():
        return f"エラー: 指定されたファイルが存在しません: {path}"

    config = ConversionConfig(
        extract_images=extract_images,
        extract_notes=extract_notes,
        enable_audio_transcription=transcribe_audio,
        enable_ocr=ocr,
    )
    try:
        result = OmniConverter(config=config).convert(path)
    except Exception as e:
        return f"エラー: 変換に失敗しました: {e}"

    header = f"# 変換結果: {path.name}\n"
    if result.assets:
        header += f"- 抽出画像アセット: {len(result.assets)} 件\n"
    if result.notes:
        header += f"- 抽出脚注・コメント: {len(result.notes)} 件\n"
    checks = result.metadata.get("ocr_check") or []
    if checks:
        risky = sum(1 for d in checks if d.get("risky"))
        header += f"- OCRで読んだ数字（金額・日付・番号など）: {len(checks)} 件（⚠ {risky} 件）。引用前に原本と照合すること\n"
    for w in result.metadata.get("warnings", []) or []:
        header += f"- ⚠️ {w}\n"
    header += "\n---\n\n"

    return header + result.markdown


@server.tool()
def inspect_document(file_path: str) -> str:
    """ファイルを変換せずに、形式・ページ数・画像数・脚注コメント数などのメタデータ構造を高速に取得します。

    Args:
        file_path: 検査対象のファイルパス
    """
    path = Path(file_path).resolve()
    if not path.exists():
        return f"エラー: 指定されたファイルが存在しません: {path}"

    # 検査では重いOCRは走らせない
    config = ConversionConfig(extract_images=False, extract_notes=True, auto_ocr=False)
    try:
        result = OmniConverter(config=config).convert(path)
    except Exception as e:
        return f"エラー: 読み込みに失敗しました: {e}"

    meta = result.metadata
    info = f"""## ドキュメント概要: {path.name}
- 形式: {meta.get('format', path.suffix)}
- ファイルサイズ: {path.stat().st_size / (1024*1024):.2f} MB
- ページ数: {meta.get('pages_count', 'N/A')}
- 脚注・コメント数: {len(result.notes)} 件
- 抽出テキスト長: {len(result.markdown)} 文字
- スキャン（文字なし）ページ: {meta.get('scanned_pages') or 'なし'}
"""
    return info


def main():
    """Stdio サーバーの起動"""
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
