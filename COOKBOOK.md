# Cookbook：README 章节 ↔ 代码位置对照表

> 每一条 README 中描述的功能/概念，这里给出其在代码库中的精确位置。

---

## 1. 架构概览 — 分层架构图

| README 中的概念 | 代码文件 | 关键行/位置 |
|---|---|---|
| L0.5 元驱动层 | `core/meta_driver.py` | `MetaDriver(triggers=..., validation_rules=...)` 类定义（全文 241 行） |
| L1 行为准则层 | `core/philosophy.py` | `Philosophy(..., max_rules=..., max_rule_length=...)` 类定义（全文 123 行） |
| L2 柔性知识层 | `core/flexible_knowledge.py` | `FlexibleKnowledge(...)` 类定义（全文 281 行） |
| L3 半静态技能层 | `core/skill_layer.py` | `SkillLayer(skills_dir, tool_registry)` 类定义（全文 ~330 行） |
| 所有层组装 | `core/agent.py` | `CognitiveAgent.__init__()` 第 25-40 行 |
| 层间桥接 | `core/layer_context.py` | `LayerContext(self.meta, self.l1, self.l2, self.l3)` 第 33 行 of `agent.py` |

---

## 2. 事件循环（Agent Loop）

| README 中的阶段 | 代码位置 |
|---|---|
| ① PRE-LLM：注入 L1 规则 + top-5 L2 卡片 + L3 技能 | `core/layer_context.py` → `LayerContext.build_context(task)` 方法 |
| ② LLM 调用 | `core/agent_loop.py` → `AgentLoop.run(task)` 内 `while` 循环中 `resp = self.llm_client.chat(messages, tools=tool_defs)` |
| ③ PRE-TOOL：危险过滤 | `core/layer_context.py` → `LayerContext.filter_tool_calls(tool_calls)` → 委托给 `MetaDriver.filter_dangerous()` |
| ④ 工具分发 | `core/agent_loop.py` → `ToolRegistry.dispatch(...)` 调用 |
| ⑤ POST-TOOL：更新 L2 激活值 | `core/layer_context.py` → `LayerContext.on_tool_results(...)` → `self.l2.boost(...)` |
| ⑥ COMPLETION 检查 | `core/layer_context.py` → `LayerContext.check_completion(...)` → 委托给 `MetaDriver.check_completion(...)` |
| POST-TASK：反思 + 学习闭环 | `core/layer_context.py` → `LayerContext.post_task(task)` 方法 |

---

## 3. 设计原则

### 架构原则 A1 — 层间严格相邻传递

| README 中的概念 | 代码位置 |
|---|---|
| A1-1: 相邻传递规则 | 待实现；当前代码中 LayerContext 为中心的星型通信违反了此规则 |
| A1-2: Orchestrator 角色 | `core/agent_loop.py` → `AgentLoop` 类（当前版本 Orchestrator 与事件循环合一） |
| A1-3: 违规点 — build_context 跨层访问 | `core/layer_context.py:17-46` → `LayerContext.build_context()` 内 `self.l1.active_rules + self.l2.active_cards + self.l3.matching_skills` |
| A1-3: 违规点 — post_task 跨层操作 | `core/layer_context.py:58-93` → `LayerContext.post_task()` 内 `meta→l2→l1→l3` 直接调用链 |
| A1-3: 违规点 — build_system_prompt 读 L1 | `core/agent_loop.py:104-125` → `_build_system_prompt()` 内 `self.layers.l1.all_rules()` |
| A1: 当前桥接层（星型枢纽） | `core/layer_context.py` → `LayerContext` 类（需重构为链式转发） |

### 架构原则 A2 — 统一层间消息信封

| README 中的概念 | 代码位置 |
|---|---|
| A2-1: `LayerMessage` 定义 | 待创建 → `core/layer_message.py`（新模块，独立于各层实现） |
| A2-2: `MessageType` 枚举（6 种基础类型） | 待创建 → `core/layer_message.py` → `class MessageType(Enum)` |
| A2-3: `subtype` 字段（层级定制预留） | 待创建 → `core/layer_message.py` → `LayerMessage.subtype: str` |
| A2-4: 当前无统一格式的体现 | `core/meta_driver.py:235` → `L1ProposalProxy` vs `core/philosophy.py:28` → `L1Proposal`（同名概念两种类）、`core/layer_context.py:73-74` → `dict` 格式的 knowledge_updates |

### 架构原则 A3 — 层内 Agent 分工与信息隔离

| README 中的概念 | 代码位置/现状 |
|---|---|
| A3: LayerManager Agent 角色 | 当前映射：`Philosophy` 类 ≈ L1 Manager, `FlexibleKnowledge` 类 ≈ L2 Manager, `SkillLayer` 类 ≈ L3 Manager, `MetaDriver` 类 ≈ L0.5 Manager |
| A3: UpwardComm / DownwardComm Agent | **待新建**：当前不存在通讯 Agent，LayerContext 以星型枢纽代替了所有通讯逻辑 |
| A3: 确定性 Agent 示例 | `core/flexible_knowledge.py:46-65` → `compute_activation()` 和 `_domain_match_score()`（纯数学计算）；`core/skill_layer.py:51-65` → `match()`（模式匹配） |
| A3: LLM Agent 示例 | `core/meta_driver.py:174-199` → `_llm_reflection()`（反思分析）；`core/skill_layer.py:138-164` → `propose_and_create()`（L2→L3 编译） |
| A3: 信息隔离违反点 | 见 A1 违规表 — LayerContext 直接访问所有层数据，破坏了"每层只暴露最小信息集"原则 |
| A3: 当前层内结构 | 每层当前是**单体类**（如 `Philosophy` 同时承担管理+通讯），需拆分为 Manager + 2 Comm Agent |

**Agent 依赖图**（A1+A3 支撑数据结构）：

| README 中的概念 | 代码位置/现状 |
|---|---|
| 图结构定义 | **待新建** → `core/agent_graph.py`（有向图，节点=Agent，边=通信通道） |
| 静态路由表 | 待实现 → 从图推导的 `ROUTES` dict，Agent 发消息只指定 direction+type，目标由图解析 |
| 影响范围分析 | 待实现 → BFS 从任意节点出发，获取受改动影响的所有 Agent 集合 |
| 启动拓扑排序 | 待实现 → 图拓扑排序驱动 L0.5→L3 逐层初始化 / 反向关闭 |
| 消息流追踪 | 需配合 A2 的 `trace_id` — 图回溯异常消息路径，定位问题节点 |
| 单节点最大出度 | 理论值 ≤ 4（同层 Manager + 邻居 Comm Agent × 2 方向），稀疏图保证可控 |

### 架构原则 A4 — 任务单元学习循环

| README 中的概念 | 代码位置/现状 |
|---|---|
| A4: Execute 阶段 | `core/agent_loop.py:27-86` → `while` 循环中的 LLM 调用 + 工具分发 |
| A4: Evaluate 阶段 | **当前缺失** — `core/agent_loop.py:91` → `result.success = True` 硬编码为 True，无真实评估 |
| A4: Reflect & Learn 阶段 | `core/layer_context.py:58-93` → `post_task()` — 有反思逻辑，但与 Execute 在同一个方法调用链中，未实现严格分离 |
| A4: 子 Task 分解 | **当前缺失** — `core/task.py:43-44` → `Task.needs_decomposition` 和 `Task.subtasks` 字段已定义但未实现分解逻辑 |
| A4: 中间 checkpoint 得分 | **当前缺失** — 无 `TaskResult` 中的中间评估维度 |
| A4: RL reward 信号 | **当前缺失** — `core/flexible_knowledge.py:67-77` → `boost()/penalize()` 仅为简单的 ±0.1/ ±0.05 固定值调整，非基于多维评估的 reward |
| A4: 跨 Task 知识迁移 | `core/flexible_knowledge.py:53-65` → `_domain_match_score()` 已实现领域层级匹配，支持同域 Task 经验复用 |
| A4: Execute/Reflect 分离 | **当前违反** — `core/layer_context.py:post_task()` 在事件循环内被直接调用（`agent_loop.py:88`），未由 Orchestrator 显式分阶段调度 |

### 工程原则 E1-E8

| README 中的原则 | 当前代码中的良性示例 | 待改进点 |
|---|---|---|
| E1: 模块化与单一职责 | `core/task.py`（仅数据类型）、`core/tools/`（每个工具一个文件） | `main.py` 中 `_LLMWrapper` 应迁至 `core/llm_client.py` |
| E2: 接口先行与依赖倒置 | `LayerContext` 对事件循环形成抽象边界 | L1/L2/L3 无 Protocol/ABC 定义；`core/__init__.py` 为空 |
| E3: 不可变数据优先 | `Domain`（frozen dataclass, `core/task.py:7`） | `TaskContext` 为可变状态，应在注释中显式标注 |
| E4: 原子持久化 | `core/philosophy.py:117-123`, `core/flexible_knowledge.py:265-271`, `core/skill_layer.py:80-86` — 统一使用 `tempfile.mkstemp + Path.replace` | 当前无共享工具函数，三段代码为重复逻辑 |
| E5: 工具系统标准化 | `core/tools/registry.py` → `register(schema, handler)` 统一接口 | handler 签名不一致（部分接受 context 参数，部分不） |
| E6: 测试先行 | `tests/` 下 9 个测试文件覆盖全部模块 | — |
| E7: 配置与代码分离 | `config.yaml` + `core/config.py` → `AgentConfig` 数据类 | — |
| E8: 错误边界与可观测性 | `logging.getLogger(__name__)` 已声明但未配置 basicConfig | 无统一错误处理策略；LLM 调用失败 silently 跳过 |

### LayerMessage 模块设计（预期结构）

| 文件 | 内容 |
|---|---|
| `core/layer_message.py` | `LayerMessage` frozen dataclass + `MessageType` Enum + 序列化/反序列化 + 校验函数 |
| 与现有代码的关系 | `LayerMessage` 作为各层 `send`/`receive` 方法的唯一参数类型；不依赖任何已有模块，被 `layer_context.py` 和各层实现引用 |

---

## 4. 快速开始

| README 中的步骤 | 代码位置 |
|---|---|
| 安装依赖 | `pyproject.toml` 第 6-14 行 |
| 配置加载 | `main.py` → `load_config(config_path)` 函数 第 31-51 行 |
| `.env` 文件加载 | `main.py` → `_load_env()` 函数 第 12-22 行 |
| LLM 包装器适配 | `main.py` → `_LLMWrapper` 类 第 54-74 行 |
| Agent 初始化 | `main.py` 第 79-82 行（`__main__` 块） |
| 命令行任务执行 | `main.py` 第 84-88 行 |
| `config.yaml` 参数 | `config.yaml` 全文 15 行 |
| `AgentConfig` 数据类 | `core/config.py` |

---

## 5. 各层详解

### L0.5 — Meta Driver

| README 中的概念 | 代码位置 |
|---|---|
| 反射触发器的定义 | `core/meta_driver.py` → `ReflectionTrigger` 类 和 `DEFAULT_TRIGGERS` 列表 |
| stagnation 触发器 | `core/meta_driver.py` → `DEFAULT_TRIGGERS[0]`，`trigger_type == "stagnation"` |
| task_failed 触发器 | `core/meta_driver.py` → `DEFAULT_TRIGGERS[1]`，`trigger_type == "task_failed"` |
| task_completed 触发器 | `core/meta_driver.py` → `DEFAULT_TRIGGERS[2]`，`trigger_type == "task_completed"` |
| domain_shift 触发器 | `core/meta_driver.py` → `DEFAULT_TRIGGERS[3]`，`trigger_type == "domain_shift"` |
| 冷却时间机制 | `core/meta_driver.py` → `ReflectionTrigger.last_triggered` 和 `cooldown_rounds` 字段 |
| 验证规则定义 | `core/meta_driver.py` → `ValidationRule` 类 和 `DEFAULT_VALIDATORS` 列表 |
| not_duplicate 验证器 | `core/meta_driver.py` → `DEFAULT_VALIDATORS[0]` |
| no_contradiction 验证器 | `core/meta_driver.py` → `DEFAULT_VALIDATORS[1]` |
| 危险过滤白名单 `["delete_all", "drop_table", "format", "rm -rf"]` | `core/meta_driver.py` → `MetaDriver.filter_dangerous()` 方法（搜索 `delete_all` 可定位） |
| 反思流 `run_reflection()` | `core/meta_driver.py` → `MetaDriver.run_reflection(...)` 方法 |
| 完成检查 `check_completion()` | `core/meta_driver.py` → `MetaDriver.check_completion(messages)` |

### L1 — Philosophy

| README 中的概念 | 代码位置 |
|---|---|
| L1 规则类 | `core/philosophy.py` → `Rule` 数据类 |
| add_rule 方法 | `core/philosophy.py` → `Philosophy.add_rule(...)` |
| modify_rule 方法（版本递增） | `core/philosophy.py` → `Philosophy.modify_rule(...)` |
| remove_rule 方法 | `core/philosophy.py` → `Philosophy.remove_rule(...)` |
| 提案审批 `apply()` | `core/philosophy.py` → `Philosophy.apply(proposal)` |
| L1→系统提示词注入 | `core/agent_loop.py` → 搜索 `l1_rules` 在 build_system_prompt 中的位置 |
| JSON 持久化 | `core/philosophy.py` → `_save()` 方法 |
| 种子规则数据 | `data/l1_rules.json`（全文） |
| 容量约束 | `core/philosophy.py` → `max_rules` 和 `max_rule_length` 参数 |

### L2 — Flexible Knowledge

| README 中的概念 | 代码位置 |
|---|---|
| KnowledgeCard 数据类 | `core/flexible_knowledge.py` → `KnowledgeCard` 类定义 |
| 激活值计算公式 | `core/flexible_knowledge.py` → `FlexibleKnowledge.compute_activation(task_domain)` |
| 领域匹配权重 (exact=1.0 / parent=0.7 / child=0.5 / general=0.4) | `core/flexible_knowledge.py` → `_domain_match_score(...)` 方法 |
| boost / penalize 方法 | `core/flexible_knowledge.py` → `KnowledgeCard.boost()` / `KnowledgeCard.penalize()` |
| apply_decay（指数衰减） | `core/flexible_knowledge.py` → `KnowledgeCard.apply_decay()` |
| KnowledgeGraph 类 | `core/flexible_knowledge.py` → `KnowledgeGraph` 类 |
| spread_activation（2 跳扩散） | `core/flexible_knowledge.py` → `KnowledgeGraph.spread_activation(seed_ids, steps=2)` |
| MD + JSON 双存方案 | `core/flexible_knowledge.py` → `save_md()` / `save_index()` 方法 |
| L2 知识点索引 | `knowledge/l2_index.json` |

### L3 — Skill Layer

| README 中的概念 | 代码位置 |
|---|---|
| Skill CRUD 操作 | `core/skill_layer.py` → `create_skill()` / `edit_skill()` / `patch_skill()` / `delete_skill()` |
| 领域匹配（精确 > 父级 > general > 根域） | `core/skill_layer.py` → `match(task_domain)` 方法 |
| L2→L3 编译条件判断 | `core/skill_layer.py` → `should_create_skill(domain, cards)` 方法 |
| L2→L3 编译流程 | `core/skill_layer.py` → `propose_and_create(...)` 方法 |
| L3 共享的三个工具注册 | `core/skill_layer.py` → `__init__` 末尾，`register_skill_tools` 相关逻辑 |
| 技能存储目录 | `skills/` 目录 |

---

## 6. 工具系统

| README 中的工具 | 注册位置 | 调度逻辑 |
|---|---|---|
| ToolRegistry 单例 | `core/tools/registry.py` → `ToolRegistry` 类 | `dispatch(name, args)` |
| thread-safe 保证 | `core/tools/registry.py` → `threading.Lock()` 的使用 | — |
| 条件过滤 `check_fn` | `core/tools/registry.py` → `register(check_fn=...)` 参数 | `get_definitions(filter=...)` |
| `toolset` 分组 | `core/tools/registry.py` → `register(toolset=...)` 参数 | — |
| `todo` 工具 | `core/tools/todo_tool.py` → `register_todo_tool(registry)` | — |
| `terminal` 工具（30s 超时） | `core/tools/terminal_tool.py` → `register_terminal_tool(registry)` | `subprocess.run(timeout=30)` |
| `terminal` 白名单 | `core/tools/terminal_tool.py` → `register_terminal_tool()` 参数 `allowed_commands` | — |
| `web_search` 工具 | `core/tools/web_search_tool.py` → `register_web_search_tool(registry)` | DuckDuckGo API 调用 |

---

## 7. 项目结构

| README 中的文件/目录 | 实际路径 |
|---|---|
| `main.py` | `main.py` |
| `config.yaml` | `config.yaml` |
| `pyproject.toml` | `pyproject.toml` |
| `core/agent.py` | `core/agent.py` |
| `core/agent_loop.py` | `core/agent_loop.py` |
| `core/config.py` | `core/config.py` |
| `core/layer_context.py` | `core/layer_context.py` |
| `core/task.py` | `core/task.py` |
| `core/meta_driver.py` | `core/meta_driver.py` |
| `core/philosophy.py` | `core/philosophy.py` |
| `core/flexible_knowledge.py` | `core/flexible_knowledge.py` |
| `core/skill_layer.py` | `core/skill_layer.py` |
| `core/tools/registry.py` | `core/tools/registry.py` |
| `core/tools/todo_tool.py` | `core/tools/todo_tool.py` |
| `core/tools/terminal_tool.py` | `core/tools/terminal_tool.py` |
| `core/tools/web_search_tool.py` | `core/tools/web_search_tool.py` |
| `data/l1_rules.json` | `data/l1_rules.json` |
| `knowledge/l2_index.json` | `knowledge/l2_index.json` |
| `skills/` | `skills/` 目录 |
| `tests/` | `tests/` 目录（含 9 个测试文件 + conftest.py） |
| `docs/` | `docs/` 目录（含 4 个设计文档） |

---

## 8. 设计文档

| README 中的文档 | 代码位置 |
|---|---|
| `docs/4.5-layer-agent-design.md` | `docs/4.5-layer-agent-design.md`（初始架构 + TextWorld 验证 + 冷启动） |
| `docs/cognitive-agent-design-v2.md` | `docs/cognitive-agent-design-v2.md`（~1500+ 行详细设计 + 伪代码） |
| `docs/cognitive-agent-phase1-plan.md` | `docs/cognitive-agent-phase1-plan.md`（~1800+ 行 TDD 实现计划） |
| `docs/4.5-layer-agent-references.md` | `docs/4.5-layer-agent-references.md`（33 篇分类参考文献） |

---

## 9. 测试覆盖

| README 中的测试目标 | 测试文件 |
|---|---|
| Domain、Task、TaskResult 数据结构 | `tests/test_task.py` |
| ToolRegistry 单例模式与注册/分发/过滤 | `tests/test_tool_registry.py` |
| L3 技能层 CRUD 与匹配 | `tests/test_skill_layer.py` |
| L2 KnowledgeCard boost/penalize/decay、域匹配、图扩散 | `tests/test_flexible_knowledge.py` |
| L1 规则增删改查、提案审批、持久化 | `tests/test_philosophy.py` |
| L0.5 触发器、验证器、危险过滤、完成判定 | `tests/test_meta_driver.py` |
| LayerContext 的三层上下文构建与工具调用过滤 | `tests/test_layer_context.py` |
| AgentLoop 任务执行与最大迭代限制 | `tests/test_agent_loop.py` |
| CognitiveAgent 端到端集成测试 | `tests/test_agent.py` |
| 共享 fixture（mock LLM、mock 注册表等） | `tests/conftest.py` |
