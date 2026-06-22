# 次工具系统 — 设计规格

> 日期：2026-06-22 |
> 状态：设计完成，待实现

## 动机

1. **LLM 工具选择精度**：主工具数量需严格控制在 50 以内，避免 Agent 选错工具或 prompt 过长
2. **场景隔离**：某些工具只在特定场景下有意义（如 DouZero 专用工具），不应跨场景可见

## 核心决策

| 决策 | 结论 | 理由 |
|------|------|------|
| 注入粒度 | session 级（thread-local） | 与现有 AgentContext 模式一致；切换场景时重建 env 自然清零 |
| 层可见性 | 不区分 L1/L2/L3 | 次工具对所有层平等可见，由 Agent prompt 和场景语义自然约束 |
| 组织方式 | 单一工具池 + `semantic_description` 字段 | 不做 domain 树绑定，LLM subagent 筛选 |
| 检索机制 | LLM subagent 纯文本筛选 | tool description 不是自然语言，embedding 语义鸿沟大；几百条元数据 LLM context 完全装得下 |
| 触发方式 | Agent 通过 `activate_secondary_tools` 工具主动调用 | session 可能漂移，Agent 按需自主发现 |
| allowlist 策略 | 次工具写入 `tools.yaml`，和主工具同格式 | 复用现有 allowlist 过滤链路，减少新机制 |

---

## 架构

```
Agent tool loop (_call_llm)
       │
       ▼
ToolRegistry.get_definitions(requested=allowlist)
       │
       ├── tool_spec="primary"  → 照常返回（受 allowlist 控制）
       │
       └── tool_spec="secondary"→ name in _enabled_secondary(thread-local) 才返回
                                   │
                                   └── activate_secondary_tools 工具负责填充
```

次工具全部预注册在 `ToolRegistry._entries` 中，默认不可见。`get_definitions()` 通过 `tool_spec` 字段 + thread-local `_enabled_secondary` 做确定性过滤。

不影响 `ToolCapability`、`LayerInjector`、`AgentContext`、`tools.yaml` 的现有逻辑。

---

## 数据结构

### ToolEntry（扩展）

```python
@dataclass
class ToolEntry:
    name: str
    schema: dict
    handler: Callable
    tool_spec: str = "primary"          # "primary" | "secondary"
    semantic_description: str = ""       # 次工具供 LLM 筛选的自然语言描述
    sync: bool = True
    force_sync: bool = False
    check_fn: Callable | None = None
    toolset: str = "core"
    # available_domains — 删除（零生产消费）
```

### ToolRegistry（变更）

新增：
- `_enabled_secondary = threading.local()` — 每个线程独立维护已启用的次工具名集合
  - 惰性初始化：首次访问时自动填充空 `set()`（`getattr(thread_local, "attr", set())`）
- `_get_enabled_secondary() -> set[str]` — 内部 helper，返回当前线程的已启用集合
- `enable_secondary(names: list[str]) -> int` — 将次工具名加入当前线程的已启用集合，返回成功添加数
- `clear_secondary() -> None` — 清空当前线程的已启用集合（Gradio 线程复用时显式调用）

修改：
- `get_definitions(requested=None) -> list[dict]` — 追加过滤：`tool_spec="secondary"` 且 name 不在 `_enabled_secondary` 中时跳过

删除：
- `ToolEntry.available_domains` 字段
- `register()` 方法的 `available_domains` 参数
- `register()` 方法中 DomainRegistry 索引逻辑（`index_item("tool", domain, name)` 循环段）
- `get_tools_for_domain()` 方法

---

## 新工具：`activate_secondary_tools`

### Schema

```json
{
  "type": "function",
  "function": {
    "name": "activate_secondary_tools",
    "description": "搜索并激活可用的次级工具。用自然语言描述需求，系统会匹配并启用合适的次工具。激活后的工具在当前 session 内对所有层可见。",
    "parameters": {
      "type": "object",
      "properties": {
        "query": {
          "type": "string",
          "description": "用自然语言描述你需要什么功能的工具"
        },
        "top_k": {
          "type": "integer",
          "description": "最多激活 N 个工具，默认 10",
          "default": 10
        }
      },
      "required": ["query"]
    }
  }
}
```

注册为 `tool_spec="primary"`，对所有层可见。

### Handler 流程

1. 从 `ToolRegistry._entries` 收集所有 `tool_spec="secondary"` 的条目
2. 提取 `{name, semantic_description}` 构建候选索引
3. 构造 LLM prompt：`[候选工具索引] + [Agent 查询: query]`，要求以 `{tools: [{name, reason}, ...]}` JSON 格式返回匹配结果
4. 对匹配到的 name 做存在性校验
5. 调用 `self.enable_secondary(matched_names)` 注入当前线程
6. 返回 `{enabled: [...], total_candidates: N}`

### Subagent Prompt 模板

```
你是一个工具匹配系统。以下是可以用的次级工具列表：

{工具索引：每行 "name: semantic_description"}

用户需要以下功能的工具：
"{query}"

请从上面的列表中选出最匹配的工具（最多 {top_k} 个），以 JSON 格式返回。
如果所有工具都不匹配，返回空列表。

输出格式：
{"tools": [{"name": "tool_name", "reason": "为什么匹配"}]}
```

---

## 删除清单

| 删除项 | 文件 | 原因 |
|--------|------|------|
| `available_domains` 字段 | `core/tools/registry.py` ToolEntry | 零生产消费 |
| `available_domains` 参数 + 默认值逻辑 | `core/tools/registry.py` register() | 同上 |
| DomainRegistry 索引块 (`index_item("tool", ...)`) | `core/tools/registry.py` register() | 同上 |
| `get_tools_for_domain()` 方法 | `core/tools/registry.py` | 仅测试用到，生产零调用 |
| `test_tool_domain_filtering` 测试 | `tests/test_tool_registry.py` | 对应功能删除 |
| 整个文件 | `core/tools/domain_tool.py` | 写入的 `_registry` 全局变量无消费者 |
| `set_domain_registry()` 调用 block | `core/chain_factory.py:77-81` | 同上 |
| `from domain_tool import set_domain_registry` | `core/tools/__init__.py:17` | 同上 |

---

## 不变的部分

- `config/tools.yaml` — 次工具加条目即可，格式和主工具一致，按层配置 allowlist
- `ToolCapability` / `LayerInjector` / `AgentContext` / `register_all_tools` — 不动
- `LayerAgent._call_llm` / `_get_tools` / `decide` — 不动
- 现有主工具的注册代码 — 不动

---

## 次工具注册示例

```python
# 注册方式与主工具一致，仅 tool_spec 不同
registry.register(
    "douzero_encode_hand",
    {"type": "function", "function": {
        "name": "douzero_encode_hand",
        "description": "Encode hand cards into DouZero model input format",
        "parameters": {...}
    }},
    _douzero_encode_handler,
    tool_spec="secondary",
    semantic_description="当 Agent 需要在斗地主对局中将手牌转换为 DouZero 模型可处理的向量格式时使用。输入卡牌列表，输出编码后的 numpy 数组。仅在 douzero 游戏场景中有意义。",
    sync=True,
    toolset="secondary",
)
```

### tools.yaml 对应条目

```yaml
douzero_encode_hand:
  sync: true
  timeout: 5
  allowlist: [l1, l2, l3]
```

---

## session 生命周期

```
Session 创建
  └─ ToolRegistry._enabled_secondary = {} (thread-local 自动初始化)

Agent 调用 activate_secondary_tools("我需要斗地主工具")
  └─ LLM subagent 筛选
  └─ enable_secondary(["douzero_encode_hand", "douzero_eval"])
  └─ _enabled_secondary = {"douzero_encode_hand", "douzero_eval"}

后续 _call_llm → get_definitions()
  └─ 主工具全部可见 + 已启用的次工具可见

Session 结束
  ├─ CLI 模式：线程终止 → thread-local 随线程消亡自动清零
  └─ Gradio 模式：线程复用 → 在 SessionState 重建/切换时调用 clear_secondary()
```
