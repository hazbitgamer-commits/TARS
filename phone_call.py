"""Real phone calls, through Twilio.

The rules the owner set are enforced HERE, in code, not in a prompt a model
can talk itself out of:

  1. NEVER dials without him confirming that exact number, right then.
  2. Emergency numbers are hard-blocked. No override, no exceptions.
  3. On any call TARS places, he opens by saying he's an assistant calling
     on someone's behalf. He is not allowed to pretend to be a person.
  4. Doesn't record. WA law generally needs every party's consent for a
     private conversation, and not recording sidesteps that entirely.

Money: calls cost a few cents a minute on HIS account. Nothing here buys
anything, creates an account, or enters card details — he sets that up
himself and pastes the keys into setup.
"""
import json
import os
import re
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent
LOG = BASE / "call_log.json"

# hard-blocked, everywhere, forever. An assistant that can dial 000 by
# accident (or by a misheard word) is not something worth having.
EMERGENCY = {"000", "112", "911", "999", "111", "106", "911911",
             "+61000", "10111"}
MAX_MINUTES = 10          # a runaway call is a runaway bill
MAX_CALLS_PER_DAY = 20


def configured() -> tuple[bool, str]:
    missing = [n for n in ("TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN")
               if not (os.getenv(n) or "").strip()]
    if missing:
        return False, ("Calling isn't set up yet — I need your Twilio SID "
                       "and token in the setup page first.")
    if not caller_id():
        return False, ("I don't know what number to call from. Put either a "
                       "Twilio number or your own mobile in setup.")
    return True, ""


def caller_id() -> str:
    """The number people SEE when he rings them.

    He wants his own mobile, so a barber sees a familiar number instead of
    a strange one. Twilio allows this only for a **Verified Caller ID** —
    a number you've proved you own, by answering a code. That's the honest
    version of the feature; setting it to a number you don't own would be
    spoofing, which is illegal and which Twilio blocks anyway.
    """
    try:
        import profile

        mine = normalise(profile.get("mobile", ""))
        use_mine = str(profile.get("caller_id_mine", "")).lower() in (
            "yes", "true", "1", "on")
    except Exception:
        mine, use_mine = "", False
    if use_mine and mine:
        return mine
    return normalise(os.getenv("TWILIO_NUMBER", ""))


def caller_id_verified() -> tuple[bool, str]:
    """Ask Twilio whether that number is actually verified on his account.
    Better to say so up front than to have every call fail at dial time."""
    sid = (os.getenv("TWILIO_ACCOUNT_SID") or "").strip()
    token = (os.getenv("TWILIO_AUTH_TOKEN") or "").strip()
    number = caller_id()
    if not (sid and token and number):
        return False, "Calling isn't set up yet."
    try:
        import requests

        r = requests.get(
            f"https://api.twilio.com/2010-04-01/Accounts/{sid}"
            f"/OutgoingCallerIds.json?PhoneNumber={number}",
            auth=(sid, token), timeout=20)
        if r.status_code != 200:
            return False, "Twilio wouldn't answer — check the SID and token."
        if r.json().get("outgoing_caller_ids"):
            return True, f"{number} is verified — that's what people will see."
        # it might be a Twilio number he owns, which needs no verification
        owned = requests.get(
            f"https://api.twilio.com/2010-04-01/Accounts/{sid}"
            f"/IncomingPhoneNumbers.json?PhoneNumber={number}",
            auth=(sid, token), timeout=20)
        if owned.status_code == 200 and owned.json().get("incoming_phone_numbers"):
            return True, f"{number} is your Twilio number — good to go."
        return False, (f"{number} isn't verified with Twilio yet, so calls "
                       f"from it will be refused. In the Twilio console: "
                       f"Phone Numbers → Verified Caller IDs → Add. They'll "
                       f"ring or text you a code.")
    except Exception as e:
        return False, f"Couldn't check with Twilio ({type(e).__name__})."


def normalise(number: str) -> str:
    """Australian numbers, in the format Twilio wants."""
    digits = re.sub(r"[^\d+]", "", number or "")
    if digits.startswith("+"):
        return digits
    if digits.startswith("0"):
        return "+61" + digits[1:]
    if len(digits) == 8:            # local Perth number, no area code
        return "+618" + digits
    if digits.startswith("61"):
        return "+" + digits
    return digits


def is_emergency(number: str) -> bool:
    """Deliberately over-eager. A false positive costs one refused call; a
    false negative dials emergency services by accident."""
    # spoken forms FIRST — "triple zero" has no digits at all, and an
    # early return on "no digits" skipped this check entirely
    spoken = (number or "").lower()
    if any(w in spoken for w in ("triple zero", "triple 0", "triple-zero",
                                 "emergency service", "nine one one",
                                 "ambulance", "the police", "fire brigade")):
        return True
    bare = re.sub(r"[^\d]", "", number or "")
    if not bare:
        return False
    if bare in EMERGENCY:
        return True
    # with any country code stripped: +61 000, 0061000, 61000 ...
    for prefix in ("61", "0061", "0"):
        if bare.startswith(prefix) and bare[len(prefix):] in EMERGENCY:
            return True
    # spoken forms whisper produces
    spoken = (number or "").lower()
    if any(w in spoken for w in ("triple zero", "triple 0", "emergency services",
                                 "nine one one", "999")):
        return True
    return False


def _log(entry: dict) -> None:
    try:
        data = json.loads(LOG.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        data = {"calls": []}
    data.setdefault("calls", []).append({**entry, "t": time.time()})
    data["calls"] = data["calls"][-200:]
    try:
        LOG.write_text(json.dumps(data, indent=1), encoding="utf-8")
    except OSError:
        pass


def calls_today() -> int:
    try:
        data = json.loads(LOG.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 0
    cutoff = time.time() - 86400
    return len([c for c in data.get("calls", []) if c.get("t", 0) > cutoff])


def _twiml_speak(message: str, who: str) -> str:
    """What the person who answers hears. Always opens by saying what this
    is — he is never allowed to imply he's a human."""
    from xml.sax.saxutils import escape

    intro = (f"Hello. This is an automated assistant calling on behalf of "
             f"{who}. ")
    return ("<Response><Say voice=\"Polly.Brian\">"
            + escape(intro + message)[:1200]
            + "</Say></Response>")


def _twiml_bridge(to: str, who: str) -> str:
    """Dial the target and join HIM to it — TARS does no talking at all.
    The safest mode, and the one that needs no conversation handling."""
    from xml.sax.saxutils import escape

    return ("<Response><Say voice=\"Polly.Brian\">"
            + escape(f"Connecting {who} now.")
            + f"</Say><Dial timeout=\"30\" timeLimit=\"{MAX_MINUTES * 60}\">"
            + escape(to) + "</Dial></Response>")


def place(number: str, mode: str = "bridge", message: str = "",
          who: str = "") -> str:
    """Actually dial. Only ever called AFTER he has confirmed."""
    # THE EMERGENCY BLOCK COMES FIRST — before configuration, before
    # anything. It must be impossible to reach a state where this is
    # skipped, so it is the first statement in the function.
    if is_emergency(number) or is_emergency(normalise(number)):
        return ("I won't dial emergency services — that's blocked in me for "
                "good. If it's an emergency, call 000 yourself right now.")
    ok, why = configured()
    if not ok:
        return why
    target = normalise(number)
    if not re.fullmatch(r"\+\d{8,15}", target):
        return f"That doesn't look like a phone number: {number}"
    if calls_today() >= MAX_CALLS_PER_DAY:
        return "That's 20 calls today — I've stopped there in case something's stuck."

    sid = os.getenv("TWILIO_ACCOUNT_SID", "").strip()
    token = os.getenv("TWILIO_AUTH_TOKEN", "").strip()
    from_number = caller_id()  # his own mobile if verified
    try:
        import profile

        owner = profile.owner()
    except Exception:
        owner = "the owner"
    who = who or owner

    if mode == "bridge":
        # ring HIS phone first, then connect him to the target — he does
        # the talking, TARS just sets it up
        try:
            import profile

            his_phone = normalise(profile.get("mobile", ""))
        except Exception:
            his_phone = ""
        if not his_phone:
            return ("I need your own mobile number in setup before I can "
                    "connect you to anyone.")
        twiml = _twiml_bridge(target, who)
        dial_to = his_phone
    else:
        twiml = _twiml_speak(message, who)
        dial_to = target

    try:
        import requests

        r = requests.post(
            f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Calls.json",
            auth=(sid, token),
            data={"To": dial_to, "From": from_number, "Twiml": twiml,
                  "TimeLimit": MAX_MINUTES * 60},
            timeout=30)
    except Exception as e:
        return f"I couldn't reach the phone service ({type(e).__name__})."
    if r.status_code not in (200, 201):
        detail = ""
        try:
            detail = r.json().get("message", "")[:120]
        except Exception:
            pass
        return f"The call didn't go through. {detail}".strip()

    _log({"to": target, "mode": mode, "message": message[:120]})
    if mode == "bridge":
        return f"Ringing your phone now — answer it and I'll connect you to {number}."
    return f"Calling {number} and passing on your message."


def history(limit: int = 5) -> str:
    try:
        data = json.loads(LOG.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "I haven't made any calls."
    calls = data.get("calls", [])[-limit:]
    if not calls:
        return "I haven't made any calls."
    import datetime

    lines = [f"{datetime.datetime.fromtimestamp(c['t']):%d %b %H:%M} to "
             f"{c['to']}" for c in reversed(calls)]
    return "Recent calls: " + "; ".join(lines) + "."
