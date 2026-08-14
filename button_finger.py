"""Keeping the Arduino's dead man's switch fed.

There is a servo taped to the top of his PC, poised over the power button.
It presses if TARS stops saying "I'm alive" for three minutes. That is the
only way to bring the machine back from a shutdown or a power cut, because
every other route needs something on the network to be awake, and after a
blackout nothing is.

So this module's whole job is to send a tick every twenty seconds, and to
say "don't" before a shutdown he actually meant.

It is deliberately unexciting:
  - if there's no Arduino plugged in, it does nothing and says nothing.
  - if the port disappears mid-run (unplugged, reset) it keeps trying
    quietly rather than throwing.
  - it never sends a press on its own. The only thing that presses without
    being asked is the Arduino, when TARS has gone quiet — which is the
    whole point, since by then TARS isn't running to ask.
"""
import threading
import time

TICK_EVERY = 20          # the sketch gives up after 180s of silence
BAUD = 9600
HINTS = ("arduino", "ch340", "usb-serial", "usb serial", "wch", "silicon labs")
# Windows describes his genuine Uno as "USB Serial Device" made by
# "Microsoft", so the words above find nothing. The USB vendor ID doesn't
# lie: 0x2341 Arduino, 0x2A03 Arduino.org, 0x1A86 CH340 clones, 0x0403 FTDI,
# 0x10C4 CP210x.
BOARD_VIDS = {0x2341, 0x2A03, 0x1A86, 0x0403, 0x10C4, 0x1B4F, 0x239A}

_state = {"port": "", "serial": None, "ticks": 0, "since": 0.0}
_lock = threading.Lock()


def _find_port() -> str:
    try:
        from serial.tools import list_ports
    except ImportError:
        return ""
    best = ""
    for port in list_ports.comports():
        if port.vid in BOARD_VIDS:
            return port.device          # the hardware ID — trust this first
        blurb = f"{port.description} {port.manufacturer or ''}".lower()
        if any(h in blurb for h in HINTS):
            return port.device
        if not best and port.device.upper().startswith("COM"):
            best = port.device          # last resort: the first serial port
    return best


def _open():
    """Connect, and give the board time to reboot.

    Opening the port resets an Uno — that's the DTR line, not a fault — so
    anything sent in the first couple of seconds lands in a bootloader that
    isn't listening yet.
    """
    import serial

    port = _find_port()
    if not port:
        return None
    link = serial.Serial(port, BAUD, timeout=1)
    time.sleep(2.5)
    _state["port"] = port
    _state["since"] = time.time()
    return link


def _loop() -> None:
    while True:
        link = _state.get("serial")
        if link is None:
            try:
                link = _open()
            except Exception:
                link = None
            _state["serial"] = link
            if link is None:
                time.sleep(30)          # nothing plugged in; look again later
                continue
            print(f"(power-button finger on {_state['port']})")
        try:
            link.write(b"T\n")
            link.flush()
            _state["ticks"] += 1
        except Exception:
            try:
                link.close()
            except Exception:
                pass
            _state["serial"] = None      # unplugged or reset — reconnect
            continue
        time.sleep(TICK_EVERY)


def _send(command: str) -> bool:
    link = _state.get("serial")
    if link is None:
        return False
    try:
        link.write((command + "\n").encode())
        link.flush()
        return True
    except Exception:
        return False


def connected() -> bool:
    return _state.get("serial") is not None


def status() -> str:
    if not connected():
        return ("No power-button finger connected — nothing would bring the "
                "PC back from a shutdown.")
    mins = int((time.time() - _state["since"]) / 60)
    return (f"Power-button finger is on {_state['port']}, fed for "
            f"{mins} minute{'s' if mins != 1 else ''}. If I go quiet for "
            f"three minutes it presses the button.")


def stay_down(minutes: int = 60) -> bool:
    """Before a shutdown he MEANT. Without this the servo would helpfully
    turn the machine straight back on, which is its job but not his wish."""
    return _send(f"D{max(1, min(720, int(minutes)))}")


def arm() -> bool:
    return _send("A")


def press() -> bool:
    """Only ever on an explicit ask — and pointless while the PC is on,
    since the button now sleeps it."""
    return _send("P")


def _open_and_send(command: str) -> bool:
    """One-shot, for when TARS itself is already gone.

    The supervisor calls this after a deliberate shutdown to say "stay
    down". By then the engine has exited and released the port, so this
    opens its own connection, waits out the Uno's reset, speaks, and closes.
    """
    try:
        import serial

        port = _find_port()
        if not port:
            return False
        with serial.Serial(port, BAUD, timeout=1) as link:
            time.sleep(2.5)          # the board reboots when the port opens
            link.write((command + "\n").encode())
            link.flush()
            time.sleep(0.3)
        return True
    except Exception:
        return False


def start() -> None:
    """Called from main(). Silent and harmless when no board is attached."""
    threading.Thread(target=_loop, daemon=True).start()
