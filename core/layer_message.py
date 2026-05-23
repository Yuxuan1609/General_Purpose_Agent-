from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class MessageType(Enum):
    QUERY = "QUERY"
    RESPONSE = "RESPONSE"
    PROPOSAL = "PROPOSAL"
    APPROVAL = "APPROVAL"
    REJECTION = "REJECTION"
    NOTIFY = "NOTIFY"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class LayerMessage:
    source: str
    target: str
    type: MessageType
    payload: Any
    trace_id: str
    subtype: str = ""
    timestamp: datetime = field(default_factory=_utc_now)
    metadata: dict = field(default_factory=dict)
