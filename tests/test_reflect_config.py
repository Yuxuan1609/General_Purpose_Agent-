# REFACTOR: LearningEnv — tests old reflect config. Will be replaced by LearningEnv domain config tests.
import pytest
from core.reflect_config import ReflectConfig, load_reflect_config


class TestReflectConfig:
    def test_loads_l1_proposer_schema(self):
        cfg = load_reflect_config()
        l1 = cfg.l1
        assert "proposer" in l1
        assert "schema" in l1["proposer"]
        assert "self_fixes" in l1["proposer"]["schema"]

    def test_loads_l2_verifier_schema(self):
        cfg = load_reflect_config()
        l2 = cfg.l2
        assert "verifier" in l2
        assert "schema" in l2["verifier"]
        assert "verified" in l2["verifier"]["schema"]

    def test_all_three_layers_configured(self):
        cfg = load_reflect_config()
        for layer in ["l1", "l2", "l3"]:
            layer_cfg = getattr(cfg, layer)
            assert "proposer" in layer_cfg
            assert "verifier" in layer_cfg

    def test_templates_contain_placeholders(self):
        cfg = load_reflect_config()
        for layer_name in ["l1", "l2", "l3"]:
            layer_cfg = getattr(cfg, layer_name)
            p_usr = layer_cfg["proposer"]["user_template"]
            assert "{refiner_reasoning}" in p_usr

    def test_convenience_methods(self):
        cfg = load_reflect_config()
        assert "add_rule" in str(cfg.proposer_schema("l1"))
        assert "L1 反思标准" in cfg.proposer_criteria("l1")
