"""Layer package — three-layer cognitive chain with Comm Agents (A2)."""

from core.layers.base import LayerManager, LayerAgent
from core.layers.comm import UpwardComm, DownwardComm, AgentPacket, ReflectPacket
from core.layers.l0_5_1.manager import L0_5_1Manager
from core.layers.l2.manager import L2Manager, L2_DOMAIN_NODES
from core.layers.l3.manager import L3Manager


def build_chain(meta_driver, philosophy, flexible_knowledge, skill_layer,
                auxiliary_llm=None) -> L0_5_1Manager:
    """Build the three-layer chain bottom-up.

    Each layer is wired with UpwardComm + DownwardComm for LayerMessage protocol.
    Returns the root (L0.5+1 Manager) which has L2 and L3 wired in.

    Phase 2a: L2's domain nodes are injected into L1 to merge L2 stage1
    (node selection) into L1's stage1 call.
    """
    from core.layers.l3.upward_comm import UpwardComm as L3Upward
    from core.layers.l3.downward_comm import DownwardComm as L3Downward
    from core.layers.l2.upward_comm import UpwardComm as L2Upward
    from core.layers.l2.downward_comm import DownwardComm as L2Downward
    from core.layers.l0_5_1.upward_comm import UpwardComm as L1Upward
    from core.layers.l0_5_1.downward_comm import DownwardComm as L1Downward

    l3 = L3Manager(skill_layer, upward=L3Upward(), downward=L3Downward(),
                   auxiliary_llm=auxiliary_llm)
    l2 = L2Manager(flexible_knowledge, downstream=l3,
                   upward=L2Upward(), downward=L2Downward(),
                   auxiliary_llm=auxiliary_llm)
    l1 = L0_5_1Manager(meta_driver, philosophy, auxiliary_llm=auxiliary_llm,
                       downstream=l2,
                       upward=L1Upward(), downward=L1Downward(),
                       domain_nodes=L2_DOMAIN_NODES)
    return l1


__all__ = ["LayerManager", "LayerAgent", "UpwardComm", "DownwardComm",
           "AgentPacket", "ReflectPacket",
           "L0_5_1Manager", "L2Manager", "L3Manager", "build_chain"]
