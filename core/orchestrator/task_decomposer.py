"""Task Decomposer — splits sessions into evaluable LearningUnit objects."""
from pathlib import Path
from core.task import LearningUnit, Domain


class TaskDecomposer:
    """Decompose a session into LearningUnit objects.

    Uses rule-based strategy selection. Future: LLM-based decomposition.
    """

    def decompose(self, session: dict, raw_log: Path) -> list[LearningUnit]:
        strategy = self._select_strategy(session)
        return strategy(session, raw_log)

    def _select_strategy(self, session: dict):
        domain_path = session.get("domain", "unknown")
        registry = {
            "game/doudizhu": self._decompose_game_unit,
            "game/leduc":    self._decompose_game_unit,
            "coding/session": self._decompose_coding,
        }
        return registry.get(domain_path, self._decompose_game_unit)

    def _decompose_game_unit(self, session: dict, raw_log) -> list[LearningUnit]:
        domain_path = session.get("domain", "game/unknown")
        domain = Domain(domain_path, "specific")
        return [LearningUnit(
            description=session["id"],
            domain=domain,
            enable_learning=session.get("enable_learning", False),
        )]

    def _decompose_coding(self, session: dict, raw_log: Path) -> list[LearningUnit]:
        return [LearningUnit(
            description=session["id"],
            domain=Domain("coding/session", "specific"),
            enable_learning=True,
            token_count=_count_tokens(raw_log) if raw_log.exists() else 0,
        )]


def _count_tokens(path: Path) -> int:
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
        return len(text) // 4
    except Exception:
        return 0
