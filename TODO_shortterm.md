# Short-term TODOs — Consolidation Pipeline

## 1. Consolidation task dispatch redesign (merge of old #1 + #2)
- **File**: `core/env/learning_env.py` → `build_consolidation_task()`, `core/layers/l2/manager.py` → L2Agent.stage1
- **Issues**:
  1. Strategy field shows raw spec text, not actionable
  2. L3 never dispatched (L2 stage1 unaware of consolidation → `call_l3=false`)
  3. Card dump is unfiltered: `build_consolidation_task()` dumps ALL L2 cards from ALL domains as plain list, no domain-specific targeting
- **Target flow**:
  ```
  Env → declares "L1 needs X optimizations, L2 needs Y, L3 needs Z" (3层都可见)
  L1 agent → 只收到 L1 自己的优化任务
  L2 agent → 只收到 L2 自己的优化任务（按 domain 定向检索）
  L3 agent → 只收到 L3 自己的优化任务
  ```
- **Design points**:
  - Env 在 meta 中标注需要整理的层和 domain，每层只看到本层的任务
  - L2 的 stage1 prompt 加 consolidation 感知：检测到 consolidate → 必须 `call_l3=true` + 给出 l3_task
  - L2 card dump 从全局列表改为 per-domain 定向检索（由 domain_registry 驱动）
  - L3 信息归 L3 管理，L2 只负责调度不负责 L3 内容判断

## 2. L1 consolidation prompt quality
- **File**: `core/layers/l0_5_1/manager.py` → L1Agent.stage2 instruction
- **Issue**: L1 prompt tells agent to use tools but doesn't explain when to deprecate vs create
- **Idea**: Add L1-specific consolidation guidelines (dedup threshold, length check, domain-specific rule filter)

## 3. Tool result feedback loop
- **File**: `core/layers/base.py` → `_call_llm()` tool call loop
- **Issue**: Tool results (e.g., "已记录: 删除 card_xxx") are terse; LLM may benefit from richer confirmation
- **Idea**: Include stats in tool responses (e.g., "已记录删除 card_xxx。当前 L2 待整理: 22 deprecate + 1 create")



## 5. DeepSeek strict mode + prompt optimization
- **File**: `core/layers/base.py`, `core/layers/l*/manager.py`
- **Issue**: Tool definitions lack `strict: true`; consolidation prompts don't guide tool usage strategy
- **Idea**: Enable strict mode (requires `/beta` endpoint + `additionalProperties: false` on all params + all properties in required). Add few-shot tool call examples to system prompts.

## 6. Full ToolRegistry mounting
- **File**: `core/layers/base.py`, `core/tools/registry.py`, `capability/`
- **Issue**: Only consolidation tools (6 functions) are mounted; registered tools (web_search, terminal, etc.) never injected
- **Idea**: Wire `ToolRegistry.get_tools_for_domain()` into all layer `_call_llm()` calls, filtered by current task domain. Decide whether to use existing `LayerInjector`/`CapabilityRegistry` or a simpler approach.

## 8. Entry format clarification (design first, no code)
- **File**: `core/env/learning_env.py` -> `build_consolidation_task()` L2/L3 entry format sections
- **Issue**: ``**Entry format:**`` lists spec fields as plain markdown bullet points; LLM may not understand which fields it should populate vs which are system-generated
- **Idea**: Clearly label each field as [system-generated] vs [agent-populated]. Replace bullet list with a table showing field name, who fills it, and whether required. Design the format layout before touching prompts.
