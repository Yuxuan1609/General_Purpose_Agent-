# Known Issues — Layer Loop Defects

> 2026-06-24 审查发现：L1/L2/L3 多轮对话中的断点与逻辑漏洞。
> 重点排查思维链传递与工具结果返回值。
>
> **2026-06-24 修复进度**：#1 #2 #3 #4 #5 #6 #8 已修复（见各条 ✅）。#7 经确认保持原状（已知限制）。

---

## 1. 决策树被 threading.local 割裂 🔴

- **位置**: `core/tools/downward_comm_tool.py:139` + `core/round_tree.py:62`
- **现象**: `downward_comm_tool` 的 handler 把 `downstream.query()` 放进 `threading.Thread` 执行（为了 timeout 控制），但 `round_tree` 的节点栈是 `threading.local()`。
- **执行流**:
  ```
  T0(主线程): L1Manager.query → push(l1_node) → T0栈=[l1_node]
    L1Agent.decide → l1_query handler → spawn T1, join
  T1: L2Manager.query → push(l2_node) → T1栈=[l2_node]  ← 新线程，独立栈
    L2Agent.decide → l2_query handler → spawn T2, join
  T2: L3Manager.query → push(l3_node) → T2栈=[l3_node]
    pop → T2栈=[] → current_node()=None → 不 append
  T1: pop → T1栈=[] → 不 append
  T0: pop → T0栈=[] → get_round_history().push(l1_node)
  ```
- **结果**: `l1_node.children` 永远为空。决策树只含 L1 根节点，L2/L3 节点全部丢失。
- **影响**:
  - `monitor.decision_tree()` 展示空树
  - `_fill_observations_llm` 无法从树中提取 L2/L3 observations → 学习记录降级

## 2. L2Manager 缺少 parent.children.append 🔴

- **位置**: `core/layers/l2/manager.py:410` vs `core/layers/l3/manager.py:299-302`
- **现象**: L3Manager 做了：
  ```python
  pop_node()
  parent = current_node()
  if parent is not None:
      parent.children.append(l3_node)
  ```
  L2Manager 只做了 `pop_node()`，**没有** append 到 parent。
- **结果**: 即使问题 1 的线程问题修复，L2 节点仍然是孤儿——L1 根节点下直接挂 L3，跳过 L2。

## 3. capture tool 与 executable tool 同轮发出时，executable 被静默丢弃 🟡

- **位置**: `core/layers/base.py:214-230`
- **代码**:
  ```python
  for tc in resp.tool_calls:
      if capture_tools and tc.function.name in capture_tools:
          return parsed  # ← 立即返回，后续不再处理
      executable_calls.append(tc)
  ```
- **场景**: LLM 同一轮发出 `[l1_query, l1_report]`：
  - `l1_query` 先进入 `executable_calls`
  - `l1_report` 命中 capture → **立即 return**
  - `l1_query` **永远不会被执行**，查询结果丢失
- **影响**: LLM 期望"先查再报"，实际只报了，查询被吞掉。

## 4. 下层 reasoning 不向上传递 🟡

- **位置**: `core/tools/downward_comm_tool.py:99-103`
- **代码**:
  ```python
  def _extract_reply(notify: dict, layer_name: str) -> str:
      layer_notify = notify.get(layer_name, {})
      return layer_notify.get("reply", "") or layer_notify.get("result", "")
  ```
- **现象**: 只提取 `reply`/`result`，**丢弃 `reasoning`**。
- **影响**: L1 看不到 L2 的推理过程，L2 看不到 L3 的推理过程。思维链在层间断裂——上层只能拿到结论文本，无法理解下层"为什么"得出该结论。

## 5. downward 路径下 async 任务无提示消息 🟡

- **位置**: `core/layers/base.py:295-397`
- **现象**: `has_downward=True` 时，async 工具被提交到 TaskRunner（line 281），返回 `{"task_id":..., "status":"running"}` 作为 tool result。但 "Pending async tasks" 的 system 提示（line 395-397）只在 `async_calls` 列表非空时才添加，而 `async_calls` 只在 `if not has_downward` 分支里填充。
- **结果**: downward 路径下 `async_calls` 始终为 `[]` → **LLM 收不到"请用 collect_tasks 收割"的系统提醒**，容易遗忘后台任务。

## 6. L3Agent.decide 缺少 fallback 🟢

- **位置**: `core/layers/l3/manager.py:193-195` vs L1 `l0_5_1/manager.py:231-235`、L2 `l2/manager.py:302-306`
- **现象**: L1 和 L2 都有：
  ```python
  if not result.get("done"):
      raw = result.get("_raw") or result.get("result") or ...
      if raw:
          return {"done": True, "result": str(raw), ...}
  return result
  ```
  L3 直接 `return result`。
- **影响**: 当 capture tool 参数 JSON 解析失败时，`_call_llm` 返回 `{"_raw":..., "_capture_tool":...}`（无 `done` 字段）。L3 不做兜底 → `result.get("result","")` 返回空字符串，L3Manager 拿到空结果。

## 7. 纯文本回复时 reasoning 丢失 🟢

- **位置**: `core/layers/base.py:407-408`
- **代码**:
  ```python
  if capture_tools or schema is None:
      return {"done": True, "reply": text, "result": text, "reasoning": "", "_raw": text}
  ```
- **现象**: LLM 没调 capture tool 而是直接输出文本时，`reasoning` 被设为空字符串。
- **影响**: LLM 的思考过程全部塞进 `result`/`reply`，`reasoning` 字段为空 → 上层和记录系统拿不到结构化的推理链。

## 8. _drain_pending_async 重复调用 🟢

- **位置**: `core/layers/base.py:220` 和 `:228`
- **现象**: capture tool 命中时，line 220 调一次 drain；如果 JSON 解析失败，line 228 又调一次。
- **影响**: 无害但冗余。

---

## 汇总

| # | 严重度 | 问题 | 位置 | 状态 |
|---|--------|------|------|------|
| 1 | 🔴 | 决策树被 threading.local 割裂 | downward_comm_tool:139 + round_tree:62 | ✅ 改纯同步 |
| 2 | 🔴 | L2Manager 缺 parent.children.append | l2/manager.py:410 | ✅ 已加 append |
| 3 | 🟡 | capture tool 同轮吞掉 executable tool | base.py:214-230 | ✅ 延迟 capture |
| 4 | 🟡 | 下层 reasoning 不向上传递 | downward_comm_tool:99-103 | ✅ 提取 reasoning |
| 5 | 🟡 | downward 路径 async 无提示 | base.py:295-397 | ✅ 统一计数器 |
| 6 | 🟢 | L3Agent 缺 done fallback | l3/manager.py:193-195 | ✅ 已加兜底 |
| 7 | 🟢 | 纯文本回复 reasoning 丢失 | base.py:407-408 | ⏸ 保持原状（已知限制） |
| 8 | 🟢 | drain 重复调用 | base.py:220,228 | ✅ 只调一次 |
