# Remote Agent Capability Boundary

> Status: **target direction**（尚未承诺具体 wire protocol 或远端实现）。
> 本文限定远程 Agent 能力如何进入 Harness；它不改变当前已实现的
> session-owned in-process multiagent 语义。

> Implementation note (2026-08-04): 本地 CLI subprocess 形态的 P0 已按
> [One-Shot Agent Invocation Tool Boundary](../agent-invocation-tool-boundary.md)
> 落地。它验证的是普通 admitted tool 的授权、非扩张工具集、取消和有界输出
> 边界，不代表远端 wire protocol、异步 job 或 collaboration backend 已实现。

## Decision

“远程”只描述部署位置，不决定交互生命周期。远端 Agent 可以是一次性
能力、可取消的异步任务，也可以是可持续通信的协作 actor。Loushang 不用
一个预先膨胀的通用 runtime/provider 接口覆盖三者，而按调用方真正需要的
交互语义暴露最小契约：

| 语义 | 最小操作 | Harness 形态 |
|---|---|---|
| 一次性能力 | `invoke(request) -> result` | 普通 admitted tool / capability；不进入 multiagent |
| 一次性异步任务 | `submit(request) -> RunRef`、`await_result`、`cancel` | job/delegation capability；只有任务引用，没有可寻址协作 actor |
| 持续协作 | `spawn`、`send`、`wait`、`list`、`interrupt`、`close` | multiagent collaboration port；存在可寻址、可 follow-up 的 agent |

远端一次性调用即使内部使用模型、工具和多个执行步骤，对本地 Agent 仍可
只是一个工具调用。只有调用方需要在结果产生前后继续寻址、发消息或控制该
实体时，它才获得 multiagent actor 语义。

## Client / Server Shape

该方案借用 LSP 的是 client/server 边界，而不是 LSP 的有状态生命周期：

```text
local Agent
  -> model-visible admitted tool
  -> tool handler / capability client
  -> stdio JSON-RPC | IPC | HTTP | gRPC | A2A adapter
  -> remote capability service
  -> typed result or activity projection
```

模型可见 tool schema 与 wire protocol 是两个契约。Tool handler 可在发出
远端请求前补充模型不应控制的字段，例如 `session_id`、`caller_ref`、
`request_id`、幂等键、协议版本和 scoped capability token。远端返回值也先
经过有界输出、artifact、错误和事件投影，再进入 Agent 上下文。

对于持续协作，当前 `MultiAgentToolPack` 仍是模型可见 façade。它依赖的
live collaboration seam 可以有两种装配：

```text
MultiAgentToolPack
  -> local collaboration adapter
       -> current SessionMultiAgentRuntime

MultiAgentToolPack
  -> remote collaboration client
       -> one remote collaboration service
```

第一版按 Session / capability profile 选择一个 collaboration backend，
不要求同一棵 agent 树逐 child 混合本进程、plugin 和远端 placement。这样
远端服务可以拥有自己的子树与 mailbox，本地只保留调用授权、tool 结果和
必要的事实投影。

## State Is Not Implied By Remoteness

以下概念不得合并：

```text
execution has progress/state
  != one server process owns mutable state
  != caller has an attachable Agent session
```

同步 `invoke` 可以完全无服务端状态。异步 job 的状态可以存放在队列、事件
存储或对象存储中，由任意服务实例通过 `RunRef` 查询；服务进程本身仍可无
状态。只有持续协作语义才要求稳定的逻辑 Agent identity，但它同样不要求
某个进程永久驻留。

因此不建立包含 `invoke / submit / attach / send / inspect / cancel / close`
的万能接口。每个契约只承诺自己实际支持的生命周期和失败语义。

## Ownership And Dependency Direction

Product / Host composition 决定准入哪种能力并注入 client。Harness tool
handler 只依赖对应的中立能力契约；client 只依赖 wire adapter，不调用
AppService，也不发现 Product：

```text
Product / Host composition
  -> admits capability and injects client

Harness tool handler
  -> AgentCapability | AgentJobService | AgentCollaborationPort
       -> protocol / transport adapter
```

- **AppService** 不位于远端 Agent tool call 的必经路径；只有 hosted
  Product 明确通过 AppService 暴露该能力时，AppService 才做应用级路由。
- **Channel** 只承载其明确接纳的 Work/runtime-view payload，不是远端
  Agent RPC 或 managed worker transport。
- **Work** 只在调用已经构成持久业务承诺时关联远端 execution/job；它不
  因为调用是远程的就成为必经层，也不让 worker 状态成为 Work truth。
- **A2A** 可作为外部独立 Agent 的 adapter；Loushang 管控服务可以先使用
  更小的 JSON-RPC/IPC 协议。两者都不改变模型可见工具语义。

权限不能随远程调用放大。Host/Product 向 client 下发的是 scoped capability，
远端 interaction、workspace 和 artifact 只能通过显式引用及本地授权投影
返回；远端服务不得绕过本地 Approval、sandbox 或 tenant 边界直接操纵 UI
和宿主资源。

## When An Execution Port Is Justified

仅仅增加一个远端 `invoke`、job client 或整棵树的 remote collaboration
backend，不足以证明需要 `AgentExecutionPort`。它只在 Host 必须透明地
统一下列需求时才有价值：

- 同一逻辑 agent 树逐 child 混合 in-process、subprocess/plugin 与 remote
  placement；
- 跨进程 attach/re-attach、lease、fencing、checkpoint、orphan detection
  和恢复；
- placement 改变时仍保持同一套本地控制、authority 和事件排序语义。

届时从当前 in-process 路径与至少一个真实的第二物理 backend 的共同事实中
提炼最小内部 port，而不是把远端协议、AppService 或 Work API 塞进该 port。
如果产品永远只需要 `invoke` 或按 Session 二选一的 collaboration backend，
这个 port 可以一直不存在。

## Delivery Order

1. 先用已实现的本地 CLI subprocess P0 验证普通 admitted capability 的输出、
   授权、非扩张工具集、超时和错误投影；接入远端时复用 tool 语义，但另行定义
   client/wire 适配器与远端身份、传输和 artifact 契约。
2. 任务确实会超出一次 tool call 生命周期时，再增加 `submit / await /
   cancel` 与 `RunRef`；不自动增加 mailbox 或 attach。
3. 只有需要 steering / follow-up 时，才增加 remote collaboration adapter，
   并复用 `spawn / send / wait / list / interrupt / close` 工具面。
4. 只有真实混合 placement 和恢复需求出现后，才评估统一 execution port。

每一步都必须证明上一层契约不足；“未来也许会远程”不是增加生命周期抽象
的充分理由。
