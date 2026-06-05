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
def stats_file(tmp_path):
    return tmp_path / "learning_stats.json"


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
def learning_env(pending_dir, knowledge_stores, stats_file):
    return LearningEnv(pending_dir, knowledge_stores, stats_file=stats_file)


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
    def test_step_with_l1_update(self, learning_env, mock_l1,
                                 sample_pending_records):
        learning_env.reset("learn from leduc games")
        action = _make_action(l1_mods=[{
            "target": "l1/rule_1", "type": "update",
            "payload": {"content": "New rule"},
        }])
        step = learning_env.step(action)
        assert "L1 rules" in step.state.observation
        mock_l1.modify_rule.assert_called_once_with("rule_1", "New rule")

    def test_step_with_l1_create(self, learning_env, mock_l1,
                                 sample_pending_records):
        learning_env.reset("learn from leduc games")
        action = _make_action(l1_mods=[{
            "target": "l1/new_rule", "type": "create",
            "payload": {"content": "New rule"},
        }])
        learning_env.step(action)
        mock_l1.add_rule.assert_called_once_with(
            "New rule", created_by="learning_env", source="l1")

    def test_step_with_l1_deprecate(self, learning_env, mock_l1,
                                    sample_pending_records):
        learning_env.reset("learn from leduc games")
        action = _make_action(l1_mods=[{
            "target": "l1/rule_old", "type": "deprecate", "payload": {},
        }])
        learning_env.step(action)
        mock_l1.remove_rule.assert_called_once_with("rule_old")

    def test_step_with_l2_mods(self, learning_env, mock_l2,
                               sample_pending_records):
        learning_env.reset("learn from leduc games")
        action = _make_action(l2_mods=[
            {"target": "l2/card_1", "type": "update",
             "payload": {"content": "Updated"}},
            {"target": "l2/new_card", "type": "create",
             "payload": {"content": "New", "domain": "game/leduc", "confidence": 0.8}},
        ])
        learning_env.step(action)
        mock_l2.modify_card.assert_called_once()
        mock_l2.add_card.assert_called_once()

    def test_step_with_l3_mods(self, learning_env, mock_l3,
                               sample_pending_records):
        learning_env.reset("learn from leduc games")
        action = _make_action(l3_mods=[
            {"target": "l3/skill_a", "type": "update",
             "payload": {"content": "# Updated skill"}},
        ])
        learning_env.step(action)
        mock_l3.edit_skill.assert_called_once_with(
            "skill_a", "# Updated skill")

    def test_step_all_layers(self, learning_env, mock_l1, mock_l2, mock_l3,
                             sample_pending_records):
        learning_env.reset("learn from leduc games")
        action = _make_action(
            l1_mods=[{"target": "l1/r1", "type": "update",
                       "payload": {"content": "r1"}}],
            l2_mods=[{"target": "l2/c1", "type": "update",
                       "payload": {"content": "c1"}}],
            l3_mods=[{"target": "l3/s1", "type": "update",
                       "payload": {"content": "# s1"}}],
        )
        step = learning_env.step(action)
        assert "L1 rules" in step.state.observation
        assert "L2 cards" in step.state.observation
        assert "L3 skills" in step.state.observation
        mock_l1.modify_rule.assert_called_once()
        mock_l2.modify_card.assert_called_once()
        mock_l3.edit_skill.assert_called_once()

    def test_step_reward_always_zero(self, learning_env,
                                     sample_pending_records):
        learning_env.reset("learn from leduc games")
        action = _make_action(l1_mods=[{
            "target": "l1/r1", "type": "update",
            "payload": {"content": "x"},
        }])
        step = learning_env.step(action)
        assert step.reward == 0.0

    def test_step_errors_captured(self, learning_env,
                                  sample_pending_records, knowledge_stores):
        learning_env.reset("learn from leduc games")
        action = _make_action(l1_mods=[{
            "target": "l1/r1", "type": "unknown_type",
            "payload": {"content": "x"},
        }])
        step = learning_env.step(action)
        assert "Errors" in step.state.observation
        assert step.reward == 0.0
        assert step.done is True

    def test_step_target_layer_mismatch(self, learning_env,
                                        sample_pending_records):
        learning_env.reset("learn from leduc games")
        action = _make_action(l1_mods=[{
            "target": "l2/wrong_layer", "type": "update",
            "payload": {"content": "x"},
        }])
        step = learning_env.step(action)
        assert "Errors" in step.state.observation

    def test_step_empty_mods(self, learning_env, sample_pending_records):
        learning_env.reset("learn from leduc games")
        action = _make_action(l1_mods=[], l2_mods=[], l3_mods=[])
        step = learning_env.step(action)
        assert "(no modifications)" in step.state.observation

    def test_step_invalid_json_fallback(self, learning_env,
                                        sample_pending_records):
        learning_env.reset("learn from leduc games")
        step = learning_env.step("not json at all")
        assert step.done is True

    def test_step_content_too_long_rejected(self, learning_env, mock_l1,
                                            sample_pending_records):
        learning_env.reset("learn from leduc games")
        action = _make_action(l1_mods=[{
            "target": "l1/r1", "type": "update",
            "payload": {"content": "x" * 600},
        }])
        step = learning_env.step(action)
        assert "Errors" in step.state.observation


# ── tests: usage stats ──────────────────────────────────────────────────

class TestUsageStats:
    def test_updates_l2_stats_from_notify(self, learning_env,
                                          sample_pending_records, stats_file):
        learning_env.reset("learn from leduc games")
        notify = {
            "l0_5_1": {"result": "ok", "l1_modifications": []},
            "l2": {
                "reply": "ok",
                "l2_modifications": [],
                "cards_used": ["card_a", "card_b"],
            },
        }
        learning_env.step(json.dumps(notify))
        assert stats_file.exists()
        stats = json.loads(stats_file.read_text())
        assert stats["l2"]["card_a"]["use_count"] == 1
        assert stats["l2"]["card_b"]["use_count"] == 1

    def test_updates_l3_stats_from_notify(self, learning_env,
                                          sample_pending_records, stats_file):
        learning_env.reset("learn from leduc games")
        notify = {
            "l0_5_1": {"result": "ok", "l1_modifications": []},
            "l2": {"reply": "ok", "l2_modifications": [], "cards_used": []},
            "l3": {
                "skills_matched": 2,
                "skills_used": [{"name": "skill_x"}, {"name": "skill_y"}],
                "l3_modifications": [],
            },
        }
        learning_env.step(json.dumps(notify))
        stats = json.loads(stats_file.read_text(encoding="utf-8"))
        assert stats["l3"]["skill_x"]["use_count"] == 1

    def test_does_not_track_l1(self, learning_env,
                               sample_pending_records, stats_file):
        learning_env.reset("learn from leduc games")
        action = _make_action(l1_mods=[{
            "target": "l1/r1", "type": "update",
            "payload": {"content": "x"},
        }])
        learning_env.step(action)
        stats = json.loads(stats_file.read_text())
        assert "l1" not in stats or stats.get("l1", {}) == {}


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
        assert "l1_modifications" in fmt
        items = fmt["l1_modifications"]
        assert isinstance(items, list)
        assert items[0]["type"].startswith("update")
        assert "l2_modifications" in obs.state["l2_output_format"]
        assert "l3_modifications" in obs.state["l3_output_format"]

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
        assert "L2 Cards" in task.meta
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
