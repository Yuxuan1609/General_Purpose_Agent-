"""Chess cognitive agent — Maia3-powered chess puzzle evaluation.

用法:
  python scripts/run_chess_agent.py                     # 默认 8 puzzle, 5M CPU
  python scripts/run_chess_agent.py --model 79m          # 79M 模型
  python scripts/run_chess_agent.py --puzzles 5          # 只跑 5 题
  python scripts/run_chess_agent.py --elo 2000           # 目标 Elo
  python scripts/run_chess_agent.py --mode random        # 随机局面
"""
import argparse
import json
import logging
import sys
import time
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

logger = logging.getLogger("chess_agent")


def main():
    parser = argparse.ArgumentParser(description="Chess cognitive agent with Maia3")
    parser.add_argument("--model", default="maia3-5m",
                        choices=["maia3-5m", "maia3-23m", "maia3-79m"],
                        help="Maia3 model size (default: 5m)")
    parser.add_argument("--elo", type=int, default=1500,
                        help="Target Elo for Maia3 predictions")
    parser.add_argument("--puzzles", type=int, default=8,
                        help="Number of puzzles to evaluate")
    parser.add_argument("--mode", default="puzzle",
                        choices=["puzzle", "random"],
                        help="Puzzle mode or random positions")
    parser.add_argument("--device", default="cpu",
                        choices=["cpu", "cuda"], help="Torch device")
    parser.add_argument("--max-turns", type=int, default=8,
                        help="Max puzzles per run")
    parser.add_argument("--seed", action="store_true", default=False,
                        help="Seed knowledge on first run")
    parser.add_argument("--no-llm", action="store_true", default=False,
                        help="Skip LLM, just test Maia3 directly")
    args = parser.parse_args()

    _setup_logging()
    _load_env()

    from core.env.chess_env import ChessEnv, generate_random_puzzles

    logger.info("=== Chess Agent: Maia3 %s (Elo=%d, device=%s) ===",
                args.model, args.elo, args.device)

    if args.no_llm:
        _run_maia3_only(args)
        return

    if args.mode == "random":
        from core.env.chess_env import generate_random_puzzles
        puzzles = generate_random_puzzles(args.puzzles)
    else:
        puzzles = None

    env = ChessEnv(model=args.model, elo=args.elo, device=args.device,
                   puzzles=puzzles, max_turns=args.max_turns)

    chain, executor, _ = _setup_cognitive(args)

    state = env.reset()
    total_reward = 0.0
    results = []

    for turn in range(args.max_turns):
        from core.types import TaskObservation
        obs = TaskObservation(
            meta=state.observation,
            state={"current": state.observation, "history": ""},
            session={
                "domain": "chess",
                "domains_hint": ["chess"],
                "step_index": turn,
                "enable_learning": True,
            },
        )

        logger.info("── Turn %d/%d ──", turn + 1, args.max_turns)
        t0 = time.time()
        result = executor.execute(obs)
        elapsed = time.time() - t0

        action = result.get("action_text", "")
        logger.info("  action: %s (%.1fs)", action[:200], elapsed)

        step = env.step(action)
        total_reward += step.reward

        logger.info("  reward: %+.1f | total: %+.1f | done=%s",
                     step.reward, total_reward, step.done)

        results.append({
            "turn": turn,
            "action": action[:200],
            "reward": step.reward,
            "elapsed": round(elapsed, 1),
            **step.state.info,
        })

        if step.done:
            break
        state = step.state

    logger.info("=== Final: %+.1f / %d puzzles ===", total_reward, len(results))
    _print_summary(results)


def _run_maia3_only(args):
    from core.env.chess_env import ChessEnv
    env = ChessEnv(model=args.model, elo=args.elo, device=args.device,
                   max_turns=args.puzzles)
    env._ensure_engine()

    correct = 0
    total = min(args.puzzles, len(env._puzzles))
    for i in range(total):
        p = env._puzzles[i]
        env._board = chess.Board(p.fen)
        env._engine.board = env._board.copy()
        env._engine._reset_history()

        _, top = env._engine.score_moves()
        top1 = top[0]["move"].uci() if top else "?"
        match = "OK" if p.expected_move and top1 == p.expected_move else "  "
        if top1 == p.expected_move:
            correct += 1
        print(f"[{i+1}/{total}] {match} expected={p.expected_move} maia3={top1} "
              f"top3={[t['move'].uci() for t in top[:3]]}")

    print(f"\nMaia3 accuracy: {correct}/{total} = {correct/max(total,1)*100:.0f}%")


def _setup_cognitive(args):
    from core.setup import setup_executor
    chain, executor = setup_executor(PROJECT_ROOT)

    from core.tools.registry import ToolRegistry
    registry = ToolRegistry()
    _register_chess_tools(registry, chain)

    if args.seed:
        _seed_chess_knowledge(chain)

    return chain, executor, registry


def _register_chess_tools(registry, chain):
    pass


def _seed_chess_knowledge(chain):
    from core.philosophy import Philosophy
    phil = chain._philosophy
    existing = {r.content for r in phil.all_rules()}
    chess_rules = [
        "分析棋局时优先评估中心控制、王安全、子力活动性三个维度",
        "走法选择前先列出候选走法并逐一评估优劣",
        "面对陌生棋局先用规则推理而非直接猜测",
    ]
    for rule in chess_rules:
        if rule not in existing:
            try:
                phil.add_rule(rule, source="l1")
                logger.info("Seeded chess rule: %s", rule[:60])
            except Exception:
                pass


def _setup_logging():
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_dir = PROJECT_ROOT / "logs" / "chess" / stamp
    log_dir.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(logging.Formatter("%(asctime)s %(levelname)-5s %(message)s",
                                       datefmt="%H:%M:%S"))
    root.handlers.clear()
    root.addHandler(ch)

    fh = logging.FileHandler(str(log_dir / "chess.log"), encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter("%(asctime)s | %(name)s | %(message)s"))
    root.addHandler(fh)

    from core.layers.logging_setup import setup_layer_logging
    setup_layer_logging(log_dir)

    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("openai").setLevel(logging.WARNING)


def _load_env():
    from core.env_loader import load_env
    load_env(PROJECT_ROOT)


def _print_summary(results):
    if not results:
        return
    correct = sum(1 for r in results if r["reward"] >= 1.0 or r.get("maia_top1") == r.get("agent_move", ""))
    print(f"\n{'='*50}")
    print(f"  结果汇总")
    print(f"  Maia3 首选命中: {correct}/{len(results)}")
    print(f"  总奖励: {sum(r['reward'] for r in results):+.1f}")
    for r in results:
        mark = "★" if r["reward"] >= 1.0 else ("○" if r["reward"] > 0 else "×")
        elapsed = r.get("elapsed", 0)
        maia_top1 = r.get("maia_top1", "?")
        print(f"  {mark} t={r['turn']+1} reward={r['reward']:+.1f} "
              f"maia_top1={maia_top1} ({elapsed:.1f}s)")
    print(f"{'='*50}")


if __name__ == "__main__":
    import chess
    main()
