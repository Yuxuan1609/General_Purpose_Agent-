from __future__ import annotations
import json
import logging
from typing import Any
from core.task import Domain
from core.types import TaskObservation
from core.layers.base import LayerManager, LayerAgent, _indent
from core.layers.comm import AgentPacket
from core.layer_message import LayerMessage

logger = logging.getLogger("l2")


def cascade_consolidation_to_l3(downstream, meta, state, trace_id):
    """Propagate consolidation task to L3 and collect NOTIFY."""
    cascade_obs = TaskObservation(
        meta=meta,
        state={
            **state,
            "context_history": [],
            "domains_hint": state.get("domains_hint", []),
        },
        session={
            "domain": state.get("domains_hint", ["general"])[0],
            "enable_learning": False,
        },
    )
    downstream.query(cascade_obs, trace_id)
    return downstream.collect_notify()


class L2Agent(LayerAgent):
    """L2 LLM Agent — while-loop decision via capture_tool mode.

    decide() is called by L2Manager's while loop. Two output tools:
      - l2_query: delegate subtask to L3
      - l2_report: deliver final answer to upper layer

    Consolidation mode uses l2_report with ToolRegistry handlers.
    """

    L2_DECISION_SCHEMA = {
        "type": "object",
        "properties": {
            "done": {"type": "boolean"},
            "reply": {"type": "string", "description": "回复上层查询的结论"},
            "selected_nodes": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "score": {"type": "number"},
                    },
                },
            },
            "selected_cards": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "card_id": {"type": "string"},
                        "domain": {"type": "string"},
                        "content": {"type": "string"},
                    },
                },
            },
            "queries_to_L3": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "domain": {"type": "string", "description": "目标领域"},
                        "task": {"type": "string", "description": "委托 L3 执行的技能任务"},
                    },
                },
            },
            "reasoning": {"type": "string"},
        },
        "required": ["done", "reasoning"],
    }



    def __init__(self, llm_client, knowledge, domain_nodes: list[dict] | None = None,
                 domain_registry=None):
        super().__init__(llm_client, logger)
        self._knowledge = knowledge
        self._registry = domain_registry
        from core.config_loader import get_section
        l2cfg = get_section('l2', default={})
        self._max_nodes = l2cfg.get('max_nodes', 5)
        self._max_cards = l2cfg.get('max_cards', 15)

    def _build_system_prompt(self, instruction: str, meta: str,
                              static_context: str = "") -> str:
        extra = f"\n{static_context}\n" if static_context else ""
        tool_rules = (
            "## 工具调用规则\n"
            "- 所有工具都有 sync 参数。sync=true(默认)阻塞等结果，sync=false 返回 task_id\n"
            "- sync=false 的任务用 collect_tasks(task_ids) 收割结果\n"
            "- check_task(task_id) 可查单个任务状态\n"
            "- 同一轮内多个 sync=true 工具并行执行，互不阻塞\n"
            "- 长耗时任务（kb_fill_gap、terminal 跑 shell 脚本等）建议设 sync=false\n"
        )
        return (
            f"## 认知层架构\n"
            f"- L1：管理行为准则，负责顶层任务拆解与最终决策\n"
            f"- L2（你）：管理概率性知识卡片，负责相关知识检索与技能调度。可调用 terminal/web_search/read_file/grep/tool_proposal 等工具。\n"
            f"- L3：管理 SKILL.md 技能，负责标准化流程执行。可调用 terminal/web_search/read_file/grep/tool_proposal 等工具。\n\n"
            f"## 领域边界\n"
            f"你只管理 L2 知识卡片（Knowledge Cards）。\n"
            f"不要修改 L1 的行为准则或 L3 的技能。\n\n"
            f"## 指令\n{instruction}\n\n"
            f"{tool_rules}\n"
            f"[Meta]\n{meta}\n"
            f"{extra}"
        )

    def _format_domain_nodes(self, nodes: list[dict]) -> str:
        if not nodes:
            return ""
        lines = ["[L1 选定领域]"]
        for n in nodes:
            name = n.get("name", n.get("path", "?"))
            score = n.get("score", n.get("relevance", 0))
            corrs = n.get("correlations", {})
            corr_str = ""
            if corrs:
                parts = [f"{k}:{v:.1f}" for k, v in sorted(corrs.items())]
                corr_str = f" corr={{ {'  '.join(parts)} }}"
            rel = n.get("relations", "")
            rel_str = f" [{rel}]" if rel else ""
            lines.append(f"  {name} (score={score:.2f}{corr_str}){rel_str}")
        return "\n".join(lines) + "\n\n"

    def _format_consolidation_cards(self, domains: list[str], stats: dict) -> str:
        """Build per-domain card listing with DD3 fields."""
        lines = []
        for domain_path in sorted(domains):
            cards = [c for c in self._knowledge.cards if c.domain.path == domain_path]
            if not cards:
                continue
            lines.append(f"### {domain_path} ({len(cards)} cards)")
            for c in cards:
                st = stats.get("l2", {}).get(c.id, {})
                comment_line = f"\n  comment: {c.comment}" if c.comment else ""
                lines.append(
                    f"- [{c.id}] used={st.get('use_count', 0)} "
                    f"last={st.get('last_used', '-')[:10]} useful=+{c.usefulness} "
                    f"mislead={c.misleading} | {c.content[:120]}{comment_line}"
                )
            lines.append("")
        return "\n".join(lines)

    def _build_learning_section(self, state: dict) -> str:
        units = state.get("learning_units", [])
        if not isinstance(units, list) or not units:
            return ""
        recs = []
        for u in units:
            l2_r = u.get("l2_reasoning", "")
            action = u.get("action", "")
            line = f"[{u.get('index', '?')}] action={action} | L2: {l2_r[:200]}" if l2_r else f"[{u.get('index', '?')}] action={action}"
            recs.append(line)
        result = "| " + " | ".join(recs) if recs else ""
        fb = state.get("feedback", "")
        l2_fb = state.get("l2_feedback", "")
        if l2_fb:
            fb = f"{fb}\n{l2_fb}" if fb else l2_fb
        if fb:
            result += f"\n\n[L2 修改结果确认]\n{fb}"
        return result

    def decide(self, query: str, meta: str, state: dict, context: dict,
               tools: list[dict] | None = None, layer: str = "l2") -> dict:
        """Single decision step for L2 while loop.

        Two capture tools:
          - l2_query: request skill execution from L3 (done=false, queries_to_L3=[...])
          - l2_report: deliver answer to upper layer (done=true, reply=...)
        Consolidation mode uses l2_report only.
        """
        l2_fmt = state.get("l2_output_format")
        selected_nodes = context.get("selected_nodes", [])
        candidate_cards = context.get("candidate_cards", [])
        l3_results = context.get("l3_results", [])

        cards_text = ""
        if candidate_cards:
            lines = []
            for c in candidate_cards:
                domain = c.get("domain", c.domain.path if hasattr(c, 'domain') else '')
                content = c.get("content", c.content if hasattr(c, 'content') else str(c))
                lines.append(f"[{domain}] {content}")
            cards_text = "\n".join(lines)
        elif selected_nodes:
            cards = self._get_cards_for_nodes(selected_nodes)
            node_scores = {n.get("name", ""): n.get("score", 0) for n in selected_nodes}
            cards_text = self._format_cards_with_relevance(cards, node_scores) if cards else (
                "⚠️ 当前所选领域暂无知识卡片。" if selected_nodes else "（无相关卡片）"
            )
        else:
            cards_text = "（无相关卡片）"

        l3_text = ""
        if l3_results:
            parts = []
            for l3r in l3_results:
                r = l3r.get("l3", {})
                if isinstance(r, dict) and r.get("result"):
                    parts.append(f"L3: {r['result'][:50000]}")
            l3_text = "\n".join(parts) if parts else "（L3 未返回信息）"

        instruction = (
            "你的核心任务是完成上层 query，Meta 提供任务整体背景。\n"
            "你有最多 5 轮工具调用次数，用完会自动截断并要求你总结。\n"
            "请在前 3-4 轮集中收集信息，最后 1-2 轮务必调用 l2_report 输出结论。\n\n"
            "*** 输出规则（极其重要）***\n"
            "1. 如果你需要 L3 的技能来执行具体任务（如搜索、分析、格式化输出等有明确定义的工作） → 调用【l2_query】工具下发任务\n"
            "2. 如果你已经掌握了足够信息，可以回复上层查询 → 调用【l2_report】工具输出结论\n"
            "3. 禁止以文本方式直接输出JSON或回复，必须调用以上两个工具之一！\n\n"
            "l2_query：向下调度，done固定为false。每次只下发一个技能任务。\n"
            "l2_report：向上回复，done固定为true，含 reply 最终结论"
        )
        if l2_fmt:
            instruction += (
                "\n\n【整理任务】你只负责 L2 知识卡片的修改。"
                "使用整理工具记录修改，完成后调用 l2_report 输出结果。"
            )

        system = self._build_system_prompt(instruction, meta)
        nodes_section = self._format_domain_nodes(selected_nodes)

        # Build context history from previous L2 calls (within same executor trace)
        context_text = ""
        ctx_history = state.get("context_history", [])
        if ctx_history:
            lines = []
            for i, h in enumerate(ctx_history):
                lines.append(f"第{i+1}次查询: {h.get('query', '')[:300]}")
                lines.append(f"第{i+1}次结果摘要: {h.get('reply', '')[:500]}")
            context_text = "\n".join(lines)

        ctx_section = f"[本轮上下文]\n{context_text}\n\n" if context_text else ""
        user = (
            f"[上层查询]\n{query}\n\n"
            f"{ctx_section}"
            f"{nodes_section}"
            f"[学习数据]\n{self._build_learning_section(state)}\n\n"
            f"[知识卡片]\n{cards_text}\n\n"
            f"[L3 返回]\n{l3_text if l3_text else '当前领域无预匹配技能。如有明确可执行的任务，可通过 l2_query 下发，L3 自行判断能否完成。'}"
        )

        if l2_fmt:
            from core.tools.registry import ToolRegistry
            from core.tools.consolidation_tools import L2_CONSOLIDATION_TOOL_NAMES
            _allowed = {"kb_query", "read_file", "grep"}
            base_tools = [t for t in (self._get_tools(layer) or [])
                          if t["function"]["name"] in _allowed]
            consol_schemas = ToolRegistry().get_definitions(L2_CONSOLIDATION_TOOL_NAMES)
            report_tool = self._schema_to_tool(
                "l2_report",
                "【特殊工具：向上汇报】必须使用！整理完成后调用此工具输出最终结果。禁止以文本方式直接回复。",
                {
                    "type": "object",
                    "properties": {
                        "done": {"type": "boolean", "const": True},
                        "reply": {"type": "string", "description": "回复上层查询的结论"},
                        "reasoning": {"type": "string"},
                    },
                    "required": ["done", "reply", "reasoning"],
                },
            )
            all_tools = base_tools + consol_schemas + [report_tool]
            self._log.debug("  tools: %s", [t["function"]["name"] for t in all_tools])
            result = self._call_llm(system, user, tools=all_tools, layer=layer,
                                    capture_tools={"l2_report"})
            result = {
                "done": True,
                "reply": result.get("reply", ""),
                "selected_nodes": [],
                "selected_cards": [],
                "queries_to_L3": [],
                "reasoning": result.get("reasoning", ""),
            }
            return result

        # Normal mode: two capture tools
        base_tools = self._get_tools(layer) or []
        query_tool = self._schema_to_tool(
            "l2_query",
            "【特殊工具：向下调度】当需要下层L3执行具体技能任务时使用。"
            "通过 selected_nodes 选择相关领域，通过 queries_to_L3 下发任务。禁止以文本方式直接回复！",
            {
                "type": "object",
                "properties": {
                    "done": {"type": "boolean", "const": False},
                    "selected_nodes": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "path": {"type": "string"},
                                "score": {"type": "number"},
                            },
                        },
                    },
                    "queries_to_L3": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "domain": {"type": "string", "description": "目标领域"},
                                "task": {"type": "string", "description": "委托 L3 执行的技能任务"},
                            },
                        },
                    },
                    "reasoning": {"type": "string"},
                },
                "required": ["done", "reasoning"],
            },
        )
        report_tool = self._schema_to_tool(
            "l2_report",
            "【特殊工具：向上回复】当你有了足够信息可以回复上层查询时使用。"
            "给出明确的结论和推理过程。禁止以文本方式直接回复！",
            {
                "type": "object",
                "properties": {
                    "done": {"type": "boolean", "const": True},
                    "reply": {"type": "string", "description": "回复上层查询的结论"},
                    "selected_cards": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "card_id": {"type": "string"},
                                "domain": {"type": "string"},
                                "content": {"type": "string"},
                            },
                        },
                    },
                    "reasoning": {"type": "string"},
                },
                "required": ["done", "reply", "reasoning"],
            },
        )
        all_tools = base_tools + [query_tool, report_tool]
        self._log.debug("  tools: %s", [t["function"]["name"] for t in all_tools])
        result = self._call_llm(system, user, tools=all_tools, layer=layer,
                                capture_tools={"l2_query", "l2_report"})
        if not result.get("done"):
            raw = result.get("_raw") or result.get("reply") or ""
            if raw:
                return {"done": True, "reply": str(raw), "reasoning": "direct reply",
                        "selected_nodes": [], "selected_cards": [], "queries_to_L3": []}
        return result

    def _get_cards_for_nodes(self, nodes: list[dict]) -> list:
        if self._registry:
            domains = [n.get("name", "") for n in nodes if n.get("name")]
            card_ids = self._registry.get_items_for_domains("l2", domains)
            if card_ids:
                card_id_set = set(card_ids)
                return [c for c in self._knowledge.cards if c.id in card_id_set]

        all_cards = []
        seen = set()
        for node in nodes:
            name = node.get("name", "")
            if name in seen:
                continue
            seen.add(name)
            try:
                domain = Domain(name, "specific")
            except Exception:
                domain = Domain("general", "general")
            all_cards.extend(self._knowledge.get_domain_cards(domain))
        return all_cards

    @staticmethod
    def _format_cards_with_relevance(cards: list, node_scores: dict) -> str:
        """Build card display text with relevance from L1's domain-node scores."""
        lines = []
        for c in cards:
            score = node_scores.get(c.domain.path, 0.0)
            lines.append(f"[{c.domain.path}] (相关度:{score:.2f}) {c.content}")
        return "\n".join(lines) if lines else "（无相关卡片）"


class L2Manager(LayerManager):
    """L2 Manager — wraps FlexibleKnowledge + L2Agent.

    Overrides query() to drive while-loop:
      decide() → propagate queries to L3 → collect NOTIFY.

    NOTIFY goes to both upper layer (L1) and Executor.
    """

    def __init__(self, knowledge, downstream: LayerManager | None = None,
                 upward=None, downward=None, auxiliary_llm=None,
                 domain_registry=None, max_rounds=None):
        super().__init__("l2", downstream, upward=upward, downward=downward)
        self._knowledge = knowledge
        self._agent = L2Agent(auxiliary_llm, knowledge, domain_registry=domain_registry) if auxiliary_llm else None
        self._registry = domain_registry
        if max_rounds is None:
            from core.config_loader import get_section
            max_rounds = get_section('runtime', default={}).get('max_rounds_l2', 3)
        self.max_rounds = max_rounds
        self._l2_notify: dict | None = None
        self._cards: list[dict] = []
        self._l3_history: list[dict] = []

    def process(self, data: Any) -> dict:
        return {"status": "ok", "layer": self.name}

    def query(self, msg: LayerMessage | Any, trace_id: str = "") -> None:
        obs, trace_id = self._unwrap_obs(msg, upward=self._upward, trace_id=trace_id)

        query: str = obs.meta
        selected_nodes: list[dict] = obs.state.get("selected_nodes", []) if obs.state else []

        if not selected_nodes:
            domains_hint = obs.state.get("domains_hint", []) if obs.state else []
            if domains_hint:
                selected_nodes = [{"name": d, "score": 1.0} for d in domains_hint]

        if self._registry and selected_nodes:
            for n in selected_nodes:
                name = n.get("name", n.get("path", ""))
                node = self._registry.get_node(name) if name else None
                if node and node.correlations:
                    n["correlations"] = node.correlations
                if node and node.relations:
                    n["relations"] = node.relations

        if self._agent is None:
            logger.warning("L2Agent not initialized (no auxiliary_llm), skipping")
            self._cards = []
            self._l2_notify = {"reply": "", "cards": [], "reasoning": "no agent"}
            self._propagate(obs, trace_id)
            return

        state = dict(obs.state) if obs and obs.state else {}
        # Clear L3 history on new executor trace (no context_history in state)
        if "context_history" not in state:
            self._l3_history.clear()
        context: dict = {
            "selected_nodes": selected_nodes,
            "candidate_cards": [],
            "l3_results": [],
        }

        tools = self._agent._get_tools("l2") if self._agent else None
        result = self._agent.decide(
            query=query, meta=meta, state=state,
            context=context, tools=tools, layer="l2",
        )
        logger.debug("  result: done=%s reply=%s",
                     result.get("done"), str(result.get("reply", ""))[:2000])

        cards = result.get("selected_cards", [])
        self._cards = cards
        self._l2_notify = {
            "reply": result.get("reply", ""),
            "cards": cards,
            "reasoning": result.get("reasoning", ""),
        }

        # Cascade consolidation to L3
        if "l2_output_format" in state and self._downstream and self._agent:
            l3_notify_full = cascade_consolidation_to_l3(
                self._downstream, meta, state, trace_id)
            if l3_notify_full:
                self._l2_notify["l3_modifications"] = \
                    l3_notify_full.get("l3_modifications",
                                       l3_notify_full.get("l3", {}).get("l3_modifications", []))

        for q in result.get("queries_to_L3", []):
            sub_obs = TaskObservation(
                meta=q["task"],
                state={
                    **state, "domain": q.get("domain", ""),
                    "context_history": list(self._l3_history),
                },
            )
            self._propagate(sub_obs, trace_id)
            l3_notify = self._downstream.collect_notify()
            l3_result_text = ""
            if isinstance(l3_notify, dict):
                l3_part = l3_notify.get("l3", {})
                if isinstance(l3_part, dict):
                    l3_result_text = l3_part.get("result", "")
            self._l3_history.append({
                "query": q["task"][:200],
                "reply": l3_result_text[:1000],
            })

        # Collect L3 children for RoundTree
        if self._l2_notify and self._l3_history:
            l3_children = []
            for h in self._l3_history:
                l3_children.append({
                    "task": h.get("query", ""),
                    "result": h.get("reply", ""),
                })
            self._l2_notify["_l3_children"] = l3_children

    def _propagate(self, obs, trace_id: str, l3_task: str = "",
                   selected_nodes: list[dict] | None = None) -> None:
        if self._downstream:
            enriched_state = dict(obs.state) if obs.state else {}
            if l3_task:
                enriched_state["l3_task"] = l3_task
            if selected_nodes:
                enriched_state["selected_nodes"] = selected_nodes
            enriched_obs = TaskObservation(
                meta=obs.meta, state=enriched_state, session=obs.session,
            )
            self._downstream.query(enriched_obs, trace_id=trace_id)

    def _build_cards(self, selected_nodes: list[dict]) -> list[dict]:
        """E3: build cards list locally, return value — no obs.state mutation."""
        cards: list = []
        seen = set()
        for node in selected_nodes:
            name = node.get("name", "")
            if name in seen:
                continue
            seen.add(name)
            try:
                domain = Domain(name, "specific")
            except Exception:
                continue
            cards.extend(self._knowledge.get_domain_cards(domain))
        return [
            {
                "content": c.content,
                "domain": c.domain.path,
            }
            for c in cards
        ]

    def _build_cards_from_ids(self, card_ids: list[str]) -> list[dict]:
        cards = []
        for cid in card_ids:
            for c in self._knowledge.cards:
                if c.id == cid:
                    cards.append({
                        "content": c.content,
                        "domain": c.domain.path,
                    })
                    break
        return cards

    def notify(self) -> Any:
        if self._l2_notify:
            result = dict(self._l2_notify)
            from core.tools.consolidation_tools import get_pending_mods
            mods = get_pending_mods()
            if mods:
                result["l2_modifications"] = mods
            return result
        return {"status": "ok", "layer": self.name}


