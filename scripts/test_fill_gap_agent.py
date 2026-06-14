"""Fill-Gap Sub-Agent standalone test — v2: web search + propose (no kb_add).

Creates a KB, runs fill-gap with SearXNG+tavily+terminal+ask_user,
verifies the sub-agent returns proposals via kb_fill_propose.
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
from scripts.interactive_kb_agent import FillGapLoop


def seed_existing_docs(kb: KnowledgeBase) -> None:
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
            title="Pandas GroupBy 聚合指南",
            content="## 基本用法\n```python\ndf.groupby('category')['value'].mean()\n```\n## 多列聚合\n```python\ndf.groupby('category').agg({'value':'mean','count':'sum'})\n```\n注意：groupby 返回 GroupBy 对象，需聚合函数触发。",
            meta={"type": "tutorial", "level": "intermediate", "tags": ["pandas", "groupby"]},
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
    print("Fill-Gap Sub-Agent v2 Test")
    print("=" * 60)

    kb = KnowledgeBase("data/kb_fill_test")
    seed_existing_docs(kb)

    suggestion = {
        "domain": "ds/ml",
        "topic": "Pandas GroupBy transform 方法详解",
        "reason": "当前仅涵盖 groupby+agg，缺少 transform/apply/filter 等高级用法",
        "existing_doc_ids": list(kb._docs.keys()),
    }

    print(f"\nGap: {suggestion['domain']}: {suggestion['topic']}")
    print(f"Reason: {suggestion['reason']}")
    print(f"Existing docs: {len(suggestion['existing_doc_ids'])}\n")

    llm = build_llm_client()
    agent = FillGapLoop(llm, kb, trace=True)

    print("--- Running fill-gap (with web search) ---")
    report = agent.run(suggestion)

    print("\n=== kb_fill_propose output ===")
    try:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    except UnicodeEncodeError:
        print(json.dumps(report, ensure_ascii=True, indent=2))

    print("\n--- Validations ---")
    proposals = report.get("proposals", [])
    skipped = report.get("skipped", [])
    print(f"  proposals: {len(proposals)}")
    for p in proposals:
        print(f"    - {p.get('title', '?')} (confidence={p.get('confidence', '?')})")
    if skipped:
        print(f"  skipped: {len(skipped)}")
        for s in skipped:
            print(f"    - {s.get('topic', '?')}: {s.get('reason', '?')[:80]}")
    if report.get("needs_ask_user"):
        print(f"  needs_ask_user: {report['needs_ask_user'].get('question', '?')[:80]}")
    print("\nDONE")
    kb.close()


if __name__ == "__main__":
    main()
