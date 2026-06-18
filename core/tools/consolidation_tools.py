"""Consolidation tools — registered in ToolRegistry, filtered by AgentContext."""
from __future__ import annotations
from dataclasses import dataclass, field
import json
import logging

logger = logging.getLogger(__name__)


@dataclass
class ConsolidationContext:
    """Immutable-ish context for consolidation tools.

    Replaces module-level global variables. Constructed once in chain_factory,
    injected into Manager constructors. pending_mods is the only mutable field
    (acts as a per-chain modification collector).
    """
    philosophy: object = None
    knowledge: object = None
    skill_layer: object = None
    domain_registry: object = None
    executor: object = None
    knowledge_stores: dict | None = None
    pending_mods: list[dict] = field(default_factory=list)

    def record_mod(self, mod: dict) -> None:
        self.pending_mods.append(mod)

    def drain_mods(self) -> list[dict]:
        mods = list(self.pending_mods)
        self.pending_mods.clear()
        return mods




L1_CONSOLIDATION_TOOL_NAMES = {
    "deprecate_l1_rule", "create_l1_rule", "modify_l1_rule",
    "create_domain", "query_domain", "deprecate_domain", "merge_domain",
}

L2_CONSOLIDATION_TOOL_NAMES = {
    "deprecate_l2_card", "create_l2_card", "modify_l2_card", "query_domain",
}

L3_CONSOLIDATION_TOOL_NAMES = {
    "deprecate_l3_skill", "create_l3_skill", "modify_l3_skill", "query_domain",
}


def register_consolidation_tools(tool_registry, ctx: ConsolidationContext | None = None):
    _ctx = ctx or ConsolidationContext()

    def _wrap(fn):
        return lambda args=None, **kw: fn(args, _ctx, **kw)

    tool_registry.register("deprecate_l1_rule", {
        "type": "function", "function": {
            "name": "deprecate_l1_rule",
            "description": "废弃（删除）一条 L1 行为准则。用于移除重复、低质量或违反跨领域原则的规则。",
            "parameters": {"type": "object", "properties": {
                "rule_id": {"type": "string", "description": "要删除的规则 id，如 l1_001"},
                "reason": {"type": "string", "description": "删除理由，如'与另一条重复'或'内容模糊'"},
            }, "required": ["rule_id", "reason"], "additionalProperties": False},
        },
    }, _wrap(_h_deprecate_l1_rule), toolset="consolidation", sync=True)

    tool_registry.register("create_l1_rule", {
        "type": "function", "function": {
            "name": "create_l1_rule",
            "description": "创建一条新的 L1 行为准则。用于合并重复规则或添加新的通用原则。",
            "parameters": {"type": "object", "properties": {
                "content": {"type": "string", "description": "完整规则文本，1-2句清晰可执行的行为准则"},
                "reason": {"type": "string", "description": "创建理由，如'合并了3条概率决策规则'"},
            }, "required": ["content", "reason"], "additionalProperties": False},
        },
    }, _wrap(_h_create_l1_rule), toolset="consolidation", sync=True)

    tool_registry.register("modify_l1_rule", {
        "type": "function", "function": {
            "name": "modify_l1_rule",
            "description": "Modify an existing L1 rule. Use content to update rule text, or pass only usefulness/misleading/comment to record quality feedback without changing content.\n\nQuality fields (both range -5 to +5):\n  usefulness: +5=critical help for correct decision, +3=helpful guidance, +1=slightly useful, 0=unset/no opinion, -1=not very useful, -3=useless/wasted tokens, -5=harmful leading to wrong decision.\n  misleading: +5=severely misleading causing critical error, +3=clearly misled reasoning, +1=slightly inaccurate/outdated, 0=unset/no opinion, -1=mostly accurate, -3=highly accurate/trustworthy, -5=completely reliable never misleads.\n  comment: natural language quality note, max 100 chars. Omit if no opinion.",
            "parameters": {"type": "object", "properties": {
                "rule_id": {"type": "string", "description": "Rule id to modify, e.g. l1_001"},
                "content": {"type": "string", "description": "Full modified rule text. Omit if only recording quality feedback without content change."},
                "reason": {"type": "string", "description": "Reason for modification or quality update"},
                "usefulness": {"type": "integer", "description": "How useful this rule was during reflection. Range -5 to +5."},
                "misleading": {"type": "integer", "description": "How misleading this rule was during reflection. Range -5 to +5."},
                "comment": {"type": "string", "description": "Quality description, max 100 chars."},
            }, "required": ["rule_id", "reason"], "additionalProperties": False},
        },
    }, _wrap(_h_modify_l1_rule), toolset="consolidation", sync=True)

    tool_registry.register("deprecate_l2_card", {
        "type": "function", "function": {
            "name": "deprecate_l2_card",
            "description": "废弃（删除）一张 L2 知识卡片。用于移除低置信度、从未使用或高度冗余的策略卡片。",
            "parameters": {"type": "object", "properties": {
                "card_id": {"type": "string", "description": "卡片 id，如 card_xxxxxxxx"},
                "reason": {"type": "string", "description": "删除理由，如'合并到 leduc_K_preflop'或'低置信度从未使用'"},
            }, "required": ["card_id", "reason"], "additionalProperties": False},
        },
    }, _wrap(_h_deprecate_l2_card), toolset="consolidation", sync=True)

    tool_registry.register("create_l2_card", {
        "type": "function", "function": {
            "name": "create_l2_card",
            "description": "创建一张新的 L2 知识卡片。用于合并多张相似卡片为一条精炼策略。",
            "parameters": {"type": "object", "properties": {
                "content": {"type": "string", "description": "完整卡片内容，格式：[场景] → [行动] + [理由]"},
                "domain": {"type": "string", "description": "所属 domain，如 game/leduc 或 game/doudizhu"},
                "reason": {"type": "string", "description": "创建理由，如'合并了3张K翻牌前加注策略卡片'"},
            }, "required": ["content", "domain", "reason"], "additionalProperties": False},
        },
    }, _wrap(_h_create_l2_card), toolset="consolidation", sync=True)

    tool_registry.register("modify_l2_card", {
        "type": "function", "function": {
            "name": "modify_l2_card",
            "description": "Modify an existing L2 card. Use content to update card text, domain to change domain assignment, or pass only quality fields for feedback.\n\nQuality fields (both range -5 to +5):\n  usefulness: +5=critical help, ... \n  misleading: +5=severely misleading, ...\n  comment: natural language quality note, max 100 chars.",
            "parameters": {"type": "object", "properties": {
                "card_id": {"type": "string", "description": "Card id to modify, e.g. card_xxxxxxxx"},
                "content": {"type": "string", "description": "Full modified card content. Omit if only recording quality feedback without content change."},
                "domain": {"type": "string", "description": "New domain path for this card. Use to move card to a different/sub domain during split/merge."},
                "reason": {"type": "string", "description": "Reason for modification or quality update"},
                "usefulness": {"type": "integer", "description": "How useful this card was during reflection. Range -5 to +5."},
                "misleading": {"type": "integer", "description": "How misleading this card was during reflection. Range -5 to +5."},
                "comment": {"type": "string", "description": "Quality description, max 100 chars."},
            }, "required": ["card_id", "reason"], "additionalProperties": False},
        },
    }, _wrap(_h_modify_l2_card), toolset="consolidation", sync=True)

    tool_registry.register("deprecate_l3_skill", {
        "type": "function", "function": {
            "name": "deprecate_l3_skill",
            "description": "废弃（删除）一个 L3 技能。用于移除低质量、从未使用或功能重叠的技能。",
            "parameters": {"type": "object", "properties": {
                "skill_name": {"type": "string", "description": "技能名称，如 leduc-bad-1"},
                "reason": {"type": "string", "description": "删除理由，如'低质量从未被匹配'或'与另一技能功能重叠'"},
            }, "required": ["skill_name", "reason"], "additionalProperties": False},
        },
    }, _wrap(_h_deprecate_l3_skill), toolset="consolidation", sync=True)

    tool_registry.register("create_l3_skill", {
        "type": "function", "function": {
            "name": "create_l3_skill",
            "description": "创建一个新的 L3 技能。用于将高激活同域卡片编译为可复用的标准化技能。",
            "parameters": {"type": "object", "properties": {
                "name": {"type": "string", "description": "技能名称，kebab-case 格式如 leduc-preflop-strategy"},
                "content": {"type": "string", "description": "完整 SKILL.md 内容（YAML frontmatter + Markdown body）"},
                "domain": {"type": "string", "description": "所属 domain，如 game/leduc"},
                "reason": {"type": "string", "description": "创建理由，如'编译自3张高激活配对加注卡片'"},
            }, "required": ["name", "content", "domain", "reason"], "additionalProperties": False},
        },
    }, _wrap(_h_create_l3_skill), toolset="consolidation", sync=True)

    tool_registry.register("modify_l3_skill", {
        "type": "function", "function": {
            "name": "modify_l3_skill",
            "description": "Modify an existing L3 skill. Use content to update SKILL.md, domain to change domain assignment, or pass only quality fields for feedback.\n\nQuality fields (both range -5 to +5):\n  usefulness: +5=critical help, ... \n  misleading: +5=severely misleading, ...\n  comment: natural language quality note, max 100 chars.",
            "parameters": {"type": "object", "properties": {
                "skill_name": {"type": "string", "description": "Skill name to modify"},
                "content": {"type": "string", "description": "Full modified SKILL.md content. Omit if only recording quality feedback without content change."},
                "domain": {"type": "string", "description": "New domain path for this skill. Use to move skill to a different/sub domain during split/merge."},
                "reason": {"type": "string", "description": "Reason for modification or quality update"},
                "usefulness": {"type": "integer", "description": "How useful this skill was during reflection. Range -5 to +5."},
                "misleading": {"type": "integer", "description": "How misleading this skill was during reflection. Range -5 to +5."},
                "comment": {"type": "string", "description": "Quality description, max 100 chars."},
            }, "required": ["skill_name", "reason"], "additionalProperties": False},
        },
    }, _wrap(_h_modify_l3_skill), toolset="consolidation", sync=True)

    tool_registry.register("query_domain", {
        "type": "function", "function": {
            "name": "query_domain",
            "description": "List all L2 cards and L3 skills in a domain. Use to inspect domain contents before splitting or merging.",
            "parameters": {"type": "object", "properties": {
                "domain": {"type": "string", "description": "Domain path to query, e.g. 'game/doudizhu'"},
            }, "required": ["domain"], "additionalProperties": False},
        },
    }, _wrap(_h_query_domain), toolset="consolidation", sync=True)

    tool_registry.register("deprecate_domain", {
        "type": "function", "function": {
            "name": "deprecate_domain",
            "description": "Remove a domain. Before calling, ensure all L2/L3 items have been migrated to other domains. Will fail if items still reference ONLY this domain.",
            "parameters": {"type": "object", "properties": {
                "domain": {"type": "string", "description": "Domain path to deprecate"},
                "reason": {"type": "string", "description": "Why this domain is being removed"},
            }, "required": ["domain", "reason"], "additionalProperties": False},
        },
    }, _wrap(_h_deprecate_domain), toolset="consolidation", sync=True)

    tool_registry.register("merge_domain", {
        "type": "function", "function": {
            "name": "merge_domain",
            "description": "Merge source domain into target: moves all items, merges correlations, deprecates source. One-click operation — Agent only provides two domain names.",
            "parameters": {"type": "object", "properties": {
                "source": {"type": "string", "description": "Domain to merge FROM (will be removed)"},
                "target": {"type": "string", "description": "Domain to merge INTO (survives)"},
                "reason": {"type": "string", "description": "Why merging"},
            }, "required": ["source", "target", "reason"], "additionalProperties": False},
        },
    }, _wrap(_h_merge_domain), toolset="consolidation", sync=True)

    tool_registry.register("create_domain", {
        "type": "function", "function": {
            "name": "create_domain",
            "description": "Create a new domain. Must provide at least one L2 card or L3 skill as initial content — empty domains are not allowed.",
            "parameters": {"type": "object", "properties": {
                "path": {"type": "string", "description": "Domain path, e.g. 'interaction'"},
                "parent": {"type": "string", "description": "Parent domain. Default: 'general'."},
                "description": {"type": "string", "description": "Brief description (1-2 sentences)"},
                "relations": {"type": "string", "description": "Related domains or notes. Optional."},
                "initial_cards": {
                    "type": "array", "items": {
                        "type": "object", "properties": {
                            "content": {"type": "string"},
                        }, "required": ["content"]
                    },
                    "description": "Initial L2 knowledge cards for this domain"
                },
                "initial_skills": {
                    "type": "array", "items": {
                        "type": "object", "properties": {
                            "name": {"type": "string"},
                            "content": {"type": "string"},
                        }, "required": ["name", "content"]
                    },
                    "description": "Initial L3 skills for this domain"
                },
            }, "required": ["path", "description"], "additionalProperties": False},
        },
    }, _wrap(_h_create_domain), toolset="consolidation", sync=True, override=True)


# ── L1 Rule Handlers ──

def _h_deprecate_l1_rule(args=None, ctx=None, **kwargs):
    args = args or {}
    ctx.record_mod({
        "type": "deprecate", "target": args.get("rule_id", ""),
        "reason": args.get("reason", ""), "layer": "l1",
    })
    return json.dumps({"recorded": True, "message": f"已记录: 删除 {args.get('rule_id', '')}"})


def _h_create_l1_rule(args=None, ctx=None, **kwargs):
    args = args or {}
    ctx.record_mod({
        "type": "create", "target": "", "layer": "l1",
        "reason": args.get("reason", ""),
        "payload": {"content": args.get("content", "")},
    })
    return json.dumps({"recorded": True, "message": "已记录: 创建新规则"})


def _h_modify_l1_rule(args=None, ctx=None, **kwargs):
    args = args or {}
    payload = {"content": args.get("content", "")}
    if "usefulness" in args:
        payload["usefulness"] = args["usefulness"]
    if "misleading" in args:
        payload["misleading"] = args["misleading"]
    if "comment" in args:
        payload["comment"] = args["comment"]
    ctx.record_mod({
        "type": "update", "target": args.get("rule_id", ""), "layer": "l1",
        "reason": args.get("reason", ""), "payload": payload,
    })
    return json.dumps({"recorded": True, "message": f"已记录: 修改 {args.get('rule_id', '')}"})


# ── L2 Card Handlers ──

def _h_deprecate_l2_card(args=None, ctx=None, **kwargs):
    args = args or {}
    ctx.record_mod({
        "type": "deprecate", "target": args.get("card_id", ""),
        "reason": args.get("reason", ""), "layer": "l2",
    })
    return json.dumps({"recorded": True, "message": f"已记录: 删除 {args.get('card_id', '')}"})


def _h_create_l2_card(args=None, ctx=None, **kwargs):
    args = args or {}
    ctx.record_mod({
        "type": "create", "target": "", "layer": "l2",
        "reason": args.get("reason", ""),
        "payload": {
            "content": args.get("content", ""),
            "domain": args.get("domain", "general"),
        },
    })
    return json.dumps({"recorded": True, "message": "已记录: 创建新卡片"})


def _h_modify_l2_card(args=None, ctx=None, **kwargs):
    args = args or {}
    payload = {"content": args.get("content", "")}
    if "domain" in args and args["domain"]:
        payload["domain"] = args["domain"]
    if "usefulness" in args:
        payload["usefulness"] = args["usefulness"]
    if "misleading" in args:
        payload["misleading"] = args["misleading"]
    if "comment" in args:
        payload["comment"] = args["comment"]
    ctx.record_mod({
        "type": "update", "target": args.get("card_id", ""), "layer": "l2",
        "reason": args.get("reason", ""), "payload": payload,
    })
    return json.dumps({"recorded": True, "message": f"已记录: 修改 {args.get('card_id', '')}"})


# ── L3 Skill Handlers ──

def _h_deprecate_l3_skill(args=None, ctx=None, **kwargs):
    args = args or {}
    ctx.record_mod({
        "type": "deprecate", "target": args.get("skill_name", ""),
        "reason": args.get("reason", ""), "layer": "l3",
    })
    return json.dumps({"recorded": True, "message": f"已记录: 删除 {args.get('skill_name', '')}"})


def _h_create_l3_skill(args=None, ctx=None, **kwargs):
    args = args or {}
    ctx.record_mod({
        "type": "create", "target": args.get("name", ""), "layer": "l3",
        "reason": args.get("reason", ""),
        "payload": {
            "content": args.get("content", ""),
            "domain": args.get("domain", "general"),
        },
    })
    return json.dumps({"recorded": True, "message": f"已记录: 创建 {args.get('name', '')}"})


def _h_modify_l3_skill(args=None, ctx=None, **kwargs):
    args = args or {}
    payload = {"content": args.get("content", "")}
    if "domain" in args and args["domain"]:
        payload["domain"] = args["domain"]
    if "usefulness" in args:
        payload["usefulness"] = args["usefulness"]
    if "misleading" in args:
        payload["misleading"] = args["misleading"]
    if "comment" in args:
        payload["comment"] = args["comment"]
    ctx.record_mod({
        "type": "update", "target": args.get("skill_name", ""), "layer": "l3",
        "reason": args.get("reason", ""), "payload": payload,
    })
    return json.dumps({"recorded": True, "message": f"已记录: 修改 {args.get('skill_name', '')}"})


# ── Domain Handlers ──

def _content_getter(layer, domain, ctx=None):
    if layer == "l2" and ctx and ctx.knowledge:
        return [c.content for c in ctx.knowledge.cards
                if domain in c.available_domains]
    if layer == "l3" and ctx and ctx.skill_layer:
        return [m.description for n, m in ctx.skill_layer._skills.items()
                if domain in m.available_domains]
    return []


def _h_query_domain(args=None, ctx=None, **kwargs):
    args = args or {}
    domain = args.get("domain", "")
    if ctx is None or ctx.domain_registry is None:
        return json.dumps({"error": "DomainRegistry not connected"})
    registry = ctx.domain_registry
    knowledge = ctx.knowledge
    skill_layer = ctx.skill_layer
    l2_ids = set(registry.get_primary_items("l2", domain))
    l3_ids = set(registry.get_primary_items("l3", domain))
    cards = []
    if knowledge:
        for c in knowledge.cards:
            if c.id in l2_ids:
                cards.append({"id": c.id, "content": c.content[:150],
                               "usefulness": c.usefulness,
                               "last_used": str(c.last_used.isoformat())[:10]})
    skills = []
    if skill_layer:
        for name, m in skill_layer._skills.items():
            if name in l3_ids:
                skills.append({"name": name, "description": m.description[:150],
                                "usefulness": m.usefulness,
                                "last_used": str(m.last_used.isoformat())[:10]})
    return json.dumps({"domain": domain, "l2_cards": cards, "l3_skills": skills},
                       ensure_ascii=False, default=str)


def _h_deprecate_domain(args=None, ctx=None, **kwargs):
    args = args or {}
    domain = args.get("domain", "")
    if ctx is None or ctx.domain_registry is None:
        return json.dumps({"error": "DomainRegistry not connected"})
    try:
        ctx.domain_registry.deprecate_domain(domain)
        return json.dumps({"success": True, "message": f"Domain '{domain}' removed"})
    except ValueError as e:
        return json.dumps({"error": str(e)})


def _h_merge_domain(args=None, ctx=None, **kwargs):
    args = args or {}
    source = args.get("source", "")
    target = args.get("target", "")
    if ctx is None or ctx.domain_registry is None:
        return json.dumps({"error": "DomainRegistry not connected"})
    try:
        g = lambda layer, domain: _content_getter(layer, domain, ctx)
        result = ctx.domain_registry.merge_domain(source, target, content_getter=g)
        return json.dumps({"success": True,
                           "message": f"Merged '{source}' → '{target}', {result['moved_items']} items moved"})
    except ValueError as e:
        return json.dumps({"error": str(e)})


def _h_create_domain(args=None, ctx=None, **kwargs):
    args = args or {}
    path = args.get("path", "")
    parent = args.get("parent", "general")
    description = args.get("description", "")
    relations = args.get("relations", "")
    initial_cards = args.get("initial_cards", [])
    initial_skills = args.get("initial_skills", [])
    if ctx is None or ctx.domain_registry is None:
        return json.dumps({"error": "DomainRegistry not connected"})
    registry = ctx.domain_registry
    knowledge = ctx.knowledge
    skill_layer = ctx.skill_layer
    if not path or not description:
        return json.dumps({"error": "path and description are required"})
    if not initial_cards and not initial_skills:
        return json.dumps({"error": "Domain must have at least one initial card or skill. Empty domains are not allowed."})
    try:
        registry.add_node(path, parent, description, {}, relations)
        created_cards = 0
        if knowledge:
            from core.task import Domain
            for card_data in initial_cards:
                knowledge.add_card(
                    content=card_data["content"],
                    domain=Domain(path, "specific"),
                    source="learning_env",
                )
                created_cards += 1
        created_skills = 0
        if skill_layer:
            from core.task import Domain
            for skill_data in initial_skills:
                skill_layer.create_skill(
                    name=skill_data["name"],
                    content=skill_data["content"],
                    domain=Domain(path, "specific"),
                    created_by="learning_env",
                )
                created_skills += 1
        g = lambda layer, domain: _content_getter(layer, domain, ctx)
        registry.compute_embedding(path, content_getter=g)
        return json.dumps({
            "success": True,
            "message": f"Domain '{path}' created under '{parent}'. Cards: {created_cards}, Skills: {created_skills}",
        }, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)})
