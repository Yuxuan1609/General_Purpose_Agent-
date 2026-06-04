from __future__ import annotations
import logging
from pathlib import Path
from core.config import AgentConfig
from core.task import LearningUnit, Domain
from core.tools.registry import ToolRegistry
from core.skill_layer import SkillLayer
from core.flexible_knowledge import FlexibleKnowledge
from core.philosophy import Philosophy
from core.meta_driver import MetaDriver, DEFAULT_TRIGGERS, DEFAULT_VALIDATORS
from core.layer_context import LayerContext
from core.agent_loop import AgentLoop

# Register remaining core tools
from core.tools.todo_tool import register_todo_tool
from core.tools.terminal_tool import register_terminal_tool
from core.tools.web_search_tool import register_web_search_tool

logger = logging.getLogger(__name__)


class CognitiveAgent:
    """Minimal cognitive agent aggregating 4 layers + event loop."""

    def __init__(self, config: AgentConfig):
        self.config = config
        self.tool_registry = ToolRegistry()

        self.l3 = SkillLayer(config.skills_dir, self.tool_registry)
        self.l2 = FlexibleKnowledge(config.knowledge_dir, config.l2_index_path)
        self.l1 = Philosophy(config.l1_rules_path, max_rules=config.l1_max_rules, max_rule_length=config.l1_max_rule_length)
        self.meta = MetaDriver(triggers=DEFAULT_TRIGGERS, validation_rules=DEFAULT_VALIDATORS, auxiliary_llm=config.auxiliary_llm, max_rules=config.l1_max_rules, max_rule_length=config.l1_max_rule_length)
        self.layers = LayerContext(self.meta, self.l1, self.l2, self.l3)
        self.loop = AgentLoop(llm_client=config.main_llm, tool_registry=self.tool_registry, layers=self.layers, max_iterations=config.max_iterations)

        register_todo_tool(self.tool_registry)
        register_terminal_tool(self.tool_registry)
        register_web_search_tool(self.tool_registry)

        self._bootstrap(config)

    def run(self, user_input: str, domain: Domain | None = None) -> any:
        task = LearningUnit(description=user_input, domain=domain or Domain("general", "general"))
        messages, raw_result = self.loop.run(task)
        return self.loop.reflect(task, messages, raw_result)

    def _bootstrap(self, config: AgentConfig):
        if config.seed_l1_rules:
            for rule_text in config.seed_l1_rules:
                try:
                    self.l1.add_rule(rule_text, created_by="seed")
                except ValueError:
                    pass
        if config.seed_l2_cards:
            for card_data in config.seed_l2_cards:
                self.l2.add_card(content=card_data["content"], domain=Domain(card_data.get("domain", "general"), "general"), confidence=card_data.get("confidence", 0.7), source=card_data.get("source", "seed"))
        if config.seed_l3_skills:
            for skill_path in config.seed_l3_skills:
                self.l3.import_skill(skill_path)

    def inspect_l1(self) -> list:
        return self.l1.all_rules()

    def inspect_l2(self, domain: Domain) -> list:
        return self.l2.get_domain_cards(domain)

    def inspect_l3(self) -> list:
        return self.l3.list_all()
