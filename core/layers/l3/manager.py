from __future__ import annotations
from typing import Any
import logging
from core.task import Domain
from core.types import TaskObservation
from core.layers.base import LayerManager

logger = logging.getLogger("l3")


class L3Manager(LayerManager):
    """L3 Manager — wraps SkillLayer, matches skills to task domain."""

    def __init__(self, skill_layer, downstream: LayerManager | None = None,
                 upward=None, downward=None):
        super().__init__("l3", downstream, upward=upward, downward=downward)
        self._skill_layer = skill_layer

    def process(self, data: Any) -> dict:
        obs: TaskObservation = data
        session = obs.session or {}
        domain_path = session.get("domain", "general")

        try:
            domain = Domain(domain_path, "specific")
        except Exception:
            domain = Domain("general", "general")

        matched = self._skill_layer.match(domain)
        obs.state["l3_skills"] = []
        for s in matched:
            content = ""
            if s.skill_dir:
                skill_file = s.skill_dir / "SKILL.md"
                if skill_file.exists():
                    content = skill_file.read_text(encoding="utf-8")
            obs.state["l3_skills"].append({
                "name": s.name, "description": s.description,
                "domain": s.domain.path, "content": content,
            })
        logger.debug("── L3 ──")
        logger.debug("  received: domain=%s", domain_path)
        logger.debug("  response: %d skills", len(matched))
        for i, s in enumerate(matched):
            logger.debug("    [skill %d] %s | %s", i + 1, s.name, s.description)
        return {"status": "ok", "skills_matched": len(matched)}

    def notify(self) -> Any:
        return {"status": "ok", "layer": "l3"}
