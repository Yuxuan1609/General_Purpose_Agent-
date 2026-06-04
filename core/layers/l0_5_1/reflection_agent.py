"""L(0.5+1) ReflectionAgent — rule-level issue attribution and repair."""
import json
import logging
from core.layers.base import ReflectionAgent, LayerAgent
from core.reflect_config import load_reflect_config

_reflect_cfg = load_reflect_config()


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


# ── Phase 2a: LLM-based Proposer + Verifier (config-driven) ──


class L1ReflectProposer(LayerAgent):
    """L1 Proposer — LLM analyzes L1 NOTIFY, proposes self-fixes.

    Input: layer_notify, refiner_reasoning, meta, dispatch_info
    Output: {self_fixes: [{action, content, reason}], dispatch_lower: null|dict}
    """

    def __init__(self, llm_client):
        super().__init__(llm_client, logging.getLogger("l0_5_1_reflect"))
        self._cfg = _reflect_cfg.l1["proposer"]

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


class L1ReflectVerifier(LayerAgent):
    """L1 Verifier — LLM validates proposals against existing rules."""

    def __init__(self, llm_client):
        super().__init__(llm_client, logging.getLogger("l0_5_1_reflect"))
        self._cfg = _reflect_cfg.l1["verifier"]

    def verify(self, proposals: list[dict], existing_rules: list[str]) -> dict:
        system = self._cfg["system_template"]
        user = self._cfg["user_template"].format(
            proposals=json.dumps(proposals, ensure_ascii=False, indent=2),
            existing_rules=json.dumps(existing_rules, ensure_ascii=False),
        )
        return self._call_llm(system, user, schema=self._cfg["schema"])
