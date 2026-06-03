---
name: leduc-preflop-raise
description: 翻牌前加注策略
domain: game/leduc
relevance_domain: game/leduc
---
# 翻牌前加注策略

持有K时强制加注，持有Q时根据对手行为判断，持有J时倾向call观察。
加注迫使弱牌fold或支付更高代价看公共牌。

## 决策树
- K → raise
- Q → 对手raise则fold，对手call则call
- J → call/fold，避免主动加注