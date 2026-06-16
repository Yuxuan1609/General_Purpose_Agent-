"""record_learning tool — Agent proposes learnable content, sub-agent fills details."""
from __future__ import annotations
import json, uuid, tempfile
from datetime import datetime, timezone
from pathlib import Path

from core.llm_factory import build_llm_client


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def register_record_learning(registry, pending_dir: str = "data/learning/pending"):
    registry.register("record_learning", {
        "type": "function",
        "function": {
            "name": "record_learning",
            "description": (
                "记录值得学习的内容（仅L1可用）。提供 domain + learning_target + importance + reasoning。"
                "L2/L3的详细evidence由后台 sub-agent 自动补充后写入pending文件夹。默认异步(sync=false)，返回task_id。"
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

    if d.get("sync", False):
        record = _build_and_save(domain, target, importance, reasoning)
        return json.dumps(record, ensure_ascii=False, default=str)

    def _run():
        return _build_and_save(domain, target, importance, reasoning)

    from core.task_runner import get_task_runner
    tid = get_task_runner().submit("record_learning", _run)
    return json.dumps({"task_id": tid, "status": "running"})


def _build_and_save(domain, target, importance, reasoning):
    from core.round_tree import get_round_history
    tree_nodes = get_round_history().snapshot()

    record = {
        "id": uuid.uuid4().hex,
        "domain": domain,
        "learning_target": target,
        "importance": importance,
        "reasoning": reasoning,
        "l1_observations": [],
        "l2_observations": [],
        "l3_observations": [],
        "source_rounds": list(range(1, len(tree_nodes) + 1)),
        "recorded_at": _now(),
    }

    # Fill L2/L3 via LLM sub-agent
    _fill_observations_llm(record, tree_nodes, target)

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


SUB_AGENT_PROMPT = """你是一个学习记录分析员。根据 learning_target 扫描决策树，
提取 L2 和 L3 层中与该目标相关的 observation。

决策树结构（缩进表示父子关系）：
  L1[name=root]: 本轮最高决策
    └─ L2[name=child]: L2 层的查询处理
         └─ L3[name=grandchild]: L3 层的技能执行

你需要输出严格的 JSON（json_mode），格式如下：
{
  "l2_observations": [
    {
      "finding": "L2层发现了什么或处理了什么",
      "evidence": "摘录自决策树中 L2 节点的 result 字段（原文引用）",
      "implication": "这对 learning_target 意味着什么",
      "relevance": "high | medium | low"
    }
  ],
  "l3_observations": [
    { "finding": "...", "evidence": "...", "implication": "...", "relevance": "high | medium | low" }
  ]
}

规则：
- 只提取与 learning_target 语义相关的 observation。不相关的跳过。
- evidence 必须是 decision_tree 中某节点的 result 原文（截取前 500 字），不能编造。
- implication 是推论：例如"因为 L2 没有该领域的卡片，所以应该补充"。
- 如果 L2 节点在某轮中无实质发现（result 为空或纯状态信息如 status:ok），跳过该节点。
- 最多每层返回 5 条 observation，按 relevance 降序。
- 如果没有相关 observation，返回空数组 []。
- L3 节点仅在其内容与 learning_target 相关时才提取。
- 注意保留树结构中的 parent-child 关系——observation 的 evidence 应该清晰地指出来自哪个 L2 节点及其子 L3 节点。
"""


def _format_tree_for_llm(nodes: list) -> str:
    """Format RoundTree with structure-aware numbering (1, 1.1, 1.1.1) for LLM."""
    lines = []
    l1_idx = 0

    def _walk(node, prefix: str = ""):
        if hasattr(node, 'layer'):
            layer = node.layer
            query = getattr(node, 'query', '')
            result = getattr(node, 'result', '')
            reasoning = getattr(node, 'reasoning', '')
        elif isinstance(node, dict):
            layer = node.get("layer", "?")
            query = node.get("query", "")
            result = node.get("result", "")
            reasoning = node.get("reasoning", "")
        else:
            return
        label = {"l0_5_1": "L1", "l2": "L2", "l3": "L3"}.get(layer, layer)
        lines.append(f"[{prefix}{label}] query: {str(query)[:200]}")
        if result:
            lines.append(f"[{prefix}{label}] result: {str(result)[:500]}")
        if reasoning:
            lines.append(f"[{prefix}{label}] reasoning: {str(reasoning)[:300]}")
        children = getattr(node, 'children', []) if hasattr(node, 'children') else node.get('children', [])
        for c_idx, child in enumerate(children):
            _walk(child, f"{prefix}{c_idx + 1}.")

    for n in nodes:
        l1_idx += 1
        _walk(n, f"{l1_idx}.")
        lines.append("")
    return "\n".join(lines)


def _fill_observations_llm(record: dict, tree_nodes: list, target: str):
    """Use LLM to extract L2/L3 observations from RoundTree, with strict JSON mode."""
    tree_text = _format_tree_for_llm(tree_nodes)
    if not tree_text.strip():
        return

    prompt = (
        f"learning_target: {target}\n"
        f"importance: {record.get('importance', 'medium')}\n"
        f"reasoning: {record.get('reasoning', '')}\n\n"
        f"decision_tree:\n{tree_text}"
    )

    try:
        llm = build_llm_client(temperature=0.1)
        messages = [
            {"role": "system", "content": SUB_AGENT_PROMPT},
            {"role": "user", "content": prompt},
        ]
        resp = llm.chat(messages=messages, json_mode=True)
        text = resp.text if hasattr(resp, 'text') else str(resp)

        try:
            filled = json.loads(text)
        except json.JSONDecodeError:
            filled = {}

        record["l2_observations"] = filled.get("l2_observations", [])
        record["l3_observations"] = filled.get("l3_observations", [])
    except Exception:
        pass  # LLM unavailable → observations stay empty
