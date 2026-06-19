"""SQLite storage for L3 skills (including SKILL.md content)."""
from __future__ import annotations
import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class L3SQLiteStore:
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
            CREATE TABLE IF NOT EXISTS l3_skills (
                name TEXT PRIMARY KEY,
                description TEXT NOT NULL DEFAULT '',
                content TEXT NOT NULL DEFAULT '',
                domain TEXT NOT NULL DEFAULT 'general',
                available_domains TEXT NOT NULL DEFAULT '[]',
                cross_domain INTEGER NOT NULL DEFAULT 0,
                version TEXT NOT NULL DEFAULT '1.0.0',
                created_by TEXT NOT NULL DEFAULT 'agent',
                source_cards TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                last_used TEXT NOT NULL,
                usefulness INTEGER NOT NULL DEFAULT 0,
                misleading INTEGER NOT NULL DEFAULT 0,
                comment TEXT NOT NULL DEFAULT ''
            )
        """)
        self._conn.commit()

    def insert(self, skill: dict) -> None:
        with self._write_lock:
            self._conn.execute("""
                INSERT OR REPLACE INTO l3_skills
                (name, description, content, domain, available_domains,
                 cross_domain, version, created_by, source_cards,
                 created_at, updated_at, last_used, usefulness, misleading, comment)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                skill["name"],
                skill.get("description", ""),
                skill.get("content", ""),
                skill.get("domain", "general"),
                json.dumps(skill.get("available_domains", [])),
                1 if skill.get("cross_domain") else 0,
                skill.get("version", "1.0.0"),
                skill.get("created_by", "agent"),
                json.dumps(skill.get("source_cards", [])),
                skill.get("created_at", _now()),
                skill.get("updated_at", _now()),
                skill.get("last_used", _now()),
                skill.get("usefulness", 0),
                skill.get("misleading", 0),
                skill.get("comment", ""),
            ))
            self._conn.commit()

    def update(self, name: str, **fields) -> bool:
        sets = []
        values = []
        for k, v in fields.items():
            if k in ("available_domains", "source_cards"):
                v = json.dumps(v)
            if k == "cross_domain":
                v = 1 if v else 0
            sets.append(f"{k} = ?")
            values.append(v)
        if not sets:
            return False
        sets.append("updated_at = ?")
        values.append(_now())
        values.append(name)
        with self._write_lock:
            self._conn.execute(
                f"UPDATE l3_skills SET {', '.join(sets)} WHERE name = ?",
                values,
            )
            self._conn.commit()
            return self._conn.total_changes > 0

    def delete(self, name: str) -> bool:
        with self._write_lock:
            self._conn.execute("DELETE FROM l3_skills WHERE name = ?", (name,))
            self._conn.commit()
            return self._conn.total_changes > 0

    def get(self, name: str) -> dict | None:
        row = self._conn.execute(
            "SELECT * FROM l3_skills WHERE name = ?", (name,)
        ).fetchone()
        return self._row_to_dict(row) if row else None

    def list_all(self) -> list[dict]:
        rows = self._conn.execute("SELECT * FROM l3_skills").fetchall()
        return [self._row_to_dict(r) for r in rows]

    def list_by_domain(self, domain: str) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM l3_skills WHERE available_domains LIKE ?",
            (f'%"{domain}"%',),
        ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def count(self) -> int:
        row = self._conn.execute("SELECT COUNT(*) as cnt FROM l3_skills").fetchone()
        return row["cnt"] if row else 0

    @staticmethod
    def _row_to_dict(row: sqlite3.Row | None) -> dict | None:
        if row is None:
            return None
        d = dict(row)
        d["available_domains"] = json.loads(d["available_domains"])
        d["source_cards"] = json.loads(d["source_cards"])
        d["cross_domain"] = bool(d["cross_domain"])
        return d

    def close(self):
        self._conn.close()
