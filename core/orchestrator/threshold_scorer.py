# --- REFACTOR: LearningEnv ---
# Old threshold-based trigger. Recyclable: threshold logic → LearningEnv reward signal.
"""Threshold scorer — domain-grouped evaluation of pending learning records."""
import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class ThresholdScorer:
    """Score pending learning records by domain to trigger reflection."""

    def __init__(self, pending_dir: Path, task_count_weight: float = 1.0,
                 complexity_weight: float = 1.0, baseline_tokens: int = 2000,
                 threshold: float = 5.0):
        self._pending = pending_dir
        self._count_weight = task_count_weight
        self._complex_weight = complexity_weight
        self._baseline = baseline_tokens
        self.threshold = threshold

    def score(self, domain: str) -> float:
        records = self._domain_records(domain)
        if not records:
            return 0.0
        count = len(records)
        total_tokens = sum(self._extract_tokens(r) for r in records)
        return (self._count_weight * count +
                self._complex_weight * total_tokens / self._baseline)

    def should_trigger(self, domain: str) -> bool:
        return self.score(domain) >= self.threshold

    def domain_count(self, domain: str) -> int:
        return len(self._domain_records(domain))

    def _domain_records(self, domain: str) -> list[dict]:
        if not self._pending.exists():
            return []
        records = []
        for f in self._pending.glob("*.json"):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                rec_domain = data.get("session", {}).get("domain", "")
                if rec_domain == domain or rec_domain.startswith(domain + "/"):
                    records.append(data)
            except (json.JSONDecodeError, OSError):
                logger.warning("Failed to read pending record: %s", f)
        return records

    @staticmethod
    def _extract_tokens(record: dict) -> int:
        return record.get("observation", {}).get("state", {}).get("token_count", 0)
