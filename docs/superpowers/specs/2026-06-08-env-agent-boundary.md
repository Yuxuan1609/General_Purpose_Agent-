# Environment ↔ Agent 职责边界（项目纪律）

> **核心原则**: Environment 决定 Agent **看什么**和**输出什么格式**；Agent 决定**怎么推理**和**输出什么内容**。Environment 不碰 Agent 的内部机制（tool、prompt、层间调度），Agent 不感知 Environment 类型。

## 通信契约

Environment 与 Agent 之间通过 **两个接口** 通信，其余一切透明：

```
┌─ Environment ──────────────────────────┐
│                                         │
│  ① build_task_observation() → TaskObservation
│     ├─ meta:  任务目标 + 输出格式约束      │
│     ├─ state: 当前观测 + 历史 + 格式信号   │
│     └─ session: domain + session 元信息   │
│                                         │
│  ② step(action) / apply_modifications() │
│     ← 消费 Agent 输出                    │
│                                         │
└────────────┬──────────┬─────────────────┘
             │ ①        │ ②
             ▼          ▲
┌─ Agent (Executor + Layers) ────────────┐
│                                         │
│  ③ Executor.execute(obs)               │
│     → LayerMessage(QUERY) → L(0.5+1)  │
│     → L1↔L2↔L3 链式推理               │
│     → collect_notify()                 │
│                                         │
│  ④ 返回 {action_text, notify_layers}   │
│                                         │
└─────────────────────────────────────────┘
```

| 接口 | 方向 | 载体 | 谁调用 |
|------|------|------|--------|
| `build_task_observation()` | Env → Agent | `TaskObservation` | CLI 脚本 / 游戏循环 |
| `step(action)` / `apply_modifications()` | Agent → Env | `action_text` / `notify_layers` | CLI 脚本 / 游戏循环 |

## 边界规则（纪律）

### R1: Environment 不碰 Agent 内部

Environment **永远不**做以下操作：

| 禁止 | 替代方式 |
|------|---------|
| 注入 tool 定义 | 通过 `state` 里的信号 key（如 `l2_output_format`）让 Agent 自行决定挂载哪些 tool |
| 修改 Agent prompt | 通过 `meta` 字段注入格式约束，Agent 层自行将 `meta` 拼入 system prompt |
| 调用 ToolRegistry / LayerInjector | Agent 层内部管理 |
| 访问 `DictInjector`、`_pending_mods` | Agent 层私有属性 |
| 直接调度某一层 | 始终走 `Executor.execute()` → 完整链式通信 |

### R2: Agent 不感知 Environment 类型

Agent（Executor + Layers）**永远不**根据 Environment 类型做分支：

| 禁止 | 替代方式 |
|------|---------|
| `if env_type == "learning": ...` | 读 `meta` 中的格式约束 |
| `if env_type == "interaction": ...` | 读 `meta` / `state["current"]` |
| hardcode 输出 schema | 从 `state["lX_output_format"]` 读取 |

### R3: 工具挂载由 Agent 层自主决定

```
错误：Environment 注入工具 → Agent 被动接收
正确：Environment 设信号 → Agent 检测信号 → Agent 自行挂载
```

**当前实现**：
1. `LearningEnv.build_consolidation_task()` 在 `state` 里设置 `l1_output_format` / `l2_output_format` / `l3_output_format`
2. 各层 Agent 的 `stage2()` / `execute()` 检测到这些 key → 调用 `_setup_lX_consolidation()` → 挂载 `DictInjector` + consolidation tools
3. `InteractionEnv.build_task_observation()` 不设这些 key → Agent 不挂载 consolidation tools

### R4: 持久化由 Executor 执行，Environment 只设标志位

```
错误：Environment 写文件
正确：Environment 设 session["enable_learning"] → Executor._write_pending()
```

- `InteractionEnv`: `session["enable_learning"] = True/False`（由 `--no-record` 控制）
- `LearningEnv`: `session["enable_learning"] = False`（反思期间不重复记录）
- `Executor._write_pending()` 检查 `session.get("enable_learning", True)` 决定是否写
- Environment **不直接写** `data/learning/pending/`

### R5: Layer feedback 通过 state，不通过旁路

`LearningEnv` 的 reverse-notify：
- ✅ 通过 `state["feedback"]` / `state["lX_feedback"]` 注入，Agent 读 `state` 字段
- ❌ 不通过 `LayerMessage` 旁路，不改 `notify_layers` 结构

## 三个 Environment 对照

| | GameEnv (RLCard) | LearningEnv | InteractionEnv |
|---|---|---|---|
| **domain** | `game/leduc` 等 | `learning/reflect` / `learning/compile` | `interaction` |
| **触发** | 游戏循环 `env.step()` | `needs_consolidation()` / `reset(task)` | CLI `receive_input()` |
| **meta 内容** | 游戏状态 + action 格式 | 执行记录分析 + modification 格式 | system_prompt |
| **state 信号** | 游戏观测 + 合法动作 | `lX_output_format` + `feedback` | `current` + `history` |
| **Agent 输出** | 结构化 action 字符串 | `notify_layers`（tool calls → mods） | `action_text`（L1 reply） |
| **env 消费** | 确定性游戏执行 | `_apply_parsed_mods()` → CRUD | `step()` → 记录 history |
| **持久化触发** | Executor 每步写 | `apply_modifications()` | Executor 每轮写（if enable_learning） |
| **工具挂载** | 无 | consolidation tools（L1/L2/L3） | 无（未来可挂全局 tools） |

## 新增 Environment 检查清单

当新增 Environment 时必须确认：

- [ ] 继承 `Environment` ABC（`core/env/base.py`）
- [ ] 实现 `reset(task_description) → EnvState`
- [ ] 实现 `step(action) → EnvStep`
- [ ] 提供 `build_task_observation() → TaskObservation | None`
- [ ] `meta` 包含任务目标 + 输出格式约束
- [ ] `state` 包含 Agent 推理所需的所有上下文
- [ ] `session` 包含 `domain` + `enable_learning`
- [ ] 不直接注入 tool 定义（通过 `state` 信号）
- [ ] 不直接写 `data/learning/pending/`
- [ ] 不与 Agent 内部属性（`_injector`, `_pending_mods`）交互
- [ ] 不根据层名做特殊处理

## 相关文件

| 文件 | 角色 |
|------|------|
| `core/env/base.py` | `Environment` ABC + `EnvState` / `EnvStep` |
| `core/env/learning_env.py` | `LearningEnv` — 学习环境 |
| `core/env/interaction_env.py` | `InteractionEnv` — 对话环境 |
| `core/types.py` | `TaskObservation` / `ExecutionRecord` |
| `core/executor.py` | `Executor` — env→agent 唯一入口 |
| `core/layers/base.py` | `LayerAgent` — tool 挂载 + `_call_llm` |
| `core/layers/l0_5_1/manager.py` | L1Agent — consolidation 信号检测 |
| `core/layers/l2/manager.py` | L2Agent — consolidation 信号检测 |
| `core/layers/l3/manager.py` | L3Agent — consolidation 信号检测 |
| `docs/superpowers/specs/2026-06-04-learning-env-design.md` | LearningEnv 设计 spec（含原始边界定义） |
