# InteractionEnv 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为认知 Agent 构建通用 CLI 对话交互环境（InteractionEnv）+ 启动脚本。

**Architecture:** InteractionEnv 继承 `Environment` ABC，对齐 `LearningEnv` 通信模式（`receive_input` → `build_task_observation` → `step`）；Executor 驱动完整认知链；脚本只负责 CLI I/O。

**Tech Stack:** Python 3.11+, pytz, pyyaml, pytest

---

### Task 1: InteractionEnv 类

**Files:**
- Create: `core/env/interaction_env.py`
- Create: `tests/test_interaction_env.py`

- [ ] **Step 1: 编写失败测试**

```python
# tests/test_interaction_env.py
import pytest
from core.env.interaction_env import InteractionEnv
from core.env.base import EnvState, EnvStep


class TestInteractionEnvReset:
    def test_reset_creates_session(self):
        env = InteractionEnv(system_prompt="You are helpful")
        state = env.reset("start chat")
        assert isinstance(state, EnvState)
        assert state.info.get("session_id")

    def test_reset_clears_history(self):
        env = InteractionEnv(system_prompt="You are helpful")
        env.reset("start")
        env.receive_input("hello")
        env.build_task_observation()
        env.step("hi")
        assert len(env.get_history()) == 2
        env.reset("restart")
        assert len(env.get_history()) == 0

    def test_sessions_have_different_ids(self):
        env = InteractionEnv(system_prompt="You are helpful")
        s1 = env.reset("start")
        s2 = env.reset("restart")
        assert s1.info["session_id"] != s2.info["session_id"]


class TestInteractionEnvReceiveBuild:
    def test_receive_input_stores_pending(self):
        env = InteractionEnv(system_prompt="You are helpful")
        env.reset("start")
        env.receive_input("hello world")
        obs = env.build_task_observation()
        assert obs is not None
        assert obs.state["current"] == "hello world"

    def test_build_task_observation_returns_none_when_no_input(self):
        env = InteractionEnv(system_prompt="You are helpful")
        env.reset("start")
        obs = env.build_task_observation()
        assert obs is None

    def test_build_task_observation_includes_history(self):
        env = InteractionEnv(system_prompt="You are helpful")
        env.reset("start")
        env.receive_input("hello")
        env.build_task_observation()
        env.step("hi")
        env.receive_input("how are you")
        obs = env.build_task_observation()
        assert obs is not None
        assert len(obs.state["conversation_history"]) == 2
        assert obs.state["conversation_history"][0] == {"role": "user", "content": "hello"}
        assert "[用户]: hello" in obs.state["history"]
        assert "[助手]: hi" in obs.state["history"]

    def test_build_task_observation_empty_history_string(self):
        env = InteractionEnv(system_prompt="You are helpful")
        env.reset("start")
        env.receive_input("first message")
        obs = env.build_task_observation()
        assert obs is not None
        assert obs.state["history"] == ""


class TestInteractionEnvStep:
    def test_step_records_exchange(self):
        env = InteractionEnv(system_prompt="You are helpful")
        env.reset("start")
        env.receive_input("hello")
        env.build_task_observation()
        result = env.step("hi there")
        assert isinstance(result, EnvStep)
        assert result.reward == 0
        assert result.done is False
        assert len(env.get_history()) == 2

    def test_step_displays_action_text(self):
        env = InteractionEnv(system_prompt="You are helpful")
        env.reset("start")
        env.receive_input("hello")
        env.build_task_observation()
        result = env.step("hi there")
        assert result.state.observation == "hi there"

    def test_step_clears_pending_input(self):
        env = InteractionEnv(system_prompt="You are helpful")
        env.reset("start")
        env.receive_input("hello")
        env.build_task_observation()
        env.step("hi")
        obs = env.build_task_observation()
        assert obs is None


class TestInteractionEnvSession:
    def test_session_info(self):
        env = InteractionEnv(system_prompt="You are helpful")
        env.reset("start")
        env.receive_input("hello")
        env.build_task_observation()
        env.step("hi")
        info = env.session_info()
        assert info["turns"] == 1
        assert isinstance(info["id"], str) and len(info["id"]) > 0
        assert isinstance(info["started_at"], str)

    def test_session_info_default_learning_true(self):
        env = InteractionEnv(system_prompt="You are helpful")
        env.reset("start")
        info = env.session_info()
        assert info["enable_learning"] is True

    def test_session_info_learning_false(self):
        env = InteractionEnv(system_prompt="You are helpful", enable_learning=False)
        env.reset("start")
        info = env.session_info()
        assert info["enable_learning"] is False

    def test_session_metadata_in_task_obs(self):
        env = InteractionEnv(system_prompt="You are helpful")
        env.reset("start")
        env.receive_input("hello")
        obs = env.build_task_observation()
        assert obs is not None
        assert obs.session["domain"] == "interaction"
        assert obs.session["domains_hint"] == ["interaction"]
        assert obs.meta == "You are helpful"
        assert obs.session["enable_learning"] is True
        assert obs.session["step_index"] == 0

    def test_step_index_increments(self):
        env = InteractionEnv(system_prompt="You are helpful")
        env.reset("start")
        env.receive_input("t1")
        obs1 = env.build_task_observation()
        env.step("r1")
        env.receive_input("t2")
        obs2 = env.build_task_observation()
        assert obs1.session["step_index"] == 0
        assert obs2.session["step_index"] == 1


class TestInteractionEnvHistory:
    def test_get_history_is_copy(self):
        env = InteractionEnv(system_prompt="You are helpful")
        env.reset("start")
        env.receive_input("hello")
        env.build_task_observation()
        env.step("hi")
        h = env.get_history()
        h.append({"role": "user", "content": "extra"})
        assert len(env.get_history()) == 2

    def test_format_history_multi_turn(self):
        env = InteractionEnv(system_prompt="You are helpful")
        env.reset("start")
        env.receive_input("hello")
        env.build_task_observation()
        env.step("hi")
        env.receive_input("weather?")
        obs = env.build_task_observation()
        expected = "[用户]: hello\n[助手]: hi"
        assert obs.state["history"] == expected
```

- [ ] **Step 2: 运行测试，确认失败**

```
pytest tests/test_interaction_env.py -v
```
Expected: all FAIL with `ModuleNotFoundError: No module named 'core.env.interaction_env'`

- [ ] **Step 3: 实现 InteractionEnv**

```python
# core/env/interaction_env.py
from __future__ import annotations
import uuid
from datetime import datetime, timezone

from core.env.base import Environment, EnvState, EnvStep
from core.types import TaskObservation


class InteractionEnv(Environment):
    """通用对话交互环境。管理会话和对话历史，构造符合 Executor 预期的 TaskObservation。

    Follows Environment ABC and LearningEnv communication pattern:
      reset → receive_input → build_task_observation → step
    """

    def __init__(self, system_prompt: str, debug: bool = False, enable_learning: bool = True):
        self._system_prompt = system_prompt
        self.debug = debug
        self._enable_learning = enable_learning
        self._session_id = ""
        self._session_started_at = ""
        self._history: list[dict] = []
        self._pending_input = ""

    def reset(self, task_description: str) -> EnvState:
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
                "conversation_history": list(self._history),
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
```

- [ ] **Step 4: 运行测试，确认全部通过**

```
pytest tests/test_interaction_env.py -v
```
Expected: all 15 tests PASS.

- [ ] **Step 5: 提交**

```bash
git add core/env/interaction_env.py tests/test_interaction_env.py
git commit -m "feat: add InteractionEnv for general-purpose CLI dialogue"
```

---

### Task 2: CLI 交互脚本

**Files:**
- Create: `scripts/interactive_agent.py`

- [ ] **Step 1: 编写脚本**

```python
# scripts/interactive_agent.py
"""交互式认知 Agent — CLI 对话环境，支持调试和会话管理。

用法:
  python scripts/interactive_agent.py
  python scripts/interactive_agent.py --debug
  python scripts/interactive_agent.py --system-prompt "你是一个编程助手"
  python scripts/interactive_agent.py --no-record
"""
import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

PROJECT_ROOT = Path(__file__).resolve().parent.parent

DEFAULT_SYSTEM_PROMPT = "你是一个智能助手。请直接简洁地回复用户的问题。"


def _parse_args():
    parser = argparse.ArgumentParser(description="交互式认知 Agent")
    parser.add_argument("--debug", action="store_true", help="显示各层 NOTIFY 输出")
    parser.add_argument("--no-record", action="store_true", dest="no_record",
                        help="不将交互记录写入学习管道")
    parser.add_argument("--system-prompt", type=str, default=None,
                        help="自定义系统提示词")
    return parser.parse_args()


def _setup_executor():
    from core.env_loader import load_env
    load_env(PROJECT_ROOT)

    from core.chain_factory import build_default_chain
    chain = build_default_chain(PROJECT_ROOT, seed=False)

    from core.llm_factory import build_llm_client
    llm = build_llm_client(PROJECT_ROOT / "config.yaml")

    from core.executor import Executor
    executor = Executor(
        layer_root=chain,
        llm_client=llm,
        learning_dir=PROJECT_ROOT / "data" / "learning",
    )
    return executor


def _show_notifies(notify_layers: dict):
    import json
    for name in ("l0_5_1", "l2", "l3"):
        payload = notify_layers.get(name, {})
        if not payload:
            continue
        label = name.replace("l0_5_1", "L1").replace("l2", "L2").replace("l3", "L3")
        text = json.dumps(payload, ensure_ascii=False, indent=2, default=str)
        if len(text) > 2000:
            text = text[:2000] + "..."
        print(f"  [{label}]\n{text}")


def main():
    args = _parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(message)s",
        handlers=[logging.StreamHandler()],
    )

    executor = _setup_executor()

    from core.env.interaction_env import InteractionEnv
    env = InteractionEnv(
        system_prompt=args.system_prompt or DEFAULT_SYSTEM_PROMPT,
        debug=args.debug,
        enable_learning=not args.no_record,
    )

    state = env.reset("interaction")
    print(state.observation)
    print("(Commands: /new=新会话, /info=会话信息, exit/quit=退出)\n")

    while True:
        try:
            user_input = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if user_input.lower() in ("exit", "quit"):
            break
        if user_input == "/new":
            state = env.reset("interaction")
            print(state.observation)
            continue
        if user_input == "/info":
            info = env.session_info()
            print(
                f"Session: {info['id'][:8]}... | turns: {info['turns']} "
                f"| started: {info['started_at'][:19]}"
            )
            continue
        if not user_input:
            continue

        env.receive_input(user_input)
        task_obs = env.build_task_observation()
        if task_obs is None:
            continue

        try:
            result = executor.execute(task_obs)
        except Exception as e:
            print(f"Error: {e}")
            continue

        reply = result.get("action_text", "").strip()
        step = env.step(reply)

        if args.debug:
            _show_notifies(result.get("notify_layers", {}))

        print(f"Agent: {reply}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 验证脚本可正常导入**

```
python -c "import sys; sys.path.insert(0,'scripts'); import interactive_agent; print(interactive_agent.DEFAULT_SYSTEM_PROMPT)"
```
Expected: 打印默认 system prompt，无 ImportError。

- [ ] **Step 3: 提交**

```bash
git add scripts/interactive_agent.py
git commit -m "feat: add interactive_agent CLI script"
```

---

### Task 3: 运行全量测试验证

- [ ] **Step 1: 运行 InteractionEnv 测试**

```
pytest tests/test_interaction_env.py -v
```
Expected: 15 passed

- [ ] **Step 2: 验证与现有测试无冲突**

```
pytest tests/ -x --ignore=tests/test_interaction_env.py -q
```
Expected: 现有全部测试仍通过

- [ ] **Step 3: 提交（如无事则跳过）**

---

### Self-Review Checklist

**1. Spec coverage:**
- InteractionEnv 类（reset/receive_input/build_task_observation/step/get_history/session_info） → Task 1
- CLI 脚本（argparse、--debug/--no-record/--system-prompt、交互循环、/new、/info） → Task 2
- 持久化（enable_learning 控制、Executor._write_pending 自动写入） → Task 1 build_task_observation + Task 2 --no-record
- 异常处理（空输入、KeyboardInterrupt、runtime 异常、NOTIFY 截断） → Task 2
- 会话管理（session_id、started_at、reset 清理） → Task 1

**2. Placeholder scan:** 无 "TBD"、"TODO"、"implement later"

**3. Type consistency:** `InteractionEnv` 所有方法签名在各 task 中一致；`build_task_observation` → `TaskObservation | None`；`step` → `EnvStep`；`reset` → `EnvState`
