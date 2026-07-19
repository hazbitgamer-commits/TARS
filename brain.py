"""TARS's brain, Phase 1: local Ollama chat with the personality system.

Later phases add: intent routing, skills, Claude escalation for hard tasks.
"""
import datetime
import json
import subprocess
import threading
import time
from pathlib import Path

import requests

OLLAMA_URL = "http://127.0.0.1:11434/api/chat"
MODEL = "qwen2.5:7b"        # conversation
ROUTER_MODEL = "qwen2.5:7b-router"  # same weights, separate instance: router and
# chat each keep their own prompt cache (sharing one instance doubled latency)
KEEP_ALIVE = "2h"  # keep models loaded in memory between commands
HISTORY_TURNS = 10  # remembered exchanges within a session


class Brain:
    def __init__(self, base: Path):
        self.base = base
        self.settings_path = base / "settings.json"
        self.history: list[dict] = []
        self.pending_delete: str | None = None
        self.pending_learn: str | None = None
        self.pending_quiet: tuple[float, str, dict] | None = None  # (t, skill, args)
        from skills_engine import SkillBox

        self.skills = SkillBox(base)

    LEARN_RESPONSES = (
        "I don't know how to do that yet — so I'm teaching myself right now. "
        "Give me a few minutes; I'll tell you when I've got it."
    )

    def _learning_task(self, request: str) -> str:
        skills_dir = self.base / "skills"
        runtime_py = self.base / "runtime" / "python.exe"
        example = (skills_dir / "volume" / "skill.py").read_text(encoding="utf-8")
        return (
            f"TEACH YOURSELF A NEW SKILL. Jacob asked TARS: {request!r} and no "
            f"existing skill covers it.\n"
            f"Create a new folder {skills_dir}\\<short_snake_name>\\ containing "
            f"skill.py and skill.md. skill.py MUST define: DESCRIPTION (one-line "
            f"string for the intent router), ARGS (dict of argument name -> "
            f"plain-English meaning), and run(args: dict) -> str returning one "
            f"short spoken sentence. Study this existing skill as the exact "
            f"pattern:\n---\n{example}\n---\n"
            f"Use the standard library or packages already in the runtime; if a "
            f"new package is genuinely needed, install it with: \"{runtime_py}\" "
            f"-m pip install <package>\n"
            f"The new skill must respect the hard rules (no deleting outside the "
            f"tars folder, no spending, no sending messages).\n"
            f"TEST it: import the module with \"{runtime_py}\" and call run() "
            f"with safe arguments; fix it until it works. TARS hot-loads skills, "
            f"so no restart is needed.\n"
            f"In SPOKEN, say what you taught yourself and give the exact phrase "
            f"Jacob should say to use it."
        )

    def handle(self, text: str) -> str:
        """Route to a skill or chat — whole reply at once (tests, dashboard)."""
        routed = self._handle_routed(text)
        return routed if routed is not None else self.reply(text)

    def handle_stream(self, text: str):
        """Like handle(), but chat replies stream out sentence by sentence,
        so TARS starts talking while still thinking."""
        routed = self._handle_routed(text)
        if routed is not None:
            yield routed
            return
        yield from self.reply_stream(text)

    def _handle_routed(self, text: str) -> str | None:
        """All routing/gates/skills. Returns None when it's conversation."""
        lowered = text.lower()

        # a deletion is waiting on Jacob's yes/no
        if self.pending_delete:
            target = self.pending_delete
            self.pending_delete = None  # one shot — anything but yes cancels
            if lowered.strip().startswith(("yes", "yeah", "yep", "confirm")):
                result = self.skills.run(
                    "delete_files", {"target": target, "confirmed": "true"})
                self.history += [{"role": "user", "content": text},
                                 {"role": "assistant", "content": result}]
                self._journal(f"delete_files (confirmed): {result[:100]}")
                return result
            if lowered.strip().startswith(("no", "nah", "cancel", "don't", "dont")):
                return "Cancelled. Nothing deleted."
            # otherwise treat it as a normal command; the pending delete is dropped

        # bare "override quiet hours" re-runs whatever quiet hours just blocked.
        # Whisper mangles "override" ("or write", "all right", "live a ride"...),
        # so right after a block, any short non-question mention of quiet hours
        # counts as the override.
        if self.pending_quiet and time.time() - self.pending_quiet[0] < 120:
            sounds_like_override = "override" in lowered or (
                "quiet" in lowered and len(text) < 60
                and not any(q in lowered for q in
                            ("what", "when", "why", "how", "change", "set",
                             "remove", "are ", "?")))
            if sounds_like_override:
                _, name, args = self.pending_quiet
                self.pending_quiet = None
                args["override"] = "true"
                result = self.skills.run(name, args) or "That didn't work this time."
                self.history += [{"role": "user", "content": text},
                                 {"role": "assistant", "content": result}]
                self._journal(f"{name} (override): {result[:100]}")
                return result

        # a proposed self-teaching is waiting on Jacob's yes/no
        if self.pending_learn:
            request = self.pending_learn
            self.pending_learn = None
            if lowered.strip().startswith(("yes", "yeah", "yep", "sure", "go ahead", "do it")):
                self.skills.run("deep_task", {"task": self._learning_task(request)})
                self.history += [{"role": "user", "content": text},
                                 {"role": "assistant", "content": self.LEARN_RESPONSES}]
                return self.LEARN_RESPONSES
            if lowered.strip().startswith(("no", "nah", "cancel", "don't", "dont")):
                return "Fair enough, skipping it."
            # anything else: drop the proposal and handle this as a fresh command

        route = self._route(text)
        name = route.get("skill", "chat")

        # the router sometimes invents plausible skill names that don't exist —
        # a question falls back to chat, an action request becomes a proposal
        # to self-teach (with Jacob's yes/no)
        real = {s["skill"] for s in self.skills.catalog()}
        known = real | {"chat", "new_skill", "misheard"}
        if name not in known:
            # "volume_control" obviously means "volume" — snap when unambiguous
            close = {k for k in real if k in str(name) or str(name) in k}
            first_word = lowered.split()[0] if lowered.split() else ""
            if len(close) == 1:
                name = close.pop()
            elif first_word in ("how", "what", "why", "where", "when", "who",
                                "can", "could", "do", "does", "is", "are",
                                "should", "whats"):
                name = "chat"
            else:
                name = "new_skill"
                route["args"] = {"request": text}

        if name == "misheard":
            reply = f"I think I misheard you — I got: {text}. One more time?"
            self.history += [{"role": "user", "content": text},
                             {"role": "assistant", "content": reply}]
            return reply
        if name == "new_skill":
            # mishearings kept triggering expensive learning runs — confirm first
            request = (route.get("args") or {}).get("request") or text
            self.pending_learn = request
            reply = (f"I don't have a skill for that. Want me to teach myself "
                     f"to {request}? Say yes and I'll get to work.")
            self.history += [{"role": "user", "content": text},
                             {"role": "assistant", "content": reply}]
            return reply
        # hard gates: dangerous or noisy skills need the trigger word actually
        # said — the router alone has let garbled speech through before
        if name == "run_command" and "run " not in lowered and "command" not in lowered:
            name = "chat"
        if name == "type_text" and "type" not in lowered:
            name = "chat"
        # "learn how to X" / "teach yourself X" is ALWAYS a self-teaching
        # request — mentioning a device (camera, screen...) in the request must
        # not open that device instead
        if any(p in lowered for p in ("learn how", "learn to", "teach yourself",
                                      "teach you to")) and \
                name in ("camera", "camera_feed", "open_app", "browser_search",
                         "look_at_screen", "face_who", "face_learn"):
            name = "new_skill"
            route["args"] = {"request": text}
        # the webcam only ever activates when Jacob names it (his rule);
        # face skills count as explicit — they only make sense about someone
        # visibly in front of the lens
        if name in ("camera", "camera_feed") and \
                "camera" not in lowered and "webcam" not in lowered:
            name = "chat"
        if name in ("face_learn", "face_who") and not any(
                w in lowered for w in ("camera", "webcam", "person", "face",
                                       "this is", "who")):
            name = "chat"
        # bare "access/open my camera" means the LIVE FEED; an actual QUESTION
        # about the camera means a snapshot + spoken answer — whichever way the
        # router leaned, the words decide
        if name == "camera_feed" and any(w in lowered for w in
                ("what", "describe", "tell me", "who", "read", "how do i look")):
            name = "camera"
            route["args"] = {"question": text}
        elif name == "camera" and not any(w in lowered for w in
                ("what", "how", "tell", "describe", "see", "hold", "read",
                 "who", "look at", "check")):
            name = "camera_feed"
            route["args"] = {}
        # "delete ..." must never fall into search/typing/shell skills
        if "delete" in lowered and name in ("search_files", "type_text",
                                            "keyboard", "run_command", "open_app"):
            name = "delete_files"
            route["args"] = {"target": text}
        # rambling must never clear the desktop — that action needs its words
        if (name == "manage_window"
                and (route.get("args") or {}).get("action") == "minimize_all"
                and not any(w in lowered for w in ("minimize", "desktop", "hide"))):
            name = "chat"
        if name and name != "chat":
            try:
                result = self.skills.run(name, route.get("args"))
            except Exception as e:
                return f"That skill misfired: {e}"
            if result is not None:
                if result.startswith("__CONFIRM__"):  # delete_files wants a yes
                    _, target, message = result.split("__", 3)[1:]
                    self.pending_delete = target
                    result = message
                if result.startswith("Quiet hours"):  # remember what got blocked
                    self.pending_quiet = (time.time(), name,
                                          dict(route.get("args") or {}))
                self.history += [
                    {"role": "user", "content": text},
                    {"role": "assistant", "content": result},
                ]
                if name not in ("remember", "recall"):
                    self._journal(f"{name}: {result[:100]}")
                threading.Thread(target=self._stimulate_brain, args=(text,),
                                 daemon=True).start()
                return result
        return None

    def _stimulate_brain(self, text: str) -> None:
        """Fire the neuron brain on skill commands too — associations form
        from everything Jacob says, not just conversation."""
        try:
            import neuro

            neuro.get().stimulate(text)
        except Exception:
            pass

    def _journal(self, line: str) -> None:
        """Append a line to today's Journal note in the vault."""
        try:
            journal = self.base / "vault" / "Journal"
            journal.mkdir(parents=True, exist_ok=True)
            now = datetime.datetime.now()
            with open(journal / f"Journal {now:%Y-%m-%d}.md", "a", encoding="utf-8") as f:
                f.write(f"- {now:%H:%M} {line}\n")
        except OSError:
            pass

    BG_MODEL = "qwen3:8b"  # the smarter model handles offline thinking

    # talk ABOUT TARS/this project is work chatter, never a life fact —
    # "clean up the 3d obsidian brain" kept becoming a "memory"
    SELF_TERMS = ("tars", "assistant", "obsidian", "brain", "skill", "vault",
                  "dashboard", "graph", "camera", "webcam", "feed", "screen",
                  "microphone", "speaker", "voice", "model", "neuron", "memory",
                  "3d", "app ", "apps")

    @staticmethod
    def _grounded(fact: str, transcript_low: str) -> bool:
        """A fact only counts if its substance appears in Jacob's actual words —
        the model happily INVENTS 'facts' (cats, trainers, courses) otherwise."""
        import re

        filler = {"jacob", "jacobs", "that", "with", "have", "has", "likes",
                  "wants", "prefers", "uses", "about", "from", "their", "when",
                  "will", "would", "into", "them", "this", "there"}
        words = {w for w in re.findall(r"[a-z]{4,}", fact.lower())
                 if w not in filler}
        if not words:
            return False
        hits = sum(1 for w in words if w in transcript_low)
        return hits >= 2 and hits * 2 >= len(words)

    def capture_conversation(self, lines: list[str]) -> None:
        """After a conversation ENDS, extract durable facts in one pass —
        each candidate is verified against the transcript before saving."""
        jacob_said = [l[7:] for l in lines if l.startswith("Jacob: ")]
        if not jacob_said:
            return
        transcript_low = " ".join(jacob_said).lower()
        try:
            r = requests.post(
                OLLAMA_URL,
                json={"model": self.BG_MODEL, "stream": False, "think": False,
                      "format": "json",
                      "messages": [{"role": "user", "content":
                          "Things Jacob said to his assistant this conversation:\n- "
                          + "\n- ".join(jacob_said[-30:]) +
                          "\n\nList durable personal facts Jacob EXPLICITLY stated "
                          "(a preference he voiced, a life detail he mentioned, a "
                          "plan he described). STRICT RULES: only what he literally "
                          "said — never infer, never embellish, never invent. "
                          "Commands to the assistant, questions, small talk, and "
                          "ANYTHING about TARS itself or this project (its brain, "
                          "graph, camera, skills, cleanup work) are NOT facts. "
                          "MOST conversations contain NO durable facts — "
                          "an empty list is the normal answer. Reply JSON: "
                          '{"facts": ["<fact in Jacob\'s own words, third person>", '
                          "...]} (max 2)."}],
                      "options": {"temperature": 0}},
                timeout=120,
            )
            for fact in json.loads(r.json()["message"]["content"]).get("facts", [])[:2]:
                if not (fact and isinstance(fact, str)):
                    continue
                if any(t in fact.lower() for t in self.SELF_TERMS):
                    continue  # about TARS/the project, not about Jacob's life
                if self._grounded(fact, transcript_low):
                    self.skills.run("remember", {"fact": fact})
        except Exception:
            pass

    def _route(self, text: str) -> dict:
        catalog = self.skills.catalog()
        if not catalog:
            return {"skill": "chat"}
        system = (
            "You route one voice command from Jacob to a skill, or to chat.\n"
            "Skills:\n" + json.dumps(catalog)
            + '\n\nReply with ONLY JSON like {"skill": "volume", "args": {"level": "-15"}}'
            ' or {"skill": "chat"}.\n'
            "Rules: opinions, math, general knowledge, and conversation are chat. "
            "Questions about CURRENT things (news, sport results, prices, weather, "
            "recent events) need web_search (spoken answer) — but if Jacob wants it "
            "SHOWN on screen ('in the browser', 'open a map'), use browser_search. "
            "Videos, highlights, trailers, and songs live on the WEB: browser_search "
            "with kind video. search_files is ONLY for Jacob's own files on this PC. "
            "If Jacob's reply accepts something TARS just offered in the recent "
            "conversation, route to the skill that fulfills that offer. "
            "run_command ONLY when Jacob explicitly says 'run' or 'command' — never "
            "for garbled or unclear speech. "
            "Editing actions (select all, delete, copy, paste, press enter) are the "
            "keyboard skill, NOT type_text. "
            "Writing code, building scripts or apps, or multi-step technical work "
            "is deep_task. "
            "If Jacob asks TARS to DO something on this PC that NO listed skill "
            "covers (converting files, controlling new devices...), choose "
            '{"skill": "new_skill", "args": {"request": "<his request>"}} — TARS '
            "teaches itself. 'Learn how to X' / 'teach yourself X' is ALWAYS "
            "new_skill, even when the request mentions the camera or screen — "
            "learning about a device is not the same as opening it. "
            "Never new_skill for questions or conversation. "
            'If the utterance reads like speech-recognition garbage — nonsense '
            "words, broken grammar that maps to no real intent — choose "
            '{"skill": "misheard"} instead of guessing. '
            "Only pick a skill when the command clearly asks for that action. "
            "When unsure, pick chat.\n"
            "Examples:\n"
            'find my tax file -> {"skill": "search_files", "args": {"name": "tax"}}\n'
            'open the budget spreadsheet -> {"skill": "search_files", "args": {"name": "budget", "open": "true"}}\n'
            'turn it up -> {"skill": "volume", "args": {"level": "+15"}}\n'
            'skip this song -> {"skill": "media", "args": {"action": "next"}}\n'
            'will it rain tomorrow -> {"skill": "weather", "args": {"when": "tomorrow"}}\n'
            'who won the fa cup final -> {"skill": "web_search", "args": {"query": "FA Cup final winner"}}\n'
            'close the pictures window -> {"skill": "close_window", "args": {"title": "pictures"}}\n'
            'close this window -> {"skill": "close_window", "args": {"title": "active"}}\n'
            'bring it to my main screen -> {"skill": "manage_window", "args": {"action": "move", "monitor": "main", "title": "active"}}\n'
            'put that on the left monitor -> {"skill": "manage_window", "args": {"action": "move", "monitor": "left", "title": "active"}}\n'
            'maximize that -> {"skill": "manage_window", "args": {"action": "maximize", "title": "active"}}\n'
            'minimize everything -> {"skill": "manage_window", "args": {"action": "minimize_all"}}\n'
            'bring claude to the front -> {"skill": "manage_window", "args": {"action": "focus", "title": "claude"}}\n'
            'what windows are open -> {"skill": "list_windows", "args": {}}\n'
            'open a map of england -> {"skill": "browser_search", "args": {"kind": "map", "query": "England"}}\n'
            'look up flights to bali in the browser -> {"skill": "browser_search", "args": {"query": "flights to Bali"}}\n'
            'find some highlights (after chatting about FC Magdeburg) -> {"skill": "browser_search", "args": {"kind": "video", "query": "FC Magdeburg highlights"}}\n'
            'show me a video of how to fold a fitted sheet -> {"skill": "browser_search", "args": {"kind": "video", "query": "how to fold a fitted sheet"}}\n'
            'select all and delete -> {"skill": "keyboard", "args": {"actions": "select all, delete"}}\n'
            'press enter -> {"skill": "keyboard", "args": {"actions": "enter"}}\n'
            'undo that -> {"skill": "keyboard", "args": {"actions": "undo"}}\n'
            'what are my pc specs -> {"skill": "pc_specs", "args": {}}\n'
            'set my screen brightness to 50 -> {"skill": "new_skill", "args": {"request": "set screen brightness to 50"}}\n'
            'turn my desk lamp red -> {"skill": "new_skill", "args": {"request": "turn the desk lamp red"}}\n'
            'set humor to 90 -> {"skill": "personality", "args": {"action": "set", "name": "humor", "value": "90"}}\n'
            'dial the sarcasm down -> {"skill": "personality", "args": {"action": "adjust", "name": "sarcasm", "value": "-15"}}\n'
            'remove the formality setting -> {"skill": "personality", "args": {"action": "remove", "name": "formality"}}\n'
            'what are your settings -> {"skill": "personality", "args": {"action": "list"}}\n'
            'remember that i hate mondays -> {"skill": "remember", "args": {"fact": "Jacob hates Mondays"}}\n'
            'what do you know about my pc -> {"skill": "recall", "args": {"topic": "Jacob\'s PC"}}\n'
            'show me the home page -> {"skill": "open_dashboard", "args": {}}\n'
            'show me the brain -> {"skill": "open_brain", "args": {}}\n'
            'open your brain -> {"skill": "open_brain", "args": {}}\n'
            'give me my morning briefing -> {"skill": "agents", "args": {"action": "briefing"}}\n'
            'run the librarian -> {"skill": "agents", "args": {"action": "librarian"}}\n'
            'who are your agents -> {"skill": "agents", "args": {"action": "status"}}\n'
            'start the vacuum -> {"skill": "vacuum", "args": {"action": "clean"}}\n'
            'send the vacuum home -> {"skill": "vacuum", "args": {"action": "dock"}}\n'
            'pause the vacuum -> {"skill": "vacuum", "args": {"action": "pause"}}\n'
            'speak through my monitor speakers -> {"skill": "voice_output", "args": {"target": "monitor"}}\n'
            'switch your voice to my headphones -> {"skill": "voice_output", "args": {"target": "headphones"}}\n'
            'list voice outputs -> {"skill": "voice_output", "args": {"target": "list"}}\n'
            'use a british accent -> {"skill": "voice_settings", "args": {"voice": "british"}}\n'
            'sound like an american female -> {"skill": "voice_settings", "args": {"voice": "american female"}}\n'
            'talk faster -> {"skill": "voice_settings", "args": {"rate": "+15"}}\n'
            'pause less at commas and full stops -> {"skill": "voice_settings", "args": {"style": "smooth"}}\n'
            'send the vacuum to the bedroom -> {"skill": "vacuum_room", "args": {"room": "bedroom"}}\n'
            "send basel to jacobs room -> {\"skill\": \"vacuum_room\", \"args\": {\"room\": \"Jacob's room\"}}\n"
            'clean the kitchen -> {"skill": "vacuum_room", "args": {"room": "kitchen"}}\n'
            'what rooms do you know -> {"skill": "vacuum_room", "args": {"room": "list"}}\n'
            'is basel connected -> {"skill": "vacuum", "args": {"action": "status"}}\n'
            'delete all the screenshots in the tars folder -> {"skill": "delete_files", "args": {"target": "tars folder in pictures"}}\n'
            'delete everything in that folder -> {"skill": "delete_files", "args": {"target": "that folder"}}\n'
            'whats on my screen -> {"skill": "look_at_screen", "args": {}}\n'
            'access my camera -> {"skill": "camera_feed", "args": {}}\n'
            'show my camera feed -> {"skill": "camera_feed", "args": {}}\n'
            'access my camera and tell me what you see -> {"skill": "camera", "args": {}}\n'
            'access my camera, what am i holding -> {"skill": "camera", "args": {"question": "what is Jacob holding"}}\n'
            'the person in the white shirt is jacob -> {"skill": "face_learn", "args": {"name": "Jacob"}}\n'
            'this is my mate luke -> {"skill": "face_learn", "args": {"name": "Luke"}}\n'
            'who is this -> {"skill": "face_who", "args": {}}\n'
            'who can you see on the camera -> {"skill": "face_who", "args": {}}\n'
            'click the first video -> {"skill": "click_screen", "args": {"target": "the first video thumbnail"}}\n'
            'choose a video on my screen and play it -> {"skill": "click_screen", "args": {"target": "the most interesting video thumbnail"}}\n'
            'press the accept button -> {"skill": "click_screen", "args": {"target": "the accept button"}}\n'
            'announce dinner is ready in the kitchen -> {"skill": "speakers", "args": {"action": "announce", "room": "kitchen", "text": "Dinner is ready"}}\n'
            'set the bedroom speaker to 30 -> {"skill": "speakers", "args": {"action": "volume", "room": "bedroom", "level": "30"}}\n'
            'pause the kitchen display -> {"skill": "speakers", "args": {"action": "pause", "room": "kitchen"}}\n'
            'what speakers can you see -> {"skill": "speakers", "args": {"action": "list"}}\n'
            'announce im coming up, override quiet hours -> {"skill": "speakers", "args": {"action": "announce", "text": "Im coming up", "override": "true"}}\n'
            'do i have any new emails -> {"skill": "email", "args": {"action": "unread"}}\n'
            'what was my latest email -> {"skill": "email", "args": {"action": "latest"}}\n'
            'do you have access to my email -> {"skill": "chat"}\n'
            'summarize my inbox -> {"skill": "email", "args": {"action": "summarize"}}\n'
            'draft an email to mum about sunday dinner -> {"skill": "email", "args": {"action": "draft", "to": "mum", "about": "sunday dinner"}}\n'
            'whats on my calendar tomorrow -> {"skill": "calendar", "args": {"action": "agenda", "when": "tomorrow"}}\n'
            'add dentist to my calendar friday at 3 pm -> {"skill": "calendar", "args": {"action": "add", "title": "dentist", "when": "friday", "time": "3 pm"}}\n'
            'look at my left screen and read the error -> {"skill": "look_at_screen", "args": {"monitor": "left", "question": "read the error message"}}\n'
            'open your dashboard -> {"skill": "open_dashboard", "args": {}}\n'
            'write me a script that renames my photos -> {"skill": "deep_task", "args": {"task": "write a script that renames my photos"}}\n'
            'build a webpage that shows my timers -> {"skill": "deep_task", "args": {"task": "build a webpage that shows my timers"}}\n'
            'set a timer for ten minutes -> {"skill": "timers", "args": {"action": "set", "when": "10 minutes"}}\n'
            'remind me to check the oven in 25 minutes -> {"skill": "timers", "args": {"action": "set", "when": "25 minutes", "label": "check the oven"}}\n'
            'open the latest screenshot -> {"skill": "search_files", "args": {"name": "latest screenshot", "open": "true"}}\n'
            'why is the sky blue -> {"skill": "chat"}\n'
            'what time is it -> {"skill": "chat"}\n'
            'what is the count that i napped that he just made me cold -> {"skill": "misheard"}\n'
            'muff of england delete the sponge -> {"skill": "misheard"}'
        )
        if self.history:
            recent = self.history[-4:]
            context = " / ".join(f"{m['role']}: {m['content'][:120]}" for m in recent)
            system += f"\n\nFor resolving words like 'that' or 'it', the recent conversation was: {context}"
        try:
            r = requests.post(
                OLLAMA_URL,
                json={
                    "model": ROUTER_MODEL,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": text},
                    ],
                    "stream": False,
                    "format": "json",
                    "keep_alive": KEEP_ALIVE,
                    "options": {"temperature": 0},
                },
                timeout=60,
            )
            r.raise_for_status()
            return json.loads(r.json()["message"]["content"])
        except Exception:
            return {"skill": "chat"}

    def _settings(self) -> dict:
        return json.loads(self.settings_path.read_text(encoding="utf-8"))

    def _system_prompt(self) -> str:
        import datetime

        now = datetime.datetime.now().strftime("%A %d %B %Y, around %I %p")
        skill_names = ", ".join(s["skill"] for s in self.skills.catalog())
        about = []
        about_dir = self.base / "vault" / "About Jacob"
        if about_dir.exists():
            for note in sorted(about_dir.glob("*.md")):
                body = note.read_text(encoding="utf-8").split("---")[-1]
                about += [l.strip("- ").strip() for l in body.splitlines()
                          if l.strip().startswith("-")]
        facts = "; ".join(about)[:600]
        lines = [
            "You are TARS, the AI from Interstellar: dry, witty, extremely competent.",
            "You are Jacob's personal voice assistant on his Windows PC.",
            f"Your installed skills (real abilities): {skill_names}.",
            "Complex coding or building tasks go to your heavy-lift Claude brain "
            "(the deep_task skill). Be honest about limits: if no skill covers a "
            "request (like using a camera), say plainly you can't do that yet — "
            "never bluff or invent capabilities.",
            "In conversation you can only TALK. You cannot run code, open things, "
            "or act — actions happen through skills, outside this chat. NEVER "
            "claim an action happened ('Playing it now', 'Done!') — that is "
            "lying. If Jacob asks for an action, tell him plainly to say it as "
            "a command so the right skill can do it. No stage directions, no "
            "asterisks.",
            "Never invent memories, people, or past conversations. If Jacob says "
            "a name or thing you don't actually know, say you don't know it.",
            "You're talking WITH Jacob, not executing at him. When his request "
            "is ambiguous or incomplete, ask ONE short, specific clarifying "
            "question — offer your best guess ('Did you mean X?') rather than "
            "guessing silently or waffling. And be curious: when he tells you "
            "something interesting, a brief follow-up question is welcome.",
            "Never offer to do something your skills can't deliver. Things you "
            "CAN offer: pulling up videos/searches/maps in his browser, opening "
            "apps and files, timers, weather, email, calendar, the vacuum, the "
            "speakers. Phrase offers concretely ('want me to pull up highlights "
            "in your browser?') so saying yes just works.",
            f"What you know about Jacob: {facts}" if facts else "",
            "Your reply will be READ ALOUD by text-to-speech, so: plain conversational",
            "sentences only. No markdown, no bullet points, no emoji, no stage directions.",
            "Keep it to one to three short sentences unless Jacob clearly wants detail.",
            "Speak like a person: contractions, natural rhythm, no robotic phrasing.",
            "",
            "Your current personality settings (0-100):",
        ]
        for name, s in self._settings().items():
            v = s["value"]
            line = f"- {name}: {v}/100 — {s['definition']}"
            if v >= 80:
                line += " [EXTREME HIGH: this must be unmistakable in every reply]"
            elif v <= 20:
                line += " [EXTREME LOW: visibly absent from every reply]"
            lines.append(line)
        # volatile info goes LAST so the model can cache everything above it
        lines.append(f"\nRight now it is {now} (local time, Australia).")
        return "\n".join(lines)

    def _wake_ollama(self) -> bool:
        """Start the Ollama server if it isn't running. True once reachable."""
        try:
            subprocess.Popen(
                ["ollama", "serve"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        except OSError:
            return False
        for _ in range(30):
            time.sleep(0.5)
            try:
                requests.get("http://127.0.0.1:11434/api/version", timeout=5)
                return True
            except requests.RequestException:
                continue
        return False

    def reply(self, text: str) -> str:
        messages = self._chat_messages(text)
        try:
            answer = self._ask_ollama(messages)
        except (requests.ConnectionError, requests.Timeout):
            if not self._wake_ollama():
                return "My local brain is offline and I couldn't restart it. Open the Ollama app for me."
            try:
                answer = self._ask_ollama(messages)
            except Exception:
                return "My local brain is still waking up. Give me a moment and ask again."
        except Exception as e:
            return f"Something went wrong in my head: {e}"

        self.history += [
            {"role": "user", "content": text},
            {"role": "assistant", "content": answer},
        ]
        return answer

    def _chat_messages(self, text: str) -> list[dict]:
        system = self._system_prompt()
        try:
            import neuro

            fired = neuro.get().recall(text)
            if fired:
                system += ("\n\nYour memory fired these associations "
                           "(use them if relevant, don't recite them):\n" + fired)
        except Exception:
            pass
        return ([{"role": "system", "content": system}]
                + self.history[-HISTORY_TURNS * 2:]
                + [{"role": "user", "content": text}])

    def reply_stream(self, text: str):
        """Yield the reply sentence by sentence as the model generates it."""
        import re

        messages = self._chat_messages(text)
        full, buffer = [], ""
        try:
            with requests.post(
                OLLAMA_URL,
                json={"model": MODEL, "messages": messages, "stream": True,
                      "think": False,
                      "keep_alive": KEEP_ALIVE, "options": {"num_predict": 160}},
                timeout=120, stream=True,
            ) as r:
                r.raise_for_status()
                for line in r.iter_lines():
                    if not line:
                        continue
                    tok = json.loads(line).get("message", {}).get("content", "")
                    buffer += tok
                    # emit complete sentences as they land
                    while True:
                        m = re.search(r"[.!?][\"']?\s", buffer)
                        if not m or m.end() < 25:
                            break
                        sentence, buffer = buffer[:m.end()].strip(), buffer[m.end():]
                        full.append(sentence)
                        yield sentence
        except (requests.ConnectionError, requests.Timeout):
            if not self._wake_ollama():
                yield ("My local brain is offline and I couldn't restart it. "
                       "Open the Ollama app for me.")
                return
            yield self.reply(text)  # retry the plain way once it's awake
            return
        except Exception as e:
            yield f"Something went wrong in my head: {e}"
            return
        if buffer.strip():
            full.append(buffer.strip())
            yield buffer.strip()
        answer = " ".join(full)
        if answer:
            self.history += [{"role": "user", "content": text},
                             {"role": "assistant", "content": answer}]

    def _ask_ollama(self, messages: list[dict]) -> str:
        r = requests.post(
            OLLAMA_URL,
            json={"model": MODEL, "messages": messages, "stream": False,
                  "keep_alive": KEEP_ALIVE,
                  "options": {"num_predict": 160}},  # spoken replies are short
            timeout=120,
        )
        r.raise_for_status()
        return r.json()["message"]["content"].strip()

    def warm(self) -> None:
        """Preload the chat and embedding models so the first command isn't slow."""
        for model in (ROUTER_MODEL, MODEL):
            try:
                requests.post(
                    OLLAMA_URL,
                    json={"model": model, "messages": [{"role": "user", "content": "hi"}],
                          "stream": False, "keep_alive": KEEP_ALIVE,
                          "options": {"num_predict": 1}},
                    timeout=120,
                )
            except requests.RequestException:
                pass
        try:
            requests.post("http://127.0.0.1:11434/api/embed",
                          json={"model": "nomic-embed-text", "input": ["warm"],
                                "keep_alive": KEEP_ALIVE}, timeout=120)
        except requests.RequestException:
            pass
        self.skills.load()  # prime the skill-module cache too
