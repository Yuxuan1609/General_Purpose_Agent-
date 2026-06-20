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

知识库范围：仅保存低时效敏感、易于验证的客观信息。
正例：成熟框架文档（Pandas API 用法）、法律条文、已发布标准的规范。
反例：新闻资讯、开发中项目信息、个人观点、时效性强的数据。

你有以下工具：
- kb_query(query, domain?) — 深度查询：搜索 → 读 meta → refine → 返回 findings + suggestions
- kb_delete(doc_id) — 删除知识库中的文档（仅当你能验证该文档确实过时或错误）
- kb_fill_gap(domain, topic) — 填补知识缺口：根据 topic 生成内容 → 验证后保存到知识库

使用建议：
- 用户问查资料 → kb_query
- kb_query 返回的 suggestions 建议 add → kb_fill_gap
- 发现文档过时/错误且你能确认 → kb_delete
- 知识库没有答案 → 诚实告知，不要编造"""

KB_SCOPE_NOTE = " 知识库仅保存低时效敏感、易于验证的客观信息（成熟框架文档、法律条文等）。正例：Pandas API 用法。反例：新闻、开发中项目信息。"

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "kb_query",
            "description": "深度查询知识库：搜索 → 读 meta → refine → 返回 findings + suggestions。知识库范围：" + KB_SCOPE_NOTE[4:],
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "搜索查询"},
                    "domain": {"type": "string", "description": "可选 domain 过滤"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "kb_delete",
            "description": "删除知识库中的文档。仅当你确认文档确实过时或错误时使用。" + KB_SCOPE_NOTE,
            "parameters": {
                "type": "object",
                "properties": {
                    "doc_id": {"type": "string", "description": "要删除的文档 ID"},
                    "reason": {"type": "string", "description": "删除原因（过时/错误/重复）"},
                },
                "required": ["doc_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "kb_fill_gap",
            "description": "填补知识库缺口：根据 topic 生成/搜集准确内容 → 验证 → 保存。" + KB_SCOPE_NOTE,
            "parameters": {
                "type": "object",
                "properties": {
                    "domain": {"type": "string", "description": "目标 domain"},
                    "topic": {"type": "string", "description": "需要填补的主题"},
                },
                "required": ["domain", "topic"],
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
        self._fill_gap = FillGapLoop(self._llm, kb, trace=False)

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
            return report
        if name == "kb_delete":
            doc = self._kb.get(args["doc_id"])
            if doc is None:
                return {"status": "not_found", "doc_id": args["doc_id"]}
            self._kb.delete(args["doc_id"])
            self._kb.save()
            return {"status": "ok", "doc_id": args["doc_id"], "title": doc.title}
        if name == "kb_fill_gap":
            return self._fill_gap.run(**args)
        return {"error": f"unknown tool: {name}"}

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
                if domain:
                    hint = f" | 0 results in domain '{domain}'. Try broader query or remove domain filter."
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
        lines = ["## 检索到的文档"]
        for f in phase1.get("findings", []):
            lines.append(f"- {f.get('doc_id', '?')[:8]}: {f.get('title', '?')} (relevance={f.get('relevance', '?')})")
        lines.append("")
        lines.append("## 建议")
        for s in phase1.get("suggestions", []):
            lines.append(f"- [{s.get('action', '?')}] {s.get('topic', '?')}: {s.get('reason', '?')}")
        return "\n".join(lines)


class FillGapLoop:
    """Fill-gap v2: KB confirm → external tools → ask_user → propose (no direct kb_add)."""

    MAX_TURNS = 10
    MAX_EXTERNAL_TURNS = 5

    FILL_TOOLS = [
        # ── KB internal ──
        {
            "type": "function",
            "function": {
                "name": "kb_search",
                "description": "Quick KB search to confirm existing content before filling.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "domain": {"type": "string"},
                    },
                    "required": ["query"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "kb_get",
                "description": "Get full document content to understand existing coverage.",
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
                "name": "kb_add",
                "description": "Add a document to the knowledge base. Call this after researching and validating content.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "domain": {"type": "string"},
                        "title": {"type": "string"},
                        "content": {"type": "string"},
                        "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
                        "meta": {"type": "object"},
                    },
                    "required": ["domain", "title", "content"],
                },
            },
        },
        # ── External tools ──
        {
            "type": "function",
            "function": {
                "name": "web_search",
                "description": "Search the web via SearXNG (multi-engine).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "max_results": {"type": "integer", "default": 5},
                    },
                    "required": ["query"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "tavily_search",
                "description": "AI-optimized web search via Tavily. Use when web_search results are insufficient.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "max_results": {"type": "integer", "default": 5},
                    },
                    "required": ["query"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "terminal",
                "description": "Execute a shell command to verify info (e.g. python -c 'help()', man).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "command": {"type": "string", "description": "Shell command"},
                    },
                    "required": ["command"],
                },
            },
        },
        # ── Fallback ──
        {
            "type": "function",
            "function": {
                "name": "ask_user",
                "description": "Ask the user to provide missing information. Use as last resort when search tools fail.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "question": {"type": "string", "description": "What to ask the user"},
                    },
                    "required": ["question"],
                },
            },
        },
        # ── End ──
        {
            "type": "function",
            "function": {
                "name": "kb_fill_propose",
                "description": "Exit signal. Submit remaining unsaved proposals + skipped items. Use AFTER calling kb_add for quality content.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "proposals": {
                            "type": "array",
                            "description": "Content proposals ready for kb_add",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "domain": {"type": "string"},
                                    "title": {"type": "string"},
                                    "content": {"type": "string"},
                                    "meta": {"type": "object"},
                                    "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
                                    "sources": {"type": "array", "items": {"type": "string"}},
                                },
                                "required": ["domain", "title", "content", "meta", "confidence"],
                            },
                        },
                        "skipped": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "topic": {"type": "string"},
                                    "reason": {"type": "string"},
                                },
                            },
                        },
                        "needs_ask_user": {
                            "type": "object",
                            "properties": {
                                "question": {"type": "string"},
                            },
                        },
                    },
                    "required": ["proposals"],
                },
            },
        },
    ]

    FILL_SYSTEM = """你是知识库填补研究代理。

知识库范围：仅保存低时效敏感、易于验证的客观信息。
正例：成熟框架 API 用法、法律条文、已发布标准。
反例：新闻、开发中项目信息、个人观点。

操作流程：

Step 1: KB 确认（≤2 轮）
  kb_search(topic) → kb_get(相关文档) → 准确理解缺口范围

Step 2: 外部工具研究（**硬上限 5 轮**，每轮可多次调用 web_search/tavily_search/terminal）
  优先级：web_search > tavily_search > terminal
  达到 5 轮上限后禁止继续搜索

Step 3: 存档
  研究结果确认质量后 **必须调用 kb_add(domain, title, content, confidence, meta) 直接入库**
  - 高置信度、有可靠来源 → kb_add
  - 不确定或信息不足 → 不要调用 kb_add，改用 kb_fill_propose 的 proposals 或 skipped 报告

Step 4: 退出
  **必须调用 kb_fill_propose 退出循环**
  - proposals：无法直接 kb_add 的建议（低置信度/需审查）
  - skipped：信息不足无法完成的研究项
  - 不需要在 proposals 中重复已在 kb_add 中入库的内容

规则：
- 不确定的信息宁可 skipped 也不编造也不入库
- kb_add 的 content 必须是完整可用的文档内容（markdown 格式）
- meta 必须包含 type/tags/confidence/sources
- 达到外部工具上限后禁止继续搜索，立即存档并退出
- 禁止连续 2 轮以上纯文本回复（无 tool_call）——必须用工具"""

    def __init__(self, llm: LLMClient, kb: KnowledgeBase, trace: bool = False):
        self._llm = llm
        self._kb = kb
        self._trace = trace
        self._external_turns = 0
        self._saved_count = 0
        self._saved_titles: list[str] = []

    def run(self, suggestion: dict, user_context: str = "") -> dict:
        self._external_turns = 0
        self._saved_count = 0
        self._saved_titles = []
        domain = suggestion.get("domain", "")
        topic = suggestion.get("topic", "")
        reason = suggestion.get("reason", "")
        existing_ids = suggestion.get("existing_doc_ids", [])

        existing_summary = ""
        if existing_ids:
            titles = []
            for did in existing_ids[:5]:
                doc = self._kb.get(did)
                if doc:
                    titles.append(f"  - [{did[:8]}] {doc.title}")
            if titles:
                existing_summary = f"\n[已有相关文档]\n" + "\n".join(titles)

        user_msg = (
            f"[知识缺口]\ndomain: {domain}\ntopic: {topic}\nreason: {reason}"
            + existing_summary
            + (f"\n\n[用户补充]\n{user_context}" if user_context else "")
        )

        messages = [
            {"role": "system", "content": self.FILL_SYSTEM},
            {"role": "user", "content": user_msg},
        ]

        for turn in range(1, self.MAX_TURNS + 1):
            resp = self._llm.chat(messages=messages, tools=self.FILL_TOOLS)

            if resp.text and not resp.tool_calls:
                messages.append({"role": "assistant", "content": resp.text})
                continue
            if not resp.tool_calls:
                continue

            external_names = {"web_search", "tavily_search", "terminal"}
            has_external = any(tc.function.name in external_names for tc in resp.tool_calls)
            if has_external:
                self._external_turns += 1
                if self._external_turns > self.MAX_EXTERNAL_TURNS:
                    messages.append({
                        "role": "user",
                        "content": (
                            f"[系统] 你已达到外部工具轮次上限 ({self.MAX_EXTERNAL_TURNS} 轮)。"
                            f"请立即调用 kb_fill_propose 提交当前结果，不要再尝试任何搜索。"
                        ),
                    })
                    continue

            tool_results = []
            for tc in resp.tool_calls:
                name = tc.function.name
                args = json.loads(tc.function.arguments)
                if self._trace:
                    print(f"  [fill turn {turn}] {name}(...)")

                if name == "kb_fill_propose":
                    return {
                        **args,
                        "saved_count": self._saved_count,
                        "saved_titles": self._saved_titles,
                    }

                result = self._dispatch(name, args)
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

        return {"proposals": [], "skipped": [{"topic": suggestion.get("topic", ""), "reason": "max_turns_exceeded"}],
                "saved_count": self._saved_count, "saved_titles": self._saved_titles}

    def _dispatch(self, name: str, args: dict) -> dict:
        if name == "kb_search":
            results = self._kb.search(args.get("query", ""), domain=args.get("domain"))
            for r in results:
                doc = self._kb.get(r["id"])
                r["meta"] = doc.meta if doc else {}
            return {"results": results, "count": len(results)}
        if name == "kb_get":
            doc = self._kb.get(args.get("doc_id", ""))
            return {"status": "ok", "doc": doc.to_dict()} if doc else {"status": "not_found"}
        if name == "kb_add":
            from core.knowledge.models import KnowledgeDoc
            doc = KnowledgeDoc(
                domain=args.get("domain", ""),
                title=args.get("title", ""),
                content=args.get("content", ""),
                source="agent",
                meta={**(args.get("meta") or {}),
                      "confidence": args.get("confidence", "low")},
            )
            ids = self._kb.add(doc)
            self._kb.save()
            self._saved_count += 1
            self._saved_titles.append(doc.title)
            return {"status": "ok", "ids": ids, "title": doc.title}
        if name == "web_search":
            from core.tools.web_search_tool import _search_searxng, _search_ddgs
            r = _search_searxng(**args)
            if r is None:
                try:
                    r = _search_ddgs(**args)
                except Exception:
                    r = []
            return {"results": r or [], "count": len(r) if r else 0, "turns_used": self._external_turns, "limit": self.MAX_EXTERNAL_TURNS}
        if name == "tavily_search":
            from core.tools.web_search_tool import _search_tavily
            import os
            key = os.environ.get("TAVILY_API_KEY", "")
            r = _search_tavily(api_key=key, **args)
            return {"results": r, "count": len(r), "turns_used": self._external_turns, "limit": self.MAX_EXTERNAL_TURNS}
        if name == "terminal":
            import subprocess
            try:
                result = subprocess.run(
                    args["command"], shell=True, capture_output=True, text=True,
                    timeout=15, cwd=self._kb._storage_path,
                )
                return {"stdout": result.stdout[-2000:], "stderr": result.stderr[-500:], "rc": result.returncode, "turns_used": self._external_turns, "limit": self.MAX_EXTERNAL_TURNS}
            except Exception as e:
                return {"error": str(e)}
        if name == "ask_user":
            return {
                "status": "waiting",
                "question": args.get("question", ""),
                "note": "main_agent_will_relay_this_question_to_the_user_and_reinvoke_fill_gap_with_user_context",
            }
        return {"error": f"unknown: {name}"}
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
