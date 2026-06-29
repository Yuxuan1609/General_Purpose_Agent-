# Chess Self-Play 自适应学习实验设计

> 日期：2026-06-29
> 依赖：Maia3 chess engine（vendor/maia3）、python-chess、cognitive-agent 分层认知架构

---

## 1. 研究目标

验证 cognitive agent 在**纯推理领域（国际象棋完整对局）**中，能否通过自适应难度的 self-play 积累 L1/L2/L3 知识，从而提升对弈水平（Elo 上升趋势）。

与 TB 实验的关系：TB Exp2 验证了 coding 领域的跨任务迁移；本实验测试的是同一领域内的**持续自我迭代学习**——agent 反复对弈，把每局经验沉淀为知识，下一局检索并应用。

---

## 2. 实验架构

### 2.1 AB 并行对照

| | B 组 (baseline) | A 组 (learning) |
|---|---|---|
| 局数 | 10 局 | 20 局 |
| record_learning | **deny** | 允许 |
| 知识检索 (l1_query/l2_query/query_domain) | 允许 | 允许 |
| 初始知识 | 干净种子（仅 meta 规则） | 干净种子（仅 meta 规则） |
| 域 | `chess/game` | `chess/game` |

- **顺序执行**：先 B 后 A。B 组确定 agent raw Elo 等级，A 组看学习能否突破。
- **数据隔离**：B 组用 `data_chess_baseline/`，A 组用 `data_chess_learning/`，各自独立 fork，互不污染。
- B 组也保留知识检索能力（能读到种子规则），但不允许写新知识——确保测的是 raw Elo 而非"无知识盲下"。

### 2.2 自适应 Elo

- 起始 Elo：1100
- 调整规则：赢 +100 / 输 -100 / 平 ±0
- 范围：clamp [1100, 2000]
- 每局结束后根据 outcome 调整下一局的 Maia3 Elo 参数

### 2.3 对局设置

- 引擎：Maia3 5m（CPU，~0.5s/步）
- Agent 执白（先手）
- max_moves：80（超时判平）
- LLM：deepseek-v4-flash（与 TB 实验一致）

---

## 3. 单局流程

```
for each game:
  1. 新建 ChessGameEnv(model=maia3-5m, elo=current_elo, agent_plays=white)
  2. 新建 chain（A 组：开学习；B 组：关学习）+ executor
  3. env.reset() → 初始棋盘
  4. while not game_over and move_count < max_moves:
     a. build TaskObservation（FEN + ASCII棋盘 + 合法走法 + 截断历史3-5步+吃子信息）
     b. executor.execute(obs) → agent 分析 → 输出 "move: <uci>"
     c. env.step(action) → 推进棋盘 + Maia3 回应
     d. 记录 per-move: reward, maia_top1, agent_move, captured_piece, material_diff
  5. game ends → 记录 outcome, total_reward, move_count, top1_hit_rate
  6. 调整 Elo: win +100 / loss -100 / draw ±0, clamp [1100, 2000]
  7. snapshot data/ 目录 → snapshot_NN/
  8. [A 组] agent 可在本局过程中调用 record_learning（async, 不阻塞对局）
```

---

## 4. 代码改动点

### 4.1 chess_game_env.py — 上下文截断 + 吃子信息

**改动 1：`_format_move_history()` 截断为最近 5 步**

当前展示全部历史，改为只展示最近 5 个 half-move pair（即最近 5 个 agent 回合 + 5 个 Maia3 回合）。避免上下文随对局长度线性膨胀。

**改动 2：history 条目增加 `captured` 和 `material_diff` 字段**

在 `step()` 中 agent 走法和 Maia3 走法 push 后，记录被吃子类型和当前子力差：

```python
# agent move
captured = board.piece_at(agent_move.to_square)  # push 前检查
# push 后计算 material_diff
material_diff = _material_balance(board)  # 白方子力 - 黑方子力（pawn=1, knight=3, bishop=3, rook=5, queen=9）
```

history 条目格式变为：
```python
{
    "move_num": 1,
    "white": "e2e4",
    "black": "e7e5",
    "agent_reward": 1.0,
    "eval": "best",
    "maia3_move": "e7e5",
    "agent_captured": None,       # agent 这步吃了什么子（None/pawn/knight/...）
    "maia3_captured": None,       # Maia3 这步吃了什么子
    "material_diff": 0,           # push 后白方-黑方子力差
}
```

`_format_move_history()` 输出格式：
```
[对局历史] 你是白方，Maia3是黑方
  1. 你: e2e4   Maia3: e7e5  +  子力: 0
  2. 你: g1f3   Maia3: b8c6  +  子力: 0
  3. 你: d1b3   Maia3: --    +  吃: -  (你被吃兵)
```

`material_diff` 以 agent 视角显示：正数=agent 领先，负数=落后。

**改动 3：新增 `_material_balance(board)` 辅助函数**

```python
_PIECE_VALUE = {chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3,
                chess.ROOK: 5, chess.QUEEN: 9, chess.KING: 0}

def _material_balance(board: chess.Board) -> int:
    """白方子力 - 黑方子力。agent 执白时正数=领先。"""
    diff = 0
    for piece in board.piece_map().values():
        val = _PIECE_VALUE[piece.piece_type]
        diff += val if piece.color == chess.WHITE else -val
    return diff
```

### 4.2 chess_game_env.py — tool_policy 精简

**改动 4：`tool_policy` 改为只保留内部认知工具**

当前：
```python
{"allowed": ["read_file", "grep", "sysinfo", "ask_user", "l1_query"]}
```

改为支持两组模式（通过构造参数控制）：

```python
class ChessGameEnv:
    def __init__(self, ..., enable_learning: bool = True):
        self._enable_learning = enable_learning
        ...

    @property
    def tool_policy(self) -> dict | None:
        allowed = ["l1_query", "l2_query", "query_domain"]
        if self._enable_learning:
            allowed.append("record_learning")
        return {"allowed": allowed}
```

- **移除** `read_file`、`grep`、`sysinfo`、`ask_user`、`kb_query` — 防止 agent 搜索磁盘上的 chess 包或外部资源
- **保留** `l1_query`、`l2_query`、`query_domain` — 知识检索能力
- **条件保留** `record_learning` — 仅 A 组（学习组）可用

### 4.3 新建 scripts/run_chess_experiment.py — 实验 harness

独立脚本，不改动现有 `run_chess_game.py`。职责：

1. **Elo 循环**：管理 current_elo，每局后根据 outcome 调整
2. **AB 组管理**：`--group baseline|learning|both`
3. **数据隔离**：为每组创建独立 data_root 目录，fork 干净种子
4. **快照**：每局后 `shutil.copytree(data_dir, snapshot_dir/game_NN)`
5. **日志**：per-game JSON + elo_progression.csv + summary.md
6. **恢复**：`--resume <snapshot_dir>` 从快照恢复
7. **工具策略**：A 组 `enable_learning=True`，B 组 `enable_learning=False`

命令行接口：
```bash
# 跑 baseline 组（10局）
python scripts/run_chess_experiment.py --group baseline

# 跑 learning 组（20局）
python scripts/run_chess_experiment.py --group learning

# 跑 both（先 baseline 后 learning）
python scripts/run_chess_experiment.py --group both

# 从快照恢复
python scripts/run_chess_experiment.py --group learning --resume experiment_results/chess_xxx/learning/snapshot_05

# 覆盖默认局数
python scripts/run_chess_experiment.py --group learning --games 30
```

---

## 5. 指标 & 日志

### 5.1 每局记录 (game_NN.json)

```json
{
  "game_id": 1,
  "group": "learning",
  "elo_before": 1100,
  "elo_after": 1200,
  "outcome": "agent wins",
  "total_reward": 8.5,
  "move_count": 42,
  "top1_hit_rate": 0.55,
  "avg_move_reward": 0.20,
  "final_material_diff": 3,
  "moves": [
    {"turn": 1, "agent_move": "e2e4", "maia3_move": "e7e5",
     "reward": 1.0, "eval": "best", "captured": null, "material_diff": 0},
    ...
  ],
  "cards_recorded": 2,
  "cards_retrieved": 3
}
```

### 5.2 Elo 趋势 (elo_progression.csv)

```csv
game,group,elo_before,elo_after,outcome,total_reward,move_count,top1_hit_rate
1,baseline,1100,1000,loss,-2.5,35,0.30
2,baseline,1000,1100,win,5.0,28,0.50
...
```

### 5.3 输出目录结构

```
experiment_results/chess_<timestamp>/
├── baseline/
│   ├── game_01.json ... game_10.json
│   ├── elo_progression.csv
│   └── snapshot_001/ ... snapshot_010/
├── learning/
│   ├── game_01.json ... game_20.json
│   ├── elo_progression.csv
│   ├── snapshot_001/ ... snapshot_020/
│   └── learning_log.jsonl
└── summary.md
```

---

## 6. 实现顺序

1. 改 `chess_game_env.py`：tool_policy 精简 + enable_learning 参数
2. 改 `chess_game_env.py`：_format_move_history 截断 + 吃子信息 + _material_balance
3. 新建 `scripts/run_chess_experiment.py`：harness 主体
4. 冒烟测试：`--group baseline --games 1` 跑通单局
5. 正式实验

---

## 7. 风险 & 约束

- **时间**：20+10 局 × ~40步 × (LLM ~5s + Maia3 ~0.5s) ≈ 12-16h，可接受
- **LLM 成本**：~1200 次 LLM 调用，deepseek-v4-flash 量级可接受
- **方差**：单局结果受 Maia3 随机性影响，Elo 趋势需多局才稳定——20 局 learning 足够看趋势
- **知识检索有效性**：A 组能检索到前 N-1 局沉淀的知识卡片（域 = `chess/game`），但知识质量取决于 agent 元认知能力（flash 级别模型可能较弱，与 TB Exp1 发现一致）
