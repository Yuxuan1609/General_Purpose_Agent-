import json
import sys

import textworld.gym


def main(game_path: str, max_steps: int = 100):
    env_id = textworld.gym.register_game(game_path, max_episode_steps=max_steps)
    env = textworld.gym.make(env_id)

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            cmd = json.loads(line)
        except json.JSONDecodeError:
            _write({"error": "invalid json"})
            continue

        cmd_type = cmd.get("type", "")

        if cmd_type == "reset":
            obs, infos = env.reset()
            _write({"observation": obs, "infos": _ser(infos)})

        elif cmd_type == "step":
            action = cmd.get("action", "")
            obs, reward, done, infos = env.step(action)
            _write({
                "observation": obs, "reward": reward,
                "done": done, "infos": _ser(infos),
            })

        elif cmd_type == "close":
            env.close()
            _write({"closed": True})
            break

        else:
            _write({"error": f"unknown command: {cmd_type}"})


def _write(data: dict):
    sys.stdout.write(json.dumps(data, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _ser(infos: dict) -> dict:
    return {k: str(v) if not isinstance(v, (str, int, float, bool, list, dict)) else v
            for k, v in infos.items()}


if __name__ == "__main__":
    game_path = sys.argv[1] if len(sys.argv) > 1 else None
    if not game_path:
        print("Usage: python tw_bridge.py <game.z8>", file=sys.stderr)
        sys.exit(1)
    main(game_path)
