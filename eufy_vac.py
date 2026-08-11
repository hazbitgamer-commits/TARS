"""Standalone eufy vacuum control for TARS.

Uses the vendored api layer from jeppesens/eufy-clean (eufy_lib/) — logs into
the owner's eufy account (EUFY_EMAIL / EUFY_PASSWORD in .env), finds the vacuum,
and drives it over eufy's MQTT. No Home Assistant required.

The slow HTTP login/discovery is cached; the MQTT link is opened fresh per
command and hung up cleanly (each voice command runs its own asyncio loop, so
a lingering MQTT thread would wake up holding a closed loop).
"""
import asyncio
import os
import sys
import time
import uuid
from pathlib import Path

BASE = Path(__file__).parent
sys.path.insert(0, str(BASE / "eufy_lib"))

UDID_FILE = BASE / "eufy_openudid.txt"
NICK_FILE = BASE / "vacuum_nickname.txt"  # the owner named it Basel
_login_cache = {"t": 0.0, "dev": None, "creds": None}
CACHE_TTL = 600  # re-login every 10 minutes at most


def _name(dev: dict) -> str:
    if NICK_FILE.exists():
        nick = NICK_FILE.read_text(encoding="utf-8").strip()
        if nick:
            return nick
    return dev.get("deviceName") or "the vacuum"


def _openudid() -> str:
    if UDID_FILE.exists():
        return UDID_FILE.read_text(encoding="utf-8").strip()
    u = uuid.uuid4().hex
    UDID_FILE.write_text(u, encoding="utf-8")
    return u


async def _discover():
    """(device, mqtt_credentials) — cached; raises RuntimeError speakably."""
    if _login_cache["dev"] and time.time() - _login_cache["t"] < CACHE_TTL:
        return _login_cache["dev"], _login_cache["creds"]

    email = (os.getenv("EUFY_EMAIL") or "").strip()
    password = (os.getenv("EUFY_PASSWORD") or "").strip()
    if not email or not password:
        raise RuntimeError("The eufy account isn't connected yet — the setup "
                           "steps are in the readme.")

    import aiohttp

    from robovac_mqtt.api.cloud import EufyLogin

    session = aiohttp.ClientSession()
    try:
        login = EufyLogin(email, password, _openudid(), websession=session)
        await login.init()
        devices = login.mqtt_devices
        if not devices:
            raise RuntimeError("I signed into eufy but couldn't find a vacuum "
                               "on the account.")
        _login_cache.update(t=time.time(), dev=devices[0],
                            creds=login.mqtt_credentials)
        return _login_cache["dev"], _login_cache["creds"]
    finally:
        await session.close()


async def _open_link(dev, creds):
    """Fresh MQTT client, connected. truststore (our Avast workaround) breaks
    the broker's mutual TLS, so step out of it for the handshake."""
    from robovac_mqtt.api.client import EufyCleanClient

    client = EufyCleanClient(
        device_id=dev["deviceId"], user_id=creds["user_id"],
        app_name=creds["app_name"], thing_name=creds["thing_name"],
        access_key="", ticket="", openudid=_openudid(),
        certificate_pem=creds["certificate_pem"],
        private_key=creds["private_key"],
        device_model=dev.get("deviceModel", ""),
        endpoint=creds["endpoint_addr"],
    )
    ts = None
    try:
        import truststore

        truststore.extract_from_ssl()
        ts = truststore
    except Exception:
        pass
    try:
        await client.connect()
    finally:
        if ts:
            try:
                ts.inject_into_ssl()
            except Exception:
                pass
    # connect() returns before the broker says hello — wait for the real
    # handshake, or the first command vanishes into the void
    try:
        await asyncio.wait_for(client._connected_event.wait(), timeout=12)
    except asyncio.TimeoutError:
        try:
            await client.disconnect()
        except Exception:
            pass
        raise RuntimeError("The vacuum link didn't come up — give it a "
                           "moment and try again.")
    return client


async def command(cmd: str) -> str:
    """Send start_auto / pause / play / return_to_base. Returns device name."""
    from robovac_mqtt.api.commands import build_command

    dev, creds = await _discover()
    payload = build_command(cmd, api_type=dev.get("apiType", "novel"))
    if not payload:
        raise RuntimeError(f"That command ({cmd}) isn't supported on this model.")
    client = await _open_link(dev, creds)
    try:
        if not (client._mqtt_client and client._mqtt_client.is_connected()):
            raise RuntimeError("The vacuum link dropped before I could send "
                               "the command. Try again.")
        await client.send_command(payload)
        await asyncio.sleep(1.0)  # let the publish flush before hanging up
    finally:
        try:
            await client.disconnect()
        except Exception:
            pass
    return _name(dev)


async def set_fan_speed(speed: str) -> str:
    """Set the vacuum's suction/fan speed (Quiet/Standard/Turbo/Max). Returns device name."""
    from robovac_mqtt.api.commands import build_command

    dev, creds = await _discover()
    payload = build_command("set_fan_speed", api_type=dev.get("apiType", "novel"),
                             fan_speed=speed)
    if not payload:
        raise RuntimeError(f"That clean speed ({speed}) isn't supported on this model.")
    client = await _open_link(dev, creds)
    try:
        if not (client._mqtt_client and client._mqtt_client.is_connected()):
            raise RuntimeError("The vacuum link dropped before I could send "
                               "the command. Try again.")
        await client.send_command(payload)
        await asyncio.sleep(1.0)  # let the publish flush before hanging up
    finally:
        try:
            await client.disconnect()
        except Exception:
            pass
    return _name(dev)


async def get_rooms() -> tuple[list, int]:
    """([{'id':..,'name':..}, ...], map_id) known from the last cloud snapshot.

    Room names only exist once the vacuum has learned the home's layout (it
    builds the map during a normal full clean) — before that this comes back
    empty.
    """
    from robovac_mqtt.api.parser import update_state
    from robovac_mqtt.models import VacuumState

    dev, _ = await _discover()
    st, _changes = update_state(
        VacuumState(api_type=dev.get("apiType", "novel")), dev.get("dps", {}))
    return st.rooms, st.map_id


def _norm_room(s: str) -> str:
    """Speech gives straight apostrophes; the eufy app stores curly ones."""
    return (s.strip().lower().replace("’", "").replace("‘", "").replace("'", "")
            .replace("the ", "", 1))


def _find_room(rooms: list, name: str):
    """Best-match a spoken room name against the known room list, or None."""
    q = _norm_room(name)
    for r in rooms:
        if _norm_room(r["name"]) == q:
            return r
    hits = [r for r in rooms
            if q in _norm_room(r["name"]) or _norm_room(r["name"]) in q]
    return hits[0] if len(hits) == 1 else None


async def clean_room(name: str) -> str:
    """Send the vacuum to clean just one named room. Returns a spoken result."""
    from robovac_mqtt.api.commands import build_command

    rooms, map_id = await get_rooms()
    if not rooms:
        raise RuntimeError("I don't know this home's rooms yet — run a full "
                            "clean once so the vacuum can map the place.")
    room = _find_room(rooms, name)
    if room is None:
        names = ", ".join(r["name"] for r in rooms)
        raise RuntimeError(f"I don't know a room called {name}. Rooms I know: {names}.")

    dev, creds = await _discover()
    payload = build_command("room_clean", api_type=dev.get("apiType", "novel"),
                             room_ids=[room["id"]], map_id=map_id)
    client = await _open_link(dev, creds)
    try:
        if not (client._mqtt_client and client._mqtt_client.is_connected()):
            raise RuntimeError("The vacuum link dropped before I could send "
                               "the command. Try again.")
        await client.send_command(payload)
        await asyncio.sleep(1.0)  # let the publish flush before hanging up
    finally:
        try:
            await client.disconnect()
        except Exception:
            pass
    article = "" if ("'" in room["name"] or "’" in room["name"]) else "the "
    return f"{_name(dev)} is cleaning {article}{room['name']}."


async def info() -> str:
    """Live status: re-login for a fresh state snapshot from eufy's cloud."""
    _login_cache["t"] = 0  # force fresh — stale status is worse than slow status
    dev, _ = await _discover()
    from robovac_mqtt.api.parser import update_state
    from robovac_mqtt.models import VacuumState

    st, _changes = update_state(
        VacuumState(api_type=dev.get("apiType", "novel")), dev.get("dps", {}))
    name = _name(dev)
    doing = {"cleaning": "cleaning", "docked": "docked", "charging": "charging",
             "returning": "heading back to the dock", "paused": "paused",
             "idle": "idle", "error": "showing an error"}.get(st.activity, st.activity)
    extra = " and charging" if st.charging and st.activity != "charging" else ""
    err = f" Error: {st.error_message}." if st.error_code else ""
    return f"{name} is {doing}{extra}, battery {st.battery_level} percent.{err}"


def run_sync(coro) -> str:
    return asyncio.run(coro)
