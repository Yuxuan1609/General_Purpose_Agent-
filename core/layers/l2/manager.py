from __future__ import annotations
import logging
from typing import Any
from core.task import Domain
from core.types import TaskObservation
from core.layers.base import LayerManager, LayerAgent, _indent
from core.layers.comm import AgentPacket
from core.layer_message import LayerMessage

logger = logging.getLogger("l2")

# Domain nodes — manually seeded. Each node represents a semantic domain
# with name (matching L2 card domain path) and a ~100-char description.
# TODO: Unified node design (schema, persistence, auto-generation) to be
#       finalized in a future session. For now, manually maintained.
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
        "nodes": [
            {"name": "string (domain path)", "score": "float (0-1)", "reason": "string"}
        ]
    }
    STAGE2_SCHEMA = {
        "cards": ["string (筛选后的卡片内容)"],
        "call_l3": "boolean",
        "l3_task": "string (需要L3执行的任务，call_l3=false时可为空)",
        "reasoning": "string (推理过程)",
    }
    STAGE3_SCHEMA = {
        "reply": "string (对L1查询的最终回复)",
        "cards": ["string (精选知识卡片内容)"],
        "reasoning": "string (综合推理过程)",
    }

    def __init__(self, llm_client, knowledge, domain_nodes: list[dict] | None = None):
        super().__init__(llm_client, logger)
        self._knowledge = knowledge
        self._nodes = domain_nodes or L2_DOMAIN_NODES

    def stage1(self, query: str, meta: str, state: dict) -> list[dict]:
        current = state.get("current", "")
        nodes_text = "\n".join(
            f"{i + 1}. {n['name']}\n   {n['description']}"
            for i, n in enumerate(self._nodes)
        )
        system = (
            "你是 L2 层的认知 Agent，负责知识检索。\n"
            "根据上层查询，从领域节点中选出最相关的 1-5 个节点，给出名称、相关度分数和选择理由。\n\n"
            f"[游戏规则]\n{meta}"
        )
        user = (
            f"[上层查询]\n{query}\n\n"
            f"[当前局面]\n{current}\n\n"
            f"[领域节点]\n{nodes_text}"
        )
        result = self._call_llm(system, user, schema=self.STAGE1_SCHEMA)
        return result.get("nodes", [])

    def stage2(self, query: str, meta: str, state: dict,
               selected_nodes: list[dict]) -> dict:
        cards = self._get_cards_for_nodes(selected_nodes)
        cards_text = "\n".join(
            f"[{c.domain.path}] {c.content}"
            for c in cards
        ) if cards else "（无相关卡片）"

        current = state.get("current", "")
        system = (
            "你是 L2 层的认知 Agent，负责知识筛选和下层调度。\n"
            "根据知识卡片和上层查询，筛选最相关的卡片（最多15张），判断是否需要 L3 层技能支持。\n\n"
            f"[游戏规则]\n{meta}"
        )
        user = (
            f"[上层查询]\n{query}\n\n"
            f"[当前局面]\n{current}\n\n"
            f"[知识卡片 ({len(cards)} 张)]\n{cards_text}"
        )
        return self._call_llm(system, user, schema=self.STAGE2_SCHEMA)

    def stage3(self, query: str, meta: str, state: dict,
               selected_nodes: list[dict], stage2_result: dict) -> dict:
        """Final NOTIFY: integrate L3 response + all prior context.

        Same pattern as L1's stage2 notify output.
        """
        cards = self._get_cards_for_nodes(selected_nodes)
        cards_text = "\n".join(
            f"[{c.domain.path}] {c.content}"
            for c in cards
        ) if cards else "（无相关卡片）"

        current = state.get("current", "")
        l3_skills = state.get("l3_skills", [])
        skills_text = "\n".join(
            f"[{s.get('name', '')}] {s.get('content', '')}"
            for s in l3_skills
        ) if l3_skills else "（L3 未返回信息）"

        system = (
            "你是 L2 层的认知 Agent，负责最终知识整合与回复。\n"
            "整合上层查询、知识卡片和 L3 层技能，给出最终回复。\n\n"
            f"[游戏规则]\n{meta}"
        )
        user = (
            f"[上层查询]\n{query}\n\n"
            f"[当前局面]\n{current}\n\n"
            f"[知识卡片 ({len(cards)} 张)]\n{cards_text}\n\n"
            f"[L3 技能]\n{skills_text}\n\n"
            f"[Stage2 分析]\n"
            f"call_l3: {stage2_result.get('call_l3', False)}\n"
            f"reasoning: {stage2_result.get('reasoning', '')}"
        )
        return self._call_llm(system, user, schema=self.STAGE3_SCHEMA)

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


class L2Manager(LayerManager):
    """L2 Manager — wraps FlexibleKnowledge + L2Agent.

    Overrides query() to drive V-structure:
      Stage1 (node selection) → Stage2 (card filter + L3 decision)
      → enrich obs.state → propagate to L3.

    NOTIFY goes to both upper layer (L1) and Executor.
    TODO: Content may differ per target.
    """

    def __init__(self, knowledge, downstream: LayerManager | None = None,
                 upward=None, downward=None, auxiliary_llm=None):
        super().__init__("l2", downstream, upward=upward, downward=downward)
        self._knowledge = knowledge
        self._agent = L2Agent(auxiliary_llm, knowledge) if auxiliary_llm else None
        self._result: dict | None = None

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
        query = obs.state.get("l1_query", obs.meta)
        meta = obs.meta

        if self._agent is None:
            logger.warning("L2Agent not initialized (no auxiliary_llm), skipping")
            obs.state["l2_cards"] = []
            self._result = {"reply": "", "cards": [], "reasoning": "no agent"}
            self._propagate(obs, trace_id)
            return

        # ═══ Stage 1: Node Selection ═══
        logger.debug("  ═══ L2 Stage 1 — Node Selection ═══")
        selected_nodes = self._agent.stage1(query, meta, obs.state)
        logger.debug("  ── Stage 1 结果 ──")
        for n in selected_nodes:
            logger.debug("    %s (score=%s)", n.get("name"), n.get("score"))
        logger.debug("")
        # TODO: Graph expansion — via KnowledgeGraph.spread_activation()

        # ═══ Stage 2: Card Filter + L3 Decision ═══
        logger.debug("  ═══ L2 Stage 2 — Card Filter ═══")
        stage2_result = self._agent.stage2(query, meta, obs.state, selected_nodes)
        logger.debug("  ── Stage 2 结果 ──")
        logger.debug("    call_l3: %s", stage2_result.get("call_l3"))
        logger.debug("    cards: %d 张", len(stage2_result.get("cards", [])))
        logger.debug("    l3_task: %s",
                     str(stage2_result.get("l3_task", ""))[:120])
        logger.debug("")

        # Enrich state for Executor
        self._enrich_cards(obs, selected_nodes)

        # Propagate to L3 (stub — enriches l3_skills)
        self._propagate(obs, trace_id)

        # ═══ Stage 3: Notify — integrate L3 + final reply ═══
        logger.debug("  ═══ L2 Stage 3 — Notify ═══")
        final = self._agent.stage3(query, meta, obs.state, selected_nodes, stage2_result)
        logger.debug("  ── Stage 3 结果 ──")
        logger.debug("    reply: %s", str(final.get("reply", ""))[:200])
        logger.debug("    cards: %d 张", len(final.get("cards", [])))
        logger.debug("    reasoning: %s", str(final.get("reasoning", ""))[:200])
        logger.debug("")

        obs.state["l2_result"] = final
        self._result = final

    def _propagate(self, obs: TaskObservation, trace_id: str) -> None:
        if self._downstream:
            q_msg = self._downward.wrap_query(
                payload=obs, source=self.name,
                target=self._downstream.name, trace_id=trace_id,
            )
            self._downstream.query(q_msg, trace_id)

    def _enrich_cards(self, obs: TaskObservation, selected_nodes: list[dict]) -> None:
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
        obs.state["l2_cards"] = [
            {
                "content": c.content,
                "confidence": c.confidence,
                "activation": c.activation,
                "domain": c.domain.path,
            }
            for c in cards
        ]

    def notify(self) -> Any:
        if self._result:
            return self._result
        return {"status": "ok", "layer": self.name}

    def apply_update(self, key: str, value: Any) -> None:
        """Phase 2: Boost/penalize knowledge cards or add new ones."""
        card_id = value.get("card_id", "") if isinstance(value, dict) else str(value)
        if key == "boost_card":
            for c in self._knowledge.cards:
                if c.id == card_id:
                    c.boost()
                    logger.info("L2 card %s boosted (conf=%.2f)", card_id, c.confidence)
                    return
        elif key == "penalize_card":
            for c in self._knowledge.cards:
                if c.id == card_id:
                    c.penalize()
                    logger.info("L2 card %s penalized (conf=%.2f)", card_id, c.confidence)
                    return
        elif key == "add_card" and isinstance(value, dict):
            from core.task import Domain
            domain_path = value.get("domain", "general")
            self._knowledge.add_card(
                content=value.get("content", ""),
                domain=Domain(domain_path, "specific"),
                confidence=value.get("confidence", 0.5),
                source="reflect",
            )
            logger.info("L2 card added via reflect")

    def _enrich_cards(self, obs: TaskObservation, selected_nodes: list[dict]) -> None:
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
        obs.state["l2_cards"] = [
            {
                "content": c.content,
                "confidence": c.confidence,
                "activation": c.activation,
                "domain": c.domain.path,
            }
            for c in cards
        ]

    def notify(self) -> Any:
        # TODO: NOTIFY to L1 (full reasoning+cards) vs Executor (structured list)
        #       may differ. Currently returns same content.
        if self._result:
            return self._result
        return {"status": "ok", "layer": self.name}
