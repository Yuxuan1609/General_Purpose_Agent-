# MAINTAIN.md / COOKBOOK.md / README vs 实际代码 — 断点审计

> 审计日期: 2026-06-16
> 基准: 当前 main 分支实际代码

---

## A. 函数签名不匹配

文档记载与代码实际不一致的签名：

| # | 模块 | 文档记载 | 代码实际 | 类型 |
|---|------|----------|----------|------|
| 1 | `ToolRegistry.dispatch` | `(name, args, context)` | `(name, args, context=None, timeout=None)` | 缺 `timeout` 参数 |
| 2 | `L0_5_1Manager.__init__` | `…max_rounds, knowledge_stores)` | `…auxiliary_llm=None, downstream=None, upward=None, downward=None, domain_registry=None, max_rounds=3, knowledge_stores=None)` | 参数顺序不同+缺默认值 |
| 3 | `L2Manager.__init__` | `(knowledge, downstream, upward, downward, auxiliary_llm)` | `…auxiliary_llm=None, domain_registry=None, max_rounds=3)` | 缺 `domain_registry`, `max_rounds` |
| 4 | `L2Agent.__init__` | `(llm_client, knowledge)` | `(llm_client, knowledge, domain_nodes=None, domain_registry=None)` | 缺 `domain_nodes`, `domain_registry` |
| 5 | `L3Manager.__init__` | `(skill_layer, downstream, upward, downward, auxiliary_llm)` | `…auxiliary_llm=None, domain_registry=None, max_rounds=3)` | 缺 `domain_registry`, `max_rounds` |
| 6 | `L1Agent.__init__` | `(llm_client, philosophy)` | `(llm_client, philosophy, domain_registry=None, knowledge_stores=None)` | 缺 `domain_registry`, `knowledge_stores` |
| 7 | `L1Agent._build_system_prompt` | `(instruction, meta)` | `(instruction, meta, static_context="")` | 缺 `static_context` |
| 8 | `FlexibleKnowledge.modify_card` | `(card_id, new_content, usefulness, misleading, comment)` | `(card_id, new_content=None, usefulness=None, misleading=None, comment=None)` | 全部 keyword-optional |
| 9 | `SkillLayer.create_skill` | `(name, content, domain, ...)` | `(name, content, domain, cross_domain=False, created_by="agent", available_domains=None)` | 缺 3 参数 |
| 10 | `SkillLayer.edit_skill` | `(name, new_content, usefulness, misleading, comment)` | `(name, new_content=None, usefulness=None, misleading=None, comment=None)` | 全 keyword-optional |
| 11 | `LLMClient.chat` | `(messages, tools=None, json_mode=False)` | `(messages, tools=None, json_mode=False, **kwargs)` | 缺 `**kwargs` |
| 12 | `ToolCapability.invoke` | `(layer, args{name, args})` | `(layer, args, timeout=None)` | 缺 `timeout` |
| 13 | `LearningEnv.__init__` | `(pending_dir, knowledge_stores, preprocessing_llm, stats_file, ..., domain_registry=None)` | △ 缺 `l2_card_limit=30`, `l3_skill_limit=20`, `dry_run=False`, `consolidation_spec=None` | 缺 4 参数 |
| 14 | `InteractionEnv.__init__` | `(system_prompt, debug, enable_learning)` | `(system_prompt, debug=False, enable_learning=True)` | 缺默认值 |
| 15 | `Executor.__init__` | `(layer_root, llm_client, learning_dir, max_tokens, temperature)` | △ 默认值 `learning_dir=None, max_tokens=512, temperature=0.1` | 缺默认值 |
| 16 | `build_chain` | 全 positional-required | △ `auxiliary_llm=None, domain_registry=None, knowledge_stores=None` | 3 参数有默认值 |
| 17 | `set_learning_context` | `(executor, knowledge_stores)` | `(executor=None, knowledge_stores=None)` | 缺默认值 |
| 18 | `register_record_learning` | `(registry, pending_dir)` | `(registry, pending_dir="data/learning/pending")` | 缺默认值 |
| 19 | `DomainRegistry.__init__` | `(nodes, embedding_model_path=None, db_path=None)` | `(nodes=None, embedding_model_path=None, db_path=None)` | `nodes` 有默认值 |

---

## B. 死引用（文档记载但代码不存在）

| # | 条目 | 详情 |
|---|------|------|
| 1 | `DomainRetrieveResult` | MAINTAIN.md 列为 dataclass，代码中已不存在 |
| 2 | `DomainRegistry.retrieve_from_root()` | 方法不存在 |
| 3 | `Executor._write_pending()` | 方法已注释/废弃为 `# deprecated`，文档仍记录 |
| 4 | `_make_content_getter()` | `core/layers/__init__.py` 中不存在 |
| 5 | `_seed_l3_skills()` | `scripts/run_leduc_cognitive.py` 中不存在 |
| 6 | `L1ProposalProxy` | MAINTAIN.md 列在 `meta_driver.py` 下，实际不存在（有 `L1Proposal` 在 `philosophy.py`） |
| 7 | `DictInjector` | 标记为 legacy/dead code 但仍占文档篇幅 |
| 8 | `ToolCall` dataclass | MAINTAIN.md Phase 3 段记录 `ToolCall(id, function:FunctionCall)`，实际 `ToolCall` 不存在于代码 |
| 9 | `core/agent.py` | COOKBOOK.md 引用，文件不存在 |
| 10 | `core/agent_loop.py` | COOKBOOK.md 引用，文件不存在 |
| 11 | `core/layer_context.py` | COOKBOOK.md 引用，文件不存在 |
| 12 | `core/config.py` | COOKBOOK.md 引用，文件不存在 |
| 13 | `main.py` | README + COOKBOOK 引用，文件不存在 |

---

## C. dataclass 字段不匹配

| # | 类 | 文档记载 | 代码实际 | 类型 |
|---|---|---------|----------|------|
| 1 | `LearningUnit` | 7 字段: `description, domain, context, needs_decomposition, subtasks, enable_learning, token_count` | 仅 `description, domain` | **5 个幻影字段** |
| 2 | `DomainNode` | 5 字段: `path, parent, description, correlations, relations` | 6 字段，缺 `embedding_vector` | 主表缺字段（V2 段有） |
| 3 | `CapabilityResult` | 6 字段 | 7 字段，缺 `fallback` | 缺字段 |
| 4 | `Rule` | 未文档化 | `id, content, created_by, source, added_at, version, last_modified, usefulness, misleading, comment` | 整个 dataclass 缺失文档 |
| 5 | `L1Proposal` | 记为 `L1ProposalProxy`（在 `meta_driver.py` 下） | 实际名为 `L1Proposal`，位于 `philosophy.py`，字段 `content, reason, rule_id, domain` | 错名+错文件 |
| 6 | `KnowledgeCard` | 未详细列出字段 | 11 字段: `id, content, domain, available_domains, sub_tags, last_used, source, created_at, updated_at, usefulness, misleading, comment` | 完整字段缺失 |
| 7 | `SkillMeta` | 主表仅列 `touch_skill` 方法 | 15 字段完整 dataclass 未记录 | 不完整 |
| 8 | `TaskState` | 未文档化 | `task_id, tool_name, status, created_at, result, error` | 缺失文档 |
| 9 | `LLMResponse` | 未文档化 | dataclass: `text, tool_calls` + `has_tool_calls` property | 缺失文档 |
| 10 | `FunctionCall` | 仅在 Phase 3 段提及 `ToolCall` (不存在) | 实际为 `FunctionCall(name, arguments)` | 名字错误 |

---

## D. 函数缺失文档（代码有但 MAINTAIN.md 没记）

| # | 文件 | 函数/类 |
|---|------|---------|
| 1 | `core/executor.py` | `write_game_result()` |
| 2 | `core/task.py` | `Domain.is_general`, `Domain.depth`, `Domain.is_descendant_of()` |
| 3 | `core/task_runner.py` | `TaskRunner.shutdown()`, `TaskState`, `get_shared_runner()` |
| 4 | `core/round_tree.py` | `DecisionNode.to_dict()`, `RoundHistory.all_as_dict()`, `RoundHistory.__len__()` |
| 5 | `core/layers/base.py` | `LayerAgent.set_context()` |
| 6 | `core/domain_registry.py` | `index_item()`, `unindex_item()`, `update_item_domains()`, `add_node()`, `update_correlation()`, `update_node()`, `__len__()` |
| 7 | `core/philosophy.py` | `Rule`, `L1Proposal`, `Philosophy.apply()`, `Philosophy.get_active_rules()` |
| 8 | `core/flexible_knowledge.py` | `KnowledgeGraph` class, `_sync_card_index`, `_unsync_card_index`, `update_from_tool_results`, `apply_updates`, `add_failed_proposal_record`, `run_decay_cycle`, `domain_stats` |
| 9 | `core/skill_layer.py` | `get_skills_by_ids()`, `patch_skill()`, `import_skill()` |
| 10 | `core/tools/kb_tools.py` | `register_kb_tools()`, `_kb_query_handler`, `_kb_delete_handler`, `_kb_fill_gap_handler` |
| 11 | `core/llm_client.py` | `LLMResponse` (dataclass), `FunctionCall` (dataclass), `has_tool_calls` property |
| 12 | `core/knowledge/knowledge_base.py` | `_ensure_domain()` |
| 13 | `scripts/douzero_agent.py` | `DouZeroLLMAgent._build_system_prompt()`, `_parse_action()`, `_parse_card_tokens()`, `_MockInfoSet`; `DouZeroCognitiveAgent.reset_session()`, `set_max_llm_steps()`, `llm_steps()`, `record_game_end()`, `_format_play_history()` |

---

## E. 上游/下游调用者引用错误

| # | 文档声称 | 实际情况 |
|---|---------|---------|
| 1 | `get_task_runner()` 是全局单例 | 实际 `get_task_runner()` 每次创建新实例，`get_shared_runner()` 才是单例 |
| 2 | `ToolRegistry.dispatch` 上游为 `ToolCapability` | 实际直接调用者是 `LayerInjector.execute_tool_call()` |
| 3 | `ToolRegistry.get_tools_for_domain` 上游为 `L2Manager, Executor` | `Executor` 不直接调用此方法 |
| 4 | `L1ProposalProxy` 在 `meta_driver.py` | 实际名为 `L1Proposal`，位于 `philosophy.py` |
| 5 | `Executor.execute` 返回 `{action_text, context, notify_layers}` | 实际返回 `{action_text, notify_layers}`，无 `context` key |

---

## F. COOKBOOK.md 整体过时

COOKBOOK.md 大量引用已删除的旧架构文件，需全面重写：

| # | COOKBOOK 引用 | 实际状态 |
|---|---------------|---------|
| 1 | `core/agent.py` → `CognitiveAgent.__init__()` | 文件不存在 |
| 2 | `core/layer_context.py` → `LayerContext(self.meta, self.l1, self.l2, self.l3)` | 文件不存在 |
| 3 | `core/agent_loop.py` → `AgentLoop.run()` | 文件不存在 |
| 4 | `main.py` → `_LLMWrapper`, `load_config()`, `_load_env()` | 文件不存在 |
| 5 | `core/config.py` → `AgentConfig` | 文件不存在 |
| 6 | `core/meta_driver.py` → `ReflectionTrigger`, `DEFAULT_TRIGGERS`, `run_reflection()` | 已在 Jun 12 changelog 中标注删除但 COOKBOOK 仍引用 |
| 7 | `data/layers/l1_rules.json`, `data/layers/knowledge/l2_index.json` | 需核实是否存在 |
| 8 | `KnowledgeCard.boost()`/`penalize()` | 已删除方法仍引用 |
| 9 | A4 段落引用 `core/agent_loop.py`, `core/layer_context.py` | 均不存在 |
| 10 | 测试列表 (`test_layer_context.py`, `test_agent_loop.py`, `test_agent.py`) | 需核实是否仍存在 |

---

## G. README.md 问题

| # | 问题 | 详情 |
|---|------|------|
| 1 | 工具表缺失 | `consolidation_tools`（10 个工具）和 `record_learning` 不在 README 工具表中 |
| 2 | 项目结构过时 | 列 `core/agent.py`, `core/config.py` 等不存在文件；缺 `core/agent_context.py`, `core/json_repair.py`, `core/tools/record_learning_tool.py`, `core/tools/consolidation_tools.py`, `core/env/interaction_env.py`, `core/metadata.py` |
| 3 | 测试数过时 | 写 "159 tests, 16 files" — 可能已变 |

---

## H. 汇总统计

| 类别 | 数量 |
|------|------|
| 签名不匹配 | 19 |
| 死引用 | 13 |
| dataclass 字段不匹配 | 10 |
| 缺失文档的函数 | 13 组 |
| 上游/下游引用错误 | 5 |
| COOKBOOK 过时引用 | 10 |
| README 问题 | 3 |