"""Open EA Sports FC 26's Ultimate Team Web App and help the owner jump straight to a
player's transfer-market listing. Deliberately does NOT log in, buy, sell, or predict
prices on the owner's behalf — the FUT Web App requires the owner's own EA login (with 2FA),
and TARS never makes purchases or trades for him. What it CAN do: open the correct
page instantly, and copy a player's name to the clipboard so it's one paste away from
the search bar, saving the owner the typing."""
import re
import webbrowser

import pyperclip

DESCRIPTION = ("Open EA Sports FC 26's Ultimate Team Web App in the browser so the owner can "
               "check the transfer market, and copy a player's name to the clipboard ready "
               "to paste into the search bar. E.g. 'open the FC 26 web app', 'look up Mbappe "
               "on the FUT market', 'check Haaland's price on the web app'. TARS only opens "
               "the page and hands the owner a paste-ready name — logging in, buying, and selling "
               "always stay the owner's own clicks, since TARS never spends money or makes "
               "purchases for him. For 'notify me when to sell', open the page with this "
               "skill first, then say 'watch this and tell me when the price drops' to hand it "
               "to the screen_watch skill.")
ARGS = {"player": "player name to look up on the transfer market, or blank to just open the web app"}

WEB_APP_URL = "https://www.ea.com/ea-sports-fc/ultimate-team/web-app/"

LEAD_PHRASES = re.compile(
    r"^(open|check|look ?up|search for|find|buy|sell|watch)\s+"
    r"(the )?(fc ?26 )?(fut )?(ultimate team )?(web ?app )?(market )?(for |on )?",
    re.IGNORECASE,
)
TRAILERS = re.compile(
    r"\s*(on the (fut )?(market|web ?app)|'s price|price)?\s*$", re.IGNORECASE
)
# words that signal a vague/predictive request ("players expected to go up in price")
# rather than one named player — TARS can't predict FUT market prices, so hand that back.
VAGUE_WORDS = {"players", "expected", "prediction", "predict", "rising", "going", "notify", "sell"}


def run(args: dict) -> str:
    player = (args.get("player") or "").strip()

    if not player:
        try:
            webbrowser.open(WEB_APP_URL)
        except Exception as e:
            return f"I couldn't open the web app: {e}"
        return "Opening the FC 26 Ultimate Team web app now — you'll need to log in yourself."

    cleaned = LEAD_PHRASES.sub("", player).strip()
    cleaned = TRAILERS.sub("", cleaned).strip()
    words = cleaned.lower().split()

    try:
        webbrowser.open(WEB_APP_URL)
    except Exception as e:
        return f"I couldn't open the web app: {e}"

    if not cleaned or any(w in VAGUE_WORDS for w in words) or len(words) > 4:
        return ("Opening the FC 26 web app now. I can't predict market prices or buy and sell "
                "for you — name me one player at a time, like 'look up Mbappe', and I'll get "
                "the name ready to paste into the search bar.")

    try:
        pyperclip.copy(cleaned)
        copied_note = f" and copied \"{cleaned}\" to your clipboard — just paste it into the search bar"
    except Exception:
        copied_note = ""

    return f"Opening the FC 26 web app{copied_note}."
