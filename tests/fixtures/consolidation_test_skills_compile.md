# Consolidation Test Skills — learning/compile domain
# These skills match the consolidation task domain so L3 is triggered

## consolidate-merge-cards
- confidence: 0.80
合并知识卡片策略：识别同 domain 下语义相似度 >80% 的卡片，合并为一条概括性更强的卡片。保留高 confidence 的版本。

## consolidate-prune-low
- confidence: 0.75
清理低质量卡片：confidence < 0.2 且从未使用的卡片标记为 deprecated 或直接删除。

## consolidate-bad-1
- confidence: 0.10
一个低质量的整理技能，从未被使用过。

## consolidate-bad-2
- confidence: 0.08
另一个实验性的整理模板，内容模糊，建议删除。
