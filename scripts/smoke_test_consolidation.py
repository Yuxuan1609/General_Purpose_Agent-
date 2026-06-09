"""Smoke test for LearningEnv consolidation monitoring.

Tests needs_consolidation() detection, get_consolidation_level() severity,
and build_consolidation_task() prompt construction (all rule-based, no LLM).
Logs to logs/smoke_test_consolidation/ timestamped directory.

Usage:
    python scripts/smoke_test_consolidation.py
"""
from __future__ import annotations
import json
import logging
import sys
import tempfile
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _setup_logging():
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_dir = PROJECT_ROOT / "logs" / "smoke_test_consolidation" / stamp
    log_dir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("smoke_consolidation")
    logger.setLevel(logging.DEBUG)

    fh = logging.FileHandler(log_dir / "test.log", encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter("%(asctime)s | %(levelname)-7s | %(message)s"))
    logger.addHandler(fh)
    return logger, log_dir


logger, LOG_DIR = _setup_logging()


# ═══════════════════════════════════════════════════════════════════════════
# Mock knowledge stores
# ═══════════════════════════════════════════════════════════════════════════

class MockL2Store:
    """Mock FlexibleKnowledge for consolidation testing."""
    def __init__(self, card_count: int = 10):
        self.cards = []
        for i in range(card_count):
            self.cards.append(MockKnowledgeCard(
                id=f"l2_card_{i:03d}",
                content=f"Strategy tip {i}: always raise with King pre-flop variant {i}",
                confidence=0.5 + i * 0.01,
                domain=MockDomain("game/leduc"),
            ))


class MockL3Store:
    """Mock SkillLayer for consolidation testing."""
    def __init__(self, skill_count: int = 5):
        self._skills = []
        for i in range(skill_count):
            self._skills.append(MockSkillMeta(
                name=f"leduc-skill-{i:02d}",
                description=f"Leduc strategy skill variant {i}",
                domain=MockDomain("game/leduc"),
            ))

    def list_all(self):
        return self._skills


class MockKnowledgeCard:
    def __init__(self, id, content, confidence, domain):
        self.id = id
        self.content = content
        self.content[:20] = confidence
        self.domain = domain
        self.activation = confidence


class MockSkillMeta:
    def __init__(self, name, description, domain):
        self.name = name
        self.description = description
        self.domain = domain


class MockDomain:
    def __init__(self, path):
        self.path = path


# ═══════════════════════════════════════════════════════════════════════════
# Tests
# ═══════════════════════════════════════════════════════════════════════════

def _make_lenv(l2_count=10, l3_count=5, l2_limit=30, l3_limit=20):
    from core.env.learning_env import LearningEnv
    tmpdir = Path(tempfile.mkdtemp())
    l2 = MockL2Store(card_count=l2_count) if l2_count > 0 else None
    l3 = MockL3Store(skill_count=l3_count) if l3_count > 0 else None
    knowledge = {}
    if l2: knowledge["l2"] = l2
    if l3: knowledge["l3"] = l3
    return LearningEnv(tmpdir, knowledge, dry_run=True,
                       l2_card_limit=l2_limit, l3_skill_limit=l3_limit)


def test_no_consolidation_needed():
    """Under limits: consolidation NOT triggered."""
    logger.info("─── 1. No consolidation needed (under limit) ───")
    lenv = _make_lenv(l2_count=10, l3_count=5)
    assert not lenv.needs_consolidation()
    assert lenv.get_consolidation_level() == 0
    task = lenv.build_consolidation_task()
    assert task is None, "should not build task when under limit"
    logger.info("  L2=10/30, L3=5/20 -> no trigger")
    logger.info("  PASS")


def test_l2_over_limit():
    """L2 exceeds limit: consolidation triggered."""
    logger.info("─── 2. L2 over limit ───")
    lenv = _make_lenv(l2_count=35, l3_count=5)
    assert lenv.needs_consolidation()
    level = lenv.get_consolidation_level()
    logger.info("  L2=35/30 (5 over) -> level=%d", level)
    assert level == 1, f"expected level 1 (mild), got {level}"
    task = lenv.build_consolidation_task()
    assert task is not None
    logger.info("  TaskObservation built: meta=%d chars", len(task.meta))
    logger.debug("  Meta preview:\n%s", task.meta[:500])
    assert "Knowledge Consolidation Task" in task.meta
    assert "L2 Knowledge Cards" in task.meta
    assert task.session["domain"] == "learning/compile"
    logger.info("  PASS")


def test_l3_over_limit():
    """L3 exceeds limit: consolidation triggered."""
    logger.info("─── 3. L3 over limit ───")
    lenv = _make_lenv(l2_count=10, l3_count=25)
    assert lenv.needs_consolidation()
    level = lenv.get_consolidation_level()
    logger.info("  L3=25/20 (5 over) -> level=%d", level)
    assert level == 1
    task = lenv.build_consolidation_task()
    assert "L3 Skills" in task.meta
    logger.info("  PASS")


def test_deep_over_limit():
    """Massive overflow: consolidation level 2."""
    logger.info("─── 4. Deep consolidation (level 2) ───")
    lenv = _make_lenv(l2_count=45, l3_count=30)
    assert lenv.needs_consolidation()
    level = lenv.get_consolidation_level()
    logger.info("  L2=45/30 (15 over), L3=30/20 (10 over) -> level=%d", level)
    assert level == 2, f"expected level 2 (deep), got {level}"
    task = lenv.build_consolidation_task()
    assert "L2 Knowledge Cards" in task.meta
    assert "L3 Skills" in task.meta
    logger.info("  PASS")


def test_custom_limits():
    """Custom limits respected."""
    logger.info("─── 5. Custom limits ───")
    lenv = _make_lenv(l2_count=12, l3_count=5, l2_limit=10, l3_limit=20)
    assert lenv.needs_consolidation()
    logger.info("  L2=12/10 (custom limit) -> triggered")
    logger.info("  PASS")


def test_consolidation_task_structure():
    """Verify consolidation task has correct structure for Agent consumption."""
    logger.info("─── 6. Consolidation task structure ───")
    lenv = _make_lenv(l2_count=35, l3_count=22)
    task = lenv.build_consolidation_task()
    assert task is not None

    # Log the full task for inspection
    logger.info("  Meta length: %d chars", len(task.meta))
    logger.info("  Session: %s", json.dumps(task.session, ensure_ascii=False))
    logger.info("  State keys: %s", list(task.state.keys()))
    logger.debug("  Full meta:\n%s", task.meta)

    # Verify required sections
    meta = task.meta
    checks = [
        ("header", "Knowledge Consolidation Task" in meta),
        ("L2 Section", "L2 Knowledge Cards" in meta),
        ("L3 Section", "L3 Skills" in meta),
        ("task spec", "consolidation task spec" in meta.lower()),
        ("keep/merge", "keep/merge/delete" in meta.lower()),
        ("usage stats", "usage stats" in meta.lower()),
        ("domain", task.session["domain"] == "learning/compile"),
        ("domains_hint", "learning/compile" in task.session.get("domains_hint", [])),
        ("enable_learning", not task.session.get("enable_learning", True)),
        ("state.current", "current" in task.state),
    ]
    all_ok = True
    for label, ok in checks:
        status = "OK" if ok else "FAIL"
        if not ok:
            logger.warning("    [%s] %s", status, label)
            all_ok = False
        else:
            logger.info("    [%s] %s", status, label)
    if not all_ok:
        # Debug: search for closest match
        lower_meta = meta.lower()
        for term in ["consolidation task", "consolidation", "task spec"]:
            idx = lower_meta.find(term)
            logger.debug("    search '%s': index=%d", term, idx)
        logger.debug("    meta tail (last 300): %s", repr(meta[-300:]))
    assert all_ok, f"Consolidation task structure: {sum(1 for _, ok in checks if ok)}/{len(checks)} checks passed"
    logger.info("  PASS")


def test_consolidation_task_only_l2():
    """When only L2 exceeds, task only lists L2 items."""
    logger.info("─── 7. L2-only consolidation task ───")
    lenv = _make_lenv(l2_count=35, l3_count=5)
    task = lenv.build_consolidation_task()
    assert "L2 Knowledge Cards" in task.meta
    assert "L3 Skills" not in task.meta  # L3 under limit -> not included
    logger.info("  L3 section absent (under limit)")
    logger.info("  PASS")


def test_consolidation_only_l3():
    """When only L3 exceeds, task only lists L3 items."""
    logger.info("─── 8. L3-only consolidation task ───")
    lenv = _make_lenv(l2_count=5, l3_count=25)
    task = lenv.build_consolidation_task()
    assert "L3 Skills" in task.meta
    assert "L2 Knowledge Cards" not in task.meta
    logger.info("  L2 section absent (under limit)")
    logger.info("  PASS")


# ═══════════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════════

def main():
    logger.info("=" * 55)
    logger.info("  LearningEnv Consolidation Smoke Test")
    logger.info("=" * 55)
    logger.info("Log dir: %s", LOG_DIR)

    tests = [
        test_no_consolidation_needed,
        test_l2_over_limit,
        test_l3_over_limit,
        test_deep_over_limit,
        test_custom_limits,
        test_consolidation_task_structure,
        test_consolidation_task_only_l2,
        test_consolidation_only_l3,
    ]

    passed = 0
    for test_fn in tests:
        try:
            test_fn()
            passed += 1
        except Exception as e:
            logger.error("  FAIL: %s", e)
            logger.debug("Traceback:", exc_info=True)

    logger.info("=" * 55)
    logger.info("  Results: %d/%d passed", passed, len(tests))
    logger.info("  Log: %s", LOG_DIR / "test.log")
    logger.info("=" * 55)
    return 0 if passed == len(tests) else 1


if __name__ == "__main__":
    sys.exit(main())
