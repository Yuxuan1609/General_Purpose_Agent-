"""SQLite storage for KB metadata (KnowledgeDoc metadata, not txtai content)."""
from __future__ import annotations
import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class KBSQLiteStore:
    def __init__(self, db_path: Path | str):
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.row_factory = sqlite3.Row
        self._init_schema()
        self._write_lock = threading.Lock()

    def _init_schema(self):
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS kb_docs (
                id TEXT PRIMARY KEY,
                domain TEXT NOT NULL DEFAULT '',
                title TEXT NOT NULL DEFAULT '',
                content_type TEXT NOT NULL DEFAULT 'markdown',
                source TEXT NOT NULL DEFAULT 'manual',
                meta TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                last_used TEXT NOT NULL
            )
        """)
        self._conn.commit()

    def insert(self, doc: dict) -> None:
        with self._write_lock:
            self._conn.execute("""
                INSERT OR REPLACE INTO kb_docs
                (id, domain, title, content_type, source, meta,
                 created_at, updated_at, last_used)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                doc["id"],
                doc["domain"],
                doc.get("title", ""),
                doc.get("content_type", "markdown"),
                doc.get("source", "manual"),
                json.dumps(doc.get("meta", {})),
                doc.get("created_at", _now()),
                doc.get("updated_at", _now()),
                doc.get("last_used", _now()),
            ))
            self._conn.commit()

    def update(self, doc_id: str, **fields) -> bool:
        sets = []
        values = []
        for k, v in fields.items():
            if k == "meta":
                v = json.dumps(v)
            sets.append(f"{k} = ?")
            values.append(v)
        if not sets:
            return False
        sets.append("updated_at = ?")
        values.append(_now())
        values.append(doc_id)
        with self._write_lock:
            self._conn.execute(
                f"UPDATE kb_docs SET {', '.join(sets)} WHERE id = ?",
                values,
            )
            self._conn.commit()
            return self._conn.total_changes > 0

    def delete(self, doc_id: str) -> bool:
        with self._write_lock:
            self._conn.execute("DELETE FROM kb_docs WHERE id = ?", (doc_id,))
            self._conn.commit()
            return self._conn.total_changes > 0

    def get(self, doc_id: str) -> dict | None:
        row = self._conn.execute(
            "SELECT * FROM kb_docs WHERE id = ?", (doc_id,)
        ).fetchone()
        return self._row_to_dict(row) if row else None

    def list_all(self) -> list[dict]:
        rows = self._conn.execute("SELECT * FROM kb_docs").fetchall()
        return [self._row_to_dict(r) for r in rows]

    def list_by_domain(self, domain: str) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM kb_docs WHERE domain = ?", (domain,)
        ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def touch(self, doc_id: str) -> None:
        with self._write_lock:
            self._conn.execute(
                "UPDATE kb_docs SET last_used = ? WHERE id = ?",
                (_now(), doc_id),
            )
            self._conn.commit()

    @staticmethod
    def _row_to_dict(row: sqlite3.Row | None) -> dict | None:
        if row is None:
            return None
        d = dict(row)
        d["meta"] = json.loads(d["meta"])
        return d

    def close(self):
        self._conn.close()
