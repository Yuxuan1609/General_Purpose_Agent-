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

from terminal_bench.harness.harness import Harness
from terminal_bench.harness.models import FailureMode, TrialResults
from terminal_bench.terminal.terminal import spin_up_terminal

_MAX_REPAIRS = 3


class FeedbackHarness(Harness):
    """Harness subclass with test-result feedback loop."""

    def _run_trial(self, trial_handler) -> TrialResults:
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
            docker_compose_path=trial_handler.task_paths.docker_compose_path,
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
                session=session, agent=task_agent, trial_handler=trial_handler,
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
                    "tests", is_active_stream=self._livestream, as_configured_user=False,
                )

            results.test_started_at = datetime.now(timezone.utc).isoformat()
            test_failure_mode = self._run_tests(
                terminal=terminal, session=session, trial_handler=trial_handler,
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

            if (
                test_failure_mode != FailureMode.NONE
                and results.failure_mode == FailureMode.UNSET
            ):
                results.failure_mode = test_failure_mode
                self._call_receive_test_results(
                    task_agent, parser_results=None,
                    is_resolved=False, exhausted=True,
                    session=session, terminal=terminal,
                )
                results.trial_ended_at = datetime.now(timezone.utc).isoformat()
                return results

            parser_results, parse_failure_mode = self._parse_results(
                trial_handler=trial_handler, post_test_pane=post_test_pane,
            )
            if parse_failure_mode != FailureMode.NONE:
                results.failure_mode = parse_failure_mode
                self._call_receive_test_results(
                    task_agent, parser_results=None,
                    is_resolved=False, exhausted=True,
                    session=session, terminal=terminal,
                )
                results.trial_ended_at = datetime.now(timezone.utc).isoformat()
                return results

            is_resolved = self._is_resolved(parser_results)

            for repair_round in range(_MAX_REPAIRS + 1):
                if is_resolved:
                    self._logger.debug(
                        f"Task {trial_handler.task_id} resolved (round {repair_round})"
                    )
                    self._call_receive_test_results(
                        task_agent, parser_results=parser_results,
                        is_resolved=True, exhausted=False,
                        session=session, terminal=terminal,
                    )
                    break

                if repair_round < _MAX_REPAIRS:
                    self._logger.debug(
                        f"Task {trial_handler.task_id} unresolved, "
                        f"repair round {repair_round + 1}/{_MAX_REPAIRS}"
                    )
                    self._call_receive_test_results(
                        task_agent, parser_results=parser_results,
                        is_resolved=False, exhausted=False,
                        session=session, terminal=terminal,
                    )
                    self._run_tests(
                        terminal=terminal, session=session, trial_handler=trial_handler,
                    )
                    post_test_pane = session.capture_pane(capture_entire=True)
                    parser_results, parse_failure_mode = self._parse_results(
                        trial_handler=trial_handler, post_test_pane=post_test_pane,
                    )
                    if parse_failure_mode != FailureMode.NONE:
                        break
                    is_resolved = self._is_resolved(parser_results)
                else:
                    self._logger.debug(
                        f"Task {trial_handler.task_id} unresolved, "
                        f"repairs exhausted ({_MAX_REPAIRS})"
                    )
                    self._call_receive_test_results(
                        task_agent, parser_results=parser_results,
                        is_resolved=False, exhausted=True,
                        session=session, terminal=terminal,
                    )

            results.parser_results = parser_results
            results.is_resolved = is_resolved
            results.trial_ended_at = datetime.now(timezone.utc).isoformat()
            return results

    @staticmethod
    def _call_receive_test_results(
        task_agent, parser_results, is_resolved, exhausted, session, terminal,
    ):
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
        except Exception:
            import logging
            logging.getLogger(__name__).warning(
                "receive_test_results failed", exc_info=True
            )
