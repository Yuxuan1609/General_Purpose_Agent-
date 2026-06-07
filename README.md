# Cognitive Agent

基于 4.5 层认知架构的 AI 智能体系统。受 ACT-R、Soar、CoALA、Constitutional AI、Reflexion 等理论启发，构建具备分层可演化记忆的自适应学习闭环。

## 架构概览

L0.5 和 L1 合并为 **L(0.5+1)**，三层链式通信：

```
AgentRuntime → Executor → L(0.5+1) ↔ L2 ↔ L3
                              ↑ 链式相邻传递 (A1)
```

| 层 | 职责 |
|----|------|
| **L(0.5+1)** | 不可变宪法 + 可演化行为规则；含 L1Agent（两阶段 V-structure） |
| **L2** | 概率性知识卡片；含 L2Agent（三阶段 V-structure） |
| **L3** | SKILL.md 技能执行；domain 确定性匹配 + L3Agent（LLM 选择+执行） |
| **L4**（预留） | 静态知识存储，L3 dispatch 目标 |

每层 Manager 驱动 V-structure 循环：**Agent（LLM 决策）↔ Manager（编排/状态管理）↔ Comm Agent（确定性协议）**。

> **核心洞察**：Reflection 不需要独立的架构设施。将其建模为 **LearningEnv**（实现 `Environment` 接口的普通环境），与 GameEnv 共享 Executor + Layers + ToolUse。学习策略通过 `domain="learning"` 走现有链式通道，系统可以学到"如何学习"（自举）。

**执行路径** — 独立环境 + 共享层链：

```
                    ToolUse（跨环境共享）
                        ↑
  ┌─────────────────────┼──────────────────────────┐
  │  GameEnv            │  LearningEnv              │
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

**通信协议**（已实现）：

```
Executor ──LayerMessage(QUERY)──→ L(0.5+1)→L2→L3
 各层 Manager 驱动 V-structure Agent 循环
 RESPONSE 链返回 → NOTIFY → Executor 组装 prompt → LLM → action
 ExecutionRecord → pending/
```

- Comm Agent（UpwardComm/DownwardComm）：确定性协议处理
- Manager：各层业务逻辑，只消费业务 dict
- Executor：独立决策者，只收不发

---

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

设置环境变量或创建 `.env`：

```bash
# Windows
set DEEPSEEK_API_KEY=your-key-here

# Linux / macOS
export DEEPSEEK_API_KEY=your-key-here
```

编辑 `config.yaml`（可选）：

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
python main.py                              # 打印各层状态
python main.py "explain how asyncio works"  # 执行任务
pytest tests/ -v                            # 运行测试
```

### RLCard 环境 (Phase 1)

```bash
pip install rlcard[torch]
```

| 游戏 | 状态空间 | 动作空间 | 预设 AI 对手 |
|------|---------|---------|------------|
| Leduc Hold'em | 10² | 4 | 预训练 CFR |
| Dou Dizhu（斗地主） | 10⁵³~10⁸³ | ~27K | DouZero |
| Limit Texas Hold'em | 10¹⁴ | 4 | 规则模型 |
| Mahjong / UNO / Bridge | — | — | 规则模型 |

**Leduc 验证路径：**

```
RLCard(Leduc) → env.step(action) → 状态 + reward
       → LLM Agent 决策 → 提交 action → 获取下一步
       → 执行完毕 → 评估输赢 → Reflect & Learn 更新 L1/L2/L3
```

**DouZero 用法：**

```bash
# 直接 LLM 模式（绕开认知层）
python scripts/run_douzero_llm.py --llm_position landlord_up --episodes 10 --step_verbose

# 认知链模式（Executor + LayerChain）
python scripts/run_douzero_llm.py --llm_position landlord_up --episodes 10 --mode cognitive

# 学习 dry-run
python scripts/run_learning_dryrun.py       # mock LLM (fast)
python scripts/run_learning_dryrun.py --real  # real DeepSeek API
```

---

## 工具系统

基于单例 `ToolRegistry`，线程安全，支持 `check_fn` 条件过滤和 `toolset` 分组。

| 工具 | 功能 | 注册位置 |
|------|------|----------|
| `todo` | 子任务跟踪 | `core/tools/todo_tool.py` |
| `terminal` | 命令行执行（30s 超时） | `core/tools/terminal_tool.py` |
| `web_search` | DuckDuckGo 网络搜索 | `core/tools/web_search_tool.py` |
| `skills_list` | 列出已注册技能 | `core/skill_layer.py` |
| `skill_view` | 查看技能详细内容 | `core/skill_layer.py` |
| `skill_manage` | 创建/编辑/删除技能 | `core/skill_layer.py` |

> 当前工具系统仅在旧 `main.py` 路径中使用，新 Executor + Layers 链尚未挂载。这是 [Phase 3 升级方向一](UPGRADE_ROADMAP.md#方向一tool-use--knowledge-挂载)。

---

## 项目结构

```
cognitive-agent/
  _archive/              # 已归档旧架构代码
  config.yaml            # 用户配置
  pyproject.toml         # 项目元数据与依赖
  config/layers/         # 分层配置 (l1.yaml, l2.yaml, l3.yaml, learning.yaml)
  core/                  # 核心源代码
    types.py             # TaskObservation, ExecutionRecord
    executor.py          # Executor — 独立决策者
    llm_client.py        # LLMResponse + LLMClient
    layer_message.py     # LayerMessage 信封 + MessageType 枚举
    task.py              # Domain, LearningUnit
    meta_driver.py       # L0.5 验证器 + 安全过滤
    philosophy.py        # L1 规则 CRUD
    flexible_knowledge.py# L2 知识卡片 + KnowledgeGraph
    skill_layer.py       # L3 技能 + L2→L3 编译
    env/                 # 环境抽象 (base.py, learning_env.py, threshold_scorer.py)
    layers/              # 三层链式 Manager + Comm Agent
      base.py            # LayerManager ABC + LayerAgent ABC
      comm.py            # UpwardComm/DownwardComm + AgentPacket
      l0_5_1/            # L(0.5+1)Manager + L1Agent
      l2/                # L2Manager + L2Agent
      l3/                # L3Manager + L3Agent
    tools/               # ToolRegistry + 工具实现
  scripts/               # 运行脚本（run_leduc_cognitive.py, run_douzero_llm.py 等）
  data/                  # 运行时数据 (layers/, learning/pending/, learning/learned/)
  tests/                 # pytest (~18 test files)
  docs/                  # 设计文档
```

---

## 实现计划

| 阶段 | 状态 |
|------|------|
| Phase 1 — Execute 链路 | ✅ 已完成 |
| Phase 1.5 — Comm Agent + LayerMessage + V-structure | ✅ 已完成 |
| Phase 2.1 — LearningEnv 骨架 | ✅ 已完成 |
| Phase 2.2 — 接入游戏循环 + 双域激活 | ✅ 已完成 |
| Phase 2.3 — 清理旧代码 + 元学习轨 | ✅ 已完成 |

## 文档

- **[ARCHITECTURE.md](ARCHITECTURE.md)** — 完整架构设计：A1-A4 设计原则、E1-E8 工程原则、通信协议、各层详解、评估策略
- **[UPGRADE_ROADMAP.md](UPGRADE_ROADMAP.md)** — Phase 3+ 升级路线图：Tool Use 挂载、并行 Agent、Hermes 循环编排、整理模式
- **[config/layers/consolidation.yaml](config/layers/consolidation.yaml)** — 各层内容规格与整理策略：条目格式、容量限制、anti-patterns、三级整理策略
- **[COOKBOOK.md](COOKBOOK.md)** — README 各章节与代码位置的精确对照表
- **[MAINTAIN.md](MAINTAIN.md)** — 函数级维护文档
- **[LEARNING_JOURNAL.md](LEARNING_JOURNAL.md)** — 可迁移工程技巧记录
- **[DEBUG_JOURNAL.md](DEBUG_JOURNAL.md)** — 复杂 Bug 排查记录
