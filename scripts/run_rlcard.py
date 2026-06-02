"""
RLCard 启动脚本 — Cognitive Agent Phase 1a/1b

用法:
  python scripts/run_rlcard.py                          # 默认：Leduc + LLM Agent
  python scripts/run_rlcard.py --game doudizhu          # Phase 1b: 斗地主
  python scripts/run_rlcard.py --opponent random        # 对手改为 Random
  python scripts/run_rlcard.py --episodes 500           # 500 局
  python scripts/run_rlcard.py --agent llm              # LLM Agent（需配置 API）
  python scripts/run_rlcard.py --no-llm                 # Random Agent vs 预设（测试用）

环境变量:
  DEEPSEEK_API_KEY         # 使用 LLM Agent 时需要
"""
import argparse
import logging
import random
import sys

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s", stream=sys.stdout)
logger = logging.getLogger(__name__)


def make_env(game, seed=None):
    import rlcard
    config = {}
    if seed is not None:
        config["seed"] = seed
    env = rlcard.make(game, config=config)
    return env


def load_opponent(opponent_id, env):
    from rlcard.models.registration import model_registry

    if opponent_id == "random":
        from rlcard.agents import RandomAgent
        return RandomAgent(env.num_actions)

    model = model_registry.load(opponent_id)
    if hasattr(model, "agent"):
        return model.agent
    if hasattr(model, "eval_step"):
        return model
    if hasattr(model, "agents"):
        return model.agents
    from rlcard.agents import RandomAgent
    logger.warning("Opponent %s has no known interface, falling back to RandomAgent", opponent_id)
    return RandomAgent(env.num_actions)


def make_llm_agent(env):
    """Placeholder: 返回一个封装 LLM 调用的 Agent"""
    return LazyLlmAgent(env)


class LazyLlmAgent:
    """
    LLM Agent 桩 — 当前返回随机合法动作，后续接入 CognitiveAgent。
    """

    def __init__(self, env):
        self.env = env
        self.use_raw = False

    def eval_step(self, state):
        legal = list(state["legal_actions"].keys())
        action = random.choice(legal)
        return action, {}

    def step(self, state):
        return self.eval_step(state)


def evaluate(env, agent, opponent, episodes, verbose=True):
    total_reward = 0
    wins = 0
    for ep in range(episodes):
        trajectories, payoffs = env.run()
        agent_reward = payoffs[0]
        total_reward += agent_reward
        if agent_reward > 0:
            wins += 1
        if verbose and (ep + 1) % max(1, episodes // 10) == 0:
            logger.info("Episode %d/%d, reward=%+d", ep + 1, episodes, agent_reward)
    avg = total_reward / episodes
    win_rate = wins / episodes
    logger.info("Results over %d episodes: avg_reward=%.2f, win_rate=%.2f%%", episodes, avg, win_rate * 100)
    return {"avg_reward": avg, "win_rate": win_rate, "total_reward": total_reward, "wins": wins}


def main():
    parser = argparse.ArgumentParser(description="RLCard 启动脚本")
    parser.add_argument("--game", default="leduc-holdem", choices=["leduc-holdem", "doudizhu", "limit-holdem", "uno"],
                        help="卡牌游戏 (default: leduc-holdem)")
    parser.add_argument("--opponent", default="leduc-holdem-cfr",
                        help="对手模型 ID (default: leduc-holdem-cfr; 可选随机: random)")
    parser.add_argument("--episodes", type=int, default=100, help="对局数 (default: 100)")
    parser.add_argument("--agent", choices=["llm", "random"], default="random",
                        help="Agent 类型 (default: random, 用于测试)")
    parser.add_argument("--seed", type=int, default=42, help="随机种子 (default: 42)")
    parser.add_argument("--verbose", action="store_true", default=True, help="输出每局结果")
    args = parser.parse_args()

    logger.info("Game: %s | Opponent: %s | Episodes: %d | Agent: %s",
                args.game, args.opponent, args.episodes, args.agent)

    env = make_env(args.game, seed=args.seed)
    logger.info("Environment: %s (actions=%d, players=%d)", args.game, env.num_actions, env.num_players)

    opponent = load_opponent(args.opponent, env)
    logger.info("Opponent: %s", type(opponent).__name__)

    from rlcard.agents import RandomAgent
    if args.agent == "llm":
        agent = make_llm_agent(env)
        logger.info("Agent: LLM (桩, 当前使用随机动作)")
    else:
        from rlcard.agents import RandomAgent
        agent = RandomAgent(env.num_actions)
        logger.info("Agent: RandomAgent")

    if isinstance(opponent, list):
        agents = [agent] + opponent[1:]
        logger.info("Opponent is a multi-agent list (%d agents)", len(opponent))
    else:
        agents = [agent]
        for _ in range(env.num_players - 1):
            agents.append(opponent)
    env.set_agents(agents)

    results = evaluate(env, agent, opponent, args.episodes, verbose=args.verbose)

    print("\n===== Summary =====")
    print(f"  Game:       {args.game}")
    print(f"  Opponent:   {args.opponent} ({type(opponent).__name__})")
    print(f"  Episodes:   {args.episodes}")
    print(f"  Avg Reward: {results['avg_reward']:+.2f}")
    print(f"  Win Rate:   {results['win_rate']*100:.1f}%")
    print(f"  Total Wins: {results['wins']}/{args.episodes}")
    print("===================\n")


if __name__ == "__main__":
    main()
