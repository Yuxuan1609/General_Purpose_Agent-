"""Tests for ReflectCoordinator."""
import json
from pathlib import Path
from core.orchestrator.reflect_coordinator import ReflectCoordinator


class TestReflectCoordinator:
    @staticmethod
    def _make_dirs(tmp_path):
        pending = tmp_path / "pending"
        learned = tmp_path / "learned"
        pending.mkdir()
        learned.mkdir()
        return pending, learned

    @staticmethod
    def _write_record(path: Path, domain: str, session_id: str,
                      notify: dict | None = None, action: str | None = None):
        rec = {
            "session": {"id": session_id, "domain": domain},
            "observation": {"meta": "test", "state": {}},
            "notify_layers": notify or {},
            "action": action,
        }
        path.write_text(json.dumps(rec))

    def test_audit_empty_pending(self, tmp_path):
        pending, learned = self._make_dirs(tmp_path)
        coord = ReflectCoordinator(pending, learned)
        result = coord.audit("game/leduc")
        assert result["l0_5_1"] == []
        assert result["l2"] == []
        assert result["l3"] == []

    def test_audit_detects_no_action(self, tmp_path):
        pending, learned = self._make_dirs(tmp_path)
        self._write_record(pending / "s1.json", "game/leduc", "s1", action=None)
        coord = ReflectCoordinator(pending, learned)
        result = coord.audit("game/leduc")
        assert len(result["l0_5_1"]) == 1
        assert result["l0_5_1"][0]["type"] == "decision_error"

    def test_audit_extracts_notify_issues(self, tmp_path):
        pending, learned = self._make_dirs(tmp_path)
        notify = {
            "l2": {"issues": [{"type": "card_confidence_low"}]},
            "l3": {"issues": [{"type": "skill_missing"}]},
        }
        self._write_record(pending / "s1.json", "game/leduc", "s1",
                           notify=notify, action="call")
        coord = ReflectCoordinator(pending, learned)
        result = coord.audit("game/leduc")
        assert len(result["l2"]) == 1
        assert len(result["l3"]) == 1
        assert len(result["l0_5_1"]) == 0

    def test_archive_moves_records(self, tmp_path):
        pending, learned = self._make_dirs(tmp_path)
        self._write_record(pending / "s1.json", "game/leduc", "s1", action="call")
        coord = ReflectCoordinator(pending, learned)
        coord._archive("game/leduc")
        assert not (pending / "s1.json").exists()
        assert (learned / "game/leduc" / "s1.json").exists()

    def test_archive_only_target_domain(self, tmp_path):
        pending, learned = self._make_dirs(tmp_path)
        self._write_record(pending / "s1.json", "game/leduc", "s1")
        self._write_record(pending / "s2.json", "game/doudizhu", "s2")
        coord = ReflectCoordinator(pending, learned)
        coord._archive("game/leduc")
        assert not (pending / "s1.json").exists()
        assert (pending / "s2.json").exists()
