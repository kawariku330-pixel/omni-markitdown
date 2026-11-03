"""omni_markitdown データモデル定義
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Tuple


@dataclass
class VisualAsset:
    """抽出された画像・図表アセット情報"""
    asset_id: str
    file_path: Path
    rel_path: str
    page_number: int
    index: int
    sha256: str
    width: Optional[int] = None
    height: Optional[int] = None
    bbox: Optional[Tuple[float, float, float, float]] = None  # (x0, y0, x1, y1)


@dataclass
class ExtractedNote:
    """抽出された脚注・コメント・注釈情報"""
    note_type: Literal["footnote", "comment", "annotation"]
    note_id: str
    content: str
    author: Optional[str] = None
    page_number: Optional[int] = None
    paragraph_index: Optional[int] = None


@dataclass
class ConversionConfig:
    """変換パイプライン設定"""
    extract_images: bool = True
    extract_notes: bool = True
    # True: 画像・PDFを必ずOCRする（OCRが使えなければエラー）
    # False: 画像とスキャンPDFだけ、OCRが使えれば自動でOCRする
    enable_ocr: bool = False
    # False にするとスキャンページ・画像の自動OCRをしない（enable_ocr=True が優先）
    auto_ocr: bool = True
    ocr_engine: str = "ndlocr"
    # ndlocr-lite の実行コマンド。未指定なら環境変数 OMNI_NDLOCR_CMD → PATH 上の ndlocr-lite の順に探す
    ndlocr_command: Optional[str] = None
    pdf_ocr_dpi: int = 200
    # OCRしたページの先頭に、原本ページ画像（_assets/page_pNNN_*.jpg）へのリンクを置く
    ocr_page_links: bool = True
    # OCRで読んだ金額・日付・番号などの照合リスト（<出力名>.ocr_check.md）を書き出す
    ocr_check_list: bool = True
    # 1ページあたりの文字数がこれ未満ならスキャンPDFとみなす
    scanned_text_threshold: int = 20
    enable_audio_transcription: bool = False
    assets_dir: str = "_assets"
    max_file_size_mb: int = 100
    table_style: str = "github"
    model_dir: Optional[str] = None
    save_meta: bool = False


@dataclass
class ConversionResult:
    """変換結果"""
    markdown: str
    assets: List[VisualAsset] = field(default_factory=list)
    notes: List[ExtractedNote] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    source_path: Optional[Path] = None
