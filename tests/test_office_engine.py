"""OfficeEngine の単体テスト (TDD)
"""

from pathlib import Path
import pytest
import openpyxl

from omni_markitdown.core.models import ConversionConfig
from omni_markitdown.engines.office_engine import OfficeEngine


@pytest.fixture
def sample_xlsx(tmp_path: Path) -> Path:
    """テスト用の Excel ファイルを作成"""
    xlsx_path = tmp_path / "test_table.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "項目一覧"

    ws.append(["番号", "項目名", "重要度", "参照"])
    ws.append([1, "標本調査", "A", "要領246条"])
    ws.append([2, "全数調査", "S", "資料"])
    ws.append([3, "抽出調査", "B", "要領267条"])

    wb.save(str(xlsx_path))
    return xlsx_path


def test_office_can_handle(sample_xlsx: Path):
    engine = OfficeEngine()
    assert engine.can_handle(sample_xlsx) is True
    assert engine.can_handle(Path("presentation.pptx")) is True
    assert engine.can_handle(Path("page.html")) is True
    assert engine.can_handle(Path("document.docx")) is False  # DocxはDocxEngine担当


def test_office_convert_xlsx(sample_xlsx: Path, tmp_path: Path):
    engine = OfficeEngine()
    config = ConversionConfig()
    result = engine.convert(sample_xlsx, config, tmp_path)

    # Markdown テーブル形式で出力されているか検証
    assert "標本調査" in result.markdown
    assert "全数調査" in result.markdown
    assert "要領246条" in result.markdown
    assert "|" in result.markdown  # テーブルのパイプ区切り
