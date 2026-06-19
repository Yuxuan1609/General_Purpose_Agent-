# tests/test_task_runner_concurrent.py
"""验证 get_shared_runner() 在多线程 submit+collect 下的正确性。"""
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from core.task_runner import get_shared_runner, TaskRunner


def test_shared_runner_is_singleton():
    """get_shared_runner() 返回同一实例。"""
    a = get_shared_runner()
    b = get_shared_runner()
    assert a is b


def test_concurrent_submit_and_collect():
    """2 线程同时 submit + collect，task 不丢失。"""
    runner = get_shared_runner()
    results = {}
    lock = threading.Lock()

    def worker(worker_id: int):
        tids = []
        for i in range(10):
            tid = runner.submit(f"test_tool_{worker_id}",
                                 lambda w=worker_id, i=i: f"r{w}-{i}")
            tids.append(tid)
        # collect() is non-blocking — wait for all tasks to complete first
        deadline = time.time() + 10
        while time.time() < deadline:
            if all(runner.check(tid) and runner.check(tid).status != "running"
                   for tid in tids):
                break
            time.sleep(0.05)
        collected = runner.collect(tids)
        with lock:
            results[worker_id] = collected

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(worker, w) for w in range(2)]
        for f in as_completed(futures):
            f.result()  # propagate exceptions

    # 每个 worker 应该收到 10 个结果
    assert len(results[0]) == 10
    assert len(results[1]) == 10
    # 所有 task 应该是 done 状态
    for collected in results.values():
        for item in collected:
            assert item["status"] == "done"


def test_concurrent_submit_does_not_lose_tasks():
    """高频并发 submit 不丢任务（验证 _tasks dict 锁保护）。"""
    runner = get_shared_runner()
    submitted_tids = []
    submit_lock = threading.Lock()

    def submitter():
        for i in range(20):
            tid = runner.submit("burst", lambda i=i: i)
            with submit_lock:
                submitted_tids.append(tid)

    threads = [threading.Thread(target=submitter) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # 80 个 task 全部应可查询到
    for tid in submitted_tids:
        assert runner.check(tid) is not None, f"task {tid} lost"


def test_update_progress():
    """update_progress 设置 task 的 progress 字段。"""
    runner = get_shared_runner()
    tid = runner.submit("test", lambda: time.sleep(0.1))
    runner.update_progress(tid, 50.0)
    task = runner.check(tid)
    assert task is not None
    assert task.progress == 50.0


def test_subscribe_receives_state_changes():
    """subscribe 的 callback 在 task 完成时被调用。"""
    runner = get_shared_runner()
    received = []
    lock = threading.Lock()

    def callback(task):
        with lock:
            received.append((task.task_id, task.status))

    runner.subscribe(callback)
    try:
        tid = runner.submit("test", lambda: "done")
        # 等 task 完成
        time.sleep(0.3)
        # callback 应该被触发
        assert any(tid == t[0] for t in received), f"callback not called for {tid}"
    finally:
        runner.unsubscribe(callback)


def test_list_tasks_filter_by_tool_name():
    """list_tasks 按工具名过滤。"""
    runner = get_shared_runner()
    tids = []
    for i in range(3):
        tids.append(runner.submit("filter_tool", lambda: i))
        runner.submit("other_tool", lambda: i)
    tasks = runner.list_tasks(tool_name="filter_tool")
    assert len(tasks) >= 3
    assert all(t.tool_name == "filter_tool" for t in tasks)


def test_list_tasks_filter_by_session_id():
    """list_tasks 按 session_id 过滤（通过 metadata 注入）。"""
    runner = get_shared_runner()
    tid = runner.submit("test", lambda: "ok", metadata={"session_id": "sess_123"})
    tasks = runner.list_tasks(session_id="sess_123")
    assert any(t.task_id == tid for t in tasks)


def test_collect_keeps_history_by_default():
    """collect 默认保留历史，不删除 task。"""
    runner = get_shared_runner()
    tid = runner.submit("test", lambda: "done")
    # Wait for completion
    deadline = time.time() + 10
    while time.time() < deadline:
        task = runner.check(tid)
        if task and task.status != "running":
            break
        time.sleep(0.05)
    collected = runner.collect([tid])  # keep_history defaults to True
    assert len(collected) == 1
    # task 应该仍然可查
    assert runner.check(tid) is not None


def test_cancel_marks_task_cancelled():
    """cancel 设置 cancelled 标志。"""
    runner = get_shared_runner()
    cancelled_flag = threading.Event()

    def long_task():
        while not cancelled_flag.is_set():
            time.sleep(0.05)
        return "cancelled"

    tid = runner.submit("long", long_task)
    runner.cancel(tid)
    cancelled_flag.set()
    time.sleep(0.2)
    task = runner.check(tid)
    assert task is not None
    assert task.status == "cancelled" or task.cancelled is True
