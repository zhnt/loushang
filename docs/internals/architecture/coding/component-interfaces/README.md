# Loushang Coding Component Interface Notes

## Status

The directory is retained as design history for the original Coding component
decomposition. It is no longer the current shared-owner map. Use the
[Harness Current Owner Map](../../harness/current-owner-map.md) for ownership,
the [Product And OEM Glossary](../../../glossary/loushang-product.md) for
terminology, and current focused Product documents for the remaining Coding
adapters.

## Purpose

本目录用于放置 `loushang-coding` 各组件的单独接口说明。

它和总览文档的分工是：

- 总览文档负责全局接口面与跨组件一致性
- 本目录负责单组件 one-pager

对应总览文档：

- [Loushang Coding Component Interfaces](../loushang-coding-component-interfaces.md)
- [Loushang Coding Component Inventory](../loushang-coding-component-inventory.md)

## Writing Rule

每个组件文档都应保持简洁明了，优先回答：

- 这个组件负责什么
- 它拥有什么边界
- 它依赖谁
- 它对外暴露什么 Commands / Queries / Events

本目录仍属于 `architecture` 文档集。

因此，这里的组件接口说明可以表达：

- 已接受的组件级接口设计
- 当前代码尚未完全落地的目标接口面

但这类文档不应用来记录：

- 当前开发状态
- 当前实现完成度
- 当前迭代的临时方案

不应在单组件文档里重复展开：

- 大段背景说明
- 长时序图
- 字段级 schema
- 实现细节
- 阶段性优先级与推进判断

具体实现状态以代码与测试为准；这次迭代的临时接口设计应继续放在 spec / plan 中。

## File Naming

- 每个组件一个文件
- 文件名直接使用组件名
- 例：`session.md`、`store.md`、`prompt.md`

## Template

新建组件接口文档时，优先复制：

- [_template.md](_template.md)

## Retained Component Notes

- [bootstrap.md](bootstrap.md)
- [sdk.md](sdk.md)
- [cli.md](cli.md)
- [mode.md](mode.md)
- [rpc.md](rpc.md)
- [runtime.md](runtime.md)
- [session.md](session.md)
- [store.md](store.md)
- [message.md](message.md)
- [event.md](event.md)
- [tools.md](tools.md)
- [exec.md](exec.md)
- [compaction.md](compaction.md)
- [prompt.md](prompt.md)
- [skill.md](skill.md)
- [loader.md](loader.md)
- [resources.md](resources.md)
- [extensions.md](extensions.md)
- [plugin.md](plugin.md)
- [package.md](package.md)
- [domain.md](domain.md)
- [control.md](control.md)
- [policy.md](policy.md)
- [diagnostics.md](diagnostics.md)
- [platform.md](platform.md)
- [workflow.md](workflow.md)
- [utils.md](utils.md)

`method.md` remains as a compatibility entry for older links. The canonical
coding component is now [domain.md](domain.md); method resources and method
plan ownership live in `loushang.method`.
