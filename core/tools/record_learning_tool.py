"""record_learning tool — Agent proposes learnable content, sub-agent fills details."""
from __future__ import annotations
import json, logging, uuid, tempfile
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

# Pending dir is set per-chain by chain_factory._mount_tools so that isolated
# data roots (e.g. chess experiment forks) get their own learning pipeline.
# Default keeps backward compat for CLI/standalone usage.
_pending_dir: Path = Path("data/learning/pending")


def set_pending_dir(path: Path | str) -> None:
    """Set the pending dir used by record_learning handlers.

    Called once per chain build from chain_factory._mount_tools.
    """
    global _pending_dir
    _pending_dir = Path(path)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def register_record_learning(registry, pending_dir: str = "data/learning/pending",
                              consol_ctx=None):
    """Register record_learning tool. consol_ctx param kept for backward compat, unused."""
    registry.register("record_learning", {
        "type": "function",
        "function": {
            "name": "record_learning",
            "description": (
                "记录值得学习的内容（仅L1可用）。提供 learning_target + importance + reasoning。"
                "L2/L3的详细evidence由后台 sub-agent 自动补充后写入pending文件夹。默认异步(sync=false)，返回task_id。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "learning_target": {"type": "string", "description": "这次要学什么（一句话）"},
                    "importance": {"type": "string", "enum": ["high", "medium", "low"]},
                    "reasoning": {"type": "string", "description": "为什么认为这值得学习"},
                    "sync": {"type": "boolean", "description": "true=blocking, false=fire-and-forget(default)"},
                },
                "required": ["learning_target", "importance", "reasoning"],
            },
        },
    }, _record_learning_handler, toolset="core", sync=False)


def _record_learning_handler(args=None, **kwargs):
    d = args or {}
    target = d.get("learning_target", "")
    importance = d.get("importance", "medium")
    reasoning = d.get("reasoning", "")
    if not target:
        return json.dumps({"error": "learning_target required"})

    domain = "interaction"

    # Capture current thread-local node BEFORE submitting to worker thread.
    # current_node() uses threading.local — a pool worker can't see the caller's
    # stack, so the in-progress round's decision tree would be lost without this.
    from core.round_tree import current_node
    current = current_node()

    if d.get("sync", False):
        record = _build_and_save(domain, target, importance, reasoning,
                                  current_node=current)
        return json.dumps(record, ensure_ascii=False, default=str)

    def _run():
        return _build_and_save(domain, target, importance, reasoning,
                               current_node=current)

    from core.task_runner import get_shared_runner
    from core.session import get_task_context, get_session_store
    session_id, parent_task_id = get_task_context()
    metadata = {"session_id": session_id, "parent_task_id": parent_task_id}
    tid = get_shared_runner().submit("record_learning", _run, metadata=metadata)
    if session_id:
        try:
            get_session_store().register_task(
                tid, session_id, "record_learning",
                parent_task_id=parent_task_id, tool_name="record_learning",
            )
        except Exception:
            logger.exception("Failed to register record_learning task in session store")
    return json.dumps({"task_id": tid, "status": "running"})


def _build_and_save(domain, target, importance, reasoning, current_node=None):
    from core.round_tree import get_round_history
    tree_nodes = get_round_history().snapshot()

    # The in-progress round's L1 node is on the thread-local stack (pushed by
    # L0_5_1Manager.query before agent.decide runs record_learning), but NOT yet
    # in RoundHistory (which is pushed only after decide returns). Without this,
    # the very round that triggered learning is invisible to the LLM observer.
    if current_node is not None and not any(current_node is n for n in tree_nodes):
        tree_nodes = tree_nodes + [current_node]

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

    _fill_observations_llm(record, tree_nodes, target)

    pending_path = _pending_dir
    pending_path.mkdir(parents=True, exist_ok=True)
    stamp = _now().replace(":", "-")
    filepath = pending_path / f"{record['id']}_{stamp}.json"
    content = json.dumps(record, ensure_ascii=False, indent=2, default=str)
    fd, tmp = tempfile.mkstemp(dir=str(pending_path), suffix=".json")
    with open(fd, "w", encoding="utf-8") as f:
        f.write(content)
    Path(tmp).replace(filepath)

    _check_auto_trigger(pending_path, domain)

    return {"status": "ok", "file": str(filepath), "id": record["id"]}


def _check_auto_trigger(pending_path: Path, domain: str):
    json_files = sorted(pending_path.glob("*.json"))
    if len(json_files) < 5:
        return

    from core.task_runner import get_shared_runner
    from core.session import get_task_context, get_session_store
    session_id, parent_task_id = get_task_context()
    metadata = {"session_id": session_id, "parent_task_id": parent_task_id}
    tid = get_shared_runner().submit(
        "auto_learning", lambda d=domain, p=pending_path, files=json_files:
        _dispatch_learning(d, p, files), metadata=metadata)
    if session_id:
        try:
            get_session_store().register_task(
                tid, session_id, "auto_learning",
                parent_task_id=parent_task_id, tool_name="auto_learning",
            )
        except Exception:
            logger.exception("Failed to register auto_learning task in session store")


def _dispatch_learning(domain: str, pending_path: Path, json_files: list):
    import json as _json
    import shutil
    import logging
    _log = logging.getLogger(__name__)

    # 1. Read all records into memory
    records = []
    for fp in json_files:
        try:
            records.append(_json.loads(fp.read_text(encoding="utf-8")))
        except (_json.JSONDecodeError, OSError):
            _log.warning("Failed to read pending file: %s", fp)

    if not records:
        return

    # 2. Move files to archive
    archive_dir = pending_path.parent.parent / "archive" / domain.replace("/", "_")
    archive_dir.mkdir(parents=True, exist_ok=True)
    for fp in json_files:
        try:
            shutil.move(str(fp), str(archive_dir / fp.name))
        except OSError as e:
            _log.warning("Failed to archive %s: %s", fp.name, e)
    _log.info("Auto-learning: archived %d files → %s", len(json_files), archive_dir)

    # 3. Get learning context
    from core.runtime_registry import get_executor
    from core.tools.consolidation_injection import get_store
    executor = get_executor()
    knowledge = {
        "l1": get_store("l1"),
        "l2": get_store("l2"),
        "l3": get_store("l3"),
    }
    knowledge = {k: v for k, v in knowledge.items() if v is not None}

    if not executor:
        _log.warning("Auto-learning: no Executor registered, skipping")
        return

    # 4. Create LearningEnv and build task
    from core.env.learning_env import LearningEnv
    lenv = LearningEnv(pending_path.parent, knowledge)
    obs = lenv.process_in_memory(records, domain)
    if obs is None:
        _log.warning("Auto-learning: failed to build task observation")
        return

    # 5. Execute through layers → apply + consolidation check
    result = executor.execute(obs)
    notify = result.get("notify_layers", {})
    step = lenv.step(_json.dumps(notify, ensure_ascii=False, default=str))
    _log.info("Auto-learning done: %s", step.state.observation)

    # 6. Check if consolidation is needed after learning
    from core.env.learning_env import LearningEnv
    if lenv.needs_consolidation():
        _log.info("Auto-learning: triggering consolidation (capacity overflow)")
        try:
            consol_task = lenv.build_consolidation_task()
            if consol_task:
                consol_result = executor.execute(consol_task)
                consol_notify = consol_result.get("notify_layers", {})
                lenv.step(_json.dumps(consol_notify, ensure_ascii=False, default=str))
                _log.info("Auto-learning: consolidation complete")
        except Exception as e:
            _log.info("Auto-learning: consolidation failed: %s", e)

    # 7. Clean up archive — delete entries older than 30 days
    _clean_old_archives(archive_dir.parent, 30)


def _clean_old_archives(archive_root: Path, max_age_days: int):
    """Delete archive subdirectories older than max_age_days."""
    import time
    if not archive_root.exists():
        return
    cutoff = time.time() - max_age_days * 86400
    for d in archive_root.iterdir():
        if d.is_dir():
            try:
                if d.stat().st_mtime < cutoff:
                    shutil.rmtree(d, ignore_errors=True)
                    _log.info("Auto-learning: cleaned old archive %s", d.name)
            except OSError:
                pass


SUB_AGENT_PROMPT = """你是一个学习记录分析员。根据 learning_target 扫描决策树，
 提取 L1、L2 和 L3 层中与该目标相关的 observation。

决策树结构（缩进表示父子关系）：
  L1[name=root]: 本轮最高决策
    └─ L2[name=child]: L2 层的查询处理
         └─ L3[name=grandchild]: L3 层的技能执行

你需要输出严格的 JSON（json_mode），格式如下：
{
  "l1_observations": [
    {
      "finding": "L1 层的顶层推理或结论",
      "evidence": "摘录自决策树中 L1 节点的 result 字段（原文引用）",
      "implication": "这对 learning_target 意味着什么",
      "relevance": "high | medium | low"
    }
  ],
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
- evidence 必须是 decision_tree 中某节点的 result 原文（截取前 10000 字），不能编造。
- implication 是推论：例如"因为 L2 没有该领域的卡片，所以应该补充"。
- 如果某节点在某轮中无实质发现（result 为空或纯状态信息如 status:ok），跳过该节点。
- 最多每层返回 5 条 observation，按 relevance 降序。
- 如果没有相关 observation，返回空数组 []。
- L3 节点仅在其内容与 learning_target 相关时才提取。
- 注意保留树结构中的 parent-child 关系——observation 的 evidence 应该清晰地指出来自哪个节点及其子节点。
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
        lines.append(f"[{prefix}{label}] query: {str(query)[:10000]}")
        if result:
            lines.append(f"[{prefix}{label}] result: {str(result)[:10000]}")
        if reasoning:
            lines.append(f"[{prefix}{label}] reasoning: {str(reasoning)[:10000]}")
        children = getattr(node, 'children', []) if hasattr(node, 'children') else node.get('children', [])
        for c_idx, child in enumerate(children):
            _walk(child, f"{prefix}{c_idx + 1}.")

    for n in nodes:
        l1_idx += 1
        _walk(n, f"{l1_idx}.")
        lines.append("")
    return "\n".join(lines)


def _fill_observations_llm(record: dict, tree_nodes: list, target: str):
    """Use LLM to extract L2/L3 observations from RoundTree, with strict JSON mode.
    Reuses the executor's existing LLM client — no new client creation per call.
    Raises on failure instead of silently writing empty record."""
    tree_text = _format_tree_for_llm(tree_nodes)
    if not tree_text.strip():
        return

    prompt = (
        f"learning_target: {target}\n"
        f"importance: {record.get('importance', 'medium')}\n"
        f"reasoning: {record.get('reasoning', '')}\n\n"
        f"decision_tree:\n{tree_text}"
    )

    from core.runtime_registry import get_executor
    executor = get_executor()
    if executor is None:
        raise RuntimeError("Executor not registered — cannot fill observations")
    llm = executor._llm
    messages = [
        {"role": "system", "content": SUB_AGENT_PROMPT},
        {"role": "user", "content": prompt},
    ]
    resp = llm.chat(messages=messages, json_mode=True)
    text = resp.text if hasattr(resp, 'text') else str(resp)
    filled = json.loads(text)
    record["l1_observations"] = filled.get("l1_observations", [])
    record["l2_observations"] = filled.get("l2_observations", [])
    record["l3_observations"] = filled.get("l3_observations", [])
