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
pytest tests/ -v                            # 运行测试
python scripts/interactive_agent.py         # 交互式 CLI
python scripts/run_leduc_cognitive.py       # Leduc 对局
python scripts/run_douzero_llm.py --mode cognitive  # DouZero 认知链
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
| `terminal` | 命令行执行（30s 超时） | `core/tools/terminal_tool.py` |
| `web_search` | SearXNG/DuckDuckGo 网络搜索 | `core/tools/web_search_tool.py` |
| `tavily_search` | Tavily AI 搜索（web_search 降级备选） | `core/tools/web_search_tool.py` |
| `read_file` | 读取文件（offset/limit） | `core/tools/file_tools.py` |
| `grep` | 正则搜索文件内容 | `core/tools/file_tools.py` |
| `kb_query`/`kb_delete`/`kb_fill_gap`/`kb_modify` | KB 查询/删除/补缺/修改 | `core/tools/kb_tools.py` |
| `ask_user` | 向用户提问（tkinter 弹窗 + console fallback） | `core/tools/kb_tools.py` |
| `query_domain` | 列出某 domain 下 L2 cards + L3 skills | `core/tools/consolidation_tools.py` |
| `create_domain` | 创建新 domain（可选初始 cards/skills） | `core/tools/consolidation_tools.py` |
| `deprecate_domain` | 删除 domain（有 orphaned item 时报错） | `core/tools/consolidation_tools.py` |
| `merge_domain` | 合并 source→target domain | `core/tools/consolidation_tools.py` |
| `tool_proposal` | Agent 提案新工具 | `core/tools/tool_proposal.py` |
| `sysinfo` | 系统信息查询（os/hardware/env/network） | `core/tools/sysinfo_tool.py` |
| `check_task`/`collect_tasks` | 异步任务状态查询/收割 | `core/tools/async_tools.py` |
| `record_learning` | Agent 主动提案学习内容 | `core/tools/record_learning_tool.py` |
| `l1_query`/`l2_query` | L1↔L2 / L2↔L3 向下通信 | `core/tools/downward_comm_tool.py` |
| `consolidation CRUD` (9) | L1/L2/L3 知识整理 deprecate/create/modify | `core/tools/consolidation_tools.py` |
| `knowledge_query` | 静态知识库语义搜索（KnowledgeCapability，需手动注册到 CapabilityRegistry） | `capability/knowledge_capability.py` |

**层可见性（ToolPolicy）** — 完整 allowlist 见 `config/tools.yaml`：

| 层 | 可见工具 |
|----|---------|
| L1 | terminal, kb_query, ask_user, create_domain, record_learning, deprecate/create/modify l1 rule (3), query_domain, deprecate_domain, merge_domain, tool_proposal, sysinfo, check_task, collect_tasks, l1_query |
| L2 | terminal, web_search, tavily_search, read_file, grep, kb_query, kb_delete, kb_modify, kb_fill_gap, ask_user, record_learning, deprecate/create/modify l2 card (3), query_domain, tool_proposal, sysinfo, check_task, collect_tasks, l2_query |
| L3 | terminal, web_search, tavily_search, read_file, grep, kb_query, kb_delete, kb_modify, kb_fill_gap, ask_user, deprecate/create/modify l3 skill (3), query_domain, tool_proposal, sysinfo, check_task, collect_tasks |

> 当 `tools` 注入时自动禁用 `json_mode`（DeepSeek 不兼容）。输出改用 `@modify` markup 格式或 tool call 原生格式。

---

## 工具调整路线图

以下为工具系统的规划优化项，基于当前代码现状分析提出，待后续实施。

### 1. 新增 `tool_overview` 工具

**现状**：Agent 通过 prompt 或尝试调用才知道有哪些可用工具，缺乏运行时自省能力。

**计划**：
- 新增 `tool_overview` 工具，注册到 `ToolRegistry`，对所有层可见
- 调用后返回当前 Agent 可见的 tool list（名称 + 描述 + 参数 schema 摘要）
- 实现方式：利用 `ToolRegistry.get_definitions()` + `AgentContext` 的 allowlist 过滤
- 帮助 Agent 在 while-loop 中动态了解自身能力边界

### 2. `tool_proposal` 改由 L1 也可用

**已完成**：allowlist 已改为 `[l1, l2, l3]`，L1/L2/L3 均可提案新工具。

### 3. 简化文件操作工具，改用 `terminal`

**现状**：L2/L3 同时拥有 `read_file`（`core/tools/file_tools.py:43`）和 `grep`（`core/tools/file_tools.py:116`）专用工具，与 `terminal` 功能重叠。

**计划**：
- 移除 `read_file` 和 `grep` 工具，文件读写统一通过 `terminal` 执行（`cat`、`grep`、`head`、`tail` 等命令）
- 消除 `file_tools.py` 中路径校验逻辑（`_validate_path:18`）的维护成本
- 保留 `set_workspace_root` 接口，作为 `terminal` 命令的路径安全层
- 风险与对策：`terminal` 不可用时降级到内置文件工具（fallback 机制）

### 4. KB 工具审查：`kb_query` / `kb_delete` / `kb_fill_gap`

**现状**（`core/tools/kb_tools.py`）：

| 工具 | 位置 | 可见层 | 实现复杂度 |
|------|------|--------|-----------|
| `kb_query` | `_kb_query_handler:226` | L1/L2/L3 | 高（依赖 `SubAgentLoop`，LLM 驱动的多轮查询） |
| `kb_delete` | `_kb_delete_handler:245` | L2/L3 | 低（直接 SQLite 操作） |
| `kb_fill_gap` | `_kb_fill_gap_handler:266` | L2/L3 | 高（依赖 `FillGapLoop`，LLM 驱动的填补管线） |

**计划**：
- `kb_query`：评估 `SubAgentLoop` 的可靠性与开销；考虑简化或用 `terminal` + 本地文件查询替代
- `kb_delete`：功能已清晰，增加 `dry_run` 参数预览删除影响
- `kb_fill_gap`：评估 `FillGapLoop` 的实际效果；考虑与 `kb_query` 合并为单一 KB 交互工具
- 统一 KB 工具的超时配置和错误处理策略

### 5. `check_task` / `collect_tasks` 优化

**现状**（`core/tools/async_tools.py`）：

| 工具 | 功能 | 问题 |
|------|------|------|
| `check_task` | 按 task_id 查状态 | 只返回 `status`，不返回部分结果或进度 |
| `collect_tasks` | 批量收割已完成任务 | 调用后移除任务记录，无法追溯历史 |

**计划**：
- `check_task` 增强：增加 `progress` 字段、预计剩余时间、部分结果预览
- `collect_tasks` 增强：增加 `keep_history` 参数，保留已收集任务的可选日志
- 合并为单一 `task_manager` 工具（`action: check | collect | list | cancel`）
- 增加 `list_tasks` 功能：按状态、工具名、时间范围列出所有任务

### 6. Consolidation CRUD 工具优化

**现状**（`core/tools/consolidation_tools.py`）：
- 9 个分离工具：`deprecate/create/modify` × L1/L2/L3
- 每个工具独立注册、独立 schema，但 handler 已通过 `_ModSpec`（`:223`）和 `_make_handler`（`:247`）统一工厂化

**计划**：
- 合并为 3 个跨层工具：`deprecate_item`、`create_item`、`modify_item`，每工具接受 `layer` 参数
- 工具数量从 9 降至 3，减少 Agent 的选择空间和 prompt 长度
- `_ModSpec` 和 `_make_handler` 工厂保持不变，仅包装层从 9 次注册变为 3 次
- 配套 `config/tools.yaml` 中仍按层配置 allowlist（L1 只能操作 l1 数据）

### 7. 任务追踪优化

**现状**（`core/task_runner.py`）：

| 方面 | 当前 | 问题 |
|------|------|------|
| 持久化 | 纯内存 `_tasks: dict` | 进程崩溃后丢失所有任务状态 |
| 历史 | `collect` 后删除 | 无法追溯已完成的异步任务 |
| 进度 | 仅 `running/done/error` | 无进度百分比或阶段信息 |
| 取消 | 不支持 | 提交后无法取消 |
| 超时 | 无单任务超时 | 卡住的任务永不会终止 |

**计划**：
- 增加可选的 SQLite 持久化层（参考 `data/cognitive/` 已有存储模式）
- 添加 `cancel(task_id)` 接口
- 单任务超时机制（`config/tools.yaml` 中每个工具的 `timeout` 应传递到 `TaskRunner`）
- 任务进度回调：允许 handler 更新 `progress`（0-100）
- `status()` 返回增加 per-task 耗时统计和资源使用

### 8. Sub-Agent 与 Fire-Dispatch 模式审查

**现状**：

| 模式 | 位置 | 说明 |
|------|------|------|
| `SubAgentLoop` | `scripts/interactive_kb_agent.py:217` | LLM 驱动的两阶段 KB 查询子 Agent（Search → Meta Review），`kb_query` 内部调用 |
| `FillGapLoop` | `scripts/interactive_kb_agent.py:550` | LLM 驱动的知识填补子 Agent，`kb_fill_gap` 内部调用 |
| 后台 sub-agent | `core/tools/record_learning_tool.py` | `record_learning` 提交后自动扫描 RoundTree 补充 L2/L3 evidence |
| Fire-Dispatch | `core/layers/base.py:246-351` (`_call_llm`) | 按 `sync` 参数拆分：sync=true 走 `run_sync_batch` 并行执行，sync=false 走 `TaskRunner.submit()` fire-and-forget |

**Fire-Dispatch 当前问题**：
- `_call_llm` async dispatch 后仅注入一条 `[Pending async tasks]` 系统消息（`:348`），Agent 需在下一轮手动调用 `collect_tasks` 收割，流程断裂
- 同一轮内 async 工具的结果无法被当前推理回合消费，增加 Agent 认知负担
- 同步批处理的超时 (`batch_timeout`) 硬编码为 300s（`:297`），未从 `config/tools.yaml` 读取各工具独立超时

**Sub-Agent 当前问题**：
- `SubAgentLoop` / `FillGapLoop` 依赖 `scripts/` 目录，不适合作为核心库代码被 `core/tools/kb_tools.py` 导入
- 子 Agent 内部无超时透传、无层上下文（layer context），无法感知 Agent 当前决策环境
- `record_learning` 的后台 sub-agent 与主线程完全解耦，无进度回查机制

**计划**：
- **Fire-Dispatch**：改为 async 结果自动注入下一轮 tool call 循环，消除 Agent 手动收割需求。同步批处理超时改为从 `config/tools.yaml` 按工具读取。评估 sync_batch 与 async_dispatch 是否可统一为单一 TaskRunner 队列。
- **Sub-Agent**：将 `SubAgentLoop` 和 `FillGapLoop` 从 `scripts/` 迁移到 `core/tools/` 作为内部工具代理，暴露统一接口并透传超时。增加进度反馈机制，允许主 Agent 在 while-loop 中查询子 Agent 状态。
- **统一调度层**：评估 `_call_llm` 中的工具调度逻辑是否应抽取为独立的 `ToolDispatcher` 组件，与 `TaskRunner` 结合，实现调度策略与 Agent 推理分离（A4）。

---

## 异步任务调度

sync 是所有工具的通用参数（Agent 可逐次覆盖）：
- sync=true（默认）：本轮阻塞等结果，同轮多个 sync 工具通过 run_sync_batch 并行执行
- sync=false：fire-and-forget，返回 task_id，Agent 通过 collect_tasks 后续收割

后端：TaskRunner（core/task_runner.py）— 线程池 + WAL 安全 task store + 运行统计。

> **潜在升级点：** `TaskState.progress` 字段和 `check_task` 的 `progress` 返回值已就绪，但目前没有 handler 调用 `update_progress()`，运行中 task 始终显示 0%。后续可在 terminal（Popen 轮询中）、kb_fill_gap 等长耗时 handler 内定期上报进度，前端即可显示实时进度条。
>
> **潜在升级点：并行层链遍历（l1_query/l2_query）。** 当前 `_call_llm` 中 `has_downward` 分支强制串行执行所有工具调用——根因是三层 Manager（L0_5_1/L2/L3）的 `_notify` 状态存储在实例变量上（`self._l1_notify`/`_l2_notify`/`_l3_notify`），多线程并发 `query()` 会互相覆盖。建议方案：将 notify 状态改为 per-trace_id 存储（thread-local dict `{trace_id: notify_dict}`），`query()` 写、`notify()` 读用 trace_id 索引。改动涉及三层 Manager + LayerManager ABC + downward_comm handler。改完后多个 `l1_query` 可在 TaskRunner 池中并行执行，显著减少 L1→L2→L3 链式查询延迟。
>
> **潜在升级点：downward comm 超时后状态泄漏追踪。** 当前 `downward_comm_tool` 用 `threading.Thread(timeout=X)` 做了 2000s 超时兜底，但超时后 daemon 线程继续运行到完成，会污染 Manager 共享状态（`_notify`）。改进方向：① downward query 移到 `TaskRunner.submit()` 异步执行，通过 `trace_id` 隔离状态；② 超时后标记 `task.cancel()` 并通过 `set_running_task_id` 协作式终止；③ `_call_llm` 收到超时 error JSON 后触发 `check_task(tid)` 轮询结果，而非完全丢弃。配合上一条 per-trace_id 状态改造后，多条 l1_query 可并行下发到 TaskRunner 池。

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
    llm_factory.py       # build_llm_client 工厂
    env_loader.py        # .env 加载
    layer_message.py     # LayerMessage 信封 + MessageType 枚举
    task.py              # Domain, LearningUnit
    philosophy.py        # L1 规则 CRUD（内置校验）
    flexible_knowledge.py# L2 知识卡片管理
    skill_layer.py       # L3 技能管理
    agent_context.py     # AgentContext — per-env 工具过滤
    config_loader.py     # 统一配置加载 (config.yaml)
    model_manager.py     # embedding 模型单例 + 共享 models_cache
    chain_factory.py     # build_default_chain — 统一构建三层链 + 挂载工具
    seed_knowledge.py    # init_registry + seed_knowledge 初始数据
    domain_registry.py   # DomainNode + DomainRegistry（反向索引+embedding）
    task_runner.py       # 异步任务调度（ThreadPool + stats）
    session.py           # SessionStore + thread-local task context
    setup.py             # setup_executor 共享入口（CLI/Gradio 共用）
    monitor.py           # 纯查询聚合模块（供 Gradio 前端展示）
    runtime_registry.py  # 全局 chain+executor 注册
    json_repair.py       # robust_parse 多层容错 JSON 解析
    round_tree.py        # DecisionNode + RoundHistory 决策树快照
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
    gradio_app.py            # Gradio Web UI（多 session + 并行任务追踪）
  data/                  # 运行时数据
  tests/                 # pytest (289 tests, 37 files)
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
- **[MAINTAIN.md](MAINTAIN.md)** — 函数级维护文档
- **[LEARNING_JOURNAL.md](LEARNING_JOURNAL.md)** — 可迁移工程技巧记录
- **[DEBUG_JOURNAL.md](DEBUG_JOURNAL.md)** — 复杂 Bug 排查记录
