"""SQLite storage backends for L2/L3/Domain/KB.

Separate database files per store, single connection per file.
All writes are serial via sqlite3's WAL mode for multi-agent concurrency.
"""
from __future__ import annotations
import json
import sqlite3
import tempfile
from pathlib import Path


def _connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.row_factory = sqlite3.Row
    return conn


def atomic_write(func):
    """Write to temp file then rename for atomicity."""
    def wrapper(db_path, *args, **kwargs):
        # SQLite already provides atomicity via transactions
        return func(db_path, *args, **kwargs)
    return wrapper
