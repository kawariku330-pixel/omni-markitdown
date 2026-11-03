"""omni-markitdown CLI エントリーポイント
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from omni_markitdown import __version__, convert
from omni_markitdown.core.converter import OmniConverter
from omni_markitdown.core.models import ConversionConfig
from omni_markitdown.utils.encoding import setup_utf8_encoding


def _default_output(input_p: Path) -> Path:
    """既定の出力先。入力が .md なら原本を上書きしないよう .converted.md にする"""
    if input_p.suffix.lower() in (".md", ".markdown"):
        return input_p.with_name(input_p.stem + ".converted.md")
    return input_p.with_suffix(".md")


def _report(result, output_p: Path, assets_dir: str) -> None:
    print(f"✅ 変換成功: {output_p}")
    if result.assets:
        print(f"   🖼️  抽出画像アセット: {len(result.assets)} 件 ({assets_dir}/)")
    if result.notes:
        print(f"   📝 抽出脚注・コメント: {len(result.notes)} 件")
    for w in result.metadata.get("warnings", []) or []:
        print(f"   ⚠️  {w}")


def main() -> int:
    setup_utf8_encoding()
    # OCR など時間のかかる処理の進み具合を表示する
    logging.basicConfig(level=logging.INFO, format="   ⏳ %(message)s", stream=sys.stderr)

    parser = argparse.ArgumentParser(
        prog="omni-markitdown",
        description="omni-markitdown: 最強のマルチモーダルMarkdown変換・構造化エンジン"
    )
    parser.add_argument("input_path", type=str, help="入力ファイルパスまたはディレクトリ")
    parser.add_argument("-o", "--output", type=str, default=None,
                        help="出力Markdownファイルパス（入力がディレクトリなら出力先ディレクトリ）")
    parser.add_argument("--no-images", action="store_true", help="画像アセット抽出を無効化")
    parser.add_argument("--no-notes", action="store_true", help="脚注・コメント抽出を無効化")
    parser.add_argument("--ocr", action="store_true",
                        help="画像・PDFを必ず ndlocr-lite でOCRする（既定でもスキャンページは自動でOCR）")
    parser.add_argument("--ndlocr-cmd", type=str, default=None, help="ndlocr-lite の実行コマンド（PATH に無い場合）")
    parser.add_argument("--transcribe", action="store_true", help="音声のローカル文字起こしを有効化")
    parser.add_argument("--assets-dir", type=str, default="_assets", help="画像アセットの出力先フォルダ名 (デフォルト: _assets)")
    parser.add_argument("-v", "--version", action="version", version=f"%(prog)s {__version__}")

    args = parser.parse_args()

    input_p = Path(args.input_path)
    if not input_p.exists():
        print(f"エラー: 指定されたパスが存在しません: {input_p}", file=sys.stderr)
        return 1

    options = dict(
        extract_images=not args.no_images,
        extract_notes=not args.no_notes,
        enable_ocr=args.ocr,
        ndlocr_command=args.ndlocr_cmd,
        enable_audio_transcription=args.transcribe,
        assets_dir=args.assets_dir,
    )

    # ディレクトリ: 中の対応ファイルをすべて変換する
    if input_p.is_dir():
        out_root = Path(args.output) if args.output else input_p
        files = list(OmniConverter(ConversionConfig(**options)).iter_supported_files(input_p))
        if not files:
            print("変換できるファイルがありません。", file=sys.stderr)
            return 1
        failed = 0
        for f in files:
            out_p = out_root / f.relative_to(input_p.resolve()) if f.is_absolute() else out_root / f
            out_p = _default_output(out_p)
            try:
                _report(convert(file_path=f, output_path=out_p, **options), out_p, args.assets_dir)
            except Exception as e:
                failed += 1
                print(f"❌ 変換エラー: {f}: {e}", file=sys.stderr)
        print(f"完了: {len(files) - failed} 件成功 / {failed} 件失敗")
        return 1 if failed else 0

    try:
        output_p = Path(args.output) if args.output else _default_output(input_p)
        result = convert(file_path=input_p, output_path=output_p, **options)
        _report(result, output_p, args.assets_dir)
        return 0
    except Exception as e:
        print(f"❌ 変換エラー: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
