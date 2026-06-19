# tests/test_session.py
"""SessionStore — session + task 元数据持久化 + thread-local task context。"""
import threading
from datetime import datetime, timezone

import pytest

from core.session import (
    SessionStore, set_task_context, get_task_context, clear_task_context,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class TestSessionStore:
    def test_create_session(self, temp_dir):
        store = SessionStore(temp_dir / "sessions.db")
        s = store.create_session(name="工作区A")
        assert s["id"]
        assert s["name"] == "工作区A"
        assert s["status"] == "active"
        store.close()

    def test_list_sessions_excludes_closed_by_default(self, temp_dir):
        store = SessionStore(temp_dir / "sessions.db")
        s1 = store.create_session("active_one")
        s2 = store.create_session("closed_one")
        store.close_session(s2["id"])
        listed = store.list_sessions()
        ids = [s["id"] for s in listed]
        assert s1["id"] in ids
        assert s2["id"] not in ids
        store.close()

    def test_list_sessions_include_closed(self, temp_dir):
        store = SessionStore(temp_dir / "sessions.db")
        s = store.create_session("to_close")
        store.close_session(s["id"])
        listed = store.list_sessions(include_closed=True)
        assert any(x["id"] == s["id"] for x in listed)
        store.close()

    def test_get_session(self, temp_dir):
        store = SessionStore(temp_dir / "sessions.db")
        s = store.create_session("test")
        got = store.get_session(s["id"])
        assert got is not None
        assert got["name"] == "test"
        assert store.get_session("nonexistent") is None
        store.close()

    def test_update_session(self, temp_dir):
        store = SessionStore(temp_dir / "sessions.db")
        s = store.create_session("old_name")
        store.update_session(s["id"], name="new_name")
        got = store.get_session(s["id"])
        assert got["name"] == "new_name"
        store.close()

    def test_delete_session_cascades_tasks(self, temp_dir):
        store = SessionStore(temp_dir / "sessions.db")
        s = store.create_session("to_delete")
        store.register_task("task_1", s["id"], "top")
        store.register_task("task_2", s["id"], "record_learning", parent_task_id="task_1")
        store.delete_session(s["id"])
        assert store.get_session(s["id"]) is None
        assert store.list_tasks(s["id"]) == []
        store.close()


class TestTaskCRUD:
    def test_register_and_list_tasks(self, temp_dir):
        store = SessionStore(temp_dir / "sessions.db")
        s = store.create_session("test")
        store.register_task("t1", s["id"], "top")
        store.register_task("t2", s["id"], "record_learning", parent_task_id="t1")
        tasks = store.list_tasks(s["id"])
        assert len(tasks) == 2
        sub = store.list_tasks(s["id"], parent_task_id="t1")
        assert len(sub) == 1
        assert sub[0]["id"] == "t2"
        store.close()

    def test_update_task(self, temp_dir):
        store = SessionStore(temp_dir / "sessions.db")
        s = store.create_session("test")
        store.register_task("t1", s["id"], "top")
        store.update_task("t1", status="done", progress=100.0,
                          result_summary="已完成")
        got = store.get_task("t1")
        assert got["status"] == "done"
        assert got["progress"] == 100.0
        assert got["result_summary"] == "已完成"
        store.close()

    def test_get_task_nonexistent(self, temp_dir):
        store = SessionStore(temp_dir / "sessions.db")
        assert store.get_task("nope") is None
        store.close()


class TestMarkInterrupted:
    def test_running_tasks_marked_interrupted_on_startup(self, temp_dir):
        """status='running' 且 updated_at 超阈值的 task 改 'interrupted'。"""
        store = SessionStore(temp_dir / "sessions.db")
        s = store.create_session("test")
        store.register_task("stuck", s["id"], "top")
        # 手动改 updated_at 为 2 小时前
        old = (datetime.now(timezone.utc).timestamp()) - 7200
        store._conn.execute(
            "UPDATE tasks SET updated_at = ? WHERE id = ?",
            (datetime.fromtimestamp(old, timezone.utc).isoformat(), "stuck"),
        )
        store._conn.commit()
        count = store.mark_interrupted_on_startup(threshold_seconds=3600)
        assert count == 1
        got = store.get_task("stuck")
        assert got["status"] == "interrupted"
        store.close()

    def test_recent_running_not_marked(self, temp_dir):
        store = SessionStore(temp_dir / "sessions.db")
        s = store.create_session("test")
        store.register_task("fresh", s["id"], "top")
        count = store.mark_interrupted_on_startup(threshold_seconds=3600)
        assert count == 0
        got = store.get_task("fresh")
        assert got["status"] == "running"
        store.close()


class TestThreadLocalContext:
    def test_set_and_get_context(self):
        clear_task_context()
        set_task_context("sess_1", "task_1")
        sid, tid = get_task_context()
        assert sid == "sess_1"
        assert tid == "task_1"
        clear_task_context()

    def test_clear_context(self):
        set_task_context("sess_1", "task_1")
        clear_task_context()
        sid, tid = get_task_context()
        assert sid is None
        assert tid is None

    def test_context_is_thread_local(self):
        """不同线程的 context 互不干扰。"""
        results = {}
        set_task_context("main_sess", "main_task")

        def worker():
            set_task_context("worker_sess", "worker_task")
            results["worker"] = get_task_context()
            clear_task_context()

        t = threading.Thread(target=worker)
        t.start()
        t.join()
        assert results["worker"] == ("worker_sess", "worker_task")
        sid, tid = get_task_context()
        assert sid == "main_sess"
        assert tid == "main_task"
        clear_task_context()
