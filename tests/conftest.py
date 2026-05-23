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
