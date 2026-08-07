"""TARS on Jacob's phone — a Telegram bridge, zero extra dependencies
(plain HTTPS long-polling against api.telegram.org).

Setup (one-time, Jacob does this on his phone):
  1. In Telegram, message @BotFather → /newbot → pick a name → BotFather
     replies with a token like 123456:ABC-xyz.
  2. Put TELEGRAM_BOT_TOKEN=<that token> into tars/.env and restart TARS.
  3. Message the new bot exactly:  hey tars it's jacob
     That first correct phrase LOCKS the bridge to that chat forever —
     anyone else who finds the bot gets ignored.

After pairing: text TARS anything you'd normally say out loud. Replies come
back as messages. Skills work too — vacuum from the shops, timers, email.
Hard-block rules apply exactly as they do by voice."""
import json
import threading
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent
OWNER_FILE = BASE / "telegram_owner.txt"
PAIR_PHRASE = "hey tars it's jacob"

_brain = None
_token = ""


def _api(method: str, **params):
    import requests

    r = requests.post(f"https://api.telegram.org/bot{_token}/{method}",
                      json=params, timeout=70)
    r.raise_for_status()
    return r.json()


def send(text: str) -> None:
    """Message the paired phone (used for replies; safe no-op unpaired)."""
    if not (_token and OWNER_FILE.exists() and text):
        return
    try:
        _api("sendMessage", chat_id=int(OWNER_FILE.read_text().strip()),
             text=text[:4000])
    except Exception:
        pass


def _handle(chat_id: int, text: str) -> None:
    owner = int(OWNER_FILE.read_text().strip()) if OWNER_FILE.exists() else None
    if owner is None:
        if text.strip().lower().rstrip(".!") == PAIR_PHRASE:
            OWNER_FILE.write_text(str(chat_id), encoding="utf-8")
            _api("sendMessage", chat_id=chat_id,
                 text="Paired. This phone is now the only one I'll ever "
                      "listen to. What do you need, Jacob?")
        return  # wrong phrase or stranger: total silence
    if chat_id != owner:
        return  # strangers get nothing, not even an error

    try:
        reply = _brain.handle(f"{text}") or "..."
    except Exception as e:
        reply = f"That went sideways on the PC: {e}"
    _api("sendMessage", chat_id=chat_id, text=reply[:4000])
    try:
        import main

        main.log("heard", f"[phone] {text}")
        main.log("said", f"[phone] {reply}")
    except Exception:
        pass


def _poll_forever() -> None:
    offset = 0
    while True:
        try:
            updates = _api("getUpdates", offset=offset, timeout=50)
            for u in updates.get("result", []):
                offset = u["update_id"] + 1
                msg = u.get("message") or {}
                text = (msg.get("text") or "").strip()
                chat_id = (msg.get("chat") or {}).get("id")
                if text and chat_id:
                    _handle(chat_id, text)
        except Exception:
            time.sleep(10)  # network blip / Avast mood — retry gently


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
    print("(phone bridge up — Telegram)")
