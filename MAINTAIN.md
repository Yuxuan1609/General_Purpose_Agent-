# Architecture Maintain Doc — cognitive-agent

> 记录所有模块的函数级信息：函数作用、参数签名、上下游调用关系。
> 每次较大修改后即时更新。配合 COOKBOOK.md（概念↔代码映射）使用。

---

## Changelog

| 日期 | 变更 |
|------|------|
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
| `ToolEntry` | `@dataclass(name, schema, handler, sync, check_fn, toolset, available_domains)` | 工具条目数据类，含域名归属及同步/异步标记 | ToolRegistry | — |
| `ToolRegistry` | `__init__(domain_registry=None)` → singleton | 线程安全工具注册中心，支持域名索引 | setup scripts, LayerAgent | DomainRegistry.index_item() |
| `ToolRegistry.register` | `(name, schema, handler, check_fn, toolset, available_domains, override, sync)` | 注册工具，可选同步到 DomainRegistry reverse index | setup scripts | DomainRegistry.index_item() |
| `ToolRegistry.get_definitions` | `(requested=None) → list[dict]` | 获取所有可见工具的 OpenAI schema 列表 | Executor, LayerInjector | — |
| `ToolRegistry.dispatch` | `(name, args, context) → str` | 按名分发工具调用 | ToolCapability | entry.handler() |
| `ToolRegistry.deregister` | `(name)` | 注销工具 | — | — |
| `ToolRegistry.get_tools_for_domain` | `(domain) → list[ToolEntry]` | 按域名过滤工具列表，无 registry 时返回全部 | L2Manager, Executor | DomainRegistry.get_primary_items() |
| `ToolRegistry.clear` | `()` | 重置所有条目（仅测试用） | test fixtures | — |

## core/tools/kb_tools.py

| 函数/类 | 签名 | 作用 | 上游调用者 | 下游调用 |
|----------|------|------|-----------|---------|
| `_ask_user_handler` | `(args) → str` | tkinter 弹窗向用户提问，fallback 到 console input | ToolRegistry.dispatch | tkinter.simpledialog |

## core/tools/async_tools.py

| 函数/类 | 签名 | 作用 | 上游调用者 | 下游调用 |
|----------|------|------|-----------|---------|
| `register_async_tools` | `(registry)` | 注册 check_task 和 collect_tasks 通用异步任务管理工具 | register_all_tools() | ToolRegistry.register() |
| `_check_task_handler` | `(args) → str` | 查询单个异步任务状态 | ToolRegistry.dispatch | TaskRunner.check() |
| `_collect_tasks_handler` | `(args) → str` | 批量收集已完成异步任务的结果 | ToolRegistry.dispatch | TaskRunner.collect(), TaskRunner.pending_tasks() |

## core/tools/consolidation_tools.py

| 函数/类 | 签名 | 作用 | 上游调用者 | 下游调用 |
|----------|------|------|-----------|---------|
| `set_consolidation_stores` | `(phil, fk, sl, reg) → None` | 设置模块级 store 引用，供 handler 访问 | chain_factory.build_default_chain() | — |
| `get_pending_mods` | `() → list[dict]` | 获取并清空所有待处理的 consolidation 修改记录 | L0_5_1Manager.notify(), L2Manager.notify(), L3Manager.notify() | — |
| `register_consolidation_tools` | `(tool_registry) → None` | 注册全部 consolidation 工具（L1 rule/L2 card/L3 skill CRUD + domain ops） | register_all_tools() | ToolRegistry.register() |
| `L1_CONSOLIDATION_TOOL_NAMES` | `set[str]` | L1 consolidation 可用工具名集合 | L1Agent.decide() | ToolRegistry.get_definitions() |
| `L2_CONSOLIDATION_TOOL_NAMES` | `set[str]` | L2 consolidation 可用工具名集合 | L2Agent.decide() | ToolRegistry.get_definitions() |
| `L3_CONSOLIDATION_TOOL_NAMES` | `set[str]` | L3 consolidation 可用工具名集合 | L3Agent.decide() | ToolRegistry.get_definitions() |

## core/domain_registry.py (Task 3)

| 函数/类 | 签名 | 作用 | 上游调用者 | 下游调用 |
|----------|------|------|-----------|---------|
| `DomainRetrieveResult` | `@dataclass(path, depth, correlation, primary_count, explore_count, total_count)` | 单域名检索结果容器 | DomainRegistry.retrieve_from_root() | Executor, L2Manager |
| `DomainNode` | `@dataclass(path, parent, description, correlations, relations)` | 领域树节点 | DomainRegistry | — |
| `DomainRegistry` | `__init__(nodes, embedding_model_path=None, db_path=None)` | 领域注册中心，管理 domain tree + reverse index + embedding（可选 SQLite 后端） | build_chain, seed_knowledge | DomainSQLiteStore (if db_path) |
| `DomainRegistry._load_from_db` | `() → None` | 从 SQLite 加载 nodes + reverse_index 到内存 | __init__ | DomainSQLiteStore.list_nodes(), get_all_index() |
| `DomainRegistry.get_node` | `(path) → DomainNode\|None` | 按路径查找节点 | L2Agent, Executor | — |
| `DomainRegistry.list_all` | `() → list[DomainNode]` | 列出所有节点 | — | — |
| `DomainRegistry.children_of` | `(path) → list[DomainNode]` | 获取直接子节点 | — | — |
| `DomainRegistry.get_primary_items` | `(layer, domain) → list[str]` | 获取某 layer 下某 domain 的主项 ID 列表 | L2Manager, Executor | — |
| `DomainRegistry.get_explore_items` | `(layer, domain, threshold=0.5) → list[str]` | 按关联权重阈值获取相邻 domain 的项 ID | L2Manager, Executor | — |
| `DomainRegistry.get_items_for_domains` | `(layer, domains) → list[str]` | 批量获取多个 domain 的项 ID（去重） | L2Manager, Executor | — |
| `DomainRegistry.retrieve_from_root` | `(root_path, layer, depth, correlation_threshold) → list[DomainRetrieveResult]` | 从 root 递归检索子孙邻域及自身项 | L2Manager | get_primary_items, get_explore_items, children_of |
| `DomainRegistry.save` | `(filepath) → None` | 原子持久化 nodes + reverse_index 到 JSON（db_path 激活时为 no-op） | seed_knowledge | — |
| `DomainRegistry.load` | `(filepath) → DomainRegistry` | 从 JSON 加载注册中心 | build_chain | — |

## core/types.py (NEW in Phase 1)

| 函数/类 | 签名 | 作用 | 上游调用者 | 下游调用 |
|----------|------|------|-----------|---------|
| `TaskObservation` | `@dataclass(meta:str, state:dict, session:dict\|None)` | 环境观测的统一格式（单步）。meta 为自然语言游戏规则 | 通信层脚本 build_prompt() | Executor.execute(), LayerManager.query() |
| `ExecutionRecord` | `@dataclass(session, observation, notify_layers, action, result)` | Execute 后的存档记录，写入 data/learning/pending/ | Executor._write_pending() | LearningEnv |
| `LearningUnit.enable_learning` | `bool = False` | 学习开关，True 时写入知识卡片/规则等 | LearningUnit 定义 | 学习管道 |

## core/task.py

| 函数/类 | 签名 | 作用 | 上游调用者 | 下游调用 |
|----------|------|------|-----------|---------|
| `Domain` | `@dataclass(frozen=True, path:str, level:str)` | 层级领域标识，frozen 可用作 dict key | LearningUnit 定义 | L2 激活计算, L3 技能匹配 |
| `Domain.parent` | `property → Domain\|None` | 返回上一级领域 | L2._domain_match_score() | — |
| `Domain.is_ancestor_of` | `(other:Domain) → bool` | 判断是否祖先领域 | L2._domain_match_score() | — |
| `LearningUnit` | `@dataclass(description, domain, context, needs_decomposition, subtasks, enable_learning, token_count)` | 最小学习单元，1个 Session 可拆为多个。区别于 TaskObservation（单步观测） | AgentRuntime | Executor.execute() |

## core/executor.py (NEW in Phase 1)

| 函数/类 | 签名 | 作用 | 上游调用者 | 下游调用 |
|----------|------|------|-----------|---------|
| `Executor` | `__init__(layer_root, llm_client, learning_dir, max_tokens, temperature)` | 独立决策者，只收不发 | AgentRuntime / 脚本 | LayerManager.query(), LLMClient.chat() |
| `Executor.execute` | `(obs:TaskObservation) → dict{action_text, context, notify_layers}` | 动作周期：LayerMessage(QUERY) 链 → collect_notify → prompt → LLM | DouZeroCognitiveAgent.act() | LayerManager.query(), collect_notify(), _call_llm() |
| `Executor._assemble_context` | `(obs) → dict{meta, state}` | 拼接 obs.meta + obs.state | execute() | _call_llm() |
| `Executor._call_llm` | `(context:dict) → str` | _build_system_prompt + _build_user_prompt → LLM | execute() | LLMClient.chat() |
| `Executor._build_system_prompt` | `(context) → str` | 组装 [任务说明]+[行为准则](state.l1_rules)+[相关知识](state.l2_cards)+[可用技能](state.l3_skills) | _call_llm() | — |
| `Executor._build_user_prompt` | `(context) → str` | 组装 [对局历史]+[当前局面] 从 state 提取 | _call_llm() | — |
| `Executor._write_pending` | `(obs, notify_layers, result) → None` | enable_learning=True 时写 ExecutionRecord 到 pending/ | execute() | 文件系统 |

## config/ (Phase 1.5)

| 文件 | 内容 | 使用者 |
|------|------|--------|
| `config/layers/l1.yaml` | L1 种子规则、max_rules、max_rule_length | Philosophy 初始化 |
| `config/layers/l2.yaml` | L2 激活权重、decay_rate、domain_match 分数 | FlexibleKnowledge 初始化 |
| `config/layers/l3.yaml` | L3 编译阈值、技能匹配分数 | SkillLayer 初始化 |

## core/layers/comm.py (Phase 1.5)

| 函数/类 | 签名 | 作用 | 上游调用者 | 下游调用 |
|----------|------|------|-----------|---------|
| `AgentPacket` | `@dataclass(frozen, source_layer, message_type, content)` | 层内 Agent 通信包，承载在 LayerMessage.payload 中运输 | L1Agent / L2Agent | Comm Agents 包装/解包 |
| `UpwardComm` | `receive(msg)→dict` / `wrap_response(...)→LayerMessage` / `wrap_notify(...)→LayerMessage` | 确定性协议处理：LayerMessage ↔ 业务 dict | LayerManager.query() | — |
| `DownwardComm` | `receive(msg)→dict` / `wrap_query(...)→LayerMessage` | 确定性协议处理：LayerMessage ↔ 业务 dict | LayerManager.query() | 下层 UpwardComm |

## core/layers/base.py (Phase 1)

| 函数/类 | 签名 | 作用 | 上游调用者 | 下游调用 |
|----------|------|------|-----------|---------|
| `LayerAgent` | `__init__(llm_client, log)` | ABC，所有层 LLM Agent 基类。含 `_pending_mods`、`_injector` 属性。 | L1Agent, L2Agent | — |
| `LayerAgent._call_llm` | `(system, user, schema=None, tools=None, layer="", capture_tools=None) → dict` | 多轮 tool call 循环 + json_mode + robust_parse。`capture_tools` 将指定 tool 的 arguments 直接作为结构化输出返回，替代 JSON-in-prompt。 | L1/L2/L3 decide() | LLMClient.chat(), robust_parse(), injector.execute_tool_call() |
| `LayerAgent._schema_to_tool` | `(name, description, schema) → dict` | 将 JSON Schema 转为 OpenAI function-calling tool 定义，供 capture_tools 使用。 | L1/L2/L3 decide() | — |
| `LayerAgent._get_tools` | `(layer) → list[dict]\|None` | 从 injector 获取该层可见工具 schema 列表。 | L1/L2/L3 decide() | injector.get_tools_for_layer() |
| `LayerAgent.set_injector` | `(injector) → None` | 注入 LayerInjector 以启用工具调用。 | chain_factory._mount_tools() | — |
| `LayerAgent.get_pending_mods` | `() → list[dict]` | (legacy, unused) 获取并清空待处理的 consolidation 修改记录。已迁移到 consolidation_tools.get_pending_mods()。 | — | — |
| `LayerAgent.decide` | `(**kwargs) → dict` (abstract) | 单步决策，各层自行实现。Manager while 循环调用。 | Manager query() while 循环 | _call_llm(), _schema_to_tool() |
| `DictInjector` | `__init__(handlers: dict[str, callable])` | (deprecated, dead code) 轻量工具注入器。Consolidation 已迁移到 ToolRegistry (consolidation_tools.py)。 | — | — |
| `LayerManager` | `__init__(name, downstream, upward, downward)` | ABC，所有层 Manager 的基类。upward/downward 为 Comm Agent | build_chain() | 子类 |
| `LayerManager.process` | `(data:Any) → dict` (abstract) | 本层业务逻辑：富化 data 并返回状态 | query() | — |
| `LayerManager.notify` | `() → Any` (abstract) | 返回本层的 NOTIFY payload | collect_notify() | — |
| `LayerManager.query` | `(msg:LayerMessage\|Any, trace_id) → None` | QUERY 入口：通过 UpwardComm 解包 → process → DownwardComm 包装 → 下游 | Executor / 上层 | process(), downstream.query() |
| `LayerManager.collect_notify` | `() → dict{layer_name: payload}` | 收集本层+所有下游的 NOTIFY | Executor.execute() | notify(), 下游.collect_notify() |

## core/layers/l0_5_1/upward_comm.py, downward_comm.py (Phase 1.5)

| 函数/类 | 签名 | 作用 | 上游调用者 | 下游调用 |
|----------|------|------|-----------|---------|
| `UpwardComm` | extends `comm.UpwardComm` | L0.5+1→Executor 通信 | Executor | L0_5_1Manager |
| `DownwardComm` | extends `comm.DownwardComm` | L0.5+1→L2 通信 | L0_5_1Manager | L2 UpwardComm |

## core/layers/l2/upward_comm.py, downward_comm.py (Phase 1.5)

| 函数/类 | 签名 | 作用 | 上游调用者 | 下游调用 |
|----------|------|------|-----------|---------|
| `UpwardComm` | extends `comm.UpwardComm` | L2→L0.5+1 通信 | L0_5_1 DownwardComm | L2Manager |
| `DownwardComm` | extends `comm.DownwardComm` | L2→L3 通信 | L2Manager | L3 UpwardComm |

## core/layers/l3/upward_comm.py, downward_comm.py (Phase 1.5)

| 函数/类 | 签名 | 作用 | 上游调用者 | 下游调用 |
|----------|------|------|-----------|---------|
| `UpwardComm` | extends `comm.UpwardComm` | L3→L2 通信 | L2 DownwardComm | L3Manager |
| `DownwardComm` | extends `comm.DownwardComm` | L3→L4 通信（预留） | L3Manager | — |

## core/layers/l3/manager.py (Phase 1 + Phase 2a)

| 函数/类 | 签名 | 作用 | 上游调用者 | 下游调用 |
|----------|------|------|-----------|---------|
| `L3Manager` | `__init__(skill_layer, downstream, upward, downward, auxiliary_llm)` | L3 层 Manager，包裹 SkillLayer + L3Agent | build_chain() | — |
| `L3Manager.query` | `(msg, trace_id) → None` | 确定性匹配技能 → while 循环 decide() 决策执行 | L2Manager._propagate | SkillLayer.match(), L3Agent.decide() |
| `L3Manager.process` | `(obs) → dict` | stub，实际逻辑在 query() | LayerManager.query() | — |
| `L3Manager.notify` | `() → dict` | 返回 `{skills_matched, skills_used, result, reasoning}` | collect_notify() | — |
| `L3Agent` | `__init__(llm_client, skill_layer=None, domain_registry=None)` | L3 LLM Agent：基于匹配技能执行认知任务 | L3Manager.query() | — |
| `L3Agent.decide` | `(meta, state, context, tools, layer) → dict{done, result, skills_used, reasoning}` | 单步决策：通过 capture_tool（l3_continue/l3_report）输出；`l3_output_format` 时从 ToolRegistry 获取 consolidation 工具 schema。 | L3Manager.query() | _call_llm(), _schema_to_tool(), ToolRegistry.get_definitions() |

## core/layers/l2/manager.py (Phase 1)

| 函数/类 | 签名 | 作用 | 上游调用者 | 下游调用 |
|----------|------|------|-----------|---------|
| `L2Manager` | `__init__(knowledge, downstream, upward, downward, auxiliary_llm)` | L2 层 Manager，包裹 FlexibleKnowledge + L2Agent | build_chain() | — |
| `L2Manager.query` | `(msg, trace_id) → None` | while 循环 + decide() → propagate queries_to_L3 → 收集 NOTIFY | L0_5_1 DownwardComm | L2Agent.decide(), _propagate(), collect_notify() |
| `L2Manager.notify` | `() → dict` | 返回 `{reply, cards, reasoning}` | collect_notify() | — |
| `L2Manager._propagate` | `(obs, trace_id) → None` | 包装 LayerMessage(QUERY) 发送到 L3 | query() | L3Manager.query() |
| `L2Agent` | `__init__(llm_client, knowledge)` | L2 层 LLM Agent，while-loop 决策 | L2Manager | — |
| `L2Agent.decide` | `(query, meta, state, context, tools, layer) → dict{done, reply, selected_nodes, selected_cards, queries_to_L3, reasoning}` | 单步决策：通过 capture_tool（l2_query/l2_report）输出；`l2_output_format` 时从 ToolRegistry 获取 consolidation 工具 schema。 | L2Manager.query() | _get_cards_for_nodes(), _call_llm(), _schema_to_tool(), ToolRegistry.get_definitions() |
| `L2Agent._get_cards_for_nodes` | `(nodes) → list[KnowledgeCard]` | 按节点 domain 检索知识卡片 | decide() | FlexibleKnowledge.get_domain_cards() |

## core/layers/l0_5_1/manager.py (Phase 1)

| 函数/类 | 签名 | 作用 | 上游调用者 | 下游调用 |
|----------|------|------|-----------|---------|
| `L0_5_1Manager` | `__init__(meta_driver, philosophy, auxiliary_llm, downstream, upward, downward, domain_registry, max_rounds, knowledge_stores)` | L(0.5+1) 层 Manager，包裹 MetaDriver + Philosophy | build_chain() | — |
| `L0_5_1Manager.query` | `(msg, trace_id) → None` | while 循环调用 decide() → propagate queries 到 L2 → 收集 NOTIFY | Executor / 上层 | self._agent.decide(), self._downward.wrap_query(), collect_notify() |
| `L0_5_1Manager.notify` | `() → dict` | 返回 `{done, result, reasoning}` 或 `{status:"ok"}` | collect_notify() | — |
| `L0_5_1Manager.process` | `(data) → dict` | 返回 `{status:"ok", layer:"l0_5_1"}` | LayerManager.query() | — |
| `L1Agent` | `__init__(llm_client, philosophy, domain_registry, knowledge_stores)` | L1 层 LLM Agent，while-loop 决策 | L0_5_1Manager | — |
| `L1Agent.decide` | `(meta, state, history, tools, layer) → dict{done, result, queries, reasoning}` | 单步决策：通过 capture_tool（l1_query/l1_report）输出；`l1_output_format` 时从 ToolRegistry 获取 consolidation 工具 schema。 | L0_5_1Manager.query() | _build_system_prompt(), _build_user_context(), _call_llm(), _schema_to_tool(), ToolRegistry.get_definitions() |
| `L1Agent._build_system_prompt` | `(instruction, meta) → str` | 注入游戏规则 + 行为准则(L1 rules) + 任务目标 | stage1/stage2 | Philosophy.all_rules() |
| `L1Agent._build_user_context` | `(state) → str` | 拼接 [当前局面] + [对局历史] | stage1/stage2 | — |

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
| `_seed_l3_skills` | `(sl) → None` | 创建 leduc + doudizhu 的 L3 技能(含 relevance_domain) | _seed_knowledge() | SkillLayer.create_skill() |
| `_setup_logging` | `() → log_dir` | 创建 per-agent 文件日志(l0_5_1.log, l2.log, l3.log, executor.log) | main() | logging |

## core/layers/__init__.py

| 函数/类 | 签名 | 作用 | 上游调用者 | 下游调用 |
|----------|------|------|-----------|---------|
| `build_chain` | `(meta_driver, philosophy, flexible_knowledge, skill_layer, auxiliary_llm, domain_registry, knowledge_stores) → L0_5_1Manager` | 自底向上构建三层链：L3 → L2 → L(0.5+1) | AgentRuntime / 脚本 | L3Manager(), L2Manager(), L0_5_1Manager() |
| `_make_content_getter` | `(fk, sl) → Callable[[str, str], list[str]]` | 构造 content_getter 闭包，供 DomainRegistry.compute_embedding 使用 | chain_factory 内部 | fk.cards, sl._skills |

## core/meta_driver.py

| 函数/类 | 签名 | 作用 | 上游调用者 | 下游调用 |
|----------|------|------|-----------|---------|
| `MetaDriver` | `__init__(validation_rules, auxiliary_llm, max_rules, max_rule_length)` | L0.5 验证器 + 安全过滤 | L0_5_1Manager, build_chain | — |
| `MetaDriver.validate_l1_change` | `(proposal, existing_rules) → tuple[bool, str]` | 检查 not_duplicate + no_contradiction + under_limit + under_length | LearningEnv._apply_l1() | ValidationRule.check_fn |
| `MetaDriver.filter_dangerous` | `(tool_calls:list) → list` | 过滤危险工具调用 | — | — |
| `MetaDriver.check_completion` | `(task, messages) → str` | 判断任务完成 ("done"/"continue") | — | — |
| `ValidationRule` | `@dataclass(id, description, check_fn)` | 验证规则容器 | DEFAULT_VALIDATORS | MetaDriver |
| `DEFAULT_VALIDATORS` | `list[ValidationRule]` | 默认验证器 (not_duplicate, no_contradiction) | build_chain, tests | — |
| `L1ProposalProxy` | `__init__(content, reason, domain)` | L1Proposal 轻量代理 | — | — |

## core/philosophy.py (已有，层内部使用)

| 函数/类 | 签名 | 作用 | 上游调用者 | 下游调用 |
|----------|------|------|-----------|---------|
| `Philosophy` | `__init__(rules_path, max_rules, max_rule_length)` | L1 可演化行为规则管理（source="l0_5"不可变，"l1"可变） | L0_5_1Manager | — |
| `Philosophy.all_rules` | `() → list[Rule]` | 返回所有规则（L0.5 + L1） | L1Agent._build_system_prompt | — |
| `Philosophy.l1_rules` | `() → list[Rule]` | 仅返回 L1 可变规则 | Verifier, test | — |
| `Philosophy.l0_5_rules` | `() → list[Rule]` | 仅返回 L0.5 不可变宪法 | — | — |
| `Philosophy.add_rule` | `(content, created_by, source="l1") → Rule` | 添加新规则 | seed, L0_5_1Manager | _save() |
| `Philosophy.modify_rule` | `(rule_id, new_content) → Rule` | 修改规则（拒绝L0.5） | L0_5_1Manager | _save() |
| `Philosophy.remove_rule` | `(rule_id) → None` | 删除规则（拒绝L0.5） | L0_5_1Manager | _save() |

## core/flexible_knowledge.py (已有，层内部使用)

| 函数/类 | 签名 | 作用 | 上游调用者 | 下游调用 |
|----------|------|------|-----------|---------|
| `FlexibleKnowledge` | `__init__(knowledge_dir, index_path, domain_registry=None, db_path=None)` | L2 知识卡片管理（可选 SQLite 后端） | L2Manager | L2SQLiteStore (if db_path) |
| `FlexibleKnowledge.get_active_cards` | `(domain, context, top_k) → list[KnowledgeCard]` | 按激活值排序返回 top-k 活跃卡片 | L2Manager.process() | KnowledgeCard.compute_activation() |
| `FlexibleKnowledge.get_domain_cards` | `(domain) → list[KnowledgeCard]` | 返回指定 domain 下所有卡片 | L2Agent | — |
| `FlexibleKnowledge._load_cards_from_files` | `() → list[KnowledgeCard]` | 文件模式加载卡片（当前返回空） | __init__ | — |
| `FlexibleKnowledge._load_cards_from_db` | `() → list[KnowledgeCard]` | 从 SQLite 加载全部卡片为内存对象 | __init__ | L2SQLiteStore.list_all() |
| `FlexibleKnowledge.add_card` | `(content, domain, sub_tags, source, available_domains) → KnowledgeCard` | 新增卡片（内存 + SQLite） | seed, L2Manager | L2SQLiteStore.insert() |
| `FlexibleKnowledge.remove_card` | `(card_id) → bool` | 删除卡片（内存 + SQLite） | L2Manager | L2SQLiteStore.delete() |
| `FlexibleKnowledge.modify_card` | `(card_id, new_content, usefulness, misleading, comment) → KnowledgeCard\|None` | 修改卡片（内存 + SQLite） | L2Manager | L2SQLiteStore.update() |

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
| `SkillLayer.create_skill` | `(name, content, domain, ...) → SkillMeta` | 创建新技能（内存 + SQLite） | L3Manager | L3SQLiteStore.insert() |
| `SkillLayer.edit_skill` | `(name, new_content, usefulness, misleading, comment) → SkillMeta` | 更新技能内容/质量字段（内存 + SQLite） | L3Manager | L3SQLiteStore.update() |
| `SkillLayer.delete_skill` | `(name) → None` | 软删除技能（移到.archive + SQLite） | L3Manager | L3SQLiteStore.delete() |
| `SkillLayer.touch_skill` | `(name) → None` | 标记技能最近使用（更新 last_used） | L3Manager.query() | — |
| `SkillLayer.should_create_skill` | `(domain, cards) → bool` | 检查 L2→L3 编译条件 | Phase 2: Reflect | — |
| `SkillLayer.propose_and_create` | `(domain, cards, llm) → SkillMeta\|None` | LLM 编译知识卡片为 SKILL.md | Phase 2: Reflect | — |

## core/env/learning_env.py (Phase 2.1)

| 函数/类 | 签名 | 作用 | 上游调用者 | 下游调用 |
|----------|------|------|-----------|---------|
| `LearningEnv` | `__init__(pending_dir, knowledge_stores, preprocessing_llm, stats_file, ..., domain_registry=None)` | 学习环境：消费 ExecutionRecords，产出知识变更，与 GameEnv 共享 Executor+LayerChain | run_leduc_cognitive.py | ThresholdScorer, Philosophy，FlexibleKnowledge，SkillLayer, DomainRegistry |
| `LearningEnv.reset` | `(task_description) → EnvState` | 扫描 pending/ records，构建 observation | orchestrator | _scan_pending(), _build_learning_units() |
| `LearningEnv.step` | `(action) → EnvStep` | 解析 NOTIFY layers → 验证 → 应用修改 → 记录统计 | Executor | _parse_notify_layers(), _apply_layer_mod() |
| `LearningEnv.build_task_observation` | `() → TaskObservation` | 构建 TaskObservation 供 Executor+Layers 消费 | run_leduc_cognitive.py | — |
| `LearningEnv.build_consolidation_task` | `() → TaskObservation\|None` | L2/L3 超限时构建整理任务 | orchestrator | — |
| `LearningEnv.archive_pending` | `() → int` | 移动已处理 records 到 learned/ | run_leduc_cognitive.py | — |

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
| `ThresholdScorer.domain_health_report` | `(registry, l2_store, l3_store) → str` | 构建 domain 健康报告 Markdown 表格（card/skill 计数、correlation、状态） | LearningEnv.build_consolidation_task | DomainRegistry.list_all(), _reverse_index |

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
| `DEFAULT_TOOL_ALLOWLIST` | `dict[str, set[str]]` | L1={todo}, L2={todo,terminal,read_file,grep}, L3=full | ToolCapability.__init__ | — |

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
| `LayerAgent._call_llm` | `(system, user, schema, tools, layer, capture_tools) → dict` | **增强**：新增 `capture_tools` 参数；多轮 tool call 循环（MAX_TOOL_TURNS=5）；tools 存在时自动禁用 json_mode；**sync/async dispatch**：按 tool_call args 中 `sync` 参数拆分为 sync_batch（run_sync_batch）和 async_calls（TaskRunner.submit），async 立即返回 task_id | L1/L2/L3 decide() | LLMClient.chat(), robust_parse(), injector.execute_tool_call(), TaskRunner.submit() |
| `LayerAgent._schema_to_tool` | `(name, description, schema) → dict` | **新增**：JSON Schema → OpenAI function-calling tool 定义，供 capture_tools 模式使用。 | decide() | — |
| `DictInjector` | `__init__(handlers: dict[str, callable])` | (deprecated, dead code) 已被 consolidation_tools.py + ToolRegistry 替代。 | — | — |

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

## config/layers/consolidation.yaml — Phase 3 新增

| 功能 | 描述 |
|------|------|
| 各层条目规格 | L1 Rule / L2 KnowledgeCard / L3 Skill 的字段定义（名称、类型、长度、ID 格式、required） |
| 容量限制 | soft/hard 两级，per-domain 细分 |
| Anti-patterns | 各层应避免的内容模式（重复、过于泛化、低置信度等） |
| 自动衰减规则 | activation < 0.1 + 30天 → deprecated；90天 → archive |
| 三级整理策略 | Level 0（无）/ Level 1（例行归并，可回滚）/ Level 2（深度压缩，需审核） |

---

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
