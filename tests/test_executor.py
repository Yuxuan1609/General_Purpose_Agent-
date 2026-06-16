import pytest
from unittest.mock import Mock
from core.types import TaskObservation
from core.layers.base import LayerManager


class _MockLayer(LayerManager):
    def __init__(self, name, notify_data=None, downstream=None):
        super().__init__(name, downstream)
        self._notify_data = notify_data or {}
    def process(self, data):
        data.state[f"{self.name}_seen"] = True
        return {"status": "ok"}
    def notify(self):
        return self._notify_data
    def apply_update(self, key, value):
        pass


@pytest.fixture
def mock_llm():
    llm = Mock()
    llm.chat.return_value = Mock(text="33", tool_calls=[], has_tool_calls=False)
    return llm


@pytest.fixture
def layer_chain():
    l3 = _MockLayer("l3", notify_data={"skills": 2})
    l2 = _MockLayer("l2", notify_data={"cards": 3}, downstream=l3)
    l1 = _MockLayer("l0_5_1", notify_data={"rules": 5}, downstream=l2)
    return l1


class TestExecutor:
    def test_execute_runs_full_chain(self, mock_llm, layer_chain):
        from core.executor import Executor

        executor = Executor(
            layer_root=layer_chain,
            llm_client=mock_llm,
        )

        obs = TaskObservation(
            meta="game rules",
            state={"hand": "3 4 5 6 7"},
        )

        result = executor.execute(obs)

        assert "action_text" in result
        assert "notify_layers" in result
        assert obs.state["l0_5_1_seen"]
        assert obs.state["l2_seen"]
        assert obs.state["l3_seen"]

    def test_execute_returns_notify_data(self, mock_llm, layer_chain):
        from core.executor import Executor

        executor = Executor(layer_root=layer_chain, llm_client=mock_llm)

        obs = TaskObservation(meta="game rules", state={})
        result = executor.execute(obs)

        assert "notify_layers" in result
        assert result["notify_layers"]["l0_5_1"]["rules"] == 5
        assert result["notify_layers"]["l2"]["cards"] == 3
        assert result["notify_layers"]["l3"]["skills"] == 2

    def test_execute_no_longer_writes_pending(self, mock_llm, layer_chain, tmp_path):
        """_write_pending is deprecated — record_learning tool handles learning now."""
        from core.executor import Executor

        learning_dir = tmp_path / "data" / "learning"
        executor = Executor(
            layer_root=layer_chain,
            llm_client=mock_llm,
            learning_dir=learning_dir,
        )

        obs = TaskObservation(
            meta="game rules",
            state={},
            session={"id": "test-session", "domain": "game/doudizhu"},
        )

        executor.execute(obs)

        pending = learning_dir / "pending"
        files = list(pending.rglob("*.json")) if pending.exists() else []
        assert len(files) == 0

    def test_execute_skips_pending_when_learning_disabled(self, mock_llm, layer_chain, tmp_path):
        from core.executor import Executor

        executor = Executor(
            layer_root=layer_chain,
            llm_client=mock_llm,
            learning_dir=None,
        )

        obs = TaskObservation(
            meta="game rules",
            state={},
            session={"id": "s1"},
        )

        executor.execute(obs)
