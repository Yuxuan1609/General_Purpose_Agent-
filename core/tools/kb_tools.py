"""KB tools for ToolRegistry: kb_query, kb_delete, kb_fill_gap.

These are the main-agent-facing tools. The sub-agents (SubAgentLoop, FillGapLoop)
internally use the lower-level functions from core/knowledge/tools.py.
"""
from __future__ import annotations
import json
import logging
import threading
from typing import Any

logger = logging.getLogger(__name__)

_ASK_USER_TIMEOUT_S = 300
_ask_user_timed_out: bool = False


def _reset_ask_user_state():
    global _ask_user_timed_out
    _ask_user_timed_out = False

logger = logging.getLogger(__name__)

KB_STORAGE = "data/knowledge"

_KB_SCHEMAS: dict[str, dict] = {}

_kb_instance = None
_kb_lock = __import__("threading").Lock()


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
                    "sync": {"type": "boolean", "description": "true=blocking(default), false=fire-and-forget returns task_id"},
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
                    "sync": {"type": "boolean", "description": "true=blocking(default), false=fire-and-forget returns task_id"},
                },
                "required": ["doc_id"],
            },
        },
    }
    _KB_SCHEMAS["kb_modify"] = {
        "type": "function",
        "function": {
            "name": "kb_modify",
            "description": (
                "更新知识库文档的标题或内容。仅当确认文档有误时使用。"
                "不填的字段保持不变。知识库仅保存低时效敏感、易于验证的客观信息。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "doc_id": {"type": "string", "description": "要更新的文档 ID"},
                    "title": {"type": "string", "description": "新标题（不填则不变）"},
                    "content": {"type": "string", "description": "新内容（不填则不变）"},
                    "domain": {"type": "string", "description": "新 domain（不填则不变）"},
                    "reason": {"type": "string", "description": "更新原因"},
                    "sync": {"type": "boolean", "description": "true=blocking(default), false=fire-and-forget returns task_id"},
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
                    "sync": {"type": "boolean", "description": "false=fire-and-forget(default, returns task_id to collect later), true=blocking"},
                },
                "required": ["domain", "topic"],
            },
        },
    }

    registry.register("kb_query", _schema("kb_query"), _kb_query_handler, toolset="core", force_sync=True)
    registry.register("kb_delete", _schema("kb_delete"), _kb_delete_handler, toolset="core")
    registry.register("kb_modify", _schema("kb_modify"), _kb_modify_handler, toolset="core")
    registry.register("kb_fill_gap", _schema("kb_fill_gap"), _kb_fill_gap_handler, toolset="core", sync=False)

    _KB_SCHEMAS["ask_user"] = {
        "type": "function",
        "function": {
            "name": "ask_user",
            "description": "向用户提问以获取缺失的信息。最后一招，在搜索工具都无法满足时使用。必须同步(sync=true)。",
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {"type": "string", "description": "要问用户的问题"},
                    "sync": {"type": "boolean", "description": "true=blocking(default, must block), false=not supported"},
                },
                "required": ["question"],
            },
        },
    }
    registry.register("ask_user", _schema("ask_user"), _ask_user_handler, toolset="core")


def _ask_user_handler(args: dict | None = None, **kwargs) -> str:
    global _ask_user_timed_out
    question = (args or {}).get("question", "")
    if not question:
        return json.dumps({"response": "(no question)"})

    _TIMEOUT_MSG = json.dumps({
        "response": "",
        "error": ("TIMEOUT: User did not respond within 300 seconds. "
                  "Do NOT call ask_user again in this session — make decisions "
                  "with available information and other tools.")
    })

    if _ask_user_timed_out:
        return _TIMEOUT_MSG

    try:
        import tkinter as tk
        root = tk.Tk()
        try:
            root.withdraw()
        finally:
            root.destroy()
        return _ask_user_dialog(question, _TIMEOUT_MSG)
    except Exception:
        logger.exception("tkinter ask_user failed, falling back to console")
        return _ask_user_console(question, _TIMEOUT_MSG)


def _ask_user_dialog(question: str, timeout_msg: str) -> str:
    global _ask_user_timed_out
    result = {"response": ""}
    lock = threading.Lock()
    done = threading.Event()

    import tkinter as tk
    from tkinter import simpledialog

    root = tk.Tk()
    root.withdraw()
    root.attributes('-topmost', True)

    def _on_timeout():
        root.destroy()
        done.set()

    root.after(_ASK_USER_TIMEOUT_S * 1000, _on_timeout)

    response = simpledialog.askstring("Agent asks", question, parent=root)
    root.destroy()

    if not done.is_set():
        result["response"] = response or "(no response)"
        done.set()
        return json.dumps(result)

    _ask_user_timed_out = True
    return timeout_msg


def _ask_user_console(question: str, timeout_msg: str) -> str:
    global _ask_user_timed_out
    result = [None]
    done = threading.Event()

    def _read_input():
        try:
            print(f"\n[Agent]: {question}")
            print(f"(timeout in {_ASK_USER_TIMEOUT_S}s)")
            response = input("> ")
            if not done.is_set():
                result[0] = response or "(no response)"
            done.set()
        except Exception as e:
            if not done.is_set():
                result[0] = f"(input error: {e})"
            done.set()

    t = threading.Thread(target=_read_input, daemon=True)
    t.start()
    done.wait(timeout=_ASK_USER_TIMEOUT_S)

    if not done.is_set():
        _ask_user_timed_out = True
        done.set()
        print(f"\n[Agent] ask_user timed out after {_ASK_USER_TIMEOUT_S}s. "
              "Agent will not call ask_user again this session.")
        return timeout_msg

    response = result[0]
    if response is not None:
        return json.dumps({"response": response})
    return timeout_msg


def _get_kb():
    global _kb_instance
    if _kb_instance is None:
        with _kb_lock:
            if _kb_instance is None:
                from core.knowledge.knowledge_base import KnowledgeBase
                _kb_instance = KnowledgeBase(KB_STORAGE)
                _kb_instance.load()
    return _kb_instance


def _get_llm():
    from core.llm_factory import build_llm_client
    return build_llm_client(temperature=0.1)



def _kb_query_handler(args: dict | None = None, **kwargs) -> str:
    query = (args or {}).get("query", "")
    domain = (args or {}).get("domain")
    if not query:
        return json.dumps({"error": "No query provided"})
    try:
        from scripts.interactive_kb_agent import SubAgentLoop
        kb = _get_kb()
        llm = _get_llm()
        agent = SubAgentLoop(llm, kb, trace=False)
        result = agent.run(query, domain)
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        logger.exception("kb_query failed")
        return json.dumps({"error": str(e)})


def _kb_delete_handler(args: dict | None = None, **kwargs) -> str:
    doc_id = (args or {}).get("doc_id", "")
    if not doc_id:
        return json.dumps({"status": "error", "reason": "empty doc_id"})
    try:
        kb = _get_kb()
        doc = kb.get(doc_id)
        if doc is None:
            return json.dumps({"status": "not_found", "doc_id": doc_id})
        title = doc.title
        kb.delete(doc_id)
        with _kb_lock:
            kb.save()
        return json.dumps({"status": "ok", "doc_id": doc_id, "title": title}, ensure_ascii=False)
    except Exception as e:
        logger.exception("kb_delete failed")
        return json.dumps({"status": "error", "reason": str(e)})


def _kb_modify_handler(args: dict | None = None, **kwargs) -> str:
    doc_id = (args or {}).get("doc_id", "")
    if not doc_id:
        return json.dumps({"status": "error", "reason": "empty doc_id"})
    try:
        kb = _get_kb()
        doc = kb.get(doc_id)
        if doc is None:
            return json.dumps({"status": "not_found", "doc_id": doc_id})
        fields = {}
        for key in ("title", "content", "domain", "content_type"):
            val = (args or {}).get(key)
            if val is not None and val != "":
                fields[key] = val
        if not fields:
            return json.dumps({"status": "ok", "doc_id": doc_id, "note": "no fields to update"})
        if not kb.update(doc_id, **fields):
            return json.dumps({"status": "not_found", "doc_id": doc_id})
        with _kb_lock:
            kb.save()
        return json.dumps({"status": "ok", "doc_id": doc_id, "updated": list(fields.keys())}, ensure_ascii=False)
    except Exception as e:
        logger.exception("kb_modify failed")
        return json.dumps({"status": "error", "reason": str(e)})


def _kb_fill_gap_handler(args: dict | None = None, **kwargs) -> str:
    suggestion = (args or {})
    domain = suggestion.get("domain", "")
    topic = suggestion.get("topic", "")
    if not domain or not topic:
        return json.dumps({"error": "domain and topic required"})
    try:
        from scripts.interactive_kb_agent import FillGapLoop
        kb = _get_kb()
        llm = _get_llm()
        agent = FillGapLoop(llm, kb, trace=False)
        result = agent.run(suggestion)
        with _kb_lock:
            kb.save()
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        logger.exception("kb_fill_gap failed")
        return json.dumps({"error": str(e)})
