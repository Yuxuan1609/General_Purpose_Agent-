"""record_learning tool — Agent proposes learnable content, sub-agent fills details."""
from __future__ import annotations
import json, uuid, tempfile
from datetime import datetime, timezone
from pathlib import Path


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def register_record_learning(registry, pending_dir: str = "data/learning/pending"):
    registry.register("record_learning", {
        "type": "function",
        "function": {
            "name": "record_learning",
            "description": (
                "记录值得学习的内容（仅L1可用）。提供 domain + learning_target + importance + reasoning。"
                "L2/L3的详细evidence由后台自动补充后写入pending文件夹。默认异步(sync=false)，返回task_id。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "domain": {"type": "string", "description": "学习域，如'interaction'"},
                    "learning_target": {"type": "string", "description": "这次要学什么（一句话）"},
                    "importance": {"type": "string", "enum": ["high", "medium", "low"]},
                    "reasoning": {"type": "string", "description": "为什么认为这值得学习"},
                    "sync": {"type": "boolean", "description": "true=blocking, false=fire-and-forget(default)"},
                },
                "required": ["domain", "learning_target", "importance", "reasoning"],
            },
        },
    }, _record_learning_handler, toolset="core", sync=False)


def _record_learning_handler(args=None):
    d = args or {}
    domain = d.get("domain", "")
    target = d.get("learning_target", "")
    importance = d.get("importance", "medium")
    reasoning = d.get("reasoning", "")
    if not domain or not target:
        return json.dumps({"error": "domain and learning_target required"})

    sync = d.get("sync", False)

    if sync:
        record = _build_and_save(domain, target, importance, reasoning)
        return json.dumps(record, ensure_ascii=False, default=str)

    def _run():
        return _build_and_save(domain, target, importance, reasoning)

    from core.task_runner import get_task_runner
    tid = get_task_runner().submit("record_learning", _run)
    return json.dumps({"task_id": tid, "status": "running"})


def _build_and_save(domain, target, importance, reasoning):
    from core.round_tree import get_round_history
    tree_data = get_round_history().all_as_dict()

    source_rounds = list(range(max(1, len(tree_data) - min(5, len(tree_data)) + 1),
                                len(tree_data) + 1))

    record = {
        "id": uuid.uuid4().hex,
        "domain": domain,
        "learning_target": target,
        "importance": importance,
        "reasoning": reasoning,
        "l1_observations": [],
        "l2_observations": [],
        "l3_observations": [],
        "source_rounds": source_rounds,
        "recorded_at": _now(),
    }

    _fill_observations(record, tree_data)

    pending_path = Path("data/learning/pending") / domain.replace("/", "_")
    pending_path.mkdir(parents=True, exist_ok=True)
    stamp = _now().replace(":", "-")
    filepath = pending_path / f"{record['id']}_{stamp}.json"
    content = json.dumps(record, ensure_ascii=False, indent=2, default=str)
    fd, tmp = tempfile.mkstemp(dir=str(pending_path), suffix=".json")
    with open(fd, "w", encoding="utf-8") as f:
        f.write(content)
    Path(tmp).replace(filepath)

    return {"status": "ok", "file": str(filepath), "id": record["id"]}


def _fill_observations(record: dict, tree_data: list[dict]):
    for round_node in tree_data:
        for child in round_node.get("children", []):
            if child["layer"] == "l2" and child.get("result"):
                record["l2_observations"].append({
                    "finding": f"L2: {child['query'][:200]}",
                    "evidence": child["result"][:500],
                    "implication": "",
                })
            for grandchild in child.get("children", []):
                if grandchild["layer"] == "l3" and grandchild.get("result"):
                    record["l3_observations"].append({
                        "finding": f"L3: {grandchild.get('query', '')[:100]}",
                        "evidence": grandchild["result"][:500],
                        "implication": "",
                    })
