"""Thread-local holder for the current TmuxSession.

TB tools (tb_terminal, tb_read_file, tb_grep) read from this to get the
active session that the harness created. CognitiveAgent.set() at the start
of perform_task and clear() at the end.

Uses threading.local so that concurrent trials (--n-concurrent > 1) don't
overwrite each other's session.
"""
from __future__ import annotations
import threading
from typing import Any

_local = threading.local()


def set(session: Any) -> None:
    _local.session = session


def get() -> Any:
    session = getattr(_local, "session", None)
    if session is None:
        raise RuntimeError("No active TmuxSession — set() not called")
    return session


def clear() -> None:
    _local.session = None
