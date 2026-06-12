# Cross-Round Context History Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When L1 queries L2 multiple times within one user input, L2 receives condensed context from previous rounds to avoid redundant work. Same for L2→L3. Context resets on each new executor trace.

**Architecture:** Each Manager tracks a `_downstream_history` list. On new trace (no `context_history` in state), clears it. Each round appends `{query, reply_summary}`. Injects into `sub_state["context_history"]` when propagating downstream.

---

## File Structure

| File | Change | Responsibility |
|------|--------|----------------|
| `core/layers/l0_5_1/manager.py` | Modify | Track `_l2_history`, inject `context_history` into L2 state |
| `core/layers/l2/manager.py` | Modify | Track `_l3_history`, clear on new trace; show `[本轮上下文]` in user prompt |
| `core/layers/l3/manager.py` | Modify | Read `context_history`, show `[本轮上下文]` in user prompt |
| `config/layers/l1.yaml` | Modify | `max_rounds: 3 → 5` (already done) |

---

### Task 1: L1 track and inject L2 context history

**Files:**
- Modify: `core/layers/l0_5_1/manager.py`

- [ ] **Add `_l2_history` to `L0_5_1Manager.__init__`**

Find `__init__` (around line 348). Add after `self._l1_notify`:

```python
self._l2_history: list[dict] = []
```

- [ ] **Clear `_l2_history` at start of `query()` when new trace**

Find `query()` (around line 363). After `state = dict(obs.state or {})`, add:

```python
state = dict(obs.state or {})
# Clear L2 history on new executor trace (no context_history in state)
if "context_history" not in state:
    self._l2_history.clear()
```

- [ ] **Inject `context_history` into sub_state when propagating to L2**

Find the `sub_state = {**state, ...}` block where L2 queries are propagated (around line 414). Replace `sub_state` with:

```python
sub_state = {
    **state,
    "query_context": q,
    "domains_hint": q.get("domains_hint", []),
    "context_history": list(self._l2_history),
}
```

- [ ] **Record L2 reply into `_l2_history` after each round**

Find where `l2_notify` is collected (around line 433). After `state[f"l2_round_{round_idx}"] = l2_notify`, add:

```python
# Record L2 round into context history (condensed)
l2_reply_text = ""
if isinstance(l2_notify, dict):
    l2_part = l2_notify.get("l2", {})
    if isinstance(l2_part, dict):
        l2_reply_text = l2_part.get("reply", "")
if not l2_reply_text:
    l2_reply_text = str(l2_notify)
self._l2_history.append({
    "query": q["query"][:200],
    "reply": l2_reply_text[:2000],
})
```

- [ ] **Verify import**

Run: `python -c "from core.layers.l0_5_1.manager import L0_5_1Manager; print('OK')"`

- [ ] **Commit**

```bash
git add core/layers/l0_5_1/manager.py config/layers/l1.yaml
git commit -m "feat: L1 tracks and injects L2 context history across rounds"
```

---

### Task 2: L2 show context history, track L3 history

**Files:**
- Modify: `core/layers/l2/manager.py`

- [ ] **Add `_l3_history` to `L2Manager.__init__`**

Find `__init__` (around line 467). Add after `self._cards`:

```python
self._l3_history: list[dict] = []
```

- [ ] **Clear `_l3_history` at start of `query()` when new trace**

Find `query()` (around line 481). After `state = dict(obs.state) if obs and obs.state else {}`, add:

```python
state = dict(obs.state) if obs and obs.state else {}
# Clear L3 history on new executor trace (no context_history in state)
if "context_history" not in state:
    self._l3_history.clear()
```

- [ ] **Add `[本轮上下文]` section to user prompt**

Find L2 `decide()` user prompt (around line 328). Add `[本轮上下文]` section before `[上层查询]`:

```python
# Build context history text
context_text = ""
ctx_history = state.get("context_history", [])
if ctx_history:
    lines = []
    for i, h in enumerate(ctx_history):
        lines.append(f"第{i+1}次查询: {h.get('query', '')[:300]}")
        lines.append(f"第{i+1}次结果: {h.get('reply', '')[:500]}")
    context_text = "\n".join(lines)

user = (
    f"[上层查询]\n{query}\n\n"
    f"{'[本轮上下文]\n' + context_text + '\n\n' if context_text else ''}"
    f"{nodes_section}"
    f"[学习数据]\n{self._build_learning_section(state)}\n\n"
    f"[知识卡片]\n{cards_text}\n\n"
    f"[L3 返回]\n{l3_text if l3_text else '（无）'}"
)
```

- [ ] **Track L3 history when propagating queries_to_L3**

Find the `queries_to_L3` section in `query()` (after decide() result). After collecting L3 results, add:

```python
for q in result.get("queries_to_L3", []):
    sub_state_with_history = {
        **state,
        "domain": q.get("domain", ""),
        "context_history": list(self._l3_history),
    }
    sub_obs = TaskObservation(
        meta=q["task"],
        state=sub_state_with_history,
    )
    self._propagate(sub_obs, trace_id)
    l3_notify = self._downstream.collect_notify()
    # Record L3 round
    l3_result_text = ""
    if isinstance(l3_notify, dict):
        l3_part = l3_notify.get("l3", {})
        if isinstance(l3_part, dict):
            l3_result_text = l3_part.get("result", "")
    self._l3_history.append({
        "query": q["task"][:200],
        "reply": l3_result_text[:1000],
    })
```

- [ ] **Verify import**

Run: `python -c "from core.layers.l2.manager import L2Manager; print('OK')"`

- [ ] **Commit**

```bash
git add core/layers/l2/manager.py
git commit -m "feat: L2 shows context history and tracks L3 history"
```

---

### Task 3: L3 show context history

**Files:**
- Modify: `core/layers/l3/manager.py`

- [ ] **Add `[本轮上下文]` to user prompt**

Find L3 `decide()` user prompt (around line 193). Add context section:

```python
# Build context history text
context_text = ""
ctx_history = state.get("context_history", [])
if ctx_history:
    lines = []
    for i, h in enumerate(ctx_history):
        lines.append(f"第{i+1}次请求: {h.get('query', '')[:300]}")
        lines.append(f"第{i+1}次结果: {h.get('reply', '')[:500]}")
    context_text = "\n".join(lines)

user = (
    f"{fb_section}"
    f"{learning_data}"
    f"{query_section}"
    f"{'[本轮上下文]\n' + context_text + '\n\n' if context_text else ''}"
    f"[当前局面]\n{current}\n\n"
    f"[可用技能]\n{skills_text}"
)
```

- [ ] **Verify import**

Run: `python -c "from core.layers.l3.manager import L3Manager; print('OK')"`

- [ ] **Commit**

```bash
git add core/layers/l3/manager.py
git commit -m "feat: L3 shows context history from previous calls"
```

---

### Task 4: Verify

- [ ] **Run full tests**

Run: `python -m pytest tests/ -q --tb=short`

Expected: all 209 pass.

---

## Self-Review

**Spec coverage:**
1. ✅ L1 tracks and injects L2 context — Task 1
2. ✅ L2 shows context, tracks L3 history — Task 2
3. ✅ L3 shows context — Task 3
4. ✅ max_rounds increased — config already updated
5. ✅ Tests — Task 4

**Placeholder check:** No TBDs.

**History reset logic:**
- L1: `"context_history" not in state` clears `_l2_history` — Executor sends new trace with fresh state (no context_history key) ✓
- L2: same check clears `_l3_history` — state inherits context_history from L1's propagation on subsequent rounds ✓
- L3: L2 injects `context_history` from `_l3_history` into sub_obs state ✓
