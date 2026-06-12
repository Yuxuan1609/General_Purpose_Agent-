"""Minimal terminal tool for environment command execution."""
import json
import subprocess
import logging

logger = logging.getLogger(__name__)


def register_terminal_tool(registry, allowed_commands: list[str] | None = None):
    def handler(args=None, timeout=30):
        command = (args or {}).get("command", "")
        effective_timeout = (args or {}).get("timeout", timeout) if args else timeout
        if not command:
            return json.dumps({"error": "No command provided"})
        if allowed_commands and not any(command.startswith(cmd) for cmd in allowed_commands):
            return json.dumps({"error": f"Command not allowed: {command}"})
        try:
            result = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=effective_timeout)
            return json.dumps({
                "stdout": result.stdout,
                "stderr": result.stderr,
                "returncode": result.returncode,
            })
        except subprocess.TimeoutExpired:
            return json.dumps({"error": f"Command timed out ({effective_timeout}s)"})
        except Exception as e:
            return json.dumps({"error": str(e)})

    registry.register("terminal", {
        "type": "function",
        "function": {
            "name": "terminal",
            "description": "Execute a shell command and capture stdout/stderr",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Shell command to execute"}
                },
                "required": ["command"]
            }
        }
    }, handler, toolset="core")
