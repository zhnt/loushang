# GUI 参考系统清单

## Status

- ID: `GUI-REF-V3`
- Scope: Loushang proposed HarnessGUI
- Parent: Loushang
- Authority: descriptive — reference evidence and candidate lessons only
- Design status: proposed
- Implementation status: not-applicable
- Owner: Loushang architecture / future GUI requirement owner
- Source baseline: `becd4eb2` plus official pages rechecked 2026-09-10
- Related requirements: [GUI requirements](gui-requirements.md)
- Related context: [GUI system context and boundary contract](gui-system-context-and-boundary-contract.md)
- Related specification: [HarnessGUI interface specification](gui-interface-specification.md)

本文登记 GUI 需求发现使用的参考系统事实，并把事实、候选借鉴和 Loushang
范围决定分开。参考系统提供问题线索和交互证据，不是 Loushang 的需求模板；
某项能力出现在 Codex App 中，不会自动成为 Loushang 的 Target、组件或实现债务。

## 1. Evidence inventory

| ID | 来源与日期 | 可确认事实 | 证据限制 |
| --- | --- | --- | --- |
| `GUI-REF-001` | [ChatGPT desktop app](https://learn.chatgpt.com/docs/app)，2026-09-09 查阅 | 官方把桌面工作区描述为并行项目、长期工作、文件产物和跨工具协作入口；可以从聊天、项目或本地文件夹开始 | 页面覆盖 ChatGPT 与 Codex 桌面工作，不证明 Loushang 应复制全部产品能力 |
| `GUI-REF-002` | [Projects and chats](https://learn.chatgpt.com/docs/projects)，2026-09-09 查阅 | 项目用于组织相关聊天和上下文；聊天保留独立 transcript；官方界面提供固定、搜索、重命名和归档等组织操作 | ChatGPT project、local project 和 Codex directory/workspace 表述是参考系统概念，不能直接映为 Loushang 持久化实体 |
| `GUI-REF-003` | [Long-running work](https://learn.chatgpt.com/docs/long-running-work)，2026-09-09 查阅 | 运行目标可显示进度控制；独立聊天可以并行；需要输入或可审查时可以通知用户 | Loushang 当前 App Contract 没有通用 Goal 对、通知或后台调度合同 |
| `GUI-REF-004` | [Code review](https://learn.chatgpt.com/docs/code-review)，2026-09-09 查阅 | review pane 反映仓库事实而不只反映 Agent 修改，并区分工作树、暂存区、提交、分支和最近轮次等范围 | 行级评论、暂存、回滚、提交和推送是独立的可变操作与权限面 |
| `GUI-REF-005` | [Integrated terminal](https://learn.chatgpt.com/docs/integrated-terminal)，2026-09-09 查阅 | 终端按当前项目或 worktree 定位，并允许用户在聊天旁验证项目 | 终端是执行能力，不是普通展示 pane；不能从界面相似性推导为首期需求 |
| `GUI-REF-006` | [Git worktrees](https://learn.chatgpt.com/docs/environments/git-worktrees)，2026-09-09 查阅 | Local、Worktree 和 Handoff 支持隔离的并行开发与前后台迁移 | Handoff 包含 Git 操作、状态搬移、清理和恢复语义，现有 GUI/App Contract 未提供等价能力 |
| `GUI-REF-007` | 用户提供的 Codex App 截图组，2026-09-09 至 2026-09-10 查阅 | 可见状态包含原生菜单、Workspace/Session 左栏、新对话、展开分组、最近和用户区；活动 `Gui 开发` Session 显示旋转标志；中央 `第 1/4 步` 表示 Task 进度，执行摘要可展开为读取文件、运行命令等 Activity；右侧显示环境、变更、Subagent 与来源 | 截图只证明指定版本中观察到的布局与标签，不证明隐藏行为、完整状态机、稳定产品合同或后端对象；截图包含用户上下文，不纳入仓库 |
| `GUI-REF-008` | [Codex environments](https://learn.chatgpt.com/docs/environments/modes) 与 [Local environments](https://learn.chatgpt.com/docs/environments/local-environment)，2026-09-10 查阅 | 官方区分 Local、Worktree、Cloud；本地环境可提供 actions 与 Git 状态/操作入口 | 官方材料未声明 SVN；Loushang 不能从目录自行推断 provider 或权限 |
| `GUI-REF-009` | [Subagents](https://learn.chatgpt.com/docs/agent-configuration/subagents)，2026-09-10 查阅 | 根 Agent 可派生专门 Agent 并行工作，App 暴露各 Subagent thread，主 Agent 汇总返回结果 | 公开页面不定义 Loushang 的 Task/AgentRun schema、事件协议或控制权限 |

外部文档可能随产品更新。进入交互设计或实现前应复核受影响页面，并把变化作为
参考事实更新处理；旧截图不能覆盖新的官方合同，也不能单独证明质量属性。

## 2. Candidate lessons and disposition

| ID | 参考系统揭示的问题 | Loushang 当前处理 | 状态 |
| --- | --- | --- | --- |
| `GUI-RL-001` | 用户需要在多个工作上下文和会话之间移动，又不丢失各自上下文 | 强化 `GUI-FR-002`，分别表达工作上下文、mux/member 与 Session 身份 | proposed-first-scope |
| `GUI-RL-002` | 并行工作需要不打开会话也能看到运行、待答复和未读状态 | 保留 `GUI-FR-014` 会话状态总览，并明确服务状态与 GUI 本地未读的不同 owner | proposed-first-scope |
| `GUI-RL-003` | 用户在采取操作前需要知道当前环境、权限和信息来源 | 新增 `GUI-FR-015/016`；当前协议缺失的值显示未知，不能从目录名或界面选择推断 | proposed-first-scope |
| `GUI-RL-004` | 用户需要辨认真实变更范围和内容来源 | 新增 `GUI-FR-017` 的只读变更概览；`loushang.harness.workspace` 是 authoritative mechanism，Workspace/ChangeSet 值合同仍需 C1 决策 | proposed-first-scope with contract gap |
| `GUI-RL-005` | 查看文档、Diff、Task 或执行详情时仍需要看见会话状态并回到输入与控制 | `GUI-FR-007/010/020` 保留 pane continuity；用户确认的单窗口三主区域及可关闭 Work Dock 由界面规约冻结 | proposed-first-scope |
| `GUI-RL-008` | 活动 Session 状态、Task 步骤、Activity 详情和 Subagent 分配需要在不同信息尺度上保持同一执行 identity | 新增 `GUI-FR-020`，并要求左栏、中央时间线和右侧面板投影同一 Run/Task/AgentRun 事实 | proposed-first-scope with contract gap |
| `GUI-RL-006` | 固定、搜索、归档和通知降低长期多任务管理成本 | 在发现/通知合同存在后作为后续候选，不进入首期完成条件 | candidate-later |
| `GUI-RL-007` | 终端、Git mutation、行级反馈和 Handoff 可以缩短开发闭环 | 各自需要执行权限、来源版本和生命周期合同；不能并入只读展示 | candidate-later |

## 3. Explicit non-adoption

本轮不只凭参考系统派生以下承诺：

- Codex 品牌、商标、图标资产、精确像素和未经用户/owner 接受的隐藏行为复刻；
- ChatGPT project、云任务、分享、账号同步或历史数据库；
- GUI 直接拥有模型 provider、工具、浏览器、终端或 Git mutation 权限；
- 仅凭显示“Local”“Worktree”“main”就拥有相应环境控制权；
- 仅凭进度控件推导可查询 Goal、百分比、暂停或恢复合同；
- 插件、语音、定时任务、浏览器和 computer-use 自动进入首期范围。

这些能力只有在 Loushang 用户目标、产品合同、权限边界和验收条件分别成立并被
接受后，才能进入 Target。参考清单本身不承担 acceptance record。

Workspace/Session 左栏、中央 Session/Run、Task progress 和右侧 Work Dock
不是从 Codex 自动派生的承诺；它们由 2026-09-10 用户方向进入
[界面规约](gui-interface-specification.md)，当前仍为 proposed。视觉布局的采用
不接受 Codex 的品牌资产，也不绕过 Loushang 的服务 capability 与事实 owner。

## 4. Requirement-discovery gaps

| Gap | 需要谁确认或决定 | 未解决时的处理 |
| --- | --- | --- |
| 工作上下文是否需要 GUI 自有的持久化项目记录 | Product / GUI requirement owner | 首期只显示公开合同或显式配置提供的上下文，不建立隐藏数据库 |
| 环境、模型、策略、权限、工具和来源由哪个公开合同提供 | AppService / Product owner | 显示可验证值与 unknown/unavailable；不从 Python 内部对象旁路读取 |
| Workspace/ChangeSet 的 schema、容量、revision、失效与错误合同 | Harness / AppService / AppContract owners | authoritative mechanism 固定为 `loushang.harness.workspace`，客户端只用 fixture，直到共享只读 facet 被接受 |
| 全局历史发现是否采用 G17 profile | AppServer / GUI owner | G16 继续只覆盖当前 application/mux；Mock 列表不算真实发现 |
| 终端、Git mutation、Handoff、通知和行级反馈何时进入范围 | Product / security / GUI owner | 保留后续候选与进入条件，不阻塞黑盒首期 |
