"""Fill-Gap Sub-Agent standalone test script.

Creates a KB, runs the fill-gap sub-agent with a real LLM,
verifies the sub-agent can: generate content for a gap topic → knowledge_add → kb_report.
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


FILL_GAP_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "kb_add",
            "description": "Add a new document to the knowledge base to fill a gap.",
            "parameters": {
                "type": "object",
                "properties": {
                    "domain": {"type": "string", "description": "Domain path"},
                    "title": {"type": "string", "description": "Document title"},
                    "content": {"type": "string", "description": "Markdown content"},
                    "meta": {
                        "type": "object",
                        "description": "Meta fields: type, level, tags",
                        "properties": {
                            "type": {"type": "string", "enum": ["reference", "tutorial", "example", "faq"]},
                            "level": {"type": "string", "enum": ["beginner", "intermediate", "advanced"]},
                            "tags": {"type": "array", "items": {"type": "string"}},
                        },
                    },
                },
                "required": ["domain", "title", "content", "meta"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "kb_report",
            "description": "End the fill-gap task. Report what was added.",
            "parameters": {
                "type": "object",
                "properties": {
                    "added": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "title": {"type": "string"},
                                "domain": {"type": "string"},
                                "doc_id": {"type": "string"},
                            },
                        },
                    },
                    "skipped": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Topics that could not be filled (no knowledge source)",
                    },
                },
                "required": ["added"],
            },
        },
    },
]

FILL_GAP_SYSTEM_PROMPT = """你是一个知识库填补子代理。你的职责是为知识库中缺失的主题生成内容并保存。

工作流程：
1. 收到 {domain, topic} — 需要填补的知识缺口
2. 根据自己的知识为这个主题生成内容（Markdown 格式，包含代码示例）
3. 调用 kb_add 保存到知识库
4. 调用 kb_report 结束

规则：
- 内容必须准确、有代码示例
- meta 必须填写 type（reference/tutorial/example/faq）、level（beginner/intermediate/advanced）、tags
- 如果某个主题超出你的知识范围 → 在 kb_report 的 skipped 中列出，不要编造
- 一个 kb_add 一条文档，需要多条就多次调用"""


class FillGapLoop:
    MAX_TURNS = 6

    def __init__(self, llm: LLMClient, kb: KnowledgeBase, trace: bool = True):
        self._llm = llm
        self._kb = kb
        self._trace = trace
        self._added_ids: list[str] = []

    def run(self, domain: str, topic: str, existing_docs_summary: str = "") -> dict:
        context = (
            f"[知识缺口]\ndomain: {domain}\ntopic: {topic}"
        )
        if existing_docs_summary:
            context += f"\n\n[该 domain 已有文档]\n{existing_docs_summary}"

        messages = [
            {"role": "system", "content": FILL_GAP_SYSTEM_PROMPT},
            {"role": "user", "content": context},
        ]

        for turn in range(1, self.MAX_TURNS + 1):
            resp = self._llm.chat(messages=messages, tools=FILL_GAP_TOOLS)

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
                    if name == "kb_add":
                        print(f"  [turn {turn}] kb_add(domain={args['domain']}, title={args['title']})")
                    else:
                        print(f"  [turn {turn}] {name}(...)")

                if name == "kb_report":
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
        if name == "kb_add":
            return self._handle_add(**args)
        return {"error": f"unknown tool: {name}"}

    def _handle_add(self, domain: str, title: str, content: str, meta: dict) -> dict:
        from core.knowledge.models import KnowledgeDoc
        doc = KnowledgeDoc(domain=domain, title=title, content=content, meta=meta, source="fill_gap")
        doc_ids = self._kb.add(doc)
        self._kb.save()
        self._added_ids.extend(doc_ids)
        return {"status": "ok", "doc_ids": doc_ids, "doc_id": doc_ids[0]}


def seed_existing_docs(kb: KnowledgeBase) -> None:
    """Seed a KB with some existing docs for context."""
    docs = [
        KnowledgeDoc(
            domain="ds/ml",
            title="Pandas 数据读取与写入",
            content="# Pandas 数据读取\n\n```python\npd.read_csv('file.csv')\npd.read_excel('file.xlsx')\n```",
            meta={"type": "tutorial", "level": "beginner", "tags": ["pandas", "io"]},
            source="seed",
        ),
        KnowledgeDoc(
            domain="ds/ml",
            title="Pandas DataFrame 筛选与过滤",
            content="# DataFrame 筛选\n\n```python\ndf[df['A'] > 10]\ndf.query('A > 10 and B < 5')\n```",
            meta={"type": "reference", "level": "beginner", "tags": ["pandas", "filter"]},
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
    print("Fill-Gap Sub-Agent Test")
    print("=" * 60)

    kb = KnowledgeBase("data/kb_fill_test")
    seed_existing_docs(kb)
    domain = "ds/ml"
    topic = "Pandas GroupBy transform 方法"

    print(f"\nDomain: {domain}")
    print(f"Topic to fill: {topic}")
    existing = "\n".join(
        f"  - {d.title}" for d in kb._docs.values()
    )
    print(f"Existing docs:\n{existing}\n")

    llm = build_llm_client()
    agent = FillGapLoop(llm, kb)

    print("--- Running fill-gap sub-agent ---")
    report = agent.run(domain, topic, existing)

    print("\n=== kb_report output ===")
    print(json.dumps(report, ensure_ascii=False, indent=2))

    print("\n--- Validations ---")
    assert "added" in report, "Missing added"
    assert len(report["added"]) >= 1, "No docs added"
    print(f"  added: {len(report['added'])} docs")

    for entry in report["added"]:
        doc = kb.get(entry["doc_id"])
        assert doc is not None, f"Doc {entry['doc_id']} not found in KB"
        assert doc.content, "Doc has no content"
        assert doc.meta.get("type"), "Doc missing type in meta"
        assert doc.meta.get("level"), "Doc missing level in meta"
        print(f"  KB verified: {doc.title}")
        print(f"    type={doc.meta.get('type')}, level={doc.meta.get('level')}, tags={doc.meta.get('tags')}")
        print(f"    content[:150]: {doc.content[:150]}...")

    print("\nDONE")
    kb.close()


if __name__ == "__main__":
    main()
