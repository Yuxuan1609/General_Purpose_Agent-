"""Learning task restructured — separate E2E test.
  
Run: python scripts/test_learning_restructured.py

Design:
  1. LearningEnv scans DouZero pending records → learning_units
  2. LLM1 integrates records into per-layer enrichment (no judgment, only aggregation)
  3. Build TaskObservation with per-layer review + layer-specific tasks
  4. Execute through full Executor + L(0.5+1) ↔ L2 ↔ L3 chain
  5. Check per-layer modifications
"""
from __future__ import annotations
import json
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.types import TaskObservation


def _write_log(path: Path, title: str, content: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(f"\n{'=' * 60}\n  {title}\n{'=' * 60}\n\n{content}\n")


def main():
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_dir = PROJECT_ROOT / "logs" / "learning_restructured" / stamp
    log_dir.mkdir(parents=True, exist_ok=True)
    env_log = log_dir / "learning_env_io.log"

    print(f"Log dir: {log_dir}")

    # ═══════════════════════════════════════════════════════════════
    # 1. Load env + LLM
    # ═══════════════════════════════════════════════════════════════
    from core.env_loader import load_env
    from core.llm_factory import build_llm_client
    from core.philosophy import Philosophy
    from core.flexible_knowledge import FlexibleKnowledge
    from core.skill_layer import SkillLayer
    from core.seed_knowledge import seed_knowledge, init_registry
    from core.env.learning_env import LearningEnv

    load_env(PROJECT_ROOT)
    llm = build_llm_client(PROJECT_ROOT / "config.yaml", temperature=0.1)
    _write_log(env_log, "LLM Client", f"model: {llm.model}")

    # ═══════════════════════════════════════════════════════════════
    # 2. Load knowledge stores + domain registry
    # ═══════════════════════════════════════════════════════════════
    reg = init_registry(PROJECT_ROOT / "data" / "layers" / "domain_registry.json")
    phil = Philosophy(PROJECT_ROOT / "data" / "layers" / "l1_rules.json")
    fk = FlexibleKnowledge(
        PROJECT_ROOT / "data" / "layers" / "knowledge",
        PROJECT_ROOT / "data" / "layers" / "knowledge" / "l2_index.json",
        domain_registry=reg,
    )
    sl = SkillLayer(PROJECT_ROOT / "data" / "layers" / "skills",
                    domain_registry=reg)
    seed_knowledge(fk, phil, sl)

    _write_log(env_log, "Knowledge state",
               f"L1 rules: {len(phil.all_rules())}\n"
               f"L2 cards: {len(fk.cards)}\n"
               f"L3 skills: {len(sl.list_all())}")

    # ═══════════════════════════════════════════════════════════════
    # 3. Scan pending records → learning_units
    # ═══════════════════════════════════════════════════════════════
    pending_dir = PROJECT_ROOT / "data" / "learning" / "pending"
    knowledge = {"l1": phil, "l2": fk, "l3": sl}
    lenv = LearningEnv(pending_dir, knowledge, preprocessing_llm=llm, dry_run=True)

    state = lenv.reset("doudizhu")
    if not state.observation:
        print("No pending records found. Run DouZero script first.")
        return

    learning_units = lenv._enriched_units
    _write_log(env_log, "LearningEnv.reset()",
               f"Pending records: {len(lenv._pending_records)}\n"
               f"Enriched units: {len(learning_units)}\n"
               f"Domain: {lenv._base_domain}")

    # ═══════════════════════════════════════════════════════════════
    # 4. LLM integration — aggregate records into per-layer review
    #    (No judgment, only integration. Follows consolidation pattern.)
    # ═══════════════════════════════════════════════════════════════
    summaries = []
    for u in learning_units:
        summaries.append({
            "step": u.get("step", "?"),
            "action": str(u.get("action", "")),
            "result": str(u.get("result", "")),
            "l1_reasoning": str(u.get("l1_reasoning", "")),
            "l2_reasoning": str(u.get("l2_reasoning", "")),
            "l3_reasoning": str(u.get("l3_reasoning", "")),
        })

    integration_prompt = (
        "You are a learning integrator. You have analyzed execution records "
        "from a game (dou dizhu / DouZero). Each record shows what the agent did "
        "and which L1 rules / L2 cards / L3 skills were involved.\n\n"
        "Your job is to INTEGRATE the records into a per-layer summary. "
        "Do NOT judge what was right or wrong. Only aggregate what happened.\n\n"
        "Output a JSON object with these fields:\n"
        "  l1_summary: string — which L1 rules appeared across the records and "
        "    what patterns of rule application emerged. One paragraph.\n"
        "  l2_summary: string — which L2 knowledge cards were used and in "
        "    what game scenarios. One paragraph.\n"
        "  l3_summary: string — which L3 skills were triggered and what "
        "    tasks they performed. One paragraph.\n"
        "  overall_goal: string — one sentence describing what the agent was "
        "    trying to achieve in these games (e.g. 'win as landlord_up by "
        "    blocking landlord cards').\n\n"
        f"Records:\n{json.dumps(summaries, ensure_ascii=False, indent=2)}"
    )

    _write_log(env_log, "LLM Integration prompt",
               f"Records: {len(summaries)}, prompt chars: {len(integration_prompt)}")
    resp = llm.chat(messages=[{"role": "user", "content": integration_prompt}],
                    json_mode=True)
    integration_text = resp.text if hasattr(resp, 'text') else str(resp)
    try:
        integration = json.loads(integration_text)
    except json.JSONDecodeError:
        integration = {"l1_summary": "", "l2_summary": "", "l3_summary": "",
                       "overall_goal": "learn from doudizhu games"}

    _write_log(env_log, "LLM Integration result",
               json.dumps(integration, ensure_ascii=False, indent=2))

    # ═══════════════════════════════════════════════════════════════
    # 5. Build TaskObservation with per-layer structure
    #    (Same pattern as consolidation)
    # ═══════════════════════════════════════════════════════════════
    from core.env.learning_env import _L1_OUTPUT, _L2_OUTPUT, _L3_OUTPUT

    # ── meta (all layers see) ──
    # ── meta (all layers see) — honest status, like consolidation ──
    l1_has = bool(integration.get("l1_summary"))
    l2_has = bool(integration.get("l2_summary"))
    l3_has = bool(integration.get("l3_summary"))

    meta = (
        f"## Learning Task — game/doudizhu\n\n"
        f"**Goal**: {integration.get('overall_goal', 'learn from doudizhu games')}\n\n"
        f"- **L1 Rules**: {'review needed.' if l1_has else 'no review needed.'} "
        f"{'L1 rules applied across records.' if l1_has else ''}\n"
        f"- **L2 Cards**: {'review needed.' if l2_has else 'no review needed.'} "
        f"{'L2 cards used in multiple scenarios.' if l2_has else ''}\n"
        f"- **L3 Skills**: {'review needed.' if l3_has else 'no review needed.'} "
        f"{'L3 skills triggered during games.' if l3_has else ''}\n\n"
        f"Each layer has its own task with detailed criteria in state. "
        f"Layer agents should read above to decide whether to query downstream layers."
    )

    # ── l1_task (L1 only) ──
    l1_task = (
        f"## L1 Learning Task\n\n"
        f"### Context\n{integration.get('l1_summary', 'No L1-related findings.')}\n\n"
        f"### Judgment Criteria\n"
        f"- Review if behavior rules were applied correctly in the context above\n"
        f"- **modify**: refine a rule that was helpful but could be improved\n"
        f"- **deprecate**: remove a rule that was irrelevant or harmful\n"
        f"- **create**: add a new cross-domain methodology discovered in these games\n\n"
        f"### Execution Records\n"
        f"{len(learning_units)} records from doudizhu games. See learning_units in state for details.\n\n"
        f"Use tools: deprecate_l1_rule / create_l1_rule / modify_l1_rule"
    )

    # ── l2_task (L2 only) ──
    # ── l2_task (L2 only) — criteria only, no target_domains
    #     L2 receives cards based on L1's query + selected_nodes, not from env
    l2_task = json.dumps({
        "criteria": (
            f"### Context\n{integration.get('l2_summary', 'No L2-related findings.')}\n\n"
            f"### Judgment Criteria\n"
            f"- **create**: new strategic pattern discovered, create a knowledge card\n"
            f"- **modify**: existing card content needs update based on game results\n"
            f"- **deprecate**: card was used but proved ineffective\n\n"
            f"Use tools: deprecate_l2_card / create_l2_card / modify_l2_card"
        ),
    }, ensure_ascii=False)

    # ── l3_task (L3 only) — criteria only
    l3_task = json.dumps({
        "criteria": (
            f"### Context\n{integration.get('l3_summary', 'No L3-related findings.')}\n\n"
            f"### Judgment Criteria\n"
            f"- **create**: compile high-frequency patterns into a reusable skill\n"
            f"- **modify**: update existing skill based on execution experience\n"
            f"- **deprecate**: remove a skill that was misleading or unused\n\n"
            f"Use tools: deprecate_l3_skill / create_l3_skill / modify_l3_skill"
        ),
    }, ensure_ascii=False)

    task = TaskObservation(
        meta=meta,
        state={
            "current": meta,
            "history": "",
            "learning_units": learning_units,
            "l1_output_format": _L1_OUTPUT,
            "l2_output_format": _L2_OUTPUT,
            "l3_output_format": _L3_OUTPUT,
            "l1_task": l1_task,
            "l2_task": l2_task,
            "l3_task": l3_task,
        },
        session={
            "id": f"learning_restructured_{stamp}",
            "domain": "learning/reflect",
            "domains_hint": ["learning/reflect", "game/doudizhu"],
            "step_index": 0,
            "enable_learning": False,
        },
    )

    _write_log(env_log, "TaskObservation built",
               f"meta: {len(meta)} chars\n"
               f"session: {json.dumps(task.session, ensure_ascii=False)}\n\n"
               f"--- META ---\n{meta[:1000]}")

    # ═══════════════════════════════════════════════════════════════
    # 6. Execute through full layer chain
    # ═══════════════════════════════════════════════════════════════
    from core.layers import build_chain as _build_chain
    from core.layers.logging_setup import setup_layer_logging
    from core.executor import Executor

    setup_layer_logging(log_dir)
    chain = _build_chain(phil, fk, sl, auxiliary_llm=llm,
                         domain_registry=reg)
    executor = Executor(layer_root=chain, llm_client=llm,
                        learning_dir=PROJECT_ROOT / "data" / "learning")
    from core.tools.consolidation_tools import set_learning_context; set_learning_context(executor=executor)

    _write_log(env_log, "Dispatching to Agent (Executor + Layers)", "...")
    result = executor.execute(task)
    notify_layers = result.get("notify_layers", {})

    for layer_key, label in [("l0_5_1", "L1"), ("l2", "L2"), ("l3", "L3")]:
        _write_log(env_log, f"Agent NOTIFY: {label}",
                   json.dumps(notify_layers.get(layer_key, {}),
                              ensure_ascii=False, default=str, indent=2))

    # ═══════════════════════════════════════════════════════════════
    # 7. Summary
    # ═══════════════════════════════════════════════════════════════
    summary_lines = ["### Learning Task Modifications"]
    for mod_key, layer_label in [("l1_modifications", "L1"),
                                  ("l2_modifications", "L2"),
                                  ("l3_modifications", "L3")]:
        src_key = {"l1_modifications": "l0_5_1", "l2_modifications": "l2",
                   "l3_modifications": "l3"}[mod_key]
        mods = notify_layers.get(src_key, {}).get(mod_key, [])
        types = {}
        for m in mods:
            t = m.get("type", "?")
            types[t] = types.get(t, 0) + 1
        summary_lines.append(f"  {layer_label}: {len(mods)} modifications {types}")

    _write_log(env_log, "Summary", "\n".join(summary_lines))
    print("\n".join(summary_lines))
    print(f"\nDone. Log: {log_dir}")


if __name__ == "__main__":
    main()
