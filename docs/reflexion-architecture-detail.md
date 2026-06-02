# Reflexion 架构详解

> **论文**: Reflexion: Language Agents with Verbal Reinforcement Learning
> **作者**: Noam Shinn, Federico Cassano, Edward Berman, Ashwin Gopinath, Karthik Narasimhan, Shunyu Yao (2023)
> **链接**: https://arxiv.org/abs/2303.11366
> **代码**: https://github.com/noahshinn024/reflexion
> **整理日期**: 2026-06-02
> **优先级**: ⭐⭐⭐ 必读

---

## 一、核心思想

不更新模型权重，而是通过**自然语言形式的自我反思**作为"语义梯度信号"，让 agent 从过往失败中学习。论文称之为 **Verbal Reinforcement Learning**。

> "We propose Reflexion, a novel framework to reinforce language agents not by updating weights, but instead through linguistic feedback."

关键比喻：反思文本 ≈ loss 的语义等价物，存储在 episodic memory buffer 中，作为后续 trial 的额外上下文。

---

## 二、第 3 章：架构（Reflexion: reinforcement via verbal reflection）

### 2.1 三组件模型

论文定义三个独立模型：

```
              ┌──────────┐
              │  Actor   │ ← LLM, 相当于 policy πθ
              │  (Ma)    │    生成文本和动作 at
              └────┬─────┘
                   │ trajectory τ = [a₀, o₀, a₁, o₁, ...]
                   ▼
              ┌──────────┐
              │ Evaluator│ ← 评估 τ 的质量
              │  (Me)    │    产出标量 reward r
              └────┬─────┘
                   │ r (二元/标量)
                   ▼
              ┌──────────┐
              │Self-Re-  │ ← 将稀疏 reward 放大为
              │flection  │    富语义的自然语言反馈
              │  (Msr)   │    分析 {τ, r} → 反思文本 sr
              └──────────┘
                   │ sr 存入长期记忆 mem
                   ▼
              Actor 下一轮以 mem 为额外上下文
```

#### Actor（行动者）

- 基于 LLM，相当于传统 RL 的 **policy πθ(aᵢ|sᵢ)**
- 参数 θ = {Ma, mem}，即 LLM 参数 + 记忆上下文
- 论文探索了两种 Actor 模式：
  - **Chain of Thought**（CoT）— 分步推理后给出答案
  - **ReAct** — 推理（Thought）与行动（Action/Action Input）交错
- 额外接收记忆上下文 `mem`，灵感来自 Brooks et al. 的 in-context policy iteration

#### Evaluator（评估者）

评估 trajectory 质量，产出标量 reward。论文尝试了三种：

| 方式 | 适用任务 | 具体含义 |
|------|---------|---------|
| **Exact Match（精确匹配）** | 推理（HotPotQA） | 生成答案与标准答案是否完全一致 |
| **预定义启发式** | 决策（ALFWorld） | 同一动作+同一响应 >3 轮 = hallucination；action 数 >30 = 低效规划 |
| **LLM 自评估** | 决策/编程 | 另一个 LLM 实例做二元分类；或自生成单元测试套件并执行 |

论文指出 semantic space 中定义有效的 reward 函数是困难的（"Defining effective value and reward functions that apply to semantic spaces is difficult"），因此他们才需要探索多种评估策略。

#### Self-Reflection（自我反思）— 核心创新

输入三样东西：
1. 稀疏 reward signal（如 binary success/fail）
2. 当前 trajectory τ
3. 已有长期记忆 `mem`

输出：反思文本 `sr`，比标量 reward 信息量大得多。

**具体例子**：多步决策中，agent 在第 i 步选了动作 aᵢ 导致后续 aᵢ₊₁ 和 aᵢ₊₂ 错误。反思时可以明确指出"应该在第 i 步选择 a'ᵢ 替代 aᵢ"，并推理出如果选了 a'ᵢ，后续应该是 a'ᵢ₊₁ 和 a'ᵢ₊₂。

这种能力是 **LLM 自身 emergent 属性**——附录 A 的结论明确写道：*"the ability to specify self-corrections is an emergent quality of stronger, larger models"*。

### 2.2 记忆系统

| 类型 | 对应 RL 概念 | 内容 | 特点 |
|------|------------|------|------|
| **短期记忆** | 当前 episode 的轨迹 | trajectory 历史 τₜ = [a₀, o₀, ..., aᵢ, oᵢ] | 每轮重置，细粒度 |
| **长期记忆** | 跨 episode 的经验 | Self-Reflection 输出的反思文本列表 mem = [sr₀, sr₁, ...] | 跨 trial 累积，受 context window 限制 |

设计动机（原文）：*"similar to the way that humans remember fine-grain recent details while also recalling distilled important experiences from long-term memory"*。

**容量限制**：mem 以滑动窗口方式存最近 1-3 条反思（LLM max context length 限制）。ALFWorld 用 3 条，编程用 1 条。

### 2.3 完整算法（Algorithm 1）

```
1:  初始化 Actor(Ma), Evaluator(Me), Self-Reflection(Msr)
2:  初始化 policy πθ(ai|si), θ = {Ma, mem}
3:  Actor 生成初始 trajectory τ₀ ← 此时 mem 为空
4:  Evaluator 评估 τ₀ → r₀
5:  Self-Reflection 分析 {τ₀, r₀} → sr₀
6:  设 mem = [sr₀]
7:  t = 0
8:  while Evaluator 未通过 and t < max_trials:
9:      Actor 以 mem 为上下文生成 τₜ = [a₀, o₀, ..., aᵢ, oᵢ]
10:     Evaluator 评估 τₜ → rₜ
11:     Self-Reflection 生成 srₜ
12:     mem.append(srₜ)
13:     t += 1
14:  return
```

### 2.4 Reflexion vs 传统 RL（原文列出的 4 个优势）

1. **轻量** — 不需要微调 LLM
2. **细致反馈** — 自然语言可表达"第 i 步该换哪个动作"这种比标量 reward 细得多的信号
3. **可解释** — episodic memory 是显式的自然语言文本
4. **明确指引** — 为下一轮提供具体的改进方向，而非仅仅一个数字

### 2.5 Reflexion vs Self-Refine（第 2 章 Related Work 的区分）

- **Self-Refine** [15]：**单 generation 内**的迭代自我修正（生成→自评→精炼→输出），不跨 trial
- **Reflexion**：**跨 trial** 的迭代学习，有**持久化的记忆**跨越不同 trial

---

## 三、第 4 章：实验

### 3.1 决策任务：ALFWorld（4.1 节）

**环境**：134 个 ALFWorld 文本环境（TextWorld 基础上的多步任务——找物体、移动物体、操作物体）

**Actor**：ReAct（含 few-shot 示例轨迹）

**评估**：环境二元成功信号 + 启发式（同一动作+同一响应 >3 轮 或 action 数 >30）

**反思触发方式**：
- Baseline：触发反思信号时 → 重置环境 → 开始新 trial（不做反思）
- Reflexion：触发反思信号时 → 用 Self-Reflection 分析错误 → 更新 mem → 重置环境 → 开始新 trial

**记忆容量**：最近 3 条反思

**结果**：
- ReAct + Reflexion → **130/134 任务完成（97%）**
- 纯 ReAct → 约 75%，且在第 6-7 轮后停止提升
- 绝对提升 **22%**

**常见失败模式分析**：
- Agent 以为自己有某物品但实际上没有 → 长序列无法回溯
- Reflexion 将长失败轨迹蒸馏为"自我提示"（self-hints），后续 trial 中避免同类错误

**两种长程记忆帮助 ALFWorld 的方式**：
1. 长 trajectory 中的早期错误容易被识别，agent 可以建议新的动作选择甚至全新计划
2. 物品太多需要逐个容器查找 → agent 跨 trial 利用经验记忆彻底搜索房间

### 3.2 推理任务：HotPotQA（4.2 节）

**环境**：100 个 HotPotQA 多跳问答

**Actor**：CoT（6-shot）/ ReAct（2-shot）

**评估**：exact match 二元成功信号

**Self-Reflection**：2-shot

**记忆容量**：3 条

**结果**：
- CoT/ReAct + Reflexion → **提升 20%**
- Baseline 不会概率性提升（temperature=0.7 下连续 trial 无改善）
- CoT (GT) + Reflexion：即使给了 ground truth context，baseline 仍有 39% 答错，Reflexion 在不知正确答案的情况下修正 14%

**消融实验（Episodic Memory ablation）**：
- CoT (GT) baseline → 60%
- + Episodic Memory（记住最近 trajectory，无反思）→ +8%
- + Self-Reflection（反思替代纯记忆）→ **再叠加 +8%**，总计 +14%

结论：*"self-reflection improves learning by an 8% absolute boost over the episodic memory learning advantage"* — 纯记忆不够，反思才是关键。

### 3.3 编程任务：HumanEval / MBPP / LeetcodeHardGym（4.3 节）

**评估方式**：自生成单元测试套件
1. CoT 生成多样化的测试用例 + 自然语言描述
2. AST 解析过滤非语法测试
3. 采样最多 6 个测试用例组成测试套件
4. 编译执行，全部通过则提交

**记忆上限**：1 条经验

**结果**：

| 基准 | 前 SOTA | Reflexion Pass@1 |
|------|---------|-----------------|
| HumanEval (Python) | 80.1 (GPT-4) | **91.0** |
| HumanEval (Rust, 50 最难题) | 60.0 (GPT-4) | **68.0** |
| MBPP (Python) | 80.1 (GPT-4) | 77.1（低于 GPT-4 基线） |
| MBPP (Rust) | 70.9 (GPT-4) | **75.4** |
| Leetcode Hard (Python) | 7.5 (GPT-4) | **15.0** |

**核心消融实验**（HumanEval Rust 50 最难题，base model = GPT-4）：

| 条件 | Test Gen | Self-Reflection | Pass@1 | 说明 |
|------|----------|----------------|--------|------|
| Base model | ✗ | ✗ | 60% | 一次生成，无学习 |
| Test generation omission | ✗ | ✓ | **52%** | 无测试验证，agent 不知道实现是否正确，对正确代码也做有害修改 |
| Self-reflection omission | ✓ | ✗ | **60%** | 测试能 catch 错误，但 agent 拿到"测试没通过"后不会修正——实现修正不反映测试指示 |
| **Full Reflexion** | ✓ | ✓ | **68%** | 两者叠加才有效 |

论文消融结论原文：*"the agent is unable to determine if the current implementation is correct without unit tests"* + *"the implementation fixes do not reflect these [test] indications"*。

**假阳性/假阴性分析**：
- **假阴性**：测试写错了，正确实现通不过 → Reflexion 能承受——agent 可以用反思识别错误的测试，保持原有实现
- **假阳性**：测试太弱，错误实现通过了所有测试 → 致命——agent 过早提交错误
- HumanEval Python 假阳性率仅 1.4% → 91% 准确率
- MBPP Python 假阳性率高达 16.3% → 77% 反而低于 GPT-4 基线

问题不在反思，在**自生成测试本身的质量**。

---

## 四、与本项目的关系分析

### 4.1 直接对应的组件映射

| Reflexion | 本项目 | 映射关系 |
|-----------|--------|---------|
| Actor（Ma，LLM 生成动作） | AgentLoop.run() 中的 LLM 调用 + 工具调度 | 核心一致，都是 LLM 驱动的动作生成 |
| Evaluator（Me，评估 trajectory） | MetaDriver 验证器 + POST-TOOL 进展跟踪 + Reflect 阶段质量评估 | 项目分散在多个环节，Reflexion 集中为单一 Evaluator 组件 |
| Self-Reflection（Msr） | MetaDriver._llm_reflection() | 功能等价，都是调用辅助 LLM 生成反思 |
| 短期记忆（trajectory 历史） | Execute 阶段完整消息日志（messages list） | 项目更完整（含 tool call 序列），Reflexion 只存文本 |
| 长期记忆（反思文本列表 mem） | L2 知识卡片 + L1 规则 + L3 技能 | **差异最大**：项目有结构化持久化，Reflexion 仅附加到 prompt |
| 跨 trial 循环 | A4 Task 级别的 Batch Reflect | Reflexion 单 task 多次 trial；项目是多个 task 一次 reflect |

### 4.2 关键差异分析

#### 差异 1：学习的持久化方式

- **Reflexion**：反思文本直接追加到 LLM prompt 中。优点是无额外存储开销，缺点是受 context window 限制（最多 1-3 条），且 agent 重启后丢失。
- **本项目**：L1 规则（JSON 持久化）+ L2 卡片（置信度/激活值/衰减）+ L3 技能（SKILL.md 文件）。优点是结构化、持久化、可跨 session 复用，缺点是实现复杂度高。

**借鉴价值**：Reflexion 的"把反思直接塞 prompt"对小项目是极简方案。但你的项目已经做得更完备——反射射结果被压缩为置信度增量（boost/penalize）而非原文存储，这实际上解决了 Reflexion 的 context window 瓶颈。

#### 差异 2：评估信号的来源

- **Reflexion**：三种评估严格分开（环境二元/启发式/LLM 自评估），在哪个任务用哪种是设计时选定的。
- **本项目**：评估信号分散——POST-TOOL 的停滞检测（≈启发式）、MetaDriver.check_completion()（≈环境二元）、Reflect 阶段的 LLM 反思评估。

**借鉴价值**：Reflexion 的 Evaluator 作为**独立组件**的设计更清晰。你的项目可以把 `check_completion()` + `track_progress()` + Reflect 中的评估标准化为一个统一的 Evaluator 接口，按任务类型切换策略。

#### 差异 3：Self-Reflection 的粒度

- **Reflexion**：反思是针对**整个 trajectory** -> 指出具体哪一步错 + 应该怎么做 -> 存储为自然语言文本。
- **本项目**：MetaDriver 的反思（`_llm_reflection()`）产出的是结构化的 JSON——knowledge_to_create（内容+置信度）+ l1_proposals（内容+理由）。

**借鉴价值**：Reflexion 的反思产出的是自由文本（"在第 i 步应该选择 a'ᵢ 而非 aᵢ"），人类可直接阅读，对 LLM 后续决策也更丰富。你的结构化方案更精确但信息量可能损失。可以考虑**反思文本原文也保留**一份，同时输出结构化数据——类似你 L2 卡片有 content 字段。

#### 差异 4：消融实验方法论

Reflexion 4.3 节的四步消融（Base → +Test → +Reflection → Full）是本项目可以直接复用的**验证框架**。你的架构有 4.5 层，每层都可以类似地开启/关闭来验证各组件的独立贡献。

### 4.3 可直接借鉴的设计

1. **Self-Reflection prompt 模板** — 附录中有完整的少样本示例，可用于改进你 MetaDriver 的 `TASK_COMPLETED_LLM_PROMPT`
2. **启发式停滞检测的阈值** — "同一动作+同一响应 >3 轮"是简单有效的策略；你的 `_check_stagnation` 用 `consecutive_no_progress >= 3`，思路一致但检测粒度更粗（Reflexion 看的是具体动作重复）
3. **Evaluator 统一接口** — 你可以把 MetaDriver 中分散的评估逻辑（`check_completion`、`track_progress`、`evaluate_triggers`、`_llm_reflection` 中的 quality check）整合成一个 `Evaluator` 类，按任务类型 `decision`/`reasoning`/`programming` 注入不同的评估策略
4. **编程任务的测试生成流程** — 如果未来项目涉及代码生成，CoT → AST 过滤 → 采样 n 条 → 编译执行的管线可以直接复用

### 4.4 你项目已超越的地方

| 维度 | Reflexion | 本项目 |
|------|-----------|--------|
| 记忆容量 | 1-3 条，受 context window 硬限制 | 分层持久化（JSON/MD 文件），理论上无上限 |
| 学习多样性 | 仅追加文本反思 | 三种机制：L2 boost/penalize、L1 规则变更（可控+审批）、L2→L3 编译 |
| 安全护栏 | 无 | L0.5 验证器防止重复/矛盾/过长规则 + 危险工具过滤 |
| 信息结构 | 反思是纯文本 | 结构化：置信度、激活值、衰减率、域路径、引用链 |
| 跨 session 持久化 | 无（全在 prompt 中） | 文件系统持久化，重启后不丢失 |
