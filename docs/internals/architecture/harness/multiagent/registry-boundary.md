# Multi-Agent Registry Boundary

> Status: **implemented**（已实现，与 `AgentRegistry` 代码一致）。本文定义
> `loushang.harness.multiagent` 的寻址与拓扑边界：`AgentPath`、两阶段
> 预留、agent 树拓扑。

## Scope

`AgentRegistry` 回答两个问题：**这个 agent 叫什么**（寻址）与**谁和
谁是父子**（拓扑）。它是纯数据组件，不含执行与协调逻辑。

本文定义：

- `AgentPath` 的形态与解析规则
- 两阶段预留（reserve / commit / 回滚）
- 树拓扑的维护与查询
- path ↔ RunHandle 的逻辑映射

本文不定义：

- spawn 的协调顺序（属 MultiAgentControl）
- RunHandle 的执行语义（属 run-handle-boundary）
- 状态机推导（属 LifecycleProjection；registry 只存控制面写入的状态）

## AgentPath

层级化寻址，形如：

```text
/root
/root/research
/root/research/auth
```

规则：

- root agent 固定为 `/root`；每次 spawn 在调用者的 path 下追加一段
  （`task_name`）形成子 path。深度即 path 段数 - 1。
- `task_name` 约束：小写字母、数字、下划线/连字符，非空、不含
  `/`——在 ToolSurfaceAdapter 参数校验时强制。
- **同名冲突**：同一父 path 下不允许两个 open agent 同名（预留阶段
  拦截）；已 close 的名字可在预留时复用（close 释放名字）。
- path 是**逻辑寻址**，不是物理执行标识：path ↔ RunHandle 的映射由
  registry 持有，RunHandle 重建（二期回收恢复）后 path 不变、映射
  更新。

### Resolution

工具面与路由收到目标引用时的解析规则：

1. **全路径**（以 `/` 开头）：直接匹配。
2. **相对名**：相对调用者的 agent_path 解析——先查调用者的直接子
   agent，再查调用者子树内同名唯一者；歧义（子树内多个同名）返回
   结构化错误，要求用全路径。
3. 解析失败（未找到 / 歧义）返回结构化错误，不猜测。

参照 Codex v2 的语义："You are able to refer to this agent as `task_3`
or `/root/task1/task_3` interchangeably. However an agent
`/root/task2/task_3` would only be able to communicate with this agent
via its canonical name"——相对名只在调用者自己的子树内有意义。

## Two-Phase Reservation

spawn 的寻址安全依赖两阶段预留：

```text
reservation = registry.reserve(agent_path, metadata)
    # 校验：父存在且 open、path 未占用、名字合法
    # 占用该 path（pending 态），并发同名 reserve 失败
    ...
reservation.commit(handle)   # spawn 流水线步骤 6：绑定 RunHandle
# 或
reservation.rollback()       # 窗口内任一步失败：释放 path，无残留
```

- `reserve` 返回的 reservation 对象是唯一提交/回滚凭证；超期未
  commit 的 reservation 由 Control 在 spawn 流水线退出时统一回滚
  （RAII 语义，不依赖调用方记得回滚）。
- **pending 可见性**：pending 条目对 reserve 冲突检测可见（防并发
  同名），对 `list_agents` / `subtree` 等查询不可见——防止模型在未就绪
  的半注册态下对 agent 发消息。
- `commit` 后条目转为 open；此后状态变更（running / 终态 /
  interrupted / closed）由 Control 经 LifecycleProjection 推导结果
  回写。
- 参照：Codex `reserve_spawn_slot` / `SpawnReservation.commit`。

## Tree Topology

registry 维护 parent→child 边，支持：

- `children(path)`：直接子 agent（按 path 排序，确定性输出）。
- `subtree(path)`：深度优先枚举全部后代（close 递归用）。
- `list(prefix?)`：按前缀过滤列出条目（list_agents 工具的基础）。
- `parent(path)`：父引用（完成通知路由、审批冒泡链用）。

拓扑事实（spawn 边、close）同时经 LifecycleProjection 发射给装配层
消费者——registry 是**控制面视图**，projection 是**事实视图**；两者
以 registry 为准做协调，以 projection 为准做展示/审计。

二期持久化：父子边与元数据外置（供回收恢复重建 registry），一期
内存态；接口一期定型，持久化是 SnapshotCodec 缝的实现细节。

## Entry Shape

```text
RegistryEntry
  agent_path: AgentPath        # 逻辑寻址（主键）
  parent_path: AgentPath       # 父引用（root 的父是自己）
  agent_type: str              # 类型名（AgentTypeRecord 的键）
  status: SubagentStatus       # pending | open 各态 | closed（控制面回写）
  handle: RunHandle | None     # 物理执行映射（None = pending 或已回收）
  created_at: Timestamp
  snapshot_ref: str | None     # 二期：已回收条目的状态外置引用
```

## Product Injection Seams

| 缝 | 注入内容 | 默认 |
|---|---|---|
| `NamingPolicy` | task_name 合法性与保留名 | 小写字母/数字/下划线/连字符 |
| `ResolutionPolicy` | 相对名解析顺序与歧义处理 | 先直接子、后子树唯一者 |
| `RegistryStore` | 二期：条目与拓扑的持久化 | 一期内存 |

## Ownership And Boundaries

拥有：

- AgentPath 形态、解析、同名冲突拦截
- 两阶段预留与回滚
- 树拓扑与查询
- path ↔ handle 映射

不拥有：

- spawn 时机与顺序（Control）
- handle 的执行（RunHandle）
- 状态的推导（LifecycleProjection 推导后由 Control 回写）
- 类型的内容（AgentTypeRecord 由装配层注入）

## Failure Semantics

- 同名 reserve 冲突：结构化错误（`agent_name_conflict`），已有 agent
  不受影响。
- 父 closed 时 reserve：结构化错误（`parent_not_open`）。
- commit 时 reservation 已回滚/过期：结构化错误（`reservation_stale`），
  不产生半注册条目。
- 解析歧义：结构化错误（`agent_reference_ambiguous`），附候选全路径
  列表——让模型能立即修正调用。
