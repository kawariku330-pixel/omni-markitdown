# 技術要件・設計仕様書: omni-markitdown (v1.3.0-draft)

## 1. 概要と目的 (Overview & Objectives)

### 1.1 背景と統合の目的
Markdown変換における5大要素の精鋭統合：
- **Microsoft MarkItDown**: 29種以上のオフィス形式（Word, PPTX, Excel, EPUB, HTML, CSV, JSON等）および音声メタデータ・文字起こし基盤。
- **脚注・コメントのインライン展開**: Word/PDFの脚注（`> 📝 脚注`）やコメント（`> 💬 コメント`）を本文直下にインライン展開する学術向け高精度抽出ロジック。
- **DeepTutor (Reading Engine & Source Visuals)**: PDFから図表画像をページ番号・ハッシュ値とともに切り出し、Markdown内に決定論的リンク（`![fig-P1-01](_assets/...)`）を埋め込むアセット抽出アーキテクチャ。
- **ndl-lab/ndlocr-lite (国会図書館 OCR)**: 近代書籍・学術文献・古典籍・縦書き・多段組（2段組/3段組）・ルビに対応するONNX/CPUベースの完全ローカル日本語OCRエンジン。
- **ローカル音声文字起こし (Speech-to-Text Engine)**: 音声講義や録音ファイル（MP3, WAV, M4A, FLAC等）のメタデータ抽出およびローカル文字起こし。

本プロジェクト `omni-markitdown` は、これらを統合し、**「あらゆる文書（Office/PDF/スキャン日本文献）および音声データを完全ローカル環境で、脚注・コメント・図表アセット・音声書き起こしを損なわずに最高品質のMarkdownへ変換する軽量・高精度な統一エンジン」** を実現する。

### 1.2 確定した設計原則
1. **完全ローカルファースト＆通信ゼロ保証**:
   - 外部APIへの通信は一切行わない。Microsoft `markitdown` 呼び出し時もLLM連携を完全無効化（`llm_client=None`）。
   - 日本語OCR（`ndlocr-lite`）はCPU/ONNX Runtimeで動作。
   - 音声文字起こしもローカルモデル（`faster-whisper` 等）またはMarkItDownローカル音声パーサーで完結。
2. **提供形態**: CLI ＋ Python SDK ＋ Stdio MCP サーバー（Antigravity / Claude Code / Claude Desktop 対応）。
3. **依存関係の階層化（オプショナルExtras分離でコア軽量性を維持）**:
   - `omni-markitdown` (基本コア: python-docx, PyMuPDF, markitdown)
   - `omni-markitdown[ocr]` (ndlocr-lite, onnxruntime, pillow, opencv-python-headless)
   - `omni-markitdown[audio]` (音声メタデータ抽出、faster-whisper等のローカルSTT)
   - `omni-markitdown[mcp]` (mcp SDK)
   - `omni-markitdown[all]` (全機能一括)

---

## 2. システムアーキテクチャ (Architecture)

### 2.1 パイプライン構成

```mermaid
flowchart TD
    Input[入力ファイル] --> Converter[OmniConverter<br/>統一オーケストレーター]
    
    Converter --> Dispatch{フォーマット判定}
    
    Dispatch -->|Word .docx| DocxEngine[DocxEngine<br/>本文 + 脚注・コメント インライン展開]
    Dispatch -->|PDF .pdf| PdfEngine[PdfEngine<br/>PyMuPDF による画像抽出 + 注釈展開]
    Dispatch -->|スキャンPDF / 画像| OcrEngine[OcrEngine<br/>ndlocr-lite 縦書き・多段組 読み順ソート]
    Dispatch -->|音声 .mp3 / .wav / .m4a| AudioEngine[AudioEngine<br/>音声メタデータ + ローカル文字起こし]
    Dispatch -->|PPTX / XLSX / HTML / EPUB 等| OfficeEngine[OfficeEngine<br/>MarkItDown 委譲 (LLM通信無効)]
    Dispatch -->|Text / Markdown / Code| PlainEngine[PlainEngine<br/>エンコーディング正規化]
    
    PdfEngine -->|画像アセット検出| AssetMgr[AssetManager<br/>ハッシュ採番 & _assets/ 保存]
    DocxEngine -->|画像アセット検出| AssetMgr
    
    DocxEngine --> Assemble[Markdown 組立 & テーブル正規化]
    PdfEngine --> Assemble
    OcrEngine --> Assemble
    AudioEngine --> Assemble
    OfficeEngine --> Assemble
    PlainEngine --> Assemble
    AssetMgr -->|リンク置換| Assemble
    
    Assemble --> Output[ConversionResult<br/>.markdown, .assets, .notes]
    
    Output --> CLI[CLI 出力]
    Output --> SDK[Python SDK 戻り値]
    Output --> MCP[MCP Stdio 応答]
```

### 2.2 ディレクトリ・ファイル構成

```
omni-markitdown/
├── pyproject.toml              # コア依存と extras (ocr, audio, mcp) の定義
├── README.md                   # 仕様・導入・使い方
├── CHANGELOG.md                # 変更履歴
├── omni_markitdown/            # メインパッケージ
│   ├── __init__.py             # __version__ = "1.0.0", convert, OmniConverter
│   ├── cli.py                  # CLIエントリーポイント
│   ├── mcp_server.py           # Model Context Protocol サーバー (Stdio)
│   ├── core/                   # オーケストレーション & データモデル
│   │   ├── __init__.py
│   │   ├── converter.py        # 統一オーケストレーター (フォーマット判定・エンジン呼出)
│   │   └── models.py           # ConversionResult, VisualAsset, ExtractedNote, Config
│   ├── engines/                # 責務ごとに完結したパーサーエンジン
│   │   ├── __init__.py
│   │   ├── base.py             # 抽象基底クラス (BaseEngine)
│   │   ├── docx_engine.py      # Docx (本文 + 脚注・コメントインライン抽出)
│   │   ├── pdf_engine.py       # PyMuPDF一本化 (高速テキスト + 注釈 + 画像切り出し)
│   │   ├── ocr_engine.py       # ndlocr-lite (ONNX/CPU 縦書き・多段組・日本文献OCR)
│   │   ├── audio_engine.py     # 音声ファイル (メタデータ抽出 + ローカル文字起こし)
│   │   └── office_engine.py    # MarkItDown委譲 (XLSX, PPTX, HTML, EPUB等, LLM完全OFF)
│   └── utils/
│       ├── __init__.py
│       ├── assets.py           # 画像アセット保存・決定論的ハッシュ採番
│       ├── encoding.py         # Windows UTF-8 / CP932 クラッシュ防止
│       └── file_guard.py       # 原本読み取り専用保護・安全オープン
├── tests/                      # TDD テストスイート
│   ├── test_docx_engine.py
│   ├── test_pdf_engine.py
│   ├── test_ocr_engine.py
│   ├── test_audio_engine.py
│   ├── test_office_engine.py
│   └── test_mcp_server.py
└── 作業用/                     # 開発・動作検証用スクリプト保管
```

---

## 3. 主要エンジンの詳細実装メカニズム

### 3.1 AudioEngine: 音声メタデータ ＆ ローカル文字起こし
- **対応形式**: `.mp3`, `.wav`, `.m4a`, `.aac`, `.flac`, `.ogg`
- **動作**:
  1. **メタデータ抽出**: ファイルサイズ、サンプリングレート、再生時間、ID3タグ（タイトル、作成者、日付等）を抽出し、Markdownのヘッダーメタ情報として出力：
     ```markdown
     # 音声文字起こし: 20261103_統計学講義.mp3
     - **再生時間**: 01:24:15
     - **形式**: MP3 (44.1kHz / 128kbps)
     - **録音日時**: 2026-11-03 14:00
     
     ---
     ```
  2. **ローカル文字起こし**:
     - `omni-markitdown[audio]` 導入時、ローカルSTTエンジン（`faster-whisper` または `markitdown` 組み込み音声パーサー）を使用してタイムスタンプ付きのMarkdownテキストを生成：
     ```markdown
     ## 文字起こし本文
     
     - **[00:00:15]** 本日は標本調査の限界について検討します。
     - **[00:02:40]** まず教科書の第3章を確認してください。
     ```
  3. **軽量性保護**: 音声ライブラリが未インストールの環境でも、基本メタデータ抽出は常時動作し、「文字起こしを利用する場合は `pip install omni-markitdown[audio]` を実行してください」と親切に案内。

### 3.2 DocxEngine: 脚注・コメントのインライン展開
- `python-docx` の XML DOM を直接走査し、段落直下に `> 📝 脚注` / `> 💬 コメント` をインライン展開。

### 3.3 PdfEngine: PyMuPDF一本化とSource Visualsアセット抽出
- `PyMuPDF` (`fitz`) により、高速テキストブロック抽出、注釈（ハイライト・コメント）抽出、および埋め込み画像の切り出し（`_assets/` 保存とMarkdownリンク自動挿入）を実施。
- スキャン画像のみのページを自動検知した場合は `OcrEngine` へ委譲。

### 3.4 OcrEngine: ndlocr-lite (日本近代文献・縦書き・多段組OCR)
- 国立国会図書館 `ndlocr-lite` の ONNX 推論モデル（CPUで軽量動作）を使用。
- 縦書き・多段組（2段組/3段組）の境界判定と正確な読み順復元。

### 3.5 OfficeEngine: Microsoft MarkItDown 委譲
- `markitdown.MarkItDown` をラップ（`llm_client=None` で外部通信完全遮断）。
- PPTX、XLSX、HTML、CSV/JSON、EPUB を処理。

---

## 4. インターフェース仕様

### 4.1 CLI
```bash
# 基本変換（Office, PDF等）
omni-markitdown input.docx -o output.md

# 音声ファイルの文字起こし
omni-markitdown lecture.mp3 -o lecture.md

# 日本文献スキャンPDFを ndlocr-lite でOCR変換
omni-markitdown old_law_book.pdf -o output.md --ocr

# 画像アセット・脚注・コメント全抽出
omni-markitdown input.pdf -o output.md --extract-images --extract-notes
```

### 4.2 Python SDK
```python
from omni_markitdown import OmniConverter, ConversionConfig

converter = OmniConverter(
    config=ConversionConfig(
        extract_images=True,
        extract_notes=True,
        enable_audio_transcription=True,
        ocr_enabled=True,
        assets_dir="_assets"
    )
)

result = converter.convert("lecture.mp3")
print(result.markdown)       # 音声メタデータ＋文字起こしMarkdown
```

### 4.3 MCP サーバー (Stdio)
AIアシスタント（Claude Code / Antigravity / Claude Desktop）の設定：
```json
{
  "mcpServers": {
    "omni-markitdown": {
      "command": "python",
      "args": ["-m", "omni_markitdown.mcp_server"]
    }
  }
}
```

---

## 5. セキュリティと堅牢性
1. **外部通信完全遮断**: 外部API通信コードを排除し、完全オフライン動作。
2. **原本読み取り専用保護**: 入力ファイルは読み取り専用モードでオープン。
3. **DoS・巨大ファイル対策**: デフォルト100MB上限、Excel巨大シート展開ガード。
4. **Windows UTF-8 互換**: Windows PowerShell 環境での文字化け完全防止。
