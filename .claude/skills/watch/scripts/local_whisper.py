"""Free local transcription fallback (faster-whisper, CPU). Decodes via ffmpeg -> numpy."""
from __future__ import annotations
import subprocess
import numpy as np


def transcribe_local(video_path: str, model: str = "small.en") -> list[dict]:
    from faster_whisper import WhisperModel  # pip install faster-whisper
    raw = subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-i", video_path, "-vn", "-ac", "1",
         "-ar", "16000", "-f", "s16le", "-"],
        capture_output=True, check=True).stdout
    audio = np.frombuffer(raw, np.int16).astype(np.float32) / 32768
    segs, _ = WhisperModel(model, compute_type="int8").transcribe(audio)
    return [{"start": round(s.start, 2), "end": round(s.end, 2), "text": s.text.strip()} for s in segs]
