"""TARS's doorbell — runs on an old Android phone, not the PC.

The problem: TARS's brain is a 7B model living in the PC's RAM. PC off, no
TARS. The fix isn't to shrink him — it's to give him a doorbell that's awake
when he isn't, and let it wake the machine.

An old phone on a charger draws about 2 watts. It sits on the home WiFi and
does almost nothing:

    is the PC's TARS answering on the network?
      yes -> sleep. The PC owns the conversation; stay out of the way.
      no  -> has he texted? Then send a magic packet to wake the PC, tell
             him it's coming, and go quiet again.

THE IMPORTANT TRICK: this never *consumes* the Telegram message. Telegram
only counts an update as delivered once you ask for the one after it, so the
doorbell peeks without confirming, and the real TARS receives that same
message himself the moment he's awake — with his full brain, memory and all
110 skills. Nothing is forwarded, nothing is lost, and there's no second
half-witted TARS living on a phone giving worse answers.

It also means the PC's dashboard stays bound to localhost. Opening it to the
network would have exposed /api/setup/reveal — his school password — to
anyone on the WiFi.

Setup: see PHONE_DOORBELL.md. First run asks four questions and remembers.

    python doorbell.py
"""
import json
import socket
import time
import urllib.error
import urllib.request
from pathlib import Path

BASE = Path(__file__).resolve().parent
CONFIG = BASE / "doorbell.json"

CHECK_EVERY = 20        # seconds between "is the PC up?" checks
PEEK_TIMEOUT = 30       # long-poll: a text wakes us within a second
WAKE_WAIT = 180         # how long to give the PC to come up
WOL_PORT = 9
PULSE_PORT = 8767       # TARS's heartbeat — see heartbeat.py on the PC


def ask_setup() -> dict:
    """Four questions, once. Everything it needs is on the PC's dashboard
    or in the same .env the PC uses."""
    print("TARS doorbell — first-time setup.\n")
    cfg = {}
    cfg["token"] = input(
        "Telegram bot token (the same one the PC uses): ").strip()
    cfg["mac"] = input(
        "PC's ethernet address, e.g. 9C-6B-00-E3-8B-50: ").strip()
    cfg["pc_ip"] = input(
        "PC's address on your home network, e.g. 192.168.4.45: ").strip()
    guess = ".".join(cfg["pc_ip"].split(".")[:3]) + ".255" if \
        cfg["pc_ip"].count(".") == 3 else "255.255.255.255"
    broadcast = input(f"Broadcast address [{guess}]: ").strip() or guess
    cfg["broadcast"] = broadcast
    # most home networks are /24; his router hands out a /22. Only matters
    # if the PC's address ever changes, so it isn't worth a question.
    cfg["prefix_len"] = 24
    CONFIG.write_text(json.dumps(cfg, indent=1), encoding="utf-8")
    print(f"\nSaved to {CONFIG}. Leave this running and put the phone on "
          f"the charger.\n")
    return cfg


def load() -> dict:
    try:
        return json.loads(CONFIG.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ask_setup()


CFG = load()


def answers_at(ip: str, timeout: float = 4.0) -> bool:
    """Ask TARS's heartbeat (port 8767) whether he's alive.

    NOT his dashboard on 8765 — that one is bound to the PC itself on
    purpose, because it can open the camera and reveal the school password.
    The heartbeat is a separate listener that can only say the word "TARS".

    A plain ping would be no good either: it proves the machine has power,
    not that TARS came back with it.
    """
    try:
        with urllib.request.urlopen(f"http://{ip}:{PULSE_PORT}/",
                                    timeout=timeout) as r:
            return r.read(16).strip() == b"TARS"
    except Exception:
        return False


def pc_awake() -> bool:
    return answers_at(CFG["pc_ip"])


def relocate() -> bool:
    """Find the PC again after its address changed.

    Home routers hand out addresses on a lease — his is four hours, and the
    PC is asleep for longer than that most school days. When the lease
    lapses the router can give that address to a phone or a TV, and a
    doorbell pinned to one number would sit there watching the wrong
    device forever, insisting TARS was dead.

    So: sweep the network for whatever is actually answering as TARS, and
    remember it. Only ever runs when the known address has gone quiet.
    """
    import ipaddress
    import queue
    import threading

    # The network isn't necessarily a /24. His is a /22 — addresses run from
    # 192.168.4.0 all the way to 192.168.7.255 — so assuming three matching
    # octets would search a quarter of it and declare the PC dead.
    try:
        net = ipaddress.ip_network(
            f"{CFG['pc_ip']}/{CFG.get('prefix_len', 24)}", strict=False)
        hosts = [str(h) for h in net.hosts()]
    except ValueError:
        prefix = ".".join(CFG["pc_ip"].split(".")[:3])
        hosts = [f"{prefix}.{n}" for n in range(1, 255)]

    todo = queue.Queue()
    for h in hosts:
        todo.put(h)
    found = []

    def worker() -> None:
        # a fixed pool, not one thread per address: a /22 is a thousand
        # addresses and this is running on a phone from 2016
        while not found:
            try:
                ip = todo.get_nowait()
            except queue.Empty:
                return
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(0.4)
            try:
                if s.connect_ex((ip, PULSE_PORT)) == 0 and answers_at(ip, 2.0):
                    found.append(ip)
            except OSError:
                pass
            finally:
                s.close()

    pool = [threading.Thread(target=worker, daemon=True) for _ in range(48)]
    for w in pool:
        w.start()
    for w in pool:
        w.join(timeout=30)

    if not found:
        return False
    CFG["pc_ip"] = found[0]
    try:
        CONFIG.write_text(json.dumps(CFG, indent=1), encoding="utf-8")
    except OSError:
        pass
    print(f"(PC moved to {found[0]} — remembered)")
    return True


def wake_pc() -> None:
    """The magic packet: six 0xFF bytes, then the MAC sixteen times. Sent to
    the broadcast address because a sleeping PC has no IP to aim at."""
    mac = CFG["mac"].replace("-", "").replace(":", "").strip()
    packet = b"\xff" * 6 + bytes.fromhex(mac) * 16
    for target in (CFG.get("broadcast", "255.255.255.255"), "255.255.255.255"):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            s.sendto(packet, (target, WOL_PORT))
            s.close()
        except OSError:
            pass


def tg(method: str, timeout: int = 20, **params):
    url = f"https://api.telegram.org/bot{CFG['token']}/{method}"
    data = json.dumps(params).encode()
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except Exception:
        return {}


def peek() -> list:
    """Look at waiting messages WITHOUT confirming them.

    Telegram only marks updates delivered when you ask for the one after
    them. Never pass an offset here — that would eat the message and the
    real TARS would never see what he was asked.
    """
    return tg("getUpdates", timeout=PEEK_TIMEOUT + 10).get("result", [])


def say(chat_id: int, text: str) -> None:
    tg("sendMessage", chat_id=chat_id, text=text)


def main() -> None:
    print("Doorbell listening. PC:", CFG["pc_ip"], "MAC:", CFG["mac"])
    handled = 0        # last update we've already acted on, so a PC that
    # refuses to wake doesn't get a fresh "waking him up!" every 30 seconds
    while True:
        try:
            if pc_awake():
                time.sleep(CHECK_EVERY)
                continue

            waiting = peek()
            fresh = [u for u in waiting if u.get("update_id", 0) > handled
                     and (u.get("message") or {}).get("chat")]
            if not fresh:
                time.sleep(5)
                continue

            handled = max(u["update_id"] for u in fresh)
            chat_id = (fresh[-1]["message"]["chat"] or {}).get("id")
            if not chat_id:
                continue

            say(chat_id, "PC's asleep — I'm waking him now. Give me a minute, "
                         "then he'll answer this himself.")
            wake_pc()

            deadline = time.time() + WAKE_WAIT
            searched = False
            while time.time() < deadline:
                time.sleep(5)
                if pc_awake():
                    break
                # half the wait gone and still nothing at the address we
                # know — the router may have moved him. Look properly
                # before telling him his PC is dead.
                if not searched and time.time() > deadline - WAKE_WAIT / 2:
                    searched = True
                    if relocate():
                        break
            if not pc_awake():
                say(chat_id, "He didn't wake up. The PC might be unplugged, "
                             "or off at the wall.")
            # if he DID wake: say nothing. His own Telegram bridge picks up
            # the message we deliberately left unread and answers it properly.
        except KeyboardInterrupt:
            print("\nDoorbell stopped.")
            return
        except Exception as e:
            print(f"(doorbell hiccup: {type(e).__name__}) — carrying on")
            time.sleep(15)


if __name__ == "__main__":
    main()
