# Test Coverage Report — cognitive-agent

> 以代码为基准，记录全量测试覆盖状态与缺口。每次较大重构后更新。

**测试状态**（2026-06-20）: 289 collected, 287 passed, 2 skipped, 37 test files

---

## 一、pytest 套件 (`tests/`)

### 通过测试统计

```
287 passed, 2 skipped in ~35s
```

2 skipped 均为 `tests/test_e2e_chain.py::TestRealLLM::*` — 需要 real LLM API key，默认跳过。

### 模块-测试映射与缺口

| 源模块 | 测试文件 | 覆盖度 | 主要缺口 |
|--------|---------|--------|---------|
| `core/types.py` | `test_types.py` | **空文件** | 文件只有 2 行 import，无 test function。`ExecutionRecord` 从未被构造或验证 |
| `core/task.py` | `test_task.py` | ★★★★☆ | `Domain.parent` 边界（空 path、3 级+深层）、`Domain.level` 已标记 DEPRECATED 但未验证 |
| `core/layer_message.py` | `test_layer_message.py` | ★★★★☆ | `APPROVAL/REJECTION` 类型未构造、序列化/反序列化未测试 |
| `core/llm_client.py` | `test_llm_client.py` | ★★★☆☆ | `json_mode` 路径、`thinking_enabled/thinking_effort`、API error 处理、`**kwargs` 合并 均未测（E2E 脚本补充了 thinking extra_body） |
| `core/executor.py` | `test_executor.py` + `test_integration_cognitive.py` | ★★☆☆☆ | **重大**: `_call_llm()` fallback 路径 100% 未触发；`_build_system_prompt`/`_build_user_prompt` 未测试；`write_game_result()` 完全未测试；`_assemble_context` 未直接测试 |
| `core/philosophy.py` | `test_philosophy.py` + `test_philosophy_validation.py` | ★★★☆☆ | `l1_rules()` 未测试；L0.5 不可变守卫未测试；`_check_no_contradiction` 未测试；SQLite/DB 加载路径未测试；`L1Proposal` 带 `rule_id` 路径未测试 |
| `core/flexible_knowledge.py` | `test_flexible_knowledge.py` | ★★★☆☆ | `get_domain_cards()` 未直接测试；`modify_card()` 完全未测试；SQLite load 路径未测试 |
| `core/skill_layer.py` | `test_skill_layer.py` | ★★★☆☆ | `edit_skill()` 未测试；`touch_skill()` 未测试；name 校验错误路径未测试；SQLite load 路径未测试 |
| `core/layers/base.py` | `test_layers.py` + `test_layer_chain.py` + `test_e2e_chain.py` | ★★☆☆☆ | **重大**: `_call_llm()` 多轮 tool loop 从未单元测试；`ConsolidationStrategy.build_tools()` 未直接测试；`_drain_pending_async()` 未测试；`_schema_to_tool()` 未直接测试；`UpwardComm`/`DownwardComm` 零单元测试 |
| `core/layers/l0_5_1/manager.py` | `test_layers.py` + `test_e2e_chain.py` | ★★☆☆☆ | `L0_5_1Manager.query()` 无单元测试；`L1Agent.decide()` 无单元测试 |
| `core/layers/l2/manager.py` | `test_layers.py` + `test_e2e_chain.py` | ★★☆☆☆ | `L2Manager.query()` 无单元测试；`L2Agent.decide()` 无单元测试；`_propagate` 已删除但未回归验证 |
| `core/layers/l3/manager.py` | `test_layers.py` + `test_e2e_chain.py` | ★★☆☆☆ | `L3Manager.process()` 未测试；`L3Agent.decide()` 无单元测试；match fallback 路径未覆盖 |
| `core/layers/comm.py` | 无 | **★☆☆☆☆** | `UpwardComm.receive/wrap_response/wrap_notify`、`DownwardComm.receive/wrap_query` 完全无测试 |
| `core/domain_registry.py` | `test_domain_registry.py` + `test_domain_registry_index.py` + `test_domain_dirty.py` | ★★★☆☆ | `compute_embedding()`、`compute_correlation()`、`compute_all_correlations()`、`refresh_embeddings_for()`、`merge_domain()`、`deprecate_domain()`、`unindex_item_all()` 未测试；SQLite persistence 路径未覆盖（E2E 脚本部分补充了 domain 管线） |
| `core/task_runner.py` | `test_task_runner_concurrent.py` | ★★☆☆☆ | **重大**: `run_sync_batch()` 并行执行未测；`wait_all()` 未测；`pending_tasks()`/`stats()`/`status()`/`shutdown()` 未测；`submit()` 内部 `set_task_context` 线程传播未测；`collect(keep_history=False)` 旧路径未测；`list_tasks(filter_by_status)` 未测（E2E 脚本补充了 sync_batch + stats + async fire+collect） |
| `core/env/*` | `test_env.py` + `test_learning_env.py` + `test_threshold_scorer.py` + `test_interaction_env.py` | ★★★☆☆ | `tool_policy` 属性未测试；`LearningEnv.needs_consolidation()`/`get_consolidation_level()`/`archive_pending()`/`process_in_memory()` 未测试；`_build_learning_units_llm` 未测试；`domain_health_report()` 未测试（E2E 脚本补充了 process_in_memory） |
| `core/round_tree.py` | `test_round_tree.py` | ★★☆☆☆ | **重大**: `RoundHistory` 类（`push`/`snapshot`/`all_as_dict`/`__len__`）仅 thread-local stack 被覆盖；`get_round_history()` 未测试（E2E 脚本补充了 RoundHistory push+snapshot） |
| `core/session.py` | `test_session.py` + `test_dispatch_tracking.py` | ★★★★☆ | `close_session()` 未单独测试；`close()` 未验证；`get_session_store()` singleton+锁未验证；`register_task` 的 `tool_name`/`trace_id` 参数未测试 |
| `core/monitor.py` | `test_monitor.py` | ★★☆☆☆ | `_capacity_snapshot`/`_learning_snapshot`/`_session_summary` 全被 mock 替代；`log_tail OSError` 分支未测试 |
| `core/setup.py` | `test_setup.py` | ★★★☆☆ | 错误/failure 路径未测试；`learning_dir` 构造未验证 |
| `core/runtime_registry.py` | `test_runtime_and_injection.py` | ★★★☆☆ | `get_chain()` 未测试 |
| `core/config_loader.py` | 无独立测试 | ★★☆☆☆ | 无独立测试文件；各模块构造函数中通过 `get_section` 间接覆盖 |
| `core/llm_factory.py` | 无独立测试 | ★★☆☆☆ | 无独立测试文件；通过 `test_setup.py` / E2E 脚本间接覆盖 |
| `core/chain_factory.py` | `test_e2e_chain.py` | ★★★☆☆ | `build_chain` 的 Comm 正确性未验证；`_iter_layers` 正确性未单独测试 |
| `core/seed_knowledge.py` | 无独立测试 | ★★☆☆☆ | 无独立测试；通过 E2E 脚本间接覆盖 |
| `core/json_repair.py` | 无独立测试 | ★★☆☆☆ | 无独立测试；通过 `_call_llm` 间接覆盖 |
| `core/agent_context.py` | 无独立测试 | ★★☆☆☆ | `from_policy`/`resolve` 未直接测试；通过 `_get_tools` 间接覆盖 |
| `core/model_manager.py` | 无独立测试 | ★☆☆☆☆ | 零覆盖率 |
| `core/env_loader.py` | 无独立测试 | ★★☆☆☆ | 零直接测试；通过 `test_setup` + E2E 间接覆盖 |
| `capability/*` | `test_capability.py` + `test_tool_fallback.py` | ★★★☆☆ | `CapabilityRegistry.get_schemas_for_layer/invoke/list_for_layer`/register 重复 未测试；`LayerInjector.inject_to_agent/format_results_for_prompt/_summarize_data` 未测试；knowledge capability 路径未测试 |
| `core/tools/registry.py` | `test_tool_registry.py` | ★★★★☆ | `dispatch` 异常/context/timeout 参数未测试；`get_definitions(requested=...)` 未测试 |
| `core/tools/consolidation_tools.py` | `test_e2e_chain.py`（1 个 handler） | ★★☆☆☆ | 仅 `deprecate_l1_rule` handler 被测试；L2/L3 CRUD handler、`query_domain`、`create_domain`、`merge_domain` 均未单元测试 |
| `core/tools/downward_comm_tool.py` | `test_downward_comm_tool.py` | ★★★☆☆ | `_extract_reply()` 未直接测试；空 queries / `selected_nodes` schema / `domains_hint` 参数未测试 |
| `core/tools/record_learning_tool.py` | `test_dispatch_tracking.py` | ★★☆☆☆ | `sync` 路径未测；`_build_and_save` 未直接测（同步路径）；`_fill_observations_llm` 未测；`_check_auto_trigger` 未测；`_dispatch_learning` 未测；`_clean_old_archives` 未测（E2E 脚本大幅补充） |
| `core/knowledge/knowledge_base.py` | `test_knowledge_base.py` + `test_knowledge_integration.py` + `test_knowledge_tools.py` | ★★★★☆ | SQLite `meta_db_path` 路径未测；`close()` 未测；`search` 评分未验证 |
| `core/storage/*` | `test_storage_threadsafe.py` | ★★☆☆☆ | 仅 `insert` 跨线程 + `count` 被验证；`update/delete/get/list_by_*` 全未单独测试 |
| `scripts/gradio_app.py` | 无 | **☆**☆☆☆☆ | 零测试覆盖率 |

### 冗余/低价值测试

| 文件 | 问题 |
|------|------|
| `tests/test_types.py` | 空文件 — 仅有 import，零 test function |
| `tests/test_l2_domains_hint.py` | 仅测试本地 toy 函数，非生产代码 |
| `tests/test_domain_registry_index.py` | 与 `test_domain_registry.py` 中已有测试高度重复 |

---

## 二、E2E / Smoke 脚本 (`scripts/`)

以下脚本属于手动执行，**不在 pytest 套件中**。

### 功能覆盖点

| 脚本 | 测试数 | 覆盖 | 需要 LLM |
|------|--------|------|----------|
| `test_e2e_full.py` | 12 | TaskRunner sync_batch、async fire+collect、mixed round、task lifecycle、KB sub-agent（SubAgentLoop/FillGapLoop）、learning task dry_run+e2e、record_learning handler+tree format、ask_user handler | 需要（2 个 KB test + learning e2e test） |
| `test_async_dispatch.py` | 4 | sync_batch parallel、sync_batch error handling、async submit+collect、stats | 否 |
| `test_auto_learning.py` | 9 | process_in_memory、consolidation context roundtrip、build_and_save threshold + trigger、dispatch_learning without executor、ask_user timeout、LLMClient thinking extra_body | 否 |
| `test_record_learning.py` | 2 | RoundTree push+snapshot、record_learning handler（⚠ 部分与 test_e2e_full.py 重复） | 否 |
| `test_learning_e2e.py` | 5 phases | Full pipeline: seed data→scan pending→execute chain→apply mods→verify embedding | 需要 |
| `test_learning_restructured.py` | 7 phases | LLM integration aggregation→TaskObservation→Executor→layer chain→per-layer modifications | 需要 |
| `test_domain_e2e_pipeline.py` | 5 | create_domain+embedding、correlation、split domain、merge_domain、save→load+flush | 需要 embedding 模型 |
| `test_domain_optimization_e2e.py` | 2 | merge_domain removes source、deprecate_domain blocks orphans | 否 |
| `test_consolidation_real.py` | — | 真实 LLM consolidation 全链路 | 需要 |
| `smoke_test_managers.py` | — | Manager 构建+通知冒烟 | 否 |
| `smoke_test_learning_env.py` | — | LearningEnv 基础冒烟 | 否 |
| `smoke_test_consolidation.py` | — | Consolidation context 冒烟 | 否 |
| `smoke_test_injector.py` | — | LayerInjector 冒烟 | 否 |
| `integration_test_capability.py` | — | Capability 集成 | 否 |
| `test_kb_io.py` | — | KB I/O 读写 | 否 |

### E2E 脚本 vs pytest 功能交叉

| 功能 | pytest 覆盖 | E2E 脚本补充 |
|------|------------|-------------|
| `TaskRunner.run_sync_batch` | ❌ | ✅ `test_e2e_full.py` + `test_async_dispatch.py` |
| `TaskRunner.stats` / `pending_tasks` / `status` | ❌ | ✅ `test_e2e_full.py` + `test_async_dispatch.py` |
| `TaskRunner.submit` → collect async 链路 | ✅ | ✅ 重复但更完备 |
| `record_learning._build_and_save` | ❌ | ✅ `test_e2e_full.py` + `test_record_learning.py` |
| `record_learning._check_auto_trigger` threshold | ❌ | ✅ `test_auto_learning.py` |
| `record_learning._dispatch_learning` | ❌ | ✅ `test_auto_learning.py`（部分） |
| `LearningEnv.process_in_memory` | ❌ | ✅ `test_auto_learning.py` |
| `DomainRegistry.compute_embedding/correlation` | ❌ | ✅ `test_domain_e2e_pipeline.py` |
| `DomainRegistry.merge_domain/deprecate_domain` | ❌ | ✅ `test_domain_optimization_e2e.py` |
| `RoundHistory.push/snapshot/all_as_dict` | ❌ | ✅ `test_record_learning.py` |
| `LLMClient.thinking_enabled/thinking_effort` | ❌ | ✅ `test_auto_learning.py` |
| KB SubAgentLoop/FillGapLoop | ❌ | ✅ `test_e2e_full.py` |
| Consolidation 全链路 (real LLM) | ❌ (skipped) | ✅ `test_consolidation_real.py` + `test_learning_e2e.py` |

---

## 三、E2E 场景缺口（多并发 + 异步 + 真实场景）

### 完全缺失的场景

| # | 场景 | 严重度 | 描述 |
|---|------|--------|------|
| 1 | **多 Session 并发** | 高 | 2+ 个 Gradio session 同时 chat，各自有独立 `SessionStore` + `set_task_context`，无测试验证隔离性 |
| 2 | **Gradio UI 集成** | 高 | `scripts/gradio_app.py` 全体无测试。chat handler、session 创建/切换/删除、task tracking、定时刷新 全未验证 |
| 3 | **并发 dispatch + context 线程安全** | 高 | 10+ 线程同时 `set_task_context` → `submit` → `_record_learning_handler` → `SessionStore.register_task`，无竞态测试 |
| 4 | **TaskRunner 高并发提交** | 高 | 100+ 任务同时 submit，验证 `_on_async_done` 回调无竞态、collect 全量收割、stats 统计准确 |
| 5 | **Sub-agent 级联** | 高 | Agent while-loop 内同一轮 touch `l1_query`→`L2.decide`→`l2_query`→`L3.decide`→`l3_report` 完整 3 层通信链路，无 E2E 覆盖 |
| 6 | **Capture tool 识别** | 中 | Agent 在工具循环中同时调用 1 个 capture tool + 2 个普通 tool → capture 立即退出、普通 tool 继续 — 无精确验证 |
| 7 | **sync_batch 超时** | 中 | `run_sync_batch(timeout=...)` 超时后的 error 返回 + remaining tasks 行为未验证 |
| 8 | **async dispatch → collect_tasks → Agent 消费** | 中 | 完整链路：Agent 发 async → 收到 task_id → 后续轮次 collect → 结果注入 LLM context → 产出最终答案 |
| 9 | **LearningEnv consolidation 自动触发** | 中 | `needs_consolidation()` → `build_consolidation_task()` → Executor → 各层修改 → `step()` → archive — 全链路无测试 |
| 10 | **SessionStore 崩溃恢复** | 中 | `mark_interrupted_on_startup` 在启动时标记旧 running task 为 interrupted，仅单元测，无 E2E 模拟进程崩溃 |
| 11 | **Progress 更新 + subscriber 通知** | 中 | TaskRunner `update_progress` → `_notify` → subscriber → SessionStore.update_task → Gradio UI 刷新 完整链路无测试 |
| 12 | **Gradio 定时刷新 task list** | 低 | `gr.Timer(3.0).tick` → `_refresh_task_list` → `SessionStore.list_tasks` 集成链路未测试 |
| 13 | **Env feedback 跨层传递** | 中 | `state.feedback` + `state.l1_feedback/l2_feedback/l3_feedback` → L1/L2/L3 各自 `_build_user_context` 读取 完整链路未验证 |
| 14 | **downward_comm 全链路** | 高 | `l1_query: {domains_hint, selected_nodes}` → L2 `_build_cards` → L3 `match` → NOTIFY 返回 完整参数透传链路无测试 |

### 已有但需增强的场景

| 场景 | 当前状态 | 缺失 |
|------|---------|------|
| sync_batch 并行 | E2E 脚本用 sleep 验证并行 | 未验证 runner 内部 `_record_stat` 统计、错误可区分、tool_name 准确性 |
| async submit → collect | E2E 脚本覆盖 happy path | 未验证: (a) error 任务 collect (b) collect 时任务仍 running 的行为 (c) `keep_history=False` 删除 |
| record_learning auto-trigger | `test_auto_learning.py` 用 mock executor | 未用 real executor + real chain 验证 learning→apply→step 完整链路 |
| domain pipeline | `test_domain_e2e_pipeline.py` 覆盖基础 | 未验证 `compute_all_correlations` O(n²) 批量计算、`refresh_embeddings_for` 增量刷新、SQLite persistence 路径 |

---

## 四、最优先需补充的测试（按影响排序）

| 优先级 | 目标 | 类型 | 原因 |
|--------|------|------|------|
| P0 | `Executor._call_llm` fallback 路径 | 单元 | L1 不产出 result 时 Executor 自行调 LLM — 当前零覆盖 |
| P0 | `LayerAgent._call_llm` 多轮 tool loop | 单元 | 最复杂的核心方法，capture/sync/async/downward 四条路径均无直接测试 |
| P0 | 3 个 Manager `query()` + 3 个 Agent `decide()` | 单元 | 所有业务逻辑入口，仅靠 e2e 间接覆盖 |
| P1 | `RoundHistory` 完整 API | 单元 | push/snapshot/all_as_dict 无 pytest 覆盖 |
| P1 | `LearningEnv` consolidation 触发链路 | 单元+E2E | needs_consolidation→build_task→execute→step 全未测 |
| P1 | Gradio app 基础集成 | E2E | `gradio_app.py` 零覆盖率 |
| P1 | 并发 dispatch + context 线程安全 | 压力 | 多线程 `set_task_context`→submit→register_task 竞态验证 |
| P2 | `DomainRegistry` embedding/correlation/merge/deprecate | 单元 | 6 个核心方法零 pytest 覆盖 |
| P2 | `CapabilityRegistry` 完整 API | 单元 | invoke/get_schemas/register 重复 全未测 |
| P2 | `record_learning` 全管线 | 单元+E2E | sync handler→build_and_save→check_auto_trigger→dispatch_learning |
| P3 | `ConsolidationStrategy.build_tools` | 单元 | consolidation 模式下工具构建逻辑 |
| P3 | `UpwardComm`/`DownwardComm` | 单元 | 确定性协议处理，当前零测试 |

---

## 五、测试覆盖统计

| 维度 | 数值 |
|------|------|
| pytest 测试总数 | 289 |
| pytest skip 数 | 2 (RealLLM) |
| 测试文件数 | 37 |
| 空/低价值测试文件 | 2 (`test_types.py`, `test_l2_domains_hint.py`) |
| E2E 脚本数 | 15（含 smoke/integration） |
| E2E 中需要 LLM 的脚本 | 5 |
| E2E 中不需要 LLM 的脚本 | 10 |
| **pytest 完全未覆盖的核心方法** | **60+** |
| **E2E 脚本补充了 pytest 缺口的场景** | **12** |
| **pytest + E2E 均未覆盖的场景** | **14** |
