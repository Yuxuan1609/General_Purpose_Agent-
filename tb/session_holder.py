"""Module-level holder for the current TmuxSession.

TB tools (tb_terminal, tb_read_file, tb_grep) read from this to get the
active session that the harness created. CognitiveAgent.set() at the start
of perform_task and clear() at the end.

Uses a module-level global (NOT threading.local) because tool dispatch
via TaskRunner.run_sync_batch runs handlers in worker threads, and those
threads need to access the session set in the perform_task thread.
Process isolation (separate python processes per task) ensures no
cross-agent interference.
"""
from __future__ import annotations
from typing import Any

_current: Any = None


def set(session: Any) -> None:
    global _current
    _current = session


def get() -> Any:
    if _current is None:
        raise RuntimeError("No active TmuxSession — set() not called")
    return _current


def clear() -> None:
    global _current
    _current = None
