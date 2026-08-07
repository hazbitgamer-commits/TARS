"""Live solar readings from Jacob's SolaX inverter (cloud realtime API —
the same data his solar monitoring app uses; token/serial in .env)."""
import os
import sys
from pathlib import Path

import requests

BASE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BASE))

DESCRIPTION = ("Jacob's SOLAR PANELS, live — 'how much power am I making', "
               "'solar update', 'how much has the solar made today', 'am I "
               "exporting to the grid'. Reads the real SolaX inverter. NOT "
               "for the weather (weather skill).")
ARGS = {"metric": "'now' for current output (default), 'today' for today's "
                   "total, 'grid' for import/export"}

API = "https://global.solaxcloud.com/proxyApp/proxy/api/getRealtimeInfo.do"


def _fetch():
    from dotenv import load_dotenv

    load_dotenv(BASE / ".env")
    token = os.getenv("SOLAX_API_TOKEN", "").strip()
    sn = os.getenv("SOLAX_SN", "").strip()
    if not token or not sn:
        return None, "My solar login isn't set up yet — ask Claude to add it."
    try:
        r = requests.get(API, params={"tokenId": token, "sn": sn}, timeout=15)
        r.raise_for_status()
        data = r.json()
        if not data.get("success"):
            reason = str(data.get("exception", "no reason given"))
            if "token" in reason.lower():
                return None, ("My solar login has expired — grab a fresh "
                              "API token from the SolaxCloud site and ask "
                              "Claude to update it for me.")
            return None, f"The solar cloud said no — {reason}."
        return data.get("result") or {}, None
    except requests.RequestException:
        return None, "I couldn't reach the solar cloud right now."


def run(args: dict) -> str:
    metric = str(args.get("metric", "now")).strip().lower()
    result, err = _fetch()
    if err:
        return err

    ac = result.get("acpower") or 0            # W right now
    today = result.get("yieldtoday") or 0      # kWh today
    feedin = result.get("feedinpower") or 0    # W to grid (+) / from grid (-)

    if "today" in metric or "total" in metric:
        return (f"The panels have made {today:.1f} kilowatt hours today"
                + (f", and they're doing {ac/1000:.1f} kilowatts right now."
                   if ac else ", and they've wound down for the day."))
    if "grid" in metric or "export" in metric or "import" in metric:
        if feedin > 50:
            return f"You're exporting {feedin/1000:.1f} kilowatts to the grid right now."
        if feedin < -50:
            return f"You're drawing {abs(feedin)/1000:.1f} kilowatts from the grid right now."
        return "You're roughly balanced with the grid right now."
    if ac < 20:
        return (f"The panels are asleep right now — but they made "
                f"{today:.1f} kilowatt hours today.")
    direction = (f", exporting {feedin/1000:.1f} of it" if feedin > 50 else "")
    return (f"Making {ac/1000:.1f} kilowatts right now{direction} — "
            f"{today:.1f} kilowatt hours so far today.")
