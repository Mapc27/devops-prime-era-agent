"""Long-term memory layers of Ops Crew (L1 working memory = LangGraph checkpointer, see graph.py).

L2 Episodic  — past investigations / postmortems. Hybrid retrieval:
               score = 0.55*cosine + 0.30*bm25_norm + 0.15*recency, x outcome weight.
               Recency decays with a 30-day half-life; unused episodes older than TTL are pruned.
L3 Semantic  — facts about infrastructure / user with bi-temporal validity (inspired by Graphiti):
               valid_from / valid_to / recorded_at / superseded_by. A new fact that contradicts an
               active one closes it (valid_to = now) instead of overwriting — history is kept and
               retrieval returns only facts valid "as of" a moment.
               Contradiction is decided by the Jev-like decision model (noul), dedup by cosine.
"""

import json
import re
import sqlite3
import time
import uuid
from dataclasses import dataclass

import httpx
import numpy as np
from rank_bm25 import BM25Okapi

from opscrew.config import models_cfg, settings
from opscrew.observability import MEMORY_OPS, MEMORY_SIZE, log, span

HALF_LIFE_DAYS = 30
EPISODE_TTL_DAYS = 180
DUP_THRESHOLD = 0.95
CANDIDATE_THRESHOLD = 0.55


def _tok(t: str) -> list[str]:
    return re.findall(r"[a-zа-я0-9_]+", t.lower())


class Embedder:
    def __init__(self):
        self.model = models_cfg()["roles"]["embed"]["model"]
        self.client = httpx.Client(timeout=60)
        self._cache: dict[str, np.ndarray] = {}

    def __call__(self, texts: list[str]) -> list[np.ndarray]:
        missing = [t for t in texts if t not in self._cache]
        if missing:
            r = self.client.post(settings.ollama_url.rstrip("/") + "/api/embed", json={"model": self.model, "input": missing})
            r.raise_for_status()
            for t, e in zip(missing, r.json()["embeddings"]):
                v = np.asarray(e, dtype=np.float32)
                self._cache[t] = v / (np.linalg.norm(v) + 1e-9)
        return [self._cache[t] for t in texts]


def _cos(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(a, b))


def _same_surface(a: str, b: str) -> bool:
    """Embeddings barely see numbers ('PostgreSQL 15' ~ 'PostgreSQL 17'), so a duplicate also needs
    identical numbers and high token overlap."""
    ta, tb = set(_tok(a)), set(_tok(b))
    nums = lambda t: {x for x in t if any(ch.isdigit() for ch in x)}  # noqa: E731
    jac = len(ta & tb) / max(1, len(ta | tb))
    return nums(ta) == nums(tb) and jac >= 0.8


@dataclass
class Episode:
    id: str
    ts: float
    title: str
    symptoms: str
    root_cause: str
    fix: str
    outcome: str
    skill: str
    steps: int
    score: float = 0.0


@dataclass
class Fact:
    id: str
    subject: str
    text: str
    valid_from: float
    valid_to: float | None
    source: str
    superseded_by: str | None = None
    score: float = 0.0


class Memory:
    def __init__(self, path=None, embedder=None, decision=None):
        self.path = path or (settings.data_dir / "memory.sqlite")
        self.db = sqlite3.connect(self.path, check_same_thread=False)
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS episodes(id TEXT PRIMARY KEY, ts REAL, title TEXT, symptoms TEXT, root_cause TEXT,
            fix TEXT, outcome TEXT, skill TEXT, steps INT, uses INT DEFAULT 0, last_used REAL, emb BLOB);
        CREATE TABLE IF NOT EXISTS facts(id TEXT PRIMARY KEY, subject TEXT, text TEXT, valid_from REAL, valid_to REAL,
            recorded_at REAL, source TEXT, superseded_by TEXT, emb BLOB);
        """)
        self.embed = embedder or Embedder()
        self._decision = decision

    @property
    def decision(self):
        if self._decision is None:
            from opscrew.llm.systemone import DecisionModel
            self._decision = DecisionModel()
        return self._decision

    # ------------------------------------------------------------ episodic (L2)
    def add_episode(self, title, symptoms, root_cause, fix, outcome, skill="", steps=0) -> str:
        with span("memory.episodic.write", **{"openinference.span.kind": "CHAIN"}):
            eid = uuid.uuid4().hex[:12]
            emb = self.embed([f"{title}\n{symptoms}\n{root_cause}"])[0]
            self.db.execute("INSERT INTO episodes VALUES(?,?,?,?,?,?,?,?,?,0,NULL,?)",
                            (eid, time.time(), title, symptoms, root_cause, fix, outcome, skill, steps, emb.tobytes()))
            self.db.commit()
            MEMORY_OPS.labels("episodic", "write").inc()
            self._gauges()
            return eid

    def search_episodes(self, query: str, k=3, min_score=0.35) -> list[Episode]:
        with span("memory.episodic.search", **{"openinference.span.kind": "RETRIEVER", "input.value": query}) as s:
            rows = self.db.execute("SELECT id,ts,title,symptoms,root_cause,fix,outcome,skill,steps,emb FROM episodes").fetchall()
            MEMORY_OPS.labels("episodic", "search").inc()
            if not rows:
                return []
            q = self.embed([query])[0]
            docs = [_tok(f"{r[2]} {r[3]} {r[4]}") for r in rows]
            bm = np.clip(BM25Okapi(docs).get_scores(_tok(query)), 0, None) if len(docs) > 1 else np.zeros(len(docs))
            bmax = bm.max() if bm.max() > 0 else 1.0
            now = time.time()
            out = []
            for r, b in zip(rows, bm):
                emb = np.frombuffer(r[9], dtype=np.float32)
                age_days = (now - r[1]) / 86400
                recency = 0.5 ** (age_days / HALF_LIFE_DAYS)
                outcome_w = 1.0 if r[6] == "resolved" else 0.7
                # with a single document BM25 IDF is degenerate -> fall back to cosine weight
                w_cos, w_bm = (0.55, 0.30) if len(docs) > 1 else (0.85, 0.0)
                sc = (w_cos * _cos(q, emb) + w_bm * (b / bmax) + 0.15 * recency) * outcome_w
                out.append(Episode(*r[:9], score=round(sc, 3)))
            out = [e for e in sorted(out, key=lambda e: -e.score) if e.score >= min_score][:k]
            for e in out:
                self.db.execute("UPDATE episodes SET uses=uses+1, last_used=? WHERE id=?", (now, e.id))
            self.db.commit()
            MEMORY_OPS.labels("episodic", "hit" if out else "miss").inc()
            s.set_attribute("retrieval.documents", json.dumps([{"title": e.title, "score": e.score} for e in out]))
            return out

    def prune(self, ttl_days=EPISODE_TTL_DAYS) -> int:
        cut = time.time() - ttl_days * 86400
        n = self.db.execute("DELETE FROM episodes WHERE ts < ? AND uses = 0", (cut,)).rowcount
        self.db.commit()
        MEMORY_OPS.labels("episodic", "prune").inc(n)
        return n

    # ------------------------------------------------------------ semantic (L3)
    def add_fact(self, text: str, subject: str = "", source: str = "user", now: float | None = None) -> dict:
        """Insert a fact; supersede contradicting active facts; skip duplicates."""
        now = now or time.time()
        with span("memory.semantic.write", **{"openinference.span.kind": "CHAIN", "input.value": text}) as s:
            emb = self.embed([text])[0]
            active = self._active_facts(as_of=now)
            superseded, duplicate_of = [], None
            for f, femb in active:
                c = _cos(emb, femb)
                if c >= DUP_THRESHOLD and _same_surface(text, f.text):
                    duplicate_of = f.id
                    break
                same_subject = subject and f.subject and subject.lower() == f.subject.lower()
                if c >= CANDIDATE_THRESHOLD or same_subject:
                    p = self.decision.noul(
                        {"old_fact": f.text, "new_fact": text},
                        "Does `new_fact` make `old_fact` outdated, replace it, or contradict it (so old_fact is no longer true)?",
                        label="memory_contradiction")
                    if p >= 0.5:
                        superseded.append((f, round(p, 3)))
            if duplicate_of:
                self.db.execute("UPDATE facts SET recorded_at=? WHERE id=?", (now, duplicate_of))
                self.db.commit()
                MEMORY_OPS.labels("semantic", "dedup").inc()
                s.set_attribute("memory.result", "duplicate")
                return {"id": duplicate_of, "duplicate": True, "superseded": []}
            fid = uuid.uuid4().hex[:12]
            self.db.execute("INSERT INTO facts VALUES(?,?,?,?,NULL,?,?,NULL,?)",
                            (fid, subject, text, now, now, source, emb.tobytes()))
            for f, _ in superseded:
                self.db.execute("UPDATE facts SET valid_to=?, superseded_by=? WHERE id=?", (now, fid, f.id))
                MEMORY_OPS.labels("semantic", "invalidate").inc()
            self.db.commit()
            MEMORY_OPS.labels("semantic", "write").inc()
            self._gauges()
            res = {"id": fid, "duplicate": False, "superseded": [{"text": f.text, "p": p} for f, p in superseded]}
            s.set_attribute("memory.result", json.dumps(res, ensure_ascii=False))
            log.info(f"fact stored: {text!r}, superseded={len(superseded)}")
            return res

    def _active_facts(self, as_of: float | None = None):
        as_of = as_of or time.time()
        rows = self.db.execute(
            "SELECT id,subject,text,valid_from,valid_to,source,superseded_by,emb FROM facts "
            "WHERE valid_from <= ? AND (valid_to IS NULL OR valid_to > ?)", (as_of, as_of)).fetchall()
        return [(Fact(*r[:7]), np.frombuffer(r[7], dtype=np.float32)) for r in rows]

    def search_facts(self, query: str, k=5, as_of: float | None = None, min_score=0.55, margin=0.12) -> list[Fact]:
        with span("memory.semantic.search", **{"openinference.span.kind": "RETRIEVER", "input.value": query}) as s:
            MEMORY_OPS.labels("semantic", "search").inc()
            act = self._active_facts(as_of)
            if not act:
                return []
            q = self.embed([query])[0]
            scored = []
            for f, e in act:
                f.score = round(_cos(q, e), 3)
                scored.append(f)
            scored.sort(key=lambda f: -f.score)
            # relative cut-off: embedding cosine has a high floor, keep only facts close to the best match
            cut = max(min_score, scored[0].score - margin)
            out = [f for f in scored if f.score >= cut][:k]
            MEMORY_OPS.labels("semantic", "hit" if out else "miss").inc()
            s.set_attribute("retrieval.documents", json.dumps([{"text": f.text, "score": f.score} for f in out], ensure_ascii=False))
            return out

    def fact_history(self, subject_query: str) -> list[dict]:
        rows = self.db.execute("SELECT text, valid_from, valid_to, superseded_by FROM facts ORDER BY valid_from").fetchall()
        return [{"text": r[0], "valid_from": r[1], "valid_to": r[2], "superseded_by": r[3]} for r in rows
                if any(t in r[0].lower() for t in _tok(subject_query))]

    def _gauges(self):
        n = self.db.execute("SELECT count(*) FROM episodes").fetchone()[0]
        MEMORY_SIZE.labels("episodic", "all").set(n)
        a = self.db.execute("SELECT count(*) FROM facts WHERE valid_to IS NULL").fetchone()[0]
        t = self.db.execute("SELECT count(*) FROM facts").fetchone()[0]
        MEMORY_SIZE.labels("semantic", "active").set(a)
        MEMORY_SIZE.labels("semantic", "superseded").set(t - a)

    def context(self, query: str) -> tuple[str, list[Episode], list[Fact]]:
        """Formatted memory context for prompts."""
        eps = self.search_episodes(query)
        facts = self.search_facts(query)
        parts = []
        if facts:
            parts.append("Known facts (currently valid):\n" + "\n".join(f"- {f.text}" for f in facts))
        if eps:
            parts.append("Similar past incidents:\n" + "\n".join(
                f"- [{e.outcome}] {e.title}: root cause: {e.root_cause}; fix: {e.fix}; diagnostic skill: {e.skill}"
                for e in eps))
        return ("\n\n".join(parts) or "No relevant memory."), eps, facts


_mem = None


def memory() -> Memory:
    global _mem
    if _mem is None:
        _mem = Memory()
    return _mem


