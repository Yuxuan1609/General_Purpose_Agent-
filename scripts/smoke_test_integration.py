"""Integration smoke test for Phase 2.2: game -> pending -> learn -> verify.

Simulates the full flow: run Leduc games (via RLCard), produce pending records,
trigger LearningEnv, dispatch to Agent (Executor + Layers), apply changes.
Uses a mock LLM client to avoid real API calls.
"""
from __future__ import annotations
import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from core.types import TaskObservation
from core.env.learning_env import LearningEnv
from core.task import Domain


def main():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)

        # ── Setup knowledge stores ──────────────────────────────────
        from core.philosophy import Philosophy
        phil = Philosophy(tmp / "l1_rules.json", max_rules=20)
        phil.add_rule("棋牌游戏中基于概率期望决策", created_by="seed", source="l1")
        phil.add_rule("持有强牌积极加注", created_by="seed", source="l1")

        from core.flexible_knowledge import FlexibleKnowledge
        l2_idx = tmp / "l2_index.json"
        l2_idx.write_text('{"version":1,"chapters":[],"relations":[]}')
        fk = FlexibleKnowledge(tmp / "knowledge", l2_idx)
        fk.add_card("持有K翻牌前加注", Domain("game/leduc", "specific"),
                     confidence=0.8, source="seed")
        fk.add_card("成对后全力加注", Domain("game/leduc", "specific"),
                     confidence=0.85, source="seed")

        from core.skill_layer import SkillLayer
        sl = SkillLayer(tmp / "skills")

        knowledge = {"l1": phil, "l2": fk, "l3": sl}

        # ── Simulate game loop: create pending records ──────────────
        pending = tmp / "pending"
        domain_dir = pending / "game_leduc"
        domain_dir.mkdir(parents=True)

        # 3 episodes with multiple steps each
        for ep in range(1, 4):
            steps = []
            for s in range(3):
                action = "raise" if (ep + s) % 3 == 0 else "fold" if (ep + s) % 3 == 1 else "call"
                steps.append({
                    "session": {"id": f"ep{ep}", "domain": "game/leduc", "step_index": s},
                    "observation": {"meta": "Play Leduc", "state": {}},
                    "notify_layers": {
                        "l0_5_1": {
                            "result": action,
                            "reasoning": f"ep{ep} step{s} decision based on hand strength",
                            "rules_applied": ["概率期望决策"],
                        },
                        "l2": {
                            "reply": f"Recommend {action}",
                            "cards_used": ["card_a"] if action == "raise" else [],
                            "l3_received": {"skills": [
                                {"name": "leduc-preflop-raise"} if action == "raise" else {}
                            ]},
                        },
                    },
                    "action": action,
                })
            (domain_dir / f"ep{ep}.json").write_text(
                json.dumps(steps, ensure_ascii=False), encoding="utf-8")

        print(f"[pending] Created 3 episodes, 9 steps total")

        # ── Learning cycle: reset ───────────────────────────────────
        lenv = LearningEnv(pending, knowledge)

        state = lenv.reset("learn from recent leduc games")
        print(f"[reset] observation: {len(state.observation)} chars")
        assert "raise" in state.observation
        assert state.observation != ""

        # ── Build TaskObservation for Agent ─────────────────────────
        obs = lenv.build_task_observation()
        assert obs is not None
        assert "Output format" in obs.meta
        assert "output_schema" in obs.state
        print(f"[task] meta: {len(obs.meta)} chars, output_schema layers: {list(obs.state['output_schema'].keys())}")
        print(f"[task] session.domains_hint: {obs.session['domains_hint']}")

        # ── Simulate Agent output (notify_layers from Executor) ─────
        rule_id = phil.all_rules()[0].id
        agent_output = {
            "l0_5_1": {
                "result": "ok", "done": True,
                "l1_modifications": [{
                    "target": f"l1/{rule_id}",
                    "type": "update",
                    "payload": {
                        "content": "棋牌游戏中基于概率期望决策，翻牌后重新评估手牌强度",
                        "reason": "观察到翻牌后决策与翻牌前策略不一致",
                    },
                }],
            },
            "l2": {
                "reply": "analysis",
                "cards_used": ["card_a"],
                "l2_modifications": [{
                    "target": "l2/new_tactic",
                    "type": "create",
                    "payload": {
                        "content": "翻牌后对手check时加注试探",
                        "domain": "game/leduc",
                        "confidence": 0.7,
                        "reason": "从recent games提取新策略",
                    },
                }],
                "l3_received": {"skills": [{"name": "leduc-preflop-raise"}]},
            },
            "l3": {
                "skills_matched": [], "l3_modifications": [],
            },
        }

        # ── Step: apply modifications ───────────────────────────────
        step = lenv.step(json.dumps(agent_output, ensure_ascii=False, default=str))
        print(f"[step] {step.state.observation}")
        print(f"[step] reward={step.reward} done={step.done}")
        assert "L1 rules" in step.state.observation
        assert "L2 cards" in step.state.observation
        assert step.reward == 0.0

        # ── Verify knowledge changed ────────────────────────────────
        modified_rule = [r for r in phil.all_rules() if "翻牌后" in r.content]
        assert len(modified_rule) == 1
        print(f"[verify] L1 rule modified: {modified_rule[0].content[:60]} (v{modified_rule[0].version})")

        new_card = [c for c in fk.cards if "试探" in c.content]
        assert len(new_card) == 1
        print(f"[verify] L2 card created: {new_card[0].content}")

        # ── Verify usage stats ──────────────────────────────────────
        assert stats.exists()
        st = json.loads(stats.read_text())
        assert st["l2"]["card_a"]["use_count"] >= 1
        assert st["l3"]["leduc-preflop-raise"]["use_count"] >= 1
        print(f"[verify] usage stats tracked")

        # ── Archive pending ──────────────────────────────────────────
        moved = lenv.archive_pending()
        assert moved > 0
        learned_dir = tmp / "learned" / "game_leduc"
        assert learned_dir.exists()
        assert len(list(learned_dir.glob("*.json"))) == moved
        print(f"[archive] moved {moved} files to learned/")

        # ── Summary ──────────────────────────────────────────────────
        print("\n" + "=" * 40)
        print("  Phase 2.2 INTEGRATION SMOKE TEST PASSED")
        print("=" * 40)


if __name__ == "__main__":
    main()
