# Conslidation Test Skills — deliberately redundant for testing consolidation
# domain=game/leduc

## leduc-skill-alpha
- confidence: 0.75
Leduc pre-flop raise strategy: with King always raise, with Queen call or raise depending on opponent, with Jack fold.

## leduc-skill-beta
- confidence: 0.72
翻牌前加注策略：持K加注、持Q跟注评估、持J弃牌。

## leduc-skill-gamma
- confidence: 0.70
Pre-flop decision framework for Leduc Hold'em. King→raise, Queen→evaluate, Jack→fold.

## leduc-postflop-1
- confidence: 0.80
翻牌后公共牌配对时全力加注。对手未配对时大概率弃牌。

## leduc-postflop-2
- confidence: 0.78
Post-flop paired strategy: maximize bets when your hand matches public card.

## leduc-bad-1
- confidence: 0.10
low quality skill, rarely used, should be removed during consolidation.

## leduc-bad-2
- confidence: 0.12
另一个低质量的技能模板，从未被匹配到，建议在整理时删除。
