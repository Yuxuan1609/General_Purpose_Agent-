# Agent Communication & Architecture Design — Phase 2

> 日期: 2026-06-03 | 状态: 设计完成

Phase 2 覆盖 Phase 1/1.5（Execute + Comm Agent）之后的内容：反射学习管道、Task Decomposer、每层 ReflectionAgent、Tool 解耦。

> **已完成于 Phase 1.5**: Comm Agent 分离（UpwardComm/DownwardComm）+ LayerMessage 协议。Phase 2 不再包含 Comm Agent 实现。

---

## 1. Task Decomposer

### 1.1 定位

独立于层体系，位于通信层（脚本）与学习管道之间。Session 结束后执行。

```
Session 结束 → 通信层写 raw log → Decomposer 拆解 → Task[] → pending/
```

### 1.2 接口

```python
class TaskDecomposer:
    def decompose(self, session: dict, raw_log: Path) -> list[Task]:
        """将 Session + 原始日志拆解为 Task 列表。

        raw_log: 通信层（脚本）在 Session 末尾写入的原始日志文件路径。
        位于 data/learning/raw/{session_id}.log。
        DouZero 类型不需要 raw_log（decompose 返回单 Task stub）。
        """
        strategy = self._select_strategy(session)
        return strategy(session, raw_log)

    def _select_strategy(self, session: dict) -> Callable:
        task_type = session.get("task_type", "unknown")
        # 现阶段: task_type → 规则函数
        # 未来: LLM 判断策略
        registry = {
            "game/doudizhu": self._decompose_game_unit,
            "game/leduc":    self._decompose_game_unit,
            "coding/session": self._decompose_coding,
        }
        return registry.get(task_type, self._decompose_game_unit)

    def _decompose_game_unit(self, session, raw_log) -> list[Task]:
        # DouZero / Leduc: 1 Session = 1 Task，不拆
        return [Task(description=session["id"], ...)]

    def _decompose_coding(self, session, raw_log) -> list[Task]:
        # 未来: LLM 按意图片段切分
        return [Task(description=session["id"], ...)]
```

### 1.3 文件位置

`core/orchestrator/task_decomposer.py`（覆盖现有 stub）

---

## 2. 学习管道架构

### 2.1 文件夹结构

```
data/learning/
  pending/              ← 等待学习 (ExecutionRecord JSON)
    {session_id}.json
  learned/              ← 已学习 (Reflect 完成后移入，不删除)
    {domain}/
      {session_id}.json
```

### 2.2 触发机制

每次 Execute 结束后 Executor 检查 `pending/`。按 Domain 分组评估：

```
score(domain) = task_count_weight × count + complexity_weight × total_tokens / baseline_tokens
```

当 `score(domain) ≥ threshold` 触发该 domain 的 Reflect。

Domain 映射检查：优先检查该 domain 是否已有处理好的映射，避免重复处理同一 domain 的同一批数据。

### 2.3 评分参数

在 `config.yaml` 中配置：

```yaml
learning:
  task_count_weight: 1.0      # 任务数量权重
  complexity_weight: 1.0      # 复杂度权重
  baseline_tokens: 2000       # 基准 token 数
  threshold: 5.0              # 触发阈值
```

---

## 3. ReflectionAgent

### 3.1 每层 Agent 完整列表（Phase 2）

| Agent | 职责 | 阶段 |
|-------|------|------|
| Manager | 局部编排、核心数据管理、可能调 LLM | Execute + Reflect |
| UpwardComm | 与上一层通信 (QUERY/RESPONSE via LayerMessage) | Execute + Reflect |
| DownwardComm | 与下一层通信 (QUERY/RESPONSE via LayerMessage) | Execute + Reflect |
| ReflectionAgent | 反思编排：判责、触发下层反思对话、通过 Manager 写回 | Reflect only |

### 3.2 ReflectionAgent 接口

```python
class ReflectionAgent(ABC):
    def __init__(self, layer_name: str, manager, downstream: ReflectionAgent | None = None):
        self._name = layer_name
        self._manager = manager
        self._downstream = downstream

    def investigate(self, issues: list[dict], context: dict) -> dict:
        """收到 Coordinator 分发的问题，判断责任归属。

        返回: {
            "my_issues": [...],       # 确认是自己的问题
            "downstream_issues": [...],  # 需要下层调查的问题
            "actions": [...],         # 本层采取的行动
        }
        """
        ...

    def fix(self, my_issues: list[dict]) -> dict:
        """对本层问题进行修复。通过 Manager 写回数据。

        返回: {fixes_applied: int, details: [...]}
        """
        ...

    def query_downstream(self, issues: list[dict], context: dict) -> dict:
        """向下层 ReflectionAgent 发起反思 QUERY，等待 RESPONSE。

        与 Execute 段相同的链式 QUERY→RESPONSE 模式。
        """
        if self._downstream:
            result = self._downstream.investigate(issues, context)
            return result
        return {"my_issues": issues, "downstream_issues": []}
```

### 3.3 各层 ReflectionAgent 特殊行为

| 层 | 判责逻辑 | 修复行为 |
|----|---------|---------|
| L3 | 技能匹配错误 → 自己 | 更新/降级 Skill |
| L2 | 知识卡片置信度异常 → 自己；卡片来源可疑 → 上层 | boost/penalize 卡片 |
| L(0.5+1) | 规则导致错误决策 → 自己；下游信息不准 → 下层 | 提案 L1 规则变更（经 L0.5 验证器） |

---

## 4. Comm Agent 分离 ✅ (Phase 1.5)

Comm Agent 分离已在 Phase 1.5 完成，不再属于 Phase 2 范围。

实现位置：`core/layers/comm.py`（基类）+ 每层 `upward_comm.py`/`downward_comm.py`。

通信流程（已实现）：
```
上层 UpwardComm.receive() → Manager.process() → DownwardComm.wrap_query() → 下层
```

---

## 5. Tool Use 按层解耦

### 5.1 方案

工具注册时增加 `allowed_layers: list[str]` 字段。ToolRegistry 新增 `get_definitions_for_layer(layer_name)` 方法。

```python
class ToolEntry:
    name: str
    schema: dict
    handler: Callable
    allowed_layers: list[str]  # 新增: ["l3", "l2", "l0_5_1", "executor"]
    check_fn: Callable | None = None
    toolset: str = "core"
```

### 5.2 工具层归属

| 工具 | 可用层 | 理由 |
|------|--------|------|
| `skills_list/view/manage` | `["l3"]` | 技能管理是 L3 本职 |
| `terminal` | `["l2", "l0_5_1", "executor"]` | 知识验证和执行需要 |
| `todo` | `["executor", "l0_5_1"]` | 任务规划在边界 |
| `web_search` | `["l2", "l0_5_1", "executor"]` | 所有需要外部信息的层 |

### 5.3 ToolRegistry 变更

```python
def get_definitions_for_layer(self, layer_name: str) -> list[dict]:
    return [e.schema for e in self._entries.values()
            if layer_name in e.allowed_layers]
```

现有 `register()` 的 `allowed_layers` 默认值为 `["l3"]`（保持向后兼容，因为现有工具都注册在 L3）。

---

## 6. 配置扩展

`config.yaml` 新增：

```yaml
learning:
  enabled: true                 # 全局开关
  task_count_weight: 1.0
  complexity_weight: 1.0
  baseline_tokens: 2000
  threshold: 5.0
  pending_dir: data/learning/pending
  learned_dir: data/learning/learned
```

`AgentConfig` 新增字段：

```python
@dataclass
class AgentConfig:
    # ... existing fields ...
    learning_enabled: bool = True
    learning_task_count_weight: float = 1.0
    learning_complexity_weight: float = 1.0
    learning_baseline_tokens: int = 2000
    learning_threshold: float = 5.0
    learning_pending_dir: Path = Path("./data/learning/pending")
    learning_learned_dir: Path = Path("./data/learning/learned")
```

---

## 7. 反射通信路径

### 7.1 Phase 1（当前 plan）中的 Executor

Execute 阶段 Executor 调用 LLM 做最终决策。Reflect 阶段同一实体承担不同职责。

### 7.2 Reflect 流程（完整）

```
Executor (Reflect 模式) 检测 pending/ 达标
  │
  ├─ 读取目标 domain 的所有 ExecutionRecord
  ├─ 审核每层的 NOTIFY（从宽：标记潜在问题即可）
  ├─ 按层分发标记的问题列表
  │
  ├─→ L(0.5+1).ReflectionAgent.investigate(issues)
  │     │
  │     ├─ 自己的问题 → fix()
  │     └─ L2 的问题 → query_downstream(issues)
  │           │
  │           ▼
  │         L2.ReflectionAgent.investigate(issues)
  │           │
  │           ├─ 自己的问题 → fix()
  │           └─ L3 的问题 → query_downstream(issues)
  │                 │
  │                 ▼
  │               L3.ReflectionAgent.investigate(issues) → fix()
  │
  └─ 各层修复合集 → 归档 pending/ → learned/{domain}/
```

### 7.3 LayerMessage subtype 扩展

| subtype | 方向 | 含义 |
|---------|------|------|
| `REFLECT:INVESTIGATE` | 上→下 | ReflectionAgent 要求下层调查问题 |
| `REFLECT:FIX_RESULT` | 下→上 | 下层返回修复结果 |
| `REFLECT:NOTIFY_ISSUE` | Executor→层 | Coordinator 分发问题 |

---

## 8. 与 Phase 1 的接口约定

Phase 2 所有组件依赖 Phase 1 的以下接口：

| Phase 1 产物 | Phase 2 消费者 |
|-------------|---------------|
| `TaskObservation` | Decomposer, ReflectionAgent |
| `ExecutionRecord` | 学习管道 (pending/ 读写) |
| `LayerManager` ABC | ReflectionAgent 通过 Manager 写回 |
| `Executor` | 扩展为 Reflect 协调者 |
| `build_chain()` | Phase 2 链中追加 Comm/Reflection |

Phase 2 不得修改 Phase 1 的公开接口签名，只能扩展。

---

## 9. L2 Domain Graph 设计

### 9.1 核心思路

L2 以**带权图**描述 Domain 之间的相关度，L3/L4 挂在 L2 Node 下。L3/L4 **不需要独立的图链接结构**——跨域资源访问由 L2 图的扩散激活完成。

### 9.2 图结构

```
Domain Graph (≤100 nodes, 规则发起合并/拆分，LLM 确认):

  coding/python ──0.8──→ coding/rust
       │ 0.7                │ 0.7
       ▼                    ▼
  coding/general ──0.4──→ game/scripting
       │
       │ 0.9
       ▼
  game/doudizhu ──0.9──→ game/leduc
       │                    │
  ┌────┴────┐         ┌────┴────┐
  │ L3 skills│         │ L3 skills│
  │ L4 docs  │         │ L4 docs  │
  └─────────┘         └─────────┘
```

- **Node**: 一个特定领域（如 `coding/python`, `game/doudizhu`）
- **Edge**: 带权无向边，权重 = 两个 Domain 的相关度 (0.0~1.0)
- **Node 维护**: 规则发起（边权重 <0.3 持续 N 次→拆分 / >0.9 持续 N 次→合并），LLM 确认
- **Edge 权重**: 从任务执行反馈中学习调整——成功的跨域引用增加权重，失败的跨域引用降低权重
- **总 Node 数**: ≤100，高内聚原则

### 9.3 L1 → L2 检索流程

```
L1 QUERY(domain="game/doudizhu", task_context) → L2:

  1. 平铺扫描: 从 task domain 出发，BFS 沿边扩散
     score(neighbor) = source_score × edge_weight × decay(step)
     扩散步数上限: 2 跳

  2. 锁定 top-k Nodes（按扩散得分排序）

  3. 对每个命中 Node:
     a. 拉取 Node 内 L2 知识卡片（按激活值 top-5）
     b. 拉取挂载的 L3 skills（优先级: specific > exportable）
     c. 拉取挂载的 L4 docs（如有）

  4. 按 graph distance 加权排序 → RESPONSE 给 L1
```

### 9.4 L3/L4 挂载方式

L3/L4 不建独立图。每个 L3 skill / L4 doc 声明 `domain` 字段，L2 图自动将其挂载到对应 Node。

**跨域场景**：当 Domain A 的 L3 不足时，L2 图扩散自动拉取邻近 Domain B 的 L3 资源。无需 L3 层自己建边。

**挂载学习**：L3 skill 的 `domain` 归属也从任务执行反馈中学习——如果一个 skill 在 domain B 中被频繁成功使用，其 domain 可能应调整为 B。

### 9.5 待确认

| # | 问题 | 状态 |
|---|------|------|
| 1 | Node 合并/拆分的具体触发规则 | 待细化 |
| 2 | Edge weight 从任务反馈学习的算法 | 待细化 |
| 3 | L3 挂载到 L2 Node 的学习机制 | 待细化 |
| 4 | 初始 Node 拓扑和 edge weight 的引导数据 | 待细化 |
