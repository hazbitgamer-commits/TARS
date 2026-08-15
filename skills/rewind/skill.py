"""Asking about screens that have already gone.

"What was that video I watched on Tuesday?" — the answer was on the screen
at the time and is nowhere now. This looks back through what Screen Rewind
kept and answers from it.

It also carries the off switch and the eraser, deliberately: the thing that
searches your screen history and the thing that stops it recording should
never be two features you have to find separately.
"""
DESCRIPTION = (
    "Search or control Screen Rewind — TARS's memory of what has been on "
    "the screen. Use for 'what was that video I watched on Tuesday', 'what "
    "did that error say', 'what was the website I had open yesterday', "
    "'what was I doing this morning', 'what was that thing about the "
    "assignment'. Also handles 'stop rewind' / 'start rewind' / 'pause "
    "rewind', 'forget the last twenty minutes', and 'how much do you "
    "remember'. NOT for his own notes or memories he told TARS (that's the "
    "vault) and NOT for taking a screenshot right now (that's screenshot).")
ARGS = {
    "query": "what to look for, e.g. 'video about volcanoes' or 'the error message'",
    "when": "optional time, e.g. 'tuesday', 'yesterday', 'this morning', 'last week'",
    "action": "optional: 'off', 'on', 'pause', 'forget', or 'status'",
    "minutes": "how many minutes to forget or pause for, when the action needs it",
}


def run(args: dict) -> str:
    import rewind

    action = str(args.get("action") or "").lower().strip()
    query = str(args.get("query") or "").strip()
    when = str(args.get("when") or "").strip()

    try:
        minutes = int(float(args.get("minutes") or 0))
    except (TypeError, ValueError):
        minutes = 0

    if action in ("off", "stop", "disable"):
        return rewind.turn(False)
    if action in ("on", "start", "enable"):
        return rewind.turn(True)
    if action == "pause":
        return rewind.pause(minutes or 30)
    if action in ("forget", "erase", "delete"):
        return rewind.forget(minutes or 15)
    if action == "status" or (not query and not when):
        return rewind.status()

    found = rewind.search(query, when)
    if not found:
        window = f" from {when}" if when else ""
        return (f"Nothing{window} matching that, I'm afraid. I only remember "
                f"screens you stayed on for a few seconds, and I skip "
                f"anything private.")

    lines = []
    for row in found:
        at = row["at"].replace("T", " ")[:16]
        title = (row.get("title") or "").strip() or "something"
        snippet = _around(row.get("text", ""), query)
        lines.append(f"{at} — {title}" + (f": {snippet}" if snippet else ""))
    head = ("Here's what I've got:" if len(lines) > 1
            else "Found it:")
    return head + "\n" + "\n".join(f"  {line}" for line in lines)


def _around(text: str, query: str, width: int = 110) -> str:
    """The bit of the screen the search words actually appeared in — a whole
    screen of text dumped at him would be useless."""
    words = [w for w in query.lower().split() if len(w) > 2]
    low = text.lower()
    for word in words:
        found = low.find(word)
        if found >= 0:
            start = max(0, found - width // 3)
            return ("…" if start else "") + text[start:start + width].strip() + "…"
    return text[:width].strip()
