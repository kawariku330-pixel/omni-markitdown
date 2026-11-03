"""PDF の注釈（ハイライト・コメント・返信・書き込み・手書き）のテスト"""

from pathlib import Path

import pymupdf
import pytest

from omni_markitdown import convert


@pytest.fixture
def page_doc():
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_font(fontname="jp", fontbuffer=pymupdf.Font("japan").buffer)
    page.insert_text((72, 100), "第一段落の前半です。ここから強調したい部分が始まり", fontname="jp", fontsize=11)
    page.insert_text((72, 116), "ここで強調が終わる。その後ろは強調していない文です。", fontname="jp", fontsize=11)
    page.insert_text((72, 300), "ページ下の別の段落です。", fontname="jp", fontsize=11)
    return doc, page


def _convert(doc, tmp_path: Path):
    path = tmp_path / "annot.pdf"
    doc.save(str(path))
    doc.close()
    return convert(path)


def test_multiline_highlight_takes_only_marked_text(page_doc, tmp_path: Path):
    """2行にまたがる部分ハイライトで、線を引いていない前後の文を取り込まない"""
    doc, page = page_doc
    a = page.search_for("ここから強調したい部分が始まり")[0]
    b = page.search_for("ここで強調が終わる。")[0]
    h = page.add_highlight_annot(quads=[a.quad, b.quad])
    h.set_info(content="重要", title="作成者A")
    h.update()
    md = _convert(doc, tmp_path).markdown
    assert "> 🖍️ ハイライト [作成者A]: 「ここから強調したい部分が始まりここで強調が終わる。」 — 重要" in md
    assert "「第一段落" not in md


def test_annotation_placed_right_after_its_paragraph(page_doc, tmp_path: Path):
    doc, page = page_doc
    h = page.add_highlight_annot(page.search_for("ここで強調が終わる。")[0])
    h.update()
    md = _convert(doc, tmp_path).markdown
    assert md.index("ハイライト") < md.index("ページ下の別の段落です。")


def test_margin_comment_goes_to_nearest_paragraph(page_doc, tmp_path: Path):
    """余白の付箋は、縦に最も近い段落の後ろに置く"""
    doc, page = page_doc
    t = page.add_text_annot((540, 296), "下の段落へのメモ")
    t.set_info(title="作成者B")
    t.update()
    md = _convert(doc, tmp_path).markdown
    assert md.index("ページ下の別の段落です。") < md.index("💬 コメント [作成者B]: 下の段落へのメモ")


def test_replies_are_threaded_under_parent(page_doc, tmp_path: Path):
    doc, page = page_doc
    parent = page.add_text_annot((540, 100), "ここの数字は要確認")
    parent.set_info(title="作成者A")
    parent.update()
    reply = page.add_text_annot((540, 110), "確認しました。資料12頁です")
    reply.set_info(title="作成者C")
    reply.set_irt_xref(parent.xref)
    reply.update()
    result = _convert(doc, tmp_path)
    md = result.markdown
    assert "> 💬 コメント [作成者A]: ここの数字は要確認\n>\n>   ↳ 返信 [作成者C]: 確認しました。資料12頁です" in md
    assert md.count("確認しました") == 1
    assert len(result.notes) == 2


def test_free_text_not_mixed_into_body(page_doc, tmp_path: Path):
    """ページに直接打ち込んだ文字は本文に混ぜず、書き込みとして1回だけ出す"""
    doc, page = page_doc
    ft = page.add_freetext_annot(pymupdf.Rect(300, 285, 520, 310), "打ち込んだメモ", fontsize=9)
    ft.update()
    md = _convert(doc, tmp_path).markdown
    assert "ページ下の別の段落です。\n" in md + "\n"
    assert md.count("打ち込んだメモ") == 1
    assert "> 📝 書き込み: 打ち込んだメモ" in md


def test_ink_and_enclosure_are_recorded(page_doc, tmp_path: Path):
    doc, page = page_doc
    ink = page.add_ink_annot([[(80, 290), (120, 300), (160, 290)]])
    ink.update()
    r = page.search_for("ページ下の別の段落です。")[0]
    circle = page.add_circle_annot(pymupdf.Rect(r.x0 - 3, r.y0 - 3, r.x1 + 3, r.y1 + 3))
    circle.update()
    md = _convert(doc, tmp_path).markdown
    assert "✍️ 手書きの書き込み" in md
    assert "> ⭕ 囲み（丸）: 「ページ下の別の段落です。」" in md


def test_no_notes_option_keeps_free_text_in_body(page_doc, tmp_path: Path):
    doc, page = page_doc
    ft = page.add_freetext_annot(pymupdf.Rect(300, 285, 520, 310), "打ち込んだメモ", fontsize=9)
    ft.update()
    path = tmp_path / "a.pdf"
    doc.save(str(path))
    doc.close()
    md = convert(path, extract_notes=False).markdown
    assert "📝" not in md
    assert "打ち込んだメモ" in md  # 注釈を出さないときは本文の文字として残す
