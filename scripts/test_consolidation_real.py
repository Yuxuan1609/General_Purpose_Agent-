"""Real LLM consolidation task test.

Creates mock knowledge stores with cards/skills BEYOND limits,
builds a consolidation TaskObservation using the consolidation.yaml spec,
sends it to DeepSeek API, and logs the full prompt + response.

LearningEnv runs in dry_run=True — NO actual knowledge modifications.

Usage:
    python scripts/test_consolidation_real.py
"""
from __future__ import annotations
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _setup_logging():
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_dir = PROJECT_ROOT / "logs" / "consolidation_real" / stamp
    log_dir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("consolidation_real")
    logger.setLevel(logging.DEBUG)
    fh = logging.FileHandler(log_dir / "test.log", encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter("%(asctime)s | %(levelname)-7s | %(message)s"))
    logger.addHandler(fh)
    return logger, log_dir


logger, LOG_DIR = _setup_logging()


# ═══════════════════════════════════════════════════════════════════════════
# Setup: mock knowledge stores with items BEYOND limits
# ═══════════════════════════════════════════════════════════════════════════

class MockCard:
    def __init__(self, id: str, content: str, confidence: float, domain_path: str,
                 activation: float = 0.5):
        self.id = id
        self.content = content
        self.confidence = confidence
        self.activation = activation
        self.domain = _MockDomain(domain_path)


class MockSkill:
    def __init__(self, name: str, description: str, domain_path: str):
        self.name = name
        self.description = description
        self.domain = _MockDomain(domain_path)


class _MockDomain:
    def __init__(self, path: str):
        self.path = path


def _build_mock_cards() -> list[MockCard]:
    """Generate 38 L2 cards (8 over hard limit of 30) with various overlap and quality."""
    cards = []
    # Good cards — high confidence, domain-specific
    for i in range(5):
        cards.append(MockCard(
            f"card_good_{i:03d}",
            f"Leduc pre-flop strategy variant {i}: With King always raise, "
            f"with Queen evaluate, with Jack consider folding. "
            f"Adjust based on opponent's previous betting patterns.",
            0.7 + i * 0.03, "game/leduc",
        ))
    # Nearly-duplicate cards (should be merged)
    for i in range(8):
        cards.append(MockCard(
            f"card_dup_{i:03d}",
            f"Pre-flop strategy: when holding King raise aggressively. "
            f"Variant {i}: consider opponent position and stack size.",
            0.5, "game/leduc",
        ))
    # Low-confidence, never-used cards
    for i in range(10):
        cards.append(MockCard(
            f"card_low_{i:03d}",
            f"Experimental strategy {i}: try unconventional play patterns. "
            f"May work against aggressive opponents. Not well tested.",
            0.2 + i * 0.01, "game/leduc",
        ))
    # DouDizhu cards (different domain, should be kept)
    for i in range(10):
        cards.append(MockCard(
            f"card_dz_{i:03d}",
            f"DouDizhu strategy {i}: As landlord_up player, top-card with "
            f"singles >= 10. Control bomb usage timing.",
            0.6 + i * 0.02, "game/doudizhu",
        ))
    # Consolidation domain cards (keep these)
    for i in range(5):
        cards.append(MockCard(
            f"card_cons_{i:03d}",
            f"Consolidation rule {i}: When knowledge base overflows, "
            f"merge similar entries and archive unused ones.",
            0.8, "learning/consolidate",
        ))
    return cards


def _build_mock_skills() -> list[MockSkill]:
    """Generate 25 L3 skills (5 over hard limit of 20)."""
    skills = []
    for i in range(10):
        skills.append(MockSkill(
            f"leduc-skill-{i:02d}",
            f"Leduc strategy skill variant {i}: handling pre-flop and post-flop situations",
            "game/leduc",
        ))
    for i in range(8):
        skills.append(MockSkill(
            f"doudizhu-skill-{i:02d}",
            f"DouDizhu advanced play pattern {i}",
            "game/doudizhu",
        ))
    for i in range(7):
        skills.append(MockSkill(
            f"generic-skill-{i:02d}",
            f"Generic game strategy pattern {i}: abstract decision framework",
            "game",
        ))
    return skills


class MockL2:
    def __init__(self):
        self.cards = _build_mock_cards()


class MockL3:
    def __init__(self):
        self._skills = _build_mock_skills()

    def list_all(self):
        return self._skills


# ═══════════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════════

def main():
    import tempfile
    from core.env.learning_env import LearningEnv, load_consolidation_spec
    from core.llm_factory import build_llm_client

    logger.info("=" * 60)
    logger.info("  Real LLM Consolidation Task Test")
    logger.info("=" * 60)

    # ── Load env + LLM client ──
    from core.env_loader import load_env
    load_env(PROJECT_ROOT)
    llm = build_llm_client(PROJECT_ROOT / "config.yaml", temperature=0.1)
    logger.info("LLM client: model=%s", llm.model)

    # ── Build mock knowledge stores ──
    l2 = MockL2()
    l3 = MockL3()
    knowledge = {"l2": l2, "l3": l3}
    logger.info("Mock stores: L2 cards=%d (limit=30), L3 skills=%d (limit=20)",
                len(l2.cards), len(l3.list_all()))

    # ── Build LearningEnv with consolidation spec ──
    spec = load_consolidation_spec()
    logger.info("Consolidation spec loaded: %s", list(spec.keys()))

    lenv = LearningEnv(
        Path(tempfile.mkdtemp()),
        knowledge,
        dry_run=True,
        l2_card_limit=30,
        l3_skill_limit=20,
        consolidation_spec=spec,
    )

    assert lenv.needs_consolidation(), "Should trigger consolidation!"
    level = lenv.get_consolidation_level()
    logger.info("Consolidation triggered: level=%d (L2=%d/30, L3=%d/20)",
                level, len(l2.cards), len(l3.list_all()))

    # ── Build consolidation task ──
    task = lenv.build_consolidation_task()
    logger.info("TaskObservation: meta=%d chars, domain=%s",
                len(task.meta), task.session["domain"])

    # ── Log full meta to separate file ──
    meta_path = LOG_DIR / "consolidation_prompt.md"
    meta_path.write_text(task.meta, encoding="utf-8")
    logger.info("Full prompt saved to: %s", meta_path)

    # ── Send to LLM ──
    logger.info("Sending to LLM...")

    system_prompt = (
        "你是一个知识库维护 Agent。你的任务是分析当前知识库的状况，"
        "并给出整理建议。请严格按要求的 JSON 格式输出 modifications。\n\n"
        "规则：\n"
        "1. 识别可以合并的相似条目（内容高度重叠的卡片）\n"
        "2. 标记低激活度、从未使用、confidence 低且 failure_count 高的条目为待删除\n"
        "3. 每个 modification 必须包含 target（精确的卡片/技能 ID）和 reason\n"
        "4. 使用 deprecate 而非 delete（保持可回滚）\n"
        "5. 如果创建合并后的新条目，使用 create，并在 reason 中列出合并的源 ID"
    )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": task.meta},
    ]

    logger.info("Calling LLM with %d chars system + %d chars user prompt...",
                len(system_prompt), len(task.meta))

    resp = llm.chat(messages=messages, json_mode=True)
    response_text = resp.text if hasattr(resp, 'text') else str(resp)

    # ── Log response ──
    resp_path = LOG_DIR / "consolidation_response.json"
    try:
        parsed = json.loads(response_text)
        resp_path.write_text(
            json.dumps(parsed, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        logger.info("Response parsed as JSON, saved to: %s", resp_path)

        # Summary stats
        for mod_key in ("l1_modifications", "l2_modifications", "l3_modifications"):
            mods = parsed.get(mod_key, [])
            if isinstance(mods, list) and mods:
                types = {}
                for m in mods:
                    t = m.get("type", "?")
                    types[t] = types.get(t, 0) + 1
                logger.info("  %s: %d modifications %s", mod_key, len(mods), types)
    except json.JSONDecodeError:
        resp_path.write_text(response_text, encoding="utf-8")
        logger.warning("Response is not valid JSON, raw text saved")

    logger.info("=" * 60)
    logger.info("  Done. Logs: %s", LOG_DIR)
    logger.info("  Prompt: %s", meta_path.name)
    logger.info("  Response: %s", resp_path.name)
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
