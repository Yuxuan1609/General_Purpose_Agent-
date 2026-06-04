"""L3 ReflectionAgent — skill-level issue attribution and repair."""
from core.layers.base import ReflectionAgent


class L3ReflectionAgent(ReflectionAgent):
    """Handles skill-level issues: skill matching errors, missing skills, out-of-date content."""

    def investigate(self, issues: list[dict], context: dict) -> dict:
        my_issues = []
        downstream_issues = []

        for issue in issues:
            error_type = issue.get("type", "")
            if error_type in ("skill_mismatch", "skill_missing", "skill_outdated",
                              "skill_wrong_output", "skill_underutilized"):
                my_issues.append(issue)

        self._log.debug("═══ L3 ReflectionAgent ═══")
        self._log.debug("  investigate:\n"
                        "    issues: %d → my=%d downstream=%d\n"
                        "    my: %s\n"
                        "    downstream: %s",
                       len(issues), len(my_issues), len(downstream_issues),
                       [i.get("type") for i in my_issues],
                       [i.get("type") for i in downstream_issues])
        return {
            "my_issues": my_issues,
            "downstream_issues": downstream_issues,
            "actions": [f"L3 identified {len(my_issues)} skill issues"],
        }

    def fix(self, my_issues: list[dict]) -> dict:
        fixes = 0
        details = []

        for issue in my_issues:
            error_type = issue.get("type", "")
            skill_name = issue.get("skill_name", "")

            if error_type == "skill_missing":
                self._manager.apply_update("update_skill", {
                    "name": skill_name,
                    "content": issue.get("suggested_content", ""),
                })
                fixes += 1
                details.append(f"Created skill: {skill_name}")
            elif error_type in ("skill_mismatch", "skill_outdated", "skill_wrong_output",
                                "skill_underutilized"):
                self._manager.apply_update("update_skill", {
                    "name": skill_name,
                    "content": issue.get("suggested_content", ""),
                })
                fixes += 1
                details.append(f"Updated skill: {skill_name}")

        return {"fixes_applied": fixes, "details": details}
