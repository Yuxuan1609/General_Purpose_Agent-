"""Task Decomposer — splits sessions into evaluable LearningUnit objects."""
from pathlib import Path
from core.task import LearningUnit, Domain


class AgentStub:
    """TODO: Implement Task Decomposer orchestrator agent (Phase 2 Task 2.2)."""

    def decompose(self, user_input: str) -> list[LearningUnit]:
        """Split user input into independent LearningUnit objects."""
        return []

    def receive(self, message) -> None:
        pass
