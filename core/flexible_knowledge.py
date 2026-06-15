from __future__ import annotations
import json
import logging
import tempfile
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

RELATION_TYPES = ("parent_child", "cross_reference", "prerequisite", "analogous")


def _now():
    return datetime.now(timezone.utc)


def _days_since(dt: datetime) -> float:
    if dt is None:
        return 0
    return (_now() - dt).total_seconds() / 86400.0


@dataclass
class KnowledgeCard:
    id: str
    content: str
    domain: "Domain"
    available_domains: list[str] = field(default_factory=list)
    sub_tags: list[str] = field(default_factory=list)
    last_used: datetime = field(default_factory=_now)
    source: str = "observation"
    created_at: datetime = field(default_factory=_now)
    updated_at: datetime = field(default_factory=_now)
    usefulness: int = 0
    misleading: int = 0
    comment: str = ""

    def compute_activation(self, task_domain, task_context: str = "") -> float:
        return self._domain_match_score(task_domain)

    def _domain_match_score(self, task_domain) -> float:
        from core.task import Domain
        if self.domain.path == task_domain.path:
            return 1.0
        if task_domain.is_descendant_of(self.domain):
            return 0.7
        if self.domain.is_general:
            return 0.4
        if task_domain.parent and self.domain.path == task_domain.parent.path:
            return 0.7
        if self.domain.parent and self.domain.parent.path == task_domain.path:
            return 0.5
        return 0.0


class KnowledgeGraph:
    """Runtime graph built from l2_index.json relations."""

    def __init__(self, index: dict):
        self.adjacency: dict[str, list[tuple[str, str]]] = {}
        self._relation_weights = {
            "parent_child": 0.8,
            "cross_reference": 0.6,
            "prerequisite": 0.5,
            "analogous": 0.7,
        }
        for rel in index.get("relations", []):
            src = rel["from"]
            tgt = rel["to"]
            rtype = rel.get("type", "cross_reference")
            self.adjacency.setdefault(src, []).append((tgt, rtype))

    def get_adjacent(self, chapter_id: str) -> list[tuple[str, str]]:
        return self.adjacency.get(chapter_id, [])

    def spread_activation(self, seed_ids: list[str], steps: int = 2) -> dict[str, float]:
        scores = {sid: 1.0 for sid in seed_ids}
        current = set(seed_ids)
        decay = 0.5
        for _ in range(steps):
            next_wave = set()
            for node in current:
                for neighbor, rtype in self.get_adjacent(node):
                    if neighbor not in scores:
                        weight = self._relation_weights.get(rtype, 0.5)
                        scores[neighbor] = scores[node] * weight * decay
                        next_wave.add(neighbor)
            current = next_wave
        return scores


class FlexibleKnowledge:
    """L2: Flexible knowledge. Stores cards in memory, persists via MD+JSON+Graph."""

    def __init__(self, knowledge_dir: Path, index_path: Path,
                 domain_registry=None, db_path: Path | None = None):
        self.knowledge_dir = Path(knowledge_dir)
        self.index_path = Path(index_path)
        self.knowledge_dir.mkdir(parents=True, exist_ok=True)
        self.graph: KnowledgeGraph | None = None
        self._registry = domain_registry
        self._db = None
        if db_path:
            from core.storage.l2_store import L2SQLiteStore
            self._db = L2SQLiteStore(db_path)
            self.cards: list[KnowledgeCard] = self._load_cards_from_db()
        else:
            self.cards: list[KnowledgeCard] = self._load_cards_from_files()
        self._load_index()

    def get_active_cards(self, task_domain, task_context: str = "", top_k: int = 5) -> list[KnowledgeCard]:
        scored = []
        for card in self.cards:
            act = card.compute_activation(task_domain, task_context)
            if act > 0:
                scored.append((act, card))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [c for _, c in scored[:top_k]]

    def get_domain_cards(self, domain) -> list[KnowledgeCard]:
        result = []
        for card in self.cards:
            if card.domain.path == domain.path or card.domain.path.startswith(domain.path + "/"):
                result.append(card)
        return result

    def _load_cards_from_files(self) -> list[KnowledgeCard]:
        return []

    def _load_cards_from_db(self) -> list[KnowledgeCard]:
        from core.task import Domain
        cards = []
        for row in self._db.list_all():
            domain_path = row.get("domain", "general")
            domain = Domain(domain_path, "general" if "/" not in domain_path else "specific")
            cards.append(KnowledgeCard(
                id=row["id"],
                content=row["content"],
                domain=domain,
                available_domains=row.get("available_domains", []),
                sub_tags=row.get("sub_tags", []),
                source=row.get("source", "observation"),
                created_at=datetime.fromisoformat(row["created_at"]),
                updated_at=datetime.fromisoformat(row["updated_at"]),
                last_used=datetime.fromisoformat(row["last_used"]),
                usefulness=row.get("usefulness", 0),
                misleading=row.get("misleading", 0),
                comment=row.get("comment", ""),
            ))
        return cards

    def add_card(self, content: str, domain, sub_tags: list[str] | None = None,
                 source: str = "observation",
                 available_domains: list[str] | None = None) -> KnowledgeCard:
        if available_domains is None:
            available_domains = [domain.path]
        card = KnowledgeCard(
            id=f"card_{uuid.uuid4().hex[:8]}",
            content=content,
            domain=domain,
            available_domains=available_domains,
            sub_tags=sub_tags or [],
            source=source,
        )
        self.cards.append(card)
        self._sync_card_index(card)
        if self._db:
            self._db.insert({
                "id": card.id,
                "content": card.content,
                "domain": card.domain.path,
                "available_domains": card.available_domains,
                "sub_tags": card.sub_tags,
                "source": card.source,
                "created_at": card.created_at.isoformat(),
                "updated_at": card.updated_at.isoformat(),
                "last_used": card.last_used.isoformat(),
                "usefulness": card.usefulness,
                "misleading": card.misleading,
                "comment": card.comment,
            })
        return card

    def _sync_card_index(self, card) -> None:
        if self._registry is None:
            return
        for d in card.available_domains:
            self._registry.index_item("l2", d, card.id)

    def _unsync_card_index(self, card_id: str) -> None:
        if self._registry is None:
            return
        idx = self._registry._reverse_index.get("l2", {})
        for d, ids in idx.items():
            if card_id in ids:
                ids.remove(card_id)

    def remove_card(self, card_id: str) -> bool:
        """Remove a knowledge card by id. Returns True if found and removed."""
        for i, c in enumerate(self.cards):
            if c.id == card_id:
                self._unsync_card_index(card_id)
                self.cards.pop(i)
                if self._db:
                    self._db.delete(card_id)
                return True
        return False

    def modify_card(self, card_id: str, new_content: str | None = None,
                    usefulness: int | None = None,
                    misleading: int | None = None,
                    comment: str | None = None) -> KnowledgeCard | None:
        """Modify a card's content and/or quality fields by id."""
        for c in self.cards:
            if c.id == card_id:
                if new_content is not None:
                    c.content = new_content
                if usefulness is not None:
                    c.usefulness = usefulness
                if misleading is not None:
                    c.misleading = misleading
                if comment is not None:
                    c.comment = comment
                c.updated_at = _now()
                if self._db:
                    fields = {}
                    if new_content is not None:
                        fields["content"] = new_content
                    if usefulness is not None:
                        fields["usefulness"] = usefulness
                    if misleading is not None:
                        fields["misleading"] = misleading
                    if comment is not None:
                        fields["comment"] = comment
                    if fields:
                        self._db.update(card_id, **fields)
                return c
        return None

    def update_from_tool_results(self, task, results: list):
        for name, result_str in results:
            success = "error" not in str(result_str).lower()
            for card in self.get_active_cards(task.domain, "", top_k=5):
                card.last_used = _now()
                card.updated_at = _now()
                if success:
                    card.usefulness += 1
                else:
                    card.misleading += 1

    def apply_updates(self, updates: list, domain):
        for update in updates:
            self.add_card(
                content=update.get("content", ""),
                domain=domain,
                source=update.get("source", "reflection"),
            )

    def add_failed_proposal_record(self, proposal):
        self.add_card(
            content=f"L1 proposal rejected: {getattr(proposal, 'content', str(proposal))[:80]}",
            domain=getattr(proposal, 'domain', 'general'),
            source="reflection_rejected",
        )

    def run_decay_cycle(self):
        # No-op: confidence/activation/decay fields removed.
        # Quality tracking is now handled by usefulness/misleading via modify tools.
        pass

    def domain_stats(self, domain) -> dict:
        cards = [c for c in self.cards
                 if c.domain.path == domain.path or c.domain.path.startswith(domain.path + "/")]
        if not cards:
            return {"count": 0}
        return {
            "count": len(cards),
        }

    def _write_md(self, domain, filename: str, content: str) -> Path:
        domain_dir = self.knowledge_dir / domain.path
        domain_dir.mkdir(parents=True, exist_ok=True)
        md_path = domain_dir / filename
        fd, tmp = tempfile.mkstemp(dir=domain_dir, suffix=".md")
        try:
            with open(fd, "w", encoding="utf-8") as f:
                f.write(content)
            Path(tmp).replace(md_path)
        finally:
            Path(tmp).unlink(missing_ok=True)
        return md_path

    def _rebuild_index(self):
        chapters = []
        existing_ids = set()
        for md_file in sorted(self.knowledge_dir.rglob("*.md")):
            if md_file.name == "l2_index.json" or md_file.parent == self.index_path.parent and md_file.name == self.index_path.name:
                continue
            rel = md_file.relative_to(self.knowledge_dir)
            domain_path = str(rel.parent) if str(rel.parent) != "." else "general"
            chapter_id = str(rel.with_suffix("")).replace("\\", "/")
            content = md_file.read_text(encoding="utf-8")
            title = ""
            sections = []
            for line in content.split("\n"):
                if line.startswith("# ") and not line.startswith("## "):
                    title = line.lstrip("# ").strip()
                elif line.startswith("## "):
                    heading = line.lstrip("# ").strip()
                    sections.append({
                        "heading": heading,
                        "summary": heading,
                        "keywords": [],
                    })
            if title:
                chapters.append({
                    "id": chapter_id,
                    "title": title,
                    "domain": domain_path,
                    "source_file": str(md_file),
                    "sections": sections,
                })
                existing_ids.add(chapter_id)

        old_index = {}
        if self.index_path.exists():
            try:
                old_index = json.loads(self.index_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                pass

        old_relations = old_index.get("relations", [])
        new_relations = [r for r in old_relations
                         if r.get("from") in existing_ids and r.get("to") in existing_ids]

        new_index = {
            "version": old_index.get("version", 1) + 1,
            "updated_at": _now().isoformat(),
            "chapters": chapters,
            "relations": new_relations,
        }
        fd, tmp = tempfile.mkstemp(dir=self.index_path.parent, suffix=".json")
        try:
            with open(fd, "w", encoding="utf-8") as f:
                json.dump(new_index, f, ensure_ascii=True, indent=2)
            Path(tmp).replace(self.index_path)
        finally:
            Path(tmp).unlink(missing_ok=True)

    def _load_index(self):
        if self.index_path.exists():
            try:
                index = json.loads(self.index_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                index = {"version": 1, "chapters": [], "relations": []}
        else:
            index = {"version": 1, "chapters": [], "relations": []}
        self.graph = KnowledgeGraph(index)
