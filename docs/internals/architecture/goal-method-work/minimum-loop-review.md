# Goal 最小业务闭环：设计评审记录

- Authority: descriptive — 固定修订评审、问题处置和用户评审入口。
- Design status: draft；Implementation status: not-started for Goal。
- Owner：Loushang architecture / HarnessWork 通用 Goal / Coding Product 策略与装配。
- 目标：[G-GOAL-MIN-01](../../plans/2026-10-25-goal-minimum-business-loop.md)。
- 源码基线：本地前置切片 `d1f418de53c58040a590683a0c499ff3de50e50d`；main 基线 `372cde4ade0fe026076c8fa5e8b4486774b09cc3`，未集成。生产源码 hash 见设计 §12。
- 方法：本地干净 master `0f9bd3ff51afabeaaf76cc38dff1ceb279b7d37e`。
- 用户接受：R2 非归属部分已认可；2026-10-26 用户明确要求按 HarnessWork 可选 Goal 方案更新架构并重新三视角评审。归属方向已获授权，R3.1 三视角技术复核完成、无剩余阻断；本轮未启动功能实现。

## 固定评审对象

| 对象 | 修订及 SHA256 |
| --- | --- |
| 原架构设计 R1（历史快照） | `ce70a42716d9894edd4c26fa3f7f7d9c6eb865b5199f49811f22c3eb0e20ba55` |
| 架构设计 R2 | `b3afb190897116719f2b39ef3d2c3c269f5291e2bc6f4bb55acf34762ee300e5` |
| [系统环境图](context.md) | `8eb9d3c04f56b9a2236d4342cf2a8d2baff47356e579057087f27f6d38e85d6d` |
| 目标与验收范围 | `71544b34206305c9b7628279c1886479cc4d45e0e95d1a6aed7c606c1f620512` |

原文副本、manifest 及三名独立 xhigh agent 的证据化报告保存在产品树外：
`/home/dev/lsspace/architecture-analysis/goal-minimum-business-loop-20261025/`。
R1 为 `review-r1-a/b/c.json`，R2 为 `review-r2-a/b/c.json`。评审者不读取本轮
其他人的报告；作者在初审后综合修订，并分别请求受影响复核。
当前修订见[架构 R3](minimum-loop-architecture.md)；上表保留旧修订身份，不将
当前文件误指为 R1/R2 原文。

本轮是架构源码核查和场景走查，未启动 Goal 实现或真实模型调用。旧证据切片的
运行报告只是前置能力证据，不能充当本 Goal 的实现验收。文档规则/链接检查已
通过，证明工作件可访问，不证明架构机制已运行。

前置版本更新：SDK 证据切片已在本地提交 `d1f418de5`，13 个文件组成独立切片，
未包含本 Goal 的组件/状态/场景设计。三个冻结生产源文件及对应回归源的哈希与
原验证记录完全一致，因此没有把版本固定误记为新运行验证。R2 文首“未提交”是
其冻结时的前置状态；当前以前述本地提交定位相同字节，main 集成和完整检查仍
未完成。R2 原文、环境图及目标范围的评审哈希保持不变；冻结时用户接受为 pending，
2026-10-26 已收到后文记录的认可及归属修订指示。

## 三视角与处置

| 视角 | R1 发现 | R2 处置及复核范围 |
| --- | --- | --- |
| A 职责与复用 | GA-B1：只读允许改的源码，无法发现其他项目文件违规改动（阻断） | §7.1 完整有界项目基线及修复后/验证前/完成前比较；新增/删改/改名/类型/链接、测试原文异常均由 Product 拒绝，不更新基线抹违规 |
| B 运行与失败 | B-G1：Session 执行 ownership 和关闭移交缺机制（阻断） | §4 内部创建/恢复原 SDK Session，原 writer 取得后才开放 handle，不借入现成 Session；§9 输入时段、无 await 转发及 close→收束→原 dispose→writer-last，失败保留 cleanup owner |
| B 运行与失败 | B-G2：unknown intent 的恢复准入未决定（阻断） | §8 明确原 Work 无足够证据时会话级 execution_unresolved；首版无解除 API，resume/replace/换 Goal/root 不绕过，不以空查询证明没有执行 |
| B 运行与失败 | B-N1：resolver 可能只绑定 executor，丢失原取消能力（非阻断） | §4 显式将修复 executor/cancellation 同时绑定为原 SessionTurnExecutor；验证保留原真实能力与 unsupported 分支 |
| C 数据与兼容 | GC-C1：driver 输入与可信测试结果边界不明确（阻断） | §7.2 选定有限纯函数域、完整 AST/签名/资源准入、固定测试与原 unittest runner；Product 原 reader 核验 bytes→原 SDK stdin→固定 driver；结果不能由受测源码自报 |
| C 数据与兼容 | GC-C2：跨记录不变量、会话 writer authority 和演进规则不全（阻断） | §8 明确序号/要求/epoch/命令/批次/原 operation/决定的引用与唯一性，同会话固定 writer scope 和 root 派生，required_features/未知版本及只读诊断边界 |

R2 三路受影响复核均已完成，R1 的 5 项阻断及 B-N1 澄清在设计层关闭，三路均
未发现新增阻断。作者逐份读取原报告及关闭证据，并核对最终 manifest；不是仅凭
作者修订说明关闭问题。没有重复运行未变化的源码盘点或无关测试矩阵。

| 独立复核 | 最终结论 | 报告 SHA256 |
| --- | --- | --- |
| A | 0 未关闭阻断、0 新非阻断，可提交用户评审 | `b7f00461a9cccd36557ae7221c4d1dc21d3625e90ba2633eb7ad2a36c820933e` |
| B | 原两阻断与取消绑定澄清关闭，无新增问题 | `89b3ac1d6904ae3d1be94a0ed62033a69943c4dc4d58eb09bfce323238b93c35` |
| C | 原两阻断关闭，无新增阻断 | `23b83585752217b842fb1f4db24b814366c09633abb758290f77b7f392da8c3b` |

上述结论只支持固定 R2 进入用户评审；未来仍需真实证明 AST/输入/driver/约束/
owner/reducer 合同及整个多批模型修复路径。项目清单只证明所列检查点的状态，
不能扩张为“任何瞬时越界写入从未发生”的文件监控保证。

## R2 当时提交用户评审的重要决定（历史）

以下保留 R2 当时提交的内容；2026-10-26 用户反馈及 R3 修订另记于后文。

1. **入口与生命周期**：首版 Linux 本地 SDK，内部创建/恢复专用原 Session，只向外
   暴露 Goal handle；同一会话一个活动 Goal，保留历史。不接任意外部执行 owner。
2. **推进与方法**：显式 Method 真实修复，一次 advance 一批原 Work；初始失败验证
   →模型修复→再验证，失败证据进入后续输入。模型自主规划后续共用同一准入合同。
3. **首个真实任务**：单文件整数减法/clamp 项目；固定测试、完整项目约束清单及
   有限纯函数验收策略。超出语法/依赖域明确拒绝，不能把首例推广成通用 Python
   安全执行器；模型仍真实修改实际源码，不用固定补丁。
4. **事实权威**：新增 Goal 要求/控制/关联/完成记录，复用原 journal 与 writer；
   Work、Transcript、Blob 和 usage 仍归原 owner，没有跨库事务或 exactly-once 承诺。
5. **控制与未知**：正常暂停可重核恢复，修订使旧依据失效；无法核实的旧执行结果
   留作会话级 unresolved，首版没有一键解除/自动重放。放弃目标不代表外部效果收尾。
6. **输入与兼容**：普通 SDK 不变；Goal 专用 handle 在修复 running 时转发原同步
   steer/follow-up/text/image，验证/完成窗口拒绝执行输入；目标变更走显式修订命令。

R2 当时将环境图、组件图、状态图及交接时序集中在 §3/4/5/8，其他关键合同在
§7/9。当前用户已认可其中非归属内容，归属按后文 R3 调整；功能实现仍未启动。
前置集成、实现、真实场景及逐项验收尚待完成，不能因设计完成就宣告整个 Goal 完成。

## 本轮进度与剩余工作

前一目标描述 turn 分类为 progress：新增了明确目标与验收文件；本轮分类亦为
progress：核对源码、补齐候选架构、独立评审并修订实质问题。没有将等待评审或
只复述计划记作实现进度。

R2 当时的推进顺序为：关闭内部设计问题→用户评审接受范围→收束前置证据切片集成与
相关检查→实施并验证原 Goal 全部要求。当前处于按用户指示进行的 R3 归属修订与复核。实现前必须固定真实项目、Method、模型
与权限配置；设计里列出的未来测试不是已执行证据。

## 2026-10-26 用户反馈：Goal controller 的归属

用户原话：“goal controller 为什么是product组件而不是harness里面的一个组件？
或者harnesswork里面的一个组件？最优雅的是？”并表示“其它没有意见”。
据此保留 R2 其余内容的认可，只收束组件归属及其直接影响；不重新开放全部架构，
也不把问题本身记为用户已选择某个新归属。

作者核对现有 Harness owner map、HarnessWork 边界及方法的职责/变化分解原则后，
建议把通用目标控制归到可选 `harnesswork.goal`，Coding 保留领域策略与装配。
R2 原因是先用单个 Coding 场景限制公共合同；它可以解释实施顺序，却不足以
证明通用 Goal 状态、要求版本、控制与跨 Work 关联应长期属于 Coding。

| 候选 | 关键判断 |
| --- | --- |
| 整体留在 Coding Product | 能快速验证首例，但容易把通用控制与 Coding 验收混在一起，未来 Product 复用需再抽取或复制 |
| 整体放基础 Harness | 当前 Harness→HarnessWork 依赖被明确禁止；Goal 需要 Work 事实和持久履约，容易引入反向依赖或过多转发，增加基础执行层职责 |
| 通用控制放 HarnessWork 可选 Goal 模块，领域策略/组装留 Product | 与已有持久履约及 Work 协作更一致；Goal 和 Work 各自保持状态权威，通用层不依赖 Coding/Method 类型，作为推荐候选 |

候选职责调整：

- `harnesswork.goal`：Goal 身份、要求版本、控制状态、epoch、批次意图与关联、
  通用准入/完成提交不变量，以及相应记录语义和 reducer。调用原 Work 端口，
  不合并进 WorkRuntime 的生命周期，也不建立第二执行器、消息队列或模型 loop。
- Product：具体下一批工作策略、Method 准备或未来模型规划、领域要求/证据判断、
  Coding 验收 driver，以及专用原 Session 的创建/关闭、数据根与存储配置。
- 通用控制只调用注入的最小策略/验收/记录合同，不 import Coding 或 Method，
  不自行创建 Coding Session，不把 calculator/AST 规则写入共享控制组件。
- Goal 为可选扩展；普通 Harness 和不使用 Goal 的 Work 路径保持原依赖及行为。
  此调整连带明确通用 record/reducer 与物理存储绑定的责任，不改变已认可的
  要求版本、完成判据、控制、未知执行及首个场景的对外行为。

依据：[Harness Current Owner Map](../harness/current-owner-map.md) 的 Scope/
Dependency Direction 与 [HarnessWork 边界](../harnesswork/README.md) 的 Definition/
Ownership。上述是新的归属推荐，不是已有实现；公共合同、依赖和生命周期的
直接影响需在后续修订中做受影响复核。固定 R2 原文及原三视角报告保留，不把
原报告自动扩张为这个新共享边界已经通过评审。

## R3：按用户指示修订并重新三视角评审

用户随后明确要求：“请按照这个更新、调整架构设计，然后再次开启三视角评审”。
据此将前节推荐方向落实到 R3：通用 Goal controller、记录语义/reducer/codec 归
`harnesswork.goal` 可选模块；Coding 保留下一工作策略、Method 准备、领域验收、
原 Session 和物理存储适配。此处是用户选择的方向，不再作为尚未得到反馈的问题。

本轮检查组件归属及其直接协作，不重做已认可业务范围或把 R2 原报告当新边界的
接受证据。重点为：

1. Core 不 import Coding/Method/私有 Harness I/O；原 Work/Harness 不反向依赖 Goal。
2. 准入与完成分为通用 basis/身份/版本/事实检查和 Product 语义确认，不在 Core
   内硬编码修复阶段、方法编译、AST 或 Blob authority 解释。
3. 三个最小合同 NextWorkPolicy、GoalAcceptancePolicy、GoalRecordStore 的输入、
   返回值、异步准备与同步最后确认责任，以及 command/basis 重试和失效处理。
4. 通用记录/codec/reducer 与物理 root/lease/durable ACK 分开；Core 借用端口，
   Product 仍按原 Work→Session→writer-last 顺序清理，失败时保留 cleanup owner。
5. 冷读的通用历史状态与领域当前有效性区分；unknown 执行闸门和版本/跨记录
   不变量不能因下沉共享代码而被绕过，正常非 Goal 路径仍不启用 Goal。

R2 已认可的本地 SDK/显式 Method/逐批推进、专用 Session、完整项目约束和有限
纯函数验证、控制状态、会话级 unknown 无解除 API 及真实模型交付要求保持。
R3 没有现存生产 Goal 日志需要迁移，因为功能代码尚未实施。

R3 固定快照、manifest 和独立报告位于产品树外
`/home/dev/lsspace/architecture-analysis/goal-minimum-business-loop-20261026/`。
新的三路评审仍由独立 xhigh agent 按职责与复用、运行与失败、数据与兼容组织；
不得读其他本轮报告，不补造缺失机制。具体发现和最终结论完成后在此留证。
本轮仅设计修订与复核，不将源代码静态可行性、旧切片测试或用户方向授权说成
新共享 Goal 已实现、已运行或全目标已达成。


### R3 初审与 R3.1 受影响修订

固定 R3：架构 SHA256 `c5b755f596f91d21c1e48d19106aea52e176e23131280a23e37934a50457edf3`；
`r3-manifest.json` 覆盖 6 份协同文档和 17 份既有源码，三位评审者独立重算均匹配。
A 无阻断；B 提出 3 项阻断；C 的 1 项阻断与 B 的序号交接发现重合，共 3 个问题。
原报告 `review-r3-a/b/c.json` 保留，不用修订后的结论覆写原初审结果。

| 问题 | 直接影响 | R3.1 设计处置（已独立复核关闭） |
| --- | --- | --- |
| B-R3-01 | 合法 not_submitted 重开后可能被空 Work 查询错误归入不可解除 unknown | §8 为严格已确认未提交单列优先冷读，reducer 明确与 association/已受理互斥；冲突拒绝，计数/控制状态保留，不重交原 operation |
| B-R3-02 / G3-C1 | 自有 intent 将 N 推到 N+1 后，旧 basis 精确比较与禁止重标存在歧义 | §4.1 保存原 basis_N，以同命令已 ACK 的唯一 intent 形成 dispatch receipt；只允许这次因果迁移，其他变动拒绝，Product 当前性确认不跳过 |
| B-R3-03 | close 仅等待原 Work，未保证尚在 prepare/assess/reader 中的借用退出 | §9 先 fence 并阻止新协作，等待自有命令/回调/reader/finally 静止，再原 Work/Session 清理、retire、writer-last；异常保留 owner 和资源 |

场景文档同步加入三项反例；本地记录端口明确同步短 I/O，不把此合同外推到异步
远程后端；README 校正历史状态。R3.1 不改变已接受的业务范围、要求、领域测试、
正常控制和保守 unknown 边界，也没有增加队列、恢复引擎、执行锁或 CI gate。
当前固定架构 SHA256 `91783771114d1c9886478f89a0e7f356b2514eb022b9d433d33473c2ffa06c82`，
6 份文档清单为 `r3.1-manifest.json`，快照位于同一分析目录 `r3.1/`。
三位原评审者已分别收到固定修订，按各自职责复核关闭证据及组合影响。


### R3.1 最终复核与综合结论

三位独立 xhigh 评审者均已核对固定 manifest 的 6 份 live/快照文档及 17 份
live/源码提交文件。作者逐份读取原报告与关闭依据，综合检查共享控制、Product
领域/物理资源及原 Work 三方的职责和正常/失败时序，确认三项原问题在设计层关闭。
复核没有以作者的修订说明代替工作件条款，也没有把重复发现当作额外独立问题。

| 视角 | 固定 R3.1 结论 | 独立报告 SHA256 |
| --- | --- | --- |
| 职责与复用 | 0 剩余阻断、0 新发现 | `3d04fe4866a51249a4a23456133a254c68f4dc48e4e1e0f495bb87d424462cd2` |
| 运行与失败 | 0 剩余阻断、0 新发现 | `36381e3491878becf457f03649f2aa38e39b789532ad93dd226a0566e0af5914` |
| 数据与兼容 | 0 剩余阻断、0 新发现 | `d699a0665704c45dc9a3e57a7e9b7125f9a4df82b6371c09190aa153eb687eb1` |

报告为分析目录内 `review-r3.1-a/b/c.json`，原 R3 报告及全部快照继续保留。
作者作为本授权任务的架构责任执行者记录：共享 Goal 归属与受影响协作合同的
内部技术复核已完成。用户对 R2 非归属部分及共享方向的认可照实保留；不制造
用户已逐条确认 R3.1 新增交接细节的记录。环境图等重要工作件仍按用户要求展示
供其评审，本轮授权仅设计修订/再审，不启动功能实现。

已完成文档规则/链接检查（9 项）及 diff 空白检查；生产源码未改、未运行 pytest、
异步 runtime、模型或工具验证。三视角结论不是运行通过：实现阶段仍需证明
自有 intent 派发、未提交/unknown 重开、回调静止和原 Work 取消组合，以及所有
GM 验收条件。特别是：不合作的回调会保持 fenced 资源，未承诺有限关闭延迟；
本地同步 store/accept 的切点不能直接推广到异步远程后端。

后续执行顺序保持：按用户反馈收束重要架构工作件 → 前置证据切片 main 集成与
适当检查 → 实施共享 Goal 最小控制与 Coding 绑定 → 真实模型多批修复/冷重开及
故障验收。尚未完成实现或真实场景，不给出没有依据的总体完成百分比。


## R3.2：Goal 环境图与子组件专项复核

用户在查看派生图后询问其是否已评审；作者明确区分 R3.1 固定架构的既有复核，
与聊天中新展开图尚未作为独立工作件评审的事实。随后用户认可：Codec/Reducer
应属于记录组件内部，外围仅在存在真实语义、协议、物理或寿命差异时保留适配；
用户明确“同意，继续”。本轮据此完成设计落盘及受影响评审，不恢复功能开发。

新增工作件：[HarnessWork Goal 环境与子组件 R1](../harnesswork/goal/README.md)。
以 Goal 为黑盒单独表达直接及间接环境；白盒只保留 GoalController 和 Goal 记录
组件，记录模型/Reducer/Codec 属于后者内部。允许记录组件提供窄编解码接口，
不将接口提供能力等同于独立组件或私有模块可被跨域导入。

| 评审视角 | 本轮直接问题 |
| --- | --- |
| 职责与复用 | 两幅图的研究对象、关系及粒度是否准确；Codec 内聚、接口/运行组件区分；直接原 Work 和真实 Product 适配是否避免无意义桥接 |
| 运行与失败 | Controller/纯记录/物理适配读取及追加交接；原 Work 事实不双写；R3.1 receipt、not_submitted 和 close 静止点组合仍成立 |
| 数据与兼容 | 唯一格式/reducer 权威、Codec 窄接口、历史与当前领域有效性、原物理耐久/锁域和未知演进边界未混淆 |

固定对象由 `r3.2-manifest.json` 标识，SHA256
`fe8d39c0dfd0330a04b429ee2b30cacb648e1394936e0728895668400dfd309a`。
7 份协同文档及 17 份原源码的固定身份、`r3.2/` 文档副本及新独立报告均在原分析目录
`/home/dev/lsspace/architecture-analysis/goal-minimum-business-loop-20261026/`。
子系统视图 SHA256 `c1bd8caac4aadb1762adf8c6c8e7ec2d099a462677d60f7a8b5cc725ec75f0f6`。
三位独立 xhigh 评审者分别获得同一固定对象，不读取彼此本轮报告或本评审记录，
仅复核直接变化，不重新打开用户已接受的业务范围。旧 R3.1 通过不被冒认为新图通过。
具体发现、处置与最终结论在实际返回后追加。


### R3.2 最终专项结论

三位独立 xhigh agent 均直接评审了固定子系统工作件中的黑盒环境图、内部组件图、
功能映射/组件收敛和适配选择；不是只复用 R3.1 的归属结论。7 份 live/快照文档、
17 份源码及源码提交身份均经核实，独立报告如下。

| 视角 | 固定 R3.2 结论 | 报告 SHA256 |
| --- | --- | --- |
| 职责/粒度与复用 | 0 阻断、0 新发现 | `ed3379c75a824fcdf4efa97c0595195bf367d95265ae30128605c7dfaecf0fd6` |
| 运行与失败 | 0 阻断、0 新发现 | `fd692733fe2de283e339d832a8df798603d9502ae32d7cde2f8ef59b8cc8cd46` |
| 数据与兼容 | 0 阻断、0 新发现 | `2b142c8a7133194d8f31e00b9260b1f51e3d7902cf1c5696c3bd7859d3ef0cb9` |

原始报告为分析目录 `review-r3.2-a/b/c.json`。作者逐份读取其证据和局限，综合确认：

- 研究对象是整个 Goal；五类直接协作者和外围间接路径明确，逻辑关系不冒充 import/部署。
- Controller 与纯记录组件有不同职责；模型/Reducer/Codec 共同内聚于记录组件。
- 记录组件提供窄编解码接口不意味着 Codec 独立或私有模块开放；存储适配仍只拥有物理事务。
- 原 Work 直接协作；方法、验收、存储和入口保留实际 Product 适配/装配，不新建统一桥接平台。
- 从 load/decode/replay 到拟变化校验/append/ACK、原 Work 事实和领域当前性路径可衔接；
  Codec/Reducer/物理适配没有重复权威。R3.1 三项原阻断关闭及业务范围完整保留。

本授权任务的架构责任执行者据此记录上述新工作件内部技术复核完成。用户同意
组件收敛及适配方向的事实已保留，不扩写为逐条接受所有新图或授权实施；重要
工作件仍展示供用户评审，本轮保持功能实现未启动。具体 Python 文件/API 不由
图提前冻结，未来实现需遵守这些边界并取得原 GM 验收证据。

检查按本地 HEAD 的文档变更计划选择文档规则/链接检查，9 项通过，diff 空白
检查通过；无生产源码、测试或 CI gate 改动，未运行 pytest/async/模型。图及
静态源可承载的结论不等于 Goal 已实现、真实修复已完成或平台支持已扩展。
