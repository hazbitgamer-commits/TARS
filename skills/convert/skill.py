"""Units, money and world time — the quick lookups, done offline where possible."""
import datetime
import re
import zoneinfo

import requests

DESCRIPTION = ("CONVERT units, money or time zones — 'how many kilometres in 5 miles', "
               "'convert 200 grams to ounces', 'what is 50 US dollars in Aussie "
               "dollars', 'what time is it in London'. Straight conversions, no web "
               "search.")
ARGS = {"query": "the whole conversion in the owner's words"}

# everything to a base unit (metre, gram, litre, km/h, KB) and back out again
UNITS = {
    "mm": ("len", 0.001), "millimetre": ("len", 0.001), "millimeter": ("len", 0.001),
    "cm": ("len", 0.01), "centimetre": ("len", 0.01), "centimeter": ("len", 0.01),
    "m": ("len", 1.0), "metre": ("len", 1.0), "meter": ("len", 1.0),
    "metres": ("len", 1.0), "meters": ("len", 1.0),
    "km": ("len", 1000.0), "kilometre": ("len", 1000.0), "kilometer": ("len", 1000.0),
    "kilometres": ("len", 1000.0), "kilometers": ("len", 1000.0),
    "in": ("len", 0.0254), "inch": ("len", 0.0254), "inches": ("len", 0.0254),
    "ft": ("len", 0.3048), "foot": ("len", 0.3048), "feet": ("len", 0.3048),
    "yd": ("len", 0.9144), "yard": ("len", 0.9144), "yards": ("len", 0.9144),
    "mi": ("len", 1609.344), "mile": ("len", 1609.344), "miles": ("len", 1609.344),
    "g": ("mass", 1.0), "gram": ("mass", 1.0), "grams": ("mass", 1.0),
    "kg": ("mass", 1000.0), "kilo": ("mass", 1000.0), "kilos": ("mass", 1000.0),
    "kilogram": ("mass", 1000.0), "kilograms": ("mass", 1000.0),
    "mg": ("mass", 0.001), "milligram": ("mass", 0.001),
    "oz": ("mass", 28.3495), "ounce": ("mass", 28.3495), "ounces": ("mass", 28.3495),
    "lb": ("mass", 453.592), "lbs": ("mass", 453.592), "pound": ("mass", 453.592),
    "pounds": ("mass", 453.592),
    "st": ("mass", 6350.29), "stone": ("mass", 6350.29),
    "ml": ("vol", 0.001), "millilitre": ("vol", 0.001), "milliliter": ("vol", 0.001),
    "l": ("vol", 1.0), "litre": ("vol", 1.0), "liter": ("vol", 1.0),
    "litres": ("vol", 1.0), "liters": ("vol", 1.0),
    "cup": ("vol", 0.25), "cups": ("vol", 0.25),
    "pint": ("vol", 0.568), "pints": ("vol", 0.568),
    "gallon": ("vol", 3.785), "gallons": ("vol", 3.785),
    "kmh": ("speed", 1.0), "kph": ("speed", 1.0),
    "mph": ("speed", 1.60934), "knot": ("speed", 1.852), "knots": ("speed", 1.852),
    "kb": ("data", 1.0), "mb": ("data", 1024.0), "gb": ("data", 1048576.0),
    "tb": ("data", 1073741824.0),
}
PLACES = {"london": "Europe/London", "uk": "Europe/London", "england": "Europe/London",
          "new york": "America/New_York", "nyc": "America/New_York",
          "los angeles": "America/Los_Angeles", "california": "America/Los_Angeles",
          "tokyo": "Asia/Tokyo", "japan": "Asia/Tokyo", "sydney": "Australia/Sydney",
          "melbourne": "Australia/Melbourne", "brisbane": "Australia/Brisbane",
          "adelaide": "Australia/Adelaide", "darwin": "Australia/Darwin",
          "perth": "Australia/Perth", "singapore": "Asia/Singapore",
          "dubai": "Asia/Dubai", "paris": "Europe/Paris", "berlin": "Europe/Berlin",
          "germany": "Europe/Berlin", "india": "Asia/Kolkata", "china": "Asia/Shanghai",
          "new zealand": "Pacific/Auckland", "auckland": "Pacific/Auckland",
          "toronto": "America/Toronto", "chicago": "America/Chicago",
          "bali": "Asia/Makassar", "thailand": "Asia/Bangkok"}
MONEY = {"usd": "USD", "us dollar": "USD", "american dollar": "USD",
         "aud": "AUD", "aussie dollar": "AUD", "australian dollar": "AUD",
         "eur": "EUR", "euro": "EUR", "euros": "EUR",
         "gbp": "GBP", "british pound": "GBP", "pound sterling": "GBP", "quid": "GBP",
         "jpy": "JPY", "yen": "JPY", "nzd": "NZD", "kiwi dollar": "NZD",
         "cad": "CAD", "canadian dollar": "CAD", "inr": "INR", "rupee": "INR",
         "cny": "CNY", "yuan": "CNY", "thb": "THB", "baht": "THB",
         "idr": "IDR", "rupiah": "IDR", "sgd": "SGD", "singapore dollar": "SGD"}


def _say(n: float) -> str:
    if abs(n) >= 100:
        return f"{n:,.0f}"
    return f"{n:.2f}".rstrip("0").rstrip(".")


def _temperature(q: str):
    m = re.search(r"(-?\d+(?:\.\d+)?)\s*(?:degrees?\s*)?(c|celsius|f|fahrenheit)\b", q)
    if not m:
        return None
    value, unit = float(m.group(1)), m.group(2)[0]
    rest = q[m.end():]
    if unit == "c" and re.search(r"\b(f|fahrenheit)\b", rest):
        return f"{_say(value)} degrees Celsius is {_say(value * 9 / 5 + 32)} Fahrenheit."
    if unit == "f" and re.search(r"\b(c|celsius)\b", rest):
        return f"{_say(value)} Fahrenheit is {_say((value - 32) * 5 / 9)} degrees Celsius."
    return None


def _money(q: str):
    hits = sorted((q.find(word), code) for word, code in MONEY.items() if word in q)
    codes = []
    for _, code in hits:
        if code not in codes:
            codes.append(code)
    if len(codes) < 2:
        return None
    m = re.search(r"(\d+(?:\.\d+)?)", q)
    if not m:
        return None
    amount, src, dst = float(m.group(1)), codes[0], codes[1]
    try:
        r = requests.get("https://api.frankfurter.app/latest",
                         params={"amount": amount, "from": src, "to": dst}, timeout=12)
        rate = r.json()["rates"][dst]
    except Exception:
        return "I couldn't reach the exchange rates just now."
    return f"{_say(amount)} {src} is about {_say(rate)} {dst}."


def _timezone(q: str):
    if "time" not in q:
        return None
    for place, zone in sorted(PLACES.items(), key=lambda kv: -len(kv[0])):
        if place in q:
            now = datetime.datetime.now(zoneinfo.ZoneInfo(zone))
            here = datetime.datetime.now().astimezone()
            gap = round((now.utcoffset() - here.utcoffset()).total_seconds() / 3600, 1)
            unit = "hour" if abs(gap) == 1 else "hours"
            word = ("the same time as here" if gap == 0 else
                    f"{abs(gap):g} {unit} {'ahead of' if gap > 0 else 'behind'} you")
            return (f"It's {now.strftime('%I:%M %p').lstrip('0')} "
                    f"{now.strftime('%A')} in {place.title()} — {word}.")
    return None


def _units(q: str):
    names = "|".join(sorted(UNITS, key=len, reverse=True))
    m = re.search(rf"(\d+(?:\.\d+)?)\s*({names})\b", q)
    if not m:
        return None
    amount, from_unit = float(m.group(1)), m.group(2)
    kind, factor = UNITS[from_unit]
    # The target unit can come after ("5 miles to km") or before the amount
    # ("how many kilometres in 5 miles") — people say it both ways. Scan every
    # unit word and keep the first of the SAME kind, so the English word "in"
    # in "80 kg in pounds" can't hijack the answer as inches.
    def _first_of_kind(text: str):
        for hit in re.finditer(rf"\b({names})\b", text):
            word = hit.group(1)
            if UNITS[word][0] == kind and word != from_unit:
                return word
        return None

    to_unit = _first_of_kind(q[m.end():]) or _first_of_kind(q[:m.start()])
    if to_unit is None:
        return None
    return (f"{_say(amount)} {from_unit} is "
            f"{_say(amount * factor / UNITS[to_unit][1])} {to_unit}.")


def run(args: dict) -> str:
    q = (args.get("query") or "").strip().lower()
    if not q:
        return "Convert what?"
    q = q.replace("kilometres per hour", "kmh").replace("kilometers per hour", "kmh")
    q = q.replace("miles per hour", "mph")
    for attempt in (_timezone, _temperature, _money, _units):
        try:
            answer = attempt(q)
        except Exception:
            answer = None
        if answer:
            return answer
    # not actually a conversion — let the brain answer it properly
    return "__PASS__"
