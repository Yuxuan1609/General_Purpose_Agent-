from __future__ import annotations
import json
import logging
from typing import Any
from core.task import Domain
from core.types import TaskObservation
from core.layers.base import LayerManager, LayerAgent, _indent, DictInjector
from core.layers.comm import AgentPacket
from core.layer_message import LayerMessage

logger = logging.getLogger("l2")

# Domain nodes — manually seeded. Each node represents a semantic domain
# with name (matching L2 card domain path) and a ~100-char description.
# TODO: Unified node design (schema, persistence, auto-generation) to be
#       finalized in a future session. For now, manually maintained.
# DEPRECATED: will be removed; use DomainRegistry.list_all() instead
L2_DOMAIN_NODES = [
    {
        "name": "game/leduc",
        "description": (
            "Leduc Hold'em简化版德州扑克，2人对局，牌面K/Q/J各两种花色，"
            "翻牌前和翻牌后两轮下注阶段，最大2次加注/轮。配对比单张高，"
            "同牌型比牌面大小和花色。行动: call/raise/fold/check。"
        ),
    },
    {
        "name": "game/doudizhu",
        "description": (
            "斗地主3人卡牌游戏，54张牌含大小王，1地主vs2农民。牌型包括单张、对子、"
            "三张、顺子、连对、飞机、炸弹、火箭。地主先出牌，农民配合顶牌，先出完胜。"
        ),
    },
    {
        "name": "learning/reflect",
        "description": (
            "学习反思域。消费执行记录，分析策略问题、成功/失败模式，"
            "基于工作反馈提出各层知识改进建议。"
            "子域包括 learning/compile 和 learning/verify。"
        ),
    },
    {
        "name": "learning/consolidate",
        "description": (
            "知识整理域。管理知识库容量的维护操作：检测超限、合并相似条目、"
            "归档低活跃内容、标记过时条目。L2 cards 软上限 25/硬上限 30，"
            "L3 skills 软上限 15/硬上限 20。使用 deprecate > delete 策略保证可回滚。"
        ),
    },
]


class L2Agent(LayerAgent):
    """L2 LLM Agent — three-stage V-structure processing.

    Stage 1 (Node Selection):
        LLM scores domain nodes by relevance to L1's query.
        (Placeholder) Graph expansion via KnowledgeGraph.spread_activation().

    Stage 2 (Card Filter + L3 Decision):
        Retrieve cards from selected nodes → LLM filters ≤15 relevant.
        LLM decides whether to consult L3.

    Stage 3 (NOTIFY):
        Integrate L3 response + previous context → final notify output.
        Same pattern as L1's notify: reply to query + cards + reasoning.

    Output uses DeepSeek JSON mode with predefined schemas.
    """

    MAX_NODES = 5
    MAX_CARDS = 15

    STAGE1_SCHEMA = {
        "cards": ["string (筛选后的知识卡片内容)"],
        "call_l3": "boolean",
        "l3_task": "string (需要L3执行的任务，call_l3=false时可为空)",
        "reasoning": "string (推理过程)",
    }
    STAGE2_SCHEMA = {
        "reply": "string (对【上层查询】的最终回复)",
        "cards": ["string (精选知识卡片内容)"],
        "reasoning": "string (综合推理过程)",
    }

    # Consolidation tools — modifications via tool calls
    _L2_CONSOLIDATION_TOOLS: list[dict] = [
        {"type": "function", "function": {
            "name": "deprecate_l2_card",
            "description": "删除一张 L2 知识卡片",
            "parameters": {"type": "object", "properties": {
                "card_id": {"type": "string", "description": "卡片 id"},
                "reason": {"type": "string", "description": "删除理由"},
            }, "required": ["card_id", "reason"]},
        }},
        {"type": "function", "function": {
            "name": "create_l2_card",
            "description": "创建一张 L2 知识卡片",
            "parameters": {"type": "object", "properties": {
                "content": {"type": "string", "description": "完整卡片内容"},
                "domain": {"type": "string", "description": "所属 domain，如 game/leduc"},
                "reason": {"type": "string", "description": "创建理由"},
            }, "required": ["content", "domain", "reason"]},
        }},
    ]

    def _setup_l2_consolidation(self):
        agent = self

        def deprecate_l2_card(args: dict) -> str:
            agent._pending_mods.append({
                "type": "deprecate", "target": args["card_id"],
                "reason": args["reason"], "layer": "l2",
            })
            return f"已记录: 删除 {args['card_id']}"

        def create_l2_card(args: dict) -> str:
            agent._pending_mods.append({
                "type": "create", "target": "", "layer": "l2",
                "content": args["content"], "domain": args["domain"],
                "reason": args["reason"],
            })
            return f"已记录: 创建新卡片"

        self._injector = DictInjector({
            "deprecate_l2_card": deprecate_l2_card,
            "create_l2_card": create_l2_card,
        })

    def __init__(self, llm_client, knowledge, domain_nodes: list[dict] | None = None):
        super().__init__(llm_client, logger)
        self._knowledge = knowledge
        self._nodes = domain_nodes or L2_DOMAIN_NODES

    def _build_system_prompt(self, instruction: str, meta: str,
                              static_context: str = "") -> str:
        extra = f"\n{static_context}\n" if static_context else ""
        return (
            f"你是 L2 层的认知 Agent。\n"
            f"{instruction}\n\n"
            f"[Meta]\n{meta}\n"
            f"{extra}"
        )

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

    def stage1(self, query: str, meta: str, state: dict,
               selected_nodes: list[dict]) -> dict:
        """Decompose: filter cards from selected nodes, decide L3 delegation.

        Lower layer: L3 — matches and executes skills per L2's task description.
        """
        cards = self._get_cards_for_nodes(selected_nodes)
        node_scores = {n.get("name", ""): n.get("score", 0) for n in selected_nodes}
        cards_text = self._format_cards_with_relevance(cards, node_scores) if cards else "（无相关卡片）"

        current = state.get("current", "")
        is_consolidation = "l2_output_format" in state
        filtered_meta = self._filter_meta_for_layer(meta, "l2") if is_consolidation else meta
        instruction = (
            "你的核心任务是完成上层 query，Meta 提供任务整体背景。\n"
            "你的局部任务是思考：核心任务怎么完成、还差什么要素。\n\n"
            "L3 层职责：根据具体任务执行标准化流程操作，管理一组 SKILL.md 技能。\n"
            "需要 L3 时输出 call_l3=true 和 l3_task（一句话任务描述）；否则 call_l3=false。\n\n"
            "示例：手牌K，对手翻牌前加注 → call_l3=true, l3_task=翻牌前持有K时是否加注。\n"
            "注意：你负责任务的部分执行和拆解下发，不做最终决策。"
        )
        system = self._build_system_prompt(instruction, filtered_meta)
        user = (
            f"[上层查询]\n{query}\n\n"
            f"[学习数据]\n{self._build_learning_section(state)}\n\n"
            f"[知识卡片 ({len(cards)} 张)]\n{cards_text}"
        ) if state.get("l1_output_format") else (
            f"[上层查询]\n{query}\n\n"
            f"[当前局面]\n{current}\n\n"
            f"[知识卡片 ({len(cards)} 张)]\n{cards_text}"
        )
        return self._call_llm(system, user, schema=self.STAGE1_SCHEMA)

    def stage2(self, query: str, meta: str, state: dict,
               selected_nodes: list[dict], stage1_result: dict,
               l3_skills: list[dict] | None = None,
               l3_result: dict | None = None) -> dict:
        """Integrate: combine cards + L3 skills → final NOTIFY reply.
        Only sees L3's result + reasoning, not L3's modifications.
        """
        l2_fmt = state.get("l2_output_format")
        filtered_meta2 = self._filter_meta_for_layer(meta, "l2") if l2_fmt else meta

        cards = self._get_cards_for_nodes(selected_nodes)
        node_scores = {n.get("name", ""): n.get("score", 0) for n in selected_nodes}
        cards_text = self._format_cards_with_relevance(cards, node_scores) if cards else "（无相关卡片）"

        skills = l3_skills or []
        l3 = l3_result or {}
        l3_reply = l3.get("result", "")
        l3_reasoning = l3.get("reasoning", "")
        parts = []
        if l3_reply:
            parts.append(f"L3执行结果: {l3_reply}")
        if l3_reasoning:
            parts.append(f"L3推理: {l3_reasoning}")
        if skills:
            skill_names = ", ".join(s.get("name", "") for s in skills)
            parts.append(f"可用技能: {skill_names}")
        l3_text = "\n".join(parts) if parts else "（L3 未返回信息）"

        instruction = (
            "你的职责：基于上层拆解的任务和筛选出的知识卡片，整合 L3 返回的执行结果，"
            "给出最终答复。"
        )
        if l2_fmt:
            instruction += (
                "\n\n【整理任务】你只负责 L2 知识卡片（KnowledgeCard）的修改。"
                "不要修改 L1 行为准则或 L3 技能。"
                "使用工具 deprecate_l2_card / create_l2_card 记录修改。"
            )
        system = self._build_system_prompt(instruction, filtered_meta2)

        if l2_fmt:
            user = (
                f"[上层查询]\n{query}\n\n"
                f"[学习数据]\n{self._build_learning_section(state)}\n\n"
                f"[知识卡片 ({len(cards)} 张)]\n{cards_text}\n\n"
                f"[L3 返回]\n{l3_text}\n\n"
                f"[Stage1 决策]\n"
                f"call_l3: {stage1_result.get('call_l3', False)}\n"
                f"l3_task: {stage1_result.get('l3_task', '')}"
            )
            self._setup_l2_consolidation()
            tools = self._L2_CONSOLIDATION_TOOLS
            schema = None
        else:
            current = state.get("current", "")
            user = (
                f"[上层查询]\n{query}\n\n"
                f"[当前局面]\n{current}\n\n"
                f"[知识卡片 ({len(cards)} 张)]\n{cards_text}\n\n"
                f"[L3 返回]\n{l3_text}"
            )

        return self._call_llm(system, user,
                              schema=None if l2_fmt else self.STAGE2_SCHEMA,
                              tools=tools if l2_fmt else None, layer="l2")

    def _get_cards_for_nodes(self, nodes: list[dict]) -> list:
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

    Overrides query() to drive V-structure:
      Stage1 (node selection) → Stage2 (card filter + L3 decision)
      → enrich obs.state → propagate to L3.

    NOTIFY goes to both upper layer (L1) and Executor.
    TODO: Content may differ per target.
    """

    def __init__(self, knowledge, downstream: LayerManager | None = None,
                 upward=None, downward=None, auxiliary_llm=None,
                 domain_registry=None):
        super().__init__("l2", downstream, upward=upward, downward=downward)
        self._knowledge = knowledge
        self._agent = L2Agent(auxiliary_llm, knowledge) if auxiliary_llm else None
        self._registry = domain_registry
        self._result: dict | None = None
        self._cards: list[dict] = []   # E3: local storage, not obs.state

    def process(self, data: Any) -> dict:
        return {"status": "ok", "layer": self.name}

    def query(self, msg: LayerMessage | Any, trace_id: str = "") -> None:
        if isinstance(msg, LayerMessage):
            data = self._upward.receive(msg)
            if not trace_id:
                trace_id = msg.trace_id
        else:
            data = msg

        # E3: payload is a composite dict {obs, query, selected_nodes} or TaskObservation directly
        if isinstance(data, dict):
            obs = data.get("obs")
            query: str = data.get("query", "")
            selected_nodes: list[dict] = data.get("selected_nodes", [])
        else:
            obs = data
            query = ""
            selected_nodes = []
        meta = obs.meta if obs else ""

        if self._agent is None:
            logger.warning("L2Agent not initialized (no auxiliary_llm), skipping")
            self._cards = []
            self._result = {"reply": "", "cards": [], "reasoning": "no agent"}
            self._propagate(obs, trace_id)
            return

        # ═══ Stage 1: Card Filter + L3 Decision (Decompose) ═══
        logger.debug("  ═══ L2 Stage 1 — Card Filter ═══")
        stage1_result = self._agent.stage1(query, meta, obs.state, selected_nodes)
        if not isinstance(stage1_result, dict):
            logger.warning("L2 stage1 returned non-dict: %s", type(stage1_result))
            stage1_result = {"cards": [], "call_l3": False, "l3_task": "",
                             "reasoning": "invalid response format"}
        logger.debug("  ── Stage 1 结果 ──")
        logger.debug("    call_l3: %s", stage1_result.get("call_l3"))
        logger.debug("    cards: %d 张", len(stage1_result.get("cards", [])))
        logger.debug("    l3_task: %s",
                     str(stage1_result.get("l3_task", ""))[:120])
        logger.debug("")

        # E3: store cards locally, not in obs.state
        # Try registry-based card retrieval first
        if self._registry and obs:
            session = obs.session if obs else {}
            task_domain = session.get("domain", "general")
            primary_ids = self._registry.get_primary_items("l2", task_domain)
            explore_ids = self._registry.get_explore_items("l2", task_domain, threshold=0.5)
            all_ids = list(dict.fromkeys(primary_ids + explore_ids))
            reg_cards = self._build_cards_from_ids(all_ids)
            if reg_cards:
                self._cards = reg_cards
            else:
                self._cards = self._build_cards(selected_nodes)
        else:
            self._cards = self._build_cards(selected_nodes)

        # Propagate to L3 only when needed
        # TODO: When L2→L3 multi-round is enabled, loop here to refine l3_task
        # based on L3's output (similar to L1 MAX_LOOPS). Currently single-shot.
        call_l3 = stage1_result.get("call_l3", False)
        if call_l3:
            l3_task = stage1_result.get("l3_task", "")
            self._propagate(obs, trace_id, l3_task=l3_task)

        # E3: L3 skills from downstream manager, not obs.state
        l3_skills = getattr(self._downstream, '_matched_skills', []) if (self._downstream and call_l3) else []
        l3_result = self._downstream._result if (self._downstream and call_l3) else {}

        # ═══ Stage 2: Notify — integrate L3 + final reply (Integrate) ═══
        logger.debug("  ═══ L2 Stage 2 — Notify ═══")
        final = self._agent.stage2(query, meta, obs.state, selected_nodes,
                                    stage1_result, l3_skills=l3_skills,
                                    l3_result=l3_result)
        logger.debug("  ── Stage 2 结果 ──")
        logger.debug("    reply: %s", str(final.get("reply", ""))[:200])
        logger.debug("    cards: %d 张", len(final.get("cards", [])))
        logger.debug("    reasoning: %s", str(final.get("reasoning", ""))[:200])
        logger.debug("")

        # NOTIFY enrichment: cards_used as summary
        cards = final.pop("cards", [])  # remove full cards from notify
        final["cards_used"] = [str(c)[:100] for c in cards[:5]]

        self._result = final

    def _propagate(self, obs, trace_id: str, l3_task: str = "") -> None:
        if self._downstream:
            q_msg = self._downward.wrap_query(
                payload={"obs": obs, "l3_task": l3_task}, source=self.name,
                target=self._downstream.name, trace_id=trace_id,
            )
            self._downstream.query(q_msg, trace_id)

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
                "confidence": c.confidence,
                "activation": c.activation,
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
                        "confidence": c.confidence,
                        "activation": c.activation,
                        "domain": c.domain.path,
                    })
                    break
        return cards

    def notify(self) -> Any:
        if self._result:
            result = dict(self._result)
            if self._agent:
                mods = self._agent.get_pending_mods()
                if mods:
                    result["l2_modifications"] = mods
            return result
        return {"status": "ok", "layer": self.name}


