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
        """Execute one action cycle through the cognitive chain.

        Returns: dict with keys:
            action_text: str   - LLM's raw response text
            context: dict      - assembled context sent to LLM
            notify_layers: dict - {layer_name: payload} from all layers
        """
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

        if obs.meta.get("enable_learning") and self._learning_dir:
            self._write_pending(obs, notify_layers, result)

        return result

    def _assemble_context(self, obs: TaskObservation) -> dict:
        return {
            "meta": obs.meta,
            "state": obs.state,
            "history": obs.history,
        }

    def _call_llm(self, context: dict) -> str:
        system = self._build_system_prompt(context)
        user = self._build_user_prompt(context)
        logger.info("LLM call | l1_rules=%d l2_cards=%d l3_skills=%d",
                     len(context.get("meta", {}).get("l1_rules", [])),
                     len(context.get("meta", {}).get("l2_cards", [])),
                     len(context.get("meta", {}).get("l3_skills", [])))
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        resp = self._llm.chat(messages=messages)
        return resp.text if hasattr(resp, 'text') else str(resp)

    def _build_system_prompt(self, context: dict) -> str:
        meta = context.get("meta", {})
        rules = meta.get("l1_rules", [])
        cards = meta.get("l2_cards", [])
        skills = meta.get("l3_skills", [])

        parts = []
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
            parts.append(
                "[可用技能]\n" + ", ".join(s["name"] for s in skills)
            )
        return "\n\n".join(parts) if parts else ""

    def _build_user_prompt(self, context: dict) -> str:
        state = context.get("state", {})
        lines = []
        for key, value in state.items():
            lines.append(f"{key}: {value}")
        return "\n".join(lines)

    def _write_pending(self, obs: TaskObservation, notify_layers: dict,
                       result: dict) -> None:
        pending_dir = self._learning_dir / "pending"
        pending_dir.mkdir(parents=True, exist_ok=True)

        session = obs.state.get("session", {}) if isinstance(obs.state, dict) else {}
        rec = ExecutionRecord(
            session=session,
            observation={"meta": obs.meta, "state": obs.state, "history": obs.history},
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
