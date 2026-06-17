"""Domain creation tool — L1 can create new domain nodes."""
import json
import logging

logger = logging.getLogger(__name__)

_registry = None


def set_domain_registry(reg) -> None:
    global _registry
    _registry = reg


def register_create_domain(tool_registry):
    def handler(args=None, context=None, **kwargs):
        path = (args or {}).get("path", "")
        parent = (args or {}).get("parent", "general")
        description = (args or {}).get("description", "")
        relations = (args or {}).get("relations", "")

        if not path:
            return json.dumps({"error": "path is required"})
        if not description:
            return json.dumps({"error": "description is required"})

        if _registry is None:
            return json.dumps({"error": "DomainRegistry not connected"})

        try:
            _registry.add_node(path, parent, description, {}, relations)
            return json.dumps({
                "success": True,
                "message": f"Domain '{path}' created under '{parent}'",
            }, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"error": str(e)})

    tool_registry.register("create_domain", {
        "type": "function",
        "function": {
            "name": "create_domain",
            "description": (
                "Create a new domain node in the domain registry. "
                "Use when encountering a task in an unregistered domain — "
                "register it so L2/L3 can build knowledge cards and skills for it."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Domain path, e.g. 'coding/python' or 'game/mahjong'. Use '/' to nest under parent.",
                    },
                    "parent": {
                        "type": "string",
                        "description": "Parent domain path. Default: 'general'. Use existing domain as parent when possible.",
                    },
                    "description": {
                        "type": "string",
                        "description": "Brief description of this domain (1-2 sentences, what kind of tasks it covers)",
                    },
                    "relations": {
                        "type": "string",
                        "description": "Related domains or notes, e.g. 'sibling of game/leduc'. Optional.",
                    },
                    "sync": {
                        "type": "boolean",
                        "description": "true=blocking(default), false=fire-and-forget returns task_id",
                    },
                },
                "required": ["path", "description"],
            },
        },
    }, handler, toolset="core")
