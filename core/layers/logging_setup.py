"""Per-layer logging setup — call once to enable file logging for all layer agents."""
import logging
from pathlib import Path


def setup_layer_logging(log_dir: Path):
    """Create per-layer DEBUG log files under log_dir.

    Creates: l0_5_1.log, l2.log, l3.log, executor.log
    Suppresses HTTP library noise.
    """
    log_dir = Path(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)

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
