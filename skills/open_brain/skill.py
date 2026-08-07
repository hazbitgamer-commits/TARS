import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

DESCRIPTION = "Open the neuron brain page in its own TARS window — live firing, learned synapses."
ARGS = {}


def run(args: dict) -> str:
    import tars_window

    tars_window.open_page("brain", 1300, 850)
    return "Brain's on screen. Try not to poke it."
