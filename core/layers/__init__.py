"""Layer package — three-layer cognitive chain with Comm Agents (A2)."""

from core.layers.base import LayerManager, LayerAgent
from core.layers.comm import UpwardComm, DownwardComm, AgentPacket
from core.layers.l0_5_1.manager import L0_5_1Manager
from core.layers.l2.manager import L2Manager
from core.layers.l3.manager import L3Manager


def build_chain(philosophy, flexible_knowledge, skill_layer,
                auxiliary_llm=None, domain_registry=None,
                knowledge_stores: dict | None = None) -> L0_5_1Manager:
    """Build the three-layer chain bottom-up.

    Each layer is wired with UpwardComm + DownwardComm for LayerMessage protocol.
    Returns the root (L0.5+1 Manager) which has L2 and L3 wired in.
    """
    from core.layers.comm import UpwardComm as CommUp, DownwardComm as CommDown

    l3 = L3Manager(skill_layer, upward=CommUp(), downward=CommDown(),
                   auxiliary_llm=auxiliary_llm, domain_registry=domain_registry)
    l2 = L2Manager(flexible_knowledge, downstream=l3,
                   upward=CommUp(), downward=CommDown(),
                   auxiliary_llm=auxiliary_llm, domain_registry=domain_registry)
    l1 = L0_5_1Manager(philosophy, auxiliary_llm=auxiliary_llm,
                        downstream=l2, upward=CommUp(), downward=CommDown(),
                        domain_registry=domain_registry,
                        knowledge_stores=knowledge_stores)
    return l1


__all__ = ["LayerManager", "LayerAgent", "UpwardComm", "DownwardComm",
           "AgentPacket",
           "L0_5_1Manager", "L2Manager", "L3Manager", "build_chain"]


