"""Comm Agents — deterministic LayerMessage protocol handlers (A2).

UpwardComm:   handles communication with the layer above.
DownwardComm: handles communication with the layer below.

Both are deterministic — no LLM involvement. They only serialize/deserialize
LayerMessage envelopes, keeping Manager free of protocol concerns.
"""
from dataclasses import dataclass, field
from core.layer_message import LayerMessage, MessageType


@dataclass(frozen=True)
class AgentPacket:
    """Agent-level communication package (E3: immutable).

    Carried inside LayerMessage.payload. Each layer's Agent produces a
    JSON dict, which becomes the content field. Comm Agents wrap/unwrap
    AgentPacket into LayerMessage for transport.
    """
    source_layer: str
    message_type: str  # "query" | "response" | "notify"
    content: dict = field(default_factory=dict)


@dataclass(frozen=True)
class ReflectPacket:
    """Reflection-phase communication: Coordinator → ReflectionAgent.

    Per-layer customized packet: each layer receives its own NOTIFY data
    from the execute phase plus the Refiner's reasoning about this step.

    Distinct from AgentPacket (execute phase) and LayerMessage (transport).
    """
    record_id: str              # which execution record
    domain: str                 # domain for context
    target_layer: str           # "l0_5_1" | "l2" | "l3"
    refiner_reasoning: str      # why Refiner selected this step
    layer_notify: dict = field(default_factory=dict)  # this layer's execute NOTIFY
    issues: tuple = field(default_factory=tuple)       # pre-detected issues (optional)

    @property
    def issue_list(self) -> list[dict]:
        return list(self.issues)


class UpwardComm:
    """Handles QUERY reception from above and RESPONSE/NOTIFY send to above."""

    def receive(self, msg: LayerMessage) -> dict:
        """Unpack LayerMessage to business dict for Manager.Process()."""
        return msg.payload

    def wrap_response(self, payload, source: str, target: str,
                      trace_id: str, subtype: str = "") -> LayerMessage:
        return LayerMessage(
            source=source, target=target, type=MessageType.RESPONSE,
            payload=payload, trace_id=trace_id, subtype=subtype,
        )

    def wrap_notify(self, payload, source: str, target: str,
                    trace_id: str) -> LayerMessage:
        return LayerMessage(
            source=source, target=target, type=MessageType.NOTIFY,
            payload=payload, trace_id=trace_id,
        )


class DownwardComm:
    """Handles QUERY send to below and RESPONSE reception from below."""

    def receive(self, msg: LayerMessage) -> dict:
        """Unpack LayerMessage RESPONSE from below to business dict."""
        return msg.payload

    def wrap_query(self, payload, source: str, target: str,
                   trace_id: str, subtype: str = "") -> LayerMessage:
        return LayerMessage(
            source=source, target=target, type=MessageType.QUERY,
            payload=payload, trace_id=trace_id, subtype=subtype,
        )
