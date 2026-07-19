import webbrowser

DESCRIPTION = ("Open the TARS dashboard home page in the browser — status, timers, "
               "personality sliders, activity, skills, brain stats.")
ARGS = {}


def run(args: dict) -> str:
    webbrowser.open("http://127.0.0.1:8765")
    return "Dashboard's up."
