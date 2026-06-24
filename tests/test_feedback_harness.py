"""Tests for FeedbackHarness repair loop logic.

Mocks TB internals to verify the feedback loop runs the correct number
of rounds and calls receive_test_results with the right arguments.
"""
from unittest.mock import MagicMock, patch
import pytest


class TestFeedbackHarnessLoop:
    """Test the repair loop in isolation by mocking all TB internals."""

    def _make_mock_harness(self):
        """Create a FeedbackHarness with all dependencies mocked."""
        from tb.feedback_harness import FeedbackHarness
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
        """When tests pass on first try, receive_test_results called once."""
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

        harness._run_tests = MagicMock(return_value=FailureMode.NONE)
        harness._parse_results = MagicMock(
            return_value=({"test_1": UnitTestStatus.PASSED}, FailureMode.NONE)
        )
        harness._is_resolved = MagicMock(return_value=True)

        harness._run_trial(handler)

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
        """When tests fail first, then pass after repair, 2 test cycles."""
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

        harness._run_tests = MagicMock(
            side_effect=[FailureMode.NONE, FailureMode.NONE]
        )
        fail_result = ({"test_1": UnitTestStatus.FAILED}, FailureMode.NONE)
        pass_result = ({"test_1": UnitTestStatus.PASSED}, FailureMode.NONE)
        harness._parse_results = MagicMock(
            side_effect=[fail_result, pass_result]
        )
        harness._is_resolved = MagicMock(side_effect=[False, True])

        harness._run_trial(handler)

        assert harness._run_tests.call_count == 2
        assert mock_agent.receive_test_results.call_count == 2
        first = mock_agent.receive_test_results.call_args_list[0]
        assert first.kwargs["is_resolved"] is False
        assert first.kwargs["exhausted"] is False
        second = mock_agent.receive_test_results.call_args_list[1]
        assert second.kwargs["is_resolved"] is True

    @patch('tb.feedback_harness.spin_up_terminal')
    @patch('tb.feedback_harness.Harness._run_agent')
    @patch('tb.feedback_harness.Harness._create_agent_for_task')
    def test_fail_3_repairs_exhausted(
        self, mock_create_agent, mock_run_agent, mock_spin_up
    ):
        """When tests fail all 4 rounds, final call has exhausted=True."""
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

        harness._run_tests = MagicMock(return_value=FailureMode.NONE)
        fail_result = ({"test_1": UnitTestStatus.FAILED}, FailureMode.NONE)
        harness._parse_results = MagicMock(return_value=fail_result)
        harness._is_resolved = MagicMock(return_value=False)

        harness._run_trial(handler)

        assert harness._run_tests.call_count == 4
        assert mock_agent.receive_test_results.call_count == 4
        for i in range(3):
            c = mock_agent.receive_test_results.call_args_list[i]
            assert c.kwargs["is_resolved"] is False
            assert c.kwargs["exhausted"] is False
        last = mock_agent.receive_test_results.call_args_list[3]
        assert last.kwargs["is_resolved"] is False
        assert last.kwargs["exhausted"] is True

    @patch('tb.feedback_harness.spin_up_terminal')
    @patch('tb.feedback_harness.Harness._run_agent')
    @patch('tb.feedback_harness.Harness._create_agent_for_task')
    def test_agent_without_receive_test_results_does_not_crash(
        self, mock_create_agent, mock_run_agent, mock_spin_up
    ):
        """Agents without receive_test_results work fine (backward compat)."""
        from terminal_bench.parsers.base_parser import UnitTestStatus
        from terminal_bench.agents.base_agent import AgentResult
        from terminal_bench.harness.models import FailureMode

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

        result = harness._run_trial(handler)
        assert result is not None


class TestReceiveTestResults:
    """Test CognitiveAgent.receive_test_results method."""

    def _make_agent(self):
        """Create a CognitiveAgent with mocked internals."""
        from unittest.mock import MagicMock
        from tb.agent.cognitive_agent import CognitiveAgent
        agent = CognitiveAgent.__new__(CognitiveAgent)
        agent._executor = MagicMock()
        agent._chain = MagicMock()
        agent._setup_done = True
        agent._task_meta = "original task instruction"
        return agent

    def test_receive_test_results_pass_calls_executor(self):
        from unittest.mock import MagicMock
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
            is_resolved=True, exhausted=False,
            session=mock_session, terminal=MagicMock(),
        )
        assert agent._executor.execute.call_count >= 1

    def test_receive_test_results_fail_repair_calls_executor(self):
        from unittest.mock import MagicMock
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
            is_resolved=False, exhausted=False,
            session=mock_session, terminal=MagicMock(),
        )
        assert agent._executor.execute.call_count >= 1

    def test_receive_test_results_exhausted_calls_executor(self):
        from unittest.mock import MagicMock
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
            is_resolved=False, exhausted=True,
            session=mock_session, terminal=MagicMock(),
        )
        assert agent._executor.execute.call_count >= 1
