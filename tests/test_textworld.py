import pytest
import json
from core.env.base import Environment, EnvState, EnvStep


class TestTextWorldEnvInterface:
    def test_implements_environment_abc(self):
        from core.env.textworld import TextWorldEnv
        assert issubclass(TextWorldEnv, Environment)

    def test_cannot_instantiate_abstract(self):
        with pytest.raises(TypeError):
            Environment()

    def test_generate_game_returns_path(self):
        from core.env.textworld import TextWorldEnv
        path = TextWorldEnv.generate_game(
            world_size=3, nb_objects=5, quest_length=3, seed=42,
        )
        assert str(path).endswith(".z8")


class TestWSLBridgeProtocol:
    def test_reset_request_format(self):
        from core.env.textworld import WSLBridge
        msg = WSLBridge._make_request("reset")
        parsed = json.loads(msg)
        assert parsed == {"type": "reset"}

    def test_step_request_format(self):
        from core.env.textworld import WSLBridge
        msg = WSLBridge._make_request("step", action="open door")
        parsed = json.loads(msg)
        assert parsed == {"type": "step", "action": "open door"}

    def test_parse_state_response(self):
        from core.env.textworld import WSLBridge
        raw = '{"observation": "You see a door.", "infos": {"score": 0}}'
        state = WSLBridge._parse_response(raw)
        assert state["observation"] == "You see a door."
        assert state["infos"]["score"] == 0

    def test_parse_step_response(self):
        from core.env.textworld import WSLBridge
        raw = '{"observation": "Door opened.", "reward": 10.0, "done": true, "infos": {}}'
        result = WSLBridge._parse_response(raw)
        assert result["observation"] == "Door opened."
        assert result["reward"] == 10.0
        assert result["done"] is True

    def test_parse_invalid_response_raises(self):
        from core.env.textworld import WSLBridge, TextWorldError
        with pytest.raises(TextWorldError):
            WSLBridge._parse_response("not valid json")

    def test_parse_error_response_raises(self):
        from core.env.textworld import WSLBridge, TextWorldError
        raw = '{"error": "Game file not found"}'
        with pytest.raises(TextWorldError, match="Game file not found"):
            WSLBridge._parse_response(raw)


class TestWSLBridgeIntegration:
    def test_bridge_detect_wsl(self):
        from core.env.textworld import is_wsl_available
        result = is_wsl_available()
        assert isinstance(result, bool)
