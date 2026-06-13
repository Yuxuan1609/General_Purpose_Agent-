"""Mini interactive KB agent — while-true loop + conversation context + KB tools.

Usage: python scripts/interactive_kb_agent.py
 Type /help for commands, /quit to exit.
"""
from __future__ import annotations
import json
import os
import sys
from pathlib import Path
from datetime import datetime, timezone

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import yaml
from openai import OpenAI

from core.env_loader import load_env
from core.llm_client import LLMClient
from core.knowledge.knowledge_base import KnowledgeBase
from core.knowledge.models import KnowledgeDoc


SYSTEM_PROMPT = """你是一个知识助手，能搜索和维护一个静态知识库。

你有以下工具：
- kb_query(query, domain?) — 深度查询：搜索 → 读 meta → refine → 返回 findings + suggestions
- kb_search(query, domain?) — 快速关键词搜索
- kb_get(doc_id) — 获取完整文档内容
- kb_add(domain, title, content, meta) — 添加新文档到知识库
- kb_list_domains() — 浏览已有的领域目录
- kb_update_meta(doc_id, meta) — 修正文档的 meta 字段

使用建议：
- 用户问"XX 是什么/怎么做" → 用 kb_query 做深度查询
- 用户问"有没有 XX" → 用 kb_search 快速搜
- kb_query 返回的 suggestions 中如果建议 add → 判断是否该补文档
- 如果知识库没有答案 → 诚实告知，并建议用 kb_add 补充"""

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "kb_query",
            "description": "Deep KB query: search → read meta → refine → report findings + suggestions.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                    "domain": {"type": "string", "description": "Optional domain filter"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "kb_search",
            "description": "Fast keyword search in knowledge base.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "domain": {"type": "string"},
                    "top_k": {"type": "integer", "default": 5},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "kb_get",
            "description": "Get full content of a single document by ID.",
            "parameters": {
                "type": "object",
                "properties": {
                    "doc_id": {"type": "string"},
                },
                "required": ["doc_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "kb_add",
            "description": "Add a new document to the knowledge base.",
            "parameters": {
                "type": "object",
                "properties": {
                    "domain": {"type": "string"},
                    "title": {"type": "string"},
                    "content": {"type": "string", "description": "Markdown content"},
                    "meta": {
                        "type": "object",
                        "properties": {
                            "type": {"type": "string", "enum": ["reference", "tutorial", "example", "faq"]},
                            "level": {"type": "string", "enum": ["beginner", "intermediate", "advanced"]},
                            "tags": {"type": "array", "items": {"type": "string"}},
                        },
                    },
                },
                "required": ["domain", "title", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "kb_list_domains",
            "description": "List all domains in the knowledge base.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "kb_update_meta",
            "description": "Fix/improve meta fields on a document (type, level, tags).",
            "parameters": {
                "type": "object",
                "properties": {
                    "doc_id": {"type": "string"},
                    "meta": {"type": "object"},
                },
                "required": ["doc_id", "meta"],
            },
        },
    },
]


class InteractiveAgent:
    """Simple while-true agent with conversation history and tool calling."""

    MAX_TOOL_TURNS = 10

    def __init__(self, kb: KnowledgeBase):
        self._kb = kb
        self._llm = self._build_llm()
        self._messages: list[dict] = []
        self._sub_agent = SubAgentLoop(self._llm, kb, trace=False)

    def _build_llm(self) -> LLMClient:
        load_env(PROJECT_ROOT)
        config_path = PROJECT_ROOT / "config.yaml"
        with open(config_path, encoding="utf-8") as f:
            raw = yaml.safe_load(f)
        cfg = raw.get("main_llm", {})
        oai = OpenAI(
            base_url=cfg.get("base_url", "https://api.deepseek.com"),
            api_key=os.environ.get(cfg.get("api_key_env", "DEEPSEEK_API_KEY"), ""),
        )
        llm = LLMClient(oai, cfg.get("model", "deepseek-v4-flash"))
        llm.temperature = 0.3
        return llm

    def start(self, system_prompt: str = SYSTEM_PROMPT):
        self._messages = [{"role": "system", "content": system_prompt}]
        print("Mini KB Agent ready. Type /help for commands.")
        self._loop()

    def _loop(self):
        while True:
            try:
                user_input = input("\nYou > ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\n/quit")
                break

            if not user_input:
                continue
            if user_input.startswith("/"):
                self._handle_command(user_input)
                continue

            self._messages.append({"role": "user", "content": user_input})
            self._chat_loop()

    def _chat_loop(self):
        for _ in range(self.MAX_TOOL_TURNS):
            resp = self._llm.chat(messages=self._messages, tools=TOOLS)

            if resp.text and not resp.tool_calls:
                _safe_print(f"\nAgent: {resp.text}")
                self._messages.append({"role": "assistant", "content": resp.text})
                return

            if not resp.tool_calls:
                return

            tool_results = []
            for tc in resp.tool_calls:
                name = tc.function.name
                args = json.loads(tc.function.arguments)
                print(f"\n  [tool] {name}(...)", end="", flush=True)
                result = self._dispatch(name, args)
                print(f" done")
                tool_results.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": json.dumps(result, ensure_ascii=False),
                })

            self._messages.append({
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    }
                    for tc in resp.tool_calls
                ],
            })
            self._messages.extend(tool_results)

        print("\nAgent: [reached max tool turns, stopping]")

    def _dispatch(self, name: str, args: dict) -> dict:
        if name == "kb_query":
            report = self._sub_agent.run(**args)
            report.pop("_trace", None)
            return report
        if name == "kb_search":
            results = self._kb.search(**args)
            for r in results:
                doc = self._kb.get(r["id"])
                r["meta"] = doc.meta if doc else {}
            return {"results": results, "count": len(results)}
        if name == "kb_get":
            doc = self._kb.get(args["doc_id"])
            return {"status": "ok", "doc": doc.to_dict()} if doc else {"status": "not_found"}
        if name == "kb_add":
            return self._handle_kb_add(**args)
        if name == "kb_list_domains":
            return {"domains": self._kb.list_domains()}
        if name == "kb_update_meta":
            return self._handle_update_meta(**args)
        return {"error": f"unknown tool: {name}"}

    def _handle_kb_add(self, domain: str, title: str, content: str,
                       meta: dict | None = None) -> dict:
        doc = KnowledgeDoc(domain=domain, title=title, content=content,
                           meta=meta or {}, source="agent")
        doc_ids = self._kb.add(doc)
        self._kb.save()
        return {"status": "ok", "doc_ids": doc_ids, "doc_id": doc_ids[0]}

    def _handle_update_meta(self, doc_id: str, meta: dict) -> dict:
        doc = self._kb.get(doc_id)
        if doc is None:
            return {"status": "not_found"}
        old = dict(doc.meta)
        self._kb.update_meta(doc_id, meta)
        self._kb.update(doc_id)
        self._kb.save()
        return {"status": "ok", "doc_id": doc_id, "old": old, "new": dict(doc.meta)}

    def _handle_command(self, cmd: str):
        if cmd == "/quit" or cmd == "/exit":
            print("Goodbye.")
            sys.exit(0)
        elif cmd == "/help":
            print("Commands: /quit, /clear, /domains, /docs")
        elif cmd == "/clear":
            self._messages = [self._messages[0]]
            print("Conversation cleared.")
        elif cmd == "/domains":
            for d in self._kb.list_domains():
                print(f"  {d['path']}: {d['doc_count']} docs")
        elif cmd == "/docs":
            for d in self._kb._docs.values():
                print(f"  [{d.id[:8]}] {d.domain}: {d.title}")


class SubAgentLoop:
    """Lightweight inline sub-agent for kb_query."""

    MAX_TURNS = 6

    SUB_TOOLS = [
        {
            "type": "function",
            "function": {
                "name": "kb_search",
                "description": "Search KB with embeddings+BM25.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "domain": {"type": "string"},
                        "top_k": {"type": "integer", "default": 10},
                    },
                    "required": ["query"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "kb_get",
                "description": "Get full document. MAX 3 calls.",
                "parameters": {
                    "type": "object",
                    "properties": {"doc_id": {"type": "string"}},
                    "required": ["doc_id"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "kb_update_meta",
                "description": "Fix meta fields on a document.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "doc_id": {"type": "string"},
                        "meta": {"type": "object"},
                    },
                    "required": ["doc_id", "meta"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "kb_report",
                "description": "END THE SEARCH. Final findings + suggestions.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "findings": {"type": "array", "items": {"type": "object"}},
                        "coverage": {
                            "type": "object",
                            "properties": {
                                "match_level": {"type": "string", "enum": ["direct", "partial", "none"]},
                                "gaps": {"type": "array", "items": {"type": "string"}},
                            },
                            "required": ["match_level"],
                        },
                        "suggestions": {"type": "array", "items": {"type": "object"}},
                        "meta_changes_made": {"type": "array", "items": {"type": "object"}},
                    },
                    "required": ["findings", "coverage", "suggestions"],
                },
            },
        },
    ]

    SUB_SYSTEM = """你是知识库检索子代理。职责：搜索、读 meta、修正问题、汇报。

流程：
1. kb_search → 读每条 meta
2. meta 不准 → kb_update_meta
3. 需深入 → kb_get (最多 3 次)
4. 不够好 → 换关键词 refine，再 kb_search
5. 完成 → kb_report

自主完成，不确认。kb_report 后禁止再调任何 tool。"""

    def __init__(self, llm: LLMClient, kb: KnowledgeBase, trace: bool = False):
        self._llm = llm
        self._kb = kb
        self._trace = trace
        self._kb_get_count = 0

    def run(self, query: str, domain: str | None = None) -> dict:
        self._kb_get_count = 0
        messages = [
            {"role": "system", "content": self.SUB_SYSTEM},
            {"role": "user", "content": f"[查询]\n{query}" + (f"\n[域]\n{domain}" if domain else "")},
        ]

        for turn in range(1, self.MAX_TURNS + 1):
            resp = self._llm.chat(messages=messages, tools=self.SUB_TOOLS)

            if resp.text and not resp.tool_calls:
                messages.append({"role": "assistant", "content": resp.text})
                continue
            if not resp.tool_calls:
                continue

            tool_results = []
            for tc in resp.tool_calls:
                name = tc.function.name
                args = json.loads(tc.function.arguments)
                if name == "kb_report":
                    return args
                result = self._sub_dispatch(name, args)
                tool_results.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": json.dumps(result, ensure_ascii=False),
                })

            messages.append({
                "role": "assistant", "content": None,
                "tool_calls": [
                    {"id": tc.id, "type": "function",
                     "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                    for tc in resp.tool_calls
                ],
            })
            messages.extend(tool_results)

        return {"error": "max_turns_exceeded"}

    def _sub_dispatch(self, name: str, args: dict) -> dict:
        if name == "kb_search":
            results = self._kb.search(**args)
            for r in results:
                doc = self._kb.get(r["id"])
                r["meta"] = doc.meta if doc else {}
            return {"results": results, "count": len(results)}
        if name == "kb_get":
            self._kb_get_count += 1
            if self._kb_get_count > 3:
                return {"status": "limit_exceeded", "reason": "max 3 kb_get"}
            doc = self._kb.get(args["doc_id"])
            return {"status": "ok", "doc": doc.to_dict()} if doc else {"status": "not_found"}
        if name == "kb_update_meta":
            doc = self._kb.get(args["doc_id"])
            if doc is None:
                return {"status": "not_found"}
            old = dict(doc.meta)
            self._kb.update_meta(args["doc_id"], args["meta"])
            self._kb.update(args["doc_id"])
            self._kb.save()
            return {"status": "ok", "doc_id": args["doc_id"], "old": old, "new": dict(doc.meta)}
        return {"error": f"unknown: {name}"}


def seed_test_kb(kb: KnowledgeBase):
    docs = [
        KnowledgeDoc(
            domain="ds/ml",
            title="Pandas DataFrame 入门",
            content="## 创建 DataFrame\n```python\npd.DataFrame({'A':[1,2],'B':[3,4]})\n```\n## 常用操作\ndf.head(), df.describe(), df['A']",
            meta={"type": "tutorial", "tags": ["pandas", "dataframe"]},
            source="seed",
        ),
        KnowledgeDoc(
            domain="ds/ml",
            title="Pandas GroupBy 聚合指南",
            content="## 基本用法\n```python\ndf.groupby('category')['value'].mean()\n```\n## 多列聚合\n```python\ndf.groupby('category').agg({'value':'mean','count':'sum'})\n```\n注意：groupby 返回 GroupBy 对象，需聚合函数触发。",
            meta={"type": "reference", "tags": ["pandas", "groupby"]},
            source="seed",
        ),
        KnowledgeDoc(
            domain="ds/ml",
            title="Python 列表操作备忘",
            content="## 基础\nappend, pop, sort\n## 列表推导\n```python\n[x*2 for x in range(10)]\n```",
            meta={"type": "reference"},
            source="seed",
        ),
        KnowledgeDoc(
            domain="devops/docker",
            title="Docker 基础命令",
            content="## 镜像\ndocker build, docker pull\n## 容器\ndocker run, docker ps, docker exec",
            meta={"type": "reference", "level": "beginner", "tags": ["docker"]},
            source="seed",
        ),
    ]
    for doc in docs:
        kb.add(doc)
    kb.save()


def _safe_print(text: str):
    """Print safely on Windows consoles that may not support all Unicode."""
    try:
        print(text)
    except UnicodeEncodeError:
        print(text.encode("ascii", errors="replace").decode("ascii"))


def main():
    print("=" * 50)
    print("Mini Interactive KB Agent")
    print("=" * 50)

    kb = KnowledgeBase("data/kb_mini_agent")
    kb.load()

    if not kb._docs:
        print("Seeding test knowledge base...")
        seed_test_kb(kb)

    print(f"\nLoaded {len(kb._docs)} docs in {len(kb._domains)} domains.")
    print(f"Domains: {', '.join(kb._domains.keys())}")

    agent = InteractiveAgent(kb)
    try:
        agent.start()
    finally:
        kb.close()


if __name__ == "__main__":
    main()
