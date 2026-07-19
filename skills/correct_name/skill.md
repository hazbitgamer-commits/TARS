# correct_name
Fuzzy find-and-replace for a name/word across the whole memory vault (vault/). Matches loosely (difflib similarity ≥ 0.6) so it still works when speech-to-text spelled the same name differently in different notes. Updates matching text inside every note and renames any note file whose title matches the old name.
**Say:** "change Luka Kapilovic to Luka Pavlovic" / "correct John Smith to Jon Smith"
**Args:** `old` — current/misspelled name; `new` — corrected name.
