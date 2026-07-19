"""Google Nest speakers/displays over the local Cast protocol (pychromecast).

Devices are cached in speakers_cache.json after the first discovery, so
commands are fast. Announcements use Google's TTS URL, which the speaker
fetches itself — no firewall gymnastics.
"""
import json
import time
import urllib.parse
from pathlib import Path
from uuid import UUID

DESCRIPTION = ("Control the Google Nest speakers: announce a message in a room, set "
               "SPEAKER volume, pause/resume/stop playback, or list devices. Rooms: "
               "kitchen (display), bedroom (speaker). Use for anything mentioning a "
               "room, speaker, or display — the plain volume skill is the PC only.")
ARGS = {"action": "'announce', 'volume', 'pause', 'resume', 'stop', or 'list'",
        "room": "'kitchen', 'bedroom', or 'all' (announce defaults to all)",
        "text": "the message, for announce",
        "level": "0-100, for volume",
        "override": "'true' ONLY if Jacob explicitly says to override quiet hours"}

BASE = Path(__file__).resolve().parents[2]
CACHE = BASE / "speakers_cache.json"


def _devices(refresh: bool = False) -> list[dict]:
    if not refresh and CACHE.exists():
        return json.loads(CACHE.read_text(encoding="utf-8"))
    import pychromecast

    ccs, browser = pychromecast.get_chromecasts(timeout=10)
    devs = [{"name": c.cast_info.friendly_name, "host": c.cast_info.host,
             "port": c.cast_info.port, "uuid": str(c.cast_info.uuid),
             "model": c.cast_info.model_name} for c in ccs]
    browser.stop_discovery()
    if devs:
        CACHE.write_text(json.dumps(devs, indent=1), encoding="utf-8")
    return devs


def _connect(dev: dict):
    import pychromecast

    cc = pychromecast.get_chromecast_from_host(
        (dev["host"], dev["port"], UUID(dev["uuid"]), dev["model"], dev["name"]))
    cc.wait(timeout=10)
    return cc


def _pick(room: str) -> list[dict]:
    devs = _devices()
    room = (room or "").strip().lower()
    if room in ("", "all", "everywhere", "house"):
        return devs
    hits = [d for d in devs if room in d["name"].lower()]
    if not hits:  # maybe the cache is stale — rescan once
        devs = _devices(refresh=True)
        hits = [d for d in devs if room in d["name"].lower()]
    return hits


def run(args: dict) -> str:
    action = (args.get("action") or "list").strip().lower()

    if action == "list":
        devs = _devices(refresh=True)
        if not devs:
            return "I can't find any speakers on the network right now."
        return "On the network: " + "; ".join(f"{d['name']} ({d['model']})" for d in devs) + "."

    # quiet hours: noise-making actions are blocked unless Jacob overrides
    if action in ("announce", "resume"):
        import sys

        sys.path.insert(0, str(BASE))
        import quiet

        active, span = quiet.is_active()
        if active and str(args.get("override", "")).lower() != "true":
            return (f"Quiet hours are on until the morning ({span}) — the house "
                    "speakers stay silent. Say 'override quiet hours' if it's urgent.")

    targets = _pick(args.get("room", "all" if action == "announce" else ""))
    if not targets:
        return "I can't find that speaker. Say 'list the speakers' to see what's around."

    if action == "announce":
        text = (args.get("text") or "").strip()
        if not text:
            return "Announce what, exactly?"
        url = ("https://translate.google.com/translate_tts?ie=UTF-8&client=tw-ob&tl=en"
               "&q=" + urllib.parse.quote(text[:180]))
        done = []
        for dev in targets:
            try:
                cc = _connect(dev)
                mc = cc.media_controller
                mc.play_media(url, "audio/mpeg")
                mc.block_until_active(timeout=10)
                done.append(dev["name"])
            except Exception:
                pass
        if not done:
            return "The speakers didn't answer. Are they powered on?"
        return f"Announced on {', '.join(done)}."

    results = []
    for dev in targets:
        try:
            cc = _connect(dev)
            if action == "volume":
                raw = str(args.get("level", "")).strip().rstrip("%")
                if not raw.isdigit():
                    results.append(f"{dev['name']} is at "
                                   f"{round(cc.status.volume_level * 100)} percent")
                    continue
                cc.set_volume(max(0, min(100, int(raw))) / 100)
                time.sleep(0.3)
                results.append(f"{dev['name']} volume {raw} percent")
            elif action == "pause":
                cc.media_controller.pause()
                results.append(f"paused {dev['name']}")
            elif action == "resume":
                cc.media_controller.play()
                results.append(f"resumed {dev['name']}")
            elif action == "stop":
                cc.media_controller.stop()
                results.append(f"stopped {dev['name']}")
            else:
                return f"I don't know the speaker action {action}."
        except Exception:
            results.append(f"{dev['name']} didn't answer")
    return (", ".join(results) + ".").capitalize()
