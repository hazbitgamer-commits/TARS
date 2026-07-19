"""Navigate straight to a specific website in the default browser — no search
results page in between, just go there. Fills the gap between browser_search
(runs a search query) and open_app (launches installed programs/folders)."""
import re
import webbrowser

DESCRIPTION = ("Go directly to a specific website or web address in the browser, "
               "skipping any search results page. E.g. 'navigate to it', 'go to "
               "github dot com', 'take me straight to reddit'. NOT for running a "
               "search query (use browser_search) and NOT for installed apps or "
               "folders (use open_app).")
ARGS = {"address": "the website name or URL to go to, e.g. 'youtube.com', 'github', 'https://reddit.com'"}

SITE_WORDS = {" dot co dot uk": ".co.uk", " dot com": ".com", " dot net": ".net",
              " dot org": ".org", " dot io": ".io", " dot au": ".au", " dot tv": ".tv"}

# common sites Jacob is likely to say by bare name, mapped to their real address
KNOWN_SITES = {
    "youtube": "youtube.com", "google": "google.com", "github": "github.com",
    "reddit": "reddit.com", "amazon": "amazon.com", "wikipedia": "wikipedia.org",
    "gmail": "mail.google.com", "email": "mail.google.com", "netflix": "netflix.com",
    "twitter": "twitter.com", "x": "x.com", "facebook": "facebook.com",
    "instagram": "instagram.com", "twitch": "twitch.tv", "spotify": "open.spotify.com",
    "steam": "store.steampowered.com", "discord": "discord.com",
}

LEAD_PHRASES = re.compile(
    r"^(go to|navigate to|take me to|take me directly to|open)\s+", re.IGNORECASE
)


def run(args: dict) -> str:
    address = (args.get("address") or "").strip().lower()
    if not address:
        return "Navigate to what, exactly?"

    for spoken, real in SITE_WORDS.items():
        address = address.replace(spoken, real)
    address = LEAD_PHRASES.sub("", address).strip()
    address = address.replace("the website ", "").replace("www.", "").strip()

    if address in KNOWN_SITES:
        address = KNOWN_SITES[address]
    elif " " in address or "." not in address:
        # a bare name like "reddit" or "my bank" — best guess is a dot-com
        address = address.replace(" ", "") + ".com"

    url = address if address.startswith(("http://", "https://")) else "https://" + address
    try:
        webbrowser.open(url)
    except Exception as e:
        return f"I couldn't open that: {e}"
    return f"Navigating to {address} now."
