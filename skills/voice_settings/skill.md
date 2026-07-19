# voice_settings
Changes TARS's own text-to-speech voice (accent/gender) and talking speed.
Saved in voice_settings.json (project root), applied live immediately and
re-applied on startup by tts.py.

**Say:** "sound like an American male" / "talk faster" / "set your speed to 20"
/ "what voice are you using" / "list voices"

**Args:** `voice` (name/description or 'list'), `rate` (+N/-N/absolute percent
or 'get').

Different from:
- `voice_output` — which PC speaker/device TARS's voice plays through.
- `personality` — humor/sarcasm/honesty character traits, not the voice itself.
