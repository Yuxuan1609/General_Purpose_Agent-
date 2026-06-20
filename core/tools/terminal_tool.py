"""Minimal terminal tool for environment command execution."""
import json
import shutil
import subprocess
import logging
import time

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
                cmd_list = [shell, "-Command", command]
                proc = subprocess.Popen(
                    cmd_list, shell=False,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                )
            else:
                proc = subprocess.Popen(
                    command, shell=True,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                )

            from core.task_runner import get_shared_runner
            from core.session import get_running_task_id
            task_id = get_running_task_id()
            deadline = time.time() + effective_timeout

            while True:
                try:
                    stdout, stderr = proc.communicate(timeout=0.5)
                    return json.dumps({
                        "stdout": stdout or "",
                        "stderr": stderr or "",
                        "returncode": proc.returncode,
                    })
                except subprocess.TimeoutExpired:
                    if time.time() > deadline:
                        proc.kill()
                        proc.communicate(timeout=1)
                        return json.dumps({"error": f"Command timed out ({effective_timeout}s)"})
                    if task_id:
                        task = get_shared_runner().check(task_id)
                        if task and task.cancelled:
                            proc.kill()
                            proc.communicate(timeout=1)
                            return json.dumps({"error": "cancelled"})
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
                    "sync": {"type": "boolean", "description": "false=fire-and-forget(default, returns task_id to collect later), true=blocking"},
                },
                "required": ["command"]
            }
        }
    }, handler, toolset="core", sync=False)
