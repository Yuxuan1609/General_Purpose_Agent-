"""Tests for DomainRegistry dirty set + incremental correlation flush (A-1)."""
import pytest
from core.domain_registry import DomainRegistry, DomainNode


@pytest.fixture
def registry():
    reg = DomainRegistry()
    reg.add_node("general", None, "general domain")
    reg.add_node("game/leduc", "game", "leduc holdem")
    reg.add_node("game/doudizhu", "game", "dou dizhu")
    return reg


class TestDirtySet:
    def test_init_has_empty_dirty_set(self, registry):
        assert hasattr(registry, "_dirty_domains")
        assert len(registry._dirty_domains) == 0

    def test_mark_domain_dirty_adds(self, registry):
        registry.mark_domain_dirty("game/leduc")
        assert "game/leduc" in registry._dirty_domains

    def test_mark_domain_dirty_idempotent(self, registry):
        registry.mark_domain_dirty("game/leduc")
        registry.mark_domain_dirty("game/leduc")
        assert len(registry._dirty_domains) == 1

    def test_mark_nonexistent_domain_silently_ignored(self, registry):
        registry.mark_domain_dirty("nonexistent")
        assert "nonexistent" not in registry._dirty_domains


class TestFlushCorrelations:
    def test_flush_clears_dirty_set(self, registry):
        registry.mark_domain_dirty("game/leduc")
        registry.flush_correlations()
        assert len(registry._dirty_domains) == 0

    def test_flush_empty_dirty_returns_zero(self, registry):
        count = registry.flush_correlations()
        assert count == 0

    def test_flush_recomputes_for_dirty_only(self, registry):
        registry.mark_domain_dirty("game/leduc")
        count = registry.flush_correlations()
        assert count > 0
        node = registry.get_node("game/leduc")
        assert node is not None

    def test_flush_ignores_deleted_domain(self, registry):
        registry.mark_domain_dirty("deleted_domain")
        count = registry.flush_correlations()
        assert count == 0
