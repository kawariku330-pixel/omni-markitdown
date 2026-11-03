# 同封している NDLOCR-Lite について

- 出典: 国立国会図書館「NDLOCR-Lite」 https://github.com/ndl-lab/ndlocr-lite
- 版: v1.3.0（master e57f7c6bd9, 2026-10-28 時点）
- ライセンス: CC BY 4.0（`LICENCE`）。実行時に使うライブラリのライセンスは `LICENCE_DEPENDENCIES`
  （原本のファイル名は `LICENCE_DEPENDENCEIES`）。
- レイアウト認識モデル（`model/deim-s-1024x1024.onnx`）はバックボーンに DINOv3 を蒸留した ViT-Tiny を使っている。
  このモデルを使う場合は DINOv3 ライセンス（`LICENCE_DEPENDENCIES` 内「DINOv3 License」、
  https://github.com/facebookresearch/dinov3/blob/main/LICENSE.md ）にも従う。

## 原本からの変更

- 画像の読み取りに必要な部分だけを同封した（`ocr.py`, `deim.py`, `parseq.py`, `ndl_parser.py`,
  `pdf_output_utils.py`, `tcy_wrapper.py`, `version.py`, `config/`, `model/`, `reading_order/`, `optional_features/`）。
  GUI（flet）・ツール類・学習用コードは含めていない。プログラムとモデルの中身は変更していない。
- omni-markitdown は `python ocr.py --sourcedir <画像フォルダ> --output <出力フォルダ>` を外部プロセスとして呼び、
  出力 XML を読む。
