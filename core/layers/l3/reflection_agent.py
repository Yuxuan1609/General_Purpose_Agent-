"""L3 ReflectionAgent — skill-level issue attribution and repair."""
import json
import logging
from core.layers.base import ReflectionAgent, LayerAgent
from core.reflect_config import load_reflect_config

_reflect_cfg = load_reflect_config()


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
            else:
                downstream_issues.append(issue)

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


# ── Phase 2a: LLM-based Proposer + Verifier (config-driven) ──


class L3ReflectProposer(LayerAgent):
    """L3 Proposer — LLM analyzes L3 NOTIFY, proposes self-fixes."""

    def __init__(self, llm_client):
        super().__init__(llm_client, logging.getLogger("l3_reflect"))
        self._cfg = _reflect_cfg.l3["proposer"]

    def propose(self, layer_notify: dict, refiner_reasoning: str,
                meta: str, dispatch_info: str = "无") -> dict:
        system = self._cfg["system_template"].format(
            criteria=self._cfg["criteria"],
        )
        user = self._cfg["user_template"].format(
            refiner_reasoning=refiner_reasoning,
            dispatch_info=dispatch_info,
            layer_notify=json.dumps(layer_notify, ensure_ascii=False, indent=2),
        )
        return self._call_llm(system, user, schema=self._cfg["schema"])


class L3ReflectVerifier(LayerAgent):
    """L3 Verifier — LLM validates proposals against existing skills."""

    def __init__(self, llm_client):
        super().__init__(llm_client, logging.getLogger("l3_reflect"))
        self._cfg = _reflect_cfg.l3["verifier"]

    def verify(self, proposals: list[dict], existing_skills: list[str]) -> dict:
        system = self._cfg["system_template"]
        user = self._cfg["user_template"].format(
            proposals=json.dumps(proposals, ensure_ascii=False, indent=2),
            existing_skills=json.dumps(existing_skills, ensure_ascii=False),
        )
        return self._call_llm(system, user, schema=self._cfg["schema"])
