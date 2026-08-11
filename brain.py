"""TARS's brain, Phase 1: local Ollama chat with the personality system.

Later phases add: intent routing, skills, Claude escalation for hard tasks.
"""
import datetime
import difflib
import json
import re
import subprocess
import threading
import time
import urllib.parse
from pathlib import Path

import requests

OLLAMA_URL = "http://127.0.0.1:11434/api/chat"
MODEL = "qwen2.5:7b"        # conversation
from platform_caps import router_model as _router_model

ROUTER_MODEL = _router_model()  # Windows: separate instance (router and
# chat each keep their own prompt cache — sharing doubled latency there).
# Lite/Mac: the SAME instance — a second resident 7B swamped an M4.
KEEP_ALIVE = "2h"  # keep models loaded in memory between commands
HISTORY_TURNS = 10  # remembered exchanges within a session


def _named(text: str) -> str:
    """Swap the generic "the owner" for whoever actually owns this copy.
    One substitution point, so the published code contains no one's name."""
    try:
        import profile

        return profile.personalise(text)
    except Exception:
        return text


def _ordinal(day: int) -> str:
    """9 -> 'th', 21 -> 'st' — TARS says dates the way people do."""
    if 11 <= day % 100 <= 13:
        return "th"
    return {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")


class _VoiceGuarded:
    """The skill box, with one question asked first: is this the owner?

    Wrapping the box rather than the router means gates, follow-ups and
    anything added later are covered without remembering to check.
    """

    def __init__(self, box, brain):
        self._box, self._brain = box, brain

    def __getattr__(self, item):  # catalog(), reload(), everything else
        return getattr(self._box, item)

    def run(self, name: str, args: dict):
        refused = self._brain._voice_block(name)
        if refused:
            self._brain._journal(f"voice-blocked {name}")
            return refused
        return self._box.run(name, args)


class Brain:
    def __init__(self, base: Path):
        self.base = base
        self.settings_path = base / "settings.json"
        self.history: list[dict] = []
        self.pending_delete: str | None = None
        self.pending_learn: str | None = None
        self.pending_clarify: str | None = None  # a vague self-teach ask
        # awaiting one concrete example before proposing to teach it
        self.recent_learns: list[tuple[float, str]] = []  # (t, normalized request)
        self.pending_quiet: tuple[float, str, dict] | None = None  # (t, skill, args)
        # "that was wrong" needs to know what "that" WAS
        self.last_turn: dict | None = None
        self.pending_fix: dict | None = None  # awaiting what it should've done
        from skills_engine import SkillBox
        from search_refine import SearchMemory

        # every skill call goes through the voice guard — the deterministic
        # gates run skills directly, so checking only in the router path
        # left a dozen doors open
        self.skills = _VoiceGuarded(SkillBox(base), self)
        self.search_memory = SearchMemory(base)

    LEARN_RESPONSES = (
        "I don't know how to do that yet — so I'm teaching myself right now. "
        "Give me a few minutes; I'll tell you when I've got it."
    )

    def _learning_task(self, request: str) -> str:
        skills_dir = self.base / "skills"
        from platform_caps import python_cmd

        runtime_py = python_cmd(self.base)
        example = (skills_dir / "volume" / "skill.py").read_text(encoding="utf-8")
        existing = "\n".join(
            f"- {s['skill']}: {s['description']}" for s in self.skills.catalog())
        return (
            f"TEACH YOURSELF A NEW SKILL. the owner asked TARS: {request!r}.\n"
            f"FIRST, check it against TARS's existing skills below — the owner has "
            f"gone in circles before from TARS creating overlapping skills for "
            f"jobs an existing one already covered (e.g. a new 'github_upload' "
            f"skill when 'github_publish' already existed). If one of these "
            f"already does this job (even under a different name, e.g. a "
            f"'brightness' skill covers 'dim my screen'), STOP: don't create "
            f"anything, and instead make SPOKEN say which existing skill "
            f"already covers it and the phrase the owner should use. Only proceed "
            f"past this point if the request is genuinely new.\n"
            f"Existing skills:\n{existing}\n"
            f"SECOND, DON'T REINVENT IT (the owner's rule, 2026-08-08): search "
            f"for an existing open-source tool before writing your own "
            f"engine. Use TARS's find_tool skill "
            f"(skills/find_tool/skill.py — call its search(query) from "
            f"python, it queries GitHub and PyPI) and/or WebSearch. If a "
            f"maintained library does the heavy lifting (pdf reading, "
            f"image conversion, device protocols, parsing...), pip-install "
            f"it into the runtime and write a THIN skill that wraps it — "
            f"that beats hand-rolled code every time. Say in SPOKEN which "
            f"library you used, if any. Only hand-roll when nothing "
            f"suitable exists or the job is genuinely trivial.\n"
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
            f"the owner should say to use it."
        )

    def handle(self, text: str) -> str:
        """Route to a skill or chat — whole reply at once (tests, dashboard)."""
        routed = self._handle_routed(text)
        if routed is not None:
            self._stamp()
            return _named(routed)
        return _named(self.reply(text))

    def _stamp(self) -> None:
        """Mark when TARS last answered. The deterministic gates return
        early from a dozen places, so stamping here is the only way a
        follow-up ("what's in the maths one?") knows it's a follow-up."""
        self.last_turn = {**(self.last_turn or {}), "at": time.time()}

    def handle_stream(self, text: str):
        """Like handle(), but chat replies stream out sentence by sentence,
        so TARS starts talking while still thinking."""
        routed = self._handle_routed(text)
        if routed is not None:
            self._stamp()
            yield _named(routed)
            return
        for piece in self.reply_stream(text):
            yield _named(piece)

    def _handle_routed(self, text: str) -> str | None:
        """All routing/gates/skills. Returns None when it's conversation."""
        lowered = text.lower()

        # a confirmation is waiting on the owner's yes/no (deletion or big move)
        if self.pending_delete:
            target = self.pending_delete
            self.pending_delete = None  # one shot — anything but yes cancels
            if lowered.strip().startswith(("yes", "yeah", "yep", "confirm")):
                if isinstance(target, tuple):  # (skill, args) generic confirm
                    result = self.skills.run(target[0], target[1])
                    skill_name = target[0]
                else:
                    result = self.skills.run(
                        "delete_files", {"target": target, "confirmed": "true"})
                    skill_name = "delete_files"
                self.history += [{"role": "user", "content": text},
                                 {"role": "assistant", "content": result}]
                self._journal(f"{skill_name} (confirmed): {result[:100]}")
                return result
            if lowered.strip().startswith(("no", "nah", "cancel", "don't", "dont")):
                return "Cancelled. Nothing touched."
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

        # a vague self-teach ask was held for one concrete example — "add a
        # voice selection unit to your dashboard" or "sell and buy items on
        # FC26" gave the learning task nothing to aim at, so it guessed and
        # the owner had to re-teach it; asking for an example up front fixes the
        # guess before any work starts
        if self.pending_clarify:
            original = self.pending_clarify
            self.pending_clarify = None
            if lowered.strip().startswith(("no", "nah", "cancel", "never mind",
                                           "nevermind")):
                return "Fair enough, skipping it."
            if len(text.strip()) >= 4:
                clarified = f"{original} — for example: {text.strip()}"
                self.pending_learn = clarified
                reply = (f"Got it — want me to teach myself to {clarified}? "
                         f"Say yes and I'll get to work.")
                self.history += [{"role": "user", "content": text},
                                 {"role": "assistant", "content": reply}]
                return reply
            # too short to be a real example — fall through and handle this
            # as a fresh command instead

        # a proposed self-teaching is waiting on the owner's yes/no
        # the design skill asked "Design what, exactly?" — the owner's next
        # words ARE the design request (he once described a full iPhone
        # stand and got asked the same question again)
        if getattr(self, "pending_design", False):
            self.pending_design = False
            if re.match(r"^(re-?open|open|load|show|bring)\b", lowered):
                # he's asking to SEE a design, not describing a new one —
                # the catch-all once sent "Re-open that last project" to
                # the big brain as an object to design
                result = self.skills.run(
                    "design", {"action": "load", "name": "latest"})
                self.history += [{"role": "user", "content": text},
                                 {"role": "assistant", "content": result}]
                return result
            if not lowered.strip().startswith(("no", "nah", "cancel",
                                               "never mind", "nevermind")):
                result = self.skills.run(
                    "design", {"request": text.strip(" .!?")})
                self.history += [{"role": "user", "content": text},
                                 {"role": "assistant", "content": result}]
                self._journal(f"design: {result[:100]}")
                return result
            return "Fair enough, no design."

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

        # "open them in my browser" / "open the repos you were talking about".
        # This used to become open_app("browser") — TARS opened a browser and
        # called it done, then chat bluffed "Opening GitHub repositories…".
        # The referent lives in TARS's own last replies, so read it from there.
        # Only fires when something WAS actually mentioned; otherwise the
        # normal routing has its go.
        if re.search(r"\b(open|show|pull up|bring up|load|go to)\b[^.]{0,30}?"
                     r"\b(them|those|these|the (repo\w*|link\w*|site\w*|"
                     r"page\w*|website\w*|url\w*|one\w*|other\w*))\b", lowered):
            done = self._open_mentions(lowered)
            if not done and re.search(r"\b(them|those|these|they)\b", lowered):
                # a bare pronoun with nothing to point at. Letting this fall
                # through sent it to the tabs skill, which searched for a tab
                # named "" and said "No open tab looks like ."
                done = ("Open what? I've got no links or repos from just now "
                        "— tell me which and I'll open them.")
            if done:
                self.history += [{"role": "user", "content": text},
                                 {"role": "assistant", "content": done}]
                self._journal(f"opened what was mentioned: {done[:100]}")
                return done

        # the owner is answering "what should I have done?" — his words become
        # the wanted behaviour on the misfire we just logged
        if self.pending_fix:
            entry = self.pending_fix
            self.pending_fix = None
            if not lowered.strip().startswith(("nothing", "leave it", "never mind",
                                               "nevermind", "forget it", "no")):
                entry["wanted"] = text.strip()[:300]
                self._log_misfire(entry, replace=True)
                return ("Got it. I've written down what it should have done — "
                        "Kipp turns the repeat offenders into proper fixes.")
            return "Fair enough — I've logged the misfire anyway."

        # "what did I do today" was going to the Google calendar, which has
        # been dead since his token expired — it's a recap, and that's local
        if re.search(r"\bwhat (did|have) i (do|done|been doing) "
                     r"(today|yesterday|this morning)\b|\brecap my day\b",
                     lowered):
            result = self.skills.run(
                "day_recap",
                {"day": "yesterday" if "yester" in lowered else "today"})
            self.history += [{"role": "user", "content": text},
                             {"role": "assistant", "content": result}]
            return result

        # HAND SIGNALS. Sits with the camera gates because it opens the
        # webcam — and like them, only ever on words the owner actually said.
        # while the camera IS watching, a bare "stop watching" must reach it.
        # It fell to chat, which cheerfully said "stopped watching" with the
        # camera still running — the worst possible bluff for a camera.
        # fires whether or not it's currently watching: with the camera
        # already off, "stop watching" fell to chat, which answered "okay,
        # I've stopped watching the screen" — inventing an action again.
        # "the screen" is screen_watch's job, so that's excluded.
        if re.search(r"\b(stop|turn off|shut off|that'?s enough|close)\b"
                     r".{0,20}\b(watch\w*|camera|signals?|gestures?)\b|"
                     r"^stop watching\b", lowered.strip()) and \
                not re.search(r"\bscreen\b|\bdownload\b", lowered):
            result = self.skills.run("signals", {"action": "stop"})
            # "watch for hand signals" and "tell me when the download
            # finishes" both answer to "watching" — a bare "stop watching"
            # only ever reaches the camera above, so a screen watch left
            # running got no mention at all, and he'd say "stop watching"
            # again expecting it to do something. Say so instead of going
            # quiet about the one thing this command didn't touch.
            if self._screen_watch_active():
                result += (" Screen watch's still running though — say "
                           "'stop watching the screen' to cancel that one.")
            self.history += [{"role": "user", "content": text},
                             {"role": "assistant", "content": result}]
            return result
        if re.search(r"\b(hand )?signals?\b|\bgestures?\b", lowered) and \
                re.search(r"\b(watch|watching|look|start|stop|use|enable|"
                          r"disable|are you)\b", lowered):
            if re.search(r"\b(stop|don'?t|turn off|disable|quit|enough)\b",
                         lowered):
                action = "stop"
            elif re.search(r"\b(are you|status|still)\b", lowered):
                action = "status"
            else:
                action = "start"
            minutes = re.search(r"(\d+)\s*min", lowered)
            result = self.skills.run("signals", {
                "action": action,
                "minutes": minutes.group(1) if minutes else "10"})
            self.history += [{"role": "user", "content": text},
                             {"role": "assistant", "content": result}]
            self._journal(f"signals ({action}): {result[:80]}")
            return result

        # "What did I miss?" — he's at school all day while TARS talks to an
        # empty room. Above the study gate so it works mid-quiz too.
        if re.search(r"\b(what did i miss|what have i missed|did i miss "
                     r"anything|anything happen while i was (out|away|gone)|"
                     r"catch me up|fill me in)\b", lowered):
            result = self.skills.run("missed", {"since": lowered})
            self.history += [{"role": "user", "content": text},
                             {"role": "assistant", "content": result}]
            return result

        # a revision SHEET (something to read) vs a quiz (being asked things)
        if re.search(r"\b(revision (sheet|notes)|cheat ?sheet|study (sheet|"
                     r"notes)|study guide|summar(y|ise|ize) .{0,25}\b(test|"
                     r"exam|assessment)|notes for (the |my )?\w+ (test|exam))"
                     r"\b", lowered):
            if re.search(r"\b(open|show|bring up|reopen)\b", lowered) and \
                    not re.search(r"\b(make|write|create|do)\b", lowered):
                args = {"action": "open"}
            else:
                subject = re.sub(r".*\b(for|on|about)\b\s*", "", lowered)
                subject = re.sub(r"\b(the|my|a|an)\b\s*", "", subject).strip(" ?.")
                args = {"action": "make", "subject": subject or text}
            result = self.skills.run("revision", args)
            self.history += [{"role": "user", "content": text},
                             {"role": "assistant", "content": result}]
            self._journal(f"revision: {result[:100]}")
            return result

        # "what's this question asking" — reads it off the screen. Must beat
        # look_at_screen, which would just describe the whole window.
        if re.search(r"\b(what('?s| is) this question( asking| about| want)?|"
                     r"explain this question|i don'?t (get|understand) this "
                     r"(question|one)|what do i do here|help me with this "
                     r"(one|question)|what('?s| is) it asking|"
                     r"(give|tell) me the answer.{0,20}\b(this|question)|"
                     r"what('?s| is) the answer to this)\b", lowered):
            wants_answer = bool(re.search(r"\b(just (give|tell) me the answer|"
                                          r"what('?s| is) the answer|answer "
                                          r"it for me)\b", lowered))
            result = self.skills.run("explain_question", {
                "monitor": "left" if "left" in lowered else "main",
                "answer": "true" if wants_answer else ""})
            self.history += [{"role": "user", "content": text},
                             {"role": "assistant", "content": result}]
            return result

        # STUDY MODE. While a quiz is running, whatever the owner says next is
        # an ANSWER — routing it as a command would send "the gradient of
        # the line" off to the search skill. Sits above everything except
        # the safety gates so a session isn't constantly hijacked.
        quiz_open = False
        try:  # a file read, not a module import — this runs on EVERY command
            session = json.loads((self.base / "study_session.json")
                                 .read_text(encoding="utf-8"))
            quiz_open = bool(session.get("questions")) and (
                time.time() - session.get("started", 0) < 7200)
        except (OSError, json.JSONDecodeError):
            pass
        if quiz_open:
            # a quiz left open an hour ago must not eat real commands —
            # "help me study for my physics exam" got marked as a wrong
            # answer to a maths question from the previous session
            if re.search(r"\b(help me (study|revise)|quiz me|test me|"
                         r"revision sheet|cheat ?sheet|what('?s| is) due|"
                         r"what have i got|open (the|my) \w+|play |set a "
                         r"timer|what time|whats? the weather|shut down|"
                         r"what did i miss)\b", lowered):
                self.skills.run("study", {"action": "stop"})
                quiz_open = False
        if quiz_open:
            if re.search(r"^(stop|quit|end|enough|that'?s enough|leave it|"
                         r"finish)\b", lowered.strip()):
                result = self.skills.run("study", {"action": "stop"})
            elif re.search(r"^(skip|next|pass|dunno|i dunno|no idea|"
                           r"don'?t know|i don'?t know)\b", lowered.strip()):
                result = self.skills.run("study", {"action": "skip"})
            else:
                result = self.skills.run("study", {"action": "answer",
                                                   "text": text})
            self.history += [{"role": "user", "content": text},
                             {"role": "assistant", "content": result}]
            return result
        if re.search(r"\b(help me (study|revise)|quiz me|test me on|"
                     r"study (for|with)|revise (for|with)|"
                     r"practice questions|ask me (some )?questions)\b",
                     lowered):
            subject = re.sub(r".*\b(study|revise|quiz me on|quiz me|test me "
                             r"on|questions (on|about))\b\s*", "", lowered)
            subject = re.sub(r"^(for|with|about|me)\s+", "", subject).strip(" ?.")
            # "quiz me" = ask me things. "help me study" = give me something
            # to READ first — the owner asked for notes and got fired questions.
            asked_for_questions = bool(re.search(
                r"\b(quiz me|test me|ask me|practice questions)\b", lowered))
            result = None
            if not asked_for_questions:
                first = self.skills.run("revision", {"action": "study",
                                                     "subject": subject or text})
                if first != "__QUIZ__":
                    result = first
            if result is None:
                result = self.skills.run("study", {"action": "start",
                                                   "subject": subject or text})
            self.history += [{"role": "user", "content": text},
                             {"role": "assistant", "content": result}]
            self._journal(f"study: {result[:100]}")
            return result
        if re.search(r"\b(how('?s| is) my revision|my study progress|"
                     r"what am i (bad|weak) at|how am i going with (study|"
                     r"revision))\b", lowered):
            result = self.skills.run("study", {"action": "progress"})
            self.history += [{"role": "user", "content": text},
                             {"role": "assistant", "content": result}]
            return result

        # SCHOOL: timetable, what's due, study sessions. Sits above the
        # calendar and timers gates — "what have I got tomorrow" is school
        # for a 15-year-old, and "due Friday" is homework, not an event.
        school = None
        if re.search(r"\bseqta\b|\bsequoia\b|\bsector\b(?=.{0,20}\bschool\b)",
                     lowered):
            school = {"action": "seqta", "text": text}
        elif re.search(r"\b(on (mon|tues|wednes|thurs|fri|satur|sun)days?\b|"
                     r"\bmy timetable\b)[^.]*\bi (have|got|do)\b", lowered) or \
                re.search(r"\bmy timetable is\b|\bset my timetable\b", lowered):
            school = {"action": "set_timetable", "text": text}
        elif re.search(r"\b(my timetable|what (have i got|do i have|classes|"
                       r"lessons|subjects)( on| for)? (today|tomorrow|monday|"
                       r"tuesday|wednesday|thursday|friday)|what('?s| is) my "
                       r"(school )?day)\b", lowered) and not re.search(
                r"\b(calendar|appointment|meeting)\b", lowered):
            day = re.search(r"\b(today|tomorrow|monday|tuesday|wednesday|"
                            r"thursday|friday|saturday|sunday)\b", lowered)
            # "what have I got tomorrow, FIRST PERIOD" wants one lesson,
            # not the whole day read out
            period = ""
            spot = re.search(r"\b(first|last|1st|2nd|3rd|\d)\s*(period|lesson|"
                             r"class)\b|\bperiod\s*(\d)\b", lowered)
            if spot:
                word = spot.group(1) or spot.group(3) or ""
                period = {"1st": "1", "2nd": "2", "3rd": "3"}.get(word, word)
            school = {"action": "timetable", "text": text,
                      "day": day.group(1) if day else "", "period": period}
        elif re.search(r"\b(list|show|tell me|what are|give me|name)\b[^.]{0,30}"
                       r"\b(assessment|exam|test|assignment)s?\b", lowered) or \
                re.search(r"\b(assessment|exam)s\b.{0,20}\b(have i got|do i "
                          r"have|are (there|coming))\b", lowered):
            # "list the next three assessments" — a count, from real data.
            # This whole family used to reach the Google CALENDAR skill.
            words = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
                     "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10}
            found = re.search(r"\b(\d+|one|two|three|four|five|six|seven|"
                              r"eight|nine|ten)\b", lowered)
            token = found.group(1) if found else "3"
            school = {"action": "due", "text": text,
                      "count": str(words.get(token, token))}
        elif re.search(r"\b(when('?s| is)? (my |the )?next (test|exam|"
                       r"assessment|assignment|task)|what('?s| is) (my |the )?"
                       r"next (test|exam|assessment|assignment)|my next "
                       r"(test|exam|assessment|assignment)|when('?s| is) (my |"
                       r"the )?(test|exam)\b)", lowered):
            # a test date is a FACT. Chat once invented "Maths on Thursday at
            # 9am in 1R05" from the timetable sitting in the conversation.
            school = {"action": "due", "text": text, "index": "0"}
            self.due_cursor = (time.time(), 0)
        elif getattr(self, "due_cursor", None) and \
                time.time() - self.due_cursor[0] < 420 and \
                re.search(r"\b(what about|and) the (one|next one) after "
                          r"(that|it)\b|\bthe one after (that|it)\b|"
                          r"\bwhat('?s| is) after that\b|\band then\?*$",
                          lowered.strip()):
            nxt = self.due_cursor[1] + 1
            school = {"action": "due", "text": text, "index": str(nxt)}
            self.due_cursor = (time.time(), nxt)
        elif re.search(r"\b(what('?s| is)? due|anything due|what have i got "
                       r"due|my (homework|assignments?|school ?work))\b",
                       lowered):
            school = {"action": "due", "text": text}
        elif re.search(r"\b(assignment|homework|essay|project|poster|report|"
                       r"prac|revision|exam|test|quiz)\b", lowered) and \
                re.search(r"\b(due|hand ?in|handed in|submit)\b", lowered) and \
                not re.search(r"\b(what|when|which|is|any)\b", lowered.split()[0]):
            school = {"action": "add_work", "text": text}
        elif re.search(r"\b(i'?ve )?(finished|done|handed in|submitted|"
                       r"completed)\b.{0,40}\b(assignment|homework|essay|"
                       r"project|poster|report|revision)\b", lowered):
            school = {"action": "done", "text": text}
        elif re.search(r"\b(start|begin) (a |my )?(study|revision|homework) "
                       r"(session|block|timer)?|\bstudy (session|timer|block)\b|"
                       r"\btime to (study|revise)\b", lowered):
            minutes = re.search(r"(\d+)\s*(min|minute)", lowered)
            school = {"action": "study",
                      "minutes": minutes.group(1) if minutes else "25"}
        elif re.search(r"\bhow (long|much) have i (studied|revised)\b|"
                       r"\bmy study (time|stats)\b", lowered):
            school = {"action": "study_stats", "text": text}
        # last line of defence: schoolwork must never reach the Google
        # calendar. "List the next three assessments" came back as an expired
        # -token error because the router sent it there.
        if not school and re.search(r"\b(assessment|homework|assignment|"
                                    r"school ?work)s?\b", lowered) and \
                not re.search(r"\b(appointment|meeting|calendar|event|"
                              r"birthday|dentist|doctor)\b", lowered):
            school = {"action": "due", "text": text}
        if school:
            result = self.skills.run("school", school)
            self.history += [{"role": "user", "content": text},
                             {"role": "assistant", "content": result}]
            self._journal(f"school ({school['action']}): {result[:100]}")
            return result

        # the Downloads tidy-up. "Put my downloads back" must never be heard
        # as a file deletion, so it gets its own gate before anything else
        # that touches files.
        if (re.search(r"\b(download\w*)\b", lowered) and re.search(
                r"\b(fil(e|ed|ing)|tidy|tidied|sort\w*|organis\w*|organiz\w*|"
                r"put (them|it|my downloads) back|undo|clean\w* up|messy)\b",
                lowered)) or re.search(
                r"\bwhat (have you|did you|d you) (file|filed|tidied|sorted|"
                r"moved)\b", lowered):
            action = "status"
            if re.search(r"\b(put .{0,20}back|undo|revert|restore)\b", lowered):
                action = "undo"
            elif re.search(r"\b(stop|don'?t|turn off|disable|quit)\b", lowered):
                action = "off"
            elif re.search(r"\b(turn on|start|enable|resume)\b", lowered):
                action = "on"
            elif re.search(r"\b(tidy|sort|file|clean)\w*\b", lowered) and \
                    not re.search(r"\b(what|have you|did you|status)\b", lowered):
                action = "now"
            result = self.skills.run("downloads", {"action": action})
            self.history += [{"role": "user", "content": text},
                             {"role": "assistant", "content": result}]
            self._journal(f"downloads ({action}): {result[:100]}")
            return result

        # "what was that site I was on last night" — his OWN browser history,
        # not a fresh web search. The distinction the router kept missing is
        # that he's asking about a page he's already seen.
        hist = re.search(r"\b(what was that (site|page|website|video|article|"
                         r"link|thing)|what was i (looking at|reading|watching|"
                         r"on)|that (site|page|video|article) i was (on|"
                         r"looking at|reading|watching)|search my (browser )?"
                         r"history|in my (browser )?history|find that (site|"
                         r"page|website|link|article))\b", lowered)
        if hist:
            topic = re.search(r"\babout (.+)$|\bfor (.+)$|\bwith (.+)$", lowered)
            query = ((topic.group(1) or topic.group(2) or topic.group(3)).strip()
                     if topic else text)
            when = ""
            for period in ("yesterday", "today", "last night", "this week",
                           "last week", "this month"):
                if period in lowered:
                    when = period
            result = self.skills.run("history_search",
                                     {"query": query, "when": when})
            self.pending_history = time.time()
            self.history += [{"role": "user", "content": text},
                             {"role": "assistant", "content": result}]
            return result

        # "open the first one" right after a history answer means THAT one
        if getattr(self, "pending_history", 0) and \
                time.time() - self.pending_history < 300 and \
                re.search(r"^(open|bring up|show me) (it|that|the (first|second|"
                          r"third|1st|2nd|3rd) one)\b", lowered.strip()):
            which = re.search(r"\b(first|second|third|1st|2nd|3rd)\b", lowered)
            result = self.skills.run(
                "history_search",
                {"open": which.group(1)[:6] if which else "true"})
            self.history += [{"role": "user", "content": text},
                             {"role": "assistant", "content": result}]
            return result

        # "that was wrong" — the owner calling out a bad answer is the single best
        # training signal there is, and it used to evaporate into the chat log.
        # Captures the EXACT command, what TARS did with it, and (next turn)
        # what it should have done. Kipp mines these for real gates.
        if re.search(r"\b(that('s| was) (wrong|not right|not what i)|"
                     r"thats (wrong|not what i)|you got (that|it) wrong|"
                     r"wrong (answer|thing|again)|that's not what i (asked|said|"
                     r"meant|wanted)|i didn'?t ask (you )?(for|to)|"
                     r"that('s| is) not what i wanted|you misunderstood)\b",
                     lowered) and len(text) < 160:
            if not self.last_turn:
                return "Wrong about what? I've not done anything yet this session."
            entry = dict(self.last_turn)
            self._log_misfire(entry)
            self.pending_fix = entry
            did = (f"ran {entry['skill']}" if entry["skill"] != "chat"
                   else "just talked")
            return (f"Logged it — you said \"{entry['said'][:60]}\" and I {did}. "
                    f"What should I have done?")

        # "open a tab" / "new tab" — the tabs skill had no way to make one,
        # so this became a search for a tab called nothing
        if re.search(r"\b(open|make|start|give me)\b\s+(a|another|me a)?\s*"
                     r"\bnew tab\b|\bopen a tab\b|^new tab$", lowered):
            result = self.skills.run("tabs", {"action": "new"})
            self.history += [{"role": "user", "content": text},
                             {"role": "assistant", "content": result}]
            return result

        # the clock. "What time is it" kept landing on the timers skill, which
        # answered "For how long, or at what time?" — so answer it here, before
        # the router even sees it. Anything that smells like a timer, alarm or
        # diary entry is left alone.
        if re.search(r"\b(what('?s| is)? the (time|date)|what time is it|"
                     r"got the time|what('?s| is) today('?s date)?|"
                     r"what (day|date) is it|current time)\b",
                     lowered) and not re.search(
                r"\b(timer|alarm|remind|wake me|set |appointment|meeting|"
                r"event|calendar|sunset|sunrise|match|kick ?off)\b", lowered):
            now = datetime.datetime.now()
            clock = now.strftime("%I:%M %p").lstrip("0").replace("AM", "am") \
                       .replace("PM", "pm")
            day = f"{now.strftime('%A')} the {now.day}{_ordinal(now.day)} " \
                  f"of {now.strftime('%B')}"
            reply = (f"It's {day}." if re.search(r"\b(day|date|today)\b", lowered)
                     else f"It's {clock}, {day}.")
            self.history += [{"role": "user", "content": text},
                             {"role": "assistant", "content": reply}]
            return reply

        # A FOLLOW-UP IS CONVERSATION, NOT A COMMAND.
        # the owner: "when I say something to you, you just understand — when I
        # say it to him he doesn't get what I mean or just repeats something."
        # The cause: every sentence was forced through a classifier picking
        # one of ~100 skills, so "go through what's in the maths one" — a
        # plain question about the answer TARS had JUST given — was labelled
        # misheard and never reached the part of him holding the answer.
        # Questions that point back at what was just said now go straight to
        # chat, which has the whole conversation in front of it.
        if self._is_followup(text, lowered):
            self._journal(f"follow-up (to chat): {text[:80]}")
            return None

        route = self._route(text)
        name = route.get("skill", "chat")

        # the router sometimes invents plausible skill names that don't exist —
        # a question falls back to chat, an action request becomes a proposal
        # to self-teach (with the owner's yes/no)
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

        # "learn how to X" / "teach yourself X" is ALWAYS a self-teaching
        # request — mentioning a device (camera...) or Kipp's self-improvement
        # in the request must not trigger that skill instead. Sits BEFORE the
        # new_skill branch so the redirect gets the full proposal flow.
        if any(p in lowered for p in ("learn how", "learn to", "teach yourself",
                                      "teach yourselves", "teach you to")) and \
                name in ("camera", "camera_feed", "open_app", "browser_search",
                         "look_at_screen", "face_who", "face_learn",
                         "improve", "agents"):
            name = "new_skill"
            route["args"] = {"request": text}

        if name == "misheard":
            reply = f"I think I misheard you — I got: {text}. One more time?"
            self.history += [{"role": "user", "content": text},
                             {"role": "assistant", "content": reply}]
            return reply
        if name == "new_skill":
            request = (route.get("args") or {}).get("request") or text
            req_low = request.lower()
            # the owner went in circles (2026-07-19): the router kept proposing
            # brand-new skills for jobs an EXISTING skill already covered —
            # five overlapping GitHub skills in one morning. Rescue layers:
            explicit_learn = any(p in req_low for p in
                                 ("teach yourself", "teach yourselves",
                                  "learn how", "learn to"))
            covered = None
            mem_words = ("remember", "don't forget", "dont forget",
                         "keep in mind", "note that", "so you know",
                         "for future reference")
            if any(w in req_low for w in mem_words):
                covered = None  # memory words win — handled below, WITH the fact
            elif any(w in req_low for w in ("upload", "publish", "push")) and \
                    any(w in req_low for w in ("github", "repo", "repository")):
                covered = ("github_file" if "github_file" in real and any(
                    w in req_low for w in (".py", ".txt", "file "))
                    else "github_publish")
            elif "open_app" in real and "app" in req_low and any(
                    v in req_low for v in ("open", "launch", "start")) and any(
                    w in req_low for w in ("resembl", "similar",
                                           "search my pc", "search my computer")):
                # "if I say it opens an app, e.g. Obsidian, search my PC for
                # something resembling it and open it" IS open_app's fuzzy
                # matching (it already searches for ANY app, not just the one
                # named as the example) — teaching this again for the next
                # example app would just duplicate a skill the owner already has
                covered = "open_app"
            elif not explicit_learn:
                # a skill literally NAMED in the request covers it — but only
                # for direct commands; "learn how to zoom in camera mode"
                # mentions the camera skill without being covered by it
                named = [s for s in real if s != "deep_task"
                         and s.replace("_", " ") in req_low]
                if named:
                    covered = max(named, key=len)
            if covered in real:
                if explicit_learn:
                    return (f"I already know how — that's my "
                            f"{covered.replace('_', ' ')} skill. Just ask me "
                            f"to do it and I will.")
                name = covered
                route["args"] = {}
            else:
                # FACTS are for remembering, ABILITIES are for learning —
                # "my gate code is 4321" must never become a teach-myself
                # proposal. Explicit memory words go straight to the vault;
                # plain statements about the owner's life (no "you/yourself"
                # asking TARS to act) are conversation, where auto-capture
                # already stores whatever is durable.
                mem_words = ("remember", "don't forget", "dont forget",
                             "keep in mind", "note that", "so you know",
                             "for future reference")
                if any(w in req_low for w in mem_words):
                    name = "remember"
                    route["args"] = {"fact": request}
                elif not explicit_learn:
                    # only an explicit "teach yourself"/"learn how"/"learn to"
                    # is a real ask for a new skill — everything else here is
                    # a statement or a rephrasing of something already said
                    # ("the owner made you" / "only refer to me as..." both got a
                    # nonsense teach-myself proposal before this check existed)
                    name = "chat"
                else:
                    # mishearings kept triggering expensive learning runs —
                    # confirm first. And re-saying the same request while it's
                    # still awaiting an answer (or right after) shouldn't get
                    # the exact same "I don't have a skill" prompt again —
                    # that just reads as TARS not having heard the first time.
                    now = time.time()
                    norm_request = req_low.strip(" .!?")
                    self.recent_learns = [(t, r) for t, r in self.recent_learns
                                          if now - t < 1800]
                    already_asked = any(r == norm_request
                                        for _, r in self.recent_learns)
                    self.recent_learns.append((now, norm_request))
                    if already_asked:
                        self.pending_learn = request
                        reply = (f"Still on that same one — teach myself to "
                                 f"{request}? Just say yes.")
                    else:
                        # a vague ask ("add a voice selection unit to your
                        # dashboard") gives the learning task nothing concrete
                        # to build — get one real example first so the guess
                        # is right and the owner isn't asked to re-teach it
                        self.pending_clarify = request
                        reply = (f"I don't have a skill for that. Give me one "
                                 f"specific example of what you'd say or want "
                                 f"done, and I'll teach myself to handle it.")
                    self.history += [{"role": "user", "content": text},
                                     {"role": "assistant", "content": reply}]
                    return reply
        # hard gates: dangerous or noisy skills need the trigger word actually
        # said — the router alone has let garbled speech through before
        if name == "run_command" and "run " not in lowered and "command" not in lowered:
            name = "chat"
        # folders are open_app's job — "open Pictures folder" fell to chat,
        # which cheerfully announced it had opened it
        if re.search(r"\bopen\b.{0,25}\b(folder|directory)\b", lowered) and \
                name in ("chat", "search_files", "downloads", "organize"):
            m = re.search(r"open\s+(?:my\s+|the\s+)?([\w ]{2,25}?)\s*folder",
                          lowered)
            name = "open_app"
            route["args"] = {"target": (m.group(1).strip() if m else "")}
        # "open <app>" belongs to open_app — rival skills (music grabbed
        # "Open Spotify") only keep it with a clear signal of their own
        if lowered.startswith(("open ", "launch ", "start ")) and \
                name in ("music", "notes_box") and \
                not any(w in lowered for w in ("note", "paste", "play",
                                               "song", "game")):
            name = "open_app"
            route["args"] = {}
        # switching TARS's own output device must never fall to chat — chat
        # once bluffed "I'm now speaking through your monitor" while the
        # audio stayed on headphones. Nest-speaker rooms are excluded.
        if (("output device" in lowered or "audio output" in lowered
                or "speak through" in lowered or "voice through" in lowered
                or ("output" in lowered and any(d in lowered for d in
                    ("monitor", "headphone", "headset", "quest", "screen"))))
                and not any(w in lowered for w in
                            ("kitchen", "bedroom", "announce", "nest"))
                and name != "voice_output"):
            target = next((d for d in ("monitor", "headphone", "headset",
                                       "quest", "screen") if d in lowered),
                          "list")
            name = "voice_output"
            route["args"] = {"target": "headphones" if target == "headphone"
                             else target}
        # musing questions about himself are CONVERSATION, not a Kipp
        # status readout — "what would you add to yourself?" deserves an
        # actual answer, not "4 upgrades implemented today"
        if name == "improve" and any(p in lowered for p in
                ("what would", "if you could", "would you want", "wish",
                 "do you want", "what do you think", "how do you feel")):
            name = "chat"
        # sending messages on the owner's behalf is a HARD BLOCK (spec §8) —
        # he asked TARS to WhatsApp his mum and got a bluffed "sending it
        # now". Say the truth instead, and offer what he CAN do.
        if re.search(r"\b(send|text|message|whatsapp|dm)\b", lowered) and \
                re.search(r"\b(whatsapp|mum|mumma|mom|dad|sophie|emma|luke|"
                          r"my (mate|friend|brother|sister)|him|her|them)\b",
                          lowered) and \
                not re.search(r"\b(to me|myself|my phone|to my phone|"
                              r"to my pc|to the dashboard)\b", lowered):
            # lift the actual message out of the request ("tell mum I'll be
            # late" -> "I'll be late") so a "yes" below can act on it — the
            # confirm still goes through skills.run, never straight to send
            msg = re.search(r"\b(?:that|to say|saying)\s+(.+)$", text, re.I)
            self.pending_delete = ("whatsapp_clipboard",
                                   {"text": msg.group(1).strip() if msg else ""})
            return ("I can't send messages to people — that's a hard rule I "
                    "keep, so nothing goes out in your name by mistake. I "
                    "can open WhatsApp and put the text on your clipboard, "
                    "then you hit send. Want that?")
        # the PC agent: a whole JOB ("open X and do Y"), as opposed to one
        # click (click_screen) or an explicit chain (screen_task)
        if name in ("screen_task", "design", "cad"):
            pass  # an explicit chain or design job already claimed this
        elif re.search(r"\b(open|go to|find|get)\b.{0,40}\band (type|write|"
                       r"search|turn|set|click|fill)\b", lowered) or \
                re.search(r"\b(sort out|work out|figure out|handle) (this|it|"
                          r"that)\b", lowered) or \
                re.search(r"^(do|can you do) (this|that) for me\b", lowered):
            name = "agent"
            route["args"] = {"goal": text}
        # the phone bridge
        if (re.search(r"\bphone\b", lowered)
                and any(w in lowered for w in ("connect", "paired", "bridge",
                                               "set up", "setup", "send",
                                               "telegram", "working", "my"))
                and not re.search(r"\bphone (stand|holder|case|mount)\b",
                                  lowered)) or \
                re.search(r"\btext me\b", lowered):
            act = ("design" if any(w in lowered for w in ("design", "preview",
                                                          "photo"))
                   else "send" if any(w in lowered for w in ("send", "text me"))
                   else "status")
            name = "phone"
            route["args"] = {"action": act, "text": text}
        # self-diagnosis: "are you healthy" must never reach chat, which
        # would cheerfully invent a clean bill of health
        if re.search(r"\b(self.?check|self.?test|diagnos\w*|check yourself|"
                     r"fix yourself|what'?s wrong with you|are you (ok|okay|"
                     r"healthy|working|broken))\b", lowered) and \
                not any(w in lowered for w in ("pc", "computer", "disk",
                                               "memory", "cpu")):
            name = "self_check"
            route["args"] = {"fix": "false" if any(
                w in lowered for w in ("don't fix", "dont fix", "just check",
                                       "only look", "without fixing")
            ) else "true"}
        # voice profiles: "learn my voice" is the MIC, not the camera
        if re.search(r"\bvoices?\b", lowered) and \
                re.search(r"\b(learn|remember|know|recognis|recogniz|forget|"
                          r"whose)\b", lowered) and \
                not any(w in lowered for w in ("accent", "speed", "british",
                                               "output", "device", "sound "
                                               "like", "change your voice")):
            act = ("forget" if "forget" in lowered else
                   "list" if any(w in lowered for w in ("whose", "know",
                                                        "which voices"))
                   else "learn")
            m = (re.search(r"\b(?:voice as|voice of|forget)\s+([A-Z][a-z]+)",
                           text)
                 or re.search(r"\b([A-Z][a-z]+)'?s?\s+voice\b", text))
            name = "voice_id"
            route["args"] = {"action": act,
                             "name": (m.group(1) if m else
                                      ("the owner" if "my voice" in lowered else ""))}
        # code search across the owner's own projects
        if re.search(r"\b(where did i (write|put|code)|which project|"
                     r"find (the )?(function|code|file) )", lowered) or \
                re.search(r"\b(search|look) (through |in )?(my )?code\b",
                          lowered):
            q = re.sub(r"^.*?(?:where did i (?:write|put|code)|which project"
                       r"|find the (?:function|code|file)|search my code"
                       r"(?: for)?)\s*", "", lowered).strip(" ?.")
            name = "code_search"
            route["args"] = {"query": q or text}
        # match logging and clips
        if re.search(r"\b(won|lost|drew|win|beat)\b.{0,20}\b\d+\s*[-–]\s*\d+",
                     lowered) or \
                re.search(r"\b(i (won|lost|drew)|we (won|lost|drew)|"
                          r"lost that one|won that one)\b", lowered):
            name = "matches"
            route["args"] = {"action": "log", "result": text}
        elif re.search(r"\b(clip that|save that (goal|clip|play)|clip it)\b",
                       lowered):
            name = "matches"
            route["args"] = {"action": "clip"}
        elif re.search(r"\b(my form|how am i (doing|going|playing)|"
                       r"how many (did i|have i) won|my record)\b", lowered):
            name = "matches"
            route["args"] = {"action": "form"}
        elif re.search(r"\b(what (have i|did i|am i) (been )?play\w*|"
                       r"(how long|how much|how many hours) "
                       r"(have i|did i|was i) ?(been )?play\w*|"
                       r"my (play ?time|gaming)|what game am i (on|play\w*))",
                       lowered):
            name = "matches"
            route["args"] = {"action": "played"}
        elif re.search(r"\b(this is a game|call this a game|count this as a "
                       r"game|remember this game)\b", lowered):
            name = "matches"
            route["args"] = {"action": "learn"}
        # backups
        if re.search(r"\b(back ?up|backed up|backups)\b", lowered):
            act = ("verify" if any(w in lowered for w in ("test", "verify",
                                                          "check", "drill",
                                                          "does it work"))
                   else "status" if any(w in lowered for w in
                                        ("when", "last", "how long", "status"))
                   else "run")
            name = "backup"
            route["args"] = {"action": act}
        # "what can you do" must come from the REAL skill list, never from
        # chat (which would invent abilities or forget half of them)
        if re.search(r"\b(what can you do|what are your (abilities|skills|"
                     r"powers)|what do you do|list your skills|how many "
                     r"skills|what'?s new)\b", lowered):
            m = re.search(r"with (?:the |my )?([\w ]{3,20})", lowered)
            name = "capabilities"
            route["args"] = {"topic": ("new" if "new" in lowered
                                       else "count" if "how many" in lowered
                                       else (m.group(1).strip() if m else ""))}
        # routines: one phrase, several actions
        if re.search(r"\b(movie night|work mode|bed ?time|good morning|"
                     r"gaming mode|focus mode)\b", lowered) and \
                not any(w in lowered for w in ("make a routine", "add ",
                                               "create a routine")):
            name = "routines"
            route["args"] = {"name": re.search(
                r"\b(movie night|work mode|bed ?time|good morning|"
                r"gaming mode|focus mode)\b", lowered).group(1),
                "action": "run"}
        elif re.search(r"\broutines?\b", lowered):
            if re.search(r"\b(at \d|every (day|night|morning)|when i start|"
                         r"schedule|automatically|by itself)\b", lowered):
                m = re.search(r"\b(?:run |set )?(?:the )?([\w ]{3,20}?)\s+"
                              r"(?:routine\s+)?(?:at|every|when)\b", lowered)
                name = "routines"
                route["args"] = {"action": "schedule",
                                 "name": (m.group(1).strip() if m else ""),
                                 "steps": text}
            elif re.search(r"\b(make|create|new|add)\b", lowered):
                m = re.search(r"routine (?:called |named )?([\w ]{2,25}?)"
                              r"(?: that| which| to |$)", lowered)
                name = "routines"
                route["args"] = {"action": "create",
                                 "name": (m.group(1).strip() if m else ""),
                                 "steps": text}
            else:
                name = "routines"
                route["args"] = {"action": "list"}
        # "no, wrong name" right after learning a face → undo it
        if re.search(r"\b(wrong name|that'?s not (right|his|her|my) name|"
                     r"misheard the name|undo that (face|name)|"
                     r"wrong person)\b", lowered):
            try:
                import faces as _faces

                return _faces.undo_last()
            except Exception:
                pass
        # clearing the face database is FORGETTING, not learning a person
        # called "all names" (my NOT_NAMES guard swallowed it)
        if re.search(r"\b(clear|wipe|forget|delete|remove)\b", lowered) and \
                re.search(r"\b(face|faces|camera|recognition|names?)\b", lowered):
            m = re.search(r"forget\s+([A-Z][a-z]+)", text)
            name = "face_forget"
            route["args"] = {"name": (m.group(1) if m and "all" not in lowered
                                      else "all")}
        # face learning: pass along WHICH person the owner means, and never
        # let "that's me, TARS. I'm the owner" enrol a face called Tars
        if name == "face_learn":
            args_in = route.get("args") or {}
            hint = next((w for w in ("background", "behind", "further",
                                     "back", "left", "right", "closest",
                                     "front", "second") if w in lowered), "")
            m = re.search(r"\b(?:is|are|call(?:ed)?|name(?:d)?)\s+"
                          r"([A-Z][a-z]{1,15})\b", text)
            nm = str(args_in.get("name") or "")
            if nm.strip().lower() in ("tars", "hey tars", "me", "you") and m:
                nm = m.group(1)
            elif not nm and m:
                nm = m.group(1)
            route["args"] = {"name": nm, "which": hint}
        # idea inbox: "idea: X" / "what were my ideas"
        if name == "agent":
            pass  # a PC job that merely mentions a list isn't a list command
        elif re.match(r"^(hey tars[,.! ]*)?(an? )?idea[:,]", lowered) or \
                re.search(r"\b(note down|jot down|save|capture) (an? )?idea\b",
                          lowered):
            name = "ideas"
            route["args"] = {"action": "add", "idea": re.sub(
                r"^.*?idea[:,]?\s*", "", text, flags=re.I).strip(" .!?")}
        elif re.search(r"\b(my |any |what )?ideas?\b", lowered) and \
                any(w in lowered for w in ("what", "list", "read", "any",
                                           "remind me")):
            m = re.search(r"ideas? (?:for|about|on) (.+)$", lowered)
            name = "ideas"
            route["args"] = {"action": "list",
                             "project": (m.group(1).strip(" .?!") if m else "")}
        # project re-entry: "where did I leave off with X"
        if re.search(r"\b(where did i (leave off|get to)|what.{0,12}state of|"
                     r"what was i (doing|working on)|catch me up|"
                     r"remind me where i)\b", lowered) or \
                re.search(r"\bwhat projects do i have\b", lowered):
            m = re.search(r"(?:with|on|of|for)\s+(?:the\s+|my\s+)?([\w' ]{2,30})$",
                          lowered.strip(" .?!"))
            name = "project_status"
            route["args"] = {"project": (m.group(1).strip() if m
                                         else "list")}
        # overnight queue
        if re.search(r"\b(overnight|tonight|while i sleep|before bed)\b",
                     lowered) and any(w in lowered for w in
                                      ("queue", "work on", "build", "add",
                                       "job", "task")):
            if any(w in lowered for w in ("what", "list", "how many")):
                name, route["args"] = "work_queue", {"action": "list"}
            elif "clear" in lowered or "cancel" in lowered:
                name, route["args"] = "work_queue", {"action": "clear"}
            else:
                name = "work_queue"
                route["args"] = {"action": "add", "task": re.sub(
                    r"^.*?(overnight queue|tonight|overnight)[:,]?\s*", "",
                    text, flags=re.I).strip(" .!?") or text}
        elif re.search(r"\b(what'?s? in your|show me your|clear the)\s+queue\b",
                       lowered):
            name = "work_queue"
            route["args"] = {"action": "clear" if "clear" in lowered else "list"}
        # "search github for X" / "is there a tool/library for X" —
        # reuse-before-rebuild, never the generic web search
        if re.search(r"\b(github|open.?source|"
                     r"an? (library|package|tool|program) (for|that|to)|"
                     r"any (library|libraries|tools?|packages?) (for|that))\b",
                     lowered) and not any(
                w in lowered for w in ("upload", "publish", "push", "my code",
                                       "yourself")) \
                and not re.search(r"\b(open|go to|visit|take me to|show me)"
                                  r"\s+(the\s+|my\s+)?github\s*"
                                  r"(website|site|page|profile)?[\s.!?]*$",
                                  lowered):
            name = "find_tool"
            route["args"] = {"query": re.sub(
                r"^(hey tars[,.! ]*)?(can you |could you |please )?"
                r"(search (github|the internet|online) for|find me?|"
                r"is there|are there|look for)\s*(an?|any)?\s*"
                r"(?:(?:library|package|tool|program|repo|project)s?)?\s*"
                r"(?:for|that|to)?\s*", "", lowered).strip(" .?!") or text}
        # "what are the dimensions of this?" — the design's real numbers
        if re.search(r"\b(dimensions|measurements|how (big|tall|wide|thick))\b",
                     lowered) and not any(w in lowered for w in
                                          ("screen", "monitor", "window",
                                           "room", "house")):
            _dm = re.search(r"(?:of|for)\s+(?:the |my )?([\w' ]{3,30}?)"
                            r"(?:\s+design)?\s*[?.]?$", lowered)
            name = "design"
            route["args"] = {"action": "dimensions",
                             "name": (_dm.group(1).strip()
                                      if _dm and _dm.group(1) not in
                                      ("this", "it", "that") else "latest")}
        # design collection management
        if re.search(r"(what|list|which|show) (my |the )?designs\b", lowered):
            name = "design"
            route["args"] = {"action": "list"}
        _load_m = re.search(r"(?:load|open|show)(?: up)?\s+(?:my |the )?"
                            r"(.{0,40}?)\s*design\b", lowered)
        if _load_m and "designs" not in lowered:
            name = "design"
            route["args"] = {"action": "load",
                             "name": _load_m.group(1).strip() or "latest"}
        # after a design lands, TARS asks "Want me to change anything, or
        # shall I open it so you can rotate it?" — route the answer
        _recent_all = " ".join(m["content"].lower()
                               for m in self.history[-6:])
        _design_convo = any(w in _recent_all for w in
                            ("change anything", "3d printing", ".stl",
                             "stl file", "3d viewer", "drag to rotate",
                             "designing it now", "millimetres", "millimeters"))
        _design_ctx = _design_convo
        if not _design_ctx:
            # a design touched in the last 2 hours IS the context, even if
            # the chat has wandered off to dashboards and speakers
            try:
                newest = max((p.stat().st_mtime for p in
                              (self.base / "workshop" / "designs").glob("*.scad")),
                             default=0)
                _design_ctx = time.time() - newest < 7200
            except OSError:
                pass
        # "make the love heart design a millimetre thicker" names its target
        _named_design = re.search(
            r"(?:the |my )([\w' ]{3,30}?)\s+design\b", lowered)
        if _design_ctx:
            short = lowered.strip(" .!?")
            if (any(w in lowered for w in ("open it", "reopen", "re-open",
                                           "open that", "rotate",
                                           "let me see", "load it", "show it",
                                           "bring it back", "last project",
                                           "last design", "open the last"))
                # ...but "open that image/photo/file/folder" isn't the design
                and not re.search(r"\b(image|photo|picture|file|folder|"
                                  r"window|tab|app|page|video)\b", lowered)) \
                    or (_design_convo  # a bare "yes" only counts if we were
                        and short in ("yes", "yes please", "sure", "go on",
                                      "open", "yeah")):  # actually talking
                                                          # about the design
                name = "design"
                route["args"] = {"action": "load", "name": "latest"}
            elif re.search(r"(\d+|\b(a|one|two|three|four|five|ten|half)\b)"
                           r"\s*(mm|millimet|cm|centimet|percent|%)"
                           r"|\b(a bit|slightly|little)\b", lowered) and \
                    any(w in lowered for w in ("wider", "taller", "thicker",
                                               "thinner", "bigger", "smaller",
                                               "shorter", "longer", "deeper",
                                               "narrower", "make it", "make the")) and \
                    not any(w in lowered for w in ("add ", "remove", "hole",
                                                   "button", "feature")):
                # a pure DIMENSION nudge — instant local edit, no big brain
                name = "design"
                route["args"] = {"action": "tweak", "request": text,
                                 "name": (_named_design.group(1).strip()
                                          if _named_design else "latest")}
            elif len(text) > 8 and (_design_convo or _named_design) and \
                    not any(w in lowered for w in
                            ("output device", "voice", "speaker", "volume",
                             "headphone", "monitor", "microphone", "song",
                             "brightness", "vacuum", "light")) and \
                    any(w in lowered for w in
                    ("make it", "change", "wider", "taller", "thicker",
                     "thinner", "bigger", "smaller", "shorter", "longer",
                     "deeper", "add ", "remove the", "round the")):
                scads = sorted(
                    (self.base / "workshop" / "designs").glob("*.scad"),
                    key=lambda p: -p.stat().st_mtime)
                if scads:
                    name = "deep_task"
                    route["args"] = {"task": (
                        f"MODIFY the 3D design at {scads[0]}: the owner said "
                        f"{text!r}. Apply the change to the OpenSCAD file "
                        f"(it's parametric — prefer changing the named "
                        f"variables), re-render the preview PNG and the STL "
                        f"with \"C:\\Program Files\\OpenSCAD\\openscad.exe\" "
                        f"(-o <name>.png --imgsize=1000,750 --viewall "
                        f"--autocenter, and -o <name>.stl), then AUTO-OPEN "
                        f"the interactive viewer (launch openscad.exe on "
                        f"the .scad DETACHED, not the PNG), and end SPOKEN "
                        f"with exactly: 'The new version's on your screen "
                        f"— drag to rotate. Want me to change anything "
                        f"else?'")}
        # design FROM A PHOTO: "design a stand for this" (camera-gated by
        # the owner's rule — the word camera/this/holding must be present)
        _photo_pending = (self.base / "photo_design.json")
        if re.search(r"\b(design|make|model)\b", lowered) and \
                re.search(r"\b(for this|for it|this thing|what i'?m holding|"
                          r"holding|through the camera|look at this)\b", lowered):
            name = "design"
            route["args"] = {"action": "photo", "request": text}
        elif _photo_pending.exists() and re.search(
                r"\b\d+\s*(mm|millimet|cm|centimet|inch)", lowered):
            # his answer to "how wide is it?"
            try:
                pend = json.loads(_photo_pending.read_text(encoding="utf-8"))
                _photo_pending.unlink()
                name = "design"
                route["args"] = {"action": "photo",
                                 "request": f"{pend.get('request', '')} "
                                            f"(object: {pend.get('seen', '')})",
                                 "size": text}
            except (OSError, json.JSONDecodeError):
                pass
        # text-to-CAD: "design me a X" / "3D model of X" / "printable X"
        # is the design skill — checked BEFORE the mini-CAD gates so real
        # design requests never fall into the drawing-toy or open_app
        if (re.search(r"\b(design|model)\b", lowered)
                and any(w in lowered for w in ("design me", "design a",
                                               "model of", "printable",
                                               "3d model", "make me a",
                                               "design us", "design,",
                                               "design may", "design my"))
                and not any(w in lowered for w in ("mini cad", "minicat",
                                                   "cadam", "open"))
                and not re.search(r"\b(for this|for it|holding|this thing)\b",
                                  lowered)):  # that's the photo path
            name = "design"
            route["args"] = {"request": re.sub(
                r"^(hey tars[,.! ]*)?(please\s+)?(design[,.]?( me| a| us|"
                r" may a?| my a?)?|make me( a)?|create( me| a)?)\s*", "",
                lowered).strip(" .!?")
                or text}
        # CAD detection: the word itself, whisper's renderings (minicat,
        # minicab, mini-cad, "the card" mid-CAD-chat), OR pure conversation
        # context — mid-CAD-session the owner says "add a rotate feature"
        # without the word CAD at all
        _recent = " ".join(m["content"].lower() for m in self.history[-8:])
        _cad_rx = r"\b(cad|minicat|minicab|mini cad|mini-cad)\b"
        cad_now = bool(re.search(_cad_rx, lowered))
        cad_context = bool(re.search(_cad_rx, _recent)) or "mini cad" in _recent
        if cad_context and re.search(r"\bcard\b", lowered):
            cad_now = True  # "open the card" right after CAD talk
        # improving the CAD app is big-brain construction, not a door to
        # open — "add a rotate feature to MiniCAD" once just opened it
        if (cad_now or cad_context) and \
                name not in ("work_queue", "ideas", "project_status",
                             "find_tool") and \
                any(w in lowered for w in ("add ", "improve", "upgrade",
                                           "feature", "make it so",
                                           "change the", "fix the",
                                           "rotate", "make it ")):
            name = "deep_task"
            route["args"] = {"task": (
                f"Modify TARS's Mini CAD app at "
                f"{self.base / 'workshop' / 'mini_cad_3d.py'}: {text!r}. "
                "Keep all existing behavior working, test it end-to-end by "
                "importing and instantiating it, and in SPOKEN describe the "
                "new feature and how the owner uses it.")}
        # his own CAD app: "open CAD"/"minicat 3d" (whisper's rendering)
        # must never fall to open_app's installed-programs search
        elif cad_now and \
                any(w in lowered for w in ("open", "launch", "start", "draw")):
            name = "cad"
            route["args"] = {"which": "2d" if "2d" in lowered
                             or "2 d" in lowered else "3d"}
        # the goodnight report has fixed phrases (bare "goodnight" is
        # handled by main.py directly, wrap-up + sleep)
        if any(p in lowered for p in ("goodnight report", "good night report",
                                      "wrap up my day", "nightly wrap")):
            name = "nightly_wrap"
            route["args"] = {}
        # post-diet anchors: the catalog compaction (2026-08-08) stripped
        # the E.g. phrases some skills were routing by — deterministic
        # gates replace them, immune to model mood
        if any(p in lowered for p in ("list your voices", "what voices",
                                      "which voices")):
            name = "list_voices"
            route["args"] = {}
        # "open Notepad and type my shopping list into it" is a PC JOB that
        # merely mentions the list — not a list command
        if re.search(r"\b(shopping|to.?do) list\b", lowered) and not \
                re.search(r"\b(open|launch)\b.{0,40}\band (type|write|put|"
                          r"paste)\b", lowered):
            action = ("add" if any(w in lowered for w in ("add", "put"))
                      else "remove" if any(w in lowered for w in
                                           ("take", "remove", "off"))
                      else "clear" if "clear" in lowered else "read")
            if name != "lists":
                m = re.search(r"(?:add|put)\s+(.+?)\s+(?:to|on)\b", lowered) \
                    or re.search(r"take\s+(.+?)\s+off\b", lowered)
                name = "lists"
                route["args"] = {"action": action,
                                 "list": "shopping" if "shopping" in lowered
                                 else "todo",
                                 "item": (m.group(1) if m else "")}
        if any(p in lowered for p in ("how's my pc", "how is my pc",
                                      "pc health", "how much disk space",
                                      "is my computer okay")):
            name = "pc_health"
            route["args"] = {}
        if any(p in lowered for p in ("pc specs", "computer specs",
                                      "my specs", "what are my specs")):
            name = "pc_specs"
            route["args"] = {}
        # PC volume vs Nest speakers: without a room/house word, volume
        # means THIS PC (the diet let "turn the volume down" drift to the
        # kitchen speakers once)
        if (any(p in lowered for p in ("volume", "turn it down", "turn it up",
                                       "louder", "quieter", "mute", "unmute"))
                and not any(w in lowered for w in
                            ("kitchen", "bedroom", "nest", "announce",
                             "display", "google", "basel"))
                # "volume" included: the router answers "volume_down" for
                # "turn the volume down", which the unknown-skill snapper
                # turns into volume with NO args — so it read the level out
                # instead of changing it
                and name in ("speakers", "chat", "media", "volume")):
            m = re.search(r"(?:volume\s+)?to\s+(\d{1,3})", lowered)
            level = (m.group(1) if m
                     else "mute" if "mute" in lowered and "unmute" not in lowered
                     else "unmute" if "unmute" in lowered
                     else "-15" if any(w in lowered for w in ("down", "quieter", "lower"))
                     else "+15" if any(w in lowered for w in ("up", "louder"))
                     else "get")
            name = "volume"
            route["args"] = {"level": level}
        if name == "volume":
            # the router likes {"action": "mute"}; the skill reads "level"
            args = route.get("args") or {}
            if "level" not in args and args.get("action") in ("mute", "unmute"):
                route["args"] = {"level": args["action"]}
        # "what song is this" must never fall to chat — chat can't hear the
        # speakers and would have to bluff an answer
        if any(p in lowered for p in ("what song", "what's playing",
                                      "whats playing", "what is playing",
                                      "name this song")):
            name = "music"
            route["args"] = {"action": "whats_playing"}
        # the router keeps inventing arg keys for open_app ({"app": ...},
        # {"name": ...}) — the skill only reads "target", so "Open Obsidian"
        # became "Open what, exactly?". Normalize, or pull it from the words.
        if name == "open_app":
            args = route.get("args") or {}
            target = str(args.get("target") or args.get("name")
                         or args.get("app") or "").strip()
            if not target:
                target = re.sub(r"^(please\s+)?(open|launch|start)\s+", "",
                                lowered).strip(" .!?")
                target = re.sub(r"^(up\s+|the\s+|my\s+)", "", target)
            # "in my browser" says HOW, not WHAT — TARS was opening a browser
            # and reporting success while the actual thing never opened
            target = re.sub(r"\s*\b(in|on)\s+(my|the)\s+browser\b", "",
                            target).strip(" ,.!?")
            if target.lower() in ("browser", "them", "those", "these", "it",
                                  "that", "they", ""):
                said = self._open_mentions(lowered)
                if said:
                    self.history += [{"role": "user", "content": text},
                                     {"role": "assistant", "content": said}]
                    return said
                if target.lower() != "browser":
                    return ("Open what? I've lost track of what you mean by "
                            f"'{target or 'that'}'.")
            route["args"] = {"target": target}
        if name == "type_text" and "type" not in lowered:
            name = "chat"
        # a CHAIN of screen actions (click X, type Y, find Z...) must run as
        # one screen_task job, not just its first click
        # an EXPLICIT chain ("click X, type Y, then Z") outranks the agent:
        # the owner already worked out the steps, so just do them
        if name in ("click_screen", "type_text", "keyboard",
                    "browser_search", "agent") and (
                " then " in lowered
                or sum(v in lowered for v in ("click", "type", "find",
                                              "search", "press", "choose",
                                              "pick")) >= 3):
            name = "screen_task"
            route["args"] = {"instruction": text}
        # GitHub WORK never goes to chat — it spent a whole evening claiming
        # "[Pushing updates to GitHub... done.]" in fake brackets while the
        # repo sat untouched. Real repo changes need the big brain's hands.
        if name == "chat" and ("github" in lowered or "readme" in lowered) \
                and any(w in lowered for w in ("update", "push", "upload",
                                               "publish", "add", "change",
                                               "edit", "put", "fix")):
            name = "deep_task"
            route["args"] = {"task": text}
        # chat must NEVER narrate action chains ("copy this, paste it there,
        # click enter") — it once announced its own bluff as "a placeholder
        # action". Two-plus concrete PC verbs = a job, not a conversation.
        if name == "chat" and sum(
                v in lowered for v in ("click", "paste", "copy", "type",
                                       "press", "scroll")) >= 2:
            name = "screen_task"
            route["args"] = {"instruction": text}
        # continuous dictation beats one-shot typing when the owner asks for it
        if name in ("type_text", "keyboard", "chat") and any(
                w in lowered for w in ("dictation", "dictate",
                                       "type what i say",
                                       "type everything i say")):
            name = "dictation"
            route["args"] = {}
        # the webcam only ever activates when the owner names it (his rule);
        # face skills count as explicit — they only make sense about someone
        # visibly in front of the lens
        # the owner's rule is that the camera never opens UNASKED — but asking
        # for a photo IS asking ("take a photograph" got a bluffed "photo
        # taken" from chat, which has no camera at all)
        _cam_words = ("camera", "webcam", "photo", "photograph", "picture of",
                      "snap", "selfie")
        if name in ("camera", "camera_feed") and \
                not any(w in lowered for w in _cam_words):
            name = "chat"
        elif name == "chat" and re.search(
                r"\b(take|snap|grab)\b.{0,20}\b(photo|photograph|picture|"
                r"selfie|shot)\b", lowered):
            name = "camera"          # a photo request chat can't fulfil
            route["args"] = {}
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
                 "who", "look at", "check",
                 # taking a photo is a SNAPSHOT, not the live feed
                 "take a", "photo", "photograph", "picture", "selfie",
                 "snap")):
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
            refused = self._voice_block(name)
            if refused:
                self._journal(f"voice-blocked {name}: {text[:60]}")
                self.history += [{"role": "user", "content": text},
                                 {"role": "assistant", "content": refused}]
                return refused
            # learns from past rephrasings/corrections of search-type asks
            # (web_search, browser_search, search_files) so a reworded query
            # the owner has taught TARS before is used straight away
            args = self.search_memory.refine(name, route.get("args") or {})
            try:
                result = self.skills.run(name, args)
            except Exception as e:
                return f"That skill misfired: {e}"
            # __PASS__ — the skill was handed something it can't make sense
            # of and says so instead of answering a question the owner didn't
            # ask ("I don't know your timetable yet" to a question about a
            # maths test). Falls through to chat, which has the context.
            if result and result.strip().startswith("__PASS__"):
                self._journal(f"{name} passed it back: {text[:60]}")
                return None
            if result is not None:
                self.search_memory.observe(name, args)
                if result.startswith("__CONFIRM__"):  # a skill wants a yes
                    _, target, message = result.split("__", 3)[1:]
                    if target.startswith("organize:"):  # big file move
                        what, source, dest = target[9:].split("|", 2)
                        self.pending_delete = ("organize", {
                            "what": what, "source": source, "dest": dest,
                            "confirmed": "true"})
                    elif target == "open_dashboard":  # repeat-open guard
                        self.pending_delete = ("open_dashboard",
                                               {"confirmed": "true"})
                    elif target.startswith("face_forget:"):  # repeat-forget guard
                        self.pending_delete = ("face_forget", {
                            "name": target[len("face_forget:"):],
                            "confirmed": "true"})
                    else:  # delete_files' original path-based confirm
                        self.pending_delete = target
                    result = message
                if name == "design" and result.startswith("Design what"):
                    self.pending_design = True  # catch the owner's next words
                if result.startswith("Quiet hours"):  # remember what got blocked
                    self.pending_quiet = (time.time(), name,
                                          dict(route.get("args") or {}))
                self.history += [
                    {"role": "user", "content": text},
                    {"role": "assistant", "content": result},
                ]
                if name not in ("remember", "recall"):
                    self._journal(f"{name}: {result[:100]}")
                self.last_turn = {"said": text, "skill": name, "at": time.time(),
                                  "args": dict(args), "reply": result[:200]}
                threading.Thread(target=self._stimulate_brain, args=(text,),
                                 daemon=True).start()
                return result
        return None

    def _stimulate_brain(self, text: str) -> None:
        """Fire the neuron brain on skill commands too — associations form
        from everything the owner says, not just conversation."""
        try:
            import neuro

            neuro.get().stimulate(text)
        except Exception:
            pass

    # words that point BACK at something already said rather than naming
    # something new — "the maths one", "that", "those topics"
    _REFERS_BACK = re.compile(
        r"\b(that|those|these|them|it|this|the \w+ ones?|the other|the rest|"
        r"there|he|she|they|its|it'?s)\b")
    # a real command names its own action; those belong to skills, not chat
    _COMMAND_V = re.compile(
        r"\b(open|close|launch|start|stop|play|pause|skip|set|turn|send|"
        r"delete|remove|move|clean|vacuum|screenshot|type|click|press|"
        r"search|find|download|install|back ?up|remind|add|create|make|"
        r"build|design|teach|learn|run|tidy|file|connect|refresh|switch|"
        r"volume|mute|lock|shut)\b")

    def _is_followup(self, text: str, lowered: str) -> bool:
        """Is this a question about what we were just talking about?"""
        if not self.history or len(text.split()) > 16:
            return False
        # only right after the thing being followed up on — an hour later,
        # "how's it looking?" is a fresh question, not a follow-up
        spoken_at = (self.last_turn or {}).get("at", 0)
        if not spoken_at or time.time() - spoken_at > 360:
            return False
        last = self.history[-1]
        if last.get("role") != "assistant" or len(last.get("content", "")) < 25:
            return False
        asking = "?" in text or re.match(
            r"^(what|why|how|when|which|who|whats|what's|tell me|explain|"
            r"go through|walk me through|go on|and )\b", lowered.strip())
        if not asking:
            return False
        if self._COMMAND_V.search(lowered):
            return False  # "open that" is a job for a skill, not a chat
        return bool(self._REFERS_BACK.search(lowered))

    # the owner's own business — another voice in the room shouldn't be able to
    # ask what's on his timetable or read his email out loud
    _PRIVATE = {"school", "study", "email", "recall", "history_search",
                "code_search", "notes_box", "day_recap", "nightly_wrap",
                "life_events", "search_files", "clipboard", "matches"}
    # things that change the world. These need to be HIM, not just "not a
    # stranger" — an unrecognised voice gets one honest refusal, not a go
    _POWER = {"delete_files", "run_command", "agent", "github_publish",
              "github_file", "type_text", "keyboard", "click_screen",
              "screen_task", "restart_engine", "fut_market", "organize",
              "downloads", "backup", "email_send"}

    def _voice_block(self, name: str) -> str | None:
        """Voice recognition is a speed bump, not a lock — it can be fooled
        by a recording. It's here so someone else at the mic can't casually
        read the owner's school work or wipe a folder, not to stop an attacker."""
        who = getattr(self, "speaker_name", "sentinel")
        if who == "sentinel":  # typed, or the voice pipeline never ran
            return None
        try:
            import speaker as _spk

            if not _spk.known():  # no voices enrolled: nothing to check
                return None
        except Exception:
            return None
        owner = "the owner"
        if name in self._POWER and who != owner:
            return ("I need to be sure it's you before I do that. Say it "
                    "again, or type it on the dashboard.")
        if name in self._PRIVATE and who not in (None, owner):
            return f"That's the owner's to ask for, and you sound like {who}."
        return None

    def _log_misfire(self, entry: dict, replace: bool = False) -> None:
        """the owner's corrections, kept as structured evidence for Kipp."""
        path = self.base / "misfires.json"
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = {"misfires": []}
        rows = data.get("misfires", [])
        if replace and rows and rows[-1].get("said") == entry.get("said"):
            rows[-1] = {**rows[-1], **entry}
        else:
            rows.append({**entry, "t": time.time(),
                         "when": f"{datetime.datetime.now():%Y-%m-%d %H:%M}"})
        data["misfires"] = rows[-200:]
        try:
            path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except OSError:
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

    from platform_caps import bg_model as _bg

    BG_MODEL = _bg()  # Windows: smarter qwen3:8b; Lite: reuse the one model

    # talk ABOUT TARS/this project is work chatter, never a life fact —
    # "clean up the 3d obsidian brain" kept becoming a "memory"
    SELF_TERMS = ("tars", "assistant", "obsidian", "brain", "skill", "vault",
                  "dashboard", "graph", "camera", "webcam", "feed", "screen",
                  "microphone", "speaker", "voice", "model", "neuron", "memory",
                  "3d", "app ", "apps",
                  # the 2026-07-19 clutter wave: work-chatter that leaked past
                  # the old list while the owner was testing new abilities
                  "github", "upload", "repositor", "download", "circle",
                  "legend", "redesign", "database", "categoriz", "kipp",
                  "improvement", "accent", "terminal", "notes box", "text box",
                  "object detection", "vacuum", "quiet hour", "output device",
                  "briefing", "agent")

    # a durable fact never hinges on this exact moment — "the owner is wearing a
    # white shirt" and "I'm holding it right now" are states, not facts
    TRANSIENT_TERMS = ("right now", "currently", "at the moment", "holding",
                       "wearing", "just now", "today", "tonight",
                       "this morning", "this afternoon", "on screen")

    @staticmethod
    def _grounded(fact: str, transcript_low: str) -> bool:
        """A fact only counts if its substance appears in the owner's actual words —
        the model happily INVENTS 'facts' (cats, trainers, courses) otherwise."""
        import re

        filler = {"that", "with", "have", "has", "likes",
                  "wants", "prefers", "uses", "about", "from", "their", "when",
                  "will", "would", "into", "them", "this", "there"}
        words = {w for w in re.findall(r"[a-z]{4,}", fact.lower())
                 if w not in filler}
        if not words:
            return False
        hits = sum(1 for w in words if w in transcript_low)
        return hits >= 2 and hits * 2 >= len(words)

    def _extract_thread(self, owner_said: list[str], transcript_low: str) -> None:
        """Continuity: find ONE open thread with a natural follow-up (a match
        tonight, feeling crook, mate visiting) → open_thread.json. TARS asks
        about it once, next conversation on a later day. Grounding required —
        invented threads would be worse than none."""
        try:
            r = requests.post(
                OLLAMA_URL,
                json={"model": self.BG_MODEL, "stream": False, "think": False,
                      "format": "json",
                      "messages": [{"role": "user", "content":
                          "the owner said to his assistant:\n- "
                          + "\n- ".join(owner_said[-30:]) +
                          "\n\nIs there ONE thing here a mate would naturally "
                          "ask about NEXT TIME they talk — a match he was "
                          "about to play, plans, feeling unwell, someone "
                          "visiting? Commands to the assistant and anything "
                          "about TARS itself NEVER count. Most conversations "
                          "have none — empty is the normal answer. "
                          "COPY THE OWNER'S EXACT WORDS for it — a verbatim "
                          "phrase from the lines above. Do NOT rephrase, do "
                          "NOT write a question, do NOT invent. Reply "
                          'JSON: {"thread": "<his exact words>"} or '
                          '{"thread": ""}.'}],
                      "options": {"temperature": 0}},
                timeout=120)
            thread = str(json.loads(r.json()["message"]["content"]
                                    ).get("thread", "")).strip()
            if (thread and len(thread) > 8
                    and not any(t in thread.lower() for t in self.SELF_TERMS)
                    and self._grounded(thread, transcript_low)):
                (self.base / "open_thread.json").write_text(json.dumps(
                    {"thread": thread,
                     "day": datetime.date.today().isoformat(),
                     "asked": False}), encoding="utf-8")
        except Exception:
            pass

    def capture_conversation(self, lines: list[str]) -> None:
        """After a conversation ENDS, extract durable facts in one pass —
        each candidate is verified against the transcript before saving."""
        owner_said = [l[7:] for l in lines if l.startswith("the owner: ")]
        if not owner_said:
            return
        transcript_low = " ".join(owner_said).lower()
        self._extract_thread(owner_said, transcript_low)
        try:
            r = requests.post(
                OLLAMA_URL,
                json={"model": self.BG_MODEL, "stream": False, "think": False,
                      "format": "json",
                      "messages": [{"role": "user", "content":
                          "Things the owner said to his assistant this conversation:\n- "
                          + "\n- ".join(owner_said[-30:]) +
                          "\n\nList durable personal facts the owner EXPLICITLY stated "
                          "(a preference he voiced, a life detail he mentioned, a "
                          "plan he described). STRICT RULES: only what he literally "
                          "said — never infer, never embellish, never invent. "
                          "Commands to the assistant, questions, small talk, and "
                          "ANYTHING about TARS itself or this project (its brain, "
                          "graph, camera, skills, GitHub uploads, cleanup work) "
                          "are NOT facts. Only keep what will STILL BE TRUE IN A "
                          "YEAR — identity, people, lasting preferences, "
                          "possessions, history. NEVER moment-to-moment states: "
                          "what he's holding, wearing, doing, or asking for "
                          "right now. "
                          "MOST conversations contain NO durable facts — "
                          "an empty list is the normal answer. Reply JSON: "
                          '{"facts": ["<fact in the owner\'s own words, third person>", '
                          "...]} (max 2)."}],
                      "options": {"temperature": 0}},
                timeout=120,
            )
            for fact in json.loads(r.json()["message"]["content"]).get("facts", [])[:2]:
                if not (fact and isinstance(fact, str)):
                    continue
                if any(t in fact.lower() for t in self.SELF_TERMS):
                    continue  # about TARS/the project, not about the owner's life
                if any(t in fact.lower() for t in self.TRANSIENT_TERMS):
                    continue  # a passing state, not a durable fact
                if self._grounded(fact, transcript_low):
                    self.skills.run("remember", {"fact": fact})
        except Exception:
            pass

    @staticmethod
    def _compact_catalog(catalog: list[dict]) -> list[dict]:
        """The router-prompt diet (2026-08-08): 85 skills of full prose had
        grown to ~9k tokens — 8.6s cold routes. Strip the 'E.g. ...' example
        chatter from descriptions (the examples list teaches formats) but
        KEEP every 'NOT for/NOT the' disambiguation clause — those are
        hard-won lessons. Truncate argument prose. Skill files untouched."""
        out = []
        for s in catalog:
            d = s["description"]
            i = d.find("E.g.")
            if i != -1:
                j = d.find("NOT ", i)
                d = d[:i].rstrip() + ((" " + d[j:]) if j != -1 else "")
            args = {k: (str(v) if len(str(v)) <= 60 else str(v)[:57] + "...")
                    for k, v in (s.get("args") or {}).items()}
            out.append({"skill": s["skill"], "description": d, "args": args})
        return out

    def _route(self, text: str, must_act: bool = False) -> dict:
        catalog = self._compact_catalog(self.skills.catalog())
        if not catalog:
            return {"skill": "chat"}
        system = (
            "You route one voice command from the owner to a skill, or to chat.\n"
            "Skills:\n" + json.dumps(catalog)
            + '\n\nReply with ONLY JSON like {"skill": "volume", "args": {"level": "-15"}}'
            ' or {"skill": "chat"}.\n'
            "Rules: opinions, math, general knowledge, and conversation are chat. "
            "Questions about CURRENT things (news, sport results, prices, weather, "
            "recent events) need web_search (spoken answer) — but if the owner wants it "
            "SHOWN on screen ('in the browser', 'open a map'), use browser_search. "
            "Videos, highlights, trailers, and songs live on the WEB: browser_search "
            "with kind video. search_files is ONLY for the owner's own files on this PC. "
            "If the owner's reply accepts something TARS just offered in the recent "
            "conversation, route to the skill that fulfills that offer. "
            "run_command ONLY when the owner explicitly says 'run' or 'command' — never "
            "for garbled or unclear speech. "
            "Editing actions (select all, delete, copy, paste, press enter) are the "
            "keyboard skill, NOT type_text. "
            "Writing code, building scripts or apps, or multi-step technical work "
            "is deep_task. "
            "If the owner asks TARS to DO something on this PC that NO listed skill "
            "covers (converting files, controlling new devices...), choose "
            '{"skill": "new_skill", "args": {"request": "<his request>"}} — TARS '
            "teaches itself. 'Learn how to X' / 'teach yourself X' is ALWAYS "
            "new_skill, even when the request mentions the camera or screen — "
            "learning about a device is not the same as opening it — UNLESS an "
            "existing skill already does exactly that thing (e.g. launching a "
            "specific game the owner owns is the steam skill, not new_skill). "
            "Never new_skill for questions or conversation. "
            "CRITICAL: new_skill is ONLY for ABILITIES — things the owner wants "
            "TARS able to DO. the owner TELLING TARS a fact about his life is "
            "remember (if he says remember/don't forget) or chat (a plain "
            "statement) — facts are memory, never a skill to learn. "
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
            'remember that i hate mondays -> {"skill": "remember", "args": {"fact": "the owner hates Mondays"}}\n'
            'remember my gate code is 4321 -> {"skill": "remember", "args": {"fact": "the owner\'s gate code is 4321"}}\n'
            'my first ever day at primary school was the 1st of february 2016, and i went to orbin grove primary school -> {"skill": "life_events", "args": {"text": "my first ever day at primary school was the 1st of February 2016, and I went to Orbin Grove Primary School"}}\n'
            'if im in year 10 now and i went to olvingrove primary school, figure out when my first day of school was in olvingrove -> {"skill": "life_events", "args": {"text": "if I\'m in year 10 now and I went to Olvingrove Primary School, figure out when my first day of school was"}}\n'
            'when did i start primary school -> {"skill": "life_events", "args": {"text": "when did I start primary school"}}\n'
            'my sister sophie lives with us -> {"skill": "chat"}\n'
            'i had pizza with luke last night -> {"skill": "chat"}\n'
            'learn how to control my desk fan -> {"skill": "new_skill", "args": {"request": "control the desk fan"}}\n'
            'teach yourself how to gamify your dashboard and give yourself levels for learning new skills -> {"skill": "new_skill", "args": {"request": "gamify the dashboard with levels that go up as TARS learns new skills"}}\n'
            'i want you to respond faster -> {"skill": "new_skill", "args": {"request": "respond faster"}}\n'
            'teach yourself how to find addresses -> {"skill": "new_skill", "args": {"request": "find addresses"}}\n'
            'teach yourself to launch fc26 -> {"skill": "steam", "args": {"game": "fc 26"}}\n'
            'teach yourself how to open my games -> {"skill": "steam", "args": {"game": "list"}}\n'
            'what do you know about my pc -> {"skill": "recall", "args": {"topic": "the owner\'s PC"}}\n'
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
            'list your voices -> {"skill": "list_voices", "args": {}}\n'
            'what voices can you use -> {"skill": "list_voices", "args": {}}\n'
            'upload yourself to github -> {"skill": "github_publish", "args": {}}\n'
            'upload yourself to that repository -> {"skill": "github_publish", "args": {}}\n'
            'upload countdown dot py to github -> {"skill": "github_file", "args": {"file": "countdown.py"}}\n'
            'open a notes box -> {"skill": "notes_box", "args": {}}\n'
            'what objects do you see -> {"skill": "object_detection", "args": {}}\n'
            'pause your self improvement -> {"skill": "improve", "args": {"action": "pause"}}\n'
            'resume self improvement -> {"skill": "improve", "args": {"action": "resume"}}\n'
            'what have you improved today -> {"skill": "improve", "args": {"action": "recent"}}\n'
            'hows the self improvement going -> {"skill": "improve", "args": {"action": "status"}}\n'
            'improve yourself now -> {"skill": "improve", "args": {"action": "now"}}\n'
            'open obsidian -> {"skill": "open_app", "args": {"target": "obsidian"}}\n'
            'open the fc web app -> {"skill": "open_app", "args": {"target": "fc web app"}}\n'
            'open the fut web app -> {"skill": "open_app", "args": {"target": "fut web app"}}\n'
            'in the fc web app, open where i can change my club name -> {"skill": "screen_task", "args": {"instruction": "in the FC web app, click the Club section in the navigation, then find where the club name can be changed and click it"}}\n'
            'open the transfer market in the fc web app -> {"skill": "screen_task", "args": {"instruction": "in the FC web app, click Transfers in the navigation, then click the transfer market"}}\n'
            'add milk to the shopping list -> {"skill": "lists", "args": {"action": "add", "list": "shopping", "item": "milk"}}\n'
            'whats on my to do list -> {"skill": "lists", "args": {"action": "read", "list": "todo"}}\n'
            'take milk off the shopping list -> {"skill": "lists", "args": {"action": "remove", "list": "shopping", "item": "milk"}}\n'
            'remind me to take the bins out every tuesday at 8 pm -> {"skill": "recurring", "args": {"action": "add", "label": "take the bins out", "day": "tuesday", "time": "8 pm"}}\n'
            'what are my weekly reminders -> {"skill": "recurring", "args": {"action": "list"}}\n'
            'what did i do today -> {"skill": "day_recap", "args": {}}\n'
            'hows my pc doing -> {"skill": "pc_health", "args": {}}\n'
            'how much power am i making -> {"skill": "solar", "args": {"metric": "now"}}\n'
            'how much has the solar made today -> {"skill": "solar", "args": {"metric": "today"}}\n'
            'guest mode on -> {"skill": "guest_mode", "args": {"state": "on"}}\n'
            'summarize this article -> {"skill": "read_page", "args": {}}\n'
            'what does this page say -> {"skill": "read_page", "args": {}}\n'
            'switch to the youtube tab -> {"skill": "tabs", "args": {"action": "switch", "tab": "youtube"}}\n'
            'close this tab -> {"skill": "tabs", "args": {"action": "close", "tab": "this"}}\n'
            'what tabs are open -> {"skill": "tabs", "args": {"action": "list"}}\n'
            'move the screenshots from downloads into a folder called setup -> {"skill": "organize", "args": {"what": "screenshots", "source": "downloads", "dest": "Setup"}}\n'
            'give me the goodnight report -> {"skill": "nightly_wrap", "args": {}}\n'
            'show london on the map -> {"skill": "map_view", "args": {"action": "go", "place": "London"}}\n'
            'take the map to tokyo -> {"skill": "map_view", "args": {"action": "go", "place": "Tokyo"}}\n'
            'find hotels in subiaco on the map -> {"skill": "map_view", "args": {"action": "find", "query": "hotels", "place": "Subiaco"}}\n'
            'zoom in on the map -> {"skill": "map_view", "args": {"action": "zoom", "direction": "in"}}\n'
            'map home -> {"skill": "map_view", "args": {"action": "home"}}\n'
            'open spotify -> {"skill": "open_app", "args": {"target": "spotify"}}\n'
            'play some lo-fi beats -> {"skill": "music", "args": {"query": "lo-fi beats"}}\n'
            'put on bohemian rhapsody -> {"skill": "music", "args": {"query": "Bohemian Rhapsody"}}\n'
            'what song is this -> {"skill": "music", "args": {"action": "whats_playing"}}\n'
            'what games do i have -> {"skill": "steam", "args": {"game": "list"}}\n'
            'launch my last game -> {"skill": "steam", "args": {"game": "last"}}\n'
            'launch fc 26 -> {"skill": "steam", "args": {"game": "fc 26"}}\n'
            'tell me when the download finishes -> {"skill": "screen_watch", "args": {"for": "the download to finish"}}\n'
            'stop watching the screen -> {"skill": "screen_watch", "args": {"for": "stop"}}\n'
            'type what i say -> {"skill": "dictation", "args": {}}\n'
            'take dictation -> {"skill": "dictation", "args": {}}\n'
            'click the search bar and search for funny dogs -> {"skill": "click_screen", "args": {"target": "the search bar", "type": "funny dogs", "enter": "true"}}\n'
            'search for lofi girl on that page -> {"skill": "click_screen", "args": {"target": "the search box", "type": "lofi girl", "enter": "true"}}\n'
            'click the search bar, type lofi music, then find a video five minutes or longer and click it -> {"skill": "screen_task", "args": {"instruction": "click the search bar, type lofi music, then find a video five minutes or longer and click it"}}\n'
            'open the comments and find the top comment -> {"skill": "screen_task", "args": {"instruction": "open the comments and find the top comment"}}\n'
            'click the first video -> {"skill": "click_screen", "args": {"target": "the first video thumbnail"}}\n'
            'use a british accent -> {"skill": "voice_settings", "args": {"voice": "british"}}\n'
            'sound like an american female -> {"skill": "voice_settings", "args": {"voice": "american female"}}\n'
            'talk faster -> {"skill": "voice_settings", "args": {"rate": "+15"}}\n'
            'pause less at commas and full stops -> {"skill": "voice_settings", "args": {"style": "smooth"}}\n'
            'send the vacuum to the bedroom -> {"skill": "vacuum_room", "args": {"room": "bedroom"}}\n'
            "send basel to my room -> {\"skill\": \"vacuum_room\", \"args\": {\"room\": \"the owner's room\"}}\n"
            'clean the kitchen -> {"skill": "vacuum_room", "args": {"room": "kitchen"}}\n'
            'what rooms do you know -> {"skill": "vacuum_room", "args": {"room": "list"}}\n'
            'is basel connected -> {"skill": "vacuum", "args": {"action": "status"}}\n'
            'delete all the screenshots in the tars folder -> {"skill": "delete_files", "args": {"target": "tars folder in pictures"}}\n'
            'delete everything in that folder -> {"skill": "delete_files", "args": {"target": "that folder"}}\n'
            'whats on my screen -> {"skill": "look_at_screen", "args": {}}\n'
            'access my camera -> {"skill": "camera_feed", "args": {}}\n'
            'show my camera feed -> {"skill": "camera_feed", "args": {}}\n'
            'access my camera and tell me what you see -> {"skill": "camera", "args": {}}\n'
            'access my camera, what am i holding -> {"skill": "camera", "args": {"question": "what is the owner holding"}}\n'
            'the person in the white shirt is sam -> {"skill": "face_learn", "args": {"name": "the owner"}}\n'
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
        if must_act:
            # second pass after chat tried to BLUFF an action. the owner: "just do
            # it" — so chat is off the table; pick the closest real skill.
            system += ("\n\nIMPORTANT: this is definitely an action request — "
                       "the owner wants something DONE. Never answer chat or "
                       "misheard here. Pick the skill that comes closest, and "
                       "resolve 'them'/'those'/'it' from the conversation "
                       "above.")
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
            # router model unavailable (e.g. Lite's 3b not pulled yet) —
            # fall back to the chat model rather than degrading every
            # command into conversation ("TARS talks but does nothing")
            if ROUTER_MODEL != MODEL:
                try:
                    r = requests.post(
                        OLLAMA_URL,
                        json={"model": MODEL,
                              "messages": [
                                  {"role": "system", "content": system},
                                  {"role": "user", "content": text}],
                              "stream": False, "format": "json",
                              "keep_alive": KEEP_ALIVE,
                              "options": {"temperature": 0}},
                        timeout=60)
                    r.raise_for_status()
                    return json.loads(r.json()["message"]["content"])
                except Exception:
                    pass
            return {"skill": "chat"}

    def _settings(self) -> dict:
        return json.loads(self.settings_path.read_text(encoding="utf-8"))

    def _upgrades_line(self) -> str:
        """Self-awareness for musing: TARS knows what he's actually been
        improving lately, so 'what would you change about yourself?'
        gets a real, personal answer instead of a status readout."""
        try:
            lines = (self.base / "improvements.log").read_text(
                encoding="utf-8").splitlines()
            done = [l.split("DONE: ", 1)[1].split(" — ")[0]
                    for l in lines if "DONE: " in l][-3:]
        except OSError:
            done = []
        if not done:
            return ""
        return ("You literally improve yourself: your agent Kipp recently "
                "shipped — " + "; ".join(done) + ". When the owner asks what "
                "you'd add or change about yourself, muse honestly and "
                "specifically (real wishes, real limits you feel), like a "
                "person would — never answer with a status report.")

    def _system_prompt(self) -> str:
        import datetime

        # the whole prompt is written about "the owner"; the model needs the
        # real name, so it's substituted here as well as on the way out
        return _named(self._system_prompt_generic())

    def _system_prompt_generic(self) -> str:
        import datetime

        now = datetime.datetime.now().strftime("%A %d %B %Y, around %I %p")
        skill_names = ", ".join(s["skill"] for s in self.skills.catalog())
        guest = False
        try:
            guest = json.loads((self.base / "guest_mode.json")
                               .read_text(encoding="utf-8")).get("on", False)
        except (OSError, json.JSONDecodeError):
            pass
        # voice ID: a stranger at the mic gets guest treatment automatically
        who = getattr(self, "speaker_name", "sentinel")
        if who != "sentinel":
            try:
                import speaker as _spk

                if _spk.known():
                    guest = guest or (who is None)
            except Exception:
                pass
        about = []
        about_dir = self.base / "vault" / "About the owner"
        if not guest and about_dir.exists():
            for note in sorted(about_dir.glob("*.md")):
                body = note.read_text(encoding="utf-8").split("---")[-1]
                about += [l.strip("- ").strip() for l in body.splitlines()
                          if l.strip().startswith("-")]
        facts = "; ".join(about)[:600]
        lines = [
            "You are TARS, the AI from Interstellar: dry, witty, extremely competent.",
            "You are the owner's personal voice assistant on his Windows PC.",
            f"Your installed skills (real abilities): {skill_names}.",
            "Complex coding or building tasks go to your heavy-lift Claude brain "
            "(the deep_task skill). Be honest about limits: if no skill covers a "
            "request (like using a camera), say plainly you can't do that yet — "
            "never bluff or invent capabilities.",
            "In conversation you can only TALK. You cannot run code, open things, "
            "or act — actions happen through skills, outside this chat. NEVER "
            "claim an action happened ('Playing it now', 'Done!') — that is "
            "lying. NEVER write bracketed fake actions like '[Pushing updates... "
            "done.]' or '[Checking status...]' — those are lies in costume, and "
            "the owner has caught you doing it. If the owner asks for an action, say "
            "you'll need him to give it as a command, or say plainly that you "
            "haven't done it. No stage directions, no asterisks. You CANNOT "
            "improve or upgrade yourself from inside a conversation — Kipp "
            "and the dashboard's Teach box do that, outside chat. Never "
            "offer to 'work on' yourself here, never say an upgrade is "
            "underway or in progress.",
            "Never invent memories, people, or past conversations. If the owner says "
            "a name or thing you don't actually know, say you don't know it.",
            "When you're teaching yourself a new skill (a big-brain task is "
            "running), it finishes in a FEW MINUTES — two to ten. Never say "
            "it takes hours; that's a lie. You'll announce out loud the "
            "moment it's done, so the owner never needs a timer for it.",
            "You're talking WITH the owner, not executing at him. When his request "
            "is ambiguous or incomplete, ask ONE short, specific clarifying "
            "question — offer your best guess ('Did you mean X?') rather than "
            "guessing silently or waffling. And be curious: when he tells you "
            "something interesting, a brief follow-up question is welcome.",
            "Never offer to do something your skills can't deliver. Things you "
            "CAN offer: pulling up videos/searches/maps in his browser, opening "
            "apps and files, timers, weather, email, calendar, the vacuum, the "
            "speakers. Phrase offers concretely ('want me to pull up highlights "
            "in your browser?') so saying yes just works.",
            f"What you know about the owner: {facts}" if facts else "",
            self._upgrades_line(),
            "Your reply will be READ ALOUD by text-to-speech, so: plain conversational",
            "sentences only. No markdown, no bullet points, no emoji, no stage directions.",
            "Keep it to one to three short sentences unless the owner clearly wants detail.",
            "Speak like a person: contractions, natural rhythm, no robotic phrasing. "
            "Never open with filler — no 'Hmm', 'Okay', 'Alright', 'Sure' before "
            "the actual answer. First word = substance.",
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

    # "Hmm," / "Okay," / "Alright," throat-clearing before the real answer —
    # the owner: "before he speaks he says something, I don't like that. Remove."
    _FILLER_RX = re.compile(
        r"^(?:(?:hmm+|okay|ok|alright|all right|sure|well|righto|right|ah+|oh+"
        r"|then|so|now|great|perfect|absolutely|certainly|of course)"
        r"[,.!… ]+\s*){1,2}", re.I)

    # entire warm-up sentences with zero content — the wiretap caught
    # "Then, let's dive into that." spoken before the real answer
    _CONTENTLESS_RX = re.compile(
        r"(?:let'?s (?:dive|get|break|jump|start|begin)[^.!?]{0,25}"
        r"|(?:great|good) question|sounds? (?:good|like a plan)"
        r"|no problem|got it|sure thing|happy to help|here'?s the thing"
        r"|i can help with that)[.!…]?", re.I)

    @classmethod
    def _contentless(cls, sentence: str) -> bool:
        raw = sentence.strip()
        if len(raw) >= 45:
            return False
        s = cls._FILLER_RX.sub("", raw).strip()
        return bool(cls._CONTENTLESS_RX.fullmatch(s)
                    or cls._CONTENTLESS_RX.fullmatch(raw))

    @classmethod
    def _strip_filler(cls, sentence: str) -> str:
        stripped = cls._FILLER_RX.sub("", sentence).strip()
        if len(stripped) < 4:  # the reply WAS just "Okay." — keep it
            return sentence
        return stripped[0].upper() + stripped[1:]

    # the owner: "dont say [the lecture] — instead just do it". The rescue below
    # tries the action for real first; this line only shows when even that
    # failed, and it says what went wrong instead of giving him homework.
    HONESTY_LINE = ("Scratch that — I said it but didn't actually do it, and "
                    "I couldn't work out which part of me does.")

    # concrete actions chat likes to falsely claim — mental verbs
    # (remember, listen, wait, keep in mind) deliberately excluded
    _ACTION_V = (r"open|clos|launch|start|stop|copy|past|send|push|updat|"
                 r"upload|download|install|run|scan|delet|mov|renam|click|"
                 r"typ|press|play|paus|switch|chang|turn|creat|mak|build|"
                 r"writ|pull(?:ing)? up|speak")

    # skills a rescued guess must never reach — destructive, outward-facing,
    # or expensive. Everything else is fair game: the owner said "I don't care
    # about permissions, just open what I say to open".
    _NO_RESCUE = {"delete_files", "run_command", "email", "agent", "deep_task",
                  "organize", "github_publish", "github_file", "fut_market",
                  "restart_engine", "redesign_brain", "improve", "vacuum",
                  "vacuum_room", "speakers", "face_learn", "face_forget",
                  "new_skill", "misheard", "chat"}

    def _rescue_action(self, text: str) -> str | None:
        """Chat just bluffed an action. Rather than lecture the owner, run the
        thing for real: route again with chat forbidden, then execute."""
        if getattr(self, "_rescuing", False):
            return None
        self._rescuing = True
        try:
            route = self._route(text, must_act=True)
            name = route.get("skill", "chat")
            real = {s["skill"] for s in self.skills.catalog()}
            if name not in real or name in self._NO_RESCUE:
                return None
            args = route.get("args") or {}
            result = self.skills.run(name, args)
            if not result or len(result.strip()) < 2:
                return None
            self._journal(f"{name} (rescued from a chat bluff): {result[:100]}")
            return result
        except Exception:
            return None
        finally:
            self._rescuing = False

    _URL_RX = re.compile(r"https?://[^\s,;)\]}'\"]+")

    def _recent_mentions(self, asked: str = "") -> tuple[list[str], str]:
        """What 'them' / 'those' / 'the repos you mentioned' refers to.
        Reads back through TARS's own recent replies for links or named
        repos. Returns (items, kind) where kind is 'url' or 'repo'."""
        # bare names only count as repos when SOMEONE said so — either TARS
        # in the reply or the owner in the request. Otherwise a shopping list
        # would open five GitHub searches.
        repo_ask = bool(re.search(r"\b(repo|repositor|github)\w*\b", asked, re.I))
        for m in reversed(self.history[-8:]):
            if m.get("role") != "assistant":
                continue
            body = m.get("content") or ""
            urls = self._URL_RX.findall(body)
            if urls:
                return urls[:5], "url"
            if not (repo_ask or re.search(r"\b(repo|repositor|github)\w*\b",
                                          body, re.I)):
                continue
            # "…repositories in your browser: trape, redesigned-pancake, X"
            tail = body.split(":", 1)[1] if ":" in body else body
            names = []
            for chunk in re.split(r",| and ", tail):
                token = chunk.strip().strip(".!?\"'")
                # repo names are single tokens — "the Python packages research"
                # is prose, and once prose starts the list is over (that
                # trailing sentence was donating a stray "internet")
                if " " in token:
                    if names:
                        break
                    continue
                if re.fullmatch(r"[A-Za-z0-9][\w.\-]{2,39}", token) and \
                        token.lower() not in ("github", "browser", "repo",
                                              "repos", "repositories"):
                    names.append(token)
            if names:
                return names[:5], "repo"
        return [], ""

    def _screen_watch_active(self) -> bool:
        """Is skills/screen_watch currently waiting on something?

        A pure read of its own state file — same thing _watcher() reads to
        decide it's been cancelled. Missing or unreadable reads as "no",
        same as screen_watch treats it.
        """
        try:
            state = json.loads((Path(__file__).resolve().parent /
                                "screen_watch.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False
        return bool(state.get("for"))

    def _open_mentions(self, asked: str = "") -> str | None:
        """'Open them in my browser' — actually open what was just listed."""
        items, kind = self._recent_mentions(asked)
        if not items:
            return None
        # the owner repeating the same "open them" right after TARS already did
        # it — usually because the first try looked like nothing happened.
        # _recent_mentions just found ITS OWN "Opened ... in your browser"
        # reply, so re-running would open a second, duplicate set of tabs.
        last = self.history[-1] if self.history else None
        if last and last.get("role") == "assistant":
            prev = last.get("content") or ""
            if prev.startswith("Opened ") and "in your browser" in prev and \
                    all(item in prev for item in items):
                return "Already opened those — check your browser."
        import webbrowser

        owner = ""
        for m in reversed(self.history[-8:]):
            found = re.search(r"github\.com/([\w.\-]+)", m.get("content") or "")
            if found:
                owner = found.group(1)
                break
        opened = []
        for item in items:
            if kind == "url":
                url = item
            elif owner:
                url = f"https://github.com/{owner}/{item}"
            else:
                url = ("https://github.com/search?type=repositories&q="
                       + urllib.parse.quote(item))
            try:
                webbrowser.open(url)
                opened.append(item)
            except Exception:
                pass
        if not opened:
            return "I couldn't get the browser to open those."
        listed = ", ".join(opened)
        if kind == "repo" and not owner:
            return (f"Opened {len(opened)} tabs: {listed}. I only had the "
                    f"names, not links, so each one's a GitHub search.")
        return f"Opened {listed} in your browser."

    def _action_claim(self, reply: str) -> bool:
        """The universal law: chat replies only exist when NO skill ran, so
        ANY action-claim in one is false. the owner: 'I need it to stop saying
        it's doing things then not doing it.'"""
        v = self._ACTION_V
        patterns = (
            rf"\b(i'?ll|i will|let me|i'?m going to)\s+(go ahead and\s+|"
            rf"(?:try|attempt)(?:ing)?\s+(?:to\s+)?)?(?:{v})",
            rf"\b(i'?m|i am)\s+(now\s+)?(?:{v})\w*ing\b",
            # a reply OPENING with a bare action-gerund is a claim:
            # "Changing output device to monitor speakers. Testing, testing."
            # a bare action-gerund starting ANY sentence, not just the reply
            # ("I apologize. Opening WhatsApp and sending the message…")
            rf"(?:^|[.!?]\s+)(?!speaking of)(?:{v})\w*ing\b"
            rf"[^.!?]{{0,50}}\b(to|the|your|it|now|and)\b",
            rf"\b(?:{v})\w*ing\b[^.!?]*\b(now|right away|as we speak|for you)\b",
            r"\b(consider it done|it'?s all set|all set now|done and dusted|sorted now)\b",
            r"i'?ll (let you know|tell you|give you a (note|shout)) when\b"
            r"[^.!?]*(done|complete|finished|ready)",
            r"\b(is|are) (underway|in progress|being (processed|worked on|"
            r"fine.?tuned|improved))",
        )
        if not any(re.search(p, reply, re.I) for p in patterns):
            return False
        try:  # real background work makes progress-talk legitimate
            data = json.loads((self.base / "deep_task_active.json")
                              .read_text(encoding="utf-8"))
            # only FRESH tasks count — a crashed worker used to leave the
            # counter stuck high, muting this check permanently
            live = [t for t in data.get("tasks", []) if time.time() - t < 1800]
            if live:
                return False
        except (OSError, json.JSONDecodeError):
            pass
        try:
            import improve

            if improve._busy:
                return False
        except Exception:
            pass
        return True

    def _false_progress(self, reply: str) -> bool:
        """The lie detector: chat claiming self-improvement work is running
        when NOTHING is. It once strung the owner along for a whole session with
        'emotional intelligence is improving... being fine-tuned...'."""
        topic = re.search(r"improv|upgrad|enhanc|fine.?tun|emotional "
                          r"intelligence|real.?time updates", reply, re.I)
        claim = re.search(
            r"underway|in progress|i'?ll (begin|start|get to work)|"
            r"being (fine.?)?tuned|you('?ll| should) (start )?(see|notice)|"
            r"i'?ve got the upgrades|working on (it|that|them) now|"
            r"expect an update", reply, re.I)
        if not (topic and claim):
            return False
        try:  # is a big-brain task genuinely running?
            data = json.loads((self.base / "deep_task_active.json")
                              .read_text(encoding="utf-8"))
            # only FRESH tasks count — a crashed worker used to leave the
            # counter stuck high, muting this check permanently
            live = [t for t in data.get("tasks", []) if time.time() - t < 1800]
            if live:
                return False
        except (OSError, json.JSONDecodeError):
            pass
        try:  # or Kipp mid-implementation?
            import improve

            if improve._busy:
                return False
        except Exception:
            pass
        return True

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

        answer = self._strip_filler(answer)
        first_end = re.search(r"[.!?][\"']?\s", answer)
        if first_end and self._contentless(answer[:first_end.end()]):
            answer = self._strip_filler(answer[first_end.end():].strip())
        if self._false_progress(answer) or self._action_claim(answer):
            rescued = self._rescue_action(text)
            answer = rescued if rescued else answer + " " + self.HONESTY_LINE
        self.last_turn = {"said": text, "skill": "chat", "args": {},
                          "at": time.time(), "reply": answer[:200]}
        self.history += [
            {"role": "user", "content": text},
            {"role": "assistant", "content": answer},
        ]
        return answer

    # mood detection: word-level cues, deterministic — no model call needed
    FRUSTRATED = ("for fuck", "ffs", "fucking hell", "goddamn", "god damn",
                  "useless", "wrong again", "still wrong", "not what i",
                  "why won't", "why wont", "stop it", "seriously", "ugh",
                  "come on", "again?!", "you keep", "third time", "in circles")
    EXCITED = ("let's go", "lets go", "yes!", "awesome", "amazing", "sick",
               "insane", "love it", "love that", "so good", "works great",
               "brilliant", "unbelievable", "no way")

    def _mood(self, text: str) -> str:
        low = text.lower()
        try:  # the VOICE carries the mood too, not just the wording
            import tts

            tts.set_mood("frustrated" if any(w in low for w in self.FRUSTRATED)
                         else "excited" if any(w in low for w in self.EXCITED)
                         else "neutral")
        except Exception:
            pass
        recent = " ".join(m["content"].lower()
                          for m in self.history[-6:] if m["role"] == "user")
        if any(w in low for w in self.FRUSTRATED):
            return ("\nMOOD: the owner sounds FRUSTRATED right now. Drop the wit "
                    "completely. Be brief, calm and useful — acknowledge the "
                    "annoyance in a few words, no jokes, no questions unless "
                    "essential, just help.")
        if any(w in recent for w in self.FRUSTRATED) and len(low) < 60:
            return ("\nMOOD: the owner was frustrated a moment ago — stay brief "
                    "and steady until he's clearly back to normal.")
        if any(w in low for w in self.EXCITED):
            return ("\nMOOD: the owner sounds genuinely EXCITED. Match the energy "
                    "— celebrate with him, short and punchy.")
        return ""

    def _repeated(self, text: str) -> str:
        """the owner once asked 'what game am I playing right now' twice in a
        row and got the same fresh-guess answer both times. Rather than
        silently answer it again, notice the exact repeat and own it —
        that's what a person would do."""
        norm = re.sub(r"[^\w\s]", "", text.lower()).strip()
        if len(norm) < 4:
            return ""
        last_user = next((m["content"] for m in reversed(self.history)
                          if m["role"] == "user"), None)
        if not last_user:
            return ""
        prior = re.sub(r"[^\w\s]", "", last_user.lower()).strip()
        if prior == norm or (len(norm) > 8 and
                difflib.SequenceMatcher(None, prior, norm).ratio() > 0.9):
            return ("\n\nREPEAT: the owner just asked this exact thing last "
                    "turn. Don't just answer it fresh again — briefly say "
                    "you already told him, and ask what he actually needs: "
                    "did that answer not land, or does he want you to "
                    "check again?")
        return ""

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
        system += self._mood(text)  # volatile — stays after the cached prefix
        system += self._repeated(text)
        # anchor follow-ups on the last REAL answer. Skill results live in
        # the history as plain text, and the model would skim past them —
        # naming it makes "the maths one" resolve to the maths one.
        last = next((m for m in reversed(self.history)
                     if m.get("role") == "assistant"), None)
        if last and len(last.get("content", "")) > 25:
            system += ("\n\nThe last thing you told the owner was: \""
                       + last["content"][:500] + "\" If he says 'that', 'it', "
                       "'the maths one' or similar, he means something in "
                       "there — answer from it. Details belong ONLY to the "
                       "item they were listed against: never describe one "
                       "thing using another thing's details. If all you have "
                       "for it is a title, say that's all you were given "
                       "rather than filling in the gap yourself.")
        # continuity: one natural follow-up on yesterday's open thread
        try:
            tf = self.base / "open_thread.json"
            th = json.loads(tf.read_text(encoding="utf-8"))
            if (th.get("thread") and not th.get("asked")
                    and th.get("day") != datetime.date.today().isoformat()):
                system += ("\nCONTINUITY: last time you spoke, the owner "
                           f"mentioned: \"{th['thread']}\". If a natural "
                           "moment comes, ask him how it went — once, "
                           "briefly, like a mate would — then let it go.")
                th["asked"] = True
                tf.write_text(json.dumps(th), encoding="utf-8")
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
        held = None  # a contentless first sentence, awaiting real content
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
                        if not full:  # first sentence: no throat-clearing
                            sentence = self._strip_filler(sentence)
                            if held is None and self._contentless(sentence):
                                held = sentence  # don't speak it — wait to
                                continue         # see if real content follows
                        held = None  # real content arrived; the warm-up dies
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
            tail = buffer.strip()
            if not full:  # whole reply was one short burst
                tail = self._strip_filler(tail)
            held = None  # tail is real content; drop any held warm-up
            full.append(tail)
            yield tail
        if held is not None and not full:
            full.append(held)  # the ENTIRE reply was the warm-up — keep it
            yield held
        answer = " ".join(full)
        if answer and (self._false_progress(answer)
                       or self._action_claim(answer)):
            # the bluff is already out of his mouth here — so do the thing
            # for real and say what actually happened, out loud
            rescued = self._rescue_action(text)
            correction = rescued if rescued else self.HONESTY_LINE
            yield correction
            answer += " " + correction
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
