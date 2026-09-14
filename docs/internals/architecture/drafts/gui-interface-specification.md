# HarnessGUI 界面规约

## Status

- ID: `GUI-UI-SPEC-V1`
- Scope: Loushang proposed HarnessGUI
- Parent: Loushang
- Authority: normative — proposed user-interface specification
- Design status: proposed
- Implementation status: partial
- Owner: Loushang architecture / future GUI owner
- Implementation baseline: `ed204d4f`, inspected 2026-09-10
- Requirements: [Loushang GUI requirements](gui-requirements.md)
- Boundary: [GUI system context and boundary contract](gui-system-context-and-boundary-contract.md)
- Reference evidence: [GUI reference system inventory](gui-reference-system-inventory.md)

本文冻结 HarnessGUI 候选界面的可观察信息架构、区域、状态、操作和降级行为，
使设计可以被实现和回放验证。本文不选择新的服务端事实 owner，不新增
AppService 权限，也不把参考系统的视觉结构解释成 Loushang 的运行时合同。

本规约接近采用 Codex desktop 的桌面布局语法，但使用 HarnessGUI 自己的领域
术语、能力合同和状态来源。它不复制 Codex 品牌、商标、图标资产或未经验证的
隐藏行为。本文尚处于 proposed；布局实现存在不代表本文已经被接受。

## 1. 输入、证据与决定

| 类型 | 本规约使用的输入 | 能够支持的结论 | 不能支持的结论 |
| --- | --- | --- | --- |
| 用户方向 | Workspace 分组的 Session 导航；活动 Session 转圈；中央 Task 步骤；可展开 Run 详情；右侧 Task/Subagent 与工作面板 | Loushang 候选界面的明确产品方向 | 现有 App Contract 已提供全部事实 |
| 官方参考 | ChatGPT desktop app、Projects and chats、Codex environments、Worktrees、Subagents、Integrated terminal、Code review | 参考系统公开的组织方式与能力入口 | Loushang 自动获得相同权限、协议或持久化 |
| 截图观察 | 菜单、左侧导航、Workspace 展开、Session 运行标志、中央步骤与执行详情、环境/来源/Subagent 面板 | 指定版本中可观察的布局和标签 | 隐藏状态机、后端对象模型或长期稳定性 |
| 本地事实 | `gui/` B1 reducer、Mock AppClient、fixture playback 和三栏功能骨架 | 当前实现可复用的状态与测试基线 | 目标视觉布局或真实 Task/Agent capability 已完成 |

外部参考变化只更新描述性参考清单。用户或 scope owner 接受的本地合同才可以
改变本规约；截图变化本身不直接改写 Target。

## 2. 界面领域词汇

| 术语 | 界面含义 | 事实与身份要求 |
| --- | --- | --- |
| Workspace | 左侧一级导航分组；关联一个可操作的工作上下文和服务可见 Session 集合 | 首期由显式配置、application/mux 和可选 workspace facet 投影；不是目录、仓库、Git worktree 或 GUI 自有数据库的同义词 |
| Session | 可持续交互、保留 transcript 与多次 Run 的独立上下文 | 使用完整 application/mux/member/Product Session identity；标题不是身份 |
| Run | 一次用户提交触发、直到完成、中断或失败的执行 | 优先使用 execution identity；不能从一组相邻消息猜测 |
| Task | Run 中具有稳定标题、状态和顺序或父子关系的工作项 | 只有服务或显式 fixture 提供 Task 投影时显示；`第 1/4 步` 表示 Task 进度 |
| Activity | Task 内可展开的具体动作或事实，例如读取文件、运行命令、工具调用和等待 | 关联 Run、Task、来源和状态；不是新的 Session 或 Task |
| AgentRun | 根 Agent 或 Subagent 对一个或多个 Task 的一次执行分配 | AgentRun 是执行者投影，Task 是工作项；二者不能合并 |
| Work Dock | 右侧可关闭、可调整宽度的通用面板容器 | 面板只消费被准入的能力；打开面板不授予权限 |

关系模型：

    Workspace
    └─ Session
       └─ Run
          ├─ Task
          │  ├─ Activity
          │  └─ assigned AgentRun
          └─ AgentRun
             └─ child AgentRun

一个 Session 同时最多突出显示一个当前 Run，但可以保留历史 Run。一个 Run 可以
有串行或并行 Task；因此 `2/5` 只表示服务公开的进度语义，不能被 GUI 强行解释
为百分比。没有 Task capability 时，GUI 仍显示 Run 状态，不伪造步骤总数。

## 3. 窗口信息架构

    DesktopWindow
    ├─ NativeFrame
    │  ├─ window navigation
    │  ├─ File / Edit / View / Help
    │  └─ operating-system window controls
    ├─ AppShell
    │  ├─ GlobalSidebar
    │  │  ├─ SidebarHeader
    │  │  ├─ NewSessionAction
    │  │  ├─ SidebarScrollArea
    │  │  │  ├─ pinned or standalone Sessions
    │  │  │  ├─ Workspace accordions
    │  │  │  └─ Recent Sessions
    │  │  └─ UserFooter
    │  ├─ SessionWorkspace
    │  │  ├─ SessionHeader
    │  │  ├─ SessionViewport
    │  │  │  ├─ transcript
    │  │  │  └─ Run activity timeline
    │  │  ├─ TaskProgressControl
    │  │  └─ Composer
    │  └─ WorkDock
    │     ├─ DockTabs
    │     └─ ActivePanel
    └─ OverlayLayer
       ├─ search and command palettes
       ├─ selectors and menus
       ├─ approvals and destructive confirmations
       └─ transient notifications

NativeFrame、GlobalSidebar、SessionHeader、Composer 和 WorkDock 的外层位置稳定；
内容能力可以缺失或降级。左侧滚动区、中央 SessionViewport 和右侧 ActivePanel
必须独立滚动，不能因为某一区域内容增长而把 Composer 或 UserFooter 推出窗口。

## 4. 原生菜单与窗口导航

Windows 基线顶层菜单为：

    [侧栏] [后退] [前进]   文件  编辑  视图  帮助

不得为了 Run/Task 新增必须存在的顶层“运行”菜单。运行控制在 SessionHeader、
TaskProgressControl、Composer 和 Work Dock 中表达。

| 菜单 | 首期可见命令 | 能力或状态规则 |
| --- | --- | --- |
| 文件 | 新对话、打开/添加 Workspace、关闭 Session、关闭窗口、退出 | 未连接时允许打开 fixture；真实 Workspace 操作受配置与服务能力约束 |
| 编辑 | 撤销、重做、剪切、复制、粘贴、全选、在当前 Session 查找 | 遵循当前焦点；密码和受保护字段不进入通用剪贴板命令 |
| 视图 | 左侧栏、Work Dock、任务、Subagents、审查、终端、浏览器、文件、来源、命令面板、缩放、重置布局 | 未提供的 capability 显示 disabled + 原因或不渲染；不得显示可用假象 |
| 帮助 | 文档、快捷键、日志、诊断、关于 | 日志和诊断默认脱敏 |

后退/前进遍历 GUI 导航历史，不撤销服务操作，也不 attach/detach Session。

## 5. GlobalSidebar

### 5.1 固定顶部

顶部从上到下包含：

1. `HarnessGUI ▼` 产品标题和当前连接/Host 入口；
2. 搜索按钮和通知按钮；
3. `新对话` 主操作及可选的快捷新增按钮。

点击“新对话”进入空白 Session composer；从 Workspace 行内新增时预选该
Workspace。没有第一次有效提交前，可以只保留本地 draft，不必建立空的持久
Session。实际创建语义仍由 AppClient/AppService 合同决定。

### 5.2 独立滚动区

顺序固定为：

1. 固定或独立 Session（存在时，无需强制显示“未归属”标题）；
2. 按用户排序的 Workspace accordion；
3. `最近` 跨 Workspace 快捷索引。

固定、最近和 Workspace 子项可以同时引用同一 Session。它们是导航投影，不是
复制 Session。没有全局发现/持久化合同时，“最近”只覆盖当前服务和本地会话
期间已知的 Session，并清楚标记范围。

### 5.3 Workspace 行

Workspace 收起时至少显示：

    [展开箭头] [Workspace图标] 名称     [VCS标志] [状态] [更多]

展开后显示固定、活动和最近的 Session；超过默认数量时出现“显示更多”。悬停
或键盘聚焦后可显示新增 Session 与更多菜单。

VCS 标志是可选事实：

| 标志 | 含义 |
| --- | --- |
| Git | Workspace 的权威 workspace facet 报告 Git repository |
| SVN | 未来被准入的 SVN provider 报告 SVN working copy |
| Mixed | 明确报告多个不同 VCS 根 |
| 无标志 | 无 VCS、未知或 capability 不可用；tooltip 区分三者 |

Codex 参考只证明 Git 相关能力。SVN 是 HarnessGUI 候选扩展，在服务合同接受前
只能作为标记 fixture 或 unavailable，不允许 GUI 直接扫描目录后自认权威。

### 5.4 Session 行

Session 行包含：

    [环境图标] Session 标题                [运行状态]
                 环境/branch/working-copy · 最近时间

窄栏可只显示第一行；完整身份在 tooltip、SessionHeader 或环境面板中可达。

状态标志：

| 可见状态 | 图形和文字 | 事实 owner |
| --- | --- | --- |
| active Run | 旋转圆环 + “运行中” | 服务 Run/execution 状态 |
| waiting approval | 橙色标志 + “待批准” | 当前有效交互 |
| waiting input | 蓝色标志 + “待输入” | 当前有效交互 |
| failed | 红色标志 + “失败” | 服务终态 |
| completed | 对勾 + “已完成” | 服务终态 |
| idle/unknown | 空心标志 + “空闲/未知” | 服务快照或明确缺失 |
| unread | 独立数字或圆点 | GUI 本地阅读状态 |

旋转动画不能是唯一状态表达；屏幕阅读器名称和静态文字必须同步。附图中
`Gui 开发` 旁的旋转圆环属于此 active Run 状态，而不是 Git 或 Subagent 标志。

### 5.5 最近与用户区

`最近` 位于 Workspace 列表下方并属于滚动区。每项显示 Session 标题和所属
Workspace；点击后选择同一 Session。UserFooter 固定在窗口底部，包含头像、
用户/组织、语音入口（能力可用时）和账户菜单。账户菜单可以进入设置、Host
连接、Provider/模型、权限、插件、诊断和退出；这些入口不改变各能力的 owner。

## 6. SessionWorkspace

### 6.1 SessionHeader

固定在中央区顶部，至少显示：

- Workspace 与 Session 标题；
- 当前 Local/Worktree/Cloud 或自定义环境；
- Git branch、SVN working copy 或 unknown；
- 当前 Run 状态；
- 分享（若支持）、更多菜单和 Work Dock 开关。

环境、分支和变更值必须来自公开投影。标题栏选择值不构成 attach、handoff、
branch switch 或其他服务操作。

### 6.2 Transcript 与 Run Activity Timeline

SessionViewport 按时间显示用户输入、Assistant 输出、审批、结果、错误和可折叠
的 Run activity groups。活动摘要示例：

    Planning detailed GUI interface specification        [展开]
      已读取 gui-requirements.md
      已运行 rg ...
      已运行文档检查

行为规则：

- 每个 activity group 明确关联 Run，能够关联时再显示 Task；
- 收起状态保留摘要、状态、耗时和失败数；
- 展开状态按服务顺序显示读取、命令、工具、等待、结果和错误；
- 点击活动只改变本地展开状态，不重放命令；
- 命令参数、路径和输出遵守脱敏与容量限制；
- 活动正在运行时使用动画和文字；完成后使用稳定终态；
- 新活动不能强制抢走正在阅读历史内容的滚动位置；
- 断线或事件 gap 后标记 stale/resync-required，不把旧活动继续显示为实时。

中央详细执行区回答“当前 Run 具体做了什么”；右侧任务面板回答“整个 Task
结构、状态和分配是什么”。两处引用相同 ID，不建立两份事实。

### 6.3 TaskProgressControl

TaskProgressControl 位于 Composer 上方，示例：

    ○ 第 1 / 4 步

它表示当前 Run 的 Task 进度。点击或键盘激活后弹出轻量 Task 列表：

    ◌ 检查 GUI 工作树和现有文档
    ○ 编写 HarnessGUI 界面规约
    ○ 补充架构方法
    ○ 运行文档检查

规则：

- 当前 Task 有旋转状态和文字；
- 已完成、当前、等待、失败和取消必须可区分；
- 并行 Task 不伪装为单一严格序号；改显示 `2 active · 3/6 completed`；
- 总数未知时显示当前 Task 标题，不显示虚构分母；
- 点击 Task 可滚动到其中央 activity group，或打开右侧 Task 面板；
- 面板关闭不影响 Run；
- Task capability 缺失时隐藏步骤控件，只显示 Run 状态。

### 6.4 Composer

Composer 固定在中央区底部，包含附件托盘、多行输入、权限模式、模型/强度、
语音（可用时）和发送/中断按钮。

| Run 状态 | 主按钮 | 发送语义 |
| --- | --- | --- |
| idle/completed/failed | 发送 | 创建新的提交/Run |
| running | 中断；输入仍可编辑 | 按合同提交 steering 或排队输入；无合同时禁用并解释 |
| waiting approval/input | 对应答复操作 | 回答当前有效交互，不作为普通新 Run |
| disconnected/resync-required | 禁用可变操作 | 保留草稿并提示重连/同步 |

IME 组合期间 Enter 不发送；草稿按完整 Session identity 隔离。打开文档、任务或
右侧面板后仍可返回 Composer，且不会丢失草稿或改变发送目标。

### 6.5 ChangeSet card 与 Diff Quick Look

Transcript 中的具名 ChangeSet 先以摘要卡片呈现文件数、增删行、scope、revision
和有界文件清单。点击文件打开中央 Quick Look；Quick Look 是只读、非模态的
临时 Diff 浮层，关闭后焦点返回原文件行，且不改变 transcript、Composer 草稿或
发送目标。用户可从 Quick Look 显式升级到右侧完整 Review 面板：

    ChangeSet summary -> file Quick Look -> Work Dock Review

Quick Look 与 Review 引用同一个 document/change identity 和 revision，不复制事实。
Quick Look 不提供暂存、还原、提交或推送；完整 Review 在首期同样只读，未来只有
服务 capability 同时声明权限、revision 前提和失败语义后才能出现可变操作。
ChangeSet 没有 accepted provider 时，卡片和 Quick Look 不得从文件系统或
Assistant 文本补造。

## 7. Work Dock

Work Dock 是右侧可关闭、可调整宽度的 tab 容器。首期至少支持环境、任务、
Subagents、变更/审查、文件/文档；终端、浏览器、来源和侧边对话按 capability
逐步启用。

| 面板 | 展示内容 | 禁止推断 |
| --- | --- | --- |
| 环境 | application、Workspace、mux/member/Session、Local/Worktree/Cloud、VCS、branch、连接和控制 generation | 显示环境不等于获得切换或控制权 |
| 任务 | 当前 Run、Task 树、当前 Task、完成/活动/等待/失败、Task 详情 | 无 Task 合同时不从 Assistant 文本解析计划 |
| Subagents | AgentRun 树、角色、被分配 Task、状态、耗时、最近活动和返回摘要 | AgentRun 不等于 Task；颜色头像不作为稳定 identity |
| 变更/审查 | ChangeSet scope、revision、文件和 Diff；后续才包含暂存/还原/提交/推送 | 全仓变更不归因于当前 Run |
| 终端 | 绑定当前 Session 环境的 terminal tabs 和输出 | pane 关闭不杀服务；无 shell 合同时不提供任意命令入口 |
| 浏览器 | 独立浏览器 capability 返回的页面和证据 | HarnessGUI WebView 不是通用浏览器执行器 |
| 文件/文档 | Workspace 文件树、最近文件、只读内容和结果引用 | 路径字符串不等于读取授权 |
| 来源 | 当前 Session 引用的文件、图片、网页和外部资源 | 来源不自动进入未来 Run |
| 侧边对话 | 可选辅助 Session 或受控子上下文 | 不静默污染主 Session transcript |

Task 面板与 Subagents 面板必须互相可导航：从 Task 定位 assigned AgentRun，从
AgentRun 定位其 Task。根 Agent 与派生 Subagent 使用同一状态词汇，但保留
parent-agent 与 parent-task 两种不同关系。

## 8. 尺寸、滚动与响应式

桌面默认建议值是实现 token，不是参考系统像素承诺：

| 区域 | 默认 | 约束 |
| --- | --- | --- |
| NativeFrame | 32 px 左右 | 服从平台窗口装饰与字体缩放 |
| GlobalSidebar | 280 px | 240–360 px，可收起和调整 |
| SessionWorkspace | 自适应 | 建议不小于 640 px |
| WorkDock | 400 px | 320–640 px，可关闭和调整 |
| Composer | 内容自适应 | 核心输入与发送/中断始终可达 |

窗口变窄时依次：

1. Work Dock 变为覆盖式抽屉或关闭；
2. GlobalSidebar 变为可呼出的抽屉；
3. SessionHeader 折叠次要身份；
4. Composer 次要操作进入更多菜单；
5. 当前 Task、输入和发送/中断始终可见。

不得通过水平滚动才能到达主要输入或中断操作。窗口恢复宽度后保留用户的面板
选择和安全范围内的宽度偏好。

## 9. 焦点、键盘与可访问性

- 三个主区域各有可识别 landmark 和名称；
- Workspace accordion、Session、Task、Dock tab 和菜单全部可用键盘操作；
- 焦点顺序与视觉顺序一致，关闭 overlay 后返回触发控件；
- 状态不只依赖颜色、旋转或图标；
- 动画遵循 reduced-motion；旋转状态可以改为静态图标加文字；
- 200% 字体缩放时核心操作仍可达，文本不被固定高度裁切；
- transcript 的流式更新不逐 token 打断屏幕阅读器；
- 错误、审批、任务变化使用合适的 live region，但不反复播报旧事件；
- 中文、英文、多行、复制粘贴和输入法场景遵守 GUI-FR-003。

建议快捷键：

| 操作 | Windows/Linux | macOS |
| --- | --- | --- |
| 新对话 | Ctrl+N | Cmd+N |
| 搜索 Session | Ctrl+K | Cmd+K |
| 切换左侧栏 | Ctrl+Shift+S | Cmd+Shift+S |
| 终端 | Ctrl+反引号 | Cmd+反引号 |
| 文件 | Ctrl+P | Cmd+P |
| 中断 Run | Esc（仅 Composer/Run 上下文） | Esc |

平台保留键冲突时由快捷键设置覆盖；菜单应显示最终有效快捷键。

## 10. 来源、能力与降级

每个动态区域至少区分：

- loading：正在取得权威快照；
- available：值与 capability 可用；
- read-only：可查看但不可变；
- unavailable：服务明确不提供；
- unknown：没有足够事实；
- stale：连接已断开或 generation 已变化；
- incompatible：版本不兼容；
- fixture：明确的离线测试数据。

fixture 标签必须在窗口和相关面板中可见。真实模式不得用 fixture 填补缺失的
Workspace、Task、Subagent、VCS、ChangeSet 或权限事实。

## 11. 可执行验收场景

| ID | 场景与可观察结果 | 追溯需求 |
| --- | --- | --- |
| GUI-UI-AC-001 | 至少三个 Workspace 可展开/收起，Session 只出现在正确分组；Git、SVN fixture 与无 VCS 可区分 | GUI-FR-002, GUI-FR-015 |
| GUI-UI-AC-002 | 一个 Session 开始 Run 后左栏出现可访问的旋转状态；切换 Session 后该状态仍属于原 Session | GUI-FR-004, GUI-FR-014 |
| GUI-UI-AC-003 | 当前 Run 有四个 Task 时显示 `第 1/4 步`；推进 fixture 后当前 Task 与完成数同步变化 | GUI-FR-004, GUI-FR-020 |
| GUI-UI-AC-004 | 点击中央执行摘要展开读取文件、运行命令与工具活动，再次点击收起；不触发任何真实动作 | GUI-FR-004, GUI-FR-012 |
| GUI-UI-AC-005 | Task 与 AgentRun 互相定位；派生 Agent 完成后摘要回到根 Run，但 Task 和 Agent identity 不合并 | GUI-FR-020 |
| GUI-UI-AC-006 | Task capability 缺失、撤销或版本不兼容时，步骤与面板明确降级，Session 输入和中断仍按基础合同可用 | GUI-FR-009, GUI-FR-018 |
| GUI-UI-AC-007 | 点击 ChangeSet 文件打开中央 Quick Look，再显式升级到右侧完整 Review；两级视图引用同一 document/revision，Composer 草稿、发送目标与 transcript 阅读位置保持，所有仓库可变操作保持不可用 | GUI-FR-003, GUI-FR-007, GUI-FR-010, GUI-FR-017 |
| GUI-UI-AC-008 | 事件 gap 或 generation 改变后所有旧 Run/Task/Agent 状态标记 stale，并冻结可变操作直到 fresh snapshot | GUI-FR-009, GUI-FR-019 |
| GUI-UI-AC-009 | 窄窗口依次收起右侧与左侧，Task 状态、输入及中断仍可达 | GUI-FR-010 |
| GUI-UI-AC-010 | 键盘和 reduced-motion 模式可以完成 Workspace、Session、Task、Activity、Dock 和 Composer 主路径 | GUI-NFR-002 |

截图只能补充视觉证据，不能单独通过以上场景。回放必须断言状态、身份、动作
次数和降级结果。

## 12. Current、Target 与 Delta

`gui/` 当前 B1 已实现两个 fixture Session、草稿隔离、流式输出、只读文档、
Diff、三栏功能骨架、断线/事件 gap reducer 和原生 fixture bridge。以下仍是
本规约相对 Current 的主要差距：

- Workspace 分组、最近与固定导航；
- Codex 风格浅色 NativeFrame/GlobalSidebar/Composer；
- Run、Task、Activity 与 AgentRun 投影；
- 左栏 active Run 状态与中央 TaskProgressControl；
- 可折叠 Run Activity Timeline；
- 通用 Work Dock tabs、收起和调整尺寸；
- VCS provider 标志与 SVN 候选合同；
- 完整键盘、缩放、reduced-motion 和窄屏验收。

这些差距只在本规约被接受后进入 accepted Target ledger；在此之前属于 proposed
实现方向，不应报告为主线缺陷。

## 13. 非目标与待补合同

本规约不接受：

- Codex 品牌、商标、专有图标或逐像素复制；
- GUI 自有的跨项目 Session 数据库；
- 从 Assistant 文本解析 Task、Subagent 或权限；
- GUI 直接控制模型 provider、Harness、Git/SVN 或浏览器内部对象；
- 仅因为存在按钮就接受 terminal、Git mutation、handoff、分享或云执行；
- 用 CSS 组件边界替代 Workspace/Session/Run/Task 领域边界。

真实 Task/AgentRun、全局历史、固定/归档、SVN、可变 Git、terminal 和 browser
均需要独立 capability、identity、版本、权限、错误、容量和生命周期合同。
在这些合同完成前，B1 通过 fixture 验证布局和交互，真实模式显示 unavailable。
