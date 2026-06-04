"""
Reflection flow test — runs full reflect pipeline on existing pending records.
Does NOT archive/move files (test mode).

用法: python scripts/test_reflection_flow.py
"""
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _setup_logging():
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_dir = PROJECT_ROOT / "logs" / "leduc_cognitive_reflect" / stamp
    log_dir.mkdir(parents=True, exist_ok=True)

    fmt = logging.Formatter("%(asctime)s | %(message)s")

    for noisy in ("httpx", "httpcore", "openai", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(logging.Formatter("%(asctime)s  %(message)s"))
    root.addHandler(ch)

    # Reflection log files
    for logger_name in ("reflect_coordinator", "learning_refiner",
                        "l0_5_1_reflect", "l2_reflect", "l3_reflect"):
        lg = logging.getLogger(logger_name)
        lg.setLevel(logging.DEBUG)
        lg.propagate = False
        fh = logging.FileHandler(str(log_dir / f"{logger_name}.log"), encoding="utf-8")
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(fmt)
        lg.addHandler(fh)

    # Console logger
    game_lg = logging.getLogger("reflect_test")
    game_lg.setLevel(logging.INFO)
    game_fh = logging.FileHandler(str(log_dir / "summary.log"), encoding="utf-8")
    game_fh.setLevel(logging.DEBUG)
    game_fh.setFormatter(fmt)
    game_lg.addHandler(game_fh)

    return log_dir


def _load_env():
    env_path = PROJECT_ROOT / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key, val = key.strip(), val.strip()
            if key not in __import__("os").environ:
                __import__("os").environ[key] = val


def build_llm_client():
    import yaml
    from openai import OpenAI
    from core.llm_client import LLMClient
    import os

    _load_env()
    with open(PROJECT_ROOT / "config.yaml", encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    cfg = raw.get("auxiliary_llm", raw.get("main_llm", {}))
    base_url = cfg.get("base_url", "https://api.deepseek.com")
    api_key = os.environ.get(cfg.get("api_key_env", "DEEPSEEK_API_KEY"), "")
    oai = OpenAI(base_url=base_url, api_key=api_key)
    llm = LLMClient(oai, cfg.get("model", "deepseek-chat"))
    llm.temperature = 0.1
    return llm


def build_chain():
    from core.meta_driver import MetaDriver, DEFAULT_TRIGGERS, DEFAULT_VALIDATORS
    from core.philosophy import Philosophy
    from core.flexible_knowledge import FlexibleKnowledge
    from core.skill_layer import SkillLayer
    from core.tools.registry import ToolRegistry
    from core.layers import build_chain as _build

    meta = MetaDriver(DEFAULT_TRIGGERS.copy(), DEFAULT_VALIDATORS.copy())
    phil = Philosophy(PROJECT_ROOT / "data" / "l1_rules.json")
    fk = FlexibleKnowledge(PROJECT_ROOT / "knowledge", PROJECT_ROOT / "knowledge" / "l2_index.json")
    sl = SkillLayer(PROJECT_ROOT / "skills", ToolRegistry())
    return _build(meta, phil, fk, sl)


def main():
    log_dir = _setup_logging()
    logger = logging.getLogger("reflect_test")
    logger.info("Reflection flow test — log=%s", log_dir)

    pending_dir = PROJECT_ROOT / "data" / "learning" / "pending"
    records = list(pending_dir.glob("*.json"))
    if not records:
        logger.warning("No pending records found")
        return

    logger.info("Pending records: %d (%s)", len(records),
                [r.name for r in records])

    # ── Load records ──
    loaded: list[dict] = []
    for f in records:
        rec = json.loads(f.read_text(encoding="utf-8"))
        loaded.append(rec)
        logger.info("  Loaded: %s (domain=%s, action=%s)",
                     f.name, rec["session"].get("domain"), rec.get("action"))

    # ── Decompose ──
    from core.orchestrator.task_decomposer import TaskDecomposer
    dec = TaskDecomposer()
    units = []
    for rec in loaded:
        session = rec["session"]
        raw_log = pending_dir / f"{session['id']}.log"
        result = dec.decompose(session, raw_log)
        units.extend(result)
        logger.info("Decomposer: session=%s → %d LearningUnit(s)",
                     session["id"], len(result))

    # ── Build chain for apply_update ──
    chain = build_chain()

    # ── Build reflection chain ──
    from core.layers.l3.reflection_agent import L3ReflectionAgent
    from core.layers.l2.reflection_agent import L2ReflectionAgent
    from core.layers.l0_5_1.reflection_agent import L0_5_1ReflectionAgent
    # Reuse existing chain's managers
    l3_reflect = L3ReflectionAgent("l3", chain._downstream._downstream)
    l2_reflect = L2ReflectionAgent("l2", chain._downstream, downstream=l3_reflect)
    l1_reflect = L0_5_1ReflectionAgent("l0_5_1", chain, downstream=l2_reflect)

    # ── LearningRefiner ──
    llm = build_llm_client()
    from core.orchestrator.learning_refiner import LearningRefiner
    lr_log = logging.getLogger("learning_refiner")
    refiner = LearningRefiner(llm, log=lr_log)

    # ── Process each LearningUnit ──
    for unit in units:
        unit_records = [r for r in loaded
                        if r["session"]["id"] == unit.description]
        meta = unit_records[0]["observation"]["meta"] if unit_records else ""

        coord_log = logging.getLogger("reflect_coordinator")
        lr_log = logging.getLogger("learning_refiner")
        l1r_log = logging.getLogger("l0_5_1_reflect")
        l2r_log = logging.getLogger("l2_reflect")
        l3r_log = logging.getLogger("l3_reflect")

        coord_log.debug("══════ LearningUnit: %s ══════", unit.description)
        coord_log.debug("  domain: %s | records: %d", unit.domain.path,
                        len(unit_records))
        coord_log.debug("  meta: %s", meta[:200])

        # ── Learning Refiner ──
        lr_log.debug("═══ LearningRefiner ═══")
        lr_log.debug("  records: %d", len(unit_records))
        refine_result = refiner.refine(meta, unit_records)
        lr_log.debug("  worth_learning: %s", refine_result.get("worth_learning"))
        lr_log.debug("  reasoning: %s",
                     str(refine_result.get("reasoning", ""))[:300])
        lr_log.debug("")

        # ── Reflection chain for each worth_learning record ──
        worth = refine_result.get("worth_learning", [])
        if not worth:
            coord_log.debug("  No records worth learning, skipping")
            continue

        for idx in worth:
            if idx >= len(unit_records):
                continue
            rec = unit_records[idx]
            coord_log.debug("  ═══ Record %d — Reflection ═══", idx)
            coord_log.debug("    action: %s", rec.get("action"))
            coord_log.debug("    L1 result: %s",
                           rec.get("notify_layers", {}).get("l0_5_1", {}).get("result", ""))

            # Heuristic issue generation (future: LLM-based)
            issues = _generate_issues(rec)
            coord_log.debug("    generated issues: L1=%d L2=%d L3=%d",
                           len(issues.get("l0_5_1", [])),
                           len(issues.get("l2", [])),
                           len(issues.get("l3", [])))

            # ── L1 Reflection ──
            l1_issues = issues.get("l0_5_1", [])
            if l1_issues:
                l1r_log.debug("═══ L1 ReflectionAgent ═══")
                l1r_log.debug("  issues: %s", json.dumps(l1_issues, ensure_ascii=False))
                result = l1_reflect.investigate(l1_issues,
                                                {"domain": unit.domain.path})
                l1r_log.debug("  investigate → my_issues=%d downstream=%d",
                             len(result.get("my_issues", [])),
                             len(result.get("downstream_issues", [])))

                # Fix L1's own issues
                my = result.get("my_issues", [])
                if my:
                    fix_result = l1_reflect.fix(my)
                    l1r_log.debug("  fix → %s",
                                 json.dumps(fix_result, ensure_ascii=False))

                # Cascade to L2
                ds = result.get("downstream_issues", [])
                if ds:
                    l1_reflect.query_downstream(ds,
                                                {"domain": unit.domain.path})

            # ── L2 Reflection ──
            l2_issues = issues.get("l2", [])
            if l2_issues:
                l2r_log.debug("═══ L2 ReflectionAgent ═══")
                l2r_log.debug("  issues: %s", json.dumps(l2_issues, ensure_ascii=False))
                result = l2_reflect.investigate(l2_issues,
                                                {"domain": unit.domain.path})
                l2r_log.debug("  investigate → my_issues=%d downstream=%d",
                             len(result.get("my_issues", [])),
                             len(result.get("downstream_issues", [])))
                my = result.get("my_issues", [])
                if my:
                    fix_result = l2_reflect.fix(my)
                    l2r_log.debug("  fix → %s",
                                 json.dumps(fix_result, ensure_ascii=False))
                ds = result.get("downstream_issues", [])
                if ds:
                    l2_reflect.query_downstream(ds,
                                                {"domain": unit.domain.path})

            # ── L3 Reflection ──
            l3_issues = issues.get("l3", [])
            if l3_issues:
                l3r_log.debug("═══ L3 ReflectionAgent ═══")
                l3r_log.debug("  issues: %s", json.dumps(l3_issues, ensure_ascii=False))
                result = l3_reflect.investigate(l3_issues,
                                                {"domain": unit.domain.path})
                l3r_log.debug("  investigate → my_issues=%d downstream=%d",
                             len(result.get("my_issues", [])),
                             len(result.get("downstream_issues", [])))
                my = result.get("my_issues", [])
                if my:
                    fix_result = l3_reflect.fix(my)
                    l3r_log.debug("  fix → %s",
                                 json.dumps(fix_result, ensure_ascii=False))

        coord_log.debug("  ═══ LearningUnit %s done ═══\n", unit.description)

    logger.info("")
    logger.info("=" * 50)
    logger.info("  Reflection Test Complete")
    logger.info("  Log: %s", log_dir)
    logger.info("=" * 50)


def _generate_issues(rec: dict) -> dict:
    """Heuristic issue generation from ExecutionRecord (future: LLM-based)."""
    issues: dict[str, list[dict]] = {"l0_5_1": [], "l2": [], "l3": []}
    notify = rec.get("notify_layers", {})

    # L1: check if reasoning looks weak or missing
    l1 = notify.get("l0_5_1", {})
    if not l1.get("result") or not l1.get("reasoning"):
        issues["l0_5_1"].append({
            "type": "decision_error",
            "message": "L1 result or reasoning missing",
        })

    # L2: check card confidence
    l2 = notify.get("l2", {})
    cards = l2.get("cards", []) if isinstance(l2, dict) else []
    for c in cards[:3]:
        # cards in NOTIFY are strings, not dicts with confidence.
        # Check obs.state for structured card data.
        pass

    obs_cards = rec.get("observation", {}).get("state", {}).get("l2_cards", [])
    for card in obs_cards:
        conf = card.get("confidence", 0.5)
        if conf < 0.5:
            issues["l2"].append({
                "type": "card_confidence_low",
                "card_id": card.get("content", "")[:40],
                "domain": card.get("domain", ""),
            })
        elif conf > 0.95:
            issues["l2"].append({
                "type": "card_confidence_high",
                "card_id": card.get("content", "")[:40],
            })

    # Always generate at least one test issue per layer to exercise full chain
    if not issues["l0_5_1"]:
        issues["l0_5_1"].append({
            "type": "decision_error",
            "message": "test: L1 decision verification",
        })
        # Trigger cascading: L1 sends card issue down to L2
        issues["l0_5_1"].append({
            "type": "card_missing",
            "domain": "game/leduc",
            "suggested_content": "test cascading card",
        })
    if not issues["l2"]:
        issues["l2"].append({
            "type": "card_outdated",
            "card_id": "test-card-outdated",
            "domain": rec["session"].get("domain", "general"),
        })
    if not issues["l3"]:
        issues["l3"].append({
            "type": "skill_underutilized",
            "message": "L3 returned status OK but no structured skill was used",
        })

    return issues
