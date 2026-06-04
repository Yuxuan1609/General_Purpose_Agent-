# Cognitive Agent

基于 4.5 层认知架构的 AI 智能体系统。受 ACT-R、Soar、CoALA、Constitutional AI、Reflexion 等理论启发，构建具备分层可演化记忆的自适应学习闭环。

## 架构概览

L0.5 和 L1 合并为 **L(0.5+1)**，三层链式通信：

```
AgentRuntime → Executor → L(0.5+1) ↔ L2 ↔ L3
                              ↑ 链式相邻传递 (A1)
```

| 层 | 原对应 | 职责 |
|----|--------|------|
| **L(0.5+1)** | L0.5 + L1 | 不可变宪法 + 可演化行为规则；含 **L1Agent（两阶段 V-structure）** |
| **L2** | FlexibleKnowledge | 概率性知识卡片；含 **L2Agent（三阶段 V-structure）** |
| **L3** | SkillLayer | SKILL.md 技能执行；domain 确定性匹配 + **L3Agent（LLM 选择+执行）** |
| **L4**（预留） | — | 静态知识存储，L3 dispatch 目标 |

> **L1-L4 每层都在执行**：任务分派到各层后，每层基于自己持有的信息和 LLM Agent 独立执行认知任务。区别在于执行"重量"——L2/L3 涉及检索+筛选+推理，较重；L1（行为准则匹配）和 L4（静态知识查询）相对轻量。游戏环境（Leduc）中差异不显著（任务粒度小、技能含策略描述）；通用任务（编程、搜索）中差异更明显。

> **抽象知识逐层下渗**：Execute 和 Reflect 阶段都遵守同一原则——上层产出相对抽象的指令/问题，传递到下层时逐步细化为更具体的操作。Execute 段 L1 提出查询方向→L2 筛选知识卡片→L3 匹配并执行技能；Reflect 段同理，L1 指出问题领域→L2 定位具体卡片→L3 更新技能内容。当前架构已具备此能力（V-structure + LayerMessage + Comm Agent），具体效果取决于每层 LLM 的提示词和输出格式要求。

每层 Manager 驱动 V-structure 循环：**Agent（LLM 决策）↔ Manager（编排/状态管理）↔ Comm Agent（确定性协议）**，通过 `AgentPacket` 跨层传递内部 Agent 通信。

### 通信协议 (Phase 1.5 — 已实现 ✅)

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

> **Note**: 当前层间通信为**单次 QUERY-RESPONSE** 模式。后续可能改为**对话式**交互——允许多轮往返，如同层间"讨论"直到确认信息充分。此变更将影响通信协议和日志格式。

### 执行路径（双轨）

项目同时存在两套执行路径：

**新架构（推荐）** — 独立 `Executor` + 链式 `LayerManager`：

```
  ┌────────────────────────────────────────────────────┐
  │  PHASE 1: EXECUTE (Executor.execute)                │
  │  Executor ──LayerMessage(QUERY)──→ L(0.5+1)→L2→L3  │
  │  各层 Manager 驱动 V-structure Agent 循环           │
  │  RESPONSE 链返回 → 各层 NOTIFY → Executor 组装 prompt │
  │  Executor 调用 LLM → parse action → AgentRuntime    │
  │  ────────────────────────────────────────────────── │
  │  enable_learning=True → ExecutionRecord → pending/   │
  │  ────────────────────────────────────────────────── │
  │  PHASE 2: REFLECT & LEARN (Orchestrator 存 stub)     │
  │  pending/ 积攒 → 阈值触发 → ReflectionAgent 递归判责   │
  └────────────────────────────────────────────────────┘
```

**旧架构（`main.py` / `CognitiveAgent`）** — 仍用于通用问答任务：

```
  while 循环:
    LLM 决策 → 工具分发 → L0.5 安全过滤 → L1/L2/L3 上下文注入
    → 完成检测 / 最大迭代终止 → post_task() 反思
```

## 设计原则

项目遵循两层设计原则：**架构原则**（定义层间通信协议，是系统骨架）和**工程原则**（定义代码实施规范，是开发纪律）。

### 架构原则

#### A1：层间严格相邻传递

1. 认知层（L0.5 / L1 / L2 / L3 / L4）之间**状态变更和数据请求必须通过相邻层传递**，禁止跨层跳跃。例如：L0.5 不能直接读写 L2 数据——必须经过 L1 转发。
2. 存在一个全局 **Orchestrator**，承担任务编排、流程控制、资源管理、全局状态监控、错误恢复决策等多重职责（不限于事件循环）。Orchestrator 可以**读取观察**所有层状态、向任意层发送调度指令，但**不绕过相邻传递规则直接修改层内数据**，也不替代层间业务数据流的消息传递。
3. 相邻传递约束的是**信息流向**（谁可以和谁交流），不约束**交互次数**。一个逻辑阶段内相邻层之间可以进行多轮往返查询。

```
                    ┌──────────────┐
                    │ Orchestrator │  ← 全局编排者（任务编排/资源管理/错误恢复等），
                    │              │    可观察所有层状态、发送调度指令，
                    └──┬──┬──┬──┬──┘    但不越过相邻传递规则操作层内数据
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

**当前代码中违反此原则的已知点**（供后续重构参照）：

> Phase 1 + 1.5 重构后，星型通信已替换为链式相邻传递。以下违规点为旧架构残留：

| 违规点 | 位置 | 当前行为 | 目标行为 |
|--------|------|----------|----------|
| POST-TASK 学习闭环 | `core/layer_context.py:post_task()` | MetaDriver 对 L1/L2/L3 直接操作 | 反思结果→L1→L2→L3 逐级转发（Phase 2） |
| 事件循环直接读 L1 规则 | `core/agent_loop.py:_build_system_prompt()` | 直接调用 `layers.l1.all_rules()` | 通过 `build_chain()` 统一入口（已部分修复） |

#### A2：统一层间消息信封

1. 所有层间通信必须使用 `LayerMessage` 结构，格式如下：

```python
@dataclass(frozen=True)
class LayerMessage:
    source: str          # 发送层标识，如 "L0.5", "L1", "L2", "L3", "ORCHESTRATOR"
    target: str          # 接收层标识
    type: MessageType    # 基础信封类型（见下表）
    subtype: str         # 层级定制语义，如 "L2_to_L3:COMPILATION_SIGNAL"
    payload: Any         # 具体业务数据
    trace_id: str        # 跨层追踪 ID（同一任务共享）
    timestamp: datetime  # 发送时间
    metadata: dict       # 扩展字段（priority, ttl, correlation_id 等）
```

2. 基础信封类型（`MessageType`）：

| type | 方向 | 含义 |
|------|------|------|
| `QUERY` | 上层→下层 | 请求下层提供数据/服务 |
| `RESPONSE` | 下层→上层 | 对 QUERY 的应答 |
| `PROPOSAL` | 下层→上层 | 下层向上层提议变更（如 L1 提议新规则） |
| `APPROVAL` | 上层→下层 | 上层批准下层提案 |
| `REJECTION` | 上层→下层 | 上层驳回下层提案（含原因） |
| `NOTIFY` | 任意方向 | 单向通知，无需回复 |

3. `subtype` 字段用于不同层组合的定制化语义（如 L2→L3 的编译信号与 L1→L0.5 的规则变更提议需要不同的上下文信息）。**当前实现阶段以 6 种基础类型满足需求，`subtype` 预留扩展。**

4. `LayerMessage` 封装为独立模块（`core/layer_message.py`），**易于独立调整和扩展**，不与其他层实现耦合。

#### A3：层内 Agent 分工与信息隔离

核心思路：通过分层实现**信息隔离 + 职责匹配**。每层不是单一类，而是由多个专职 Agent 组成的微型集群。每个 Agent 只能读写本层信息、只能执行本层职责。

**每层最小 Agent 集合：**

```
Layer N:
  ┌──────────────────────────────────────────────────┐
  │                                                   │
  │  ┌──────────────┐   ┌──────────────┐              │
  │  │ UpwardComm   │   │ DownwardComm │   ← 相邻层通讯   │
  │  │ Agent        │   │ Agent        │              │
  │  └──────┬───────┘   └──────┬───────┘              │
  │         │                  │                      │
  │         └────────┬─────────┘                      │
  │                  ▼                                │
  │         ┌──────────────┐                          │
  │         │ LayerManager │   ← 本层信息管理/业务逻辑     │
  │         └──────────────┘                          │
  └──────────────────────────────────────────────────┘
```

| Agent | 职责 | 典型执行方式 |
|-------|------|-------------|
| **LayerManager** | 管理本层核心数据（增删改查）、执行业务逻辑（激活计算/衰减/编译判断/规则变更）、接收 Comm Agent 路由来的请求 | 确定性方法为主；部分决策可由 LLM 辅助 |
| **UpwardComm** | 与上一层通信：接收上层消息→解析校验→转发 LayerManager；接收 LayerManager 回复→封装 LayerMessage→发回上层 | 确定性协议处理，无需 LLM |
| **DownwardComm** | 与下一层通信：接收下层消息→解析校验→转发 LayerManager；接收 LayerManager 请求→封装 LayerMessage→发送下层 | 确定性协议处理，无需 LLM |

**Agent 执行模型（Agent 不一定是 LLM 调用）：**

| 类型 | 适用场景 | 示例 |
|------|----------|------|
| 确定性 Agent | 规则引擎、协议处理、匹配算法 | L3Manager 技能匹配、Comm Agent 消息序列化、KnowledgeCard 激活值计算 |
| LLM Agent (V-structure) | 多阶段推理决策 | **L1Agent**（两阶段：知识需求→最终决策）、**L2Agent**（三阶段：节点选择→卡片过滤+L3决策→整合 NOTIFY） |
| LLM Agent | 反思分析、知识提取 | MetaDriver 反思、L2→L3 编译 |
| 混合 Agent | 确定性逻辑为主，特定节点委托 LLM | L1 Manager：规则 CRUD 走确定性，规则提案评估可走 LLM |

**信息隔离原则：**
- L0.5 的 Agent 不会收到 L2 的知识卡片内容——只能通过 L1 看到经过筛选和格式化的行为规则
- L2 的 Agent 不关心 L3 的 SKILL.md 格式——只管知识卡片的置信度和激活值
- 每一层只暴露其相邻层需要的最小信息集

**Agent 依赖图**（A1+A3 的支撑数据结构）：

Agent 总量虽大（~15 个），但单节点最大出度不超过 3-4 条边。通过有向图建模 Agent 间通信拓扑，服务于四个工程场景：

| 用途 | 说明 |
|------|------|
| **静态路由表** | Agent 发消息只关心 direction + type，目标 Agent 由图解析，无需硬编码 |
| **影响范围分析** | 改动任意 Agent → 从图 BFS 出受影响节点集合 → 精确重测范围 |
| **启动/关闭拓扑排序** | L0.5→L1→L2→L3 逐层启动，关闭反序，消除初始化和销毁的竞态条件 |
| **消息流追踪** | `trace_id` 串联路径 + 图回溯 → 异常时反向定位出问题的节点 |

#### A4：任务单元学习循环

核心思路：以 **Task 为最小执行和评估单元**，将 Agent 的整体行为拆分为 Execute → Evaluate → Reflect & Learn 两个宏观步骤。受强化学习中"行动-评估-改进"循环启发。

```
用户输入 / 训练数据
        │
        ▼
  ┌─────────────┐
  │ Orchestrator │  分解为 Task₁, Task₂, Task₃ ...
  └──────┬──────┘
         │
         ▼
  ┌──────────────────────────────────────────┐
  │  对每个 Task:                             │
  │                                          │
  │  ① EXECUTE                               │
  │     层间相邻协作（遵循 A1），产出最终响应     │
  │     可以包含多轮对话、多次工具调用            │
  │                                          │
  │  ② EVALUATE                              │
  │     评估执行质量：                          │
  │     - 目标达成？(binary)                   │
  │     - 效率如何？(iterations, token 消耗)    │
  │     - 中间步骤得分？(intermediate reward)   │
  │                                          │
  │  ③ REFLECT & LEARN                       │
  │     基于评估结果，通过链式通道（A1）驱动学习：  │
  │     Orchestrator → L1 → L2 → L3          │
  │     - 提取知识卡片 (L2)                    │
  │     - 修正/新增行为规则 (L1)                │
  │     - 编译高频模式为技能 (L2→L3)            │
  │     - 标记失败模式避免重复 (L0.5 验证器)      │
  └──────────────────────────────────────────┘
```

**设计动机：**

1. **可评估性**：Task 是天然的最小评估单元。"修一个 bug" → 可以判断修没修好。"搜论文" → 可以判断搜到没有。
2. **细粒度反馈**：长任务拆成子 Task，每个单独评估。即使整体失败，也知道是哪个步骤出问题——比"整段对话结束后来一次全局反思"精准得多。
3. **RL 视角**：Task 评估 = reward signal。多次执行同类 Task → 累积多个 reward → L1/L2 演化有统计依据。这比单次启发式的 `boost()/penalize()` 更可靠。
4. **跨 Task 知识迁移**：Task 通过 `Domain` 关联。`Domain("coding/python")` 下的失败经验可被同域 Task 复用。

**执行与反思的严格分离：**

- Execute 阶段：LLM 在工作，层间协作产出行动。此时不做学习。
- Reflect & Learn 阶段：LLM 已停止，基于评估结果驱动层间知识更新。
- Orchestrator 确保 EXECUTE 完成后再进入 REFLECT，不交错。

**执行与反思的环境隔离：**

- Execute 阶段：Agent **独占**环境交互权（读写）——发送动作、接收状态、获取 reward
- Reflect & Learn 阶段：Agent **只读**执行记录（messages 日志 / 工具调用序列 / 环境返回的 reward），禁止对环境发起任何写入或回放
- Task 间环境隔离：本质上是多进程并发问题。通过**串行执行**天然避免——同一时间只有一个 Task 持有环境实例和环境状态的读写权
- **批量反思策略**：不每条 Task 单独反思。以 5-10 条 Task 为一个 batch，串行执行完毕后统一进行 batch 级反思。好处：
  - 环境状态不会跨 Task 泄漏（串行天然保证）
  - 反思开销摊销到一批 Task（减少 LLM 调用次数）
  - batch 内跨 Task 的模式在反思时自然可见（呼应 Orchestrator 中 Meta Learner 的职责）

```
Batch₁: Task₁ → Task₂ → ... → Task₅ → Batch Reflect₁
Batch₂: Task₆ → Task₇ → ... → Task₁₀ → Batch Reflect₂
```

**与 A1/A2/A3 的关系：**
- A1 约束 **信息怎么流**（相邻传递）
- A2 约束 **信息用什么格式流**（LayerMessage）
- A3 约束 **谁在层内处理信息**（Agent 分工）
- A4 约束 **什么时候学**（Task 级别的 Execute→Reflect 循环）

### 工程实施策略 (Phase 1)

#### 环境与范围

- **Phase 1 使用 RLCard 卡牌游戏环境**，环境直接返回客观评估信号（赢/输/得分），解决 A4 中"评估信号从哪里来"的问题
- **分阶段推进难度**：
- **Phase 1a**: Leduc Hold'em（简化德州扑克，信息集 10²，使用预训练 CFR 模型作为对手）
  - **Leduc 仅用于跑通 Agent 的迭代学习闭环（Execute → Reflect → Learn）**，验证 L0.5/L1/L2/L3 层间通信和知识演化机制是否正常工作。Leduc 是简化环境，不做深度博弈优化。
- **Phase 1b**: Dou Dizhu（斗地主，信息集 10⁵³~10⁸³，使用 DouZero 预训练权重作为对手）
  - 验证 Agent 在复杂不完全信息博弈中的自适应能力
- **后续方向**: 转向通用博弈智能 —— 参考 AlphaGo General 思路，从单一卡牌游戏泛化到多游戏、多领域决策，目标是构建领域无关的认知决策架构
- **棋类扩展**: `python-chess` + Stockfish（限制 ELO 1200-1800）作为更强的棋类对手。纳什均衡级 bot（如 RLCard 预训练 CFR）已被现代 LLM 达到 ~50% 胜率，不再构成挑战。Game 环境仅是验证手段，跑通后转移到真实世界任务
- **Phase 1.5（已完成）**：Comm Agent + LayerMessage 链式通信 + V-structure Agent 实现
  - `core/layers/` 三层链式 Manager（L0_5_1 → L2 → L3）
  - 每层 Manager 驱动 V-structure Agent 循环
  - Executor 独立决策，旧 CognitiveAgent/AgentLoop 仍用于通用任务
- **L4 暂不实现**，仅保留 L0.5 + L1 + L2 + 极简 L3
  - L3 保留 skills 框架但内容从简
  - 工具代码保留但不作为 Phase 1 测试重点
- 核心验证目标：L1↔L2 的学习闭环能否在闭环环境反馈下自主演化

#### 评估策略（双轨）

**轨道 A — 环境反馈：** RLCard 直接返回赢/输/得分。客观信号，无 LLM bias。

**轨道 B — 对话片段评估：**

```
原始聊天记录:
  User: 帮我解决 X
  Agent: 先分析... [tool call] ... 结果 A
  User: 不对，应该用方法 Y
  Agent: 好，用 Y ... 结果 B ✓

切片（以轮次为边界）:
  Segment₁: User"帮我解决X" → Agent"分析...结果A"
  Segment₂: User"用方法Y"   → Agent"结果B"
```

- 以**对话轮次**为切分边界（而非语义切分）
- 切分时调用 LLM 判断相邻两个轮次的**用户意图连续性**——逻辑简单可控
- 连续意图的片段合并为一个 Task，中断处自然形成 Task 边界
- 片段级评估比整段评估细粒度更高（知道哪个步骤出问题）

#### 编排者分层（TODO）

> 核心方向已确定：编排者**横向分层**（而非 Agent 层的竖向分层），不同编排者承担不同任务。具体层数待细化。

```
Orchestrator (横向分层):
  ┌──────────────────────┐
  │ Task Decomposer      │  ← 接收用户请求，分解为大 Task
  └──────────┬───────────┘
             │
             ▼
  ┌──────────────────────┐
  │ Task Runner(s)       │  ← 每个 Task 一个实例，管理执行/评估/反思
  └──────────┬───────────┘
             │
             ▼
  ┌──────────────────────┐
  │ Meta Learner         │  ← 跨 Task 分析：识别模式、合并经验
  └──────────────────────┘
```

### 工程原则

| 编号 | 原则 | 核心要求 |
|------|------|----------|
| E1 | **模块化与单一职责** | 每文件仅承担一项可陈述的职责；入口文件不寄生业务逻辑 |
| E2 | **接口先行与依赖倒置** | 每层暴露 Protocol/ABC；组件依赖抽象而非具体实现；`__init__.py` 定义公共 API |
| E3 | **不可变数据优先** | 数据类型默认 frozen dataclass；状态变更返回新实例而非原地修改 |
| E4 | **原子持久化** | 所有文件写入使用 `tempfile + replace` 模式，保证崩溃安全 |
| E5 | **工具系统标准化** | 统一 `register(schema, handler)` 接口；handler 签名一致；错误返回 JSON `{"error": "..."}` |
| E6 | **测试先行** | 每个模块必须有对应测试文件；使用 mock 隔离外部依赖；共享 fixture 集中于 `conftest.py` |
| E7 | **配置与代码分离** | 环境相关值一律通过 `config.yaml` + 环境变量注入；无硬编码路径/密钥 |
| E8 | **错误边界与可观测性** | 明确每层的错误捕获策略（重试/降级/失败）；关键跨层调用记录结构化日志 |

## 快速开始

### 环境要求

- Python >= 3.11
- DeepSeek API Key（或其他 OpenAI 兼容端点）

### 安装

```bash
git clone <repo-url>
cd General_Purpose_Agent--master
pip install -e ".[dev]"
```

### 配置

1. 设置环境变量：

```bash
# Windows
set DEEPSEEK_API_KEY=your-key-here

# Linux / macOS
export DEEPSEEK_API_KEY=your-key-here
```

也可在项目根目录创建 `.env` 文件：

```
DEEPSEEK_API_KEY=your-key-here
```

2. 编辑 `config.yaml` 调整模型与参数（可选）：

```yaml
main_llm:
  provider: deepseek
  model: deepseek-chat
  api_key_env: DEEPSEEK_API_KEY
  base_url: https://api.deepseek.com

max_iterations: 50
l1_max_rules: 20
l1_max_rule_length: 100
```

### 运行

```bash
# 直接启动（打印各层状态）
python main.py

# 执行任务
python main.py "explain how Python's asyncio works"
```

### 运行测试

```bash
pytest tests/ -v
```

### RLCard 环境 (Phase 1)

RLCard 为卡牌游戏强化学习环境，无需 WSL，Windows 原生运行。

**安装：**

```bash
pip install rlcard[torch]
```

**可用游戏：**

| 游戏 | 状态空间 | 动作空间 | 预设 AI 对手 |
|------|---------|---------|------------|
| Leduc Hold'em | 10² | 4 | 预训练 CFR（纳什均衡级） |
| Dou Dizhu（斗地主） | 10⁵³~10⁸³ | ~27K | 规则模型 v1（→ Phase 1b 换 DouZero） |
| Limit Texas Hold'em | 10¹⁴ | 4 | 规则模型 v1 |
| Mahjong（麻将） | 10¹²¹ | 38 | — |
| No-limit Hold'em | 10¹⁶² | 5(抽象) | — |
| UNO | 10¹⁶³ | 61 | 规则模型 v1 |
| Gin Rummy / Bridge | — | 110/91 | Gin Rummy novice / Bridge 规则 |

**Phase 1a 验证路径：**

```
RLCard(Leduc) → env.step(action) → 状态 + reward
       ↓
LLM Agent 决策 → 提交 action → 获取下一步
       ↓
执行完毕 → 评估输赢 → Reflect & Learn 更新 L1/L2/L3
       ↓
循环（多局 batch 后批量反思）
```

#### Phase 1b 架构 — DouZero + LLM Agent

Phase 1b 使用 DouZero 原生 GameEnv 作为游戏引擎，将 LLM Agent 作为三个玩家之一接入，与 DouZero 预训练 DeepAgent 对局。

```
GameEnv.step()
  │
  ├─ ① 取当前玩家 infoset (InfoSet)
  ├─ ② player.act(infoset) → list[int]        ← 所有 Agent 统一接口
  │       │
  │       ├─ DeepAgent:  模型前向推理 → argmax
  │       ├─ LLMAgent:   build_prompt → LLM.chat() → parse_action
  │       └─ RandomAgent: random.choice(legal_actions)
  │
  ├─ ③ 处理出牌 → 更新 hand_cards / played_cards / action_seq / bomb_num
  ├─ ④ 判断 game_over
  └─ ⑤ 切换 acting_player_position → 生成新 infoset → 下一轮
```

```
示例对局:
  landlord      → DeepAgent (baselines/douzero_ADP/landlord.ckpt)
  landlord_up   → DouZeroLLMAgent (DeepSeek API)
  landlord_down → DeepAgent (baselines/douzero_ADP/landlord_down.ckpt)
```

**用法：**
```bash
#  直接 LLM 模式（默认，绕开认知层，独立 prompt）
python scripts/run_douzero_llm.py --llm_position landlord_up --episodes 10 --step_verbose

#  认知链模式（通过 Executor + LayerChain 决策）
python scripts/run_douzero_llm.py --llm_position landlord_up --episodes 10 --mode cognitive

# 完美信息（可看到对手手牌）
python scripts/run_douzero_llm.py --llm_position landlord_up --episodes 10 --step_verbose --perfect_info

# dry-run 快速验证流程
python scripts/run_douzero_llm.py --dry_run --episodes 10
```

**DouZero 权重**（已预置）：
```
baselines/
  douzero_ADP/   # ADP 奖励训练的 DouZero
  douzero_WP/    # WP 奖励训练的 DouZero
  sl/            # 监督学习基线
```

## 各层详解（新架构）

### L0.5 数据模块（旧层内部直接使用）

仍作为数据对象保留，但不再作为独立层运行：

- **MetaDriver** (`core/meta_driver.py`)：4 个反射触发器（stagnation/task_failed/task_completed/domain_shift）、2 个验证器（not_duplicate/no_contradiction）、危险工具过滤
- **Philosophy** (`core/philosophy.py`)：L1 规则 CRUD，持久化到 `data/l1_rules.json`，种子规则在 `config/l1.yaml`
- **FlexibleKnowledge** (`core/flexible_knowledge.py`)：KnowledgeCard + KnowledgeGraph，MD+JSON 双存
- **SkillLayer** (`core/skill_layer.py`)：SKILL.md 管理，L2→L3 编译

### L(0.5+1) — 合并宪法 + 行为准则层

`core/layers/l0_5_1/manager.py` 将 L0.5 和 L1 合并为一个 Manager，由 **L1Agent（两阶段 V-structure）** 驱动：

```
L1Agent.stage1(meta, state)
  → 判断"需要从下层获取什么知识" → query text
  → 写入 obs.state["l1_query"] → 通过 AgentPacket 传到 L2

L1Agent.stage2(meta, state)
  → 整合 L2 返回的知识卡片 + 行为准则 → 最终决策
  → 输出 {done, result, reasoning}（DeepSeek JSON mode）
```

- **L1Agent** 系统 prompt 注入：游戏规则 + 行为准则（L1 rules）+ 任务目标
- **L0_5_1Manager** 编排 V-structure 循环（当前 MAX_LOOPS=1）
- 通过 `DownwardComm` 将 `AgentPacket(query)` 传递给 L2

### L2 — Flexible Knowledge（柔性知识层）

`core/layers/l2/manager.py` 包裹 FlexibleKnowledge，由 **L2Agent（三阶段 V-structure）** 驱动：

```
L2Agent.stage1(query, meta, state)
  → LLM 对领域节点打分（name + score + reason）
  → 选 top-5 节点（目前 seed 两个：game/leduc, game/doudizhu）

L2Agent.stage2(query, meta, state, selected_nodes)
  → 检索节点下知识卡片 → LLM 筛选 ≤15 张
  → 判断是否需要调 L3 → {cards, call_l3, l3_task}

L2Agent.stage3(query, meta, state, selected_nodes, stage2_result)
  → 整合 L3 返回的技能内容 → 最终 NOTIFY
  → {reply, cards, reasoning}
```

- **激活值计算**：`activation = confidence × (domain_match_score × 0.6 + recency_score × 0.4)`
- **领域匹配**：exact=1.0 / parent=0.7 / child=0.5 / general=0.4 / unrelated=0.0
- **KnowledgeGraph**：2 跳扩散激活（`spread_activation()`）

### L3 — Skill Layer（技能层）

`core/layers/l3/manager.py` 包裹 SkillLayer，**纯确定性（无 LLM）**：

- **匹配**：精确域 > 父域 > general 跨域 > 根域
- **Skill CRUD**：`create_skill` / `edit_skill` / `patch_skill` / `delete_skill`
- **L2→L3 编译**：同域 ≥3 卡片且平均激活值 > 0.7 → LLM 编译为 SKILL.md
- 注册工具：`skills_list` / `skill_view` / `skill_manage`

## 工具系统

基于单例 `ToolRegistry`，线程安全，支持 `check_fn` 条件过滤和 `toolset` 分组。

| 工具 | 功能 | 注册位置 |
|------|------|----------|
| `todo` | 子任务跟踪（pending/in_progress/completed/cancelled） | `core/tools/todo_tool.py` |
| `terminal` | 命令行执行（30s 超时，可选命令白名单） | `core/tools/terminal_tool.py` |
| `web_search` | DuckDuckGo 网络搜索（无需 API Key） | `core/tools/web_search_tool.py` |
| `skills_list` | 列出已注册技能 | `core/skill_layer.py` |
| `skill_view` | 查看技能详细内容 | `core/skill_layer.py` |
| `skill_manage` | 创建/编辑/删除技能 | `core/skill_layer.py` |

## 项目结构

```
cognitive-agent/
  main.py                     # 入口（旧架构）：配置加载 → CognitiveAgent → 任务执行
  config.yaml                 # 用户配置
  pyproject.toml              # 项目元数据与依赖
  config/                     # 分层配置文件
    l1.yaml                   # L1 行为规则种子 (max: 20, ≤300字/rule)
    l2.yaml                   # L2 激活权重、衰减率、limits (≤10 cards/query)
    l3.yaml                   # L3 编译阈值、匹配分数、limits (≤15 skills/query)
  core/                       # 核心源代码
    types.py                  # TaskObservation, ExecutionRecord
    executor.py               # Executor — 独立决策者（新架构入口）
    llm_client.py             # LLMResponse + LLMClient
    layer_message.py          # LayerMessage 信封 + MessageType 枚举 (A2)
    config.py                 # AgentConfig dataclass
    task.py                   # Domain, Task, TaskResult, TaskContext
    agent.py / agent_loop.py  # CognitiveAgent + AgentLoop（旧架构）
    layer_context.py          # 旧星型桥接（旧架构用）
    meta_driver.py            # L0.5 触发器 + 验证器
    philosophy.py             # L1 规则 CRUD
    flexible_knowledge.py     # L2 知识卡片 + KnowledgeGraph
    skill_layer.py            # L3 技能 + L2→L3 编译
    env/                      # 环境抽象 (ABC)
      base.py                 # Environment, EnvState, EnvStep
    layers/                   # 新架构：三层链式 Manager + Comm Agent
      base.py                 # LayerManager ABC + LayerAgent ABC + ReflectionAgent ABC
      comm.py                 # UpwardComm/DownwardComm + AgentPacket
      __init__.py             # build_chain() — 自底向上构建
      l0_5_1/                 # L(0.5+1)Manager + L1Agent (V-structure)
      l2/                     # L2Manager + L2Agent (V-structure)
      l3/                     # L3Manager (确定性，无 LLM)
    orchestrator/             # Phase 2: 编排器（stub）
      task_runner.py          # AgentStub
      task_decomposer.py      # AgentStub
      meta_learner.py         # AgentStub
    tools/
      registry.py             # ToolRegistry 单例（线程安全）
      todo_tool.py            # 子任务跟踪
      terminal_tool.py        # 命令行执行
      web_search_tool.py      # DuckDuckGo 搜索
    l0_5/ l1/ l2/ l3/ l4/    # 旧层 stub（逐步淘汰）
  scripts/                    # 运行脚本
    run_leduc_cognitive.py    # Leduc 对局 — seed L1/L2/L3 + chain 日志
    leduc_cognitive_agent.py  # LeducCognitiveAgent — RLCard接口+Executor
    run_douzero_llm.py        # DouZero 对局 (--mode direct|cognitive)
    douzero_agent.py          # DouZeroLLMAgent + DouZeroCognitiveAgent
    run_rlcard.py             # RLCard 通用测试
    run_llm_leduc.py          # LLM 直接 vs Leduc（绕开认知层）
    process_stats.py          # CSV 数据处理
    run_parallel_test.py      # 并行 Leduc 测试
  data/                       # 运行时数据
    l1_rules.json             # L1 持久化
    learning/pending/         # ExecutionRecord 待反思
  knowledge/                  # L2 知识 MD + l2_index.json
    game/leduc/               # Leduc Hold'em 策略
    game/doudizhu/            # 斗地主策略
  skills/                     # L3 技能 SKILL.md
    game/leduc/               # leduc-preflop-raise, leduc-postflop-pair
    game/doudizhu/            # doudizhu-top-card
  logs/                       # 运行日志
  tests/                      # pytest (19 test files)
  docs/                       # 设计文档
```

## 实现计划

| 阶段 | 文档 | 状态 |
|------|------|------|
| Phase 1 — Execute 链路 | `docs/superpowers/plans/...-implementation.md` | ✅ 已完成 |
| Phase 1.5 — Comm Agent + LayerMessage + V-structure | `docs/superpowers/plans/...-implementation-phase1.5.md` | ✅ 已完成 |
| Phase 2 — Reflect & Learning + Orchestrator | `docs/superpowers/plans/...-implementation-phase2.md` | 🚧 Orchestrator stub 就绪，核心逻辑待实现 |

## 架构设计文档

| 文档 | 说明 |
|------|------|
| `docs/superpowers/specs/2026-06-03-agent-communication-design.md` | **当前架构 v2**：三层链式通信、Executor 独立决策、V-structure Agent |
| `docs/superpowers/specs/2026-06-03-agent-communication-design-phase2.md` | **Phase 2**：ReflectionAgent 递归判责、Task Decomposer、学习管道 |
| `docs/4.5-layer-agent-design.md` | 初始架构设计，含 TextWorld 验证策略与冷启动方案 |
| `docs/cognitive-agent-design-v2.md` | 详细设计文档（~1500+ 行），含伪代码与数据结构模式 |
| `docs/cognitive-agent-phase1-plan.md` | 分阶段实现计划（~1800+ 行），TDD 风格逐步分解 |
| `docs/4.5-layer-agent-references.md` | 33 篇学术/开源参考文献（CoALA, Reflexion, Voyager, MemGPT, HippoRAG 等） |
| `docs/voyager-skill-system-detail.md` | Voyager 技能系统详解 — L3 SKILL.md 格式参考 |
| `docs/reflexion-architecture-detail.md` | Reflexion 架构详解 — ReflectionAgent 递归判责模式 |
| `docs/environment-setup.md` | RLCard + DouZero 环境配置说明 |

## 长期规划 / Future Work

### 1. Short Circuit：同 Session 信息复用

当前每次 `Executor.execute()` 都完整执行全链路（L1 Stage1 → L2 Stage1/2/3 → L3 → L1 Stage2）。对于同一 session 内的连续步骤（或 `meta` 字段高度相似的任务），大部分层间通信结果可以复用：

- **策略**：检测当前 `meta` + `state.current` 与上一步相比是否发生变化。若未变，直接沿用上一步的 L2/L3 NOTIFY 结果，跳过 LLM 调用
- **复杂度**：只需在 `Executor` 层维护一个轻量缓存，`_assemble_context()` 中比对 hash 决定是否短路
- **收益**：典型博弈场景（如 Leduc/DouZero）每步状态变化小而多，可节省 60-80% 的 LLM 调用

### 2. 多轮对话与会话并发

从当前单步决策扩展到多轮对话场景时，需要解决：

- **历史会话管理**：同一 session 的多轮历史不应重复经过层链，需设计增量路由（仅新内容参与 QUERY）
- **并发控制**：多 session 并发时，各层 Manager 的 `_final_result` 等可变状态需做到 session 级隔离，避免交叉污染
- **方向**：可参考 `trace_id` 扩展到 `session_id` 粒度的状态隔离，或为每个 session 实例化独立的层链

### 3. 真实世界 Coding 场景

Phase 2.1 — Benchmark 评估：
- 使用开源基准（如 **SWE-bench**）评估 Agent 在真实代码仓库上的修复/开发能力
- 评估粒度从"测试是否通过"扩展到**工程质量**（代码风格、模块化程度、可维护性）和**执行效率**（迭代次数、Token 消耗、运行时间）

Phase 2.2 — 对抗性评测：
- 构建对抗性 Agent，在代码仓库中**人为制造问题**（Bug、性能缺陷、安全隐患），然后验证主 Agent 能否发现并修复
- 或直接利用 Git 提交记录 / Pull Request 中的真实修复案例作为训练和评估数据
- 目标：从"通过测试"到"写出好代码"的评估范式迁移

## 工程文件

- **[COOKBOOK.md](COOKBOOK.md)** — README 各章节与代码位置的精确对照表
- **[MAINTAIN.md](MAINTAIN.md)** — 函数级维护文档：每个模块的函数签名、参数、上下游调用关系
- **[LEARNING_JOURNAL.md](LEARNING_JOURNAL.md)** — 可迁移工程技巧记录
- **[DEBUG_JOURNAL.md](DEBUG_JOURNAL.md)** — 复杂 Bug 排查记录
