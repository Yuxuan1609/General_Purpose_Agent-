#!/usr/bin/env bash
# ==============================================================================
# TextWorld Game Generator & Player — Cognitive Agent
# Usage:
#   bash scripts/run-textworld.sh          # 生成并游玩默认游戏
#   bash scripts/run-textworld.sh --gen    # 仅生成游戏
#   bash scripts/run-textworld.sh --play   # 仅游玩已有游戏
#   bash scripts/run-textworld.sh --gym    # 用 Python Gym API 运行测试
# ==============================================================================
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
GAMES_DIR="$PROJECT_DIR/tw_games"
ACTIVATE="source ~/tw-env/bin/activate"

mkdir -p "$GAMES_DIR"

gen_game() {
    local world_size="${1:-5}"
    local nb_objects="${2:-10}"
    local quest_length="${3:-5}"
    local seed="${4:-1234}"
    local output="$GAMES_DIR/game_s${seed}_w${world_size}_o${nb_objects}_q${quest_length}.z8"

    echo "=== Generating TextWorld game ==="
    echo "  World size:  $world_size"
    echo "  Objects:     $nb_objects"
    echo "  Quest length: $quest_length"
    echo "  Seed:        $seed"
    echo "  Output:      $output"
    echo ""

    bash -c "$ACTIVATE && tw-make custom --world-size $world_size --nb-objects $nb_objects --quest-length $quest_length --seed $seed --output \"$output\""

    echo "  Game generated: $output"
    echo "$output"
}

play_game() {
    local game_file="$1"
    if [ ! -f "$game_file" ]; then
        echo "ERROR: Game file not found: $game_file" >&2
        exit 1
    fi

    echo "=== Playing TextWorld game ==="
    echo "  Game: $game_file"
    echo "  (Type commands to play. Type 'quit' to exit.)"
    echo ""

    bash -c "$ACTIVATE && tw-play \"$game_file\""
}

gym_test() {
    local game_file="$1"
    if [ ! -f "$game_file" ]; then
        echo "ERROR: Game file not found: $game_file" >&2
        exit 1
    fi

    echo "=== Testing TextWorld via Gym API ==="
    bash -c "$ACTIVATE && python -c '
import textworld.gym

env_id = textworld.gym.register_game(\"$game_file\", max_episode_steps=10)
env = textworld.gym.make(env_id)

obs, infos = env.reset()
print(\"Initial observation:\", obs[:200])

score, moves, done = 0, 0, False
while not done and moves < 5:
    action = input(\"Enter command (or quit): \")
    if action.lower() == \"quit\":
        break
    obs, score, done, infos = env.step(action)
    print(\"Obs:\", obs[:200])
    print(\"Score:\", score, \"| Done:\", done)
    moves += 1

env.close()
print(\"Game finished. Moves:\", moves, \"| Score:\", score)
'"
}

# ── Main ─────────────────────────────────────────────────────────────────────

if [ ! -d "$HOME/tw-env" ]; then
    echo "ERROR: tw-env not found. Run scripts/setup-wsl-env.sh first." >&2
    exit 1
fi

case "${1:-}" in
    --gen)
        game_path=$(gen_game "${2:-5}" "${3:-10}" "${4:-5}" "${5:-1234}")
        echo "Game ready at: $game_path"
        ;;
    --play)
        shift
        game_file="${1:-$(ls -t "$GAMES_DIR"/*.z8 2>/dev/null | head -1)}"
        if [ -z "$game_file" ]; then
            echo "No game found. Generate one first: bash scripts/run-textworld.sh --gen" >&2
            exit 1
        fi
        play_game "$game_file"
        ;;
    --gym)
        shift
        game_file="${1:-$(ls -t "$GAMES_DIR"/*.z8 2>/dev/null | head -1)}"
        if [ -z "$game_file" ]; then
            echo "No game found. Generate one first: bash scripts/run-textworld.sh --gen" >&2
            exit 1
        fi
        gym_test "$game_file"
        ;;
    *)
        # 默认: 生成 + 游玩
        game_path=$(gen_game)
        echo ""
        play_game "$game_path"
        ;;
esac
