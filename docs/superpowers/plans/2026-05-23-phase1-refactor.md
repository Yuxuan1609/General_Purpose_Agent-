# Phase 1 Refactor — Foundation + A2/A4 Skeleton Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Clean up code smells (MagicMock in production, LLM wrapper in entry point), introduce LayerMessage (A2), separate Execute/Reflect phases (A4), add explicit evaluation fields, create environment adapter interface, and erect layer directory scaffolding with Agent stubs.

**Architecture:** 6 self-contained refactoring tasks. Tasks 1-2 are dependency chain cleanup. Task 3 is a pure data module (zero deps). Tasks 4-5 modify the event loop and task model. Task 6 introduces the env adapter interface. Task 7 erects the directory skeleton. All existing tests must pass after every task; new tests written TDD-style.

**Tech Stack:** Python 3.11+, dataclasses, pytest, unittest.mock

---

### Task 1: LLMResponse dataclass — remove MagicMock from production code

**Files:**
- Create: `core/llm_client.py`
- Modify: `main.py:1-88`
- Modify: `core/agent.py:1-67`
- Modify: `core/config.py:1-20`
- Test: `tests/test_llm_client.py`

**Note:** All existing tests mock LLM behavior with `MagicMock(has_tool_calls=..., tool_calls=[...], text=...)`. The new `LLMResponse` must expose the same attributes so existing tests do not break. `LLMClient` wraps `_LLMWrapper.chat()` logic and returns `LLMResponse` instead of `MagicMock`.

- [ ] **Step 1: Write failing tests for LLMResponse and LLMClient**

```python
# tests/test_llm_client.py
import pytest
from unittest.mock import MagicMock, patch
from core.llm_client import LLMResponse, LLMClient, ToolCall, FunctionCall


class TestLLMResponse:
    def test_response_without_tool_calls(self):
        resp = LLMResponse(text="Hello", tool_calls=[])
        assert resp.has_tool_calls is False
        assert resp.text == "Hello"

    def test_response_with_tool_calls(self):
        tc = ToolCall(function=FunctionCall(name="search", arguments='{"q":"test"}'))
        resp = LLMResponse(text="", tool_calls=[tc])
        assert resp.has_tool_calls is True
        assert len(resp.tool_calls) == 1
        assert resp.tool_calls[0].function.name == "search"
        assert resp.tool_calls[0].function.arguments == '{"q":"test"}'

    def test_response_text_and_tool_calls(self):
        tc = ToolCall(function=FunctionCall(name="search", arguments="{}"))
        resp = LLMResponse(text="Let me search", tool_calls=[tc])
        assert resp.has_tool_calls is True
        assert resp.text == "Let me search"


class TestLLMClient:
    def test_chat_returns_llm_response(self):
        mock_openai = MagicMock()
        mock_msg = MagicMock()
        mock_msg.content = "response text"
        mock_msg.tool_calls = None
        mock_openai.chat.completions.create.return_value = MagicMock(
            choices=[MagicMock(message=mock_msg)]
        )
        client = LLMClient(client=mock_openai, model="test-model")
        resp = client.chat(messages=[{"role": "user", "content": "hi"}])
        assert isinstance(resp, LLMResponse)
        assert resp.text == "response text"
        assert resp.has_tool_calls is False

    def test_chat_with_tools(self):
        mock_openai = MagicMock()
        mock_tc = MagicMock()
        mock_tc.function.name = "skills_list"
        mock_tc.function.arguments = '{}'
        mock_msg = MagicMock()
        mock_msg.content = ""
        mock_msg.tool_calls = [mock_tc]
        mock_openai.chat.completions.create.return_value = MagicMock(
            choices=[MagicMock(message=mock_msg)]
        )
        client = LLMClient(client=mock_openai, model="test-model")
        tools = [{"type": "function", "function": {"name": "test", "parameters": {}}}]
        resp = client.chat(messages=[], tools=tools)
        assert resp.has_tool_calls is True
        assert resp.tool_calls[0].function.name == "skills_list"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_llm_client.py -v
```
Expected: FAIL with `ModuleNotFoundError: No module named 'core.llm_client'`

- [ ] **Step 3: Create `core/llm_client.py` with LLMResponse, ToolCall, FunctionCall, LLMClient**

```python
# core/llm_client.py
from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class FunctionCall:
    name: str
    arguments: str = "{}"


@dataclass
class ToolCall:
    function: FunctionCall


@dataclass
class LLMResponse:
    text: str
    tool_calls: list[ToolCall] = field(default_factory=list)

    @property
    def has_tool_calls(self) -> bool:
        return len(self.tool_calls) > 0


class LLMClient:
    def __init__(self, client, model: str):
        self._client = client
        self.model = model

    def chat(self, messages: list, tools: list | None = None, **kwargs) -> LLMResponse:
        params = {"model": self.model, "messages": messages}
        if tools:
            params["tools"] = [
                {"type": "function", "function": t["function"]}
                if isinstance(t, dict) and "function" in t else t
                for t in tools
            ]
        resp = self._client.chat.completions.create(**params)
        msg = resp.choices[0].message
        raw_calls = msg.tool_calls or []
        tool_calls = [
            ToolCall(function=FunctionCall(
                name=tc.function.name,
                arguments=getattr(tc.function, "arguments", "{}"),
            ))
            for tc in raw_calls
        ]
        return LLMResponse(
            text=msg.content or "",
            tool_calls=tool_calls,
        )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_llm_client.py -v
```
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add core/llm_client.py tests/test_llm_client.py
git commit -m "feat: add LLMResponse dataclass and LLMClient adapter"
```

---

### Task 2: Migrate main.py to use LLMClient, remove _LLMWrapper and MagicMock import

**Files:**
- Modify: `main.py:1-88`
- Modify: `core/config.py:1-20`

**Note:** `AgentConfig` stores `main_llm` and `auxiliary_llm` as `Any`. After migration they will hold `LLMClient` instances. Update `load_config()` to use `LLMClient`. All consumers (`agent.py`, `agent_loop.py`, `meta_driver.py`) access `config.main_llm` and call `.chat()` — the interface is identical (`LLMClient.chat` returns `LLMResponse` which has `.has_tool_calls`, `.tool_calls`, `.text`), so no consumer changes needed.

- [ ] **Step 1: Write test for load_config with LLMClient**

```python
# tests/test_main_config.py
import os
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
from main import load_config
from core.llm_client import LLMClient


class TestLoadConfig:
    def test_load_config_returns_llm_client(self, tmp_path):
        config_file = tmp_path / "config.yaml"
        config_file.write_text("""
main_llm:
  provider: deepseek
  model: deepseek-chat
  api_key_env: TEST_KEY
  base_url: https://test.api.com
auxiliary_llm:
  provider: deepseek
  model: deepseek-chat
  api_key_env: TEST_KEY
  base_url: https://test.api.com
max_iterations: 10
""")
        os.environ["TEST_KEY"] = "fake-key"
        with patch("main.OpenAI") as mock_openai:
            cfg = load_config(str(config_file))
            assert isinstance(cfg.main_llm, LLMClient)
            assert isinstance(cfg.auxiliary_llm, LLMClient)
            assert cfg.main_llm.model == "deepseek-chat"
        del os.environ["TEST_KEY"]
```

- [ ] **Step 2: Run test to verify it fails** (expect LLMClient not used)

```bash
pytest tests/test_main_config.py -v
```
Expected: FAIL (main_llm is _LLMWrapper MagicMock, not LLMClient)

- [ ] **Step 3: Rewrite `main.py` — remove `_LLMWrapper` class, remove `from unittest.mock import MagicMock`, use `LLMClient`**

```python
"""Cognitive Agent — entry point."""
import yaml
import os
from pathlib import Path
from openai import OpenAI
from core.config import AgentConfig
from core.llm_client import LLMClient
from core.agent import CognitiveAgent


def _load_env():
    env_path = Path(__file__).parent / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key, val = key.strip(), val.strip()
            if key not in os.environ:
                os.environ[key] = val


def _make_llm(cfg: dict) -> LLMClient:
    base_url = cfg.get("base_url", "https://api.deepseek.com")
    api_key = os.environ.get(cfg.get("api_key_env", "DEEPSEEK_API_KEY"), "")
    return LLMClient(OpenAI(base_url=base_url, api_key=api_key), cfg.get("model", "deepseek-chat"))


def load_config(config_path: str = "config.yaml") -> AgentConfig:
    _load_env()

    with open(config_path) as f:
        raw = yaml.safe_load(f)

    main_llm = _make_llm(raw.get("main_llm", {}))
    aux_llm = _make_llm(raw.get("auxiliary_llm", {}))

    return AgentConfig(
        main_llm=main_llm, auxiliary_llm=aux_llm,
        max_iterations=raw.get("max_iterations", 50),
        l1_max_rules=raw.get("l1_max_rules", 20),
        l1_max_rule_length=raw.get("l1_max_rule_length", 100),
        l1_rules_path=Path(raw.get("l1_rules_path", "./data/l1_rules.json")),
        skills_dir=Path(raw.get("skills_dir", "./skills")),
        knowledge_dir=Path(raw.get("knowledge_dir", "./knowledge")),
        l2_index_path=Path(raw.get("l2_index_path", "./knowledge/l2_index.json")),
        seed_l1_rules=raw.get("seed_l1_rules"),
        seed_l2_cards=raw.get("seed_l2_cards"),
    )


if __name__ == "__main__":
    import sys
    config = load_config()
    agent = CognitiveAgent(config)
    print("Cognitive Agent ready.")
    print(f"L1 rules: {len(agent.inspect_l1())}")
    print(f"L3 skills: {len(agent.inspect_l3())}")
    if len(sys.argv) > 1:
        result = agent.run(" ".join(sys.argv[1:]))
        print(f"\nResult: {result.final_response[:500]}")
        print(f"Iterations: {result.iterations_used}")
        print(f"New L2 cards: {result.new_knowledge_cards}")
```

- [ ] **Step 4: Run new test to verify it passes**

```bash
pytest tests/test_main_config.py -v
```
Expected: PASS

- [ ] **Step 5: Run ALL existing tests to verify no regressions**

```bash
pytest tests/ -v
```
Expected: PASS (all 27+ tests)

- [ ] **Step 6: Commit**

```bash
git add main.py tests/test_main_config.py
git commit -m "refactor: replace _LLMWrapper/MagicMock with LLMClient/LLMResponse"
```

---

### Task 3: Create LayerMessage module (A2 foundation)

**Files:**
- Create: `core/layer_message.py`
- Create: `tests/test_layer_message.py`

**Note:** Pure data module with zero dependencies on any existing code. Defines the contract for all future inter-layer communication.

- [ ] **Step 1: Write failing tests for LayerMessage and MessageType**

```python
# tests/test_layer_message.py
import pytest
from datetime import datetime
from core.layer_message import LayerMessage, MessageType


class TestMessageType:
    def test_message_type_values(self):
        assert MessageType.QUERY.value == "QUERY"
        assert MessageType.RESPONSE.value == "RESPONSE"
        assert MessageType.PROPOSAL.value == "PROPOSAL"
        assert MessageType.APPROVAL.value == "APPROVAL"
        assert MessageType.REJECTION.value == "REJECTION"
        assert MessageType.NOTIFY.value == "NOTIFY"


class TestLayerMessage:
    def test_create_query_message(self):
        msg = LayerMessage(
            source="L1",
            target="L2",
            type=MessageType.QUERY,
            payload={"request": "get_active_cards"},
            trace_id="task-42",
            timestamp=datetime(2026, 1, 1),
        )
        assert msg.source == "L1"
        assert msg.target == "L2"
        assert msg.type == MessageType.QUERY
        assert msg.subtype == ""
        assert msg.payload == {"request": "get_active_cards"}
        assert msg.trace_id == "task-42"

    def test_create_with_subtype(self):
        msg = LayerMessage(
            source="L2",
            target="L3",
            type=MessageType.PROPOSAL,
            subtype="L2_to_L3:COMPILATION_SIGNAL",
            payload={"cards": 5},
            trace_id="task-42",
        )
        assert msg.subtype == "L2_to_L3:COMPILATION_SIGNAL"

    def test_frozen_immutable(self):
        msg = LayerMessage(
            source="L1", target="L2", type=MessageType.NOTIFY,
            payload="test", trace_id="t1",
        )
        with pytest.raises(Exception):
            msg.source = "L3"

    def test_default_values(self):
        msg = LayerMessage(
            source="ORCHESTRATOR",
            target="L1",
            type=MessageType.NOTIFY,
            payload=None,
            trace_id="t1",
        )
        assert msg.subtype == ""
        assert isinstance(msg.timestamp, datetime)
        assert msg.metadata == {}

    def test_metadata_extension(self):
        msg = LayerMessage(
            source="L1", target="L0.5", type=MessageType.PROPOSAL,
            payload={"rule": "new rule"},
            trace_id="t1",
            metadata={"priority": "high", "ttl": 5},
        )
        assert msg.metadata["priority"] == "high"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_layer_message.py -v
```
Expected: FAIL (module not found)

- [ ] **Step 3: Create `core/layer_message.py`**

```python
# core/layer_message.py
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class MessageType(Enum):
    QUERY = "QUERY"
    RESPONSE = "RESPONSE"
    PROPOSAL = "PROPOSAL"
    APPROVAL = "APPROVAL"
    REJECTION = "REJECTION"
    NOTIFY = "NOTIFY"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class LayerMessage:
    source: str
    target: str
    type: MessageType
    payload: Any
    trace_id: str
    subtype: str = ""
    timestamp: datetime = field(default_factory=_utc_now)
    metadata: dict = field(default_factory=dict)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_layer_message.py -v
```
Expected: PASS (6 tests)

- [ ] **Step 5: Run ALL existing tests to verify no regressions**

```bash
pytest tests/ -v
```
Expected: PASS (all tests, LayerMessage has zero impact on existing code)

- [ ] **Step 6: Commit**

```bash
git add core/layer_message.py tests/test_layer_message.py
git commit -m "feat: add LayerMessage and MessageType (A2 data contract)"
```

---

### Task 4: Separate Execute and Reflect in AgentLoop (A4 phase separation)

**Files:**
- Modify: `core/agent_loop.py:1-125`
- Modify: `core/task.py:47-66` (TaskResult add fields)
- Modify: `tests/test_agent_loop.py:1-73`
- Modify: `tests/test_task.py:48-57`

**Note:** Currently `AgentLoop.run(task)` does Execute + Reflect in one method (calls `post_task` inside). Refactor so `run()` only does Execute (returns messages + raw result), and `reflect(task, result)` does the learning phase. The `CognitiveAgent.run()` in `agent.py` orchestrates both.

Also add `eval_result` and `eval_score` to `TaskResult` for explicit evaluation.

- [ ] **Step 1: Write failing tests for new TaskResult fields and separated AgentLoop**

```python
# tests/test_agent_loop.py (append to existing file)
class TestAgentLoopSeparated:
    def test_run_returns_messages_without_reflection(self, mock_llm, mock_tools, mock_layers):
        mock_layers.check_completion.return_value = "done"
        loop = AgentLoop(mock_llm, mock_tools, mock_layers, max_iterations=5)
        task = Task("test", Domain("general", "general"))
        messages, raw_result = loop.run(task)
        assert isinstance(messages, list)
        assert messages[0]["role"] == "system"
        assert raw_result.eval_result == ""
        mock_layers.post_task.assert_not_called()

    def test_run_returns_eval_fields(self, mock_llm, mock_tools, mock_layers):
        mock_layers.check_completion.return_value = "done"
        loop = AgentLoop(mock_llm, mock_tools, mock_layers, max_iterations=5)
        task = Task("test", Domain("general", "general"))
        _, raw_result = loop.run(task)
        assert hasattr(raw_result, "eval_result")
        assert hasattr(raw_result, "eval_score")

    def test_reflect_calls_post_task(self, mock_llm, mock_tools, mock_layers):
        loop = AgentLoop(mock_llm, mock_tools, mock_layers, max_iterations=5)
        task = Task("test", Domain("general", "general"))
        raw_result = TaskResult(success=True, eval_result="success", eval_score=0.9)
        result = loop.reflect(task, ["dummy"], raw_result)
        mock_layers.post_task.assert_called_once()
        assert result is not None

    def test_existing_run_test_still_passes(self, mock_llm, mock_tools, mock_layers):
        """Backward compat: CognitiveAgent.run() should still work via exec+reflect"""
        mock_layers.check_completion.return_value = "done"
        loop = AgentLoop(mock_llm, mock_tools, mock_layers, max_iterations=5)
        task = Task("test", Domain("general", "general"))
        messages, raw_result = loop.run(task)
        final = loop.reflect(task, messages, raw_result)
        assert final.success is True


# tests/test_task.py (append to class TestTask)
class TestTaskResult:
    def test_task_result_eval_fields(self):
        tr = TaskResult(success=True, eval_result="success", eval_score=0.95)
        assert tr.eval_result == "success"
        assert tr.eval_score == 0.95

    def test_task_result_default_eval(self):
        tr = TaskResult()
        assert tr.eval_result == ""
        assert tr.eval_score == 0.0
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_agent_loop.py::TestAgentLoopSeparated -v
pytest tests/test_task.py::TestTaskResult -v
```
Expected: FAIL (AgentLoop.run returns TaskResult not tuple; TaskResult missing eval fields)

- [ ] **Step 3: Add eval_result and eval_score to TaskResult**

In `core/task.py`, modify `TaskResult`:

```python
# core/task.py — modify TaskResult dataclass
@dataclass
class TaskResult:
    success: bool = False
    final_response: str = ""
    new_knowledge_cards: int = 0
    l1_changes: list[str] = field(default_factory=list)
    l1_rejections: list[str] = field(default_factory=list)
    new_skills: list[str] = field(default_factory=list)
    iterations_used: int = 0
    summary: str = ""
    eval_result: str = ""
    eval_score: float = 0.0
```

- [ ] **Step 4: Refactor AgentLoop.run() to return (messages, TaskResult) and add reflect()**

Modify `core/agent_loop.py`:

```python
from __future__ import annotations
import json
import logging
from core.task import Task, TaskResult

logger = logging.getLogger(__name__)


class AgentLoop:
    def __init__(self, llm_client, tool_registry, layers, max_iterations: int = 50):
        self.llm = llm_client
        self.tools = tool_registry
        self.layers = layers
        self.max_iterations = max_iterations

    def run(self, task: Task) -> tuple[list, TaskResult]:
        """Execute phase only. Returns (messages_log, raw_result)."""
        messages = []
        iteration = 0
        self.layers.meta.reset_turn_state()

        system_prompt = self._build_system_prompt(task)
        messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": task.description})

        raw_result = TaskResult()

        while iteration < self.max_iterations:
            iteration += 1

            context_block = self.layers.build_context(task)
            if context_block:
                messages[-1]["content"] += "\n\n" + context_block

            try:
                response = self._call_llm(messages)
            except Exception as e:
                logger.warning("LLM call failed (iteration %s): %s", iteration, e)
                continue

            if response.has_tool_calls:
                filtered = self.layers.filter_tool_calls(response.tool_calls)

                assistant_msg = {
                    "role": "assistant",
                    "content": response.text or "",
                    "tool_calls": [
                        {
                            "id": f"call_{i}",
                            "type": "function",
                            "function": {
                                "name": tc.function.name,
                                "arguments": getattr(tc.function, 'arguments', '{}'),
                            }
                        }
                        for i, tc in enumerate(filtered)
                    ]
                }
                messages.append(assistant_msg)

                tool_results = []
                for i, tc in enumerate(filtered):
                    try:
                        args = json.loads(getattr(tc.function, 'arguments', '{}'))
                    except (json.JSONDecodeError, TypeError):
                        args = {}
                    raw_result_text = self.tools.dispatch(tc.function.name, args)
                    messages.append({
                        "role": "tool",
                        "name": tc.function.name,
                        "content": raw_result_text,
                        "tool_call_id": f"call_{i}",
                    })
                    tool_results.append((tc.function.name, raw_result_text))

                self.layers.on_tool_results(task, tool_results)
            else:
                messages.append({"role": "assistant", "content": response.text or ""})
                verdict = self.layers.check_completion(task, messages)
                if verdict == "done":
                    break

        raw_result.iterations_used = iteration
        raw_result.final_response = messages[-1].get("content", "") if messages else ""
        return messages, raw_result

    def reflect(self, task: Task, messages: list, raw_result: TaskResult) -> TaskResult:
        """Reflect & Learn phase. Calls post_task on layers."""
        result = self.layers.post_task(task, messages)
        result.iterations_used = raw_result.iterations_used
        result.final_response = raw_result.final_response
        result.eval_result = raw_result.eval_result
        result.eval_score = raw_result.eval_score
        result.success = raw_result.success or result.success
        return result

    def execute_and_reflect(self, task: Task) -> TaskResult:
        """Convenience: run + reflect in one call for backward compat."""
        messages, raw_result = self.run(task)
        return self.reflect(task, messages, raw_result)

    def _call_llm(self, messages):
        resp = self.llm.chat(
            messages=messages,
            tools=self.tools.schemas if hasattr(self.tools, 'schemas') else None,
        )
        if not hasattr(resp, 'has_tool_calls'):
            resp.has_tool_calls = False
            resp.text = str(resp)
        return resp

    def _build_system_prompt(self, task: Task) -> str:
        parts = [
            "You are a cognitive AI agent with a layered learning architecture. "
            "You can use tools to interact with your environment and create "
            "skills from successful patterns.",
            f"Current domain: {task.domain.path}",
        ]
        if hasattr(self.layers, 'l1') and self.layers.l1:
            rules = self.layers.l1.all_rules()
            if rules:
                parts.append(
                    "[Behavioral Principles — Your Philosophy]\n" +
                    "\n".join(f"- {r.content}" for r in rules) +
                    "\n\nThese principles guide your behavior. You may propose "
                    "additions or modifications through reflection after tasks."
                )
        parts.append(
            "Available tools: skills_list, skill_view, skill_manage, todo, terminal. "
            "Use skills_list() to see what skills are available. "
            "Use skill_view('skill-name') to load a skill's full content before using it."
        )
        return "\n\n".join(parts)
```

- [ ] **Step 5: Update CognitiveAgent.run() to use the two-phase pattern**

In `core/agent.py`, modify `run()`:

```python
def run(self, user_input: str, domain: Domain | None = None) -> any:
    task = Task(description=user_input, domain=domain or Domain("general", "general"))
    messages, raw_result = self.loop.run(task)
    return self.loop.reflect(task, messages, raw_result)
```

- [ ] **Step 6: Run tests to verify**

```bash
pytest tests/test_task.py::TestTaskResult -v
pytest tests/test_agent_loop.py::TestAgentLoopSeparated -v
pytest tests/test_agent_loop.py::TestAgentLoop -v
pytest tests/test_agent.py -v
pytest tests/test_layer_context.py -v
```
Expected: all PASS

- [ ] **Step 7: Run full test suite**

```bash
pytest tests/ -v
```
Expected: all PASS

- [ ] **Step 8: Commit**

```bash
git add core/task.py core/agent_loop.py core/agent.py tests/test_task.py tests/test_agent_loop.py
git commit -m "feat: separate execute/reflect phases, add eval_result/eval_score to TaskResult"
```

---

### Task 5: Create Environment Adapter interface

**Files:**
- Create: `core/env/__init__.py`
- Create: `core/env/base.py`
- Create: `tests/test_env.py`

**Note:** Abstract interface only. Phase 1 TextWorld adapter will implement this. Decouples environment interaction from Agent internals.

- [ ] **Step 1: Write failing tests for Environment adapter**

```python
# tests/test_env.py
import pytest
from core.env.base import Environment, EnvStep, EnvState


class FakeEnv(Environment):
    def reset(self, task_description: str) -> EnvState:
        return EnvState(observation="Start", info={})

    def step(self, action: str) -> EnvStep:
        return EnvStep(state=EnvState(observation="next", info={}), reward=1.0, done=True)


class TestEnvInterface:
    def test_reset_returns_state(self):
        env = FakeEnv()
        state = env.reset("find the key")
        assert state.observation == "Start"

    def test_step_returns_step(self):
        env = FakeEnv()
        env.reset("test")
        s = env.step("open door")
        assert s.reward == 1.0
        assert s.done is True

    def test_cannot_instantiate_abstract(self):
        with pytest.raises(TypeError):
            Environment()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_env.py -v
```
Expected: FAIL (module not found)

- [ ] **Step 3: Create `core/env/__init__.py` and `core/env/base.py`**

```python
# core/env/__init__.py
from core.env.base import Environment, EnvState, EnvStep

__all__ = ["Environment", "EnvState", "EnvStep"]
```

```python
# core/env/base.py
from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class EnvState:
    observation: str
    info: dict = field(default_factory=dict)


@dataclass
class EnvStep:
    state: EnvState
    reward: float
    done: bool


class Environment(ABC):
    @abstractmethod
    def reset(self, task_description: str) -> EnvState:
        ...

    @abstractmethod
    def step(self, action: str) -> EnvStep:
        ...
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_env.py -v
```
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add core/env/__init__.py core/env/base.py tests/test_env.py
git commit -m "feat: add Environment adapter interface (EnvState, EnvStep, Environment ABC)"
```

---

### Task 6: Create layer directory scaffolding with Agent stubs

**Files:**
- Create: `core/orchestrator/__init__.py`
- Create: `core/orchestrator/task_decomposer.py`
- Create: `core/orchestrator/task_runner.py`
- Create: `core/orchestrator/meta_learner.py`
- Create: `core/l0_5/__init__.py`
- Create: `core/l0_5/manager.py`
- Create: `core/l0_5/upward_comm.py`
- Create: `core/l0_5/downward_comm.py`
- Create: `core/l1/__init__.py`
- Create: `core/l1/manager.py`
- Create: `core/l1/upward_comm.py`
- Create: `core/l1/downward_comm.py`
- Create: `core/l2/__init__.py`
- Create: `core/l2/manager.py`
- Create: `core/l2/upward_comm.py`
- Create: `core/l2/downward_comm.py`
- Create: `core/l3/__init__.py`
- Create: `core/l3/manager.py`
- Create: `core/l3/upward_comm.py`
- Create: `core/l3/downward_comm.py`
- Create: `core/l4/__init__.py`
- Create: `core/l4/manager.py`
- Create: `core/l4/upward_comm.py`
- Create: `core/l4/downward_comm.py`
- Create: `tests/test_agent_stubs.py`

- [ ] **Step 1: Write test verifying all stubs exist and have required interface**

```python
# tests/test_agent_stubs.py
import pytest


STUB_DIRS = [
    "core.orchestrator.task_decomposer",
    "core.orchestrator.task_runner",
    "core.orchestrator.meta_learner",
    "core.l0_5.manager",
    "core.l0_5.upward_comm",
    "core.l0_5.downward_comm",
    "core.l1.manager",
    "core.l1.upward_comm",
    "core.l1.downward_comm",
    "core.l2.manager",
    "core.l2.upward_comm",
    "core.l2.downward_comm",
    "core.l3.manager",
    "core.l3.upward_comm",
    "core.l3.downward_comm",
    "core.l4.manager",
    "core.l4.upward_comm",
    "core.l4.downward_comm",
]


class TestAgentStubsExist:
    @pytest.mark.parametrize("module_name", STUB_DIRS)
    def test_module_importable(self, module_name):
        mod = __import__(module_name, fromlist=["AgentStub"])
        assert hasattr(mod, "AgentStub"), f"{module_name} missing AgentStub"


class TestAgentStubInterface:
    def test_orchestrator_stubs_have_correct_methods(self):
        from core.orchestrator.task_decomposer import AgentStub
        stub = AgentStub()
        assert callable(stub.decompose)
        assert callable(stub.receive)

    def test_manager_stubs_have_correct_methods(self):
        from core.l2.manager import AgentStub
        stub = AgentStub()
        assert callable(stub.receive)
        assert callable(stub.send)

    def test_comm_stubs_have_correct_methods(self):
        from core.l1.upward_comm import AgentStub
        stub = AgentStub()
        assert callable(stub.receive)
        assert callable(stub.send)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_agent_stubs.py -v
```
Expected: FAIL (modules not found)

- [ ] **Step 3: Create all directory scaffolding files**

Create orchestrator stubs:

```python
# core/orchestrator/__init__.py
"""Orchestrator layer: task decomposition, execution, meta-learning."""
```

```python
# core/orchestrator/task_decomposer.py
"""Task Decomposer — splits user input into evaluable Task units."""


class AgentStub:
    """TODO: Implement Task Decomposer orchestrator agent."""

    def decompose(self, user_input: str) -> list:
        """Split user input into independent Task objects."""
        return []

    def receive(self, message) -> None:
        pass
```

```python
# core/orchestrator/task_runner.py
"""Task Runner — manages execute/evaluate/reflect lifecycle for one Task."""


class AgentStub:
    """TODO: Implement Task Runner orchestrator agent."""

    def receive(self, message) -> None:
        pass
```

```python
# core/orchestrator/meta_learner.py
"""Meta Learner — cross-task pattern recognition, batch reflection."""


class AgentStub:
    """TODO: Implement Meta Learner orchestrator agent."""

    def receive(self, message) -> None:
        pass
```

Create layer stubs — pattern repeated for L0.5/L1/L2/L3/L4. Example for L2:

```python
# core/l2/__init__.py
"""L2: Flexible Knowledge — probabilistic knowledge cards with activation/decay."""
```

```python
# core/l2/manager.py
"""L2 Manager Agent — manages knowledge cards, activation, decay, graph."""


class AgentStub:
    """TODO: Implement L2 Manager. Currently FlexibleKnowledge class in core/."""

    def receive(self, message) -> None:
        pass

    def send(self, direction: str, payload) -> None:
        pass
```

```python
# core/l2/upward_comm.py
"""L2 UpwardComm Agent — handles communication with L1."""


class AgentStub:
    """TODO: Implement L2→L1 communication via LayerMessage."""

    def receive(self, message) -> None:
        pass

    def send(self, payload) -> None:
        pass
```

```python
# core/l2/downward_comm.py
"""L2 DownwardComm Agent — handles communication with L3."""


class AgentStub:
    """TODO: Implement L2→L3 communication via LayerMessage."""

    def receive(self, message) -> None:
        pass

    def send(self, payload) -> None:
        pass
```

**Repeat the same pattern for `core/l0_5/`, `core/l1/`, `core/l3/`, `core/l4/`** with their respective `__init__.py`, `manager.py`, `upward_comm.py`, `downward_comm.py`. Each file contains a docstring and `AgentStub` class with docstrings explaining the future purpose.

Specific docstrings per layer:

```
core/l0_5/manager.py     → "L0.5 Manager Agent — immutable constitution: triggers, validators, safety filters"
core/l1/manager.py       → "L1 Manager Agent — evolvable behavioral rules injected into system prompt"
core/l3/manager.py       → "L3 Manager Agent — semi-static skills (SKILL.md), L2→L3 compilation"
core/l4/manager.py       → "L4 Manager Agent — static knowledge base (Phase 2+)"
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_agent_stubs.py -v
```
Expected: PASS (19 parameterized + 2 interface tests)

- [ ] **Step 5: Run full test suite for regressions**

```bash
pytest tests/ -v
```
Expected: all PASS

- [ ] **Step 6: Commit**

```bash
git add core/orchestrator/ core/l0_5/ core/l1/ core/l2/ core/l3/ core/l4/ tests/test_agent_stubs.py
git commit -m "feat: erect layer directory scaffolding with Agent stubs (L0.5-L4 + Orchestrator)"
```

---

## Self-Review Checklist

- [x] **Spec coverage:** All 6 tasks map to R1-R6 from the design discussion. R1 (LLM cleanup) covered by Tasks 1+2. R2 (LayerMessage) by Task 3. R3 (Execute/Reflect separation) by Task 4. R4 (eval fields) by Task 4. R5 (env adapter) by Task 5. R6 (directory scaffolding) by Task 6.
- [x] **Placeholder scan:** No TODOs, TBDs, or "implement later" in steps. All code is complete. Agent stubs intentionally have empty method bodies with "TODO: Implement" docstrings — this is by design for scaffolding, not a placeholder in the plan.
- [x] **Type consistency:** `LLMResponse` defined in Task 1, used by `LLMClient` in same task. `LayerMessage` defined in Task 3, referenced in stub interfaces in Task 6. `EnvState`/`EnvStep` defined in Task 5. `eval_result`/`eval_score` added in Task 4, default values match.
- [x] **Backward compat:** Task 4 preserves `execute_and_reflect()` convenience method. `CognitiveAgent.run()` behavior unchanged from consumer perspective. All existing tests expected to pass after each task.
