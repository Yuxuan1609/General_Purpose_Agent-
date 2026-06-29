# Cognitive-Agent 学习/泛化实验报告（草稿）

> 整理日期：2026-06-29。本文汇总 Terminal-Bench 上 cognitive-agent 的学习与泛化实验：
> **Baseline → Exp1（同任务学习）→ Exp2（跨任务泛化/迁移）→ Exp1 调整实验（cohort retrain）**，
> 以及贯穿全程的基础设施发现与修复。供撰写正式报告参考。所有结论均附数据来源（`tb/runs/...`）。

---

## 0. 概述（一句话结论）

*结论：初步认为架构有效，在同domain下agent能较好的学习知识并产生知识的迁移能力并更好的解决学习前解决不了的困难问题*
*同时注意：因为资源问题实验数据集较小，目前的结论仅作为设计有效性验证的proof of concept，不是严谨的定论*

**实验setup**
  基于terminal bench 1 + 2 为基础的大题目集基础上筛选的小型测试数据集。一共进行了2组核心实验

| 实验 | 设计 | 关键结果 | 结论 |
|------|------|----------|------|
| **Baseline** | 32 任务按4个大类分成干净基线 | 23/32 PASS，9 个真能力 FAIL | 定出学习候选 cohort |
| **Exp1 同任务学习** | 9 个 FAIL 任务 train→eval | 1-shot: base 0/9 → learned 1/9；pass@3: base 3/9，learned **作废（域不匹配）** | 机制可跑通，但学习态检索失效 → 触发调整实验 |
| **Exp2 跨任务迁移（git 簇）** | 5个git相关任务，测试后划分3 个 PASS 任务 train → 2 个fail任务 held-out eval | held-out **2/2 翻转 FAIL→PASS**（baseline 0/2） | **正向迁移信号**（git-leak 有方差注意） |
| **Exp1 调整实验（retrain）** | 修复域不匹配+基础设施后，从干净种子重训 9 任务 | 域问题解决（22/23 卡落 terminal-bench）；learned eval 暴露**卡片混淆负转移** → 已修复 → 重跑中 | 揭示新失败模式：agent 把"记忆"当"环境" （提示词截断问题）|


**核心发现**：
1. 学习/反馈机制**能产生正向迁移**（Exp2 git：未见任务 FAIL→PASS）。
2. 学习要生效，**卡片必须落在可被检索到的 domain**（Exp1 原版因域不匹配部分失效，retrain 修复）。备注：这是一个已知的升级点详情见7.3
3. 学习也可能**负向**：learned agent 会把检索到的记忆卡片 id 误当成容器文件去全盘搜索，浪费预算甚至卡死终端（卡片混淆）——已通过提示词修复。
以上三条符合预期，此外还有一条超出预期的发现
4. *IMPORTANT* 没有预料到的情况，*单个任务*下目前agent能力不足以通过多轮尝试自主完成学习，但是exp2揭露通过同类的相关的简单任务下的学习经验反而很可能优化agent在困难任务下的表现
---

## 1. 方法论与实验环境

### 1.1 Agent 与运行框架
- **Agent**：cognitive-agent（分层认知架构 L0.5/L1/L2/L3 + KB），入口 `tb.agent.cognitive_agent:CognitiveAgent`。
- **模型**：deepseek-v4-flash（thinking=high，streaming，idle_timeout=60s）。
- **Bench**：Terminal-Bench，本地任务集 `~/tb-tasks/original-tasks`，每任务一个 Docker 容器。

### 1.2 运行模式（`tb/run_epoch.sh` / `tb/run.sh` / `tb/feedback_harness.py`）
- **train**：写学习（record_learning 等工具开放），每个 case 后等 consolidation 落卡到 L1/L2/L3。
- **bench**：只读评测（18 个写学习工具被 deny），用于 baseline 与 learned eval。
- **test**：纯单次评测（feedback loop 整段跳过）。
- **repair / pass@N**：`feedback_harness._MAX_REPAIRS` 默认 **3 → pass@4**；设 `TB_MAX_REPAIRS=2 → pass@3`。
  - train/bench 走 repair loop；**test 单次**。
  - 重要退化：若 agent 首次就跑满 deadline 超时（`feedback_harness.py:146`），跳过 repair 只反思一次 → 事实单次。故重型任务 train 常退化为单次。
  - 本报告：**baseline 与所有 eval 用 pass@3**（`TB_MAX_REPAIRS=2`）；**train 用默认 pass@4**（含 timeout 退化）。

### 1.3 时间预算
- **内部 deadline**（`TB_AGENT_DEADLINE_SEC`）= 任务 `max_agent_timeout_sec` × `TB_DEADLINE_MULT`；agent 在轮次边界自终止。
- **容器硬 cap** = `max(deadline+1200, 2400)`，到点由 `timeout` 杀容器（记 ERR）。
- `TB_DEADLINE_MULT`：eval/baseline=1.0；train 视实验取 1.0（git/cohort）或 1.5（build）。
- reaper：定期杀运行 >100min 的容器（兜底）。

### 1.4 实验状态隔离（`tb/exp_state.sh`）
每个 train 类实验前 fork 全量 `data/` 快照（KB+L1+L2+L3+domain+learning，活存储是 `data/cognitive/*.db`），实验后 restore，避免跨实验污染。关键快照见附录 B。

### 1.5 domain 机制（与 Exp1 失效直接相关）
- 学习卡片按 **domain** 组织；检索时按 `domains_hint` 过滤（`core/layers/l2/manager.py:376-377`：hint 命中的域才进检索）。
- 当前系统已统一把 terminal-bench 任务的学习落到 **`terminal-bench`** 域（agent 提示 + record_learning）。
- **Exp1 原版**早于此统一 → 卡片落在旧域（system / coding/polyglot / latex/pdflatex …），eval 时 hint=`terminal-bench` 检索不到 → 学习作废。这是触发"调整实验"的根因。

---

## 2. Baseline（Step 0，已完成）

- 原始 baseline 18/32 = 56%。对 14 个 FAIL 干净重测后，**5 个是 bug 导致的伪失败**（修复后翻盘），真实干净 baseline = **23/32 PASS**。
- 余下 **9 个真·能力 FAIL** 即 **Exp1 cohort**（学习候选）：
  `conda-env-conflict-resolution, overfull-hbox, mailman, broken-networking, polyglot-c-py, write-compressor, nginx-request-logging, circuit-fibsqrt, regex-chess`
- 超时根因（6 个 round-0 超时）：环境摩擦（缺 pip→apt→PEP668→多 GB 下载）+ agent 试错不收敛 + 慢命令，**非无网/不可做**（容器有网）。
- 来源：`tb/runs/exp_baseline/baseline14/results.txt`；详见 `TB_BASELINE_RESULTS.md`。

---

## 3. Exp1 — 同任务学习（9 任务 cohort）

**问题**：在 agent "已跑完但答错"的 9 个任务上，train（repair loop + 学习）能否把 FAIL 转 PASS？验证机制是否根本有用（不涉及泛化）。

### 3.1 train（3 轮，pass@4，1.0×）
来源 `tb/runs/exp1/r{1,2,3}/results.txt`：

| 任务 | r1 | r2 | r3 |
|------|----|----|----|
| conda | PASS | PASS | PASS |
| overfull-hbox | FAIL | FAIL | ERR |
| mailman | PASS | FAIL | FAIL |
| broken-networking | FAIL | FAIL | PASS |
| polyglot-c-py | PASS | PASS | PASS |
| write-compressor | FAIL | FAIL | PASS |
| nginx | PASS | PASS | FAIL |
| circuit-fibsqrt | FAIL | ERR | FAIL |
| regex-chess | FAIL | FAIL | FAIL |
| **轮通过** | **4/9** | **3/9** | **4/9** |

终态快照 `exp1_after_r3`（l1=7 l2=10 l3=0）。

### 3.2 eval
- **1-shot（pass@1，过苛）**：base **0/9** → learned **1/9**（仅 nginx）。来源 `tb/runs/exp1/eval/results.txt`。
- **pass@3 复评**（`tb/runs/exp1_cohort_pass3/`）：
  - **base pass@3 = 3/9**：conda / mailman / polyglot PASS；overfull / circuit ERR（重任务超时）；broken-net / write-comp / nginx / regex FAIL。
  - **learned pass@3 = 作废（域不匹配）**：`exp1_after_r3` 的 10 张卡全在旧域，eval 时 hint=`terminal-bench` 检索不到（0 命中），learned 测的是 base+方差而非迁移。部分结果（仅前 3 个）：conda FAIL / overfull PASS / mailman PASS。

### 3.3 Exp1 结论
- 机制可跑通（train 多轮能让部分任务 PASS）。
- 但**学习态在 eval 时检索失效（域不匹配）**，无法测出真实迁移 → 必须重训（见 §5 调整实验）。
- pass@3 比 1-shot 明显更强（base 0→3），说明"过苛的 pass@1"会低估能力。

---

## 4. Exp2 — 跨任务泛化 / 迁移（核心实验）

> 设计依据（`TB_EXPERIMENT_PLAN.md` Step 3）：不用 TB 大类当 domain（类内不共享知识），改挑**一簇真正共享知识的相关任务**。先试 build-from-source 簇，因环境噪声改用 **git 簇**（逻辑型、无重编译，更干净）。

### 4.1 build 簇（先行，已取消）
- build pass@3 baseline = **4/8**（`tb/runs/exp2_baseline/pass3/`）。
- build train（3 轮，1.5×）：r1=3/5、r2=2/5；学习累积 l1=2 l2=7（全 terminal-bench 子域）；快照 `exp2_after_train`。
- **build eval 取消**：held-out 全因环境噪声 ERR（tcc-qemu cap 超时、cython cap、sudo-llvm 未跑,我使用的ECS轻量级服务器进行实验，服务器资源配置较弱进一步扩大了这个问题），不可归因 → 转向 git 簇。

### 4.2 git 簇（干净迁移测试台）
5 个 git 任务，train 用 3 个 baseline-PASS 的、eval 用 2 个 baseline-FAIL 的 held-out。

**(1) git pass@3 baseline = 3/5**（`tb/runs/exp2_git/git_baseline/results.txt`，restore `exp1_seed` 无学习）：
- PASS：merge-diff-arc-agi-task、git-multibranch、sanitize-git-repo
- FAIL：**git-leak-recovery、configure-git-webserver**（= held-out 2，baseline **0/2**）

**(2) git train（3 轮，pass@4，1.0×）**（`tb/runs/git_train/r{1,2,3}/`，训练 merge-diff / multibranch / sanitize）：

| 任务 | r1 | r2 | r3 |
|------|----|----|----|
| merge-diff | FAIL(21m) | PASS(3m) | FAIL(21m) |
| git-multibranch | PASS(21m) | PASS(21m) | PASS(5m) |
| sanitize-git-repo | PASS(2.5m) | PASS(11m) | PASS(7.5m) |
| **轮通过** | **2/3** | **3/3** | **2/3** |

终态 `git_after_train`：l1=1 **l2=6**（全 terminal-bench 域），archive 15。

**(3) git eval（held-out 2，pass@3，restore `git_after_train`）**：
- **configure-git-webserver：FAIL → PASS（2m48s）** —— 干净翻转。来源 `tb/runs/git_eval/git_eval/results.txt`。
- **git-leak-recovery：FAIL → ERR（2400s cap）** —— 学习更强但更慢、撞 cap，未定论。
- **git-leak recheck（抬 cap 1800/3600，restore `git_after_train`）：PASS（4m16s，检索到 10 张 terminal-bench 卡）** —— 决定性。来源 `tb/runs/git_leak_recheck/`。

### 4.3 Exp2 结论
- **held-out 2/2 翻转 FAIL→PASS**（vs baseline 0/2）→ **正向迁移信号**。
- configure 是干净翻转（2m48s）；git-leak 翻转伴随**高方差**（同一份学习：一次 40min ERR、一次 4min PASS）→ 迁移真实，但 git-leak 单点归因不够铁，configure也具有潜在的方差风险。
- **未决**：给 learned eval 单独抬 cap（避免"learned 更彻底→更慢→撞 cap"误判）；做无学习对照在同 cap 下复测 git-leak 以净化归因。

---

## 5. Exp1 调整实验 —— cohort retrain（进行中）

**动机**：Exp1 learned 因域不匹配作废。两条路：(A) 把旧卡改域到 terminal-bench（多存储手术，风险高）；(B) **用当前修复后的系统从干净种子重训**（卡自然落 terminal-bench）。选 **B**。

### 5.1 协议
- restore `exp1_seed`（l1=0 l2=1）→ 3 轮 × 9 任务 train（pass@4，1.0×，串行）→ 每轮 drain pending 落卡 → 终态快照 `exp1_cohort_after_train`。
- 然后 learned pass@3 eval（restore 终态，bench/pass@3 ×9）vs base 3/9。

### 5.2 train 结果（`tb/runs/exp1_cohort_train/r{1,2,3}/`）

| 任务 | r1 | r2 | r3 |
|------|----|----|----|
| conda | FAIL | FAIL | PASS |
| overfull-hbox | ERR | PASS | FAIL |
| mailman | PASS | PASS | ERR |
| broken-networking | FAIL | FAIL | FAIL |
| polyglot-c-py | PASS | PASS | PASS |
| write-compressor | FAIL | ERR | ERR |
| nginx | FAIL | FAIL | FAIL |
| circuit-fibsqrt | PASS | PASS | FAIL |
| regex-chess | FAIL | FAIL | FAIL |
| **轮通过** | **3/9** | **4/9** | **2/9** |

总耗时 ≈ 10 小时（21:09→07:06，含重型 circuit/regex native 3600s）。

### 5.3 ★ 域问题已解决
终态 `exp1_cohort_after_train`：l1=1 **l2=23** l3=0，archive=46。L2 域分布：
`terminal-bench:11 + terminal-bench/circuit-fibsqrt:5 + terminal-bench/mailman3:2 + terminal-bench/fake-binaries:2 + terminal-bench/debug-methodology:1`
= **22/23 张卡落在 terminal-bench 域**（仅 latex/overfull-hbox:1、general:1 在外）→ learned eval 能检索到卡片了。

### 5.4 ★★ 关键发现：卡片混淆负转移
learned eval 启动后出现意外的**负转移**：learned agent 把检索到的记忆卡片当成了容器里的文件去搜索。

**机制链**（mailman，日志 `logs/tb/20260629_080221`）：
1. `query_domain("terminal-bench/mailman3")` 正常返回 `{"l2_cards":[{"id":"card_73bd84d9","content":"## Mailman3+Postfix 配置..."}]}`（检索成功，域对了）。
2. agent 误读 `id:"card_73bd84d9"` → 当成容器文件 → `read_file("/app/terminal-bench/mailman3/card_73bd84d9.md")`（不存在）。
3. 越陷越深：全盘搜索卡片 id + 认知工具名 → `grep("card_73bd84d9", path="/")`、`find / | xargs grep -l "query_domain|kb_query|knowledge"`（把自己工具列表里的工具名也当容器对象搜）。
4. 全盘 `grep /`、`find /` 是慢命令 → grep/read_file 10s 超时 → tmux session 被占住 → 后续命令 `{"error":""}`（空错误）。

**与并发楔死（§6.1）无关**：当时并行 turn=1，空错误不是并行工具互扰，而是单条全盘慢命令占住 session。这是独立新问题，只由 learned 检索行为触发（base 不检索卡片故不受影响）。

**train 阶段也有但较轻**：精确扫描 17 个 train 日志，**5/17 命中**（read_file 卡片当文件=5、terminal/grep 搜认知概念=9、grep path=/ =3），集中在 r2/r3（卡片多后），多数能自行恢复（mailman r2 / polyglot r3 仍 PASS）；不像 learned eval 用最终 23 张卡时深陷。

### 5.5 修复（提示词 + 工具返回，3 处）
1. `tb/agent/cognitive_agent.py` task_meta：新增"检索到的经验卡片"段落——卡片 id（card_xxx）仅是认知系统记忆标识、用于 l2_query/l1_query 引用，**不是容器文件路径**，切勿 read_file/grep/terminal 搜 card_xxx，直接用 content。
2. `core/tools/consolidation_tools.py` `_h_query_domain` 返回：JSON 加 `note` 字段说明同上。
3. 同文件 query_domain `description`：补一句 card id 是记忆标识非文件。

### 5.6 重跑验证（进行中）
restore `exp1_cohort_after_train` → bench/pass@3 ×9。当前（截至整理时）：
- conda → **PASS**（与 base 持平）；overfull-hbox 在跑。
- **修复已验证生效**：本次 eval 日志 `read_card=0 / 搜认知=0 / grep根=0`（卡片混淆消除）、楔死签名全 0。
- 预计总耗时 ≈ base pass@3 的 4h18m 量级（取决于重型任务是否撞 cap）。**最终 learned vs base(3/9) 对比待跑完补入。**

---

## 6. 基础设施发现与修复（贯穿全程）

| # | 问题 | 根因 | 修复 |
|---|------|------|------|
| 6.1 | **tmux 并发楔死** | terminal/read_file/grep 三工具共享同一 tmux session 但各持独立 `threading.Lock`；一个 turn 内并行调用（如 read_file+terminal）并发驱动 session → 交错 send-keys → session 损坏 → 空错误级联 + 10s 超时 + agent 用 tmux send-keys 绕路 → 撞 cap | `tb/session_holder.py` 加全局 `tmux_session_lock`，三工具改用同一把锁序列化跨工具 session 访问。验证：polyglot（曾 turn16 楔死）修复后 8min 干净 PASS、16 terminal+6 并行 turn 全 0 楔死 |
| 6.2 | **pager 卡死** | git/man 等默认 pager（less）在 tmux 内阻塞 agent | `tb/tools/tb_terminal.py` 首条命令守卫：`export PAGER=cat GIT_PAGER=cat` + `git config --global core.pager cat`；agent 启动提示同步说明 |
| 6.3 | **docker 地址池耗尽** | `--no-cleanup` 每任务残留 compose 网络，累积 29 个 → `all predefined address pools fully subnetted` → 新任务 4s 内 ERR | 各 launcher `_clean_all()` 加 `docker network prune -f` |
| 6.4 | **pending 泄漏污染 bench** | bench(无学习)跑批里 sub-agent 工具的 record 绕过主 agent 的 deny，核心是sub-agent类工具和主agent的工具是分别注册的手动修改难度高容易遗漏，pending 攒到 ≥5 自动 consolidate → 污染"无学习"基线 | `tb/run_epoch.sh` 逐 case：`[ "$MODE" != "train" ] && rm -f data/learning/pending/*.json`（bench/test 清，train 保留供 consolidate） |
| 6.5 | **卡片混淆负转移** | learned agent 把检索到的 card id 当容器文件全盘搜索（见 §5.4） | 提示词 + query_domain 返回/描述 3 处说明 card id 非文件 |

总结：主要基础设施方面的问题来自docker和服务器层面，提示词和项目本身的基础设施暴露出了一些问题但是相对较轻
---

## 7. 结论与未决问题

### 7.1 结论
1. **学习能产生正向跨任务迁移**：Exp2 git 簇 held-out **2/2 翻转 FAIL→PASS**（baseline 0/2），其中 configure 为干净翻转。
2. **可检索性是学习生效的前提**：Exp1 原版因卡片落在旧 domain、eval 检索不到而失效；retrain 把卡片统一落到 terminal-bench 域后检索恢复（22/23）。
3. **学习存在负向风险**：learned agent 会把"记忆卡片"误当"任务环境对象"全盘搜索（卡片混淆），浪费预算甚至卡死终端 → 已修复，重跑验证中。

### 7.2 未决问题 / 下一步
- **完成 retrain learned eval**：补 learned vs base(3/9) 对比，量化卡片混淆修复后的净迁移（正/负/持平）。
- **抬 cap 复测**：为 learned eval 单独抬 deadline/cap，净化"慢 vs 不会"的混淆。
- **git-leak 方差**：同 cap 下做无学习对照，净化迁移归因；多 seed 控方差。
- **build 簇**：环境噪声导致取消，若要纳入需更稳的算力/环境或更轻的 build 任务。

### 7.3 **已知主要drawback和升级点**
  1 l1_query个整个agent依赖domain系统，而后者目前还处于较原始的阶段尤其是domain的维护（目前的domain是索引式设计，domain由domain下的skill和knowledge card定义，这个设计带来的问题就是skill card的domain更新该怎么进行，类似rl中的explore and exploit问题）

  2 Scale-up和通用性：最初的agent项目设计目的是基于大量跨领域数据，系统性通过agent框架的“学习和训练”提升模型能力但是受限于我个人的时间和资源目前的实验实际未能完成这一点，只能*初步证明*框架在指定领域（git任务）下的学习是有效的。同样由于目前只关注了一个domain 多domain测试下agent的归纳和抽象能力没有被测试到。（理想情况是整个泛coding domain下python的知识可以迁移到Java，数据结构的知识可以迁移到实际代码设计）

  3 稳定性问题：大模型系统天生存在随机性，受限于资源限制暂时没有进行大量case+多轮测试验证稳定性尤其是exp2 （3个train + 2个test）。不过考虑到exp2的2个case全部反转+手动检查了Log确认有效返回了学习结果，作为proof of concept可以通过，但是将来需要进一步验证稳定性

  4 **自我迭代学习效果不显著**：预期中 agent 应能通过反复尝试同一任务进行主动的自我迭代学习——将失败经验自动沉淀为 L1 准则/L2 卡片/L3 技能，进而在下次重试时改进表现。但从 Exp1 retrain 的 3 轮 train 结果看（r1=3/9, r2=4/9, r3=2/9），多轮训练的通过率**没有持续上升趋势**——学习态的积累并未转化为可观测的迭代收益。分析原因：
     - 当前使用的模型（deepseek-v4-flash）在"从失败中提炼抽象经验"这一能力上存在瓶颈——容易学到的是一些表面的"what"（如某个命令正确写法），而非可迁移的"how"或"why"
     - 学习质量依赖 agent 自身的元认知能力，而 flash 级别模型这方面较弱
     - 两个潜在升级方向：(1) **引入强模型做"知识蒸馏"**——用更强的 teacher model（如 deepseek-v4-pro）分析 agent 失败轨迹、提炼经验写入 L1/L2/L3，弱 model 作为 student 受益于先验知识。实现相对简单。(2) **优化冷启动**——在种子知识中预写入高质量的学习策略（如"拆解复杂任务并逐步实现"、"失败后先分析根因再重试"、"识别失败模式而非记忆操作步骤"），让 agent 初始即具备结构化学习方法论。实现难度较高。最理想的方式是(1)+(2)组合
---

## 附录 A — 实验结果文件索引（`tb/runs/...`）
- Baseline：`exp_baseline/baseline14/results.txt`
- Exp1 train：`exp1/r{1,2,3}/results.txt`；1-shot eval：`exp1/eval/results.txt`
- Exp1 pass@3：`exp1_cohort_pass3/cohort_base/results.txt`（base 3/9）、`exp1_cohort_pass3/cohort_learned/results.txt`（旧/作废）；summary：`exp1_cohort_pass3/summary.txt`
- Exp2 build：`exp2_baseline/pass3/results.txt`、`exp2_p1/r{1,2,3}/results.txt`、`exp_cluster/cluster_build_git/results.txt`
- Exp2 git：`exp2_git/git_baseline/results.txt`（3/5）、`git_train/r{1,2,3}/results.txt`、`git_eval/git_eval/results.txt`、`git_leak_recheck/git_leak_recheck/results.txt`
- Exp1 retrain：`exp1_cohort_train/r{1,2,3}/results.txt`、`exp1_cohort_retrain/cohort_learned/results.txt`、summary `exp1_cohort_train/summary.txt`、`exp1_cohort_retrain/summary.txt`
- 共享锁验证：`polyglot_validate/validate/results.txt`

## 附录 B — 关键快照（`data_snapshots/`）
- `exp1_seed`（干净种子 l1=0 l2=1）、`exp1_after_r3`（Exp1 旧学习态，旧域）
- `git_after_train`（git 学习态 l1=1 l2=6，terminal-bench 域）
- `exp1_cohort_after_train`（retrain 终态 l1=1 l2=23，22/23 terminal-bench 域）、`exp1_cohort_train_start`

## 附录 C — 关键证据日志（打包于 `evidence_logs/`）
- **卡片混淆（修复前，learned mailman）**：`cardconfusion_mailman_l2.log`（源 `logs/tb/20260629_080221`）—— read_file 卡片当文件 + 全盘 grep/find + 空错误。
- **卡片混淆（修复后，learned eval）**：`FIXED_learned_eval_20260629_084314_l2.log`（read_card=0，混淆消除）。
- 注：更早的"并发楔死（修复前 polyglot）/共享锁验证 polyglot"日志已被日志轮转清除；相关结论见 §6.1 与 `TB_BASELINE_RESULTS.md`。

## 附录 D — 相关文档
`TB_BASELINE_RESULTS.md`（baseline + 各实验详细过程记录）、`TB_EXPERIMENT_PLAN.md`（实验规划/方法论）、`ARCHITECTURE.md`（认知架构）。
