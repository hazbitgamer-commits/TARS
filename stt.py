"""Speech-to-text via faster-whisper, CPU int8 (AMD GPU = no CUDA here)."""
import numpy as np
from faster_whisper import WhisperModel

SAMPLE_WARMUP = 16000  # one second of silence


class Transcriber:
    def __init__(self, model_size: str = "small.en"):  # base.en misheard too much
        print(f"Loading whisper '{model_size}' model...")
        self.model = WhisperModel(model_size, device="cpu", compute_type="int8")
        self.last_confidence = 0.0  # mean log-probability of the kept segments
        # warm up: the first inference carries one-off setup cost
        self.transcribe(np.zeros(SAMPLE_WARMUP, dtype=np.float32))

    # Whisper invents these when it hears noise/music instead of speech
    ARTIFACTS = ("](", "to learn more", "thanks for watching", "thank you for watching",
                 "like and subscribe", "see you in the next", "captions by",
                 "transcription by", "subtitles by", "copyright ©")

    def transcribe(self, audio_16k_f32: np.ndarray) -> str:
        segments, _ = self.model.transcribe(
            audio_16k_f32, language="en", beam_size=2, vad_filter=True,
            condition_on_previous_text=False,
            initial_prompt=(
                "Jacob is talking to TARS, his computer voice assistant. "
                "TARS opens apps, folders like the TARS folder, and files. "
                "Apps include Claude, Brave, Chrome, YouTube, Spotify, Steam, "
                "Discord, Obsidian, and File Explorer. TARS can show its brain "
                "page and its dashboard, and controls the Robovac vacuum, "
                "which Jacob calls Basel. Jacob often says: override quiet hours."
            ),
        )
        parts, logprobs = [], []
        for s in segments:
            # the model's own doubt: probably not speech, or very low confidence
            if s.no_speech_prob > 0.6 or s.avg_logprob < -1.0:
                continue
            parts.append(s.text.strip())
            logprobs.append(s.avg_logprob)
        text = " ".join(parts).strip()
        self.last_confidence = (sum(logprobs) / len(logprobs)) if logprobs else -2.0
        low = text.lower()
        if any(a in low for a in self.ARTIFACTS):
            return ""  # a caption ghost, not Jacob
        return text
