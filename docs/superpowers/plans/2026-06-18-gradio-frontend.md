# Gradio Frontend — Design Spec (v2)

> **SUPERSEDED by v2:** 本文档已被 `docs/superpowers/specs/2026-06-19-gradio-frontend-v2-design.md` + `docs/superpowers/plans/2026-06-19-gradio-frontend-v2.md` 取代。
> v2 增加多 session 持久化 + 单 session 多 task 并行追踪 + sub-agent 任务可见性 + SQLite store 线程安全修复。
> 本文档保留作历史参考，请勿据此实现。

> **For agentic workers:** Use superpowers:subagent-driven-development to implement this plan task-by-task.

**Goal:** 为 cognitive agent 添加 Gradio Web UI，提供交互式对话 + **三层决策循环实时可视化**。不改动核心 agent 逻辑，通过 `core/monitor.py`（新增聚合模块）统一读取各组件状态。

**Architecture:** Gradio 作为独立前端层，复用 `scripts/interactive_agent.py` 的 setup 模式。Agent 核心不变。

**Tech Stack:** gradio, Python 3.10+, existing agent chain

---

## 架构边界

```
┌──────────────────────────────────────────────────────────┐
│  Gradio UI (scripts/gradio_app.py)                       │
│  ├─ Chat panel  ── executor.execute(obs) ────────────────┼──► Agent Chain
│  └─ Monitor panel ── monitor.snapshot() ─────────────────┼──► TaskRunner / stores
│                        └─ monitor.trace_events ──────────┼──► per-step NOTIFY
├──────────────────────────────────────────────────────────┤
│  core/setup.py (NEW)                                     │
│  └─ setup_executor()        → shared chain+executor init │
├──────────────────────────────────────────────────────────┤
│  core/monitor.py (NEW)                                   │
│  ├─ snapshot()              → static status              │
│  ├─ StepTrace               → per-step NOTIFY capture    │
│  ├─ task_snapshot()         → TaskRunner.status()        │
│  ├─ learning_snapshot()     → pending file count         │
│  └─ capacity_snapshot()     → L2/L3 card/skill count     │
├──────────────────────────────────────────────────────────┤
│  Existing core (UNCHANGED)                               │
│  ├─ TaskRunner.get_shared_runner().status()              │
│  ├─ consolidation_injection (get_store / get_registry)   │
│  ├─ runtime_registry (get_executor / get_chain)          │
│  └─ FlexibleKnowledge / SkillLayer                       │
└──────────────────────────────────────────────────────────┘

原则：
- Agent core 零源码改动 — 新增 3 文件 (core/setup.py, core/monitor.py, scripts/gradio_app.py)，修改 1 文件 (scripts/interactive_agent.py)
- 监控数据读取有锁保护（TaskRunner._lock），线程安全
- LLM 调用同步执行，Gradio 队列模式自动排队；定期定时刷新（`every=5`）不阻塞 callback
- 复用 scripts/interactive_agent.py 的 _setup_executor() 模式
- **v1 设计约束**：全局 chain + executor 共享，不支持多用户并发 chat（NOTIFY 字段会互相覆盖）。多用户时仅保证 session_state 隔离。
```

---

## File Structure

```
scripts/
  gradio_app.py          # NEW — Gradio 入口 + UI 布局
  interactive_agent.py   # MODIFIED — _setup_executor() → setup_executor()
core/
  setup.py               # NEW — 共享 executor/chain 初始化入口
  monitor.py             # NEW — 聚合监控数据 + StepTrace
  task_runner.py         # unchanged — 已有 status() / stats()
  chain_factory.py       # unchanged — build_default_chain()
  runtime_registry.py    # unchanged — register_runtime(chain, executor)
  consolidation_injection.py # unchanged — get_store() / get_registry()
  env/
    interaction_env.py   # unchanged — InteractionEnv
```

---

## Task 0: 提取共享 setup (`core/setup.py`)

**目标:** `scripts/interactive_agent.py` 的 `_setup_executor()` 逻辑提取为 `setup_executor()` 函数，放在独立新文件 `core/setup.py`。避免与 `core/monitor.py` 的监控职责混淆。

**当前问题:** interactive_agent.py 和 gradio_app.py 各自 copy-paste 相同的 LLM + chain + executor 初始化。违反 "禁止一事两做"。

**方案:** 新建 `core/setup.py`，CLI 和 Gradio 统一调用。与 `monitor.py` 职责分离：setup.py 负责初始化，monitor.py 负责查询。

```python
# core/setup.py (NEW)
"""Shared executor/chain setup — used by both CLI and Gradio."""
from pathlib import Path


def setup_executor(project_root: Path | None = None):
    """Create and wire llm → chain → executor. Returns (chain, executor)."""
    from core.env_loader import load_env
    if project_root is None:
        project_root = Path(__file__).resolve().parent.parent
    load_env(project_root)

    from core.llm_factory import build_llm_client
    llm = build_llm_client(project_root / "config.yaml")

    from core.chain_factory import build_default_chain
    chain = build_default_chain(project_root, auxiliary_llm=llm, seed=False)

    from core.executor import Executor
    executor = Executor(
        layer_root=chain,
        llm_client=llm,
        learning_dir=project_root / "data" / "learning",
    )

    from core.runtime_registry import register_runtime
    register_runtime(chain, executor)

    return chain, executor
```

**注意:** 原 interactive_agent.py 中 `chain._consol_ctx.executor = executor` 写入了一个**不存在的属性**（`ConsolidationContext` 类已被删除，consol_ctx 在当前 codebase 中不存在）。正确方式是用 `runtime_registry.register_runtime(chain, executor)`。

**同步修改:**
- `scripts/interactive_agent.py`: 替换 `_setup_executor()` 为 `from core.setup import setup_executor; chain, executor = setup_executor()`
- `scripts/gradio_app.py`: `from core.setup import setup_executor`

---

## Task 1: Monitor Module (`core/monitor.py`)

**目标:** 提供 `snapshot()` 静态状态查询 + `StepTrace` 数据结构用于捕获每次 execute 的三层决策过程。**纯查询模块，不包含 setup 逻辑**（setup 在 `core/setup.py`）。

### 1.1 `StepTrace` — 每次 execute 的完整记录

```python
from dataclasses import dataclass, field
from typing import Any

@dataclass
class StepTrace:
    """Captured per-execute trace of the 3-layer cognitive chain."""
    timestamp: str = ""
    user_input: str = ""
    action_text: str = ""
    notify_layers: dict = field(default_factory=dict)
    # {layer_name: {done, result, reply, reasoning, ...}}
    tool_calls: list[dict] = field(default_factory=list)
    # [{layer, tool_name, args, result_summary, sync, task_id}]
    record_learning_calls: list[dict] = field(default_factory=list)
    # [{domain, learning_target, importance, reasoning}]
```

### 1.2 `snapshot()` — 静态状态快照

```python
def snapshot(chain=None, pending_dir="data/learning/pending") -> dict:
    """Return full agent status snapshot as JSON-serializable dict."""
    return {
        "tasks": _task_snapshot(),
        "learning": _learning_snapshot(pending_dir),
        "capacity": _capacity_snapshot(chain),
        "sessions": _log_snapshot(),
    }

def _task_snapshot() -> dict:
    from core.task_runner import get_shared_runner
    return get_shared_runner().status()

def _learning_snapshot(pending_dir: str) -> dict:
    p = Path(pending_dir)
    domains = {}
    if p.exists():
        for d in p.iterdir():
            if d.is_dir():
                files = list(d.glob("*.json"))
                domains[d.name] = {"pending": len(files)}
    archive_dir = Path("data/learning/archive")
    archive_count = sum(1 for _ in archive_dir.rglob("*.json")) if archive_dir.exists() else 0
    return {
        "domains": domains,
        "total_pending": sum(d["pending"] for d in domains.values()),
        "total_archive": archive_count,
    }

def _capacity_snapshot(chain) -> dict:
    """L2/L3 capacity vs limits.
    
    chain structure: L0_5_1Manager → _downstream=L2Manager → _downstream=L3Manager
    L2Manager._knowledge = FlexibleKnowledge (has .cards list)
    L3Manager._skill_layer = SkillLayer (has .list_all())
    """
    from core.config_loader import get_section
    learn = get_section("learning", default={})
    l2_limit = learn.get("l2_card_limit", 30)
    l3_limit = learn.get("l3_skill_limit", 20)

    l2_count = 0
    l3_count = 0
    if chain:
        l2_mgr = chain._downstream  # L2Manager
        if l2_mgr and hasattr(l2_mgr, '_knowledge'):
            l2_count = len(l2_mgr._knowledge.cards)
        l3_mgr = l2_mgr._downstream if l2_mgr else None  # L3Manager
        if l3_mgr and hasattr(l3_mgr, '_skill_layer'):
            l3_count = len(l3_mgr._skill_layer.list_all())

    return {
        "l2": {"count": l2_count, "limit": l2_limit, "over": max(0, l2_count - l2_limit)},
        "l3": {"count": l3_count, "limit": l3_limit, "over": max(0, l3_count - l3_limit)},
    }

def _log_snapshot() -> dict:
    logs_dir = Path("logs/interaction")
    sessions = []
    if logs_dir.exists():
        for d in sorted(logs_dir.iterdir(), reverse=True):
            if d.is_dir():
                sessions.append(d.name)
    return {
        "interaction_logs": len(sessions),
        "latest": sessions[0] if sessions else None,
    }
```

### 1.3 Trace collection hook

要从 Gradio 获取每次 `executor.execute()` 产生的 NOTIFY 和各层工具调用，需要在 Executor 周围加薄包装。**不改 Executor 源码**，在 `scripts/gradio_app.py` 中调用后手动收集。

```python
# In gradio_app.py chat handler:
result = executor.execute(obs)
trace = StepTrace(
    user_input=user_input,
    action_text=result.get("action_text", ""),
    notify_layers=result.get("notify_layers", {}),
)
```

### 1.4 Key API verification

| Plan 引用 | 实际存在 | 备注 |
|-----------|---------|------|
| `TaskRunner.status()` | ✅ `core/task_runner.py:125` | |
| `get_shared_runner()` | ✅ `core/task_runner.py:171` | |
| `build_default_chain(data_root, ...)` | ✅ `core/chain_factory.py:5` | seed 默认 True |
| `build_llm_client(config_path)` | ✅ `core/llm_factory.py:8` | |
| `InteracionEnv(system_prompt, debug, enable_learning)` | ✅ `core/env/interaction_env.py:21` | **system_prompt 是位置参数，必填** |
| `InteractionEnv.reset()` | ✅ 必须调用才能初始化 session_id | |
| `InteractionEnv.receive_input()` | ✅ `interaction_env.py:42` | |
| `InteractionEnv.build_task_observation()` | ✅ `interaction_env.py:45` | |
| `InteractionEnv.step()` | ✅ `interaction_env.py:63` | 内部会 append user+assistant |
| `Executor.execute(obs) → {action_text, notify_layers}` | ✅ `core/executor.py:39` | |
| `chain._downstream._knowledge.cards` | ✅ | chain→L2Manager→FlexibleKnowledge |
| `chain._downstream._downstream._skill_layer.list_all()` | ✅ | chain→L2Manager→L3Manager→SkillLayer |
| `get_section('learning')` | ✅ `core/config_loader.py:24` | |
| `register_runtime(chain, executor)` | ✅ `core/runtime_registry.py:13` | 替代已删除的 consol_ctx |
| ~~`chain._consol_ctx.pending_mods`~~ | ❌ 不存在 | `ConsolidationContext` 类已删除 |
| ~~`chain._consol_ctx.executor = ...`~~ | ❌ 不存在 | 用 `register_runtime()` 替代 |
| ~~`consolidation_injection.pending_mods`~~ | ❌ 不存在 | handler 直接修改 store，无 side-channel |

---

## Task 2: Gradio App (`scripts/gradio_app.py`)

**目标:** 对话界面 + 三层决策循环实时可视化。复用 `core.setup.setup_executor()`。

### 2.1 核心设计

```python
# scripts/gradio_app.py
"""Cognitive Agent — Gradio Web UI with 3-layer decision loop monitoring."""
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
import gradio as gr

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.setup import setup_executor
from core.monitor import snapshot, StepTrace

DEFAULT_SYSTEM_PROMPT = "你是一个智能助手。请直接简洁地回复用户的问题。"

# ── State Management ──

@dataclass
class SessionState:
    """Per-session state. Gradio runs in multi-user mode — each user needs their own."""
    env: object = None
    trace_history: list[StepTrace] = field(default_factory=list)


def _create_session(system_prompt: str = DEFAULT_SYSTEM_PROMPT,
                    debug: bool = True, enable_learning: bool = True) -> SessionState:
    from core.env.interaction_env import InteractionEnv
    env = InteractionEnv(
        system_prompt=system_prompt,
        debug=debug,
        enable_learning=enable_learning,
    )
    env.reset("interaction")
    return SessionState(env=env)


def main():
    chain, executor = setup_executor(PROJECT_ROOT)

    def chat(user_input: str, history: list, session_state: SessionState):
        """Handle one chat turn. Runs LLM in sync (blocking callback), but preserves UI."""
        if not user_input or not user_input.strip():
            return history, session_state, *_empty_monitor()

        env = session_state.env
        env.receive_input(user_input.strip())
        task_obs = env.build_task_observation()
        if task_obs is None:
            return history, session_state, *_empty_monitor()

        try:
            result = executor.execute(task_obs)
        except Exception as e:
            reply = f"[Error] {e}"
            trace = StepTrace(user_input=user_input)
        else:
            reply = (result.get("action_text") or "").strip() or "(no output)"
            trace = StepTrace(
                timestamp=datetime.now().isoformat(),
                user_input=user_input,
                action_text=reply,
                notify_layers=result.get("notify_layers", {}),
            )

        # env.step 内部会 append user + assistant 两条，不要再手动加
        env.step(reply)
        session_state.trace_history.append(trace)

        history.append((user_input, reply))
        monitor_data = _build_monitor_display(chain, trace, session_state.trace_history)
        return history, session_state, *monitor_data  # unpack 5-tuple → 7 outputs


    def clear_chat(session_state: SessionState):
        """Clear chat + reset session state."""
        new_session = _create_session()
        return [], "", new_session  # chatbot, msg, session_state


    def _empty_monitor():
        return (
            gr.update(value={}),                          # task_status
            gr.update(value={}),                          # capacity
            gr.update(value={}),                          # learning
            gr.update(value=[]),                          # trace_log
            gr.update(value="## 暂无 trace"),              # trace_detail
        )

    def _build_monitor_display(chain, trace: StepTrace, all_traces: list[StepTrace]):
        """Build all monitor panel outputs from snapshot + trace."""
        snap = snapshot(chain=chain)

        # ── Task status ──
        task_data = snap.get("tasks", {})

        # ── Capacity ──
        capacity = snap.get("capacity", {})

        # ── Learning ──
        learning = snap.get("learning", {})

        # ── Trace log (last 20 steps) ──
        log_rows = []
        for t in all_traces[-20:]:
            layers_activity = ", ".join(
                n.replace("l0_5_1","L1").replace("l2","L2").replace("l3","L3")
                for n, v in t.notify_layers.items() if v
            )
            log_rows.append([
                t.timestamp[:19] if t.timestamp else "",
                f"{t.user_input[:60]}..." if len(t.user_input) > 60 else t.user_input,
                f"{t.action_text[:60]}..." if len(t.action_text) > 60 else t.action_text,
                layers_activity or "—",
            ])

        # ── Trace detail (latest step) ──
        detail_md = _format_trace_detail(trace) if trace.user_input else "## 等待输入..."

        return (
            gr.update(value=task_data),
            gr.update(value=capacity),
            gr.update(value=learning),
            gr.update(value=log_rows),
            gr.update(value=detail_md),
        )

    # ── UI Layout ──

    with gr.Blocks(title="Cognitive Agent", theme=gr.themes.Soft()) as app:
        # Session state — Gradio State 为每个用户创建独立实例
        session_state = gr.State(_create_session())

        gr.Markdown("# Cognitive Agent — 三层认知架构")

        with gr.Row():
            # ── Chat panel (left, 60%) ──
            with gr.Column(scale=3):
                chatbot = gr.Chatbot(label="对话", height=500)
                with gr.Row():
                    msg = gr.Textbox(label="输入", placeholder="输入你的问题...", scale=8)
                    send_btn = gr.Button("发送", variant="primary", scale=1)
                clear_btn = gr.Button("清空对话 / 新会话", size="sm")

            # ── Monitor panel (right, 40%) ──
            with gr.Column(scale=2):
                gr.Markdown("## 监控面板")

                with gr.Accordion("TaskRunner 状态", open=True):
                    task_json = gr.JSON(label="")

                with gr.Accordion("容量状态 (L2/L3)", open=True):
                    cap_json = gr.JSON(label="")

                with gr.Accordion("学习记录", open=True):
                    learn_json = gr.JSON(label="")

                gr.Markdown("---")
                gr.Markdown("### 决策链 Trace (最近 20 步)")

                trace_table = gr.Dataframe(
                    headers=["时间", "用户输入", "Agent 输出", "活动层"],
                    datatype=["str", "str", "str", "str"],
                    label="",
                )

                gr.Markdown("### 当前步骤详情")
                trace_detail = gr.Markdown("## 暂无 trace")

                with gr.Row():
                    refresh_btn = gr.Button("手动刷新", size="sm")

        # ── Event handlers ──

        def on_chat(user_input, history, state):
            return chat(user_input, history, state)

        # Send on Enter or button click
        msg.submit(
            on_chat,
            [msg, chatbot, session_state],
            [chatbot, session_state, task_json, cap_json, learn_json, trace_table, trace_detail],
        ).then(lambda: "", None, msg)

        send_btn.click(
            on_chat,
            [msg, chatbot, session_state],
            [chatbot, session_state, task_json, cap_json, learn_json, trace_table, trace_detail],
        ).then(lambda: "", None, msg)

        clear_btn.click(
            clear_chat,
            [session_state],
            [chatbot, msg, session_state],
        ).then(
            lambda: _empty_monitor(),
            None,
            [task_json, cap_json, learn_json, trace_table, trace_detail],
        )

        refresh_btn.click(
            lambda s: _build_monitor_display(
                chain, s.trace_history[-1] if s.trace_history else StepTrace(), s.trace_history,
            ),
            [session_state],
            [task_json, cap_json, learn_json, trace_table, trace_detail],
        )

        # Periodic refresh (every 5s)
        app.load(
            lambda s: _build_monitor_display(
                chain, s.trace_history[-1] if s.trace_history else StepTrace(), s.trace_history,
            ),
            [session_state],
            [task_json, cap_json, learn_json, trace_table, trace_detail],
            every=5,
        )

    app.launch(server_name="127.0.0.1", server_port=7860)


def _format_trace_detail(trace: StepTrace) -> str:
    """Format latest step trace as Markdown for display in detail panel."""
    lines = [
        f"**时间:** {trace.timestamp[:19] if trace.timestamp else '—'}",
        f"**用户输入:** {trace.user_input}",
        f"**Agent 输出:** {trace.action_text}",
        "",
        "### 各层 NOTIFY",
    ]

    # Per-layer key mapping — layers output different field names:
    # L1: done, result, reasoning
    # L2: done, reply, reasoning
    # L3: result, reasoning
    layer_keys = {
        "l0_5_1": {"label": "L1 (行为准则+决策)", "keys": ("done", "result", "reasoning")},
        "l2":     {"label": "L2 (知识检索)",       "keys": ("done", "reply", "reasoning")},
        "l3":     {"label": "L3 (技能执行)",       "keys": ("result", "reasoning")},
    }

    for layer_name, info in layer_keys.items():
        payload = trace.notify_layers.get(layer_name, {})
        if not payload:
            continue
        lines.append(f"\n#### {info['label']}")
        for key in info["keys"]:
            val = payload.get(key)
            if val is not None and val != "":
                lines.append(f"- **{key}:** {str(val)[:300]}")

    return "\n".join(lines)


if __name__ == "__main__":
    main()
```

### 2.2 状态管理

| 问题 | 修复 |
|------|------|
| InteractionEnv 缺 system_prompt 参数 | 传入 `DEFAULT_SYSTEM_PROMPT` |
| reset() 未调用 | `_create_session()` 中调用 `env.reset()` |
| 多 session 共享 env | 用 `gr.State(_create_session())` 每用户独立 |
| LLM 同步阻塞 UI | 使用 Gradio 4.x `app.load(..., every=5)` 定时刷新监控；chat callback 内阻塞可接受（Gradio 队列模式自动排队） |
| monitor 返回值不匹配 outputs | 返回 tuple 对应 5 个 output 组件 |
| 清空按钮不清 env | 重建 session_state |
| env.step 内部已 append history | 移除 chat 函数中的外部 `session_history.append()` |
| auto_refresh 死控件 | 用 Gradio 4.x `every=5` 参数实现真正的定时刷新 |
| Executor 双实例 | 用 `setup_executor()` 统一创建，`register_runtime()` 注册 |
| `consol_ctx.pending_mods` 不存在 | 完全移除该访问；consolidation 状态暂不在 v1 显示 |
| `register_record_learning` 死导入 | 移除 |

### 2.3 UI Layout

```
┌──────────────────────────────────────────────────────────┐
│  # Cognitive Agent — 三层认知架构                         │
├───────────────────────────────┬──────────────────────────┤
│  Chat Panel (60%)           │  监控面板 (40%)           │
│  ┌────────────────────────┐  │  ┌─ TaskRunner 状态 ───┐ │
│  │ User: 你好             │  │  │ {running:1, done:3} │ │
│  │ Agent: 你好！...       │  │  └─────────────────────┘ │
│  └────────────────────────┘  │  ┌─ 容量状态 ──────────┐ │
│  [输入框___________] [发送] │  │  │ L2: 5/30 L3:3/20 │ │
│  [清空对话 / 新会话]        │  │  └─────────────────────┘ │
│                              │  ┌─ 学习记录 ──────────┐ │
│                              │  │  │ pending:2 arch:8│ │
│                              │  └─────────────────────┘ │
│                              │  ─── 决策链 Trace ────   │
│                              │  │时间│输入│输出│活动层│ │
│                              │  │... │... │... │L1,L2│ │
│                              │  ─── 当前步骤详情 ────   │
│                              │  ## L1: done=True       │
│                              │  ## L2: reply=...       │
│                              │  ## L3: result=...      │
│                              │  [手动刷新]              │
└───────────────────────────────┴──────────────────────────┘
```

---

## Task Dependency Graph

```
T0 (core/setup.py) ────────→ update interactive_agent.py
     │                              │
     │                              └─→ 共用 setup 逻辑
     │
     └──→ T2 (gradio_app.py) ── 依赖 setup + monitor
              ↑
T1 (monitor.py) ── 纯查询，零副作用
     │
     └── 读取: TaskRunner.status(), chain 内部属性
```

---

## 自检清单

### 功能正确性
- [ ] `core/setup.py` 独立文件，不混入 monitor 模块
- [ ] `core/monitor.py` 所有函数纯查询，不修改状态
- [ ] `snapshot()` 各子函数使用已验证存在的 API（见 1.4 表）
- [ ] `_capacity_snapshot` 用 `chain._downstream._knowledge.cards` 和 `chain._downstream._downstream._skill_layer.list_all()`
- [ ] 不再引用不存在的 `ConsolidationContext` / `pending_mods`
- [ ] 使用 `runtime_registry.register_runtime()` 而非 `chain._consol_ctx.executor = ...`

### InteractionEnv 生命周期
- [ ] `InteractionEnv` 构造时传入 `system_prompt`（必填参数）
- [ ] `env.reset()` 在 `_create_session()` 中调用
- [ ] env.step 内部已 append history，chat 函数不重复添加
- [ ] 清空按钮重建 session_state（包含 env reset）

### Gradio 正确性
- [ ] `chat()` 返回值用 `*monitor_data` 展开，匹配 7 个 outputs
- [ ] 所有 `return` 路径（含 early return）都展开 `*_empty_monitor()`
- [ ] `gr.Markdown` 无无效的 `label` 参数
- [ ] 使用 `gr.State(_create_session())` 保证多用户 session 隔离
- [ ] LLM 调用同步执行，Gradio 队列模式自动处理多用户排队
- [ ] 定时刷新使用 `every=5` 参数
- [ ] `_empty_monitor()` 返回 5-tuple 匹配 monitor outputs 数量

### Trace 展示
- [ ] 监控面板展示决策链 Trace（活动层 table + NOTIFY 详情）
- [ ] `_format_trace_detail` 按层使用不同 key mapping（L1: result, L2: reply, L3: result）
- [ ] trace 仅从 `executor.execute()` 返回值收集，不修改 Executor 源码

### 文件/纪律
- [ ] agent core 零源码改动（setup.py + monitor.py + gradio_app.py 仅新增）
- [ ] `scripts/interactive_agent.py` 的 `_setup_executor()` 替换为 `from core.setup import setup_executor`
- [ ] 无死导入（无 `threading`、无 `register_record_learning` 等）
- [ ] `MAINTAIN.md` 新增条目：`setup.py` — `setup_executor()`；`monitor.py` — `snapshot()`, `StepTrace`, `_task_snapshot`, `_learning_snapshot`, `_capacity_snapshot`, `_log_snapshot`；`gradio_app.py` — `main()`
- [ ] `MAINTAIN.md` 修正 4 处过时签名：`build_chain`(L302) 删 `consol_ctx`；`L0_5_1Manager`(L274), `L2Manager`(L262), `L3Manager`(L252) 删 `consol_ctx` 参数
