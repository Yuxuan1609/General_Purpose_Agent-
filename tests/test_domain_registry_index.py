from core.domain_registry import DomainRegistry, DomainNode


class TestDomainRegistryIndexRead:

    def setup_method(self):
        self.reg = DomainRegistry(nodes={
            "game": DomainNode(path="game", parent=None, description="Games"),
            "game/leduc": DomainNode(path="game/leduc", parent="game", description="Leduc"),
        })

    def test_get_primary_items_returns_indexed_items(self):
        self.reg.index_item("l2", "game/leduc", "card_001")
        self.reg.index_item("l2", "game/leduc", "card_002")
        items = self.reg.get_primary_items("l2", "game/leduc")
        assert items == ["card_001", "card_002"]

    def test_get_primary_items_empty_for_unknown_domain(self):
        items = self.reg.get_primary_items("l2", "nonexistent")
        assert items == []

    def test_get_items_for_domains_union(self):
        self.reg.index_item("l2", "game/leduc", "card_a")
        self.reg.index_item("l2", "game", "card_b")
        items = self.reg.get_items_for_domains("l2", ["game/leduc", "game"])
        assert set(items) == {"card_a", "card_b"}

    def test_get_explore_items_with_correlations(self):
        self.reg._nodes["game/leduc"].correlations["game/doudizhu"] = 0.8
        self.reg._nodes["game/doudizhu"] = DomainNode(
            path="game/doudizhu", parent="game", description="Doudizhu")
        self.reg.index_item("l2", "game/doudizhu", "card_x")
        items = self.reg.get_explore_items("l2", "game/leduc", threshold=0.5)
        assert "card_x" in items
