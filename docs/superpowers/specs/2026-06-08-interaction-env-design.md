# 通用对话交互环境 (InteractionEnv) 设计

## 动机

为认知 Agent 提供一个通用的 CLI 对话式交互环境，支持多轮对话、会话管理、调试可见性，以及经验持久化到学习管道。

通信格式对齐 `LearningEnv`：`reset` → `receive_input` → `build_task_observation` → `step`，TaskObservation 字段匹配 Executor 预期。

## 架构

```
CLI 终端（用户）
   ↓ user_input
InteractionEnv.receive_input(user_input)
   ↓ build_task_observation()
TaskObservation { meta, state: {current, history, conversation_history}, session }
   ↓ AgentRuntime.run()
Executor → L(0.5+1) ↔ L2 ↔ L3
   ↓ result {"action_text", "notify_layers"}
InteractionEnv.step(action_text)
   ├─→ 记入 history
   └─→ (可选) Executor._write_pending() → data/learning/pending/interaction/{sid}_{ts}.json
CLI 终端（显示 reply）
```

## 组件

### 1. `core/env/interaction_env.py` — InteractionEnv

继承 `Environment` ABC（`core/env/base.py`），对齐 `LearningEnv` 通信模式。

```python
class InteractionEnv(Environment):
    """通用对话交互环境。管理会话和对话历史，构造符合 Executor 预期的 TaskObservation。"""

    def __init__(self, system_prompt: str, debug: bool = False, enable_learning: bool = True):
        self._system_prompt = system_prompt
        self._debug = debug
        self._enable_learning = enable_learning

        # 当前会话
        self._session_id: str = ""
        self._session_started_at: str = ""

        # 对话状态
        self._history: list[dict] = []          # [{"role":"user","content":...}, ...]
        self._pending_input: str = ""           # 待处理的用户输入
```

**方法**：

| 方法 | 签名 | 作用 |
|------|------|------|
| `reset` | `(task_description: str) -> EnvState` | 创建新会话，清空 history，返回欢迎 state |
| `receive_input` | `(user_input: str) -> None` | 接收用户输入，存入 `_pending_input` |
| `build_task_observation` | `() -> TaskObservation \| None` | 对齐 LearningEnv 命名，从 `_pending_input`+history 构造 TaskObservation |
| `step` | `(action: str) -> EnvStep` | 对齐 Environment ABC：记录本轮 (user,agent) 到 history，清空 `_pending_input` |
| `get_history` | `() -> list[dict]` | 返回 history 副本 |
| `session_info` | `() -> dict` | 返回当前会话元信息 |

**reset() 行为**：
- 生成新 `session_id` (UUID4)，记录 `_started_at` (UTC ISO)
- `_history.clear()`，`_pending_input = ""`
- 返回 `EnvState(observation=f"Session {session_id[:8]} started", info={"session_id": session_id})`

**build_task_observation() 构造**（对齐 LearningEnv 格式）：

```python
TaskObservation(
    meta=self._system_prompt,
    state={
        "current": self._pending_input,                          # Executor 传入 _build_user_prompt
        "history": self._format_history_for_prompt(),            # Executor 传入 _build_user_prompt
        "conversation_history": list(self._history),             # 结构化历史，供层内使用
    },
    session={
        "id": self._session_id,
        "domain": "interaction",
        "domains_hint": ["interaction"],
        "step_index": len(self._history) // 2,
        "enable_learning": self._enable_learning,
    },
)
```

**_format_history_for_prompt() 输出**（对齐 Executor 的 `state["history"]` 预期）：

```
[用户]: 你好
[助手]: 你好，有什么可以帮你？
[用户]: 今天天气怎么样
```

**step(action) 行为**：
- `self._history.append({"role": "user", "content": self._pending_input})`
- `self._history.append({"role": "assistant", "content": action})`
- `self._pending_input = ""`
- 返回 `EnvStep(state=EnvState(observation=action), reward=0, done=False)`

**history 格式**：

```python
[
    {"role": "user",      "content": "你好"},
    {"role": "assistant", "content": "你好，有什么可以帮你？"},
    {"role": "user",      "content": "今天天气怎么样"},
    {"role": "assistant", "content": "我目前没有实时天气查询能力..."},
]
```

### 2. `scripts/interactive_agent.py` — CLI 入口

```python
DEFAULT_SYSTEM_PROMPT = "你是一个智能助手。基于给定的知识和规则，直接回复用户的问题。"

def main():
    args = parse_args()  # --debug, --no-record, --system-prompt

    env = InteractionEnv(
        system_prompt=args.system_prompt or DEFAULT_SYSTEM_PROMPT,
        debug=args.debug,
        enable_learning=not args.no_record,
    )
    runtime = AgentRuntime(config)

    state = env.reset("interaction")
    print(state.observation)
    print("(Commands: /new=新会话, /info=会话信息, exit/quit=退出)\n")

    while True:
        try:
            user_input = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if user_input.lower() in ("exit", "quit"):
            break

        # ── 会话管理命令 ──
        if user_input == "/new":
            state = env.reset("interaction")
            print(state.observation)
            continue
        if user_input == "/info":
            info = env.session_info()
            print(f"Session: {info['id']} | turns: {info['turns']} | started: {info['started_at']}")
            continue

        if not user_input:
            continue

        # ── 标准交互循环 ──
        env.receive_input(user_input)
        task_obs = env.build_task_observation()
        result = runtime.run(task_obs)

        reply = result["action_text"]
        step = env.step(reply)

        if env._debug:
            _show_notifies(result["notify_layers"])

        print(f"Agent: {reply}")
```

**CLI 命令**：

| 命令 | 作用 |
|------|------|
| `exit` / `quit` | 退出 |
| `/new` | 调用 `env.reset()`，开始新会话（清空历史，新 session_id） |
| `/info` | 显示当前 session_id、turn 数、开始时间 |

### 3. 会话管理

| 属性 | 来源 | 说明 |
|------|------|------|
| `_session_id` | `uuid4()` | `reset()` 时生成，整个会话生命周期不变 |
| `_session_started_at` | `datetime.now(timezone.utc).isoformat()` | 会话开始时间 |
| `session_info()` | 方法 | 返回 `{"id", "turns": len//2, "started_at", "enable_learning"}` |

CLI 用户可通过 `/new` 触发会话重建，旧 history 丢弃（不存档），Executor pending 写入的旧 session 文件不影响新 session。

### 4. 持久化到学习管道（重点）

#### 触发条件

- **默认开启**：InteractionEnv 初始化时 `enable_learning=True`
- **关闭方式**：CLI 传 `--no-record` → `session["enable_learning"] = False` → Executor 跳过写入
- **谁负责写**：完全由 Executor 的 `_write_pending()` 方法执行，InteractionEnv 和脚本不直接写文件

#### 写入路径

```
data/learning/pending/interaction/{session_id}_{timestamp}.json
```

- `session_id` 来自 `TaskObservation.session["id"]`（InteractionEnv.reset() 时生成的 UUID）
- `timestamp` 为 Executor 首轮写入时的 `YYYYmmdd_HHMMSS` 格式
- 同一 session 的多轮对话**累积写入同一个文件**（原子写，load → append → replace）

#### 写入内容

每个 ExecutionRecord 完整记录一轮交互：

```json
[
  {
    "session": {
      "id": "abc12345-...",
      "domain": "interaction",
      "step_index": 0,
      "enable_learning": true
    },
    "observation": {
      "meta": "<system_prompt 文本>",
      "state": {
        "current": "你好",                   ← 本轮用户输入
        "history": "",                       ← 空（首轮无历史）
        "conversation_history": []           ← 结构化列表
      }
    },
    "notify_layers": {
      "l0_5_1": {"done": true, "result": "你好！有什么可以帮你的？", ...},
      "l2": {"cards_used": [...], ...},
      "l3": {}
    },
    "action": "你好！有什么可以帮你的？"
  },
  {
    "session": { "id": "abc12345-...", "domain": "interaction", "step_index": 1, ... },
    "observation": {
      "meta": "...",
      "state": {
        "current": "今天天气怎么样",          ← 第二轮用户输入
        "history": "[用户]: 你好\n[助手]: 你好！有什么可以帮你的？",
        "conversation_history": [
          {"role": "user", "content": "你好"},
          {"role": "assistant", "content": "你好！有什么可以帮你的？"}
        ]
      }
    },
    "notify_layers": {...},
    "action": "我目前没有实时天气查询能力..."
  }
]
```

#### 下游消费

- `LearningEnv._scan_pending("interaction")` 可读取该目录下所有 session 文件
- 每条 ExecutionRecord 包含完整的用户输入+对话历史+Agent 回复+各层 NOTIFY
- 后续可作为 L2 知识提炼、L1 规则优化的经验数据

## 异常情况设计

| 场景 | 处理 |
|------|------|
| 用户输入为空（直接回车） | 忽略，不发送给 Agent |
| 连续两次 `receive_input()` 未 `step()` | `receive_input` 覆盖 `_pending_input` |
| `build_task_observation()` 时 `_pending_input` 为空 | 返回 None，CLI 脚本跳过 |
| `runtime.run()` 抛出异常 | CLI 捕获，打印错误并提示重试，不退出 |
| debug 模式下 NOTIFY 过大 | `json.dumps(..., default=str)[:2000]` 截断 |
| `--no-record` 时 Executor IO 错 | 不影响交互循环，仅记录日志 |

## 未包含（YAGNI）

- Web/GUI 前端：换前端 I/O 层即可
- 对话分支/编辑：只保留线性历史
- 用户反馈标注：不做评分，后续 LearningEnv 扩展
- 流式输出：Executor 目前非流式
- 会话存档/恢复：`/new` 后旧 session 丢弃
