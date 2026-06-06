# Phase 3+ 架构升级路线图

> 当前架构最核心的功能链路（Execute → Record → LearningEnv → 知识更新）已跑通，但以下四大方向存在明显短板。下述为各方向的现状、缺口、目标设计及建议优先级。

## 方向一：Tool Use & Knowledge 挂载

**现状：**
- `ToolRegistry` 单例（`core/tools/registry.py`）实现了 6 个工具（todo / terminal / web_search / skills_list / skill_view / skill_manage），线程安全，支持 `check_fn` 过滤和 `toolset` 分组
- 工具仅在旧 `main.py` / `_archive/` 路径中使用，新 Executor + Layers 链**未挂载工具**
- `L0_5_1Manager` 有 TODO 注释指明"工具集成保留给通用任务场景"
- 当前游戏环境不需要工具调用，但通用任务（编程、搜索、代码验证）离开工具寸步难行

**缺口：**
1. 工具定义无法注入各层 LLM prompt（L1/L2/L3 的 system prompt 未携带工具 schema）
2. 工具调用结果无法回流到层链（无 `ToolResult → LayerMessage` 的封装路径）
3. 没有工具执行的**安全层级路由**——哪些工具 L1 可见、哪些 L2 可见、哪些仅 Executor 可见
4. Knowledge 挂载是单向的——L2 卡片只能被 LLM 读取，无法作为工具的触发条件
5. LearningEnv 内无法调用 `terminal`/`web_search` 对学习内容做验证

**目标设计：**
```
                        ToolRegistry（全局单例）
                       /        |          \
              tool_schemas   dispatch    check_fn
              inject to↓     route↓     filter↓
   ┌──────────────┬──────────────┬──────────────┐
   │ L1Agent      │ L2Agent      │ L3Agent      │
   │ (todo +      │ (terminal +  │ (skills_* +  │
   │  knowledge_*)│  knowledge_*)│  web_search) │
   └──────────────┴──────────────┴──────────────┘
              ↓ ToolResult 回流
   ┌──────────────────────────────────────────┐
   │  ToolResult → LayerMessage(RESPONSE)      │
   │  → 注入下层 stage 的 user prompt          │
   └──────────────────────────────────────────┘
```

**关键变更点：**
- `LayerAgent._call_llm()` 支持 `tools` 参数
- 新增 `ToolPolicy` 配置：每层可见工具白名单、最大调用次数、超时
- `ToolResult` 作为 `LayerMessage.payload` 回流到 Manager
- LearningEnv 的 Agent 任务中显式注入验证工具

---

## 方向二：并行 Agent 执行 & 并行学习

**现状：**
- `scripts/run_parallel_test.py` 使用 `ThreadPoolExecutor` 开 N 组子进程
- 这是**进程级并行**（子进程各自独立，无共享运行时状态）
- 学习阶段是串行的——GameEnv 批量跑完 → 一次 LearningEnv.step()
- 不存在"并行 Agent 同时操作同一个知识库"的协调机制

**缺口：**
1. 多个 Agent 并行写 pending/ 文件的并发安全问题
2. 多个 domain 同时触发 LearningEnv 时，知识库并发读写无保护
3. 并行 Agent 之间的**知识共享**——Agent A 学到的东西何时对 Agent B 可见？
4. 缺少"多 Agent 协作"模式

**目标设计：**
```
┌─────────────────────────────────────────────────────────┐
│                Orchestrator (全局调度)                    │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐              │
│  │ Agent₁   │  │ Agent₂   │  │ Agent₃   │  ← 并行执行   │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘              │
│       └──────────────┼──────────────┘                    │
│                      ▼                                   │
│   ┌──────────────────────────────────────┐              │
│   │  Knowledge Store (统一知识库)         │              │
│   │  ← 加锁写入 / 批量合并 / 冲突检测      │              │
│   └──────────────────────────────────────┘              │
│                      ▼                                   │
│   ┌──────────────────────────────────────┐              │
│   │  Parallel Learning Loop              │              │
│   │  → 合并 per-domain knowledge diff    │              │
│   │  → 去重 + 冲突解决                    │              │
│   └──────────────────────────────────────┘              │
└─────────────────────────────────────────────────────────┘
```

**关键变更点：**
- `FlexibleKnowledge` / `Philosophy` / `SkillLayer` 需要写锁
- `LearningEnv` 支持多 domain 并行消费
- 新增 `KnowledgeBuffer`：Agent 写入缓冲区 → Orchestrator 批量 commit
- 新增 `ConflictResolver`：基于 confidence + success_count 仲裁

---

## 方向三：Agent 调度模式优化（Hermes 式循环编排）

**现状：**
- Orchestrator 横向分层（Task Decomposer → Task Runner(s) → Meta Learner）**标记为 TODO，代码未实现**
- 当前每层的 V-structure 循环 `MAX_LOOPS=1`——单次查询后直接决策，无多轮追问
- `PROPOSAL` / `APPROVAL` / `REJECTION` 三种消息类型**代码已定义但从未使用**
- 任务划分职责硬编码在 prompt 中，未在架构层面显式约束

**缺口：**
1. 每层缺少独立的持续循环
2. 无 Hermes 式的 `while step(): observe → decide → act` 内部循环
3. L1→L2、L2→L3 之间无多轮对话能力
4. PROPOSAL/APPROVAL/REJECTION 未启用，下层无法向上层主动提案
5. 任务划分职责未在代码中显式约束

**目标设计：**
```
每层 Manager 的内部循环（Hermes 式）：
┌─────────────────────────────────────────────────┐
│  while not done:                                 │
│    1. observe: 从上层 QUERY + 本层 data 构建观察  │
│    2. plan:    本层 Agent 决定"需要什么信息"       │
│    3. delegate: 需要下层信息 → QUERY 到下层       │
│    4. propose:  需要上层变更 → PROPOSAL 到上层     │
│    5. decide:   信息充分 → 产出 NOTIFY             │
│    6. review:   收到 REJECTION → 回到 step 2       │
│  限制: max_rounds=N, 超时=T, token_budget=B       │
└─────────────────────────────────────────────────┘
```

**层间任务划分规格（显式约束）：**

| 维度 | L1 (L0.5+1) | L2 | L3 |
|------|------------|----|-----|
| **决策粒度** | 宏观任务目标 | 中观策略选择 | 微观操作执行 |
| **持有的知识** | 行为准则（抽象原则） | 经验卡片（具体策略） | 技能模板（标准化流程） |
| **可发起的消息类型** | QUERY, APPROVAL, REJECTION | QUERY, PROPOSAL, NOTIFY | PROPOSAL, NOTIFY |
| **循环终止条件** | stage2 输出 done=true | 信息充分 / 无需 L3 | 技能执行完毕 |
| **多轮追问** | 可追问 L2 | 可追问 L3 | — |

**关键变更点：**
- 将 `MAX_LOOPS` 从 1 提升到可配置值（如 3）
- 启用 `PROPOSAL` / `APPROVAL` / `REJECTION` 消息流
- 每层 Manager 从被动 `process()` 改为主动 `run_loop()`
- 新增 `Orchestrator` 实现类

---

## 方向四：整理模式 — 各层内容规格与整理策略

**现状：**
- `LearningEnv.build_consolidation_task()` 已实现基础整理触发——当 L2 cards > 30 或 L3 skills > 20 时触发
- 整理逻辑极简：仅提供 `use_count` + `last_used` 统计，无自动整理策略
- 每层 Agent 没有明确的内容规格约束——粒度、长度、格式只在 prompt 中以自然语言描述

**缺口：**
1. **内容规格缺失**——仅有 `max_rules` / `max_rule_length` 两个数值限制
2. **整理策略单一**——仅有"超限时触发"，缺少例行整理
3. **无自动整理算法**——同类卡片合并、低激活度衰减删除等规则引擎未实现
4. **整理结果验证缺失**——无回滚机制
5. **各层内容关联性缺失**——L2 卡片关联的 L3 技能被删除时无感知

**目标设计 — 各层内容规格：**

| 属性 | L1 Rule | L2 KnowledgeCard | L3 SKILL.md |
|------|---------|-----------------|-------------|
| **最小粒度** | 1-2 句行为准则 | 单条领域策略提示 | 完整 YAML + Markdown |
| **最大长度** | ≤100 字符 | ≤500 字符 | ≤5000 字符 |
| **ID 格式** | `l1_XXXX`（6 位 hex） | UUID（8 位 hex） | 语义化 kebab-case |
| **上限** | 20 条 | 30 张/domain | 20 个 skill |
| **版本控制** | `version` 字段递增 | 无版本（直接覆盖） | 无版本（直接覆盖） |
| **来源追踪** | `created_by` / `source` | `source` 字段 | `created_by` 字段 |
| **统计字段** | — | success_count / failure_count / last_used / activation | usage_stats（外部文件） |
| **依赖关系** | 可引用 L2 domain | 可关联 L3 skill（TODO） | `relevance_domain` 指向 L2 domain |

**目标设计 — 三级整理策略：**

```
Level 1 — 自动衰减（无 Agent 参与）:
  - activation < 0.1 且 30 天未使用 → 自动标记 deprecated
  - L2 卡片 decay_rate 每天衰减，activation 归零后归档
  - L1 版本号超过 5 的旧版本自动清理

Level 2 — 例行整理（轻量 Agent）:
  - 每 N 局后触发（如 N=50），走 LearningEnv
  - Agent 任务: 合并相似卡片、归档过时规则、压缩冗余技能
  - 可回滚（整理结果写入 temp → 验证 → 正式提交）

Level 3 — 深度重构（重量 Agent）:
  - 重大版本升级时触发
  - Agent 任务: 跨 domain 模式提取、抽象规则归纳、技能模板泛化
  - 需要人工审核
```

**关键变更点：**
- `KnowledgeCard` 增加 `status` 字段（active / deprecated / archived）
- 新增 `ConsolidationEngine` 模块：Level 1 自动衰减引擎 + Level 2/3 调度入口
- `LearningEnv.build_consolidation_task()` 扩展：支持指定整理级别、可回滚的 diff 输出
- 内容关联性维护：L2→L3 skill 的双向引用

---

## 优先级建议

综合依赖关系和收益分析，建议按以下顺序推进：

| 优先级 | 方向 | 理由 | 预计影响范围 |
|--------|------|------|-------------|
| **P0** | 方向四：内容规格 + 整理模式 | 不定义内容规格，其他方向产出的知识会失控。改动最小，收益最大。 | `KnowledgeCard` + `Rule` + `SkillMeta` 数据类；`LearningEnv.build_consolidation_task()` |
| **P1** | 方向一：Tool Use 挂载 | 工具是通用任务能力的入口。先挂基础工具（terminal + web_search），LearningEnv 验证能力即可生效。 | `LayerAgent._call_llm()` + 每层 `_build_system_prompt()` + 新增 `ToolPolicy` |
| **P2** | 方向三：Hermes 式循环编排 | 调度模式决定层间交互灵活度。在工具挂载之后做，多轮追问在工具调用场景中最有意义。 | `L0_5_1Manager.query()` + `L2Manager.query()` 循环逻辑；新增 `Orchestrator` |
| **P3** | 方向二：并行 Agent + 并行学习 | 依赖前三个方向的基础：内容规格定义冲突解决标准、工具集成保证独立能力、循环编排提供调度框架。 | `KnowledgeStore` 并发安全；`ParallelOrchestrator`；`ConflictResolver` |
