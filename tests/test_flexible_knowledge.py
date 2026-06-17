import pytest
import json
from pathlib import Path
from core.flexible_knowledge import (
    KnowledgeCard, FlexibleKnowledge,
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
            source="observation",
        )
        assert card.usefulness == 0
        assert card.misleading == 0
        assert card.comment == ""

    def test_usefulness_updated(self, textworld_domain):
        card = KnowledgeCard(id="card_001", content="test", domain=textworld_domain, source="observation")
        card.usefulness += 3
        assert card.usefulness == 3

    def test_misleading_updated(self, textworld_domain):
        card = KnowledgeCard(id="card_001", content="test", domain=textworld_domain, source="observation")
        card.misleading += 1
        assert card.misleading == 1

    def test_comment_set(self, textworld_domain):
        card = KnowledgeCard(id="card_001", content="test", domain=textworld_domain, source="observation")
        card.comment = "useful for pre-flop strategy"
        assert card.comment == "useful for pre-flop strategy"


class TestFlexibleKnowledge:
    def test_add_card(self, l2_store, textworld_domain):
        card = l2_store.add_card("map_A的钥匙在厨房抽屉里", textworld_domain, source="observation")
        assert card.id is not None
        assert len(l2_store.cards) == 1

    def test_write_md_and_rebuild_index(self, l2_store, textworld_domain):
        md_path = l2_store._write_md(textworld_domain, "map-navigation.md",
            "# 地图导航\n\n## 上锁的门需要钥匙\n钥匙通常在同一地图内。\n\n## 先探索未知房间\n新地图优先遍历未访问房间。\n")
        assert md_path.exists()
        l2_store._rebuild_index()
        index = json.loads(l2_store.index_path.read_text())
        chapters = [c for c in index["chapters"] if c["id"].startswith("textworld")]
        assert len(chapters) > 0

    def test_domain_stats(self, l2_store, textworld_domain):
        l2_store.add_card("card A", textworld_domain, source="observation")
        l2_store.add_card("card B", textworld_domain, source="observation")
        stats = l2_store.domain_stats(textworld_domain)
        assert stats["count"] >= 2

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
