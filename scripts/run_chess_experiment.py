"""Chess self-play experiment harness — adaptive Elo AB-group comparison.

用法:
  python scripts/run_chess_experiment.py --group baseline          # 10局无学习
  python scripts/run_chess_experiment.py --group learning          # 20局开学习
  python scripts/run_chess_experiment.py --group both              # 先B后A
  python scripts/run_chess_experiment.py --group learning --games 30
  python scripts/run_chess_experiment.py --group learning --resume <snapshot_dir>
"""
import argparse
import csv
import json
import logging
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

logger = logging.getLogger("chess_experiment")

_DEFAULT_GAMES = {"baseline": 10, "learning": 20, "train": 20, "eval": 3}
_ELO_START = 700
_ELO_MIN = 600
_ELO_MAX = 2000
_ELO_STEP = 100
_MAX_MOVES = 80


def main():
    parser = argparse.ArgumentParser(description="Chess self-play experiment")
    parser.add_argument("--group", default="both",
                        choices=["baseline", "learning", "both", "train", "eval"])
    parser.add_argument("--games", type=int, default=None, help="Override games per group")
    parser.add_argument("--model", default="maia3-5m", choices=["maia3-5m", "maia3-23m", "maia3-79m"])
    parser.add_argument("--device", default="cpu", choices=["cpu", "cuda"])
    parser.add_argument("--resume", default=None, help="Snapshot dir to resume from")
    parser.add_argument("--out-dir", default=None, help="Output directory (default: auto timestamp)")
    parser.add_argument("--eval-elo", type=int, default=None, help="Fixed Elo for eval (no adaptation)")
    args = parser.parse_args()

    _setup_logging()

    import shutil as _shutil
    import os as _os
    # Only expose the Elo-limited wrapper (vendor/bin/stockfish_1400.bat) in PATH.
    # The raw stockfish exe is NOT in PATH — agent cannot bypass the 1400 limit.
    _bin_dir = PROJECT_ROOT / "vendor" / "bin"
    if not (_bin_dir / "stockfish_1400.bat").exists():
        logger.error("stockfish_1400.bat not found in %s", _bin_dir)
        sys.exit(1)
    _os.environ["PATH"] = str(_bin_dir) + _os.pathsep + _os.environ.get("PATH", "")
    if not _shutil.which("stockfish_1400"):
        logger.error("stockfish_1400 not findable in PATH after adding vendor/bin")
        sys.exit(1)
    logger.info("stockfish_1400 wrapper available (Elo limited to 1400)")

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_root = Path(args.out_dir) if args.out_dir else PROJECT_ROOT / "experiment_results" / f"chess_{stamp}"
    out_root.mkdir(parents=True, exist_ok=True)

    if args.group == "both":
        groups = ["baseline", "learning"]
    elif args.group == "train":
        groups = ["train"]
    elif args.group == "eval":
        groups = ["eval"]
    else:
        groups = [args.group]

    for grp in groups:
        n = args.games or _DEFAULT_GAMES.get(grp, 20)
        run_group(grp, n, args, out_root)

    _write_summary(out_root)


def run_group(group: str, n_games: int, args, out_root: Path):
    from core.env.chess_game_env import ChessGameEnv, _material_balance

    if group == "eval":
        elo_subdir = f"elo_{args.eval_elo or 1000}"
        grp_dir = out_root / group / elo_subdir
    else:
        grp_dir = out_root / group
    grp_dir.mkdir(parents=True, exist_ok=True)
    snapshot_dir = grp_dir / "snapshots"
    snapshot_dir.mkdir(exist_ok=True)

    data_root = _fork_data(group, out_root, grp_dir)

    enable_learning = group in ("learning", "train")
    current_elo = _ELO_START
    start_game = 1

    if group == "eval":
        current_elo = args.eval_elo or 1000

    if args.resume:
        resume_dir = Path(args.resume)
        if resume_dir.exists():
            current_elo, start_game = _load_resume_state(resume_dir, data_root, group)
            if group == "eval":
                current_elo = args.eval_elo or current_elo
            logger.info("Resumed from %s: elo=%d, start_game=%d", resume_dir, current_elo, start_game)

    csv_path = grp_dir / "elo_progression.csv"
    write_header = not csv_path.exists()
    csv_f = open(csv_path, "a", newline="", encoding="utf-8")
    writer = csv.writer(csv_f)
    if write_header:
        writer.writerow(["game", "group", "elo_before", "elo_after", "outcome",
                         "total_reward", "move_count", "top1_hit_rate", "final_material_diff"])

    for gi in range(start_game, n_games + 1):
        logger.info("════ %s Game %d/%d  Elo=%d ════", group.upper(), gi, n_games, current_elo)
        t0 = time.time()

        try:
            result = run_single_game(gi, group, current_elo, enable_learning, args, data_root)
        except Exception as e:
            logger.exception("Game %d crashed: %s", gi, e)
            result = {
                "game_id": gi, "group": group,
                "elo_before": current_elo, "elo_after": current_elo,
                "outcome": "error", "total_reward": 0.0,
                "move_count": 0, "top1_hit_rate": 0.0,
                "final_material_diff": 0, "moves": [],
                "error": str(e),
            }

        elapsed = time.time() - t0
        logger.info("  [DONE G%d] %s | elo %d→%d | moves=%d | reward=%+.1f | top1=%.0f%% | mat=%+d | %.0fs",
                     gi, result["outcome"], result["elo_before"], result["elo_after"],
                     result["move_count"], result["total_reward"],
                     result["top1_hit_rate"] * 100, result["final_material_diff"], elapsed)

        game_path = grp_dir / f"game_{gi:02d}.json"
        game_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

        writer.writerow([gi, group, result["elo_before"], result["elo_after"],
                         result["outcome"], result["total_reward"], result["move_count"],
                         f"{result['top1_hit_rate']:.2f}", result["final_material_diff"]])
        csv_f.flush()

        snap_path = snapshot_dir / f"snapshot_{gi:03d}"
        if snap_path.exists():
            shutil.rmtree(snap_path)
        shutil.copytree(data_root / "data", snap_path, dirs_exist_ok=False)
        logger.info("  Snapshot saved: %s", snap_path)

        if group != "eval":
            current_elo = result["elo_after"]
        # eval: fixed Elo, no adaptation

    csv_f.close()
    logger.info("=== %s group done: %d games ===", group, n_games)


def run_single_game(game_id: int, group: str, elo: int,
                    enable_learning: bool, args, data_root: Path) -> dict:
    from core.env.chess_game_env import ChessGameEnv, _material_balance
    from core.types import TaskObservation

    env = ChessGameEnv(
        model=args.model, elo=elo, device=args.device,
        max_moves=_MAX_MOVES, agent_plays="white",
        enable_learning=enable_learning,
    )

    executor = _setup_cognitive(env, data_root, enable_learning)

    env.reset()
    logger.info("Game started. Agent plays white. Elo=%d", elo)

    per_move = []
    top1_hits = 0
    total_moves = 0

    while not env.is_game_over:
        _reset_step_counters(executor._root)
        obs = _build_obs(env, game_id, group)
        t0 = time.time()
        result = executor.execute(obs)
        elapsed = time.time() - t0
        action = result.get("action_text", "")

        step = env.step(action)
        total_moves += 1

        info = step.state.info
        maia_top1 = info.get("maia_top1", "")
        agent_move = _extract_move(action)
        if agent_move and maia_top1 and agent_move == maia_top1:
            top1_hits += 1

        per_move.append({
            "turn": total_moves,
            "agent_move": agent_move or "?",
            "maia_top1": maia_top1,
            "reward": step.reward,
            "elapsed": round(elapsed, 1),
        })

        logger.info("  [%s G%d move %d] agent=%s maia=%s reward=%+.1f total=%+.1f (%.0fs)",
                     group[0].upper(), game_id, total_moves,
                     agent_move or "?", maia_top1 or "?",
                     step.reward, env.total_reward, elapsed)

        if step.done:
            break

    outcome = env.game_result or "unknown"
    total_reward = env.total_reward
    move_count = env._move_count
    top1_hit_rate = top1_hits / max(total_moves, 1)
    final_mat = _material_balance(env._board) if env._board else 0

    # End-game reflection (learning mode only)
    if enable_learning:
        try:
            reflect_obs = TaskObservation(
                meta="对局已结束。请复盘整局棋，分析关键转折点、得失原因，"
                     "提炼可固化的经验。调用 record_learning 记录重要教训。",
                state={
                    "current": f"结果: {outcome} | 总奖励: {total_reward:+.1f} | "
                               f"子力差: {final_mat:+d} | 走法匹配率: {top1_hit_rate*100:.0f}%",
                    "history": env._format_move_history(),
                },
                session={
                    "id": env._session_id,
                    "domain": "chess/game",
                    "domains_hint": ["chess", "chess/game"],
                    "step_index": move_count,
                    "enable_learning": True,
                },
            )
            executor.execute(reflect_obs)
        except Exception as e:
            logger.warning("End-game reflection failed: %s", e)

    if "agent wins" in outcome:
        elo_after = min(elo + _ELO_STEP, _ELO_MAX)
    elif "maia3 wins" in outcome:
        elo_after = max(elo - _ELO_STEP, _ELO_MIN)
    else:
        elo_after = elo

    env.save_game(data_root / "data" / f"game_{game_id:02d}.json")

    return {
        "game_id": game_id,
        "group": group,
        "elo_before": elo,
        "elo_after": elo_after,
        "outcome": outcome,
        "total_reward": total_reward,
        "move_count": move_count,
        "top1_hit_rate": top1_hit_rate,
        "final_material_diff": final_mat,
        "moves": per_move,
    }


def _build_obs(env, game_id: int, group: str):
    from core.types import TaskObservation
    state = env._build_observation()
    return TaskObservation(
        meta=_SYSTEM_PROMPT.format(group=group),
        state={
            "current": state.observation,
            "history": env._format_move_history(),
        },
        session={
            "id": env._session_id,
            "domain": "chess/game",
            "domains_hint": ["chess", "chess/game"],
            "step_index": env._move_count,
            "enable_learning": (group == "learning"),
        },
    )


_SYSTEM_PROMPT = (
    "你正在与 Maia3 国际象棋引擎对弈（{group}组实验）。\n\n"
    "**每轮是独立上下文**：你不会看到之前的分析内容，只有当前局面和最近几步历史。\n"
    "请完整分析当前局面，不要假设你记得上一轮的推理。\n"
    "合法走法已由环境列出——你只需从中选择最佳的一个。\n\n"
    "**可用工具**：\n"
    "- terminal：可执行 shell 命令（L1 通过 l1_query 下发给 L2/L3 执行）\n"
    "- web_search / tavily_search：搜索**思路和理论**（开局原则、战术模式名称、残局技巧），"
    "**不要搜索当前具体棋局的 FEN 或走法**。"
    "web_search 和 tavily_search **共享**每步最多 2 次调用限额。\n"
    "- read_file / grep：搜索本地 chess 相关文件\n"
    "- kb_query / kb_modify / kb_fill_gap：知识库查询/修改/补缺\n"
    "- l1_query / l2_query：下发内部认知层做深度分析（L2/L3 可调用 chess_analyze 等工具）\n\n"
    "**建议流程**：\n"
    "1. 通过 l1_query 下发当前 FEN 让 L2/L3 用 chess_analyze 分析（获取最佳走法 + 评估）\n"
    "2. 如需理论背景，用 web_search/tavily_search 查开局名称或战术概念（不查具体局面）\n"
    "3. 用 kb_query 检索已有知识卡片\n"
    "4. 综合引擎评估和知识，选择最佳走法\n"
    "5. [train 组] 如果发现有效的工具使用模式或战术经验，调用 record_learning 记录\n\n"
    "**搜索硬性限制**：\n"
    "- web_search 和 tavily_search 共享每步最多 2 次调用（环境强制，超限自动拒绝并返回错误）\n"
    "- 搜索只用于查思路和工具用法，不要搜当前 FEN/具体走法\n\n"
    "**重要——使用 l1_query 调用下层认知**：\n"
    "- 在复杂局面（被将军、吃子决策、多路分支）时，必须调用 l1_query 下发给L2/L3做深度分析\n"
    "- l1_query 可以让L2检索知识卡片、让L3调用技能执行计算\n"
    "- 收到L2回复后，综合信息做决策，不要跳过l1_query直接出结果\n\n"
    "**重要——中间学习记录**：\n"
    "- 每当子力对比发生变化（吃子/被吃），立即评估是否为关键转折点\n"
    "- 如果发现某类走法（如开局模式、战术组合）在本局持续有效，记录为成功经验\n"
    "- 不要等到整局结束才学习——及时固化中间发现\n\n"
    "**禁止**：\n"
    "- 不要安装或调用 Stockfish 以外的外部引擎（如 Leela、Komodo）\n\n"
    "输出要求：\n"
    "- 最终选择一步走法，以格式 'move: <uci>' 结尾（如 move: e2e4）"
)


def _reset_step_counters(chain) -> None:
    """Reset per-step call counters on all layer agents' AgentContext."""
    from core.agent_context import AgentContext
    node = chain
    while node is not None:
        if node._agent is not None:
            ctx = getattr(node._agent, '_context', None)
            if isinstance(ctx, AgentContext):
                ctx.reset_call_counters()
        node = node._downstream


def _setup_cognitive(env, data_root: Path, enable_learning: bool):
    from core.chain_factory import build_default_chain as _build_chain
    from core.llm_factory import build_llm_client
    from core.executor import Executor
    from core.runtime_registry import register_runtime
    from core.round_tree import reset_round_history

    # Each game is an independent episode — clear prior rounds so record_learning
    # snapshots don't bleed decision trees from the previous game into this one.
    reset_round_history()

    chain = _build_chain(data_root, auxiliary_llm=build_llm_client(),
                         seed=False, env=env)
    executor = Executor(chain, build_llm_client())
    register_runtime(chain, executor)

    _seed_l1_only(chain, enable_learning)

    return executor


def _seed_l1_only(chain, enable_learning: bool):
    phil = chain._philosophy
    existing = {r.content for r in phil.all_rules()}
    base_rules = [
        "分析棋局时优先评估中心控制、王安全、子力活动性三个维度",
        "面对不确定局面时，不要假设答案，仔细分析候选走法的优劣",
    ]
    if enable_learning:
        base_rules += [
            "对于象棋对局这种长程任务，积极使用中间结果和反馈进行分析和学习记录",
            "长程任务中每几步后检查是否有值得固化的经验，及时调用 record_learning",
            "当子力对比变化（吃子/被吃）时，评估是否为关键转折点并考虑 record_learning",
            "复杂局面（被将军、多路分支、吃子决策）时，通过 l1_query 下发给L2/L3分析",
        ]
    for rule in base_rules:
        if rule not in existing:
            try:
                phil.add_rule(rule, source="l1")
            except Exception:
                pass


def _fork_data(group: str, out_root: Path, grp_dir: Path = None) -> Path:
    """Create clean data directory with minimal chess-only domain preset."""
    if group == "eval" and grp_dir is not None:
        data_root = grp_dir / "data_eval"
    else:
        data_root = out_root / f"data_{group}"
    data_dir = data_root / "data"

    if data_root.exists():
        return data_root

    data_root.mkdir(parents=True, exist_ok=True)
    (data_dir / "cognitive").mkdir(parents=True, exist_ok=True)
    (data_dir / "layers" / "knowledge").mkdir(parents=True, exist_ok=True)
    (data_dir / "layers" / "skills").mkdir(parents=True, exist_ok=True)
    (data_dir / "learning").mkdir(parents=True, exist_ok=True)
    (data_dir / "knowledge").mkdir(parents=True, exist_ok=True)

    # Pre-create minimal domain_registry so init_registry() skips _seed_domain_nodes
    domain_json = data_dir / "layers" / "domain_registry.json"
    domain_json.write_text(json.dumps({
        "nodes": {
            "general": {"path": "general", "parent": None,
                        "description": "通用领域", "correlations": {}, "relations": ""},
            "chess": {"path": "chess", "parent": "general",
                      "description": "国际象棋策略域", "correlations": {}, "relations": ""},
            "chess/game": {"path": "chess/game", "parent": "chess",
                           "description": "对弈实战经验", "correlations": {}, "relations": ""},
        }
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    logger.info("Clean chess data created for %s: %s", group, data_root)
    return data_root


def _load_resume_state(resume_dir: Path, data_root: Path, group: str) -> tuple[int, int]:
    """Load Elo and game index from a snapshot directory."""
    import shutil
    data_dir = data_root / "data"
    if data_dir.exists():
        shutil.rmtree(data_dir)
    shutil.copytree(resume_dir, data_dir)

    parent = resume_dir.parent
    snap_name = resume_dir.name
    game_num = int(snap_name.replace("snapshot_", ""))
    next_game = game_num + 1

    csv_path = parent.parent / "elo_progression.csv"
    elo = _ELO_START
    if csv_path.exists():
        with open(csv_path, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            if rows:
                last = rows[-1]
                elo = int(last["elo_after"])

    return elo, next_game


def _write_summary(out_root: Path):
    summary_path = out_root / "summary.md"
    lines = ["# Chess Experiment Summary", ""]
    lines.append(f"Generated: {datetime.now().isoformat()}")
    lines.append("")

    for group in ("baseline", "learning"):
        grp_dir = out_root / group
        if not grp_dir.exists():
            continue
        csv_path = grp_dir / "elo_progression.csv"
        if not csv_path.exists():
            continue

        with open(csv_path, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        if not rows:
            continue

        wins = sum(1 for r in rows if "agent wins" in r["outcome"])
        losses = sum(1 for r in rows if "maia3 wins" in r["outcome"])
        draws = len(rows) - wins - losses
        final_elo = int(rows[-1]["elo_after"])
        start_elo = int(rows[0]["elo_before"])

        lines.append(f"## {group} ({len(rows)} games)")
        lines.append("")
        lines.append(f"- Elo: {start_elo} → {final_elo} ({final_elo - start_elo:+d})")
        lines.append(f"- W/L/D: {wins}/{losses}/{draws}")
        avg_reward = sum(float(r["total_reward"]) for r in rows) / len(rows)
        avg_hit = sum(float(r["top1_hit_rate"]) for r in rows) / len(rows)
        lines.append(f"- Avg reward: {avg_reward:+.1f}")
        lines.append(f"- Avg top1 hit: {avg_hit*100:.0f}%")
        lines.append("")

    summary_path.write_text("\n".join(lines), encoding="utf-8")
    logger.info("Summary written to %s", summary_path)


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
    log_dir = PROJECT_ROOT / "logs" / "chess_experiment" / stamp
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

    fh = logging.FileHandler(str(log_dir / "experiment.log"), encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter("%(asctime)s | %(name)s | %(message)s"))
    root.addHandler(fh)

    from core.layers.logging_setup import setup_layer_logging
    setup_layer_logging(log_dir)

    for name in ("httpx", "httpcore", "openai", "chain_factory"):
        logging.getLogger(name).setLevel(logging.WARNING)


if __name__ == "__main__":
    main()
