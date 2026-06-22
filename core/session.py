# core/session.py
"""SessionStore — session + task 元数据持久化 (SQLite WAL) + thread-local task context.

Tracks:
- sessions: user-level workspaces (id, name, created_at, status, log_dir)
- tasks: per-session execution units (top-level + sub-agent)

Thread-local context (set_task_context/get_task_context/clear_task_context)
allows dispatch handlers to know which session/task they belong to without
explicit parameter passing.
"""
from __future__ import annotations
import logging
import sqlite3
import threading
import uuid
from datetime import datetime, timezone

logger = logging.getLogger(__name__)
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Thread-local task context ──
_context = threading.local()


def set_task_context(session_id: str, task_id: str) -> None:
    """Set current thread's session_id + task_id for dispatch tracking."""
    _context.session_id = session_id
    _context.task_id = task_id


def get_task_context() -> tuple[str | None, str | None]:
    """Return (session_id, task_id) of current thread, or (None, None)."""
    return getattr(_context, "session_id", None), getattr(_context, "task_id", None)


def clear_task_context() -> None:
    """Clear current thread's task context."""
    _context.session_id = None
    _context.task_id = None


def set_running_task_id(task_id: str) -> None:
    """Set the ID of the async task currently executing in this thread (for cancel polling)."""
    _context.running_task_id = task_id


def get_running_task_id() -> str | None:
    """Return the ID of the currently executing async task, or None."""
    return getattr(_context, 'running_task_id', None)


# ── SessionStore ──
class SessionStore:
    def __init__(self, db_path: Path | str = "data/cognitive/sessions.db"):
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.row_factory = sqlite3.Row
        self._write_lock = threading.Lock()
        self._init_schema()

    def _init_schema(self):
        with self._write_lock:
            self._conn.execute("""
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active',
                    log_dir TEXT,
                    last_active_at TEXT NOT NULL
                )
            """)
            self._conn.execute("""
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    parent_task_id TEXT,
                    type TEXT NOT NULL,
                    tool_name TEXT,
                    status TEXT NOT NULL DEFAULT 'running',
                    progress REAL NOT NULL DEFAULT 0.0,
                    trace_id TEXT,
                    result_summary TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (session_id) REFERENCES sessions(id)
                )
            """)
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_tasks_session ON tasks(session_id)")
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_tasks_parent ON tasks(parent_task_id)")
            self._conn.commit()

    # ── Session CRUD ──
    def create_session(self, name: str, log_dir: str | None = None) -> dict:
        sid = uuid.uuid4().hex[:12]
        now = _now()
        with self._write_lock:
            self._conn.execute(
                "INSERT INTO sessions (id, name, created_at, status, log_dir, last_active_at) "
                "VALUES (?, ?, ?, 'active', ?, ?)",
                (sid, name, now, log_dir, now),
            )
            self._conn.commit()
        return {"id": sid, "name": name, "created_at": now,
                "status": "active", "log_dir": log_dir, "last_active_at": now}

    def list_sessions(self, include_closed: bool = False) -> list[dict]:
        if include_closed:
            rows = self._conn.execute(
                "SELECT * FROM sessions ORDER BY last_active_at DESC"
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM sessions WHERE status = 'active' ORDER BY last_active_at DESC"
            ).fetchall()
        return [dict(r) for r in rows]

    def get_session(self, session_id: str) -> dict | None:
        row = self._conn.execute(
            "SELECT * FROM sessions WHERE id = ?", (session_id,)
        ).fetchone()
        return dict(row) if row else None

    def update_session(self, session_id: str, **fields) -> bool:
        if not fields:
            return False
        sets = []
        values = []
        for k, v in fields.items():
            if k == "last_active_at":
                continue
            sets.append(f"{k} = ?")
            values.append(v)
        sets.append("last_active_at = ?")
        values.append(_now())
        values.append(session_id)
        with self._write_lock:
            self._conn.execute(
                f"UPDATE sessions SET {', '.join(sets)} WHERE id = ?",
                values,
            )
            self._conn.commit()
            return self._conn.total_changes > 0

    def close_session(self, session_id: str) -> None:
        if not self.update_session(session_id, status="closed"):
            logger.warning("close_session: session %s not found or already closed", session_id)

    def delete_session(self, session_id: str) -> None:
        with self._write_lock:
            self._conn.execute(
                "DELETE FROM tasks WHERE session_id = ?", (session_id,))
            self._conn.execute(
                "DELETE FROM sessions WHERE id = ?", (session_id,))
            self._conn.commit()

    # ── Task CRUD ──
    def register_task(self, task_id: str, session_id: str, type: str,
                      parent_task_id: str | None = None,
                      tool_name: str | None = None,
                      trace_id: str | None = None) -> None:
        now = _now()
        with self._write_lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO tasks "
                "(id, session_id, parent_task_id, type, tool_name, status, progress, "
                " trace_id, result_summary, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, 'running', 0.0, ?, NULL, ?, ?)",
                (task_id, session_id, parent_task_id, type, tool_name,
                 trace_id, now, now),
            )
            self._conn.commit()

    def update_task(self, task_id: str, **fields) -> bool:
        if not fields:
            return False
        sets = []
        values = []
        for k, v in fields.items():
            sets.append(f"{k} = ?")
            values.append(v)
        sets.append("updated_at = ?")
        values.append(_now())
        values.append(task_id)
        with self._write_lock:
            self._conn.execute(
                f"UPDATE tasks SET {', '.join(sets)} WHERE id = ?",
                values,
            )
            self._conn.commit()
            return self._conn.total_changes > 0

    def list_tasks(self, session_id: str,
                   parent_task_id: str | None = None) -> list[dict]:
        if parent_task_id is None:
            rows = self._conn.execute(
                "SELECT * FROM tasks WHERE session_id = ? ORDER BY created_at",
                (session_id,),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM tasks WHERE session_id = ? AND parent_task_id = ? "
                "ORDER BY created_at",
                (session_id, parent_task_id),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_task(self, task_id: str) -> dict | None:
        row = self._conn.execute(
            "SELECT * FROM tasks WHERE id = ?", (task_id,)
        ).fetchone()
        return dict(row) if row else None

    def mark_interrupted_on_startup(self, threshold_seconds: int = 3600) -> int:
        """Mark running tasks older than threshold as interrupted (crash recovery)."""
        import time as _time
        cutoff_iso = datetime.fromtimestamp(
            _time.time() - threshold_seconds, timezone.utc
        ).isoformat()
        with self._write_lock:
            cur = self._conn.execute(
                "UPDATE tasks SET status = 'interrupted' "
                "WHERE status = 'running' AND updated_at < ?",
                (cutoff_iso,),
            )
            self._conn.commit()
            return cur.rowcount

    def close(self) -> None:
        self._conn.close()


# ── Module-level singleton ──
_store: SessionStore | None = None
_store_lock = threading.Lock()


def get_session_store() -> SessionStore:
    """Global singleton SessionStore."""
    global _store
    if _store is None:
        with _store_lock:
            if _store is None:
                _store = SessionStore()
    return _store
