"""File system tools — read_file & grep."""
from __future__ import annotations
import json
import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

_root_for_paths: Path | None = None


def set_workspace_root(root: Path) -> None:
    global _root_for_paths
    _root_for_paths = root.resolve()


def _validate_path(path_str: str) -> Path:
    target = Path(path_str)
    if not target.is_absolute():
        if _root_for_paths is None:
            raise ValueError(
                "Relative paths require workspace root. "
                "Call set_workspace_root() first."
            )
        target = (_root_for_paths / target).resolve()
    else:
        target = target.resolve()

    if _root_for_paths and not str(target).startswith(str(_root_for_paths)):
        raise ValueError(
            f"Path '{target}' is outside workspace root '{_root_for_paths}'"
        )

    blocked = {"..", "~", "$", "`", "|", ";"}
    for segment in target.parts:
        if any(b in segment for b in blocked):
            raise ValueError(f"Dangerous path segment: {segment}")

    return target


def register_read_file(registry):
    def handler(args=None, timeout=10):
        path_str = (args or {}).get("path", "")
        if not path_str:
            return json.dumps({"error": "No path provided"})

        try:
            target = _validate_path(path_str)
        except ValueError as e:
            return json.dumps({"error": str(e)})

        if not target.exists():
            return json.dumps({"error": f"File not found: {target}"})
        if not target.is_file():
            return json.dumps({"error": f"Not a file: {target}"})

        try:
            offset = max(1, int((args or {}).get("offset", 1)))
            limit = min(int((args or {}).get("limit", 200)), 2000)
            content = target.read_text(encoding="utf-8", errors="replace")
            lines = content.splitlines()
            total = len(lines)
            start = offset - 1
            end = min(start + limit, total)
            selected = lines[start:end]
        except Exception as e:
            return json.dumps({"error": str(e)})

        result_lines = []
        for i, line in enumerate(selected, start=start + 1):
            result_lines.append(f"{i}: {line}")

        return json.dumps({
            "path": str(target),
            "total_lines": total,
            "offset": offset,
            "content": "\n".join(result_lines),
        }, ensure_ascii=False)

    registry.register("read_file", {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": (
                "Read content from a file with optional offset and line limit. "
                "Returns numbered lines."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Absolute or workspace-relative path to the file",
                    },
                    "offset": {
                        "type": "integer",
                        "description": "Start line (1-indexed, default 1)",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max lines to read (default 200, max 2000)",
                    },
                },
                "required": ["path"],
            },
        },
    }, handler, toolset="core")


def register_grep(registry):
    def handler(args=None, timeout=10):
        pattern = (args or {}).get("pattern", "")
        if not pattern:
            return json.dumps({"error": "No pattern provided"})

        search_path = (args or {}).get("path", "")
        include = (args or {}).get("include", "*")

        if search_path:
            try:
                target = _validate_path(search_path)
            except ValueError as e:
                return json.dumps({"error": str(e)})
            if not target.exists():
                return json.dumps({"error": f"Path not found: {target}"})
            search_dir = str(target)
        elif _root_for_paths:
            search_dir = str(_root_for_paths)
        else:
            return json.dumps({"error": "No path or workspace root configured"})

        try:
            return _grep_rg(search_dir, pattern, include)
        except (FileNotFoundError, Exception):
            return _grep_python(search_dir, pattern, include)

    registry.register("grep", {
        "type": "function",
        "function": {
            "name": "grep",
            "description": (
                "Search file contents with regex pattern. "
                "Returns matching file paths, line numbers, and line content. "
                "Uses ripgrep (rg) when available, Python fallback otherwise."
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
                        "description": (
                            "Directory to search in. "
                            "Default: workspace root"
                        ),
                    },
                    "include": {
                        "type": "string",
                        "description": (
                            "File glob pattern to filter (e.g. '*.py', '*.{ts,tsx}'). "
                            "Default: all files"
                        ),
                    },
                },
                "required": ["pattern"],
            },
        },
    }, handler, toolset="core")


def _grep_rg(search_dir: str, pattern: str, include: str) -> str:
    cmd = ["rg", "--line-number", "--no-heading", pattern, search_dir]
    if include and include != "*":
        cmd.extend(["--glob", include])

    result = subprocess.run(
        cmd, capture_output=True, text=True, timeout=30,
    )
    lines = result.stdout.strip().splitlines()[:50]
    return json.dumps({"matches": lines, "count": len(lines)}, ensure_ascii=False)


def _grep_python(search_dir: str, pattern: str, include: str) -> str:
    import re
    from pathlib import Path as P

    try:
        compiled = re.compile(pattern)
    except re.error as e:
        return json.dumps({"error": f"Invalid regex: {e}"})

    matches: list[str] = []
    root = P(search_dir)
    glob_pattern = f"**/{include}" if include and include != "*" else "**/*"

    for f in sorted(root.glob(glob_pattern)):
        if not f.is_file():
            continue
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            if compiled.search(line):
                rel = str(f.relative_to(root)) if f.is_relative_to(root) else str(f)
                matches.append(f"{rel}:{i}: {line[:200]}")
            if len(matches) >= 50:
                break
        if len(matches) >= 50:
            break

    return json.dumps({"matches": matches, "count": len(matches)}, ensure_ascii=False)
