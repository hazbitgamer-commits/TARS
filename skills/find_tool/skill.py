"""Search the open-source world instead of reinventing it — GitHub repos
and PyPI packages. Jacob's idea (2026-08-08): "instead of making a new
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
# (Jacob heard "the Python package the" read aloud) — never probe filler
FILLER = {"find", "the", "a", "an", "please", "open", "search", "look",
          "for", "me", "my", "some", "any", "tool", "tools", "library",
          "libraries", "package", "packages", "repo", "repos", "repository",
          "github", "that", "this", "with", "and", "get", "use", "using",
          "called", "named", "app", "program", "thing", "stuff", "can",
          "you", "there", "is", "are", "it"}


def _pypi(query: str, limit: int = 3) -> list[dict]:
    """PyPI has no search API anymore — probe exact/obvious names."""
    out = []
    words = [w for w in query.lower().split() if len(w) > 2 and w not in FILLER]
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

    q = re.sub(r"^\W*(hey tars[,.! ]*)?(can you |could you |please |just )*"
               r"(find|search|look ?up|look for|get|show me|see if there'?s?)?"
               r"\s*(me\s+)?(the|a|an|any)?\s*"
               r"(github\s+)?(repo(sitory)?|project|package|library|tool)?s?"
               r"\s*(on github|in github|from github|on pypi)?\s*"
               r"(called|named|for|that|to)?\s*", "", query.strip(), flags=re.I)
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
                keys = [w for w in query.lower().split() if w not in FILLER]
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
    for pkg in found["pypi"][:2]:
        parts.append(f"the Python package {pkg['name']}"
                     + (f", {pkg['desc']}" if pkg["desc"] else ""))
    return (f"For {query}: " + ". ".join(parts)
            + ". Say teach yourself to use one of those if you want it built in.")
