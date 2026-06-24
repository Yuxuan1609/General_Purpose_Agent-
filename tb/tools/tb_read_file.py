"""TB read_file tool — reads files inside the Docker container via tmux."""
from __future__ import annotations
import json
import logging
import threading
import time

logger = logging.getLogger(__name__)
_lock = threading.Lock()


def register_tb_read_file(registry):
    def handler(args=None, timeout=10):
        path = (args or {}).get("path", "")
        if not path:
            return json.dumps({"error": "No path provided"})

        offset = max(1, int((args or {}).get("offset", 1)))
        limit = min(int((args or {}).get("limit", 200)), 2000)

        with _lock:
            from tb.session_holder import get
            session = get()

            # Count lines
            session.get_incremental_output()
            wc_cmd = f"wc -l < '{path}'"
            try:
                session.send_keys([wc_cmd, "Enter"], block=True,
                                  max_timeout_sec=float(timeout))
                time.sleep(0.2)
                wc_out = session.get_incremental_output()
                total_lines = _extract_first_int(wc_out)
            except Exception:
                total_lines = -1

            # Read lines
            session.get_incremental_output()
            sed_cmd = f"sed -n '{offset},{offset + limit - 1}p' '{path}'"
            try:
                session.send_keys([sed_cmd, "Enter"], block=True,
                                  max_timeout_sec=float(timeout))
                time.sleep(0.2)
                content = session.get_incremental_output()
            except Exception as e:
                return json.dumps({"error": str(e)})

        return json.dumps({
            "path": path,
            "total_lines": total_lines,
            "offset": offset,
            "content": content,
        }, ensure_ascii=False)

    registry.register("read_file", {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": (
                "Read content from a file inside the TB container. "
                "Returns numbered lines. Uses sed via tmux."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Absolute path to the file in the container",
                    },
                    "offset": {
                        "type": "integer",
                        "description": "Start line (1-indexed, default 1)",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max lines to read (default 200, max 2000)",
                    },
                    "sync": {
                        "type": "boolean",
                        "description": "true=blocking(default)",
                    },
                },
                "required": ["path"],
            },
        },
    }, handler, toolset="core", override=True)


def _extract_first_int(text: str) -> int:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.isdigit() or (stripped.startswith('-') and stripped[1:].isdigit()):
            return int(stripped)
    return -1
