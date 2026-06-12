"""CLI for static knowledge base management.
Usage: python -m core.knowledge.cli <command> [args]
"""
from __future__ import annotations
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.knowledge.knowledge_base import KnowledgeBase
from core.knowledge.models import KnowledgeDoc


def main():
    if len(sys.argv) < 2:
        print("Usage: python -m core.knowledge.cli <add|search|list|delete|import> [args]")
        sys.exit(1)

    kb = KnowledgeBase("data/knowledge")
    kb.load()
    cmd = sys.argv[1]

    if cmd == "add":
        if len(sys.argv) < 5:
            print("Usage: add <domain> <title> <file_path>")
            sys.exit(1)
        domain, title, filepath = sys.argv[2], sys.argv[3], sys.argv[4]
        content = Path(filepath).read_text(encoding="utf-8")
        doc = KnowledgeDoc(domain=domain, title=title, content=content, source="manual")
        kb.add(doc)
        kb.save()
        print(f"Added: {doc.id} ({title})")

    elif cmd == "search":
        query = sys.argv[2] if len(sys.argv) > 2 else ""
        results = kb.search(query)
        for r in results:
            print(f"[{r['domain']}] {r['title']} (score={r['score']})")

    elif cmd == "list":
        for d in kb.list_domains():
            print(f"  {d['path']}: {d['doc_count']} docs")

    elif cmd == "delete":
        if len(sys.argv) < 3:
            print("Usage: delete <doc_id>")
            sys.exit(1)
        kb.delete(sys.argv[2])
        kb.save()
        print(f"Deleted: {sys.argv[2]}")

    elif cmd == "import":
        if len(sys.argv) < 3:
            print("Usage: import <dir_path>")
            sys.exit(1)
        import_dir = Path(sys.argv[2])
        count = 0
        for md_file in import_dir.rglob("*.md"):
            rel = md_file.parent.relative_to(import_dir)
            domain = str(rel).replace("\\", "/").replace(" ", "_") or "root"
            title = md_file.stem
            content = md_file.read_text(encoding="utf-8")
            kb.add(KnowledgeDoc(domain=domain, title=title, content=content, source="import"))
            count += 1
        kb.save()
        print(f"Imported {count} docs from {sys.argv[2]}")


if __name__ == "__main__":
    main()
