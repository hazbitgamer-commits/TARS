"""Shared announcement queue: background work posts here, main.py speaks them."""
import json
from pathlib import Path

FILE = Path(__file__).parent / "announcements.json"


def post(message: str) -> None:
    try:
        items = json.loads(FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        items = []
    items.append(message)
    FILE.write_text(json.dumps(items, indent=1), encoding="utf-8")


def pop() -> list[str]:
    try:
        items = json.loads(FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return []
    if items:
        FILE.write_text("[]", encoding="utf-8")
    return items
