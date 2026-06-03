from __future__ import annotations
from typing import Any
import logging
from core.task import Domain, Task
from core.types import TaskObservation
from core.layers.base import LayerManager

logger = logging.getLogger("l0_5_1")


class L0_5_1Manager(LayerManager):
    """L(0.5+1) Manager — wraps MetaDriver + Philosophy.

    Immutable L0.5: safety filters, triggers (not yet invoked in execute phase).
    Mutable L1: behavioral rules injected into system prompt.
    """

    def __init__(self, meta_driver, philosophy, auxiliary_llm=None,
                 downstream: LayerManager | None = None,
                 upward=None, downward=None):
        super().__init__("l0_5_1", downstream, upward=upward, downward=downward)
        self._meta = meta_driver
        self._philosophy = philosophy
        self._aux_llm = auxiliary_llm

    def process(self, data: Any) -> dict:
        obs: TaskObservation = data
        domain = obs.meta.get("domain", "general")
        logger.debug("[L0_5_1] received: domain=%s", domain)

        rules = self._philosophy.all_rules()
        obs.meta["l1_rules"] = [r.content for r in rules]

        logger.debug("[L0_5_1] response: %d rules", len(rules))
        return {"status": "ok", "rules_count": len(rules)}

    def notify(self) -> Any:
        return {"status": "ok", "layer": "l0_5_1"}
