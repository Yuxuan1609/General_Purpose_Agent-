"""CognitiveAgent — Terminal-Bench BaseAgent implementation.

Wraps the cognitive-agent's Executor + 3-layer chain into TB's BaseAgent
interface. perform_task runs a multi-turn loop:
  1. Build TaskObservation from instruction + initial terminal state
  2. executor.execute(obs) → L1 decides action (may call tools via tmux)
  3. Capture pane → feed back as next observation
  4. Repeat until L1 returns done=True or max rounds reached
"""
from __future__ import annotations
import json
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from terminal_bench.agents.base_agent import AgentResult, BaseAgent
from terminal_bench.agents.failure_mode import FailureMode

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_MAX_ROUNDS = 30
_INITIAL_PANE_LINES = 50


class CognitiveAgent(BaseAgent):

    @staticmethod
    def name() -> str:
        return "cognitive-agent"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._executor = None
        self._chain = None
        self._setup_done = False
        self._task_meta = ""

    def _ensure_setup(self):
        if self._setup_done:
            return
        if str(_PROJECT_ROOT) not in sys.path:
            sys.path.insert(0, str(_PROJECT_ROOT))
        from core.setup import setup_executor
        self._chain, self._executor = setup_executor(_PROJECT_ROOT)

        import os
        phase = os.environ.get("TB_PHASE", "train")
        from tb.env import apply_learning_context
        apply_learning_context(self._chain, enable=(phase == "train"))

        from tb.tools import register_tb_tools
        from core.tools.registry import ToolRegistry
        registry = ToolRegistry()
        register_tb_tools(registry)
        self._setup_done = True

    def perform_task(
        self,
        instruction: str,
        session,
        logging_dir: Path | None = None,
    ) -> AgentResult:
        t_start = time.time()
        self._ensure_setup()

        from tb.session_holder import set as set_session, clear as clear_session
        set_session(session)

        # Disable pagers so git/man/etc output goes straight to terminal
        # instead of opening less, which breaks the tmux blocking mechanism.
        session.send_keys(
            ["export PAGER=cat GIT_PAGER=cat LESS=FRX", "Enter"],
            block=True, max_timeout_sec=10,
        )

        # Setup per-layer file logging (detailed prompts + tool calls → logs/tb/)
        _setup_tb_logging()

        try:
            time.sleep(0.5)
            initial_pane = session.capture_pane(capture_entire=True)
        except Exception:
            initial_pane = ""

        task_meta = (
            f"{instruction}\n\n"
            "## 重要说明\n"
            "你正在一个 Docker 容器内的终端环境中工作。所有文件操作和命令执行"
            "都在容器内进行。\n"
            "使用 terminal 工具执行命令，read_file 读取文件，grep 搜索文件内容。\n"
            "当任务完成时，明确输出 done=true 并在 result 中说明你做了什么。\n"
            "最终 test feedback（任务结束后的自动化测试结果）是 golden standard，"
            "判断任务是否成功的唯一标准。\n"
        )
        self._task_meta = task_meta

        current_feedback = _trim_pane(initial_pane, _INITIAL_PANE_LINES)

        # Reset LLM token counters
        llm = self._executor._llm
        llm.reset_token_counts()
        round_logs: list[dict] = []

        logger.info("=== Task started ===")
        logger.info("Instruction: %s", instruction[:200])
        logger.info("Initial pane (%d lines):\n%s",
                     len(initial_pane.splitlines()) if initial_pane else 0,
                     _head(initial_pane, 500))

        for round_idx in range(_MAX_ROUNDS):
            t_round = time.time()
            obs = self._build_observation(task_meta, current_feedback, round_idx)

            try:
                result = self._executor.execute(obs)
            except Exception as e:
                logger.error("Executor failed at round %d: %s", round_idx, e)
                clear_session()
                return AgentResult(
                    total_input_tokens=llm._prompt_tokens,
                    total_output_tokens=llm._completion_tokens,
                    failure_mode=FailureMode.UNKNOWN_AGENT_ERROR,
                )

            notify = result.get("notify_layers", {})
            l1_notify = notify.get("l0_5_1", {})
            done = l1_notify.get("done", False)
            action_text = str(result.get("action_text", ""))[:500]

            elapsed = time.time() - t_round
            tokens_so_far = llm.total_tokens
            logger.info(
                "Round %d: done=%s tokens=%d time=%.1fs action=%s",
                round_idx, done, tokens_so_far, elapsed, action_text[:120],
            )

            round_log = {
                "round": round_idx,
                "done": done,
                "elapsed_s": round(elapsed, 2),
                "tokens_total": tokens_so_far,
                "action_text": action_text,
                "l1_notify": {
                    k: str(v)[:300] for k, v in l1_notify.items()
                },
            }
            round_logs.append(round_log)

            if logging_dir:
                self._log_round(logging_dir, round_idx, result, done, elapsed,
                                tokens_so_far)

            time.sleep(0.5)
            try:
                pane = session.capture_pane(capture_entire=True)
                current_feedback = _trim_pane(pane, _INITIAL_PANE_LINES)
            except Exception:
                current_feedback = "(无法读取终端输出)"

            if done:
                logger.info("Task done at round %d (total tokens=%d time=%.1fs)",
                            round_idx, tokens_so_far, time.time() - t_start)
                break
        else:
            logger.warning("Reached max rounds (%d) without done signal", _MAX_ROUNDS)

        total_time = time.time() - t_start
        clear_session()

        if logging_dir:
            self._log_summary(logging_dir, round_logs, llm, total_time)

        return AgentResult(
            total_input_tokens=llm._prompt_tokens,
            total_output_tokens=llm._completion_tokens,
            failure_mode=FailureMode.NONE,
        )

    def _build_observation(self, task_meta: str, feedback: str, round_idx: int):
        from core.types import TaskObservation
        return TaskObservation(
            meta=task_meta,
            state={
                "current": feedback,
                "history": "",
                "round": round_idx,
            },
            session={
                "id": f"tb_{round_idx}",
                "domain": "tb",
                "domains_hint": ["tb"],
                "step_index": round_idx,
                "enable_learning": True,
            },
        )

    _REPAIR_MAX_ROUNDS = 15
    _REFLECT_MAX_ROUNDS = 5

    def receive_test_results(
        self,
        parser_results: dict | None,
        is_resolved: bool,
        exhausted: bool,
        session,
        terminal,
    ) -> None:
        """Called by FeedbackHarness after tests, while container is still alive."""
        from tb.session_holder import set as set_session, clear as clear_session

        set_session(session)

        try:
            time.sleep(0.3)
            pane = session.capture_pane(capture_entire=True)
        except Exception:
            pane = ""

        feedback_meta = self._build_feedback_meta(
            parser_results, is_resolved, exhausted
        )
        current_feedback = _trim_pane(pane, _INITIAL_PANE_LINES)

        max_rounds = (
            self._REFLECT_MAX_ROUNDS
            if (is_resolved or exhausted)
            else self._REPAIR_MAX_ROUNDS
        )

        logger.info(
            "=== Test feedback === is_resolved=%s exhausted=%s max_rounds=%d",
            is_resolved, exhausted, max_rounds,
        )

        for round_idx in range(max_rounds):
            obs = self._build_observation(feedback_meta, current_feedback, round_idx)
            try:
                result = self._executor.execute(obs)
            except Exception as e:
                logger.error("Executor failed in feedback round %d: %s", round_idx, e)
                break

            notify = result.get("notify_layers", {})
            l1_notify = notify.get("l0_5_1", {})
            done = l1_notify.get("done", False)

            logger.info(
                "Feedback round %d: done=%s action=%s",
                round_idx, done,
                str(result.get("action_text", ""))[:120],
            )

            time.sleep(0.3)
            try:
                pane = session.capture_pane(capture_entire=True)
                current_feedback = _trim_pane(pane, _INITIAL_PANE_LINES)
            except Exception:
                current_feedback = "(无法读取终端输出)"

            if done:
                break

        clear_session()

    def _build_feedback_meta(
        self,
        parser_results: dict | None,
        is_resolved: bool,
        exhausted: bool,
    ) -> str:
        """Build task meta for the feedback phase."""
        results_text = "（无测试结果）"
        if parser_results:
            lines = []
            for test_name, status in parser_results.items():
                lines.append(f"  {test_name}: {status.value}")
            results_text = "\n".join(lines)

        if is_resolved:
            phase = (
                "## 测试结果: PASS\n\n"
                "所有测试通过。请反思成功经验：\n"
                "- 哪些策略/命令有效\n"
                "- 哪些知识卡片/技能有帮助\n"
                "反思完成后，调用 record_learning 记录可复用经验，"
                "然后输出 done=true。\n"
            )
        elif exhausted:
            phase = (
                "## 测试结果: FAIL（已用尽修复次数）\n\n"
                "所有修复轮次已用完，任务未通过。请反思失败原因：\n"
                "- 哪里出了问题\n"
                "- 下次遇到类似任务该如何避免\n"
                "反思完成后，调用 record_learning 记录教训，"
                "然后输出 done=true。\n"
            )
        else:
            phase = (
                "## 测试结果: FAIL\n\n"
                "测试未通过。请分析失败原因，修复问题。\n"
                "- 使用 terminal/read_file/grep 工具检查文件和状态\n"
                "- 修复后输出 done=true 表示修复完成\n"
            )

        return (
            f"{self._task_meta}\n\n"
            f"{phase}\n"
            f"### 测试详情\n{results_text}\n"
        )

    def _log_round(self, logging_dir: Path, round_idx: int,
                   result: dict, done: bool, elapsed: float, tokens: int):
        log_path = logging_dir / f"round_{round_idx}.json"
        try:
            notify_summary = {}
            for k, v in result.get("notify_layers", {}).items():
                notify_summary[k] = {
                    kk: str(vv)[:500] for kk, vv in v.items()
                }
            log_path.write_text(json.dumps({
                "round": round_idx,
                "done": done,
                "elapsed_s": round(elapsed, 2),
                "tokens_total": tokens,
                "action_text": str(result.get("action_text", ""))[:2000],
                "notify_layers": notify_summary,
            }, ensure_ascii=False, indent=2))
        except Exception:
            pass

    def _log_summary(self, logging_dir: Path, round_logs: list[dict],
                     llm, total_time: float):
        summary_path = logging_dir / "summary.json"
        try:
            summary_path.write_text(json.dumps({
                "agent": "cognitive-agent",
                "completed_at": datetime.now(timezone.utc).isoformat(),
                "total_time_s": round(total_time, 1),
                "total_rounds": len(round_logs),
                "prompt_tokens": llm._prompt_tokens,
                "completion_tokens": llm._completion_tokens,
                "total_tokens": llm.total_tokens,
                "rounds": round_logs,
            }, ensure_ascii=False, indent=2))
        except Exception:
            pass


def _trim_pane(pane: str, max_lines: int) -> str:
    lines = pane.splitlines()
    if len(lines) <= max_lines:
        return pane
    return "\n".join(lines[-max_lines:])


def _head(text: str, n: int) -> str:
    return text[:n] + ("..." if len(text) > n else "")


def _setup_tb_logging():
    """Create per-layer DEBUG log files under logs/tb/<timestamp>/.

    Reuses the same logging infrastructure as interactive_agent.py via
    setup_layer_logging. Creates: l0_5_1.log, l2.log, l3.log, executor.log
    with full prompt and tool-call detail.
    """
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_dir = _PROJECT_ROOT / "logs" / "tb" / stamp
    from core.layers.logging_setup import setup_layer_logging
    setup_layer_logging(log_dir)
