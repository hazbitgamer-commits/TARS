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


_real_cloud = mr._cloud


def pretend(installed, loaded, cloud=""):
    """Fake what Ollama has, what's in memory, and whether the cloud brain
    is available.

    The cloud brain arrived after these tests did. It legitimately beats the
    local ladder for code and while gaming — it's free and it's a better
    coder than a 7B — so it has to be pinned OFF to test the local ladder at
    all, and checked separately on its own terms.
    """
    mr._installed.update(names=list(installed), at=float("inf"))
    mr._loaded.update(names=list(loaded), at=float("inf"))
    mr._cloud = (lambda: cloud)


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
check("a hard one gets the bigger brain WHERE ONE EXISTS",
      mr.pick("explain step by step why the sky is blue",
              DEFAULT)[0], DEFAULT)     # his machine: only qwen3, so no
# qwen3 is a reasoning model. Left alone it returns 791 characters of
# thinking and an empty answer — "he just ghosted me". Turn the thinking off
# to get words out of it and it's four times slower than the 7B for an answer
# that isn't better. So it is deliberately not an escalation target.
check("a thinking model is never picked, however big it is",
      "qwen3:14b" in mr.DEEP, False)
pretend(HIS_MACHINE + ["qwen2.5:14b"], ["qwen2.5:3b", DEFAULT])
check("but a plain bigger model IS used when installed",
      mr.pick("explain step by step why the sky is blue", DEFAULT)[0],
      "qwen2.5:14b")
pretend(HIS_MACHINE, ["qwen2.5:3b", DEFAULT])

check("a model that isn't installed is never substituted for a lookalike",
      mr._first_available(["qwen2.5:14b"]), "")
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

print("\nlearning from what actually happened")
# The half of OpenJarvis's argument worth more than the rules: measure, and
# let the numbers overrule the assumptions. Every threshold above this line
# is a guess made from one measurement on an idle machine.
import tempfile

from brain import wants_brain_report

real_stats = mr.STATS
try:
    def fresh_stats():
        mr.STATS = Path(tempfile.mktemp(suffix=".json"))
        mr._stats = {}
        mr._last.update(model="", at=0.0)

    fresh_stats()
    pretend(HIS_MACHINE, ["qwen2.5:3b", DEFAULT])
    check("with nothing measured it follows the rules",
          mr.pick("what time is it", DEFAULT)[0], "qwen2.5:3b")

    check("it doesn't trust a handful of samples",
          mr.typical("qwen2.5:3b"), 0.0)
    for _ in range(mr.ENOUGH):
        mr.record("qwen2.5:3b", 0.2)
    check("once there are enough, it knows the real speed",
          mr.typical("qwen2.5:3b"), 0.2)

    fresh_stats()
    for _ in range(8):
        mr.record("qwen2.5:3b", 0.9)      # small model slower HERE
        mr.record(DEFAULT, 0.4)
    check("measurements overrule my assumption that small means fast",
          mr.pick("what time is it", DEFAULT)[0], DEFAULT)

    fresh_stats()
    for _ in range(8):
        mr.record("qwen2.5:3b", 0.2)
    check("a model nobody complains about is fine",
          mr.struggling("qwen2.5:3b"), False)
    for _ in range(4):
        mr._last.update(model="qwen2.5:3b", at=__import__("time").time())
        mr.note_reask()
    check("but one whose answers keep getting re-asked is not",
          mr.struggling("qwen2.5:3b"), True)
    check("and it stops being chosen",
          mr.pick("what time is it", DEFAULT)[0], DEFAULT)

    fresh_stats()
    mr.record("qwen2.5:3b", 0.2)
    mr._last.update(model="qwen2.5:3b", at=__import__("time").time() - 600)
    mr.note_reask()
    check("a question ten minutes later is a new question, not a complaint",
          (mr._load_stats().get("qwen2.5:3b") or {}).get("reasks", 0), 0)

    fresh_stats()
    mr.record("qwen2.5:3b", 0.2)
    mr.note_reask()
    mr.note_reask()
    check("one complaint per answer, not one per word",
          (mr._load_stats().get("qwen2.5:3b") or {}).get("reasks", 0), 1)

    fresh_stats()
    check("it says so plainly when it hasn't learned anything yet",
          "haven't answered enough" in mr.report(), True)
    for _ in range(mr.ENOUGH):
        mr.record("qwen2.5:3b", 0.35)
    check("and reports real numbers once it has",
          "qwen2.5:3b" in mr.report() and "0.3" in mr.report(), True)

    check("recording a blank model is ignored rather than crashing",
          mr.record("", 1.0), None)
finally:
    mr.STATS = real_stats
    mr._stats = {}

print("\nknowing when a local model isn't the right tool at all")
# A local model always answers. That's the trouble — on something genuinely
# hard the answer is mediocre in a way that doesn't LOOK mediocre. Better to
# say so and offer the big brain than pass it off as the best available.
for text, offer in [
    ("what time is it", False),
    ("hows your day", False),
    ("why is the sky blue", False),
    ("set a timer for ten minutes", False),
    ("tell me a joke", False),
    ("explain step by step how i should plan my science assignment and why "
     "that order works best", True),
    ("fix this python function, it throws a traceback, and explain why", True),
]:
    check(f'{"offers" if offer else "doesn\'t"}: "{text[:44]}"',
          mr.deserves_big_brain(text), offer)

check("a long ramble with no real question in it doesn't trigger it",
      mr.deserves_big_brain("so anyway i was walking to school and then the "
                            "bus was late and my mate said the thing about "
                            "the game and it was all a bit much really"), False)

guts = Path("brain.py").read_text(encoding="utf-8")
check("the offer is only ever added to an answer that exists",
      "len(answer) > 40" in guts, True)
check("and it never doubles up on itself",
      'not in (answer or "").lower()' in guts, True)

print("\nhe can actually ask about it")
for said in ["which brain are you using", "how are your brains",
             "what model are you on", "brain stats"]:
    check(f'"{said}"', wants_brain_report(said), True)
for said in ["how are you", "whats the weather", "which one is better"]:
    check(f'not the report: "{said}"', wants_brain_report(said), False)

print("\nhearing a word isn't the same as being told it")
# His words: "i dont like it how if he hears a key word he refuses to adapt
# to the sentence." From the logs: he said "I'm not watching Taskmaster!" and
# TARS replied "Understood. Let's proceed with shutting down the PC."
from brain import (means_it, wants_clip, wants_guard, wants_presence,
                   wants_rewind)


def anything(said):
    return (wants_clip(said)[0] or wants_rewind(said)[0]
            or wants_presence(said) or wants_guard(said) or "")


print("  commands still work:")
for said, want in [("clip that", "clip"), ("watch for me", "on"),
                   ("stop watching for me", "off"), ("guard my room", "on"),
                   ("stop rewind", "off"),
                   ("forget the last 20 minutes", "forget")]:
    check(f'    "{said}"', anything(said), want)

print("  but saying the words isn't asking:")
for said in ["i'm not watching taskmaster",
             "don't clip that",
             "no need to watch for me",
             "what does clip that do",
             "you said stop watching",
             "he told me to stop watching",
             "i didn't say guard my room",
             "never clip that again",
             "instead of guarding my room just tell me"]:
    check(f'    "{said}"', anything(said), "")

check("a plain command means it", means_it("clip that"), True)
check("a negated one doesn't", means_it("dont clip that", 5), False)
check("and asking about it doesn't", means_it("what does clip that do"), False)


print(chr(10) + "the cloud brain, which outranks the local ladder where it is better")
CLOUD = "cloud:stealth/ox-alpha"
pretend(HIS_MACHINE, ["qwen2.5:3b", DEFAULT], cloud=CLOUD)
check("a coding question goes to the cloud, not the local coder",
      mr.pick("theres a bug in my python function", DEFAULT)[0], CLOUD)
check("and mid-game it does too, costing this PC nothing",
      mr.pick("what time is it", DEFAULT, gaming=True)[0], CLOUD)
check("ordinary chat still stays local",
      mr.pick("hows your day", DEFAULT)[0] in (DEFAULT, "qwen2.5:3b"), True)
pretend(HIS_MACHINE, ["qwen2.5:3b", DEFAULT], cloud="")
check("with no cloud it falls back to the local coder",
      mr.pick("theres a bug in my python function", DEFAULT)[0], "qwen2.5-coder:14b")
check("and mid-game to the small local one",
      mr.pick("what time is it", DEFAULT, gaming=True)[0], "qwen2.5:3b")


print(chr(10) + "a repeat on ANY command makes it try something else")
from brain import _VoiceGuarded
class _Box2:
    def run(self, name, args):
        return {"browser_search": "Searching for best VPN for changing location in your browser.",
                "open_app": "Opened the downloads folder for you."}.get(name, "")
    def catalog(self): return [{"skill": "browser_search"}, {"skill": "open_app"}]
class _B2:
    _NO_RESCUE = {"chat"}
    _asked_now = ""
    def _voice_block(self, n): return None
    def _journal(self, l): pass
    def _route(self, text, must_act=False): return {"skill": "open_app", "args": {}}
_b2 = _B2(); _g2 = _VoiceGuarded(_Box2(), _b2)
_b2._asked_now = "find me the best vpn"
_first2 = _g2.run("browser_search", {})
_b2._asked_now = "now download one of them"
_second2 = _g2.run("browser_search", {})
# It used to RUN the alternative automatically. That executed an action he
# had not asked for, on the conversation thread, and when the second skill
# blocked TARS went silent mid-sentence — "he js left me on read". It now
# names the alternative and waits to be asked.
check("a repeated line is called out rather than parroted",
      "same answer I just gave" in _second2, True)
check("and it offers what else it could do, without doing it",
      "could try" in _second2 or _second2.endswith("another go."), True)
check("the first answer is untouched", _first2.startswith("Searching"), True)
_b2._asked_now = "volume 30"
_g3 = _VoiceGuarded(_Box2(), _b2)
_g3.run("open_app", {})
check("the SAME command twice is left alone",
      _g3.run("open_app", {}), "Opened the downloads folder for you.")


print(chr(10) + "an app to install is not a GitHub search")
from brain import wants_an_app_not_a_library as _app
# "Find me a good VPN and open the installer" went to find_tool and came
# back with OpenWrt config files and starred repos. He wanted something to
# install; find_tool is for a developer after a library.
for _s in ["find me a good vpn and open the installer", "download me the best vpn",
           "recommend a good antivirus", "get me a better browser"]:
    check(f"app: {_s[:40]}", _app(_s), True)
for _s in ["find me a python library for pdfs", "search github for a subtitle downloader",
           "is there a package for reading pdfs", "whats the weather",
           "find my keys"]:
    check(f"not an app: {_s[:36]}", _app(_s), False)

print(chr(10) + "no skill can hold the conversation open forever")
import time as _tm
class _Slow:
    def run(self, n, a):
        _tm.sleep(30)
        return "done"
    def catalog(self): return []
class _B3:
    _NO_RESCUE = set(); _asked_now = "x"
    def _voice_block(self, n): return None
    def _journal(self, l): pass
_old_p = _VoiceGuarded.PATIENCE
_VoiceGuarded.PATIENCE = 2
try:
    _g4 = _VoiceGuarded(_Slow(), _B3())
    _t0 = _tm.time(); _r4 = _g4.run("find_tool", {})
    check("a stalling skill still gets an answer out", _tm.time()-_t0 < 5, True)
    check("and says it is still working", "taking a while" in _r4, True)
finally:
    _VoiceGuarded.PATIENCE = _old_p
check("the limit is generous enough for real work", _VoiceGuarded.PATIENCE >= 20, True)

print(f"\n{passed} passed, {failed} failed\n")
sys.exit(1 if failed else 0)