# core/knowledge/models.py
from __future__ import annotations
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _uid() -> str:
    return uuid.uuid4().hex[:8]


@dataclass
class KnowledgeDoc:
    id: str = field(default_factory=_uid)
    domain: str = ""
    title: str = ""
    content: str = ""
    content_type: str = "markdown"
    source: str = "manual"
    tags: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "domain": self.domain,
            "title": self.title,
            "content": self.content,
            "content_type": self.content_type,
            "source": self.source,
            "tags": self.tags,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> KnowledgeDoc:
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class KBDomain:
    path: str
    parent: str | None = None
    description: str = ""
    doc_count: int = 0
    neighbors: dict[str, float] = field(default_factory=dict)
