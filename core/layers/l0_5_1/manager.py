from __future__ import annotations
import json
import logging
from typing import Any
from core.types import TaskObservation
from core.layers.base import LayerManager, LayerAgent, _indent
from core.layer_message import LayerMessage

logger = logging.getLogger("l0_5_1")

from core.layers.base import CaptureToolDef, ConsolidationStrategy

L1_REPORT_TOOL = CaptureToolDef(
    name="l1_report",
    description="【特殊工具：向上汇报】当你有了足够信息可以做出最终决策时使用。"
    "给出明确的决策结果和推理过程。禁止以文本方式直接回复！",
    done=True,
    schema={
        "type": "object",
        "properties": {
            "done": {"type": "boolean", "const": True},
            "result": {"type": "string", "description": "最终决策文本"},
            "reasoning": {"type": "string"},
        },
        "required": ["done", "result", "reasoning"],
    },
)


from core.tools.consolidation_tools import L1_CONSOLIDATION_TOOL_NAMES
L1_CONSOLIDATION_STRATEGY = ConsolidationStrategy(
    consolidation_tool_names=L1_CONSOLIDATION_TOOL_NAMES,
    allowed_base_tools={"kb_query", "ask_user", "l1_query"},
    report_tool=L1_REPORT_TOOL,
)


class L1Agent(LayerAgent):
    """L1 LLM Agent — while-loop decide processing.

    System prompt carries the task goal + game rules + behavior rules.
    User prompt carries the current situation + history (dynamic per-step).
    Output uses DeepSeek JSON mode with predefined schemas.

    Task goal is provided by the communication script via the meta field
    (not hardcoded here).
    """

    MAX_LOOPS = 1

    def __init__(self, llm_client, philosophy, domain_registry=None,
                 knowledge_stores: dict | None = None):
        super().__init__(llm_client, logger)
        self._philosophy = philosophy
        self._registry = domain_registry

    def _build_system_prompt(self, instruction: str, meta: str,
                              static_context: str = "") -> str:
        """Build system prompt: layer identity + behavior rules + tool guidance."""
        rules = self._philosophy.all_rules()
        rules_text = "\n".join(
            f"- [{r.id}] {r.content}" for r in rules
        ) if rules else "（无）"
        extra = f"\n{static_context}\n" if static_context else ""
        from core.layers.base import _TOOL_RULES
        tool_rules = _TOOL_RULES
        learning_guidance = (
            "## 学习记录\n"
            "如果本轮产生了值得固化的知识，调用 record_learning。判断标准:\n"
            "- 完成了复杂任务且用到了可复用策略\n"
            "- 发现 L2知识缺口或 L3技能缺口\n"
            "- 用户给出明确的正向/负向反馈\n"
            "只填 domain, learning_target, importance, reasoning。\n"
            "L2/L3的详细evidence会由后台自动补充。\n"
            "注意：如果之前已提交过内容相似的 learning_target，不要重复调用 record_learning。\n"
        )
        l1_query_guide = (
            "## l1_query 工具用法\n"
            "l1_query 是向 L2 层发起查询的工具。使用场景：\n"
            "- 需要 L2 检索相关知识卡片来辅助决策\n"
            "- 需要 L2 调用终端/write/search 等工具执行具体操作\n"
            "- 不确定某些事实或信息，需要 L2 补充\n"
            "每次 l1_query 提交一个问题，L2 会回复结果。收到回复后：\n"
            "- 如果还需要 L2 协助 → 再发一次 l1_query\n"
            "- 如果已掌握足够信息 → 调用 l1_report 汇报最终结果\n"
            "禁止在未调用 l1_query 咨询 L2 的情况下直接 l1_report（除非任务无需下层协助）。\n"
        )
        return (
            f"## 认知层架构\n"
            f"- L1（你）：管理行为准则，负责顶层任务拆解与最终决策。可调用 create_domain 创建新领域。\n"
            f"- L2：管理概率性知识卡片，负责相关知识检索与技能调度。可调用 terminal/web_search/read_file/grep/tool_proposal 等工具。\n"
            f"- L3：管理 SKILL.md 技能，负责标准化流程执行。可调用 terminal/web_search/read_file/grep/tool_proposal 等工具。\n\n"
            f"## 领域边界\n"
            f"你只管理 L1 行为准则（Philosophy Rules）。\n"
            f"不要修改 L2 的知识卡片或 L3 的技能。\n"
            f"你只实际执行相对简单的任务。对于需要多步骤操作的复杂任务，"
            f"你进行拆解并通过 l1_query 逐个部分下发。\n"
            f"需要工具调用（如 web_search、terminal、读文件等）的任务，通过 l1_query 下发给 L2/L3 执行。\n\n"
            f"{l1_query_guide}\n"
            f"{tool_rules}\n"
            f"{learning_guidance}\n"
            f"【行为准则】\n{rules_text}\n\n"
            f"你必须遵守以上【行为准则】并基于行为准则进行思考。\n"
            f"{extra}"
        )

    def _build_user_context(self, state: dict, meta: str = "") -> str:
        """Build user prompt body: task input (meta) + current state + history.

        For learning tasks, include Execution Records here instead of system prompt.
        """
        current = state.get("current", "")
        history = state.get("history", "")
        is_learning = "l1_output_format" in state

        task_section = f"[任务]\n{meta}\n\n" if meta else ""

        if is_learning:
            units = state.get("learning_units", [])
            recs = []
            if isinstance(units, list):
                for u in units:
                    idx = u.get("index", "?")
                    l1_r = u.get("l1_reasoning", "")
                    action = u.get("action", "")
                    line = f"[{idx}] action={action} | L1: {l1_r[:200]}" if l1_r else f"[{idx}] action={action}"
                    recs.append(line)
            records_text = "\n".join(recs) if recs else "（无）"
            feedback = state.get("feedback", "")
            l1_fb = state.get("l1_feedback", "")
            fb_text = feedback
            if l1_fb:
                fb_text = f"{feedback}\n{l1_fb}" if feedback else l1_fb
            fb_section = f"\n\n[L1 修改结果确认]\n{fb_text}" if fb_text else ""
            return f"{task_section}[学习数据]\n{records_text}{fb_section}"
        return (
            f"{task_section}"
            f"[当前局面]\n{current}\n\n"
            f"[对局历史]\n{history or '（无）'}"
        )

    def decide(self, meta: str, state: dict, history: list,
               tools: list[dict] | None = None, layer: str = "l1") -> dict:
        """Single decision step for L1 while loop.

        Two capture tools:
          - l1_query: request knowledge from L2 (done=false, queries=[...])
          - l1_report: deliver final decision (done=true, result=...)
        Consolidation mode uses l1_report only.
        """
        l1_fmt = state.get("l1_output_format")

        instruction = (
            "你的职责：基于【行为准则】将任务拆解为下层需要协助的具体子任务。\n"
            "拆解时思考：已有信息能完成什么、还差什么子任务或信息、所需材料是否可以由下层提供。\n\n"
            "*** 输出规则（极其重要）***\n"
            "1. 如果你需要 L2 层的策略知识才能做出决策 → 调用【l1_query】工具下发查询\n"
            "2. 如果你已经掌握了足够信息，可以独立做出最终决策 → 调用【l1_report】工具汇报结果\n"
            "3. 禁止以文本方式直接输出JSON或回复，必须调用以上两个工具之一！\n\n"
            "l1_query：向下查询，done固定为false。每次只能提交一个问题，收到L2回复后如仍需补充再发起下一次查询。\n"
            "l1_report：向上汇报，done固定为true，给出最终决策和理由\n"
        )
        if l1_fmt:
            instruction += (
                "\n\n【整理任务】你只负责 L1 行为准则的修改。"
                "使用整理工具记录修改，完成后调用 l1_report 输出结果。"
                "\n要求：先调用 l1_query 向 L2 下发整理需求（如审查卡片过期/重复、技能冗余等），"
                "收到 L2 回复后汇总 L1+L2 结果输出。禁止在未查询 L2 的情况下直接 report。"
            )
        else:
            instruction += (
                "\n如果任务无需下层协助，直接调用 l1_report。"
            )

        domain_nodes = state.get("domain_nodes", [])
        nodes_text = ""
        if domain_nodes:
            lines = []
            for i, n in enumerate(domain_nodes):
                path = n.path if hasattr(n, 'path') else n.get('name', '?')
                desc = n.description if hasattr(n, 'description') else n.get('description', '')
                rel = getattr(n, 'relations', '')
                line = f"{i + 1}. {path}"
                if desc:
                    line += f"\n   {desc}"
                if rel:
                    line += f"\n   关联: {rel}"
                lines.append(line)
            nodes_text = "\n".join(lines)

        static_context = f"[领域节点]\n{nodes_text}" if nodes_text else ""
        system = self._build_system_prompt(instruction, meta, static_context=static_context)

        user_parts = [self._build_user_context(state, meta=meta)]
        if history:
            history_lines = []
            for h in history:
                q_text = h.get("query", "")
                l2_reply = h.get("l2_reply", {})
                reply_text = ""
                if isinstance(l2_reply, dict):
                    l1_part = l2_reply.get("l0_5_1", {})
                    if isinstance(l1_part, dict):
                        reply_text = l1_part.get("reply", "")
                if not reply_text:
                    reply_text = str(l2_reply)
                history_lines.append(f"  Round {h.get('round', '?')}: query='{q_text}' → L2: {reply_text[:50000]}")
            if history_lines:
                user_parts.append("[L2 历史返回]\n" + "\n".join(history_lines))
        user = "\n\n".join(user_parts)

        if l1_fmt:
            all_tools, capture_set = L1_CONSOLIDATION_STRATEGY.build_tools(self, layer)
            self._log.debug("  tools: %s",
                           [t["function"]["name"] for t in all_tools])
            result = self._call_llm(system, user, tools=all_tools, layer=layer,
                                    capture_tools=capture_set)
            return {
                "done": True,
                "result": result.get("result", result.get("reply", "")),
                "reasoning": result.get("reasoning", ""),
                "queries": [],
            }

        # Normal mode: single capture tool (l1_query is now a regular tool)
        base_tools = self._get_tools(layer) or []
        all_tools = base_tools + [L1_REPORT_TOOL.to_openai_tool()]
        self._log.debug("  tools: %s", [t["function"]["name"] for t in all_tools])
        result = self._call_llm(system, user, tools=all_tools, layer=layer,
                                capture_tools={"l1_report"})
        if not result.get("done"):
            raw = result.get("_raw") or result.get("result") or result.get("reply") or ""
            if raw:
                return {"done": True, "result": str(raw), "reasoning": "direct reply", "queries": []}
        return result


class L0_5_1Manager(LayerManager):
    """L(0.5+1) Manager — wraps Philosophy + L1Agent.

    Single decide() call. L1 queries L2 via l1_query tool (in _call_llm tool loop).
    RoundTree built via thread-local node stack bound to decide.
    """

    def __init__(self, philosophy, auxiliary_llm=None,
                 downstream: LayerManager | None = None,
                 upward=None, downward=None,
                 domain_registry=None,
                 knowledge_stores: dict | None = None):
        super().__init__("l0_5_1", downstream, upward=upward, downward=downward)
        self._philosophy = philosophy
        self._agent = L1Agent(auxiliary_llm, philosophy, domain_registry,
                               knowledge_stores=knowledge_stores) if auxiliary_llm else None
        self._registry = domain_registry
        self._l1_notify: dict | None = None

    def process(self, data: Any) -> dict:
        return {"status": "ok", "layer": self.name}

    def query(self, msg: LayerMessage | Any, trace_id: str = "") -> None:
        obs, trace_id = self._unwrap_obs(msg, upward=self._upward, trace_id=trace_id)
        meta = obs.meta

        if self._agent is None:
            logger.warning("L1Agent not initialized (no auxiliary_llm), skipping")
            self._l1_notify = {"done": False, "reasoning": "no agent"}
            return

        state = dict(obs.state or {})
        if self._registry:
            state["domain_nodes"] = self._registry.list_all()

        from core.round_tree import DecisionNode, get_round_history, push_node, pop_node
        l1_node = DecisionNode(layer="l0_5_1", query=meta, result="", reasoning="")
        push_node(l1_node)

        logger.debug("── L1 decide ──")
        tools = self._agent._get_tools("l1") if self._agent else None
        result = self._agent.decide(
            meta=meta, state=state, history=[],
            tools=tools, layer="l1",
        )
        logger.debug("  result: done=%s result=%s",
                     result.get("done"), str(result.get("result", ""))[:2000])

        l1_node.result = result.get("result", "")
        l1_node.reasoning = result.get("reasoning", "")
        pop_node()
        get_round_history().push(l1_node)

        if self._registry:
            self._registry.flush_correlations()

        self._l1_notify = {
            "done": True,
            "result": result.get("result", ""),
            "reasoning": result.get("reasoning", ""),
        }

    def notify(self) -> Any:
        if self._l1_notify:
            return dict(self._l1_notify)
        return {"status": "ok", "layer": self.name}
