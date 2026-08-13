# Windows 开箱即用的 Shell 执行设计评审

## 状态

- 状态：待评审提案，尚未成为接受的架构决定
- 日期：2026-08-12
- 范围：`loushang.harness.workspace`、命令工具、Session 手工命令、策略审批与 Coding 产品接线
- 本文只记录问题、目标设计和交付门槛，不代表相关实现已经完成

2026-08-12 的第二轮独立评审已被选择性吸收。新增重点包括 PowerShell 别名与混淆输入、长脚本 transport、现存跨平台 reader 挂起、P1 Bash 策略零回归门槛、P2 目标能力门控和最小只读命令分类。评审中“排除全部用户可写 PATH”和“直接按控制端 `os.name` 注册工具”的建议没有原样采用：前者会误伤 Scoop 等正常用户级安装，后者不符合未来远端执行目标感知的边界。

## 实施进度

- 追踪 Issue：[#444](https://github.com/zhnt/loushang/issues/444)
- P0：已完成。跨平台分块输出、增量 UTF-8 解码、有限 idle drain、外层 task cancellation 进程树清理、Windows `CREATE_NO_WINDOW`/`taskkill` 原语、结构化 launch error 和 Windows 环境变量合并均已落地，并通过完整 harness 回归。
- P1：已完成隐藏实现。新增执行目标感知的 `ShellSpec` 解析/编译、PowerShell UTF-16LE `-EncodedCommand` transport、命令行长度 fail-closed、明文 policy subject、保守的 PowerShell 5.1/7 分类，以及跨 `bash`/`shell` 工具名稳定生效的 `workspace.command` capability 匹配。此阶段没有注册或暴露新模型工具；既有 POSIX Bash 决策与完整 harness 回归通过。
- P2：已完成代码接线。Windows 执行目标会以同一原子切片把默认 `bash` 工具替换为 `shell`，注册并默认激活 PowerShell 方言提示，接通 Settings 中的 shell path/prefix、用户 `!`/`execute_bash` 兼容入口、`user_bash` hook、transcript、审计与 `workspace.command` 权限能力；POSIX 默认工具表保持不变。旧 `blocked_tools/ask_tools` 中的 `bash` 会迁移匹配稳定 capability，新的 `blocked_capabilities/ask_capabilities` 也可持久化配置。
- P2 验证：非 Windows CI 已通过完整 harness 门禁（Ruff、mypy、1791 项测试）及 637 项 Coding 产品回归，并包含模拟 Windows 目标的 registry -> AgentSession -> PowerShell transport 端到端测试。仓库已新增 `windows-shell-compatibility.yml`，在 `windows-latest` 上实际解析系统 PowerShell 并验证 UTF-8、非零退出码、工具注册、策略和 Session 兼容链路；该 workflow 需要随分支发布后取得绿灯，且仍建议用 Windows 10 + PS 5.1 实体环境补充验收。在原生结果返回前不宣称平台验证完成。
- P2.1：已完成首轮审批降噪。PowerShell policy 现在仅对“单条、字面量、无展开/管道/重定向/调用运算符”的 Git 命令做保守解析，普通 `status/diff/log/show/rev-parse/add/commit/switch/merge/fetch/pull` 等复用既有 Git effect detector 并在无风险 effect 时直接放行；`push`、`reset --hard`、`clean -f` 继续产生原有审批风险码，未知 alias、大小写伪装、动态参数、外部 diff 和未分类 mutation 继续 fail-closed。Git 发布的 session/project 授权已从旧 `bash` 工具名迁移到 `workspace.command` capability，因此 Windows `shell` 可以复用按 repository/remote/非 force 约束的窄授权。同期修复了受限 Linux host 中短命 `fd/rg` 进程退出回调已排队但 selector 未唤醒造成的挂起，并保持取消与提前停止的亚秒级收尾。
- P2.1 验证：完整 Harness 门禁通过 Ruff、mypy 与 1836 项测试（另 3 项按环境跳过）；Coding 的策略、工具策略集成、AgentSession 工具、工具注册和权限行为共 207 项回归通过。另已加入原生 Windows `git --version` 免审批测试，该项在非 Windows 主机跳过，等待 Windows CI/实体环境继续验收。
- P3：尚未实施，包括更完整的 PowerShell AST/effect 分类、Windows Job Object、企业 Windows sandbox 和可选 Cmd 深度支持。

## 目标

让 loushang 在干净的 Windows 10/11 环境中无需安装 Git Bash、WSL 或额外配置即可执行模型命令和用户手工命令，同时保证：

- 工具名称与实际 shell 方言一致，不让名为 `bash` 的工具隐式执行 PowerShell；
- PowerShell 命令经过与 Bash 同等级别的策略、审批、审计和生命周期管理；
- 超时、取消和 Session 关闭能够终止完整进程树；
- Windows PowerShell 5.1 的编码、退出码和语法差异得到明确处理；
- Git Bash 继续作为显式兼容能力，而不是 Windows 开箱即用的前置依赖。

## 用户报告与直接根因

Windows 用户从工具调用任意 Bash 命令时立即得到：

```text
[WinError 2] 系统找不到指定的文件。
```

即使命令文本是 `cmd.exe /c echo test`、`powershell.exe -Command ...` 或系统程序绝对路径，结果仍然相同。这是因为命令文本执行之前，外层 Bash 进程已经启动失败。

当前实现有两条彼此独立、但都假定 POSIX Bash 存在的路径：

- 模型 Bash 工具最终构造 `bash -lc <command>`：[`harness/tools/workspace/bash.py`](../../../src/loushang/harness/tools/workspace/bash.py)
- 用户 `!` 命令默认构造 `/bin/bash -lc <command>`：[`harness/session/bash.py`](../../../src/loushang/harness/session/bash.py)

底层 [`_local_process.py`](../../../src/loushang/harness/workspace/_local_process.py) 直接把 argv 交给 `asyncio.create_subprocess_exec()`。因此 Windows 上找不到外层 shell 时，内部命令是否合法完全不影响结果。

`WinError 2` 也可能由不存在的 cwd 引起，最终诊断不能继续只暴露原始系统错误，必须至少区分：

- `cwd_not_found`
- `cwd_not_directory`
- `shell_not_found`
- `spawn_failed`
- `timed_out`
- `cancelled`

## 当前存在但没有真正接通的配置

配置层已经持久化：

- `shell_path`
- `shell_command_prefix`

对应定义位于 [`config/agent/types.py`](../../../src/loushang/harness/config/agent/types.py)，下层 [`tools/workspace/factory.py`](../../../src/loushang/harness/tools/workspace/factory.py) 也能接收这些值。

但是 Coding 工具注册路径 [`coding/tool_pack.py`](../../../src/loushang/coding/tool_pack.py) 没有把设置传入工具选项，用户 `!` 命令又完全绕过这套选项。当前测试主要证明配置能够保存和重新加载，没有证明它会改变最终 spawn argv。

此外，即使直接把 `powershell.exe` 填进现有 `shell_path`，固定的 `-lc` 调用协议仍然错误。因此本问题不能通过单独接线 `shell_path` 修复。

## Windows 10 的 PowerShell 基线

Windows 10 的开箱即用基线是 **Windows PowerShell 5.1**：

```text
可执行文件：powershell.exe
标准位置：%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe
Edition：Desktop
```

路径中的 `v1.0` 不是实际产品版本。Windows PowerShell 的最终版本是 5.1，支持周期跟随 Windows。微软说明见：

- <https://learn.microsoft.com/powershell/scripting/what-is-windows-powershell>
- <https://learn.microsoft.com/powershell/module/microsoft.powershell.core/about/about_windows_powershell_5.1>

PowerShell 7 使用 `pwsh.exe`，需要另外安装，并与 Windows PowerShell 5.1 并存。程序可以优先使用已安装的 PowerShell 7，但绝不能把它当作 Windows 10 必然具备的组件。

建议的首版自动探测顺序：

```text
1. 用户显式配置的绝对路径和 shell kind
2. %ProgramFiles%\PowerShell\7\pwsh.exe
3. PATH 中的 pwsh.exe，解析为绝对路径并验证
4. %SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe
5. 明确返回 shell_not_found
```

PATH 命中不能来自 workspace/cwd，解析结果、版本、edition 和 `source=path` 必须进入审计。不能把所有用户可写目录一律拒绝，因为 Scoop 和便携安装可能是用户的有效选择；显式配置仍然拥有最高优先级。

首版建议不自动回退到 `cmd.exe`。`cmd` 会立即引入第三套语法、转义、编码、退出码和策略规则，也会在 shell 探测失败时改变 policy subject 的方言。正常 Windows 10 自带 PowerShell 5.1，因此 Cmd 自动兜底主要服务损坏或非标准镜像，不值得削弱 fail-closed 一致性；可先作为显式 opt-in。

## CC、Codex 和 pi 的参考结论

### Claude Code（CC）

CC 的成熟默认路线仍然是要求 Git Bash：

- Windows 启动时解析 Git Bash；
- 支持显式 `CLAUDE_CODE_GIT_BASH_PATH`；
- 从 Git 安装目录推导 `bash.exe`；
- 未找到时明确报错；
- Bash 与 PowerShell 使用独立 provider，不让两种方言共享错误的 argv 协议。
- PowerShell 使用专门的 AST/安全检查，覆盖动态调用、下载执行、提权和混淆输入，并在解析失败时转入审批。

参考路径：

```text
/home/dev/workspace/cc/src/utils/windowsPaths.ts
/home/dev/workspace/cc/src/utils/Shell.ts
/home/dev/workspace/cc/src/utils/shell/shellProvider.ts
/home/dev/workspace/cc/src/utils/shell/powershellProvider.ts
/home/dev/workspace/cc/src/tools/PowerShellTool/powershellSecurity.ts
```

这一策略可靠，但不满足“干净 Windows 无额外安装即可运行”的产品目标。

### Codex

Codex 最接近本提案的默认路线：

- 明确建模 Bash、Zsh、Sh、PowerShell 和 Cmd；
- Windows 默认探测 PowerShell，最终可回退 Cmd；
- shell kind 参与 argv 构造；
- Windows 工具描述明确告诉模型使用 PowerShell 语法；
- PowerShell 注入 UTF-8 初始化。

参考路径：

```text
/home/dev/workspace/codex/codex-rs/shell-command/src/shell_detect.rs
/home/dev/workspace/codex/codex-rs/core/src/shell.rs
/home/dev/workspace/codex/codex-rs/core/src/tools/handlers/shell_spec.rs
/home/dev/workspace/codex/codex-rs/shell-command/src/powershell.rs
```

### pi

pi 提供了适合 Bash 兼容能力的 Windows 解析路线：

- 支持显式 shell path；
- 探测 Git Bash 的常见安装目录；
- 再使用 `where bash.exe`；
- 未找到时给出明确诊断；
- 对旧 WSL Bash 使用不同 transport；
- Windows 取消采用进程树终止；
- shell 退出后对被后代持有的输出管道使用有限 idle grace；每收到新的输出都重新计时，而不是使用固定总死线。

参考路径：

```text
/home/dev/workspace/pi/packages/coding-agent/src/utils/shell.ts
/home/dev/workspace/pi/packages/coding-agent/src/core/tools/bash.ts
/home/dev/workspace/pi/packages/coding-agent/src/utils/child-process.ts
```

综合建议是：**采用 Codex 的跨平台 shell 建模作为主路线，采用 pi 的 Git Bash 解析和输出生命周期设计作为兼容路线，并参考 CC 的 PowerShell 专用安全策略。**

## 发布阻断项

### 1. PowerShell 策略当前会 fail-open

现有策略的 shell 入口、token 化和 effect detector 都以 POSIX 为中心：

- [`policy/subjects.py`](../../../src/loushang/harness/policy/subjects.py)
- [`policy/effects_detection.py`](../../../src/loushang/harness/policy/effects_detection.py)
- [`policy/engine.py`](../../../src/loushang/harness/policy/engine.py)

当策略检测不到 effect 时，默认结果是 allow。以下 PowerShell 命令可能不经过审批：

```powershell
Remove-Item -Recurse -Force .\target
Invoke-Expression $downloadedText
Start-Process powershell -Verb RunAs
Invoke-WebRequest $url | Invoke-Expression
Remove-ItemProperty HKCU:\Software\...
```

PowerShell 还存在 POSIX detector 无法正确处理的方言边界：

- `rm`、`del`、`erase`、`ri`、`rd` 等可能是 `Remove-Item` 的别名；
- Windows PowerShell 5.1 中的 `iwr`、`curl`、`wget` 等可能解析到 `Invoke-WebRequest`，`iex` 解析到 `Invoke-Expression`；
- 参数缩写和大小写不敏感；
- 反引号拆词、smart quotes、Unicode dash，以及安全扫描器应保守识别的 `/` 参数前缀等混淆输入；
- 别名可以被重定义，无法静态确定时必须视为动态调用。

别名和混淆规则必须按 `flavor` 区分，不能假定 Windows PowerShell 5.1 与 PowerShell 7 拥有相同别名表，也不能继续用 POSIX `rm` 语义判断 PowerShell 的 `rm`。

因此 PowerShell 执行器和 PowerShell policy 必须同步上线。首版保守规则应为：

- 可靠识别的直接只读命令可以 allow；
- 解析失败、超时、脚本过长、动态命令、嵌套 shell、`-EncodedCommand`、UNC 访问统一 ask；
- headless 模式下无法分类则 deny；
- 首版只支持逐次精确审批，不生成宽泛的持久 PowerShell 授权。

为避免“所有命令都 ask”造成审批疲劳和习惯性放行，P2 之前必须至少可靠分类一小组无副作用的只读形态，例如受限参数下的 `Get-ChildItem`、`Get-Content`、`Get-Location` 和 `Get-Process`。一旦包含重定向、动态表达式、provider 写入或嵌套命令，就不能沿用只读结论。

策略和 UI 必须分析、展示明文脚本。即使 transport 使用 Base64，策略也不能分析 Base64 blob。

### 2. 进程树终止和 reader 收尾不可靠

当前本地进程实现主要依赖 POSIX `start_new_session` 和 `killpg`。Windows 上只终止外层 PowerShell 会留下 child/grandchild。

此外，[`workspace/exec/service.py`](../../../src/loushang/harness/workspace/exec/service.py) 在 shell 退出后无界等待 stdout/stderr reader。只要后代继承管道，当前 POSIX 路径也可能永久等不到 EOF，并阻碍 asyncio cancellation 完成。因此有限 drain 是现存跨平台正确性修复，不只是 Windows 新功能。

最低上线要求：

- timeout、显式取消、外层 asyncio task cancellation、Session close 都进入同一终止路径；
- 首版至少同步等待 `%SystemRoot%\System32\taskkill.exe /T /F /PID <pid>`；
- 长期使用 Windows Job Object，并处理 spawn 后加入 Job 的竞态；
- 终止后对输出 reader 只做有限 drain，不无限等待 EOF；
- tree-kill 首版在诊断与审计中标记为 best-effort，记录 taskkill 结果和可能的再生窗口。

Job Object 解决进程生命周期，不等于文件系统 sandbox。

### 3. 编码和输出管道不可靠

Windows PowerShell 5.1 和它启动的原生子进程不天然保证 UTF-8。当前固定 UTF-8 解码和 `readline()` 还存在以下问题：

- 中文输出乱码；
- 超长无换行输出触发读取问题；
- shell 退出后，后代继承管道导致 reader 永久等待。

建议：

- PowerShell 使用 `-NoLogo -NoProfile -NonInteractive`；
- 显式初始化 `[Console]::OutputEncoding`、`[Console]::InputEncoding` 和 `$OutputEncoding`；
- 使用分块读取和增量 decoder；
- shell 退出后启动短暂 idle grace，每收到 data chunk 就重新计时，连续沉默到期后主动关闭读取；具体时长需要由 Python/Windows 压测确定，pi 的 100 ms 只作为起点；
- 对二进制或无法解码输出保留安全替代行为和诊断。

### 4. 退出码语义必须单独定义

PowerShell 的 cmdlet、native executable、非终止错误、`throw`、pipeline、显式 `exit N` 对 `$?` 和 `$LASTEXITCODE` 的影响不同。不能简单假定 PowerShell 自身退出码等于逻辑命令结果。

实现必须定义并测试统一语义，至少覆盖：

- 成功 cmdlet；
- cmdlet 非终止错误；
- `throw`；
- `exit 7`；
- native child exit 7；
- native command 与 cmdlet 混合 pipeline；
- `$ErrorActionPreference='Stop'` 下的 cmdlet 错误。

实现可以使用 `$?`、`$LASTEXITCODE`、`trap` 或显式包装进行归一，但不能未经设计就强制改变用户的 `$ErrorActionPreference`，因为这本身会改变脚本语义。

### 5. 长脚本 transport 尚未定义

Windows `CreateProcessW` 的完整命令行有约 32,767 个 UTF-16 code unit 的上限，`-EncodedCommand` 还会因 UTF-16LE Base64 膨胀。`-Command`、`-Command -`、`-File` 和临时脚本文件也具有不同的退出码、引用和完整性语义。

P1 必须让 `ShellLaunch` 明确记录 transport，并对序列化后的完整 argv 做长度检查。首版建议：

- 正常脚本统一使用经过测试的 `-Command`/`-EncodedCommand` 路径；
- 超出保守上限时返回结构化 `command_too_long`，不能静默切换到 `-File` 或临时文件；
- 后续只有在 stdin transport 的退出码、取消、编码、策略指纹和 transcript 语义经过真实 Windows 测试后，才允许以 `-Command -` 承载长脚本；
- 无论 transport 如何变化，策略和审批始终使用同一份明文脚本，执行指纹包含 transport 和精确 argv。

### 6. Windows 当前没有可用的本地 sandbox

现有 sandbox 后端是 Linux Bubblewrap。Windows best-effort 会降级到本地执行，因此：

- UI、诊断和审计必须明确显示未沙箱化；
- `sandbox=required` 时必须拒绝，不能静默降级；
- 在 Windows filesystem sandbox 落地前，PowerShell policy 必须采用保守策略。

## 推荐的核心模型

底层 `ExecService` 应继续保持 shell-free argv 边界；shell 选择与脚本编译位于它的上层。

```python
ShellKind = Literal["powershell", "bash", "sh", "zsh", "cmd"]

@dataclass(frozen=True)
class ResolvedShell:
    kind: ShellKind
    executable: str       # 已验证的绝对路径
    flavor: str | None    # pwsh / windows-powershell / git-bash
    source: str           # configured / path / system-fallback
    target_id: str

@dataclass(frozen=True)
class ShellLaunch:
    shell: ResolvedShell
    plain_script: str
    transport: str        # command / encoded-command / stdin
    argv: tuple[str, ...]
    cwd: str
    effective_environment: tuple[tuple[str, str], ...]
```

建议执行链：

```text
shell(script)
  -> 获取执行目标的 ShellCapabilities
  -> 解析并冻结 ResolvedShell
  -> 按 shell kind 编译精确 argv
  -> 使用 plain script + shell kind 构造 policy subject
  -> 审批并绑定同一份 cwd/env/argv
  -> 交给现有 shell-free ExecService
```

关键不变量：

- shell 针对执行目标解析，而不是盲目根据控制进程所在 OS 解析；
- 自动解析只接受可信绝对路径，不能从 workspace/cwd 选择伪造的 `pwsh.exe`；
- 每次工具调用提供的 PATH 覆盖不能改变已经冻结的 shell；
- shell 的 `source`、版本、edition/flavor 和 transport 必须进入 audit/transcript metadata；
- 审批后 shell、script、cwd、env 或 argv 任一变化，都必须使执行指纹失效；
- 用户 `!` 命令和模型命令必须走同一 resolver、policy、approval、audit、sandbox 和 ExecService。

## 工具命名与兼容性待决策

评审中形成两种意见：

### 方案 A：模型工具命名为 `exec_command`

优点：与 Codex 和通用“执行命令”心智一致，跨平台含义清晰。

问题：当前扩展 API 已有 `exec_command(command, args)`，它表示直接 argv，而不是 shell script：[`session/agent_adapter.py`](../../../src/loushang/harness/session/agent_adapter.py)。静默复用会造成 API 语义冲突。

### 方案 B：模型工具命名为 `shell`（当前推荐）

优点：明确表达输入是 shell script，不与直接 argv API 重名。

建议配套：

- 稳定逻辑能力 ID 使用 `workspace.command`；
- Windows 默认只向模型暴露 `shell`；
- POSIX 可以在兼容周期继续暴露 `bash`；
- Windows 的 `bash` 仅在用户显式配置 Git Bash 时启用；
- `execute_bash`、`BashExecutionRuntime`、`user_bash` 暂时保留兼容包装；
- blocked/allowed/ask 规则最终绑定 `workspace.command`，不能仅按工具名称绑定。

`shell` 名称本身不表达方言，因此工具 description、参数 schema 和平台提示必须根据 `ResolvedShell.flavor` 明确写出“PowerShell 5.1”“PowerShell 7”或“Git Bash”，并给出对应语法。特别是 PowerShell 5.1 不支持 `&&`/`||`，而 `~`、引用和 profile 行为也不能套用 Bash 心智。

兼容移除不预先绑定到一个固定 minor 版本：公共 SDK、hook 和持久 transcript 至少保留一个正式 deprecation 周期，最终移除应服从公共兼容政策和使用证据。过渡期内旧的按名规则必须同时映射 `bash` 与稳定能力 ID `workspace.command`，防止存量 blocked/ask 策略静默失效。

如果最终坚持 `exec_command`，必须明确引入 `mode="argv" | "script"` 和迁移策略，不能让旧调用静默改变含义。

## 配置迁移建议

不要直接删除已有字段。建议增量增加：

```text
command_shell_kind = auto | powershell | bash | sh | zsh | cmd
command_shell_path = <absolute path or null>
command_shell_login = false
```

兼容规则：

- 新配置优先；
- 显式配置无效时 fail-closed，不继续自动探测；
- 仅存在旧 `shell_path` 时保留其 Bash/POSIX 兼容含义并发出迁移提示；
- 旧 `shell_command_prefix` 不得自动注入 PowerShell，因为它可能包含 `set -e`、`source` 等 Bash 语法；
- Git Bash 默认使用 `-c`，login/profile 模式必须显式开启并采用更保守审批。

## 安全交付顺序

### P0：跨平台进程底座，不新增用户工具

- Windows spawn 选项和 `CREATE_NO_WINDOW`；
- 完整进程树取消；
- 分块输出、增量解码和有限 drain；
- Windows 环境变量大小写不敏感合并；
- cwd 预检查和结构化 launch error。

此阶段不改变模型可见工具，能够独立合并和验证。由于有限 drain 和 cancellation 会修改现有 POSIX 热路径，交付门槛必须同时覆盖 POSIX 的 timeout、abort、大输出和“后代持管道”回归。

### P1：隐藏的 ShellSpec 与 policy 安全合同

- 增加目标环境感知的 resolver/compiler；
- 增加 shell kind、明文 script 和精确 argv 的 policy subject；
- 增加 PowerShell AST/保守解析、flavor-aware 别名展开和混淆输入检查；
- PowerShell 无法分类时默认 ask/headless deny；
- PowerShell 首版只允许逐次精确审批；
- 建立最小可靠只读命令分类，避免 P2 全量 ask；
- 定义 `command`/`encoded-command` transport 和 `command_too_long` 行为；
- 接通统一的退出码与 UTF-8 包装测试；
- 新增 policy subject 字段不得改变现有 Bash 决策：现有 Coding/Harness policy 测试全量通过，并增加代表性 Bash 决策快照对比。

此阶段仍不注册 Windows 模型工具。

### P2：原子启用 Windows 产品路径

同一切片必须完成：

- Settings -> CLI -> ToolOptions -> ShellSpec 的真实接线；
- 新工具注册、builtin/default 分类、multi-agent allowlist 和 policy capability 映射；
- 按执行目标的 platform/shell capabilities 门控新工具；本地首版可由 host capability 得出 Windows，但不能把散落的 `os.name == "nt"` 当作长期边界；
- 根据 PS5.1/PS7 flavor 生成平台提示词、参数 schema 和工具描述；
- 用户 `!` 与模型工具统一 runtime；
- 同一 Session `ExecService` 成为唯一执行权威；
- `bash` 兼容 API、事件和 transcript 的迁移适配。

只有这一片完整通过后，才能宣称 Windows 开箱即用。

P2 可以先合入 Settings -> ToolOptions -> ShellSpec 的不可达接线测试，只要尚未注册 Windows 工具就不会扩大执行面；工具注册、默认激活和 policy capability 映射必须保持原子。POSIX 默认工具表和行为在这一阶段保持字面不变。

### P3：降低审批噪音并增强隔离

- 扩大 PowerShell AST/effect detector 覆盖率并降低误报；
- 增加受控的 PowerShell 持久授权；
- 根据评审决定加入 Cmd；
- 使用 Job Object 改善原子进程归属；
- 评估 Windows filesystem sandbox；
- 支持远端执行目标报告 shell capabilities。

## 必须覆盖的 Windows 验收矩阵

| 维度 | 必测场景 |
|---|---|
| 环境 | 仅 PS5.1、PS7+PS5.1、非 C 盘 `%SystemRoot%`、无 Git Bash、显式 Git Bash、Program Files/PATH/Scoop 来源、cwd 中伪造 `pwsh.exe` |
| 路径 | 空格、中文、长路径、盘符大小写、junction/reparse point、UNC、cwd 不存在或不是目录 |
| 语法 | PS5.1 不支持 `&&/||`、PS7 支持；`~` 差异、引号、smart quotes、反引号、here-string、多行、中文、emoji、`$()` |
| I/O | UTF-8 stdout/stderr/stdin、超过 64 KiB 无换行输出、大输出 artifact、后代持有管道 |
| Transport | 普通 `-Command`、非 ASCII/EncodedCommand、接近 32,767 上限、`command_too_long`、策略始终展示明文 |
| 退出 | cmdlet 非终止错误、`throw`、`exit N`、native 非零退出、混合 pipeline、`ErrorActionPreference=Stop` |
| 生命周期 | timeout、显式取消、task cancellation、Session close、child+grandchild 清理、无窗口闪烁 |
| 策略 | 删除/覆盖、注册表、下载、IEX、RunAs、动态调用、别名重定义、大小写/缩写、`/` 前缀、Unicode dash、smart quotes、反引号拆词、nested pwsh/cmd/wsl、UNC、parser error/timeout |
| 审批 | UI 展示明文；shell/script/cwd/env/argv 变化使指纹失效；不存在宽泛 PowerShell 持久授权 |
| Git Bash | 默认 `-c`、安装路径带空格、中文 cwd、未安装不影响 PowerShell、绝不自动选择 WSL |
| Sandbox | disabled、best-effort degraded、required failure 都有明确诊断 |

P1 还必须在非 Windows CI 上证明现有 Bash policy 决策不变；P0 必须证明有限 drain 和 cancellation 没有破坏 POSIX 热路径。

不能只在 Linux 上 mock `os.name`；Windows 开箱即用结论必须由真实 Windows CI 证明。

## 请求评审的问题

请评审者优先回答以下问题：

1. `ShellSpec`/`ResolvedShell` 的所有权是否应位于 `loushang.harness.workspace`，同时让 Coding 保留风险分类、提示和默认激活策略？
2. 模型工具应命名为 `shell`，还是在解决现有 argv API 冲突后命名为 `exec_command`？
3. Windows 首版是否应仅自动探测 `pwsh -> Windows PowerShell 5.1`，把 Cmd 留作显式 opt-in？
4. PowerShell 无法可靠分类时 `interactive=ask`、`headless=deny` 是否足够保守？
5. P0/P1/P2 的切片是否保证任何可合并中间状态都不会暴露未受策略保护的 PowerShell？
6. `taskkill /T /F` 是否可以作为首版完整进程树终止，还是 Job Object 必须进入 P0？
7. 现有 `bash` 工具名、SDK、hook、transcript、blocked-tools 和持久授权分别需要多长兼容周期？
8. `command_too_long` 是否是首版可接受的 fail-closed 行为，还是 stdin transport 必须进入 P1？
9. flavor-aware 别名、混淆输入和最小只读分类是否足以让 P2 同时避免 fail-open 与审批疲劳？
10. 文档是否遗漏 PowerShell 5.1、Windows 路径、编码、退出码、UNC/reparse point 或企业 sandbox 的关键边界？

## 可复制给其他 Agent 的评审请求

> 请对 `docs/internals/specs/2026-08-12-windows-shell-execution-design-review.md` 做一次严格、只读的架构与安全评审。请结合 loushang 当前代码和本地只读参考仓库 `codex/`、`cc/`、`pi/` 核实文档中的事实，不要只评价文字；重点检查 PowerShell 5.1/7 的 argv、编码、退出码、别名与混淆输入，长脚本 command-line 上限和 transport，Windows/Posix 进程树取消与管道收尾，PowerShell 策略是否 fail-closed 且不会引发全量审批疲劳，shell 解析是否针对执行目标，配置是否真正接入模型工具与用户 `!` 命令，以及 `shell`/`exec_command`/`bash` 的 API、权限能力 ID、hook、transcript 和迁移兼容。请列出阻断项、非阻断建议、不同意的决定及证据路径，验证 P1 不改变既有 Bash 策略决策，并判断 P0/P1/P2 是否能够在每个可合并中间状态保持安全；本轮只评审，不修改文件。
