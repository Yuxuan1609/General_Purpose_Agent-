#!/bin/bash
# Baseline: Debugging(8) + Software_Engineering(8) = 16 tasks in test mode
set -e

cd /home/tonyyang
export PATH="$HOME/.local/bin:$PATH"
export PYTHONPATH="/mnt/c/Users/micha/PycharmProjects/cognitive-agent:$PYTHONPATH"
DATASET="/home/tonyyang/tb-tasks/original-tasks"
TS=$(date +%Y%m%d-%H%M%S)
OUTDIR="/home/tonyyang/tb-runs/test-baseline-$TS"
mkdir -p "$OUTDIR"

# Source .env for DEEPSEEK_API_KEY
set -a
source /mnt/c/Users/micha/PycharmProjects/cognitive-agent/.env 2>/dev/null || true
set +a

TASKS=(
    fix-pandas-version conda-env-conflict-resolution incompatible-python-fasttext
    cpp-compatibility classifier-debug swe-bench-fsspec overfull-hbox swe-bench-astropy-1
    fix-git modernize-fortran-build polyglot-c-py broken-python
    pypi-server write-compressor regex-chess circuit-fibsqrt
)

echo "=== Test Baseline: 16 tasks ==="  | tee "$OUTDIR/summary.txt"
echo "Start: $(date)"                   | tee -a "$OUTDIR/summary.txt"
echo "DEEPSEEK_API_KEY: ${DEEPSEEK_API_KEY:0:12}..." | tee -a "$OUTDIR/summary.txt"

PASS=0 FAIL=0 ERR=0

for task in "${TASKS[@]}"; do
    echo "" | tee -a "$OUTDIR/summary.txt"
    echo "--- $task ---" | tee -a "$OUTDIR/summary.txt"

    TB_PHASE=test python3.13 -m tb.runner run \
        --agent-import-path "tb.agent.cognitive_agent:CognitiveAgent" \
        --dataset-path "$DATASET" \
        --task-id "$task" \
        --output-path "$OUTDIR" \
        --n-concurrent 1 \
        --no-rebuild \
        --no-cleanup \
        2>&1 | tee "$OUTDIR/${task}.log"
    rc=${PIPESTATUS[0]}

    # Parse results.json for actual accuracy
    accuracy="N/A"
    is_resolved="N/A"
    result_json=$(find "$OUTDIR" -name results.json -newer "$OUTDIR" -maxdepth 5 2>/dev/null | tail -1)
    if [ -f "$result_json" ]; then
        accuracy=$(python3.13 -c "import json; d=json.load(open('$result_json')); print(d.get('accuracy','N/A'))" 2>/dev/null || echo "parse_error")
        is_resolved=$(python3.13 -c "import json; d=json.load(open('$result_json')); print('PASS' if d.get('n_resolved',0)>0 else 'FAIL')" 2>/dev/null || echo "parse_error")
    fi

    if [ "$is_resolved" = "PASS" ]; then
        PASS=$((PASS+1))
        echo "RESULT: PASS  accuracy=$accuracy" | tee -a "$OUTDIR/summary.txt"
    elif [ "$is_resolved" = "FAIL" ]; then
        FAIL=$((FAIL+1))
        echo "RESULT: FAIL  accuracy=$accuracy  exit=$rc" | tee -a "$OUTDIR/summary.txt"
    else
        ERR=$((ERR+1))
        echo "RESULT: ERROR  accuracy=$accuracy  exit=$rc  is_resolved=$is_resolved" | tee -a "$OUTDIR/summary.txt"
    fi
done

echo ""  | tee -a "$OUTDIR/summary.txt"
echo "=== Summary ===" | tee -a "$OUTDIR/summary.txt"
echo "PASS:  $PASS / ${#TASKS[@]}" | tee -a "$OUTDIR/summary.txt"
echo "FAIL:  $FAIL"               | tee -a "$OUTDIR/summary.txt"
echo "ERROR: $ERR"                | tee -a "$OUTDIR/summary.txt"
echo "End: $(date)"               | tee -a "$OUTDIR/summary.txt"
