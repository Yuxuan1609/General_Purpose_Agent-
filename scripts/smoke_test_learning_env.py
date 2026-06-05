"""Smoke test with full input/output display for Phase 2.1 review."""
from __future__ import annotations
import json
import sys
import tempfile
from pathlib import Path

_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from core.env.learning_env import LearningEnv
from core.task import Domain


def show(title, content):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")
    print(content)


def main():
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)

        # ── Setup ──
        from core.philosophy import Philosophy
        phil = Philosophy(tmp_path / "l1_rules.json", max_rules=20)
        phil.add_rule("面对强牌时积极加注", created_by="seed", source="l1")
        phil.add_rule("持有弱牌时优先弃牌", created_by="seed", source="l1")
        phil.add_rule("中等牌力时观察对手行为再决策", created_by="seed", source="l0_5")

        from core.flexible_knowledge import FlexibleKnowledge
        l2_idx = tmp_path / "l2_index.json"
        l2_idx.write_text('{"version":1,"chapters":[],"relations":[]}')
        fk = FlexibleKnowledge(tmp_path / "knowledge", l2_idx)
        fk.add_card("有对子时应积极加注", Domain("game/leduc", "specific"),
                     confidence=0.8, source="seed")
        fk.add_card("翻牌前弃牌保留筹码", Domain("game/leduc", "specific"),
                     confidence=0.6, source="seed")
        fk.add_card("翻牌后对手弱动作时可加注", Domain("game/leduc", "specific"),
                     confidence=0.5, source="seed")

        from core.skill_layer import SkillLayer
        from core.tools.registry import ToolRegistry
        sl = SkillLayer(tmp_path / "skills", ToolRegistry())

        knowledge = {"l1": phil, "l2": fk, "l3": sl}

        # ── Pending records ──
        pending = tmp_path / "pending"
        domain_dir = pending / "game_leduc"
        domain_dir.mkdir(parents=True)
        records = [
            {
                "session": {"id": "sess_1", "domain": "game/leduc", "step_index": 0},
                "observation": {"meta": "Play Leduc", "state": {}},
                "notify_layers": {
                    "l0_5_1": {
                        "result": "raise",
                        "reasoning": "手牌为K，根据L1规则'面对强牌时积极加注'决定加注",
                        "rules_applied": ["面对强牌时积极加注"],
                    },
                    "l2": {
                        "reply": "推荐加注",
                        "cards_used": ["有对子时应积极加注"],
                        "l3_received": {"skills": [{"name": "leduc-preflop-raise"}]},
                    },
                },
                "action": "raise",
            },
            {
                "session": {"id": "sess_1", "domain": "game/leduc", "step_index": 1},
                "observation": {"meta": "Play Leduc", "state": {}},
                "notify_layers": {
                    "l0_5_1": {
                        "result": "fold",
                        "reasoning": "手牌为J，对手加注，持有弱牌优先弃牌",
                        "rules_applied": ["持有弱牌时优先弃牌"],
                    },
                    "l2": {
                        "reply": "建议弃牌",
                        "cards_used": ["翻牌前弃牌保留筹码"],
                        "l3_received": {"skills": []},
                    },
                },
                "action": "fold",
            },
        ]
        (domain_dir / "sess_1_20260605.json").write_text(
            json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")

        # ══════════════════════════════════════════════════════════════
        # Step 1: reset() → 构建 observation
        # ══════════════════════════════════════════════════════════════
        stats_file = tmp_path / "learning_stats.json"
        env = LearningEnv(pending, knowledge, stats_file=stats_file)
        state = env.reset("learn from recent leduc games")

        show("STEP 1: reset() 输出 → EnvState",
             f"observation:\n{state.observation}")

        # ══════════════════════════════════════════════════════════════
        # Step 2: build_task_observation() → meta 注入输出格式
        # ══════════════════════════════════════════════════════════════
        obs = env.build_task_observation()

        show("STEP 2: build_task_observation() → meta (Agent 收到的任务描述+输出格式)",
             f"meta (前400字符):\n{obs.meta[:400]}...\n\n"
             f"session: {json.dumps(obs.session, ensure_ascii=False, indent=2)}")

        # ══════════════════════════════════════════════════════════════
        # Step 3: Agent 模拟输出 → step() 解析执行
        # ══════════════════════════════════════════════════════════════
        rule_id = phil.all_rules()[0].id
        agent_output = {
            "l0_5_1": {
                "result": "ok",
                "done": True,
                "reasoning": "分析了两局对局，发现翻牌前加注策略缺少翻牌后的应对说明",
                "l1_modifications": [
                    {
                        "target": f"l1/{rule_id}",
                        "type": "update",
                        "payload": {
                            "content": "面对强牌时积极加注；翻牌后对手示弱可加大注，对手反加则根据公共牌重新评估",
                            "reason": "原规则只覆盖翻牌前，缺少翻牌后分支策略",
                        },
                    }
                ],
            },
            "l2": {
                "reply": "L2 知识卡片分析完成",
                "reasoning": "翻牌后对手check时应加注试探这张卡片置信度偏低但最近对局中有效",
                "cards_used": ["card_a", "card_b"],
                "l2_modifications": [
                    {
                        "target": "l2/new_skill_probe",
                        "type": "create",
                        "payload": {
                            "content": "翻牌后对手check时加注试探，可迫使弱牌弃牌或暴露强牌",
                            "domain": "game/leduc",
                            "confidence": 0.7,
                            "reason": "从最近对局中提取的新模式",
                        },
                    },
                    {
                        "target": f"l2/{fk.cards[0].id}",
                        "type": "update",
                        "payload": {
                            "content": "有对子时应积极加注，翻牌后公共牌有利则持续施压",
                            "reason": "根据胜率数据调整加注力度",
                        },
                    },
                ],
                "l3_received": {
                    "skills": [{"name": "leduc-preflop-raise"}],
                },
            },
            "l3": {
                "skills_matched": ["leduc-preflop-raise"],
                "skills_used": ["leduc-preflop-raise"],
                "l3_modifications": [],
            },
        }

        agent_json = json.dumps(agent_output, ensure_ascii=False, indent=2)
        show("STEP 3: Agent 输出 → notify_layers (作为 step() 输入)",
             agent_json[:800] + ("..." if len(agent_json) > 800 else ""))

        step = env.step(agent_json)

        show("STEP 3 结果: EnvStep",
             f"state.observation:\n  {step.state.observation}\n\n"
             f"reward: {step.reward}\n"
             f"done: {step.done}")

        # ══════════════════════════════════════════════════════════════
        # Step 4: 验证知识变更
        # ══════════════════════════════════════════════════════════════
        rules = phil.all_rules()
        show("STEP 4: 验证 — L1 规则变更",
             "\n".join(f"  [{r.id}] [{r.source}] (v{r.version}) {r.content[:80]}"
                       for r in rules))

        show("STEP 4: 验证 — L2 卡片变更",
             "\n".join(f"  [{c.id}] [{c.domain.path}] conf={c.confidence:.1f} {c.content[:80]}"
                       for c in fk.cards))

        stats = json.loads(stats_file.read_text()) if stats_file.exists() else {}
        show("STEP 4: 验证 — 使用统计 (learning_stats.json)",
             json.dumps(stats, ensure_ascii=False, indent=2))

        # ══════════════════════════════════════════════════════════════
        # 模板提取
        # ══════════════════════════════════════════════════════════════
        show("输出格式模板 (Phase 2.2 Agent prompt 参考)", """
# ── 单层修改条目 ──
# L1 修改 (在 l0_5_1 NOTIFY.l1_modifications)
{
  "target": "l1/<rule_id>",          # create时为 l1/new_name
  "type": "update|create|deprecate",
  "payload": {
    "content": "<完整规则内容>",
    "reason": "<修改原因，引用对局证据>"
  }
}

# L2 修改 (在 l2 NOTIFY.l2_modifications)
{
  "target": "l2/<card_id>",          # create时为 l2/new_card_name
  "type": "update|create|deprecate",
  "payload": {
    "content": "<完整卡片内容>",
    "reason": "<原因>",
    "domain": "<仅create: game/leduc等>",
    "confidence": 0.7                # 仅create，默认0.5
  }
}

# L3 修改 (在 l3 NOTIFY.l3_modifications)
{
  "target": "l3/<skill_name>",
  "type": "update|create|deprecate",
  "payload": {
    "content": "<完整SKILL.md内容>",
    "reason": "<原因>",
    "domain": "<仅create>"
  }
}

# summary: 当前所有层会在同一个 notify_layers dict 中返回
# LearningEnv 按层解析并路由到对应 store
""")


if __name__ == "__main__":
    main()
