from __future__ import annotations
import json
import logging
import tempfile
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)


def _now():
    return datetime.now(timezone.utc).isoformat()


@dataclass
class Rule:
    id: str
    content: str
    created_by: str
    source: str = "l1"                # "l0_5" = immutable constitution, "l1" = mutable behavior
    added_at: str = field(default_factory=_now)
    version: int = 1
    last_modified: str = field(default_factory=_now)
    usefulness: int = 0
    misleading: int = 0
    comment: str = ""


@dataclass
class L1Proposal:
    content: str
    reason: str = ""
    rule_id: str | None = None
    domain: str = "general"


class Philosophy:
    """L1: Behavioral philosophy. Rules stored in JSON, injected into system prompt."""

    def __init__(self, rules_path: Path, max_rules: int = 20, max_rule_length: int = 100):
        self.rules_path = Path(rules_path)
        self.max_rules = max_rules
        self.max_rule_length = max_rule_length
        self._rules: list[Rule] = []
        self._load()

    def all_rules(self) -> list[Rule]:
        """Return all rules (L0.5 constitution + L1 mutable)."""
        return list(self._rules)

    def l1_rules(self) -> list[Rule]:
        """Return only L1 mutable rules (exclude L0.5 constitution).
        
        Used by verifier: reflection can only modify L1 rules.
        L0.5 rules are immutable constitution, only changeable manually by user.
        """
        return [r for r in self._rules if r.source != "l0_5"]

    def l0_5_rules(self) -> list[Rule]:
        """Return only L0.5 immutable constitution rules."""
        return [r for r in self._rules if r.source == "l0_5"]

    def get_active_rules(self, task) -> list[str]:
        return [r.content for r in self._rules]

    def add_rule(self, content: str, created_by: str = "reflection",
                 source: str = "l1") -> Rule:
        if len(content) > self.max_rule_length:
            raise ValueError(f"Rule too long: {len(content)} > {self.max_rule_length}")
        rule = Rule(
            id=f"l1_{uuid.uuid4().hex[:6]}",
            content=content,
            created_by=created_by,
            source=source,
        )
        self._rules.append(rule)
        self._save()
        return rule

    def modify_rule(self, rule_id: str, new_content: str) -> Rule:
        for i, r in enumerate(self._rules):
            if r.id == rule_id:
                if r.source == "l0_5":
                    raise ValueError(
                        f"Rule {rule_id} is L0.5 constitution (immutable). "
                        "Only manually modifiable by user."
                    )
                if len(new_content) > self.max_rule_length:
                    raise ValueError(f"Rule too long: {len(new_content)} > {self.max_rule_length}")
                updated = Rule(
                    id=r.id, content=new_content, created_by=r.created_by,
                    source=r.source,
                    added_at=r.added_at, version=r.version + 1, last_modified=_now(),
                )
                self._rules[i] = updated
                self._save()
                return updated
        raise ValueError(f"Rule not found: {rule_id}")

    def remove_rule(self, rule_id: str) -> None:
        for r in self._rules:
            if r.id == rule_id:
                if r.source == "l0_5":
                    raise ValueError(
                        f"Rule {rule_id} is L0.5 constitution (immutable). "
                        "Only manually removable by user."
                    )
                break
        self._rules = [r for r in self._rules if r.id != rule_id]
        self._save()

    def apply(self, proposal: L1Proposal) -> Rule:
        if proposal.rule_id:
            return self.modify_rule(proposal.rule_id, proposal.content)
        return self.add_rule(proposal.content, created_by="reflection")

    def _load(self):
        if self.rules_path.exists():
            try:
                data = json.loads(self.rules_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                data = {"version": 1, "rules": []}
        else:
            data = {"version": 1, "rules": []}
        self._rules = [
            Rule(
                id=r["id"], content=r["content"],
                created_by=r.get("created_by", "unknown"),
                source=r.get("source", "l1"),
                added_at=r.get("added_at", _now()),
                version=r.get("version", 1),
                last_modified=r.get("last_modified", _now()),
            )
            for r in data.get("rules", [])
        ]

    def _save(self):
        self.rules_path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "version": 1,
            "rules": [
                {
                    "id": r.id, "content": r.content, "created_by": r.created_by,
                    "source": r.source,
                    "added_at": r.added_at, "version": r.version, "last_modified": r.last_modified,
                }
                for r in self._rules
            ],
        }
        fd, tmp = tempfile.mkstemp(dir=self.rules_path.parent, suffix=".json")
        try:
            with open(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            Path(tmp).replace(self.rules_path)
        finally:
            Path(tmp).unlink(missing_ok=True)
