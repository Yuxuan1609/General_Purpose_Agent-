# Agent While-Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace hardcoded V-structure stage1/stage2/stage3 pipelines per layer with a unified `decide()` + Manager while-loop pattern.

**Architecture:** Each layer's Agent gets a single `decide()` method returning `{done, result, queries, ...}`; Manager's `query()` wraps this in a `while round < MAX_ROUNDS` loop, propagating sub-queries to the next lower layer. `_call_llm()` inner MAX_TOOL_TURNS loop retained unchanged.

**Tech Stack:** Python 3.11+, DeepSeek API

**Design Spec:** `docs/superpowers/specs/2026-06-11-agent-loop-design.md`

---

## File Structure

### Files Modified (7 core + 3 config + 2 doc)

| File | Change |
|------|--------|
| `core/layers/base.py` | Add `decide()` abstract method to `LayerAgent`; integrate `robust_parse` into `_call_llm` |
| `core/layers/l0_5_1/manager.py` | L1Agent: delete `stage1/stage2`, add `decide()`. L0_5_1Manager: `query()` → while loop |
| `core/layers/l2/manager.py` | L2Agent: delete `stage1/stage2`, add `decide()`. L2Manager: `query()` → while loop |
| `core/layers/l3/manager.py` | L3Agent: delete `execute()`, add `decide()`. L3Manager: `query()` → while loop |
| `core/env/learning_env.py` | Rewrite `_L1/_L2/_L3_OUTPUT` as valid JSON Schema objects (output-format-redesign item 1) |
| `config/layers/l1.yaml` | Add `max_rounds: 3` |
| `config/layers/l2.yaml` | Add `max_rounds: 3` |
| `config/layers/l3.yaml` | Add `max_rounds: 3` |
| `MAINTAIN.md` | Update function signatures |
| `README.md` | Fix outdated V-structure descriptions |

### No changes to:
- `core/executor.py` — entry signature unchanged
- `core/layer_message.py` — protocol unchanged
- `core/layers/comm.py` — Comm Agent unchanged
- `core/env/*` — all Environment unchanged
- `capability/*` — capability system unchanged
- `core/tools/*` — tool system unchanged
- `scripts/*` — script params unchanged

---

### Task 1: Add `decide()` abstract method to `LayerAgent` (base.py)

**Files:**
- Modify: `core/layers/base.py:42-192`

- [ ] **Add abstract decide() to LayerAgent**

```python
# In class LayerAgent (after _call_llm, before class LayerManager):

    @abstractmethod
    def decide(self, **kwargs) -> dict:
        """Single decision step: evaluate context and return {done, result, ...}.
        
        Each layer Agent implements this with its own schema.
        Manager calls this in a while loop.
        """
```

- [ ] **Verify file still parses**

Run: `python -c "from core.layers.base import LayerAgent, LayerManager; print('OK')"`

---

### Task 2: Rewrite L1 Agent + Manager

**Files:**
- Modify: `core/layers/l0_5_1/manager.py`

#### L1Agent changes (lines 16-248)

- [ ] **Add L1_DECISION_SCHEMA** (after STAGE2_SCHEMA, around line 48)

```python
    L1_DECISION_SCHEMA = {
        "type": "object",
        "properties": {
            "done": {"type": "boolean"},
            "result": {"type": "string", "description": "最终决策文本"},
            "queries": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "向下层 L2 查询的问题"},
                        "domains_hint": {
                            "type": "array", "items": {"type": "string"},
                            "description": "建议查询的领域",
                        },
                    },
                },
            },
            "reasoning": {"type": "string"},
        },
        "required": ["done", "reasoning"],
    }
```

- [ ] **Replace stage1() and stage2() with decide()**

Delete `stage1()` method (lines 176-203) and `stage2()` method (lines 205-248).

Add `decide()` method:

```python
    def decide(self, meta: str, state: dict, history: list,
               tools: list[dict] | None = None, layer: str = "l1") -> dict:
        """Single decision step for L1 while loop.
        
        Consolidation mode (l1_output_format in state):
          - Uses _L1_CONSOLIDATION_TOOLS, returns {done:True, result, ...}
        Normal mode:
          - Uses L1_DECISION_SCHEMA, returns {done, result, queries, reasoning}
        """
        l1_fmt = state.get("l1_output_format")
        instruction = (
            "你的职责：基于【行为准则】将任务拆解为下层需要协助的具体子任务。\n"
            "拆解时思考：已有信息能完成什么、还差什么子任务或信息、所需材料是否可以由下层提供。\n\n"
            "如果任务完全可以在 L1 层独立完成（无需 L2/L3 协助），设置 done=true 并给出 result。\n"
            "如果任务需要调用工具或需要下层知识，设置 done=false 并通过 queries 下发子任务。\n"
        )
        if l1_fmt:
            instruction += (
                "\n\n【整理任务】你只负责 L1 行为准则（Philosophy rules）的修改。"
                "不要修改 L2 知识卡片或 L3 技能。"
                "使用工具 deprecate_l1_rule / create_l1_rule / modify_l1_rule 记录修改。"
            )

        # Include domain nodes in system prompt if available
        domain_nodes = state.get("domain_nodes", [])
        nodes_text = ""
        if domain_nodes:
            lines = []
            for i, n in enumerate(domain_nodes):
                path = n.path if hasattr(n, 'path') else n.get('name', '?')
                desc = n.description if hasattr(n, 'description') else n.get('description', '')
                lines.append(f"{i + 1}. {path}\n   {desc}")
            nodes_text = "\n".join(lines)

        static_context = f"[领域节点]\n{nodes_text}" if nodes_text else ""
        system = self._build_system_prompt(instruction, meta, static_context=static_context)

        # Build user prompt: current state + history (L2 results)
        user_parts = [self._build_user_context(state)]
        if history:
            history_lines = []
            for h in history:
                query_text = h.get("query", "")
                l2_reply = h.get("l2_reply", {})
                reply_text = l2_reply.get("l0_5_1", {}).get("reply", "") if isinstance(l2_reply, dict) else str(l2_reply)
                history_lines.append(f"  Round {h.get('round', '?')}: query='{query_text}' → L2: {reply_text[:200]}")
            if history_lines:
                user_parts.append("[L2 历史返回]\n" + "\n".join(history_lines))
        user = "\n\n".join(user_parts)

        if l1_fmt:
            self._setup_l1_consolidation()
            tools = self._L1_CONSOLIDATION_TOOLS
            schema = None
            self._log.debug("  consolidation tools: %s",
                           [t["function"]["name"] for t in tools])
        else:
            tools = tools
            schema = self.L1_DECISION_SCHEMA

        result = self._call_llm(system, user, schema=schema, tools=tools, layer=layer)

        # Normalize consolidation mode output to match decide() contract
        if l1_fmt:
            result = {
                "done": True,
                "result": result.get("reply", ""),
                "reasoning": "",
                "queries": [],
            }
        return result
```

#### L0_5_1Manager changes (lines 251-346)

- [ ] **Add max_rounds param to __init__**

```python
    def __init__(self, meta_driver, philosophy, auxiliary_llm=None,
                 downstream=None, upward=None, downward=None,
                 domain_registry=None, max_rounds=3):
        super().__init__("l0_5_1", downstream, upward=upward, downward=downward)
        self._meta = meta_driver
        self._philosophy = philosophy
        self._agent = L1Agent(auxiliary_llm, philosophy) if auxiliary_llm else None
        self._registry = domain_registry
        self.max_rounds = max_rounds
        self._l1_notify: dict | None = None
```

- [ ] **Replace query() method** (lines 275-336)

```python
    def query(self, msg: LayerMessage | Any, trace_id: str = "") -> None:
        if isinstance(msg, LayerMessage):
            data = self._upward.receive(msg)
            if not trace_id:
                trace_id = msg.trace_id
        else:
            data = msg

        obs: TaskObservation = data if isinstance(data, TaskObservation) else TaskObservation(**data)
        meta = obs.meta

        if self._agent is None:
            logger.warning("L1Agent not initialized (no auxiliary_llm), skipping")
            self._l1_notify = {"done": True, "result": "", "reasoning": "no agent"}
            return

        state = dict(obs.state or {})
        history: list[dict] = []

        for round_idx in range(1, self.max_rounds + 1):
            logger.debug("── L1 decide [round %d/%d] ──", round_idx, self.max_rounds)

            # Inject domain nodes into state for decide()
            if self._registry:
                state["domain_nodes"] = self._registry.list_all()

            tools = self._injector.get_tools_for_layer("l1") if hasattr(self, '_injector') and self._injector else None
            # Also try agent's injector
            if tools is None and self._agent._injector:
                tools = self._agent._get_tools("l1")

            result = self._agent.decide(
                meta=meta, state=state, history=history,
                tools=tools, layer="l1",
            )
            logger.debug("  result: done=%s result=%s",
                         result.get("done"), str(result.get("result", ""))[:200])

            if result.get("done"):
                self._l1_notify = {
                    "done": True,
                    "result": result.get("result", ""),
                    "reasoning": result.get("reasoning", ""),
                }
                return

            queries = result.get("queries", [])
            if not queries:
                # No sub-queries but not done → treat as done
                self._l1_notify = {
                    "done": True,
                    "result": result.get("result", ""),
                    "reasoning": result.get("reasoning", ""),
                }
                return

            for q in queries:
                sub_state = {
                    **state,
                    "query_context": q,
                    "domains_hint": q.get("domains_hint", []),
                }
                sub_obs = TaskObservation(meta=q["query"], state=sub_state)
                q_msg = self._downward.wrap_query(
                    payload=sub_obs,
                    source=self.name,
                    target=self._downstream.name,
                    trace_id=trace_id,
                )
                self._downstream.query(q_msg, trace_id)
                l2_notify = self._downstream.collect_notify()
                history.append({
                    "round": round_idx,
                    "query": q["query"],
                    "l2_reply": l2_notify,
                })
                state[f"l2_round_{round_idx}"] = l2_notify

        # Force terminate
        logger.debug("── L1 force terminate (max_rounds=%d) ──", self.max_rounds)
        force = self._agent._call_llm(
            system=self._agent._build_system_prompt("force_terminate", meta),
            user="鉴于已超过最大轮次，基于已有信息给出最终决策。",
            layer="l1",
        )
        self._l1_notify = {"done": True, "result": str(force), "reasoning": "max_rounds"}
```

- [ ] **Update notify()** to use `_l1_notify`

```python
    def notify(self) -> Any:
        if self._l1_notify:
            result = dict(self._l1_notify)
            if self._agent:
                mods = self._agent.get_pending_mods()
                if mods:
                    result["l1_modifications"] = mods
            return result
        return {"status": "ok", "layer": self.name}
```

- [ ] **Verify**

Run: `python -c "from core.layers.l0_5_1.manager import L1Agent, L0_5_1Manager; print('OK')"`

---

### Task 3: Rewrite L2 Agent + Manager

**Files:**
- Modify: `core/layers/l2/manager.py`

#### L2Agent changes (lines 53-380)

- [ ] **Replace STAGE1_SCHEMA and STAGE2_SCHEMA with L2_DECISION_SCHEMA**

```python
    L2_DECISION_SCHEMA = {
        "type": "object",
        "properties": {
            "done": {"type": "boolean"},
            "reply": {"type": "string", "description": "回复上层查询的结论"},
            "selected_nodes": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "score": {"type": "number"},
                    },
                },
            },
            "selected_cards": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "card_id": {"type": "string"},
                        "domain": {"type": "string"},
                        "content": {"type": "string"},
                    },
                },
            },
            "queries_to_L3": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "domain": {"type": "string", "description": "目标领域"},
                        "task": {"type": "string", "description": "委托 L3 执行的技能任务"},
                    },
                },
            },
            "reasoning": {"type": "string"},
        },
        "required": ["done", "reasoning"],
    }
```

- [ ] **Replace stage1() and stage2() with decide()**

Delete `stage1()` (lines 241-285) and `stage2()` (lines 287-355).

Add `decide()`:

```python
    def decide(self, query: str, meta: str, state: dict, context: dict,
               tools: list[dict] | None = None, layer: str = "l2") -> dict:
        """Single decision step for L2 while loop.
        
        Consolidation mode (l2_output_format in state):
          - Uses _L2_CONSOLIDATION_TOOLS, returns {done:True, reply, ...}
        Normal mode:
          - Uses L2_DECISION_SCHEMA
        """
        l2_fmt = state.get("l2_output_format")
        selected_nodes = context.get("selected_nodes", [])
        candidate_cards = context.get("candidate_cards", [])
        l3_results = context.get("l3_results", [])

        # Build cards display
        cards_text = ""
        if candidate_cards:
            lines = []
            for c in candidate_cards:
                lines.append(f"[{c.get('domain', c.domain.path if hasattr(c, 'domain') else '')}] {c.get('content', c.content if hasattr(c, 'content') else c)}")
            cards_text = "\n".join(lines)
        elif selected_nodes:
            cards = self._get_cards_for_nodes(selected_nodes)
            node_scores = {n.get("name", ""): n.get("score", 0) for n in selected_nodes}
            cards_text = self._format_cards_with_relevance(cards, node_scores) if cards else (
                "⚠️ 当前所选领域暂无知识卡片。" if selected_nodes else "（无相关卡片）"
            )
        else:
            cards_text = "（无相关卡片）"

        # Build L3 results text
        l3_text = ""
        if l3_results:
            parts = []
            for l3r in l3_results:
                r = l3r.get("l3", {})
                if r.get("result"):
                    parts.append(f"L3: {r['result'][:200]}")
            l3_text = "\n".join(parts) if parts else "（L3 未返回信息）"

        instruction = (
            "你的核心任务是完成上层 query，Meta 提供任务整体背景。\n"
            "你的局部任务是思考：核心任务怎么完成、还差什么要素。\n\n"
            "当信息充分时设置 done=true 并给出 reply。\n"
            "当需要更多信息时：\n"
            "  - 通过 selected_nodes 选择相关领域节点\n"
            "  - 通过 queries_to_L3 向 L3 下发技能任务\n"
            "  - 后续轮次中你会收到 L3 的执行结果\n"
            "注意：你负责任务的部分执行和拆解下发，不做最终决策。"
        )
        if l2_fmt:
            instruction += (
                "\n\n【整理任务】你只负责 L2 知识卡片（KnowledgeCard）的修改。"
                "不要修改 L1 行为准则或 L3 技能。"
                "使用工具 deprecate_l2_card / create_l2_card / modify_l2_card 记录修改。"
            )

        system = self._build_system_prompt(instruction, meta)
        nodes_section = self._format_domain_nodes(selected_nodes)

        user = (
            f"[上层查询]\n{query}\n\n"
            f"{nodes_section}"
            f"[学习数据]\n{self._build_learning_section(state)}\n\n"
            f"[知识卡片]\n{cards_text}\n\n"
            f"[L3 返回]\n{l3_text if l3_text else '（无）'}"
        )

        if l2_fmt:
            self._setup_l2_consolidation()
            tools = self._L2_CONSOLIDATION_TOOLS
            self._log.debug("  consolidation tools: %s",
                           [t["function"]["name"] for t in tools])
            schema = None
        else:
            schema = self.L2_DECISION_SCHEMA

        result = self._call_llm(system, user, schema=schema, tools=tools, layer=layer)

        # Normalize consolidation mode
        if l2_fmt:
            result = {
                "done": True,
                "reply": result.get("reply", ""),
                "selected_nodes": [],
                "selected_cards": [],
                "queries_to_L3": [],
                "reasoning": "",
            }

        return result
```

#### L2Manager changes (lines 382-552)

- [ ] **Add max_rounds to __init__**

```python
    def __init__(self, knowledge, downstream=None,
                 upward=None, downward=None, auxiliary_llm=None,
                 domain_registry=None, max_rounds=3):
        super().__init__("l2", downstream, upward=upward, downward=downward)
        self._knowledge = knowledge
        self._agent = L2Agent(auxiliary_llm, knowledge) if auxiliary_llm else None
        self._registry = domain_registry
        self.max_rounds = max_rounds
        self._l2_notify: dict | None = None
        self._cards: list[dict] = []
```

- [ ] **Replace query() method** (lines 406-496)

```python
    def query(self, msg: LayerMessage | Any, trace_id: str = "") -> None:
        if isinstance(msg, LayerMessage):
            data = self._upward.receive(msg)
            if not trace_id:
                trace_id = msg.trace_id
        else:
            data = msg

        if isinstance(data, dict):
            obs = data.get("obs")
            query: str = data.get("query", "")
            selected_nodes: list[dict] = data.get("selected_nodes", [])
        else:
            obs = data
            query = ""
            selected_nodes = []
        meta = obs.meta if obs else ""

        # Enrich selected_nodes with correlation scores
        if self._registry and selected_nodes:
            for n in selected_nodes:
                name = n.get("name", n.get("path", ""))
                node = self._registry.get_node(name) if name else None
                if node and node.correlations:
                    n["correlations"] = node.correlations

        if self._agent is None:
            logger.warning("L2Agent not initialized (no auxiliary_llm), skipping")
            self._cards = []
            self._l2_notify = {"reply": "", "cards": [], "reasoning": "no agent"}
            self._propagate(obs, trace_id)
            return

        state = dict(obs.state) if obs and obs.state else {}
        context: dict = {
            "history": [],
            "selected_nodes": selected_nodes,
            "candidate_cards": [],
            "l3_results": [],
        }

        for round_idx in range(1, self.max_rounds + 1):
            logger.debug("── L2 decide [round %d/%d] ──", round_idx, self.max_rounds)

            tools = self._injector.get_tools_for_layer("l2") if hasattr(self, '_injector') and self._injector else None
            if tools is None and self._agent._injector:
                tools = self._agent._get_tools("l2")

            result = self._agent.decide(
                query=query, meta=meta, state=state,
                context=context, tools=tools, layer="l2",
            )
            logger.debug("  result: done=%s reply=%s",
                         result.get("done"), str(result.get("reply", ""))[:200])

            if result.get("done"):
                cards = result.get("selected_cards", [])
                self._cards = cards
                self._l2_notify = {
                    "reply": result.get("reply", ""),
                    "cards": cards,
                    "reasoning": result.get("reasoning", ""),
                }
                return

            if result.get("selected_nodes"):
                context["selected_nodes"] = result["selected_nodes"]
                context["candidate_cards"] = self._agent._get_cards_for_nodes(
                    result["selected_nodes"]
                )

            for q in result.get("queries_to_L3", []):
                sub_obs = TaskObservation(
                    meta=q["task"],
                    state={**state, "domain": q.get("domain", "")},
                )
                self._propagate(sub_obs, trace_id)
                l3_notify = self._downstream.collect_notify()
                context["l3_results"].append(l3_notify)
                context["history"].append({"round": round_idx, "query_to_L3": q})

        # Force terminate
        logger.debug("── L2 force terminate (max_rounds=%d) ──", self.max_rounds)
        force_reply = self._agent._call_llm(
            system=self._agent._build_system_prompt("force_terminate", obs.meta if obs else ""),
            user="基于已有卡片和上下文，给出最终回复。",
            layer="l2",
        )
        self._l2_notify = {
            "reply": str(force_reply),
            "cards": context.get("candidate_cards", []),
            "reasoning": "max_rounds",
        }
```

- [ ] **Update notify()**

```python
    def notify(self) -> Any:
        if self._l2_notify:
            result = dict(self._l2_notify)
            if self._agent:
                mods = self._agent.get_pending_mods()
                if mods:
                    result["l2_modifications"] = mods
            return result
        return {"status": "ok", "layer": self.name}
```

- [ ] **Verify**

Run: `python -c "from core.layers.l2.manager import L2Agent, L2Manager; print('OK')"`

---

### Task 4: Rewrite L3 Agent + Manager

**Files:**
- Modify: `core/layers/l3/manager.py`

#### L3Agent changes (lines 29-203)

- [ ] **Replace EXECUTE_SCHEMA with L3_DECISION_SCHEMA**

```python
    L3_DECISION_SCHEMA = {
        "type": "object",
        "properties": {
            "done": {"type": "boolean"},
            "result": {"type": "string", "description": "技能执行结果"},
            "skills_used": {"type": "array", "items": {"type": "string"}},
            "reasoning": {"type": "string"},
        },
        "required": ["done", "reasoning"],
    }
```

- [ ] **Replace execute() with decide()**

Delete `execute()` method (lines 131-203).

Add `decide()`:

```python
    def decide(self, meta: str, state: dict, context: dict,
               tools: list[dict] | None = None, layer: str = "l3") -> dict:
        """Single decision step for L3 while loop.
        
        Consolidation mode (l3_output_format in state):
          - Uses _L3_CONSOLIDATION_TOOLS, returns {done:True, result, ...}
        Normal mode:
          - Uses L3_DECISION_SCHEMA
        """
        l3_fmt = state.get("l3_output_format")
        matched_skills = context.get("matched_skills", [])
        l3_task = context.get("l3_task", "")

        current = state.get("current", "")
        skills_text = "\n".join(
            f"## {s.get('name', '')}: {s.get('description', '')}"
            f"\n  used={s.get('use_count', 0)} last={str(s.get('last_used', ''))[:10]}"
            f" useful=+{s.get('usefulness', 0)} mislead={s.get('misleading', 0)}"
            f"{chr(10) + '  comment: ' + s['comment'] if s.get('comment') else ''}"
            f"\n{_strip_frontmatter(s.get('content', '')[:800])}"
            for s in matched_skills
        ) if matched_skills else "（无匹配技能）"

        learning_data = ""
        if l3_fmt:
            units = state.get("learning_units", [])
            if isinstance(units, list) and units:
                recs = []
                for u in units:
                    l3_r = u.get("l3_reasoning", "")
                    if l3_r:
                        recs.append(f"[{u.get('index','?')}] L3: {l3_r[:200]}")
                if recs:
                    learning_data = "[学习数据]\n" + "\n".join(recs) + "\n\n"
        fb = state.get("feedback", "")
        l3_fb = state.get("l3_feedback", "")
        if l3_fb:
            fb = f"{fb}\n{l3_fb}" if fb else l3_fb
        fb_section = f"[L3 修改结果确认]\n{fb}\n\n" if fb else ""

        instruction = (
            "你的核心任务是完成 L2 下发的任务，Meta 提供任务整体背景。\n"
            "选择相关技能并基于技能内容执行任务。\n"
            "当任务完成时设置 done=true 并给出 result。"
        )
        if l3_fmt:
            instruction += (
                "\n\n【整理任务】你只负责 L3 技能（Skill）的修改。"
                "不要修改 L1 行为准则或 L2 知识卡片。"
                "使用工具 deprecate_l3_skill / create_l3_skill / modify_l3_skill 记录修改。"
            )
        system = self._build_system_prompt(instruction, meta)
        query_section = f"[上层查询]\n完成 L2 下发的任务：{l3_task}\n\n" if l3_task else ""

        user = (
            f"{fb_section}"
            f"{learning_data}"
            f"{query_section}"
            f"[当前局面]\n{current}\n\n"
            f"[可用技能]\n{skills_text}"
        )

        if l3_fmt:
            self._setup_l3_consolidation()
            tools = self._L3_CONSOLIDATION_TOOLS
            self._log.debug("  consolidation tools: %s",
                           [t["function"]["name"] for t in tools])
            schema = None
        else:
            schema = self.L3_DECISION_SCHEMA

        result = self._call_llm(system, user, schema=schema, tools=tools, layer=layer)

        # Normalize consolidation mode
        if l3_fmt:
            result = {
                "done": True,
                "result": result.get("reply", result.get("result", "")),
                "skills_used": [],
                "reasoning": "",
            }

        return result
```

#### L3Manager changes (lines 206-322)

- [ ] **Add max_rounds to __init__**

```python
    def __init__(self, skill_layer, downstream=None,
                 upward=None, downward=None, auxiliary_llm=None,
                 domain_registry=None, max_rounds=3):
        super().__init__("l3", downstream, upward=upward, downward=downward)
        self._skill_layer = skill_layer
        self._agent = L3Agent(auxiliary_llm) if auxiliary_llm else None
        self._registry = domain_registry
        self.max_rounds = max_rounds
        self._matched: list[str] = []
        self._matched_skills: list[dict] = []
        self._l3_notify: dict | None = None
```

- [ ] **Replace query() method** (lines 230-308)

```python
    def query(self, msg: LayerMessage | Any, trace_id: str = "") -> None:
        if isinstance(msg, LayerMessage):
            data = self._upward.receive(msg)
            if not trace_id:
                trace_id = msg.trace_id
        else:
            data = msg

        if isinstance(data, dict):
            obs = data.get("obs")
            l3_task = data.get("l3_task", "")
            selected_nodes = data.get("selected_nodes", [])
        else:
            obs = data
            l3_task = ""
            selected_nodes = []
        session = obs.session if obs else {}
        domain_path = session.get("domain", "general")

        # Deterministic: domain-based skill matching (unchanged)
        node_domains = [n.get("name", "") for n in selected_nodes if n.get("name")]
        domains_hint = session.get("domains_hint", [domain_path])
        if node_domains:
            all_domains = list(dict.fromkeys(domains_hint + node_domains))
        else:
            all_domains = domains_hint

        if self._registry:
            skill_ids = self._registry.get_items_for_domains("l3", all_domains)
            self._matched_skills = self._skill_layer.get_skills_by_ids(skill_ids)
            self._matched = [s["name"] for s in self._matched_skills]
        else:
            try:
                domain = Domain(domain_path, "specific")
            except Exception:
                domain = Domain("general", "general")
            matched = self._skill_layer.match(domain)
            self._matched = [s.name for s in matched]
            self._matched_skills = []
            for s in matched:
                content = ""
                if s.skill_dir:
                    skill_file = s.skill_dir / "SKILL.md"
                    if skill_file.exists():
                        content = skill_file.read_text(encoding="utf-8")
                self._matched_skills.append({
                    "name": s.name, "description": s.description,
                    "domain": s.domain.path, "content": content,
                })
        logger.debug("── L3 (match) ──")
        logger.debug("  domain: %s → %d skills", domain_path, len(self._matched))

        if not self._agent:
            logger.warning("L3Agent not initialized (no auxiliary_llm), skipping")
            self._l3_notify = {
                "skills_matched": len(self._matched),
                "skills_used": [],
                "result": "",
                "reasoning": "no agent",
            }
            return

        state = dict(obs.state) if obs and obs.state else {}
        context: dict = {
            "matched_skills": self._matched_skills,
            "l3_task": l3_task,
            "history": [],
        }

        for round_idx in range(1, self.max_rounds + 1):
            logger.debug("── L3 decide [round %d/%d] ──", round_idx, self.max_rounds)

            tools = self._injector.get_tools_for_layer("l3") if hasattr(self, '_injector') and self._injector else None
            if tools is None and self._agent._injector:
                tools = self._agent._get_tools("l3")

            meta = l3_task or (obs.meta if obs else "")
            result = self._agent.decide(
                meta=meta, state=state, context=context,
                tools=tools, layer="l3",
            )
            logger.debug("  result: done=%s result=%s",
                         result.get("done"), str(result.get("result", ""))[:200])

            if result.get("done"):
                self._l3_notify = {
                    "skills_matched": len(self._matched),
                    "skills_used": result.get("skills_used", []),
                    "result": result.get("result", ""),
                    "reasoning": result.get("reasoning", ""),
                }
                break

            context["history"].append({"round": round_idx, "result": result})

        # Propagate downstream (L4, reserved)
        if self._downstream:
            q_msg = self._downward.wrap_query(
                payload={"obs": obs}, source=self.name,
                target=self._downstream.name, trace_id=trace_id,
            )
            self._downstream.query(q_msg, trace_id)
```

- [ ] **Update notify()**

```python
    def notify(self) -> Any:
        if self._l3_notify:
            result = dict(self._l3_notify)
            if self._agent:
                mods = self._agent.get_pending_mods()
                if mods:
                    result["l3_modifications"] = mods
            return result
        return {"status": "ok", "layer": "l3", "skills_matched": len(self._matched)}
```

- [ ] **Verify**

Run: `python -c "from core.layers.l3.manager import L3Agent, L3Manager; print('OK')"`

---

### Task 4.5: Integrate robust_parse into _call_llm

**Files:**
- Modify: `core/layers/base.py:78-193`

**Design spec:** `docs/superpowers/plans/2026-06-11-output-format-redesign.md` — items 5, R3

- [ ] **Integrate robust_parse into _call_llm**

In `_call_llm`, replace the final `try/except json.JSONDecodeError` block that returns `{"_raw": text}` with a call to `robust_parse(text, schema)` which has multi-tier recovery (markdown code fence extraction, bracket repair, syntax repair, schema-aware salvage).

Change:
```python
            if schema is None:
                return {"reply": text, "reasoning": ""}
            try:
                parsed = json.loads(text)
                if not isinstance(parsed, dict):
                    self._log.warning("Expected JSON object, got %s", type(parsed).__name__)
                    return {"_raw": text, "_type": type(parsed).__name__}
                return parsed
            except json.JSONDecodeError:
                self._log.warning("JSON parse failed, raw text returned")
                return {"_raw": text}
```

To:
```python
            if schema is None:
                return {"reply": text, "reasoning": ""}
            try:
                parsed = json.loads(text)
                if not isinstance(parsed, dict):
                    self._log.warning("Expected JSON object, got %s", type(parsed).__name__)
                    return {"_raw": text, "_type": type(parsed).__name__}
                return parsed
            except json.JSONDecodeError:
                from core.json_repair import robust_parse
                self._log.debug("JSON parse failed, trying robust_parse")
                repaired = robust_parse(text, schema)
                if repaired:
                    return repaired
                self._log.warning("robust_parse also failed, returning raw")
                return {"_raw": text}
```

- [ ] **Verify**

Run: `python -c "from core.layers.base import LayerAgent; print('OK')"`

---

### Task 5: Update Config Files

**Files:**
- Modify: `config/layers/l1.yaml`
- Modify: `config/layers/l2.yaml`
- Modify: `config/layers/l3.yaml`

- [ ] **Add max_rounds to l1.yaml**

```yaml
# 每层 Manager while 循环最大轮次
max_rounds: 3
```

Add before `seed_rules:` section.

- [ ] **Add max_rounds to l2.yaml**

```yaml
# 每层 Manager while 循环最大轮次
max_rounds: 3
```

Add before `limits:` section.

- [ ] **Add max_rounds to l3.yaml**

```yaml
# 每层 Manager while 循环最大轮次
max_rounds: 3
```

Add before `limits:` section.

- [ ] **Also fix indentation bug in l1.yaml** (line 13 has `max_rule_length` indented under `max_rules`)

Change:
```yaml
  max_rule_length: 300
```
To:
```yaml
max_rule_length: 300
```

---

### Task 6: Update MAINTAIN.md

**Files:**
- Modify: `MAINTAIN.md`

- [ ] **Update LayerAgent section** (lines 93-103)

Replace:
```
| `LayerAgent._call_llm` | `(system, user, schema) → dict` | ... |
```
Add:
```
| `LayerAgent.decide` | `(**kwargs) → dict` (abstract) | 单步决策，各层自行实现 | Manager query() while 循环 | — |
```

- [ ] **Update L1Agent section** (lines 161-165)

Replace:
```
| `L1Agent.stage1` | `(meta, state) → str` | ... |
| `L1Agent.stage2` | `(meta, state) → dict{done, result, reasoning}` | ... |
```
With:
```
| `L1Agent.decide` | `(meta, state, history, tools, layer) → dict{done, result, queries, reasoning}` | 单步决策：判断完成/下发子查询 | L0_5_1Manager.query() | _build_system_prompt(), _build_user_context(), _call_llm() |
```

- [ ] **Update L1Manager section** (lines 157-160)

Replace:
```
| `L0_5_1Manager.query` | `(msg, trace_id) → None` | 重写：驱动 V-structure 循环 (Stage1→传给L2→Stage2) | ... |
```
With:
```
| `L0_5_1Manager.query` | `(msg, trace_id) → None` | while 循环调用 decide() → propagate queries 到 L2 → 收集 NOTIFY | Executor / 上层 | self._agent.decide(), self._downward.wrap_query(), collect_notify() |
```

- [ ] **Update L2Agent section** (lines 147-151)

Replace stage1/stage2 entries:
```
| `L2Agent.stage1` | ... |
| `L2Agent.stage2` | ... |
| `L2Agent.stage3` (if any) | ... |
```
With:
```
| `L2Agent.decide` | `(query, meta, state, context, tools, layer) → dict{done, reply, selected_nodes, queries_to_L3, ...}` | 单步决策：选择节点/查询L3/完成 | L2Manager.query() | _get_cards_for_nodes(), _call_llm() |
```

- [ ] **Update L2Manager section** (lines 141-145)

Replace:
```
| `L2Manager.query` | `(msg, trace_id) → None` | 重写：驱动 V-structure 循环 (Stage1→Stage2→propagate→Stage3) | ... |
| `L2Manager._enrich_cards` | ... |
```
With:
```
| `L2Manager.query` | `(msg, trace_id) → None` | while 循环 + decide() → propagate queries_to_L3 → 收集 NOTIFY | L0_5_1 DownwardComm | L2Agent.decide(), _propagate(), collect_notify() |
```

- [ ] **Update L3Agent section** (lines 134-135)

Replace:
```
| `L3Agent.execute` | `(meta, state) → dict{skills_used, result, reasoning}` | ... |
```
With:
```
| `L3Agent.decide` | `(meta, state, context, tools, layer) → dict{done, result, skills_used, reasoning}` | 单步决策：选择技能执行/完成 | L3Manager.query() | _call_llm() |
```

- [ ] **Update L3Manager section** (lines 130-136)

Replace:
```
| `L3Manager.query` | `(msg, trace_id) → None` | 确定性匹配技能 → L3Agent(LLM) 选择+执行 → 存储结果 | L2Manager._propagate | SkillLayer.match(), L3Agent.execute() |
```
With:
```
| `L3Manager.query` | `(msg, trace_id) → None` | 确定性匹配技能 → while 循环 decide() | L2Manager._propagate | SkillLayer.match(), L3Agent.decide() |
```

---

### Task 7: Fix README Outdated Content

**Files:**
- Modify: `README.md`

- [ ] **Update V-structure references** (lines 16-18)

Current:
```
| **L(0.5+1)** | 不可变宪法 + 可演化行为规则；含 L1Agent（两阶段 V-structure） |
| **L2** | 概率性知识卡片；含 L2Agent（三阶段 V-structure） |
| **L3** | SKILL.md 技能执行；domain 确定性匹配 + L3Agent（LLM 选择+执行） |
```
New:
```
| **L(0.5+1)** | 不可变宪法 + 可演化行为规则；含 L1Agent（while-loop decide） |
| **L2** | 概率性知识卡片；含 L2Agent（while-loop decide） |
| **L3** | SKILL.md 技能执行；domain 确定性匹配 + L3Agent（while-loop decide） |
```

- [ ] **Update line 22** — V-structure ref

Change:
```
每层 Manager 驱动 V-structure 循环
```
To:
```
每层 Manager 驱动 Agent while-loop 决策循环
```

- [ ] **Update line 49** — RESPONSE chain ref

Current:
```
 各层 Manager 驱动 V-structure Agent 循环
 RESPONSE 链返回 → NOTIFY → Executor 组装 prompt → LLM → action
```
New:
```
 各层 Manager 驱动 Agent while-loop 循环
 NOTIFY 链返回 → Executor 组装 prompt → LLM → action
```

---

### Task 8: Run Tests

- [ ] **Run all tests**

Run: `python -m pytest tests/ -v --tb=short 2>&1`

Expected: All tests pass (the mock-based tests should be unaffected by Agent method changes).

- [ ] **If any failures, fix them**

---

## Self-Review

**Spec coverage check:**
1. ✅ L1Agent: delete stage1/stage2, add decide() — Task 2
2. ✅ L0_5_1Manager: query() → while loop — Task 2
3. ✅ L2Agent: delete stage1/stage2, add decide() — Task 3
4. ✅ L2Manager: query() → while loop — Task 3
5. ✅ L3Agent: delete execute(), add decide() — Task 4
6. ✅ L3Manager: query() → while loop — Task 4
7. ✅ LayerAgent: add decide() abstract method — Task 1
8. ✅ Config: add max_rounds — Task 5
9. ✅ MAINTAIN.md update — Task 6
10. ✅ README update — Task 7
11. ✅ Tests — Task 8

**Placeholder check:** No placeholders found — all steps contain actual code.

**Type consistency:** All method signatures match between task definitions (base.py abstract → L1/L2/L3 implementations → Manager callers).
