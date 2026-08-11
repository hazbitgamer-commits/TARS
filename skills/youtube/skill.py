"""Open YouTube in the default web browser, and search it if the owner gave a topic."""
import urllib.parse
import webbrowser

DESCRIPTION = ("Go straight to YouTube: open the YouTube homepage, or open YouTube "
               "search results for a video/topic/channel. E.g. 'to YouTube', 'go to "
               "YouTube', 'open YouTube', 'YouTube cat videos', 'find the MrBeast "
               "channel on YouTube'. NOT for general web searches or other websites "
               "(use browser_search or navigate_to for those).")
ARGS = {"query": "what to search for on YouTube (a video topic, song, or channel name), "
                 "or blank/empty to just open the YouTube homepage"}


def run(args: dict) -> str:
    query = str(args.get("query", "")).strip()
    try:
        if not query:
            webbrowser.open("https://www.youtube.com")
            return "Opening YouTube."
        url = "https://www.youtube.com/results?search_query=" + urllib.parse.quote(query)
        webbrowser.open(url)
        return f"Opening YouTube and searching for {query}."
    except Exception as e:
        return f"I couldn't open YouTube: {e}"
