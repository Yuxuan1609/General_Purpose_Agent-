from __future__ import annotations
from typing import Any
from core.task import Domain
from core.types import TaskObservation
from core.layers.base import LayerManager


class L3Manager(LayerManager):
    """L3 Manager — wraps SkillLayer, matches skills to task domain."""

    def __init__(self, skill_layer, downstream: LayerManager | None = None,
                 upward=None, downward=None):
        super().__init__("l3", downstream, upward=upward, downward=downward)
        self._skill_layer = skill_layer

    def process(self, data: Any) -> dict:
        obs: TaskObservation = data
        domain_path = obs.meta.get("domain", "general")

        try:
            domain = Domain(domain_path, "specific")
        except Exception:
            domain = Domain("general", "general")

        matched = self._skill_layer.match(domain)
        obs.meta["l3_skills"] = [
            {"name": s.name, "description": s.description, "domain": s.domain.path}
            for s in matched
        ]
        return {"status": "ok", "skills_matched": len(matched)}

    def notify(self) -> Any:
        return {"status": "ok", "layer": "l3"}
