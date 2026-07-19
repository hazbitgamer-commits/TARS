"""Package the non-personal parts of TARS -- the engine code, skills, and
dashboard UI -- into a clean folder Jacob can upload to GitHub himself.

TARS never uploads or pushes anything anywhere (that would break the
"never send messages" hard rule) -- this only COPIES files, locally, into
workshop/github_export/. Jacob still has to drag that folder onto GitHub.

What gets copied (the code / design -- "TARS as an AI"):
  - the root *.py engine files (brain.py, neuro.py, skills_engine.py, ...)
  - skills/**/skill.py and skill.md -- every skill's code + description
  - dashboard/*.html, *.js, *.css -- the HUD UI
  - README.md, with any personal email address blanked out

What's deliberately left out (personal / private / not really "design"):
  - vault/, vault_quarantine/, faces/, logs/ -- Jacob's actual memories,
    conversations, and photos
  - brain_neurons.json, brain_synapses.json, brain_vectors.npy,
    brain_activity.jsonl -- the LEARNED memory data (not the design itself)
  - .env, google_credentials.json, google_token.json, ca_bundle.pem,
    settings.json, *_state.json, timers.json, etc -- secrets/tokens/state
  - runtime/, models/, wakeword/ model files -- huge binaries, not source
"""
import re
import shutil
from pathlib import Path

DESCRIPTION = ("Package the non-personal, code-only parts of TARS -- the "
               "brain/engine code, every skill, and the dashboard UI -- into "
               "a clean folder ready for Jacob to upload to GitHub himself. "
               "Leaves out anything personal: the vault, faces, logs, "
               "conversation memory, learned brain data, and all "
               "credentials/tokens. E.g. 'which part of you can I upload to "
               "GitHub', 'package your brain design for GitHub', 'make me a "
               "GitHub-ready copy of yourself'. NOT for actually uploading or "
               "pushing anywhere -- TARS never sends files anywhere; this "
               "only prepares a local folder.")
ARGS = {}

TARS_ROOT = Path(__file__).resolve().parents[2]
DEST = TARS_ROOT / "workshop" / "github_export"

ROOT_PY_FILES = [
    "agents.py", "announce.py", "audio_out.py", "brain.py", "dashboard.py",
    "eufy_vac.py", "faces.py", "google_auth.py", "main.py", "neuro.py",
    "quiet.py", "skills_engine.py", "stt.py", "timers_watch.py", "topics.py",
    "tts.py", "ui.py",
]
DASHBOARD_EXTS = {".html", ".js", ".css"}
EMAIL_RE = re.compile(r"[\w.+-]+@[\w.-]+\.\w+")

EXPORT_NOTES = """This folder was auto-packaged by TARS's github_export skill.

Included: the engine code (brain.py, neuro.py, skills_engine.py, main.py,
and friends), every skill in skills/, and the dashboard HTML/JS/CSS --
the actual design of TARS as an AI.

Left out on purpose: the vault (Jacob's memories/notes), faces, logs,
conversation transcripts, the learned brain data files (brain_neurons.json,
brain_synapses.json, brain_vectors.npy, brain_activity.jsonl), and every
credential/token/settings file (.env, google_credentials.json,
google_token.json, settings.json, etc). None of that belongs on a public
GitHub repo.

Nothing was uploaded anywhere -- this is just a clean local copy. Jacob,
drag this folder into a new GitHub repo yourself when you're ready.
"""


def _copy_skills(skills_src: Path, skills_dst: Path) -> int:
    count = 0
    for skill_py in sorted(skills_src.glob("*/skill.py")):
        skill_dir = skill_py.parent
        if skill_dir.name == "github_export":
            continue  # this skill copying itself would be silly
        out_dir = skills_dst / skill_dir.name
        out_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(skill_py, out_dir / "skill.py")
        skill_md = skill_dir / "skill.md"
        if skill_md.exists():
            shutil.copy2(skill_md, out_dir / "skill.md")
        count += 1
    return count


def run(args: dict) -> str:
    if DEST.exists():
        shutil.rmtree(DEST)
    DEST.mkdir(parents=True)

    copied_root = 0
    for name in ROOT_PY_FILES:
        src = TARS_ROOT / name
        if src.exists():
            shutil.copy2(src, DEST / name)
            copied_root += 1

    skills_count = 0
    skills_src = TARS_ROOT / "skills"
    if skills_src.exists():
        skills_count = _copy_skills(skills_src, DEST / "skills")

    dashboard_count = 0
    dash_src = TARS_ROOT / "dashboard"
    if dash_src.exists():
        dash_dst = DEST / "dashboard"
        dash_dst.mkdir(exist_ok=True)
        for f in dash_src.iterdir():
            if f.is_file() and f.suffix.lower() in DASHBOARD_EXTS:
                shutil.copy2(f, dash_dst / f.name)
                dashboard_count += 1

    readme_src = TARS_ROOT / "README.md"
    if readme_src.exists():
        text = readme_src.read_text(encoding="utf-8")
        text = EMAIL_RE.sub("[personal email removed]", text)
        (DEST / "README.md").write_text(text, encoding="utf-8")

    (DEST / "EXPORT_NOTES.md").write_text(EXPORT_NOTES, encoding="utf-8")

    return (f"Packaged {copied_root} core brain files, {skills_count} skills, "
            f"and the dashboard UI into the workshop folder, under "
            f"github export -- nothing personal, ready for you to upload "
            f"to GitHub.")
