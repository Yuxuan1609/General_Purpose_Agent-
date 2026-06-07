# Capability System Design

## 设计背景

当前架构中 Tool 和 Knowledge 处于两个困境：

1. **Tool**：`ToolRegistry`（`core/tools/registry.py`）已实现注册/分发/过滤，但仅用于旧 `_archive/` 路径。新 Executor + Layers 链未挂载——Agent 层无法调用工具。
2. **Knowledge**：原计划作为 L4 独立层（L3 dispatch 目标），但静态知识不需要 Manager/Agent/Comm 全套。所有层都可能需要查静态知识，L4 作为单独层反而违反 A3。
3. **整理（Consolidation）**：`LearningEnv.build_consolidation_task()` 已有骨架，但触发机制缺失，容量监测未集成。

三者共享同一模式——**可被层消费的能力 + 访问控制 + 生命周期管理**。本设计用一个薄抽象层统一三者接口，各自实现独立，留好未来合并的空间。

## 核心概念

### Capability = 可被任意层通过 LayerAgent 调用的能力

Tool 和 Knowledge 是 Capability 的两种子类型。Capability ABC 定义的接口不是"访问控制"（那在各子类内部），而是**统一的注册/发现/调用/回流**路径。

```
                    CapabilityRegistry
                   /        |        \
          ToolCapability  KnowledgeCapability  (future: SkillCapability, ...)
                   \        |        /
                    LayerInjector
                   /        |        \
              L1Agent    L2Agent    L3Agent
```

## 设计

### 1. Capability ABC + CapabilityRegistry

```python
# capability/__init__.py

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

@dataclass(frozen=True)
class CapabilityResult:
    """能力调用结果 —— 统一回流格式"""
    capability_name: str
    layer: str
    success: bool
    data: Any                    # 成功时的返回数据
    error: str = ""              # 失败时的错误信息
    metadata: dict = field(default_factory=dict)

class Capability(ABC):
    """可被认知层调用的能力抽象。

    子类自行管理访问控制（哪些层可见、可见哪些子项）。
    Capability ABC 只定义统一的注册/发现/调用接口。
    """

    name: str

    @abstractmethod
    def get_schema(self) -> dict:
        """返回 OpenAI function-calling 兼容的 JSON schema，
        注入到 LLM tools/functions 参数中。"""

    @abstractmethod
    def invoke(self, layer: str, args: dict) -> CapabilityResult:
        """执行调用。

        Args:
            layer: 调用方层级标识（"l1"/"l2"/"l3"），
                   子类内部据此做访问控制判断。
            args: 工具参数（函数参数 JSON）

        Returns:
            CapabilityResult: 统一的调用结果，成功/失败/错误信息。
        """

    @abstractmethod
    def is_visible_to(self, layer: str) -> bool:
        """该层是否可以看见此能力（决定 schema 是否注入到该层 prompt）"""
```

```python
class CapabilityRegistry:
    """统一的能力注册与分发中心。

    替代将来可能的多套注册表（ToolRegistry / KnowledgeRegistry / ...）。
    当前 ToolRegistry 保留不动，通过 ToolCapability 包装接入。
    """

    def __init__(self):
        self._capabilities: dict[str, Capability] = {}

    def register(self, cap: Capability) -> None: ...
    def get_schemas_for_layer(self, layer: str) -> list[dict]: ...
    def invoke(self, name: str, layer: str, args: dict) -> CapabilityResult: ...
    def list_for_layer(self, layer: str) -> list[str]: ...
```

### 2. ToolCapability

包装现有 `ToolRegistry`，加上层可见性控制。

```python
# capability/tool_capability.py

class ToolCapability(Capability):
    """将 ToolRegistry 中的工具包装为一个 Capability。

    访问控制粒度：toolset 级别 + 单个 tool 级别。
    层可见性由构造时的 allowlist 决定。

    示例配置：
        allowlist = {
            "l1": {"todo"},
            "l2": {"todo", "terminal"},
            "l3": {"todo", "terminal", "web_search", "skills_list", "skill_view"},
        }
    """

    name = "tool"

    def __init__(self, registry: ToolRegistry, allowlist: dict[str, set[str]]):
        self._registry = registry
        self._allowlist = allowlist

    def is_visible_to(self, layer: str) -> bool:
        return layer in self._allowlist and len(self._allowlist[layer]) > 0

    def get_schema(self) -> dict:
        # 返回一个 "tool_call" 的 meta-schema，实际 tool 列表在 invoke 时解析
        ...

    def invoke(self, layer: str, args: dict) -> CapabilityResult:
        tool_name = args["name"]
        if tool_name not in self._allowlist.get(layer, set()):
            return CapabilityResult(
                capability_name="tool", layer=layer, success=False,
                error=f"Tool '{tool_name}' not allowed for layer '{layer}'"
            )
        try:
            result_json = self._registry.dispatch(tool_name, args.get("args", {}))
            return CapabilityResult(
                capability_name="tool", layer=layer, success=True,
                data=json.loads(result_json)
            )
        except Exception as e:
            return CapabilityResult(
                capability_name="tool", layer=layer, success=False, error=str(e)
            )
```

**附带的具体 Tool 示例（从现有工具库选取，加新增工具）：**

| 工具名 | 来源 | 层可见 | 功能 |
|--------|------|--------|------|
| `todo` | 现有 `core/tools/todo_tool.py` | L1, L2, L3 | 子任务跟踪 |
| `terminal` | 现有 `core/tools/terminal_tool.py` | L2, L3 | 执行 Shell 命令，30s 超时 |
| `web_search` | 现有 `core/tools/web_search_tool.py` | L3 | DuckDuckGo 搜索，无需 API Key |
| `read_file` | 新增，受 Hermes style 启发 | L2, L3 | 读取文件内容（指定 offset/limit） |
| `write_file` | 新增 | L3（需 APPROVAL） | 写入文件（原子写入 tempfile+replace） |
| `grep` | 新增，受 Hermes style 启发 | L2, L3 | 正则搜索文件内容，返回匹配行+行号 |
| `skills_list/view/manage` | 现有 `core/skill_layer.py` | L3 | 技能管理 |

新增工具的 schema 示例（OpenAI function-calling 格式）：

```python
# read_file 工具 schema
{
    "type": "function",
    "function": {
        "name": "read_file",
        "description": "Read content from a file with optional offset and line limit",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Absolute path to the file"},
                "offset": {"type": "integer", "description": "Start line (1-indexed, default 1)"},
                "limit": {"type": "integer", "description": "Max lines to read (default 200)"}
            },
            "required": ["path"]
        }
    }
}

# grep 工具 schema
{
    "type": "function",
    "function": {
        "name": "grep",
        "description": "Search file contents with regex and return matching lines",
        "parameters": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Regex pattern to search for"},
                "path": {"type": "string", "description": "Directory to search in (default: workspace root)"},
                "include": {"type": "string", "description": "File glob pattern to filter (e.g. '*.py')"}
            },
            "required": ["pattern"]
        }
    }
}
```

### 3. KnowledgeCapability

静态知识的存储和查询。独立于 L2 FlexibleKnowledge——L2 是动态经验，Knowledge 是静态参考。

```python
# capability/knowledge_capability.py

class BaseKnowledgeStore(ABC):
    """静态知识存储的抽象。

    实现可以是内存 dict、JSON 文件、vector DB、Elasticsearch 等。
    """

    @abstractmethod
    def search(self, query: str, top_k: int = 5) -> list[dict]:
        """语义/关键词搜索，返回 {id, content, metadata, score} 列表"""

    @abstractmethod
    def get(self, doc_id: str) -> dict | None:
        """按 ID 精确获取"""

    @abstractmethod
    def add(self, doc_id: str, content: str, metadata: dict | None = None) -> None:
        """添加文档"""

    @abstractmethod
    def remove(self, doc_id: str) -> bool:
        """删除文档（返回是否成功）"""

    @abstractmethod
    def list_ids(self) -> list[str]:
        """列出所有文档 ID"""

class InMemoryKnowledgeStore(BaseKnowledgeStore):
    """Phase 3 初始实现：内存 dict + 简单关键词匹配。

    未来可替换为 ChromaDB / FAISS / Elasticsearch 等。
    """
    def __init__(self):
        self._docs: dict[str, dict] = {}

    def search(self, query: str, top_k: int = 5) -> list[dict]:
        # 简单关键词匹配：query 中的词在 content 中出现的次数
        keywords = query.lower().split()
        scored = []
        for doc_id, doc in self._docs.items():
            content_lower = doc["content"].lower()
            score = sum(1 for kw in keywords if kw in content_lower)
            if score > 0:
                scored.append({**doc, "score": score})
        scored.sort(key=lambda d: d["score"], reverse=True)
        return scored[:top_k]
    ...
```

```python
class KnowledgeCapability(Capability):
    """将 KnowledgeStore 包装为 Capability。

    访问控制粒度：store 级别。
    每个 KnowledgeStore 实例可配置不同的层可见性。

    示例配置：
        stores = {
            "game_rules": (store_large, {"l1", "l2", "l3"}),
            "api_docs":   (store_small, {"l3"}),
            "design_docs":(store_design, {"l1", "l2"}),
        }
    """

    name = "knowledge"

    def __init__(self, stores: dict[str, tuple[BaseKnowledgeStore, set[str]]]):
        self._stores = stores  # name → (store, visible_layers)

    def is_visible_to(self, layer: str) -> bool:
        return any(layer in layers for _, layers in self._stores.values())

    def get_schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": "knowledge_query",
                "description": "Query static knowledge stores for reference information",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "store": {
                            "type": "string",
                            "description": "Knowledge store to query",
                            "enum": list(self._stores.keys())
                        },
                        "query": {
                            "type": "string",
                            "description": "Search query"
                        },
                        "top_k": {
                            "type": "integer",
                            "description": "Max results (default 5)"
                        }
                    },
                    "required": ["store", "query"]
                }
            }
        }

    def invoke(self, layer: str, args: dict) -> CapabilityResult:
        store_name = args["store"]
        if store_name not in self._stores:
            return CapabilityResult(name="knowledge", layer=layer, success=False,
                                     error=f"Unknown store: {store_name}")

        store, visible_layers = self._stores[store_name]
        if layer not in visible_layers:
            return CapabilityResult(name="knowledge", layer=layer, success=False,
                                     error=f"Store '{store_name}' not visible to {layer}")

        results = store.search(args["query"], top_k=args.get("top_k", 5))
        return CapabilityResult(name="knowledge", layer=layer, success=True, data=results)
```

**附带的 Knowledge Store 示例：**

```python
# Leduc 游戏规则 store
leduc_rules = InMemoryKnowledgeStore()
leduc_rules.add("leduc_basics", """
Leduc Hold'em 简化版德州扑克：2人对局，6张牌（K/Q/J 各两种花色）。
两轮下注：翻牌前和翻牌后，每轮最多2次加注。
牌型比较：配对比单张高，同牌型比牌面大小和花色。
行动：call / raise / fold / check。
""")
leduc_rules.add("leduc_preflop", """
翻牌前策略：持有K=强制加注，持有Q=跟注或加注取决于对手，
持有J=通常跟注或弃牌。公共牌未翻时信息有限。
""")

# 设计文档 store
design_docs = InMemoryKnowledgeStore()
design_docs.add("a1_adjacent", "A1: 层间严格相邻传递。L(0.5+1)↔L2↔L3，禁止跨层跳跃。")
design_docs.add("a2_message", "A2: 统一 LayerMessage 信封。QUERY/RESPONSE/PROPOSAL/APPROVAL/REJECTION/NOTIFY。")

# KnowledgeCapability 组装
knowledge_cap = KnowledgeCapability(stores={
    "game_rules": (leduc_rules, {"l1", "l2", "l3"}),
    "design_docs": (design_docs, {"l1", "l2"}),
})
```

### 4. LayerInjector — 将 Capability 注入各层 Agent

这是方向一的核心：让 LayerAgent 的 LLM 调用能看到可用能力。

```python
# capability/layer_injector.py

class LayerInjector:
    """将 CapabilityRegistry 中的能力 schema 注入各层 Agent 的 LLM 调用。

    不改 LayerAgent._call_llm() 的签名——通过扩展参数注入。
    """

    def __init__(self, registry: CapabilityRegistry):
        self._registry = registry

    def get_tools_for_layer(self, layer: str) -> list[dict]:
        """返回该层可见工具的 OpenAI function-calling schema 列表"""
        tool_cap = self._registry._capabilities.get("tool")
        if tool_cap is None:
            return []
        # ToolCapability 根据 layer 返回该层可见工具的 schema
        return tool_cap.get_schemas_by_layer(layer)

    def inject_to_agent(self, layer: str, call_kwargs: dict) -> dict:
        """在 LayerAgent._call_llm() 调用前注入 tools 参数。

        Usage in LayerAgent._call_llm():
            call_kwargs = {"system": ..., "user": ..., "json_mode": True}
            self._injector.inject_to_agent("l2", call_kwargs)
            resp = self._llm.chat(**call_kwargs)
        """
        tools = self.get_tools_for_layer(layer)
        if tools:
            call_kwargs["tools"] = tools
        return call_kwargs

    def handle_tool_calls(self, layer: str, tool_calls: list[dict]) -> list[CapabilityResult]:
        """处理 LLM 返回的 tool_calls，执行并返回结果。
        调用方将 CapabilityResult 列表注入下一 stage 的 user prompt。
        """
        results = []
        for tc in tool_calls:
            func = tc.get("function", {})
            name = func.get("name", "")
            args = json.loads(func.get("arguments", "{}"))
            result = self._registry.invoke(name, layer, args)
            results.append(result)
        return results
```

### 5. Consolidation 整合到 LearningEnv

整理作为一种特殊的学习任务类型，完全复用 LearningEnv → Executor + Layers 路径。

新增内容仅在 LearningEnv：
- 容量规格（`limits` 配置）
- 自动监测（`needs_consolidation()`）
- 整理任务构建（已有 `build_consolidation_task()`，扩展三级整理策略）

```python
# core/env/learning_env.py 新增

class LearningEnv(Environment):
    def __init__(self, ...,
                 limits: dict | None = None,  # {"l2": 30, "l3": 20}
                 ):
        ...
        self._limits = limits or {"l2": 30, "l3": 20}

    def needs_consolidation(self) -> bool:
        """检查是否有层超过容量上限"""
        l2 = self._knowledge.get("l2")
        l3 = self._knowledge.get("l3")
        if l2 and len(l2.cards) > self._limits.get("l2", 30):
            return True
        if l3 and len(l3.list_all()) > self._limits.get("l3", 20):
            return True
        return False

    def get_consolidation_level(self) -> int:
        """根据超限程度返回整理级别：
        1 = 轻微超限（例行整理）
        2 = 严重超限（深度整理）
        """
        # 实现略
        return 1
```

触发时机（在游戏循环中，不改 LearningEnv 内部逻辑）：

```python
# scripts/run_leduc_cognitive.py 中的循环

# 学习检查
if scorer.should_trigger(domain):
    _run_learning_cycle(...)

# 整理检查（新增一行）
if lenv.needs_consolidation():
    _run_consolidation_cycle(...)  # 本质和 _run_learning_cycle 相同，
                                    # 只是 obs 来自 build_consolidation_task()
```

### 6. 与现有代码的边界

| 现有模块 | 改什么 | 不改什么 |
|---------|--------|---------|
| `core/tools/registry.py` | 无 | 完全不动 |
| `core/layers/base.py` → `LayerAgent._call_llm()` | 加可选参数 `tools: list[dict] \| None = None`。injector 在外部通过 `inject_to_agent()` 修改 call_kwargs 后传入 | 不改已有调用处（默认值 None 保持向后兼容） |
| `core/llm_client.py` → `LLMClient.chat()` | 加可选参数 `tools: list[dict] \| None = None`，透传到 OpenAI API | 不改已有调用处 |
| `core/env/learning_env.py` | 加 `needs_consolidation()` 方法 | 不改已有方法签名 |
| `core/skill_layer.py` | 无 | 完全不动 |
| `core/flexible_knowledge.py` | 无 | 完全不动 |
| `core/philosophy.py` | 无 | 完全不动 |

## 工具调用执行路径（消费端）

明确：**LLM 不执行工具，LLM 只决定调用什么工具 + 传什么参数。执行在 Python 端。**

```
LLM 返回 tool_calls
  │
  ▼
LayerAgent._call_llm() 检测到 resp.tool_calls
  │
  ▼
LayerInjector.handle_tool_calls(layer, tool_calls)
  │  遍历每个 tool_call:
  │    1. 解析 function.name + function.arguments (JSON)
  │    2. CapabilityRegistry.invoke(name, layer, args)
  │       ├─→ ToolCapability.invoke:
  │       │     ├─ 校验 layer 可见性
  │       │     └─ ToolRegistry.dispatch(name, args) → handler(args) → JSON string
  │       └─→ KnowledgeCapability.invoke:
  │             ├─ 校验层对 store 的可见性
  │             └─ store.search(query) → list[dict]
  │    3. 返回 CapabilityResult(success, data, error)
  │
  ▼
CapabilityResult 列表注入下一 stage 的 user prompt
  → L2Agent.stage2 的 user prompt 中追加 [工具调用结果] 段
```

关键约束：
- 工具执行超时由 handler 自行控制（如 `terminal` 的 30s 超时），不在 Capability 层面统一设置
- 工具的副作用（如 `write_file`）需要 APPROVAL 流程——当前预留，Phase 3 后期启用 `MessageType.APPROVAL`
- CapabilityResult 直接注入 user prompt 的文本格式：`[工具名] 结果摘要`，不经过 JSON 二次解析

## 预留方向：Meta-Capability

以下方向不在 Phase 3 初期实现范围内，但 Capability ABC 的设计已预留扩展空间。标记以供 Phase 3 后期根据实际使用数据决定。

### 7.1 工具编排（轻量 pipeline）

**场景**：Agent 频繁需要 `grep → read_file → web_search 验证` 这种固定模式的工具链。每次都通过 LLM 多轮 tool_call 完成，token 消耗大。

**现状覆盖**：大部分编排被现有 V-structure 承担——L1 拆解任务→L2 筛选知识→L3 执行技能，这不是纯工具串联而是认知推理链。

**建议方向**：如果数据表明 Agent 在单层内频繁做 3+ tool_calls 的线性串联，可增加一个 `pipeline` 工具：

```python
# 伪代码——非实现
pipeline({
    "steps": [
        {"tool": "grep", "args": {"pattern": "class Agent", "include": "*.py"}},
        {"tool": "read_file", "args": {"path": "$step0.matches[0].file"}},
        {"tool": "web_search", "args": {"query": "$step1.content[:100]"}},
    ]
})
```

Python 端顺序执行，中间结果通过 `$stepN.field` 引用传递。不涉及 LLM 推理。

**不做成完整 LangChain 的理由**：LangChain 的核心价值是 Chain/Branch/Loop + Prompt 模板 + Memory 管理，这三者在当前架构中已被 LayerMessage(A2) + V-structure + FlexibleKnowledge 分别覆盖。额外引入 LangChain 会与既有架构产生职责重叠和竞态。

### 7.2 自我注册——工具注册作为工具

**场景**：Agent 在运行时发现需要新能力（如"我需要一个读取 PDF 的工具"），能否自助注册？

**安全分析**：

| 注册对象 | 风险 | 建议 |
|---------|------|------|
| 新的 KnowledgeStore 条目 | 低——只是数据增删 | 可以：`knowledge_manage` 工具（类比 `skill_manage`） |
| 新的 Tool | 高——可注册 `rm -rf /` | 不允许。工具注册必须在启动时由配置完成 |
| 修改 Tool allowlist | 极高——绕过所有访问控制 | 绝不允许 |

**折中方案 — 工具注册 proposal + 人工审核**：

```
工具注册流程（非实时，带人工审核）:

  Agent 发现需要新工具
    │
    ▼
  LLM 输出 tool_proposal:
    {
      "name": "read_pdf",
      "schema": {...},           # OpenAI function-calling schema
      "handler_type": "subprocess",  # subprocess | http | python_callable
      "handler_config": {"command": "pdftotext {path} -"},
      "reason": "需要从 PDF 报告中提取策略数据用于学习"
    }
    │
    ▼
  Python 端: proposal 写入 data/tool_proposals/{name}.json
    │
    ▼
  用户定期检查 proposals/ 目录:
    - 审核 handler_type 是否安全（subprocess 命令、HTTP URL、Python 函数等）
    - 决定 allowlist 归属（哪些层可见）
    - 手动移入 core/tools/ 或拒绝（移到 rejected/）
    │
    ▼
  下次启动时，审核通过的工具自动注册到 ToolRegistry
```

关键安全措施：
- Agent 只能**提议**，不能注册——`tool_propose` 工具只写 JSON 文件，不调 `ToolRegistry.register()`
- proposal 不含 handler 实现代码——只含 handler_type + 配置参数，实际 handler 由人工编写
- 审核在启动时发生——新工具不会在 Agent 运行期间突然激活
- proposals/ 目录与代码同级——`data/tool_proposals/`，可加入 gitignore 或版本控制

Phase 3 初期不实现此功能。标记为预留方向，与 `knowledge_manage` 工具一起评估。

### 7.3 Python handler 的定位：安全边界而非能力上限

```
LLM 输出 ──→ Python handler(args) ──→ 系统能力
              ┌──────────────────┐
              │ 1. 输入校验       │  ← 限制 LLM 能做什么
              │ 2. 能力执行       │  ← Python 几乎无限制（subprocess / http / ctypes / ...）
              │ 3. 输出过滤       │  ← 限制返回给 LLM 的信息量
              └──────────────────┘
```

**Python 不是能力的瓶颈**——通过 `subprocess` 可以调用任何可执行文件、通过 `httpx` 可以访问任何网络 API、通过 `ctypes` 可以调用任何 C 库。不存在"系统能做到但 Python 做不到"的事情。

**Python handler 的真正价值是三层安全**：

| 层 | 作用 | 例子 |
|----|------|------|
| 输入校验 | 限制 LLM 的输入范围 | terminal 检查命令白名单；web_search 只取 query 字段，忽略 LLM 可能夹带的内部状态 |
| 能力执行 | 无限制的系统调用 | `subprocess.run()` / `httpx.post()` / `ctypes.CDLL()` |
| 输出过滤 | 限制返回给 LLM 的信息量 | terminal 返回 stdout 但截断 >10KB；web_search 只返回 title+snippet，不返回 HTTP headers |
| 运行时控制 | 防止失控 | terminal 30s 超时；max_calls_per_step 限制 |

**这意味着：设计一个新工具时，核心工作不是"怎么让 Python 做某件事"，而是"怎么安全地让 Python 做某件事"。**

handler 签名规范（所有工具 handler 遵循此模式）：

```python
def handler(args: dict, context: dict | None = None) -> str:
    """所有工具的 handler 统一签名。

    Args:
        args:     LLM 传来的参数（已由 function-calling schema 约束类型）
        context:  调用上下文 {layer, trace_id, tool_name} —— 用于日志和校验

    Returns:
        JSON string: {"result": ...} 或 {"error": "..."}

    安全约束：
        - 必须自行处理超时（长时间操作）
        - 必须捕获所有异常，返回结构化 error 而非 raise
        - 输出必须截断（避免 LLM 上下文爆炸）
        - 涉及文件/网络的，必须校验路径/URL 在允许范围内
    """
```

## 完整示例：L2 Agent 如何调用工具和知识

```
L2Agent.stage1(user_query="翻牌前持有K时应该怎么打")

  → LayerAgent._call_llm(system_prompt, user_query, schema=STAGE1_SCHEMA,
                          injector=injector, layer="l2")
     ↓ injector 自动注入 tools=[knowledge_query]
  → LLM 返回：
     {
       "cards": [...],
       "call_l3": false,
       "tool_calls": [
         {"function": {"name": "knowledge_query",
                        "arguments": {"store": "game_rules",
                                      "query": "翻牌前持有K时的策略"}}}
       ]
     }
  → LayerAgent 检测到 tool_calls → injector.handle_tool_calls("l2", tool_calls)
  → 返回 [CapabilityResult(success=True, data=[{content:"持有K=强制加注",...}])]
  → 将 tool 结果注入 stage2 的 user prompt:
     "[工具调用结果]\n knowledge_query: 持有K=强制加注，翻牌前应主动加注建立底池..."
  → L2Agent.stage2(...) 基于增强了的信息继续推理
```
