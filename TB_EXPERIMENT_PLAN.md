# Terminal-Bench 实验规划（cognitive-agent 学习/泛化）

承接 `TB_BASELINE_RESULTS.md`。目标：验证 cognitive-agent 的**学习是否能泛化**——在一组任务上 train（record_learning → 固化进 L1/L2/L3 + KB）后，能否提升**未见过**任务的通过率。

---

## 0. 通用方法论

### 实验状态隔离（关键）
每个 train 类实验前 **fork 一份完整学习状态**、实验后 **restore**，避免相互污染。
"完整学习状态" = **KB + L1 + L2 + L3 + domain + learning**，全在 `data/` 下；活存储是 SQLite `data/cognitive/{l1,l2,l3,domain}.db`（不是 `data/layers/*.json`，那是过时索引）。

工具：`tb/exp_state.sh`（全量 `data/` 快照，覆盖上述全部）
```bash
bash tb/exp_state.sh fork  <name>     # 实验前快照
bash tb/exp_state.sh restore <name>   # 实验后/失败回滚
bash tb/exp_state.sh list
```
> `setup_clean_kb.sh` 只重置过时 JSON 索引、**不动 `data/cognitive/*.db`**，不足以隔离实验——一律用 `exp_state.sh`。

### 并发与可靠性
- **train 阶段一律串行（并发=1）**：保证学习顺序可复现、干净归因（并行的跨进程写虽已被固化单飞锁缓解，实验仍要确定性）。
- **test/eval 阶段低并发（1–2）**：减少 docker-exec 争用（baseline 挂死的根因）；`tb_terminal.py` 已加 Python 侧看门狗兜底。
- token 预算不设限（已在模型服务侧处理）。

### 测量
- 小样本 + LLM 随机性 → **每个 eval 任务 before/after 各跑 2–3 次**取通过率，降方差。

### 术语（避免歧义，下文统一用）
- **round**：一次 `executor.execute(obs)` —— 观察终端 → 走完整 L1→L2→L3 认知链 → 出一个动作 → 重新观察。上限 `_MAX_ROUNDS=30`，落 `round_N.json`。**test/train 都有**。
- **turn**：某层 `_call_llm` 的一次**大模型回复**（可带多个 tool_calls）→ 工具执行 → 结果回灌 → 再问。日志 `turn X/30`。一个 round 内、每层各自有 turn 循环。
- **tool call**：单个工具调用（如一条 terminal 命令）；一个 turn 可发多个。
- 层级：**round ⊃ turn ⊃ tool call**。「`rounds=0`」= 连第一轮 `executor.execute` 都没收完（不是没调工具）。
- **repair round**（另一概念，**train-only**）：测试失败后的反馈/修复循环（`feedback_harness._MAX_REPAIRS=3`；`receive_test_results` 内 `_REPAIR_MAX_ROUNDS=15`/`_REFLECT_MAX_ROUNDS=5`）。test 模式整段跳过。

---

## Step 0 — 重跑 8 个"挂死"case（✅ 已完成，结论修正）
test 模式、并发 2、带看门狗复跑。**结果：8 个全 FAIL，看门狗触发 0 次。**

- 低并发下**没有任何单命令挂死 330s+** → 之前并发 3 的"无限挂死"是并发问题，已规避。
- 但 **6 个仍 `agent_timeout / rounds=0`**（agent 跑满预算、round 0 都没跑完），**2 个跑完测试没过**（polyglot-c-py、regex-chess = 真能力失败）。
- **推翻"8 个是基础设施挂死、修了就过"**：无一通过。详见 `TB_BASELINE_RESULTS.md` 修正版。

→ 真实 baseline = **18/32 = 56%**；14 个 FAIL 重新归类：**7 真能力失败 / 6 round-0 超时 / 1 parse_error**。
→ 超时根因（见 baseline 文档）：环境摩擦（缺 pip→apt→PEP668→多 GB 下载）+ agent 试错不收敛 + 慢命令，**不是无网/不可做**（容器有网）。

---

## Step 1 — 实验一：7 个能力失败做最简单的概念测试
对象（agent 跑完但测试没过的**真·能力失败**，含 Step 0 复跑确认的 polyglot-c-py / regex-chess）：
`conda-env-conflict-resolution overfull-hbox modernize-fortran-build mailman vul-flink polyglot-c-py regex-chess`

- **目的（最简单的概念验证）**：在 agent 已经"跑完但答错"的任务上，train 模式的 **repair loop（同任务内拿测试反馈修复，最多 3 轮）+ 学习**能否把 FAIL 转 PASS？这是验证学习/反馈机制**是否根本有用**的最低门槛，不涉及泛化。
- 对照组 = 已有 test-mode 失败结果。
- 串行跑；跑前 `exp_state.sh fork exp1_base`，跑后 restore。
- 记录：每个 case test→train 是否 FAIL→PASS、用了几轮 repair、record_learning 触发（`python -m core.learning_track`）。

---

## Step 2 — 实验二：timeout 能力的修复与评估
对象（Step 0 复跑确认的 **6 个 round-0 超时**）：
`cpp-compatibility classifier-debug write-compressor nginx-request-logging home-server-https circuit-fibsqrt`

- **背景**：这些不是"做不了"，而是 agent 把预算耗在**环境摩擦 + 试错不收敛 + 慢命令**上（如 classifier-debug 反复试 6 种装 torch 的写法、撞 PEP668、多 GB CUDA 下载），真正的任务还没开始就超时。
- **假设**：这正是学习能修的——把"该环境装包要 `apt install python3-pip` + `pip install --break-system-packages`""torch 装一次很久、别反复重试""失败时换策略而非换写法"等**可复用经验**固化后，agent 应能少走弯路、在预算内完成。
- **协议**：`exp_state.sh fork exp2_base` →（先在一两个超时 case 上 train，写入上述经验）→ 复跑这些 case（带学到的经验）→ 看是否由 timeout 转 完成/PASS、turn 数/耗时是否下降。
- **评估指标**：不仅看 PASS/FAIL，还看 **round-0 turn 数、是否进入 round 1、是否下派 L2/L3、重试次数**——衡量"效率修复"。

---

## Step 3 — 实验三：泛化（先一簇共享知识的任务）
**核心实验**（前两个实验确认机制有用后再做）。关键设计决策：

1. **不用 TB 的 4 大类当 domain**（类内任务几乎不共享可复用知识，如 Security 里 SQL注入/openssl/7z/Flink 互不相关 → 学到的卡太专属、迁移不动）。改为**挑一簇真正共享知识的相关任务**（如：git 恢复类 / python 版本冲突类 / web-server 配置类）。依据：agent 自发建的 "coding" 域卡（git reflog 恢复、shell 排查、pandas 版本）确实跨任务可复用——这才是泛化能成立的前提。
2. **TB 类别 ≠ agent 内部 domain**：agent 按涌现语义域组织学习；"筛簇"只是选任务，迁移可能跨 TB 类别（可作附加观测）。
3. cluster 来源：原始 241 道任务池（`~/tb-tasks/original-tasks`），按任务描述/技能聚类挑选；规模 train 6–10 / test 4–6（比 5/3 更出信号）。

**协议**：
```
exp_state.sh fork exp2_clean            # 干净基线快照
（A）eval test-split（纯 test 模式，无学习/无 repair）         → before 通过率
（B）train train-split（train 模式，串行，写入知识）
（C）eval test-split（纯 test 模式，带学到的 L1/L2/L3+KB）     → after 通过率
delta = after − before                  # 泛化效应
exp_state.sh restore exp2_clean         # 复位
```
每个 test 任务 before/after 各 2–3 次。

---

## Step 4 — 取决于实验三：扩数据 / 加难度
- 若有正向信号：扩大该 cluster（更多 train+test）、再加别的 cluster。
- baseline 通过率 56%（含 6 个 round-0 超时的提升空间）→ 从 241 池**加入更高难度 case** 避免天花板效应；挑"学了可能会"的中等偏难，别挑"学了也不会"的。
- 可把"扩到更大 cluster"提前并入 Step 3，一次把信号做扎实。

---

## 主要风险
| 风险 | 说明 | 缓解 |
|------|------|------|
| 类内知识不共享 | TB 大类太宽，迁移不动 | 用**共享知识 task cluster**而非大类 |
| 小样本 | 每簇 test 仅数个，1 个变化=大波动 | 多 trial + 扩样本（Step 3 提前） |
| LLM 随机性 | 同任务结果不稳定 | before/after 各 2–3 次 |
| 实验污染 | KB/L1/L2/L3 跨实验串扰 | 每次 `exp_state.sh` fork/restore |
| 终端 flake 复发 | 高并发再触发 docker-exec 卡顿 | train 串行 / eval 低并发 + 看门狗 |

---

## 状态
- [x] Step 0 — 重跑 8 个：完成，8/32 全 FAIL，基线修正为 18/32=56%
- [ ] Step 1 — 实验一：7 个能力失败的概念测试（repair/学习能否 FAIL→PASS）
- [ ] Step 2 — 实验二：6 个 round-0 超时的"效率修复"与评估
- [ ] Step 3 — 实验三：泛化（共享知识 cluster，待 Exp1/2 确认机制有用后）
- [ ] Step 4 — 扩数据 / 加难度
