"""Consolidation test via Executor + LayerChain — real LLM calls.

Loads test fixture data into FlexibleKnowledge + SkillLayer, builds the
full Executor + L(0.5+1)↔L2↔L3 chain, dispatches a consolidation task
through the chain, and collects tool call modifications from layer NOTIFY.

LearningEnv runs dry_run=True — NO modifications applied.

Log structure:
  - consolidation_env_io.log   — Knowledge state, spec, analysis, dispatch, response
  - agent_prompts.log          — TaskObservation sent to Agent
  - l0_5_1.log / l2.log / l3.log / executor.log — Per-layer Agent communication

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
# Fixture loader (same as before)
# ═══════════════════════════════════════════════════════════════════════════

def _parse_cards_from_md(path: Path) -> list[dict]:
    cards = []
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
            cards.append({"id": card_id, "content": " ".join(content_lines),
                          "confidence": confidence})
    return cards


def _parse_skills_from_md(path: Path) -> list[dict]:
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
            skills.append({"name": skill_name, "content": " ".join(content_lines),
                           "confidence": confidence})
    return skills


def _load_fixtures(fk, phil, sl, fixtures_dir: Path) -> dict:
    from core.task import Domain
    l1_count = l2_count = l3_count = 0
    # L1 rules — clean old fixture rules first, then add fresh ones
    fp = fixtures_dir / "consolidation_test_l1.md"
    if fp.exists():
        for r in phil.all_rules():
            if r.created_by == "test_fixture":
                try:
                    phil.remove_rule(r.id)
                except Exception:
                    pass
        for line in fp.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("#") or not line or line.startswith("-"):
                continue
            try:
                phil.add_rule(line[:300], created_by="test_fixture", source="l1")
                l1_count += 1
            except Exception:
                pass
    # L2 cards
    for name, domain_path in [("consolidation_test_leduc", "game/leduc"),
                                ("consolidation_test_doudizhu", "game/doudizhu")]:
        fp = fixtures_dir / f"{name}.md"
        if fp.exists():
            for card in _parse_cards_from_md(fp):
                fk.add_card(content=card["content"],
                            domain=Domain(domain_path, "specific"), source="test_fixture")
                l2_count += 1
    if sl is not None:
        for fixture_name, domain_path in [("consolidation_test_skills", "game/leduc"),
                                           ("consolidation_test_skills_compile", "learning/compile")]:
            fp = fixtures_dir / f"{fixture_name}.md"
            if fp.exists():
                for skill in _parse_skills_from_md(fp):
                    content = (
                        f"---\n"
                        f"name: {skill['name']}\n"
                        f"description: {skill['content'][:80]}\n"
                        f"domain: {domain_path}\n"
                        f"---\n"
                        f"{skill['content']}"
                    )
                    sl.create_skill(name=skill["name"], content=content,
                                    domain=Domain(domain_path, "specific"),
                                    created_by="test_fixture")
                    l3_count += 1
    return {"l1_count": l1_count, "l2_count": l2_count, "l3_count": l3_count}


# ═══════════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════════

def main():
    import tempfile
    from core.env.learning_env import LearningEnv, load_consolidation_spec
    from core.llm_factory import build_llm_client
    from core.env_loader import load_env
    from core.layers.logging_setup import setup_layer_logging

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_dir = PROJECT_ROOT / "logs" / "consolidation_real" / stamp
    log_dir.mkdir(parents=True, exist_ok=True)

    env_log = log_dir / "consolidation_env_io.log"
    agent_log = log_dir / "agent_prompts.log"

    print(f"Log dir: {log_dir}")
    print(f"  Env I/O:     {env_log.name}")
    print(f"  Agent:       {agent_log.name}")

    # ── Per-layer agent logs ──
    setup_layer_logging(log_dir)
    print(f"  Layers:      l0_5_1.log, l2.log, l3.log, executor.log")

    # ── Load env + LLM ──
    load_env(PROJECT_ROOT)
    llm = build_llm_client(PROJECT_ROOT / "config.yaml", temperature=0.1)
    _write_log(env_log, "LLM Client", f"model: {llm.model}")

    # ── Domain registry ──
    reg_path = PROJECT_ROOT / "data" / "layers" / "domain_registry.json"
    reg = None
    try:
        from core.seed_knowledge import init_registry
        reg = init_registry(reg_path)
    except Exception:
        pass

    # ── Knowledge stores ──
    from core.meta_driver import MetaDriver, DEFAULT_VALIDATORS
    from core.philosophy import Philosophy
    from core.flexible_knowledge import FlexibleKnowledge
    from core.skill_layer import SkillLayer
    from core.tools.registry import ToolRegistry
    from core.seed_knowledge import seed_knowledge

    phil = Philosophy(PROJECT_ROOT / "data" / "layers" / "l1_rules.json")
    fk = FlexibleKnowledge(PROJECT_ROOT / "data" / "layers" / "knowledge",
                           PROJECT_ROOT / "data" / "layers" / "knowledge" / "l2_index.json",
                           domain_registry=reg)
    sl = SkillLayer(PROJECT_ROOT / "data" / "layers" / "skills", ToolRegistry(),
                    domain_registry=reg)
    seed_knowledge(fk, phil, sl)

    # Load consolidation test fixtures
    loaded = _load_fixtures(fk, phil, sl, PROJECT_ROOT / "tests" / "fixtures")
    _write_log(env_log, "Knowledge state (pre-consolidation)",
               f"L1 rules: {len(phil.all_rules())}\n"
               + "\n".join(f"  [{r.id}] [{r.source}] {r.content[:100]}" for r in phil.all_rules())
               + f"\n\nL2 cards: {len(fk.cards)} (fixtures +{loaded['l2_count']})\n"
               + "\n".join(f"  [{c.id}] [{c.domain.path}]  {c.content[:100]}" for c in fk.cards)
               + f"\n\nL3 skills: {len(sl.list_all())} (fixtures +{loaded['l3_count']})\n"
               + "\n".join(f"  [{s.name}] [{s.domain.path}] {s.description[:100]}" for s in sl.list_all()))

    # ── Build chain + Executor ──
    from core.layers import build_chain as _build_chain
    meta_driver = MetaDriver(DEFAULT_VALIDATORS.copy())
    chain = _build_chain(meta_driver, phil, fk, sl, auxiliary_llm=llm, domain_registry=reg)
    from core.executor import Executor
    executor = Executor(layer_root=chain, llm_client=llm,
                        learning_dir=PROJECT_ROOT / "data" / "learning")

    # ── LearningEnv with spec ──
    spec = load_consolidation_spec()
    knowledge = {"l1": phil, "l2": fk, "l3": sl}
    lenv = LearningEnv(
        Path(tempfile.mkdtemp()), knowledge,
        dry_run=True,
        l2_card_limit=25, l3_skill_limit=20,
        consolidation_spec=spec,
    )
    # Pre-set maintenance triggers for test domains
    lenv._stats["_consolidation"] = {
        "game/leduc": {"mod_count": 7, "last_consolidation": ""},
        "game/doudizhu": {"mod_count": 6, "last_consolidation": ""},
        "learning/compile": {"mod_count": 5, "last_consolidation": ""},
    }

    needs = lenv.needs_consolidation()
    level = lenv.get_consolidation_level()
    _write_log(env_log, "Consolidation analysis",
               f"needs_consolidation: {needs}\n"
               f"level: {level}\n"
               f"L2: {len(fk.cards)}/15, L3: {len(sl.list_all())}/5")

    assert needs

    # ── Build consolidation task ──
    task = lenv.build_consolidation_task()
    _write_log(env_log, "TaskObservation built",
               f"meta: {len(task.meta)} chars\n"
               f"session: {json.dumps(task.session, ensure_ascii=False)}\n\n"
               f"--- META (first 800 chars) ---\n{task.meta[:800]}\n...")

    _write_log(agent_log, "Agent receives TaskObservation",
               f"Full META:\n{task.meta}\n\n"
               f"SESSION: {json.dumps(task.session, ensure_ascii=False, indent=2)}")

    # ── Dispatch via Executor + LayerChain ──
    _write_log(env_log, "Dispatching to Agent (Executor + Layers)", "...")
    result = executor.execute(task)
    notify_layers = result.get("notify_layers", {})

    for layer_key, label in [("l0_5_1", "L1"), ("l2", "L2"), ("l3", "L3")]:
        _write_log(env_log, f"Agent NOTIFY: {label}",
                   json.dumps(notify_layers.get(layer_key, {}),
                              ensure_ascii=False, default=str, indent=2))

    # ── Collect tool call modifications from notify layers ──
    summary_lines = []
    for mod_key, layer_label in [("l1_modifications", "L1"), ("l2_modifications", "L2"), ("l3_modifications", "L3")]:
        mods = notify_layers.get({"l1_modifications": "l0_5_1", "l2_modifications": "l2", "l3_modifications": "l3"}[mod_key], {}).get(mod_key, [])
        if not mods:
            summary_lines.append(f"{mod_key}: 0 modifications")
            continue
        types = {}
        for m in mods:
            t = m.get("type", "?")
            types[t] = types.get(t, 0) + 1
        summary_lines.append(f"{mod_key}: {len(mods)} modifications {types}")
        types = {}
        for m in mods:
            t = m.get("type", "?")
            types[t] = types.get(t, 0) + 1
        summary_lines.append(f"{mod_key}: {len(mods)} modifications {types}")

    _write_log(env_log, "Tool call modifications summary", "\n".join(summary_lines))
    _write_log(env_log, "Full notify_layers",
               json.dumps(notify_layers, ensure_ascii=False, indent=2, default=str))

    # ── LearningEnv applies (dry_run — no actual changes) ──
    step = lenv.apply_modifications(notify_layers)
    _write_log(env_log, "LearningEnv.apply_modifications()",
               f"state: {step.state.observation}\nreward: {step.reward}\ndone: {step.done}")

    _write_log(env_log, "Done", "dry_run=True — no modifications applied. "
               f"Logs: l0_5_1.log, l2.log, l3.log, executor.log")
    print(f"\nDone. Log: {log_dir}")


if __name__ == "__main__":
    main()
