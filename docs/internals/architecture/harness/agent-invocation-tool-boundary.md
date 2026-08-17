# One-Shot Agent Invocation Tool Boundary

Status: P0 implemented (2026-08-04)

## Decision

`delegate_agent` 是一个有限、同步、一次性的 admitted tool，不是
`harness.multiagent` 中的 child actor，也不是 Session、Work 或异步 job。
第一版只允许 Coding 的只读 agent type，并复用当前 Session 的
`ExecService` 启动一个 `loushang --mode print` 子进程：

```text
model tool call
  -> AgentDelegateToolPack                         Harness
  -> prepare complete immutable subprocess plan   Coding adapter
  -> AuthorizedExecution + ProcessEffect          Harness Gateway
  -> current Session ExecService / sandbox
  -> bounded opaque stdout                        Coding adapter
  -> AgentToolResult                              Harness
```

这个边界有意不复用 `spawn_agent` 的树、mailbox、round、follow-up、approval
bubbling 和 child registry 语义。子进程退出后调用即结束。

## Ownership

Harness 拥有：

- `AgentInvocationRequest`、`PreparedAgentInvocation` 和
  `AgentInvocationResult` 三个冻结值对象；
- `AgentInvocationAdapter` 这一窄 Product seam；
- `AgentDelegateToolPack`、schema、顺序执行语义，以及
  `AuthorizedExecution + ProcessEffect`；
- prepare / authorize / execute / project 的不可绕过顺序。

Coding 拥有：

- agent type 准入、角色 system prompt 和每类工具集合；
- `loushang` CLI argv、`--mode print` 输出含义、模型引用和 cwd 规则；
- 子进程安全默认值与最终输出/错误投影；
- 在 Product bootstrap 中把适配器注入 Harness tool pack。

Harness 不认识 `loushang` CLI flag、Coding 角色或 plain-mode 事件 schema；
Coding 不自行执行或绕过 Harness Gateway。

## P0 Security Contract

1. Product 先生成完整的 `ExecRequest`，再交给 Policy/Approval；授权对象包含
   精确 argv、cwd、timeout、模型引用、工具白名单以及 task/environment 摘要。
2. task 正文只通过 stdin 传入，不出现在 argv、`ProcessEffect`、Policy subject
   或审计 arguments 中。完整继承环境同样不进入审计，只以摘要绑定冻结计划。
3. handler 在执行前重新计算并核对上述授权事实；执行时把 Gateway 产生的
   `EffectiveExecutionProfile` 绑定到同一个冻结请求。
4. 子工具集合是“父会话允许的工具 ∩ Coding 只读角色工具”。无论父集合为何，
   都删除 `delegate_agent`、整个 multi-agent tool pack 以及 `bash/write/edit`。
   因而 P0 既不能跨进程递归派生，也不把提示词层面的“只读”误当成权限边界。
   只有只读 execution profile 或等价的可验证策略传递落地后，才重新评估给
   subprocess explorer 开放 shell。
5. 子 CLI 强制 `--no-session`、`--no-extensions`、`--no-skills` 和
   `--no-prompt-templates`。子进程没有交互式审批通道，外层 Session 的
   Policy、Approval、Sandbox 和取消信号仍然有效。
6. timeout 与输出上限由 Product 固定，模型不能修改；返回值是有界 plain
   output，不解析或依赖 TUI JSONL 事件。滚动捕获产生的临时 artifact 由
   `ExecService` 在投影完成前删除，既不向模型暴露，也不遗留在宿主文件系统。
7. 可选 `cwd` 必须解析到当前 Session workspace 内；动态 Session cwd 是
   默认根，不能被 runtime builder 的初始目录错误固化。
8. Coding 默认不注册该工具；只有用户通过显式 `--tools delegate_agent,...`
   选择时才装配和激活，避免在缺少独立预算控制的 P0 中产生隐含成本与延迟。

`ProcessEffect` 是必要但不充分的保护。真正的不放大来自外层执行授权、Sandbox
ceiling 和子工具非扩张三者同时成立。

## Explicit Non-Goals

P0 不提供：

- 写入型 implementation worker；
- follow-up、steering、list、attach、resume 或持久 Session；
- job id、后台轮询、跨调用取消或恢复；
- JSONL event parsing、流式 child event 投影或远端 wire protocol；
- 通用 `AgentRuntimeProvider`、`AgentExecutionPort` 或独立
  `harness.agent_invocation` 子系统。

只有出现第二个非工具消费者、第二个真实 backend、稳定异步 job，或需要版本化
输出协议时，才重新评估是否从 `harness.tools.agent_delegate` 提炼独立 substrate。
只有需要持续寻址、follow-up、审批冒泡、共享跨进程配额或恢复 Session 时，才把
相应 backend 接到 `harness.multiagent`。

## Verification

架构与回归测试必须持续证明：

- tool definition 使用 `AuthorizedExecution` 并声明 `ProcessEffect`；
- Policy deny 时不会调用 exec service；
- task/凭据不进入 authorization arguments；
- Gateway execution profile 和取消信号传到同一请求；
- cwd 不越界，工具集不放大且不能递归派生；
- timeout、cancel、非零退出、空输出和截断具有稳定语义；
- 默认 Coding 装配不提供该工具，只有显式 `--tools delegate_agent,...` 才注册；
- 大输出的滚动捕获不会遗留临时 artifact。
