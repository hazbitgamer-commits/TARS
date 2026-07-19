# vacuum
eufy robot vacuum over eufy's cloud MQTT (vendored jeppesens/eufy-clean api in eufy_lib/). Needs EUFY_EMAIL + EUFY_PASSWORD in .env (Jacob adds these himself). Cleaning blocked during quiet hours unless override.
**Say:** "start the vacuum" / "send the vacuum home" / "pause the vacuum" / "is the vacuum connected"
**Args:** `action` — clean/pause/resume/dock/status; `override`.
