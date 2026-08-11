"""Predictive search & query refinement.

the owner often has to re-ask or correct a search-type request (web_search,
browser_search, search_files) when TARS's first read on it misses the mark.
This remembers those rephrasings — if a new query closely matches one the owner
previously reworded, the reworded version is used automatically, so the
first attempt lands more often and the owner has to correct less.

Small, self-contained, and persisted to a plain JSON file in the project
root (same pattern as agents_state.json / proactive_state.json) — no vault,
no logs, nothing personal beyond the search phrasing itself.
"""
import json
import time
from pathlib import Path

SEARCH_SKILLS = {"web_search", "browser_search", "search_files"}
QUERY_ARGS = ("query", "name")  # which arg holds the search text, per skill
MEMORY_FILE = "search_memory.json"
RECENT_WINDOW_SEC = 180  # a follow-up this soon after counts as a refinement
MAX_ENTRIES = 200
# corrections often swap in entirely new words ("that football score" ->
# "Liverpool vs Arsenal score last night"), so word overlap — not character
# similarity — is what tells a related reword apart from a fresh, unrelated
# search right after it
STOPWORDS = {"a", "an", "the", "my", "is", "of", "in", "on", "at", "to",
             "for", "that", "this", "whats", "what's", "what", "me", "and"}


class SearchMemory:
    def __init__(self, base: Path):
        self.path = base / MEMORY_FILE
        self.last_search: tuple[float, str, str] | None = None  # (t, skill, query)
        self._data: dict = self._load()

    def _load(self) -> dict:
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _save(self) -> None:
        try:
            self.path.write_text(json.dumps(self._data, indent=2), encoding="utf-8")
        except Exception:
            pass

    @staticmethod
    def _norm(q: str) -> str:
        return " ".join(q.lower().split())

    @staticmethod
    def _related(a: str, b: str) -> bool:
        """True when a and b share at least one meaningful word — related
        enough that b looks like a reword of a, not a brand new topic."""
        wa = set(a.split()) - STOPWORDS
        wb = set(b.split()) - STOPWORDS
        return bool(wa & wb)

    @staticmethod
    def _query_key(skill: str, args: dict) -> str | None:
        if skill not in SEARCH_SKILLS:
            return None
        for key in QUERY_ARGS:
            if args.get(key):
                return key
        return None

    def refine(self, skill: str, args: dict) -> dict:
        """Before a search runs: if the owner previously reworded a close match
        of this query, use that wording instead of the fresh one."""
        key = self._query_key(skill, args)
        if not key:
            return args
        entry = self._data.get(self._norm(args[key]))
        if entry and entry.get("refined"):
            new_args = dict(args)
            new_args[key] = entry["refined"]
            return new_args
        return args

    def observe(self, skill: str, args: dict) -> None:
        """After a search runs: if it followed a different-but-similar search
        soon after, treat it as the owner refining/correcting his ask, and
        remember the better wording for next time."""
        key = self._query_key(skill, args)
        if not key:
            self.last_search = None
            return
        query = args[key]
        norm = self._norm(query)
        now = time.time()
        if self.last_search:
            t, prev_skill, prev_query = self.last_search
            prev_norm = self._norm(prev_query)
            if (prev_skill == skill and now - t <= RECENT_WINDOW_SEC
                    and prev_norm != norm):
                if self._related(prev_norm, norm):
                    self._data[prev_norm] = {"refined": query, "t": now}
                    if len(self._data) > MAX_ENTRIES:
                        oldest = sorted(self._data,
                                         key=lambda k: self._data[k].get("t", 0)
                                         )[:len(self._data) - MAX_ENTRIES]
                        for k in oldest:
                            del self._data[k]
                    self._save()
        self.last_search = (now, skill, query)
