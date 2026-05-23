from __future__ import annotations
import json
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

logger = logging.getLogger(__name__)


class TriggerType(Enum):
    RULE = "rule"
    LLM = "llm"


@dataclass
class ReflectionTrigger:
    id: str
    trigger_type: TriggerType
    condition_desc: str
    rule_check: Callable | None = None
    llm_prompt: str | None = None
    cooldown_rounds: int = 1
    last_triggered_at: int = -999

    def evaluate(self, ctx) -> bool:
        if ctx.rounds - self.last_triggered_at < self.cooldown_rounds:
            return False
        if self.trigger_type == TriggerType.RULE and self.rule_check:
            result = self.rule_check(ctx)
            if result:
                self.last_triggered_at = ctx.rounds
            return result
        return False

    def evaluate_with_llm(self, ctx, llm_client) -> bool:
        if ctx.rounds - self.last_triggered_at < self.cooldown_rounds:
            return False
        if self.trigger_type != TriggerType.LLM or not self.llm_prompt:
            return False
        prompt = self.llm_prompt.format(
            task_description=ctx.task.description,
            domain=ctx.task.domain.path,
            execution_summary="(summary unavailable)",
            new_domain=ctx.task.domain.path,
            previous_domains="",
            l2_domains="",
        )
        try:
            resp = llm_client.chat(messages=[{"role": "user", "content": prompt}])
            data = json.loads(resp.text)
            if data.get("completed") or data.get("is_new_domain"):
                self.last_triggered_at = ctx.rounds
                return True
            return False
        except Exception as e:
            logger.debug("LLM trigger %s failed: %s", self.id, e)
            return False


@dataclass
class ValidationRule:
    id: str
    description: str
    check_fn: Callable


def _check_stagnation(ctx) -> bool:
    return ctx.consecutive_no_progress >= 3


def _check_task_failure(ctx) -> bool:
    return ctx.eval_result == "failure"


TASK_COMPLETED_LLM_PROMPT = (
    "Review the following task execution:\n"
    "Task: {task_description}\nDomain: {domain}\nExecution: {execution_summary}\n\n"
    'Respond in JSON:\n'
    '{{"completed": true/false, "efficient": true/false, '
    '"knowledge_to_create": [{{"content": "...", "confidence": 0.0-1.0}}], '
    '"l1_proposals": [{{"content": "...", "reason": "..."}}]}}'
)

DOMAIN_SHIFT_LLM_PROMPT = (
    "Agent entered new domain: '{new_domain}'. Previous: {previous_domains}. "
    "L2 covers: {l2_domains}. "
    "Respond in JSON: {{'is_new_domain': true/false, "
    "'adjacent_domains': [], 'recommended_general_cards': []}}"
)

DEFAULT_TRIGGERS = [
    ReflectionTrigger(id="stagnation", trigger_type=TriggerType.RULE,
                       condition_desc="连续3轮无实质进展",
                       rule_check=_check_stagnation, cooldown_rounds=5),
    ReflectionTrigger(id="task_failed", trigger_type=TriggerType.RULE,
                       condition_desc="明确判定任务失败",
                       rule_check=_check_task_failure, cooldown_rounds=1),
    ReflectionTrigger(id="task_completed", trigger_type=TriggerType.LLM,
                       condition_desc="任务完成确认并提取经验",
                       llm_prompt=TASK_COMPLETED_LLM_PROMPT, cooldown_rounds=3),
    ReflectionTrigger(id="domain_shift", trigger_type=TriggerType.LLM,
                       condition_desc="进入新领域需跨域知识迁移",
                       llm_prompt=DOMAIN_SHIFT_LLM_PROMPT, cooldown_rounds=10),
]


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


@dataclass
class ReflectionResult:
    knowledge_updates: list[dict] = field(default_factory=list)
    l1_proposals: list = field(default_factory=list)


class MetaDriver:
    """L0.5: Immutable meta-driver. Hardcoded triggers and validators."""

    def __init__(self, triggers: list[ReflectionTrigger],
                 validation_rules: list[ValidationRule],
                 auxiliary_llm=None, max_rules: int = 20, max_rule_length: int = 100):
        self.triggers = triggers
        self.validation_rules = validation_rules
        self.auxiliary_llm = auxiliary_llm
        self.max_rules = max_rules
        self.max_rule_length = max_rule_length
        self.dangerous_tool_patterns: list[str] = ["delete_all", "drop_table", "format", "rm -rf"]
        self._turn_state = {"consecutive_no_progress": 0}

    def reset_turn_state(self):
        self._turn_state = {"consecutive_no_progress": 0}

    def track_progress(self, results: list):
        has_progress = any("error" not in str(r).lower() for _, r in results)
        self._turn_state["consecutive_no_progress"] = 0 if has_progress else self._turn_state["consecutive_no_progress"] + 1

    def evaluate_triggers(self, ctx) -> list[ReflectionTrigger]:
        fired = []
        for trigger in self.triggers:
            if trigger.trigger_type == TriggerType.RULE:
                if trigger.evaluate(ctx):
                    fired.append(trigger)
            elif trigger.trigger_type == TriggerType.LLM and self.auxiliary_llm:
                if trigger.evaluate_with_llm(ctx, self.auxiliary_llm):
                    fired.append(trigger)
        return fired

    def run_reflection(self, trigger, task, messages) -> ReflectionResult:
        if trigger.trigger_type == TriggerType.LLM and self.auxiliary_llm:
            return self._llm_reflection(trigger, task, messages)
        return ReflectionResult()

    def _llm_reflection(self, trigger, task, messages) -> ReflectionResult:
        prompt = trigger.llm_prompt.format(
            task_description=task.description, domain=task.domain.path,
            execution_summary=self._summarize_messages(messages),
            new_domain=task.domain.path, previous_domains="", l2_domains="",
        )
        try:
            resp = self.auxiliary_llm.chat(messages=[{"role": "user", "content": prompt}])
            data = json.loads(resp.text)
            result = ReflectionResult()
            for item in data.get("knowledge_to_create", []):
                result.knowledge_updates.append({
                    "content": item["content"],
                    "confidence": item.get("confidence", 0.7),
                    "source": "reflection",
                })
            for item in data.get("l1_proposals", []):
                result.l1_proposals.append(L1ProposalProxy(
                    content=item["content"],
                    reason=item.get("reason", ""),
                    domain=task.domain.path,
                ))
            return result
        except Exception as e:
            logger.warning("Reflection failed for %s: %s", trigger.id, e)
            return ReflectionResult()

    def _summarize_messages(self, messages: list) -> str:
        lines = []
        for m in messages[-10:]:
            role = m.get("role", "?")
            content = str(m.get("content", ""))[:200]
            lines.append(f"[{role}] {content}")
        return "\n".join(lines)

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

    def task_decompose_trigger(self, task) -> list:
        return []


class L1ProposalProxy:
    """Lightweight proxy that supports attribute access for L1Proposal-like objects."""
    def __init__(self, content: str, reason: str = "", domain: str = "general"):
        self.content = content
        self.reason = reason
        self.domain = domain
        self.rule_id = None
