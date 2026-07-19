"""Upload a single file to a dedicated GitHub repo so Jacob can grab it
from any other computer later, just by telling TARS the file name.

Different from the existing github_upload skill (which pushes a whole
folder and needs the GitHub repo web address repeated on every single
call) and github_export (which only copies files locally and never
uploads anything): this skill is built for Jacob's actual ask -- "tell
you which file ... and you do it automatically". It keeps one small
dropbox-style folder (workshop/github_files/) as its own git repo, copies
just the one named file into it, and pushes. The GitHub repo address only
has to be given once -- after that it's remembered in
workshop/github_files/.repo_url.txt and every future upload just needs a
file name.

Safety (matches TARS's hard rules):
  - Only ever creates/modifies files inside workshop/github_files/ --
    never deletes anything, never touches files outside that folder.
  - Doesn't spend any money -- GitHub pushes are free.
  - Doesn't send any email or message -- pushing a file to a repo Jacob
    owns is neither.
  - Auth is handled entirely by git/Windows itself (same as
    github_upload). If this PC isn't already signed in to GitHub, git
    will pop up a login window for Jacob -- that's expected and not
    something this skill does on his behalf.
"""
import shutil
import subprocess
from pathlib import Path

DESCRIPTION = ("Upload ONE specific file to GitHub automatically so Jacob "
               "can download it later from any other computer, just by "
               "naming the file. E.g. 'upload countdown.py to GitHub', "
               "'send my notes file to GitHub so I can get it on my "
               "laptop'. Remembers the GitHub repo address after the "
               "first use, so Jacob doesn't have to repeat it every time. "
               "NOT for pushing a whole project folder (that's the "
               "github_upload skill) and NOT for just making a local copy "
               "without uploading anywhere (that's github_export).")
ARGS = {
    "file": "name or path of the single file to upload, e.g. countdown.py",
    "repo_url": "GitHub repo web address, e.g. https://github.com/yourname/yourrepo.git -- only needed the first time, then it's remembered",
    "note": "optional short note about the file, used as the commit message",
}

WORKSHOP = Path(r"C:\Users\hazbi\Projects\tars\workshop")
DROPBOX = WORKSHOP / "github_files"
REPO_URL_FILE = DROPBOX / ".repo_url.txt"
GIT_TIMEOUT = 25  # seconds -- long enough for a normal push, short enough not to hang forever


def _run(cmd, cwd):
    return subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True,
                           timeout=GIT_TIMEOUT)


def _find_file(name: str):
    """Look for the file: as given, then inside the workshop folder, then
    anywhere under the workshop folder by that exact name."""
    p = Path(name)
    if p.is_absolute() and p.exists():
        return p
    candidate = WORKSHOP / name
    if candidate.exists():
        return candidate
    matches = list(WORKSHOP.rglob(name))
    return matches[0] if matches else None


def run(args: dict) -> str:
    file_arg = str(args.get("file") or "").strip().strip('"')
    if not file_arg:
        return "Tell me which file to upload, and I'll send it to GitHub."

    src = _find_file(file_arg)
    if src is None or not src.is_file():
        return f"I can't find a file called {file_arg} in the workshop folder."

    DROPBOX.mkdir(parents=True, exist_ok=True)

    repo_url = str(args.get("repo_url") or "").strip().strip('"')
    if not repo_url and REPO_URL_FILE.exists():
        repo_url = REPO_URL_FILE.read_text(encoding="utf-8").strip()
    if not repo_url:
        return ("I need the GitHub repo web address the first time -- "
                "something like https://github.com/yourname/yourrepo.git "
                "-- tell me that along with the file and I'll remember it "
                "for every upload after this.")

    note = str(args.get("note") or f"Add {src.name} via TARS").strip()

    try:
        if not (DROPBOX / ".git").exists():
            _run(["git", "init"], DROPBOX)
            _run(["git", "branch", "-M", "main"], DROPBOX)

        shutil.copy2(src, DROPBOX / src.name)
        REPO_URL_FILE.write_text(repo_url, encoding="utf-8")

        remotes = _run(["git", "remote"], DROPBOX).stdout.split()
        if "origin" in remotes:
            _run(["git", "remote", "set-url", "origin", repo_url], DROPBOX)
        else:
            _run(["git", "remote", "add", "origin", repo_url], DROPBOX)

        _run(["git", "add", src.name], DROPBOX)
        _run(["git", "commit", "-m", note], DROPBOX)  # no-op if nothing changed
        push = _run(["git", "push", "-u", "origin", "main"], DROPBOX)
    except subprocess.TimeoutExpired:
        return ("That's taking a while -- GitHub may have opened a login "
                "window for you. Finish signing in, then ask me to upload "
                "again.")
    except FileNotFoundError:
        return "Git isn't installed on this PC, so I can't upload to GitHub."

    if push.returncode == 0:
        return (f"Done -- {src.name} is uploaded to GitHub, so you can "
                f"download it from any computer now.")
    return ("The upload didn't go through. Make sure the repo address is "
            "right and that you're logged into GitHub on this PC, then "
            "ask me to try again.")
