# Cognitive Agent — 认知架构 AI 智能体

## 项目定位

构建一个具备**分层认知架构**的 AI 智能体系统，让 LLM 不仅能"思考"，还能"学习"——在任务执行中积累知识、提炼模式、优化行为。

受 ACT-R、Soar、CoALA 等认知架构理论启发，将传统单一 LLM 调用拆分为**三层专职 Agent 协作链路**，每层只处理本层数据，层间通过标准化消息协议通信。

## 核心架构

```
用户/环境 → Executor → L1(行为准则) ↔ L2(知识卡片) ↔ L3(技能执行)
                         ↑         链式相邻传递          ↑
```

- **L1 — 行为准则 Agent**：管理不可变宪法 + 可演化规则，负责任务拆解与最终决策
- **L2 — 知识卡片 Agent**：管理概率性知识卡片（domain + confidence），负责检索与调度
- **L3 — 技能执行 Agent**：管理 SKILL.md 标准化技能，负责确定性流程执行

每层内部由 **Agent（LLM 决策）↔ Manager（编排/状态管理）↔ Comm Agent（确定性协议）** 三组件构成 while-loop 决策循环。

## 关键设计决策

- **学习即环境**：将 Reflection 建模为普通 Environment（LearningEnv），与 GameEnv 共享执行链路，无需独立架构设施
- **工具系统**：统一 ToolRegistry 注册，CapabilityRegistry + LayerInjector 注入各层 Agent 的多轮 tool call 循环
- **异步调度**：同步工具并行批处理，异步工具 fire-and-forget，TaskRunner 线程池管理
- **SQLite 持久化**：WAL 模式，多并发安全，覆盖 L1/L2/L3 存储 + 域索引
- **知识整理（Consolidation）**：容量超限时自动触发 Agent 整理链路，合并冗余、归档低质

## 实现状态

| 模块 | 状态 |
|------|------|
| Layer 链路（L1↔L2↔L3 通信 + Agent while-loop） | ✅ 完成 |
| LearningEnv + 双域激活（game/learning） | ✅ 完成 |
| Capability 系统（ToolCapability + KnowledgeCapability + LayerInjector） | ✅ 完成 |
| 知识整理自动化（Consolidation spec + 触发 + Agent 整理） | ✅ 完成 |
| 异步任务调度（TaskRunner + sync/async 双模式） | ✅ 完成 |
| Gradio Web UI（多 session + 任务追踪 + 决策树可视化） | ✅ 完成 |
| Secondary Tools 系统（LLM subagent 筛选 + 懒加载） | ✅ 完成 |
| Terminal Bench 2.0 学习能力验证 | 🔄 进行中 |

## 技术栈

- **LLM**: DeepSeek API（OpenAI 兼容接口）
- **语言**: Python >= 3.11
- **存储**: SQLite（WAL 模式，每层独立存储）
- **工具系统**: 统一注册 + 层可见 allowlist + 次级工具懒加载
- **UI**: Gradio（多 session + 实时任务追踪）
- **测试**: pytest（331 tests）

## 当前阶段

项目正在 Terminal Bench 2.0 上验证学习能力：第一组实验以 8-10 个高难度 case 迭代做概念验证，第二组按类目划分 train/test split 评估泛化能力。
