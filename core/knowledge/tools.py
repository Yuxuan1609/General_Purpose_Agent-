"""Tool handlers for knowledge_* operations. Each returns a JSON string."""
from __future__ import annotations
import json
from core.knowledge.models import KnowledgeDoc


def knowledge_query(kb, query: str, domain: str | None = None,
                   search_type: str = "keyword", top_k: int = 5) -> str:
    results = kb.search(query, domain=domain, top_k=top_k)
    return json.dumps({"results": results}, ensure_ascii=False)


def knowledge_add(kb, domain: str, title: str, content: str,
                  meta: dict | None = None, source: str = "agent") -> str:
    doc = KnowledgeDoc(domain=domain, title=title, content=content,
                       meta=meta or {}, source=source)
    kb.add(doc)
    kb.save()
    return json.dumps({"status": "ok", "doc_id": doc.id}, ensure_ascii=False)


def knowledge_update(kb, doc_id: str, content: str | None = None,
                     title: str | None = None, meta: dict | None = None) -> str:
    kwargs = {}
    if content is not None:
        kwargs["content"] = content
    if title is not None:
        kwargs["title"] = title
    ok = kb.update(doc_id, **kwargs)
    if ok and meta:
        kb.update_meta(doc_id, meta)
    if ok:
        kb.save()
    return json.dumps({"status": "ok" if ok else "not_found"}, ensure_ascii=False)


def knowledge_delete(kb, doc_id: str) -> str:
    kb.delete(doc_id)
    kb.save()
    return json.dumps({"status": "ok"}, ensure_ascii=False)


def knowledge_get(kb, doc_id: str) -> str:
    doc = kb.get(doc_id)
    if doc is None:
        return json.dumps({"status": "not_found"}, ensure_ascii=False)
    return json.dumps({"status": "ok", "doc": doc.to_dict()}, ensure_ascii=False)


def knowledge_list_domains(kb, parent: str | None = None) -> str:
    domains = kb.list_domains()
    if parent:
        prefix = parent.rstrip("/") + "/"
        domains = [d for d in domains if d["path"].startswith(prefix)]
    return json.dumps({"domains": domains}, ensure_ascii=False)


def knowledge_sync_domain(kb, action: str, source_domain: str,
                           target_domain: str = "") -> str:
    if action == "rename":
        if not target_domain:
            return json.dumps({"status": "error", "reason": "target_domain required"}, ensure_ascii=False)
        kb.rename_domain(source_domain, target_domain)
        kb.save()
        return json.dumps({"status": "ok"}, ensure_ascii=False)
    elif action == "list":
        return json.dumps({"domains": kb.list_domains()}, ensure_ascii=False)
    else:
        return json.dumps({"status": "error", "reason": f"unknown action: {action}"}, ensure_ascii=False)
