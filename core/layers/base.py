from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Any


class LayerManager(ABC):
    """Abstract base for all layer Manager agents.

    Each Manager:
      - process(data) → enriches data with its layer's information → calls downstream
      - query(data) → entry point for the QUERY chain
      - collect_notify() → gathers NOTIFY payloads from self + all downstream
    """

    def __init__(self, name: str, downstream: LayerManager | None = None):
        self.name = name
        self._downstream = downstream
        self._last_notify: Any = None

    @abstractmethod
    def process(self, data: Any) -> dict:
        """Enrich data with this layer's information.

        Returns a dict with status info for the RESPONSE chain.
        Must update `data` in-place with layer-specific fields.
        """
        ...

    @abstractmethod
    def notify(self) -> Any:
        """Return the payload for this layer's NOTIFY to the Executor."""
        ...

    def query(self, data: Any) -> None:
        """Entry point: process this layer, then propagate downstream."""
        self.process(data)
        if self._downstream:
            self._downstream.query(data)

    def collect_notify(self) -> dict:
        """Collect NOTIFY payloads from this layer and all downstream layers.

        Returns: {layer_name: notify_payload, ...}
        """
        result: dict = {}
        result[self.name] = self.notify()
        if self._downstream:
            result.update(self._downstream.collect_notify())
        return result
