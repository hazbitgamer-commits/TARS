"""'Run a self check' / 'are you healthy' / 'fix yourself' — TARS examines
his own organs (parts, models, thinking engine, microphone, speakers, big
brain, disk), repairs what he can, and says the rest in plain English."""
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BASE))

DESCRIPTION = ("TARS checks HIMSELF for problems and fixes what he can — "
               "'run a self check', 'are you healthy', 'diagnose yourself', "
               "'fix yourself', 'what's wrong with you'. Covers his parts, "
               "AI models, microphone, speakers, big brain and disk space. "
               "NOT for the PC's health (pc_health) and NOT for his "
               "self-improvement agent (improve).")
ARGS = {"fix": "'true' (default) to repair what he can, 'false' to only look"}


def run(args: dict) -> str:
    import doctor

    fix = str(args.get("fix", "true")).lower() not in ("false", "no", "0")
    problems, fixed = doctor.run_checks(fix=fix)
    return doctor.spoken_summary(problems, fixed)
