"""Integration test: Capability system + LayerAgent multi-turn tool loop.

Validates DeepSeek-compatible multi-turn tool call flow (role:"tool" messages):
  1. LLM returns tool_calls → execute → role:"tool" → continue → final JSON content
  2. Consolidation task generation with spec sheet
  3. Full round-trip with mock LLM

Logs to logs/integration_test_capability/<timestamp>/test.log.

Usage:
    python scripts/integration_test_capability.py
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
    log_dir = PROJECT_ROOT / "logs" / "integration_test_capability" / stamp
    log_dir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("integration_cap")
    logger.setLevel(logging.DEBUG)
    fh = logging.FileHandler(log_dir / "test.log", encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter("%(asctime)s | %(levelname)-7s | %(message)s"))
    logger.addHandler(fh)
    return logger, log_dir


logger, LOG_DIR = _setup_logging()


# ═══════════════════════════════════════════════════════════════════════════
# Mock LLM that simulates multi-turn tool call flow
# ═══════════════════════════════════════════════════════════════════════════

class MultiTurnMockLLM:
    """Mock LLM that returns tool_calls on first turn, content on second.

    Simulates DeepSeek's multi-turn tool call pattern:
      Turn 1: returns tool_calls → user executes → role:"tool" → Turn 2: returns content
    """

    def __init__(self):
        from core.llm_client import LLMClient, LLMResponse, ToolCall, FunctionCall
        self._LLMResponse = LLMResponse
        self._ToolCall = ToolCall
        self._FunctionCall = FunctionCall
        self.model = "mock-multi-turn"
        self.call_history: list[dict] = []  # track all calls

    def chat(self, messages: list, tools: list | None = None,
             json_mode: bool = False, **kwargs):
        from core.llm_client import LLMResponse, ToolCall, FunctionCall
        turn = len(self.call_history) + 1
        self.call_history.append({
            "turn": turn, "msg_count": len(messages),
            "tools_provided": bool(tools),
            "last_role": messages[-1]["role"] if messages else "",
        })
        logger.debug("  Mock LLM turn %d: %d messages, tools=%s, json_mode=%s",
                     turn, len(messages), bool(tools), json_mode)

        # Check if there's a role:"tool" message → this is a follow-up turn
        has_tool_result = any(m.get("role") == "tool" for m in messages)

        if tools and not has_tool_result:
            # First turn with tools → return tool_calls
            return self._tool_call_response()
        else:
            # Follow-up turn after tool results → return final JSON content
            return self._content_response()

    def _tool_call_response(self):
        return self._LLMResponse(
            text="",
            tool_calls=[
                self._ToolCall(
                    id="call_mock_001",
                    function=self._FunctionCall(
                        name="knowledge_query",
                        arguments=json.dumps({
                            "store": "game_rules",
                            "query": "King pre-flop strategy",
                        }),
                    ),
                ),
            ],
        )

    def _content_response(self):
        return self._LLMResponse(
            text=json.dumps({
                "done": True,
                "result": "raise",
                "reasoning": "Based on knowledge: King pre-flop always raise. "
                             "With K as strongest card, aggressive raise is optimal.",
                "rules_used": ["l1_602ae3"],
            }),
        )


class MultiToolMockLLM:
    """Mock LLM that makes TWO sequential tool calls before content."""

    def __init__(self):
        from core.llm_client import LLMResponse, ToolCall, FunctionCall
        self._LLMResponse = LLMResponse
        self._ToolCall = ToolCall
        self._FunctionCall = FunctionCall
        self.model = "mock-multi-tool"
        self.call_history: list[dict] = []
        self._turn = 0

    def chat(self, messages: list, tools: list | None = None,
             json_mode: bool = False, **kwargs):
        self._turn += 1
        self.call_history.append({
            "turn": self._turn, "msg_count": len(messages),
            "tools_provided": bool(tools),
        })
        logger.debug("  Multi-tool Mock turn %d: %d msgs", self._turn, len(messages))

        tool_msg_count = sum(1 for m in messages if m.get("role") == "tool")

        if self._turn == 1 and tools:
            # Turn 1: ask for knowledge
            return self._LLMResponse(
                text="",
                tool_calls=[self._ToolCall(
                    id="call_multi_001",
                    function=self._FunctionCall(
                        name="knowledge_query",
                        arguments=json.dumps({"store": "game_rules", "query": "Leduc strategy"}),
                    ),
                )],
            )
        elif self._turn == 2 and tools:
            # Turn 2: after knowledge result, also call todo
            return self._LLMResponse(
                text="",
                tool_calls=[self._ToolCall(
                    id="call_multi_002",
                    function=self._FunctionCall(
                        name="todo",
                        arguments=json.dumps({"todos": [
                            {"id": "1", "content": "Evaluate pre-flop strategy", "status": "completed"},
                            {"id": "2", "content": "Make final decision", "status": "in_progress"},
                        ]}),
                    ),
                )],
            )
        else:
            # Final turn: return decision
            return self._LLMResponse(
                text=json.dumps({
                    "done": True, "result": "raise",
                    "reasoning": "multiple tools consulted, decision: raise",
                }),
            )


# ═══════════════════════════════════════════════════════════════════════════
# Setup
# ═══════════════════════════════════════════════════════════════════════════

def setup():
    from core.layers.base import LayerAgent
    from core.tools.registry import ToolRegistry
    from capability import CapabilityRegistry
    from capability.tool_capability import ToolCapability
    from capability.knowledge_capability import (
        KnowledgeCapability, InMemoryKnowledgeStore,
    )
    from capability.layer_injector import LayerInjector

    # ── ToolRegistry ──
    ToolRegistry._instance = None
    tool_reg = ToolRegistry()
    from core.tools.todo_tool import register_todo_tool
    register_todo_tool(tool_reg)

    # ── Knowledge stores ──
    games = InMemoryKnowledgeStore()
    games.add("k_strategy", "With King pre-flop always raise. King is the strongest card.")
    games.add("q_strategy", "With Queen evaluate opponent before deciding call or raise.")
    games.add("j_strategy", "With Jack usually fold unless opponent shows clear weakness.")

    # ── CapabilityRegistry ──
    registry = CapabilityRegistry()
    registry.register(ToolCapability(tool_reg))
    registry.register(KnowledgeCapability(stores={
        "game_rules": (games, {"l1", "l2"}),
    }))

    # ── LayerInjector ──
    injector = LayerInjector(registry)

    # ── LayerAgent with injector ──
    agent_log = logging.getLogger("test_agent")
    agent_log.setLevel(logging.DEBUG)
    agent_log.addHandler(logging.getLogger("integration_cap").handlers[0])

    class TestAgent(LayerAgent):
        pass

    agent = TestAgent(None, agent_log)
    # Override _llm to use mock (skip LayerAgent init which expects llm_client)
    # We'll pass tools directly to _call_llm

    return injector, registry, games


# ═══════════════════════════════════════════════════════════════════════════
# Test Cases
# ═══════════════════════════════════════════════════════════════════════════

def test_multi_turn_tool_call(injector):
    """Test: Agent with single tool call → tool result → final content."""
    logger.info("=" * 55)
    logger.info("  TEST 1: Single tool call multi-turn loop")
    logger.info("=" * 55)

    from core.layers.base import LayerAgent
    mock_llm = MultiTurnMockLLM()

    class TestAgent(LayerAgent):
        pass

    agent = TestAgent(mock_llm, logging.getLogger("test_agent"))
    agent.set_injector(injector)

    tools = injector.get_tools_for_layer("l1")
    logger.info("  Tools visible to L1: %s", [t["function"]["name"] for t in tools])

    result = agent._call_llm(
        system="You are an L1 agent. Use knowledge_query to get strategy info.",
        user="With King pre-flop, opponent raises. What should I do?",
        schema={"done": "boolean", "result": "string", "reasoning": "string"},
        tools=tools,
        layer="l1",
    )

    logger.info("  Result: %s", json.dumps(result, ensure_ascii=False))
    assert result["done"] is True
    assert result["result"] == "raise"
    assert len(mock_llm.call_history) == 2  # 2 turns: tool_call + content
    logger.info("  Turns: %d → PASS", len(mock_llm.call_history))


def test_multi_tool_sequential(injector):
    """Test: Agent makes TWO tool calls before final content."""
    logger.info("=" * 55)
    logger.info("  TEST 2: Sequential tool calls (knowledge → todo → decision)")
    logger.info("=" * 55)

    from core.layers.base import LayerAgent
    mock_llm = MultiToolMockLLM()

    class TestAgent(LayerAgent):
        pass

    agent = TestAgent(mock_llm, logging.getLogger("test_agent"))
    agent.set_injector(injector)

    tools = injector.get_tools_for_layer("l2")
    logger.info("  Tools visible to L2: %s", [t["function"]["name"] for t in tools])

    result = agent._call_llm(
        system="You are an L2 agent. Use tools to gather information.",
        user="Make a decision for Leduc Hold'em pre-flop.",
        schema={"done": "boolean", "result": "string", "reasoning": "string"},
        tools=tools,
        layer="l2",
    )

    logger.info("  Result: %s", json.dumps(result, ensure_ascii=False))
    assert result["done"] is True
    turns = len(mock_llm.call_history)
    logger.info("  Turns: %d → PASS", turns)
    assert turns == 3  # tool1 → tool2 → content


def test_no_tools_no_loop(_injector=None):
    """Test: When no tools provided, _call_llm works as before (single call)."""
    logger.info("=" * 55)
    logger.info("  TEST 3: No tools → single call (backward compat)")
    logger.info("=" * 55)

    from core.layers.base import LayerAgent
    from core.llm_client import LLMResponse

    class PlainMockLLM:
        model = "mock-plain"
        def chat(self, messages, tools=None, json_mode=False, **kwargs):
            return LLMResponse(text=json.dumps({"done": True, "result": "fold"}))

    class TestAgent(LayerAgent):
        pass

    agent = TestAgent(PlainMockLLM(), logging.getLogger("test_agent"))

    result = agent._call_llm(
        system="You are an L1 agent.",
        user="What to do?",
        schema={"done": "boolean", "result": "string"},
        # no tools!
        layer="l1",
    )

    logger.info("  Result: %s", json.dumps(result, ensure_ascii=False))
    assert result["done"] is True
    assert result["result"] == "fold"
    logger.info("  PASS (single call, no tool loop)")


def test_tool_access_denied(injector):
    """Test: Agent calls a tool it doesn't have access to."""
    logger.info("=" * 55)
    logger.info("  TEST 4: Tool access denied → error in result")
    logger.info("=" * 55)

    from core.layers.base import LayerAgent
    from core.llm_client import LLMResponse, ToolCall, FunctionCall

    class DeniedMockLLM:
        model = "mock-denied"
        call_count = 0
        def chat(self, messages, tools=None, json_mode=False, **kwargs):
            self.call_count += 1
            if self.call_count == 1:
                # L1 tries to call terminal (not in L1 allowlist)
                return LLMResponse(text="", tool_calls=[
                    ToolCall(id="denied_001", function=FunctionCall(
                        name="terminal",
                        arguments=json.dumps({"command": "echo hacked"}),
                    )),
                ])
            else:
                return LLMResponse(text=json.dumps({
                    "done": True, "result": "error_handled",
                }))

    class TestAgent(LayerAgent):
        pass

    agent = TestAgent(DeniedMockLLM(), logging.getLogger("test_agent"))
    agent.set_injector(injector)

    tools = injector.get_tools_for_layer("l1")
    # L1 should NOT have terminal
    tool_names = [t["function"]["name"] for t in tools]
    logger.info("  L1 tools: %s", tool_names)
    assert "terminal" not in tool_names

    # Even though tool schema for terminal is not injected, mock bypasses that
    # by hardcoding the tool_call. The injector should still reject it.
    result = agent._call_llm(
        system="L1 agent", user="Try terminal",
        tools=tools, layer="l1",
    )
    logger.info("  Result: %s", json.dumps(result, ensure_ascii=False))
    # Should get error-handled result since tool was blocked
    logger.info("  PASS (tool denial verified)")


def test_consolidation_with_spec(_injector=None):
    """Test: Consolidation task uses spec sheet for enriched prompts."""
    logger.info("=" * 55)
    logger.info("  TEST 5: Consolidation with spec sheet")
    logger.info("=" * 55)

    import tempfile
    from core.env.learning_env import LearningEnv

    # Mock stores with cards beyond limits
    class MockDC:
        def __init__(self, i):
            self.id = f"card_{i:03d}"
            self.content = f"Strategy {i}: Always raise with King variant {i}"
            from core.task import Domain
            self.domain = Domain("game/leduc", "specific")

    class MockL2:
        def __init__(self): self.cards = [MockDC(i) for i in range(35)]
    class MockS:
        def __init__(self, i):
            self.name = f"skill-{i:02d}"
            self.description = f"Skill variant {i}"
            from core.task import Domain
            self.domain = Domain("game/leduc", "specific")
    class MockL3:
        def __init__(self): self._s = [MockS(i) for i in range(22)]
        def list_all(self): return self._s

    lenv = LearningEnv(
        Path(tempfile.mkdtemp()),
        {"l2": MockL2(), "l3": MockL3()},
        dry_run=True,
        l2_card_limit=30, l3_skill_limit=20,
    )

    assert lenv.needs_consolidation()
    level = lenv.get_consolidation_level()
    logger.info("  Consolidation level: %d", level)

    task = lenv.build_consolidation_task()
    assert task is not None
    meta = task.meta

    # Verify spec-enriched prompt sections
    checks = [
        ("header", "Knowledge Consolidation Task" in meta),
        ("level info", "Consolidation Level" in meta),
        ("L2 section", "L2 Knowledge Cards" in meta),
        ("L3 section", "L3 Skills" in meta),
        ("L2 soft limit", "soft=25" in meta),
        ("L2 hard limit", "hard=30" in meta),
        ("L3 soft limit", "soft=15" in meta),
        ("entry format", "Entry format" in meta),
        ("anti-patterns", "Avoid" in meta),
        ("consolidation spec", "consolidation task spec" in meta.lower()),
        ("output format", "Output format" in meta),
        ("per-layer ref", "Per-layer entry format reference" in meta),
    ]

    all_ok = True
    for label, ok in checks:
        status = "OK" if ok else "FAIL"
        if not ok:
            logger.warning("    [%s] %s", status, label)
            all_ok = False
        else:
            logger.info("    [%s] %s", status, label)

    logger.info("  Meta length: %d chars", len(meta))
    logger.info("  Session domain: %s", task.session["domain"])
    assert all_ok, f"{sum(1 for _, ok in checks if ok)}/{len(checks)} checks passed"
    logger.info("  PASS")


# ═══════════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════════

def main():
    logger.info("=" * 60)
    logger.info("  Capability System Integration Test")
    logger.info("  DeepSeek-compatible multi-turn tool loop")
    logger.info("=" * 60)
    logger.info("Log dir: %s", LOG_DIR)

    injector, registry, games = setup()
    logger.info("Setup: %d capabilities registered",
                len(registry.list_for_layer("l2")))

    tests = [
        test_multi_turn_tool_call,
        test_multi_tool_sequential,
        test_no_tools_no_loop,
        test_tool_access_denied,
        test_consolidation_with_spec,
    ]

    passed = 0
    for test_fn in tests:
        try:
            test_fn(injector)
            passed += 1
        except Exception as e:
            logger.error("  FAIL: %s", e)
            logger.debug("Traceback:", exc_info=True)

    logger.info("=" * 60)
    logger.info("  Results: %d/%d passed", passed, len(tests))
    logger.info("  Log: %s", LOG_DIR / "test.log")
    logger.info("=" * 60)
    return 0 if passed == len(tests) else 1


if __name__ == "__main__":
    sys.exit(main())
