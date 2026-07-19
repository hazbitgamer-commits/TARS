# github_upload

Actually uploads (pushes) a local folder to a GitHub repository, by running
the real git commands: `git init`, `add`, `commit`, and `push`. This is
different from the older `github_export` skill, which only makes a clean
local copy and refuses to upload anything.

**Say:** "upload this folder to GitHub" / "push my project to
github.com/yourname/yourrepo" / "commit and upload my changes"

**Args:**
- `folder` -- path of the local folder to upload. Leave blank to use the
  `workshop` folder.
- `repo_url` -- the GitHub repo web address to push to, e.g.
  `https://github.com/yourname/yourrepo.git`. Required -- Jacob must have
  already created this repo on GitHub's website.
- `message` -- optional short commit message. Defaults to "Update from TARS".

**How auth works:** this skill never handles GitHub passwords or tokens
itself. It just runs plain `git push`. If this PC isn't already signed in
to GitHub, Windows/Git will pop up a browser login window for Jacob to
complete -- that's expected.

**Safety:** only adds/commits/pushes inside the one folder given -- never
deletes files, never touches anything outside that folder, never spends
money, never sends emails or messages.
