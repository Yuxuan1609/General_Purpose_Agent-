# Gradio Frontend — Design Spec

> **For agentic workers:** Use superpowers:subagent-driven-development to implement this plan task-by-task.

**Goal:** 为 cognitive agent 添加 Gradio Web UI，提供交互式对话 + sub-agent 实时监控面板。不改动核心 agent 逻辑，通过现有单例 API 读取状态。

**Architecture:** Gradio 作为独立前端层，通过 `core/monitor.py`（新增聚合模块）统一读取各组件状态。Agent 核心不变。

**Tech Stack:** gradio, Python 3.10+, existing agent chain

---

## 架构边界

```
┌─────────────────────────────────────────────────────┐
│  Gradio UI (scripts/gradio_app.py)                  │
│  ├─ Chat panel  ── Executor.execute(obs) ──────────┼──► Agent Chain
│  └─ Monitor panel ── monitor.snapshot() ────────────┼──► TaskRunner / stores
├─────────────────────────────────────────────────────┤
│  core/monitor.py (NEW)                              │
│  ├─ task_snapshot()      → TaskRunner.status()     │
│  ├─ learning_snapshot()  → pending file count      │
│  ├─ capacity_snapshot()  → L2/L3 card/skill count  │
│  └─ consolidation_snapshot() → pending_mods        │
├─────────────────────────────────────────────────────┤
│  Existing core (UNCHANGED)                          │
│  ├─ TaskRunner.get_shared_runner().status()        │
│  ├─ ConsolidationContext (via chain._consol_ctx)    │
│  └─ FlexibleKnowledge / SkillLayer (len() queries)  │
└─────────────────────────────────────────────────────┘

原则：
- Agent core 零改动 — 只新增 2 个文件
- 监控数据读取有锁保护（TaskRunner._lock），线程安全
- LLM 调用在 Gradio callback 中同步执行，不阻塞 UI 刷新
```

---

## File Structure

```
scripts/
  gradio_app.py          # NEW — Gradio 入口 + UI 布局
core/
  monitor.py             # NEW — 聚合监控数据
  task_runner.py         # unchanged — 已有 status() / stats()
  chain_factory.py       # unchanged — build_default_chain()
```

---

## Task 1: Monitor Module (`core/monitor.py`)

**目标:** 提供单一 `snapshot()` 函数，聚合所有监控数据。

```python
# core/monitor.py
"""Monitor module — aggregate all agent stats for UI display."""
from pathlib import Path

def snapshot(chain=None, pending_dir="data/learning/pending") -> dict:
    """Return full agent status snapshot as JSON-serializable dict."""
    return {
        "tasks": _task_snapshot(),
        "learning": _learning_snapshot(pending_dir),
        "capacity": _capacity_snapshot(chain),
        "consolidation": _consolidation_snapshot(chain),
        "sessions": _log_snapshot(),
    }

def _task_snapshot() -> dict:
    """TaskRunner live status."""
    from core.task_runner import get_shared_runner
    return get_shared_runner().status()

def _learning_snapshot(pending_dir: str) -> dict:
    """Pending learning records per domain."""
    p = Path(pending_dir)
    domains = {}
    if p.exists():
        for d in p.iterdir():
            if d.is_dir():
                files = list(d.glob("*.json"))
                domains[d.name] = {
                    "pending": len(files),
                    "ready": len(files) >= 5,
                }
    archive_dir = Path("data/learning/archive")
    archive_count = sum(1 for _ in archive_dir.rglob("*.json")) if archive_dir.exists() else 0
    return {
        "domains": domains,
        "total_pending": sum(d["pending"] for d in domains.values()),
        "total_archive": archive_count,
    }

def _capacity_snapshot(chain) -> dict:
    """L2/L3 capacity vs limits."""
    from core.config_loader import get_section
    learn = get_section("learning", default={})
    l2_limit = learn.get("l2_card_limit", 30)
    l3_limit = learn.get("l3_skill_limit", 20)

    l2_count = 0
    l3_count = 0
    if chain:
        l2_mgr = chain._downstream
        if l2_mgr and l2_mgr._knowledge:
            l2_count = len(l2_mgr._knowledge.cards)
        l3_mgr = l2_mgr._downstream if l2_mgr else None
        if l3_mgr and l3_mgr._skill_layer:
            l3_count = len(l3_mgr._skill_layer.list_all())

    return {
        "l2": {"count": l2_count, "limit": l2_limit, "over": max(0, l2_count - l2_limit)},
        "l3": {"count": l3_count, "limit": l3_limit, "over": max(0, l3_count - l3_limit)},
    }

def _consolidation_snapshot(chain) -> dict:
    """Pending consolidation modifications."""
    if chain and hasattr(chain, "_consol_ctx") and chain._consol_ctx:
        return {
            "pending_mods": len(chain._consol_ctx.pending_mods),
        }
    return {"pending_mods": 0}

def _log_snapshot() -> dict:
    """Recent session log directories."""
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

---

## Task 2: Gradio App (`scripts/gradio_app.py`)

**目标:** 提供对话界面 + 侧栏监控面板。

```python
# scripts/gradio_app.py
"""Cognitive Agent — Gradio Web UI with sub-agent monitoring."""
import sys
import threading
import time
from pathlib import Path
import gradio as gr

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.env_loader import load_env
load_env(PROJECT_ROOT)


def _setup_agent():
    from core.llm_factory import build_llm_client
    from core.chain_factory import build_default_chain
    from core.executor import Executor

    llm = build_llm_client(PROJECT_ROOT / "config.yaml")
    chain = build_default_chain(PROJECT_ROOT, auxiliary_llm=llm, seed=False)

    from core.tools.record_learning_tool import register_record_learning
    from core.task_runner import get_shared_runner
    runner = get_shared_runner()
    chain._consol_ctx.executor = Executor(layer_root=chain, llm_client=llm)
    return chain, Executor(layer_root=chain, llm_client=llm)


def _build_ui(chain, executor):
    from core.monitor import snapshot
    from core.env.interaction_env import InteractionEnv

    env = InteractionEnv(enable_learning=True)
    session_history = []

    def chat(user_input, history):
        env.receive_input(user_input)
        obs = env.build_task_observation()
        result = executor.execute(obs)
        reply = (result.get("action_text") or "").strip() or "(no output)"
        env.step(reply)
        session_history.append({"role": "user", "content": user_input})
        session_history.append({"role": "assistant", "content": reply})
        history.append((user_input, reply))
        return history

    def refresh_monitor():
        return snapshot(chain=chain)

    with gr.Blocks(title="Cognitive Agent", theme=gr.themes.Soft()) as app:
        gr.Markdown("# Cognitive Agent")

        with gr.Row():
            # ── Chat panel (left) ──
            with gr.Column(scale=2):
                chatbot = gr.Chatbot(label="对话", height=500)
                msg = gr.Textbox(label="输入", placeholder="输入你的问题...")
                clear_btn = gr.Button("清空对话")

            # ── Monitor panel (right) ──
            with gr.Column(scale=1):
                gr.Markdown("## 监控面板")
                task_json = gr.JSON(label="TaskRunner 状态")
                cap_json = gr.JSON(label="容量状态 (L2/L3)")
                learn_json = gr.JSON(label="学习记录")
                refresh_btn = gr.Button("手动刷新")
                auto_refresh = gr.Checkbox(label="自动刷新 (3s)", value=True)

        msg.submit(chat, [msg, chatbot], chatbot).then(
            lambda: msg.update(value=""), None, msg
        ).then(refresh_monitor, None, [task_json, cap_json, learn_json])

        refresh_btn.click(refresh_monitor, None, [task_json, cap_json, learn_json])
        clear_btn.click(lambda: ([], []), None, [chatbot, msg])

        # Auto-refresh loop
        def auto_refresh_loop():
            while True:
                time.sleep(3)
                yield refresh_monitor()

        # TODO: gr.Periodic callback for auto-refresh (Gradio 4.x feature)

    return app


def main():
    chain, executor = _setup_agent()
    app = _build_ui(chain, executor)
    app.launch(server_name="127.0.0.1", server_port=7860)


if __name__ == "__main__":
    main()
```

---

## UI Layout

```
┌──────────────────────────────────────────────────┐
│  # Cognitive Agent                   [清空对话] │
├────────────────────────┬─────────────────────────┤
│  Chat Panel            │  监控面板               │
│                        │                         │
│  ┌──────────────────┐  │  TaskRunner 状态        │
│  │ User: 你好       │  │  {running:1, done:3,   │
│  │ Agent: 你好！... │  │   error:0}             │
│  │                  │  │                         │
│  │                  │  │  容量状态 (L2/L3)       │
│  │                  │  │  {l2:{count:5,limit:30}│
│  │                  │  │   l3:{count:3,limit:20}│
│  └──────────────────┘  │                         │
│  [输入框___________]   │  学习记录               │
│                        │  {pending:2, archive:8} │
│                        │                         │
│                        │  [手动刷新] ☑自动刷新   │
├────────────────────────┴─────────────────────────┤
└──────────────────────────────────────────────────┘
```

---

## Task Dependency Graph

```
T1 (monitor.py) ──→ T2 (gradio_app.py)
     │
     └── 读取: TaskRunner.status(), chain._consol_ctx, L2/L3 stores
     └── 不写: 纯查询，零副作用
```

---

## 自检清单

- [ ] `core/monitor.py` 所有 snapshot 函数纯查询，不修改状态
- [ ] TaskRunner 读取有锁保护
- [ ] Gradio UI 不导入 core/layers 内部实现细节，只通过 monitor.py 间接访问
- [ ] agent core 零改动
- [ ] LLM 调用同步执行（Gradio callback 阻塞直到返回），不超时
