# Loushang Coding Component Interfaces

## Status

Superseded as the current cross-component interface map by the
[Harness Current Owner Map](../harness/current-owner-map.md). Feature-local
Coding contracts remain useful historical inputs, but shared resource,
Package, Plugin, and Extension contracts are owned by Harness.

## Scope

本文档作为 `loushang-coding` 组件接口设计的总入口。

它主要回答：

- 组件接口文档应该怎么读
- 接口命名与分层遵循什么统一规则
- 每个组件的详细接口应该去哪里看

本文档不再重复展开每个组件的长段接口说明。

详细 one-pager 统一放在：

- [component-interfaces/](component-interfaces/README.md)

当前组件清单总表见：

- [Loushang Coding Component Inventory](loushang-coding-component-inventory.md)

## Design Basis

本文档建立在以下文档之上：

- [Loushang Coding Component Structure And Responsibilities](loushang-coding-component-structure-and-responsibilities.md)
- [Loushang Coding Component Dependencies](loushang-coding-component-dependencies.md)
- [Loushang Coding Core Service Objects](loushang-coding-core-service-objects.md)
- [Loushang Coding Core Data Objects](loushang-coding-core-data-objects.md)
- [Loushang Coding Deployment Unit Terminology](loushang-coding-du-terminology.md)
- [reference coding agent Internal Dependency Overview](reference/reference-coding-agent/architecture-dependencies.md)

## How To Use This Doc Set

建议按下面顺序阅读：

1. 先看本文档，理解接口命名、分层和跨组件约束
2. 再看 [Component Inventory](loushang-coding-component-inventory.md) 了解组件清单与结构分层
3. 最后按需进入 [component-interfaces/](component-interfaces/README.md) 阅读单组件 one-pager

阅读时还应区分两种口径：

- `architecture` 文档主要表达 should-be 的目标边界与结构约束
- `spec / plan` 文档主要表达某次迭代的临时设计与落地步骤

## Interface Conventions

当前接受以下统一规则：

- 服务对象名尽量对齐 `reference coding agent`
- 方法 / 函数名使用 Python 风格 `snake_case`
- Python SDK surface 通过 `loushang.py.typed` 声明 typed package；新增稳定公开类型时应补顶层
  `loushang.coding` 导出或明确记录只在子包导出
- 单组件文档统一按 `Role / Owns / Depends On / Commands / Queries / Events` 描述
- 组件特定边界以单组件 one-pager 为准

典型命名例子：

- `createAgentSession()` -> `create_agent_session()`
- `createAgentSessionRuntime()` -> `create_agent_session_runtime()`
- `switchSession()` -> `switch_session()`
- `waitForIdle()` -> `wait_for_idle()`
- `continue()` -> `continue_run()`

## Interface Classification

为保持接口面一致，当前统一使用三类接口：

1. `Commands`
   - 推进状态、改变状态、触发运行

2. `Queries`
   - 只读查询、获取当前视图

3. `Events`
   - 对外暴露的稳定事件面

## Component Navigation

### Entry And Surface Layer

- [bootstrap](component-interfaces/bootstrap.md)
- [sdk](component-interfaces/sdk.md)
- [cli](component-interfaces/cli.md)
- [mode](component-interfaces/mode.md)
- [rpc](component-interfaces/rpc.md)

### Runtime Core Layer

- [runtime](component-interfaces/runtime.md)
- [session](component-interfaces/session.md)
- [store](component-interfaces/store.md)
- [message](component-interfaces/message.md)
- [event](component-interfaces/event.md)

### Execution And Assembly Layer

- [tools](component-interfaces/tools.md)
- [exec](component-interfaces/exec.md)
- [compaction](component-interfaces/compaction.md)

### Resource And Customization Layer

- [prompt](component-interfaces/prompt.md)
- [skill](component-interfaces/skill.md)
- [loader](component-interfaces/loader.md)
- [resources](component-interfaces/resources.md)
- [extensions](component-interfaces/extensions.md)
- [plugin](component-interfaces/plugin.md)
- [package](component-interfaces/package.md)
- [domain](component-interfaces/domain.md)

### Control, Platform And Support Layer

- [control](component-interfaces/control.md)
- [policy](component-interfaces/policy.md)
- [diagnostics](component-interfaces/diagnostics.md)
- [platform](component-interfaces/platform.md)
- [workflow](component-interfaces/workflow.md)
- [utils](component-interfaces/utils.md)

## Cross-Component Constraints

当前建议把这些约束视为接口一致性的主规则：

- `session` 是业务中心；不要把核心编排下沉到 `cli`、`mode` 或 `bootstrap`
- `store` 负责持久化边界；special summary entry 不应伪装成普通 message
- `message` 与 `event` 应尽量早稳，避免后续 mode/tool/diagnostics 大面积返工
- `prompt` 是资源层到运行层的桥，不应吞并 `skill`、`domain` 或 `session` 的职责
- `domain` 是 coding 对 `loushang.method` 的桥，不拥有 method registry/compiler/projector lifecycle
- `package` 负责 package lifecycle；`plugin` 只负责 manifest-backed source view 与资源展开
- `tools`、`exec`、`policy` 保持分离；不要把工具注册、命令执行和审批逻辑混成单层
- `compaction` 是协调层，不应回流成 `store` 或 `session` 内部的隐式逻辑
- `utils` 只能做薄辅助层，不应承载隐藏业务中心

## Related Docs

- [Loushang Coding Component Inventory](loushang-coding-component-inventory.md)
- [Loushang Coding Component Structure And Responsibilities](loushang-coding-component-structure-and-responsibilities.md)
- [Loushang Coding Component Dependencies](loushang-coding-component-dependencies.md)
- [Loushang Coding Development Priority And Stability Strategy](loushang-coding-development-priority-and-stability-strategy.md)
- [Component Interface Notes](component-interfaces/README.md)
- [Proposed Coding LSP Capability Architecture](lsp/README.md)
