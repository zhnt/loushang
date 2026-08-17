# Multi-Agent Tool Surface Boundary

> Status: **implemented**（已实现，与 `MultiAgentToolPack` 代码一致）。
> 六件套工具（spawn_agent / send_message / wait_agent / list_agents /
> interrupt_agent / close_agent）已完整交付；参数、结果与提示纪律
> 与当前实现一致。

## Scope

`loushang.harness.tools.multiagent.MultiAgentToolPack` 是公共
multiagent 内核之外唯一依赖 agent 工具框架的位置：它把
Control / AgentInputFacade / Registry 的能力封装为模型可调用工具，
并承载提示纪律（briefing 要求、通知纪律）这一模型行为的关键杠杆。

这套工具面表达的是“可持续寻址的协作 actor”，不是所有由 Agent 实现的
远端能力。一次性远端 Agent 应注册为普通 `invoke -> result` tool；长时但
不可交互的调用应使用最小 job contract。只有需要 steering、follow-up、
等待 activity 或显式关闭时，才使用本工具面。远程与本地的边界决策见
[Remote Agent Capability Boundary](remote-agent-capability-boundary.md)。

本文定义：

- 六件套工具的参数面与结果 shape
- 参数校验与错误语义
- 提示纪律资源（可替换）
- 产品裁剪（暴露子集、类型白名单）

本文不定义：

- 工具的执行机制（属 Control 等各组件）
- 类型的业务内容（属装配层注入的 AgentTypeRecord）
- 工具在 UI 中的呈现（属产品 UI）

## Tool Set

### `spawn_agent`

派生子 agent 处理一个有界子任务。

```json
{
  "name": "research_auth",             // 必填；小写字母/数字/下划线/连字符
  "prompt": "调查 src/auth/ 的 token 刷新逻辑，找出竞态。不写代码，200 字内报告。",
                                       // 必填；完整简报（fresh spawn 零上下文）
  "agent_type": "explorer"             // 必填；必须是产品准入类型
}
```

结果（成功）：

```json
{
  "path": "/root/research_auth",
  "incarnation": 1,
  "agent_type": "explorer",
  "status": "running",
  "round_id": 1,
  "workspace_ref": null,
  "change_set_ref": null
}
```

spawn 立即返回（ARD-002 全异步）；子 agent 的结果**不在此返回**，
经完成通知到达。

### `send_message`

给 open agent 发消息。

```json
{
  "target": "research_auth",           // 必填；相对名或全路径
  "message": "补充：也看一下 refresh 的 backoff 策略。",
  "kind": "follow_up"                  // 可选；follow_up（默认，下轮消费）
                                       // | steering（注入当前 turn）
}
```

结果：

```json
{ "status": "delivered", "triggered_new_round": true }
```

- 目标 idle/终态（open）：`triggered_new_round=true`，唤醒新一轮 run。
- 目标 running：入队，`triggered_new_round=false`。
- 目标 closed：错误 `agent_not_addressable`。

### `wait_agent`

等待自己 input 的 activity（ARD-002：不轮询子状态）。

```json
{ "timeout_ms": 30000 }                // 可选；边界由策略注入
```

结果：

```json
{
  "status": "activity",                // activity | steered | timed_out
  "senders": ["/root/research_auth"],  // 哪些 sender 有更新（摘要）
  "timed_out": false
}
```

只给摘要不给内容——通知全文在后续 turn 作为 user-role 消息出现。

## Validation And Error Semantics

- 所有参数严格校验（name 形态、target 解析、类型
  白名单）；校验失败返回**结构化工具错误**，不抛异常。
- 错误结果带稳定 `code`，供模型与测试依赖；消息文本人可读，
  不作为程序契约。底层组件的错误经工具面统一映射：

| code | 来源 | 语义 |
|---|---|---|
| `invalid_agent_type` | Registry/Control | 未知类型或不在白名单 |
| `agent_limit_reached` | Limits | 并发名额已满 |
| `agent_depth_exceeded` | Limits | 超过 max_spawn_depth |
| `agent_name_conflict` | Registry | 同父下同名 open agent |
| `agent_reference_ambiguous` | Registry | 相对名歧义（附候选全路径） |
| `agent_not_found` | Registry | 目标不存在 |
| `agent_not_addressable` | AgentInputFacade | 目标已 close，不可投递 |
| `invalid_fork_option` | ContextFactory | fork 档位非法或与 model 覆盖冲突 |
| `spawn_rejected` | Control | 其他 spawn 拒绝（如类型工具为空） |

## Prompt Discipline Resources

工具描述与纪律文本是**可替换资源**（OEM 可覆盖），核心内容：

1. **何时 spawn**：只为具体、有界、可独立运行的子任务 spawn；简单
   任务直接做。
2. **简报纪律**（cc 对齐）："像简报刚进门的同事"——fresh spawn 零
   上下文，必须含目标、已知约束、判定所需背景；"never delegate
   understanding"（不写"基于你的发现修 bug"）；要短报告就明说。
3. **fork 纪律**：`fork` 仅当需要子 agent 继承对话背景；fork 档
   不可改 model（cache）；fork 后**不要窥探**（不读子 agent 的中间
   输出）也**不要编造**（通知到达前不知道结果）。
4. **等待纪律**：spawn 后用 wait_agent 等通知；通知到达前可以给
   用户状态（"还在查"），不给猜测的结果。
5. **并行纪律**：并行 spawn 时告知子 agent 环境中有其他 agent，
   不要回滚他人工作；跑测试类子 agent 的类型不得含 spawn 工具
   （防递归——结构性防线在类型裁剪，提示只是补强）。
6. **结果归属**：子 agent 的终态消息用户看不到；由父 agent 总结
   给用户。子 agent 的输出一般应当信任。

## Product Customization

产品装配层对工具面的裁剪（不改变工具语义）：

| 裁剪 | 机制 |
|---|---|
| 暴露子集 | 如只暴露 spawn + wait，不暴露 send_message |
| 类型白名单 | spawn 的 `agent_type` 限定子集（如 method 场景只能派生图纸内角色） |
| 默认类型 | 缺省 `agent_type` 的产品默认 |
| 超时边界 | wait 的 min/max/default（经 MultiAgentPolicy） |
| 纪律文本 | 替换提示资源（OEM 本地化、行业纪律） |

工具面的 schema 变化会击穿 prompt cache，因此：类型列表**不嵌入**
工具描述（cc 的 agent_listing_delta 教训），类型清单经系统消息/
附件注入，工具描述保持静态。

## Ownership And Boundaries

拥有：

- 三件套工具的 schema、参数校验、结果 shape
- 结构化错误码
- 提示纪律资源（默认文本）
- 产品裁剪的接入点

不拥有：

- spawn / send / wait 的执行（Control / AgentInputFacade / RunHandle）
- 类型注册表内容（装配层注入）
- 工具 UI 呈现（产品 UI）
- 审批冒泡（ContextFactory 装配）

## Failure Semantics

- 校验/准入/寻址失败：结构化工具错误（正常结果），无副作用。
- spawn 后首轮启动失败：spawn 已返回（异步），子 agent 以 failed
  终态呈现并经通知到达——不反转为 spawn 工具错误。
- wait 期间被 steer：返回 `steered`，模型转处理用户输入。
