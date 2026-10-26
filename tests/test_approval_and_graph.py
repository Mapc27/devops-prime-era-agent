"""HITL protection: apply_remediation requires a valid approval token; graph wiring is complete."""
import os

os.environ.setdefault("APPROVAL_SECRET", "test-secret")

from opscrew.tools import client  # noqa: E402
from opscrew.tools import mcp_server as srv  # noqa: E402


def test_token_matches_server():
    srv.APPROVAL_SECRET = client.settings.approval_secret
    assert client.approval_token("r1", "rollback_config", "") == srv.expected_token("r1", "rollback_config", "")


def test_apply_without_token_denied():
    assert srv.apply_remediation("rollback_config", "r1", "forged").startswith("DENIED")
    assert srv.apply_remediation("rm_rf", "r1", "x").startswith("DENIED")


def test_graph_has_all_agents_and_hitl():
    from opscrew.graph import build_graph
    g = build_graph().get_graph()
    nodes = set(g.nodes)
    for n in ["triage", "recall", "plan", "investigate", "diagnose", "validate_diagnosis", "remediate",
              "validate_remediation", "human_gate", "execute", "verify", "scribe", "respond"]:
        assert n in nodes
    edges = {(e.source, e.target) for e in g.edges}
    assert ("validate_diagnosis", "investigate") in edges     # revise loop
    assert ("human_gate", "execute") in edges and ("human_gate", "scribe") in edges


def test_skills_loaded():
    from opscrew import skillbook
    assert len(skillbook.all_skills()) >= 6
    assert "none" in skillbook.criteria()
