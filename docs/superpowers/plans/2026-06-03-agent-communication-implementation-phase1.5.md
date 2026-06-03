# Phase 1.5: Execute 通讯协议完整实现

> 日期: 2026-06-03 | 优先级: 高

将 Phase 1 的直接方法调用升级为 **LayerMessage 信封 + Comm Agent** 通信。补充 L1/L2/L3 配置分离。

---

## 目标

1. **Comm Agent 实现**: 每层 UpwardComm + DownwardComm，用 LayerMessage 协议通信
2. **通信协议**: QUERY → Manager.process() → RESPONSE，NOTIFY 走 LayerMessage.NOTIFY
3. **协议分离**: Manager 只处理业务 dict，Comm Agent 处理 LayerMessage 信封
4. **配置分离**: L1/L2/L3 各自独立配置文件，放到 `config/` 目录

---

## 修改范围

```
core/layers/
  base.py                        # 保留 LayerManager ABC（不变）
  l0_5_1/
    upward_comm.py               # 实现（覆盖 stub）
    downward_comm.py             # 实现（覆盖 stub）
    manager.py                   # 改为接收 business dict（不是 LayerMessage）
  l2/
    upward_comm.py               # 实现（覆盖 stub）
    downward_comm.py             # 实现（覆盖 stub）
    manager.py                   # 同上
  l3/
    upward_comm.py               # 实现（覆盖 stub）
    downward_comm.py             # 实现（覆盖 stub）
    manager.py                   # 同上
  __init__.py                    # build_chain() 改为注入 Comm Agent

core/executor.py                 # 改为通过 Comm Agent 发 QUERY，收 NOTIFY

config/
  prompts/                       # 集中配置目录
    executor_system.yaml         # NEW: Executor 的 system prompt 模板
    l0_5_1.yaml                  # NEW: L0.5 触发器/验证器 配置
  l1_rules.yaml                  # MOVE: 从 data/l1_rules.json 迁移
  l2_seed.yaml                   # NEW: L2 种子知识卡片
  l3.yaml                        # NEW: L3 编译阈值、路径

data/                            # Phase 1 的运行时数据保留
  l1_rules.json                  # 保留，作为持久化存储（非配置）
```

---

## Task 1.5.1: UpwardComm + DownwardComm 基类

**文件**: `core/layers/comm.py` (新文件，Comm Agent 共享逻辑)

```python
class CommAgent:
    """Base for UpwardComm/DownwardComm. Handles LayerMessage serialization."""

    def receive(self, msg: LayerMessage) -> dict:
        """Extract payload from LayerMessage. Returns business dict for Manager."""
        return msg.payload

    def wrap(self, source: str, target: str, msg_type: MessageType,
             payload: Any, trace_id: str) -> LayerMessage:
        """Wrap business dict in LayerMessage envelope."""
        return LayerMessage(
            source=source, target=target, type=msg_type,
            payload=payload, trace_id=trace_id,
        )
```

## Task 1.5.2: 每层 UpwardComm/DownwardComm 实现

每层 2 个 Comm Agent，负责：
- `UpwardComm`: 从上层收 QUERY → 解包给 Manager → Manager 返回后包装 RESPONSE 发回
- `DownwardComm`: 从 Manager 收到请求 → 包装 QUERY 发下层 → 接收下层 RESPONSE → 解包给 Manager

## Task 1.5.3: Manager 协议分离

Manager 接口不变（`process()` 收业务 dict，`notify()` 返回业务 dict），但 `query()` 和 `collect_notify()` 从 Manager 移除，交由 Comm Agent 编排。

## Task 1.5.4: Executor 改为通过 Comm Agent 通信

`Executor.execute()` 改为通过 LayerMessage QUERY 启动链。

## Task 1.5.5: 配置分离

```
config/
  prompts/
    executor_system.yaml  # Executor 的 system prompt 模板
  l1_rules.yaml           # L1 行为规则（种子 + 结构定义）
  l2_seed.yaml            # L2 种子知识卡片
  l3.yaml                 # L3 编译阈值、domain 配置
```

---

## 验证标准

- 所有现有 28 个测试继续通过
- 通信链路走 `LayerMessage` 信封
- `build_chain()` 产出带 Comm Agent 的完整链路
- 配置从 `config/` 目录读取
