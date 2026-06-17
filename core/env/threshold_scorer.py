"""Threshold scorer — domain-grouped evaluation of pending learning records."""
import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class ThresholdScorer:
    """Score pending learning records by domain to trigger reflection."""

    def __init__(self, pending_dir: Path,
                 task_count_weight: float | None = None,
                 complexity_weight: float | None = None,
                 baseline_tokens: int | None = None,
                 threshold: float | None = None):
        self._pending = pending_dir
        from core.config_loader import get_section
        learn_cfg = get_section('learning', default={})
        self._count_weight = task_count_weight if task_count_weight is not None else learn_cfg.get('trigger_count_weight', 1.0)
        self._complex_weight = complexity_weight if complexity_weight is not None else learn_cfg.get('trigger_complexity_weight', 1.0)
        self._baseline = baseline_tokens if baseline_tokens is not None else learn_cfg.get('trigger_baseline_tokens', 2000)
        self.threshold = threshold if threshold is not None else learn_cfg.get('trigger_threshold', 5.0)

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

    def domain_health_report(self, registry, l2_store, l3_store) -> str:
        """Build a domain health report for consolidation task meta."""
        lines = ["### Domain Health Report", ""]
        lines.append("| domain | L2 cards | L3 skills | correlations | status |")
        lines.append("|--------|----------|-----------|-------------|--------|")
        for node in registry.list_all():
            path = node.path
            l2_count = len(registry.get_primary_items("l2", path))
            l3_count = len(registry.get_primary_items("l3", path))
            corr_items = sorted(node.correlations.items())
            corr_str = ", ".join(f"{k}={v:.2f}" for k, v in corr_items[:3])
            if len(corr_items) > 3:
                corr_str += ", ..."
            status = []
            if l2_count >= 25:
                status.append("L2_OVER_LIMIT")
            if l3_count >= 20:
                status.append("L3_OVER_LIMIT")
            if not status:
                status.append("OK")
            lines.append(f"| {path} | {l2_count} | {l3_count} | {corr_str} | {', '.join(status)} |")
        return "\n".join(lines)

    @staticmethod
    def _extract_tokens(record: dict) -> int:
        return record.get("observation", {}).get("state", {}).get("token_count", 0)
