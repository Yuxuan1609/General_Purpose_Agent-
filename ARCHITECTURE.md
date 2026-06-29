# Architecture Design — Cognitive Agent

> 设计原则、系统架构、工具系统、执行流程、学习机制的完整描述。快速入门见 [README.md](README.md)，实验报告见 [EXPERIMENT_REPORT.md](EXPERIMENT_REPORT.md)。

本文档基于当前代码实现（2026-06-29），描述已落地的系统行为。

---

## 设计原则

### 架构原则

#### A1：层间严格相邻传递

三层认知链（L(0.5+1) ↔ L2 ↔ L3）之间**状态变更和数据请求必须通过相邻层传递**，禁止跨层跳跃。

相邻传递约束的是**信息流向**（谁可以和谁交流），不约束**交互次数**。一个逻辑阶段内相邻层之间可以进行多轮往返查询——这通过 `l1_query` / `l2_query` 工具在 `_call_llm` 的 tool loop 中实现。

```
AgentRuntime → Executor
                 │
                 ▼
        ┌──────────────────┐
        │   L(0.5+1)       │          ← 行为准则层
        │   (哲学 + 行为规则) │
        └────────┬─────────┘
                 │ l1_query / l2_query (工具调用)
                 ▼
        ┌──────────────────┐
        │   L2              │          ← 知识卡片层
        │   (概率性知识)      │
        └────────┬─────────┘
                 │ l2_query (工具调用)
                 ▼
        ┌──────────────────┐
        │   L3              │          ← 技能执行层
        │   (SKILL.md)      │
        └──────────────────┘
```

#### A2：统一层间消息信封

所有层间通信使用 `LayerMessage` 结构：

```python
@dataclass(frozen=True)
class LayerMessage:
    source: str          # 发送层标识
    target: str          # 接收层标识
    type: MessageType    # QUERY / RESPONSE / NOTIFY
    payload: Any         # 具体业务数据（TaskObservation）
    trace_id: str        # 跨层追踪 ID
    timestamp: datetime
    metadata: dict
```

每层 Manager 的 `query()` 接收 LayerMessage（或底层 dict），通过 `UpwardComm.receive()` 解包，处理后通过 `DownwardComm.wrap_query()` 向下传播。

> `PROPOSAL` / `APPROVAL` / `REJECTION` 已定义但当前未启用。

#### A3：层内信息隔离

每层只处理本层数据，只看到相邻层暴露的最小信息集：

| 原则 | 说明 |
|------|------|
| L(0.5+1) 不接触 L2 卡片内容 | 通过 `l1_query` 工具获取 L2 的 reply，不直接读取 L2 存储 |
| L2 不关心 L3 的 SKILL.md 格式 | 通过 `l2_query` 工具下发任务获取 L3 结果 |
| 每层暴露最小接口 | 只暴露 notify() 的 business dict，不暴露内部状态 |

**每层标准组件：**

```
Layer N:
  ┌─────────────────────────────────────────────────┐
  │  LayerAgent (LLM 决策)                           │
  │    ├─ decide() 单次调用                           │
  │    └─ _call_llm() 多轮 tool loop (max 30 turns)  │
  │                                                   │
  │  LayerManager (编排/状态管理)                      │
  │    ├─ query() 入口：解包 → 调用 decide → collect   │
  │    ├─ notify() 向上汇报本层结果                    │
  │    ├─ UpwardComm 上行消息解包                      │
  │    └─ DownwardComm 下行消息封装                    │
  └─────────────────────────────────────────────────┘
```

#### A4：Execute 与 Reflect 严格分离

学习（Reflect）被建模为独立环境 `LearningEnv`，与任务环境（GameEnv / InteractionEnv / Terminal-Bench）平级，共享同一套 Executor + Layers + 工具系统。

```
        ToolUse（工具系统，跨环境共享）
            ↑
  ┌─────────┼──────────────────────────┐
  │  TaskEnv │  LearningEnv             │
  │  (TB等)  │  domain="learning"       │
  │          │                          │
  │  产生     │  消费 ExecutionRecords    │
  │  行为记录 │  驱动 L1/L2/L3 演化       │
  └────┬─────┘  └───────────┬───────────┘
       └─────────┬──────────┘
                 ▼
       ┌──────────────────────┐
       │  Executor + Layers   │
       │  (L(0.5+1)↔L2↔L3)   │
       └──────────────────────┘
```

---

## 系统架构

### 顶层结构

```
入口 (interactive_agent / gradio_app / run_* / tb.runner)
  │
  ▼
setup_executor()
  ├─ load_env()                    # .env → os.environ
  ├─ build_llm_client()            # config.yaml → LLMClient
  ├─ build_default_chain()         # 构建三层链 + 注册工具
  │    ├─ init_registry()          # DomainRegistry + SQLite
  │    ├─ Philosophy / FK / SkillLayer
  │    ├─ build_chain()            # 创建 Managers + Agents
  │    ├─ _mount_tools()           # 注册全部工具 + LayerInjector
  │    └─ AgentContext             # per-env 工具过滤
  ├─ Executor(layer_root, llm)
  └─ register_runtime(chain, executor)
```

### 核心模块

| 模块 | 文件 | 职责 |
|------|------|------|
| **LLMClient** | `core/llm_client.py` | DeepSeek API 封装，支持 thinking/tool_calls/json_mode |
| **Executor** | `core/executor.py` | 独立决策者，发送 TaskObservation → 层链 → 收集 NOTIFY → 输出 action |
| **ToolRegistry** | `core/tools/registry.py` | 线程安全单例，管理所有工具的注册/分发/allowlist 过滤 |
| **LayerInjector** | `capability/layer_injector.py` | 按层注入工具 schema + 执行 tool calls |
| **TaskRunner** | `core/task_runner.py` | 全局线程池（8 workers），管理同步/异步工具调用的并行执行 |
| **SessionStore** | `core/session.py` | SQLite 持久化 session/task 元数据，支持 thread-local task context |
| **RoundTree** | `core/round_tree.py` | 记录每轮 L1→L2→L3 决策树，供 record_learning 消费 |
| **DomainRegistry** | `core/domain_registry.py` | 领域节点注册 + 反向索引，支持跨 L2/L3 检索 |
| **KnowledgeBase** | `core/knowledge/knowledge_base.py` | txtai BM25 + embeddings 知识检索，独立于 L2 卡片系统 |

---

## 层系统

### L(0.5+1) — 行为准则层

`core/layers/l0_5_1/manager.py`

- **L1Agent.decide()**：单次调用，LLM 在多轮 tool loop 中自驱决策
- **输出**：通过 `l1_report` capture tool 输出 `{done, result, reasoning}`
- **向下查询**：通过 `l1_query` 工具（ToolRegistry 普通工具）向 L2 查询
- **数据**：Philosophy Rules（L0.5 种子规则不可变 + L1 可演化规则，上限 20 条）
- **领域管理**：L1 是唯一有权创建/合并/废弃 domain 的层
- **学习提案**：通过 `record_learning` 工具记录值得固化的知识（异步，由 sub-agent 补充 detail）

### L2 — 知识卡片层

`core/layers/l2/manager.py`

- **L2Agent.decide()**：单次调用，基于 query + domain + 卡片 + L3 返回做决策
- **输出**：通过 `l2_report` capture tool 输出 `{done, reply, selected_cards, reasoning}`
- **向下调度**：通过 `l2_query` 工具向 L3 下发任务
- **数据**：FlexibleKnowledge Cards（上限 15 张，含 usefulness/misleading/comment 质量字段）
- **领域检索**：通过 DomainRegistry 反向索引按 domain 检索卡片
- **工具权限**：terminal / web_search / read_file / grep / tool_proposal / kb_*

### L3 — 技能执行层

`core/layers/l3/manager.py`

- **匹配**：DomainRegistry 反向索引 + SkillLayer.match() 两级匹配算法
- **L3Agent.decide()**：单次调用，基于匹配技能 + 任务执行
- **输出**：通过 `l3_report` capture tool 输出 `{done, result, skills_used, reasoning}`
- **数据**：SKILL.md 技能（YAML frontmatter + Markdown，上限 20 个）
- **工具权限**：terminal / read_file / grep / kb_query

### 层内决策流程（统一模式）

每层 Manager 的 `query()` 调用 `Agent.decide()` **仅一次**。多轮推理统一在 `_call_llm` 的 tool loop 中完成：

```
Agent.decide()
  └─ _call_llm(system, user, tools, capture_tools={report})
       └─ for turn in 1..max_tool_turns (默认30):
            ├─ LLM.chat(messages, tools)
            ├─ if tool_calls:
            │    ├─ 拆分为 capture tool vs 可执行工具
            │    ├─ 可执行工具：按 sync 拆 sync_batch/async_calls
            │    │    ├─ sync_batch → TaskRunner.run_sync_batch (并行)
            │    │    └─ async_calls → TaskRunner.submit (后台线程)
            │    ├─ 工具结果 → role:"tool" 消息追加到 messages
            │    └─ capture tool 命中 → 返回其 arguments 作为结构化输出
            └─ if 无 tool_calls → 返回最终内容 (JSON parse)
```

**Capture tool** 机制：`l1_report` / `l2_report` / `l3_report` 是特殊工具——LLM 调用它们时，其 arguments 被直接返回为结构化结果，不再执行工具 handler。这替代了早期在 prompt 中注入 JSON schema 的方式。

---

## 工具系统

### 注册与分发

所有工具通过 `core/tools/__init__.py:register_all_tools()` 统一注册到 `ToolRegistry` 单例。

| 类别 | 工具 | 说明 |
|------|------|------|
| **执行** | `terminal` | shell 命令执行（pwsh/powershell/cmd） |
| **搜索** | `web_search`、`tavily_search` | SearXNG 自部署 + Tavily AI 搜索 |
| **文件** | `read_file`、`grep` | 文件读取（含 offset/limit）+ 正则搜索 |
| **知识库** | `kb_query`、`kb_delete`、`kb_modify`、`kb_fill_gap` | 知识库 CRUD + 缺口填补（sub-agent） |
| **异步管理** | `check_task`、`collect_tasks` | 检查/收集异步任务结果 |
| **领域** | `query_domain`、`create_domain`、`merge_domain`、`deprecate_domain` | Domain 生命周期管理 |
| **固化** | `create_l*_rule/card/skill`、`deprecate_l*_*`、`modify_l*_*` | L1/L2/L3 条目 CRUD |
| **学习** | `record_learning` | Agent 提案学习（异步，sub-agent 补 detail） |
| **通讯** | `l1_query`、`l2_query` | 层间下行查询（同步阻塞，在 tool loop 内执行） |
| **交互** | `ask_user` | tkinter 弹窗 / console 向用户提问 |
| **系统** | `sysinfo` | OS/硬件/Python/网络信息 |
| **元工具** | `tool_proposal`、`activate_secondary_tools` | 工具提案 + 次工具按需激活 |

### Per-layer 访问控制

`config/tools.yaml` 定义每个工具的 `allowlist`（允许哪些层使用）和 `timeout`/`fallback`：

```yaml
tools:
  terminal:
    sync: true
    timeout: 300
    allowlist: [l1, l2, l3]
  read_file:
    sync: true
    timeout: 10
    allowlist: [l2, l3]
```

`LayerInjector.get_tools_for_layer(layer)` 按 allowlist 过滤，只返回该层可见的工具 schema。

### 同步/异步执行

每个工具的 schema 含 `sync` 参数（Agent 可逐次覆盖默认值）：

```
Agent 调用多个工具（同一 turn）:
  ├─ sync_batch: [read_file, grep, ...]     → TaskRunner.run_sync_batch (并行)
  └─ async_calls: [kb_fill_gap, ...]        → TaskRunner.submit (后台线程)
                                               → 返回 task_id
                                               → Agent 后续用 collect_tasks 收割
```

`_call_llm` 中存在特殊路径：当 tool calls 中包含 `l1_query` 或 `l2_query` 时，**所有 sync 工具改为串行 inline 执行**（主线程），确保下层查询的时序正确性。

### 次工具系统

`activate_secondary_tools` 让 Agent 在运行时按需搜索并激活次工具。次工具默认不可见（`tool_spec="secondary"`），LLM subagent 根据 `semantic_description` 筛选后通过 `ToolRegistry.enable_secondary()` 启用，仅在当前线程 session 内有效。

---

## 执行流程

### 单步执行（Executor.execute）

```
1. AgentRuntime → Executor.execute(TaskObservation)
2. Executor → chain_root.query(obs, trace_id)
3.   L(0.5+1).query():
     ├─ L1Agent.decide() ── _call_llm tool loop ──→ {done, result, reasoning}
     │    ├─ 可能调用 l1_query → L2.query() → 收到 reply
     │    └─ 最终调用 l1_report → 结构化输出
     └─ L1 node 写入 RoundTree
4.   L2.query() (由 l1_query 触发或独立):
     ├─ DomainRegistry 检索相关卡片
     ├─ L2Agent.decide() ── _call_llm tool loop ──→ {done, reply, ...}
     │    ├─ 可能调用 l2_query → L3.query() → 收到 result
     │    └─ 最终调用 l2_report → 结构化输出
     └─ L2 node 作为 L1 node 的子节点写入 RoundTree
5.   L3.query() (由 l2_query 触发或独立):
     ├─ DomainRegistry + SkillLayer 匹配技能
     ├─ L3Agent.decide() ── _call_llm tool loop ──→ {done, result, ...}
     │    └─ 最终调用 l3_report → 结构化输出
     └─ L3 node 作为 L2 node 的子节点写入 RoundTree
6. Executor.collect_notify() ← 各层 NOTIFY
7. L1 的 result 即为最终 action
8. Executor 返回 {action_text, notify_layers}
```

### 决策树记录

每轮执行在 `RoundTree` 中记录为：

```
L1 (root)
  ├─ L2 (child)  ← L1 通过 l1_query 调用时创建
  │   └─ L3 (child)  ← L2 通过 l2_query 调用时创建
  ├─ L2 (child)  ← L1 再次 l1_query 时创建
  │   └─ L3 (child)
  ...
```

`RoundHistory` FIFO 队列保留最近 5 轮。`record_learning` 工具通过 `RoundHistory.snapshot()` 获取决策树，由 LLM sub-agent 分析提取 L1/L2/L3 观察（observation）。

---

## 学习与 Consolidation

### record_learning 流程

```
Agent 调用 record_learning({learning_target, importance, reasoning})
  ├─ 异步提交到 TaskRunner
  ├─ sub-agent (LLM, json_mode):
  │    ├─ 扫描 RoundTree 快照
  │    ├─ 提取 L1/L2/L3 层与 learning_target 相关的 observation
  │    └─ 写入 data/learning/pending/{uuid}.json
  └─ 返回 task_id
```

当 `pending/` 目录积累 ≥5 个文件时，自动触发 `auto_learning`：读取所有 pending → 归档 → `LearningEnv` 构建 TaskObservation → Executor 执行 → 各层 apply 学习 → consolidation 检查。

### Consolidation（知识整理）

由 `LearningEnv.needs_consolidation()` 触发（L2 >25 卡或 L3 >15 技能）：

| 级别 | 触发条件 | 策略 |
|------|----------|------|
| Level 0 | 未超软上限 | 无需整理 |
| Level 1 | 超软上限，overflow ≤ 5 | 合并相似条目、归档过时内容（可逆） |
| Level 2 | overflow > 5 | 激进去重、跨域抽象、L2→L3 编译（不可逆） |

在 consolidation 模式下，Agent 的 prompt 中包含当前层的全部条目列表 + 使用统计，使用 CRUD 工具（`deprecate_l*_*`、`create_l*_*`、`modify_l*_*`）做整理。

---

## Terminal-Bench 集成

### 模块结构 (`tb/`)

| 组件 | 文件 | 职责 |
|------|------|------|
| **CognitiveAgent** | `tb/agent/cognitive_agent.py` | 将 cognitive-agent 封装为 TB BaseAgent |
| **TB 工具覆盖** | `tb/tools/tb_*.py` | terminal/read_file/grep 重写为 tmux send_keys + capture_pane |
| **FeedbackHarness** | `tb/feedback_harness.py` | 在容器存活期间插入多轮修复循环（pass@N） |
| **SessionHolder** | `tb/session_holder.py` | 模块级 tmux session 引用，供 TB 工具取 session |
| **学习过滤** | `tb/env.py` | train 开放学习工具，test/bench 通过 AgentContext deny |
| **运行入口** | `tb/runner.py`、`tb/run_epoch.sh` | monkey-patch Harness → 启动 TB CLI |

### 运行模式

| 模式 | 工具权限 | 反馈循环 | 用途 |
|------|----------|----------|------|
| **train** | 全部工具开放 | pass@4 (feedback loop) | 任务执行 + 学习记录 |
| **bench** | deny 18 个写学习工具 | pass@3 | 只读评测 learned agent |
| **test** | deny 18 个写学习工具 | 单次（无 feedback） | 纯单次评测 |

### 实验隔离

每个 train 实验前 fork 全量 `data/` 快照（L1/L2/L3/domain/KB 全部 SQLite 文件），实验后 restore，避免跨实验污染。关键快照见 `EXPERIMENT_REPORT.md` 附录 B。

---

## 工程原则

| 编号 | 原则 | 核心要求 |
|------|------|----------|
| E1 | **模块化与单一职责** | 每文件仅承担一项可陈述的职责；入口文件不寄生业务逻辑 |
| E2 | **接口先行与依赖倒置** | 每层暴露 ABC；组件依赖抽象而非具体实现 |
| E3 | **不可变数据优先** | 数据类型默认 frozen dataclass；状态变更返回新实例 |
| E4 | **原子持久化** | 所有文件写入使用 `tempfile + replace` 模式，保证崩溃安全 |
| E5 | **工具系统标准化** | 统一 `register(schema, handler)` 接口；错误返回 JSON `{"error": "..."}` |
| E6 | **测试先行** | 每个模块必须有对应测试文件；使用 mock 隔离外部依赖 |
| E7 | **配置与代码分离** | 环境相关值一律通过 `config.yaml` + 环境变量注入 |
| E8 | **错误边界与可观测性** | 明确每层的错误捕获策略；关键跨层调用记录结构化日志 |
| E9 | **Manager 无特殊分支** | Agent 行为由 prompt 决定、不由 Manager 的 if/else 硬编码。调度逻辑通过 task meta/state 注入 prompt |

---

## 数据存储

### SQLite 后端 (WAL 模式)

全部持久化走 SQLite，`check_same_thread=False` + `threading.Lock` 写锁保证跨线程安全：

| Store | 文件 | 存储内容 |
|-------|------|---------|
| L1SQLiteStore | `data/cognitive/l1.db` | Philosophy Rules |
| L2SQLiteStore | `data/cognitive/l2.db` | Knowledge Cards |
| L3SQLiteStore | `data/cognitive/l3.db` | Skills (SkillMeta) |
| DomainSQLiteStore | `data/cognitive/domain.db` | DomainGraph nodes + edges |
| KBSQLiteStore | `data/cognitive/kb.db` | 知识库 meta（可选） |
| SessionStore | `data/cognitive/sessions.db` | Session + Task 元数据 |

### txtai 知识库

KnowledgeBase 使用 vendored txtai 提供 BM25 + embedding 双路检索，数据存储在 `data/knowledge/`（config/embeddings/scoring/documents/kb.json）。

---

## 文档索引

- **[README.md](README.md)** — 项目概览、快速开始、实验汇总
- **[EXPERIMENT_REPORT.md](EXPERIMENT_REPORT.md)** — Terminal-Bench 完整实验报告
- **[MAINTAIN.md](MAINTAIN.md)** — 函数级维护文档（所有公开接口签名 + 调用关系）
- **[IDENTITY.md](IDENTITY.md)** — 层 Agent 术语与身份声明
- **[TB_BASELINE_RESULTS.md](TB_BASELINE_RESULTS.md)** — 基线详细结果与各实验过程
- **[TB_EXPERIMENT_PLAN.md](TB_EXPERIMENT_PLAN.md)** — 实验规划与方法论
