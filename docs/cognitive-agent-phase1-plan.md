# Cognitive Agent — Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a minimal 4-layer cognitive agent framework (~1,500 lines) with layered learning loop, borrowing tool/skill patterns from Hermes Agent.

**Architecture:** Bottom-up construction: types → tools → L3 → L2 → L1 → L0.5 → layer context → event loop → agent. Each layer has a well-defined interface tested independently before the next layer depends on it. TDD throughout.

**Tech Stack:** Python 3.11+, pytest, PyYAML, OpenAI SDK (for LLM calls). No database — L2 uses MD + JSON + runtime Graph.

**Design doc:** `C:\Users\micha\Documents\cognitive-agent-design-v2.md`
**Reference impl:** `C:\Users\micha\PycharmProjects\hermes-agent`

---

## File Structure

```
C:\Users\micha\PycharmProjects\cognitive-agent\
├── main.py                          # Entry point
├── config.yaml                      # User config
├── pyproject.toml                   # Dependencies
│
├── core/
│   ├── __init__.py
│   ├── task.py                      # Task, Domain, TaskResult, TaskContext
│   ├── config.py                    # AgentConfig
│   ├── agent.py                     # CognitiveAgent
│   ├── agent_loop.py                # Event loop with 5 insertion points
│   ├── layer_context.py             # LayerContext bridge
│   │
│   ├── meta_driver.py               # L0.5: triggers, validators, reflection
│   ├── philosophy.py                # L1: rules CRUD, active filter
│   ├── flexible_knowledge.py        # L2: KnowledgeCard, activation, MD+JSON+Graph
│   ├── skill_layer.py               # L3: skill CRUD, match, L2→L3 compilation
│   │
│   └── tools/
│       ├── __init__.py
│       ├── registry.py              # ToolRegistry (adapted from Hermes)
│       ├── skills_tool.py           # skills_list, skill_view
│       ├── skill_manager.py         # skill_manage: create/edit/patch
│       ├── todo_tool.py             # subtask tracking
│       └── terminal_tool.py         # environment command execution
│
├── data/
│   └── l1_rules.json                # L1 rule storage (seed + agent-created)
│
├── knowledge/                        # L2 knowledge store
│   ├── general/
│   │   └── .gitkeep
│   └── l2_index.json                # auto-maintained metadata index
│
├── skills/                           # L3 skill store (agentskills.io format)
│   └── general/
│       └── .gitkeep
│
└── tests/
    ├── __init__.py
    ├── conftest.py                   # Shared fixtures
    ├── test_task.py
    ├── test_tool_registry.py
    ├── test_skill_layer.py
    ├── test_flexible_knowledge.py
    ├── test_philosophy.py
    ├── test_meta_driver.py
    ├── test_layer_context.py
    ├── test_agent_loop.py
    └── test_agent.py
```

---

### Task 1: Project scaffold

**Files:**
- Create: `C:\Users\micha\PycharmProjects\cognitive-agent\pyproject.toml`
- Create: `C:\Users\micha\PycharmProjects\cognitive-agent\config.yaml`
- Create: `C:\Users\micha\PycharmProjects\cognitive-agent\core\__init__.py`
- Create: `C:\Users\micha\PycharmProjects\cognitive-agent\core\tools\__init__.py`
- Create: `C:\Users\micha\PycharmProjects\cognitive-agent\tests\__init__.py`
- Create: `C:\Users\micha\PycharmProjects\cognitive-agent\tests\conftest.py`
- Create: `C:\Users\micha\PycharmProjects\cognitive-agent\data\l1_rules.json`
- Create: `C:\Users\micha\PycharmProjects\cognitive-agent\knowledge\general\.gitkeep`
- Create: `C:\Users\micha\PycharmProjects\cognitive-agent\knowledge\l2_index.json`
- Create: `C:\Users\micha\PycharmProjects\cognitive-agent\skills\general\.gitkeep`

- [ ] **Step 1: Create project directory and pyproject.toml**

```bash
mkdir -p C:/Users/micha/PycharmProjects/cognitive-agent/{core/tools,tests,data,knowledge/general,skills/general}
```

```toml
# pyproject.toml
[project]
name = "cognitive-agent"
version = "0.1.0"
description = "4.5-layer cognitive architecture AI agent"
requires-python = ">=3.11"
dependencies = [
    "openai>=1.0.0",
    "pyyaml>=6.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0.0",
]

[tool.pytest.ini_options]
testpaths = ["tests"]
```

- [ ] **Step 2: Create config.yaml**

```yaml
# config.yaml
main_llm:
  provider: openrouter
  model: anthropic/claude-sonnet-4-20250514
  api_key_env: OPENROUTER_API_KEY

auxiliary_llm:
  provider: openrouter
  model: google/gemini-flash-2.0
  api_key_env: OPENROUTER_API_KEY

max_iterations: 50
l1_max_rules: 20
l1_max_rule_length: 100
```

- [ ] **Step 3: Create empty init files and seed data**

```bash
touch C:/Users/micha/PycharmProjects/cognitive-agent/core/__init__.py
touch C:/Users/micha/PycharmProjects/cognitive-agent/core/tools/__init__.py
touch C:/Users/micha/PycharmProjects/cognitive-agent/tests/__init__.py
```

```json
// data/l1_rules.json
{
  "version": 1,
  "rules": [
    {
      "id": "l1_001",
      "content": "面对不确定信息时优先搜索验证，不要直接假设答案",
      "created_by": "seed",
      "added_at": "2026-05-18T00:00:00Z",
      "version": 1,
      "last_modified": "2026-05-18T00:00:00Z"
    },
    {
      "id": "l1_002",
      "content": "当同一种方法连续失败时，主动换策略而非坚持原路径",
      "created_by": "seed",
      "added_at": "2026-05-18T00:00:00Z",
      "version": 1,
      "last_modified": "2026-05-18T00:00:00Z"
    }
  ]
}
```

```json
// knowledge/l2_index.json
{
  "version": 1,
  "updated_at": "2026-05-18T00:00:00Z",
  "chapters": [],
  "relations": []
}
```

- [ ] **Step 4: Create conftest.py with shared fixtures**

```python
# tests/conftest.py
import pytest
from pathlib import Path
import tempfile
import os

@pytest.fixture
def temp_dir():
    """Temporary directory that cleans up after test."""
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)

@pytest.fixture
def sample_domain():
    from core.task import Domain
    return Domain(path="textworld/map_A", level="specific")

@pytest.fixture
def general_domain():
    from core.task import Domain
    return Domain(path="general", level="general")

@pytest.fixture
def mock_llm_client():
    """LLM client that returns preset responses for testing."""
    from unittest.mock import MagicMock
    client = MagicMock()
    client.chat.return_value = MagicMock()
    client.chat.return_value.has_tool_calls = False
    client.chat.return_value.text = "Mock response"
    return client
```

- [ ] **Step 5: Run test to verify project loads**

```bash
cd C:/Users/micha/PycharmProjects/cognitive-agent && python -c "from core.task import Domain; d = Domain('general', 'general'); print(d.path)"
```
Expected: `general`

- [ ] **Step 6: Initialize git and commit**

```bash
cd C:/Users/micha/PycharmProjects/cognitive-agent && git init && git add -A && git commit -m "feat: project scaffold with config, seeds, test fixtures"
```

---

### Task 2: Core types — Task, Domain, TaskResult, TaskContext

**Files:**
- Create: `core/task.py`
- Create: `tests/test_task.py`

- [ ] **Step 1: Write failing tests for Domain**

```python
# tests/test_task.py
from core.task import Domain, Task, TaskResult, TaskContext

class TestDomain:
    def test_general_domain_is_general(self):
        d = Domain("general", "general")
        assert d.is_general is True

    def test_specific_domain_is_not_general(self):
        d = Domain("textworld/map_A", "specific")
        assert d.is_general is False

    def test_domain_parent(self):
        d = Domain("textworld/map_A", "specific")
        parent = d.parent
        assert parent is not None
        assert parent.path == "textworld"
        assert parent.level == "general"

    def test_general_domain_has_no_parent(self):
        d = Domain("general", "general")
        assert d.parent is None

    def test_domain_depth(self):
        assert Domain("general", "general").depth == 0
        assert Domain("textworld", "general").depth == 1
        assert Domain("textworld/map_A", "specific").depth == 2

    def test_is_ancestor_of(self):
        parent = Domain("textworld", "general")
        child = Domain("textworld/map_A", "specific")
        assert parent.is_ancestor_of(child) is True
        assert child.is_ancestor_of(parent) is False

    def test_is_descendant_of(self):
        parent = Domain("textworld", "general")
        child = Domain("textworld/map_A", "specific")
        assert child.is_descendant_of(parent) is True
        assert parent.is_descendant_of(child) is False

    def test_domain_equality(self):
        a = Domain("textworld", "general")
        b = Domain("textworld", "general")
        assert a == b
        assert hash(a) == hash(b)

class TestTask:
    def test_task_creation(self):
        t = Task(description="find the treasure", domain=Domain("textworld/map_A", "specific"))
        assert t.description == "find the treasure"
        assert t.domain.path == "textworld/map_A"

    def test_task_default_domain(self):
        t = Task(description="do something")
        assert t.domain.path == "general"
        assert t.domain.is_general is True
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd C:/Users/micha/PycharmProjects/cognitive-agent && python -m pytest tests/test_task.py -v
```
Expected: `ModuleNotFoundError: No module named 'core.task'`

- [ ] **Step 3: Write minimal implementation**

```python
# core/task.py
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class Domain:
    """Hierarchical domain identifier. Frozen for use as dict key."""
    path: str          # "textworld/map_A" | "programming/python" | "general"
    level: str         # "specific" | "general"

    @property
    def is_general(self) -> bool:
        return self.level == "general"

    @property
    def parent(self) -> Domain | None:
        parts = self.path.rsplit("/", 1)
        if len(parts) == 1:
            return None
        return Domain(parts[0], "general")

    @property
    def depth(self) -> int:
        if self.path == "general":
            return 0
        return self.path.count("/") + 1

    def is_ancestor_of(self, other: Domain) -> bool:
        return other.path.startswith(self.path + "/")

    def is_descendant_of(self, other: Domain) -> bool:
        return self.path.startswith(other.path + "/")


@dataclass
class Task:
    """A user request with a defined domain and evaluation criteria."""
    description: str
    domain: Domain = field(default_factory=lambda: Domain("general", "general"))
    context: str = ""
    needs_decomposition: bool = False
    subtasks: list[Task] = field(default_factory=list)


@dataclass
class TaskResult:
    """Output of a completed task execution."""
    success: bool = False
    final_response: str = ""
    new_knowledge_cards: int = 0
    l1_changes: list[str] = field(default_factory=list)
    l1_rejections: list[str] = field(default_factory=list)
    new_skills: list[str] = field(default_factory=list)
    iterations_used: int = 0
    summary: str = ""


@dataclass
class TaskContext:
    """Mutable context tracked during a single task execution."""
    task: Task
    consecutive_no_progress: int = 0
    eval_result: str = ""  # "success" | "failure" | ""
    rounds: int = 0
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd C:/Users/micha/PycharmProjects/cognitive-agent && python -m pytest tests/test_task.py -v
```
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
cd C:/Users/micha/PycharmProjects/cognitive-agent && git add core/task.py tests/test_task.py && git commit -m "feat: add core types — Domain, Task, TaskResult, TaskContext"
```

---

### Task 3: Tool registry

**Files:**
- Create: `core/tools/registry.py`
- Create: `tests/test_tool_registry.py`

- [ ] **Step 1: Write failing tests for ToolRegistry**

```python
# tests/test_tool_registry.py
import pytest
from core.tools.registry import ToolRegistry, ToolEntry


def echo_handler(args, context=None):
    return f"echo: {args.get('message', '')}"

def check_always():
    return True

def check_never():
    return False


class TestToolRegistry:
    def test_singleton(self):
        a = ToolRegistry()
        b = ToolRegistry()
        assert a is b

    def test_register_and_get(self):
        r = ToolRegistry()
        r.register("echo", {
            "type": "function",
            "function": {
                "name": "echo",
                "description": "Echo a message",
                "parameters": {"type": "object", "properties": {}}
            }
        }, echo_handler, check_fn=check_always)
        defs = r.get_definitions()
        assert len(defs) == 1
        assert defs[0]["function"]["name"] == "echo"

    def test_get_definitions_filters_by_check_fn(self):
        r = ToolRegistry()
        r.register("always", {
            "type": "function",
            "function": {"name": "always", "description": "", "parameters": {}}
        }, echo_handler, check_fn=check_always)
        r.register("never", {
            "type": "function",
            "function": {"name": "never", "description": "", "parameters": {}}
        }, echo_handler, check_fn=check_never)
        defs = r.get_definitions()
        names = [d["function"]["name"] for d in defs]
        assert "always" in names
        assert "never" not in names

    def test_dispatch(self):
        r = ToolRegistry()
        r.register("echo", {
            "type": "function",
            "function": {"name": "echo", "description": "", "parameters": {}}
        }, echo_handler, check_fn=check_always)
        result = r.dispatch("echo", {"message": "hello"})
        assert result == "echo: hello"

    def test_dispatch_unknown_tool_returns_error(self):
        r = ToolRegistry()
        result = r.dispatch("nonexistent", {})
        assert "error" in result

    def test_deregister(self):
        r = ToolRegistry()
        r.register("temp", {
            "type": "function",
            "function": {"name": "temp", "description": "", "parameters": {}}
        }, echo_handler, check_fn=check_always)
        assert len(r.get_definitions()) == 1
        r.deregister("temp")
        assert len(r.get_definitions()) == 0

    def test_duplicate_register_same_toolset_is_ok(self):
        r = ToolRegistry()
        schema = {"type": "function", "function": {"name": "dup", "description": "", "parameters": {}}}
        r.register("dup", schema, echo_handler, check_fn=check_always, toolset="core")
        r.register("dup", schema, echo_handler, check_fn=check_always, toolset="core")
        assert len(r.get_definitions()) == 1

    def test_duplicate_register_different_toolset_raises(self):
        r = ToolRegistry()
        schema = {"type": "function", "function": {"name": "dup", "description": "", "parameters": {}}}
        r.register("dup", schema, echo_handler, check_fn=check_always, toolset="A")
        with pytest.raises(ValueError, match="already registered"):
            r.register("dup", schema, echo_handler, check_fn=check_always, toolset="B")
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd C:/Users/micha/PycharmProjects/cognitive-agent && python -m pytest tests/test_tool_registry.py -v
```
Expected: `ModuleNotFoundError`

- [ ] **Step 3: Write ToolRegistry implementation**

```python
# core/tools/registry.py
from __future__ import annotations
import json
import threading
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class ToolEntry:
    name: str
    schema: dict
    handler: Callable
    check_fn: Callable | None = None
    toolset: str = "core"


class ToolRegistry:
    """Thread-safe singleton tool registry. Adapted from Hermes tools/registry.py."""
    _instance: ToolRegistry | None = None
    _lock = threading.RLock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._entries: dict[str, ToolEntry] = {}
        return cls._instance

    def register(self, name: str, schema: dict, handler: Callable,
                 check_fn: Callable | None = None, toolset: str = "core",
                 override: bool = False):
        with self._lock:
            existing = self._entries.get(name)
            if existing and existing.toolset != toolset and not override:
                raise ValueError(
                    f"Tool '{name}' already registered from toolset "
                    f"'{existing.toolset}' (attempted from '{toolset}')"
                )
            self._entries[name] = ToolEntry(
                name=name, schema=schema, handler=handler,
                check_fn=check_fn, toolset=toolset,
            )

    def get_definitions(self, requested: set[str] | None = None) -> list[dict]:
        with self._lock:
            entries = self._entries.values()
            if requested:
                entries = [e for e in entries if e.name in requested]
            return [
                e.schema for e in entries
                if e.check_fn is None or e.check_fn()
            ]

    def dispatch(self, name: str, args: dict, context: dict | None = None) -> str:
        with self._lock:
            entry = self._entries.get(name)
        if entry is None:
            return json.dumps({"error": f"Tool '{name}' not found"})
        try:
            result = entry.handler(args, context) if context else entry.handler(args)
            if isinstance(result, str):
                return result
            return json.dumps(result)
        except Exception as e:
            return json.dumps({"error": str(e)})

    def deregister(self, name: str):
        with self._lock:
            self._entries.pop(name, None)

    def clear(self):
        """Reset all entries. For testing only."""
        with self._lock:
            self._entries.clear()
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd C:/Users/micha/PycharmProjects/cognitive-agent && python -m pytest tests/test_tool_registry.py -v
```
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
cd C:/Users/micha/PycharmProjects/cognitive-agent && git add core/tools/registry.py tests/test_tool_registry.py && git commit -m "feat: add ToolRegistry — thread-safe singleton with register/dispatch/deregister"
```

---

### Task 4: L3 Skill layer — storage, CRUD, match

**Files:**
- Create: `core/skill_layer.py`
- Create: `tests/test_skill_layer.py`
- Create: `skills/general/test-skill/SKILL.md` (test fixture, created in setUp)

- [ ] **Step 1: Write failing tests for SkillLayer**

```python
# tests/test_skill_layer.py
import pytest
from pathlib import Path
from core.skill_layer import SkillLayer, SkillMeta
from core.task import Domain
from core.tools.registry import ToolRegistry


@pytest.fixture
def skill_registry():
    r = ToolRegistry()
    r.clear()  # fresh start
    return r


@pytest.fixture
def skill_layer(temp_dir, skill_registry):
    skills_dir = temp_dir / "skills"
    skills_dir.mkdir()
    (skills_dir / "general").mkdir()
    return SkillLayer(skills_dir, skill_registry)


class TestSkillLayer:
    def test_create_skill(self, skill_layer, skill_registry):
        content = """---
name: test-skill
description: "A test skill"
domain: general
cross_domain: true
version: 1.0.0
---
# Test Skill

## Procedure
1. Do something
"""
        meta = skill_layer.create_skill("test-skill", content, Domain("general", "general"))
        assert meta.name == "test-skill"
        assert meta.domain.path == "general"
        assert meta.cross_domain is True

        skill_file = skill_layer.skills_dir / "general" / "test-skill" / "SKILL.md"
        assert skill_file.exists()

    def test_list_all(self, skill_layer):
        content = """---
name: skill-a
description: "Skill A"
domain: general
cross_domain: false
version: 1.0.0
---
# A
"""
        skill_layer.create_skill("skill-a", content, Domain("general", "general"))
        skills = skill_layer.list_all()
        assert len(skills) == 1
        assert skills[0].name == "skill-a"

    def test_match_by_domain(self, skill_layer):
        # Create general skill
        content_g = """---
name: gen-skill
description: "General"
domain: general
cross_domain: true
version: 1.0.0
---
# G
"""
        skill_layer.create_skill("gen-skill", content_g, Domain("general", "general"))

        # Match from specific domain
        matches = skill_layer.match(Domain("textworld/map_A", "specific"))
        assert len(matches) >= 1
        assert any(s.name == "gen-skill" for s in matches)

    def test_match_exact_domain_preferred(self, skill_layer):
        content_tw = """---
name: tw-skill
description: "TextWorld"
domain: textworld
cross_domain: false
version: 1.0.0
---
# TW
"""
        content_gen = """---
name: gen-skill
description: "General"
domain: general
cross_domain: true
version: 1.0.0
---
# G
"""
        skill_layer.create_skill("tw-skill", content_tw, Domain("textworld", "general"))
        skill_layer.create_skill("gen-skill", content_gen, Domain("general", "general"))

        matches = skill_layer.match(Domain("textworld", "general"))
        # exact domain match should come first
        assert matches[0].name == "tw-skill"

    def test_delete_skill_archives_not_deletes(self, skill_layer):
        content = """---
name: temp-skill
description: "Temp"
domain: general
cross_domain: false
version: 1.0.0
---
# T
"""
        skill_layer.create_skill("temp-skill", content, Domain("general", "general"))
        skill_layer.delete_skill("temp-skill")

        # Should not be in list
        assert len(skill_layer.list_all()) == 0

        # Should be in archive
        archive = skill_layer.skills_dir / ".archive" / "temp-skill"
        assert archive.exists()

    def test_tools_registered(self, skill_layer, skill_registry):
        defs = skill_registry.get_definitions()
        names = [d["function"]["name"] for d in defs]
        assert "skills_list" in names
        assert "skill_view" in names
        assert "skill_manage" in names
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd C:/Users/micha/PycharmProjects/cognitive-agent && python -m pytest tests/test_skill_layer.py -v
```
Expected: FAIL (ModuleNotFoundError)

- [ ] **Step 3: Write SkillLayer implementation**

```python
# core/skill_layer.py
from __future__ import annotations
import json
import logging
import re
import tempfile
from datetime import datetime
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

# ── Constants ──
L3_CREATION_THRESHOLD_CARDS = 3
L3_CREATION_THRESHOLD_ACTIVATION = 0.7


@dataclass
class SkillMeta:
    name: str
    description: str
    domain: "Domain"
    cross_domain: bool = False
    version: str = "1.0.0"
    created_by: str = "agent"
    source_cards: list[str] = field(default_factory=list)
    skill_dir: Path | None = None


class SkillLayer:
    """L3: Semi-static skills. SKILL.md format (compatible with agentskills.io)."""

    def __init__(self, skills_dir: Path, tool_registry):
        from core.task import Domain
        self.skills_dir = Path(skills_dir)
        self.skills_dir.mkdir(parents=True, exist_ok=True)
        self._register_tools(tool_registry)

    # ── Query ──

    def list_all(self) -> list[SkillMeta]:
        metas = []
        for skill_dir in self.skills_dir.rglob("SKILL.md"):
            if ".archive" in skill_dir.parts:
                continue
            try:
                meta = self._parse_skill_meta(skill_dir)
                if meta:
                    metas.append(meta)
            except Exception:
                logger.debug("Failed to parse %s", skill_dir, exc_info=True)
        return metas

    def match(self, task_domain) -> list[SkillMeta]:
        """Match skills to task domain. Exact > parent > general cross-domain."""
        from core.task import Domain
        all_skills = self.list_all()
        scored = []
        for s in all_skills:
            if s.domain.path == task_domain.path:
                scored.append((3, s))
            elif task_domain.parent and s.domain.path == task_domain.parent.path:
                scored.append((2, s))
            elif s.cross_domain and s.domain.is_general:
                scored.append((1, s))
            elif s.domain.path == task_domain.path.split("/")[0]:
                scored.append((1, s))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [s for _, s in scored]

    # ── CRUD ──

    def create_skill(self, name: str, content: str, domain,
                     cross_domain: bool = False, created_by: str = "agent") -> SkillMeta:
        from core.task import Domain

        if not re.match(r'^[a-z0-9][a-z0-9._-]*$', name):
            raise ValueError(f"Invalid skill name: {name}")
        if len(name) > 64:
            raise ValueError(f"Skill name too long: {len(name)} > 64")

        # Determine directory
        if domain.is_general:
            skill_dir = self.skills_dir / "general" / name
        else:
            skill_dir = self.skills_dir / domain.path / name
        skill_dir.mkdir(parents=True, exist_ok=True)

        # Atomic write
        skill_file = skill_dir / "SKILL.md"
        fd, tmp_path = tempfile.mkstemp(dir=skill_dir, suffix=".md")
        try:
            with open(fd, "w", encoding="utf-8") as f:
                f.write(content)
            Path(tmp_path).replace(skill_file)
        finally:
            Path(tmp_path).unlink(missing_ok=True)

        return SkillMeta(
            name=name,
            description=self._extract_description(content),
            domain=domain,
            cross_domain=cross_domain,
            created_by=created_by,
            skill_dir=skill_dir,
        )

    def edit_skill(self, name: str, new_content: str) -> SkillMeta:
        skill_dir = self._find_skill_dir(name)
        if not skill_dir:
            raise ValueError(f"Skill not found: {name}")
        skill_file = skill_dir / "SKILL.md"
        fd, tmp_path = tempfile.mkstemp(dir=skill_dir, suffix=".md")
        try:
            with open(fd, "w", encoding="utf-8") as f:
                f.write(new_content)
            Path(tmp_path).replace(skill_file)
        finally:
            Path(tmp_path).unlink(missing_ok=True)
        return self._parse_skill_meta(skill_file)

    def patch_skill(self, name: str, find: str, replace: str) -> SkillMeta:
        skill_dir = self._find_skill_dir(name)
        if not skill_dir:
            raise ValueError(f"Skill not found: {name}")
        skill_file = skill_dir / "SKILL.md"
        content = skill_file.read_text(encoding="utf-8")
        if find not in content:
            raise ValueError(f"Find text not found in {name}")
        new_content = content.replace(find, replace, 1)
        return self.edit_skill(name, new_content)

    def delete_skill(self, name: str) -> None:
        skill_dir = self._find_skill_dir(name)
        if not skill_dir:
            raise ValueError(f"Skill not found: {name}")
        archive_dir = self.skills_dir / ".archive"
        archive_dir.mkdir(exist_ok=True)
        skill_dir.rename(archive_dir / name)

    # ── L2 → L3 compilation ──

    def should_create_skill(self, domain, domain_cards: list) -> bool:
        cards = [c for c in domain_cards if c.domain.path == domain.path]
        if len(cards) < L3_CREATION_THRESHOLD_CARDS:
            return False
        avg = sum(c.activation for c in cards) / len(cards)
        return avg > L3_CREATION_THRESHOLD_ACTIVATION

    def propose_and_create(self, domain, cards: list, llm_client=None) -> SkillMeta | None:
        """Compile L2 cards into SKILL.md via LLM, then create."""
        if llm_client is None:
            return None
        cards_text = "\n\n".join(
            f"- [{c.id}] (confidence:{c.confidence:.1f}, activation:{c.activation:.2f}) {c.content}"
            for c in cards if c.domain.path == domain.path
        )
        prompt = (
            f"Create a SKILL.md for domain '{domain.path}' from these knowledge cards:\n\n"
            f"{cards_text}\n\n"
            f"Generate YAML frontmatter + markdown body. Include name, description, "
            f"domain, and a numbered procedure. Format exactly:\n"
            f"---\nname: skill-name\ndescription: \"...\"\ndomain: {domain.path}\n"
            f"cross_domain: false\nversion: 1.0.0\n---\n# Title\n\n## Procedure\n1. ..."
        )
        response = self._call_llm(llm_client, prompt)
        try:
            meta = self.create_skill(
                f"{domain.path.replace('/', '-')}-compiled",
                response, domain, created_by="l2_compilation",
            )
            meta.source_cards = [c.id for c in cards if c.domain.path == domain.path]
            return meta
        except Exception:
            return None

    # ── Helpers ──

    def _parse_skill_meta(self, skill_file: Path) -> SkillMeta | None:
        from core.task import Domain
        content = skill_file.read_text(encoding="utf-8")
        if not content.startswith("---"):
            return None
        parts = content.split("---", 2)
        if len(parts) < 3:
            return None
        try:
            fm = yaml.safe_load(parts[1])
        except yaml.YAMLError:
            return None
        domain_path = fm.get("domain", "general")
        domain_level = "general" if domain_path == "general" else "specific"
        return SkillMeta(
            name=fm.get("name", skill_file.parent.name),
            description=fm.get("description", ""),
            domain=Domain(domain_path, domain_level),
            cross_domain=fm.get("cross_domain", False),
            version=str(fm.get("version", "1.0.0")),
            created_by=str(fm.get("created_by", "agent")),
            source_cards=fm.get("source_cards", []),
            skill_dir=skill_file.parent,
        )

    def _extract_description(self, content: str) -> str:
        if not content.startswith("---"):
            return ""
        parts = content.split("---", 2)
        if len(parts) < 3:
            return ""
        try:
            fm = yaml.safe_load(parts[1])
            return fm.get("description", "")
        except yaml.YAMLError:
            return ""

    def _find_skill_dir(self, name: str) -> Path | None:
        for skill_file in self.skills_dir.rglob("SKILL.md"):
            if ".archive" in skill_file.parts:
                continue
            if skill_file.parent.name == name:
                return skill_file.parent
        return None

    def _call_llm(self, client, prompt: str) -> str:
        resp = client.chat(
            messages=[{"role": "user", "content": prompt}],
            tools=None,
        )
        return resp.text if hasattr(resp, 'text') else str(resp)

    def _register_tools(self, registry):
        """Register skill tools on the given registry."""
        layer = self  # capture for closure

        def _skills_list(args=None, context=None):
            category = (args or {}).get("category", "")
            skills = layer.list_all()
            if category:
                skills = [s for s in skills if category in s.domain.path]
            return json.dumps([
                {"name": s.name, "description": s.description, "domain": s.domain.path}
                for s in skills
            ], ensure_ascii=False)

        def _skill_view(args=None, context=None):
            name = (args or {}).get("name", "")
            skill_dir = layer._find_skill_dir(name)
            if not skill_dir:
                return json.dumps({"error": f"Skill '{name}' not found"})
            skill_file = skill_dir / "SKILL.md"
            content = skill_file.read_text(encoding="utf-8")
            return json.dumps({"success": True, "name": name, "content": content}, ensure_ascii=False)

        def _skill_manage(args=None, context=None):
            action = (args or {}).get("action", "")
            skill_name = (args or {}).get("name", "")
            content = (args or {}).get("content", "")
            domain_path = (args or {}).get("domain", "general")
            find_text = (args or {}).get("find", "")
            replace_text = (args or {}).get("replace", "")
            from core.task import Domain
            domain = Domain(domain_path, "general" if domain_path == "general" else "specific")

            try:
                if action == "create":
                    meta = layer.create_skill(skill_name, content, domain)
                    return json.dumps({"success": True, "name": meta.name})
                elif action == "edit":
                    meta = layer.edit_skill(skill_name, content)
                    return json.dumps({"success": True, "name": meta.name})
                elif action == "patch":
                    meta = layer.patch_skill(skill_name, find_text, replace_text)
                    return json.dumps({"success": True, "name": meta.name})
                elif action == "delete":
                    layer.delete_skill(skill_name)
                    return json.dumps({"success": True})
                else:
                    return json.dumps({"error": f"Unknown action: {action}"})
            except Exception as e:
                return json.dumps({"error": str(e)})

        registry.register("skills_list", {
            "type": "function",
            "function": {
                "name": "skills_list",
                "description": "List available skills with metadata",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "category": {"type": "string", "description": "Filter by domain/category"}
                    }
                }
            }
        }, _skills_list, toolset="core")

        registry.register("skill_view", {
            "type": "function",
            "function": {
                "name": "skill_view",
                "description": "Load full skill content by name",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "Skill name"}
                    },
                    "required": ["name"]
                }
            }
        }, _skill_view, toolset="core")

        registry.register("skill_manage", {
            "type": "function",
            "function": {
                "name": "skill_manage",
                "description": "Create, edit, patch, or delete a skill",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "enum": ["create", "edit", "patch", "delete"]},
                        "name": {"type": "string"},
                        "content": {"type": "string"},
                        "domain": {"type": "string"},
                        "find": {"type": "string"},
                        "replace": {"type": "string"},
                    },
                    "required": ["action", "name"]
                }
            }
        }, _skill_manage, toolset="core")
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd C:/Users/micha/PycharmProjects/cognitive-agent && python -m pytest tests/test_skill_layer.py -v
```
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
cd C:/Users/micha/PycharmProjects/cognitive-agent && git add core/skill_layer.py tests/test_skill_layer.py && git commit -m "feat: add L3 SkillLayer — CRUD, match, L2→L3 compilation, tool registration"
```

---

### Task 5: L2 Flexible knowledge — KnowledgeCard + activation + MD/JSON/Graph

**Files:**
- Create: `core/flexible_knowledge.py`
- Create: `tests/test_flexible_knowledge.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_flexible_knowledge.py
import pytest
import json
from pathlib import Path
from datetime import datetime, timedelta
from core.flexible_knowledge import (
    KnowledgeCard, FlexibleKnowledge, KnowledgeGraph,
    RELATION_TYPES,
)
from core.task import Domain


@pytest.fixture
def textworld_domain():
    return Domain("textworld/map_A", "specific")


@pytest.fixture
def general_domain():
    return Domain("general", "general")


@pytest.fixture
def l2_store(temp_dir):
    knowledge_dir = temp_dir / "knowledge"
    knowledge_dir.mkdir()
    (knowledge_dir / "general").mkdir()
    index_path = knowledge_dir / "l2_index.json"
    index_path.write_text(json.dumps({
        "version": 1, "updated_at": "", "chapters": [], "relations": []
    }))
    return FlexibleKnowledge(knowledge_dir, index_path)


class TestKnowledgeCard:
    def test_create_card(self, textworld_domain):
        card = KnowledgeCard(
            id="card_001",
            content="map_A的钥匙在厨房抽屉里",
            domain=textworld_domain,
            sub_tags=["navigation", "key_location"],
            confidence=0.9,
            source="observation",
        )
        assert card.confidence == 0.9
        assert card.activation == 0.9  # initial activation = confidence
        assert card.success_count == 0

    def test_boost_increases_confidence(self, textworld_domain):
        card = KnowledgeCard(
            id="card_001", content="test", domain=textworld_domain,
            confidence=0.5, source="observation",
        )
        card.boost()
        assert card.confidence > 0.5
        assert card.success_count == 1

    def test_penalize_decreases_confidence(self, textworld_domain):
        card = KnowledgeCard(
            id="card_001", content="test", domain=textworld_domain,
            confidence=0.5, source="observation",
        )
        card.penalize()
        assert card.confidence < 0.5
        assert card.failure_count == 1

    def test_confidence_cannot_exceed_one(self, textworld_domain):
        card = KnowledgeCard(
            id="card_001", content="test", domain=textworld_domain,
            confidence=0.99, source="observation",
        )
        card.boost()
        assert card.confidence <= 1.0

    def test_confidence_floor(self, textworld_domain):
        card = KnowledgeCard(
            id="card_001", content="test", domain=textworld_domain,
            confidence=0.05, source="observation",
        )
        card.penalize()
        assert card.confidence >= 0.1

    def test_domain_match_exact(self, textworld_domain):
        card = KnowledgeCard(
            id="card_001", content="test", domain=textworld_domain,
            confidence=1.0, source="observation",
        )
        score = card._domain_match_score(textworld_domain)
        assert score == 1.0

    def test_domain_match_general(self, general_domain, textworld_domain):
        card = KnowledgeCard(
            id="card_001", content="test", domain=general_domain,
            confidence=1.0, source="observation",
        )
        score = card._domain_match_score(textworld_domain)
        assert score == 0.4

    def test_domain_match_parent(self):
        parent = Domain("textworld", "general")
        child = Domain("textworld/map_A", "specific")
        card = KnowledgeCard(
            id="card_001", content="test", domain=parent,
            confidence=1.0, source="observation",
        )
        score = card._domain_match_score(child)
        assert score == 0.7

    def test_domain_match_unrelated(self):
        card = KnowledgeCard(
            id="card_001", content="test",
            domain=Domain("programming/python", "specific"),
            confidence=1.0, source="observation",
        )
        score = card._domain_match_score(Domain("textworld/map_A", "specific"))
        assert score == 0.0


class TestFlexibleKnowledge:
    def test_add_card(self, l2_store, textworld_domain):
        card = l2_store.add_card(
            content="map_A的钥匙在厨房抽屉里",
            domain=textworld_domain,
            sub_tags=["key_location"],
            confidence=0.9,
            source="observation",
        )
        assert card.id is not None
        assert len(l2_store.cards) == 1

    def test_get_active_cards(self, l2_store, textworld_domain):
        l2_store.add_card("钥匙在厨房", textworld_domain, confidence=0.9, source="observation")
        l2_store.add_card("宝藏在阁楼", textworld_domain, confidence=0.8, source="observation")
        l2_store.add_card("无关卡片", Domain("programming/python", "specific"),
                         confidence=0.9, source="observation")
        active = l2_store.get_active_cards(textworld_domain, "", top_k=5)
        assert len(active) <= 3  # 2 matching + possibly general
        assert all(c.domain.path.startswith("textworld") or c.domain.is_general for c in active)

    def test_write_md_and_rebuild_index(self, l2_store, textworld_domain):
        md_path = l2_store._write_md(
            textworld_domain, "map-navigation.md",
            "# 地图导航\n\n"
            "## 上锁的门需要钥匙\n钥匙通常在同一地图内。\n\n"
            "## 先探索未知房间\n新地图优先遍历未访问房间。\n"
        )
        assert md_path.exists()
        # Rebuild index
        l2_store._rebuild_index()
        index = json.loads(l2_store.index_path.read_text())
        chapters = [c for c in index["chapters"] if c["id"].startswith("textworld")]
        assert len(chapters) > 0

    def test_domain_stats(self, l2_store, textworld_domain):
        l2_store.add_card("card A", textworld_domain, confidence=0.9, source="observation")
        l2_store.add_card("card B", textworld_domain, confidence=0.7, source="observation")
        stats = l2_store.domain_stats(textworld_domain)
        assert stats["count"] >= 2
        assert 0 < stats["avg_activation"] <= 1.0


class TestKnowledgeGraph:
    def test_build_from_index(self):
        index = {
            "chapters": [],
            "relations": [
                {"from": "textworld/map-navigation", "to": "textworld/item-search", "type": "cross_reference"},
                {"from": "textworld/map-navigation", "to": "general/task-strategy", "type": "parent_child"},
            ]
        }
        graph = KnowledgeGraph(index)
        adj = graph.get_adjacent("textworld/map-navigation")
        assert len(adj) == 2
        assert ("textworld/item-search", "cross_reference") in adj

    def test_spread_activation(self):
        index = {
            "chapters": [],
            "relations": [
                {"from": "A", "to": "B", "type": "cross_reference"},
                {"from": "B", "to": "C", "type": "prerequisite"},
            ]
        }
        graph = KnowledgeGraph(index)
        scores = graph.spread_activation(["A"], steps=2)
        assert "A" in scores
        assert scores.get("B", 0) > 0
        assert scores.get("C", 0) > 0

    def test_empty_index(self):
        graph = KnowledgeGraph({"chapters": [], "relations": []})
        assert graph.get_adjacent("nonexistent") == []
        assert graph.spread_activation(["A"]) == {"A": 1.0}
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd C:/Users/micha/PycharmProjects/cognitive-agent && python -m pytest tests/test_flexible_knowledge.py -v
```
Expected: FAIL (ModuleNotFoundError)

- [ ] **Step 3: Write FlexibleKnowledge implementation**

```python
# core/flexible_knowledge.py
from __future__ import annotations
import json
import logging
import re
import tempfile
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ── Relation types ──
RELATION_TYPES = ("parent_child", "cross_reference", "prerequisite", "analogous")


def _now():
    return datetime.now(timezone.utc)


def _days_since(dt: datetime) -> float:
    if dt is None:
        return 0
    return (_now() - dt).total_seconds() / 86400.0


# ── Knowledge Card ──

@dataclass
class KnowledgeCard:
    id: str
    content: str
    domain: "Domain"
    sub_tags: list[str] = field(default_factory=list)
    confidence: float = 0.5
    activation: float = 0.5
    last_used: datetime = field(default_factory=_now)
    decay_rate: float = 0.01
    source: str = "observation"
    success_count: int = 0
    failure_count: int = 0
    created_at: datetime = field(default_factory=_now)
    updated_at: datetime = field(default_factory=_now)
    marker: str = ""  # "compiled_to_skill" | "dormant" | ""

    def __post_init__(self):
        if self.activation == 0.5 and self.confidence != 0.5:
            self.activation = self.confidence

    def compute_activation(self, task_domain, task_context: str = "") -> float:
        domain_score = self._domain_match_score(task_domain)
        if domain_score == 0.0:
            return 0.0
        recency_score = max(0, 1.0 - _days_since(self.last_used) * 0.1)
        return min(1.0, self.confidence * (domain_score * 0.6 + recency_score * 0.4))

    def _domain_match_score(self, task_domain) -> float:
        from core.task import Domain
        if self.domain.path == task_domain.path:
            return 1.0
        if self.domain.is_general:
            return 0.4
        if task_domain.parent and self.domain.path == task_domain.parent.path:
            return 0.7
        if self.domain.parent and self.domain.parent.path == task_domain.path:
            return 0.5
        return 0.0

    def boost(self):
        self.confidence = min(1.0, self.confidence + 0.05)
        self.success_count += 1
        self.activation = min(1.0, self.activation + 0.1)
        self.last_used = _now()
        self.updated_at = _now()

    def penalize(self):
        self.confidence = max(0.1, self.confidence - 0.1)
        self.failure_count += 1
        self.updated_at = _now()

    def apply_decay(self):
        days = _days_since(self.last_used)
        self.activation *= (1 - self.decay_rate) ** days
        self.updated_at = _now()


# ── Knowledge Graph (runtime) ──

class KnowledgeGraph:
    """Runtime graph built from l2_index.json relations."""

    def __init__(self, index: dict):
        self.adjacency: dict[str, list[tuple[str, str]]] = {}
        self._relation_weights = {
            "parent_child": 0.8,
            "cross_reference": 0.6,
            "prerequisite": 0.5,
            "analogous": 0.7,
        }
        for rel in index.get("relations", []):
            src = rel["from"]
            tgt = rel["to"]
            rtype = rel.get("type", "cross_reference")
            self.adjacency.setdefault(src, []).append((tgt, rtype))

    def get_adjacent(self, chapter_id: str) -> list[tuple[str, str]]:
        return self.adjacency.get(chapter_id, [])

    def spread_activation(self, seed_ids: list[str], steps: int = 2) -> dict[str, float]:
        scores = {sid: 1.0 for sid in seed_ids}
        current = set(seed_ids)
        decay = 0.5
        for _ in range(steps):
            next_wave = set()
            for node in current:
                for neighbor, rtype in self.get_adjacent(node):
                    if neighbor not in scores:
                        weight = self._relation_weights.get(rtype, 0.5)
                        scores[neighbor] = scores[node] * weight * decay
                        next_wave.add(neighbor)
            current = next_wave
        return scores


# ── Flexible Knowledge Layer ──

class FlexibleKnowledge:
    """L2: Flexible knowledge. Stores cards in memory, persists via MD+JSON+Graph."""

    def __init__(self, knowledge_dir: Path, index_path: Path):
        from core.task import Domain
        self.knowledge_dir = Path(knowledge_dir)
        self.index_path = Path(index_path)
        self.knowledge_dir.mkdir(parents=True, exist_ok=True)
        self.cards: list[KnowledgeCard] = []
        self.graph: KnowledgeGraph | None = None
        self._load_index()

    # ── Query ──

    def get_active_cards(self, task_domain, task_context: str = "",
                         top_k: int = 5) -> list[KnowledgeCard]:
        scored = []
        for card in self.cards:
            act = card.compute_activation(task_domain, task_context)
            if act > 0:
                scored.append((act, card))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [c for _, c in scored[:top_k]]

    def get_domain_cards(self, domain) -> list[KnowledgeCard]:
        result = []
        for card in self.cards:
            if card.domain.path == domain.path or card.domain.path.startswith(domain.path + "/"):
                result.append(card)
        return result

    # ── Write ──

    def add_card(self, content: str, domain, sub_tags: list[str] | None = None,
                 confidence: float = 0.5, source: str = "observation") -> KnowledgeCard:
        from core.task import Domain
        card = KnowledgeCard(
            id=f"card_{uuid.uuid4().hex[:8]}",
            content=content,
            domain=domain,
            sub_tags=sub_tags or [],
            confidence=confidence,
            activation=confidence,
            source=source,
        )
        self.cards.append(card)
        return card

    def update_from_tool_results(self, task, results: list):
        """Update card activation based on tool execution results."""
        for name, result_str in results:
            success = "error" not in str(result_str).lower()
            for card in self.get_active_cards(task.domain, "", top_k=5):
                if success:
                    card.boost()
                else:
                    card.penalize()

    def apply_updates(self, updates: list, domain):
        for update in updates:
            self.add_card(
                content=update.get("content", ""),
                domain=domain,
                confidence=update.get("confidence", 0.5),
                source=update.get("source", "reflection"),
            )

    def add_failed_proposal_record(self, proposal):
        self.add_card(
            content=f"L1 proposal rejected: {proposal.content[:80]}...",
            domain=proposal.domain if hasattr(proposal, 'domain') else "general",
            confidence=0.3,
            source="reflection_rejected",
        )

    # ── Decay ──

    def run_decay_cycle(self):
        for card in self.cards:
            card.apply_decay()

    # ── Stats ──

    def domain_stats(self, domain) -> dict:
        from core.task import Domain
        cards = [c for c in self.cards
                 if c.domain.path == domain.path
                 or c.domain.path.startswith(domain.path + "/")]
        if not cards:
            return {"count": 0, "avg_activation": 0.0, "avg_confidence": 0.0}
        return {
            "count": len(cards),
            "avg_activation": sum(c.activation for c in cards) / len(cards),
            "avg_confidence": sum(c.confidence for c in cards) / len(cards),
        }

    # ── MD + JSON storage ──

    def _write_md(self, domain, filename: str, content: str) -> Path:
        domain_dir = self.knowledge_dir / domain.path
        domain_dir.mkdir(parents=True, exist_ok=True)
        md_path = domain_dir / filename
        fd, tmp = tempfile.mkstemp(dir=domain_dir, suffix=".md")
        try:
            with open(fd, "w", encoding="utf-8") as f:
                f.write(content)
            Path(tmp).replace(md_path)
        finally:
            Path(tmp).unlink(missing_ok=True)
        return md_path

    def _rebuild_index(self):
        """Scan all MD files, parse ## headings, update l2_index.json."""
        chapters = []
        existing_ids = set()
        for md_file in sorted(self.knowledge_dir.rglob("*.md")):
            rel = md_file.relative_to(self.knowledge_dir)
            domain_path = str(rel.parent) if str(rel.parent) != "." else "general"
            chapter_id = str(rel.with_suffix("")).replace("\\", "/")
            content = md_file.read_text(encoding="utf-8")
            title = ""
            sections = []
            for line in content.split("\n"):
                if line.startswith("# ") and not line.startswith("## "):
                    title = line.lstrip("# ").strip()
                elif line.startswith("## "):
                    heading = line.lstrip("# ").strip()
                    sections.append({
                        "heading": heading,
                        "summary": heading,  # placeholder, LLM fills on next pass
                        "keywords": [],
                    })
            if title:
                chapters.append({
                    "id": chapter_id,
                    "title": title,
                    "domain": domain_path,
                    "source_file": str(md_file),
                    "sections": sections,
                })
                existing_ids.add(chapter_id)

        # Load existing index to preserve manually-added relations
        old_index = {}
        if self.index_path.exists():
            try:
                old_index = json.loads(self.index_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                pass

        old_relations = old_index.get("relations", [])
        new_relations = [r for r in old_relations
                         if r.get("from") in existing_ids and r.get("to") in existing_ids]

        new_index = {
            "version": old_index.get("version", 1) + 1,
            "updated_at": _now().isoformat(),
            "chapters": chapters,
            "relations": new_relations,
        }
        fd, tmp = tempfile.mkstemp(dir=self.index_path.parent, suffix=".json")
        try:
            with open(fd, "w", encoding="utf-8") as f:
                json.dump(new_index, f, ensure_ascii=False, indent=2)
            Path(tmp).replace(self.index_path)
        finally:
            Path(tmp).unlink(missing_ok=True)

    def _load_index(self):
        if self.index_path.exists():
            try:
                index = json.loads(self.index_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                index = {"version": 1, "chapters": [], "relations": []}
        else:
            index = {"version": 1, "chapters": [], "relations": []}
        self.graph = KnowledgeGraph(index)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd C:/Users/micha/PycharmProjects/cognitive-agent && python -m pytest tests/test_flexible_knowledge.py -v
```
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
cd C:/Users/micha/PycharmProjects/cognitive-agent && git add core/flexible_knowledge.py tests/test_flexible_knowledge.py && git commit -m "feat: add L2 FlexibleKnowledge — KnowledgeCard, activation/decay, MD+JSON+Graph storage"
```

---

### Task 6: L1 Philosophy — rules CRUD + active filter

**Files:**
- Create: `core/philosophy.py`
- Create: `tests/test_philosophy.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_philosophy.py
import pytest
import json
from pathlib import Path
from core.philosophy import Philosophy, Rule, L1Proposal
from core.task import Task, Domain


@pytest.fixture
def rules_path(temp_dir):
    p = temp_dir / "l1_rules.json"
    p.write_text(json.dumps({"version": 1, "rules": []}))
    return p


@pytest.fixture
def philosophy(rules_path):
    return Philosophy(rules_path, max_rules=20, max_rule_length=100)


class TestPhilosophy:
    def test_add_rule(self, philosophy):
        rule = philosophy.add_rule("test rule content", created_by="test")
        assert rule.id is not None
        assert rule.content == "test rule content"
        assert rule.created_by == "test"

    def test_all_rules(self, philosophy):
        philosophy.add_rule("rule 1", created_by="test")
        philosophy.add_rule("rule 2", created_by="test")
        assert len(philosophy.all_rules()) == 2

    def test_get_active_rules_returns_all(self, philosophy):
        philosophy.add_rule("rule A", created_by="test")
        philosophy.add_rule("rule B", created_by="test")
        task = Task(description="test", domain=Domain("general", "general"))
        active = philosophy.get_active_rules(task)
        assert len(active) == 2

    def test_modify_rule(self, philosophy):
        rule = philosophy.add_rule("original content", created_by="test")
        modified = philosophy.modify_rule(rule.id, "modified content")
        assert modified.version == 2
        assert modified.content == "modified content"

    def test_remove_rule(self, philosophy):
        rule = philosophy.add_rule("to be removed", created_by="test")
        philosophy.remove_rule(rule.id)
        assert len(philosophy.all_rules()) == 0

    def test_apply_proposal(self, philosophy):
        proposal = L1Proposal(content="new rule from reflection", reason="test")
        philosophy.apply(proposal)
        rules = philosophy.all_rules()
        assert any(r.content == "new rule from reflection" for r in rules)

    def test_persists_to_disk(self, rules_path):
        p = Philosophy(rules_path, max_rules=20, max_rule_length=100)
        p.add_rule("persistent rule", created_by="test")
        # Reload
        p2 = Philosophy(rules_path, max_rules=20, max_rule_length=100)
        assert len(p2.all_rules()) == 1
        assert p2.all_rules()[0].content == "persistent rule"

    def test_max_rule_length_enforced(self, philosophy):
        with pytest.raises(ValueError):
            philosophy.add_rule("x" * 101, created_by="test")
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd C:/Users/micha/PycharmProjects/cognitive-agent && python -m pytest tests/test_philosophy.py -v
```
Expected: FAIL (ModuleNotFoundError)

- [ ] **Step 3: Write Philosophy implementation**

```python
# core/philosophy.py
from __future__ import annotations
import json
import logging
import tempfile
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)


def _now():
    return datetime.now(timezone.utc).isoformat()


@dataclass
class Rule:
    id: str
    content: str
    created_by: str
    added_at: str = field(default_factory=_now)
    version: int = 1
    last_modified: str = field(default_factory=_now)


@dataclass
class L1Proposal:
    content: str
    reason: str = ""
    rule_id: str | None = None  # set if modifying existing rule
    domain: str = "general"


class Philosophy:
    """L1: Behavioral philosophy. Rules stored in JSON, injected into system prompt."""

    def __init__(self, rules_path: Path, max_rules: int = 20, max_rule_length: int = 100):
        self.rules_path = Path(rules_path)
        self.max_rules = max_rules
        self.max_rule_length = max_rule_length
        self._rules: list[Rule] = []
        self._load()

    # ── Query ──

    def all_rules(self) -> list[Rule]:
        return list(self._rules)

    def get_active_rules(self, task) -> list[str]:
        """Phase 1: return all rule contents (small set, no filtering needed)."""
        return [r.content for r in self._rules]

    # ── Mutate ──

    def add_rule(self, content: str, created_by: str = "reflection") -> Rule:
        if len(content) > self.max_rule_length:
            raise ValueError(
                f"Rule too long: {len(content)} > {self.max_rule_length}"
            )
        rule = Rule(
            id=f"l1_{uuid.uuid4().hex[:6]}",
            content=content,
            created_by=created_by,
        )
        self._rules.append(rule)
        self._save()
        return rule

    def modify_rule(self, rule_id: str, new_content: str) -> Rule:
        for i, r in enumerate(self._rules):
            if r.id == rule_id:
                if len(new_content) > self.max_rule_length:
                    raise ValueError(
                        f"Rule too long: {len(new_content)} > {self.max_rule_length}"
                    )
                    updated = Rule(
                        id=r.id,
                        content=new_content,
                        created_by=r.created_by,
                        added_at=r.added_at,
                        version=r.version + 1,
                        last_modified=_now(),
                    )
                    self._rules[i] = updated
                    self._save()
                    return updated
        raise ValueError(f"Rule not found: {rule_id}")

    def remove_rule(self, rule_id: str) -> None:
        self._rules = [r for r in self._rules if r.id != rule_id]
        self._save()

    def apply(self, proposal: L1Proposal) -> Rule:
        if proposal.rule_id:
            return self.modify_rule(proposal.rule_id, proposal.content)
        return self.add_rule(proposal.content, created_by="reflection")

    # ── Persistence ──

    def _load(self):
        if self.rules_path.exists():
            try:
                data = json.loads(self.rules_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                data = {"version": 1, "rules": []}
        else:
            data = {"version": 1, "rules": []}
        self._rules = [
            Rule(
                id=r["id"],
                content=r["content"],
                created_by=r.get("created_by", "unknown"),
                added_at=r.get("added_at", _now()),
                version=r.get("version", 1),
                last_modified=r.get("last_modified", _now()),
            )
            for r in data.get("rules", [])
        ]

    def _save(self):
        self.rules_path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "version": 1,
            "rules": [
                {
                    "id": r.id,
                    "content": r.content,
                    "created_by": r.created_by,
                    "added_at": r.added_at,
                    "version": r.version,
                    "last_modified": r.last_modified,
                }
                for r in self._rules
            ],
        }
        fd, tmp = tempfile.mkstemp(dir=self.rules_path.parent, suffix=".json")
        try:
            with open(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            Path(tmp).replace(self.rules_path)
        finally:
            Path(tmp).unlink(missing_ok=True)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd C:/Users/micha/PycharmProjects/cognitive-agent && python -m pytest tests/test_philosophy.py -v
```
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
cd C:/Users/micha/PycharmProjects/cognitive-agent && git add core/philosophy.py tests/test_philosophy.py && git commit -m "feat: add L1 Philosophy — rules CRUD, JSON persistence, active filter"
```

---

### Task 7: L0.5 Meta driver — triggers, validators, reflection

**Files:**
- Create: `core/meta_driver.py`
- Create: `tests/test_meta_driver.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_meta_driver.py
import pytest
from unittest.mock import MagicMock
from core.meta_driver import (
    MetaDriver, ReflectionTrigger, TriggerType, ValidationRule,
    DEFAULT_TRIGGERS, DEFAULT_VALIDATORS,
)
from core.task import Task, TaskContext, Domain
from core.philosophy import L1Proposal


@pytest.fixture
def mock_llm():
    llm = MagicMock()
    llm.chat.return_value.text = '{"approved": true, "reason": "looks good"}'
    return llm


@pytest.fixture
def meta(mock_llm):
    return MetaDriver(
        triggers=DEFAULT_TRIGGERS,
        validation_rules=DEFAULT_VALIDATORS,
        auxiliary_llm=mock_llm,
    )


class TestReflectionTrigger:
    def test_rule_trigger_fires(self):
        trigger = ReflectionTrigger(
            id="test", trigger_type=TriggerType.RULE,
            condition_desc="test",
            rule_check=lambda ctx: ctx.consecutive_no_progress >= 3,
            llm_prompt=None, cooldown_rounds=1,
        )
        ctx = TaskContext(task=Task("test"))
        ctx.consecutive_no_progress = 3
        assert trigger.evaluate(ctx) is True

    def test_rule_trigger_does_not_fire(self):
        trigger = ReflectionTrigger(
            id="test", trigger_type=TriggerType.RULE,
            condition_desc="test",
            rule_check=lambda ctx: ctx.consecutive_no_progress >= 3,
            llm_prompt=None, cooldown_rounds=1,
        )
        ctx = TaskContext(task=Task("test"))
        ctx.consecutive_no_progress = 1
        assert trigger.evaluate(ctx) is False

    def test_cooldown_prevents_firing(self):
        trigger = ReflectionTrigger(
            id="test", trigger_type=TriggerType.RULE,
            condition_desc="test",
            rule_check=lambda ctx: True,
            llm_prompt=None, cooldown_rounds=5,
        )
        ctx = TaskContext(task=Task("test"))
        ctx.rounds = 0
        assert trigger.evaluate(ctx) is True  # fires
        assert trigger.evaluate(ctx) is False  # cooldown


class TestMetaDriver:
    def test_evaluate_triggers_rule_type(self, meta):
        ctx = TaskContext(task=Task("test"))
        ctx.consecutive_no_progress = 5
        triggered = meta.evaluate_triggers(ctx)
        assert any(t.id == "stagnation" for t in triggered)

    def test_evaluate_triggers_task_failed(self, meta):
        ctx = TaskContext(task=Task("test"))
        ctx.eval_result = "failure"
        triggered = meta.evaluate_triggers(ctx)
        assert any(t.id == "task_failed" for t in triggered)

    def test_validate_l1_change_rejects_duplicate(self):
        meta = MetaDriver(DEFAULT_TRIGGERS, DEFAULT_VALIDATORS, None)
        from core.philosophy import Rule as L1Rule
        existing = [L1Rule(id="r1", content="be careful", created_by="seed")]
        proposal = L1Proposal(content="be careful", reason="test")
        approved, reason = meta.validate_l1_change(proposal, existing)
        assert approved is False

    def test_validate_l1_change_rejects_over_limit(self):
        meta = MetaDriver(DEFAULT_TRIGGERS, DEFAULT_VALIDATORS, None, max_rules=2)
        from core.philosophy import Rule as L1Rule
        existing = [
            L1Rule(id="r1", content="rule 1", created_by="seed"),
            L1Rule(id="r2", content="rule 2", created_by="seed"),
        ]
        proposal = L1Proposal(content="rule 3", reason="test")
        approved, reason = meta.validate_l1_change(proposal, existing)
        assert approved is False
        assert "上限" in reason

    def test_filter_dangerous_removes_blocked(self, meta):
        calls = [
            MagicMock(function=MagicMock(name="safe_tool")),
            MagicMock(function=MagicMock(name="unsafe_delete_all")),
        ]
        meta.dangerous_tool_patterns = ["delete_all"]
        filtered = meta.filter_dangerous(calls)
        assert len(filtered) == 1
        assert filtered[0].function.name == "safe_tool"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd C:/Users/micha/PycharmProjects/cognitive-agent && python -m pytest tests/test_meta_driver.py -v
```
Expected: FAIL (ModuleNotFoundError)

- [ ] **Step 3: Write MetaDriver implementation**

```python
# core/meta_driver.py
from __future__ import annotations
import json
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

logger = logging.getLogger(__name__)


class TriggerType(Enum):
    RULE = "rule"
    LLM = "llm"


@dataclass
class ReflectionTrigger:
    id: str
    trigger_type: TriggerType
    condition_desc: str
    rule_check: Callable | None = None
    llm_prompt: str | None = None
    cooldown_rounds: int = 1
    last_triggered_at: int = -999

    def evaluate(self, ctx) -> bool:
        if ctx.rounds - self.last_triggered_at < self.cooldown_rounds:
            return False
        if self.trigger_type == TriggerType.RULE and self.rule_check:
            result = self.rule_check(ctx)
            if result:
                self.last_triggered_at = ctx.rounds
            return result
        return False

    def evaluate_with_llm(self, ctx, llm_client) -> bool:
        if ctx.rounds - self.last_triggered_at < self.cooldown_rounds:
            return False
        if self.trigger_type != TriggerType.LLM or not self.llm_prompt:
            return False
        prompt = self.llm_prompt.format(
            task_description=ctx.task.description,
            domain=ctx.task.domain.path,
            execution_summary="(summary unavailable)",
            new_domain=ctx.task.domain.path,
            previous_domains="",
            l2_domains="",
        )
        try:
            resp = llm_client.chat(messages=[{"role": "user", "content": prompt}])
            data = json.loads(resp.text)
            triggered = data.get("triggered", data.get("completed", False))
            if triggered:
                self.last_triggered_at = ctx.rounds
            return bool(triggered)
        except Exception as e:
            logger.debug("LLM trigger %s failed: %s", self.id, e)
            return False


@dataclass
class ValidationRule:
    id: str
    description: str
    check_fn: Callable  # (proposal, existing_rules) -> (approved:bool, reason:str)

# ── Default triggers (hardcoded, immutable by agent) ──

def _check_stagnation(ctx) -> bool:
    return ctx.consecutive_no_progress >= 3

def _check_task_failure(ctx) -> bool:
    return ctx.eval_result == "failure"

def _check_task_completion(ctx) -> bool:
    return ctx.eval_result == "success"

TASK_COMPLETED_LLM_PROMPT = (
    "Review the following task execution:\n"
    "Task: {task_description}\nDomain: {domain}\nExecution: {execution_summary}\n\n"
    "Respond in JSON:\n"
    '{{"completed": true/false, "efficient": true/false, '
    '"knowledge_to_create": [{{"content": "...", "confidence": 0.0-1.0}}], '
    '"l1_proposals": [{{"content": "...", "reason": "..."}}]}}'
)

DOMAIN_SHIFT_LLM_PROMPT = (
    "Agent entered new domain: '{new_domain}'. Previous: {previous_domains}. "
    "L2 covers: {l2_domains}. "
    "Respond in JSON: {{'is_new_domain': true/false, "
    "'adjacent_domains': [], 'recommended_general_cards': []}}"
)

DEFAULT_TRIGGERS = [
    ReflectionTrigger(
        id="stagnation", trigger_type=TriggerType.RULE,
        condition_desc="连续3轮无实质进展",
        rule_check=_check_stagnation, cooldown_rounds=5,
    ),
    ReflectionTrigger(
        id="task_failed", trigger_type=TriggerType.RULE,
        condition_desc="明确判定任务失败",
        rule_check=_check_task_failure, cooldown_rounds=1,
    ),
    ReflectionTrigger(
        id="task_completed", trigger_type=TriggerType.LLM,
        condition_desc="任务完成确认并提取经验",
        llm_prompt=TASK_COMPLETED_LLM_PROMPT, cooldown_rounds=3,
    ),
    ReflectionTrigger(
        id="domain_shift", trigger_type=TriggerType.LLM,
        condition_desc="进入新领域需跨域知识迁移",
        llm_prompt=DOMAIN_SHIFT_LLM_PROMPT, cooldown_rounds=10,
    ),
]

# ── Default validation rules (hardcoded) ──

def _check_not_duplicate(proposal, existing) -> tuple[bool, str]:
    for r in existing:
        if proposal.content.strip() == r.content.strip():
            return False, "新规则与已有规则完全重复"
    return True, ""

def _check_no_contradiction(proposal, existing) -> tuple[bool, str]:
    # Simple heuristic: check for negation patterns
    negations = ["不要", "禁止", "避免", "别"]
    for r in existing:
        for neg in negations:
            if neg in proposal.content and proposal.content.replace(neg, "") in r.content:
                return False, f"新规则可能与已有规则矛盾 (涉及'{neg}')"
    return True, ""

def _check_under_limit(proposal, existing, max_rules: int = 20) -> tuple[bool, str]:
    if len(existing) >= max_rules:
        return False, f"规则总数已达上限 {max_rules} 条"
    return True, ""

def _check_under_length(proposal, existing, max_length: int = 100) -> tuple[bool, str]:
    if len(proposal.content) > max_length:
        return False, f"规则长度 {len(proposal.content)} 超过上限 {max_length}"
    return True, ""

DEFAULT_VALIDATORS = [
    ValidationRule(id="not_duplicate", description="不重复", check_fn=_check_not_duplicate),
    ValidationRule(id="no_contradiction", description="不矛盾", check_fn=_check_no_contradiction),
]


class MetaDriver:
    """L0.5: Immutable meta-driver. Hardcoded triggers and validators."""

    def __init__(self, triggers: list[ReflectionTrigger],
                 validation_rules: list[ValidationRule],
                 auxiliary_llm=None,
                 max_rules: int = 20,
                 max_rule_length: int = 100):
        self.triggers = triggers
        self.validation_rules = validation_rules
        self.auxiliary_llm = auxiliary_llm
        self.max_rules = max_rules
        self.max_rule_length = max_rule_length
        self.dangerous_tool_patterns: list[str] = [
            "delete_all", "drop_table", "format", "rm -rf",
        ]
        self._turn_state = {"consecutive_no_progress": 0}

    def reset_turn_state(self):
        self._turn_state = {"consecutive_no_progress": 0}

    def track_progress(self, results: list):
        has_progress = any(
            "error" not in str(r).lower()
            for _, r in results
        )
        if has_progress:
            self._turn_state["consecutive_no_progress"] = 0
        else:
            self._turn_state["consecutive_no_progress"] += 1

    # ── Triggers ──

    def evaluate_triggers(self, ctx) -> list[ReflectionTrigger]:
        fired = []
        for trigger in self.triggers:
            if trigger.trigger_type == TriggerType.RULE:
                if trigger.evaluate(ctx):
                    fired.append(trigger)
            elif trigger.trigger_type == TriggerType.LLM and self.auxiliary_llm:
                if trigger.evaluate_with_llm(ctx, self.auxiliary_llm):
                    fired.append(trigger)
        return fired

    # ── Reflection ──

    def run_reflection(self, trigger: ReflectionTrigger, task, messages: list) -> ReflectionResult:
        if trigger.trigger_type == TriggerType.LLM and self.auxiliary_llm:
            return self._llm_reflection(trigger, task, messages)
        return ReflectionResult()

    def _llm_reflection(self, trigger, task, messages) -> ReflectionResult:
        prompt = trigger.llm_prompt.format(
            task_description=task.description,
            domain=task.domain.path,
            execution_summary=self._summarize_messages(messages),
            new_domain=task.domain.path,
            previous_domains="",
            l2_domains="",
        )
        try:
            resp = self.auxiliary_llm.chat(
                messages=[{"role": "user", "content": prompt}],
            )
            data = json.loads(resp.text)
            result = ReflectionResult()
            for item in data.get("knowledge_to_create", []):
                result.knowledge_updates.append({
                    "content": item["content"],
                    "confidence": item.get("confidence", 0.7),
                    "source": "reflection",
                })
            for item in data.get("l1_proposals", []):
                result.l1_proposals.append(
                    type('L1Proposal', (), {
                        'content': item["content"],
                        'reason': item.get("reason", ""),
                        'domain': task.domain.path,
                    })()
                )
            return result
        except Exception as e:
            logger.warning("Reflection failed for %s: %s", trigger.id, e)
            return ReflectionResult()

    def _summarize_messages(self, messages: list) -> str:
        lines = []
        for m in messages[-10:]:
            role = m.get("role", "?")
            content = str(m.get("content", ""))[:200]
            lines.append(f"[{role}] {content}")
        return "\n".join(lines)

    # ── L1 Validation ──

    def validate_l1_change(self, proposal, existing_rules: list) -> tuple[bool, str]:
        for vr in self.validation_rules:
            approved, reason = vr.check_fn(proposal, existing_rules)
            if not approved:
                return False, f"[{vr.id}] {reason}"
        approved, reason = _check_under_limit(proposal, existing_rules, self.max_rules)
        if not approved:
            return False, reason
        approved, reason = _check_under_length(proposal, existing_rules, self.max_rule_length)
        if not approved:
            return False, reason
        return True, ""

    # ── Tool filtering ──

    def filter_dangerous(self, tool_calls: list) -> list:
        return [
            tc for tc in tool_calls
            if not any(
                pattern in tc.function.name
                for pattern in self.dangerous_tool_patterns
            )
        ]

    # ── Completion check ──

    def check_completion(self, task, messages) -> str:
        """Simple heuristic: if last assistant message has no tool_calls, done."""
        if not messages:
            return "continue"
        last = messages[-1]
        if last.get("role") == "assistant" and not last.get("tool_calls"):
            return "done"
        return "continue"

    def task_decompose_trigger(self, task) -> list:
        """Phase 1: return empty. Future: LLM-based decomposition."""
        return []


@dataclass
class ReflectionResult:
    knowledge_updates: list[dict] = field(default_factory=list)
    l1_proposals: list = field(default_factory=list)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd C:/Users/micha/PycharmProjects/cognitive-agent && python -m pytest tests/test_meta_driver.py -v
```
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
cd C:/Users/micha/PycharmProjects/cognitive-agent && git add core/meta_driver.py tests/test_meta_driver.py && git commit -m "feat: add L0.5 MetaDriver — RULE+LLM triggers, validators, reflection, tool filtering"
```

---

### Task 8: Layer context bridge

**Files:**
- Create: `core/layer_context.py`
- Create: `tests/test_layer_context.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_layer_context.py
import pytest
from unittest.mock import MagicMock, patch
from core.layer_context import LayerContext
from core.task import Task, Domain, TaskResult


@pytest.fixture
def mock_layers():
    meta = MagicMock()
    meta.filter_dangerous.return_value = [MagicMock()]
    meta.evaluate_triggers.return_value = []
    meta.run_reflection.return_value = MagicMock(
        knowledge_updates=[], l1_proposals=[]
    )
    meta.validate_l1_change.return_value = (True, "")
    meta.check_completion.return_value = "done"
    meta.task_decompose_trigger.return_value = []

    l1 = MagicMock()
    l1.get_active_rules.return_value = ["rule1", "rule2"]
    l1.all_rules.return_value = [MagicMock(content="rule1"), MagicMock(content="rule2")]
    l1.apply.return_value = None

    l2 = MagicMock()
    l2.get_active_cards.return_value = [
        MagicMock(
            id="card_001", content="test knowledge",
            domain=Domain("textworld/map_A", "specific"),
            confidence=0.9, activation=0.85,
        )
    ]
    l2.update_from_tool_results.return_value = None
    l2.apply_updates.return_value = None
    l2.get_domain_cards.return_value = [MagicMock(activation=0.8)]

    l3 = MagicMock()
    l3.match.return_value = [MagicMock(name="test-skill")]
    l3.should_create_skill.return_value = False

    return LayerContext(meta=meta, l1=l1, l2=l2, l3=l3)


class TestLayerContext:
    def test_build_context_includes_l1_rules(self, mock_layers):
        task = Task("test", Domain("textworld/map_A", "specific"))
        context = mock_layers.build_context(task)
        assert "rule1" in context
        assert "rule2" in context

    def test_build_context_includes_l2_cards(self, mock_layers):
        task = Task("test", Domain("textworld/map_A", "specific"))
        context = mock_layers.build_context(task)
        assert "test knowledge" in context

    def test_build_context_includes_l3_skills(self, mock_layers):
        task = Task("test", Domain("textworld/map_A", "specific"))
        context = mock_layers.build_context(task)
        assert "test-skill" in context

    def test_build_context_empty(self, mock_layers):
        mock_layers.l1.get_active_rules.return_value = []
        mock_layers.l2.get_active_cards.return_value = []
        mock_layers.l3.match.return_value = []
        task = Task("test", Domain("general", "general"))
        context = mock_layers.build_context(task)
        assert context == ""

    def test_filter_tool_calls(self, mock_layers):
        calls = [MagicMock(), MagicMock()]
        mock_layers.meta.filter_dangerous.return_value = calls[:1]
        result = mock_layers.filter_tool_calls(calls)
        assert len(result) == 1

    def test_post_task_no_triggers(self, mock_layers):
        task = Task("test", Domain("general", "general"))
        result = mock_layers.post_task(task, [])
        assert isinstance(result, TaskResult)
        assert result.new_knowledge_cards == 0
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd C:/Users/micha/PycharmProjects/cognitive-agent && python -m pytest tests/test_layer_context.py -v
```
Expected: FAIL

- [ ] **Step 3: Write LayerContext implementation**

```python
# core/layer_context.py
from __future__ import annotations
import logging
from core.task import Task, TaskResult

logger = logging.getLogger(__name__)


class LayerContext:
    """Bridge between layers and event loop. Each layer is transparent to the loop."""

    def __init__(self, meta, l1, l2, l3):
        self.meta = meta
        self.l1 = l1
        self.l2 = l2
        self.l3 = l3

    # ── Insertion point 1: PRE-LLM ──

    def build_context(self, task: Task) -> str:
        parts = []

        active_rules = self.l1.get_active_rules(task)
        if active_rules:
            parts.append(
                "[Behavioral Principles]\n" +
                "\n".join(f"- {r}" for r in active_rules)
            )

        active_cards = self.l2.get_active_cards(task.domain, task.context or "", top_k=5)
        if active_cards:
            parts.append(
                "[Relevant Knowledge]\n" +
                "\n".join(
                    f"- [{c.domain.path}] {c.content} "
                    f"(confidence:{c.confidence:.1f}, activation:{c.activation:.2f})"
                    for c in active_cards
                )
            )

        matching_skills = self.l3.match(task.domain)
        if matching_skills:
            parts.append(
                "[Available Skills]\n" +
                ", ".join(f"`{s.name}`" for s in matching_skills) +
                "\nUse `skill_view(name)` to load a skill's full instructions."
            )

        return "\n\n".join(parts) if parts else ""

    # ── Insertion point 2: PRE-TOOL ──

    def filter_tool_calls(self, calls: list) -> list:
        return self.meta.filter_dangerous(calls)

    # ── Insertion point 3: POST-TOOL ──

    def on_tool_results(self, task, results):
        self.l2.update_from_tool_results(task, results)
        self.meta.track_progress(results)

    # ── Insertion point 4: COMPLETION CHECK ──

    def check_completion(self, task, messages):
        return self.meta.check_completion(task, messages)

    # ── Insertion point 5: POST-TASK ──

    def post_task(self, task: Task, messages: list) -> TaskResult:
        result = TaskResult()

        triggers = self.meta.evaluate_triggers(task, messages)
        if not triggers:
            return result

        for trigger in triggers:
            reflection = self.meta.run_reflection(trigger, task, messages)

            # Step 1: L2 updates
            if reflection.knowledge_updates:
                self.l2.apply_updates(reflection.knowledge_updates, task.domain)
                result.new_knowledge_cards = len(reflection.knowledge_updates)

            # Step 2: L1 proposals
            existing_rules = self.l1.all_rules()
            for proposal in reflection.l1_proposals:
                approved, reason = self.meta.validate_l1_change(proposal, existing_rules)
                if approved:
                    self.l1.apply(proposal)
                    result.l1_changes.append(f"+{proposal.content[:50]}...")
                else:
                    self.l2.add_failed_proposal_record(proposal)
                    result.l1_rejections.append(reason)

            # Step 3: L3 compilation check
            domain_cards = self.l2.get_domain_cards(task.domain)
            if self.l3.should_create_skill(task.domain, domain_cards):
                skill_meta = self.l3.propose_and_create(
                    task.domain, domain_cards,
                )
                if skill_meta:
                    result.new_skills.append(skill_meta.name)

        return result
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd C:/Users/micha/PycharmProjects/cognitive-agent && python -m pytest tests/test_layer_context.py -v
```
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
cd C:/Users/micha/PycharmProjects/cognitive-agent && git add core/layer_context.py tests/test_layer_context.py && git commit -m "feat: add LayerContext — 5 insertion points bridging layers and event loop"
```

---

### Task 9: Agent loop

**Files:**
- Create: `core/agent_loop.py`
- Create: `tests/test_agent_loop.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_agent_loop.py
import pytest
from unittest.mock import MagicMock, patch
from core.agent_loop import AgentLoop
from core.task import Task, Domain


@pytest.fixture
def mock_llm():
    llm = MagicMock()
    # First call returns tool_calls, second returns text (done)
    tool_resp = MagicMock()
    tool_resp.has_tool_calls = True
    tool_resp.tool_calls = [
        MagicMock(function=MagicMock(name="skills_list"))
    ]
    text_resp = MagicMock()
    text_resp.has_tool_calls = False
    text_resp.text = "Task completed."
    llm.chat.side_effect = [tool_resp, text_resp]
    return llm


@pytest.fixture
def mock_tools():
    registry = MagicMock()
    registry.schemas = []
    registry.dispatch.return_value = [("skills_list", '{"success": true}')]
    return registry


@pytest.fixture
def mock_layers():
    layers = MagicMock()
    layers.build_context.return_value = "[L1 rules]\n- rule1"
    layers.filter_tool_calls.side_effect = lambda x: x
    layers.on_tool_results.return_value = None
    layers.check_completion.return_value = "done"
    layers.post_task.return_value = MagicMock(
        success=True, new_knowledge_cards=2, l1_changes=[], new_skills=[]
    )
    return layers


class TestAgentLoop:
    def test_run_simple_task(self, mock_llm, mock_tools, mock_layers):
        loop = AgentLoop(mock_llm, mock_tools, mock_layers, max_iterations=10)
        task = Task("test task", Domain("general", "general"))
        result = loop.run(task)
        assert result is not None
        assert mock_llm.chat.called
        # build_context called at least once
        assert mock_layers.build_context.called
        # post_task called at end
        assert mock_layers.post_task.called

    def test_max_iterations_respected(self, mock_llm, mock_tools, mock_layers):
        # Never returns done → should hit max_iterations
        tool_resp = MagicMock()
        tool_resp.has_tool_calls = True
        tool_resp.tool_calls = [MagicMock(function=MagicMock(name="skills_list"))]
        mock_llm.chat.return_value = tool_resp
        mock_layers.check_completion.return_value = "continue"

        loop = AgentLoop(mock_llm, mock_tools, mock_layers, max_iterations=3)
        task = Task("test", Domain("general", "general"))
        result = loop.run(task)
        assert mock_llm.chat.call_count == 3

    def test_system_prompt_includes_l1_rules(self, mock_llm, mock_tools, mock_layers):
        mock_layers.l1 = MagicMock()
        mock_layers.l1.all_rules.return_value = [
            MagicMock(content="rule A"),
            MagicMock(content="rule B"),
        ]
        loop = AgentLoop(mock_llm, mock_tools, mock_layers, max_iterations=3)
        task = Task("test", Domain("general", "general"))
        loop.run(task)
        system_msg = mock_llm.chat.call_args_list[0][1]["messages"][0]
        assert system_msg["role"] == "system"
        assert "rule A" in system_msg["content"]
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd C:/Users/micha/PycharmProjects/cognitive-agent && python -m pytest tests/test_agent_loop.py -v
```
Expected: FAIL

- [ ] **Step 3: Write AgentLoop implementation**

```python
# core/agent_loop.py
from __future__ import annotations
import logging
from core.task import Task, TaskResult

logger = logging.getLogger(__name__)


class AgentLoop:
    """Minimal event loop. Pattern extracted from Hermes run_conversation() (~3900→~100 lines)."""

    def __init__(self, llm_client, tool_registry, layers, max_iterations: int = 50):
        self.llm = llm_client
        self.tools = tool_registry
        self.layers = layers
        self.max_iterations = max_iterations

    def run(self, task: Task) -> TaskResult:
        messages = []
        iteration = 0
        self.layers.meta.reset_turn_state()

        # Build system prompt once
        system_prompt = self._build_system_prompt(task)
        messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": task.description})

        while iteration < self.max_iterations:
            iteration += 1

            # ── Insertion point 1: PRE-LLM ──
            context_block = self.layers.build_context(task)
            if context_block:
                messages[-1]["content"] += "\n\n" + context_block

            # ── API call ──
            try:
                response = self._call_llm(messages)
            except Exception as e:
                logger.warning("LLM call failed (iteration %s): %s", iteration, e)
                continue

            if response.has_tool_calls:
                # ── Insertion point 2: PRE-TOOL ──
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

                for i, tc in enumerate(filtered):
                    try:
                        import json as _json
                        args = _json.loads(getattr(tc.function, 'arguments', '{}'))
                    except Exception:
                        args = {}
                    raw_result = self.tools.dispatch(tc.function.name, args)
                    messages.append({
                        "role": "tool",
                        "name": tc.function.name,
                        "content": raw_result,
                        "tool_call_id": f"call_{i}",
                    })

                tool_results = [
                    (tc.function.name, messages[-1]["content"])
                    for tc in filtered
                ]

                # ── Insertion point 3: POST-TOOL ──
                self.layers.on_tool_results(task, tool_results)

            else:
                messages.append({
                    "role": "assistant",
                    "content": response.text or "",
                })

                # ── Insertion point 4: COMPLETION CHECK ──
                verdict = self.layers.check_completion(task, messages)
                if verdict == "done":
                    break

        # ── Insertion point 5: POST-TASK ──
        result = self.layers.post_task(task, messages)
        result.iterations_used = iteration
        result.final_response = (
            messages[-1].get("content", "") if messages else ""
        )
        result.success = True
        return result

    def _call_llm(self, messages):
        resp = self.llm.chat(
            messages=messages,
            tools=self.tools.schemas if hasattr(self.tools, 'schemas') else None,
        )
        # Normalize response shape
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
        # L1 rules
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

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd C:/Users/micha/PycharmProjects/cognitive-agent && python -m pytest tests/test_agent_loop.py -v
```
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
cd C:/Users/micha/PycharmProjects/cognitive-agent && git add core/agent_loop.py tests/test_agent_loop.py && git commit -m "feat: add AgentLoop — event loop with 5 insertion points"
```

---

### Task 10: Agent config + Agent main class + main.py

**Files:**
- Create: `core/config.py`
- Create: `core/agent.py`
- Create: `main.py`
- Create: `tests/test_agent.py`

- [ ] **Step 1: Write config and agent**

```python
# core/config.py
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class AgentConfig:
    main_llm: Any = None
    auxiliary_llm: Any = None
    max_iterations: int = 50
    l1_max_rules: int = 20
    l1_max_rule_length: int = 100
    l1_rules_path: Path = Path("./data/l1_rules.json")
    skills_dir: Path = Path("./skills")
    knowledge_dir: Path = Path("./knowledge")
    l2_index_path: Path = Path("./knowledge/l2_index.json")
    seed_l1_rules: list[str] | None = None
    seed_l2_cards: list[dict] | None = None
    seed_l3_skills: list[Path] | None = None
```

```python
# core/agent.py
from __future__ import annotations
import logging
from pathlib import Path
from core.config import AgentConfig
from core.task import Task, Domain
from core.tools.registry import ToolRegistry
from core.skill_layer import SkillLayer
from core.flexible_knowledge import FlexibleKnowledge
from core.philosophy import Philosophy
from core.meta_driver import MetaDriver, DEFAULT_TRIGGERS, DEFAULT_VALIDATORS
from core.layer_context import LayerContext
from core.agent_loop import AgentLoop

logger = logging.getLogger(__name__)


class CognitiveAgent:
    """Minimal cognitive agent aggregating 4 layers + event loop."""

    def __init__(self, config: AgentConfig):
        self.tool_registry = ToolRegistry()
        self.config = config

        # Init bottom-up: L3 → L2 → L1 → L0.5
        self.l3 = SkillLayer(config.skills_dir, self.tool_registry)
        self.l2 = FlexibleKnowledge(config.knowledge_dir, config.l2_index_path)
        self.l1 = Philosophy(
            config.l1_rules_path,
            max_rules=config.l1_max_rules,
            max_rule_length=config.l1_max_rule_length,
        )
        self.meta = MetaDriver(
            triggers=DEFAULT_TRIGGERS,
            validation_rules=DEFAULT_VALIDATORS,
            auxiliary_llm=config.auxiliary_llm,
            max_rules=config.l1_max_rules,
            max_rule_length=config.l1_max_rule_length,
        )
        self.layers = LayerContext(self.meta, self.l1, self.l2, self.l3)
        self.loop = AgentLoop(
            llm_client=config.main_llm,
            tool_registry=self.tool_registry,
            layers=self.layers,
            max_iterations=config.max_iterations,
        )

        self._bootstrap(config)

    def run(self, user_input: str, domain: Domain | None = None) -> any:
        task = Task(
            description=user_input,
            domain=domain or Domain("general", "general"),
        )
        return self.loop.run(task)

    def _bootstrap(self, config: AgentConfig):
        """Inject seed data for cold start."""
        if config.seed_l1_rules:
            for rule_text in config.seed_l1_rules:
                try:
                    self.l1.add_rule(rule_text, created_by="seed")
                except ValueError:
                    pass  # already exists

        if config.seed_l2_cards:
            for card_data in config.seed_l2_cards:
                self.l2.add_card(
                    content=card_data["content"],
                    domain=Domain(card_data.get("domain", "general"), "general"),
                    confidence=card_data.get("confidence", 0.7),
                    source=card_data.get("source", "seed"),
                )

        if config.seed_l3_skills:
            for skill_path in config.seed_l3_skills:
                self.l3.import_skill(skill_path)

    # ── Management ──
    def inspect_l1(self) -> list:
        return self.l1.all_rules()

    def inspect_l2(self, domain: Domain) -> list:
        return self.l2.get_domain_cards(domain)

    def inspect_l3(self) -> list:
        return self.l3.list_all()
```

```python
# main.py
"""Cognitive Agent — entry point."""
import yaml
import os
from pathlib import Path
from openai import OpenAI
from core.config import AgentConfig
from core.agent import CognitiveAgent


def load_config(config_path: str = "config.yaml") -> AgentConfig:
    with open(config_path) as f:
        raw = yaml.safe_load(f)

    main_cfg = raw.get("main_llm", {})
    aux_cfg = raw.get("auxiliary_llm", {})

    main_llm = OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=os.environ.get(main_cfg.get("api_key_env", "OPENROUTER_API_KEY")),
    )
    aux_llm = OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=os.environ.get(aux_cfg.get("api_key_env", "OPENROUTER_API_KEY")),
    )

    return AgentConfig(
        main_llm=_LLMWrapper(main_llm, main_cfg.get("model", "")),
        auxiliary_llm=_LLMWrapper(aux_llm, aux_cfg.get("model", "")),
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


class _LLMWrapper:
    """Minimal wrapper adapting OpenAI client to our expected interface."""
    def __init__(self, client: OpenAI, model: str):
        self._client = client
        self.model = model

    def chat(self, messages, tools=None, **kwargs):
        from unittest.mock import MagicMock
        params = {"model": self.model, "messages": messages}
        if tools:
            import json
            params["tools"] = [
                {"type": "function", "function": t["function"]}
                if isinstance(t, dict) and "function" in t
                else t
                for t in tools
            ]
        resp = self._client.chat.completions.create(**params)
        msg = resp.choices[0].message
        wrapper = MagicMock()
        wrapper.has_tool_calls = bool(msg.tool_calls)
        wrapper.tool_calls = msg.tool_calls or []
        wrapper.text = msg.content or ""
        return wrapper


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

- [ ] **Step 2: Write integration test**

```python
# tests/test_agent.py
import pytest
from unittest.mock import MagicMock, patch
from core.config import AgentConfig
from core.agent import CognitiveAgent
from core.task import Domain


@pytest.fixture
def mock_agent_config(temp_dir):
    # LLM that returns text on first call
    llm = MagicMock()
    resp = MagicMock()
    resp.has_tool_calls = False
    resp.text = "I have completed the task."
    llm.chat.return_value = resp

    # Set up paths in temp dir
    rules_path = temp_dir / "l1_rules.json"
    rules_path.write_text('{"version":1,"rules":[]}')
    skills_dir = temp_dir / "skills"
    skills_dir.mkdir()
    (skills_dir / "general").mkdir()
    knowledge_dir = temp_dir / "knowledge"
    knowledge_dir.mkdir()
    (knowledge_dir / "general").mkdir()
    index_path = knowledge_dir / "l2_index.json"
    index_path.write_text('{"version":1,"chapters":[],"relations":[]}')

    return AgentConfig(
        main_llm=llm,
        auxiliary_llm=llm,
        max_iterations=10,
        l1_rules_path=rules_path,
        skills_dir=skills_dir,
        knowledge_dir=knowledge_dir,
        l2_index_path=index_path,
        seed_l1_rules=["test seed rule"],
    )


class TestCognitiveAgent:
    def test_agent_creation(self, mock_agent_config):
        agent = CognitiveAgent(mock_agent_config)
        assert agent.l1 is not None
        assert agent.l2 is not None
        assert agent.l3 is not None
        assert agent.meta is not None
        assert agent.layers is not None
        assert agent.loop is not None

    def test_agent_run(self, mock_agent_config):
        agent = CognitiveAgent(mock_agent_config)
        result = agent.run("Do a test task")
        assert result is not None
        assert result.iterations_used > 0

    def test_seed_data_injected(self, mock_agent_config):
        agent = CognitiveAgent(mock_agent_config)
        rules = agent.inspect_l1()
        assert any("test seed rule" in r.content for r in rules)

    def test_inspect_methods(self, mock_agent_config):
        agent = CognitiveAgent(mock_agent_config)
        assert len(agent.inspect_l1()) >= 0
        assert len(agent.inspect_l3()) >= 0
```

- [ ] **Step 3: Run all tests**

```bash
cd C:/Users/micha/PycharmProjects/cognitive-agent && python -m pytest tests/ -v
```
Expected: all PASS (~30+ tests)

- [ ] **Step 4: Commit**

```bash
cd C:/Users/micha/PycharmProjects/cognitive-agent && git add -A && git commit -m "feat: add AgentConfig, CognitiveAgent, main.py — complete framework assembly"
```

---

### Task 11: Todo and Terminal tools (remaining tools)

**Files:**
- Create: `core/tools/todo_tool.py`
- Create: `core/tools/terminal_tool.py`

These are small utility tools. Write them directly with light tests.

- [ ] **Step 1: Write todo tool**

```python
# core/tools/todo_tool.py
"""Minimal todo tool for subtask tracking."""
import json


class TodoStore:
    def __init__(self):
        self._items: list[dict] = []

    def update(self, todos: list[dict]) -> list[dict]:
        for t in todos:
            t.setdefault("status", "pending")
            existing = next((i for i in self._items if i.get("id") == t.get("id")), None)
            if existing:
                existing.update(t)
            else:
                self._items.append(t)
        return self._items

    def active(self) -> list[dict]:
        return [t for t in self._items if t.get("status") in ("pending", "in_progress")]

    def format(self) -> str:
        active = self.active()
        if not active:
            return "No active tasks."
        return "\n".join(
            f"- [{t['status']}] {t.get('content', t.get('id', '?'))}"
            for t in active
        )


_store = TodoStore()


def _register_todo_tool(registry):
    def handler(args=None, context=None):
        todos = (args or {}).get("todos")
        if todos:
            updated = _store.update(todos)
            return json.dumps({"success": True, "todos": updated})
        return json.dumps({"todos": _store.active()})

    registry.register("todo", {
        "type": "function",
        "function": {
            "name": "todo",
            "description": "Create or view subtask tracking list",
            "parameters": {
                "type": "object",
                "properties": {
                    "todos": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "id": {"type": "string"},
                                "content": {"type": "string"},
                                "status": {"type": "string", "enum": ["pending", "in_progress", "completed", "cancelled"]}
                            }
                        }
                    }
                }
            }
        }
    }, handler, toolset="core")
```

```python
# core/tools/terminal_tool.py
"""Minimal terminal tool for environment command execution."""
import json
import subprocess
import logging

logger = logging.getLogger(__name__)


def _register_terminal_tool(registry, allowed_commands: list[str] | None = None):
    def handler(args=None, context=None):
        command = (args or {}).get("command", "")
        if not command:
            return json.dumps({"error": "No command provided"})

        if allowed_commands and not any(
            command.startswith(cmd) for cmd in allowed_commands
        ):
            return json.dumps({"error": f"Command not allowed: {command}"})

        try:
            result = subprocess.run(
                command, shell=True, capture_output=True, text=True, timeout=30,
            )
            output = result.stdout
            if result.stderr:
                output += "\n[stderr]\n" + result.stderr
            return json.dumps({
                "stdout": result.stdout,
                "stderr": result.stderr,
                "returncode": result.returncode,
            })
        except subprocess.TimeoutExpired:
            return json.dumps({"error": "Command timed out (30s)"})
        except Exception as e:
            return json.dumps({"error": str(e)})

    registry.register("terminal", {
        "type": "function",
        "function": {
            "name": "terminal",
            "description": "Execute a shell command and capture stdout/stderr",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "Shell command to execute"
                    }
                },
                "required": ["command"]
            }
        }
    }, handler, toolset="core")
```

- [ ] **Step 2: Run all tests**

```bash
cd C:/Users/micha/PycharmProjects/cognitive-agent && python -m pytest tests/ -v
```
Expected: all PASS

- [ ] **Step 3: Final commit**

```bash
cd C:/Users/micha/PycharmProjects/cognitive-agent && git add -A && git commit -m "feat: add todo and terminal tools"
```

---

## Plan Summary

| Task | Component | Files | Key Tests |
|------|-----------|-------|-----------|
| 1 | Project scaffold | pyproject.toml, config.yaml, seed data | Import check |
| 2 | Core types | core/task.py | Domain hierarchy, TaskResult |
| 3 | Tool registry | core/tools/registry.py | Register, dispatch, deregister |
| 4 | L3 Skill layer | core/skill_layer.py | CRUD, match, tool registration |
| 5 | L2 Knowledge | core/flexible_knowledge.py | Cards, activation, MD+JSON+Graph |
| 6 | L1 Philosophy | core/philosophy.py | Rules CRUD, persistence |
| 7 | L0.5 Meta driver | core/meta_driver.py | Triggers, validators, reflection |
| 8 | Layer context | core/layer_context.py | 5 insertion points |
| 9 | Agent loop | core/agent_loop.py | Event loop, system prompt |
| 10 | Agent + config + main | core/agent.py, core/config.py, main.py | Full integration |
| 11 | Todo + Terminal tools | core/tools/todo_tool.py, core/tools/terminal_tool.py | Light tests |

**Total: 11 tasks, ~35 test cases, ~1,500 lines of implementation**
