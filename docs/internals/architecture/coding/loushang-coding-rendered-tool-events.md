# Loushang Coding Rendered Tool Events

## Scope

本文档定义 `loushang-coding` 中 rendered tool event 的边界合约。

它覆盖两类入口：

- print JSON mode:
  - `--mode json --render-tool-events`
  - `run_print_mode(..., output_mode="json", render_tool_events=True)`
- RPC JSONL mode:
  - `--mode rpc --render-tool-events`
  - `run_rpc_mode(..., render_tool_events=True)`

本文档不重新定义工具执行模型。工具执行仍由 `ToolDefinition.execute(...)` 和 agent tool loop 负责；
rendered tool event 只是把已有 `tool_execution_*` session event 投影成客户端可直接展示的 payload。

## Boundary Position

Rendered tool event 位于下面这个边界：

```text
ToolDefinition.render_call/render_result
  -> ToolRenderRuntime
  -> event projection
  -> PrintMode JSON / RpcMode JSONL / HTML export
```

职责划分：

- `ToolDefinition`
  - 可选提供 `render_call` / `render_result`
  - 只负责生成工具自己的展示内容

- `ToolRenderRuntime`
  - 保存同一个 `tool_call_id` 下的 renderer state
  - 提供 `ToolRenderContext`
  - 兼容 sync renderer callback

- event projection
  - 把 renderer 输出装进稳定 wire payload
  - 补齐状态、耗时、artifact、partial/expanded 等边界字段

- mode / export
  - 决定是否启用 rendered payload
  - 决定输出 JSONL、RPC event 或 HTML data attribute

## Activation

默认不输出 rendered payload。客户端必须显式启用：

```bash
python -m loushang.coding.cli --mode json --event-view tools --render-tool-events "list files"
python -m loushang.coding.cli --mode rpc --render-tool-events
```

程序入口示例：

```python
await run_print_mode(
    runtime=runtime,
    session=session,
    user_input="list files",
    output_mode="json",
    event_view="tools",
    render_tool_events=True,
)
```

如果某个工具没有 renderer，或者 renderer 抛错，事件仍正常输出，只是不附加 `rendered_tool_call` /
`rendered_tool_result`。renderer failure 不应影响工具执行和 agent turn。

## Output Keys

`tool_execution_start` 使用：

```json
{
  "type": "tool_execution_start",
  "tool_call_id": "call-1",
  "tool_name": "bash",
  "args": {"command": "ls"},
  "rendered_tool_call": {
    "type": "text",
    "text": "$ ls",
    "plain_text": "$ ls",
    "contract_version": 1,
    "status": "running"
  }
}
```

`tool_execution_update` 和 `tool_execution_end` 使用：

```json
{
  "type": "tool_execution_end",
  "tool_call_id": "call-1",
  "tool_name": "bash",
  "result": {"content": [{"type": "text", "text": "README.md\n"}], "terminate": false},
  "is_error": false,
  "rendered_tool_result": {
    "type": "text",
    "text": "README.md",
    "plain_text": "README.md",
    "contract_version": 1,
    "status": "ok",
    "is_partial": false,
    "expanded": false,
    "collapsed_text": "README.md",
    "duration_ms": 12,
    "artifacts": []
  }
}
```

## Render Payload Contract

所有 rendered payload 都带：

- `contract_version`: 当前为 `1`
- `type`: `text`、`html` 或 `custom`

文本 payload 通常带：

- `text`: 面向展示的文本
- `plain_text`: 面向复制、日志、搜索、降级展示的文本

HTML payload 通常带：

- `html`: 已由 renderer 生成的 HTML fragment
- `plain_text`: HTML 不可用时的降级文本

客户端应基于 `contract_version` 做能力判断。未知字段必须容忍，避免破坏向前兼容。

## Result Status

`rendered_tool_call.status` 当前固定为：

- `running`

`rendered_tool_result.status` 可能是：

- `partial`: 来自 `tool_execution_update`
- `ok`: 最终成功
- `error`: `is_error` 为 true
- `terminate`: `AgentToolResult.terminate` 为 true
- `timed_out`: result details 中 `timed_out` 为 true
- `cancelled`: result details 中 `cancelled` 为 true

状态由 event projection 统一推导，工具 renderer 不需要自己维护这些跨工具语义。

## Partial And Expanded

结果 payload 会稳定包含：

- `is_partial`: 是否是中间 update
- `expanded`: 当前输出是否为 expanded 渲染
- `collapsed_text`: collapsed 渲染的纯文本摘要，存在时可用于折叠态
- `expanded_text`: expanded 渲染的纯文本摘要，存在时可用于展开态

当前 print / RPC 的默认投影使用 collapsed 渲染。HTML export 可以按页面需要同时保留 renderer metadata。

## Duration

`duration_ms` 的解析优先级：

1. renderer payload 自带 `duration_ms`
2. `AgentToolResult.details.duration_ms`
3. `AgentToolResult.details.elapsed_ms`
4. session event 的 `duration_ms`

只接受非负数值，并投影为整数毫秒。

## Artifacts

`artifacts` 由 result details 推导。当前支持这些 key：

- `stdout_artifact_path`
- `stderr_artifact_path`
- `full_output_path`

输出形态：

```json
{
  "type": "file",
  "path": "/tmp/loushang-bash-stdout.txt",
  "name": "loushang-bash-stdout.txt",
  "stream": "stdout"
}
```

`stream` 只在能从 key 推断出 `stdout` / `stderr` 时出现。

## Protocol Rules

- `rendered_tool_call` / `rendered_tool_result` 是 additive 字段，不改变原始 `tool_execution_*` event。
- 未启用 `render_tool_events` 时，JSON/RPC 输出保持原形。
- renderer 不存在或失败时，事件仍输出，不生成 rendered payload。
- `text`、`plain_text`、`is_partial`、`expanded` 等字段使用 snake_case。
- camelCase 字段不再接受或发出；客户端必须升级到当前协议。
- 客户端应允许新增字段，并基于 `contract_version` 做降级。

## Related Code

- [projection.py](/home/dev/workspace/loushang/src/loushang/coding/event/projection.py)
- [print_mode.py](/home/dev/workspace/loushang/src/loushang/coding/mode/print_mode.py)
- [rpc_mode.py](/home/dev/workspace/loushang/src/loushang/coding/mode/rpc_mode.py)
- [rendering.py](/home/dev/workspace/loushang/src/loushang/coding/tools/rendering.py)
- [builtin_renderers.py](/home/dev/workspace/loushang/src/loushang/coding/tools/builtin_renderers.py)
