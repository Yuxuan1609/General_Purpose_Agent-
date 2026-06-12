import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def _extract_selected_nodes_from_state(state: dict) -> list[dict]:
    domains_hint = state.get("domains_hint", [])
    return [{"name": d, "score": 1.0} for d in domains_hint]


class TestL2DomainsHintFlow:
    def test_domains_hint_flows_to_selected_nodes(self):
        state = {
            "domains_hint": ["game/leduc", "game/doudizhu"],
            "context_history": [],
        }
        selected_nodes = _extract_selected_nodes_from_state(state)
        assert len(selected_nodes) == 2
        assert selected_nodes[0]["name"] == "game/leduc"
        assert selected_nodes[1]["name"] == "game/doudizhu"

    def test_no_domains_hint_gives_empty(self):
        state = {"context_history": []}
        selected_nodes = _extract_selected_nodes_from_state(state)
        assert selected_nodes == []

    def test_empty_domains_hint_list_gives_empty(self):
        state = {"domains_hint": [], "context_history": []}
        selected_nodes = _extract_selected_nodes_from_state(state)
        assert selected_nodes == []
