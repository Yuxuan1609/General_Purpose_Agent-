"""KB Query Sub-Agent standalone test script.

Creates a KB with seeded test docs, runs the sub-agent with a real LLM,
verifies the sub-agent can: search → read meta → kb_get links → fix meta → kb_report.
"""
from __future__ import annotations
import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import yaml
from openai import OpenAI

from core.env_loader import load_env
from core.llm_client import LLMClient
from core.knowledge.knowledge_base import KnowledgeBase
from core.knowledge.models import KnowledgeDoc


SUB_AGENT_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "kb_search",
            "description": "Search knowledge base with embeddings+BM25. Returns candidates with full meta.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                    "domain": {"type": "string", "description": "Optional domain filter"},
                    "top_k": {"type": "integer", "description": "Max results (default 10)"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "kb_get",
            "description": "Get full content of single document by ID. Use to follow parent/children/related links. HARD LIMIT: 3 calls total.",
            "parameters": {
                "type": "object",
                "properties": {
                    "doc_id": {"type": "string", "description": "Document ID to fetch"},
                },
                "required": ["doc_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "kb_update_meta",
            "description": "Fix/improve meta fields on a document (type, level, tags, related, etc.) while exploring.",
            "parameters": {
                "type": "object",
                "properties": {
                    "doc_id": {"type": "string", "description": "Document ID"},
                    "meta": {"type": "object", "description": "Meta fields to set (shallow merge)"},
                },
                "required": ["doc_id", "meta"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "kb_report",
            "description": "END THE SEARCH. Report findings, coverage assessment, and suggestions for the main agent. Call this as your final action.",
            "parameters": {
                "type": "object",
                "properties": {
                    "findings": {
                        "type": "array",
                        "description": "Documents found and their relevance",
                        "items": {
                            "type": "object",
                            "properties": {
                                "doc_id": {"type": "string"},
                                "title": {"type": "string"},
                                "relevance": {"type": "string", "enum": ["direct", "partial", "background"]},
                                "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
                                "note": {"type": "string", "description": "Why this doc is relevant"},
                            },
                            "required": ["doc_id", "title", "relevance", "confidence"],
                        },
                    },
                    "coverage": {
                        "type": "object",
                        "properties": {
                            "match_level": {"type": "string", "enum": ["direct", "partial", "none"]},
                            "gaps": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Topics missing from results",
                            },
                        },
                        "required": ["match_level"],
                    },
                    "suggestions": {
                        "type": "array",
                        "description": "Recommendations for the main agent",
                        "items": {
                            "type": "object",
                            "properties": {
                                "action": {"type": "string", "enum": ["add", "delete", "fix_meta", "search_external"]},
                                "domain": {"type": "string"},
                                "topic": {"type": "string"},
                                "reason": {"type": "string"},
                                "priority": {"type": "string", "enum": ["high", "medium", "low"]},
                            },
                            "required": ["action", "reason"],
                        },
                    },
                    "meta_changes_made": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "doc_id": {"type": "string"},
                                "field": {"type": "string"},
                                "old": {},
                                "new": {},
                            },
                            "required": ["doc_id", "field"],
                        },
                    },
                },
                "required": ["findings", "coverage", "suggestions"],
            },
        },
    },
]

SUB_AGENT_SYSTEM_PROMPT = """你是一个知识库检索子代理。你的职责是搜索知识库、阅读 meta、修正问题、最终汇报。

工作流程：
1. 调用 kb_search 搜索用户查询 → 获得候选文档列表（含 id, domain, title, content[:500], score, meta）
2. 仔细阅读每条结果的 meta 字段
3. 如果 meta 不准确 → 调用 kb_update_meta 修正
4. 如果需要深入了解某条文档 → 调用 kb_get (限制：最多 3 次)
5. 如果第一轮结果不够好 → 换关键词/跟关联链 refine，再次 kb_search
6. 完成检索 → 调用 kb_report 汇报

规则：
- 自主完成，不需要和任何人确认
- kb_get 仅用于跟 parent/children/related 链，不用于批量全文
- kb_report 是最后一步，之后必须停止
- 你已穷尽当前 query 方向的所有相关信息"""


class SubAgentLoop:
    """Simple multi-turn tool-call loop for the KB query sub-agent."""

    MAX_TURNS = 8

    def __init__(self, llm: LLMClient, kb: KnowledgeBase, trace: bool = True):
        self._llm = llm
        self._kb = kb
        self._kb_get_count = 0
        self._report = None
        self._trace = trace
        self._turn_count = 0

    def run(self, query: str, context: str = "") -> dict:
        messages = [
            {"role": "system", "content": SUB_AGENT_SYSTEM_PROMPT},
            {"role": "user", "content": f"[查询]\n{query}\n\n[上下文]\n{context}"},
        ]

        for turn in range(1, self.MAX_TURNS + 1):
            self._turn_count = turn
            resp = self._llm.chat(messages=messages, tools=SUB_AGENT_TOOLS)

            if resp.text and not resp.tool_calls:
                if self._trace:
                    print(f"  [turn {turn}] LLM text: {resp.text[:120]}...")
                messages.append({"role": "assistant", "content": resp.text})
                continue

            if not resp.tool_calls:
                continue

            tool_results = []
            for tc in resp.tool_calls:
                name = tc.function.name
                args = json.loads(tc.function.arguments)
                if self._trace:
                    arg_summary = {k: v for k, v in args.items() if k not in ("content",)}
                    print(f"  [turn {turn}] {name}({json.dumps(arg_summary, ensure_ascii=False)})")

                if name == "kb_report":
                    self._report = args
                    return args

                result = self._dispatch(name, args)
                tool_results.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": json.dumps(result, ensure_ascii=False),
                })

            messages.append({
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
            messages.extend(tool_results)

        return {"error": "max_turns_exceeded", "turns": self.MAX_TURNS}

    def _dispatch(self, name: str, args: dict) -> dict:
        if name == "kb_search":
            return self._handle_search(**args)
        if name == "kb_get":
            return self._handle_get(**args)
        if name == "kb_update_meta":
            return self._handle_update_meta(**args)
        return {"error": f"unknown tool: {name}"}

    def _handle_search(self, query: str, domain: str | None = None, top_k: int = 10) -> dict:
        results = self._kb.search(query, domain=domain, top_k=top_k)
        for r in results:
            doc = self._kb.get(r["id"])
            if doc:
                r["meta"] = doc.meta
        return {"results": results, "count": len(results)}

    def _handle_get(self, doc_id: str) -> dict:
        self._kb_get_count += 1
        if self._kb_get_count > 3:
            return {"status": "limit_exceeded", "reason": "kb_get limit of 3 reached"}
        doc = self._kb.get(doc_id)
        if doc is None:
            return {"status": "not_found"}
        return {"status": "ok", "doc": doc.to_dict()}

    def _handle_update_meta(self, doc_id: str, meta: dict) -> dict:
        doc = self._kb.get(doc_id)
        if doc is None:
            return {"status": "not_found"}
        old = dict(doc.meta)
        self._kb.update_meta(doc_id, meta)
        self._kb.update(doc_id)
        self._kb.save()
        return {"status": "ok", "doc_id": doc_id, "old": old, "new": dict(doc.meta)}


def _now():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def seed_test_docs(kb: KnowledgeBase) -> None:
    """Seed KB with docs that have intentional meta gaps for the sub-agent to fix."""
    docs = [
        KnowledgeDoc(
            domain="ds/ml",
            title="Pandas DataFrame 入门",
            content=(
                "# Pandas DataFrame 入门\n\n"
                "DataFrame 是 Pandas 最核心的数据结构，类似电子表格。\n\n"
                "## 创建 DataFrame\n"
                "```python\nimport pandas as pd\n"
                "df = pd.DataFrame({'A': [1,2,3], 'B': [4,5,6]})\n```\n\n"
                "## 常用操作\n"
                "- `df.head()` 查看前 5 行\n"
                "- `df.describe()` 统计摘要\n"
                "- `df['A']` 访问列\n\n"
                "## 关联文档\n"
                "进阶用法见 Pandas GroupBy 指南。"
            ),
            meta={"type": "tutorial", "tags": ["pandas", "dataframe"]},
            source="seed",
        ),
        KnowledgeDoc(
            domain="ds/ml",
            title="Pandas GroupBy 聚合指南",
            content=(
                "# Pandas GroupBy 聚合指南\n\n"
                "groupby 是数据分析中的核心操作，用于分组聚合。\n\n"
                "## 基本用法\n"
                "```python\ndf.groupby('category')['value'].mean()\n```\n\n"
                "## 多列聚合\n"
                "```python\ndf.groupby('category').agg({'value': 'mean', 'count': 'sum'})\n```\n\n"
                "## 注意事项\n"
                "groupby 返回的是一个 GroupBy 对象，需要用聚合函数触发计算。\n\n"
                "这是 DataFrame 入门文档的进阶内容。"
            ),
            meta={"type": "reference", "tags": ["pandas", "groupby"]},
            source="seed",
        ),
        KnowledgeDoc(
            domain="ds/ml",
            title="Python 列表操作备忘",
            content=(
                "# Python 列表操作\n\n"
                "## 基础\n"
                "- `lst.append(x)` 末尾添加\n"
                "- `lst.pop()` 末尾移除\n"
                "- `lst.sort()` 就地排序\n\n"
                "## 列表推导式\n"
                "```python\n[x*2 for x in range(10) if x > 3]\n```"
            ),
            meta={"type": "reference"},
            source="seed",
        ),
        KnowledgeDoc(
            domain="ds/ml",
            title="Docker 基础命令",
            content=(
                "# Docker 基础命令\n\n"
                "## 镜像操作\n"
                "- `docker build -t name .` 构建镜像\n"
                "- `docker pull image` 拉取镜像\n\n"
                "## 容器操作\n"
                "- `docker run -d image` 后台运行\n"
                "- `docker ps` 查看运行中容器\n"
                "- `docker exec -it container bash` 进入容器"
            ),
            meta={"type": "reference", "level": "beginner", "tags": ["docker"]},
            source="seed",
        ),
        KnowledgeDoc(
            domain="ds/ml",
            title="Pandas Merge Join 连接操作",
            content=(
                "# Pandas Merge Join 连接操作\n\n"
                "## merge 函数\n"
                "```python\npd.merge(df1, df2, on='key', how='inner')\n```\n\n"
                "## 连接类型\n"
                "- `how='inner'` 内连接（默认）\n"
                "- `how='left'` 左连接\n"
                "- `how='right'` 右连接\n"
                "- `how='outer'` 全外连接\n\n"
                "## 关联\n"
                "参考 DataFrame 入门文档的 `related` 部分。"
            ),
            meta={"type": "tutorial", "tags": ["pandas", "merge"]},
            source="seed",
        ),
    ]
    for doc in docs:
        kb.add(doc)
    kb.save()


def build_llm_client() -> LLMClient:
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
    llm.temperature = 0.1
    return llm


def main():
    print("=" * 60)
    print("KB Query Sub-Agent Test")
    print("=" * 60)

    kb = KnowledgeBase("data/kb_sub_test")
    seed_test_docs(kb)
    print(f"\nSeeded {len(kb._docs)} docs in domain 'ds/ml'")
    print(f"  Intentional gaps: doc '列表操作' missing level & tags")
    print(f"  Expected links: 'GroupBy' should relate to 'DataFrame' (mentioned)\n")

    llm = build_llm_client()
    agent = SubAgentLoop(llm, kb)

    print("--- Running sub-agent ---")
    query = "Pandas 数据分组聚合 groupby 怎么用"
    report = agent.run(query)

    print("\n=== kb_report output ===")
    print(json.dumps(report, ensure_ascii=False, indent=2))

    # Validations
    print("\n--- Validations ---")
    assert "findings" in report, "Missing findings"
    assert "coverage" in report, "Missing coverage"
    assert "suggestions" in report, "Missing suggestions"
    print(f"  findings: {len(report.get('findings', []))} docs reported")
    print(f"  coverage.match_level: {report['coverage'].get('match_level')}")
    print(f"  suggestions: {len(report.get('suggestions', []))}")
    print(f"  meta_changes_made: {len(report.get('meta_changes_made', []))}")

    # Verify kb_get under limit
    assert agent._kb_get_count <= 3, f"kb_get called {agent._kb_get_count} times (limit 3)"

    # Verify meta was actually persisted
    for change in report.get("meta_changes_made", []):
        doc = kb.get(change["doc_id"])
        assert doc is not None, f"Doc {change['doc_id']} not found in KB"
        print(f"  KB verified: {doc.title} meta = {doc.meta}")

    print("\nDONE")

    kb.close()


if __name__ == "__main__":
    main()
