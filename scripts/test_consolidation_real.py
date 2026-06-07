"""Consolidation test — real LLM call with rich structured logging.

Reuses the _write_log pattern from run_learning_dryrun.py.
Produces:
  - consolidation_env_io.log   — Knowledge state, consolidation analysis, LLM summary
  - consolidation_prompt.log   — Full system + user prompt
  - consolidation_response.log — Raw + parsed LLM response
  - l0_5_1.log / l2.log / l3.log — Per-layer agent logs (setup_layer_logging)

LearningEnv runs dry_run=True — NO knowledge modifications applied.

Usage:
    python scripts/test_consolidation_real.py
"""
from __future__ import annotations
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _write_log(path: Path, title: str, content: str):
    with open(path, "a", encoding="utf-8") as f:
        f.write(f"\n{'=' * 60}\n")
        f.write(f"  {title}\n")
        f.write(f"{'=' * 60}\n\n")
        f.write(content)
        f.write("\n")


# ═══════════════════════════════════════════════════════════════════════════
# Mock data
# ═══════════════════════════════════════════════════════════════════════════

class _MockDomain:
    def __init__(self, p): self.path = p


class MockCard:
    def __init__(self, id, content, confidence, domain_path, activation=0.5):
        self.id = id; self.content = content; self.confidence = confidence
        self.activation = activation; self.domain = _MockDomain(domain_path)


class MockSkill:
    def __init__(self, name, description, domain_path):
        self.name = name; self.description = description
        self.domain = _MockDomain(domain_path)


def _make_cards() -> list[MockCard]:
    cards = []
    for i in range(5):
        cards.append(MockCard(f"card_good_{i:03d}",
            f"Leduc pre-flop strategy variant {i}: With King always raise. "
            f"With Queen evaluate, with Jack consider folding.", 0.7 + i * 0.03, "game/leduc"))
    for i in range(8):
        cards.append(MockCard(f"card_dup_{i:03d}",
            f"Pre-flop: when holding King raise aggressively. Variant {i}.", 0.5, "game/leduc"))
    for i in range(10):
        cards.append(MockCard(f"card_low_{i:03d}",
            f"Experimental {i}: unconventional play. Not well tested.", 0.2, "game/leduc"))
    for i in range(10):
        cards.append(MockCard(f"card_dz_{i:03d}",
            f"DouDizhu strategy {i}: top-card with singles >= 10.", 0.6 + i * 0.02, "game/doudizhu"))
    for i in range(5):
        cards.append(MockCard(f"card_cons_{i:03d}",
            f"Consolidation rule {i}: merge similar entries, archive unused ones.", 0.8, "learning/consolidate"))
    return cards


def _make_skills() -> list[MockSkill]:
    skills = []
    for i in range(10):
        skills.append(MockSkill(f"leduc-skill-{i:02d}", f"Leduc skill variant {i}", "game/leduc"))
    for i in range(8):
        skills.append(MockSkill(f"doudizhu-skill-{i:02d}", f"DouDizhu skill variant {i}", "game/doudizhu"))
    for i in range(7):
        skills.append(MockSkill(f"generic-skill-{i:02d}", f"Generic strategy pattern {i}", "game"))
    return skills


class MockL2:
    def __init__(self): self.cards = _make_cards()


class MockL3:
    def __init__(self): self._s = _make_skills()
    def list_all(self): return self._s


# ═══════════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════════

def main():
    import tempfile
    from core.env.learning_env import LearningEnv, load_consolidation_spec
    from core.llm_factory import build_llm_client
    from core.env_loader import load_env

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_dir = PROJECT_ROOT / "logs" / "consolidation_real" / stamp
    log_dir.mkdir(parents=True, exist_ok=True)

    env_log = log_dir / "consolidation_env_io.log"
    prompt_log = log_dir / "consolidation_prompt.log"
    response_log = log_dir / "consolidation_response.log"

    print(f"Log dir: {log_dir}")
    print(f"  Env I/O:     {env_log.name}")
    print(f"  Prompt:      {prompt_log.name}")
    print(f"  Response:    {response_log.name}")

    # ── Layer agent logs ──────────────────────────────────────────
    from core.layers.logging_setup import setup_layer_logging
    setup_layer_logging(log_dir)
    print(f"  Agent layers: l0_5_1.log, l2.log, l3.log, executor.log")

    # ── Load env + LLM ──
    load_env(PROJECT_ROOT)
    llm = build_llm_client(PROJECT_ROOT / "config.yaml", temperature=0.1)

    _write_log(env_log, "LLM Client",
               f"model: {llm.model}\n"
               f"temperature: 0.1")

    # ── Build mock knowledge stores ──
    l2 = MockL2()
    l3 = MockL3()
    knowledge = {"l2": l2, "l3": l3}

    _write_log(env_log, "Knowledge state (pre-consolidation)",
               f"L2 cards: {len(l2.cards)} (limit=30)\n" +
               "\n".join(f"  [{c.id}] [{c.domain.path}] conf={c.confidence:.2f} {c.content[:100]}"
                         for c in l2.cards) +
               f"\n\nL3 skills: {len(l3.list_all())} (limit=20)\n" +
               "\n".join(f"  [{s.name}] [{s.domain.path}] {s.description[:100]}"
                         for s in l3.list_all()))

    # ── Build spec + check consolidation ──
    spec = load_consolidation_spec()
    _write_log(env_log, "Consolidation spec loaded",
               f"keys: {list(spec.keys())}\n"
               f"L2 limits: soft={spec['l2']['limits']['soft']}, hard={spec['l2']['limits']['hard']}\n"
               f"L3 limits: soft={spec['l3']['limits']['soft']}, hard={spec['l3']['limits']['hard']}")

    lenv = LearningEnv(
        Path(tempfile.mkdtemp()),
        knowledge,
        dry_run=True,
        l2_card_limit=30,
        l3_skill_limit=20,
        consolidation_spec=spec,
    )

    needs = lenv.needs_consolidation()
    level = lenv.get_consolidation_level()
    _write_log(env_log, "Consolidation analysis",
               f"needs_consolidation: {needs}\n"
               f"level: {level} ({spec['consolidation_levels'][level]['label']})\n"
               f"trigger: {spec['consolidation_levels'][level].get('trigger', '-')}\n"
               f"strategy:\n{spec['consolidation_levels'][level].get('strategy', '-')}\n"
               f"reversible: {spec['consolidation_levels'][level].get('reversible', '-')}")

    assert needs
    assert level == 2

    # ── Build consolidation task ──
    task = lenv.build_consolidation_task()
    _write_log(env_log, "TaskObservation built",
               f"meta: {len(task.meta)} chars\n"
               f"session: {json.dumps(task.session, ensure_ascii=False)}\n\n"
               f"--- META PREVIEW (first 500 chars) ---\n{task.meta[:500]}\n...")

    # ── System prompt ──
    system_prompt = (
        "你是一个知识库维护 Agent。分析当前知识库状况并给出整理建议。\n\n"
        "规则：\n"
        "1. 识别可合并的相似条目（同一 domain 下内容高度重叠的卡片合并为一条）\n"
        "2. 标记低激活度、从未使用、confidence<0.3 的条目为待删除\n"
        "3. 每个 modification 必须包含 target（精确的卡片/技能 ID）和 reason\n"
        "4. 使用 deprecate 而非 delete（保持可回滚）\n"
        "5. 如果创建合并后的新条目，使用 create 并填写完整的 content\n"
        "6. 不同 domain 的条目不要跨域合并\n\n"
        "输出格式：返回 JSON，各层 modifications 以 l1_modifications / l2_modifications / "
        "l3_modifications 为 key。每条 modification 包含 type（create/update/deprecate）、"
        "target（ID）、reason、payload（含 content）。"
    )

    # ── Log full prompt ──
    _write_log(prompt_log, "SYSTEM PROMPT", system_prompt)
    _write_log(prompt_log, "USER PROMPT (consolidation task meta)", task.meta)

    # ── Call LLM ──
    _write_log(env_log, "Dispatching to LLM",
               f"system: {len(system_prompt)} chars\n"
               f"user meta: {len(task.meta)} chars\n"
               f"total: {len(system_prompt) + len(task.meta)} chars\n"
               f"json_mode: True")

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": task.meta},
    ]
    resp = llm.chat(messages=messages, json_mode=True)
    raw_text = resp.text if hasattr(resp, 'text') else str(resp)

    # ── Log response ──
    _write_log(response_log, "RAW LLM RESPONSE", raw_text)

    try:
        parsed = json.loads(raw_text)
        _write_log(response_log, "PARSED JSON", json.dumps(parsed, ensure_ascii=False, indent=2))

        # Per-layer summary
        summary_lines = []
        for mod_key in ("l1_modifications", "l2_modifications", "l3_modifications"):
            mods = parsed.get(mod_key, [])
            if not isinstance(mods, list) or not mods:
                summary_lines.append(f"{mod_key}: 0 modifications")
                continue
            types = {}
            for m in mods:
                t = m.get("type", "?")
                types[t] = types.get(t, 0) + 1
            summary_lines.append(f"{mod_key}: {len(mods)} modifications {types}")
        _write_log(env_log, "LLM response summary", "\n".join(summary_lines))
    except json.JSONDecodeError:
        _write_log(env_log, "LLM response (invalid JSON)", raw_text[:2000])

    _write_log(env_log, "Done", f"dry_run=True — no modifications applied")
    print(f"\nDone. Log: {log_dir}")


if __name__ == "__main__":
    main()
