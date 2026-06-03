import pytest
from unittest.mock import Mock
from pathlib import Path
from core.types import TaskObservation
from core.layers import build_chain
from core.executor import Executor


@pytest.fixture
def mock_llm_with_action():
    llm = Mock()
    llm.chat.return_value = Mock(
        text="33",
        tool_calls=[],
        has_tool_calls=False,
    )
    return llm


@pytest.fixture
def full_chain(tmp_path):
    from core.meta_driver import MetaDriver, DEFAULT_TRIGGERS, DEFAULT_VALIDATORS
    from core.philosophy import Philosophy
    from core.flexible_knowledge import FlexibleKnowledge
    from core.skill_layer import SkillLayer
    from core.tools.registry import ToolRegistry

    rules_path = tmp_path / "l1_rules.json"
    rules_path.write_text('{"version":1,"rules":[{"id":"r1","content":"test rule","created_by":"seed","added_at":"","version":1,"last_modified":""}]}')

    knowledge_dir = tmp_path / "knowledge"
    knowledge_dir.mkdir()
    index_path = knowledge_dir / "l2_index.json"
    index_path.write_text('{"version":1,"chapters":[],"relations":[]}')

    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()

    meta = MetaDriver(DEFAULT_TRIGGERS.copy(), DEFAULT_VALIDATORS.copy())
    phil = Philosophy(rules_path)
    fk = FlexibleKnowledge(knowledge_dir, index_path)
    sl = SkillLayer(skills_dir, ToolRegistry())

    return build_chain(meta, phil, fk, sl)


class TestEndToEnd:
    def test_full_execute_chain(self, full_chain, mock_llm_with_action):
        executor = Executor(layer_root=full_chain, llm_client=mock_llm_with_action)

        obs = TaskObservation(
            meta={"domain": "game/doudizhu", "role": "地主上家"},
            state={"hand": "3 4 5 6 7", "legal_actions": "1. 33  2. 过"},
        )

        result = executor.execute(obs)

        assert "action_text" in result
        assert result["action_text"] == "33"
        assert "notify_layers" in result
        assert "l0_5_1" in result["notify_layers"]
        assert "l2" in result["notify_layers"]
        assert "l3" in result["notify_layers"]

    def test_meta_gets_rule_from_l1(self, full_chain, mock_llm_with_action):
        executor = Executor(layer_root=full_chain, llm_client=mock_llm_with_action)

        obs = TaskObservation(meta={"domain": "game/doudizhu"})
        executor.execute(obs)

        assert "l1_rules" in obs.meta
        assert len(obs.meta["l1_rules"]) >= 1

    def test_learning_disabled_no_pending_file(self, full_chain, mock_llm_with_action, tmp_path):
        learning_dir = tmp_path / "learning"
        executor = Executor(layer_root=full_chain, llm_client=mock_llm_with_action,
                           learning_dir=learning_dir)

        obs = TaskObservation(
            meta={"domain": "game/doudizhu", "enable_learning": False},
            state={"session": {"id": "s1"}},
        )
        executor.execute(obs)

        pending = learning_dir / "pending"
        assert not (pending.exists() and list(pending.glob("*.json")))

    def test_learning_enabled_writes_pending(self, full_chain, mock_llm_with_action, tmp_path):
        learning_dir = tmp_path / "learning"
        executor = Executor(layer_root=full_chain, llm_client=mock_llm_with_action,
                           learning_dir=learning_dir)

        obs = TaskObservation(
            meta={"domain": "game/doudizhu", "enable_learning": True},
            state={"session": {"id": "learn-s1", "datetime": "2026-01-01", "meta_hash": "abc"}},
        )
        executor.execute(obs)

        pending = learning_dir / "pending"
        files = list(pending.glob("*.json"))
        assert len(files) == 1
