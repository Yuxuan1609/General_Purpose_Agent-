import pytest
from core.env.base import Environment, EnvState, EnvStep


class FakeEnv(Environment):
    def reset(self, task_description: str) -> EnvState:
        return EnvState(observation="Start", info={})

    def step(self, action: str) -> EnvStep:
        return EnvStep(state=EnvState(observation="next", info={}), reward=1.0, done=True)


class TestEnvInterface:
    def test_reset_returns_state(self):
        env = FakeEnv()
        state = env.reset("find the key")
        assert state.observation == "Start"

    def test_step_returns_step(self):
        env = FakeEnv()
        env.reset("test")
        s = env.step("open door")
        assert s.reward == 1.0
        assert s.done is True

    def test_cannot_instantiate_abstract(self):
        with pytest.raises(TypeError):
            Environment()
