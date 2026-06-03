# Agent Communication & Architecture Design — Phase 2

> 日期: 2026-06-03 | 状态: 讨论完成

Phase 2 覆盖 Phase 1（Execute 链路）之后的内容：反射学习管道、Task Decomposer、每层 ReflectionAgent、Comm Agent 分离、Tool 解耦。

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

## 4. Comm Agent 分离

Phase 1 中 Manager 直接处理 QUERY/RESPONSE。Phase 2 将通信职责拆到独立 Comm Agent。

### 4.1 接口

```python
class UpwardComm:
    """确定性 Agent，无需 LLM。"""
    def receive(self, msg: LayerMessage) -> None: ...
    def forward_to_manager(self, msg: LayerMessage) -> LayerMessage: ...
    def send_response(self, manager_reply: Any) -> LayerMessage: ...

class DownwardComm:
    """确定性 Agent，无需 LLM。"""
    def receive(self, msg: LayerMessage) -> None: ...
    def query_down(self, subtype: str, payload: Any) -> LayerMessage: ...
    def send_to_manager(self, msg: LayerMessage) -> Any: ...
```

### 4.2 文件结构

```
core/layers/l0_5_1/
  manager.py
  upward_comm.py        ← 覆盖现有 stub
  downward_comm.py      ← 覆盖现有 stub
  reflection_agent.py   ← 新增

core/layers/l2/
  manager.py
  upward_comm.py
  downward_comm.py
  reflection_agent.py

core/layers/l3/
  manager.py
  upward_comm.py
  downward_comm.py
  reflection_agent.py
```

### 4.3 Manager 与 Comm Agent 关系

Manager 不再直接收发 LayerMessage。流程变为：

```
上层 UpwardComm → 本层 UpwardComm.receive() → Manager.process()
                                               → DownwardComm.query_down() → 下层
```

Manager 专注于业务逻辑，Comm Agent 处理协议。

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
