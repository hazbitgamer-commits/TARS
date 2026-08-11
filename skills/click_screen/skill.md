# click_screen
Vision-guided clicking: describes-in-words → qwen2.5vl finds coordinates → pyautogui clicks. Scaled 1280w view, coords mapped back to real screen + monitor offset.
**Say:** "click the first video" / "press the play button" / "double click the file"
**Args:** `target`; `monitor` — main/left; `double`.
If nothing meets the confident-match bar, a looser accessibility-tree pass looks for a near-miss and circles it (no click) so the owner can still see where it is, instead of a flat "can't see it".
