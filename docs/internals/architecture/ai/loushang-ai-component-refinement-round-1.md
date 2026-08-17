# Loushang-AI Component Refinement Round 1（同步现状）

## Scope

本文档是 `loushang-ai` 白盒组件设计的第一轮收敛结果。  
它基于前面的候选功能、候选组件与功能-组件映射分析，开始回答：

- 哪些候选对象应 `keep`
- 哪些候选对象应 `merge`
- 哪些候选对象应 `split`

本文档只讨论：

- 第一轮组件收敛判断
- 每个判断背后的主要理由
- 第一轮之后更稳的组件结构草案

本文档不讨论：

- 最终包结构
- 最终接口字段
- 代码实现顺序
- v0.1 范围裁剪

---

## Input Documents

- [Loushang-AI Component Structure V1](./loushang-ai-component-structure-v1.md)
- [Loushang-AI Component Interfaces V1](./loushang-ai-component-interfaces-v1.md)
- [Loushang-AI Streaming and Cancellation](./loushang-ai-streaming-and-cancellation.md)
- [Loushang-AI Streaming Semantics](./loushang-ai-streaming-semantics.md)

---

## Refinement Goal

这一轮收敛不追求最终定版，而追求三件事：

1. 让明显稳定的组件先稳下来
2. 让明显过细的责任簇先并回去
3. 让明显过载的候选对象避免继续膨胀

因此这一轮优先采用保守策略：

- 能 `keep` 的先 `keep`
- 没有充分理由，不轻易 `split`
- 只有在独立收益明显不足时才 `merge`

---

## Round-1 Decisions

## 1. Keep As Core Components

以下对象在第一轮应直接保留为正式候选核心组件。

### 1. Public API (`loushang.ai.api`)

**动作：**

- `keep`

**理由：**

- 主功能清晰
- public contract 已冻结
- 与 `reference AI SDK` 对齐明确
- 没有必要再拆

### 2. Model Registry

**动作：**

- `keep`

**理由：**

- 与模型定义/查询的映射接近 `1:1`
- 高内聚
- 与 provider 执行层低耦合

### 3. API Adapter Registry

**动作：**

- `keep`

**理由：**

- 统一接线职责明确
- 与 `api` 维度直接绑定
- 不应合并回 top-level API 或 model registry

### 4. APIAdapter Protocol

**动作：**

- `keep`

**理由：**

- 边界协议作用稳定
- 对 provider adapter layer 有明确约束价值
- 若不保留，会削弱边界稳定性

### 5. Provider Adapter Component (`loushang.ai.protocols.*`)

**动作：**

- `keep`

**理由：**

- 是最典型的边界组件
- 对外部协议的高耦合必须被局部化
- 不应与 registry、assembler、carrier 支撑混在一起

### 6. Raw Part Types (`loushang.ai.event_stream.raw_parts`)

**动作：**

- `keep`

**理由：**

- 是 provider stream 与 public event stream 之间的唯一稳定归一边界
- 若没有这一层，后续语义会散入 adapter 与 assembler

### 7. Raw Assembler (`loushang.ai.event_stream.assembler`)

**动作：**

- `keep`

**理由：**

- 最终消息收敛职责明确
- 与 event stream 紧密协作，但不等同于 event stream
- 是 `loushang-ai` 自身结构中很重要的中心组件

### 8. Assistant Message Event Stream (`loushang.ai.event_stream.stream`)

**动作：**

- `keep`

**理由：**

- streaming public contract 的核心承载者
- 与 `.result()` 语义绑定
- 不应退化为 assembler 的附属对象

### 9. Tool Semantic Component

**动作：**

- `keep`

**理由：**

- 功能域完整
- 与 tool schema / tool call / tool result 语义直接对应
- 后续很可能成为正式逻辑功能组件

### 10. Provider Bootstrap And Extensibility Component (`loushang.ai.bootstrap` + `models.json` compat)

**动作：**

- `keep`

**理由：**

- 白盒阶段必须前置识别的扩展点骨架
- 如果不保留，后续 built-in provider 与 test provider 接线会散

---

## 2. Merge Into Stronger Parents

以下对象在第一轮更适合先并回更强的父组件或父责任域，而不是独立成正式组件。

### 11. Final Message Completion Cluster

**动作：**

- `merge`

**并入目标：**

- `Assistant Message Event Stream`
- `Raw Assembler`

**理由：**

- 它本质上是 stream `.result()` 收敛语义的一部分
- 独立收益不足
- 第一轮没有必要把 completion 再升成一级组件

### 12. Tool Validation Cluster

**动作：**

- `merge`

**并入目标：**

- `Tool Semantic Component`

**理由：**

- 这是 tool semantic 域内的重要支撑职责
- 当前独立边界还不够强
- 第一轮更适合作为 `Tool Semantic Component` 内部子模块

### 13. Thinking / Reasoning Mapping Cluster

**动作：**

- `merge`

**并入目标：**

- `Simple Invocation Mapping`
- `Provider Adapter Component`

**理由：**

- 这是跨 simple 入口与 provider adapter 的共享支撑逻辑
- 单独作为一级组件还偏早
- 第一轮更适合作为 shared mapping 子域

### 14. Multimodal Content Component

**动作：**

- `merge`

**并入目标：**

- `Context Intake And Normalization`
- `Raw Part Types`
- `Tool Semantic Component`

**理由：**

- 功能域真实存在
- 但在 v0.1 前期支持面可能较克制
- 第一轮单独立组件会使结构偏细

### 15. Error Mapping Cluster

**动作：**

- `merge`

**并入目标：**

- `Provider Adapter Component`
- `API Adapter Registry`
- `Assistant Message Event Stream`

**理由：**

- 它是横切责任，但边界更像 shared policy / helper domain
- 作为独立组件的边界还偏弱
- 第一轮先保留为跨多个组件共享的内部责任域更稳

### 16. Auth Input Cluster

**动作：**

- `merge`

**并入目标：**

- `Carrier Invocation Cluster`

**理由：**

- 认证输入当前主要服务于 carrier/provider invocation
- 单独升格为正式组件还偏早
- 但必须保留为明显子域，不能丢进普通 utils

### 17. Environment Intake Cluster

**动作：**

- `merge`

**并入目标：**

- `Carrier Invocation Cluster`
- `Cancellation And Aborted Bridge`

**理由：**

- 当前更像运行条件输入子域
- 第一轮独立收益不足

### 18. Observability Emission Cluster

**动作：**

- `merge`

**并入目标：**

- 作为跨组件共享的 observability support domain 保留

**理由：**

- 这是明确横切能力
- 但还不适合在 `loushang-ai` 内单独抬成核心正式组件

### 19. Test / Validation Support Cluster

**动作：**

- `merge`

**并入目标：**

- `Provider Bootstrap And Extensibility Component`

**理由：**

- 两者都属于长期扩展/验证支撑域
- 第一轮拆得太细收益不高
- 但应明确作为子域保留

---

## 3. Keep As Supporting Domains（含新增）

以下对象暂不升格为“核心正式组件”，但也不建议继续压回 utils。

### 20. Context Intake And Normalization (`loushang.ai.context`)

**动作：**

- `keep`

**定位：**

- 支撑组件

**理由：**

- 它和 top-level API、adapter、assembler 的关系都很稳定
- 当前边界已经够强
- 但后续仍可能与 message/content 语义再做组合

### 21. Carrier Invocation Cluster（边界支撑内子域）

**动作：**

- `keep`

**定位：**

- 支撑责任域

**理由：**

- 虽然不适合叫 layer，也暂不建议升格为一级主组件
- 但它承载 auth、env、client lifecycle、carrier invocation，不能消失

### 22. Simple Invocation Mapping

**动作：**

- `keep`

**定位：**

- shared supporting domain

**理由：**

- simple 入口语义真实存在
- 它既不该全塞进 top-level API，也不该完全下沉到 provider adapter

### 23. Cancellation And Aborted Bridge（见 Streaming & Cancellation）

**动作：**

- `keep`

**定位：**

- shared technical domain

**理由：**

- 已有真实验证支撑
- 责任稳定
- 如果并回某一个组件，后续很容易再次散落

### 24. Provider Payload Transformation（边界支撑内子域）

### 25. Utils / Overflow (`loushang.ai.utils`)

**动作：**

- `keep`

**定位：**

- utilities 域

**理由：**

- `is_context_overflow` 等通用能力应集中管理

### 26. Record & Replay（设计已落地为文档）

**动作：**

- `keep`

**定位：**

- 观测与测试能力域

**理由：**

- 支持 RawPart/vendor-raw 双轨录制与回放，服务于零 Token 回归与诊断

**动作：**

- `keep`

**定位：**

- adapter-internal shared domain

**理由：**

- 这是 provider adapter 的核心子域
- 第一轮不单独升格为正式组件
- 但必须保持显式责任边界

---

## 4. Split Decisions

第一轮不建议新做明显 `split`，原因是：

- 当前候选对象总量并不低
- 先前更大的问题是“命名过细”和“把责任簇抬成层”
- 这一轮优先解决过细与命名漂移，而不是继续向下切

也就是说，当前阶段更合适的主动作是：

- `keep`
- `merge`

而不是继续新增更多子组件。

---

## Round-1 Structure

经过第一轮收敛后，`loushang-ai` 当前更稳的结构可以先理解为：

### A. Core Components

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

### B. Stable Supporting Domains

- `Context Intake And Normalization`
- `Simple Invocation Mapping`
- `Carrier Invocation Cluster`
- `Cancellation And Aborted Bridge`
- `Provider Payload Transformation`

### C. Merged Subdomains

- `Final Message Completion`
- `Tool Validation`
- `Thinking / Reasoning Mapping`
- `Multimodal Content`
- `Error Mapping`
- `Auth Input`
- `Environment Intake`
- `Observability Emission`
- `Test / Validation Support`

这些对象没有被删除，而是先并入更强的父域中观察。

---

## First-Round Cohesion / Coupling View

### Cohesion Strongest

以下对象当前最接近高内聚正式组件：

- `Top-Level AI API`
- `Model Registry`
- `API Adapter Registry`
- `Provider Adapter Component`
- `Raw Part Types`
- `Raw Assembler`
- `Assistant Message Event Stream`

### Coupling Intentionally Localized

以下对象对外部世界天然高耦合，但这种耦合应被明确局部化：

- `Provider Adapter Component`
- `APIAdapter Protocol`
- `Carrier Invocation Cluster`
- `Provider Payload Transformation`

### Still Sensitive To Over-Splitting

以下对象目前最容易因为过早独立而导致结构过细：

- `Tool Validation`
- `Thinking / Reasoning Mapping`
- `Error Mapping`
- `Auth Input`
- `Observability Emission`
- `Test / Validation Support`

---

## Takeaway

第一轮收敛后的核心判断是：

1. `loushang-ai` 已经有一批足够稳定的核心组件
2. 也有一批必须保留、但暂不应升格过度的支撑责任域
3. 当前最大风险不是“拆得不够细”，而是“过早把很多责任簇独立化”

因此，下一步不应再回到大范围发现，而应继续做第二轮更聚焦的 refinement：

1. 为核心组件画边界
2. 为 stable supporting domains 判断是否再升格
3. 明确 merged subdomains 的主拥有者
4. 开始形成更正式的组件关系图
