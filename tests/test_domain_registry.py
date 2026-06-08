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
