import pytest
import json
from pathlib import Path
from core.flexible_knowledge import (
    KnowledgeCard, FlexibleKnowledge, KnowledgeGraph,
    RELATION_TYPES,
)
from core.task import Domain


@pytest.fixture
def textworld_domain():
    return Domain("textworld/map_A", "specific")


@pytest.fixture
def general_domain():
    return Domain("general", "general")


@pytest.fixture
def l2_store(temp_dir):
    knowledge_dir = temp_dir / "knowledge"
    knowledge_dir.mkdir()
    (knowledge_dir / "general").mkdir()
    index_path = knowledge_dir / "l2_index.json"
    index_path.write_text(json.dumps({
        "version": 1, "updated_at": "", "chapters": [], "relations": []
    }))
    return FlexibleKnowledge(knowledge_dir, index_path)


class TestKnowledgeCard:
    def test_create_card(self, textworld_domain):
        card = KnowledgeCard(
            id="card_001",
            content="map_A的钥匙在厨房抽屉里",
            domain=textworld_domain,
            sub_tags=["navigation", "key_location"],
            confidence=0.9,
            source="observation",
        )
        assert card.confidence == 0.9
        assert card.activation == 0.9
        assert card.success_count == 0

    def test_boost_increases_confidence(self, textworld_domain):
        card = KnowledgeCard(id="card_001", content="test", domain=textworld_domain, confidence=0.5, source="observation")
        card.boost()
        assert card.confidence > 0.5
        assert card.success_count == 1

    def test_penalize_decreases_confidence(self, textworld_domain):
        card = KnowledgeCard(id="card_001", content="test", domain=textworld_domain, confidence=0.5, source="observation")
        card.penalize()
        assert card.confidence < 0.5
        assert card.failure_count == 1

    def test_confidence_cannot_exceed_one(self, textworld_domain):
        card = KnowledgeCard(id="card_001", content="test", domain=textworld_domain, confidence=0.99, source="observation")
        card.boost()
        assert card.confidence <= 1.0

    def test_confidence_floor(self, textworld_domain):
        card = KnowledgeCard(id="card_001", content="test", domain=textworld_domain, confidence=0.05, source="observation")
        card.penalize()
        assert card.confidence >= 0.1

    def test_domain_match_exact(self, textworld_domain):
        card = KnowledgeCard(id="card_001", content="test", domain=textworld_domain, confidence=1.0, source="observation")
        score = card._domain_match_score(textworld_domain)
        assert score == 1.0

    def test_domain_match_general(self, general_domain, textworld_domain):
        card = KnowledgeCard(id="card_001", content="test", domain=general_domain, confidence=1.0, source="observation")
        score = card._domain_match_score(textworld_domain)
        assert score == 0.4

    def test_domain_match_parent(self):
        parent = Domain("textworld", "general")
        child = Domain("textworld/map_A", "specific")
        card = KnowledgeCard(id="card_001", content="test", domain=parent, confidence=1.0, source="observation")
        score = card._domain_match_score(child)
        assert score == 0.7

    def test_domain_match_unrelated(self):
        card = KnowledgeCard(id="card_001", content="test", domain=Domain("programming/python", "specific"), confidence=1.0, source="observation")
        score = card._domain_match_score(Domain("textworld/map_A", "specific"))
        assert score == 0.0


class TestFlexibleKnowledge:
    def test_add_card(self, l2_store, textworld_domain):
        card = l2_store.add_card("map_A的钥匙在厨房抽屉里", textworld_domain, sub_tags=["key_location"], confidence=0.9, source="observation")
        assert card.id is not None
        assert len(l2_store.cards) == 1

    def test_get_active_cards(self, l2_store, textworld_domain):
        l2_store.add_card("钥匙在厨房", textworld_domain, confidence=0.9, source="observation")
        l2_store.add_card("宝藏在阁楼", textworld_domain, confidence=0.8, source="observation")
        l2_store.add_card("无关卡片", Domain("programming/python", "specific"), confidence=0.9, source="observation")
        active = l2_store.get_active_cards(textworld_domain, "", top_k=5)
        assert len(active) <= 3
        assert all(c.domain.path.startswith("textworld") or c.domain.is_general for c in active)

    def test_write_md_and_rebuild_index(self, l2_store, textworld_domain):
        md_path = l2_store._write_md(textworld_domain, "map-navigation.md",
            "# 地图导航\n\n## 上锁的门需要钥匙\n钥匙通常在同一地图内。\n\n## 先探索未知房间\n新地图优先遍历未访问房间。\n")
        assert md_path.exists()
        l2_store._rebuild_index()
        index = json.loads(l2_store.index_path.read_text())
        chapters = [c for c in index["chapters"] if c["id"].startswith("textworld")]
        assert len(chapters) > 0

    def test_domain_stats(self, l2_store, textworld_domain):
        l2_store.add_card("card A", textworld_domain, confidence=0.9, source="observation")
        l2_store.add_card("card B", textworld_domain, confidence=0.7, source="observation")
        stats = l2_store.domain_stats(textworld_domain)
        assert stats["count"] >= 2
        assert 0 < stats["avg_activation"] <= 1.0

    def test_card_available_domains_indexed(self, tmp_path):
        from core.domain_registry import DomainRegistry
        reg = DomainRegistry()
        reg.add_node("game/leduc", "game", "Leduc")
        reg.add_node("game", None, "Game")
        fk = FlexibleKnowledge(tmp_path / "k", tmp_path / "index.json",
                               domain_registry=reg)
        from core.task import Domain
        card = fk.add_card(content="test", domain=Domain("game/leduc", "specific"))
        assert card.available_domains == ["game/leduc"]
        items = reg.get_primary_items("l2", "game/leduc")
        assert card.id in items

    def test_card_remove_unsyncs_index(self, tmp_path):
        from core.domain_registry import DomainRegistry
        reg = DomainRegistry()
        reg.add_node("game/leduc", "game", "Leduc")
        fk = FlexibleKnowledge(tmp_path / "k", tmp_path / "index.json",
                               domain_registry=reg)
        from core.task import Domain
        card = fk.add_card(content="test", domain=Domain("game/leduc", "specific"))
        assert card.id in reg.get_primary_items("l2", "game/leduc")
        fk.remove_card(card.id)
        assert card.id not in reg.get_primary_items("l2", "game/leduc")


class TestKnowledgeGraph:
    def test_build_from_index(self):
        index = {
            "chapters": [],
            "relations": [
                {"from": "textworld/map-navigation", "to": "textworld/item-search", "type": "cross_reference"},
                {"from": "textworld/map-navigation", "to": "general/task-strategy", "type": "parent_child"},
            ]
        }
        graph = KnowledgeGraph(index)
        adj = graph.get_adjacent("textworld/map-navigation")
        assert len(adj) == 2
        assert ("textworld/item-search", "cross_reference") in adj

    def test_spread_activation(self):
        index = {
            "chapters": [],
            "relations": [
                {"from": "A", "to": "B", "type": "cross_reference"},
                {"from": "B", "to": "C", "type": "prerequisite"},
            ]
        }
        graph = KnowledgeGraph(index)
        scores = graph.spread_activation(["A"], steps=2)
        assert "A" in scores
        assert scores.get("B", 0) > 0
        assert scores.get("C", 0) > 0

    def test_empty_index(self):
        graph = KnowledgeGraph({"chapters": [], "relations": []})
        assert graph.get_adjacent("nonexistent") == []
        assert graph.spread_activation(["A"]) == {"A": 1.0}
