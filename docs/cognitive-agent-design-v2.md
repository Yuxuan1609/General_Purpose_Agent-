# 认知架构 Agent — 详细设计文档 v2

> 创建日期: 2026-05-18
> 状态: 设计完成，待评审
> 上版文档: [v1 设计文档](./4.5-layer-agent-design.md)
> 参考文献: [参考文献汇总](./4.5-layer-agent-references.md)
> 参考实现: [Hermes Agent](https://github.com/NousResearch/hermes-agent) (v0.13.0)

---

## 一、项目定位

构建一个基于 4.5 层认知架构的 AI Agent 系统。不基于 LangChain、AutoGPT 等现有框架，从零实现。参考 Hermes Agent 的成熟工程实践（Tool 系统、Skill 格式、事件循环结构），加入 Hermes 缺失的**分层学习闭环**。

**Phase 1 目标**：在可评估任务环境中验证分层归因 + 层次化知识固化的闭环是否工作。

**与 Hermes 的关系**：
- Tool 系统结构、SKILL.md 格式、事件循环核心模式 → **借鉴**
- L0.5 元驱动、L1 自动演化、L2 激活衰减、分层归因 → **自建**
- L4 多索引知识库 → **暂缓**

**实现原则**：从 L0.5 到 L4 逐层优化。L0.5 是整个系统的"锚"——先把元驱动做对，再向下逐层验证各层信息流动是否正确。每层稳定后再进入下一层，不跳跃。

---

## 二、4.5 层架构

### 总览

```
┌──────────────────────────────────────────────────────────┐
│                    L0.5  元驱动层                          │
│  类型: 固定参数 · 硬编码在代码中 · Agent 不可修改           │
│  功能: 反思触发器 · L1 修改审批 · 任务分解入口               │
│  实现: ~150行 Python, 4个触发器(RULE×2 + LLM×2)            │
├──────────────────────────────────────────────────────────┤
│                    L1  哲学 / 行为准则层                    │
│  类型: 可演化参数 · Agent 可修改 · 需 L0.5 审批             │
│  功能: 行为规则集合 → 注入 system prompt                    │
│  实现: ~100行 Python + JSON存储, ≤20条, 每条≤100字          │
├──────────────────────────────────────────────────────────┤
│                    L2  柔性知识 / 领域经验                  │
│  类型: 概率性知识 · 带置信度和激活值 · Domain 分层          │
│  功能: 知识卡片存储 · 上下文激活 · 时间衰减 · 经验积累       │
│  实现: ~200行 Python + JSON + Graph (无数据库依赖)          │
├──────────────────────────────────────────────────────────┤
│                    L3  半静态能力 (Skills)                  │
│  类型: 过程性记忆 · 编译后的可调用单元                      │
│  功能: 技能匹配 · L2→L3 固化 · SKILL.md 管理               │
│  实现: ~200行 Python + SKILL.md 文件 (借 Hermes 格式)       │
├──────────────────────────────────────────────────────────┤
│                    L4  静态知识库                           │
│  状态: ★ Phase 1 暂缓 ★                                    │
│  接口: build_context() 已预留插入点                         │
│  未来: 多索引 (语义+关键词+领域+时间) + 无限扩展              │
└──────────────────────────────────────────────────────────┘
```

### 层间约束

- 上层可读取/调用下层，**下层不能直接修改上层**
- L0.5 是唯一可以修改 L1 的入口（通过反思验证）
- L1 约束 L2 的激活条件，L2 为 L3 的创建提供经验模板
- 未来 L4 被所有层读取，只被 L0.5 和 L2 写入

### 可改性层次

```
完全不可变 (代码层)
┌──────────────────────────────────┐
│  L0.5 触发器逻辑 (硬编码)         │
│  L0.5 校验规则 (硬编码)           │
│  触发冷却时间                     │
│  L1 最大容量 (= 20)              │
│  L1 单条最大字数 (= 100)          │
│  L3 固化阈值 (= 3张同域卡 + 0.7)  │
│  Domain 层级结构                  │
├──────────────────────────────────┤
│  种子 L1 规则 (初始值用户可改)    │  ← 用户配置文件
│  LLM 连接信息                     │  ← 用户配置文件
│  存储路径                         │  ← 用户配置文件
│  最大迭代次数                     │  ← 用户配置文件
├──────────────────────────────────┤
│  L1 规则内容 (运行时)             │  ← Agent 可改 (L0.5 审批)
│  L2 知识卡片 (运行时)             │  ← Agent 运行时读写
│  L3 技能文件 (运行时)             │  ← Agent 可创建/修改
└──────────────────────────────────┘
完全可改 (运行时)
```

---

## 三、L0.5 — 元驱动层详细设计

### 触发器定义 (硬编码在 `core/meta_driver.py`)

```python
from enum import Enum
from dataclasses import dataclass, field
from typing import Callable

class TriggerType(Enum):
    RULE = "rule"      # 硬编码 Python 判定
    LLM = "llm"        # 轻量 LLM 子 Agent 判定

@dataclass
class ReflectionTrigger:
    id: str
    trigger_type: TriggerType
    condition_desc: str         # 人类可读描述
    rule_check: Callable | None # RULE 类型使用
    llm_prompt: str | None      # LLM 类型使用的判定 prompt
    cooldown_rounds: int        # 触发后冷却轮数
    last_triggered_at: int = 0  # 上次触发的轮次

# ── 硬编码的 4 个初始触发器 ──

DEFAULT_TRIGGERS = [
    # RULE 类型：确定性条件判断
    ReflectionTrigger(
        id="stagnation",
        trigger_type=TriggerType.RULE,
        condition_desc="连续 3 轮无实质进展",
        rule_check=lambda ctx: ctx.consecutive_no_progress >= 3,
        cooldown_rounds=5,
    ),
    ReflectionTrigger(
        id="task_failed",
        trigger_type=TriggerType.RULE,
        condition_desc="evaluator 明确判定任务失败",
        rule_check=lambda ctx: ctx.eval_result == "failure",
        cooldown_rounds=1,
    ),

    # LLM 类型：需要语义判断
    ReflectionTrigger(
        id="task_completed",
        trigger_type=TriggerType.LLM,
        condition_desc="任务看起来已完成，需 LLM 确认是否真正成功并提取经验",
        llm_prompt=(
            "Review the following task execution. Determine:\n"
            "1. Has the task been completed successfully?\n"
            "2. Was the approach efficient, or could it be improved?\n"
            "3. Are there reusable patterns worth remembering?\n"
            "4. Should any behavioral rules (L1) be added or modified?\n\n"
            "Task: {task_description}\n"
            "Domain: {domain}\n"
            "Execution history: {execution_summary}\n\n"
            "Respond in JSON:\n"
            '{{"completed": bool, "efficient": bool, '
            '"patterns_found": ["..."], '
            '"knowledge_cards_to_create": [{{"content": "...", "confidence": 0.0-1.0}}], '
            '"l1_proposals": [{{"content": "...", "reason": "..."}}]}}'
        ),
        cooldown_rounds=3,
    ),
    ReflectionTrigger(
        id="domain_shift",
        trigger_type=TriggerType.LLM,
        condition_desc="进入新的问题领域，需 LLM 判断是否需要跨域知识迁移",
        llm_prompt=(
            "The agent has entered a new problem domain.\n"
            "New domain: '{new_domain}'\n"
            "Previous domains encountered: {previous_domains}\n"
            "Current L2 knowledge domains: {l2_domains}\n\n"
            "Determine:\n"
            "1. Is this truly a new domain requiring new knowledge structures?\n"
            "2. What adjacent domains might have transferable knowledge?\n"
            "3. What general-domain knowledge is most relevant?\n\n"
            "Respond in JSON:\n"
            '{{"is_new_domain": bool, '
            '"adjacent_domains": ["..."], '
            '"recommended_general_cards": ["card_id_1", ...]}}'
        ),
        cooldown_rounds=10,
    ),
]
```

### 触发执行流程

```
每个 task turn → 遍历 DEFAULT_TRIGGERS:
  ├── cooldown 未过期? → 跳过
  ├── RULE 类型 → 直接执行 rule_check(context)
  │   └── 返回 True → 触发反思
  └── LLM 类型 → 使用 auxiliary_llm 执行 llm_prompt
      │   (带 prompt caching 避免重复 token 消耗)
      └── 返回 structured JSON → 解析判定结果

任何触发器激活:
  ├── 重置 cooldown (last_triggered_at = current_round)
  └── 调用 MetaDriver.run_reflection(trigger, task, messages)
      └── 进入 post_task() 学习闭环
```

### L1 修改校验规则

```python
# 硬编码的校验规则 — Agent 不可修改
@dataclass
class ValidationRule:
    id: str
    description: str
    check_fn: Callable  # (proposed_rule, existing_rules) → (approved:bool, reason:str)

DEFAULT_VALIDATORS = [
    ValidationRule(
        id="no_contradiction",
        description="新规则不能和已有规则逻辑矛盾",
        check_fn=check_no_contradiction,   # LLM 辅助判定
    ),
    ValidationRule(
        id="has_condition",
        description="新规则必须有明确的适用条件",
        check_fn=check_has_trigger_condition,
    ),
    ValidationRule(
        id="not_duplicate",
        description="新规则不能与已有规则高度重复",
        check_fn=check_not_duplicate,       # 简单相似度
    ),
    ValidationRule(
        id="under_limit",
        description="规则总数不超过 MAX_L1_RULES",
        check_fn=lambda proposed, existing: (
            len(existing) < MAX_L1_RULES,
            f"已达上限 {MAX_L1_RULES} 条" if len(existing) >= MAX_L1_RULES else ""
        ),
    ),
    ValidationRule(
        id="under_length",
        description="单条规则不超过 MAX_RULE_LENGTH 字符",
        check_fn=lambda proposed, existing: (
            len(proposed.content) <= MAX_RULE_LENGTH,
            f"规则长度 {len(proposed.content)} 超过上限 {MAX_RULE_LENGTH}"
        ),
    ),
]
```

### 接口预留

```python
class MetaDriver:
    """L0.5 元驱动。所有方法都是可继承/可覆盖的接口。"""

    def evaluate_triggers(self, ctx: TaskContext) -> list[ReflectionTrigger]:
        """★ 扩展点: 遍历所有触发器，返回激活的列表"""
        ...

    def run_reflection(self, trigger, task, messages) -> ReflectionResult:
        """★ 扩展点: 执行反思流程"""
        ...

    def validate_l1_change(self, proposal, existing_rules) -> tuple[bool, str]:
        """★ 扩展点: L1 修改审批。可新增校验规则"""
        ...

    def filter_dangerous(self, tool_calls: list) -> list:
        """★ 扩展点: 危险工具调用拦截"""
        ...

    def check_completion(self, task, messages) -> str:
        """★ 扩展点: 任务完成判定。可替换 evaluator"""
        ...

    def task_decompose_trigger(self, task: Task) -> list[Task]:
        """★ 扩展点: 任务分解入口。可替换分解策略"""
        ...
```

---

## 四、L1 — 哲学/行为准则层详细设计

### 数据模型

```json
// data/l1_rules.json
{
  "version": 3,
  "max_rules": 20,
  "max_rule_length": 100,
  "rules": [
    {
      "id": "l1_001",
      "content": "面对不确定信息时优先搜索验证，不要直接假设答案",
      "created_by": "seed",
      "added_at": "2026-05-01T00:00:00Z",
      "version": 1,
      "last_modified": "2026-05-01T00:00:00Z"
    },
    {
      "id": "l1_002",
      "content": "当同一种方法连续3次失败时，主动尝试替代方案而非坚持原路径",
      "created_by": "reflection",
      "added_at": "2026-05-03T12:00:00Z",
      "version": 1,
      "last_modified": "2026-05-03T12:00:00Z"
    }
  ]
}
```

### 核心操作

```python
class Philosophy:
    """L1 哲学层。管理行为规则的完整生命周期。"""

    def __init__(self, rules_path: Path, max_rules: int = 20, max_rule_length: int = 100):
        self.rules_path = rules_path      # ★ 路径可配置
        self.max_rules = max_rules        # ★ 容量可配置
        self.max_rule_length = max_rule_length  # ★ 长度可配置
        self._rules: list[Rule] = []

    # ── 查询 ──
    def all_rules(self) -> list[Rule]:
        """返回所有规则。留作未来 dashboard。"""
        ...

    def get_active_rules(self, task: Task) -> list[str]:
        """
        ★ 扩展点: 给定任务，返回当前活跃的规则内容列表。
        当前实现: 返回全部规则（数量极少，无需过滤）。
        未来: 基于任务 domain/类型 选择性激活。
        """
        ...

    # ── 修改 (经 L0.5 审批后调用) ──
    def add_rule(self, content: str, created_by: str = "reflection") -> Rule:
        """添加规则。由 L0.5 审批通过后调用。"""
        ...

    def modify_rule(self, rule_id: str, new_content: str) -> Rule:
        """修改已有规则。version + 1。"""
        ...

    def remove_rule(self, rule_id: str) -> None:
        """删除规则。需要 L0.5 明确审批。"""
        ...

    def apply(self, proposal: L1Proposal) -> None:
        """L0.5 审批通过后统一入口。"""
        ...

    # ── 持久化 ──
    def _load_index(self) -> None:
        """加载 l2_index.json → 构建 KnowledgeGraph"""
        ...

    def _rebuild_index(self) -> None:
        """
        ★ 自动维护: 扫描 knowledge_dir 下所有 MD,
        解析 ## 标题, LLM 生成摘要/关键词, 检测新关系,
        更新 l2_index.json。
        """
        ...

    def _write_md(self, domain: Domain, filename: str, content: str) -> Path:
        """写入 MD 文件 → 触发 _rebuild_index()"""
        ...

    # ── Graph 操作 ──
    def get_adjacent_chapters(self, chapter_id: str) -> list[tuple[str, str]]:
        """获取相邻章节。用于跨域类比检索。"""
        ...

    def spread_activation(self, seed_ids: list[str], steps: int = 2) -> dict[str, float]:
        """从种子节点沿关系边激活扩散。"""
        ...
```

### L1 修改流程

```
反思结果 → L1Proposal(内容, 原因)
  → MetaDriver.validate_l1_change()
    → 遍历 DEFAULT_VALIDATORS
    → 全部通过 → approved
    → 任一拒绝 → rejected + 记录原因
  → approved: Philosophy.apply(proposal) → _save()
  → rejected: 原因记录到 L2 作为知识卡片 (标记为失败的修改尝试)
```

### System Prompt 注入格式

```
[Behavioral Principles — Agent Philosophy]
- 面对不确定信息时优先搜索验证，不要直接假设答案
- 当同一种方法连续3次失败时，主动尝试替代方案而非坚持原路径

These principles guide your behavior. You may propose additions or modifications
through reflection, which will be reviewed before acceptance.
```

---

## 五、L2 — 柔性知识层详细设计

### Domain 体系

```python
@dataclass(frozen=True)  # 不可变 — 作为 dict key
class Domain:
    """领域标识符。支持层次化路径。"""
    path: str          # "textworld/map_A" | "programming/python" | "general"
    level: str         # "specific" | "general"

    @property
    def is_general(self) -> bool:
        return self.level == "general"

    @property
    def parent(self) -> "Domain | None":
        """textworld/map_A → textworld"""
        parts = self.path.rsplit("/", 1)
        return Domain(parts[0], "general") if len(parts) > 1 else None

    @property
    def depth(self) -> int:
        """路径深度。general=0, textworld=1, textworld/map_A=2"""
        return self.path.count("/") + 1 if self.path != "general" else 0

    def is_ancestor_of(self, other: "Domain") -> bool:
        """self 是否是 other 的祖先域"""
        return other.path.startswith(self.path + "/")

    def is_descendant_of(self, other: "Domain") -> bool:
        return self.path.startswith(other.path + "/")
```

**Domain 层次示例：**

```
general/                              depth=0  ← 跨域通用知识
├── "复杂问题应该分解为子步骤"           confidence:0.9
├── "失败后应该反思而非盲目重试"          confidence:0.85
│
textworld/                            depth=1  ← 游戏领域通用知识
├── "上锁的门通常需要匹配的钥匙"          confidence:0.9
├── "物品经常藏在容器里需要仔细搜索"      confidence:0.7
│
textworld/map_A/                      depth=2  ← 特定地图知识
├── "map_A的钥匙在厨房抽屉里"           confidence:0.9
├── "map_A的宝藏在阁楼"                confidence:0.95
│
programming/                          depth=1
├── "修改代码前先读测试文件了解预期行为"   confidence:0.85
│
programming/python/                   depth=2
├── "项目使用 .venv 而非 venv"         confidence:0.8
```

### KnowledgeCard 数据结构

```python
@dataclass
class KnowledgeCard:
    id: str
    content: str                    # 知识内容 (自然语言)
    domain: Domain                  # ★ 领域归属 (替代扁平 tags)
    sub_tags: list[str]             # domain 内的细粒度标签 ["navigation", "key_search"]
    confidence: float               # 0.0-1.0, 创建时设定, 基于来源可靠性
    activation: float               # 0.0-1.0, ★ 运行时动态计算
    last_used: datetime             # 上次被激活的时间
    decay_rate: float               # 每日衰减率, 默认 0.01
    source: str                     # "observation" | "deduction" | "user" | "reflection"
    success_count: int = 0          # 被成功使用的次数
    failure_count: int = 0          # 关联失败的次数
    created_at: datetime            # 创建时间
    updated_at: datetime            # 最后更新时间

    # ── 激活值计算 (核心算法) ──

    def compute_activation(self, task_domain: Domain, task_context: str) -> float:
        """
        激活 = domain匹配度 × confidence × recency_boost

        domain匹配度权重:
          精确匹配 (same path)     → 1.0
          本域是任务的子域           → 0.5
          本域是任务的父域           → 0.7
          本域是 general domain     → 0.4 (始终适用但权重低)
          完全不相关                 → 0.0 (不激活)
        """
        domain_score = self._domain_match_score(task_domain)
        if domain_score == 0.0:
            return 0.0

        recency_score = max(0, 1.0 - _days_since(self.last_used) * 0.1)
        return min(1.0, self.confidence * (domain_score * 0.6 + recency_score * 0.4))

    def _domain_match_score(self, task_domain: Domain) -> float:
        if self.domain.path == task_domain.path:
            return 1.0
        if self.domain.is_general:
            return 0.4
        if task_domain.parent and self.domain.path == task_domain.parent.path:
            return 0.7
        if self.domain.parent and self.domain.parent.path == task_domain.path:
            return 0.5
        return 0.0

    # ── 衰减 ──

    def apply_decay(self):
        """时间衰减：activation *= (1 - decay_rate) ^ days_since_last_use"""
        days = _days_since(self.last_used)
        self.activation *= (1 - self.decay_rate) ** days

    # ── 反馈更新 ──

    def boost(self):
        """成功使用 → 提升 confidence"""
        self.confidence = min(1.0, self.confidence + 0.05)
        self.success_count += 1
        self.activation = min(1.0, self.activation + 0.1)
        self.last_used = datetime.now()

    def penalize(self):
        """关联失败 → 降低 confidence"""
        self.confidence = max(0.1, self.confidence - 0.1)
        self.failure_count += 1
```

### FlexibleKnowledge 核心操作

```python
class FlexibleKnowledge:
    """L2 柔性知识层。JSON + Graph 轻量持久化，不引入数据库依赖。"""

    def __init__(self, knowledge_dir: Path, index_path: Path):
        self.knowledge_dir = knowledge_dir   # MD 文件根目录 (按 domain 分)
        self.index_path = index_path         # JSON 索引文件
        self.cards: list[KnowledgeCard] = []
        self.graph: KnowledgeGraph | None = None  # 运行时从 JSON 构建

    # ── 查询 ──

    def get_active_cards(self, task_domain: Domain, task_context: str,
                         top_k: int = 5) -> list[KnowledgeCard]:
        """
        ★ 扩展点: 给定任务 domain 和上下文，返回 top-k 最高激活的知识卡片。
        当前实现: tag-match + recency。
        未来: spreading activation 在图结构上传播。
        """
        ...

    def get_domain_cards(self, domain: Domain) -> list[KnowledgeCard]:
        """获取指定 domain 下所有卡片 (含子域)"""
        ...

    # ── 写入 ──

    def add_card(self, card: KnowledgeCard):
        """添加新知识卡片。原子写入。"""
        ...

    def update_from_tool_results(self, task: Task, results: list):
        """★ 扩展点: 根据工具执行结果更新卡片激活值。"""
        ...

    def apply_updates(self, updates: list[KnowledgeUpdate], domain: Domain):
        """post_task 中批量应用知识更新。"""
        ...

    def add_failed_proposal_record(self, proposal: L1Proposal):
        """记录被 L0.5 拒绝的 L1 修改建议。作经验积累。"""
        ...

    # ── 衰减 (定时触发) ──

    def run_decay_cycle(self):
        """对所有卡片执行时间衰减。可定时/周期调用。"""
        ...

    # ── 统计 ──

    def domain_stats(self, domain: Domain) -> dict:
        """某 domain 下的卡片数量、平均 activation、平均 confidence"""
        ...
```

### L2 知识卡片的生命周期

```
创建:
  observation  → 任务执行中观察到的模式 (confidence: 0.5-0.7)
  deduction    → 反思推导的结论 (confidence: 0.6-0.8)
  user         → 用户直接告知 (confidence: 0.9-1.0)
  reflection   → L0.5 反思产物 (confidence: 0.7-0.9)

激活:
  每轮 pre-LLM 时 compute_activation(task.domain)
  → top-5 注入 context block

更新:
  post-tool: 如果知识被使用且工具成功 → boost()
  post-tool: 如果知识被使用但工具失败 → penalize()
  post-task: 反思生成的新知识 → add_card()

衰减:
  定时 decay_cycle → 降低长期未使用卡片的激活值
  当 activation < 0.1 → 标记为 dormant (保留但不注入 context)

→ L3 固化:
  同一 domain 下 ≥3 张卡片且平均 activation > 0.7
  → L0.5 触发 → LLM 生成 SKILL.md → L3 创建技能
  → 原 L2 卡片保留 (不删除), marker 标记为 "compiled_to_skill"
```

### L2 持久化: MD + JSON + Graph

三层存储，各司其职:

```
knowledge/                         ← L2 知识根目录
├── general/                       ← 通用知识
│   ├── task-strategy.md
│   └── learning-patterns.md
│
├── textworld/                     ← 领域知识
│   ├── map-navigation.md
│   │   # 地图导航
│   │   ## 上锁的门通常需要匹配的钥匙
│   │   ## 先探索未知房间再深入已知区域
│   │   ## 记录钥匙位置避免重复搜索
│   └── item-search.md
│       # 物品搜索
│       ## 物品经常藏在容器里
│       ## 先搜索与任务相关的房间
│
├── programming/                   ← 另一领域
│   └── python-venv.md
│
└── l2_index.json                  ← ★ JSON 索引 (自动维护)
```

**MD 文件** — 原始内容，按章节 (`##`) 组织。人类可读。每个 domain 目录下按主题分文件。

```markdown
# knowledge/textworld/map-navigation.md

# 地图导航

## 上锁的门通常需要匹配的钥匙
在 TextWorld 中，遇到上锁的门时，钥匙通常在同一地图的某个房间内。
不要尝试绕过门，应该系统性搜索相邻房间。

## 先探索未知房间再深入已知区域
进入新地图时，优先遍历所有未访问的房间，而不是在已知区域反复搜索。
这能最大化发现新物品和线索的概率。

## 记录钥匙位置避免重复搜索
找到一个钥匙后，立即在记忆中记录它的原始位置和对应的门。
这样后续玩同一地图时可以直接定位。
```

**JSON 索引** — 章节名 + 摘要 + 关系。Agent 写入 MD 后自动更新。快速检索不读 MD。

```json
// knowledge/l2_index.json
{
  "version": 3,
  "updated_at": "2026-05-18T15:00:00Z",
  "chapters": [
    {
      "id": "textworld/map-navigation",
      "title": "地图导航",
      "domain": "textworld",
      "source_file": "knowledge/textworld/map-navigation.md",
      "sections": [
        {
          "heading": "上锁的门通常需要匹配的钥匙",
          "summary": "钥匙在同一地图内，应系统性搜索相邻房间而非绕过门",
          "keywords": ["locked door", "key", "adjacent rooms", "systematic search"]
        },
        {
          "heading": "先探索未知房间再深入已知区域",
          "summary": "新地图优先遍历未访问房间，最大化信息和物品发现",
          "keywords": ["exploration", "unknown rooms", "new map", "prioritization"]
        },
        {
          "heading": "记录钥匙位置避免重复搜索",
          "summary": "找到钥匙后立即记录位置和对应门，供后续复用",
          "keywords": ["key location", "memory", "recording", "reuse"]
        }
      ]
    },
    {
      "id": "textworld/item-search",
      "title": "物品搜索",
      "domain": "textworld",
      "source_file": "knowledge/textworld/item-search.md",
      "sections": [...]
    }
  ],
  "relations": [
    {
      "from": "textworld/map-navigation",
      "to": "textworld/item-search",
      "type": "cross_reference"
    },
    {
      "from": "textworld/map-navigation",
      "to": "general/task-strategy",
      "type": "cross_reference"
    },
    {
      "from": "general/task-strategy",
      "to": "textworld/map-navigation",
      "type": "parent_child"
    }
  ]
}
```

**4 种关系类型:**

| 类型 | 含义 | 示例 |
|------|------|------|
| `parent_child` | 层级包含，子章节是父章节的特化 | general/task-strategy → textworld/map-navigation |
| `cross_reference` | 跨域引用，不同领域但相关 | textworld/map-navigation → textworld/item-search |
| `prerequisite` | 前置依赖，必须先理解A再看B | textworld/basics → textworld/map-navigation |
| `analogous` | 类比，不同领域但结构相似 | programming/debugging → textworld/troubleshooting |

**Graph** — 运行时从 JSON `relations` 构建邻接表。纯内存，不持久化。用于激活扩散和跨域类比检索。

```python
class KnowledgeGraph:
    """运行时图。从 l2_index.json 的 relations 构建。"""
    
    def __init__(self, index: dict):
        self.adjacency: dict[str, list[tuple[str, str]]] = {}
        # domain_id → [(target_id, relation_type), ...]
        for rel in index["relations"]:
            self.adjacency.setdefault(rel["from"], []).append(
                (rel["to"], rel["type"])
            )
    
    def get_adjacent(self, chapter_id: str) -> list[tuple[str, str]]:
        """获取相邻章节及关系类型"""
        return self.adjacency.get(chapter_id, [])
    
    def spread_activation(self, seed_ids: list[str], steps: int = 2) -> dict[str, float]:
        """从种子节点出发，沿边扩散激活。用于跨域类比检索。"""
        ...
```

**JSON 自动维护流程:**

```
Agent 写入/修改 MD 文件 (通过 terminal tool 或 skill_manage)
  → 触发索引更新钩子
  → 解析 MD: 提取 ## 标题 + 对应段落
  → LLM (auxiliary) 为每个 section 生成摘要和关键词
  → 更新 l2_index.json:
      - 新增/修改 chapters 条目
      - 检测新关系 (LLM 判断与其他章节的关系类型)
      - 版本号 +1
  → 下次运行时从 JSON 构建 Graph
```

---

## 六、L3 — 半静态能力层详细设计

### 技能文件格式 (借用 Hermes agentskills.io 标准)

```yaml
# skills/textworld/finding-keys/SKILL.md
---
name: finding-keys
description: "Systematic approach to finding keys in TextWorld grid environments"
domain: textworld              # ★ 新增: 所属领域
cross_domain: false            # ★ 是否跨域通用
version: 1.0.0
created_by: l2_compilation     # "seed" | "agent" | "l2_compilation"
created_at: "2026-05-15T00:00:00Z"
source_cards: ["l2_card_003", "l2_card_007", "l2_card_012"]
---
# Finding Keys in TextWorld

## When to Use
- When a locked door blocks progress
- When exploring a new map for the first time

## Procedure
1. Note all locked doors and their locations
2. Search rooms adjacent to locked doors first
3. Check all containers (drawers, chests, cabinets) in each room
4. If key not found after full sweep, check behind furniture and under rugs
5. Record key locations for this map in knowledge base (L2)
```

### SkillLayer 核心操作

```python
class SkillLayer:
    """L3 技能层。管理 SKILL.md 文件的完整生命周期。"""

    def __init__(self, skills_dir: Path, tool_registry: ToolRegistry):
        self.skills_dir = skills_dir
        self._register_tools(tool_registry)

    # ── 查询 (progressive disclosure) ──

    def match(self, task_domain: Domain) -> list[SkillMeta]:
        """
        给定任务 domain，返回匹配技能列表。
        匹配规则: exact domain > parent domain > general (cross_domain=true)
        Phase 1: 只返回 metadata (name + description)。
        技能 body 在 Agent 调用 skill_view 时按需加载。
        """
        ...

    def list_all(self) -> list[SkillMeta]:
        """所有已安装技能。留作 dashboard。"""
        ...

    # ── 固化 (L2 → L3, 核心创新) ──

    def should_create_skill(self, domain: Domain,
                            domain_cards: list[KnowledgeCard]) -> bool:
        """
        固化阈值判定 (硬编码):
        - 同一 exact domain 下 >= 3 张卡片
        - 平均 activation > 0.7
        ★ 扩展点: 阈值常量可调，判定逻辑可替换
        """
        ...

    def propose_skill(self, domain: Domain,
                      cards: list[KnowledgeCard]) -> dict:
        """
        调用 LLM (auxiliary) 将一组高激活 L2 卡片编译为 SKILL.md。
        输入: 知识卡片列表
        输出: SKILL.md 的 YAML frontmatter + markdown body
        """
        ...

    def propose_and_create(self, domain: Domain,
                           cards: list[KnowledgeCard]) -> SkillMeta:
        """合并 propose + create。调试/手动触发用。"""
        ...

    # ── CRUD (借鉴 Hermes skill_manager_tool) ──

    def create_skill(self, name: str, content: str,
                     domain: Domain, cross_domain: bool = False) -> SkillMeta:
        """创建技能文件。原子写入 + 安全扫描 (可选)。"""
        ...

    def edit_skill(self, name: str, new_content: str) -> SkillMeta:
        """全量替换 SKILL.md。"""
        ...

    def patch_skill(self, name: str, find: str, replace: str) -> SkillMeta:
        """定向修改。"""
        ...

    def delete_skill(self, name: str) -> None:
        """删除 → 移到 .archive/ (从不真删除, 借鉴 Hermes curator)。"""
        ...

    # ── 导入 ──

    def import_skill(self, skill_path: Path) -> SkillMeta:
        """从外部 SKILL.md 文件导入。用于种子技能。"""
        ...
```

### L2→L3 固化流程

```
L0.5 post_task 反思后:
  │
  ├── 1. L2 新增/更新知识卡片
  │
  ├── 2. 检查: should_create_skill(domain, domain_cards)
  │     ├── 条件不满足 → 跳过
  │     └── 条件满足 →
  │         ├── propose_skill(): LLM 编译 cards → SKILL.md
  │         ├── create_skill(): 原子写入技能文件
  │         ├── 标记 source_cards: cards 的 id 列表
  │         └── 不删除原 L2 卡片 (保留追溯链)
  │
  └── 3. 日志: "New skill created: {name} in domain {domain}"
```

---

## 七、事件循环与层集成

### 事件循环结构

```python
class AgentLoop:
    """
    最小事件循环。结构提取自 Hermes run_conversation()。
    去掉: 多 provider fallback, context compression, streaming,
          steer/interrupt, prompt caching, 40+ 种错误分类。
    保留: while 循环模式, API message 准备, tool dispatch, 结果追加。
    """

    def __init__(self, llm_client, tool_registry, layers: LayerContext,
                 max_iterations: int = 50):
        self.llm = llm_client
        self.tools = tool_registry
        self.layers = layers
        self.max_iterations = max_iterations

    def run(self, task: Task) -> TaskResult:
        messages = []
        iteration = 0
        self.layers.meta.reset_turn_state()

        # ── L0.5: 任务分解入口 ──
        if task.needs_decomposition:
            subtasks = self.layers.meta.task_decompose_trigger(task)
            if subtasks:
                task.subtasks = subtasks

        # ── System prompt (一次构建，缓存整轮) ──
        system_prompt = self._build_system_prompt(task)
        messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": task.description})

        while iteration < self.max_iterations:
            iteration += 1

            # ── ★ 插入点1: PRE-LLM ──
            context_block = self.layers.build_context(task)
            if context_block:
                # 注入当前 user message，不修改 system prompt
                messages[-1]["content"] += "\n\n" + context_block

            # ── API call (with 1 retry) ──
            try:
                response = self.llm.chat(
                    messages=messages,
                    tools=self.tools.schemas,
                )
            except Exception as e:
                if self._should_retry(e):
                    continue  # 简单重试 1 次
                raise

            if response.has_tool_calls:
                # ── ★ 插入点2: PRE-TOOL ──
                filtered = self.layers.filter_tool_calls(
                    response.tool_calls
                )

                # ── Tool dispatch ──
                assistant_msg = {"role": "assistant", "tool_calls": [...]}
                messages.append(assistant_msg)
                tool_results = self.tools.dispatch(filtered)
                for name, result in tool_results:
                    messages.append({
                        "role": "tool",
                        "name": name,
                        "content": result,
                    })

                # ── ★ 插入点3: POST-TOOL ──
                self.layers.on_tool_results(task, tool_results)

            else:
                # Text response (无 tool call)
                messages.append({
                    "role": "assistant",
                    "content": response.text,
                })

                # ── ★ 插入点4: COMPLETION CHECK ──
                verdict = self.layers.check_completion(task, messages)
                if verdict == "done":
                    break
                # "continue" → 继续循环让模型自己决定下一步

        # ── ★ 插入点5: POST-TASK (学习闭环) ──
        return self.layers.post_task(task, messages)
```

### 5 个插入点定义

| # | 插入点 | 触发时机 | 当前逻辑 | 扩展方向 |
|---|--------|---------|---------|---------|
| 1 | PRE-LLM | 每次 LLM 调用前 | L1 规则 + L2 top-5 卡片 + L3 匹配技能名注入 user message | +L4 多索引检索结果 + RAG |
| 2 | PRE-TOOL | Tool call 执行前 | L0.5 危险操作拦截 + L1 行为过滤 | +安全沙箱 + 资源预算检查 |
| 3 | POST-TOOL | Tool 执行结果返回后 | L2 激活值更新 + L0.5 停滞检测 | +实时在线学习 + 异常检测 |
| 4 | COMPLETION | 模型返回 text 响应时 | LLM 判定任务是否完成 | +自定义 evaluator 插件 |
| 5 | POST-TASK | 任务结束后 | 反思→L2写入→L1提议→L3固化 | +每步可独立替换 + 插件化 |

### LayerContext 桥接器

```python
class LayerContext:
    """
    层到事件循环的统一接口。
    每层对循环完全透明 — 循环只知道调用 build_context / post_task。
    """

    def __init__(self, meta: MetaDriver, l1: Philosophy,
                 l2: FlexibleKnowledge, l3: SkillLayer):
        self.meta = meta
        self.l1 = l1
        self.l2 = l2
        self.l3 = l3

    def build_context(self, task: Task) -> str:
        """PRE-LLM: 构建注入上下文"""
        parts = []

        active_rules = self.l1.get_active_rules(task)
        if active_rules:
            parts.append(
                "[Behavioral Principles]\n" +
                "\n".join(f"- {r}" for r in active_rules)
            )

        active_cards = self.l2.get_active_cards(task.domain, task.context, top_k=5)
        if active_cards:
            parts.append(
                "[Relevant Knowledge]\n" +
                "\n".join(
                    f"- [{c.domain.path}] {c.content} "
                    f"(confidence:{c.confidence:.1f}, activation:{c.activation:.2f})"
                    for c in active_cards
                )
            )

        matching_skills = self.l3.match(task.domain)
        if matching_skills:
            parts.append(
                "[Available Skills]\n" +
                ", ".join(f"`{s.name}`" for s in matching_skills) +
                "\nUse `skill_view(name)` to load a skill's full instructions before using it."
            )

        return "\n\n".join(parts) if parts else ""

    def filter_tool_calls(self, calls: list) -> list:
        return self.meta.filter_dangerous(calls)

    def on_tool_results(self, task, results):
        self.l2.update_from_tool_results(task, results)
        self.meta.track_progress(results)

    def check_completion(self, task, messages):
        return self.meta.check_completion(task, messages)

    def post_task(self, task, messages) -> TaskResult:
        """完整学习闭环。返回 TaskResult 供外部检查。"""
        result = TaskResult()

        triggers = self.meta.evaluate_triggers(task, messages)
        if not triggers:
            return result

        for trigger in triggers:
            reflection = self.meta.run_reflection(trigger, task, messages)

            # Step 1: L2 知识更新
            if reflection.knowledge_updates:
                self.l2.apply_updates(reflection.knowledge_updates, task.domain)
                result.new_knowledge_cards = len(reflection.knowledge_updates)

            # Step 2: L1 规则提议
            if reflection.l1_proposals:
                for proposal in reflection.l1_proposals:
                    approved, reason = self.meta.validate_l1_change(
                        proposal, self.l1.all_rules()
                    )
                    if approved:
                        self.l1.apply(proposal)
                        result.l1_changes.append(
                            f"+{proposal.content[:50]}..."
                        )
                    else:
                        self.l2.add_failed_proposal_record(proposal)
                        result.l1_rejections.append(reason)

            # Step 3: L3 固化检查
            domain_cards = self.l2.get_domain_cards(task.domain)
            if self.l3.should_create_skill(task.domain, domain_cards):
                skill_meta = self.l3.propose_and_create(task.domain, domain_cards)
                if skill_meta:
                    result.new_skills.append(skill_meta.name)

        return result
```

### System Prompt 构建

```python
def _build_system_prompt(self, task: Task) -> str:
    """构建 system prompt。借鉴 Hermes 的分层结构但大幅简化。"""
    parts = []

    # ── 稳定层 (identity + tools + domain context) ──
    parts.append(
        "You are a cognitive AI agent with a layered learning architecture. "
        "You can use tools to interact with your environment, create skills "
        "from successful patterns, and refine your behavioral rules over time."
    )
    parts.append(f"Current domain: {task.domain.path}")
    parts.append(self._build_tool_guidance())

    # ── L1 注入 (行为准则) ──
    rules = self.layers.l1.all_rules()
    if rules:
        rules_text = "\n".join(f"- {r.content}" for r in rules)
        parts.append(
            f"[Behavioral Principles — Your Philosophy]\n{rules_text}\n\n"
            "These principles guide your behavior. You may propose additions "
            "or modifications through reflection after tasks."
        )

    # ── 可变层 (memory snapshot, timestamp — 暂不注入) ──
    # Phase 1 L2/L3 知识通过 build_context() 注入 user message，
    # 不放入 system prompt 以保持 prefix cache 稳定。

    return "\n\n".join(parts)
```

---

## 八、Tool 系统 (借鉴 Hermes)

### 从 Hermes 选取的组件

```
Hermes 工具                           Phase 1 需要
─────────────────────────────────────────────────────
tools/registry.py         →    复用结构 (单例 ToolRegistry)
tools/skills_tool.py      →    适配 (skills_list, skill_view)
tools/skill_manager_tool  →    适配 (create, edit, patch, delete)
tools/todo_tool.py        →    简化 (任务分解跟踪)
tools/terminal_tool.py    →    适配 (环境交互通用接口)
tools/memory_tool.py      →    暂不需要 (L4 暂缓)
tools/delegate_tool.py    →    暂不需要
tools/clarify_tool.py     →    暂不需要
```

### ToolRegistry (直接复用结构)

```python
# core/tools/registry.py — 结构借鉴 Hermes

@dataclass
class ToolEntry:
    name: str
    schema: dict           # OpenAI-compatible tool schema
    handler: Callable      # 工具实现
    check_fn: Callable     # 可用性检查
    toolset: str = "core"

class ToolRegistry:
    """线程安全单例。工具模块在 import 时自注册。"""
    _instance = None
    _lock = threading.RLock()

    def register(self, name, schema, handler,
                 check_fn=None, toolset="core"):
        """注册工具。重名且不同 toolset → 拒绝 (除非 override=True)。"""
        ...

    def get_definitions(self, requested: set[str] = None) -> list[dict]:
        """返回 OpenAI 兼容的 tool schema 列表。"""
        ...

    def dispatch(self, name: str, args: dict, context: dict) -> str:
        """执行工具。异常捕获 → JSON error。"""
        ...

    def deregister(self, name: str):
        """注销工具 (MCP 热更新预留)。"""
        ...
```

### Phase 1 工具清单

| 工具名 | 来源 | 功能 |
|--------|------|------|
| `skills_list` | 适配 Hermes | 列出所有可用技能 (metadata only) |
| `skill_view` | 适配 Hermes | 加载指定技能的完整内容 |
| `skill_manage` | 适配 Hermes | 创建/编辑/修补技能 (Agent 调用) |
| `todo` | 简化 Hermes | 创建/更新任务子步骤清单 |
| `terminal` | 适配 Hermes | 执行环境命令，捕获 stdout/stderr 返回给 Agent |

---

## 九、Agent 主类

```python
# core/agent.py

class CognitiveAgent:
    """最小 Agent 主类。聚合层 + 循环，暴露单一入口 run()。"""

    def __init__(self, config: AgentConfig):
        # 初始化顺序: 底层 → 高层
        self.tool_registry = ToolRegistry()
        self._register_core_tools()

        self.l3 = SkillLayer(config.skills_dir, self.tool_registry)
        self.l2 = FlexibleKnowledge(config.l2_knowledge_dir, config.l2_index_path)
        self.l1 = Philosophy(
            config.l1_rules_path,
            max_rules=config.l1_max_rules,
            max_rule_length=config.l1_max_rule_length,
        )

        self.meta = MetaDriver(
            triggers=DEFAULT_TRIGGERS,         # 硬编码
            validation_rules=DEFAULT_VALIDATORS,  # 硬编码
            auxiliary_llm=config.auxiliary_llm,
        )

        self.layers = LayerContext(self.meta, self.l1, self.l2, self.l3)

        self.loop = AgentLoop(
            llm_client=config.main_llm,
            tool_registry=self.tool_registry,
            layers=self.layers,
            max_iterations=config.max_iterations,
        )

        # 种子数据注入
        self._bootstrap(config)

    def run(self, user_input: str, domain: Domain = None) -> TaskResult:
        task = Task(
            description=user_input,
            domain=domain or Domain("general", "general"),
        )
        return self.loop.run(task)

    # ── 管理接口 ──
    def inspect_l1(self) -> list: ...
    def inspect_l2(self, domain: Domain) -> list: ...
    def inspect_l3(self) -> list: ...
    def force_create_skill(self, domain: Domain): ...
```

---

## 十、配置系统

```python
@dataclass
class AgentConfig:
    """
    三层可改性:
      HARDCODED — 写死在代码里 (L0.5 逻辑)
      USER      — 用户通过此 config 配置
      RUNTIME   — Agent 运行时修改 (L1/L2/L3)
    """

    # ── USER: LLM ──
    main_llm: LLMClient
    auxiliary_llm: LLMClient     # L0.5 判定用，建议 flash 级轻量模型

    # ── USER: 路径 ──
    skills_dir: Path = Path("./skills")
    l1_rules_path: Path = Path("./data/l1_rules.json")
    l2_knowledge_dir: Path = Path("./knowledge")
    l2_index_path: Path = Path("./knowledge/l2_index.json")

    # ── USER: 容量 ──
    max_iterations: int = 50
    l1_max_rules: int = 20
    l1_max_rule_length: int = 100

    # ── USER: 种子数据 ──
    seed_l1_rules: list[str] | None = None
    seed_l2_cards: list[dict] | None = None
    seed_l3_skills: list[Path] | None = None

    # ── HARDCODED (不在 config 中，在 meta_driver.py) ──
    # - 触发器和冷却时间
    # - 校验规则
    # - L3 固化阈值 (3 cards, 0.7 avg activation)
```

### 启动流程

```python
def bootstrap(config_path: str) -> CognitiveAgent:
    config = load_config(config_path)
    agent = CognitiveAgent(config)
    # 种子数据已通过 _bootstrap() 注入
    return agent

# config.yaml 示例:
# main_llm:
#   provider: openrouter
#   model: anthropic/claude-sonnet-4-20250514
# auxiliary_llm:
#   provider: openrouter
#   model: google/gemini-flash-2.0
# seed_l1_rules:
#   - "面对不确定信息时优先搜索验证，不要直接假设答案"
#   - "当同一种方法连续3次失败时，主动换策略而非坚持"
# max_iterations: 50
```

---

## 十一、项目文件结构

```
cognitive-agent/
├── main.py                          # 入口: bootstrap() + run()
├── config.yaml                      # 用户配置
├── pyproject.toml                   # 项目元数据
│
├── core/
│   ├── __init__.py
│   ├── agent.py                     # CognitiveAgent 主类 (~100行)
│   ├── agent_loop.py                # 事件循环 (~180行)
│   ├── config.py                    # AgentConfig (~40行)
│   ├── layer_context.py             # LayerContext 桥接器 (~120行)
│   ├── task.py                      # Task / TaskResult / TaskContext 定义
│   │
│   ├── meta_driver.py               # L0.5: 触发器 + 校验器 + 反思 (~150行)
│   ├── philosophy.py                # L1: 规则 CRUD + active filter (~100行)
│   ├── flexible_knowledge.py        # L2: KnowledgeCard + activation + DB (~200行)
│   ├── skill_layer.py               # L3: 匹配 + 固化 + CRUD (~200行)
│   │
│   └── tools/
│       ├── __init__.py
│       ├── registry.py              # ToolRegistry (借 Hermes 结构, ~80行)
│       ├── skills_tool.py           # skills_list + skill_view (适配, ~80行)
│       ├── skill_manager.py         # skill_manage: create/edit/patch (~120行)
│       ├── todo_tool.py             # 任务子步骤跟踪 (简化, ~50行)
│       └── terminal_tool.py         # 环境交互接口 (~60行)
│
├── data/
│   └── l1_rules.json                # L1 规则持久化
│
├── knowledge/                        # ★ L2 知识存储 (MD + JSON)
│   ├── general/                      # 通用知识
│   │   └── *.md
│   ├── textworld/                    # 领域知识 (按 domain 分目录)
│   │   └── *.md
│   └── l2_index.json                # JSON 索引 (自动维护) + Graph 运行时构建
│
├── skills/                          # L3 技能文件 (agentskills.io 格式)
│   ├── general/
│   │   └── task-decomposition/
│   │       └── SKILL.md
│   └── (domain-specific skills)
│
└── tests/
    ├── __init__.py
    ├── test_meta_driver.py
    ├── test_philosophy.py
    ├── test_flexible_knowledge.py
    ├── test_skill_layer.py
    ├── test_layer_context.py
    ├── test_agent_loop.py
    └── test_agent.py
```

---

## 十二、代码量估算

| 模块 | 来源 | 行数 |
|------|------|------|
| agent.py | 自建 | ~100 |
| agent_loop.py | 提取 Hermes 结构 | ~180 |
| config.py | 自建 | ~40 |
| layer_context.py | 自建 | ~120 |
| task.py | 自建 | ~40 |
| meta_driver.py | 自建 | ~150 |
| philosophy.py | 自建 | ~100 |
| flexible_knowledge.py | 自建 | ~200 |
| skill_layer.py | 借 Hermes + 新增 | ~200 |
| tools/*.py (5 files) | 借 Hermes 结构 + 适配 | ~390 |
| main.py | 自建 | ~40 |
| **Total** | | **~1,560** |

---

## 十三、扩展点清单

每个扩展点都是预留接口，当前有默认实现，未来可替换或增强。

| # | 扩展点 | 位置 | 当前实现 | 可替换方向 |
|----|--------|------|---------|-----------|
| 1 | L0.5 触发器 | `MetaDriver.evaluate_triggers()` | 4 个硬编码触发器 | 用户自定义触发器 |
| 2 | L0.5 校验规则 | `MetaDriver.validate_l1_change()` | 5 个硬编码校验 | 新增校验维度 |
| 3 | L0.5 反思执行 | `MetaDriver.run_reflection()` | LLM 子 Agent 执行 | 结构化反思模板 |
| 4 | L1 规则过滤 | `Philosophy.get_active_rules()` | 全部返回 | 按 domain/场景 选择性激活 |
| 5 | L2 激活算法 | `KnowledgeCard.compute_activation()` | tag-match + recency | Spreading activation, GNN |
| 6 | L2 衰减模型 | `FlexibleKnowledge.run_decay_cycle()` | 指数衰减 | Ebbinghaus 遗忘曲线 |
| 7 | L2 存储后端 | `FlexibleKnowledge.__init__()` | MD + JSON index + Graph runtime | 向量 DB, 图 DB |
| 8 | L3 固化判定 | `SkillLayer.should_create_skill()` | 3 cards + 0.7 activation | LLM 判定, 人工审批 |
| 9 | L3 编译 | `SkillLayer.propose_skill()` | LLM 生成 SKILL.md | 模板引擎, code generation |
| 10 | Tool 发现 | `ToolRegistry.register()` | 手动注册 | 自动扫描 + AST 解析 |
| 11 | Tool 执行 | `AgentLoop.run()` | 顺序 dispatch | 并发执行 (借 Hermes) |
| 12 | 任务完成判定 | `MetaDriver.check_completion()` | LLM 判定 | 自定义 evaluator 插件 |
| 13 | PRE-LLM context | `LayerContext.build_context()` | L1+L2+L3 | +L4 多索引 + RAG |
| 14 | Domain 体系 | `Domain` | 字符串路径层次 | URI/IRI, 本体论 |

---

## 十四、与 Hermes 的差异对照

| | Hermes | 本架构 |
|----|--------|--------|
| 元驱动 | Curator (janitor, 可暂停) | **L0.5 (immutable driver)** |
| 行为准则 | 静态 SOUL.md + System Prompt | **L1 可演化规则 + L0.5 审批** |
| 知识组织 | 平面 MEMORY.md + Honcho | **L2 Domain 分层 + 激活衰减** |
| 技能创建 | Agent 自主决定 | **L2 模式激活 → L0.5 触发 → L3 固化** |
| 失败处理 | retry/fallback，不归因 | **分层归因: 归因到具体层** |
| 学习循环 | 记忆持久化 | **L4→L2→L3 层次化知识固化** |
| 事件循环 | 3900行，生产级 | ~180行，验证级 (借结构不借代码) |
| 配置可改性 | 几乎全部可配置 | 三层分离: HARDCODED/USER/RUNTIME |
| Tool 系统 | 60+ 工具，自动发现 | 5 个最小工具，手动注册 |

---

*待后续细化: Phase 1 具体环境适配层 (TextWorld connector)、evaluator 插件定义。*
