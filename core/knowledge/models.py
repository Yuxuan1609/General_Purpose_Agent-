# core/knowledge/models.py
from __future__ import annotations
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _uid() -> str:
    return uuid.uuid4().hex[:8]


_gemma_tokenizer = None


def _get_tokenizer():
    global _gemma_tokenizer
    if _gemma_tokenizer is None:
        from transformers import AutoTokenizer
        _gemma_tokenizer = AutoTokenizer.from_pretrained(
            "C:/Users/micha/PycharmProjects/cognitive-agent/embeddinggemma"
        )
    return _gemma_tokenizer


def _count_tokens(text: str) -> int:
    return len(_get_tokenizer().encode(text))


@dataclass
class KnowledgeDoc:
    id: str = field(default_factory=_uid)
    domain: str = ""
    title: str = ""
    content: str = ""
    content_type: str = "markdown"
    source: str = "manual"
    meta: dict = field(default_factory=dict)
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
            "meta": self.meta,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> KnowledgeDoc:
        obj = cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})
        obj.meta.pop("id", None)
        return obj


@dataclass
class KBDomain:
    path: str
    parent: str | None = None
    description: str = ""
    doc_count: int = 0
    neighbors: dict[str, float] = field(default_factory=dict)
