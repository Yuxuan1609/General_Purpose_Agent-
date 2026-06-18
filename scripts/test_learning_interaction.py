"""Learning test — interaction domain."""
from __future__ import annotations
import json
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def _write_log(path: Path, title: str, content: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(f"\n{'=' * 60}\n  {title}\n{'=' * 60}\n\n{content}\n")


def main():
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_dir = PROJECT_ROOT / "logs" / "learning_interaction" / stamp
    log_dir.mkdir(parents=True, exist_ok=True)
    env_log = log_dir / "learning_env_io.log"

    print(f"Log dir: {log_dir}")

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

    # ── Ensure interaction domain exists ──
    if reg.get_node("interaction") is None:
        reg.add_node("interaction", "general",
                     "交互对话域：管理多轮对话技巧、用户意图理解、回复风格策略",
                     {}, "姊妹域: coding")
        reg.save(PROJECT_ROOT / "data" / "layers" / "domain_registry.json")
        _write_log(env_log, "Domain created + saved", "interaction under general")

    # ── Seed L2 cards for interaction domain ──
    existing = [c for c in fk.cards if c.domain.path == "interaction"]
    if not existing:
        from core.task import Domain
        fk.add_card(
            content="[问候] → [简洁友好回复] + [开放式提问以了解用户需求]",
            domain=Domain("interaction", "specific"),
            source="seed",
        )
        fk.add_card(
            content="[文件操作请求] → [调用 terminal/read_file 获取信息] + [格式化后回复]",
            domain=Domain("interaction", "specific"),
            source="seed",
        )
        fk.add_card(
            content="[评估/分析请求] → [先读取相关文件] → [结构化输出评估报告]",
            domain=Domain("interaction", "specific"),
            source="seed",
        )
        _write_log(env_log, "L2 Cards seeded",
                   f"3 cards in interaction domain (total: {len(fk.cards)})")
    else:
        _write_log(env_log, "L2 Cards exist",
                   f"{len(existing)} cards in interaction domain (total: {len(fk.cards)})")

    _write_log(env_log, "Knowledge state",
               f"L1 rules: {len(phil.all_rules())}\n"
               f"L2 cards: {len(fk.cards)}\n"
               f"L3 skills: {len(sl.list_all())}\n"
               f"Domains: {[n.path for n in reg.list_all()]}")

    # ── Scan pending interaction records ──
    pending_dir = PROJECT_ROOT / "data" / "learning" / "pending"
    knowledge = {"l1": phil, "l2": fk, "l3": sl}
    lenv = LearningEnv(pending_dir, knowledge, preprocessing_llm=llm, dry_run=True)

    state = lenv.reset("interaction")
    if not state.observation:
        print("No pending records found.")
        return

    learning_units = lenv._enriched_units
    _write_log(env_log, "LearningEnv.reset()",
               f"Pending records: {len(lenv._pending_records)}\n"
               f"Enriched units: {len(learning_units)}\n"
               f"Domain: {lenv._base_domain}")
    for u in learning_units:
        _write_log(env_log, f"Unit [{u.get('index', '?')}]",
                   f"action: {str(u.get('action', ''))[:200]}\n"
                   f"l1_reasoning: {str(u.get('l1_reasoning', ''))[:200]}\n"
                   f"l2_reasoning: {str(u.get('l2_reasoning', ''))[:200]}\n"
                   f"l3_reasoning: {str(u.get('l3_reasoning', ''))[:200]}")

    # ── Build TaskObservation via LLM integration ──
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
        "You are a learning integrator. Integrate conversation records into per-layer summary.\n"
        "Do NOT judge right/wrong. Only aggregate what happened.\n\n"
        "Output JSON:\n"
        "  l1_summary: which L1 behavior rules appeared and what patterns emerged\n"
        "  l2_summary: which L2 knowledge cards were used and in what scenarios\n"
        "  l3_summary: which L3 skills were triggered\n"
        "  overall_goal: one sentence\n\n"
        f"Records:\n{json.dumps(summaries, ensure_ascii=False, indent=2)}"
    )
    resp = llm.chat(messages=[{"role": "user", "content": integration_prompt}],
                    json_mode=True)
    integration_text = resp.text if hasattr(resp, 'text') else str(resp)
    try:
        integration = json.loads(integration_text)
    except json.JSONDecodeError:
        integration = {"l1_summary": "", "l2_summary": "", "l3_summary": "",
                       "overall_goal": "learn from interaction records"}

    _write_log(env_log, "LLM Integration",
               json.dumps(integration, ensure_ascii=False, indent=2))

    # ── Build TaskObservation ──
    from core.env.learning_env import _L1_OUTPUT, _L2_OUTPUT, _L3_OUTPUT
    from core.types import TaskObservation

    meta = (
        f"## Learning Task — interaction\n\n"
        f"**Goal**: {integration.get('overall_goal', 'learn from interaction records')}\n\n"
        f"- **L1 Rules**: {'review needed.' if integration.get('l1_summary') else 'no review needed.'}\n"
        f"- **L2 Cards**: {'review needed.' if integration.get('l2_summary') else 'no review needed.'}\n"
        f"- **L3 Skills**: {'review needed.' if integration.get('l3_summary') else 'no review needed.'}\n\n"
        f"Layer agents should read above to decide whether to query downstream layers."
    )

    l1_task = (
        f"## L1 Learning Task\n\n"
        f"### Context\n{integration.get('l1_summary', 'No L1-related findings.')}\n\n"
        f"### Judgment Criteria\n"
        f"- Review if behavior rules were applied correctly\n"
        f"- **modify**: refine a rule that was helpful but could be improved\n"
        f"- **deprecate**: remove a rule that was irrelevant or harmful\n"
        f"- **create**: add a new cross-domain methodology discovered\n\n"
        f"Use tools: create_domain / deprecate_l1_rule / create_l1_rule / modify_l1_rule"
    )

    l2_task = json.dumps({
        "criteria": (
            f"### Context\n{integration.get('l2_summary', 'No L2-related findings.')}\n\n"
            f"### Judgment Criteria\n"
            f"- **create**: new strategic pattern discovered, create a knowledge card\n"
            f"- **modify**: existing card content needs update based on results\n"
            f"- **deprecate**: card was used but proved ineffective\n\n"
            f"Use tools: deprecate_l2_card / create_l2_card / modify_l2_card"
        ),
    }, ensure_ascii=False)

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
            "id": f"learning_interaction_{stamp}",
            "domain": "learning/reflect",
            "domains_hint": ["learning/reflect", "interaction"],
            "step_index": 0,
            "enable_learning": False,
        },
    )

    _write_log(env_log, "TaskObservation built",
               f"meta: {len(meta)} chars\n"
               f"session: {json.dumps(task.session, ensure_ascii=False)}")

    # ── Execute through layer chain ──
    from core.layers import build_chain as _build_chain
    from core.layers.logging_setup import setup_layer_logging
    from core.executor import Executor

    setup_layer_logging(log_dir)
    chain = _build_chain(phil, fk, sl, auxiliary_llm=llm,
                         domain_registry=reg)
    executor = Executor(layer_root=chain, llm_client=llm,
                        learning_dir=PROJECT_ROOT / "data" / "learning")
    chain._consol_ctx.executor = executor

    _write_log(env_log, "Dispatching to Agent (Executor + Layers)", "...")
    result = executor.execute(task)
    notify_layers = result.get("notify_layers", {})

    for layer_key, label in [("l0_5_1", "L1"), ("l2", "L2"), ("l3", "L3")]:
        _write_log(env_log, f"Agent NOTIFY: {label}",
                   json.dumps(notify_layers.get(layer_key, {}),
                              ensure_ascii=False, default=str, indent=2))

    # ── Summary ──
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
        for m in mods:
            summary_lines.append(f"    [{m.get('type', '?')}] {m.get('target', '?')}: "
                               f"{str(m.get('reason', ''))[:120]}")

    _write_log(env_log, "Summary", "\n".join(summary_lines))
    print("\n".join(summary_lines))
    print(f"\nDone. Log: {log_dir}")


if __name__ == "__main__":
    main()
