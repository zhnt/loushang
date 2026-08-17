# Loushang Coding Observability Design

状态：Draft

本文定义 `loushang.coding` 与 `loushang.tui` 的轻量可观测性设计。目标不是建设一套“大一统观测平台”，而是把用户体验、开发者调用方式和内部语义收敛到一个足够简单、足够可靠的模型。

最终方向：

- 外部体验借鉴 Kimi CLI / Claude Code：`--debug`、per-session debug log、`latest` symlink、TUI 内 `/debug`。
- 内部语义借鉴 PI 的结构化 diagnostics 思路，但使用更直观的 `Problem` 概念。
- 开发者只面对一个 logger-like 对象：`get_log(__name__)`。
- P0 不引入 Event Bus；由 `ObservabilityLog` 内部 fanout 到各 sink。

## Design Principles

### UX First

普通用户不应该理解 log、trace、diagnostics、ProblemStore 的区别。排查问题时，主入口应该是：

```bash
loushang --debug
```

复杂竞态或流式问题再使用：

```bash
loushang --debug=tui,agent --trace=tui,agent
```

TUI 中途排障入口是：

```text
/debug
```

### One Developer Entry

开发者不应该在 `logger.warning(...)`、`trace.emit(...)`、`diagnostics.record(...)` 之间做选择。模块内只需要：

```python
from loushang.foundation.observability import get_log

log = get_log(__name__)
```

然后按照事实性质调用：

```python
log.info("coding session started")
log.problem("provider_request_cancelled", recoverable=True, exc=err)
log.debug_event("tui", "prompt.dispatch.start", active_run=True)
```

### Structured Where It Matters

普通 debug log 可以是人类可读文本；但用户/上层能感知的问题必须结构化记录为 `Problem`，内部竞态/时序信息必须可选择性输出为结构化 trace JSONL。

### No Session Dependency Cycle

`loushang.foundation.observability` 是基础层，不允许依赖 `loushang.coding.session`、`loushang.coding.runtime`、`loushang.coding.ui` 或 provider 具体实现。session/run/cwd/mode 等信息通过 context variables 绑定。

依赖方向：

```text
loushang.foundation.observability
  <- loushang.ai
  <- loushang.coding
  <- loushang.tui
```

如果 coding 需要把 Problem 持久化到 session，由 coding 在启动时注入 sink；observability 不反向 import coding。

## Core Concepts

### Transcript

Transcript 是产品事实，不属于 observability 本体。

职责：

- 保存用户消息、assistant 消息、tool call/result。
- 支撑 resume、compact、replay、context rebuild。
- 必须保持稳定 schema 和 timestamp 单位。

约束：

- 不保存 TUI redraw、agent loop 细节、provider chunk 时序。
- 不作为 debug log 或 trace 的替代品。
- 可在 export bundle 中被引用，但不由 observability 层写入。

### Problem

Problem 是用户、UI、RPC、doctor、export 或上层控制流需要知道的异常事实。

典型场景：

- provider request cancelled
- tool validation failed
- session timestamp normalized
- model selection ambiguous
- config/resource collision
- abort recovery failed

Problem 必须结构化、可查询、可导出，并且不受 logging level 过滤。

建议字段：

```python
ProblemRecord(
    code="provider_request_cancelled",
    severity="error",
    source="provider",
    message="Request cancelled.",
    recoverable=True,
    session_id="...",
    run_id=4,
    cwd="/repo",
    mode="tui",
    details={},
)
```

说明：

- 文档概念使用 `Problem`。
- 现有 `DiagnosticRecord` 可以作为 Problem 的当前存储/查询模型。
- `Diagnostic` 一词仍可用于 IDE/LSP diagnostics；避免把所有运行期问题都叫 diagnostics。

### Debug Event

Debug Event 是内部排障事实，用于理解状态机、时序、竞态和性能。

典型场景：

- TUI prompt dispatch start/end
- active_run/session_running 状态快照
- agent loop lifecycle
- provider streaming chunk/tool JSON 解析状态
- terminal emit timing
- abort/steer/follow 控制流

Debug Event 默认不需要用户看到；只有 `--debug=<scope>` 或 `--trace=<scope>` 匹配时才写入对应 sink。

事件建议形状：

```json
{
  "time": "2026-05-14T12:00:00.123Z",
  "monotonic_ms": 123456789,
  "scope": "tui",
  "name": "prompt.suppressed_cancelled",
  "module": "loushang.coding.ui.mode",
  "component": "CodingUiMode",
  "session_id": "...",
  "run_id": 4,
  "data": {
    "active_run": false,
    "session_running": false
  }
}
```

## Developer Decision Tree

遇到需要记录的信息时，按以下顺序判断：

```text
会影响 session 恢复、回放、上下文重建？
  -> Transcript 层处理，不在 observability 里重复写。

用户、UI、RPC、doctor、export 或上层控制流需要知道，或者能据此做反应？
  -> log.problem(...)

只是内部状态、时序、竞态、性能排障信息？
  -> log.debug_event(...)

普通人类可读调试说明？
  -> log.debug/info/warning/error(...)
```

判断标准：

- 如果问题发生后系统需要展示、恢复、重试、停止、查询或导出，使用 `log.problem(...)`。
- 如果只是帮助开发者还原“刚才发生了什么”，使用 `log.debug_event(...)`。
- 如果既是 Problem 又需要时序细节，先 `log.problem(...)`，必要时再补 `log.debug_event(...)`。

## ObservabilityLog API

### Entry

```python
from loushang.foundation.observability import get_log, log_context

log = get_log(__name__)
```

`get_log(__name__)` 返回 logger-like 对象。变量名推荐使用 `log`，降低采用门槛。

### Context

```python
with log_context(session_id=session_id, run_id=run_id, cwd=str(cwd), mode="tui"):
    await controller.dispatch(intent)
```

context 使用 `contextvars` 实现，自动附加到 Problem、Debug Event 和 debug log。

基础 context 字段：

- `session_id: str | None`
- `run_id: int | str | None`
- `cwd: str | None`
- `mode: str | None`

observability 层只认识这些基础字段，不认识 session object。

### Human-Readable Log Methods

```python
log.debug("inline runtime redraw requested")
log.info("coding session started")
log.warning("model fallback selected")
log.error("provider request failed")
```

语义：

- 写人类可读 debug log。
- 受 debug/log level 和 scope 配置影响。
- 不创建 Problem。

### Problem

建议签名：

```python
def problem(
    code: str,
    *,
    message: str | None = None,
    severity: ProblemSeverity = "error",
    source: str | None = None,
    recoverable: bool = False,
    exc: BaseException | None = None,
    details: Mapping[str, JSONValue] | None = None,
) -> ProblemRecord:
    ...
```

示例：

```python
log.problem(
    "provider_request_cancelled",
    source="provider",
    recoverable=True,
    exc=err,
)
```

```python
log.problem(
    "tool_validation_failed",
    source="tool",
    recoverable=True,
    details={"tool": "write", "reason": "missing path"},
)
```

约束：

- `code` 必填，使用 snake_case。
- `message` 可选；默认可由 `code` 或 `exc` 推导。
- `severity` 建议枚举：`error`、`warning`、`info`。
- `details` 必须 JSON-safe；不要塞 session object、Path object、raw provider payload。
- `Problem` 不受 logging level 过滤。

快捷入口：

```python
log.problem_from_exception(
    exc,
    code="provider_request_cancelled",
    source="provider",
    recoverable=True,
)
```

### Debug Event

建议签名：

```python
def debug_event(
    scope: str,
    name: str,
    **data: JSONValue,
) -> None:
    ...
```

示例：

```python
log.debug_event(
    "tui",
    "prompt.dispatch.start",
    active_run=active_run,
    session_running=session_running,
)
```

约束：

- 调用方不判断 debug/trace 是否开启。
- `scope` 是排障分类，不从 module 自动推导。
- `name` 使用 dot-separated 名称。
- `data` 必须 JSON-safe。

推荐 scope：

- `tui`
- `agent`
- `tool`
- `provider`
- `session`
- `scenario`

### Binding Component

模块名自动来自 `get_log(__name__)`。类/组件名可显式绑定：

```python
log = get_log(__name__).bind(component="CodingUiController")
```

字段区别：

- `module`：Python 模块名，自动。
- `component`：类或组件名，手动绑定。
- `scope`：Debug Event 排障域。
- `source`：Problem 来源。

不要用 module 推导 scope。

## Output Sinks

P0 不做 Event Bus。`ObservabilityLog` 内部直接 fanout。

```text
log.debug/info/warning/error
  -> DebugLogSink

log.problem(...)
  -> ProblemStoreSink
  -> DebugLogSink if debug enabled
  -> TraceJSONLSink if trace enabled

log.debug_event(...)
  -> DebugLogSink if debug scope matches
  -> TraceJSONLSink if trace scope matches
```

未来如果 sink 增加到 telemetry、metrics、remote upload、alerting，再抽 `ObservationRouter` / Event Bus。

配置语义：

- `configure_observability(...)` 是局部更新：未传的 sink/scope 保持不变。
- 显式传 `debug_sink=None` 或 `trace_sink=None` 会清除对应 sink，并清除对应 scope，避免旧 scope 泄漏到下一个 sink。
- coding/runtime 临时注入 ProblemStore 或 per-session sink 时，必须先 capture 当前配置，退出时 restore；不要用 `reset_observability()` 清掉外层 debug/trace。
- `reset_observability()` 只用于进程级清理、测试隔离或明确需要丢弃全部 observability 配置的路径。

### DebugLogSink

职责：

- 人类可读 debug log。
- per-session 文件。
- 支持 `/debug` 中途开启。

默认路径：

```text
~/.loushang/debug/<session_id>.log
~/.loushang/debug/latest -> <session_id>.log
```

session 尚未创建时：

```text
~/.loushang/debug/startup-<timestamp>-<pid>.log
```

P0 可直接写 startup 文件；后续可优化为内存 buffer，绑定 session 后 flush。

滚动建议：

- 单文件上限：20MB。
- rollover 文件数：5。
- 清理 14 天前 debug 文件。
- `latest` symlink 指向当前 session 主文件，不指向 rollover 文件。

### TraceJSONLSink

职责：

- 结构化排障事件。
- 用于竞态、流式、状态机、scenario 排查。

默认路径：

```text
~/.loushang/traces/<session_id>.jsonl
~/.loushang/traces/latest -> <session_id>.jsonl
```

滚动建议：

- 单文件上限：50MB。
- rollover 文件数：3。
- 清理 14 天前 trace 文件。

Trace event 同时包含 wall-clock `time` 和 monotonic `monotonic_ms`，避免只依赖 float timestamp。

### ProblemStoreSink

职责：

- 保存当前进程/session 的 Problem。
- 支撑 UI/RPC/doctor/export 查询。

P0：

- 内存 store。
- 可由 coding 注入 session summary sink。

后续：

- 按 session 持久化 Problem 摘要。
- 支持 `get_problems(...)` / `get_problem_summary(...)` 查询。

### Export Bundle

P0 命令：

```bash
loushang diag export --output PATH
```

打包内容：

- transcript/session record；
- Problem 摘要；
- debug log；
- trace JSONL；
- model/config 摘要；
- Python/platform/package 版本；
- 隐私过滤后的 manifest。

Export Bundle 是输出产品，不是新的记录类别。

## CLI And TUI UX

### CLI

建议入口：

```text
--debug
--debug=<scope-list>
--debug-file PATH
--trace
--trace=<scope-list>
--trace-file PATH
```

语义：

- `--debug` 是主入口，写人类可读 debug log，并默认启用全部 Debug Event scope。
- `--debug=<scope-list>` 只写指定 Debug Event scope，例如 `--debug=tui,agent`。
- `--trace` 打开结构化 trace JSONL。
- `--trace=<scope-list>` 只输出指定 scope。
- `--debug` 不自动打开完整 JSONL trace。
- `--trace` 不要求 debug log 同时开启，但实际排障建议两者可组合。

Scope list 使用逗号分隔：

```bash
loushang --debug=tui,agent --trace=tui,agent
```

### TUI

Slash command：

```text
/debug
/debug tui,agent
/debug off
```

行为：

1. 如果 debug log 未开启，则为当前 session 开启。
2. 可用 `/debug <scope-list>` 指定 scope，scope 用逗号或空格分隔。
3. 可用 `/debug off` 关闭当前进程的 debug log sink；ProblemStore 不受影响。
4. 显示 debug log 路径、latest symlink 和当前 scope。
5. 显示最近若干行 error/warning/problem 摘要。
6. 提示用户复现问题后可查看或导出。

示例输出：

```text
Debug logging enabled:
~/.loushang/debug/latest
Scopes: all

Diagnostics bundle:
loushang diag export --cwd /path/to/project --output /path/to/project/.loushang/diagnostics/loushang-diag.zip --debug-file ~/.loushang/debug/<session_id>.log
```

不建议 P0 增加新的 TUI keybinding；slash command 更明确，也更容易测试。

### Env Policy

长期入口应少而稳定：

```text
LOUSHANG_DEBUG_SCOPES
LOUSHANG_DEBUG_FILE
LOUSHANG_TRACE_SCOPES
LOUSHANG_TRACE_FILE
```

不作为长期入口：

```text
LOUSHANG_DEBUG
LOUSHANG_TUI_TRACE
LOUSHANG_TUI_TRACE_FILE
```

当前这些旧变量来自临时排障实现，不进入正式 API。实现迁移时可以一次性更新 tests/scenarios/docs；不设计长期隐藏兼容层。

CLI 优先级高于 env。

## Reference Alignment

### Kimi CLI

可借鉴：

- 全局 `--debug`。
- 文件日志。
- session/wire 与 log 分离。
- export bundle 聚合 session 与近期日志。

不直接照搬：

- Kimi 偏文本日志；Loushang 的 TUI/agent/provider 竞态需要结构化 Problem 和 Debug Event。

### Claude Code

可借鉴：

- per-session debug log。
- `latest` symlink。
- `/debug` 中途开启并读取 tail。
- `--debug=<filter>`。
- debug log 是用户主入口，高级 tracing 另行开启。

不直接照搬：

- CC 的 `diagnostics` 多指 IDE/LSP diagnostics；Loushang 的运行期问题应使用 `Problem`。
- CC 的 tracing/telemetry 体系比 P0 所需更重。

### PI

可借鉴：

- diagnostics/problem 作为结构化事实，而不是纯日志文本。
- runtime/service 初始化返回 diagnostics，由上层决定展示或终止。

不直接照搬：

- P0 不做完整 Event Bus 或复杂 diagnostics service 重构。

## Migration Plan

1. 使用 canonical `loushang.foundation.observability` 包；旧
   `loushang.observability` 入口已经退出。
   - `get_log(...)`
   - `log_context(...)`
   - `ObservabilityLog`
   - `ProblemRecord`
   - sink interfaces

2. 接入 CLI/TUI debug 配置。
   - `--debug`
   - `--debug=<scope-list>`
   - `--debug-file`
   - per-session debug log
   - `latest` symlink

3. 替换 TUI 临时 trace writer。
   - 移除 TUI 专属 trace env 解析。
   - 使用 `log.debug_event("tui", ...)`。

4. 接入 trace JSONL。
   - `--trace`
   - `--trace=<scope-list>`
   - `--trace-file`
   - provider `options.trace` adapter 到 `log.debug_event("provider", ...)` 或 TraceJSONLSink。

5. 接入 Problem。
   - provider cancellation / request error。
   - tool validation failure。
   - session normalization warning。
   - model selection/config error。

6. 将 coding UI 错误展示改为 Problem/ErrorReport 投影。
   - `■ Error: ...`
   - abort/interruption 不重复刷屏。

7. 收敛 scenarios trace flags。
   - 内部统一到 debug/trace scopes。
   - 不保留长期旧 env 兼容层。

8. 增加 `/debug`。
   - 中途开启 debug log。
   - 显示 path 和 recent tail。

9. 增加 `loushang diag export`。
   - 不启动 agent runtime。
   - 打包 latest debug log、latest trace、latest session JSONL、Problem/diagnostics 摘要和 manifest。

## Non-Goals

- P0 不实现 Event Bus。
- P0 不实现远程 telemetry。
- P0 不承诺 trace event schema 为稳定公共 API。
- P0 不把完整用户 prompt、文件内容、raw provider payload 默认写入 debug log 或 trace。
- P0 不把 Transcript 迁移进 observability 层。
