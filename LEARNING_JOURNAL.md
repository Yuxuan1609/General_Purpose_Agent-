# Project Learning Journal — cognitive-agent

> 更新原则：记录本项目中可迁移的工程技巧。保持 ≤5000 字。
> **来源**：代码实现、Debug、架构决策中提炼的可复用经验。
> **写入前**：与已有内容交叉对比——新条目可能与已有条目重叠或互补，优先合并而非新增。
> **同步**：有大更新时对比 `~/.config/opencode/LEARNING_JOURNAL.md`，将可迁移技巧同步到全局。

---

## 子系统通过 dataclass 合约解耦
- 多个模块协同开发时，先定输入/输出 dataclass（合约），各自独立实现，仅依赖消息类型
- 本项目示例：各层（L0.5 / L1 / L2 / L3）通过 `LayerContext` 桥接，层之间不直接引用对方内部模块
- 适用于任何分层架构——合约稳定则实现独立

## 事件循环从成熟实现提取结构而非复制代码
- Hermes `run_conversation()` ~3900行 → 提取核心 while-loop 模式 ~100行
- 保留：迭代控制、tool dispatch、消息追加；去掉：多 provider fallback、streaming、compression、error recovery
- 5 个插入点（PRE-LLM / PRE-TOOL / POST-TOOL / COMPLETION / POST-TASK）是定制化的接口

## LLM System/User Prompt 分离
- System prompt：身份定义 + 工具说明 + L1 规则（稳定、缓存友好）
- User message：动态注入 L2 知识卡片 + L3 技能提示（每次任务变化）
- 借鉴 Hermes 的三级分层（stable → context → volatile），Phase 1 简化到 2 层

## MD + JSON + Graph 三层存储模式
- MD：源内容，按 domain 分目录，`##` 章节，人类可读
- JSON：自动维护的索引（章节名 + 摘要 + 关系），快速检索不读 MD
- Graph：运行时从 JSON relations 构建邻接表，激活扩散用
- 适用范围：需要"内容 + 结构化索引 + 关系推理"的知识管理系统

## 配置可改性分层（HARDCODED / USER / RUNTIME）
- L0.5 触发器 → 代码常量（Agent 不可改）
- L1/L2/L3 路径和上限 → 用户配置文件
- L1/L2/L3 运行时内容 → Agent 可修改（经 L0.5 审批）
- 用途：清晰界定"什么能改、在哪改、谁能改"

## 4 种知识关系类型
- `parent_child`、`cross_reference`、`prerequisite`、`analogous`
- 覆盖知识层级、跨域引用、前置依赖、类比迁移
- 关系驱动 L2 的 Graph 激活扩散，用于跨域类比检索

## Singleton ToolRegistry 的线程安全 + 测试隔离
- 双重检查锁（DCL）实现线程安全
- 测试中需要 `clear()` 重置单例状态，避免测试间污染
- 借鉴 Hermes `tools/registry.py` 结构，去掉 AST 自动发现

## Tool 设计遵循 self-register 模式
- 每个 tool 文件暴露 `register_xxx_tool(registry)` 函数
- 主类在 `__init__` 中统一调用注册
- Hermes 用 AST 扫描 + import 自动发现，Phase 1 改为显式注册（更简单）

## TDD 中 fixture 设计：temp_dir + autouse clear
- `temp_dir` fixture 提供隔离的文件系统，测试写入不污染磁盘
- `autouse` fixture 清理单例状态（ToolRegistry），避免测试间泄漏
- Mock LLM client 返回预设响应，隔离外部 API 依赖

## LLM prompt 中中文花括号转义
- `str.format()` 中 `{关键词}` 被误解析为 format key → 用 `{{关键词}}` 转义
- 本项目 L0.5 的 LLM prompt 模板使用 `{task_description}` 等占位符，中文 JSON 示例需转义

## 外部 API 调用必须设超时
- `terminal_tool` 中 `subprocess.run(timeout=30)` 防止命令 hang
- 未来 `_LLMWrapper` 需要给 `client.chat.completions.create()` 加 `timeout`

## 集成测试中 mock 隔离外部依赖
- Agent 集成测试中 mock LLM client 返回预设 tool_calls/text
- 短路要保留接口合约——返回合法的 `MagicMock` with `has_tool_calls`/`text`/`tool_calls`
- 适用：多子系统集成测试中个别系统未就绪或会阻塞全局的场景
