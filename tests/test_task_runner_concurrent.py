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
