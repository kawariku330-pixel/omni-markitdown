"""DocxEngine の単体テスト (TDD)
"""

from pathlib import Path
import pytest
from docx import Document

from omni_markitdown.core.models import ConversionConfig
from omni_markitdown.engines.docx_engine import DocxEngine


@pytest.fixture
def sample_docx(tmp_path: Path) -> Path:
    """テスト用の Word ドキュメントを作成"""
    doc_path = tmp_path / "test_sample.docx"
    doc = Document()
    doc.add_heading("第1章 調査の目的", level=1)
    
    # 段落
    p1 = doc.add_paragraph("本調査は、対象地域における交通量の変化を把握し、交通計画の見直しに役立てることを目的とする。")
    
    # 見出し2
    doc.add_heading("第1節 観測の方法", level=2)
    p2 = doc.add_paragraph("観測は、平日と休日の各3日間、午前7時から午後7時まで行った（観測要領246条）。")
    
    doc.save(str(doc_path))
    return doc_path


def test_docx_can_handle(sample_docx: Path):
    engine = DocxEngine()
    assert engine.can_handle(sample_docx) is True
    assert engine.can_handle(Path("dummy.pdf")) is False


def test_docx_convert_basic(sample_docx: Path, tmp_path: Path):
    engine = DocxEngine()
    config = ConversionConfig()
    result = engine.convert(sample_docx, config, tmp_path)

    assert "# 第1章 調査の目的" in result.markdown
    assert "## 第1節 観測の方法" in result.markdown
    assert "本調査は" in result.markdown
    assert "観測要領246条" in result.markdown
