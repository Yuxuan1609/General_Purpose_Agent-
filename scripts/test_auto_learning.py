"""Auto-learning E2E test — record_learning → 5 files → auto-trigger → archive → dispatch.

Scenarios:
  1. process_in_memory — TaskObservation fields & format
  2. set/get_learning_context — roundtrip
  3. _build_and_save — <5 files → no trigger
  4. _build_and_save — ≥5 files → trigger + archive
  5. _dispatch_learning — full chain: archive → Executor → step
"""
from __future__ import annotations
import json
import shutil
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


TEST_DOMAIN = "tests_auto"
TMP_DIR: Path | None = None
_cleanup_callbacks: list = []


def _tmp() -> Path:
    global TMP_DIR
    if TMP_DIR is None:
        TMP_DIR = Path(tempfile.mkdtemp(prefix="alearn_"))
        _cleanup_callbacks.append(lambda: shutil.rmtree(TMP_DIR, ignore_errors=True))
    return TMP_DIR


def _cleanup():
    for cb in reversed(_cleanup_callbacks):
        try:
            cb()
        except Exception:
            pass


def _make_knowledge_stores(tmp_p: Path):
    from core.philosophy import Philosophy
    from core.flexible_knowledge import FlexibleKnowledge
    from core.skill_layer import SkillLayer

    phil = Philosophy(tmp_p / "l1_rules.json", max_rules=20)
    phil.add_rule("基于概率期望决策", created_by="seed", source="l1")
    phil.add_rule("持有强牌积极加注", created_by="seed", source="l1")

    fk_dir = tmp_p / "knowledge"
    fk_dir.mkdir()
    (fk_dir / "l2_index.json").write_text('{"version":1,"chapters":[],"relations":[]}')
    fk = FlexibleKnowledge(fk_dir, fk_dir / "l2_index.json")

    sl = SkillLayer(tmp_p / "skills")

    return phil, fk, sl


def _make_records(domain: str, count: int) -> list[dict]:
    records = []
    for i in range(count):
        records.append({
            "id": f"rec_{domain}_{i}",
            "domain": domain,
            "learning_target": f"学习目标 {i}: 测试自动化学习链路",
            "importance": "medium",
            "reasoning": f"第{i}轮测试中观察到新策略",
            "l1_observations": [],
            "l2_observations": [
                {
                    "finding": f"发现 {i}",
                    "evidence": f"L2第{i}轮结果摘要",
                    "implication": f"需要补充知识卡片 {i}",
                    "relevance": "high" if i % 2 == 0 else "medium",
                }
            ],
            "l3_observations": [
                {
                    "finding": f"技能发现 {i}",
                    "evidence": f"L3第{i}轮执行结果",
                    "implication": f"技能运行正常 {i}",
                    "relevance": "medium",
                }
            ],
            "source_rounds": [i + 1],
            "recorded_at": "2026-06-16T10:00:00+00:00",
        })
    return records


# ═══════════════════════════════════════════════════════════════════
# Scenario 1: process_in_memory — TaskObservation structure
# ═══════════════════════════════════════════════════════════════════

def test_process_in_memory_structure():
    """process_in_memory builds valid TaskObservation with all required fields."""
    from core.env.learning_env import LearningEnv

    tmp = _tmp()
    phil, fk, sl = _make_knowledge_stores(tmp)
    knowledge = {"l1": phil, "l2": fk, "l3": sl}

    lenv = LearningEnv(tmp / "pending", knowledge)
    records = _make_records("coding", 3)

    obs = lenv.process_in_memory(records, "coding")
    assert obs is not None, "TaskObservation should not be None"

    # Structure checks
    assert "任务1:" in obs.meta, "meta must contain task labels"
    assert "任务2:" in obs.meta
    assert "任务3:" in obs.meta
    assert "从 3 条记录中学习" in obs.meta
    assert json.dumps(records[0], ensure_ascii=False, indent=2) in obs.meta

    required_state = [
        "current", "history", "learning_units", "feedback",
        "l1_output_format", "l2_output_format", "l3_output_format",
        "l1_task", "l2_task", "l3_task",
        "l1_feedback", "l2_feedback", "l3_feedback",
    ]
    for key in required_state:
        assert key in obs.state, f"state missing key: {key}"

    assert obs.state["learning_units"] == records
    assert obs.state["l1_output_format"]["required"] == ["response"]
    assert obs.state["l2_output_format"]["required"] == ["response"]
    assert obs.state["l3_output_format"]["required"] == ["response"]

    assert obs.session["domain"] == "coding"
    assert obs.session["enable_learning"] is False

    print("  PASS: process_in_memory — 3 records → correct TaskObservation")


def test_process_in_memory_empty():
    """process_in_memory with empty records still returns valid TaskObservation."""
    from core.env.learning_env import LearningEnv

    tmp = _tmp()
    phil, fk, sl = _make_knowledge_stores(tmp)
    lenv = LearningEnv(tmp / "pending", {"l1": phil, "l2": fk, "l3": sl})

    obs = lenv.process_in_memory([], "empty_domain")
    assert obs is not None
    assert "从 0 条记录中学习" in obs.meta
    assert obs.session["domain"] == "empty_domain"

    print("  PASS: process_in_memory — empty records handled")


# ═══════════════════════════════════════════════════════════════════
# Scenario 2: set/get_learning_context roundtrip
# ═══════════════════════════════════════════════════════════════════

def test_learning_context_roundtrip():
    """ConsolidationContext stores and returns same references."""
    from core.tools.consolidation_tools import ConsolidationContext

    tmp = _tmp()
    phil, fk, sl = _make_knowledge_stores(tmp)
    mock_exec = MagicMock()

    ctx = ConsolidationContext(philosophy=phil, knowledge=fk, skill_layer=sl,
                               executor=mock_exec)

    assert ctx.executor is mock_exec
    assert ctx.philosophy is phil
    assert ctx.knowledge is fk
    assert ctx.skill_layer is sl

    print("  PASS: ConsolidationContext — roundtrip OK")


def test_learning_context_partial_update():
    """ConsolidationContext.executor can be set after construction."""
    tmp = _tmp()
    phil, fk, sl = _make_knowledge_stores(tmp)

    from core.tools.consolidation_tools import ConsolidationContext
    ctx = ConsolidationContext(philosophy=phil, knowledge=fk, skill_layer=sl)
    assert ctx.executor is None

    mock_exec = MagicMock()
    ctx.executor = mock_exec
    assert ctx.executor is mock_exec
    assert ctx.philosophy is phil, "knowledge_stores should persist"

    print("  PASS: ConsolidationContext — partial update preserves stores")


# ═══════════════════════════════════════════════════════════════════
# Scenario 3: _build_and_save — <5 files no trigger
# ═══════════════════════════════════════════════════════════════════

def test_build_and_save_below_threshold():
    """Writing <5 files does NOT trigger auto-learning."""
    from core.tools.record_learning_tool import _build_and_save

    tmp = _tmp()
    domain = f"{TEST_DOMAIN}_below"
    pending_dir = tmp / "pending" / domain
    pending_dir.mkdir(parents=True)

    import core.tools.record_learning_tool as rlt
    orig_path = rlt.Path

    def _fake_path(p):
        s = str(p)
        if s.startswith("data/learning/pending"):
            rel = s[len("data/learning/pending/"):]
            return tmp / "pending" / rel
        if s.startswith("data/learning/archive"):
            rel = s[len("data/learning/archive/"):]
            return tmp / "archive" / rel
        return orig_path(p)

    rlt.Path = _fake_path
    try:
        for i in range(4):
            _build_and_save(domain, f"target_{i}", "low", f"reason_{i}")

        archive_dir = tmp / "archive" / domain
        assert not archive_dir.exists() or len(list(archive_dir.glob("*.json"))) == 0, \
            f"No archive should exist for <5 files"

        assert len(list(pending_dir.glob("*.json"))) == 4, "All 4 files should remain in pending"
        print("  PASS: _build_and_save — 4 files, no trigger, no archive")
    finally:
        rlt.Path = orig_path


# ═══════════════════════════════════════════════════════════════════
# Scenario 4: _build_and_save — ≥5 files triggers + archives
# ═══════════════════════════════════════════════════════════════════

def test_build_and_save_triggers_auto_learning():
    """Writing ≥5 files triggers archive + dispatch."""
    from core.tools.record_learning_tool import _build_and_save
    from core.tools.consolidation_tools import ConsolidationContext

    tmp = _tmp()
    domain = f"{TEST_DOMAIN}_trigger"
    pending_dir = tmp / "pending" / domain
    pending_dir.mkdir(parents=True)

    # Wire mock Executor so dispatch can proceed
    phil, fk, sl = _make_knowledge_stores(tmp)
    mock_exec = MagicMock()
    mock_exec.execute.return_value = {
        "notify_layers": {
            "l0_5_1": {"l1_modifications": [], "result": "ok", "done": True},
            "l2": {"l2_modifications": [], "reply": "ok"},
            "l3": {"l3_modifications": [], "result": "ok"},
        }
    }
    ctx = ConsolidationContext(philosophy=phil, knowledge=fk, skill_layer=sl,
                                executor=mock_exec,
                                knowledge_stores={"l1": phil, "l2": fk, "l3": sl})
    import core.tools.record_learning_tool as rlt
    rlt._consol_ctx = ctx

    import core.tools.record_learning_tool as rlt
    orig_path = rlt.Path

    def _fake_path(p):
        s = str(p)
        if s.startswith("data/learning/pending"):
            rel = s[len("data/learning/pending/"):]
            return tmp / "pending" / rel
        if s.startswith("data/learning/archive"):
            rel = s[len("data/learning/archive/"):]
            return tmp / "archive" / rel
        return orig_path(p)

    rlt.Path = _fake_path
    try:
        for i in range(5):
            _build_and_save(domain, f"target_{i}", "low", f"reason_{i}")

        import time
        time.sleep(2)  # Allow async TaskRunner to process

        # After dispatch: pending should be empty, archive should have 5 files
        pending_files = list(pending_dir.glob("*.json"))
        archive_dir = tmp / "archive" / domain
        archive_files = list(archive_dir.glob("*.json")) if archive_dir.exists() else []

        assert len(pending_files) == 0, f"Expected 0 pending, got {len(pending_files)}"
        assert len(archive_files) == 5, f"Expected 5 archived, got {len(archive_files)}"
        assert mock_exec.execute.called, "Executor.execute should be called by dispatch"

        print("  PASS: _build_and_save — 5 files, archive + Executor.execute called")
    finally:
        rlt.Path = orig_path


# ═══════════════════════════════════════════════════════════════════
# Scenario 5: _dispatch_learning — full chain without executor
# ═══════════════════════════════════════════════════════════════════

def test_dispatch_learning_skips_without_executor():
    """_dispatch_learning skips when executor is None (graceful degradation)."""
    from core.tools.record_learning_tool import _dispatch_learning
    import core.tools.record_learning_tool as rlt

    tmp = _tmp()
    domain = f"{TEST_DOMAIN}_noexec"
    pending_dir = tmp / "pending" / domain
    pending_dir.mkdir(parents=True)

    # Create 5 files
    records = _make_records(domain, 5)
    json_files = []
    for i, rec in enumerate(records):
        fp = pending_dir / f"rec_{i}.json"
        fp.write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")
        json_files.append(fp)

    # Clear executor
    rlt._consol_ctx = None

    import core.tools.record_learning_tool as rlt
    orig_path = rlt.Path

    def _fake_path(p):
        s = str(p)
        if s.startswith("data/learning/pending"):
            rel = s[len("data/learning/pending/"):]
            return tmp / "pending" / rel
        if s.startswith("data/learning/archive"):
            rel = s[len("data/learning/archive/"):]
            return tmp / "archive" / rel
        return orig_path(p)

    rlt.Path = _fake_path
    try:
        _dispatch_learning(domain, pending_dir, json_files)

        # Files should be archived anyway (archive happens before executor check)
        archive_dir = tmp / "archive" / domain
        assert archive_dir.exists()
        assert len(list(archive_dir.glob("*.json"))) == 5

        assert len(list(pending_dir.glob("*.json"))) == 0
        print("  PASS: _dispatch_learning — no executor, skips learning, archives OK")
    finally:
        rlt.Path = orig_path


# ═══════════════════════════════════════════════════════════════════
# Scenario 6: ask_user timeout flag
# ═══════════════════════════════════════════════════════════════════

def test_ask_user_timeout_flag():
    """After _ask_user_timed_out is set, handler returns TIMEOUT_MSG."""
    from core.tools.kb_tools import _ask_user_handler, _reset_ask_user_state, _ask_user_console
    import core.tools.kb_tools as kt

    _reset_ask_user_state()

    # Simulate a timed-out state
    kt._ask_user_timed_out = True
    result = _ask_user_handler({"question": "test?"})
    data = json.loads(result)
    assert data["response"] == ""
    assert "TIMEOUT" in data["error"]
    assert "Do NOT call ask_user again" in data["error"]

    _reset_ask_user_state()
    kt._ask_user_timed_out = False

    print("  PASS: ask_user — timeout flag blocks subsequent calls")


# ═══════════════════════════════════════════════════════════════════
# Scenario 7: LLMClient thinking extra_body
# ═══════════════════════════════════════════════════════════════════

def test_llm_client_thinking_extra_body():
    """LLMClient.chat() injects extra_body when thinking_enabled."""
    from core.llm_client import LLMClient, LLMResponse
    from unittest.mock import MagicMock

    mock_oai = MagicMock()
    mock_resp = MagicMock()
    mock_resp.choices = [MagicMock()]
    mock_resp.choices[0].message.content = "test"
    mock_resp.choices[0].message.tool_calls = None
    mock_oai.chat.completions.create.return_value = mock_resp

    client = LLMClient(mock_oai, "test-model")
    client.thinking_enabled = True
    client.thinking_effort = "high"

    client.chat(messages=[{"role": "user", "content": "hi"}])

    call_kwargs = mock_oai.chat.completions.create.call_args[1]
    assert "extra_body" in call_kwargs
    assert call_kwargs["extra_body"]["thinking"]["type"] == "enabled"
    assert call_kwargs["extra_body"]["thinking"]["effort"] == "high"

    print("  PASS: LLMClient — thinking extra_body injected")


def test_llm_client_no_thinking():
    """LLMClient.chat() does NOT inject extra_body when thinking disabled."""
    from core.llm_client import LLMClient
    from unittest.mock import MagicMock

    mock_oai = MagicMock()
    mock_resp = MagicMock()
    mock_resp.choices = [MagicMock()]
    mock_resp.choices[0].message.content = "test"
    mock_resp.choices[0].message.tool_calls = None
    mock_oai.chat.completions.create.return_value = mock_resp

    client = LLMClient(mock_oai, "test-model")
    # thinking_enabled defaults to False, NOT set

    client.chat(messages=[{"role": "user", "content": "hi"}])

    call_kwargs = mock_oai.chat.completions.create.call_args[1]
    assert "extra_body" not in call_kwargs, "No extra_body when thinking disabled"

    print("  PASS: LLMClient — no extra_body without thinking")


# ═══════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════

def main():
    print("=== process_in_memory ===")
    test_process_in_memory_structure()
    test_process_in_memory_empty()

    print("\n=== ConsolidationContext ===")
    test_learning_context_roundtrip()
    test_learning_context_partial_update()

    print("\n=== auto-learning threshold ===")
    test_build_and_save_below_threshold()
    test_build_and_save_triggers_auto_learning()

    print("\n=== dispatch_learning edge cases ===")
    test_dispatch_learning_skips_without_executor()

    print("\n=== ask_user timeout ===")
    test_ask_user_timeout_flag()

    print("\n=== LLMClient thinking ===")
    test_llm_client_thinking_extra_body()
    test_llm_client_no_thinking()

    _cleanup()
    print("\nAll auto-learning E2E tests pass!")


if __name__ == "__main__":
    try:
        main()
    finally:
        _cleanup()
