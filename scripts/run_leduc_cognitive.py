"""
Leduc Hold'em Cognitive Agent — 接入完整认知链

用法:
  python scripts/run_leduc_cognitive.py
  python scripts/run_leduc_cognitive.py --episodes 5
"""
import argparse
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

PROJECT_ROOT = Path(__file__).resolve().parent.parent

_ch = logging.StreamHandler(sys.stdout)
_ch.setLevel(logging.INFO)
_ch.setFormatter(logging.Formatter("%(asctime)s  %(message)s"))
logging.basicConfig(level=logging.INFO, handlers=[_ch])
logger = logging.getLogger("leduc_cognitive")


def _setup_logging():
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_dir = PROJECT_ROOT / "logs" / "leduc_cognitive" / stamp
    log_dir.mkdir(parents=True, exist_ok=True)
    fh = logging.FileHandler(log_dir / "game.log", encoding="utf-8")
    fh.setLevel(logging.INFO)
    fh.setFormatter(logging.Formatter("%(asctime)s  %(message)s"))
    logger.addHandler(fh)
    return log_dir


def _load_env():
    env_path = PROJECT_ROOT / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key, val = key.strip(), val.strip()
            if key not in os.environ:
                os.environ[key] = val


def build_llm_client(model=None, temperature=0.1):
    import yaml
    from openai import OpenAI
    from core.llm_client import LLMClient

    _load_env()
    with open(PROJECT_ROOT / "config.yaml", encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    cfg = raw.get("main_llm", {})
    base_url = cfg.get("base_url", "https://api.deepseek.com")
    api_key = os.environ.get(cfg.get("api_key_env", "DEEPSEEK_API_KEY"), "")
    oai = OpenAI(base_url=base_url, api_key=api_key)
    llm = LLMClient(oai, model or cfg.get("model", "deepseek-v4-flash"))
    llm.temperature = temperature
    return llm


def build_chain():
    from core.meta_driver import MetaDriver, DEFAULT_TRIGGERS, DEFAULT_VALIDATORS
    from core.philosophy import Philosophy
    from core.flexible_knowledge import FlexibleKnowledge
    from core.skill_layer import SkillLayer
    from core.tools.registry import ToolRegistry
    from core.layers import build_chain

    meta = MetaDriver(DEFAULT_TRIGGERS.copy(), DEFAULT_VALIDATORS.copy())
    phil = Philosophy(PROJECT_ROOT / "data" / "l1_rules.json")
    fk = FlexibleKnowledge(PROJECT_ROOT / "knowledge", PROJECT_ROOT / "knowledge" / "l2_index.json")
    sl = SkillLayer(PROJECT_ROOT / "skills", ToolRegistry())
    return build_chain(meta, phil, fk, sl)


def main():
    parser = argparse.ArgumentParser(description="Leduc Cognitive Agent")
    parser.add_argument("--episodes", type=int, default=3, help="对局数 (default: 3)")
    parser.add_argument("--temperature", type=float, default=0.1)
    parser.add_argument("--verbose", action="store_true", help="输出每步详情")
    args = parser.parse_args()

    log_dir = _setup_logging()
    logger.info("Config: episodes=%d temperature=%.1f log=%s",
                args.episodes, args.temperature, log_dir)

    _load_env()
    llm_client = build_llm_client(temperature=args.temperature)
    chain = build_chain()

    from core.executor import Executor
    executor = Executor(layer_root=chain, llm_client=llm_client,
                        learning_dir=PROJECT_ROOT / "data" / "learning")

    from scripts.leduc_cognitive_agent import LeducCognitiveAgent
    agent = LeducCognitiveAgent(executor, temperature=args.temperature)

    import rlcard
    from rlcard.models.registration import model_registry

    env = rlcard.make("leduc-holdem")
    cfr = model_registry.load("leduc-holdem-cfr").agent

    total_reward = 0
    wins = 0
    step_counts = []

    for ep in range(1, args.episodes + 1):
        env.set_agents([agent, cfr])
        state, player_id = env.reset()
        step = 0

        logger.info("=== Episode %d ===", ep)
        while not env.is_over():
            if player_id == 0:
                action_id, _ = agent.eval_step(state)
            else:
                result = cfr.eval_step(state)
                action_id = result[0] if isinstance(result, tuple) else result

            if args.verbose:
                raw = state["raw_obs"]
                legal = raw["legal_actions"]
                action_idx = action_id if isinstance(action_id, int) else 0
                action_label = legal[action_idx] if action_idx < len(legal) else "?"
                logger.info("  Step %d | hand=%s public=%s legal=%s → %s",
                           step, raw.get("hand"), raw.get("public_card"),
                           legal, action_label)

            state, player_id = env.step(action_id)
            step += 1

        payoffs = env.get_payoffs()
        reward = payoffs[0]
        total_reward += reward
        step_counts.append(step)
        if reward > 0:
            wins += 1

        logger.info("  Result: reward=%+.1f chips | steps=%d", reward, step)

    avg_reward = total_reward / args.episodes
    win_rate = wins / args.episodes
    avg_steps = sum(step_counts) / len(step_counts)

    print()
    print("=" * 55)
    print("  Leduc Hold'em — Cognitive Agent Results")
    print("=" * 55)
    print(f"  Episodes:    {args.episodes}")
    print(f"  Total Score: {total_reward:+.1f} chips")
    print(f"  Avg/Ep:      {avg_reward:+.2f} chips")
    print(f"  Win Rate:    {win_rate*100:.0f}% ({wins}/{args.episodes})")
    print(f"  Avg Steps:   {avg_steps:.1f}")
    print(f"  Log:         {log_dir / 'game.log'}")
    print("=" * 55)


if __name__ == "__main__":
    main()
