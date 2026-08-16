"""Checking TARS picks the right local brain for each question.

The idea comes from OpenJarvis (Stanford, Apache-2.0): run on the cheapest
thing that can do the job, and reach for something bigger only when the
question earns it. What's tested here is mostly the RESTRAINT, because the
failure mode isn't picking a poor model — it's picking a better one that
isn't loaded, and paying six to fourteen seconds to load it in order to save
two. A router that's theoretically right and practically slower is worse
than no router.

Nothing here talks to Ollama. The list of installed models is faked, so
these run the same on a machine with one model or ten.
"""
import sys
from pathlib import Path

# the console here is cp1252, and one of the test inputs is deliberately an
# emoji — printing it raw killed the run on the last line, which would have
# looked like the router failing when the router was fine
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

sys.path.insert(0, str(Path(__file__).resolve().parent))
import model_router as mr

passed = failed = 0
DEFAULT = "qwen2.5:7b"
HIS_MACHINE = ["qwen2.5:3b", "qwen2.5:7b", "qwen3:14b", "qwen2.5-coder:14b",
               "nomic-embed-text:latest"]


def check(name, got, want):
    global passed, failed
    ok = got == want
    passed, failed = (passed + 1, failed) if ok else (passed, failed + 1)
    print(f"  {'ok  ' if ok else 'FAIL'} {name}"
          + ("" if ok else f"\n         got {got!r}, wanted {want!r}"))


def pretend(installed, loaded):
    """Fake what Ollama has and what's in memory."""
    mr._installed.update(names=list(installed), at=float("inf"))
    mr._loaded.update(names=list(loaded), at=float("inf"))


print("\nscoring — is this question actually hard?")
for text, hard in [
    ("what time is it", False),
    ("hi", False),
    ("thanks", False),
    ("turn the lights off", False),
    ("whats the weather", False),
    ("calculate 2 + 2", False),
    ("solve the quadratic equation x^2 + 5x + 6 = 0", True),
    ("why is the sky blue, explain step by step", True),
    ("compare the pros and cons of doing my assignment tonight or tomorrow", True),
]:
    got, _ = mr.score(text)
    check(f'{"hard " if hard else "easy "} "{text[:44]}"',
          got >= mr.HARD_ABOVE, hard)

check("a code question is spotted",
      mr.score("fix the bug in my python function")[1]["code"], True)
check("a maths question is spotted",
      mr.score("solve this equation")[1]["math"], True)
check("plain chat is neither",
      mr.score("tell me about your day")[1]["code"]
      or mr.score("tell me about your day")[1]["math"], False)

print("\npicking — with everything installed and the 3B already loaded")
pretend(HIS_MACHINE, ["qwen2.5:3b", DEFAULT])
check("a trivial question drops to the small one",
      mr.pick("what time is it", DEFAULT)[0], "qwen2.5:3b")
check("a coding question gets the coder",
      mr.pick("theres a bug in my python function", DEFAULT)[0],
      "qwen2.5-coder:14b")
check("a hard one gets the bigger brain",
      mr.pick("explain step by step why the sky is blue", DEFAULT)[0],
      "qwen3:14b")
check("everything in between stays put",
      mr.pick("what should i do about dinner tonight", DEFAULT)[0], DEFAULT)

print("\nrestraint — the part that stops it being slower than no router")
pretend(HIS_MACHINE, ["qwen3:14b"])        # only the big one is warm
check("it won't load the small model just to save a moment",
      mr.pick("what time is it", DEFAULT)[0], DEFAULT)
pretend(HIS_MACHINE, [])
check("with nothing loaded at all, a trivial question may take the small one",
      mr.pick("what time is it", DEFAULT)[0], "qwen2.5:3b")

print("\nmid-game, everything goes to the smallest")
pretend(HIS_MACHINE, ["qwen3:14b"])
for text in ["explain step by step why the sky is blue",
             "fix the bug in my python function",
             "what time is it"]:
    check(f'"{text[:40]}"', mr.pick(text, DEFAULT, gaming=True)[0], "qwen2.5:3b")
check("and it says why", "mid-game" in mr.pick("hi", DEFAULT, gaming=True)[1], True)

print("\na machine that hasn't got those models")
pretend([DEFAULT], [DEFAULT])
for text in ["what time is it", "fix the bug in my python code",
             "explain step by step why the sky is blue"]:
    check(f'falls back to the default: "{text[:36]}"',
          mr.pick(text, DEFAULT)[0], DEFAULT)

pretend([], [])
check("no models listed at all still answers with the default",
      mr.pick("anything", DEFAULT)[0], DEFAULT)

print("\nit must never break answering")
pretend(HIS_MACHINE, ["qwen2.5:3b"])
for odd in ["", "   ", None, "?" * 500, "\n\n", "🙂🙂🙂"]:
    try:
        model, _ = mr.pick(odd, DEFAULT)
        ok = bool(model)
    except Exception:
        ok = False
    check(f"survives {repr(odd)[:22]}", ok, True)

print("\nand the brain uses it without ever failing over to nothing")
guts = Path("brain.py").read_text(encoding="utf-8")
body = guts[guts.index("def _model_for"):guts.index("def _ask_ollama")]
check("a broken router falls back to the usual model",
      "return MODEL" in body and "except Exception" in body, True)
check("the question is passed to the streaming reply",
      "self._model_for(text)" in guts, True)
check("and to the plain one", guts.count("_ask_ollama(messages, text)"), 2)

print(f"\n{passed} passed, {failed} failed\n")
sys.exit(1 if failed else 0)
