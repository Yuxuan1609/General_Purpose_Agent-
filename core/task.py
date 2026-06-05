from __future__ import annotations
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Domain:
    """Hierarchical domain identifier. Frozen for use as dict key."""
    path: str
    level: str

    @property
    def is_general(self) -> bool:
        return self.level == "general"

    @property
    def parent(self) -> Domain | None:
        parts = self.path.rsplit("/", 1)
        if len(parts) == 1:
            return None
        return Domain(parts[0], "general")

    @property
    def depth(self) -> int:
        if self.path == "general":
            return 0
        return self.path.count("/") + 1

    def is_ancestor_of(self, other: Domain) -> bool:
        return other.path.startswith(self.path + "/")

    def is_descendant_of(self, other: Domain) -> bool:
        return self.path.startswith(other.path + "/")


@dataclass
class LearningUnit:
    """Minimum unit for learning. One session may decompose into multiple LearningUnits.

    Distinct from TaskObservation (a single step's observation). A LearningUnit
    can span multiple TaskObservations; the learning pipeline groups them by domain.
    """
    description: str
    domain: Domain = field(default_factory=lambda: Domain("general", "general"))
