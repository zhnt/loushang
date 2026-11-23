# GUI、Embedded TUI 与 Hosted TUI 的会话能力

| 能力 | Embedded TUI | Hosted TUI | GUI | 后端拥有者与本轮处理 |
| --- | --- | --- | --- | --- |
| 模型与推理档位 | `/model`、`/models` | `/model`、`/models`，包括 `--thinking` | 输入框的 ModelPicker | Hosted 与 GUI 均走 `session/models`、`session/model/select`，由当前 Session 的模型选择能力生效 |
| 新建 | `/new` | `/new <scope>` 打开 Mux 成员 | 侧栏新会话，草稿首次发送时提交 | AppService 和 Coding 生命周期管理当前实例。GUI 还处理已注册工作区和临时会话 |
| 删除 | `/delete` | `/close --yes` 关闭 Mux 成员 | 侧栏会话菜单「删除会话」 | GUI 走工作区会话删除，包含记录清理。Hosted 的关闭成员具有独立语义 |
| 重命名 | `/rename` 或直接给名称 | `/rename [name]`，写入会话元数据 | 展示 Host 确认的标题，暂无手动重命名菜单 | 标准命令及 Coding Session 元数据。本轮记录 GUI 的入口差异 |
| 工具管理 | `/tools` 及其子操作 | `/tools` 读取，变更走受控提交 | 「＋ → 工具 → 管理工具」 | 标准工具命令、Session ToolController 和 ToolActivation。GUI 展示已注册、允许与活动状态，并支持开关和恢复默认 |
| 手动压缩 | `/compact [instructions]` | `/compact [instructions]` | 「＋ → 工具 → 会话信息 → 压缩上下文」 | 同一 Session Compaction。GUI 提交默认压缩，复用 Hosted 的 Execution Guard、Registry、中断及对账 |
| 会话信息 | `/session` | `/session` | 「＋ → 工具 → 会话信息」 | Session 检查能力提供名称、身份、上下文 Token 和活动工具数。模型仍在 ModelPicker 显示 |
| Goal | Coding `/goal` | 当前 Hosted Slash 清单无 `/goal` | 输入框「模式 → 目标」与工作面板 | GUI 使用现有 Coding Interactive Goal 接口 |
| Prompt、Skill | 资源命令及 Prompt preflight | 可发现当前描述，专用命令执行入口暂不可用 | 规划中的动态入口 | 保持 ResourceBundle、Skill 目录和正文授权归属 |
| Extension | 已注册命令及 Extension Runtime | `/extensions` 查询已加载扩展。动态命令可发现 | 规划中的动态入口 | 命令执行需 Host 侧 Extension Runtime 上下文及准入 |
| LSP | `/lsp` | `/lsp`、`/lsp status`、受控 `/lsp stop` | 本轮无图形入口 | Coding Session LSP supervisor |

Hosted 命令清单与特殊路由详见 [Hosted Session Commands](hosted-session-commands.md)。

## GUI 调用链与执行状态

React 提供具体业务操作和会话作用域。Native 的 Tauri invoke 和 Rust Web 的 live action 分别核对连接 epoch 与 Host 实例，再交给同一 Rust AppClient。AppClient 从当前 Attachment 的成员映射生成控制请求，AppServer 和 AppService 在访问 Coding Session 前复核成员、控制代际和实例。

- 会话信息和工具清单使用 `session/command_read`。裸 `tools` 是只读形式，活动集合变更仍由标准工具命令处理。工具说明使用现有 ToolDefinition 说明的有界投影。执行许可仍由运行时策略与审批决定。
- 工具变更和压缩使用 `session/command_submit`。GUI 生成一次 Submission ID，并在当前窗口内按 Host、Mux 与会话保存未收敛提交。查询使用 `execution/find_submission` 和 `session/command_result`。会话或连接切换后，旧响应随原面板失效。同一 Host 重连后，重新打开面板可以沿原 ID 查询。未确认结果继续保留对应 ID，查询会话操作时不会重发。
- 压缩停止使用 `execution/interrupt` 并指向已对账的 Execution ID。终态以 Registry 为准。GUI 随后读最新会话或工具状态，失败反馈保留结果或执行错误码。
- 入口依赖带 Hosted Session Command 的 AppHost。Hosted 会话运行时随普通会话输入启动或恢复。尚未启动的会话，以及未提供对应能力的会话，会收到后端的不可用反馈。未确认提交的窗口内状态随窗口关闭结束。

## 后续动态入口

1. 在输入框动态入口中从当前会话查询 `session/command_catalog`，使用服务器返回的有效名称、来源、可用性及补全。会话切换或资源刷新时重新获取，保留同名冲突和 Hosted 保留名称的当前规则。
2. Prompt 模板与 Skill 属于普通输入的资源解析。选择条目后保留用户可编辑的参数，最终由其普通 turn 路由和 Prompt preflight 解析。先验证 Hosted 输入路径对模板展开、Skill 正文授权及恢复会话的资源代际行为，再开放条目。Skill 正文由授权的 Host 目录加载。
3. Extension 命令描述来自已加载的 Extension Runtime。开放某一命令的执行前，核对 Host 是否有对应的命令上下文、权限、参数补全和阻塞交互能力，以及 Execution 生命周期能否完整接管其结果。继续将只有 Embedded UI 上下文的操作标为当前不可用。

## 技术验收记录

实现代理 Codex 审查了 `lane/gui` 基线 `e5a76e4e0` 与 `feature/gui-session-capabilities` 的交付差异，范围为 GUI 展示、Native 与 Rust Web 桥、Hosted Session Command 投影及执行归属。接受复用现有只读查询与受控执行的设计。工具业务与压缩仍由 Coding Session 和 Harness 处理，会话信息从后台直接投影。Native 与 Rust Web 共用 AppClient 请求构造和对账，实现没有新增 AppServer 操作、业务 Registry 或直接调用 Python Runtime 的路径。

Linux Native 使用真实 Tauri WebView 和隔离测试 AppHost 验证了菜单入口、工具关闭与恢复默认、会话身份和压缩终态。Rust Web 进程验证了工具状态回读、成员隔离、旧 epoch 与 Host 拒绝、运行中的压缩准入。共享 Hosted 测试验证了压缩成功、失败、中断和按原 Submission ID 恢复。

基线记录。扩大 Coding 检查中，`tests/coding/test_hosted_interactive_goal.py` 的八个用例超时，停止该轮时已有 1,440 项通过。八项超时在未修改的 `e5a76e4e0` 全部重现。原 Rust Web 测试首次回查提交偶尔返回结果未知，本轮在测试中按原 ID 限时等待实际回执。
