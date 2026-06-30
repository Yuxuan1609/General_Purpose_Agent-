"""chess_analyze tool — Stockfish position analysis with fixed Elo limit.

Wraps the Stockfish UCI protocol into a simple tool call.
Elo 1400 limit is hardcoded inside — agent cannot bypass it.
"""
from __future__ import annotations
import json
import logging
import subprocess
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)

_STOCKFISH_ELO = 1400
_stockfish_exe: str | None = None


def _resolve_stockfish():
    """Find the Stockfish binary. Called once, cached."""
    global _stockfish_exe
    if _stockfish_exe is not None:
        return _stockfish_exe
    # 1. Try PATH (vendor/bin/stockfish_1400.bat may set it)
    sf = shutil.which("stockfish_1400")
    if sf:
        _stockfish_exe = sf
        return sf
    # 2. Try winget install location
    import os
    sf_dir = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft/WinGet/Packages" / "Stockfish.Stockfish_Microsoft.Winget.Source_8wekyb3d8bbwe" / "stockfish"
    if sf_dir.exists():
        candidates = list(sf_dir.glob("stockfish-windows-x86-64*.exe"))
        if candidates:
            _stockfish_exe = str(candidates[0])
            return _stockfish_exe
    # 3. Try project vendor/bin wrapper
    bin_dir = Path(__file__).resolve().parent.parent.parent / "vendor" / "bin"
    wrapper = bin_dir / "stockfish_1400.bat"
    if wrapper.exists():
        _stockfish_exe = str(wrapper)
        return _stockfish_exe
    return None


def register_chess_analyze_tool(registry):
    def handler(args=None, **kwargs):
        d = args or {}
        fen = d.get("fen", "")
        depth = min(int(d.get("depth", 15)), 20)
        if not fen:
            return json.dumps({"error": "fen parameter required"})

        sf = _resolve_stockfish()
        if not sf:
            return json.dumps({"error": "Stockfish not installed"})

        uci_cmds = [
            "setoption name UCI_LimitStrength value true",
            f"setoption name UCI_Elo value {_STOCKFISH_ELO}",
            f"position fen {fen}",
            f"go depth {depth}",
            "quit",
        ]
        uci_input = "\n".join(uci_cmds) + "\n"

        try:
            result = subprocess.run(
                [sf] if sf.endswith(".exe") else ["cmd", "/c", sf],
                input=uci_input,
                capture_output=True,
                text=True,
                timeout=60,
            )
            output = result.stdout
        except subprocess.TimeoutExpired:
            return json.dumps({"error": f"Stockfish analysis timed out (depth {depth})"})
        except Exception as e:
            return json.dumps({"error": str(e)})

        # Parse UCI output: extract bestmove and last score
        bestmove = ""
        score_cp = None
        pv = []
        for line in output.split("\n"):
            if line.startswith("bestmove"):
                parts = line.split()
                if len(parts) >= 2:
                    bestmove = parts[1]
            elif "info" in line and "score cp" in line:
                parts = line.split()
                for i, p in enumerate(parts):
                    if p == "cp" and i + 1 < len(parts):
                        score_cp = int(parts[i + 1])
                    if p == "pv" and i + 1 < len(parts):
                        pv = parts[i + 1:]
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
                "用 Stockfish 引擎分析当前棋局（强度固定 Elo 1400）。"
                "输入 FEN 字符串和搜索深度，返回最佳走法、评估分数和主要变例。"
                "建议 depth 10-15。优先使用此工具而非 terminal 直接调 stockfish。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "fen": {"type": "string", "description": "当前局面的 FEN 字符串"},
                    "depth": {"type": "integer", "description": "搜索深度（建议 10-15，最大 20）", "default": 15},
                },
                "required": ["fen"],
            },
        },
    }, handler, toolset="core")
