"""Chess game environment — full self-play vs Maia3.

One move = one Executor round (like InteractionEnv's one user input round).
Agent plays one side, Maia3 plays the other. Game ends on checkmate/stalemate/draw.
"""
from __future__ import annotations
import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path

import chess
from core.env.base import Environment, EnvState, EnvStep
from core.types import TaskObservation

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "你正在与 Maia3 国际象棋引擎对弈。\n\n"
    "**每轮是独立上下文**：你不会看到之前的分析内容，只有当前局面和历史走法列表。\n"
    "请完整分析当前局面，不要假设你记得上一轮的推理。\n"
    "合法走法已由环境列出——你只需从中选择最佳的一个。\n\n"
    "**禁止安装或调用外部引擎（如 Stockfish、Leela）**。\n"
    "环境已提供所有所需信息（FEN + ASCII 棋盘 + 合法走法列表）。\n\n"
    "输出要求：\n"
    "- 分析当前局面（中心控制、王安全、子力活动性、战术威胁）\n"
    "- 列出 2-3 个候选走法并简要比较\n"
    "- 最终选择一步走法，以格式 'move: <uci>' 结尾（如 move: e2e4）"
)


class ChessGameEnv(Environment):
    """Full chess self-play environment. Agent vs Maia3.

    Flow:
      reset() → initial board
      for each move:
        receive_next() → build_task_observation() → Executor.execute → step(move)
      → until game over

    Agent plays White by default. Maia3 plays Black.
    """

    def __init__(self, model: str = "maia3-5m", elo: int = 1500,
                 temperature: float = 0.0, device: str = "cpu",
                 max_moves: int = 80, agent_plays: str = "white"):
        self._model_name = model
        self._elo = elo
        self._temperature = temperature
        self._device = device
        self._max_moves = max_moves
        self._agent_plays = agent_plays  # "white" or "black"

        self._engine = None
        self._board: chess.Board | None = None
        self._session_id: str = ""
        self._session_started_at: str = ""
        self._move_count: int = 0
        self._total_reward: float = 0.0
        self._history: list[dict] = []
        self._pending_state: EnvState | None = None
        self._game_over: bool = False
        self._game_result: str = ""

    def _ensure_engine(self):
        if self._engine is not None:
            return
        logger.info("Loading Maia3 engine: %s (elo=%d, device=%s)",
                     self._model_name, self._elo, self._device)

        from maia3.model_registry import resolve_model_spec, apply_model_config

        class _Cfg:
            pass
        cfg = _Cfg()
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
        self._session_id = uuid.uuid4().hex
        self._session_started_at = datetime.now(timezone.utc).isoformat()
        self._board = chess.Board()
        self._move_count = 0
        self._total_reward = 0.0
        self._history.clear()
        self._game_over = False
        self._game_result = ""

        # If agent plays black, Maia3 makes first move
        if self._agent_plays == "black":
            self._make_maia3_move()

        self._pending_state = self._build_observation()
        return self._pending_state

    def _build_observation(self) -> EnvState:
        side = "白方" if self._board.turn == chess.WHITE else "黑方"
        info = {
            "fen": self._board.fen(),
            "move_count": self._move_count,
            "total_reward": self._total_reward,
            "game_over": self._game_over,
            "game_result": self._game_result,
            "session_id": self._session_id,
        }

        if self._game_over:
            return EnvState(
                observation=f"对局结束。结果: {self._game_result}\n"
                            f"总步数: {self._move_count} | 总奖励: {self._total_reward:+.1f}\n\n"
                            f"最终局面 FEN: {self._board.fen()}",
                info=info,
            )

        legal = [m.uci() for m in self._board.legal_moves]
        move_history = self._format_move_history()
        board_text = _board_to_ascii(self._board)
        legal_text = _format_legal_moves(self._board)

        observation = (
            f"[第 {self._move_count + 1} 步] {side}走棋\n"
            f"FEN: {self._board.fen()}\n"
            f"\n{board_text}\n"
            f"{legal_text}\n"
            f"{move_history}"
            f"请分析局面并从上方合法走法中选择一步。以 'move: <uci>' 结尾。"
        )
        return EnvState(observation=observation, info=info)

    def _format_move_history(self) -> str:
        if not self._history:
            return ""
        agent_side = "白方" if self._agent_plays == "white" else "黑方"
        maia_side = "黑方" if self._agent_plays == "white" else "白方"
        lines = [f"[对局历史] 你是{agent_side}，Maia3是{maia_side}"]
        for h in self._history:
            agent_col = h.get(self._agent_plays, "")
            maia_col = h.get("maia3_move", "")
            lines.append(
                f"  {h['move_num']:2d}. 你: {agent_col or '--':6s}  Maia3: {maia_col or '--':6s}"
                f"  {'+' if h.get('agent_reward', 0) > 0 else '-' if h.get('agent_reward', 0) < 0 else ' '}"
            )
        return "\n".join(lines) + "\n\n"

    def build_task_observation(self) -> TaskObservation | None:
        if self._pending_state is None:
            return None
        return TaskObservation(
            meta=_SYSTEM_PROMPT,
            state={
                "current": self._pending_state.observation,
                "history": self._format_move_history(),
            },
            session={
                "id": self._session_id,
                "domain": "chess/game",
                "domains_hint": ["chess", "chess/game"],
                "step_index": self._move_count,
                "enable_learning": True,
            },
        )

    def step(self, action: str) -> EnvStep:
        if self._game_over:
            return EnvStep(
                state=EnvState(observation=f"对局已结束: {self._game_result}"),
                reward=0.0,
                done=True,
            )

        move_uci = _extract_move(action)
        if not move_uci:
            legal = [m.uci() for m in self._board.legal_moves]
            return EnvStep(
                state=self._build_observation(),
                reward=-0.5,
                done=False,
            )

        try:
            agent_move = chess.Move.from_uci(move_uci)
        except ValueError:
            return EnvStep(
                state=self._build_observation(),
                reward=-0.5,
                done=False,
            )

        if agent_move not in self._board.legal_moves:
            return EnvStep(
                state=self._build_observation(),
                reward=-1.0,
                done=False,
            )

        # Evaluate agent's move via Maia3
        reward = 0.0
        eval_str = ""
        try:
            engine_board = self._board.copy()
            self._engine.board = engine_board
            self._engine._reset_history()
            _, top_moves = self._engine.score_moves()
            if top_moves:
                top1_uci = top_moves[0]["move"].uci()
                top_uci_list = [t["move"].uci() for t in top_moves]
                rank = _find_rank(move_uci, top_uci_list)
                if rank == 0:
                    reward = 1.0
                    eval_str = "best"
                elif rank > 0:
                    reward = 0.5 / rank
                    eval_str = f"top{rank + 1}"
                else:
                    reward = -0.5
                    eval_str = f"miss (maia3={top1_uci})"
        except Exception as e:
            logger.warning("Maia3 eval failed: %s", e)

        # Push agent's move
        self._board.push(agent_move)
        self._move_count += 1

        # Record in history
        move_num = (self._move_count + 1) // 2
        entry = self._get_or_create_history_entry(move_num)
        side_key = "white" if self._agent_plays == "white" else "black"
        entry[side_key] = move_uci
        entry["agent_reward"] = reward
        entry["eval"] = eval_str

        self._total_reward += reward

        # Check game over after agent's move
        if self._check_game_over():
            return EnvStep(
                state=self._build_observation(),
                reward=reward + self._game_outcome_reward(),
                done=True,
            )

        # Maia3 responds
        self._make_maia3_move()
        entry["maia3_move"] = self._board.peek().uci()

        if self._check_game_over():
            return EnvStep(
                state=self._build_observation(),
                reward=reward,
                done=True,
            )

        if self._move_count >= self._max_moves:
            self._game_over = True
            self._game_result = "draw (max_moves)"
            return EnvStep(
                state=self._build_observation(),
                reward=reward,
                done=True,
            )

        self._pending_state = self._build_observation()
        return EnvStep(
            state=self._pending_state,
            reward=reward,
            done=False,
        )

    def _make_maia3_move(self):
        try:
            engine_board = self._board.copy()
            self._engine.board = engine_board
            self._engine._reset_history()
            move, _ = self._engine.score_moves()
            if move is None:
                return
            self._board.push(move)
            self._move_count += 1
        except Exception as e:
            logger.warning("Maia3 move failed: %s", e)

    def _check_game_over(self) -> bool:
        if not self._board.is_game_over():
            return False
        self._game_over = True
        outcome = self._board.outcome()
        if outcome is None:
            self._game_result = "draw"
        elif outcome.winner is None:
            self._game_result = "draw (stalemate)"
        elif (outcome.winner == chess.WHITE and self._agent_plays == "white") or \
             (outcome.winner == chess.BLACK and self._agent_plays == "black"):
            self._game_result = "agent wins"
        else:
            self._game_result = "maia3 wins"
        return True

    def _game_outcome_reward(self) -> float:
        if "agent wins" in self._game_result:
            return 3.0
        if "draw" in self._game_result:
            return 1.0
        return -3.0

    def _get_or_create_history_entry(self, move_num: int) -> dict:
        # move_num is a half-move pair index
        for h in self._history:
            if h["move_num"] == move_num:
                return h
        entry = {"move_num": move_num, "white": "", "black": "",
                 "agent_reward": 0.0, "eval": "", "maia3_move": ""}
        self._history.append(entry)
        return entry

    def get_history(self) -> list[dict]:
        return [dict(h) for h in self._history]

    def save_game(self, filepath: Path) -> Path:
        data = {
            "session_id": self._session_id,
            "started_at": self._session_started_at,
            "model": self._model_name,
            "elo": self._elo,
            "agent_plays": self._agent_plays,
            "result": self._game_result,
            "total_moves": self._move_count,
            "total_reward": self._total_reward,
            "final_fen": self._board.fen() if self._board else "",
            "history": self.get_history(),
            "saved_at": datetime.now(timezone.utc).isoformat(),
        }
        filepath.parent.mkdir(parents=True, exist_ok=True)
        filepath.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return filepath

    @property
    def tool_policy(self) -> dict | None:
        return {
            "allowed": ["read_file", "grep", "sysinfo", "ask_user", "l1_query"],
        }

    @property
    def is_game_over(self) -> bool:
        return self._game_over

    @property
    def game_result(self) -> str:
        return self._game_result

    @property
    def total_reward(self) -> float:
        return self._total_reward


def _extract_move(action: str) -> str:
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


def _board_to_ascii(board: chess.Board) -> str:
    """Render board as readable ASCII with coord labels for LLM consumption."""
    lines = []
    rank_lines = str(board).split("\n")
    for r in range(8):
        lines.append(f"  {8 - r}  {rank_lines[r]}  {8 - r}")
    lines.append("     a b c d e f g h")
    return "\n".join(lines)


def _format_legal_moves(board: chess.Board) -> str:
    """Group legal moves by piece type for LLM readability."""
    piece_names = {
        chess.PAWN: "兵", chess.KNIGHT: "马", chess.BISHOP: "象",
        chess.ROOK: "车", chess.QUEEN: "后", chess.KING: "王",
    }
    groups: dict[str, list[str]] = {}
    for move in board.legal_moves:
        piece = board.piece_at(move.from_square)
        name = piece_names.get(piece.piece_type, "?") if piece else "?"
        groups.setdefault(name, []).append(move.uci())

    lines = [f"[合法走法] 共 {board.legal_moves.count()} 步"]
    for name in ("王", "后", "车", "象", "马", "兵"):
        if name in groups:
            lines.append(f"  {name}: {', '.join(sorted(groups[name]))}")
    return "\n".join(lines)
