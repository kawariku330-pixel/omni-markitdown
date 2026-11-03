"""AudioEngine の単体テスト (TDD)
"""

import wave
import struct
from pathlib import Path
import pytest

from omni_markitdown.core.models import ConversionConfig
from omni_markitdown.engines.audio_engine import AudioEngine


@pytest.fixture
def sample_wav(tmp_path: Path) -> Path:
    """1秒間の無音 WAV ファイルを作成"""
    wav_path = tmp_path / "test_lecture.wav"
    sample_rate = 16000
    num_channels = 1
    duration_sec = 2
    num_frames = sample_rate * duration_sec

    with wave.open(str(wav_path), "wb") as wf:
        wf.setnchannels(num_channels)
        wf.setsampwidth(2)  # 16-bit
        wf.setframerate(sample_rate)
        for _ in range(num_frames):
            wf.writeframes(struct.pack("<h", 0))

    return wav_path


def test_audio_can_handle(sample_wav: Path):
    engine = AudioEngine()
    assert engine.can_handle(sample_wav) is True
    assert engine.can_handle(Path("song.mp3")) is True
    assert engine.can_handle(Path("record.m4a")) is True
    assert engine.can_handle(Path("dummy.pdf")) is False


def test_audio_convert_metadata(sample_wav: Path, tmp_path: Path):
    engine = AudioEngine()
    config = ConversionConfig()
    result = engine.convert(sample_wav, config, tmp_path)

    assert "# 音声ファイル:" in result.markdown
    assert "test_lecture.wav" in result.markdown
    assert "再生時間" in result.markdown
    assert "00:00:02" in result.markdown or "2.0" in result.markdown
    assert "16000 Hz" in result.markdown or "16.0 kHz" in result.markdown
