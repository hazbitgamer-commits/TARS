"""Deciding when TARS is worth paying for.

ElevenLabs bills per character. The free tier is 10,000 credits a month —
about ten minutes of speech — and even the paid tier is roughly two hours,
which is four minutes a day. TARS talks more than that before school.

So "use ElevenLabs for everything" doesn't mean a better-sounding assistant;
it means a better-sounding assistant until Tuesday, then a silent switch
back to the local voice with no explanation. This module spends the budget
where he'd actually notice:

  - acknowledgements and one-word replies never use it. "Okay." costs the
    same per character as the answer to a real question, and nobody ever
    wished "okay" sounded warmer.
  - long readouts never use it. A twelve-item shopping list would eat a
    third of the month in one go.
  - it paces itself. Without this the whole month goes in about two days,
    which is the same as not having it, except you paid.
  - the last tenth is held back, so there's something left for the end of
    the month rather than three good weeks and a flat one.

Real usage comes from ElevenLabs itself rather than a count kept here — a
local tally drifts, and drift means either wasted budget or a surprise.
"""
import json
import os
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent
STATE = BASE / "eleven_usage.json"

MIN_CHARS = 25          # below this it's an acknowledgement, not an answer
MAX_CHARS = 700         # above this it's a readout; the local voice can have it
RESERVE = 0.10          # keep the last tenth for the end of the month
CHECK_EVERY = 600       # seconds between asking ElevenLabs where we're up to
# An ElevenLabs key can be scoped to text-to-speech WITHOUT permission to read
# the account, which is a perfectly sensible thing to do and leaves this
# module blind. Blind used to mean "allow everything", so the pacing quietly
# stopped and a month's credits went in an afternoon. Now it falls back to
# counting its own spending against the free-tier allowance — an estimate,
# but an estimate that paces is worth more than perfect numbers that don't.
ASSUMED_LIMIT = 10000


def _state() -> dict:
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _save(data: dict) -> None:
    try:
        STATE.write_text(json.dumps(data, indent=1), encoding="utf-8")
    except OSError:
        pass


def usage(force: bool = False) -> dict:
    """(used, limit) straight from ElevenLabs, cached for ten minutes.

    Asking them is the only honest source: a tally kept here misses speech
    generated anywhere else on the same account and drifts a little on every
    call, and drift is exactly what you can't have in a spending limit.
    """
    data = _state()
    fresh = time.time() - data.get("checked", 0) < CHECK_EVERY
    if fresh and not force and "limit" in data:
        return data

    key = (os.getenv("ELEVENLABS_API_KEY") or "").strip()
    if not key:
        return {"used": 0, "limit": 0, "checked": time.time()}
    try:
        import requests

        r = requests.get("https://api.elevenlabs.io/v1/user/subscription",
                         headers={"xi-api-key": key}, timeout=15)
        if r.status_code != 200:
            # keep WHY. "Couldn't reach ElevenLabs" is what this used to say
            # when the truth was "they answered instantly and told us the key
            # was wrong" — a wrong diagnosis costs him a round trip.
            why = ""
            try:
                detail = r.json().get("detail", {})
                why = (detail.get("message") if isinstance(detail, dict)
                       else str(detail)) or ""
            except Exception:
                pass
            data["error"] = why[:160] or f"HTTP {r.status_code}"
            data["checked"] = time.time()
            _save(data)
            return data
        body = r.json()
        data.pop("error", None)
        data.update({"used": int(body.get("character_count", 0)),
                     "limit": int(body.get("character_limit", 0)),
                     "resets": body.get("next_character_count_reset_unix", 0),
                     "checked": time.time()})
        _save(data)
    except Exception:
        pass
    return data


def _spent_today(data: dict) -> int:
    day = time.strftime("%Y-%m-%d")
    return int(data.get("daily", {}).get(day, 0))


def _spent_this_month(data: dict) -> int:
    month = time.strftime("%Y-%m")
    return sum(int(v) for k, v in data.get("daily", {}).items()
               if str(k).startswith(month))


def _note_spend(chars: int) -> None:
    data = _state()
    day = time.strftime("%Y-%m-%d")
    daily = data.get("daily", {})
    daily[day] = int(daily.get(day, 0)) + chars
    # a month of days is all that's ever useful; don't grow forever
    data["daily"] = dict(sorted(daily.items())[-31:])
    _save(data)


def allow(text: str) -> tuple[bool, str]:
    """Should this line be spoken by ElevenLabs? Returns (yes/no, why)."""
    if not (os.getenv("ELEVENLABS_API_KEY") or "").strip():
        return False, "no key"
    n = len(text or "")
    if n < MIN_CHARS:
        return False, "too short to be worth it"
    if n > MAX_CHARS:
        return False, "long readout"

    data = usage()
    limit = int(data.get("limit", 0))
    if limit:
        used = int(data.get("used", 0))
    else:
        # blind: the key can speak but can't read the account. Pace against
        # our own tally rather than giving up and spending the lot.
        limit, used = ASSUMED_LIMIT, _spent_this_month(data)
    left = limit - used
    if left <= limit * RESERVE:
        return False, "saving the last of the month"

    # pace it: a thirtieth of the allowance a day, plus a little slack so a
    # quiet day lends to a busy one
    daily_cap = max(200, int(limit / 25))
    if _spent_today(data) + n > daily_cap:
        return False, "today's share is used up"
    return True, "ok"


def record(text: str) -> None:
    _note_spend(len(text or ""))


def status() -> str:
    """Plain English, for when he asks how much voice is left."""
    if not (os.getenv("ELEVENLABS_API_KEY") or "").strip():
        return ("The paid voice isn't switched on — I'm using the free local "
                "one. Add an ElevenLabs key on the setup page if you want it.")
    data = usage(force=True)
    limit = int(data.get("limit", 0))
    if not limit:
        problem = str(data.get("error", ""))
        if "API key ID" in problem or "invalid_api_key" in problem:
            return ("That's the key ID, not the key. ElevenLabs only shows "
                    "the real one when you create or rotate it, and it "
                    "starts with s k underscore. Make a new key and paste "
                    "that into the setup page.")
        if "user_read" in problem:
            # the common case: speech works, reading the account doesn't
            spent = _spent_this_month(_state())
            left = max(0, ASSUMED_LIMIT - spent)
            return (f"My key can talk but can't read your account, so I'm "
                    f"going on my own count: about {left:,} of "
                    f"{ASSUMED_LIMIT:,} credits left this month — roughly "
                    f"{left / 1000:.0f} minutes. Tick User Read on the key "
                    f"in ElevenLabs and I'll give you the real number.")
        if problem:
            return f"ElevenLabs turned me away: {problem}"
        return "I couldn't reach ElevenLabs to check the balance."
    used = int(data.get("used", 0))
    left = max(0, limit - used)
    minutes = left / 1000.0        # ~1000 characters a minute of speech
    when = ""
    resets = int(data.get("resets", 0) or 0)
    if resets:
        when = f" It resets on {time.strftime('%d %b', time.localtime(resets))}."
    today = _spent_today(_state())
    return (f"{left:,} of {limit:,} credits left — roughly "
            f"{minutes:.0f} minutes of the good voice.{when} "
            f"I've used {today:,} today.")
