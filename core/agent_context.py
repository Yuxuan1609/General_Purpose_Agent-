"""AgentContext — per-environment tool allow/deny."""
from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class AgentContext:
    allowed_tools: set[str] = field(default_factory=set)
    denied_tools: set[str] = field(default_factory=set)

    def resolve(self, registry) -> list[dict]:
        """Return tool schemas visible to this context."""
        tools = list(registry._entries.values()) if hasattr(registry, '_entries') else []
        if self.allowed_tools:
            return [t.schema for t in tools if t.name in self.allowed_tools]
        if self.denied_tools:
            return [t.schema for t in tools if t.name not in self.denied_tools]
        return [t.schema for t in tools]
