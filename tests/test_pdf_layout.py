"""PDF の行組み立て・段落・段組・表・ヘッダー除去のテスト

官公庁のPDFで実際に起きた崩れを、小さなPDFで再現して確かめる。
"""

import re
from pathlib import Path

import pymupdf
import pytest

from omni_markitdown import convert
from omni_markitdown.utils.pdf_text import clean_inline


def _page(doc):
    page = doc.new_page(width=595, height=842)
    page.insert_font(fontname="jp", fontbuffer=pymupdf.Font("japan").buffer)
    return page


def _save(doc, path: Path) -> Path:
    doc.save(str(path))
    doc.close()
    return path


def test_overprinted_punctuation_is_put_back_in_place(tmp_path: Path):
    """読点だけを後から重ね打ちしたPDF（官公庁のPDFと同じ作り）でも、正しい位置に戻る"""
    doc = pymupdf.open()
    page = _page(doc)
    # 本文は読点の位置を空けて描き、読点は別の命令で後から描く
    page.insert_text((100, 150), "交通量の変化", fontname="jp", fontsize=10)
    page.insert_text((170, 150), "その推移", fontname="jp", fontsize=10)
    page.insert_text((160, 150), "，", fontname="jp", fontsize=10)
    result = convert(_save(doc, tmp_path / "comma.pdf"))
    # テスト用フォントは全角読点を半角で書き出すので、どちらでもよい
    assert re.search("交通量の変化[，,]その推移", result.markdown)


def test_wrapped_lines_join_and_indent_starts_paragraph(tmp_path: Path):
    """1行ずつ別に描かれた本文がつながり、字下げで段落が分かれる"""
    doc = pymupdf.open()
    page = _page(doc)
    lines = [
        (111, "本調査は，対象地域における交通量の変化を把握するために行った観測"),
        (101, "の結果をまとめたもので，平日と休日の差を中心に分析を加えている。"),
        (111, "本調査の目的は，交通計画の見直しに要る基礎資料を得ることにある。"),
    ]
    y = 140
    for x, text in lines:
        page.insert_text((x, y), text, fontname="jp", fontsize=10)
        y += 15.5
    result = convert(_save(doc, tmp_path / "wrap.pdf"))
    paras = result.markdown.split("\n\n")
    assert "行った観測の結果をまとめたもの" in result.markdown
    assert len(paras) == 2


def test_two_columns_read_left_then_right(tmp_path: Path):
    doc = pymupdf.open()
    page = _page(doc)
    page.insert_text((50, 80), "大見出し：事案の概要", fontname="jp", fontsize=18)
    for i in range(4):
        page.insert_text((50, 120 + i * 16), f"左段{i}行目の文章です。", fontname="jp", fontsize=10)
        page.insert_text((320, 120 + i * 16), f"右段{i}行目の文章です。", fontname="jp", fontsize=10)
    md = convert(_save(doc, tmp_path / "cols.pdf")).markdown
    assert md.startswith("# 大見出し：事案の概要")
    assert md.index("左段3行目") < md.index("右段0行目")


def test_headers_footers_and_page_numbers_removed(tmp_path: Path):
    doc = pymupdf.open()
    for n in range(1, 4):
        page = _page(doc)
        page.insert_text((50, 30), "月刊 調査報告 第26号", fontname="jp", fontsize=8)
        page.insert_text((290, 820), f"- {n} -", fontname="jp", fontsize=8)
        page.insert_text((50, 120), f"第{n}ページの本文です。", fontname="jp", fontsize=10)
    md = convert(_save(doc, tmp_path / "hf.pdf")).markdown
    assert "調査報告" not in md
    assert "- 2 -" not in md
    assert "第3ページの本文です。" in md


def test_ruled_table_becomes_markdown_table(tmp_path: Path):
    doc = pymupdf.open()
    page = _page(doc)
    xs, ys = [50, 200, 350], [220, 240, 260, 280]
    for y in ys:
        page.draw_line((xs[0], y), (xs[-1], y))
    for x in xs:
        page.draw_line((x, ys[0]), (x, ys[-1]))
    for r, (a, b) in enumerate([("項目", "金額"), ("予算額", "100万円"), ("決算額", "80万円")]):
        page.insert_text((55, ys[r] + 15), a, fontname="jp", fontsize=10)
        page.insert_text((205, ys[r] + 15), b, fontname="jp", fontsize=10)
    md = convert(_save(doc, tmp_path / "table.pdf")).markdown
    assert "| 項目 | 金額 |" in md
    assert "| 予算額 | 100万円 |" in md


def test_emphasis_dots_are_dropped(tmp_path: Path):
    """傍点（強調の点）が本文に混ざらない（官公庁のPDFで起きた崩れ）"""
    doc = pymupdf.open()
    page = _page(doc)
    page.insert_text((100, 150), "相当程度の確実さをもって指定を受けられない。", fontname="jp", fontsize=10)
    page.insert_text((100, 141), "．．．．．", fontname="jp", fontsize=5)
    md = convert(_save(doc, tmp_path / "dots.pdf")).markdown
    assert "．．" not in md
    assert "相当程度の確実さをもって" in md


def test_highlight_text_is_extracted(tmp_path: Path):
    doc = pymupdf.open()
    page = _page(doc)
    page.insert_text((100, 150), "重要な説明部分", fontname="jp", fontsize=10)
    page.add_highlight_annot(page.search_for("重要な説明部分")[0])
    result = convert(_save(doc, tmp_path / "hl.pdf"))
    assert "🖍️ ハイライト" in result.markdown
    assert "重要な説明部分" in result.notes[0].content


def test_same_image_on_every_page_saved_once(tmp_path: Path):
    from PIL import Image

    img = tmp_path / "logo.png"
    Image.new("RGB", (120, 60), "red").save(img)
    doc = pymupdf.open()
    for _ in range(3):
        page = _page(doc)
        page.insert_image(pymupdf.Rect(50, 50, 290, 170), filename=str(img))
        page.insert_text((50, 200), "本文", fontname="jp", fontsize=10)
    result = convert(_save(doc, tmp_path / "img.pdf"))
    assert len(result.assets) == 1
    assert result.markdown.count("![") == 3


@pytest.mark.parametrize("raw, expected", [
    ("⾒解", "見解"),          # 康熙部首
    ("⻑官", "長官"),          # CJK部首補助
    ("本 調 査 は 、 交 通 の 問 題", "本調査は、交通の問題"),  # 字間を空けた行は詰める
    ("第1回 講義ノート", "第1回 講義ノート"),  # 意図した区切りは残す
    ("ＡＢ１２", "ＡＢ１２"),  # 全角英数字は変えない
])
def test_clean_inline(raw, expected):
    assert clean_inline(raw) == expected


def test_narrow_repeated_chars_are_kept(tmp_path: Path):
    """「//」「ii」「ll」のような幅の狭い同じ文字の並びを、太字の重ね描きと間違えて消さない
    （以前は https://www.wiill-example.org が https:/www.wil-example.org のように欠けた）"""
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 100), "https://www.wiill-example.org skill 1111", fontname="helv", fontsize=8)
    md = convert(_save(doc, tmp_path / "narrow.pdf")).markdown
    assert "https://www.wiill-example.org skill 1111" in md


def test_bold_double_draw_still_collapsed(tmp_path: Path):
    """同じ文字を少しずらして2回描く太字は、1文字にまとめる"""
    doc = pymupdf.open()
    page = _page(doc)
    for dx in (0, 0.4):
        page.insert_text((100 + dx, 150), "重要事項", fontname="jp", fontsize=12)
    md = convert(_save(doc, tmp_path / "bold.pdf")).markdown
    assert "重要事項" in md
    assert "重重" not in md and "重要事項重要事項" not in md
