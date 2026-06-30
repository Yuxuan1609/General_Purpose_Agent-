"""Maia3 vs Stockfish direct engine match — quick calibration script.

Usage: python scripts/maia_vs_stockfish.py
"""
from __future__ import annotations
import chess
import subprocess
import sys
import os
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

MAIA_ELOS = [1000]
SF_ELOS = [1250, 1300, 1350, 1400]
SF_DEPTH = 15
SF_HASH = 256
SF_THREADS = 2
MAX_MOVES = 80


def _find_stockfish() -> str:
    """Locate raw Stockfish exe."""
    sf_dir = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft/WinGet/Packages" / "Stockfish.Stockfish_Microsoft.Winget.Source_8wekyb3d8bbwe" / "stockfish"
    candidates = list(sf_dir.glob("stockfish-windows-x86-64*.exe"))
    if candidates:
        return str(candidates[0])
    raise RuntimeError("Stockfish not found")


def stockfish_bestmove(fen: str, depth: int = 0, movetime: int = 0, elo: int = 0) -> str | None:
    """Get Stockfish's best move. Waits for search to complete before quitting."""
    sf = _find_stockfish()
    p = subprocess.Popen([sf], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE, text=True)
    p.stdin.write(f"setoption name Hash value {SF_HASH}\n")
    p.stdin.write(f"setoption name Threads value {SF_THREADS}\n")
    if elo > 0:
        p.stdin.write("setoption name UCI_LimitStrength value true\n")
        p.stdin.write(f"setoption name UCI_Elo value {elo}\n")
    p.stdin.write(f"position fen {fen}\n")
    if movetime > 0:
        p.stdin.write(f"go movetime {movetime}\n")
    else:
        p.stdin.write(f"go depth {depth}\n")
    p.stdin.flush()

    bestmove = None
    deadline = time.time() + 60
    buf = ""
    while time.time() < deadline:
        # Read available output
        import select
        if sys.platform == "win32":
            chunk = p.stdout.readline()
        else:
            chunk = p.stdout.readline()
        if not chunk and p.poll() is not None:
            break
        buf += chunk
        for line in buf.split("\n"):
            if line.startswith("bestmove"):
                parts = line.split()
                if len(parts) >= 2:
                    bestmove = parts[1]
                break
        if bestmove:
            break
    p.stdin.write("quit\n")
    p.stdin.flush()
    try:
        p.wait(timeout=5)
    except subprocess.TimeoutExpired:
        p.kill()
    return bestmove


def load_maia3(elo: int = 1000):
    """Load Maia3 with specified Elo."""
    from maia3.model_registry import resolve_model_spec, apply_model_config

    class _Cfg:
        pass
    cfg = _Cfg()
    cfg.model = "maia3-5m"
    cfg.device = "cpu"
    cfg.elo = elo
    cfg.temperature = 0.0
    cfg.top_p = 1.0
    cfg.multipv = 5
    cfg.history = 8
    cfg.use_uci_history = False
    cfg.include_time_info = False
    cfg.seed = 42
    cfg.use_amp = False
    cfg.checkpoint_path = None
    cfg.checkpoint_filename = None
    cfg.cache_dir = None
    cfg.revision = None
    cfg.local_files_only = False
    cfg.force_download = False
    cfg.hf_token = None
    cfg.trust_checkpoint = False
    cfg.model_spec = None
    spec = resolve_model_spec("maia3-5m")
    apply_model_config(cfg, spec)
    cfg.model_spec = spec
    from maia3.uci import Maia3UCIEngine
    engine = Maia3UCIEngine(cfg)
    engine.ensure_model_loaded()
    engine.board = chess.Board()
    return engine


def maia3_bestmove(engine, board: chess.Board) -> chess.Move | None:
    """Get Maia3's best move."""
    engine.board = board.copy()
    engine._reset_history()
    move, _ = engine.score_moves()
    return move


def main():
    print(f"Stockfish 18 (depth {SF_DEPTH}, hash {SF_HASH}MB, {SF_THREADS} threads)")
    print("=" * 60)

    engine = load_maia3(MAIA_ELOS[0])

    for sf_elo in SF_ELOS:
        for maia_elo in MAIA_ELOS:
            engine.self_elo = maia_elo
            engine.oppo_elo = maia_elo
            board = chess.Board()
            move_num = 0

            while not board.is_game_over() and move_num < MAX_MOVES:
                move_num += 1
                fen = board.fen()

                if board.turn == chess.WHITE:
                    move = maia3_bestmove(engine, board)
                    if move is None:
                        break
                    board.push(move)
                else:
                    uci = stockfish_bestmove(fen, depth=SF_DEPTH, elo=sf_elo)
                    if uci is None:
                        break
                    move_obj = chess.Move.from_uci(uci)
                    if move_obj not in board.legal_moves:
                        legal = list(board.legal_moves)[0]
                        board.push(legal)
                    else:
                        board.push(move_obj)

            result = board.result()
            if board.is_checkmate():
                winner = "Maia3" if board.turn == chess.BLACK else "SF"
                outcome = f"{winner} checkmate"
            elif board.is_stalemate() or board.is_insufficient_material():
                outcome = "Draw"
            else:
                from core.env.chess_game_env import _material_balance
                diff = _material_balance(board)
                if abs(diff) >= 15:
                    winner = "Maia3" if diff > 0 else "SF"
                    outcome = f"{winner} (mat +{diff:+d})"
                else:
                    outcome = f"Draw (mat +{diff:+d})"

            print(f"SF {sf_elo:>4} vs Maia3 {maia_elo:>4}: {result}  {outcome}  ({move_num}m)")

if __name__ == "__main__":
    main()
