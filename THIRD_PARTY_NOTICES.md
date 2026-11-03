# Third-party notices / 第三者のライセンス

omni-markitdown 本体のソースコードは MIT License（`LICENSE`）。`LICENSE` は本体のソースだけに適用され、同封の NDLOCR-Lite（`omni_markitdown/_vendor/ndlocr_lite/`）には適用されない。
このリポジトリに**同封している**ものと、インストール時に**別に入る**ものは、それぞれのライセンスに従う。

## 1. 同封しているもの

### NDLOCR-Lite（国立国会図書館）

- 場所: `omni_markitdown/_vendor/ndlocr_lite/`
- 出典: https://github.com/ndl-lab/ndlocr-lite （v1.3.0、master e57f7c6bd9）
- ライセンス: **CC BY 4.0**（`omni_markitdown/_vendor/ndlocr_lite/LICENCE`）
- 表示: 「NDLOCR-Lite（国立国会図書館）」を CC BY 4.0 のもとで利用。
- 変更: 画像の読み取りに必要な部分（プログラム・設定・学習済みモデル）だけを同封した。GUI・ツール・学習用コードは含めていない。プログラムとモデルの中身は変更していない。詳細は同フォルダの `NOTICE.md`。
- NDLOCR-Lite が実行時に使うライブラリのライセンスは `omni_markitdown/_vendor/ndlocr_lite/LICENCE_DEPENDENCIES`。

### DINOv3 License（Meta）— レイアウト認識モデル

- 対象: `omni_markitdown/_vendor/ndlocr_lite/model/deim-s-1024x1024.onnx`
- このモデルはバックボーンに DINOv3 を蒸留した ViT-Tiny を使っており、使用・再配布には **DINOv3 License** にも従う。
- 全文: `omni_markitdown/_vendor/ndlocr_lite/LICENCE_DEPENDENCIES` 内「DINOv3 License」、https://github.com/facebookresearch/dinov3/blob/main/LICENSE.md

## 2. インストール時に別に入るもの（このリポジトリには含まない）

`pip install` で PyPI から入る。主なもの:

| パッケージ | 用途 | ライセンス |
|---|---|---|
| **PyMuPDF** | PDF の読み取り | **AGPL-3.0**（または Artifex の商用ライセンス） |
| markitdown | Excel・PowerPoint・HTML など | MIT |
| python-docx | Word | MIT |
| openpyxl / python-pptx / pandas | Excel・PowerPoint（markitdown 経由） | MIT / MIT / BSD-3-Clause |
| magika | ファイル形式の判定（markitdown 経由） | Apache-2.0 |
| Pillow | 画像 | MIT-CMU |
| mcp | MCP サーバー | MIT |
| onnxruntime | OCR（`[ocr]`） | MIT |
| opencv-python-headless | OCR（`[ocr]`） | Apache-2.0 |
| numpy / lxml / networkx | OCR（`[ocr]`） | BSD-3-Clause |
| PyYAML / tqdm | OCR（`[ocr]`） | MIT / MIT・MPL-2.0 |
| faster-whisper / soundfile | 音声（`[audio]`） | MIT / BSD-3-Clause |

### PyMuPDF（AGPL-3.0）について

PyMuPDF は AGPL-3.0 のライブラリで、このリポジトリには含まず、利用者の環境に `pip` で入る。
omni-markitdown 本体の MIT は変わらないが、PyMuPDF と組み合わせたものを**配布する**場合や、**改変してネットワーク越しに他人へ提供する**場合は、AGPL-3.0 の条件（対応するソースコードの提供など）に従う必要がある。
自分や自分の組織の中で使うだけなら、これらの条件は問題にならない。

## 3. 設計の参考にしたもの

コードの一部の考え方を参考にした（同封はしていない）。

- Microsoft MarkItDown（MIT）: 多形式の変換。インストール時の依存として使用。
- DeepTutor（HKUDS、Apache-2.0）: 図表画像をページ番号とハッシュ値で保存し、Markdown からリンクする方式。
