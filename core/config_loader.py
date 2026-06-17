"""Shared config loader — reads config.yaml once, provides sections."""
from __future__ import annotations

from pathlib import Path
import yaml

_config: dict | None = None
_config_path: Path | None = None


def load_config(path: Path | str | None = None) -> dict:
    """Load config.yaml once, return the full dict."""
    global _config, _config_path
    if _config is not None:
        return _config
    if path is None:
        path = Path(__file__).resolve().parent.parent / "config.yaml"
    _config_path = Path(path)
    with open(_config_path, encoding="utf-8") as f:
        _config = yaml.safe_load(f) or {}
    return _config


def get_section(*keys, default=None):
    """Traverse nested keys, return the subtree or default.

    get_section('runtime') → config['runtime']
    get_section('l3', 'match_scores') → config['l3']['match_scores']
    """
    cfg = load_config()
    for k in keys:
        if not isinstance(cfg, dict):
            return default
        cfg = cfg.get(k)
        if cfg is None:
            return default
    return cfg
