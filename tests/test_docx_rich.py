"""Word の書式・リスト・画像・脚注・結合セルのテスト"""

import zipfile
from pathlib import Path

import pytest
from docx import Document
from PIL import Image

from omni_markitdown import convert

W_NS = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'


@pytest.fixture
def rich_docx(tmp_path: Path) -> Path:
    doc = Document()
    doc.add_heading("第1章 総論", 1)
    p = doc.add_paragraph("これは")
    p.add_run("太字").bold = True
    p.add_run("と")
    p.add_run("斜体").italic = True
    p.add_run("です。")
    doc.add_paragraph("箇条書き一", style="List Bullet")
    doc.add_paragraph("箇条書き二", style="List Bullet")
    doc.add_paragraph("番号一", style="List Number")
    doc.add_paragraph("番号二", style="List Number")
    t = doc.add_table(rows=2, cols=3)
    t.cell(0, 0).text, t.cell(0, 1).text, t.cell(0, 2).text = "A", "B", "C"
    t.cell(1, 0).text, t.cell(1, 2).text = "結合", "右"
    t.cell(1, 0).merge(t.cell(1, 1))
    img = tmp_path / "red.png"
    Image.new("RGB", (80, 40), "red").save(img)
    doc.add_picture(str(img))
    path = tmp_path / "rich.docx"
    doc.save(str(path))
    return path


def test_formatting_lists_table_image(rich_docx: Path, tmp_path: Path):
    result = convert(rich_docx, tmp_path / "out" / "rich.md")
    md = result.markdown
    assert "# 第1章 総論" in md
    assert "これは**太字**と*斜体*です。" in md
    assert "- 箇条書き一\n- 箇条書き二" in md
    assert "1. 番号一\n2. 番号二" in md
    assert "| 結合 |  | 右 |" in md  # 横結合の文字は1回だけ
    assert len(result.assets) == 1
    assert (tmp_path / "out" / result.assets[0].rel_path).exists()
    assert f"]({result.assets[0].rel_path})" in md


def _add_notes(src: Path, dst: Path) -> Path:
    """python-docx では脚注を作れないので、XML を直接書き足す"""
    fn = (f'<?xml version="1.0" encoding="UTF-8"?><w:footnotes {W_NS}>'
          '<w:footnote w:type="separator" w:id="-1"><w:p><w:r><w:separator/></w:r></w:p></w:footnote>'
          '<w:footnote w:id="1"><w:p><w:r><w:t>総務省統計（令和元年）参照。</w:t></w:r></w:p></w:footnote></w:footnotes>')
    en = (f'<?xml version="1.0" encoding="UTF-8"?><w:endnotes {W_NS}>'
          '<w:endnote w:id="1"><w:p><w:r><w:t>文末の補足説明。</w:t></w:r></w:p></w:endnote></w:endnotes>')
    with zipfile.ZipFile(src) as zin, zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as zout:
        for it in zin.infolist():
            data = zin.read(it.filename)
            if it.filename == "word/document.xml":
                data = data.decode().replace(
                    "<w:t>本文です。</w:t></w:r>",
                    '<w:t>本文です。</w:t></w:r><w:r><w:footnoteReference w:id="1"/></w:r>'
                    '<w:r><w:endnoteReference w:id="1"/></w:r>', 1).encode()
            elif it.filename == "[Content_Types].xml":
                data = data.decode().replace("</Types>", (
                    '<Override PartName="/word/footnotes.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.footnotes+xml"/>'
                    '<Override PartName="/word/endnotes.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.endnotes+xml"/></Types>')).encode()
            elif it.filename == "word/_rels/document.xml.rels":
                data = data.decode().replace("</Relationships>", (
                    '<Relationship Id="rIdFn" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/footnotes" Target="footnotes.xml"/>'
                    '<Relationship Id="rIdEn" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/endnotes" Target="endnotes.xml"/></Relationships>')).encode()
            zout.writestr(it, data)
        zout.writestr("word/footnotes.xml", fn)
        zout.writestr("word/endnotes.xml", en)
    return dst


def test_footnotes_and_endnotes_inline(tmp_path: Path):
    doc = Document()
    doc.add_paragraph("本文です。")
    src = tmp_path / "plain.docx"
    doc.save(str(src))
    result = convert(_add_notes(src, tmp_path / "notes.docx"))
    md = result.markdown
    assert "本文です。[^1][^e1]" in md
    assert "> 📝 脚注 [^1]: 総務省統計（令和元年）参照。" in md
    assert "> 📝 文末脚注 [^e1]: 文末の補足説明。" in md
    assert len(result.notes) == 2


def test_comment_inline(tmp_path: Path):
    doc = Document()
    p = doc.add_paragraph("コメント対象の文")
    doc.add_comment(p.runs[0], text="ここは要確認", author="作成者A")
    path = tmp_path / "c.docx"
    doc.save(str(path))
    md = convert(path).markdown
    assert "> 💬 コメント [作成者A]: ここは要確認" in md
