---
name: learning-compile-skill
description: 将高频知识卡片编译为可复用的 L3 技能
domain: learning/compile
cross_domain: false
version: 1.0.0
---
# 知识卡片编译技能

## 流程
1. 筛选同域下激活值 > 0.7 且数量 ≥ 3 的知识卡片
2. 提取卡片间的共性和差异
3. 将共性提炼为通用决策流程
4. 生成 SKILL.md 格式的技能文件

## 输出
- 编译后的技能内容（YAML frontmatter + markdown body）
- 关联的 source card IDs（用于溯源）

## 原则
- 技能应覆盖常见场景但不失泛化
- 保留原始卡片的置信度信息
- 编译后原始卡片标记为已编译状态
