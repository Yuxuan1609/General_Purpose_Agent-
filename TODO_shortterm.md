# Short-term TODOs — Consolidation Pipeline

## 1. Consolidation task dispatch redesign [DONE]
- **Plan**: `docs/superpowers/plans/2026-06-08-consolidation-dispatch-redesign.md`
- `_CONSOLIDATION_FORMAT` 移除，meta 精简为 header
- `state["l1_task"]` / `["l2_task"]` / `["l3_task"]` 注入 per-layer 任务
- Dual trigger: capacity (count > limit) + maintenance (mod_count >= 5)
- `_filter_meta_for_layer()` 移除
- L3 dispatch: meta 声明 "All three layers must participate" → LLM 自然调度
- Domain directed: L2/L3 通过 L1 的 `selected_nodes` 结构进行域匹配
- Entry format + few-shot 移除（判断标准内嵌各层 task）

## 2. Quality fields: usefulness / misleading / comment [DONE]
- `Rule`, `KnowledgeCard`, `SkillMeta` 新增三个字段
- `usefulness`: -5..+5, `misleading`: -5..+5, `comment`: str
- `modify_l*` 工具 `required` 改为 `["id", "reason"]`，content 可选
- `confidence`/`activation`/`decay`/`success_count`/`failure_count`/`marker` 从 KnowledgeCard 移除
- `boost()`/`penalize()`/`apply_decay()` 移除，质量反馈统一走 modify 工具

## 3. Tool result feedback loop
- **File**: `core/layers/base.py` → `_call_llm()` tool call loop
- **Issue**: Tool results (e.g., "已记录: 删除 card_xxx") are terse; LLM may benefit from richer confirmation
- **Idea**: Include stats in tool responses (e.g., "已记录删除 card_xxx。当前 L2 待整理: 22 deprecate + 1 create")

## 4. DeepSeek strict mode + prompt optimization
- **File**: `core/layers/base.py`, `core/layers/l*/manager.py`
- **Issue**: Tool definitions lack `strict: true`; consolidation prompts don't guide tool usage strategy
- **Idea**: Enable strict mode (requires `/beta` endpoint + `additionalProperties: false` on all params + all properties in required). Add few-shot tool call examples to system prompts.

## 5. Full ToolRegistry mounting
- **File**: `core/layers/base.py`, `core/tools/registry.py`, `capability/`
- **Issue**: Only consolidation tools (6 functions) are mounted; registered tools (web_search, terminal, etc.) never injected
- **Idea**: Wire `ToolRegistry.get_tools_for_domain()` into all layer `_call_llm()` calls, filtered by current task domain.

## 6. Entry format clarification (design first, no code)
- **File**: `core/env/learning_env.py` -> `build_consolidation_task()` L2/L3 entry format sections
- **Issue**: ``**Entry format:**`` lists spec fields as plain markdown bullet points; LLM may not understand which fields it should populate vs which are system-generated
- **Idea**: Clearly label each field as [system-generated] vs [agent-populated]. Design the format layout before touching prompts.

---

## Long-term TODOs

### L7. Tools refined by domain
- Current tools use a flat per-layer allowlist (`DEFAULT_TOOL_ALLOWLIST` in `capability/tool_capability.py`)
- Each tool should eventually declare which domain(s) it operates in (e.g., `terminal` only for `cli`, `web_search` only for `research`)
- Layer+domain combined visibility matrix replaces simple per-layer allowlist
- `ToolProposal` feedback will need a domain field
