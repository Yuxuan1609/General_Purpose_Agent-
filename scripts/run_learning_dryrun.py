"""Phase 2.2 dry-run: read real pending records, LLM preprocess,
dispatch to Agent via Executor + Layers, apply modifications.
Separates LearningEnv I/O log from Agent internal communication logs.

Usage:
  python scripts/run_learning_dryrun.py           # uses mock LLM (fast)
  python scripts/run_learning_dryrun.py --real    # uses real DeepSeek API
  python scripts/run_learning_dryrun.py --mock    # explicit mock mode
"""
from __future__ import annotations
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def _load_env():
    env_path = PROJECT_ROOT / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key, val = key.strip(), val.strip()
            if key not in os.environ:
                os.environ[key] = val


def build_llm_client(mock: bool = True, model=None, temperature=0.1):
    """Build LLM client. mock=True uses MockLLMClient (fast canned responses),
    mock=False uses real DeepSeek API."""
    if mock:
        from scripts.mock_llm import MockLLMClient
        return MockLLMClient()
    import yaml
    from openai import OpenAI
    from core.llm_client import LLMClient
    _load_env()
    with open(PROJECT_ROOT / "config.yaml", encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    cfg = raw.get("main_llm", {})
    base_url = cfg.get("base_url", "https://api.deepseek.com")
    api_key = os.environ.get(cfg.get("api_key_env", "DEEPSEEK_API_KEY"), "")
    oai = OpenAI(base_url=base_url, api_key=api_key)
    llm = LLMClient(oai, model or cfg.get("model", "deepseek-v4-flash"))
    llm.temperature = temperature
    return llm


def _write_log(path: Path, title: str, content: str):
    with open(path, "a", encoding="utf-8") as f:
        f.write(f"\n{'=' * 60}\n")
        f.write(f"  {title}\n")
        f.write(f"{'=' * 60}\n\n")
        f.write(content)
        f.write("\n")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="LearningEnv dry-run")
    parser.add_argument("--real", action="store_true", help="Use real DeepSeek API")
    parser.add_argument("--mock", action="store_true", help="Use mock LLM (default)")
    args = parser.parse_args()
    use_mock = not args.real  # default to mock; --real overrides

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    mode = "mock" if use_mock else "real"
    log_dir = PROJECT_ROOT / "logs" / "learning_dryrun" / f"{stamp}_{mode}"
    log_dir.mkdir(parents=True, exist_ok=True)

    env_log = log_dir / "learning_env_io.log"
    agent_log = log_dir / "agent_prompts.log"

    print(f"Log dir: {log_dir}")
    print(f"  LearningEnv I/O:  {env_log.name}")
    print(f"  Agent prompts:    {agent_log.name}")

    # ── Layer agent logs to own directory ──────────────────────────
    fmt = logging.Formatter("%(message)s")
    for noisy in ("httpx", "httpcore", "openai", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    for lg_name, fn in [("l0_5_1", "l0_5_1"), ("l2", "l2"),
                         ("l3", "l3"), ("core.executor", "executor")]:
        lg = logging.getLogger(lg_name)
        lg.setLevel(logging.DEBUG)
        lg.propagate = False
        fh = logging.FileHandler(str(log_dir / f"{fn}.log"), encoding="utf-8")
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(fmt)
        lg.addHandler(fh)
    print(f"  Agent layers:     l0_5_1.log, l2.log, l3.log, executor.log")

    # ═══════════════════════════════════════════════════════════════
    # Load pending records
    # ═══════════════════════════════════════════════════════════════
    pending_dir = PROJECT_ROOT / "data" / "learning" / "pending"
    records = []
    record_files = sorted((pending_dir / "game_leduc").glob("*.json"))
    for f in record_files:
        data = json.loads(f.read_text(encoding="utf-8"))
        records.extend(data if isinstance(data, list) else [data])

    _write_log(env_log, "INPUT: Raw pending records",
               f"from: {[f.name for f in record_files]}\n"
               f"total records: {len(records)}\n\n"
               f"first record sample:\n"
               f"{json.dumps({k: str(v)[:200] for k, v in records[0].items()}, ensure_ascii=False, indent=2)}")

    # ═══════════════════════════════════════════════════════════════
    # Setup knowledge stores + chain
    # ═══════════════════════════════════════════════════════════════
    _load_env()
    from core.meta_driver import MetaDriver, DEFAULT_VALIDATORS
    from core.philosophy import Philosophy
    from core.flexible_knowledge import FlexibleKnowledge
    from core.skill_layer import SkillLayer
    from core.tools.registry import ToolRegistry
    from core.layers import build_chain as _build
    from scripts.run_leduc_cognitive import _seed_knowledge

    phil = Philosophy(PROJECT_ROOT / "data" / "layers" / "l1_rules.json")
    fk = FlexibleKnowledge(PROJECT_ROOT / "data" / "layers" / "knowledge",
                           PROJECT_ROOT / "data" / "layers" / "knowledge" / "l2_index.json")
    sl = SkillLayer(PROJECT_ROOT / "data" / "layers" / "skills", ToolRegistry())
    _seed_knowledge(fk, phil, sl)

    _write_log(env_log, "Knowledge state (pre-learn)",
               f"L1 rules: {len(phil.all_rules())}\n"
               + "\n".join(f"  [{r.id}] [{r.source}] {r.content[:100]}" for r in phil.all_rules())
               + f"\n\nL2 cards: {len(fk.cards)}\n"
               + "\n".join(f"  [{c.id}] [{c.domain.path}] conf={c.confidence} {c.content[:100]}" for c in fk.cards)
               + f"\n\nL3 skills: {len(sl.list_all())}\n"
               + "\n".join(f"  [{s.name}] [{s.domain.path}]" for s in sl.list_all()))

    # ═══════════════════════════════════════════════════════════════
    # LearningEnv: LLM1 preprocessing
    # ═══════════════════════════════════════════════════════════════
    from core.env.learning_env import LearningEnv
    knowledge = {"l1": phil, "l2": fk, "l3": sl}
    stats_file = PROJECT_ROOT / "data" / "learning" / "learning_stats.json"

    pre_llm = build_llm_client(mock=use_mock, temperature=0.1)
    print(f"  LLM mode:        {mode}")

    lenv = LearningEnv(
        PROJECT_ROOT / "data" / "learning" / "pending",
        knowledge,
        preprocessing_llm=pre_llm,
        stats_file=stats_file,
    )

    _write_log(env_log, "LLM1: Preprocessing (raw -> LearningUnits)",
               f"model: {pre_llm.model}\n"
               f"sending {min(len(records), 20)} records to LLM1...")

    units_llm = lenv._build_learning_units_llm(records)

    units_text = "\n".join(
        f"[{u['index']}] action={u['action']} result={u['result']}\n"
        f"  summary: {u.get('reasoning', '')[:150]}\n"
        f"  l1: {u.get('l1_reasoning', '')[:150]}\n"
        f"  l2: {u.get('l2_reasoning', '')[:150]}\n"
        f"  l3: {u.get('l3_reasoning', '')[:150]}\n"
        for u in units_llm
    )
    _write_log(env_log, f"LLM1 output: {len(units_llm)} enriched LearningUnits", units_text)

    obs_text = lenv._format_observation(units_llm, "game/leduc")
    _write_log(env_log, "Formatted observation (for Agent prompt)", obs_text)

    # ═══════════════════════════════════════════════════════════════
    # Build TaskObservation for Agent
    # ═══════════════════════════════════════════════════════════════
    # Use reset properly so domain is extracted
    state = lenv.reset("learn from recent leduc games")
    obs = lenv.build_task_observation()

    _write_log(env_log, "TaskObservation dispatched to Agent",
               f"META ({len(obs.meta)} chars):\n{obs.meta[:800]}...\n\n"
               f"STATE per-layer format keys: {[k for k in obs.state if 'output' in k]}\n"
               f"SESSION: {json.dumps(obs.session, ensure_ascii=False, indent=2)}")

    _write_log(agent_log, "Agent receives TaskObservation",
               f"Full META:\n{obs.meta}\n\n"
               f"L1 output format in state:\n{json.dumps(obs.state.get('l1_output_format'), ensure_ascii=False, indent=2)}\n\n"
               f"L2 output format in state:\n{json.dumps(obs.state.get('l2_output_format'), ensure_ascii=False, indent=2)}\n\n"
               f"L3 output format in state:\n{json.dumps(obs.state.get('l3_output_format'), ensure_ascii=False, indent=2)}")

    # ═══════════════════════════════════════════════════════════════
    # Agent: Executor + Layers (real LLM calls)
    # ═══════════════════════════════════════════════════════════════
    from core.layers import build_chain as _build_chain
    meta_driver = MetaDriver(DEFAULT_VALIDATORS.copy())
    chain = _build_chain(meta_driver, phil, fk, sl, auxiliary_llm=pre_llm)

    from core.executor import Executor
    executor = Executor(layer_root=chain, llm_client=pre_llm,
                        learning_dir=PROJECT_ROOT / "data" / "learning")

    _write_log(env_log, "Dispatching to Agent (Executor + Layers)", "...")
    result = executor.execute(obs)
    notify_layers = result.get("notify_layers", {})

    for layer_key, label in [("l0_5_1", "L1"), ("l2", "L2"), ("l3", "L3")]:
        _write_log(env_log, f"Agent NOTIFY: {label}",
                   json.dumps(notify_layers.get(layer_key, {}),
                              ensure_ascii=False, default=str, indent=2))

    # ═══════════════════════════════════════════════════════════════
    # LearningEnv: step() -> apply
    # ═══════════════════════════════════════════════════════════════
    action_json = json.dumps(notify_layers, ensure_ascii=False, default=str)
    step = lenv.step(action_json)

    _write_log(env_log, "LearningEnv.step() result",
               f"state: {step.state.observation}\n"
               f"reward: {step.reward}\n"
               f"done: {step.done}")

    # ═══════════════════════════════════════════════════════════════
    # Post-learning knowledge state
    # ═══════════════════════════════════════════════════════════════
    _write_log(env_log, "Knowledge state (post-learn)",
               f"L1 rules: {len(phil.all_rules())}\n"
               + "\n".join(f"  [{r.id}] [{r.source}] v{r.version} {r.content[:100]}" for r in phil.all_rules())
               + f"\n\nL2 cards: {len(fk.cards)}\n"
               + "\n".join(f"  [{c.id}] [{c.domain.path}] conf={c.confidence} {c.content[:100]}" for c in fk.cards))

    if stats_file.exists():
        try:
            stats = json.loads(stats_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            stats = {"error": "could not read stats file"}
        _write_log(env_log, "Usage stats", json.dumps(stats, ensure_ascii=False, indent=2))

    # ═══════════════════════════════════════════════════════════════
    # Copy layer agent prompts into agent_prompts.log
    # ═══════════════════════════════════════════════════════════════
    for fn in ["l0_5_1.log", "l2.log", "l3.log", "executor.log"]:
        fp = log_dir / fn
        if fp.exists():
            content = fp.read_text(encoding="utf-8")
            _write_log(agent_log, f"--- {fn} ---", content[:30000])

    print(f"\nDone. Logs: {log_dir}")


if __name__ == "__main__":
    main()
