"""What's on its way — orders and deliveries, pulled out of the inbox.

Nobody wants to dig through a hundred marketing emails to find out where the
thing they bought is. This reads the shipping mail and says it in a sentence.
"""
import json
import sys
from pathlib import Path

import requests

BASE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BASE))

DESCRIPTION = ("DELIVERIES AND ORDERS on the way — 'where's my package', 'what have I "
               "got coming', 'any deliveries today', 'has my order shipped'. Reads "
               "shipping and order emails from the inbox and sums them up. NOT for "
               "reading email generally (that's the email skill).")
ARGS = {"days": "how far back to look, in days (default 30)"}

OLLAMA_URL = "http://127.0.0.1:11434/api/chat"
NOT_CONNECTED = ("Google isn't connected yet, so I can't see any orders. "
                 "The setup steps are in the readme.")
# gmail search: the language shipping mail actually uses
QUERY = ('newer_than:{days}d (subject:(shipped OR dispatched OR "on its way" OR '
         '"out for delivery" OR delivered OR tracking OR "order confirmed" OR '
         '"your order" OR "has been sent") OR from:(auspost OR startrack OR dhl OR '
         'fedex OR ups OR aramex OR couriersplease OR sendle OR shippit))')


def _bg_model() -> str:
    try:
        from platform_caps import bg_model

        return bg_model()
    except Exception:
        return "qwen3:8b"


def _clean(text: str) -> str:
    import html
    import unicodedata

    text = html.unescape(text or "")
    text = "".join(c for c in text
                   if unicodedata.category(c) not in ("Cf", "Co", "Cc", "Mn"))
    return " ".join(text.split())


def run(args: dict) -> str:
    raw = "".join(c for c in str(args.get("days", "") or "") if c.isdigit())
    days = max(1, min(120, int(raw))) if raw else 30

    try:
        from google_auth import get_service

        svc = get_service("gmail", "v1")
    except Exception as e:
        return f"Google sign-in hiccuped: {e}"
    if svc is None:
        return NOT_CONNECTED

    try:
        res = svc.users().messages().list(
            userId="me", q=QUERY.format(days=days), maxResults=12).execute()
        msgs = res.get("messages", [])
        if not msgs:
            return f"Nothing looks like it's on its way — no shipping mail in {days} days."
        lines = []
        for m in msgs:
            full = svc.users().messages().get(
                userId="me", id=m["id"], format="metadata",
                metadataHeaders=["From", "Subject", "Date"]).execute()
            h = {x["name"]: x["value"] for x in full["payload"]["headers"]}
            sender = _clean(h.get("From", "")).split("<")[0].strip().strip('"')
            lines.append(f"- {h.get('Date', '')[:16]} | {sender} | "
                         f"{_clean(h.get('Subject', ''))} | "
                         f"{_clean(full.get('snippet', ''))[:140]}")
    except Exception as e:
        return f"I couldn't read the inbox just then: {e}"

    try:
        r = requests.post(OLLAMA_URL, json={
            "model": _bg_model(), "stream": False, "think": False,
            "messages": [{"role": "user", "content":
                "Shipping and order emails from the owner's inbox, newest first:\n"
                + "\n".join(lines) +
                "\n\nSay what is ON THE WAY and what has already ARRIVED, grouping "
                "by retailer, newest first. Two or three short spoken sentences, "
                "plain text, no markdown, no links. Ignore marketing emails that "
                "aren't about a real order. If none are real orders, say so."}],
            "options": {"num_predict": 180}}, timeout=120)
        r.raise_for_status()
        return r.json()["message"]["content"].strip()
    except Exception:
        newest = lines[0].split("|")
        return f"Latest looks like {newest[1].strip()}: {newest[2].strip()}"
