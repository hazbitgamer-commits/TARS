"""TARS — always-on voice assistant. Core loop (Phase 1).

Flow: wake word ("Hey Jarvis" for now, custom "TARS" later) -> record command
      -> transcribe (whisper) -> brain (Ollama, local) -> speak (edge-tts, free).

Wake word engine: openWakeWord — fully local, free, no account needed.
If it fails to load, falls back to press-Enter-to-talk.
"""
try:
    import truststore

    truststore.inject_into_ssl()  # trust the OS certificate store (an old
    # Avast-era fix on Windows; harmless elsewhere, optional everywhere)
except ImportError:
    pass  # a Mac without it boots fine — this crashed the first Mac install

import datetime
import json
import sys
import threading
import time
from pathlib import Path

import numpy as np
import sounddevice as sd
from dotenv import load_dotenv

BASE = Path(__file__).parent
load_dotenv(BASE / ".env")

import quiet_spawn

# TARS runs windowless (pythonw), so any console child — the Claude CLI
# most of all — gets handed its own black window on the owner's desktop.
quiet_spawn.hide()

from brain import Brain      # noqa: E402
from stt import Transcriber  # noqa: E402
from tts import Speaker      # noqa: E402
from ui import StatusUI      # noqa: E402

SAMPLE_RATE = 16000
FRAME_LEN = 1280         # 80 ms frames — what openWakeWord expects
WAKE_THRESHOLD = 0.5     # openWakeWord confidence needed to wake
MAX_COMMAND_SEC = 12     # hard stop for one command
SILENCE_STOP_SEC = 0.8   # stop recording after this much silence
MIN_SPEECH_SEC = 0.4     # ignore recordings shorter than this
WAIT_FOR_SPEECH_SEC = 6  # after the wake word, give up if no speech starts
FOLLOWUP_SEC = 5         # after a reply, keep listening this long for more
CONFIRM_BELOW = -0.55    # shaky transcription confidence: ask "did you say..?"

END_WORDS = ("that's all", "thats all", "that is all", "that's it", "thats it",
             "never mind", "nevermind", "stop listening", "thanks tars",
             "thank you tars")
LAST_AUDIO = None      # the last recorded command — voice_id learns from it
LAST_SPEAKER = None    # who TARS thinks is talking (None = unknown/guest)
TRANSCRIBER = None     # the one whisper model, shared with the phone bridge
SLEEP_WORDS = ("go to sleep", "sleep mode", "go quiet")
WAKE_UP_WORDS = ("wake up", "i'm back", "wakey")
SHUTDOWN_WORDS = ("goodbye tars", "goodbye, tars", "shut down tars", "tars shut down",
                  "shut yourself down", "power down", "close yourself",
                  "turn yourself off", "close tars", "turn off tars",
                  "quit tars", "exit tars", "power off")


def vault_conversation_line(day: str, hhmm: str, kind: str, text: str) -> None:
    """Append one exchange line to the vault's daily conversation note."""
    conv_dir = BASE / "vault" / "Conversations"
    conv_dir.mkdir(parents=True, exist_ok=True)
    note = conv_dir / f"Conversation {day}.md"
    if not note.exists():
        note.write_text(f"---\ncreated: {day}\ntags:\n  - conversation\n---\n\n",
                        encoding="utf-8")
        journal_dir = BASE / "vault" / "Journal"
        journal_dir.mkdir(exist_ok=True)
        with open(journal_dir / f"Journal {day}.md", "a", encoding="utf-8") as jf:
            jf.write(f"- Conversation log: [[Conversation {day}]]\n")
    who = "the owner" if kind == "heard" else "TARS"
    with open(note, "a", encoding="utf-8") as f:
        f.write(f"- **{hhmm}** {who}: {text}\n")


def log(kind: str, text: str) -> None:
    try:  # logs are kept forever and read by the big brain — no passwords
        import secrets_store

        text = secrets_store.redact(text)
    except Exception:
        pass
    now = datetime.datetime.now()
    day = datetime.date.today().isoformat()
    line = json.dumps(
        {"t": now.isoformat(timespec="seconds"), "kind": kind, "text": text}
    )
    logs = BASE / "logs"
    logs.mkdir(exist_ok=True)
    with open(logs / f"{day}.jsonl", "a", encoding="utf-8") as f:
        f.write(line + "\n")
    try:
        vault_conversation_line(day, now.strftime("%H:%M"), kind, text)
    except OSError:
        pass


class AutoGain:
    """Boosts quiet mic input toward a target loudness — early-morning
    whisper-voice still reaches the wake word and the transcriber."""

    def __init__(self, target: float = 0.06, limit: float = 8.0):
        self.gain = 2.0
        self.target = target
        self.limit = limit

    def process(self, pcm: np.ndarray) -> np.ndarray:
        f = pcm.astype(np.float32) / 32768.0
        rms = float(np.sqrt(np.mean(f**2)))
        if rms > 0.003:  # adapt on signal, not on silence
            desired = self.target / max(rms, 1e-6)
            self.gain = float(np.clip(0.9 * self.gain + 0.1 * desired, 1.0, self.limit))
        boosted = np.clip(f * self.gain, -1.0, 1.0)
        return (boosted * 32767).astype(np.int16)


# --- the deaf-TARS watchdog -------------------------------------------
#
# The conversation loop switches the microphone OFF before TARS speaks, and
# only switches it back on once the reply has finished. That's correct — it
# stops TARS hearing itself — but it means anything that blocks mid-reply
# leaves the microphone off with nobody left to turn it back on.
#
# It happened for real: "clip that" uploaded a 29MB video to Telegram on the
# conversation thread. For the length of that upload TARS was running, the
# dashboard answered normally, and it could not hear a thing. From the
# outside it looked like TARS had died, and it never came back on its own.
#
# That particular upload now runs on its own thread, but the trap isn't
# specific to clipping — ANY slow skill can do it. So rather than trusting
# every skill to behave, this watches from outside: if TARS hasn't been
# listening for a few minutes, something has it stuck, and it restarts
# itself rather than sitting there deaf.
STUCK_AFTER = 180        # seconds not listening before TARS is presumed stuck
_alive = {"state": "listening", "since": time.time(), "recovered": 0.0}


def note_state(state: str) -> None:
    """Every state change lands here, so the watchdog knows how long TARS
    has been out of the listening state."""
    if state != _alive["state"]:
        _alive["state"] = state
        _alive["since"] = time.time()


def _watchdog() -> None:
    while True:
        time.sleep(10)
        try:
            stuck = (_alive["state"] != "listening"
                     and time.time() - _alive["since"] > STUCK_AFTER)
            # once per ten minutes at most: a restart that fails shouldn't
            # turn into a machine that restarts itself forever
            if not stuck or time.time() - _alive["recovered"] < 600:
                continue
            _alive["recovered"] = time.time()
            stuck_for = int(time.time() - _alive["since"])
            log("said", f"(watchdog: stuck in '{_alive['state']}' for "
                        f"{stuck_for}s — restarting)")
            print(f"[watchdog] stuck in '{_alive['state']}' for {stuck_for}s "
                  f"— restarting the engine", flush=True)
            try:
                import tars_phone

                tars_phone.send(
                    "Something jammed me up and I'd gone deaf — restarting "
                    "myself now. Give me a few seconds.", force=True)
            except Exception:
                pass
            import os
            import subprocess

            helper = BASE / "skills" / "restart_engine" / "_do_restart.py"
            if helper.exists():
                subprocess.Popen(
                    [sys.executable, str(helper), str(os.getpid()), str(BASE)],
                    cwd=str(BASE), close_fds=True,
                    creationflags=(subprocess.DETACHED_PROCESS
                                   | subprocess.CREATE_NO_WINDOW)
                    if sys.platform == "win32" else 0)
        except Exception:
            pass          # a broken watchdog must never take TARS down with it


def _mid_game() -> bool:
    """Is he in a game right now? If so, one command means one command."""
    try:
        import game_watch

        return game_watch.playing_now()
    except Exception:
        return False


def beep(freq: int = 880, dur: float = 0.12) -> None:
    t = np.linspace(0, dur, int(44100 * dur), False)
    tone = (0.25 * np.sin(2 * np.pi * freq * t)).astype(np.float32)
    sd.play(tone, 44100)
    sd.wait()


def ambient_threshold(stream, agc: AutoGain) -> float:
    """Listen briefly to the room and set a speech-detection threshold."""
    chunks = []
    for _ in range(max(1, int(0.5 * SAMPLE_RATE / FRAME_LEN))):
        data, _ = stream.read(FRAME_LEN)
        chunks.append(agc.process(np.frombuffer(bytes(data), dtype=np.int16)))
    ambient = np.concatenate(chunks).astype(np.float32) / 32768.0
    rms = float(np.sqrt(np.mean(ambient**2)))
    import sys as _sys

    if _sys.platform != "win32":
        # MacBook mics run quieter than the LifeCam — a gentler gate, or
        # speech never crosses the line (wake heard, commands ignored)
        return max(rms * 2.0, 0.003)
    return max(rms * 2.5, 0.005)


def record_command(stream, threshold: float, agc: AutoGain,
                   wait_sec: float = WAIT_FOR_SPEECH_SEC) -> np.ndarray | None:
    """Record from an open 16 kHz int16 stream until silence or timeout.

    Returns None if no speech starts within wait_sec.
    """
    frames: list[np.ndarray] = []
    heard_speech = False
    silence_frames = 0
    elapsed_frames = 0
    frames_per_sec = SAMPLE_RATE / FRAME_LEN
    max_frames = int(MAX_COMMAND_SEC * frames_per_sec)
    stop_after = max(1, int(SILENCE_STOP_SEC * frames_per_sec))
    give_up_after = int(wait_sec * frames_per_sec)

    while elapsed_frames < max_frames:
        data, _ = stream.read(FRAME_LEN)
        elapsed_frames += 1
        pcm = agc.process(np.frombuffer(bytes(data), dtype=np.int16))
        frames.append(pcm)
        rms = float(np.sqrt(np.mean((pcm.astype(np.float32) / 32768.0) ** 2)))
        if rms >= threshold:
            heard_speech = True
            silence_frames = 0
        elif heard_speech:
            silence_frames += 1
            if silence_frames >= stop_after:
                break
        elif elapsed_frames >= give_up_after:
            return None

    if not heard_speech:
        return None
    audio = np.concatenate(frames).astype(np.float32) / 32768.0
    if len(audio) / SAMPLE_RATE < MIN_SPEECH_SEC:
        return None
    return audio


def ensure_single_instance() -> None:
    """If an older TARS is still running, close it — no double voices."""
    import os

    import psutil

    me = os.getpid()
    try:
        procs = list(psutil.process_iter())
    except Exception:
        return  # scan unavailable — never let it block startup
    for p in procs:
        # every per-process read guarded: protected processes (anti-cheat,
        # antivirus) throw raw OSErrors that once killed TARS at boot
        try:
            if p.pid == me or not (p.name() or "").lower().startswith("python"):
                continue
            mine, readable = False, True
            try:
                args = [a.lower() for a in (p.cmdline() or [])]
                # exact argument match only — a script merely *mentioning*
                # main.py (a diagnostic) must not count as a TARS instance
                mine = any(a.endswith(("main.py", "boot.py")) for a in args) \
                    and any("tars" in a for a in args)
            except Exception:
                readable = False
            if not readable:
                # unreadable command line = the wedged-zombie signature
                # (one from 19:25 survived every polite sweep that way);
                # if it runs from TARS's own interpreter, it's a dead TARS.
                # Healthy diagnostic scripts stay untouched — theirs read.
                try:
                    exe = (p.exe() or "").lower().replace("\\", "/")
                    mine = "/tars/runtime/" in exe or "/tars/.venv/" in exe
                except Exception:
                    mine = False
            if mine:
                p.kill()  # kill, not terminate — zombies ignore polite
                print("(closed an older TARS instance)")
        except Exception:
            continue
    # deterministic port takeover: whatever process holds the dashboard
    # port and isn't me IS an old TARS, however unrecognizable — sweeps
    # have missed zombies twice; socket ownership never lies
    try:
        for c in psutil.net_connections(kind="tcp"):
            if getattr(c.laddr, "port", None) == 8765 and c.pid and c.pid != me:
                try:
                    psutil.Process(c.pid).kill()
                    print("(killed the process squatting on the dashboard port)")
                except Exception:
                    pass
    except Exception:
        pass


def main() -> None:
    print("TARS is starting up...")
    # BEFORE anything asks for a credential: pull them out of Windows
    # Credential Manager into this process's environment. They used to sit
    # in .env in plain text; now the file has none and this is where they
    # come from. Must be first — seqta.py and the phone bridge read the
    # environment the moment they start.
    try:
        import secrets_store

        loaded = secrets_store.load_into_env()
        if loaded:
            print(f"(unlocked {loaded} credential(s) from Windows vault)")
    except Exception as e:
        print(f"(credential vault unavailable: {type(e).__name__})")
    ensure_single_instance()
    import audio_out

    audio_out.apply_saved()  # voice comes out wherever the owner last put it
    ui = StatusUI()
    import dashboard

    dashboard.start()  # localhost:8765, "show me the home page"

    # FIRST RUN EVER — ask who this is. Never again after that: updating
    # TARS must not wipe someone's details or re-ask for their password.
    import profile

    if profile.needs_setup():
        import tars_window as _win
        import threading as _th

        print("First run — opening setup so you can introduce yourself.")
        _th.Timer(2.0, lambda: _win.open_page("setup", 700, 900)).start()

    def set_state(s: str) -> None:
        ui.set(s)
        dashboard.set_status(s)
        note_state(s)      # the watchdog's only view of whether TARS is stuck

    threading.Thread(target=_watchdog, daemon=True).start()
    speaker = Speaker()
    transcriber = Transcriber()
    global TRANSCRIBER
    TRANSCRIBER = transcriber  # so a voice note off the phone can use the
    # same whisper model instead of loading a second one into RAM
    brain = Brain(BASE)
    dashboard.BRAIN = brain      # the dashboard's Teach + Talk boxes
    import gestures

    gestures.wire(speaker=speaker, brain=brain)  # palm-up / thumbs signals
    dashboard.SPEAKER = speaker  # so typed messages can be answered aloud
    import threading

    threading.Thread(target=brain.warm, daemon=True).start()
    # mediapipe costs 4.3s to import — pay it here, in the background, so
    # "watch for signals" starts in the time it takes to open the camera.
    # (Must sit AFTER `import threading`: main() binds threading locally, so
    # touching it earlier in the function is an UnboundLocalError — which is
    # exactly how I crashed the boot and triggered a 37-file rollback.)
    threading.Thread(target=gestures.warm, daemon=True).start()
    import tars_phone

    tars_phone.start(brain)  # no-op until a Telegram token is in .env
    import heartbeat

    heartbeat.start()  # lets the doorbell phone see he's awake. Says only
    # "TARS" to anyone on the home WiFi — the dashboard stays on localhost.
    import button_finger

    button_finger.start()  # feeds the servo on the power button. If TARS
    # goes quiet for three minutes it presses — the only thing that can
    # bring the PC back from a shutdown or a blackout.
    import rewind

    import presence

    presence.start()  # ARMED ONLY — the camera does nothing until he says
    # "watch for me", because the standing rule is that the webcam opens on
    # an explicit word and nothing else.
    import highlights

    highlights.start()  # holds the last 30 seconds of any game in memory, so
    # "clip that" catches the thing that already happened rather than starting
    # a recording after it.
    rewind.start()  # remembers screens he actually settles on, so he can ask
    # about them later. Skips password managers, banking and private windows
    # before the screenshot is taken, and says out loud that it's running.
    # after a healthy minute of uptime, this running set of core files is
    # proven bootable — snapshot it so boot.py can roll back a bad Kipp
    # self-upgrade that breaks start-up
    import improve

    def _startup_health() -> None:
        """Quiet self-check after startup: speak ONLY if something's wrong,
        so a broken organ announces itself instead of failing silently."""
        try:
            import announce
            import doctor

            problems, fixed = doctor.run_checks(fix=True)
            if problems:
                announce.post("Heads up — " + doctor.spoken_summary(
                    problems, fixed), hold_during_quiet=True)
            elif fixed:
                print(f"(self-check fixed: {', '.join(fixed)})")
        except Exception:
            pass

    health_timer = threading.Timer(25, _startup_health)
    health_timer.daemon = True
    health_timer.start()
    snapshot_timer = threading.Timer(60, improve.snapshot_last_good)
    snapshot_timer.daemon = True  # never keep a dying TARS alive
    snapshot_timer.start()
    from wakeword import make_wakeword

    waker = make_wakeword(BASE)

    def open_mic():
        # pick_input now PROVES a device carries sound before returning it —
        # his webcam mic spent a day delivering digital silence while
        # everything looked healthy. Say out loud which ears are in use when
        # they aren't the usual ones, so "he can't hear me" is never a mystery.
        device = audio_out.pick_input()
        open_mic.device = device          # remembered, so a deaf one can be dropped
        name = audio_out.input_name(device)
        print(f"(microphone: {name})")
        s = sd.RawInputStream(samplerate=SAMPLE_RATE, blocksize=FRAME_LEN,
                              channels=1, dtype="int16", device=device)
        s.start()
        return s

    stream = open_mic()
    agc = AutoGain()
    threshold = ambient_threshold(stream, agc)

    if waker:
        print(f"Listening. Say '{waker.name}' to talk. Ctrl+C to quit.")
    else:
        print("Press Enter to talk. Ctrl+C to quit.")

    asleep = False
    deaf_frames = 0  # consecutive silent frames — a dead mic tripwire
    try:
      while True:  # outer: survives the microphone vanishing mid-listen
       try:
        while True:
            # --- wait for wake (and announce due timers) ---
            set_state("asleep" if asleep else "standby")
            if waker:
                import timers_watch

                woke = False
                frames_seen = 0
                while not woke:
                    data, _ = stream.read(FRAME_LEN)
                    pcm = agc.process(np.frombuffer(bytes(data), dtype=np.int16))
                    woke = waker.process(pcm)
                    frames_seen += 1
                    # EARS HEARTBEAT — proof the listening loop is alive and
                    # that sound is actually arriving. Without it, "he isn't
                    # answering" is indistinguishable from "he isn't
                    # listening", which is how a stale mic handle hid for
                    # hours behind a healthy-looking dashboard.
                    level = float(np.sqrt(np.mean(
                        (pcm.astype(np.float32) / 32768.0) ** 2)))
                    dashboard.EARS = (time.time(), level)
                    # A DEAD-BUT-OPEN MIC is the worst failure he has: the
                    # loop spins, the dashboard says "standing by", and he
                    # hears nothing for hours. His LifeCam does this
                    # intermittently. A real mic always has a noise floor,
                    # so sustained digital silence means reopen it.
                    if level < 2e-5:
                        deaf_frames += 1
                        if deaf_frames > 750:  # ~60 seconds of nothing
                            raise sd.PortAudioError(
                                "microphone went silent (dead endpoint)")
                    else:
                        deaf_frames = 0
                    if frames_seen % 12 == 0:  # roughly once a second
                        import announce
                        import agents
                        import improve

                        agents.tick()  # Scout runs itself each morning
                        improve.tick()  # Kipp self-improves whenever idle
                        import game_watch
                        import proactive

                        import routine_watch

                        game_watch.tick()  # session buddy + gaming flag
                        routine_watch.tick()  # routines that fire themselves
                        import backup

                        backup.tick()  # nightly, quiet unless it matters
                        import downloads_watch

                        downloads_watch.tick()  # files finished downloads away
                        import publish_watch
                        import updater

                        publish_watch.tick()  # push improvements out on their own
                        updater.tick()        # and notice when there are some to take
                        proactive.tick()   # calendar heads-ups, rules-gated
                        for announcement in timers_watch.pop_due() + announce.pop():
                            print(f"TARS: {announcement}")
                            log("said", announcement)
                            # remember it, so "open the file you just made" works
                            brain.history.append(
                                {"role": "assistant", "content": announcement})
                            set_state("speaking")
                            stream.stop()
                            beep(988, 0.25)
                            speaker.say(announcement)
                            stream.start()
                            set_state("standby")
            else:
                stream.stop()
                input("\n[Enter] to talk: ")
                stream.start()

            import sys as _sys

            if _sys.platform != "win32":
                # Macs stall the INPUT stream when output plays over it —
                # the mate's TARS beeped then went deaf. Cycle the mic
                # around the beep so listening restarts clean.
                stream.stop()
                beep()
                stream.start()
            else:
                beep()

            # --- asleep: only "wake up" gets a reaction ---
            if asleep:
                audio = record_command(stream, threshold, agc)
                if waker:
                    waker.reset()
                text = transcriber.transcribe(audio) if audio is not None else ""
                if text and any(w in text.lower() for w in WAKE_UP_WORDS):
                    asleep = False
                    set_state("speaking")
                    stream.stop()
                    speaker.say("I'm back. What do you need?")
                    stream.start()
                continue

            # --- conversation: keep listening until the owner goes quiet ---
            in_conversation = True
            first_turn = True
            convo: list[str] = []
            last_command_norm = None  # catch back-to-back identical commands
            while in_conversation:
                set_state("listening")
                wait = WAIT_FOR_SPEECH_SEC if first_turn else FOLLOWUP_SEC
                audio = record_command(stream, threshold, agc, wait_sec=wait)
                if waker:
                    waker.reset()  # don't re-trigger on leftover audio
                if audio is None:
                    break  # silence — back to wake word

                # mic is not read while we think/speak, so TARS can't hear itself
                set_state("thinking")
                text = transcriber.transcribe(audio)
                if not text:
                    break

                # WHO said it — unknown voices get the guest treatment
                # automatically (no personal facts), the owner gets himself
                global LAST_AUDIO, LAST_SPEAKER
                LAST_AUDIO = audio
                try:
                    import speaker as spk_id

                    if spk_id.known():
                        who = spk_id.identify(audio)
                        if who != LAST_SPEAKER:
                            LAST_SPEAKER = who
                            log("said", f"(voice: {who or 'unknown'})")
                        brain.speaker_name = who
                except Exception:
                    pass

                # humanoid instinct: if the ears weren't sure, check first
                if (transcriber.last_confidence < CONFIRM_BELOW
                        and len(text.split()) >= 3):
                    set_state("speaking")
                    stream.stop()
                    speaker.say(f"Did you say: {text}?")
                    stream.start()
                    set_state("listening")
                    audio2 = record_command(stream, threshold, agc, wait_sec=6)
                    reply2 = transcriber.transcribe(audio2) if audio2 is not None else ""
                    if waker:
                        waker.reset()
                    low2 = reply2.lower()
                    if not reply2 or low2.startswith(("yes", "yeah", "yep",
                                                      "correct", "right")):
                        pass  # silence or a yes — run with what was heard
                    elif low2.startswith(("no", "nah")) and len(reply2.split()) <= 3:
                        set_state("speaking")
                        stream.stop()
                        speaker.say("My mistake. Say it again?")
                        stream.start()
                        set_state("listening")
                        audio3 = record_command(stream, threshold, agc, wait_sec=8)
                        text = transcriber.transcribe(audio3) if audio3 is not None else ""
                        if waker:
                            waker.reset()
                        if not text:
                            break
                    else:
                        text = reply2  # he just said the corrected command

                print(f"You: {text}")
                log("heard", text)
                convo.append(f"the owner: {text}")

                if any(w in text.lower() for w in ("goodnight", "good night")):
                    # the nightly wrap-up: recap + tomorrow, then sleep
                    set_state("speaking")
                    stream.stop()
                    try:
                        wrap = brain.skills.run("nightly_wrap", {}) or ""
                    except Exception:
                        wrap = "Sleep well, the owner."
                    log("said", wrap)
                    speaker.say(wrap + " Going quiet now — say, hey TARS, "
                                "wake up, if you need me.")
                    stream.start()
                    asleep = True
                    break

                if any(w in text.lower() for w in SLEEP_WORDS):
                    set_state("speaking")
                    stream.stop()
                    speaker.say("Going quiet. Say, hey TARS, wake up, when you need me.")
                    stream.start()
                    asleep = True
                    break

                if any(w in text.lower() for w in SHUTDOWN_WORDS):
                    set_state("speaking")
                    stream.stop()
                    speaker.say("Powering down. Goodbye, the owner.")
                    log("said", "Powering down.")
                    import os

                    os._exit(0)  # invisible engine must ACTUALLY die —
                    # a plain return once left a zombie with no console

                if any(w in text.lower() for w in END_WORDS):
                    set_state("speaking")
                    stream.stop()
                    speaker.say("Righto.")
                    stream.start()
                    break

                # if the owner just said the exact same thing again, don't run it
                # twice blind — the repeat almost always means TARS missed it
                # the first time, not that he wants a second run.
                norm = text.strip().lower().rstrip(".!? ")
                if norm and norm == last_command_norm:
                    set_state("speaking")
                    stream.stop()
                    msg = ("That's the same thing again — did I miss "
                           "it, or did you mean something else?")
                    try:
                        alts = brain.suggest_alternatives(text)
                    except Exception:
                        alts = []
                    if alts:
                        msg += (" Something close I do know: "
                                + " or ".join(f'"{a}"' for a in alts) + ".")
                    speaker.say(msg)
                    stream.start()
                    log("said", "(repeated command caught)")
                    convo.append("TARS: (repeated command caught)")
                    last_command_norm = None
                    first_turn = False
                    if _mid_game():
                        break
                    continue
                last_command_norm = norm

                # THE OWNER'S STANDING ORDER (2026-08-08): NO spoken sounds
                # before the reply — no "Okay."/"Right."/"On it.", ever.
                # Kipp re-added an ack here once ("confirmation step",
                # 2026-07-22) and it took a wiretap to catch. Do not re-add.
                gen = brain.handle_stream(text)
                try:
                    first = next(gen)  # brain starts thinking here
                except StopIteration:
                    first = None
                if first is None:
                    break

                # --- dictation mode: type everything until "stop dictation" ---
                if first.startswith("__DICTATE__"):
                    import pyautogui

                    set_state("speaking")
                    stream.stop()
                    speaker.say("Dictation on. Click where the words should "
                                "go — I'll type everything you say until you "
                                "say stop dictation.")
                    stream.start()
                    set_state("listening")
                    quiet_strikes = 0
                    while True:
                        audio_d = record_command(stream, threshold, agc,
                                                 wait_sec=30)
                        if waker:
                            waker.reset()
                        if audio_d is None:
                            quiet_strikes += 1
                            if quiet_strikes >= 2:  # a minute of silence: done
                                break
                            continue
                        quiet_strikes = 0
                        piece = transcriber.transcribe(audio_d)
                        if not piece:
                            continue
                        low_d = piece.lower()
                        if ("stop dictation" in low_d or "stop typing" in low_d
                                or low_d.strip(".!, ") in ("stop", "stop it",
                                                           "that's it")):
                            break
                        pyautogui.write(piece + " ", interval=0.02)
                    set_state("speaking")
                    stream.stop()
                    speaker.say("Dictation off.")
                    log("said", "(dictation session ended)")
                    stream.start()
                    set_state("listening")
                    continue

                set_state("speaking")
                stream.stop()  # keep wake-word detection off while audio plays
                import itertools

                reply = speaker.say_stream(itertools.chain([first], gen))
                print(f"TARS: {reply}")
                log("said", reply)
                convo.append(f"TARS: {reply}")
                stream.start()
                first_turn = False

                # Mid-game, one command means ONE command. Normally TARS
                # keeps listening for a few seconds after answering, which is
                # right at a desk and wrong in a match: the follow-up window
                # sits open through game audio and him talking to teammates,
                # and every stray word gets transcribed at him. His words:
                # "after i say clip that, dont listen for me to say another
                # thing because that would get annoying" — and he asked for
                # it on ANY command while playing, not just clipping.
                #
                # No blip either. The blip means "still listening", so making
                # that sound while going straight back to sleep would be a
                # small lie about what TARS is doing.
                if _mid_game():
                    break
                beep(660, 0.07)  # soft blip: still listening for a follow-up

            # conversation over — file topics and capture facts while idle
            if len(convo) >= 2:
                import topics

                threading.Thread(
                    target=topics.digest,
                    args=(convo[:], datetime.date.today().isoformat()),
                    daemon=True,
                ).start()
                threading.Thread(
                    target=brain.capture_conversation, args=(convo[:],),
                    daemon=True,
                ).start()
       except KeyboardInterrupt:
        print("\nTARS shutting down.")
        break
       except sd.PortAudioError as e:
        # Windows shuffled the audio devices (a controller/headset connected,
        # driver restarted...) — reopen the mic instead of dying
        print(f"(microphone lost: {e} — reconnecting)")
        if "went silent" in str(e):
            # not unplugged — WORSE: open but deaf. Never pick it again
            # this session, or the reconnect lands on the same dead device.
            audio_out.mark_dead(getattr(open_mic, "device", None))
            print(f"(dropping {audio_out.input_name(getattr(open_mic, 'device', None))}"
                  f" — it was open but delivering silence)")
        set_state("offline")
        try:
            stream.abort()
            stream.close()
        except Exception:
            pass
        while True:
            time.sleep(4)
            try:
                sd._terminate()
                sd._initialize()
                audio_out.apply_saved()  # the reset wipes the output choice
                stream = open_mic()
                threshold = ambient_threshold(stream, agc)
                print("(microphone back)")
                break
            except Exception:
                set_state("offline")
    finally:
        set_state("offline")
        try:
            stream.stop()
            stream.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()
