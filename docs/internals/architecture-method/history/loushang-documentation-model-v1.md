# Loushang Documentation Model V1

## Status

- Authority: historical documentation-governance model
- Design status: superseded
- Implementation status: not-applicable
- Owner: Loushang architecture method history
- Superseded by: [Architecture Artifact Model](../artifact-model.md)

This document preserves the documentation model that preceded the recursive
Architecture Scope and Current/Target/History governance method. It remains
useful as rationale, but it is not a current authority.

## Original Scope

本文档定义 `loushang` 的文档分层与职责模型。

它主要回答：

- 不同类型的文档各自应该表达什么
- `architecture`、`spec / plan`、代码与测试之间如何分工
- 设计与实现对照时应如何阅读这些材料

本文档不展开：

- 单个子系统的具体接口设计
- 某次迭代的实现步骤
- 具体差异项清单

## Why This Existed

`loushang` 同时维护：

- 目标架构设计
- 组件级接口设计
- 单次迭代的临时设计
- 代码与测试中的事实行为

如果这些材料没有明确分工，常见问题会反复出现：

- 用架构文档冒充当前实现说明
- 用组件接口文档记录开发状态
- 用 spec / plan 替代长期设计
- 直接拿旧文档与代码对照，得出错误结论

本文档的目的，是把这些材料的职责边界先钉住。

## Documentation Layers

### 1. `architecture`

`architecture` 文档主要表达 should-be 的目标边界、结构约束与已接受设计。

它回答的是：

- 系统应该如何分层
- 组件边界应该如何划分
- 接口与数据对象应该如何建模
- 哪些设计口径已经被接受

它不负责：

- 记录当前开发状态
- 说明当前实现完成度
- 承接某次迭代的临时方案

### 2. `component-interfaces`

`docs/architecture/.../component-interfaces/` 仍属于 `architecture` 文档集。

它表达的是：

- 组件级接口设计
- 组件边界、依赖与对外接口面
- 已接受但尚未完全落地的目标接口

它不应表达：

- 当前开发状态
- 当前实现比例
- 当前迭代的临时接口裁剪

### 3. `spec / plan`

`spec / plan` 文档主要表达某次迭代的临时设计与落地步骤。

它回答的是：

- 这次准备怎么做
- 本轮接受哪版接口与边界
- 本轮打算改哪些文件
- 如何分步落地

它不应替代：

- 长期架构设计
- 组件级长期接口文档

### 4. Code And Tests

代码与测试定义 today actually works。

它们回答的是：

- 当前实际 API 是什么
- 当前实际行为是什么
- 当前哪些能力已经可运行、可验证

因此：

- 设计判断优先看 `architecture`
- 迭代判断优先看 `spec / plan`
- 事实行为优先看代码与测试

## Reading Rule

当某个问题同时涉及设计与实现时，建议按以下顺序阅读：

1. 先确认当前接受的设计口径是什么
2. 再确认本轮迭代是否有临时设计或裁剪
3. 最后再确认代码与测试中的事实行为是什么

不要直接把旧文档、临时 spec 和当前实现混成同一种口径。

## Difference Analysis

分析设计与实现关系时，统一使用 `设计-实现差异`。具体术语见
[Loushang Design-Implementation Difference Terms](../../glossary/loushang-design-implementation-difference.md)。

其中应特别区分：

- `缺失`：设计有，代码无
- `偏离`：设计有，代码也有，但实现方式不一致
- `部分落地`：设计有，代码有，但只实现了部分边界或能力
- `未建模实现`：代码有，设计无
- `文档过时`：当前接受的设计已变化，但文档仍停留在旧口径

## Original One-Line Rule

- `architecture` 写 should-be
- `spec / plan` 写 this-iteration temporary design
- 代码与测试定义 today actually works
