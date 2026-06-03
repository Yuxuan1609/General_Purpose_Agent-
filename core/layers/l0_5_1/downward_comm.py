"""L0.5+1 DownwardComm Agent — handles LayerMessage communication with L2."""
from core.layers.comm import DownwardComm as _Base


class DownwardComm(_Base):
    """L0.5+1 → L2 communication via LayerMessage (A2)."""
