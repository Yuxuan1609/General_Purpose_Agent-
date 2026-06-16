"""Async dispatch integration test."""
from pathlib import Path
import sys, time

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def test_async_submit_collect():
    from core.task_runner import get_task_runner
    runner = get_task_runner()

    tids = []
    for i in range(3):
        def _work(n=i):
            time.sleep(0.3)
            return f"result_{n}"
        tid = runner.submit("test_async", _work)
        tids.append(tid)
        print(f"  dispatched: {tid}")

    # Collect before done — should be empty
    early = runner.collect(tids)
    assert len(early) == 0
    print("PASS: collect before done returns empty")

    time.sleep(1)
    results = runner.collect(tids)
    assert len(results) == 3
    for r in results:
        assert r["status"] == "done"
    print(f"PASS: async submit → collect {len(results)} results")

    assert runner.check(tids[0]) is None
    print("PASS: tasks removed from store after collect")


def test_sync_batch_parallel():
    from core.task_runner import get_task_runner
    runner = get_task_runner()

    start = time.time()
    results = runner.run_sync_batch([
        {"id": "a", "tool": "slow", "exec": lambda: time.sleep(0.5) or "a"},
        {"id": "b", "tool": "slow", "exec": lambda: time.sleep(0.5) or "b"},
        {"id": "c", "tool": "fast", "exec": lambda: "c"},
    ])
    elapsed = time.time() - start
    # Parallel: should be ~0.5s, not 1.0s
    assert elapsed < 0.8, f"too slow: {elapsed:.2f}s (expected <0.8)"
    assert len(results) == 3
    print(f"PASS: sync batch parallel in {elapsed:.2f}s")


def test_sync_batch_error_handling():
    from core.task_runner import get_task_runner
    runner = get_task_runner()

    results = runner.run_sync_batch([
        {"id": "ok", "tool": "t", "exec": lambda: "good"},
        {"id": "bad", "tool": "t", "exec": lambda: (_ for _ in ()).throw(ValueError("boom"))},
    ])
    assert results[0]["success"]
    assert results[0]["data"] == "good"
    assert not results[1]["success"]
    assert "boom" in str(results[1]["error"])
    print("PASS: error handling — good result + error both returned")


def test_stats():
    from core.task_runner import get_task_runner
    runner = get_task_runner()
    runner.run_sync_batch([
        {"id": "x", "tool": "stat_tool", "exec": lambda: "ok"},
    ])
    s = runner.stats()
    assert "stat_tool" in s
    assert s["stat_tool"]["count"] == 1
    print(f"PASS: stats present: {list(s.keys())[:5]}")


if __name__ == "__main__":
    test_async_submit_collect()
    test_sync_batch_parallel()
    test_sync_batch_error_handling()
    test_stats()
    print("\nAll async dispatch tests pass!")
