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
    """Two-phase KB sub-agent: Phase 1 search → Phase 2 meta review (conditional)."""

    MAX_SEARCHES = 3
    MAX_KB_GET = 3
    MAX_TURNS = 8

    # ── Phase 1: Search & Explore ──
    PHASE1_TOOLS = [
        {
            "type": "function",
            "function": {
                "name": "kb_search",
                "description": "Search KB with embeddings+BM25. Returns candidates with meta.",
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
                "description": "Get full document by ID. MAX 3 calls total.",
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
                "name": "kb_phase1_done",
                "description": "End search phase. Report findings and suggestions.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "findings": {
                            "type": "array",
                            "description": "Documents found. Each: {doc_id, title, relevance, confidence, note}",
                            "items": {"type": "object"},
                        },
                        "suggestions": {
                            "type": "array",
                            "description": "For the main agent. Each: {action: add|fix_meta|search_external, topic, reason, priority}",
                            "items": {"type": "object"},
                        },
                        "needs_meta_review": {
                            "type": "boolean",
                            "description": "True if any retrieved docs need meta fixes (missing level, wrong type, etc.)",
                        },
                    },
                    "required": ["findings", "suggestions", "needs_meta_review"],
                },
            },
        },
    ]

    PHASE1_SYSTEM = """你是知识库检索子代理（搜索阶段）。

任务：根据查询搜索知识库，阅读 meta 质量，refine 直到满意。

meta 字段说明：
- type: "reference"|"tutorial"|"example"|"faq" — 文档类型
- level: "beginner"|"intermediate"|"advanced" — 难度等级
- tags: string[] — 关键词标签
- related: string[] — 横向关联文档 ID
- parent: string — 上级文档 ID
- children: string[] — 下级文档 ID

流程：
1. kb_search(query) → 阅读每条结果的 meta 字段
2. 如需深入 → kb_get(doc_id)，最多 3 次
3. 如结果不够好 → 换关键词 refine，再 kb_search（最多 3 轮 search）
4. 完成后 → kb_phase1_done

注意：
- 本阶段只做检索和阅读，不修改 meta
- 如果你发现检索到的文档 meta 有缺陷（缺 level、type 不对等），
  设置 needs_meta_review=true，第二阶段会专门处理
- kb_search 会自动去重（已见过的 doc 不会重复返回），域不存在时会有提示"""

    # ── Phase 2: Meta Review ──
    PHASE2_TOOLS = [
        {
            "type": "function",
            "function": {
                "name": "kb_update_meta",
                "description": "Fix meta fields on a document (type, level, tags, related, etc.).",
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
                "name": "kb_phase2_done",
                "description": "End meta review. Report what was changed.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "meta_changes": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "doc_id": {"type": "string"},
                                    "field": {"type": "string"},
                                    "old": {},
                                    "new": {},
                                },
                            },
                        },
                    },
                    "required": ["meta_changes"],
                },
            },
        },
    ]

    PHASE2_SYSTEM = """你是知识库 meta 维护子代理（维护阶段）。

meta schema：
- type: "reference"|"tutorial"|"example"|"faq"
- level: "beginner"|"intermediate"|"advanced"
- tags: string[] (全小写，有意义的关键词)
- related: string[] (相关文档 ID)
- parent/children: string[] (层级关系)

任务：阅读下方检索历史中提到的每篇文档，检查 meta 质量，调用 kb_update_meta 修正。

[检索历史]
{history}

完成后调用 kb_phase2_done。"""

    def __init__(self, llm: LLMClient, kb: KnowledgeBase, trace: bool = False):
        self._llm = llm
        self._kb = kb
        self._trace = trace
        self._kb_get_count = 0
        self._search_count = 0
        self._seen_ids: set[str] = set()
        self._phase1_messages: list[dict] = []

    def run(self, query: str, domain: str | None = None) -> dict:
        self._kb_get_count = 0
        self._search_count = 0
        self._seen_ids = set()
        self._phase1_messages = []

        # ── Phase 1: Search ──
        phase1 = self._run_phase1(query, domain)

        # ── Phase 2: Meta Review (conditional) ──
        meta_changes = []
        if phase1.get("needs_meta_review"):
            meta_changes = self._run_phase2(phase1)

        # ── Build final report ──
        return {
            "findings": phase1.get("findings", []),
            "suggestions": phase1.get("suggestions", []),
            "meta_changes_made": meta_changes,
        }

    def _run_phase1(self, query: str, domain: str | None) -> dict:
        messages = [
            {"role": "system", "content": self.PHASE1_SYSTEM},
            {"role": "user", "content": f"[查询]\n{query}" + (f"\n[域]\n{domain}" if domain else "")},
        ]

        for turn in range(1, self.MAX_TURNS + 1):
            resp = self._llm.chat(messages=messages, tools=self.PHASE1_TOOLS)

            if resp.text and not resp.tool_calls:
                messages.append({"role": "assistant", "content": resp.text})
                continue
            if not resp.tool_calls:
                continue

            tool_results = []
            for tc in resp.tool_calls:
                name = tc.function.name
                args = json.loads(tc.function.arguments)
                if self._trace:
                    arg_summary = {k: v for k, v in args.items() if k != "findings"}
                    print(f"  [P1 turn {turn}] {name}({json.dumps(arg_summary, ensure_ascii=False)[:120]})")

                if name == "kb_phase1_done":
                    self._phase1_messages = messages
                    return args

                result = self._dispatch_phase1(name, args)
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

        self._phase1_messages = messages
        return {"findings": [], "suggestions": [], "needs_meta_review": False}

    def _dispatch_phase1(self, name: str, args: dict) -> dict:
        if name == "kb_search":
            self._search_count += 1
            if self._search_count > self.MAX_SEARCHES:
                return {"error": f"max {self.MAX_SEARCHES} searches reached, use kb_phase1_done to finish"}
            domain = args.get("domain")
            results = self._kb.search(**args)
            # System-side dedup: filter out already-seen IDs
            new_results = [r for r in results if r["id"] not in self._seen_ids]
            deduped = len(results) - len(new_results)
            for r in new_results:
                doc = self._kb.get(r["id"])
                r["meta"] = doc.meta if doc else {}
            hint = ""
            if len(new_results) == 0:
                domains = [d["path"] for d in self._kb.list_domains()]
                if domain and domain not in domains:
                    avail = ", ".join(domains) if domains else "(empty)"
                    hint = f" | domain '{domain}' not found. Available: {avail}"
                elif domain:
                    hint = f" | 0 results in '{domain}'. Try broader query or different domain."
                else:
                    hint = " | 0 results. Try different query terms."
            return {
                "results": new_results,
                "count": len(new_results),
                "deduped": deduped,
                "hint": hint,
                "all_domains": [d["path"] for d in self._kb.list_domains()],
            }
        if name == "kb_get":
            self._kb_get_count += 1
            if self._kb_get_count > self.MAX_KB_GET:
                return {"status": "limit_exceeded", "reason": f"max {self.MAX_KB_GET} kb_get"}
            doc_id = (args.get("doc_id") or "").strip()
            if not doc_id:
                return {"status": "error", "reason": "empty doc_id"}
            self._seen_ids.add(doc_id)
            doc = self._kb.get(doc_id)
            return {"status": "ok", "doc": doc.to_dict()} if doc else {"status": "not_found"}
        return {"error": f"unknown: {name}"}

    def _run_phase2(self, phase1: dict) -> list[dict]:
        history = self._build_phase1_history(phase1)
        messages = [
            {"role": "system", "content": self.PHASE2_SYSTEM.format(history=history)},
            {"role": "user", "content": "请检查上述检索结果中所有文档的 meta 质量并修正。"},
        ]

        for turn in range(1, self.MAX_TURNS + 1):
            resp = self._llm.chat(messages=messages, tools=self.PHASE2_TOOLS)

            if resp.text and not resp.tool_calls:
                messages.append({"role": "assistant", "content": resp.text})
                continue
            if not resp.tool_calls:
                continue

            tool_results = []
            for tc in resp.tool_calls:
                name = tc.function.name
                args = json.loads(tc.function.arguments)
                if self._trace:
                    print(f"  [P2 turn {turn}] {name}(...)")

                if name == "kb_phase2_done":
                    return args.get("meta_changes", [])

                result = self._dispatch_phase2(name, args)
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

        return []

    def _dispatch_phase2(self, name: str, args: dict) -> dict:
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

    def _build_phase1_history(self, phase1: dict) -> str:
        lines = [f"原始查询: (见下方用户消息)", ""]
        lines.append("## 检索到的文档")
        for f in phase1.get("findings", []):
            lines.append(f"- {f.get('doc_id', '?')[:8]}: {f.get('title', '?')} (relevance={f.get('relevance', '?')})")
        lines.append("")
        lines.append("## 覆盖评估")
        cov = phase1.get("coverage", {})
        lines.append(f"  match_level: {cov.get('match_level', '?')}")
        if cov.get("gaps"):
            lines.append(f"  gaps: {', '.join(cov['gaps'])}")
        return "\n".join(lines)


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
