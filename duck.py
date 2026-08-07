"""Volume ducking: other apps (games, music, YouTube) dip to a quarter of
their volume while TARS speaks, then come right back — so Jacob never
misses a reply mid-game. Used by tts.Speaker around every playback."""
import os

_ducked: dict[int, tuple] = {}


def duck(factor: float = 0.25) -> None:
    global _ducked
    if _ducked:  # already ducked (nested speech) — leave originals alone
        return
    try:
        import comtypes

        try:
            comtypes.CoInitialize()
        except OSError:
            pass
        from pycaw.pycaw import AudioUtilities

        me = os.getpid()
        for session in AudioUtilities.GetAllSessions():
            try:
                if not session.Process or session.Process.pid == me:
                    continue  # never duck TARS's own voice
                vol = session.SimpleAudioVolume
                current = vol.GetMasterVolume()
                if current > 0.05:
                    _ducked[session.Process.pid] = (vol, current)
                    vol.SetMasterVolume(current * factor, None)
            except Exception:
                continue
    except Exception:
        _ducked = {}


def restore() -> None:
    global _ducked
    for vol, original in _ducked.values():
        try:
            vol.SetMasterVolume(original, None)
        except Exception:
            continue
    _ducked = {}
