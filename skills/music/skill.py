"""Music by voice: find and PLAY actual music, not just search for it.
"Play some lo-fi" finds the top YouTube result and opens it directly —
the watch page autoplays. Pause/skip ride the system media keys (same as
the media skill), and "what's playing" reads the player's window title.
"""
import webbrowser

DESCRIPTION = ("PLAY music by voice: 'play some lo-fi beats', 'put on 80s "
               "rock', 'play Bohemian Rhapsody', plus 'what song is this' / "
               "'what's playing'. Finds the music and starts it playing in "
               "the browser. NOT for pausing/skipping an already-playing "
               "track (that's the media skill), NOT for general video "
               "requests like trailers or highlights (that's browser_search), "
               "and NOT for opening/launching an app like Spotify — that's "
               "open_app.")
ARGS = {"query": "what to play, e.g. 'lo-fi beats' or a song/artist name",
        "action": "'play' (default) or 'whats_playing'"}


def _whats_playing() -> str:
    import pygetwindow as gw

    for w in gw.getAllWindows():
        title = (w.title or "").strip()
        if not title:
            continue
        if title.endswith(" - YouTube") and title != "YouTube":
            return f"Playing from YouTube: {title[:-10]}."
        if "spotify" in title.lower() and " - " in title:
            return f"Spotify's playing {title}."
    return "I can't see a music player open right now."


def run(args: dict) -> str:
    action = str(args.get("action") or "play").strip().lower()
    if "playing" in action or "song" in action:
        return _whats_playing()

    query = str(args.get("query") or "").strip()
    if not query:
        return "What do you want to hear?"

    try:
        from ddgs import DDGS

        try:
            hits = list(DDGS().videos(f"{query} music", max_results=8))
        except Exception:
            hits = list(DDGS(verify=False).videos(f"{query} music",
                                                  max_results=8))
        url = next((h.get("content") or h.get("url") or ""
                    for h in hits
                    if "youtube.com/watch" in (h.get("content")
                                               or h.get("url") or "")), "")
    except Exception:
        url = ""

    if not url:
        # graceful fallback: at least land the owner on the results page
        webbrowser.open("https://www.youtube.com/results?search_query="
                        + query.replace(" ", "+"))
        return (f"I couldn't lock onto a track for {query}, so I've opened "
                f"the search results — click the one you fancy.")
    webbrowser.open(url)
    return f"Playing {query}. It's opening in your browser now."
