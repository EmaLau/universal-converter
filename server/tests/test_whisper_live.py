"""Trascrizione con un servizio Whisper vero (speaches, whisper.cpp...): solo se WHISPER_TEST_URL e' impostato.

In GitHub Actions il job "Whisper" avvia speaches con il modello tiny, genera una frase con espeak-ng e controlla
che il convertitore la riconosca. In locale:
    WHISPER_TEST_URL=http://localhost:8000 WHISPER_TEST_MODEL=Systran/faster-whisper-tiny.en pytest tests/test_whisper_live.py
"""
import asyncio
import os
import shutil
import subprocess
from types import SimpleNamespace

import pytest

from converter.transcribe import Transcriber

URL = os.environ.get("WHISPER_TEST_URL", "")
pytestmark = pytest.mark.skipif(not URL or not shutil.which("ffmpeg") or not shutil.which("espeak-ng"),
                                reason="servono WHISPER_TEST_URL, ffmpeg ed espeak-ng")


def speech(tmp_path):
    wav = tmp_path / "speech.wav"
    subprocess.run(["espeak-ng", "-v", "en-us", "-s", "140", "-w", str(wav),
                    "Hello world. This is a transcription test for the universal converter."], check=True)
    return wav


@pytest.mark.parametrize("fmt", ["txt", "srt", "vtt"])
def test_live_transcription(tmp_path, fmt):
    t = Transcriber(URL, os.environ.get("WHISPER_TEST_MODEL", "Systran/faster-whisper-tiny.en"))
    job = SimpleNamespace(options={"language": "en"}, target=fmt, step="", note="")
    out = asyncio.run(t(job, speech(tmp_path), fmt, tmp_path))
    text = out.read_text().lower()
    assert "hello" in text and "test" in text, text
    if fmt == "srt":
        assert "-->" in text and text.lstrip().startswith("1")
    if fmt == "vtt":
        assert text.startswith("webvtt")
