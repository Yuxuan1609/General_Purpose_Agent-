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
    sub_tags: list[str] = field(default_factory=list)
    confidence: float = 0.5
    activation: float = 0.5
    last_used: datetime = field(default_factory=_now)
    decay_rate: float = 0.01
    source: str = "observation"
    success_count: int = 0
    failure_count: int = 0
    created_at: datetime = field(default_factory=_now)
    updated_at: datetime = field(default_factory=_now)
    marker: str = ""

    def __post_init__(self):
        if self.activation == 0.5 and self.confidence != 0.5:
            self.activation = self.confidence

    def compute_activation(self, task_domain, task_context: str = "") -> float:
        domain_score = self._domain_match_score(task_domain)
        if domain_score == 0.0:
            return 0.0
        recency_score = max(0, 1.0 - _days_since(self.last_used) * 0.1)
        return min(1.0, self.confidence * (domain_score * 0.6 + recency_score * 0.4))

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

    def boost(self):
        self.confidence = min(1.0, self.confidence + 0.05)
        self.success_count += 1
        self.activation = min(1.0, self.activation + 0.1)
        self.last_used = _now()
        self.updated_at = _now()

    def penalize(self):
        self.confidence = max(0.1, self.confidence - 0.1)
        self.failure_count += 1
        self.updated_at = _now()

    def apply_decay(self):
        days = _days_since(self.last_used)
        self.activation *= (1 - self.decay_rate) ** days
        self.updated_at = _now()


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

    def __init__(self, knowledge_dir: Path, index_path: Path):
        self.knowledge_dir = Path(knowledge_dir)
        self.index_path = Path(index_path)
        self.knowledge_dir.mkdir(parents=True, exist_ok=True)
        self.cards: list[KnowledgeCard] = []
        self.graph: KnowledgeGraph | None = None
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

    def add_card(self, content: str, domain, sub_tags: list[str] | None = None,
                 confidence: float = 0.5, source: str = "observation") -> KnowledgeCard:
        card = KnowledgeCard(
            id=f"card_{uuid.uuid4().hex[:8]}",
            content=content,
            domain=domain,
            sub_tags=sub_tags or [],
            confidence=confidence,
            activation=confidence,
            source=source,
        )
        self.cards.append(card)
        return card

    def remove_card(self, card_id: str) -> bool:
        """Remove a knowledge card by id. Returns True if found and removed."""
        for i, c in enumerate(self.cards):
            if c.id == card_id:
                self.cards.pop(i)
                return True
        return False

    def modify_card(self, card_id: str, new_content: str) -> KnowledgeCard | None:
        """Modify a card's content by id. Returns the updated card or None."""
        for c in self.cards:
            if c.id == card_id:
                c.content = new_content
                c.updated_at = _now()
                return c
        return None

    def update_from_tool_results(self, task, results: list):
        for name, result_str in results:
            success = "error" not in str(result_str).lower()
            for card in self.get_active_cards(task.domain, "", top_k=5):
                if success:
                    card.boost()
                else:
                    card.penalize()

    def apply_updates(self, updates: list, domain):
        for update in updates:
            self.add_card(
                content=update.get("content", ""),
                domain=domain,
                confidence=update.get("confidence", 0.5),
                source=update.get("source", "reflection"),
            )

    def add_failed_proposal_record(self, proposal):
        self.add_card(
            content=f"L1 proposal rejected: {getattr(proposal, 'content', str(proposal))[:80]}",
            domain=getattr(proposal, 'domain', 'general'),
            confidence=0.3,
            source="reflection_rejected",
        )

    def run_decay_cycle(self):
        for card in self.cards:
            card.apply_decay()

    def domain_stats(self, domain) -> dict:
        cards = [c for c in self.cards
                 if c.domain.path == domain.path or c.domain.path.startswith(domain.path + "/")]
        if not cards:
            return {"count": 0, "avg_activation": 0.0, "avg_confidence": 0.0}
        return {
            "count": len(cards),
            "avg_activation": sum(c.activation for c in cards) / len(cards),
            "avg_confidence": sum(c.confidence for c in cards) / len(cards),
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
