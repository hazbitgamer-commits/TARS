"""Explains, out loud, how TARS teaches itself new skills.

This is a meta skill: it doesn't DO anything on the PC, it just describes
the same process that was used to create it. Kept purely informational —
no files touched, nothing installed, nothing sent anywhere.
"""

DESCRIPTION = ("Explain HOW TARS learns / teaches itself new skills or abilities. "
               "Use for questions like 'how do you learn new things', 'how do you "
               "teach yourself a skill', 'walk me through how you learn'. "
               "NOT for teaching a specific new skill — just explains the process.")
ARGS = {"detail": "'short' for a one-line answer (default), or 'long' for the full step-by-step version"}

_SHORT = ("When you ask me for something no skill covers, Claude writes a small "
          "skill dot py and skill dot md file matching my existing skills, tests it "
          "live, and I hot load it immediately, no restart needed.")

_LONG = ("Here's how it works. First, you ask for something and my intent router "
         "finds no existing skill matches it. Second, Claude looks at an existing "
         "skill as a template, then writes a new folder with a skill dot py, which "
         "declares a description, its arguments, and a run function, plus a skill "
         "dot md file explaining it in plain English. Third, Claude tests the new "
         "skill directly with the runtime Python interpreter and fixes it until it "
         "works. Finally, since I hot load skills from disk, the new ability is "
         "available right away, no restart needed.")


def run(args: dict) -> str:
    detail = str(args.get("detail", "short")).strip().lower()
    if detail == "long":
        return _LONG
    return _SHORT
