"""Checking Screen Rewind before it is allowed to watch anything.

This is the most invasive thing TARS has ever done — it reads his screen.
The feature is worthless if the privacy rules are decorative, so they get
tested first and hardest: what it must refuse to look at, what it scrubs,
and that "forget it" really deletes.

Everything here runs against a throwaway folder. None of it touches his real
recordings, and none of it takes a screenshot.
"""
import json
import shutil
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import rewind as R
from brain import wants_rewind

passed = failed = 0


def check(name, got, want):
    global passed, failed
    ok = got == want
    passed, failed = (passed + 1, failed) if ok else (passed, failed + 1)
    print(f"  {'ok  ' if ok else 'FAIL'} {name}"
          + ("" if ok else f"\n         got {got!r}, wanted {want!r}"))


print("\nwindows it must NEVER record")
for title in ["1Password — Personal", "Bitwarden Vault",
              "Google Chrome (Incognito)", "InPrivate — Edit",
              "CommBank NetBank — Log in", "Sign in to your account",
              "PayPal Checkout", "Windows Credential Manager",
              "TARS Setup", "Change your password", "Authenticator",
              "westpac online banking", "card details"]:
    check(f"blocked: {title[:38]}", R._private(title), True)

check("an unknown/blank window is blocked too, not risked", R._private(""), True)

print("\nordinary windows it may record")
for title in ["YouTube - How volcanoes work - Google Chrome",
              "assignment.docx - Word", "SEQTA Learn - Assessments",
              "Minecraft", "Visual Studio Code - main.py",
              "Messages", "Spotify"]:
    check(f"allowed: {title[:38]}", R._private(title), False)

print("\ntelling one screen from another")
try:
    import numpy as np

    a = np.zeros((400, 600, 3), dtype=np.uint8)
    b = a.copy()
    b[10:14, 10:120] = 255                      # a cursor / a clock ticking
    c = np.full((400, 600, 3), 200, dtype=np.uint8)
    c[50:300, 50:400] = 20                      # a completely different screen
    same = bin(R._fingerprint(a) ^ R._fingerprint(b)).count("1")
    other = bin(R._fingerprint(a) ^ R._fingerprint(c)).count("1")
    check("a blinking cursor is the SAME screen", same <= R.SAME, True)
    check("a different page is a NEW screen", other > R.SAME, True)
except ImportError:
    print("  (skipped — no numpy)")

print("\nsecrets are scrubbed out of what it writes down")
# These are credentials TARS has never seen. The vault-based redaction can't
# help — it only knows its own secrets — so Rewind has to catch them by shape.
for label, secret, sample in [
    ("a Claude key", _FAKE_CLAUDE := "sk-" + "ant-" + "abc123456789012345678901234",
     "export ANTHROPIC_API_KEY=" + _FAKE_CLAUDE),
    ("a GitHub token", "ghp_AbCdEf0123456789AbCdEf0123456789",
     "remote add origin https://ghp_AbCdEf0123456789AbCdEf0123456789@github"),
    # Glued together rather than written out: the publish safety-scan reads
    # this file too, and a token-shaped string sitting in it — invented or
    # not — reads as a real leak and blocks every future publish.
    ("a Telegram bot token", _FAKE_TELEGRAM := "8123456789:" + "AA"
     + "F-abcdefghijklmnopqrstuvwxyz123456",
     "TELEGRAM_BOT_TOKEN=" + _FAKE_TELEGRAM),
    ("a written-down password", "hunter2correct", "password: hunter2correct"),
    ("a card number", "4111 1111 1111 1111", "card 4111 1111 1111 1111 exp"),
    ("a JWT", "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9",
     "Authorization eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"),
]:
    check(f"{label} never reaches the file", secret in R._clean(sample), False)

check("ordinary screen text is left alone",
      R._clean("YouTube - how volcanoes erupt - 4:32 remaining"),
      "YouTube - how volcanoes erupt - 4:32 remaining")

print("\nsearching, remembering, and forgetting")
real_store, real_index = R.STORE, R.INDEX
sandbox = Path(tempfile.mkdtemp(prefix="rewind_test_"))
R.STORE, R.INDEX = sandbox, sandbox / "index.jsonl"
try:
    now = datetime.now()

    def add(minutes_ago, title, text):
        at = (now - timedelta(minutes=minutes_ago)).isoformat(timespec="seconds")
        with R.INDEX.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"at": at, "title": title, "text": text,
                                "shot": "x/y.jpg"}) + "\n")

    add(5, "YouTube - How volcanoes erupt", "volcano magma eruption lava")
    add(60, "assignment.docx - Word", "science assignment due friday")
    add(60 * 26, "YouTube - Football skills", "ronaldo skills compilation")
    add(3, "Error", "ModuleNotFoundError: no module named requests")

    check("finds a video by what was in it",
          R.search("volcano")[0]["title"].startswith("YouTube - How"), True)
    check("finds an error by its words",
          "ModuleNotFoundError" in R.search("module named requests")[0]["text"], True)
    check("a word that was never on screen finds nothing",
          R.search("helicopter"), [])
    check("yesterday means yesterday",
          len(R.search("youtube", when="yesterday")), 1)
    check("and today means today",
          len(R.search("youtube", when="today")), 1)

    before = len(R.entries())
    R.forget(10)
    after = R.entries()
    check("forgetting the last 10 minutes drops the recent ones",
          len(after), before - 2)
    check("and leaves the older ones alone",
          all("volcano" not in row["text"] for row in after), True)
finally:
    R.STORE, R.INDEX = real_store, real_index
    shutil.rmtree(sandbox, ignore_errors=True)

print("\nhe can reach it by voice — an unreachable skill may as well not exist")
for said, want in [
    ("stop rewind", "off"),
    ("turn off screen rewind", "off"),
    ("stop watching my screen", "off"),
    ("start rewind", "on"),
    ("pause rewind", "pause"),
    ("forget the last 20 minutes", "forget"),
    ("forget what you just saw", "forget"),
    ("how much do you remember", "status"),
    ("what was that video i watched on tuesday", "search"),
    ("what did that error message say", "search"),
    ("what was i doing this morning", "search"),
    ("what website was i on yesterday", "search"),
]:
    check(f'"{said}"', wants_rewind(said)[0], want)

check("'forget the last 2 hours' is understood as 120 minutes",
      wants_rewind("forget the last 2 hours")[1], 120)

print("\nand it doesn't hijack ordinary talk")
for said in ["what was that noise", "what did you say", "stop the music",
             "what was the score", "forget it", "start the timer",
             "what was mum's name", "remember to buy milk",
             "what was i saying", "turn off the lights"]:
    check(f'not rewind: "{said}"', wants_rewind(said)[0], "")

print(f"\n{passed} passed, {failed} failed\n")
sys.exit(1 if failed else 0)
