"""TARS's neuron brain.

Every vault note is a neuron. Speech activates ("fires") the closest neurons
by meaning; neurons that fire close together in time strengthen their synapse
(STDP — spike-timing-dependent plasticity); unused synapses decay. When a
learned synapse gets strong between two notes nobody ever linked, the brain
writes the wikilink into Obsidian itself.

No LLM is involved in the learning — pure co-activation statistics.
"""
import datetime
import json
import re
import time
from pathlib import Path

import numpy as np
import requests

BASE = Path(__file__).parent
VAULT = BASE / "vault"
EXCLUDE_DIRS = {".obsidian", "Conversations", "Journal"}  # archives/timelines, not concepts

NEURONS_FILE = BASE / "brain_neurons.json"
VECTORS_FILE = BASE / "brain_vectors.npy"
SYNAPSES_FILE = BASE / "brain_synapses.json"
ACTIVITY_FILE = BASE / "brain_activity.jsonl"

EMBED_URL = "http://127.0.0.1:11434/api/embed"
EMBED_MODEL = "nomic-embed-text"

FIRE_TOP_K = 4          # neurons stimulated directly per utterance
FIRE_MIN_SIM = 0.45     # meaning similarity needed to fire at all
SPREAD_FACTOR = 0.6     # how strongly firing spreads across synapses/links
STDP_WINDOW = 90.0      # seconds — co-firing inside this window wires together
STDP_RATE = 0.03        # learning rate — associations must be EARNED over many co-firings
DECAY_PER_DAY = 0.02    # synapses fade when unused
LINK_THRESHOLD = 0.55   # learned weight that earns a real wikilink in Obsidian


def _embed(texts: list[str]) -> np.ndarray:
    r = requests.post(EMBED_URL, json={"model": EMBED_MODEL, "input": texts,
                                       "keep_alive": "2h"},
                      timeout=120)
    r.raise_for_status()
    v = np.array(r.json()["embeddings"], dtype=np.float32)
    return v / (np.linalg.norm(v, axis=1, keepdims=True) + 1e-9)


class NeuronBrain:
    def __init__(self):
        self.neurons: dict[str, dict] = {}   # name -> {path, folder, mtime, row}
        self.vectors = np.zeros((0, 768), dtype=np.float32)
        self.synapses: dict[str, dict] = {}  # "a|b" (sorted) -> {w, t}
        self.last_fired: dict[str, float] = {}
        self._load()

    # ---------- persistence ----------
    def _load(self):
        try:
            self.neurons = json.loads(NEURONS_FILE.read_text(encoding="utf-8"))
            self.vectors = np.load(VECTORS_FILE)
            self.synapses = json.loads(SYNAPSES_FILE.read_text(encoding="utf-8"))
        except Exception:
            self.neurons, self.synapses = {}, {}
            self.vectors = np.zeros((0, 768), dtype=np.float32)

    def _save(self):
        NEURONS_FILE.write_text(json.dumps(self.neurons), encoding="utf-8")
        np.save(VECTORS_FILE, self.vectors)
        SYNAPSES_FILE.write_text(json.dumps(self.synapses), encoding="utf-8")

    # ---------- indexing ----------
    def reindex(self) -> int:
        """Embed new/changed notes. Returns how many changed."""
        seen, changed = set(), []
        for p in VAULT.rglob("*.md"):
            if any(x in p.parts for x in EXCLUDE_DIRS):
                continue
            name = p.stem
            seen.add(name)
            mtime = p.stat().st_mtime
            if name not in self.neurons or self.neurons[name]["mtime"] < mtime:
                changed.append((name, p, mtime))
        gone = [n for n in self.neurons if n not in seen]
        if not changed and not gone:
            return 0

        for name in gone:
            del self.neurons[name]
        texts, metas = [], []
        for name, p, mtime in changed:
            body = p.read_text(encoding="utf-8")[:1500]
            texts.append(f"{name}\n{body}")
            metas.append((name, p, mtime))
        new_vecs = _embed(texts) if texts else np.zeros((0, 768), dtype=np.float32)

        # rebuild vector matrix in a stable order
        names = [n for n in self.neurons if n not in {m[0] for m in metas}]
        rows = [self.vectors[self.neurons[n]["row"]] for n in names
                if self.neurons[n].get("row", -1) < len(self.vectors)]
        for (name, p, mtime), vec in zip(metas, new_vecs):
            names.append(name)
            rows.append(vec)
            self.neurons[name] = {"path": str(p), "folder": p.parent.name,
                                  "mtime": mtime}
        self.vectors = np.array(rows, dtype=np.float32) if rows else \
            np.zeros((0, 768), dtype=np.float32)
        for i, n in enumerate(names):
            self.neurons[n]["row"] = i
        self._save()
        return len(changed)

    # ---------- wikilinks ----------
    def _links_of(self, name: str) -> set[str]:
        try:
            text = Path(self.neurons[name]["path"]).read_text(encoding="utf-8")
        except Exception:
            return set()
        return {m for m in re.findall(r"\[\[([^\]|#]+)", text) if m in self.neurons}

    # ---------- the living part ----------
    def stimulate(self, text: str, source: str = "jacob") -> list[dict]:
        """Fire the neurons closest in meaning; spread; learn (STDP)."""
        self.reindex()
        if not len(self.vectors):
            return []
        try:
            q = _embed([text])[0]
        except Exception:
            return []
        sims = self.vectors @ q
        order = np.argsort(-sims)[:FIRE_TOP_K]
        now = time.time()
        row_to_name = {v["row"]: k for k, v in self.neurons.items()}

        fired = []
        for idx in order:
            sim = float(sims[idx])
            if sim < FIRE_MIN_SIM:
                continue
            name = row_to_name.get(int(idx))
            if name:
                fired.append({"name": name, "strength": round(sim, 3)})

        # spreading activation: strong synapses & wikilinks pull neighbours in
        spread = {}
        for f in fired:
            for nb in self._links_of(f["name"]):
                spread[nb] = max(spread.get(nb, 0), f["strength"] * SPREAD_FACTOR)
            for key, syn in self.synapses.items():
                a, b = key.split("|")
                if f["name"] in (a, b) and syn["w"] > 0.25:
                    other = b if f["name"] == a else a
                    spread[other] = max(spread.get(other, 0),
                                        f["strength"] * syn["w"])
        for nb, s in spread.items():
            if s > 0.3 and nb not in [f["name"] for f in fired]:
                fired.append({"name": nb, "strength": round(s, 3),
                              "via": "association"})

        # STDP: wire what fires together — each pair counted ONCE per thought
        def _strengthen(a: str, b: str, closeness: float):
            key = "|".join(sorted([a, b]))
            syn = self.synapses.get(key, {"w": 0.0, "t": now})
            idle_days = (now - syn.get("t", now)) / 86400
            syn["w"] = max(0.0, syn["w"] - DECAY_PER_DAY * idle_days)
            syn["w"] = min(1.0, syn["w"] + STDP_RATE * closeness)
            syn["t"] = now
            self.synapses[key] = syn

        prior = dict(self.last_fired)
        names_now = [f["name"] for f in fired]
        for i in range(len(names_now)):
            for j in range(i + 1, len(names_now)):  # co-fired in this thought
                _strengthen(names_now[i], names_now[j], 1.0)
        for name in names_now:                       # fired near a recent thought
            for other, t_other in prior.items():
                if other in names_now or now - t_other > STDP_WINDOW:
                    continue
                _strengthen(name, other, float(np.exp(-(now - t_other) / STDP_WINDOW)))
        for name in names_now:
            self.last_fired[name] = now

        if fired:
            self._save()
            with open(ACTIVITY_FILE, "a", encoding="utf-8") as f_:
                f_.write(json.dumps({"t": now, "source": source,
                                     "fired": fired}) + "\n")
            # only pay the file-scan cost when a synapse is actually ready
            if any(s["w"] >= LINK_THRESHOLD and not s.get("linked")
                   for s in self.synapses.values()):
                self._discover_links()
        return fired

    def _discover_links(self):
        """Strong learned synapses become real wikilinks — written by the brain."""
        today = datetime.date.today().isoformat()
        for key, syn in self.synapses.items():
            if syn["w"] < LINK_THRESHOLD or syn.get("linked"):
                continue
            a, b = key.split("|")
            if a not in self.neurons or b not in self.neurons:
                continue
            if b in self._links_of(a) or a in self._links_of(b):
                syn["linked"] = True
                continue
            with open(self.neurons[a]["path"], "a", encoding="utf-8") as f:
                f.write(f"\n- My brain keeps associating this with [[{b}]] "
                        f"*(self-discovered {today})*\n")
            syn["linked"] = True
        self._save()

    def recall(self, text: str, source: str = "jacob") -> str:
        """Fire on the text and return snippet context for the chat prompt."""
        fired = self.stimulate(text, source)
        bits = []
        for f in fired[:4]:
            try:
                body = Path(self.neurons[f["name"]]["path"]).read_text(encoding="utf-8")
                body = body.split("---")[-1].strip()[:220]
            except Exception:
                body = ""
            bits.append(f"[{f['name']}] {body}")
        return "\n".join(bits)


_instance: NeuronBrain | None = None


def get() -> NeuronBrain:
    global _instance
    if _instance is None:
        _instance = NeuronBrain()
    return _instance
