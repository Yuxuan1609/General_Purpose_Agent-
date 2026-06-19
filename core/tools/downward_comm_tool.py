"""Downward comm tools — l1_query/l2_query as regular ToolRegistry tools.

Replaces the capture_tool pattern: Agent calls these tools in _call_llm tool loop,
handler synchronously calls downstream Manager.query + collect_notify, returns
downstream results as tool result for LLM to consume in same session.
"""
from __future__ import annotations
import json
from typing import Any

_downstreams: dict[str, Any] = {}


def set_layer_downstreams(mapping: dict[str, Any]) -> None:
    global _downstreams
    _downstreams.clear()
    _downstreams.update(mapping)


_L1_QUERY_SCHEMA = {
    "type": "function",
    "function": {
        "name": "l1_query",
        "description": (
            "【向下查询】当需要下层L2的策略知识辅助决策时使用。"
            "每次调用同步阻塞等待L2返回结果，可在同一会话内多次调用。"
            "禁止以文本方式直接回复！"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "queries": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "query": {"type": "string", "description": "向下层 L2 查询的问题"},
                            "domains_hint": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "建议查询的领域",
                            },
                        },
                    },
                    "description": "下发给 L2 的查询列表",
                },
                "reasoning": {"type": "string"},
                "sync": {"type": "boolean", "description": "true=blocking(default)"},
            },
            "required": ["queries", "reasoning"],
        },
    },
}

_L2_QUERY_SCHEMA = {
    "type": "function",
    "function": {
        "name": "l2_query",
        "description": (
            "【向下调度】当需要下层L3执行具体技能任务时使用。"
            "通过 queries_to_L3 下发任务，同步阻塞等待L3返回结果。"
            "禁止以文本方式直接回复！"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "queries_to_L3": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "domain": {"type": "string", "description": "目标领域"},
                            "task": {"type": "string", "description": "委托 L3 执行的技能任务"},
                        },
                    },
                    "description": "下发给 L3 的任务列表",
                },
                "selected_nodes": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string"},
                            "score": {"type": "number"},
                        },
                    },
                    "description": "选定的领域节点",
                },
                "reasoning": {"type": "string"},
                "sync": {"type": "boolean", "description": "true=blocking(default)"},
            },
            "required": ["queries_to_L3", "reasoning"],
        },
    },
}


def _extract_reply(notify: dict, layer_name: str) -> str:
    layer_notify = notify.get(layer_name, {})
    if isinstance(layer_notify, dict):
        return layer_notify.get("reply", "") or layer_notify.get("result", "")
    return ""


def _make_handler(tool_name: str):
    def handler(args=None, **kwargs):
        downstream = _downstreams.get(tool_name)
        if downstream is None:
            return json.dumps({"error": f"{tool_name}: downstream not bound"})

        args = args or {}
        queries = args.get("queries") or args.get("queries_to_L3") or []
        if not queries:
            return json.dumps({"error": "queries/queries_to_L3 required"})

        results = []
        for q in queries:
            query_text = q.get("query") or q.get("task") or ""
            domains_hint = q.get("domains_hint", [])

            from core.types import TaskObservation
            sub_obs = TaskObservation(
                meta=query_text,
                state={"domains_hint": domains_hint} if domains_hint else {},
            )
            downstream.query(sub_obs)
            notify = downstream.collect_notify()

            reply = _extract_reply(notify, downstream.name)
            results.append({
                "query": query_text,
                "reply": reply,
            })

        return json.dumps({"results": results}, ensure_ascii=False)

    return handler


def register_downward_tools(tool_registry):
    tool_registry.register(
        "l1_query", _L1_QUERY_SCHEMA,
        _make_handler("l1_query"), toolset="core", sync=True,
    )
    tool_registry.register(
        "l2_query", _L2_QUERY_SCHEMA,
        _make_handler("l2_query"), toolset="core", sync=True,
    )
