# REFACTOR: LearningEnv — TaskDecomposer is partially recyclable as LearningUnit splitter in LearningEnv.
import pytest
from pathlib import Path
from core.task import LearningUnit, Domain
from core.orchestrator.task_decomposer import TaskDecomposer


class TestDecomposerGameUnit:
    def test_doudizhu_returns_single_unit(self, tmp_path):
        session = {
            "id": "dz-001",
            "domain": "game/doudizhu",
            "meta_hash": "abc123",
        }
        dec = TaskDecomposer()
        units = dec.decompose(session, tmp_path / "test.log")
        assert len(units) == 1
        assert units[0].description == "dz-001"
        assert units[0].domain.path == "game/doudizhu"

    def test_leduc_returns_single_unit(self, tmp_path):
        session = {
            "id": "le-001",
            "domain": "game/leduc",
            "meta_hash": "abc123",
        }
        dec = TaskDecomposer()
        units = dec.decompose(session, tmp_path / "test.log")
        assert len(units) == 1
        assert units[0].domain.path == "game/leduc"

    def test_unknown_domain_returns_single_unit(self, tmp_path):
        session = {
            "id": "unknown-001",
            "domain": "bogus/type",
            "meta_hash": "abc",
        }
        dec = TaskDecomposer()
        units = dec.decompose(session, tmp_path / "test.log")
        assert len(units) == 1

    def test_coding_session_single_unit_stub(self, tmp_path):
        raw_log = tmp_path / "test.log"
        raw_log.write_text("user: fix bug\nassistant: ok")
        session = {
            "id": "code-001",
            "domain": "coding/session",
            "meta_hash": "abc",
        }
        dec = TaskDecomposer()
        units = dec.decompose(session, raw_log)
        assert len(units) == 1

    def test_enable_learning_passed_through(self, tmp_path):
        session = {
            "id": "le-002",
            "domain": "game/leduc",
            "enable_learning": True,
        }
        dec = TaskDecomposer()
        units = dec.decompose(session, tmp_path / "test.log")
        assert units[0].enable_learning is True
