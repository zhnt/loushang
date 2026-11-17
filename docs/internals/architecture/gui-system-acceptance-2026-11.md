# GUI / AppHost 系统验收

验收基线 `58eeb81f494d4bf4dd054e8886a689e87a9fc4eb`。2026-11-17 在 Linux x86_64 上从该 SHA 独立构建，使用 Python 3.11.15、Node 24.22.2 和 Rust 1.98.1。本文是本轮验收记录，历史平台证据另列。没有修改产品代码、预期值或 CI 门禁。

## 结论

Linux Rust Web 与 Chromium 已完成六类场景的主要路径。崩溃后，原 Transcript、待答业务选择和 Goal/Work 持久事实可重读。旧 Execution 和 Goal 命令仍受原实例与所有权约束。Linux Tauri 实测独立连接、实时回复、动态 Goal Step 和窗口托盘生命周期。Windows、macOS 与跨机器转发未在本轮重测。

本轮没有发现已复现的 P0/P1 产品缺陷。如果发布范围是本机 Linux 且采用任务 14 的只读恢复合同，建议关闭本阶段。如果发布范围还包括 Windows、macOS 或跨机器连接，保留对应验收项。任务 14 的交付范围是只读恢复。在该范围内，可执行 Goal owner 的重新取得属于后续范围。如果恢复后可继续执行是发布承诺，该能力缺口为 P1，阶段应保持开放。

## 场景与本轮证据

以下每行均使用上述 Git SHA。Web 场景使用独立 Managed Coding AppHost、真实认证 AppServer、Rust Web、生产 Vite 构建和 Chromium。测试使用临时 Workspace、私有连接记录和确定性模型。验收脚本只终止自己启动的进程。本轮日志与截图保存在 `/tmp/loushang-w15-evidence/`。

| 编号 | 操作及预期 | 观察与结果 | 证据 |
| --- | --- | --- | --- |
| S1 | 新建临时或项目草稿，首次发送才创建 Session。丢弃首次提交的 HTTP 回执并按原 Submission 查找。重复同一提交应复用 Execution。 | **PASS**。草稿打开和输入期间目录计数保持原值。临时首发后是 `0 → 1`，其余四次项目首发逐次增加至 5。首次丢回执以 `gui-17c03c05-1d34-4bcd-bc3b-2652cdb4103d` 查到原 `exec-52bbfee932471d60a0b90f32-1`。重交同一 ID 返回同一个 Execution，每条指令仅进入一次模型。独立 Managed 服务的直接打开另验证默认 Session 只有一个，显式创建第二个有自己的身份。确定拒绝和无法对账时保留草稿由 GUI 回放测试覆盖。 | `workspace.log` 的 `S1-LOST-RECEIPT`、`S1/S3`，`manager-restart.log`，`probe.log`，`gui/tests/playback/conversation.test.tsx`。 |
| S2 | 创建项目目录并查询。尝试已有目录、相对路径和不可写父目录。 | **PASS**。已存在目录的哨兵内容保留，非法路径和权限错误在 UI 中可辨，失败后登记数仍为 0。创建 `alpha` 和 `beta` 后两个空目录可查询和选择，Session 数仍为 0。浏览器输入为 Host 上的绝对路径，Rust 仅验证请求形态，目录判定在 Host 上执行。跨机器路径见平台限制。 | `workspace.log` 的 `S2`，`tests/apphost/test_managed_registry.py`。 |
| S3 | 每个 Workspace 创建两个 Session，在它们之间切换，然后重启独立 Managed 服务并查回原身份。 | **PASS**。四个项目 Session 的标识及 Execution 不同，回复与所属项目一致。等待目标 Snapshot 就绪后，`alpha 1` 的草稿未进入 `beta 1`，切回时原草稿恢复。独立服务中两套 Workspace 的四个 Session 在重启后以原 ID 列出，每个 Workspace 的两次受控副作用保留且没有增加。 | `workspace.log` 的 `S1/S3`、`S3-DRAFT`，`manager-restart.log`。 |
| S4a | 普通发送与流式渲染，主动中断，工具审批允许一次、拒绝及取消。 | **PASS**。正文完成后仍在原 Session。可在 Execution 活跃期间看到部分文本 `waiting`，点击 Interrupt 后显示终态。只有允许一次产生工具执行标记。拒绝与取消都关闭审批且无第二个执行标记。 | `workspace.log`、`approval.log`，`tests/coding/test_hosted_session.py::test_G14_PRODUCT_real_approval_broker_round_trip_and_close`。 |
| S4b | 收到 `ask_user` 后选择 A、选择带附注的 B，并重复点击确认。 | **PASS**。原 Session 内用新的 Execution 继续，双击只有一次提交。刷新保留待答卡片，另行发送普通消息按原规则继续。 | `choice.log`，`tests/coding/test_hosted_user_choice.py`。 |
| S4c | 创建动态 Goal，Step、Run、Pause、Resume、Cancel、审阅、拒绝后再运行、接受。旧候选和证据缺失不能通过。 | **PASS**。Chromium 中 Step 只进一个 Batch，Pause 结算中仍能观察原 Work，Cancel 产生取消事实。Goal 使用原 AgentSession 和 WorkRuntime，丢回执靠原 Command ID 对账。在真实拒绝后可重跑并通过原 Review Work 完成。候选变化、必需检查、并行聊天拒绝由现有 Hosted Interactive Goal 测试验证。 | `goal-12.log`、`goal-13.log`，`tests/coding/test_hosted_interactive_goal.py`。 |
| S5 | 接受长任务后关闭浏览器，再启动页面。另停止并重启独立 Rust Web 进程。检查 PID、原 Session、快照、原提交和控制权限。 | **PASS**（Web 与 AppClient）。关闭页面后同 PID 下原任务完成一次，新 View 重连取回原 Mux/Session/Execution。Rust Web 退出后独立 Managed Host PID 不变，四条在途 Execution 仍在。Rust 实际连接探针验证独立 Mux、同一 Mux 的控制冲突、释放和重新取得。AppService 测试验证旧 generation 的写入拒绝。Goal 与 Review 的丢回执和重连覆盖见 S4c。Tauri 关闭到托盘、重开与 Quit 均单独通过。真正停止 Host 由独立 Managed 管理命令触发。 | `workspace.log` 的 `S5`、`web-reconnected.png`、`manager-restart.log`、`probe.log`、`transport.log`。 |
| S6a | SIGKILL 后由新实例重开原 Session。 | **PASS**。原 Mux 和 Session 可通过生产导航恢复，Chromium 显示原普通 Transcript。Goal 与选择场景均使用实际新实例。 | `goal-14.log`、`choice-crash.log`。 |
| S6b | 待答选择写入原 Transcript 后 SIGKILL。重连观察，再提交选择。 | **PASS**。重开前后 Mux 与 Session ID 相同，Host 实例改变。观察阶段 Transcript 字节相同且新实例无模型调用。双击确认只产生一个新 Execution，模型只收到这一次新回答。 | `choice-crash.log`、`web-choice-recovered.png`、`choice-restart.log`。 |
| S6c | Work 已写出工作区文件但终态未落盘时 SIGKILL。重连读 Goal 和 Work。 | **PASS**（只读范围）。原 Goal revision 1、epoch 1 显示为上次记录时活跃。2 个 Batch 的 Work 结果为 1 completed 和 1 orphaned，同时标记 unresolved。旧命令被拒绝，无新模型或 Work 受理，无新 Goal owner。原 Transcript、Goal Journal、Work Event Log、已写出文件的字节均未变化。历史完成和暂停的独立投影由本轮定向测试验证。 | `goal-14.log`，`tests/coding/test_hosted_interactive_goal.py`。 |

## 职责与权威

| 对象 | 本轮核验 |
| --- | --- |
| GUI / Web UI | React 通过 [Host API](../../../gui/src/client/hostApi.ts) 和 [Web](../../../gui/src/client/webLiveClient.ts)／[Native](../../../gui/src/client/nativeLiveClient.ts) 客户端呈现 Snapshot、交互和 UI 草稿。生产调用链未发现直接读取服务私有文件或凭据的入口。Rust 保管连接记录并向界面传输投影。 |
| Rust AppClient / AppServer | [共享 Rust 客户端](../../../gui/app-client/src/app_client/mod.rs)处理连接、认证协议、快照和控制。Python [LocalAppServer](../../../src/loushang/appserver/local.py) 发布监听并认证，按客户端 scope 调度。Rust Web 和 Tauri 在连接边界之外运行。Linux Tauri 窗口进程与运行 Python 的独立 Host 进程分离。 |
| AppService / AppHost | [Execution Service](../../../src/loushang/appservice/execution_service.py)在原 attachment、controller、member、instance 下登记、去重和协调 Execution。[Managed Coordinator](../../../src/loushang/apphost/managed/coordinator.py)持有服务生命周期。实测 Host PID 独立于 Web，四个项目 Session 共用一个 Host。短生命周期管理命令只负责启停及状态，客户端连接释放不等同于停止服务。 |
| Workspace / Session | [Managed Bootstrap](../../../src/loushang/coding/managed_bootstrap.py)装配 Host Registry，[Coding Catalog](../../../src/loushang/coding/workspace_catalog.py)借用 Registry，Workspace 路径由 Host 创建、登记和选择。Mux Member 指向 Session，Canonical Transcript 是会话历史权威。GUI 配置保存导航和偏好。 |
| Product / Harness / Goal / Work | Coding 持有业务准入并通过 [HostedGoalCommands](../../../src/loushang/coding/hosted_goal_commands.py)提交原 InteractiveGoal。真实测试对比了同一个 AgentSession 和 WorkRuntime。原 Goal Journal 与 Work Event Log 能重放已提交事实，[冷恢复投影](../../../src/loushang/coding/hosted_goal_recovery.py)没有运行或存储权威。[Deferred Session](../../../src/loushang/coding/hosted_resume.py)在读取前后验证原 Transcript。 |

使用仓库的 `scripts/gui/check_apphost_integration.py` 验证真实 Rust 连接。浏览器脚本使用暂存目录的 `workspace.py`、`approval-managed.py`、`choice.py`、`goal-12.py`、`goal-13.py`、`goal-14.py` 和 `choice-crash.py`。在验收基线环境用 `PYTHONPATH` 指向仓库、`src`、`tests/coding` 与 `scripts/gui`，并把脚本中的临时 checkout 和构建路径替换为同一基线构建的 Web 可执行文件与 `gui/dist`。独立服务重启脚本复用了 `tests/coding/test_rust_web_apphost.py` 的场景，将请求对齐到当前 `viewId` 和创建身份合同。

复核对照 [GUI 边界合同](drafts/gui-system-context-and-boundary-contract.md)、[Web 共享适配器](gui-web-host-interface.md)和 [AppHost G13](apphost/durable-hosted-application-continuity-g13.md)。Codex 对本轮检查的生产路径负责。这份证据不代表用户对阶段关闭作了验收决定。

## 平台与部署

- **Linux Rust Web + Chromium，PASS。** 界面使用生产资源。Managed supervisor 场景另以真实独立服务进程复核重启行为。`127.0.0.1` 是本机 HTTP 验收。
- **Linux Tauri 窗口，PASS。** Debug 原生窗口实际加载生产前端资源，通过独立 AppServer 连接。实测发送、在 Interrupt 可用时读到部分回复、在两个 Session 间往返并读回原 Transcript、创建 Goal 并执行 Step。X11 观察确认关闭窗口后窗口隐藏而进程仍在。通过同一个测试进程导出的真实托盘菜单触发 Show window，重新显示的是原窗口。触发 Quit 后 GUI 以 0 退出，独立 Host 保持同一 PID 并继续提供 Mux。独立 AppClient 探针覆盖连接释放、同一 Mux 冲突和重新取得。见 `native-tray.log`、`native-steps.log` 和 `probe.log`。
- **Windows，NOT_TESTED。** [历史可见窗口记录](../../../gui/tests/playback/windows-live-apphost-acceptance.md)只作为历史证据。本轮未启动 Windows 窗口或验证安装包及缩放。
- **macOS，NOT_TESTED。** [G17 既有原生机制证据](apphost/hosted-session-workflow-g17-darwin-native-manifest.json)属于历史 Hosted/TUI 范围。本轮没有 macOS Tauri 窗口或打包证据。
- **远程，跨机器 NOT_TESTED。** [当前支持方式](../../../gui/README.md)是 AppServer 单独发放 app-only 凭据，Rust AppClient 连接客户端转发到的 loopback port，由外部 SSH 保护传输。服务生命周期仍在 Host 上控制。本轮真实 loopback TCP 测试通过，验证 app-only listener 使用独立凭据并拒绝停止操作。未建立跨机器 SSH forward、远端原生窗口或对外 HTTP/TLS 服务。

## 质量与风险

- Python 定向测试 133 项通过，含 Goal、Execution、Registry、发现和审批。传输与 AppService 20 项通过。Ruff 和 AppService mypy 通过。GUI TypeScript 与 144 项 Vitest、Rust Web/AppClient 与 Tauri 测试及 Clippy、C1 三语言协议（101 接受、194 拒绝）、生成文件与 i18n 检查通过。
- **Baseline。** `npm --prefix gui run check:full` 停在 `gui/src-tauri/src/tray.rs:188` 的格式差异。Managed Coordinator mypy 在 `coordinator.py:175,382` 两处仍把可空状态交给 `recover_exited`。lmux 的 `test_real_product_projection_matches_recipe_window[0]` 仍因测试替身缺少 `_user_choice` 失败。三个问题均在本轮基线实际复现，日志为 `gui-check.log`、`python-static.log`、`baseline.log`。
- **P0/P1。** 在已执行的 Linux Web/Host 路径中未复现错误授权、数据损坏或重复副作用。旧日志损坏、关联缺失、orphaned 或未知副作用仍需核对原工作区，不能以历史完成计数代替核查。跨重启重获原 Goal 执行所有权仍未实现，版本归属见结论。
- **P2。** 工具审批场景首次打开项目草稿时，日志记录一个 `visit` HTTP 503，随后实际 Session 首发及审批均完成。可在独立空项目中复跑 `approval-managed.py` 定位此导航回执。
- **下一步。** 按发布范围决定是否补测 Windows、macOS 或两机转发。若发布要求重启后续跑原 Goal，单独设计 owner 重新准入和未知副作用的人工确认边界。
