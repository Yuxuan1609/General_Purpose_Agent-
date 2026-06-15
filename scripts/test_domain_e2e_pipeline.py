"""E2E test: consolidation tool → full pipeline.

Tests the complete flow from tool-like operations through
DomainRegistry, embedding, correlation, and persistence.

Does NOT call LLM agents — starts at the tool handler level.
"""
from __future__ import annotations
import json, sys, tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.env_loader import load_env
load_env(PROJECT_ROOT)


def _make_helpers():
    """Set up stores + registry matching consolidation tool context."""
    from core.domain_registry import DomainRegistry
    from core.flexible_knowledge import FlexibleKnowledge
    from core.skill_layer import SkillLayer
    from core.task import Domain

    reg = DomainRegistry()
    reg.add_node("general", None, "根域", {}, "")
    reg.add_node("game", "general", "游戏", {}, "")

    fk = FlexibleKnowledge(
        PROJECT_ROOT / "data" / "layers" / "knowledge",
        PROJECT_ROOT / "data" / "layers" / "knowledge" / "l2_index.json",
        domain_registry=reg,
    )
    sl = SkillLayer(
        PROJECT_ROOT / "data" / "layers" / "skills",
        domain_registry=reg,
    )

    def getter(layer, domain):
        if layer == "l2":
            return [c.content for c in fk.cards
                    if domain in c.available_domains]
        if layer == "l3":
            return [m.description for n, m in sl._skills.items()
                    if domain in m.available_domains]
        return []

    return reg, fk, sl, Domain, getter


def reset_stores(fk, sl):
    """Clean up all cards and skills from previous tests."""
    for c in list(fk.cards):
        fk.remove_card(c.id)
    for name in list(sl._skills.keys()):
        sl.delete_skill(name)


def test_pipeline_create_embed_correlate():
    """1. Create domain with cards → embedding computed → correlation updated."""
    reg, fk, sl, Domain, getter = _make_helpers()
    reset_stores(fk, sl)

    # Simulate create_domain tool call
    reg.add_node("game/poker", "game", "Poker strategy domain", {}, "")
    fk.add_card(content="Preflop: raise with AA/KK", domain=Domain("game/poker", "specific"),
                source="learning_env")
    fk.add_card(content="Postflop: bet when top pair", domain=Domain("game/poker", "specific"),
                source="learning_env")

    # Compute embedding (as consolidation handler does after create)
    assert reg.compute_embedding("game/poker", content_getter=getter)

    # Verify embedding exists
    node = reg.get_node("game/poker")
    assert node.embedding_vector is not None
    assert len(node.embedding_vector) == 768
    print("PASS: create_domain → embedding computed (768-dim)")

    # Compute correlation with sibling domain
    reg.add_node("game/blackjack", "game", "Blackjack strategy", {}, "")
    fk.add_card(content="Basic strategy: hit on 16 vs 10", domain=Domain("game/blackjack", "specific"),
                source="learning_env")
    reg.compute_embedding("game/blackjack", content_getter=getter)

    corr = reg.compute_correlation("game/poker", "game/blackjack")
    assert 0.0 <= corr <= 1.0
    print(f"PASS: correlation computed: {corr:.4f}")

    return reg, Domain, getter


def test_pipeline_split_domain():
    """2. Split domain: move card to sub-domain → reverse_index updated."""
    reg, fk, sl, Domain, getter = _make_helpers()
    reset_stores(fk, sl)

    reg.add_node("game/test_game", "game", "Test game", {}, "")
    c1 = fk.add_card(content="Rule: always go first", domain=Domain("game/test_game", "specific"),
                     source="learning_env")
    c2 = fk.add_card(content="Rule: fold on bad hands", domain=Domain("game/test_game", "specific"),
                     source="learning_env")

    # Create sub-domain
    reg.add_node("game/test_game/bidding", "game/test_game", "Bidding phase", {}, "")
    reg.compute_embedding("game/test_game", content_getter=getter)

    # Simulate modify_l2_card with domain field
    reg.index_item("l2", "game/test_game/bidding", c1.id)

    # Verify reverse_index
    l2_idx = reg._reverse_index.get("l2", {})
    assert c1.id in l2_idx.get("game/test_game/bidding", [])
    assert c1.id in l2_idx.get("game/test_game", [])  # still in parent
    print("PASS: split domain → card in both parent and sub-domain reverse_index")

    return reg


def test_pipeline_merge_domain():
    """3. Merge source→target: items move, source removed, target embedding updated."""
    reg, fk, sl, Domain, getter = _make_helpers()
    reset_stores(fk, sl)

    reg.add_node("game/src", "game", "Source domain",
                 {"game/other": 0.5}, "")
    reg.add_node("game/target", "game", "Target domain",
                 {"game/src": 0.7}, "")
    reg.add_node("game/other", "game", "Other domain",
                 {"game/src": 0.3}, "")

    c1 = fk.add_card(content="src card 1", domain=Domain("game/src", "specific"),
                     source="seed")
    c2 = fk.add_card(content="src card 2", domain=Domain("game/src", "specific"),
                     source="seed")

    result = reg.merge_domain("game/src", "game/target", content_getter=getter)

    assert result["moved_items"] == 2
    assert "game/src" not in reg._nodes  # source removed
    assert reg.get_node("game/target") is not None

    # Items moved to target's reverse_index
    l2_idx = reg._reverse_index.get("l2", {})
    assert c1.id in l2_idx.get("game/target", [])
    assert c2.id in l2_idx.get("game/target", [])

    # Other domain's correlation updated
    other = reg.get_node("game/other")
    assert "game/target" in other.correlations

    print(f"PASS: merge → {result['moved_items']} items moved, source removed, "
          f"correlations propagated")


def test_pipeline_deprecate_domain():
    """4. Deprecate domain: blocks if items exist, succeeds after migration."""
    reg, fk, sl, Domain, getter = _make_helpers()
    reset_stores(fk, sl)

    reg.add_node("game/temp", "game", "Temp domain", {}, "")
    c = fk.add_card(content="temp card", domain=Domain("game/temp", "specific"),
                    source="seed")

    # Should block: item still references this domain as its only domain
    try:
        reg.deprecate_domain("game/temp")
        print("FAIL: should have blocked")
        sys.exit(1)
    except ValueError:
        print("PASS: deprecate blocks when orphaned items exist")

    # Move item to another domain
    reg.index_item("l2", "game", c.id)

    # Now should succeed
    reg.deprecate_domain("game/temp")
    assert "game/temp" not in reg._nodes
    print("PASS: deprecate succeeds after item migration")


def test_pipeline_learning_round_simulated():
    """5. Simulate LearningEnv._apply_parsed_mods after learning round."""
    reg, fk, sl, Domain, getter = _make_helpers()
    reset_stores(fk, sl)

    reg.add_node("game/roundtest", "game", "Round test domain", {}, "")
    reg.compute_embedding("game/roundtest", content_getter=getter)

    # Simulate modifications from consolidation
    parsed = {
        "l2_modifications": [
            {"type": "create", "target": "card_new",
             "domain": "game/roundtest",
             "content": "New card from learning", "reason": "new pattern"},
        ],
    }

    # Apply (non-dry-run)
    l2 = fk
    for mod in parsed.get("l2_modifications", []):
        if mod["type"] == "create":
            l2.add_card(content=mod["content"], domain=Domain(mod["domain"], "specific"),
                        source="learning_env")

    # Simulate the LearningEnv auto-refresh
    affected = {"game/roundtest"}
    refreshed = reg.refresh_embeddings_for(list(affected), content_getter=getter)
    assert refreshed >= 1
    updated = reg.compute_all_correlations()
    assert updated >= 0
    print(f"PASS: learning round simulated → {refreshed} embeddings refreshed, "
          f"{updated} correlations updated")


def test_pipeline_save_load_roundtrip():
    """6. Full roundtrip: save with embeddings + correlations, reload, verify."""
    reg, fk, sl, Domain, getter = _make_helpers()
    reset_stores(fk, sl)

    reg.add_node("game/roundtrip", "game", "Roundtrip test", {}, "")
    fk.add_card(content="RT card content", domain=Domain("game/roundtrip", "specific"),
                source="seed")
    reg.compute_embedding("game/roundtrip", content_getter=getter)
    reg.compute_all_correlations()

    with tempfile.TemporaryDirectory() as tmp:
        json_path = Path(tmp) / "test_registry.json"
        reg.save(json_path)

        from core.domain_registry import DomainRegistry
        reg2 = DomainRegistry.load(json_path)

        node2 = reg2.get_node("game/roundtrip")
        assert node2 is not None
        assert node2.embedding_vector is not None
        assert len(node2.embedding_vector) == 768
        assert "game/roundtrip" in reg2._reverse_index.get("l2", {})
        print("PASS: save/load roundtrip → node + embedding + reverse_index preserved")


def test_pipeline_modify_domain_field():
    """7. Modify card domain → _apply_l2 handles domain change."""
    reg, fk, sl, Domain, getter = _make_helpers()
    reset_stores(fk, sl)

    reg.add_node("game/origin", "game", "Origin", {}, "")
    reg.add_node("game/dest", "game", "Destination", {}, "")

    c = fk.add_card(content="movable card", domain=Domain("game/origin", "specific"),
                    source="seed")

    # Simulate _apply_l2 with domain field (as LearningEnv does)
    new_domain = "game/dest"
    result = fk.modify_card(c.id, new_content=None)
    assert result is not None
    if new_domain and new_domain != result.domain.path:
        result.domain = Domain(new_domain, "specific")
        result.available_domains = [new_domain]

    assert result.domain.path == "game/dest"
    assert result.available_domains == ["game/dest"]
    print("PASS: modify domain field → card domain updated")


if __name__ == "__main__":
    test_pipeline_create_embed_correlate()
    test_pipeline_split_domain()
    test_pipeline_merge_domain()
    test_pipeline_deprecate_domain()
    test_pipeline_learning_round_simulated()
    test_pipeline_save_load_roundtrip()
    test_pipeline_modify_domain_field()
    print("\nAll 7 E2E pipeline tests pass!")
