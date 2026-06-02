#!/usr/bin/env python3
"""TextWorld + LLM test — multi-turn conversation with logging."""
import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

PROJECT = Path("/mnt/c/Users/micha/PycharmProjects/cognitive-agent")
GAME = str(PROJECT / "tw_games" / "hard_game.z8")
BRIDGE = str(PROJECT / "scripts" / "tw_bridge.py")

GAME_CONFIG = {
    "world_size": 7,
    "nb_objects": 20,
    "quest_length": 10,
    "seed": 999,
    "max_steps": 30,
    "game_file": "hard_game.z8",
    "llm_model": "deepseek-chat",
    "llm_temperature": 0.3,
}

AVAILABLE_ACTIONS = [
    "go <direction>  — move (north/south/east/west/up/down)",
    "take <object>   — pick up an object",
    "drop <object>   — drop an object",
    "examine <obj>   — look at something closely",
    "open <object>   — open a container/door",
    "close <object>  — close a container/door",
    "inventory       — check what you are carrying",
    "look            — look around the room",
    "search <object> — search a container",
    "eat <object>    — eat something",
    "wait            — pass time",
]


def _start_bridge():
    proc = subprocess.Popen(
        ["python3", BRIDGE, GAME, str(GAME_CONFIG["max_steps"])],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        text=True, bufsize=1,
    )
    return proc


def _send(proc, data: dict) -> dict:
    proc.stdin.write(json.dumps(data) + "\n")
    proc.stdin.flush()
    raw = proc.stdout.readline().strip()
    return json.loads(raw)


def _extract_quest(obs: str) -> str:
    m = re.search(r"^(.*?)\n\n-=", obs, re.DOTALL)
    if not m:
        return ""
    lines = m.group(1).strip().split("\n")
    for i, line in enumerate(lines):
        if re.search(r"[a-zA-Z]{3,}", line):
            return "\n".join(lines[i:]).strip()
    return ""


def _extract_score(obs: str) -> str:
    m = re.search(r"(\d+)/(\d+)\s*$", obs.strip(), re.MULTILINE)
    return m.group(0) if m else ""


def _build_system_prompt(quest: str) -> str:
    lines = ["[QUEST]", quest, ""]
    lines.append("[AVAILABLE ACTIONS]")
    lines.extend(AVAILABLE_ACTIONS)
    lines.append("")
    lines.append(
        "Respond with ONE action only. "
        "Your message is sent directly to the game as a command."
    )
    return "\n".join(lines)


def _call_llm(messages: list, api_key: str, model="deepseek-chat") -> tuple[str, str]:
    from openai import OpenAI
    client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com")
    resp = client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=GAME_CONFIG["llm_temperature"],
        max_tokens=50,
    )
    full = resp.choices[0].message.content.strip()
    action = full.split("\n")[0].strip().strip('"').strip("'").strip(".").lower()
    return action, full


def _setup_log_dir() -> Path:
    ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    log_dir = PROJECT / "tw_logs" / ts
    log_dir.mkdir(parents=True, exist_ok=True)
    (log_dir / "config.json").write_text(
        json.dumps(GAME_CONFIG, indent=2, ensure_ascii=False),
    )
    return log_dir


def _dump_log(log_dir: Path, sys_prompt: str, conversation: list, steps_data: list):
    (log_dir / "system_prompt.json").write_text(
        json.dumps({"system_prompt": sys_prompt}, indent=2, ensure_ascii=False),
    )
    (log_dir / "conversation.json").write_text(
        json.dumps(conversation, indent=2, ensure_ascii=False),
    )
    (log_dir / "steps.json").write_text(
        json.dumps(steps_data, indent=2, ensure_ascii=False),
    )
    summary = {
        "total_steps": len(steps_data),
        "final_reward": steps_data[-1]["game_result"]["reward"] if steps_data else 0,
        "final_score": steps_data[-1]["game_result"]["score"] if steps_data else "",
        "completed": steps_data[-1]["game_result"]["done"] if steps_data else False,
        "actions": [s["action"] for s in steps_data],
    }
    (log_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False),
    )


def main():
    api_key = os.environ.get("DEEPSEEK_API_KEY", "")
    if not api_key:
        print("DEEPSEEK_API_KEY not set")
        sys.exit(1)

    log_dir = _setup_log_dir()
    print(f"log: {log_dir}")

    proc = _start_bridge()

    resp = _send(proc, {"type": "reset"})
    obs = resp.get("observation", "")

    quest = _extract_quest(obs)
    sys_prompt = _build_system_prompt(quest)

    messages = [{"role": "system", "content": sys_prompt}]
    steps_data = []
    conversation = []
    game_memory = obs

    for step in range(1, GAME_CONFIG["max_steps"] + 1):
        score = _extract_score(game_memory)
        user_msg = game_memory
        messages.append({"role": "user", "content": user_msg})

        try:
            action, raw_output = _call_llm(messages, api_key)
        except Exception as e:
            print(f"[{step}] LLM error: {e}")
            break

        messages.append({"role": "assistant", "content": raw_output})

        resp = _send(proc, {"type": "step", "action": action})
        new_obs = resp.get("observation", "")
        reward = resp.get("reward", 0.0)
        done = resp.get("done", False)
        new_score = _extract_score(new_obs)

        step_entry = {
            "step": step,
            "input_obs": user_msg,
            "action": action,
            "raw_llm": raw_output,
            "game_result": {
                "observation": new_obs,
                "reward": reward,
                "score": new_score,
                "done": done,
            },
        }
        steps_data.append(step_entry)
        conversation.append({"user": user_msg, "assistant": raw_output, "action": action})

        short = new_obs[:120].replace("\n", " | ")
        print(f"  {step:2d}. {action:20s}  r={reward}  {new_score:5s}  {short}")

        game_memory = new_obs

        if done:
            print(f"[DONE] step {step}, reward {reward}")
            break

    _send(proc, {"type": "close"})
    proc.wait()

    _dump_log(log_dir, sys_prompt, conversation, steps_data)
    print(f"\nsummary: {json.dumps({'steps': len(steps_data)}, indent=2)}")
    print(f"logs: {log_dir}")


if __name__ == "__main__":
    main()
