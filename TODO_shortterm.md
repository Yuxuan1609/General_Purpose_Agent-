# Short-term TODOs — Consolidation Pipeline

## 1. Consolidation strategy display optimization
- **File**: `core/env/learning_env.py` → `_CONSOLIDATION_FORMAT` + `build_consolidation_task()`
- **Issue**: Strategy field shows raw spec text ("1. 执行 Level 1 所有策略...") which is verbose and not actionable for LLM
- **Idea**: Convert to structured task list with per-level breakdown: what L1/L2/L3 should each do

## 2. L3 not dispatched in consolidation  
- **File**: `core/layers/l2/manager.py` → L2Agent.stage1 instruction
- **Issue**: L2 doesn't set `call_l3=true` for consolidation tasks, so L3 tools never run even when L3 skills exceed limit
- **Idea**: Add consolidation-specific logic to L2's stage1 prompt or manager.query() to force call_l3 when consolidation needed

## 3. L1 consolidation prompt quality
- **File**: `core/layers/l0_5_1/manager.py` → L1Agent.stage2 instruction
- **Issue**: L1 prompt tells agent to use tools but doesn't explain when to deprecate vs create
- **Idea**: Add L1-specific consolidation guidelines (dedup threshold, length check, domain-specific rule filter)

## 4. Tool result feedback loop
- **File**: `core/layers/base.py` → `_call_llm()` tool call loop
- **Issue**: Tool results (e.g., "已记录: 删除 card_xxx") are terse; LLM may benefit from richer confirmation
- **Idea**: Include stats in tool responses (e.g., "已记录删除 card_xxx。当前 L2 待整理: 22 deprecate + 1 create")

## 5. Consolidation dry-run reporting
- **File**: `core/env/learning_env.py` → `_apply_parsed_mods()`
- **Issue**: `apply_modifications()` summary shows "L2 cards: card_1, card_2, ..." which is unreadable with 20+ items
- **Idea**: Summarize as "L2: 22 deprecate'd, 1 created" instead of listing all targets

## 6. DeepSeek strict mode + prompt optimization
- **File**: `core/layers/base.py`, `core/layers/l*/manager.py`
- **Issue**: Tool definitions lack `strict: true`; consolidation prompts don't guide tool usage strategy
- **Idea**: Enable strict mode (requires `/beta` endpoint + `additionalProperties: false` on all params + all properties in required). Add few-shot tool call examples to system prompts.

## 7. Full ToolRegistry mounting
- **File**: `core/layers/base.py`, `core/tools/registry.py`, `capability/`
- **Issue**: Only consolidation tools (6 functions) are mounted; registered tools (web_search, terminal, etc.) never injected
- **Idea**: Wire `ToolRegistry.get_tools_for_domain()` into all layer `_call_llm()` calls, filtered by current task domain. Decide whether to use existing `LayerInjector`/`CapabilityRegistry` or a simpler approach.
