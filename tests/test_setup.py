# tests/test_setup.py
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock


def test_setup_executor_returns_chain_and_executor(tmp_path, monkeypatch):
    """setup_executor 应返回 (chain, executor) 元组并注册到 runtime_registry。"""
    # Mock 重依赖以避免真实 LLM/加载
    mock_llm = MagicMock()
    mock_chain = MagicMock(name="chain")
    mock_executor = MagicMock(name="executor")

    with patch("core.setup.load_env") as mock_load_env, \
         patch("core.setup.build_llm_client", return_value=mock_llm), \
         patch("core.setup.build_default_chain", return_value=mock_chain), \
         patch("core.setup.Executor", return_value=mock_executor), \
         patch("core.setup.register_runtime") as mock_register:
        from core.setup import setup_executor
        chain, executor = setup_executor(project_root=tmp_path)

    assert chain is mock_chain
    assert executor is mock_executor
    mock_load_env.assert_called_once_with(tmp_path)
    mock_register.assert_called_once_with(mock_chain, mock_executor)


def test_setup_executor_defaults_project_root(monkeypatch):
    """不传 project_root 时使用 setup.py 所在目录的 parent。"""
    with patch("core.setup.load_env"), \
         patch("core.setup.build_llm_client", return_value=MagicMock()), \
         patch("core.setup.build_default_chain", return_value=MagicMock()), \
         patch("core.setup.Executor", return_value=MagicMock()), \
         patch("core.setup.register_runtime"):
        from core.setup import setup_executor
        setup_executor()  # 不应抛异常
