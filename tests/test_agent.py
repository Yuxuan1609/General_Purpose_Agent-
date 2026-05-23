import pytest
from unittest.mock import MagicMock
from core.config import AgentConfig
from core.agent import CognitiveAgent


@pytest.fixture
def mock_agent_config(temp_dir):
    llm = MagicMock()
    resp = MagicMock()
    resp.has_tool_calls = False
    resp.text = "I have completed the task."
    llm.chat.return_value = resp

    rules_path = temp_dir / "l1_rules.json"
    rules_path.write_text('{"version":1,"rules":[]}')
    skills_dir = temp_dir / "skills"
    skills_dir.mkdir()
    (skills_dir / "general").mkdir()
    knowledge_dir = temp_dir / "knowledge"
    knowledge_dir.mkdir()
    (knowledge_dir / "general").mkdir()
    index_path = knowledge_dir / "l2_index.json"
    index_path.write_text('{"version":1,"chapters":[],"relations":[]}')

    return AgentConfig(
        main_llm=llm, auxiliary_llm=llm, max_iterations=10,
        l1_rules_path=rules_path, skills_dir=skills_dir,
        knowledge_dir=knowledge_dir, l2_index_path=index_path,
        seed_l1_rules=["test seed rule"],
    )


class TestCognitiveAgent:
    def test_agent_creation(self, mock_agent_config):
        agent = CognitiveAgent(mock_agent_config)
        assert agent.l1 is not None
        assert agent.l2 is not None
        assert agent.l3 is not None
        assert agent.meta is not None
        assert agent.layers is not None
        assert agent.loop is not None

    def test_agent_run(self, mock_agent_config):
        agent = CognitiveAgent(mock_agent_config)
        result = agent.run("Do a test task")
        assert result is not None
        assert result.iterations_used > 0

    def test_seed_data_injected(self, mock_agent_config):
        agent = CognitiveAgent(mock_agent_config)
        rules = agent.inspect_l1()
        assert any("test seed rule" in r.content for r in rules)
