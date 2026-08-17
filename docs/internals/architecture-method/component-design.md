# Loushang Design Method: Component

## Status

- Authority: normative supporting method for component discovery/refinement
- Design status: accepted
- Implementation status: not-applicable
- Owner: Loushang architecture method

The canonical end-to-end method, recursive Architecture Scope rules, truth
planes, status model and governance process are defined by
[Architecture Design And Governance Method](README.md).
This document remains authoritative for the focused component-design details
that do not conflict with that method.

## Scope

本文档沉淀 `loushang` 在子系统白盒阶段进行组件设计的方法。  
它不只讨论“如何识别候选组件”，还覆盖：

- 如何识别候选功能
- 如何识别候选组件
- 如何做功能到组件映射
- 如何做第一轮 `split / merge / keep`
- 如何控制粒度、命名、layer 使用与文档组织

本文档不讨论：

- 某个具体子系统的最终组件清单
- 最终包结构
- 具体代码实现
- 最终一轮定版后的详细接口字段

---

## Why This Exists

在 `loushang-ai` 这一轮设计中，我们已经验证了一件事：

- 只做黑盒边界设计是不够的
- 只列候选组件清单也不够
- 如果没有一套明确的方法，后续很容易陷入：
  - 功能、组件、实现依赖混写
  - 组件发现过晚
  - 命名失控
  - layer 滥用
  - 责任簇过早独立化

因此，需要一篇更完整的组件设计方法文档，把这轮有效经验沉淀下来。

---

## Design Stages

建议把组件设计分成 6 个阶段。

### 1. Blackbox Framing

先建立：

- 子系统边界
- 上下游关系
- 外部系统
- public contract 大方向

这一阶段回答：

- 这个子系统是干什么的
- 它不干什么
- 它和谁交互

### 2. Candidate Function Discovery

在进入组件前，先列候选功能清单。

这一阶段回答：

- 子系统需要稳定承载哪些能力

注意：

- 功能不是组件
- 功能可能由一个组件承载，也可能由多个组件共同承载

### 3. Candidate Component Discovery

基于功能、参考系统、用例、边界与横切需求，识别候选组件与候选责任簇。

这一阶段回答：

- 哪些职责单元值得成为白盒设计对象

### 4. Function To Component Mapping

将候选功能与候选组件拉通。

这一阶段回答：

- 哪个功能由谁主负责
- 哪些组件是关键协作者
- 映射更像 `1:1`、`1:n`、`n:1` 还是 `n:n`

### 5. Refinement

基于映射结果做第一轮收敛：

- `split`
- `merge`
- `keep`

这一阶段回答：

- 哪些对象应保留为组件
- 哪些更适合先回收到更强的父域
- 哪些对象仍只是责任簇

### 6. Structure / Interface / Interaction

在收敛后继续形成：

- 组件结构草案
- 组件接口草案
- 组件交互时序

这一阶段回答：

- 核心组件有哪些
- 它们负责什么 / 不负责什么
- 主依赖方向是什么
- 关键时序如何流动

---

## Recommended Output Sequence

建议按以下顺序输出文档：

1. 系统环境或黑盒边界文档
2. 候选功能清单
3. 候选组件清单
4. 功能到组件映射
5. 第一轮 refinement
6. 组件结构
7. 组件接口
8. 组件交互
9. 必要的关键内部协议设计

注意：

- 第 9 步不一定每次都需要
- 但当某个内部协议会直接决定实现结构时，应单独成文

在 `loushang-ai` 中，`raw part` 就属于这一类关键内部协议。

---

## Core Distinctions

### Function vs Component

- 功能回答“要提供什么能力”
- 组件回答“谁负责承载该能力”

### Component vs Class

- 组件是架构层概念
- 类是实现层概念

组件不按 class 识别，也不要求和 class 一一对应。

### Component vs Responsibility Cluster

- 组件具有更明确的边界与拥有者
- 责任簇则是“已经稳定，但暂不一定要独立”的职责集合

### Layer vs Component Group

- `layer` 应站在整个 `loushang` 架构范围内讨论
- 在单个子系统白盒阶段，优先用：
  - component
  - component group
  - responsibility cluster

除非一组对象真的处于相近抽象层级，并且依赖方向一致，否则不要轻率命名为 `layer`

---

## Candidate Discovery Rules

候选功能或候选组件，至少应从以下来源发现：

1. 从功能出发
2. 从参考系统出发
3. 从用例中的名词与动作出发
4. 从外部关系与边界变化出发
5. 从扩展点需求出发
6. 从非功能特性出发
7. 从横切技术点出发

其中：

- 参考系统既提供线索，也提供反例
- 不应直接复制参考系统结构作为本系统结论

---

## Refinement Principles

### 1. High Cohesion, Low Coupling

- 单一组件仍应追求高内聚
- 组件之间应减少双重拥有与双向依赖
- 对边界组件，重点不是字面最低耦合，而是把对外高耦合局部化

### 2. Component Promotion Rule

从责任簇升格为组件，通常至少要满足以下条件中的大部分：

- 职责稳定
- 边界清楚
- 可单独说明输入、输出、依赖
- 会被多个功能复用
- 用于隔离外部变化
- 若不抽出，后续会散落

### 3. Decomposition Granularity Rule

粒度控制应克制。

推荐经验范围：

- `3-7` 个同级对象最理想
- `8-9` 进入复查区
- `>9` 通常需要重新分组或上提中间抽象

这里的数字只适用于：

- 层内对象数
- 同级组件组对象数

不适用于：

- 所有 helper
- 所有类
- 所有责任簇的总量

### 4. Consistent Decomposition View

同一层级的对象，应尽量按同一分解视角组织，例如：

- 功能
- 边界
- 技术支撑
- 扩展点

不能把业务主能力、SDK 载体、零散 helper 混在同一层级讨论。

### 5. MCME-Oriented Rule

这里将 `MCME` 落成可执行判断：

- 组件内部职责应尽量共同服务一个中心目标
- 组件之间职责应尽量互斥
- 无法完全互斥时，应明确主拥有者与协作者
- 共享能力优先抽成支撑组件，不要复制扩散

### 6. Split / Merge / Keep Rule

每个候选对象都先判断属于哪类动作：

- `split`
- `merge`
- `keep`

第一轮通常应更保守：

- 能 `keep` 的先 `keep`
- 没充分理由，不轻易 `split`
- 只有独立收益明显不足时才 `merge`

### 7. Ownership Rule

每项稳定能力都要回答：

- 谁主负责
- 谁协作
- 谁不应拥有

如果答不出来，说明边界还不稳定。

### 8. Component Group vs Component Rule

- 同组归档，不等于同组件拥有
- 组件组可以是弱内聚集合
- 单一组件仍应追求高内聚

例如一组“横切支撑对象”可以放在同一组件组中讨论，但不应因此被草率合并成一个组件。

### 9. Utilities And Helpers Rule

`utils` / `helpers` 可以存在，但不能成为逃避建模的垃圾桶。

只有在以下情况下，才适合降格为 helper：

- 不拥有稳定业务或边界职责
- 只提供局部复用小逻辑
- 换一种组织方式不会改变系统结构

如果对象承担了：

- error mapping
- auth input
- cancellation bridge
- provider bootstrap

这类稳定职责，就不应轻率放进 `utils`

---

## Naming Rules

这一轮 `loushang-ai` 设计也证明，命名要尽量克制。

### 1. 不轻易使用 `system`

像：

- `Raw Part Type System`

这类名字通常过重。  
如果对象只是稳定类型集合，更合适叫：

- `Raw Part Types`

### 2. 不轻易使用 `layer`

在单个子系统内部，很多对象其实更适合叫：

- component
- component group
- cluster

而不是：

- `Technical Support Layer`
- `Error Mapping Layer`

### 3. 历史文档应从名字上降级

比如：

- `historical-handoff`

这样后续不会再把它误读成当前主设计文档。

### 4. 通用方法文档应避免绑死子系统名

如果一篇文档沉淀的是可复用方法，命名应尽量通用，例如：

- `history/initial-ai-architecture-method-notes.md`

而不是：

- `loushang-ai-method-notes.md`

---

## Documentation Organization Rules

当某个子系统的设计文档开始增多时，不应继续堆在 `docs/architecture/` 根目录。

更合适的组织方式是：

- 子系统主目录
- `reference/`
- `validation/`
- `history/`

例如 `loushang-ai` 当前采用：

- `docs/architecture/ai/`
- `docs/architecture/ai/reference/`
- `docs/architecture/ai/validation/`
- `docs/architecture/ai/history/`

但通用方法文档仍应留在 `docs/architecture/` 根目录。

---

## Spike Rule

不是每个关键设计都需要先做 spike。

建议规则是：

- 协议建模问题，优先设计
- 运行可行性问题，再做 spike

例如：

- provider adapter 兼容真实端点，需要 spike
- raw part 的边界建模，优先写设计文档

只有当设计过程中仍存在具体高风险不确定点时，再补一个窄 spike。

---

## Suggested Workflow

结合这轮经验，更稳的工作流可以概括为：

1. 建黑盒边界
2. 建 glossary
3. 建 types
4. 对关键高风险主题单独开设计
5. 必要时做 spike
6. 输出 validation 结论
7. 进入白盒阶段：
   - 候选功能
   - 候选组件
   - 功能映射
   - refinement
   - structure / interfaces / interactions
8. 对关键内部协议做最后补充
9. 再进入实现计划

---

## Relationship To Existing Docs

这篇文档是更总的方法文档。  
它和已有文档的关系建议如下：

- [Component Identification Method](component-identification.md)
  - 偏“如何识别候选组件”
- [Initial AI Architecture Method Notes](history/initial-ai-architecture-method-notes.md)
  - 偏“本轮工作过程中的经验记录”
- 本文
  - 偏“端到端的组件设计方法”

---

## Takeaway

这轮 `loushang-ai` 设计验证了一个更完整的方法：

- 组件设计不是直接画组件图
- 而是一条从边界、术语、类型、关键设计、验证、候选发现、映射、收敛到结构化表达的链路

如果以后在 `loushang` 的其他子系统继续做白盒设计，建议优先复用这套方法，而不是重新从“组件是什么”开始讨论。
