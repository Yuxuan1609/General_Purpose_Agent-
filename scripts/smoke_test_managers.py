"""Smoke test: simulate verifier output → call Manager.apply_update → check data files.

Usage: python scripts/smoke_test_managers.py
Each layer's every action is tested by directly inspecting persisted data.
"""
import json
import shutil
import sys
from pathlib import Path
from unittest.mock import Mock

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

DATA_DIR = PROJECT_ROOT / "data" / "smoke_test"
LAYERS_DATA = DATA_DIR / "layers"
LAYERS_DATA.mkdir(parents=True, exist_ok=True)

# Clean slate
shutil.rmtree(DATA_DIR, ignore_errors=True)
LAYERS_DATA.mkdir(parents=True, exist_ok=True)
(LAYERS_DATA / "skills").mkdir(exist_ok=True)
(LAYERS_DATA / "knowledge").mkdir(exist_ok=True)

# ── L1 rules path ──
RULES_PATH = LAYERS_DATA / "l1_rules.json"
RULES_PATH.write_text(json.dumps({
    "version": 1,
    "rules": [
        {"id": "constitution_1", "content": "安全第一", "created_by": "seed", "source": "l0_5",
         "added_at": "", "version": 1, "last_modified": ""},
        {"id": "l1_existing", "content": "existing rule", "created_by": "seed", "source": "l1",
         "added_at": "", "version": 1, "last_modified": ""},
    ]
}, ensure_ascii=False, indent=2), encoding="utf-8")

# ── L2 index ──
L2_INDEX = LAYERS_DATA / "knowledge" / "l2_index.json"
L2_INDEX.parent.mkdir(exist_ok=True)
L2_INDEX.write_text(json.dumps({"version": 1, "chapters": [], "relations": []}))

# ── Build chain ──
from core.meta_driver import MetaDriver, DEFAULT_TRIGGERS, DEFAULT_VALIDATORS
from core.philosophy import Philosophy
from core.flexible_knowledge import FlexibleKnowledge
from core.skill_layer import SkillLayer
from core.tools.registry import ToolRegistry
from core.layers import build_chain
from core.layers.l2.manager import L2_DOMAIN_NODES

meta = MetaDriver(DEFAULT_TRIGGERS.copy(), DEFAULT_VALIDATORS.copy())
phil = Philosophy(RULES_PATH)
fk = FlexibleKnowledge(LAYERS_DATA / "knowledge", L2_INDEX)
sl = SkillLayer(LAYERS_DATA / "skills", ToolRegistry())

# Seed L2 cards for modify/remove tests
from core.task import Domain
leduc = Domain("game/leduc", "specific")
card1 = fk.add_card(content="card one: hold K raise preflop", domain=leduc, confidence=0.8, source="seed")
card2 = fk.add_card(content="card two: fold weak hands", domain=leduc, confidence=0.6, source="seed")

# Seed L3 skills for update/remove tests
sl.create_skill(name="test-skill-a", content="---\nname: test-skill-a\ndescription: A\n---\n# A", domain=leduc)
sl.create_skill(name="test-skill-b", content="---\nname: test-skill-b\ndescription: B\n---\n# B", domain=leduc)

chain = build_chain(meta, phil, fk, sl, auxiliary_llm=None)
l1_mgr = chain
l2_mgr = chain._downstream
l3_mgr = l2_mgr._downstream if l2_mgr else None

errors = []

def check(condition, msg):
    if not condition:
        errors.append(msg)
        print(f"  FAIL: {msg}")
    else:
        print(f"  OK:   {msg}")

def reload_rules():
    return json.loads(RULES_PATH.read_text(encoding="utf-8"))["rules"]

# ══════════════════════════════════════════════
print("\n=== L1 Manager Smoke Test ===")

# L1: add_rule
print("\n  [add_rule]")
l1_mgr.apply_update("add_rule", {"content": "smoke test: new rule"})
rules = reload_rules()
check(any(r["content"] == "smoke test: new rule" for r in rules),
      "new rule persisted to JSON")

# L1: modify_rule
print("\n  [modify_rule]")
l1_mgr.apply_update("modify_rule", {"rule_id": "l1_existing", "content": "smoke test: modified rule"})
rules = reload_rules()
check(any(r["content"] == "smoke test: modified rule" for r in rules),
      "rule content modified in JSON")
check(not any(r["content"] == "existing rule" for r in rules),
      "old rule content removed")

# L1: modify_rule on L0.5 — should REJECT
print("\n  [modify_rule → L0.5 (should reject)]")
try:
    l1_mgr.apply_update("modify_rule", {"rule_id": "constitution_1", "content": "evil rule"})
    rules = reload_rules()
    check(any(r["content"] == "安全第一" and r["id"] == "constitution_1" for r in rules),
          "L0.5 constitution NOT modified (protected)")
except ValueError:
    check(True, "L0.5 constitution rejected with ValueError")

# L1: remove_rule
print("\n  [remove_rule]")
l1_mgr.apply_update("remove_rule", {"rule_id": "l1_existing"})
rules = reload_rules()
check(not any(r["id"] == "l1_existing" for r in rules),
      "L1 rule removed from JSON")

# L1: remove_rule on L0.5 — should REJECT
print("\n  [remove_rule → L0.5 (should reject)]")
try:
    l1_mgr.apply_update("remove_rule", {"rule_id": "constitution_1"})
    rules = reload_rules()
    check(any(r["id"] == "constitution_1" for r in rules),
          "L0.5 constitution NOT removed (protected)")
except ValueError:
    check(True, "L0.5 constitution remove rejected with ValueError")

# ══════════════════════════════════════════════
print("\n=== L2 Manager Smoke Test ===")

# L2: add_card
print("\n  [add_card]")
new_card_content = "smoke test: L2 new card with strategy"
l2_mgr.apply_update("add_card", {
    "content": new_card_content,
    "domain": "game/leduc",
    "confidence": 0.75,
})
check(any(c.content == new_card_content for c in fk.cards),
      "new card exists in FlexibleKnowledge.cards")

# L2: modify_card
print("\n  [modify_card]")
modified = "smoke test: MODIFIED card content"
l2_mgr.apply_update("modify_card", {
    "card_id": card1.id,
    "content": modified,
})
check(any(c.id == card1.id and c.content == modified for c in fk.cards),
      f"card {card1.id} content modified")

# L2: modify_card on non-existent
print("\n  [modify_card → non-existent]")
l2_mgr.apply_update("modify_card", {"card_id": "nonexistent", "content": "whatever"})
check(True, "non-existent modify handled without crash")

# L2: remove_card
print("\n  [remove_card]")
l2_mgr.apply_update("remove_card", {"card_id": card2.id})
check(not any(c.id == card2.id for c in fk.cards),
      f"card {card2.id} removed")

# L2: remove_card on non-existent
print("\n  [remove_card → non-existent]")
l2_mgr.apply_update("remove_card", {"card_id": "nonexistent"})
check(True, "non-existent remove handled without crash")

# L2: boost_card (TODO — just verify it doesn't crash)
print("\n  [boost_card (TODO)]")
card3 = fk.add_card(content="boostable card", domain=leduc, confidence=0.5, source="seed")
l2_mgr.apply_update("boost_card", {"card_id": card3.id})
updated = next(c for c in fk.cards if c.id == card3.id)
check(updated.confidence > 0.5, f"card boosted: confidence {updated.confidence} > 0.5")

# L2: penalize_card (TODO)
print("\n  [penalize_card (TODO)]")
l2_mgr.apply_update("penalize_card", {"card_id": card3.id})
updated = next(c for c in fk.cards if c.id == card3.id)
check(updated.confidence < 0.55, f"card penalized: confidence {updated.confidence} < 0.55")

# ══════════════════════════════════════════════
print("\n=== L3 Manager Smoke Test ===")

SKILLS_DIR = LAYERS_DATA / "skills"

def skill_exists(name):
    return (SKILLS_DIR / name).exists() or (SKILLS_DIR / "game" / "leduc" / name).exists()

def find_skill_dir(name):
    for p in SKILLS_DIR.rglob(name):
        if p.is_dir() and ".archive" not in str(p):
            return p
    return None

def read_skill(name):
    d = find_skill_dir(name)
    if d:
        return (d / "SKILL.md").read_text(encoding="utf-8")
    return ""

# L3: add_skill
print("\n  [add_skill]")
l3_mgr.apply_update("add_skill", {
    "name": "smoke-test-new-skill",
    "content": "---\nname: smoke-test-new-skill\ndescription: Smoke test\ndomain: game/leduc\n---\n# Smoke Test Skill",
    "domain": "game/leduc",
})
check(skill_exists("smoke-test-new-skill"),
      "new skill directory created on disk")
content = read_skill("smoke-test-new-skill")
check("# Smoke Test Skill" in content,
      "new skill SKILL.md content correct")

# L3: update_skill
print("\n  [update_skill]")
l3_mgr.apply_update("update_skill", {
    "name": "test-skill-a",
    "content": "---\nname: test-skill-a\ndescription: A\ndomain: game/leduc\n---\n# Updated Content",
})
content = read_skill("test-skill-a")
check("# Updated Content" in content,
      "skill content updated on disk")

# L3: update_skill on non-existent
print("\n  [update_skill → non-existent (no-op)]")
old = read_skill("test-skill-a")
l3_mgr.apply_update("update_skill", {"name": "nonexistent", "content": "should-not-write"})
check(read_skill("test-skill-a") == old,
      "existing skill NOT affected by failed update")
check(not find_skill_dir("nonexistent"),
      "non-existent skill NOT created by failed update")

# L3: remove_skill
print("\n  [remove_skill]")
l3_mgr.apply_update("remove_skill", {"name": "test-skill-b"})
archive = SKILLS_DIR / ".archive" / "test-skill-b"
check(archive.exists(),
      f"removed skill moved to .archive (soft delete)")
check(not find_skill_dir("test-skill-b"),
      "original skill directory gone")

# L3: remove_skill on non-existent
print("\n  [remove_skill → non-existent (no-op)]")
l3_mgr.apply_update("remove_skill", {"name": "nonexistent"})
check(True, "non-existent remove handled without crash")

# ══════════════════════════════════════════════
print(f"\n{'='*50}")
if errors:
    print(f"FAILED: {len(errors)} error(s):")
    for e in errors:
        print(f"  - {e}")
    sys.exit(1)
else:
    print("ALL SMOKE TESTS PASSED")
    shutil.rmtree(DATA_DIR, ignore_errors=True)
