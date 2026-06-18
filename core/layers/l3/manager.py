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
    
    Input: task context + matched skills
    Output: {skills_used, result, reasoning}
    """

    L3_DECISION_SCHEMA = {
        "type": "object",
        "properties": {
            "done": {"type": "boolean"},
            "result": {"type": "string", "description": "技能执行结果"},
            "skills_used": {"type": "array", "items": {"type": "string"}},
            "reasoning": {"type": "string"},
        },
        "required": ["done", "reasoning"],
    }



    def __init__(self, llm_client, skill_layer=None, domain_registry=None):
        super().__init__(llm_client, logger)
        self._skill_layer = skill_layer
        self._registry = domain_registry

    def _build_system_prompt(self, instruction: str, meta: str) -> str:
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
            f"- L2：管理概率性知识卡片，负责相关知识检索与技能调度。可调用 terminal/web_search/read_file/grep/tool_proposal 等工具。\n"
            f"- L3（你）：管理 SKILL.md 技能，负责标准化流程执行。可调用 terminal/web_search/read_file/grep/tool_proposal 等工具。\n\n"
            f"## 领域边界\n"
            f"你只管理 L3 技能（Skills / SKILL.md）。\n"
            f"不要修改 L1 的行为准则或 L2 的知识卡片。\n\n"
            f"## 指令\n{instruction}\n\n"
            f"{tool_rules}\n"
            f"[Meta]\n{meta}"
        )

    def decide(self, meta: str, state: dict, context: dict,
               tools: list[dict] | None = None, layer: str = "l3") -> dict:
        """Single decision step for L3 while loop.

        Two capture tools:
          - l3_continue: request more tool usage / thinking (done=false)
          - l3_report: deliver execution result (done=true)
        Consolidation mode uses l3_report only.
        """
        l3_fmt = state.get("l3_output_format")
        matched_skills = context.get("matched_skills", [])
        l3_task = context.get("l3_task", "")

        current = state.get("current", "")
        skills_text = "\n".join(
            f"## {s.get('name', '')}: {s.get('description', '')}"
            f"\n  used={s.get('use_count', 0)} last={str(s.get('last_used', ''))[:10]}"
            f" useful=+{s.get('usefulness', 0)} mislead={s.get('misleading', 0)}"
            f"{chr(10) + '  comment: ' + s['comment'] if s.get('comment') else ''}"
            f"\n{_strip_frontmatter(s.get('content', '')[:800])}"
            for s in matched_skills
        ) if matched_skills else "（无匹配技能）"

        learning_data = ""
        if l3_fmt:
            units = state.get("learning_units", [])
            if isinstance(units, list) and units:
                recs = []
                for u in units:
                    l3_r = u.get("l3_reasoning", "")
                    if l3_r:
                        recs.append(f"[{u.get('index','?')}] L3: {l3_r[:200]}")
                if recs:
                    learning_data = "[学习数据]\n" + "\n".join(recs) + "\n\n"
        fb = state.get("feedback", "")
        l3_fb = state.get("l3_feedback", "")
        if l3_fb:
            fb = f"{fb}\n{l3_fb}" if fb else l3_fb
        fb_section = f"[L3 修改结果确认]\n{fb}\n\n" if fb else ""

        instruction = (
            "你的核心任务是完成 L2 下发的任务，Meta 提供任务整体背景。\n\n"
            "*** 输出规则（极其重要）***\n"
            "1. 如果需要继续思考或执行工具 → 调用【l3_continue】表示还需进一步工作\n"
            "2. 如果任务已完成 → 调用【l3_report】输出执行结果\n"
            "3. 禁止以文本方式直接输出JSON或回复，必须调用以上两个工具之一！\n\n"
            "l3_continue：继续思考，done固定为false\n"
            "l3_report：汇报结果，done固定为true，含 result 执行结果"
        )
        if l3_fmt:
            instruction += (
                "\n\n【整理任务】你只负责 L3 技能的修改。"
                "使用整理工具记录修改，完成后调用 l3_report 输出结果。"
            )
        system = self._build_system_prompt(instruction, meta)
        query_section = f"[上层查询]\n完成 L2 下发的任务：{l3_task}\n\n" if l3_task else ""

        # Build context history from previous L3 calls (within same executor trace)
        context_text = ""
        ctx_history = state.get("context_history", [])
        if ctx_history:
            lines = []
            for i, h in enumerate(ctx_history):
                lines.append(f"第{i+1}次请求: {h.get('query', '')[:300]}")
                lines.append(f"第{i+1}次结果: {h.get('reply', '')[:500]}")
            context_text = "\n".join(lines)

        ctx_section = f"[本轮上下文]\n{context_text}\n\n" if context_text else ""
        user = (
            f"{fb_section}"
            f"{learning_data}"
            f"{query_section}"
            f"{ctx_section}"
            f"[当前局面]\n{current}\n\n"
            f"[可用技能]\n{skills_text}"
        )

        if l3_fmt:
            from core.tools.registry import ToolRegistry
            from core.tools.consolidation_tools import L3_CONSOLIDATION_TOOL_NAMES
            _allowed = {"kb_query", "read_file", "grep"}
            base_tools = [t for t in (self._get_tools(layer) or [])
                          if t["function"]["name"] in _allowed]
            consol_schemas = ToolRegistry().get_definitions(L3_CONSOLIDATION_TOOL_NAMES)
            report_tool = self._schema_to_tool(
                "l3_report",
                "【特殊工具：向上汇报】必须使用！整理完成后调用此工具输出最终结果。禁止以文本方式直接回复。",
                {
                    "type": "object",
                    "properties": {
                        "done": {"type": "boolean", "const": True},
                        "result": {"type": "string", "description": "技能执行结果"},
                        "skills_used": {"type": "array", "items": {"type": "string"}},
                        "reasoning": {"type": "string"},
                    },
                    "required": ["done", "result", "reasoning"],
                },
            )
            all_tools = base_tools + consol_schemas + [report_tool]
            self._log.debug("  tools: %s", [t["function"]["name"] for t in all_tools])
            result = self._call_llm(system, user, tools=all_tools, layer=layer,
                                    capture_tools={"l3_report"})
            result = {
                "done": True,
                "result": result.get("result", ""),
                "skills_used": result.get("skills_used", []),
                "reasoning": result.get("reasoning", ""),
            }
            return result

        # Normal mode: two capture tools
        base_tools = self._get_tools(layer) or []
        continue_tool = self._schema_to_tool(
            "l3_continue",
            "【特殊工具：继续思考】当你需要进一步思考或执行工具来完成L2下发的任务时使用。"
            "调用此工具表示还需要继续工作。禁止以文本方式直接回复！",
            {
                "type": "object",
                "properties": {
                    "done": {"type": "boolean", "const": False},
                    "skills_used": {"type": "array", "items": {"type": "string"}},
                    "reasoning": {"type": "string"},
                },
                "required": ["done", "reasoning"],
            },
        )
        report_tool = self._schema_to_tool(
            "l3_report",
            "【特殊工具：向上汇报】当L2下发的任务执行完成时使用。"
            "给出明确的执行结果和使用的技能列表。禁止以文本方式直接回复！",
            {
                "type": "object",
                "properties": {
                    "done": {"type": "boolean", "const": True},
                    "result": {"type": "string", "description": "技能执行结果"},
                    "skills_used": {"type": "array", "items": {"type": "string"}},
                    "reasoning": {"type": "string"},
                },
                "required": ["done", "result", "reasoning"],
            },
        )
        all_tools = base_tools + [continue_tool, report_tool]
        self._log.debug("  tools: %s", [t["function"]["name"] for t in all_tools])
        result = self._call_llm(system, user, tools=all_tools, layer=layer,
                                capture_tools={"l3_continue", "l3_report"})
        if not result.get("done"):
            raw = result.get("_raw") or result.get("result") or result.get("reply") or ""
            if raw:
                return {"done": True, "result": str(raw), "reasoning": "direct reply",
                        "skills_used": []}
        return result


class L3Manager(LayerManager):
    """L3 Manager — wraps SkillLayer + L3Agent.

    Phase 1: domain-based deterministic skill matching → load SKILL.md.
    Phase 2: L3Agent(LLM) analyzes matched skills → selects + executes.
    TODO: Future card-level matching + L4 dispatch.

    Overrides query() to add LLM agent stage after deterministic match.
    """

    def __init__(self, skill_layer, downstream: LayerManager | None = None,
                 upward=None, downward=None, auxiliary_llm=None,
                 domain_registry=None, max_rounds=None, consol_ctx=None):
        super().__init__("l3", downstream, upward=upward, downward=downward)
        self._skill_layer = skill_layer
        self._agent = L3Agent(auxiliary_llm, skill_layer=skill_layer, domain_registry=domain_registry) if auxiliary_llm else None
        self._registry = domain_registry
        self._consol_ctx = consol_ctx
        if max_rounds is None:
            from core.config_loader import get_section
            max_rounds = get_section('runtime', default={}).get('max_rounds_l3', 3)
        self.max_rounds = max_rounds
        self._matched: list[str] = []
        self._matched_skills: list[dict] = []
        self._l3_notify: dict | None = None

    def process(self, data: Any) -> dict:
        return {"status": "ok", "layer": self.name}

    def query(self, msg: LayerMessage | Any, trace_id: str = "") -> None:
        obs, trace_id = self._unwrap_obs(msg, upward=self._upward, trace_id=trace_id)

        l3_task = obs.state.get("l3_task", "") if obs.state else ""
        selected_nodes = obs.state.get("selected_nodes", []) if obs.state else []
        session = obs.session if obs else {}
        domain_path = session.get("domain", "general")

        # Deterministic: domain-based skill matching (unchanged)
        node_domains = [n.get("name", "") for n in selected_nodes if n.get("name")]
        domains_hint = session.get("domains_hint", [domain_path])
        if node_domains:
            all_domains = list(dict.fromkeys(domains_hint + node_domains))
        else:
            all_domains = domains_hint

        if self._registry:
            skill_ids = self._registry.get_items_for_domains("l3", all_domains)
            self._matched_skills = self._skill_layer.get_skills_by_ids(skill_ids)
            self._matched = [s["name"] for s in self._matched_skills]
        else:
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

        for skill_id in self._matched:
            self._skill_layer.touch_skill(skill_id)

        logger.debug("── L3 (match) ──")
        logger.debug("  domain: %s → %d skills", domain_path, len(self._matched))

        if not self._agent:
            logger.warning("L3Agent not initialized (no auxiliary_llm), skipping")
            self._l3_notify = {
                "skills_matched": len(self._matched),
                "skills_used": [],
                "result": "",
                "reasoning": "no agent",
            }
            return

        state = dict(obs.state) if obs and obs.state else {}
        context: dict = {
            "matched_skills": self._matched_skills,
            "l3_task": l3_task,
        }

        tools = self._agent._get_tools("l3") if self._agent else None
        meta = l3_task or (obs.meta if obs else "")
        result = self._agent.decide(
            meta=meta, state=state, context=context,
            tools=tools, layer="l3",
        )
        logger.debug("  result: done=%s result=%s",
                     result.get("done"), str(result.get("result", ""))[:2000])

        self._l3_notify = {
            "skills_matched": len(self._matched),
            "skills_used": result.get("skills_used", []),
            "result": result.get("result", ""),
            "reasoning": result.get("reasoning", ""),
        }

        # Propagate downstream (L4, reserved)
        if self._downstream:
            q_msg = self._downward.wrap_query(
                payload={"obs": obs}, source=self.name,
                target=self._downstream.name, trace_id=trace_id,
            )
            self._downstream.query(q_msg, trace_id)

    def notify(self) -> Any:
        if self._l3_notify:
            result = dict(self._l3_notify)
            if self._consol_ctx:
                mods = self._consol_ctx.drain_mods()
                if mods:
                    result["l3_modifications"] = mods
            return result
        return {"status": "ok", "layer": "l3", "skills_matched": len(self._matched)}
