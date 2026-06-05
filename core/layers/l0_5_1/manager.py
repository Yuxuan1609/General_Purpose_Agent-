from __future__ import annotations
import json
import logging
from typing import Any
from core.types import TaskObservation
from core.layers.base import LayerManager, LayerAgent, _indent
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

    STAGE1_SCHEMA = {
        "query": "string (需要下层根据领域知识完成的任务，可附上基于【行为准则】的完成建议)",
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

    # Learning task extension: schema for l1_modifications field
    _L1_MOD_SCHEMA = {
        "l1_modifications": [
            {"target": "l1/<rule_id> (target for modify/deprecate; new id for create)",
             "type": "update | create | deprecate",
             "payload": {
                 "content": "string (full rule text, ~1-2 sentences matching existing L1 rule granularity)",
                 "reason": "string (why, citing execution record evidence)",
             }},
        ],
    }

    def __init__(self, llm_client, philosophy):
        super().__init__(llm_client, logger)
        self._philosophy = philosophy

    def _build_system_prompt(self, instruction: str, meta: str,
                              static_context: str = "") -> str:
        """Build system prompt: task meta + behavior rules + optional static context + instruction."""
        rules = self._philosophy.all_rules()
        rules_text = "\n".join(f"- {r.content}" for r in rules) if rules else "（无）"
        extra = f"\n{static_context}\n" if static_context else ""
        return (
            f"你是 L1 层的认知 Agent。\n\n"
            f"{meta}\n\n"
            f"【行为准则】\n{rules_text}\n\n"
            f"你必须遵守以上【行为准则】并基于行为准则进行思考。\n"
            f"{extra}"
            f"{instruction}"
        )

    def _build_user_context(self, state: dict) -> str:
        """Build user prompt body: current state + history (dynamic per-step).

        For learning tasks, current state is already in meta/system prompt,
        so skip to avoid duplication. Learning context comes from learning_units.
        """
        current = state.get("current", "")
        history = state.get("history", "")
        is_learning = "l1_output_format" in state

        if is_learning:
            units = state.get("learning_units", [])
            unit_count = len(units) if isinstance(units, list) else 0
            return f"[学习数据] {unit_count} 条记录（详见系统提示词）\n\n[对局历史]\n{history or '（无）'}"
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
            f"{i + 1}. {n['name']}\n   {n['description']}"
            for i, n in enumerate(nodes)
        )
        instruction = (
            "你的职责：基于【行为准则】将任务拆解为下层需要协助的具体子任务。"
            "从领域节点中选出最相关的 1-5 个节点，并给出清晰的语义查询交给 L2 层检索知识卡片。"
            "如果不需要领域知识，返回空的 domain_nodes（[]）。"
        )
        system = self._build_system_prompt(
            instruction, meta,
            static_context=f"[领域节点]\n{nodes_text}" if nodes_text else "",
        )
        user = self._build_user_context(state)
        result = self._call_llm(system, user, schema=self.STAGE1_SCHEMA)
        return result

    def stage2(self, meta: str, state: dict,
               l2_cards: list[dict] | None = None,
               l2_result: dict | None = None) -> dict:
        """Stage2: integrate L2 knowledge and produce final decision.

        Accepts L2 results as explicit params (E3: no shared mutable state).
        Detects learning tasks via state.l1_output_format.
        """
        l1_fmt = state.get("l1_output_format")

        instruction = (
            "你的职责：基于【行为准则】整合下层返回的知识信息，做出最终决策。"
            "在 rules_used 中列出本次推理中实际引用到的行为准则的 id。"
        )
        system = self._build_system_prompt(instruction, meta)

        cards = l2_cards or []
        cards_text = "\n".join(
            f"- [{c.get('domain', '')}] {c.get('content', '')}"
            for c in cards
        ) if cards else "（下层未返回信息）"

        user = f"{self._build_user_context(state)}\n\n[下层知识]\n{cards_text}"

        schema = self.STAGE2_SCHEMA
        if l1_fmt:
            schema = {**schema, **self._L1_MOD_SCHEMA}
        result = self._call_llm(system, user, schema=schema)

        # NOTIFY enrichment: rules actually used (from LLM)
        l2 = l2_result or {}
        result["l2_reply"] = str(l2.get("reply", ""))[:300]
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
                 domain_nodes: list[dict] | None = None):
        super().__init__("l0_5_1", downstream, upward=upward, downward=downward)
        self._meta = meta_driver
        self._philosophy = philosophy
        self._agent = L1Agent(auxiliary_llm, philosophy) if auxiliary_llm else None
        self._domain_nodes = domain_nodes or []
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
            stage1_result = self._agent.stage1(meta, obs.state,
                                                domain_nodes=self._domain_nodes)
            query_text = stage1_result.get("query", "")
            selected_nodes = stage1_result.get("domain_nodes", [])
            logger.debug("  query: %s", query_text)
            for n in selected_nodes:
                logger.debug("    node: %s (score=%s)", n.get("name"), n.get("score"))

            if self._downstream:
                # E3: pass data via LayerMessage payload, not obs.state mutation
                q_msg = self._downward.wrap_query(
                    payload={"obs": obs, "query": query_text,
                             "selected_nodes": selected_nodes},
                    source=self.name, target=self._downstream.name,
                    trace_id=trace_id,
                )
                self._downstream.query(q_msg, trace_id)

            # E3: read L2 results from downstream manager, not from obs.state
            l2_cards = getattr(self._downstream, '_cards', []) if self._downstream else []
            l2_result = self._downstream._result if self._downstream else {}

            logger.debug("── L1 Stage 2 [loop %d/%d] ──", loop, L1Agent.MAX_LOOPS)
            result = self._agent.stage2(meta, obs.state,
                                        l2_cards=l2_cards, l2_result=l2_result)
            logger.debug("  result: done=%s result=%s",
                         result.get("done"), str(result.get("result", ""))[:200])

            if result.get("done"):
                self._final_result = result
                return

        logger.warning("L1 max loops (%d) reached, force done", L1Agent.MAX_LOOPS)
        self._final_result = {"done": True, "result": "", "reasoning": "max loops exceeded"}

    def notify(self) -> Any:
        if self._final_result:
            return self._final_result
        return {"status": "ok", "layer": self.name}

    def apply_update(self, key: str, value: Any) -> None:
        """Phase 2: Apply L1 rule changes via MetaDriver validation → Philosophy.

        L0.5 rules (source='l0_5') are immutable constitution — only manually
        modifiable by user. L1 rules (source='l1') are mutable via reflection.
        """
        if key == "add_rule":
            content = value.get("content", "") if isinstance(value, dict) else str(value)
            if not content:
                return
            existing = [r.content for r in self._philosophy.all_rules()]
            is_valid, reason = self._meta.validate_l1_change(
                type("_Proposal", (), {"content": content})(), existing)
            if is_valid:
                self._philosophy.add_rule(content, created_by="reflect", source="l1")
                logger.info("L1 rule added: %s", content[:80])
            else:
                logger.warning("L1 rule rejected: %s", reason)
        elif key == "modify_rule":
            rule_id = value.get("rule_id", "")
            new_content = value.get("content", "")
            try:
                self._philosophy.modify_rule(rule_id, new_content)
                logger.info("L1 rule %s modified", rule_id)
            except ValueError as e:
                logger.warning("L1 rule modify failed: %s", e)
        elif key == "remove_rule":
            rule_id = value.get("rule_id", "") if isinstance(value, dict) else str(value)
            try:
                self._philosophy.remove_rule(rule_id)
                logger.info("L1 rule %s removed", rule_id)
            except ValueError as e:
                logger.warning("L1 rule remove failed: %s", e)
