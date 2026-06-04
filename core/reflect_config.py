# --- REFACTOR: LearningEnv ---
# Old reflection config loader. Recyclable: schema definitions → LearningEnv domain
# config (learning/reflect/compile domain configs under data/layers/knowledge/learning/).
"""Reflection config loader — reads config/reflect.yaml into structured dicts."""
import yaml
from pathlib import Path
from dataclasses import dataclass, field


@dataclass
class ReflectConfig:
    l1: dict = field(default_factory=dict)
    l2: dict = field(default_factory=dict)
    l3: dict = field(default_factory=dict)

    @classmethod
    def from_yaml(cls, path: Path) -> "ReflectConfig":
        with open(path, encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
        return cls(
            l1=raw.get("l1", {}),
            l2=raw.get("l2", {}),
            l3=raw.get("l3", {}),
        )

    def proposer_schema(self, layer: str) -> dict:
        return getattr(self, layer, {}).get("proposer", {}).get("schema", {})

    def proposer_system(self, layer: str) -> str:
        return getattr(self, layer, {}).get("proposer", {}).get("system_template", "")

    def proposer_user(self, layer: str) -> str:
        return getattr(self, layer, {}).get("proposer", {}).get("user_template", "")

    def proposer_criteria(self, layer: str) -> str:
        return getattr(self, layer, {}).get("proposer", {}).get("criteria", "")

    def verifier_schema(self, layer: str) -> dict:
        return getattr(self, layer, {}).get("verifier", {}).get("schema", {})

    def verifier_system(self, layer: str) -> str:
        return getattr(self, layer, {}).get("verifier", {}).get("system_template", "")

    def verifier_user(self, layer: str) -> str:
        return getattr(self, layer, {}).get("verifier", {}).get("user_template", "")


def load_reflect_config() -> ReflectConfig:
    config_path = Path(__file__).resolve().parent.parent / "config" / "layers" / "reflect.yaml"
    return ReflectConfig.from_yaml(config_path)
