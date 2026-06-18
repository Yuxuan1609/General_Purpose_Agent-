# Architecture Design — Cognitive Agent

> 设计原则、通信协议、层间结构、工程规范的完整描述。快速入门见 [README.md](README.md)。

## 设计原则

项目遵循两层设计原则：**架构原则**（定义层间通信协议，是系统骨架）和**工程原则**（定义代码实施规范，是开发纪律）。

### 架构原则

#### A1：层间严格相邻传递

1. 认知层（L0.5 / L1 / L2 / L3 / L4）之间**状态变更和数据请求必须通过相邻层传递**，禁止跨层跳跃。例如：L0.5 不能直接读写 L2 数据——必须经过 L1 转发。
2. 存在一个全局 **Orchestrator**，承担任务编排、流程控制、资源管理、全局状态监控、错误恢复决策等多重职责（不限于事件循环）。Orchestrator 可以**读取观察**所有层状态、向任意层发送调度指令，但**不绕过相邻传递规则直接修改层内数据**，也不替代层间业务数据流的消息传递。
3. 相邻传递约束的是**信息流向**（谁可以和谁交流），不约束**交互次数**。一个逻辑阶段内相邻层之间可以进行多轮往返查询。

```
                    ┌──────────────┐
                    │ Orchestrator │  ← 全局编排者，可观察所有层状态、发送调度指令，
                    │              │    但不越过相邻传递规则操作层内数据
                    └──┬──┬──┬──┬──┘
                       │  │  │  │  (只读观察)
           ┌────────────┼──┼──┼──┼────────────┐
           │            │  │  │  │            │
           ▼            ▼  ▼  ▼  ▼            ▼
        ┌──────────────────┐  ┌──────┐    ┌──────┐
        │   L(0.5+1)       │◄►│ L2   │◄──►│ L3   │
        │ (L0.5 + L1 合并)  │  │      │    │      │
        └──────────────────┘  └──────┘    └──────┘
            ▲ 严格相邻传递（通过 LayerMessage）  ▲
```

#### A2：统一层间消息信封

1. 所有层间通信必须使用 `LayerMessage` 结构，格式如下：

```python
@dataclass(frozen=True)
class LayerMessage:
    source: str          # 发送层标识
    target: str          # 接收层标识
    type: MessageType    # 基础信封类型（见下表）
    subtype: str         # 层级定制语义
    payload: Any         # 具体业务数据
    trace_id: str        # 跨层追踪 ID
    timestamp: datetime  # 发送时间
    metadata: dict       # 扩展字段
```

2. 基础信封类型（`MessageType`）：

| type | 方向 | 含义 |
|------|------|------|
| `QUERY` | 上层→下层 | 请求下层提供数据/服务 |
| `RESPONSE` | 下层→上层 | 对 QUERY 的应答 |
| `PROPOSAL` | 下层→上层 | 下层向上层提议变更 |
| `APPROVAL` | 上层→下层 | 上层批准下层提案 |
| `REJECTION` | 上层→下层 | 上层驳回下层提案（含原因） |
| `NOTIFY` | 任意方向 | 单向通知，无需回复 |

> `PROPOSAL` / `APPROVAL` / `REJECTION` 已定义但尚未启用——当前仅 QUERY / RESPONSE / NOTIFY 在实际流程中。

3. `LayerMessage` 封装为独立模块（`core/layer_message.py`），不与其他层实现耦合。

#### A3：层内 Agent 分工与信息隔离

核心思路：通过分层实现**信息隔离 + 职责匹配**。每层由多个专职 Agent 组成的微型集群。每个 Agent 只能读写本层信息、只能执行本层职责。

**每层最小 Agent 集合：**

```
Layer N:
  ┌──────────────────────────────────────────────────┐
  │  ┌──────────────┐   ┌──────────────┐              │
  │  │ UpwardComm   │   │ DownwardComm │   ← 相邻层通讯 │
  │  │ Agent        │   │ Agent        │              │
  │  └──────┬───────┘   └──────┬───────┘              │
  │         └────────┬─────────┘                      │
  │                  ▼                                │
  │         ┌──────────────┐                          │
  │         │ LayerManager │   ← 本层信息管理/业务逻辑   │
  │         └──────────────┘                          │
  └──────────────────────────────────────────────────┘
```

| Agent | 职责 | 典型执行方式 |
|-------|------|-------------|
| **LayerManager** | 管理本层核心数据、执行业务逻辑、接收 Comm Agent 路由来的请求 | 确定性方法为主；部分决策可由 LLM 辅助 |
| **UpwardComm** | 接收上层消息→解析校验→转发 LayerManager；回复→封装 LayerMessage→发回上层 | 确定性协议处理，无需 LLM |
| **DownwardComm** | 接收下层消息→解析校验→转发 LayerManager；请求→封装 LayerMessage→发送下层 | 确定性协议处理，无需 LLM |

**Agent 执行模型：**

| 类型 | 适用场景 | 示例 |
|------|----------|------|
| 确定性 Agent | 规则引擎、协议处理、匹配算法 | L3Manager 技能匹配、Comm Agent 消息序列化 |
| LLM Agent (while-loop decide) | 多轮推理决策 | L1Agent / L2Agent / L3Agent（decide() + Manager while 循环） |
| 混合 Agent | 确定性逻辑为主，特定节点委托 LLM | L1 Manager：规则 CRUD 走确定性，提案评估走 LLM |

**信息隔离原则：**
- L0.5 的 Agent 不会收到 L2 的知识卡片内容——只能通过 L1 看到经过筛选和格式化的行为规则
- L2 的 Agent 不关心 L3 的 SKILL.md 格式——只管知识卡片的置信度和激活值
- 每一层只暴露其相邻层需要的最小信息集

**Agent 依赖图**（A1+A3 的支撑数据结构，通过有向图建模 Agent 间通信拓扑）：

| 用途 | 说明 |
|------|------|
| **静态路由表** | Agent 发消息只关心 direction + type，目标 Agent 由图解析 |
| **影响范围分析** | 改动任意 Agent → 从图 BFS 出受影响节点集合 → 精确重测范围 |
| **启动/关闭拓扑排序** | L0.5→L1→L2→L3 逐层启动，关闭反序 |
| **消息流追踪** | `trace_id` 串联路径 + 图回溯 → 异常时反向定位问题节点 |

#### A4：任务单元学习循环

以 **Task 为最小执行和评估单元**，将行为拆分为 Execute → Evaluate → Reflect & Learn 宏观循环。

```
用户输入 / 训练数据
        │
        ▼
  ┌─────────────┐
  │ Orchestrator │  分解为 Task₁, Task₂, Task₃ ...
  └──────┬──────┘
         ▼
  ┌──────────────────────────────────────────┐
  │  对每个 Task:                             │
  │  ① EXECUTE — 层间相邻协作，产出最终响应     │
  │  ② EVALUATE — 评估目标达成、效率、中间得分  │
  │  ③ REFLECT & LEARN — 链式通道驱动学习       │
  │     - 提取知识卡片 (L2)                    │
  │     - 修正/新增行为规则 (L1)                │
  │     - 编译高频模式为技能 (L2→L3)            │
  └──────────────────────────────────────────┘
```

**设计动机：**
1. **可评估性**：Task 是天然的最小评估单元
2. **细粒度反馈**：长任务拆成子 Task，每个单独评估
3. **RL 视角**：Task 评估 = reward signal，累积多个 reward → L1/L2 演化有统计依据
4. **跨 Task 知识迁移**：Task 通过 `Domain` 关联

**执行与反思的严格分离：**

| 旧方案 | 新方案 |
|--------|--------|
| Reflect 是独立第二阶段，写死判责逻辑 | Reflect 降级为 LearningEnv，和 GameEnv 平级 |
| 反思阶段 LLM 已停止 | LearningEnv 的 LLM 正常工作 |
| 反思不能调工具 | LearningEnv 可以调用 ToolUse |
| ReflectionAgent 写死每层判责逻辑 | 学习策略走普通层链，可自举 |

**环境隔离：**

```
                    ToolUse（跨环境共享）
                        ↑
  ┌─────────────────────┼──────────────────────────┐
  │  GameEnv            │  LearningEnv              │
  │  domain="game/leduc"│  domain="learning/reflect"│
  │  env.step(action)   │  env.step(action)         │
  │  → state+reward     │  → knowledge diff         │
  └─────────┬───────────┘  └──────────┬──────────────┘
            └──────────┬──────────────┘
                       ▼
            ┌──────────────────────┐
            │  Executor + Layers   │
            │  (L(0.5+1)↔L2↔L3)   │
            └──────────────────────┘
```

**与 A1/A2/A3 的关系：**
- A1 约束 **信息怎么流**（相邻传递）
- A2 约束 **信息用什么格式流**（LayerMessage）
- A3 约束 **谁在层内处理信息**（Agent 分工）
- A4 约束 **什么时候学**（Task 级别的 Execute→Reflect 循环）

---

### 工程原则

| 编号 | 原则 | 核心要求 |
|------|------|----------|
| E1 | **模块化与单一职责** | 每文件仅承担一项可陈述的职责；入口文件不寄生业务逻辑 |
| E2 | **接口先行与依赖倒置** | 每层暴露 Protocol/ABC；组件依赖抽象而非具体实现 |
| E3 | **不可变数据优先** | 数据类型默认 frozen dataclass；状态变更返回新实例 |
| E4 | **原子持久化** | 所有文件写入使用 `tempfile + replace` 模式，保证崩溃安全 |
| E5 | **工具系统标准化** | 统一 `register(schema, handler)` 接口；错误返回 JSON `{"error": "..."}` |
| E6 | **测试先行** | 每个模块必须有对应测试文件；使用 mock 隔离外部依赖 |
| E7 | **配置与代码分离** | 环境相关值一律通过 `config.yaml` + 环境变量注入 |
| E8 | **错误边界与可观测性** | 明确每层的错误捕获策略；关键跨层调用记录结构化日志 |

---

## 通信协议

```
每步动作:
  AgentRuntime ──TaskObservation──→ Executor
     │  LayerMessage(QUERY)                │
     ▼                                     │
  L(0.5+1).UpwardComm → Manager → DownwardComm
     │  LayerMessage(QUERY)                │  ← LayerMessage(NOTIFY)
     ▼                                     │
  L2.UpwardComm → Manager → DownwardComm   │
     │  LayerMessage(QUERY)                │
     ▼                                     │
  L3.UpwardComm → Manager                  │
     │                                     │
     链式 RESPONSE 返回 ────────────────────┘
```

- **Comm Agent** (UpwardComm/DownwardComm): 确定性协议处理，不涉及 LLM
- **Manager**: 各层业务逻辑，只消费业务 dict
- **Executor**: 独立决策者，组装各层 NOTIFY → prompt → LLM → action

> 每层 Manager 的 `query()` 在 while 循环中调用 Agent `decide()`，`max_rounds` 可配置（L1=5, L2=3, L3=3，见 `config.yaml:runtime`）。Agent 通过 capture_tool（l1_query/l1_report 等）声明 done 与否，控制循环退出。

---

## 执行路径

**新架构** — 独立环境 + 共享层链：

```
                    ToolUse（工具系统，跨环境共享）
                        ↑
  ┌─────────────────────┼──────────────────────────┐
  │  GameEnv (Leduc)    │  LearningEnv              │
  │  env.step(action)   │  env.step(action)         │
  │  → state+reward     │  → knowledge diff         │
  └─────────┬───────────┘  └──────────┬──────────────┘
            └──────────┬──────────────┘
                       ▼
            ┌──────────────────────┐
            │  Executor + Layers   │
            │  (L(0.5+1)↔L2↔L3)   │
            └──────────────────────┘
```

- **GameEnv**: 原始认知任务环境（Leduc/DouZero），产生 `ExecutionRecord` → 入 LearningEnv
- **LearningEnv**: 读取 pending records，将学习建模为标准 env.step
- **Executor**: 对两个环境完全无感，只发 `TaskObservation` 收 action
- **ToolUse**: GameEnv 和 LearningEnv 共享

**Execute 详细流程：**

```
Executor ──LayerMessage(QUERY)──→ L(0.5+1)→L2→L3
 各层 Manager while 循环调用 Agent.decide()（capture_tool 控制 done）
 RESPONSE 链返回 → 各层 NOTIFY → Executor 组装 prompt
 Executor → LLM → parse action → AgentRuntime
 ExecutionRecord → pending/
```

---

## 各层详解

### L0.5 数据模块

仍作为数据对象保留，但不再作为独立层运行：

- **Philosophy** (`core/philosophy.py`)：Rule.source 区分 L0.5 宪法（不可变）和 L1 行为规则（可变，反射可修改）。内置校验器（not_duplicate/no_contradiction）已迁入 Philosophy.add_rule/modify_rule（原 MetaDriver 已解散）
- **FlexibleKnowledge** (`core/flexible_knowledge.py`)：KnowledgeCard 管理，SQLite 后端
- **SkillLayer** (`core/skill_layer.py`)：SKILL.md 管理，支持 create/edit/delete，SQLite 后端

### L(0.5+1) — 合并宪法 + 行为准则层

`core/layers/l0_5_1/manager.py`，由 **L1Agent（while-loop decide）** 驱动：

- L0.5 rules (`source="l0_5"`)：通用认知原则，仅在配置中手工修改
- L1 rules (`source="l1"`)：领域相关行为准则，反射可添加/修改/删除

```
L0_5_1Manager.query(msg)
  while round ≤ max_rounds:
    L1Agent.decide(meta, state, history, tools, layer)
      → capture_tool: l1_query(done=false, 向 L2 查询) / l1_report(done=true, 最终决策)
    if done: break
    else: propagate query → L2 → 收集 NOTIFY
  → NOTIFY {done, result, reasoning}
```

### L2 — Flexible Knowledge（柔性知识层）

`core/layers/l2/manager.py`，由 **L2Agent（while-loop decide）** 驱动：

```
L2Manager.query(msg)
  while round ≤ max_rounds:
    L2Agent.decide(query, meta, state, context, tools, layer)
      → capture_tool: l2_query(done=false, 向 L3 查询) / l2_report(done=true, 最终回复)
    if done: break
    else: propagate queries_to_L3 → L3 → 收集 NOTIFY
  → NOTIFY {reply, cards, reasoning}
```

- **领域检索**：通过 DomainRegistry 反向索引按 domain 检索知识卡片（`get_domain_cards`）
- **质量字段**：`usefulness` / `misleading` / `comment`，通过 modify_l2_card 工具更新

### L3 — Skill Layer（技能层）

`core/layers/l3/manager.py`，包裹 SkillLayer + L3Agent（LLM decide）：

- **确定性匹配**：基于 DomainRegistry 反向索引按 domain 匹配技能（`get_items_for_domains`），回退到 `SkillLayer.match()`
- **Skill CRUD**：`create_skill` / `edit_skill` / `delete_skill`
- **L2→L3 编译**：同域 ≥3 卡片 → LLM 编译为 SKILL.md

---

## 工程实施策略 (Phase 1)

### 环境与范围

- **Phase 1 使用 RLCard 卡牌游戏环境**，环境直接返回客观评估信号
- **Phase 1a**: Leduc Hold'em（简化德州扑克，信息集 10²，CFR 对手）
- **Phase 1b**: Dou Dizhu（斗地主，信息集 10⁵³~10⁸³，DouZero 对手）
- **Phase 1.5（已完成）**：Comm Agent + LayerMessage 链式通信 + Agent while-loop decide 设计
- **L4 暂不实现**

### 评估策略（双轨）

**轨道 A — 环境反馈：** RLCard 直接返回赢/输/得分。

**轨道 B — 对话片段评估：** 以对话轮次为切分边界，LLM 判断意图连续性，连续意图的片段合并为一个 Task。

### 编排者分层（TODO）

编排者**横向分层**（而非 Agent 层的竖向分层）：

```
Orchestrator (横向分层):
  ┌──────────────────────┐
  │ Task Decomposer      │  ← 接收用户请求，分解为大 Task
  └──────────┬───────────┘
             ▼
  ┌──────────────────────┐
  │ Task Runner(s)       │  ← 每个 Task 一个实例
  └──────────┬───────────┘
             ▼
  ┌──────────────────────┐
  │ Meta Learner         │  ← 跨 Task 分析：识别模式、合并经验
  └──────────────────────┘
```
