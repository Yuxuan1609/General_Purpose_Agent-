# Architecture Maintain Doc — cognitive-agent

> 记录所有模块的函数级信息：函数作用、参数签名、上下游调用关系。
> 每次较大修改后即时更新。配合 COOKBOOK.md（概念↔代码映射）使用。

---

## core/types.py (NEW in Phase 1)

| 函数/类 | 签名 | 作用 | 上游调用者 | 下游调用 |
|----------|------|------|-----------|---------|
| `TaskObservation` | `@dataclass(meta:dict, state:dict, history:list\|None, session:dict\|None)` | 环境观测的统一格式。session={id,datetime,task_type,meta_hash} | 通信层脚本 build_prompt() | Executor.execute(), LayerManager.process() |
| `ExecutionRecord` | `@dataclass(session:dict, observation:dict, notify_layers:dict, action:Any, result:Any)` | Execute 后的存档记录，写入 data/learning/pending/ | Executor._write_pending() | ReflectCoordinator.audit(), ThresholdScorer |
| `Task.enable_learning` | `bool = False` | 学习开关，手动开启。True 时 Executor 写 pending/ | Task 定义 | Executor.execute() |

## core/task.py

| 函数/类 | 签名 | 作用 | 上游调用者 | 下游调用 |
|----------|------|------|-----------|---------|
| `Domain` | `@dataclass(frozen=True, path:str, level:str)` | 层级领域标识，frozen 可用作 dict key | Task 定义 | L2 激活计算, L3 技能匹配 |
| `Domain.parent` | `property → Domain\|None` | 返回上一级领域 | L2._domain_match_score() | — |
| `Domain.is_ancestor_of` | `(other:Domain) → bool` | 判断是否祖先领域 | L2._domain_match_score() | — |
| `Task` | `@dataclass(description, domain, context, needs_decomposition, subtasks, enable_learning)` | 最小学习单元 | AgentRuntime, TaskDecomposer | Executor.execute() |
| `TaskResult` | `@dataclass(success, final_response, new_knowledge_cards, l1_changes, l1_rejections, new_skills, iterations_used, summary, eval_result, eval_score)` | 任务完成结果 | AgentLoop.reflect() | 调用者统计 |
| `TaskContext` | `@dataclass(task, consecutive_no_progress, eval_result, rounds)` | Execute 阶段的可变上下文 | AgentLoop.run() | MetaDriver.evaluate_triggers() |

## core/executor.py (NEW in Phase 1)

| 函数/类 | 签名 | 作用 | 上游调用者 | 下游调用 |
|----------|------|------|-----------|---------|
| `Executor` | `__init__(layer_root, llm_client, learning_dir, max_tokens, temperature)` | 独立决策者，不在层体系内 | AgentRuntime / 脚本 | LayerManager.query(), LLMClient.chat() |
| `Executor.execute` | `(obs:TaskObservation) → dict{action_text, context, notify_layers}` | 执行一次完整动作周期：QUERY 链 → NOTIFY → prompt → LLM | DouZeroCognitiveAgent.act() | LayerManager.query(), collect_notify(), _call_llm() |
| `Executor._assemble_context` | `(obs:TaskObservation) → dict` | 拼接各层富化后的 meta/state/history | execute() | _call_llm() |
| `Executor._call_llm` | `(context:dict) → str` | 组装 system+user prompt，调 LLM | execute() | LLMClient.chat() |
| `Executor._build_system_prompt` | `(context:dict) → str` | 从 context.meta 提取 L1 规则/L2 卡片/L3 技能拼 system prompt | _call_llm() | — |
| `Executor._build_user_prompt` | `(context:dict) → str` | 从 context.state 拼 user prompt | _call_llm() | — |
| `Executor._write_pending` | `(obs, notify_layers, result) → None` | enable_learning=True 时写 ExecutionRecord 到 pending/ | execute() | 文件系统 |

## config/ (Phase 1.5)

| 文件 | 内容 | 使用者 |
|------|------|--------|
| `config/l1.yaml` | L1 种子规则、max_rules、max_rule_length | Philosophy 初始化 |
| `config/l2.yaml` | L2 激活权重、decay_rate、domain_match 分数 | FlexibleKnowledge 初始化 |
| `config/l3.yaml` | L3 编译阈值、技能匹配分数 | SkillLayer 初始化 |

## core/layers/comm.py (Phase 1.5)

| 函数/类 | 签名 | 作用 | 上游调用者 | 下游调用 |
|----------|------|------|-----------|---------|
| `UpwardComm` | `receive(msg)→dict` / `wrap_response(...)→LayerMessage` / `wrap_notify(...)→LayerMessage` | 确定性协议处理：LayerMessage ↔ 业务 dict | LayerManager.query() | — |
| `DownwardComm` | `receive(msg)→dict` / `wrap_query(...)→LayerMessage` | 确定性协议处理：LayerMessage ↔ 业务 dict | LayerManager.query() | 下层 UpwardComm |

## core/layers/base.py (NEW in Phase 1)

| 函数/类 | 签名 | 作用 | 上游调用者 | 下游调用 |
|----------|------|------|-----------|---------|
| `LayerManager` | `__init__(name, downstream, upward, downward)` | ABC，所有层 Manager 的基类。upward/downward 为 Comm Agent | build_chain() | 子类 |
| `LayerManager.process` | `(data:Any) → dict` (abstract) | 本层业务逻辑：富化 data 并返回状态 | query() | — |
| `LayerManager.notify` | `() → Any` (abstract) | 返回本层的 NOTIFY payload | collect_notify() | — |
| `LayerManager.query` | `(msg:LayerMessage\|Any, trace_id) → None` | QUERY 入口：通过 UpwardComm 解包 → process → DownwardComm 包装 → 下游 | Executor / 上层 | process(), downstream.query() |
| `LayerManager.collect_notify` | `() → dict{layer_name: payload}` | 收集本层+所有下游的 NOTIFY | Executor.execute() | notify(), 下游.collect_notify() |
| `LayerManager.apply_update` | `(key:str, value) → None` | Phase 2: ReflectionAgent 修复时写回数据 | ReflectionAgent.fix() | 子类实现 |
| `ReflectionAgent` | `__init__(layer_name, manager, downstream)` | Phase 2: 反思编排 Agent ABC | ReflectCoordinator.run_reflect() | investigate(), fix(), query_downstream() |
| `ReflectionAgent.investigate` | `(issues:list[dict], context:dict) → dict` | 判断问题归属（自己 vs 下层） | ReflectCoordinator / 上层 ReflectionAgent | — |
| `ReflectionAgent.fix` | `(my_issues:list[dict]) → dict` | 修复确认的问题，通过 Manager.apply_update() | investigate() | Manager.apply_update() |
| `ReflectionAgent.query_downstream` | `(issues, context) → dict` | 将问题递交给下层 ReflectionAgent | investigate() | 下层.investigate() |

## core/layers/comm.py (Phase 1.5)

| 函数/类 | 签名 | 作用 | 上游调用者 | 下游调用 |
|----------|------|------|-----------|---------|
| `UpwardComm` | `receive(msg)→dict` / `wrap_response(...)→LayerMessage` / `wrap_notify(...)→LayerMessage` | 确定性协议处理：LayerMessage ↔ 业务 dict | LayerManager.query() | — |
| `DownwardComm` | `receive(msg)→dict` / `wrap_query(...)→LayerMessage` | 确定性协议处理：LayerMessage ↔ 业务 dict | LayerManager.query() | 下层 UpwardComm |

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

## core/layers/l3/manager.py (NEW in Phase 1)

| 函数/类 | 签名 | 作用 | 上游调用者 | 下游调用 |
|----------|------|------|-----------|---------|
| `L3Manager` | `__init__(skill_layer, downstream)` | L3 层 Manager，包裹 SkillLayer | build_chain() | — |
| `L3Manager.process` | `(obs:TaskObservation) → dict` | 按 domain 匹配技能，写入 obs.meta["l3_skills"] | LayerManager.query() | SkillLayer.match() |
| `L3Manager.notify` | `() → dict` | 返回 `{status:"ok", layer:"l3"}` | collect_notify() | — |

## core/layers/l2/manager.py (NEW in Phase 1)

| 函数/类 | 签名 | 作用 | 上游调用者 | 下游调用 |
|----------|------|------|-----------|---------|
| `L2Manager` | `__init__(knowledge, downstream)` | L2 层 Manager，包裹 FlexibleKnowledge | build_chain() | — |
| `L2Manager.process` | `(obs:TaskObservation) → dict` | 按 domain 检索 top-5 活跃卡片，写入 obs.meta["l2_cards"] | LayerManager.query() | FlexibleKnowledge.get_active_cards() |
| `L2Manager.notify` | `() → dict` | 返回 `{status:"ok", layer:"l2"}` | collect_notify() | — |
| `L2Manager.apply_update` | `(key, value) → None` | Phase 2: boost_card 或通用 reflect_fix | ReflectionAgent.fix() | KnowledgeCard.boost() |

## core/layers/l0_5_1/manager.py (NEW in Phase 1)

| 函数/类 | 签名 | 作用 | 上游调用者 | 下游调用 |
|----------|------|------|-----------|---------|
| `L0_5_1Manager` | `__init__(meta_driver, philosophy, auxiliary_llm, downstream)` | L(0.5+1) 层 Manager，包裹 MetaDriver + Philosophy | build_chain() | — |
| `L0_5_1Manager.process` | `(obs:TaskObservation) → dict` | 注入 L1 规则到 obs.meta["l1_rules"]；过滤危险 tool_calls | LayerManager.query() | Philosophy.all_rules(), MetaDriver.filter_dangerous() |
| `L0_5_1Manager.notify` | `() → dict` | 返回 `{status:"ok", layer:"l0_5_1"}` | collect_notify() | — |
| `L0_5_1Manager.apply_update` | `(key, value) → None` | Phase 2: modify_rule 或通用 reflect_fix | ReflectionAgent.fix() | Philosophy.modify_rule() |

## core/layers/__init__.py

| 函数/类 | 签名 | 作用 | 上游调用者 | 下游调用 |
|----------|------|------|-----------|---------|
| `build_chain` | `(meta_driver, philosophy, flexible_knowledge, skill_layer, auxiliary_llm) → L0_5_1Manager` | 自底向上构建三层链：L3 → L2 → L(0.5+1) | AgentRuntime / 脚本 | L3Manager(), L2Manager(), L0_5_1Manager() |

## core/meta_driver.py (已有，层内部使用)

| 函数/类 | 签名 | 作用 | 上游调用者 | 下游调用 |
|----------|------|------|-----------|---------|
| `MetaDriver` | `__init__(triggers, validation_rules, auxiliary_llm, max_rules, max_rule_length)` | L0.5 不可变核心：触发器+验证器+安全过滤 | L0_5_1Manager | — |
| `MetaDriver.filter_dangerous` | `(tool_calls:list) → list` | 过滤危险工具调用（rm -rf, delete_all 等） | L0_5_1Manager.process() | — |
| `MetaDriver.check_completion` | `(task, messages) → str` | 判断任务是否完成（"done"/"continue"） | AgentLoop.run()（旧架构） | — |
| `MetaDriver.validate_l1_change` | `(proposal, existing_rules) → tuple[bool, str]` | L0.5 验证器：检查 not_duplicate + no_contradiction + under_limit + under_length | L0_5_1Manager.apply_update()（Phase 2） | Philosophy |

## core/philosophy.py (已有，层内部使用)

| 函数/类 | 签名 | 作用 | 上游调用者 | 下游调用 |
|----------|------|------|-----------|---------|
| `Philosophy` | `__init__(rules_path, max_rules, max_rule_length)` | L1 可演化行为规则管理 | L0_5_1Manager | — |
| `Philosophy.all_rules` | `() → list[Rule]` | 返回所有规则副本 | L0_5_1Manager.process() | — |
| `Philosophy.modify_rule` | `(rule_id:str, new_content:str) → Rule` | 修改规则（版本递增） | L0_5_1Manager.apply_update() | — |
| `Philosophy.add_rule` | `(content:str, created_by:str) → Rule` | 添加新规则 | L0_5_1Manager.apply_update() | — |

## core/flexible_knowledge.py (已有，层内部使用)

| 函数/类 | 签名 | 作用 | 上游调用者 | 下游调用 |
|----------|------|------|-----------|---------|
| `FlexibleKnowledge` | `__init__(knowledge_dir, index_path)` | L2 知识卡片管理 | L2Manager | — |
| `FlexibleKnowledge.get_active_cards` | `(domain, context, top_k) → list[KnowledgeCard]` | 按激活值排序返回 top-k 活跃卡片 | L2Manager.process() | KnowledgeCard.compute_activation() |
| `FlexibleKnowledge.get_domain_cards` | `(domain) → list[KnowledgeCard]` | 返回指定 domain 下所有卡片 | Phase 2: L3 编译检查 | — |
| `KnowledgeCard.boost` | `() → None` | 置信度+0.05, 激活值+0.1, success_count+1 | L2Manager.apply_update() | — |
| `KnowledgeCard.penalize` | `() → None` | 置信度-0.1(min 0.1), failure_count+1 | L2Manager.apply_update() | — |

## core/skill_layer.py (已有，层内部使用)

| 函数/类 | 签名 | 作用 | 上游调用者 | 下游调用 |
|----------|------|------|-----------|---------|
| `SkillLayer` | `__init__(skills_dir, tool_registry)` | L3 技能管理 | L3Manager | — |
| `SkillLayer.match` | `(domain) → list[SkillMeta]` | 按 domain 匹配技能，精确>父级>跨域 | L3Manager.process() | — |
| `SkillLayer.should_create_skill` | `(domain, cards) → bool` | 检查 L2→L3 编译条件 | Phase 2: Reflect | — |
| `SkillLayer.propose_and_create` | `(domain, cards, llm) → SkillMeta\|None` | LLM 编译知识卡片为 SKILL.md | Phase 2: Reflect | — |

## core/orchestrator/ (Phase 2)

| 函数/类 | 签名 | 作用 | 上游调用者 | 下游调用 |
|----------|------|------|-----------|---------|
| `TaskDecomposer.decompose` | `(session:dict, raw_log:Path) → list[Task]` | Session → Task 拆解 | AgentRuntime / ReflectCoordinator | _decompose_game_unit(), _decompose_coding() |
| `ThresholdScorer.score` | `(domain:str) → float` | 计算 domain 的学习积攒评分 | ReflectCoordinator | _domain_records() |
| `ThresholdScorer.should_trigger` | `(domain:str) → bool` | 评分 ≥ threshold 时返回 True | Executor（Reflect 模式） | score() |
| `ReflectCoordinator.audit` | `(domain:str) → dict{layer: issues}` | 审核 pending/ 中所有 NOTIFY，标记潜在问题 | Executor（Reflect 模式） | — |
| `ReflectCoordinator.run_reflect` | `(domain, layer_root, reflection_chain) → dict` | 完整反射周期：audit → 分发 → 修复 → archive | Executor（Reflect 模式） | ReflectionAgent, _archive() |

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
