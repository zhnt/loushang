# Loushang Design Method: Identify Component

## Status

- Authority: normative supporting method for candidate component discovery
- Design status: accepted
- Implementation status: not-applicable
- Owner: Loushang architecture method

The canonical end-to-end method and Architecture Scope promotion rules are
defined by
[Architecture Design And Governance Method](README.md).

## Scope

本文档定义 `loushang` 在进入子系统白盒设计阶段时，如何识别候选组件。

本文档只讨论：

- 组件候选的识别来源
- 候选组件进入清单的判断标准
- 功能、组件、边界、实现依赖之间的区分方法
- 如何从系统环境图识别候选组件与变化维度
- 识别完成后应进入的下一步收敛工作

本文档不讨论：

- 某个子系统的最终组件划分
- 最终模块结构
- 具体代码实现
- 组件到文件的映射
- 组件之间的最终一对一或多对多映射结论

---

## Why This Exists

在黑盒阶段，关注点主要是：

- public contract
- 子系统边界
- 外部关系

进入白盒阶段后，仅靠这些信息已经不够。  
此时必须识别：

- 子系统内部的稳定职责单元
- 为隔离外部变化而存在的边界组件
- 为扩展点、非功能特性与横切技术点服务的支撑结构
- 从系统环境图就能看出的外部变化维度

如果这一步不先完成，后续很容易出现：

- 功能、组件、实现依赖混写
- 组件边界发现过晚
- 扩展点位置不清楚
- 认证、校验、错误映射、加载、配置等能力散落在实现中

因此，白盒阶段应先做：

- 候选功能清单
- 候选组件清单

而不是直接进入最终组件分解或代码实现。

---

## Expected Outputs

采用本方法后，后续至少应产出三类工作产物：

1. 候选功能清单
2. 候选组件清单
3. 功能到组件的映射分析

其中：

- 候选功能清单回答“子系统需要稳定承载哪些能力”
- 候选组件清单回答“哪些职责单元值得成为白盒设计对象”
- 映射分析回答“功能最终由哪些组件承载”

需要注意：

- 组件不必与功能一一对应
- 映射关系可以是：
  - 一对一
  - 一对多
  - 多对一
  - 多对多

这些映射关系不在本方法文档中下最终结论，而在后续阶段继续分析。

在进入候选功能清单和候选组件清单之前，建议先准备两类环境图：

1. 逻辑系统环境图
2. 物理系统环境图

因为很多组件并不是从“功能名词”里直接长出来，而是从系统环境图中的：

- actor
- user
- protocol family
- auth
- transport
- model family
- host/runtime constraints

这些变化面被识别出来的。

---

## Core Principle

组件识别阶段的目标不是立即定版，而是：

- 先发现
- 再分类
- 最后再收敛

因此，本阶段必须允许：

- 多列一些候选
- 暂时保留重叠
- 暂时保留边界模糊对象

但不允许：

- 组件、功能、外部系统、实现载体混为一谈

同时还要记住：

- 不应只从用例和 API 名词识别组件
- 还应从系统环境图识别稳定变化来源
- 很多边界组件和支撑组件，首先不是“功能对象”，而是“变化吸收对象”

---

## Refinement Principles

候选功能清单与候选组件清单完成后，不应立刻凭感觉定版。  
在进入组件收敛、分解、组合前，应先遵守以下原则。

### 1. High Cohesion, Low Coupling

默认目标仍然是：

- 高内聚
- 低耦合

但这两个词需要落到可执行判断上：

- 一个组件内部职责应尽量共同服务一个中心目的
- 一个组件应能用几句话清楚说明“它做什么、不做什么”
- 组件之间应尽量减少双重拥有与双向依赖
- 若两个组件都在长期拥有同一职责，应视为边界不清

需要特别注意：

- 对边界组件，不追求字面上的最低耦合
- 更重要的是把对外部系统、协议、SDK、transport 的高耦合局部化，避免向核心组件扩散

### 2. Component Promotion Rule

一个对象值得从“责任簇”升格为正式候选组件，通常需要满足下列条件中的大部分：

- 承担稳定职责
- 边界清楚
- 可单独说明输入、输出、依赖
- 会被多个功能复用
- 用于隔离外部变化
- 若不单独抽出，后续很容易散落

若不满足这些条件，优先保留为：

- 责任簇
- 组件内部子模块

而不是勉强升格成组件。

### 3. Decomposition Granularity Rule

组件分解粒度应保持克制与一致。

判断粒度是否合适时，优先看：

- 单个组件是否已经承载多个中心目的
- 同一层次对象是否大小严重失衡
- 某个对象是否只是 helper 级细节，却被抬成与核心组件同级

不建议机械规定固定粒度，但可以采用一个经验范围：

- 某一层长期少于 3 个对象，说明这一层可能过粗
- 某一层明显超过 9 个对象，说明这一层可能过细，需要分组或提升中间抽象

这里的 `3-9` 只是经验范围，不是硬约束。

### 4. Consistent Decomposition View

同一层级中的对象，分解视角应尽量一致。

不能把这些对象混放在同一层级：

- 业务主能力
- 边界吸收能力
- transport 细节
- SDK 实现载体
- 零散 helper

因此，在同一轮分解里必须先问：

- 这一层是在按什么维度分解

常见维度包括：

- 功能
- 边界
- 技术支撑
- 扩展点

若维度混乱，应优先重排，而不是继续细拆。

### 5. MCME-Oriented Rule

这里将 `MCME` 解释为一组面向组件收敛的执行原则，而不是只保留缩写：

- 组件内部职责应尽量共同服务一个中心目标
- 组件之间职责应尽量互斥，避免双重拥有
- 无法完全互斥时，应明确主拥有者与协作者
- 共享能力优先抽成支撑组件，不要在多个组件中复制扩散

也就是说：

- 组件内部要“尽量共同”
- 组件之间要“尽量分明”

### 6. Split, Merge, Keep Rule

在收敛阶段，每个候选对象都应先判断属于哪一类动作：

- `split`
- `merge`
- `keep`

#### `split`

当一个候选组件已经明显承担多个中心目的时，应优先分解。

#### `merge`

当两个候选对象长期一起变化、边界很难分清、独立存在收益很低时，应优先组合。

#### `keep`

当一个对象职责明确、边界清楚、依赖关系稳定时，先保持不动。

### 7. Ownership Rule

每项稳定能力都应回答三个问题：

- 谁主负责
- 谁协作
- 谁不应拥有

若回答不出这三点，说明当前边界仍不稳定。

### 8. Layer Restraint Rule

`layer` 应谨慎使用。

在 `loushang` 架构里，层更适合站在整个系统范围内讨论。  
通常 `3-7` 层已经足够。

因此：

- 不应在单个子系统内部随手命名很多 `layer`
- 白盒阶段优先识别组件、组件组与责任簇
- 只有当一组对象处于相近抽象层级，并且遵守一致依赖方向时，才适合被称为 `layer`

像下面这些对象，在白盒阶段更适合先叫：

- component
- component group
- responsibility cluster
- helper / utility

而不是直接称为 `layer`

### 9. Utilities And Helpers Rule

`utils` 或 `helpers` 可以存在，但不应成为逃避建模的垃圾桶。

只有在以下情况下，才适合把对象视为 helper / utility：

- 它不拥有稳定业务或边界职责
- 它主要提供局部复用的小型支持逻辑
- 换一种组织方式不会改变系统结构

---

## Identification Sources

候选组件可以来自多个来源。  
这些来源不应互斥，而应叠加使用。

### 1. 功能

从子系统需要稳定承载的能力出发识别候选组件。

### 2. 参考系统

从参考系统的白盒组件与职责簇出发识别候选组件。

### 3. 用例名词与动作

从场景中的名词、动作、输入输出对象识别候选组件。

### 4. 系统环境图

这是白盒阶段经常被遗漏、但非常重要的一类来源。

系统环境图不仅帮助识别：

- 外部 actor
- 物理 user
- 逻辑边界

还帮助识别：

- application protocol families
- auth styles
- transport modes
- model family handling
- provider actor kinds
- host/runtime constraints

这些对象中，很多本身不是组件，但它们会直接驱动以下候选对象出现：

- 边界组件
- supporting component
- capability / metadata handling component
- auth / transport / loading / validation 等责任簇

### 5. 对外关系与边界支撑

从与外部系统交互时必须建立的稳定隔离层识别候选组件。

### 6. 为可扩展性而存在的结构

从注册、加载、override、hook、bootstrap 等扩展点骨架识别候选组件。

### 7. 为非功能特性而存在的技术支撑

从 observability、validation、overflow、caching、safety 等支撑结构识别候选组件。

### 8. 横切技术点

从 cancellation、error mapping、normalization、auth、transport 等横切变化面识别候选组件。

---

## Using System Context To Identify Components

在白盒阶段，建议把系统环境图作为正式识别输入，而不是只把它当成“总览图”。

### 1. 先从逻辑系统环境图识别

逻辑系统环境图适合识别：

- internal logical actors
- external logical actors
- 相邻子系统 actor
- 外部 actor
- application protocol family
- auth source
- transport mode
- model family metadata

这些对象中：

- actor 往往提示边界组件
- user 往往提示 public entry / local workflow / runtime boundary
- family / mode / source 往往提示变化维度

### 2. 再从物理系统环境图识别

物理系统环境图适合识别：

- physical users / operators
- implementation carrier
- provider actor kinds
- host/runtime dependency
- SDK / HTTP / websocket / SSE 等技术接线路径

这些对象中：

- physical user 往往提示顶层入口、example / test / packaging / bootstrap 边界
- carrier / transport 往往提示边界支撑组件
- model family / actor kinds 往往提示 capability handling 或 resolver 类组件

### 3. 区分“变化源”和“组件”

从环境图识别出来的对象，不能直接等同为组件。

例如：

- `openai-responses`
- `SSE`
- `API key`
- `OpenAI-family provider actor`

这些首先是：

- 协议族
- transport
- auth material
- actor kinds

它们本身不是组件，但会推动产生：

- `Provider Adapter`
- `Auth Support`
- `Transport Strategy`
- `Model Capability Resolver`

### 4. 判断哪些变化值得升格

当某个变化面满足下列条件中的大部分时，应优先考虑在组件设计中显式承认它：

- 它稳定存在
- 它已经影响多个 provider / protocol
- 它会在后续继续扩张
- 如果不单独识别，逻辑会散落在多个文件中
- 它会影响 public contract 或 provider boundary

### 5. 环境图不是装饰图

系统环境图的目标不是“画出来好看”，而是帮助回答：

- 变化从哪里来
- 哪些变化应由边界组件吸收
- 哪些变化应由支撑组件吸收
- 哪些变化应上提为 metadata / capability handling

若一个对象承担了：

- 错误归一
- 认证输入
- cancellation 语义桥接
- provider bootstrap

这类稳定职责，就不应轻率降格为普通 `utils`

### 10. Component Group vs Component Rule

需要特别区分：

- 组件组
- 单一组件

有些对象虽然都属于“支撑能力”，但职责中心并不相同。  
这类对象可以：

- 放在同一个组件组中观察
- 放在同一层次中并列讨论

但这并不意味着它们应该被合并成一个单一组件。

因此应明确：

- 同组归档，不等于同组件拥有
- 组件组可以是弱内聚集合
- 单一组件仍应追求高内聚

只有当多个对象：

- 长期一起变化
- 边界很难分清
- 独立存在收益很低

时，才适合进一步组合为一个组件。

---

## Distinguish The Objects

在识别候选组件前，必须先区分以下对象：

### Component vs Class

组件不是代码构造物类型，而是架构中的职责边界与协作单元。

类不是组件本身。  
类只是实现组件的一种代码组织手段。

因此：

- 组件按职责边界识别，不按代码构造物识别
- 类、函数、模块、包都可能是组件的实现形式
- 不应因为一个对象是 class 就自动将其识别为组件
- 也不应要求组件必须最终落成单一 class

需要特别注意：

- 一个组件可以由一个类实现
- 一个组件也可以由多个类、多个模块或一组函数共同实现
- 一个类也可能只实现某个组件中的局部职责

所以：

- 组件是架构层概念
- 类是代码实现层概念

### Function

功能回答：

- 子系统需要提供什么能力

功能不是组件。  
功能可能由一个组件承载，也可能由多个组件共同承载。

### Logical Component

逻辑组件回答：

- 子系统内部有哪些稳定职责单元

逻辑组件是白盒阶段的主要识别对象。

### Layer

层回答：

- 在更大系统范围内，哪些组件处于相近抽象层级，并遵守相同依赖方向

需要特别注意：

- `layer` 不是随手给一组对象起的统称
- 只有当一组对象处于相近抽象层级、对上/对下具有一致依赖方向时，才适合被称为 `layer`
- 在当前 `loushang-ai` 白盒阶段，优先识别组件、组件组与责任簇，不要过早在子系统内部命名过多 `layer`
- 更稳定的 `layer` 通常应站在整个 `loushang` 架构范围内讨论，而不是在单个子系统内部随意细分

### Boundary Logical Component

边界逻辑组件回答：

- 为了稳定子系统与外部世界的接口，必须建立哪些隔离层

这类组件通常不是为了内部拆分而生，而是为了吸收外部变化。

### External System

外部系统回答：

- 子系统之外，谁与它交互

外部系统不是内部组件，但经常是边界组件的识别来源。

### Implementation Carrier / Dependency

实现载体或实现依赖回答：

- 用什么库、SDK、runtime、client、基础设施能力来落地组件

它们不是组件本身。

例如：

- `Provider Adapter` 是边界逻辑组件
- `anthropic SDK` 是实现载体
- `httpx` 是实现依赖或实现载体

---

## Candidate Sources

候选组件应至少从以下来源识别。

### 1. From Functions

从子系统功能出发识别候选组件。

关注问题：

- 为了实现这个功能，是否需要稳定职责单元长期承载它
- 一个功能是否天然提示某个组件存在

### 2. From Reference Systems

从参考系统中识别组件线索与职责簇。

当前重点参考可包括：

- `reference AI SDK`
- `kimi-cli`

需要注意：

- 参考系统既可以提供组件线索，也可以提供反例
- 参考系统中的结构不能被直接复制为本系统结论
- 参考系统的价值在于帮助发现候选，而不是替代判断

### 3. From Use Cases

从真实用例中的名词、动作、边界关系中识别候选组件。

常见规律包括：

- 名词常提示稳定对象或边界
- 动作常提示职责与协作链路

### 4. From External Relations

从对外关系与外部变化中识别边界组件。

如果一个外部系统：

- 变化频繁
- 协议复杂
- 供应方不稳定
- 需要兼容多种实现

那么通常会催生边界逻辑组件。

### 5. From Extension Requirements

从可扩展性需求中识别候选组件。

重点包括：

- registration
- bootstrap
- lazy loading
- override
- injection
- plugin-like growth points

这类对象即使暂时不在 public surface 中，也可能是白盒阶段必须识别的内部组件。

### 6. From Non-Functional Requirements

从非功能特性中识别候选组件或支撑职责。

重点包括：

- 可扩展性
- 可测试性
- 可观测性
- 性能
- 可靠性
- 错误隔离
- 配置隔离

这类需求经常催生：

- 支撑组件
- 技术组件
- 边界吸收组件

### 7. From Cross-Cutting Concerns

从横切技术点中识别候选组件或候选职责簇。

例如：

- auth / oauth
- validation
- normalization
- cancellation
- error mapping
- logging / metrics hooks
- overflow / context boundary

这些对象不一定最终都成为一级组件，但白盒阶段必须先识别出来。

---

## Candidate Classification

候选组件清单中的对象，建议先按以下类别归档：

### 1. Logical Functional Component

直接承载子系统对外核心能力的组件。

### 2. Logical Supporting Component

不直接作为对外主能力出现，但为功能组件提供稳定支撑的组件。

### 3. Logical Technical Component

承担内部稳定技术机制的组件。

### 4. Boundary Logical Component

为了稳定外部边界而建立的组件。

### 5. Candidate Responsibility Cluster

尚不确定是否需要独立成组件，但已经足够稳定，值得先记录的职责簇。

这类对象可以在后续阶段再决定：

- 升格为组件
- 合并进其他组件
- 保持为组件内部子模块

---

## Entry Criteria

一个对象如果满足以下一条或多条，应进入候选组件清单：

1. 承载稳定职责
2. 换实现后职责边界仍然存在
3. 为隔离外部变化而存在
4. 为多个功能提供共同支撑
5. 属于明显扩展点或未来扩展点
6. 若不单独识别，后续极易散落到多个实现位置

如果一个对象只回答：

- 用哪个库
- 用哪个 SDK
- 用哪个 runtime

那它通常不进入候选组件清单，而应进入实现选型或依赖清单。

---

## White-Box Reminder

进入白盒阶段后，不能只看 export surface。

必须同时关注：

- export 出来的组件
- internal support components
- internal extension-point components
- internal boundary absorption components

否则会漏掉后期最容易造成混乱的结构，例如：

- oauth / auth integration
- bootstrap / loader
- validation / normalization
- error mapping
- compatibility helpers
- test / faux support

---

## What Happens Next

候选清单识别完成后，下一步才进入：

1. 功能到组件映射
2. 必要抽象判断
3. 组件分解
4. 组件组合
5. 内聚 / 耦合评估
6. 扩展点收敛

也就是说：

- 本文档解决“先找什么”
- 下一阶段解决“如何收敛成最终结构”

---

## Practical Rule

一条实用规则可以帮助识别时不跑偏：

- 先把“值得长期存在的职责单元”识别出来
- 再决定它是不是最终组件

而不是：

- 只看当前代码文件
- 或只看当前 export
- 或只看现在用到了哪些第三方库

---

## Current Recommendation

在 `loushang-ai` 当前阶段，建议按本方法继续推进如下顺序：

1. 列 `reference AI SDK` 白盒候选组件清单
2. 列 `loushang-ai` 白盒候选功能清单
3. 列 `loushang-ai` 白盒候选组件清单
4. 再进入组件映射、抽象、分解、组合与内聚/耦合判断
