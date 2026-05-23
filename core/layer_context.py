from __future__ import annotations
import logging
from core.task import Task, TaskResult, TaskContext

logger = logging.getLogger(__name__)


class LayerContext:
    """Bridge between layers and event loop. Each layer is transparent to the loop."""

    def __init__(self, meta, l1, l2, l3):
        self.meta = meta
        self.l1 = l1
        self.l2 = l2
        self.l3 = l3

    def build_context(self, task: Task) -> str:
        parts = []

        active_rules = self.l1.get_active_rules(task)
        if active_rules:
            parts.append(
                "[Behavioral Principles]\n" +
                "\n".join(f"- {r}" for r in active_rules)
            )

        active_cards = self.l2.get_active_cards(task.domain, task.context or "", top_k=5)
        if active_cards:
            parts.append(
                "[Relevant Knowledge]\n" +
                "\n".join(
                    f"- [{c.domain.path}] {c.content} "
                    f"(confidence:{c.confidence:.1f}, activation:{c.activation:.2f})"
                    for c in active_cards
                )
            )

        matching_skills = self.l3.match(task.domain)
        if matching_skills:
            parts.append(
                "[Available Skills]\n" +
                ", ".join(f"`{s.name}`" for s in matching_skills) +
                "\nUse `skill_view(name)` to load a skill's full instructions."
            )

        return "\n\n".join(parts) if parts else ""

    def filter_tool_calls(self, calls: list) -> list:
        return self.meta.filter_dangerous(calls)

    def on_tool_results(self, task, results):
        self.l2.update_from_tool_results(task, results)
        self.meta.track_progress(results)

    def check_completion(self, task, messages):
        return self.meta.check_completion(task, messages)

    def post_task(self, task: Task, messages: list) -> TaskResult:
        result = TaskResult()

        eval_ctx = TaskContext(
            task=task,
            consecutive_no_progress=self.meta._turn_state.get("consecutive_no_progress", 0),
            rounds=len(messages) // 2,
        )
        triggers = self.meta.evaluate_triggers(eval_ctx)
        if not triggers:
            return result

        for trigger in triggers:
            reflection = self.meta.run_reflection(trigger, task, messages)

            if reflection.knowledge_updates:
                self.l2.apply_updates(reflection.knowledge_updates, task.domain)
                result.new_knowledge_cards = len(reflection.knowledge_updates)

            existing_rules = self.l1.all_rules()
            for proposal in reflection.l1_proposals:
                approved, reason = self.meta.validate_l1_change(proposal, existing_rules)
                if approved:
                    self.l1.apply(proposal)
                    result.l1_changes.append(f"+{proposal.content[:50]}...")
                else:
                    self.l2.add_failed_proposal_record(proposal)
                    result.l1_rejections.append(reason)

            domain_cards = self.l2.get_domain_cards(task.domain)
            if self.l3.should_create_skill(task.domain, domain_cards):
                skill_meta = self.l3.propose_and_create(task.domain, domain_cards)
                if skill_meta:
                    result.new_skills.append(skill_meta.name)

        return result
