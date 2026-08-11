"""Why doesn't he answer? — walks the whole voice chain and names the
first broken link.

"Doesn't respond" can mean six different faults, and the person in front
of the machine can't tell them apart: no microphone, no permission, the
wake word never firing, speech not transcribing, the brain being offline,
or the voice failing. This runs each link in order, stops at the first
real failure, and writes voice_report.txt to send on.

Run:  python3 voice_check.py
"""
import datetime
import subprocess
import sys
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))
REPORT = BASE / "voice_report.txt"

LINES: list[str] = []


def say(text: str = "") -> None:
    print(text)
    LINES.append(text)


def step(number: int, title: str) -> None:
    say("")
    say(f"[{number}] {title}")


def fail(what: str, fix: str) -> None:
    say(f"    BROKEN: {what}")
    say(f"    FIX:    {fix}")


def ok(detail: str) -> None:
    say(f"    ok — {detail}")


def main() -> int:
    say("=" * 52)
    say("  TARS voice check")
    say(f"  {datetime.datetime.now():%Y-%m-%d %H:%M}  {sys.platform}")
    say("=" * 52)

    # ---- 0. is he even running? ----
    step(0, "Is TARS running?")
    engine = False
    try:
        import urllib.request

        with urllib.request.urlopen("http://127.0.0.1:8765/api/state",
                                    timeout=4) as response:
            import json

            engine = True
            ok(f"engine up — status {json.loads(response.read()).get('status')}")
    except Exception:
        say("    not running (that's fine for this test — it tests the parts)")

    # ---- 1. the audio library ----
    step(1, "Audio library")
    try:
        import numpy as np
        import sounddevice as sd
    except Exception as e:
        fail(f"the audio library won't load ({e})",
             "brew install portaudio && bash setup_mac.sh")
        return finish(1)
    ok("sounddevice loaded")

    # ---- 2. a microphone, and does it hear anything ----
    step(2, "Microphone")
    try:
        import audio_out

        index = audio_out.pick_input()
    except Exception:
        index = None
    try:
        devices = sd.query_devices()
        inputs = [f"{i}: {d['name'][:34]}" for i, d in enumerate(devices)
                  if d["max_input_channels"] > 0]
    except Exception as e:
        fail(f"no audio devices at all ({e})", "check macOS sound settings")
        return finish(2)
    say("    inputs found: " + ("; ".join(inputs) if inputs else "NONE"))
    if not inputs:
        fail("no microphone", "plug one in, or check System Settings > Sound")
        return finish(2)

    say("    >>> SAY SOMETHING NOW (3 seconds) <<<")
    try:
        clip = sd.rec(int(16000 * 3), samplerate=16000, channels=1,
                      dtype="float32", device=index)
        sd.wait()
    except Exception as e:
        fail(f"couldn't record ({e})",
             "System Settings > Privacy & Security > Microphone > allow Terminal")
        return finish(2)
    level = float(np.sqrt(np.mean(clip ** 2)))
    peak = float(np.max(np.abs(clip)))
    say(f"    level={level:.5f} peak={peak:.3f}")
    if peak == 0.0:
        fail("the microphone returned pure silence",
             "macOS is blocking it: System Settings > Privacy & Security > "
             "Microphone > turn ON for Terminal (or iTerm), then try again")
        return finish(2)
    if level < 0.002:
        fail("the microphone is barely picking anything up",
             "check the input level in System Settings > Sound > Input, and "
             "that the right mic is selected")
        return finish(2)
    ok(f"hearing you (level {level:.4f})")

    # ---- 3. the wake word ----
    step(3, "Wake word ('hey TARS')")
    model_dir = BASE / "wakeword" / "vosk-model-small-en-us-0.15"
    if not model_dir.is_dir():
        fail("the wake-word model isn't downloaded",
             "bash setup_mac.sh  (it fetches it)")
        return finish(3)
    try:
        from vosk import KaldiRecognizer, Model

        recogniser = KaldiRecognizer(Model(str(model_dir)), 16000,
                                     '["hey tars", "[unk]"]')
    except Exception as e:
        fail(f"the wake-word engine won't start ({e})",
             "bash setup_mac.sh  to reinstall it")
        return finish(3)
    say('    >>> SAY "HEY TARS" NOW (4 seconds) <<<')
    heard = ""
    try:
        clip = sd.rec(int(16000 * 4), samplerate=16000, channels=1,
                      dtype="int16", device=index)
        sd.wait()
        import json

        recogniser.AcceptWaveform(clip.tobytes())
        heard = json.loads(recogniser.FinalResult()).get("text", "")
    except Exception as e:
        fail(f"the wake-word check errored ({e})", "send this report on")
        return finish(3)
    say(f"    it heard: {heard!r}")
    if "tars" not in heard.lower():
        fail("it didn't pick up the wake word",
             "say it clearly and a bit louder, closer to the mic. If it never "
             "works, the mic level is too low — System Settings > Sound > Input")
        # not fatal: keep testing the rest so the report is complete
    else:
        ok("wake word recognised")

    # ---- 4. understanding speech ----
    step(4, "Understanding speech (Whisper)")
    try:
        from stt import Transcriber

        transcriber = Transcriber()
    except Exception as e:
        fail(f"the speech engine won't load ({e})",
             "bash setup_mac.sh  (it may still be downloading its model)")
        return finish(4)
    say("    >>> SAY A SENTENCE NOW (4 seconds) <<<")
    try:
        clip = sd.rec(int(16000 * 4), samplerate=16000, channels=1,
                      dtype="float32", device=index)
        sd.wait()
        words = transcriber.transcribe(clip.flatten())
    except Exception as e:
        fail(f"transcription failed ({e})", "send this report on")
        return finish(4)
    say(f"    it understood: {words!r}")
    if not (words or "").strip():
        fail("it heard sound but no words",
             "speak a full sentence at normal volume; if it stays empty the "
             "mic level is too low")
    else:
        ok("speech understood")

    # ---- 5. the thinking ----
    step(5, "The brain (Ollama)")
    try:
        import requests

        tags = requests.get("http://127.0.0.1:11434/api/tags", timeout=8)
        installed = [m["name"] for m in tags.json().get("models", [])]
    except Exception:
        fail("Ollama isn't running — this is the most common cause of "
             "'he doesn't answer'",
             "open the Ollama app (or run: ollama serve), then start TARS again")
        return finish(5)
    say(f"    models installed: {', '.join(installed) or 'NONE'}")
    import platform_caps as caps

    wanted = {caps.chat_model(), caps.router_model()}
    missing = [m for m in wanted if not any(m in i for i in installed)]
    if missing:
        fail(f"missing model(s): {', '.join(missing)}",
             "ollama pull " + " && ollama pull ".join(missing))
        return finish(5)
    ok(f"{caps.total_ram_gb():.0f}GB RAM — using {caps.chat_model()}")

    say("    asking it to think (this also times it)…")
    started = time.time()
    try:
        reply = requests.post("http://127.0.0.1:11434/api/chat", json={
            "model": caps.chat_model(),
            "messages": [{"role": "user", "content": "Say hello in five words."}],
            "stream": False, "options": {"num_predict": 20}}, timeout=180)
        answer = reply.json()["message"]["content"].strip()
    except Exception as e:
        fail(f"the brain didn't answer ({e})",
             "restart the Ollama app, then try again")
        return finish(5)
    took = time.time() - started
    say(f"    it said: {answer[:60]!r}  in {took:.1f}s")
    if took > 25:
        fail(f"it took {took:.0f} seconds — far too slow to feel like talking",
             "this machine is short on memory for that model. TARS now picks "
             "a smaller one automatically — make sure you're on the latest "
             "version (see the repair kit in INSTALL_MAC.md)")
    else:
        ok("thinking at a usable speed")

    # ---- 6. the voice ----
    step(6, "His voice")
    try:
        import tts

        audio = tts._synth("Voice check complete.")
        if audio is None:
            raise RuntimeError("nothing came back")
        sd.play(audio[0], audio[1])
        sd.wait()
        ok("spoke a line — did you hear it?")
    except Exception as e:
        fail(f"speech failed ({e})",
             "bash setup_mac.sh  to re-download the voice model")
    return finish(0)


def finish(broken_at: int) -> int:
    say("")
    say("=" * 52)
    if broken_at:
        say(f"  FIRST BROKEN LINK: step {broken_at} above.")
        say("  Do the FIX line under it, then run this again.")
    else:
        say("  Every link in the chain works.")
        say("  If he still doesn't answer, start him with: bash tars_mac.sh")
    say("=" * 52)
    try:
        REPORT.write_text("\n".join(LINES), encoding="utf-8")
        print(f"\nSaved to {REPORT} — send that file if you're stuck.")
    except OSError:
        pass
    return broken_at


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
