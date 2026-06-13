"""Load spec docs into KB and test CRUD + search."""
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.knowledge.knowledge_base import KnowledgeBase
from core.knowledge.models import KnowledgeDoc
from core.knowledge.tools import (
    knowledge_add, knowledge_query, knowledge_get,
    knowledge_update, knowledge_delete, knowledge_list_domains, knowledge_sync_domain,
)

SPEC_DIR = PROJECT_ROOT / "docs" / "superpowers" / "specs"

kb = KnowledgeBase("data/knowledge_test")
kb.load()

print("=== 1. Import spec docs ===")
count = 0
for md_file in sorted(SPEC_DIR.glob("*.md")):
    content = md_file.read_text(encoding="utf-8")
    title = md_file.stem
    r = json.loads(knowledge_add(kb,
        domain="docs/superpowers/specs",
        title=title,
        content=content,
        meta={"type": "reference", "source_file": md_file.name},
        source="import",
    ))
    if r["status"] == "ok":
        count += 1
        print(f"  OK: {title} → {r['doc_id']}")
    else:
        print(f"  FAIL: {title}")
print(f"  Total: {count} docs imported\n")

print("=== 2. List domains ===")
r = json.loads(knowledge_list_domains(kb))
for d in r["domains"]:
    print(f"  {d['path']}: {d['doc_count']} docs")
print()

print("=== 3. Search: 'agent communication' ===")
r = json.loads(knowledge_query(kb, query="agent communication", top_k=3))
for doc in r["results"]:
    print(f"  [{doc['domain']}] {doc['title']} (score={doc['score']})")
print()

print("=== 4. Search: '工具 fallback 超时' ===")
r = json.loads(knowledge_query(kb, query="工具 fallback 超时", top_k=3))
for doc in r["results"]:
    print(f"  [{doc['domain']}] {doc['title']} (score={doc['score']})")
print()

print("=== 5. Get full doc + meta ===")
r = json.loads(knowledge_query(kb, query="domain system", top_k=1))
if r["results"]:
    doc_id = r["results"][0]["id"]
    r2 = json.loads(knowledge_get(kb, doc_id=doc_id))
    doc = r2["doc"]
    print(f"  Title: {doc['title']}")
    print(f"  Content[:100]: {doc['content'][:100]}...")
    print(f"  Meta: {doc['meta']}")
print()

print("=== 6. Update meta on a doc ===")
r = json.loads(knowledge_query(kb, query="learning env", top_k=1))
if r["results"]:
    doc_id = r["results"][0]["id"]
    r2 = json.loads(knowledge_update(kb, doc_id=doc_id, meta={"level": "advanced", "tags": ["learning", "env"]}))
    print(f"  Update: {r2['status']}")
    r3 = json.loads(knowledge_get(kb, doc_id=doc_id))
    print(f"  Updated meta: {r3['doc']['meta']}")
print()

print("=== 7. Delete and verify ===")
r = json.loads(knowledge_query(kb, query="env agent boundary", top_k=1))
if r["results"]:
    doc_id = r["results"][0]["id"]
    title = r["results"][0]["title"]
    r2 = json.loads(knowledge_delete(kb, doc_id=doc_id))
    print(f"  Deleted: {title} → {r2['status']}")
    r3 = json.loads(knowledge_get(kb, doc_id=doc_id))
    print(f"  Verify gone: {r3['status']}")

print("\n=== 8. Save/Load roundtrip ===")
kb.save()
print(f"  Saved to {kb._storage_path}/")

kb2 = KnowledgeBase("data/knowledge_test")
kb2.load()
r = json.loads(knowledge_list_domains(kb2))
print(f"  Domains after reload: {len(r['domains'])}")
for d in r["domains"]:
    print(f"    {d['path']}: {d['doc_count']} docs")

r = json.loads(knowledge_query(kb2, query="agent communication", top_k=2))
print(f"  Search after reload: {len(r['results'])} results")
for doc in r["results"]:
    print(f"    [{doc['domain']}] {doc['title']} (score={doc['score']})")

import shutil
shutil.rmtree("data/knowledge_test", ignore_errors=True)

print("\n=== DONE ===")
