"""Tests for runtime_registry (A-2) and consolidation_injection (A-3)."""
import pytest
from unittest.mock import MagicMock


class TestRuntimeRegistry:
    def test_get_executor_returns_none_before_register(self):
        from core.runtime_registry import get_executor, register_runtime
        register_runtime(None, None)
        assert get_executor() is None

    def test_register_then_get(self):
        from core.runtime_registry import register_runtime, get_executor
        mock_chain = MagicMock()
        mock_exec = MagicMock()
        register_runtime(mock_chain, mock_exec)
        assert get_executor() is mock_exec
        register_runtime(None, None)

    def test_reregister_overwrites(self):
        from core.runtime_registry import register_runtime, get_executor
        e1, e2 = MagicMock(), MagicMock()
        register_runtime(None, e1)
        register_runtime(None, e2)
        assert get_executor() is e2
        register_runtime(None, None)


class TestConsolidationInjection:
    def test_set_stores(self):
        from core.tools.consolidation_injection import set_consolidation_stores, _stores
        phil, fk, sl = MagicMock(), MagicMock(), MagicMock()
        set_consolidation_stores({"l1": phil, "l2": fk, "l3": sl})
        assert _stores["l1"] is phil
        assert _stores["l2"] is fk
        assert _stores["l3"] is sl
        set_consolidation_stores({})

    def test_set_registry(self):
        import core.tools.consolidation_injection as ci
        from core.tools.consolidation_injection import set_consolidation_stores
        reg = MagicMock()
        set_consolidation_stores({}, registry=reg)
        assert ci._registry is reg
        set_consolidation_stores({})

    def test_get_store(self):
        from core.tools.consolidation_injection import set_consolidation_stores, get_store
        phil = MagicMock()
        set_consolidation_stores({"l1": phil})
        assert get_store("l1") is phil
        assert get_store("l2") is None
        set_consolidation_stores({})

    def test_get_registry(self):
        from core.tools.consolidation_injection import set_consolidation_stores, get_registry
        reg = MagicMock()
        set_consolidation_stores({}, registry=reg)
        assert get_registry() is reg
        set_consolidation_stores({})
