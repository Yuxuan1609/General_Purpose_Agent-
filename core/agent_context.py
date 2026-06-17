"""AgentContext — per-environment tool allow/deny filter."""
from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class AgentContext:
    """Per-environment tool filter. Receives pre-filtered tool schemas and
    applies allow/deny policy.  Priority: allowed > denied > pass.

    Constructed from Environment.tool_policy() when available.
    Sub-agents (kb_fill_gap etc.) define their own tools independently.
    """
    allowed_tools: set[str] = field(default_factory=set)
    denied_tools: set[str] = field(default_factory=set)

    @classmethod
    def from_policy(cls, policy: dict | None) -> AgentContext | None:
        """Create from env tool_policy dict or None."""
        if policy is None:
            return None
        allowed = set(policy.get("allowed", []))
        denied = set(policy.get("denied", []))
        if not allowed and not denied:
            return None
        return cls(allowed_tools=allowed, denied_tools=denied)

    def resolve(self, tools: list[dict]) -> list[dict]:
        """Filter tool schemas by allow/deny policy.

        tools: list of OpenAI tool schemas (each with `function.name`).
        Returns filtered list.
        """
        if not tools:
            return tools
        if self.allowed_tools:
            return [t for t in tools if t["function"]["name"] in self.allowed_tools]
        if self.denied_tools:
            return [t for t in tools if t["function"]["name"] not in self.denied_tools]
        return tools
