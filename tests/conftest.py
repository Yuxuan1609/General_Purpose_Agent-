import pytest
from pathlib import Path
import tempfile
import os

@pytest.fixture
def temp_dir():
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)

@pytest.fixture
def sample_domain():
    from core.task import Domain
    return Domain(path="textworld/map_A", level="specific")

@pytest.fixture
def general_domain():
    from core.task import Domain
    return Domain(path="general", level="general")

@pytest.fixture
def mock_llm_client():
    from unittest.mock import MagicMock
    client = MagicMock()
    client.chat.return_value = MagicMock()
    client.chat.return_value.has_tool_calls = False
    client.chat.return_value.text = "Mock response"
    return client


@pytest.fixture
def domain_registry():
    from core.domain_registry import DomainRegistry
    reg = DomainRegistry()
    reg.add_node("general", None, "通用领域")
    reg.add_node("game/leduc", "game", "Leduc Hold'em")
    reg.add_node("game/doudizhu", "game", "斗地主")
    reg.add_node("learning/reflect", "general", "学习反思")
    reg.add_node("learning/consolidate", "learning/reflect", "知识整理")
    return reg
