# Reflection Proposer-Verifier Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement LLM-based Proposer-Verifier reflection pipeline replacing rule-based ReflectionAgent.investigate/fix

**Architecture:** Proposer (LLM) analyzes NOTIFY → Verifier (LLM) validates + integrates with existing content → Manager.apply_update(). Config-driven schemas prevent interface breakage.

**Tech Stack:** Python 3.11+, dataclasses, YAML config, DeepSeek JSON mode

---

## File Structure

```
config/
  reflect.yaml                            # NEW: Proposer/Verifier schemas + prompts per layer

core/layers/
  l0_5_1/
    reflection_agent.py                   # MODIFY: replace investigate/fix with Proposer/Verifier
    manager.py                            # MODIFY: enhance NOTIFY with rules_applied, l2_received
  l2/
    reflection_agent.py                   # MODIFY: same
    manager.py                            # MODIFY: enhance NOTIFY with cards_used, l3_received
  l3/
    reflection_agent.py                   # MODIFY: same
    manager.py                            # MODIFY: enhance NOTIFY with skills_used

scripts/
  test_reflection_flow.py                # MODIFY: integrate Proposer/Verifier, use config

tests/
  test_reflect_proposer.py               # NEW: Proposer config loading + output parsing
  test_reflect_verifier.py               # NEW: Verifier config loading + integration detection
```

---

### Task 1: Config file — schemas and prompts

**Files:**
- Create: `config/reflect.yaml`

- [ ] **Step 1: Write the config**

```yaml
# Reflection Proposer/Verifier config per layer.
# Schemas define JSON output contract; prompts define LLM behavior.
# Changing schemas updates both prompt injection and parse validation.

l1:
  proposer:
    schema:
      self_fixes:
        - action: "add_rule | modify_rule | remove_rule"
          content: "string"
          reason: "string"
      dispatch_lower: "null | {layer: string, task: string}"
    criteria: |
      L1 反思标准：
      1) result 与 reasoning 的推理方向是否一致
      2) reasoning 是否基于概率期望而非直觉
      3) rules_applied 是否充分覆盖当前决策需求
      4) l2_received 的回复是否准确且信息充分
    system_template: |
      你是 L1 层的反思 Proposer。分析本层 Execute 段的输出质量。
      
      {criteria}
      
      你的任务：
      1. 分析本层 NOTIFY，提出对本层行为准则的修复方案
      2. 判断是否需要 L2 层反思（仅当 l2_received 信息不充分时）
      
      可用的 action: add_rule（新增准则）, modify_rule（修改准则）, remove_rule（删除准则）
    user_template: |
      [Refiner 评估]
      {refiner_reasoning}
      
      [上层 Dispatch]
      {dispatch_info}
      
      [本层 NOTIFY]
      {layer_notify}
      
      请输出 JSON。

  verifier:
    schema:
      verified:
        - action: "string"
          content: "string"
          integrated_with: "string"
      rejected:
        - action: "string"
          content: "string"
          reason: "string"
    system_template: |
      你是 L1 层的反思 Verifier。根据已有行为准则整合 Proposer 的提案。
      
      规则：
      1. 与已有准则语义重复 → reject
      2. 可整合但需调整 → modified + verified
      3. 全新独立准则 → verified
      4. 准则数已达上限 → 说明并reject
    user_template: |
      [Proposer 提案]
      {proposals}
      
      [已有行为准则]
      {existing_rules}
      
      请输出 JSON。

l2:
  proposer:
    schema:
      self_fixes:
        - action: "boost_card | penalize_card | add_card"
          card_id: "string"
          new_confidence: "float | null"
          content: "string | null"
          reason: "string"
      dispatch_lower: "null | {layer: string, task: string}"
    criteria: |
      L2 反思标准：
      1) cards_used 是否准确覆盖了 L1 query 的信息需求
      2) reply 是否完整且基于卡片内容
      3) 卡片置信度是否反映实际效用
      4) l3_received 的技能是否被合理调用
    system_template: |
      你是 L2 层的反思 Proposer。分析本层 Execute 段的知识检索输出质量。
      
      {criteria}
      
      可用的 action:
      - boost_card: 提高卡片置信度（需 card_id + new_confidence）
      - penalize_card: 降低卡片置信度（需 card_id）
      - add_card: 新增知识卡片（需 content + domain）
    user_template: |
      [Refiner 评估]
      {refiner_reasoning}
      
      [上层 Dispatch]
      {dispatch_info}
      
      [本层 NOTIFY]
      {layer_notify}
      
      请输出 JSON。

  verifier:
    schema:
      verified:
        - action: "string"
          card_id: "string"
          new_confidence: "float | null"
          content: "string | null"
      rejected:
        - action: "string"
          reason: "string"
    system_template: |
      你是 L2 层的反思 Verifier。根据已有知识卡片整合 Proposer 的提案。
      
      规则：
      1. boost/penalize 后置信度必须在 0.1-1.0 范围内
      2. add_card 的内容不得与已有卡片高度重复
      3. card_id 必须对应真实存在的卡片
    user_template: |
      [Proposer 提案]
      {proposals}
      
      [已有知识卡片]
      {existing_cards}
      
      请输出 JSON。

l3:
  proposer:
    schema:
      self_fixes:
        - action: "update_skill"
          skill_name: "string"
          content: "string"
          reason: "string"
      dispatch_lower: "null"
    criteria: |
      L3 反思标准：
      1) skills_used 是否匹配当前局面的需求
      2) 是否有可用的技能未被调用
      3) 技能内容是否需要更新以更贴切当前任务
    system_template: |
      你是 L3 层的反思 Proposer。分析本层 Execute 段的技能匹配输出质量。
      
      {criteria}
      
      可用的 action: update_skill（更新技能内容，需 skill_name + content）
    user_template: |
      [Refiner 评估]
      {refiner_reasoning}
      
      [上层 Dispatch]
      {dispatch_info}
      
      [本层 NOTIFY]
      {layer_notify}
      
      请输出 JSON。

  verifier:
    schema:
      verified:
        - action: "string"
          skill_name: "string"
          content: "string"
      rejected:
        - action: "string"
          reason: "string"
    system_template: |
      你是 L3 层的反思 Verifier。根据已有技能整合 Proposer 的提案。
      
      规则：
      1. skill_name 必须匹配已有或合理的技能名
      2. update_skill 的内容需符合 SKILL.md 格式
      3. 避免覆盖现有的有效技能（除非提案明确说明更新理由）
    user_template: |
      [Proposer 提案]
      {proposals}
      
      [已有技能]
      {existing_skills}
      
      请输出 JSON。
```

- [ ] **Step 2: Verify YAML is valid**

```bash
python -c "import yaml; yaml.safe_load(open('config/reflect.yaml'))" && echo "OK"
```

- [ ] **Step 3: Commit**

```bash
git add config/reflect.yaml
git commit -m "feat: Reflection Proposer/Verifier config with schemas per layer"
```

---

### Task 2: Config loader + schema validation

**Files:**
- Create: `core/reflect_config.py`
- Test: `tests/test_reflect_config.py`

- [ ] **Step 1: Write test for config loading**

```python
# tests/test_reflect_config.py
import pytest
from core.reflect_config import ReflectConfig, load_reflect_config


class TestReflectConfig:
    def test_loads_l1_proposer_schema(self):
        cfg = load_reflect_config()
        l1 = cfg.l1
        assert "proposer" in l1
        assert "schema" in l1["proposer"]
        assert "self_fixes" in l1["proposer"]["schema"]
        assert l1["proposer"]["schema"]["self_fixes"][0]["action"].startswith("add_rule")

    def test_loads_l2_verifier_schema(self):
        cfg = load_reflect_config()
        l2 = cfg.l2
        assert "verifier" in l2
        assert "schema" in l2["verifier"]
        assert "verified" in l2["verifier"]["schema"]

    def test_all_three_layers_configured(self):
        cfg = load_reflect_config()
        for layer in ["l1", "l2", "l3"]:
            layer_cfg = getattr(cfg, layer)
            assert "proposer" in layer_cfg
            assert "verifier" in layer_cfg
            assert layer_cfg["proposer"]["schema"]
            assert layer_cfg["verifier"]["schema"]

    def test_templates_contain_placeholders(self):
        cfg = load_reflect_config()
        for layer_name in ["l1", "l2", "l3"]:
            layer_cfg = getattr(cfg, layer_name)
            p_sys = layer_cfg["proposer"]["system_template"]
            p_usr = layer_cfg["proposer"]["user_template"]
            assert "{criteria}" in p_sys
            assert "{refiner_reasoning}" in p_usr
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_reflect_config.py -v
```
Expected: FAIL (module not found)

- [ ] **Step 3: Implement config loader**

```python
# core/reflect_config.py
"""Reflection config loader — reads config/reflect.yaml into structured dicts."""
import yaml
from pathlib import Path
from dataclasses import dataclass, field


@dataclass
class ReflectConfig:
    l1: dict = field(default_factory=dict)
    l2: dict = field(default_factory=dict)
    l3: dict = field(default_factory=dict)

    @classmethod
    def from_yaml(cls, path: Path) -> "ReflectConfig":
        with open(path, encoding="utf-8") as f:
            raw = yaml.safe_load(f)
        return cls(
            l1=raw.get("l1", {}),
            l2=raw.get("l2", {}),
            l3=raw.get("l3", {}),
        )


def load_reflect_config() -> ReflectConfig:
    config_path = Path(__file__).resolve().parent.parent / "config" / "reflect.yaml"
    return ReflectConfig.from_yaml(config_path)
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/test_reflect_config.py -v
```
Expected: 4 PASS

- [ ] **Step 5: Commit**

```bash
git add core/reflect_config.py tests/test_reflect_config.py
git commit -m "feat: ReflectConfig loader from config/reflect.yaml"
```

---

### Task 3: L1 Proposer

**Files:**
- Modify: `core/layers/l0_5_1/reflection_agent.py`
- Test: `tests/test_reflect_proposer.py`

- [ ] **Step 1: Write test for L1 Proposer format**

```python
# tests/test_reflect_proposer.py
import pytest
from unittest.mock import Mock
from core.layers.l0_5_1.reflection_agent import L1ReflectProposer


class TestL1ReflectProposer:
    @pytest.fixture
    def mock_llm(self):
        llm = Mock()
        llm.chat.return_value = Mock(
            text='{"self_fixes": [], "dispatch_lower": null}',
            tool_calls=[], has_tool_calls=False,
        )
        return llm

    @pytest.fixture
    def proposer(self, mock_llm):
        return L1ReflectProposer(mock_llm)

    def test_propose_returns_structured_output(self, proposer, mock_llm):
        result = proposer.propose(
            layer_notify={"result": "fold", "reasoning": "weak hand"},
            refiner_reasoning="good decision",
            meta="Leduc rules",
            dispatch_info="无",
        )
        assert "self_fixes" in result
        assert "dispatch_lower" in result

    def test_proposer_sends_json_mode(self, proposer, mock_llm):
        proposer.propose(
            layer_notify={}, refiner_reasoning="", meta="", dispatch_info="",
        )
        call_kwargs = mock_llm.chat.call_args[1]
        assert call_kwargs.get("json_mode") is True

    def test_system_prompt_includes_criteria(self, proposer, mock_llm):
        proposer.propose(
            layer_notify={}, refiner_reasoning="", meta="", dispatch_info="",
        )
        messages = mock_llm.chat.call_args[1]["messages"]
        system = messages[0]["content"]
        assert "L1 反思标准" in system
        assert "result" in system
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_reflect_proposer.py::TestL1ReflectProposer -v
```
Expected: FAIL (L1ReflectProposer not defined)

- [ ] **Step 3: Implement L1ReflectProposer**

```python
# Add to core/layers/l0_5_1/reflection_agent.py
import logging
from core.layers.base import LayerAgent
from core.reflect_config import load_reflect_config

_reflect_cfg = load_reflect_config()


class L1ReflectProposer(LayerAgent):
    """L1 Proposer — analyzes L1 NOTIFY and proposes self-fixes.

    Input: layer_notify, refiner_reasoning, meta, dispatch_info
    Output: {self_fixes: [{action, content, reason}], dispatch_lower: null|dict}
    """

    def __init__(self, llm_client):
        super().__init__(llm_client, logging.getLogger("l0_5_1_reflect"))
        self._cfg = _reflect_cfg.l1["proposer"]

    def propose(self, layer_notify: dict, refiner_reasoning: str,
                meta: str, dispatch_info: str = "无") -> dict:
        system = self._cfg["system_template"].format(
            criteria=self._cfg["criteria"],
        )
        import json
        user = self._cfg["user_template"].format(
            refiner_reasoning=refiner_reasoning,
            dispatch_info=dispatch_info,
            layer_notify=json.dumps(layer_notify, ensure_ascii=False, indent=2),
        )
        return self._call_llm(system, user, schema=self._cfg["schema"])
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/test_reflect_proposer.py::TestL1ReflectProposer -v
```
Expected: 3 PASS

- [ ] **Step 5: Commit**

```bash
git add core/layers/l0_5_1/reflection_agent.py tests/test_reflect_proposer.py
git commit -m "feat: L1ReflectProposer with config-driven schema"
```

---

### Task 4: L1 Verifier

**Files:**
- Modify: `core/layers/l0_5_1/reflection_agent.py`
- Test: `tests/test_reflect_verifier.py`

- [ ] **Step 1: Write test**

```python
# tests/test_reflect_verifier.py
import pytest
from unittest.mock import Mock
from core.layers.l0_5_1.reflection_agent import L1ReflectVerifier


class TestL1ReflectVerifier:
    @pytest.fixture
    def mock_llm(self):
        llm = Mock()
        llm.chat.return_value = Mock(
            text='{"verified": [], "rejected": []}',
            tool_calls=[], has_tool_calls=False,
        )
        return llm

    @pytest.fixture
    def verifier(self, mock_llm):
        return L1ReflectVerifier(mock_llm)

    def test_verify_includes_existing_rules(self, verifier, mock_llm):
        proposals = [
            {"action": "add_rule", "content": "持有弱牌时优先fold", "reason": "test"}
        ]
        existing_rules = ["面对不确定信息时优先搜索验证"]
        verifier.verify(proposals, existing_rules)

        messages = mock_llm.chat.call_args[1]["messages"]
        user = messages[1]["content"]
        assert "持有弱牌时优先fold" in user
        assert "面对不确定信息时优先搜索验证" in user

    def test_verify_returns_structured_output(self, verifier, mock_llm):
        result = verifier.verify([], [])
        assert "verified" in result
        assert "rejected" in result
        assert isinstance(result["verified"], list)
        assert isinstance(result["rejected"], list)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_reflect_verifier.py::TestL1ReflectVerifier -v
```
Expected: FAIL

- [ ] **Step 3: Implement L1ReflectVerifier**

```python
# Add to core/layers/l0_5_1/reflection_agent.py

class L1ReflectVerifier(LayerAgent):
    """L1 Verifier — validates proposals against existing rules."""

    def __init__(self, llm_client):
        super().__init__(llm_client, logging.getLogger("l0_5_1_reflect"))
        self._cfg = _reflect_cfg.l1["verifier"]

    def verify(self, proposals: list[dict], existing_rules: list[str]) -> dict:
        import json
        system = self._cfg["system_template"]
        user = self._cfg["user_template"].format(
            proposals=json.dumps(proposals, ensure_ascii=False, indent=2),
            existing_rules=json.dumps(existing_rules, ensure_ascii=False),
        )
        return self._call_llm(system, user, schema=self._cfg["schema"])
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/test_reflect_verifier.py::TestL1ReflectVerifier -v
```
Expected: 2 PASS

- [ ] **Step 5: Commit**

```bash
git add core/layers/l0_5_1/reflection_agent.py tests/test_reflect_verifier.py
git commit -m "feat: L1ReflectVerifier validates proposals against existing rules"
```

---

### Task 5: L2/L3 Proposer + Verifier (repeat pattern)

**Files:**
- Modify: `core/layers/l2/reflection_agent.py`
- Modify: `core/layers/l3/reflection_agent.py`

- [ ] **Step 1: Implement L2ReflectProposer + L2ReflectVerifier**

```python
# Add to core/layers/l2/reflection_agent.py
import logging
from core.layers.base import LayerAgent
from core.reflect_config import load_reflect_config
import json

_reflect_cfg = load_reflect_config()


class L2ReflectProposer(LayerAgent):
    def __init__(self, llm_client):
        super().__init__(llm_client, logging.getLogger("l2_reflect"))
        self._cfg = _reflect_cfg.l2["proposer"]

    def propose(self, layer_notify: dict, refiner_reasoning: str,
                meta: str, dispatch_info: str = "无") -> dict:
        system = self._cfg["system_template"].format(criteria=self._cfg["criteria"])
        user = self._cfg["user_template"].format(
            refiner_reasoning=refiner_reasoning,
            dispatch_info=dispatch_info,
            layer_notify=json.dumps(layer_notify, ensure_ascii=False, indent=2),
        )
        return self._call_llm(system, user, schema=self._cfg["schema"])


class L2ReflectVerifier(LayerAgent):
    def __init__(self, llm_client):
        super().__init__(llm_client, logging.getLogger("l2_reflect"))
        self._cfg = _reflect_cfg.l2["verifier"]

    def verify(self, proposals: list[dict], existing_cards: list[str]) -> dict:
        system = self._cfg["system_template"]
        user = self._cfg["user_template"].format(
            proposals=json.dumps(proposals, ensure_ascii=False, indent=2),
            existing_cards=json.dumps(existing_cards, ensure_ascii=False),
        )
        return self._call_llm(system, user, schema=self._cfg["schema"])
```

- [ ] **Step 2: Implement L3ReflectProposer + L3ReflectVerifier**

```python
# Add to core/layers/l3/reflection_agent.py
import logging
from core.layers.base import LayerAgent
from core.reflect_config import load_reflect_config
import json

_reflect_cfg = load_reflect_config()


class L3ReflectProposer(LayerAgent):
    def __init__(self, llm_client):
        super().__init__(llm_client, logging.getLogger("l3_reflect"))
        self._cfg = _reflect_cfg.l3["proposer"]

    def propose(self, layer_notify: dict, refiner_reasoning: str,
                meta: str, dispatch_info: str = "无") -> dict:
        system = self._cfg["system_template"].format(criteria=self._cfg["criteria"])
        user = self._cfg["user_template"].format(
            refiner_reasoning=refiner_reasoning,
            dispatch_info=dispatch_info,
            layer_notify=json.dumps(layer_notify, ensure_ascii=False, indent=2),
        )
        return self._call_llm(system, user, schema=self._cfg["schema"])


class L3ReflectVerifier(LayerAgent):
    def __init__(self, llm_client):
        super().__init__(llm_client, logging.getLogger("l3_reflect"))
        self._cfg = _reflect_cfg.l3["verifier"]

    def verify(self, proposals: list[dict], existing_skills: list[str]) -> dict:
        system = self._cfg["system_template"]
        user = self._cfg["user_template"].format(
            proposals=json.dumps(proposals, ensure_ascii=False, indent=2),
            existing_skills=json.dumps(existing_skills, ensure_ascii=False),
        )
        return self._call_llm(system, user, schema=self._cfg["schema"])
```

- [ ] **Step 3: Add L2 Proposer test**

```python
# append to tests/test_reflect_proposer.py
from core.layers.l2.reflection_agent import L2ReflectProposer
from core.layers.l3.reflection_agent import L3ReflectProposer


class TestL2ReflectProposer:
    def test_propose_uses_correct_schema(self, monkeypatch):
        llm = Mock()
        llm.chat.return_value = Mock(text='{"self_fixes": [], "dispatch_lower": null}',
                                      tool_calls=[], has_tool_calls=False)
        proposer = L2ReflectProposer(llm)
        result = proposer.propose({"reply": "test"}, "good", "meta")
        assert "self_fixes" in result


class TestL3ReflectProposer:
    def test_propose_dispatches_null(self, monkeypatch):
        llm = Mock()
        llm.chat.return_value = Mock(text='{"self_fixes": [], "dispatch_lower": null}',
                                      tool_calls=[], has_tool_calls=False)
        proposer = L3ReflectProposer(llm)
        result = proposer.propose({"skills_used": []}, "ok", "meta")
        assert result["dispatch_lower"] is None
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_reflect_proposer.py tests/test_reflect_verifier.py -v
```
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add core/layers/l2/reflection_agent.py core/layers/l3/reflection_agent.py tests/
git commit -m "feat: L2/L3 Proposer + Verifier with config-driven schemas"
```

---

### Task 6: NOTIFY enrichment in managers

**Files:**
- Modify: `core/layers/l0_5_1/manager.py`
- Modify: `core/layers/l2/manager.py`
- Modify: `core/layers/l3/manager.py`

- [ ] **Step 1: Enrich L1Agent stage2 to add rules_applied + l2_received**

In L1Agent.stage2(), add to the NOTIFY dict returned:
```python
# After stage2 result is computed, add enrichment
result["rules_applied"] = [r.content[:80] for r in self._philosophy.all_rules()[:3]]
l2_result = state.get("l2_result", {})
result["l2_received"] = {
    "reply": l2_result.get("reply", "")[:200],
    "cards": l2_result.get("cards", [])[:3],
}
```

- [ ] **Step 2: Enrich L2 NOTIFY**

In L2Manager.query(), add after stage3:
```python
result["cards_used"] = [c[:80] for c in result.get("cards", [])[:5]]
l3_result = state.get("l3_skills", [])
result["l3_received"] = {
    "skills": [s.get("name", "") for s in l3_result[:3]],
}
```

- [ ] **Step 3: Enrich L3 NOTIFY**

In L3Manager.process(), change:
```python
obs.state["l3_skills"] = [...]  # existing
obs.state["l3_skills_matched"] = [s.name for s in matched]  # NEW
```

And enhance notify():
```python
def notify(self) -> Any:
    return {
        "status": "ok",
        "skills_matched": self._matched_count,
        "skills_used": self._matched_names[:3],
    }
```

- [ ] **Step 4: Run existing tests for regression**

```bash
pytest tests/test_layers.py tests/test_executor.py -v
```
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add core/layers/l0_5_1/manager.py core/layers/l2/manager.py core/layers/l3/manager.py
git commit -m "feat: NOTIFY enrichment with rules_applied/cards_used/l2_received"
```

---

### Task 7: Integrate Proposer/Verifier into test flow

**Files:**
- Modify: `scripts/test_reflection_flow.py`

- [ ] **Step 1: Replace rule-based investigate/fix with Proposer/Verifier**

In `_process_reflect_packet()`, replace:
```python
# OLD: rule-based
issues = pkt.issue_list or _detect_issues(pkt.layer_notify)
result = agent.investigate(issues, context)
my = result.get("my_issues", [])
if my:
    fix_result = agent.fix(my)
```

With:
```python
# NEW: LLM-based Proposer → Verifier → Manager
from core.layers.l0_5_1.reflection_agent import L1ReflectProposer, L1ReflectVerifier
# ... (similar for l2, l3)

proposer = L1ReflectProposer(llm)
verifier = L1ReflectVerifier(llm)

dispatch_info = "无"
proposal = proposer.propose(
    layer_notify=pkt.layer_notify,
    refiner_reasoning=pkt.refiner_reasoning,
    meta=meta,
    dispatch_info=dispatch_info,
)
log.debug("  Proposer → %s", json.dumps(proposal, ensure_ascii=False)[:300])

if proposal.get("self_fixes"):
    existing = [r.content for r in philosophy.all_rules()]
    verified = verifier.verify(proposal["self_fixes"], existing)
    log.debug("  Verifier → %s", json.dumps(verified, ensure_ascii=False)[:300])

    for fix in verified.get("verified", []):
        chain.apply_update(fix["action"], {"content": fix.get("content", "")})
    log.debug("  Manager → %d applied", len(verified.get("verified", [])))
```

- [ ] **Step 2: Run test flow**

```bash
python -c "import sys; sys.path.insert(0, '.'); from scripts.test_reflection_flow import main; main()"
```
Expected: Proposer/Verifier logs appear in reflect logs, format matches design

- [ ] **Step 3: Verify logs show Proposer + Verifier sections**

Check `logs/leduc_cognitive_reflect/*/l0_5_1_reflect.log` contains:
- `═══ Proposer ═══` with system/user/response
- `═══ Verifier ═══` with system/user/response  
- `═══ Manager ═══` with applied count

- [ ] **Step 4: Commit**

```bash
git add scripts/test_reflection_flow.py
git commit -m "feat: Integrate Proposer-Verifier into reflection test flow"
```

---

### Task 8: ReflectDispatch wiring

**Files:**
- Modify: `core/layers/l0_5_1/reflection_agent.py`
- Modify: `core/layers/l2/reflection_agent.py`

- [ ] **Step 1: Add dispatch support to Proposer output interpretation**

```python
# In _process_reflect_packet or reflection_agent:
if proposal.get("dispatch_lower"):
    dispatch = proposal["dispatch_lower"]
    if isinstance(dispatch, dict) and dispatch.get("layer"):
        dispatch_pkt = AgentPacket(
            source_layer=layer_key,
            message_type="reflect_dispatch",
            content={"task": dispatch.get("task", ""), "context": proposal},
        )
        # TODO: Internal dispatch via LayerMessage — not implemented yet,
        #       reserved for future communication work.
        log.debug("  dispatch → %s (reserved, not sent)", dispatch.get("layer"))
```

- [ ] **Step 2: Add LayerMessage subtype for reflect dispatch**

In `core/layer_message.py`, add comment (no code change needed — subtype is already a string field):
```python
# Phase 2: "REFLECT:DISPATCH" subtype used for upper→lower reflection delegation
```

- [ ] **Step 3: Commit**

```bash
git add core/layers/l0_5_1/reflection_agent.py core/layer_message.py
git commit -m "feat: ReflectDispatch placeholder + subtype documentation"
```

---

### Task 9: Final integration + full test suite

- [ ] **Step 1: Run full test suite**

```bash
pytest tests/ -v --tb=short --ignore=tests/test_env.py --ignore=tests/test_main_config.py
```
Expected: all PASS

- [ ] **Step 2: Run end-to-end reflection flow**

```bash
python -c "import sys; sys.path.insert(0, '.'); from scripts.test_reflection_flow import main; main()"
```
Expected: clean run, no errors

- [ ] **Step 3: Commit**

```bash
git add -A && git commit -m "feat: Complete reflection Proposer-Verifier pipeline" && git push
```
