"""
Leduc Cognitive Agent — RLCard agent that uses the Cognitive Agent architecture.

Implements RLCard agent interface (eval_step/step), wraps Executor + LayerChain
for poker decision-making.
"""
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.types import TaskObservation

logger = logging.getLogger("leduc_cognitive")

LEDUC_SYSTEM_PROMPT = """You are playing Leduc Hold'em. Your goal is to MAXIMIZE expected chips.

Cards: K, Q, J in spades(SP) and hearts(HR). SP > HR in ties.
2 players. Player 0 posts 1 chip, acts first. Player 1 posts 2 chips.

Pre-flop: call, raise(2 chips), or fold. Max 2 raises per round.
Post-flop: public card dealt. check/call, raise(4 chips), or fold.

Pair (card matches public) beats no pair. Higher rank wins ties, then suit.
Output ONLY one word: call, raise, fold, or check."""

CARD_MAP = {
    "SJ": "J♠", "SQ": "Q♠", "SK": "K♠",
    "HJ": "J♥", "HQ": "Q♥", "HK": "K♥",
}


class LeducCognitiveAgent:
    """RLCard-compatible agent using the Cognitive Agent architecture."""

    def __init__(self, executor, temperature: float = 0.1):
        self._executor = executor
        self._temperature = temperature
        self.use_raw = False
        self._step = 0
        self._session_id = ""
        self._history: list[str] = []

    def eval_step(self, state):
        return self._decide(state)

    def step(self, state):
        return self._decide(state)

    def reset_session(self, session_id: str = ""):
        self._step = 0
        self._session_id = session_id
        self._history = []

    def _decide(self, state):
        raw = state["raw_obs"]
        legal_names = raw["legal_actions"]
        self._step += 1

        current_text = self._build_current_text(raw)
        history_text = "\n".join(f"  {h}" for h in self._history[-6:])

        obs = TaskObservation(
            meta=LEDUC_SYSTEM_PROMPT,
            state={
                "current": current_text,
                "history": history_text,
            },
            session={
                "id": self._session_id,
                "domain": "game/leduc",
                "step_index": self._step,
            } if self._session_id else None,
        )

        result = self._executor.execute(obs)
        action_text = result["action_text"].strip().lower()

        action_name = self._parse_action(action_text, legal_names)
        self._history.append(
            f"Step {self._step} | hand={raw.get('hand')} public={raw.get('public_card')} "
            f"legal={legal_names} → {action_name}"
        )
        logger.info("Step | hand=%s public=%s legal=%s → %s",
                     raw.get("hand"), raw.get("public_card"), legal_names, action_name)

        action_id = list(state["legal_actions"].keys())[legal_names.index(action_name)]
        return action_id, {}

    def _build_current_text(self, raw: dict) -> str:
        hand_str = CARD_MAP.get(raw["hand"], raw["hand"])
        public = raw["public_card"]
        public_str = "not yet dealt" if public is None else CARD_MAP.get(public, str(public))
        chips = raw.get("all_chips", [0, 0])
        my_chips = raw.get("my_chips", 0)
        legal = raw["legal_actions"]
        round_name = "pre-flop" if "check" not in legal and raw["public_card"] is None else "post-flop"

        return (
            f"=== Round: {round_name} ===\n"
            f"Your card: {hand_str}\n"
            f"Public card: {public_str}\n"
            f"Your bet this round: {my_chips}\n"
            f"Opponent bet this round: {chips[1]}\n"
            f"Total pot: {sum(chips)}\n"
            f"Legal actions: {', '.join(legal)}\n"
            f"Choose:"
        )

    def _parse_action(self, text: str, legal_actions: list[str]) -> str:
        text_lower = text.lower()
        for act in legal_actions:
            if act.lower() in text_lower:
                return act
        return legal_actions[0]
