"""Who owns this copy of TARS.

Everything personal lives here — name, city, school, logins — instead of
being written into the code. The public repo therefore contains nobody's
details, and each person's copy knows only about them.

profile.json NEVER goes to GitHub (it's in .gitignore and excluded from
the publish list). It IS included in the nightly backup, so a reinstall
doesn't mean typing it all again, and updating TARS never touches it.
"""
import json
import os
from pathlib import Path

BASE = Path(__file__).resolve().parent
FILE = BASE / "profile.json"

# what setup asks for. "secret" fields are masked in the dashboard until
# the owner clicks reveal — they're his own details, on his own machine.
FIELDS = [
    {"key": "name", "label": "What should I call you?",
     "hint": "First name is fine", "required": True},
    {"key": "city", "label": "Which town or city?",
     "hint": "For weather and sunset times", "required": True},
    {"key": "email", "label": "Your email address",
     "hint": "Used when he fills in a signup form for you. Not a secret, "
             "so it stays readable in your profile"},
    {"key": "school_portal", "label": "Does your school use SEQTA?",
     "hint": "SEQTA connects automatically; anything else you can tell me "
             "your timetable yourself", "choices": ["SEQTA", "Something else",
                                                    "No school"]},
    {"key": "seqta_url", "label": "Your school's portal address",
     "hint": "The address you log into, e.g. learn.yourschool.wa.edu.au"},
    {"key": "seqta_user", "label": "Portal username"},
    {"key": "seqta_pass", "label": "Portal password", "secret": True,
     "hint": "Stays on this computer — it's only ever sent to your school"},
    {"key": "telegram_token", "label": "Telegram bot token", "secret": True,
     "hint": "Optional — lets you text TARS from your phone. From @BotFather"},
    {"key": "big_brain", "label": "Big jobs (self-teaching, building things)",
     "choices": ["Claude", "ChatGPT", "Off"],
     "hint": "Optional and paid, on your own account. Everyday talking is "
             "always free and local."},
    {"key": "big_brain_key", "label": "Your key for that", "secret": True,
     "hint": "Claude: an OAuth token. ChatGPT: an API key starting sk-"},
    {"key": "mobile", "label": "Your mobile number",
     "hint": "So he can ring you, and connect you to calls he places"},
    {"key": "eleven_key", "label": "ElevenLabs key (a human-sounding voice)",
     "secret": True, "hint": "Optional and paid. Without it he uses the free "
                             "local voice."},
    {"key": "twilio_sid", "label": "Twilio account SID",
     "hint": "Optional — only needed for real phone calls"},
    {"key": "twilio_token", "label": "Twilio auth token", "secret": True},
    {"key": "twilio_number", "label": "Your Twilio phone number",
     "hint": "The number he calls FROM, e.g. +61... (not needed if you use "
             "your own number below)"},
    {"key": "caller_id_mine", "label": "Show MY number when he calls people",
     "choices": ["No", "Yes"],
     "hint": "Twilio must verify you own it first — Verified Caller IDs in "
             "their console. Then people see your mobile, not a strange number."},
]
SECRETS = {f["key"] for f in FIELDS if f.get("secret")}

# profile key -> environment variable. Everything that reads a credential
# (seqta.py, tars_phone.py, phone_call.py, tts.py) reads the environment,
# so this is the one place that decides what they're called.
ENV_MAP = {"seqta_url": "SEQTA_URL", "seqta_user": "SEQTA_USER",
           "seqta_pass": "SEQTA_PASS",
           "telegram_token": "TELEGRAM_BOT_TOKEN", "city": "HOME_CITY",
           "eleven_key": "ELEVENLABS_API_KEY",
           "twilio_sid": "TWILIO_ACCOUNT_SID",
           "twilio_token": "TWILIO_AUTH_TOKEN",
           "twilio_number": "TWILIO_NUMBER"}


def _env_name(key: str, data: dict | None = None) -> str:
    """Which environment variable a profile field lands in. big_brain_key is
    the odd one — it's a Claude token or an OpenAI key depending on choice."""
    if key == "big_brain_key":
        which = (data or load()).get("big_brain")
        return "OPENAI_API_KEY" if which == "ChatGPT" else "CLAUDE_CODE_OAUTH_TOKEN"
    return ENV_MAP.get(key, key.upper())


def _vault():
    """The password store, or None if it isn't available. Never fatal:
    without it TARS falls back to the old behaviour rather than refusing
    to start."""
    try:
        import secrets_store

        return secrets_store
    except Exception:
        return None


def load() -> dict:
    try:
        return json.loads(FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def save(data: dict) -> None:
    current = load()
    vault = _vault()
    for key, value in data.items():
        # an empty box means "leave what's there", not "wipe it" — otherwise
        # a masked password field would erase itself on every save
        if value == "" and key in SECRETS and get(key):
            continue
        if key in SECRETS and vault:
            # passwords go to Windows Credential Manager and NOWHERE else.
            # Not profile.json, not .env — this file gets backed up and that
            # file gets read by anything on the PC.
            var = _env_name(key, {**current, **data})
            vault.put_env(var, value)
            # ...and into THIS process's environment too. Without this a
            # secret saved on the setup page only took effect after a
            # restart, because the vault is read once at startup — so he'd
            # paste a Twilio token, be told he was set up, and find calling
            # still broken. Vault for next time, environment for right now.
            os.environ[var] = value
            current.pop(key, None)
            continue
        current[key] = value
    current["set_up"] = True
    FILE.write_text(json.dumps(current, indent=1), encoding="utf-8")
    _mirror_to_env(current)


def _mirror_to_env(data: dict) -> None:
    """Keep .env in step, since seqta.py and tars_phone.py read from it and
    from the environment. Written key by key so nothing else is disturbed.

    SECRETS are deliberately excluded from the FILE — they're set in the
    live environment from the vault instead (see secrets_store.load_into_env).
    """
    mapping = {k: v for k, v in ENV_MAP.items() if k not in SECRETS}
    env = BASE / ".env"
    try:
        lines = env.read_text(encoding="utf-8").splitlines()
    except OSError:
        lines = []
    for key, name in mapping.items():
        value = str(data.get(key, "")).strip()
        if not value:
            continue
        os.environ[name] = value
        for i, line in enumerate(lines):
            if line.strip().startswith(f"{name}="):
                lines[i] = f"{name}={value}"
                break
        else:
            lines.append(f"{name}={value}")
    if data.get("big_brain_key"):
        # live environment only — the key itself belongs in the vault
        os.environ[_env_name("big_brain_key", data)] = data["big_brain_key"]
    try:
        env.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")
    except OSError:
        pass


def needs_setup() -> bool:
    """First run ever. Updating TARS must never make this true again."""
    return not load().get("set_up")


def owner() -> str:
    """The name TARS calls them. Falls back to something neutral rather
    than anyone's actual name."""
    return (load().get("name") or "").strip() or "you"


def owner_or(default: str = "the owner") -> str:
    return (load().get("name") or "").strip() or default


def city() -> str:
    return (load().get("city") or "").strip() or os.getenv("HOME_CITY", "Perth")


def get(key: str, default: str = "") -> str:
    if key in SECRETS:
        vault = _vault()
        if vault:
            found = vault.use_env(_env_name(key))
            if found:
                return found
        # not migrated yet: fall back to the old plaintext home
        return str(load().get(key, default) or default)
    return str(load().get(key, default) or default)


def public_view() -> dict:
    """What the setup page shows: everything, with secrets masked until
    the owner asks to see them. He wanted to be able to read his own
    details back — people forget school passwords."""
    data = load()
    out = {}
    for field in FIELDS:
        key = field["key"]
        if field.get("secret"):
            # the value now lives in the vault, so ask how long it is
            # without ever putting it in something bound for a web page
            value = get(key)
            out[key] = "•" * min(len(value), 12) if value else ""
        else:
            out[key] = str(data.get(key, "") or "")
    return out


_OWNER_WORDS = ("the owner's", "The owner's", "the owner", "The owner")


def personalise(text: str) -> str:
    """Code says "the owner"; the person hears their own name.

    The name was written into 419 places across 108 files, which is why
    none of it could be published. It now lives in exactly one file, and
    gets substituted on the way out — so the repo is nobody's, and each
    copy is somebody's.
    """
    name = (load().get("name") or "").strip()
    if not name or not text:
        return text
    return (text.replace("the owner's", f"{name}'s")
                .replace("The owner's", f"{name}'s")
                .replace("the owner", name)
                .replace("The owner", name))


def reveal() -> dict:
    """The real values, for the owner's own eyes on his own machine.

    This is the one deliberate exception to "a password never comes back
    out" — he asked for it, because people forget their school password
    and this is his own dashboard on his own PC, bound to localhost.
    """
    return {key: get(key) for key in SECRETS}
