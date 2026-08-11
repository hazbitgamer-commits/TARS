"""Publishing and updating by voice — 'publish yourself', 'is there an
update', 'update yourself'."""
import json
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[2]
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

DESCRIPTION = ("PUBLISH TARS's own code to GitHub, or UPDATE this copy from "
               "it — 'publish yourself', 'push your code', 'is there an "
               "update', 'update yourself', 'stop publishing automatically'. "
               "Publishing also happens on its own whenever the code changes; "
               "this is for asking directly. NOT for uploading a single file "
               "(github_file).")
ARGS = {"action": "'publish', 'update', 'check', 'auto_off', or 'auto_on'"}


def _setting(key: str, value: bool) -> None:
    path = BASE / "settings.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        data = {}
    data[key] = value
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def run(args: dict) -> str:
    action = str(args.get("action") or "publish").strip().lower()

    if action in ("update", "upgrade", "pull"):
        import updater

        return updater.check(apply=True)
    if action in ("check", "any_updates", "updates"):
        import updater

        return updater.check(apply=False)
    if action in ("auto_off", "off", "stop"):
        _setting("auto_publish", False)
        return ("I'll stop publishing automatically. Say publish yourself "
                "when you want it done.")
    if action in ("auto_on", "on", "start"):
        _setting("auto_publish", True)
        return "Automatic publishing is back on."

    import publish_watch

    return publish_watch.publish_now(force=True)
