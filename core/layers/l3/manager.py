from __future__ import annotations
import json
import logging
from typing import Any
from core.task import Domain
from core.types import TaskObservation
from core.layers.base import LayerManager, LayerAgent
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

    _L3_MOD_SCHEMA = {
        "l3_modifications": [
            {"target": "l3/<skill_name> (existing name for update/deprecate; new name for create)",
             "type": "update | create | deprecate",
             "payload": {
                 "content": "string (full SKILL.md: YAML frontmatter + markdown body)",
                 "reason": "string (why)",
                 "domain": "string (for create)",
             }},
        ],
    }

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
                    recs.append(f"[{u.get('index','?')}] {u.get('reasoning','')[:120]}")
                learning_data = f"[学习数据]\n" + "\n".join(recs) + "\n\n"

        instruction = (
            "你的核心任务是完成 L2 下发的 l3_task，Meta 提供任务整体背景。\n"
            "选择相关技能并基于技能内容执行任务。"
        )
        system = self._build_system_prompt(instruction, meta)
        user = (
            f"{learning_data}"
            f"[当前局面]\n{current}\n\n"
            f"[可用技能]\n{skills_text}"
        )

        schema = self.EXECUTE_SCHEMA
        if l3_fmt:
            schema = {**schema, **self._L3_MOD_SCHEMA}
        return self._call_llm(system, user, schema=schema)


class L3Manager(LayerManager):
    """L3 Manager — wraps SkillLayer + L3Agent.

    Phase 1: domain-based deterministic skill matching → load SKILL.md.
    Phase 2: L3Agent(LLM) analyzes matched skills → selects + executes.
    TODO: Future card-level matching + L4 dispatch.

    Overrides query() to add LLM agent stage after deterministic match.
    """

    def __init__(self, skill_layer, downstream: LayerManager | None = None,
                 upward=None, downward=None, auxiliary_llm=None):
        super().__init__("l3", downstream, upward=upward, downward=downward)
        self._skill_layer = skill_layer
        self._agent = L3Agent(auxiliary_llm) if auxiliary_llm else None
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
        logger.debug("  domain: %s → %d skills", domain_path, len(matched))
        for i, s in enumerate(matched):
            logger.debug("    [skill %d] %s | %s", i + 1, s.name, s.description)

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
        if self._downstream:
            q_msg = self._downward.wrap_query(
                payload={"obs": obs}, source=self.name,
                target=self._downstream.name, trace_id=trace_id,
            )
            self._downstream.query(q_msg, trace_id)

    def notify(self) -> Any:
        if self._result:
            return {
                "skills_matched": len(self._matched),
                "skills_used": self._result.get("skills_used", []),
                "result": self._result.get("result", ""),
                "reasoning": self._result.get("reasoning", ""),
            }
        return {
            "status": "ok",
            "layer": "l3",
            "skills_matched": len(self._matched),
        }

    def apply_update(self, key: str, value: Any) -> None:
        """Phase 2: Manage L3 skills.

        Supported actions: add_skill, update_skill, remove_skill.

        TODO: Future L3 skills may bind to L2 knowledge cards (card-level
        skill association). When a skill is created from specific knowledge
        cards, the skill stores source_card_ids for traceability. Not yet
        implemented — skills currently operate independently.
        """
        if isinstance(value, dict):
            skill_name = value.get("name", "")
        else:
            skill_name = str(value)
        if key == "add_skill" and isinstance(value, dict):
            try:
                domain_path = value.get("domain", "general")
                from core.task import Domain
                self._skill_layer.create_skill(
                    name=skill_name,
                    content=value.get("content", ""),
                    domain=Domain(domain_path, "specific"),
                    created_by="reflect",
                )
                logger.info("L3 skill %s added via reflect", skill_name)
            except Exception as e:
                logger.warning("L3 skill add failed: %s", e)
        elif key == "update_skill" and isinstance(value, dict):
            try:
                self._skill_layer.edit_skill(skill_name, value.get("content", ""))
                logger.info("L3 skill %s updated via reflect", skill_name)
            except Exception as e:
                logger.warning("L3 skill update failed: %s", e)
        elif key == "remove_skill":
            try:
                self._skill_layer.delete_skill(skill_name)
                logger.info("L3 skill %s removed via reflect", skill_name)
            except Exception as e:
                logger.warning("L3 skill remove failed: %s", e)
