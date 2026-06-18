"""Per-layer logging setup — call once to enable file logging for all layer agents."""
import logging
import shutil
from pathlib import Path

_MAX_LOG_SESSIONS = 20


def _rotate_log_dir(log_dir: Path, max_sessions: int = _MAX_LOG_SESSIONS):
    """Keep only the last max_sessions timestamped subdirectories in log_dir."""
    if not log_dir.exists():
        return
    subdirs = sorted(
        [d for d in log_dir.iterdir() if d.is_dir()],
        key=lambda d: d.name, reverse=True,
    )
    for d in subdirs[max_sessions:]:
        shutil.rmtree(d, ignore_errors=True)


def setup_layer_logging(log_dir: Path):
    """Create per-layer DEBUG log files under log_dir.

    Creates: l0_5_1.log, l2.log, l3.log, executor.log
    Suppresses HTTP library noise.
    Rotates old session directories (keeps last 20).
    """
    log_dir = Path(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)

    _rotate_log_dir(log_dir.parent, _MAX_LOG_SESSIONS)

    # Suppress http noise
    for noisy in ("httpx", "httpcore", "openai", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    fmt = logging.Formatter("%(message)s")
    for lg_name in ("l0_5_1", "l2", "l3", "core.executor"):
        lg = logging.getLogger(lg_name)
        lg.setLevel(logging.DEBUG)
        lg.propagate = False
        fh = logging.FileHandler(str(log_dir / f"{lg_name.replace('core.', '')}.log"),
                                 encoding="utf-8")
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(fmt)
        lg.addHandler(fh)
