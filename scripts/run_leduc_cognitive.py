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

    fmt = logging.Formatter("%(asctime)s | %(message)s")

    # Suppress http noise (already handled by setup_layer_logging)
    # Console: INFO only
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(logging.Formatter("%(asctime)s  %(message)s"))
    root.addHandler(ch)

    # Per-agent file handlers via shared utility
    from core.layers.logging_setup import setup_layer_logging
    setup_layer_logging(log_dir)

    # Game summary log
    game_logger = logging.getLogger("leduc_cognitive")
    game_logger.setLevel(logging.DEBUG)
    game_fh = logging.FileHandler(str(log_dir / "game.log"), encoding="utf-8")
    game_fh.setLevel(logging.DEBUG)
    game_fh.setFormatter(fmt)
    game_logger.addHandler(game_fh)

    return log_dir


def _load_env():
    from core.env_loader import load_env
    load_env(PROJECT_ROOT)


def build_llm_client(model=None, temperature=0.1):
    from core.llm_factory import build_llm_client as _build
    return _build(PROJECT_ROOT / "config.yaml", model=model, temperature=temperature)


def build_chain(auxiliary_llm=None):
    from core.chain_factory import build_default_chain
    return build_default_chain(PROJECT_ROOT, auxiliary_llm=auxiliary_llm, seed=True)


def _seed_knowledge(fk, phil, sl=None):
    """Deprecated — use core.seed_knowledge.seed_knowledge()."""
    from core.seed_knowledge import seed_knowledge
    seed_knowledge(fk, phil, sl)


def _seed_knowledge(fk, phil, sl=None):
    """Deprecated — use core.seed_knowledge.seed_knowledge()."""
    from core.seed_knowledge import seed_knowledge
    seed_knowledge(fk, phil, sl)


def _run_learning_cycle(log_dir, llm_client, chain, executor,
                        pending_dir, phil, fk, sl, pre_win_rate=0.0):
    """Phase 2.2: run learning env cycle after game batch."""
    from core.env.learning_env import LearningEnv
    from core.env.threshold_scorer import ThresholdScorer
    import json

    logger.info("")
    logger.info("=" * 55)
    logger.info("  Learning cycle triggered")
    logger.info("=" * 55)

    knowledge = {"l1": phil, "l2": fk, "l3": sl}
    stats_file = PROJECT_ROOT / "data" / "learning" / "learning_stats.json"
    lenv = LearningEnv(pending_dir, knowledge,
                       preprocessing_llm=llm_client,
                       stats_file=stats_file)

    # Step 1: reset -> build observation
    state = lenv.reset("learn from recent leduc games")
    if not state.observation:
        logger.info("No pending records to learn from")
        return

    # Step 2: build TaskObservation for Agent
    obs = lenv.build_task_observation()
    if obs is None:
        logger.warning("Failed to build learning task observation")
        return

    logger.info("Learning task: %d chars meta, %d records pending",
                len(obs.meta), len(obs.state.get("learning_units", [])))

    # Step 3: Agent processes via Executor + Layers
    logger.info("Dispatching learning task to Agent...")
    result = executor.execute(obs)
    notify_layers = result.get("notify_layers", {})

    # Step 4: LearningEnv applies the modifications
    action_json = json.dumps(notify_layers, ensure_ascii=False, default=str)
    step = lenv.step(action_json)

    logger.info("Learning step result: %s", step.state.observation)
    logger.info("Reward: %.1f, Done: %s", step.reward, step.done)

    # Step 5: Archive consumed pending records
    moved = lenv.archive_pending()
    logger.info("Archived %d pending files -> learned/", moved)

    # Step 6: Print knowledge change summary
    rules = phil.all_rules()
    logger.info("Post-learn: L1 rules=%d L2 cards=%d L3 skills=%d",
                len(rules), len(fk.cards), len(sl.list_all()))


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
    chain = build_chain(auxiliary_llm=llm_client)

    from core.executor import Executor
    executor = Executor(layer_root=chain, llm_client=llm_client,
                        learning_dir=PROJECT_ROOT / "data" / "learning")
    chain._consol_ctx.executor = executor

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
        agent.reset_session(f"leduc_ep{ep}")

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
                logger.info("  Step %d | hand=%s public=%s legal=%s -> %s",
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

    summary = [
        "",
        "=" * 55,
        "  Leduc Hold'em -- Cognitive Agent Results",
        "=" * 55,
        f"  Episodes:    {args.episodes}",
        f"  Total Score: {total_reward:+.1f} chips",
        f"  Avg/Ep:      {avg_reward:+.2f} chips",
        f"  Win Rate:    {win_rate*100:.0f}% ({wins}/{args.episodes})",
        f"  Avg Steps:   {avg_steps:.1f}",
        f"  Log:         {log_dir / 'game.log'}",
        "=" * 55,
    ]
    for line in summary:
        print(line)
        logger.info(line)

    # ── Phase 2.2: Learning cycle ────────────────────────────────────
    from core.env.threshold_scorer import ThresholdScorer
    pending_dir = PROJECT_ROOT / "data" / "learning" / "pending"
    scorer = ThresholdScorer(pending_dir)
    if scorer.should_trigger("game/leduc"):
        _run_learning_cycle(log_dir, llm_client, chain, executor,
                            pending_dir, phil, fk, sl,
                            pre_win_rate=win_rate)
    else:
        logger.info("Learning not triggered (below threshold)")


if __name__ == "__main__":
    main()
