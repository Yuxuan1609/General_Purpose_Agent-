#!/bin/bash
# Fork clean KB state for training experiments.
# Saves current data/ to a backup and creates clean state with only L0.5 seed content.
#
# Usage:
#   bash tb/setup_clean_kb.sh        # save current + create clean
#   bash tb/setup_clean_kb.sh restore  # restore from last backup

set -e
PROJECT="$(cd "$(dirname "$0")/.." && pwd)"
DATA="$PROJECT/data"
BACKUP_BASE="$PROJECT/data_backup"

if [ "$1" = "restore" ]; then
    LATEST=$(ls -dt "$BACKUP_BASE"/*/ 2>/dev/null | head -1)
    if [ -z "$LATEST" ]; then
        echo "No backup found under $BACKUP_BASE"
        exit 1
    fi
    echo "Restoring from $LATEST"
    rm -rf "$DATA"
    cp -r "$LATEST" "$DATA"
    echo "Restored."
    exit 0
fi

# === Backup current state ===
TS=$(date +%Y%m%d_%H%M%S)
BACKUP="${BACKUP_BASE}/backup_${TS}_main"
mkdir -p "$(dirname "$BACKUP")"
echo "Backing up $DATA → $BACKUP"
cp -r "$DATA" "$BACKUP"

# === Create clean KB state ===
echo "Creating clean KB state..."

# 1. Clear KB index
rm -rf "$DATA/knowledge"
mkdir -p "$DATA/knowledge"

# 2. Clear learning
rm -rf "$DATA/learning/pending"
mkdir -p "$DATA/learning/pending"
echo '{"version":1}' > "$DATA/learning/learning_stats.json"

# 3. Clear L2 knowledge cards
rm -rf "$DATA/layers/knowledge"
mkdir -p "$DATA/layers/knowledge"
echo '{"version":1,"cards":[],"version_history":[]}' > "$DATA/layers/knowledge/l2_index.json"

# 4. Clear L3 skills
rm -rf "$DATA/layers/skills"
mkdir -p "$DATA/layers/skills"

# 5. Reset domain registry with TB-relevant domains
python3 << 'PYEOF'
import json, os
PROJECT = os.environ.get("PROJECT", ".")
data_dir = os.path.join(PROJECT, "data")

from pathlib import Path
import sys
sys.path.insert(0, str(Path(data_dir).parent))
from core.domain_registry import DomainRegistry, DomainNode

reg = DomainRegistry()
nodes = [
    ("general", None, "通用领域，跨域知识的默认归属", {}),
    ("tb", "general", "Terminal-Bench 任务根域，涵盖所有 TB benchmark 任务", {"learning/reflect": 0.3}),
    ("tb/debugging", "tb", "调试类任务：修复代码错误、环境兼容性、编译问题", {}),
    ("tb/software-engineering", "tb", "软件工程类任务：git操作、构建系统、包管理", {}),
    ("tb/system-administration", "tb", "系统管理类任务：权限、网络、日志、服务配置", {}),
    ("tb/security", "tb", "安全类任务：加密、漏洞修复、安全配置", {}),
    ("learning/reflect", "general", "学习反思域，消费执行记录分析策略问题和改进机会", {}),
    ("learning/compile", "learning/reflect", "知识编译域，将高激活同域卡片编译为L3技能", {}),
    ("learning/consolidate", "learning/reflect", "知识整理域，管理知识库容量", {}),
]
for path, parent, desc, corr in nodes:
    reg.add_node(path, parent, desc, corr)

registry_path = os.path.join(data_dir, "layers", "domain_registry.json")
reg.save(Path(registry_path))
print(f"  domain_registry: {len(nodes)} domains seeded (tb + learning)")
PYEOF

# 6. Reset L1 rules to seed backup (L0.5 content only)
SEED="$DATA/layers/l1_rules_seed_backup.json"
TARGET="$DATA/layers/l1_rules.json"
if [ -f "$SEED" ]; then
    cp "$SEED" "$TARGET"
    echo "  l1_rules: reset from seed backup ($(python3 -c "import json; print(len(json.load(open('$SEED'))))" ) rules)"
else
    echo "  WARNING: seed backup not found at $SEED"
fi

echo ""
echo "Clean KB state ready at $DATA"
echo "Backup saved to $BACKUP"
echo ""
echo "To restore: bash tb/setup_clean_kb.sh restore"
