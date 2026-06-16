"""record_learning integration test."""
from __future__ import annotations
import json, sys, tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def test_round_tree_build():
    """Test DecisionNode construction and push to history."""
    from core.round_tree import DecisionNode, get_round_history

    l1 = DecisionNode("l0_5_1", "评估方案", "8/10", "用了结构化框架")
    l2 = DecisionNode("l2", "读文件", "307行", "找到search.txt")
    l3 = DecisionNode("l3", "ls", "done", "")
    l2.children.append(l3)
    l1.children.append(l2)

    h = get_round_history()
    h.push(l1)
    assert len(h.snapshot()) >= 1
    data = h.all_as_dict()
    assert any("读文件" in str(d) for d in data)
    print("PASS: RoundTree build + push")


def test_record_learning_handler():
    """Test handler — builds and saves a learning record."""
    from core.tools.record_learning_tool import _build_and_save
    from core.round_tree import DecisionNode, get_round_history

    h = get_round_history()
    l1 = DecisionNode("l0_5_1", "查目录", "found 17 files", "used ls command")
    l2 = DecisionNode("l2", "ls /mnt/c/...", "path: /workspace", "executed pwd+ls")
    l1.children.append(l2)
    h.push(l1)

    record = _build_and_save("test_e2e", "how to handle file queries",
                            "high", "user frequently asks about files")
    assert record["status"] == "ok"
    assert Path(record["file"]).exists()
    print(f"PASS: record_learning → file: {Path(record['file']).name}")

    with open(record["file"], encoding="utf-8") as f:
        data = json.load(f)
    assert data["domain"] == "test_e2e"
    assert data["importance"] == "high"
    assert len(data["l2_observations"]) >= 1
    print(f"PASS: content valid — {len(data['l2_observations'])} L2 observations")

    Path(record["file"]).unlink()
    print("PASS: cleanup done")


if __name__ == "__main__":
    test_round_tree_build()
    test_record_learning_handler()
    print("\nAll record_learning tests pass!")
