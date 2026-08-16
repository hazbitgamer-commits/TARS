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
"""
import re
import time

# Models by job. Each is a preference list — the first one installed wins,
# so a machine without the coder model still routes sensibly.
FAST = ["qwen2.5:3b", "qwen2.5:1.5b", "llama3.2:3b"]
CODE = ["qwen2.5-coder:14b", "qwen2.5-coder:7b", "deepseek-coder:6.7b"]
DEEP = ["qwen3:14b", "qwen2.5:14b", "qwen3.6:35b"]

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
    have = installed()
    for name in wanted:
        for got in have:
            if got == name or got.startswith(name.split(":")[0] + ":") and got == name:
                return got
    for name in wanted:                        # looser: same family, any tag
        stem = name.split(":")[0]
        for got in have:
            if got.split(":")[0] == stem:
                return got
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


def pick(text: str, default: str, gaming: bool = False) -> tuple:
    """(model to use, why). Returns the default when nothing is worth moving
    for — which is most of the time, and is the point."""
    hard, signals = score(text)
    here = resident()

    if gaming:
        small = _first_available(FAST)
        if small:
            return small, "mid-game, so the small quick one"

    if signals["code"]:
        coder = _first_available(CODE)
        if coder:
            return coder, "a coding question"

    if hard <= TRIVIAL_BELOW:
        small = _first_available(FAST)
        # only if it's already loaded, or it's small enough that loading it
        # costs less than the time it saves
        if small and (small in here or not here):
            return small, "a quick one"

    if hard >= HARD_ABOVE:
        big = _first_available(DEEP)
        if big and big != default:
            return big, "this one needs some thinking"

    return default, ""
