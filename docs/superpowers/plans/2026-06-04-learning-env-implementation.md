# LearningEnv Implementation Plan

> 基于 `docs/superpowers/specs/2026-06-04-learning-env-design.md` 设计文档。
> 分三阶段实现，每阶段完成后可独立测试。

## Phase 2.1: LearningEnv 骨架

**目标**：LearningEnv 独立运行，不接入游戏。能扫描 pending、预处理、接收模拟输入、执行修改。

### 核心任务

| # | 任务 | 文件 |
|---|------|------|
| 1 | 创建 `core/env/learning_env.py`：`LearningEnv(Environment)` 类 | 新文件 |
| 2 | 实现 `reset()`：扫描 `data/learning/pending/`，沿用 `ThresholdScorer` 做触发判断 | learning_env.py |
| 3 | 实现 `_build_learning_units()`：一次轻量 LLM 调用，raw Session JSON → structured LearningUnit | learning_env.py |
| 4 | 实现 `_parse_NOTIFY()`：NOTIFY 文本 → structured modifications（LLM₂） | learning_env.py |
| 5 | 实现 `_apply()`：统一知识写入门，路由到 L1/L2/L3 的 modify/create 方法 | learning_env.py |
| 6 | 实现 `step()`：组装 `_parse_NOTIFY → _apply → _build_state → EnvStep` | learning_env.py |
| 7 | 添加 `learning/reflect` 到 `L2_DOMAIN_NODES` | `core/layers/l2/manager.py` |
| 8 | `session` 支持 `domains: list[str]`，Executor 兼容 | `core/types.py`, `core/executor.py` |
| 9 | 创建 `config/layers/learning.yaml`（LLM₁/LLM₂ 参数、trigger 阈值） | 新文件 |
| 10 | 创建 `data/layers/knowledge/learning/` 种子目录（初始 2-3 张 L2 卡片 + 1-2 个 L3 技能） | 新目录 |

### 不做的

- 不接入游戏循环
- 不实现通信层格式注入
- 不删除旧 Reflection 代码
- 不实现轨 2（元学习）

### 验证方式

```
# 1. 手动造 pending records
# 2. 调用 learning_env.reset("learn from recent leduc games")
#    → 验证返回的 observation 是结构化的 LearningUnit
# 3. 模拟一个 NOTIFY 文本（包含 game 分析 + 修改建议）
# 4. 调用 learning_env.step(simulated_notify_text)
#    → 验证 L2 卡片/L1 规则被正确修改
```

### 测试文件

- `tests/test_learning_env.py` — 单元测试（mock LLM₁、LLM₂、knowledge stores）

---

## Phase 2.2: 接入游戏循环 + 双域激活

**目标**：完整闭环——Leduc 对局 → pending → LearningEnv → Agent → 知识变更 → 下一轮对局。

### 核心任务

| # | 任务 | 文件 |
|---|------|------|
| 1 | LearningEnv 通信层：在 TaskObservation.meta 中注入输出格式约束 | learning_env.py 或新文件 |
| 2 | `run_leduc_cognitive.py` 集成：对局 batch 后 → LearningEnv.reset() → Executor.execute() → LearningEnv.step() | scripts/ |
| 3 | L1/L2/L3 层链验证双域激活：prompt 中同时注入 game/leduc + learning/reflect 的知识 | 修改验证 / 日志确认 |
| 4 | LearningEnv 的 pending 消费和清理：消费后移动到 learned/ 或删除（沿用现有逻辑） | learning_env.py |
| 5 | 简化的 deferred reward：学习后重跑 N 局，比对胜率变化 | learning_env.py / scripts |

### 不做的

- 不实现复杂的 deferred reward 闭环（只做简单比对）
- 不删除旧 Reflection 代码
- 不实现轨 2（元学习）

### 验证方式

```
# 跑 N 局 Leduc
#   → Agent 通过 Executor + Layers 决策
#   → ExecutionRecord 写入 pending/
# 达到阈值后
#   → LearningEnv.reset() → TaskObservation
#   → Executor.execute(learning_task) → NOTIFY
#   → LearningEnv.step(notify) → 修改 L2 卡片/L1 规则
# 再跑 N 局
#   → 对比胜率（或其他指标）验证学习效果
```

### 测试文件

- `tests/test_learning_integration.py` — 集成测试（用真实 Leduc 环境或 mock）
- 修改 `scripts/run_leduc_cognitive.py` — 加入 LearningEnv

---

## Phase 2.3: 清理旧代码 + 元学习轨（可选）

**目标**：删除旧 Reflection 系统，为轨 2 预留接口（可延后）。

### 核心任务

| # | 任务 |
|---|------|
| 1 | 删除 `ReflectionAgent(ABC)` 及相关代码 |
| 2 | 删除 `core/layers/*/reflection_agent.py`（3 文件） |
| 3 | 删除 `core/layers/comm.py:ReflectPacket` |
| 4 | 删除 `core/orchestrator/reflect_coordinator.py` |
| 5 | 删除对应测试文件（5 个） |
| 6 | 清理 `LayerManager.apply_update()` 方法 |
| 7 | 若需要，为轨 2 预留 `LearningEnv.meta_learn()` 接口（stub） |

### 不做的

- 轨 2 完整实现（留待 Phase 3+）

---

## 整体时间线

```
Phase 2.1 ────→ 独立测试通过 ────→ Phase 2.2 ────→ 集成测试通过 ────→ Phase 2.3
 (骨架)                             (接入)                              (清理)
```

每个 Phase 完成后：
1. 所有测试通过
2. 当前 Phase 新增代码可通过独立脚本手动验证
3. 再进入下一 Phase
