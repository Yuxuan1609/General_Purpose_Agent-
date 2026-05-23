from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class AgentConfig:
    main_llm: Any = None
    auxiliary_llm: Any = None
    max_iterations: int = 50
    l1_max_rules: int = 20
    l1_max_rule_length: int = 100
    l1_rules_path: Path = Path("./data/l1_rules.json")
    skills_dir: Path = Path("./skills")
    knowledge_dir: Path = Path("./knowledge")
    l2_index_path: Path = Path("./knowledge/l2_index.json")
    seed_l1_rules: list[str] | None = None
    seed_l2_cards: list[dict] | None = None
    seed_l3_skills: list[Path] | None = None
