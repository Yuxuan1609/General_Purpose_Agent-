# RLCard + 环境设置

## 环境概览

| 组件 | 说明 |
|------|------|
| RLCard | 1.2.0 (pip install rlcard[torch]) |
| 操作系统 | Windows (原生，无需 WSL) |
| 验证路径 | Phase 1a: Leduc Hold'em → Phase 1b: Dou Dizhu (DouZero) |

## 已安装

```bash
pip install rlcard[torch]   # 卡牌游戏环境 + PyTorch
pip install douzero          # 斗地主 AI 框架（Phase 1b）
```

## RLCard 基础用法

### 创建环境

```python
import rlcard

# Leduc Hold'em — Phase 1a
env = rlcard.make('leduc-holdem', config={'seed': 42})

# Dou Dizhu — Phase 1b
env = rlcard.make('doudizhu')
```

### 核心接口

```python
# 重置
state, player_id = env.reset()

# 执行动作
next_state, next_player_id = env.step(action)

# 获取 payoff（结束后）
payoffs = env.get_payoffs()

# 检查是否结束
done = env.is_over()
```

`state` 是一个 dict，包含：
- `state['obs']` — 观测向量
- `state['legal_actions']` — 合法动作集合
- `state['raw_obs']` — 原始观测（自然语言可读）
- `state['raw_legal_actions']` — 原始合法动作

### 加载预设 AI 对手

```python
from rlcard.models.registration import model_registry

# Leduc Hold'em CFR (纳什均衡级)
cfr_agent = model_registry.load('leduc-holdem-cfr')

# Dou Dizhu 规则模型 v1 (Phase 1b 过渡)
rule_agent = model_registry.load('doudizhu-rule-v1')
```

### 完整对局示例

```python
import rlcard
from rlcard.agents import RandomAgent
from rlcard.models.registration import model_registry

env = rlcard.make('leduc-holdem')
cfr_agent = model_registry.load('leduc-holdem-cfr')

# Agent 0 = LLM Agent (此处用 Random 占位)
# Agent 1 = CFR 对手
env.set_agents([RandomAgent(env.num_actions), cfr_agent])

trajectories, payoffs = env.run()
print(f"Payoffs: {payoffs}")  # [agent0_score, agent1_score]
```

## 预设模型一览

| 模型 ID | 类型 | 难度 | 适用 |
|---------|------|------|------|
| `leduc-holdem-cfr` | 预训练 CFR | 高（纳什均衡） | Phase 1a 主对手 |
| `leduc-holdem-rule-v1/v2` | 规则 | 低 | Leduc 热身 |
| `doudizhu-rule-v1` | 规则 | 低 | Phase 1b 过渡 |
| `limit-holdem-rule-v1` | 规则 | 中 | 备选 |
| `uno-rule-v1` | 规则 | 低 | 备选 |

## Phase 1b: DouZero

当前 `pip install douzero` 不包含预训练权重，需单独下载：

```bash
# 下载 DouZero checkpoints
curl -L -o checkpoints.zip https://github.com/kwai/DouZero/releases/download/v1.0/checkpoints.zip
unzip checkpoints.zip -d douzero_checkpoints
```

使用：

```python
from douzero.evaluation.deep_agent import DeepAgent

# 三个位置各需一个 checkpoint
landlord = DeepAgent('landlord', 'douzero_checkpoints/landlord.ckpt')
landlord_up = DeepAgent('landlord_up', 'douzero_checkpoints/landlord_up.ckpt')
landlord_down = DeepAgent('landlord_down', 'douzero_checkpoints/landlord_down.ckpt')
```
