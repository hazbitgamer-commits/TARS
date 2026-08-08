"""Wake word engines.

Primary: Vosk keyword spotting for "Hey TARS" — free, local, no account.
Fallback: openWakeWord's built-in "Hey Jarvis" if the Vosk model is missing.

Both expose: .process(int16 numpy frame) -> bool (woke?), .reset(), .name
"""
import json
from pathlib import Path

import numpy as np

class VoskWake:
    name = "Hey TARS"

    def __init__(self, base: Path):
        from vosk import KaldiRecognizer, Model, SetLogLevel

        SetLogLevel(-1)  # silence vosk's startup chatter
        model_dir = base / "wakeword" / "vosk-model-small-en-us-0.15"
        if not model_dir.exists():
            raise FileNotFoundError(model_dir)
        self._rec = KaldiRecognizer(
            Model(str(model_dir)), 16000, json.dumps(["hey tars", "[unk]"])
        )

    def process(self, pcm: np.ndarray) -> bool:
        # Only trust FINAL results — partials hallucinate the wake phrase.
        if self._rec.AcceptWaveform(pcm.tobytes()):
            heard = json.loads(self._rec.Result()).get("text", "")
            if "hey tars" in heard:
                self._rec.Reset()
                return True
        return False

    def reset(self) -> None:
        self._rec.Reset()


class OwwWake:
    name = "Hey Jarvis"

    def __init__(self, threshold: float = 0.5):
        import openwakeword
        from openwakeword.model import Model

        openwakeword.utils.download_models(model_names=["hey_jarvis_v0.1"])
        self._model = Model(wakeword_models=["hey_jarvis_v0.1"], inference_framework="onnx")
        self._threshold = threshold

    def process(self, pcm: np.ndarray) -> bool:
        scores = self._model.predict(pcm)
        return max(scores.values()) >= self._threshold

    def reset(self) -> None:
        self._model.reset()


def make_wakeword(base: Path):
    """Best available engine, or None (falls back to press-Enter mode)."""
    for engine in (lambda: VoskWake(base), OwwWake):
        try:
            return engine()
        except Exception as e:
            print(f"(wake engine unavailable: {e})")
    return None
