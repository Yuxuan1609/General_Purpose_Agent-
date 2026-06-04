# --- REFACTOR: LearningEnv ---
# Old reflection orchestrator. Recyclable: record scanning → LearningEnv.get_state();
# archive logic → LearningEnv reward tracking.
"""Reflect Coordinator — orchestrates the reflection cycle across layers."""
import json
import logging
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)


class ReflectCoordinator:
    """Audit pending execution records and coordinate per-layer reflection.

    Flow:
      1. audit(domain) → scan pending/ records for issues by layer
      2. run_reflect(domain, root) → distribute issues to L1→L2→L3, collect fixes
      3. _archive(domain) → move fixed records to learned/{domain}/
    """

    def __init__(self, pending_dir: Path, learned_dir: Path):
        self._pending = pending_dir
        self._learned = learned_dir

    def audit(self, domain: str) -> dict:
        """Scan pending/ records for a domain, extract per-layer issues from NOTIFY."""
        records = self._domain_records(domain)
        issues_by_layer: dict[str, list[dict]] = {
            "l0_5_1": [],
            "l2": [],
            "l3": [],
        }

        for rec in records:
            notify = rec.get("notify_layers", {})
            action = rec.get("action")
            obs = rec.get("observation", {})

            # Extract issues from each layer's NOTIFY
            for layer_name in ["l0_5_1", "l2", "l3"]:
                layer_notify = notify.get(layer_name, {})
                if isinstance(layer_notify, dict):
                    layer_issues = layer_notify.get("issues", [])
                    if layer_issues:
                        issues_by_layer[layer_name].extend(layer_issues)

            # Heuristic: if action is None or empty, flag as potential issue
            if not action:
                issues_by_layer["l0_5_1"].append({
                    "type": "decision_error",
                    "message": "No action taken",
                    "context": {"domain": domain},
                })

        return issues_by_layer

    def run_reflect(self, domain: str, layer_root, reflection_root) -> dict:
        """Full reflection cycle: audit → distribute → collect fixes.

        Args:
            domain: target domain for reflection
            layer_root: root LayerManager (L0_5_1) for data access
            reflection_root: root ReflectionAgent (L0_5_1) for issue distribution

        Returns:
            {"domain": str, "audit_results": dict, "fixes": dict}
        """
        issues = self.audit(domain)

        if not any(issues.values()):
            logger.info("No issues found for domain=%s, skipping reflect", domain)
            return {"domain": domain, "audit_results": issues, "fixes": {}}

        context = {"domain": domain}
        all_fixes = {}

        # Distribute issues top-down via reflection chain
        if issues.get("l0_5_1"):
            result = reflection_root.investigate(issues["l0_5_1"], context)
            my_issues = result.get("my_issues", [])
            if my_issues:
                fix_result = reflection_root.fix(my_issues)
                all_fixes["l0_5_1"] = fix_result

            downstream = result.get("downstream_issues", [])
            if downstream:
                reflection_root.query_downstream(downstream, context)
                # Downstream fixes collected via NOTIFY chain (handled by per-layer agents)

        for layer_name, layer_issues in issues.items():
            if layer_name != "l0_5_1" and layer_issues:
                all_fixes[layer_name] = {
                    "status": "issues_flagged",
                    "count": len(layer_issues),
                }

        self._archive(domain)
        return {"domain": domain, "audit_results": issues, "fixes": all_fixes}

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

    def _archive(self, domain: str) -> None:
        target = self._learned / domain
        target.mkdir(parents=True, exist_ok=True)

        for f in self._pending.glob("*.json"):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                rec_domain = data.get("session", {}).get("domain", "")
                if rec_domain == domain or rec_domain.startswith(domain + "/"):
                    shutil.move(str(f), str(target / f.name))
                    logger.info("Archived %s → %s", f.name, target)
            except (json.JSONDecodeError, OSError) as e:
                logger.warning("Failed to archive %s: %s", f.name, e)
