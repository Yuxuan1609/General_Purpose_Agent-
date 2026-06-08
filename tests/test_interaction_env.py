import pytest
from core.env.interaction_env import InteractionEnv
from core.env.base import EnvState, EnvStep


class TestInteractionEnvReset:
    def test_reset_creates_session(self):
        env = InteractionEnv(system_prompt="You are helpful")
        state = env.reset("start chat")
        assert isinstance(state, EnvState)
        assert state.info.get("session_id")

    def test_reset_clears_history(self):
        env = InteractionEnv(system_prompt="You are helpful")
        env.reset("start")
        env.receive_input("hello")
        env.build_task_observation()
        env.step("hi")
        assert len(env.get_history()) == 2
        env.reset("restart")
        assert len(env.get_history()) == 0

    def test_sessions_have_different_ids(self):
        env = InteractionEnv(system_prompt="You are helpful")
        s1 = env.reset("start")
        s2 = env.reset("restart")
        assert s1.info["session_id"] != s2.info["session_id"]


class TestInteractionEnvReceiveBuild:
    def test_receive_input_stores_pending(self):
        env = InteractionEnv(system_prompt="You are helpful")
        env.reset("start")
        env.receive_input("hello world")
        obs = env.build_task_observation()
        assert obs is not None
        assert obs.state["current"] == "hello world"

    def test_build_task_observation_returns_none_when_no_input(self):
        env = InteractionEnv(system_prompt="You are helpful")
        env.reset("start")
        obs = env.build_task_observation()
        assert obs is None

    def test_build_task_observation_includes_history(self):
        env = InteractionEnv(system_prompt="You are helpful")
        env.reset("start")
        env.receive_input("hello")
        env.build_task_observation()
        env.step("hi")
        env.receive_input("how are you")
        obs = env.build_task_observation()
        assert obs is not None
        assert len(obs.state["conversation_history"]) == 2
        assert obs.state["conversation_history"][0] == {"role": "user", "content": "hello"}
        assert "[用户]: hello" in obs.state["history"]
        assert "[助手]: hi" in obs.state["history"]

    def test_build_task_observation_empty_history_string(self):
        env = InteractionEnv(system_prompt="You are helpful")
        env.reset("start")
        env.receive_input("first message")
        obs = env.build_task_observation()
        assert obs is not None
        assert obs.state["history"] == ""


class TestInteractionEnvStep:
    def test_step_records_exchange(self):
        env = InteractionEnv(system_prompt="You are helpful")
        env.reset("start")
        env.receive_input("hello")
        env.build_task_observation()
        result = env.step("hi there")
        assert isinstance(result, EnvStep)
        assert result.reward == 0
        assert result.done is False
        assert len(env.get_history()) == 2

    def test_step_displays_action_text(self):
        env = InteractionEnv(system_prompt="You are helpful")
        env.reset("start")
        env.receive_input("hello")
        env.build_task_observation()
        result = env.step("hi there")
        assert result.state.observation == "hi there"

    def test_step_clears_pending_input(self):
        env = InteractionEnv(system_prompt="You are helpful")
        env.reset("start")
        env.receive_input("hello")
        env.build_task_observation()
        env.step("hi")
        obs = env.build_task_observation()
        assert obs is None


class TestInteractionEnvSession:
    def test_session_info(self):
        env = InteractionEnv(system_prompt="You are helpful")
        env.reset("start")
        env.receive_input("hello")
        env.build_task_observation()
        env.step("hi")
        info = env.session_info()
        assert info["turns"] == 1
        assert isinstance(info["id"], str) and len(info["id"]) > 0
        assert isinstance(info["started_at"], str)

    def test_session_info_default_learning_true(self):
        env = InteractionEnv(system_prompt="You are helpful")
        env.reset("start")
        info = env.session_info()
        assert info["enable_learning"] is True

    def test_session_info_learning_false(self):
        env = InteractionEnv(system_prompt="You are helpful", enable_learning=False)
        env.reset("start")
        info = env.session_info()
        assert info["enable_learning"] is False

    def test_session_metadata_in_task_obs(self):
        env = InteractionEnv(system_prompt="You are helpful")
        env.reset("start")
        env.receive_input("hello")
        obs = env.build_task_observation()
        assert obs is not None
        assert obs.session["domain"] == "interaction"
        assert obs.session["domains_hint"] == ["interaction"]
        assert obs.meta == "You are helpful"
        assert obs.session["enable_learning"] is True
        assert obs.session["step_index"] == 0

    def test_step_index_increments(self):
        env = InteractionEnv(system_prompt="You are helpful")
        env.reset("start")
        env.receive_input("t1")
        obs1 = env.build_task_observation()
        env.step("r1")
        env.receive_input("t2")
        obs2 = env.build_task_observation()
        assert obs1.session["step_index"] == 0
        assert obs2.session["step_index"] == 1


class TestInteractionEnvHistory:
    def test_get_history_is_copy(self):
        env = InteractionEnv(system_prompt="You are helpful")
        env.reset("start")
        env.receive_input("hello")
        env.build_task_observation()
        env.step("hi")
        h = env.get_history()
        h.append({"role": "user", "content": "extra"})
        assert len(env.get_history()) == 2

    def test_format_history_multi_turn(self):
        env = InteractionEnv(system_prompt="You are helpful")
        env.reset("start")
        env.receive_input("hello")
        env.build_task_observation()
        env.step("hi")
        env.receive_input("weather?")
        obs = env.build_task_observation()
        expected = "[用户]: hello\n[助手]: hi"
        assert obs.state["history"] == expected
