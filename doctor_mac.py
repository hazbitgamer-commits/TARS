"""TARS Doctor — one-command health check for Mac/Linux Lite installs.
Run:  bash tars_mac.sh --doctor
Prints a short PASS/FAIL report to screenshot and send back. Speaks a
test line at the end if the voice stack is healthy."""
import sys
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent
RESULTS = []


def check(name, fn):
    try:
        detail = fn()
        RESULTS.append((True, name, detail or ""))
    except Exception as e:
        RESULTS.append((False, name, f"{type(e).__name__}: {e}"))


def ollama():
    import requests

    r = requests.get("http://127.0.0.1:11434/api/tags", timeout=5)
    names = [m["name"] for m in r.json().get("models", [])]
    need = [n for n in ("qwen2.5:7b", "qwen2.5:3b") if not any(
        n in x for x in names)]
    if need:
        raise RuntimeError(f"models missing: {need} — re-run the installer "
                           "one-liner (it pulls them)")
    return f"{len(names)} models ready (7b talks, 3b routes)"


def vosk_model():
    from vosk import KaldiRecognizer, Model

    path = BASE / "wakeword" / "vosk-model-small-en-us-0.15"
    if not path.is_dir():
        raise RuntimeError(f"model folder missing: {path}")
    KaldiRecognizer(Model(str(path)), 16000, '["hey tars", "[unk]"]')
    return "wake-word model loads"


def kokoro_files():
    for f in ("kokoro-v1.0.onnx", "voices-v1.0.bin"):
        if not (BASE / "models" / f).exists():
            raise RuntimeError(f"missing models/{f} — re-run setup_mac.sh")
    import kokoro_onnx  # noqa: F401

    return "voice files + library present"


def whisper_lib():
    import faster_whisper  # noqa: F401

    return "hearing library present (model downloads on first listen)"


def microphone():
    import numpy as np
    import sounddevice as sd

    import audio_out

    all_inputs = [f"{i}:{d['name'][:30]}" for i, d in
                  enumerate(sd.query_devices()) if d["max_input_channels"] > 0]
    print(f"        (all input devices: {'; '.join(all_inputs)})")
    idx = audio_out.pick_input()
    name = sd.query_devices()[idx]["name"] if idx is not None else "(default)"
    for rate in (16000, 48000, 44100):
        try:
            rec = sd.rec(int(rate * 2), samplerate=rate, channels=1,
                         dtype="float32", device=idx)
            sd.wait()
            rms = float(np.sqrt(np.mean(rec ** 2)))
            level = ("HEARING YOU (make noise while this runs to be sure)"
                     if rms > 0.003 else
                     "SILENT - likely macOS mic permission: System Settings "
                     "> Privacy & Security > Microphone > enable Terminal")
            note = "" if rate == 16000 else \
                f" [NOTE: 16kHz unsupported, works at {rate} — TARS needs a resample patch]"
            return f"mic '{name[:28]}' @{rate}Hz level={rms:.4f} → {level}{note}"
        except Exception:
            continue
    raise RuntimeError(f"could not record from mic '{name[:28]}' at any rate")


def portaudio():
    """sounddevice is a wrapper around PortAudio, which macOS doesn't ship.
    Without it every audio import dies — which reads as "voice recognition
    wouldn't install"."""
    # test the SYMPTOM (does the audio library actually load?) rather than
    # the cause — Windows bundles PortAudio differently and find_library
    # returns nothing there even when audio works perfectly
    try:
        import sounddevice  # noqa: F401
    except Exception as e:
        import ctypes.util

        if not ctypes.util.find_library("portaudio"):
            raise RuntimeError(
                "PortAudio is missing — TARS can't hear or speak without it. "
                "Fix: brew install portaudio, then run setup_mac.sh again")
        raise RuntimeError(f"the audio library won't load: {e}")
    return "audio library loads"


def memory_fit():
    """A 7B model on an 8GB machine makes the WHOLE computer crawl."""
    sys.path.insert(0, str(BASE))
    import platform_caps as caps

    gb = caps.total_ram_gb()
    chat, router = caps.chat_model(), caps.router_model()
    if caps.tight_on_memory():
        return (f"{gb:.0f}GB RAM — using the small brain ({chat}) so the "
                f"machine stays usable")
    return f"{gb:.0f}GB RAM — chat {chat}, router {router}"


def big_brain():
    """The token is useless without the claude command it drives."""
    import os
    import shutil

    from dotenv import load_dotenv

    load_dotenv(BASE / ".env")
    token = (os.getenv("CLAUDE_CODE_OAUTH_TOKEN") or "").strip()
    key = (os.getenv("OPENAI_API_KEY") or "").strip()
    if not token and not key:
        return "off (no key set — optional, everything else works)"
    try:
        import claude_agent_sdk  # noqa: F401
    except ImportError:
        raise RuntimeError("the Python SDK is missing — run setup_mac.sh again")
    if token and not shutil.which("claude"):
        raise RuntimeError("token is set but the `claude` command isn't "
                           "installed, so big jobs can never run. Fix: "
                           "npm install -g @anthropic-ai/claude-code")
    return "ready"


def speak_test():
    import sounddevice as sd

    sys.path.insert(0, str(BASE))
    import tts

    res = tts._synth("TARS Doctor here. If you can hear this, my voice works.")
    if res is None:
        raise RuntimeError("synthesis returned nothing (kokoro failed, edge-tts offline?)")
    sd.play(res[0], res[1])
    sd.wait()
    return "spoke a test line — did you hear it?"


print("=" * 46)
print("  TARS DOCTOR")
print("=" * 46)
print("(speak or clap during the mic test — ~8s)\n")
check("Audio library (PortAudio)", portaudio)
check("Memory vs model size", memory_fit)
check("Ollama brain server + models", ollama)
check("Wake word (Vosk)", vosk_model)
check("Voice (Kokoro)", kokoro_files)
check("Hearing (Whisper)", whisper_lib)
check("Microphone", microphone)
check("Big brain (optional)", big_brain)


def beep_then_listen():
    """The wake sequence in miniature: play a beep, then immediately
    record — if the after-beep level collapses, the Mac is stalling the
    mic when output plays (the 'beeps but doesn't listen' bug)."""
    import numpy as np
    import sounddevice as sd

    import audio_out

    idx = audio_out.pick_input()
    t = np.linspace(0, 0.15, int(44100 * 0.15), False)
    tone = (0.3 * np.sin(2 * np.pi * 880 * t)).astype(np.float32)
    sd.play(tone, 44100)
    sd.wait()
    rec = sd.rec(int(16000 * 2.5), samplerate=16000, channels=1,
                 dtype="float32", device=idx)
    sd.wait()
    rms = float(np.sqrt(np.mean(rec ** 2)))
    if rms < 0.0005:
        raise RuntimeError(f"mic DEAD right after a beep (level {rms:.5f}) "
                           "— the Mac stalls input during output")
    return f"mic alive after beep, level {rms:.4f} (talk during this test)"


check("Listen-after-beep", beep_then_listen)
check("Speaker output", speak_test)
print()
for ok, name, detail in RESULTS:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    if detail:
        print(f"        {detail}")
print()
fails = [r for r in RESULTS if not r[0]]
print("ALL CLEAR — start TARS with: bash tars_mac.sh" if not fails else
      f"{len(fails)} problem(s) above — screenshot this whole report and send it.")
