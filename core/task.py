from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


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
    context: str = ""
    needs_decomposition: bool = False
    subtasks: list[LearningUnit] = field(default_factory=list)
    enable_learning: bool = False
    token_count: int = 0


@dataclass
class TaskResult:
    """Output of a completed task execution."""
    success: bool = False
    final_response: str = ""
    new_knowledge_cards: int = 0
    l1_changes: list[str] = field(default_factory=list)
    l1_rejections: list[str] = field(default_factory=list)
    new_skills: list[str] = field(default_factory=list)
    iterations_used: int = 0
    summary: str = ""
    eval_result: str = ""
    eval_score: float = 0.0


@dataclass
class TaskContext:
    """Mutable context tracked during a single task execution."""
    task: LearningUnit
    consecutive_no_progress: int = 0
    eval_result: str = ""
    rounds: int = 0
