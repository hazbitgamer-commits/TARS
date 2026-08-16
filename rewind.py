"""Screen Rewind — remembering what was on screen, so it can be asked later.

"What was that video I watched on Tuesday?" "What did that error message
say?" "What was the website with the assignment on it?" All questions about
things that were right there on the screen and are now gone.

How it works, in one line: every few seconds it looks at the screen, and any
screen he actually SETTLED on gets read and filed away as searchable text.

The settling matters more than it sounds. Reading a screen costs about a
second of processing, so reading every single one would eat the machine
alive — and most screens are half-scrolled transitions nobody was looking
at. Only a screen that stayed put for ten seconds was really being read by a
person, and those are exactly the ones worth remembering.

PRIVACY, which is the whole ballgame for something that watches a screen:

  - a blocklist of windows that are NEVER captured, not even as a thumbnail:
    password managers, banking, incognito windows, TARS's own setup page.
    Checked BEFORE the screenshot is taken, so the pixels never exist.
  - every scrap of text goes through the same redaction the speech and
    Telegram paths use, so a key or password caught in passing is scrubbed
    before it's written down.
  - it says out loud when it starts, because something that records a screen
    silently is wrong even when you asked for it.
  - "stop rewind" turns it off, "forget the last twenty minutes" erases.
  - nothing leaves the machine. No upload, no cloud, no account.

It also forgets on its own: two weeks, or a disk cap, whichever comes first.
"""
import json
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

BASE = Path(__file__).resolve().parent
STORE = BASE / "rewind"
INDEX = STORE / "index.jsonl"
STATE = BASE / "rewind_state.json"

EVERY = 4.0            # seconds between glances at the screen
SETTLED = 10.0         # how long a screen must sit still to count as looked at
SHOT_WIDTH = 1024      # what gets kept, in pixels across
SHOT_QUALITY = 40
OCR_WIDTH = 1600       # bigger for reading — accuracy falls off sharply below
KEEP_DAYS = 14
MAX_MB = 1500
SAME = 6               # hash bits different before it counts as a new screen

# Windows that are never, ever captured. Matched against the window title in
# lowercase, BEFORE anything is grabbed, so there's no moment where the
# picture existed and was thrown away — it was never taken.
#
# Deliberately broad. A false positive costs one forgotten screen; a false
# negative writes his banking or his passwords to disk.
PRIVATE = (
    "incognito", "inprivate", "private browsing", "private window",
    "1password", "bitwarden", "lastpass", "keepass", "dashlane", "nordpass",
    "credential manager", "keychain", "password", "passwords",
    "bank", "banking", "commbank", "westpac", "anz", "nab ", "bankwest",
    "paypal", "stripe", "billing", "payment", "card details",
    "sign in", "signin", "log in", "login", "authenticator", "two-factor",
    "2fa", "verification code", "reset your password",
    "tars setup", "setup — tars", "seqta login",
)


_state = {"on": True, "paused_until": 0.0, "announced": False,
          "last": None, "shots": 0}
_lock = threading.Lock()


def _load_state() -> None:
    try:
        _state.update(json.loads(STATE.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError):
        pass


def _save_state() -> None:
    try:
        STATE.write_text(json.dumps({k: v for k, v in _state.items()
                                     if k in ("on", "paused_until",
                                              "announced", "shots")},
                                    indent=1), encoding="utf-8")
    except OSError:
        pass


def _private(title: str) -> bool:
    """Is this a window that must never be recorded?"""
    low = (title or "").lower()
    if not low:
        return True          # unknown window — don't risk it
    return any(word in low for word in PRIVATE)


def _title() -> str:
    try:
        import input_guard

        return input_guard.focused_title() or ""
    except Exception:
        return ""


def _fingerprint(shot) -> int:
    """A small number that changes when the screen does.

    Sixteen-by-sixteen, greyscale, each pixel a bit for lighter-or-darker
    than average. Two screens whose fingerprints differ by only a few bits
    are the same screen with a blinking cursor on it.
    """
    import cv2

    tiny = cv2.cvtColor(cv2.resize(shot, (16, 16)), cv2.COLOR_BGR2GRAY)
    mean = tiny.mean()
    bits = 0
    for value in tiny.flatten():
        bits = (bits << 1) | int(value > mean)
    return bits


def _grab():
    """The primary screen, as an image. None if that isn't possible."""
    try:
        import cv2
        import mss
        import numpy as np

        with mss.mss() as sct:
            shot = np.array(sct.grab(sct.monitors[1]))[:, :, :3]
        return np.ascontiguousarray(shot)
    except Exception:
        return None


_ocr = {"engine": None, "tried": False}


def _read_text(shot) -> str:
    """Whatever words are on this screen."""
    if not _ocr["tried"]:
        _ocr["tried"] = True
        try:
            from rapidocr_onnxruntime import RapidOCR

            _ocr["engine"] = RapidOCR()
        except Exception:
            _ocr["engine"] = None
    if _ocr["engine"] is None:
        return ""
    try:
        import cv2

        height = int(shot.shape[0] * OCR_WIDTH / shot.shape[1])
        result, _ = _ocr["engine"](cv2.resize(shot, (OCR_WIDTH, height)))
        return " ".join(line[1] for line in (result or []))
    except Exception:
        return ""


# Anything that LOOKS like a credential, whether or not TARS knows it.
#
# secrets_store.redact() only removes secrets TARS already holds — it works
# by string-matching its own vault. That's right for speech and Telegram,
# where TARS is the one doing the talking. It is nowhere near enough here:
# a key sitting in a terminal, a token in a config file he happens to have
# open, a password typed into a page that wasn't on the blocklist — none of
# those are in the vault, so all of them would sail into the index.
#
# Reading a screen means reading whatever is on it, so this has to catch
# credentials it has never seen before.
_SECRETISH = [
    r"sk-ant-[\w-]{16,}",                       # Claude
    r"\bsk-[A-Za-z0-9]{20,}",                   # OpenAI and friends
    r"\bgh[pousr]_[A-Za-z0-9]{16,}",            # GitHub
    r"\bxox[baprs]-[\w-]{10,}",                 # Slack
    r"\bAKIA[0-9A-Z]{12,}",                     # AWS
    r"\b\d{8,10}:AA[\w-]{20,}",                 # Telegram bot
    r"\beyJ[A-Za-z0-9._-]{20,}",                # JWT
    r"\b[Bb]earer\s+[A-Za-z0-9._-]{20,}",
    # scoped (?i:...), NOT a bare (?i) — Python refuses a global flag that
    # isn't at the very start of the pattern, and since this was assembled
    # by joining the list with "|", it never was. The whole expression threw
    # on first use and the catch-all quietly handed back the unscrubbed text,
    # so every secret went straight into the file. Compiled at import now,
    # so a broken pattern breaks loudly instead of disabling the safeguard.
    r"(?i:\b(?:password|passwd|pwd|secret|token|api[_ -]?key|access[_ -]?key)"
    r"\s*[:=]\s*\S+)",
    r"\b[A-Fa-f0-9]{32,}\b",                    # long hex — keys and hashes
    r"\b(?:\d[ -]?){13,16}\b",                  # card-shaped numbers
]
_SECRET_RX = __import__("re").compile("|".join(_SECRETISH))


def _clean(text: str) -> str:
    """Scrub anything secret before it is written down."""
    if not text:
        return text
    try:
        import secrets_store

        text = secrets_store.redact(text)
    except Exception:
        pass
    return _SECRET_RX.sub("[hidden]", text)


def _remember(shot, title: str, text: str) -> None:
    import cv2

    STORE.mkdir(exist_ok=True)
    now = datetime.now()
    day = STORE / now.strftime("%Y-%m-%d")
    day.mkdir(exist_ok=True)
    name = now.strftime("%H%M%S") + ".jpg"
    height = int(shot.shape[0] * SHOT_WIDTH / shot.shape[1])
    cv2.imwrite(str(day / name),
                cv2.resize(shot, (SHOT_WIDTH, height)),
                [cv2.IMWRITE_JPEG_QUALITY, SHOT_QUALITY])
    with _lock:
        with INDEX.open("a", encoding="utf-8") as f:
            f.write(json.dumps({
                "at": now.isoformat(timespec="seconds"),
                "title": _clean(title)[:200],
                "text": text[:4000],
                "shot": f"{now.strftime('%Y-%m-%d')}/{name}",
            }) + "\n")
    _state["shots"] = _state.get("shots", 0) + 1


def entries() -> list[dict]:
    try:
        with INDEX.open(encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]
    except (OSError, json.JSONDecodeError):
        return []


def _tidy() -> None:
    """Forget what's too old, and keep the whole thing under the disk cap."""
    kept, dropped = [], []
    cutoff = datetime.now() - timedelta(days=KEEP_DAYS)
    for row in entries():
        try:
            when = datetime.fromisoformat(row["at"])
        except (ValueError, KeyError):
            continue
        (kept if when >= cutoff else dropped).append(row)

    # over the disk cap? drop oldest until under it
    def megabytes():
        return sum(p.stat().st_size for p in STORE.rglob("*.jpg")) / 1e6

    while kept and megabytes() > MAX_MB:
        dropped.append(kept.pop(0))
        for row in dropped[-40:]:
            _unlink(row)
    for row in dropped:
        _unlink(row)
    if dropped:
        with _lock:
            with INDEX.open("w", encoding="utf-8") as f:
                for row in kept:
                    f.write(json.dumps(row) + "\n")
        for day in STORE.iterdir():
            if day.is_dir() and not any(day.iterdir()):
                try:
                    day.rmdir()
                except OSError:
                    pass


def _unlink(row: dict) -> None:
    try:
        (STORE / row.get("shot", "")).unlink(missing_ok=True)
    except (OSError, ValueError):
        pass


def _watch() -> None:
    """The loop. Deliberately dull, and quiet when it has nothing to do."""
    _load_state()
    settled_for, pending = 0.0, None
    last_tidy = 0.0
    while True:
        time.sleep(EVERY)
        try:
            if not _state.get("on") or time.time() < _state.get("paused_until", 0):
                pending = None
                continue
            if time.time() - last_tidy > 3600:
                last_tidy = time.time()
                _tidy()

            # Not while he's gaming. Two things want the screen at once
            # then, and a screenshot of a match is a picture of a match —
            # no text worth reading later, so a second grab plus a second of
            # OCR is spent for nothing exactly when the machine can least
            # afford it.
            try:
                import game_watch

                if game_watch.playing_now():
                    pending = None
                    continue
            except Exception:
                pass

            title = _title()
            if _private(title):
                pending = None            # never even take the picture
                continue
            shot = _grab()
            if shot is None:
                continue
            mark = _fingerprint(shot)

            if pending and bin(pending["mark"] ^ mark).count("1") <= SAME:
                settled_for += EVERY
                if settled_for >= SETTLED and not pending["kept"]:
                    pending["kept"] = True
                    text = _clean(_read_text(shot))
                    # re-check the window: he may have alt-tabbed to something
                    # private during the second it took to read the screen
                    if not _private(_title()):
                        _remember(shot, title, text)
            else:
                pending = {"mark": mark, "kept": False}
                settled_for = 0.0
        except Exception:
            pending = None                # never let the loop die


def start() -> None:
    """From main(). Announces itself the first time it ever runs."""
    _load_state()
    if not _state.get("on"):
        return
    threading.Thread(target=_watch, daemon=True).start()
    if not _state.get("announced"):
        _state["announced"] = True
        _save_state()
        try:
            import announce

            announce.post(
                "Screen Rewind is on from now on — I'll remember what's been "
                "on your screen so you can ask me about it later. It skips "
                "passwords, banking and private windows, it all stays on this "
                "PC, and it forgets after a fortnight. Say 'stop rewind' any "
                "time.", hold_during_quiet=True)
        except Exception:
            pass


# ---- the things he can ask for -----------------------------------------

WHEN_WORDS = {
    "today": 0, "this morning": 0, "this afternoon": 0, "tonight": 0,
    "yesterday": 1, "monday": None, "tuesday": None, "wednesday": None,
    "thursday": None, "friday": None, "saturday": None, "sunday": None,
}
DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday",
        "saturday", "sunday"]


def _window_for(when: str):
    """Turn 'tuesday' or 'yesterday' into a start and end time."""
    if not when:
        return None, None
    low = when.lower()
    now = datetime.now()
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if "yesterday" in low:
        return start - timedelta(days=1), start
    if "today" in low or "this morning" in low or "this afternoon" in low:
        if "morning" in low:
            return start, start + timedelta(hours=12)
        if "afternoon" in low:
            return start + timedelta(hours=12), start + timedelta(hours=18)
        return start, now
    if "last week" in low:
        return start - timedelta(days=7), now
    for i, day in enumerate(DAYS):
        if day in low:
            back = (now.weekday() - i) % 7 or 7
            was = start - timedelta(days=back)
            return was, was + timedelta(days=1)
    return None, None


def search(query: str, when: str = "", limit: int = 5) -> list[dict]:
    """Screens matching these words, most recent first."""
    words = [w for w in (query or "").lower().split() if len(w) > 2]
    since, until = _window_for(when)
    hits = []
    for row in entries():
        try:
            at = datetime.fromisoformat(row["at"])
        except (ValueError, KeyError):
            continue
        if since and not (since <= at < until):
            continue
        haystack = (row.get("title", "") + " " + row.get("text", "")).lower()
        score = sum(haystack.count(w) for w in words) if words else 1
        if score:
            hits.append((score, at, row))
    hits.sort(key=lambda h: (h[0], h[1]), reverse=True)
    return [row for _, _, row in hits[:limit]]


def forget(minutes: int) -> str:
    """Erase the last however-many minutes, pictures and all."""
    cutoff = datetime.now() - timedelta(minutes=max(1, minutes))
    kept, gone = [], 0
    for row in entries():
        try:
            at = datetime.fromisoformat(row["at"])
        except (ValueError, KeyError):
            continue
        if at >= cutoff:
            _unlink(row)
            gone += 1
        else:
            kept.append(row)
    with _lock:
        with INDEX.open("w", encoding="utf-8") as f:
            for row in kept:
                f.write(json.dumps(row) + "\n")
    return (f"Forgotten — {gone} screen{'s' if gone != 1 else ''} from the "
            f"last {minutes} minutes are gone for good.")


def turn(on: bool) -> str:
    _load_state()
    was = _state.get("on")
    _state["on"] = on
    _save_state()
    if on and not was:
        threading.Thread(target=_watch, daemon=True).start()
    if on:
        return "Screen Rewind is on — I'll remember what's on your screen."
    return ("Screen Rewind is off. I'll stop remembering screens. What I "
            "already have stays until you tell me to forget it.")


def pause(minutes: int = 30) -> str:
    _load_state()
    _state["paused_until"] = time.time() + minutes * 60
    _save_state()
    return f"Rewind paused for {minutes} minutes — nothing recorded till then."


def status() -> str:
    _load_state()
    rows = entries()
    if not _state.get("on"):
        return f"Screen Rewind is off. I still have {len(rows)} screens saved."
    size = sum(p.stat().st_size for p in STORE.rglob("*.jpg")) / 1e6 if STORE.exists() else 0
    if not rows:
        return ("Screen Rewind is on, but I haven't kept anything yet — I only "
                "remember screens you stay on for a few seconds.")
    much = f"{size:.0f} MB" if size >= 1 else "hardly any space"
    return (f"Screen Rewind is on. {len(rows)} screen"
            f"{'s' if len(rows) != 1 else ''} remembered, back to "
            f"{rows[0]['at'][:10]}, using {much}. It skips passwords, banking "
            f"and private windows, and forgets after {KEEP_DAYS} days.")
