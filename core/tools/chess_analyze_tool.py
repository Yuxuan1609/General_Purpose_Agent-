"""chess_analyze tool — Stockfish position analysis with fixed Elo limit.

Wraps the Stockfish UCI protocol into a simple tool call.
Elo 1400 limit is hardcoded inside — agent cannot bypass it.
"""
from __future__ import annotations
import json
import logging
import os
import shutil
import subprocess
import time
from pathlib import Path

logger = logging.getLogger(__name__)

_STOCKFISH_ELO = 1400
_SF_HASH = 256
_SF_THREADS = 2
_stockfish_exe: str | None = None


def _resolve_stockfish():
    """Find the Stockfish binary. Called once, cached."""
    global _stockfish_exe
    if _stockfish_exe is not None:
        return _stockfish_exe
    # Prefer raw exe over wrapper (wrapper uses `more` which may hang)
    sf_dir = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft/WinGet/Packages" / "Stockfish.Stockfish_Microsoft.Winget.Source_8wekyb3d8bbwe" / "stockfish"
    candidates = list(sf_dir.glob("stockfish-windows-x86-64*.exe"))
    if candidates:
        _stockfish_exe = str(candidates[0])
        return _stockfish_exe
    # Fallback to wrapper in vendor/bin
    sf = shutil.which("stockfish_1400")
    if sf:
        _stockfish_exe = sf
        return sf
    return None


def register_chess_analyze_tool(registry):
    def handler(args=None, **kwargs):
        d = args or {}
        fen = d.get("fen", "")
        depth = min(int(d.get("depth", 15)), 25)
        if not fen:
            return json.dumps({"error": "fen parameter required"})

        sf = _resolve_stockfish()
        if not sf:
            return json.dumps({"error": "Stockfish not installed"})

        p = subprocess.Popen([sf], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, text=True)
        p.stdin.write(f"setoption name Hash value {_SF_HASH}\n")
        p.stdin.write(f"setoption name Threads value {_SF_THREADS}\n")
        p.stdin.write("setoption name UCI_LimitStrength value true\n")
        p.stdin.write(f"setoption name UCI_Elo value {_STOCKFISH_ELO}\n")
        p.stdin.write(f"position fen {fen}\n")
        p.stdin.write(f"go depth {depth}\n")
        p.stdin.flush()

        bestmove = ""
        score_cp = None
        pv = []
        deadline = time.time() + 60
        buf = ""
        while time.time() < deadline:
            line = p.stdout.readline()
            if not line and p.poll() is not None:
                break
            buf += line
            if line.startswith("bestmove"):
                parts = line.split()
                if len(parts) >= 2:
                    bestmove = parts[1]
                break
        # Parse last info line for score and pv
        for line in reversed(buf.split("\n")):
            if "info" in line and "score cp" in line:
                parts = line.split()
                for i, pt in enumerate(parts):
                    if pt == "cp" and i + 1 < len(parts):
                        try:
                            score_cp = int(parts[i + 1])
                        except ValueError:
                            pass
                    if pt == "pv" and i + 1 < len(parts):
                        pv = parts[i + 1:i + 9]
                break

        p.stdin.write("quit\n")
        p.stdin.flush()
        try:
            p.wait(timeout=5)
        except subprocess.TimeoutExpired:
            p.kill()
            p.wait()

        return json.dumps({
            "bestmove": bestmove,
            "score_cp": score_cp,
            "pv": pv[:8],
            "elo": _STOCKFISH_ELO,
            "depth": depth,
        }, ensure_ascii=False)

    registry.register("chess_analyze", {
        "type": "function",
        "function": {
            "name": "chess_analyze",
            "description": (
                "用 Stockfish 引擎分析当前棋局（强度固定 Elo 1400, Hash 256MB, 2线程）。"
                "输入 FEN 字符串和搜索深度，返回最佳走法、评估分数和主要变例。"
                "建议 depth 15-20。优先使用此工具而非 terminal 直接调 stockfish。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "fen": {"type": "string", "description": "当前局面的 FEN 字符串"},
                    "depth": {"type": "integer", "description": "搜索深度（建议 15-20，最大 25）", "default": 15},
                },
                "required": ["fen"],
            },
        },
    }, handler, toolset="core")
