"""The registry and the Blast Radius grid describe the same agents.

The registry once served six invented agents whose service accounts did not exist while
the grid probed three real ones. These run without Google Cloud: /api/agents reads the
matrix, bootstrap.py's grants, and the committed eval results.
"""
import bootstrap
import containment_matrix
from test_phase5_dashboard_backend import call


def _agents():
    status, body = call("GET", "/api/agents")
    assert status == 200
    return body


def test_every_grid_agent_is_in_the_registry_under_the_same_identity():
    agents = _agents()
    for vertical_key, vertical in containment_matrix.VERTICALS.items():
        for row in vertical["agents"]:
            match = [a for a in agents.values()
                     if a.get("vertical") == vertical_key and a["title"] == row.label]
            assert match, f"{row.label} is in the {vertical_key} grid but not the registry"
            assert match[0]["runtimeLogin"] == containment_matrix.agent_sa(row.sa_name)


def test_every_registry_identity_is_one_bootstrap_creates():
    for agent in _agents().values():
        assert agent["runtimeLogin"].split("@")[0] in bootstrap.AGENTS


def test_reach_matches_the_declared_grid():
    agents = _agents()
    payments = agents["payments"]
    allowed = {e["name"] for e in payments["reachableEndpoints"]
               if e["statusClass"] == "endpoint-allowed"}
    assert allowed == {"Funding status (view)", "Request a payment"}


def test_unmeasured_agents_carry_no_cost_figure():
    agents = _agents()
    assert agents["payments"]["costEstimate"] is None
    assert agents["sales-agent"]["costEstimate"]["modelTier"].startswith("gemini-2.5")
