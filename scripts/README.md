# Scripts 使用说明

## 环境依赖

```bash
pip install rlcard[torch]       # 卡牌游戏环境
pip install douzero             # 斗地主 AI (Phase 1b)
```

需要配置 API Key（用于 LLM Agent）：

```bash
# 方式 1: 环境变量
set DEEPSEEK_API_KEY=sk-your-key

# 方式 2: .env 文件（项目根目录）
DEEPSEEK_API_KEY=sk-your-key
```

---

## 脚本列表

### 1. `run_rlcard.py` — RLCard 通用启动脚本

支持多种游戏和对手的通用测试脚本，适合验证环境连通性。

```bash
# Leduc Hold'em vs CFR 预训练模型（100 局）
python scripts/run_rlcard.py --game leduc-holdem --opponent leduc-holdem-cfr --episodes 100

# 斗地主 vs 规则模型
python scripts/run_rlcard.py --game doudizhu --opponent doudizhu-rule-v1 --episodes 10

# 随机对手（用于基线对比）
python scripts/run_rlcard.py --game leduc-holdem --opponent random --episodes 50
```

**参数**

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--game` | `leduc-holdem` | 游戏: `leduc-holdem`, `doudizhu`, `limit-holdem`, `uno` |
| `--opponent` | `leduc-holdem-cfr` | 对手: `leduc-holdem-cfr`, `doudizhu-rule-v1`, `random` |
| `--episodes` | `100` | 对局数 |
| `--agent` | `random` | Agent 类型: `random`（基线）, `llm`（LLM Agent，当前为桩）|
| `--seed` | `42` | 随机种子 |
| `--verbose` | `True` | 输出每局结果 |

---

### 2. `run_llm_leduc.py` — LLM Agent 玩 Leduc Hold'em

使用大模型作为决策引擎，接入 Cognitive Agent 的 LLMClient。完整 prompt 写入日志文件，控制台仅输出汇总。

```bash
# 默认 5 局
python scripts/run_llm_leduc.py

# 10 局，指定日志目录
python scripts/run_llm_leduc.py --episodes 10 --log-dir ./my_logs
```

**日志文件**：`logs/llm_leduc_YYYYMMDD_HHMMSS.log`

日志包含每步的完整 [SYSTEM PROMPT]、[USER PROMPT]、[LLM RESPONSE] 和最终结果。

**参数**

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--episodes` | `5` | 对局数 |
| `--model` | 从 config.yaml 读取 | 模型名称（如 `deepseek-chat`）|
| `--temperature` | `0.1` | LLM 生成温度 |
| `--log-dir` | `logs` | 日志输出目录 |

---

### 3. `process_stats.py` — CSV 数据处理

通用 CSV 处理器（与 RLCard 无关）。

---

## 游戏说明

### Leduc Hold'em（Phase 1a）

简化德州扑克：
- 2 名玩家，6 张牌（K, Q, J × ♥ ♠）
- 每人 1 张底牌，1 张公共牌
- 两轮下注（翻牌前 + 翻牌后）
- 动作: `call` / `raise` / `fold`
- 预设对手: `leduc-holdem-cfr`（CFR 算法，纳什均衡级）

### Dou Dizhu / 斗地主（Phase 1b）

- 3 名玩家，54 张牌
- 信息集大小: 10⁵³ ~ 10⁸³
- 动作空间: ~27K
- 预设对手: `doudizhu-rule-v1`（规则模型，后续替换为 DouZero）

---

## RLCard 核心接口速查

```python
import rlcard

env = rlcard.make("leduc-holdem", config={"seed": 42})

# 手动控制
state, player_id = env.reset()
state, next_player = env.step(action_id)
payoffs = env.get_payoffs()   # [agent0_reward, agent1_reward, ...]
done = env.is_over()

# 自动对局（需先 set_agents）
env.set_agents([agent0, agent1])
trajectories, payoffs = env.run()
```

`state` 结构：

```python
{
    "obs":                np.array,         # 数值特征（给 RL 算法）
    "legal_actions":      OrderedDict,      # {0: None, 1: None, ...}
    "raw_obs": {                            # 自然语言描述（给 LLM）
        "hand":           "HJ",             # 手牌
        "public_card":    None,             # 公共牌
        "all_chips":      [2, 1],           # 总筹码
        "my_chips":       1,                # 己方下注
        "legal_actions":  ["call", "raise", "fold"],
        "current_player": 0
    },
    "raw_legal_actions": ["call", "raise", "fold"],
    "action_record": []
}
```
