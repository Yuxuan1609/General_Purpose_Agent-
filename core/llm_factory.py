"""Shared LLM client factory — builds a configured LLMClient from config.yaml."""
import os
from pathlib import Path

from core.env_loader import load_env as _load_env_default


def build_llm_client(config_path: Path | None = None, model=None,
                     temperature: float = 0.1) -> "LLMClient":
    """Build an LLMClient from config.yaml + .env.

    Args:
        config_path: Path to config.yaml. Auto-detected if None.
        model: Override model name from config. None = use config value.
        temperature: LLM temperature.
    """
    import yaml
    from openai import OpenAI

    from core.llm_client import LLMClient

    if config_path is None:
        config_path = Path(__file__).resolve().parent.parent / "config.yaml"

    project_root = config_path.parent
    _load_env_default(project_root)

    with open(config_path, encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    cfg = raw.get("main_llm", {})

    base_url = cfg.get("base_url", "https://api.deepseek.com")
    api_key = os.environ.get(cfg.get("api_key_env", "DEEPSEEK_API_KEY"), "")
    oai = OpenAI(base_url=base_url, api_key=api_key)

    llm = LLMClient(oai, model or cfg.get("model", "deepseek-v4-flash"))
    llm.temperature = temperature
    if cfg.get("thinking", False):
        llm.thinking_enabled = True
        effort = cfg.get("thinking_effort", "high")
        llm.thinking_effort = effort
    return llm
