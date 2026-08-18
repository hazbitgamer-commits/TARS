"""TARS's self-diagnosis — one check-up that finds what's broken, FIXES
what it can, and explains the rest in plain English.

  python doctor.py            full check-up, auto-fixing what it can
  python doctor.py --quick    silent startup check (returns problems only)
  python doctor.py --no-fix   diagnose only, change nothing

the owner's mate's Mac install took nine rounds of screenshots; this exists so
the next person's takes one. Voice: "run a self check" / "are you healthy".
"""
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

BASE = Path(__file__).resolve().parent
IS_WIN = sys.platform == "win32"
OLLAMA_URL = "http://127.0.0.1:11434"

CRITICAL_IMPORTS = [
    ("numpy", "numpy"), ("sounddevice", "sounddevice"), ("vosk", "vosk"),
    ("faster_whisper", "faster-whisper"), ("requests", "requests"),
    ("psutil", "psutil"), ("dotenv", "python-dotenv"), ("PIL", "Pillow"),
    ("soundfile", "soundfile"),
]
OPTIONAL_IMPORTS = [
    ("kokoro_onnx", "kokoro-onnx", "his best voice (falls back to a robotic one)"),
    ("cv2", "opencv-python", "the camera and screen vision"),
    ("uiautomation", "uiautomation", "fast screen clicking"),
    ("claude_agent_sdk", "claude-agent-sdk", "the big brain that builds things"),
]
MODEL_FILES = [
    (BASE / "wakeword" / "vosk-model-small-en-us-0.15", "wake word",
     "https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip"),
    (BASE / "wakeword" / "vosk-model-spk-0.4", "voice recognition",
     "https://alphacephei.com/vosk/models/vosk-model-spk-0.4.zip"),
    (BASE / "models" / "kokoro-v1.0.onnx", "voice",
     "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx"),
    (BASE / "models" / "voices-v1.0.bin", "voice styles",
     "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin"),
]

problems: list[str] = []   # plain-English, spoken to the owner
fixed: list[str] = []
FIX = True


def _py() -> str:
    if IS_WIN:
        return str(BASE / "runtime" / "python.exe")
    return sys.executable or "python3"


def _ollama_bin() -> str | None:
    exe = shutil.which("ollama")
    if exe:
        return exe
    for guess in (Path(os.environ.get("LOCALAPPDATA", "")) / "Programs"
                  / "Ollama" / "ollama.exe",
                  Path("/Applications/Ollama.app/Contents/Resources/ollama")):
        if guess.exists():
            return str(guess)
    return None


def check_packages() -> None:
    global fixed
    missing = []
    for module, package in CRITICAL_IMPORTS:
        try:
            __import__(module)
        except ImportError:
            missing.append(package)
    if missing and FIX:
        subprocess.run([_py(), "-m", "pip", "install", "-q", *missing],
                       capture_output=True, timeout=600,
                       env=dict(os.environ, PYTHONNOUSERSITE="1"))
        still = [p for m, p in CRITICAL_IMPORTS if p in missing
                 and not _importable(m)]
        fixed += [] if still else [f"installed {len(missing)} missing parts"]
        missing = still
    if missing:
        problems.append("some of my parts are missing: " + ", ".join(missing))
    for module, package, what in OPTIONAL_IMPORTS:
        if not _importable(module):
            problems.append(f"{what} is unavailable ({package} not installed)")


def _importable(module: str) -> bool:
    try:
        __import__(module)
        return True
    except Exception:
        return False


def check_models() -> None:
    for path, what, url in MODEL_FILES:
        if path.exists():
            continue
        if not FIX:
            problems.append(f"my {what} model is missing")
            continue
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            if url.endswith(".zip"):
                tmp = path.parent / "_dl.zip"
                urllib.request.urlretrieve(url, tmp)
                import zipfile

                with zipfile.ZipFile(tmp) as z:
                    z.extractall(path.parent)
                tmp.unlink(missing_ok=True)
            else:
                urllib.request.urlretrieve(url, path)
            fixed.append(f"downloaded my {what} model")
        except Exception:
            problems.append(f"my {what} model is missing and wouldn't download")


def check_brain() -> None:
    from platform_caps import LITE

    want = ["qwen2.5:7b"] + (["qwen2.5:3b"] if LITE
                             else ["qwen2.5:7b-router", "qwen3:8b"])
    try:
        with urllib.request.urlopen(f"{OLLAMA_URL}/api/tags", timeout=5) as r:
            have = [m["name"] for m in json.load(r).get("models", [])]
    except Exception:
        exe = _ollama_bin()
        if exe and FIX:
            try:
                subprocess.Popen([exe, "serve"],
                                 stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL,
                                 creationflags=(subprocess.CREATE_NO_WINDOW
                                                if IS_WIN else 0))
                import time

                for _ in range(20):
                    time.sleep(1)
                    try:
                        urllib.request.urlopen(f"{OLLAMA_URL}/api/tags", timeout=3)
                        fixed.append("started my thinking engine")
                        return check_brain()
                    except Exception:
                        continue
            except Exception:
                pass
        problems.append("my thinking engine (Ollama) isn't running"
                        + ("" if exe else " and isn't installed — "
                                          "get it from ollama.com"))
        return
    missing = [m for m in want if not any(m in h for h in have)]
    if missing and FIX and _ollama_bin():
        for m in missing:
            if m.endswith("-router"):
                subprocess.run([_ollama_bin(), "cp", "qwen2.5:7b", m],
                               capture_output=True, timeout=120)
            else:
                subprocess.run([_ollama_bin(), "pull", m],
                               capture_output=True, timeout=3600)
        fixed.append(f"downloaded {len(missing)} brain model(s)")
        missing = []
    if missing:
        problems.append("brain models missing: " + ", ".join(missing))


def check_audio() -> None:
    try:
        import numpy as np
        import sounddevice as sd

        import audio_out

        idx = audio_out.pick_input()
        if idx is None:
            problems.append("I can't find a microphone at all")
            return
        # ASK THE LOOP THAT'S ALREADY LISTENING, don't open a second stream.
        #
        # This check opened its own recording on a device TARS itself has
        # held open since startup. A second stream on a busy device hands
        # back near-silence, so the test concluded the microphone was broken
        # and sent him to Windows sound settings — 45 times across the logs,
        # every one of them while his voice commands were working perfectly.
        #
        # Someone hit this before and responded by lowering the threshold
        # (the comment below). That treated the symptom: the reading was
        # never measuring the microphone, it was measuring the contention.
        #
        # The listening loop publishes what it actually hears, from the
        # stream that is genuinely open. That's the real answer, and no test
        # run from out here can beat it.
        try:
            import dashboard

            heard_at, heard_level = dashboard.EARS
            if heard_at and time.time() - heard_at < 120:
                if heard_level <= 0.0:
                    problems.append(
                        "my microphone is open but completely dead — nothing "
                        "at all is arriving from it")
                return          # a live reading settles it either way
        except Exception:
            pass                # no loop running (doctor run on its own)

        rec = sd.rec(int(16000 * 1.2), samplerate=16000, channels=1,
                     dtype="float32", device=idx)
        sd.wait()
        # A working mic in a quiet room still has a noise floor (the owner's
        # reads about 0.003). PURE zeros mean the device gave us nothing —
        # muted, disabled, or already open elsewhere. The old test called a
        # quiet room a broken microphone and sent him to Windows settings
        # five times in one day while his voice commands were working fine.
        if not np.any(rec):
            problems.append(
                "my microphone handed back pure silence — it's muted or "
                "disabled, or something else has hold of it"
                + ("" if IS_WIN else
                   " (check Microphone permission in System Settings)"))
        elif float(np.sqrt(np.mean(rec ** 2))) < 0.00002:
            problems.append(
                "my microphone is barely registering anything — "
                + ("check its level in Windows sound settings"
                   if IS_WIN else "check its input level in System Settings"))
        if not any(d["max_output_channels"] > 0 for d in sd.query_devices()):
            problems.append("I have no speakers to talk through")
    except Exception as e:
        problems.append(f"my audio system wouldn't answer ({type(e).__name__})")


def check_extras() -> None:
    from platform_caps import LITE

    if not LITE:
        scad = Path(r"C:\Program Files\OpenSCAD\openscad.exe")
        if not scad.exists() and not shutil.which("openscad"):
            problems.append("OpenSCAD is missing, so I can't build 3D designs")
    env = BASE / ".env"
    text = env.read_text(encoding="utf-8") if env.exists() else ""
    if "CLAUDE_CODE_OAUTH_TOKEN" not in text:
        problems.append("my big brain isn't connected — "
                        "the owner needs to run claude setup-token")
    free = shutil.disk_usage(BASE).free / 1e9
    if free < 3:
        problems.append(f"only {free:.1f} gigabytes of disk space left")


def run_checks(fix: bool = True) -> tuple[list[str], list[str]]:
    global FIX, problems, fixed
    FIX, problems, fixed = fix, [], []
    for check in (check_packages, check_models, check_brain, check_audio,
                  check_extras):
        try:
            check()
        except Exception as e:
            problems.append(f"a self-check failed: {type(e).__name__}")
    return problems, fixed


def spoken_summary(problems: list[str], fixed: list[str]) -> str:
    if not problems and not fixed:
        return "Full check-up done — everything's healthy."
    parts = []
    if fixed:
        parts.append("I fixed " + ", and ".join(fixed))
    if problems:
        parts.append(("but " if fixed else "")
                     + ("here's what's wrong: " if len(problems) > 1
                        else "one thing's wrong: ")
                     + "; ".join(problems))
    else:
        parts.append("everything else is healthy")
    return ". ".join(p[0].upper() + p[1:] for p in parts) + "."


if __name__ == "__main__":
    quick = "--quick" in sys.argv
    probs, fx = run_checks(fix="--no-fix" not in sys.argv)
    if quick:
        print(json.dumps({"problems": probs, "fixed": fx}))
    else:
        print("=" * 52)
        print("  TARS SELF-DIAGNOSIS")
        print("=" * 52)
        for f in fx:
            print(f"  FIXED   {f}")
        for p in probs:
            print(f"  PROBLEM {p}")
        if not probs and not fx:
            print("  ALL HEALTHY")
        print("\n" + spoken_summary(probs, fx))
