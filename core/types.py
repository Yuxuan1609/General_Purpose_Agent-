from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any


@dataclass
class TaskObservation:
    """Environment observation consumed by all cognitive layers.

    Fields:
        meta:    Task metadata (role, goal, domain). Populated by comm layer.
                 Layers append their enrichment to meta during chain processing.
        state:   Task-specific state (game board, code context, search results).
                 Populated by comm layer.
        history: Past interactions. None = history not needed for this task type.
                 When present, already trimmed by comm layer.
        session: Session context {id, datetime, task_type, meta_hash}.
                 Populated by comm layer. Used by learning pipeline.
    """
    meta: dict = field(default_factory=dict)
    state: dict = field(default_factory=dict)
    history: list | None = None
    session: dict | None = None


@dataclass
class ExecutionRecord:
    """Archive produced by Executor after each execute cycle.

    Used for the learning pipeline: written to data/learning/pending/,
    moved to data/learning/learned/{domain}/ after reflection.
    """
    session: dict = field(default_factory=dict)        # {id, datetime, meta_hash}
    observation: dict = field(default_factory=dict)     # raw TaskObservation
    notify_layers: dict = field(default_factory=dict)   # {layer_name: notify_payload}
    action: Any = None                                  # final action returned to env
    result: Any = None                                  # env reward/outcome
