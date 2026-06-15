"""SQLite storage for L2 knowledge cards."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class L2SQLiteStore:
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
            CREATE TABLE IF NOT EXISTS l2_cards (
                id TEXT PRIMARY KEY,
                content TEXT NOT NULL,
                domain TEXT NOT NULL DEFAULT 'general',
                available_domains TEXT NOT NULL DEFAULT '[]',
                sub_tags TEXT NOT NULL DEFAULT '[]',
                source TEXT NOT NULL DEFAULT 'observation',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                last_used TEXT NOT NULL,
                usefulness INTEGER NOT NULL DEFAULT 0,
                misleading INTEGER NOT NULL DEFAULT 0,
                comment TEXT NOT NULL DEFAULT ''
            )
        """)
        self._conn.commit()

    def insert(self, card: dict) -> None:
        self._conn.execute("""
            INSERT OR REPLACE INTO l2_cards
            (id, content, domain, available_domains, sub_tags, source,
             created_at, updated_at, last_used, usefulness, misleading, comment)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            card["id"],
            card["content"],
            card.get("domain", "general"),
            json.dumps(card.get("available_domains", [])),
            json.dumps(card.get("sub_tags", [])),
            card.get("source", "observation"),
            card.get("created_at", _now()),
            card.get("updated_at", _now()),
            card.get("last_used", _now()),
            card.get("usefulness", 0),
            card.get("misleading", 0),
            card.get("comment", ""),
        ))
        self._conn.commit()

    def update(self, card_id: str, **fields) -> bool:
        sets = []
        values = []
        for k, v in fields.items():
            if k in ("available_domains", "sub_tags"):
                v = json.dumps(v)
            sets.append(f"{k} = ?")
            values.append(v)
        if not sets:
            return False
        sets.append("updated_at = ?")
        values.append(_now())
        values.append(card_id)
        self._conn.execute(
            f"UPDATE l2_cards SET {', '.join(sets)} WHERE id = ?",
            values,
        )
        self._conn.commit()
        return self._conn.total_changes > 0

    def delete(self, card_id: str) -> bool:
        self._conn.execute("DELETE FROM l2_cards WHERE id = ?", (card_id,))
        self._conn.commit()
        return self._conn.total_changes > 0

    def get(self, card_id: str) -> dict | None:
        row = self._conn.execute(
            "SELECT * FROM l2_cards WHERE id = ?", (card_id,)
        ).fetchone()
        return self._row_to_dict(row) if row else None

    def list_all(self) -> list[dict]:
        rows = self._conn.execute("SELECT * FROM l2_cards").fetchall()
        return [self._row_to_dict(r) for r in rows]

    def list_by_domain(self, domain: str) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM l2_cards WHERE available_domains LIKE ?",
            (f'%"{domain}"%',),
        ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    @staticmethod
    def _row_to_dict(row: sqlite3.Row | None) -> dict | None:
        if row is None:
            return None
        d = dict(row)
        d["available_domains"] = json.loads(d["available_domains"])
        d["sub_tags"] = json.loads(d["sub_tags"])
        return d

    def close(self):
        self._conn.close()
