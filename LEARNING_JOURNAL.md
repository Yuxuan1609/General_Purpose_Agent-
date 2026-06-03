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

## 认知层设计：合并语义相近层减少传递开销
- L0.5（不可变宪法）和 L1（可演化规则）合并为 L(0.5+1) 一层，内部通过"L0.5 验证器审批 L1 提案"分权
- 原因：两者同属"行为宪法"语义域，合并后层链从 4 层减为 3 层，减少 A1 相邻传递的往返次数
- 适用于任何分层架构中语义高度重叠的相邻层

## Executor 独立于层体系：决策者与认知层解耦
- Executor 不归属任何认知层，职责简单明确：拼接各层结果 → prompt → LLM → action
- 层只向 Executor NOTIFY，Executor 不反向通信（只收不发）
- 好处：认知层可独立演化（增删层、改内部逻辑），Executor 接口不变

## 每层 Manager 作为局部编排者
- 不再设全局 Orchestrator，编排职责分发到每层 Manager
- Manager 决定：是否向下一层 QUERY、传什么、等 RESPONSE 后怎么聚合
- 与信息隔离原则（A3）天然契合：每层只管理自己边界内的事

## ReflectionAgent 递归判责模式
- 每层设独立 ReflectionAgent，反思编排时：判责（自己 vs 下层）→ 是自己则 fix() → 是下层则 QUERY 下层 ReflectionAgent
- 与 Execute 段相同的链式 QUERY→RESPONSE 模式
- 两条链路分离：全局 Reflect（Coordinator 审核分发）和每层 Reflect（ReflectionAgent 递归链）

## TaskObservation 三层语义的通信层填充
- meta（干什么）、state（什么情况）、history（之前发生了什么）三层语义，全部由通信层（脚本）填充
- history=None 表示任务不需要历史（如完美信息斗地主），由通信层决策
- 等价于 Reflexion 的短期记忆 + Voyager 的环境反馈的结构化合并

## Comm Agent 分离：Manager 不处理协议
- UpwardComm/DownwardComm 是确定性 Agent，仅处理 LayerMessage 序列化/反序列化
- Manager 专注业务逻辑，收发的都是业务 dict，不接触 LayerMessage 格式
- 适用：任何需要统一通信协议但不想污染业务代码的分层系统

## 参考文献与设计决策记录
- Voyager 技能系统：L3 SKILL.md 格式借鉴 Voyager 的 Skill Library 设计（`docs/voyager-skill-system-detail.md`）
- Reflexion 反思模式：ReflectionAgent 递归判责借鉴 Reflexion 的 Self-Reflection 模型（`docs/reflexion-architecture-detail.md`）
- 关键差异：本项目用结构化持久化（JSON/MD）替代 Reflexion 的纯 prompt 存储，突破 context window 限制
- Session-学习单元映射策略受 Voyager 的 Automatic Curriculum 的"从简单到复杂"递进思想影响

## Session Review: 2026-06-03 — Execute 链路跑通

### 成果
- **架构设计**: 三层链式 L(0.5+1)→L2→L3，Executor→Comm Agent→LayerMessage 协议
- **代码**: Phase 1 (10 tasks) + Phase 1.5 (6 tasks)，28 新增 tests，135 total
- **双环境验证**: DouZero + Leduc，L1 rules + L2 cards + L3 skills 全链流通
- **日志**: per-agent 分文件 + 干净分隔符 + http 噪音抑制

### 架构决策
1. **L0.5+L1 合并**: 同属"行为宪法"语义域，减少链长度
2. **Executor 独立**: 决策者与记忆系统解耦，层可独立演化
3. **Comm Agent 分离**: Manager 不碰 LayerMessage 协议
4. **per-agent 分文件日志**: 多 agent 系统中单文件不可读

### 工程教训
1. **文档积债代价**: Phase 1/1.5 后 6 个文档含大量"待实现"标记，清理耗时约等于一个 task。建议每次 task 即时更新
2. **Prompt 组装是 Executor 核心**: 从 raw dict dump 改为层次化格式 + 技能全文加载，LLM 决策质量差距明显
3. **种子 vs 学习闭环**: 当前 L1/L2/L3 手动种子，框架价值取决于 Phase 2 从失败中学习的能力
4. **双环境暴露接口问题**: RLCard eval_step vs DouZero act，TaskObservation 够灵活但适配仍需定制

### 框架价值的关键前提
1. **L2 卡片质量 > 通用 LLM 知识** — 种子内容必须包含反直觉的领域经验才有增量价值
2. **Reflect 闭环正面反馈** — boost/penalize 要区分"坏策略"和"运气差"
3. **L2 Domain Graph 跨域泛化** — 斗地主和 Leduc 的策略能互相借鉴多少是关键
