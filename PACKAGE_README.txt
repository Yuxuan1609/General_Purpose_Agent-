cognitive-agent 学习/泛化实验交付包
====================================
整理日期: 2026-06-29

【主报告】
  EXPERIMENT_REPORT.md   — 统一实验报告(Baseline→Exp1→Exp2→Exp1调整实验+基础设施)
  TB_BASELINE_RESULTS.md — baseline及各实验详细过程记录
  TB_EXPERIMENT_PLAN.md  — 实验规划/方法论
  ARCHITECTURE.md 等     — 架构/其他文档

【代码 (修复均已含)】
  tb/        — agent(cognitive_agent.py)、tools(tb_terminal/read_file/grep/session_holder)、运行脚本(run_*.sh)
  core/      — 认知层(layers/l0_5/l1/l2/l3)、tools(consolidation_tools.py 卡片混淆修复)、storage
  capability/ scripts/

【实验结果 (轻量, 不含246M per-task大日志)】
  tb_runs_results/  — 各实验 results.txt + summary.txt + chain日志(保留相对路径)

【学习态快照 (可复现)】
  data_snapshots/   — exp1_seed / exp1_after_r3 / git_after_train / exp1_cohort_after_train 等

【关键证据日志】
  evidence_logs/    — 卡片混淆修复前/后对照 l2.log

注: 不含 .venv / vendor / .git / 容器产物 / per-task verbose 日志。
