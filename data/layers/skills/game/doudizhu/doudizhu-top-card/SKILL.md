---
name: doudizhu-top-card
description: 顶牌策略
domain: game/doudizhu
relevance_domain: game/doudizhu
---
# 顶牌策略

作为地主上家，核心任务是顶住地主的出牌。出单张时优先出≥10的牌。
迫使地主消耗2或大小王等大牌资源。

## 顶牌优先级
- 出单张: 10 → J → Q → K → A → 2
- 出对子: 优先出较大的对子
- 不要出炸弹或火箭作为顶牌（留给残局）