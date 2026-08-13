# send_screenshot
Takes a screenshot and sends it to the owner's phone as a photo, over the existing Telegram bridge (`tars_phone.send_photo`). Also saves a copy to Pictures\TARS, same as the plain `screenshot` skill.

**Say:** "take a screenshot of my left screen and show me it", "send me a screenshot", "show me what's on my screen right now", "send a photo of both my screens to my phone"

**Args:**
- `which`: "left", "right", "main"/"primary" (default), or "all" for every monitor combined into one image.

**Requires:** the phone bridge already set up and paired (see the `phone` skill). If it isn't, this skill still saves the screenshot locally and tells the owner how to pair.
