from __future__ import annotations
import json
import logging
from typing import Any
from core.types import TaskObservation
from core.layers.base import LayerManager, LayerAgent, _indent
from core.layer_message import LayerMessage

logger = logging.getLogger("l0_5_1")

# Tools are mounted on L1Agent via LayerInjector.set_injector() (see chain_factory).
# L1 does NOT call tools directly — it delegates tool-requiring tasks to L2/L3.
# Consolidation tools are registered in ToolRegistry (core/tools/consolidation_tools.py).


class L1Agent(LayerAgent):
    """L1 LLM Agent — two-stage V-structure processing.

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
        stores = knowledge_stores or {}
        self._l2_store = stores.get("l2")
        self._l3_store = stores.get("l3")

    def _build_system_prompt(self, instruction: str, meta: str,
                              static_context: str = "") -> str:
        """Build system prompt: layer identity + instruction + meta + behavior rules."""
        rules = self._philosophy.all_rules()
        rules_text = "\n".join(f"- {r.content}" for r in rules) if rules else "（无）"
        extra = f"\n{static_context}\n" if static_context else ""
        tool_rules = (
            "## 工具调用规则\n"
            "- 所有工具都有 sync 参数。sync=true(默认)阻塞等结果，sync=false 返回 task_id\n"
            "- sync=false 的任务用 collect_tasks(task_ids) 收割结果\n"
            "- check_task(task_id) 可查单个任务状态\n"
            "- 同一轮内多个 sync=true 工具并行执行，互不阻塞\n"
            "- 长耗时任务（kb_fill_gap、terminal 跑 shell 脚本等）建议设 sync=false\n"
        )
        learning_guidance = (
            "## 学习记录\n"
            "如果本轮产生了值得固化的知识，调用 record_learning。判断标准:\n"
            "- 完成了复杂任务且用到了可复用策略\n"
            "- 发现 L2知识缺口或 L3技能缺口\n"
            "- 用户给出明确的正向/负向反馈\n"
            "只填 domain, learning_target, importance, reasoning。\n"
            "L2/L3的详细evidence会由后台自动补充。\n"
        )
        return (
            f"## 认知层架构\n"
            f"- L1（你）：管理行为准则，负责顶层任务拆解与最终决策。可调用 create_domain 创建新领域。不调用其他工具。\n"
            f"- L2：管理概率性知识卡片，负责相关知识检索与技能调度。可调用 terminal/web_search/read_file/grep/tool_proposal 等工具。\n"
            f"- L3：管理 SKILL.md 技能，负责标准化流程执行。可调用 terminal/web_search/read_file/grep/tool_proposal 等工具。\n\n"
            f"## 领域边界\n"
            f"你只管理 L1 行为准则（Philosophy Rules）。\n"
            f"不要修改 L2 的知识卡片或 L3 的技能。\n"
            f"需要工具调用（如 web_search、terminal、读文件等）的任务，通过 call_l2=true 下发给 L2/L3 执行。\n\n"
            f"## 指令\n{instruction}\n\n"
            f"{tool_rules}\n"
            f"{learning_guidance}\n"
            f"{meta}\n\n"
            f"【行为准则】\n{rules_text}\n\n"
            f"你必须遵守以上【行为准则】并基于行为准则进行思考。\n"
            f"{extra}"
        )

    def _build_user_context(self, state: dict) -> str:
        """Build user prompt body: current state + history (dynamic per-step).

        For learning tasks, include Execution Records here instead of system prompt.
        """
        current = state.get("current", "")
        history = state.get("history", "")
        is_learning = "l1_output_format" in state

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
            return f"[学习数据]\n{records_text}{fb_section}"
        return (
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
                lines.append(f"{i + 1}. {path}\n   {desc}")
            nodes_text = "\n".join(lines)

        static_context = f"[领域节点]\n{nodes_text}" if nodes_text else ""
        system = self._build_system_prompt(instruction, meta, static_context=static_context)

        user_parts = [self._build_user_context(state)]
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
            from core.tools.registry import ToolRegistry
            from core.tools.consolidation_tools import L1_CONSOLIDATION_TOOL_NAMES
            _allowed = {"kb_query", "ask_user"}
            base_tools = [t for t in (self._get_tools(layer) or [])
                          if t["function"]["name"] in _allowed]
            consol_schemas = ToolRegistry().get_definitions(L1_CONSOLIDATION_TOOL_NAMES)
            report_tool = self._schema_to_tool(
                "l1_report",
                "【特殊工具：向上汇报】必须使用！整理完成后调用此工具输出最终结果。禁止以文本方式直接回复。",
                {
                    "type": "object",
                    "properties": {
                        "done": {"type": "boolean", "const": True},
                        "result": {"type": "string", "description": "最终决策文本"},
                        "reasoning": {"type": "string"},
                    },
                    "required": ["done", "reasoning"],
                },
            )
            all_tools = base_tools + consol_schemas + [report_tool]
            self._log.debug("  tools: %s",
                           [t["function"]["name"] for t in all_tools])
            result = self._call_llm(system, user, tools=all_tools, layer=layer,
                                    capture_tools={"l1_report"})
            result = {
                "done": True,
                "result": result.get("result", result.get("reply", "")),
                "reasoning": result.get("reasoning", ""),
                "queries": [],
            }
            return result

        # Normal mode: two capture tools
        base_tools = self._get_tools(layer) or []
        query_tool = self._schema_to_tool(
            "l1_query",
            "【特殊工具：向下查询】当需要下层L2的策略知识辅助决策时使用。"
            "每次只提交一个问题，收到回复后再决定是否继续查询。禁止以文本方式直接回复！",
            {
                "type": "object",
                "properties": {
                    "done": {"type": "boolean", "const": False},
                    "queries": {
                        "type": "array",
                        "maxItems": 1,
                        "items": {
                            "type": "object",
                            "properties": {
                                "query": {"type": "string", "description": "向下层 L2 查询的问题"},
                                "domains_hint": {
                                    "type": "array", "items": {"type": "string"},
                                    "description": "建议查询的领域",
                                },
                            },
                        },
                    },
                    "reasoning": {"type": "string"},
                },
                "required": ["done", "queries", "reasoning"],
            },
        )
        report_tool = self._schema_to_tool(
            "l1_report",
            "【特殊工具：向上汇报】当你有了足够信息可以做出最终决策时使用。"
            "给出明确的决策结果和推理过程。禁止以文本方式直接回复！",
            {
                "type": "object",
                "properties": {
                    "done": {"type": "boolean", "const": True},
                    "result": {"type": "string", "description": "最终决策文本"},
                    "reasoning": {"type": "string"},
                },
                "required": ["done", "result", "reasoning"],
            },
        )
        all_tools = base_tools + [query_tool, report_tool]
        self._log.debug("  tools: %s", [t["function"]["name"] for t in all_tools])
        result = self._call_llm(system, user, tools=all_tools, layer=layer,
                                capture_tools={"l1_query", "l1_report"})
        return result


class L0_5_1Manager(LayerManager):
    """L(0.5+1) Manager — wraps MetaDriver + Philosophy + L1Agent.

    Overrides query() to drive V-structure loop:
      Stage1 → AgentPacket(QUERY) → L2 → Stage2 → done? NOTIFY : retry

    NOTIFY goes to both upper layer and Executor.
    TODO: Content may differ per target.
    """

    def __init__(self, meta_driver, philosophy, auxiliary_llm=None,
                 downstream: LayerManager | None = None,
                 upward=None, downward=None,
                 domain_registry=None, max_rounds=3,
                 knowledge_stores: dict | None = None):
        super().__init__("l0_5_1", downstream, upward=upward, downward=downward)
        self._meta = meta_driver
        self._philosophy = philosophy
        self._agent = L1Agent(auxiliary_llm, philosophy, domain_registry,
                              knowledge_stores=knowledge_stores) if auxiliary_llm else None
        self._registry = domain_registry
        self.max_rounds = max_rounds
        self._l1_notify: dict | None = None
        self._l2_history: list[dict] = []

    def process(self, data: Any) -> dict:
        return {"status": "ok", "layer": self.name}

    def query(self, msg: LayerMessage | Any, trace_id: str = "") -> None:
        if isinstance(msg, LayerMessage):
            data = self._upward.receive(msg)
            if not trace_id:
                trace_id = msg.trace_id
        else:
            data = msg

        obs: TaskObservation = data if isinstance(data, TaskObservation) else TaskObservation(**data)
        meta = obs.meta

        if self._agent is None:
            logger.warning("L1Agent not initialized (no auxiliary_llm), skipping")
            self._l1_notify = {"done": True, "result": "", "reasoning": "no agent"}
            return

        state = dict(obs.state or {})
        # Clear L2 history on new executor trace (no context_history in state means fresh input)
        if "context_history" not in state:
            self._l2_history.clear()
        history: list[dict] = []

        for round_idx in range(1, self.max_rounds + 1):
            logger.debug("── L1 decide [round %d/%d] ──", round_idx, self.max_rounds)

            if self._registry:
                state["domain_nodes"] = self._registry.list_all()

            tools = self._agent._get_tools("l1") if self._agent else None
            result = self._agent.decide(
                meta=meta, state=state, history=history,
                tools=tools, layer="l1",
            )
            logger.debug("  result: done=%s result=%s",
                         result.get("done"), str(result.get("result", ""))[:2000])

            if result.get("done"):
                self._l1_notify = {
                    "done": True,
                    "result": result.get("result", ""),
                    "reasoning": result.get("reasoning", ""),
                }
                # Build RoundTree node
                from core.round_tree import DecisionNode, get_round_history
                l1_node = DecisionNode(
                    layer="l0_5_1",
                    query=meta,
                    result=self._l1_notify.get("result", ""),
                    reasoning=self._l1_notify.get("reasoning", ""),
                )
                for h in self._l2_history:
                    l2_data = h.get("l2_reply", {})
                    l2_node = DecisionNode(
                        layer="l2",
                        query=str(h.get("query", "")),
                        result=str(l2_data.get("reply", "")),
                        reasoning=str(l2_data.get("reasoning", "")),
                    )
                    l3_children = l2_data.get("_l3_children", [])
                    for l3 in l3_children:
                        l2_node.children.append(DecisionNode(
                            layer="l3",
                            query=str(l3.get("task", "")),
                            result=str(l3.get("result", "")),
                        ))
                    l1_node.children.append(l2_node)
                get_round_history().push(l1_node)
                # Cascade consolidation to L2/L3
                if "l1_output_format" in state and self._downstream:
                    cascade_obs = TaskObservation(
                        meta=meta,
                        state={
                            **state,
                            "context_history": [],
                            "domains_hint": obs.session.get("domains_hint", [])
                                if obs.session else [],
                        },
                        session={
                            "domain": (obs.session.get("domains_hint", ["general"])[0]
                                       if obs.session else "general"),
                            "enable_learning": False,
                        },
                    )
                    self._downstream.query(cascade_obs, trace_id)
                    l2_notify = self._downstream.collect_notify()
                    mods = []
                    if isinstance(l2_notify, dict):
                        mods = l2_notify.get("l2_modifications", [])
                        l3_mods = l2_notify.get("l3_modifications", [])
                        self._l1_notify["l3_modifications"] = l3_mods
                    self._l1_notify["l2_modifications"] = mods
                return

            queries = result.get("queries", [])
            if not queries:
                self._l1_notify = {
                    "done": True,
                    "result": result.get("result", ""),
                    "reasoning": result.get("reasoning", ""),
                }
                return

            for q in queries:
                sub_state = {
                    **state,
                    "query_context": q,
                    "domains_hint": q.get("domains_hint", []),
                    "context_history": list(self._l2_history),
                }
                sub_obs = TaskObservation(meta=q["query"], state=sub_state)
                q_msg = self._downward.wrap_query(
                    payload=sub_obs,
                    source=self.name,
                    target=self._downstream.name,
                    trace_id=trace_id,
                )
                self._downstream.query(q_msg, trace_id)
                l2_notify = self._downstream.collect_notify()
                history.append({
                    "round": round_idx,
                    "query": q["query"],
                    "l2_reply": l2_notify,
                })
                state[f"l2_round_{round_idx}"] = l2_notify
                # Record L2 round into context history for next L2 call
                l2_reply_text = ""
                if isinstance(l2_notify, dict):
                    l2_part = l2_notify.get("l2", {})
                    if isinstance(l2_part, dict):
                        l2_reply_text = l2_part.get("reply", "")
                if not l2_reply_text:
                    l2_reply_text = str(l2_notify)
                self._l2_history.append({
                    "query": q["query"][:200],
                    "reply": l2_reply_text[:2000],
                })

        # Force terminate — inject accumulated L2 history so LLM has context
        logger.debug("── L1 force terminate (max_rounds=%d) ──", self.max_rounds)
        history_text = ""
        if history:
            lines = []
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
                lines.append(f"查询: {q_text}\nL2回复: {reply_text[:50000]}")
            history_text = "\n\n".join(lines)
        user_text = (
            f"鉴于已超过最大轮次，基于已有信息给出最终决策。\n\n"
            f"[已完成的查询与回复]\n{history_text}" if history_text
            else "鉴于已超过最大轮次，基于已有信息给出最终决策。"
        )
        force = self._agent._call_llm(
            system=self._agent._build_system_prompt("force_terminate", meta),
            user=user_text,
            layer="l1",
        )
        self._l1_notify = {"done": True, "result": str(force), "reasoning": "max_rounds"}

    def notify(self) -> Any:
        if self._l1_notify:
            result = dict(self._l1_notify)
            from core.tools.consolidation_tools import get_pending_mods
            mods = get_pending_mods()
            if mods:
                result["l1_modifications"] = mods
            return result
        return {"status": "ok", "layer": self.name}
