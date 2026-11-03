"""MCP サーバー ツールのテスト (TDD)
"""

from pathlib import Path
import pytest
from docx import Document

from omni_markitdown.mcp_server import convert_to_markdown, inspect_document


@pytest.fixture
def mcp_docx_file(tmp_path: Path) -> Path:
    doc_path = tmp_path / "mcp_test.docx"
    doc = Document()
    doc.add_heading("論点: 標本の偏り", level=1)
    doc.add_paragraph("調査要領第142条についての検討。")
    doc.save(str(doc_path))
    return doc_path


def test_mcp_convert_to_markdown(mcp_docx_file: Path):
    """convert_to_markdown ツールの動作検証"""
    text = convert_to_markdown(str(mcp_docx_file))
    assert "標本の偏り" in text
    assert "調査要領第142条" in text


def test_mcp_inspect_document(mcp_docx_file: Path):
    """inspect_document ツールのメタデータ取得検証"""
    info = inspect_document(str(mcp_docx_file))
    assert "ドキュメント概要" in info
    assert "mcp_test.docx" in info
