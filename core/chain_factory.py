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
    from core.tools.registry import ToolRegistry
    from core.layers import build_chain as _build

    if data_root is None:
        data_root = Path(__file__).resolve().parent.parent

    meta = MetaDriver(DEFAULT_VALIDATORS.copy())
    phil = Philosophy(data_root / "data" / "layers" / "l1_rules.json")
    fk = FlexibleKnowledge(
        data_root / "data" / "layers" / "knowledge",
        data_root / "data" / "layers" / "knowledge" / "l2_index.json",
    )
    sl = SkillLayer(data_root / "data" / "layers" / "skills", ToolRegistry())

    if seed:
        from core.seed_knowledge import seed_knowledge
        seed_knowledge(fk, phil, sl)

    return _build(meta, phil, fk, sl, auxiliary_llm=auxiliary_llm)
