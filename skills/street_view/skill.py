"""Google Street View panel on the TARS dashboard: 'open street view on the
dashboard', 'show me Times Square in street view', 'close street view'.
Geocodes with OpenStreetMap (free, no key) then points the dashboard's
embedded Street View iframe (Google's key-less 'svembed' trick) at it —
writes street_view_state.json, the dashboard polls it and swaps the map
panel for a live 360 photo."""
import json
import time
from pathlib import Path

import requests

BASE = Path(__file__).resolve().parents[2]
STATE = BASE / "street_view_state.json"
NOMINATIM = "https://nominatim.openstreetmap.org/search"
HEADERS = {"User-Agent": "TARS-home-assistant/1.0 (personal use)"}
HOME = {"active": False, "lat": -31.95, "lon": 115.86, "label": ""}

DESCRIPTION = ("Open, move, or close GOOGLE STREET VIEW on the TARS "
               "dashboard — a street-level 360 photo panel that replaces "
               "the overhead map. E.g. 'open street view on the "
               "dashboard', 'show me street view of the Eiffel Tower', "
               "'close street view'. NOT for the overhead map with pins "
               "(that's map_view) and NOT for maps/directions in the "
               "browser (browser_search).")
ARGS = {"action": "'show' (open street view at a place) or 'close' (hide "
                   "it, back to the normal map)",
        "place": "the address/place to drop into street view, e.g. "
                  "'Eiffel Tower' or 'Times Square New York'"}


def _save(state: dict) -> None:
    state["t"] = time.time()
    STATE.write_text(json.dumps(state), encoding="utf-8")


def _geocode(q: str) -> dict | None:
    r = requests.get(NOMINATIM, params={"format": "json", "q": q, "limit": 1},
                      headers=HEADERS, timeout=15)
    r.raise_for_status()
    hits = r.json()
    return hits[0] if hits else None


def run(args: dict) -> str:
    action = str(args.get("action", "show")).strip().lower()
    place = str(args.get("place", "")).strip()

    if action in ("close", "hide", "off", "stop"):
        _save(dict(HOME))
        return "Closed street view — back to the map."

    if not place:
        return "Tell me a place and I'll drop street view there on the dashboard."

    try:
        hit = _geocode(place)
    except requests.RequestException:
        return "The map service isn't answering right now."

    if not hit:
        return f"I couldn't find {place} to drop into street view."

    _save({"active": True, "lat": float(hit["lat"]), "lon": float(hit["lon"]),
           "label": place.upper()})
    return f"Street view's up on the dashboard, looking at {place}."
