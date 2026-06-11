"""Tool proposal tool — agent proposes new tools, human reviews."""
import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_proposal_dir: Path | None = None


def set_proposal_dir(directory: Path) -> None:
    global _proposal_dir
    _proposal_dir = directory
    _proposal_dir.mkdir(parents=True, exist_ok=True)


def register_tool_proposal(registry):
    def handler(args=None, context=None):
        name = (args or {}).get("name", "")
        description = (args or {}).get("description", "")
        schema = (args or {}).get("schema", {})
        rationale = (args or {}).get("rationale", "")

        if not name or not description:
            return json.dumps({"error": "name and description are required"})

        proposal = {
            "name": name,
            "description": description,
            "schema": schema,
            "rationale": rationale,
        }

        if _proposal_dir:
            filename = _proposal_dir / f"{name}.json"
            filename.write_text(json.dumps(proposal, ensure_ascii=False, indent=2),
                               encoding="utf-8")

        return json.dumps({
            "success": True,
            "message": f"Tool proposal '{name}' saved for human review",
        }, ensure_ascii=False)

    registry.register("tool_proposal", {
        "type": "function",
        "function": {
            "name": "tool_proposal",
            "description": (
                "Propose a new tool for registration. "
                "The proposal is saved for manual review — it does NOT register automatically."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Proposed tool name",
                    },
                    "description": {
                        "type": "string",
                        "description": "What the tool does and when to use it",
                    },
                    "schema": {
                        "type": "object",
                        "description": "OpenAI function-calling parameter schema (properties, required)",
                    },
                    "rationale": {
                        "type": "string",
                        "description": "Why this tool is needed and which layer(s) should access it",
                    },
                },
                "required": ["name", "description"],
            },
        },
    }, handler, toolset="core")
