"""TC-13/TC-14: episodic recall and temporal fact invalidation (offline: fake embedder + fake decision model)."""
import numpy as np

from opscrew.memory.store import Memory


class FakeEmbed:
    vocab = ["postgres", "postgresql", "database", "redis", "cart", "500", "oncall", "alex", "worker", "memory", "17", "15"]

    def __call__(self, texts):
        out = []
        for t in texts:
            v = np.array([1.0 if w in t.lower() else 0.0 for w in self.vocab] + [0.1], dtype=np.float32)
            out.append(v / np.linalg.norm(v))
        return out


class FakeDecision:
    def noul(self, state, instructions, label=""):
        old, new = state["old_fact"].lower(), state["new_fact"].lower()
        return 0.9 if ("database" in old and "database" in new and old != new) else 0.05


def mem(tmp_path):
    return Memory(path=tmp_path / "m.sqlite", embedder=FakeEmbed(), decision=FakeDecision())


def test_fact_supersede_keeps_history(tmp_path):
    m = mem(tmp_path)
    m.add_fact("The main database runs PostgreSQL 15", "database")
    r = m.add_fact("The main database runs PostgreSQL 17", "database")
    assert r["superseded"] and "15" in r["superseded"][0]["text"]
    active = [f.text for f in m.search_facts("which postgresql database version")]
    assert active == ["The main database runs PostgreSQL 17"]
    hist = m.fact_history("postgresql")
    assert len(hist) == 2 and hist[0]["valid_to"] is not None and hist[1]["valid_to"] is None


def test_duplicate_fact_not_inserted(tmp_path):
    m = mem(tmp_path)
    a = m.add_fact("On-call engineer is Alex", "oncall")
    b = m.add_fact("On-call engineer is Alex", "oncall")
    assert b["duplicate"] and a["id"] == b["id"]


def test_as_of_query_returns_old_fact(tmp_path):
    m = mem(tmp_path)
    m.add_fact("The main database runs PostgreSQL 15", "database", now=1000.0)
    m.add_fact("The main database runs PostgreSQL 17", "database", now=2000.0)
    old = m.search_facts("postgresql database", as_of=1500.0)
    assert [f.text for f in old] == ["The main database runs PostgreSQL 15"]


def test_episode_recall(tmp_path):
    m = mem(tmp_path)
    m.add_episode("redis down", "cart 500 errors", "redis container stopped", "restart_service redis", "resolved", "triage-http-5xx", 4)
    m.add_episode("worker OOM", "worker restarts", "worker memory limit", "rollback_config", "resolved", "diagnose-oom", 5)
    eps = m.search_episodes("cart returns 500 redis")
    assert eps and eps[0].title == "redis down"
