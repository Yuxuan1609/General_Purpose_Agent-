# Agent Communication Architecture — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the new Execute communication chain (Runtime → Executor → L(0.5+1) → L2 → L3) with QUERY/RESPONSE/NOTIFY protocol, integrate with DouZero, and verify end-to-end.

**Architecture:** Three-layer chain (L(0.5+1) ↔ L2 ↔ L3) with Executor as external decision-maker. Each layer's Manager handles its own orchestration. Comm agents (UpwardComm/DownwardComm) deferred to Phase 2. Reflection pipeline deferred to Phase 2.

**Tech Stack:** Python 3.11+, dataclasses, pytest, existing `core/` modules (MetaDriver, Philosophy, FlexibleKnowledge, SkillLayer)

---

## File Structure

```
core/
  types.py                      # NEW: TaskObservation, ExecutionRecord, Session
  executor.py                   # NEW: Executor class
  layers/
    __init__.py                  # NEW: LayerChain orchestrator
    base.py                      # NEW: LayerManager ABC
    l0_5_1/
      __init__.py                # NEW
      manager.py                 # NEW: wraps MetaDriver + Philosophy
    l2/
      __init__.py                # NEW
      manager.py                 # NEW: wraps FlexibleKnowledge
    l3/
      __init__.py                # NEW
      manager.py                 # NEW: wraps SkillLayer

  task.py                       # MODIFY: add enable_learning to Task
  config.py                     # MODIFY: add learning config fields

scripts/
  douzero_agent.py              # MODIFY: integrate with Executor

tests/
  test_types.py                 # NEW
  test_executor.py              # NEW
  test_layers.py                # NEW
  test_layer_chain.py           # NEW

config.yaml                     # MODIFY: add learning config section
```

---

### Task 1: New core types

**Files:**
- Create: `core/types.py`
- Modify: `core/task.py:37-44`

- [ ] **Step 1: Write tests for new types**

Create `tests/test_types.py`:

```python
from core.types import TaskObservation, ExecutionRecord
from core.task import Task, Domain


class TestTaskObservation:
    def test_defaults(self):
        obs = TaskObservation()
        assert obs.meta == {}
        assert obs.state == {}
        assert obs.history is None

    def test_with_history(self):
        obs = TaskObservation(history=[{"role": "agent", "action": "33"}])
        assert len(obs.history) == 1

    def test_meta_field_setter(self):
        obs = TaskObservation()
        obs.meta["domain"] = "game/doudizhu"
        obs.meta["enable_learning"] = True
        assert obs.meta["domain"] == "game/doudizhu"
        assert obs.meta["enable_learning"] is True


class TestExecutionRecord:
    def test_defaults(self):
        rec = ExecutionRecord()
        assert rec.session == {}
        assert rec.observation == {}
        assert rec.notify_layers == {}

    def test_full_record(self):
        rec = ExecutionRecord(
            session={"id": "s1", "datetime": "2026-01-01T00:00:00", "meta_hash": "abc"},
            observation={"meta": {"domain": "game/doudizhu"}},
            notify_layers={"l0_5_1": "ok", "l2": "ok", "l3": "ok"},
            action=[3, 3],
            result={"winner": "landlord"},
        )
        assert rec.action == [3, 3]
        assert rec.result["winner"] == "landlord"


class TestTaskEnableLearning:
    def test_enable_learning_defaults_to_false(self):
        task = Task(description="test")
        assert task.enable_learning is False

    def test_enable_learning_true(self):
        task = Task(description="test", enable_learning=True)
        assert task.enable_learning is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_types.py -v`
Expected: FAIL — module not found or attribute not found

- [ ] **Step 3: Create `core/types.py`**

```python
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any


@dataclass
class TaskObservation:
    """Environment observation consumed by all cognitive layers.

    Fields:
        meta:    Task metadata (role, goal, domain). Populated by comm layer.
                 Layers append their enrichment to meta during chain processing.
        state:   Task-specific state (game board, code context, search results).
                 Populated by comm layer.
        history: Past interactions. None = history not needed for this task type.
                 When present, already trimmed by comm layer.
    """
    meta: dict = field(default_factory=dict)
    state: dict = field(default_factory=dict)
    history: list | None = None


@dataclass
class ExecutionRecord:
    """Archive produced by Executor after each execute cycle.

    Used for the learning pipeline: written to data/learning/pending/,
    moved to data/learning/learned/{domain}/ after reflection.
    """
    session: dict = field(default_factory=dict)        # {id, datetime, meta_hash}
    observation: dict = field(default_factory=dict)     # raw TaskObservation
    notify_layers: dict = field(default_factory=dict)   # {layer_name: notify_payload}
    action: Any = None                                  # final action returned to env
    result: Any = None                                  # env reward/outcome
```

- [ ] **Step 4: Modify `core/task.py` — add `enable_learning` field to Task**

```python
# In core/task.py, modify the Task dataclass (line 37-44):
@dataclass
class Task:
    """A user request with a defined domain and evaluation criteria."""
    description: str
    domain: Domain = field(default_factory=lambda: Domain("general", "general"))
    context: str = ""
    needs_decomposition: bool = False
    subtasks: list[Task] = field(default_factory=list)
    enable_learning: bool = False
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_types.py -v`
Expected: all PASS

- [ ] **Step 6: Commit**

```bash
git add core/types.py core/task.py tests/test_types.py
git commit -m "feat: add TaskObservation, ExecutionRecord, enable_learning"
```

---

### Task 2: LayerManager ABC and LayerChain

**Files:**
- Create: `core/layers/base.py`
- Create: `core/layers/__init__.py`
- Create: `tests/test_layer_chain.py`

- [ ] **Step 1: Write tests for LayerChain**

```python
import pytest
from core.types import TaskObservation
from core.layers.base import LayerManager

# --- Mock managers for testing ---

class MockL3Manager(LayerManager):
    """Returns basic skill match info."""
    def __init__(self):
        super().__init__("l3")
    def process(self, obs: TaskObservation) -> dict:
        obs.meta["l3_skills"] = ["skill_a", "skill_b"]
        return {"status": "ok", "skills_found": 2}
    def notify(self) -> Any:
        return {"l3_result": "all_good"}


class MockL2Manager(LayerManager):
    """Adds knowledge card info."""
    def __init__(self, downstream: LayerManager | None = None):
        super().__init__("l2", downstream)
    def process(self, obs: TaskObservation) -> dict:
        obs.meta["l2_cards"] = [{"content": "trick: play high cards", "activation": 0.8}]
        return {"status": "ok", "cards_found": 1}
    def notify(self) -> Any:
        return {"l2_result": "all_good"}


class MockL0_5_1Manager(LayerManager):
    """Adds behavioral rules."""
    def __init__(self, downstream: LayerManager | None = None):
        super().__init__("l0_5_1", downstream)
    def process(self, obs: TaskObservation) -> dict:
        obs.meta["l1_rules"] = ["优先出大牌"]
        return {"status": "ok", "rules_applied": 1}
    def notify(self) -> Any:
        return {"l0_5_1_result": "all_good"}


class TestLayerChain:
    def test_query_flows_top_down(self):
        """QUERY propagates from L0.5+1 → L2 → L3."""
        l3 = MockL3Manager()
        l2 = MockL2Manager(downstream=l3)
        l1 = MockL0_5_1Manager(downstream=l2)

        obs = TaskObservation(meta={"domain": "game/doudizhu"})
        l1.query(obs)

        assert obs.meta["l1_rules"] == ["优先出大牌"]
        assert obs.meta["l2_cards"][0]["content"] == "trick: play high cards"
        assert obs.meta["l3_skills"] == ["skill_a", "skill_b"]

    def test_notify_collects_all_layers(self):
        """NOTIFY gathers from all layers after RESPONSE completes."""
        l3 = MockL3Manager()
        l2 = MockL2Manager(downstream=l3)
        l1 = MockL0_5_1Manager(downstream=l2)

        obs = TaskObservation()
        l1.query(obs)

        notifications = l1.collect_notify()
        assert "l0_5_1" in notifications
        assert "l2" in notifications
        assert "l3" in notifications
        assert notifications["l3"]["l3_result"] == "all_good"

    def test_collect_notify_returns_shallow_copy(self):
        l3 = MockL3Manager()
        l2 = MockL2Manager(downstream=l3)
        l1 = MockL0_5_1Manager(downstream=l2)

        obs = TaskObservation()
        l1.query(obs)

        n1 = l1.collect_notify()
        n1["extra"] = "mutated"
        n2 = l1.collect_notify()
        assert "extra" not in n2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_layer_chain.py -v`
Expected: FAIL

- [ ] **Step 3: Create `core/layers/base.py`**

```python
from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Any


class LayerManager(ABC):
    """Abstract base for all layer Manager agents.

    Each Manager:
      - process(data) → enriches data with its layer's information → calls downstream
      - query(data) → entry point for the QUERY chain
      - collect_notify() → gathers NOTIFY payloads from self + all downstream
    """

    def __init__(self, name: str, downstream: LayerManager | None = None):
        self.name = name
        self._downstream = downstream
        self._last_notify: Any = None

    @abstractmethod
    def process(self, data: Any) -> dict:
        """Enrich data with this layer's information.

        Returns a dict with status info for the RESPONSE chain.
        Must update `data` in-place with layer-specific fields.
        """
        ...

    @abstractmethod
    def notify(self) -> Any:
        """Return the payload for this layer's NOTIFY to the Executor."""
        ...

    def query(self, data: Any) -> None:
        """Entry point: process this layer, then propagate downstream.

        Override in subclasses if pre/post-processing is needed around
        the downstream call.
        """
        self.process(data)
        if self._downstream:
            self._downstream.query(data)

    def collect_notify(self) -> dict:
        """Collect NOTIFY payloads from this layer and all downstream layers.

        Returns: {layer_name: notify_payload, ...}
        """
        result: dict = {}
        result[self.name] = self.notify()
        if self._downstream:
            result.update(self._downstream.collect_notify())
        return result
```

- [ ] **Step 4: Create `core/layers/__init__.py`**

```python
"""Layer package — three-layer cognitive chain."""

from core.layers.base import LayerManager

__all__ = ["LayerManager"]
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_layer_chain.py -v`
Expected: all PASS

- [ ] **Step 6: Commit**

```bash
git add core/layers/ tests/test_layer_chain.py
git commit -m "feat: add LayerManager ABC and chain tests"
```

---

### Task 3: L3 Manager (wraps SkillLayer)

**Files:**
- Create: `core/layers/l3/__init__.py`
- Create: `core/layers/l3/manager.py`
- Create: `tests/test_layers.py` (add L3 tests)

- [ ] **Step 1: Write L3 Manager test**

In `tests/test_layers.py`:

```python
import pytest
from pathlib import Path
from core.types import TaskObservation
from core.task import Domain
from core.layers.l3.manager import L3Manager


@pytest.fixture
def l3_skill_layer(tmp_path):
    from core.skill_layer import SkillLayer
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    from core.tools.registry import ToolRegistry
    return SkillLayer(skills_dir, ToolRegistry())


class TestL3Manager:
    def test_process_adds_skills_to_meta(self, l3_skill_layer, tmp_path):
        # Create a skill first
        domain = Domain("game/doudizhu", "specific")
        l3_skill_layer.create_skill(
            name="test-skill",
            content="---\nname: test-skill\ndescription: A test skill\ndomain: game/doudizhu\n---\n# Test",
            domain=domain,
        )

        manager = L3Manager(l3_skill_layer)
        obs = TaskObservation(meta={"domain": "game/doudizhu"})
        result = manager.process(obs)

        assert "l3_skills" in obs.meta
        assert result["status"] == "ok"

    def test_process_handles_no_match(self, l3_skill_layer):
        manager = L3Manager(l3_skill_layer)
        obs = TaskObservation(meta={"domain": "game/doudizhu"})
        result = manager.process(obs)

        assert result["status"] == "ok"
        assert obs.meta["l3_skills"] == []

    def test_notify_returns_payload(self, l3_skill_layer):
        manager = L3Manager(l3_skill_layer)
        payload = manager.notify()
        assert "status" in payload
        assert payload["layer"] == "l3"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_layers.py::TestL3Manager -v`
Expected: FAIL

- [ ] **Step 3: Create `core/layers/l3/manager.py`**

```python
from __future__ import annotations
from typing import Any
from core.task import Domain
from core.types import TaskObservation
from core.layers.base import LayerManager


class L3Manager(LayerManager):
    """L3 Manager — wraps SkillLayer, matches skills to task domain."""

    def __init__(self, skill_layer, downstream: LayerManager | None = None):
        super().__init__("l3", downstream)
        self._skill_layer = skill_layer

    def process(self, data: Any) -> dict:
        obs: TaskObservation = data
        domain_path = obs.meta.get("domain", "general")

        try:
            domain = Domain(domain_path, "specific")
        except Exception:
            domain = Domain("general", "general")

        matched = self._skill_layer.match(domain)
        obs.meta["l3_skills"] = [
            {"name": s.name, "description": s.description, "domain": s.domain.path}
            for s in matched
        ]
        return {"status": "ok", "skills_matched": len(matched)}

    def notify(self) -> Any:
        return {"status": "ok", "layer": "l3"}
```

- [ ] **Step 4: Create `core/layers/l3/__init__.py`**

```python
from core.layers.l3.manager import L3Manager

__all__ = ["L3Manager"]
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_layers.py::TestL3Manager -v`
Expected: all PASS

- [ ] **Step 6: Commit**

```bash
git add core/layers/l3/ tests/test_layers.py
git commit -m "feat: add L3 Manager wrapping SkillLayer"
```

---

### Task 4: L2 Manager (wraps FlexibleKnowledge)

**Files:**
- Create: `core/layers/l2/__init__.py`
- Create: `core/layers/l2/manager.py`
- Modify: `tests/test_layers.py` (add L2 tests)

- [ ] **Step 1: Write L2 Manager test**

Append to `tests/test_layers.py`:

```python
from core.layers.l2.manager import L2Manager


@pytest.fixture
def l2_knowledge(tmp_path):
    from core.flexible_knowledge import FlexibleKnowledge
    knowledge_dir = tmp_path / "knowledge"
    knowledge_dir.mkdir()
    index_path = knowledge_dir / "l2_index.json"
    index_path.write_text('{"version":1,"chapters":[],"relations":[]}')
    fk = FlexibleKnowledge(knowledge_dir, index_path)
    return fk


class TestL2Manager:
    def test_process_adds_cards_to_meta(self, l2_knowledge):
        from core.task import Domain
        domain = Domain("game/doudizhu", "specific")
        card = l2_knowledge.add_card(
            content="地主上家应优先出单张",
            domain=domain,
            confidence=0.8,
            source="observation",
        )
        card.activation = 0.9

        manager = L2Manager(l2_knowledge)
        obs = TaskObservation(meta={"domain": "game/doudizhu"})
        result = manager.process(obs)

        assert "l2_cards" in obs.meta
        assert len(obs.meta["l2_cards"]) >= 1
        assert result["status"] == "ok"

    def test_process_no_cards(self, l2_knowledge):
        manager = L2Manager(l2_knowledge)
        obs = TaskObservation(meta={"domain": "game/doudizhu"})
        result = manager.process(obs)

        assert result["status"] == "ok"
        assert obs.meta["l2_cards"] == []

    def test_notify_returns_payload(self, l2_knowledge):
        manager = L2Manager(l2_knowledge)
        payload = manager.notify()
        assert "status" in payload
        assert payload["layer"] == "l2"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_layers.py::TestL2Manager -v`
Expected: FAIL

- [ ] **Step 3: Create `core/layers/l2/manager.py`**

```python
from __future__ import annotations
from typing import Any
from core.task import Domain
from core.types import TaskObservation
from core.layers.base import LayerManager


class L2Manager(LayerManager):
    """L2 Manager — wraps FlexibleKnowledge, retrieves top-k active cards."""

    def __init__(self, knowledge, downstream: LayerManager | None = None):
        super().__init__("l2", downstream)
        self._knowledge = knowledge

    def process(self, data: Any) -> dict:
        obs: TaskObservation = data
        domain_path = obs.meta.get("domain", "general")

        try:
            domain = Domain(domain_path, "specific")
        except Exception:
            domain = Domain("general", "general")

        active = self._knowledge.get_active_cards(domain, obs.meta.get("context", ""), top_k=5)
        obs.meta["l2_cards"] = [
            {
                "content": c.content,
                "confidence": c.confidence,
                "activation": c.activation,
                "domain": c.domain.path,
            }
            for c in active
        ]
        return {"status": "ok", "cards_found": len(active)}

    def notify(self) -> Any:
        return {"status": "ok", "layer": "l2"}
```

- [ ] **Step 4: Create `core/layers/l2/__init__.py`**

```python
from core.layers.l2.manager import L2Manager

__all__ = ["L2Manager"]
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_layers.py::TestL2Manager -v`
Expected: all PASS

- [ ] **Step 6: Commit**

```bash
git add core/layers/l2/ tests/test_layers.py
git commit -m "feat: add L2 Manager wrapping FlexibleKnowledge"
```

---

### Task 5: L(0.5+1) Manager (wraps MetaDriver + Philosophy)

**Files:**
- Create: `core/layers/l0_5_1/__init__.py`
- Create: `core/layers/l0_5_1/manager.py`
- Modify: `tests/test_layers.py` (add L0.5+1 tests)

- [ ] **Step 1: Write L0.5+1 Manager test**

Append to `tests/test_layers.py`:

```python
from core.layers.l0_5_1.manager import L0_5_1Manager


@pytest.fixture
def l1_philosophy(tmp_path):
    from core.philosophy import Philosophy
    rules_path = tmp_path / "l1_rules.json"
    rules_path.write_text('{"version":1,"rules":[]}')
    return Philosophy(rules_path, max_rules=20, max_rule_length=100)


@pytest.fixture
def l0_5_meta():
    from core.meta_driver import MetaDriver, DEFAULT_TRIGGERS, DEFAULT_VALIDATORS
    return MetaDriver(
        triggers=DEFAULT_TRIGGERS.copy(),
        validation_rules=DEFAULT_VALIDATORS.copy(),
        auxiliary_llm=None,
    )


class TestL0_5_1Manager:
    def test_process_adds_rules_to_meta(self, l0_5_meta, l1_philosophy):
        l1_philosophy.add_rule("面对不确定信息时优先搜索验证", created_by="test")

        manager = L0_5_1Manager(l0_5_meta, l1_philosophy, auxiliary_llm=None)
        obs = TaskObservation(meta={"domain": "game/doudizhu"})
        result = manager.process(obs)

        assert "l1_rules" in obs.meta
        assert len(obs.meta["l1_rules"]) >= 1
        assert result["status"] == "ok"

    def test_process_no_rules(self, l0_5_meta, l1_philosophy):
        manager = L0_5_1Manager(l0_5_meta, l1_philosophy, auxiliary_llm=None)
        obs = TaskObservation(meta={"domain": "game/doudizhu"})
        result = manager.process(obs)

        assert result["status"] == "ok"
        assert obs.meta["l1_rules"] == []

    def test_filter_dangerous_calls(self, l0_5_meta, l1_philosophy):
        manager = L0_5_1Manager(l0_5_meta, l1_philosophy, auxiliary_llm=None)
        obs = TaskObservation(meta={"domain": "game/doudizhu"})

        obs.meta["tool_calls"] = [
            {"function": {"name": "safe_tool"}},
            {"function": {"name": "rm -rf"}},
        ]

        manager.process(obs)
        filtered = obs.meta.get("filtered_tool_calls", [])
        names = [tc["function"]["name"] for tc in filtered]
        assert "rm -rf" not in names
        assert "safe_tool" in names

    def test_notify_returns_payload(self, l0_5_meta, l1_philosophy):
        manager = L0_5_1Manager(l0_5_meta, l1_philosophy, auxiliary_llm=None)
        payload = manager.notify()
        assert "status" in payload
        assert payload["layer"] == "l0_5_1"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_layers.py::TestL0_5_1Manager -v`
Expected: FAIL

- [ ] **Step 3: Create `core/layers/l0_5_1/manager.py`**

```python
from __future__ import annotations
from typing import Any
from core.task import Domain, Task
from core.types import TaskObservation
from core.layers.base import LayerManager


class L0_5_1Manager(LayerManager):
    """L(0.5+1) Manager — wraps MetaDriver + Philosophy.

    Immutable L0.5: safety filters, triggers (not yet invoked in execute phase).
    Mutable L1: behavioral rules injected into system prompt.
    """

    def __init__(self, meta_driver, philosophy, auxiliary_llm=None,
                 downstream: LayerManager | None = None):
        super().__init__("l0_5_1", downstream)
        self._meta = meta_driver
        self._philosophy = philosophy
        self._aux_llm = auxiliary_llm

    def process(self, data: Any) -> dict:
        obs: TaskObservation = data

        # L1: inject active behavioral rules
        rules = self._philosophy.all_rules()
        obs.meta["l1_rules"] = [r.content for r in rules]

        # L0.5: filter dangerous tool calls if any are present
        tool_calls = obs.meta.get("tool_calls")
        if tool_calls:
            from core.llm_client import ToolCall, FunctionCall
            tc_list = [ToolCall(function=FunctionCall(**tc["function"])) for tc in tool_calls]
            filtered = self._meta.filter_dangerous(tc_list)
            obs.meta["filtered_tool_calls"] = [
                {"function": {"name": tc.function.name}} for tc in filtered
            ]

        return {"status": "ok", "rules_count": len(rules)}

    def notify(self) -> Any:
        return {"status": "ok", "layer": "l0_5_1"}
```

- [ ] **Step 4: Create `core/layers/l0_5_1/__init__.py`**

```python
from core.layers.l0_5_1.manager import L0_5_1Manager

__all__ = ["L0_5_1Manager"]
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_layers.py::TestL0_5_1Manager -v`
Expected: all PASS

- [ ] **Step 6: Commit**

```bash
git add core/layers/l0_5_1/ tests/test_layers.py
git commit -m "feat: add L0.5+1 Manager wrapping MetaDriver + Philosophy"
```

---

### Task 6: Executor

**Files:**
- Create: `core/executor.py`
- Create: `tests/test_executor.py`

- [ ] **Step 1: Write Executor tests**

Create `tests/test_executor.py`:

```python
import pytest
from unittest.mock import Mock
from core.types import TaskObservation
from core.layers.base import LayerManager


class _MockLayer(LayerManager):
    def __init__(self, name, notify_data=None, downstream=None):
        super().__init__(name, downstream)
        self._notify_data = notify_data or {}
    def process(self, data):
        data.meta[f"{self.name}_seen"] = True
        return {"status": "ok"}
    def notify(self):
        return self._notify_data


@pytest.fixture
def mock_llm():
    llm = Mock()
    llm.chat.return_value = Mock(text="33", tool_calls=[], has_tool_calls=False)
    return llm


@pytest.fixture
def layer_chain():
    l3 = _MockLayer("l3", notify_data={"skills": 2})
    l2 = _MockLayer("l2", notify_data={"cards": 3}, downstream=l3)
    l1 = _MockLayer("l0_5_1", notify_data={"rules": 5}, downstream=l2)
    return l1


class TestExecutor:
    def test_execute_runs_full_chain(self, mock_llm, layer_chain):
        from core.executor import Executor

        executor = Executor(
            layer_root=layer_chain,
            llm_client=mock_llm,
            max_tokens=512,
        )

        obs = TaskObservation(
            meta={"domain": "game/doudizhu", "enable_learning": False},
            state={"hand": "3 4 5 6 7"},
        )

        result = executor.execute(obs)

        assert "action_text" in result
        assert "context" in result
        assert obs.meta["l0_5_1_seen"]
        assert obs.meta["l2_seen"]
        assert obs.meta["l3_seen"]

    def test_execute_returns_notify_data(self, mock_llm, layer_chain):
        from core.executor import Executor

        executor = Executor(layer_root=layer_chain, llm_client=mock_llm)

        obs = TaskObservation()
        result = executor.execute(obs)

        assert "notify_layers" in result
        assert result["notify_layers"]["l0_5_1"]["rules"] == 5
        assert result["notify_layers"]["l2"]["cards"] == 3
        assert result["notify_layers"]["l3"]["skills"] == 2

    def test_execute_writes_pending_when_learning_enabled(self, mock_llm, layer_chain, tmp_path):
        from core.executor import Executor
        import json

        learning_dir = tmp_path / "data" / "learning"
        executor = Executor(
            layer_root=layer_chain,
            llm_client=mock_llm,
            learning_dir=learning_dir,
        )

        obs = TaskObservation(
            meta={"domain": "game/doudizhu", "enable_learning": True},
            state={"session": {"id": "test-session", "datetime": "2026-01-01", "meta_hash": "abc"}},
        )

        executor.execute(obs)

        pending = learning_dir / "pending"
        assert pending.exists()
        files = list(pending.glob("*.json"))
        assert len(files) == 1

        with open(files[0]) as f:
            rec = json.load(f)
        assert rec["session"]["id"] == "test-session"
        assert "notify_layers" in rec

    def test_execute_skips_pending_when_learning_disabled(self, mock_llm, layer_chain, tmp_path):
        from core.executor import Executor

        learning_dir = tmp_path / "data" / "learning"
        executor = Executor(
            layer_root=layer_chain,
            llm_client=mock_llm,
            learning_dir=learning_dir,
        )

        obs = TaskObservation(
            meta={"domain": "game/doudizhu", "enable_learning": False},
            state={"session": {"id": "s1"}},
        )

        executor.execute(obs)
        pending = learning_dir / "pending"
        assert not pending.exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_executor.py -v`
Expected: FAIL

- [ ] **Step 3: Create `core/executor.py`**

```python
from __future__ import annotations
import json
import logging
import tempfile
from pathlib import Path
from typing import Any

from core.types import TaskObservation, ExecutionRecord

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
        self._root.query(obs)
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_executor.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add core/executor.py tests/test_executor.py
git commit -m "feat: add Executor with chain orchestration and learning pipeline write"
```

---

### Task 7: LayerChain factory

**Files:**
- Modify: `core/layers/__init__.py`

- [ ] **Step 1: Add LayerChain factory function**

Replace `core/layers/__init__.py`:

```python
"""Layer package — three-layer cognitive chain."""

from core.layers.base import LayerManager
from core.layers.l0_5_1.manager import L0_5_1Manager
from core.layers.l2.manager import L2Manager
from core.layers.l3.manager import L3Manager


def build_chain(meta_driver, philosophy, flexible_knowledge, skill_layer,
                auxiliary_llm=None) -> L0_5_1Manager:
    """Build the three-layer chain bottom-up.

    Returns the root (L0.5+1 Manager) which has L2 and L3 wired in.
    """
    l3 = L3Manager(skill_layer)
    l2 = L2Manager(flexible_knowledge, downstream=l3)
    l1 = L0_5_1Manager(meta_driver, philosophy, auxiliary_llm=auxiliary_llm,
                       downstream=l2)
    return l1


__all__ = ["LayerManager", "L0_5_1Manager", "L2Manager", "L3Manager", "build_chain"]
```

- [ ] **Step 2: Verify existing tests still pass**

Run: `pytest tests/test_layer_chain.py tests/test_layers.py tests/test_executor.py -v`
Expected: all PASS

- [ ] **Step 3: Commit**

```bash
git add core/layers/__init__.py
git commit -m "feat: add build_chain factory function"
```

---

### Task 8: Integrate Executor into DouZero agent

**Files:**
- Modify: `scripts/douzero_agent.py`
- Modify: `scripts/run_douzero_llm.py`

- [ ] **Step 1: Create `DouZeroCognitiveAgent` class in douzero_agent.py**

Add after the existing `DouZeroLLMAgent` class:

```python
class DouZeroCognitiveAgent:
    """DouZero agent that uses the Cognitive Agent architecture (Executor + LayerChain)."""

    def __init__(self, executor, position: str = 'landlord_up'):
        self._executor = executor
        self.position = position
        self._position_cn = POSITION_CN.get(position, position)

    def act(self, infoset) -> list[int]:
        if len(infoset.legal_actions) == 1:
            return infoset.legal_actions[0]

        obs = TaskObservation(
            meta={
                "domain": "game/doudizhu",
                "role": self._position_cn,
                "enable_learning": False,
            },
            state=self._build_state(infoset),
            history=None,
        )

        result = self._executor.execute(obs)
        action_text = result["action_text"]
        action = self.parse_action(action_text, infoset.legal_actions)
        logger.info("CognitiveAgent action: %s", cards_to_str(action) if action else "pass")
        return action

    def _build_state(self, infoset) -> dict:
        hand = cards_to_str(infoset.player_hand_cards)
        nc = infoset.num_cards_left_dict
        left_str = (
            f"地主{nc.get('landlord', '?')}张  "
            f"上家{nc.get('landlord_up', '?')}张  "
            f"下家{nc.get('landlord_down', '?')}张"
        )

        last = infoset.last_move
        if last:
            last_pid = POSITION_CN.get(infoset.last_pid, infoset.last_pid or '')
            last_str = f"{cards_to_str(last)}（由{last_pid}打出）"
        else:
            last_str = '无（你是先手）'

        legal_lines = []
        for i, act in enumerate(infoset.legal_actions, 1):
            label = f"{i}. 不出（过）" if not act else f"{i}. {cards_to_str(act)}"
            legal_lines.append(label)

        system_text = _SYSTEM_PROMPT_TEMPLATE.format(position_cn=self._position_cn)
        user_text = f"你的手牌: {hand}\n剩余牌数: {left_str}\n上一手: {last_str}\n可选: {chr(10).join(legal_lines)}"

        return {
            "system_prompt": system_text,
            "prompt": user_text,
            "hand": hand,
            "hand_raw": infoset.player_hand_cards if hasattr(infoset, 'player_hand_cards') else [],
            "legal_actions": infoset.legal_actions,
        }

    def parse_action(self, llm_response: str, legal_actions: list[list[int]]) -> list[int]:
        """Reuse DouZeroLLMAgent's parsing logic."""
        from scripts.douzero_agent import DouZeroLLMAgent
        dummy = DouZeroLLMAgent.__new__(DouZeroLLMAgent)
        return DouZeroLLMAgent.parse_action(dummy, llm_response, legal_actions)
```

Note: Add `from core.types import TaskObservation` at top of file.

- [ ] **Step 2: Modify `run_douzero_llm.py` to support cognitive mode**

Add `--mode` argument. In `_make_agent()`:

```python
def _make_agent(
    position: str,
    agent_type: str,
    baselines_dir: str,
    objective: str,
    llm_client=None,
    perfect_info: bool = False,
    mode: str = "direct",
    layers=None,
):
    if agent_type == "llm":
        if mode == "cognitive":
            from scripts.douzero_agent import DouZeroCognitiveAgent
            from core.executor import Executor
            from core.layers import build_chain
            if layers is None:
                # Fallback: build chain from scratch
                from core.meta_driver import MetaDriver, DEFAULT_TRIGGERS, DEFAULT_VALIDATORS
                from core.philosophy import Philosophy
                from core.flexible_knowledge import FlexibleKnowledge
                from core.skill_layer import SkillLayer
                from core.tools.registry import ToolRegistry
                from pathlib import Path

                meta = MetaDriver(DEFAULT_TRIGGERS.copy(), DEFAULT_VALIDATORS.copy())
                phil = Philosophy(Path("./data/l1_rules.json"))
                fk = FlexibleKnowledge(Path("./knowledge"), Path("./knowledge/l2_index.json"))
                sl = SkillLayer(Path("./skills"), ToolRegistry())
                chain = build_chain(meta, phil, fk, sl)
            else:
                chain = layers
            executor = Executor(layer_root=chain, llm_client=llm_client)
            return DouZeroCognitiveAgent(executor=executor, position=position)
        else:
            from scripts.douzero_agent import DouZeroLLMAgent
            return DouZeroLLMAgent(llm_client=llm_client, position=position, use_perfect_info=perfect_info)
    elif agent_type == "random":
        ...
```

And add `--mode` argument to the parser:
```python
parser.add_argument("--mode", default="direct", choices=["direct", "cognitive"],
                    help="LLM agent mode: direct (bypass layers) or cognitive (full chain)")
```

- [ ] **Step 3: Run dry-run integration test**

```bash
python scripts/run_douzero_llm.py --dry_run --episodes 1 --mode cognitive
```
Expected: Script runs 1 episode without errors (using RandomAgent for LLM position).

- [ ] **Step 4: Commit**

```bash
git add scripts/douzero_agent.py scripts/run_douzero_llm.py
git commit -m "feat: add DouZeroCognitiveAgent with full layer chain integration"
```

---

### Task 9: End-to-end integration test

**Files:**
- Create: `tests/test_integration_cognitive.py`

- [ ] **Step 1: Write integration test**

```python
import pytest
from unittest.mock import Mock
from pathlib import Path
from core.types import TaskObservation
from core.layers import build_chain
from core.executor import Executor


@pytest.fixture
def mock_llm_with_action():
    llm = Mock()
    llm.chat.return_value = Mock(
        text="33",
        tool_calls=[],
        has_tool_calls=False,
    )
    return llm


@pytest.fixture
def full_chain(tmp_path):
    from core.meta_driver import MetaDriver, DEFAULT_TRIGGERS, DEFAULT_VALIDATORS
    from core.philosophy import Philosophy
    from core.flexible_knowledge import FlexibleKnowledge
    from core.skill_layer import SkillLayer
    from core.tools.registry import ToolRegistry

    rules_path = tmp_path / "l1_rules.json"
    rules_path.write_text('{"version":1,"rules":[{"id":"r1","content":"test rule","created_by":"seed","added_at":"","version":1,"last_modified":""}]}')

    knowledge_dir = tmp_path / "knowledge"
    knowledge_dir.mkdir()
    index_path = knowledge_dir / "l2_index.json"
    index_path.write_text('{"version":1,"chapters":[],"relations":[]}')

    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()

    meta = MetaDriver(DEFAULT_TRIGGERS.copy(), DEFAULT_VALIDATORS.copy())
    phil = Philosophy(rules_path)
    fk = FlexibleKnowledge(knowledge_dir, index_path)
    sl = SkillLayer(skills_dir, ToolRegistry())

    return build_chain(meta, phil, fk, sl)


class TestEndToEnd:
    def test_full_execute_chain(self, full_chain, mock_llm_with_action):
        executor = Executor(layer_root=full_chain, llm_client=mock_llm_with_action)

        obs = TaskObservation(
            meta={"domain": "game/doudizhu", "role": "地主上家"},
            state={"hand": "3 4 5 6 7", "legal_actions": "1. 33  2. 过"},
        )

        result = executor.execute(obs)

        assert "action_text" in result
        assert result["action_text"] == "33"
        assert "notify_layers" in result
        assert "l0_5_1" in result["notify_layers"]
        assert "l2" in result["notify_layers"]
        assert "l3" in result["notify_layers"]

    def test_meta_gets_rule_from_l1(self, full_chain, mock_llm_with_action):
        executor = Executor(layer_root=full_chain, llm_client=mock_llm_with_action)

        obs = TaskObservation(meta={"domain": "game/doudizhu"})
        executor.execute(obs)

        assert "l1_rules" in obs.meta
        assert len(obs.meta["l1_rules"]) >= 1

    def test_learning_disabled_no_pending_file(self, full_chain, mock_llm_with_action, tmp_path):
        learning_dir = tmp_path / "learning"
        executor = Executor(layer_root=full_chain, llm_client=mock_llm_with_action,
                           learning_dir=learning_dir)

        obs = TaskObservation(
            meta={"domain": "game/doudizhu", "enable_learning": False},
            state={"session": {"id": "s1"}},
        )
        executor.execute(obs)

        pending = learning_dir / "pending"
        assert not pending.exists()

    def test_learning_enabled_writes_pending(self, full_chain, mock_llm_with_action, tmp_path):
        learning_dir = tmp_path / "learning"
        executor = Executor(layer_root=full_chain, llm_client=mock_llm_with_action,
                           learning_dir=learning_dir)

        obs = TaskObservation(
            meta={"domain": "game/doudizhu", "enable_learning": True},
            state={"session": {"id": "learn-s1", "datetime": "2026-01-01", "meta_hash": "abc"}},
        )
        executor.execute(obs)

        pending = learning_dir / "pending"
        files = list(pending.glob("*.json"))
        assert len(files) == 1
```

- [ ] **Step 2: Run integration tests**

Run: `pytest tests/test_integration_cognitive.py -v`
Expected: all PASS

- [ ] **Step 3: Run all tests to verify no regressions**

Run: `pytest tests/ -v --tb=short`
Expected: all existing tests still PASS

- [ ] **Step 4: Commit**

```bash
git add tests/test_integration_cognitive.py
git commit -m "feat: add end-to-end integration test for cognitive chain"
```

---

### Task 10: Verify existing tests still pass and run live DouZero with cognitive mode

- [ ] **Step 1: Run full test suite**

```bash
pytest tests/ -v --tb=short
```
Expected: All tests pass (existing + new)

- [ ] **Step 2: Dry-run cognitive mode**

```bash
python scripts/run_douzero_llm.py --dry_run --episodes 3 --mode cognitive
```
Expected: 3 episodes complete without errors, random actions

- [ ] **Step 3: Live LLM cognitive mode (1 episode, quick test)**

```bash
python scripts/run_douzero_llm.py --episodes 1 --mode cognitive --llm_position landlord_up
```
Expected: 1 episode completes with actual LLM decisions

- [ ] **Step 4: Commit**

```bash
git commit -m "test: verify full test suite and cognitive mode end-to-end"
```

---

## Phase 2 (Subsequent — not in this plan)

1. **Task Decomposer** (`core/orchestrator/task_decomposer.py`) — rule-based strategy selector, DouZero stub
2. **Reflection pipeline** — pent/learned folder monitoring, domain-threshold scorer, Reflect coordinator
3. **ReflectionAgent per layer** — independent agent per layer for reflection dialogue
4. **Comm agents** — UpwardComm/DownwardComm per layer (separate from Manager)
5. **Tool decoupling** — `allowed_layers` on tools, per-layer tool filtering
6. **Config updates** — learning thresholds, weights, paths in config.yaml
7. **Full script migration** — Leduc, parallel tests use new architecture
