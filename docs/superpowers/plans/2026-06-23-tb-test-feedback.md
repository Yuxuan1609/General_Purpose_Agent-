# TB 测试结果反馈机制 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 TB harness 在测试跑完后、容器销毁前，将 pass/fail 结果反馈给 agent。FAIL 时 agent 可反思+修复并重跑测试（最多 3 轮修复），PASS 时 agent 反思成功原因并调用 `record_learning` 记录经验。

**Architecture:** 创建 `FeedbackHarness(Harness)` 子类重写 `_run_trial`，将 `_parse_results` 移入 `with spin_up_terminal()` 块内（容器存活期间），在解析结果后插入修复循环。`CognitiveAgent` 新增 `receive_test_results()` 方法接收反馈并驱动 Executor 反思/修复。通过 `tb/runner.py` monkey-patch `terminal_bench.Harness = FeedbackHarness` 后调用 Typer CLI。

**Tech Stack:** Python 3.13, Terminal-Bench 0.2.18, Typer CLI, threading.Lock

---

## File Map

| File | Role | Change |
|------|------|--------|
| `tb/feedback_harness.py` | `FeedbackHarness(Harness)` 子类 | Create — 重写 `_run_trial`，插入修复循环 |
| `tb/agent/cognitive_agent.py` | `CognitiveAgent(BaseAgent)` | Modify — 新增 `receive_test_results()` 方法 |
| `tb/runner.py` | Monkey-patch 入口 | Create — patch `terminal_bench.Harness` 后调用 CLI |
| `tb/run.sh` | TB 运行脚本 | Modify — `tb run` → `python -m tb.runner run`；加 `TB_PHASE` 传递 |
| `tb/env.py` | Train/Test 工具过滤 | Create — `apply_learning_context(chain, enable)` |
| `tb/config/tasks_data.yaml` | 32 道 Debugging 任务配置 | Create — 4 类 × 8 道 = 32 道，含 phase/train/test 标注 |
| `tests/test_feedback_harness.py` | 修复循环逻辑测试 | Create |
| `MAINTAIN.md` | 函数级维护文档 | Modify — 更新 tb/ 章节及 Changelog |

---

### Task 1: FeedbackHarness — 重写 `_run_trial` 插入修复循环

**Files:**
- Create: `tb/feedback_harness.py`
- Test: `tests/test_feedback_harness.py`

- [ ] **Step 1: Write failing test for repair loop logic**

创建 `tests/test_feedback_harness.py`：

```python
"""Tests for FeedbackHarness repair loop logic.

Mocks TB internals to verify the feedback loop runs the correct number
of rounds and calls receive_test_results with the right arguments.
"""
from unittest.mock import MagicMock, patch, call
import pytest


class TestFeedbackHarnessLoop:
    """Test the repair loop in isolation by mocking all TB internals."""

    def _make_mock_harness(self):
        """Create a FeedbackHarness with all dependencies mocked."""
        from tb.feedback_harness import FeedbackHarness
        # Bypass __init__ — we only test _run_trial logic
        h = FeedbackHarness.__new__(FeedbackHarness)
        h._logger = MagicMock()
        h._livestream = False
        h._no_rebuild = True
        h._cleanup = False
        return h

    def _make_mock_trial_handler(self):
        """Create a mock TrialHandler with minimal attributes."""
        handler = MagicMock()
        handler.task_id = "test-task"
        handler.instruction = "do something"
        handler.trial_name = "test-task__trial1"
        handler.task.run_tests_in_same_shell = True
        handler.task.disable_asciinema = True
        handler.task.max_test_timeout_sec = 60
        handler.trial_paths.pre_agent_pane_path = MagicMock()
        handler.trial_paths.pre_agent_pane_path.write_text = MagicMock()
        handler.trial_paths.post_agent_pane_path = MagicMock()
        handler.trial_paths.post_agent_pane_path.write_text = MagicMock()
        handler.trial_paths.sessions_path = MagicMock()
        handler.trial_paths.agent_logging_dir = MagicMock()
        handler.trial_paths.commands_path = MagicMock()
        handler.trial_paths.docker_compose_path = MagicMock()
        handler.client_container_name = "test-container"
        handler.client_image_name = "test-image"
        handler.docker_image_name_prefix = "test-prefix"
        handler.parser = MagicMock()
        return handler

    @patch('tb.feedback_harness.spin_up_terminal')
    @patch('tb.feedback_harness.Harness._run_agent')
    @patch('tb.feedback_harness.Harness._create_agent_for_task')
    def test_pass_calls_receive_test_results_once(
        self, mock_create_agent, mock_run_agent, mock_spin_up
    ):
        """When tests pass on first try, receive_test_results called once with is_resolved=True."""
        from terminal_bench.parsers.base_parser import UnitTestStatus
        from terminal_bench.agents.base_agent import AgentResult
        from terminal_bench.harness.models import FailureMode

        mock_agent = MagicMock()
        mock_create_agent.return_value = mock_agent
        mock_run_agent.return_value = (AgentResult(), FailureMode.NONE)

        mock_session = MagicMock()
        mock_session.capture_pane.return_value = "test output"
        mock_terminal = MagicMock()
        mock_terminal.create_session.return_value = mock_session
        mock_spin_up.return_value.__enter__.return_value = mock_terminal
        mock_spin_up.return_value.__exit__.return_value = False

        harness = self._make_mock_harness()
        handler = self._make_mock_trial_handler()

        # Tests pass on first try
        harness._run_tests = MagicMock(return_value=FailureMode.NONE)
        harness._parse_results = MagicMock(
            return_value=({"test_1": UnitTestStatus.PASSED}, FailureMode.NONE)
        )
        harness._is_resolved = MagicMock(return_value=True)

        harness._run_trial(handler)

        # Agent should have been called once with success
        assert mock_agent.receive_test_results.call_count == 1
        _, kwargs = mock_agent.receive_test_results.call_args
        assert kwargs["is_resolved"] is True
        assert kwargs["exhausted"] is False

    @patch('tb.feedback_harness.spin_up_terminal')
    @patch('tb.feedback_harness.Harness._run_agent')
    @patch('tb.feedback_harness.Harness._create_agent_for_task')
    def test_fail_then_repair_then_pass(
        self, mock_create_agent, mock_run_agent, mock_spin_up
    ):
        """When tests fail first, then pass after repair, loop runs 2 test cycles."""
        from terminal_bench.parsers.base_parser import UnitTestStatus
        from terminal_bench.agents.base_agent import AgentResult
        from terminal_bench.harness.models import FailureMode

        mock_agent = MagicMock()
        mock_create_agent.return_value = mock_agent
        mock_run_agent.return_value = (AgentResult(), FailureMode.NONE)

        mock_session = MagicMock()
        mock_session.capture_pane.return_value = "test output"
        mock_terminal = MagicMock()
        mock_terminal.create_session.return_value = mock_session
        mock_spin_up.return_value.__enter__.return_value = mock_terminal
        mock_spin_up.return_value.__exit__.return_value = False

        harness = self._make_mock_harness()
        handler = self._make_mock_trial_handler()

        # First test: FAIL, second test: PASS
        harness._run_tests = MagicMock(
            side_effect=[FailureMode.NONE, FailureMode.NONE]
        )
        parse_results_fail = ({"test_1": UnitTestStatus.FAILED}, FailureMode.NONE)
        parse_results_pass = ({"test_1": UnitTestStatus.PASSED}, FailureMode.NONE)
        harness._parse_results = MagicMock(
            side_effect=[parse_results_fail, parse_results_pass]
        )
        harness._is_resolved = MagicMock(
            side_effect=[False, True]
        )

        harness._run_trial(handler)

        # Tests run twice (initial + 1 repair retest)
        assert harness._run_tests.call_count == 2
        # Agent called twice: first FAIL (repair), then PASS (reflect)
        assert mock_agent.receive_test_results.call_count == 2
        first_call = mock_agent.receive_test_results.call_args_list[0]
        assert first_call.kwargs["is_resolved"] is False
        assert first_call.kwargs["exhausted"] is False
        second_call = mock_agent.receive_test_results.call_args_list[1]
        assert second_call.kwargs["is_resolved"] is True

    @patch('tb.feedback_harness.spin_up_terminal')
    @patch('tb.feedback_harness.Harness._run_agent')
    @patch('tb.feedback_harness.Harness._create_agent_for_task')
    def test_fail_3_repairs_exhausted(
        self, mock_create_agent, mock_run_agent, mock_spin_up
    ):
        """When tests fail all 4 rounds (1 initial + 3 repairs), final call has exhausted=True."""
        from terminal_bench.parsers.base_parser import UnitTestStatus
        from terminal_bench.agents.base_agent import AgentResult
        from terminal_bench.harness.models import FailureMode

        mock_agent = MagicMock()
        mock_create_agent.return_value = mock_agent
        mock_run_agent.return_value = (AgentResult(), FailureMode.NONE)

        mock_session = MagicMock()
        mock_session.capture_pane.return_value = "test output"
        mock_terminal = MagicMock()
        mock_terminal.create_session.return_value = mock_session
        mock_spin_up.return_value.__enter__.return_value = mock_terminal
        mock_spin_up.return_value.__exit__.return_value = False

        harness = self._make_mock_harness()
        handler = self._make_mock_trial_handler()

        # All 4 test runs fail
        harness._run_tests = MagicMock(return_value=FailureMode.NONE)
        fail_result = ({"test_1": UnitTestStatus.FAILED}, FailureMode.NONE)
        harness._parse_results = MagicMock(return_value=fail_result)
        harness._is_resolved = MagicMock(return_value=False)

        harness._run_trial(handler)

        # 4 test runs: 1 initial + 3 repairs
        assert harness._run_tests.call_count == 4
        # 4 agent calls: 3 repair + 1 exhausted
        assert mock_agent.receive_test_results.call_count == 4
        # First 3 calls: exhausted=False
        for i in range(3):
            c = mock_agent.receive_test_results.call_args_list[i]
            assert c.kwargs["is_resolved"] is False
            assert c.kwargs["exhausted"] is False
        # Last call: exhausted=True
        last_call = mock_agent.receive_test_results.call_args_list[3]
        assert last_call.kwargs["is_resolved"] is False
        assert last_call.kwargs["exhausted"] is True

    @patch('tb.feedback_harness.spin_up_terminal')
    @patch('tb.feedback_harness.Harness._run_agent')
    @patch('tb.feedback_harness.Harness._create_agent_for_task')
    def test_agent_without_receive_test_results_does_not_crash(
        self, mock_create_agent, mock_run_agent, mock_spin_up
    ):
        """Agents without receive_test_results (e.g. built-in agents) work fine."""
        from terminal_bench.parsers.base_parser import UnitTestStatus
        from terminal_bench.agents.base_agent import AgentResult
        from terminal_bench.harness.models import FailureMode

        # Agent without receive_test_results method
        mock_agent = MagicMock(spec=[])
        mock_create_agent.return_value = mock_agent
        mock_run_agent.return_value = (AgentResult(), FailureMode.NONE)

        mock_session = MagicMock()
        mock_session.capture_pane.return_value = "test output"
        mock_terminal = MagicMock()
        mock_terminal.create_session.return_value = mock_session
        mock_spin_up.return_value.__enter__.return_value = mock_terminal
        mock_spin_up.return_value.__exit__.return_value = False

        harness = self._make_mock_harness()
        handler = self._make_mock_trial_handler()

        harness._run_tests = MagicMock(return_value=FailureMode.NONE)
        harness._parse_results = MagicMock(
            return_value=({"test_1": UnitTestStatus.PASSED}, FailureMode.NONE)
        )
        harness._is_resolved = MagicMock(return_value=True)

        # Should not raise
        result = harness._run_trial(handler)
        assert result is not None
```

- [ ] **Step 2: Run test to verify it fails (module not found)**

Run: `python -m pytest tests/test_feedback_harness.py -v --tb=short`
Expected: FAIL with `ModuleNotFoundError: No module named 'tb.feedback_harness'`

- [ ] **Step 3: Write FeedbackHarness implementation**

创建 `tb/feedback_harness.py`：

```python
"""FeedbackHarness — Harness subclass that feeds test results back to agent.

Overrides _run_trial to:
1. Move _parse_results inside the `with spin_up_terminal()` block
2. After tests pass: call agent.receive_test_results(is_resolved=True) for reflection
3. After tests fail: call agent.receive_test_results(is_resolved=False) for repair,
   then retest. Max 3 repair rounds. On exhaustion, call with exhausted=True.
4. Agent without receive_test_results method is silently skipped (backward compat).
"""
from __future__ import annotations

from datetime import datetime, timezone

from terminal_bench.agents.base_agent import AgentResult
from terminal_bench.harness.harness import Harness
from terminal_bench.harness.models import FailureMode, TrialResults
from terminal_bench.terminal.terminal import spin_up_terminal

_MAX_REPAIRS = 3


class FeedbackHarness(Harness):
    """Harness subclass with test-result feedback loop.

    Identical to Harness._run_trial except:
    - _parse_results moved inside the `with` block (container still alive)
    - After parsing, runs a repair loop that calls agent.receive_test_results()
    - Final results.is_resolved reflects the LAST test run's outcome
    """

    def _run_trial(
        self,
        trial_handler,
    ) -> TrialResults:
        self._logger.debug(f"Running task: {trial_handler.task_id}")

        results = TrialResults(
            trial_name=trial_handler.trial_name,
            task_id=trial_handler.task_id,
            instruction=trial_handler.instruction,
        )
        results.trial_started_at = datetime.now(timezone.utc).isoformat()

        with spin_up_terminal(
            client_container_name=trial_handler.client_container_name,
            client_image_name=trial_handler.client_image_name,
            docker_image_name_prefix=trial_handler.docker_image_name_prefix,
            docker_compose_path=trial_handler.trial_paths.docker_compose_path,
            sessions_logs_path=trial_handler.trial_paths.sessions_path,
            agent_logs_path=trial_handler.trial_paths.agent_logging_dir,
            commands_path=trial_handler.trial_paths.commands_path,
            no_rebuild=self._no_rebuild,
            cleanup=self._cleanup,
            livestream=self._livestream,
            disable_recording=trial_handler.task.disable_asciinema,
        ) as terminal:
            session = terminal.create_session(
                "agent", is_active_stream=self._livestream, as_configured_user=True
            )

            pre_agent_pane = session.capture_pane(capture_entire=True)
            trial_handler.trial_paths.pre_agent_pane_path.write_text(pre_agent_pane)

            task_agent = self._create_agent_for_task(trial_handler.task_id)

            results.agent_started_at = datetime.now(timezone.utc).isoformat()

            agent_result, agent_failure_mode = self._run_agent(
                session=session,
                agent=task_agent,
                trial_handler=trial_handler,
            )

            results.agent_ended_at = datetime.now(timezone.utc).isoformat()

            post_agent_pane = session.capture_pane(capture_entire=True)
            trial_handler.trial_paths.post_agent_pane_path.write_text(post_agent_pane)

            if agent_failure_mode == FailureMode.AGENT_TIMEOUT:
                results.failure_mode = agent_failure_mode
                self._logger.debug(
                    f"Agent failed with mode {agent_failure_mode}, continuing"
                    " with test execution"
                )
            elif agent_failure_mode != FailureMode.NONE:
                results.failure_mode = agent_failure_mode

            if agent_result is not None:
                results.total_input_tokens = agent_result.total_input_tokens
                results.total_output_tokens = agent_result.total_output_tokens

            if not trial_handler.task.run_tests_in_same_shell:
                session = terminal.create_session(
                    "tests",
                    is_active_stream=self._livestream,
                    as_configured_user=False,
                )

            # ── Feedback loop: run tests, parse, repair if needed ──
            results.test_started_at = datetime.now(timezone.utc).isoformat()

            test_failure_mode = self._run_tests(
                terminal=terminal,
                session=session,
                trial_handler=trial_handler,
            )

            results.test_ended_at = datetime.now(timezone.utc).isoformat()

            post_test_pane = session.capture_pane(capture_entire=True)
            trial_handler.trial_paths.post_test_pane_path.write_text(post_test_pane)

            if not trial_handler.task.disable_asciinema:
                agent_recording_path = (
                    trial_handler.trial_paths.sessions_path / "agent.cast"
                )
                results.recording_path = str(
                    agent_recording_path.relative_to(self._output_path)
                )
                if agent_result is not None:
                    from terminal_bench.handlers.asciinema_handler import AsciinemaHandler
                    asciinema_handler = AsciinemaHandler(
                        markers=agent_result.timestamped_markers,
                        recording_path=agent_recording_path,
                    )
                    asciinema_handler.merge_markers()

            # Early return if test execution itself failed (timeout etc.)
            if (
                test_failure_mode != FailureMode.NONE
                and results.failure_mode == FailureMode.UNSET
            ):
                results.failure_mode = test_failure_mode
                self._call_receive_test_results(
                    task_agent,
                    parser_results=None,
                    is_resolved=False,
                    exhausted=True,
                    session=session,
                    terminal=terminal,
                )
                results.trial_ended_at = datetime.now(timezone.utc).isoformat()
                return results

            # Parse results inside the with block (container still alive)
            parser_results, parse_failure_mode = self._parse_results(
                trial_handler=trial_handler,
                post_test_pane=post_test_pane,
            )

            if parse_failure_mode != FailureMode.NONE:
                results.failure_mode = parse_failure_mode
                self._call_receive_test_results(
                    task_agent,
                    parser_results=None,
                    is_resolved=False,
                    exhausted=True,
                    session=session,
                    terminal=terminal,
                )
                results.trial_ended_at = datetime.now(timezone.utc).isoformat()
                return results

            is_resolved = self._is_resolved(parser_results)

            # ── Repair loop ──
            for repair_round in range(_MAX_REPAIRS + 1):
                if is_resolved:
                    self._logger.debug(
                        f"Task {trial_handler.task_id} resolved "
                        f"(round {repair_round})"
                    )
                    self._call_receive_test_results(
                        task_agent,
                        parser_results=parser_results,
                        is_resolved=True,
                        exhausted=False,
                        session=session,
                        terminal=terminal,
                    )
                    break

                if repair_round < _MAX_REPAIRS:
                    # FAIL — agent inspects and repairs
                    self._logger.debug(
                        f"Task {trial_handler.task_id} unresolved, "
                        f"repair round {repair_round + 1}/{_MAX_REPAIRS}"
                    )
                    self._call_receive_test_results(
                        task_agent,
                        parser_results=parser_results,
                        is_resolved=False,
                        exhausted=False,
                        session=session,
                        terminal=terminal,
                    )
                    # Retest
                    self._run_tests(
                        terminal=terminal,
                        session=session,
                        trial_handler=trial_handler,
                    )
                    post_test_pane = session.capture_pane(capture_entire=True)
                    parser_results, parse_failure_mode = self._parse_results(
                        trial_handler=trial_handler,
                        post_test_pane=post_test_pane,
                    )
                    if parse_failure_mode != FailureMode.NONE:
                        break
                    is_resolved = self._is_resolved(parser_results)
                else:
                    # Exhausted — final reflection on failure
                    self._logger.debug(
                        f"Task {trial_handler.task_id} unresolved, "
                        f"repairs exhausted ({_MAX_REPAIRS})"
                    )
                    self._call_receive_test_results(
                        task_agent,
                        parser_results=parser_results,
                        is_resolved=False,
                        exhausted=True,
                        session=session,
                        terminal=terminal,
                    )

            results.parser_results = parser_results
            results.is_resolved = is_resolved
            results.trial_ended_at = datetime.now(timezone.utc).isoformat()

            return results

    @staticmethod
    def _call_receive_test_results(
        task_agent,
        parser_results,
        is_resolved: bool,
        exhausted: bool,
        session,
        terminal,
    ):
        """Call receive_test_results if the agent supports it."""
        if not hasattr(task_agent, "receive_test_results"):
            return
        try:
            task_agent.receive_test_results(
                parser_results=parser_results,
                is_resolved=is_resolved,
                exhausted=exhausted,
                session=session,
                terminal=terminal,
            )
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(
                f"receive_test_results failed: {e}"
            )
```

- [ ] **Step 4: Run test to verify all 4 tests pass**

Run: `python -m pytest tests/test_feedback_harness.py -v --tb=short`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add tb/feedback_harness.py tests/test_feedback_harness.py
git commit -m "feat: add FeedbackHarness with test-result feedback loop"
```

---

### Task 2: CognitiveAgent — 新增 `receive_test_results` 方法

**Files:**
- Modify: `tb/agent/cognitive_agent.py`
- Test: `tests/test_feedback_harness.py` (append)

- [ ] **Step 1: Write failing test for receive_test_results**

在 `tests/test_feedback_harness.py` 末尾追加：

```python
class TestReceiveTestResults:
    """Test CognitiveAgent.receive_test_results method."""

    def _make_agent(self):
        """Create a CognitiveAgent with mocked internals."""
        from tb.agent.cognitive_agent import CognitiveAgent
        agent = CognitiveAgent.__new__(CognitiveAgent)
        agent._executor = MagicMock()
        agent._chain = MagicMock()
        agent._setup_done = True
        agent._task_meta = "original task instruction"
        return agent

    def test_receive_test_results_pass_calls_executor_and_returns(self):
        """On PASS, agent reflects via executor and returns."""
        from terminal_bench.parsers.base_parser import UnitTestStatus

        agent = self._make_agent()
        agent._executor.execute.return_value = {
            "notify_layers": {"l0_5_1": {"done": True, "result": "reflected"}},
            "action_text": "done",
        }

        mock_session = MagicMock()
        mock_session.capture_pane.return_value = "pane content"

        agent.receive_test_results(
            parser_results={"test_1": UnitTestStatus.PASSED},
            is_resolved=True,
            exhausted=False,
            session=mock_session,
            terminal=MagicMock(),
        )

        # Executor should have been called at least once
        assert agent._executor.execute.call_count >= 1

    def test_receive_test_results_fail_repair_calls_executor(self):
        """On FAIL (not exhausted), agent repairs via executor."""
        from terminal_bench.parsers.base_parser import UnitTestStatus

        agent = self._make_agent()
        agent._executor.execute.return_value = {
            "notify_layers": {"l0_5_1": {"done": True, "result": "fixed"}},
            "action_text": "done",
        }

        mock_session = MagicMock()
        mock_session.capture_pane.return_value = "pane content"

        agent.receive_test_results(
            parser_results={"test_1": UnitTestStatus.FAILED},
            is_resolved=False,
            exhausted=False,
            session=mock_session,
            terminal=MagicMock(),
        )

        assert agent._executor.execute.call_count >= 1

    def test_receive_test_results_exhausted_calls_executor(self):
        """On FAIL (exhausted), agent reflects on failure."""
        from terminal_bench.parsers.base_parser import UnitTestStatus

        agent = self._make_agent()
        agent._executor.execute.return_value = {
            "notify_layers": {"l0_5_1": {"done": True, "result": "learned"}},
            "action_text": "done",
        }

        mock_session = MagicMock()
        mock_session.capture_pane.return_value = "pane content"

        agent.receive_test_results(
            parser_results={"test_1": UnitTestStatus.FAILED},
            is_resolved=False,
            exhausted=True,
            session=mock_session,
            terminal=MagicMock(),
        )

        assert agent._executor.execute.call_count >= 1
```

- [ ] **Step 2: Run test to verify it fails (method not found)**

Run: `python -m pytest tests/test_feedback_harness.py::TestReceiveTestResults -v --tb=short`
Expected: FAIL with `AttributeError: 'CognitiveAgent' object has no attribute 'receive_test_results'`

- [ ] **Step 3: Implement `receive_test_results` on CognitiveAgent**

在 `tb/agent/cognitive_agent.py` 的 `CognitiveAgent` 类中，`perform_task` 方法之后、`_build_observation` 之前，插入：

```python
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
        """Called by FeedbackHarness after tests, while container is still alive.

        - PASS: agent reflects on success, calls record_learning, returns.
        - FAIL (not exhausted): agent inspects failures, repairs via tools.
        - FAIL (exhausted): agent reflects on failure, calls record_learning.
        """
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
```

同时在 `__init__` 中初始化 `_task_meta`：
```python
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._executor = None
        self._chain = None
        self._setup_done = False
        self._task_meta = ""
```

在 `perform_task` 方法中 `task_meta = (...)` 赋值块之后添加一行保存 task_meta 供反馈阶段使用：
```python
        self._task_meta = task_meta
```

- [ ] **Step 4: Run test to verify all 3 new tests pass**

Run: `python -m pytest tests/test_feedback_harness.py::TestReceiveTestResults -v --tb=short`
Expected: 3 passed

- [ ] **Step 5: Run full test suite to verify no regressions**

Run: `python -m pytest tests/test_feedback_harness.py -v --tb=short`
Expected: 7 passed (4 from Task 1 + 3 from Task 2)

- [ ] **Step 6: Commit**

```bash
git add tb/agent/cognitive_agent.py tests/test_feedback_harness.py
git commit -m "feat: add receive_test_results to CognitiveAgent for feedback loop"
```

---

### Task 3: Runner — Monkey-patch 入口

**Files:**
- Create: `tb/runner.py`
- Test: `tests/test_feedback_harness.py` (append)

- [ ] **Step 1: Write failing test for monkey-patch**

在 `tests/test_feedback_harness.py` 末尾追加：

```python
class TestRunnerPatch:
    """Test that tb.runner patches terminal_bench.Harness correctly."""

    def test_import_runner_patches_harness(self):
        """Importing tb.runner replaces terminal_bench.Harness with FeedbackHarness."""
        import terminal_bench
        from tb.feedback_harness import FeedbackHarness

        # Save original
        original = terminal_bench.Harness

        # Import runner module (triggers patch)
        import importlib
        import tb.runner as runner_mod
        importlib.reload(runner_mod)

        # Verify patch
        assert terminal_bench.Harness is FeedbackHarness

        # Also check the harness module is patched
        import terminal_bench.harness.harness as harness_mod
        assert harness_mod.Harness is FeedbackHarness

        # Restore original for other tests
        terminal_bench.Harness = original
        harness_mod.Harness = original
```

- [ ] **Step 2: Run test to verify it fails (module not found)**

Run: `python -m pytest tests/test_feedback_harness.py::TestRunnerPatch -v --tb=short`
Expected: FAIL with `ModuleNotFoundError: No module named 'tb.runner'`

- [ ] **Step 3: Create `tb/runner.py`**

```python
"""Monkey-patch entry point for Terminal-Bench with FeedbackHarness.

Usage:
    python -m tb.runner run --agent-import-path tb.agent.cognitive_agent:CognitiveAgent ...

Patches terminal_bench.Harness = FeedbackHarness before CLI import,
then invokes the Typer CLI app (same args as `tb run`).
"""
import sys

# Patch BEFORE importing any CLI module that does `from terminal_bench import Harness`
import terminal_bench
import terminal_bench.harness.harness as harness_mod

from tb.feedback_harness import FeedbackHarness

terminal_bench.Harness = FeedbackHarness
harness_mod.Harness = FeedbackHarness

# Now import and run the CLI
from terminal_bench.cli.tb.main import app

if __name__ == "__main__":
    app()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_feedback_harness.py::TestRunnerPatch -v --tb=short`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tb/runner.py tests/test_feedback_harness.py
git commit -m "feat: add tb/runner.py monkey-patch entry point for FeedbackHarness"
```

---

### Task 4: 更新 `tb/run.sh` 使用 runner 入口

**Files:**
- Modify: `tb/run.sh`

- [ ] **Step 1: Replace `tb run` with `python -m tb.runner run`**

在 `tb/run.sh` 中，将所有 `tb run \` 替换为 `python3.13 -m tb.runner run \`。

单任务模式 (line 33-40):
```bash
    python3.13 -m tb.runner run \
        --agent-import-path "$AGENT" \
        --dataset-path "$DATASET_PATH" \
        --task-id "$TASK_ID" \
        --output-path "$OUTPUT_DIR" \
        --n-concurrent 1 \
        --no-rebuild \
        --no-cleanup
```

批量模式 (line 55-61):
```bash
        python3.13 -m tb.runner run \
            --agent-import-path "$AGENT" \
            --dataset-path "$DATASET_PATH" \
            --task-id "$task" \
            --output-path "$OUTPUT_DIR" \
            --n-concurrent 1 \
            --no-cleanup
```

- [ ] **Step 2: Verify run.sh syntax**

Run: `bash -n tb/run.sh`
Expected: no output (syntax OK)

- [ ] **Step 4: Commit**

```bash
git add tb/run.sh
git commit -m "feat: switch run.sh to tb.runner entry point with task filtering"
```

---

### Task 4.5: 工具过滤 — `tb/env.py` + `TB_PHASE` 环境变量

**Files:**
- Create: `tb/env.py`
- Modify: `tb/agent/cognitive_agent.py` (`_ensure_setup`)
- Modify: `tb/run.sh` (`_run` 函数加 phase 参数)

Train 和 test 环境需要不同的工具集：
- **Train**：全部工具可用（`record_learning`, `kb_add`, `kb_fill_gap` 等）
- **Test**：禁用 `record_learning`, `kb_add`, `kb_fill_gap`

机制：`AgentContext(denied_tools={...})` → `LayerAgent.set_context(ctx)` → `_get_tools()` 动态过滤。无需重建 chain。

- [ ] **Step 1: Create `tb/env.py`**

```python
"""TB env helper — apply learning context to chain layers.

Uses existing AgentContext + set_context mechanism for dynamic tool filtering.
Train: all tools enabled.  Test: record_learning, kb_add, kb_fill_gap denied.
"""
from __future__ import annotations


def apply_learning_context(chain, enable: bool) -> None:
    """Apply tool context to all chain layers.

    Args:
        chain: Root layer node of the cognitive chain.
        enable: If True, all tools available (train mode).
                If False, record_learning/kb_add/kb_fill_gap denied (test mode).
    """
    from core.agent_context import AgentContext

    ctx = None
    if not enable:
        ctx = AgentContext(
            denied_tools={"record_learning", "kb_add", "kb_fill_gap"}
        )

    node = chain
    while node is not None:
        agent = getattr(node, '_agent', None)
        if agent is not None:
            agent.set_context(ctx)
        node = getattr(node, '_downstream', None)
```

- [ ] **Step 2: Wire `_ensure_setup()` to read `TB_PHASE`**

在 `tb/agent/cognitive_agent.py` 的 `_ensure_setup()` 方法中，`setup_executor` 调用之后添加：

```python
        self._chain, self._executor = setup_executor(_PROJECT_ROOT)

        # Apply learning context based on TB_PHASE env var
        import os
        phase = os.environ.get("TB_PHASE", "train")
        from tb.env import apply_learning_context
        apply_learning_context(self._chain, enable=(phase == "train"))
```

- [ ] **Step 3: Update `run.sh` `_run()` to pass `TB_PHASE`**

在 `tb/run.sh` 的 `_run()` 函数中，在 `tb run` 命令前加环境变量：

```bash
_run() {
    local task="$1"
    local phase="${2:-train}"
    echo "=== Running $task (phase=$phase) ==="
    TB_PHASE="$phase" python3.13 -m tb.runner run \
        --agent-import-path "$AGENT" \
        --dataset-path "$DATASET_PATH" \
        --task-id "$task" \
        --output-path "$OUTPUT_DIR" \
        --n-concurrent 1 \
        --no-rebuild \
        --no-cleanup
}
```

调用方：
- `_run "$task" "train"` — train tasks
- `_run "$task" "test"` — test tasks
- 单任务模式默认 `"train"`（`_run "$TASK_ID"` → phase 默认为 train）

在 case 语句中的调用也相应更新：train/test 子命令自动传 phase；类别子命令和全量模式不区分 phase（留空，默认 train）。

- [ ] **Step 4: Run test to verify context filtering**

Run: `python -m pytest tests/test_env.py -v --tb=short`
Expected: existing tests pass (no regression)

- [ ] **Step 5: Commit**

```bash
git add tb/env.py tb/agent/cognitive_agent.py tb/run.sh
git commit -m "feat: add TB_PHASE for train/test tool filtering via AgentContext"
```

---

### Task 5: 更新 MAINTAIN.md

**Files:**
- Modify: `MAINTAIN.md`

- [ ] **Step 1: Add changelog entry and tb/ module docs**

在 MAINTAIN.md Changelog 表格顶部添加：

```markdown
| 2026-06-23 | **TB 测试反馈机制**：新增 `tb/feedback_harness.py` — `FeedbackHarness(Harness)` 子类重写 `_run_trial`，将 `_parse_results` 移入 `with spin_up_terminal()` 块内，在容器存活期间插入修复循环（最多 3 轮修复）。`tb/agent/cognitive_agent.py` 新增 `receive_test_results()`/`_build_feedback_meta()` 方法 — 接收 pass/fail 结果驱动 Executor 反思/修复。新增 `tb/runner.py` — monkey-patch `terminal_bench.Harness = FeedbackHarness` 后调用 Typer CLI。`tb/run.sh` 改用 `python -m tb.runner run` 入口。 |
```

在 MAINTAIN.md 的 tb/ 模块表格中追加 `FeedbackHarness`、`receive_test_results`、`_build_feedback_meta`、`tb/runner.py` 条目。

- [ ] **Step 2: Commit**

```bash
git add MAINTAIN.md
git commit -m "docs: update MAINTAIN.md for TB test feedback mechanism"
```

---

### Task 6: 集成验证 — 跑 hello-world smoke test

**Files:** 无代码改动

- [ ] **Step 1: Run hello-world via new runner**

Run:
```bash
wsl -d Ubuntu-22.04 -- bash -c 'cd /mnt/c/Users/micha/PycharmProjects/cognitive-agent && bash tb/run.sh hello-world'
```
Expected: Agent runs, tests pass, `receive_test_results` called with `is_resolved=True`, agent reflects + record_learning. Check `tb/runs/*/hello-world/*/agent-logs/` for feedback round logs.

- [ ] **Step 2: Run heterogeneous-dates to verify repair loop**

Run:
```bash
wsl -d Ubuntu-22.04 -- bash -c 'cd /mnt/c/Users/micha/PycharmProjects/cognitive-agent && bash tb/run.sh heterogeneous-dates'
```
Expected: If first attempt fails, agent gets feedback, repairs, retests. Check logs for repair rounds.

- [ ] **Step 3: Verify results.json has correct is_resolved**

Check `tb/runs/*/results.json` — `is_resolved` should reflect final test outcome after repairs.
