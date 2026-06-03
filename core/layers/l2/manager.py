from __future__ import annotations
from typing import Any
import logging
from core.task import Domain
from core.types import TaskObservation
from core.layers.base import LayerManager

logger = logging.getLogger("l2")


class L2Manager(LayerManager):
    """L2 Manager — wraps FlexibleKnowledge, retrieves top-k active cards."""

    def __init__(self, knowledge, downstream: LayerManager | None = None,
                 upward=None, downward=None):
        super().__init__("l2", downstream, upward=upward, downward=downward)
        self._knowledge = knowledge

    def process(self, data: Any) -> dict:
        obs: TaskObservation = data
        domain_path = obs.meta.get("domain", "general")

        try:
            domain = Domain(domain_path, "specific")
        except Exception:
            domain = Domain("general", "general")

        active = self._knowledge.get_active_cards(domain, obs.meta.get("context", ""), top_k=5)
        obs.meta["l2_cards"] = [
            {
                "content": c.content,
                "confidence": c.confidence,
                "activation": c.activation,
                "domain": c.domain.path,
            }
            for c in active
        ]
        domains = list({c.domain.path for c in active})
        logger.debug("── L2 ──")
        logger.debug("  received: domain=%s", domain_path)
        logger.debug("  response: %d cards  (nodes: %s)", len(active), domains)
        return {"status": "ok", "cards_found": len(active)}

    def notify(self) -> Any:
        return {"status": "ok", "layer": "l2"}
