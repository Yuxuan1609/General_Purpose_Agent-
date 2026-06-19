# core/setup.py
"""Shared executor/chain setup — used by both CLI and Gradio."""
from __future__ import annotations
from pathlib import Path
from typing import Any

from core.env_loader import load_env
from core.llm_factory import build_llm_client
from core.chain_factory import build_default_chain
from core.executor import Executor
from core.runtime_registry import register_runtime


def setup_executor(project_root: Path | None = None) -> tuple[Any, Any]:
    """Create and wire llm → chain → executor. Returns (chain, executor).

    Registers the chain + executor to runtime_registry so auto-learning
    and other global consumers can find them.
    """
    if project_root is None:
        project_root = Path(__file__).resolve().parent.parent
    load_env(project_root)

    llm = build_llm_client(project_root / "config.yaml")
    chain = build_default_chain(project_root, auxiliary_llm=llm, seed=False)
    executor = Executor(
        layer_root=chain,
        llm_client=llm,
        learning_dir=project_root / "data" / "learning",
    )
    register_runtime(chain, executor)
    return chain, executor
