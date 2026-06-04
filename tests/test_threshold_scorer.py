# REFACTOR: LearningEnv — tests old ThresholdScorer. Recyclable: threshold logic → LearningEnv reward signal.
import json
from pathlib import Path
from core.orchestrator.threshold_scorer import ThresholdScorer


def _write_record(path: Path, domain: str, token_count: int, session_id: str):
    record = {
        "session": {"id": session_id, "domain": domain},
        "observation": {
            "meta": "Game rules placeholder",
            "state": {"token_count": token_count},
        },
        "notify_layers": {},
    }
    path.write_text(json.dumps(record))


class TestThresholdScorer:
    @staticmethod
    def _make_pending(tmp_path):
        d = tmp_path / "pending"
        d.mkdir()
        return d

    def test_no_files_returns_zero(self, tmp_path):
        pending_dir = self._make_pending(tmp_path)
        scorer = ThresholdScorer(pending_dir)
        assert scorer.score("game/doudizhu") == 0.0

    def test_counts_tasks_by_domain(self, tmp_path):
        pending_dir = self._make_pending(tmp_path)
        _write_record(pending_dir / "s1_1.json", "game/doudizhu", 500, "s1")
        _write_record(pending_dir / "s1_2.json", "game/doudizhu", 500, "s1")
        _write_record(pending_dir / "s2_1.json", "game/leduc", 100, "s2")

        scorer = ThresholdScorer(pending_dir)
        score_dz = scorer.score("game/doudizhu")
        score_le = scorer.score("game/leduc")
        assert score_dz > score_le

    def test_respects_custom_weights(self, tmp_path):
        pending_dir = self._make_pending(tmp_path)
        _write_record(pending_dir / "s1_1.json", "game/doudizhu", 500, "s1")
        _write_record(pending_dir / "s1_2.json", "game/doudizhu", 500, "s1")

        scorer_default = ThresholdScorer(pending_dir)
        scorer_heavy = ThresholdScorer(pending_dir, task_count_weight=10.0)
        assert scorer_heavy.score("game/doudizhu") > scorer_default.score("game/doudizhu")

    def test_should_trigger(self, tmp_path):
        pending_dir = self._make_pending(tmp_path)
        for i in range(6):
            _write_record(pending_dir / f"s{i}.json", "game/doudizhu", 500, f"s{i}")

        scorer = ThresholdScorer(pending_dir, threshold=5.0)
        assert scorer.should_trigger("game/doudizhu") is True

    def test_below_threshold_no_trigger(self, tmp_path):
        pending_dir = self._make_pending(tmp_path)
        _write_record(pending_dir / "s1_1.json", "game/doudizhu", 500, "s1")

        scorer = ThresholdScorer(pending_dir, threshold=5.0)
        assert scorer.should_trigger("game/doudizhu") is False

    def test_domain_count(self, tmp_path):
        pending_dir = self._make_pending(tmp_path)
        _write_record(pending_dir / "s1_1.json", "game/doudizhu", 500, "s1")
        _write_record(pending_dir / "s2_1.json", "game/leduc", 100, "s2")
        _write_record(pending_dir / "s3_1.json", "game/doudizhu", 500, "s3")

        scorer = ThresholdScorer(pending_dir)
        assert scorer.domain_count("game/doudizhu") == 2
        assert scorer.domain_count("game/leduc") == 1
