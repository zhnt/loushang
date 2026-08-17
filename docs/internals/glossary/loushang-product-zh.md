# Loushang Product 与 OEM 中文术语对照表

本文档是 [Loushang Product And OEM Glossary](./loushang-product.md) 的中文
对照表，用于团队讨论、架构评审和实现计划编写。英文术语及完整边界定义以
`loushang-product.md` 为规范源。

## 核心心智模型

```text
平台 CLI 或 OEM CLI
  → 平台宿主
  → OEM 配置
  → Product 注册表
  → Product 路由器
  → Product 工厂
  → 每个 Product Session 只有一个活跃 Product Runtime
       → Product 内核
       → 已准入的 Capability Pack
       → 已激活的 Product Capability Bundle
       → Product 批准的 Plugin 贡献
```

Harness 提供产品中立机制；Product 提供领域语义、默认值与策略；OEM 选择并
覆盖多个 Product；Plugin 只能在 Product 和 OEM 准入后贡献可选资源或行为。

## 核心概念所在维度

这些术语分别回答不同问题，不能互相替代：

| 英文术语 | 所在维度 | 核心问题 |
| --- | --- | --- |
| Product | 领域身份 | 哪个完整领域体验拥有当前 Session？ |
| OEM | 平台选择与覆盖 | 当前发行选择哪些 Product、默认值、策略、资源与品牌？ |
| Capability | 运行时组合 | 运行时需要绑定什么具名能力？ |
| Harness Capability | 共享机制 owner | 哪些产品中立契约或机制由 Harness 拥有？ |
| Package | 分发与物化 | 软件或资源如何交付？ |
| Plugin | 可选身份与激活 | 哪个 manifest-backed 贡献源可以被独立准入和启停？ |
| Extension | 可执行或声明式贡献 | 什么可选行为进入一个明确的扩展面？ |

运行时关系是：

```text
OEM 选择并覆盖 Products
  → Product 声明并绑定 Capability Slots
     → Harness 提供产品中立的 Harness Capabilities
     → 已准入 Plugin 贡献资源或 Extensions
```

分发关系是另一条独立轴：

```text
Product Package  → 注册 Product
OEM Package      → 提供 OEM Profile、覆盖和可选 Plugins
Resource Package → 分发资源和可选 Extensions
Plugin           → 为贡献源提供可选身份与激活边界
Extension        → 向已准入运行时扩展面贡献行为
```

## 平台与启动模型

| 英文术语 | 中文术语 | 中文简介 |
| --- | --- | --- |
| Platform | 平台 | 可发现、注册并承载一个或多个 Product 的 Loushang 系统；平台本身不是领域 Product。 |
| Platform Host | 平台宿主 | 进程级组合根，负责 Product 发现、OEM 选择、Product 路由、共享服务和运行时释放。 |
| Platform CLI | 平台 CLI | 中立的 `loushang` 命令入口，根据显式参数或配置选择 OEM 与 Product。 |
| OEM CLI | OEM CLI／OEM 品牌命令 | 如 `acme` 的 OEM 品牌入口；调用共享平台启动机制，不复制 Product 启动逻辑。 |
| Default OEM | 缺省 OEM | 启动请求未指定 OEM 时使用的 OEM Profile。 |
| Default Product | 缺省 Product | OEM 或平台未收到显式 Product 选择时启动的 Product。 |

`loushang.<OEM>.cli` 可以是某个实现模块路径，但不是架构概念或强制打包规范。
平台应通过已注册且已信任的描述符加载 OEM，而不是从未校验字符串拼接导入路径。

## Product 模型

| 英文术语 | 中文术语 | 中文简介 |
| --- | --- | --- |
| Product | 产品 | 拥有领域目标、语言、Prompt、能力默认值、策略、上下文、Artifact、Session 兼容性和呈现语义的完整领域体验。 |
| Product Kernel | Product 内核／产品内核 | 不能因 Harness 可复用机制增加而迁出的领域语义与策略。 |
| Product Adapter | Product 适配器／产品适配器 | 把 Product 内核绑定到 Harness、Agent、Work、Channel、TUI 等共享机制的代码。 |
| Product Package | Product 包／产品包 | 提供 Product Descriptor、Factory、Adapter 和内置资源的可安装软件分发。 |
| Product Descriptor | Product 描述符 | 不创建运行时的数据注册记录，至少包含稳定 `product_id`、版本、API 兼容信息和工厂引用。 |
| Product Factory | Product 工厂 | 根据已准入的平台、OEM、工作区、Channel 和 Session 上下文创建 Product Runtime。 |
| Product Registry | Product 注册表 | 当前 Platform Host 已准入 Product Descriptor 的确定性目录。 |
| Product Router | Product 路由器 | 为启动、请求、工作区或持久化 Session 选择已注册 Product 的机制。 |
| Product Runtime Plan | Product 运行时计划 | Product 声明的能力槽、默认选择、可覆盖来源和配置；不包含 live object 或凭证。 |
| Resolved Runtime Profile | 已解析运行时配置 | 将 Product、OEM、Extension 和 Session 层确定性合成后的能力选择。 |
| Product Runtime | Product 运行时 | Product Factory 创建的一个活跃、已绑定执行实例。 |
| Active Product | 活跃 Product | 拥有当前 Product Session，并解释其输入、上下文、策略、Artifact 和呈现的 Product。 |
| Product Session | Product 会话 | 由一个 Product 及其 Session schema 和兼容策略拥有的持久或临时交互范围。 |
| Product Handoff | Product 移交 | 在不同 Product Session 之间显式转交 Work、Artifact 引用或用户意图。 |
| Code-Enabled Product | 具备代码能力的 Product | 挂载 Product 已批准的 Harness workspace、文件、进程、Sandbox、Approval 或自动化能力，但不因此获得 Coding Product 身份或完整仓库工程生命周期。 |
| Coding Product | Coding Product／代码产品 | 拥有完整仓库工程体验、Coding Prompt、工具包缺省、Git 工作流、Session 兼容性、诊断与呈现语义的 Product。 |

一个 Product Session 恰好有一个 Active Product。平台可以同时承载多个 Product，
但不能在不迁移的情况下把一个 Session 的 `product_id` 原地改成另一个 Product。

每个 Product 都可以具备适合自己的代码能力，但并非每个 Product 都是 Coding
Product。挂载 Harness 所有的 read、list、search、write、edit 或进程执行机制，
不会创建第二个 Product，也不会自动授予不受限 shell、网络、依赖安装或工作区
访问权。已接受的目标 Coding 专属可挂载 Capability ID 只有
`coding.arch` 和 `coding.lsp`；对应 Coding 常量已存在，但顶层 planner 与
live Mount graph 尚未实现。read、list、search、write、edit 与授权进程
执行是 `harness.workspace` 的内部 facet。Coding 对这些共享机制的缺省 pack、
文案、策略和激活选择，以及其他 Product Kernel 语义仍由 Coding 拥有。

## OEM 模型

| 英文术语 | 中文术语 | 中文简介 |
| --- | --- | --- |
| OEM | OEM／OEM 配置 | 选择 Product，并覆盖其允许配置、资源、能力、模型、权限、Channel 和品牌呈现的平台配置。 |
| OEM Package | OEM 包 | 提供 OEM Profile、可选 OEM CLI、资源覆盖、Extension、品牌与 Product 可用策略的可安装分发。 |
| OEM Profile | OEM 配置描述 | 声明启用的 Product、缺省 Product、Product 覆盖、共享 Extension、品牌、模型和权限策略的数据配置。 |
| OEM Layer | OEM 层 | 应用到 Product 已声明覆盖点的 OEM 选择或资源；不能修改 Product 封闭的 Capability Slot。 |
| Multi-Product OEM | 多 Product OEM | 在同一个 Platform Host 中准入并配置多个 Product 的 OEM Profile。 |
| OEM Product | OEM 自有 Product | 仅指 OEM 确实定义独立 Product 内核与 `product_id` 的情况。 |

OEM 通常不是 Product。一个 OEM Package 可以启用 `coding`、`ppt` 和
`environmental` 等多个 Product，也可以把 Coding 设为缺省 Product。

## 能力组合模型

本节只定义术语。绑定、冲突、依赖、权限与生命周期规则见
[Harness Capability Variation And Replacement Boundary](../architecture/harness/capability-variation-and-replacement-boundary.md)；
顶层依赖方向与 Mount 生命周期见
[Capability Dependency And Mount Lifecycle](../architecture/harness/capability-dependency-and-mount-lifecycle.md)。

| 英文术语 | 中文术语 | 中文简介 |
| --- | --- | --- |
| Capability | 能力 | 可命名的运行时或领域关注点，如 Store、Memory、Tool、Command、Deck Renderer 或 Artifact Handler。 |
| Capability ID | 能力标识 | 顶层 Capability 的稳定 owner-qualified 身份，如 `harness.workspace` 或 `coding.lsp`；它不是 live Mount、实现 key、权限、Protocol 或 Plugin 身份。 |
| Capability Bundle | 能力运行时组合 | 由 owner 组装、实现且仅实现一个 Capability ID 的运行时边界；可包含 Tool、Resource、公共 facet view 与更细粒度的私有 Binding Facet。它不是面向装配或分发的 Product Capability Bundle。 |
| Harness Capability | Harness 能力／共享能力 | 由 Harness 拥有公共契约、可复用机制或可覆盖平台默认值的产品中立 Capability；“共享”不表示全局单例、强制启用或 Plugin 类型。 |
| Capability Dependency | 能力依赖 | 一个 Capability ID 对另一个 Capability ID 的声明式依赖；图中 `A -> B` 表示 A 依赖 B，B 先绑定、后释放。 |
| Binding Facet | 绑定分面 | Capability Bundle 内部由 owner 管理的选择、provider、贡献族或生命周期单元；可以有独立诊断，但不自动成为顶层 DAG 节点。 |
| Capability Slot | 能力槽 | Product 声明的能力绑定位置，定义组合形态、生命周期范围、刷新边界和允许来源。 |
| Runtime Capability Shape | 运行时能力形态 | `RuntimeCapabilitySlot` 的选择保留和绑定规则：`single`、`exclusive`、`ordered` 或 `append_only`；它与 provider/extension surface 的行为组合语义正交。 |
| Capability Provider | 能力提供者 | 经过发现、准入和解析后，可绑定到 Capability Slot 的工厂、适配器或运行时实现；被安装或发现本身不授予权限。 |
| Override | 覆盖／变体 | 对 Product 或 Platform 缺省行为的泛称；它本身不规定冲突规则，必须进一步说明使用哪一种组合语义。 |
| Aggregate Contribution | 聚合贡献 | 所有获准贡献都保持有效，并由所属 Product 或 Harness 机制确定性合并。 |
| Ordered Interception | 有序拦截 | 获准处理器组成顺序明确的处理链，并按照声明的错误策略委托、观察或转换结果。 |
| Decoration | 装饰 | 有序拦截的受限形式；包装已经解析的能力，但不接管选择权，也不能削弱授权、沙箱或生命周期不变量。 |
| Exclusive Replacement | 独占替换 | 一个声明的变体 surface 最终只有一个获准 provider 生效；选择必须显式且可解释，Runtime Capability Shape 另行决定选择保留和刷新。 |
| Protocol Injection | 协议注入 | Composition Root 通过稳定 Protocol 或公共能力契约注入实现；运行时调用注入对象不构成源码反向依赖。 |
| Composition Root | 组合根 | 发现、准入、解析、构造、绑定并释放运行时对象图的最外层生命周期 owner。 |
| Invariant Enforcement Layer | 不变量执行层 | 围绕可替换 provider 或私有机制强制授权、审批、沙箱、资源限制、校验和清理保证的不可绕过包装层。 |
| Trusted Backend Substitution | 可信后端替换 | 仅在 owner 明确公开相应 seam 时，由可信 Platform 组合替换私有机制；它不是普通 Plugin 权利。 |
| Capability Pack | 能力包 | 运行时准入后，针对单一能力项类型的有序贡献组；对应代码中的 `CapabilityPack[T]`。 |
| Product Capability Bundle | Product 能力组合包 | 面向装配或分发、可包含多个 Capability Bundle、Capability Pack 与资源类型的组合，如 `ppt-authoring`；它不是顶层 DAG 节点。 |
| Capability Mount | 能力挂载 | Product 把已准入 Capability Bundle 接入特定运行时 scope 的动作和结果；Capability ID 本身不是 Mount。 |
| Mount Policy | 挂载策略 | 决定何时挂载已准入 Capability 的 Product 策略，如 `disabled`、`on_demand`、`always`；它不选择 provider 或授予权限。 |
| Mounted Capability | 已挂载能力 | 绑定到具体 process、tenant、workspace、Session、turn 或 Channel scope 的 Capability Bundle 实例，如 `coding.lsp@session:session-42`。 |

Runtime Capability Shape 与行为组合语义不是同一维度：`ordered` shape
既可以承载 Aggregate Contribution，也可以承载 Ordered Interception；
`single`／`exclusive` 只说明最终绑定一个选择，并不自动授予任意来源替换权，
其中 `exclusive` 还要求 sealed refresh boundary。

`CapabilityPack[T]` 不是安装包。它只组合一种 `T`，例如 Tool 或 Command。
`ppt-authoring` 如果同时包含 Skill、Prompt、Tool、Command、Deck Asset、
Renderer 和 Artifact Handler，应称为 Product Capability Bundle。

Coding 挂载 `ppt-authoring` 后仍是 Active Product；如果需要 PPT 专属 Canvas、
Session、Compaction、审批或 Deck 生命周期，应通过 Product Handoff 进入 PPT
Product。

## Package、Plugin、Extension 与资源模型

| 英文术语 | 中文术语 | 中文简介 |
| --- | --- | --- |
| Package | 包（需加限定词） | 架构文档中必须写成 Product Package、OEM Package 或 Resource Package。 |
| Python package | Python 包 | Python 导入或软件分发概念；不自动表示 Loushang Resource Package、Plugin 或 Product Package。 |
| Resource Package | 资源包 | 可安装或物化的 Skill、Prompt、Theme、Extension 和 Product Asset 集合。 |
| Plugin | 插件 | 可选、可独立启停的资源根或 Extension 贡献来源；受 Product/OEM 信任与激活策略控制。 |
| Extension | 扩展 | 通过约定扩展面贡献的可执行或声明式行为，如 Tool、Command、Hook、Policy、Renderer 或 Channel Adapter。 |
| Skill | 技能／Skill | 教给模型专业工作流、领域约定或 Tool 使用方式的指令资源，不代表执行权限。 |
| Product Asset | Product 素材／产品素材 | 由 Product 解释的领域文件，如模板、布局、品牌包、图片或设计素材。 |
| Deck Asset | Deck 素材／演示文稿素材 | PPT 领域的 Product Asset，如演示模板、Slide Layout、Master、Theme、Brand Kit 或媒体。 |

三者关系应写成：

```text
plugin source → plugin manifest → resource package root → resource descriptors
                                                       → extension descriptors
```

- Resource Package 是分发／物化边界；不一定带有 Plugin manifest。
- Plugin 是 manifest-backed 身份、准入和启停边界；可以只贡献 Skill、Prompt、Theme 或素材。
- Extension 是运行时行为贡献；被发现不等于已获准执行，也不会因此成为 Product。

Deck Asset 可以来自 PPT Product、OEM 覆盖或 Product Capability Bundle，但不应
为了复用相对文件路径而被建模成 Skill。

## 启动关系示例

缺省平台启动：

```text
loushang
  → 解析 Default OEM
  → 解析该 OEM 的 Default Product
  → 创建对应 Product Runtime
```

OEM 品牌启动 Coding 并激活 PPT 创作能力组合包：

```text
acme
  → 使用 "acme" OEM Profile 启动共享 Platform Host
  → 选择 "coding" Product
  → 激活已准入的 OEM 与 ppt-authoring 组合贡献
```

完整 PPT Product：

```text
loushang ppt
  → 选择 "ppt" Product
  → 创建 PPT Product Session
```

## 避免混用的术语

| 避免术语 | 应改用 |
| --- | --- |
| Product Plugin | Product Package；如果同时实现 Plugin 合约，明确写出两个角色。 |
| PPT Skill Pack | 仅包含 Skill 时使用；跨 Skill、Tool、素材等类型时用 Product Capability Bundle。 |
| OEM Product | OEM CLI、OEM Profile、OEM Package、带 OEM Layer 的 Product，或真正拥有独立 `product_id` 的 OEM Product。 |
| Multi-Product Session | 部署可用性用 Multi-Product OEM；跨 Product 转交用 Product Handoff；真正统一语义时定义新的 Product。 |
| `loushang.<OEM>.cli` | 这是实现路径；架构术语用 OEM CLI、注册入口和 Platform Host。 |
