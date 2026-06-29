from __future__ import annotations
import json
import logging
from typing import Any
from core.task import Domain
from core.layers.base import LayerManager, LayerAgent, _indent
from core.layers.comm import AgentPacket
from core.layer_message import LayerMessage

logger = logging.getLogger("l2")


from core.layers.base import CaptureToolDef, ConsolidationStrategy

L2_REPORT_TOOL = CaptureToolDef(
    name="l2_report",
    description="【特殊工具：向上回复】当你有了足够信息可以回复上层查询时使用。"
    "给出明确的结论和推理过程。禁止以文本方式直接回复！",
    done=True,
    schema={
        "type": "object",
        "properties": {
            "done": {"type": "boolean", "const": True},
            "reply": {"type": "string", "description": "回复上层查询的结论"},
            "selected_cards": {"type": "array", "items": {
                "type": "object", "properties": {
                    "card_id": {"type": "string"}, "domain": {"type": "string"},
                    "content": {"type": "string"},
                },
            }},
            "reasoning": {"type": "string"},
        },
        "required": ["done", "reply", "reasoning"],
    },
)


from core.tools.consolidation_tools import L2_CONSOLIDATION_TOOL_NAMES
L2_CONSOLIDATION_STRATEGY = ConsolidationStrategy(
    consolidation_tool_names=L2_CONSOLIDATION_TOOL_NAMES,
    allowed_base_tools={"kb_query", "read_file", "grep", "l2_query"},
    report_tool=L2_REPORT_TOOL,
)


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
        from core.layers.base import _TOOL_RULES
        tool_rules = _TOOL_RULES
        l2_query_guide = (
            "## l2_query 工具用法\n"
            "l2_query 是向 L3 层下发技能执行任务的工具。使用场景：\n"
            "- 需要 L3 执行具体操作（环境允许的工具）\n"
            "- 需要 L3 按标准化流程（SKILL.md）完成复杂任务\n"
            "每次 l2_query 下发一个任务，L3 会返回执行结果。收到结果后：\n"
            "- 如果还需要 L3 执行更多操作 → 再发一次 l2_query\n"
            "- 如果已掌握足够信息 → 调用 l2_report 向上回复\n"
            "禁止在未调用 l2_query 调度 L3 的情况下直接 l2_report（除非任务无需 L3 辅助）。\n"
        )
        return (
            f"## 认知层架构\n"
            f"- L1：管理行为准则，负责顶层任务拆解与最终决策\n"
            f"- L2（你）：管理概率性知识卡片，负责相关知识检索与技能调度。可调用环境允许的工具执行具体操作。\n"
            f"- L3：管理 SKILL.md 技能，负责标准化流程执行。可调用环境允许的工具执行具体操作。\n\n"
            f"## 领域边界\n"
            f"你只管理 L2 知识卡片（Knowledge Cards）。\n"
            f"不要修改 L1 的行为准则或 L3 的技能。\n\n"
            f"{l2_query_guide}\n"
            f"{tool_rules}\n"
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
        instruction += (
            "\n\n【学习记录】\n"
            "如果本轮分析中发现了值得固化的知识（L2知识缺口、新发现的高效策略、L3技能缺失等），"
            "可以调用 record_learning 工具记录。判断标准: 完成了复杂查询或分析任务、"
            "发现 L2 知识缺口或 L3 技能缺失、当前结果可作为可复用经验。"
        )
        if l2_fmt:
            instruction += (
                "\n\n【整理任务】你只负责 L2 知识卡片的修改。"
                "使用整理工具记录修改，完成后调用 l2_report 输出结果。"
                "\n要求：先调用 l2_query 向 L3 下发整理需求（如审查技能过时/重复/功能重叠等），"
                "收到 L3 回复后汇总 L2+L3 结果输出。禁止在未查询 L3 的情况下直接 report。"
            )

        system = self._build_system_prompt(instruction, meta)
        nodes_section = self._format_domain_nodes(selected_nodes)


        meta_section = f"[任务背景]\n{meta}\n\n" if meta else ""
        user = (
            f"{meta_section}"
            f"[上层查询]\n{query}\n\n"
            f"{nodes_section}"
            f"[学习数据]\n{self._build_learning_section(state)}\n\n"
            f"[知识卡片]\n{cards_text}\n\n"
            f"[L3 返回]\n{l3_text if l3_text else '当前领域无预匹配技能。如有明确可执行的任务，可通过 l2_query 下发，L3 自行判断能否完成。'}"
        )

        if l2_fmt:
            all_tools, capture_set = L2_CONSOLIDATION_STRATEGY.build_tools(self, layer)
            self._log.debug("  tools: %s", [t["function"]["name"] for t in all_tools])
            result = self._call_llm(system, user, tools=all_tools, layer=layer,
                                    capture_tools=capture_set)
            return {
                "done": True,
                "reply": result.get("reply", ""),
                "selected_nodes": [],
                "selected_cards": [],
                "queries_to_L3": [],
                "reasoning": result.get("reasoning", ""),
            }

        # Normal mode: single capture tool (l2_query is now a regular tool)
        base_tools = self._get_tools(layer) or []
        all_tools = base_tools + [L2_REPORT_TOOL.to_openai_tool()]
        self._log.debug("  tools: %s", [t["function"]["name"] for t in all_tools])
        result = self._call_llm(system, user, tools=all_tools, layer=layer,
                                capture_tools={"l2_report"})
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
                logger.exception("Failed to construct Domain(%s), falling back to general", name)
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

    Single decide() call. L2 queries L3 via l2_query tool (in _call_llm tool loop).
    RoundTree built via thread-local node stack bound to decide.
    """

    def __init__(self, knowledge, downstream: LayerManager | None = None,
                 upward=None, downward=None, auxiliary_llm=None,
                 domain_registry=None):
        super().__init__("l2", downstream, upward=upward, downward=downward)
        self._knowledge = knowledge
        self._agent = L2Agent(auxiliary_llm, knowledge, domain_registry=domain_registry) if auxiliary_llm else None
        self._registry = domain_registry
        self._l2_notify: dict | None = None
        self._cards: list[dict] = []

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
            return

        state = dict(obs.state) if obs and obs.state else {}
        context: dict = {
            "selected_nodes": selected_nodes,
            "candidate_cards": [],
            "l3_results": [],
        }

        from core.round_tree import DecisionNode, push_node, pop_node, current_node
        l2_node = DecisionNode(layer="l2", query=query, result="", reasoning="")
        push_node(l2_node)

        logger.debug("── L2 decide ──")
        tools = self._agent._get_tools("l2") if self._agent else None
        result = self._agent.decide(
            query=query, meta=obs.meta, state=state,
            context=context, tools=tools, layer="l2",
        )
        logger.debug("  result: done=%s reply=%s",
                     result.get("done"), str(result.get("reply", ""))[:2000])

        l2_node.result = result.get("reply", "")
        l2_node.reasoning = result.get("reasoning", "")
        pop_node()
        parent = current_node()
        if parent is not None:
            parent.children.append(l2_node)

        cards = result.get("selected_cards", [])
        self._cards = cards
        self._l2_notify = {
            "reply": result.get("reply", ""),
            "cards": cards,
            "reasoning": result.get("reasoning", ""),
        }

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
                logger.exception("Failed to construct Domain(%s), skipping node", name)
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
            return dict(self._l2_notify)
        return {"status": "ok", "layer": self.name}


