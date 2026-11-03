"""OcrEngine（ndlocr-lite 連携・読み順）のテスト

本物の ndlocr-lite は重いので、同じ形の XML を書き出す「偽 ndlocr-lite」スクリプトで
呼び出しから Markdown 化までの流れを確かめる。
"""

import sys
import textwrap
from pathlib import Path

import pymupdf
import pytest
from PIL import Image

from omni_markitdown import convert
from omni_markitdown.core.models import ConversionConfig
from omni_markitdown.engines.ocr_engine import (
    OcrEngine,
    OcrUnavailableError,
    TextBlock,
    blocks_to_markdown,
    parse_ndlocr_xml,
    sort_blocks_reading_order,
)

# ndlocr-lite の出力XMLと同じ構造（柱・ノンブルは捨てられるべき）
FAKE_XML = """<OCRDATASET><PAGE IMAGENAME="x.png" WIDTH="1000" HEIGHT="1400">
<BLOCK TYPE="柱" X="900" Y="20" WIDTH="40" HEIGHT="200"><LINE TYPE="本文" X="900" Y="20" WIDTH="40" HEIGHT="200" STRING="調査報告" ORDER="0"/></BLOCK>
<LINE TYPE="タイトル本文" X="850" Y="100" WIDTH="50" HEIGHT="400" STRING="第一章　総則" ORDER="1"/>
<TEXTBLOCK><LINE TYPE="本文" X="780" Y="100" WIDTH="40" HEIGHT="900" STRING="右の列の文は" ORDER="2"/>
<LINE TYPE="本文" X="730" Y="100" WIDTH="40" HEIGHT="900" STRING="左の列へ続く。" ORDER="3"/></TEXTBLOCK>
<BLOCK TYPE="ノンブル" X="480" Y="1350" WIDTH="40" HEIGHT="20"><LINE TYPE="本文" X="480" Y="1350" WIDTH="40" HEIGHT="20" STRING="12" ORDER="4"/></BLOCK>
</PAGE></OCRDATASET>"""


@pytest.fixture
def fake_ndlocr(tmp_path: Path, monkeypatch) -> Path:
    """--sourcedir の画像ごとに FAKE_XML を書き出す偽コマンドを用意して環境変数に設定する"""
    script = tmp_path / "fake_ndlocr.py"
    script.write_text(textwrap.dedent(f'''
        import argparse, pathlib
        ap = argparse.ArgumentParser()
        ap.add_argument("--sourcedir"); ap.add_argument("--sourceimg"); ap.add_argument("--output")
        a = ap.parse_args()
        out = pathlib.Path(a.output)
        imgs = list(pathlib.Path(a.sourcedir).iterdir()) if a.sourcedir else [pathlib.Path(a.sourceimg)]
        for p in imgs:
            (out / (p.stem + ".xml")).write_text({FAKE_XML!r}, encoding="utf-8")
    '''), encoding="utf-8")
    monkeypatch.setenv("OMNI_NDLOCR_CMD", f'"{sys.executable}" "{script}"')
    return script


@pytest.fixture
def no_ndlocr(monkeypatch):
    monkeypatch.delenv("OMNI_NDLOCR_CMD", raising=False)
    monkeypatch.setattr("omni_markitdown.engines.ocr_engine.shutil.which", lambda name: None)
    monkeypatch.setattr("omni_markitdown.engines.ocr_engine.bundled_ocr_ready", lambda: False)


def _png(path: Path) -> Path:
    Image.new("RGB", (200, 280), "white").save(path)
    return path


# ---------------------------------------------------------------- 読み順

def test_sort_vertical_blocks():
    """縦書き: 右の列 → 左の列、同じ列は上から下"""
    b_right_top = TextBlock(text="右列の一行目", bbox=(800, 100, 850, 400), is_vertical=True)
    b_right_bottom = TextBlock(text="右列の二行目", bbox=(800, 450, 850, 800), is_vertical=True)
    b_left_top = TextBlock(text="左列の一行目", bbox=(700, 100, 750, 400), is_vertical=True)
    b_left_bottom = TextBlock(text="左列の二行目", bbox=(700, 450, 750, 800), is_vertical=True)

    raw = [b_left_bottom, b_right_top, b_left_top, b_right_bottom]
    texts = [b.text for b in sort_blocks_reading_order(raw, is_vertical=True)]
    assert texts == ["右列の一行目", "右列の二行目", "左列の一行目", "左列の二行目"]


def test_sort_two_column_horizontal_lines():
    """横書き2段組: 行の高さがそろっていても、左段を読み切ってから右段へ進む"""
    blocks = []
    for i in range(4):
        y = 200 + i * 20
        blocks.append(TextBlock(text=f"左{i}", bbox=(50, y, 400, y + 14)))
        blocks.append(TextBlock(text=f"右{i}", bbox=(450, y, 800, y + 14)))
    title = TextBlock(text="全幅の見出し", bbox=(50, 100, 800, 130))
    texts = [b.text for b in sort_blocks_reading_order(blocks[::-1] + [title], is_vertical=False)]
    assert texts == ["全幅の見出し", "左0", "左1", "左2", "左3", "右0", "右1", "右2", "右3"]


def test_order_attribute_wins():
    """ndlocr-lite が付けた ORDER があればそれに従う"""
    a = TextBlock(text="二番目", bbox=(0, 0, 10, 10), order=2)
    b = TextBlock(text="一番目", bbox=(100, 100, 110, 110), order=1)
    assert [x.text for x in sort_blocks_reading_order([a, b])] == ["一番目", "二番目"]


# ---------------------------------------------------------------- XML の解釈

def test_parse_xml_skips_pillar_and_folio_and_marks_title():
    blocks = sort_blocks_reading_order(parse_ndlocr_xml(FAKE_XML))
    md = blocks_to_markdown(blocks)
    assert "調査報告" not in md       # 柱
    assert "\n12" not in md           # ノンブル
    assert md.startswith("## 第一章　総則")
    assert "右の列の文は左の列へ続く。" in md  # 同じ本文ブロックの行はつながる


# ---------------------------------------------------------------- エンジン

def test_image_ocr_runs_ndlocr(fake_ndlocr, tmp_path: Path):
    img = _png(tmp_path / "scan.png")
    result = OcrEngine().convert(img, ConversionConfig(), tmp_path)
    assert result.metadata["ocr"] is True
    assert "## 第一章　総則" in result.markdown
    assert "OCR処理完了" not in result.markdown


def test_image_without_ocr_returns_warning_not_fake_text(no_ndlocr, tmp_path: Path):
    img = _png(tmp_path / "scan.png")
    result = OcrEngine().convert(img, ConversionConfig(), tmp_path)
    assert result.metadata["ocr"] is False
    assert result.metadata["warnings"]
    assert "![scan](scan.png)" in result.markdown


def test_forced_ocr_without_engine_raises(no_ndlocr, tmp_path: Path):
    img = _png(tmp_path / "scan.png")
    with pytest.raises(OcrUnavailableError):
        OcrEngine().convert(img, ConversionConfig(enable_ocr=True), tmp_path)


def test_scanned_pdf_is_ocred_automatically(fake_ndlocr, tmp_path: Path):
    """文字の無いページ（スキャン）は自動でOCRされ、全面スキャン画像は保存しない"""
    img = _png(tmp_path / "page.png")
    pdf_path = tmp_path / "scan.pdf"
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_image(page.rect, filename=str(img))
    doc.save(str(pdf_path))
    doc.close()

    result = convert(pdf_path)
    assert result.metadata["ocr_pages"] == [1]
    assert "右の列の文は左の列へ続く。" in result.markdown
    assert result.assets == []


def test_scanned_pdf_without_engine_warns(no_ndlocr, tmp_path: Path):
    img = _png(tmp_path / "page.png")
    pdf_path = tmp_path / "scan.pdf"
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_image(page.rect, filename=str(img))
    doc.save(str(pdf_path))
    doc.close()

    result = convert(pdf_path)
    assert result.metadata["scanned_pages"] == [1]
    assert result.metadata["warnings"]
    assert "⚠️" in result.markdown


# ---------------------------------------------------------------- 後処理（書籍・報告書のスキャンで見えた崩れ）

def test_ocr_punctuation_and_parens_normalized():
    from omni_markitdown.utils.pdf_text import normalize_ocr_punctuation as n
    assert n("要件であるとして.調査の動機(背景)について,資料。") == "要件であるとして，調査の動機（背景）について，資料。"
    assert n("(1)この点") == "（1）この点"
    assert n("see (e.g. ABC)") == "see (e.g. ABC)"  # 英語だけのかっこは変えない


def test_paragraph_broken_at_column_is_merged():
    from omni_markitdown.utils.pdf_text import merge_broken_paragraphs as m
    assert m(["(1)このような調査方法をどのように理解するべき", "か。古典的な見解は", "## 見出し"]) == [
        "(1)このような調査方法をどのように理解するべきか。古典的な見解は", "## 見出し"]
    assert m(["第一文。", "（2）次の段落"]) == ["第一文。", "（2）次の段落"]


def test_section_number_after_period_starts_paragraph():
    from omni_markitdown.engines.ocr_engine import SECTION_NUMBER_SPLIT_RE as R
    assert R.split("注目される。2今回の調査は") == ["注目される。", "2今回の調査は"]
    assert len(R.split("決定した。5人の委員が。12月に")) == 1


def test_repeated_watermark_removed_from_ocr_pages():
    from omni_markitdown.engines.pdf_engine import _drop_repeated_paragraphs
    bodies = ["調査の要件について。", "動機の表示について。", "資料の理解について。", "見解の対立について。"]
    pages = {i: f"{bodies[i]}\n\nDL版データベース 閲覧期限 2023/04/2{i}" for i in range(4)}
    out = _drop_repeated_paragraphs(pages)
    assert all("データベース" not in v for v in out.values())
    assert out[2] == "資料の理解について。"


def test_broken_text_layer_is_treated_as_scanned(no_ndlocr, tmp_path: Path):
    """前のOCRの失敗で制御文字だらけになった文字の層（スキャンした書籍で発生）は使わない"""
    from omni_markitdown.engines.pdf_engine import _is_garbage
    assert _is_garbage("\x01" * 30 + "abc")
    assert not _is_garbage("普通の日本語の文章がここに十分な長さで書かれている。")


def test_pages_are_stitched_when_sentence_continues():
    from omni_markitdown.engines.pdf_engine import _stitch_pages
    out = _stitch_pages(["前のページの文が「対象施設の表", "示」に続く。\n\n次の段落。"])
    assert out == ["前のページの文が「対象施設の表示」に続く。", "次の段落。"]


# ---------------------------------------------------------------- 照合の補助

def test_kanji_zero_read_as_circle_is_fixed():
    from omni_markitdown.utils.pdf_text import normalize_ocr_punctuation as n
    assert n("規則二○条三項") == "規則二〇条三項"
    assert n("○印をつける") == "○印をつける"  # 記号としての○はそのまま


def test_check_list_extracts_numbers_and_flags_repeated_zero():
    from omni_markitdown.utils.ocr_check import check_list_markdown, extract_check_items
    text = "委託費金四〇〇〇〇円を支出し、規則二〇条三項に違反する（昭和52・7・13 統計年報31巻4号533頁）。令和2年（第3）202号"
    items = extract_check_items(text, 3)
    kinds = {(d["kind"], d["value"]) for d in items}
    assert ("金額", "四〇〇〇〇円") in kinds
    assert ("条番号", "二〇条三項") in kinds
    assert ("文献", "統計年報31巻4号533頁") in kinds
    assert any(d["kind"] == "日付" and "52・7・13" in d["value"] for d in items)
    assert any(d["kind"] == "番号" and "202号" in d["value"] for d in items)
    assert next(d for d in items if d["value"] == "四〇〇〇〇円")["risky"] is True
    md = check_list_markdown(items, "x.pdf")
    assert "| 3 | 金額 | ⚠ 四〇〇〇〇円 |" in md


def test_scanned_pdf_gets_page_link_and_check_file(fake_ndlocr, tmp_path: Path):
    img = _png(tmp_path / "page.png")
    pdf_path = tmp_path / "scan.pdf"
    doc = pymupdf.open()
    for _ in range(2):
        page = doc.new_page()
        page.insert_image(page.rect, filename=str(img))
    doc.save(str(pdf_path))
    doc.close()

    out = tmp_path / "out" / "scan.md"
    result = convert(pdf_path, out)
    assert "[📄 原本 p.1](_assets/page_p001_" in result.markdown
    assert "[📄 原本 p.2](_assets/page_p002_" in result.markdown
    assert list((tmp_path / "out" / "_assets").glob("page_p00*.jpg"))
    # 偽 ndlocr の文には数字が無いので照合リストは出ない
    assert not (tmp_path / "out" / "scan.ocr_check.md").exists()


BS = chr(92)  # バックスラッシュ
LONG_PREFIX = BS * 2 + "?" + BS  # Windows の長いパス接頭辞 \\?\


def test_windows_long_path_prefix(monkeypatch):
    r"""深いフォルダでもモデルを開けるよう、260文字を超えるパスに \\?\ を付ける"""
    from omni_markitdown.engines import ocr_engine as oe
    monkeypatch.setattr(oe.os, "name", "nt")
    long_p = Path("C:/" + "a" * 300 + "/model.onnx")
    assert oe.windows_long_path(long_p).startswith(LONG_PREFIX)
    assert oe.windows_long_path(Path("C:/short/model.onnx")) == str(Path("C:/short/model.onnx"))
    assert oe.windows_long_path(Path("//server/share/" + "b" * 300)).startswith(LONG_PREFIX + "UNC" + BS)


def test_bundled_command_passes_every_model_file(monkeypatch):
    from omni_markitdown.engines import ocr_engine as oe
    monkeypatch.delenv("OMNI_NDLOCR_CMD", raising=False)
    monkeypatch.setattr(oe, "bundled_ocr_ready", lambda: True)
    cmd = oe.find_ndlocr_command()
    for flag in oe.BUNDLED_MODEL_FILES:
        assert flag in cmd
    for flag, parts in oe.BUNDLED_MODEL_FILES.items():
        path = cmd[cmd.index(flag) + 1].replace(LONG_PREFIX, "")
        assert Path(path).exists(), path


def test_short_text_page_is_not_ocred(fake_ndlocr, tmp_path: Path):
    """文字が少なくても文字の層があり、スキャン画像が無いページ（章の扉など）は OCR しない。
    以前は 20 文字未満のページを OCR し、正しい文字を OCR の推測で上書きしていた"""
    pdf_path = tmp_path / "title.pdf"
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_font(fontname="jp", fontbuffer=pymupdf.Font("japan").buffer)
    page.insert_text((100, 150), "第1章 概要", fontname="jp", fontsize=20)
    doc.save(str(pdf_path))
    doc.close()

    result = convert(pdf_path)
    assert result.metadata["ocr_pages"] == []
    assert "第1章 概要" in result.markdown


def test_space_after_japanese_punctuation_removed():
    """OCR が日本語の句読点の後ろに入れる空白を取る（200dpi で読むと出る）。英文の空白は残す"""
    from omni_markitdown.utils.pdf_text import normalize_ocr_punctuation as n
    assert n("担当者Aが司会、 その他の三名が補助となり、 いずれも所定の手順で。 次に") == "担当者Aが司会、その他の三名が補助となり、いずれも所定の手順で。次に"
    assert n("see the result. Next step") == "see the result. Next step"
