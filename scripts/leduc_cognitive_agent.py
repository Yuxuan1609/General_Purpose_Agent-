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

    def eval_step(self, state):
        return self._decide(state)

    def step(self, state):
        return self._decide(state)

    def reset_session(self, session_id: str = ""):
        self._step = 0
        self._session_id = session_id

    def _decide(self, state):
        raw = state["raw_obs"]
        legal_names = raw["legal_actions"]
        self._step += 1

        obs = TaskObservation(
            meta={
                "domain": "game/leduc",
                "role": "Player 0",
                "step": self._step,
                "enable_learning": True,
            },
            state=self._build_state(raw),
            history=None,
            session={
                "id": self._session_id,
                "task_type": "game/leduc",
                "step_index": self._step,
            } if self._session_id else None,
        )

        result = self._executor.execute(obs)
        action_text = result["action_text"].strip().lower()

        action_name = self._parse_action(action_text, legal_names)
        logger.info("Step | hand=%s public=%s legal=%s → %s",
                     raw.get("hand"), raw.get("public_card"), legal_names, action_name)

        action_id = list(state["legal_actions"].keys())[legal_names.index(action_name)]
        return action_id, {}

    def _build_state(self, raw: dict) -> dict:
        hand_str = CARD_MAP.get(raw["hand"], raw["hand"])
        public = raw["public_card"]
        public_str = "not yet dealt" if public is None else CARD_MAP.get(public, str(public))
        chips = raw.get("all_chips", [0, 0])
        my_chips = raw.get("my_chips", 0)

        legal = raw["legal_actions"]
        round_name = "pre-flop" if "check" not in legal and raw["public_card"] is None else "post-flop"

        user_prompt = (
            f"=== Round: {round_name} ===\n"
            f"Your card: {hand_str}\n"
            f"Public card: {public_str}\n"
            f"Your bet this round: {my_chips}\n"
            f"Opponent bet this round: {chips[1]}\n"
            f"Total pot: {sum(chips)}\n"
            f"Legal actions: {', '.join(legal)}\n"
            f"Choose:"
        )

        return {
            "system_prompt": LEDUC_SYSTEM_PROMPT,
            "prompt": user_prompt,
            "hand": raw["hand"],
            "public_card": str(raw["public_card"]),
            "legal_actions": legal,
            "round": round_name,
            "my_chips": my_chips,
            "pot": sum(chips),
        }

    def _parse_action(self, text: str, legal_actions: list[str]) -> str:
        text_lower = text.lower()
        for act in legal_actions:
            if act.lower() in text_lower:
                return act
        return legal_actions[0]
