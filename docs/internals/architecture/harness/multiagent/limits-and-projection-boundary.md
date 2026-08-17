# Multi-Agent Limits And Lifecycle Projection Boundary

> Status: **implemented**（已实现，与 `ControlLimits` / `AgentFact` 代码一致）。本文定义
> `loushang.harness.multiagent` 的资源准入（Limits）与生命周期事实投影
> （LifecycleProjection）边界。

## Scope

两个小组件合写一文：Limits 决定"**能不能生**"（准入），
LifecycleProjection 决定"**现在是什么状态、发生了什么**"（事实）。
它们都不做协调，分别被 MultiAgentControl 调用与触发。

本文定义：

- 并发闸门、depth 上限、驻留回收（二期）的准入语义
- 生命周期状态机与推导规则
- 技术事实的形状与发射纪律

本文不定义：

- 准入失败后的调用方行为（属 Control / ToolSurfaceAdapter）
- 事实的消费者形态（属装配层）
- 回收的状态外置编解码（属 SnapshotCodec 缝 / RunHandle）

## Limits

### Concurrency Gate

一期名额模型（简化：避免 per-turn 计数的时序问题）：

- **名额 = open agent 数**，按 root run 树计数（整棵树共享上限，不是每个
  agent 一份）。
- **获取：spawn 预留时**（registry.reserve 成功即占名额）；
  **释放：close 完成时**（唯一释放点）。
- 持有期内活跃/空闲切换不计数：已 spawn 的 agent 在 idle /
  终态后仍占名额，唤醒新一轮不再检查名额（名额在 spawn 时已计入）。
  agent 数被上限封住，并发 turn 数被同一上限封住，一期不需
  per-turn 闸门。
- 超限 → `AgentLimitReached(max)` 结构化错误（**正常工具结果**，模型
  可据此改用 wait/串行策略）。

二期演进：若引入驻留制（见 Residency），名额语义升级为
"已加载 agent 数（LRU 回收）、registry 不设限"——与 Codex v2 的演进一致，
届时 close 释放名额、回收释放加载位。

### Depth Limit

- spawn depth = 父 depth + 1（root 为 0）；超过 `max_spawn_depth`
  拒绝派生。
- 这是**结构性递归防护的兜底**；首要防线是类型工具裁剪（类型不含
  spawn 工具即不可再派生，见 context-fork 隔离矩阵）。

### Residency（二期，一期不实现）

- 已完成 agent 保持 open 占名额直至 close；容量压力下
  按 LRU 回收 **idle 终态且无待收消息** 的 agent。
- 回收前状态外置（经 `SnapshotCodec`），父子边保持 open；回收后
  send_message 透明重载（ARD-002）。
- 回收候选判定、idle 阈值、保护规则（如"pinned" agent 不回收）均为
  可注入策略。

### Policy Parameters

全部由装配层注入，harness 只提供保守默认：

| 参数 | 默认 | 说明 |
|---|---|---|
| `max_open_agents` | 保守小值（如 6，含 root） | 树级 open agent 上限；终态 child 在显式 close 前仍计入 |
| `max_spawn_depth` | 保守小值（如 3） | 递归防护兜底 |
| `idle_eviction_timeout` | 二期 | 驻留超时 |
| `wait_timeouts` | min 10s / max 1h / default 30s | wait 边界（Codex v2 同量级） |

## LifecycleProjection

### State Machine

```text
pending ──首轮 run 开始──► running ──终态──► completed | failed
                              │
                              └─interrupt──► interrupted ──deliver──► running
任何 open 态 ──close──► closed
```

- `pending`：已注册未开跑（spawn 流水线内）；`running`：有活跃轮；
  `completed` / `failed`：终态（保持 open 可唤醒，ARD-002）；
  `interrupted`：被中断（保持 open）；`closed`：已关闭（不可寻址）。
- `maximum_children` 和 `max_open_agents` 限制的是 **open residency**，
  不是同时运行的 turn 数。一次性 fan-out 在汇总完成后必须显式
  `close_agent`；需要连续上下文时则保留 child 并用 `send_message`
  开始下一轮。失败的 `spawn_agent` 不创建 child，调用者不得等待或
  关闭猜测出来的路径。
- 推导来源：RunHandle 转接的 run 事件（turn_start → running；
  run result → completed/failed；interrupt → interrupted；close →
  closed）。projection 不监听模型内容，只映射 run 生命周期。

### Technical Facts

```text
AgentFact
  kind: spawned | status_changed | terminal | closed
  agent_path, parent_path, agent_type
  status: SubagentStatus
  terminal_payload: { final_message, usage, duration_ms, tool_uses } | None
  at: Timestamp
  metadata: Mapping                  # 产品经 TerminalFactMapper 追加
```

发射纪律：

1. **先状态后收尾**：registry 状态回写与 `await_terminal` 解阻塞先于
   事实发射；发射失败不反转状态（cc gh-20236）。
2. **有序**：同一 agent 的事实按其发生顺序；不同 agent 间不保证全局
   序（消费者按 path 分组）。
3. **技术事实不是业务产物**：terminal 的 final_message 是否构成业务
   "产物/验收依据"由装配层 / work 判定；projection 不解释。
4. **registry ↔ projection 分工**：registry 是控制面视图（协调以它为
   准），projection 是事实视图（展示/审计/work 投影以它为准）。

### Consumer Interface

```text
subscribe(consumer: AgentFactConsumer)
  # 装配层注册：UI 面板、审计日志、work 投影适配器
  # 消费者收到的是不可变事实快照；不回调进 multiagent
```

## Product Injection Seams

| 缝 | 注入内容 | 默认 |
|---|---|---|
| `LimitPolicy` | 上限值与超限行为（拒绝/排队等待） | 拒绝（结构化错误） |
| `EvictionPolicy` | 二期：回收候选、阈值、保护规则 | LRU + idle 终态 |
| `TerminalFactMapper` | 终态事实的产品附加字段（经 metadata，不改核心 shape） | 标准终态（status/终态消息/usage/时长/tool 计数） |
| `FactSinks` | 额外事实消费者（OEM 审计等） | 无 |

## Ownership And Boundaries

Limits 拥有：名额计数（spawn 获取、close 释放）、depth 判定、回收决策（二期执行由
Control/RunHandle 完成）。不拥有：spawn 协调、状态存储。

LifecycleProjection 拥有：状态机推导、事实 shape 与发射（经 `TerminalFactMapper`
丰富终态事实；丰富后的事实供 AgentInputFacade 合成完成通知）。不拥有：
registry 的协调视图、消费者的处理、业务解释。

## Failure Semantics

- 超限/超深：结构化错误返回调用方，无预留残留。
- 回收冲突（回收与 deliver 并发）：deliver 优先——回收前检查
  "无待收消息"，deliver 到达即取消本次回收。
- 事实发射失败（消费者异常）：记录诊断、跳过该消费者，不影响
  状态机与其他消费者。
