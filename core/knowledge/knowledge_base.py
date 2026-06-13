# core/knowledge/knowledge_base.py
from __future__ import annotations
import json
import logging
from datetime import datetime, timezone
from typing import Any

from core.knowledge.models import KnowledgeDoc, KBDomain, _count_tokens, _get_tokenizer
from vendor.txtai_core.embeddings import Embeddings

logger = logging.getLogger("knowledge_base")


def _now_static() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


class KnowledgeBase:
    """Knowledge base backed by txtai Embeddings for storage/persistence.

    Provides CRUD operations and search over KnowledgeDoc entries.
    Domain graph is maintained alongside documents.
    """

    def __init__(self, storage_path: str = "data/knowledge"):
        self._storage_path = storage_path
        self._emb = None
        self._docs: dict[str, KnowledgeDoc] = {}
        self._domains: dict[str, KBDomain] = {}

    def _ensure_emb(self):
        if self._emb is not None:
            return
        self._emb = Embeddings({
            "path": "C:/Users/micha/PycharmProjects/cognitive-agent/embeddinggemma",
            "trust_remote_code": True,
            "content": "sqlite",
            "keyword": "bm25",
        })

    def add(self, doc: KnowledgeDoc) -> list[str]:
        return self._chunk_and_add(doc)

    def _chunk_and_add(self, doc: KnowledgeDoc) -> list[str]:
        MAX_TOKENS = 8192
        tokens = _count_tokens(doc.content)
        if tokens <= MAX_TOKENS:
            self._add_single(doc)
            return [doc.id]

        tokenizer = _get_tokenizer()
        token_ids = tokenizer.encode(doc.content)
        chunks = []
        for i in range(0, len(token_ids), MAX_TOKENS):
            chunk_ids = token_ids[i:i + MAX_TOKENS]
            chunk_text = tokenizer.decode(chunk_ids, skip_special_tokens=True)
            chunks.append(chunk_text)

        doc_ids = []
        for idx, chunk_text in enumerate(chunks):
            chunk_doc = KnowledgeDoc(
                domain=doc.domain,
                title=f"{doc.title} (part {idx+1}/{len(chunks)})",
                content=chunk_text,
                meta=dict(doc.meta),
                source=doc.source,
            )
            chunk_doc.meta["chunk_of"] = doc.id if idx == 0 else doc_ids[0]
            chunk_doc.meta["chunk_index"] = idx
            chunk_doc.meta["chunk_total"] = len(chunks)
            self._add_single(chunk_doc)
            doc_ids.append(chunk_doc.id)
        return doc_ids

    def _add_single(self, doc: KnowledgeDoc) -> str:
        doc.meta.pop("id", None)

        self._ensure_emb()
        tags_str = json.dumps(dict(doc.meta), ensure_ascii=False) if doc.meta else None
        self._emb.upsert([(doc.id, doc.content, tags_str)])
        self._docs[doc.id] = doc
        self._ensure_domain(doc.domain)
        self._domains[doc.domain].doc_count += 1
        logger.debug("added doc %s to domain %s", doc.id, doc.domain)
        return doc.id

    def get(self, doc_id: str) -> KnowledgeDoc | None:
        return self._docs.get(doc_id)

    def update(self, doc_id: str, **kwargs) -> bool:
        doc = self._docs.get(doc_id)
        if doc is None:
            return False
        for k, v in kwargs.items():
            if hasattr(doc, k) and k != "meta":
                setattr(doc, k, v)
        doc.updated_at = datetime.now(timezone.utc).isoformat()
        self._ensure_emb()
        tags_str = json.dumps(dict(doc.meta), ensure_ascii=False) if doc.meta else None
        self._emb.upsert([(doc.id, doc.content, tags_str)])
        return True

    def delete(self, doc_id: str) -> bool:
        doc = self._docs.pop(doc_id, None)
        if doc is None:
            return False
        if doc.domain in self._domains:
            self._domains[doc.domain].doc_count = max(0, self._domains[doc.domain].doc_count - 1)
        if self._emb:
            self._emb.delete([doc_id])
        return True

    def search(self, query: str, domain: str | None = None, top_k: int = 5) -> list[dict]:
        self._ensure_emb()
        if len(self._docs) == 0:
            return []
        results = self._emb.search(query, limit=max(top_k * 4, 20))
        out = []
        for r in results:
            doc_id = r["id"]
            doc = self._docs.get(doc_id)
            if doc is None:
                continue
            if domain and doc.domain != domain:
                continue
            out.append({
                "id": doc.id,
                "domain": doc.domain,
                "title": doc.title,
                "content": doc.content[:500],
                "score": round(r["score"], 4),
                "source": doc.source,
                "meta": dict(doc.meta),
            })
            if len(out) >= top_k:
                break
        return out

    def list_domains(self) -> list[dict]:
        return [
            {
                "path": d.path,
                "parent": d.parent,
                "description": d.description,
                "doc_count": d.doc_count,
            }
            for d in self._domains.values()
        ]

    def get_meta(self, doc_id: str) -> dict | None:
        doc = self._docs.get(doc_id)
        return doc.meta if doc else None

    def update_meta(self, doc_id: str, meta: dict) -> bool:
        doc = self._docs.get(doc_id)
        if doc is None:
            return False
        doc.meta.update(meta)
        doc.updated_at = _now_static()
        return True

    def save(self) -> None:
        import json as _json
        from pathlib import Path
        p = Path(self._storage_path)
        p.mkdir(parents=True, exist_ok=True)

        if self._emb:
            self._emb.save(str(self._storage_path))

        data = {
            "docs": {did: d.to_dict() for did, d in self._docs.items()},
            "domains": {
                dpath: {
                    "path": d.path,
                    "parent": d.parent,
                    "description": d.description,
                    "doc_count": d.doc_count,
                    "neighbors": d.neighbors,
                }
                for dpath, d in self._domains.items()
            },
        }
        (p / "kb.json").write_text(_json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def load(self) -> None:
        import json as _json
        from pathlib import Path

        p = Path(self._storage_path)

        config_path = p / "config"
        if config_path.exists():
            try:
                self._emb = Embeddings()
                self._emb.load(str(self._storage_path))
            except Exception:
                logger.exception("failed to load txtai from disk, rebuilding")
                if self._emb:
                    self._emb.close()
                self._emb = None

        kb_path = p / "kb.json"
        if not kb_path.exists():
            return
        data = _json.loads(kb_path.read_text(encoding="utf-8"))
        self._docs = {
            did: KnowledgeDoc.from_dict(d)
            for did, d in data.get("docs", {}).items()
        }
        self._domains = {}
        for dpath, d in data.get("domains", {}).items():
            self._domains[dpath] = KBDomain(
                path=d["path"],
                parent=d.get("parent"),
                description=d.get("description", ""),
                doc_count=d.get("doc_count", 0),
                neighbors=d.get("neighbors", {}),
            )
        if self._docs and self._emb is None:
            self._ensure_emb()
            for doc in self._docs.values():
                tags_str = _json.dumps(dict(doc.meta), ensure_ascii=False) if doc.meta else None
                self._emb.upsert([(doc.id, doc.content, tags_str)])

    def close(self):
        if self._emb:
            self._emb.close()
            self._emb = None

    def rename_domain(self, old_path: str, new_path: str) -> int:
        """Rename a domain and all its documents. Returns count of affected docs."""
        count = 0
        prefix = old_path + "/"
        for doc in list(self._docs.values()):
            if doc.domain == old_path or doc.domain.startswith(prefix):
                doc.domain = doc.domain.replace(old_path, new_path, 1)
                count += 1
        if old_path in self._domains:
            domain = self._domains.pop(old_path)
            domain.path = new_path
            parent = "/".join(new_path.split("/")[:-1]) or None
            domain.parent = parent
            self._domains[new_path] = domain
        return count

    def _ensure_domain(self, domain_path: str) -> KBDomain:
        if domain_path not in self._domains:
            parent = "/".join(domain_path.split("/")[:-1]) or None
            self._domains[domain_path] = KBDomain(
                path=domain_path,
                parent=parent,
            )
        return self._domains[domain_path]
