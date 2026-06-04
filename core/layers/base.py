from __future__ import annotations
import json
import logging
from abc import ABC, abstractmethod
from typing import Any

from core.layer_message import LayerMessage, MessageType
from core.layers.comm import UpwardComm, DownwardComm


class ReflectionAgent(ABC):
    """Phase 2: Per-layer reflection coordinator for recursive problem attribution.

    Each layer's ReflectionAgent:
      - investigate(issues, context) → attributs problems to self vs downstream
      - fix(my_issues) → repairs confirmed problems via Manager.apply_update()
      - query_downstream(issues, context) → delegates investigation to lower layer

    Communication uses the same chain pattern as Execute (QUERY→RESPONSE via
    downstream ReflectionAgent reference), not LayerMessage.
    """

    def __init__(self, layer_name: str, manager,
                 downstream: "ReflectionAgent | None" = None):
        self._name = layer_name
        self._manager = manager
        self._downstream = downstream
        self._log = logging.getLogger(f"{layer_name}_reflect")

    @abstractmethod
    def investigate(self, issues: list[dict], context: dict) -> dict:
        """Determine which issues belong to this layer.

        Returns:
            {"my_issues": [...], "downstream_issues": [...], "actions": [...]}
        """
        ...

    @abstractmethod
    def fix(self, my_issues: list[dict]) -> dict:
        """Repair confirmed issues via Manager.apply_update().

        Returns:
            {"fixes_applied": int, "details": [...]}
        """
        ...

    def query_downstream(self, issues: list[dict], context: dict) -> dict:
        """Delegate investigation to downstream ReflectionAgent."""
        if self._downstream:
            self._log.debug("  ═══ cascading %d issues → %s ═══",
                           len(issues), self._downstream._name)
            result = self._downstream.investigate(issues, context)
            self._log.debug("  cascade result: my=%d downstream=%d",
                           len(result.get("my_issues", [])),
                           len(result.get("downstream_issues", [])))
            return result
        return {"my_issues": [], "downstream_issues": []}


def _indent(text: str, spaces: int) -> str:
    prefix = " " * spaces
    return prefix + text.replace("\n", "\n" + prefix)


class LayerAgent(ABC):
    """Common base for all layer LLM agents.

    Provides _call_llm() with DeepSeek JSON mode + full prompt/response logging.
    Output is always a parsed JSON dict.
    """

    def __init__(self, llm_client, log: logging.Logger):
        self._llm = llm_client
        self._log = log

    def _call_llm(self, system: str, user: str,
                  schema: dict | None = None) -> dict:
        """Call LLM, return parsed JSON dict.

        When schema is given, enables DeepSeek response_format={'type':'json_object'}
        and injects the schema example into the system prompt (per official requirement:
        include "json" word + example format).
        """
        if schema:
            schema_text = json.dumps(schema, ensure_ascii=False, indent=2)
            system = (
                f"{system}\n\n"
                f"请以 JSON 格式输出，严格遵循以下结构：\n"
                f"```json\n{schema_text}\n```"
            )

        self._log.debug("  system:\n%s", _indent(system, 4))
        self._log.debug("  user:\n%s", _indent(user, 4))

        resp = self._llm.chat(
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            json_mode=bool(schema),
        )
        text = resp.text if hasattr(resp, 'text') else str(resp)
        self._log.debug("  response:\n%s", _indent(text, 4))

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            self._log.warning("JSON parse failed, raw text returned")
            return {"_raw": text}


class LayerManager(ABC):
    """Abstract base for all layer Manager agents.

    Each Manager:
      - process(data) → enriches data with its layer's information → returns status
      - notify() → returns this layer's NOTIFY payload (business dict)
      - query() → handles LayerMessage QUERY chain top-down (uses Comm Agents)
      - collect_notify() → gathers NOTIFY payloads bottom-up

    Manager only deals with business dicts. Comm Agents handle LayerMessage wrapping.
    """

    def __init__(self, name: str, downstream: LayerManager | None = None,
                 upward: UpwardComm | None = None,
                 downward: DownwardComm | None = None):
        self.name = name
        self._downstream = downstream
        self._upward = upward or UpwardComm()
        self._downward = downward or DownwardComm()

    @abstractmethod
    def process(self, data: Any) -> dict:
        """Enrich data with this layer's information.

        Returns a dict with status info.
        Must update `data` in-place with layer-specific fields.
        """
        ...

    @abstractmethod
    def notify(self) -> Any:
        """Return the payload for this layer's NOTIFY to the Executor."""
        ...

    @abstractmethod
    def apply_update(self, key: str, value: Any) -> None:
        """Phase 2: Apply a fix from ReflectionAgent to this layer's data.

        Called by ReflectionAgent.fix() to write back repaired data.
        Implementation is layer-specific (rule CRUD, card boost/penalize, skill update).
        """
        ...

    def query(self, msg: LayerMessage | Any, trace_id: str = "") -> None:
        """Entry point: unpack LayerMessage, process, propagate downstream.

        Accepts LayerMessage (from Executor or upper layer) or raw dict
        (backward compat). If LayerMessage, unpacks via UpwardComm.
        """
        if isinstance(msg, LayerMessage):
            data = self._upward.receive(msg)
            if not trace_id:
                trace_id = msg.trace_id
        else:
            data = msg

        self.process(data)

        if self._downstream:
            q_msg = self._downward.wrap_query(
                payload=data,
                source=self.name,
                target=self._downstream.name,
                trace_id=trace_id,
            )
            self._downstream.query(q_msg, trace_id)

    def collect_notify(self) -> dict:
        """Collect NOTIFY payloads from this layer and all downstream.

        Returns business dicts: {layer_name: notify_payload, ...}
        """
        result: dict = {}
        result[self.name] = self.notify()
        if self._downstream:
            result.update(self._downstream.collect_notify())
        return result
