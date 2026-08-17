# `runtime-state`

## Scope

- 运行态状态与上下文对象

## Objects

### `AgentSessionState`

归属组件：

- `session`

角色：

- 单个 session 的内存态运行状态对象

承担语义：

- 当前运行状态
- 当前高层控制状态
- 当前 session 内部的可变事实状态

### `RunState`

归属组件：

- `loushang.harness.runtime.types`

角色：

- 一次 run / turn 的瞬时状态对象

承担语义：

- 当前 run 是否在执行
- 当前 run 的阶段
- 当前 run 的中断、失败、完成状态

备注：

- Coding 公共路径 re-export 同一个 Harness-owned record
- `AgentSessionState` 仍是 Coding 产品投影

### `SessionContext`

归属组件：

- `session`
- `store`

角色：

- 从 `SessionEntry[]` 投影出的运行上下文对象

承担语义：

- `messages`
- `thinking_level`
- `model`

## Reference Implementation Alignment

- `SessionContext` 直接对齐 `reference coding agent`
- `AgentSessionState` 与 `RunState` 对齐的是 `reference CLI` 中真实存在、但未必被明确独立命名导出的状态语义

## Notes

- `AgentSessionRuntime` 与 `AgentSession` 属于服务对象，已不再放在 data objects 体系中
