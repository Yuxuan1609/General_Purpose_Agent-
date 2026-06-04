"""L(0.5+1) ReflectionAgent — rule-level issue attribution and repair."""
from core.layers.base import ReflectionAgent


class L0_5_1ReflectionAgent(ReflectionAgent):
    """Handles rule-level issues: wrong rules, missing rules, contradiction."""

    def investigate(self, issues: list[dict], context: dict) -> dict:
        my_issues = []
        downstream_issues = []

        for issue in issues:
            error_type = issue.get("type", "")
            if error_type in ("rule_wrong", "rule_missing", "rule_contradiction",
                              "rule_outdated", "decision_error"):
                my_issues.append(issue)
            elif error_type in ("card_confidence_low", "card_confidence_high",
                                "card_missing", "card_outdated"):
                downstream_issues.append(issue)
            elif error_type in ("skill_mismatch", "skill_missing"):
                downstream_issues.append(issue)
            else:
                my_issues.append(issue)

        self._log.debug("═══ L1 ReflectionAgent ═══")
        for i, issue in enumerate(issues):
            self._log.debug("  [issue %d] type=%s",
                           i, issue.get("type", "?"))
        self._log.debug("  → my=%d downstream=%d",
                       len(my_issues), len(downstream_issues))
        for mi in my_issues:
            self._log.debug("    my: %s", mi.get("type", ""))
        for di in downstream_issues:
            self._log.debug("    downstream: %s", di.get("type", ""))
        return {
            "my_issues": my_issues,
            "downstream_issues": downstream_issues,
            "actions": [f"L1 identified {len(my_issues)} rule issues"],
        }

    def fix(self, my_issues: list[dict]) -> dict:
        fixes = 0
        details = []

        for issue in my_issues:
            error_type = issue.get("type", "")
            content = issue.get("suggested_content", "")

            if error_type in ("rule_missing", "rule_wrong", "decision_error"):
                self._manager.apply_update("add_rule", {"content": content})
                fixes += 1
                details.append(f"Added rule: {content[:80]}")
            elif error_type == "rule_outdated":
                self._manager.apply_update("modify_rule", {
                    "rule_id": issue.get("rule_id", ""),
                    "content": content,
                })
                fixes += 1
                details.append(f"Modified rule: {issue.get('rule_id', '')}")
            elif error_type == "rule_contradiction":
                self._manager.apply_update("remove_rule", {
                    "rule_id": issue.get("rule_id", ""),
                })
                fixes += 1
                details.append(f"Removed contradictory rule: {issue.get('rule_id', '')}")

        return {"fixes_applied": fixes, "details": details}
