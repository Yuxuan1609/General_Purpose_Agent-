from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class EnvState:
    observation: str
    info: dict = field(default_factory=dict)


@dataclass
class EnvStep:
    state: EnvState
    reward: float
    done: bool


class Environment(ABC):
    @abstractmethod
    def reset(self, task_description: str) -> EnvState:
        ...

    @abstractmethod
    def step(self, action: str) -> EnvStep:
        ...

    @property
    def tool_policy(self) -> dict | None:
        """Optional per-environment tool filter.

        Returns None (no filtering) or {"allowed": [...], "denied": [...]}.
        Priority: allowed > denied > pass.
        Agents use this to construct AgentContext for per-env filtering.
        Does NOT inject tool definitions — only name lists (R1/R3 compliant).
        """
        return None
