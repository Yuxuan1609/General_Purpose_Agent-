# Terminal-Bench Test Baseline — Results & Analysis

> ⚠️ **本 baseline 已作废（2026-06-26）**：原始结果**以及** §0/§5 的"Step 0 复跑修正"都跑在一批后来才修复的 bug 之上——
> LLM 调用无超时挂死 ~10min、heredoc 经 tmux 写文件卡死、SearXNG web 搜索坏、反思无历史无法 record_learning、
> tb 的 asyncio 超时打不断阻塞 agent。这些会把"非能力失败"误记为失败（已实证 polyglot 由 ERR→PASS）。
> **下方所有数字与分类均不可信**，须用修复后的系统重跑干净的 32-case TEST baseline 作为新参照。修复详见 `DEBUG_JOURNAL.md`（2026-06-26）。

---

## ★ 干净 BASELINE（修复后重跑，2026-06-26）— 当前唯一有效参照

**Mode:** `TB_PHASE=test`（无学习 / 1-shot）·**串行**（避免并发 docker-exec 抖动）·每 case 内部 deadline + CAP·reaper 兜底
**Source:** `tb/runs/exp_baseline/baseline14/results.txt`（14 个原 FAIL 重测）；18 个原 PASS 顺延未重测
**全程 0 挂死 / 0 看门狗触发** —— 修复（LLM streaming+idle timeout、write_file、conv_history、tavily、内部 deadline）全部生效。

### 重测 14 个原 FAIL → **5 PASS / 9 FAIL**

**5 个翻盘 → PASS（原"失败"实为 bug 造成，占 36%）：**
| task | 备注 |
|------|------|
| modernize-fortran-build | 原挂死类 |
| vul-flink | 原判"真·能力 877K tok"，hard/security，现 1-shot PASS |
| cpp-compatibility | 原挂死类（~11min PASS）|
| classifier-debug | 原挂死类（~15min PASS）|
| home-server-https | 原挂死类 |

### ★ 9 个真·能力 FAIL = **Exp1 cohort（学习候选）**
| # | task | 备注 |
|---|------|------|
| 1 | conda-env-conflict-resolution | 跑完，测试没过 |
| 2 | overfull-hbox | 跑完，测试没过 |
| 3 | mailman | 跑完，测试没过 |
| 4 | broken-networking | 跑完，测试没过 |
| 5 | polyglot-c-py | **现为干净 FAIL（2min，不再 heredoc 挂死 ERR）**——write_file 修复后变诚实 1-shot 失败 |
| 6 | write-compressor | 跑完（~20min），测试没过 |
| 7 | nginx-request-logging | 跑完，测试没过 |
| 8 | circuit-fibsqrt | 跑满 3600s deadline，没过 |
| 9 | regex-chess | 跑满 3600s deadline，没过 |

### 全量干净 baseline = **23 / 32 PASS**（18 原 PASS 顺延 + 5 翻盘；9 真 FAIL）
> 注：18 个原 PASS 在旧 harness 下通过，未重测；修复只去挂死/不改通过行为，故按 PASS 顺延。如需严格可补测这 18 个。

**结论：原 baseline 把 5 个 bug 造成的"失败"误记为能力失败。干净后真能力失败仅 9 个 → Exp1 就练这 9 个。**

### 📌 待办（TODO）：Exp1 cohort 的 pass@3 复评（之后补，**不用重训**）
> 背景：Exp1 eval 只跑了 **1-shot（pass@1）= 1/9（仅 nginx）**，太苛刻。改用 pass@3 复评一遍看真实迁移信号。**train 不用重跑**——直接读已有训练快照。
>
> **9 个 cohort 任务**：conda-env-conflict-resolution、overfull-hbox、mailman、broken-networking、polyglot-c-py、write-compressor、nginx-request-logging、circuit-fibsqrt、regex-chess
>
> 跑两组（都 `TB_PHASE=bench`、`TB_MAX_REPAIRS=2`(=pass@3)、1.0× deadline、串行）：
> 1. **基础 pass@3**（无学习）：`restore exp1_seed` → bench/pass@3 on 9 → 得 pass@3 floor（对比 1-shot 的 baseline 0/9）
> 2. **带学习 pass@3**：`restore exp1_after_r3`（已训练态 l1=7 l2=10 l3=0，**直接读快照、不重训**）→ bench/pass@3 on 9 → 对比 (1) 看迁移（vs 1-shot eval 的 1/9）
>
> 实现：照搬 `tb/run_git_baseline.sh` / `tb/run_git_eval.sh` 模板，换快照名 + 任务列表即可。**等当前 git 实验跑完再做**（串行约束，不能并跑）。
>
> **⚠️ 更新（2026-06-28，已跑一轮但 LEARNED 作废）**：
> - **BASE pass@3 = 3/9 有效**（conda/mailman/polyglot PASS；overfull/circuit ERR=重任务超时；broken-net/write-comp/nginx/regex FAIL）vs 1-shot 0/9 → pass@3 明显更强。
> - **LEARNED 作废（域不匹配）**：`exp1_after_r3` 的 10 张卡全在**旧域**（system / coding/polyglot / latex/pdflatex … **无一在 terminal-bench**，Exp1 早于域统一修复）；而 learned agent 的 l1_query 都 hint `["terminal-bench"]`，检索按 domains_hint 过滤（`core/layers/l2/manager.py:376-377` 只搜 hint 域）→ **0 命中、学习根本没被用上**。实证：conda 查 3 次 0 命中、有张 latex 卡完美对口 overfull 却因域错过。→ conda base-PASS→learned-FAIL = **纯方差，非学习有害**。已于 16:50 停掉（base 数据保留）。
> - **重排修法（之后，与 git-leak recheck 之后一起排）**：① 把 `exp1_after_r3` 卡**改域到 terminal-bench**（`update l2_cards set domain='terminal-bench/'||domain`，l1 同理）→ 存 `exp1_after_r3_td`；验证 hint `terminal-bench` 能前缀命中（git 卡即如此命中）。② 先把 pending-leak 永久修法（per-case bench `rm pending`）加进 `run_epoch.sh`。③ 重跑**整个 cohort（base+learned）** with 改域快照 → 干净对比 vs 1-shot 0/9、1/9。

### 📌 待办（TODO）：带学习 eval 的"更彻底→更慢→撞 cap"问题 → 考虑拉长测试时间
> 观察（git eval, 2026-06-28）：held-out `git-leak-recovery` 在 **baseline(无学习)=干净 FAIL（22min，远低于 40min cap）**，但 **eval(带学习) 明显更慢（>32min）**——`l1_query` 检索卡 + 更细致的 git 取证让 agent 更彻底但更慢，3 次 pass@3 attempt 磨到逼近/撞 40min cap → **可能变 ERR**。
>
> **问题**：`baseline-FAIL vs eval-ERR` **不是干净对照**（ERR=超时，含糊，无法判断学习到底帮没帮）。
>
> **待办**：给**带学习的 eval**（git eval 重测 + cohort learned pass@3）**单独抬 cap/deadline**（如 `TB_DEADLINE_MULT=1.5~2`、cap 3600~5400s），让它跑完 pass@3 收敛成干净 FAIL/PASS，再与 baseline 公平对照。规则：若某任务 baseline=FAIL 而 eval=ERR，先判 **inconclusive**。
> 学习成果快照已存：`git_after_train`（l1=1 l2=6，pending=0）+ 每轮 `git_train_after_r{1,2,3}`。

### 📌 待办（TODO）：修 bench 模式"无学习"却仍写卡的泄漏（2 个候选路径）
> 症状：bench(无学习) 跑批（build baseline / git baseline / cohort base）里，主 agent 的 `record_learning` 已被 tool-deny，但仍攒出 ≥5 条 pending → 后台 `consolidate_runner` 自动 consolidate → 写 L2/L1 卡（cohort base 实证 2026-06-28：5 pending → 4 张 terminal-bench 卡 @13:50 本地；幸而多在任务结局之后，污染有限）。说明 **tool 级封禁不够，bench gate 没传到子作用域**。
>
> **2 个候选根因路径（之后排查/排除）**：
> 1. **sub-agent 类工具**（`kb_fill_gap`[`sync=False`：KB检查→外部搜索→提案]、`kb_query` 等，`toolset="core"`，经 `core/layers/base.py` 的 SubAgentLoop 实现）：spawn 的子 agent **单独注册工具集**，很可能**没继承父级 bench 的 `ctx.resolve()` deny** → 子 agent 里仍有 `record_learning`/`create_l2_card`/kb 写工具 active → 泄漏。修向：把父级 deny-set / bench gate **传播到子 agent 工具注册**。
> 2. **`activate_secondary_tools` 绕过**：上一轮 build 泄漏即此路（激活二级工具时未重过 `ctx.resolve()`）。已把 `activate_secondary_tools` 加入 deny-set —— **需验证彻底堵死**、无残留激活路径。
>
> 原则：bench/eval 的"只读"必须在 **tool 注册层 + 子作用域**统一执行，不能只靠主 agent 的 tool deny。
>
> **✅ 决定的修法（2026-06-28，避免改核心 sub-agent 代码、风险低）**：在 `run_epoch.sh` 逐 case 循环里，**仅 bench 模式**、每个 case 跑完后 `rm -f data/learning/pending/*.json` → pending 永不攒到 ≥5 → consolidate 自动触发不发生 → 泄漏被中和。**train 不动**（train 要留 pending 去 consolidate 成卡）。**待当前 cohort 跑完后再加**（不能编辑正在运行的 run_epoch.sh，bash 边读边执行会错乱）。上面 2 个根因方向仅作排查参考，**不做侵入式代码修改**。

---

## ★ Exp2（泛化）cohort — build-from-source 簇

**cluster-test**（`TB_PHASE=test`，1-shot，串行）→ 9 个 build 任务 = **6 FAIL / 3 PASS**
**Source:** `tb/runs/exp_cluster/cluster_build_git/results.txt`

| task | 源 | 难度 | 1-shot | 描述 |
|------|----|----|--------|------|
| build-cython-ext | TB2 | medium | ❌ | clone pyknotid 0.5.3，编译 Cython 扩展装到全局 Python，修 NumPy 2.3 兼容 |
| build-pmars | TB2 | medium | ✅ | 从 Debian 源码无 X11 编译 pMARS，装 /usr/local/bin |
| build-stp | tb1 | easy | ❌ | 从 /app/stp 编译 STP 定理证明器，`stp` 可当命令跑 |
| gcc-compiler-optimization | tb1 | medium | ✅ | 4 种 gcc flag 编译同一 C 程序量体积+运行时出 MD 表（偏测量/报告） |
| sudo-llvm-ir | tb1 | medium | ❌ | 改 sudo 构建配置 emit 完整 LLVM IR(-O0 -g)到 /app/binary.ll |
| build-tcc-qemu | tb1 | medium | ❌ | 编 TinyCC 打进 ISO 挂 QEMU cdrom，内核机里能用 tcc |
| build-initramfs-qemu | tb1 | medium | ❌ | 给预编译内核做 initramfs.cpio.gz，QEMU 启动进 root shell |
| compile-compcert | TB2 | medium | ❌ | 从源码构建 CompCert 3.13.1 验证编译器，ccomp 可用（2400s）|
| build-linux-kernel-qemu | tb1 | medium | ✅ | 从源码编 linux-6.9 加 printk 生成 ramfs QEMU 启动（1800s）|

**两条主题线：** ① QEMU/内核/启动族（共享 /app/linux-6.9 + initramfs + QEMU）；② 通用源码构建族（configure/make、修构建错、装产物）。

### ★ build pass@3 baseline（`TB_PHASE=bench`，TB_MAX_REPAIRS=2，净 seed，serial，2026-06-27）= **4/8 PASS**
| task | 1-shot | pass@3 |
|------|--------|--------|
| build-linux-kernel-qemu | ✅ | ✅ |
| build-pmars | ✅ | ✅ |
| build-stp | ❌ | ✅↑ |
| compile-compcert | ❌ | ✅↑ |
| build-tcc-qemu | ❌ | ❌ |
| build-cython-ext | ❌ | ❌ |
| build-initramfs-qemu | ❌ | ❌ |
| sudo-llvm-ir | ❌ | ❌ |

> feedback 把 stp、compcert 从 1-shot FAIL 救成 pass@3 PASS（+2）。Source: `tb/runs/exp2_baseline/pass3/`

### Exp2 train-test 拆分（已按 pass@3 修订 2026-06-27：compcert↔sudo-llvm 对调）
**原则：** TEST 全选 **pass@3-FAIL**（有头部空间、能体现学习翻盘）；TRAIN 含可解任务（产高质量学习卡）；两族不相交。compcert 已 pass@3 PASS、放 TEST 会天花板 → 调进 TRAIN；sudo-llvm pass@3 仍 FAIL → 调进 TEST。

- **TRAIN (5)：** build-linux-kernel-qemu、build-initramfs-qemu、build-stp、build-pmars、**compile-compcert**
- **TEST (3, 全 pass@3-FAIL)：** build-tcc-qemu、build-cython-ext、**sudo-llvm-ir**
- **剔除：** gcc-compiler-optimization（PASS + 离群"测量/报告"）

**迁移逻辑：** tcc-qemu ← kernel+initramfs（QEMU/内核族，最强）；cython-ext ← stp+pmars+compcert（cmake/configure/make/装产物/解编译错）；sudo-llvm ← compcert+pmars（configure-from-source、构建配置改写、出产物）。

---

## ★ Exp2 执行计划 / 跑批序列（2026-06-27）

**背景**：build 类任务**严重受环境/算力影响**（compcert 卡在 Coq 源码编译；kernel 这轮 agent 自己 `make clean` 整核重编 ~60min）——这些是环境噪声、非推理/学习差异，信噪比差。→ 引入 **git 簇作为更干净的泛化 cohort**（git 偏逻辑/推理，几乎不编译）。

**序列**（串行；2-4 步均 `TB_PHASE=bench` + `TB_MAX_REPAIRS=2`=pass@3 + 1.0× deadline + cap 兜底）：
1. **Phase-1 build train**（train，3 轮，**1.5× deadline**）— `tb/run_exp2_phase1.sh`
   - r1=3/5、r2=2/5 PASS；学习累积：**l1=2、l2=7（全 terminal-bench 子域）、l3=0**；终态快照 `exp2_after_train`
2. **build eval**（held-out 3 个，restore `exp2_after_train`，**带学习**）→ vs build pass@3 baseline 0/3，看翻盘
3. **git pass@3 baseline**（5 个 git，restore `exp1_seed`，**无学习**）→ git 控制底线 + 定 git train/test 划分
4. **git 实验**（train→eval，**据步骤2 结果再定**划分与执行）

> 步骤 2-3 由 `tb/run_exp2_eval_chain.sh` 自动串跑（等 Phase-1 PID 结束触发）；步骤 4 人工决策。

**git 簇现状**：1-shot = **2 PASS / 3 FAIL**（merge-diff-arc-agi-task ✅ / git-leak-recovery ✅ / git-multibranch ❌ / sanitize-git-repo ❌ / configure-git-webserver ❌ hard）。**pass@3 baseline 已完成 = 3/5**（见下方「Git 迁移实验结果」）。

---

## ★ Git 迁移实验结果（train→eval，2026-06-28）— 更干净的泛化 cohort

**方法**：5 个 git 任务（逻辑/推理类，几乎不编译，避开 build 的环境噪声）。`TB_PHASE=bench`、pass@3（`TB_MAX_REPAIRS=2`）、1.0× deadline、串行。pager 修复 + network prune 全程生效，**无 wedge / 无网络耗尽**。脚本：`tb/run_git_train.sh` / `run_git_eval.sh` / `run_git_chain.sh`。

### 1. git pass@3 baseline（无学习，restore `exp1_seed`）= **3/5**
| task | 1-shot | pass@3 | |
|---|---|---|---|
| merge-diff-arc-agi-task | PASS | **PASS** | = |
| git-multibranch | FAIL | **PASS** | ↑ |
| sanitize-git-repo | FAIL | **PASS** | ↑ |
| git-leak-recovery | PASS | **FAIL**（22min，干净）| ↓ 方差大 |
| configure-git-webserver | FAIL | **FAIL** | = hard |
> Source: `tb/runs/exp2_git/git_baseline/results.txt`。git-leak 在两次跑里 PASS↔FAIL 抖动 → 方差大、非干净"难"。

### 2. train-test 拆分（按 pass@3）
- **TRAIN（3 个 PASS = 学习源）**：merge-diff-arc-agi-task、git-multibranch、sanitize-git-repo
- **TEST/held-out（2 个 FAIL = baseline 0/2 floor）**：git-leak-recovery、configure-git-webserver

### 3. git TRAIN（3 轮，learning ON，1.0×，每轮 drain→consolidate）
| 轮 | train PASS | 学习态 |
|---|---|---|
| r1 | 2/3 | l1=1 l2=2 |
| r2 | **3/3** | l1=1 l2=6 |
| r3 | 2/3 | l1=1 l2=6 |

终态 **l1=1 l2=6 l3=0 archive=15**（L2 卡全落 terminal-bench 域），快照 `git_after_train`（+ 每轮 `git_train_after_r{1,2,3}`、`git_train_start`）。
L2 卡内容：Git API-Key/Token 脱敏、API密钥清理、**Nginx HTTPS+SSL**、**Git post-receive 部署**、**Git SSH 服务器搭建**、merge/bundle。

### 4. ★ git EVAL（held-out 2，restore `git_after_train`，带学习 pass@3）= **1/2 vs baseline 0/2**
| held-out | baseline | eval(带学习) | 判定 |
|---|---|---|---|
| **configure-git-webserver** | FAIL | **PASS（仅 2m48s）** | ✅ **干净翻盘 = 真迁移** |
| git-leak-recovery | FAIL | **ERR**(eval@2400cap) → **PASS**(recheck) | ✅ 复测翻盘（见下）|
> Source: `tb/runs/git_eval/git_eval/results.txt`。
> **git-leak 复测**（2026-06-28，`git_after_train` + **每 attempt 1800s / cap 3600s**）= **PASS（4m16s，检索到 10 张 terminal-bench 卡）**。⚠️ **方差极大**：同样的学习，eval(900s) 磨 40min 撞 cap ERR，recheck(1800s) 4min 就 PASS —— git-leak 结果高度受 agent 路径方差影响；且 recheck 每 attempt 时间(1800s)>baseline(900s)，故"翻盘归因于学习"是 **suggestive 非铁证**。结合 configure 的干净翻盘，git held-out 整体正向（**2/2 learned PASS vs baseline 0/2**）。

### 结论
- **≥1 个干净迁移翻盘**：configure-git-webserver `FAIL→PASS` 且仅 2m48s——学到的 **Nginx HTTPS / post-receive 部署 / git SSH 服务器** 卡正好对口，直接迁移到 held-out。pipeline（train→snapshot→eval 检索复用）**验证有效**；迁移机制实测确认（eval 任务 `l1_query` 检索到 terminal-bench git 卡）。
- git-leak-recovery：eval ERR → **复测(1800/3600) PASS（4m16s，检索到 10 张 terminal-bench 卡）** → held-out 整体 **2/2 learned PASS vs baseline 0/2**。但 git-leak **方差极大**（同样学习：40min-ERR ↔ 4min-PASS）且 recheck 每 attempt 时间>baseline，故其翻盘 **suggestive 非铁证**；**configure-git-webserver（2m48s 干净翻盘、同条件）是更硬证据**。
- git 簇比 build 簇干净（无环境超时），更适合迁移信号。
- **🔭 将来工作（有时间再做）**：强化归因——给 git-leak 跑一个**同 1800/3600 的无学习 baseline**（隔离"学习 vs 多给时间"）；多 seed 复测压方差；扩更多 held-out 任务；git-leak 这类高方差任务需多次重复取统计。

**今日关键基建修复**（影响以上所有 bench/eval 的有效性）：
- **bench/test 彻底封学习写**：`activate_secondary_tools` 并入封禁集——堵住"二级工具激活"后门（此前 record_learning 在 bench 漏写 5 张卡的根因；base 列表过滤有效但激活路径绕过）
- **域统一**：record_learning 域 `interaction`→`terminal-bench`；L1/L2 提示词域示例改 terminal-bench → 学习卡正确落 `terminal-bench/*` 子域、eval 可检索（已验证 6 张卡全落子域）
- **卡片渲染去掉误导性 `(相关度:0.00)`**（历史遗留 0 分会让 agent 忽略好卡；`l2/manager.py:_format_cards_with_relevance`）
- **run_epoch 支持 `TB_DEADLINE_MULT`**（train 用 1.5×；eval/baseline 用 1.0×）

---

**Date:** 2026-06-25
**Agent:** `tb.agent.cognitive_agent:CognitiveAgent`
**Mode:** `TB_PHASE=test`（无学习 / baseline）
**Concurrency:** 3（`TB_PARALLEL_N=3 bash tb/run.sh parallel <32 tasks>`）
**Dataset:** `~/tb-tasks/original-tasks`（32 道目标任务，镜像预构建 `--no-rebuild`）

---

## 0. 总览

| 指标 | 值 |
|------|----|
| 通过率 | **18 / 32 = 56.2%** |
| 其中 FAIL | 14 |
| └ 真·能力失败（agent 跑完、测试没过） | **7** |
| └ round-0 超时（环境摩擦+试错不收敛+慢命令） | **6** |
| └ parse_error（测试输出未解析） | 1 |

> **修正（Step 0 复跑后）**：本文档初版曾把 14 个 FAIL 中的 8 个判为"终端工具并发挂死（修了就能过）"。**这是错的**——把这 8 个在低并发+看门狗下复跑，**8 个全 FAIL、看门狗 0 触发**（即没有任何单命令挂死 330s+）。详见 §5。
> 真实结论：通过率就是 **56.2%**；其中 6 个是 agent **跑满预算、round 0 都没跑完**（`agent_timeout`），根因是把时间耗在环境摩擦/试错上而非任务本身做不了（§5）。Security 最强 7/8。

---

## 1. 逐 case 结果（按类别）

### Debugging — 4/8
| task | 结果 | 备注 |
|------|------|------|
| fix-pandas-version | ✅ PASS | |
| incompatible-python-fasttext | ✅ PASS | |
| swe-bench-fsspec | ✅ PASS | |
| swe-bench-astropy-1 | ✅ PASS | |
| conda-env-conflict-resolution | ❌ FAIL | 真·能力（agent 跑完，473K tok） |
| overfull-hbox | ❌ FAIL | 真·能力（170K tok） |
| cpp-compatibility | ❌ FAIL | **基础设施挂死**（agent_timeout / 0 round） |
| classifier-debug | ❌ FAIL | **基础设施挂死** |

### Software-Engineering — 3/8
| task | 结果 | 备注 |
|------|------|------|
| fix-git | ✅ PASS | |
| broken-python | ✅ PASS | |
| pypi-server | ✅ PASS | |
| modernize-fortran-build | ❌ FAIL | 真·能力（289K tok） |
| polyglot-c-py | ❌ FAIL | **基础设施挂死** |
| write-compressor | ❌ FAIL | **基础设施挂死** |
| regex-chess | ❌ FAIL | **基础设施挂死**（人工 kill，timeout 3600s） |
| circuit-fibsqrt | ❌ FAIL | **基础设施挂死**（人工 kill，timeout 3600s） |

### System-Administration — 4/8
| task | 结果 | 备注 |
|------|------|------|
| fix-permissions | ✅ PASS | |
| processing-pipeline | ✅ PASS | |
| log-summary | ✅ PASS | |
| configure-git-webserver | ✅ PASS | |
| mailman | ❌ FAIL | 真·能力（803K tok） |
| broken-networking | ❌ FAIL | parse_error（962K tok，agent 干了很多但测试输出未解析） |
| nginx-request-logging | ❌ FAIL | **基础设施挂死** |
| home-server-https | ❌ FAIL | **基础设施挂死** |

### Security — 7/8
| task | 结果 | 备注 |
|------|------|------|
| extract-safely | ✅ PASS | |
| git-workflow-hack | ✅ PASS | |
| openssl-selfsigned-cert | ✅ PASS | |
| sql-injection-attack | ✅ PASS | |
| vul-flask | ✅ PASS | |
| crack-7z-hash | ✅ PASS | |
| fix-code-vulnerability | ✅ PASS | |
| vul-flink | ❌ FAIL | 真·能力（877K tok） |

---

## 2. FAIL 初步甄别（并发 3 观测；**判定已被 §5 修正**）

> ⚠️ 本节是 baseline（并发 3）当时的初步分析，把 8 个判为"终端工具挂死/修了能过"。**Step 0 低并发复跑已推翻该判定**（8 个全 FAIL）——以 **§5** 为准。下表的 `failure_mode/rounds` 信号本身仍真实。

判别信号（per-trial `results.json` + `agent-logs/`）：

| task | failure_mode | rounds | summary.json | in_tok | 判定 |
|------|------|------|------|------|------|
| cpp-compatibility | agent_timeout | 0 | 无 | 0 | 挂死 |
| classifier-debug | agent_timeout | 0 | 无 | 0 | 挂死 |
| polyglot-c-py | agent_timeout | 0 | 无 | 0 | 挂死 |
| write-compressor | agent_timeout | 0 | 无 | 0 | 挂死 |
| nginx-request-logging | agent_timeout | 0 | 无 | 0 | 挂死 |
| home-server-https | agent_timeout | 0 | 无 | 0 | 挂死 |
| regex-chess / circuit-fibsqrt | (人工 kill) | 0 | 无 | 0 | 挂死 |
| conda-env-conflict-resolution | unset | 1 | 有 | 473K | 能力 |
| overfull-hbox | unset | 1 | 有 | 170K | 能力 |
| modernize-fortran-build | unset | 1 | 有 | 289K | 能力 |
| mailman | unset | 1 | 有 | 803K | 能力 |
| vul-flink | unset | 1 | 有 | 877K | 能力 |
| broken-networking | parse_error | 1 | 有 | 962K | parse_error |

**挂死共同特征**：`failure_mode=agent_timeout` + **0 round 完成** + **无 summary.json** + **0 token** → `perform_task` 卡在 round 0 从未完成，一直到任务自身的 agent timeout 才被判超时。

**根因（终端工具）**：`terminal` 工具（`tb/tools/tb_terminal.py` → TB `TmuxSession.send_keys(block=True)`）每条命令要做多次独立 `docker exec` 往返（打字 + `timeout Ns tmux wait done`）。并发负载下 docker 守护层卡顿：
1. 瞬时 exec 失败 → 工具返回 `{"error": ""}`（空消息，但命令其实已在容器里跑完——终端 pane 可证）。本次 baseline 共出现 **22 次** `{"error": ""}`、波及 **8 个 run**。
2. **`docker exec` API 调用本身挂死** → agent 永久阻塞。关键：`send_keys` 的 `max_timeout_sec=300` 只在**容器内**限 `tmux wait`，**拦不住宿主侧已挂死的 exec 调用**，Python 侧又**零超时** → 一直挂到任务的 agent timeout（900s~3600s）。

命令最密集的长任务（regex-chess 生成大量规则、circuit-fibsqrt 仿真等）中招最重。

---

## 3. 修复：terminal 工具加 Python 侧看门狗

`tb/tools/tb_terminal.py`（+39/-6）：
- 把 `session.send_keys(block=True)` 放进 **watchdog 线程**，`Event.wait(timeout + 30s)` 兜底——若 `send_keys` 自身挂住（卡死的 docker-exec），到点**返回错误而非永久阻塞**，把单条命令的最坏阻塞从"无限"收敛到 ~330s。
- 顺手修了**空错误**：`{"error": str(e) or repr(e) or type(e).__name__}`，不再给 agent 无意义的 `{"error": ""}`。

> 注：watchdog 超时后被放弃的线程仍可能在后台占用 session（Python 无法强杀线程），但此时任务多半已注定失败，属可接受权衡。

---

## 4. 建议

1. **跑批并发降到 1–2**（重/长任务尤其），减少 docker 守护争用——最直接缓解（`TB_PARALLEL_N=1` 或 `2`）。
2. **重跑这 8 个基础设施挂死的 case**（带看门狗 + 低并发）以得到真实能力数：
   `cpp-compatibility classifier-debug polyglot-c-py write-compressor nginx-request-logging home-server-https regex-chess circuit-fibsqrt`
3. broken-networking 的 parse_error 值得单看（agent 用了 962K token，可能是终端遗留状态导致测试输出格式异常）。

---

## 5. Step 0 复跑修正（重要）

把 §2 判为"挂死"的 8 个，在 **test 模式 / 并发 2 / 带看门狗** 下复跑：

| task | 结果 | failure_mode | rounds | 修正判定 |
|------|------|------|------|------|
| cpp-compatibility | FAIL | agent_timeout | 0 | round-0 超时 |
| classifier-debug | FAIL | agent_timeout | 0 | round-0 超时 |
| write-compressor | FAIL | agent_timeout | 0 | round-0 超时 |
| nginx-request-logging | FAIL | agent_timeout | 0 | round-0 超时 |
| home-server-https | FAIL | agent_timeout | 0 | round-0 超时 |
| circuit-fibsqrt | FAIL | agent_timeout | 0 | round-0 超时 |
| polyglot-c-py | FAIL | unset | 1 | **真能力失败**（跑完没过） |
| regex-chess | FAIL | unset | 1 | **真能力失败**（跑完没过） |

**8 个全 FAIL，看门狗触发 0 次。** → 推翻 §2 的"基础设施挂死、修了就过"。低并发下没有任何单命令挂死 330s+，说明**并发 3 的"无限挂死"是并发问题**（已规避），但这 6 个的真瓶颈是别的。

### 为什么 round 0 能吃掉整个预算（6 条叠加）
> 术语：**round** = 一次 `executor.execute`（观察终端→走 L1→L2→L3 认知链→出动作，`_MAX_ROUNDS=30`，test/train 都有）；**turn** = 某层 `_call_llm` 的一次大模型回复（可含多个 tool_calls）；**tool call** = 单条命令。层级 **round ⊃ turn ⊃ tool call**。`rounds=0` = 连第一轮 `executor.execute` 都没收完（不是没调工具）。

agent `perform_task` 每个 round 的 L1 `_call_llm` 最多 30 个 turn；这些任务**连 round 0 都没跑完**就超时。每 turn 实测 ~40–110s（健康应 ~10–20s），原因：
1. **慢命令主导**：大依赖安装（torch + 全套 CUDA，多 GB）、编译、apt——每条数十秒到数分钟。
2. **重试不收敛**：命令失败后换写法再试、不换策略（classifier-debug 试了 6 种装 torch 的写法）。
3. **残缺/多行命令卡 shell**：续行反斜杠、heredoc → shell 等输入吞掉后续命令。
4. **每 turn 的 LLM 越来越慢**：每轮把累积终端输出全量重发，上下文越滚越大（日志 11→42KB）。
5. **全程困在 L1、从不下派 L2/L3**（l2.log≈0）→ 无结构化推进、无任何 round 完成。
6. **空错误 flake 仍在**（并发 2 下 1–10 次/run）误导 agent 重试。

### 网络纠正（容器**有**网）
此前误判"容器无网"。实证：classifier-debug 里
`pip install --break-system-packages numpy torch` **成功下载并安装** torch 2.12.1 + numpy 2.5.0 + 整套 CUDA/nvidia 包（`Successfully installed`）。
所谓"装不上"的真相是**环境摩擦**：① 真缺 numpy/torch；② 容器连 pip 都没装（需 `apt-get install python3-pip`）；③ 撞 **PEP 668**（externally-managed，需 `--break-system-packages`）；④ torch+CUDA 多 GB 下载本就慢。这四道坎靠 agent 试错逐个发现，环境搭好时预算已耗尽，真正任务还没开始。

**结论**：这 6 个超时**不是"做不了"**，而是 agent 把预算耗在环境摩擦 + 试错不收敛上 → **正是学习可修复的目标**（见 `TB_EXPERIMENT_PLAN.md` 实验二）。看门狗仍有价值（防并发 3 的无限挂死），但治不了"任务本身要的时间/试错超预算"。

---

## § Exp1 cohort retrain + 卡片混淆负转移（2026-06-29）

### retrain 完成（域问题已解决）
从干净 `exp1_seed` 重训 3 轮 × 9 任务（共享锁修复后，无 session 并发楔死）。train = pass@4（默认 `_MAX_REPAIRS=3`，但 agent 首次跑满 deadline 会在 `feedback_harness.py:146` 跳过 repair 退化为单次反思）。三轮 train 通过率 r1=3/9、r2=4/9、r3=2/9。最终 `exp1_cohort_after_train`：l1=1 **l2=23** l3=0 archive=46。

**L2 域分布（关键）**：terminal-bench:11 + terminal-bench/circuit-fibsqrt:5 + terminal-bench/mailman3:2 + terminal-bench/fake-binaries:2 + terminal-bench/debug-methodology:1 = **22/23 张卡在 terminal-bench 域**（仅 latex/overfull-hbox:1、general:1 在外）。→ **域不匹配问题已解决**，learned eval（hint terminal-bench）能检索到卡片了。

### ★ 卡片混淆负转移（新发现，独立于共享锁问题）
learned eval（bench/pass@3）启动后出现**负转移污染**：learned agent 把检索到的记忆卡片当成了容器里的文件去搜索。

**机制链**（以 mailman 为例，log `logs/tb/20260629_080221`）：
1. agent 调 `query_domain("terminal-bench/mailman3")` → 正常返回 `{"l2_cards":[{"id":"card_73bd84d9","content":"## Mailman3+Postfix 配置..."}]}`（检索成功，域对了）
2. agent 误读 `id:"card_73bd84d9"` → 以为是容器文件 → `read_file("/app/terminal-bench/mailman3/card_73bd84d9.md")`（不存在）
3. 越陷越深：全盘搜索卡片 id + 认知工具名 → `grep("card_73bd84d9|card_c01a941a", path="/")`、`find / ... | xargs grep -l "query_domain|kb_query|knowledge"`（把自己工具列表里的 `kb_query`/`query_domain` 也当容器里的东西去搜）
4. 全盘 `grep /`、`find /` 是慢命令 → grep/read_file 工具 10s 超时 → tmux session 被占住 → 后续命令返回 `{"error":""}`（空错误）

**与共享锁修复无关**：当前 mailman `并行turn=1`（几乎无并行多工具），空错误**不是**并行 read_file+terminal 互相干扰导致，而是单条全盘慢命令占住 session。共享锁修复仍有效（train 20 个日志大多 0 楔死签名），这是**独立的新问题**，只由 learned 检索行为触发（base 不检索卡片故不受影响）。

**影响**：learned eval 被污染。已完成部分：conda 持平（PASS/PASS）、overfull（learned FAIL / base ERR 略好）、**mailman（base PASS → learned 困在搜卡片 turn 16，大概率退化 = 负转移）**。eval 中断于 mailman。

### 修复（提示词 + 工具返回，3 处）
1. **`tb/agent/cognitive_agent.py` task_meta**：新增"检索到的经验卡片"段落——卡片 id（card_xxx）仅是认知系统记忆标识、用于 l2_query/l1_query 引用，**不是容器文件路径**，切勿 read_file/grep/terminal 搜索 card_xxx，直接用 content。
2. **`core/tools/consolidation_tools.py` `_h_query_domain` 返回**：JSON 加 `note` 字段说明同上。
3. **`core/tools/consolidation_tools.py` query_domain description**：补一句 card id 是记忆标识非文件。

修复后重启 learned eval（restore `exp1_cohort_after_train` → bench/pass@3 ×9）验证负转移是否消除。

