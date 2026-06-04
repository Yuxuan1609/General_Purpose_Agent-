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
    # Phase 2: Learning pipeline
    learning_enabled: bool = True
    learning_task_count_weight: float = 1.0
    learning_complexity_weight: float = 1.0
    learning_baseline_tokens: int = 2000
    learning_threshold: float = 5.0
    learning_pending_dir: Path = Path("./data/learning/pending")
    learning_learned_dir: Path = Path("./data/learning/learned")
    learning_raw_dir: Path = Path("./data/learning/raw")
