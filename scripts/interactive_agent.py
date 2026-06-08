"""交互式认知 Agent — CLI 对话环境，支持调试和会话管理。

用法:
  python scripts/interactive_agent.py
  python scripts/interactive_agent.py --debug
  python scripts/interactive_agent.py --system-prompt "你是一个编程助手"
  python scripts/interactive_agent.py --no-record
"""
import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

PROJECT_ROOT = Path(__file__).resolve().parent.parent

DEFAULT_SYSTEM_PROMPT = "你是一个智能助手。请直接简洁地回复用户的问题。"


def _parse_args():
    parser = argparse.ArgumentParser(description="交互式认知 Agent")
    parser.add_argument("--debug", action="store_true", help="显示各层 NOTIFY 输出")
    parser.add_argument("--no-record", action="store_true", dest="no_record",
                        help="不将交互记录写入学习管道")
    parser.add_argument("--system-prompt", type=str, default=None,
                        help="自定义系统提示词")
    return parser.parse_args()


def _setup_executor():
    from core.env_loader import load_env
    load_env(PROJECT_ROOT)

    from core.chain_factory import build_default_chain
    chain = build_default_chain(PROJECT_ROOT, seed=False)

    from core.llm_factory import build_llm_client
    llm = build_llm_client(PROJECT_ROOT / "config.yaml")

    from core.executor import Executor
    executor = Executor(
        layer_root=chain,
        llm_client=llm,
        learning_dir=PROJECT_ROOT / "data" / "learning",
    )
    return executor


def _show_notifies(notify_layers: dict):
    import json
    for name in ("l0_5_1", "l2", "l3"):
        payload = notify_layers.get(name, {})
        if not payload:
            continue
        label = name.replace("l0_5_1", "L1").replace("l2", "L2").replace("l3", "L3")
        text = json.dumps(payload, ensure_ascii=False, indent=2, default=str)
        if len(text) > 2000:
            text = text[:2000] + "..."
        print(f"  [{label}]\n{text}")


def main():
    args = _parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(message)s",
        handlers=[logging.StreamHandler()],
    )

    try:
        executor = _setup_executor()
    except Exception as e:
        print(f"Failed to initialize: {e}")
        sys.exit(1)

    from core.env.interaction_env import InteractionEnv
    env = InteractionEnv(
        system_prompt=args.system_prompt or DEFAULT_SYSTEM_PROMPT,
        debug=args.debug,
        enable_learning=not args.no_record,
    )

    state = env.reset("interaction")
    print(state.observation)
    print("(Commands: /new=新会话, /info=会话信息, exit/quit=退出)\n")

    while True:
        try:
            user_input = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if user_input.lower() in ("exit", "quit"):
            break
        elif user_input == "/new":
            state = env.reset("interaction")
            print(state.observation)
            continue
        elif user_input == "/info":
            info = env.session_info()
            print(
                f"Session: {info['id'][:8]}... | turns: {info['turns']} "
                f"| started: {info['started_at'][:19]}"
            )
            continue
        elif not user_input:
            continue

        env.receive_input(user_input)
        task_obs = env.build_task_observation()
        if task_obs is None:
            continue

        try:
            result = executor.execute(task_obs)
            if not isinstance(result, dict):
                print(f"Error: unexpected response type: {type(result).__name__}")
                continue
        except Exception as e:
            print(f"Error: {e}")
            continue

        reply = result.get("action_text", "").strip()
        step = env.step(reply)

        if args.debug:
            _show_notifies(result.get("notify_layers", {}))

        print(f"Agent: {reply}")


if __name__ == "__main__":
    main()
