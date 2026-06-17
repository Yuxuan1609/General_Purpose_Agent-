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


def _check_not_duplicate(content: str, existing_rules: list) -> tuple[bool, str]:
    for r in existing_rules:
        if content.strip() == r.content.strip():
            return False, "新规则与已有规则完全重复"
    return True, ""


def _check_no_contradiction(content: str, existing_rules: list) -> tuple[bool, str]:
    negations = ["不要", "禁止", "避免", "别"]
    for r in existing_rules:
        rc = r.content
        for neg in negations:
            if neg in content and content.replace(neg, "") in rc:
                return False, f"新规则可能与已有规则矛盾 (涉及'{neg}')"
    return True, ""


class Philosophy:
    """L1: Behavioral philosophy. Rules stored in SQLite or JSON."""

    def __init__(self, rules_path: Path, max_rules: int | None = None,
                 max_rule_length: int | None = None,
                 db_path: Path | None = None):
        self.rules_path = Path(rules_path)
        from core.config_loader import get_section
        l1cfg = get_section('l1', default={})
        self.max_rules = max_rules if max_rules is not None else l1cfg.get('max_rules', 20)
        self.max_rule_length = max_rule_length if max_rule_length is not None else l1cfg.get('max_rule_length', 300)
        self._rules: list[Rule] = []
        self._db = None
        if db_path:
            from core.storage.l1_store import L1SQLiteStore
            self._db = L1SQLiteStore(db_path)
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

    def add_rule(self, content: str, created_by: str = "reflection",
                 source: str = "l1") -> Rule:
        if len(content) > self.max_rule_length:
            raise ValueError(f"Rule too long: {len(content)} > {self.max_rule_length}")
        self._validate_rule_change(content)
        rule = Rule(
            id=f"l1_{uuid.uuid4().hex[:6]}",
            content=content,
            created_by=created_by,
            source=source,
        )
        self._rules.append(rule)
        if self._db:
            self._db.insert({
                "id": rule.id,
                "content": rule.content,
                "created_by": rule.created_by,
                "source": rule.source,
                "added_at": rule.added_at,
                "version": rule.version,
                "last_modified": rule.last_modified,
            })
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
                self._validate_rule_change(new_content, skip_rule_id=rule_id)
                updated = Rule(
                    id=r.id, content=new_content, created_by=r.created_by,
                    source=r.source,
                    added_at=r.added_at, version=r.version + 1, last_modified=_now(),
                )
                self._rules[i] = updated
                if self._db:
                    self._db.update(rule_id, content=new_content, version=updated.version)
                self._save()
                return updated
        raise ValueError(f"Rule not found: {rule_id}")

    def _validate_rule_change(self, content: str, skip_rule_id: str | None = None) -> None:
        existing = [r for r in self._rules if r.id != skip_rule_id and r.source != "l0_5"]
        approved, reason = _check_not_duplicate(content, existing)
        if not approved:
            raise ValueError(f"[not_duplicate] {reason}")
        approved, reason = _check_no_contradiction(content, existing)
        if not approved:
            raise ValueError(f"[no_contradiction] {reason}")
        if len(self._rules) >= self.max_rules:
            raise ValueError(f"规则总数已达上限 {self.max_rules} 条")

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
        if self._db:
            self._db.delete(rule_id)
        self._save()

    def apply(self, proposal: L1Proposal) -> Rule:
        if proposal.rule_id:
            return self.modify_rule(proposal.rule_id, proposal.content)
        return self.add_rule(proposal.content, created_by="reflection")

    def _load(self):
        if self._db and self._db.count() > 0:
            self._load_from_db()
            return
        self._load_from_json()

    def _load_from_db(self):
        self._rules = [
            Rule(
                id=r["id"], content=r["content"],
                created_by=r.get("created_by", "unknown"),
                source=r.get("source", "l1"),
                added_at=r.get("added_at", _now()),
                version=r.get("version", 1),
                last_modified=r.get("last_modified", _now()),
                usefulness=r.get("usefulness", 0),
                misleading=r.get("misleading", 0),
                comment=r.get("comment", ""),
            )
            for r in self._db.list_all()
        ]

    def _load_from_json(self):
        if self.rules_path.exists():
            try:
                data = json.loads(self.rules_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError) as e:
                logger.error("Failed to load rules from %s: %s", self.rules_path, e)
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
        if self._db:
            return
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
