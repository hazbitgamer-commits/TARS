"""Search the open-source world instead of reinventing it — GitHub repos
and PyPI packages. the owner's idea (2026-08-08): "instead of making a new
skill every time, can he search GitHub". Used by voice AND read by the
self-teaching pipeline, which now looks for an existing library before
writing anything from scratch."""
import requests

DESCRIPTION = ("SEARCH the open-source world for existing tools — 'search "
               "GitHub for a subtitle downloader', 'is there a library for "
               "reading PDFs', 'find me a tool that converts images'. "
               "Returns the top real projects with stars and one-line "
               "descriptions. NOT for general web answers (web_search) and "
               "NOT for uploading TARS's own code (github_publish).")
ARGS = {"query": "what the tool should do, in a few words",
        "where": "'both' (default), 'github', or 'pypi'"}

HEADERS = {"User-Agent": "TARS-home-assistant", "Accept": "application/vnd.github+json"}


def _github(query: str, limit: int = 4) -> list[dict]:
    r = requests.get("https://api.github.com/search/repositories",
                     params={"q": query, "sort": "stars", "per_page": limit},
                     headers=HEADERS, timeout=20)
    r.raise_for_status()
    return [{"name": i["full_name"], "stars": i["stargazers_count"],
             "desc": (i.get("description") or "")[:110],
             "lang": i.get("language") or "?", "url": i["html_url"]}
            for i in r.json().get("items", [])[:limit]]


# probing PyPI for words like "find"/"the"/"open" returns absurd packages
# (the owner heard "the Python package the" read aloud) — never probe filler
FILLER = {"find", "the", "a", "an", "please", "open", "search", "look",
          "for", "me", "my", "some", "any", "tool", "tools", "library",
          "libraries", "package", "packages", "repo", "repos", "repository",
          "github", "that", "this", "with", "and", "get", "use", "using",
          "called", "named", "app", "program", "thing", "stuff", "can",
          "you", "there", "is", "are", "it",
          # 2026-08-09: a long request ("i want you to search through github
          # repo's to find what may help you answer faster") kept its own
          # framing words, so the top THREE became the query — GitHub was
          # searched for "i want to" and returned the most-starred repos
          # whose descriptions happen to say "want". None were relevant.
          "i", "im", "id", "ive", "want", "wants", "wanted", "wanna", "need",
          "needs", "needed", "like", "help", "helps", "may", "might", "must",
          "would", "could", "should", "will", "shall", "to", "into", "in",
          "on", "of", "or", "so", "if", "do", "does", "did", "be", "been",
          "am", "was", "were", "your", "yours", "yourself", "we", "us", "our",
          "what", "whats", "which", "who", "how", "why", "when", "where",
          "through", "without", "about", "from", "make", "makes", "made",
          "give", "gives", "want", "something", "anything", "everything",
          "way", "ways", "good", "better", "best", "more", "most", "much",
          "one", "ones", "out", "up", "at", "by", "as", "but", "not", "no",
          "then", "than", "them", "they", "he", "she", "his", "her"}


def _keys(query: str) -> list[str]:
    """The words that actually name a subject — no pronouns, no verbs of
    asking. Length filter too: 'i' and 'to' are never a search term."""
    import re

    return [w for w in re.findall(r"[a-z0-9+.#][a-z0-9+.#-]{2,}", query.lower())
            if w not in FILLER]


def _relevant(repo: dict, keys: list[str]) -> bool:
    """Does this result have anything to do with what was asked? A repo that
    merely shares the word 'want' with the sentence does not."""
    blob = (repo.get("name", "") + " " + repo.get("desc", "")).lower()
    return any(k in blob for k in keys if len(k) >= 4)


def _pypi(query: str, limit: int = 3) -> list[dict]:
    """PyPI has no search API anymore — probe exact/obvious names."""
    out = []
    words = [w for w in _keys(query) if len(w) > 3]
    if not words:
        return []
    candidates = ["-".join(words[:2]), "".join(words[:2])] + words[:2]
    for name in dict.fromkeys(candidates):
        try:
            r = requests.get(f"https://pypi.org/pypi/{name}/json", timeout=10)
            if r.status_code == 200:
                info = r.json()["info"]
                out.append({"name": info["name"],
                            "desc": (info.get("summary") or "")[:110]})
        except requests.RequestException:
            continue
        if len(out) >= limit:
            break
    return out


def _clean(query: str) -> str:
    """Strip the asking-words so GitHub gets the SUBJECT, not the sentence
    ('find the github repo called LittleBigMouse' → 'LittleBigMouse')."""
    import re

    # Every optional word must be followed by WHITESPACE. The old bare
    # (the|a|an|any)? ate the "a" of "answer" and searched for "nswer" —
    # the same trap as the trailing-\b bugs elsewhere in TARS.
    # "I want you to search through GitHub to find X" — first-person framing
    # the old opener-stripper never saw, so the whole sentence became the query
    q = re.sub(r"^\W*(?:hey tars[,.!\s]*)?"
               r"(?:(?:i'?m|i'?d|i)\s+)?"
               r"(?:(?:want|need|would\s+like|like)\s+)?"
               r"(?:(?:you|u)\s+)?(?:to\s+)?(?:go\s+)?(?:and\s+)?"
               r"(?:have\s+a\s+)?(?:(?:search|look|scan|dig|check)\s+)?"
               r"(?:(?:through|around|into|in|on)\s+)?"
               r"(?:(?:github|the\s+internet|online)\s*)?"
               r"[,.\s]*(?:repo(?:sitory)?s?'?s?\s+)?(?:to\s+)?"
               r"(?:(?:find|see|check|discover)\s+)?"
               r"(?:(?:what|which|if|whether|any)\s+)?"
               r"(?:(?:may|might|could|would|will)\s+)?(?:(?:help|helps)\s+)?"
               r"(?:(?:you|him|it)\s+)?", "", query.strip(), flags=re.I)
    q = re.sub(r"^\W*(?:(?:can|could)\s+you\s+|please\s+|just\s+)*"
               r"(?:(?:find|search|look\s?up|look\s+for|get|show\s+me|"
               r"see\s+if\s+there'?s?)\s+)?"
               r"(?:me\s+)?(?:(?:the|a|an|any)\s+)?(?:github\s+)?"
               r"(?:(?:repo(?:sitory)?|project|package|library|tool)s?\s+)?"
               r"(?:(?:on|in|from)\s+github\s+|on\s+pypi\s+)?"
               r"(?:(?:called|named|for|that|to)\s+)?", "", q, flags=re.I)
    q = re.sub(r"\b(please|for me|on github|thanks)\b", "", q, flags=re.I)
    return q.strip(" .,?!") or query.strip()


def search(query: str, where: str = "both") -> dict:
    """Shared entry point — the learning pipeline calls this too."""
    query = _clean(query)
    result = {"github": [], "pypi": [], "query": query}
    if where in ("both", "github"):
        try:
            result["github"] = _github(query)
            import re as _re

            if not result["github"] and " " not in query:
                # a name that isn't exact ("LittleBigMouse4Me") — try the
                # stem before trailing digits/suffixes
                stem = _re.sub(r"[\d_\-]*\d\w*$|4me$", "", query, flags=_re.I)
                if len(stem) > 3 and stem != query:
                    result["github"] = _github(stem)
            if len(query.split()) > 2 and (
                    not result["github"]
                    or max(r["stars"] for r in result["github"]) < 400):
                # a wordy phrase drowns GitHub's matcher — retry on the
                # distinctive keywords only
                keys = _keys(query)
                if keys and " ".join(keys[:3]) != query.lower():
                    better = _github(" ".join(keys[:3]))
                    if better and (not result["github"] or
                                   max(r["stars"] for r in better) >
                                   max(r["stars"] for r in result["github"])):
                        result["github"] = better
            # an exact/near name match belongs first ("LittleBigMouse")
            key = query.lower().replace(" ", "").replace("-", "")
            result["github"].sort(
                key=lambda r: (key not in r["name"].lower().replace("-", ""),
                               -r["stars"]))
        except requests.RequestException:
            pass
    if where in ("both", "pypi"):
        result["pypi"] = _pypi(query)
    return result


def run(args: dict) -> str:
    query = str(args.get("query") or "").strip()
    if not query:
        return "Search for what sort of tool?"
    found = search(query, str(args.get("where") or "both").lower())
    query = found.get("query") or query
    if not found["github"] and not found["pypi"]:
        return f"I found no open-source projects for {query}."
    # a named-repo hunt: answer with THAT repo, not a survey
    key = query.lower().replace(" ", "").replace("-", "")
    exact = next((r for r in found["github"]
                  if key and key in r["name"].lower().replace("-", "")), None)
    # THE KEYWORD-SOUP GUARD. GitHub answers any sentence with its most
    # starred loose match, so a vague ask ("what would make you faster")
    # came back as a JavaScript link list and a Neovim helper — all three
    # shared only the word "want" with the owner's request. A result that
    # matches nothing meaningful is not an answer.
    keys = _keys(query)
    if len(query.split()) > 2 and keys and not exact:
        kept = [r for r in found["github"] if _relevant(r, keys)]
        if not kept:
            searched = " ".join(keys[:3])
            return (f"Nothing real came back for that. I searched GitHub for "
                    f"'{searched}' and the top hits only share a word with "
                    f"your sentence — none of them actually do it. Try "
                    f"naming the job, like 'a library that reads PDFs'.")
        found["github"] = kept
    if exact and len(query.split()) <= 3:
        stars = (f"{exact['stars'] / 1000:.1f} thousand"
                 if exact["stars"] >= 1000 else str(exact["stars"]))
        return (f"Found it: {exact['name']} — {stars} stars, "
                f"{exact['lang']}"
                + (f". {exact['desc']}" if exact["desc"] else "")
                + ". Say open it in the browser, or teach yourself to use it.")
    parts = []
    for repo in found["github"][:3]:
        stars = (f"{repo['stars'] / 1000:.1f} thousand" if repo["stars"] >= 1000
                 else str(repo["stars"]))
        parts.append(f"{repo['name'].split('/')[-1]} — {stars} stars, "
                     f"{repo['lang']}" + (f": {repo['desc']}" if repo["desc"] else ""))
    pypi = [p for p in found["pypi"]
            if not keys or len(query.split()) <= 2 or _relevant(p, keys)]
    for pkg in pypi[:2]:
        parts.append(f"the Python package {pkg['name']}"
                     + (f", {pkg['desc']}" if pkg["desc"] else ""))
    return (f"For {query}: " + ". ".join(parts)
            + ". Say teach yourself to use one of those if you want it built in.")
