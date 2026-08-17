# Loushang-AI Function To Component Mapping

## Scope

本文档在 `loushang-ai` 白盒候选功能清单与白盒候选组件清单之间，建立第一轮映射关系。

本文档只讨论：

- 候选功能由哪些候选组件承载
- 每条映射的主承载组件与关键协作组件
- 映射关系的大致形态，例如 `1:1`、`1:n`、`n:1`、`n:n`
- 当前哪些候选组件更像真正独立组件，哪些更像责任簇

本文档不讨论：

- 最终组件定版
- 最终包结构
- 代码层实现顺序
- 组件之间的最终接口字段

---

## Input Documents

本文档建立在以下输入之上：

- [Loushang-AI Whitebox Candidate Functions](/home/dev/workspace/loushang/docs/architecture/ai/loushang-ai-whitebox-candidate-functions.md)
- [Loushang-AI Whitebox Candidate Components](/home/dev/workspace/loushang/docs/architecture/ai/loushang-ai-whitebox-candidate-components.md)
- [Component Identification Method](../../architecture-method/component-identification.md)

---

## Mapping Rule

这里的映射遵守以下原则：

1. 每个功能至少给出一个主承载组件
2. 若一个功能天然依赖多个组件协作，则明确列出关键协作组件
3. 若某个对象目前更像责任簇而非最终独立组件，在表中仍保留，但会标明
4. 当前阶段的目标不是“压扁成最少组件”，而是先看清职责分布

---

## Mapping Table

## 1. Unified Top-Level Model Invocation

**主承载组件：**

- `Top-Level AI API`

**关键协作组件：**

- `Model Registry`
- `API Adapter Registry`
- `Assistant Message Event Stream`
- `Final Message Completion Cluster`

**映射关系：**

- `1:n`

**说明：**

- 这个功能的主承载者很明确，就是 `Top-Level AI API`
- 但它必须依赖 resolution、stream、completion 收敛能力，因此天然不是纯 `1:1`

---

## 2. Model Description And Lookup

**主承载组件：**

- `Model Registry`

**关键协作组件：**

- `Top-Level AI API`
- `API Adapter Registry`

**映射关系：**

- `1:1`

**说明：**

- 当前看这是最接近 `1:1` 的映射之一
- `Model Registry` 很像最终独立组件

---

## 3. API-Based Provider Resolution

**主承载组件：**

- `API Adapter Registry`

**关键协作组件：**

- `Model Registry`
- `APIAdapter Protocol`
- `Top-Level AI API`
- `Provider Bootstrap And Extensibility Component`

**映射关系：**

- `1:n`

**说明：**

- resolution 的主承载组件是 registry
- 但它依赖 protocol 和 bootstrap 才能稳定成立

---

## 4. Cross-Provider Simple Invocation Semantics

**主承载组件：**

- `Top-Level AI API`
- `Simple Invocation Mapping`

**关键协作组件：**

- `APIAdapter Protocol`
- `Provider Adapter Component`
- `Thinking / Reasoning Mapping Cluster`

**映射关系：**

- `1:n`

**说明：**

- 这个功能不应只压在 `Top-Level AI API`
- 也不应完全塞进每个 provider adapter
- 当前更像由一个主入口组件加一个 shared 支撑组件共同承载

---

## 5. Unified Context Intake

**主承载组件：**

- `Context Intake And Normalization`

**关键协作组件：**

- `Top-Level AI API`
- `Provider Adapter Component`
- `Raw Part Types`

**映射关系：**

- `1:n`

**说明：**

- 当前看它值得作为候选组件保留
- 但后续也可能与 type / message 相关结构组合

---

## 6. Provider Protocol Adaptation

**主承载组件：**

- `Provider Adapter Component`

**关键协作组件：**

- `APIAdapter Protocol`
- `Provider Payload Transformation`
- `Carrier Invocation Cluster`
- `Error Mapping Cluster`
- `Cancellation And Aborted Bridge`

**映射关系：**

- `1:n`

**说明：**

- 这是典型边界功能
- 主承载组件明确，但周边支撑层很多

---

## 7. Provider Carrier Selection And Invocation

**主承载组件：**

- `Carrier Invocation Cluster`

**关键协作组件：**

- `Provider Adapter Component`
- `Auth Input Cluster`
- `Environment Intake Cluster`
- `Error Mapping Cluster`

**映射关系：**

- `1:n`

**说明：**

- 这项功能明显不应由 `Provider Adapter Component` 独吞
- 更适合有单独 carrier 支撑层

---

## 8. Streaming Event Normalization

**主承载组件：**

- `Assistant Message Event Stream`
- `Raw Assembler`

**关键协作组件：**

- `Raw Part Types`
- `Provider Adapter Component`
- `Cancellation And Aborted Bridge`

**映射关系：**

- `1:n`

**说明：**

- 这是 `loushang-ai` 与 `kimi-cli` 不同的关键点之一
- 当前最合理的是把 event stream 与 assembler 视为协同承载，而不是把它们硬并成一个对象

---

## 9. Final Assistant Message Assembly

**主承载组件：**

- `Raw Assembler`

**关键协作组件：**

- `Raw Part Types`
- `Assistant Message Event Stream`
- `Final Message Completion Cluster`

**映射关系：**

- `1:n`

**说明：**

- 主承载者相对清楚，应该是 assembler
- 但 completion 与 event stream 紧密参与收敛

---

## 10. Raw-Part Level Normalization

**主承载组件：**

- `Raw Part Types`

**关键协作组件：**

- `Provider Adapter Component`
- `Provider Payload Transformation`
- `Raw Assembler`

**映射关系：**

- `1:n`

**说明：**

- 这项功能的主承载者很明确
- `Raw Part Types` 也很像最终独立支撑组件

---

## 11. Tool Schema And Tool-Call Semantic Support

**主承载组件：**

- `Tool Semantic Component`

**关键协作组件：**

- `Context Intake And Normalization`
- `Provider Payload Transformation`
- `Raw Part Types`
- `Raw Assembler`

**映射关系：**

- `1:n`

**说明：**

- 这是一块完整功能域
- 后续很可能成为独立逻辑功能组件

---

## 12. Tool Argument Validation Support

**主承载组件：**

- `Tool Validation Cluster`

**关键协作组件：**

- `Tool Semantic Component`
- `Error Mapping Cluster`
- `Provider Payload Transformation`

**映射关系：**

- `1:n`

**说明：**

- 当前更像支撑组件或责任簇
- 需要下一步判断是否升格

---

## 13. Thinking / Reasoning Semantic Normalization

**主承载组件：**

- `Thinking / Reasoning Mapping Cluster`

**关键协作组件：**

- `Simple Invocation Mapping`
- `Provider Adapter Component`
- `Raw Part Types`
- `Raw Assembler`

**映射关系：**

- `1:n`

**说明：**

- 这是跨 provider 共享责任
- 当前很像 shared supporting component

---

## 14. Multimodal Content Semantic Support

**主承载组件：**

- `Multimodal Content Component`

**关键协作组件：**

- `Context Intake And Normalization`
- `Provider Payload Transformation`
- `Raw Part Types`
- `Tool Semantic Component`

**映射关系：**

- `1:n`

**说明：**

- 这是完整功能域
- 但是否立即作为一级组件，还要看 v0.1 支持面

---

## 15. Error Normalization

**主承载组件：**

- `Error Mapping Cluster`

**关键协作组件：**

- `API Adapter Registry`
- `Provider Adapter Component`
- `Carrier Invocation Cluster`
- `Tool Validation Cluster`

**映射关系：**

- `1:n`

**说明：**

- 明显是横切技术支撑层
- 不适合塞进某一个主功能组件内部草草处理

---

## 16. Cancellation And Aborted Semantics

**主承载组件：**

- `Cancellation And Aborted Bridge`

**关键协作组件：**

- `Provider Adapter Component`
- `Assistant Message Event Stream`
- `Raw Assembler`
- `Final Message Completion Cluster`

**映射关系：**

- `1:n`

**说明：**

- 这是一项横切功能，但已经足够稳定
- 应保留为明确内部技术能力，而不是散落处理

---

## 17. OAuth / Auth Input Support

**主承载组件：**

- `Auth Input Cluster`

**关键协作组件：**

- `Carrier Invocation Cluster`
- `Provider Adapter Component`
- `Environment Intake Cluster`

**映射关系：**

- `1:n`

**说明：**

- 当前最重要的是先识别
- 是否升格为更明确边界组件，需要下一步再拍

---

## 18. Environment And Host Capability Intake

**主承载组件：**

- `Environment Intake Cluster`

**关键协作组件：**

- `Auth Input Cluster`
- `Carrier Invocation Cluster`
- `Cancellation And Aborted Bridge`
- `Observability Emission Cluster`

**映射关系：**

- `1:n`

**说明：**

- 这是稳定技术边界
- 通常不应与业务输入层合并

---

## 19. Observability And Audit Emission

**主承载组件：**

- `Observability Emission Cluster`

**关键协作组件：**

- `Top-Level AI API`
- `Provider Adapter Component`
- `Assistant Message Event Stream`
- `Error Mapping Cluster`

**映射关系：**

- `1:n`

**说明：**

- 典型横切能力
- 适合作为独立技术支撑层或独立子模块对待

---

## 20. Built-In Provider Bootstrap And Extensibility

**主承载组件：**

- `Provider Bootstrap And Extensibility Component`

**关键协作组件：**

- `API Adapter Registry`
- `APIAdapter Protocol`
- `Provider Adapter Component`
- `Test / Validation Support Cluster`

**映射关系：**

- `1:n`

**说明：**

- 这是白盒阶段必须识别的扩展点能力
- 很像最终独立技术组件

---

## 21. Test / Validation Support For AI Integration

**主承载组件：**

- `Test / Validation Support Cluster`

**关键协作组件：**

- `Provider Bootstrap And Extensibility Component`
- `Provider Adapter Component`
- `Assistant Message Event Stream`
- `Cancellation And Aborted Bridge`

**映射关系：**

- `1:n`

**说明：**

- 这不是主产品能力
- 但作为协议层子系统的长期支撑功能，很值得保留为明确组件候选

---

## Components That Already Look Stable

从当前映射看，以下对象已经比较像最终独立组件：

- `Top-Level AI API`
- `Model Registry`
- `API Adapter Registry`
- `APIAdapter Protocol`
- `Provider Adapter Component`
- `Raw Part Types`
- `Raw Assembler`
- `Assistant Message Event Stream`
- `Tool Semantic Component`
- `Provider Bootstrap And Extensibility Component`

这些对象要么承载明确主功能，要么处在稳定边界上，要么是统一语义的中心支点。

---

## Components Still Likely To Be Refined

以下对象当前更像需要继续判断的责任簇或二级组件：

- `Context Intake And Normalization`
- `Provider Payload Transformation`
- `Carrier Invocation Cluster`
- `Final Message Completion Cluster`
- `Simple Invocation Mapping`
- `Tool Validation Cluster`
- `Thinking / Reasoning Mapping Cluster`
- `Multimodal Content Component`
- `Error Mapping Cluster`
- `Cancellation And Aborted Bridge`
- `Auth Input Cluster`
- `Environment Intake Cluster`
- `Observability Emission Cluster`
- `Test / Validation Support Cluster`

这些对象下一步要回答的问题主要是：

- 是否应该升格为独立组件
- 是否适合组合进更大组件
- 是否应保持为组件内部子模块

---

## Summary

第一轮映射说明了几件事：

1. `loushang-ai` 的大多数功能都不是纯 `1:1`
2. 真正接近 `1:1` 的主要是：
- `Model Description And Lookup -> Model Registry`
- 某些横切能力到其支撑层
3. `Top-Level AI API`、`Provider Adapter Component`、`Raw Assembler`、`Assistant Message Event Stream` 是当前最明显的结构中心
4. `Auth`、`Error`、`Cancellation`、`Carrier Invocation`、`Bootstrap` 这些不能再被当成“以后实现时顺手补”的杂项

---

## Takeaway For Next Step

下一步最自然的是进入第一轮收敛判断：

1. 哪些候选责任簇应升格为正式组件
2. 哪些候选组件应被分解
3. 哪些候选组件应被组合
4. 对核心组件做第一轮内聚 / 耦合判断

我建议下一篇直接写：

- `loushang-ai-component-refinement-round-1.md`
