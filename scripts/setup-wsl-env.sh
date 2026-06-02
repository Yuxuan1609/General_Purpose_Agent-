#!/usr/bin/env bash
# ==============================================================================
# WSL Environment Setup Script — Cognitive Agent + TextWorld
# Usage: bash scripts/setup-wsl-env.sh
# ==============================================================================
set -euo pipefail

echo "===== Cognitive Agent — WSL Environment Setup ====="

# ── 1. System Dependencies ──────────────────────────────────────────────────
echo "[1/5] Installing system packages..."
sudo apt update -qq
sudo apt install -y -qq python3-pip python3-venv build-essential libffi-dev python3-dev curl git

# ── 2. Virtual Environment ──────────────────────────────────────────────────
TW_ENV="$HOME/tw-env"
echo "[2/5] Creating Python virtualenv at $TW_ENV..."
python3 -m venv "$TW_ENV"

# ── 3. Install TextWorld ────────────────────────────────────────────────────
echo "[3/5] Installing TextWorld..."
"$TW_ENV/bin/pip" install textworld

# ── 4. Install Project Dependencies ─────────────────────────────────────────
echo "[4/5] Installing project dependencies..."
cd "$(dirname "$0")/.."
"$TW_ENV/bin/pip" install openai pyyaml duckduckgo_search pytest

# ── 5. Passwordless sudo (recommended) ──────────────────────────────────────
echo "[5/5] Configuring passwordless sudo..."
SUDOERS_FILE="/etc/sudoers.d/tonyyang-nopasswd"
if [ ! -f "$SUDOERS_FILE" ]; then
    printf 'tonyyang ALL=(ALL) NOPASSWD:ALL\n' | sudo tee "$SUDOERS_FILE" > /dev/null
    sudo chmod 440 "$SUDOERS_FILE"
    echo "  Passwordless sudo configured for tonyyang"
else
    echo "  Passwordless sudo already configured"
fi

# ── Verify ───────────────────────────────────────────────────────────────────
echo ""
echo "===== Verification ====="
"$TW_ENV/bin/python" -c 'import textworld; print("TextWorld version:", textworld.__version__)'
"$TW_ENV/bin/python" -c 'import openai, yaml, duckduckgo_search, pytest; print("All deps OK")'
echo ""
echo "===== Setup Complete ====="
echo "Activate: source ~/tw-env/bin/activate"
echo "Run tests: pytest tests/ -v"
