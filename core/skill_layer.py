from __future__ import annotations
import json
import logging
import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

L3_CREATION_THRESHOLD_CARDS = 3
L3_CREATION_THRESHOLD_ACTIVATION = 0.7


@dataclass
class SkillMeta:
    name: str
    description: str
    domain: "Domain"
    available_domains: list[str] = field(default_factory=list)
    cross_domain: bool = False
    version: str = "1.0.0"
    created_by: str = "agent"
    source_cards: list[str] = field(default_factory=list)
    skill_dir: Path | None = None
    usefulness: int = 0
    misleading: int = 0
    comment: str = ""


class SkillLayer:
    """L3: Semi-static skills. SKILL.md format (compatible with agentskills.io)."""

    def __init__(self, skills_dir: Path, tool_registry, domain_registry=None):
        from core.task import Domain
        self.skills_dir = Path(skills_dir)
        self.skills_dir.mkdir(parents=True, exist_ok=True)
        self._registry = domain_registry
        self._skills: dict[str, SkillMeta] = {}
        self._register_tools(tool_registry)

    def list_all(self) -> list[SkillMeta]:
        metas = []
        for skill_file in self.skills_dir.rglob("SKILL.md"):
            if ".archive" in skill_file.parts:
                continue
            try:
                meta = self._parse_skill_meta(skill_file)
                if meta:
                    metas.append(meta)
            except Exception:
                logger.debug("Failed to parse %s", skill_file, exc_info=True)
        return metas

    def match(self, task_domain) -> list[SkillMeta]:
        if self._registry:
            ids = self._registry.get_primary_items("l3", task_domain.path)
            return [self._skills[n] for n in ids if n in self._skills]
        from core.task import Domain
        all_skills = self.list_all()
        scored = []
        for s in all_skills:
            if s.domain.path == task_domain.path:
                scored.append((3, s))
            elif task_domain.parent and s.domain.path == task_domain.parent.path:
                scored.append((2, s))
            elif s.cross_domain and s.domain.is_general:
                scored.append((1, s))
            elif s.domain.path == task_domain.path.split("/")[0]:
                scored.append((1, s))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [s for _, s in scored]

    def create_skill(self, name: str, content: str, domain,
                     cross_domain: bool = False, created_by: str = "agent",
                     available_domains: list[str] | None = None) -> SkillMeta:
        from core.task import Domain
        if not re.match(r'^[\w][\w._-]*$', name):
            raise ValueError(f"Invalid skill name: {name}")
        if len(name) > 64:
            raise ValueError(f"Skill name too long: {len(name)} > 64")
        if available_domains is None:
            available_domains = [domain.path]
        if domain.is_general:
            skill_dir = self.skills_dir / "general" / name
        else:
            skill_dir = self.skills_dir / domain.path / name
        skill_dir.mkdir(parents=True, exist_ok=True)
        skill_file = skill_dir / "SKILL.md"
        fd, tmp_path = tempfile.mkstemp(dir=skill_dir, suffix=".md")
        try:
            with open(fd, "w", encoding="utf-8") as f:
                f.write(content)
            Path(tmp_path).replace(skill_file)
        finally:
            Path(tmp_path).unlink(missing_ok=True)
        # Extract metadata from YAML frontmatter to allow content-driven overrides
        fm_cross_domain = self._extract_bool_from_frontmatter(content, "cross_domain")
        meta = SkillMeta(
            name=name,
            description=self._extract_description(content),
            domain=domain,
            available_domains=available_domains,
            cross_domain=cross_domain if cross_domain else fm_cross_domain,
            created_by=created_by,
            skill_dir=skill_dir,
        )
        self._skills[name] = meta
        if self._registry:
            for d in meta.available_domains:
                self._registry.index_item("l3", d, name)
        return meta

    def get_skills_by_ids(self, ids: list[str]) -> list[dict]:
        result = []
        for name in ids:
            skill = self._skills.get(name)
            if skill is None:
                continue
            content = ""
            if skill.skill_dir:
                skf = skill.skill_dir / "SKILL.md"
                if skf.exists():
                    content = skf.read_text(encoding="utf-8")
            result.append({
                "name": skill.name,
                "description": skill.description,
                "domain": skill.domain.path,
                "content": content,
            })
        return result

    def edit_skill(self, name: str, new_content: str) -> SkillMeta:
        skill_dir = self._find_skill_dir(name)
        if not skill_dir:
            raise ValueError(f"Skill not found: {name}")
        skill_file = skill_dir / "SKILL.md"
        fd, tmp_path = tempfile.mkstemp(dir=skill_dir, suffix=".md")
        try:
            with open(fd, "w", encoding="utf-8") as f:
                f.write(new_content)
            Path(tmp_path).replace(skill_file)
        finally:
            Path(tmp_path).unlink(missing_ok=True)
        return self._parse_skill_meta(skill_file)

    def patch_skill(self, name: str, find: str, replace: str) -> SkillMeta:
        skill_dir = self._find_skill_dir(name)
        if not skill_dir:
            raise ValueError(f"Skill not found: {name}")
        skill_file = skill_dir / "SKILL.md"
        content = skill_file.read_text(encoding="utf-8")
        if find not in content:
            raise ValueError(f"Find text not found in {name}")
        new_content = content.replace(find, replace, 1)
        return self.edit_skill(name, new_content)

    def delete_skill(self, name: str) -> None:
        skill_dir = self._find_skill_dir(name)
        if not skill_dir:
            raise ValueError(f"Skill not found: {name}")
        archive_dir = self.skills_dir / ".archive"
        archive_dir.mkdir(exist_ok=True)
        skill_dir.rename(archive_dir / name)

    def should_create_skill(self, domain, domain_cards: list) -> bool:
        cards = [c for c in domain_cards if c.domain.path == domain.path]
        if len(cards) < L3_CREATION_THRESHOLD_CARDS:
            return False
        avg = sum(c.activation for c in cards) / len(cards)
        return avg > L3_CREATION_THRESHOLD_ACTIVATION

    def propose_and_create(self, domain, cards: list, llm_client=None) -> SkillMeta | None:
        if llm_client is None:
            return None
        cards_text = "\n\n".join(
            f"- [{c.id}] (confidence:{c.confidence:.1f}, activation:{c.activation:.2f}) {c.content}"
            for c in cards if c.domain.path == domain.path
        )
        prompt = (
            f"Create a SKILL.md for domain '{domain.path}' from these knowledge cards:\n\n"
            f"{cards_text}\n\n"
            f"Generate YAML frontmatter + markdown body. Include name, description, "
            f"domain, and a numbered procedure. Format exactly:\n"
            f"---\nname: skill-name\ndescription: \"...\"\ndomain: {domain.path}\n"
            f"cross_domain: false\nversion: 1.0.0\n---\n# Title\n\n## Procedure\n1. ..."
        )
        try:
            resp = llm_client.chat(messages=[{"role": "user", "content": prompt}])
            content = resp.text if hasattr(resp, 'text') else str(resp)
            meta = self.create_skill(
                f"{domain.path.replace('/', '-')}-compiled",
                content, domain, created_by="l2_compilation",
            )
            meta.source_cards = [c.id for c in cards if c.domain.path == domain.path]
            return meta
        except Exception as e:
            logger.warning("L2→L3 compilation failed: %s", e)
            return None

    def import_skill(self, skill_path: Path) -> SkillMeta | None:
        skill_path = Path(skill_path)
        if not skill_path.exists():
            return None
        content = skill_path.read_text(encoding="utf-8")
        meta = self._parse_skill_meta(skill_path)
        if meta is None:
            return None
        return self.create_skill(meta.name, content, meta.domain, meta.cross_domain, "seed")

    def _parse_skill_meta(self, skill_file: Path) -> SkillMeta | None:
        from core.task import Domain
        content = skill_file.read_text(encoding="utf-8")
        if not content.startswith("---"):
            return None
        parts = content.split("---", 2)
        if len(parts) < 3:
            return None
        try:
            fm = yaml.safe_load(parts[1])
        except yaml.YAMLError:
            return None
        if not isinstance(fm, dict):
            return None
        domain_path = fm.get("domain", "general")
        domain_level = "general" if domain_path == "general" else "specific"
        return SkillMeta(
            name=fm.get("name", skill_file.parent.name),
            description=fm.get("description", ""),
            domain=Domain(domain_path, domain_level),
            cross_domain=fm.get("cross_domain", False),
            version=str(fm.get("version", "1.0.0")),
            created_by=str(fm.get("created_by", "agent")),
            source_cards=fm.get("source_cards", []),
            skill_dir=skill_file.parent,
        )

    def _extract_bool_from_frontmatter(self, content: str, key: str) -> bool:
        if not content.startswith("---"):
            return False
        parts = content.split("---", 2)
        if len(parts) < 3:
            return False
        try:
            fm = yaml.safe_load(parts[1])
            return bool(fm.get(key, False)) if isinstance(fm, dict) else False
        except yaml.YAMLError:
            return False

    def _extract_description(self, content: str) -> str:
        if not content.startswith("---"):
            return ""
        parts = content.split("---", 2)
        if len(parts) < 3:
            return ""
        try:
            fm = yaml.safe_load(parts[1])
            return str(fm.get("description", "")) if isinstance(fm, dict) else ""
        except yaml.YAMLError:
            return ""

    def _find_skill_dir(self, name: str) -> Path | None:
        for skill_file in self.skills_dir.rglob("SKILL.md"):
            if ".archive" in skill_file.parts:
                continue
            if skill_file.parent.name == name:
                return skill_file.parent
        return None

    def _register_tools(self, registry):
        layer = self

        def _skills_list(args=None, context=None):
            category = (args or {}).get("category", "")
            skills = layer.list_all()
            if category:
                skills = [s for s in skills if category in s.domain.path]
            return json.dumps([
                {"name": s.name, "description": s.description, "domain": s.domain.path}
                for s in skills
            ], ensure_ascii=False)

        def _skill_view(args=None, context=None):
            name = (args or {}).get("name", "")
            skill_dir = layer._find_skill_dir(name)
            if not skill_dir:
                return json.dumps({"error": f"Skill '{name}' not found"})
            content = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
            return json.dumps({"success": True, "name": name, "content": content}, ensure_ascii=False)

        def _skill_manage(args=None, context=None):
            action = (args or {}).get("action", "")
            skill_name = (args or {}).get("name", "")
            content = (args or {}).get("content", "")
            domain_path = (args or {}).get("domain", "general")
            find_text = (args or {}).get("find", "")
            replace_text = (args or {}).get("replace", "")
            from core.task import Domain
            domain = Domain(domain_path, "general" if domain_path == "general" else "specific")
            try:
                if action == "create":
                    meta = layer.create_skill(skill_name, content, domain)
                    return json.dumps({"success": True, "name": meta.name})
                elif action == "edit":
                    meta = layer.edit_skill(skill_name, content)
                    return json.dumps({"success": True, "name": meta.name})
                elif action == "patch":
                    meta = layer.patch_skill(skill_name, find_text, replace_text)
                    return json.dumps({"success": True, "name": meta.name})
                elif action == "delete":
                    layer.delete_skill(skill_name)
                    return json.dumps({"success": True})
                else:
                    return json.dumps({"error": f"Unknown action: {action}"})
            except Exception as e:
                return json.dumps({"error": str(e)})

        registry.register("skills_list", {
            "type": "function",
            "function": {
                "name": "skills_list",
                "description": "List available skills with metadata",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "category": {"type": "string", "description": "Filter by domain/category"}
                    }
                }
            }
        }, _skills_list, toolset="core")

        registry.register("skill_view", {
            "type": "function",
            "function": {
                "name": "skill_view",
                "description": "Load full skill content by name",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "Skill name"}
                    },
                    "required": ["name"]
                }
            }
        }, _skill_view, toolset="core")

        registry.register("skill_manage", {
            "type": "function",
            "function": {
                "name": "skill_manage",
                "description": "Create, edit, patch, or delete a skill",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "enum": ["create", "edit", "patch", "delete"]},
                        "name": {"type": "string"},
                        "content": {"type": "string"},
                        "domain": {"type": "string"},
                        "find": {"type": "string"},
                        "replace": {"type": "string"},
                    },
                    "required": ["action", "name"]
                }
            }
        }, _skill_manage, toolset="core")
