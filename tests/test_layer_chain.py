import pytest
from typing import Any
from core.types import TaskObservation
from core.layers.base import LayerManager


# --- Mock managers for testing ---

class MockL3Manager(LayerManager):
    def __init__(self, downstream: LayerManager | None = None):
        super().__init__("l3", downstream)
    def process(self, obs: TaskObservation) -> dict:
        obs.state["l3_skills"] = ["skill_a", "skill_b"]
        return {"status": "ok", "skills": 2}
    def notify(self) -> Any:
        return {"l3_result": "all_good"}
    def apply_update(self, key, value):
        pass


class MockL2Manager(LayerManager):
    def __init__(self, downstream: LayerManager | None = None):
        super().__init__("l2", downstream)
    def process(self, obs: TaskObservation) -> dict:
        obs.state["l2_cards"] = [{"content": "trick: play high cards", "confidence": 0.8, "domain": "game/doudizhu"}]
        return {"status": "ok", "cards_found": 1}
    def notify(self) -> Any:
        return {"l2_result": "all_good"}
    def apply_update(self, key, value):
        pass


class MockL0_5_1Manager(LayerManager):
    def __init__(self, downstream: LayerManager | None = None):
        super().__init__("l0_5_1", downstream)
    def process(self, obs: TaskObservation) -> dict:
        obs.state["l1_rules"] = ["优先出大牌"]
        return {"status": "ok", "rules_applied": 1}
    def notify(self) -> Any:
        return {"l0_5_1_result": "all_good"}
    def apply_update(self, key, value):
        pass


class TestLayerChain:
    def test_query_flows_top_down(self):
        """QUERY propagates from L0.5+1 → L2 → L3."""
        l3 = MockL3Manager()
        l2 = MockL2Manager(downstream=l3)
        l1 = MockL0_5_1Manager(downstream=l2)

        obs = TaskObservation(meta="game rules", state={"current": "test"})
        l1.query(obs)

        assert obs.state["l1_rules"] == ["优先出大牌"]
        assert obs.state["l2_cards"][0]["content"] == "trick: play high cards"
        assert obs.state["l3_skills"] == ["skill_a", "skill_b"]

    def test_notify_collects_all_layers(self):
        """NOTIFY gathers from all layers after RESPONSE completes."""
        l3 = MockL3Manager()
        l2 = MockL2Manager(downstream=l3)
        l1 = MockL0_5_1Manager(downstream=l2)

        obs = TaskObservation()
        l1.query(obs)

        notifications = l1.collect_notify()
        assert "l0_5_1" in notifications
        assert "l2" in notifications
        assert "l3" in notifications
        assert notifications["l3"]["l3_result"] == "all_good"

    def test_collect_notify_returns_shallow_copy(self):
        l3 = MockL3Manager()
        l2 = MockL2Manager(downstream=l3)
        l1 = MockL0_5_1Manager(downstream=l2)

        obs = TaskObservation()
        l1.query(obs)

        n1 = l1.collect_notify()
        n1["extra"] = "mutated"
        n2 = l1.collect_notify()
        assert "extra" not in n2
