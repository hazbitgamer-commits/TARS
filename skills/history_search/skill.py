"""Search the owner's own browser history by topic — "what was that site I was
on last night about solar batteries". Reads the browser's own history file
(a copy of it — the real one is locked while the browser runs), so there's
no extension to install and no account to connect."""
import json
import os
import shutil
import sqlite3
import tempfile
import time
from pathlib import Path

BASE = Path(__file__).resolve().parents[2]
LAST = BASE / "history_last.json"

DESCRIPTION = ("Search the owner's BROWSER HISTORY for a page he's already "
               "visited — 'what was that site about solar batteries', 'find "
               "that github page I was on yesterday', 'what was I reading "
               "last night'. Can reopen a result. NOT for searching the web "
               "for new pages (browser_search / web_search) and NOT for "
               "files on the PC (search_files).")
ARGS = {"query": "the topic or site name to look for",
        "when": "optional: 'today', 'yesterday', 'this week'",
        "open": "'true' to open the best match, or a number to open that one"}

# where Chromium browsers keep their history, newest-used first
BROWSERS = [("Brave", "BraveSoftware/Brave-Browser/User Data"),
            ("Chrome", "Google/Chrome/User Data"),
            ("Edge", "Microsoft/Edge/User Data")]

# TARS's own pages and browser plumbing are not "sites the owner visited"
JUNK = ("127.0.0.1:8765", "localhost:8765", "chrome://", "brave://",
        "edge://", "about:blank", "chrome-extension://", "newtab")

WORD_SKIP = {"the", "that", "this", "a", "an", "was", "were", "is", "on",
             "in", "at", "about", "of", "for", "to", "with", "my", "i",
             "site", "page", "website", "thing", "one", "it", "what",
             "which", "and", "or", "from", "some", "any", "looking",
             "reading", "watching", "visited", "yesterday", "today",
             "night", "morning", "week", "last", "back", "again"}


def _chrome_now() -> int:
    """Chromium stores time as microseconds since 1601-01-01."""
    return int((time.time() + 11644473600) * 1_000_000)


def _window(when: str) -> tuple[int, int]:
    """(since, until) in Chromium time. 'Last night' means the evening, not
    the last 48 hours — asking what he watched last night and being told
    about a page from an hour ago is the wrong answer."""
    import datetime

    when = (when or "").strip().lower()
    now = datetime.datetime.now()
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    to_chrome = lambda d: int((d.timestamp() + 11644473600) * 1_000_000)

    if "night" in when or "evening" in when:
        start = midnight - datetime.timedelta(hours=7)  # yesterday 5pm
        end = min(midnight + datetime.timedelta(hours=5), now)
        return to_chrome(start), to_chrome(end)
    if "today" in when or "this morning" in when:
        return to_chrome(midnight), _chrome_now()
    if "yesterday" in when:
        return to_chrome(midnight - datetime.timedelta(days=1)), to_chrome(midnight)
    if "week" in when:
        return to_chrome(midnight - datetime.timedelta(days=7)), _chrome_now()
    if "month" in when:
        return to_chrome(midnight - datetime.timedelta(days=30)), _chrome_now()
    return 0, 0


def _databases() -> list[tuple[str, Path]]:
    """Every Chromium profile's history file, on any OS. This used to read
    %LOCALAPPDATA% only, so on a Mac it silently found nothing."""
    import sys as _sys

    if str(BASE) not in _sys.path:
        _sys.path.insert(0, str(BASE))
    try:
        from platform_caps import browser_data_dirs

        roots = browser_data_dirs()
    except Exception:
        local = os.environ.get("LOCALAPPDATA")
        roots = [Path(local) / rel for _, rel in BROWSERS] if local else []
    out = []
    for root in roots:
        if not root.is_dir():
            continue
        # the folder layout differs per OS, so name the browser from the
        # whole path rather than the last directory ("User Data" on Windows)
        blob = str(root).lower()
        label = ("Brave" if "brave" in blob else "Chrome" if "chrome" in blob
                 else "Edge" if "edge" in blob else "Browser")
        for profile in root.iterdir():
            db = profile / "History"
            if db.is_file():
                out.append((label, db))
    return out


def _rows(db: Path, words: list[str], since: int, until: int = 0) -> list[dict]:
    """The live file is locked by the running browser, so query a copy."""
    tmp = Path(tempfile.gettempdir()) / f"tars_hist_{db.parent.name}.db"
    try:
        shutil.copy2(db, tmp)
    except OSError:
        return []
    # short words match TITLES only — "fc" and "26" appear inside random
    # query strings in URLs and dragged in Google sign-in pages
    clauses, params = [], []
    for w in words:
        if len(w) >= 3:
            clauses.append("(lower(title) LIKE ? OR lower(url) LIKE ?)")
            params += [f"%{w}%", f"%{w}%"]
        else:
            clauses.append("lower(title) LIKE ?")
            params.append(f"%{w}%")
    where = " AND ".join(clauses) or "1=1"
    sql = ("SELECT url, title, visit_count, last_visit_time FROM urls "
           f"WHERE {where}")
    if since:
        sql += " AND last_visit_time > ?"
        params.append(since)
    if until:
        sql += " AND last_visit_time < ?"
        params.append(until)
    sql += " ORDER BY last_visit_time DESC LIMIT 60"
    try:
        con = sqlite3.connect(f"file:{tmp}?mode=ro", uri=True)
        rows = con.execute(sql, params).fetchall()
        con.close()
    except sqlite3.Error:
        return []
    finally:
        try:
            tmp.unlink()
        except OSError:
            pass
    return [{"url": r[0], "title": r[1] or r[0], "visits": r[2], "t": r[3]}
            for r in rows if not any(j in (r[0] or "").lower() for j in JUNK)]


def _ago(chrome_t: int) -> str:
    seconds = time.time() - (chrome_t / 1_000_000 - 11644473600)
    if seconds < 3600:
        return "less than an hour ago"
    if seconds < 86_400:
        return f"{int(seconds // 3600)} hours ago"
    days = int(seconds // 86_400)
    return "yesterday" if days == 1 else f"{days} days ago"


def _domain(url: str) -> str:
    return url.split("//")[-1].split("/")[0].replace("www.", "")


def _words(query: str) -> list[str]:
    tokens = [w.strip(".,?!'\"") for w in query.lower().replace("'s", "").split()]
    words = [w for w in tokens if len(w) > 2 and w not in WORD_SKIP]
    if not words:  # short but real: "fc 26", "ea", "x"
        words = [w for w in tokens if len(w) >= 2 and w not in WORD_SKIP]
    return words


def _search(query: str, when: str = "") -> list[dict]:
    words = _words(query)
    since, until = _window(when or query)
    # "what was I watching last night" names no topic — that's not a failed
    # search, it's a request to browse that stretch of the evening
    if not words and not since:
        return []
    hits: dict[str, dict] = {}
    for label, db in _databases():
        for row in _rows(db, words, since, until):
            row["browser"] = label
            best = hits.get(row["url"])
            if not best or row["t"] > best["t"]:
                hits[row["url"]] = row
    found = sorted(hits.values(), key=lambda r: (-r["t"], -r["visits"]))
    # one entry per site: 14 YouTube pages is not 14 answers
    seen, unique = set(), []
    for row in found:
        key = (_domain(row["url"]), row["title"][:40].lower())
        if key in seen:
            continue
        seen.add(key)
        unique.append(row)
    return unique[:8]


def run(args: dict) -> str:
    import webbrowser

    query = str(args.get("query") or "").strip()
    want_open = str(args.get("open") or "").strip().lower()

    # "open the second one" — the results are still on the clipboard of his mind
    if want_open and not query:
        try:
            saved = json.loads(LAST.read_text(encoding="utf-8"))["results"]
        except (OSError, json.JSONDecodeError, KeyError):
            return "I've not looked anything up yet."
        index = {"first": 0, "second": 1, "third": 2, "1": 0, "2": 1,
                 "3": 2, "true": 0, "yes": 0}.get(want_open, 0)
        if index >= len(saved):
            return f"There were only {len(saved)}."
        webbrowser.open(saved[index]["url"])
        return f"Opening {saved[index]['title'][:60]}."

    if not query:
        return "Search your history for what?"
    results = _search(query, str(args.get("when") or ""))
    if not results:
        when = str(args.get("when") or "").strip()
        if not _words(query):  # he asked about a time, not a topic
            return (f"Nothing in your history from {when or 'then'} — you "
                    f"weren't browsing.")
        return (f"Nothing in your browser history matches {query}. It only "
                f"goes back as far as the browser keeps it.")
    try:
        LAST.write_text(json.dumps({"query": query, "results": results[:5]}),
                        encoding="utf-8")
    except OSError:
        pass
    if want_open in ("true", "yes", "1", "first"):
        webbrowser.open(results[0]["url"])
        return (f"Opening {results[0]['title'][:70]} — {_domain(results[0]['url'])}, "
                f"visited {_ago(results[0]['t'])}.")
    parts = [f"{r['title'][:60]} on {_domain(r['url'])}, {_ago(r['t'])}"
             for r in results[:3]]
    tail = (" Say open the first one and I'll bring it up."
            if len(parts) > 1 else " Say open it and I'll bring it up.")
    return f"From your history: " + ". ".join(parts) + "." + tail
