"""Hearing repair — fix garbled words using TARS's OWN vocabulary.

Whisper mangles the words that matter most: names it has never seen. the owner's
logs contain "Minicat 3D" and "minicab" (Mini CAD), "CADM" (CADAM), "Basil"
(Basel the vacuum), "Toss" (TARS), "design, may a" (design me a). TARS knows
what those words should be — his skills, apps, designs, routines, rooms and
people are a dictionary no general speech model has.

Conservative on purpose: only unusual words are considered, only close
matches are replaced, and every repair is logged so mistakes are visible.
"""
import difflib
import json
import re
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent
LOG = BASE / "logs" / "hearing_fixes.log"

# known mishearings straight from the owner's transcripts
ALIASES = {
    "minicat": "mini cad", "minicab": "mini cad", "mini cat": "mini cad",
    "mini-cad": "mini cad", "cadm": "cadam", "cad am": "cadam",
    "kadam": "cadam", "cadem": "cadam",
    "basil": "basel", "bazel": "basel", "hazel": "basel",
    "toss": "tars", "tarz": "tars", "tar's": "tars",
    "obsidion": "obsidian", "obsidiun": "obsidian",
    "design may a": "design me a", "design, may a": "design me a",
    "design my a": "design me a", "or write": "override",
    "client hours": "override quiet hours",
}
# words that must never be "corrected" — ordinary speech
COMMON = set("""a an the and or but if then than that this these those is are
was were be been being do does did done have has had will would can could
should may might must i you he she it we they me him her us them my your his
their our what when where who why how all any both each few more most other
some such no nor not only own same so too very just now here there about
above after again against because before below between down during for from
in into of off on once out over under up with without to too also please
yes yeah no nah okay ok right sure thanks thank hey hi hello""".split())


def _vocab() -> dict:
    """TARS's own words → the phrases they should be."""
    words: dict[str, str] = {}

    def add(phrase: str) -> None:
        phrase = (phrase or "").strip().lower()
        if len(phrase) >= 3:
            words[phrase] = phrase

    # deliberately NOT skill names: they're ordinary English ("lists",
    # "timers", "weather") and fuzzy-matching turned "shopping list" into
    # "shopping lists". Only proper nouns — things no dictionary knows.
    for path, pattern in ((BASE / "workshop" / "designs", "*.scad"),
                          (BASE / "faces", "*.jpg")):
        try:
            for p in path.glob(pattern):
                add(p.stem.replace("_", " "))
        except OSError:
            pass
    for f, key in ((BASE / "routines.json", None),
                   (BASE / "vacuum_rooms.json", None)):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            for name in (data.keys() if isinstance(data, dict) else data):
                add(str(name))
        except (OSError, json.JSONDecodeError, AttributeError):
            pass
    for extra in ("tars", "basel", "obsidian", "cadam", "mini cad", "kipp",
                  "solax", "eufy", "steam", "brave", "telegram", "openscad",
                  "sophie", "emma", "luke"):
        add(extra)
    return words


_cache: dict = {"t": 0.0, "words": {}}


def vocabulary() -> dict:
    if time.time() - _cache["t"] > 120:
        _cache.update(t=time.time(), words=_vocab())
    return _cache["words"]


def fix(text: str) -> str:
    """Repair TARS-specific words in a transcript. Returns the text."""
    if not text or len(text) < 3:
        return text
    original = text
    low = text.lower()

    for wrong, right in ALIASES.items():          # known mishearings first
        if wrong in low:
            low = low.replace(wrong, right)
    words = vocabulary()
    tokens = re.findall(r"[\w']+|\W+", low)
    out = []
    for tok in tokens:
        word = tok.strip().lower()
        if (not word.isalpha() or len(word) < 4 or word in COMMON
                or word in words):
            out.append(tok)
            continue
        match = difflib.get_close_matches(word, list(words), n=1, cutoff=0.82)
        # only swap when the heard word isn't a plain English word itself —
        # rough test: TARS's vocabulary is proper nouns, so require the
        # match to be clearly closer than a coincidence
        if match and difflib.SequenceMatcher(None, word, match[0]).ratio() >= 0.85:
            out.append(tok.replace(word, match[0]))
        else:
            out.append(tok)
    fixed = "".join(out)
    if fixed.lower() != original.lower():
        try:
            LOG.parent.mkdir(exist_ok=True)
            with open(LOG, "a", encoding="utf-8") as f:
                f.write(f"{time.strftime('%H:%M')} {original!r} -> {fixed!r}\n")
        except OSError:
            pass
        return fixed[0].upper() + fixed[1:] if original[:1].isupper() else fixed
    return original
