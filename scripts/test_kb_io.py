"""Quick KB I/O test — store 2 specs, verify retrieval and CRUD."""
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def main():
    from core.knowledge.models import KnowledgeDoc
    from core.knowledge.knowledge_base import KnowledgeBase

    kb = KnowledgeBase(storage_path=str(PROJECT_ROOT / "data" / "knowledge"))

    # ── Read 2 spec files ──
    specs = [
        ("2026-06-04-learning-env-design.md", "learning"),
        ("2026-06-06-capability-system-design.md", "architecture"),
    ]
    docs = []
    for filename, domain in specs:
        path = PROJECT_ROOT / "docs" / "superpowers" / "specs" / filename
        if not path.exists():
            print(f"SKIP: {filename} not found")
            continue
        content = path.read_text(encoding="utf-8")
        doc = KnowledgeDoc(
            domain=domain,
            title=filename.replace(".md", ""),
            content=content,
            content_type="markdown",
            source="test",
        )
        kb.add(doc)
        docs.append(doc)
        print(f"ADD: {filename} ({len(content)} chars) → domain={domain}")

    kb.save()
    print(f"\nStored {len(docs)} docs, saved to {kb._storage_path}")

    # ── Test retrieval ──
    for query, expected_domain in [
        ("learning environment design", "learning"),
        ("capability tool registry", "architecture"),
    ]:
        results = kb.search(query, top_k=2)
        print(f"\nSEARCH: '{query}' → {len(results)} results")
        for r in results:
            title = r.get("title", "?")
            score = r.get("score", 0)
            print(f"  [{r.get('domain', '?')}] {title} (score={score:.4f})")

    # ── Test get ──
    if docs:
        doc_id = docs[0].id
        fetched = kb.get(doc_id)
        if fetched:
            print(f"\nGET: id={doc_id} → title={fetched.title}")
        else:
            print(f"\nGET FAIL: id={doc_id}")

        # ── Test delete ──
        kb.delete(doc_id)
        fetched2 = kb.get(doc_id)
        print(f"DELETE: id={doc_id} → get={fetched2 is not None}")
        kb.save()

    print("\nKB I/O test complete!")


if __name__ == "__main__":
    main()
