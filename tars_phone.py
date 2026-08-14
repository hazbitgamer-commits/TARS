"""TARS on the owner's phone — a Telegram bridge, zero extra dependencies
(plain HTTPS long-polling against api.telegram.org).

Setup (one-time, on the phone):
  1. Message @BotFather → /newbot → pick a name → he replies with a token
     like 123456:ABC-xyz.
  2. Put TELEGRAM_BOT_TOKEN=<token> into tars/.env and restart TARS.
  3. Message the new bot:  hey tars it's <your name>
     That first correct phrase LOCKS the bridge to that chat forever —
     anyone else who finds the bot is ignored in total silence.

Then text him anything you'd say out loud: skills run, replies come back,
design previews arrive as photos. Hard-block rules apply exactly as they
do by voice, and /notify decides whether his announcements follow you.

Three ways to talk to him from the phone:
  - type it          → he types back
  - hold and speak   → whisper hears the voice note, he answers in HIS voice
  - send a photo     → the local vision model reads it (homework, a sign,
                       a broken thing) and he answers about it
Voice notes are transcribed by the same whisper model the mic uses, and
photos go to the same local vision model the webcam uses — so nothing
leaves the PC except the Telegram message itself.
"""
import json
import threading
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent
OWNER_FILE = BASE / "telegram_owner.txt"
STATE_FILE = BASE / "telegram_state.json"
OLLAMA_URL = "http://127.0.0.1:11434/api/chat"
VISION_MODEL = "qwen2.5vl:7b"
# a voice note longer than this is a chore to listen to, and if he's put an
# ElevenLabs key in it's also money per character — long answers stay text
VOICE_REPLY_MAX = 600
# the pairing phrase is "hey tars it's <your name>" — the name comes from
# the setup profile, so this file names nobody
def _pair_phrases() -> tuple:
    try:
        import profile

        who = (profile.owner() or "").lower().strip()
    except Exception:
        who = ""
    who = who if who and who != "you" else "me"
    return (f"hey tars it's {who}", f"hey tars its {who}",
            f"hey tars, it's {who}", f"hey tars this is {who}")


PAIR_PHRASES = _pair_phrases()
HELP = ("Text me like you'd talk to me:\n"
        "• any command — timers, vacuum, lists, email, designs\n"
        "• hold the mic and talk — I'll listen and answer out loud\n"
        "• send a photo — I'll look at it (homework, a sign, anything)\n"
        "• /photo — a photo of the room, right now\n"
        "• /clip — six seconds of video from the room\n"
        "• /screen — what's on the PC screen (add left/right)\n"
        "• /live — live video of the room for 10 min, behind a code\n"
        "     /live screen · /live left · /live right — your monitors\n"
        "     /live off — stop it now\n"
        "• /school — today's lessons, straight from SEQTA\n"
        "• /due — what's coming up, soonest first\n"
        "• /status — how I'm doing right now\n"
        "• /games — your installed Steam library\n"
        "• /designs — my latest design, as a photo\n"
        "• /voice on|off|auto — should I reply out loud (auto = match you)\n"
        "• /notify on|off — should my announcements reach your phone\n"
        "• /help — this")

_brain = None
_token = ""


def _state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _save(s: dict) -> None:
    STATE_FILE.write_text(json.dumps(s), encoding="utf-8")


def _api(method: str, **params):
    import requests

    r = requests.post(f"https://api.telegram.org/bot{_token}/{method}",
                      json=params, timeout=70)
    r.raise_for_status()
    return r.json()


def paired() -> bool:
    return OWNER_FILE.exists()


def _owner() -> int | None:
    try:
        return int(OWNER_FILE.read_text().strip())
    except (OSError, ValueError):
        return None


def send(text: str, force: bool = False) -> None:
    """Message the paired phone. Announcements only go out if /notify is on
    (force=True for replies to something the owner just texted)."""
    owner = _owner()
    if not (_token and owner and text):
        return
    if not force and not _state().get("notify", False):
        return
    try:  # Telegram leaves the house entirely — last chance to catch one
        import secrets_store

        text = secrets_store.redact(text)
    except Exception:
        pass
    try:
        for chunk in [text[i:i + 3800] for i in range(0, len(text), 3800)]:
            _api("sendMessage", chat_id=owner, text=chunk)
    except Exception:
        pass


def send_photo(path: Path, caption: str = "") -> bool:
    owner = _owner()
    if not (_token and owner and Path(path).exists()):
        return False
    try:
        import requests

        with open(path, "rb") as f:
            r = requests.post(
                f"https://api.telegram.org/bot{_token}/sendPhoto",
                data={"chat_id": owner, "caption": caption[:900]},
                files={"photo": f}, timeout=90)
        return r.status_code == 200
    except Exception:
        return False


def send_video(path: Path, caption: str = "") -> bool:
    """A short clip. Telegram wants sendVideo rather than sendPhoto, and
    happily takes the mp4 OpenCV writes."""
    owner = _owner()
    if not (_token and owner and Path(path).exists()):
        return False
    try:
        import requests

        with open(path, "rb") as f:
            r = requests.post(
                f"https://api.telegram.org/bot{_token}/sendVideo",
                data={"chat_id": owner, "caption": caption[:900]},
                files={"video": f}, timeout=180)
        return r.status_code == 200
    except Exception:
        return False


def _typing(chat_id: int, action: str = "typing") -> None:
    """The little "TARS is typing…" line. A skill can take twenty seconds,
    and dead silence looks like he's broken."""
    try:
        _api("sendChatAction", chat_id=chat_id, action=action)
    except Exception:
        pass


def _download(file_id: str) -> bytes | None:
    """Pull a voice note / photo off Telegram's servers."""
    try:
        import requests

        info = _api("getFile", file_id=file_id)
        path = info["result"]["file_path"]
        r = requests.get(
            f"https://api.telegram.org/file/bot{_token}/{path}", timeout=90)
        return r.content if r.status_code == 200 else None
    except Exception:
        return None


def _opus(audio, rate: int) -> bytes | None:
    """TARS's speech as an .ogg voice note.

    Telegram wants OGG/OPUS, and Opus only accepts certain sample rates —
    ElevenLabs hands back 44.1kHz, which isn't one of them, so anything odd
    gets resampled to 48k rather than refused.
    """
    try:
        import io

        import numpy as np
        import soundfile as sf

        audio = np.asarray(audio, dtype="float32")
        if audio.ndim > 1:               # stereo → mono; it's a voice
            audio = audio.mean(axis=1)
        if rate not in (8000, 12000, 16000, 24000, 48000):
            target = 48000
            n = int(len(audio) * target / float(rate))
            audio = np.interp(np.linspace(0, len(audio) - 1, n),
                              np.arange(len(audio)), audio).astype("float32")
            rate = target
        buf = io.BytesIO()
        sf.write(buf, audio, rate, format="OGG", subtype="OPUS")
        return buf.getvalue()
    except Exception:
        return None


def send_voice(text: str, chat_id: int) -> bool:
    """Answer out loud, in his own voice, on the phone."""
    if not text or len(text) > VOICE_REPLY_MAX:
        return False
    try:
        import requests
        import tts

        made = tts._synth(text)
        if made is None:
            return False
        ogg = _opus(made[0], int(made[1]))
        if not ogg:
            return False
        r = requests.post(f"https://api.telegram.org/bot{_token}/sendVoice",
                          data={"chat_id": chat_id},
                          files={"voice": ("tars.ogg", ogg, "audio/ogg")},
                          timeout=90)
        return r.status_code == 200
    except Exception:
        return False


def _look(image: bytes, question: str) -> str:
    """Read a photo with the same local vision model the webcam uses —
    the picture never leaves the PC."""
    try:
        import base64

        import requests

        r = requests.post(OLLAMA_URL, json={
            "model": VISION_MODEL, "stream": False, "keep_alive": "30m",
            "messages": [{
                "role": "user",
                "content": (f"{question}\nThis photo was texted to you from a "
                            "phone. If it's schoolwork, explain how to do it "
                            "rather than just giving the answer. Keep it "
                            "short and plain — it's being read on a phone."),
                "images": [base64.b64encode(image).decode()],
            }],
            "options": {"num_predict": 400, "num_ctx": 8192}}, timeout=180)
        r.raise_for_status()
        return r.json()["message"]["content"].strip()
    except Exception:
        return ("I couldn't get my vision model to look at that — is the "
                "engine running on the PC?")


def _hear(audio_bytes: bytes) -> str:
    """A voice note → words, through the mic's own whisper model."""
    import tempfile

    try:
        import main

        transcriber = getattr(main, "TRANSCRIBER", None)
    except Exception:
        transcriber = None
    if transcriber is None:
        return ""
    tmp = Path(tempfile.gettempdir()) / f"tars_voice_{int(time.time())}.oga"
    try:
        tmp.write_bytes(audio_bytes)
        return (transcriber.transcribe(str(tmp)) or "").strip()
    except Exception:
        return ""
    finally:
        try:
            tmp.unlink()
        except OSError:
            pass


def _command(cmd: str, chat_id: int) -> bool:
    """Slash commands. True if handled."""
    low = cmd.lower()
    if low.startswith("/help") or low.startswith("/start"):
        _api("sendMessage", chat_id=chat_id, text=HELP)
        return True
    if low.startswith("/status"):
        try:
            import dashboard
            import improve

            s = improve._state()
            _api("sendMessage", chat_id=chat_id, text=(
                f"Status: {dashboard.state.get('status', '?')}\n"
                f"Upgrades today: {s.get('count', 0)}\n"
                f"Notifications: {'on' if _state().get('notify') else 'off'}"))
        except Exception:
            _api("sendMessage", chat_id=chat_id, text="I'm awake.")
        return True
    if low.startswith("/school") or low.startswith("/timetable"):
        # "/school tomorrow" works too — the day rides along
        when = low.replace("/timetable", "").replace("/school", "").strip()
        try:
            reply = _brain.skills.run("school", {
                "action": "timetable", "day": when or "today",
                "text": f"what have i got {when or 'today'}"})
        except Exception as e:
            reply = f"Couldn't reach school: {e}"
        _api("sendMessage", chat_id=chat_id, text=reply or "Nothing there.")
        return True
    if low.startswith("/due") or low.startswith("/assessments"):
        try:
            reply = _brain.skills.run("school", {"action": "due",
                                                 "text": "what's due",
                                                 "count": "5"})
        except Exception as e:
            reply = f"Couldn't reach school: {e}"
        _api("sendMessage", chat_id=chat_id, text=reply or "Nothing due.")
        return True
    if low.startswith("/live"):
        import livestream

        if "off" in low or "stop" in low:
            _api("sendMessage", chat_id=chat_id, text=livestream.stop())
            return True
        if "status" in low:
            _api("sendMessage", chat_id=chat_id, text=livestream.status())
            return True
        # "/live" alone is the camera; "/live screen", "/live left",
        # "/live right" share the monitors instead. It only ever did the
        # camera before, with no way to ask for anything else.
        if "left" in low:
            source, what = "screen:left", "your left screen"
        elif "right" in low:
            source, what = "screen:right", "your right screen"
        elif "screen" in low or "monitor" in low or "desktop" in low:
            source, what = "screen", "both your screens"
        else:
            source, what = "camera", "the room"
        _api("sendMessage", chat_id=chat_id,
             text=f"Opening a live view of {what} — give me a few seconds.")
        url, code = livestream.start(source)
        if not code:
            _api("sendMessage", chat_id=chat_id, text=url)
            return True
        # link and code in SEPARATE messages, so one of them leaking on its
        # own (a shoulder-surfed screen, a shared chat) isn't enough
        _api("sendMessage", chat_id=chat_id, text=url)
        _api("sendMessage", chat_id=chat_id,
             text=f"Code: {code}\nCloses itself in "
                  f"{livestream.MINUTES} minutes. /live off to end it now.")
        return True
    if low.startswith(("/photo", "/room", "/clip", "/video", "/screen")):
        # looking at his own room or screen, from wherever he is — one
        # deliberate capture per request, nothing continuous
        import remote_view

        _typing(chat_id, "upload_video" if low.startswith(("/clip", "/video"))
                else "upload_photo")
        if low.startswith(("/clip", "/video")):
            path, note = remote_view.clip()
            ok = send_video(path, note) if path else False
        elif low.startswith("/screen"):
            which = low.replace("/screen", "").strip()
            path, note = remote_view.screen(which)
            ok = send_photo(path, note) if path else False
        else:
            path, note = remote_view.photo()
            ok = send_photo(path, note) if path else False
        if not ok:
            _api("sendMessage", chat_id=chat_id, text=note)
        remote_view.tidy()
        return True
    if low.startswith("/voice"):
        want = ("off" if "off" in low else
                "on" if "on" in low else "auto")
        s = _state()
        s["voice"] = want
        _save(s)
        _api("sendMessage", chat_id=chat_id, text={
            "on": "I'll answer with a voice note every time.",
            "off": "Text only from now on.",
            "auto": "I'll talk back when you talk to me, and type when you "
                    "type.",
        }[want])
        return True
    if low.startswith("/notify"):
        on = "off" not in low
        s = _state()
        s["notify"] = on
        _save(s)
        _api("sendMessage", chat_id=chat_id,
             text=f"Announcements to your phone are {'on' if on else 'off'}.")
        return True
    if low.startswith("/games"):
        try:
            reply = _brain.skills.run("steam", {"game": "list"})
        except Exception:
            reply = None
        _api("sendMessage", chat_id=chat_id,
             text=reply or "I can't reach your Steam library right now.")
        return True
    if low.startswith("/designs"):
        pngs = sorted((BASE / "workshop" / "designs").glob("*.png"),
                      key=lambda p: -p.stat().st_mtime)
        if not pngs:
            _api("sendMessage", chat_id=chat_id, text="No designs yet.")
        elif not send_photo(pngs[0], pngs[0].stem.replace("_", " ")):
            _api("sendMessage", chat_id=chat_id,
                 text="I couldn't send the preview.")
        return True
    return False


def _pairs(text: str) -> bool:
    """Phones rewrite apostrophes (it's → it’s) and capitalise — the first
    pairing attempt died on a curly quote. Be generous: the phrase just has
    to mention TARS and the owner."""
    clean = (text.lower().replace("’", "'").replace("‘", "'")
             .strip(" .!?,"))
    if clean in PAIR_PHRASES:
        return True
    owner = ""
    try:
        import profile

        owner = (profile.owner() or "").lower().strip()
    except Exception:
        pass
    owner = owner if owner and owner != "you" else "me"
    return "tars" in clean and owner in clean and len(clean) < 60


def _reply(chat_id: int, text: str, spoken: bool) -> None:
    """Text always (it's the record, and it survives a TTS failure), plus a
    voice note when he asked for one or when he spoke to me first."""
    send(text, force=True)
    mode = _state().get("voice", "auto")
    if mode == "on" or (mode == "auto" and spoken):
        _typing(chat_id, "record_voice")
        send_voice(text, chat_id)


def _think(chat_id: int, text: str, spoken: bool = False) -> None:
    """Run one message through the brain exactly as if he'd said it aloud."""
    _typing(chat_id)
    try:
        # this chat id is owner-locked, so a message here IS the owner — without
        # this it would inherit whoever last spoke at the mic
        _brain.speaker_name = __import__("profile").owner()
        reply = _brain.handle(text) or "..."
    except Exception as e:
        reply = f"That went sideways on the PC: {e}"
    _reply(chat_id, reply, spoken)
    try:
        import main

        main.log("heard", f"[phone] {text}")
        main.log("said", f"[phone] {reply}")
    except Exception:
        pass


def _handle_media(chat_id: int, msg: dict) -> None:
    """A voice note or a photo. Pairing stays text-only, so anyone who isn't
    the paired phone gets silence here, same as everywhere else."""
    owner = _owner()
    if owner is None or chat_id != owner:
        return

    voice = msg.get("voice") or msg.get("audio") or {}
    if voice.get("file_id"):
        _typing(chat_id)
        blob = _download(voice["file_id"])
        heard = _hear(blob) if blob else ""
        if not heard:
            send("I couldn't make that out — try again, or type it.",
                 force=True)
            return
        # show him what I heard, so a misheard word is obvious rather than
        # baffling — the same reason the mic loop asks "did you say..?"
        send(f"“{heard}”", force=True)
        if heard.startswith("/") and _command(heard, chat_id):
            return
        _think(chat_id, heard, spoken=True)
        return

    photo = msg.get("photo") or []
    doc = msg.get("document") or {}
    file_id = ""
    if photo:
        file_id = photo[-1].get("file_id", "")      # last = biggest
    elif str(doc.get("mime_type", "")).startswith("image/"):
        file_id = doc.get("file_id", "")            # sent as a file, uncompressed
    if not file_id:
        return
    _typing(chat_id)
    image = _download(file_id)
    if not image:
        send("That picture wouldn't download.", force=True)
        return
    question = (msg.get("caption") or "").strip() or (
        "What is this? If it's a question or a task, help me with it.")
    answer = _look(image, question)
    _reply(chat_id, answer, spoken=False)
    try:
        import main

        main.log("heard", f"[phone photo] {question}")
        main.log("said", f"[phone] {answer}")
    except Exception:
        pass


def _handle(chat_id: int, text: str) -> None:
    owner = _owner()
    if owner is None:
        try:  # so a failed pairing is visible instead of silent
            print(f"(phone: unpaired message from {chat_id}: {text[:60]!r})")
        except Exception:
            pass
        if _pairs(text):
            OWNER_FILE.write_text(str(chat_id), encoding="utf-8")
            _api("sendMessage", chat_id=chat_id,
                 text="Paired. This phone is now the only one I'll ever "
                      "listen to.\n\n" + HELP)
        return  # wrong phrase or stranger: total silence
    if chat_id != owner:
        return

    if text.startswith("/") and _command(text, chat_id):
        return
    _think(chat_id, text)


def _poll_forever() -> None:
    offset = _state().get("offset", 0)
    while True:
        try:
            updates = _api("getUpdates", offset=offset, timeout=50)
            for u in updates.get("result", []):
                offset = u["update_id"] + 1
                s = _state()
                s["offset"] = offset  # survive restarts without replaying
                _save(s)
                msg = u.get("message") or {}
                text = (msg.get("text") or "").strip()
                chat_id = (msg.get("chat") or {}).get("id")
                if not chat_id:
                    continue
                if text:
                    _handle(chat_id, text)
                elif msg.get("voice") or msg.get("audio") or \
                        msg.get("photo") or msg.get("document"):
                    # one message at a time, but a slow vision read shouldn't
                    # stall the poller and back up everything behind it
                    threading.Thread(target=_handle_media,
                                     args=(chat_id, msg), daemon=True).start()
        except Exception:
            time.sleep(10)  # network blip — retry gently


def start(brain) -> None:
    """Called from main(); silently does nothing until a token exists."""
    global _brain, _token
    import os

    from dotenv import load_dotenv

    load_dotenv(BASE / ".env")
    _token = (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
    if not _token:
        return
    _brain = brain
    threading.Thread(target=_poll_forever, daemon=True).start()
    print("(phone bridge up — Telegram"
          + (", paired)" if paired() else ", waiting to pair)"))
