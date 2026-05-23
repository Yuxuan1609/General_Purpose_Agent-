import pytest
from datetime import datetime
from core.layer_message import LayerMessage, MessageType


class TestMessageType:
    def test_message_type_values(self):
        assert MessageType.QUERY.value == "QUERY"
        assert MessageType.RESPONSE.value == "RESPONSE"
        assert MessageType.PROPOSAL.value == "PROPOSAL"
        assert MessageType.APPROVAL.value == "APPROVAL"
        assert MessageType.REJECTION.value == "REJECTION"
        assert MessageType.NOTIFY.value == "NOTIFY"


class TestLayerMessage:
    def test_create_query_message(self):
        msg = LayerMessage(
            source="L1",
            target="L2",
            type=MessageType.QUERY,
            payload={"request": "get_active_cards"},
            trace_id="task-42",
            timestamp=datetime(2026, 1, 1),
        )
        assert msg.source == "L1"
        assert msg.target == "L2"
        assert msg.type == MessageType.QUERY
        assert msg.subtype == ""
        assert msg.payload == {"request": "get_active_cards"}
        assert msg.trace_id == "task-42"

    def test_create_with_subtype(self):
        msg = LayerMessage(
            source="L2",
            target="L3",
            type=MessageType.PROPOSAL,
            subtype="L2_to_L3:COMPILATION_SIGNAL",
            payload={"cards": 5},
            trace_id="task-42",
        )
        assert msg.subtype == "L2_to_L3:COMPILATION_SIGNAL"

    def test_frozen_immutable(self):
        msg = LayerMessage(
            source="L1", target="L2", type=MessageType.NOTIFY,
            payload="test", trace_id="t1",
        )
        with pytest.raises(Exception):
            msg.source = "L3"

    def test_default_values(self):
        msg = LayerMessage(
            source="ORCHESTRATOR",
            target="L1",
            type=MessageType.NOTIFY,
            payload=None,
            trace_id="t1",
        )
        assert msg.subtype == ""
        assert isinstance(msg.timestamp, datetime)
        assert msg.metadata == {}

    def test_metadata_extension(self):
        msg = LayerMessage(
            source="L1", target="L0.5", type=MessageType.PROPOSAL,
            payload={"rule": "new rule"},
            trace_id="t1",
            metadata={"priority": "high", "ttl": 5},
        )
        assert msg.metadata["priority"] == "high"
