"""E2E test: record_learning → auto-learning → consolidation, with real LLM.

Verifies the full pipeline:
  1. Simulate 5+ record_learning JSON files in pending/
  2. _dispatch_learning archives them, runs learning pass via Executor
  3. If stores overflow, consolidation pass triggers
  4. Tracks new L1/L2/L3 items for cleanup

Usage:
    python scripts/test_learning_e2e.py          # run all scenarios
    python scripts/test_learning_e2e.py --dry     # dry-run (no LLM, just structure)
"""
from __future__ import annotations
import json
import shutil
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from contextlib import contextmanager

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.env_loader import load_env
load_env(PROJECT_ROOT)

_TMP: Path | None = None
_CLEANUP: list = []
_TEST_ID = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
_LOG_DIR = PROJECT_ROOT / "logs" / "test_learning_e2e" / _TEST_ID
_NEW_ITEMS: dict[str, list[str]] = {"l1": [], "l2": [], "l3": []}


# ═══════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _tmp() -> Path:
    global _TMP
    if _TMP is None:
        _TMP = Path(tempfile.mkdtemp(prefix="learn_e2e_"))
        _CLEANUP.append(lambda: shutil.rmtree(str(_TMP), ignore_errors=True))
    return _TMP


def _cleanup():
    for cb in reversed(_CLEANUP):
        try:
            cb()
        except Exception:
            pass


def _log(title: str, content: str = ""):
    _LOG_DIR.mkdir(parents=True, exist_ok=True)
    path = _LOG_DIR / "test.log"
    with open(path, "a", encoding="utf-8") as f:
        f.write(f"\n{'=' * 60}\n  {title}\n{'=' * 60}\n\n")
        if content:
            f.write(content)
            f.write("\n")


# ═══════════════════════════════════════════════════════════════════════════
# Fixture: build stores with seed data (over limit to trigger consolidation)
# ═══════════════════════════════════════════════════════════════════════════

def _build_seed_stores(root: Path) -> tuple:
    """Build Philosophy + FlexibleKnowledge + SkillLayer with enough data
    to trigger consolidation: L2 > 25 cards, L3 > 15 skills."""
    from core.philosophy import Philosophy
    from core.flexible_knowledge import FlexibleKnowledge
    from core.skill_layer import SkillLayer
    from core.task import Domain
    from core.domain_registry import DomainRegistry

    data = root / "data"
    data.mkdir(parents=True, exist_ok=True)

    # L1: seed rules
    l1_path = data / "l1_rules.json"
    phil = Philosophy(l1_path, max_rules=20, max_rule_length=300)
    for r in [
        "面对不确定信息时优先搜索验证",
        "当同一种方法连续3次失败时主动换策略",
        "代码修改前先用搜索确认改动范围",
        "工具调用后必须检查返回结果",
    ]:
        phil.add_rule(r, created_by="seed", source="l1")

    # L2: seed cards + overflow cards (> 25)
    fk_dir = root / "data" / "knowledge"
    fk_dir.mkdir(parents=True, exist_ok=True)
    (fk_dir / "l2_index.json").write_text(
        '{"version":1,"chapters":[],"relations":[]}')
    fk = FlexibleKnowledge(fk_dir, fk_dir / "l2_index.json")

    for i in range(30):
        fk.add_card(
            content=f"测试知识卡片 #{i}: 描述测试场景中观察到的策略模式",
            domain=Domain("tests_auto/e2e_learning", "specific"),
            source="seed",
        )

    # L3: seed skills + overflow skills (> 15)
    skills_dir = root / "data" / "skills"
    skills_dir.mkdir(parents=True, exist_ok=True)
    sl = SkillLayer(skills_dir, db_path=root / "data" / "l3.db")
    for i in range(20):
        sl.create_skill(
            name=f"test-skill-{i}",
            content=f"---\ndomain: tests_auto/e2e_learning\ndescription: 测试技能 #{i}\n---\n\n# 测试技能\n\n步骤:\n1. 步骤一\n2. 步骤二\n",
            domain=Domain("tests_auto/e2e_learning", "specific"),
            created_by="seed",
        )

    reg = DomainRegistry()
    reg.add_node("tests_auto/e2e_learning", "tests_auto",
                 "E2E test learning domain")

    return phil, fk, sl, reg


def _make_records(domain: str, count: int = 6) -> list[dict]:
    records = []
    for i in range(count):
        records.append({
            "id": f"e2e_rec_{i}",
            "domain": domain,
            "learning_target": f"学习目标 #{i}: 验证完整学习管线",
            "importance": "high" if i < 2 else "medium",
            "reasoning": f"第{i}轮学习验证中观察到知识点",
            "l1_observations": [
                {"finding": f"规则发现 {i}", "evidence": f"L1第{i}轮决策推理",
                 "implication": f"需要补充或修改规则", "relevance": "high"}
            ],
            "l2_observations": [
                {"finding": f"卡片发现 {i}",
                 "evidence": f"L2第{i}轮结果: 匹配到卡片 card_{i%30}",
                 "implication": f"卡片需要更新或新建", "relevance": "high"}
            ],
            "l3_observations": [
                {"finding": f"技能发现 {i}",
                 "evidence": f"L3第{i}轮执行: test-skill-{i%20}",
                 "implication": f"技能可优化", "relevance": "medium"}
            ],
            "source_rounds": [i + 1],
            "recorded_at": _now(),
        })
    return records


def _snapshot_items(phil, fk, sl) -> dict[str, set]:
    """Capture current item IDs for later diff."""
    return {
        "l1": {r.id for r in phil.all_rules()},
        "l2": {c.id for c in fk.cards},
        "l3": {s.name for s in sl.list_all()},
    }


def _diff_items(before: dict, after: dict) -> dict:
    """Return newly created item IDs."""
    return {
        layer: sorted(after[layer] - before[layer])
        for layer in ("l1", "l2", "l3")
    }


def _cleanup_new_items(phil, fk, sl, items: dict):
    """Remove items created during test."""
    for rid in items.get("l1", []):
        try:
            phil.remove_rule(rid)
        except ValueError:
            pass
    for cid in items.get("l2", []):
        fk.remove_card(cid)
    for sname in items.get("l3", []):
        try:
            sl.delete_skill(sname)
        except ValueError:
            pass


# ═══════════════════════════════════════════════════════════════════════════
# Main test
# ═══════════════════════════════════════════════════════════════════════════

def test_full_learning_pipeline(domain: str = "tests_auto/e2e_learning"):
    """E2E: write 6 records → dispatch_learning → learning + consolidation."""
    tmp = _tmp()
    test_root = tmp / "project"
    test_root.mkdir()

    # 1. Build seed stores with overflow data
    phil, fk, sl, reg = _build_seed_stores(test_root)
    _log("Stores built",
         f"L1 rules: {len(phil.all_rules())}\n"
         f"L2 cards: {len(fk.cards)}\n"
         f"L3 skills: {len(sl.list_all())}")

    # Snapshot pre-test state
    before = _snapshot_items(phil, fk, sl)

    # 2. Create pending records
    pending_dir = tmp / "data" / "learning" / "pending" / domain.replace("/", "_")
    pending_dir.mkdir(parents=True, exist_ok=True)
    records = _make_records(domain, 6)
    json_files = []
    for i, rec in enumerate(records):
        fp = pending_dir / f"e2e_rec_{i}.json"
        fp.write_text(json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")
        json_files.append(fp)
    _log("Pending records written",
         f"{len(json_files)} files in {pending_dir}")

    # 3. Log: pre-state summary
    cards_by_domain = {}
    for c in fk.cards:
        d = c.domain.path
        cards_by_domain[d] = cards_by_domain.get(d, 0) + 1
    skills_by_domain = {}
    for s in sl.list_all():
        d = s.domain.path
        skills_by_domain[d] = skills_by_domain.get(d, 0) + 1
    _log("Pre-test capacity",
         f"L2 domains: {json.dumps(cards_by_domain, indent=2)}\n"
         f"L3 domains: {json.dumps(skills_by_domain, indent=2)}")

    # 4. Build chain with real LLM using pre-built stores
    from core.layers import build_chain
    from core.layers.comm import UpwardComm, DownwardComm
    from core.llm_factory import build_llm_client
    from core.executor import Executor
    from core.runtime_registry import register_runtime
    from core.chain_factory import _mount_tools

    llm = build_llm_client(PROJECT_ROOT / "config.yaml")
    chain = build_chain(phil, fk, sl, auxiliary_llm=llm,
                        domain_registry=reg,
                        knowledge_stores={"l2": fk, "l3": sl})
    _mount_tools(chain, test_root)
    executor = Executor(
        layer_root=chain,
        llm_client=llm,
        learning_dir=test_root / "data" / "learning",
    )
    register_runtime(chain, executor)
    _log("Chain built", "Executor + L1→L2→L3 chain ready")

    # 5. Ensure paths resolve to temp dir
    (tmp / "data" / "learning" / "archive").mkdir(parents=True, exist_ok=True)

    import core.tools.record_learning_tool as rlt
    _orig_path = rlt.Path

    def _patch_path(p):
        s = str(p)
        if s.startswith("data/learning"):
            # Map "data/learning/..." to tmp/data/learning/...
            return tmp / s
        return _orig_path(p)

    rlt.Path = _patch_path

    try:
        # 6. Dispatch learning
        _log("Dispatching learning", f"{len(json_files)} records, domain={domain}")
        t0 = time.time()
        rlt._dispatch_learning(domain,
                               tmp / "data" / "learning" / "pending",
                               json_files)
        elapsed = time.time() - t0
        _log("Dispatch complete", f"Took {elapsed:.1f}s")

        # 7. Snapshot post-test state
        after = _snapshot_items(phil, fk, sl)
        new_items = _diff_items(before, after)

        _log("New items created",
             f"L1 rules: {len(new_items['l1'])} → {new_items['l1']}\n"
             f"L2 cards: {len(new_items['l2'])} → {new_items['l2'][:20]}\n"
             f"L3 skills: {len(new_items['l3'])} → {new_items['l3']}")

        # 8. Verify expectations
        print(f"\n{'=' * 60}")
        print(f"  E2E Learning Pipeline Results")
        print(f"{'=' * 60}")
        print(f"  Duration: {elapsed:.1f}s")
        print(f"  L1 new rules: {len(new_items['l1'])}")
        print(f"  L2 new cards: {len(new_items['l2'])}")
        print(f"  L3 new skills: {len(new_items['l3'])}")
        print(f"  Logs: {_LOG_DIR}")
        print(f"{'=' * 60}")

        # Persist new items for manual cleanup
        global _NEW_ITEMS
        _NEW_ITEMS = new_items
        marker = tmp / "e2e_new_items.json"
        marker.write_text(json.dumps(new_items, ensure_ascii=False, indent=2))
        print(f"  Cleanup marker: {marker}")
        print(f"  Run cleanup: del marker content → "
              f"_cleanup_new_items(phil, fk, sl, json.load(marker))")

        return new_items

    finally:
        rlt.Path = _orig_path


# ═══════════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry", action="store_true",
                        help="Dry-run: validate structure only, no LLM")
    args = parser.parse_args()

    if args.dry:
        print("Dry-run mode: checking structure only")
        tmp = _tmp()
        test_root = tmp / "project"
        test_root.mkdir()
        phil, fk, sl, reg = _build_seed_stores(test_root)
        records = _make_records("tests_auto/e2e_learning", 6)
        from core.env.learning_env import LearningEnv
        lenv = LearningEnv(tmp, {"l1": phil, "l2": fk, "l3": sl})
        obs = lenv.process_in_memory(records, "tests_auto/e2e_learning")
        assert obs is not None, "process_in_memory returned None"
        assert "learning" in obs.meta.lower()
        print(f"  PASS: process_in_memory → valid TaskObservation ({len(obs.meta)} chars meta)")
        consol = lenv.build_consolidation_task()
        assert consol is not None, "consolidation task returned None (stores under limit?)"
        assert "learning/compile" in consol.session.get("domain", "")
        print(f"  PASS: build_consolidation_task → valid ({len(consol.meta)} chars meta)")
        print("  Dry-run OK — all structures valid")
    else:
        result = test_full_learning_pipeline()
        print(f"\nDone. New items: {json.dumps(result, indent=2)}")
