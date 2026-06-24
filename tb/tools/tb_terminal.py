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

            # Split multi-line commands (heredoc, etc.) into individual key
            # arguments. Docker exec API corrupts args containing literal \n,
            # so each line becomes a separate tmux send-keys argument with
            # "Enter" between them.
            #
            # TB harness _prevent_execution strips trailing "Enter" keys, then
            # appends "; tmux wait -S done" as the next key arg. tmux types
            # consecutive args without a line break, so the completion marker
            # would land on the same line as the heredoc terminator (e.g.
            # "EOF; tmux wait -S done"), which bash doesn't recognize as the
            # heredoc delimiter. Appending "true" forces the completion marker
            # onto a separate line after the heredoc closes.
            lines = command.split('\n')
            keys = []
            for line in lines:
                keys.append(line)
                keys.append("Enter")
            if len(lines) > 1:
                keys.append("true")
                keys.append("Enter")
            try:
                session.send_keys(keys, block=True,
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
