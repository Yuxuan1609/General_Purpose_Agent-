"""SQLite storage for L1 rules."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class L1SQLiteStore:
    def __init__(self, db_path: Path | str):
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._db_path))
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self):
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS l1_rules (
                id TEXT PRIMARY KEY,
                content TEXT NOT NULL,
                created_by TEXT NOT NULL DEFAULT 'unknown',
                source TEXT NOT NULL DEFAULT 'l1',
                added_at TEXT NOT NULL,
                version INTEGER NOT NULL DEFAULT 1,
                last_modified TEXT NOT NULL
            )
        """)
        self._conn.commit()

    def insert(self, rule: dict) -> None:
        self._conn.execute("""
            INSERT OR REPLACE INTO l1_rules
            (id, content, created_by, source, added_at, version, last_modified)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            rule["id"],
            rule["content"],
            rule.get("created_by", "unknown"),
            rule.get("source", "l1"),
            rule.get("added_at", _now()),
            rule.get("version", 1),
            rule.get("last_modified", _now()),
        ))
        self._conn.commit()

    def update(self, rule_id: str, **fields) -> bool:
        sets = []
        values = []
        for k, v in fields.items():
            sets.append(f"{k} = ?")
            values.append(v)
        if not sets:
            return False
        sets.append("last_modified = ?")
        values.append(_now())
        values.append(rule_id)
        self._conn.execute(
            f"UPDATE l1_rules SET {', '.join(sets)} WHERE id = ?",
            values,
        )
        self._conn.commit()
        return self._conn.total_changes > 0

    def delete(self, rule_id: str) -> bool:
        self._conn.execute("DELETE FROM l1_rules WHERE id = ?", (rule_id,))
        self._conn.commit()
        return self._conn.total_changes > 0

    def get(self, rule_id: str) -> dict | None:
        row = self._conn.execute(
            "SELECT * FROM l1_rules WHERE id = ?", (rule_id,)
        ).fetchone()
        return dict(row) if row else None

    def list_all(self) -> list[dict]:
        rows = self._conn.execute("SELECT * FROM l1_rules").fetchall()
        return [dict(r) for r in rows]

    def count(self) -> int:
        return self._conn.execute("SELECT COUNT(*) FROM l1_rules").fetchone()[0]

    def close(self):
        self._conn.close()
