"""Unit tests for LearningEnv skeleton (Phase 2.1)."""
import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock

from core.env.learning_env import LearningEnv
from core.env.base import EnvState, EnvStep


# ── fixtures ────────────────────────────────────────────────────────────

@pytest.fixture
def pending_dir(tmp_path):
    d = tmp_path / "pending"
    d.mkdir()
    return d


@pytest.fixture
def mock_l1():
    store = MagicMock()
    store.add_rule.return_value = MagicMock(id="l1_new")
    store.modify_rule.return_value = MagicMock(id="l1_mod")
    return store


@pytest.fixture
def mock_l2():
    store = MagicMock()
    store.add_card.return_value = MagicMock(id="card_new")
    store.modify_card.return_value = MagicMock(id="card_mod")
    store.remove_card.return_value = True
    store.cards = []
    return store


@pytest.fixture
def mock_l3():
    store = MagicMock()
    store.create_skill.return_value = MagicMock(name="skill_new")
    store.edit_skill.return_value = MagicMock(name="skill_mod")
    store.list_all.return_value = []
    return store


@pytest.fixture
def knowledge_stores(mock_l1, mock_l2, mock_l3):
    return {"l1": mock_l1, "l2": mock_l2, "l3": mock_l3}


@pytest.fixture
def learning_env(pending_dir, knowledge_stores):
    return LearningEnv(pending_dir, knowledge_stores)


@pytest.fixture
def sample_pending_records(pending_dir):
    domain_dir = pending_dir / "game_leduc"
    domain_dir.mkdir()
    rec = [{
        "session": {"id": "sess_1", "domain": "game/leduc", "step_index": 0},
        "observation": {"meta": "Play Leduc", "state": {}},
        "notify_layers": {
            "l0_5_1": {"result": "raise", "reasoning": "Strong hand"},
            "l2": {"cards_used": ["card_a"], "l3_received": {"skills": []}},
        },
        "action": "raise",
    }]
    fpath = domain_dir / "sess_1_20260605.json"
    fpath.write_text(json.dumps(rec))
    return domain_dir


def _make_action(l1_mods=None, l2_mods=None, l3_mods=None):
    """Build a notify_layers JSON matching Executor output format."""
    notify = {}
    if l1_mods is not None:
        notify["l0_5_1"] = {"result": "ok", "done": True, "l1_modifications": l1_mods}
    if l2_mods is not None:
        notify["l2"] = {"reply": "ok", "l2_modifications": l2_mods, "cards_used": []}
    if l3_mods is not None:
        notify["l3"] = {"skills_matched": [], "l3_modifications": l3_mods}
    return json.dumps(notify)


# ── tests: init ─────────────────────────────────────────────────────────

class TestLearningEnvInit:
    def test_creates_with_defaults(self, pending_dir, knowledge_stores):
        env = LearningEnv(pending_dir, knowledge_stores)
        assert env._pending_dir == pending_dir
        assert env._knowledge is knowledge_stores
        assert env._step_count == 0
        assert env._done is False

    def test_accepts_preprocessing_llm(self, pending_dir, knowledge_stores):
        llm = MagicMock()
        env = LearningEnv(pending_dir, knowledge_stores, preprocessing_llm=llm)
        assert env._pre_llm is llm


# ── tests: reset ────────────────────────────────────────────────────────

class TestLearningEnvReset:
    def test_no_pending_returns_empty_observation(self, learning_env):
        state = learning_env.reset("learn from leduc games")
        assert state.observation == ""

    def test_returns_observation_with_pending(
        self, learning_env, sample_pending_records,
    ):
        state = learning_env.reset("learn from leduc games")
        assert "game/leduc" in state.observation


# ── tests: step (per-layer notify format) ───────────────────────────────

class TestLearningEnvStep:
    """Step is lightweight post-A: handlers directly modify stores; step just
    bumps count and marks done. Application layer (_apply_*, _parse_*) deleted."""

    def test_step_marks_done(self, learning_env, sample_pending_records):
        learning_env.reset("learn from leduc games")
        step = learning_env.step('{"any": "json"}')
        assert step.done is True

    def test_step_bumps_count(self, learning_env, sample_pending_records):
        learning_env.reset("learn from leduc games")
        assert learning_env._step_count == 0
        learning_env.step('{}')
        assert learning_env._step_count == 1

    def test_step_reward_always_zero(self, learning_env, sample_pending_records):
        learning_env.reset("learn from leduc games")
        step = learning_env.step("any text")
        assert step.reward == 0.0

    def test_step_sets_feedback(self, learning_env, sample_pending_records):
        learning_env.reset("learn from leduc games")
        learning_env.step('{}')
        assert learning_env._shared_feedback != ""

    def test_apply_modifications_marks_done(self, learning_env, sample_pending_records):
        learning_env.reset("learn from leduc games")
        step = learning_env.apply_modifications({})
        assert step.done is True


# ── tests: build_task_observation ───────────────────────────────────────

class TestBuildTaskObservation:
    def test_meta_has_task_content(self, learning_env,
                                    sample_pending_records):
        learning_env.reset("learn from leduc games")
        obs = learning_env.build_task_observation()
        assert obs is not None
        assert "game/leduc" in obs.meta

    def test_state_has_per_layer_format(self, learning_env,
                                        sample_pending_records):
        learning_env.reset("learn from leduc games")
        obs = learning_env.build_task_observation()
        fmt = obs.state["l1_output_format"]
        assert "properties" in fmt
        assert "notify" in fmt["properties"]
        assert "l1_modifications" in fmt["properties"]["notify"]["properties"]
        assert "response" in fmt["properties"]
        assert "l2_output_format" in obs.state
        assert "l3_output_format" in obs.state

    def test_returns_none_before_reset(self, learning_env):
        obs = learning_env.build_task_observation()
        assert obs is None


# ── tests: consolidation task ───────────────────────────────────────────

class TestConsolidationTask:
    def test_no_consolidation_when_under_limit(self, learning_env):
        task = learning_env.build_consolidation_task()
        assert task is None

    def test_triggers_when_l2_over_limit(self, learning_env, knowledge_stores):
        from core.flexible_knowledge import KnowledgeCard
        from core.task import Domain
        l2 = knowledge_stores["l2"]
        l2.cards = [
            KnowledgeCard(id=f"card_{i}", content=f"Content {i}",
                          domain=Domain("game/leduc", "specific"))
            for i in range(35)
        ]
        task = learning_env.build_consolidation_task()
        assert task is not None
        assert "L2 Knowledge Cards" in task.meta or "L2 Cards" in task.meta
        assert "Consolidation" in task.meta or "deprecate" in task.meta

    def test_triggers_when_l3_over_limit(self, learning_env, knowledge_stores):
        from core.skill_layer import SkillMeta
        from core.task import Domain
        l3 = knowledge_stores["l3"]
        skills = []
        for i in range(25):
            m = MagicMock()
            m.name = f"skill_{i}"
            m.domain = Domain("game/leduc", "specific")
            m.description = f"desc {i}"
            skills.append(m)
        l3.list_all.return_value = skills
        task = learning_env.build_consolidation_task()
        assert task is not None
        assert "L3 Skills" in task.meta or "L3" in task.meta

    def test_consolidation_session_has_learning_compile_domain(self, learning_env, knowledge_stores):
        from core.flexible_knowledge import KnowledgeCard
        from core.task import Domain
        l2 = knowledge_stores["l2"]
        l2.cards = [
            KnowledgeCard(id=f"card_{i}", content=f"C{i}",
                          domain=Domain("game/leduc", "specific"))
            for i in range(35)
        ]
        task = learning_env.build_consolidation_task()
        assert task.session["domain"] == "learning/compile"
        assert "learning/compile" in task.session["domains_hint"]


# ── tests: consolidation limit source (#14) ─────────────────────────────

class TestConsolidationLimitSource:
    """LearningEnv 默认限制必须取自 consolidation.l*.limits.soft，
    不再从 learning.l2_card_limit/l3_skill_limit 读取（修复 spec/代码脱钩）。"""

    def test_l2_default_reads_consolidation_soft(self, pending_dir, knowledge_stores):
        from core.config_loader import get_section
        soft = get_section('consolidation', default={}).get('l2', {}).get('limits', {}).get('soft')
        assert soft is not None, "config.yaml must define consolidation.l2.limits.soft"
        env = LearningEnv(pending_dir, knowledge_stores)
        assert env._l2_limit == soft

    def test_l3_default_reads_consolidation_soft(self, pending_dir, knowledge_stores):
        from core.config_loader import get_section
        soft = get_section('consolidation', default={}).get('l3', {}).get('limits', {}).get('soft')
        assert soft is not None, "config.yaml must define consolidation.l3.limits.soft"
        env = LearningEnv(pending_dir, knowledge_stores)
        assert env._l3_limit == soft

    def test_constructor_override_still_wins(self, pending_dir, knowledge_stores):
        env = LearningEnv(pending_dir, knowledge_stores,
                          l2_card_limit=50, l3_skill_limit=40)
        assert env._l2_limit == 50
        assert env._l3_limit == 40
