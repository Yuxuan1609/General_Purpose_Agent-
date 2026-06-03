from __future__ import annotations
import json
import logging
import tempfile
import uuid
from pathlib import Path
from typing import Any

from core.types import TaskObservation, ExecutionRecord
from core.layer_message import LayerMessage, MessageType

logger = logging.getLogger(__name__)


def _indent(text: str, spaces: int) -> str:
    prefix = " " * spaces
    return prefix + text.replace("\n", "\n" + prefix)


class Executor:
    """Independent decision-maker outside the layer system.

    Responsibilities:
      1. Send QUERY down the layer chain
      2. Wait for RESPONSE chain to complete
      3. Collect NOTIFY from all layers
      4. Assemble final prompt from all layer contexts
      5. Call LLM and return action
      6. Optionally write ExecutionRecord to learning pipeline

    Executor does NOT send messages back to layers (只收不发).
    """

    def __init__(self, layer_root, llm_client, learning_dir: Path | None = None,
                 max_tokens: int = 512, temperature: float = 0.1):
        self._root = layer_root
        self._llm = llm_client
        self._learning_dir = learning_dir
        self._max_tokens = max_tokens
        self._temperature = temperature

    def execute(self, obs: TaskObservation) -> dict:
        """Execute one action cycle through the cognitive chain."""
        session = obs.session or {}
        step = session.get("step_index", 0)
        domain = session.get("domain", "")
        logger.debug("══════ Step %d  [%s] ══════", step, domain)
        trace_id = uuid.uuid4().hex[:12]
        msg = LayerMessage(
            source="executor", target=self._root.name,
            type=MessageType.QUERY,
            payload=obs, trace_id=trace_id,
        )
        self._root.query(msg, trace_id)
        notify_layers = self._root.collect_notify()

        context = self._assemble_context(obs)
        action_text = self._call_llm(context)

        result = {
            "action_text": action_text,
            "context": context,
            "notify_layers": notify_layers,
        }

        if self._learning_dir:
            self._write_pending(obs, notify_layers, result)

        return result

    def _assemble_context(self, obs: TaskObservation) -> dict:
        return {
            "meta": obs.meta,
            "state": obs.state,
        }

    def _call_llm(self, context: dict) -> str:
        system = self._build_system_prompt(context)
        user = self._build_user_prompt(context)
        state = context.get("state", {})
        l1_count = len(state.get("l1_rules", []))
        l2_count = len(state.get("l2_cards", []))
        l3_count = len(state.get("l3_skills", []))
        logger.debug("── Executor ──")
        logger.debug("  context: l1=%d l2=%d l3=%d",
                     l1_count, l2_count, l3_count)
        logger.debug("  system:\n%s", _indent(system, 4))
        logger.debug("  user:\n%s", _indent(user, 4))
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        resp = self._llm.chat(messages=messages)
        action_text = resp.text if hasattr(resp, 'text') else str(resp)
        logger.info("[Executor] action: %s", action_text)
        logger.debug("── end Executor ──\n")
        return action_text

    def _build_system_prompt(self, context: dict) -> str:
        meta = context.get("meta", "")
        state = context.get("state", {})
        rules = state.get("l1_rules", [])
        cards = state.get("l2_cards", [])
        skills = state.get("l3_skills", [])

        parts = []
        if meta:
            parts.append("[任务说明]\n" + meta)
        if rules:
            parts.append("[行为准则]\n" + "\n".join(f"- {r}" for r in rules))
        if cards:
            parts.append(
                "[相关知识]\n" +
                "\n".join(
                    f"- [{c['domain']}] {c['content']} (confidence:{c['confidence']:.1f})"
                    for c in cards
                )
            )
        if skills:
            skill_lines = []
            for s in skills:
                skill_lines.append(f"## {s['name']}: {s['description']}")
                if s.get("content"):
                    skill_lines.append(s["content"])
            parts.append("[可用技能]\n" + "\n".join(skill_lines))
        return "\n\n".join(parts) if parts else ""

    def _build_user_prompt(self, context: dict) -> str:
        state = context.get("state", {})
        parts = []
        history = state.get("history", "")
        if history:
            parts.append(f"[对局历史]\n{history}")
        current = state.get("current", "")
        if current:
            parts.append(current)
        return "\n\n".join(parts) if parts else ""

    def _write_pending(self, obs: TaskObservation, notify_layers: dict,
                       result: dict) -> None:
        pending_dir = self._learning_dir / "pending"
        pending_dir.mkdir(parents=True, exist_ok=True)

        session = obs.session or {}
        rec = ExecutionRecord(
            session=session,
            observation={"meta": obs.meta, "state": obs.state},
            notify_layers=notify_layers,
            action=result.get("action_text"),
        )

        session_id = session.get("id", "unknown")
        filepath = pending_dir / f"{session_id}.json"
        content = json.dumps(rec.__dict__, ensure_ascii=False, indent=2, default=str)
        tmp = tempfile.mktemp(suffix=".json", dir=str(pending_dir))
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(content)
        Path(tmp).replace(filepath)
