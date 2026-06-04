from core.types import TaskObservation, ExecutionRecord
from core.task import LearningUnit, Domain


class TestTaskObservation:
    def test_defaults(self):
        obs = TaskObservation()
        assert obs.meta == ""
        assert obs.state == {}
        assert obs.session is None

    def test_with_meta_str(self):
        obs = TaskObservation(meta="You are playing Leduc Hold'em")
        assert "Leduc" in obs.meta
        assert obs.state == {}

    def test_with_state(self):
        obs = TaskObservation(state={"current": "Round: pre-flop", "history": ""})
        assert obs.state["current"] == "Round: pre-flop"

    def test_session_field(self):
        obs = TaskObservation(session={"id": "s1", "domain": "game/doudizhu"})
        assert obs.session["id"] == "s1"
        assert obs.session["domain"] == "game/doudizhu"


class TestExecutionRecord:
    def test_defaults(self):
        rec = ExecutionRecord()
        assert rec.session == {}
        assert rec.observation == {}
        assert rec.notify_layers == {}

    def test_full_record(self):
        rec = ExecutionRecord(
            session={"id": "s1", "datetime": "2026-01-01T00:00:00", "meta_hash": "abc"},
            observation={"meta": "Game rules", "state": {"current": "pre-flop"}},
            notify_layers={"l0_5_1": "ok", "l2": "ok", "l3": "ok"},
            action=[3, 3],
            result={"winner": "landlord"},
        )
        assert rec.action == [3, 3]
        assert rec.result["winner"] == "landlord"


class TestTaskEnableLearning:
    def test_enable_learning_defaults_to_false(self):
        task = LearningUnit(description="test")
        assert task.enable_learning is False

    def test_enable_learning_true(self):
        task = LearningUnit(description="test", enable_learning=True)
        assert task.enable_learning is True
