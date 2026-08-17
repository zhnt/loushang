# Loushang Coding JSON Mode Design

## Scope

本文档定义 `loushang-coding` 中 `json mode` 的设计口径。

本文中的 `json mode` 指用户可见的 JSON event stream 运行形态，
不等于一个独立的 `JsonMode` service object。

本文档主要回答：

- `json mode` 在组件边界上应该如何定位
- `json mode` 应复用哪些已有核心数据对象
- 哪些 JSON line 结构属于边界投影，而不是新的核心对象

## Design Goal

`json mode` 的目标不是引入新的 runtime 模型，而是把现有 `session` 运行过程稳定地投影为 JSON Lines 输出。

因此，`json mode` 应被视为：

- 边界投影层
- `PrintMode` 的 JSON output projection
- 事件流输出模式

而不应被视为：

- 新的 session core
- 新的 store 模型
- 新的核心数据对象体系

## Component Position

`json mode` 在组件关系上应表达为：

```text
session
  -> event / message
  -> mode/print(output_mode="json")
```

职责划分建议如下：

- `session`
  - 产出标准 `AgentSessionEvent`

- `event`
  - 定义事件对象族
  - 提供事件到 JSON-ready payload 的序列化

- `message`
  - 定义消息对象族
  - 提供消息到 JSON-ready payload 的序列化

- `mode/print`（`output_mode="json"`）
  - 负责输出顺序
  - 负责 JSON Lines 写出
  - 不定义新的业务对象模型

- `store`
  - 只提供 session header / context / transcript 的持久化来源
  - 不负责 JSON mode 输出流

## Data Model Rule

`json mode` 应复用已有核心数据对象：

- `SessionHeader`
- `AgentSessionEvent`
- `AgentMessage` family
- `AssistantMessageEvent`

当前不建议为了 `json mode` 再单独定义新的核心数据对象，例如：

- `JsonSessionHeader`
- `JsonEventRecord`
- `JsonStreamRecord`

这些如果未来需要，也应被视为：

- boundary payload
- protocol projection

而不是新的 core data objects。

当前也不建议为此单独定义新的 adapter object，例如：

- `JsonMode`

## Output Shape

推荐的输出形态与 `reference CLI` 一致：

1. 第一行输出 session header
2. 后续逐行输出 session event

示意如下：

```json
{"type":"session","version":3,"id":"uuid","timestamp":"...","cwd":"/path"}
{"type":"agent_start"}
{"type":"turn_start"}
{"type":"message_start","message":{...}}
{"type":"message_update","message":{...},"assistant_message_event":{...}}
{"type":"message_end","message":{...}}
{"type":"turn_end","message":{...},"toolResults":[]}
{"type":"agent_end","messages":[...]}
```

## Session Header

首行建议直接由 `SessionHeader` 投影得到。

推荐字段：

- `type`
- `version`
- `id`
- `timestamp`
- `cwd`
- `parentSession`（如存在）

也就是说，header line 是：

- `SessionHeader` 的 boundary projection

而不是新的 header core object。

## Event Stream

后续各行建议直接由：

- `AgentSessionEvent`

通过：

- `serialize_session_event(...)`

投影得到。

当前应覆盖的事件包括：

- `agent_start`
- `agent_end`
- `turn_start`
- `turn_end`
- `message_start`
- `message_update`
- `message_end`
- `tool_execution_start`
- `tool_execution_update`
- `tool_execution_end`
- `queue_update`
- `compaction_start`
- `compaction_end`
- `auto_retry_start`
- `auto_retry_end`

## Rendered Tool Events

`json mode` 可以通过 `render_tool_events=True` 或 CLI 的 `--render-tool-events`
把工具事件附加为可展示 payload：

- `tool_execution_start` 附加 `rendered_tool_call`
- `tool_execution_update` / `tool_execution_end` 附加 `rendered_tool_result`

这些字段属于 JSON boundary projection，不是新的核心 event object。
它们复用 `ToolDefinition.render_call/render_result`，由 event projection 统一补齐
`contract_version`、`status`、`duration_ms`、`artifacts` 等稳定边界字段。

详细合约见：

- [Loushang Coding Rendered Tool Events](loushang-coding-rendered-tool-events.md)

## Message Serialization

事件内部嵌套的消息对象，应继续复用：

- base AI message family
- coding-specific custom message family

特别包括：

- `UserMessage`
- `AssistantMessage`
- `ToolResultMessage`
- `BashExecutionMessage`
- `CustomMessage`
- `BranchSummaryMessage`
- `CompactionSummaryMessage`

这些都属于已有消息对象的 JSON 投影，不属于 `json mode` 新引入的数据模型。

## Event Envelope

当前不要求 `json mode` 先引入统一 `EventEnvelope`。

原因：

- 现有 `AgentSessionEvent` 已足够支撑 JSON event stream
- 过早引入 envelope 会把 `json mode` 设计提前耦合到未来 `loushang.channel` 协议

但可保留这个判断：

- 如果后续引入 package-level `loushang.channel`
- 或希望统一 `json/web/external host` 边界协议

则：

- `EventEnvelope` 可以成为 future boundary object

## Design Rule

对 `json mode`，当前建议坚持以下规则：

1. 不新增新的 runtime core object
2. 不新增新的 store object
3. 尽量复用 `SessionHeader + AgentSessionEvent + AgentMessage family`
4. JSON line 视为 boundary projection，而不是新的核心数据对象

## Related Docs

- [Loushang Coding Component Interfaces](loushang-coding-component-interfaces.md)
- [Loushang Coding Core Data Objects](loushang-coding-core-data-objects.md)
- [Core Data Object Notes](core-data-objects/README.md)
- [event-family.md](core-data-objects/event-family.md)
- [message-family.md](core-data-objects/message-family.md)
- [mode.md](component-interfaces/mode.md)
- [Loushang Coding Rendered Tool Events](loushang-coding-rendered-tool-events.md)
