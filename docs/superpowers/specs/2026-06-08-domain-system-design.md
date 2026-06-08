# Domain System Redesign

> 状态: 设计完成，待用户审阅
> 日期: 2026-06-08

## 动机

当前 domain 系统存在以下问题：

1. **硬编码散落**: 8 个 domain 字符串分布在 8 个文件中，`L2_DOMAIN_NODES` 是唯一的伪注册表（4 条）
2. **L3/Capability 无 domain 感知**: L3 只用 `obs.session.domain` 做简单匹配，capability/tool 完全没有 domain 过滤
3. **无层级**: `Domain` 类只有 `path` + 几乎不用的 `level` 字段，无法表达 `coding → coding/python` 这种关系
4. **无自优化**: domain 关系无法随 agent 使用经验而演化

## 设计目标

1. 统一的 domain registry，所有层和工具通过同一入口查询
2. 支持 2-3 级层级（`coding/python`），通过 parent + correlations 表达
3. 每个知识条目/skill/tool 用 `available_domains` 字段声明适用范围
4. Agent 通过 execute-reflect-expand 循环自主发现和优化跨域关系
5. consolidation 阶段可创建新 domain、更新已有 domain 关系和条目归属

---

## 数据模型

### DomainNode

持久化文件: `data/layers/domain_registry.json`

```python
@dataclass
class DomainNode:
    path: str                       # "game/leduc", "coding/python"
    parent: str | None              # 单父节点，root 为 None
    description: str                 # 这个 domain 本身是什么（本体描述）
    correlations: dict[str, float]  # {neighbor_path: weight}，横向关联权重
    relations: str                  # 自然语言：姊妹域、上下游任务等非常规关系
```

内存中 children 从 parent 反向推导，不显式存储，避免一致性问题。

### 统一字段: available_domains

所有可检索实体统一用 `available_domains: list[str]` 替代旧的单一 `domain` 字段：

| 实体 | 旧字段 | 新字段 |
|------|--------|--------|
| KnowledgeCard | `domain: Domain` | `available_domains: list[str]` |
| SkillMeta | `domain: Domain` + `cross_domain: bool` | `available_domains: list[str]` |
| ToolDefinition | (无) | `available_domains: list[str]` |

"跨域" 不再是特殊标记，而是 `available_domains` 有多个值即可。

### 持久化格式

```json
{
  "nodes": {
    "general": {
      "parent": null,
      "description": "通用领域，跨域知识的默认归属",
      "correlations": {},
      "relations": ""
    },
    "game": {
      "parent": "general",
      "description": "游戏策略领域的根节点，涵盖各类对抗性游戏的决策知识",
      "correlations": {"learning/reflect": 0.2},
      "relations": "子域: game/leduc, game/doudizhu"
    },
    "game/leduc": {
      "parent": "game",
      "description": "Leduc Hold'em 简化德州扑克，2 人对局，K/Q/J 各两种花色，翻牌前/翻牌后两轮下注",
      "correlations": {"game/doudizhu": 0.6},
      "relations": "姊妹域: game/doudizhu（同为扑克类游戏，部分策略可迁移）"
    },
    "game/doudizhu": {
      "parent": "game",
      "description": "斗地主 3 人卡牌游戏，54 张牌含大小王，1 地主 vs 2 农民",
      "correlations": {"game/leduc": 0.6},
      "relations": "姊妹域: game/leduc（扑克类，顶牌/炸弹等策略部分互通）"
    },
    "coding": {
      "parent": "general",
      "description": "通用编程领域，涵盖软件开发的方法论和工具使用",
      "correlations": {"learning/reflect": 0.3},
      "relations": "子域: coding/python, coding/web"
    },
    "coding/python": {
      "parent": "coding",
      "description": "Python 编程子域，CPython 生态、类型系统、async/await、包管理",
      "correlations": {"coding": 0.9},
      "relations": "父域: coding。姊妹域: coding/web"
    },
    "learning/reflect": {
      "parent": "general",
      "description": "学习反思域，消费执行记录分析策略问题和改进机会",
      "correlations": {},
      "relations": "子域: learning/compile, learning/consolidate"
    },
    "learning/compile": {
      "parent": "learning/reflect",
      "description": "知识编译域，将高激活同域卡片编译为 L3 技能",
      "correlations": {"learning/consolidate": 0.8},
      "relations": "姊妹域: learning/consolidate"
    },
    "learning/consolidate": {
      "parent": "learning/reflect",
      "description": "知识整理域，管理知识库容量：合并相似条目、归档低活跃内容",
      "correlations": {"learning/compile": 0.8},
      "relations": "姊妹域: learning/compile。与 learning/compile 配合：compile 产出技能，consolidate 整理冗余"
    }
  },
  "reverse_index": {
    "l2": {
      "game/leduc": ["card_ac56cc3e", "card_ebf37687"],
      "game/doudizhu": ["card_790dd04b", "card_b0dbad33"],
      "learning/consolidate": ["card_f19d09db", "card_a9f35675"]
    },
    "l3": {
      "game/leduc": ["leduc-preflop-raise", "leduc-postflop-pair"],
      "game/doudizhu": ["doudizhu-top-card"],
      "learning/compile": ["learning-compile-skill"],
      "learning/reflect": ["learning-reflect-analyze"]
    },
    "tool": {
      "general": ["web_search", "terminal"],
      "game/leduc": ["poker_odds_calculator"]
    }
  }
}
```

---

## DomainRegistry API

```python
class DomainRegistry:
    # ── 查询 ──
    def get_node(path: str) -> DomainNode | None
    def list_all() -> list[DomainNode]
    def children_of(path: str) -> list[DomainNode]     # 从 parent 反向推导

    # ── 双路召回 ──
    def get_primary_items(layer: str, domain: str) -> list[str]
        # available_domains 包含 domain 的 items

    def get_explore_items(layer: str, domain: str,
                          threshold: float = 0.5) -> list[str]
        # correlations > threshold 的邻近 domain 的 items

    def get_items_for_domains(layer: str, domains: list[str]) -> list[str]
        # 多 domain 联合查询，去重

    # ── 索引管理 ──
    def index_item(layer: str, domain: str, item_id: str)
    def unindex_item(layer: str, domain: str, item_id: str)
    def update_item_domains(layer: str, item_id: str,
                            domains: list[str])            # 批量替换

    # ── 图管理 ──
    def add_node(path: str, parent: str | None,
                 description: str, correlations: dict,
                 relations: str) -> DomainNode
    def update_correlation(a: str, b: str, weight: float)
    def update_node(path: str, **fields)

    # ── 持久化 ──
    def save()                                                 # 原子写入 JSON
    @classmethod
    def load(registry_path: Path) -> DomainRegistry
```

---

## 层间交互

### L1 (L0_5_1): Domain 节点选择

L1Agent.stage1 中，将 `DomainRegistry.list_all()` 的节点列表注入 system prompt（替代当前的 `L2_DOMAIN_NODES` 硬编码列表）：

```python
nodes = registry.list_all()
nodes_text = "\n".join(
    f"{i+1}. {n.path}\n   {n.description}"
    for i, n in enumerate(nodes)
)
```

LLM 仍然打分选相关节点，但节点来源从硬编码常量变为 registry 动态查询。

### L2: 双路 domain 召回

```python
# Primary: 精确匹配
primary_ids = registry.get_primary_items("l2", task_domain)

# Exploration: 邻近 domain
explore_ids = registry.get_explore_items("l2", task_domain, threshold=0.5)
```

L2Manager 合并两路结果，传给 L2Agent 做语义筛选。

### L3: Domain 感知的技能匹配

```python
# 替代当前的 skill_layer.match(domain)
primary_skills = registry.get_primary_items("l3", task_domain)
matched = skill_layer.get_skills_by_ids(primary_skills)
```

去掉 `SkillLayer.match()` 中的路径前缀匹配逻辑，改为调用 registry 反向索引。

### Tool: Domain 过滤

ToolRegistry 新增 domain 感知查询：

```python
def get_tools_for_domain(domain: str) -> list[ToolDefinition]:
    tool_ids = registry.get_primary_items("tool", domain)
    return [t for t in self._tools if t.name in tool_ids]
```

---

## Execute-Reflect-Expand 循环

```
┌──────────────────────────────────────────┐
│  Agent 执行任务 (session.domain)           │
│  ┌──────────────────────────────────────┐ │
│  │ PRIMARY: 当前 domain 的 items         │ │
│  │ cards + skills + tools              │ │
│  └──────────────────────────────────────┘ │
│              ↓                            │
│  ┌──────────────────────────────────────┐ │
│  │ REFLECT: 结果评估                     │ │
│  │ 信息充足？任务完成？                   │ │
│  └──────────────────────────────────────┘ │
│       ↓ 不够                  ↓ 够了      │
│  ┌────────────────┐         ┌──────────┐ │
│  │ EXPAND: 追加    │         │  DONE    │ │
│  │ explore items  │         └──────────┘ │
│  │ (corr > threshold)                    │ │
│  └────────────────┘                     │ │
│       ↓                                 │ │
│  ┌────────────────┐                     │ │
│  │ RE-EXECUTE     │                     │ │
│  │ primary + explore items              │ │
│  └────────────────┘                     │ │
│       ↓ (loop back to REFLECT)           │ │
└──────────────────────────────────────────┘
```

以上为 design skeleton。Greedy-explore balance 和 Expand 决策阈值细节后续在 implementation plan 中细化。

> **与 Agent while 循环的合并**：当前 L1 已有 `MAX_LOOPS` 机制（line 29, `l0_5_1/manager.py`），Expand 循环不是新增独立循环，而是在现有 V-structure 循环内扩展：L1 的某次 loop 中如果 REFLECT 判定信息不足，下一轮 stage1 传入更广的 domain 列表（primary → primary + explore），L2/L3 自然也获得更多 items。循环退出条件不变（L1 判定 done 或达到 MAX_LOOPS）。

---

## 自优化：跨域归属学习

场景: `game/doudizhu` 的 tool `poker_odds_calculator` 在 `game/leduc` 任务中被 Expand 发现有用。

Consolidation 时 Agent 输出：

```
@modify layer=tool type=update target=poker_odds_calculator
       available_domains=["game/doudizhu", "game/leduc"]
       reason="used in leduc task via expand, calculation logic applies to both"
```

LearningEnv 调用 `registry.update_item_domains("tool", "poker_odds_calculator", [...])` 更新。

长此以往，频繁跨域使用的 tool 和 skill 会自然获得更广的 `available_domains`，correlation 权重也可以基于跨域引用频次调整。

---

## 迁移计划

### Phase 1: DomainRegistry 核心 + 层间接入（本次实现）

1. 新建 `data/layers/domain_registry.json`（初始节点同当前硬编码值）
2. 新建 `core/domain_registry.py`（DomainRegistry 类 + DomainNode dataclass）
3. 废弃 `core/task.py` 中 Domain 的 `level` 字段（保留 path 兼容过渡）
4. 修改 `core/seed_knowledge.py`：初始化 registry 节点 + 索引 seed items
5. 给 KnowledgeCard / SkillMeta / ToolDefinition 加 `available_domains` 字段，同步维护 `reverse_index`
6. L1: `L2_DOMAIN_NODES` → `registry.list_all()`
7. L2: 双路召回（primary + explore）
8. L3: 技能匹配改为 registry 反向索引
9. Tool: 新增 domain 过滤

### Phase 2: 自优化与 Expand 循环

1. LearningEnv consolidation 支持 domain 节点增改
2. Execute-Reflect-Expand 循环实现
3. 跨域归属自动学习

---

## 待决定（留到 implementation plan）

- Greedy-explore balance 的具体阈值和策略
- Expand 循环的最大迭代次数
- `available_domains` 迁移策略：旧 `domain: Domain` 字段何时完全移除
- DomainNode.description 和 relations 的长度限制
- 初始 registry 中 correlation 权重的具体值
