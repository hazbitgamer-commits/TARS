"""'change Luka Kapilovic to Luka Pavlovic' — fuzzy find-and-replace a name/word
across TARS's memory vault (handles the fact that speech-to-text spells the same
name differently each time), and renames any note file titled with the old name.
"""
import difflib
import re
from pathlib import Path

VAULT = Path(__file__).resolve().parents[2] / "vault"

DESCRIPTION = ("Correct a wrong or misspelled name (person, place, thing) everywhere it "
               "appears in TARS's memory vault — fixes it inside note text and renames "
               "any note file titled with the old name. Matches loosely, so it still "
               "works if speech-to-text spelled it a bit differently each time. "
               "E.g. 'change Luka Kapilovic to Luka Pavlovic', 'correct John Smith to "
               "Jon Smith'. NOT for saving a brand-new fact — that's the remember skill.")
ARGS = {"old": "the name/word as it's currently written or misspelled",
        "new": "what it should be changed to"}

SKIP_DIRS = {".obsidian"}
# capitalised word, or up to 3 in a row (e.g. "Luke Capalovich")
PHRASE_RE = re.compile(r"\b[A-Z][a-zA-Z'-]*(?:\s+[A-Z][a-zA-Z'-]*){0,2}\b")
THRESHOLD = 0.6
INVALID_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*]')


def _similar(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a.lower(), b.lower()).ratio()


def run(args: dict) -> str:
    old = (args.get("old") or "").strip()
    new = (args.get("new") or "").strip()
    if not old or not new:
        return "I need both the current name and the corrected name to do that."
    if not VAULT.exists():
        return "I can't find my memory vault, so there's nothing to correct."

    safe_new_stem = INVALID_FILENAME_CHARS.sub("", new).strip() or new
    edited, renamed = 0, 0

    for path in sorted(VAULT.rglob("*.md")):
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue

        def repl(m):
            phrase = m.group(0)
            return new if _similar(phrase, old) >= THRESHOLD else phrase

        new_text = PHRASE_RE.sub(repl, text)
        if new_text != text:
            path.write_text(new_text, encoding="utf-8")
            edited += 1

        if _similar(path.stem, old) >= THRESHOLD:
            target = path.with_name(f"{safe_new_stem}.md")
            if target != path and not target.exists():
                path.rename(target)
                renamed += 1

    if not edited and not renamed:
        return f"I couldn't find {old} anywhere in my memory."
    bits = []
    if edited:
        bits.append(f"updated {edited} note{'s' if edited != 1 else ''}")
    if renamed:
        bits.append(f"renamed {renamed} file{'s' if renamed != 1 else ''}")
    return f"Done — {' and '.join(bits)}, {old} is now {new}."
