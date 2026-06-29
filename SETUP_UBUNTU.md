# SETUP_UBUNTU.md — Windows→Ubuntu 移植 & Terminal-Bench 搭建说明

> 本文档由自动化搭建任务生成，记录从 `cognitive-agent-lite.zip` 解压后在 **Ubuntu 22.04** 上完成的全部改造、依赖安装、Terminal-Bench 镜像构建，以及**需要你确认的不确定点**。
> 标记 `❓需确认` 的地方是我没有自行做架构决策、留给你拍板的内容（遵循 AGENTS.md「禁止自行做架构/设计决策」）。

---

## 0. TL;DR 当前状态

| 项 | 状态 |
|----|------|
| 解压 + 梳理项目 | ✅ 完成 |
| 迁出只读 `/mnt`，落到可写持久路径 | ✅ `/home/admin/cognitive-agent` |
| Python 3.13（terminal-bench 要求 ≥3.12，脚本写死 `python3.13`） | ✅ 安装 + venv |
| Docker Engine + Compose | ✅ v29.6.0，daemon 运行中 |
| 项目核心依赖 + terminal-bench 0.2.18 + KB 向量栈（含 msgpack） | ✅ 装入 `.venv` |
| 单元测试 | ✅ **347 passed / 2 skipped / 0 failed**（KB 模型补齐后全绿） |
| Windows/WSL 写死路径修复 | ✅ `tb/run.sh`、`tb/run_baseline.sh` |
| Terminal-Bench 任务数据集（含全部 32 道目标任务） | ✅ `/home/admin/tb-tasks/original-tasks`（241 道） |
| 32 道任务 Docker 镜像预构建 | ✅ **32/32 全部构建成功，0 失败**（见 §5.3） |
| 端到端冒烟测试（`fix-git`, test 模式） | ✅ **PASS，Accuracy 100%（1/1 resolved）** |
| embeddinggemma 嵌入模型（1.2GB） | ✅ **已从 HF 下载装好**（`google/embeddinggemma-300m`，见 §6.1） |
| 卡牌游戏 legacy 依赖（rlcard/douzero/gradio） | ✅ 不装（已确认，见 §6.2） |
| 学习系统：record_learning track + auto_learning 独立固化 | ✅ **已实现并验证**（见 §6.5） |

**项目根目录：`/home/admin/cognitive-agent`**
**虚拟环境：`/home/admin/cognitive-agent/.venv`（Python 3.13.14）**
**任务数据集：`/home/admin/tb-tasks/original-tasks`**

---

## 1. 运行环境

- OS：Ubuntu 22.04.5 LTS（非 WSL，原生 Linux VM）
- 用户：`admin`（uid 1000），**有免密 sudo**
- 系统自带 Python：3.10.12（不满足 terminal-bench 的 ≥3.12，故另装 3.13）
- 磁盘：根分区 79G，余量充足

### 关键版本（已安装）
```
Python            3.13.14   (deadsnakes PPA, /usr/bin/python3.13)
Docker            29.6.0    + compose v5.2.0 + buildx v0.35.0
terminal-bench    0.2.18
torch             2.12.1+cpu
transformers      5.12.1
openai            2.44.0
numpy 2.5.0 / pandas 3.0.3 / pyyaml 6.0.3 / ddgs 9.14.4 / GitPython 3.1.50
scikit-learn 1.9.0 / safetensors 0.8.0
```
完整冻结清单见 `requirements-ubuntu.lock`（143 个包）。

---

## 2. 项目迁移

原项目是在 Windows + WSL 下建的，原始路径线索（来自脚本）：
- Windows 侧：`C:\Users\micha\PycharmProjects\cognitive-agent`（WSL 内为 `/mnt/c/Users/micha/...`）
- WSL 侧家目录：`/home/tonyyang`

本环境 `/mnt` 对 `admin` 只读，且 `/tmp` 可能被清理，故：
- 解压到 `/tmp/opencode/work/`，再 **`cp -a`** 到持久路径 **`/home/admin/cognitive-agent`**（保留 `.git`、`.env`、工作区改动）。

> ❓需确认：你希望项目最终落在哪个目录？我默认放在 `/home/admin/cognitive-agent`。如需别的位置告诉我。

---

## 3. 系统依赖安装（已完成）

```bash
# Python 3.13（deadsnakes）
sudo add-apt-repository -y ppa:deadsnakes/ppa
sudo apt-get install -y python3.13 python3.13-venv python3.13-dev

# 构建/常用工具
sudo apt-get install -y build-essential git tmux unzip jq curl

# Docker（官方源）
#   download.docker.com 的 docker-ce / cli / containerd / buildx / compose 插件
sudo systemctl enable --now docker
sudo usermod -aG docker admin   # 让 admin 免 sudo 用 docker
```

> ⚠️ docker 组对当前已存在的 shell 不生效，需**重新登录**或用 `sg docker -c '...'`。
> 重新登录后 `docker ps` 可直接用，无需 sudo。本次后台构建用的是 `sg docker -c`。

---

## 4. Python 依赖安装（已完成）

`pyproject.toml` 只声明了 `openai / pyyaml / duckduckgo_search`，**严重不全**。实际依赖通过扫描 import 补齐：

```bash
cd /home/admin/cognitive-agent
python3.13 -m venv .venv
.venv/bin/pip install --upgrade pip setuptools wheel

# 核心 + terminal-bench
.venv/bin/pip install "terminal-bench==0.2.18" "openai>=1.0.0" "pyyaml>=6.0" \
    ddgs "duckduckgo_search>=7.0.0" GitPython numpy pandas "pytest>=8.0.0"

# 知识库（KB）向量栈 —— vendored txtai 依赖（CPU 版 torch）
.venv/bin/pip install --extra-index-url https://download.pytorch.org/whl/cpu \
    torch transformers safetensors huggingface_hub scikit-learn
```

> ❓需确认：`pyproject.toml` 是否要我补全成完整依赖声明？目前我**没动它**（改 `pyproject` 属于项目元数据变更），只生成了 `requirements-ubuntu.lock` 作为快照。

---

## 5. Terminal-Bench 搭建（重点）

### 5.1 架构回顾（来自代码与 `docs/.../2026-06-23-tb-test-feedback.md`）
- `tb/runner.py`：monkey-patch `terminal_bench.Harness = FeedbackHarness` 后调用 TB 的 Typer CLI。
- `tb/feedback_harness.py`：重写 `_run_trial`，测试跑完、容器销毁前把 PASS/FAIL 反馈给 agent（FAIL 最多修 3 轮，train 模式才反思+`record_learning`）。
- `tb/agent/cognitive_agent.py`：`CognitiveAgent(BaseAgent)`，把认知链接到 TB。
- `tb/run.sh`：32 道任务（4 类 × 8 道），train=每类前 5，test=每类后 3。
- `TB_PHASE=train|test` 控制工具过滤（test 禁用 `record_learning/kb_add/kb_fill_gap`）。

### 5.2 数据集（已就位）
原脚本期望数据集在 `~/tb-tasks/original-tasks`。该目录正是 `laude-institute/terminal-bench` 仓库里的 **`original-tasks/`**（按名字一一对应）。

- 我先试了注册表数据集 `terminal-bench-core==0.1.1`（仅 80 道，**只覆盖 17/32**）；`head` 版本经 `tb datasets download` 下载会报 `FileNotFoundError: .../tasks`（**TB CLI 对 head 的已知 bug**）。
- 改为 **sparse 克隆官方仓库**取 `original-tasks/`（241 道，**覆盖 32/32**），拷到 `~/tb-tasks/original-tasks`。这与原项目布局完全一致。

```bash
git clone --depth 1 --filter=blob:none --sparse https://github.com/laude-institute/terminal-bench.git
# 仓库根有 original-tasks/（241 道），整目录拷到 ~/tb-tasks/original-tasks
```

### 5.3 镜像预构建（✅ 已完成 32/32，0 失败）
镜像命名是确定性的（已核对 TB 源码 `trial_handler.py`）：
```
prefix = "tb__<task_id>".replace(".", "-")
client_image_name = f"{prefix}__client"        # 例：tb__fix-git__client:latest
```
`tb tasks build` 产出的镜像名与 harness `--no-rebuild` 复用的名字**完全一致**，所以预构建有效。

新增脚本 **`tb/build_images.sh`**（可重跑、已存在则跳过）：
```bash
cd /home/admin/cognitive-agent
sg docker -c './tb/build_images.sh'                 # 构建全部 32 道
sg docker -c 'FORCE=1 ./tb/build_images.sh fix-git' # 强制重建某道
```
**查看后台进度：**
```bash
tail -f /home/admin/cognitive-agent/tb/build-logs/_MASTER.log   # 总进度
ls    /home/admin/cognitive-agent/tb/build-logs/                # 每道一个 <task>.log
sg docker -c 'docker images | grep tb__'                        # 已建镜像
```
> 构建小结（OK/SKIP/FAIL）会写到 `_MASTER.log` 末尾。FAIL 的任务看对应 `tb/build-logs/<task>.log`。
> 基础镜像 `ghcr.io/laude-institute/t-bench/{python-3-13,ubuntu-24-04}` 已预拉取。
> **本次结果：OK 31 / SKIP 1（fix-git 早先已建）/ FAIL 0 → 32 个镜像全部就位并按名校验通过。**

### 5.3.1 端到端冒烟测试（✅ 已验证）
跑了一道完整闭环验证移植可用：
```bash
set -a; source .env; set +a
bash tb/run.sh fix-git test     # TB_PHASE=test，单次测试、无修复循环
```
结果：harness 拉起预构建镜像（`--no-rebuild` 命中）→ CognitiveAgent 走认知链调用 DeepSeek → 解题 → 测试通过。
**Accuracy 100%，Resolved 1/1**，结果落在 `tb/runs/<ts>/results.json`。即 Docker + agent + DeepSeek + 测试 + 反馈 harness 全链路在 Ubuntu 上跑通。

### 5.4 如何跑基准（构建完成后）
```bash
cd /home/admin/cognitive-agent
set -a; source .env; set +a               # 载入 DEEPSEEK_API_KEY 等
bash tb/run.sh fix-git                     # 单任务（默认 train）
bash tb/run.sh fix-git test                # 单任务 test 模式
bash tb/run.sh train                       # 全部 20 道 train
bash tb/run.sh test                        # 全部 12 道 test
bash tb/run.sh parallel <task...>          # 并发（最多 4）
```
> 脚本已自动优先用 `.venv/bin/python`，无需手动 activate。

---

## 6. 已知缺口 & 需你确认的决策

### 6.1 ✅ embeddinggemma 嵌入模型 —— 已解决（从 HF 下载，1.2GB）
- `core/model_manager.py` 读本地 `<project>/embeddinggemma`，`core/knowledge/models.py` 还会 `AutoTokenizer.from_pretrained(embeddinggemma)`。
- **经过**：
  1. lite 包不含模型；你传的完整包 `/mnt/cognitive-agent.zip` 是**被截断的 zip**（主权重 `model.safetensors` = 0 字节、tokenizer 文件全缺），不可用，已弃。
  2. 改用你给的 HF token 直接 `snapshot_download("google/embeddinggemma-300m")` → 落到 `/home/admin/cognitive-agent/embeddinggemma/`（19 个文件，**`model.safetensors` 1.21GB**，tokenizer/config/Dense 层齐全，结构与原包一致）。
  3. 还差最后一个**未声明的依赖 `msgpack`**（vendored txtai 存盘序列化用）——已 `pip install msgpack`。
- **结果**：KB 全功能可用，单测 **21 fail → 0 fail，全套 347 passed / 2 skipped**。
- **决策（已定）**：用真实 embeddinggemma，未替换模型、未改 KB 降级代码。

> ⚠️ **安全**：你在对话里发的两个 HF token 我**只用于一次性下载、未落盘**（已确认 `~/.cache/huggingface` 无 token、磁盘无 token 串）。仍建议去 HF 后台**撤销/轮换**这两个 token。
>
> 复现（模型已就位，无需重下）：`PYTHONPATH=$PWD .venv/bin/python -m pytest tests/ -q` → 应 347 passed。
> 若日后要重下模型：`HF_TOKEN=<read权限token> .venv/bin/python -c "from huggingface_hub import snapshot_download as s; s('google/embeddinggemma-300m', local_dir='embeddinggemma')"`（注意 token 需勾选「读取门控仓库内容」权限）。

### 6.2 ✅ 卡牌游戏 legacy 依赖 —— 决策：不装（已确认）
- `rlcard / douzero / gradio` 是 Phase-1（Leduc / 斗地主）遗留，与 terminal-bench 无关。
- **你已确认「不要了」**，故不安装。`torch`（CPU 版）因 KB 仍在；仓库内 `DouZero-1.1.0/` 源码原样保留，未删。

### 6.3 ⚠️ `.env` 含真实密钥
`.env` 内有真实 `DEEPSEEK_API_KEY` 和 `TAVILY_API_KEY`（随 lite 包一起来的）。已 `.gitignore`，我未改动、未外泄。建议你尽快**轮换**这两个 key（它们已出现在分发包里）。

### 6.4 Python 版本选择
脚本写死 `python3.13` 且 terminal-bench 需 ≥3.12，系统只有 3.10 →我装了 **3.13**。脚本已改为「优先用 `.venv/bin/python`，回退 `python3.13`」，两者都满足。

### 6.5 ✅ 学习系统：record_learning track + auto_learning 独立固化

学习系统的核心是 `record_learning`（KB 只是它的一个下游 sink）。本节两项改动均已实现并验证。

**(a) record_learning track（轻量可观测）— `core/learning_track.py`（新）**
- append-only JSONL（默认 `data/learning/record_learning_track.jsonl`，env `LEARNING_TRACK_PATH` 可改），best-effort 永不打断学习流，单行 `O_APPEND` 跨进程/跨任务并发安全。
- 只记两类：**调用次数**（`call` 事件）+ **下游状态**（`downstream`: ok/fill_failed；`auto_learning`: triggered/ok/failed）。
- 查看：`PYTHONPATH=$PWD .venv/bin/python -m core.learning_track`
- 在 `record_learning_tool.py` 加了 3 个 best-effort hook（调用计数 / `_build_and_save` 下游终态 / auto_learning 触发与完成）。

**(b) auto_learning 固化 → 改为独立子进程 — `core/consolidate_runner.py`（新）**
- **根因**：原 `_check_auto_trigger`（pending≥5 触发）把固化丢给**进程内线程池**异步跑。在 tb 任务进程里，进程一退出固化即被截断：① `cannot schedule new futures after shutdown`（池随进程关闭）② 固化层链带 terminal/grep 工具却对着已失效的 session 调用 → `Command timed out (300s)`。结果：记录被归档却**没固化进 L1/L2/L3**。
- **修复（方案 A + 保留自动触发）**：触发时改为 `_spawn_consolidation()` **spawn 一个分离子进程** `python -m core.consolidate_runner`（`start_new_session=True` 脱离 tb 进程组；日志 `data/learning/consolidate.log`）。该进程：
  - **文件锁 single-flight**（`data/learning/.consolidate.lock`）→ parallel-train 多触发也只跑一个，不竞争 SQLite 库；
  - 自己 `setup_executor`（活线程池 + `load_env` 自带 key），**deny 掉 terminal/web/grep 等任务类工具**（用 `AgentContext.denied_tools`）→ 固化只碰 L1/L2/L3 + KB；
  - 跑现有 `_dispatch_learning`，track 记 `ok`/`failed`；`CONSOLIDATE_DEBUG_LOGS=1` 可开分层详细日志。
- **验证**：独立跑 ~60s 完成、track `auto_learning: ok`、无 shutdown/无 terminal 超时；**确实固化进库**（活存储是 SQLite `data/cognitive/*.db`，不是废弃的 `data/layers/.../*_index.json`）：`l2.db` 4 张卡 + L3 技能 `data/layers/skills/coding/git_recover_lost_commits/SKILL.md`。分离子进程在父进程立即退出后仍独立跑完（= tb 真实场景）。全套测试 347 passed / 2 skipped 无回归。

> 注意：L1/L2/L3/domain 的**活存储是 `data/cognitive/{l1,l2,l3,domain}.db`（SQLite）**；`data/layers/knowledge/l2_index.json`、`data/layers/domain_registry.json` 是旧/非活跃 JSON 索引（常为 0），别用它们判断固化是否生效。

---

## 7. 对原项目的具体改动清单

| 文件 | 改动 | 原因 |
|------|------|------|
| `tb/run.sh` | `python3.13`→优先 `.venv/bin/python`；`_run_task` 里 `cd /home/tonyyang`→`cd "$PROJECT_ROOT"` | 去 WSL 写死路径/解释器 |
| `tb/run_baseline.sh` | 去掉 `/home/tonyyang`、`/mnt/c/Users/micha/...`、写死 `DATASET`/`OUTDIR`/`.env` 路径，改为基于 `PROJECT_ROOT`/`$HOME`/venv | 同上 |
| `tb/build_images.sh` | **新增**：批量预构建 32 道任务镜像（可重跑） | 满足「把 images 建好」 |
| `requirements-ubuntu.lock` | **新增**：venv 依赖冻结快照 | 复现依赖 |
| `SETUP_UBUNTU.md` | **新增**：本文档 | 交接 |
| `core/learning_track.py` | **新增**：record_learning 调用次数 + 下游状态 track（见 §6.5） | 学习可观测（已确认） |
| `core/consolidate_runner.py` | **新增**：auto_learning 固化独立子进程入口（文件锁 single-flight + deny 任务工具，见 §6.5） | 修复固化在 tb 进程内被截断（已确认） |
| `core/tools/record_learning_tool.py` | 加 3 个 track hook；`_check_auto_trigger` 由「提交进程内线程池」→ `_spawn_consolidation` spawn 分离子进程 | 同上（已确认） |

> 早期移植阶段未动 `core/`；§6.5 的两项学习系统改动是**经你确认后**实施的（track + 独立固化）。仍未改动 `pyproject.toml`、`config.yaml`、`.env`。`tb/agent/cognitive_agent.py` 曾试加 drain 后已回退（真实 diff = 0）。

---

## 8. 复现 / 校验命令速查
```bash
cd /home/admin/cognitive-agent
# 跑全部单测（应为 347 passed, 2 skipped, 0 failed）
PYTHONPATH=$PWD .venv/bin/python -m pytest tests/ -q
# 跑一道 TB 任务冒烟
set -a; source .env; set +a; bash tb/run.sh fix-git
# 看 record_learning track（调用次数 + 下游状态）
PYTHONPATH=$PWD .venv/bin/python -m core.learning_track
# 手动跑一次独立固化（pending≥5 时自动 spawn；也可手动触发）
set -a; source .env; set +a; PYTHONPATH=$PWD .venv/bin/python -m core.consolidate_runner --domain interaction
# 看固化结果（活存储 = SQLite）
.venv/bin/python -c "import sqlite3;print('l2 cards:',sqlite3.connect('data/cognitive/l2.db').execute('select count(*) from l2_cards').fetchone()[0])"
# 32 道 test baseline（test 模式 / 无学习，4 并发）
set -a; source .env; set +a; bash tb/run.sh parallel <task...>
```
