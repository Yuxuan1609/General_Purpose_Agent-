"""Shared chain factory — builds the three-layer cognitive chain."""
from pathlib import Path


def build_default_chain(data_root: Path | None = None, auxiliary_llm=None,
                        seed: bool = True, env=None):
    """Build L(0.5+1)→L2→L3 chain with default knowledge stores.

    Args:
        data_root: Project root (auto-detected if None).
        auxiliary_llm: Optional LLM client for layer agents.
        seed: If True, call seed_knowledge() to populate initial cards/skills.
        env: Optional Environment for per-env tool filtering (tool_policy).
    """
    from core.philosophy import Philosophy
    from core.flexible_knowledge import FlexibleKnowledge
    from core.skill_layer import SkillLayer
    from core.layers import build_chain as _build

    if data_root is None:
        data_root = Path(__file__).resolve().parent.parent

    data_path = data_root / "data" / "cognitive"
    data_path.mkdir(parents=True, exist_ok=True)

    from core.seed_knowledge import init_registry
    from core.model_manager import set_model_path
    set_model_path(str(Path(__file__).resolve().parent.parent / "embeddinggemma"))
    reg = init_registry(data_root / "data" / "layers" / "domain_registry.json",
                        db_path=data_path / "domain.db")

    phil = Philosophy(data_root / "data" / "layers" / "l1_rules.json",
                       db_path=data_path / "l1.db")
    fk = FlexibleKnowledge(
        data_root / "data" / "layers" / "knowledge",
        data_root / "data" / "layers" / "knowledge" / "l2_index.json",
        domain_registry=reg,
        db_path=data_path / "l2.db",
    )
    sl = SkillLayer(data_root / "data" / "layers" / "skills",
                    domain_registry=reg,
                    db_path=data_path / "l3.db")

    if seed:
        from core.seed_knowledge import seed_knowledge
        seed_knowledge(fk, phil, sl, domain_registry=reg)

    knowledge_stores = {"l2": fk, "l3": sl}

    chain = _build(phil, fk, sl, auxiliary_llm=auxiliary_llm,
                    domain_registry=reg, knowledge_stores=knowledge_stores)
    _mount_tools(chain, data_root)

    if env is not None:
        from core.agent_context import AgentContext
        policy = getattr(env, "tool_policy", None)
        ctx = AgentContext.from_policy(policy)
        if ctx is not None:
            for layer in _iter_layers(chain):
                if layer._agent:
                    layer._agent.set_context(ctx)

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

    from core.tools.consolidation_injection import set_consolidation_stores
    l2 = chain._downstream
    l3 = l2._downstream if l2 else None
    set_consolidation_stores(
        {"l1": chain._philosophy,
         "l2": l2._knowledge if l2 else None,
         "l3": l3._skill_layer if l3 else None},
        registry=chain._registry,
    )

    from core.tools.downward_comm_tool import set_layer_downstreams
    downstream_map = {}
    node = chain
    while node is not None:
        if node.name == "l0_5_1" and node._downstream:
            downstream_map["l1_query"] = node._downstream
        if node.name == "l2" and node._downstream:
            downstream_map["l2_query"] = node._downstream
        node = node._downstream
    set_layer_downstreams(downstream_map)

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


def _iter_layers(root):
    """Walk the chain downward from root."""
    node = root
    while node is not None:
        yield node
        node = node._downstream
