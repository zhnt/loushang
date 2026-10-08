# 使用手册

[English](../../en/user-guide/) | 中文

使用手册说明当前 `loushang code` 相关的产品面。

## CLI 与 TUI

`loushang` 是主 CLI 入口。它支持一次性 prompt 运行、text/print/json/rpc 模式、会话控制、模型列表、命令列表、诊断、工具、扩展、技能、方法、包、导出和 work log。

需要交互式 coding session 时，可以使用 `loushang --tui` 启动终端 UI 产品面。已安装的 `loushang-tui` 命令是同一 TUI 模式的便捷入口。

TUI 模式当前有两个运行面。在 stdin/stdout 都是 TTY 时，`loushang --tui` 和
`loushang-tui` 会打开 screen 交互面。在 `--tui` 下使用管道或重定向 stdio 时，同一模式会使用
plain prompt loop，适合做快速 smoke test：

```bash
printf "hi\n/quit\n" | loushang --tui
```

plain 输出没有单独的 UI selector flag。继续使用 `--tui`，由终端交互性决定具体运行面。

常用起始命令：

```bash
loushang --help
loushang --list-models
loushang --list-commands
loushang --list-sessions
loushang --tui
loushang-tui
loushang -p "Summarize the current project."
```

如果要用 `loushang.tui` 构建终端 UI 应用，见 [构建 TUI 应用](tui.md)。

在对话界面点击 **Show Detail** 或 **Show Less** 可以展开或收起单条工具结果。
直接通过 SSH 连接时，默认也会请求鼠标事件，即使远端无法写入本机剪贴板；此时
复制选中文本会明确提示剪贴板不可用。确认终端支持 OSC 52 后，可以设置
`LOUSHANG_TUI_OSC52=1`；如需保留终端原生的鼠标划选，则设置
`LOUSHANG_TUI_MOUSE_POLICY=terminal`。在 tmux 中需开启 `mouse` 才能转发点击；
关闭时可用 F4 和 Enter 操作详情控件。
使用 macOS 自带 Terminal 时，还须在“显示”菜单中勾选“允许鼠标报告”；关闭该终端选项时，
应用即使启用鼠标模式也收不到点击。可用 `/terminal` 查看 `mouse_mode_active` 和
`mouse_event_observed` 排查。

Linux 后台命名 Mux 开发预览见 [lmux 使用说明](lmux.md)，包含目录、重连及升级限制。

### 显式 Hosted Application

`loushang-hosted` 是供应用启动器连接的前台 stdio 服务，不是新的交互式 prompt loop；
现有 CLI/TUI 入口不变。可先运行 `loushang-hosted --help`。

启动时显式提供 `--workspace`、`--application-root`、`--cwd-sessions` 和
`--home-sessions`。工作目录和应用状态目录的父目录须已存在，三个存储目录必须相互
独立。应用状态目录须为私有目录（POSIX 下 0700），缺失的叶目录会按私有权限创建。
增加 `--describe` 可只读查看连接所需的范围标识，不启动或写入状态；移除此标志后，
使用管道连接带帧协议，而不是逐行文本，启动器应使用 `StdioAppClientV1`。

保持相同的 application ID（默认 `coding.default`）、工作目录和存储根，可在关闭后
恢复 mux、成员和会话。EOF 会终止这个前台应用；正在运行的回合、审批和旧连接权限
不会恢复。它不提供后台常驻、网络监听或自动重连。
客户端组合方式、三平台验收证据和集成状态见
[G14 契约与交付状态](../../internals/architecture/appserver/foreground-stdio-hosted-app-g14.md)。

## 会话

会话保存 coding 对话与执行记录，适合需要恢复、分叉、导出、诊断和后续检查的工作流。

常见操作：

```bash
loushang --list-sessions
loushang --resume
loushang --continue
loushang --resume <session-id-or-path>
loushang --export
```

交互式 `loushang --resume` 和无参数 `/resume` 会打开全屏、可搜索的 continuity 选择器。默认按键中，空格按需加载预览；安装多个 Provider 时 Ctrl+P 切换 Provider、Tab 切换 Domain；Ctrl+S 切换公共排序。`--continue` 恢复当前项目最新会话，`--resume <session-id-or-path>` 和 `/resume <session-id-or-path>` 直接恢复指定会话。非交互模式必须使用这些显式形式之一。

在交互界面中，内置 slash commands 包括 `/session`、`/resume`、`/fork`、`/clone`、`/branch`、`/tree`、`/tools`、`/extensions`、`/export`、`/compact`、`/reload` 和 `/quit`。`/fork` 把当前 chat 复制为一个新会话，`/clone` 是兼容别名，`/branch` 则打开 prompt 选择器，从较早的用户消息创建分支。

## 工具

工具把可执行能力暴露给 agent。Coding 产品包含内置工具面，并支持启用、禁用和收窄工具范围：

新的交互会话默认启用内置 `read`、`ls`、`find`、`grep`、`bash`、`edit` 和 `write` 工具。文件探索优先使用 `ls`、`find`、`grep` 和 `read`；`bash` 更适合 shell 管道、重定向、构建命令、测试和 Git 操作。

```bash
/tools
/tools off bash
/tools only read,ls,find,grep
/tools reset
loushang --tools bash,write -p "Inspect this project."
loushang --no-tools -p "Explain the repository from context only."
```

### 架构分析工具

`coding.arch` 提供有界的 `inspect_import_graph` 工具，默认模式为
`on_demand`。可在 Coding Session 中显式激活：

```bash
loushang --capability coding.arch=always \
  -p "请使用 inspect_import_graph 总结这个仓库的依赖关系。"
```

如果不需要模型或 Session，可直接运行确定性的模块 CLI：

```bash
uv run python -m loushang.coding.arch src/loushang \
  --package-prefix loushang --query summary --pretty
```

两个入口都会把分析根限制在选定 workspace 内；`--no-tools` 与
`coding.arch=disabled` 会完全跳过 Arch Plugin。

### LSP 语义工具

`coding.lsp` 是可选的高频 Coding 能力，提供 `inspect_symbol` 和
`document_outline`。默认是 `on_demand`；要让它们进入当前 agent 的默认工具集：

```bash
loushang --capability coding.lsp=always
loushang lsp status
loushang lsp doctor
```

Server 仍只会在第一次语义查询时惰性启动。独立 CLI 的 `status` 和 `doctor` 标记为
`scope=catalog`：它们只检查配置与可执行文件，不构造 Session，也不会启动或安装任何
Server。Loushang 会探测已安装的 Pyright、TypeScript Language Server、rust-analyzer、
gopls 和 clangd。

TypeScript 预设覆盖 `.ts`、`.tsx`、`.js`、`.jsx` 及其标准模块变体，并选择最近的
`tsconfig.json`、`jsconfig.json`、`package.json` 或 `.git` 作为根。用户需要自行安装
`typescript-language-server` 和兼容的 `typescript` 包；缺少可用 Server 时，普通 Coding
工具仍可继续工作，Loushang 不会自动安装任何包。

其他默认预设同样选择最近的语言原生项目根：Pyright 使用 `pyrightconfig.json` 或
`pyproject.toml`，rust-analyzer 使用 `rust-project.json` 或 `Cargo.toml`，gopls 使用
`go.work` 或 `go.mod`，clangd 使用 `.clangd`、`compile_commands.json` 或
`compile_flags.txt`；它们也都会回退到最近的 `.git` 根。

在交互式 Coding Session 内，使用独立的 Session 运行态表面：

```text
/lsp status
/lsp stop <server-id> <root>
```

`/lsp status` 只报告当前 Session 已知的 Server，包括生命周期、打开文档数、请求、超时、
替换次数和已丢弃诊断发布数；查询本身不会启动 Server。`/lsp stop` 优雅关闭精确匹配的
Session Server，下一次语义查询可以按需启动替代实例。嵌入方可使用
`session.get_lsp_status()` 和 `await session.stop_lsp_server(...)` 取得同一份有界状态。
TUI 会直接执行同一个 Session 命令；RPC 客户端可以先用 `get_commands` 发现命令，再在不经过
模型回合的情况下执行：

```json
{"id":"lsp-status","type":"execute_command","command":"lsp","args":"status"}
```

响应会把命令的结构化结果放在 `data.result`。

已经把 `pyright-langserver` 放入 `PATH` 的贡献者可以运行可选真实 Server 门：
`uv run pytest tests/integration/coding/test_pyright_lsp_live.py -q`。未安装 Pyright 时测试会
跳过，测试自身不会安装它。

TypeScript 的对应兼容性门是
`uv run pytest tests/integration/coding/test_typescript_lsp_live.py -q`，默认从 `PATH`
查找 `typescript-language-server`，也可通过 `LOUSHANG_TEST_TYPESCRIPT_LANGSERVER`
指定可执行文件；测试同样不会安装 Server。

gopls 的兼容性门是 `uv run pytest
tests/integration/coding/test_gopls_lsp_live.py -q`，默认从 `PATH` 查找 `gopls`，
也可通过 `LOUSHANG_TEST_GOPLS` 指定；安装仍是独立的开发者或 CI 步骤。

rust-analyzer 的兼容性门是 `uv run pytest
tests/integration/coding/test_rust_analyzer_lsp_live.py -q`，默认从 `PATH` 查找
`rust-analyzer`，也可通过 `LOUSHANG_TEST_RUST_ANALYZER` 指定；贡献者应通过 rustup
安装相互匹配的稳定 toolchain、`rust-analyzer` 与 `rust-src`。

自定义 Server 写入 `~/.loushang/coding/lsp.json`：

```json
{
  "servers": [
    {
      "id": "python-custom",
      "command": ["my-language-server", "--stdio"],
      "language_extensions": {"python": [".py", ".pyi"]}
    }
  ]
}
```

项目的 `.loushang/lsp.json` 可以调整产品默认或用户已声明的 Server，但在通用 workspace
trust 机制完成前，不能从仓库配置引入新的可执行文件或环境变量。

## 扩展

扩展是可以注册生命周期 hooks、工具、动态资源、命令和 flags 的 Python 文件。可以先阅读 [examples/coding/extensions](../../../examples/coding/extensions/) 中的可运行扩展示例。

简单的工作区扩展可直接放在 `.loushang/extensions/<name>.py`，实现 `register(api)`；也可用包含 `extension.py` 或 `__init__.py` 的目录。无需构建 Wheel。这是 Coding 进程内运行的可信 Python，没有独立的 Wheel 安装、版本和退役生命周期。旧的 `--extension`/`-e` 参数已移除。

用 `loushang-coding-extension init .loushang/extensions/hello.py` 创建单文件模板，再运行返回的 `smokeCommand`。它在一次性 Product 工作区启动离线 Coding Session 并调用模板工具；扩展 Python 代码仍以当前用户权限在进程内执行，一次性工作区不是代码沙箱。工具需用 `direct_tool(...)` 或带 Action 适配器的 `authorized_tool(...)` 包装后注册。

扩展可以携带相邻的 `loushang-extension.toml` manifest，用来声明身份、权限等级、依赖和预期贡献。使用 `/extensions` 查看已加载扩展、贡献摘要和诊断；使用 `/extensions <id>` 查看单个扩展详情。`/tools` 会在可用时展示 extension tool 的来源信息。

## 包与插件

包与插件可以提供可复用的 coding 资产。常见生命周期命令：

文档型 Skill/Prompt Wheel 可用 `loushang-plugin init-coding-skill ./reviewpack --resource-name review`（Prompt 用 `init-coding-prompt`）创建源码；返回的 `buildCommand` 构建 Wheel，`smokeCommand` 在一次性离线 POSIX Product 工作区执行安装、选择和模型输入消费验证。结果分别报告三个阶段，不会安装到当前工作区。各类型和入口的开放状态见 [插件支持矩阵](../../internals/architecture/harness/plugin/plugin-support-matrix.md)。

Screen Theme 候选可用 `loushang-plugin init-coding-theme ./themepack --resource-name dusk` 创建源码，再运行返回的构建和 smoke 命令。Theme smoke 在一次性 POSIX Product 工作区验证显式选择后的 Screen 样式；Hosted Mux 和全面上线仍需分别评估。

带 fence 的工作区可用 `loushang-coding-plugin-status --workspace PATH` 或 `/plugins status` 查看与本地 SDK `support_status()` 相同的只读阶段。`projected` 只表示当前组合预览，`productUse: not_checked` 表示尚未通过真实 Session 或 Screen 验证使用。

```bash
loushang --list-plugins
loushang --list-packages
loushang --install-package <source>
loushang --check-package-updates
loushang --update-packages
```

Linux 上没有旧 Plugin 状态、旧 Plugin/Package 设置的新工作区，可离线切换到带 fence 的 Product Store：

```bash
loushang-package-cutover --workspace /工作区/绝对路径
```

先停止该工作区的 Loushang 进程；命令也会拒绝仍在运行的旧 writer。已有的 Loushang 私有主目录必须归当前用户所有、不可供其他用户访问；命令不会改写它的权限。它通过 Product 事务安装内置的 base、LSP、架构三个插件，中断后可以重试。需要旧状态采纳或设置迁移的工作区会被拒绝。写入 fence 后只能使用理解该 fence 的 Loushang 版本。

包含旧 Plugin 状态、设置、Source 或 Package Store 成员的 pre-B 工作区不在当前 Product 路径的支持范围内。普通切换命令会在创建 B fence 或改写旧工作区前拒绝它们。请为 Product 插件路径创建新工作区；已有 B fence 的工作区可用理解该 fence 的版本重开。历史遗留的旧版审核与采纳命令仍保留在 CLI 中，但不构成当前候选版本支持的迁移路线。

在 POSIX 工作区中，如果 Package 操作在 staging 阶段中断，可用准确的操作 ID 查看检查点并请求限定范围的 Product 恢复：

```sh
loushang-package-repair --workspace /工作区/绝对路径 inspect-staging <操作ID>
loushang-package-repair --workspace /工作区/绝对路径 repair-staging <操作ID>
```

两个动作都会激活 Product 恢复并打开 runtime lease。`inspect-staging` 不会为指定操作选择修复。`repair-staging` 在同一个 lease 内完成选择与执行，只有操作提交成功才返回零退出码；Source 已改变、旧 lease 仍在运行或 staging 证据不匹配时会拒绝。

如果 `transaction_pinned` 操作尚无 staging 效果，应改用 `repair-pinned <操作ID>`。Product 在同一个新 lease 中先复核保留 pin 和 Source，再选择并执行。已经产生 staging receipt 的操作应使用 `repair-staging`。

对于仍处于 `retryable_failure` 的 A2 操作，可使用独立的 `repair-retryable` 动作。Product 会先检查跨 runtime 的 Source、清理状态和 lease，再选择并执行一次重试；只有提交成功才返回零退出码：

```sh
loushang-package-repair --workspace /工作区/绝对路径 repair-retryable <操作ID>
```

对于中断后仍为 active 的尝试，按 Package 阶段选择对应动作。各动作由 Product 校验旧 lease 和 Source、结算精确的中断尝试，再在同一个新 runtime lease 中选择并执行一次重试：

```sh
loushang-package-repair --workspace /工作区/绝对路径 repair-unstarted <操作ID>  # classified 或 acquiring
loushang-package-repair --workspace /工作区/绝对路径 repair-acquired <操作ID>   # acquired、inspecting 或 extracted
loushang-package-repair --workspace /工作区/绝对路径 repair-resolving <操作ID>  # resolving_closure
loushang-package-repair --workspace /工作区/绝对路径 repair-verified <操作ID>   # closure_verified
```

阶段不匹配、Source 已改变或旧 lease 仍在运行时会拒绝，只有 Product 提交成功才返回零退出码。如果运行在旧尝试变为 `retryable_failure` 后中断，可对同一操作执行 `repair-retryable`。已 pin 和已 staging 的状态使用上文独立动作；更晚的事务状态仍需要 Product 恢复路径。这不是通用 Package 修复命令。

如果更新已提交，但 Package handoff 在终态收据写入前中断，可精确恢复该操作，不触发通用 Package 恢复：

```sh
loushang-package-repair --workspace /工作区/绝对路径 repair-handoff <操作ID>
```

Product 要求指定操作具有终态 handoff。未知操作 ID 不会顺带恢复其他待处理操作；此动作也不修复更早的 A2 事务阶段。

本地 Python 操作者可从 `loushang.coding.package_product_repair` 调用 `open_coding_package_repair_client(workspace)`，再执行 `client.perform(action, operation_id)`。类型化结果提供 `committed` 和不含路径的 `to_dict()`；`inspect-staging` 返回 checkpoint 证据，不提供已提交的 disposition。这是 Coding 管理 API，与 Plugin 作者 SDK 分离。

在 Coding Screen 或普通 TUI 中，`/plugins repair-package repair-retryable <操作ID>` 会显式调用同一个 Product 修复动作，不发送模型提示。仅在 Package 阶段匹配时，才将 `repair-retryable` 换成上文其他动作。当前 Session 保留已选择的资源；修复提交后需启动新 Session。此命令与修复待处理 Desired State 命令的 `/plugins repair <操作ID>` 相互独立。

Linux 上，已切换工作区的不可变 Plugin 根可通过单独的离线 GC 命令清理。先停止所有 Loushang Session。`prepare` 会恢复 Product 事务并持久封存 GC 写入者，这是单向维护步骤；`list` 返回不含文件路径的精确候选和 reservation ID。复制候选 ID 后只删除该根：

```bash
loushang-package-gc --workspace /工作区/绝对路径 prepare
loushang-package-gc --workspace /工作区/绝对路径 list
loushang-package-gc --workspace /工作区/绝对路径 delete --candidate-id <候选ID> --attempt-key <本次尝试标识>
```

保留尝试标识可安全重放同一请求。如果已开始删除但未结算，用结果或 `list` 中的 reservation ID 和新的尝试标识重试：

```bash
loushang-package-gc --workspace /工作区/绝对路径 retry --reservation-id <reservation-ID> --attempt-key <新尝试标识>
```

该命令仅删除精确匹配的不可变 Plugin 根，不会删除 Plugin 私有数据，也不会推断备份已过期。

Linux 上，独立的 `loushang-plugin-private-data` 命令管理 `coding.arch.default` 的 Installation 缓存。先停止所有 Coding Session。`backup` 将该缓存复制并校验到独立的 Installation 备份目录；只有备份内容仍可校验时，`backup-status` 才报告 `retained`：

```bash
loushang-plugin-private-data --workspace /工作区/绝对路径 --plugin-id coding.arch.default backup > arch-backup-receipt.json
loushang-plugin-private-data --workspace /工作区/绝对路径 --plugin-id coding.arch.default backup-status
loushang-plugin-private-data --workspace /工作区/绝对路径 --plugin-id coding.arch.default backup-verify --backup-id 从收据中取得的精确backupId
```

当该 Plugin 的 Desired State 已为 `absent` 后，保存删除预览，再把预览中的精确 `fingerprint` 值输入独立确认命令：

```bash
loushang-plugin-private-data --workspace /工作区/绝对路径 --plugin-id coding.arch.default preview > arch-plan.json
loushang-plugin-private-data --workspace /工作区/绝对路径 --plugin-id coding.arch.default confirm --plan-file arch-plan.json --accept-fingerprint EXACT_FINGERPRINT_FROM_PLAN > arch-confirmation.json
loushang-plugin-private-data --workspace /工作区/绝对路径 --plugin-id coding.arch.default delete --plan-file arch-plan.json --confirmation-file arch-confirmation.json
```

删除时会重新核对数据目标、独立确认、Desired State 已移除及没有活动 Product Session。重复相同命令会返回持久收据。备份保留状态独立投影；源数据删除后仍可报告 `retained`。`backup-verify` 按收据中的精确 `backupId` 重新校验归档，即使源数据已删除也可使用；备份被篡改时会拒绝。

Installation 已移除且数据删除有完成收据后，可以先预览精确备份恢复，再接受预览指纹，将数据恢复到空目录。命令拒绝被修改的现有数据；恢复中断后可重放同一计划：

```bash
loushang-plugin-private-data --workspace /工作区/绝对路径 --plugin-id coding.arch.default restore-preview --backup-id 从收据中取得的精确backupId > arch-restore-plan.json
loushang-plugin-private-data --workspace /工作区/绝对路径 --plugin-id coding.arch.default restore --plan-file arch-restore-plan.json --accept-fingerprint 从恢复计划中取得的精确fingerprint
loushang-plugin-private-data --workspace /工作区/绝对路径 --plugin-id coding.arch.default restore-confirm --backup-id 从收据中取得的精确backupId > arch-restore-confirmation.json
loushang-plugin-private-data --workspace /工作区/绝对路径 --plugin-id coding.arch.default restore-confirm-verify --backup-id 从收据中取得的精确backupId --confirmation-id 精确confirmationId
```

恢复完成后运行 `restore-confirm`。它重新校验归档、已完成的删除与恢复记录及恢复后的数据，再写入独立的持久确认。恢复树变动后，确认验证会拒绝。这份 Arch Installation 确认不能充当迁移恢复演练收据。

完成确认后，先预览精确归档和恢复数据证据，保存计划并独立接受其指纹，再只对该备份执行到期：

```bash
loushang-plugin-private-data --workspace /工作区/绝对路径 --plugin-id coding.arch.default backup-expiry-preview --backup-id 从收据中取得的精确backupId --confirmation-id 精确confirmationId > arch-backup-expiry-plan.json
loushang-plugin-private-data --workspace /工作区/绝对路径 --plugin-id coding.arch.default backup-expiry-confirm --plan-file arch-backup-expiry-plan.json --accept-fingerprint 从到期计划中取得的精确fingerprint > arch-backup-expiry-confirmation.json
loushang-plugin-private-data --workspace /工作区/绝对路径 --plugin-id coding.arch.default backup-expire --plan-file arch-backup-expiry-plan.json --confirmation-file arch-backup-expiry-confirmation.json
loushang-plugin-private-data --workspace /工作区/绝对路径 --plugin-id coding.arch.default backup-status
```

`backup-expire` 会永久删除已验证的归档。执行时要求 Installation 仍为已移除、已确认的恢复数据未改变，且没有活动 Product Session。若中断，状态为 `expiry_pending`；重放同一命令可继续完成。完成后，`backup-status` 报告 `expired` 和独立收据 ID；恢复后的 Installation 数据仍保留。其他 Plugin 数据类型和 Windows 尚未准入。

对已经准入带依赖 Wheel 的 Product，`list` 还会显示 `dependencyRetention`。只有所有持有该依赖的根均有已验证的删除结果，`exact_target` 条目才会给出依赖 ref 与 settlement ID。按这些精确 ID 删除孤儿依赖；如果删除已开始但结果未落盘，用持久化 start ID 重试：

```bash
loushang-package-gc --workspace /工作区/绝对路径 delete-dependency --dependency-ref-id <依赖-ref-ID> --settlement-id <settlement-ID> --attempt-key <本次尝试标识>
loushang-package-gc --workspace /工作区/绝对路径 retry-dependency --start-id <start-ID> --attempt-key <新尝试标识>
```

Coding 当前的本地数据 Wheel 策略尚不准入带依赖的 Wheel；这些命令不会扩大该准入范围。

## 方法与技能

方法与技能把可复用工作实践变成运行时资产。CLI 中可以使用：

```bash
loushang --list-methods
loushang --show-method <method>
loushang --show-method-plan <method>
loushang --method <method> -p "Run this coding task."
loushang --no-method -p "Run without the configured default method."
loushang --list-skills
```

`--method` 支持非交互的 prompt/print/json 路径。在 method step UI 与 work-event projection 路径就绪前，TUI 和 RPC mode 会继续拒绝 `--method`。

## Work Logs

Work log 会为一次性 prompt/print/json 运行记录 `WorkOperation` 与 `WorkEvent`：

```bash
loushang --work-log .loushang/work/events.jsonl -p "Run this coding task."
loushang --work-log-inspect .loushang/work/events.jsonl
loushang --work-log-inspect .loushang/work/events.jsonl --work-log-inspect-format plans
```

`--work-log` 不支持 TUI 或 RPC mode。

## 诊断与导出

诊断和导出用于检查 session 中发生了什么：

```bash
loushang --list-diagnostics
loushang --diag-export --diag-output diagnostics.json
loushang --export session.html
```
