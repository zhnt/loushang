# Loushang Coding Development Priority And Stability Strategy

## Scope

本文档定义 `loushang-coding` 的开发优先级与稳定性策略。

本文档目标是回答：

- 哪些组件/对象应优先开发
- 哪些中心依赖对象应尽量一次开发到位
- 哪些能力可以先做窄实现
- 后续 P0 实施时应遵循什么顺序

本文档不展开：

- 具体任务分解
- 具体文件列表
- 详细迭代计划

## Design Basis

本文档建立在以下文档之上：

- [Loushang Coding Component Dependencies](/home/dev/workspace/loushang/docs/architecture/coding/loushang-coding-component-dependencies.md)
- [Loushang Coding Core Service Objects](/home/dev/workspace/loushang/docs/architecture/coding/loushang-coding-core-service-objects.md)
- [Loushang Coding Core Data Objects](/home/dev/workspace/loushang/docs/architecture/coding/loushang-coding-core-data-objects.md)
- [Loushang Coding Key Mode Sequences](/home/dev/workspace/loushang/docs/architecture/coding/loushang-coding-key-mode-sequences.md)

同时参考 `reference coding agent` 的复杂度分布与依赖中心判断：

- `AgentSession`
- `InteractiveMode`
- `SessionManager`
- `SettingsManager`
- `ModelRegistry`
- `DefaultResourceLoader`

## Core Principle

当前接受以下开发原则：

### 1. 被依赖最多的对象优先开发

优先顺序不按“最容易写”决定，而按“被依赖程度”和“后期改动代价”决定。

### 2. 中心依赖对象尽量一次定稳

以下对象不应做成临时最小版后频繁返工：

- `message`
- `event`
- `store`
- `AgentSession`
- `SessionManager`
- `SettingsManager`
- `ModelRegistry`
- `DefaultResourceLoader`

### 3. 行为实现可以先窄，中心模型不能太窄

这意味着：

- 可以先少做 mode
- 可以先少做 tool
- 可以先不做 branch/checkpoint 全能力

但不能把以下东西先做成明显会重写的临时结构：

- transcript 对象模型
- `AgentSessionEvent` 事件族
- session store 文件组织
- settings/model/resource 的中心服务边界

## Stability Classes

当前建议把对象分成三类稳定性等级。

### A. Must Be Stable Early

这类对象应尽量一次设计到位。

#### Data / Record

- `SessionEntry`
- `SessionContext`
  - 虽然它是 read model，不直接落盘，但它是高扇出中心对象，且其重建语义应尽早稳定
- `AgentSessionEvent`
- `SessionRecord`
- `SessionMetadata`
- `SessionCheckpointRecord`（至少要预留位）

#### Services

- `AgentSession`
- `SessionManager`
- `SettingsManager`
- `ModelRegistry`
- `DefaultResourceLoader`

理由：

- 它们是高扇出中心
- 后续几乎所有 mode、tool、diagnostics、extensions 都会依赖它们
- 一旦返工，波及面最大

### B. Should Be Stable Early

这类对象也应尽早定稳，但允许在实现初期先保留一定裁剪空间。

#### Data / Record

- `AgentSessionState`
- `RunState`
- `ModelSelection`
- `ToolDefinition`
- `PolicyDecision`
- `PromptAssembly`

#### Services

- `AgentSessionRuntime`
- `ToolRegistry`
- `PolicyEngine`
- Harness `PromptAssembler` contract 与 Coding 默认值兼容适配
- `AuthStorage`

理由：

- 它们仍然是中心对象
- 但第一阶段可以先实现较窄的行为面

### C. Can Be Narrow First

这类对象可以先做窄实现，后续再扩。

#### Services / Features

- `ModeAdapter`
- `ExecService`
- `CompactionCoordinator`
- `ExtensionRunner`
- `DiagnosticsService`
- `SkillLoader`
- `MethodRegistry`

#### Mode Surfaces

- `PrintMode`（`text/json` projections）
- `RpcMode`
- `InteractiveMode`（未来）

理由：

- 它们大多建立在前面主骨架之上
- 更适合作为上层投影、协调或增强能力逐步扩展
- 其中 `CompactionCoordinator` / `DiagnosticsService` 更应被视为增强边界，而不是先定义中心数据模型的起点

## Practical Priority Order

当前建议的实际开发顺序如下：

### Phase 1: 先定中心数据与存储骨架

1. `message`
2. `event`
3. `store`

要求：

- 对象模型尽量稳定
- transcript / event / record 的命名与归属先定稳
- 文件组织方式至少定出长期可扩展骨架

### Phase 2: 先定 session 主中心

4. `AgentSession`
5. `SessionManager`

要求：

- `AgentSession` 的职责边界先稳定
- `SessionManager` 的持久化边界先稳定

### Phase 3: 先定控制平面与资源平面中心

6. `SettingsManager`
7. `ModelRegistry`
8. `AuthStorage`
9. `DefaultResourceLoader`

要求：

- 与 `loushang-ai` 的直接接缝先明确
- 避免后期大范围改名或改职责

### Phase 4: 再定工具与装配中心

10. `ToolRegistry`
11. `PolicyEngine`
12. `PromptAssembler`

要求：

- 工具定义与 prompt 装配边界先稳定
- 行为可以先少，但入口面要清楚

### Phase 5: 最后接 mode

13. `AgentSessionRuntime`
14. `Bootstrap`
15. `SDK`
16. `PrintMode`（先 text，再 json projection）
17. `RpcMode`
18. `InteractiveMode`（未来）

理由：

- mode 是上层消费面
- 在中心骨架未稳之前，不应先驱动 mode 设计

## Guidance For P0

这份策略对 P0 的直接约束是：

### P0 不应从 mode 开始

P0 不应以：

- `print mode`
- `json mode`
- `rpc mode`

作为真正的起点。

更合理的起点应是：

- `message / event / store`
- `AgentSession`
- `SettingsManager / ModelRegistry / DefaultResourceLoader`

### P0 可以少做功能，但不能少做骨架

例如：

- branch 可暂不完整实现
- checkpoint 可先预留位
- extensions 可先不落
- interactive 可后置

但：

- transcript 对象模型不能随便临时命名
- event 族不能先做一版临时协议再推倒
- session/store 边界不能先糊起来后面再拆

## Alignment With reference coding agent

该策略与 `reference coding agent` 的主要对齐点是：

- 优先稳定 `AgentSession`
- 优先稳定 `SessionManager`
- 优先稳定 `SettingsManager` / `ModelRegistry` / `ResourceLoader`
- mode 作为上层 adapter，而不是底层中心

## Open Questions

当前仍保留这些执行层面的开放问题：

- `message / event / store` 是否需要再单独补一份更细的稳定骨架文档
- `PromptAssembler` 是否应比 `ToolRegistry` 更早落地
- `AuthStorage` 在第一阶段是否需要完整持久化

## Next Step

基于当前稳定性策略，后续建议直接进入：

1. `message / event / store` 的稳定骨架设计补强
2. P0 实现切片设计
