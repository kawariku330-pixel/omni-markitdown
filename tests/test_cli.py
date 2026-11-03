"""CLI および MCP ツールの統合テスト (TDD)
"""

import subprocess
import sys
from pathlib import Path
import pytest
from docx import Document

from omni_markitdown.core.converter import convert


@pytest.fixture
def sample_docx_file(tmp_path: Path) -> Path:
    doc_path = tmp_path / "cli_test.docx"
    doc = Document()
    doc.add_heading("統計学講義", level=1)
    doc.add_paragraph("第3回 回帰分析の基礎（教科書12頁）。")
    doc.save(str(doc_path))
    return doc_path


def test_cli_convert_execution(sample_docx_file: Path, tmp_path: Path):
    """CLIコマンドライン実行のテスト"""
    out_md = tmp_path / "output.md"
    cmd = [
        sys.executable,
        "-m",
        "omni_markitdown.cli",
        str(sample_docx_file),
        "-o",
        str(out_md)
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    assert res.returncode == 0
    assert out_md.exists()

    content = out_md.read_text(encoding="utf-8")
    assert "統計学講義" in content
    assert "回帰分析の基礎" in content


def test_converter_direct_call(sample_docx_file: Path, tmp_path: Path):
    """Python SDK 直呼び出しのテスト"""
    out_md = tmp_path / "sdk_test.md"
    res = convert(sample_docx_file, output_path=out_md)

    assert res.source_path == sample_docx_file
    assert "統計学講義" in res.markdown
    assert out_md.exists()


def test_cli_markdown_input_does_not_overwrite_original(tmp_path: Path):
    """入力が .md でも原本を上書きしない（.converted.md に出す）"""
    src = tmp_path / "note.md"
    src.write_text("# 原本\n大事なメモ\n", encoding="utf-8")
    res = subprocess.run([sys.executable, "-m", "omni_markitdown.cli", str(src)],
                         capture_output=True, text=True, encoding="utf-8")
    assert res.returncode == 0
    assert src.read_text(encoding="utf-8") == "# 原本\n大事なメモ\n"
    assert (tmp_path / "note.converted.md").exists()


def test_convert_refuses_same_output_path(tmp_path: Path):
    src = tmp_path / "a.md"
    src.write_text("x", encoding="utf-8")
    with pytest.raises(ValueError):
        convert(src, output_path=src)


def test_cli_directory_input(sample_docx_file: Path, tmp_path: Path):
    """ディレクトリを渡すと中の対応ファイルをまとめて変換する"""
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "memo.txt").write_bytes("メモ（Shift_JIS）".encode("cp932"))
    out = tmp_path / "out"
    res = subprocess.run([sys.executable, "-m", "omni_markitdown.cli", str(tmp_path), "-o", str(out)],
                         capture_output=True, text=True, encoding="utf-8")
    assert res.returncode == 0, res.stderr
    assert (out / "cli_test.md").exists()
    assert (out / "sub" / "memo.md").read_text(encoding="utf-8") == "メモ（Shift_JIS）"


def test_unsupported_binary_is_rejected(tmp_path: Path):
    """.doc のような対応していないバイナリは、意味のない文字を出さずにエラーにする"""
    old = tmp_path / "old.doc"
    old.write_bytes(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1\x00\x00binary\x00")
    with pytest.raises(ValueError, match="対応していない形式"):
        convert(old)
