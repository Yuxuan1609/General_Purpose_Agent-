import os
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
from main import load_config
from core.llm_client import LLMClient


class TestLoadConfig:
    def test_load_config_returns_llm_client(self, tmp_path):
        config_file = tmp_path / "config.yaml"
        config_file.write_text("""
main_llm:
  provider: deepseek
  model: deepseek-chat
  api_key_env: TEST_KEY
  base_url: https://test.api.com
auxiliary_llm:
  provider: deepseek
  model: deepseek-chat
  api_key_env: TEST_KEY
  base_url: https://test.api.com
max_iterations: 10
""")
        os.environ["TEST_KEY"] = "fake-key"
        try:
            with patch("main.OpenAI") as mock_openai:
                cfg = load_config(str(config_file))
                assert isinstance(cfg.main_llm, LLMClient)
                assert isinstance(cfg.auxiliary_llm, LLMClient)
                assert cfg.main_llm.model == "deepseek-chat"
        finally:
            del os.environ["TEST_KEY"]
