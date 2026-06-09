from __future__ import annotations
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import yaml

from core.env.base import Environment, EnvState, EnvStep
from core.env.threshold_scorer import ThresholdScorer
from core.types import TaskObservation

logger = logging.getLogger(__name__)

# ── Consolidation spec loader ──────────────────────────────────────────

def load_consolidation_spec(spec_path: Path | str | None = None) -> dict:
    """Load consolidation spec from YAML config.

    Args:
        spec_path: Path to consolidation.yaml. If None, uses the default
                   config/layers/consolidation.yaml relative to project root.

    Returns:
        dict with per-layer entry specs, limits, and consolidation strategies.
        Returns {} if file not found (graceful degradation).
    """
    if spec_path is None:
        # Try project-root-relative default path
        candidate = Path(__file__).resolve().parent.parent.parent / "config" / "layers" / "consolidation.yaml"
    else:
        candidate = Path(spec_path)

    if not candidate.exists():
        logger.debug("Consolidation spec not found at %s, using defaults", candidate)
        return {}

    try:
        with open(candidate, "r", encoding="utf-8") as f:
            spec = yaml.safe_load(f) or {}
        logger.debug("Loaded consolidation spec from %s: %s",
                     candidate, list(spec.keys()))
        return spec
    except Exception as e:
        logger.warning("Failed to load consolidation spec: %s", e)
        return {}

# Per-layer output format — each layer checks its key in state and merges
# the field schema into its JSON output. Field descriptions reference
# the existing knowledge format for that layer.
_L1_OUTPUT = {
    "l1_modifications": [
        {"target": "l1/<rule_id> (target for modify/deprecate; arbitrary name for create)",
         "type": "update | create | deprecate",
         "payload": {
             "content": "string (full rule text, ~1-2 sentences matching existing L1 rule granularity)",
             "reason": "string (why, citing specific execution record evidence)",
         }},
    ],
}

_L2_OUTPUT = {
    "l2_modifications": [
        {"target": "l2/<card_id> (existing card id for update/deprecate; arbitrary id for create)",
         "type": "update | create | deprecate",
         "payload": {
             "content": "string (full card content, matching existing KnowledgeCard granularity: domain-specific strategy tip)",
             "reason": "string (why this change)",
             "domain": "string (domain path, only for create, e.g. game/leduc)",
             "confidence": "float 0.1-1.0 (only for create, default 0.5)",
         }},
    ],
}

_L3_OUTPUT = {
    "l3_modifications": [
        {"target": "l3/<skill_name> (existing skill name for update/deprecate; new name for create)",
         "type": "update | create | deprecate",
         "payload": {
             "content": "string (full SKILL.md content: YAML frontmatter + markdown body, matching existing skill format)",
             "reason": "string (why this change)",
             "domain": "string (domain path, only for create)",
         }},
    ],
}


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


class LearningEnv(Environment):
    """Learning environment — consumes ExecutionRecords, produces knowledge changes.

    Shares Executor + Layers + ToolUse with GameEnv. Learning is modeled as
    a standard env: observation = pending records as LearningUnits,
    action = Agent's per-layer NOTIFY with modifications,
    step = parse NOTIFY layers → validate → apply → record stats.

    Agent decides WHAT to change; LearningEnv executes HOW and tracks usage.
    """

    def __init__(self, pending_dir: Path, knowledge_stores: dict,
                 preprocessing_llm=None, stats_file: Path | None = None,
                 l2_card_limit: int = 30, l3_skill_limit: int = 20,
                 dry_run: bool = False,
                 consolidation_spec: dict | None = None):
        self._pending_dir = Path(pending_dir)
        self._knowledge = knowledge_stores
        self._pre_llm = preprocessing_llm
        self._scorer = ThresholdScorer(pending_dir)
        self._stats_file = Path(stats_file) if stats_file else (
            self._pending_dir.parent / "learning_stats.json")
        self._l2_limit = l2_card_limit
        self._l3_limit = l3_skill_limit
        self._dry_run = dry_run

        # Consolidation spec — loaded from YAML or passed directly
        self._consolidation_spec = consolidation_spec or load_consolidation_spec()

        self._pending_records: list[dict] = []
        self._enriched_units: list[dict] = []
        self._step_count: int = 0
        self._done: bool = False
        self._current_observation: str = ""
        self._base_domain: str = "general"
        self._stats: dict = self._load_stats()

        # Per-layer reverse-notify feedback — populated by step(),
        # consumed by build_task_observation() / build_consolidation_task().
        # feedback (shared, read by all layers) + lX_feedback (per-layer).
        self._shared_feedback: str = ""
        self._layer_feedback: dict[str, str] = {}

    # ── public API ──────────────────────────────────────────────────────

    def reset(self, task_description: str) -> EnvState:
        domain = self._extract_domain(task_description)
        self._base_domain = domain

        records = self._scan_pending(domain)
        if not records:
            self._pending_records = []
            self._done = True
            return EnvState(observation="")

        self._pending_records = records
        self._step_count = 0
        self._done = False

        learning_units = self._build_learning_units(records)
        obs_text = self._format_observation(learning_units, domain)

        self._current_observation = obs_text
        self._enriched_units = learning_units  # for build_task_observation
        return EnvState(observation=obs_text)

    def step(self, action: str) -> EnvStep:
        parsed = self._parse_notify_layers(action)
        if not parsed:
            self._step_count += 1
            return EnvStep(
                state=EnvState(observation="(no modifications parsed)"),
                reward=0.0, done=True)
        return self._apply_parsed_mods(parsed)

    def apply_modifications(self, notify_layers: dict) -> EnvStep:
        """Apply structured modifications from tool calls (consolidation).
        notify_layers: {"l0_5_1": {...l1_modifications: [...]}, "l2": {...}, "l3": {...}}
        """
        parsed: dict = {
            "l1_modifications": notify_layers.get("l0_5_1", {}).get("l1_modifications", []),
            "l2_modifications": notify_layers.get("l2", {}).get("l2_modifications", []),
            "l3_modifications": notify_layers.get("l3", {}).get("l3_modifications", []),
        }
        return self._apply_parsed_mods(parsed)

    def _apply_parsed_mods(self, parsed: dict) -> EnvStep:

        if not self._dry_run:
            self._update_usage_stats(parsed)

        summary = {"l1": [], "l2": [], "l3": [], "errors": []}
        feedback: dict[str, list[str]] = {"l1": [], "l2": [], "l3": []}
        for layer_key in ("l1", "l2", "l3"):
            mods = parsed.get(f"{layer_key}_modifications", [])
            for mod in mods:
                target = mod.get("target", "?")
                mod_type = mod.get("type", "?")
                try:
                    if not self._dry_run:
                        self._apply_layer_mod(layer_key, mod)
                    summary[layer_key].append(target)
                    feedback[layer_key].append(f"{mod_type} {target}: ok")
                except Exception as e:
                    summary["errors"].append(
                        {"target": target, "error": str(e)})
                    feedback[layer_key].append(f"{mod_type} {target}: REJECTED ({e})")
                    logger.warning("Failed to apply %s mod: %s", layer_key, e)
        self._layer_feedback = {
            "l1": "\n".join(feedback["l1"]) if feedback["l1"] else "",
            "l2": "\n".join(feedback["l2"]) if feedback["l2"] else "",
            "l3": "\n".join(feedback["l3"]) if feedback["l3"] else "",
        }
        total = sum(len(v) for v in feedback.values())
        ok_count = sum(1 for v in feedback.values() for x in v if x.endswith(": ok"))
        rej_count = total - ok_count
        mode = "dry-run (未实际应用)" if self._dry_run else "已应用"
        self._shared_feedback = (
            f"本次共 {total} 条修改 ({mode})：{ok_count} 成功"
            + (f"，{rej_count} 被拒" if rej_count else "")
        )

        if not self._dry_run:
            self._save_stats()
        self._step_count += 1
        self._done = True

        return EnvStep(
            state=self._build_step_state(summary),
            reward=0.0, done=True)

    def build_task_observation(self) -> TaskObservation | None:
        if not self._current_observation:
            return None

        # Per-layer design: each layer reads state.learning_units directly.
        # L1's query to L2 carries task decomposition, not raw data.
        # L2's l3_task to L3 carries operation description, not raw data.
        return TaskObservation(
            meta=self._current_observation,
            state={
                "current": self._current_observation,
                "history": "",
                "learning_units": getattr(self, '_enriched_units', self._pending_records),
                "l1_output_format": _L1_OUTPUT,
                "l2_output_format": _L2_OUTPUT,
                "l3_output_format": _L3_OUTPUT,
                "feedback": self._shared_feedback,
                "l1_feedback": self._layer_feedback.get("l1", ""),
                "l2_feedback": self._layer_feedback.get("l2", ""),
                "l3_feedback": self._layer_feedback.get("l3", ""),
            },
            session={
                "domain": self._base_domain,
                "domains_hint": ["learning/reflect", self._base_domain],
                "id": f"learning_{self._step_count}",
                "step_index": self._step_count,
                "enable_learning": False,
            },
        )

    def build_consolidation_task(self) -> TaskObservation | None:
        l2 = self._knowledge.get("l2")
        l3 = self._knowledge.get("l3")
        l1_rules = self._knowledge.get("l1")
        needs_l2 = l2 and len(l2.cards) > self._l2_limit
        needs_l3 = l3 and len(l3.list_all()) > self._l3_limit

        # ── Build triggered domain lists (DD1: dual trigger) ──
        cons_state = self._stats.get("_consolidation", {})
        spec = self._consolidation_spec

        l2_limits = spec.get("l2", {}).get("limits", {}) if spec else {}
        l2_soft = l2_limits.get("per_domain_soft", l2_limits.get("soft", 25)) if l2_limits else 25
        l2_hard = l2_limits.get("per_domain_hard", l2_limits.get("hard", 30)) if l2_limits else 30

        l3_limits = spec.get("l3", {}).get("limits", {}) if spec else {}
        l3_soft = l3_limits.get("per_domain_soft", l3_limits.get("soft", 15)) if l3_limits else 15
        l3_hard = l3_limits.get("per_domain_hard", l3_limits.get("hard", 20)) if l3_limits else 20

        l2_triggers: dict[str, str] = {}
        l3_triggers: dict[str, str] = {}
        from collections import Counter
        all_domains: set[str] = set()
        domain_counts: Counter[str] = Counter()
        skill_domain_counts: Counter[str] = Counter()

        if needs_l2 and l2:
            for c in l2.cards:
                domain_counts[c.domain.path] += 1
                all_domains.add(c.domain.path)
            for domain, count in domain_counts.items():
                mods = cons_state.get(domain, {}).get("mod_count", 0)
                if count > l2_soft:
                    l2_triggers[domain] = "capacity"
                elif mods >= 5:
                    l2_triggers[domain] = "maintenance"

        if needs_l3 and l3:
            for s in l3.list_all():
                skill_domain_counts[s.domain.path] += 1
                all_domains.add(s.domain.path)
            for domain, count in skill_domain_counts.items():
                mods = cons_state.get(domain, {}).get("mod_count", 0)
                if count > l3_soft:
                    l3_triggers[domain] = "capacity"
                elif mods >= 5:
                    l3_triggers[domain] = "maintenance"

        # Fallback: if total exceeds limit but no per-domain trigger, trigger all domains
        if needs_l2 and not l2_triggers and l2:
            for d in set(c.domain.path for c in l2.cards):
                l2_triggers[d] = "global_overflow"
                domain_counts[d] += 1
        if needs_l3 and not l3_triggers and l3:
            for d in set(s.domain.path for s in l3.list_all()):
                l3_triggers[d] = "global_overflow"
                skill_domain_counts[d] += 1

        if not l2_triggers and not l3_triggers:
            return None

        level = self.get_consolidation_level()
        level_info = spec.get("consolidation_levels", {}).get(level, {}) if spec else {}

        # ── meta: clear task description with trigger info ──
        triggered = sorted(set(l2_triggers.keys()) | set(l3_triggers.keys()))
        domain_list = ", ".join(triggered)
        meta_lines = [
            "## Knowledge Consolidation Task",
            "",
            f"**Level {level}**: {level_info.get('label', '整理')}.",
            f"Triggered domains: {domain_list}.",
            "All three layers must participate — each layer has its own sub-task in state.",
            "",
        ]
        if l2_triggers:
            target_count = sum(
                max(0, domain_counts.get(d, 0) - l2_soft)
                for d in l2_triggers if l2_triggers.get(d) == "capacity"
            )
            meta_lines.append("### L2 Cards — triggered domains")
            for domain, count in sorted(domain_counts.items()):
                if domain not in l2_triggers:
                    continue
                reason = l2_triggers[domain]
                mods = cons_state.get(domain, {}).get("mod_count", 0) if reason == "maintenance" else 0
                if reason == "capacity":
                    if count <= l2_soft:
                        meta_lines.append(
                            f"- **{domain}**: {count} cards (within limit {l2_soft} — included due to global overflow). "
                            f"Review for overlap with over-limit domains."
                        )
                    else:
                        over = count - l2_soft
                        meta_lines.append(
                            f"- **{domain}**: {count} cards (capacity overflow — {over} over soft limit {l2_soft}). "
                            f"Reduce to below {l2_soft} via merge/deprecate."
                        )
                elif reason == "global_overflow":
                    meta_lines.append(
                        f"- **{domain}**: {count} cards (included — global total exceeds limit). "
                        f"Review for quality, merge similar, deprecate unused."
                    )
                elif reason == "maintenance":
                    meta_lines.append(
                        f"- **{domain}**: {count} cards (routine maintenance — {mods} modifications since last consolidate). "
                        f"Review for quality, merge similar, deprecate unused."
                    )
            meta_lines.append("")
        if l3_triggers:
            meta_lines.append("### L3 Skills — triggered domains")
            for domain, count in sorted(skill_domain_counts.items()):
                if domain not in l3_triggers:
                    continue
                reason = l3_triggers[domain]
                mods = cons_state.get(domain, {}).get("mod_count", 0) if reason == "maintenance" else 0
                if reason == "capacity":
                    if count <= l3_soft:
                        meta_lines.append(
                            f"- **{domain}**: {count} skills (within limit {l3_soft} — included due to global overflow). "
                            f"Review for overlap with over-limit domains."
                        )
                    else:
                        over = count - l3_soft
                        meta_lines.append(
                            f"- **{domain}**: {count} skills (capacity overflow — {over} over soft limit {l3_soft}). "
                            f"Reduce to below {l3_soft} via deprecate/compile."
                        )
                elif reason == "global_overflow":
                    meta_lines.append(
                        f"- **{domain}**: {count} skills (included — global total exceeds limit). "
                        f"Review quality, deprecate unused, compile redundant."
                    )
                elif reason == "maintenance":
                    meta_lines.append(
                        f"- **{domain}**: {count} skills (routine maintenance — {mods} modifications since last consolidate). "
                        f"Review quality, deprecate unused, compile redundant."
                    )
            meta_lines.append("")
        meta = "\n".join(meta_lines)

        # ── l1_task: criteria text only (DD4 — no rule listing, system prompt has rules) ──
        l1_task = (
            "## L1 Task\n\n"
            "Review your behavior rules in the system prompt against the criteria below.\n\n"
            "### Judgment Criteria\n"
            "- **deprecate**: duplicate rules (semantic similarity > 80%), domain-specific content "
            "(should belong to L2), vague rules (< 20 chars with no specific directive), "
            "violates cross-domain methodology principle\n"
            "- **modify**: merge multiple rules into one while preserving complete semantics; "
            "also use modify to update usefulness/misleading/comment for rules "
            "that were helpful or misleading during reflection\n"
            "- **create**: only for new cross-domain methodology not achievable via modify\n\n"
            "Use tools: deprecate_l1_rule / create_l1_rule / modify_l1_rule"
        )

        # ── l2_task: target_domains dict (DD4 — cards fetched by L2Manager) ──
        l2_task = json.dumps({
            "criteria": (
                "### Judgment Criteria\n"
                "- **deprecate**: used=0 + content appears to be placeholder/experimental, "
                "content semantically > 80% similar to another card (keep higher-quality one)\n"
                "- **modify**: merge >= 2 similar cards in same domain into one refined card; "
                "also use modify to update usefulness/misleading/comment for cards "
                "that were helpful or misleading during reflection\n"
                "- **create**: cross-domain generalization (multiple similar cards -> one higher-level card)"
            ),
            "target_domains": list(l2_triggers.keys()),
            "triggers": l2_triggers,
        }, ensure_ascii=False)

        # ── l3_task: target_domains dict (DD4 — skills fetched by L3Manager) ──
        l3_task = json.dumps({
            "criteria": (
                "### Judgment Criteria\n"
                "- **deprecate**: never matched/used (use_count=0), vague content, "
                "functionally overlaps with another skill\n"
                "- **modify**: add missing process steps, update outdated instructions; "
                "also use modify to update usefulness/misleading/comment\n"
                "- **create**: compile >= 3 high-activation same-domain cards into SKILL.md "
                "(write full YAML frontmatter + Markdown procedure)"
            ),
            "target_domains": list(l3_triggers.keys()),
            "triggers": l3_triggers,
        }, ensure_ascii=False)

        hint_domains = ["learning/compile"] + sorted(all_domains)

        return TaskObservation(
            meta=meta,
            state={
                "current": "Consolidation task — see per-layer tasks below",
                "history": "",
                "l1_output_format": _L1_OUTPUT,
                "l2_output_format": _L2_OUTPUT,
                "l3_output_format": _L3_OUTPUT,
                "l1_task": l1_task,
                "l2_task": l2_task,
                "l3_task": l3_task,
                "feedback": self._shared_feedback,
                "l1_feedback": self._layer_feedback.get("l1", ""),
                "l2_feedback": self._layer_feedback.get("l2", ""),
                "l3_feedback": self._layer_feedback.get("l3", ""),
            },
            session={
                "domain": "learning/compile",
                "domains_hint": list(dict.fromkeys(hint_domains)),
                "id": f"consolidation_{self._step_count}",
                "step_index": 0,
                "enable_learning": False,
            },
        )

    # ── consolidation monitoring ────────────────────────────────────────

    def needs_consolidation(self) -> bool:
        """Check if any layer exceeds its capacity limit.

        Triggers when L2 cards or L3 skills exceed configured thresholds.
        """
        l2 = self._knowledge.get("l2")
        if l2 and len(l2.cards) > self._l2_limit:
            logger.info("Consolidation needed: L2 cards=%d > limit=%d",
                        len(l2.cards), self._l2_limit)
            return True

        l3 = self._knowledge.get("l3")
        if l3 and len(l3.list_all()) > self._l3_limit:
            logger.info("Consolidation needed: L3 skills=%d > limit=%d",
                        len(l3.list_all()), self._l3_limit)
            return True

        return False

    def get_consolidation_level(self) -> int:
        """Return consolidation intensity based on overflow severity.

        1 = mild (routine cleanup) — 1-5 items over limit
        2 = deep (aggressive merge/prune) — >5 items over limit
        """
        level = 0
        l2 = self._knowledge.get("l2")
        if l2:
            over = len(l2.cards) - self._l2_limit
            level = max(level, 2 if over > 5 else (1 if over > 0 else 0))
        l3 = self._knowledge.get("l3")
        if l3:
            over = len(l3.list_all()) - self._l3_limit
            level = max(level, 2 if over > 5 else (1 if over > 0 else 0))
        return level

    def archive_pending(self) -> int:
        import shutil
        domain_dir = self._pending_dir / self._base_domain.replace("/", "_")
        if not domain_dir.exists():
            return 0
        learned_dir = (
            self._pending_dir.parent / "learned" /
            self._base_domain.replace("/", "_"))
        learned_dir.mkdir(parents=True, exist_ok=True)
        moved = 0
        for f in sorted(domain_dir.glob("*.json")):
            shutil.move(str(f), str(learned_dir / f.name))
            moved += 1
        logger.info("Archived %d pending file(s) -> %s", moved, learned_dir)
        return moved

    # ── notify parsing ──────────────────────────────────────────────────

    def _parse_notify_layers(self, action: str) -> dict:
        action = action.strip()

        if not (action.startswith("{") or action.startswith("[")):
            if self._pre_llm:
                return self._parse_notify_llm(action)
            logger.warning("Cannot parse action as JSON, no LLM fallback")
            return {}

        try:
            parsed = json.loads(action)
        except json.JSONDecodeError:
            if self._pre_llm:
                return self._parse_notify_llm(action)
            return {}

        if not isinstance(parsed, dict):
            return {}

        result = {}
        l1_notify = parsed.get("l0_5_1", {})
        if isinstance(l1_notify, dict):
            result["l1_modifications"] = self._normalize_mods(
                l1_notify.get("l1_modifications", []))

        l2_notify = parsed.get("l2", {})
        if isinstance(l2_notify, dict):
            result["l2_modifications"] = self._normalize_mods(
                l2_notify.get("l2_modifications", []))
            result["_l2_cards_used"] = l2_notify.get("cards_used", [])

        l3_notify = parsed.get("l3", {})
        if isinstance(l3_notify, dict):
            result["l3_modifications"] = self._normalize_mods(
                l3_notify.get("l3_modifications", []))
            result["_l3_skills_used"] = l3_notify.get("skills_used", [])

        return result

    @staticmethod
    def _normalize_mods(raw) -> list[dict]:
        if isinstance(raw, list):
            return raw
        return []

    def _parse_notify_llm(self, text: str) -> dict:
        prompt = (
            "Extract per-layer modifications from the following analysis. "
            "Output JSON with l1_modifications, l2_modifications, l3_modifications arrays.\n\n"
            f"Analysis:\n{text}"
        )
        try:
            resp = self._pre_llm.chat(
                messages=[{"role": "user", "content": prompt}],
                json_mode=True,
            )
            raw = resp.text if hasattr(resp, 'text') else str(resp)
            parsed = json.loads(raw)
            return {
                "l1_modifications": self._normalize_mods(parsed.get("l1_modifications", [])),
                "l2_modifications": self._normalize_mods(parsed.get("l2_modifications", [])),
                "l3_modifications": self._normalize_mods(parsed.get("l3_modifications", [])),
            }
        except Exception as e:
            logger.warning("LLM parse failed: %s", e)
            return {}

    # ── apply ────────────────────────────────────────────────────────────

    def _apply_layer_mod(self, layer: str, modification: dict) -> None:
        target = modification.get("target", "")
        mod_type = modification.get("type", "update")
        payload = modification.get("payload", {})

        if "/" not in target:
            target = f"{layer}/{target}"
        layer_prefix, key = target.split("/", 1)
        if layer_prefix != layer:
            raise ValueError(f"Target layer '{layer_prefix}' != mod layer '{layer}'")
        if mod_type not in ("update", "create", "deprecate"):
            raise ValueError(f"Unknown type: {mod_type}")

        if layer == "l1":
            self._apply_l1(mod_type, key, payload)
        elif layer == "l2":
            self._apply_l2(mod_type, key, payload)
        elif layer == "l3":
            self._apply_l3(mod_type, key, payload)

    def _apply_l1(self, mod_type: str, rule_id: str, payload: dict) -> None:
        store = self._knowledge.get("l1")
        if store is None:
            raise ValueError("L1 store not available")
        content = payload.get("content", "")
        if len(content) > 500:
            raise ValueError(f"Content too long: {len(content)} chars")
        if mod_type == "create":
            store.add_rule(content, created_by="learning_env", source="l1")
        elif mod_type == "update":
            store.modify_rule(rule_id, content)
        elif mod_type == "deprecate":
            store.remove_rule(rule_id)

    def _apply_l2(self, mod_type: str, card_id: str, payload: dict) -> None:
        store = self._knowledge.get("l2")
        if store is None:
            raise ValueError("L2 store not available")
        content = payload.get("content", "")
        from core.task import Domain
        if mod_type == "create":
            domain = payload.get("domain", "general")
            confidence = max(0.1, min(1.0, payload.get("confidence", 0.5)))
            store.add_card(content=content, domain=Domain(domain, "specific"),
                           confidence=confidence, source="learning_env")
        elif mod_type == "update":
            result = store.modify_card(card_id, content)
            if result is None:
                raise ValueError(f"Card not found: {card_id}")
        elif mod_type == "deprecate":
            if not store.remove_card(card_id):
                raise ValueError(f"Card not found: {card_id}")

    def _apply_l3(self, mod_type: str, skill_name: str, payload: dict) -> None:
        store = self._knowledge.get("l3")
        if store is None:
            raise ValueError("L3 store not available")
        content = payload.get("content", "")
        from core.task import Domain
        if mod_type == "create":
            domain = payload.get("domain", "general")
            store.create_skill(name=skill_name, content=content,
                               domain=Domain(domain, "specific"),
                               created_by="learning_env")
        elif mod_type == "update":
            store.edit_skill(skill_name, content)
        elif mod_type == "deprecate":
            store.delete_skill(skill_name)

    # ── usage stats ──────────────────────────────────────────────────────

    def _update_usage_stats(self, parsed: dict) -> None:
        now = _now_iso()
        cards_used = parsed.get("_l2_cards_used", [])
        if isinstance(cards_used, list):
            for entry in cards_used:
                card_id = entry if isinstance(entry, str) else entry.get("id", "")
                if card_id:
                    self._inc_stat("l2", card_id, now)
        skills_used = parsed.get("_l3_skills_used", [])
        for entry in skills_used:
            skill_name = entry.get("name", "") if isinstance(entry, dict) else str(entry)
            if skill_name:
                self._inc_stat("l3", skill_name, now)

    def _inc_stat(self, layer: str, key: str, timestamp: str) -> None:
        layer_stats = self._stats.setdefault(layer, {})
        entry = layer_stats.setdefault(key, {"use_count": 0, "last_used": ""})
        entry["use_count"] += 1
        entry["last_used"] = timestamp

    def _load_stats(self) -> dict:
        if self._stats_file.exists():
            try:
                return json.loads(self._stats_file.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                pass
        return {}

    def _save_stats(self) -> None:
        self._stats_file.parent.mkdir(parents=True, exist_ok=True)
        import tempfile
        fd, tmp = tempfile.mkstemp(dir=self._stats_file.parent, suffix=".json")
        try:
            with open(fd, "w", encoding="utf-8") as f:
                json.dump(self._stats, f, ensure_ascii=False, indent=2)
            Path(tmp).replace(self._stats_file)
        finally:
            Path(tmp).unlink(missing_ok=True)

    # ── observation building ────────────────────────────────────────────

    def _build_step_state(self, summary: dict) -> EnvState:
        parts = []
        for layer in ("l1", "l2", "l3"):
            items = summary.get(layer, [])
            if items:
                label = {"l1": "L1 rules", "l2": "L2 cards", "l3": "L3 skills"}
                parts.append(f"{label[layer]}: " + ", ".join(str(i) for i in items))
        if not parts:
            parts.append("(no modifications)")
        errors = summary.get("errors", [])
        if errors:
            parts.append(f"Errors: {len(errors)}")
        return EnvState(
            observation="\n".join(parts),
            info={"step_count": self._step_count, "done": self._done},
        )

    def _build_learning_units(self, records: list[dict]) -> list[dict]:
        """Phase 2.2: LLM preprocess when available, else heuristic fallback."""
        if self._pre_llm is not None:
            try:
                return self._build_learning_units_llm(records)
            except Exception as e:
                logger.warning("LLM1 preprocessing failed, using heuristic: %s", e)
        return self._build_learning_units_heuristic(records)

    def _build_learning_units_llm(self, records: list[dict]) -> list[dict]:
        """LLM1: enrich raw records with structured per-layer reasoning."""
        cap = min(len(records), 20)
        summaries = []
        for i, rec in enumerate(records[:cap]):
            session = rec.get("session", {})
            notify = rec.get("notify_layers", {})
            l1_n = notify.get("l0_5_1", {})
            l2_n = notify.get("l2", {})
            summaries.append({
                "idx": i,
                "session_id": session.get("id", ""),
                "step": session.get("step_index", 0),
                "action": rec.get("action", ""),
                "l1_result": l1_n.get("result", ""),
                "l1_reasoning": str(l1_n.get("reasoning", ""))[:200],
                "l2_cards_used": str(l2_n.get("cards_used", []))[:200],
                "l3_skills": str(
                    [s.get("name", "") if isinstance(s, dict) else str(s)
                     for s in notify.get("l3", {}).get("skills_used", [])]
                ),
            })

        prompt = (
            "You are a learning data preprocessor. Convert raw game execution "
            "records into structured LearningUnits. For each record, extract:\n"
            "- summary: one-line description of what happened and why\n"
            "- l1_reasoning: what L1 rule/principle drove the decision\n"
            "- l2_reasoning: what L2 knowledge cards informed the decision\n"
            "- l3_reasoning: what L3 skills contributed\n\n"
            f"Records:\n{json.dumps(summaries, ensure_ascii=False, indent=2)}\n\n"
            "Return a JSON array of objects with fields: "
            "idx, summary, l1_reasoning, l2_reasoning, l3_reasoning."
        )
        logger.debug("── LLM1 Preprocess ──")
        logger.debug("  records: %d, prompt chars: %d", cap, len(prompt))
        logger.debug("  prompt:\n%s", prompt[:3000])
        resp = self._pre_llm.chat(
            messages=[{"role": "user", "content": prompt}],
            json_mode=True,
        )
        text = resp.text if hasattr(resp, 'text') else str(resp)
        enriched = json.loads(text)
        if not isinstance(enriched, list):
            enriched = []

        enriched_map = {e.get("idx", e.get("index", -1)): e for e in enriched}
        units = []
        for i in range(len(records)):
            rec = records[i]
            enrich = enriched_map.get(i, {})
            session = rec.get("session", {})
            notify = rec.get("notify_layers", {})
            units.append({
                "index": i,
                "session_id": session.get("id", "unknown"),
                "domain": session.get("domain", "general"),
                "action": str(rec.get("action", "")),
                "result": str(notify.get("l0_5_1", {}).get("result", "")),
                "reasoning": enrich.get("summary", "") or
                    str(notify.get("l0_5_1", {}).get("reasoning", ""))[:200],
                "step": session.get("step_index", 0),
                "l1_reasoning": enrich.get("l1_reasoning", ""),
                "l2_reasoning": enrich.get("l2_reasoning", ""),
                "l3_reasoning": enrich.get("l3_reasoning", ""),
            })
        return units

    def _build_learning_units_heuristic(self, records: list[dict]) -> list[dict]:
        units = []
        for i, rec in enumerate(records):
            session = rec.get("session", {})
            notify = rec.get("notify_layers", {})
            l1_notify = notify.get("l0_5_1", {})
            units.append({
                "index": i,
                "session_id": session.get("id", "unknown"),
                "domain": session.get("domain", "general"),
                "action": str(rec.get("action", "")),
                "result": str(l1_notify.get("result", "")),
                "reasoning": str(l1_notify.get("reasoning", ""))[:200],
                "step": session.get("step_index", 0),
            })
        return units

    def _format_observation(self, units: list[dict], domain: str) -> str:
        return (
            f"从以下 {len(units)} 条 {domain} 执行记录中分析策略缺陷和改进机会。"
            f"同时反思本次学习策略是否有效。"
        )

    # ── utilities ────────────────────────────────────────────────────────

    def _extract_domain(self, task_description: str) -> str:
        desc_lower = task_description.lower()
        for keyword, domain in [
            ("leduc", "game/leduc"),
            ("doudizhu", "game/doudizhu"),
            ("coding", "coding"),
            ("learn", "learning/reflect"),
        ]:
            if keyword in desc_lower:
                return domain
        return "general"

    def _scan_pending(self, domain: str) -> list[dict]:
        records = []
        domain_dir = self._pending_dir / domain.replace("/", "_")
        if not domain_dir.exists():
            return records
        for f in sorted(domain_dir.glob("*.json")):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                records.extend(data if isinstance(data, list) else [data])
            except (json.JSONDecodeError, OSError):
                logger.warning("Failed to read pending record: %s", f)
        return records
