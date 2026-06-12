"""Tool handlers for knowledge_* operations. Each returns a JSON string."""
from __future__ import annotations
import json
from core.knowledge.models import KnowledgeDoc


def knowledge_query(kb, query: str, domain: str | None = None,
                   search_type: str = "keyword", top_k: int = 5) -> str:
    results = kb.search(query, domain=domain, top_k=top_k)
    return json.dumps({"results": results}, ensure_ascii=False)


def knowledge_add(kb, domain: str, title: str, content: str,
                  tags: list | None = None, source: str = "agent") -> str:
    doc = KnowledgeDoc(
        domain=domain,
        title=title,
        content=content,
        tags=tags or [],
        source=source,
    )
    kb.add(doc)
    kb.save()
    return json.dumps({"status": "ok", "doc_id": doc.id}, ensure_ascii=False)


def knowledge_update(kb, doc_id: str, content: str | None = None,
                     title: str | None = None, tags: list | None = None) -> str:
    kwargs = {}
    if content is not None:
        kwargs["content"] = content
    if title is not None:
        kwargs["title"] = title
    if tags is not None:
        kwargs["tags"] = tags
    ok = kb.update(doc_id, **kwargs)
    if ok:
        kb.save()
    return json.dumps({"status": "ok" if ok else "not_found"}, ensure_ascii=False)


def knowledge_delete(kb, doc_id: str) -> str:
    kb.delete(doc_id)
    kb.save()
    return json.dumps({"status": "ok"}, ensure_ascii=False)
