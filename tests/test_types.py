from core.types import TaskObservation, ExecutionRecord
from core.task import Task, Domain


class TestTaskObservation:
    def test_defaults(self):
        obs = TaskObservation()
        assert obs.meta == {}
        assert obs.state == {}
        assert obs.history is None

    def test_with_history(self):
        obs = TaskObservation(history=[{"role": "agent", "action": "33"}])
        assert len(obs.history) == 1

    def test_meta_field_setter(self):
        obs = TaskObservation()
        obs.meta["domain"] = "game/doudizhu"
        obs.meta["enable_learning"] = True
        assert obs.meta["domain"] == "game/doudizhu"
        assert obs.meta["enable_learning"] is True


class TestExecutionRecord:
    def test_defaults(self):
        rec = ExecutionRecord()
        assert rec.session == {}
        assert rec.observation == {}
        assert rec.notify_layers == {}

    def test_full_record(self):
        rec = ExecutionRecord(
            session={"id": "s1", "datetime": "2026-01-01T00:00:00", "meta_hash": "abc"},
            observation={"meta": {"domain": "game/doudizhu"}},
            notify_layers={"l0_5_1": "ok", "l2": "ok", "l3": "ok"},
            action=[3, 3],
            result={"winner": "landlord"},
        )
        assert rec.action == [3, 3]
        assert rec.result["winner"] == "landlord"


class TestTaskEnableLearning:
    def test_enable_learning_defaults_to_false(self):
        task = Task(description="test")
        assert task.enable_learning is False

    def test_enable_learning_true(self):
        task = Task(description="test", enable_learning=True)
        assert task.enable_learning is True
