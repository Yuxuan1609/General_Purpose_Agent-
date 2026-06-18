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
| **L(0.5+1)** | 不可变宪法 + 可演化行为规则；含 L1Agent（while-loop decide） |
| **L2** | 概率性知识卡片；含 L2Agent（while-loop decide） |
| **L3** | SKILL.md 技能执行；domain 确定性匹配 + L3Agent（while-loop decide） |

> **L4 已取消**。原计划作为静态知识存储层（L3 dispatch 目标），现已转化为两个共享机制：**KnowledgeCapability**（静态知识查询，所有层可调用）和 **ToolCapability**（工具系统，层可见 allowlist）。两者通过 `CapabilityRegistry` 统一注册，`LayerInjector` 注入各层 Agent 的多轮 tool call 循环。详见 [capability/](capability/)。

每层 Manager 驱动 Agent while-loop 决策循环：**Agent（LLM 决策）↔ Manager（编排/状态管理）↔ Comm Agent（确定性协议）**。

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
Executor → QUERY 下发 → L(0.5+1)→L2→L3
  Agent while-loop 决策（sync 工具并行，async 工具 fire-and-collect）
  NOTIFY 返回 → Executor 收结果
  Agent 通过 record_learning 工具自行提案学习内容
```

- Comm Agent（UpwardComm/DownwardComm）：确定性协议处理（基类直接实例化，无 per-layer 子类）
- Manager：各层业务逻辑，只消费业务 dict
- Executor：独立决策者，只收不发

---

## 项目纪律 — Environment ↔ Agent 边界

> **Environment 决定 Agent 看什么和输出什么格式；Agent 决定怎么推理和输出什么内容。**  
> 详见 [docs/superpowers/specs/2026-06-08-env-agent-boundary.md](docs/superpowers/specs/2026-06-08-env-agent-boundary.md)。

| 规则 | 含义 |
|------|------|
| **R1** | Environment 不碰 Agent 内部（不注入 tool、不修改 prompt、不调 ToolRegistry） |
| **R2** | Agent 不感知 Environment 类型（不 `if env_type == ...`，只读 `meta`/`state` 字段） |
| **R3** | 工具挂载由 Agent 层自主决定（Environment 只设 `state` 信号，不注入 tool 定义） |
| **R4** | 持久化由 Agent 通过 record_learning 工具控制，写入 data/learning/pending/ |
| **R5** | Layer feedback 通过 `state` 字段注入，不走旁路 |

**三个 Environment 对照**：

| | GameEnv | LearningEnv | InteractionEnv |
|---|---|---|---|
| domain | `game/*` | `learning/*` | `interaction` |
| meta 角色 | 游戏状态 + action 格式 | 修改建议格式 + 统计 | system_prompt |
| state 信号 | 合法动作 | `lX_output_format` + feedback | `current` + `history` |
| 工具挂载 | 无 | consolidation tools | 无（预留） |
| 持久化 | Agent 通过 record_learning 提案 | 同上 | Executor 每轮写 |

---

## 快速开始

### 环境要求

- Python >= 3.10
- DeepSeek API Key（或其他 OpenAI 兼容端点）
- **推荐 WSL2（Windows 用户）** — `terminal` 工具在 Linux 环境下行为正常，Windows 原生 cmd 命令与 Linux 工具链不兼容

### WSL 运行（Windows 推荐）

```powershell
# 1. 进入 WSL，直接使用 Windows 侧的项目目录（/mnt/c/ 挂载，实时同步）
wsl
cd /mnt/c/Users/micha/PycharmProjects/cognitive-agent

# 2. 安装依赖（pip 包是 Linux 二进制，需 WSL 侧独立安装）
pip install pyyaml pytest ddgs

# 3. 设置 API Key
export DEEPSEEK_API_KEY=your-key-here

# 4. 运行
python3 main.py "test query"
python3 -m pytest tests/ -v
```

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

# 知识整理（真实 LLM）
python scripts/test_consolidation_real.py

# 能力系统测试
python scripts/smoke_test_injector.py
python scripts/integration_test_capability.py

# E2E 测试（11 场景）
python scripts/test_e2e_full.py

# record_learning 测试
python scripts/test_record_learning.py

# KB I/O 测试
python scripts/test_kb_io.py
```

---

## 工具系统

基于 `CapabilityRegistry` 统一管理，通过 `LayerInjector` 注入各层 Agent 的多轮 tool call 循环（DeepSeek API 兼容，`role:"tool"` 消息格式）。原 `ToolRegistry` 通过 `ToolCapability` 包装接入。

| 工具 | 功能 | 注册位置 |
|------|------|----------|
| `todo` | 子任务跟踪 | `core/tools/todo_tool.py` |
| `terminal` | 命令行执行（30s 超时） | `core/tools/terminal_tool.py` |
| `web_search` | DuckDuckGo 网络搜索 | `core/tools/web_search_tool.py` |
| `read_file` | 读取文件（offset/limit） | `capability/example_tools.py` |
| `grep` | 正则搜索文件内容 | `capability/example_tools.py` |
| `knowledge_query` | 静态知识库语义搜索 | `capability/knowledge_capability.py` |
| `skills_list/view/manage` | 技能管理 | `core/skill_layer.py` |
| `record_learning` | Agent 主动提案学习内容 | `core/tools/record_learning_tool.py` |
| `consolidation_tools` (10) | L1/L2/L3 知识整理 CRUD + domain 管理 | `core/tools/consolidation_tools.py` |

**层可见性（ToolPolicy）**：

| 层 | 可见工具 |
|----|---------|
| L1 | `todo`, `knowledge_query` |
| L2 | `todo`, `terminal`, `read_file`, `grep`, `knowledge_query` |
| L3 | 全部（含 `web_search`, `skills_*`） |

> 当 `tools` 注入时自动禁用 `json_mode`（DeepSeek 不兼容）。输出改用 `@modify` markup 格式或 tool call 原生格式。

---

## 异步任务调度

sync 是所有工具的通用参数（Agent 可逐次覆盖）：
- sync=true（默认）：本轮阻塞等结果，同轮多个 sync 工具通过 run_sync_batch 并行执行
- sync=false：fire-and-forget，返回 task_id，Agent 通过 collect_tasks 后续收割

后端：TaskRunner（core/task_runner.py）— 线程池 + WAL 安全 task store + 运行统计。

## 学习记录（record_learning）

Agent 通过 record_learning 工具主动提案学习内容：
1. L1 Agent 提供 domain + learning_target + importance + reasoning
2. 后台 sub-agent 扫描 RoundTree（多轮 L1→L2→L3 决策树）补充 L2/L3 evidence
3. 写入 data/learning/pending/{domain}/{uuid}.json
4. LearningEnv 独立消费（与 Executor 解耦）

## 工具系统架构

所有工具通过 ToolRegistry 统一注册，ConsolidationContext 注入式管理 store 引用：
- Normal mode: tools.yaml allowlist → LayerInjector → Agent
- Consolidation mode: ConsolidationStrategy.build_tools() → ToolRegistry → Agent
- DictInjector 已废弃（consolidation tools 迁入 ToolRegistry）
- 全局 `set_consolidation_stores`/`set_learning_context` 已删除 → ConsolidationContext DI

## 捕获工具 (Capture Tools)

每层 Agent.decide() 通过 CaptureToolDef 声明式定义结构化输出工具：
- L1: `l1_query`(done=false) / `l1_report`(done=true)
- L2: `l2_query`(done=false) / `l2_report`(done=true)  
- L3: `l3_continue`(done=false) / `l3_report`(done=true)
统一 `_TOOL_RULES` 常量消除三层重复提示文本。

## ConsolidationStrategy

消除三层 decide() 的 `if lX_output_format` 分支：`ConsolidationStrategy.build_tools(agent, layer)` 一次封装 `allowed_base_tools` 过滤 + `consol_schemas` 查询 + `report_tool` 组装。

## SQLite 存储

运行时数据统一存 SQLite（WAL 模式，多并发安全）：
- data/cognitive/l2.db — L2 知识卡片
- data/cognitive/l3.db — L3 技能（含 SKILL.md 内容）
- data/cognitive/domain.db — 领域节点 + reverse_index
- data/cognitive/kb.db — KB 元数据

---

## 项目结构

```
cognitive-agent/
  _archive/              # 已归档旧架构代码
  config.yaml            # 用户配置（唯一入口，config/layers/*.yaml 已删除）
  pyproject.toml         # 项目元数据与依赖
  config/                # 分层工具配置
    tools.yaml           # per-layer tool allowlist + timeout/fallback
  capability/            # Phase 3 能力系统
    __init__.py          # Capability ABC + CapabilityRegistry
    tool_capability.py   # ToolCapability（层可见 allowlist）
    knowledge_capability.py  # KnowledgeCapability + InMemoryKnowledgeStore
    layer_injector.py    # LayerInjector（schema 注入 + 多轮 tool loop）
  core/                  # 核心源代码
    types.py             # TaskObservation, ExecutionRecord
    executor.py          # Executor — 独立决策者
    llm_client.py        # LLMResponse + LLMClient
    layer_message.py     # LayerMessage 信封 + MessageType 枚举
    task.py              # Domain, LearningUnit
    philosophy.py        # L1 规则 CRUD（内置校验）
    flexible_knowledge.py# L2 知识卡片管理
    skill_layer.py       # L3 技能管理
    agent_context.py     # AgentContext — per-env 工具过滤
    config_loader.py     # 统一配置加载 (config.yaml)
    model_manager.py     # embedding 模型单例 + 共享 models_cache
    chain_factory.py     # 统一构建三层链
    domain_registry.py   # DomainNode + DomainRegistry（反向索引+embedding）
    task_runner.py       # 异步任务调度（ThreadPool + stats）
    env/                 # 环境抽象 (base.py, learning_env.py, interaction_env.py, threshold_scorer.py)
    knowledge/           # KnowledgeBase — SQLite 向量知识库
    layers/              # 三层链式 Manager
      base.py            # LayerManager ABC + LayerAgent ABC + CaptureToolDef + ConsolidationStrategy
      comm.py            # UpwardComm/DownwardComm + AgentPacket（基类直接实例化）
      logging_setup.py   # 按 session 分目录的 per-layer 日志
      l0_5_1/            # L(0.5+1)Manager + L1Agent
      l2/                # L2Manager + L2Agent
      l3/                # L3Manager + L3Agent
    tools/               # ToolRegistry + 工具实现
      registry.py        # 注册中心
      terminal_tool.py   # 终端执行（优先 pwsh）
      web_search_tool.py # web_search + tavily_search
      file_tools.py      # read_file + grep
      kb_tools.py        # kb_query / ask_user / kb_delete / kb_fill_gap
      async_tools.py     # check_task / collect_tasks
      domain_tool.py     # L1 create_domain
      tool_proposal.py   # Agent 提案新工具
      sysinfo_tool.py    # 系统信息查询（os/hardware/env/network）
      consolidation_tools.py # 整理工具（9 CRUD handler 工厂化 + ConsolidationContext）
      record_learning_tool.py # record_learning + auto-learning dispatch
    storage/             # SQLite 存储后端 (l1_store, l2_store, l3_store, domain_store, kb_store)
  scripts/               # 运行脚本
    interactive_agent.py      # 交互式 CLI Agent
    run_leduc_cognitive.py    # Leduc 对局
    run_douzero_llm.py        # DouZero 对局
    run_learning_dryrun.py    # 学习 dry-run
    test_e2e_full.py          # E2E 全量测试（async dispatch + KB + learning）
    test_auto_learning.py     # auto-learning 管线测试
    test_consolidation_real.py# 真实 LLM consolidation 测试
  data/                  # 运行时数据
  tests/                 # pytest (206 tests, 27 files)
    fixtures/              #   Consolidation 测试数据
  docs/                  # 设计文档
```

---

## 实现计划

| 阶段 | 状态 |
|------|------|
| Phase 1 — Execute 链路 | ✅ 已完成 |
| Phase 1.5 — Comm Agent + LayerMessage + Agent while-loop design | ✅ 已完成 |
| Phase 2.1 — LearningEnv 骨架 | ✅ 已完成 |
| Phase 2.2 — 接入游戏循环 + 双域激活 | ✅ 已完成 |
| Phase 2.3 — 清理旧代码 + 元学习轨 | ✅ 已完成 |
| Phase 3.1 — Capability 系统（ABC + Tool + Knowledge + Injector） | ✅ 已完成 |
| Phase 3.2 — Consolidation（spec + 自动触发 + @modify 格式） | ✅ 已完成 |
| Phase 3.3 — Agent 层接入（真实 LLM 整理测试通过） | ✅ 已完成 |

## Consolidation — 知识整理

LearningEnv 作为特殊的外部环境，在检测到知识库超限时自动下发整理任务。任务通过 Executor + LayerChain 走完整的 Agent 链路：

```
容量监测（needs_consolidation）
       │ L2 cards > 25 or L3 skills > 15
       ▼
LearningEnv.build_consolidation_task()
       │ 读取 consolidation.yaml spec → 构建 TaskObservation
       ▼
Executor.execute(obs)
       │ L1 分解 → L2 分析卡/技能 → L3 匹配技能 → NOTIFY 链返回
       ▼
各层 NOTIFY（L2 reply 含 @modify markup）
       │ _parse_markup_modifications()
       ▼
per-layer modifications (create/update/deprecate)
       │ LearningEnv.step() → dry_run 或 正式应用
       ▼
知识库变更（合并冗余 → 归档低质 → 标记过期）
```

**整理等级**：
| Level | 触发条件 | 策略 |
|-------|---------|------|
| 0 | 所有层在软上限以下 | 无动作 |
| 1 | 超软上限 ≤5 条 | 例行归并（合并相似、标记 deprecated，可回滚）|
| 2 | 超软上限 >5 条 | 深度压缩（跨域抽象、L2→L3 编译、归档过时，需审核）|

配置规格见 `config.yaml` 的 `consolidation:` 段。测试脚本：`python scripts/test_consolidation_real.py`。

## 文档

- **[ARCHITECTURE.md](ARCHITECTURE.md)** — 完整架构设计：A1-A4 设计原则、E1-E8 工程原则、通信协议、各层详解、评估策略
- **[IDENTITY.md](IDENTITY.md)** — 每层 Agent 术语与概念：L1 行为准则 Agent、L2 知识卡片 Agent、L3 技能执行 Agent 的完整定义与领域边界
- **[COOKBOOK.md](COOKBOOK.md)** — README 各章节与代码位置的精确对照表
- **[MAINTAIN.md](MAINTAIN.md)** — 函数级维护文档
- **[LEARNING_JOURNAL.md](LEARNING_JOURNAL.md)** — 可迁移工程技巧记录
- **[DEBUG_JOURNAL.md](DEBUG_JOURNAL.md)** — 复杂 Bug 排查记录
