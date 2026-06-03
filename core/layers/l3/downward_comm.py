"""L3 DownwardComm Agent — handles LayerMessage communication with L4 (future)."""
from core.layers.comm import DownwardComm as _Base


class DownwardComm(_Base):
    """L3 → L4 communication via LayerMessage (A2)."""
