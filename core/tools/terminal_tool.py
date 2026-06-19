"""Minimal terminal tool for environment command execution."""
import json
import shutil
import subprocess
import logging

logger = logging.getLogger(__name__)

_SHELL = None


def _get_shell():
    global _SHELL
    if _SHELL is not None:
        return _SHELL
    pwsh = shutil.which("pwsh")
    if pwsh:
        _SHELL = pwsh
        logger.info("terminal shell: pwsh (%s)", _SHELL)
        return _SHELL
    ps = shutil.which("powershell")
    if ps:
        _SHELL = ps
        logger.warning("terminal shell: fallback to powershell (%s) — pwsh not found", _SHELL)
        return _SHELL
    _SHELL = "cmd"
    logger.warning("terminal shell: fallback to cmd — pwsh and powershell not found")
    return _SHELL


def register_terminal_tool(registry, allowed_commands: list[str] | None = None):
    def handler(args=None, timeout=300):
        command = (args or {}).get("command", "")
        effective_timeout = (args or {}).get("timeout", timeout) if args else timeout
        if not command:
            return json.dumps({"error": "No command provided"})
        if allowed_commands and not any(command.startswith(cmd) for cmd in allowed_commands):
            return json.dumps({"error": f"Command not allowed: {command}"})
        try:
            shell = _get_shell()
            if shell != "cmd":
                cmd = f'"{shell}" -Command "{command}"'
                result = subprocess.run(cmd, shell=False,
                                        capture_output=True, text=True, timeout=effective_timeout)
            else:
                result = subprocess.run(command, shell=True,
                                        capture_output=True, text=True, timeout=effective_timeout)
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
                    "command": {"type": "string", "description": "Shell command to execute"},
                    "sync": {"type": "boolean", "description": "true=blocking(default), false=fire-and-forget returns task_id"},
                },
                "required": ["command"]
            }
        }
    }, handler, toolset="core")
