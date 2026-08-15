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

print(f"\n{passed} passed, {failed} failed\n")
sys.exit(1 if failed else 0)
