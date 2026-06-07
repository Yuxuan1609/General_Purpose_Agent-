from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class CapabilityResult:
    """Unified return type for all capability invocations.

    Flows through LayerMessage back to the calling layer's user prompt.
    """
    capability_name: str
    layer: str
    success: bool
    data: Any = None
    error: str = ""
    metadata: dict = field(default_factory=dict)


class Capability(ABC):
    """Abstract capability consumable by cognitive layers via LayerAgent.

    Subclasses manage their own access control (which layers see which
    sub-items). The ABC only defines the unified register/discover/invoke
    contract.
    """

    name: str

    @abstractmethod
    def get_schema(self) -> dict:
        """Return OpenAI function-calling compatible JSON schema.

        Injected into LLM tools/functions parameter via LayerInjector.
        """
        ...

    @abstractmethod
    def is_visible_to(self, layer: str) -> bool:
        """Whether this capability should appear in the given layer's prompt."""
        ...

    @abstractmethod
    def invoke(self, layer: str, args: dict) -> CapabilityResult:
        """Execute a call from the given layer.

        Args:
            layer: Calling layer identifier ("l1"/"l2"/"l3").
                   Subclasses use this for access control.
            args: Tool arguments (function-call JSON).

        Returns:
            CapabilityResult with success/data or failure/error.
        """
        ...


class CapabilityRegistry:
    """Unified capability registration and dispatch.

    Replaces potential future multiple registries (ToolRegistry /
    KnowledgeRegistry / ...). Existing ToolRegistry is kept unchanged
    and wrapped via ToolCapability.
    """

    def __init__(self):
        self._capabilities: dict[str, Capability] = {}

    def register(self, cap: Capability) -> None:
        if cap.name in self._capabilities:
            raise ValueError(
                f"Capability '{cap.name}' already registered"
            )
        self._capabilities[cap.name] = cap

    def get(self, name: str) -> Capability | None:
        return self._capabilities.get(name)

    def get_schemas_for_layer(self, layer: str) -> list[dict]:
        """Return all visible capability schemas for the given layer."""
        schemas = []
        for cap in self._capabilities.values():
            if cap.is_visible_to(layer):
                schema = cap.get_schema()
                schemas.append(schema)
        return schemas

    def invoke(self, name: str, layer: str, args: dict) -> CapabilityResult:
        """Dispatch an invocation to the named capability."""
        cap = self._capabilities.get(name)
        if cap is None:
            return CapabilityResult(
                capability_name=name, layer=layer, success=False,
                error=f"Capability '{name}' not found",
            )
        return cap.invoke(layer, args)

    def list_for_layer(self, layer: str) -> list[str]:
        """Return names of capabilities visible to the given layer."""
        return [
            name for name, cap in self._capabilities.items()
            if cap.is_visible_to(layer)
        ]
