# Architecture Maintain Doc — cognitive-agent

> 记录所有模块的函数级信息：函数作用、参数签名、上下游调用关系。
> 每次较大修改后即时更新。

---

## Changelog

| 日期 | 变更 |
|------|------|
| 2026-06-24 | **Layer Loop 缺陷修复（ISSUES.md #1-6,#8）**：`downward_comm_tool` 去掉 `threading.Thread+join(timeout)`，改纯同步执行（放弃 downward 超时），修复 thread-local RoundTree 栈被线程割裂致 L2/L3 节点丢失 (#1)；`_extract_reply` 签名 `str→dict{reply,reasoning}`，下层 reasoning 向上传递 (#4)；`L2Manager.query` pop 后 append l2_node 到 `current_node()`，对齐 L3 (#2)；`L3Agent.decide` normal mode 加 done 兜底（_raw/result 拼装），对齐 L1/L2 (#6)；`base.py _call_llm` capture 改延迟语义——同轮 executable 先执行再 return capture (#3)；统一 `async_dispatched` 计数器驱动 "Pending async/collect_tasks" 提醒，覆盖 downward 路径 (#5)；capture 命中 `_drain_pending_async` 只调一次 (#8)。#7 经确认保持原状（纯文本回复 reasoning 仍为空，LLMResponse 无独立 thinking 字段）。新增 `tests/test_call_llm_tool_loop.py`，扩展 `test_downward_comm_tool.py`/`test_layers.py`。 |
| 2026-06-24 | **TB 测试反馈机制**：新增 `tb/feedback_harness.py` — `FeedbackHarness(Harness)` 子类重写 `_run_trial`，将 `_parse_results` 移入 `with spin_up_terminal()` 块内，在容器存活期间插入修复循环（最多 3 轮修复）。`tb/agent/cognitive_agent.py` 新增 `receive_test_results()`/`_build_feedback_meta()` 方法 — 接收 pass/fail 结果驱动 Executor 反思/修复。新增 `tb/runner.py` — monkey-patch `terminal_bench.Harness = FeedbackHarness` 后调用 Typer CLI。新增 `tb/env.py` — `apply_learning_context(chain, enable)` 用 `AgentContext(denied_tools={...})` 实现 train/test 工具过滤（test 禁用 record_learning/kb_add/kb_fill_gap）。`tb/run.sh` 改用 `python -m tb.runner run` 入口；加 `_run()` 函数支持 `$2` phase 参数 → `TB_PHASE` 环境变量。`tb/config/tasks_data.yaml` 更新为 32 道 Debugging/SoftwareEng/SystemAdmin/Security 四类任务（20 train + 12 test）。 |
| 2026-06-23 | **Terminal-Bench 集成**：新增 `tb/` 模块 — TB 评估环境。`tb/agent/cognitive_agent.py`：`CognitiveAgent(BaseAgent)` 将 cognitive-agent 的 Executor+三层链封装为 TB Agent，`perform_task` 内多轮循环（TaskObservation → Executor → tool call via tmux → capture_pane 反馈 → 直到 done）。`tb/tools/`：`tb_terminal`/`tb_read_file`/`tb_grep` — 同名覆盖原工具（`override=True`），走 `TmuxSession.send_keys()` + `capture_pane()` 在 Docker 容器内执行。`tb/session_holder.py`：模块级 `_current` 引用供 TB 工具取 session。`tb/config/tasks_data.yaml`：Data & File Processing 8 道 task 列表（5 train + 3 test）。`tb/run.sh`：`tb run --agent-import-path` 入口脚本。`core/llm_client.py`：`LLMResponse` 新增 `prompt_tokens`/`completion_tokens` 字段；`LLMClient` 新增 `total_tokens` 属性 + `reset_token_counts()` 方法（累积计数 + 可重置）。`CognitiveAgent.perform_task` 增强：per-round 日志（tokens/耗时/action）、summary.json 摘要文件（含时间戳/轮次/token 统计）。 |
| 2026-06-22 | **次工具系统**：新增 `core/tools/secondary_tool.py` — `activate_secondary_tools` 工具（LLM subagent 筛选次工具池的 `semantic_description` → `ToolRegistry.enable_secondary()` 启用当前线程）。ToolEntry 新增 `tool_spec`（"primary"/"secondary"）+ `semantic_description` 字段；ToolRegistry 新增 thread-local `_enabled_secondary` + `enable_secondary`/`clear_secondary`/`_get_enabled_secondary` 方法；`get_definitions()` 按确定性逻辑过滤次工具（仅已启用返回）。删除死代码：`ToolEntry.available_domains` 字段、`register()` 中 DomainRegistry 索引块、`get_tools_for_domain()` 方法、`core/tools/domain_tool.py` 整个文件、`chain_factory.py` 中 `set_domain_registry` block。config/tools.yaml 新增 `activate_secondary_tools` 条目（allowlist [l1,l2,l3]）。 |
| 2026-06-20 | **测试覆盖评估**：新增 `TEST_COVERAGE.md` — 全量测试覆盖报告（pytest 289 tests + 15 E2E 脚本），记录模块-测试映射、覆盖缺口、多并发/异步/E2E 场景缺失。MAINTAIN.md 补：`LayerAgent.set_context`/`_drain_pending_async`、`TaskRunner.wait_all`/`shutdown`、修正 `_call_llm` 中 `MAX_TOOL_TURNS` 为 config 可配。README.md 补：`core/session|monitor|setup|runtime_registry.py` + `scripts/gradio_app.py`；更新测试数 (229→289)。
| 2026-06-20 | **Gradio App（Gradio v2 Task 7）**：新增 `scripts/gradio_app.py` — Gradio Web UI 入口，三栏布局（左：Session 列表持久化创建/切换/删除；中：当前 session 的任务列表+对话输入；右：选中 task 的 trace 详情 L1/L2/L3 决策树+子任务+层日志）。`SessionState` dataclass 持每浏览器会话 env/session_id/current_task_id/chat_history。`_setup_task_tracking` 订阅 TaskRunner 事件自动回写 SessionStore（sub-agent 完成无需轮询）。`chat()` 用 `set_task_context`/`clear_task_context`（try/finally）绑定 thread-local context 供 dispatch handler 关联子任务。`app.load(every=3)` 定时刷新任务列表。Gradio 4.x API（gr.Blocks/gr.State/gr.Dataframe）。无自动测试，仅 import + py_compile 验证。 |
| 2026-06-20 | **Monitor 模块（Gradio v2 Task 6）**：新增 `core/monitor.py`——纯查询聚合模块，供 Gradio 前端展示。5 个公开函数 `snapshot`/`task_list`/`task_detail`/`log_tail`/`decision_tree` + 4 个内部 helper `_task_list`/`_capacity_snapshot`/`_learning_snapshot`/`_session_summary`。数据源：SessionStore（session/task 元数据）、per-layer 日志文件（`logs/interaction/{ts}/*.log`）、RoundTree.snapshot()（决策树）、chain 内部（L2/L3 capacity）。不修改任何状态，函数内 lazy import 避免循环依赖。MAINTAIN.md 中原计划版 monitor 章节（`StepTrace`/`_task_snapshot`/`_log_snapshot`）替换为实际实现（`StepTrace` 归属 gradio_app，由 Task 7 处理）。 |
| 2026-06-20 | **SessionStore（Gradio v2 Task 4）**：新增 `core/session.py` — `SessionStore`（SQLite WAL 持久化 sessions + tasks 元数据）+ thread-local task context（`set_task_context`/`get_task_context`/`clear_task_context`）+ `get_session_store` 单例。sessions 表（id/name/created_at/status/log_dir/last_active_at），tasks 表（id/session_id/parent_task_id/type/tool_name/status/progress/trace_id/result_summary/created_at/updated_at，FK→sessions，idx_tasks_session/idx_tasks_parent 索引）。`mark_interrupted_on_startup` 崩溃恢复：status='running' 且 updated_at 超阈值的 task 标记为 'interrupted'。Gradio 前端用 sessions 管理用户工作区、用 tasks 关联顶层对话与子 agent dispatch。dispatch handler 通过 thread-local context 读取当前 session/task 无需参数透传。 |
| 2026-06-20 | **TaskRunner 增强（Gradio v2 Task 3）**：`TaskState` 新增 `progress`/`metadata`/`cancelled` 字段。`TaskRunner.submit` 加 `metadata` 参数（可含 session_id/parent_task_id 供前端关联）。`TaskRunner.collect` 加 `keep_history=True` 默认值——默认保留历史不删除（旧行为 auto-remove 改由 `keep_history=False` 触发）。新增 `update_progress`/`subscribe`/`unsubscribe`/`list_tasks`/`cancel`（协作式取消）+ `_notify` 事件分发。`status()` 加 `cancelled` 计数。`get_task_runner` 标记 DEPRECATED（dispatch 改用 `get_shared_runner`，仅留测试隔离实例）。 |
| 2026-06-20 | **dispatch 集成 SessionStore（Gradio v2 Task 5）**：`record_learning_tool.py` `_record_learning_handler`/`_check_auto_trigger` + `base.py` `_call_llm` async_calls 分支：submit 后读 `get_task_context()` → 传 `metadata` 到 `runner.submit()` → `SessionStore.register_task` 登记 sub-agent task（仅 session 上下文活跃时）。`try/except Exception: pass` 保护——SessionStore 故障不影响 dispatch。CLI 模式（无 context）跳过登记，向后兼容。sync_batch 分支 + `async_tools.py` 不改动。 |
| 2026-06-20 | **SQLite Store 线程安全（Gradio v2 Task 2）**：6 个 store（l1/l2/l3/domain/kb `+__init__.py _connect`）加 `check_same_thread=False` + `threading.Lock` 写锁。原 `sqlite3.connect()` 默认 `check_same_thread=True` 阻止跨线程访问共享连接——顶层 task 并行第一轮 consolidation 即崩。19 个写方法（insert/update/delete/touch/index_item 等）加 `with self._write_lock`，读方法不加锁（WAL 允许并发读）。 |
| 2026-06-20 | **dispatch 统一 shared runner（Gradio v2 Task 1）**：7 处 dispatch 调用点 `get_task_runner()` → `get_shared_runner()`（`record_learning_tool.py`×2、`async_tools.py`×2、`base.py`×3）。根因：`get_task_runner()` 每次新建临时 runner，提交的 task_id 返回 agent 后 runner 失去引用、结果写进孤立 dict 被 GC——"dispatch-and-forget 没有实际执行"的根因。`get_shared_runner()` 返回全局单例，task 可追踪可 collect。 |
| 2026-06-20 | **setup_executor 提取（Gradio v2 Task 0）**：新增 `core/setup.py` — `setup_executor(project_root=None) → (chain, executor)`，一次性构建 llm→chain→executor→register_runtime。CLI（`interactive_agent.py`）和 Gradio 共用，消除 copy-paste。`scripts/interactive_agent.py` `_setup_executor` 改为委托 `setup_executor`。 |
| 2026-06-19 | **Gradio Frontend Plan + MAINTAIN.md 修正**：新增 `core/setup.py`、`core/monitor.py`、`scripts/gradio_app.py` 三个模块文档。修正 6 处签名过时：`L0_5_1Manager`/`L2Manager`/`L3Manager`/`build_chain` 删 `consol_ctx` 参数；`Rule` 删 usefulness/misleading/comment 字段；`LearningEnv.step` 描述更新为轻量。新增 `core/chain_factory.py` — `build_default_chain`/`_mount_tools`/`_iter_layers`。新增 `scripts/interactive_agent.py` — `main`/`_setup_executor`/`_show_notifies`。删 `TaskRunner.stats` 重复条目，`get_task_runner` 替换为 `get_shared_runner`。删 `core/llm_factory.py` 重复章节。 |
| 2026-06-18 | **#12 A段 拆 ConsolidationContext**：`ConsolidationContext` 废弃，拆为 `consolidation_injection`（store DI）+ `runtime_registry`（chain/executor 全局注册）。9 CRUD handler 改为直接改 store（不再 record_mod → drain_mods side-channel）。`pending_mods`/`drain_mods`/三层 Manager `_consol_ctx`/learning env `_apply_*`/`_parse_*`/`_quality_kwargs` 全删。`learning env step` 退化为轻量（只计轮次）。DomainRegistry 加 `mark_domain_dirty`/`flush_correlations`（增量，L1 Manager.query 在 decide 返回后调）。8 脚本 `chain._consol_ctx.executor = executor` 改 `register_runtime(chain, executor)`。L1 `Rule` 删 usefulness/misleading/comment 字段 + `L1SQLiteStore` 删对应列 + `modify_l1_rule` schema 删 quality。auto-learning 改调 `get_executor()`。`build_chain`/`build_default_chain`/`register_all_tools` 删 consol_ctx 参数。 |
| 2026-06-22 | **downward comm 超时 + tool turn 提升**：`downward_comm_tool` handler 改用 `threading.Thread + join(timeout)` 执行 `downstream.query()`，超时返回 error JSON。`l1_query`/`l2_query` config timeout 120→2000。`max_tool_turns` 5→10。 |
| 2026-06-22 | **kb_modify + L1 id/bug修复**：新增 `kb_modify` 工具（更新标题/内容/domain），注册到 ToolRegistry + tools.yaml allowlist。L1 `remove_rule` 不存在时改为 `ValueError`（原静默成功）。L0.5.1 prompt 显示 `r.id`（原只有 content），Agent 可以正确传递 rule_id 给 deprecate/modify 工具。 |
| 2026-06-18 | **#20 B段 decide-once 统一模型**：三层 Manager 外层 while 全废，每层只调一次 `decide()`，多轮统一在 `_call_llm` tool loop（`MAX_TOOL_TURNS`）。`l1_query`/`l2_query` 从 capture_tool 降级为 ToolRegistry 普通工具（新建 `core/tools/downward_comm_tool.py`，handler 同步调 downstream.query + collect_notify 回灌 tool result）。`L3_CONTINUE_TOOL` 删除（l3_report 是唯一退出信号）。consolidation cascade 整段删除（record_learning 后由 Agent 自驱分发）。`ConsolidationStrategy.allowed_base_tools` L1/L2 加 downward 工具。RoundTree 改 thread-local node 栈绑定 decide 建节点（`round_tree.py` 新增 `current_node`/`push_node`/`pop_node`）。`config.yaml:runtime.max_rounds_l1/l2/l3` 删除。`build_chain` 删 max_rounds 参数。`L0_5_1Manager`/`L2Manager`/`L3Manager` __init__ 删 max_rounds。 |
| 2026-06-18 | **#14 限制来源统一**：`LearningEnv.__init__` 默认 `_l2_limit`/`_l3_limit` 改从 `config.yaml:consolidation.l*.limits.soft` 读取（原读 `learning.l2_card_limit/l3_skill_limit`）。构造函数 override 参数 `l2_card_limit`/`l3_skill_limit` 保留优先级不变。删除 `config.yaml:learning.l2_card_limit`/`l3_skill_limit` 两个死 key（单一来源，避免一事两做）。触发语义对齐 spec：L2 触发 >25、level1=26-30、level2=31+；L3 触发 >15、level1=16-20、level2=21+。 |
| 2026-06-17 | **Config Overhaul**：统一 `config.yaml` 为唯一配置入口。新建 `core/config_loader.py`（`load_config`/`get_section`）。所有模块从 config 读默认值 + 构造函数可覆盖。删除 `config/layers/`（6 个 yaml）和 `config/consolidation_tools.yaml`。Consolidation spec 合并进 config.yaml。 |MAINTAIN.md 修复签名不匹配（A）、删死引用（B）、修正 dataclass 字段（C）、补缺失方法文档（D）、修正上下游引用错误（E）。README 工具表/项目结构/测试数更新。COOKBOOK 标注过时。 |`DomainRegistry.unindex_item_all()` 替代外部 `_reverse_index` 直接访问（`flexible_knowledge.py`、`consolidation_tools.py`、`threshold_scorer.py`）。删 `sub_tags` 字段链（无消费者）。删 `apply_updates` + `add_failed_proposal_record`（零调用者）。`_apply_l2`/`_apply_l3` domain 变更前校验路径存在于 DomainRegistry。 |
| 2026-06-17 | **MetaDriver 解散 + F39 索引同步**：`validate_l1_change` 迁入 `Philosophy.add_rule/modify_rule` 内置校验。`filter_dangerous`、`check_completion`、`L1ProposalProxy` 删除。`delete_skill` 加 `unindex_item` 调用。`_apply_l2`/`_apply_l3` domain 变更后调用 `DomainRegistry.update_item_domains()`。 |
| 2026-06-16 | **Consolidation→ToolRegistry 迁移**：将 L1/L2/L3 consolidation 工具从 DictInjector 硬编码迁移到 ToolRegistry。新增 `core/tools/consolidation_tools.py`（10 工具注册 + module-level pending_mods）。Manager notify() 改用 `consolidation_tools.get_pending_mods()`。`config/tools.yaml` 新增 consolidation allowlist。`DictInjector` 标记为 dead code。 |
| 2026-06-16 | **sync-as-Agent-param**：所有工具 schema 新增 `sync` 可选参数（Agent 可逐次覆盖默认值）。`_call_llm` 按 sync 拆分 sync_batch/async_calls 分别走 run_sync_batch 和 TaskRunner.submit。删除 `kb_query_async`/`kb_fill_gap_async` 独立变体。`kb_check_task`/`kb_collect_tasks` 重命名为通用 `check_task`/`collect_tasks`。`ask_user` 改为 tkinter 弹窗 + console fallback。 |
| 2026-06-15 | **KB SQLite Backend**：新增 `core/storage/kb_store.py`（KBSQLiteStore），KnowledgeBase 新增 `meta_db_path` 参数，激活后 metadata 写入 SQLite 而非 kb.json。向后兼容：不传 meta_db_path 时行为不变。 |
| 2026-06-13 | **Step 3 文档**：KB query-response 两阶段检索设计（Stage 1 txtai 粗筛 + Stage 2 Agent LLM 精排）、`knowledge_select` capture_tool、Agent while-loop 集成、推广到 L1/L2/L3 内部通信。见 `docs/superpowers/specs/2026-06-13-kb-query-response.md`。 |
| 2026-06-13 | **Step 2 文档**：KB 维护 task 规格（cleanup/fill_gaps/link_related/dedup），触发机制，质量指标，与 Step 3 query-response 关系。见 `docs/superpowers/specs/2026-06-13-kb-maintenance-tasks.md`。 |
| 2026-06-13 | **KB 存储合并**：`save()` 同时写入 txtai 持久化文件（config/embeddings/scoring/documents）和 `kb.json` 到同一路径；`load()` 优先从 txtai 磁盘加载，仅在缺失时重建索引。 |
| 2026-06-13 | **KnowledgeBase BM25**：`search()` 改用 txtai BM25 scoring 替代 `_keyword_score` 简单匹配。新增 `_rebuild_index()`（lazy reindex）、`_scoring`/`_id_to_idx`/`_needs_reindex` 字段。删除 `_keyword_score` 静态方法。 |
| 2026-06-12 | **Cleanup**：删除 `L2_DOMAIN_NODES` 硬编码节点列表（已由 DomainRegistry 替代）；删除 `STAGE1_SCHEMA`/`STAGE2_SCHEMA`/`L1_DECISION_SCHEMA`（已被 capture_tools 替代）；删除 `KnowledgeCard.boost`/`penalize` 条目（方法不存在）；清理各层 stage1/stage2 旧注释。 |
| 2026-06-12 | **Capture-Tool Strict Mode**：L1/L2/L3 decide() 改用 capture_tool 模式（l1_query/l1_report, l2_query/l2_report, l3_continue/l3_report），LLM 通过 tool_call 输出结构化结果替代 JSON-in-prompt。新增 `DictInjector`（轻量工具注入器）、`_schema_to_tool()`。`_call_llm` 新增 `capture_tools` 参数。 |
| 2026-06-11 | **Agent While-Loop Design**：各层删除硬编码 stage 流水线，统一为 `decide()` + Manager while 循环。L1Agent/L2Agent/L3Agent 新增 `decide()` 方法；L0_5_1Manager/L2Manager/L3Manager 的 `query()` 改为 while 循环，新增 `max_rounds` 配置。`LayerAgent` 新增 `decide()` 抽象方法。 |
| 2026-06-08 | **Domain System Redesign**：新增 `core/domain_registry.py`（DomainNode dataclass + DomainRegistry 类）。所有可检索实体统一 `available_domains: list[str]` 字段。Registry 提供反向索引 + 双路召回（primary/explore）。L1/L2/L3 managers 接入 registry，废弃 `L2_DOMAIN_NODES` 硬编码。`Domain.level` 标记 deprecated。 |
| 2026-06-07 | **Phase 3 实现**：新增 `capability/` 模块（Capability ABC + ToolCapability + KnowledgeCapability + LayerInjector）。`LayerAgent._call_llm()` 支持多轮 tool call 循环（role:"tool" 消息）。`LLMClient.chat()` 支持 tools 参数 + ToolCall.id。`LearningEnv` 新增 needs_consolidation/get_consolidation_level + consolidation.yaml spec。 |
| 2026-06-05 | **Phase 2.3 清理**：删除所有旧 Reflection 系统 + `MetaDriver` 旧触发器。迁移 `ThresholdScorer`。 |

---

## core/tools/registry.py

| 函数/类 | 签名 | 作用 | 上游调用者 | 下游调用 |
|----------|------|------|-----------|---------|
| `ToolEntry` | `@dataclass(name, schema, handler, tool_spec, semantic_description, sync, force_sync, check_fn, toolset)` | 工具条目数据类，含主/次标记及次工具语义描述 | ToolRegistry | — |
| `ToolRegistry` | `__init__(domain_registry=None)` → singleton | 线程安全工具注册中心，支持主/次工具区分 + thread-local 次工具启用 | setup scripts, LayerAgent | — |
| `ToolRegistry.register` | `(name, schema, handler, check_fn, toolset, override, sync, force_sync, tool_spec, semantic_description)` | 注册工具（主/次统一），次工具默认不可见 | setup scripts | — |
| `ToolRegistry.get_definitions` | `(requested=None) → list[dict]` | 获取可见工具的 OpenAI schema 列表；次工具仅在当前线程已启用时返回 | Executor, LayerInjector | — |
| `ToolRegistry.dispatch` | `(name, args, context=None, timeout=None) → str` | 按名分发工具调用 | ToolCapability | entry.handler() |
| `ToolRegistry.deregister` | `(name)` | 注销工具 | — | — |
| `ToolRegistry.enable_secondary` | `(names: list[str]) → int` | 将次工具加入当前线程的可用集，返回成功数 | activate_secondary_tools handler | — |
| `ToolRegistry.clear_secondary` | `() → None` | 清空当前线程的次工具可用集（Gradio session 切换时调用） | session teardown | — |
| `ToolRegistry.clear` | `()` | 重置所有条目（仅测试用） | test fixtures | — |

## core/tools/secondary_tool.py

| 函数/类 | 签名 | 作用 | 上游调用者 | 下游调用 |
|----------|------|------|-----------|---------|
| `register_secondary_tool` | `(registry)` | 注册 activate_secondary_tools 工具（tool_spec="primary"，所有层可见） | register_all_tools() | ToolRegistry.register() |
| `_activate_secondary_tools_handler` | `(args) → str` | 收集次工具 semantic_description → LLM subagent 筛选 → enable_secondary() → 返回启用列表 | ToolRegistry.dispatch | ToolRegistry.enable_secondary(), LLM.chat() |
| `_get_llm` | `() → LLMClient` | 获取 LLM 实例（优先用 test 注入，其次 executor 的 llm，最后 build_llm_client） | _activate_secondary_tools_handler | runtime_registry.get_executor / build_llm_client |
| `_set_llm_for_test` | `(llm) → None` | 测试用：注入 fake LLM 客户端 | test fixtures | — |

## core/tools/kb_tools.py

| 函数/类 | 签名 | 作用 | 上游调用者 | 下游调用 |
|----------|------|------|-----------|---------|
| `_ask_user_handler` | `(args) → str` | tkinter 弹窗向用户提问，fallback 到 console input | ToolRegistry.dispatch | tkinter.simpledialog |
| `_kb_query_handler` | `(args) → str` | 知识库语义检索，Stage1 txtai 粗筛 + Stage2 Agent LLM 精排 | ToolRegistry.dispatch | _get_kb(), LLM |
| `_kb_delete_handler` | `(args) → str` | 删除知识库文档，检查 doc_id 存在性 | ToolRegistry.dispatch | _get_kb(), kb.delete(), kb.save() |
| `_kb_modify_handler` | `(args) → str` | 更新知识库文档 title/content/domain，检查 doc_id 存在性 | ToolRegistry.dispatch | _get_kb(), kb.update(), kb.save() |
| `_kb_fill_gap_handler` | `(args) → str` | 触发后台 FillGapLoop 填补知识库缺口 | ToolRegistry.dispatch | FillGapLoop.run(), _get_kb(), kb.save() |
| `_get_kb` | `() → KnowledgeBase` | 单例获取 KnowledgeBase，加 _kb_lock 保护并行 save() | kb handlers | KnowledgeBase() |
| `_get_llm` | `() → LLM` | 获取全局 LLM 实例 | _kb_fill_gap_handler, _kb_query_handler | model_manager |

## core/tools/async_tools.py

| 函数/类 | 签名 | 作用 | 上游调用者 | 下游调用 |
|----------|------|------|-----------|---------|
| `register_async_tools` | `(registry)` | 注册 check_task 和 collect_tasks 通用异步任务管理工具 | register_all_tools() | ToolRegistry.register() |
| `_check_task_handler` | `(args) → str` | 查询单个异步任务状态 | ToolRegistry.dispatch | TaskRunner.check() |
| `_collect_tasks_handler` | `(args) → str` | 批量收集已完成异步任务的结果 | ToolRegistry.dispatch | TaskRunner.collect(), TaskRunner.pending_tasks() |

## core/task_runner.py

| 函数/类 | 签名 | 作用 | 上游调用者 | 下游调用 |
|----------|------|------|-----------|---------|
| `TaskState` | `dataclass(task_id, tool_name, status, created_at, result, error, progress=0.0, metadata={}, cancelled=False)` | 任务状态：running/done/error/cancelled | TaskRunner, check/list_tasks 返回 | — |
| `TaskRunner` | `__init__(max_workers=8)` | Thread pool + task lifecycle + stats + progress + 事件订阅，singleton | _call_llm, tool handlers, Gradio frontend | threading.Lock, ThreadPoolExecutor |
| `TaskRunner.submit` | `(tool_name, fn, metadata=None) → str` | Submit async task, returns task_id；metadata 可含 session_id/parent_task_id 供前端关联 | async tool handlers | ThreadPoolExecutor.submit |
| `TaskRunner.update_progress` | `(task_id, progress) → None` | 更新运行中任务进度（0-100）并触发 _notify | Gradio frontend | _notify() |
| `TaskRunner.subscribe` | `(callback) → None` | 订阅任务状态变更事件 | Gradio frontend | — |
| `TaskRunner.unsubscribe` | `(callback) → None` | 取消订阅 | Gradio frontend | — |
| `TaskRunner.list_tasks` | `(status?, tool_name?, session_id?) → list[TaskState]` | 按状态/工具名/session_id(metadata)过滤任务 | Gradio frontend | — |
| `TaskRunner.cancel` | `(task_id) → bool` | 协作式取消：置 cancelled 标志，handler 自检退出 | Gradio frontend | _notify() |
| `TaskRunner.run_sync_batch` | `(calls, timeout=300) → list[dict]` | Parallel execution of sync tools in batch | _call_llm | — |
| `TaskRunner.collect` | `(task_ids, keep_history=True) → list[dict]` | 收集已完成任务结果；keep_history=True 默认保留历史不删除，False 则移除（旧行为） | collect_tasks handler, _drain_async | — |
| `TaskRunner.check` | `(task_id) → TaskState\|None` | Query single task status | check_task handler | — |
| `TaskRunner.pending_tasks` | `() → list[str]` | List running task IDs | collect_tasks handler, _drain_async | — |
| `TaskRunner.stats` | `() → dict` | Running statistics (count/success/error/duration) | — | — |
| `TaskRunner.status` | `() → dict` | running/done/error/cancelled 计数 + by_tool 统计 | snapshot | — |
| `TaskRunner.wait_all` | `(timeout=None) → None` | 阻塞等待所有 running 任务完成，超时抛 TimeoutError | test fixtures, E2E 脚本 | — |
| `TaskRunner.shutdown` | `(wait=True) → None` | 关闭线程池 | 进程退出前 | ThreadPoolExecutor.shutdown() |
| `get_shared_runner` | `() → TaskRunner` | 全局单例（复用同一 runner） | _call_llm, tool handlers, Gradio frontend | — |
| `get_task_runner` | `() → TaskRunner` | 每次新建；dispatch 已弃用改用 get_shared_runner，仅留测试隔离实例 | test fixtures | — |

## core/chain_factory.py

| 函数/类 | 签名 | 作用 | 上游调用者 | 下游调用 |
|----------|------|------|-----------|---------|
| `build_default_chain` | `(data_root=None, auxiliary_llm=None, seed=True, env=None) → chain` | 完整构建三层链：loader → build_chain → mount_tools → agent_context。seed=False 时跳过 seed_knowledge | 脚本入口 (interactive_agent, gradio_app, run_*) | build_chain(), _mount_tools(), seed_knowledge() |
| `_mount_tools` | `(chain, data_root: Path) → None` | 注册全部工具 + 设置 LayerInjector + 设置 downward_comm layer 映射 | build_default_chain | register_all_tools(), LayerInjector, set_layer_downstreams() |
| `_iter_layers` | `(root) → generator` | 沿 _downstream 遍历链上所有 Manager | _mount_tools | — |

## core/llm_factory.py

| 函数/类 | 签名 | 作用 | 上游调用者 | 下游调用 |
|----------|------|------|-----------|---------|
| `build_llm_client` | `(config_path=None, model=None, temperature=0.1) → LLMClient` | 从 config.yaml + .env 构建 LLMClient。支持 thinking/thinking_effort 配置 | 脚本入口, record_learning_tool._fill_observations_llm | env_loader.load_env, LLMClient() |

## core/setup.py

| 函数/类 | 签名 | 作用 | 上游调用者 | 下游调用 |
|----------|------|------|-----------|---------|
| `setup_executor` | `(project_root: Path\|None = None) → (chain, executor)` | 共享 setup：load_env → build_llm_client → build_default_chain(seed=False) → Executor → register_runtime。返回 (chain, executor)。project_root 缺省为 setup.py 所在目录的 parent | scripts/interactive_agent._setup_executor, scripts/gradio_app | load_env, build_llm_client, build_default_chain, Executor, register_runtime |

## core/config_loader.py

| 函数/类 | 签名 | 作用 | 上游调用者 | 下游调用 |
|----------|------|------|-----------|---------|
| `load_config` | `(path: Path\|str\|None = None) → dict` | 加载 config.yaml 返回完整 dict（None 时用默认路径） | 脚本入口 | — |
| `get_section` | `(*keys, default=None) → dict` | 按 keys 路径获取 config 子段（如 `get_section('learning')`）。第一次调用时加载全量 config 并缓存。 | 所有模块构造函数 | load_config() |

## core/round_tree.py

| 函数/类 | 签名 | 作用 | 上游调用者 | 下游调用 |
|----------|------|------|-----------|---------|
| `DecisionNode` | `@dataclass(layer, query, result, reasoning, children, timestamp)` | Single decision tree node | L0_5_1Manager, L2Manager | — |
| `RoundHistory` | `__init__(max_rounds=5)` | FIFO queue of decision trees (deque) | L0_5_1Manager.query() | — |
| `RoundHistory.push` | `(l1_node) → None` | Append L1 root node (with L2/L3 children) | L0_5_1Manager.query() | — |
| `RoundHistory.snapshot` | `(count?) → list[DecisionNode]` | Return recent N rounds | _build_and_save | — |
| `get_round_history` | `() → RoundHistory` | Global singleton | — | — |
| `current_node` | `() → DecisionNode\|None` | 返回 thread-local 栈顶节点（绑定 decide 建树用） | 三层 Manager.query, downward_comm handler | — |
| `push_node` | `(node: DecisionNode) → None` | 压入 thread-local 栈 | 三层 Manager.query | — |
| `pop_node` | `() → DecisionNode\|None` | 弹出 thread-local 栈顶 | 三层 Manager.query | — |

## core/tools/record_learning_tool.py

| 函数/类 | 签名 | 作用 | 上游调用者 | 下游调用 |
|----------|------|------|-----------|---------|
| `register_record_learning` | `(registry, pending_dir) → None` | Register record_learning tool (sync=false) | register_all_tools() | ToolRegistry.register |
| `_record_learning_handler` | `(args) → str` | Submit to TaskRunner, return task_id；有 thread-local context 时登记到 SessionStore | ToolRegistry.dispatch | TaskRunner.submit, _build_and_save, SessionStore.register_task (via get_task_context) |
| `_build_and_save` | `(domain, target, importance, reasoning) → dict` | Build stub → LLM fills observations → write pending JSON | _record_learning_handler | RoundTree.snapshot, _fill_observations_llm |
| `_fill_observations_llm` | `(record, tree_nodes, target) → None` | LLM sub-agent: scan tree, extract L2/L3 observations (json_mode) | _build_and_save | build_llm_client, LLM.chat |
| `_format_tree_for_llm` | `(nodes) → str` | Structure-aware tree formatting with numbering (1, 1.1, 1.1.1) | _fill_observations_llm | — |
| `_check_auto_trigger` | `(pending_path, domain) → None` | 检查 pending/{domain}/ 下 ≥5 个文件时触发 auto-learning；有 context 时登记到 SessionStore | _build_and_save | TaskRunner.submit, SessionStore.register_task (via get_task_context) |
| `_dispatch_learning` | `(domain, pending_path, json_files) → None` | 读取记录→archive→LearningEnv→Executor→layers→step→apply 的完整学习循环 | _check_auto_trigger (via TaskRunner) | get_learning_context, LearningEnv.process_in_memory, Executor.execute, LearningEnv.step |

## core/model_manager.py

| 函数/类 | 签名 | 作用 | 上游调用者 | 下游调用 |
|----------|------|------|-----------|---------|
| `set_model_path` | `(path) → None` | Set embeddinggemma path before first load | chain_factory | — |
| `get_model_path` | `() → str` | Return configured model path | knowledge_base, domain_registry | — |
| `get_embedding_model` | `() → Embeddings` | Lazy-load singleton Embeddings instance | compute_embedding, KnowledgeBase | vendor.txtai_core.embeddings.Embeddings |

## core/agent_context.py

| 函数/类 | 签名 | 作用 | 上游调用者 | 下游调用 |
|----------|------|------|-----------|---------|
| `AgentContext` | `@dataclass(allowed_tools, denied_tools)` | Per-environment tool filter。从 `Environment.tool_policy` 构造（`from_policy()`） | chain_factory, Environment | — |
| `AgentContext.from_policy` | `(policy: dict\|None) → AgentContext\|None` | 从 env tool_policy dict 构造；无策略返回 None | chain_factory | — |
| `AgentContext.resolve` | `(tools: list[dict]) → list[dict]` | 按 allow/deny 过滤预过滤的 tool schema 列表。优先级：allowed > denied > pass | LayerAgent._get_tools | — |

## core/tools/sysinfo_tool.py

| 函数/类 | 签名 | 作用 | 上游调用者 | 下游调用 |
|----------|------|------|-----------|---------|
| `register_sysinfo_tool` | `(registry) → None` | 注册 sysinfo 工具：os/hardware/env/network 四类系统信息。 | register_all_tools() | ToolRegistry.register() |

## core/tools/downward_comm_tool.py

| 函数/类 | 签名 | 作用 | 上游调用者 | 下游调用 |
|----------|------|------|-----------|---------|
| `set_layer_downstreams` | `(mapping: dict[str, Manager]) → None` | 设置 tool_name → downstream Manager 映射（模块级 global） | chain_factory._mount_tools | — |
| `register_downward_tools` | `(tool_registry) → None` | 注册 l1_query / l2_query 为普通 ToolRegistry 工具（sync=true） | register_all_tools() | ToolRegistry.register() |
| `_extract_reply` | `(notify: dict, layer_name: str) → dict{reply, reasoning}` | 从下层 notify payload 提取 reply 与 reasoning（原只取 reply，现 reasoning 一并向上传） | l1_query/l2_query handler | — |
| `l1_query` handler | `(args, **kwargs) → str` | 同步（主线程）调 L2 Manager.query + collect_notify，返回含 reply+reasoning 的 JSON。原用 threading.Thread+join(timeout) 实现 timeout，但 thread-local RoundTree 栈被割裂致决策树断裂，已移除线程改纯同步（放弃 downward 超时） | L1Agent tool loop（_call_llm） | downstream.query(), downstream.collect_notify() |
| `l2_query` handler | `(args, **kwargs) → str` | 同步（主线程）调 L3 Manager.query + collect_notify，返回含 reply+reasoning 的 JSON。同上，已移除线程改纯同步 | L2Agent tool loop（_call_llm） | downstream.query(), downstream.collect_notify() |

## core/tools/consolidation_tools.py

| 函数/类 | 签名 | 作用 | 上游调用者 | 下游调用 |
|----------|------|------|-----------|---------|
| `register_consolidation_tools` | `(tool_registry, ctx=None) → None` | 注册全部 consolidation 工具（handler 直接改 store，不再 record_mod）。ctx 参数保留兼容，忽略。 | register_all_tools() | ToolRegistry.register() |
| `L1_CONSOLIDATION_TOOL_NAMES` | `set[str]` | L1 consolidation 可用工具名集合 | L1Agent.decide() | ToolRegistry.get_definitions() |
| `L2_CONSOLIDATION_TOOL_NAMES` | `set[str]` | L2 consolidation 可用工具名集合 | L2Agent.decide() | ToolRegistry.get_definitions() |
| `L3_CONSOLIDATION_TOOL_NAMES` | `set[str]` | L3 consolidation 可用工具名集合 | L3Agent.decide() | ToolRegistry.get_definitions() |

## core/tools/consolidation_injection.py

| 函数/类 | 签名 | 作用 | 上游调用者 | 下游调用 |
|----------|------|------|-----------|---------|
| `set_consolidation_stores` | `(stores: dict, registry=None) → None` | 设置 consolidation handler 可用的 store 引用（模块级 global） | chain_factory._mount_tools | — |
| `get_store` | `(layer: str) → store\|None` | 按层名获取 store（"l1"/"l2"/"l3"） | consolidation_tools handler | — |
| `get_registry` | `() → DomainRegistry\|None` | 获取 DomainRegistry | consolidation_tools handler | — |

## core/runtime_registry.py

| 函数/类 | 签名 | 作用 | 上游调用者 | 下游调用 |
|----------|------|------|-----------|---------|
| `register_runtime` | `(chain, executor) → None` | 全局注册 chain + executor（替代 ConsolidationContext.executor 手补） | 脚本入口 | — |
| `get_executor` | `() → Executor\|None` | 获取全局 Executor | _dispatch_learning | — |
| `get_chain` | `() → chain\|None` | 获取全局 chain | — | — |

## core/domain_registry.py (Task 3)

| 函数/类 | 签名 | 作用 | 上游调用者 | 下游调用 |
|----------|------|------|-----------|---------|
| `DomainNode` | `@dataclass(path, parent, description, correlations, relations, embedding_vector)` | 领域树节点 | DomainRegistry | — |
| `DomainRegistry` | `__init__(nodes, embedding_model_path=None, db_path=None)` | 领域注册中心，管理 domain tree + reverse index + embedding（可选 SQLite 后端） | build_chain, seed_knowledge | DomainSQLiteStore (if db_path) |
| `DomainRegistry._load_from_db` | `() → None` | 从 SQLite 加载 nodes + reverse_index 到内存 | __init__ | DomainSQLiteStore.list_nodes(), get_all_index() |
| `DomainRegistry.get_node` | `(path) → DomainNode\|None` | 按路径查找节点 | L2Agent, Executor | — |
| `DomainRegistry.list_all` | `() → list[DomainNode]` | 列出所有节点 | — | — |
| `DomainRegistry.children_of` | `(path) → list[DomainNode]` | 获取直接子节点 | — | — |
| `DomainRegistry.get_primary_items` | `(layer, domain) → list[str]` | 获取某 layer 下某 domain 的主项 ID 列表 | L2Manager, Executor | — |
| `DomainRegistry.get_explore_items` | `(layer, domain, threshold=0.5) → list[str]` | 按关联权重阈值获取相邻 domain 的项 ID | L2Manager, Executor | — |
| `DomainRegistry.get_items_for_domains` | `(layer, domains) → list[str]` | 批量获取多个 domain 的项 ID（去重） | L2Manager, Executor | — |
| `DomainRegistry.index_item` | `(layer, domain, item_id) → None` | 将 item 按 domain 注册到反向索引 | FlexibleKnowledge.add_card, SkillLayer.create_skill | DomainSQLiteStore.index_item() |
| `DomainRegistry.unindex_item` | `(layer, domain, item_id) → None` | 从反向索引移除单条 item | FlexibleKnowledge.remove_card, SkillLayer.delete_skill | DomainSQLiteStore.unindex_item() |
| `DomainRegistry.unindex_item_all` | `(layer, item_id) → None` | 从所有 domain 索引中移除 item | consolidation_tools, FlexibleKnowledge | DomainSQLiteStore.unindex_item() |
| `DomainRegistry.update_item_domains` | `(layer, item_id, domains) → None` | 更新 item 的 domain 归属（先清旧、后加新） | LearningEnv._apply_l2(), _apply_l3() | index_item(), unindex_item() |
| `DomainRegistry.add_node` | `(path, parent, description, correlations, relations) → DomainNode` | 添加新的 domain 树节点 | consolidation_tools, seed_knowledge | DomainSQLiteStore.insert_node() |
| `DomainRegistry.update_correlation` | `(a, b, weight) → None` | 更新两个 domain 间的关联权重 | consolidation_tools, compute_correlation | DomainSQLiteStore.update_node() |
| `DomainRegistry.update_node` | `(path, **fields) → DomainNode\|None` | 按字段更新 domain 节点 | consolidation_tools | DomainSQLiteStore.update_node() |
| `DomainRegistry.save` | `(filepath) → None` | 原子持久化 nodes + reverse_index 到 JSON（db_path 激活时为 no-op） | seed_knowledge | — |
| `DomainRegistry.load` | `(filepath) → DomainRegistry` | 从 JSON 加载注册中心 | build_chain | — |

## core/types.py (NEW in Phase 1)

| 函数/类 | 签名 | 作用 | 上游调用者 | 下游调用 |
|----------|------|------|-----------|---------|
| `TaskObservation` | `@dataclass(meta:str, state:dict, session:dict\|None)` | 环境观测的统一格式（单步）。meta 为自然语言游戏规则 | 通信层脚本 build_prompt() | Executor.execute(), LayerManager.query() |
| `ExecutionRecord` | `@dataclass(session, observation, notify_layers, action, result)` | Execute 后的存档记录，写入 data/learning/pending/ | Executor._write_pending() | LearningEnv |

## core/task.py

| 函数/类 | 签名 | 作用 | 上游调用者 | 下游调用 |
|----------|------|------|-----------|---------|
| `Domain` | `@dataclass(frozen=True, path:str, level:str)` | 层级领域标识，frozen 可用作 dict key | LearningUnit 定义 | L2 激活计算, L3 技能匹配 |
| `Domain.parent` | `property → Domain\|None` | 返回上一级领域 | L2._domain_match_score() | — |
| `Domain.is_ancestor_of` | `(other:Domain) → bool` | 判断是否祖先领域 | L2._domain_match_score() | — |
| `LearningUnit` | `@dataclass(description, domain)` | 最小学习单元，1个 Session 可拆为多个。区别于 TaskObservation（单步观测） | AgentRuntime | Executor.execute() |

## core/executor.py (NEW in Phase 1)

| 函数/类 | 签名 | 作用 | 上游调用者 | 下游调用 |
|----------|------|------|-----------|---------|
| `Executor` | `__init__(layer_root, llm_client, learning_dir, max_tokens, temperature)` | 独立决策者，只收不发 | AgentRuntime / 脚本 | LayerManager.query(), LLMClient.chat() |
| `Executor.execute` | `(obs:TaskObservation) → dict{action_text, notify_layers}` | 动作周期：LayerMessage(QUERY) 链 → collect_notify → prompt → LLM | DouZeroCognitiveAgent.act() | LayerManager.query(), collect_notify(), _call_llm() |
| `Executor._assemble_context` | `(obs) → dict{meta, state}` | 拼接 obs.meta + obs.state | execute() | _call_llm() |
| `Executor._call_llm` | `(context:dict) → str` | _build_system_prompt + _build_user_prompt → LLM | execute() | LLMClient.chat() |
| `Executor._build_system_prompt` | `(context) → str` | 组装 [任务说明]+[行为准则](state.l1_rules)+[相关知识](state.l2_cards)+[可用技能](state.l3_skills) | _call_llm() | — |
| `Executor._build_user_prompt` | `(context) → str` | 组装 [对局历史]+[当前局面] 从 state 提取 | _call_llm() | — |

## config/

| 文件 | 内容 | 使用者 |
|------|------|--------|
| `config.yaml` | 主配置入口（main_llm / auxiliary_llm / runtime / l1 / l2 / l3 / learning / consolidation） | `llm_factory.py`, `config_loader.py`, 各模块构造函数 |
| `config/tools.yaml` | 工具 per-layer allowlist + timeout/fallback | `ToolCapability._get_allowlist()` |

## core/layers/comm.py (Phase 1.5)

| 函数/类 | 签名 | 作用 | 上游调用者 | 下游调用 |
|----------|------|------|-----------|---------|
| `AgentPacket` | `@dataclass(frozen, source_layer, message_type, content)` | 层内 Agent 通信包，承载在 LayerMessage.payload 中运输 | L1Agent / L2Agent | Comm Agents 包装/解包 |
| `UpwardComm` | `receive(msg)→dict` / `wrap_response(...)→LayerMessage` / `wrap_notify(...)→LayerMessage` | 确定性协议处理：LayerMessage ↔ 业务 dict。基类直接实例化使用（无子类）。 | LayerManager.query() / build_chain() | — |
| `DownwardComm` | `receive(msg)→dict` / `wrap_query(...)→LayerMessage` | 确定性协议处理：LayerMessage ↔ 业务 dict。基类直接实例化使用（无子类）。 | LayerManager.query() / build_chain() | 下层 UpwardComm |

## core/layers/base.py (Phase 1)

| 函数/类 | 签名 | 作用 | 上游调用者 | 下游调用 |
|----------|------|------|-----------|---------|
| `LayerAgent` | `__init__(llm_client, log)` | ABC，所有层 LLM Agent 基类。含 `_injector` 属性。 | L1Agent, L2Agent | — |
| `LayerAgent._call_llm` | `(system, user, schema=None, tools=None, layer="", capture_tools=None) → dict` | 多轮 tool call 循环 + json_mode + robust_parse。parallel sync execution via run_sync_batch, async dispatch via TaskRunner。`capture_tools` 将指定 tool 的 arguments 直接作为结构化输出返回，替代 JSON-in-prompt。capture 现为延迟语义：同轮 executable 先执行（副作用+tool 结果入 messages）再 return capture；统一 `async_dispatched` 计数器驱动 "Pending async/collect_tasks" 提醒（覆盖 downward 路径）；capture 命中时 `_drain_pending_async` 只调一次。async 分支有 thread-local context 时登记到 SessionStore。 | L1/L2/L3 decide() | LLMClient.chat(), robust_parse(), injector.execute_tool_call(), TaskRunner.submit(), run_sync_batch(), SessionStore.register_task (async branch, via get_task_context) |
| `LayerAgent._schema_to_tool` | `(name, description, schema) → dict` | 将 JSON Schema 转为 OpenAI function-calling tool 定义（已少用，CaptureToolDef.to_openai_tool() 替代） | L1/L2/L3 decide() | — |
| `LayerAgent._get_tools` | `(layer) → list[dict]\|None` | 从 injector 获取该层可见工具 schema 列表。 | L1/L2/L3 decide() | injector.get_tools_for_layer() |
| `LayerAgent.set_injector` | `(injector) → None` | 注入 LayerInjector 以启用工具调用。 | chain_factory._mount_tools() | — |
| `LayerAgent.set_context` | `(ctx) → None` | 设置 AgentContext 用于 per-env 工具过滤（tool_policy） | chain_factory._mount_tools() | — |
| `LayerAgent._drain_pending_async` | `(grace_seconds=5.0) → None` | 等待 pending async 任务完成再退出 decide，防止后台任务 produce 孤儿输出 | decide()（_call_llm 返回前调用） | TaskRunner.pending_tasks(), TaskRunner.collect() |
| `LayerAgent.decide` | `(**kwargs) → dict` (abstract) | 单步决策，各层自行实现。Manager while 循环调用。 | Manager query() while 循环 | _call_llm(), CaptureToolDef.to_openai_tool() |
| `CaptureToolDef` | `@dataclass(name, description, done, schema)` | 声明式 capture tool 定义。`to_openai_tool()` 转为 OpenAI 格式。 | L1/L2/L3 decide() (模块常量) | — |
| `ConsolidationStrategy` | `__init__(consolidation_tool_names, allowed_base_tools, report_tool)` | 封装 consolidation 模式 tool 构建。`build_tools(agent, layer)` 返回 (all_tools, capture_set)。 | L1/L2/L3 decide() (模块常量) | ToolRegistry.get_definitions() |
| `_TOOL_RULES` | `str` (模块常量) | 工具调用规则提示文本，三层共享 | L1/L2/L3 _build_system_prompt() | — |
| `LayerManager` | `__init__(name, downstream, upward, downward)` | ABC，所有层 Manager 的基类。upward/downward 为 Comm Agent | build_chain() | 子类 |
| `LayerManager.process` | `(data:Any) → dict` (abstract) | 本层业务逻辑：富化 data 并返回状态 | query() | — |
| `LayerManager.notify` | `() → Any` (abstract) | 返回本层的 NOTIFY payload | collect_notify() | — |
| `LayerManager.query` | `(msg:LayerMessage\|Any, trace_id) → None` | QUERY 入口：通过 _unwrap_obs() 解包为 TaskObservation → process → propagate | Executor / 上层 | process(), downstream.query() |
| `LayerManager._unwrap_obs` | `(msg, upward=None, trace_id="") → (TaskObservation, trace_id)` | 静态辅助：LayerMessage 解包或直接 TaskObservation 透传，统一返回 TaskObservation | 各层 Manager.query() | — |
| `LayerManager.collect_notify` | `() → dict{layer_name: payload}` | 收集本层+所有下游的 NOTIFY | Executor.execute() | notify(), 下游.collect_notify() |

## core/layers/l3/manager.py (Phase 1 + Phase 2a)

| 函数/类 | 签名 | 作用 | 上游调用者 | 下游调用 |
|----------|------|------|-----------|---------|
| `L3Manager` | `__init__(skill_layer, downstream, upward, downward, auxiliary_llm, domain_registry=None)` | L3 层 Manager，包裹 SkillLayer + L3Agent。单次 decide() | build_chain() | — |
| `L3Manager.query` | `(msg, trace_id) → None` | 确定性匹配技能 → 单次 decide()（l3_report 唯一退出）→ RoundTree push + append 到父节点 | l2_query handler | SkillLayer.match(), L3Agent.decide(), push_node/pop_node |
| `L3Manager.process` | `(obs) → dict` | stub，实际逻辑在 query() | LayerManager.query() | — |
| `L3Manager.notify` | `() → dict` | 返回 `{skills_matched, skills_used, result, reasoning}` | collect_notify() | — |
| `L3Agent` | `__init__(llm_client, skill_layer=None, domain_registry=None)` | L3 LLM Agent：基于匹配技能执行认知任务 | L3Manager.query() | — |
| `L3Agent.decide` | `(meta, state, context, tools, layer) → dict{done, result, skills_used, reasoning}` | 单步决策：通过 capture_tool（l3_report 唯一退出）输出；`l3_output_format` 时从 ToolRegistry 获取 consolidation 工具 schema。normal mode 加 done 兜底（capture JSON 解析失败时用 _raw/result 拼装 done=True 返回，对齐 L1/L2）。L3_CONTINUE_TOOL 已删除，多轮靠 tool loop。 | L3Manager.query() | _call_llm(), _schema_to_tool(), ToolRegistry.get_definitions() |

## core/layers/l2/manager.py (Phase 1)

| 函数/类 | 签名 | 作用 | 上游调用者 | 下游调用 |
|----------|------|------|-----------|---------|
| `L2Manager` | `__init__(knowledge, downstream, upward, downward, auxiliary_llm, domain_registry=None)` | L2 层 Manager，包裹 FlexibleKnowledge + L2Agent。单次 decide()，l2_query 走 ToolRegistry 工具 | build_chain() | — |
| `L2Manager.query` | `(msg, trace_id) → None` | 单次 decide()（l2_query 在 tool loop 内同步调 L3）→ RoundTree push + append l2_node 到父节点（current_node） | L0_5_1 DownwardComm / l1_query handler | L2Agent.decide(), push_node/pop_node/current_node |
| `L2Manager.notify` | `() → dict` | 返回 `{reply, cards, reasoning}` | collect_notify() | — |
| `L2Manager._propagate` | `(obs, trace_id, l3_task="", selected_nodes=None) → None` | 包装 LayerMessage(QUERY) 发送到 L3 | query() | L3Manager.query() |
| `L2Agent` | `__init__(llm_client, knowledge, domain_nodes=None, domain_registry=None)` | L2 层 LLM Agent，while-loop 决策 | L2Manager | — |
| `L2Agent.decide` | `(query, meta, state, context, tools, layer) → dict{done, reply, selected_nodes, selected_cards, queries_to_L3, reasoning}` | 单步决策：通过 capture_tool（l2_query/l2_report）输出；`l2_output_format` 时从 ToolRegistry 获取 consolidation 工具 schema。 | L2Manager.query() | _get_cards_for_nodes(), _call_llm(), _schema_to_tool(), ToolRegistry.get_definitions() |
| `L2Agent._get_cards_for_nodes` | `(nodes) → list[KnowledgeCard]` | 按节点 domain 检索知识卡片 | decide() | FlexibleKnowledge.get_domain_cards() |

## core/layers/l0_5_1/manager.py (Phase 1)

| 函数/类 | 签名 | 作用 | 上游调用者 | 下游调用 |
|----------|------|------|-----------|---------|
| `L0_5_1Manager` | `__init__(philosophy, auxiliary_llm=None, downstream=None, upward=None, downward=None, domain_registry=None, knowledge_stores=None)` | L(0.5+1) 层 Manager，包裹 Philosophy + L1Agent。单次 decide()，l1_query 走 ToolRegistry 工具 | build_chain() | — |
| `L0_5_1Manager.query` | `(msg, trace_id) → None` | 单次 decide()（l1_query 在 tool loop 内同步调 L2）→ RoundTree push | Executor / 上层 | self._agent.decide(), push_node/pop_node, get_round_history().push() |
| `L0_5_1Manager.notify` | `() → dict` | 返回 `{done, result, reasoning}` 或 `{status:"ok"}` | collect_notify() | — |
| `L0_5_1Manager.process` | `(data) → dict` | 返回 `{status:"ok", layer:"l0_5_1"}` | LayerManager.query() | — |
| `L1Agent` | `__init__(llm_client, philosophy, domain_registry, knowledge_stores)` | L1 层 LLM Agent，while-loop 决策 | L0_5_1Manager | — |
| `L1Agent.decide` | `(meta, state, history, tools, layer) → dict{done, result, queries, reasoning}` | 单步决策：通过 capture_tool（l1_query/l1_report）输出；`l1_output_format` 时从 ToolRegistry 获取 consolidation 工具 schema。 | L0_5_1Manager.query() | _build_system_prompt(), _build_user_context(), _call_llm(), _schema_to_tool(), ToolRegistry.get_definitions() |
| `L1Agent._build_system_prompt` | `(instruction, meta, static_context="") → str` | 注入游戏规则 + 行为准则(L1 rules) + 任务目标 + 静态上下文 | decide() | Philosophy.all_rules() |
| `L1Agent._build_user_context` | `(state) → str` | 拼接 [当前局面] + [对局历史] + [修改结果确认]（读取 state.feedback / l1_feedback） | decide() | — |

## scripts/leduc_cognitive_agent.py (Phase 1)

| 函数/类 | 签名 | 作用 | 上游调用者 | 下游调用 |
|----------|------|------|-----------|---------|
| `LeducCognitiveAgent` | `__init__(executor, temperature)` | RLCard 接口的认知 Agent，通过 Executor 决策 | run_leduc_cognitive.py | Executor.execute() |
| `LeducCognitiveAgent.reset_session` | `(session_id) → None` | 重置 step 计数 + session_id | 脚本 per-episode | — |
| `LeducCognitiveAgent._decide` | `(state) → (action_id, {})` | RLCard state → TaskObservation(session) → Executor → parse | env.step() | Executor |

## scripts/run_leduc_cognitive.py (Phase 1)

| 函数/类 | 签名 | 作用 | 上游调用者 | 下游调用 |
|----------|------|------|-----------|---------|
| `_seed_knowledge` | `(fk, phil, sl) → None` | 注入 seed: L1 规则 + L2 卡片 + L3 技能(L2 Node 映射) | build_chain() | fk.add_card(), sl.create_skill() |
| `_setup_logging` | `() → log_dir` | 创建 per-agent 文件日志(l0_5_1.log, l2.log, l3.log, executor.log) | main() | logging |

## core/layers/__init__.py

| 函数/类 | 签名 | 作用 | 上游调用者 | 下游调用 |
|----------|------|------|-----------|---------|
| `build_chain` | `(philosophy, flexible_knowledge, skill_layer, auxiliary_llm, domain_registry, knowledge_stores) → L0_5_1Manager` | 自底向上构建三层链：L3 → L2 → L(0.5+1)，Comm 直接使用基类 UpwardComm/DownwardComm（无子类）。max_rounds、consol_ctx 参数已删 | AgentRuntime / 脚本 | L3Manager(), L2Manager(), L0_5_1Manager() |

## core/philosophy.py (已有，层内部使用)

| 函数/类 | 签名 | 作用 | 上游调用者 | 下游调用 |
|----------|------|------|-----------|---------|
| `Rule` | `@dataclass(id, content, created_by, source, added_at, version, last_modified)` | L1 规则数据类。usefulness/misleading/comment 已删 | Philosophy | — |
| `L1Proposal` | `@dataclass(content, reason="", rule_id=None, domain="general")` | 规则变更提案 | LearningEnv | Philosophy.apply() |
| `Philosophy` | `__init__(rules_path, max_rules, max_rule_length, db_path=None)` | L1 可演化行为规则管理（source="l0_5"不可变，"l1"可变）。内置自动校验。优先 SQLite 加载。 | L0_5_1Manager | L1SQLiteStore (if db_path) |
| `Philosophy.all_rules` | `() → list[Rule]` | 返回所有规则（L0.5 + L1） | L1Agent._build_system_prompt | — |
| `Philosophy.l1_rules` | `() → list[Rule]` | 仅返回 L1 可变规则 | Verifier, test | — |
| `Philosophy.add_rule` | `(content, created_by, source="l1") → Rule` | 添加新规则（自动校验 not_duplicate + no_contradiction + max_rules） | seed, L0_5_1Manager, LearningEnv | _validate_rule_change(), _save() |
| `Philosophy.modify_rule` | `(rule_id, new_content) → Rule` | 修改规则（拒绝L0.5，自动校验）| L0_5_1Manager, LearningEnv | _validate_rule_change(), _save() |
| `Philosophy.remove_rule` | `(rule_id) → None` | 删除规则（拒绝L0.5，不存在抛 ValueError）| L0_5_1Manager, consolidation_tools._do_deprecate | _save() |
| `Philosophy._validate_rule_change` | `(content, skip_rule_id) → None` | 校验规则变更：duplicate、contradiction、max_rules；不通过 raise ValueError | add_rule(), modify_rule() | _check_not_duplicate(), _check_no_contradiction() |
| `Philosophy.apply` | `(proposal: L1Proposal) → Rule` | 按 proposal 调用 add_rule 或 modify_rule | LearningEnv | add_rule(), modify_rule() |
| `_check_not_duplicate` | `(content, existing_rules) → tuple[bool, str]` | 检查新规则是否与已有规则重复 | _validate_rule_change | — |
| `_check_no_contradiction` | `(content, existing_rules) → tuple[bool, str]` | 检查新规则是否与已有规则矛盾 | _validate_rule_change | — |

## core/flexible_knowledge.py (已有，层内部使用)

| 函数/类 | 签名 | 作用 | 上游调用者 | 下游调用 |
|----------|------|------|-----------|---------|
| `FlexibleKnowledge` | `__init__(knowledge_dir, index_path, domain_registry=None, db_path=None)` | L2 知识卡片管理（SQLite 后端） | L2Manager | L2SQLiteStore (if db_path) |
| `FlexibleKnowledge.get_domain_cards` | `(domain) → list[KnowledgeCard]` | 返回指定 domain 下所有卡片 | L2Agent | — |
| `FlexibleKnowledge._load_cards_from_db` | `() → list[KnowledgeCard]` | 从 SQLite 加载全部卡片为内存对象 | __init__ | L2SQLiteStore.list_all() |
| `KnowledgeCard` | `@dataclass(id, content, domain, available_domains, last_used, source, created_at, updated_at, usefulness, misleading, comment)` | L2 知识卡片数据类 | FlexibleKnowledge | — |
| `FlexibleKnowledge.add_card` | `(content, domain, source, available_domains) → KnowledgeCard` | 新增卡片（内存 + SQLite + 索引） | seed, L2Manager | L2SQLiteStore.insert(), DomainRegistry.index_item() |
| `FlexibleKnowledge.remove_card` | `(card_id) → bool` | 删除卡片（内存 + SQLite + 索引） | L2Manager | L2SQLiteStore.delete() |
| `FlexibleKnowledge.modify_card` | `(card_id, new_content, usefulness, misleading, comment) → KnowledgeCard\|None` | 修改卡片（内存 + SQLite） | L2Manager | L2SQLiteStore.update() |

## core/storage/l1_store.py

| 函数/类 | 签名 | 作用 | 上游调用者 | 下游调用 |
|----------|------|------|-----------|---------|
| `L1SQLiteStore` | `__init__(db_path)` | SQLite WAL 模式存储 L1 规则 | Philosophy | sqlite3 |
| `L1SQLiteStore.insert` | `(rule: dict) → None` | 插入或替换一条规则 | Philosophy.add_rule | — |
| `L1SQLiteStore.update` | `(rule_id, **fields) → bool` | 按字段更新规则 | Philosophy.modify_rule | — |
| `L1SQLiteStore.delete` | `(rule_id) → bool` | 删除规则 | Philosophy.remove_rule | — |
| `L1SQLiteStore.list_all` | `() → list[dict]` | 返回全部规则 | Philosophy._load_from_db | — |
| `L1SQLiteStore.count` | `() → int` | 返回规则总数 | Philosophy._load | — |

## core/storage/l2_store.py

| 函数/类 | 签名 | 作用 | 上游调用者 | 下游调用 |
|----------|------|------|-----------|---------|
| `L2SQLiteStore` | `__init__(db_path)` | SQLite WAL 模式存储 L2 知识卡片 | FlexibleKnowledge | sqlite3 |
| `L2SQLiteStore.insert` | `(card: dict) → None` | 插入或替换一张卡片 | FlexibleKnowledge.add_card | — |
| `L2SQLiteStore.update` | `(card_id, **fields) → bool` | 按字段更新卡片 | FlexibleKnowledge.modify_card | — |
| `L2SQLiteStore.delete` | `(card_id) → bool` | 删除卡片 | FlexibleKnowledge.remove_card | — |
| `L2SQLiteStore.get` | `(card_id) → dict\|None` | 按 ID 获取单张卡片 | — | — |
| `L2SQLiteStore.list_all` | `() → list[dict]` | 返回全部卡片 | FlexibleKnowledge._load_cards_from_db | — |
| `L2SQLiteStore.list_by_domain` | `(domain) → list[dict]` | 按 available_domains 模糊匹配 | — | — |
| `L2SQLiteStore.close` | `() → None` | 关闭连接 | — | — |

## core/storage/l3_store.py

| 函数/类 | 签名 | 作用 | 上游调用者 | 下游调用 |
|----------|------|------|-----------|---------|
| `L3SQLiteStore` | `__init__(db_path)` | SQLite WAL 模式存储 L3 技能（含 SKILL.md 内容） | SkillLayer | sqlite3 |
| `L3SQLiteStore.insert` | `(skill: dict) → None` | 插入或替换一个技能 | SkillLayer.create_skill | — |
| `L3SQLiteStore.update` | `(name, **fields) → bool` | 按字段更新技能 | SkillLayer.edit_skill | — |
| `L3SQLiteStore.delete` | `(name) → bool` | 删除技能 | SkillLayer.delete_skill | — |
| `L3SQLiteStore.get` | `(name) → dict\|None` | 按 name 获取单个技能 | — | — |
| `L3SQLiteStore.list_all` | `() → list[dict]` | 返回全部技能 | SkillLayer._load_from_db | — |
| `L3SQLiteStore.list_by_domain` | `(domain) → list[dict]` | 按 available_domains 模糊匹配 | — | — |
| `L3SQLiteStore.count` | `() → int` | 返回技能总数 | — | — |
| `L3SQLiteStore.close` | `() → None` | 关闭连接 | — | — |

## core/storage/domain_store.py

| 函数/类 | 签名 | 作用 | 上游调用者 | 下游调用 |
|----------|------|------|-----------|---------|
| `DomainSQLiteStore` | `__init__(db_path)` | SQLite WAL 模式存储 DomainRegistry nodes + reverse_index | DomainRegistry | sqlite3 |
| `DomainSQLiteStore.insert_node` | `(node: dict) → None` | 插入或替换一个 domain 节点 | DomainRegistry.add_node | — |
| `DomainSQLiteStore.update_node` | `(path, **fields) → bool` | 按字段更新节点 | DomainRegistry.update_correlation, compute_embedding, merge_domain | — |
| `DomainSQLiteStore.delete_node` | `(path) → bool` | 删除节点 | DomainRegistry._remove_domain, deprecate_domain | — |
| `DomainSQLiteStore.get_node` | `(path) → dict\|None` | 按 path 获取单个节点 | — | — |
| `DomainSQLiteStore.list_nodes` | `() → list[dict]` | 返回全部节点 | DomainRegistry._load_from_db | — |
| `DomainSQLiteStore.index_item` | `(layer, domain, item_id) → None` | 插入反向索引条目 | DomainRegistry.index_item, merge_domain | — |
| `DomainSQLiteStore.unindex_item` | `(layer, domain, item_id) → None` | 删除单条反向索引 | DomainRegistry.unindex_item, update_item_domains | — |
| `DomainSQLiteStore.unindex_domain` | `(layer, domain) → None` | 删除某 domain 全部反向索引 | DomainRegistry._remove_domain, deprecate_domain | — |
| `DomainSQLiteStore.get_items` | `(layer, domain) → list[str]` | 获取某 layer+domain 的 item_id 列表 | — | — |
| `DomainSQLiteStore.get_all_index` | `() → dict` | 返回完整反向索引结构 | DomainRegistry._load_from_db | — |
| `DomainSQLiteStore.count` | `() → int` | 返回节点总数 | — | — |
| `DomainSQLiteStore.close` | `() → None` | 关闭连接 | — | — |

## core/storage/kb_store.py

| 函数/类 | 签名 | 作用 | 上游调用者 | 下游调用 |
|----------|------|------|-----------|---------|
| `KBSQLiteStore` | `__init__(db_path)` | SQLite WAL 模式存储 KB metadata（非 txtai 内容） | KnowledgeBase | sqlite3 |
| `KBSQLiteStore.insert` | `(doc: dict) → None` | 插入或替换一条 KB metadata | KnowledgeBase._add_single | — |
| `KBSQLiteStore.update` | `(doc_id, **fields) → bool` | 按字段更新 metadata，自动设置 updated_at | — | — |
| `KBSQLiteStore.delete` | `(doc_id) → bool` | 删除 metadata | KnowledgeBase.delete | — |
| `KBSQLiteStore.get` | `(doc_id) → dict\|None` | 按 ID 获取 metadata | — | — |
| `KBSQLiteStore.list_all` | `() → list[dict]` | 返回全部 metadata | KnowledgeBase._load_meta_from_db | — |
| `KBSQLiteStore.list_by_domain` | `(domain) → list[dict]` | 按 domain 过滤 metadata | — | — |
| `KBSQLiteStore.touch` | `(doc_id) → None` | 更新 last_used 时间戳 | — | — |
| `KBSQLiteStore.close` | `() → None` | 关闭连接 | KnowledgeBase.close | — |

## core/knowledge/knowledge_base.py

| 函数/类 | 签名 | 作用 | 上游调用者 | 下游调用 |
|----------|------|------|-----------|---------|
| `KnowledgeBase` | `__init__(storage_path="data/knowledge", meta_db_path=None)` | 静态知识库，BM25+embeddings 两路检索 + CRUD；可选 SQLite metadata 后端 | scripts, KnowledgeCapability | txtai Embeddings, KBSQLiteStore (if meta_db_path) |
| `KnowledgeBase._load_meta_from_db` | `() → None` | 从 SQLite 加载 metadata 到 _docs 内存 | __init__ | KBSQLiteStore.list_all() |
| `KnowledgeBase.add` | `(doc: KnowledgeDoc) → list[str]` | 添加文档（自动 >8192 token 分块），upsert 到 txtai | seed scripts | _chunk_and_add(), _add_single(), _ensure_domain() |
| `KnowledgeBase.get` | `(doc_id) → KnowledgeDoc\|None` | 按 ID 获取文档 | tools.py | — |
| `KnowledgeBase.update` | `(doc_id, **kwargs) → bool` | 更新文档字段，upsert 到 txtai | tools.py | _ensure_emb() |
| `KnowledgeBase.delete` | `(doc_id) → bool` | 删除文档，从 txtai delete + meta_db delete | tools.py | embeddings.delete(), KBSQLiteStore.delete() |
| `KnowledgeBase.search` | `(query, domain=None, top_k=5) → list[dict]` | txtai embeddings+BM25 两路融合搜索，domain 过滤，返回 top_k | KnowledgeCapability, tools.py | embeddings.search() |
| `KnowledgeBase._add_single` | `(doc: KnowledgeDoc) → str` | 单文档 upsert（去 meta.id），更新 domain 计数，写入 meta_db | add(), load() | embeddings.upsert(), KBSQLiteStore.insert() |
| `KnowledgeBase._chunk_and_add` | `(doc: KnowledgeDoc) → list[str]` | >8192 token 文档分块添加，chunk 间通过 meta.chunk_of 链接 | add() | _count_tokens(), _add_single() |
| `KnowledgeBase._ensure_emb` | `() → None` | 懒初始化 txtai Embeddings（path=embeddinggemma, content=sqlite, keyword=bm25） | _add_single(), update(), search(), list_domains | Embeddings() |
| `KnowledgeBase.save` | `() → None` | 持久化 txtai；若 meta_db 激活则跳过 kb.json（metadata 已在 SQLite） | scripts, CLI | embeddings.save() |
| `KnowledgeBase.load` | `() → None` | 从 disk 加载 txtai 索引 + kb.json；若无 disk 数据则从 kb.json 重建 | scripts, CLI | embeddings.load() / embeddings.upsert() |
| `KnowledgeBase.list_domains` | `() → list[dict]` | 列出所有 domain（path/parent/description/doc_count） | tools.py | — |
| `KnowledgeBase.get_meta` | `(doc_id) → dict\|None` | 获取文档 meta | tools.py | — |
| `KnowledgeBase.update_meta` | `(doc_id, meta: dict) → bool` | 局部更新 meta dict | tools.py | — |
| `KnowledgeBase.rename_domain` | `(old_path, new_path) → int` | 重命名 domain 及其文档 | tools.py | — |
| `KnowledgeBase.close` | `() → None` | 关闭 txtai embeddings + meta_db | — | embeddings.close(), KBSQLiteStore.close() |

### KnowledgeBase 配置（Embeddings config）

| 配置项 | 值 | 说明 |
|--------|-----|------|
| `path` | `C:/Users/micha/PycharmProjects/cognitive-agent/embeddinggemma` | 本地 Gemma embedding 模型路径（768-dim, 2048 token max） |
| `trust_remote_code` | `True` | HF trust |
| `content` | `"sqlite"` | 文档存储后端（SQLite） |
| `keyword` | `"bm25"` | 关键词搜索方法（展开为 scoring={method:"bm25",terms:True,normalize:True}） |

### KnowledgeBase 存储布局（storage_path 目录）

| 文件/目录 | 内容 | 管理者 |
|-----------|------|--------|
| `config` | txtai 配置（模型路径、scoring 参数等） | txtai save/load |
| `embeddings` | ANN 向量索引（NumPy, 768-dim） | txtai save/load |
| `scoring` | BM25 倒排索引 | txtai save/load |
| `documents/` | SQLite 数据库（id + text + tags） | txtai save/load |
| `kb.json` | 文档（KnowledgeDoc dict）+ domains（KBDomain dict）| KnowledgeBase save/load |

### KnowledgeBase 工具接口（core/knowledge/tools.py）

所有 handler 签名为 `(kb: KnowledgeBase, **kwargs) → str`（返回 JSON）。

| 工具名 | 输入 | 输出 |
|--------|------|------|
| `knowledge_query` | `query`, `domain?`, `top_k?`(5) | `{results: [{id, domain, title, content[:500], score, source, meta}]}` |
| `knowledge_add` | `domain`, `title`, `content`, `meta?`, `source?`("agent") | `{status, doc_id}` |
| `knowledge_get` | `doc_id` | `{status, doc: KnowledgeDoc \| null}` |
| `knowledge_update` | `doc_id`, `content?`, `meta?`（局部 merge） | `{status}` |
| `knowledge_delete` | `doc_id` | `{status}` |
| `knowledge_list_domains` | `parent?` | `{domains: [{path, parent, description, doc_count}]}` |
| `knowledge_sync_domain` | `action`(rename), `source_domain`, `target_domain` | `{status, count}` |

## core/skill_layer.py (已有，层内部使用)

| 函数/类 | 签名 | 作用 | 上游调用者 | 下游调用 |
|----------|------|------|-----------|---------|
| `SkillLayer` | `__init__(skills_dir, domain_registry=None, db_path=None)` | L3 技能管理（可选 SQLite 后端） | L3Manager | L3SQLiteStore (if db_path) |
| `SkillLayer._load_from_db` | `() → None` | 从 SQLite 加载全部技能为内存对象 | __init__ | L3SQLiteStore.list_all() |
| `SkillLayer.match` | `(domain) → list[SkillMeta]` | 按 domain 匹配技能 | L3Manager.query() | — |
| `SkillLayer.create_skill` | `(name, content, domain, cross_domain=False, created_by="agent", available_domains=None) → SkillMeta` | 创建新技能（内存 + SQLite） | L3Manager | L3SQLiteStore.insert() |
| `SkillLayer.edit_skill` | `(name, new_content=None, usefulness=None, misleading=None, comment=None) → SkillMeta` | 更新技能内容/质量字段（内存 + SQLite） | L3Manager | L3SQLiteStore.update() |
| `SkillLayer.delete_skill` | `(name) → None` | 软删除技能（移到.archive + SQLite + unindex from DomainRegistry） | L3Manager | L3SQLiteStore.delete(), DomainRegistry.unindex_item() |
| `SkillLayer.touch_skill` | `(name) → None` | 标记技能最近使用（更新 last_used） | L3Manager.query() | — |

## core/env/base.py

| 函数/类 | 签名 | 作用 | 上游调用者 | 下游调用 |
|----------|------|------|-----------|---------|
| `EnvState` | `@dataclass(observation, info)` | 环境状态 | — | — |
| `EnvStep` | `@dataclass(state, reward, done)` | 环境 step 结果 | — | — |
| `Environment` | `ABC(reset, step)` | 环境抽象基类 | GameEnv, LearningEnv, InteractionEnv | — |
| `Environment.tool_policy` | `() → dict\|None` | 可选 per-env 工具过滤策略。返回 `{"allowed": [...], "denied": [...]}` 或 None。R1/R3 兼容（只给名字、不注入定义） | chain_factory | AgentContext.from_policy() |

## core/env/learning_env.py (Phase 2.1)

| 函数/类 | 签名 | 作用 | 上游调用者 | 下游调用 |
|----------|------|------|-----------|---------|
| `LearningEnv` | `__init__(pending_dir, knowledge_stores, preprocessing_llm=None, l2_card_limit=None, l3_skill_limit=None, dry_run=False, consolidation_spec=None, domain_registry=None)` | 学习环境：构建 TaskObservation + 监测 consolidation 触发。应用层（_apply_*/_parse_*/_quality_kwargs）已删（handler 直接改 store）。step 退化为轻量（只计轮次）。 | run_leduc_cognitive.py, auto-learning | ThresholdScorer |
| `LearningEnv.reset` | `(task_description) → EnvState` | 扫描 pending/ records，构建 observation | orchestrator | _scan_pending(), _build_learning_units() |
| `LearningEnv.step` | `(action) → EnvStep` | 退化为轻量：只计轮次（_step_count += 1），修改由 consolidation handler 直接改 store | Executor | — |
| `LearningEnv.build_task_observation` | `() → TaskObservation` | 构建 TaskObservation 供 Executor+Layers 消费 | run_leduc_cognitive.py | — |
| `LearningEnv.build_consolidation_task` | `() → TaskObservation\|None` | L2/L3 超限时构建整理任务 | orchestrator | — |
| `LearningEnv.archive_pending` | `() → int` | 移动已处理 records 到 learned/ | run_leduc_cognitive.py | — |
| `LearningEnv.process_in_memory` | `(records, domain) → TaskObservation` | 从内存中的 record_learning 记录构建 TaskObservation（跳过 LLM1，简单任务格式） | _dispatch_learning | — |

## core/env/interaction_env.py

| 函数/类 | 签名 | 作用 | 上游调用者 | 下游调用 |
|----------|------|------|-----------|---------|
| `InteractionEnv` | `__init__(system_prompt: str, debug: bool, enable_learning: bool)` | 通用对话交互环境，管理会话和对话历史，构造 Executor 预期的 TaskObservation | interactive_agent.py | — |
| `InteractionEnv.reset` | `(task_description: str) → EnvState` | 创建新会话（UUID + UTC 时间戳），清空历史 | interactive_agent.py | — |
| `InteractionEnv.receive_input` | `(user_input: str) → None` | 接收用户输入存入 _pending_input | interactive_agent.py | — |
| `InteractionEnv.build_task_observation` | `() → TaskObservation \| None` | 对齐 LearningEnv 模式：从 pending_input + history 构造 TaskObservation | interactive_agent.py | _format_history_for_prompt() |
| `InteractionEnv.step` | `(action: str) → EnvStep` | 记录本轮 (user, assistant) 到 history，清空 pending_input | interactive_agent.py | — |
| `InteractionEnv.get_history` | `() → list[dict]` | 返回 history 的深层副本 | interactive_agent.py | — |
| `InteractionEnv.save_history` | `(filepath: Path) → Path` | 将完整会话 JSON 序列化到文件（/quit 触发） | interactive_agent.py | — |
| `InteractionEnv.session_info` | `() → dict` | 返回当前会话元信息 {id, turns, started_at, enable_learning} | interactive_agent.py | — |
| `InteractionEnv._format_history_for_prompt` | `() → str` | 将 history 格式化为 `[用户]: ...\n[助手]: ...` 文本 | build_task_observation() | — |

## core/env/threshold_scorer.py (Phase 2.3 — 从 core/orchestrator/ 迁移)

| 函数/类 | 签名 | 作用 | 上游调用者 | 下游调用 |
|----------|------|------|-----------|---------|
| `ThresholdScorer` | `__init__(pending_dir, task_count_weight, complexity_weight, baseline_tokens, threshold)` | 按 domain 计算 pending records 的学习触发分数 | LearningEnv, run_leduc_cognitive.py | — |
| `ThresholdScorer.score` | `(domain) → float` | 计算某 domain 的分数 (count + tokens) | should_trigger() | _domain_records() |
| `ThresholdScorer.should_trigger` | `(domain) → bool` | 判断是否达到学习触发阈值 | run_leduc_cognitive.py | score() |
| `ThresholdScorer.domain_count` | `(domain) → int` | 返回某 domain 的 pending records 数量 | test | _domain_records() |
| `ThresholdScorer.domain_health_report` | `(registry, l2_store, l3_store) → str` | 构建 domain 健康报告 Markdown 表格（card/skill 计数、correlation、状态） | LearningEnv.build_consolidation_task | DomainRegistry.list_all(), get_primary_items() |

## core/layer_message.py (已有)

| 函数/类 | 签名 | 作用 | 上游调用者 | 下游调用 |
|----------|------|------|-----------|---------|
| `LayerMessage` | `@dataclass(frozen=True, source, target, type:MessageType, payload, trace_id, subtype, timestamp, metadata)` | 层间通信信封（A2） | Comm Agents | Comm Agents |
| `MessageType` | `Enum(QUERY, RESPONSE, PROPOSAL, APPROVAL, REJECTION, NOTIFY)` | 基础信封类型 | LayerMessage 构造 | — |

## scripts/douzero_agent.py

| 函数/类 | 签名 | 作用 | 上游调用者 | 下游调用 |
|----------|------|------|-----------|---------|
| `DouZeroLLMAgent` (已有) | `__init__(llm_client, position, use_perfect_info)` | 直接调 LLM 的斗地主 Agent（绕过认知层） | run_douzero_llm.py --mode direct | LLMClient.chat() |
| `DouZeroLLMAgent.act` | `(infoset) → list[int]` | 从 InfoSet 到动作的完整流程 | DouZero GameEnv.step() | build_prompt_test(), LLMClient.chat(), parse_action() |
| `DouZeroLLMAgent.build_prompt` | `(infoset) → dict` | 结构化 game state（给 Agent 系统消费） | CognitiveAgent | — |
| `DouZeroLLMAgent.build_prompt_test` | `(infoset) → str` | 自闭环中文 prompt（绕过 Agent 系统） | act() | — |
| `DouZeroCognitiveAgent` (NEW) | `__init__(executor, position)` | 通过 Executor + LayerChain 决策的斗地主 Agent | run_douzero_llm.py --mode cognitive | Executor.execute() |
| `DouZeroCognitiveAgent.act` | `(infoset) → list[int]` | TaskObservation → Executor → action | DouZero GameEnv.step() | Executor.execute(), parse_action() |
| `DouZeroCognitiveAgent._build_state` | `(infoset) → dict` | InfoSet → TaskObservation.state | act() | — |
| `cards_to_str` | `(cards:list[int]) → str` | DouZero 卡牌编码 → 人类可读字符串 | 各处 | — |

## scripts/interactive_agent.py

| 函数/类 | 签名 | 作用 | 上游调用者 | 下游调用 |
|----------|------|------|-----------|---------|
| `DEFAULT_SYSTEM_PROMPT` | `str` | 默认 system_prompt："你是一个智能助手…" | InteractionEnv 构造 | — |
| `main` | `() → None` | CLI 交互式认知 Agent 入口（/new, /info, /quit） | 直接运行 | _setup_executor, InteractionEnv, Executor.execute |
| `_setup_executor` | `() → Executor` | 委托 `core.setup.setup_executor(PROJECT_ROOT)` 并返回 executor（chain 丢弃） | main | setup_executor |
| `_show_notifies` | `(notify_layers: dict) → None` | 打印三层 NOTIFY payload（debug 模式） | main | — |

## capability/ — Phase 3 能力系统

### capability/__init__.py

| 函数/类 | 签名 | 作用 | 上游调用者 | 下游调用 |
|----------|------|------|-----------|---------|
| `CapabilityResult` | `@dataclass(frozen=True, capability_name, layer, success, data, error, metadata)` | 能力调用结果统一格式 | ToolCapability, KnowledgeCapability | LayerInjector |
| `Capability` | `ABC(name, get_schema, is_visible_to, invoke)` | 可被认知层调用的能力抽象 | ToolCapability, KnowledgeCapability | — |
| `CapabilityRegistry` | `register(cap) / get(name) / get_schemas_for_layer(layer) / invoke(name, layer, args) / list_for_layer(layer)` | 统一能力注册与分发中心 | LayerInjector, setup scripts | — |

### capability/tool_capability.py

| 函数/类 | 签名 | 作用 | 上游调用者 | 下游调用 |
|----------|------|------|-----------|---------|
| `ToolCapability` | `__init__(registry, allowlist)` | 包装 ToolRegistry，加层可见性控制 | setup scripts | ToolRegistry.dispatch() |
| `ToolCapability.is_visible_to` | `(layer) → bool` | 该层是否至少有一个工具可见 | CapabilityRegistry | — |
| `ToolCapability.invoke` | `(layer, args{name, args}) → CapabilityResult` | 校验权限 → dispatch → 返回结果 | LayerInjector.execute_tool_call() | ToolRegistry.dispatch() |
| `ToolCapability.get_schemas_by_layer` | `(layer) → list[dict]` | 返回该层可见工具的 OpenAI schema 列表 | LayerInjector.get_tools_for_layer() | ToolRegistry.get_definitions() |
| `_get_allowlist` | `() → dict[str, set[str]]` | 从 config/tools.yaml 读取 per-layer tool allowlist。无模块级常量 | ToolCapability.__init__ | yaml.safe_load |

### capability/knowledge_capability.py

| 函数/类 | 签名 | 作用 | 上游调用者 | 下游调用 |
|----------|------|------|-----------|---------|
| `BaseKnowledgeStore` | `ABC(search, get, add, remove, list_ids)` | 静态知识存储抽象（可替换为 vector DB） | — | InMemoryKnowledgeStore |
| `InMemoryKnowledgeStore` | `__init__()` | 内存 dict 实现 + 简单关键词匹配 | setup, tests | — |
| `KnowledgeCapability` | `__init__(stores: dict[name, (store, visible_layers)])` | 将 KnowledgeStore 包装为 Capability | setup scripts | store.search() |
| `KnowledgeCapability.invoke` | `(layer, args{store, query, top_k}) → CapabilityResult` | 校验 store 权限 → 搜索 → 返回结果 | LayerInjector.execute_tool_call() | store.search() |
| `seed_knowledge_stores` | `() → dict[str, InMemoryKnowledgeStore]` | 开发/测试用种子数据 | smoke tests | — |

### capability/layer_injector.py

| 函数/类 | 签名 | 作用 | 上游调用者 | 下游调用 |
|----------|------|------|-----------|---------|
| `LayerInjector` | `__init__(registry)` | 将 CapabilityRegistry 的能力注入各层 Agent | setup scripts, LayerAgent | CapabilityRegistry |
| `LayerInjector.get_tools_for_layer` | `(layer) → list[dict]` | 聚合 ToolCapability + KnowledgeCapability 的可见 schema | LayerAgent._call_llm() | ToolCapability.get_schemas_by_layer(), KnowledgeCapability.get_schema() |
| `LayerInjector.inject_to_agent` | `(layer, call_kwargs) → dict` | 注入 tools 字段到 call_kwargs | LayerAgent stage methods | — |
| `LayerInjector.execute_tool_call` | `(layer, name, raw_args) → CapabilityResult` | 执行单个 tool_call（供 _call_llm 多轮循环） | LayerAgent._call_llm() | CapabilityRegistry.invoke() |
| `LayerInjector.handle_tool_calls` | `(layer, tool_calls) → list[CapabilityResult]` | 批量执行 tool_calls | smoke tests | execute_tool_call() |
| `LayerInjector.format_results_for_prompt` | `(results) → str` | 格式化 CapabilityResult 列表为 prompt 文本 | smoke tests | — |

## core/llm_client.py — Phase 3 更新

| 函数/类 | 签名 | 变化 | 上游调用者 | 下游调用 |
|----------|------|------|-----------|---------|
| `ToolCall` | `@dataclass(id:str, function:FunctionCall)` | **新增** `id` 字段，用于 DeepSeek role:"tool" 消息的 tool_call_id | LLMClient.chat() | LayerAgent._call_llm() |
| `LLMClient.chat` | `(messages, tools=None, json_mode=False) → LLMResponse` | **新增** `tools` 参数，透传 OpenAI function-calling 格式到 API | LayerAgent._call_llm() | OpenAI API |

## core/layers/base.py — Phase 3 更新

| 函数/类 | 签名 | 变化 | 上游调用者 | 下游调用 |
|----------|------|------|-----------|---------|
| `LayerAgent.set_injector` | `(injector) → None` | **新增**，注入 LayerInjector | chain_factory._mount_tools() | — |
| `LayerAgent._call_llm` | `(system, user, schema, tools, layer, capture_tools) → dict` | **增强**：新增 `capture_tools` 参数；多轮 tool call 循环（`self._max_tool_turns`，从 config.yaml runtime.max_tool_turns 读取，默认 5）；tools 存在时自动禁用 json_mode；**sync/async dispatch**：按 tool_call args 中 `sync` 参数拆分为 sync_batch（run_sync_batch）和 async_calls（TaskRunner.submit），async 立即返回 task_id；async 分支有 thread-local context 时登记到 SessionStore | L1/L2/L3 decide() | LLMClient.chat(), robust_parse(), injector.execute_tool_call(), TaskRunner.submit(), SessionStore.register_task (async branch, via get_task_context) |
| `LayerAgent._schema_to_tool` | `(name, description, schema) → dict` | **新增**：JSON Schema → OpenAI function-calling tool 定义，供 capture_tools 模式使用。 | decide() | — |

## core/env/learning_env.py — Phase 3 更新

| 函数/类 | 签名 | 变化 | 上游调用者 | 下游调用 |
|----------|------|------|-----------|---------|
| `load_consolidation_spec` | `(spec_path) → dict` | **新增** 函数，从 consolidation.yaml 加载内容规格 | LearningEnv.__init__ | yaml.safe_load |
| `LearningEnv.__init__` | 新增 `consolidation_spec` 参数 | 加载 consolidation spec，用于 build_consolidation_task 的增强 prompt | scripts | — |
| `LearningEnv.needs_consolidation` | `() → bool` | **新增** 方法，L2/L3 超限检测 | run scripts | — |
| `LearningEnv.get_consolidation_level` | `() → int` | **新增** 方法，0=无, 1=例行, 2=深度 | run scripts | — |
| `LearningEnv.build_consolidation_task` | `() → TaskObservation` | **增强**：从 spec 注入条目格式规范、anti-patterns、整理策略等级；注入 `l1/l2/l3_feedback` | run scripts | — |
| `LearningEnv._layer_feedback` | `dict[str, str]` | **新增** 属性：`step()` 后将 per-layer apply 结果存入，供下次 `build_task_observation()` 注入 state | step() → build_task_observation() | — |
| `LearningEnv._shared_feedback` | `str` | **新增** 属性：`step()` 生成共享摘要（总修改数/成功/被拒/dry-run），所有层均读取 | step() → build_task_observation() | — |
| `state.feedback` | `str` | **新增** state 字段：共享反馈，被 L1/L2/L3 共同读取，作为 `[修改结果确认]` 的通用前缀 | build_task_observation() / build_consolidation_task() | L1/L2/L3 Agent |
| `state.lX_feedback` | `str` | **增强**：L1/L2/L3 各自读取 `feedback` + `lX_feedback` 合并为完整反馈展示。共享 → `feedback`，专属 → `lX_feedback` | build_task_observation() | L1/L2/L3 Agent |
| `L1Agent._build_user_context` | `(state) → str` | **增强**：读取 `state["feedback"]`（共享）+ `state["l1_feedback"]`（专属），合并追加 `[L1 修改结果确认]` 节 | stage1/stage2 | — |
| `L2Agent._build_learning_section` | `(state) → str` | **增强**：读取 `state["feedback"]`（共享）+ `state["l2_feedback"]`（专属），合并追加 `[L2 修改结果确认]` 节 | stage1/stage2 | — |
| `L3Agent.execute` | `(meta, state, matched_skills) → dict` | **增强**：读取 `state["feedback"]`（共享）+ `state["l3_feedback"]`（专属），合并前置 `[L3 修改结果确认]` 节 | L3Manager.query() | _call_llm() |

## docs/superpowers/specs/2026-06-08-env-agent-boundary.md — 项目纪律

| 规则 | 含义 |
|------|------|
| R1 | Environment 不碰 Agent 内部（不注入 tool、不修改 prompt、不调 ToolRegistry） |
| R2 | Agent 不感知 Environment 类型（不 if env_type，只读 meta/state） |
| R3 | 工具挂载由 Agent 层自主决定（Environment 只设 state 信号） |
| R4 | 持久化由 Executor 执行，Environment 只设 enable_learning 标志位 |
| R5 | Layer feedback 通过 state 字段注入，不走旁路 |

## core/json_repair.py — 2026-06-11 集成

| 函数 | 签名 | 作用 | 上游调用者 | 下游调用 |
|------|------|------|-----------|---------|
| `robust_parse` | `(text: str, schema: dict\|None) → dict` | 多层容错 JSON 解析：T0 直接解析 → T1 markdown 代码块提取 → T2 bracket 修复 → T3 语法修复 → T4 schema 字段级提取 | `LayerAgent._call_llm()` | `_try_json_loads`, `_extract_json_block`, `_bracket_repair`, `_syntax_repair`, `_schema_salvage` |

## core/env_loader.py

| 函数/类 | 签名 | 作用 | 上游调用者 | 下游调用 |
|----------|------|------|-----------|---------|
| `load_env` | `(project_root: Path\|None = None) → None` | 加载 .env 文件到 os.environ（跳过已设置的 key） | llm_factory.build_llm_client | — |

## core/seed_knowledge.py

| 函数/类 | 签名 | 作用 | 上游调用者 | 下游调用 |
|----------|------|------|-----------|---------|
| `init_registry` | `(registry_path, embedding_model_path=None, db_path=None) → DomainRegistry` | 加载或初始化 DomainRegistry（空则 seed domain 树 + 持久化） | chain_factory.build_default_chain | DomainRegistry.load(), _seed_domain_nodes(), DomainSQLiteStore |
| `seed_knowledge` | `(fk, phil, sl=None, domain_registry=None) → None` | 从 config.yaml seed L1 规则 + L2 卡片 + L3 技能 | chain_factory.build_default_chain | Philosophy.add_rule(), FlexibleKnowledge.add_card(), SkillLayer.create_skill() |
| `_seed_domain_nodes` | `() → DomainRegistry` | 构建 seed domain 树（general/game/learning 层级） | init_registry | DomainRegistry.add_node() |

## config.yaml — consolidation 段（Phase 3）

> 原 `config/layers/consolidation.yaml` 已在 Config Overhaul 中合并进 `config.yaml` 的 `consolidation:` 段。

| 功能 | 描述 |
|------|------|
| 各层条目规格 | L1 Rule / L2 KnowledgeCard / L3 Skill 的字段定义（名称、类型、长度、ID 格式、required） |
| 容量限制 | soft/hard 两级，per-domain 细分 |
| Anti-patterns | 各层应避免的内容模式（重复、过于泛化、低置信度等） |
| 三级整理策略 | Level 0（无）/ Level 1（例行归并，可回滚）/ Level 2（深度压缩，需审核） |

---

## core/session.py

| 函数/类 | 签名 | 作用 | 上游调用者 | 下游调用 |
|----------|------|------|-----------|---------|
| `set_task_context` | `(session_id: str, task_id: str) → None` | 设置当前线程的 session_id + task_id（dispatch 跟踪用） | Gradio chat handler（execute 前）, dispatch handlers | threading.local |
| `get_task_context` | `() → tuple[str\|None, str\|None]` | 返回当前线程的 (session_id, task_id)，未设置返回 (None, None) | record_learning_tool handler, base.py dispatch handlers | threading.local |
| `clear_task_context` | `() → None` | 清除当前线程的 task context | Gradio chat handler（execute 后）, test fixtures | threading.local |
| `SessionStore` | `__init__(db_path: Path\|str = "data/cognitive/sessions.db")` | SQLite WAL 持久化 sessions + tasks 元数据，check_same_thread=False + 写锁 | get_session_store, Gradio frontend, tests | sqlite3 |
| `SessionStore.create_session` | `(name: str, log_dir: str\|None = None) → dict` | 新建用户工作区（uuid hex[:12]，status='active'），返回 session dict | Gradio frontend | — |
| `SessionStore.list_sessions` | `(include_closed: bool = False) → list[dict]` | 列出 sessions（默认排除 status='closed'），按 last_active_at DESC | Gradio frontend | — |
| `SessionStore.get_session` | `(session_id: str) → dict\|None` | 按 id 获取单个 session | Gradio frontend | — |
| `SessionStore.update_session` | `(session_id: str, **fields) → bool` | 按字段更新 session，自动刷新 last_active_at（跳过该字段显式赋值） | Gradio frontend, close_session | — |
| `SessionStore.close_session` | `(session_id: str) → None` | 标记 session 为 status='closed'（软关闭，可 include_closed=true 列出） | Gradio frontend | update_session |
| `SessionStore.delete_session` | `(session_id: str) → None` | 硬删除 session + 级联删除其全部 tasks | Gradio frontend | — |
| `SessionStore.register_task` | `(task_id, session_id, type, parent_task_id=None, tool_name=None, trace_id=None) → None` | 注册 task（INSERT OR REPLACE，默认 status='running' progress=0.0） | Gradio chat handler（top task）, dispatch handlers（sub task via thread-local context） | — |
| `SessionStore.update_task` | `(task_id: str, **fields) → bool` | 按字段更新 task，自动刷新 updated_at | Gradio frontend, dispatch handlers | — |
| `SessionStore.list_tasks` | `(session_id: str, parent_task_id: str\|None = None) → list[dict]` | 列出 session 下 tasks，可按 parent_task_id 过滤子任务 | Gradio frontend | — |
| `SessionStore.get_task` | `(task_id: str) → dict\|None` | 按 id 获取单个 task | Gradio frontend, dispatch handlers | — |
| `SessionStore.mark_interrupted_on_startup` | `(threshold_seconds: int = 3600) → int` | 崩溃恢复：status='running' 且 updated_at 早于阈值的 task 改 'interrupted'，返回受影响行数 | gradio_app 启动 | — |
| `SessionStore.close` | `() → None` | 关闭 sqlite 连接 | tests, Gradio shutdown | — |
| `get_session_store` | `() → SessionStore` | 全局单例（双重检查锁） | Gradio frontend, dispatch handlers | SessionStore |

## core/monitor.py

> 纯查询模块——聚合 trace 数据源供前端展示，不修改任何状态。所有数据来自 SessionStore / per-layer 日志文件 / RoundTree.snapshot() / chain 内部。

| 函数/类 | 签名 | 作用 | 上游调用者 | 下游调用 |
|----------|------|------|-----------|---------|
| `snapshot` | `(session_id=None, chain=None, pending_dir="data/learning/pending") → dict` | 聚合全量状态快照，返回 {tasks, capacity, learning, sessions} | gradio_app | _task_list, _capacity_snapshot, _learning_snapshot, _session_summary |
| `task_list` | `(session_id, parent_task_id=None) → list[dict]` | 按 session 列出 tasks（可按 parent 过滤） | gradio_app, _task_list | get_session_store().list_tasks() |
| `task_detail` | `(task_id) → dict\|None` | 单个 task 详情 | gradio_app | get_session_store().get_task() |
| `log_tail` | `(log_dir, layer, lines=50) → str` | 读 per-layer 日志文件尾部 N 行（layer: l0_5_1/l2/l3/executor）；文件不存在返回 "" | gradio_app | Path.readlines() |
| `decision_tree` | `(task_id=None) → list[DecisionNode]` | 复用 RoundTree.snapshot()——线程局部决策树 | gradio_app | get_round_history().snapshot() |
| `_task_list` | `(session_id) → list[dict]` | session_id 为 None 时返回空列表，否则委托 task_list | snapshot | task_list |
| `_capacity_snapshot` | `(chain) → dict` | L2 cards / L3 skills 数量 vs config 上限，返回 {l2:{count,limit,over}, l3:{...}} | snapshot | get_section('learning'), chain._downstream._knowledge.cards, chain._downstream._downstream._skill_layer.list_all() |
| `_learning_snapshot` | `(pending_dir) → dict` | 统计 pending/ 下各 domain 文件数和 archive 总数，返回 {domains, total_pending, total_archive} | snapshot | Path.iterdir/glob/rglob |
| `_session_summary` | `() → dict` | 活跃 session 计数 + 最近一条 session，返回 {count, latest} | snapshot | get_session_store().list_sessions() |

## Long-term TODO

### Async / Multi-instance Agent Runtime

**范围**：整个 Agent 运行时的异步调度与多实例管理，不局限于 fill-gap。

**核心问题**：
1. 多 Agent 实例的 IO 管理（LLM call 流、tool 执行、stdin/stdout 路由）
2. 任务调度与生命周期（dispatch → run → complete/fail → cleanup）
3. 跨 Agent 通信（主 agent ↔ 子 agent、ask_user 的中断与恢复）
4. 状态持久化与故障恢复
5. 资源管理（LLM API rate limit、并发 tool 调用、KB 写锁）

**备选方案**：

| 方案 | 核心思路 | 复杂度 | 外部依赖 | IO 模型 |
|------|---------|--------|---------|---------|
| **A. asyncio 事件循环** | 全 Agent 跑在单进程 asyncio loop 上，每个 Agent 是 async coroutine | 中 | 无 | async/await 原生，需把 LLMClient/tool 全改为 async |
| **B. Agent Owner 模式** | 每个 SubAgent 有 Owner 对象管理线程、IO channel、状态机；主 Agent 通过 Owner API 通信 | 中高 | 无 | 线程 + Queue channel，Owner 负责 IO 路由 |
| **C. Celery/Redis 任务队列** | 发任务到 Redis → Worker 进程执行 → 结果回调 | 高 | Redis+Celery | Worker 内部同步，外部消息驱动 |
| **D. 消息总线 + 状态机** | 所有 Agent 通过 MessageBus 通信（类似 Actor 模型）；Supervisor 管理生命周期 | 高 | 可能 ZeroMQ | 消息驱动，Agent 异步消费 |
| **E. 进程池 + 共享存储** | 子进程池执行 Agent，结果写回 KB/文件，主 Agent 轮询或回调 | 中 | 无 | 进程间通过文件/DB 传结果，无实时通信 |

**关键权衡**：

| 维度 | A (asyncio) | B (Owner) | C (Celery) | D (Bus) | E (进程池) |
|------|------------|-----------|------------|---------|------------|
| 改造量 | 大（全链路 async） | 中（Agent 实现协议接口） | 大（基础设施） | 大（架构级重构） | 小（只改调度层） |
| ask_user 支持 | ✅ 原生协程暂停 | ✅ Owner 持有会话 | ⚠️ 需 callback | ✅ 消息回复 | ❌ 进程间难交互 |
| 跨进程扩展 | ❌ 单进程 | ⚠️ 线程受限 | ✅ | ✅ | ✅ |
| 故障恢复 | ❌ 进程崩溃全丢 | ⚠️ 需额外持久化 | ✅ 任务重试 | ⚠️ 需消息持久化 | ❌ 无内置恢复 |

**参考项目**：

| 项目 | 方案 | 要点 |
|------|------|------|
| **OpenClaw** (379k★) | 自建 lane-aware FIFO 队列，纯 TS/promises，无外部依赖 | session lane(maxConcurrent=1) + subagent lane(8) + cron lane，文件锁保护 session 写入 |
| **LangGraph** | StateGraph + checkpoint + interrupt | 概念贴合但拉 LangChain 全生态，替代现有 while-loop |

**当前结论**：
1. **多 Agent 实例并行** → SQLite 解决底层文件读写一致性（KB 本身基于 SQLite）。Python 多实例内存隔离默认。
2. **单实例内 sub-agent/tool 调度** → 手写方案，借鉴 OpenClaw lane 模型：进程内 FIFO 队列 + 每 lane 独立并发上限 + 文件锁。不引入 Redis/Celery。

---

## DomainRegistry — Domain Management V2

### DomainRegistry (core/domain_registry.py)

| Method | Signature | Description |
|--------|-----------|-------------|
| `compute_embedding` | `(path, content_getter) -> bool` | Compute and cache embedding vector for a domain using HFVectors + embeddinggemma |
| `compute_correlation` | `(a, b) -> float` | 50% embedding cosine + 50% reverse_index Jaccard, returns [0,1] |
| `refresh_embeddings_for` | `(domains, content_getter) -> int` | Recompute embeddings for given domains, returns count |
| `compute_all_correlations` | `() -> int` | Recompute all domain pair correlations, returns count |
| `mark_domain_dirty` | `(path) -> None` | Mark domain for incremental correlation flush | consolidation_tools handler |
| `flush_correlations` | `() -> int` | Recompute correlations for dirty domains only (O(n×dirty)), clears dirty set | L0_5_1Manager.query |
| `deprecate_domain` | `(path) -> None` | Remove domain node, raises if orphaned L2/L3 items exist |
| `merge_domain` | `(source, target, content_getter) -> dict` | Move items + merge correlations + deprecate source, auto-embeds target |
| `_remove_domain` | `(path) -> None` | Internal: remove domain without orphan check (used by merge) |

### DomainNode

| Field | Type | Description |
|-------|------|-------------|
| `embedding_vector` | `list[float] \| None` | Cached embeddinggemma vector, persisted to JSON |

### SkillLayer (core/skill_layer.py)

| Method | Signature | Description |
|--------|-----------|-------------|
| `touch_skill` | `(name) -> None` | Mark skill as recently used (sets last_used) |

### SkillMeta — new time fields

| Field | Type | Description |
|-------|------|-------------|
| `created_at` | `datetime` | When skill was created |
| `updated_at` | `datetime` | Last content update |
| `last_used` | `datetime` | Last time skill was matched |

### KnowledgeDoc — new time field

| Field | Type | Description |
|-------|------|-------------|
| `last_used` | `str` | ISO timestamp of last KB query hit |

### Consolidation Tools (ToolRegistry — core/tools/consolidation_tools.py)

| Tool | Description |
|------|-------------|
| `query_domain` | List L2 cards + L3 skills in a domain |
| `deprecate_domain` | Remove domain (fails if orphaned items) |
| `merge_domain` | Merge source→target: move items, merge correlations, deprecate source |
| `create_domain` (enhanced) | Create domain + must provide initial_cards or initial_skills |

### Modify Tools (L2/L3)

| Field | Description |
|-------|-------------|
| `domain` (modify_l2_card) | Change card's domain assignment |
| `domain` (modify_l3_skill) | Change skill's domain assignment |

## scripts/gradio_app.py (Gradio v2 Task 7)

| 函数/类 | 签名 | 作用 | 上游调用者 | 下游调用 |
|----------|------|------|-----------|---------|
| `SessionState` | `@dataclass(env, session_id, session_name, current_task_id, chat_history)` | 每浏览器会话状态（Gradio State 每用户一份） | gr.State | — |
| `DEFAULT_SYSTEM_PROMPT` | `str` | 默认 system_prompt（与 interactive_agent 同） | _create_env | — |
| `main` | `() → None` | Gradio 入口：setup_executor → _setup_task_tracking → 构建 Blocks 三栏 UI → launch(127.0.0.1:7860) | 直接运行 | setup_executor, _setup_task_tracking, gr.Blocks, create_session/switch_session/delete_session/chat/select_task/refresh_log (closures) |
| `_create_env` | `(system_prompt=DEFAULT_SYSTEM_PROMPT) → InteractionEnv` | 新建 InteractionEnv(debug=True, enable_learning=True) + reset("interaction") | create_session, switch_session | InteractionEnv |
| `_setup_task_tracking` | `() → None` | 订阅 TaskRunner 事件 → SessionStore.update_task（sub-agent 完成自动回写，无需轮询）；启动时 mark_interrupted_on_startup 崩溃恢复 | main | get_session_store, get_shared_runner, SessionStore.mark_interrupted_on_startup/subscribe |
| `_refresh_session_list` | `() → gr.update` | 查询 SessionStore.list_sessions → Dataframe rows [id,name,status,last_active] | create/switch/delete_session | SessionStore.list_sessions |
| `_refresh_task_list` | `(session_id: str) → gr.update` | 查询 monitor.task_list → Dataframe rows [id前8,type标签,status,progress%,created_at] | create/switch/delete_session/chat, app.load | monitor.task_list |
| `_refresh_trace` | `(session_id, task_id, log_dir="") → (gr.update, gr.update, gr.update)` | 构建 trace 面板：task_detail + 子任务列表 + 决策树轮数 + 层日志尾部 50 行 | create/switch/delete_session/chat/select_task | monitor.task_detail/task_list/decision_tree/log_tail |
| `create_session` | `(name: str) → (state, session_df, task_df, trace_md, trace_json, log)` closure | 新建 SessionStore 记录 + per-layer logging + InteractionEnv → 返回新 SessionState | create_btn.click | SessionStore.create_session, setup_layer_logging, _create_env, _refresh_* |
| `switch_session` | `(evt: SelectData, session_table, current_state) → 6-tuple` closure | 点击 session 行切换：重建 env + 刷新 task/trace | session_table.select | SessionStore.get_session, _create_env, _refresh_* |
| `delete_session` | `(session_table, current_state) → 6-tuple` closure | 删除当前 session + 重置 state | delete_btn.click | SessionStore.delete_session, _refresh_* |
| `chat` | `(user_input, state) → (state, msg, task_df, trace_md, trace_json, log)` closure | 注册 top task → set_task_context → executor.execute → clear_task_context(try/finally) → update_task done/error → env.step | msg.submit, send_btn.click | SessionStore.register_task/update_task/get_session, set_task_context/clear_task_context, executor.execute, env.receive_input/build_task_observation/step, _refresh_* |
| `select_task` | `(evt: SelectData, task_table, state) → (state, trace_md, trace_json, log)` closure | 点击 task 行：短 id 匹配全 id → 刷新 trace | task_table.select | SessionStore.list_tasks/get_session, _refresh_trace |
| `refresh_log` | `(log_dir, layer_choice) → gr.update` closure | 按选中层重读日志尾部 50 行 | log_refresh_btn.click | monitor.log_tail |

## tb/ — Terminal-Bench 评估模块

### tb/session_holder.py

| 函数/类 | 签名 | 作用 | 上游调用者 | 下游调用 |
|----------|------|------|-----------|---------|
| `set` | `(session) → None` | 设置当前 TmuxSession（模块级 global） | CognitiveAgent.perform_task | — |
| `get` | `() → TmuxSession` | 获取当前 session（未设置抛 RuntimeError） | tb_terminal/tb_read_file/tb_grep handlers | — |
| `clear` | `() → None` | 清除当前 session | CognitiveAgent.perform_task | — |

### tb/tools/tb_terminal.py

| 函数/类 | 签名 | 作用 | 上游调用者 | 下游调用 |
|----------|------|------|-----------|---------|
| `register_tb_terminal_tool` | `(registry) → None` | 注册 TB 版 `terminal` 工具（override=True）：`session.send_keys([command, "Enter"], block=True)` → `capture_pane()` | register_tb_tools() | ToolRegistry.register(), session_holder.get() |

### tb/tools/tb_read_file.py

| 函数/类 | 签名 | 作用 | 上游调用者 | 下游调用 |
|----------|------|------|-----------|---------|
| `register_tb_read_file` | `(registry) → None` | 注册 TB 版 `read_file` 工具（override=True）：`wc -l` + `sed -n` 通过 tmux 读取容器内文件 | register_tb_tools() | ToolRegistry.register(), session_holder.get() |
| `_extract_last_int` | `(pane: str) → int` | 从 wc 输出提取最后整数（总行数） | register_tb_read_file handler | — |
| `_extract_command_output` | `(pane: str, command: str) → str` | 从 tmux pane 中提取命令后的实际输出 | register_tb_read_file handler | — |

### tb/tools/tb_grep.py

| 函数/类 | 签名 | 作用 | 上游调用者 | 下游调用 |
|----------|------|------|-----------|---------|
| `register_tb_grep` | `(registry) → None` | 注册 TB 版 `grep` 工具（override=True）：`grep -rn -- pattern path` 通过 tmux 搜索容器内文件 | register_tb_tools() | ToolRegistry.register(), session_holder.get() |

### tb/tools/__init__.py

| 函数/类 | 签名 | 作用 | 上游调用者 | 下游调用 |
|----------|------|------|-----------|---------|
| `register_tb_tools` | `(registry) → None` | 注册所有 TB 专用工具（覆盖 terminal/read_file/grep） | CognitiveAgent._ensure_setup() | register_tb_terminal_tool, register_tb_read_file, register_tb_grep |

### tb/agent/cognitive_agent.py

| 函数/类 | 签名 | 作用 | 上游调用者 | 下游调用 |
|----------|------|------|-----------|---------|
| `CognitiveAgent` | `__init__(**kwargs)` | TB BaseAgent 实现：懒加载 Executor+chain+TB 工具。初始化 `_task_meta=""` | tb run harness | setup_executor(), register_tb_tools() |
| `CognitiveAgent.name` | `() → "cognitive-agent"` | Agent 名称（静态） | harness | — |
| `CognitiveAgent._ensure_setup` | `() → None` | 首次调用时一次性构建：setup_executor + register_tb_tools + apply_learning_context（读 `TB_PHASE` 环境变量控制 train/test 工具集） | perform_task | setup_executor(), register_tb_tools(), tb.env.apply_learning_context() |
| `CognitiveAgent.perform_task` | `(instruction, session, logging_dir) → AgentResult` | 多轮执行循环：保存 `_task_meta` → build_observation → execute → capture_pane → 反馈 → 直到 L1 done 或 max_rounds | tb run harness | Executor.execute(), session_holder.set/clear, TmuxSession.capture_pane() |
| `CognitiveAgent._build_observation` | `(task_meta, feedback, round_idx) → TaskObservation` | 构建 TaskObservation（domain="tb", enable_learning=True） | perform_task | — |
| `CognitiveAgent._log_round` | `(logging_dir, round_idx, result, done, elapsed, tokens) → None` | 写 round_N.json（含 notify 摘要、耗时、token 统计） | perform_task | — |
| `CognitiveAgent._log_summary` | `(logging_dir, round_logs, llm, total_time) → None` | 写 summary.json（含完成时间、总轮次、总 tokens） | perform_task | — |
| `CognitiveAgent._build_feedback_meta` | `(parser_results, is_resolved, exhausted) → str` | 构建反馈阶段 task meta（PASS 反思成功 / FAIL 修复 / EXHAUSTED 反思失败） | receive_test_results | — |
| `CognitiveAgent.receive_test_results` | `(parser_results, is_resolved, exhausted, session, terminal) → None` | 接收 harness 测试结果，驱动 Executor 反思/修复循环（PASS/EXHAUSTED 最多 5 轮，FAIL 修复最多 15 轮） | FeedbackHarness._call_receive_test_results | Executor.execute(), session_holder.set/clear |
| `_trim_pane` | `(pane, max_lines) → str` | 截断终端输出保留最后 N 行 | perform_task, receive_test_results | — |
| `_head` | `(text, n) → str` | 截取文本前 N 字符 | perform_task | — |

### tb/feedback_harness.py

| 函数/类 | 签名 | 作用 | 上游调用者 | 下游调用 |
|----------|------|------|-----------|---------|
| `FeedbackHarness(Harness)` | `__init__(same as Harness)` | Harness 子类，重写 `_run_trial` 插入测试结果反馈循环 | tb/runner.py (monkey-patch) | _run_agent, _run_tests, _parse_results, _is_resolved |
| `FeedbackHarness._run_trial` | `(trial_handler) → TrialResults` | 重写：将 `_parse_results` 移入 container 生命周期内；PASS → agent.receive_test_results；FAIL → 最多 3 轮修复循环 | Harness._execute_tasks → ThreadPoolExecutor | — |
| `FeedbackHarness._call_receive_test_results` | `(task_agent, parser_results, is_resolved, exhausted, session, terminal) → None` | 安全调用 `agent.receive_test_results()`（hasattr 检查 + try/except） | _run_trial | CognitiveAgent.receive_test_results |

### tb/runner.py

| 函数/类 | 签名 | 作用 | 上游调用者 | 下游调用 |
|----------|------|------|-----------|---------|
| `tb.runner (module)` | — | Monkey-patch `terminal_bench.Harness = FeedbackHarness` 后调用 Typer CLI `app()` | tb/run.sh (`python -m tb.runner run`) | FeedbackHarness, terminal_bench.cli.tb.main.app() |

### tb/env.py

| 函数/类 | 签名 | 作用 | 上游调用者 | 下游调用 |
|----------|------|------|-----------|---------|
| `apply_learning_context` | `(chain, enable) → None` | 遍历 chain 所有层 `set_context(ctx)`：enable=True → None（全部工具可用）；enable=False → `AgentContext(denied_tools={record_learning, kb_add, kb_fill_gap})` | CognitiveAgent._ensure_setup（读 `TB_PHASE` 环境变量） | AgentContext, LayerAgent.set_context |

### tb/config/tasks_data.yaml

| 字段 | 作用 |
|------|------|
| `dataset` | TB dataset 名称（terminal-bench-2）|
| `train[]` | 5 道训练任务（log-summary-date-ranges / heterogeneous-dates / gcode-to-text / db-wal-recovery / extract-elf） |
| `test[]` | 3 道测试任务（financial-document-processor / large-scale-text-editing / organization-json-generator） |

### tb/run.sh

| 字段 | 作用 |
|------|------|
| 用法 | `bash tb/run.sh [task_id]` — 不传 task_id 则跑全部 8 道；参数 `TB_DATASET_PATH` 可覆盖数据集路径 |
| --agent-import-path | `tb.agent.cognitive_agent:CognitiveAgent` |
| --dataset-path | 默认 `/tmp/tb-tasks/original-tasks`（需先 `git clone --depth 1 https://github.com/laude-institute/terminal-bench.git /tmp/tb-tasks`）|

### core/llm_client.py (2026-06-23 更新)

| 变化 | 描述 |
|------|------|
| `LLMResponse.prompt_tokens` | 新增字段：每次调用的 prompt token 数 |
| `LLMResponse.completion_tokens` | 新增字段：每次调用的 completion token 数 |
| `LLMResponse.total_tokens` | 新增 property：prompt_tokens + completion_tokens |
| `LLMClient.total_tokens` | 新增 property：所有调用的累积 total tokens |
| `LLMClient.reset_token_counts` | 新增方法：重置累积计数器（每个 task 开始时调用） |
