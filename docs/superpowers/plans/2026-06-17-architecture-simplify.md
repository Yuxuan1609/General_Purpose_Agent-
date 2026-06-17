# Architecture Simplification (A+B) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate 6 architecture-level pain points by removing Comm Agent空壳, unifying data flow, killing global mutable state, and template化 Agent/Manager重复模式 — making the codebase ~500 lines shorter and significantly more robust.

**Architecture:** Two-track approach: (A) Layer Template Protocol — extract Manager/Agent repetitive patterns into base class template methods + declarative configs; (B) Communication Layer Simplification — delete Comm Agent空壳, unify query() signature to `TaskObservation`-only, replace module-level global setters with constructor-injected `ConsolidationContext`.

**Tech Stack:** Python 3.10+, dataclasses, pytest, existing test suite

---

## Pain Points Addressed

| # | Pain | Root Cause | Task |
|---|------|-----------|------|
| P1 | Manager/Agent 3层高度重复 | 每层独立实现相同的 query/decide 模板 | T4, T5, T6 |
| P2 | Comm Agent 6个空文件 | 子类继承基类但不添加任何逻辑 | T1 |
| P3 | Consolidation if-branch 重复3次 | `if lX_output_format:` 硬编码在每层 decide() | T5 |
| P4 | 全局可变状态 (set_*, get_pending_mods) | 模块级 global + setter 注入依赖 | T3 |
| P5 | _call_llm 200行承担过多 | 将拆分留给后续迭代，本次不动 | — |
| P6 | query() 接受 LayerMessage|Any | 类型不统一，Comm 只做透传 | T2 |
| P7 | 9个 consolidation handler 模式一致 | 每个 handler 手写 append + return | T7 |
| P8 | _L1/_L2/_L3_OUTPUT schema 重复 | 结构相同只是字段名微差 | T5 |
| P9 | 3层 tool_rules 提示文本完全相同 | 每层各自硬编码同一字符串 | T4 |

---

## File Structure (Post-Plan)

```
core/layers/
  __init__.py          # build_chain 简化 (删除6行空壳import)
  base.py              # +Template Method hooks, +CaptureToolDef, +ConsolidationStrategy
  comm.py              # 不变 (基类保留，删除6个子类文件)
  logging_setup.py     # 不变
  l0_5_1/
    manager.py         # 精简: query() 用基类, decide() 用模板
    upward_comm.py     # ❌ 删除
    downward_comm.py   # ❌ 删除
  l2/
    manager.py         # 精简: 同上
    upward_comm.py     # ❌ 删除
    downward_comm.py   # ❌ 删除
  l3/
    manager.py         # 精简: 同上
    upward_comm.py     # ❌ 删除
    downward_comm.py   # ❌ 删除

core/tools/
  consolidation_tools.py  # -9 handler → +1 _record_mod 工厂 + 声明式注册表
  # 其余不变

core/chain_factory.py     # 注入 ConsolidationContext, 删 set_* 调用

新增:
  (无新文件 — 所有改动在现有文件内)
```

---

## Task Dependency Graph

```
T1 (删Comm空壳) ──→ T2 (统一query签名)
                         │
                         ▼
T3 (消灭全局状态) ──→ T2 依赖 T3 的 ConsolidationContext 注入 Manager
     │
     ▼
T4 (CaptureTool配置化) ──→ T5 (Consolidation Strategy) ──→ T6 (Agent Template Method)
     │                        │
     ▼                        ▼
T7 (handler去重)          T5 包含 OUTPUT_SCHEMA 统一

执行顺序: T1 → T2 → T3 → T7 → T4 → T5 → T6
(每步可独立测试，每步 commit)
```

---

