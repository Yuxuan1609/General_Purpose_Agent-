# Short-term TODOs — Consolidation Pipeline

## 1. Consolidation task dispatch redesign [PLAN READY]
- **Plan**: `docs/superpowers/plans/2026-06-08-consolidation-dispatch-redesign.md`
- **File**: `core/env/learning_env.py` → `build_consolidation_task()`, `core/layers/*/manager.py`, `core/layers/base.py`
- **Design decisions confirmed**:
  - **DD1 Dual trigger**: 容量超限 (soft/hard) + 修改累积计数 (per-domain mod_count >= 5)
  - **DD2 Quality fields**: `usefulness` / `misleading` / `comment` 加在 `Rule`, `KnowledgeCard`, `SkillMeta` 上，由 reflect/consolidate 的 modify tools 更新
  - **DD3 Card display**: `conf=N used=N last=YYYY-MM-DD useful=+N mislead=N | content`，comment 换行缩进，不要 activation/succ/fail/decay
  - **DD4 Env injection + layer self-retrieval**: `state["lX_task"]` 写 target_domains + criteria，cards/skills 正文由各层 Manager 自己取；L1 不列规则（system prompt 已有）
- **关键变更**:
  1. `_CONSOLIDATION_FORMAT` 拆掉，meta 只留级别声明 + 统计摘要
  2. `state["l1_task"]` / `["l2_task"]` / `["l3_task"]` 注入 per-layer 任务
  3. L2 stage1 prompt 加 consolidate 感知 → `call_l3=true`
  4. 移除 `_filter_meta_for_layer()`
  5. 修改计数持久化到 `learning_stats.json` 的 `_consolidation` 节

## 2. Quality fields: usefulness / misleading / comment
- **File**: `core/flexible_knowledge.py` → `KnowledgeCard`, `core/philosophy.py` → `Rule`, `core/skill_layer.py` → `SkillMeta`
- **Add fields**: `usefulness: int = 0`, `misleading: int = 0`, `comment: str = ""`
- **Tool updates**: `modify_l1_rule` / `modify_l2_card` / `modify_l3_skill` 加可选参数 (不 required)
- **Prompt updates**: consolidation 卡片行显示 `useful=+N mislead=N`，comment 换行缩进
- **Depends on**: #1 (consolidation dispatch redesign)

## 3. Tool result feedback loop
- **File**: `core/layers/base.py` → `_call_llm()` tool call loop
- **Issue**: Tool results (e.g., "已记录: 删除 card_xxx") are terse; LLM may benefit from richer confirmation
- **Idea**: Include stats in tool responses (e.g., "已记录删除 card_xxx。当前 L2 待整理: 22 deprecate + 1 create")

## 3. DeepSeek strict mode + prompt optimization
- **File**: `core/layers/base.py`, `core/layers/l*/manager.py`
- **Issue**: Tool definitions lack `strict: true`; consolidation prompts don't guide tool usage strategy
- **Idea**: Enable strict mode (requires `/beta` endpoint + `additionalProperties: false` on all params + all properties in required). Add few-shot tool call examples to system prompts.

## 4. Full ToolRegistry mounting
- **File**: `core/layers/base.py`, `core/tools/registry.py`, `capability/`
- **Issue**: Only consolidation tools (6 functions) are mounted; registered tools (web_search, terminal, etc.) never injected
- **Idea**: Wire `ToolRegistry.get_tools_for_domain()` into all layer `_call_llm()` calls, filtered by current task domain. Decide whether to use existing `LayerInjector`/`CapabilityRegistry` or a simpler approach.

## 5. Entry format clarification (design first, no code)
- **File**: `core/env/learning_env.py` -> `build_consolidation_task()` L2/L3 entry format sections
- **Issue**: ``**Entry format:**`` lists spec fields as plain markdown bullet points; LLM may not understand which fields it should populate vs which are system-generated
- **Idea**: Clearly label each field as [system-generated] vs [agent-populated]. Replace bullet list with a table showing field name, who fills it, and whether required. Design the format layout before touching prompts.
