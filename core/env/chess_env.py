"""Chess learning environment powered by Maia3 chess engine.

Evaluates agent moves against Maia3's human-like move predictions
across configurable Elo levels. Supports puzzle mode and full self-play.
"""
from __future__ import annotations
import json
import logging
import random
from dataclasses import dataclass, field
from pathlib import Path

import chess
from core.env.base import Environment, EnvState, EnvStep

logger = logging.getLogger(__name__)

_KNOWN_PUZZLES = [
    ("r1bqkb1r/pppp1ppp/2n2n2/4p3/2B1P3/5N2/PPPP1PPP/RNBQK2R w KQkq - 4 4", "d2d3"),
    ("r1bqkb1r/pppp1ppp/2n2n2/4p3/2B1P3/5N2/PPPP1PPP/RNBQ1RK1 b kq - 5 4", "f8c5"),
    ("rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR w KQkq - 0 2", "g1f3"),
    ("r1bqkbnr/pppp1ppp/2n5/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R w KQkq - 2 3", "f1b5"),
    ("rnbqk2r/pppp1ppp/5n2/2b1p3/2B1P3/5N2/PPPP1PPP/RNBQK2R w KQkq - 4 4", "d2d3"),
    ("r1bqkbnr/pppp1ppp/2n5/1B2p3/4P3/5N2/PPPP1PPP/RNBQK2R b KQkq - 3 3", "a7a6"),
    ("rnbqkbnr/ppp2ppp/3p4/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R w KQkq - 0 3", "f1c4"),
    ("r1bqk2r/pppp1ppp/2n2n2/2b1p3/2B1P3/3P1N2/PPP2PPP/RNBQK2R b KQkq - 0 5", "d7d6"),
    ("rnbqkb1r/ppp2ppp/3p1n2/4p3/2B1P3/5N2/PPPP1PPP/RNBQK2R w KQkq - 0 4", "d2d3"),
    ("r1bqkb1r/ppp2ppp/2np1n2/4p3/2BPP3/5N2/PPP2PPP/RNBQK2R b KQkq d3 0 5", "e5d4"),
]


@dataclass
class ChessPuzzle:
    fen: str
    expected_move: str = ""
    description: str = ""
    elo_target: int = 1500


class ChessEnv(Environment):
    """Chess evaluation environment using Maia3 for move quality scoring.

    Presents chess positions to the agent. Agent uses tools to analyze
    and choose a move. Reward is based on how close the agent's move
    matches Maia3's top predictions at the target Elo level.

    Modes:
      - puzzle: Fixed set of known-good moves (mate-in-N, tactical patterns)
      - random: Random legal chess positions for open-ended evaluation
    """

    def __init__(self, model: str = "maia3-5m", elo: int = 1500,
                 temperature: float = 0.0, device: str = "cpu",
                 puzzles: list[ChessPuzzle] | None = None,
                 max_turns: int = 10):
        self._model_name = model
        self._elo = elo
        self._temperature = temperature
        self._device = device
        self._max_turns = max_turns

        self._puzzles: list[ChessPuzzle] = puzzles or []
        if not self._puzzles:
            for fen, move in _KNOWN_PUZZLES:
                board = chess.Board(fen)
                self._puzzles.append(ChessPuzzle(
                    fen=fen, expected_move=move,
                    description=f"{board.fullmove_number}. {_describe_position(board)}",
                    elo_target=elo,
                ))

        self._engine = None
        self._board: chess.Board | None = None
        self._current_puzzle: ChessPuzzle | None = None
        self._puzzle_index: int = 0
        self._turn_count: int = 0
        self._total_score: float = 0.0
        self._move_history: list[dict] = []

    def _ensure_engine(self):
        if self._engine is not None:
            return
        logger.info("Loading Maia3 engine: %s (device=%s, elo=%d)",
                     self._model_name, self._device, self._elo)

        from maia3.model_registry import resolve_model_spec, apply_model_config
        import argparse

        cfg = argparse.Namespace()
        cfg.model = self._model_name
        cfg.device = self._device
        cfg.elo = self._elo
        cfg.temperature = self._temperature
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

        spec = resolve_model_spec(self._model_name)
        apply_model_config(cfg, spec)
        cfg.model_spec = spec

        from maia3.uci import Maia3UCIEngine
        self._engine = Maia3UCIEngine(cfg)
        self._engine.ensure_model_loaded()
        logger.info("Maia3 engine ready")

    def reset(self, task_description: str = "") -> EnvState:
        self._ensure_engine()
        self._turn_count = 0
        self._total_score = 0.0
        self._move_history.clear()

        self._puzzle_index = 0
        return self._next_puzzle()

    def _next_puzzle(self) -> EnvState:
        if self._puzzle_index >= len(self._puzzles):
            self._puzzle_index = 0

        self._current_puzzle = self._puzzles[self._puzzle_index]
        self._board = chess.Board(self._current_puzzle.fen)
        self._engine.board = self._board.copy()
        self._engine._reset_history()

        side = "白方" if self._board.turn == chess.WHITE else "黑方"
        fen = self._current_puzzle.fen
        desc = self._current_puzzle.description

        observation = (
            f"[棋局 #{self._puzzle_index + 1}/{len(self._puzzles)}] {desc}\n"
            f"当前: {side}走棋\n"
            f"FEN: {fen}\n\n"
            f"请分析当前棋局并选择一步最佳走法。\n"
            f"输出要求：分析后给出 UCI 格式走法（如 e2e4、g1f3），"
            f"以 'move: <uci>' 结尾。"
        )

        self._puzzle_index += 1
        return EnvState(observation=observation, info={
            "fen": fen, "side": "white" if self._board.turn == chess.WHITE else "black",
            "puzzle_index": self._puzzle_index,
            "legal_moves": [m.uci() for m in self._board.legal_moves],
        })

    def step(self, action: str) -> EnvStep:
        if self._board is None or self._current_puzzle is None:
            return EnvStep(state=EnvState(observation="No active game"), reward=0.0, done=True)

        self._turn_count += 1

        move_uci = _extract_move(action)
        if not move_uci:
            legal = [m.uci() for m in self._board.legal_moves]
            return EnvStep(
                state=EnvState(observation=f"无法解析走法。合法走法: {', '.join(legal[:10])}"),
                reward=-0.5,
                done=False,
            )

        try:
            agent_move = chess.Move.from_uci(move_uci)
        except ValueError:
            return EnvStep(
                state=EnvState(observation=f"无效 UCI 走法: {move_uci}"),
                reward=-0.5,
                done=False,
            )

        if agent_move not in self._board.legal_moves:
            return EnvStep(
                state=EnvState(observation=f"非法走法: {move_uci}"),
                reward=-1.0,
                done=False,
            )

        try:
            _, top_moves = self._engine.score_moves()
        except Exception as e:
            logger.exception("Maia3 score_moves failed")
            return EnvStep(
                state=EnvState(observation=f"引擎错误: {e}"),
                reward=0.0,
                done=False,
            )

        maia_top_uci = [item["move"].uci() for item in top_moves]

        rank = _find_rank(move_uci, maia_top_uci)
        if rank == 0:
            reward = 1.0
            result_msg = f"**PERFECT!** 你的走法 {move_uci} 正是 Maia3 的首选走法。"
        elif rank > 0:
            reward = 0.5 / rank
            result_msg = (f"good: {move_uci} 在 Maia3 的推荐中排第 {rank + 1} 位。"
                          f"首选: {maia_top_uci[0]}")
        else:
            reward = -0.5
            result_msg = (f"miss: {move_uci} 不在 Maia3 的 Top-{len(top_moves)} 推荐中。"
                          f"首选: {maia_top_uci[0]} | 你的走法: {move_uci}")

        self._total_score += reward
        self._board.push(agent_move)
        self._move_history.append({
            "fen_before": self._current_puzzle.fen,
            "agent_move": move_uci,
            "maia_top1": maia_top_uci[0],
            "maia_top5": maia_top_uci,
            "reward": reward,
        })

        done = self._turn_count >= self._max_turns
        next_state = self._next_puzzle() if not done else EnvState(
            observation=f"测试完成。总分: {self._total_score:.1f}/{self._turn_count}",
            info={"total_score": self._total_score, "turns": self._turn_count},
        )

        return EnvStep(
            state=EnvState(
                observation=f"{result_msg}\n\n{next_state.observation}",
                info={**next_state.info, "maia_top1": maia_top_uci[0],
                      "maia_top5": maia_top_uci, "reward": reward},
            ),
            reward=reward,
            done=done,
        )

    @property
    def tool_policy(self) -> dict | None:
        return {
            "allowed": ["read_file", "grep", "web_search", "tavily_search",
                        "terminal", "sysinfo", "ask_user", "l1_query"],
        }

    @property
    def move_history(self) -> list[dict]:
        return self._move_history


def _extract_move(action: str) -> str:
    """Extract UCI move from agent's response text."""
    import re
    for pattern in [
        r'move:\s*([a-h][1-8][a-h][1-8][qrbn]?)',
        r'走法[：:]\s*([a-h][1-8][a-h][1-8][qrbn]?)',
        r'([a-h][1-8][a-h][1-8][qrbn]?)',
    ]:
        m = re.search(pattern, action, re.IGNORECASE)
        if m:
            return m.group(1)
    return ""


def _find_rank(move_uci: str, top_list: list[str]) -> int:
    for i, m in enumerate(top_list):
        if m == move_uci:
            return i
    return -1


def _describe_position(board: chess.Board) -> str:
    if board.is_check():
        return "将军局面"
    if board.is_checkmate():
        return "将杀局面"
    move_num = board.fullmove_number
    if move_num <= 5:
        return "开局"
    if move_num <= 15:
        return "中局"
    if len(board.piece_map()) <= 10:
        return "残局"
    return "中局"


def generate_random_puzzles(count: int = 10) -> list[ChessPuzzle]:
    """Generate random legal chess positions for testing."""
    puzzles = []
    for _ in range(count):
        board = chess.Board()
        for _ in range(random.randint(3, 15)):
            legal = list(board.legal_moves)
            if not legal:
                break
            board.push(random.choice(legal))
        if board.is_game_over():
            continue
        puzzles.append(ChessPuzzle(
            fen=board.fen(),
            description=f"{_describe_position(board)} 随机局面",
            elo_target=1500,
        ))
    return puzzles
