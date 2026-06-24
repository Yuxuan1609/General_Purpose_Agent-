"""TB env helper — apply learning context to chain layers.

Uses existing AgentContext + set_context mechanism for dynamic tool filtering.
Train: all tools enabled.  Test: record_learning, kb_add, kb_fill_gap denied.
"""
from __future__ import annotations


def apply_learning_context(chain, enable: bool) -> None:
    """Apply tool context to all chain layers.

    Args:
        chain: Root layer node of the cognitive chain.
        enable: If True, all tools available (train mode).
                If False, record_learning/kb_add/kb_fill_gap denied (test mode).
    """
    from core.agent_context import AgentContext

    ctx = None
    if not enable:
        ctx = AgentContext(
            denied_tools={"record_learning", "kb_add", "kb_fill_gap"}
        )

    node = chain
    while node is not None:
        agent = getattr(node, '_agent', None)
        if agent is not None:
            agent.set_context(ctx)
        node = getattr(node, '_downstream', None)
