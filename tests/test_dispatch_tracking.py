# tests/test_dispatch_tracking.py
"""验证 dispatch 调用点正确登记到 SessionStore。"""
import json
from unittest.mock import patch, MagicMock

import pytest

from core.session import SessionStore, set_task_context, clear_task_context


def test_record_learning_registers_task(temp_dir, monkeypatch):
    """record_learning sync=false 时登记到 SessionStore。"""
    store = SessionStore(temp_dir / "sessions.db")
    monkeypatch.setattr("core.session.get_session_store", lambda: store)

    s = store.create_session("test")
    set_task_context(s["id"], "top_task_1")

    try:
        from core.tools.record_learning_tool import _record_learning_handler
        mock_runner = MagicMock()
        mock_runner.submit.return_value = "rl_tid_123"
        with patch("core.task_runner.get_shared_runner", return_value=mock_runner):
            result = _record_learning_handler({
                "domain": "interaction",
                "learning_target": "test target",
                "importance": "high",
                "reasoning": "test reasoning",
                "sync": False,
            })
        task = store.get_task("rl_tid_123")
        assert task is not None
        assert task["session_id"] == s["id"]
        assert task["parent_task_id"] == "top_task_1"
        assert task["type"] == "record_learning"
        parsed = json.loads(result)
        assert parsed["task_id"] == "rl_tid_123"
    finally:
        clear_task_context()
        store.close()


def test_no_context_skips_registration(temp_dir, monkeypatch):
    """无 thread-local context 时不登记（向后兼容 CLI 模式）。"""
    store = SessionStore(temp_dir / "sessions.db")
    monkeypatch.setattr("core.session.get_session_store", lambda: store)

    clear_task_context()

    from core.tools.record_learning_tool import _record_learning_handler
    mock_runner = MagicMock()
    mock_runner.submit.return_value = "rl_tid_no_ctx"
    with patch("core.task_runner.get_shared_runner", return_value=mock_runner):
        _record_learning_handler({
            "domain": "interaction",
            "learning_target": "no ctx",
            "importance": "low",
            "reasoning": "test",
            "sync": False,
        })
    assert store.get_task("rl_tid_no_ctx") is None
    store.close()
