# 架构评估 — chain_factory + ConsolidationContext 与 L2/L3 while-loop（#12 / #20）

> **状态**：评估稿，**不动代码**。列出问题、证据、选项、待决问题。决策由用户定。
> **基准**：以实际代码为准（MAINTAIN/README 部分条目已过时，已在文中标注）。

---

## Part A — #12：chain_factory + ConsolidationContext 架构

### A.1 现状（证据）

- 构造：`core/chain_factory.py:51-55` 创建 `ConsolidationContext(philosophy, knowledge, skill_layer, domain_registry, executor=None, knowledge_stores={...})`，`executor` 硬编码 `None`。
- 字段：`core/tools/consolidation_tools.py:10-24` `ConsolidationContext` dataclass，字段 `philosophy / knowledge / skill_layer / domain_registry / executor / knowledge_stores / pending_mods`，方法 `record_mod()` / `drain_mods()`。
- consolidation handler 对 `executor` 的使用：**零**。`consolidation_tools.py` 全部 handler（`_make_handler` 工厂 + `_h_query_domain` / `_h_deprecate_domain` / `_h_merge_domain` / `_h_create_domain`）只读 `ctx.philosophy/knowledge/skill_layer/domain_registry`，无一处读 `ctx.executor`（grep 仅命中 `consolidation_tools.py:22` 字段定义）。
- `executor` 的唯一消费者：`core/tools/record_learning_tool.py:138` `_dispatch_learning` → `executor = _consol_ctx.executor`，随后 `record_learning_tool.py:147-149` `if not executor: log.warning("no Executor in context, skipping"); return`。
- 自动学习触发链：`record_learning_tool.py:99` `_check_auto_trigger`（pending 满 5 条）→ `_dispatch_learning`。在 `build_default_chain` 默认产物上**必然在第 148 行 abort**。
- workaround：8+ 脚本在 `build_default_chain` 之后手动补 `chain._consol_ctx.executor = executor`：
  - `scripts/run_leduc_cognitive.py:157`、`scripts/run_douzero_llm.py:111`、`scripts/interactive_agent.py:53`、`scripts/run_learning_dryrun.py:176`、`scripts/test_consolidation_real.py:225`、`scripts/test_learning_e2e.py:187`、`scripts/test_learning_restructured.py:242`、`scripts/test_learning_interaction.py:226`。
- `pending_mods` 回流路径：Agent 在 `_call_llm` tool loop 内调 consolidation 工具 → handler `ctx.record_mod()`（`consolidation_tools.py:286`）→ Manager.notify() `ctx.drain_mods()`（`l2/manager.py:537`、`l3/manager.py:337`、`l0_5_1/manager.py:437`）→ mods 进 NOTIFY。dataclass 注释自承 "Immutable-ish"，但 `pending_mods` 为此设为可变。

### A.2 问题

1. **循环依赖 → 构造不完整**：`chain_factory` 构造 `ConsolidationContext` 时 `Executor` 尚不存在（Executor 需要 chain 作 `layer_root` + 主 LLM，而 chain_factory 只收 `auxiliary_llm`，且 chain 此刻未返回）。结果：`executor=None` 占位 + 8+ 脚本事后补。ConsolidationContext 的完整化跨两个构造阶段，契约不闭合，每条运行入口都得记得手补，漏补则自动学习静默失效。

2. **职责混杂**：`ConsolidationContext` 同时承载三类不相关依赖：
   - (a) consolidation 工具 handler 的 DI（philosophy/knowledge/skill_layer/domain_registry）
   - (b) 跨轮修改收集 side-channel（`pending_mods` + `record_mod`/`drain_mods`，被三层 Manager notify() drain）
   - (c) 自动学习的 executor 引用（仅 `record_learning_tool._dispatch_learning` 用）
   一个 dataclass 承担三种职责，构造来源也分两处（chain_factory + 脚本）。

3. **pending_mods 绕过 LayerMessage 协议（A2）**：修改不经过 capture_tool 输出，也不经 Comm/LayerMessage 信封，靠共享可变状态回流。Manager.notify() 的 mods 来源是 tool handler 的 side-effect，而非 Agent 显式输出。这使得"一次 decide 里 Agent 实际改了什么"只能从 side-channel 观察，capture_tool 的 `result`/`reply` 与真实修改脱节。

### A.3 选项（不决策，仅列举）

| 选项 | 核心思路 | 影响面 | 注意 |
|------|---------|--------|------|
| **A1 最小：补 executor 注入闭环** | 在 chain_factory 提供一个"事后绑定 executor"的显式步骤（或接受 main_llm/executor 工厂），消除 8 处手补 boilerplate。ConsolidationContext 结构不动。 | 小（chain_factory + 脚本） | 不解决职责混杂与 side-channel；自动学习断链修了，其余结构问题留待后续 |
| **A2 中等：拆 ConsolidationContext 职责** | 把 (a)工具DI / (b)pending_mods / (c)auto-learning executor 拆成独立对象。consolidation 工具只拿 store 引用；mod 收集器独立；executor 不进 ConsolidationContext。 | 中（consolidation_tools + 三层 Manager notify + record_learning_tool） | 需先出 spec；side-channel 是否同时改走 capture_tool 输出需单独决定 |
| **A3 大：mod 走 capture_tool 输出，废 side-channel** | Agent 通过 capture_tool 显式输出 modifications（与 consolidation 工具调用合并或替代），Manager 从 decide 结果取 mods，不再 drain `pending_mods`。 | 大（三层 Agent.decide + Manager + consolidation_tools） | 与 A2 正交可叠加；改变 consolidation 工具的语义（从"执行即记录"变为"Agent 显式汇总"）；需评估与 A2 的取舍 |
| **A4 暂不动，只补文档/注释** | 保留现状，在 chain_factory 与 ConsolidationContext 标注已知缺口与手补契约。 | 极小 | 不消除脚本 boilerplate，仅降低误解风险 |

### A.4 待决问题

1. `executor` 是否应留在 `ConsolidationContext` 内？还是 auto-learning 该走单独的上下文/工厂？（A1 保留，A2 拆出）
2. `pending_mods` side-channel 是否要改走 capture_tool 显式输出（A3）？还是保留 side-channel 只拆职责（A2）？
3. 8 个脚本的 `chain._consol_ctx.executor = executor` 手补，是否本轮就用 A1 统一消除？

---

## Part B — #20：L2/L3 Manager while-loop 语义

### B.1 现状（证据）

| Manager | 外层 while | 证据 |
|---|---|---|
| L0_5_1Manager | ✅ 有 | `l0_5_1/manager.py:288` `for round_idx in range(1, self.max_rounds+1)`，检查 `result.get("done")`，l1_query(done=false) 回灌 L2 结果再 decide，l1_report(done=true) 退出 |
| L2Manager | ❌ 无 | `l2/manager.py:433` 单次 `decide()`，之后 `for q in queries_to_L3`（`l2/manager.py:457`）仅透传，**不再回 decide** |
| L3Manager | ❌ 无 | `l3/manager.py:311` 单次 `decide()`，无循环 |

- capture_tool 语义：`l2_query`/`l3_continue` 的 `done=false` 本意是"未完成、需继续"；`l2_report`/`l3_report` 的 `done=true` 是"完成、向上汇报"（`l2/manager.py:34-80`、`l3/manager.py:31-62`）。
- L3 连带：`l3/manager.py:211` 在 `L3Agent.decide()` 内把 `not done` 直接 coerce 成 `done=True` 返回 raw —— `l3_continue` 语义被废。
- L2 连带 bug：`l2/manager.py:442-446` 在 `decide()` 返回后**立即**用 `result.get("reply","")` 设定 `_l2_notify.reply`，而 `queries_to_L3` 的 L3 调度在 `l2/manager.py:457` **之后**才发生。即 L2 选 l2_query（无 reply）→ 最终 reply 恒为 ""；L3 结果只进 `_l3_children`（`l2/manager.py:478-485`）但 L2 永不基于 L3 结果再 decide 出 l2_report。`context.l3_results` 恒为 `[]`（`l2/manager.py:429`）。实际可用路径只剩"L2 直接 l2_report 不问 L3"。
- `_call_llm` 内 `MAX_TOOL_TURNS=5` 是**单次 decide 内**的多轮 tool call，**非** Manager 级重入循环，不能替代后者。
- 文档偏差：`MAINTAIN.md:233` 称 `L2Manager.query` 为 "while 循环 + decide()"，与实际不符。`README.md:22` 称"每层 Manager 驱动 Agent while-loop 决策循环"，仅 L1 成立。

### B.2 语义歧义（需先明确，再决定改法）

1. **l2_query 的"继续"语义**：Agent 调 l2_query 下发 N 个 queries_to_L3 后，期望 Manager
   - (a) 收完 L3 结果后**回 decide** 让 L2 综合 L3 结果再决定 l2_query 还是 l2_report？（L1 模式）
   - (b) 还是 l2_query 只能调一次，L2 应在单次 decide 里同时给出 reply 与 queries（reply 不依赖 L3 结果）？
   现状是 (b) 的实现但 capture_tool 语义暗示 (a)。

2. **l3_continue 的"继续"语义**：Agent 调 l3_continue 表示"还需思考/用工具"，期望 Manager
   - (a) 回 decide 让 L3 继续多轮（直到 l3_report 或 max_rounds）？
   - (b) 还是 l3_continue 仅作为单次 decide 内的 tool-call 信号，Manager 不重入？
   现状是 (b)（且被 coerce 成 done），capture_tool 语义暗示 (a)。

3. **max_rounds 策略**：`config.yaml:20-22` 有 `max_rounds_l1:5 / l2:3 / l3:3`。L2/L3 的 max_rounds 目前未被 query() 使用（无循环）。若引入 while 循环，这三个值即生效——是否沿用现值？还是 L2/L3 用不同上限？

4. **context_history 回灌**：L1 用 `self._l2_history`（`l0_5_1/manager.py:398`）跨轮回灌。L2 现有 `self._l3_history`（`l2/manager.py:390`）在 `_propagate` 时写入 L3 的 context_history（`l2/manager.py:462`），但**不回灌 L2 自身 decide**。若引入 L2 while 循环，`l3_results` / `_l3_history` 需在下一轮 decide 前注入 context——注入哪个字段？

### B.3 选项（不决策，仅列举）

| 选项 | 核心思路 | 影响面 |
|------|---------|--------|
| **B1 对齐 L1 while 模式** | L2/L3 query() 加 `for round in range(max_rounds)`，done=false 时把下游结果回灌 context 再 decide，done=true 或 max_rounds 退出。L2 修后 reply 基于 L3 结果生成；L3 修后 l3_continue 生效。 | 中（`l2/manager.py` + `l3/manager.py` query()，含 context 回灌字段约定） |
| **B2 只修 L3** | 仅给 L3Manager 加 while（恢复 l3_continue），L2 维持单次 decide。 | 小（`l3/manager.py`） | L2 的 reply-before-L3 bug 仍在 |
| **B3 改 capture_tool 语义对齐代码** | 承认现状为设计：l2_query/l3_continue 的 done=false 仅作单次 decide 内信号，改 capture_tool 描述与 MAINTAIN/README 对齐，不引入 Manager while。 | 极小（文档+capture_tool 文案） | 放弃 L2 基于 L3 结果综合的能力；L2 reply 恒为单次 decide 产物 |
| **B4 重设计层间交互** | L2/L3 改为非循环的"一次 decide 完成全部"模型，queries_to_L3 的结果通过别的方式（如 L3 结果直接并入 L2 reply 文本）回流。 | 大 | 属架构变更，需独立 spec |

### B.4 待决问题

1. l2_query / l3_continue 的预期语义是 (a) 触发 Manager 重入 decide，还是 (b) 仅单次 decide 内信号？（决定走 B1 还是 B3）
2. 若走 B1，L2 while 循环里 L3 结果回灌到 `context.l3_results` 还是 `state.context_history`？
3. `max_rounds_l2:3 / l3:3` 是否沿用？L2 单次 decide 可下发多个 queries_to_L3，一轮即可能产生多个 L3 调用——"轮"的计数单位是 decide 次数还是 L3 调用次数？
4. L2 reply-before-L3 bug：无论选 B1/B3/B4，是否本轮至少把"reply 在 L3 执行前设定"这一明显与语义冲突的点修掉？

---

## 相关文件

| 文件 | 关联 |
|------|------|
| `core/chain_factory.py` | A：ConsolidationContext 构造 + executor=None |
| `core/tools/consolidation_tools.py` | A：ConsolidationContext 定义 + handler + record_mod |
| `core/tools/record_learning_tool.py` | A：唯一 executor 消费者（auto-learning） |
| `core/layers/l0_5_1/manager.py` | B：while-loop 参考实现 + drain_mods |
| `core/layers/l2/manager.py` | B：缺 while + reply-before-L3 + drain_mods |
| `core/layers/l3/manager.py` | B：缺 while + l3_continue coerce + drain_mods |
| `core/layers/base.py` | B：`_call_llm` MAX_TOOL_TURNS（单次内多轮） |
| `config.yaml` | B：`runtime.max_rounds_l1/l2/l3` |
| `MAINTAIN.md` | A/B：多处与实际不符（L2Manager while、get_tools_for_domain 上游） |

---

## 附：本次已修（#14，独立于本评估）

#14（consolidation 检测限制与 spec soft 限制脱钩）已按"代码对齐 spec（用 soft）"修完：
- `core/env/learning_env.py:199-204` 默认 `_l2_limit/_l3_limit` 改读 `config.yaml:consolidation.l*.limits.soft`
- 删除 `config.yaml:learning.l2_card_limit/l3_skill_limit` 两个死 key
- `tests/test_learning_env.py` 加 `TestConsolidationLimitSource`（3 测试）
- `MAINTAIN.md` LearningEnv 行 + changelog 同步
- 验证：`pytest tests/` 230 passed, 2 skipped

#18（`get_tools_for_domain` 零调用）按用户决定本轮不处理，留作后续升级点（`TODO_shortterm.md:33` 已有接线 idea）。
