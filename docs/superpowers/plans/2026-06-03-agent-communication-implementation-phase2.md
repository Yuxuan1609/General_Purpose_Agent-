# Phase 2: Reflection & Learning Pipeline — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the full reflection learning pipeline: Task Decomposer, domain-threshold scorer, per-layer ReflectionAgent, Comm agent separation, tool decoupling, and pending→learned archive.

**Architecture:** Extends Phase 1 Execute chain with parallel reflection coordination. Executor gains Reflect mode; each layer gets ReflectionAgent for recursive problem attribution. Comm agents separate protocol handling from Manager business logic.

**Tech Stack:** Python 3.11+, dataclasses, pytest, existing Phase 1 codebase

**Prerequisite:** Phase 1 implementation complete (core/types.py, executor.py, layers/, douzero integration)

---

## File Structure (Phase 2 additions)

```
core/
  config.py                      # MODIFY: add learning config fields
  task.py                        # MODIFY: add token_count to Task
  orchestrator/
    task_decomposer.py           # MODIFY: implement from stub
    threshold_scorer.py          # NEW: domain-grouped threshold logic
    reflect_coordinator.py        # NEW: Executor reflect mode extension
  layers/
    base.py                      # MODIFY: add Manager write methods, ReflectionAgent ABC
    l0_5_1/
      upward_comm.py             # MODIFY: implement from stub
      downward_comm.py           # MODIFY: implement from stub
      reflection_agent.py        # NEW
    l2/
      upward_comm.py             # MODIFY: implement from stub
      downward_comm.py           # MODIFY: implement from stub
      reflection_agent.py        # NEW
    l3/
      upward_comm.py             # MODIFY: implement from stub
      downward_comm.py           # MODIFY: implement from stub
      reflection_agent.py        # NEW
  tools/
    registry.py                  # MODIFY: add allowed_layers, get_definitions_for_layer()

tests/
  test_decomposer.py             # NEW
  test_threshold_scorer.py       # NEW
  test_reflect_coordinator.py    # NEW
  test_reflection_agent.py       # NEW
  test_comm_agents.py            # NEW
  test_tool_allowed_layers.py    # NEW

config.yaml                      # MODIFY: add learning section
```

---

### Task 2.1: Config extension for learning pipeline

**Files:**
- Modify: `core/config.py`
- Modify: `config.yaml`

- [ ] **Step 1: Add learning fields to AgentConfig**

```python
# In core/config.py, add to AgentConfig:
@dataclass
class AgentConfig:
    # ... existing fields ...
    
    # Learning pipeline (Phase 2)
    learning_enabled: bool = True
    learning_task_count_weight: float = 1.0
    learning_complexity_weight: float = 1.0
    learning_baseline_tokens: int = 2000
    learning_threshold: float = 5.0
    learning_pending_dir: Path = Path("./data/learning/pending")
    learning_learned_dir: Path = Path("./data/learning/learned")
    learning_raw_dir: Path = Path("./data/learning/raw")
```

- [ ] **Step 2: Add learning section to config.yaml**

```yaml
# Append to config.yaml:
learning:
  enabled: true
  task_count_weight: 1.0
  complexity_weight: 1.0
  baseline_tokens: 2000
  threshold: 5.0
  pending_dir: data/learning/pending
  learned_dir: data/learning/learned
  raw_dir: data/learning/raw
```

- [ ] **Step 3: Add token_count to Task**

```python
# In core/task.py, modify Task:
@dataclass
class Task:
    description: str
    domain: Domain = field(default_factory=lambda: Domain("general", "general"))
    context: str = ""
    needs_decomposition: bool = False
    subtasks: list[Task] = field(default_factory=list)
    enable_learning: bool = False
    token_count: int = 0      # NEW: estimated token count of this task
```

- [ ] **Step 4: verify existing tests pass**

Run: `pytest tests/ -v --tb=short`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add core/config.py core/task.py config.yaml
git commit -m "feat: add learning pipeline config fields and token_count to Task"
```

---

### Task 2.2: Task Decomposer

**Files:**
- Modify: `core/orchestrator/task_decomposer.py` (replace stub)
- Create: `tests/test_decomposer.py`

- [ ] **Step 1: Write tests**

```python
import pytest
from pathlib import Path
from core.task import Task, Domain
from core.orchestrator.task_decomposer import TaskDecomposer


class TestDecomposerGameUnit:
    def test_doudizhu_returns_single_task(self, tmp_path):
        raw_log = tmp_path / "test.log"
        raw_log.write_text("game log content")

        session = {
            "id": "dz-001",
            "datetime": "2026-01-01T00:00:00",
            "task_type": "game/doudizhu",
            "meta_hash": "abc123",
        }

        dec = TaskDecomposer()
        tasks = dec.decompose(session, raw_log)

        assert len(tasks) == 1
        assert tasks[0].description == "dz-001"
        assert tasks[0].domain.path == "game/doudizhu"

    def test_leduc_returns_single_task(self, tmp_path):
        raw_log = tmp_path / "test.log"
        raw_log.write_text("")

        session = {
            "id": "le-001",
            "datetime": "2026-01-01T00:00:00",
            "task_type": "game/leduc",
            "meta_hash": "abc123",
        }

        dec = TaskDecomposer()
        tasks = dec.decompose(session, raw_log)

        assert len(tasks) == 1
        assert tasks[0].domain.path == "game/leduc"

    def test_unknown_task_type_returns_single_task(self, tmp_path):
        raw_log = tmp_path / "test.log"
        raw_log.write_text("")

        session = {
            "id": "unknown-001",
            "task_type": "bogus/type",
            "meta_hash": "abc",
        }

        dec = TaskDecomposer()
        tasks = dec.decompose(session, {})

        assert len(tasks) == 1

    def test_coding_session_single_task_stub(self, tmp_path):
        raw_log = tmp_path / "test.log"
        raw_log.write_text("user: fix bug\nassistant: ok")

        session = {
            "id": "code-001",
            "task_type": "coding/session",
            "meta_hash": "abc",
        }

        dec = TaskDecomposer()
        tasks = dec.decompose(session, raw_log)

        # Future: LLM-based split. For now, stub returns single task.
        assert len(tasks) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_decomposer.py -v`
Expected: FAIL (current stub returns [])

- [ ] **Step 3: Implement TaskDecomposer**

```python
"""Task Decomposer — splits sessions into evaluable Task units."""
from pathlib import Path
from core.task import Task, Domain


class TaskDecomposer:
    """Decompose a session into learning-unit Tasks.

    Uses rule-based strategy selection. Future: LLM-based decomposition.
    """

    def decompose(self, session: dict, raw_log: Path) -> list[Task]:
        strategy = self._select_strategy(session)
        return strategy(session, raw_log)

    def _select_strategy(self, session: dict):
        task_type = session.get("task_type", "unknown")
        registry = {
            "game/doudizhu": self._decompose_game_unit,
            "game/leduc":    self._decompose_game_unit,
            "coding/session": self._decompose_coding,
        }
        return registry.get(task_type, self._decompose_game_unit)

    def _decompose_game_unit(self, session: dict, raw_log) -> list[Task]:
        task_type = session.get("task_type", "game/unknown")
        domain = Domain(task_type.split("/", 1)[1] if "/" in task_type else task_type, "specific")
        return [Task(
            description=session["id"],
            domain=domain,
            enable_learning=session.get("enable_learning", False),
        )]

    def _decompose_coding(self, session: dict, raw_log: Path) -> list[Task]:
        # Stub: return single task. Future: LLM-based intent segmentation.
        return [Task(
            description=session["id"],
            domain=Domain("coding/session", "specific"),
            enable_learning=True,
            token_count=_count_tokens(raw_log) if raw_log.exists() else 0,
        )]


def _count_tokens(path: Path) -> int:
    """Rough token estimate: characters / 4."""
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
        return len(text) // 4
    except Exception:
        return 0
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_decomposer.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add core/orchestrator/task_decomposer.py tests/test_decomposer.py
git commit -m "feat: implement TaskDecomposer with rule-based strategy selection"
```

---

### Task 2.3: Threshold Scorer

**Files:**
- Create: `core/orchestrator/threshold_scorer.py`
- Create: `tests/test_threshold_scorer.py`

- [ ] **Step 1: Write tests**

```python
import pytest
import json
from pathlib import Path
from core.orchestrator.threshold_scorer import ThresholdScorer


@pytest.fixture
def pending_dir(tmp_path):
    d = tmp_path / "pending"
    d.mkdir()
    return d


def _write_record(path: Path, domain: str, token_count: int, session_id: str):
    record = {
        "session": {"id": session_id},
        "observation": {
            "meta": {"domain": domain},
            "state": {"token_count": token_count},
        },
        "notify_layers": {},
    }
    path.write_text(json.dumps(record))


class TestThresholdScorer:
    def test_no_files_returns_zero(self, pending_dir):
        scorer = ThresholdScorer(pending_dir)
        score = scorer.score("game/doudizhu")
        assert score == 0.0

    def test_counts_tasks_by_domain(self, pending_dir):
        _write_record(pending_dir / "s1_1.json", "game/doudizhu", 500, "s1")
        _write_record(pending_dir / "s1_2.json", "game/doudizhu", 500, "s1")
        _write_record(pending_dir / "s2_1.json", "game/leduc", 100, "s2")

        scorer = ThresholdScorer(pending_dir)
        score_dz = scorer.score("game/doudizhu")
        score_le = scorer.score("game/leduc")

        assert score_dz > score_le

    def test_respects_custom_weights(self, pending_dir):
        _write_record(pending_dir / "s1_1.json", "game/doudizhu", 500, "s1")
        _write_record(pending_dir / "s1_2.json", "game/doudizhu", 500, "s1")

        scorer_default = ThresholdScorer(pending_dir)
        scorer_heavy_count = ThresholdScorer(pending_dir, task_count_weight=10.0)

        assert scorer_heavy_count.score("game/doudizhu") > scorer_default.score("game/doudizhu")

    def test_should_trigger(self, pending_dir):
        _write_record(pending_dir / "s1_1.json", "game/doudizhu", 500, "s1")
        _write_record(pending_dir / "s1_2.json", "game/doudizhu", 500, "s1")
        _write_record(pending_dir / "s1_3.json", "game/doudizhu", 500, "s1")
        _write_record(pending_dir / "s1_4.json", "game/doudizhu", 500, "s1")
        _write_record(pending_dir / "s1_5.json", "game/doudizhu", 500, "s1")
        _write_record(pending_dir / "s1_6.json", "game/doudizhu", 500, "s1")

        scorer = ThresholdScorer(pending_dir, threshold=5.0)
        assert scorer.should_trigger("game/doudizhu") is True

    def test_below_threshold_no_trigger(self, pending_dir):
        _write_record(pending_dir / "s1_1.json", "game/doudizhu", 500, "s1")

        scorer = ThresholdScorer(pending_dir, threshold=5.0)
        assert scorer.should_trigger("game/doudizhu") is False

    def test_domain_count(self, pending_dir):
        _write_record(pending_dir / "s1_1.json", "game/doudizhu", 500, "s1")
        _write_record(pending_dir / "s2_1.json", "game/leduc", 100, "s2")
        _write_record(pending_dir / "s3_1.json", "game/doudizhu", 500, "s3")

        scorer = ThresholdScorer(pending_dir)
        assert scorer.domain_count("game/doudizhu") == 2
        assert scorer.domain_count("game/leduc") == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_threshold_scorer.py -v`
Expected: FAIL

- [ ] **Step 3: Implement ThresholdScorer**

```python
"""Threshold scorer — domain-grouped evaluation of pending learning records."""
import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class ThresholdScorer:
    def __init__(self, pending_dir: Path, task_count_weight: float = 1.0,
                 complexity_weight: float = 1.0, baseline_tokens: int = 2000,
                 threshold: float = 5.0):
        self._pending = pending_dir
        self._count_weight = task_count_weight
        self._complex_weight = complexity_weight
        self._baseline = baseline_tokens
        self.threshold = threshold

    def score(self, domain: str) -> float:
        records = self._domain_records(domain)
        if not records:
            return 0.0

        count = len(records)
        total_tokens = sum(r.get("total_tokens", 0) for r in records)
        return (self._count_weight * count
                + self._complex_weight * total_tokens / max(1, self._baseline))

    def should_trigger(self, domain: str) -> bool:
        return self.score(domain) >= self.threshold

    def domain_count(self, domain: str) -> int:
        return len(self._domain_records(domain))

    def _domain_records(self, domain: str) -> list[dict]:
        if not self._pending.exists():
            return []
        records = []
        for f in self._pending.glob("*.json"):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                obs = data.get("observation", {})
                meta = obs.get("meta", {})
                rec_domain = meta.get("domain", "")
                if rec_domain == domain or rec_domain.startswith(domain + "/"):
                    state = obs.get("state", {})
                    token_count = state.get("token_count", 0)
                    records.append({"file": f, "total_tokens": token_count})
            except Exception:
                logger.warning("Failed to read pending record: %s", f)
        return records
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_threshold_scorer.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add core/orchestrator/threshold_scorer.py tests/test_threshold_scorer.py
git commit -m "feat: add ThresholdScorer with domain-grouped evaluation"
```

---

### Task 2.4: Manager write methods + ReflectionAgent ABC

**Files:**
- Modify: `core/layers/base.py`
- Create: `tests/test_reflection_agent.py`

- [ ] **Step 1: Write tests**

```python
import pytest
from core.layers.base import LayerManager, ReflectionAgent


class _MockManager(LayerManager):
    def __init__(self, name, data_store=None, downstream=None):
        super().__init__(name, downstream)
        self._store = data_store or {}
    def process(self, data):
        return {"status": "ok"}
    def notify(self):
        return {"status": "ok"}
    def apply_update(self, key: str, value) -> None:
        self._store[key] = value
        self._store["updated"] = True


class TestReflectionAgent:
    def test_investigate_identifies_own_issues(self):
        mgr = _MockManager("l3")
        agent = ReflectionAgent("l3", mgr)
        issues = [
            {"type": "skill_mismatch", "detail": "wrong skill matched"},
        ]
        result = agent.investigate(issues, context={})
        assert len(result["my_issues"]) == 1
        assert len(result["downstream_issues"]) == 0

    def test_investigate_defaults_to_my_issues(self):
        mgr = _MockManager("l2")
        agent = ReflectionAgent("l2", mgr)
        issues = [{"type": "unknown", "detail": "something"}]
        result = agent.investigate(issues, context={})
        assert len(result["my_issues"]) == 1

    def test_fix_calls_manager_apply_update(self):
        mgr = _MockManager("l3")
        agent = ReflectionAgent("l3", mgr)
        my_issues = [{"type": "skill_mismatch", "fix": "downgrade"}]
        result = agent.fix(my_issues)
        assert mgr._store["updated"] is True
        assert result["fixes_applied"] == 1

    def test_query_downstream_delegates(self):
        l3_mgr = _MockManager("l3")
        l2_mgr = _MockManager("l2", downstream=l3_mgr)
        l2_agent = ReflectionAgent("l2", l2_mgr, downstream=ReflectionAgent("l3", l3_mgr))

        issues = [{"type": "card_decay", "source": "l3"}]
        result = l2_agent.query_downstream(issues, context={})
        assert "my_issues" in result


class TestManagerWriteMethods:
    def test_apply_update_writes_data(self):
        mgr = _MockManager("l2")
        mgr.apply_update("confidence_boost", {"card_id": "abc", "delta": 0.1})
        assert mgr._store["confidence_boost"]["delta"] == 0.1

    def test_archive_after_reflect(self):
        mgr = _MockManager("l1")
        mgr.archive_reflect_result({"domain": "game/doudizhu", "fixes": 3})
        assert "domain" in mgr._store
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_reflection_agent.py -v`
Expected: FAIL (ReflectionAgent not defined yet)

- [ ] **Step 3: Add ReflectionAgent ABC and Manager write methods to base.py**

```python
# Add after existing LayerManager class in core/layers/base.py:

class ReflectionAgent:
    """Per-layer reflection agent. Investigates issues and fixes them.

    Receives flagged issues from the Reflect Coordinator.
    Determines if the issue belongs to this layer or a lower layer.
    If lower layer: QUERY downstream ReflectionAgent (recursive chain).
    If this layer: fix() through Manager.apply_update().
    """

    def __init__(self, layer_name: str, manager, downstream: ReflectionAgent | None = None):
        self._name = layer_name
        self._manager = manager
        self._downstream = downstream

    def investigate(self, issues: list[dict], context: dict) -> dict:
        """Judge issue attribution. Default: all issues are this layer's."""
        return {
            "my_issues": list(issues),
            "downstream_issues": [],
            "actions": [],
        }

    def fix(self, my_issues: list[dict]) -> dict:
        """Fix confirmed issues via Manager. Default: delegate to Manager."""
        for issue in my_issues:
            self._manager.apply_update("reflect_fix", issue)
        return {"fixes_applied": len(my_issues)}

    def query_downstream(self, issues: list[dict], context: dict) -> dict:
        """Send issues to the layer below for investigation."""
        if self._downstream:
            result = self._downstream.investigate(issues, context)
            downs = result.get("downstream_issues", [])
            if downs:
                result.update(self._downstream.fix(downs))
            return result
        return {"my_issues": issues, "downstream_issues": []}
```

Add to `LayerManager`:

```python
# Add these methods to the LayerManager class:

    def apply_update(self, key: str, value) -> None:
        """Write an update to this layer's data store. Called by ReflectionAgent.

        Override in subclasses for layer-specific persistence logic.
        """
        pass

    def archive_reflect_result(self, result: dict) -> None:
        """Post-reflect: clean up state after reflection cycle."""
        pass
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_reflection_agent.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add core/layers/base.py tests/test_reflection_agent.py
git commit -m "feat: add ReflectionAgent ABC and Manager write methods"
```

---

### Task 2.5: L3 ReflectionAgent + L3 Manager write methods

**Files:**
- Create: `core/layers/l3/reflection_agent.py`
- Modify: `core/layers/l3/manager.py`
- Modify: `tests/test_reflection_agent.py`

- [ ] **Step 1: Write L3-specific tests**

```python
# Append to tests/test_reflection_agent.py:

from pathlib import Path
from core.task import Domain


@pytest.fixture
def l3_skill_layer(tmp_path):
    from core.skill_layer import SkillLayer
    from core.tools.registry import ToolRegistry
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    return SkillLayer(skills_dir, ToolRegistry())


class TestL3ReflectionAgent:
    def test_skill_mismatch_identified_as_own(self, l3_skill_layer):
        from core.layers.l3.manager import L3Manager
        from core.layers.l3.reflection_agent import L3ReflectionAgent

        mgr = L3Manager(l3_skill_layer)
        agent = L3ReflectionAgent(mgr)

        issues = [{"type": "skill_mismatch", "detail": "matched wrong skill for domain X"}]
        result = agent.investigate(issues, context={})

        assert len(result["my_issues"]) == 1
        assert len(result["downstream_issues"]) == 0

    def test_not_skill_issue_defaults_to_self(self, l3_skill_layer):
        from core.layers.l3.manager import L3Manager
        from core.layers.l3.reflection_agent import L3ReflectionAgent

        mgr = L3Manager(l3_skill_layer)
        agent = L3ReflectionAgent(mgr)

        issues = [{"type": "unknown", "detail": "ambiguous signal"}]
        result = agent.investigate(issues, context={})

        assert len(result["my_issues"]) == 1

    def test_fix_writes_through_manager(self, l3_skill_layer, tmp_path):
        from core.layers.l3.manager import L3Manager
        from core.layers.l3.reflection_agent import L3ReflectionAgent

        mgr = L3Manager(l3_skill_layer)
        agent = L3ReflectionAgent(mgr)

        issues = [{"type": "skill_mismatch", "skill_name": "bad-skill"}]
        result = agent.fix(issues)

        assert result["fixes_applied"] == 1
        assert mgr._fixes == [{"type": "skill_mismatch", "skill_name": "bad-skill"}]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_reflection_agent.py::TestL3ReflectionAgent -v`
Expected: FAIL

- [ ] **Step 3: Implement L3ReflectionAgent**

```python
"""L3 ReflectionAgent — handles skill-level issues."""
from core.layers.base import ReflectionAgent


class L3ReflectionAgent(ReflectionAgent):
    def __init__(self, manager, downstream=None):
        super().__init__("l3", manager, downstream)

    def investigate(self, issues: list[dict], context: dict) -> dict:
        # L3 is the terminal layer — all issues attributed to itself
        return {"my_issues": list(issues), "downstream_issues": [], "actions": []}
```

- [ ] **Step 4: Add write tracking to L3Manager**

```python
# Add to L3Manager.__init__:
        self._fixes: list = []

# Add to L3Manager:
    def apply_update(self, key: str, value) -> None:
        if key == "reflect_fix":
            self._fixes.append(value)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_reflection_agent.py::TestL3ReflectionAgent -v`
Expected: all PASS

- [ ] **Step 6: Commit**

```bash
git add core/layers/l3/reflection_agent.py core/layers/l3/manager.py tests/test_reflection_agent.py
git commit -m "feat: add L3 ReflectionAgent with skill issue handling"
```

---

### Task 2.6: L2 ReflectionAgent + L2 Manager write methods

**Files:**
- Create: `core/layers/l2/reflection_agent.py`
- Modify: `core/layers/l2/manager.py`
- Modify: `tests/test_reflection_agent.py`

- [ ] **Step 1: Write L2 tests**

```python
# Append to tests/test_reflection_agent.py:

class TestL2ReflectionAgent:
    def test_activation_issue_is_own(self, l2_knowledge):
        from core.layers.l2.manager import L2Manager
        from core.layers.l2.reflection_agent import L2ReflectionAgent

        mgr = L2Manager(l2_knowledge)
        agent = L2ReflectionAgent(mgr)

        issues = [{"type": "low_activation", "card_id": "card_abc"}]
        result = agent.investigate(issues, context={})

        assert len(result["my_issues"]) >= 1

    def test_source_issue_delegates_downstream(self, l2_knowledge):
        from core.layers.l2.manager import L2Manager
        from core.layers.l2.reflection_agent import L2ReflectionAgent
        from core.layers.l3.reflection_agent import L3ReflectionAgent
        from core.layers.l3.manager import L3Manager
        from core.skill_layer import SkillLayer
        from core.tools.registry import ToolRegistry
        from pathlib import Path

        skills_dir = Path(".") / "tmp_skills_l2_test"
        skills_dir.mkdir(exist_ok=True)
        sl = SkillLayer(skills_dir, ToolRegistry())
        l3_mgr = L3Manager(sl)
        l3_agent = L3ReflectionAgent(l3_mgr)

        mgr = L2Manager(l2_knowledge)
        agent = L2ReflectionAgent(mgr, downstream=l3_agent)

        issues = [{"type": "skill_compilation_failure", "source": "l3"}]
        result = agent.investigate(issues, context={})

        assert len(result["downstream_issues"]) >= 1

    def test_fix_boosts_card_confidence(self, l2_knowledge):
        from core.layers.l2.manager import L2Manager
        from core.layers.l2.reflection_agent import L2ReflectionAgent
        from core.task import Domain

        domain = Domain("game/doudizhu", "specific")
        card = l2_knowledge.add_card("test card", domain, confidence=0.5)
        card_id = card.id

        mgr = L2Manager(l2_knowledge)
        agent = L2ReflectionAgent(mgr)

        issues = [{"type": "low_confidence", "card_id": card_id}]
        result = agent.fix(issues)

        assert result["fixes_applied"] == 1
```

- [ ] **Step 2: Implement L2ReflectionAgent**

```python
"""L2 ReflectionAgent — handles knowledge card-level issues."""
import logging
from core.layers.base import ReflectionAgent

logger = logging.getLogger(__name__)


class L2ReflectionAgent(ReflectionAgent):
    def __init__(self, manager, downstream=None):
        super().__init__("l2", manager, downstream)

    def investigate(self, issues: list[dict], context: dict) -> dict:
        my_issues = []
        downstream_issues = []

        for issue in issues:
            source = issue.get("source", "")
            itype = issue.get("type", "")

            if source in ("l3", "l0_5_1") or itype in ("skill_compilation_failure",):
                downstream_issues.append(issue)
            else:
                # Activation, confidence, decay issues → our problem
                my_issues.append(issue)

        return {
            "my_issues": my_issues,
            "downstream_issues": downstream_issues,
            "actions": [],
        }

    def fix(self, my_issues: list[dict]) -> dict:
        count = 0
        for issue in my_issues:
            card_id = issue.get("card_id")
            itype = issue.get("type", "")

            if card_id and itype == "low_confidence":
                self._manager.apply_update("boost_card", {"card_id": card_id})
                count += 1
            elif issue:
                self._manager.apply_update("reflect_fix", issue)
                count += 1

        return {"fixes_applied": count}
```

- [ ] **Step 3: Add write methods to L2Manager**

```python
# Add to L2Manager.__init__:
        self._fixes: list = []

# Add to L2Manager:
    def apply_update(self, key: str, value) -> None:
        if key == "boost_card":
            card_id = value.get("card_id")
            for card in self._knowledge.cards:
                if card.id == card_id:
                    card.boost()
        elif key == "reflect_fix":
            self._fixes.append(value)
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_reflection_agent.py::TestL2ReflectionAgent -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add core/layers/l2/reflection_agent.py core/layers/l2/manager.py tests/test_reflection_agent.py
git commit -m "feat: add L2 ReflectionAgent with card-level issue handling"
```

---

### Task 2.7: L(0.5+1) ReflectionAgent + Manager write methods

**Files:**
- Create: `core/layers/l0_5_1/reflection_agent.py`
- Modify: `core/layers/l0_5_1/manager.py`
- Modify: `tests/test_reflection_agent.py`

- [ ] **Step 1: Write L(0.5+1) tests**

```python
# Append to tests/test_reflection_agent.py:

class TestL0_5_1ReflectionAgent:
    def test_rule_issue_is_own(self, l0_5_meta, l1_philosophy):
        from core.layers.l0_5_1.manager import L0_5_1Manager
        from core.layers.l0_5_1.reflection_agent import L0_5_1ReflectionAgent

        mgr = L0_5_1Manager(l0_5_meta, l1_philosophy)
        agent = L0_5_1ReflectionAgent(mgr)

        issues = [{"type": "bad_rule", "rule_id": "r1", "content": "always fold"}]
        result = agent.investigate(issues, context={})

        assert len(result["my_issues"]) >= 1

    def test_card_issue_delegates_downstream(self, l0_5_meta, l1_philosophy, l2_knowledge):
        from core.layers.l0_5_1.manager import L0_5_1Manager
        from core.layers.l0_5_1.reflection_agent import L0_5_1ReflectionAgent
        from core.layers.l2.manager import L2Manager
        from core.layers.l2.reflection_agent import L2ReflectionAgent
        from core.layers.l3.reflection_agent import L3ReflectionAgent
        from core.layers.l3.manager import L3Manager
        from core.skill_layer import SkillLayer
        from core.tools.registry import ToolRegistry
        from pathlib import Path

        skills_dir = Path(".") / "tmp_skills_l1_test"
        skills_dir.mkdir(exist_ok=True)
        sl = SkillLayer(skills_dir, ToolRegistry())
        l3_mgr = L3Manager(sl)
        l3_agent = L3ReflectionAgent(l3_mgr)
        l2_mgr = L2Manager(l2_knowledge)
        l2_agent = L2ReflectionAgent(l2_mgr, downstream=l3_agent)

        mgr = L0_5_1Manager(l0_5_meta, l1_philosophy)
        agent = L0_5_1ReflectionAgent(mgr, downstream=l2_agent)

        issues = [{"type": "card_decay", "source": "l2", "card_id": "abc"}]
        result = agent.investigate(issues, context={})

        assert len(result["downstream_issues"]) >= 1

    def test_fix_proposes_rule_change(self, l0_5_meta, l1_philosophy):
        from core.layers.l0_5_1.manager import L0_5_1Manager
        from core.layers.l0_5_1.reflection_agent import L0_5_1ReflectionAgent

        mgr = L0_5_1Manager(l0_5_meta, l1_philosophy)
        agent = L0_5_1ReflectionAgent(mgr)

        issues = [{"type": "bad_rule", "rule_id": "r1", "content": "always fold", "new_content": "consider fold when weak"}]
        result = agent.fix(issues)

        assert result["fixes_applied"] >= 1
```

- [ ] **Step 2: Implement L0_5_1ReflectionAgent**

```python
"""L0.5+1 ReflectionAgent — handles rule-level issues and delegates downstream."""
import logging
from core.layers.base import ReflectionAgent

logger = logging.getLogger(__name__)


class L0_5_1ReflectionAgent(ReflectionAgent):
    def __init__(self, manager, downstream=None):
        super().__init__("l0_5_1", manager, downstream)

    def investigate(self, issues: list[dict], context: dict) -> dict:
        my_issues = []
        downstream_issues = []

        for issue in issues:
            itype = issue.get("type", "")
            source = issue.get("source", "")

            if source in ("l2", "l3"):
                downstream_issues.append(issue)
            elif itype in ("card_decay", "skill_mismatch", "skill_compilation_failure"):
                downstream_issues.append(issue)
            else:
                # Rule issues, safety violations, trigger problems → our problem
                my_issues.append(issue)

        return {
            "my_issues": my_issues,
            "downstream_issues": downstream_issues,
            "actions": [],
        }

    def fix(self, my_issues: list[dict]) -> dict:
        count = 0
        for issue in my_issues:
            itype = issue.get("type", "")

            if itype == "bad_rule":
                rule_id = issue.get("rule_id")
                new_content = issue.get("new_content")
                if rule_id and new_content:
                    self._manager.apply_update("modify_rule", {
                        "rule_id": rule_id,
                        "new_content": new_content,
                    })
                    count += 1
            else:
                self._manager.apply_update("reflect_fix", issue)
                count += 1

        return {"fixes_applied": count}
```

- [ ] **Step 3: Add write methods to L0_5_1Manager**

```python
# Add to L0_5_1Manager.__init__:
        self._fixes: list = []

# Add to L0_5_1Manager:
    def apply_update(self, key: str, value) -> None:
        if key == "modify_rule":
            rule_id = value.get("rule_id")
            new_content = value.get("new_content")
            try:
                self._philosophy.modify_rule(rule_id, new_content)
            except Exception:
                logger.warning("Failed to modify rule %s", rule_id)
        elif key == "reflect_fix":
            self._fixes.append(value)
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_reflection_agent.py::TestL0_5_1ReflectionAgent -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add core/layers/l0_5_1/reflection_agent.py core/layers/l0_5_1/manager.py tests/test_reflection_agent.py
git commit -m "feat: add L0.5+1 ReflectionAgent with rule modification handling"
```

---

### Task 2.8: ReflectCoordinator (Executor reflect mode)

**Files:**
- Create: `core/orchestrator/reflect_coordinator.py`
- Create: `tests/test_reflect_coordinator.py`

- [ ] **Step 1: Write tests**

```python
import pytest
import json
from pathlib import Path
from core.orchestrator.reflect_coordinator import ReflectCoordinator


@pytest.fixture
def pending_dir(tmp_path):
    d = tmp_path / "pending"
    d.mkdir()
    return d


@pytest.fixture
def learned_dir(tmp_path):
    d = tmp_path / "learned"
    d.mkdir()
    return d


def _write_pending(pending_dir, session_id, domain, notify_data):
    rec = {
        "session": {"id": session_id, "task_type": "game/doudizhu"},
        "observation": {"meta": {"domain": domain}, "state": {}},
        "notify_layers": notify_data,
        "action": [3, 3],
        "result": {},
    }
    (pending_dir / f"{session_id}.json").write_text(json.dumps(rec))


class MockLayerRoot:
    def __init__(self):
        self.queries = []
    def query(self, data):
        self.queries.append(data)
    def collect_notify(self):
        return {}


class TestReflectCoordinator:
    def test_audit_notify_flags_potential_issues(self, pending_dir):
        _write_pending(pending_dir, "s1", "game/doudizhu", {
            "l0_5_1": {"status": "ok"},
            "l2": {"status": "ok", "warning": "low card activation"},
            "l3": {"status": "ok"},
        })

        coord = ReflectCoordinator(pending_dir)
        issues = coord.audit("game/doudizhu")

        assert len(issues["l2"]) >= 1
        assert issues["l2"][0]["layer"] == "l2"

    def test_audit_returns_empty_for_clean_notify(self, pending_dir):
        _write_pending(pending_dir, "s1", "game/doudizhu", {
            "l0_5_1": {"status": "ok"},
            "l2": {"status": "ok"},
            "l3": {"status": "ok"},
        })

        coord = ReflectCoordinator(pending_dir)
        issues = coord.audit("game/doudizhu")

        assert all(len(v) == 0 for v in issues.values())

    def test_run_reflect_archives_files(self, pending_dir, learned_dir):
        _write_pending(pending_dir, "s1", "game/doudizhu", {
            "l0_5_1": {"status": "ok"},
            "l2": {"status": "ok"},
            "l3": {"status": "ok"},
        })

        coord = ReflectCoordinator(pending_dir, learned_dir=learned_dir)
        result = coord.run_reflect("game/doudizhu", layer_root=MockLayerRoot())

        assert len(result["archived"]) == 1
        assert not (pending_dir / "s1.json").exists()
        assert (learned_dir / "game" / "doudizhu" / "s1.json").exists()

    def test_run_reflect_creates_domain_subdir(self, pending_dir, learned_dir):
        _write_pending(pending_dir, "s2", "coding/python", {
            "l0_5_1": {"status": "ok"},
            "l2": {"status": "ok"},
            "l3": {"status": "ok"},
        })

        coord = ReflectCoordinator(pending_dir, learned_dir=learned_dir)
        coord.run_reflect("coding/python", layer_root=MockLayerRoot())

        assert (learned_dir / "coding" / "python").exists()
```

- [ ] **Step 2: Implement ReflectCoordinator**

```python
"""Reflect Coordinator — manages the global reflection cycle."""
import json
import logging
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)


class ReflectCoordinator:
    """Coordinates the global Reflect phase.

    Reuses Executor's pending/ directory. In reflect mode:
      1. Reads pending/ records for target domain
      2. Audits NOTIFY payloads for potential issues (lenient)
      3. Distributes flagged issues to layers via ReflectionAgent chain
      4. Archives processed files to learned/
    """

    def __init__(self, pending_dir: Path, learned_dir: Path | None = None):
        self._pending = pending_dir
        self._learned = learned_dir

    def audit(self, domain: str) -> dict[str, list[dict]]:
        """Review all NOTIFY payloads for the given domain.

        Returns: {layer_name: [flagged_issue, ...]}
        """
        flagged: dict[str, list[dict]] = {}

        for f in self._pending.glob("*.json"):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
            except Exception:
                continue

            obs = data.get("observation", {})
            meta = obs.get("meta", {})
            rec_domain = meta.get("domain", "")

            if rec_domain != domain and not rec_domain.startswith(domain + "/"):
                continue

            layers = data.get("notify_layers", {})
            for layer, payload in layers.items():
                if isinstance(payload, dict):
                    # Lenient audit: any non-"ok" status or warning/exceptions keys
                    if payload.get("status") != "ok" or "warning" in payload or "error" in payload:
                        flagged.setdefault(layer, []).append({
                            "layer": layer,
                            "type": "suspicious_notify",
                            "payload": payload,
                        })

        return flagged

    def run_reflect(self, domain: str, layer_root=None,
                    reflection_chain=None) -> dict:
        """Execute full reflect cycle for a domain.

        Args:
            domain: Target domain for reflection
            layer_root: LayerManager chain root (for Execute mode)
            reflection_chain: ReflectionAgent chain root (for Reflect mode)
        """
        issues_by_layer = self.audit(domain)

        # Distribute issues to ReflectionAgents
        fixes = {}
        if reflection_chain and any(issues_by_layer.values()):
            for layer, issues in issues_by_layer.items():
                if not issues:
                    continue
                # Walk reflection chain to find the matching ReflectionAgent
                current = reflection_chain
                while current:
                    if current._name == layer:
                        result = current.investigate(issues, context={"domain": domain})
                        if result.get("my_issues"):
                            fixes[layer] = current.fix(result["my_issues"])
                        downstream = result.get("downstream_issues", [])
                        if downstream:
                            fixes.setdefault(f"{layer}→downstream", current.query_downstream(downstream, context={}))
                        break
                    current = getattr(current, '_downstream', None)

        # Archive processed records
        archived = self._archive(domain)

        return {
            "domain": domain,
            "issues_found": {k: len(v) for k, v in issues_by_layer.items()},
            "fixes": fixes,
            "archived": archived,
        }

    def _archive(self, domain: str) -> list[str]:
        """Move processed pending/ files to learned/{domain}/."""
        moved = []
        for f in self._pending.glob("*.json"):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
            except Exception:
                continue

            obs = data.get("observation", {})
            meta = obs.get("meta", {})
            rec_domain = meta.get("domain", "")

            if rec_domain != domain and not rec_domain.startswith(domain + "/"):
                continue

            if self._learned:
                dest_dir = self._learned / domain.replace("/", "/")
                dest_dir.mkdir(parents=True, exist_ok=True)
                shutil.move(str(f), str(dest_dir / f.name))
            else:
                f.unlink()

            moved.append(f.name)

        return moved
```

- [ ] **Step 3: Run tests**

Run: `pytest tests/test_reflect_coordinator.py -v`
Expected: all PASS

- [ ] **Step 4: Commit**

```bash
git add core/orchestrator/reflect_coordinator.py tests/test_reflect_coordinator.py
git commit -m "feat: add ReflectCoordinator with audit and archive"
```

---

### Task 2.9: Comm agents (UpwardComm + DownwardComm)

**Files:**
- Modify: `core/layers/l3/upward_comm.py`, `core/layers/l3/downward_comm.py`
- Modify: `core/layers/l2/upward_comm.py`, `core/layers/l2/downward_comm.py`
- Modify: `core/layers/l0_5_1/upward_comm.py`, `core/layers/l0_5_1/downward_comm.py`
- Create: `tests/test_comm_agents.py`

- [ ] **Step 1: Write tests**

```python
import pytest
from datetime import datetime, timezone
from core.layer_message import LayerMessage, MessageType
from core.layers.l3.upward_comm import UpwardComm as L3UpwardComm


class TestUpwardComm:
    def test_send_response_creates_layer_message(self):
        comm = L3UpwardComm()
        msg = comm.send_response(source="l3", target="l2", payload={"status": "ok"}, trace_id="t1")
        assert msg.type == MessageType.RESPONSE
        assert msg.source == "l3"
        assert msg.target == "l2"
        assert msg.payload["status"] == "ok"

    def test_receive_returns_payload(self):
        comm = L3UpwardComm()
        msg = LayerMessage(
            source="l2", target="l3", type=MessageType.QUERY,
            payload={"query": "match skills"},
            trace_id="t1",
        )
        result = comm.receive(msg)
        assert result["query"] == "match skills"


class TestDownwardComm:
    def test_query_down_creates_message(self):
        from core.layers.l2.downward_comm import DownwardComm as L2DownwardComm
        comm = L2DownwardComm()
        msg = comm.query_down(target="l3", payload={"domain": "game/doudizhu"}, trace_id="t2")
        assert msg.type == MessageType.QUERY
        assert msg.target == "l3"

    def test_receive_returns_payload(self):
        from core.layers.l2.downward_comm import DownwardComm as L2DownwardComm
        comm = L2DownwardComm()
        msg = LayerMessage(
            source="l3", target="l2", type=MessageType.RESPONSE,
            payload={"skills": []},
            trace_id="t1",
        )
        result = comm.receive(msg)
        assert result["skills"] == []
```

- [ ] **Step 2: Implement Comm agents**

For `core/layers/l3/upward_comm.py`:

```python
"""L3 UpwardComm Agent — communication with L2."""
from core.layer_message import LayerMessage, MessageType


class UpwardComm:
    def receive(self, message: LayerMessage) -> dict:
        return message.payload

    def send_response(self, source: str, target: str, payload, trace_id: str) -> LayerMessage:
        return LayerMessage(
            source=source, target=target, type=MessageType.RESPONSE,
            payload=payload, trace_id=trace_id,
        )
```

For `core/layers/l3/downward_comm.py`:

```python
"""L3 DownwardComm Agent — communication with L4 (future)."""
from core.layer_message import LayerMessage, MessageType


class DownwardComm:
    def receive(self, message: LayerMessage) -> dict:
        return message.payload

    def query_down(self, target: str, payload, trace_id: str) -> LayerMessage:
        return LayerMessage(
            source="l3", target=target, type=MessageType.QUERY,
            payload=payload, trace_id=trace_id,
        )
```

Same pattern for L2 and L0.5+1 (just update class names and default `source`).

- [ ] **Step 3: Run tests**

Run: `pytest tests/test_comm_agents.py -v`
Expected: all PASS

- [ ] **Step 4: Commit**

```bash
git add core/layers/*/upward_comm.py core/layers/*/downward_comm.py tests/test_comm_agents.py
git commit -m "feat: implement Comm agents with LayerMessage protocol"
```

---

### Task 2.10: Tool allowed_layers

**Files:**
- Modify: `core/tools/registry.py`
- Create: `tests/test_tool_allowed_layers.py`

- [ ] **Step 1: Write tests**

```python
import pytest
from core.tools.registry import ToolRegistry


def dummy_handler(args, context=None):
    return "ok"


class TestToolAllowedLayers:
    def test_get_definitions_for_layer_filters_by_allowed(self):
        reg = ToolRegistry()
        reg.register("tool_a", {"name": "tool_a"}, dummy_handler, allowed_layers=["l3"])
        reg.register("tool_b", {"name": "tool_b"}, dummy_handler, allowed_layers=["l2", "executor"])

        l3_defs = reg.get_definitions_for_layer("l3")
        assert len(l3_defs) == 1
        assert l3_defs[0]["name"] == "tool_a"

        exec_defs = reg.get_definitions_for_layer("executor")
        assert len(exec_defs) == 1
        assert exec_defs[0]["name"] == "tool_b"

    def test_default_allowed_layers_is_l3(self):
        reg = ToolRegistry()
        reg.register("tool_x", {"name": "tool_x"}, dummy_handler)

        assert len(reg.get_definitions_for_layer("l3")) == 1
        assert len(reg.get_definitions_for_layer("l2")) == 0

    def test_multiple_layers_access(self):
        reg = ToolRegistry()
        reg.register("shared", {"name": "shared"}, dummy_handler, allowed_layers=["l3", "l2", "l0_5_1"])

        assert len(reg.get_definitions_for_layer("l3")) == 1
        assert len(reg.get_definitions_for_layer("l2")) == 1
        assert len(reg.get_definitions_for_layer("l0_5_1")) == 1
```

- [ ] **Step 2: Modify ToolRegistry**

```python
# In core/tools/registry.py:

# Modify ToolEntry to include allowed_layers:
@dataclass
class ToolEntry:
    name: str
    schema: dict
    handler: Callable
    allowed_layers: list[str] = field(default_factory=lambda: ["l3"])
    check_fn: Callable | None = None
    toolset: str = "core"

# Update register() signature:
def register(self, name: str, schema: dict, handler: Callable,
             allowed_layers: list[str] | None = None,
             check_fn: Callable | None = None, toolset: str = "core",
             override: bool = False) -> None:
    ...
    entry = ToolEntry(
        name=name, schema=schema, handler=handler,
        allowed_layers=allowed_layers or ["l3"],
        check_fn=check_fn, toolset=toolset,
    )

# Add new method:
def get_definitions_for_layer(self, layer_name: str) -> list[dict]:
    with self._lock:
        return [e.schema for e in self._entries.values()
                if layer_name in e.allowed_layers]
```

- [ ] **Step 3: Run all tests**

Run: `pytest tests/test_tool_allowed_layers.py tests/test_tool_registry.py -v`
Expected: all PASS (existing tool registry tests still pass)

- [ ] **Step 4: Commit**

```bash
git add core/tools/registry.py tests/test_tool_allowed_layers.py
git commit -m "feat: add allowed_layers to ToolRegistry for per-layer tool access"
```

---

### Task 2.11: Full integration test + verify no regressions

- [ ] **Step 1: Run complete test suite**

```bash
pytest tests/ -v --tb=short
```
Expected: ALL pass (existing Phase 1 + new Phase 2)

- [ ] **Step 2: Run dry-run with cognitive mode**

```bash
python scripts/run_douzero_llm.py --dry_run --episodes 3 --mode cognitive
```
Expected: no errors

- [ ] **Step 3: Commit**

```bash
git add -A
git commit -m "test: final Phase 2 integration verification"
```
