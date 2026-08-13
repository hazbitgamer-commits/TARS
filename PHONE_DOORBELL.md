# TARS's doorbell — keeping him reachable when the PC is off

TARS's brain is a 7-billion-parameter model that lives in your PC's memory.
When the PC is off, there is no TARS to talk to. Nothing can change that
short of paying for a server.

So instead of shrinking him into something worse, you give him a **doorbell**:
an old Android phone on a charger that's awake when he isn't. You text him,
the phone wakes the PC, and the real TARS answers — full brain, full memory,
all 110 skills.

The phone draws about **2 watts**. Leaving it plugged in costs you roughly a
dollar a year.

---

## How it works

The phone does almost nothing. Every 20 seconds it asks: *is TARS answering
on the network?*

- **Yes** → it goes back to sleep. The PC owns the conversation.
- **No** → it checks whether you've texted. If you have, it sends a "magic
  packet" that wakes the PC, tells you it's coming, and goes quiet.

**It never reads your message.** Telegram only counts a message as delivered
once a program asks for the *next* one, so the doorbell peeks without ever
confirming. The real TARS receives that exact message himself the moment he's
awake, and answers it properly. Nothing is forwarded and nothing is lost.

That also means the PC's dashboard stays locked to the PC itself. Opening it
up to the WiFi would have exposed your school password to anyone on the
network.

---

## Before you start: use Sleep, not Shut Down

**This matters more than anything else on this page.**

- **Sleep** → the PC wakes in about 3 seconds, still logged in, with TARS
  already running in memory. He answers almost immediately.
- **Shut Down** → the PC boots to the lock screen, and *TARS cannot start
  until someone logs in*. The doorbell will wake the machine, but he'll sit
  at the login screen until you get home.

There is a way around that (Windows auto-login), but it means storing your
Windows password in the registry in a form other programs can read, and
anyone who walks up to your PC is straight in. That's your call to make, not
mine — I haven't set it up.

So: **Start → Power → Sleep**, not Shut Down.

---

## What you need

- An old Android phone (any age — it's doing almost nothing)
- Your home WiFi
- A charger

---

## Setup

### 1. Install Termux on the phone

Get it from **F-Droid**, not the Play Store — the Play Store copy is
abandoned and won't install packages.

1. On the phone, go to `f-droid.org` and install F-Droid.
2. Open F-Droid, search **Termux**, install it.

### 2. Install Python and fetch the doorbell

Open Termux and type these two lines:

```bash
pkg install python -y
curl -O https://raw.githubusercontent.com/hazbitgamer-commits/TARS/main/doorbell.py
```

### 3. Stop Android killing it

Android puts sleeping apps to death. Two things prevent that:

```bash
termux-wake-lock
```

Then in Android **Settings → Apps → Termux → Battery**, set it to
**Unrestricted**. Without this the doorbell dies overnight and you'll think
it's broken.

### 4. Start it

```bash
python doorbell.py
```

It asks four questions, once:

| Question | Your answer |
|---|---|
| Telegram bot token | The same one the PC uses (it's in `tars/.env`) |
| PC's ethernet address | `9C-6B-00-E3-8B-50` |
| PC's network address | `192.168.4.45` |
| Broadcast address | Just press Enter — it works it out |

Then leave it running and put the phone on the charger, on WiFi.

---

## Testing it

1. Put the PC to sleep (**Start → Power → Sleep**).
2. From your own phone, text TARS anything.
3. You should get *"PC's asleep — I'm waking him now"* within seconds.
4. About 5 seconds later, TARS answers the original message himself.

If the PC doesn't wake, it's almost always one of these:

- **The phone isn't on the same WiFi as the PC.** Magic packets don't leave
  your home network — that's why the doorbell has to be at home, and why it
  works when *you're* anywhere in the world.
- **The PC is off at the wall.** Wake-on-LAN needs the network card to keep
  a trickle of power.
- **Wake-on-LAN is off in the BIOS.** It's already enabled in Windows on your
  machine (I checked), but some motherboards have a second switch in the BIOS
  under "Power Management" — look for *Wake on LAN* or *Power On by PCI-E*.

---

## If the phone dies or you unplug it

Nothing breaks. The doorbell is a convenience layer — TARS on the PC doesn't
know or care whether it exists. Plug the phone back in, run
`python doorbell.py`, and it picks up where it left off.

---

## One honest limitation

If the PC is **off at the wall**, or the power's out, or the phone is off the
WiFi, there's no doorbell to ring. Nothing running on a phone can fix a PC
with no electricity.
