"""Learning Refiner — LLM agent that selects which steps to learn from.

After a Session ends and TaskDecomposer creates LearningUnits, this agent
reviews each LearningUnit's ExecutionRecords and identifies which steps
are worth learning based on the meta-level goal.

Future: The "worth learning" judgment criteria itself can become learnable.
"""
import json
import logging
from core.layers.base import LayerAgent

logger = logging.getLogger(__name__)


class LearningRefiner(LayerAgent):
    """LLM agent that marks ExecutionRecords as worth_learning based on meta goal.

    Input: meta (game rules/goal) + list of step summaries
    Output: {"worth_learning": [record_index, ...], "reasoning": "..."}
    """

    SCHEMA = {
        "worth_learning": ["int (execution record indices worth learning from)"],
        "reasoning": "string (why these steps are selected)",
    }

    SYSTEM = (
        "你是学习精炼 Agent。你的任务是根据任务目标，判断哪些执行步骤对达成目标有贡献，"
        "值得从中学习。\n\n"
        "判断标准：\n"
        "- 该步骤的动作是否合理，是否推动了目标的达成\n"
        "- 该步骤的决策是否体现了有效的知识应用\n"
        "- 该步骤的结果（成功/失败）是否反映了某层知识的质量\n\n"
        "输出所有你认为值得学习的步骤索引（整数数组）。"
    )

    def __init__(self, llm_client):
        super().__init__(llm_client, logger)

    def refine(self, meta: str, records: list[dict]) -> dict:
        """Select which records to learn from.

        Args:
            meta: Task goal / game rules
            records: list of ExecutionRecord dicts with keys:
                     {action, notify_layers}

        Returns:
            {"worth_learning": [int, ...], "reasoning": "..."}
        """
        steps_text = self._format_steps(records)
        user = (
            f"[任务目标]\n{meta}\n\n"
            f"[执行步骤]\n{steps_text}\n\n"
            f"请输出值得从中学习的步骤索引。"
        )
        return self._call_llm(self.SYSTEM, user, schema=self.SCHEMA)

    def _format_steps(self, records: list[dict]) -> str:
        parts = []
        for i, rec in enumerate(records):
            action = rec.get("action", "")
            notify = rec.get("notify_layers", {})
            l1 = notify.get("l0_5_1", {})
            l2 = notify.get("l2", {})
            parts.append(
                f"Step {i}:\n"
                f"  action: {action}\n"
                f"  L1_result: {l1.get('result', '')}\n"
                f"  L1_reasoning: {l1.get('reasoning', '')[:200]}\n"
                f"  L2_reply: {l2.get('reply', '')[:200]}\n"
            )
        return "\n\n".join(parts)
