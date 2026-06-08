from core.domain_registry import DomainNode, DomainRegistry


class TestDomainNode:
    def test_create_node(self):
        node = DomainNode(
            path="game/leduc",
            parent="game",
            description="Leduc Hold'em",
            correlations={"game/doudizhu": 0.6},
            relations="sister of doudizhu",
        )
        assert node.path == "game/leduc"
        assert node.parent == "game"
        assert node.correlations["game/doudizhu"] == 0.6


class TestDomainRegistry:
    def test_empty_registry(self):
        reg = DomainRegistry()
        assert len(reg) == 0
        assert reg.list_all() == []

    def test_add_and_get_node(self):
        reg = DomainRegistry()
        reg._nodes["game"] = DomainNode(
            path="game", parent=None,
            description="Games", relations="child: leduc"
        )
        node = reg.get_node("game")
        assert node is not None
        assert node.description == "Games"
        assert node.parent is None

    def test_get_nonexistent_returns_none(self):
        reg = DomainRegistry()
        assert reg.get_node("nonexistent") is None

    def test_list_all(self):
        reg = DomainRegistry()
        reg._nodes["a"] = DomainNode(path="a", parent=None, description="A")
        reg._nodes["b"] = DomainNode(path="b", parent="a", description="B")
        nodes = reg.list_all()
        assert len(nodes) == 2
        paths = {n.path for n in nodes}
        assert paths == {"a", "b"}

    def test_children_of(self):
        reg = DomainRegistry()
        reg._nodes["game"] = DomainNode(path="game", parent=None, description="G")
        reg._nodes["game/leduc"] = DomainNode(path="game/leduc", parent="game", description="L")
        reg._nodes["game/doudizhu"] = DomainNode(path="game/doudizhu", parent="game", description="D")
        reg._nodes["coding"] = DomainNode(path="coding", parent=None, description="C")
        children = reg.children_of("game")
        assert len(children) == 2
        assert {c.path for c in children} == {"game/leduc", "game/doudizhu"}

    def test_save_load_roundtrip(self, tmp_path):
        reg = DomainRegistry()
        reg._nodes["game"] = DomainNode(
            path="game", parent=None,
            description="Games", correlations={}, relations=""
        )
        reg._nodes["game/leduc"] = DomainNode(
            path="game/leduc", parent="game",
            description="Leduc", correlations={"game/doudizhu": 0.6}, relations="sib"
        )
        reg._reverse_index["l2"]["game/leduc"] = ["card_1", "card_2"]
        reg._reverse_index["l3"]["game/leduc"] = ["skill_a"]
        reg._reverse_index["tool"]["general"] = ["web_search"]

        fp = tmp_path / "registry.json"
        reg.save(fp)

        loaded = DomainRegistry.load(fp)
        assert len(loaded) == 2
        node = loaded.get_node("game/leduc")
        assert node.description == "Leduc"
        assert node.correlations == {"game/doudizhu": 0.6}
        assert loaded._reverse_index["l2"]["game/leduc"] == ["card_1", "card_2"]
        assert loaded._reverse_index["l3"]["game/leduc"] == ["skill_a"]
        assert loaded._reverse_index["tool"]["general"] == ["web_search"]

    def test_load_nonexistent_returns_empty(self, tmp_path):
        reg = DomainRegistry.load(tmp_path / "nonexistent.json")
        assert len(reg) == 0

    def _setup_registry_with_index(self):
        reg = DomainRegistry()
        reg._nodes["game/leduc"] = DomainNode(
            path="game/leduc", parent="game",
            description="Leduc", correlations={"game/doudizhu": 0.6}
        )
        reg._nodes["game/doudizhu"] = DomainNode(
            path="game/doudizhu", parent="game",
            description="Doudizhu", correlations={"game/leduc": 0.6}
        )
        reg._nodes["coding"] = DomainNode(
            path="coding", parent=None,
            description="Code", correlations={}
        )
        reg._reverse_index = {
            "l2": {
                "game/leduc": ["card_1", "card_2"],
                "game/doudizhu": ["card_3"],
                "coding": ["card_4"],
            },
            "l3": {
                "game/leduc": ["skill_a"],
            },
            "tool": {
                "general": ["web_search"],
                "game/leduc": ["poker_calc"],
            },
        }
        return reg

    def test_get_primary_items(self):
        reg = self._setup_registry_with_index()
        assert reg.get_primary_items("l2", "game/leduc") == ["card_1", "card_2"]
        assert reg.get_primary_items("l2", "nonexistent") == []

    def test_get_explore_items(self):
        reg = self._setup_registry_with_index()
        items = reg.get_explore_items("l2", "game/leduc", threshold=0.5)
        assert "card_3" in items
        assert "card_4" not in items

    def test_get_explore_items_below_threshold(self):
        reg = self._setup_registry_with_index()
        items = reg.get_explore_items("l2", "game/leduc", threshold=0.9)
        assert items == []

    def test_get_items_for_domains(self):
        reg = self._setup_registry_with_index()
        items = reg.get_items_for_domains("l2", ["game/leduc", "game/doudizhu"])
        assert sorted(items) == ["card_1", "card_2", "card_3"]

    def test_index_and_unindex(self):
        reg = DomainRegistry()
        reg.index_item("l2", "game/leduc", "card_1")
        assert reg.get_primary_items("l2", "game/leduc") == ["card_1"]
        reg.index_item("l2", "game/leduc", "card_2")
        assert reg.get_primary_items("l2", "game/leduc") == ["card_1", "card_2"]
        reg.index_item("l2", "game/leduc", "card_1")  # no dupe
        assert reg.get_primary_items("l2", "game/leduc") == ["card_1", "card_2"]
        reg.unindex_item("l2", "game/leduc", "card_1")
        assert reg.get_primary_items("l2", "game/leduc") == ["card_2"]

    def test_update_item_domains(self):
        reg = DomainRegistry()
        reg.index_item("l2", "game/leduc", "card_x")
        reg.index_item("l2", "game/doudizhu", "card_x")
        reg.update_item_domains("l2", "card_x", ["game/leduc", "coding"])
        assert reg.get_primary_items("l2", "game/leduc") == ["card_x"]
        assert reg.get_primary_items("l2", "game/doudizhu") == []
        assert reg.get_primary_items("l2", "coding") == ["card_x"]

    def test_add_node(self):
        reg = DomainRegistry()
        node = reg.add_node("coding/python", parent="coding",
                            description="Python stuff",
                            correlations={"coding": 0.9},
                            relations="sub of coding")
        retrieved = reg.get_node("coding/python")
        assert retrieved is node
        assert retrieved.description == "Python stuff"
        assert len(reg) == 1

    def test_update_correlation(self):
        reg = DomainRegistry()
        reg.add_node("a", None, "A")
        reg.add_node("b", None, "B", correlations={"a": 0.3})
        reg.update_correlation("a", "b", 0.7)
        assert reg.get_node("a").correlations == {"b": 0.7}
        assert reg.get_node("b").correlations == {"a": 0.7}

    def test_update_node(self):
        reg = DomainRegistry()
        reg.add_node("x", None, "old desc")
        result = reg.update_node("x", description="new desc", relations="hi")
        assert result is not None
        assert reg.get_node("x").description == "new desc"
        assert reg.get_node("x").relations == "hi"

    def test_update_node_nonexistent(self):
        reg = DomainRegistry()
        assert reg.update_node("nope", description="x") is None
