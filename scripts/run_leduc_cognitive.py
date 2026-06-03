"""
Leduc Hold'em Cognitive Agent — 接入完整认知链

用法:
  python scripts/run_leduc_cognitive.py
  python scripts/run_leduc_cognitive.py --episodes 5
"""
import argparse
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

PROJECT_ROOT = Path(__file__).resolve().parent.parent

_ch = logging.StreamHandler(sys.stdout)
_ch.setLevel(logging.INFO)
_ch.setFormatter(logging.Formatter("%(asctime)s  %(message)s"))
logging.basicConfig(level=logging.INFO, handlers=[_ch])
logger = logging.getLogger("leduc_cognitive")


def _setup_logging():
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_dir = PROJECT_ROOT / "logs" / "leduc_cognitive" / stamp
    log_dir.mkdir(parents=True, exist_ok=True)

    fmt = logging.Formatter("%(asctime)s | %(message)s")

    # Suppress http noise
    for noisy in ("httpx", "httpcore", "openai", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    # Console: INFO only, no propagation from agent loggers
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(logging.Formatter("%(asctime)s  %(message)s"))
    root.addHandler(ch)

    # Per-agent file handlers
    for logger_name, file_name in [("l0_5_1", "l0_5_1"), ("l2", "l2"),
                                    ("l3", "l3"), ("core.executor", "executor")]:
        lg = logging.getLogger(logger_name)
        lg.setLevel(logging.DEBUG)
        lg.propagate = False
        fh = logging.FileHandler(str(log_dir / f"{file_name}.log"), encoding="utf-8")
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(fmt)
        lg.addHandler(fh)

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
            if key not in os.environ:
                os.environ[key] = val


def build_llm_client(model=None, temperature=0.1):
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


def build_chain():
    from core.meta_driver import MetaDriver, DEFAULT_TRIGGERS, DEFAULT_VALIDATORS
    from core.philosophy import Philosophy
    from core.flexible_knowledge import FlexibleKnowledge
    from core.skill_layer import SkillLayer
    from core.tools.registry import ToolRegistry
    from core.layers import build_chain

    meta = MetaDriver(DEFAULT_TRIGGERS.copy(), DEFAULT_VALIDATORS.copy())
    phil = Philosophy(PROJECT_ROOT / "data" / "l1_rules.json")
    fk = FlexibleKnowledge(PROJECT_ROOT / "knowledge", PROJECT_ROOT / "knowledge" / "l2_index.json")
    sl = SkillLayer(PROJECT_ROOT / "skills", ToolRegistry())

    _seed_knowledge(fk, phil, sl)
    return build_chain(meta, phil, fk, sl)


def _seed_knowledge(fk, phil, sl=None):
    """Seed game-specific L1 rules + L2 knowledge cards + L3 skills."""
    from core.task import Domain

    # L1 game-specific rule
    rule_text = ("棋牌游戏中，面对不完全信息时必须基于概率期望而非直觉决策。"
                 "手牌强度、对手行为模式、剩余筹码一并考虑，计算期望收益后行动。"
                 "避免因单局短期结果改变长期策略。")
    existing = [r.content for r in phil.all_rules()]
    if rule_text not in existing:
        phil.add_rule(rule_text, created_by="seed")

    # L2 knowledge cards — Leduc
    leduc_domain = Domain("game/leduc", "specific")
    leduc_cards = [
        ("持有K（最大牌）时翻牌前激进加注。对手Call说明对手有Q或J并赌公共牌。max 2 raises per round，"
         "尽量打满加注次数。" , 0.8),
        ("公共牌与手牌配对时全力加注。翻牌后加注额4筹码。对手未配对时大概率fold。"
         "如对手仍call，说明对手可能也有高牌或已成对。" , 0.85),
        ("翻牌后未成对且手牌为J时，若对手加注应考虑fold。公共牌即使是K，对手可能已配对或持有更高单张。"
         "fold损失已有投入但避免更大损失。" , 0.7),
    ]
    for content, conf in leduc_cards:
        fk.add_card(content=content, domain=leduc_domain, confidence=conf, source="seed")

    # L2 knowledge cards — Douzero
    dz_domain = Domain("game/doudizhu", "specific")
    dz_cards = [
        ("作为地主上家，核心职责是顶牌——用较大的单张或对子卡住地主的小牌，给下家创造跑牌机会。"
         "不要只顾自己出完。出单张时尽量出≥10的牌迫使地主消耗大牌。" , 0.8),
        ("炸弹(4张相同)可管任何牌型，火箭(XD)最大。农民保留炸弹到残局压制地主；"
         "地主尽早用炸弹确立牌权。追踪已出炸弹数判断剩余威胁。" , 0.85),
    ]
    for content, conf in dz_cards:
        fk.add_card(content=content, domain=dz_domain, confidence=conf, source="seed")

    # L3 skills — each maps to L2 Node via Relevance Domain field
    if sl:
        _seed_l3_skills(sl)

    logger.info("Seeded: L1 rules=%d L2 cards=%d L3 skills=%d",
                len(phil.all_rules()), len(fk.cards),
                len(sl.list_all()) if sl else 0)


def _seed_l3_skills(sl):
    """Create L3 skills with Relevance Domain mapping to L2 Node name."""
    from core.task import Domain

    leduc_domain = Domain("game/leduc", "specific")
    leduc_skills = [
        ("leduc-preflop-raise", "翻牌前加注策略",
         "---\nname: leduc-preflop-raise\ndescription: 翻牌前加注策略\ndomain: game/leduc\nrelevance_domain: game/leduc\n---\n"
         "# 翻牌前加注策略\n\n持有K时强制加注，持有Q时根据对手行为判断，持有J时倾向call观察。\n"
         "加注迫使弱牌fold或支付更高代价看公共牌。\n\n## 决策树\n"
         "- K → raise\n"
         "- Q → 对手raise则fold，对手call则call\n"
         "- J → call/fold，避免主动加注"),
        ("leduc-postflop-pair", "翻牌后成对加注",
         "---\nname: leduc-postflop-pair\ndescription: 翻牌后成对加注\ndomain: game/leduc\nrelevance_domain: game/leduc\n---\n"
         "# 翻牌后成对加注\n\n公共牌与手牌配对时，你有最高牌型。\n"
         "max 2 raises per round，尽量打满加注。每次加注4筹码。\n\n"
         "## 对手信号\n"
         "- 对手call → 对手可能也有较高单张\n"
         "- 对手fold → 收底池\n"
         "- 对手re-raise → 评估对手是否可能已成对"),
    ]
    for name, desc, content in leduc_skills:
        try:
            sl.create_skill(name=name, content=content, domain=leduc_domain)
        except Exception:
            pass  # skill already exists

    dz_domain = Domain("game/doudizhu", "specific")
    dz_skills = [
        ("doudizhu-top-card", "顶牌策略",
         "---\nname: doudizhu-top-card\ndescription: 顶牌策略\ndomain: game/doudizhu\nrelevance_domain: game/doudizhu\n---\n"
         "# 顶牌策略\n\n作为地主上家，核心任务是顶住地主的出牌。出单张时优先出≥10的牌。\n"
         "迫使地主消耗2或大小王等大牌资源。\n\n"
         "## 顶牌优先级\n"
         "- 出单张: 10 → J → Q → K → A → 2\n"
         "- 出对子: 优先出较大的对子\n"
         "- 不要出炸弹或火箭作为顶牌（留给残局）"),
    ]
    for name, desc, content in dz_skills:
        try:
            sl.create_skill(name=name, content=content, domain=dz_domain)
        except Exception:
            pass


def main():
    parser = argparse.ArgumentParser(description="Leduc Cognitive Agent")
    parser.add_argument("--episodes", type=int, default=3, help="对局数 (default: 3)")
    parser.add_argument("--temperature", type=float, default=0.1)
    parser.add_argument("--verbose", action="store_true", help="输出每步详情")
    args = parser.parse_args()

    log_dir = _setup_logging()
    logger.info("Config: episodes=%d temperature=%.1f log=%s",
                args.episodes, args.temperature, log_dir)

    _load_env()
    llm_client = build_llm_client(temperature=args.temperature)
    chain = build_chain()

    from core.executor import Executor
    executor = Executor(layer_root=chain, llm_client=llm_client,
                        learning_dir=PROJECT_ROOT / "data" / "learning")

    from scripts.leduc_cognitive_agent import LeducCognitiveAgent
    agent = LeducCognitiveAgent(executor, temperature=args.temperature)

    import rlcard
    from rlcard.models.registration import model_registry

    env = rlcard.make("leduc-holdem")
    cfr = model_registry.load("leduc-holdem-cfr").agent

    total_reward = 0
    wins = 0
    step_counts = []

    for ep in range(1, args.episodes + 1):
        env.set_agents([agent, cfr])
        state, player_id = env.reset()
        step = 0
        agent.reset_session(f"leduc_ep{ep}")

        logger.info("=== Episode %d ===", ep)
        while not env.is_over():
            if player_id == 0:
                action_id, _ = agent.eval_step(state)
            else:
                result = cfr.eval_step(state)
                action_id = result[0] if isinstance(result, tuple) else result

            if args.verbose:
                raw = state["raw_obs"]
                legal = raw["legal_actions"]
                action_idx = action_id if isinstance(action_id, int) else 0
                action_label = legal[action_idx] if action_idx < len(legal) else "?"
                logger.info("  Step %d | hand=%s public=%s legal=%s → %s",
                           step, raw.get("hand"), raw.get("public_card"),
                           legal, action_label)

            state, player_id = env.step(action_id)
            step += 1

        payoffs = env.get_payoffs()
        reward = payoffs[0]
        total_reward += reward
        step_counts.append(step)
        if reward > 0:
            wins += 1

        logger.info("  Result: reward=%+.1f chips | steps=%d", reward, step)

    avg_reward = total_reward / args.episodes
    win_rate = wins / args.episodes
    avg_steps = sum(step_counts) / len(step_counts)

    print()
    print("=" * 55)
    print("  Leduc Hold'em — Cognitive Agent Results")
    print("=" * 55)
    print(f"  Episodes:    {args.episodes}")
    print(f"  Total Score: {total_reward:+.1f} chips")
    print(f"  Avg/Ep:      {avg_reward:+.2f} chips")
    print(f"  Win Rate:    {win_rate*100:.0f}% ({wins}/{args.episodes})")
    print(f"  Avg Steps:   {avg_steps:.1f}")
    print(f"  Log:         {log_dir / 'game.log'}")
    print("=" * 55)


if __name__ == "__main__":
    main()
