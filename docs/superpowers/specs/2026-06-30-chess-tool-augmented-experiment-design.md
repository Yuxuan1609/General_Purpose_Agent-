# Chess 工具编排实验设计（方案 B）

> 日期：2026-06-30
> 前置：2026-06-29-chess-self-play-experiment-design.md（纯推理实验，已验证裸 LLM 棋力不足）
> 依赖：Maia3 chess engine、python-chess、Stockfish（系统预装）、cognitive-agent 分层认知架构

---

## 1. 背景与目标

### 1.1 纯推理实验结论

2026-06-29 实验验证了裸 LLM（deepseek-v4-flash）在无外部工具条件下对弈 Maia3-5M（Elo 700）：
- 两组（baseline/learning）G1 均输，top1 hit rate = 0%
- 子力差 -15 ~ -34，agent 持续送子
- LLM 纯推理棋力不足以在 Elo 700 级别构成有效对抗

### 1.2 本实验目标

放开外部工具（terminal + web_search + read_file + grep），测试 cognitive agent 的**工具编排能力**：
- agent 能否编排"Stockfish 引擎分析 → web_search 查理论 → 选最佳走法 → record_learning 记录"工具链
- 通过 20 局 train 积累工具使用经验（L1/L2/L3），提升对弈 Elo
- eval 阶段用 train 沉淀的知识测基础分数能力，eval 可并行跑多个 Elo 级别加速评估

### 1.3 与前实验的关系

前实验测"纯棋力+自我迭代学习"；本实验测"工具编排+学习"。架构不变，只改 tool_policy + prompt + 实验分组。

---

## 2. 实验结构

### 2.1 Eval 阶段（先跑，确定基础等级）

| 项 | 值 |
|----|-----|
| 工具 | terminal + web_search + tavily_search + read_file + grep + l1_query + l2_query + query_domain |
| record_learning | **deny** |
| 初始知识 | 干净种子（6 条 chess L1 规则，0 L2/L3），无任何学习积累 |
| 局数 | 每个 Elo 级别 3 局 |
| Elo 级别 | 1000 / 1200 / 1400 / 1600 / 1800（5 个并行 session） |
| Elo 自适应 | 无，固定级别 |
| 目的 | 确定基础模型+工具的等级——不带学习，纯测工具编排能力的天花板 |

5 个 Elo 级别并行启动，最快速度确定"模型+工具"在哪个 Elo 级别能稳定赢/输/平。

### 2.2 Train 阶段（eval 之后跑，观察 Elo 轨迹）

| 项 | 值 |
|----|-----|
| 工具 | 同 eval + record_learning |
| record_learning | 允许 |
| 初始知识 | 干净种子（6 条 chess L1 规则，0 L2/L3） |
| Elo 起始 | 700（或根据 eval 结果调整） |
| Elo 范围 | [600, 2000] |
| Elo 步长 | ±100（赢 +100 / 输 -100 / 平 ±0） |
| 局数 | 开放式，观察 Elo 轨迹直到稳定（初步预期 ~20 局） |
| Agent 执 | 白（先手） |
| max_moves | 80 |
| 引擎 | Maia3-5M (CPU) |
| LLM | deepseek-v4-flash |

### 2.3 Eval 并行设计

eval 在 train 之前跑，5 个 Elo 级别并行，各自独立子目录：

```bash
# eval 并行（5 个 Elo 级别，各 3 局）
python scripts/run_chess_experiment.py --group eval --eval-elo 1000 --games 3 --out-dir ...
python scripts/run_chess_experiment.py --group eval --eval-elo 1200 --games 3 --out-dir ...
python scripts/run_chess_experiment.py --group eval --eval-elo 1400 --games 3 --out-dir ...
python scripts/run_chess_experiment.py --group eval --eval-elo 1600 --games 3 --out-dir ...
python scripts/run_chess_experiment.py --group eval --eval-elo 1800 --games 3 --out-dir ...

# train 在 eval 之后跑
python scripts/run_chess_experiment.py --group train --games 20 --out-dir ...
```

---

## 3. 改动点

### 3.1 预装 Stockfish

实验开始前检查 `stockfish` 是否在 PATH：

```python
# run_chess_experiment.py 启动时
import shutil
if not shutil.which("stockfish"):
    logger.error("Stockfish not found in PATH. Install via: winget install Stockfish")
    sys.exit(1)
```

安装方式（手动，不自动化）：`winget install Stockfish` 或 `scoop install stockfish`。

### 3.2 `chess_game_env.py` — tool_policy 放开

```python
@property
def tool_policy(self) -> dict | None:
    allowed = ["terminal", "web_search", "tavily_search", "read_file", "grep",
               "kb_query", "kb_modify", "kb_fill_gap",
               "l1_query", "l2_query"]
    if self._enable_learning:
        allowed.append("record_learning")
    return {"allowed": allowed}
```

移除前的 policy（仅内部认知工具）→ 加入外部工具 + kb_ 工具。移除 `query_domain`/`create_domain`（未完成），加入 `kb_query`/`kb_modify`/`kb_fill_gap`。

### 3.3 `chess_game_env.py` — _SYSTEM_PROMPT 更新

在现有 prompt 基础上加入工具编排引导：

```
你正在与 Maia3 国际象棋引擎对弈（{group}组实验）。

**可用工具**：
- terminal：可执行 shell 命令。环境已预装 Stockfish，可通过 UCI 协议分析局面：
    echo "position fen <FEN>\ngo depth 15\nquit" | stockfish
  返回最佳走法和评估分数。建议 depth 10-15（平衡速度和精度）。
- web_search / tavily_search：搜索**思路和理论**（开局原则、战术模式名称、残局技巧），**不要搜索当前具体棋局的 FEN 或走法**——用 Stockfish 分析具体局面。每步最多调用 2 次搜索。
- read_file / grep：搜索本地 chess 相关文件
- kb_query / kb_modify / kb_fill_gap：知识库查询/修改/补缺
- l1_query / l2_query：下发内部认知层做深度分析

**建议流程**：
1. 用 terminal 调 Stockfish 分析当前 FEN（获取最佳走法 + 评估）
2. 如需理论背景，用 web_search/tavily_search 查开局名称或战术概念（不查具体局面）
3. 用 kb_query 检索已有知识卡片，用 l1_query 下发深度分析
4. 综合引擎评估和知识，选择最佳走法
5. [train 组] 如果发现有效的工具使用模式或战术经验，调用 record_learning 记录

**搜索硬性限制**：
- 每步最多 2 次 web_search/tavily_search 调用（环境强制，超限自动拒绝）
- 搜索只用于查思路和工具用法，不要搜当前 FEN/具体走法

**重要——使用 l1_query 调用下层认知**：
- 在复杂局面（被将军、吃子决策、多路分支）时，必须调用 l1_query 下发给L2/L3做深度分析
- l1_query 可以让L2检索知识卡片、让L3调用技能执行计算
- 收到L2回复后，综合信息做决策，不要跳过l1_query直接出结果

**重要——中间学习记录**：
- 每当子力对比发生变化（吃子/被吃），立即评估是否为关键转折点
- 如果发现某类走法（如开局模式、战术组合）在本局持续有效，记录为成功经验
- 不要等到整局结束才学习——及时固化中间发现

**禁止**：
- 不要安装或调用 Stockfish 以外的外部引擎（如 Leela、Komodo）
- 合法走法已由环境列出——你只需从中选择最佳的一个

输出要求：
- 最终选择一步走法，以格式 'move: <uci>' 结尾（如 move: e2e4）
```

### 3.4 `run_chess_experiment.py` — 加 eval 模式

新增 `--group eval` + `--eval-elo <N>` 参数（保留原有 `baseline/learning/both` 向后兼容）：

```python
parser.add_argument("--group", default="train", choices=["baseline", "learning", "both", "train", "eval"])
parser.add_argument("--eval-elo", type=int, default=None, help="Fixed Elo for eval (no adaptation)")

# eval 模式：enable_learning=False，固定 Elo，无自适应
if args.group == "eval":
    enable_learning = False
    current_elo = args.eval_elo or 1000
    # eval 不做 Elo 自适应，固定级别
elif args.group == "train":
    # train = learning 的别名（带工具版），enable_learning=True
    enable_learning = True
```

eval 组的 `enable_learning=False` → `tool_policy` 不含 `record_learning`，但保留 terminal/web_search 等工具。

### 3.5 不改的部分

- 实验 harness 主体（snapshot、CSV、game_NN.json）
- 三层认知架构（L1/L2/L3）
- record_learning / auto-learning 流程
- LLM 超时修复（已完成）
- reset_round_history（已完成）
- pending_dir 路径修复（已完成）

---

## 4. 单局流程

```
for each game (train):
  1. reset_round_history() — 清空跨局污染
  2. 新建 ChessGameEnv(model=maia3-5m, elo=current_elo, agent_plays=white, enable_learning=True)
  3. 新建 chain（指向 fork data_root）+ executor
  4. seed chess L1 rules（6 条）
  5. env.reset() → 初始棋盘
  6. while not game_over and move_count < max_moves:
     a. build TaskObservation（FEN + ASCII棋盘 + 合法走法 + 历史5步 + 子力信息）
     b. executor.execute(obs)
        → L1 agent 可调:
           - terminal: echo "position fen ...\ngo depth 15\nquit" | stockfish
           - web_search: "chess opening theory Italian Game"
           - read_file/grep: 查本地文件
           - l1_query → L2 → L3（内部认知）
           - record_learning（async，不阻塞对局）
     c. agent 输出 "move: <uci>"
     d. env.step(action) → 推进棋盘 + Maia3 回应 + reward
  7. game ends → 记录 outcome, total_reward, move_count, top1_hit_rate
  8. 调整 Elo: win +100 / loss -100 / draw ±0, clamp [600, 2000]
  9. snapshot data/ 目录 → snapshot_NN/
  10. [train] end-game reflection（可选）
```

eval 流程相同，除：
- enable_learning=False（无 record_learning）
- 固定 Elo（不自适应）
- 不写 snapshot
- 先于 train 跑，5 个 Elo 级别并行

---

## 5. 数据流

```
每步对局：
  env.build_observation(FEN + ASCII + 合法走法 + 历史)
  → executor.execute(obs)
  → L1 agent 工具编排:
     [外部工具]
     terminal → "echo 'position fen ...\ngo depth 15\nquit' | stockfish" → stdout 解析最佳走法
     web_search → "Italian Game theory" → 搜索结果
     read_file/grep → 本地文件
     [内部认知]
     l1_query → L2 检索知识卡片 + L3 技能执行
     record_learning → 异步写 pending JSON → auto-learning（train only）
  → agent 综合所有信息输出 "move: <uci>"
  → env.step(action) → Maia3 回应 → reward
```

---

## 6. 指标 & 日志

### 6.1 每局记录 (game_NN.json)

在现有字段基础上增加工具使用统计：

```json
{
  "game_id": 1,
  "group": "train",
  "elo_before": 700,
  "elo_after": 600,
  "outcome": "maia3 wins",
  "total_reward": 2.5,
  "move_count": 32,
  "top1_hit_rate": 0.15,
  "final_material_diff": -8,
  "tool_usage": {
    "terminal_calls": 15,
    "web_search_calls": 3,
    "tavily_search_calls": 1,
    "l1_query_calls": 8,
    "record_learning_calls": 2
  },
  "moves": [...]
}
```

### 6.2 Elo 趋势 (elo_progression.csv)

```csv
game,group,elo_before,elo_after,outcome,total_reward,move_count,top1_hit_rate,terminal_calls,web_search_calls,tavily_search_calls
1,train,700,600,maia3 wins,2.5,32,0.15,15,3,1
2,train,600,700,agent wins,5.0,28,0.30,12,2,0
...
```

### 6.3 输出目录结构

```
experiment_results/chess_tools_<timestamp>/
├── eval/
│   ├── elo_1000/
│   │   ├── game_01.json ... game_03.json
│   │   └── summary.json
│   ├── elo_1200/
│   │   └── ...
│   ├── elo_1400/
│   │   └── ...
│   ├── elo_1600/
│   │   └── ...
│   └── elo_1800/
│       └── ...
└── train/
    ├── game_01.json ... game_NN.json
    ├── elo_progression.csv
    └── snapshots/snapshot_001/ ... snapshot_NN/
```

eval 先跑确定基础等级，train 后跑观察 Elo 轨迹。

---

## 7. 实现顺序

1. 预装 Stockfish（`winget install Stockfish`，手动）
2. 改 `chess_game_env.py`：tool_policy 放开 + _SYSTEM_PROMPT 更新
3. 改 `run_chess_experiment.py`：加 `--group eval` + `--eval-elo` + Stockfish 启动检查 + 工具调用统计
4. 冒烟测试：`--group train --games 1` 跑通单局，确认 agent 能调 stockfish
5. 正式实验：eval 5 个 Elo 并行 → train 跑到 Elo 轨迹稳定

---

## 8. 风险 & 约束

- **Stockfish 主导**：agent 可能直接抄 Stockfish 的最佳走法，导致"学习"变成"记 Stockfish 输出"。但 record_learning 的价值在于记录**工具使用模式**（何时该查、查什么、如何综合判断），而非棋步本身。
- **terminal 开销**：每次调 stockfish 需启动进程 + UCI 交互，约 2-5s/次。80 步 × 15 次调用 ≈ 额外 30-60min/局。
- **web_search 依赖**：网络质量影响搜索结果可用性。SearXNG/DuckDuckGo fallback 已内置。
- **LLM API 超时**：已修复（600s timeout + max_retries=1 + try/except fallback）。
- **工具滥用**：agent 可能在简单局面也调 stockfish，浪费 token/time。prompt 引导"复杂局面才调"。
- **Elo 上限**：Stockfish depth 15 约对应 Elo 2500+，远超 Maia3-5M 的 2000 上限。agent 带 Stockfish 理论上能打到 Elo 上限。

---

## 9. 与前实验的兼容性

- 前实验的 `data_chess/` 数据不影响本实验（本实验用新 timestamp 目录）
- 前实验的 `chess_game_env.py` 改动（tool_policy 精简）会被本实验覆盖（放开工具）
- 前实验的 `run_chess_experiment.py` 会被扩展（加 eval 模式），baseline/learning 组保留向后兼容
