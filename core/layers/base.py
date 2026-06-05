from __future__ import annotations
import json
import logging
from abc import ABC, abstractmethod
from typing import Any

from core.layer_message import LayerMessage
from core.layers.comm import UpwardComm, DownwardComm


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

        self._log.debug("  ── system ──\n%s", _indent(system, 4))
        self._log.debug("\n\n\n  ── user ──\n%s", _indent(user, 4))

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
