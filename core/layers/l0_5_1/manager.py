from __future__ import annotations
import json
import logging
from typing import Any
from core.types import TaskObservation
from core.layers.base import LayerManager, LayerAgent, _indent, DictInjector
from core.layer_message import LayerMessage

logger = logging.getLogger("l0_5_1")

# TODO: Future tool-use integration — load ToolRegistry into L1Agent and inject
#       tool definitions into stage prompts. Current Leduc/DouZero game context
#       does not require tool calls; reserved for general task scenarios.
#       See: core/tools/registry.py (ToolRegistry), core/llm_client.py (LLMClient.chat tools param)


class L1Agent(LayerAgent):
    """L1 LLM Agent — two-stage V-structure processing.

    System prompt carries the task goal + game rules + behavior rules.
    User prompt carries the current situation + history (dynamic per-step).
    Output uses DeepSeek JSON mode with predefined schemas.

    Phase 2a: L2's domain node selection is merged into L1 stage1.
    Task goal is provided by the communication script via the meta field
    (not hardcoded here).
    """

    MAX_LOOPS = 1
    # TODO: Increase MAX_LOOPS to enable multi-round L1→L2 and L2→L3 queries.
    # The architecture supports iterative refinement: L1 can re-query L2 with
    # adjusted questions, and L2 can re-query L3 with refined tasks.
    # Currently disabled — single-shot only.

    STAGE1_SCHEMA = {
        "query": "string (需要下层根据领域知识完成的任务。可附上基于【行为准则】的完成建议，给出可直接使用的相关准则整合。注意下层看不到完整的【行为准则】)",
        "call_l2": "boolean (是否需要查询下层 L2 知识库，true/false)",
        "domain_nodes": [
            {"name": "string (从领域节点列表中选出的节点路径，如 game/leduc)",
             "score": "float (该节点与当前决策的相关度分数，0.0-1.0)",
             "reason": "string (选择该节点的理由，一短句)"}
        ],
    }
    STAGE2_SCHEMA = {
        "done": "boolean (true/false)",
        "result": "string (最终决策)",
        "reasoning": "string (推理过程)",
        "rules_used": ["string (本次决策中实际引用的行为准则的id，如 l1_001)"],
    }

    # Consolidation tools — modifications via tool calls
    _L1_CONSOLIDATION_TOOLS: list[dict] = [
        {"type": "function", "function": {
            "name": "deprecate_l1_rule",
            "description": "废弃（删除）一条 L1 行为准则。用于移除重复、低质量或违反跨领域原则的规则。",
            "parameters": {"type": "object", "properties": {
                "rule_id": {"type": "string", "description": "要删除的规则 id，如 l1_001"},
                "reason": {"type": "string", "description": "删除理由，如'与另一条重复'或'内容模糊'"},
            }, "required": ["rule_id", "reason"], "additionalProperties": False},
        }},
        {"type": "function", "function": {
            "name": "create_l1_rule",
            "description": "创建一条新的 L1 行为准则。用于合并重复规则或添加新的通用原则。",
            "parameters": {"type": "object", "properties": {
                "content": {"type": "string", "description": "完整规则文本，1-2句清晰可执行的行为准则"},
                "reason": {"type": "string", "description": "创建理由，如'合并了3条概率决策规则'"},
            }, "required": ["content", "reason"], "additionalProperties": False},
        }},
        {"type": "function", "function": {
            "name": "modify_l1_rule",
            "description": "Modify an existing L1 rule. Use content to update rule text, or pass only usefulness/misleading/comment to record quality feedback without changing content.\n\nQuality fields (both range -5 to +5):\n  usefulness: +5=critical help for correct decision, +3=helpful guidance, +1=slightly useful, 0=unset/no opinion, -1=not very useful, -3=useless/wasted tokens, -5=harmful leading to wrong decision.\n  misleading: +5=severely misleading causing critical error, +3=clearly misled reasoning, +1=slightly inaccurate/outdated, 0=unset/no opinion, -1=mostly accurate, -3=highly accurate/trustworthy, -5=completely reliable never misleads.\n  comment: natural language quality note, max 100 chars. Omit if no opinion.",
            "parameters": {"type": "object", "properties": {
                "rule_id": {"type": "string", "description": "Rule id to modify, e.g. l1_001"},
                "content": {"type": "string", "description": "Full modified rule text. Omit if only recording quality feedback without content change."},
                "reason": {"type": "string", "description": "Reason for modification or quality update"},
                "usefulness": {"type": "integer", "description": "How useful this rule was during reflection. Range -5 to +5."},
                "misleading": {"type": "integer", "description": "How misleading this rule was during reflection. Range -5 to +5."},
                "comment": {"type": "string", "description": "Quality description, max 100 chars."},
            }, "required": ["rule_id", "reason"], "additionalProperties": False},
        }},
    ]

    def _setup_l1_consolidation(self):
        """Wire DictInjector for L1 consolidation tools."""
        agent = self

        def deprecate_l1_rule(args: dict) -> str:
            agent._pending_mods.append({
                "type": "deprecate", "target": args["rule_id"],
                "reason": args["reason"], "layer": "l1",
            })
            return f"已记录: 删除 {args['rule_id']}"

        def create_l1_rule(args: dict) -> str:
            agent._pending_mods.append({
                "type": "create", "target": "", "layer": "l1",
                "content": args["content"], "reason": args["reason"],
            })
            return f"已记录: 创建新规则"

        def modify_l1_rule(args: dict) -> str:
            mod = {"type": "update", "target": args["rule_id"], "layer": "l1",
                   "content": args["content"], "reason": args["reason"]}
            if "usefulness" in args:
                mod["usefulness"] = args["usefulness"]
            if "misleading" in args:
                mod["misleading"] = args["misleading"]
            if "comment" in args:
                mod["comment"] = args["comment"]
            agent._pending_mods.append(mod)
            return f"已记录: 修改 {args['rule_id']}"

        self._injector = DictInjector({
            "deprecate_l1_rule": deprecate_l1_rule,
            "create_l1_rule": create_l1_rule,
            "modify_l1_rule": modify_l1_rule,
        })

    def __init__(self, llm_client, philosophy):
        super().__init__(llm_client, logger)
        self._philosophy = philosophy

    def _build_system_prompt(self, instruction: str, meta: str,
                              static_context: str = "") -> str:
        """Build system prompt: layer identity + instruction + meta + behavior rules."""
        rules = self._philosophy.all_rules()
        rules_text = "\n".join(f"- {r.content}" for r in rules) if rules else "（无）"
        extra = f"\n{static_context}\n" if static_context else ""
        return (
            f"## 认知层架构\n"
            f"- L1（你）：管理行为准则，负责顶层任务拆解与最终决策\n"
            f"- L2：管理概率性知识卡片，负责相关知识检索与技能调度\n"
            f"- L3：管理 SKILL.md 技能，负责标准化流程执行\n\n"
            f"## 领域边界\n"
            f"你只管理 L1 行为准则（Philosophy Rules）。\n"
            f"不要修改 L2 的知识卡片或 L3 的技能。\n\n"
            f"## 指令\n{instruction}\n\n"
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

    def stage1(self, meta: str, state: dict, domain_nodes: list[dict] | None = None) -> dict:
        """Stage1: produce query + domain targeting.

        Merges L2's domain-node selection into L1. Domain nodes injected into
        system prompt (static context), not user prompt.
        """
        nodes = domain_nodes or []
        nodes_text = "\n".join(
            f"{i + 1}. {n.path if hasattr(n, 'path') else n['name']}\n"
            f"   {n.description if hasattr(n, 'description') else n.get('description','')}"
            for i, n in enumerate(nodes)
        )
        instruction = (
            "你的职责：基于【行为准则】将任务拆解为下层需要协助的具体子任务。\n"
            "拆解时思考：已有信息能完成什么、还差什么子任务或信息、所需材料是否可以由下层提供。\n\n"
            "你的 query 应结合本层的行为准则和任务目标，给出清晰的拆解任务交给 L2 层。\n\n"
            "如果任务完全可以在 L1 层独立完成（无需 L2/L3 协助），设置 call_l2=false。\n"
            "从领域节点中选出最相关的 1-5 个节点。不需要领域知识时返回空的 domain_nodes（[]）。"
        )
        system = self._build_system_prompt(
            instruction, meta,
            static_context=f"[领域节点]\n{nodes_text}" if nodes_text else "",
        )
        user = self._build_user_context(state)
        result = self._call_llm(system, user, schema=self.STAGE1_SCHEMA)
        return result

    def stage2(self, meta: str, state: dict,
               l2_result: dict | None = None) -> dict:
        """Stage2: integrate L2 knowledge and produce final decision.
        For consolidation: uses tool calls to record modifications.
        """
        l1_fmt = state.get("l1_output_format")

        instruction = (
            "你的职责：基于【行为准则】整合下层返回的知识信息，做出最终决策。"
            "在 rules_used 中列出本次推理中实际引用到的行为准则的 id。"
        )
        if l1_fmt:
            instruction += (
                "\n\n【整理任务】你只负责 L1 行为准则（Philosophy rules）的修改。"
                "不要修改 L2 知识卡片或 L3 技能。"
                "使用工具 deprecate_l1_rule / create_l1_rule / modify_l1_rule 记录修改。"
            )
        system = self._build_system_prompt(instruction, meta)

        l2 = l2_result or {}
        reply = l2.get("reply", "")
        reasoning = l2.get("reasoning", "")
        parts = []
        if reply:
            parts.append(f"L2回复: {reply}")
        if reasoning:
            parts.append(f"L2推理: {reasoning}")
        response_text = "\n\n".join(parts) if parts else "（下层未返回信息）"
        l1_task_text = state.get("l1_task", "")
        l1_task_section = f"[L1 整理任务]\n{l1_task_text}\n\n" if l1_task_text else ""
        user = f"{l1_task_section}{self._build_user_context(state)}\n\n[下层任务返回]\n{response_text}"

        if l1_fmt:
            self._setup_l1_consolidation()
            tools = self._L1_CONSOLIDATION_TOOLS
            self._log.debug("  consolidation tools: %s",
                           [t["function"]["name"] for t in tools])
            schema = None
        else:
            tools = None
            schema = self.STAGE2_SCHEMA
        result = self._call_llm(system, user, schema=schema, tools=tools, layer="l1")

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
                 domain_registry=None):
        super().__init__("l0_5_1", downstream, upward=upward, downward=downward)
        self._meta = meta_driver
        self._philosophy = philosophy
        self._agent = L1Agent(auxiliary_llm, philosophy) if auxiliary_llm else None
        self._registry = domain_registry
        self._final_result: dict | None = None

    def process(self, data: Any) -> dict:
        return {"status": "ok", "layer": self.name}

    def query(self, msg: LayerMessage | Any, trace_id: str = "") -> None:
        if isinstance(msg, LayerMessage):
            data = self._upward.receive(msg)
            if not trace_id:
                trace_id = msg.trace_id
        else:
            data = msg

        obs: TaskObservation = data
        meta = obs.meta

        if self._agent is None:
            logger.warning("L1Agent not initialized (no auxiliary_llm), skipping")
            self._final_result = {"done": True, "result": "", "reasoning": "no agent"}
            return

        for loop in range(1, L1Agent.MAX_LOOPS + 1):
            logger.debug("── L1 Stage 1 [loop %d/%d] ──", loop, L1Agent.MAX_LOOPS)
            domain_nodes = []
            if self._registry:
                domain_nodes = self._registry.list_all()
            stage1_result = self._agent.stage1(meta, obs.state,
                                                domain_nodes=domain_nodes)
            query_text = stage1_result.get("query", "")
            selected_nodes = stage1_result.get("domain_nodes", [])
            call_l2 = stage1_result.get("call_l2", True)
            logger.debug("  query: %s", query_text)
            logger.debug("  call_l2: %s", call_l2)
            for n in selected_nodes:
                logger.debug("    node: %s (score=%s)", n.get("name"), n.get("score"))

            need_l2 = call_l2 and bool(selected_nodes or query_text)
            if self._downstream and need_l2:
                # E3: pass data via LayerMessage payload, not obs.state mutation
                q_msg = self._downward.wrap_query(
                    payload={"obs": obs, "query": query_text,
                             "selected_nodes": selected_nodes},
                    source=self.name, target=self._downstream.name,
                    trace_id=trace_id,
                )
                self._downstream.query(q_msg, trace_id)

            # E3: read L2 results only if L2 was queried
            if need_l2:
                l2_result = self._downstream._result if self._downstream else {}
            else:
                l2_result = {}

            logger.debug("── L1 Stage 2 [loop %d/%d] ──", loop, L1Agent.MAX_LOOPS)
            result = self._agent.stage2(meta, obs.state,
                                        l2_result=l2_result)
            logger.debug("  result: done=%s result=%s",
                         result.get("done"), str(result.get("result", ""))[:200])

            if result.get("done"):
                self._final_result = result
                return

        # TODO: When MAX_LOOPS > 1, loop allows multi-round refinement.
        # Use the last stage2 result (even if incomplete) rather than empty.
        self._final_result = result.copy()
        self._final_result["done"] = True

    def notify(self) -> Any:
        if self._final_result:
            result = dict(self._final_result)
            if self._agent:
                mods = self._agent.get_pending_mods()
                if mods:
                    result["l1_modifications"] = mods
            return result
        return {"status": "ok", "layer": self.name}
