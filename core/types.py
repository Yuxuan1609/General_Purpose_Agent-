from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any


@dataclass
class TaskObservation:
    """Environment observation consumed by all cognitive layers.

    Fields:
        meta:    Natural language task description (what to do, goal).
                 Populated by comm layer.
        state:   Task-specific state. Keys: "current" (str, current situation),
                 "history" (str, past context). Populated by comm layer.
        session: Session context {id, domain, step_index, ...}.
                 Populated by comm layer. Used by learning pipeline.
    """
    meta: str = ""
    state: dict = field(default_factory=dict)
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
