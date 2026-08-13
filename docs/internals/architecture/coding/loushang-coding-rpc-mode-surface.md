# Loushang Coding RPC Mode Surface

## Status

- Authority: historical compatibility contract
- Design status: superseded
- Implementation status: retired at this owner/path
- Superseded by: `loushang.harness.host.rpc`

The body below records the former `coding.mode.RpcMode` surface. It is retained
for protocol migration and compatibility analysis; it does not describe the
Current owner or import path. Current boundaries are
[Harness Mode/Host](../harness/mode-host-boundary.md) and
[Session/RPC Operations](../harness/session-rpc-operation-boundary.md).

## Scope

本文档记录当前 `RpcMode` 的 concrete JSONL surface。

它补充架构文档中的 `mode` / `session` one-pager，重点回答：

- `RpcMode` 当前接受什么命令
- `get_state` 的 canonical shape 是什么
- mutator / lifecycle response 为什么要收瘦
- `model` 在 RPC 中如何从 `loushang.ai.Model` 投影出来

`RpcMode` 当前定位是 transitional headless mode surface，不是长期
package-level `loushang.channel` protocol layer。长期 channel 设计见
[ARD-005: RPC Mode Transitional Channel Positioning](ARD-005-rpc-mode-transitional-channel-positioning.md)。

相关架构文档仍然看这里：

- [mode](component-interfaces/mode.md)
- [session](component-interfaces/session.md)
- [Loushang Coding Key Mode Sequences](loushang-coding-key-mode-sequences.md)

当前代码入口：

- [rpc_mode.py](/home/dev/workspace/loushang/src/loushang/coding/mode/rpc_mode.py)

## Transport Shape

`RpcMode` 以 JSONL 读写。

- client -> server: 一行一个 JSON object，必须有 `type`
- server -> client:
  - command response: `{"type":"response", ...}`
  - projected session event: `{"type":"...", ...}`

命令通常带可选 `id`，response 会原样带回。

## Rendered Tool Events

`RpcMode` 默认转发标准 projected session event。启动时传入 `render_tool_events=True`
或 CLI 使用 `--mode rpc --render-tool-events` 后，工具事件会附加展示 payload：

- `tool_execution_start.rendered_tool_call`
- `tool_execution_update.rendered_tool_result`
- `tool_execution_end.rendered_tool_result`

这只是 event stream 的 additive 字段，不改变 RPC command response 语义。
客户端可以基于 `contract_version` 判断 rendered payload 版本；如果字段不存在，应回退到原始
`tool_name` / `args` / `result` 展示。

详细合约见：

- [Loushang Coding Rendered Tool Events](loushang-coding-rendered-tool-events.md)

## Command Families

当前支持的命令可以按 4 类理解：

- run control:
  - `prompt`
  - `steer`
  - `follow_up`
  - `abort`
  - `bash`
  - `abort_bash`
  - `compact`
- session lifecycle:
  - `new_session`
  - `switch_session`
  - `fork`
  - `clone`
- state and discovery:
  - `get_state`
  - `get_messages`
  - `get_fork_messages`
  - `get_available_models`
  - `get_session_stats`
  - `get_last_assistant_text`
  - `get_commands`
  - `export_html`
- mutators:
  - `set_model`
  - `cycle_model`
  - `set_thinking_level`
  - `cycle_thinking_level`
  - `set_steering_mode`
  - `set_follow_up_mode`
  - `set_auto_retry`
  - `abort_retry`
  - `set_auto_compaction`
  - `set_session_name`
  - `set_active_tools`

## Canonical Session Snapshot

`get_state` 现在只返回 canonical session snapshot，不再混入 runtime/debug extras。

当前 top-level 字段是：

- `sessionId`
- `sessionName`
- `sessionFile`
- `model`
- `thinkingLevel`
- `isStreaming`
- `isCompacting`
- `steeringMode`
- `followUpMode`
- `autoCompactionEnabled`
- `messageCount`
- `pendingMessageCount`

字段语义：

- `isStreaming` 由当前 run state 投影而来，等价于“当前是否有活动 prompt 在跑”
- `messageCount` 表示当前 session context 中可见 message 数量
- `pendingMessageCount` 表示 steering + follow-up 队列总长度

当前有意 **不** 放进 `get_state` 的字段：

- `cwd`
- `run`
- `steering`
- `followUp`
- `activeToolNames`
- `isRetrying`
- `autoRetryEnabled`
- `modelSelection`

原因不是这些状态不存在，而是它们更像 runtime detail、queue internals 或 implementation-specific state，不适合继续作为 canonical session snapshot 暴露。

## Response Shape Policy

当前 RPC surface 采用下面这条规则：

- query 命令只返回查询结果
- mutator 命令尽量只返回最小成功确认
- lifecycle 命令只返回这次切换本身的最小结果
- `prompt` response 对齐 `reference CLI`：preflight 成功后立即返回 success，LLM streaming 和最终 `agent_end` 继续通过事件流输出；preflight 失败才返回 prompt error

已经收瘦到最小 ACK 的 mutator：

- `set_thinking_level`
- `set_steering_mode`
- `set_follow_up_mode`
- `set_auto_compaction`
- `set_auto_retry`
- `abort_retry`
- `set_session_name`

这类命令成功时只返回：

```json
{
  "id": "cmd-1",
  "type": "response",
  "command": "set_thinking_level",
  "success": true
}
```

lifecycle 命令当前的最小结果：

- `new_session` -> `{ "cancelled": bool }`
- `switch_session` -> `{ "cancelled": bool }`
- `fork` -> `{ "cancelled": bool, "text": string | null }`
- `clone` -> `{ "cancelled": bool }`

当前仍然保留 richer response 的命令：

- `set_model`
  - 返回当前选中的 serialized model
- `cycle_model`
  - 返回 `{ model, thinkingLevel, isScoped }`
- `set_active_tools`
  - 当前仍返回完整 serialized session state
  - 这是 `loushang` 自有 surface，暂未收瘦

## Model Projection

RPC `model` 字段不直接暴露 `ModelSelection`，而是优先投影真实的 `loushang.ai.Model`。

解析顺序：

1. 优先使用当前 agent state 上的真实 `Model`
2. 如果当前 agent state 上没有 model，则尝试用 `ModelSelection` 通过 `model_registry.build_model(...)` 解析
3. 如果仍然解析不到，则退回最小 `{ provider, id }`

同一套 serializer 现在被以下入口共用：

- `get_state.data.model`
- `set_model.data`
- `cycle_model.data.model`
- `get_available_models.data.models[]`

当前会在可用时投影这些字段：

- `provider`
- `id`
- `name`
- `api`
- `baseUrl`
- `input`
- `contextWindow`
- `maxTokens`
- `reasoning`
- `cost`
- `compat`

补充规则：

- `name` 缺失时回退成 `id`
- `cost` 只有所有价格组件都是已知数值时才输出；缺少 pricing 或任一组件未知时省略，显式 `0` 仍按 `0` 输出
- `compat` 只有非空时才输出

## Type Notes

当前代码里，`rpc_mode.py` 直接定义了最关键的 wire-shape `TypedDict`：

- `RpcModelCost`
- `RpcModel`
- `RpcSessionState`

它们不是完整命令协议总表，而是当前最稳定、最值得直接标明类型的 canonical payload：

- `get_state`
- `model` 相关响应

其余命令 response 仍以更轻的 dict construction 为主，后续如果 surface 继续稳定，再决定是否把更多 response family 提成独立协议类型。

## Commands Surface

RPC wire command `get_commands` 是当前命令发现的统一入口。它只承担“返回可用命令列表”，并且约定：

- `name` 为可执行命令名（无前导 `/`）
- `source` 为 `extension`、`prompt`、`skill` 三选一
- `sourceInfo` 使用 `path / source / scope / origin / baseDir` 结构

会话内命令条目统一使用 `AgentSession.list_commands()` 返回的 typed descriptor。该面按 `reference CLI` 风格由 session 动态聚合，不引入独立 command registry class：

- `name`: 命令名（无前导 `/`）
- `description`: 可选说明
- `source`: 命令来源类型（`extension`、`prompt`、`skill`）
- `source_info`: `CommandSourceInfo`

`RpcMode` 会把会话 descriptor 序列化为标准 `sourceInfo` 输出。
建议客户端基于 `sourceInfo.path` 做展示；内部不再保留 legacy dict / alias 输入兼容。

`sourceInfo` 由会话 descriptor 的 `source_info` 投影：

- `path`: 命令来源文件路径
- `source`: 一般为 `filesystem`
- `scope`: 通常是 `project`（或 `user`）
- `origin`: 一般为 `top-level`（或 `package`）
- `baseDir`: 命令类型的目录级基线

package provenance 不在 RPC 层兜底推断：prompt / skill 来自 loader descriptor，extension command 来自 `LoadedExtension`，RPC 仅序列化 session descriptor。

命令执行路径不在 RPC 新增 command verb，保持与 `reference CLI` 一致：主机仍通过常规 prompt 输入（如 `/deploy prod`）或 CLI 的 `--command` 触发会话命令执行。

`fork` 默认使用 `position="before"`，对齐 `reference CLI`：目标必须是 user message，响应 `text` 为选中的用户文本；调用方可传 `position="at"` 显式保留目标 entry。

## Method And Work Log Boundary

当前 RPC surface 不支持 `--method` / method plan execution，也不支持 `--work-log`
写入路径。原因不是 wire protocol 无法承载，而是 RPC 当前仍是 `loushang.coding`
内部 transitional mode surface；在 method plan/step projection、work event replay 与
长期 channel contract 收敛前，不把 method lifecycle 挂到 RPC 命令面上。

这一判断与 [ARD-006: TUI Method Integration Constraints](ARD-006-tui-method-integration-constraints.md)
保持一致：method-driven execution 当前只落在非交互 prompt/print/json path。

## Reference Implementation Alignment

当前这版 RPC surface 对齐 `reference CLI` 的核心思路是：

- `rpc mode` 仍是 mode adapter，不是另一套 runtime
- `rpc mode` 也不是长期 `loushang.channel` package layer
- `get_state` 只暴露 canonical session snapshot
- `cwd` 和 active tools 不是 canonical session state
- `model` 尽量围绕真实 AI model，而不是只围绕 selection object

当前保留的差异主要有两类：

- `loushang` 自有命令仍存在，例如 `set_active_tools`
- 部分命令的 response 还没有完全压成 `reference CLI` 风格的最小集合

## Related Tests

- [test_rpc_mode.py](/home/dev/workspace/loushang/tests/coding/test_rpc_mode.py)
