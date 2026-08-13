"""Where the owner's passwords live — and, more importantly, how they get out.

Storage is Windows Credential Manager, not a file. That isn't a detail: TARS
publishes himself to GitHub every hour, and a password in a file is one bug
in an exclusion list away from being public forever. There is nothing here
for that bug to leak. His SEQTA password sat in plain text in profile.json
and .env before this existed.

The real work in this module is redact(). A password is only safe if it
cannot come back OUT, and TARS has a lot of mouths: he speaks, he texts, he
writes to a log, he saves things to his memory vault, and he sends whole
conversations to Claude when a job is too big for the local model. Any one
of those could carry a password out of the house.

So every one of them is filtered through redact() on the way out. Not a rule
in a prompt the model can talk itself past — a function it has to physically
pass through. If a password ever reaches TARS's mouth, it comes out as
[password hidden] and nothing else.

    put("school", "...")     store / replace
    use("school")            the real value, for typing into a login box
    redact(text)             strip every stored secret out of any text
    names()                  what he has, never what they are
    forget("school")         gone
"""
import json
import time

SERVICE = "TARS"
INDEX = "__index__"
# below this, a "secret" is too short to redact safely — blanking every "abc"
# in his conversation would mangle it, and a 3-character password isn't one
MIN_REDACT = 6
_cache: tuple[float, list] = (0.0, [])
CACHE_SECONDS = 20


def _kr():
    import keyring

    return keyring


def names() -> list:
    """The names of what's stored. Never the values — this is the one
    listing function, and it must stay safe to print, speak and log."""
    try:
        raw = _kr().get_password(SERVICE, INDEX)
        return sorted(json.loads(raw)) if raw else []
    except Exception:
        return []


def _remember_name(name: str, adding: bool = True) -> None:
    current = set(names())
    current.add(name) if adding else current.discard(name)
    try:
        _kr().set_password(SERVICE, INDEX, json.dumps(sorted(current)))
    except Exception:
        pass


def put(name: str, value: str) -> bool:
    name = (name or "").strip().lower()
    if not name or not value:
        return False
    try:
        _kr().set_password(SERVICE, name, value)
    except Exception:
        return False
    _remember_name(name)
    _bust()
    return True


def use(name: str) -> str:
    """The real value. ONLY for handing to the thing it logs into.

    Never return this to the model, never put it in a reply, never write it
    anywhere. If you're about to do any of those, you want names() instead.
    """
    try:
        return _kr().get_password(SERVICE, (name or "").strip().lower()) or ""
    except Exception:
        return ""


def forget(name: str) -> bool:
    name = (name or "").strip().lower()
    try:
        _kr().delete_password(SERVICE, name)
    except Exception:
        return False
    _remember_name(name, adding=False)
    _bust()
    return True


def _bust() -> None:
    global _cache
    _cache = (0.0, [])


def _values() -> list:
    """Every stored secret, cached briefly. redact() runs on every single
    line TARS says, texts or logs, so it can't hit the credential store
    each time."""
    global _cache
    when, cached = _cache
    if time.time() - when < CACHE_SECONDS:
        return cached
    found = []
    for name in names():
        value = use(name)
        if value and len(value) >= MIN_REDACT:
            found.append(value)
    # longest first, so a password that contains another one still goes
    _cache = (time.time(), sorted(found, key=len, reverse=True))
    return _cache[1]


def redact(text: str) -> str:
    """The last gate before anything leaves TARS.

    Wired into speech, Telegram, the dashboard, the log and the memory
    vault. Cheap, total, and it must never raise — a crash here would take
    out TARS's ability to speak at all, so everything is wrapped.
    """
    if not text:
        return text
    try:
        for value in _values():
            if value in text:
                text = text.replace(value, "[password hidden]")
    except Exception:
        pass
    return text
