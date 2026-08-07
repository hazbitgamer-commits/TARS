"""Quick random decision helper for when Jacob says things like 'I'm not sure'."""
import random
import re

DESCRIPTION = ("Helps Jacob make a quick decision when he's unsure — flips a coin, rolls a "
               "die, gives a magic-8-ball style yes/no answer, or randomly picks one option "
               "from a list he names. E.g. 'flip a coin', 'I'm not too sure', 'roll a die', "
               "'should I go for a walk', 'pick one: pizza or tacos'. NOT for anything needing "
               "real facts, research, or math — just quick random decisions.")
ARGS = {"mode": "'coin', 'dice', 'yesno' (magic 8-ball style), or 'choice' to pick from options. "
                 "Leave blank if unclear.",
        "options": "comma or 'or'-separated list of choices, only used for mode 'choice'"}

EIGHT_BALL = [
    "Yes, definitely.", "It is certain.", "Without a doubt, yes.",
    "Most likely.", "Signs point to yes.", "Ask again later.",
    "Cannot predict that right now.", "Don't count on it.",
    "My sources say no.", "Very doubtful.", "No.",
]


def run(args: dict) -> str:
    mode = str(args.get("mode", "")).strip().lower()
    options_raw = str(args.get("options", "")).strip()

    if not mode:
        mode = "choice" if options_raw else "yesno"

    if mode in ("coin", "flip", "coinflip"):
        return f"{random.choice(['Heads', 'Tails'])}."

    if mode in ("dice", "die", "roll"):
        return f"You rolled a {random.randint(1, 6)}."

    if mode in ("choice", "pick", "choose") or options_raw:
        parts = [p.strip() for p in re.split(r",|\bor\b", options_raw) if p.strip()]
        if len(parts) < 2:
            return "Give me at least two options to choose between."
        return f"I'd go with {random.choice(parts)}."

    return random.choice(EIGHT_BALL)
