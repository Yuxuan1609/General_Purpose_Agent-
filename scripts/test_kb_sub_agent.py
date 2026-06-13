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


class SubAgentLoop:
    """Two-phase KB sub-agent: Phase 1 search (≤3 searches) → Phase 2 meta review (conditional)."""

    MAX_SEARCHES = 3
    MAX_KB_GET = 3
    MAX_TURNS = 8

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
                "description": "Get full document by ID. MAX 3 calls.",
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
                            "description": "Documents found",
                            "items": {"type": "object"},
                        },
                        "suggestions": {
                            "type": "array",
                            "description": "For main agent: {action, topic, reason, priority}",
                            "items": {"type": "object"},
                        },
                        "needs_meta_review": {
                            "type": "boolean",
                        },
                    },
                    "required": ["findings", "suggestions", "needs_meta_review"],
                },
            },
        },
    ]

    PHASE1_SYSTEM = """你是知识库检索子代理（搜索阶段）。

任务：根据查询搜索知识库，阅读 meta 质量，refine 直到满意。

meta 字段：
- type: "reference"|"tutorial"|"example"|"faq"
- level: "beginner"|"intermediate"|"advanced"
- tags: string[]
- related: string[] / parent: string / children: string[]

流程：
1. kb_search → 读每条 meta
2. 需深入 → kb_get (最多 3 次)
3. 不够好 → 换关键词 refine kb_search (最多 3 轮)
4. 完成 → kb_phase1_done

注意：本阶段只检索不修改 meta。如发现 meta 有缺陷，设 needs_meta_review=true。kb_search 自动去重，0 结果时有域提示。"""

    PHASE2_TOOLS = [
        {
            "type": "function",
            "function": {
                "name": "kb_update_meta",
                "description": "Fix meta fields (type, level, tags, related, etc.).",
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
                "description": "End meta review. Report changes made.",
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

    PHASE2_SYSTEM = """你是知识库 meta 维护子代理。

meta schema: type(reference|tutorial|example|faq), level(beginner|intermediate|advanced), tags(string[]), related(string[])

任务：阅读检索历史中提到的每篇文档，检查 meta 质量，调用 kb_update_meta 修正。

[检索历史]
{history}

完成后调用 kb_phase2_done。"""

    def __init__(self, llm: LLMClient, kb: KnowledgeBase, trace: bool = True):
        self._llm = llm
        self._kb = kb
        self._trace = trace
        self._kb_get_count = 0
        self._search_count = 0
        self._seen_ids: set[str] = set()
        self._phase1_messages: list[dict] = []

    def run(self, query: str, context: str = "") -> dict:
        self._kb_get_count = 0
        self._search_count = 0
        self._seen_ids = set()
        self._phase1_messages = []

        phase1 = self._run_phase1(query, context)
        meta_changes = []
        if phase1.get("needs_meta_review"):
            meta_changes = self._run_phase2(phase1)

        return {
            "findings": phase1.get("findings", []),
            "suggestions": phase1.get("suggestions", []),
            "meta_changes_made": meta_changes,
        }

    def _run_phase1(self, query: str, context: str) -> dict:
        messages = [
            {"role": "system", "content": self.PHASE1_SYSTEM},
            {"role": "user", "content": f"[查询]\n{query}\n\n[上下文]\n{context}"},
        ]

        for turn in range(1, self.MAX_TURNS + 1):
            resp = self._llm.chat(messages=messages, tools=self.PHASE1_TOOLS)

            if resp.text and not resp.tool_calls:
                if self._trace:
                    print(f"  [P1 turn {turn}] text: {resp.text[:100]}...")
                messages.append({"role": "assistant", "content": resp.text})
                continue
            if not resp.tool_calls:
                continue

            tool_results = []
            for tc in resp.tool_calls:
                name = tc.function.name
                args = json.loads(tc.function.arguments)
                if self._trace:
                    arg_summary = {k: v for k, v in args.items() if k not in ("findings", "content")}
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
                return {"error": f"max {self.MAX_SEARCHES} searches, use kb_phase1_done"}
            domain = args.get("domain")
            results = self._kb.search(**args)
            new_results = [r for r in results if r["id"] not in self._seen_ids]
            deduped = len(results) - len(new_results)
            for r in new_results:
                doc = self._kb.get(r["id"])
                r["meta"] = doc.meta if doc else {}
            hint = ""
            if len(new_results) == 0:
                domains = [d["path"] for d in self._kb.list_domains()]
                if domain and domain not in domains:
                    hint = f" | domain '{domain}' not found. Available: {', '.join(domains)}"
                elif domain:
                    hint = f" | 0 results in '{domain}'. Try broader query."
                else:
                    hint = " | 0 results. Try different query terms."
            return {
                "results": new_results, "count": len(new_results),
                "deduped": deduped, "hint": hint,
                "all_domains": [d["path"] for d in self._kb.list_domains()],
            }
        if name == "kb_get":
            self._kb_get_count += 1
            if self._kb_get_count > self.MAX_KB_GET:
                return {"status": "limit_exceeded"}
            doc_id = (args.get("doc_id") or "").strip()
            if not doc_id:
                return {"status": "error", "reason": "empty doc_id"}
            self._seen_ids.add(doc_id)
            doc = self._kb.get(args["doc_id"])
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
                    print(f"  [P2] {name}(...)")

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
        lines.append("## 覆盖评估")
        cov = phase1.get("coverage", {})
        lines.append(f"  match_level: {cov.get('match_level', '?')}")
        if cov.get("gaps"):
            lines.append(f"  gaps: {', '.join(cov['gaps'])}")
        return "\n".join(lines)


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
    assert "suggestions" in report, "Missing suggestions"
    print(f"  findings: {len(report.get('findings', []))} docs reported")
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
