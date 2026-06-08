from __future__ import annotations
import json
import logging
from typing import Any
from core.task import Domain
from core.types import TaskObservation
from core.layers.base import LayerManager, LayerAgent, DictInjector
from core.layer_message import LayerMessage

logger = logging.getLogger("l3")


def _strip_frontmatter(content: str) -> str:
    """Remove YAML frontmatter (--- ... ---) from skill content for display."""
    if content.startswith("---"):
        parts = content.split("---", 2)
        if len(parts) >= 3:
            return parts[2].lstrip("\n")
        return content.lstrip("-").lstrip("\n")
    return content

# TODO: Future card-level skill matching — use L2 knowledge cards to refine
#       skill selection beyond simple domain match. Currently domain-based only.
#       See: L2 Domain Graph design (spec Section 9).
# TODO: Future L4 dispatch — L3 sends task to L4 (static knowledge) for
#       additional reference lookup. Reserved for later phases.


class L3Agent(LayerAgent):
    """L3 LLM Agent — skill-based task execution.

    Currently single-stage (combining find + execute per user's spec).
    TODO: Future split into stage1 (find relevant skills) + stage2 (execute).

    Input: task context + matched skills
    Output: {skills_used, result, reasoning}
    """

    EXECUTE_SCHEMA = {
        "skills_used": ["string (本次使用的技能名称)"],
        "result": "string (基于技能的任务执行结果)",
        "reasoning": "string (技能选择和执行的推理过程)",
    }

    # Learning/consolidation — tool call instead of @modify text
    _L3_CONSOLIDATION_TOOLS: list[dict] = [
        {"type": "function", "function": {
            "name": "deprecate_l3_skill",
            "description": "删除一个 L3 技能",
            "parameters": {"type": "object", "properties": {
                "skill_name": {"type": "string", "description": "技能名称"},
                "reason": {"type": "string", "description": "删除理由"},
            }, "required": ["skill_name", "reason"]},
        }},
        {"type": "function", "function": {
            "name": "create_l3_skill",
            "description": "创建一个 L3 技能",
            "parameters": {"type": "object", "properties": {
                "name": {"type": "string", "description": "技能名称"},
                "content": {"type": "string", "description": "完整 SKILL.md 内容"},
                "domain": {"type": "string", "description": "所属 domain"},
                "reason": {"type": "string", "description": "创建理由"},
            }, "required": ["name", "content", "domain", "reason"]},
        }},
    ]

    def _setup_l3_consolidation(self):
        agent = self

        def deprecate_l3_skill(args: dict) -> str:
            agent._pending_mods.append({
                "type": "deprecate", "target": args["skill_name"],
                "reason": args["reason"], "layer": "l3",
            })
            return f"已记录: 删除 {args['skill_name']}"

        def create_l3_skill(args: dict) -> str:
            agent._pending_mods.append({
                "type": "create", "target": args["name"], "layer": "l3",
                "content": args["content"], "domain": args["domain"],
                "reason": args["reason"],
            })
            return f"已记录: 创建 {args['name']}"

        self._injector = DictInjector({
            "deprecate_l3_skill": deprecate_l3_skill,
            "create_l3_skill": create_l3_skill,
        })

    def __init__(self, llm_client):
        super().__init__(llm_client, logger)

    def _build_system_prompt(self, instruction: str, meta: str) -> str:
        return (
            f"你是 L3 层的认知 Agent。\n"
            f"{instruction}\n\n"
            f"[Meta]\n{meta}"
        )

    def execute(self, meta: str, state: dict,
                matched_skills: list[dict] | None = None) -> dict:
        l3_fmt = state.get("l3_output_format") if state else None
        if l3_fmt:
            meta = self._filter_meta_for_layer(meta, "l3")

        current = state.get("current", "") if state else ""
        skills = matched_skills or []
        skills_text = "\n".join(
            f"## {s.get('name', '')}: {s.get('description', '')}"
            f"\n{_strip_frontmatter(s.get('content', '')[:800])}"
            for s in skills
        ) if skills else "（无匹配技能）"

        learning_data = ""
        if l3_fmt:
            units = state.get("learning_units", []) if state else []
            if isinstance(units, list) and units:
                recs = []
                for u in units:
                    l3_r = u.get("l3_reasoning", "")
                    if l3_r:
                        recs.append(f"[{u.get('index','?')}] L3: {l3_r[:200]}")
                if recs:
                    learning_data = f"[学习数据]\n" + "\n".join(recs) + "\n\n"
        fb = (state or {}).get("feedback", "")
        l3_fb = (state or {}).get("l3_feedback", "")
        if l3_fb:
            fb = f"{fb}\n{l3_fb}" if fb else l3_fb
        fb_section = f"[L3 修改结果确认]\n{fb}\n\n" if fb else ""

        instruction = (
            "你的核心任务是完成 L2 下发的 l3_task，Meta 提供任务整体背景。\n"
            "选择相关技能并基于技能内容执行任务。"
        )
        if l3_fmt:
            instruction += (
                "\n\n【整理任务】你只负责 L3 技能（Skill）的修改。"
                "不要修改 L1 行为准则或 L2 知识卡片。"
                "使用工具 deprecate_l3_skill / create_l3_skill 记录修改。"
            )
        system = self._build_system_prompt(instruction, meta)
        user = (
            f"{fb_section}"
            f"{learning_data}"
            f"[当前局面]\n{current}\n\n"
            f"[可用技能]\n{skills_text}"
        )

        if l3_fmt:
            self._setup_l3_consolidation()
            tools = self._L3_CONSOLIDATION_TOOLS
            schema = None
        else:
            tools = None
            schema = self.EXECUTE_SCHEMA
        return self._call_llm(system, user, schema=schema, tools=tools, layer="l3")


class L3Manager(LayerManager):
    """L3 Manager — wraps SkillLayer + L3Agent.

    Phase 1: domain-based deterministic skill matching → load SKILL.md.
    Phase 2: L3Agent(LLM) analyzes matched skills → selects + executes.
    TODO: Future card-level matching + L4 dispatch.

    Overrides query() to add LLM agent stage after deterministic match.
    """

    def __init__(self, skill_layer, downstream: LayerManager | None = None,
                 upward=None, downward=None, auxiliary_llm=None,
                 domain_registry=None):
        super().__init__("l3", downstream, upward=upward, downward=downward)
        self._skill_layer = skill_layer
        self._agent = L3Agent(auxiliary_llm) if auxiliary_llm else None
        self._registry = domain_registry
        self._matched: list[str] = []
        self._matched_skills: list[dict] = []  # E3: local storage, not obs.state
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

        # E3: payload is a composite dict {obs, ...} or TaskObservation directly
        if isinstance(data, dict):
            obs = data.get("obs")
            l3_task = data.get("l3_task", "")
        else:
            obs = data
            l3_task = ""
        session = obs.session if obs else {}
        domain_path = session.get("domain", "general")

        # Deterministic: domain-based skill matching
        # Registry-based skill matching
        if self._registry:
            skill_ids = self._registry.get_primary_items("l3", domain_path)
            self._matched_skills = self._skill_layer.get_skills_by_ids(skill_ids)
            self._matched = [s["name"] for s in self._matched_skills]
        else:
            # Fallback to old domain-based matching
            try:
                domain = Domain(domain_path, "specific")
            except Exception:
                domain = Domain("general", "general")

            matched = self._skill_layer.match(domain)
            self._matched = [s.name for s in matched]
            self._matched_skills = []
            for s in matched:
                content = ""
                if s.skill_dir:
                    skill_file = s.skill_dir / "SKILL.md"
                    if skill_file.exists():
                        content = skill_file.read_text(encoding="utf-8")
                self._matched_skills.append({
                    "name": s.name, "description": s.description,
                    "domain": s.domain.path, "content": content,
                })
        logger.debug("── L3 (match) ──")
        logger.debug("  domain: %s → %d skills", domain_path, len(self._matched))
        for i, name in enumerate(self._matched):
            desc = next((s.get("description", "") for s in self._matched_skills if s.get("name") == name), "")
            logger.debug("    [skill %d] %s | %s", i + 1, name, desc)

        # LLM Agent: select relevant skills + execute
        if self._agent:
            logger.debug("── L3 Agent ──")
            meta = l3_task or (obs.meta if obs else "")
            result = self._agent.execute(meta, obs.state if obs else {},
                                         matched_skills=self._matched_skills)
            logger.debug("  skills_used: %s", result.get("skills_used"))
            logger.debug("  result: %s", str(result.get("result", ""))[:200])
            self._result = result

        # Propagate downstream (L4, reserved)
        # TODO: When L3→L4 multi-round is enabled, loop here for iterative
        # query-refinement (same pattern as L1 MAX_LOOPS). Currently single-shot.
        if self._downstream:
            q_msg = self._downward.wrap_query(
                payload={"obs": obs}, source=self.name,
                target=self._downstream.name, trace_id=trace_id,
            )
            self._downstream.query(q_msg, trace_id)

    def notify(self) -> Any:
        result: dict = {"status": "ok", "layer": "l3", "skills_matched": len(self._matched)}
        if self._result:
            result.update({
                "skills_used": self._result.get("skills_used", []),
                "result": self._result.get("result", ""),
                "reasoning": self._result.get("reasoning", ""),
            })
        if self._agent:
            mods = self._agent.get_pending_mods()
            if mods:
                result["l3_modifications"] = mods
        return result
