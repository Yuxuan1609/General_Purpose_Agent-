"""AgentContext — per-environment tool allow/deny filter."""
from __future__ import annotations
import threading
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
    # Per-step call counters (thread-safe). Reset by env between steps.
    _call_counters: dict[str, int] = field(default_factory=dict)
    _counter_lock: threading.Lock = field(default_factory=threading.Lock)
    # Per-step call limits: tool_name → max calls per step
    call_limits: dict[str, int] = field(default_factory=dict)
    # Shared call groups: group_name → (max_calls, [tool_names])
    # Tools in a group share a single counter.
    call_groups: dict[str, tuple[int, list[str]]] = field(default_factory=dict)
    # Command filter for terminal tool: function(command_str) -> filtered_str
    # Set by environments that need to intercept/reroute shell commands.
    terminal_command_filter: object = None

    @classmethod
    def from_policy(cls, policy: dict | None) -> AgentContext | None:
        """Create from env tool_policy dict or None."""
        if policy is None:
            return None
        allowed = set(policy.get("allowed", []))
        denied = set(policy.get("denied", []))
        call_limits = dict(policy.get("call_limits", {}))
        call_groups = {}
        for gname, gdef in policy.get("call_groups", {}).items():
            if isinstance(gdef, dict) and "max" in gdef and "tools" in gdef:
                call_groups[gname] = (int(gdef["max"]), list(gdef["tools"]))
        terminal_filter = policy.get("terminal_command_filter")
        if not allowed and not denied and not call_limits and not call_groups and not terminal_filter:
            return None
        return cls(allowed_tools=allowed, denied_tools=denied,
                   call_limits=call_limits, call_groups=call_groups,
                   terminal_command_filter=terminal_filter)

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

    def check_call_limit(self, tool_name: str) -> bool:
        """Check if tool can still be called this step. Returns True if allowed.
        Increments counter. Called from base.py tool dispatch.
        """
        # Check shared group limit first
        for gname, (max_calls, tools) in self.call_groups.items():
            if tool_name in tools:
                with self._counter_lock:
                    count = self._call_counters.get(gname, 0)
                    if count >= max_calls:
                        return False
                    self._call_counters[gname] = count + 1
                    return True
        # Check individual limit
        if tool_name not in self.call_limits:
            return True
        with self._counter_lock:
            count = self._call_counters.get(tool_name, 0)
            limit = self.call_limits[tool_name]
            if count >= limit:
                return False
            self._call_counters[tool_name] = count + 1
            return True

    def reset_call_counters(self) -> None:
        """Reset per-step counters. Called by env at the start of each step."""
        with self._counter_lock:
            self._call_counters.clear()
