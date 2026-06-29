# Cognitive Agent

具备分层自我学习能力的 AI 智能体系统。

## 灵感 / 动机

在 Agent Coding 场景下，一个非常有效的实践是让 Agent 自己维护 bug 日志和代码思路记录。每次踩坑后 Agent 记录原因和方案，下次遇到类似问题就能直接复用——就像一个不断增长的"经验笔记"。

本项目试图把这个简单的 journal 模式推向更结构化、自动化的方向：**基于信息分层，让学习不只是"记录"，而是系统性的观察 → 提炼 → 内化闭环**。Agent 在任务执行中自行决定学什么、学到哪一层、以及什么时候做知识整理。

受 ACT-R、Soar、CoALA 等认知架构的部分理念启发，但设计上保持独立。

## 核心架构

三层信息分层，链式相邻传递：

```
AgentRuntime → Executor → L(0.5+1) ↔ L2 ↔ L3
                              ↑ 链式相邻传递 ↑
```

| 层 | 信息类型 | 特性 |
|----|---------|------|
| **L(0.5+1)** | 不可变宪法 + 可演化行为规则 | L1Agent while-loop 决策 |
| **L2** | 概率性知识卡片（domain + confidence） | L2Agent while-loop 决策 |
| **L3** | SKILL.md 确定性技能 | 按 domain 匹配 + L3Agent while-loop 决策 |

每层内部由三个组件构成决策循环：

```
Agent (LLM 决策) ↔ Manager (编排/状态管理) ↔ Comm Agent (确定性协议)
```

### 关键设计决策

**学习即环境。** Reflection 不需要独立的架构设施。将其建模为 `LearningEnv`（与 GameEnv 共享 Executor + Layers + 工具系统），学习策略通过 `domain="learning"` 走现有链式通道——系统可以学到"如何学习"。

**环境决定格式，Agent 决定内容。** Environment 控制 Agent 看什么和输出什么格式；Agent 控制怎么推理和输出什么内容。两者严格解耦，Agent 不感知 Environment 类型。

**Agent 自主提案学习。** `record_learning` 工具让 Agent 自行决定学什么、存到哪层，`LearningEnv` 独立消费，不与 Executor 耦合。

## 快速开始

### 环境要求

- Python >= 3.10
- DeepSeek API Key（或其他 OpenAI 兼容端点）
- **推荐 WSL2（Windows 用户）** — `terminal` 工具在 Linux 下行为正常

### WSL 运行（Windows 推荐）

```powershell
wsl
cd /mnt/c/Users/micha/PycharmProjects/cognitive-agent
pip install pyyaml pytest ddgs
export DEEPSEEK_API_KEY=your-key-here
python3 -m pytest tests/ -v
```

### 配置

```bash
export DEEPSEEK_API_KEY=your-key-here
```

编辑 `config.yaml`（可选，默认值开箱可用）：

```yaml
main_llm:
  provider: deepseek
  model: deepseek-v4-flash
  api_key_env: DEEPSEEK_API_KEY
  thinking: true
  thinking_effort: high

runtime:
  max_tool_turns: 30
  task_runner_workers: 8
```

### 运行

```bash
pytest tests/ -v                            # 运行测试
python scripts/interactive_agent.py         # 交互式 CLI
python scripts/run_chess_agent.py           # 国际象棋学习（Maia3）
python scripts/run_douzero_llm.py --mode cognitive  # DouZero 认知链
```

## 新环境：Chess Learning（Maia3）

基于 **[Maia3](https://github.com/CSSLab/maia3)** 国际象棋人棋预测引擎构建的棋类学习环境，用于测试 cognitive agent 在纯推理领域的自学习能力。

### 安装

```bash
git clone https://github.com/CSSLab/maia3.git vendor/maia3
pip install -e vendor/maia3
pip install python-chess
```

### 使用

```bash
# 直接测试 Maia3 模型准确率
python scripts/run_chess_agent.py --no-llm --puzzles 10 --model maia3-5m

# 完整 cognitive agent 学习流程（5M 轻量模型）
python scripts/run_chess_agent.py --puzzles 5 --model maia3-5m --seed

# 79M 大模型（CPU 可跑，首次需下载 ~300MB）
python scripts/run_chess_agent.py --puzzles 5 --model maia3-79m --seed
```

### 评估方式

- **对手**：Maia3 引擎预测给定 Elo 的人棋最佳走法
- **奖励**：agent 走法偏离 Maia3 首选时递减（Top1=+1.0, TopN=+0.5/N, miss=-0.5）
- **模式**：puzzle（固定开局/中局/残局）或 random（随机合法局面）

| 模型 | 大小 | CPU 速度 | 预期准确率 |
|------|------|----------|-----------|
| maia3-5m | ~25MB | ~0.5s/局面 | 70% |
| maia3-23m | ~90MB | ~1s/局面 | — |
| maia3-79m | ~300MB | ~2s/局面 | 60% (小样本) |

## 实验：Terminal-Bench 学习与泛化验证

基于 **Terminal-Bench 2.0**（32 道 Debugging / SoftwareEng / SystemAdmin / Security 任务）进行了三个核心实验，验证分层认知架构的学习与泛化能力。详见 **[EXPERIMENT_REPORT.md](EXPERIMENT_REPORT.md)**。

### 实验概览

| 实验 | 设计 | 关键结果 | 结论 |
|------|------|----------|------|
| **Baseline** | 32 任务干净基线 | 23/32 PASS | 定出 9 个学习候选任务 |
| **Exp1 同任务学习** | 9 个 FAIL 任务 train → eval | 机制可跑通；初版因域不匹配学习态检索失效，retrain 后修复 | learning loop 完整闭环验证 |
| **Exp2 跨任务迁移（git 簇）** | 3 个 PASS 任务 train → 2 个 held-out eval | **held-out 2/2 翻转 FAIL→PASS**（baseline 0/2） | 正向跨任务迁移信号 |

### 核心发现

1. **学习能产生正向跨任务迁移**：git 簇 held-out 任务从 FAIL 翻转为 PASS
2. **可检索性是学习生效的前提**：卡片必须落在 agent 能检索到的 domain 下
3. **学习存在负向风险**：learned agent 可能把"记忆卡片"误当"任务环境对象"全盘搜索（卡片混淆）——已修复

### 实验档案

```bash
# 完整的实验报告、基线数据、实验计划、证据日志、运行结果均已纳入仓库：
EXPERIMENT_REPORT.md          # 正式实验报告（Baseline → Exp1 → Exp2 → Retrain）
TB_BASELINE_RESULTS.md        # 基线详细结果与各实验过程记录
TB_EXPERIMENT_PLAN.md         # 实验规划/方法论文档
evidence_logs/                # 关键证据日志（卡片混淆修复前后对比）
experiment_results/           # 所有实验轮次的原始运行结果
cogagent_exp_report_20260629.tar.gz  # 完整实验包（含 data_snapshots 状态快照）
```

### 已知限制与升级方向

**Domain 系统尚处早期。** 当前采用索引式设计，domain 由其下的 skill 和 knowledge card 定义——类似 RL 中 explore/exploit 的问题，domain 的归属更新策略尚未系统化解决。多 domain 场景下 agent 的跨域归纳抽象能力也未测试（理想情况：python 知识可迁移到 Java，数据结构知识可迁移到实际代码设计）。

**Scale-up 未完成。** 项目原始目标是大规模跨领域训练/学习提升模型能力，但受限于个人时间资源，目前仅在单个领域（git 簇，3 train + 2 eval）初步证明了框架学习有效性。Exp2 的 2/2 翻转作为 proof of concept 通过，但 5 个 case 样本量无法覆盖 LLM 固有的随机性波动。

**学习稳定性。** LLM 随机性 + 多轮 tool 调用的级联方差导致同一学习态的结果不稳定（如 git-leak：同份学习一次 40min ERR、一次 4min PASS）。需要多 seed 重复实验验证。

**自我迭代学习未达预期。** 理想中 agent 应能通过反复尝试任务的自我迭代来主动学习——每次失败后分析原因、固化经验、下次改进。但当前实验结果表明这种闭环效果不显著（Exp1 retrain 多轮 train 未带来持续提升）。两个潜在实验方向：

1. **引入强模型做"知识蒸馏"**：用更强的 teacher model（如 deepseek-v4-pro）在线或离线分析 agent 的失败轨迹，将提炼的经验/策略写入 L1/L2/L3→弱 model 作为 student 从这些先验知识受益。实现相对简单。（意义不大已经有大量先例了，主要是为了测试infrascture）
2. **优化冷启动内容与学习流程**：从种子阶段就写入优质学习策略（如"对复杂任务拆解并逐步实现"、"失败后先分析根因再重试而非盲目重试"），让 agent 在初始状态下就具备结构化的学习方法论。（受实验2启发，同domain下已经出现了类似的效果，能不能"泛化"并稳定复现）

## 项目结构

```
cognitive-agent/
  config.yaml            # 用户配置
  config/tools.yaml      # per-layer tool allowlist
  core/
    executor.py          # Executor — 独立决策者
    llm_client.py        # LLM 客户端
    layer_message.py     # LayerMessage 信封协议
    layers/              # 三层 Manager + Agent
      l0_5_1/            # L(0.5+1) 行为准则层
      l2/                # L2 知识卡片层
      l3/                # L3 技能执行层
    tools/               # ToolRegistry + 工具实现
      registry.py        # 统一注册中心
      terminal_tool.py   # 终端执行
      kb_tools.py        # KB 查询/修改
      consolidation_tools.py  # 知识整理 CRUD
      record_learning_tool.py # Agent 学习提案
      ...
    env/                 # GameEnv / LearningEnv / InteractionEnv
    storage/             # SQLite 存储后端（WAL 模式）
  capability/            # ToolCapability + KnowledgeCapability
  scripts/               # 运行与测试脚本
  tests/                 # pytest (331 tests)
  docs/                  # 设计文档
```

## 文档

- **[EXPERIMENT_REPORT.md](EXPERIMENT_REPORT.md)** — 学习/泛化实验报告
- **[TB_BASELINE_RESULTS.md](TB_BASELINE_RESULTS.md)** — 基线详细结果与实验过程记录
- **[TB_EXPERIMENT_PLAN.md](TB_EXPERIMENT_PLAN.md)** — 实验规划与方法论
- **[ARCHITECTURE.md](ARCHITECTURE.md)** — 完整架构设计：设计原则、通信协议、各层详解
- **[IDENTITY.md](IDENTITY.md)** — 每层 Agent 术语与概念
- **[MAINTAIN.md](MAINTAIN.md)** — 函数级维护文档
- **[LEARNING_JOURNAL.md](LEARNING_JOURNAL.md)** — 可迁移工程技巧记录
- **[DEBUG_JOURNAL.md](DEBUG_JOURNAL.md)** — 复杂 Bug 排查记录
