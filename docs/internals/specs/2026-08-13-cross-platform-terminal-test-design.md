# 跨平台原生终端与 TUI 测试设计

状态：经三项独立只读评审、最终文本复核及一轮外部联合评审后修订，认可进入实施；跟踪 issue：[#445](https://github.com/zhnt/loushang/issues/445)。

日期：2026-08-13

## 结论

Windows 不能因为缺少 Unix `pty` 或 `tmux` 而跳过 TUI 产品能力。正确做法也不是把 ConPTY 原始输出当作 Windows 版 `capture-pane`，而是建立一套按证据能力分层、按平台选择实现、在 CI 中 fail-closed 的跨平台终端验证栈：

1. **共享确定性语义合同**：复用现有 `FakeScreen`、`FakeTerminalPort`、playback 和 screen-loop 测试，Linux 与 Windows 运行同一套渲染、历史、光标、压缩、恢复和退出清理断言。
2. **原生伪终端进程合同**：同一个产品测试合同通过 POSIX PTY 或 Windows ConPTY 启动真实 CLI，验证 TTY 边界、输入输出、VT 生命周期、resize、退出码、有限 drain 和进程树清理。
3. **终端实现专属合同**：tmux 继续验证它实际解释后的 pane、scrollback 和 `capture-pane` 语义；Windows 不运行 tmux，但必须运行前两层和 ConPTY 专属合同。

这三类证据是现有 Native TUI 四层测试策略的纵向补充，不替代 `Pure Renderable -> Render Loop -> Terminal Playback -> Boundary` 分层。

## 目标与非目标

### 目标

- 明确区分 API 最低兼容边界、自动化验证平台与正式支持平台，不用依赖 wheel 存在替代本仓库证据。
- Linux 与 Windows 对相同用户可见不变量执行同一个 native terminal contract，而不是维护两套漂移的产品测试。
- 平台差异被封装在 test-only driver 内，不污染 `loushang.tui` 产品 API。
- required CI 中 backend 缺失、零测试、skip、挂起或清理失败都必须失败并给出结构化诊断。
- ConPTY transport、确定性 screen model 和真实 terminal emulator 的证据边界清晰，不作过度声明。

### 非目标

- 首版不自研完整的 `CreatePseudoConsole` ctypes 封装。
- 首版不把 pywinpty 加入产品运行依赖。
- 首版不实现完整 VT emulator，也不声称 ConPTY 原始 VT 流等价于最终 Windows Terminal 屏幕。
- 不要求 Windows 运行 tmux 专属功能；能力不适用不等于跳过 Windows 产品合同。
- 首版正式验证范围收敛为 Windows x64、Python 3.11+；Windows ARM64 仅标记为 API 层预期兼容，进入独立 runner 或发布验收矩阵后才升级为正式支持。
- 不扩展到 Windows x86、早于 Windows 10 1809 的系统或所有 Python 版本组合。

## 当前事实与缺口

### 已有能力

- `src/loushang/tui/terminal.py` 已有 `FakeScreen`、`FakeTerminalPort` 和 `ProcessTerminalPort`。
- `src/loushang/tui/playback.py`、`src/loushang/harnesstui/testing/` 和 `tests/coding/tui_support/playback.py` 已形成确定性 playback 基础，不能重复建设。
- `tests/coding/test_screen_coding_tui_terminal_playback.py` 已覆盖自动压缩后的历史/流式输出和退出清理最终屏幕。
- `src/loushang/tui/terminal_platform.py` 与 `terminal_input.py` 已包含 Windows VT console mode 和 `msvcrt` 输入路径。
- `tests/coding/test_screen_coding_tui_pty_smoke.py` 已有 POSIX `/quit` smoke 和 tmux scrollback 集成。

### 现存缺口

1. 测试模块顶层无条件 `import pty`。Python 的 `pty` 只支持 Unix，Windows 会在执行任何 `pytest.skip()` 之前收集失败。
2. `/quit` PTY smoke 没有 `tui_render_contract` marker，也不在 `HARNESSTUI_TEST_PATHS` 中，当前两个 TUI workflow 实际都不执行它。
3. `tui_render_contract` 同时承载确定性 playback 和外部 tmux 集成，marker 语义不纯。
4. tmux 缺失时静默 skip；即使合同从未运行，CI 仍可能绿色。
5. `tests/tui/test_terminal_platform.py`、`test_terminal_session.py` 和 `test_terminal_input.py` 未进入现有 TUI required gate。
6. `TimedTtyChunkInput` 以 `os.pipe()` 模拟输入却声明 `isatty() == True`。Windows 下产品 reader 因而改走 `msvcrt` 并读取当前进程控制台，而不是 scripted pipe；共享 screen-loop playback 可能挂起或读取错误输入。
7. tmux fixture 的 ready file 只证明子进程已写出，不证明 tmux 已消费完输出；随后立即 `capture-pane` 有竞态。
8. auto-compaction tmux 用例混合策略、Session、持久化、恢复、投影、渲染和 scrollback，多数状态断言应属于共享确定性合同。

本设计形成前的本地聚焦基线为 23 项通过。受限沙箱内 tmux 因 socket `Operation not permitted` 失败，沙箱外同一组测试全部通过；这也证明环境能力诊断与产品回归报告必须分开。

## 证据架构

| 证据层 | 回答的问题 | 公共机制 | 平台路由 |
|---|---|---|---|
| 共享确定性语义 | 逻辑历史、viewport、cursor、最终 screen 和清理语义是否正确 | 现有 FakeTerminal/playback/screen-loop | Linux、Windows 同一套 |
| 原生伪终端 transport | 真实 CLI 是否识别 TTY、接受输入、输出 VT、退出并清理 | `TerminalProcessDriver` contract | POSIX PTY / ConPTY |
| 终端实现集成 | 特定 emulator/multiplexer 如何解释 VT 并保存历史 | tmux `capture-pane`；未来可选 VT emulator | Ubuntu tmux；Windows 首版无等价 pane API |
| 人工真实终端 | IME、候选窗、宿主快捷键及肉眼体验 | 发布前 smoke checklist | Windows Terminal、VS Code、WezTerm、Kitty 等 |

### 证据边界

- `strip_control_sequences(raw_output)` 只删除控制序列，不执行光标移动、清行、覆盖和 scrollback，因此不能证明最终屏幕状态。
- “退出后最终 screen 没有 idle/running 状态栏”由 FakeTerminal playback 负责。
- 原生 PTY/ConPTY 负责证明相应 cleanup/restore VT 序列确实穿过真实终端 transport、命令正常退出且没有残留进程。
- tmux `capture-pane -S -` 负责证明 tmux 解释后的 pane/history；它不能被 ConPTY raw output 机械替代。

## 共享确定性语义层

### 复用而非重建

继续使用以下所有权：

- `loushang.tui`：render operation、FakeScreen、FakeTerminalPort 和基础 playback。
- `loushang.harnesstui.testing`：产品中立 conversation/render/screen-loop 测试能力。
- `tests/coding/tui_support`：Coding 专属 scenario、fixture 和产品绑定。

不得新增第二套 FakeScreen、第二套 render playback 或独立的“Windows screen model”。

### 修复 Windows fake-TTY 缺陷

共享 screen-loop 测试不应使用 `os.pipe() + isatty=True` 假冒操作系统控制台。推荐为 screen-loop runner 注入明确的 input-chunk source/read function，使确定性测试消费 scripted bytes；原生 TTY reader 则由 PTY/ConPTY 合同单独覆盖。

验收要求：

- 相同 screen-loop suite 在 Ubuntu 和 Windows 上运行。
- 测试输入永远不读取 CI runner 的真实 console。
- decoded input、生命周期、压缩、history/resume、退出清理均无平台 skip。

### auto-compaction 职责拆分

- 把 `AgentSession 自动压缩 -> TUI projection -> persistence/resume` 及 JSON evidence 迁移为平台无关组合合同。
- tmux 用例只保留需要真实 pane/history 的最小场景。
- 手工 compact 和自动 compact 共享 scenario 数据，不各自维护一套 80/40 行魔法常量。

## Test-only 原生终端驱动

### 所有权与目录

中立驱动放在：

```text
tests/tui/terminal_process_support/
  __init__.py
  contract.py
  diagnostics.py
  factory.py
  posix_pty.py
  windows_conpty.py
```

Coding 产品 smoke 放在：

```text
tests/coding/test_cli_terminal_contract.py
```

tmux 专属集成放在：

```text
tests/coding/test_tmux_scrollback_integration.py
```

这样 driver 仍为 test-only、可供任何 TUI 产品复用，又不会错误归属到 Coding 产品或 `harnesstui` conversation 层。

### 统一接口

```python
class TerminalProcessDriver(Protocol):
    @classmethod
    def spawn(
        cls,
        args: Sequence[str],
        *,
        cwd: Path,
        env: Mapping[str, str],
        columns: int,
        rows: int,
    ) -> Self: ...

    def __enter__(self) -> Self: ...
    def __exit__(self, exc_type, exc, traceback) -> Literal[False]: ...
    def write(self, text: str) -> None: ...
    def read_until(
        self,
        predicate: Callable[[str], bool],
        *,
        timeout: float,
    ) -> str: ...
    def resize(self, *, columns: int, rows: int) -> None: ...
    def is_alive(self) -> bool: ...
    def wait(self, *, timeout: float) -> int: ...
    def terminate_tree(self, *, timeout: float) -> None: ...
    def close(self, *, timeout: float) -> None: ...

    @property
    def raw_output(self) -> str: ...

    @property
    def diagnostics(self) -> TerminalProcessDiagnostics: ...
```

接口合同：

- `args` 必须是结构化 argv，不允许 `shell=True`；不得用 `shlex.join()` 构造 Windows 命令行。
- PTY 的 stdout/stderr 合并是显式合同。
- driver 是 context manager，`__exit__()` 委托幂等 `close()` 并返回 `False`；断言失败、timeout 和异常路径都必须关闭 handle/FD、终止进程树。
- 后台持续 drain，不能依赖 `readline()`；ANSI、无换行输出和跨 chunk Unicode 都必须工作。
- POSIX 使用增量 UTF-8 decoder；ConPTY 若 library 返回 Unicode，也要保留原始文本边界和 reader error。
- 输出使用有界 ring buffer；诊断保留 backend、PID、argv、cwd、尺寸、退出状态、reader error 和有限输出尾部。
- 所有 timeout 使用 monotonic deadline。
- 进程退出后采用“收到数据则重新计时”的有限 idle drain，避免丢失尾部恢复序列。
- `close()` 和 `terminate_tree()` 幂等。

### Driver conformance

两个 backend 必须运行同一个 conformance suite：

- argv、cwd、env，含空格和中文路径；
- 中文、emoji、跨 chunk UTF-8；
- CR、CRLF 和无换行输出；
- VT 序列保持可观测；
- 初始尺寸与 resize；
- 退出码 0 和非 0；
- 大于管道容量的输出后立即退出；
- timeout/cancellation 后根进程和孙进程均无残留；
- 输出管道 EOF/reader 完成、尾部 idle drain、重复 close；不把 POSIX Ctrl-D 与 Windows input-channel close 伪装成统一的输入 EOF 合同；
- terminal query/response 不挂起。

## POSIX PTY backend

- 平台专属 `pty`、`select`、`termios`、`fcntl` 导入只存在于 `posix_pty.py`。
- 子进程使用新 session/process group；timeout 后先温和终止，再按 deadline 强制杀整个组。
- resize 使用 `TIOCSWINSZ` 并验证子进程能观察到新尺寸。
- 把 PTY master 上的预期 EIO 识别为 EOF，不吞掉其他 OSError。
- 读循环、有限 drain、输出上限和错误诊断必须与 ConPTY 后端语义一致。

## Windows ConPTY backend

### 支持边界与依赖

ConPTY API 最低可用边界为 Windows 10 1809/build 17763 和 Windows Server 2019；这不等于每个最低版本都已有持续验证。首版自动化验证平台为 Windows Server 2022 x64/Python 3.11，正式桌面验收平台为 Windows 10 22H2 x64。测试后端通过 Python 标准库 `ctypes` 直接调用系统 ConPTY API，不下载 Windows 原生 wheel。ARM64 在 API 层预期兼容，但必须增加独立 CI 证据后才声明支持，不能从 API 可用性推导已验证兼容。

P1 在 Windows Server 2022 上实测拒绝了两个 pywinpty 候选：`3.0.5`/`winpty-rs 1.0.6` 的异步写入可能把最后一次 terminal response 留在 pending 状态，异步 reader 也会在进程退出边界丢失大输出尾块；`2.0.15` 会在跨块 UTF-8 输出中产生替换字符，且真实 CLI 正常退出后 reader 不能在总 deadline 内关闭。首版因此不引入 pywinpty 开发依赖，而以测试专用薄封装显式拥有 pipe、HPCON、process handle 和线程生命周期。任何未来依赖替换都必须通过 query、无换行大输出、退出码、进程树与零残留合同，不能只按版本号前进。

### 强制 ConPTY

- backend 必须显式选择 `ConPTY`，不能使用自动选择后静默回退 WinPTY。
- required CI 中缺少依赖、系统版本过低、架构无 wheel、创建失败或实际 backend 不符都直接失败并打印诊断。
- 不启用 `PSEUDOCONSOLE_INHERIT_CURSOR`。

### 同步 I/O、drain 与关闭

ConPTY driver 使用自己拥有的同步匿名管道，必须：

- 用独立 reader thread 持续排空输出；测试主线程不得直接阻塞在 `PtyProcess.read()`。
- writer 串行化，测试输入和 terminal responder 不并发写底层 PTY。
- 自己实现有 deadline 的 `read_until()` 与 `wait()`，不直接暴露 Win32 同步 I/O 的无界阻塞面。
- Windows 超时清理使用从可信 `%SystemRoot%\System32` 解析的绝对路径 `taskkill.exe /PID <pid> /T /F` 作为同步进程树兜底，记录 stdout、stderr 和退出码；随后轮询 fixture 暴露的根/孙 PID 直到消失或 deadline。`taskkill` 非零但进程已不存在可记录为竞态成功，仍有残留则 required CI 失败。后续若产品引入 Job Object，可复用更强的树生命周期能力。
- 关闭采用有总 deadline 的状态机，而不是固定的“先 join reader、再 close PTY”：reader 从 spawn 起持续运行；请求正常退出或同步树终止；在 reader 仍持续排空时启动经过 spike 验证的 PTY teardown（后端若支持则显式管理 output endpoint）；等待 teardown/EOF；必要时调用 `cancel_io()` 解除阻塞；最后有限 join reader 并确认 thread/handle 零残留。
- 所有输入/输出 pipe、HPCON、process/thread handle 都有唯一所有者；传给 `CreatePseudoConsole` 的 server-side pipe handles 是借用关系，必须存活到 `ClosePseudoConsole` 返回后才能关闭。正常退出、timeout 和异常路径都必须关闭。`ClosePseudoConsole` 在独立受 deadline 约束的线程执行，同时 reader 持续 drain；未通过零残留断言前不得以 Python 外层进程退出推定 ConPTY 已安全关闭。

### Terminal query responder

headless ConPTY 不只是哑管道。当前源码审计显示产品主动发出两类 query：KeyboardProtocolController 的 `ESC[?u`（150ms 后回退 modify-other-keys）以及 capability-gated 的 `ESC[16t`；后者不会阻塞产品启动，若终端响应则输入层解析 `ESC[6;<height>;<width>t`。此外 ConPTY backend、依赖或专用 fixture 可能触发 DSR。P1 必须从产品源码、pywinpty/winpty-rs 行为和测试 fixture 重新生成“query -> 响应/无响应 -> fallback/deadline”清单，并把清单固化为 responder contract，不能仅依赖本设计中的静态枚举。

最小 responder 必须跨 chunk 识别并响应：

- `CSI 5 n` -> `CSI 0 n`；
- `CSI 6 n` -> harness 明确配置的合法位置（首版默认 `ESC[1;1R`），仅作为 headless-test fallback 解阻塞。

driver 不拥有 screen model，因此该固定 DSR 响应不代表真实最终 cursor，也不能用于验证 cursor correctness。若未来产品合同依赖真实 cursor truth，必须增加有限 VT cursor tracker，并对超出支持的控制序列 fail-closed。首版不伪装 Kitty keyboard protocol 支持；对 `ESC[?u` 保持无响应并验证产品按既有 150ms deadline 回退。hermetic 基线 profile 关闭 cell-size query；单独的 cell-size profile 对 `ESC[16t` 明确选择“无响应但产品继续运行”或返回受控的 `ESC[6;<height>;<width>t`，两条路径都需测试。主动 DSR fixture 必须验证跨 chunk query、响应格式及普通文本不被误识别；清单中任何可能阻塞且无已验证 fallback 的未知 query 都 fail-closed。

### 原生 Windows 单元边界

Windows CI 还必须实际执行 terminal platform/session/input 的共享及 Windows 专属集合；Ubuntu 执行共享及 POSIX 专属集合。P0 要把当前文件中依赖 `termios`/`tty` 或显式 Windows skip 的测试拆到精确集合，required job 不整文件运行后再容忍 runtime skip。

相关现有文件包括：

- `tests/tui/test_terminal_platform.py`；
- `tests/tui/test_terminal_session.py`；
- `tests/tui/test_terminal_input.py`。

覆盖 VT input/output mode、Quick Edit 处理、`msvcrt` 输入、正常/异常/timeout 后 console mode 恢复。共享、POSIX-only、Windows-only 测试由 workflow 精确选择，required 集合内部不得保留 `importorskip` 或平台 skip。这些单元测试不能被 ConPTY smoke 取代。

## 共享真实 CLI 产品合同

POSIX PTY 与 Windows ConPTY 执行同一组断言：

1. 用 `sys.executable -m loushang.coding.cli --tui` 启动结构化 argv。
2. 等待明确的产品 readiness 条件，而不是绑定某个 `show cursor` 实现细节。
3. 确认欢迎内容和所需 VT 生命周期序列到达 transport。
4. 发送 `/quit\r`，在有界时间内以退出码 0 结束。
5. 确认启用过的 cursor、paste、mouse/focus/keyboard 等终端模式有配对的恢复序列。
6. 完成有限 tail drain，输出末尾不再追加 live `idle/running` 状态。
7. timeout 或断言失败时无子孙进程、FD、handle 或 reader thread 残留。

注意：第 5、6 项只断言 transport 中发出了清理/恢复事实；最终 screen 的精确状态仍由共享 FakeTerminal playback 证明。

产品合同必须使用 hermetic terminal environment：从清洗后的宿主环境构造，明确设置 `TERM`/`COLORTERM`，清除 `TMUX`、`STY`、`WT_SESSION`、`TERM_PROGRAM`、Kitty/WezTerm/Ghostty、SSH/WSL 等会改变 capability detection 的身份变量。Windows 环境变量按大小写不敏感方式合并，避免 `PATH`/`Path` 重复。需要验证特定宿主时另建显式 profile，不能让 CI runner 的偶然环境改变共享断言。

第二阶段增加：

- 中文输入/输出；
- resize 后继续输入并退出；
- Ctrl-C、异常退出和强制 timeout 恢复；
- 连续 10–20 次运行的稳定性检查。

## tmux 专属合同

- 独立 marker：`tui_tmux_integration`。
- Ubuntu CI 显式安装并运行 `tmux -V`；required job 中缺失或 socket 启动失败直接失败。
- 不再以 ready file 作为唯一完成条件；轮询 `capture-pane`，直到最终可见 sentinel/预期尾行出现或 monotonic deadline 到期。
- 失败诊断包含 tmux server stderr、pane capture 和 fixture evidence。
- 对关键 sentinel 在可行时断言恰好一次，避免 `rfind` 掩盖重复历史回放。
- tmux 测试只保留 pane/history/scrollback 证据；自动压缩策略、持久化和 resume 状态移入共享组合合同。

## Marker 与 CI 设计

### Marker

- `tui_render_contract`：纯 Python、确定性、平台无关，不依赖外部终端进程。
- `tui_terminal_backend`：POSIX PTY/ConPTY driver conformance。
- `tui_terminal_contract`：共享真实 CLI 产品合同。
- `tui_tmux_integration`：tmux pane/history 专属集成。

required marker 中不得使用平台 `skipif` 来表达实现路由。workflow/fixture 选择当前 backend，合同本身保持共享。

### Required jobs

| Job | Runner | 必须执行 |
|---|---|---|
| deterministic-render | `ubuntu-24.04` + `windows-2022` | 共享 render/playback/screen-loop；零平台 skip |
| terminal-platform-unit | `ubuntu-24.04` + `windows-2022` | 共享集合 + 当前平台专属集合；required collection 零 skip |
| native-terminal | `ubuntu-24.04` | POSIX PTY backend conformance + 共享 CLI contract |
| native-terminal | `windows-2022` | 强制 ConPTY backend conformance + 同一 CLI contract |
| tmux-scrollback | `ubuntu-24.04` | 显式安装 tmux，执行 pane/history 合同 |

CI 公共规则：

- 使用 Python 3.11，并固定 `ubuntu-24.04` 与 `windows-2022`，避免 `*-latest` 迁移操作系统版本；runner image 内部更新仍通过 job 日志与失败诊断记录。
- Windows 直接运行 `uv sync --locked --extra dev` 与 `uv run pytest`，不依赖当前 POSIX Make recipe。
- native job 设置 `LOUSHANG_REQUIRED_TERMINAL_BACKEND=posix-pty|conpty`；tmux job 设置 `LOUSHANG_REQUIRE_TMUX=1`。
- 使用 `--strict-markers --strict-config`、job `timeout-minutes` 和 JUnit 输出。
- 平台无关的 JUnit 校验器要求 required job 的测试数大于零、skipped 为零、failure/error 为零，并核对诊断中的实际 backend；该校验器属于 P0 交付物，不是只停留在 workflow 约定中的人工检查。
- 不把“本机缺少可选能力”静默转为假绿；普通本地运行可以给出明确 capability unavailable 诊断，required CI 必须失败。
- native 与 tmux job 必须显式选择 `tests/tui/terminal_process_support/` 及对应产品合同路径；driver 位于 `tests/tui/` 不代表现有白名单 gate 会自动收集它。

GitHub hosted Windows Server 只证明 Windows API 与 ConPTY 路径。若 Windows 10 是正式支持平台，还必须保留 Windows 10 22H2/build 19045 实机或 self-hosted nightly/发布前验收。

## 分阶段实施

### P0：测试语义与 CI 止血

- 创建/绑定跟踪 issue，并记录当前基线。
- 首先在 `windows-2022` 运行 terminal platform/session/input 与共享 playback 的裸基线，记录通过、失败和现有 skip，再据此拆分共享/POSIX/Windows collection；不把未知基线直接算作产品回归。
- 拆分顶层 Unix-only import，保证 Windows 能收集共享测试。
- 修复 `TimedTtyChunkInput` 假 TTY；共享 screen-loop 改用注入的 scripted input source。
- 纯化 marker，拆出共享、POSIX、Windows terminal platform/input 集合，确保 `/quit` smoke 与相应单元测试进入明确 gate。
- marker 拆分与最小 Ubuntu tmux required job 原子落地：显式安装/预检 tmux，required collection 零 skip。若该 job 尚未就绪，不得先把现有 tmux 测试移出 render gate。
- deterministic render/playback 在 Ubuntu 和 Windows 同时运行。
- 增加平台无关的 JUnit 结果校验器并在每个 required job 调用：断言 tests > 0、skipped = 0、failures/errors = 0，并在 native job 校验实际 backend。
- 更新 `pyproject.toml` marker 注册/说明、Native TUI testing strategy 及 `tests/tui/test_tui_testing_strategy_docs.py`，避免文档守护测试和 marker 语义漂移。
- 把 `make test-tui` 改造为与新集合一致的跨平台本地入口，或以明确的新入口替代并删除；不得保留一个 CI 永不调用且只能在 POSIX `.venv/bin/activate` 下工作的权威名称。

P0 风险清单必须点名 `src/loushang/harnesstui/testing/screen_loop_playback.py` 和当前 required gate 中使用本地 `_TimedTtyChunkInput` 的 `tests/coding/test_screen_coding_tui_loop.py`；input source 注入不得只修共享 helper 而遗漏产品侧同类假 TTY。

交付门槛：Windows 共享合同不 skip、不读取 runner 真实 console；现有 Linux 确定性回归不降级。

### P1：Windows ConPTY 生命周期技术选型 spike（不独立合并）

在正式抽象前，用锁定版本、强制 ConPTY 验证五个场景：

1. 大于 64 KiB 的无换行输出与 backpressure，以及独立的立即退出尾部 drain；
2. 产品/依赖/fixture query 全集盘点，为每一类定义响应、无响应 fallback 与 deadline，并覆盖 DSR、Kitty 和 cell-size profile；
3. 正常退出与尾部 drain；
4. timeout 后孙进程清理；
5. 重复 close/异常路径无挂起。

Spike 结果必须固化为 backend conformance tests，不能只留下实验脚本。

P1 是探索分支上的合并前门槛，不是可单独发布的切片。它比较 `PtyProcess`、低层 `winpty.PTY` 与显式所有权的测试薄封装，最终淘汰两个 pywinpty 候选并选择直接 Win32 ConPTY 路径；选型证据通过后再进入 P2a/P2b。不得把临时依赖、无 required CI 的 spike 或无法验证 thread/handle 零残留的实现合入主线。

### P2a：中立协议、POSIX backend 与既有 smoke 迁移

- 在 P1 已验证双平台可实现性的接口上落地 test-only driver protocol 与 POSIX PTY backend。
- 固化 POSIX backend conformance，增加 Ubuntu native-terminal required job。
- 迁移现有 `/quit` smoke 为同一产品合同。

P2a 不宣称 Windows 原生 terminal contract 已完成，也不得关闭 P0 的 Windows deterministic/platform gates。共享合同与协议必须以 P1 已验证的 ConPTY 生命周期能力为约束，避免 POSIX 先行后把 Windows 实现逼入不兼容接口。

### P2b：ConPTY 与 Windows native gate 原子启用

- 落地基于 Win32 API 的强制 ConPTY backend；保持测试栈零 Windows 条件依赖，Linux 与 Windows 均不安装 pywinpty。
- 增加 Windows native-terminal required job；显式选择 test support、backend conformance 和同一 `/quit` 产品合同路径。
- 把 P1 的大输出、query matrix、Unicode、resize、退出码、timeout 子孙进程、输出 EOF/drain 和幂等 close 固化为双 backend conformance。

P2b 不允许合并“Windows job 存在但全部 skip”“ConPTY backend 尚未受进程树清理保护”或“ConPTY teardown 尚未证明 reader/handle 零残留”的中间状态。P2a 与 P2b 可以分成小步提交，但 P2b 是 Windows 原生支持声明和本轮跨平台目标的发布阻断项，不能停在 P2a 宣称完成。

### P3：tmux 与 auto-compaction 职责收敛

- 自动压缩、投影、持久化、恢复迁移为共享组合合同。
- tmux 用例瘦身为真实 pane/history 证据。
- 在 P0 已有 required job 上继续完善 capture polling、完成 sentinel、有限 drain、重复检测和 fixture 诊断。
- `kill-server` 必须有 timeout、退出诊断和清理后确认；清理失败不能被 finally 中的 `check=False` 静默吞掉。

### P4：真实产品与宿主稳定性发布矩阵

- 将 P2b 已在 backend conformance 覆盖的 Unicode、resize、Ctrl-C/timeout、异常退出、无换行和大输出进一步扩展到真实 CLI 产品场景。
- PR 上做小规模重复，nightly 做 10–20 次稳定性检查。
- Windows 10 22H2 实机/自托管验收 Windows Terminal、VS Code Terminal 和至少一个第三方宿主。
- ARM64 若要升级为正式支持，必须在本阶段加入 Windows ARM64 自托管/native runner，实际运行依赖安装、ConPTY conformance 和共享 CLI contract；否则继续标记为预期兼容。
- 只有在需要自动证明 Windows 最终屏幕解释时，再评估独立 VT emulator；它不是首版阻断项。

## 发布验收矩阵

| 不变量 | FakeTerminal | POSIX PTY | ConPTY | tmux |
|---|---:|---:|---:|---:|
| 精确 logical history/viewport/cursor | 必须 | 不声明 | 不声明 | pane 结果 |
| 自动压缩与 persistence/resume | 必须 | 不绑定 | 不绑定 | 不再承担 |
| 最终 screen 清除 live 状态栏 | 必须 | 不声明 | 不声明 | 可观察 |
| 真实 CLI TTY 识别与 `/quit` | 不适用 | 必须 | 必须 | 非核心 |
| VT cleanup/restore 穿过 transport | operation 级 | 必须 | 必须 | 可观察 |
| resize/Unicode/退出码 | 语义级 | 必须 | 必须 | 非核心 |
| timeout/进程树/handle 清理 | 不适用 | 必须 | 必须 | fixture 清理 |
| pane scrollback/history | 模型级 | 不声明 | 不声明 | 必须 |

最终完成标准：Ubuntu 与 Windows 共享 native contract 均实际执行且零 skip；Windows 诊断确认使用 ConPTY；tmux job 实际启动并零 skip；正常退出、异常和 timeout 三条路径均恢复终端且无残留；现有 deterministic render contract 不降级。

## 三项独立评审与裁决

本方案经架构边界、Windows/ConPTY、测试/CI 三个只读 Agent 独立评审，在正式文本落盘后完成第二轮逐条复核，并吸收一轮外部联合评审。共同认可三类证据分离、双 backend 共享产品合同、ConPTY 不等于 `capture-pane`、Windows required job 零 skip。已吸收的关键意见包括：

- 先修 Windows fake-TTY playback 输入缺陷；
- 新增独立 terminal/tmux marker，补齐现有 CI 覆盖空洞；
- 区分 ConPTY API 最低边界、x64 正式验证范围和 ARM64 预期兼容，避免无证据的支持声明；
- reader thread、可配置 terminal query responder、有限 drain、同步树终止和幂等 close；
- 删除不可移植的统一输入 EOF 语义，并将 ConPTY teardown 能否零残留设为 P1 技术选型门槛；
- 平台单元测试拆成共享/POSIX/Windows 精确集合，避免“零 skip”与现有 runtime skip 冲突；
- auto-compaction 状态合同与 tmux pane 合同拆分；
- tmux marker 与最小 required job 在 P0 原子落地，readiness 后续改为 capture polling，CI 中依赖缺失不允许 skip。
- 外部联合评审进一步补充并已采纳：JUnit fail-closed 校验器归入 P0、产品 query 全集归入 P1、Ubuntu runner 固定、测试策略守护与本地入口同步、tmux teardown 诊断，以及 P2 拆为可审查的 P2a/P2b。

对 driver 放置存在轻微分歧：一项评审建议放 Coding test support，另一项建议放 TUI test support。本方案选择中立的 `tests/tui/terminal_process_support/`，因为 driver 不包含 Coding 语义；Coding `/quit` contract 仍留在 `tests/coding/`，避免所有权混淆。

## 可交给其他 Agent 的评审请求

> 请对 `docs/internals/specs/2026-08-13-cross-platform-terminal-test-design.md` 做一次严格、只读的架构、Windows 与 CI 联合评审，不要修改文件。请对照 loushang 当前 `src/loushang/tui/`、`src/loushang/harnesstui/testing/`、`tests/tui/`、`tests/coding/test_screen_coding_tui_pty_smoke.py`、`tests/coding/test_screen_coding_tui_terminal_playback.py`、`tests/coding/tui_support/`、Makefile 和 `.github/workflows/` 核实事实；重点判断：现有 Native TUI 四层测试与新增三类终端证据是否职责清晰且不重复，`TimedTtyChunkInput` 的 Windows 假 TTY 缺陷是否被正确处理，test-only driver 的所有权和接口是否足以覆盖 argv/Unicode/resize/timeout/有限 drain/进程树/幂等关闭，pywinpty 强制 ConPTY、Windows API 最低边界与实际支持声明、同步 I/O、terminal query responder 与旧系统关闭死锁是否完整，ConPTY raw VT 与最终 screen/tmux capture-pane 是否严格区分，以及 required CI 的 marker、零 skip、测试数校验、Windows Server 2022 与 Windows 10 实机矩阵是否能防止假绿。请逐项列出认可项、阻断项、非阻断建议、不同意的决定和证据路径，并判断 P0/P1/P2a/P2b/P3/P4 每个切片或技术门槛是否保持跨平台正确性与 fail-closed。

## 参考

- Python `pty`：<https://docs.python.org/3/library/pty.html>
- Microsoft `CreatePseudoConsole`：<https://learn.microsoft.com/en-us/windows/console/createpseudoconsole>
- Microsoft 创建 pseudoconsole session：<https://learn.microsoft.com/en-us/windows/console/creating-a-pseudoconsole-session>
- Microsoft `ClosePseudoConsole`：<https://learn.microsoft.com/en-us/windows/console/closepseudoconsole>
- pywinpty：<https://pypi.org/project/pywinpty/>
- pywinpty（被 P1 spike 淘汰的候选）：<https://github.com/andfoy/pywinpty/>
- winpty-rs terminal query 注意事项：<https://github.com/andfoy/winpty-rs#important-notes>
- GitHub Actions runner image labels：<https://github.com/actions/runner-images>
