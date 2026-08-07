# learning_status

Reports what new skill(s) TARS has most recently taught himself — the actual
finished skills (each `skills/<name>/skill.py`), newest first, based on when
the file was written.

This powers the "Learning" card on the dashboard, and also answers it out
loud if Jacob asks.

**Say:** "what are you currently learning" / "what's the newest skill you've
taught yourself" / "what have you learned lately"

**Args:** `count` — how many recently learned skills to mention (default 1,
max 5).

**Not the same as:**
- `improve` (Kipp) — Kipp's queue of *planned* upgrades to TARS's existing
  core code. This skill only reports finished, already-learned skills.
- `how_i_learn` — explains the general process TARS uses to teach himself,
  not what has actually been learned recently.
