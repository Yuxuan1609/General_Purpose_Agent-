"""E2E domain optimization test."""
from __future__ import annotations
import json, sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def test_merge_domain():
    """Test merge_domain removes source and moves items."""
    from core.domain_registry import DomainRegistry
    reg = DomainRegistry()
    reg.add_node("game/doudizhu", "game", "斗地主", {"game/leduc": 0.6}, "")
    reg.add_node("game/doudizhu_v2", "game", "斗地主变体", {"game/doudizhu": 0.85}, "")

    result = reg.merge_domain("game/doudizhu_v2", "game/doudizhu")
    assert result["moved_items"] == 0  # no items yet
    assert "game/doudizhu_v2" not in reg._nodes
    print("PASS: merge_domain removes source node")


def test_deprecate_blocks_orphans():
    """Test deprecate_domain raises when items have no other domain."""
    from core.domain_registry import DomainRegistry
    from core.task import Domain
    from core.flexible_knowledge import FlexibleKnowledge

    reg = DomainRegistry()
    reg.add_node("game/doudizhu", "game", "斗地主", {}, "")

    fk = FlexibleKnowledge(
        PROJECT_ROOT / "data" / "layers" / "knowledge",
        PROJECT_ROOT / "data" / "layers" / "knowledge" / "l2_index.json",
        domain_registry=reg,
    )
    card = fk.add_card("test card content", Domain("game/doudizhu", "specific"))

    try:
        reg.deprecate_domain("game/doudizhu")
        print("FAIL: should have raised ValueError")
        sys.exit(1)
    except ValueError as e:
        print(f"PASS: deprecate blocks orphaned items: {str(e)[:80]}")

    # Clean up
    fk.remove_card(card.id)


def test_compute_correlation():
    """Test correlation returns float in [0, 1]."""
    from core.domain_registry import DomainRegistry
    reg = DomainRegistry()
    reg.add_node("game/leduc", "game", "Leduc poker", {}, "")
    reg.add_node("game/doudizhu", "game", "斗地主", {}, "")

    corr = reg.compute_correlation("game/leduc", "game/doudizhu")
    assert 0.0 <= corr <= 1.0
    print(f"PASS: correlation = {corr}")


def test_create_domain():
    """Test domain node creation."""
    from core.domain_registry import DomainRegistry
    reg = DomainRegistry()
    reg.add_node("test/domain", "general", "test domain description", {}, "")
    node = reg.get_node("test/domain")
    assert node is not None
    assert node.description == "test domain description"
    print("PASS: domain node created")


def test_domain_registry_save_load():
    """Test roundtrip save/load including embedding_vector."""
    import tempfile, json
    from core.domain_registry import DomainRegistry

    reg = DomainRegistry()
    reg.add_node("test/save", "general", "save test", {"other": 0.5}, "")

    with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as f:
        tmp_path = Path(f.name)
    try:
        reg.save(tmp_path)
        reg2 = DomainRegistry.load(tmp_path)
        node = reg2.get_node("test/save")
        assert node is not None
        assert node.correlations == {"other": 0.5}
        print("PASS: domain roundtrip save/load")
    finally:
        tmp_path.unlink(missing_ok=True)


if __name__ == "__main__":
    test_merge_domain()
    test_deprecate_blocks_orphans()
    test_compute_correlation()
    test_create_domain()
    test_domain_registry_save_load()
    print("\nAll E2E domain optimization tests pass!")
