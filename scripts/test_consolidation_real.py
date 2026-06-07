"""Consolidation test — real LLM call with rich structured logging.

Loads test fixture data from standardized MD files in tests/fixtures/:
  - consolidation_test_leduc.md      → L2 cards (game/leduc, 15 cards)
  - consolidation_test_doudizhu.md    → L2 cards (game/doudizhu, 9 cards)
  - consolidation_test_skills.md      → L3 skills (7 skills)

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
import re
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
# Fixture loader — reads standardized MD files, populates FlexibleKnowledge
# ═══════════════════════════════════════════════════════════════════════════

def _parse_cards_from_md(path: Path) -> list[dict]:
    """Parse knowledge cards from a standard MD file.

    Expected format:
        ## card_id
        - confidence: 0.75
        Content text here...

    Returns list of {id, content, confidence, domain}.
    """
    cards = []
    text = path.read_text(encoding="utf-8")
    # Split by ## sections
    sections = re.split(r'\n(?=## )', text)
    for sec in sections:
        sec = sec.strip()
        if not sec or not sec.startswith("## "):
            continue
        lines = sec.split("\n")
        header = lines[0].replace("## ", "").strip()
        # The header may be a comment or a card_id
        if header.startswith("#") or header.lower() in ("leduc hold'em", "dou dizhu",
                                                          "conslidation test skills"):
            continue
        card_id = header
        confidence = 0.5
        content_lines = []
        in_meta = True
        for line in lines[1:]:
            match = re.match(r'- confidence:\s*([\d.]+)', line)
            if match:
                confidence = float(match.group(1))
                continue
            stripped = line.strip()
            if stripped and in_meta and (stripped.startswith("-") or stripped.startswith("domain:")):
                continue
            if stripped:
                in_meta = False
                content_lines.append(stripped)
        if content_lines:
            cards.append({
                "id": card_id,
                "content": " ".join(content_lines),
                "confidence": confidence,
            })
    return cards


def _parse_skills_from_md(path: Path) -> list[dict]:
    """Parse skill templates from MD file.

    Expected format:
        ## skill-name
        - confidence: 0.75
        Skill description content...
    """
    skills = []
    text = path.read_text(encoding="utf-8")
    sections = re.split(r'\n(?=## )', text)
    for sec in sections:
        sec = sec.strip()
        if not sec or not sec.startswith("## "):
            continue
        lines = sec.split("\n")
        header = lines[0].replace("## ", "").strip()
        if header.startswith("#"):
            continue
        skill_name = header
        confidence = 0.5
        content_lines = []
        for line in lines[1:]:
            match = re.match(r'- confidence:\s*([\d.]+)', line)
            if match:
                confidence = float(match.group(1))
                continue
            stripped = line.strip()
            if stripped:
                content_lines.append(stripped)
        if content_lines:
            skills.append({
                "name": skill_name,
                "content": " ".join(content_lines),
                "confidence": confidence,
            })
    return skills


def _load_fixtures_into_knowledge(fk, sl, fixtures_dir: Path):
    """Load consolidation test fixtures into FlexibleKnowledge + SkillLayer.

    Reads standardized MD files and calls fk.add_card() / sl.create_skill().
    Returns dict with {l2_count, l3_count}.
    """
    from core.task import Domain

    l2_count = 0
    l3_count = 0

    # L2: Leduc cards
    leduc_path = fixtures_dir / "consolidation_test_leduc.md"
    if leduc_path.exists():
        for card in _parse_cards_from_md(leduc_path):
            fk.add_card(
                content=card["content"],
                domain=Domain("game/leduc", "specific"),
                confidence=card["confidence"],
                source="test_fixture",
            )
            l2_count += 1

    # L2: DouDizhu cards
    dz_path = fixtures_dir / "consolidation_test_doudizhu.md"
    if dz_path.exists():
        for card in _parse_cards_from_md(dz_path):
            fk.add_card(
                content=card["content"],
                domain=Domain("game/doudizhu", "specific"),
                confidence=card["confidence"],
                source="test_fixture",
            )
            l2_count += 1

    # L3: test skills
    if sl is not None:
        skills_path = fixtures_dir / "consolidation_test_skills.md"
        if skills_path.exists():
            for skill in _parse_skills_from_md(skills_path):
                sl.create_skill(
                    name=skill["name"],
                    content=skill["content"],
                    domain=Domain("game/leduc", "specific"),
                    created_by="test_fixture",
                )
                l3_count += 1

    return {"l2_count": l2_count, "l3_count": l3_count}


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

    # ── Build knowledge stores from real classes + fixture files ──
    from core.flexible_knowledge import FlexibleKnowledge
    from core.skill_layer import SkillLayer
    from core.tools.registry import ToolRegistry

    fk = FlexibleKnowledge(
        PROJECT_ROOT / "data" / "layers" / "knowledge",
        PROJECT_ROOT / "data" / "layers" / "knowledge" / "l2_index.json",
    )
    sl = SkillLayer(
        PROJECT_ROOT / "data" / "layers" / "skills",
        ToolRegistry(),
    )

    fixtures_dir = PROJECT_ROOT / "tests" / "fixtures"
    loaded = _load_fixtures_into_knowledge(fk, sl, fixtures_dir)
    knowledge = {"l2": fk, "l3": sl}

    _write_log(env_log, "Knowledge state (pre-consolidation)",
               f"L2 cards: {len(fk.cards)} (limit=30)\n" +
               "\n".join(f"  [{c.id}] [{c.domain.path}] conf={c.confidence:.2f} {c.content[:100]}"
                         for c in fk.cards) +
               f"\n\nL3 skills: {len(sl.list_all())} (limit=20)\n" +
               "\n".join(f"  [{s.name}] [{s.domain.path}] {s.description[:100]}"
                         for s in sl.list_all()))

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
        l2_card_limit=15,      # 24 cards → trigger consolidation
        l3_skill_limit=5,       # 7 skills → trigger consolidation
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

    # ── System prompt (markup format — no json_mode needed) ──
    system_prompt = (
        "你是一个知识库维护 Agent。分析当前知识库状况并给出整理建议。\n\n"
        "规则：\n"
        "1. 识别可合并的相似条目（同一 domain 下内容高度重叠的卡片合并为一条）\n"
        "2. 标记低 confidence、内容冗余的条目为待删除\n"
        "3. 不同 domain 的条目不要跨域合并\n"
        "4. 使用 deprecate 而非 delete（保持可回滚）\n\n"
        "输出格式：每条修改一行，使用 @modify 标记。格式如下：\n\n"
        "  @modify layer=l2 type=deprecate target=card_id reason=\"merged into xxx\"\n"
        "  @modify layer=l2 type=create target=new_card_id content=\"merged strategy text\" reason=\"merge of a,b,c\"\n"
        "  @modify layer=l3 type=deprecate target=skill_name reason=\"duplicate of yyy\"\n\n"
        "注意：\n"
        "- layer 必须是 l1 / l2 / l3\n"
        "- type 必须是 create / update / deprecate\n"
        "- target 使用原始卡片/技能 ID\n"
        "- content 和 reason 用双引号包裹（如包含内部双引号用单引号替代）\n"
        "- 每条 @modify 独占一行\n"
        "- 不要输出 JSON，不要输出 markdown 代码块，直接输出 @modify 行"
    )

    # ── Log full prompt ──
    _write_log(prompt_log, "SYSTEM PROMPT", system_prompt)
    _write_log(prompt_log, "USER PROMPT (consolidation task meta)", task.meta)

    # ── Call LLM (NO json_mode — markup format output) ──
    _write_log(env_log, "Dispatching to LLM",
               f"system: {len(system_prompt)} chars\n"
               f"user meta: {len(task.meta)} chars\n"
               f"total: {len(system_prompt) + len(task.meta)} chars\n"
               f"format: @modify markup (json_mode=False)")

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": task.meta},
    ]
    resp = llm.chat(messages=messages)  # no json_mode!
    raw_text = resp.text if hasattr(resp, 'text') else str(resp)

    # ── Log response ──
    _write_log(response_log, "RAW LLM RESPONSE (@modify markup)", raw_text)

    # ── Parse @modify markup ──
    from core.env.learning_env import LearningEnv
    parsed = LearningEnv._parse_markup_modifications(raw_text)
    _write_log(response_log, "PARSED MODIFICATIONS",
               json.dumps(parsed, ensure_ascii=False, indent=2))

    # Per-layer summary
    summary_lines = []
    for mod_key in ("l1_modifications", "l2_modifications", "l3_modifications"):
        mods = parsed.get(mod_key, [])
        if not mods:
            summary_lines.append(f"{mod_key}: 0 modifications")
            continue
        types = {}
        for m in mods:
            t = m.get("type", "?")
            types[t] = types.get(t, 0) + 1
        summary_lines.append(f"{mod_key}: {len(mods)} modifications {types}")
    _write_log(env_log, "LLM response summary", "\n".join(summary_lines))

    _write_log(env_log, "Done", f"dry_run=True — no modifications applied")
    print(f"\nDone. Log: {log_dir}")


if __name__ == "__main__":
    main()
