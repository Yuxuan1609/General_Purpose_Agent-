"""Chess game — full self-play agent vs Maia3.

用法:
  python scripts/run_chess_game.py                          # 默认 5M, agent 执白
  python scripts/run_chess_game.py --model maia3-79m        # 79M
  python scripts/run_chess_game.py --agent-plays black      # agent 执黑
  python scripts/run_chess_game.py --no-llm                 # Maia3 vs Maia3 自弈
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

logger = logging.getLogger("chess_game")


def main():
    parser = argparse.ArgumentParser(description="Chess game: Agent vs Maia3")
    parser.add_argument("--model", default="maia3-5m",
                        choices=["maia3-5m", "maia3-23m", "maia3-79m"])
    parser.add_argument("--elo", type=int, default=1500)
    parser.add_argument("--agent-plays", default="white", choices=["white", "black"])
    parser.add_argument("--device", default="cpu", choices=["cpu", "cuda"])
    parser.add_argument("--max-moves", type=int, default=80)
    parser.add_argument("--no-llm", action="store_true", default=False)
    parser.add_argument("--save-dir", default=None)
    args = parser.parse_args()

    _setup_logging()
    _load_env()

    from core.env.chess_game_env import ChessGameEnv

    logger.info("=== Chess Game: %s vs Maia3-%s (Elo=%d) ===",
                "Maia3" if args.no_llm else "Agent",
                args.model.replace("maia3-", ""), args.elo)

    env = ChessGameEnv(model=args.model, elo=args.elo, device=args.device,
                       max_moves=args.max_moves, agent_plays=args.agent_plays)

    if args.no_llm:
        _run_self_play(env, args)
        return

    executor = _setup_cognitive(env)

    state = env.reset()
    logger.info("Game started. %s plays white.",
                "Agent" if args.agent_plays == "white" else "Maia3")
    print(f"Initial: {state.observation.split(chr(10))[0]}", flush=True)

    move_count = 0
    while not env.is_game_over:
        obs = _build_obs(env)
        if obs is None:
            break

        move_count += 1
        side = "W" if env._board.turn == chess.WHITE else "B"
        sys.stdout.write(f"[{move_count}] {side} thinking...")
        sys.stdout.flush()

        t0 = time.time()
        result = executor.execute(obs)
        elapsed = time.time() - t0
        action = result.get("action_text", "")
        move_uci = _extract_move(action)
        notify = result.get("notify_layers", {})
        l1_ok = notify.get("l0_5_1", {}).get("done", False)

        step = env.step(action)
        sys.stdout.write(
            f"\r[{move_count}] {side} move={move_uci or '?'} "
            f"reward={step.reward:+.1f} total={env.total_reward:+.1f} "
            f"L1={'OK' if l1_ok else '?'} ({elapsed:.0f}s)\n")
        sys.stdout.flush()

        if step.done:
            break

    logger.info("=== Game Over: %s ===", env.game_result)
    logger.info("  moves=%d reward=%+.1f", env._move_count, env.total_reward)
    logger.info("  Final FEN: %s", env._board.fen())

    print(f"\nResult: {env.game_result} | {env._move_count} moves | {env.total_reward:+.1f} reward")
    for h in env.get_history():
        mn = h["move_num"]
        w = h.get("white", "--")
        b = h.get("black", "--")
        r = h.get("agent_reward", 0)
        e = h.get("eval", "")
        print(f"  {mn:2d}. {w:6s}  {b:6s}  {'+' if r > 0 else '-' if r < 0 else ' '}{abs(r):.1f}  {e}")

    if args.save_dir:
        path = env.save_game(Path(args.save_dir) / f"chess_{env._session_id[:8]}.json")
        logger.info("Game saved to %s", path)


def _build_obs(env):
    from core.types import TaskObservation
    state = env._build_observation()
    return TaskObservation(
        meta="你正在与 Maia3 下棋。每轮独立上下文。合法走法已列出——直接从中选择最佳。"
             "分析局面后以 'move: <uci>' 结尾。禁止安装外部引擎（Stockfish等）。",
        state={
            "current": state.observation,
            "history": env._format_move_history(),
        },
        session={
            "id": env._session_id,
            "domain": "chess/game",
            "domains_hint": ["chess", "chess/game"],
            "step_index": env._move_count,
            "enable_learning": True,
        },
    )


def _setup_cognitive(env):
    from core.chain_factory import build_default_chain as _build_chain
    from core.llm_factory import build_llm_client
    from core.executor import Executor
    from core.runtime_registry import register_runtime

    _fork_chess_data()

    data_root = PROJECT_ROOT / "data_chess"
    chain = _build_chain(data_root, auxiliary_llm=build_llm_client(),
                         seed=True, env=env)
    executor = Executor(chain, build_llm_client())
    register_runtime(chain, executor)

    phil = chain._philosophy
    existing = {r.content for r in phil.all_rules()}
    rules = [
        "长程任务（如完整棋局）中：每几步后检查是否有值得固化的经验，"
        "及时调用 record_learning，不要等到全部结束后才学习",
        "如果发现某类走法持续有效或无效，立即 record_learning 记录模式",
    ]
    for rule in rules:
        if rule not in existing:
            try:
                phil.add_rule(rule, source="l1")
            except Exception:
                pass

    return executor


def _fork_chess_data():
    import shutil
    chess_root = PROJECT_ROOT / "data_chess"
    if chess_root.exists():
        return
    chess_root.mkdir(parents=True, exist_ok=True)
    (chess_root / "data" / "cognitive").mkdir(parents=True, exist_ok=True)
    (chess_root / "data" / "layers").mkdir(parents=True, exist_ok=True)
    (chess_root / "data" / "learning").mkdir(parents=True, exist_ok=True)
    (chess_root / "data" / "knowledge").mkdir(parents=True, exist_ok=True)

    src_layers = PROJECT_ROOT / "data" / "layers"
    dst_layers = chess_root / "data" / "layers"
    for f in src_layers.glob("*.json"):
        if not (dst_layers / f.name).exists():
            shutil.copy2(f, dst_layers / f.name)

    logger.info("Chess data forked to %s", chess_root)


def _run_self_play(env, args):
    import chess
    env._ensure_engine()
    board = chess.Board()
    move_count = 0
    start = time.time()

    while not board.is_game_over() and move_count < args.max_moves:
        engine_board = board.copy()
        env._engine.board = engine_board
        env._engine._reset_history()
        move, _ = env._engine.score_moves()
        if move is None:
            break
        board.push(move)
        move_count += 1
        if move_count % 10 == 0:
            print(f"  move {move_count}...", flush=True)

    elapsed = time.time() - start
    outcome = board.outcome()
    result = "draw"
    if outcome and outcome.winner is not None:
        result = "white wins" if outcome.winner == chess.WHITE else "black wins"

    logger.info("Self-play: %s | %d moves | %.1fs", result, move_count, elapsed)
    logger.info("Final FEN: %s", board.fen())


def _extract_move(action: str) -> str:
    import re
    for pat in [r'move:\s*([a-h][1-8][a-h][1-8][qrbn]?)',
                r'([a-h][1-8][a-h][1-8][qrbn]?)']:
        m = re.search(pat, action, re.IGNORECASE)
        if m:
            return m.group(1)
    return ""


def _setup_logging():
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_dir = PROJECT_ROOT / "logs" / "chess_game" / stamp
    log_dir.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    for h in list(root.handlers):
        root.removeHandler(h)

    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(logging.Formatter("%(asctime)s %(levelname)-5s %(message)s",
                                       datefmt="%H:%M:%S"))
    root.addHandler(ch)

    fh = logging.FileHandler(str(log_dir / "game.log"), encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter("%(asctime)s | %(name)s | %(message)s"))
    root.addHandler(fh)

    from core.layers.logging_setup import setup_layer_logging
    setup_layer_logging(log_dir)

    for name in ("httpx", "httpcore", "openai", "chain_factory"):
        logging.getLogger(name).setLevel(logging.WARNING)


def _load_env():
    from core.env_loader import load_env
    load_env(PROJECT_ROOT)


if __name__ == "__main__":
    import chess
    main()
