# L1 Rules — Consolidation Test Fixtures
# Deliberately redundant / low-quality rules for testing consolidation

## l1_good_a
- source: l1
总是优先使用经过验证的策略知识，而非依赖直觉或猜测。在不确定时优先调用 L2/L3 层获取相关知识和技能。

## l1_good_b  
- source: l1
面对概率性决策时，基于期望收益而非直觉判断。综合考虑各选项的成功概率、收益和代价后行动。

## l1_dup_a
- source: l1
在做出任何决策之前，务必检查可用的知识卡片和技能，不要凭感觉瞎猜。

## l1_dup_b
- source: l1
决策前先看有没有相关的知识卡片或技能可以用，不要直接猜测答案。

## l1_low_a
- confidence: 0.15
一个非常模糊的规则，几乎没有任何可操作性。

## l1_low_b
- confidence: 0.10
偶尔可以尝试一些新的方法，但具体什么方法不明确。
