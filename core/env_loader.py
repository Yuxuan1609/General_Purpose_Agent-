"""Shared environment variable loader — reads .env file into os.environ."""
import os
from pathlib import Path


def load_env(project_root: Path | None = None):
    """Load .env file into os.environ (skips already-set keys).

    Args:
        project_root: Project root directory containing .env. If None,
                      auto-detects relative to this file's location.
    """
    if project_root is None:
        project_root = Path(__file__).resolve().parent.parent

    env_path = project_root / ".env"
    if not env_path.exists():
        return

    for line in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key, val = key.strip(), val.strip()
        if key not in os.environ:
            os.environ[key] = val
