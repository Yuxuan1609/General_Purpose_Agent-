from __future__ import annotations
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from core.env.base import Environment, EnvState, EnvStep
from core.types import TaskObservation


class InteractionEnv(Environment):
    """通用对话交互环境。管理会话和对话历史，构造符合 Executor 预期的 TaskObservation。

    Follows Environment ABC and LearningEnv communication pattern:
      reset -> receive_input -> build_task_observation -> step

    Note: task_description 在 InteractionEnv 中不使用（不像 LearningEnv 需提取 domain）。
    InteractionEnv 的 domain 固定为 "interaction"。
    """

    def __init__(self, system_prompt: str, debug: bool = False,
                 enable_learning: bool = True):
        self._system_prompt: str = system_prompt
        self.debug: bool = debug
        self._enable_learning: bool = enable_learning
        self._session_id: str = ""
        self._session_started_at: str = ""
        self._history: list[dict] = []
        self._pending_input: str = ""

    def reset(self, task_description: str = "") -> EnvState:
        self._session_id = uuid.uuid4().hex
        self._session_started_at = datetime.now(timezone.utc).isoformat()
        self._history.clear()
        self._pending_input = ""
        sid = self._session_id[:8]
        return EnvState(
            observation=f"Session {sid} started",
            info={"session_id": self._session_id, "started_at": self._session_started_at},
        )

    def receive_input(self, user_input: str) -> None:
        self._pending_input = user_input

    def build_task_observation(self) -> TaskObservation | None:
        if not self._pending_input:
            return None
        return TaskObservation(
            meta=self._system_prompt,
            state={
                "current": self._pending_input,
                "history": self._format_history_for_prompt(),
            },
            session={
                "id": self._session_id,
                "domain": "interaction",
                "domains_hint": ["interaction"],
                "step_index": len(self._history) // 2,
                "enable_learning": self._enable_learning,
            },
        )

    def step(self, action: str) -> EnvStep:
        if self._pending_input:
            self._history.append({"role": "user", "content": self._pending_input})
        self._history.append({"role": "assistant", "content": action})
        self._pending_input = ""
        return EnvStep(
            state=EnvState(observation=action, info={"turns": len(self._history) // 2}),
            reward=0,
            done=False,
        )

    def get_history(self) -> list[dict]:
        return [dict(h) for h in self._history]

    def save_history(self, filepath: Path) -> Path:
        data = {
            "session_id": self._session_id,
            "started_at": self._session_started_at,
            "system_prompt": self._system_prompt,
            "turns": len(self._history) // 2,
            "history": self.get_history(),
            "saved_at": datetime.now(timezone.utc).isoformat(),
        }
        filepath.parent.mkdir(parents=True, exist_ok=True)
        filepath.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return filepath

    def session_info(self) -> dict:
        return {
            "id": self._session_id,
            "turns": len(self._history) // 2,
            "started_at": self._session_started_at,
            "enable_learning": self._enable_learning,
        }

    def _format_history_for_prompt(self) -> str:
        if not self._history:
            return ""
        lines = []
        for entry in self._history:
            if entry["role"] == "user":
                lines.append(f"[用户]: {entry['content']}")
            elif entry["role"] == "assistant":
                lines.append(f"[助手]: {entry['content']}")
        return "\n".join(lines)

