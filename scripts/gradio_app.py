"""Cognitive Agent — Gradio Web UI with multi-session + parallel task tracking.

Three-column layout:
- Left: Session list (persistent, create/switch/delete)
- Middle: Task list for current session (top-level + sub-agent, parallel visible) + chat input
- Right: Trace detail for selected task (L1/L2/L3 decision tree + sub-tasks + layer logs)
"""
from __future__ import annotations
import sys
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import gradio as gr

from core.setup import setup_executor
from core.session import (
    get_session_store, set_task_context, clear_task_context,
)
from core.monitor import snapshot, log_tail, task_list, task_detail, decision_tree
from core.task_runner import get_shared_runner

DEFAULT_SYSTEM_PROMPT = "你是一个智能助手。请直接简洁地回复用户的问题。"


@dataclass
class SessionState:
    """Per-browser-session state. Gradio State creates one per user."""
    env: object = None
    session_id: str = ""
    session_name: str = ""
    current_task_id: str = ""
    chat_history: list = field(default_factory=list)


def _create_env(system_prompt: str = DEFAULT_SYSTEM_PROMPT):
    from core.env.interaction_env import InteractionEnv
    env = InteractionEnv(
        system_prompt=system_prompt,
        debug=True,
        enable_learning=True,
    )
    env.reset("interaction")
    return env


def _setup_task_tracking():
    """Wire TaskRunner events → SessionStore updates."""
    store = get_session_store()
    store.mark_interrupted_on_startup()

    def on_task_change(task):
        try:
            store.update_task(
                task.task_id,
                status=task.status,
                progress=task.progress,
                result_summary=(str(task.result)[:500] if task.result else None),
            )
        except Exception:
            pass

    get_shared_runner().subscribe(on_task_change)


def _refresh_session_list():
    store = get_session_store()
    sessions = store.list_sessions(include_closed=False)
    rows = []
    for s in sessions:
        rows.append([s["id"], s["name"], s["status"], s.get("last_active_at", "")[:19]])
    return gr.update(value=rows)


def _refresh_task_list(session_id: str):
    if not session_id:
        return gr.update(value=[])
    tasks = task_list(session_id)
    rows = []
    for t in tasks:
        type_label = {"top": "用户查询", "record_learning": "记录学习",
                      "auto_learning": "自动学习", "terminal": "终端"}.get(
            t["type"], t["type"])
        rows.append([
            t["id"][:8],
            type_label,
            t["status"],
            f"{t['progress']:.0f}%",
            t.get("created_at", "")[:19],
        ])
    return gr.update(value=rows)


def _refresh_trace(session_id: str, task_id: str, log_dir: str = ""):
    """Build trace panel content for selected task."""
    if not task_id:
        return gr.update(value="## 选择一个 task 查看详情"), gr.update(value={}), gr.update(value="")

    detail = task_detail(task_id)
    if not detail:
        return gr.update(value=f"## Task {task_id} 未找到"), gr.update(value={}), gr.update(value="")

    md_lines = [
        f"## Task {task_id[:8]}",
        f"- **类型:** {detail['type']}",
        f"- **状态:** {detail['status']}",
        f"- **进度:** {detail['progress']:.0f}%",
    ]
    if detail.get("result_summary"):
        md_lines.append(f"- **结果:** {detail['result_summary'][:300]}")

    sub_tasks = task_list(session_id, parent_task_id=task_id) if session_id else []
    if sub_tasks:
        md_lines.append("\n### 子任务 (sub-agent)")
        for st in sub_tasks:
            md_lines.append(
                f"- `{st['id'][:8]}` {st['type']} [{st['status']}] {st['progress']:.0f}%"
            )

    if detail["type"] == "top":
        tree = decision_tree()
        if tree:
            md_lines.append(f"\n### 决策树 (L1→L2→L3)")
            md_lines.append(f"共 {len(tree)} 轮决策")

    log_content = log_tail(log_dir, "l0_5_1", lines=50) if log_dir else ""

    return gr.update(value="\n".join(md_lines)), gr.update(value={"task": detail, "sub_tasks": sub_tasks}), gr.update(value=log_content)


def main():
    chain, executor = setup_executor(PROJECT_ROOT)
    _setup_task_tracking()

    def create_session(name: str):
        if not name.strip():
            name = f"Session {datetime.now().strftime('%H:%M')}"
        store = get_session_store()
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_dir = str(PROJECT_ROOT / "logs" / "interaction" / stamp)
        Path(log_dir).mkdir(parents=True, exist_ok=True)
        from core.layers.logging_setup import setup_layer_logging
        setup_layer_logging(Path(log_dir))
        s = store.create_session(name, log_dir=log_dir)
        env = _create_env()
        state = SessionState(env=env, session_id=s["id"], session_name=name)
        return state, [], _refresh_session_list(), _refresh_task_list(s["id"]), *_refresh_trace(s["id"], "", log_dir)

    def switch_session(evt: gr.SelectData, session_table, current_state):
        if evt.index[0] < 0:
            return current_state, [], gr.update(), gr.update(), gr.update(), gr.update(), gr.update()
        store = get_session_store()
        sessions = store.list_sessions(include_closed=False)
        if evt.index[0] >= len(sessions):
            return current_state, [], gr.update(), gr.update(), gr.update(), gr.update(), gr.update()
        session_id = sessions[evt.index[0]]["id"]
        s = store.get_session(session_id)
        if s is None:
            return current_state, [], gr.update(), gr.update(), gr.update(), gr.update(), gr.update()
        env = _create_env()
        new_state = SessionState(env=env, session_id=s["id"], session_name=s["name"])
        return (new_state, [], _refresh_session_list(), _refresh_task_list(s["id"]),
                *_refresh_trace(s["id"], "", s.get("log_dir", "")))

    def delete_session(session_table, current_state):
        if not current_state.session_id:
            return current_state, [], _refresh_session_list(), gr.update(), *_refresh_trace("", "")
        store = get_session_store()
        store.delete_session(current_state.session_id)
        new_state = SessionState()
        return new_state, [], _refresh_session_list(), gr.update(), *_refresh_trace("", "")

    def chat(user_input: str, state: SessionState):
        if not user_input or not user_input.strip():
            session = get_session_store().get_session(state.session_id) if state.session_id else None
            return state, state.chat_history, "", gr.update(), *_refresh_trace(
                state.session_id, state.current_task_id,
                (session or {}).get("log_dir", ""))
        if not state.session_id:
            state, *_ = create_session("默认 Session")

        env = state.env
        env.receive_input(user_input.strip())
        obs = env.build_task_observation()
        if obs is None:
            return state, state.chat_history, "", gr.update(), *_refresh_trace(
                state.session_id, state.current_task_id, "")

        top_tid = uuid.uuid4().hex[:12]
        store = get_session_store()
        store.register_task(top_tid, state.session_id, "top")
        set_task_context(state.session_id, top_tid)
        try:
            result = executor.execute(obs)
            reply = (result.get("action_text") or "").strip() or "(no output)"
            store.update_task(top_tid, status="done", progress=100.0,
                              result_summary=reply[:500])
        except Exception as e:
            reply = f"[Error] {e}"
            store.update_task(top_tid, status="error", result_summary=str(e)[:500])
        finally:
            clear_task_context()

        env.step(reply)
        state.chat_history.append({"role": "user", "content": user_input})
        state.chat_history.append({"role": "assistant", "content": reply})
        state.current_task_id = top_tid

        session = store.get_session(state.session_id) or {}
        log_dir = session.get("log_dir", "")
        return (state, state.chat_history, "", _refresh_task_list(state.session_id),
                *_refresh_trace(state.session_id, top_tid, log_dir))

    def select_task(evt: gr.SelectData, task_table, state: SessionState):
        if evt.index[0] < 0:
            return state, *_refresh_trace(state.session_id, "", "")
        store = get_session_store()
        tasks = store.list_tasks(state.session_id)
        if evt.index[0] >= len(tasks):
            return state, *_refresh_trace(state.session_id, "", "")
        state.current_task_id = tasks[evt.index[0]]["id"]
        session = store.get_session(state.session_id) or {}
        return state, *_refresh_trace(state.session_id, state.current_task_id,
                                      session.get("log_dir", ""))

    def refresh_log(log_dir, layer_choice):
        return gr.update(value=log_tail(log_dir, layer_choice, lines=50))

    # ── UI Layout ──
    with gr.Blocks(title="Cognitive Agent") as app:
        session_state = gr.State(SessionState())

        gr.Markdown("# Cognitive Agent — 多 Session + 并行任务追踪")

        with gr.Row():
            # ── Session 栏（左 25%）──
            with gr.Column(scale=1):
                gr.Markdown("### Sessions")
                with gr.Row():
                    new_session_name = gr.Textbox(
                        label="新 session 名", placeholder="工作区名...",
                        scale=3, lines=1)
                    create_btn = gr.Button("新建", variant="primary", scale=1)
                session_table = gr.Dataframe(
                    headers=["ID", "名称", "状态", "最后活跃"],
                    datatype=["str", "str", "str", "str"],
                    label="Session 列表",
                    interactive=False,
                )
                delete_btn = gr.Button("删除当前 session", size="sm", variant="stop")

            # ── 任务栏（中 30%）──
            with gr.Column(scale=1):
                gr.Markdown("### 任务 (并行可见)")
                task_table = gr.Dataframe(
                    headers=["ID", "类型", "状态", "进度", "创建时间"],
                    datatype=["str", "str", "str", "str", "str"],
                    label="当前 session 的任务",
                    interactive=False,
                )
                refresh_tasks_btn = gr.Button("刷新任务", size="sm")
                gr.Markdown("---")
                gr.Markdown("### 对话 (单任务提交)")
                chatbot = gr.Chatbot(label="对话历史", height=200)
                with gr.Row():
                    msg = gr.Textbox(label="输入", placeholder="输入问题...",
                                     scale=4, lines=1)
                    send_btn = gr.Button("发送", variant="primary", scale=1)

            # ── Trace 栏（右 45%）──
            with gr.Column(scale=2):
                gr.Markdown("### Trace 详情")
                trace_md = gr.Markdown("## 选择一个 task 查看详情")
                trace_json = gr.JSON(label="任务数据")

                gr.Markdown("### 层日志 (尾部 50 行)")
                with gr.Row():
                    layer_choice = gr.Radio(
                        ["l0_5_1", "l2", "l3", "executor"],
                        label="层", value="l0_5_1", scale=1)
                    log_refresh_btn = gr.Button("刷新日志", size="sm", scale=1)
                log_content = gr.Textbox(
                    label="", lines=15, max_lines=15,
                    interactive=False, show_label=False)

        # ── Event handlers ──
        create_btn.click(
            create_session,
            [new_session_name],
            [session_state, chatbot, session_table, task_table, trace_md, trace_json, log_content],
        ).then(lambda: "", None, new_session_name)

        session_table.select(
            switch_session,
            [session_table, session_state],
            [session_state, chatbot, session_table, task_table, trace_md, trace_json, log_content],
        )

        delete_btn.click(
            delete_session,
            [session_table, session_state],
            [session_state, chatbot, session_table, task_table, trace_md, trace_json, log_content],
        )

        msg.submit(
            chat,
            [msg, session_state],
            [session_state, chatbot, msg, task_table, trace_md, trace_json, log_content],
        )
        send_btn.click(
            chat,
            [msg, session_state],
            [session_state, chatbot, msg, task_table, trace_md, trace_json, log_content],
        )

        task_table.select(
            select_task,
            [task_table, session_state],
            [session_state, trace_md, trace_json, log_content],
        )

        refresh_tasks_btn.click(
            lambda s: _refresh_task_list(s.session_id),
            [session_state],
            [task_table],
        )

        log_refresh_btn.click(
            lambda s, lc: refresh_log(
                (get_session_store().get_session(s.session_id) or {}).get("log_dir", ""),
                lc),
            [session_state, layer_choice],
            [log_content],
        )

        # 定时刷新任务列表（每 3s）
        timer = gr.Timer(3.0)
        timer.tick(
            lambda s: _refresh_task_list(s.session_id) if s.session_id else gr.update(),
            [session_state],
            [task_table],
        )

    app.launch(server_name="127.0.0.1", server_port=7860, theme=gr.themes.Soft())


if __name__ == "__main__":
    main()
