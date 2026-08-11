# github_file

Uploads ONE file the owner names to a GitHub repo automatically, so he can
download it again later from any other computer. This is the skill for
"grab me this file, put it on GitHub" -- give it a file name (and, the very
first time, a repo web address) and it does the rest: copies the file into
its own small folder, `workshop/github_files/`, and runs the real git
commands (`init`, `add`, `commit`, `push`) to send it to GitHub.

After the first upload, the repo address is remembered in
`workshop/github_files/.repo_url.txt`, so every upload after that just
needs a file name -- no need to repeat the GitHub address.

**How this is different from the other GitHub skills:**
- `github_upload` pushes a whole folder and needs the repo address every
  single time.
- `github_export` only makes a clean local copy and never uploads
  anywhere.
- `github_file` (this one) is for a single file at a time, remembers the
  repo address, and is what the owner asked for: "tell you which file ... and
  you do it automatically."

**Say:** "upload countdown.py to GitHub" / "send my notes file to GitHub
so I can get it on my laptop" / "put brain_specs.txt on GitHub"

**Args:**
- `file` -- name or path of the file to upload, e.g. `countdown.py`. TARS
  looks for it in the workshop folder if just a name is given.
- `repo_url` -- the GitHub repo web address to use, e.g.
  `https://github.com/yourname/yourrepo.git`. Only needed the first time;
  after that TARS remembers it.
- `note` -- optional short note about the file, used as the commit
  message.

**How auth works:** same as `github_upload` -- this skill never handles
GitHub passwords or tokens itself, it just runs plain `git push`. If this
PC isn't already signed in to GitHub, Windows/Git will pop up a browser
login window for the owner to complete.

**How to download a file later, from any computer:** open the GitHub repo
in a browser (the address the owner gave the first time), find the file in the
file list, and click "Download" (or open it and use the "Raw" button).

**Safety:** only ever creates/changes files inside
`workshop/github_files/` -- never deletes anything, never touches files
outside that folder, never spends money, never sends emails or messages.
Requires a repo the owner already owns on GitHub (this skill does not create
GitHub repos -- see `create_github_repo.py` in the workshop folder for a
guided lesson on making one).
