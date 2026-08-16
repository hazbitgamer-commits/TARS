"""Checking the presence watch and the game clipper.

The two things that matter most here aren't features, they're limits:

  - the camera must do NOTHING until he arms it, because his standing rule
    is that the webcam opens on an explicit word and never on its own.
  - TARS locks the PC and never unlocks it. Locking is something anyone can
    do; unlocking is defeating the lock, and an assistant shouldn't hold it.

After that it's routing, which is where every one of these features has
actually failed before — a skill nothing can reach may as well not exist,
and two camera features answering to the same words is worse than either.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import presence
from brain import wants_clip, wants_presence

passed = failed = 0


def check(name, got, want):
    global passed, failed
    ok = got == want
    passed, failed = (passed + 1, failed) if ok else (passed, failed + 1)
    print(f"  {'ok  ' if ok else 'FAIL'} {name}"
          + ("" if ok else f"\n         got {got!r}, wanted {want!r}"))


print("\nthe camera stays shut until he says otherwise")
# armed() re-reads the saved state on purpose — the answer to "is the camera
# on" must come from the file everything else agrees on, not from whatever
# this process happens to hold in memory.
try:
    presence.turn(False)
    check("it starts off", presence.armed(), False)
    check("and says so plainly",
          "not watching" in presence.status().lower(), True)
    presence.turn(True)
    check("armed only when asked", presence.armed(), True)
finally:
    presence.turn(False)          # never leave his camera armed by a test
check("a test can't leave the camera on", presence.armed(), False)

print("\nit locks, and it must never unlock")
source = Path("presence.py").read_text(encoding="utf-8").lower()
check("there is a lock", "def lock_screen" in source, True)
check("there is NO unlock anywhere in the file",
      any(word in source for word in ("def unlock", "unlockworkstation",
                                      "auto_login", "autologon",
                                      "defaultpassword")), False)
check("it says out loud that it can't unlock",
      "can't unlock" in presence.turn(True).lower(), True)
presence.turn(False)

print("\narming and disarming by voice")
for said, want in [
    ("watch for me", "on"),
    ("keep an eye out for me", "on"),
    ("lock my pc when i leave", "on"),
    ("pause my music when i walk away", "on"),
    ("stop watching for me", "off"),
    ("stop watching me", "off"),
    ("turn off presence", "off"),
    ("are you watching for me", "status"),
]:
    check(f'"{said}"', wants_presence(said), want)

print("\nand it doesn't grab things meant for something else")
for said in ["watch for hand signals", "stop watching the screen",
             "guard my room", "watch this video", "stop watching netflix",
             "keep an eye on the download", "what's the weather"]:
    check(f'not presence: "{said}"', wants_presence(said), "")

print("\nclipping the thing that already happened")
for said, want in [
    ("clip that", "clip"),
    ("clip the last 15 seconds", "clip"),
    ("did you get that", "clip"),
    ("save that clip", "clip"),
    ("highlight that", "clip"),
    ("turn off highlights", "off"),
    ("start highlights", "on"),
    ("are you recording", "status"),
]:
    check(f'"{said}"', wants_clip(said)[0], want)

check("'clip the last 15 seconds' picks up the 15",
      wants_clip("clip the last 15 seconds")[1], 15)

print("\nand it leaves ordinary talk alone")
for said in ["clip my nails", "that was a good game", "save my work",
             "record a voice note", "stop the music", "what did you get"]:
    check(f'not clip: "{said}"', wants_clip(said)[0], "")

print("\nthe clipper is honest when there's nothing to clip")
import highlights

highlights._frames.clear()
answer = highlights.save("test", send=False)
check("it admits it has no footage rather than inventing a clip",
      any(word in answer.lower()
          for word in ("not in one", "haven't got", "isn't enough")), True)

print("\nsending a clip must NEVER block the voice loop")
# This one cost a working assistant. The conversation loop stops the
# microphone before it speaks and only restarts it once the reply is
# finished. A clip skill that uploaded 29MB to Telegram on that same thread
# left TARS alive, answering the dashboard, and stone deaf for minutes.
import threading as _threading
import time as _time
import types as _types

import numpy as _np

sent = {"thread": None, "done": False}


def slow_send(path, caption=""):
    sent["thread"] = _threading.current_thread().name
    _time.sleep(3)                      # a slow upload, as it was in real life
    sent["done"] = True
    return True


fake_phone = _types.SimpleNamespace(send_video=slow_send)
real_phone = sys.modules.get("tars_phone")
real_gaming = highlights._gaming
try:
    sys.modules["tars_phone"] = fake_phone
    highlights._gaming = lambda: True
    import cv2 as _cv2

    blank = _np.zeros((160, 284, 3), dtype=_np.uint8)
    ok, buf = _cv2.imencode(".jpg", blank)
    now = _time.time()
    highlights._frames.clear()
    for i in range(highlights.FPS * 3):
        highlights._frames.append((now - 2 + i * 0.05, buf.tobytes()))

    began = _time.time()
    reply = highlights.save("Clip", send=True, seconds=25)
    took = _time.time() - began
    check("save() comes straight back instead of waiting on the upload",
          took < 2.0, True)
    check("the upload had not finished when it returned", sent["done"], False)
    check("and it says the clip is on its way",
          "sending" in reply.lower() or "too big" in reply.lower(), True)
    _time.sleep(3.5)
    check("the upload still happened, just off to the side", sent["done"], True)
    check("on a background thread, not the caller's",
          sent["thread"] != _threading.current_thread().name, True)
finally:
    highlights._gaming = real_gaming
    highlights._frames.clear()
    if real_phone is not None:
        sys.modules["tars_phone"] = real_phone
    else:
        sys.modules.pop("tars_phone", None)
    for leftover in highlights.CLIPS.glob("*.mp4"):
        if _time.time() - leftover.stat().st_mtime < 60:
            leftover.unlink()

print(f"\n{passed} passed, {failed} failed\n")
sys.exit(1 if failed else 0)
