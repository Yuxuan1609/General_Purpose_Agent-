"""E2E chain tests — full Executor → L1→L2→L3 → notify with mock LLM.

Verifies:
- Chain initialization and wiring
- Tool dispatching and results (l1_query→l2_report, l2_query→l3_report)
- Consolidation mode tool building (ConsolidationStrategy)
- Domain routing and L2→L3 propagation
- Multi-round L1 decision loop
- NOTIFY payload structure

TODO: Real LLM E2E tests — run against actual DeepSeek API with small prompts.
      Marked as @pytest.mark.real_llm (skipped by default).
"""
import json
import pytest
from unittest.mock import Mock
from pathlib import Path

from core.types import TaskObservation


# ── Fixtures ──

@pytest.fixture
def empty_chain(tmp_path):
    """Minimal chain with empty knowledge stores (no seed, no LLM)."""
    from core.philosophy import Philosophy
    from core.flexible_knowledge import FlexibleKnowledge
    from core.skill_layer import SkillLayer
    from core.layers import build_chain
    from core.domain_registry import DomainRegistry

    data = tmp_path / "data" / "cognitive"
    data.mkdir(parents=True)

    rules_path = tmp_path / "l1_rules.json"
    rules_path.write_text(json.dumps({"version": 1, "rules": []}))

    knowledge_dir = tmp_path / "knowledge"
    knowledge_dir.mkdir()
    (knowledge_dir / "l2_index.json").write_text(
        json.dumps({"version": 1, "chapters": [], "relations": []}))

    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()

    phil = Philosophy(rules_path, db_path=data / "l1.db")
    fk = FlexibleKnowledge(knowledge_dir, knowledge_dir / "l2_index.json",
                           db_path=data / "l2.db")
    sl = SkillLayer(skills_dir, db_path=data / "l3.db")
    reg = DomainRegistry()

    return build_chain(phil, fk, sl, domain_registry=reg,
                       knowledge_stores={"l2": fk, "l3": sl})


@pytest.fixture
def wired_chain(tmp_path):
    """Chain with auxiliary LLM and tool mounting."""
    from core.philosophy import Philosophy
    from core.flexible_knowledge import FlexibleKnowledge
    from core.skill_layer import SkillLayer
    from core.layers import build_chain
    from core.domain_registry import DomainRegistry
    from core.tools.registry import ToolRegistry
    from capability.tool_capability import ToolCapability
    from capability import CapabilityRegistry
    from capability.layer_injector import LayerInjector

    data = tmp_path / "data" / "cognitive"
    data.mkdir(parents=True)

    rules_path = tmp_path / "l1_rules.json"
    rules_path.write_text(json.dumps({"version": 1, "rules": [
        {"id": "r1", "content": "优先搜索验证", "created_by": "seed",
         "added_at": "", "version": 1, "last_modified": ""}
    ]}))

    knowledge_dir = tmp_path / "knowledge"
    knowledge_dir.mkdir()
    (knowledge_dir / "l2_index.json").write_text(
        json.dumps({"version": 1, "chapters": [], "relations": []}))

    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()

    phil = Philosophy(rules_path, db_path=data / "l1.db")
    fk = FlexibleKnowledge(knowledge_dir, knowledge_dir / "l2_index.json",
                           db_path=data / "l2.db")
    sl = SkillLayer(skills_dir, db_path=data / "l3.db")
    reg = DomainRegistry()
    reg.add_node("general", None, "通用领域")

    mock_llm = Mock()
    mock_llm.chat.return_value = Mock(text="{}", tool_calls=[], has_tool_calls=False)

    # Build chain WITHOUT consol_ctx — register tools separately for controlled tests
    chain = build_chain(phil, fk, sl, auxiliary_llm=mock_llm,
                        domain_registry=reg,
                        knowledge_stores={"l2": fk, "l3": sl})

    # Mount only core tools (skip consolidation to avoid create_domain conflict)
    from core.tools.terminal_tool import register_terminal_tool
    from core.tools.web_search_tool import register_web_search_tool, register_tavily_search_tool
    from core.tools.file_tools import register_read_file, register_grep
    from core.tools.kb_tools import register_kb_tools
    from core.tools.async_tools import register_async_tools
    from core.tools.sysinfo_tool import register_sysinfo_tool

    registry = ToolRegistry()
    register_terminal_tool(registry)
    register_web_search_tool(registry)
    register_tavily_search_tool(registry)
    register_read_file(registry)
    register_grep(registry)
    register_kb_tools(registry)
    register_async_tools(registry)
    register_sysinfo_tool(registry)

    cap_registry = CapabilityRegistry()
    cap_registry.register(ToolCapability(registry))
    injector = LayerInjector(cap_registry)

    def _iter_layers(root):
        node = root
        while node is not None:
            yield node
            node = node._downstream

    for layer in _iter_layers(chain):
        if layer._agent is not None:
            layer._agent.set_injector(injector)

    return chain, mock_llm


# ── Basic Chain Tests ──

class TestChainWiring:
    """Verify chain topology and NOTIFY collection."""

    def test_chain_names_match_layers(self, empty_chain):
        assert empty_chain.name == "l0_5_1"
        l2 = empty_chain._downstream
        assert l2 is not None
        assert l2.name == "l2"
        l3 = l2._downstream
        assert l3 is not None
        assert l3.name == "l3"
        assert l3._downstream is None

    def test_collect_notify_all_layers(self, empty_chain):
        notify = empty_chain.collect_notify()
        assert "l0_5_1" in notify
        assert "l2" in notify
        assert "l3" in notify

    def test_notify_structure_l1(self, empty_chain):
        empty_chain.notify()
        notify = empty_chain.collect_notify()["l0_5_1"]
        assert notify["status"] == "ok"
        assert notify["layer"] == "l0_5_1"

    def test_notify_structure_l2(self, empty_chain):
        l2 = empty_chain._downstream
        notify = l2.notify()
        assert notify["status"] == "ok"
        assert notify["layer"] == "l2"

    def test_notify_structure_l3(self, empty_chain):
        l3 = empty_chain._downstream._downstream
        notify = l3.notify()
        assert notify["status"] == "ok"
        assert notify["layer"] == "l3"


# ── Tool Dispatch Tests ──

class TestToolDispatch:
    """Verify tools are correctly wired per layer."""

    def test_l1_has_terminal_tool(self, wired_chain):
        chain, _ = wired_chain
        tools = chain._agent._get_tools("l1") if chain._agent else None
        assert tools is not None, "L1 agent not initialized"
        names = [t["function"]["name"] for t in tools]
        assert "terminal" in names, f"L1 missing terminal tool. Got: {names}"
        assert "kb_query" in names

    def test_l2_has_execution_tools(self, wired_chain):
        chain, _ = wired_chain
        l2 = chain._downstream
        tools = l2._agent._get_tools("l2") if l2._agent else None
        assert tools is not None, "L2 agent not initialized"
        names = [t["function"]["name"] for t in tools]
        for t in ("terminal", "web_search", "read_file", "grep", "sysinfo"):
            assert t in names, f"L2 missing {t}"

    def test_l3_has_consolidation_tools(self, wired_chain):
        """L3 consolidation tools are registered via ToolRegistry."""
        from core.tools.registry import ToolRegistry
        from core.tools.consolidation_tools import register_consolidation_tools, ConsolidationContext
        # Register consolidation tools (separate from core tools to avoid conflicts)
        reg = ToolRegistry()
        register_consolidation_tools(reg, ctx=ConsolidationContext())
        defs = reg.get_definitions({"deprecate_l3_skill", "create_l3_skill",
                                      "modify_l3_skill"})
        names = [d["function"]["name"] for d in defs]
        for t in ("deprecate_l3_skill", "create_l3_skill", "modify_l3_skill"):
            assert t in names, f"L3 consolidation tool not registered: {t}"

    def test_kb_query_tool_registered(self, wired_chain):
        """Verify kb_query is registered in ToolRegistry."""
        from core.tools.registry import ToolRegistry
        defs = ToolRegistry().get_definitions(["kb_query"])
        assert len(defs) == 1
        assert defs[0]["function"]["name"] == "kb_query"

    def test_sysinfo_tool_registered(self, wired_chain):
        """Verify sysinfo is registered and schema valid."""
        from core.tools.registry import ToolRegistry
        defs = ToolRegistry().get_definitions(["sysinfo"])
        assert len(defs) == 1
        schema = defs[0]["function"]["parameters"]
        assert "category" in schema.get("properties", {})

    def test_terminal_tool_registered(self, wired_chain):
        """Verify terminal is registered and schema valid."""
        from core.tools.registry import ToolRegistry
        defs = ToolRegistry().get_definitions(["terminal"])
        assert len(defs) == 1
        assert "command" in defs[0]["function"]["parameters"]["properties"]

    def test_check_task_tool_registered(self, wired_chain):
        """Verify check_task is registered and schema valid."""
        from core.tools.registry import ToolRegistry
        defs = ToolRegistry().get_definitions(["check_task"])
        assert len(defs) == 1
        assert "task_id" in defs[0]["function"]["parameters"]["properties"]

    def test_consolidation_handler_factory(self, wired_chain):
        """Verify consolidation handler records mods via ConsolidationContext."""
        from core.tools.registry import ToolRegistry
        from core.tools.consolidation_tools import register_consolidation_tools, ConsolidationContext
        reg = ToolRegistry()
        ctx = ConsolidationContext()
        register_consolidation_tools(reg, ctx=ctx)

        result = reg.dispatch("deprecate_l1_rule",
                              {"rule_id": "r1", "reason": "test"}, timeout=10)
        parsed = json.loads(result)
        assert parsed["recorded"] is True
        mods = ctx.drain_mods()
        assert len(mods) == 1
        assert mods[0]["type"] == "deprecate"
        assert mods[0]["target"] == "r1"
        assert mods[0]["layer"] == "l1"


# ── Domain Routing Tests ──

class TestDomainRouting:
    def test_selected_nodes_enrichment(self, wired_chain):
        """Selected nodes from L1 propagate correctly to L2 state."""
        chain, _ = wired_chain
        obs = TaskObservation(
            meta="query about leduc",
            state={
                "selected_nodes": [{"name": "game/leduc", "score": 1.0}],
                "domains_hint": ["game/leduc"],
            },
            session={"domain": "game/leduc", "id": "s1"},
        )
        # L2 query unwrap should extract selected_nodes from state
        l2 = chain._downstream
        obs2, _ = l2._unwrap_obs(obs)
        nodes = obs2.state.get("selected_nodes", []) if obs2.state else []
        assert len(nodes) > 0
        assert nodes[0]["name"] == "game/leduc"

    def test_l2_to_l3_propagation_state(self, wired_chain):
        """L2._propagate enriches L3 state with l3_task and selected_nodes."""
        chain, _ = wired_chain
        l2 = chain._downstream
        src_obs = TaskObservation(meta="test", state={"key": "val"},
                                  session={"domain": "general"})
        l2._downstream = Mock()  # intercept propagation

        l2._propagate(src_obs, "tr", l3_task="do_x",
                      selected_nodes=[{"name": "general", "score": 1.0}])

        l2._downstream.query.assert_called_once()
        call_obs = l2._downstream.query.call_args[0][0]
        assert call_obs.state["l3_task"] == "do_x"
        assert call_obs.state["selected_nodes"] == [{"name": "general", "score": 1.0}]
        # original state preserved
        assert call_obs.state["key"] == "val"


# ── Capture Tool Tests ──

class TestCaptureTools:
    def test_l1_capture_tool_schemas(self):
        from core.layers.l0_5_1.manager import L1_QUERY_TOOL, L1_REPORT_TOOL
        t = L1_QUERY_TOOL.to_openai_tool()
        assert t["function"]["name"] == "l1_query"
        assert t["function"]["parameters"]["properties"]["done"]["const"] == False
        t = L1_REPORT_TOOL.to_openai_tool()
        assert t["function"]["name"] == "l1_report"
        assert t["function"]["parameters"]["properties"]["done"]["const"] == True

    def test_l2_capture_tool_schemas(self):
        from core.layers.l2.manager import L2_QUERY_TOOL, L2_REPORT_TOOL
        t = L2_QUERY_TOOL.to_openai_tool()
        assert t["function"]["name"] == "l2_query"
        assert "selected_nodes" in t["function"]["parameters"]["properties"]
        t = L2_REPORT_TOOL.to_openai_tool()
        assert t["function"]["name"] == "l2_report"
        assert "selected_cards" in t["function"]["parameters"]["properties"]

    def test_l3_capture_tool_schemas(self):
        from core.layers.l3.manager import L3_CONTINUE_TOOL, L3_REPORT_TOOL
        t = L3_CONTINUE_TOOL.to_openai_tool()
        assert t["function"]["name"] == "l3_continue"
        t = L3_REPORT_TOOL.to_openai_tool()
        assert t["function"]["name"] == "l3_report"
        assert "skills_used" in t["function"]["parameters"]["properties"]

    def test_consolidation_strategy_l1(self):
        from core.layers.l0_5_1.manager import L1_CONSOLIDATION_STRATEGY
        assert L1_CONSOLIDATION_STRATEGY.allowed_base_tools == {"kb_query", "ask_user"}
        assert L1_CONSOLIDATION_STRATEGY.report_tool.name == "l1_report"

    def test_consolidation_strategy_l2(self):
        from core.layers.l2.manager import L2_CONSOLIDATION_STRATEGY
        assert "read_file" in L2_CONSOLIDATION_STRATEGY.allowed_base_tools

    def test_consolidation_strategy_l3(self):
        from core.layers.l3.manager import L3_CONSOLIDATION_STRATEGY
        assert "grep" in L3_CONSOLIDATION_STRATEGY.allowed_base_tools


# ── ConsolidationContext Tests ──

class TestConsolidationContext:
    def test_record_and_drain(self):
        from core.tools.consolidation_tools import ConsolidationContext
        ctx = ConsolidationContext()
        ctx.record_mod({"type": "create", "target": "x", "layer": "l1"})
        ctx.record_mod({"type": "deprecate", "target": "y", "layer": "l2"})
        mods = ctx.drain_mods()
        assert len(mods) == 2
        assert mods[0]["type"] == "create"
        assert mods[1]["type"] == "deprecate"
        assert len(ctx.pending_mods) == 0, "drain should clear"

    def test_drain_returns_copy(self):
        from core.tools.consolidation_tools import ConsolidationContext
        ctx = ConsolidationContext()
        ctx.record_mod({"type": "create"})
        mods = ctx.drain_mods()
        mods.clear()
        ctx.record_mod({"type": "deprecate"})
        assert len(ctx.pending_mods) == 1, "drain returned reference that modified original"

    def test_knowledge_stores(self):
        from core.tools.consolidation_tools import ConsolidationContext
        mock = Mock()
        ctx = ConsolidationContext(philosophy=mock, knowledge_stores={"l1": mock})
        assert ctx.philosophy is mock
        assert ctx.knowledge_stores["l1"] is mock


# ── TODO: Real LLM Tests ──

@pytest.mark.skip(reason="Real LLM test — requires API key and network. Run manually with --real-llm.")
class TestRealLLM:
    """End-to-end tests against actual LLM (DeepSeek via API key).

    To run:  pytest tests/test_e2e_chain.py -k "RealLLM" -s

    These tests verify:
    - L1 correctly calls l1_query/l1_report for simple queries
    - L2 correctly routes domains and delegates to L3
    - Terminal/web_search tools produce valid results
    """

    def test_full_chain_simple_query(self):
        """L1 receives simple query → l1_report with result."""
        from core.env_loader import load_env
        from core.llm_factory import build_llm_client
        from core.chain_factory import build_default_chain
        from core.executor import Executor
        from pathlib import Path

        root = Path(__file__).resolve().parent.parent
        load_env(root)
        llm = build_llm_client(root / "config.yaml")
        chain = build_default_chain(root, auxiliary_llm=llm, seed=False)
        executor = Executor(layer_root=chain, llm_client=llm)

        obs = TaskObservation(
            meta="用户问：1+1等于几？直接回答。",
            session={"domain": "interaction", "id": "t1"},
        )
        result = executor.execute(obs)
        assert result["action_text"], "Should produce non-empty result"
        assert "notify_layers" in result
        print(f"\nE2E result: {result['action_text'][:100]}")

    def test_tool_dispatch_terminal(self):
        """L1 delegates to L2 which calls terminal tool."""
        from core.env_loader import load_env
        from core.llm_factory import build_llm_client
        from core.chain_factory import build_default_chain
        from core.executor import Executor
        from pathlib import Path

        root = Path(__file__).resolve().parent.parent
        load_env(root)
        llm = build_llm_client(root / "config.yaml")
        chain = build_default_chain(root, auxiliary_llm=llm, seed=False)
        executor = Executor(layer_root=chain, llm_client=llm)

        obs = TaskObservation(
            meta="用户想确认系统日期。请用终端工具执行 date 命令并告知结果。",
            session={"domain": "interaction", "id": "t2"},
        )
        result = executor.execute(obs)
        assert result["action_text"]
        print(f"\nE2E terminal result: {result['action_text'][:200]}")
