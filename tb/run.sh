#!/bin/bash
# Terminal-Bench runner for cognitive-agent
#
# Usage:
#   bash tb/run.sh                            # run ALL 32 tasks
#   bash tb/run.sh <task-id>                  # run single task
#   bash tb/run.sh train                      # run all 20 train tasks
#   bash tb/run.sh test                       # run all 12 test tasks
#   bash tb/run.sh debugging                  # run Debugging category (8)
#   bash tb/run.sh software-engineering       # run Software Engineering (8)
#   bash tb/run.sh system-administration      # run System Administration (8)
#   bash tb/run.sh security                   # run Security category (8)
#
# Requires: terminal-bench installed (pip), Docker running, DEEPSEEK_API_KEY set

set -e

# Ensure tb CLI is on PATH
export PATH="$HOME/.local/bin:$PATH"

# Project root (parent of tb/)
PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export PYTHONPATH="$PROJECT_ROOT:$PYTHONPATH"

# Agent import path — tb.agent.cognitive_agent:CognitiveAgent
AGENT="tb.agent.cognitive_agent:CognitiveAgent"

# Dataset — local clone of terminal-bench repo
DATASET_PATH="${TB_DATASET_PATH:-${HOME}/tb-tasks/original-tasks}"

# Output directory
OUTPUT_DIR="${PROJECT_ROOT}/tb/runs"

# =============================================================================
# Task definitions — 32 tasks across 4 categories
# =============================================================================
DEBUGGING_TASKS=(
    fix-pandas-version
    conda-env-conflict-resolution
    incompatible-python-fasttext
    cpp-compatibility
    classifier-debug
    swe-bench-fsspec
    overfull-hbox
    swe-bench-astropy-1
)

SOFTWARE_ENGINEERING_TASKS=(
    fix-git
    modernize-fortran-build
    polyglot-c-py
    broken-python
    pypi-server
    write-compressor
    regex-chess
    circuit-fibsqrt
)

SYSTEM_ADMIN_TASKS=(
    fix-permissions
    processing-pipeline
    nginx-request-logging
    log-summary
    broken-networking
    configure-git-webserver
    home-server-https
    mailman
)

SECURITY_TASKS=(
    extract-safely
    git-workflow-hack
    openssl-selfsigned-cert
    sql-injection-attack
    vul-flask
    crack-7z-hash
    fix-code-vulnerability
    vul-flink
)

# Train = first 5 of each category (20 tasks)
TRAIN_TASKS=(
    "${DEBUGGING_TASKS[@]:0:5}"
    "${SOFTWARE_ENGINEERING_TASKS[@]:0:5}"
    "${SYSTEM_ADMIN_TASKS[@]:0:5}"
    "${SECURITY_TASKS[@]:0:5}"
)

# Test = last 3 of each category (12 tasks)
TEST_TASKS=(
    "${DEBUGGING_TASKS[@]:5:3}"
    "${SOFTWARE_ENGINEERING_TASKS[@]:5:3}"
    "${SYSTEM_ADMIN_TASKS[@]:5:3}"
    "${SECURITY_TASKS[@]:5:3}"
)

# Combined all 32
ALL_TASKS=(
    "${DEBUGGING_TASKS[@]}"
    "${SOFTWARE_ENGINEERING_TASKS[@]}"
    "${SYSTEM_ADMIN_TASKS[@]}"
    "${SECURITY_TASKS[@]}"
)

_run() {
    local task="$1"
    local phase="${2:-train}"
    echo "=== Running $task (phase=$phase) ==="
    TB_PHASE="$phase" python3.13 -m tb.runner run \
        --agent-import-path "$AGENT" \
        --dataset-path "$DATASET_PATH" \
        --task-id "$task" \
        --output-path "$OUTPUT_DIR" \
        --n-concurrent 1 \
        --no-rebuild \
        --no-cleanup
}

if [ -n "$1" ]; then
    case "$1" in
        train)
            echo "Running ALL train tasks (${#TRAIN_TASKS[@]} tasks)"
            for task in "${TRAIN_TASKS[@]}"; do _run "$task" "train"; done
            ;;
        test)
            echo "Running ALL test tasks (${#TEST_TASKS[@]} tasks)"
            for task in "${TEST_TASKS[@]}"; do _run "$task" "test"; done
            ;;
        debugging)
            echo "Running Debugging category (${#DEBUGGING_TASKS[@]} tasks)"
            for task in "${DEBUGGING_TASKS[@]}"; do _run "$task"; done
            ;;
        software-engineering)
            echo "Running Software Engineering category (${#SOFTWARE_ENGINEERING_TASKS[@]} tasks)"
            for task in "${SOFTWARE_ENGINEERING_TASKS[@]}"; do _run "$task"; done
            ;;
        system-administration)
            echo "Running System Administration category (${#SYSTEM_ADMIN_TASKS[@]} tasks)"
            for task in "${SYSTEM_ADMIN_TASKS[@]}"; do _run "$task"; done
            ;;
        security)
            echo "Running Security category (${#SECURITY_TASKS[@]} tasks)"
            for task in "${SECURITY_TASKS[@]}"; do _run "$task"; done
            ;;
        *)
            echo "Running single task: $1"
            _run "$1" "train"
            ;;
    esac
else
    echo "Running ALL 32 tasks (20 train + 12 test)"
    for task in "${TRAIN_TASKS[@]}"; do _run "$task" "train"; done
    for task in "${TEST_TASKS[@]}"; do _run "$task" "test"; done
fi
