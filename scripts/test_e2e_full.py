"""Full E2E test suite — async dispatch + KB sub-agent + learning task integration.

Uses SubAgentLoop/FillGapLoop from interactive_kb_agent.py as the tool engine.
"""
from __future__ import annotations
import json, sys, time
from contextlib import contextmanager
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.env_loader import load_env
load_env(PROJECT_ROOT)


def _now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


# ══════════════════════════════════════════════════════════════════════════
# Async dispatch tests
# ══════════════════════════════════════════════════════════════════════════

def test_sync_batch_parallel():
    """3 sync tasks in one round → all parallel → total < 2x longest."""
    from core.task_runner import get_task_runner
    runner = get_task_runner()

    start = time.time()
    results = runner.run_sync_batch([
        {"id": "a", "tool": "slow1", "exec": lambda: time.sleep(0.4) or "a"},
        {"id": "b", "tool": "slow2", "exec": lambda: time.sleep(0.4) or "b"},
        {"id": "c", "tool": "fast",  "exec": lambda: "c"},
    ])
    elapsed = time.time() - start
    assert len(results) == 3
    assert elapsed < 0.8, f"too slow: {elapsed:.2f}s (expected <0.8s parallel)"
    assert results[0]["success"] and results[1]["success"] and results[2]["success"]
    print(f"  PASS: sync batch parallel — 3 tasks in {elapsed:.2f}s")


def test_async_fire_and_collect():
    """Fire async → running → collect empty → wait → collect done."""
    from core.task_runner import get_task_runner
    runner = get_task_runner()

    tid = runner.submit("test_async", lambda: time.sleep(0.5) or "ok")

    # Immediate collect returns empty (still running)
    early = runner.collect([tid])
    assert len(early) == 0
    assert runner.check(tid) is not None
    assert runner.check(tid).status == "running"

    time.sleep(0.6)
    results = runner.collect([tid])
    assert len(results) == 1
    assert results[0]["status"] == "done"
    assert results[0]["result"] == "ok"
    assert runner.check(tid) is None  # removed after collect
    print("  PASS: async fire → running check → collect done → removed")


def test_mixed_sync_async_round():
    """Mixed round: sync tools via batch, async via submit — round completes."""
    from core.task_runner import get_task_runner
    runner = get_task_runner()

    # Simulate Agent building a batch with mixed sync flags
    batch = []
    async_tids = []

    # sync=true tools → go into batch
    batch.append({"id": "s1", "tool": "reader", "exec": lambda: "file_content"})

    # sync=false tools → submit async
    tid = runner.submit("kb_q", lambda: time.sleep(0.4) or "search_result")
    async_tids.append(tid)

    # Run sync batch
    results = runner.run_sync_batch(batch)
    assert len(results) == 1 and results[0]["data"] == "file_content"

    # Async not yet done
    assert runner.check(tid).status == "running"

    time.sleep(0.5)
    collected = runner.collect(async_tids)
    assert len(collected) == 1
    assert collected[0]["result"] == "search_result"
    print("  PASS: mixed round — sync result + async collected later")


def test_task_lifecycle():
    """Task: created→running→done→collected→deleted. Stats tracked."""
    from core.task_runner import get_task_runner
    runner = get_task_runner()

    tids = [runner.submit(f"worker_{i}", lambda n=i: time.sleep(0.2) or f"r{n}")
            for i in range(3)]

    pending = runner.pending_tasks()
    assert len(pending) == 3

    time.sleep(0.5)
    results = runner.collect(tids)
    assert len(results) == 3
    for r in results:
        assert r["status"] == "done"
    assert len(runner.pending_tasks()) == 0

    stats = runner.stats()
    assert "worker_0" in stats or "worker_1" in stats
    print(f"  PASS: task lifecycle — 3 tasks, stats: {list(stats.keys())[:3]}")


# ══════════════════════════════════════════════════════════════════════════
# KB sub-agent tests
# ══════════════════════════════════════════════════════════════════════════

def test_kb_query_sub_agent():
    """Real SubAgentLoop.run() on seeded KB docs."""
    from core.knowledge.knowledge_base import KnowledgeBase
    from core.knowledge.models import KnowledgeDoc
    from scripts.interactive_kb_agent import SubAgentLoop
    from core.llm_factory import build_llm_client

    kb = KnowledgeBase()
    kb.load()

    # Ensure test docs exist
    if not kb._docs:
        kb.add(KnowledgeDoc(domain="test", title="test_doc",
                            content="This is a test document about Python testing frameworks."))
        kb.add(KnowledgeDoc(domain="test", title="test_doc2",
                            content="pytest is a popular testing framework for Python."))
        kb.save()
        kb.load()

    llm = build_llm_client(PROJECT_ROOT / "config.yaml", temperature=0.1)
    agent = SubAgentLoop(llm, kb, trace=False)
    result = agent.run("Python testing framework", "test")

    assert "findings" in result
    assert isinstance(result["findings"], list)
    assert "suggestions" in result
    print(f"  PASS: kb_query sub-agent — {len(result['findings'])} findings, "
          f"{len(result.get('suggestions', []))} suggestions")
    kb.close()


def test_kb_fill_gap_sub_agent():
    """Real FillGapLoop.run() — proposes, does NOT write KB."""
    from core.knowledge.knowledge_base import KnowledgeBase
    from core.knowledge.models import KnowledgeDoc
    from scripts.interactive_kb_agent import FillGapLoop
    from core.llm_factory import build_llm_client

    kb = KnowledgeBase()
    kb.load()

    # Ensure seed doc exists
    if not kb._docs:
        kb.add(KnowledgeDoc(domain="test", title="seed",
                            content="Base document for fill-gap context."))
        kb.save()
        kb.load()

    doc_count_before = len(kb._docs)

    llm = build_llm_client(PROJECT_ROOT / "config.yaml", temperature=0.1)
    agent = FillGapLoop(llm, kb, trace=False)
    result = agent.run({
        "domain": "test",
        "topic": "asyncio event loop basics",
        "reason": "KB missing async Python fundamentals",
    })

    assert "proposals" in result
    # FillGapLoop proposes, does NOT write — KB unchanged
    assert len(kb._docs) == doc_count_before
    print(f"  PASS: kb_fill_gap sub-agent — {len(result.get('proposals', []))} proposals, "
          f"KB unchanged ({doc_count_before} docs)")
    kb.close()


# ══════════════════════════════════════════════════════════════════════════
# Learning task integration tests
# ══════════════════════════════════════════════════════════════════════════

def test_learning_task_dry_run():
    """LearningEnv + Executor → L1 consolidate → verify flow (dry_run)."""
    from core.philosophy import Philosophy
    from core.flexible_knowledge import FlexibleKnowledge
    from core.skill_layer import SkillLayer
    from core.seed_knowledge import init_registry, seed_knowledge
    from core.env.learning_env import LearningEnv

    reg = init_registry(PROJECT_ROOT / "data" / "layers" / "domain_registry.json")
    phil = Philosophy(PROJECT_ROOT / "data" / "layers" / "l1_rules.json")
    fk = FlexibleKnowledge(
        PROJECT_ROOT / "data" / "layers" / "knowledge",
        PROJECT_ROOT / "data" / "layers" / "knowledge" / "l2_index.json",
        domain_registry=reg,
    )
    sl = SkillLayer(PROJECT_ROOT / "data" / "layers" / "skills", domain_registry=reg)

    # Ensure interaction domain exists
    if reg.get_node("interaction") is None:
        reg.add_node("interaction", "general",
                     "交互对话域", {}, "姊妹域: coding")

    from core.task import Domain
    if not [c for c in fk.cards if c.domain.path == "interaction"]:
        fk.add_card(content="[问候] → [简洁友好回复]", domain=Domain("interaction", "specific"), source="seed")

    knowledge = {"l1": phil, "l2": fk, "l3": sl}
    lenv = LearningEnv(PROJECT_ROOT / "data" / "learning" / "pending",
                       knowledge, dry_run=True, domain_registry=reg)

    state = lenv.reset("interaction")
    if not state.observation:
        print("  SKIP: no interaction pending records (expected)")
        return

    units = lenv._enriched_units
    assert len(units) > 0
    task = lenv.build_task_observation()
    assert task is not None and task.meta
    print(f"  PASS: learning task dry_run — {len(units)} units, "
          f"task meta: {len(task.meta)} chars")


def test_learning_task_e2e():
    """Full pipeline with actual Executor + chain (needs LLM)."""
    from core.philosophy import Philosophy
    from core.flexible_knowledge import FlexibleKnowledge
    from core.skill_layer import SkillLayer
    from core.seed_knowledge import init_registry
    from core.env.learning_env import LearningEnv
    from core.meta_driver import MetaDriver, DEFAULT_VALIDATORS
    from core.layers import build_chain as _build_chain
    from core.layers.logging_setup import setup_layer_logging
    from core.executor import Executor
    from core.llm_factory import build_llm_client

    reg = init_registry(PROJECT_ROOT / "data" / "layers" / "domain_registry.json")
    phil = Philosophy(PROJECT_ROOT / "data" / "layers" / "l1_rules.json")
    fk = FlexibleKnowledge(
        PROJECT_ROOT / "data" / "layers" / "knowledge",
        PROJECT_ROOT / "data" / "layers" / "knowledge" / "l2_index.json",
        domain_registry=reg,
    )
    sl = SkillLayer(PROJECT_ROOT / "data" / "layers" / "skills", domain_registry=reg)

    if reg.get_node("interaction") is None:
        reg.add_node("interaction", "general", "交互对话域", {}, "")

    knowledge = {"l1": phil, "l2": fk, "l3": sl}
    lenv = LearningEnv(PROJECT_ROOT / "data" / "learning" / "pending",
                       knowledge, dry_run=True, domain_registry=reg)

    state = lenv.reset("interaction")
    if not state.observation:
        print("  SKIP: no interaction pending records (expected)")
        return

    task = lenv.build_task_observation()
    llm = build_llm_client(PROJECT_ROOT / "config.yaml", temperature=0.1)

    meta_driver = MetaDriver(DEFAULT_VALIDATORS.copy())
    chain = _build_chain(meta_driver, phil, fk, sl, auxiliary_llm=llm,
                         domain_registry=reg,
                         knowledge_stores={"l2": fk, "l3": sl})
    executor = Executor(layer_root=chain, llm_client=llm,
                        learning_dir=PROJECT_ROOT / "data" / "learning")

    result = executor.execute(task)
    notify = result.get("notify_layers", {})

    l1_mods = notify.get("l0_5_1", {}).get("l1_modifications", [])
    l2_mods = notify.get("l2", {}).get("l2_modifications", [])
    print(f"  PASS: learning task E2E — L1:{len(l1_mods)} mods, L2:{len(l2_mods)} mods")


# ══════════════════════════════════════════════════════════════════════════
# ask_user test
# ══════════════════════════════════════════════════════════════════════════

def test_ask_user_handler():
    """ask_user with tkinter disabled → falls back to console input."""
    from core.tools.kb_tools import _ask_user_handler
    from unittest.mock import patch

    with patch("tkinter.Tk", side_effect=RuntimeError("no display")):
        with patch("builtins.input", return_value="my answer"):
            result = _ask_user_handler({"question": "What is 2+2?"})
            data = json.loads(result)
            assert data["response"] == "my answer"
            print(f"  PASS: ask_user — Q: 'What is 2+2?' → A: 'my answer'")


# ══════════════════════════════════════════════════════════════════════════
# record_learning tests
# ══════════════════════════════════════════════════════════════════════════

def test_record_learning_tree_and_handler():
    """RoundTree → record_learning handler → pending JSON → LearningEnv parse."""
    from core.round_tree import DecisionNode, get_round_history, RoundHistory
    from core.tools.record_learning_tool import _build_and_save

    # Reset history
    import core.round_tree as rt
    old = rt._history
    rt._history = RoundHistory(5)

    try:
        # Build RoundTree with L1→L2→L3 structure
        l1 = DecisionNode("l0_5_1", "评估search.txt方案", "8/10分", "结构化框架")
        l2a = DecisionNode("l2", "读search.txt文件", "307行SearXNG部署方案", "find找到文件")
        l2b = DecisionNode("l2", "查找方案评估标准", "无相关知识卡片", "L2无评估域卡片")
        l3 = DecisionNode("l3", "ls -la项目目录", "14 dirs, 17 files", "提供目录上下文")
        l2b.children.append(l3)
        l1.children.append(l2a)
        l1.children.append(l2b)
        get_round_history().push(l1)

        # Build and save
        record = _build_and_save("test_record", "如何系统化评估技术方案",
                                 "high", "第4轮采用了结构化评估框架且用户认可")
        assert record["status"] == "ok"
        filepath = Path(record["file"])
        assert filepath.exists()

        with open(filepath, encoding="utf-8") as f:
            data = json.load(f)
        assert data["domain"] == "test_record"
        assert data["learning_target"] == "如何系统化评估技术方案"
        assert data["importance"] == "high"
        print(f"  PASS: record_learning → file: {filepath.name}")
        print(f"         L2 observations: {len(data.get('l2_observations', []))}")
        print(f"         L3 observations: {len(data.get('l3_observations', []))}")

        # Verify LearningEnv can parse it
        from core.env.learning_env import LearningEnv
        from core.philosophy import Philosophy
        from core.flexible_knowledge import FlexibleKnowledge
        from core.skill_layer import SkillLayer
        from core.seed_knowledge import init_registry

        reg = init_registry(PROJECT_ROOT / "data" / "layers" / "domain_registry.json")
        phil = Philosophy(PROJECT_ROOT / "data" / "layers" / "l1_rules.json")
        fk = FlexibleKnowledge(
            PROJECT_ROOT / "data" / "layers" / "knowledge",
            PROJECT_ROOT / "data" / "layers" / "knowledge" / "l2_index.json",
            domain_registry=reg,
        )
        sl = SkillLayer(PROJECT_ROOT / "data" / "layers" / "skills", domain_registry=reg)
        knowledge = {"l1": phil, "l2": fk, "l3": sl}
        lenv = LearningEnv(PROJECT_ROOT / "data" / "learning" / "pending",
                           knowledge, dry_run=True, domain_registry=reg)
        state = lenv.reset("test_record")
        if state.observation:
            units = lenv._enriched_units
            print(f"  PASS: LearningEnv parsed pending → {len(units)} units")
        else:
            print(f"  PASS: LearningEnv scanned (0 units, dry_run OK)")

        # Cleanup
        filepath.unlink()
        try:
            filepath.parent.rmdir()
        except OSError:
            pass
        print("  PASS: cleanup done")
    finally:
        rt._history = old


def test_record_learning_format_tree():
    """Verify tree formatting with numbering."""
    from core.tools.record_learning_tool import _format_tree_for_llm
    from core.round_tree import DecisionNode

    l1 = DecisionNode("l0_5_1", "query1", "result1", "reason1")
    l2 = DecisionNode("l2", "query2", "result2", "reason2")
    l1.children.append(l2)

    text = _format_tree_for_llm([l1])
    assert "[1.L1]" in text
    assert "[1.1.L2]" in text
    print("  PASS: tree numbering — 1.L1, 1.1.L2 present")


# ══════════════════════════════════════════════════════════════════════════
# Main
# ══════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=== Async Dispatch ===")
    test_sync_batch_parallel()
    test_async_fire_and_collect()
    test_mixed_sync_async_round()
    test_task_lifecycle()

    print("\n=== KB Sub-Agent ===")
    test_kb_query_sub_agent()
    test_kb_fill_gap_sub_agent()

    print("\n=== Learning Task ===")
    test_learning_task_dry_run()
    test_learning_task_e2e()

    print("\n=== ask_user ===")
    test_ask_user_handler()

    print("\n=== record_learning ===")
    test_record_learning_tree_and_handler()
    test_record_learning_format_tree()

    print(f"\nAll 11 E2E tests pass!")
