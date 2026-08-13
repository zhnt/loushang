# Loushang Multi-Agent Architecture

> Status: **implemented**（已实现，Phases 1A-1C / 2A-2B 全部完成）。
> 本目录的文档描述已实现的架构边界；与代码冲突时以代码
> 与已接受 ARD 为准（见
> [Architecture Artifact Model](../../../architecture-method/artifact-model.md)）。

`loushang.harness.multiagent` 提供子 agent 的派生、隔离、通信与生命
周期管控——是**纯技术态**能力：它不理解 stage / acceptance / artifact
等业务语义；业务编排（method / work）经产品装配层间接消费本能力。

## Reading Order

1. [System Context](system-context.md)
   黑盒边界：直接上游（产品装配层）、直接下游（harness prepared run）、
   逻辑 actor（parent agent、user/host）；明确不在边界上的子系统。
2. [Candidate Components](candidate-components.md)
   候选职责及其复用依据；实现已压缩到五个内核文件和一个 session
   adapter，不按候选职责逐一造组件。
3. [Technical Runtime, Scheduling, And Tools](technical-runtime-and-tools.md)
   最新的实施收敛：技术态与调度态的分层、四个内核模块、workspace
   lease、模型可调用协作 tools 与长期 Work execution 的接缝。
4. [Remote Agent Capability Boundary](remote-agent-capability-boundary.md)
   远程 Agent 的渐进契约：一次性 capability、异步 job、持续 collaboration；
   明确何时不需要、何时才需要统一 execution port。
5. [Workspace Collaboration And Git Handoff](workspace-collaboration-and-git-handoff.md)
   workspace scope 与 Git checkout 的正交模型；共享写入、detached
   artifact 交付以及延后的 branch-backed workspace。
6. [Temporary Implementation Plan](implementation-plan.md)
   分阶段的执行检查表；实施稳定后将删除或转为正式开发记录。
7. Accepted-direction ARDs:
   - [ARD-001: Harness Ownership](ARD-001-harness-ownership.md) —
     为什么是 `loushang.harness.multiagent` 而非顶层包或 agent 内核。
   - [ARD-002: Async-Only Execution And Recovery](ARD-002-async-execution-and-recovery.md) —
     一期全异步、消息驱动恢复、open/closed 区分。
8. Component boundaries（按依赖序阅读）:
   - [Tool Surface](tool-surface-boundary.md) — 模型可见的六个通用协作
     tools 与提示纪律；一期最小闭环仍以 spawn / send / wait 为核心。
   - [Control](control-boundary.md) — spawn 流水线与消息路由的编排。
   - [Registry](registry-boundary.md) — AgentPath 寻址、两阶段预留、
     树拓扑。
   - [Run Handle](run-handle-boundary.md) — 子 agent 运行载体：多轮
     驱动、取消双模式、事件转接。
   - [Agent Input Facade](agent-input-facade-boundary.md) — 通知合成
     与 wait 原语（用户队列复用 HostInputQueue，系统通知走 Agent
     mailbox）。
   - [Context Fork](context-fork-boundary.md) — 隔离矩阵、fork 档位、
     历史过滤、审批冒泡装配、可参数化 `fork_history()`。
   - [Limits And Projection](limits-and-projection-boundary.md) — 并发
     闸门、depth 上限、驻留回收（二期）、生命周期状态机与事实。

## Core Invariants

所有组件与注入缝必须遵守的不变式（产品/OEM 可定制策略，不可改写
这些语义）：

1. **不写第二套 agent loop**：子 agent 本体是 `run_agent(AgentRunSpec)`
   的 prepared run 重入。
2. **默认隔离，显式共享**：子上下文默认全隔离；任务注册穿透 root；
   审批冒泡到 root 交互出口。
3. **全异步 + 通知**：无同步 spawn；结果经完成通知到达；wait 等自己
   input 的 activity，不轮询子状态。
4. **先状态后收尾**：有界 workspace snapshot/capture 属于终态 payload
   物化；无论物化成功、失败或超时，随后都必须提交终态事实。清理/汇总仍
   在终态之后，失败不反转状态。
5. **open / closed 区分**：close 后不可寻址；open 的 idle/终态 agent
   可被消息唤醒。
6. **fork 的确定性**：同一 transcript watermark、档位与过滤规则产生
   相同的语义历史；已渲染字节前缀可用时用于 prompt cache 优化，无法
   提供时不阻塞正确的 fork。
7. **机制写死、策略注入**：上限值、过滤规则、通知模板、纪律文本等
   是产品/OEM 注入缝；组件语义不变式不是。

## Relationship To Other Subsystems

- `loushang.harness`：本目录归属其中；复用其 `run_agent`、
  `HostInputQueue`、Agent mailbox、`ApprovalRequest`、transcript（fork 历史源）、
  host lifecycle 编排。
- `loushang.agent`：提供 agent loop 与稳定原语；multiagent 不扩大其
  内核语义。
- `loushang.method` / `loushang.work`：业务态编排层；method 角色可
  编译为 agent 类型（装配层职责），work 可消费 agent 树事实做业务
  投影——multiagent 不依赖它们。
- `loushang.channel`：承载其明确接纳的 Work/runtime-view 订阅与投影；
  multiagent 的事实经装配层投影后才可能进入 Channel。远端 Agent RPC、
  job 和 managed-worker transport 不属于 Channel。
- 产品装配层（coding / design / …）：注入类型注册表、策略参数、
  事件消费者、审批出口；决定工具面暴露范围。

## Current Executable Slice

Coding 已接入显式的非持久 child factory 和 Harness 通用协作 tools。
即时、非持久的 CLI recipe 可直接手工验证：

```console
uv run loushang ma recipes
uv run loushang ma run parallel-review \
  --provider scripted --prompt "Review this design" --count 3
uv run loushang ma run debate \
  --provider scripted --prompt "Should we adopt this architecture?"
```

`scripted` 只替换模型流，仍走真实 Coding child session、Agent loop、
HostInputQueue、Agent mailbox、RunHandle 和 session release。真实模型改用
`--model provider/model`；`--agent ROLE=provider/model` 可为辩论角色
分别选择模型。recipe root 与 children 均不持久化为普通 Resume
session。

普通 Coding session 还可由根模型按准入类型调用 `spawn_agent`。
`explorer` 可使用 Coding 现有的 `bash`、本地文件搜索和读取工具执行
Git 检查、Python 分析以及策略允许的 curl 获取，但不获得专用的 `write`
或 `edit`；Bash 仍服从 Product 配置的策略与审批链。
`implementation_worker` 与 `test_runner` 会进入系统分配的隔离 Git
detached worktree；无改动的 worktree 自动清理，有改动的 worktree 保留，
并通过完成通知返回不透明的 `workspace_ref`/`artifact_refs`。Coding 新
路径不再生成临时 branch 或填充兼容字段 `change_set_ref`；apply/discard
由显式 Coding CLI 确认。
对于明确要求直接修改当前脏工作区的小型任务，Coding 另提供
`shared_implementation_worker`：它使用父 session 已解析的同一 `cwd`、
同一 Git worktree 和 branch，不申请 lease，也不返回隔离
`change_set_ref`。该角色允许在 Product 配置的 session 并发额度内派生
多个，但父 Agent 必须为每个 worker 明确分配互不重叠的文件或职责范围；
worker 必须保留无关未提交修改、适应其他 worker 的并发变化且不得回退
他人修改。父 Agent 在 worker 运行期间也不得修改其负责文件；同一文件或
高度耦合的写入仍需串行。commit、merge 和 publish 仍由父 Coding
session 控制。这里采用与 Codex 相同的协作契约，而不是通用文件锁；
边界不清或可能重叠的任务应使用隔离 `implementation_worker`。

`/agents` 是 `loushang.harnesstui.multiagent` 提供的跨产品命令和实时、
只读全屏 Agent Tree。Coding 只是第一个为它绑定当前 session
`multiagent_runtime` 的 Product；PPT、Design 和其他 Product 应复用同一
命令与页面，并注入各自的 live records 和 facts。

多 agent 的 TUI 问题应按工具、通信、渲染三层回放，避免只靠复制终端
文本推断：

```console
uv run python scripts/run_tui_playback.py \
  multiagent-tools multiagent-messaging \
  multiagent-followup multiagent-nested-tree multiagent-lifecycle \
  multiagent-parallel-review multiagent-debate \
  multiagent-shared-workspace multiagent-isolated-artifact \
  multiagent-shared-parallel-writers \
  multiagent-render \
  --artifacts /tmp/loushang-multiagent-playback \
  --include-frames
```

`*-events.jsonl` 记录 spawn、终态事实、完成通知、wait activity 和输入
投影；`*-render.jsonl` 记录每一帧的终端操作分类与恢复重绘原因；
`*-screen.txt` 保存最终可见屏幕。排查顺序必须先确认工具注册表与通知
恰好一次，再判断输入投影，最后检查终端重绘。

新增拓扑回放分别覆盖：同一 child 的多轮 follow-up、嵌套
root→coordinator→worker 的直接父通知、interrupt/close 后的名称复用与
incarnation 变化、parallel-review 的 fan-out/fan-in，以及
proposer→critic→judge 的串行证据传递；`multiagent-shared-workspace`
还验证 child 使用父 session 的精确 `cwd` 直接修改同一工作区，而不生成
lease 或隔离变更引用；`multiagent-shared-parallel-writers` 验证两个
共享 worker 同时运行、使用同一 `cwd`，并按显式所有权分别修改不同文件。
`multiagent-isolated-artifact` 走真实 Git detached worktree，覆盖终态
artifact 引用、diff review、显式批准 apply 与 discard。

## Evolution Path

1. **技术一期**：session-owned 控制树、异步协作 tools、消息驱动唤醒、
   Coding Git workspace lease、事实驱动的跨产品 TUI；无 LRU 回收。
2. **远端能力（按需独立演进）**：先用普通 tool/capability 支持一次性
   `invoke`；执行确实越过单次调用生命周期时才增加 job；需要 steering /
   follow-up 时才增加 remote collaboration backend。
3. **持久调度**：仅对已接受的 durable Work，把 Work-owned 业务履约与
   Host-owned execution backend 显式关联，增加 checkpoint、orphan recovery
   与 attach/cancel。
4. **后续**：LRU 驻留回收、确有混合 placement 后提炼的 execution port、
   Method 编译的 stage 级派生、验收和工作产品调度；Channel 不作为远端
   capability、job 或受管 worker 的 transport。
