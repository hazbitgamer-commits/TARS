"""Actually push a local folder of files up to a GitHub repository.

Unlike the github_export skill (which only COPIES/packages files locally and
deliberately refuses to upload anything), this skill runs the real git
commands: init, add, commit, and push. Jacob has to give it a repo web
address to push to.

Safety:
  - Never deletes anything -- only adds/commits/pushes.
  - Never touches files outside the one folder it's pointed at.
  - Doesn't spend any money (git/GitHub pushes are free) and doesn't send
    any emails or messages -- pushing code to a repo you own is neither.
  - Auth is handled entirely by git/Windows itself. If this PC isn't
    already signed in to GitHub, a browser window pops up for Jacob to log
    in -- that's normal, expected, and not something this skill can (or
    should) do on his behalf.
"""
import subprocess
from pathlib import Path

DESCRIPTION = ("Actually upload/push a local folder of files to a GitHub "
               "repository, by running git init/add/commit/push. E.g. "
               "'upload this folder to GitHub', 'push my project to "
               "github.com/jacob/myrepo', 'commit and upload my changes'. "
               "Needs a repo web address to push to. NOT for just making a "
               "clean local copy without uploading -- that's the "
               "github_export skill.")
ARGS = {
    "folder": "path of the local folder to upload; leave blank for the workshop folder",
    "repo_url": "the GitHub repo web address to push to, e.g. https://github.com/yourname/yourrepo.git",
    "message": "optional short commit message describing what changed",
}

DEFAULT_FOLDER = Path(r"C:\Users\hazbi\Projects\tars\workshop")
GIT_TIMEOUT = 25  # seconds -- long enough for a normal push, short enough not to hang forever


def _run(cmd, cwd):
    return subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True,
                           timeout=GIT_TIMEOUT)


def run(args: dict) -> str:
    folder = str(args.get("folder") or DEFAULT_FOLDER).strip().strip('"')
    repo_url = str(args.get("repo_url") or "").strip().strip('"')
    message = str(args.get("message") or "Update from TARS").strip()

    folder_path = Path(folder)
    if not folder_path.exists() or not folder_path.is_dir():
        return f"I can't find a folder at {folder}, so I didn't upload anything."

    if not repo_url:
        return ("I need the GitHub repo web address to upload to, something "
                "like https://github.com/yourname/yourrepo.git -- tell me "
                "that and I'll push the files.")

    try:
        if not (folder_path / ".git").exists():
            _run(["git", "init"], folder_path)

        _run(["git", "add", "-A"], folder_path)
        _run(["git", "commit", "-m", message], folder_path)  # no-op if nothing changed
        _run(["git", "branch", "-M", "main"], folder_path)

        remotes = _run(["git", "remote"], folder_path).stdout.split()
        if "origin" in remotes:
            _run(["git", "remote", "set-url", "origin", repo_url], folder_path)
        else:
            _run(["git", "remote", "add", "origin", repo_url], folder_path)

        push = _run(["git", "push", "-u", "origin", "main"], folder_path)
    except subprocess.TimeoutExpired:
        return ("The upload is taking a while -- GitHub may have opened a "
                "browser window for you to log in. Finish that, then ask "
                "me to upload again.")
    except FileNotFoundError:
        return "Git isn't installed on this PC, so I can't upload to GitHub."

    if push.returncode == 0:
        return f"Done -- {folder_path.name} is uploaded to GitHub."
    return ("The upload didn't go through. Double check the repo address "
            "and that you're logged into GitHub on this PC, then ask me to "
            "try again.")
