# Leduc Hold'em — Consolidation Test Fixtures
# Deliberately redundant / low-quality cards for testing consolidation
# domain=game/leduc

## card_leduc_a1
- confidence: 0.75
持有K时翻牌前强制加注，建立底池优势。对手跟注说明对手持Q或J赌公共牌。

## card_leduc_a2
- confidence: 0.72
翻牌前持有K（最大牌）时应果断加注。K是绝对强牌，加注可迫使弱牌弃牌。

## card_leduc_a3
- confidence: 0.78
手持K在翻牌前必须加注攻击，不要平跟让对手看到便宜公共牌。

## card_leduc_b1
- confidence: 0.55
翻牌前持有Q时，中等牌力需要谨慎评估。如果对手加注而你持Q，可以考虑跟注。

## card_leduc_b2
- confidence: 0.52
手持Q翻牌前策略：观察对手下注行为。对手激进则跟注观察，对手被动则可尝试加注。

## card_leduc_c1
- confidence: 0.25
翻牌前持有J时可以尝试bluff加注，给对手施加压力。风险较高但可能获得意外收益。

## card_leduc_c2
- confidence: 0.22
experimental: with Jack pre-flop, occasionally raise to represent strength. 成功率低。

## card_leduc_c3
- confidence: 0.18
尝试在翻牌前用J做半bluff，对手可能误以为你持K或Q。不推荐常用。

## card_leduc_d1
- confidence: 0.85
公共牌与你手牌配对时全力加注。翻牌后加注额4筹码，两次加注上限内打满。

## card_leduc_d2
- confidence: 0.82
当公共牌和你的手牌形成一对时，这是极强的牌型。此时应最大化下注，对手很可能没有配。

## card_leduc_e1
- confidence: 0.60
翻牌后未配对时保持谨慎。如手牌为J且对手加注，fold是最安全的选择。

## card_leduc_e2
- confidence: 0.58
翻牌后没有配到对子时要保守。尤其是手持J的时候，面对对手加注应该fold。

## card_leduc_x1
- confidence: 0.10
some random strategy idea, not tested, very low confidence.

## card_leduc_x2
- confidence: 0.12
另一个未经验证的策略想法，activation 很低，从未在实战中使用。

## card_leduc_x3
- confidence: 0.08
非常低可信度的实验性策略，建议在整理时删除。
