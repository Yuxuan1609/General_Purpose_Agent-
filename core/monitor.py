# core/monitor.py
"""Monitor — aggregates trace data sources for frontend display.

Pure query module — does NOT modify any state. All data sourced from:
- SessionStore (session/task metadata)
- per-layer log files (logs/interaction/{ts}/*.log)
- RoundTree.snapshot() (decision tree)
- TaskRunner.status() (running task stats)
- chain internals (L2/L3 capacity)
"""
from __future__ import annotations
from pathlib import Path
from typing import Any


def snapshot(session_id: str | None = None, chain=None,
             pending_dir: str = "data/learning/pending") -> dict:
    """Return full agent status snapshot as JSON-serializable dict."""
    return {
        "tasks": _task_list(session_id),
        "capacity": _capacity_snapshot(chain),
        "learning": _learning_snapshot(pending_dir),
        "sessions": _session_summary(),
    }


def task_list(session_id: str, parent_task_id: str | None = None) -> list[dict]:
    """List tasks for a session from SessionStore."""
    from core.session import get_session_store
    return get_session_store().list_tasks(session_id, parent_task_id)


def task_detail(task_id: str) -> dict | None:
    """Single task detail from SessionStore."""
    from core.session import get_session_store
    return get_session_store().get_task(task_id)


def log_tail(log_dir: str, layer: str, lines: int = 50) -> str:
    """Read tail of a per-layer log file.

    layer: "l0_5_1" | "l2" | "l3" | "executor"
    """
    path = Path(log_dir) / f"{layer}.log"
    if not path.exists():
        return ""
    try:
        with open(path, encoding="utf-8") as f:
            all_lines = f.readlines()
    except OSError:
        return ""
    return "".join(all_lines[-lines:])


def decision_tree(task_id: str | None = None) -> list:
    """Reuse RoundTree.snapshot() — thread-local decision tree."""
    from core.round_tree import get_round_history
    return get_round_history().snapshot()


# ── Internal helpers ──

def _task_list(session_id: str | None) -> list[dict]:
    if session_id is None:
        return []
    return task_list(session_id)


def _capacity_snapshot(chain) -> dict:
    """L2/L3 capacity vs limits."""
    from core.config_loader import get_section
    learn = get_section("learning", default={})
    l2_limit = learn.get("l2_card_limit", 30)
    l3_limit = learn.get("l3_skill_limit", 20)

    l2_count = 0
    l3_count = 0
    if chain:
        l2_mgr = getattr(chain, "_downstream", None)
        if l2_mgr and hasattr(l2_mgr, "_knowledge"):
            l2_count = len(l2_mgr._knowledge.cards)
        l3_mgr = getattr(l2_mgr, "_downstream", None) if l2_mgr else None
        if l3_mgr and hasattr(l3_mgr, "_skill_layer"):
            l3_count = len(l3_mgr._skill_layer.list_all())

    return {
        "l2": {"count": l2_count, "limit": l2_limit,
               "over": max(0, l2_count - l2_limit)},
        "l3": {"count": l3_count, "limit": l3_limit,
               "over": max(0, l3_count - l3_limit)},
    }


def _learning_snapshot(pending_dir: str) -> dict:
    p = Path(pending_dir)
    domains = {}
    if p.exists():
        for d in p.iterdir():
            if d.is_dir():
                files = list(d.glob("*.json"))
                domains[d.name] = {"pending": len(files)}
    archive_dir = Path("data/learning/archive")
    archive_count = sum(1 for _ in archive_dir.rglob("*.json")) if archive_dir.exists() else 0
    return {
        "domains": domains,
        "total_pending": sum(d["pending"] for d in domains.values()),
        "total_archive": archive_count,
    }


def _session_summary() -> dict:
    """Active session count + latest session info."""
    from core.session import get_session_store
    sessions = get_session_store().list_sessions(include_closed=False)
    return {
        "count": len(sessions),
        "latest": sessions[0] if sessions else None,
    }
