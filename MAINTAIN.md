# Architecture Maintain Doc — cognitive-agent

> 记录所有模块的函数级信息：函数作用、参数签名、上下游调用关系。
> 每次较大修改后即时更新。配合 COOKBOOK.md（概念↔代码映射）使用。

---

## Changelog

| 日期 | 变更 |
|------|------|
| 2026-06-05 | **Phase 2.3 清理**：删除所有旧 Reflection 系统 + `MetaDriver` 旧触发器。迁移 `ThresholdScorer`。 |

---

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
| `LayerAgent` | `__init__(llm_client, log)` | ABC，所有层 LLM Agent 基类。DeepSeek JSON mode 统一调用 + 日志 | L1Agent, L2Agent | LLMClient.chat(json_mode=True) |
| `LayerAgent._call_llm` | `(system, user, schema) → dict` | 注入 JSON schema 到 system prompt → LLM → json.loads 解析 | L1/L2 stage 方法 | LLMClient.chat() |
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
| `L3Manager.query` | `(msg, trace_id) → None` | 确定性匹配技能 → L3Agent(LLM) 选择+执行 → 存储结果 | L2Manager._propagate | SkillLayer.match(), L3Agent.execute() |
| `L3Manager.process` | `(obs) → dict` | stub，实际逻辑在 query() | LayerManager.query() | — |
| `L3Manager.notify` | `() → dict` | 返回 `{skills_matched, skills_used, result, reasoning}` | collect_notify() | — |
| `L3Agent` | `__init__(llm_client)` | L3 LLM Agent：基于匹配技能执行认知任务 | L3Manager.query() | — |
| `L3Agent.execute` | `(meta, state) → dict{skills_used, result, reasoning}` | 选择相关技能 + 基于技能推理 + 产出执行结果 | L3Manager.query() | _call_llm() |

## core/layers/l2/manager.py (Phase 1)

| 函数/类 | 签名 | 作用 | 上游调用者 | 下游调用 |
|----------|------|------|-----------|---------|
| `L2Manager` | `__init__(knowledge, downstream, upward, downward, auxiliary_llm)` | L2 层 Manager，包裹 FlexibleKnowledge + L2Agent | build_chain() | — |
| `L2Manager.query` | `(msg, trace_id) → None` | 重写：驱动 V-structure 循环 (Stage1→Stage2→propagate→Stage3) | L0_5_1 DownwardComm | L2Agent.stage1/2/3(), _propagate() |
| `L2Manager.notify` | `() → dict` | 返回 `{reply, cards, reasoning}` | collect_notify() | — |
| `L2Manager._enrich_cards` | `(obs, selected_nodes) → None` | 从 selected_nodes 提取知识卡片写入 obs.state["l2_cards"] | query() | FlexibleKnowledge.get_domain_cards() |
| `L2Manager._propagate` | `(obs, trace_id) → None` | 包装 LayerMessage(QUERY) 发送到 L3 | query() | L3Manager.query() |
| `L2Agent` | `__init__(llm_client, knowledge, domain_nodes)` | L2 层 LLM Agent，三阶段 V-structure | L2Manager | — |
| `L2Agent.stage1` | `(query, meta, state) → list[dict]` | 对 domain nodes 打分，选 top-5 | L2Manager.query() | _call_llm() |
| `L2Agent.stage2` | `(query, meta, state, selected_nodes) → dict` | 筛选知识卡片(≤15)，判断是否调 L3 | L2Manager.query() | _get_cards_for_nodes(), _call_llm() |
| `L2Agent.stage3` | `(query, meta, state, selected_nodes, stage2_result) → dict` | 整合 L3 响应 + 上下文 → 最终 NOTIFY | L2Manager.query() | _get_cards_for_nodes(), _call_llm() |
| `L2Agent._get_cards_for_nodes` | `(nodes) → list[KnowledgeCard]` | 按节点 domain 检索知识卡片 | stage2/stage3 | FlexibleKnowledge.get_domain_cards() |
| `L2_DOMAIN_NODES` | `list[dict{name, description}]` | 硬编码 seed 领域节点 (game/leduc, game/doudizhu) | L2Agent.stage1 | — |

## core/layers/l0_5_1/manager.py (Phase 1)

| 函数/类 | 签名 | 作用 | 上游调用者 | 下游调用 |
|----------|------|------|-----------|---------|
| `L0_5_1Manager` | `__init__(meta_driver, philosophy, auxiliary_llm, downstream, upward, downward)` | L(0.5+1) 层 Manager，包裹 MetaDriver + Philosophy | build_chain() | — |
| `L0_5_1Manager.query` | `(msg, trace_id) → None` | 重写：驱动 V-structure 循环 (Stage1→传给L2→Stage2) | Executor / 上层 | L1Agent.stage1(), downward.wrap_query(), L1Agent.stage2() |
| `L0_5_1Manager.notify` | `() → dict` | 返回 `{done, result, reasoning}` 或 `{status:"ok"}` | collect_notify() | — |
| `L0_5_1Manager.process` | `(data) → dict` | 返回 `{status:"ok", layer:"l0_5_1"}` | LayerManager.query() | — |
| `L1Agent` | `__init__(llm_client, philosophy)` | L1 层 LLM Agent，两阶段 V-structure | L0_5_1Manager | — |
| `L1Agent.stage1` | `(meta, state) → str` | 判断"需要从下层获取什么知识" → query text | L0_5_1Manager.query() | _build_system_prompt(), _build_user_context(), _call_llm() |
| `L1Agent.stage2` | `(meta, state) → dict{done, result, reasoning}` | 整合 L2 知识卡片 + 行为准则 → 最终决策 | L0_5_1Manager.query() | _build_system_prompt(), _build_user_context(), _call_llm() |
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
| `build_chain` | `(meta_driver, philosophy, flexible_knowledge, skill_layer, auxiliary_llm) → L0_5_1Manager` | 自底向上构建三层链：L3 → L2 → L(0.5+1) | AgentRuntime / 脚本 | L3Manager(), L2Manager(), L0_5_1Manager() |

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
| `FlexibleKnowledge` | `__init__(knowledge_dir, index_path)` | L2 知识卡片管理 | L2Manager | — |
| `FlexibleKnowledge.get_active_cards` | `(domain, context, top_k) → list[KnowledgeCard]` | 按激活值排序返回 top-k 活跃卡片 | L2Manager.process() | KnowledgeCard.compute_activation() |
| `FlexibleKnowledge.get_domain_cards` | `(domain) → list[KnowledgeCard]` | 返回指定 domain 下所有卡片 | L2Agent | — |
| `FlexibleKnowledge.add_card` | `(content, domain, confidence, source) → KnowledgeCard` | 新增卡片（仅内存） | seed, L2Manager | — |
| `FlexibleKnowledge.remove_card` | `(card_id) → bool` | 删除卡片 | L2Manager | — |
| `FlexibleKnowledge.modify_card` | `(card_id, new_content) → KnowledgeCard\|None` | 修改卡片内容 | L2Manager | — |
| `KnowledgeCard.boost` | `() → None` | **TODO: 机制待定，勿在反射中使用** | — | — |
| `KnowledgeCard.penalize` | `() → None` | **TODO: 机制待定，勿在反射中使用** | — | — |

## core/skill_layer.py (已有，层内部使用)

| 函数/类 | 签名 | 作用 | 上游调用者 | 下游调用 |
|----------|------|------|-----------|---------|
| `SkillLayer` | `__init__(skills_dir, tool_registry)` | L3 技能管理 | L3Manager | — |
| `SkillLayer.match` | `(domain) → list[SkillMeta]` | 按 domain 匹配技能 | L3Manager.query() | — |
| `SkillLayer.create_skill` | `(name, content, domain, ...) → SkillMeta` | 创建新技能 | L3Manager | 写 SKILL.md |
| `SkillLayer.edit_skill` | `(name, new_content) → SkillMeta` | 更新技能内容 | L3Manager | 写 SKILL.md |
| `SkillLayer.delete_skill` | `(name) → None` | 软删除技能（移到.archive） | L3Manager | — |
| `SkillLayer.should_create_skill` | `(domain, cards) → bool` | 检查 L2→L3 编译条件 | Phase 2: Reflect | — |
| `SkillLayer.propose_and_create` | `(domain, cards, llm) → SkillMeta\|None` | LLM 编译知识卡片为 SKILL.md | Phase 2: Reflect | — |

## core/env/learning_env.py (Phase 2.1)

| 函数/类 | 签名 | 作用 | 上游调用者 | 下游调用 |
|----------|------|------|-----------|---------|
| `LearningEnv` | `__init__(pending_dir, knowledge_stores, preprocessing_llm, stats_file)` | 学习环境：消费 ExecutionRecords，产出知识变更，与 GameEnv 共享 Executor+LayerChain | run_leduc_cognitive.py | ThresholdScorer, Philosophy，FlexibleKnowledge，SkillLayer |
| `LearningEnv.reset` | `(task_description) → EnvState` | 扫描 pending/ records，构建 observation | orchestrator | _scan_pending(), _build_learning_units() |
| `LearningEnv.step` | `(action) → EnvStep` | 解析 NOTIFY layers → 验证 → 应用修改 → 记录统计 | Executor | _parse_notify_layers(), _apply_layer_mod() |
| `LearningEnv.build_task_observation` | `() → TaskObservation` | 构建 TaskObservation 供 Executor+Layers 消费 | run_leduc_cognitive.py | — |
| `LearningEnv.build_consolidation_task` | `() → TaskObservation\|None` | L2/L3 超限时构建整理任务 | orchestrator | — |
| `LearningEnv.archive_pending` | `() → int` | 移动已处理 records 到 learned/ | run_leduc_cognitive.py | — |

## core/env/threshold_scorer.py (Phase 2.3 — 从 core/orchestrator/ 迁移)

| 函数/类 | 签名 | 作用 | 上游调用者 | 下游调用 |
|----------|------|------|-----------|---------|
| `ThresholdScorer` | `__init__(pending_dir, task_count_weight, complexity_weight, baseline_tokens, threshold)` | 按 domain 计算 pending records 的学习触发分数 | LearningEnv, run_leduc_cognitive.py | — |
| `ThresholdScorer.score` | `(domain) → float` | 计算某 domain 的分数 (count + tokens) | should_trigger() | _domain_records() |
| `ThresholdScorer.should_trigger` | `(domain) → bool` | 判断是否达到学习触发阈值 | run_leduc_cognitive.py | score() |
| `ThresholdScorer.domain_count` | `(domain) → int` | 返回某 domain 的 pending records 数量 | test | _domain_records() |

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
