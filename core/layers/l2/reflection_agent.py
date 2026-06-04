# --- REFACTOR: LearningEnv ---
# Card-layer reflection. Recyclable: card scoring logic → LearningEnv threshold feature.
"""L2 ReflectionAgent — knowledge card issue attribution and repair."""
import json
import logging
from core.layers.base import ReflectionAgent, LayerAgent
from core.reflect_config import load_reflect_config

_reflect_cfg = load_reflect_config()


class L2ReflectionAgent(ReflectionAgent):
    """Handles knowledge card issues: confidence anomalies, outdated cards, missing domain knowledge."""

    def investigate(self, issues: list[dict], context: dict) -> dict:
        my_issues = []
        downstream_issues = []

        for issue in issues:
            error_type = issue.get("type", "")
            if error_type in ("card_confidence_low", "card_confidence_high",
                              "card_outdated", "card_missing", "card_wrong_domain"):
                my_issues.append(issue)
            elif error_type in ("skill_mismatch", "skill_missing"):
                downstream_issues.append(issue)
            else:
                my_issues.append(issue)

        self._log.debug("═══ L2 ReflectionAgent ═══")
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
            "actions": [f"L2 identified {len(my_issues)} card issues"],
        }

    def fix(self, my_issues: list[dict]) -> dict:
        fixes = 0
        details = []

        for issue in my_issues:
            error_type = issue.get("type", "")
            card_id = issue.get("card_id", "")

            if error_type in ("card_confidence_low", "card_outdated"):
                self._manager.apply_update("penalize_card", {"card_id": card_id})
                fixes += 1
                details.append(f"Penalized card: {card_id}")
            elif error_type == "card_confidence_high":
                self._manager.apply_update("boost_card", {"card_id": card_id})
                fixes += 1
                details.append(f"Boosted card: {card_id}")
            elif error_type == "card_missing":
                self._manager.apply_update("add_card", {
                    "domain": issue.get("domain", "general"),
                    "content": issue.get("suggested_content", ""),
                    "confidence": 0.5,
                })
                fixes += 1
                details.append(f"Added card for domain: {issue.get('domain', '')}")

        return {"fixes_applied": fixes, "details": details}


# ── Phase 2a: LLM-based Proposer + Verifier (config-driven) ──


class L2ReflectProposer(LayerAgent):
    """L2 Proposer — LLM analyzes L2 NOTIFY, proposes self-fixes."""

    def __init__(self, llm_client):
        super().__init__(llm_client, logging.getLogger("l2_reflect"))
        self._cfg = _reflect_cfg.l2["proposer"]

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


class L2ReflectVerifier(LayerAgent):
    """L2 Verifier — LLM validates proposals against existing cards."""

    def __init__(self, llm_client):
        super().__init__(llm_client, logging.getLogger("l2_reflect"))
        self._cfg = _reflect_cfg.l2["verifier"]

    def verify(self, proposals: list[dict], existing_cards: list[str]) -> dict:
        system = self._cfg["system_template"]
        user = self._cfg["user_template"].format(
            proposals=json.dumps(proposals, ensure_ascii=False, indent=2),
            existing_cards=json.dumps(existing_cards, ensure_ascii=False),
        )
        return self._call_llm(system, user, schema=self._cfg["schema"])
