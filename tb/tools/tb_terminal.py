"""TB terminal tool — executes commands in Docker container via TmuxSession."""
from __future__ import annotations
import json
import logging
import threading
import time

logger = logging.getLogger(__name__)
_lock = threading.Lock()


def register_tb_terminal_tool(registry):
    def handler(args=None, timeout=300):
        command = (args or {}).get("command", "")
        if not command:
            return json.dumps({"error": "No command provided"})

        with _lock:
            from tb.session_holder import get
            session = get()

            # Drain incremental state before command
            session.get_incremental_output()

            # Split multi-line commands (heredoc, etc.) into individual lines.
            # Docker exec API + tmux send-keys fail on args containing \n.
            lines = command.split('\n')
            try:
                for i, line in enumerate(lines):
                    if i < len(lines) - 1:
                        session.send_keys([line, "Enter"], block=False)
                        time.sleep(0.05)
                    else:
                        session.send_keys([line, "Enter"], block=True,
                                          max_timeout_sec=float(timeout))
            except TimeoutError:
                return json.dumps({"error": f"Command timed out ({timeout}s)"})
            except Exception as e:
                return json.dumps({"error": str(e)})

            time.sleep(0.3)
            output = session.get_incremental_output()

        return json.dumps({
            "command": command,
            "output": output,
        }, ensure_ascii=False)

    registry.register("terminal", {
        "type": "function",
        "function": {
            "name": "terminal",
            "description": (
                "Execute a shell command in the TB Docker container and capture "
                "the terminal output. Commands run inside the task container via tmux."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "Shell command to execute in the container",
                    },
                    "sync": {
                        "type": "boolean",
                        "description": "true=blocking(default)",
                    },
                },
                "required": ["command"],
            },
        },
    }, handler, toolset="core", override=True)
