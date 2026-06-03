"""L2 UpwardComm Agent — handles LayerMessage communication with L0.5+1."""
from core.layers.comm import UpwardComm as _Base


class UpwardComm(_Base):
    """L2 → L0.5+1 communication via LayerMessage (A2)."""
