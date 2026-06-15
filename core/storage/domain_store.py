"""SQLite storage for DomainRegistry (nodes + reverse_index)."""
from __future__ import annotations
import json
import sqlite3
from pathlib import Path


class DomainSQLiteStore:
    def __init__(self, db_path: Path | str):
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._db_path))
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self):
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS domain_nodes (
                path TEXT PRIMARY KEY,
                parent TEXT,
                description TEXT NOT NULL DEFAULT '',
                correlations TEXT NOT NULL DEFAULT '{}',
                relations TEXT NOT NULL DEFAULT '',
                embedding_vector TEXT
            );
            CREATE TABLE IF NOT EXISTS reverse_index (
                layer TEXT NOT NULL,
                domain TEXT NOT NULL,
                item_id TEXT NOT NULL,
                PRIMARY KEY (layer, domain, item_id)
            );
        """)
        self._conn.commit()

    # ── nodes ──

    def insert_node(self, node: dict) -> None:
        emb = node.get("embedding_vector")
        emb_json = json.dumps(emb) if emb else None
        self._conn.execute("""
            INSERT OR REPLACE INTO domain_nodes
            (path, parent, description, correlations, relations, embedding_vector)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            node["path"],
            node.get("parent"),
            node.get("description", ""),
            json.dumps(node.get("correlations", {})),
            node.get("relations", ""),
            emb_json,
        ))
        self._conn.commit()

    def update_node(self, path: str, **fields) -> bool:
        sets = []
        values = []
        for k, v in fields.items():
            if k == "correlations":
                v = json.dumps(v)
            if k == "embedding_vector" and v is not None:
                v = json.dumps(v)
            sets.append(f"{k} = ?")
            values.append(v)
        if not sets:
            return False
        values.append(path)
        self._conn.execute(
            f"UPDATE domain_nodes SET {', '.join(sets)} WHERE path = ?",
            values,
        )
        self._conn.commit()
        return self._conn.total_changes > 0

    def delete_node(self, path: str) -> bool:
        self._conn.execute("DELETE FROM domain_nodes WHERE path = ?", (path,))
        self._conn.commit()
        return self._conn.total_changes > 0

    def get_node(self, path: str) -> dict | None:
        row = self._conn.execute(
            "SELECT * FROM domain_nodes WHERE path = ?", (path,)
        ).fetchone()
        return self._row_to_node(row) if row else None

    def list_nodes(self) -> list[dict]:
        rows = self._conn.execute("SELECT * FROM domain_nodes").fetchall()
        return [self._row_to_node(r) for r in rows]

    @staticmethod
    def _row_to_node(row: sqlite3.Row) -> dict:
        d = dict(row)
        d["correlations"] = json.loads(d["correlations"])
        emb = d.get("embedding_vector")
        d["embedding_vector"] = json.loads(emb) if emb else None
        return d

    # ── reverse_index ──

    def index_item(self, layer: str, domain: str, item_id: str) -> None:
        self._conn.execute(
            "INSERT OR IGNORE INTO reverse_index (layer, domain, item_id) VALUES (?, ?, ?)",
            (layer, domain, item_id),
        )
        self._conn.commit()

    def unindex_item(self, layer: str, domain: str, item_id: str) -> None:
        self._conn.execute(
            "DELETE FROM reverse_index WHERE layer = ? AND domain = ? AND item_id = ?",
            (layer, domain, item_id),
        )
        self._conn.commit()

    def unindex_domain(self, layer: str, domain: str) -> None:
        self._conn.execute(
            "DELETE FROM reverse_index WHERE layer = ? AND domain = ?",
            (layer, domain),
        )
        self._conn.commit()

    def get_items(self, layer: str, domain: str) -> list[str]:
        rows = self._conn.execute(
            "SELECT item_id FROM reverse_index WHERE layer = ? AND domain = ?",
            (layer, domain),
        ).fetchall()
        return [r["item_id"] for r in rows]

    def get_all_index(self) -> dict[str, dict[str, list[str]]]:
        rows = self._conn.execute(
            "SELECT layer, domain, item_id FROM reverse_index ORDER BY layer, domain"
        ).fetchall()
        result: dict = {"l2": {}, "l3": {}, "tool": {}}
        for r in rows:
            result.setdefault(r["layer"], {}).setdefault(r["domain"], []).append(r["item_id"])
        return result

    def count(self) -> int:
        row = self._conn.execute("SELECT COUNT(*) as cnt FROM domain_nodes").fetchone()
        return row["cnt"] if row else 0

    def close(self):
        self._conn.close()
