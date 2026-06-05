"""
DouZero + LLM Agent 对局脚本 — Phase 1b

用法:
  python scripts/run_douzero_llm.py                                    # 默认: LLM 为地主上家 vs DouZero-ADP
  python scripts/run_douzero_llm.py --position landlord                # LLM 做地主
  python scripts/run_douzero_llm.py --episodes 10 --objective adp      # 10局 ADP计分
  python scripts/run_douzero_llm.py --llm_position landlord_up          # LLM为地主上家
  python scripts/run_douzero_llm.py --opponent random                   # 对手改为随机 (快速测试)
  python scripts/run_douzero_llm.py --dry-run                           # 不调LLM，用随机Agent替代(测试流程)
"""
import argparse
import logging
import os
import random
import sys
from datetime import datetime
from pathlib import Path

import numpy as np

LOG_DIR = Path(__file__).resolve().parent.parent / "logs"

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

DZ_ROOT = PROJECT_ROOT / "DouZero-1.1.0" / "DouZero-1.1.0"
sys.path.insert(0, str(DZ_ROOT))

from douzero.env.game import GameEnv
from douzero.env.env import deck as DECK

_ch = logging.StreamHandler(sys.stdout)
_ch.setLevel(logging.INFO)
_ch.setFormatter(logging.Formatter("%(asctime)s  %(message)s"))

logging.basicConfig(level=logging.INFO, handlers=[_ch])
logger = logging.getLogger("douzero_llm")


def _setup_file_logging(task_label: str):
    """Create timestamped log dir under logs/{task_label}/ and add file handler."""
    label = task_label.strip("/\\").replace(" ", "_")
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_dir = LOG_DIR / label / stamp
    log_dir.mkdir(parents=True, exist_ok=True)

    fh = logging.FileHandler(log_dir / "game.log", encoding="utf-8")
    fh.setLevel(logging.INFO)
    fh.setFormatter(logging.Formatter("%(asctime)s  %(message)s"))
    logger.addHandler(fh)

    logger.info("Run folder: %s", log_dir)
    return log_dir


def _shuffle_deck(seed: int | None = None):
    if seed is not None:
        np.random.seed(seed)
    d = DECK.copy()
    np.random.shuffle(d)
    return d


def _gen_game_data(deck):
    return {
        'landlord':      sorted(deck[:20]),
        'landlord_up':   sorted(deck[20:37]),
        'landlord_down': sorted(deck[37:54]),
        'three_landlord_cards': sorted(deck[17:20]),
    }


def _load_douzero_model(position: str, model_dir: str, objective: str):
    """Load a DouZero .ckpt model for the given position."""
    ckpt_path = os.path.join(model_dir, f"{position}.ckpt")
    if not os.path.isfile(ckpt_path):
        raise FileNotFoundError(f"Model not found: {ckpt_path}")

    from douzero.evaluation.deep_agent import DeepAgent
    return DeepAgent(position, ckpt_path)


def _make_agent(
    position: str,
    agent_type: str,
    baselines_dir: str,
    objective: str,
    llm_client=None,
    perfect_info: bool = False,
    mode: str = "direct",
    layers=None,
):
    if agent_type == "llm":
        if mode == "cognitive":
            from scripts.douzero_agent import DouZeroCognitiveAgent
            from core.executor import Executor
            if layers is None:
                from core.chain_factory import build_default_chain

                chain = build_default_chain(PROJECT_ROOT, auxiliary_llm=None, seed=True)
            else:
                chain = layers
            executor = Executor(layer_root=chain, llm_client=llm_client)
            return DouZeroCognitiveAgent(executor=executor, position=position)
        else:
            from scripts.douzero_agent import DouZeroLLMAgent
            return DouZeroLLMAgent(llm_client=llm_client, position=position, use_perfect_info=perfect_info)
    elif agent_type == "random":
        from douzero.evaluation.random_agent import RandomAgent
        return RandomAgent()
    elif agent_type == "rlcard":
        from douzero.evaluation.rlcard_agent import RLCardAgent
        return RLCardAgent(position)
    else:
        model_dir = os.path.join(baselines_dir, agent_type)
        return _load_douzero_model(position, model_dir, objective)


_POSITION_CN = {
    'landlord': '地主', 'landlord_up': '地主上家', 'landlord_down': '地主下家',
}


def _get_position_cn(pos: str) -> str:
    return _POSITION_CN.get(pos, pos)


def _cards_to_str(cards: list[int]) -> str:
    from scripts.douzero_agent import cards_to_str
    return cards_to_str(cards)


def run_episodes(
    env: GameEnv,
    players: dict,
    episodes: int,
    seed: int | None = None,
    verbose: bool = True,
    step_verbose: bool = False,
) -> dict:
    wins = {'landlord': 0, 'farmer': 0}
    scores = {'landlord': 0, 'farmer': 0}

    for ep in range(1, episodes + 1):
        deck = _shuffle_deck(seed + ep - 1 if seed is not None else None)
        game_data = _gen_game_data(deck)
        env.card_play_init(game_data)

        for pos, agent in players.items():
            if hasattr(agent, 'reset_session'):
                agent.reset_session(f"douzero_{pos}_ep{ep}")

        step_count = 0
        while not env.game_over:
            pos = env.acting_player_position
            env.step()
            step_count += 1
            if step_verbose and step_count % 5 == 0:
                logger.info("  ep=%d step=%d acting=%s", ep, step_count, pos)

        winner = env.get_winner()
        bomb_num = env.get_bomb_num()
        base_score = 2 if winner == 'landlord' else 1
        score = base_score * (2 ** bomb_num)

        if winner == 'landlord':
            wins['landlord'] += 1
            scores['landlord'] += score
            scores['farmer'] -= score
        else:
            wins['farmer'] += 1
            scores['farmer'] += score
            scores['landlord'] -= score

        env.reset()

        if verbose and ep % max(1, episodes // 10) == 0:
            logger.info(
                "Ep %d/%d  steps=%d  landlord=%d  farmer=%d",
                ep, episodes, step_count,
                wins['landlord'], wins['farmer'],
            )

    return {
        "episodes": episodes,
        "wins": wins,
        "scores": scores,
        "wp_landlord": wins['landlord'] / episodes,
        "wp_farmer": wins['farmer'] / episodes,
        "adp_landlord": scores['landlord'] / episodes,
        "adp_farmer": scores['farmer'] / episodes,
    }


def main():
    parser = argparse.ArgumentParser(description="DouZero + LLM Agent 对局脚本")
    parser.add_argument("--episodes", type=int, default=20,
                        help="对局数 (default: 20)")
    parser.add_argument("--seed", type=int, default=42,
                        help="随机种子 (default: 42)")

    position_group = parser.add_argument_group("LLM Agent")
    position_group.add_argument("--llm_position", default="random",
                                choices=["landlord", "landlord_up", "landlord_down", "random"],
                                help="LLM Agent 担任的角色 (default: random=随机农民位置)")
    position_group.add_argument("--opponent", default="douzero_ADP",
                                help="对手类型: douzero_ADP/douzero_WP/sl/random/rlcard")

    parser.add_argument("--baselines_dir", default=str(PROJECT_ROOT / "baselines"),
                        help="预训练模型目录 (default: baselines/)")
    parser.add_argument("--objective", default="adp", choices=["adp", "wp"],
                        help="计分方式 (default: adp)")
    parser.add_argument("--dry_run", action="store_true",
                        help="用随机Agent替代LLM (调试用)")
    parser.add_argument("--perfect_info", action="store_true",
                        help="LLM Agent 使用完美信息（能看到对手手牌）")
    parser.add_argument("--verbose", action="store_true", default=True)
    parser.add_argument("--step_verbose", action="store_true",
                        help="每5步输出一次进度 (LLM模式推荐开启)")
    parser.add_argument("--mode", default="direct", choices=["direct", "cognitive"],
                        help="LLM agent mode: direct (bypass layers) or cognitive (full chain)")

    args = parser.parse_args()

    if args.llm_position == "random":
        farmer_positions = ["landlord_up", "landlord_down"]
        rng = random.Random(args.seed)
        args.llm_position = rng.choice(farmer_positions)
        logger.info("Random position: LLM plays as %s",
                    _get_position_cn(args.llm_position))

    task_label = f"douzero_{args.llm_position}"
    _run_log_dir = _setup_file_logging(task_label)

    logger.info("Config: episodes=%d  seed=%d  llm_pos=%s  opponent=%s  dry_run=%s",
                args.episodes, args.seed, args.llm_position, args.opponent, args.dry_run)

    # LLM client
    llm_client = None
    if args.dry_run:
        logger.info("DRY RUN mode - using RandomAgent for LLM position")

    if not args.dry_run:
        from core.llm_factory import build_llm_client

        llm_client = build_llm_client(PROJECT_ROOT / "config.yaml")
        logger.info("LLM: %s  thinking=%s", getattr(llm_client, "model", "?"),
                    getattr(llm_client, "thinking_enabled", False))

    # Build players
    players = {}
    for pos in ["landlord", "landlord_up", "landlord_down"]:
        if pos == args.llm_position:
            agent_type = "random" if args.dry_run else "llm"
            players[pos] = _make_agent(pos, agent_type, args.baselines_dir, args.objective,
                                         llm_client=llm_client, perfect_info=args.perfect_info,
                                         mode=args.mode)
        else:
            players[pos] = _make_agent(pos, args.opponent, args.baselines_dir, args.objective,
                                         mode=args.mode)

    logger.info("Players: landlord=%s  up=%s  down=%s",
                type(players['landlord']).__name__,
                type(players['landlord_up']).__name__,
                type(players['landlord_down']).__name__)

    env = GameEnv(players)

    t0 = datetime.now()
    results = run_episodes(env, players, args.episodes, seed=args.seed,
                           verbose=args.verbose, step_verbose=args.step_verbose)
    elapsed = (datetime.now() - t0).total_seconds()

    print()
    print("=" * 55)
    print("  DouZero + LLM Agent  --  Results")
    print("=" * 55)
    print(f"  Episodes:   {args.episodes}")
    print(f"  LLM role:   {args.llm_position}")
    print(f"  Opponent:   {args.opponent}")
    print(f"  Time:       {elapsed:.0f}s  ({elapsed/args.episodes:.1f}s/ep)")
    print()
    print(f"  Landlord wins:  {results['wins']['landlord']:>4}  ({results['wp_landlord']:.1%})")
    print(f"  Farmer wins:    {results['wins']['farmer']:>4}  ({results['wp_farmer']:.1%})")
    print(f"  ADP landlord:   {results['adp_landlord']:+.2f}")
    print(f"  ADP farmer:     {results['adp_farmer']:+.2f}")
    print("=" * 55)
    print(f"  Log:        {_run_log_dir / 'game.log'}")
    print("=" * 55)


if __name__ == "__main__":
    main()
