"""KB tools for ToolRegistry: kb_query, kb_delete, kb_fill_gap.

These are the main-agent-facing tools. The sub-agents (SubAgentLoop, FillGapLoop)
internally use the lower-level functions from core/knowledge/tools.py.
"""
from __future__ import annotations
import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

KB_STORAGE = "data/knowledge"

_KB_SCHEMAS: dict[str, dict] = {}


def _schema(name: str) -> dict:
    return _KB_SCHEMAS.get(name, {})


def register_kb_tools(registry):
    _KB_SCHEMAS["kb_query"] = {
        "type": "function",
        "function": {
            "name": "kb_query",
            "description": (
                "深度查询知识库：搜索→读meta→refine→修正meta→返回findings+suggestions。"
                "知识库仅保存低时效敏感、易于验证的客观信息（成熟框架文档、法律条文等）。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "搜索查询"},
                    "domain": {"type": "string", "description": "可选 domain 过滤"},
                },
                "required": ["query"],
            },
        },
    }
    _KB_SCHEMAS["kb_delete"] = {
        "type": "function",
        "function": {
            "name": "kb_delete",
            "description": (
                "删除知识库中的文档。仅当你确认文档过时或错误时使用。"
                "知识库仅保存低时效敏感、易于验证的客观信息。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "doc_id": {"type": "string", "description": "要删除的文档 ID"},
                    "reason": {"type": "string", "description": "删除原因"},
                },
                "required": ["doc_id"],
            },
        },
    }
    _KB_SCHEMAS["kb_fill_gap"] = {
        "type": "function",
        "function": {
            "name": "kb_fill_gap",
            "description": (
                "填补知识库缺口：KB确认→外部工具搜索→提案（不直接保存）。"
                "知识库仅保存低时效敏感、易于验证的客观信息。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "domain": {"type": "string", "description": "目标 domain（来自 kb_query suggestions）"},
                    "topic": {"type": "string", "description": "需填补的主题（来自 kb_query suggestions）"},
                    "reason": {"type": "string", "description": "为什么需要填补（来自 kb_query suggestions）"},
                    "priority": {"type": "string", "enum": ["high", "medium", "low"]},
                    "existing_doc_ids": {
                        "type": "array", "items": {"type": "string"},
                        "description": "Phase 1 已检索到的相关文档 ID",
                    },
                    "user_context": {"type": "string", "description": "用户补充的信息（仅在 ask_user 后重新调用时填写）"},
                },
                "required": ["domain", "topic"],
            },
        },
    }

    registry.register("kb_query", _schema("kb_query"), _kb_query_handler, toolset="core")
    registry.register("kb_delete", _schema("kb_delete"), _kb_delete_handler, toolset="core")
    registry.register("kb_fill_gap", _schema("kb_fill_gap"), _kb_fill_gap_handler, toolset="core")

    # ── ask_user: available to both main agent and fill-gap sub-agent ──
    _KB_SCHEMAS["ask_user"] = {
        "type": "function",
        "function": {
            "name": "ask_user",
            "description": "向用户提问以获取缺失的信息。最后一招，在搜索工具都无法满足时使用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {"type": "string", "description": "要问用户的问题"},
                },
                "required": ["question"],
            },
        },
    }
    registry.register("ask_user", _schema("ask_user"), _ask_user_handler, toolset="core")


def _ask_user_handler(args: dict | None = None) -> str:
    question = (args or {}).get("question", "")
    return json.dumps({
        "status": "waiting",
        "question": question,
        "note": "用户回复后将通过 user_context 继续任务",
    })


def _get_kb():
    from core.knowledge.knowledge_base import KnowledgeBase
    return KnowledgeBase(KB_STORAGE)


def _get_llm():
    from core.llm_factory import build_llm_client
    return build_llm_client(temperature=0.1)


def _kb_query_handler(args: dict | None = None) -> str:
    query = (args or {}).get("query", "")
    domain = (args or {}).get("domain")
    if not query:
        return json.dumps({"error": "No query provided"})
    try:
        from scripts.interactive_kb_agent import SubAgentLoop
        kb = _get_kb()
        kb.load()
        llm = _get_llm()
        agent = SubAgentLoop(llm, kb, trace=False)
        result = agent.run(query, domain)
        kb.close()
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        logger.exception("kb_query failed")
        return json.dumps({"error": str(e)})


def _kb_delete_handler(args: dict | None = None) -> str:
    doc_id = (args or {}).get("doc_id", "")
    if not doc_id:
        return json.dumps({"status": "error", "reason": "empty doc_id"})
    try:
        kb = _get_kb()
        kb.load()
        doc = kb.get(doc_id)
        if doc is None:
            kb.close()
            return json.dumps({"status": "not_found", "doc_id": doc_id})
        title = doc.title
        kb.delete(doc_id)
        kb.save()
        kb.close()
        return json.dumps({"status": "ok", "doc_id": doc_id, "title": title}, ensure_ascii=False)
    except Exception as e:
        logger.exception("kb_delete failed")
        return json.dumps({"status": "error", "reason": str(e)})


def _kb_fill_gap_handler(args: dict | None = None) -> str:
    suggestion = (args or {})
    domain = suggestion.get("domain", "")
    topic = suggestion.get("topic", "")
    if not domain or not topic:
        return json.dumps({"error": "domain and topic required"})
    try:
        from scripts.interactive_kb_agent import FillGapLoop
        kb = _get_kb()
        kb.load()
        llm = _get_llm()
        agent = FillGapLoop(llm, kb, trace=False)
        result = agent.run(suggestion)
        kb.close()
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        logger.exception("kb_fill_gap failed")
        return json.dumps({"error": str(e)})
