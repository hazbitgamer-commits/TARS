"""One command means one command, while he's in a game.

Normally TARS keeps listening for about five seconds after it answers, so he
can follow up without saying the wake word again. At a desk that's right. In
a match it's wrong: the window sits open through game audio and him talking
to teammates, and every stray word gets transcribed back at him.

His words: "after i say clip that, dont listen for me to say another thing
because that would get annoying" — and he asked for it on ANY command while
playing, not just clipping.

Testing the real loop would mean a microphone, a game and a person, so what
gets tested here is the decision itself: is he mid-game, do both paths agree,
and does asking the question change anything it shouldn't.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import game_watch
import main

passed = failed = 0


def check(name, got, want):
    global passed, failed
    ok = got == want
    passed, failed = (passed + 1, failed) if ok else (passed, failed + 1)
    print(f"  {'ok  ' if ok else 'FAIL'} {name}"
          + ("" if ok else f"\n         got {got!r}, wanted {want!r}"))


print("\nspotting a game from the window in front")
real_title, real_steam, real_learned = (game_watch._foreground_title,
                                        game_watch._steam_titles,
                                        game_watch._learned)
try:
    game_watch._steam_titles = lambda: ["portal 2", "terraria"]
    game_watch._learned = lambda: []
    for title, want in [
        ("EA SPORTS FC 26", True),
        ("Minecraft 1.21", True),
        ("Rocket League (64-bit)", True),
        ("Portal 2", True),
        ("assignment.docx - Word", False),
        ("YouTube - Google Chrome", False),
        ("TARS", False),
    ]:
        game_watch._foreground_title = lambda t=title: t
        check(f'"{title[:34]}"', game_watch.playing_now(), want)
finally:
    (game_watch._foreground_title, game_watch._steam_titles,
     game_watch._learned) = real_title, real_steam, real_learned

print("\nasking the question must not DO anything")
# _check() knows whether a game is on, but it also logs sessions and can
# announce a break reminder. Calling it just to ask would mean asking a
# question caused TARS to speak.
source = Path("game_watch.py").read_text(encoding="utf-8")
body = source[source.index("def playing_now"):source.index("def _check")]
# strip the docstring first — it EXPLAINS why _check isn't called, and
# matching that prose would pass or fail on the wording of a comment
code = body.split('"""')[-1]
check("playing_now doesn't call _check", "_check()" in code, False)
check("playing_now doesn't announce", "announce" in code, False)
check("it doesn't touch the session either", "_session.update" in code, False)

print("\nthe loop asks the right question")
real = main._mid_game
try:
    import types

    fake = types.SimpleNamespace(playing_now=lambda: True)
    sys.modules["game_watch"], keep = fake, sys.modules["game_watch"]
    check("mid-game says yes when a game is up", main._mid_game(), True)
    fake.playing_now = lambda: False
    check("and no when there isn't", main._mid_game(), False)

    def explode():
        raise RuntimeError("game_watch is broken")

    fake.playing_now = explode
    check("a broken game check never breaks the conversation",
          main._mid_game(), False)
    sys.modules["game_watch"] = keep
finally:
    main._mid_game = real

print("\nboth ways out of the conversation are covered")
loop = Path("main.py").read_text(encoding="utf-8")
check("the normal reply path checks it", loop.count("if _mid_game():") >= 2, True)
# the blip means "still listening" — making that sound while going straight
# back to sleep would be a small lie about what TARS is doing
after_reply = loop[loop.index("first_turn = False\n\n                # Mid-game"):]
check("it breaks BEFORE the still-listening blip",
      after_reply.index("if _mid_game():") < after_reply.index("beep(660"), True)

print("\nthe watchdog: catch a jam, never touch an idle TARS")
# The first version asked "is the state anything but listening?" — and the
# idle state is called "standby", so it restarted him every three minutes all
# day. Each restart re-ran the health check and re-announced the microphone
# warning, which he reported as "mic notifications again".
import time as _t


def would_restart(state, seconds):
    main._alive.update(state=state, since=_t.time() - seconds)
    return (main._alive["state"] in main.BUSY_STATES
            and _t.time() - main._alive["since"] > main.STUCK_AFTER)


check("idle in STANDBY is not stuck — the bug that looped all day",
      would_restart("standby", 600), False)
check("listening for an hour is not stuck", would_restart("listening", 3600), False)
check("offline is not stuck either", would_restart("offline", 600), False)
check("but a reply jammed for minutes IS", would_restart("speaking", 300), True)
check("and thinking that never ends", would_restart("thinking", 300), True)
check("a normal reply is left alone", would_restart("speaking", 5), False)
check("only real work counts as busy",
      sorted(main.BUSY_STATES), ["speaking", "thinking"])

main.note_state("listening")
check("going back to listening clears it", main._alive["state"], "listening")
_began = main._alive["since"]
main.note_state("listening")
check("repeating a state doesn't restart the clock", main._alive["since"], _began)

_real_wd = main.RECOVERED_FILE
main.RECOVERED_FILE = Path("workshop") / "_wd_check.json"
try:
    main.RECOVERED_FILE.unlink(missing_ok=True)
    check("with no history a restart is allowed",
          _t.time() - main._last_recovery() > 3600, True)
    main._remember_recovery()
    check("straight after one, another is refused",
          _t.time() - main._last_recovery() > 3600, False)
    check("and that memory is ON DISK, so a restart cannot forget it",
          main.RECOVERED_FILE.exists(), True)
finally:
    main.RECOVERED_FILE.unlink(missing_ok=True)
    main.RECOVERED_FILE = _real_wd

_guts = Path("main.py").read_text(encoding="utf-8")
_wd = _guts[_guts.index("def _watchdog"):_guts.index("def start_watchdog")]
check("it tells him on his phone rather than just vanishing",
      "tars_phone" in _wd, True)
check("and a broken watchdog can't take TARS down", "except Exception" in _wd, True)

print("\nsaying the same problem forty-five times")
# TARS said "my microphone is barely registering anything — check its level
# in Windows sound settings" 45 times across the logs, once per restart,
# while his voice commands worked perfectly. Two faults: the check was wrong
# (it opened a second mic stream on a device TARS already held, and measured
# the contention), and nothing stopped it repeating.
import json as _json

real_told = main.TOLD_FILE
main.TOLD_FILE = Path("workshop") / "_told_check.json"
try:
    main.TOLD_FILE.unlink(missing_ok=True)
    mic = "my microphone is barely registering anything"
    check("the first time, he's told", main._worth_saying([mic]), [mic])
    check("the next restart, it stays quiet", main._worth_saying([mic]), [])
    check("and the one after that", main._worth_saying([mic]), [])
    check("but something NEW is always said",
          main._worth_saying([mic, "no speakers"]), ["no speakers"])
    main._worth_saying([])          # problem clears
    check("a problem that goes away and comes back is news again",
          main._worth_saying([mic]), [mic])
    check("nothing wrong means nothing said", main._worth_saying([]), [])
    check("it waits half a day, not forever", main.SAY_AGAIN_AFTER <= 24 * 3600,
          True)
finally:
    main.TOLD_FILE.unlink(missing_ok=True)
    main.TOLD_FILE = real_told

print("\nthe mic check asks the loop that's actually listening")
doc = Path("doctor.py").read_text(encoding="utf-8")
audio = doc[doc.index("def check_audio"):doc.index("def check_extras")]
check("it reads the live listening level", "dashboard.EARS" in audio, True)
check("and only complains when nothing at all is arriving",
      "heard_level <= 0.0" in audio, True)
check("the live reading settles it, rather than opening a rival stream",
      audio.index("dashboard.EARS") < audio.index("sd.rec("), True)

print(f"\n{passed} passed, {failed} failed\n")
sys.exit(1 if failed else 0)
