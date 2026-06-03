# Agent Communication & Architecture Design

> 日期: 2026-06-03 | 状态: 讨论中

## 1. 术语定义

| 术语 | 含义 |
|------|------|
| **AgentRuntime** | 程序入口/运行时本身，非某个 Agent 实例。接收环境 TaskObservation，启动执行流程，最终把 action 发回环境 |
| **Executor** | 独立于层体系外的最终决策者。从各层收集 NOTIFY、拼接 prompt、调用 LLM、返回 action。只收不发（层不收到 Executor 的消息） |
| **Manager** | 每层的主控 Agent（L(0.5+1).Manager / L2.Manager / L3.Manager），承担本层"局部编排者"职责 |

## 2. 认知层合并

L0.5 和 L1 合并为 **L(0.5+1)**，共 3 层：

```
AgentRuntime ──→ Executor ──→ L(0.5+1) ──→ L2 ──→ L3
                                               ↑ 链式相邻传递 (A1)
```

L(0.5+1) 内部：
- 不可变部分 (原 L0.5): 硬编码触发器、验证器、危险过滤
- 可变部分 (原 L1): 可演化的行为规则，改规则需 L0.5 验证器审批

## 3. 层内 Agent 设计

每层含 3 个 Agent：

| Agent | 职责 | 类型 |
|-------|------|------|
| **Manager** | 本层"局部编排者"：管理核心数据、决定是否向下一层发 QUERY、等 RESPONSE 后聚合、通过 UpwardComm/DownwardComm 收发消息。可能调用 LLM 完成本层工作 | 混合 |
| **UpwardComm** | 与上一层通信：接收上层 QUERY → 转 Manager；收到 Manager 回复 → 封装 RESPONSE 发回上层 | 确定性 |
| **DownwardComm** | 与下一层通信：接收 Manager 请求 → 封装 QUERY 发下层；接收下层 RESPONSE → 转 Manager | 确定性 |

### 3.1 各层 LLM 调用

下层 Manager 在上层 QUERY 到达后才可能调用 LLM。调用决策由 chain 驱动（上层决定是否引发下层处理），但不阻塞上层——上层发出 QUERY 后不等待下层 LLM 完成才继续。

**Phase 1（Execute）**：仅 Executor 调用 LLM。层 Manager 为确定性逻辑（规则注入、卡片检索、技能匹配）。

**Phase 2（Reflect）**：各层 Manager/ReflectionAgent 可能调用 LLM。典型场景待细化。

### 3.2 提示词集中配置

所有 LLM prompt 模板统一存放在 `config/prompts/` 目录下，按层/角色分文件（如 `executor_system.yaml`、`l0_5_1_reflect.yaml`）。避免散落在各层代码中。Phase 1 的 Executor 提示词为硬编码占位，Phase 2 迁移到集中配置。

## 4. Execute 阶段通信流程

```
每步动作触发一次完整流程:

  AgentRuntime ──TaskObservation──→ Executor
                                      │
          ┌───────────────────────────┼───────────────────────┐
          │ QUERY                     │                       │
          ▼                           │                       │
      L(0.5+1).Manager                │                       │
          │  (可能内部调LLM)           │                       │
          │ QUERY                     │                       │
          ▼                           │                       │
      L2.Manager                      │                       │
          │  (可能内部调LLM)           │                       │
          │ QUERY                     │                       │
          ▼                           │                       │
      L3.Manager                      │                       │
          │  (可能内部调LLM)           │                       │
          │                           │                       │
          └──── RESPONSE 链逐层返回 ──┘                       │
                      │                                       │
          L(0.5+1).Manager ──NOTIFY──→ ┐                     │
          L2.Manager         ──NOTIFY──→ ├── Executor         │
          L3.Manager         ──NOTIFY──→ ┘  (等待全部收齐)     │
                                              │
                                    组装 prompt → LLM.chat()
                                              │
                                    parse → action → AgentRuntime
                                              │
                                          发回环境
```

### 4.1 通信规则

1. **QUERY 从 Executor 发起**，沿 L(0.5+1) → L2 → L3 链式传递
2. **RESPONSE 沿链逐层回溯**——每层在本层 Manager 处理完后附加上自己的结果，再往上一层返回
3. **NOTIFY 独立于 RESPONSE 链**，是每层 Manager 完成后向 Executor 的并行通知。工程实现上：**等 RESPONSE 链完全结束，再统一发送所有 NOTIFY**，避免并发复杂度
4. **Executor 只收不发**——各层 NOTIFY 到 Executor 后，Executor 不向层内回复
5. **Executor 的职责简单**：拼接各层结果 + 有限处理 + 调 LLM + 返回 action。不做任务编排、不反向通信

## 5. TaskObservation 格式

```python
@dataclass
class TaskObservation:
    meta:    dict              # 任务元信息：角色、目标、领域 (通信层填充)
    state:   dict              # 当前局面：任务特异性 (通信层填充)
    history: list | None       # None = 不需要历史, [...] = 已裁剪好的历史 (通信层决定)
    session: dict | None = None # 所属 Session {id, datetime, task_type, meta_hash} (通信层填充)
```

- `build_prompt(env_input) → TaskObservation` 由通信层（脚本）实现
- history 管理由通信层负责——每个任务自行决定保留多少历史、如何裁剪
- Agent 层只消费 TaskObservation，往 `meta` 上叠加各层信息

## 6. Tool Use 解耦与集中配置

工具不绑定特定层。每个工具声明其可用层级（`allowed_layers`），ToolRegistry 按层过滤。

工具定义集中在 `config/tools.yaml`：
```yaml
tools:
  skills_list:
    handler: l3.skills_list
    allowed_layers: [l3]
    description: "列出所有已注册技能"
  terminal:
    handler: tools.terminal
    allowed_layers: [l2, l0_5_1, executor]
    description: "命令行执行"
  todo:
    handler: tools.todo
    allowed_layers: [executor, l0_5_1]
    description: "子任务跟踪"
  web_search:
    handler: tools.web_search
    allowed_layers: [l2, l0_5_1, executor]
    description: "网络搜索"
```

工具归属逻辑（按本质决定可用层）：
| 工具 | 可用层 | 理由 |
|------|--------|------|
| `skills_list/view/manage` | L3 | 技能管理是 L3 本职 |
| `terminal` | L2+, Executor | 知识验证和执行需要 |
| `todo` | Executor, L(0.5+1) | 任务规划在边界 |
| `web_search` | L2+, Executor | 所有需要外部信息的层 |

Phase 1 不迁移到集中配置，维持代码内注册。Phase 2 迁移。

## 7. Executor 存档格式

每次 Execute 完成后，Executor 产出一条存档记录：

```python
@dataclass
class ExecutionRecord:
    session:       dict       # {id, datetime, meta_hash} — 通信层填写
    observation:   dict       # 原始 TaskObservation (meta + state + history)
    notify_layers: dict       # {layer: notify_payload} — 各层 NOTIFY 的汇总
    action:        Any        # 最终执行的 action
    result:        Any        # 环境返回的 reward / outcome
```

## 8. Session 与 Task Decomposer (概述)

> 详细设计见 `docs/superpowers/specs/2026-06-03-agent-communication-design-phase2.md`

通信层（脚本）定义 Session 边界。Decomposer 将 Session 拆解为 Task，现阶段用规则做特殊处理（DouZero = 不拆）。

Phase 1 不实现 Decomposer，Executor 直接用通信层提供的 TaskObservation。

## 9. 学习管道 (概述)

> 详细设计见 `docs/superpowers/specs/2026-06-03-agent-communication-design-phase2.md`

核心概念：
- Task 附带 `meta.enable_learning`（手动开启）
- Execute 结束后写 `ExecutionRecord` 到 `pending/`
- 按 Domain 分组积攒，达标触发 Reflect
- Reflect 完成后归档到 `learned/{domain}/`（不删除）

Phase 1 仅实现 pending/ 写入（Executor._write_pending），不实现触发/归档。

## 10. Reflect 阶段 (概述)

> 详细设计见 `docs/superpowers/specs/2026-06-03-agent-communication-design-phase2.md`

核心流程：
1. Executor（Reflect 模式）审核 pending/ 中 NOTIFY
2. 按层分发问题
3. 每层 ReflectionAgent 递归判责修复
4. 归档到 learned/

Phase 1 不实现 Reflect。全局 Reflect 链路与每层反思编排链路分离。

每层 Agent 列表（Phase 2 完整实现）：
| Agent | 职责 | 类型 |
|-------|------|------|
| Manager | 本层局部编排者、核心数据管理 | 混合 |
| UpwardComm | 与上一层通信 | 确定性 |
| DownwardComm | 与下一层通信 | 确定性 |
| ReflectionAgent | 反思编排：判责→修复（Phase 2） | 混合 |

## 11. 设计原则保留

- **A1 (相邻传递)**: L(0.5+1) ↔ L2 ↔ L3，链式不可跳跃
- **A2 (LayerMessage)**: 所有通信使用 `LayerMessage` 信封
- **A3 (信息隔离)**: 每层 Manager 只处理本层数据，只看到相邻层暴露的最小信息集
- **A4 (Task 单元学习)**: Execute 与 Reflect 严格分离
- **工程原则 E1-E8**: 完整保留
