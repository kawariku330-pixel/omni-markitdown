"""PdfEngine の単体テスト (TDD)
"""

from pathlib import Path
import pytest
import fitz  # PyMuPDF
from PIL import Image

from omni_markitdown.core.models import ConversionConfig
from omni_markitdown.engines.pdf_engine import PdfEngine


@pytest.fixture
def sample_pdf_with_image(tmp_path: Path) -> Path:
    """テキストと画像を含むテスト用 PDF を作成"""
    pdf_path = tmp_path / "test_sample.pdf"
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)  # A4

    # 日本語フォント (japan) を指定してテキスト挿入
    p1 = fitz.Point(50, 72)
    page.insert_text(p1, "第1回 講義ノート", fontname="japan", fontsize=18)
    
    p2 = fitz.Point(50, 110)
    page.insert_text(p2, "本文: 調査結果の第13項についての検討。", fontname="japan", fontsize=12)

    # テスト画像を生成して挿入
    img_path = tmp_path / "sample_chart.png"
    img = Image.new("RGB", (100, 100), color="blue")
    img.save(str(img_path))

    rect = fitz.Rect(50, 150, 250, 350)
    page.insert_image(rect, filename=str(img_path))

    # 注釈（ハイライト／コメント）を挿入
    annot = page.add_text_annot(fitz.Point(50, 380), "講師コメント: ここは二つの見解の対立に注意すること。")
    annot.update()

    doc.save(str(pdf_path))
    doc.close()
    return pdf_path


def test_pdf_can_handle(sample_pdf_with_image: Path):
    engine = PdfEngine()
    assert engine.can_handle(sample_pdf_with_image) is True
    assert engine.can_handle(Path("dummy.docx")) is False


def test_pdf_convert_extract_text_and_assets(sample_pdf_with_image: Path, tmp_path: Path):
    engine = PdfEngine()
    config = ConversionConfig(extract_images=True, extract_notes=True, assets_dir="_assets")
    result = engine.convert(sample_pdf_with_image, config, tmp_path)

    # 1. 本文テキストの抽出検証
    assert "第1回 講義ノート" in result.markdown
    assert "調査結果の第13項" in result.markdown

    # 2. 注釈（コメント）の抽出検証
    assert "講師コメント" in result.markdown
    assert len(result.notes) >= 1

    # 3. 画像アセット切り出しとMarkdownリンクの検証
    assert len(result.assets) >= 1
    asset = result.assets[0]
    assert asset.file_path.exists()
    assert "_assets" in result.markdown
    assert "![" in result.markdown
