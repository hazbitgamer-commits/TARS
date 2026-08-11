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
"""
import json
import threading
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent
OWNER_FILE = BASE / "telegram_owner.txt"
STATE_FILE = BASE / "telegram_state.json"
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
        "• /school — today's lessons, straight from SEQTA\n"
        "• /due — what's coming up, soonest first\n"
        "• /status — how I'm doing right now\n"
        "• /games — your installed Steam library\n"
        "• /designs — my latest design, as a photo\n"
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
    try:
        # this chat id is owner-locked, so a message here IS the owner — without
        # this it would inherit whoever last spoke at the mic
        _brain.speaker_name = __import__("profile").owner()
        reply = _brain.handle(text) or "..."
    except Exception as e:
        reply = f"That went sideways on the PC: {e}"
    send(reply, force=True)
    try:
        import main

        main.log("heard", f"[phone] {text}")
        main.log("said", f"[phone] {reply}")
    except Exception:
        pass


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
                if text and chat_id:
                    _handle(chat_id, text)
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
