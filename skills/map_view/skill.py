"""The dashboard's living map: 'show London on the map', 'find hotels in
Subiaco on the map', 'zoom in', 'map home'. Geocodes with OpenStreetMap
(free, no key), writes map_state.json — the dashboard's map flies there
with markers, fully animated."""
import json
import time
from pathlib import Path

import requests

BASE = Path(__file__).resolve().parents[2]
STATE = BASE / "map_state.json"
HOME = {"center": [-31.95, 115.86], "zoom": 11, "label": "PERTH — HOME",
        "markers": []}
NOMINATIM = "https://nominatim.openstreetmap.org/search"
HEADERS = {"User-Agent": "TARS-home-assistant/1.0 (personal use)"}

DESCRIPTION = ("Control the MAP on the TARS dashboard — 'show London on the "
               "map', 'take the map to Tokyo', 'find hotels in Subiaco on "
               "the map' (drops markers), 'zoom in', 'zoom out', 'map "
               "home'. The dashboard map flies there, animated. NOT for "
               "directions in the browser (browser_search kind map).")
ARGS = {"action": "'go' (a place), 'find' (things in a place), 'zoom', 'home'",
        "place": "the town/city/area, e.g. 'London' or 'Subiaco'",
        "query": "for find: what to look for, e.g. 'hotels', 'cafes'",
        "direction": "for zoom: 'in' or 'out'"}


def _load() -> dict:
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return dict(HOME)


def _save(state: dict) -> None:
    state["t"] = time.time()
    STATE.write_text(json.dumps(state), encoding="utf-8")


def _search(q: str, limit: int = 8) -> list[dict]:
    r = requests.get(NOMINATIM, params={"format": "json", "q": q,
                                        "limit": limit}, headers=HEADERS,
                     timeout=15)
    r.raise_for_status()
    return r.json()


def run(args: dict) -> str:
    action = str(args.get("action", "go")).strip().lower()
    place = str(args.get("place", "")).strip()
    query = str(args.get("query", "")).strip()

    if action == "home" or (action == "go" and place.lower() in ("home", "perth", "")):
        _save(dict(HOME))
        return "Map's back home over Perth."

    if action == "zoom":
        state = _load()
        step = 2 if "in" in str(args.get("direction", "in")).lower() else -2
        state["zoom"] = max(2, min(18, int(state.get("zoom", 11)) + step))
        _save(state)
        return f"Zoomed {'in' if step > 0 else 'out'}."

    try:
        if action == "find" and query:
            where = place or _load().get("label", "Perth")
            hits = _search(f"{query} in {where}")
            if not hits:
                return f"The map found no {query} around {where}."
            markers = [{"lat": float(h["lat"]), "lon": float(h["lon"]),
                        "name": h.get("display_name", query).split(",")[0][:60]}
                       for h in hits]
            _save({"center": [markers[0]["lat"], markers[0]["lon"]],
                   "zoom": 14, "label": f"{query.upper()} — {where.upper()}",
                   "markers": markers})
            return (f"Found {len(markers)} {query} around {where} — "
                    f"they're on the map now.")
        # plain go
        hits = _search(place or query)
        if not hits:
            return f"The map can't find {place or query}."
        h = hits[0]
        _save({"center": [float(h["lat"]), float(h["lon"])], "zoom": 12,
               "label": (place or query).upper(), "markers": []})
        return f"Map's flying to {place or query}."
    except requests.RequestException:
        return "The map service isn't answering right now."
