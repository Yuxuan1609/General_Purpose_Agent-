"""Shared chain factory — builds the three-layer cognitive chain."""
from pathlib import Path


def build_default_chain(data_root: Path | None = None, auxiliary_llm=None,
                        seed: bool = True):
    """Build L(0.5+1)→L2→L3 chain with default knowledge stores.

    Args:
        data_root: Project root (auto-detected if None).
        auxiliary_llm: Optional LLM client for layer agents.
        seed: If True, call seed_knowledge() to populate initial cards/skills.
    """
    from core.meta_driver import MetaDriver, DEFAULT_VALIDATORS
    from core.philosophy import Philosophy
    from core.flexible_knowledge import FlexibleKnowledge
    from core.skill_layer import SkillLayer
    from core.layers import build_chain as _build

    if data_root is None:
        data_root = Path(__file__).resolve().parent.parent

    from core.seed_knowledge import init_registry
    from core.domain_registry import set_embedding_model_path
    set_embedding_model_path(str(data_root / "embeddinggemma"))
    reg = init_registry(data_root / "data" / "layers" / "domain_registry.json")

    meta = MetaDriver(DEFAULT_VALIDATORS.copy())
    phil = Philosophy(data_root / "data" / "layers" / "l1_rules.json")
    fk = FlexibleKnowledge(
        data_root / "data" / "layers" / "knowledge",
        data_root / "data" / "layers" / "knowledge" / "l2_index.json",
        domain_registry=reg,
    )
    sl = SkillLayer(data_root / "data" / "layers" / "skills", domain_registry=reg)

    if seed:
        from core.seed_knowledge import seed_knowledge
        seed_knowledge(fk, phil, sl, domain_registry=reg)

    knowledge_stores = {"l2": fk, "l3": sl}
    chain = _build(meta, phil, fk, sl, auxiliary_llm=auxiliary_llm,
                    domain_registry=reg, knowledge_stores=knowledge_stores)
    _mount_tools(chain, data_root)
    return chain


def _mount_tools(chain, data_root: Path):
    """Register all tools and attach LayerInjector to every layer."""
    from core.tools import register_all_tools
    from core.tools.registry import ToolRegistry
    from capability.tool_capability import ToolCapability
    from capability import CapabilityRegistry
    from capability.layer_injector import LayerInjector

    registry = ToolRegistry()
    register_all_tools(registry, proposal_dir=data_root / "data" / "tool_proposals")
    from core.tools.domain_tool import set_domain_registry
    for layer in _iter_layers(chain):
        if layer._registry:
            set_domain_registry(layer._registry)
            break

    cap_registry = CapabilityRegistry()
    cap_registry.register(ToolCapability(registry))

    injector = LayerInjector(cap_registry)
    for layer in _iter_layers(chain):
        if layer._agent is not None:
            layer._agent.set_injector(injector)
            tool_names = [t["function"]["name"] for t in injector.get_tools_for_layer(layer.name)]
            import logging
            logging.getLogger("chain_factory").info(
                "[%s] tools: %s", layer.name, ", ".join(tool_names) if tool_names else "(none)"
            )


def _make_content_getter(fk, sl):
    def getter(layer: str, domain: str) -> list[str]:
        if layer == "l2":
            return [c.content for c in fk.cards if domain in c.available_domains]
        elif layer == "l3":
            return [m.description for n, m in sl._skills.items()
                    if domain in m.available_domains]
        return []
    return getter


def _iter_layers(root):
    """Walk the chain downward from root."""
    node = root
    while node is not None:
        yield node
        node = node._downstream
