---
name: omni-markitdown
description: Convert any document (Word, PDF, Excel, PPTX, scanned Japanese documents, audio lectures, EPUB, HTML, CSV/JSON) into structured Markdown completely offline. Preserves inline footnotes, comments, diagram images (Source Visuals), and vertical/multi-column reading order. Use whenever the user asks to "convert to markdown", "make MD", "MD化", "parse document", "extract lecture notes", "transcribe audio", or when documents need high-fidelity Markdown representation with assets.
---

# omni-markitdown: 最強マルチモーダルMarkdown変換スキル

あらゆる文書・資料・音声を、外部API通信ゼロ（完全ローカル）で最高精度の構造化Markdownへ変換・抽出するスキルです。

## 特徴と強み

1. **完全ローカルファースト（外部通信ゼロ）**:
   - 外部有料API（OpenAI, Gemini, Azure等）への通信を一切行わないため、機密文書や社内資料、講義ノートを安全にMarkdown化できます。
2. **Word・PDFの脚注・コメントをインライン展開**:
   - Wordの脚注（`> 📝 脚注 [注1]: 内容`）やコメント（`> 💬 コメント [作成者]: 内容`）、PDFのハイライト注釈を該当段落の直下にインライン配置します。
3. **図表画像の決定論的抽出・アセット埋め込み**:
   - PDFや文書から図表を自動切り出し、`_assets/` フォルダへ決定論的ハッシュで保存してMarkdownリンク（`![fig_p01_01](_assets/...)`）を埋め込みます。
4. **日本文献・縦書き・多段組の読み順復元 (ndlocr-lite準拠)**:
   - 近代活字書籍、学術論文、資料集（2段組・3段組や縦書き）の読み順（右上→左下、多段組境界）を正確に復元してMarkdown化します。
5. **音声メタデータ ＆ ローカル文字起こし (MarkItDown + faster-whisper)**:
   - 音声ファイル（MP3, WAV, M4A等）から再生時間・サンプリングレートなどのメタデータを抽出し、タイムスタンプ付きのテキスト起こしを出力します。

---

## 実行方法

### 1. コマンドライン実行 (CLI)

```bash
# 基本変換（Word, PDF, Excel, PPTX等）
omni-markitdown "C:\path\to\document.docx" -o "C:\path\to\output.md"

# 図表画像と脚注・コメントを完全抽出
omni-markitdown "C:\path\to\lecture.pdf" -o "C:\path\to\output.md" --assets-dir _assets

# 日本語スキャン文献・縦書き・多段組OCR変換
omni-markitdown "C:\path\to\old_law_book.pdf" -o "C:\path\to\output.md" --ocr

# 音声ファイルの文字起こし
omni-markitdown "C:\path\to\lecture.mp3" -o "C:\path\to\output.md" --transcribe
```

### 2. Python SDK 実行

```python
from omni_markitdown import OmniConverter, ConversionConfig, convert

# 簡易変換
result = convert("input.pdf", "output.md")
print(result.markdown)

# 詳細オプション指定
config = ConversionConfig(
    extract_images=True,
    extract_notes=True,
    enable_ocr=True,
    assets_dir="_assets"
)
converter = OmniConverter(config=config)
res = converter.convert("path/to/file.docx")
print(f"画像アセット: {len(res.assets)} 件")
print(f"脚注・コメント: {len(res.notes)} 件")
```

### 3. MCP ツール利用 (AIアシスタント)

エージェントは設定された MCP サーバー `omni-markitdown` を介して、以下のツールを呼び出せます：
- `convert_to_markdown(file_path, extract_images, extract_notes, transcribe_audio)`: ファイルを構造化Markdownに変換。
- `inspect_document(file_path)`: ファイルを変換せずに形式・ページ数・画像数・脚注数を高速確認。

---

## トラブルシューティング

| 現象 | 原因と対処 |
| :--- | :--- |
| Excel変換でエラーが出る | `pandas` および `openpyxl` が必要です（`pip install pandas openpyxl`）。 |
| 音声文字起こしがスキップされる | ローカルSTTライブラリが必要です（`pip install "omni-markitdown[audio]"` または `pip install faster-whisper`）。 |
| PDFの日本語が文字化けしている・本文が空 | スキャンPDFです。`pip install -e ".[ocr]"` で同封の ndlocr-lite 用の部品を入れると自動でOCRされます（全ページ強制は `--ocr`）。 |
