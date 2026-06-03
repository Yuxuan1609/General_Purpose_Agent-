"""L3 UpwardComm Agent — handles LayerMessage communication with L2."""
from core.layers.comm import UpwardComm as _Base


class UpwardComm(_Base):
    """L3 → L2 communication via LayerMessage (A2)."""
