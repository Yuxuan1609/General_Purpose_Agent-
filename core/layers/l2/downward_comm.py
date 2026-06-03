"""L2 DownwardComm Agent — handles LayerMessage communication with L3."""
from core.layers.comm import DownwardComm as _Base


class DownwardComm(_Base):
    """L2 → L3 communication via LayerMessage (A2)."""
