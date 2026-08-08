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
        from skills_engine import SkillBox
        from search_refine import SearchMemory

        self.skills = SkillBox(base)
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
            f"TEACH YOURSELF A NEW SKILL. Jacob asked TARS: {request!r}.\n"
            f"FIRST, check it against TARS's existing skills below — Jacob has "
            f"gone in circles before from TARS creating overlapping skills for "
            f"jobs an existing one already covered (e.g. a new 'github_upload' "
            f"skill when 'github_publish' already existed). If one of these "
            f"already does this job (even under a different name, e.g. a "
            f"'brightness' skill covers 'dim my screen'), STOP: don't create "
            f"anything, and instead make SPOKEN say which existing skill "
            f"already covers it and the phrase Jacob should use. Only proceed "
            f"past this point if the request is genuinely new.\n"
            f"Existing skills:\n{existing}\n"
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

        # a confirmation is waiting on Jacob's yes/no (deletion or big move)
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
        # Jacob had to re-teach it; asking for an example up front fixes the
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
            # Jacob went in circles (2026-07-19): the router kept proposing
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
                # example app would just duplicate a skill Jacob already has
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
                # plain statements about Jacob's life (no "you/yourself"
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
                    # ("Jacob made you" / "only refer to me as..." both got a
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
                        # is right and Jacob isn't asked to re-teach it
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
        if re.search(r"\b(shopping|to.?do) list\b", lowered):
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
                                       "louder", "quieter", "mute the sound",
                                       "unmute"))
                and not any(w in lowered for w in
                            ("kitchen", "bedroom", "nest", "announce",
                             "display", "google", "basel"))
                and name in ("speakers", "chat", "media")):
            m = re.search(r"(?:volume\s+)?to\s+(\d{1,3})", lowered)
            level = (m.group(1) if m
                     else "mute" if "mute" in lowered and "unmute" not in lowered
                     else "unmute" if "unmute" in lowered
                     else "-15" if any(w in lowered for w in ("down", "quieter", "lower"))
                     else "+15" if any(w in lowered for w in ("up", "louder"))
                     else "get")
            name = "volume"
            route["args"] = {"level": level}
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
            route["args"] = {"target": target}
        if name == "type_text" and "type" not in lowered:
            name = "chat"
        # a CHAIN of screen actions (click X, type Y, find Z...) must run as
        # one screen_task job, not just its first click
        if name in ("click_screen", "type_text", "keyboard",
                    "browser_search") and (
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
        # continuous dictation beats one-shot typing when Jacob asks for it
        if name in ("type_text", "keyboard", "chat") and any(
                w in lowered for w in ("dictation", "dictate",
                                       "type what i say",
                                       "type everything i say")):
            name = "dictation"
            route["args"] = {}
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
            # learns from past rephrasings/corrections of search-type asks
            # (web_search, browser_search, search_files) so a reworded query
            # Jacob has taught TARS before is used straight away
            args = self.search_memory.refine(name, route.get("args") or {})
            try:
                result = self.skills.run(name, args)
            except Exception as e:
                return f"That skill misfired: {e}"
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
                    else:  # delete_files' original path-based confirm
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

    from platform_caps import bg_model as _bg

    BG_MODEL = _bg()  # Windows: smarter qwen3:8b; Lite: reuse the one model

    # talk ABOUT TARS/this project is work chatter, never a life fact —
    # "clean up the 3d obsidian brain" kept becoming a "memory"
    SELF_TERMS = ("tars", "assistant", "obsidian", "brain", "skill", "vault",
                  "dashboard", "graph", "camera", "webcam", "feed", "screen",
                  "microphone", "speaker", "voice", "model", "neuron", "memory",
                  "3d", "app ", "apps",
                  # the 2026-07-19 clutter wave: work-chatter that leaked past
                  # the old list while Jacob was testing new abilities
                  "github", "upload", "repositor", "download", "circle",
                  "legend", "redesign", "database", "categoriz", "kipp",
                  "improvement", "accent", "terminal", "notes box", "text box",
                  "object detection", "vacuum", "quiet hour", "output device",
                  "briefing", "agent")

    # a durable fact never hinges on this exact moment — "Jacob is wearing a
    # white shirt" and "I'm holding it right now" are states, not facts
    TRANSIENT_TERMS = ("right now", "currently", "at the moment", "holding",
                       "wearing", "just now", "today", "tonight",
                       "this morning", "this afternoon", "on screen")

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

    def _extract_thread(self, jacob_said: list[str], transcript_low: str) -> None:
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
                          "Jacob said to his assistant:\n- "
                          + "\n- ".join(jacob_said[-30:]) +
                          "\n\nIs there ONE thing here a mate would naturally "
                          "ask about NEXT TIME they talk — a match he was "
                          "about to play, plans, feeling unwell, someone "
                          "visiting? Commands to the assistant and anything "
                          "about TARS itself NEVER count. Most conversations "
                          "have none — empty is the normal answer. "
                          "COPY JACOB'S EXACT WORDS for it — a verbatim "
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
        jacob_said = [l[7:] for l in lines if l.startswith("Jacob: ")]
        if not jacob_said:
            return
        transcript_low = " ".join(jacob_said).lower()
        self._extract_thread(jacob_said, transcript_low)
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
                          "graph, camera, skills, GitHub uploads, cleanup work) "
                          "are NOT facts. Only keep what will STILL BE TRUE IN A "
                          "YEAR — identity, people, lasting preferences, "
                          "possessions, history. NEVER moment-to-moment states: "
                          "what he's holding, wearing, doing, or asking for "
                          "right now. "
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

    def _route(self, text: str) -> dict:
        catalog = self._compact_catalog(self.skills.catalog())
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
            "learning about a device is not the same as opening it — UNLESS an "
            "existing skill already does exactly that thing (e.g. launching a "
            "specific game Jacob owns is the steam skill, not new_skill). "
            "Never new_skill for questions or conversation. "
            "CRITICAL: new_skill is ONLY for ABILITIES — things Jacob wants "
            "TARS able to DO. Jacob TELLING TARS a fact about his life is "
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
            'remember that i hate mondays -> {"skill": "remember", "args": {"fact": "Jacob hates Mondays"}}\n'
            'remember my gate code is 4321 -> {"skill": "remember", "args": {"fact": "Jacob\'s gate code is 4321"}}\n'
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
                "shipped — " + "; ".join(done) + ". When Jacob asks what "
                "you'd add or change about yourself, muse honestly and "
                "specifically (real wishes, real limits you feel), like a "
                "person would — never answer with a status report.")

    def _system_prompt(self) -> str:
        import datetime

        now = datetime.datetime.now().strftime("%A %d %B %Y, around %I %p")
        skill_names = ", ".join(s["skill"] for s in self.skills.catalog())
        guest = False
        try:
            guest = json.loads((self.base / "guest_mode.json")
                               .read_text(encoding="utf-8")).get("on", False)
        except (OSError, json.JSONDecodeError):
            pass
        about = []
        about_dir = self.base / "vault" / "About Jacob"
        if not guest and about_dir.exists():
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
            "lying. NEVER write bracketed fake actions like '[Pushing updates... "
            "done.]' or '[Checking status...]' — those are lies in costume, and "
            "Jacob has caught you doing it. If Jacob asks for an action, say "
            "you'll need him to give it as a command, or say plainly that you "
            "haven't done it. No stage directions, no asterisks. You CANNOT "
            "improve or upgrade yourself from inside a conversation — Kipp "
            "and the dashboard's Teach box do that, outside chat. Never "
            "offer to 'work on' yourself here, never say an upgrade is "
            "underway or in progress.",
            "Never invent memories, people, or past conversations. If Jacob says "
            "a name or thing you don't actually know, say you don't know it.",
            "When you're teaching yourself a new skill (a big-brain task is "
            "running), it finishes in a FEW MINUTES — two to ten. Never say "
            "it takes hours; that's a lie. You'll announce out loud the "
            "moment it's done, so Jacob never needs a timer for it.",
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
            self._upgrades_line(),
            "Your reply will be READ ALOUD by text-to-speech, so: plain conversational",
            "sentences only. No markdown, no bullet points, no emoji, no stage directions.",
            "Keep it to one to three short sentences unless Jacob clearly wants detail.",
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
    # Jacob: "before he speaks he says something, I don't like that. Remove."
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

    HONESTY_LINE = ("Hold on — honesty check. That was just talk: I haven't "
                    "actually done anything, and this side of me can't. Say "
                    "it as a direct command and the right part of me will "
                    "really do it.")

    # concrete actions chat likes to falsely claim — mental verbs
    # (remember, listen, wait, keep in mind) deliberately excluded
    _ACTION_V = (r"open|clos|launch|start|stop|copy|past|send|push|updat|"
                 r"upload|download|install|run|scan|delet|mov|renam|click|"
                 r"typ|press|play|paus|switch|chang|turn|creat|mak|build|"
                 r"writ|pull(?:ing)? up|speak")

    def _action_claim(self, reply: str) -> bool:
        """The universal law: chat replies only exist when NO skill ran, so
        ANY action-claim in one is false. Jacob: 'I need it to stop saying
        it's doing things then not doing it.'"""
        v = self._ACTION_V
        patterns = (
            rf"\b(i'?ll|i will|let me|i'?m going to)\s+(go ahead and\s+|"
            rf"(?:try|attempt)(?:ing)?\s+(?:to\s+)?)?(?:{v})",
            rf"\b(i'?m|i am)\s+(now\s+)?(?:{v})\w*ing\b",
            # a reply OPENING with a bare action-gerund is a claim:
            # "Changing output device to monitor speakers. Testing, testing."
            rf"^\s*(?!speaking of)(?:{v})\w*ing\b[^.!?]{{0,50}}\b(to|the|your|it|now)\b",
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
            active = json.loads((self.base / "deep_task_active.json")
                                .read_text(encoding="utf-8")).get("count", 0)
            if active > 0:
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
        when NOTHING is. It once strung Jacob along for a whole session with
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
            active = json.loads((self.base / "deep_task_active.json")
                                .read_text(encoding="utf-8")).get("count", 0)
            if active > 0:
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
            answer += " " + self.HONESTY_LINE
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
        recent = " ".join(m["content"].lower()
                          for m in self.history[-6:] if m["role"] == "user")
        if any(w in low for w in self.FRUSTRATED):
            return ("\nMOOD: Jacob sounds FRUSTRATED right now. Drop the wit "
                    "completely. Be brief, calm and useful — acknowledge the "
                    "annoyance in a few words, no jokes, no questions unless "
                    "essential, just help.")
        if any(w in recent for w in self.FRUSTRATED) and len(low) < 60:
            return ("\nMOOD: Jacob was frustrated a moment ago — stay brief "
                    "and steady until he's clearly back to normal.")
        if any(w in low for w in self.EXCITED):
            return ("\nMOOD: Jacob sounds genuinely EXCITED. Match the energy "
                    "— celebrate with him, short and punchy.")
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
        # continuity: one natural follow-up on yesterday's open thread
        try:
            tf = self.base / "open_thread.json"
            th = json.loads(tf.read_text(encoding="utf-8"))
            if (th.get("thread") and not th.get("asked")
                    and th.get("day") != datetime.date.today().isoformat()):
                system += ("\nCONTINUITY: last time you spoke, Jacob "
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
            yield self.HONESTY_LINE  # spoken self-correction, out loud
            answer += " " + self.HONESTY_LINE
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
