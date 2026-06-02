"""
RLCard LLM Agent — Leduc Hold'em 演示脚本

用法:
  python scripts/run_llm_leduc.py
  python scripts/run_llm_leduc.py --episodes 10
  python scripts/run_llm_leduc.py --model deepseek-chat --temperature 0.1
"""
import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logger = logging.getLogger(__name__)

RULES_SYSTEM_PROMPT = """You are playing Leduc Hold'em. Your goal is to MAXIMIZE expected chips per hand (EV).

OBJECTIVE: Chips are unlimited — there is no bankroll constraint. Focus purely on expected value: every decision should maximize the average chips you win. Fold when negative EV, bet/raise when positive EV. The only metric that matters is long-run chip profit.

Cards: 6 cards total — K(ing), Q(ueen), J(ack) in spades(SP) and hearts(HR).
       Suit ranking: SP > HR.

Setup: 2 players, each gets 1 private card. Infinite chips, no betting limit.
       Player 0 posts 1 chip (small blind) and acts first. Player 1 posts 2 chips (big blind).

Pre-flop round:
  1. Player 0 acts first: call, raise, or fold.
  2. Player 1 acts.
  3. If anyone raises, the other gets a chance to call, re-raise, or fold.
  4. Max 2 raises per round (one raise + one re-raise), then only call or fold.
  5. Raise amount: 2 chips pre-flop.
  6. Once both players have matched bets, the round ends and the public card is revealed.

Post-flop round:
  1. Public card is dealt. It's shared by both players.
  2. Same action order:
     - If there is an active bet: call, raise, or fold.
     - If no active bet: check (pass), raise, or fold.
  3. Max 2 raises per round. Raise amount: 4 chips post-flop.
  4. Once both players have matched bets, showdown.

Showdown (winning):
  1. Pair (your card matches the public card) beats no pair.
  2. If both have a pair: higher card rank wins. Example: KK > QQ > JJ.
  3. If no pair: higher card rank wins. Example: K > Q > J.
  4. If same rank: suit decides. SP > HR.
  5. If completely tied: split pot.

Actions:
  call    — match the opponent's bet to stay in. Cost = opponent's bet - your bet.
  raise   — increase the bet. Forces opponent to match or fold.
  fold    — give up the hand. Cut losses when EV is negative.
  check   — pass without betting. Only available post-flop when no active bet.

Output ONLY one word: call, raise, fold, or check."""


def make_llm_client(model, temperature):
    import os
    import yaml
    from openai import OpenAI
    from core.llm_client import LLMClient

    env_path = Path(__file__).resolve().parent.parent / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key, val = key.strip(), val.strip()
            if key not in os.environ:
                os.environ[key] = val

    with open(Path(__file__).resolve().parent.parent / "config.yaml", encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    cfg = raw.get("main_llm", {})
    base_url = cfg.get("base_url", "https://api.deepseek.com")
    api_key = os.environ.get(cfg.get("api_key_env", "DEEPSEEK_API_KEY"), "")
    client = LLMClient(OpenAI(base_url=base_url, api_key=api_key), model or cfg.get("model", "deepseek-v4-flash"))
    client.temperature = temperature
    client.thinking_enabled = cfg.get("thinking", False)
    return client


def build_user_prompt(state):
    raw = state["raw_obs"]
    hand = raw["hand"]
    hand_str = {"SJ": "J SP", "SQ": "Q SP", "SK": "K SP",
                 "HJ": "J HR", "HQ": "Q HR", "HK": "K HR"}.get(hand, hand)
    public = raw["public_card"]
    public_str = "not yet dealt" if public is None else \
                 {"SJ": "J SP", "SQ": "Q SP", "SK": "K SP",
                  "HJ": "J HR", "HQ": "Q HR", "HK": "K HR"}.get(public, public)
    chips = raw["all_chips"]
    my_chips = raw["my_chips"]
    legal = raw["legal_actions"]
    round_name = "pre-flop" if "check" not in legal and raw["public_card"] is None else "post-flop"
    return f"""=== Round: {round_name} ===
Your position: Player 0
Your card: {hand_str}
Public card: {public_str}

Your total bet this round: {my_chips}
Opponent total bet this round: {chips[1]}
Total pot: {sum(chips)}

Legal actions: {', '.join(legal)}

Choose:"""


def parse_action(text, legal_actions):
    text = text.strip().lower()
    for act in legal_actions:
        if act.lower() in text:
            return act
    return legal_actions[0]


def play_episode(env, llm_client, log_file, ep_num):
    state, _ = env.reset()
    trajectory = []
    step = 0

    log_file.write(f"\n{'='*60}\n")
    log_file.write(f"Episode {ep_num}\n")
    log_file.write(f"{'='*60}\n")

    while not env.is_over():
        user_prompt = build_user_prompt(state)
        messages = [
            {"role": "system", "content": RULES_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]

        log_file.write(f"\n--- Step {step + 1} ---\n")
        log_file.write(f"[SYSTEM PROMPT]\n{RULES_SYSTEM_PROMPT}\n\n")
        log_file.write(f"[USER PROMPT]\n{user_prompt}\n\n")

        chat_kwargs = {}
        if getattr(llm_client, "thinking_enabled", False):
            chat_kwargs["extra_body"] = {"thinking": {"type": "enabled"}}
            chat_kwargs["reasoning_effort"] = "high"

        resp = llm_client.chat(messages=messages, **chat_kwargs)
        action_text = resp.text.strip()
        action_name = parse_action(action_text, state["raw_obs"]["legal_actions"])
        action_id = list(state["legal_actions"].keys())[
            state["raw_obs"]["legal_actions"].index(action_name)
        ]

        log_file.write(f"[LLM RESPONSE]\n{action_text}\n\n")
        log_file.write(f"[ACTION] {action_name} -> step done\n")

        trajectory.append((state, action_id))
        state, _ = env.step(action_id)
        step += 1

    payoffs = env.get_payoffs()
    log_file.write(f"[RESULT] reward={payoffs[0]:+.0f}\n")
    return payoffs[0], trajectory


def main():
    parser = argparse.ArgumentParser(description="LLM Agent plays Leduc Hold'em")
    parser.add_argument("--episodes", type=int, default=5, help="对局数 (default: 5)")
    parser.add_argument("--model", default=None, help="模型名称 (default: 从 config.yaml 读取)")
    parser.add_argument("--temperature", type=float, default=0.1, help="LLM temperature (default: 0.1)")
    parser.add_argument("--log-dir", default="logs/leduc", help="日志目录 (default: logs/leduc)")
    args = parser.parse_args()

    import rlcard
    from rlcard.models.registration import model_registry

    env = rlcard.make("leduc-holdem")
    cfr = model_registry.load("leduc-holdem-cfr").agent

    llm_client = make_llm_client(args.model, args.temperature)

    log_dir = Path(args.log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"llm_leduc_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

    total_reward = 0
    wins = 0

     with open(log_path, "w", encoding="utf-8") as f:
        f.write(f"LLM Leduc Hold'em — Score-Driven Log\n")
        f.write(f"Model: {args.model or llm_client.model}\n")
        f.write(f"Temperature: {args.temperature}\n")
        f.write(f"Episodes: {args.episodes}\n")
        f.write(f"Time: {datetime.now().isoformat()}\n")

        for ep in range(1, args.episodes + 1):
            env.set_agents([None, cfr])
            reward, _ = play_episode(env, llm_client, f, ep)
            total_reward += reward
            if reward > 0:
                wins += 1
            f.write(f"  Episode {ep:2d} | reward={reward:+.0f} chips | cumulative={total_reward:+d}\n")

        avg = total_reward / args.episodes
        win_rate = wins / args.episodes

        f.write(f"\n{'='*60}\n")
        f.write(f"SUMMARY (score-focused)\n")
        f.write(f"  Model:         {args.model or llm_client.model}\n")
        f.write(f"  Episodes:      {args.episodes}\n")
        f.write(f"  Total Score:   {total_reward:+d} chips\n")
        f.write(f"  Avg Score/Ep:  {avg:+.2f} chips\n")
        f.write(f"  Win Rate:      {win_rate*100:.1f}%\n")
        f.write(f"  Wins:          {wins}/{args.episodes}\n")

    print(f"Log saved to: {log_path}")
    print(f"  Episodes:      {args.episodes}")
    print(f"  Total Score:   {total_reward:+d} chips")
    print(f"  Avg Score/Ep:  {avg:+.2f}")
    print(f"  Win Rate:      {win_rate*100:.1f}%")
    print(f"  Wins:          {wins}/{args.episodes}")


if __name__ == "__main__":
    main()
