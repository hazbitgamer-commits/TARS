"""Look up the real-world address of a place, business, or landmark by
name — spoken back to Jacob. Uses OpenStreetMap's free Nominatim geocoder
(no key, no cost), the same service map_view already uses to place map
markers. This skill just reads the address out loud instead of drawing it
on the dashboard map."""
import requests

NOMINATIM = "https://nominatim.openstreetmap.org/search"
HEADERS = {"User-Agent": "TARS-home-assistant/1.0 (personal use)"}

DESCRIPTION = ("Find and speak the real street/postal address of a place, "
               "business, or landmark by name. E.g. 'find the address of "
               "the Eiffel Tower', 'what's the address of Woolworths "
               "Claremont'. NOT for showing a location on the dashboard map "
               "(that's map_view) and NOT for general web searches "
               "(web_search).")
ARGS = {"query": "the place, business, or landmark name to find the address for"}


def run(args: dict) -> str:
    query = str(args.get("query", "")).strip()
    if not query:
        return "I need a place or business name to look up an address for."

    try:
        r = requests.get(
            NOMINATIM,
            params={"format": "json", "q": query, "limit": 1, "addressdetails": 1},
            headers=HEADERS,
            timeout=15,
        )
        r.raise_for_status()
        hits = r.json()
    except requests.RequestException:
        return "The address lookup service isn't answering right now."

    if not hits:
        return f"I couldn't find an address for {query}."

    address = hits[0].get("display_name", "").strip()
    if not address:
        return f"I couldn't find an address for {query}."

    return f"The address for {query} is {address}."
