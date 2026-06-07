# domain=learning/consolidate

## consolidation-strategy-basics

- **domain**: learning/consolidate
- **confidence**: 0.8
- **source**: seed

Consolidation 是知识库维护的核心操作。策略：
1. 优先删除从未被使用过的条目（use_count=0）
2. 合并语义相似的条目（相似度 > 80%）
3. 标记过时条目为 deprecated 而非直接删除（保险）
4. activation < 0.1 且超过 30 天未使用的条目优先清理
5. confidence 低且 failure_count 高的条目应被淘汰

## consolidation-l2-specific

- **domain**: learning/consolidate
- **confidence**: 0.7
- **source**: seed

L2 KnowledgeCard 整理要点：
1. 同一 domain 下内容高度相似的卡片 → 合并为一条概括性更强的卡片
2. 跨 domain 可泛化的策略 → 提升 domain 层级（如 game/leduc → game）
3. 内容过长的卡片（>300 字）→ 压缩为关键要点
4. soft limit 25，hard limit 30；接近 soft limit 时触发例行整理

## consolidation-l3-specific

- **domain**: learning/consolidate
- **confidence**: 0.7
- **source**: seed

L3 Skill 整理要点：
1. 功能重叠的技能 → 合并并保留更完整的版本
2. 与现有 L2 卡片无关联的技能 → 检查是否已过时
3. SKILL.md 内容 > 5000 字 → 拆分或精炼
4. soft limit 15，hard limit 20

## consolidation-output-format

- **domain**: learning/consolidate
- **confidence**: 0.9
- **source**: seed

整理任务输出格式：返回 per-layer modifications 数组。
- 使用 deprecate 删除无用条目
- 使用 update 修改/压缩内容
- 使用 create 创建合并后的新条目
- 每个 modification 必须包含 target（ID）和 reason（原因）
- 优先使用 deprecate 而非直接删除（可回滚）
