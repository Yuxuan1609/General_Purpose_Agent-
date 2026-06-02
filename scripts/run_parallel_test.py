"""
顺序跑 5 组 × 10 局 Leduc Hold'em LLM Agent 测试，结果汇总到一个文件。
"""
import subprocess
import sys
from datetime import datetime
from pathlib import Path
import re

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

SCRIPT = Path(__file__).resolve().parent / "run_llm_leduc.py"
LOG_DIR = Path(__file__).resolve().parent.parent / "logs"
RUNS = 5
EPISODES = 10

LOG_DIR.mkdir(exist_ok=True)
timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
summary_path = LOG_DIR / f"parallel_summary_{timestamp}.log"

all_results = []

for run_id in range(1, RUNS + 1):
    print(f"Run {run_id}/{RUNS} ({EPISODES} episodes)...")
    log_path = LOG_DIR / f"run_{run_id}_{timestamp}.log"
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--episodes", str(EPISODES), "--log-dir", str(LOG_DIR)],
        capture_output=True, text=True, timeout=600,
    )
    lines = result.stdout.strip().splitlines()
    summary = [l.strip() for l in lines if l.startswith("Log saved") or l.startswith("  ")]
    all_results.append((run_id, summary, result.stdout.strip()))

with open(summary_path, "w", encoding="utf-8") as f:
    f.write(f"Parallel Test Results\n")
    f.write(f"Model: deepseek-v4-flash (no thinking)\n")
    f.write(f"Runs: {RUNS} × {EPISODES} episodes\n")
    f.write(f"Time: {datetime.now().isoformat()}\n")
    f.write(f"{'='*50}\n\n")

    all_wins = 0
    all_total = 0
    for run_id, summary, raw in all_results:
        f.write(f"Run {run_id}:\n")
        for line in summary:
            f.write(f"  {line.strip()}\n")
        for line in summary:
            m = re.search(r"(\d+)/(\d+)", line)
            if m:
                all_wins += int(m.group(1))
                all_total += int(m.group(2))
        f.write("\n")

    f.write(f"{'='*50}\n")
    f.write(f"Total: {all_wins}/{all_total} wins ({all_wins/all_total*100:.1f}%)\n")

print(f"\nSummary written to: {summary_path}")
print(f"Total: {all_wins}/{all_total} wins ({all_wins/all_total*100:.1f}%)")
