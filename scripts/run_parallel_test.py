"""
并行跑 N 组 × M 局 Leduc Hold'em LLM Agent 测试，结果汇总到一个文件。

用法:
  python scripts/run_parallel_test.py --runs 3 --episodes 3
  python scripts/run_parallel_test.py --runs 5 --episodes 10 --workers 3
"""
import argparse
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

SCRIPT = Path(__file__).resolve().parent / "run_llm_leduc.py"
LOG_DIR = Path(__file__).resolve().parent.parent / "logs"


def run_one(run_id: int, episodes: int, log_dir: Path) -> tuple[int, list[str], str]:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--episodes", str(episodes), "--log-dir", str(log_dir)],
        capture_output=True, text=True, timeout=600,
    )
    lines = result.stdout.strip().splitlines()
    summary = [l.strip() for l in lines if l.startswith("Log saved") or l.startswith("  ")]
    return run_id, summary, result.stdout.strip()


def main():
    parser = argparse.ArgumentParser(description="Parallel Leduc Hold'em LLM Agent test")
    parser.add_argument("--runs", type=int, default=5, help="并行组数 (default: 5)")
    parser.add_argument("--episodes", type=int, default=10, help="每组局数 (default: 10)")
    parser.add_argument("--workers", type=int, default=None, help="最大并发数 (default: 同 runs)")
    args = parser.parse_args()

    LOG_DIR.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    summary_path = LOG_DIR / f"parallel_summary_{timestamp}.log"

    all_results = []
    max_workers = args.workers or args.runs

    print(f"Starting {args.runs} runs × {args.episodes} episodes (workers={max_workers})...")
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(run_one, i, args.episodes, LOG_DIR): i
            for i in range(1, args.runs + 1)
        }
        for future in as_completed(futures):
            run_id, summary, raw = future.result()
            print(f"  Run {run_id}/{args.runs} done")
            all_results.append((run_id, summary, raw))

    all_results.sort(key=lambda x: x[0])

    all_wins = 0
    all_total = 0
    with open(summary_path, "w", encoding="utf-8") as f:
        f.write("Parallel Test Results\n")
        f.write(f"Runs: {args.runs} x {args.episodes} episodes\n")
        f.write(f"Time: {datetime.now().isoformat()}\n")
        f.write(f"{'='*50}\n\n")

        for run_id, summary, raw in all_results:
            f.write(f"Run {run_id}:\n")
            for line in summary:
                f.write(f"  {line}\n")
            for line in summary:
                m = re.search(r"(\d+)/(\d+)", line)
                if m:
                    all_wins += int(m.group(1))
                    all_total += int(m.group(2))
            f.write("\n")

        f.write(f"{'='*50}\n")
        f.write(f"Total: {all_wins}/{all_total} wins ({all_wins / all_total * 100:.1f}%)\n")

    print(f"\nSummary written to: {summary_path}")
    print(f"Total: {all_wins}/{all_total} wins ({all_wins / all_total * 100:.1f}%)")


if __name__ == "__main__":
    main()
