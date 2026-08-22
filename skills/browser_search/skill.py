import urllib.parse
import webbrowser

DESCRIPTION = ("Show something in the browser: a web search, a map, or VIDEOS "
               "(highlights, trailers, music, clips — opens YouTube results). Use when "
               "the owner wants it ON SCREEN (web_search is for spoken answers). E.g. "
               "'find FC Magdeburg highlights', 'open a map of England'.")
ARGS = {"query": "what to look up",
        "kind": "'video' for highlights/clips/trailers/music, 'map' for maps, else 'search'"}


def run(args: dict) -> str:
    query = (args.get("query") or "").strip()
    if not query:
        return "Look up what, exactly?"
    kind = (args.get("kind") or "search").strip().lower()
    lowered = query.lower()
    if lowered.startswith("map of "):
        kind, query = "map", query[7:]
    # "download me a VPN" / "now download one of them". The router already
    # understands this is a download, and the skill used to ignore that and
    # run a plain search — so the same "Searching for..." line came back
    # twice to two different questions, which reads as not listening.
    #
    # TARS opens the page. It does NOT fetch and run an installer: putting
    # software on his PC off a search result is his decision to make, not
    # something to do quietly on his behalf.
    if kind == "download" or any(w in lowered for w in
                                 ("download", "install", "get me the app")):
        webbrowser.open("https://www.google.com/search?q="
                        + urllib.parse.quote(query + " download"))
        return (f"I've opened the download page for {query}. I won't install "
                f"it myself though — grab the installer and run it, and I'll "
                f"help you set it up after.")
    if kind == "map":
        webbrowser.open("https://www.google.com/maps/search/" + urllib.parse.quote(query))
        return f"Bringing up a map of {query}."
    if kind == "video" or any(w in lowered for w in ("highlights", "trailer", "music video")):
        webbrowser.open("https://www.youtube.com/results?search_query="
                        + urllib.parse.quote(query))
        return f"Pulling up videos of {query} — take your pick."
    webbrowser.open("https://www.google.com/search?q=" + urllib.parse.quote(query))
    return f"Searching for {query} in your browser."
