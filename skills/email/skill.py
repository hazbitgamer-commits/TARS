"""Gmail: check/read/summarize mail, and write drafts. TARS never sends —
drafts wait in Gmail for the owner to review and hit send himself (hard-block rule).
"""
import base64
import sys
from email.mime.text import MIMEText
from pathlib import Path

import requests

BASE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BASE))

DESCRIPTION = ("Gmail: check for new email, read the latest one, summarize the inbox, "
               "or draft an email (drafts only — the owner sends them himself from Gmail). "
               "E.g. 'any new emails?', 'what was my latest email', 'summarize my "
               "emails', 'draft an email to mum about sunday dinner'.")
ARGS = {"action": "'unread', 'latest', 'summarize', or 'draft'",
        "to": "recipient, for draft (name or address)",
        "about": "what the draft should say, in the owner's words"}

NOT_CONNECTED = ("Google isn't connected yet — the setup steps are in the readme, "
                 "or ask Claude to walk you through it.")

OLLAMA_URL = "http://127.0.0.1:11434/api/chat"
from platform_caps import bg_model
MODEL = bg_model()


def _svc():
    from google_auth import get_service

    return get_service("gmail", "v1")


def _clean(text: str) -> str:
    """Strip the invisible junk characters newsletters hide in previews."""
    import html
    import unicodedata

    text = html.unescape(text)
    text = "".join(c for c in text
                   if unicodedata.category(c) not in ("Cf", "Co", "Cc", "Mn"))
    return " ".join(text.split())


def _headers(svc, msg_id):
    m = svc.users().messages().get(
        userId="me", id=msg_id, format="metadata",
        metadataHeaders=["From", "Subject"]).execute()
    h = {x["name"]: x["value"] for x in m["payload"]["headers"]}
    sender = h.get("From", "unknown").split("<")[0].strip().strip('"')
    return sender, _clean(h.get("Subject", "(no subject)")), _clean(m.get("snippet", ""))


def run(args: dict) -> str:
    action = (args.get("action") or "unread").strip().lower()
    try:
        svc = _svc()
    except Exception as e:
        return f"Google sign-in hiccuped: {e}"
    if svc is None:
        return NOT_CONNECTED

    if action in ("unread", "check"):
        res = svc.users().messages().list(
            userId="me", labelIds=["UNREAD", "INBOX"], maxResults=5).execute()
        msgs = res.get("messages", [])
        if not msgs:
            return "Inbox zero on unread. Enjoy it while it lasts."
        parts = []
        for m in msgs[:5]:
            sender, subject, _ = _headers(svc, m["id"])
            parts.append(f"{sender}: {subject}")
        total = res.get("resultSizeEstimate", len(msgs))
        return f"{total} unread. " + "; ".join(parts) + "."

    if action in ("latest", "last", "read", "newest"):
        res = svc.users().messages().list(
            userId="me", labelIds=["INBOX"], maxResults=1).execute()
        msgs = res.get("messages", [])
        if not msgs:
            return "The inbox is empty."
        sender, subject, snippet = _headers(svc, msgs[0]["id"])
        return (f"Latest email is from {sender}. Subject: {subject}. "
                f"It starts: {snippet[:200]}")

    if action == "summarize":
        res = svc.users().messages().list(
            userId="me", labelIds=["INBOX"], maxResults=8).execute()
        msgs = res.get("messages", [])
        if not msgs:
            return "The inbox is empty."
        lines = []
        for m in msgs:
            sender, subject, snippet = _headers(svc, m["id"])
            lines.append(f"- {sender} | {subject} | {snippet[:120]}")
        r = requests.post(OLLAMA_URL, json={
            "model": MODEL, "stream": False, "think": False,
            "messages": [{"role": "user", "content":
                "Recent emails in the owner's inbox:\n" + "\n".join(lines) +
                "\n\nSummarize what matters in two or three short spoken "
                "sentences. Skip obvious spam/newsletters unless notable. "
                "Plain text, no markdown."}],
            "options": {"num_predict": 160}}, timeout=120)
        return r.json()["message"]["content"].strip()

    if action == "draft":
        to = (args.get("to") or "").strip()
        about = (args.get("about") or "").strip()
        if not about:
            return "Draft what, exactly?"
        r = requests.post(OLLAMA_URL, json={
            "model": MODEL, "stream": False, "think": False, "format": "json",
            "messages": [{"role": "user", "content":
                f"Write a short friendly email from the owner. To: {to or 'unknown'}. "
                f"About: {about}. Reply JSON: "
                '{"subject": "...", "body": "... (sign off as the owner)"}'}],
            "options": {"temperature": 0.4}}, timeout=120)
        import json as _json

        data = _json.loads(r.json()["message"]["content"])
        mime = MIMEText(data.get("body", about))
        if "@" in to:
            mime["To"] = to
        mime["Subject"] = data.get("subject", about[:60])
        raw = base64.urlsafe_b64encode(mime.as_bytes()).decode()
        svc.users().drafts().create(
            userId="me", body={"message": {"raw": raw}}).execute()
        who = f" to {to}" if to else ""
        return (f"Draft{who} saved in your Gmail drafts — subject: "
                f"{mime['Subject']}. Review and send it from there.")

    return ("With email I can check unread, read the latest, summarize the inbox, "
            "or write a draft. Which would you like?")
