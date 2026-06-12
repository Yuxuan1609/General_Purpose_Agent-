# core/knowledge/knowledge_base.py
from __future__ import annotations
import json
import logging
from datetime import datetime, timezone
from typing import Any

from core.knowledge.models import KnowledgeDoc, KBDomain

logger = logging.getLogger("knowledge_base")


class KnowledgeBase:
    """Static knowledge base backed by in-memory dicts.

    Provides CRUD operations and search over KnowledgeDoc entries.
    Domain graph is maintained alongside documents.
    """

    def __init__(self, storage_path: str = "data/knowledge"):
        self._storage_path = storage_path
        self._docs: dict[str, KnowledgeDoc] = {}
        self._domains: dict[str, KBDomain] = {}

    def add(self, doc: KnowledgeDoc) -> str:
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
            if hasattr(doc, k):
                setattr(doc, k, v)
        doc.updated_at = datetime.now(timezone.utc).isoformat()
        return True

    def delete(self, doc_id: str) -> bool:
        doc = self._docs.pop(doc_id, None)
        if doc and doc.domain in self._domains:
            self._domains[doc.domain].doc_count = max(0, self._domains[doc.domain].doc_count - 1)
        return doc is not None

    def search(self, query: str, domain: str | None = None, top_k: int = 5) -> list[dict]:
        results = []
        for doc in self._docs.values():
            if domain and doc.domain != domain:
                continue
            score = self._keyword_score(query, doc)
            if score > 0:
                results.append({
                    "id": doc.id,
                    "domain": doc.domain,
                    "title": doc.title,
                    "content": doc.content[:500],
                    "score": round(score, 4),
                    "source": doc.source,
                    "tags": doc.tags,
                })
        results.sort(key=lambda r: r["score"], reverse=True)
        return results[:top_k]

    @staticmethod
    def _keyword_score(query: str, doc: KnowledgeDoc) -> float:
        q = query.lower()
        score = 0.0
        if q in doc.title.lower():
            score += 1.0
        if q in doc.content.lower():
            score += 0.5
        for tag in doc.tags:
            if q in tag.lower():
                score += 0.3
        return score

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

    def _ensure_domain(self, domain_path: str) -> KBDomain:
        if domain_path not in self._domains:
            parent = "/".join(domain_path.split("/")[:-1]) or None
            self._domains[domain_path] = KBDomain(
                path=domain_path,
                parent=parent,
            )
        return self._domains[domain_path]
