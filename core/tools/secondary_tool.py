"""Secondary tool activation — Agent searches and enables secondary tools on demand."""
from __future__ import annotations
import json
import logging

logger = logging.getLogger(__name__)

_test_llm = None


def _set_llm_for_test(llm):
    """Inject a fake LLM client for testing."""
    global _test_llm
    _test_llm = llm


def _get_llm():
    if _test_llm is not None:
        return _test_llm
    from core.runtime_registry import get_executor
    executor = get_executor()
    if executor is not None:
        return executor._llm
    from core.llm_factory import build_llm_client
    return build_llm_client(temperature=0.1)


def _activate_secondary_tools_handler(args: dict | None = None, **kwargs) -> str:
    from core.tools.registry import ToolRegistry

    args = args or {}
    query = args.get("query", "")
    top_k = args.get("top_k", 10)

    if not query:
        return json.dumps({"error": "query is required"})

    registry = ToolRegistry()
    with registry._lock:
        candidates = [
            {"name": e.name, "semantic_description": e.semantic_description}
            for e in registry._entries.values()
            if e.tool_spec == "secondary"
        ]

    if not candidates:
        return json.dumps({"enabled": [], "total_candidates": 0})

    index_text = "\n".join(
        f"- {c['name']}: {c['semantic_description']}" for c in candidates
    )

    prompt = (
        f"你是一个工具匹配系统。以下是可以用的次级工具列表：\n\n"
        f"{index_text}\n\n"
        f"用户需要以下功能的工具：\n"
        f'"{query}"\n\n'
        f"请从上面的列表中选出最匹配的工具（最多 {top_k} 个），以 JSON 格式返回。\n"
        f"如果所有工具都不匹配，返回空列表。\n\n"
        f'输出格式：\n'
        f'{{"tools": [{{"name": "tool_name", "reason": "为什么匹配"}}]}}'
    )

    messages = [
        {"role": "system", "content": "你是一个工具匹配系统，只输出 JSON。"},
        {"role": "user", "content": prompt},
    ]

    try:
        llm = _get_llm()
        resp = llm.chat(messages=messages, json_mode=True)
        text = resp.text if hasattr(resp, "text") else str(resp)
        parsed = json.loads(text)
        matched_names = [t.get("name", "") for t in parsed.get("tools", [])]
    except Exception as e:
        logger.warning("activate_secondary_tools LLM call failed: %s", e)
        return json.dumps({"error": str(e), "total_candidates": len(candidates)})

    count = registry.enable_secondary(matched_names)
    return json.dumps({
        "enabled": [n for n in matched_names if n],
        "total_candidates": len(candidates),
    }, ensure_ascii=False)


def register_secondary_tool(registry):
    """Register activate_secondary_tools as a primary tool visible to all layers."""
    registry.register(
        "activate_secondary_tools",
        {
            "type": "function",
            "function": {
                "name": "activate_secondary_tools",
                "description": (
                    "搜索并激活可用的次级工具。用自然语言描述需求，系统会匹配并启用合适的次工具。"
                    "激活后的工具在当前 session 内对所有层可见。"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "用自然语言描述你需要什么功能的工具",
                        },
                        "top_k": {
                            "type": "integer",
                            "description": "最多激活 N 个工具，默认 10",
                            "default": 10,
                        },
                    },
                    "required": ["query"],
                    "additionalProperties": False,
                },
            },
        },
        _activate_secondary_tools_handler,
        sync=True,
        toolset="core",
        tool_spec="primary",
    )
