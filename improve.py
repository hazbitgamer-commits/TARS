"""Kipp — TARS's self-improvement agent (the owner's "always getting smarter" rule,
2026-07-19). Whenever TARS is idle, Kipp re-reads the recent conversation
transcripts looking for FRICTION — misroutes, misfires, mishearings, the owner
repeating himself, "I can't do that" moments — turns the worst one into an
upgrade proposal (local model, free), has a critic score it, and hands the
good ones to the Claude big brain to actually implement, fully automatically.

Hard safety, in code not prompts:
  - Implementation runs are throttled (IMPLEMENT_GAP + DAILY_CAP) so the owner's
    shared Claude allowance survives; reflection itself is local and free.
  - Every core-file change is preceded by a backup (rule in the task prompt)
    AND main.py snapshots a known-good copy of every root .py to
    backups/last_good/ after each healthy start — boot.py restores from
    there if an upgrade ever breaks TARS so badly he can't boot.
  - Kipp may never touch the vault, faces, notes, logs, credentials, boot.py
    or TARS.bat, and never reads personal content. Voice off-switch:
    "pause self-improvement" (skills/improve).
  - Announcements about upgrades hold during quiet hours (no 3am talking).
"""
import datetime
import difflib
import hashlib
import json
import shutil
import threading
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent
STATE_FILE = BASE / "improve_state.json"
LOG_FILE = BASE / "improvements.log"
LAST_GOOD = BASE / "backups" / "last_good"
OLLAMA_URL = "http://127.0.0.1:11434/api/chat"
from platform_caps import bg_model
MODEL = bg_model()

IDLE_BEFORE_WORK = 10 * 60   # only self-improve after 10 quiet minutes
REFLECT_GAP = 15 * 60        # think about the transcripts at most every 15 min
IMPLEMENT_GAP = 30 * 60      # at most one big-brain upgrade per half hour
DAILY_CAP = 12               # and at most a dozen a day — Claude allowance
INTROSPECT_GAP = 6 * 3600    # the scientist session: every ~6 idle hours

# the owner's "scientist" battery (2026-07-22): Kipp interrogates himself with
# these during introspection, against REAL mined evidence — never vibes.
QUESTIONS = (
    "What task did the owner repeat that should become one command?",
    "What did he repeatedly search or ask for?",
    "Where did he correct me or rephrase because I got it wrong?",
    "What work do I keep making him do manually?",
    "What decision could be automated?",
    "What capability would save the most time, given the evidence?",
    "What knowledge or skill of mine looks stale or unused?",
    "What assumptions of mine failed most often?",
)

_lock = threading.Lock()
_busy = False
_last_tick = 0.0


# ---------------- state ----------------
def _state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save(s: dict) -> None:
    STATE_FILE.write_text(json.dumps(s, indent=1), encoding="utf-8")


def _log(line: str) -> None:
    stamp = datetime.datetime.now().isoformat(timespec="seconds")
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(f"{stamp} {line}\n")


def paused() -> bool:
    return bool(_state().get("paused"))


def set_paused(value: bool) -> None:
    s = _state()
    s["paused"] = bool(value)
    _save(s)
    _log(f"PAUSED set to {value}")


# ---------------- known-good snapshot / rollback support ----------------
def snapshot_last_good() -> None:
    """Called by main.py once TARS has been up and healthy for a minute:
    this running set of core files is proven bootable — keep a copy for
    boot.py to restore if a future self-upgrade bricks the start-up."""
    try:
        LAST_GOOD.mkdir(parents=True, exist_ok=True)
        for f in BASE.glob("*.py"):
            shutil.copy2(f, LAST_GOOD / f.name)
    except OSError:
        pass


# ---------------- transcript mining (deterministic, grounded) ----------------
def _recent_lines(max_lines: int = 300) -> list[dict]:
    lines: list[dict] = []
    today = datetime.date.today()
    for day in (today - datetime.timedelta(days=1), today):
        p = BASE / "logs" / f"{day.isoformat()}.jsonl"
        if not p.exists():
            continue
        for raw in p.read_text(encoding="utf-8").splitlines():
            try:
                lines.append(json.loads(raw))
            except json.JSONDecodeError:
                pass
    return lines[-max_lines:]


def _parse_t(entry: dict) -> float:
    try:
        return datetime.datetime.fromisoformat(entry["t"]).timestamp()
    except (KeyError, ValueError):
        return 0.0


def _signals(lines: list[dict]) -> list[dict]:
    """Friction detectors. Every signal carries EXACT transcript lines as
    evidence — proposals must grow from real events, never invention
    (lesson of the memory-fabrication crisis)."""
    found = []
    heard = [e for e in lines if e.get("kind") == "heard"]
    said = [e for e in lines if e.get("kind") == "said"]

    # 1. self-teaching proposed twice for near-identical requests = the
    #    router missed an existing skill, or a taught skill isn't routing
    teaches = [e for e in said if "Want me to teach myself" in e.get("text", "")]
    for a, b in zip(teaches, teaches[1:]):
        if difflib.SequenceMatcher(None, a["text"], b["text"]).ratio() > 0.6:
            found.append({"kind": "learn-loop", "evidence": [a["text"], b["text"]],
                          "hint": "The intent router proposed teaching a new skill "
                                  "twice for nearly the same request — an existing "
                                  "skill probably already covers it, or the router "
                                  "needs an example for it."})

    # 2. a skill crashed in the owner's face
    for e in said:
        if "That skill misfired" in e.get("text", ""):
            found.append({"kind": "misfire", "evidence": [e["text"]],
                          "hint": "A skill raised an exception during a real "
                                  "command. Find and fix the root cause."})

    # 3. the owner had to repeat himself (same-ish command twice inside 3 min)
    for a, b in zip(heard, heard[1:]):
        if (0 < _parse_t(b) - _parse_t(a) < 180
                and difflib.SequenceMatcher(
                    None, a["text"].lower(), b["text"].lower()).ratio() > 0.75
                and len(a["text"]) > 15):
            found.append({"kind": "repeat", "evidence": [a["text"], b["text"]],
                          "hint": "the owner repeated almost the same command within "
                                  "minutes — the first attempt didn't do what he "
                                  "wanted. Work out why from the replies around it."})

    # 4. capability gaps and refusals
    for e in said:
        text = e.get("text", "")
        if ("I can't" in text or "I don't have a skill" in text) \
                and "Want me to teach myself" not in text:
            found.append({"kind": "gap", "evidence": [text],
                          "hint": "TARS told the owner he couldn't do something. If a "
                                  "small fix or new capability would close the gap "
                                  "safely, that's an upgrade."})

    # 4b. the owner said "that was wrong" — the strongest signal there is,
    #     because he also told us what it SHOULD have done. Beats every
    #     inference in this file: no guessing what went wrong.
    try:
        rows = json.loads((BASE / "misfires.json").read_text(
            encoding="utf-8")).get("misfires", [])
    except (OSError, json.JSONDecodeError):
        rows = []
    for row in rows[-12:]:
        if not row.get("wanted"):
            continue  # unfinished correction — no target to build towards
        found.append({
            "kind": "correction",
            "evidence": [f"the owner said: {row.get('said', '')}",
                         f"TARS ran: {row.get('skill', '?')} "
                         f"{json.dumps(row.get('args', {}))[:120]}",
                         f"TARS replied: {row.get('reply', '')[:120]}",
                         f"the owner wanted: {row['wanted']}"],
            "hint": "the owner explicitly corrected this. Add a DETERMINISTIC gate "
                    "in brain._handle_routed (or fix the skill) so this exact "
                    "phrasing does the right thing — he prefers hard code gates "
                    "over prompt tweaks. Test the old and new phrasings both."})

    # 5. frequent mishearing days deserve STT prompt/gate tuning
    misheard = [e for e in said if "I think I misheard" in e.get("text", "")]
    if len(misheard) >= 3:
        found.append({"kind": "misheard", "evidence":
                      [e["text"] for e in misheard[:3]],
                      "hint": "Speech recognition is stumbling repeatedly today. "
                              "Consider additions to the STT initial prompt or "
                              "the artifact gates in stt.py."})
    return found


def _hash(sig: dict) -> str:
    return hashlib.md5("|".join(sig["evidence"]).encode("utf-8")).hexdigest()[:12]


# ---------------- local-model reflection + critic (free) ----------------
def _ollama(prompt: str, want_json: bool = False) -> str:
    import requests

    body = {"model": MODEL, "stream": False, "think": False,
            "messages": [{"role": "user", "content": prompt}]}
    if want_json:
        body["format"] = "json"
    r = requests.post(OLLAMA_URL, json=body, timeout=180)
    r.raise_for_status()
    return r.json().get("message", {}).get("content", "")


def _reflect() -> None:
    s = _state()
    seen = s.get("seen", [])
    pending = s.get("pending", [])
    fresh = [sig for sig in _signals(_recent_lines())
             if _hash(sig) not in seen]
    if not fresh:
        return
    sig = fresh[0]  # one per reflection — steady, not frantic
    seen.append(_hash(sig))
    s["seen"] = seen[-200:]
    _save(s)

    evidence = "\n".join(f"  TRANSCRIPT: {e}" for e in sig["evidence"])
    try:
        raw = _ollama(
            "You are Kipp, the self-improvement agent inside TARS, a voice "
            "assistant. From this REAL friction found in today's transcripts, "
            "write ONE small, concrete upgrade proposal.\n"
            f"Friction type: {sig['kind']}\n{evidence}\nContext: {sig['hint']}\n"
            'Reply as JSON: {"title": "<max 10 words>", '
            '"fix": "<2-3 sentences: what to change and why>"} '
            "Stay strictly grounded in the transcript lines above — do not "
            "invent events.", want_json=True)
        proposal = json.loads(raw)
        title = str(proposal.get("title", ""))[:80]
        fix = str(proposal.get("fix", ""))[:500]
        if not title or not fix:
            return
        score_raw = _ollama(
            "You are a strict critic inside TARS the voice assistant. Score "
            "this self-upgrade proposal 1-10 for how much it would actually "
            "improve the owner's daily experience (10 = clear real win, 1 = "
            "noise). Reply with ONLY the number.\n"
            f"Proposal: {title} — {fix}\nEvidence:\n{evidence}")
        digits = "".join(c for c in score_raw if c.isdigit())
        score = int(digits[:2] or 0)
    except Exception:
        return

    if score >= 7:
        pending.append({"title": title, "fix": fix, "score": score,
                        "evidence": sig["evidence"], "kind": sig["kind"]})
        s = _state()
        s["pending"] = pending[-10:]
        _save(s)
        _log(f"PROPOSED ({score}/10): {title} — {fix}")
    else:
        _log(f"REJECTED ({score}/10): {title}")
    try:
        import agents

        agents.log_touch("Kipp", [])
    except Exception:
        pass


# ---------------- the owner's overnight work queue ----------------
QUEUE_FILE = BASE / "work_queue.json"
NIGHT_HOURS = (22, 7)  # queue drains between 10pm and 7am


def queue_load() -> list:
    try:
        return json.loads(QUEUE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []


def queue_save(items: list) -> None:
    QUEUE_FILE.write_text(json.dumps(items, indent=1), encoding="utf-8")


def queue_add(task: str) -> int:
    items = queue_load()
    items.append({"task": task, "added": datetime.datetime.now().isoformat(
        timespec="minutes"), "status": "waiting"})
    queue_save(items)
    _log(f"QUEUED: {task[:90]}")
    return len([i for i in items if i["status"] == "waiting"])


def _drain_queue() -> None:
    """One queued job per implement-slot, overnight only — the owner hands TARS
    a list before bed and hears the results in the morning."""
    global _busy
    hour = datetime.datetime.now().hour
    if not (hour >= NIGHT_HOURS[0] or hour < NIGHT_HOURS[1]):
        return
    items = queue_load()
    job = next((i for i in items if i["status"] == "waiting"), None)
    if job is None:
        return
    with _lock:
        if _busy:
            return
        _busy = True
    job["status"] = "running"
    queue_save(items)

    def worker():
        try:
            _implement_worker({"title": job["task"][:60],
                               "fix": job["task"], "evidence": []})
            job["status"] = "done"
        except Exception as e:
            job["status"] = f"failed: {e}"[:80]
        finally:
            queue_save(queue_load()[:0] + items)

    threading.Thread(target=worker, daemon=True).start()


# ---------------- skill spring-cleaning ----------------
def unused_skills(days: int = 14) -> list[str]:
    """Skills that haven't fired in a fortnight — 46 of 83 were idle when
    Kipp first counted. Dead weight slows routing and clutters his head."""
    try:
        from skills_engine import SkillBox

        all_skills = {s["skill"] for s in SkillBox(BASE).catalog()}
    except Exception:
        return []
    used, today = set(), datetime.date.today()
    for back in range(days + 1):
        day = (today - datetime.timedelta(days=back)).isoformat()
        for p in (BASE / "vault" / "Journal" / f"Journal {day}.md",
                  BASE / "logs" / f"{day}.jsonl"):
            if p.exists():
                text = p.read_text(encoding="utf-8", errors="replace").lower()
                used |= {s for s in all_skills if s.lower() in text}
    KEEP = {"chat", "deep_task", "improve", "remember", "recall", "timers",
            "weather", "camera", "camera_feed", "delete_files", "vacuum",
            "calendar", "email", "open_app", "volume", "design", "cad"}
    # a brand-new skill isn't a dead skill — it just hasn't had its turn
    # (this once listed 43 "idle" skills, most of them a day old)
    fresh = set()
    for s in all_skills:
        try:
            age = (datetime.datetime.now().timestamp()
                   - (BASE / "skills" / s / "skill.py").stat().st_mtime)
            if age < 10 * 86400:
                fresh.add(s)
        except OSError:
            continue
    return sorted(all_skills - used - KEEP - fresh)


# ---------------- introspection: the scientist session ----------------
def _week_lines() -> list[dict]:
    lines = []
    today = datetime.date.today()
    for back in range(7, -1, -1):
        p = BASE / "logs" / f"{(today - datetime.timedelta(days=back)).isoformat()}.jsonl"
        if not p.exists():
            continue
        for raw in p.read_text(encoding="utf-8").splitlines():
            try:
                lines.append(json.loads(raw))
            except json.JSONDecodeError:
                pass
    return lines


def _evidence() -> list[str]:
    """Deterministic pattern mining over the last week — real counts only,
    so the model can't invent habits the owner doesn't have."""
    lines = _week_lines()
    heard = [e.get("text", "") for e in lines if e.get("kind") == "heard"]
    said = [e.get("text", "") for e in lines if e.get("kind") == "said"]
    facts = []

    # repeated near-identical commands → automation candidates
    clusters: list[list[str]] = []
    for h in heard:
        key = h.lower().strip(".!? ")
        if len(key) < 12:
            continue
        for c in clusters:
            if difflib.SequenceMatcher(None, key, c[0]).ratio() > 0.8:
                c.append(key)
                break
        else:
            clusters.append([key])
    for c in sorted(clusters, key=len, reverse=True)[:5]:
        if len(c) >= 4:
            facts.append(f"the owner said nearly the same thing {len(c)} times "
                         f"this week: \"{c[0][:80]}\"")

    # corrections right after TARS spoke → wrongness hotspots
    fixes = [h for h in heard if h.lower().startswith(
        ("no,", "no ", "not that", "i meant", "wrong", "that's not"))]
    if len(fixes) >= 3:
        facts.append(f"the owner corrected or redirected me {len(fixes)} times, "
                     f"e.g. \"{fixes[-1][:70]}\"")

    # capability gaps
    cant = [s for s in said if "I can't" in s or "don't have a skill" in s]
    if cant:
        facts.append(f"I told the owner 'I can't' {len(cant)} times this week, "
                     f"most recently: \"{cant[-1][:80]}\"")

    # unused skills → spring-cleaning candidates, named so Kipp can act
    idle = unused_skills()
    if len(idle) >= 8:
        facts.append(f"{len(idle)} skills haven't fired in a fortnight, "
                     f"including: {', '.join(idle[:8])}. Retiring dead "
                     f"weight keeps routing fast (moving a folder to "
                     f"skills_retired/ is how TARS retires a skill).")
    return facts


def _library_scout(facts: list[str]) -> str:
    """the owner's rule — reuse before rebuild: for capability gaps, look for a
    real open-source tool and put THAT in front of him."""
    gap = next((f for f in facts if "I can't" in f), "")
    if not gap:
        return ""
    try:
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "find_tool_skill", BASE / "skills" / "find_tool" / "skill.py")
        ft = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(ft)
        topic = _ollama(
            "In FIVE words or fewer, name the capability missing here — "
            "just the capability, no sentence:\n" + gap)[:60]
        hits = ft.search(topic).get("github", [])[:2]
        if not hits:
            return ""
        return ("Open-source tools that could close this gap: "
                + "; ".join(f"{h['name']} ({h['stars']} stars, {h['lang']}): "
                            f"{h['desc'][:80]}" for h in hits))
    except Exception:
        return ""


def get_proposals() -> list[dict]:
    return _state().get("proposals", [])


def decide(title: str, build: bool) -> bool:
    """the owner clicked BUILD or IGNORE on a proposal card."""
    s = _state()
    proposals = s.get("proposals", [])
    hit = next((p for p in proposals if p.get("title") == title), None)
    if hit is None:
        return False
    if not build:
        hit["status"] = "ignored"
        _save(s)
        _log(f"PROPOSAL IGNORED by the owner: {title}")
        return True
    hit["status"] = "building"
    s["pending"] = [{"title": hit["title"], "fix": hit.get("build", ""),
                     "score": 99, "evidence": [hit.get("why", "")],
                     "kind": "introspection"}] + s.get("pending", [])
    s["last_implement"] = 0  # the owner's click outranks the throttle
    _save(s)
    _log(f"PROPOSAL APPROVED by the owner: {title}")
    _implement()
    return True


def _introspect() -> None:
    """The scientist session: mine a week of evidence, put the question
    battery to the local model, surface up to 2 capability PROPOSALS as
    dashboard cards with Build/Ignore buttons — the owner decides by click."""
    facts = _evidence()
    if not facts:
        return
    scouted = _library_scout(facts)
    if scouted:
        facts.append(scouted)
    s = _state()
    proposals = s.get("proposals", [])
    known = [p["title"].lower() for p in proposals]
    try:
        raw = _ollama(
            "You are Kipp, the self-improvement scientist inside TARS, a "
            "voice assistant on the owner's PC. EVIDENCE mined from this week "
            "(real, counted — trust it):\n"
            + "\n".join(f"- {f}" for f in facts)
            + "\n\nInterrogate the evidence with these questions:\n"
            + "\n".join(f"- {q}" for q in QUESTIONS)
            + "\n\nPropose up to 2 NEW capabilities or automations that the "
            "evidence clearly justifies — things worth building, not "
            "tweaks. Cite the numbers from the evidence in 'why'. If the "
            "evidence justifies nothing, an empty list is the right "
            'answer. Reply JSON: {"proposals": [{"title": "<max 8 words>", '
            '"why": "<1-2 sentences citing the evidence>", '
            '"build": "<2-3 sentences: what to implement>"}]}',
            want_json=True)
        fresh = json.loads(raw).get("proposals", [])[:2]
    except Exception:
        return
    added = 0
    for p in fresh:
        title = str(p.get("title", ""))[:70]
        if not title or any(difflib.SequenceMatcher(
                None, title.lower(), k).ratio() > 0.7 for k in known):
            continue
        proposals.append({"title": title, "why": str(p.get("why", ""))[:300],
                          "build": str(p.get("build", ""))[:400],
                          "status": "offered",
                          "day": datetime.date.today().isoformat()})
        added += 1
        _log(f"PROPOSAL OFFERED: {title} — {p.get('why', '')[:120]}")
    if added:
        s = _state()
        s["proposals"] = proposals[-12:]
        _save(s)
        try:
            import announce

            announce.post(f"Kipp here — I've got {added} new idea"
                          f"{'s' if added > 1 else ''} for you on the "
                          f"dashboard. Build or ignore, your call.",
                          hold_during_quiet=True)
        except Exception:
            pass


# ---------------- big-brain implementation (throttled) ----------------
FORBIDDEN = (
    "vault/, vault_quarantine/, faces/, notes/, logs/ (their CONTENTS are "
    "the owner's personal life — never read or copy them), .env, "
    "google_credentials.json, google_token.json, any *token*/*credential* "
    "file, eufy_openudid.txt, boot.py, TARS.bat, runtime/, models/, "
    "wakeword/, backups/"
)


PROOF = BASE / "workshop" / "kipp_proof.py"


def _editable_files() -> list[Path]:
    """Everything Kipp is allowed to change — the rollback set."""
    files = [p for p in BASE.glob("*.py")]
    files += list((BASE / "skills").glob("*/skill.py"))
    files += [p for p in (BASE / "dashboard").glob("*.html")]
    return files


def _snapshot_tree() -> dict:
    """Contents before Kipp touches anything. Own snapshot deliberately —
    the rollback must not depend on Kipp having obeyed the rule about
    copying originals into backups/auto."""
    out = {}
    for path in _editable_files():
        try:
            out[str(path)] = path.read_bytes()
        except OSError:
            pass
    return out


def _restore_tree(before: dict) -> list[str]:
    """Put back everything that changed. Returns the names restored."""
    undone = []
    for path_text, blob in before.items():
        path = Path(path_text)
        try:
            if path.exists() and path.read_bytes() == blob:
                continue
            path.write_bytes(blob)
            undone.append(path.name)
        except OSError:
            pass
    # a file Kipp CREATED isn't in the snapshot; leave new skills alone but
    # note them, since a half-built skill that never proved itself shouldn't
    # be silently kept either
    return undone


def _verify_proof(started: float) -> tuple[bool, str]:
    """Run Kipp's own proof script. No proof, no DONE."""
    import subprocess
    import sys

    if not PROOF.exists():
        return False, "no proof script was written"
    try:
        if PROOF.stat().st_mtime < started:
            return False, "the proof script is left over from an earlier job"
    except OSError:
        return False, "the proof script vanished"
    python = BASE / "runtime" / "python.exe"
    if not python.exists():  # Lite/Mac has no bundled runtime
        python = Path(sys.executable)
    try:
        run = subprocess.run([str(python), "-s", str(PROOF)], cwd=str(BASE),
                             capture_output=True, text=True, timeout=180)
    except subprocess.TimeoutExpired:
        return False, "the proof ran over two minutes and was stopped"
    except OSError as e:
        return False, f"the proof wouldn't start ({e})"
    output = (run.stdout or "") + (run.stderr or "")
    if run.returncode != 0:
        tail = output.strip().splitlines()[-1:] or [""]
        return False, f"the proof failed: {tail[0][:160]}"
    for line in output.splitlines():
        if line.strip().startswith("PROOF OK"):
            return True, line.strip()[9:].strip(" :")[:200]
    return False, "the proof ran but never printed PROOF OK"


def _implement_worker(item: dict) -> None:
    global _busy
    import os
    import sys

    sys.path.insert(0, str(BASE))
    import announce

    started = time.time()
    before = _snapshot_tree()  # taken BEFORE anything, so a revert is total
    try:
        from dotenv import load_dotenv

        load_dotenv(BASE / ".env")
        token = (os.getenv("CLAUDE_CODE_OAUTH_TOKEN") or "").strip()
        for key in [k for k in os.environ
                    if k.startswith(("ANTHROPIC", "CLAUDE"))]:
            os.environ.pop(key, None)
        if not token:
            _log("SKIPPED (no Claude token): " + item["title"])
            return
        os.environ["CLAUDE_CODE_OAUTH_TOKEN"] = token

        import anyio
        import quiet_spawn
        from claude_agent_sdk import ClaudeAgentOptions, ResultMessage, query

        quiet_spawn.hide()  # no black console window over the owner's desktop

        evidence = "\n".join(f"  {e}" for e in item.get("evidence", []))
        prompt = (
            "You are Kipp, TARS's self-improvement engineer, upgrading TARS's "
            f"own code at {BASE} on the owner's Windows PC. TARS is a running "
            "voice assistant; the owner is non-technical.\n\n"
            f"UPGRADE TO IMPLEMENT: {item['title']}\n{item['fix']}\n"
            f"Transcript evidence this grew from:\n{evidence}\n\n"
            "HARD RULES, no exceptions:\n"
            f"- NEVER touch, read, or copy: {FORBIDDEN}\n"
            "- Prefer EXISTING open-source libraries over hand-rolled code: "
            "TARS's find_tool skill searches GitHub and PyPI (import its "
            "search(query)); a thin wrapper around a maintained library "
            "beats a bespoke engine.\n"
            "- NEVER add spoken acknowledgments, confirmations, or any "
            "sound before TARS's actual reply — the owner has explicitly and "
            "repeatedly banned pre-speech noises. You added them once "
            "('confirmation step') and it had to be hunted down and "
            "removed.\n"
            "- Never delete files; never spend money; never send messages.\n"
            "- Before modifying ANY root .py file, first copy the original to "
            f"{BASE / 'backups' / 'auto'}\\<name>.<timestamp>.py (create the "
            "folder if needed).\n"
            "- Keep changes SMALL and surgical — one focused upgrade, matching "
            "the existing code style. If, on inspection, the idea is wrong or "
            "already handled, CHANGE NOTHING and say so.\n"
            "- After changes: syntax-check every touched file "
            f"({BASE / 'runtime' / 'python.exe'} -m py_compile <file>) and "
            "import-test it. A broken TARS is the worst possible outcome.\n"
            "- TARS hot-loads skills/, but changes to root .py files only "
            "apply after the owner restarts TARS — mention that in SPOKEN if "
            "you touched core files.\n\n"
            "PROOF IS MANDATORY — an upgrade you haven't watched work is not "
            "finished. You once announced 'your afternoon reminder pulls real "
            "SEQTA due dates now' when that code could never run: it sat "
            "below an unguarded read of a file that doesn't exist until "
            "the owner types something in, and the function's except-block "
            "swallowed the error. It compiled. It read correctly. It had "
            "never once fired.\n"
            f"So: write {PROOF} — a script that RUNS the new behaviour for "
            "real (import the module, call the function, check what comes "
            "back) and prints a line starting 'PROOF OK: ' with the actual "
            "output as evidence. Requirements:\n"
            "  - It must exercise the CHANGED code path, not just import it.\n"
            "  - It must pass with optional state files ABSENT as well as "
            "present — most of TARS's json files only appear once the owner has "
            "used that feature. Test the empty case explicitly.\n"
            "  - No network, no microphone, no GUI, under two minutes.\n"
            "  - It must leave the owner's real data exactly as it found it: "
            "work on copies or restore what you touch.\n"
            "  - Print 'PROOF FAILED: <why>' and exit 1 if the behaviour is "
            "wrong. A proof that cannot fail proves nothing.\n"
            "TARS runs your proof itself afterwards. If it doesn't exist, "
            "doesn't print PROOF OK, or exits non-zero, your whole change is "
            "REVERTED and the owner is told it couldn't be verified — so make it "
            "honest rather than easy.\n\n"
            "End your final message with a line starting exactly 'SPOKEN: ' — "
            "one short friendly sentence describing the upgrade for "
            "text-to-speech."
        )
        options = ClaudeAgentOptions(
            cwd=str(BASE),
            permission_mode="acceptEdits",
            allowed_tools=["Read", "Write", "Edit", "Bash", "Glob", "Grep",
                           "WebSearch", "WebFetch"],
            setting_sources=[],
            max_turns=50,
        )

        async def go() -> str:
            result_text = ""
            async for message in query(prompt=prompt, options=options):
                if isinstance(message, ResultMessage) and message.result:
                    result_text = message.result
            return result_text

        result = anyio.run(go)
        spoken = ""
        for line in reversed(result.splitlines()):
            if line.strip().startswith("SPOKEN:"):
                spoken = line.strip()[7:].strip()
                break
        with open(BASE / "logs" / "deep_tasks.log", "a", encoding="utf-8") as f:
            stamp = datetime.datetime.now().isoformat(timespec="seconds")
            f.write(f"\n=== {stamp} :: KIPP UPGRADE: {item['title']}\n{result}\n")

        # THE GATE. the owner: "can u make kipp actually test his stuff before
        # saying its done". A claim is not evidence — the proof has to run.
        changed = [Path(p).name for p, blob in before.items()
                   if Path(p).exists() and Path(p).read_bytes() != blob]
        if not changed:
            _log(f"NO CHANGE: {item['title']} — Kipp decided against it")
            if spoken:
                announce.post(f"Kipp here — {spoken}", hold_during_quiet=True)
            return
        proved, detail = _verify_proof(started)
        if not proved:
            undone = _restore_tree(before)
            _log(f"UNVERIFIED (reverted {len(undone)}): {item['title']} — "
                 f"{detail}")
            announce.post(
                f"Kipp here — I tried {item['title'].lower()}, but I "
                f"couldn't prove it actually worked, so I've put everything "
                f"back the way it was. Nothing's changed.",
                hold_during_quiet=True)
            return
        _log(f"DONE (verified): {item['title']} — {spoken or 'no summary'} "
             f"[proof: {detail}] [files: {', '.join(changed)}]")
        if spoken:
            announce.post(f"Kipp here — {spoken}", hold_during_quiet=True)
        try:
            import agents

            agents.log_touch("Kipp", [])
        except Exception:
            pass
    except Exception as e:
        _log(f"FAILED: {item['title']} — {e}")
    finally:
        with _lock:
            _busy = False


def _implement() -> None:
    global _busy
    s = _state()
    pending = s.get("pending", [])
    if not pending:
        return
    today = datetime.date.today().isoformat()
    if s.get("day") != today:
        s["day"], s["count"] = today, 0
    if s.get("count", 0) >= DAILY_CAP:
        return
    with _lock:
        if _busy:
            return
        _busy = True
    pending.sort(key=lambda p: -p.get("score", 0))
    item = pending.pop(0)
    s["pending"] = pending
    s["count"] = s.get("count", 0) + 1
    s["last_implement"] = time.time()
    _save(s)
    threading.Thread(target=_implement_worker, args=(item,), daemon=True).start()


# ---------------- the tick (called ~1/sec from main's standby loop) ----------------
def _idle_seconds() -> float:
    p = BASE / "logs" / f"{datetime.date.today().isoformat()}.jsonl"
    if not p.exists():
        return 24 * 3600.0
    return time.time() - p.stat().st_mtime


def tick() -> None:
    global _last_tick
    now = time.time()
    if now - _last_tick < 30:  # cheap guard; real work is rarer + threaded
        return
    _last_tick = now
    try:
        s = _state()
        if s.get("paused") or _idle_seconds() < IDLE_BEFORE_WORK:
            return
        if now - s.get("last_reflect", 0) >= REFLECT_GAP:
            s["last_reflect"] = now
            _save(s)
            threading.Thread(target=_reflect, daemon=True).start()
        if now - s.get("last_introspect", 0) >= INTROSPECT_GAP:
            s["last_introspect"] = now
            _save(s)
            threading.Thread(target=_introspect, daemon=True).start()
        if now - s.get("last_implement", 0) >= IMPLEMENT_GAP:
            _implement()
        _drain_queue()  # overnight jobs the owner left for him
    except Exception:
        pass  # self-improvement must never take down the voice loop


def force_now() -> str:
    """Voice command path ('improve yourself now') — skips the idle wait."""
    s = _state()
    if s.get("paused"):
        return "Self-improvement is paused. Say 'resume self-improvement' first."
    threading.Thread(target=_reflect, daemon=True).start()
    if s.get("pending"):
        s["last_implement"] = 0
        _save(s)
        _implement()
        return ("On it — implementing my best pending upgrade now, and "
                "re-reading today's transcripts for more.")
    return ("Re-reading today's transcripts for friction now. If I find "
            "something worth fixing, I'll get to work and tell you.")
