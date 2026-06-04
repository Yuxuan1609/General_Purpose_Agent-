# --- REFACTOR: LearningEnv ---
# This script tests the old reflection pipeline. Will be replaced by
# LearningEnv integration test: env.reset() → Executor.execute() → env.step() loop.
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

from core.layers.comm import ReflectPacket
from core.layers.base import _indent
from core.layers.l0_5_1.reflection_agent import L1ReflectProposer, L1ReflectVerifier
from core.layers.l2.reflection_agent import L2ReflectProposer, L2ReflectVerifier
from core.layers.l3.reflection_agent import L3ReflectProposer, L3ReflectVerifier


def _setup_logging():
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_dir = PROJECT_ROOT / "logs" / "leduc_cognitive_reflect" / stamp
    log_dir.mkdir(parents=True, exist_ok=True)

    fmt = logging.Formatter("%(message)s")

    for noisy in ("httpx", "httpcore", "openai", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(logging.Formatter("%(message)s"))
    root.addHandler(ch)

    # Reflection log files
    for logger_name in ("learning_refiner",
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
    phil = Philosophy(PROJECT_ROOT / "data" / "layers" / "l1_rules.json")
    fk = FlexibleKnowledge(PROJECT_ROOT / "data" / "layers" / "knowledge",
                           PROJECT_ROOT / "data" / "layers" / "knowledge" / "l2_index.json")
    sl = SkillLayer(PROJECT_ROOT / "data" / "layers" / "skills", ToolRegistry())
    return _build(meta, phil, fk, sl)


def main():
    log_dir = _setup_logging()
    logger = logging.getLogger("reflect_test")
    logger.info("[%s] Reflection flow test", datetime.now().strftime("%H:%M:%S"))
    logger.info("  log=%s", log_dir)

    pending_dir = PROJECT_ROOT / "data" / "learning" / "pending"
    records = list(pending_dir.rglob("*.json"))
    if not records:
        logger.warning("No pending records found")
        return

    logger.info("Pending records: %d (%s)", len(records),
                [r.name for r in records])

    # ── Load records ──
    loaded: list[dict] = []
    for f in records:
        content = json.loads(f.read_text(encoding="utf-8"))
        # Pending files are JSON arrays (accumulated steps)
        steps = content if isinstance(content, list) else [content]
        loaded.extend(steps)
        logger.info("  Loaded: %s → %d steps (domain=%s)",
                     f.name, len(steps), steps[0]["session"].get("domain") if steps else "?")

    if not loaded:
        logger.warning("No records in pending files")
        return

    # ── Decompose (once per unique session) ──
    from core.orchestrator.task_decomposer import TaskDecomposer
    dec = TaskDecomposer()
    units = []
    # Group records by session_id
    session_records: dict[str, list[dict]] = {}
    for rec in loaded:
        sid = rec["session"]["id"]
        session_records.setdefault(sid, []).append(rec)
    for sid, recs in session_records.items():
        session = recs[0]["session"]
        raw_log = pending_dir / f"{sid}.log"
        result = dec.decompose(session, raw_log)
        # Attach session records to each LearningUnit for downstream use
        for u in result:
            u._records = recs
        units.extend(result)
        logger.info("Decomposer: session=%s (%d records) → %d LearningUnit(s)",
                     sid, len(recs), len(result))

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
        unit_records = getattr(unit, '_records', [])
        meta = unit_records[0]["observation"]["meta"] if unit_records else ""

        coord_log = logging.getLogger("reflect_coordinator")
        lr_log = logging.getLogger("learning_refiner")
        l1r_log = logging.getLogger("l0_5_1_reflect")
        l2r_log = logging.getLogger("l2_reflect")
        l3r_log = logging.getLogger("l3_reflect")

        coord_log.debug("══════ LearningUnit: %s ══════", unit.description)
        coord_log.debug("  domain: %s | records: %d", unit.domain.path,
                        len(unit_records))

        # ── Learning Refiner ──
        lr_log.debug("═══ LearningRefiner ═══")
        lr_log.debug("  records: %d", len(unit_records))
        refine_result = refiner.refine(meta, unit_records)
        steps = refine_result.get("steps", [])
        lr_log.debug("  selected: %d steps", len(steps))
        for s in steps:
            lr_log.debug("    step %d: %s",
                        s.get("index", "?"),
                        str(s.get("reasoning", ""))[:120])
        lr_log.debug("")

        # ── Reflection chain for each worth_learning step ──
        if not steps:
            coord_log.debug("  No steps worth learning, skipping\n")
            continue

        for s in steps:
            idx = s.get("index", 0) if isinstance(s, dict) else s
            if idx >= len(unit_records):
                continue
            rec = unit_records[idx]
            record_id = rec["session"].get("id", "unknown")
            domain = unit.domain.path
            rec_notify = rec.get("notify_layers", {})
            refiner_reasoning = s.get("reasoning", "") if isinstance(s, dict) else ""

            coord_log.debug("  ═══ Record %d — %s ═══", idx, record_id)
            coord_log.debug("    step_index: %s | action: %s",
                           rec["session"].get("step_index"), rec.get("action"))

            for layer_key, agent, log in [
                ("l0_5_1", l1_reflect, l1r_log),
                ("l2", l2_reflect, l2r_log),
                ("l3", l3_reflect, l3r_log)]:
                layer_notify = rec_notify.get(layer_key, {})
                pkt = ReflectPacket(
                    record_id=record_id, domain=domain,
                    target_layer=layer_key,
                    refiner_reasoning=refiner_reasoning,
                    layer_notify=layer_notify,
                )
                _process_reflect_packet(pkt, agent, log, meta, llm, chain)

        coord_log.debug("  ═══ LearningUnit %s done ═══\n", unit.description)

    logger.info("=" * 50)
    logger.info("  Reflection Test Complete")
    logger.info("  Log: %s", log_dir)
    logger.info("  [%s]", datetime.now().strftime("%H:%M:%S"))
    logger.info("=" * 50)


def _process_reflect_packet(pkt: ReflectPacket, agent, log: logging.Logger,
                            meta: str, llm_client, chain):
    """Process ReflectPacket: Proposer → Verifier → Manager (Phase 2a LLM-based).

    Replaces older rule-based investigate/fix with config-driven LLM pipeline.
    """
    log.debug("═══ ReflectPacket → %s ═══", pkt.target_layer)
    log.debug("  record_id: %s | domain: %s", pkt.record_id, pkt.domain)
    log.debug("  refiner: %s", pkt.refiner_reasoning)
    log.debug("  layer_notify:\n%s",
              _indent(json.dumps(pkt.layer_notify, ensure_ascii=False, indent=2), 4))

    # ── Route to LLM-based Proposer/Verifier ──
    layer = pkt.target_layer
    if layer == "l0_5_1":
        _run_proposer_verifier(pkt, meta, log, layer_key="l1",
                               proposer_class=L1ReflectProposer,
                               verifier_class=L1ReflectVerifier,
                               existing_content_fn=lambda: _get_l1_existing(chain),
                               llm_client=llm_client, chain=chain)
    elif layer == "l2":
        _run_proposer_verifier(pkt, meta, log, layer_key="l2",
                               proposer_class=L2ReflectProposer,
                               verifier_class=L2ReflectVerifier,
                               existing_content_fn=lambda: _get_l2_existing(),
                               llm_client=llm_client, chain=chain)
    elif layer == "l3":
        _run_proposer_verifier(pkt, meta, log, layer_key="l3",
                               proposer_class=L3ReflectProposer,
                               verifier_class=L3ReflectVerifier,
                               existing_content_fn=lambda: _get_l3_existing(),
                               llm_client=llm_client, chain=chain)

    log.debug("")


def _run_proposer_verifier(pkt, meta, log, layer_key, proposer_class,
                           verifier_class, existing_content_fn, llm_client, chain):
    """Run Proposer → Verifier → Manager pipeline for one layer."""
    proposer = proposer_class(llm_client)
    verifier = verifier_class(llm_client)

    # Dispatch info (from upper layer or none)
    dispatch_info = getattr(pkt, 'dispatch_info', '无') or '无'

    # ── Proposer ──
    log.debug("  ═══ Proposer ═══")
    proposal = proposer.propose(
        layer_notify=pkt.layer_notify,
        refiner_reasoning=pkt.refiner_reasoning,
        meta=meta,
        dispatch_info=str(dispatch_info),
    )
    log.debug("  output: %s", json.dumps(proposal, ensure_ascii=False)[:500])

    fixes = proposal.get("self_fixes", [])
    dispatch_lower = proposal.get("dispatch_lower")

    if dispatch_lower and isinstance(dispatch_lower, dict) and dispatch_lower.get("layer"):
        log.debug("  → dispatch %s (reserved, not sent): %s",
                 dispatch_lower.get("layer"),
                 dispatch_lower.get("task", "")[:120])

    if fixes:
        # Verifier
        log.debug("  ═══ Verifier ═══")
        existing = existing_content_fn()
        verified = verifier.verify(fixes, existing)
        log.debug("  output: %s", json.dumps(verified, ensure_ascii=False)[:500])

        # Manager: route to correct layer
        log.debug("  ═══ Manager ═══")
        if layer_key == "l1":
            mgr = chain
        elif layer_key == "l2":
            mgr = chain._downstream
        elif layer_key == "l3":
            mgr = chain._downstream._downstream if chain._downstream else None
        else:
            mgr = chain
        if mgr is None:
            log.debug("  target manager not available, skipping")
            return

        for fix in verified.get("verified", []):
            action = fix.get("action", "")
            params: dict = {"content": fix.get("content", "")}
            if layer_key == "l1":
                params["rule_id"] = fix.get("rule_id", "")
            elif layer_key == "l2":
                params["card_id"] = fix.get("card_id", "")
                params["domain"] = fix.get("domain", "general")
                params["confidence"] = fix.get("confidence", 0.5)
            elif layer_key == "l3":
                params["name"] = fix.get("name", "")
                params["domain"] = fix.get("domain", "general")
            try:
                mgr.apply_update(action, params)
                log.debug("  Manager applied: %s", action)
            except Exception as e:
                log.debug("  Manager error: %s", e)
        log.debug("  ═══ end %s ═══\n", layer_key.upper())
    else:
        log.debug("  no self_fixes proposed")
        log.debug("  ═══ end %s ═══\n", layer_key.upper())


# ── Helper: extract existing content per layer ──


def _get_l1_existing(mgr):
    # Only L1 mutable rules — L0.5 constitution is immutable
    return [r.content for r in mgr._philosophy.l1_rules()]


def _get_l2_existing():
    return []


def _get_l3_existing():
    return []


def _detect_issues(layer_notify: dict) -> list[dict]:
    """Detect issues from a single layer's NOTIFY content."""
    if not layer_notify:
        return [{"type": "decision_error" if layer_notify is not None else "missing_notify"}]
    # L1 check
    if "result" in layer_notify and "reasoning" in layer_notify:
        if not layer_notify.get("result") or len(layer_notify.get("reasoning", "")) < 10:
            return [{"type": "decision_error"}]
    # L2 check
    if "cards" in layer_notify:
        cards = layer_notify.get("cards", [])
        if not cards:
            return [{"type": "card_missing"}]
    # L3 check
    if layer_notify.get("status") == "ok" and not layer_notify.get("issues"):
        return [{"type": "skill_underutilized", "skill_name": ""}]
    return []
