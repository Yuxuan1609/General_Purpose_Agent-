"""L0.5+1 UpwardComm Agent — handles LayerMessage communication with Executor."""
from core.layers.comm import UpwardComm as _Base


class UpwardComm(_Base):
    """L0.5+1 → Executor communication via LayerMessage (A2)."""
