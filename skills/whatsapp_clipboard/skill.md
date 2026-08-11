# whatsapp_clipboard

Stages a WhatsApp message for the owner to send himself. Copies the given text onto
his clipboard (via `pyperclip`) and opens WhatsApp Web, so he just pastes and
hits send. Never sends anything on its own.

This is the follow-through for TARS's hard "I can't send messages" rule: when
the owner asks TARS to WhatsApp someone, TARS offers this instead, and a "yes"
runs this skill.

## Examples
- (after TARS offers) "yes" / "yeah, do that"

## Notes
- Triggered by `brain.py`'s hard block on send/text/whatsapp/dm requests — not
  usually invoked directly.
- If no text is given, it just opens WhatsApp with whatever's already on the
  clipboard.
- Uses `pyperclip`, already installed in the TARS runtime.
