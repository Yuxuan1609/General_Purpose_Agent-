"""验证 6 个 store 支持跨线程访问（check_same_thread=False + 写锁）。"""
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

import pytest

from core.storage.l1_store import L1SQLiteStore
from core.storage.l2_store import L2SQLiteStore
from core.storage.l3_store import L3SQLiteStore
from core.storage.domain_store import DomainSQLiteStore
from core.storage.kb_store import KBSQLiteStore


def test_l1_store_cross_thread_access(temp_dir):
    """L1SQLiteStore 在构建线程外的线程访问不抛 ProgrammingError。"""
    store = L1SQLiteStore(temp_dir / "l1.db")
    errors = []

    def worker(i):
        try:
            store.insert({
                "id": f"rule_{i}",
                "content": f"rule content {i}",
                "created_by": "test",
                "source": "l1",
                "added_at": "2026-01-01T00:00:00Z",
                "version": 1,
                "last_modified": "2026-01-01T00:00:00Z",
            })
        except Exception as e:
            errors.append(str(e))

    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(worker, i) for i in range(20)]
        for f in as_completed(futures):
            f.result()

    assert not errors, f"cross-thread errors: {errors}"
    assert store.count() == 20
    store.close()


def test_l2_store_cross_thread_concurrent_write(temp_dir):
    """L2SQLiteStore 并发写不丢数据、不损坏。"""
    store = L2SQLiteStore(temp_dir / "l2.db")
    errors = []

    def worker(i):
        try:
            for j in range(5):
                store.insert({
                    "id": f"card_{i}_{j}",
                    "content": f"content {i}-{j}",
                    "domain": "general",
                    "available_domains": ["general"],
                    "source": "observation",
                    "created_at": "2026-01-01T00:00:00Z",
                    "updated_at": "2026-01-01T00:00:00Z",
                    "last_used": "2026-01-01T00:00:00Z",
                    "usefulness": 0,
                    "misleading": 0,
                    "comment": "",
                })
        except Exception as e:
            errors.append(str(e))

    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(worker, i) for i in range(5)]
        for f in as_completed(futures):
            f.result()

    assert not errors, f"concurrent write errors: {errors}"
    assert len(store.list_all()) == 25
    store.close()


def test_l3_store_cross_thread_access(temp_dir):
    """L3SQLiteStore 跨线程访问。"""
    store = L3SQLiteStore(temp_dir / "l3.db")
    errors = []

    def worker(i):
        try:
            store.insert({
                "name": f"skill_{i}",
                "content": f"# Skill {i}\n...",
                "domain": "general",
                "available_domains": ["general"],
                "created_by": "test",
                "created_at": "2026-01-01T00:00:00Z",
                "updated_at": "2026-01-01T00:00:00Z",
                "last_used": "2026-01-01T00:00:00Z",
            })
        except Exception as e:
            errors.append(str(e))

    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(worker, i) for i in range(10)]
        for f in as_completed(futures):
            f.result()

    assert not errors
    assert store.count() == 10
    store.close()


def test_domain_store_cross_thread_index(temp_dir):
    """DomainSQLiteStore 跨线程 index_item。"""
    store = DomainSQLiteStore(temp_dir / "domain.db")
    store.insert_node({
        "path": "general", "parent": None, "description": "general",
        "correlations": {}, "relations": "", "embedding_vector": None,
    })
    errors = []

    def worker(i):
        try:
            store.index_item("l2", "general", f"item_{i}")
        except Exception as e:
            errors.append(str(e))

    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(worker, i) for i in range(20)]
        for f in as_completed(futures):
            f.result()

    assert not errors
    items = store.get_items("l2", "general")
    assert len(items) == 20
    store.close()


def test_kb_store_cross_thread_insert(temp_dir):
    """KBSQLiteStore 跨线程 insert。"""
    store = KBSQLiteStore(temp_dir / "kb.db")
    errors = []

    def worker(i):
        try:
            store.insert({
                "id": f"doc_{i}",
                "domain": "general",
                "title": f"Title {i}",
                "content": f"content {i}",
                "source": "test",
                "meta": {},
                "created_at": "2026-01-01T00:00:00Z",
                "updated_at": "2026-01-01T00:00:00Z",
                "last_used": "2026-01-01T00:00:00Z",
            })
        except Exception as e:
            errors.append(str(e))

    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(worker, i) for i in range(10)]
        for f in as_completed(futures):
            f.result()

    assert not errors
    assert len(store.list_all()) == 10
    store.close()
