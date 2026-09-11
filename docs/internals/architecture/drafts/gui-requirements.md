# Loushang GUI 需求：功能与非功能

## Status

- ID: `GUI-REQ-V2`
- Scope: Loushang proposed HarnessGUI on the G16 detachable AppHost application
- Parent: Loushang
- Authority: normative — proposed requirements; not an accepted scope contract
- Design status: proposed
- Implementation status: not-started
- Owner: Loushang architecture / future GUI requirement owner
- Source baseline: `3c06f5b9`, inspected 2026-09-08
- Execution contract update: `d89c4c9f` on `main` (PR #580), inspected 2026-09-09
- Target architecture: [Loushang Future Target Architecture V3.1](future-loushang-architecture-v3.1.md)
- Design stage: requirements; placement and component design follow separately
- System context: [GUI system context and boundary contract](gui-system-context-and-boundary-contract.md)
- Reference evidence: [GUI reference system inventory](gui-reference-system-inventory.md)

本文是第一步需求设计，描述用户结果、质量约束和验收条件。具体组件、目录、
接口字段、状态机和测试驱动由后续设计确定。以下需求尚未成为已接受 Target，
也不代表已有 GUI 实现；评审通过与运行验收分别记录。

继承 [架构方法](../../architecture-method/README.md)、
[项目治理规范](../governance-profile.md) 和
[系统原则](../loushang-architecture-principles.md)。
[工程启动方案](gui-engineering-bootstrap-plan.md) 负责交付编排与技术准备，
[已有评审](gui-engineering-bootstrap-review.md) 是该计划的评审证据，不是本文
需求已经评审通过的证明。

V2 增量从 Codex App 参考材料补充多任务可见性、工作上下文、环境与权限信息、
只读变更审查和 pane continuity，并按用户方向固定既有 AppHost 与单一
HarnessGUI。桌面 GUI 不再建立第二个 Host；它与
G16 detachable HarnessTUI Hosted Mux 作为 peer presentation 复用同一长期运行的
AppHost/AppService application；G15/G17 foreground launcher 仍拥有其 child/退出
结算语义，HarnessTUI Embedded 保留直接嵌入路径。参考材料只提供候选和证据；
新增条目仍是 proposed，必须由 Loushang owner 接受后才能成为 Target。

## 1. 目标与需求来源

目标是在既有 Product-neutral `AppHost` 上增加一个可独立开发、可自动回放、
可在三平台协作维护的 Loushang 桌面 GUI client，而不新建 Desktop GUI Host。
G16 detachable HarnessTUI Hosted Mux 与 GUI 是共用同一个长期运行
AppHost/AppService application 的 peer presentation。首期沿用 G16：不同 client
可控制不同 mux，同一 mux 仍只有一个 controller，第二个 attach 返回
`already_attached`；不新增 observer 或 takeover。HarnessTUI Embedded 则继续直接
借用 Product/Harness conversation，不经过 AppHost/AppService。G15/G17 foreground
`loushang-hosted-tui` 继续由 controller 拥有 child，不能用来证明 GUI 关闭后共享
application 仍存活。首期不建立 Coding、Design、Research、Work 等 Product GUI
surface；Product 仍是 AppHost 后方的运行时 binding，不因此成为前端分区。
HarnessGUI 与 Hosted Mux 对服务公开的 `workspace`、`changes`、`artifacts` 等
可选能力使用同一 HarnessClient 合同族，表现形式可以不同，事实与权限不能分叉。

| 来源 | 已知输入 | 本文处理 |
| --- | --- | --- |
| 用户明确方向 | Rust 桌面方案，Tauri + React；GUI 与 AppService 可以并行开发 | 作为技术与交付约束，不按技术库名称预先划分组件 |
| 用户明确方向 | GUI 展示文档；浏览器独立窗口，由浏览器/coding 插件操控 | 首期只读文档展示，浏览器执行留给后续产品能力 |
| 用户明确方向 | GUI 可以像现有 TUI playback 一样自动回放 UI | 首期拟以开发测试回放为基线；GUI 内播放控制的范围见 GUI-OQ-001 |
| 用户明确方向 | macOS、Windows、Linux 可以同步协作开发 | 三平台从工程基线进入正式开发与验证范围 |
| 用户补充方向（2026-09-09） | GUI 主要在 Windows 或 macOS 真实图形环境机器开发，方便边开发边 playback | 从 B0/B1 开始提供本机原生开发/回放入口；保留 Linux 支持与三平台验证，不延后到最终验收才迁移 |
| 用户补充方向（2026-09-09） | 先整理系统环境图和黑盒需求，参考 Codex App 界面 | 先登记参考事实、外部关系和用户结果；不从界面布局反推组件或隐含权限 |
| 用户最终方向（2026-09-09） | 暂不考虑 Coding GUI，只有 HarnessGUI；仓库、Diff、worktree 是通用能力；GUI 与 Hosted Mux 共用接口族 | 取消首期 Product GUI/presentation contribution 分区；通用能力由服务端 capability 与版本化 HarnessClient facet 声明，两个前端均可消费 |
| 用户补充方向（2026-09-09） | Desktop GUI Host 使用既有 AppHost，并与 TUI 共用同一个；HarnessTUI 有 Hosted Mux（tmux）和 Embedded 两种形态 | 删除第二个 GUI Host 概念；GUI 复用 G16 detachable application 及其 Hosted Mux shell，Embedded 保持直接 Product/Harness 路径；G15/G17 foreground child lifecycle 不冒充可共享 Host |
| Codex 官方参考 | 桌面工作区组织项目/会话、长期工作、文件结果、review、terminal 和 worktree | 采用多任务可见性、上下文/来源可信和只读 review 问题；可变 Git、终端、Handoff 等能力保留后续 |
| 用户提供截图 | 可见状态同时呈现任务导航、主对话/输入、环境、变更和来源 | 作为单状态观察证据；不冻结三栏布局、标签、图标或隐藏行为，截图不入库 |
| 已有工程方案 | Mock 优先、同机 AppService 接入、真实原生验证、发布另行交付 | 作为本稿的阶段基线，保留外部契约缺口 |
| 本稿细化建议 | 草稿隔离、键盘可达性、故障提示、性能场景和量化验收 | 拟议需求，可在评审时调整，不视为用户已逐项确认 |

首期主要使用者：桌面用户、GUI 开发者、回归验证维护者。首个可交付产品界面
统一称为 **HarnessGUI**；当前 hosted Product binding 只提供运行时语义，不建立
Product-owned 前端。AppHost 继续对 G16 detachable
HarnessTUI Hosted Mux 和 GUI 保持 Product-neutral、UI-neutral；Embedded TUI
仍是独立的直接组合形态，G15/G17 foreground lifecycle 也不因 GUI 而改变。
GUI 展示需求不改变已有 Product、Session、Plugin 与执行权限的权威来源。
“工作空间”在本文仅指用户可选择的会话集合；其与现有 mux/workspace 的映射
留给边界设计，不能由界面名称推导新的持久化实体。
“工作上下文”是用户辨认长期任务来源所需的项目、目录或 Product 背景；会话是
一次可持续交互的独立对话，工作空间是当前服务提供的会话组织。工作上下文不
等于 mux、Git worktree 或 Session，也不要求 GUI 新建项目数据库或跨项目运行时。
GUI 可以同时显示多个事实，但每项须保留自己的 owner、identity 和新鲜度；具体
映射见边界合同。

## 2. 范围与优先级

- **首期必须**：GUI-B0 至 GUI-B3 的退出要求；标记 B1/B2 的条目分别先取得
  样例/Mock 证据，再取得真实服务证据。
- **后续候选**：保留用户方向或扩展需求，不计入首期完成条件。
- **待定**：仍需确认的产品取舍或实施基线；明确决策阶段，不用空白冒充完成。

阶段沿用工程计划：B0 工程与三平台启动，B1 独立界面与回放，C1 跨语言契约
准备，B2 各平台本机真实连接，B3 桌面开发验收。此处是需求验收的对应关系，
不预先确定组件分工。全部功能与非功能需求均为首期必须，除非单独标为后续。

## 3. 功能需求

| ID | 用户可观察的需求 | 最小验收条件 | 首次证据 |
| --- | --- | --- | --- |
| GUI-FR-001 | 独立启动与离线体验：未启动后端时也能打开 GUI，使用明确标注的样例体验基本交互 | 无后端、无真实模型请求时可打开界面、阅读样例并运行 Mock 场景；样例状态不会显示为真实会话 | B0/B1 |
| GUI-FR-002 | 工作上下文、工作空间与会话导航：在已知项目/目录背景中选择服务可见的会话集合，创建、打开或切换其允许操作的会话 | 工作上下文、application、mux/member 与 Session 不被折叠成同一 identity；至少两个会话切换时消息、状态、草稿和后续操作对象归属正确；空列表、失效对象与控制冲突可解释 | B1/B2 |
| GUI-FR-003 | 文本输入：支持中文/英文、多行编辑、粘贴、选择、复制及显式发送 | 输入法组合过程中不误发送；用户提交的文本不丢失、不被无提示改写；切换会话后未发送草稿仍与原会话绑定 | B1，原生输入 B3 |
| GUI-FR-004 | 会话输出与运行反馈：显示用户输入、流式输出和服务提供的运行/终止结果 | 同一消息不会因流式片段重复追加；服务未确认完成时不显示成功；本地发送中、服务运行中、失败及结果未知可区分 | B1/B2 |
| GUI-FR-005 | 运行中控制：用户可请求中断，并使用服务合同支持的继续输入方式 | 长任务尚未返回时中断入口仍可用；补充当前任务与排队后续任务的语义清楚；请求失败不会伪装为已执行 | B1/B2 |
| GUI-FR-006 | 待处理交互：显示服务要求用户回答的审批或选择，并提交合法答复 | 显示请求对象、可选操作和当前有效性；失效或已答复的请求不能再次授权；服务拒绝答复时可解释 | B1/B2 |
| GUI-FR-007 | 文档阅读：只读展示 Markdown、纯文本、代码、Diff 和图片内容 | 首期格式清单见下文；支持选择/复制适用文本与滚动；内容变化、窗口缩放不造成正文错序或无故清空 | B1；真实来源按契约验收 |
| GUI-FR-008 | 文档入口与状态：可打开用户明确选择的本地文档，或查看产品提供的结果引用 | 来源可辨认；无法读取、格式不支持、内容过大或结果缺失时有明确状态；查看文档本身不修改项目文件 | B1；产品来源后续补充 |
| GUI-FR-009 | 连接状态与故障恢复：用户能理解未连接、连接失败、控制冲突和需要重新同步的状态，并发起重新连接 | 断线或事件缺口不继续显示旧状态为实时事实；恢复后结果与新的服务端快照一致；不自动重发发送/审批等操作 | B1/B2 |
| GUI-FR-010 | 桌面基本操作：支持窗口调整、文字缩放、焦点切换和稳定阅读位置 | 查看历史时新输出不强制抢走阅读位置；可以显式返回最新内容；缩小窗口仍可到达输入、状态和核心操作 | B1/B3 |
| GUI-FR-011 | 退出与分离：关闭 GUI 能结束自身连接，并让用户理解服务仍可能继续运行 | 关闭窗口不等价于停止应用服务；重开后读取当前事实；不会恢复已失效的审批；不承诺跨崩溃恢复未持久化草稿 | B2/B3 |
| GUI-FR-012 | 自动回放：维护者可保存、选择并重复执行一组 GUI 操作场景 | 场景表达输入、事件、等待和逐步断言；可自动操作界面并报告通过或失败；默认离线，不依赖真实模型或浏览器插件副作用 | B1 |
| GUI-FR-013 | 回放证据查看：维护者可定位失败步骤并查看对应状态、画面和日志 | 每次运行可关联场景版本、构建来源和执行环境；失败步骤可定位；证据可通过本地产物查看，首期不要求应用内时间线播放器 | B1 |
| GUI-FR-014 | 会话状态总览：无需逐个打开会话即可知道哪些会话正在运行、等待答复或有未读更新 | 当前 attachment 覆盖的会话集合可显示服务已知的运行/终止/有效交互状态和 GUI 本地未读状态；点击定位到对应会话；断线标陈旧，不能把未运行猜为成功完成 | B1/B2 |
| GUI-FR-015 | 工作上下文与执行环境可见：用户采取操作前可以辨认当前项目/目录背景、application、mux/member/Session，以及服务公开的 Local/Worktree、仓库、分支或版本信息 | 每项显示值保留来源和新鲜度；协议未提供的值显示 unknown/unavailable，不从目录名或选中页推断；上下文变化后旧页面不能向新对象静默提交 | B1 fixture；真实来源按 C1/B2 合同验收 |
| GUI-FR-016 | 权限与能力可见：展示服务公开的连接 profile、控制状态、模型/执行策略、审批模式和工具/来源能力，并只允许合同支持的改变 | 可用、只读、未知和不支持可区分；显示权限不等于授予权限；服务不支持选择时不提供假选择器；旧 generation 或断线后可变操作立即冻结 | B1 fixture；真实来源按 C1/B2 合同验收 |
| GUI-FR-017 | 工作区变更概览与只读审查：用户能辨认是否有变更、查看具名范围的文本 Diff，并知道内容来源和版本 | 区分工作树、暂存区、提交、分支或轮次等实际支持的 scope；不得把仓库全部修改归因于当前 Agent；无权威来源时显示 unavailable；首期不暂存、回滚、提交或推送 | B1 fixture；B3 必须用已接受的 Harness workspace/change provider 取得真实证据 |
| GUI-FR-018 | 共享 HarnessClient 能力一致性：服务公开的 `workspace`、`changes`、`artifacts` 等可选 facet 对 HarnessGUI 与 G16 Hosted Mux 使用同一版本、identity、来源、revision 与错误语义 | B1 双 client fixture 证明 capability 出现、缺失、版本不相容和撤销时，两端解释一致；能力是否可用只由服务端声明，不按 GUI/TUI 类型分配；两个前端可以采用不同表现但不得建立第二个事实 owner | B1 fixture；C1/B2 真实合同证据 |
| GUI-FR-019 | 同一 G16 detachable AppHost application 的多前端一致性：HarnessTUI Hosted Mux 与 GUI 通过各自 client scope 使用同一已准入 Product application，且不复制 Product Runtime 或另建 GUI authority；Embedded 与 G15/G17 foreground 不属于该共享生命周期 | B1 双 client fixture 验证投影与本地状态隔离；B2/B3 证明两个真实 client 可控制不同 mux，同一 mux 的第二次 attach 返回 `already_attached` 且不改变 generation，detach/连接关闭只释放本 client scope，已接受工作继续；重连以 fresh generation/snapshot barrier 恢复；草稿、焦点、滚动不互串；不提供 observer 或 takeover | B1 双 client fixture；B2/B3 真实 G16 共享 application 证据 |

首期文档格式基线（拟议）：Markdown 的标题、段落、列表、引用、链接、表格、
代码块和图片；UTF-8 纯文本与代码；只读文本 Diff；PNG/JPEG 静态图片。
文件选择入口、页面布局与语法高亮方案不在需求阶段冻结。其他格式明确提示
不支持；禁止用“打开文档”隐式进入通用浏览器、编辑器或脚本执行环境。

GUI-FR-003 的草稿保证限应用存活期间的切换和短暂连接变化；应用崩溃/退出后的
草稿持久化是后续候选。GUI-FR-002 不承诺跨重启历史 Session 发现；GUI-FR-007
在 B1 的 Diff/图片证据只验证展示能力，不代替真实产品数据接入。
GUI-FR-007/010 还要求阅读文档或 Diff 时可继续查看会话状态、返回输入并请求
中断，不因打开内容丢失对话与阅读位置。具体采用并排面板还是可切换视图由交互
设计确定。文档、Diff 的来源和读取版本须可辨认；没有可信的行号或版本时不能
伪造精确定位。此处不增加文件编辑、Git 暂存/回滚或提交功能。

GUI-FR-007/010/017/018/019 还要求打开文档、Diff、workspace、changes 或 artifact 面板时，
会话状态、草稿、阅读位置和运行中控制仍可到达；具体采用并排面板还是切换视图
由交互设计决定。
GUI-FR-015/016 不要求当前 App Contract 已经拥有全部显示字段，而是把缺口变成
显式合同责任；Mock 值必须标为 fixture，不能用它声称 B2 已完成。

## 4. 非功能需求

| ID | 质量要求 | 可验证条件 | 首次证据 |
| --- | --- | --- | --- |
| GUI-NFR-001 | 三平台可开发与可运行 | Linux/macOS/Windows 各有具名 OS/CPU 基线；可独立初始化、开发和构建；B1 各平台通过最小真实桌面回放，B2 各自连接本机服务 | B0–B3 |
| GUI-NFR-002 | 交互可用性与基本可访问性 | 核心操作可用键盘到达和执行，焦点可见且无陷阱，控件有可访问名称；中文输入、系统剪贴板、文字缩放通过真实桌面检查 | B1/B3 |
| GUI-NFR-003 | 响应性能 | 固定负载下普通文本输入到可见更新 p95 初始目标 ≤100 ms；持续输出时仍能编辑、切换和请求中断；按 §4.1 单独记录代理计时与真实呈现 | B1/B3 |
| GUI-NFR-004 | 状态、上下文与操作正确性 | 不丢输入、不重复消息、不跨会话/环境污染；重复/迟到/缺失事件和上下文替换均有验收场景；未知结果、权限和来源不猜测；恢复期间禁止依赖旧状态的操作 | B1/B2 |
| GUI-NFR-005 | 并发与故障隔离 | 长 turn 等待不阻塞事件、审批和中断；普通请求容量耗尽时控制操作仍可达；单个文档渲染失败不使整个会话界面不可用 | B1/B2 |
| GUI-NFR-006 | 资源有界与生命周期收敛 | 消息展示缓存、事件缓冲、待处理请求及文档大小均有明确上限与超限行为；重复打开/关闭后 GUI 自有连接和监听能释放；慢消费不能无限累积 | B1/B2 |
| GUI-NFR-007 | 本机权限与内容安全 | 仅经许可入口读文档；不因文档脚本/链接/结果引用取得执行权限；客户端凭据不可由文档读取；首期不因渲染文档自动访问外部资源 | B1/B2/B3 |
| GUI-NFR-008 | 可重复测试与证据可信 | 同一平台/构建/fixture 的必需场景重复运行，逐步状态断言一致；原生测试实际经过桌面与 Rust 交互；缺环境、零场景或跳过不能算通过 | B1/B2 |
| GUI-NFR-009 | 可诊断与隐私 | 连接、同步、交互和回放失败有可定位原因；诊断默认不包含认证秘密；真实内容录制需明确启用和保存范围，测试默认使用可入库样例 | B1/B2 |
| GUI-NFR-010 | 可复现协作 | 三平台通过 Git 同步源码、场景与依赖锁；按固定工具版本各机安装和编译；操作入口语义一致，Windows 原生开发不依赖 WSL/Bash/Make | B0/B1 |
| GUI-NFR-011 | 跨语言与版本兼容 | 合法/非法请求、事件和边界值在 Python/Rust/前端间解释一致；大整数不损失精度；不支持的协议/能力明确拒绝或降级，不静默猜测 | C1/B2 |
| GUI-NFR-012 | 可维护与可演进 | 文档展示、测试与平台差异不迫使 AppService 导入 GUI；改变表现形式不改变执行权威；关键需求可追溯到合同、代码与验证场景 | 后续设计/C1/B2 |
| GUI-NFR-013 | 多前端与能力隔离 | AppHost 不导入 TUI/GUI；G16 detachable Hosted Mux 与 HarnessGUI 只通过各自 AppClient adapter 共享服务事实，Embedded TUI 不被重定向，G15/G17 foreground owner 不被绕过；两个前端不硬编码 Product 专属 UI，也不读取彼此的本地状态；可选 facet 使用有界、版本化合同，不能取得 ambient service locator、AppClient secret、任意文件或额外执行权限 | B1 fixture；C1/B2 真实共享 Host/capability contract evidence |

### 4.1 性能与容量验收口径

GUI-NFR-003 的 100 ms 来自现有工程方案，是待校准的初始目标，不是测量结果。
建议 B1 以以下离线 fixture 开始建立负载基线，再评审固定数据摘要：

| 场景 | 拟议基线 | 主要观察 |
| --- | --- | --- |
| 日常输入 | 100 条固定消息，输入中文/英文/换行/emoji | 输入延迟、焦点、字符与发送次数正确性 |
| 流式长会话 | 1,000 条固定历史消息，每条约 512 字符；30 个增量/秒，持续 60 秒 | 编辑和控制响应、阅读锚点、缓冲与展示资源有界 |
| 文档与生命周期 | 1 MiB 固定文本；重复切换会话、打开/关闭文档及连接 | 文档可读性、恢复正确性、自有资源释放与内存趋势 |

以上是 GUI 展示负载，不要求 AppService 一次返回等量快照，也不隐含扩展 wire
消息上限。性能采样须给出硬件、OS/WebView、发布/测试 profile、预热与样本数；
普通输入每个声明基线至少收集 200 次有效样本。性能使用真实单调时钟，不能
使用快进的测试时钟。DOM 更新/下一帧回调只是代理指标，自动化 driver 往返
只是操作耗时；真实呈现的测量方法须在 B1 明确，代理指标不能代替它过门禁。

启动耗时、内存绝对上限、最大文档/历史规模和队列预算在 GUI-OQ-003 中跟踪。
在这些预算冻结前不能宣称完整性能/容量验收通过；不妨碍先设计正确性与资源
上限机制。各平台结果分别保留，系统 WebView 差异不能被平均值掩盖。

### 4.2 关键黑盒质量场景

以下稳定 ID 归本需求所有。系统环境、合同、ARD、组件模型和评审引用这些定义，
不复制另一套 canonical 场景。尚未接受的度量按本需求的 proposed 状态处理。

| ID | Source / stimulus / environment | Artifact and response | Measure / pass rule |
| --- | --- | --- | --- |
| `GUI-QS-001` | 桌面用户在已连接、包含会话 A/B 的 GUI 中，于 A 正在运行时切换到 B 并继续编辑 | GUI 工作区保持 A/B identity、草稿和状态隔离；A 的更新只改变 A 的投影和总览 | B 文本不被 A 的迟到结果改变；无需打开 A 即可定位其待答复/未读状态 |
| `GUI-QS-002` | AppServer transport、事件源或服务 authority 使已连接 GUI 的当前 attachment 断线、事件跳号或 generation 失效 | GUI 标记受影响事实陈旧，冻结发送、审批、`close_mux`/`close_member` 等服务端旧权威 mutation 并建立新屏障 | 新屏障前零次依赖旧 token 的 mutation；不自动重放未知结果请求；不把这些操作与关闭 GUI 窗口混淆 |
| `GUI-QS-003` | 具有已接受 authoritative 变更来源的 Git-backed Harness workspace 中，用户、Agent 或外部工具同时修改工作树 | 变更视图显示所选 Git scope 和来源版本，不把仓库全部修改归因于当前 Agent | 每个展示 diff 有可辨认 scope；无法建立来源时显示 unavailable/unknown；B3 使用真实来源取证 |
| `GUI-QS-004` | 用户在分支、checkout 或项目上下文变化后，从保留的旧 GUI 页面尝试操作 | GUI 重新核对服务与环境 identity，保留不可发送草稿并解释失配 | 不向不同 Session/checkout 静默提交；任何迁移必须由已接受合同完成 |
| `GUI-QS-005` | 用户选择文档后，OS/文件适配器返回无权限、过大或读取中变化，或者内容解析器识别出主动内容 | 读取被拒绝或有界展示；会话输入、中断和状态仍可用 | 无脚本/远程资源自动执行；单文档失败不使会话工作区失效 |
| `GUI-QS-006` | AppService 新增、撤销 `workspace`/`changes`/`artifacts` capability，或其版本、provider generation 变为不相容 | HarnessGUI 与 Hosted Mux 保留基础会话能力，卸载或标记不可用的 facet，冻结其动作，只从新 generation 投影可用事实 | 零次旧 generation mutation；未知、不相容或失败 facet 不使基础会话失效；两端均可定位来源与失效原因 |
| `GUI-QS-007` | G16 detachable Hosted Mux 与 GUI 连接同一 AppHost application；二者分别控制 mux A/B，随后 GUI 尝试 attach 已被控制的 A、detach 并重连 | 两个 client 只经 AppClient/AppService 收敛到各自权威投影；A 的第二次 attach 返回 `already_attached` 且不改 generation；GUI detach 只释放自身 scope，已接受工作继续；重连安装 fresh generation/snapshot barrier；本地草稿/焦点不共享 | 无第二个 Product Runtime、observer/takeover 或 GUI authority；无跨前端草稿泄漏、Embedded/foreground 路径回归或因关闭 GUI 而停止 application |

## 5. 约束、依赖与当前缺口

| ID | 约束 | 对需求设计的影响 |
| --- | --- | --- |
| GUI-CON-001 | 首期采用 Tauri/Rust + React/TypeScript，与现有 Python 运行时同仓协作 | 技术方向已选；具体组件、数据流与边界仍按后续设计完成 |
| GUI-CON-002 | 首个真实连接显式使用本机 `local-detachable-execution/v1`；需要 G17 会话发现时使用 `local-detachable-discovery-execution/v1` | 继承 G16 本机认证、控制权与恢复边界；C1 核对 profile/capabilities/版本，不静默回退旧 start；各平台 GUI 与服务同机 |
| GUI-CON-003 | GUI 消费既有 Product/AppService 的执行、审批与 Session 事实 | GUI 退出、画面回放和界面缓存不能重新定义执行生命周期或成为事实存储权威 |
| GUI-CON-004 | 浏览器自动化由后续产品能力/插件负责，采用独立浏览器窗口 | GUI 可展示结果；不会因新增文档 pane 而拥有浏览器执行或会话寿命 |
| GUI-CON-005 | 开发者可运行与最终用户可安装是不同交付 | 首期验证开发者构建；公开发布、后端打包、签名、安装与更新另立交付 |
| GUI-CON-006 | GUI 只把公开合同、用户许可和受控本机适配提供的信息当作外部事实 | 项目/环境/分支/模型/权限/来源字段缺失时明确降级；不得通过 Python 内部对象或任意 shell 补齐 |
| GUI-CON-007 | 既有 G16 detachable AppHost application 是 HarnessTUI Hosted Mux 与 HarnessGUI 共用的唯一 Product-neutral、UI-neutral Host；不新增 Desktop GUI Host。HarnessTUI Embedded 仍直接组合 Product/Harness；G15/G17 foreground controller 仍拥有 child 与退出结算。HarnessGUI 与 Hosted Mux 是同一 HarnessClient 接口族的 peer presentation | AppHost core 不导入任何 UI，且只拥有 Product runtime/binding；AppService 保持 client-scope/attachment/controller/detach/reattach semantics 的唯一 owner；两个 G16 client 只经公开合同共享 application 事实，不共享 presentation state；首期保留 different-mux concurrency、one-controller-per-mux、`already_attached`、fresh reattach 和 normal-detach-not-stop 语义，不引入 observer/takeover |
| GUI-CON-008 | `AppClientV1` 保持会话/控制基线；`capabilities`、`workspace`、`changes`、`artifacts` 等可选 HarnessClient facet 使用封闭、版本化值合同 | facet availability、identity、source、revision、大小/分页、失效与错误由 AppService 和 exact capability provider 拥有；HarnessGUI 与 Hosted Mux 均可消费，服务端不得按前端类型制造两套语义；Embedded 可通过满足同一值语义的 in-process adapter 复用 |

当前 [AppClient](../../../../src/loushang/appserver/client.py) 已有 mux/member、
快照、turn、交互响应与事件操作；[G16](../appserver/detachable-local-workspace-g16.md)
明确本机身份、控制权与恢复语义。[PR #580](https://github.com/zhnt/loushang/pull/580)
已交付可选的 `loushang.execution/v1` 提交、查询、定向中断、复合快照和恢复参考；
真实 Coding 装配需要显式启用，默认行为保持不变。旧 `start_turn` 仍等待完成，
不将其 Ack 改成接收确认。具体 profile 选择见 [工程计划 §6](gui-engineering-bootstrap-plan.md)。
完整跨语言 payload、认证和本机记录兼容仍需 C1 的独立证据。
协议中未提供的能力不能通过读取 Python 内部对象补齐。

GUI-FR-004/005/009/014 在 execution 模式下消费明确的 accepted/running/终态，
无输出也能显示运行；成功来自服务结果，等待取消和连接断开不等于执行停止。
启动响应丢失时以原提交身份查询，显式重试保持精确文本与提交身份；服务实例
变化时保留未知结果，不自动重放。该行为属于首期执行接入，消息/工具条目身份
和跨服务重启的执行恢复仍是后续能力，详见边界合同 BC-004/006。

| 需求相关缺口 | 首期处理 | 后续责任与退出条件 |
| --- | --- | --- |
| 全局历史 Session 发现 | GUI-FR-002 只展示已连接服务可见且可操作的集合；G17 已提供有界 cwd/home 候选发现，但仅 execution profile 不含发现能力 | 按 GUI-CON-002 显式选择 discovery + execution 组合 profile 并取得 C1/B2 证据；全局跨 scope 列表仍不承诺，Mock 历史列表不算真实接入 |
| GUI execution 跨语言与原生接入 | 服务端已交付，首期按已提交 codec、JSON 样例和恢复参考设计 Mock 与真实客户端 | AppServer/GUI owners 完成 C1 的独立兼容测试与 B2 三平台闭环；Python 或 PR CI 通过不替代 GUI 证据 |
| 跨服务重启的执行登记与去重恢复 | 提交键保存到服务实例结束，实例变化保留未知结果；不自动重试或从 Session 历史推断执行登记 | 另行设计持久化、保存期限与重启保证；首期客户端遵守 `restartRecovery: false` |
| 完整工具/Diff/图片/Artifact 的结构化投影 | GUI-FR-007 先用本地样例验证渲染，GUI-FR-008 支持用户选定本地文档 | Product、Harness 与 AppService capability owners 提供明确来源、类型、大小、分页、权限和失效合同后，再验收真实结果 |
| 项目、环境、模型、策略、权限和来源投影 | GUI-FR-015/016 可用明确 fixture 设计状态；真实界面只显示当前公开事实 | Harness/AppService capability owner 冻结 identity、版本、可变性和错误合同后，取得 C1/B2 证据 |
| Git 变更事实来源 | GUI-FR-017 在 B1 先验证只读展示、scope、unavailable 降级与归因规则；B3 仍要求真实来源 | `loushang.harness.workspace` 作为 authoritative mechanism owner；AppService/AppContract 提供只读 Workspace/ChangeSet facet，并取得真实仓库证据后完成首期 |
| 共享 HarnessClient 可选 facet | GUI-FR-018 在 B1 用双 client fixture 验证 capability、来源、版本与失败隔离 | AppService 冻结 capability discovery；Harness exact provider 冻结 Workspace/ChangeSet/Artifact schema、revision、分页和失效合同；GUI/TUI 不另建 frontend-specific authority |
| G16 detachable HarnessTUI Hosted Mux 与 GUI 共用同一 AppHost application | GUI-FR-019 在 B1 用两个 client fixture 验证投影与本地状态隔离；B2/B3 复用已定义的 different-mux concurrency、one-controller-per-mux、`already_attached`、normal detach 和 fresh reattach；Embedded 与 G15/G17 foreground 不进入该共享生命周期 | AppService 保持 client-scope/attachment/controller/detach/reattach semantics 的唯一 owner；AppHost 只证明 runtime/binding 未复制；AppClient/HarnessTUI/HarnessGUI 提供两个真实 client 使用同一 G16 application 的证据；同 mux observer/takeover 保持非目标，若要新增则独立设计 |
| 远程 AppService 与远端浏览器可视访问 | 首期同机服务；远端 GUI/浏览器通过远程图形会话观察 | 新连接 profile 和权限边界需独立设计 |
| 发布包的 Python 后端分发 | 使用各机显式配置的开发后端 | 产品发布范围另行确定，不用开发机 `.venv` 充当发行包 |

## 6. 非目标与后续候选

首期非目标：

- 嵌入通用浏览器、自动操控 GUI WebView 浏览网页；
- 完整 IDE、文件编辑器、终端模拟器或 PDF/Office 全格式应用；
- Git 暂存、回滚、提交、推送、分支切换、worktree 创建或 Handoff；
- 新建 GUI 自有 Agent loop、权限系统、服务端 Session 数据库或插件运行时；
- Coding/Design/Research/Work 等 Product-specific GUI surface，或动态 presentation contribution；
- 把 HarnessTUI Embedded 强制迁移到 AppHost，或把 Hosted Mux 与 Embedded 合并成一条生命周期；
- 改写 G15/G17 foreground child ownership，或为同一 G16 mux 新增只读 observer/显式 takeover；
- 远程多用户服务、跨机器共享实时 Session、云端同步凭据和会话数据；
- 全平台像素完全相同，以及所有 OS 版本、CPU 架构和输入法组合的兼容承诺；
- 公开发行、自更新、系统服务安装、自动安装或升级 Python 后端。

后续候选：浏览器插件接入与结果面板、契约支持后的历史发现和富产物、跨重启
草稿恢复、完整屏幕阅读器验收及界面本地化。主题、布局与快捷键的可配置深度
在后续交互设计明确，不作为首期无限扩展的承诺。GUI 内回放控制见下表。

以下细化方向保留稳定 ID，均为**后续候选**，不计入首期必须；进入实施前补充
正式需求、产品合同与验收证据：

| ID | 候选用户结果 | 进入实施所需条件 |
| --- | --- | --- |
| GUI-FUT-001 | 按轮次查看消息、工具执行和文件变更，并从结果定位对应执行条目 | 已交付 execution ID 可关联完整执行；消息/工具条目 ID、文件变更引用和富条目投影仍需 Product/AppService 扩展，界面分组不能假装已有这些字段 |
| GUI-FUT-002 | 针对文档或 Diff 的具体位置提交反馈并跟进修正 | 明确来源版本、行/片段定位、失效处理及产品命令；反馈提交与立即执行修改分开 |
| GUI-FUT-003 | 后台运行时收到可配置的任务完成、待审批/回答通知 | 三平台系统通知准入与隐私策略；点击回到会话后重新校验交互有效性，不从通知直接授予旧权限 |
| GUI-FUT-004 | 固定、搜索、重命名、归档和恢复长期项目/会话 | 全局发现、稳定标题/归档 identity 与持久化 owner 明确；组织操作不得改变执行 authority |
| GUI-FUT-005 | 在当前项目或 worktree 中使用集成终端和可复用动作 | 独立 shell owner、cwd、环境、sandbox、凭据、输出预算和关闭合同 |
| GUI-FUT-006 | 暂存/回滚/提交/推送选择的 Git 变更 | Git authority、原子范围、确认、冲突、恢复和审计合同；不并入只读文档入口 |
| GUI-FUT-007 | 创建或迁移 Local/Worktree 工作，并保持会话连续 | Git worktree 生命周期、ignored 文件、branch ownership、清理/恢复和 handoff 合同 |
| GUI-FUT-008 | 扩展更多通用 Harness capability/provider，并让 GUI、Hosted TUI 与 Embedded TUI 保持可比语义 | 先接受版本化 facet、exact provider owner、capability discovery、聚合/冲突、分页/容量、失效和 generation retirement 合同；不通过 Product-specific GUI 绕过共享接口 |

GUI-FR-012/013 的回放继续用于确定性 UI 验证；录制用户业务操作并生成技能、
重新执行真实工具属于不同的后续产品能力，不并入 GUI 测试回放。

## 7. 待定项与决策时点

| ID | 待定内容 | 当前处理 | 最迟决策时点 |
| --- | --- | --- | --- |
| GUI-OQ-001 | 首期 playback 是否需要应用内播放/暂停/逐步查看面板 | 暂按开发测试回放与本地产物查看；界面播放器需单独确认，尚未列为必须 | 功能需求确认前；不阻塞其余需求梳理 |
| GUI-OQ-002 | 三平台最低 OS/CPU、窗口最小尺寸、字体缩放与语言基线 | 三平台均必须支持，每系统至少一个具名环境；具体版本和配置留待环境盘点 | B0 退出前 |
| GUI-OQ-003 | 启动、内存、文档/历史最大规模、队列上限及真实呈现测量方式 | 保留 100 ms 初始目标与拟议负载，不把未测数字写成已验证预算 | B1 性能/容量验收前 |
| GUI-OQ-004 | 真实富产物与历史发现的合同和交付范围 | 本地展示可先行；真实接入单独验收，不作为现有 B2 完成承诺 | 对应真实功能进入设计前 |
| GUI-OQ-005 | Workspace/ChangeSet facet 的 exact schema、分页/容量、revision 与失效规则 | authoritative mechanism 已固定为 `loushang.harness.workspace`，取数经 AppService/AppContract；待收敛值合同，不建立 GUI/TUI 双重 owner | C1 schema/contract 冻结及真实接入前 |
| GUI-OQ-006 | 工作上下文、环境、模型、策略、权限和来源的公开字段与可变性 | 当前只显示已知值和 unknown；不从内部对象、路径或 UI 选择推断 | C1 schema/contract 冻结前 |
| GUI-OQ-007 | 首期是否需要 GUI 自有项目索引，以及固定/搜索/归档范围 | 默认无 GUI 项目数据库；保持为 GUI-FUT-004 | scope acceptance 或历史导航进入设计前 |
| GUI-OQ-008 | 一个 HarnessGUI 进程/窗口如何组合会话、workspace、changes 与 artifact pane，并隔离多工作上下文的草稿和阅读状态 | 候选发现比较单窗口多 pane、多工作区与多窗口；不把视觉 tab 当作 Session/worktree 迁移或 capability admission | 接受 GUI placement/component model 前 |
| GUI-OQ-009 | 未来是否允许 HarnessTUI Hosted Mux 与 GUI 同时观察或显式 takeover 同一 mux | 首期不新增：G16 已定义 one-controller-per-mux，第二个 scope 得到 `already_attached`，read-events/snapshot 也不能越 scope；共用 AppHost 只先支持不同 mux 的并行控制和断开后 fresh reattach。Embedded 与 G15/G17 foreground 不进入该决定 | 若 observer/takeover 被提升为需求，在其 C1/实现前独立接受；不阻塞 GUI-FR-019 按现有 G16 语义验收 |

## 8. 需求验证与下一步

需求阶段完成条件：功能与质量要求有稳定 ID、用户结果、可观察验收条件、
阶段与缺口；已有约束来源可追溯；未把尚未设计的组件、协议或安装流程当作
需求事实。待定项有明确的决策时点。

后续每项首期需求建立“需求 → 边界/合同 → 组件 → 代码 → 测试/回放证据”的
追溯关系。本阶段尚未识别组件或实现测试，不能填写虚构的映射或测试通过数。
黑盒阶段的拟议职责与合同、需求追溯和待补能力现见
[GUI 系统上下文与边界合同](gui-system-context-and-boundary-contract.md)；
该文不改变本文的 proposed 状态，也不代表已有 GUI 实现。
GUI-FR-012/013 是开发者使用的验证功能，GUI-NFR-008 约束其确定性与可信度，
两者分别验收；仅有最终截图不足以证明状态和操作正确。

下一步依次为：评审并确认 [参考系统清单](gui-reference-system-inventory.md)、
[系统上下文与边界合同](gui-system-context-and-boundary-contract.md) 和本需求范围；接受单一 HarnessGUI、
共享 HarnessClient facet、共用 AppHost 关系与关键黑盒边界后，再进行候选组件发现、
功能映射与收敛。此次不新增 GUI 运行入口、不改变 AppHost/AppService。
