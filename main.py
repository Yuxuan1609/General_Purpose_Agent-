"""Cognitive Agent — entry point."""
import yaml
import os
from pathlib import Path
from openai import OpenAI
from core.config import AgentConfig
from core.llm_client import LLMClient
from core.agent import CognitiveAgent


def _load_env():
    """Load .env file if present. Override via system env vars."""
    env_path = Path(__file__).parent / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key, val = key.strip(), val.strip()
            if key not in os.environ:
                os.environ[key] = val


def _make_llm(cfg: dict) -> LLMClient:
    base_url = cfg.get("base_url", "https://api.deepseek.com")
    api_key = os.environ.get(cfg.get("api_key_env", "DEEPSEEK_API_KEY"), "")
    return LLMClient(OpenAI(base_url=base_url, api_key=api_key), cfg.get("model", "deepseek-chat"))


def load_config(config_path: str = "config.yaml") -> AgentConfig:
    _load_env()

    with open(config_path) as f:
        raw = yaml.safe_load(f)

    main_llm = _make_llm(raw.get("main_llm", {}))
    aux_llm = _make_llm(raw.get("auxiliary_llm", {}))

    return AgentConfig(
        main_llm=main_llm, auxiliary_llm=aux_llm,
        max_iterations=raw.get("max_iterations", 50),
        l1_max_rules=raw.get("l1_max_rules", 20),
        l1_max_rule_length=raw.get("l1_max_rule_length", 100),
        l1_rules_path=Path(raw.get("l1_rules_path", "./data/l1_rules.json")),
        skills_dir=Path(raw.get("skills_dir", "./skills")),
        knowledge_dir=Path(raw.get("knowledge_dir", "./knowledge")),
        l2_index_path=Path(raw.get("l2_index_path", "./knowledge/l2_index.json")),
        seed_l1_rules=raw.get("seed_l1_rules"),
        seed_l2_cards=raw.get("seed_l2_cards"),
    )


if __name__ == "__main__":
    import sys
    config = load_config()
    agent = CognitiveAgent(config)
    print("Cognitive Agent ready.")
    print(f"L1 rules: {len(agent.inspect_l1())}")
    print(f"L3 skills: {len(agent.inspect_l3())}")
    if len(sys.argv) > 1:
        result = agent.run(" ".join(sys.argv[1:]))
        print(f"\nResult: {result.final_response[:500]}")
        print(f"Iterations: {result.iterations_used}")
        print(f"New L2 cards: {result.new_knowledge_cards}")
