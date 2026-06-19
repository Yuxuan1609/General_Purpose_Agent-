"""Consolidation tools — registered in ToolRegistry, filtered by AgentContext.

Handlers directly modify stores (no pending_mods side-channel). Domain index
operations (index_item/update_item_domains/mark_domain_dirty) handled here.
Store legality validation is in store methods (Philosophy.add_rule etc).
"""
from __future__ import annotations
from dataclasses import dataclass, field
import json
import logging

logger = logging.getLogger(__name__)


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


def register_consolidation_tools(tool_registry, ctx=None):
    """Register consolidation tools. ctx param kept for backward compat but ignored."""
    _specs = {s.tool_name: s for s in _MOD_SPECS}

    tool_registry.register("deprecate_l1_rule", {
        "type": "function", "function": {
            "name": "deprecate_l1_rule",
            "description": "废弃（删除）一条 L1 行为准则。用于移除重复、低质量或违反跨领域原则的规则。",
            "parameters": {"type": "object", "properties": {
                "rule_id": {"type": "string", "description": "要删除的规则 id，如 l1_001"},
                "reason": {"type": "string", "description": "删除理由，如'与另一条重复'或'内容模糊'"},
            }, "required": ["rule_id", "reason"], "additionalProperties": False},
        },
    }, _make_handler(_specs["deprecate_l1_rule"]), toolset="consolidation", sync=True)

    tool_registry.register("create_l1_rule", {
        "type": "function", "function": {
            "name": "create_l1_rule",
            "description": "创建一条新的 L1 行为准则。用于合并重复规则或添加新的通用原则。",
            "parameters": {"type": "object", "properties": {
                "content": {"type": "string", "description": "完整规则文本，1-2句清晰可执行的行为准则"},
                "reason": {"type": "string", "description": "创建理由，如'合并了3条概率决策规则'"},
            }, "required": ["content", "reason"], "additionalProperties": False},
        },
    }, _make_handler(_specs["create_l1_rule"]), toolset="consolidation", sync=True)

    tool_registry.register("modify_l1_rule", {
        "type": "function", "function": {
            "name": "modify_l1_rule",
            "description": "修改一条现有 L1 规则的文本内容。",
            "parameters": {"type": "object", "properties": {
                "rule_id": {"type": "string", "description": "Rule id to modify, e.g. l1_001"},
                "content": {"type": "string", "description": "完整修改后的规则文本。"},
                "reason": {"type": "string", "description": "修改理由"},
            }, "required": ["rule_id", "reason"], "additionalProperties": False},
        },
    }, _make_handler(_specs["modify_l1_rule"]), toolset="consolidation", sync=True)

    tool_registry.register("deprecate_l2_card", {
        "type": "function", "function": {
            "name": "deprecate_l2_card",
            "description": "废弃（删除）一张 L2 知识卡片。用于移除低置信度、从未使用或高度冗余的策略卡片。",
            "parameters": {"type": "object", "properties": {
                "card_id": {"type": "string", "description": "卡片 id，如 card_xxxxxxxx"},
                "reason": {"type": "string", "description": "删除理由，如'合并到 leduc_K_preflop'或'低置信度从未使用'"},
            }, "required": ["card_id", "reason"], "additionalProperties": False},
        },
    }, _make_handler(_specs["deprecate_l2_card"]), toolset="consolidation", sync=True)

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
    }, _make_handler(_specs["create_l2_card"]), toolset="consolidation", sync=True)

    tool_registry.register("modify_l2_card", {
        "type": "function", "function": {
            "name": "modify_l2_card",
            "description": "Modify an existing L2 card. Use content to update card text, domain to change domain assignment, or pass quality fields for feedback.\n\nQuality fields (both range -5 to +5):\n  usefulness: +5=critical help, ... \n  misleading: +5=severely misleading, ...\n  comment: natural language quality note, max 100 chars.",
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
    }, _make_handler(_specs["modify_l2_card"]), toolset="consolidation", sync=True)

    tool_registry.register("deprecate_l3_skill", {
        "type": "function", "function": {
            "name": "deprecate_l3_skill",
            "description": "废弃（删除）一个 L3 技能。用于移除低质量、从未使用或功能重叠的技能。",
            "parameters": {"type": "object", "properties": {
                "skill_name": {"type": "string", "description": "技能名称，如 leduc-bad-1"},
                "reason": {"type": "string", "description": "删除理由，如'低质量从未被匹配'或'与另一技能功能重叠'"},
            }, "required": ["skill_name", "reason"], "additionalProperties": False},
        },
    }, _make_handler(_specs["deprecate_l3_skill"]), toolset="consolidation", sync=True)

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
    }, _make_handler(_specs["create_l3_skill"]), toolset="consolidation", sync=True)

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
    }, _make_handler(_specs["modify_l3_skill"]), toolset="consolidation", sync=True)

    tool_registry.register("query_domain", {
        "type": "function", "function": {
            "name": "query_domain",
            "description": "List all L2 cards and L3 skills in a domain. Use to inspect domain contents before splitting or merging.",
            "parameters": {"type": "object", "properties": {
                "domain": {"type": "string", "description": "Domain path to query, e.g. 'game/doudizhu'"},
            }, "required": ["domain"], "additionalProperties": False},
        },
    }, _h_query_domain, toolset="consolidation", sync=True)

    tool_registry.register("deprecate_domain", {
        "type": "function", "function": {
            "name": "deprecate_domain",
            "description": "Remove a domain. Before calling, ensure all L2/L3 items have been migrated to other domains. Will fail if items still reference ONLY this domain.",
            "parameters": {"type": "object", "properties": {
                "domain": {"type": "string", "description": "Domain path to deprecate"},
                "reason": {"type": "string", "description": "Why this domain is being removed"},
            }, "required": ["domain", "reason"], "additionalProperties": False},
        },
    }, _h_deprecate_domain, toolset="consolidation", sync=True)

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
    }, _h_merge_domain, toolset="consolidation", sync=True)

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
    }, _h_create_domain, toolset="consolidation", sync=True, override=True)


# ── Handler factory for declarative CRUD tools — direct store modification ──

@dataclass
class _ModSpec:
    """Declarative spec for a consolidation CRUD handler."""
    tool_name: str
    mod_type: str
    layer: str
    target_arg: str
    payload_args: list[str] = field(default_factory=list)
    message_template: str = ""


_MOD_SPECS: list[_ModSpec] = [
    _ModSpec("deprecate_l1_rule", "deprecate", "l1", "rule_id",
             message_template="已删除: {target}"),
    _ModSpec("create_l1_rule", "create", "l1", "",
             payload_args=["content"], message_template="已创建: 新规则"),
    _ModSpec("modify_l1_rule", "update", "l1", "rule_id",
             payload_args=["content"], message_template="已修改: {target}"),
    _ModSpec("deprecate_l2_card", "deprecate", "l2", "card_id",
             message_template="已删除: {target}"),
    _ModSpec("create_l2_card", "create", "l2", "",
             payload_args=["content", "domain"], message_template="已创建: 新卡片"),
    _ModSpec("modify_l2_card", "update", "l2", "card_id",
             payload_args=["content", "domain", "usefulness", "misleading", "comment"],
             message_template="已修改: {target}"),
    _ModSpec("deprecate_l3_skill", "deprecate", "l3", "skill_name",
             message_template="已删除: {target}"),
    _ModSpec("create_l3_skill", "create", "l3", "name",
             payload_args=["content", "domain"], message_template="已创建: {target}"),
    _ModSpec("modify_l3_skill", "update", "l3", "skill_name",
             payload_args=["content", "domain", "usefulness", "misleading", "comment"],
             message_template="已修改: {target}"),
]


def _make_handler(spec: _ModSpec):
    """Generate a consolidation handler that directly modifies the store."""
    def handler(args=None, **kwargs):
        from core.tools.consolidation_injection import get_store, get_registry
        args = args or {}
        target = args.get(spec.target_arg, "") if spec.target_arg else ""
        store = get_store(spec.layer)
        if store is None:
            return json.dumps({"error": f"{spec.layer} store not available"})
        registry = get_registry()

        try:
            if spec.mod_type == "create":
                _do_create(store, spec.layer, args)
            elif spec.mod_type == "update":
                _do_update(store, spec.layer, target, args, registry)
            elif spec.mod_type == "deprecate":
                _do_deprecate(store, spec.layer, target, args, registry)
            msg = spec.message_template.format(target=target)
            return json.dumps({"success": True, "message": msg})
        except Exception as e:
            logger.warning("consolidation %s failed: %s", spec.tool_name, e)
            return json.dumps({"error": str(e)})
    return handler


def _do_create(store, layer, args):
    content = args.get("content", "")
    domain = args.get("domain", "general")
    if layer == "l1":
        store.add_rule(content, created_by="agent", source="l1")
    elif layer == "l2":
        from core.task import Domain
        store.add_card(content=content, domain=Domain(domain, "specific"),
                       source="agent")
        registry = __import__("core.tools.consolidation_injection", fromlist=["get_registry"]).get_registry()
        if registry:
            registry.mark_domain_dirty(domain)
    elif layer == "l3":
        from core.task import Domain
        name = args.get("name", "")
        store.create_skill(name=name, content=content,
                           domain=Domain(domain, "specific"),
                           created_by="agent")
        registry = __import__("core.tools.consolidation_injection", fromlist=["get_registry"]).get_registry()
        if registry:
            registry.mark_domain_dirty(domain)


def _do_update(store, layer, target, args, registry):
    content = args.get("content")
    new_domain = args.get("domain")
    if layer == "l1":
        store.modify_rule(target, content)
    elif layer == "l2":
        quality = _extract_quality(args)
        result = store.modify_card(target, content, **quality)
        if result is None:
            raise ValueError(f"Card not found: {target}")
        if new_domain and new_domain != result.domain.path:
            _change_domain(registry, "l2", target, result, new_domain)
    elif layer == "l3":
        quality = _extract_quality(args)
        store.edit_skill(target, content, **quality)
        if new_domain:
            meta = store._skills.get(target)
            if meta is None:
                raise ValueError(f"Skill not found: {target}")
            if new_domain != meta.domain.path:
                _change_domain(registry, "l3", target, meta, new_domain)


def _do_deprecate(store, layer, target, args, registry):
    if layer == "l1":
        store.remove_rule(target)
    elif layer == "l2":
        if not store.remove_card(target):
            raise ValueError(f"Card not found: {target}")
        if registry:
            for d in (store.cards if hasattr(store, 'cards') else []):
                pass
    elif layer == "l3":
        store.delete_skill(target)


def _extract_quality(args):
    quality = {}
    for key in ("usefulness", "misleading", "comment"):
        val = args.get(key)
        if val is not None and val != "":
            quality[key] = val
    return quality


def _change_domain(registry, layer, item_id, item_obj, new_domain):
    if registry is None:
        return
    if registry.get_node(new_domain) is None:
        raise ValueError(f"Domain not found in registry: {new_domain}")
    from core.task import Domain
    old_domain = item_obj.domain.path
    item_obj.domain = Domain(new_domain, "specific")
    item_obj.available_domains = [new_domain]
    registry.update_item_domains(layer, item_id, [new_domain])
    registry.mark_domain_dirty(new_domain)
    registry.mark_domain_dirty(old_domain)


# ── Domain Handlers ──

def _content_getter(layer, domain):
    from core.tools.consolidation_injection import get_store
    if layer == "l2":
        knowledge = get_store("l2")
        if knowledge:
            return [c.content for c in knowledge.cards
                    if domain in c.available_domains]
    if layer == "l3":
        skill_layer = get_store("l3")
        if skill_layer:
            return [m.description for n, m in skill_layer._skills.items()
                    if domain in m.available_domains]
    return []


def _h_query_domain(args=None, **kwargs):
    from core.tools.consolidation_injection import get_registry, get_store
    args = args or {}
    domain = args.get("domain", "")
    registry = get_registry()
    if registry is None:
        return json.dumps({"error": "DomainRegistry not connected"})
    knowledge = get_store("l2")
    skill_layer = get_store("l3")
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


def _h_deprecate_domain(args=None, **kwargs):
    from core.tools.consolidation_injection import get_registry
    args = args or {}
    domain = args.get("domain", "")
    registry = get_registry()
    if registry is None:
        return json.dumps({"error": "DomainRegistry not connected"})
    try:
        registry.deprecate_domain(domain)
        return json.dumps({"success": True, "message": f"Domain '{domain}' removed"})
    except ValueError as e:
        return json.dumps({"error": str(e)})


def _h_merge_domain(args=None, **kwargs):
    from core.tools.consolidation_injection import get_registry
    args = args or {}
    source = args.get("source", "")
    target = args.get("target", "")
    registry = get_registry()
    if registry is None:
        return json.dumps({"error": "DomainRegistry not connected"})
    try:
        g = lambda layer, domain: _content_getter(layer, domain)
        result = registry.merge_domain(source, target, content_getter=g)
        registry.mark_domain_dirty(target)
        return json.dumps({"success": True,
                           "message": f"Merged '{source}' → '{target}', {result['moved_items']} items moved"})
    except ValueError as e:
        return json.dumps({"error": str(e)})


def _h_create_domain(args=None, **kwargs):
    from core.tools.consolidation_injection import get_registry, get_store
    args = args or {}
    path = args.get("path", "")
    parent = args.get("parent", "general")
    description = args.get("description", "")
    relations = args.get("relations", "")
    initial_cards = args.get("initial_cards", [])
    initial_skills = args.get("initial_skills", [])
    registry = get_registry()
    if registry is None:
        return json.dumps({"error": "DomainRegistry not connected"})
    knowledge = get_store("l2")
    skill_layer = get_store("l3")
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
        g = lambda layer, domain: _content_getter(layer, domain)
        registry.compute_embedding(path, content_getter=g)
        registry.mark_domain_dirty(path)
        return json.dumps({
            "success": True,
            "message": f"Domain '{path}' created under '{parent}'. Cards: {created_cards}, Skills: {created_skills}",
        }, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)})

