"""Layer package — three-layer cognitive chain."""

from core.layers.base import LayerManager
from core.layers.l0_5_1.manager import L0_5_1Manager
from core.layers.l2.manager import L2Manager
from core.layers.l3.manager import L3Manager


def build_chain(meta_driver, philosophy, flexible_knowledge, skill_layer,
                auxiliary_llm=None) -> L0_5_1Manager:
    """Build the three-layer chain bottom-up.

    Returns the root (L0.5+1 Manager) which has L2 and L3 wired in.
    """
    l3 = L3Manager(skill_layer)
    l2 = L2Manager(flexible_knowledge, downstream=l3)
    l1 = L0_5_1Manager(meta_driver, philosophy, auxiliary_llm=auxiliary_llm,
                       downstream=l2)
    return l1


__all__ = ["LayerManager", "L0_5_1Manager", "L2Manager", "L3Manager", "build_chain"]
