"""AudioEngine: 音声ファイルメタデータ抽出 ＆ ローカル文字起こしエンジン
"""

from __future__ import annotations

import os
import wave
from datetime import timedelta
from pathlib import Path
from typing import Optional

from omni_markitdown.core.models import ConversionConfig, ConversionResult
from omni_markitdown.engines.base import BaseEngine
from omni_markitdown.utils.file_guard import verify_file_readable


class AudioEngine(BaseEngine):
    """音声ファイルからメタデータ（再生時間・サンプリングレート等）と文字起こしを行うエンジン"""

    SUPPORTED_EXTENSIONS = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".wma"}

    def can_handle(self, path: Path) -> bool:
        return path.suffix.lower() in self.SUPPORTED_EXTENSIONS

    def convert(self, path: Path, config: ConversionConfig, output_dir: Path) -> ConversionResult:
        verify_file_readable(path, config.max_file_size_mb)

        suffix = path.suffix.lower()
        size_mb = path.stat().st_size / (1024 * 1024)

        duration_sec: Optional[float] = None
        sample_rate: Optional[int] = None
        channels: Optional[int] = None

        # 1. メタデータ取得（WAV形式の標準ライブラリ解析）
        if suffix == ".wav":
            try:
                with wave.open(str(path), "rb") as wf:
                    sample_rate = wf.getframerate()
                    channels = wf.getnchannels()
                    frames = wf.getnframes()
                    if sample_rate > 0:
                        duration_sec = frames / float(sample_rate)
            except Exception:
                pass

        # 他形式（soundfileが利用可能な場合）
        if duration_sec is None:
            try:
                import soundfile as sf
                info = sf.info(str(path))
                duration_sec = info.duration
                sample_rate = info.samplerate
                channels = info.channels
            except Exception:
                pass

        # 2. Markdownヘッダーの生成
        lines = [
            f"# 音声ファイル: {path.name}",
            "",
            f"- **形式**: {suffix.upper().replace('.', '')} ({size_mb:.2f} MB)",
        ]

        if duration_sec is not None:
            time_str = str(timedelta(seconds=int(duration_sec)))
            lines.append(f"- **再生時間**: {time_str} ({duration_sec:.1f} 秒)")
        if sample_rate is not None:
            lines.append(f"- **サンプリングレート**: {sample_rate} Hz ({sample_rate / 1000.0:.1f} kHz)")
        if channels is not None:
            lines.append(f"- **チャンネル数**: {'ステレオ (2ch)' if channels == 2 else 'モノラル (1ch)' if channels == 1 else f'{channels}ch'}")

        lines.append("")
        lines.append("---")
        lines.append("")

        # 3. ローカル文字起こし (Speech-to-Text)
        if config.enable_audio_transcription:
            transcription_text = self._transcribe_local(path)
            lines.append("## 文字起こし本文\n")
            lines.append(transcription_text)
        else:
            lines.append("## 文字起こしについて\n")
            lines.append("> ℹ️ 音声の自動文字起こしを行うには `--transcribe` オプションを指定してください。\n> （ローカルSTTパッケージ `pip install omni-markitdown[audio]` が必要です）")

        full_markdown = "\n".join(lines).strip()

        return ConversionResult(
            markdown=full_markdown,
            source_path=path,
            metadata={
                "format": "audio",
                "duration_seconds": duration_sec,
                "sample_rate": sample_rate,
                "channels": channels,
                "file_size_mb": size_mb
            }
        )

    def _transcribe_local(self, path: Path) -> str:
        """ローカルでの文字起こし実行 (faster-whisper または whisper)"""
        try:
            from faster_whisper import WhisperModel
            # 完全ローカル・CPU動作の小型モデル
            model = WhisperModel("base", device="cpu", compute_type="int8")
            segments, info = model.transcribe(str(path), beam_size=5)

            results = []
            for seg in segments:
                t_str = str(timedelta(seconds=int(seg.start)))
                results.append(f"- **[{t_str}]** {seg.text.strip()}")
            return "\n".join(results) if results else "（音声からテキストが検出されませんでした）"
        except ImportError:
            return "> ⚠️ `faster-whisper` がインストールされていません。`pip install faster-whisper` を実行してください。"
        except Exception as e:
            return f"> ⚠️ 文字起こし処理中にエラーが発生しました: {e}"
