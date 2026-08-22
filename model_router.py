"""Choosing WHICH local brain answers, question by question.

The idea is taken from OpenJarvis (Stanford, Apache-2.0), whose whole
argument is that a personal AI should run on the cheapest thing that can
actually do the job, and only reach for something bigger when the question
earns it. Their router scores a query for code, maths and reasoning and
picks a model to match. This is that idea, written for TARS and measured on
his machine — not their code, which is built around their own model
registry.

Why it's worth doing here: TARS had eight models installed and used exactly
one of them for everything, chosen once by how powerful the PC is. Measured
on his box, warm:

    qwen2.5:3b     0.5s      qwen3:14b     2.2s

Four times quicker for "what time do people eat dinner", which is most of
what anyone actually asks a voice assistant. But the same measurement shows
why naive per-question switching would be a mistake:

    qwen2.5:3b     5.8s cold      qwen3:14b    13.5s cold

Swapping models means loading one. Route every question to its theoretical
best model and most questions pay six to fourteen seconds to save two — the
routing would be right and the assistant would be slower. So this is built
around what is ALREADY LOADED, and only pays a load when the gain is worth
it: a coding question, or something genuinely hard.

One rule that isn't from the paper: while he's gaming, everything goes to
the smallest model. That's from watching TARS eat 40% of a core mid-match.

August 2026 addendum: there is now a cloud brain (cloud_brain.py — Ox Alpha,
a free frontier preview on OpenRouter). It changes two conclusions above.
The escalation tier this machine never had a good local model for now has
a genuinely big model that costs nothing and loads nothing. And the gaming
rule inverts: the whole point of dropping to the 3B mid-game was local
compute, and a cloud model uses none at all — so mid-game the BIGGEST brain
is now also the cheapest one for the PC. Trivial and everyday questions
still never leave the house: local stays the default, the cloud has to be
earned, and struggling() judges Ox by exactly the same re-ask evidence as
everyone else.
"""
import re
import time

# Models by job. Each is a preference list — the first one installed wins,
# so a machine without the coder model still routes sensibly.
FAST = ["qwen2.5:3b", "qwen2.5:1.5b", "llama3.2:3b"]
CODE = ["qwen2.5-coder:14b", "qwen2.5-coder:7b", "deepseek-coder:6.7b"]

# Deliberately NOT qwen3, and this is the interesting bit. qwen3 is a
# REASONING model: left to itself it spends its whole word budget thinking
# and returns an empty answer — measured at 791 characters of thinking and
# 0 of reply, which is exactly what "he just ghosted me" looks like. The fix
# is to disable the thinking, and then you are paying for a big slow model
# with the one thing that makes it good switched off:
#
#     qwen3:14b, thinking off   18.6s   767 characters
#     qwen2.5:7b                 4.3s   840 characters
#
# Four times slower, no better. So on THIS machine there is no local model
# worth escalating to — the 7B is the sweet spot, and anything genuinely
# beyond it should go to the big brain rather than to a bigger local model
# pretending. The list stays for machines that have a plain (non-thinking)
# larger model installed.
DEEP = ["qwen2.5:14b", "qwen2.5:32b", "llama3.1:70b"]

# A question has to be clearly trivial to drop to the small model, and
# clearly hard to justify loading a big one. Everything in between stays on
# whatever is already answering — the middle is where switching costs more
# than it wins.
#
# The escalation bar is set against HIS default, which is a 7B. Sending a
# real maths or reasoning question to a 14B is a genuine gain over that;
# it wouldn't be if the default were already the 14B. Simple arithmetic
# still stays put — "calculate 2+2" is a maths question and not a hard one.
TRIVIAL_BELOW = 0.20
HARD_ABOVE = 0.45
# Above this, no local model on this machine is really the right tool. A 7B
# or a 14B running on a home PC will answer — that's the problem, it always
# answers — and the answer to something genuinely hard will be mediocre in a
# way that isn't obvious. The honest move is to say so and offer the big
# brain, which runs on his existing Claude subscription, rather than quietly
# handing over a weak answer as though it were the best available.
VERY_HARD = 0.55


def deserves_big_brain(text: str) -> bool:
    """Is this beyond what a local model should be trusted with?"""
    hard, signals = score(text)
    # a long question with real reasoning in it, not just a long ramble
    return hard >= VERY_HARD and (signals["reasoning"] or signals["code"]
                                  or signals["math"])

_CODE_RX = re.compile(
    r"\b(?:def |class |import |function|await |const |var |=>|\{\}|\[\]|"
    r"regex|stack ?trace|traceback|compile|syntax error|null pointer|"
    r"python|javascript|typescript|java\b|rust\b|css\b|html\b|sql\b|"
    r"bug in|debug|refactor|api call)\b|[{}<>]=|==|!=|\(\)|;\s*$", re.I)
_MATH_RX = re.compile(
    r"\b(?:calculate|solve|equation|integral|derivative|algebra|quadratic|"
    r"factorise|factorize|simultaneous|percentage|probability|matrix|"
    r"trigonometry|sine|cosine|logarithm)\b|\d+\s*[\^+\-*/x]\s*\d+", re.I)
_REASON_RX = re.compile(
    r"\b(?:why|how come|explain|compare|difference between|pros and cons|"
    r"step by step|work out|plan|strategy|decide|should i|analyse|analyze|"
    r"summarise|summarize|because|reasoning|trade.?off)\b", re.I)
# short, closed questions — the bread and butter of a voice assistant
_TRIVIAL_RX = re.compile(
    r"^(?:what(?:'s| is) the |what time|when is|who is|where is|how many|"
    r"how much|is it|are you|do you|can you|tell me the |remind me|"
    r"set a |turn |open |play |stop |pause |what's|hi\b|hello|thanks|"
    r"good (?:morning|night|evening))", re.I)

_installed = {"names": [], "at": 0.0}
_loaded = {"names": [], "at": 0.0}

# ---- learning from what actually happens ------------------------------
#
# The second half of OpenJarvis's argument, and the half worth more than the
# first: don't just route on rules, MEASURE what the routing did and let the
# numbers correct you. Their version tracks energy, FLOPs and latency and
# feeds it back into the router.
#
# It matters here because every threshold above this line is a guess I made.
# I measured 3B at 0.5s and 14B at 2.2s once, on an idle machine, and wrote
# rules around that. On a machine mid-game, or with a model that's fallen
# out of memory, those numbers are wrong — and nothing would ever tell me.
# So TARS times every answer and keeps the running truth per model.
#
# The second signal is cheaper and better than any benchmark: if he asks
# something again within half a minute, the answer he got was no good. That
# is a real quality measurement on his actual questions, and it costs
# nothing to collect.
from pathlib import Path

STATS = Path(__file__).resolve().parent / "model_stats.json"
REMEMBER = 40           # recent answers kept per model
REASK_SECONDS = 30      # asking again this soon means the answer missed
ENOUGH = 6              # samples before the numbers are worth trusting
TOO_MANY_REASKS = 0.34  # a third of answers re-asked is a model doing badly

_stats = {}
_last = {"model": "", "at": 0.0, "score": 0.0}


def _load_stats() -> dict:
    global _stats
    if _stats:
        return _stats
    try:
        import json

        _stats = json.loads(STATS.read_text(encoding="utf-8"))
    except Exception:
        _stats = {}
    return _stats


def _save_stats() -> None:
    try:
        import json

        STATS.write_text(json.dumps(_stats, indent=1), encoding="utf-8")
    except Exception:
        pass


def record(model: str, seconds: float, score: float = 0.0) -> None:
    """One answer happened. Note how long it really took."""
    if not model:
        return
    stats = _load_stats()
    row = stats.setdefault(model, {"times": [], "answers": 0, "reasks": 0})
    row["times"] = (row["times"] + [round(float(seconds), 3)])[-REMEMBER:]
    row["answers"] = row.get("answers", 0) + 1
    _last.update(model=model, at=time.time(), score=score)
    _save_stats()


def note_reask() -> None:
    """He asked again almost immediately — chalk that against whichever
    model just answered. Only counts if it really was just now: a question
    ten minutes later is a new question, not a complaint."""
    if not _last["model"] or time.time() - _last["at"] > REASK_SECONDS:
        return
    stats = _load_stats()
    row = stats.setdefault(_last["model"], {"times": [], "answers": 0,
                                            "reasks": 0})
    row["reasks"] = row.get("reasks", 0) + 1
    _last["model"] = ""            # one complaint per answer, not per word
    _save_stats()


def typical(model: str) -> float:
    """How long this model really takes here, or 0 if we don't know yet."""
    row = _load_stats().get(model) or {}
    times = sorted(row.get("times", []))
    if len(times) < ENOUGH:
        return 0.0
    return times[len(times) // 2]          # median: one stall shouldn't count


def struggling(model: str) -> bool:
    """Is this model's work being re-asked more than it should be?"""
    row = _load_stats().get(model) or {}
    answers = row.get("answers", 0)
    if answers < ENOUGH:
        return False
    return (row.get("reasks", 0) / answers) > TOO_MANY_REASKS


def report() -> str:
    """What TARS has learned about its own brains, in plain words."""
    stats = _load_stats()
    if not stats:
        return "I haven't answered enough yet to know which of my brains is best."
    lines = []
    for model, row in sorted(stats.items(),
                             key=lambda kv: -kv[1].get("answers", 0)):
        answers = row.get("answers", 0)
        if not answers:
            continue
        median = typical(model)
        speed = f"about {median:.1f}s" if median else "not enough yet"
        reasks = row.get("reasks", 0)
        note = ""
        if answers >= ENOUGH and reasks:
            note = f", {round(100 * reasks / answers)}% asked again"
        lines.append(f"  {model}: {answers} answers, {speed}{note}")
    return "Here's how my brains are doing:\n" + "\n".join(lines)


def _ollama(path: str, cache: dict, seconds: float) -> list:
    """Ask Ollama something cheap, and don't ask again for a while.

    This runs on the answering path, so it must never be the slow part —
    a stale list costs one slightly-wrong routing decision, and a blocking
    HTTP call costs the reply.
    """
    if time.time() - cache["at"] < seconds:
        return cache["names"]
    cache["at"] = time.time()
    try:
        import requests

        r = requests.get(f"http://127.0.0.1:11434/api/{path}", timeout=2)
        cache["names"] = [m.get("name", "") for m in r.json().get("models", [])]
    except Exception:
        pass                      # keep whatever we had; never raise from here
    return cache["names"]


def installed() -> list:
    return _ollama("tags", _installed, 300)


def resident() -> list:
    """Models loaded in memory right now — answering on one of these is free,
    answering on anything else means waiting for it to load."""
    return _ollama("ps", _loaded, 5)


def _first_available(wanted: list) -> str:
    """The first model on the list that is actually installed. Exact names
    only.

    There used to be a "same family, any tag" fallback here, and it was
    quietly wrong: asked for qwen2.5:14b, which isn't installed, it happily
    returned qwen2.5:7b-router — the separate instance the ROUTER uses to
    decide which skill to run. Answering questions on that competes with the
    routing itself for the same prompt cache, and it isn't a bigger model at
    all, which was the entire reason for asking.

    A missing model should mean "don't switch", not "switch to something
    that shares a name".
    """
    have = installed()
    for name in wanted:
        if name in have:
            return name
    return ""


def score(text: str) -> tuple:
    """(0-1 difficulty, what was spotted). Deliberately dumb and instant —
    working out whether a question is hard must never cost more than
    answering it."""
    words = len((text or "").split())
    signals = {
        "code": bool(_CODE_RX.search(text or "")),
        "math": bool(_MATH_RX.search(text or "")),
        "reasoning": bool(_REASON_RX.search(text or "")),
        "opener": bool(_TRIVIAL_RX.match((text or "").strip())),
        "words": words,
    }
    value = 0.0
    value += min(words / 60.0, 0.35)           # long questions tend to be harder
    if signals["code"]:
        value += 0.35
    if signals["math"]:
        value += 0.40
    if signals["reasoning"]:
        value += 0.32
    if signals["opener"] and words <= 12:
        value -= 0.30                          # "what time is it" is not hard
    if words <= 5:
        value -= 0.15
    return max(0.0, min(1.0, value)), signals


def _cloud() -> str:
    """The cloud brain's routing name, or "" when it shouldn't answer:
    no key, sulking after a recent failure, or its answers keep getting
    re-asked — the same evidence that benches any local model."""
    try:
        import cloud_brain

        if not cloud_brain.available():
            return ""
        name = cloud_brain.routing_name()
        if struggling(name):
            return ""
        return name
    except Exception:
        return ""


def pick(text: str, default: str, gaming: bool = False) -> tuple:
    """(model to use, why). Returns the default when nothing is worth moving
    for — which is most of the time, and is the point."""
    hard, signals = score(text)
    here = resident()

    if gaming:
        cloud = _cloud()
        if cloud:
            return cloud, "mid-game — the cloud brain costs this PC nothing"
        small = _first_available(FAST)
        if small:
            return small, "mid-game, so the small quick one"

    if signals["code"]:
        cloud = _cloud()
        if cloud:
            return cloud, "a coding question, and the cloud brain is the best coder in the house"
        coder = _first_available(CODE)
        if coder:
            return coder, "a coding question"

    if hard <= TRIVIAL_BELOW:
        small = _first_available(FAST)
        # only if it's already loaded, or it's small enough that loading it
        # costs less than the time it saves
        if small and (small in here or not here):
            # ...and only if the measurements agree. I assumed the small
            # model is quicker. Once there are enough real timings from THIS
            # machine, they decide instead of my assumption — if the small
            # one isn't actually faster here, there is no reason to use it.
            mine, theirs = typical(small), typical(default)
            if mine and theirs and mine >= theirs * 0.9:
                return default, ""
            if struggling(small):
                return default, ""       # its answers keep getting re-asked
            return small, "a quick one"

    if hard >= HARD_ABOVE:
        cloud = _cloud()
        if cloud:
            return cloud, "this one needs some proper thinking"
        big = _first_available(DEEP)
        if big and big != default and not struggling(big):
            return big, "this one needs some thinking"

    return default, ""
