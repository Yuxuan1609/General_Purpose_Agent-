# tests/test_monitor.py
"""Monitor 模块 — 聚合 trace 数据源（纯查询，不修改状态）。"""
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from core.monitor import snapshot, log_tail, task_list, decision_tree, task_detail


def test_snapshot_returns_expected_keys(temp_dir, monkeypatch):
    """snapshot 返回 tasks/capacity/learning/sessions 四个 key。"""
    mock_chain = MagicMock()
    mock_chain._downstream = None
    monkeypatch.setattr("core.monitor._session_summary", lambda: {"count": 1})
    monkeypatch.setattr("core.monitor._learning_snapshot", lambda d: {"total_pending": 0})
    monkeypatch.setattr("core.monitor._capacity_snapshot", lambda c: {"l2": {}, "l3": {}})
    monkeypatch.setattr("core.monitor._task_list", lambda sid: [])

    snap = snapshot(session_id="s1", chain=mock_chain)
    assert set(snap.keys()) == {"tasks", "capacity", "learning", "sessions"}


def test_log_tail_returns_last_n_lines(temp_dir):
    """log_tail 读文件尾部 N 行。"""
    log_dir = temp_dir / "logs" / "ts_1"
    log_dir.mkdir(parents=True)
    log_file = log_dir / "l0_5_1.log"
    log_file.write_text("line1\nline2\nline3\nline4\nline5\n", encoding="utf-8")

    tail = log_tail(str(log_dir), "l0_5_1", lines=2)
    assert "line4" in tail
    assert "line5" in tail
    assert "line3" not in tail


def test_log_tail_nonexistent_file_returns_empty(temp_dir):
    """log_tail 不存在的文件返回空字符串。"""
    result = log_tail(str(temp_dir / "nope"), "l0_5_1")
    assert result == ""


def test_task_list_uses_session_store(temp_dir, monkeypatch):
    """task_list 从 SessionStore 拉取。"""
    mock_store = MagicMock()
    mock_store.list_tasks.return_value = [{"id": "t1", "type": "top"}]
    monkeypatch.setattr("core.session.get_session_store", lambda: mock_store)

    tasks = task_list("sess_1")
    assert tasks == [{"id": "t1", "type": "top"}]
    mock_store.list_tasks.assert_called_once_with("sess_1", None)


def test_decision_tree_uses_round_history(monkeypatch):
    """decision_tree 复用 RoundTree.snapshot()。"""
    mock_history = MagicMock()
    mock_node = MagicMock()
    mock_node.layer = "l0_5_1"
    mock_history.snapshot.return_value = [mock_node]
    monkeypatch.setattr("core.round_tree.get_round_history", lambda: mock_history)

    tree = decision_tree()
    assert tree == [mock_node]


def test_task_detail_uses_session_store(temp_dir, monkeypatch):
    """task_detail 从 SessionStore.get_task 拉取。"""
    mock_store = MagicMock()
    mock_store.get_task.return_value = {"id": "t1", "status": "done"}
    monkeypatch.setattr("core.session.get_session_store", lambda: mock_store)

    detail = task_detail("t1")
    assert detail == {"id": "t1", "status": "done"}
