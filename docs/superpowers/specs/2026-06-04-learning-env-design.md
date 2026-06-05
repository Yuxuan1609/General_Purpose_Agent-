# LearningEnv Design

> **核心洞察**：Reflection 不需要独立架构。将学习建模为 `LearningEnv`（实现 `Environment` 接口），与 GameEnv 共享 Executor + Layers + ToolUse。学习走 `domain="learning/*"` 通过现有链式通道，系统因此可以学到"如何学习"（自举）。

## 核心理念

### 1. meta 与 domains 解耦

| | 含义 | 决定者 |
|---|---|---|
| **meta** | "什么任务" | Environment 决定 |
| **domains** | "激活哪些知识域" | Agent 根据任务内容推断 |

当前混淆是因为环境太简单。GameEnv 发 `"Play Leduc"` → 自动用 game 域够用。LearningEnv 发 `"分析最近 5 局 Leduc"` → 需要同时激活 `learning/reflect` + `game/leduc`。将来 CodingEnv 发 `"修复 auth 的 token 过期 bug"` → 激活 `coding/python` + `coding/auth` + `coding/bugfix`。

environments 只管发 meta，Agent 自己根据内容决定拉哪些知识域。

### 2. LearningEnv = 通用知识修改层

Agent 返回修改建议，LearningEnv 负责落实。不挑食——L2 卡片、L3 技能、L1 规则、未来工具注册，统一走 `step()`。

```
Agent → action = {target: "l2/card_42", type: "modify", payload: {...}}
      → LearningEnv.step(action)
        → 路由到对应 store 的 modify 方法
        → 返回 {status, reward}
```

二次检查暂不做，保留 `MetaDriver.validate_l1_change()` 作为最后防线（只拦不修）。

### 3. LearningEnv 内部双轨

LearningEnv 本身也有认知循环：

- **轨 1（数据驱动）**：消费 pending records → 产出"该学什么"——面向 Agent 的输出
- **轨 2（元学习）**：观察学习效果 → 调整自己的学习策略——面向自身的进化

轨 2 的学习结果跟 GameEnv 一样，往 learning domain 的知识库里写规则/卡片。

### 4. Reward = 学习域的自我强化

Reward 不是外部信号。learning domain 的知识越丰富 → Agent 越能判断"什么值得学" → 学习效果越好 → learning domain 积累更多经验。初期可能需要辅助设计，但这是核心理念。

```
第 1 轮学习: learning/reflect 知识很弱 → 靠 LLM 通用能力判断 → 可能不准
第 N 轮学习: learning/reflect 积累了大量"什么值得学"的卡片 → 判断更准
```

## 架构总览

```
                    ToolUse（跨环境共享）
                        ↑
  ┌─────────────────────┼──────────────────────────┐
  │  GameEnv (Leduc)    │  LearningEnv              │
  │  meta="Play Leduc"  │  meta="分析Leduc对局"     │
  │                     │                           │
  │  产出 ExecutionRecord│  定期扫描 pending/        │
  │  → pending/         │  轻量 LLM 预处理           │
  │                     │  raw → LearningUnit       │
  │                     │                           │
  │  env.step(action)   │  env.step(action)          │
  │  → game reward      │  → knowledge diff          │
  └──────────┬──────────┘  └──────────┬──────────────┘
             │                        │
             └──────────┬─────────────┘
                        ▼
             ┌──────────────────────┐
             │  Executor + Layers   │  ← 不关心背后是什么环境
             │  (L(0.5+1)↔L2↔L3)   │
             │                      │
             │  domains: ["game/leduc", "learning/reflect"]
             │  ← Agent 根据 meta 内容推断激活哪些域
             └──────────────────────┘
```

**完整数据流**：

```
GameEnv 对局 → ExecutionRecord → pending/{domain}/
                                      │
                                      ▼
              ┌─────────────────────────────────────────┐
              │  LearningEnv.reset()                     │
              │                                         │
              │  1. 扫描 pending/（沿用 threshold/scorer）│
              │  2. 一次轻量 LLM 调用：                  │
              │     把 raw Session JSON → LearningUnit  │
              │     （格式转换 + 初步聚类，不做判断）      │
              │  3. 包装为 TaskObservation               │
              └─────────────────────────────────────────┘
                                      │
                                      ▼
              TaskObservation {
                meta: "从以下对局中学习 Leduc 策略...",
                state: { learning_units: [...] },
                session: {
                  domain: "game/leduc",       # 保留（向后兼容）
                  domains: ["game/leduc", "learning/reflect"]  # Agent 激活的知识域
                }
              }
                                      │
                                      ▼
              Executor + Layers + ToolUse
              → Agent 天然同时用 game 域 + learning 域的知识
              → 输出既可能是 "fold"（游戏动作）也可能是 "extract_card"（学习动作）
                                      │
                                      ▼
              LearningEnv.step(action)
              → 统一知识写入门 → 路由到对应 store
```

## LearningEnv 内部结构

```python
class LearningEnv(Environment):
    """学习环境 —— 消费 ExecutionRecords，产出知识变更"""

    def __init__(self, pending_dir: Path, knowledge_stores: dict,
                 preprocessing_llm):  # 轻量 LLM，做 raw → LearningUnit 转换
        self._pending_dir = pending_dir
        self._knowledge = knowledge_stores  # l1/l2/l3 引用
        self._pre_llm = preprocessing_llm   # 冷启动：只做格式转换
        self._history: list = []
        self._pending_records: list[dict] = []

    def reset(self, task_description: str) -> EnvState:
        """扫描 pending → 轻量 LLM 预处理 → 返回 TaskObservation 可用状态"""
        domain = self._extract_domain(task_description)

        # 1. 扫描 pending/（沿用 ThresholdScorer）
        records = self._scan_pending(domain)
        if not records:
            return EnvState(observation="", info={"done": True, "reason": "no_pending"})

        self._pending_records = records

        # 2. 轻量 LLM 调用：raw Session JSON → structured LearningUnit
        #    一次调用即可 —— decomposer + refiner 在这步合为一体
        learning_units = self._build_learning_units(records)

        # 3. 包装为 observation text（Agent 直接放进 prompt）
        obs_text = self._format_observation(learning_units)

        return EnvState(
            observation=obs_text,
            info={
                "pending_count": len(records),
                "learning_units": len(learning_units),
                "base_domain": domain,
                "active_domains": [domain, "learning/reflect"],
            }
        )

    def _build_learning_units(self, records: list[dict]) -> list[dict]:
        """轻量 LLM 调用：raw Session → LearningUnit（游戏环境：一局一个）"""
        # 当前游戏环境：一局 = 一个 LearningUnit，数据结构简单
        # 将来复杂任务时这步会独立演进
        prompt = self._build_preprocess_prompt(records)
        response = self._pre_llm.chat(...)
        return json.loads(response)

    def step(self, action: dict) -> EnvStep:
        """落实 Agent 的修改建议 → 统一知识写入门"""
        # 路由到 L1/L2/L3/Tool 的 modify 方法
        result = self._apply(action)
        self._history.append(result)

        # 奖励：确定性验证（L0.5 去重/矛盾检测）
        reward = self._validate(result)

        done = self._should_stop()

        return EnvStep(
            state=self._build_state(),
            reward=reward,
            done=done
        )

    def _apply(self, action: dict) -> dict:
        """统一知识写入门"""
        target = action["target"]    # "l1/rule_id" | "l2/card_id" | "l3/skill_name"
        layer, key = target.split("/", 1)

        if layer == "l1":
            self._knowledge["l1"].modify_rule(key, action["payload"]["content"])
        elif layer == "l2":
            self._knowledge["l2"].modify_card(key, action["payload"]["content"])
        elif layer == "l3":
            self._knowledge["l3"].edit_skill(key, action["payload"]["content"])
        # ... tool store, etc.

        return {"status": "applied", "target": target}
```

## State（TaskObservation 可消费的观测）

```python
# LearningEnv.reset() 产出的 obs_text 格式（给 Agent 的 prompt 内容）：

"""
## 学习任务
目标：从以下 {N} 局 Leduc 对局中提取可改进的策略

## 对局摘要
[1/5] LOSS — 翻牌前加注，翻牌后对手反加 → 跟注到底 → 输给对手对子
      本轮 L2 激活卡片: ["preflop-raise 面对弱牌应加注", "postflop-pair 有对子应积极"]
      最终决策: call → 输

[2/5] WIN  — 翻牌前弃牌，保留筹码
...

## 当前知识状态
L1 规则: 12 条 (mix: l1=8, l0_5=4)
L2 卡片: 15 张 (game/leduc: 10, general: 5)
L3 技能: 3 个 (leduc-preflop-raise, leduc-postflop-pair, leduc-fold)
"""
```

> 游戏环境：一局一个 LearningUnit。将来复杂任务（如 coding session 拆分为多个子任务）时预处理步骤会独立演进。

## Agent 输出格式（修改建议）

```python
{
    "action": "modify",                    # modify | no_op
    "modifications": [
        {
            "target": "l2/card_42",        # l1/rule_id | l2/card_id | l3/skill_name
            "type": "update",              # update | deprecate | create
            "payload": {
                "content": "...",          # 修改后的完整内容
                "reason": "该卡片建议'有对子就加注'，但最近3局因此输牌"
            }
        },
        {
            "target": "l1/rule_7",
            "type": "create",
            "payload": {
                "content": "在翻牌后对手反加注时，需重新评估对子强度",
                "reason": "...",
            }
        }
    ],
    "reasoning": "本轮学习中发现了..."
}
```

## Environment ↔ Agent 职责边界

> 每个 Environment 自带通信层，**输出格式由通信层在 `meta` 字段中注入**。Agent（Executor + Layers）不感知背后是什么环境，只读 `meta` 中的格式约束并按格式输出。

```
┌─ Environment（含通信层）─────────────────────┐
│                                              │
│  ① 构建 TaskObservation                      │
│     meta = "任务目标 + 输出格式约束"           │
│     state = {当前观测, 历史, ...}              │
│     session = {domain, domains, ...}         │
│                                              │
│  ② 发送给 Agent ──────────────────────┐       │
│                                       │       │
└───────────────────────────────────────┼───────┘
                                        ▼
┌─ Agent（Executor + Layers）──────────────┐
│                                          │
│  ③ 层链推理（L1→L2→L3）                  │
│     按 meta 里的格式约束输出               │
│                                          │
│  ④ 返回 NOTIFY / action ──────────┐      │
│                                    │      │
└────────────────────────────────────┼──────┘
                                     ▼
┌─ Environment ──────────────────────────────┐
│                                            │
│  ⑤ env.step(Agent输出)                     │
│     GameEnv: 直接执行结构化 action          │
│     LearningEnv: 解析 NOTIFY → 执行修改    │
│                                            │
└────────────────────────────────────────────┘
```

| 谁 | 做什么 | 决定什么 |
|----|--------|---------|
| **Environment + 通信层** | 构建 TaskObservation，在 `meta` 中注入输出格式 | 输出格式 schema、任务目标描述 |
| **Agent（Executor + Layers）** | 读 `meta` 中的格式约束，层链推理，按格式输出 | 推理结果、策略决策、修改建议内容 |
| **Environment（step）** | 消费 Agent 输出，执行环境逻辑 | 是否终止、reward 计算 |

**LearningEnv 通信层注入的 meta 格式（示意）**：
```
meta: |
  ## 任务
  从以下 N 条执行记录中分析可改进的策略。

  ## 输出格式
  请以 JSON 格式返回，结构如下：
  {
    "analysis": "整体分析",
    "modifications": [
      {
        "target": "l1/rule_id | l2/card_id | l3/skill_name",
        "type": "update | create | deprecate",
        "payload": {
          "content": "修改后的内容",
          "reason": "原因"
        }
      }
    ]
  }
```

Agent 不硬编码任何输出 schema——所有格式约束来自 `meta`。

## 与 Executor + Layers 的集成

**核心流程**：LearningEnv ≠ GameEnv。GameEnv 的 `step()` 拿 Agent 按 `meta` 格式输出的结构化 action（"加注"/"出牌"）直接执行；LearningEnv 的 `step()` 拿到的是 Agent 按 `meta` 格式输出的修改建议 JSON。LearningEnv 解析后执行修改。

```
Agent (via Executor + Layers)
        │
        ▼ 按 meta 格式输出的 JSON（含 modifications 数组）
LearningEnv._parse_action(json_text)
        │
        ▼
structured modifications [{target, type, payload}, ...]
        │
        ▼
LearningEnv._apply(modifications)
        │
        ▼
knowledge store (L1/L2/L3)
```

**LearningEnv 内部的两个 LLM 调用点**：
1. **LLM₁（预处理）**：raw Session → LearningUnit，发给 Agent 之前做数据整理
2. **LLM₂（解析）**：NOTIFY 文本 → structured modifications（当 Agent 输出不是纯 JSON 时的 fallback）

> Phase 2.1 实现更新：`_parse_action()` 优先尝试 JSON 解析（Agent 按 meta 格式输出），失败时回退到 LLM₂ 解析。`build_task_observation()` 负责在 `meta` 中注入输出格式约束。

Executor 不需要额外处理 RESPONSE 这一路——LearningEnv 直接从 Agent 输出中解析。

| | GameEnv | LearningEnv |
|---|---|---|
| Agent 输出 | 结构化 action（按 meta 格式） | 结构化 JSON（按 meta 格式） |
| env.step() | 确定性执行 | 解析 → 执行 |
| 通信层 | 斗地主/简化的通信层 | LearningEnv 内建通信层 |
| meta 注入 | "请返回 {action: ...}" | "请返回 {modifications: [...]}" |
| fallback 解析 | 不需要（action 是简单字符串） | LLM₂ 解析非标准格式输出 |

## 与现有代码的关系

| 旧模块 | 处理方式 |
|--------|---------|
| `data/learning/pending/` | **直接复用** — LearningEnv 输入源，消费时机不变 |
| `core/orchestrator/threshold_scorer.py` | **回收** — score() → LearningEnv 的 trigger 条件 |
| `core/orchestrator/task_decomposer.py` | **合并进 LearningEnv** — decompose() + LearningRefiner 合为一次轻量 LLM 调用 |
| `core/orchestrator/learning_refiner.py` | **合并进 LearningEnv** — 同上 |
| `core/reflect_config.py` | **重构** — schema 移到 learning domain config |
| `config/layers/reflect.yaml` | **重构** — 内容移到 learning domain config |
| `core/layers/*/reflection_agent.py` | **删除** — 被 LearningEnv.step() 取代 |
| `core/orchestrator/reflect_coordinator.py` | **删除** — audit/run_reflect/archive 被 LearningEnv 状态机取代 |
| `core/layers/comm.py:ReflectPacket` | **删除** — 学习走标准 LayerMessage + AgentPacket |

## 关键设计决策

1. **meta 与 domains 解耦** — `session["domain"]` 保持向后兼容，新增 `session["domains"]` 支持多域。Agent 根据 meta 内容推断激活哪些知识域。

2. **LearningEnv = 通用修改层** — 统一的 `step()` 路由到 L1/L2/L3/Tool 的 modify 方法。Agent 决定 WHAT，LearningEnv 执行 HOW。

3. **数据预处理：一次轻量 LLM 调用** — raw Session → structured LearningUnit。Decomposer + Refiner 在此合为一体。不判断"好坏"，只做格式转换 + 初步聚类。游戏环境：一局一个 LearningUnit。

4. **双轨分离** — 轨 1（数据驱动）输出给 Agent，轨 2（元学习）更新 learning domain 自身。两者共享同一套知识存储。

5. **Reward = 学习域自我强化** — 不搞外部评分。learning domain 知识越丰富 → 判断越准 → 越能积累有效经验。Reinforcement 来自 domain 内部的 cards/skills 质量提升。

6. **Executor 无感** — 不修改 Executor 一行代码。TaskObservation 里多 domain 激活由 L2 的 stage1 自然处理（该 stage 已支持多域打分）。

7. **L2_DOMAIN_NODES 增加 `learning/reflect`** — 只需加一个节点，现有 L2 逻辑不需要改。Agent 自然同时激活 game + learning 域。

8. **冷启动逐个 case 处理** — learning domain 种子（L2 卡片、L3 技能）按具体场景逐一定制，不做统一安排。

9. **输出格式由通信层定义** — Agent 的输出 schema 不由 LearningEnv 硬编码。每个 Environment 有自己的通信层（如斗地主的通信层、LearningEnv 的通信层），通信层在 meta 里注入输出格式约束。Agent 收到的 TaskObservation 里，meta 已包含"请按以下格式输出"的指令。

10. **learning 域管理方式与 game 域一致** — 不考虑特殊工具。learning/reflect 域有自己专用的 L2 知识卡片和 L3 技能，管理方式（CRUD、编译、匹配）与 game 域完全相同。不引入 tool registry 的特殊处理。

11. **多域整合由当层 Manager 完成（待实践）** — 当两个域同时激活时（如 game/leduc + learning/reflect），各层 Manager 需要在 prompt 中同时注入两个域的知识。核心原则：
    - learning 域不会产出具体领域概念（如"加注"），但可能产出抽象指导（如"翻牌后应重新评估手牌强度"）
    - 若 game 域推理与 learning 域抽象指导冲突，由当层 Manager 负责在 prompt 中呈现双方观点，让 LLM 自行整合
    - 具体整合策略需要实践后确定，当前保持"双域知识均注入 prompt，LLM 自行权衡"

## 新文件

| 文件 | 职责 |
|------|------|
| `core/env/learning_env.py` | `LearningEnv(Environment)` 实现 |
| `data/layers/knowledge/learning/` | Learning domain 知识种子（卡片+技能，按 case 定制） |
| `config/layers/learning.yaml` | Learning domain 配置（预处理 LLM 参数、trigger 阈值等） |
| `tests/test_learning_env.py` | LearningEnv 单元测试 |
