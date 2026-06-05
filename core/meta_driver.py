from __future__ import annotations
import logging
from dataclasses import dataclass
from typing import Callable

logger = logging.getLogger(__name__)


@dataclass
class ValidationRule:
    id: str
    description: str
    check_fn: Callable


def _check_not_duplicate(proposal, existing) -> tuple[bool, str]:
    for r in existing:
        if proposal.content.strip() == getattr(r, 'content', str(r)).strip():
            return False, "新规则与已有规则完全重复"
    return True, ""


def _check_no_contradiction(proposal, existing) -> tuple[bool, str]:
    negations = ["不要", "禁止", "避免", "别"]
    for r in existing:
        rc = getattr(r, 'content', str(r))
        for neg in negations:
            if neg in proposal.content and proposal.content.replace(neg, "") in rc:
                return False, f"新规则可能与已有规则矛盾 (涉及'{neg}')"
    return True, ""


DEFAULT_VALIDATORS = [
    ValidationRule(id="not_duplicate", description="不重复", check_fn=_check_not_duplicate),
    ValidationRule(id="no_contradiction", description="不矛盾", check_fn=_check_no_contradiction),
]


class MetaDriver:
    """L0.5: Immutable meta-driver. Validation rules and safety checks."""

    def __init__(self, validation_rules: list[ValidationRule],
                 auxiliary_llm=None, max_rules: int = 20, max_rule_length: int = 100):
        self.validation_rules = validation_rules
        self.auxiliary_llm = auxiliary_llm
        self.max_rules = max_rules
        self.max_rule_length = max_rule_length
        self.dangerous_tool_patterns: list[str] = ["delete_all", "drop_table", "format", "rm -rf"]

    def validate_l1_change(self, proposal, existing_rules: list) -> tuple[bool, str]:
        for vr in self.validation_rules:
            approved, reason = vr.check_fn(proposal, existing_rules)
            if not approved:
                return False, f"[{vr.id}] {reason}"
        if len(existing_rules) >= self.max_rules:
            return False, f"规则总数已达上限 {self.max_rules} 条"
        if len(proposal.content) > self.max_rule_length:
            return False, f"规则长度 {len(proposal.content)} 超过上限 {self.max_rule_length}"
        return True, ""

    def filter_dangerous(self, tool_calls: list) -> list:
        return [tc for tc in tool_calls if not any(p in tc.function.name for p in self.dangerous_tool_patterns)]

    def check_completion(self, task, messages) -> str:
        if not messages:
            return "continue"
        last = messages[-1]
        if last.get("role") == "assistant" and not last.get("tool_calls"):
            return "done"
        return "continue"


class L1ProposalProxy:
    """Lightweight proxy that supports attribute access for L1Proposal-like objects."""
    def __init__(self, content: str, reason: str = "", domain: str = "general"):
        self.content = content
        self.reason = reason
        self.domain = domain
        self.rule_id = None
