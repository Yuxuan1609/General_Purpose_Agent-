"""Chess experiment monitor — 查看实验进度、Elo 趋势、对局结果。

用法:
  python scripts/monitor_chess.py                          # 自动找最新实验目录
  python scripts/monitor_chess.py --dir experiment_results/chess_xxx
  python scripts/monitor_chess.py --watch                  # 每 30s 刷新
"""
import argparse
import csv
import json
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def find_latest_experiment() -> Path | None:
    dirs = sorted(PROJECT_ROOT.glob("experiment_results/chess_*"), reverse=True)
    return dirs[0] if dirs else None


def print_status(exp_dir: Path):
    print(f"\n{'='*60}")
    print(f"  Experiment: {exp_dir.name}")
    print(f"  Time: {time.strftime('%H:%M:%S')}")
    print(f"{'='*60}")

    for group in ("baseline", "learning"):
        grp_dir = exp_dir / group
        if not grp_dir.exists():
            continue

        games = sorted(grp_dir.glob("game_*.json"))
        csv_path = grp_dir / "elo_progression.csv"

        print(f"\n  [{group.upper()}]")

        # Latest log lines
        log_path = exp_dir / f"{group}.log"
        if log_path.exists():
            lines = log_path.read_text(encoding="utf-8", errors="replace").strip().split("\n")
            recent = [l for l in lines[-8:] if l.strip() and "Category" not in l]
            for l in recent:
                print(f"    {l}")

        # CSV summary
        if csv_path.exists():
            with open(csv_path, encoding="utf-8") as f:
                rows = list(csv.DictReader(f))
            if rows:
                done = len(rows)
                wins = sum(1 for r in rows if "agent wins" in r["outcome"])
                losses = sum(1 for r in rows if "maia3 wins" in r["outcome"])
                draws = done - wins - losses
                start_elo = int(rows[0]["elo_before"])
                final_elo = int(rows[-1]["elo_after"])
                avg_hit = sum(float(r["top1_hit_rate"]) for r in rows) / done
                avg_reward = sum(float(r["total_reward"]) for r in rows) / done

                target = 10 if group == "baseline" else 20
                print(f"    ── Summary: {done}/{target} games ──")
                print(f"    Elo: {start_elo} → {final_elo} ({final_elo - start_elo:+d})")
                print(f"    W/L/D: {wins}/{losses}/{draws}")
                print(f"    Avg reward: {avg_reward:+.1f} | Avg top1: {avg_hit*100:.0f}%")
                print(f"    ┌─────┬────────┬────────┬──────────────┬───────┬────────┐")
                print(f"    │ Game│ EloBef│ EloAft│ Outcome      │ Moves │ Reward │")
                print(f"    ├─────┼────────┼────────┼──────────────┼───────┼────────┤")
                for r in rows[-5:]:
                    print(f"    │ {r['game']:>3} │ {r['elo_before']:>6} │ {r['elo_after']:>6} "
                          f"│ {r['outcome']:<12} │ {r['move_count']:>5} │ {float(r['total_reward']):>+6.1f} │")
                print(f"    └─────┴────────┴────────┴──────────────┴───────┴────────┘")
        else:
            print(f"    (no games completed yet)")

        # Game files detail
        if games:
            latest = json.loads(games[-1].read_text(encoding="utf-8"))
            moves = latest.get("moves", [])
            if moves:
                print(f"    Latest game #{latest['game_id']} last 3 moves:")
                for m in moves[-3:]:
                    print(f"      turn {m['turn']}: agent={m['agent_move']} "
                          f"reward={m['reward']:+.1f} ({m['elapsed']}s)")


def main():
    parser = argparse.ArgumentParser(description="Chess experiment monitor")
    parser.add_argument("--dir", default=None, help="Experiment directory")
    parser.add_argument("--watch", action="store_true", help="Auto-refresh every 30s")
    args = parser.parse_args()

    exp_dir = Path(args.dir) if args.dir else find_latest_experiment()
    if exp_dir is None or not exp_dir.exists():
        print("No experiment directory found.")
        sys.exit(1)

    if args.watch:
        try:
            while True:
                print("\033[2J\033[H", end="")
                print_status(exp_dir)
                print(f"\n  (refreshing in 30s, Ctrl+C to exit)")
                time.sleep(30)
        except KeyboardInterrupt:
            print("\nStopped.")
    else:
        print_status(exp_dir)


if __name__ == "__main__":
    main()
