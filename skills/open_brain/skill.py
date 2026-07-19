import webbrowser

DESCRIPTION = "Open the 3D neuron brain page in the browser — live firing, learned synapses."
ARGS = {}


def run(args: dict) -> str:
    webbrowser.open("http://127.0.0.1:8765/brain")
    return "Brain's on screen. Try not to poke it."
