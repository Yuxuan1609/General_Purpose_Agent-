"""Shared model manager — singleton for embedding/tokenizer models.

Both KB and DomainRegistry use the same Embeddings instance to avoid
loading the ~600MB gemma model twice.
"""
from __future__ import annotations

_embedding_model = None
_model_path: str | None = None


def set_model_path(path: str) -> None:
    global _model_path
    _model_path = path


def get_model_path() -> str:
    from pathlib import Path
    return _model_path or str(Path(__file__).resolve().parent.parent / "embeddinggemma")


def get_embedding_model():
    """Return the shared Embeddings instance (lazy-load on first call)."""
    global _embedding_model
    if _embedding_model is not None:
        return _embedding_model
    from vendor.txtai_core.embeddings import Embeddings
    _embedding_model = Embeddings({
        "path": get_model_path(),
        "content": "memory",
        "trust_remote_code": True,
    })
    return _embedding_model
