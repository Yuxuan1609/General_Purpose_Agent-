"""Smoke test for Capability + LayerInjector end-to-end flow.

Simulates a simple LLM agent loop with tool injection and tool_call handling.
Uses mock LLM responses that include tool_calls — no real API required.
Logs to logs/smoke_test_injector/ timestamped directory.

Usage:
    python scripts/smoke_test_injector.py
"""
from __future__ import annotations
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _setup_logging():
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_dir = PROJECT_ROOT / "logs" / "smoke_test_injector" / stamp
    log_dir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("smoke_injector")
    logger.setLevel(logging.DEBUG)

    fh = logging.FileHandler(log_dir / "test.log", encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter("%(asctime)s | %(levelname)-7s | %(message)s"))
    logger.addHandler(fh)
    return logger, log_dir


logger, LOG_DIR = _setup_logging()

from core.tools.registry import ToolRegistry
from core.llm_client import LLMClient, LLMResponse
from capability import CapabilityRegistry
from capability.tool_capability import ToolCapability
from capability.knowledge_capability import (
    KnowledgeCapability, InMemoryKnowledgeStore,
)
from capability.layer_injector import LayerInjector


# ═══════════════════════════════════════════════════════════════════════════
# Mock LLM that returns tool_calls
# ═══════════════════════════════════════════════════════════════════════════

class ToolCallMockLLM(LLMClient):
    """LLM client that returns pre-canned responses with tool_calls."""

    def __init__(self, canned_text: str = "",
                 tool_calls: list[dict] | None = None):
        super().__init__(ToolCallMockLLM, "mock")
        self.model = "mock"
        self._text = canned_text
        self._tool_calls = tool_calls or []
        self.call_count = 0
        self.last_messages: list[dict] = []
        self.last_tools: list[dict] | None = None

    def chat(self, messages: list, tools: list[dict] | None = None,
             json_mode: bool = False, **kwargs) -> LLMResponse:
        self.call_count += 1
        self.last_messages = messages
        self.last_tools = tools
        text = self._text if self._text else json.dumps({"done": True, "result": "ok"})
        return LLMResponse(text=text, tool_calls=self._tool_calls)


# ═══════════════════════════════════════════════════════════════════════════
# Setup
# ═══════════════════════════════════════════════════════════════════════════

def setup():
    """Build the full capability + injector stack."""
    # ── ToolRegistry with real tools ──
    ToolRegistry._instance = None  # reset singleton
    tool_reg = ToolRegistry()

    from core.tools.terminal_tool import register_terminal_tool
    register_terminal_tool(tool_reg)

    # ── Knowledge stores (English content for keyword matching) ──
    games = InMemoryKnowledgeStore()
    games.add("leduc_k", "With King pre-flop always raise. Post-flop if paired continue raising.")
    games.add("leduc_q", "With Queen evaluate opponent action then call or raise accordingly.")
    games.add("leduc_j", "With Jack usually fold unless opponent shows weakness.")

    # ── CapabilityRegistry ──
    registry = CapabilityRegistry()
    tool_cap = ToolCapability(tool_reg)
    knowledge_cap = KnowledgeCapability(stores={
        "game_rules": (games, {"l1", "l2"}),
    })
    registry.register(tool_cap)
    registry.register(knowledge_cap)

    # ── LayerInjector ──
    injector = LayerInjector(registry)
    return injector, tool_reg, registry


# ═══════════════════════════════════════════════════════════════════════════
# Test cases
# ═══════════════════════════════════════════════════════════════════════════

def test_tool_injection(injector):
    """Verify tools are injected into LLM call kwargs."""
    logger.info("─── 1. Tool injection ───")
    call_kwargs = {
        "system": "You are an L2 agent. Decide what to do.",
        "user": "How should I play with King pre-flop?",
    }
    result = injector.inject_to_agent("l2", call_kwargs)
    assert "tools" in result, "tools NOT injected!"
    tool_names = [t["function"]["name"] for t in result["tools"]]
    logger.info("  Injected tools: %s", tool_names)
    logger.debug("  Tool schemas:\n%s", json.dumps(result["tools"], indent=2, ensure_ascii=False))
    logger.info("  PASS")


def test_knowledge_query(injector):
    """Simulate an LLM that calls knowledge_query and handle the result."""
    logger.info("─── 2. Knowledge query via tool_call ───")
    llm = ToolCallMockLLM(canned_text="", tool_calls=[{
        "function": {
            "name": "knowledge_query",
            "arguments": json.dumps({
                "store": "game_rules",
                "query": "King pre-flop strategy raise",
            }),
        },
    }])

    # Step 1: inject tools + call LLM
    call_kwargs = {
        "system": "You are an L1 agent. Use tools to find relevant knowledge.",
        "user": "How should I play with King pre-flop?",
    }
    injector.inject_to_agent("l2", call_kwargs)
    resp = llm.chat(
        messages=[
            {"role": "system", "content": call_kwargs["system"]},
            {"role": "user", "content": call_kwargs["user"]},
        ],
        tools=call_kwargs.get("tools"),
    )
    assert resp.tool_calls, "LLM returned no tool_calls"

    # Step 2: handle tool_calls
    results = injector.handle_tool_calls("l2", resp.tool_calls)
    assert len(results) == 1
    assert results[0].success, f"knowledge query failed: {results[0].error}"
    logger.info("  Query returned %d docs", len(results[0].data))
    for doc in results[0].data:
        logger.debug("    [%s] score=%s %s...", doc["id"], doc["score"], doc["content"][:60])

    # Step 3: format for next stage's user prompt
    formatted = injector.format_results_for_prompt(results)
    logger.info("  Formatted for prompt:\n%s", formatted)
    logger.info("  PASS")


def test_tool_dispatch(injector):
    """Simulate LLM calling a real tool (todo) and handle the result."""
    logger.info("─── 3. Tool dispatch via tool_call ───")
    llm = ToolCallMockLLM(canned_text="", tool_calls=[{
        "function": {
            "name": "todo",
            "arguments": json.dumps({
                "todos": [
                    {"id": "1", "content": "analyze hand", "status": "in_progress"},
                    {"id": "2", "content": "search strategy", "status": "pending"},
                ],
            }),
        },
    }])

    # Step 1: inject + call
    call_kwargs = {"system": "L2 agent", "user": "Task: track subtasks"}
    injector.inject_to_agent("l2", call_kwargs)
    resp = llm.chat(
        messages=[
            {"role": "system", "content": call_kwargs["system"]},
            {"role": "user", "content": call_kwargs["user"]},
        ],
        tools=call_kwargs.get("tools"),
    )
    assert resp.tool_calls

    # Step 2: handle
    results = injector.handle_tool_calls("l2", resp.tool_calls)
    assert results[0].success
    data = results[0].data
    logger.info("  Todo result: %s", json.dumps(data, ensure_ascii=False))
    assert data.get("success")
    assert len(data["todos"]) == 2
    logger.info("  PASS")


def test_tool_denied(injector):
    """Verify a forbidden tool is rejected."""
    logger.info("─── 4. Tool access denied ───")
    llm = ToolCallMockLLM(canned_text="", tool_calls=[{
        "function": {
            "name": "terminal",
            "arguments": json.dumps({"command": "echo hello"}),
        },
    }])

    call_kwargs = {"system": "L1 agent", "user": "Try terminal"}
    injector.inject_to_agent("l1", call_kwargs)
    resp = llm.chat(
        messages=[
            {"role": "system", "content": call_kwargs["system"]},
            {"role": "user", "content": call_kwargs["user"]},
        ],
        tools=call_kwargs.get("tools"),
    )

    results = injector.handle_tool_calls("l1", resp.tool_calls)
    assert not results[0].success
    logger.info("  Error: %s", results[0].error)
    assert "not allowed" in results[0].error.lower()
    logger.info("  PASS")


def test_full_agent_loop(injector):
    """Simulate a complete agent stage: inject -> LLM -> handle -> format -> next stage."""
    logger.info("─── 5. Full agent loop ───")

    # Stage 1: Agent asks for knowledge
    llm_stage1 = ToolCallMockLLM(canned_text="", tool_calls=[{
        "function": {
            "name": "knowledge_query",
            "arguments": json.dumps({
                "store": "game_rules",
                "query": "Leduc pre-flop strategy King raise",
            }),
        },
    }])

    call_kwargs = {
        "system": "You are an L1 agent. First gather knowledge, then decide.",
        "user": "With King pre-flop, opponent raises. What should I do?",
    }
    injector.inject_to_agent("l1", call_kwargs)

    logger.info("  Stage 1: LLM calls knowledge_query...")
    resp1 = llm_stage1.chat(
        messages=[
            {"role": "system", "content": call_kwargs["system"]},
            {"role": "user", "content": call_kwargs["user"]},
        ],
        tools=call_kwargs.get("tools"),
    )

    results = injector.handle_tool_calls("l1", resp1.tool_calls)
    assert results[0].success

    knowledge_text = injector.format_results_for_prompt(results)
    logger.debug("  Knowledge result:\n%s", knowledge_text)

    # Stage 2: Agent decides based on knowledge + original query
    logger.info("  Stage 2: LLM decides (with knowledge in prompt)...")
    llm_stage2 = ToolCallMockLLM(
        canned_text=json.dumps({"done": True, "result": "raise",
                                "reasoning": "King is strongest, should raise"}),
    )

    stage2_kwargs = {
        "system": "You are an L1 agent. Make final decision.",
        "user": f"Query: How to play with King pre-flop?\n\n{knowledge_text}",
    }
    injector.inject_to_agent("l1", stage2_kwargs)
    resp2 = llm_stage2.chat(
        messages=[
            {"role": "system", "content": stage2_kwargs["system"]},
            {"role": "user", "content": stage2_kwargs["user"]},
        ],
        tools=stage2_kwargs.get("tools"),
    )

    decision = json.loads(resp2.text)
    logger.info("  Final decision: raise (done=%s)", decision["done"])
    logger.info("  Reasoning: King is strongest, should raise")
    assert decision["result"] == "raise"
    logger.info("  PASS")


# ═══════════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════════

def main():
    logger.info("=" * 55)
    logger.info("  Capability + LayerInjector Smoke Test")
    logger.info("=" * 55)

    injector, tool_reg, registry = setup()
    logger.info("Setup: %d tools, %d capabilities visible to L1",
                len(tool_reg.get_definitions()),
                len(registry.list_for_layer("l1")))
    logger.info("Log dir: %s", LOG_DIR)

    tests = [
        test_tool_injection,
        test_knowledge_query,
        test_tool_dispatch,
        test_tool_denied,
        test_full_agent_loop,
    ]

    passed = 0
    for test_fn in tests:
        try:
            test_fn(injector)
            passed += 1
        except Exception as e:
            logger.error("  FAIL: %s", e)
            logger.debug("Traceback:", exc_info=True)

    logger.info("=" * 55)
    logger.info("  Results: %d/%d passed", passed, len(tests))
    logger.info("  Log: %s", LOG_DIR / "test.log")
    logger.info("=" * 55)
    return 0 if passed == len(tests) else 1


if __name__ == "__main__":
    sys.exit(main())
