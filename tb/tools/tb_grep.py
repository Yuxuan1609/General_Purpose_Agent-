"""TB grep tool — searches file contents inside the Docker container via tmux."""
from __future__ import annotations
import json
import logging
import threading
import time

logger = logging.getLogger(__name__)
_lock = threading.Lock()


def register_tb_grep(registry):
    def handler(args=None, timeout=10):
        pattern = (args or {}).get("pattern", "")
        if not pattern:
            return json.dumps({"error": "No pattern provided"})

        search_path = (args or {}).get("path", "/app")
        include = (args or {}).get("include", "")

        with _lock:
            from tb.session_holder import get
            session = get()

            session.get_incremental_output()

            cmd = f"grep -rn -- '{pattern}' '{search_path}'"
            if include:
                cmd = f"grep -rn --include='{include}' -- '{pattern}' '{search_path}'"
            cmd += " 2>/dev/null | head -50"

            try:
                session.send_keys([cmd, "Enter"], block=True,
                                  max_timeout_sec=float(timeout))
                time.sleep(0.3)
                output = session.get_incremental_output()
            except Exception as e:
                return json.dumps({"error": str(e)})

        matches = [l for l in output.splitlines() if l.strip()]
        return json.dumps({
            "matches": matches,
            "count": len(matches),
        }, ensure_ascii=False)

    registry.register("grep", {
        "type": "function",
        "function": {
            "name": "grep",
            "description": (
                "Search file contents with regex pattern inside the TB container. "
                "Returns matching file paths, line numbers, and line content. "
                "Uses grep via tmux."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {
                        "type": "string",
                        "description": "Regex pattern to search for",
                    },
                    "path": {
                        "type": "string",
                        "description": "Directory to search in (default /app)",
                    },
                    "include": {
                        "type": "string",
                        "description": "File glob filter (e.g. '*.py'). Default: all files",
                    },
                    "sync": {
                        "type": "boolean",
                        "description": "true=blocking(default)",
                    },
                },
                "required": ["pattern"],
            },
        },
    }, handler, toolset="core", override=True)
