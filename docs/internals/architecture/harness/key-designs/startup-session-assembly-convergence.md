# H-COD-KD-009 R2：启动与 Session 装配职责收敛

- Authority: accepted key design（§5 publication、§10清理及§12回执交接合同）；其余广域接口仍proposed。
- Design status: accepted（R2 §5、§10清理R2、§12回执交接及原owner复用）；已完成三独立视角增量复核。其余8092行范围的具体接口仍须逐项细化/评审，不预支接受。
- Implementation status: partial；§5 owner publication首批已接入，原21组观察对照及75项实际集成通过；§10清理路径亦已接入、固定44组及实际34节点通过；§12回执交接已接入，原47节点通过/失败集合保持、16固定观察通过，保留10项迁前失败，三视角代码终态已核；其余启动装配仍待收敛。本件不重复KD007已完成的租约、账本和family生命周期。
- Owner: Harness Session/Runtime/Resources及Coding原owner；跨域技术合同由共同架构owner综合接受。
- 依据：[完整Goal](../coding-responsibility-convergence-goal.md)、[Current Owner Map](../current-owner-map.md)、[KD007](plugin-session-lifecycle-convergence.md)。
- 方法：本地干净archmethod master `0f9bd3ff51afabeaaf76cc38dff1ceb279b7d37e`；未验证远程版本。
- 实物起点：Harness lane `harness/coding-responsibility-convergence` 未提交工作树，Code125729/系统637682/1892源。原件和全量指纹保存在产品树外`p2-startup-assembly/start.json`，HEAD不能代替实物。

## 1. 问题、范围与边界

本轮分析`coding/bootstrap.py`3531行、`coding/session/agent_session.py`2372行、`coding/_capability_plugin_composition.py`2189行，共8092行。`_create_agent_session`单函数2196行，混合产品选择、三种来源路线、目录/执行装配、延迟LSP、owner发布与失败清理。AgentSession本身继承通用AgentProductSession，但仍保存两份相似的owner发布状态机和产品组装胶水。

这些文件已经大量复用Harness，不能把全部8092行等同缺口或可删行数。全Code395个dataclass的字段声明仅2326行；只处理字段或薄helper无法解释11万行的剩余量。本件面向整个启动业务路径，不以一次局部迁移代替P2/完整Goal。

保持现有新建/恢复、持久/非持久、legacy/Package Product、只读、显式/延迟能力、嵌入式/托管入口行为。保留Coding产品选择、信任与权限政策、路径/namespace、默认插件、LSP/Arch配置、资源含义、Method/Skill内容与结果投影；共同机制进入原子系统，禁止Harness根目录杂项。

## 2. Current：已经有的能力

| 当前机制 | 源码依据 | 本轮复用边界 |
| --- | --- | --- |
| 标准配置、资源/模型/工具/Agent构造 | `session/bootstrap_configuration.py`、`bootstrap_construction.py`的StandardAgentSessionConfigurationRuntime、AgentProductConstructionBinding/Runtime | Code已经调用；不新建StartupWorkflow/Stage引擎 |
| 通用Session行为、图准备/发布/退役 | `session/agent_product.py`、`composition.py`、`capability_composition_inputs.py` | 保原图和registration权威；不从Code复制第二个AgentProductSession |
| 插件选择、Provider/component装配 | `session/product_composition_assembly.py`及原Capabilities/Approval/Resources | Code给领域请求/授权政策，原compiler/admission/import realm仍执行 |
| member/owner进程租约、证据账本及family/退役/关闭 | KD007实际`session/plugin_lifecycle/`，原PM/Journal | 本轮直接消费，禁止重新实现或重复记完成 |
| 原startup注册与失活、目录、Package事实 | Package Product、Resources、Journal原组件 | 产品根和生命周期策略仍由Coding给；不借Transcript writer或另造registrar |
| 延迟能力与子执行 | DeferredCapabilitySlot、原Session Graph/Multiagent | LSP配置与Git worktree政策留Code；不再造slot/子Session创建器 |
| 失败主异常与清理notes | Code `_cleanup.run_cleanup_steps`，Core构造还有局部同类循环 | 比较原catch/时点后在Session内部共用原程序；不是统一一切关闭语义 |

`RuntimeResourceOwner.close()`无论lease退出是否报错都finally关闭其状态；它是应用run/artifact寿命，不等同Code准备失败custodian的依赖保留/逐项重试。不得以“已有Owner”之名直接替换。原custodian只在runtime结清后释放management，再清composition/private根；正常assembly.close与失败custodian.close的职责也不同。

## 3. 系统环境与组件关系

首批沿用用户已接受的[KD007环境与子组件](plugin-session-lifecycle-convergence.md#3-候选系统环境与子组件)：Coding政策→原Session Plugin集成→原Runtime/Graph、PM、Journal、Package Product/Resources。本文不新增进程、系统环境角色、事实日志或全局执行者。

新增owner publication是该Session集成内部的实现模块：把原Code两套易失发布状态收敛到原owner证据协同处，不作为独立L3组件或新的持久状态权威。AgentProductSession的原stage/commit钩子提供接点；实际owner注册/graph commit与dispose仍由原Graph驱动。其余大块装配若需要变更重要环境/组件关系，必须更新对应工作件并按用户约定提交评审，不能借本首批合同提前接受。

## 4. 完整职责与实施路径

| 原路径/职责 | 选择的owner/复用路线 | Coding保留与待补证据 |
| --- | --- | --- |
| `_create_agent_session`开头恢复、composition、invocation、Worker/权限选择 | Code领域政策；共享输入仍用现有BootstrapServices/ConstructionBinding | 不将coding.base/LSP/Arch、trust和默认权限移为Core隐式政策 |
| 三种Package/legacy/自定义来源的共同输入准备 | 优先原Resource Catalog及Package Product接口，消除初次/refresh的重复观察与装配 | 原来源的判据和错误在Code；完整调用/失败时点映射后才定新接口 |
| workspace execution与sandbox绑定 | 原Authorization/Workspace/Process owners | Code决定workspace writable与权限政策；不能改变委托ceiling或直接暴露宿主执行 |
| capability/provider/component绑定 | 原ProductPluginCompositionPreparation与Session composition inputs | Code加载编码相关配置和确切工具owner，批量去除重复编排；不能绕过原approval/epoch |
| base/capability owner证据的prepare→publish→重试→retire | Session Plugin集成内部，共用一份易失发布算法，直接消费KD007叶lease | Code只选哪些owner/Resource贡献属于哪一组；首批具体合同见§5 |
| 延迟LSP与父子图关闭依赖 | 原DeferredCapabilitySlot与Session Graph；只补必要装配 | 不新建异步队列；取消必须结清真实构造，失败保留原凭据 |
| 失败后custodian、根清理和正常dispose | 原Session构造/Plugin集成内部职责；保各自barrier、逐项重试和notes | 先对照原状态/作用域，禁止以一次通用ExitStack吞掉原恢复合同 |
| composition receipt/恢复授权 | Code领域内容；通用resume effect仍原Transcript/ResumeEffects/Session | 原字段/hash/旧历史和实际参与者集合保持；没有新恢复协议获接受 |
| 两入口与多agent装配 | 复用原AgentProductSessionRuntime、Hosting、Multiagent | Code只保产品参数、Git领域租约；不复制入口业务程序 |

先用首批打通现有Graph publication与原owner证据，随后按同一完整路径继续初次/refresh共同准备、构造失败/正常关闭、根输入与薄入口。每批必须接通真实消费者、删除旧体、计入全部接收成本并评审；不把未完成部分永久认定领域代码。

## 5. 首批专项：owner publication合同

### 5.1 事实与选择

Code AgentSession约2030–2240行的prepare/commit、base与capability两种publish重试程序，以及构造/dispose中的相应flag，是同一流程的两种数据形状。已经存在的持久prepared/published/retired记录与幂等权威仍是KD007 evidence ledger；本批仅收敛图边界上短命的回执/flag/首次错误，不增日志或恢复调度器。

选择在`harness/session/plugin_lifecycle`内部提供一个泛型易失publication程序，并给原单lease与lease集合两种窄target。它们直接调用原Core SessionLease的prepare/publish/retire，集合target负责原顺序fanout；Code不以IO callback代理这些共同动作。收据选择器只从原staged/mounted generations与Resource候选生成值，由Code保留plugin id、Resource贡献筛选及原错误投影。

拟议窄接口（内部名称可在实施时校正，不能改变下述时点）：

```text
PublicationTarget[ReceiptValue]
  has_targets -> bool
  prepare(receipts), publish(receipts), retire(receipts)

OwnerPublication[ReceiptValue]
  prepare(receipts)              # 存回执，再调用原prepare，返回才置prepared
  commit_after_graph()           # 同步原图提交后publish；错误只暂存，不回滚图
  require_published(capture)     # 原调用点：先抛/清一次错误，再仅重试所欠步骤
  retire_after_graph()           # 原实际退役资格检查之后，由原调用者触发
  read-only receipts/flags       # 同一份易失事实，不保留Code双写flags
```

ReceiptValue保原两种形状：base是tuple，capability是plugin→tuple映射。保`bool(raw_value)`分支，不能把“有key但值为空”的mapping当作false。绑定缺席与存在但空的集合target分别处理，完整分支表见§5.4；真实base ledger拒空回执，不能据不可达的手改私有flags状态扩充协议。

两种target是固定现有lease端口的适配，不是新的执行器。若无法消除Code assembly中对应的重复fanout，应把同一Core批处理直接复用回旧薄入口，不能保两份循环。没有真实复用抵消的“再加一层facade”应撤回。

### 5.2 时序与失败表

| 时点/失败 | 必须保留的行为 |
| --- | --- |
| stage owner后、graph commit前 | capability组先于base组；先保留捕获值，再append prepared；失败不冒称prepared |
| graph与owner注册同步提交 | 原commit程序不变；各组publish失败暂存，继续下一组，不回滚已提交图 |
| 下一次业务准备 | 原Code位置在Worker工具activate后、composition receipt前；capability先于base。首次只抛并清原publication error；之后prepare/publish按原flag重试，不重新运行已结清动作 |
| require时已有回执 | 此路径不重复capture；stage hook每次仍capture/store，不能与require合并。无回执时仍在原staged/mounted与prepared参数下capture |
| 部分组或部分lease写成后失败 | 每组flag只在整次调用返回后置位；原ledger幂等处理已写部分，不新建跨组事务 |
| 原graph/child dispose失败 | 保原management lease、根和cleanup凭据；不得先调用retire_after_graph或删状态 |
| retire append失败 | 保存同一组/同一回执/未成功flag，下一次dispose继续；不把cancel/错误称已结清 |
| 新Product/无legacy management lease | 缺省空绑定保持当前行为，不要求凭空owner evidence或拒绝普通prompt |

Receipt排序保原三元key；证据ledger canonical另含contribution_ids。不能把四元排序作为看似相同的helper替换三元排序并改变输入错误面。回执/hash/operation/event身份仍由既有Codec与Ledger决定；新controller对象id不入持久记录。

### 5.3 与现有Session的接点

原AgentProductSession已具prepare/commit hooks，当前缺省无副作用。通过可选、缺省空的固定publication绑定接入原钩子，不改图引擎。Code公开AgentSession构造及prepare_model_call_runtime的恢复/Worker/receipt政策保持；只退出共同状态机，原Code路径上的两个publish方法可保必要薄调用。

新易失状态只由Session拥有。Code composition receipt若需读取回执/状态，消费窄只读view；不把整个Code对象交给Core，不复制旧fields同步双写。原私有测试观察位置随真实owner维护；公开入口、持久字段/类身份与失败恢复保持。继承/private metadata变化单独披露，不能承诺任意私有反射全等。

### 5.4 R2：可达分支与资格精化

本节关闭R1三个视角指出的同一缺口，不引入新的owner/组件或恢复协议。Target的`has_targets`只用于原require提前返回分支，**不能**成为所有phase的统一guard。绑定存在性在原Code选择时点确定：无assembly，或base无management lease，就没有对应绑定；capability assembly存在但lease mapping为空，仍存在集合绑定。已接管的Session中原management lease身份保持，不把内部字段热替换变成新受支持协议；mapping本身仍按原顺序读取，不新增排序或副本。

| 原情况/阶段 | capture与状态写 | 调用与错误消费 |
| --- | --- | --- |
| 无capability assembly | 不建该绑定，未捕获/未准备，缺省状态仍false | 所有相关动作不执行；不要求用户另配evidence |
| base无assembly或无management lease | 无base绑定，原空tuple/false状态 | prepare/require/retire仍不执行 |
| capability assembly存在、leases为空：stage | 仍调用原collector，保存`{}`；空fanout返回后prepared=True | 不调用任何叶lease；不得由has_targets提前跳过 |
| 上述空集合：commit | 原`bool({})`为false，不置published | 不publish、不消费既存error |
| 上述空集合：require | 在读取/清error前返回；原prepared保留 | 不capture、不写入、不消费error |
| 上述空集合：dispose | 无回执不retire，prepared=True仍是原runtime_was_published实参 | 原graph资格检查不能丢失这一信息 |
| mapping有key但tuple为空：stage | 先保存原truthy mapping；叶prepare拒空时flag保持旧值 | 不把mapping压成空tuple，不跳过原错误 |
| 非空stage（含已有值/flags） | **每次**重新capture/store；原prepared/published/retired/error不重置 | 仍调用原prepare；仅在返回后把prepared置True，失败不清此前True |
| collector抛错 | 不改该组原回执，前组已发生动作不撤回 | capability阶段失败则base本次未执行；交原Graph中止路径处理 |
| commit有回执且未published | 调用publish；成功后published=True | 捕获BaseException保存于本组（含取消）；cap失败仍尝试base；不回滚提交图 |
| commit无回执或已published | 原flags/error保持 | 不调用publish，不消费error |
| require有target且有暂存error | 只清该组error并抛同一个异常 | 此次不capture/prepare/publish；cap错误阻断本次base require，不跨组聚合 |
| require无回执 | 原mounted/capability generations、prepared=False的collector；保存值 | 依原flag补prepare/publish；不重新准备Graph或签新身份 |
| require已有回执 | 保原值，不capture | 只补尚欠prepare/publish；不改变该组已成功flags |
| 部分集合叶写入后失败 | 整组flag仅在fanout全部返回后置True | 重试仍按原mapping顺序调用前叶，靠既有ledger幂等，不增加每叶checkpoint或去重身份 |
| 原实际graph退役失败 | 收据、错误与未成功flags保留 | 原caller继续自己的非依赖清理，但不得调用相应retire/释放依赖根 |
| 合法退役调用 | 有回执且未retired时，按原flag补prepare，再retire，成功才置retired | 不以published=True作为新增前置条件；原prepared→retired路径保留 |

默认prepare/commit/require顺序仍capability→base；**dispose不能沿同一顺序批量retire**。原caller先在super graph dispose无错误时retire base，再调用capability assembly.close，且primary_error仍为空才retire capability及confirm/release。base退役失败会阻断后续capability退休，capability.close本身仍按原清理程序尝试。共用程序只处理单组步骤，退役由原资格与原调用点分别触发，不自行推断Graph已关。

首次/重复prepare不重置已成功flag是原合同；本批不借“新generation”语义偷偷修订它。raw tuple/map的真值、错误一次性消费与组间短路都在首批旧行为捕获和迁后对照中验证；未证明的私有任意热改状态不当作新产品保证。

## 6. 选项与理由

| 方案 | 判断 |
| --- | --- |
| 整体搬8092行进Harness | 拒绝：混入产品选择/信任/内容，复杂度和隐式依赖原样保留 |
| 再建通用StartupWorkflowManager和大Context | 拒绝：已有configuration/construction/Graph，易重复引擎并扩大端口 |
| 只拆Code文件/字段/转发模块 | 不足：不能形成职责归一与系统净减，本Goal范围不因此缩小 |
| 原owner复用 + 单一发布算法 + 其余完整装配逐路径收敛 | 选择首批路线；后续接口须经真实源码/场景比较，不能提前称全部可实施 |

若首批实现后只是Code少了而Core多了且没有共同程序复用，必须再收敛或撤回多余层；全成本如实报告。系统最终须净减，所有Protocol、配置、字段兼容与测试外生产代码都计入。

## 7. 验证与交付

1. 冻结实际原源码与收据状态/调用时点，核全部读写消费者和真实可达分支；先捕获旧行为，不用迁后结果生成期望。
2. 复用现有非live Session/Plugin/资源/owner generation与构造失败、dispose重试用例；仅为缺口做树外有限实验，不加/扩PR gate。
3. 对照部分prepare/publish失败、首次错误重抛后retry、组间顺序、tuple/mapping真假值、已提交图不回滚，以及失败保留依赖后关闭重试。
4. 验证公开构造、DTO/codec/旧历史、恢复参与者与两入口合同。保原20秒等超时、skip/host选择器；机器/观察超时与业务失败分开，不靠加严判定造通过。
5. 每批三视角代码评审：职责/复用，运行/失败，数据/兼容；完整成本、原失败与最终终态分别保存。重要环境/组件关系变化仍按原用户评审约定处理。

R2设计冻结时只有静态取证与接口提议；该历史帧及12项原生产源保存在树外。当前§5首批已实施，实际验证另见§9，不能用KD007的旧通过代替本轮验收。


## 8. R2首合同技术接受与原行为取证

三个原独立视角对R1发现同一present-empty分支缺口，R2 §5.4逐项关闭；独立增量复核均无首合同剩余具体设计阻断，确认没有需要重新接受的新环境/组件关系。实施owner `/root`在用户已接受的P2 Session owner证据职责内接受§5首合同；不追认为用户接受新接口、不接受其余广域装配已就绪。冻结R1/R2及六报告在产品树外，状态补记不冒称它们审了当前后加文字的相同SHA。

13375原程序取证21 passed/4.63s：实际Code Session/assembly方法运行，IO叶与Graph退出做确定性stub，逐组捕获prepare/commit/错误/require/retire/close与flags。12原源SHA守卫通过，旧JSON采用独占创建，未修改生产源。它证明有限算法观察，不是完整构造/真实Graph、磁盘、授权或hosted/native平台验证；原21期望迁后不得重写。其余原有端到端回归继续作为实际接入验收。


## 9. 首批接通、实际成本与验证

Session Plugin集成内新增单份易失publication程序；原AgentProductSession的prepare/commit钩子采用缺省空的有序绑定。Code退出两份回执/flag/首次错误状态及共同算法，仅保领域收据选择、Worker/receipt调用时点与原dispose资格。原单lease直接作为target，集合fanout复用同一Core程序，Code原assembly三个入口不再保第二份循环。没有新增Graph、账本、恢复调度或授权判定。

| 全部生产成本 | 起点 | 实际 | 变化 |
| --- | ---: | ---: | ---: |
| Code AgentSession | 2372 | 2295 | −77 |
| Code capability assembly | 2189 | 2187 | −2 |
| 原Core AgentProductSession | 2892 | 2904 | +12 |
| 新Session publication（含接口/状态/view） | 0 | 168 | +168 |
| 全Coding | 125729 | 125650 | **−79** |
| 四根系统 | 637682 | 637783 | **+101** |

全1893源中1889与起点逐字同。系统没有因此净减；本批确实合并两份算法，但接口和只读状态成本较原重复体高。没有以搬迁当精简收益，也不接受整个8092行/P2/Goal完成。后续须按完整路径消除重复装配，原15K/系统净减目标不变。

- 实际21组旧观察对照：30496 exit0，21 passed/9.42s；原期望未重写。确定性叶/Graph替身的局限仍见§8。
- 原70场景加5个Bootstrap装配节点：5537 exit0，**75 passed/382.89s**，零失败/错误/skip。本轮实际测试，不借用上一批结果；保持not-live及skip-host-runtime，未修改断言或超时。
- 99424四显式实际源silent-import mypy通过；这不是全项目类型证明。原Code公开构造参数和两个收据collector完整AST与原件相等，持久codec/ledger未改。
- 首个整文件formatter帧与最终帧AST相同。三个原文件独立format基线已有失败，仅恢复未改子树的原排版，首帧/原件/最终指纹均保留；新Core模块format与四源Ruff通过，不宣称原三文件全格式绿，未改门禁。

三个独立代码视角及各自真实终态补件均无本片具体阻断。实施owner `/root`在原P2授权下有界接受首批publication合同；完整评审见[代码评审记录](startup-session-assembly-convergence-review.md)。源码、固定期望、原始报告和全量成本保存在产品树外p2-startup-assembly，重要环境/组件变化仍按原用户评审约定处理。


## 10. 后续专项候选：构造与交付前后的清理职责

本节R1/R2冻结时接口proposed；后经独立评审另行接受，实际接入见§11，不沿用§5的接受代替本节评审。范围是Code capability composer三个既有对象及Core构造失败程序，不处理此前观察到但尚无完整共同合同的Catalog来源政策。冻结候选在树外cleanup/candidate-r1，原七源候选成本Code−252/Core+264/系统+12；该历史帧不是净删或实际验收，最终接口/类型/格式成本见§11。

### 10.1 唯一状态与复用

三个Code公开dataclass的定义、字段顺序/flags/default/repr/slots、具体返回类型与异常附着/查找仍保原模块。它们在同一个实际对象上采用Session Plugin内部无状态Mixin，Mixin `__slots__=()`且不新持有状态；不再保Code版关闭算法。Code保Coding Capability错误标签、配置/授权/选择与工作区绑定。原runtime.close和Session lease.close是唯一下游动作，不增加依赖管理器、物理IO或清理日志。

Code原run_cleanup_steps共同程序归Session构造内部，保原签名、全尝试、首异常及逐条notes；原Code导入兼容入口只转发，同一程序由Code调用者、Session Plugin及已有Core Bootstrap构造失败复用。Core构造仍逐项取出绑定再执行，不提前批量取所有dispose属性，不改变原catch边界及错误格式。RuntimeResourceOwner/ExitStack不满足原重试合同，不能替换。

### 10.2 三种固定合同

| 对象 | 必须保持的原程序 |
| --- | --- |
| failure custodian | runtime关闭失败阻断所有后续动作；成功后按原mapping逆序尝试所有未释放lease，失败不标成功。全部lease释放后才清management根，再composition根，再private根；前阶段失败保后续根。每项成功flag只在真实动作返回后写，重试跳过已释放lease。callback adopt仍保同一身份判断与原错误。 |
| preparation | closed或transferred直接返回；runtime→逆序所有lease（不新增每叶checkpoint）→management根→composition根→private根。任一步失败保未成功flag，原全部flags才closed；交付后不再清理。 |
| published assembly | close仅runtime与composition evidence；不得由此释放management/private根。confirm仍核原graph资格，prepared未published的退役不被新条件拒绝；release仍先要求retired与runtime_closed，再逆序所有lease，全部成功才清management根。private仍要求原三个flags；abort保原顺序与资格。 |

不将三个close统一成同一策略分支，不建立可配置phase引擎。仅复用固定runtime、三项根清理的成功写flag，以及原全尝试错误累计程序；每种调用方的资格/顺序独立。正常assembly与preparation重试会再次调用已结清lease，靠原lease幂等；custodian有原released ids集合，保该区别。原flags留在同一Code facade对象，构造/字段兼容不靠第二份view或同步。

### 10.3 兼容、验证与接受边界

持久格式/身份/实际writer/lease/Graph/namespace及根寿命不变；继承方法定义metadata变化与私有内部import位置明确，不承诺任意私有反射/任意热重绑全等。外观Code._cleanup原两个导出保持；Core不能反向导入Code。错误标签由Code固定配置，通用机械动作归Session。

实施前捕获原程序的有限调用/flags/错误notes：runtime、lease、各根失败与取消、重试/重复close、transferred/closed、graph资格和callback ownership。实际迁后读取固定期望，不能重生；probe是确定性叶替身，不等于真实FS/并发证明。实际原cleanup、Plugin生命周期及真实LSP父子图关闭失败重试/构造失败节点补接入验证。三视角先审本节和候选，再审实际源码及终态；不扩大CI门禁或原native/host/live范围。

本节沿用既有Session内部集成关系，不新增重要环境/组件关系；若独立复核发现必须改变外部权威或范围，先调整工作件，不能据原P2接受直接放行。完整启动路径、P2和Goal始终保持未完成。


### 10.4 R2：保留属性取值的原异常边界

R1三独立视角发现同一具体问题：向helper传bound method会在实参求值时提前读取dispose属性，若lookup本身失败，将逃出原cleanup catch并覆盖构造主异常。R2在原三个逐项位置传立即执行的lambda；属性读取和调用同处原helper的try内，side-question每次立即执行当前项，不批量预取后续绑定。它不新增委托或phase引擎，原标签/notes和主异常保持。R1原报告和候选字节另存，R2只作此窄修正，不改其它清理合同。


## 11. 清理完整路径实际接入及代码评审

三Code外观保原dataclass字段/slots/构造与具体类型，采用Session内部三种固定清理Mixin：失败custodian、未交付preparation、已发布assembly。无状态Mixin不新增实例存储；Protocol局部类型视图仍是同一self，未复制flags。原runtime/lease仍唯一下游，原根callback和Code错误标签保留。原Code cleanup导出保持兼容转发；共同算法由Session构造、Plugin集成与Code实际调用方共用，旧算法退出。

R2恢复的lookup屏障保持。末版side-question采用具类型的局部函数，默认值绑定当前循环项，立即传原helper执行；属性读取仍在helper try内。package lambda只用现有cast细化可选变量，不转换对象；原Code字节只因共同体删除、绑定和必要import而变。Code私有方法的定义metadata随继承改变，不伪称任意私有反射/patch兼容。

| 七源完整生产成本 | 起点 | 实际 | 变化 |
| --- | ---: | ---: | ---: |
| Code capability composer | 2187 | 1957 | −230 |
| Code cleanup兼容入口 | 28 | 6 | −22 |
| Code Bootstrap / AgentSession | 3531 / 2295 | 3531 / 2295 | 0 |
| 原Core construction | 832 | 844 | +12 |
| Session共同cleanup及Plugin清理（含Protocol等） | 0 | 291 | +291 |
| 全Coding | 125650 | 125398 | **−252** |
| 四根系统 | 637783 | 637834 | **+51** |

最终全1895源中1888同本批起点，五旧源变、两新源，所有接口/类型/兼容代码全额计入。候选+12、同对象类型修复+21、具类型回调及原本格式clean的Core construction正常格式化+18，最终+51；不以早期候选成本替代实际，不冒称净删。

验证与局限：

- 66348原源码44组独占捕获4.75s；27534迁后同44期望加5lookup为49 passed/4.00s。期望文件hash始终保持。
- 57525真实原共享构造、Plugin关闭/失败重试、LSP父子图/恢复等34节点 **34 passed/333.81s**。该批import早于后续纯类型/回调窄修复，不宣称最终字节完整重跑。
- 92613末Protocol视图版固定44加原构造节点45通过，5个提取式lookup probe因缺少真实module globals里的cast而失败。保原XML/探针，不归因Product。探针改用实际模块globals，不改断言/原期望后49388五节点通过；最后具类型回调25295五lookup加原构造 **6 passed/4.82s**。重叠节点不累计。
- 10519七源类型首检10错；同对象Protocol修复后24125仅Core construction可选lambda推断1错，其余六源不变且无错；具类型回调后42955该源通过。七显式源分批silent-import mypy通过，非首轮/最终七源整批或全依赖图证明。Ruff七源、四个本批可格式化源、生成依赖check、文档静态九项及diff通过；不把旧Code格式债伪称已清。

原三设计R1指出lookup问题、R2窄复核关闭，三个实际代码报告、同对象类型修复窄补核和真实终态补件分存树外cleanup，原失败/早期pending不覆盖。实施owner `/root`在用户已授权的P2关系内接受本完整清理子路径；其它Catalog共同准备/refresh与整个P2/Goal仍未完成，15K/系统净减条件保持。


## 12. Loader回执至Catalog输入：共同准备的完整交接

本合同延续§4的原Resource Catalog/Package Product关系，没有新增组件、环境连接、存储、Graph或来源权威。三视角设计均无具体阻断，实施owner `/root`在已获接受的P2职责内接受本内部合同后接入；不是用户对KD008联合执行图的接受，亦不代表整个P2完成。冻结设计、两源原像与候选、完整成本及报告保存在产品树外`p2-catalog-inputs`。

### 12.1 既有能力、缺口与职责

原Loader签发唯一`ResourceCatalogInputReceipt`；原`InitialResourceCatalogProductSelection/Adapter`接收已经匹配好的source specs，再由原Source/Bootstrap参与图准备与发布。原Adapter并未实现receipt的mount/fact与admission/path逐项匹配，因此不能仅删除Code适配，也不应再建Loader。

既有Resource Catalog内的[`_loader_inputs.py`](../../../../../src/loushang/harness/resource_catalog/_loader_inputs.py)只补完整输入交接。它直接复用原Package/Native/Embedded specs、VerifiedRevisionHandle、locator规范、内置capture和Product snapshot类型；不新建DTO、Protocol、注册表或配置语言。源选择、canonical来源开关、clock、作用域/冲突/类型检查、package plan编译及信任/owner政策仍由[原Code入口](../../../../../src/loushang/coding/_resource_catalog_adapter.py)提供。

内部函数接收原receipt、product/policy值、已选择的composition/snapshot/admissions、三个来源bool、disabled selectors和错误投影factory，返回原Selection；Code仍构造原Adapter并传原clock。它不是任意Product的缺省信任政策或公开兼容API。原初次/refresh、只读Product preview和local discovery共同调用原公开build入口，六个Code私有转换体退出，无fallback副本。

已逐一比较8处Plan构造：选择、继承、trust及config覆盖有实质差异，本片没有为这些政策再造统一plan builder。不得把未迁移部分直接宣称已是薄适配或P2已完成。

### 12.2 求值、数据与失败合同

Code原18条前缀语句保持：先检查输入、canonical policy与clock，校验互斥，必要时编译一次plan，读取并验证admissions及整数time，然后交接。Catalog按原次序累计composition/temporary/switch/snapshot原因→匹配package→观察user/context/project根→若有原因由原Code错误类拒绝→capture内置内容→构造原Selection。不能提前capture或把累计原因改为遇错即停。

Package helper的早退仍只退出helper；原每项admission的Product/policy/sealed/time/kind/owner/locator/唯一fact次序、可选reservation计数及未声明资源检查不变。snapshot以`is not None`区分缺席与空tuple，仍跳过legacy匹配而拒绝混入legacy输入。根的exists/is_dir/is_symlink次序、目录skill补SKILL.md、原coding-*身份、内置import path/NUL/排序路径/逐文件SHA256摘要域和disabled过滤均保持。

借用原handle，不在转换中获取/关闭lease或重开来源；后续Adapter仍在原时点独立重核归属/policy/sealed/time并承担原准备/失败清理。新helper不读clock、不缓存refresh、不签授权、不接管发布/取消/债务。三个bool来自原canonical冻结常量，不承诺任意私有热改policy或已退出helper的monkeypatch/traceback逐帧兼容。

### 12.3 实际成本及验证边界

| 两源完整成本 | 迁前 | 最终 | 变化 |
| --- | ---: | ---: | ---: |
| Code适配器 | 1094 | 725 | −369 |
| Catalog内部交接 | 0 | 410 | +410 |
| 全Coding | 124345 | 123976 | **−369** |
| 四生产根 | 638294 | 638335 | **+41** |

所有参数/导入/类型成本计入。原来只有一份转换算法，因此本片是职责迁移，不声称删除了第二份算法或系统净删。首候选Code726/+42；实际项目Ruff仅重排同一组import并去一空行，最终725/+41；非import AST及import绑定集合相同，原首帧另存。当前累计Code减13779（10.0%），距15K仍108976；系统较634794起点增3541，完整Goal继续active。

- 迁前59454实际原47节点为37过/10失败、116.13s；接入后60806为相同37原节点通过、相同10原节点失败，加16固定观察通过，共53过/10失败、78.71s。不是全绿。失败原始message有一项仅set显示顺序不同，其余相同；两份原XML保留。
- 至少一项输出直接显示测试scratch祖先中的工作区AGENTS.md被原发现逻辑纳入context；源码解释了无自身context时选择上层资源根的路径，但尚未逐项证明10项失败都由该环境造成。没有修改Product发现语义、测试断言/fixture、managed wrapper或指定runtime目录来制造通过；尚未验证环境隔离后的这10项端到端行为，不能声称它们已关闭。实际选择为shadow文件34项、local discovery 5项及rcp5 8项，不是冻结五文件的全量执行。
- 原16份有限观察采用独占写入：43409首轮14过/2个探针无效输入失败；只修正no-context的receipt前置约束和重复selector输入后，52986补两项通过，原14份未覆盖。60806对同16份全部通过；最终仅import修正后67613又为16过/5.87s。包含完整内置摘要、根身份、禁来源、错误优先级和clock次数；没有覆盖所有package/snapshot组合、native或全SDK。
- 50566候选及16540实际两显式源silent-import mypy通过，非全图；实际Ruff/format及83237原生成依赖check通过。首次实际Ruff指出import排序，原失败与纯import修正分存。

三视角实际代码与终态复核记录见[评审记录](startup-session-assembly-convergence-review.md)。不得用本片有界证据接受完整启动路径、整个Goal或掩盖上述10项原失败。

## 13. A28：双Plugin Resume parent协作归原Approval

R2具体合同经职责/复用、运行/失败、数据/兼容三独立视角后，实施owner `/root`在已授权内部关系内接受并接入；实际代码评审结论另列[评审记录](startup-session-assembly-convergence-review.md)。方法沿本地clean master `0f9bd3ff51afabeaaf76cc38dff1ceb279b7d37e`。本片不改变KD008/KD011待用户审阅的图：原Coding已经消费两个Approval Journal，未增加环境参与者、权限或Session图关系。

### 13.1 同一DTO与原owner

`CodingResumePluginParents`原两字段、own annotations、frozen/slots、构造、同intent/owner/Product校验与`_journals`绑定保持。`require_open/enroll/seal`完整机械程序退出Code，归原Approval内部`_plugin_resume_parents`无状态方法基类；空slots、不另建DTO/状态/parent registry，不采用已拒绝的字段继承或包装对象。Code保原路径/scope/writer capabilities/clock绑定及纯sealed错误值构造，Core实际调用原两个native Journal的snapshot/enroll/seal，不通过Code代理文件IO。

`_journals`的原具体类型仍在Code调用时查找，构造器只绑定和校验参数，无文件打开；实际Journal保持唯一持久事实与授权权威。Core没有可执行阶段表、新队列、跨Journal事务或自动恢复。Code中已审计LSP/Arch工厂与当前revision的settlement政策、其它startup/Resume选择均不因共享机械程序而成为Kernel默认保证。

### 13.2 顺序、部分成功与兼容

- require_open构造两Journal后，先Definition snapshot并拒sealed，再Activation；缺enrollment/其它原错误直接传播。本层不追加enroll/seal事件，**不代表整个调用无写盘**：原snapshot使用exclusive lock，可能创建lock，并按原partial-tail repair加载，均保持。
- enroll先Definition，只捕其原具体JournalError/unknown code，才按原当前revision登记；已有open不写，sealed拒绝。之后才处理Activation，后者失败保前者事实，调用方重试借原owner继续。异码和异类错误不吞，不增加回滚或跨Journal原子性。
- seal同样先Definition snapshot/必要seal，再Activation，保各自snapshot revision和原返回对象/顺序。第二owner失败不清掉第一owner已封存的事实。
- 三个原sealed拒绝分支仅改为调用Code纯错误构造，保真实Error类、message/code及原cause资格；无提前构造、IO或授权。MRO及继承方法的module/qualname/source发生变化，不能据有效签名/字段相同声称所有私有反射或旧安装pickle全等。

### 13.3 完整成本与实物验证

| 完整生产成本 | 迁前 | 实际 | 变化 |
| --- | ---: | ---: | ---: |
| Code composition | 1957 | 1887 | −70 |
| 原Approval内部机制（类型/绑定全计） | 0 | 108 | +108 |
| 全Coding | 123062 | 122992 | **−70** |
| 四生产根 | 638313 | 638351 | **+38** |

原三方法各只有一份，因此这是完整原生parent协作的职责归位成本，不称算法去重或大块净删。全1908源中只有一旧Code改动及一新Approval文件，原其余1906逐SHA保持；完整Goal距15K仍107992行，系统较634794起点仍增3557，P1–P4及两数量条件均未完成。

原业务16133整个文件9过/4.05s；原60556排他捕获58顺序/失败观察，58过/1故意跳过仅候选合同节点。候选64227为68过/8.32s。实际首53309为同68过/14.70s；首实际Ruff指出一处import排序，最终仅排序同组imports并去空行，非import AST及import绑定集合保持，最终Code1887/系统+38（候选1888/+39历史保留）。62155最终实际在原wrapper/selector与磁盘runtime、沙箱外得到**68过/9.61s、零skip/error/fail、exit0**，含58固定观察、1实际Code字段/方法合同和同9原业务，不叠加前批。

probe从真实工作树执行继承的新Approval方法，并以路径/两源SHA/co_filename守卫；原58JSON只读比较，Code own fields/annotations/slots/sizeof、有效签名/hints、原_journals/post_init及其它定义AST均核。叶Journal端口替身观察不是实际磁盘/权限/并发或所有repair分支证明，原9业务单列提供其真实Journal/Transcript集成范围；未跑旧安装pickle/native/hosted/断电/性能。1104最终两实际显式源silent/no-incremental类型、实际Ruff/format与80729生成新鲜度通过，不称全图类型或全仓绿。原Catalog十项与Session两项失败不销账。原件/两版文案/候选/实际/固定观察/XML/报告与完整切点保存于产品树外`p2-plugin-resume-parents`。

## 13. A35：完整 Session 构造路径审计与下一候选边界

- Authority: accepted design inputs / Current audit；实施 owner `/root`综合三个独立视角接受本节事实与选题约束，不接受尚未提出的接口或实施。
- Design status: input audit complete；下一完整候选须补具体接缝、全部替代成本及相应三视角设计评审。
- Implementation status: not started（A35）；A34及此前交付保持，不能把本次审计计成源码削减。
- 方法：本地干净 archmethod master `0f9bd3ff51afabeaaf76cc38dff1ceb279b7d37e`。起点为实际 A34 工作树，非仅 Git HEAD。

### 13.1 审计结论与不应重复建设的部分

`bootstrap._create_agent_session` 当前跨度 2196 行（586–2781）。三个独立视角均不支持整段迁入 Harness：它包含 Coding composition、历史与 Resume 参与者、工具/权限、LSP/Arch、legacy/fenced Product 路由等真实政策；通用执行已大量归原 owner。它很长不等于另一套可整体删除的中性引擎。

| 现有职责 | 已实际使用的原能力 | 本轮处置 |
| --- | --- | --- |
| 配置与 Agent/Session 构造 | `AgentProductConstructionBinding`、`AgentProductConstructionRuntime`、`AgentSessionConstructionRuntime` | 保持；不得把这些已经共享的算法再次计作迁移收益 |
| receipt 到 Catalog 来源及投影 | 原 `_loader_inputs`、`InitialResourceCatalogProductAdapter`、`prepare_resource_catalog_bootstrap_result` | 继续使用同一机制；不另建来源 Reader、输入事实或预览缓存 |
| 初始输入交付与失败关闭 | 原 `construct_session`、`InitialSessionResourceCatalogBootstrap` | 保原同步交付、`close_unprepared` 与错误 notes；不新增 BootstrapManager |
| 后续代际发布与回滚 | 原 `AgentProductSession._refresh_resource_catalog`、joint generation | 刷新候选只准备确切输入，不重做 prepare/publish/rollback/retire |
| owner publication、membership 与清理 | 已交付 Session Plugin lifecycle 程序 | 不重开、不再迁一次，也不把 RuntimeResourceOwner 或普通 ExitStack 当作多 claim 重试替代 |
| deferred 激活 | 原 `DeferredCapabilitySlot`、Graph Binder、component 与 owner generation APIs | Slot 已有 single-flight、shield、保候选和失败重试边界；不是缺一个通用 Slot 引擎 |

静态闭包证据：initial projection 捕获 15 个外部变量，Product projection 27 个，refresh 14 个，完整 `_create_session` 41 个。将这些原样装入大 Context、可执行步骤列表或整段 Code IO callback，会保留原耦合；不能称其为职责归一。闭包/list/nonlocal 的 Python 表示可以重组，公开参数、Header/startup wire、owner/manifest 标识与授权/失败义务不能随之改写。

### 13.2 下一候选：选定资源的初投影、交接与刷新

选择 **Product-selected 初投影→Session 输入交接→refresh/restart 拒绝** 作为下一份全成本候选。运行和数据视角优先此簇；职责视角同时建议比较 deferred 单子图 generation，但明确两者成本均未知。实施 owner 选择前者先试算，因为其复用轨迹已明确，且初投影与刷新必须一起说明，不能只搬一段 helper。

Product projection 382、错误投影 wrapper 24、refresh 202，合计 **608 个方法跨度行**；legacy initial 115 是兼容对照及可能受影响的调用者，合计调查池 723。若仅计三个操作体为 699 行，不含 wrapper。各口径不能相混，更不能将包含它们的 729 行 `_create_session` 再累计。所有数字只是调查池，**没有已证明的删除预算**。

| 责任 | 原 owner 与候选限制 |
| --- | --- |
| 请求哪些 base/LSP/Arch/外部资源、legacy/fenced/default/minimal 路由 | Coding 产品政策；配置 factory 中 Arch 私有根准备等可能有副作用，不称纯编译回调 |
| Desired、selected manifest 与 external IDs 事实查询/有效性 | 原 `PackageProductRuntimeBindingV1` 的 capture/query/assert APIs；不另建可信事实账本，不将多个原调用改成新全局事务 |
| receipt、来源选择和投影 | 原 Loader、Catalog adapter 与已交付输入转换；候选必须说明实际复用，而非把整个原闭包回借 Coding |
| 单次 Session 输入交付、代际发布、关闭与重试 | 原 Catalog/Session 生命周期；候选不持有第二组 lease/提交状态 |
| 具体错误 reason、诊断、Coding 公共参数和持久格式 | 保原领域映射与原调用位置；薄适配不能变成整块策略隐藏的执行器 |

下一设计可重新安排未持久化的准备结果表示，但必须先给每段“保留政策／调用已有能力／退出旧体／确有缺口”的精确对照。当前没有接受一个新 controller、Context、投影记录或 factory 协议；不能将上表当作已选定具体 API。

### 13.3 必须保留的完整操作合同

| 路径/时点 | 下一候选的约束 |
| --- | --- |
| legacy 初投影 | 原 peer 检查→receipt→clock/plan→base/eager/custom 分流→compatibility reconcile→投影；不借新方案重做既有 Loader 转换 |
| Product base disabled / recorded absent | 先保原 Desired 分类与 runtime 绑定，再外部资源/能力选择及准备，之后才 receipt；未记录 absent 与记录过的 absent 不互换 |
| Product base enabled | capture base manifest→clock→领域 compile→receipt→能力选择与准备；不得统一提前收集所有输入改变首错 |
| capability/Resume | requested、recorded、disabled、eager/deferred 各分支保原次序；无选定能力时的 Resume parents 拒绝仍保留 |
| 单次 adapter 交接 | `_create_session` 先要求恰一个 adapter 并 pop，再检查原 Desired；不补自动恢复 list、不静默换路线，之后由原 adapter mint/construct/失败关闭 |
| refresh currentness | 检查原 pinned base/capability/external manifest 与 disabled selection，变化要求原 restart reason；不得重新激活或默默选用新 Desired |
| refresh 捕获差异 | capability 分支只捕原 Activation/Read 错误；disabled-base 另捕 RuntimeError；base/capability/external 的 reason 仍分立 |
| 时间与来源 | compiled Product 可使用原 authority 的 evaluated_at；另有毫秒 plugin clock 与秒级 fallback，各取值位置保持，不统一时间单位或延长租期 |
| 动态读取 | refresh 重新取得 receipt、disabled-skills 与原 cwd；initial 使用参数 loader，refresh 使用捕获的原 services loader，不换对象或提前缓存 |
| `None`、空 tuple 与默认 policy | 表示不同来源路线，尤其 Product snapshot / disabled-base 分支；不能用真值折叠成同一个默认 |
| 失败与资源寿命 | 临时根、factory 与 projection 的部分失败仍由原实际 owner 清理；已获/未获 lease 不混，关闭失败保依赖及重试凭据 |
| 公共与历史兼容 | Code FQN、own 字段、exact-type、原 Header/startup wire、hash 域及旧 reader 约束保持；不重开 A16 字段继承或类 alias 路线 |

以上是源码与既有合同的设计输入，不是本轮新运行证明。固定旧行为时优先复用已存在的 bootstrap、Product 选择/撤销、Resource Catalog shadow/refresh、deferred vertical-slice 与原 Harness 构造测试；仅补新接缝的真实缺口，不扩大 gate 或平台矩阵。

### 13.4 次选和被拒绝的捷径

- **deferred 单子图 generation：** 可比较原 Session component/Graph/stage APIs 承接同对象完整 prepare→publish→dispose；Code 保 LSP requirement、exact owner、配置与 current-selection 政策。外部 class 230 行（含字段）、其方法池约 181 行；bootstrap build 116 行另有领域配置，均非删除预算。不存在已核实的现成整块替代，若只多一个 facade，应拒绝。
- **内部取消窗口：** thread 成功而内部 prepare 自身被取消时，failure-first join 可能不向 generation 交出结果；但正常 `Slot.activate` 已 shield，close 等待而不 cancel。尚未证明正常入口可达，不能称常规用户取消泄漏，更不能因此改共同 join 或新增取消矩阵。
- **workspace/sandbox 整段搬迁：** 只有一套 bootstrap 绑定，ceiling/权限/Git/provider fingerprint 有产品政策；已有 Sandbox/Process/Workspace 执行原语不能再计为新接管。
- **临时 startup 单独抽计数 helper：** 多方 claim、最后 release startup lease 后删根和失败重试有真实合同；普通 ExitStack/RunLease 不等价。规模与全成本不足以将其冒充下一完整主线。
- **更改机械身份凑行数：** 当前无需求或接受依据。公开声明跨度另核为 9582 行，仅是现布局的观察成本，不是不可变下界或 15K 不可达证明；不以此弱化原合同。

### 13.5 证据、成本和实施退出条件

树外 `architecture-analysis/coding-responsibility-goal-20261107/p2-bootstrap-complete-scenario` 固定 17 份原输入及 1911 生产源指纹、完整 closure/callee 对照、声明跨度清单与三个独立审计报告。实施 owner 已逐份读取并综合上述差异；它们是独立审计输入，**不是新接口已通过三视角设计评审**。

本轮未运行测试或修改生产源码，新增精简 **0**：Coding **121529**、系统 **638589**；A34 已过检查不重复执行。下一候选必须实际给出 Code 保留量、原 owner 扩充、类型/兼容/cleanup 的全部成本和旧体退出清单，再评审是否值得采用；不能以 608/699/723 行跨度预报“可减几百”。若候选只是等量搬运加大 callback，应记录拒绝并转向其它完整职责，而非为造进度安装。

完整 Goal 继续 active；15K/系统相对634794严格净减目标、原失败与 A33/KD008/KD011 待用户的重要工作件均不由本轮改变。本节保留既有 owner 关系，不提出或接受新的系统环境/组件图。

## 14. A36：Catalog package plan 与 selection 的完整接缝

- Authority: accepted bounded implementation design R2；实施 owner `/root`综合三个独立设计及R2差分视角接受原组件内细化。
- Design status: accepted；不新增系统环境角色，不接受 A33/KD008/KD011。
- Implementation status: implemented（有界）；两实际源逐字等R2，39固定对照及原业务失败集合保持，实际代码三视角终审完成。

### 14.1 完整操作与现成能力

从原 Loader receipt 的已发布包事实，合并原给定 seed 与 configured resource contributions，核精确修订、生成同一惰性 `ProductPluginPlanSeed`，仅 finalize 一次声明或接收原公开 custom resolver 的同 plan selection，再投影原 contribution candidates、按原 grouping 绑定 owner，交给原 Product compiler/Catalog adapter。这是§13初投影/交接/refresh的真实公共callee，**不是整个608/723行场景已经收尾**。

原Session Product装配已拥有两种Seed、证据validator和 `_complete_product_plugin_selection_seed`。Seed本身不执行receipt合并，Host只解析已给计划，compiler只消费已完成selection；不存在能保持原分支而直接替换完整前段的现成API。新增固定私有函数放在同一 `harness.session.product_composition_assembly`，直接复用这些原值、Host/PendingOnly、candidate projection及既有grouping；不新增步骤框架、manager、DTO、存储或权限authority。

### 14.2 Code政策与原owner接缝

| 原操作/政策 | R2落点及边界 |
| --- | --- |
| receipt包筛选、同修订合并、context/ref/trust/config/ceiling与Seed构造 | 原Session Product的 `_prepare_catalog_plugin_plan_seed`；receipt是原窄不可变事实，不是大Session/Product/context |
| configured-resource惰性policy值扩展 | 同owner `_extend_configured_resource_owner_binding`；Code提供原trust class，返回惰性值不授予实际admission或执行权限 |
| default/custom finalize、same-plan检查与candidate投影 | 同owner `_finalize_catalog_plugin_plan_seed` / `_complete_catalog_plugin_selection_seed`；仍调用原Host及原grouping，不复制selector/owner解析引擎 |
| 产品id、trust/policy revisions、错误及owner边界 | 原Code常量、真实source-policy/error类和 `_resolve_coding_contribution_owner` / covers判据；只给纯值/错误构造与纯领域policy决策 |
| 原公开入口 | 三个原Code typed薄函数保参数、返回注解、文档与有效hints；无DTO字段继承、alias或module伪装 |
| 原两个private适配 | `extend`薄包装和rejection helper迁后无消费者，R2直接删除及sole imports；不为无公开合同的符号造兼容shim |

公开 custom resolve 可有副作用，仍在原finalize边界调用一次，不称纯函数或缓存结果。三政策字符串和resolver/reject现在由Code wrapper入口绑定；机械globals、Host局部名字和traceback位置改变。任意同次回调内热换模块全局名不承诺等价，原Host类方法注入仍命中同一实际类；公开回调的次数、实际输出、错误及数据合同保持。

### 14.3 原接受集合、顺序与兼容

- seed类型/双seed检查仍先于receipt字段访问；空包输入在时间/flag验证前返回None。非空才按原int排bool、bool选择flag校验；不新增receipt准入或用更严类型拒绝原有效值。
- 仍按包name排序；seed contribution选择优先，configured只纳resource_item；缺包/修订漂移保原reason。context仍原replace，已有ref/trust沿原get/or复用，不误称context是同对象。
- 原source-descriptor fingerprint决定configuration覆盖集合；ceiling不扩大。configured trust已允许时返回原binding，否则保原policy revision后缀/TTL建立新值；supplied owner是否有效仍由原Code policy决定。
- default非selection保持incomplete；custom不可调用保持TypeError，custom非selection或plan不等保持mismatch；direct complete不匹配仍ValueError。plan准入为相等，接受distinct-but-equal对象，不加is门槛。
- 只投影原允许contribution kinds，再直接用原grouping/duplicate/extra/owner边界程序。真实Code DTO、公开FQN/own字段、持久Header/startup/manifest身份均未修改。
- bootstrap各route、receipt/clock/cwd时点、临时根、effectful配置factory、publication/cleanup仍原路径；本片不借callee迁移改变上层政策或声明已完成整个A35。

### 14.4 全成本、候选证据与安装环境边界

| 生产范围 | 起点 | R2实际 | 净变化 |
| --- | ---: | ---: | ---: |
| Code resource adapter | 725 | 445 | −280 |
| 原Session Product装配 | 1288 | 1638 | +350 |
| 合计 | 2013 | 2083 | **+70** |

R1为Code−263/系统+87；三个设计视角指出无消费者private层后，R2去掉17行包装/import成本，Core逐字同R1。这是完整机械操作归原owner，**不是280行系统去重**。两实际源逐字等R2，全1911生产源仅两源变化、其余1909逐SHA同A34；Code **121249**、系统 **638659**，累计Code减16506，系统仍比634794起点多3865。15K与系统严格净减尚未满足。

原观察使用真实PackageMaterializer、published packages/绑定、合法mount receipt和原Host。首76654为探针fixture缺mount造成37 setup errors；27672为12过/25探针失败（Mapping归一化及声明canonical JSON），只修探针，1183窄补25过/12 deselected，原12期望未改；21677另补真实ProductSelection与有效supplied owner身份2过。39旧JSON分批排他固定，不能称首次或单批原39全绿。

98561候选只读比较39项，**39 passed/36.94s/exit0**；真实非空plan、default/custom/direct成功、等值非同对象plan、owner is/扩展与首错均有原结果，callee用loaded路径/SHA、确切Core co_filename/profile及公开hints守卫，未用旧AST冒新实现。96328两R2显式源silent-import/no-incremental类型通过；实际结果不能由此预支。

5591迁前12个相关业务节点为**7过/5失败/139.45s/exit1**，五项均在Product资源可见性上缺review Skill。62126树外shadow为5过/7失败，含editable distribution origin不可验证/host distribution unavailable提前拒绝；该安装来源与真实工作树不等价，不能据此称行为一致或通过，亦未放宽Product来源校验。为核真实行为，按已接受两源设计进行可回退实际接入，以同12节点及39旧观察、三个既有架构边界比较；38921仍待终态。不把原失败或shadow环境拒绝抹成绿色。

### 14.5 接受范围与回退

三个独立R1设计与R2差分评审无剩余静态职责/运行/数据阻断；实施owner接受的是原seed/selection组件内部的具体接缝及上述+70成本，不是新的系统组件关系。树外 `architecture-analysis/coding-responsibility-goal-20261107/p2-catalog-plan-convergence` 保留原件/R1/R2、固定期望、红绿XML、源码帧及报告。

两源整体可回退到冻结原件，无数据/schema迁移，不留Code重型fallback。实际最终类型、业务失败集合与代码三视角仍须闭合后才接受本片交付；原五项失败、其它旧失败、A33/KD008/KD011和完整Goal范围均不由候选通过关闭。无新gate、平台、live或付费调用。

### 14.6 实际终态与有界代码接受

38921实际Root共54节点，**49 passed／5 failed／0 error或skip、116.09s、exit1**。39固定对照与三个原架构边界全部通过；同12原业务逐classname/name核状态及failure.message完全相同，仍7过/五个缺review Skill的原assert。临时shadow中两个原通过节点的提前来源拒绝未在实际Root重现；原shadow失败保留，不改写为候选全绿。此批不是绿suite，五项原失败没有被修复或销账。

47439两显式实际源silent-import/no-incremental mypy成功；79819原dependency renderer新鲜度exit0，Ruff/format两源通过。两实际源与R2字节、1911源帧和39原JSON未变。三个独立实际代码视角及终态补件逐项核对这些证据，无本片新增职责/运行/数据阻断；实施owner `/root`以树外 `code-acceptance.json`在原失败基线范围内接受本片交付。

Code121249／系统638659及本片−280／+350／系统+70保持。完整A35初投影、交接、刷新政策协作仍待收敛；下一步应先核原五项资源可见性失败的现行发现合同与fixture，再比较剩余协调候选，不将错误行为迁成新默认，也不先判定测试过时。完整Goal保持active，15K与系统严格净减仍未达成。

## 15. A37：五项资源夹具失败关闭与后续候选成本复核

### 15.1 资源根与实际修正

A36 的五项原失败来自 `test_plugin_p3_composition_choice.py` 的两处测试：四种 fenced startup 参数与 disabled-base 场景。它们创建 `workspace/skills/review/SKILL.md`，却没有声明本地 context 根。原 Loader receipt 算法从上下文祖先中选择最近含已配置 context 文件的目录；本机按工作区规则使用的磁盘测试目录处于 `/home/dev/lsspace` 下，祖先 `AGENTS.md` 会使它成为所选 Resource 根。这不是 Catalog 丢弃已选 Skill 的证据。

树外直接对照实际 `CodingResourceLoader.prepare_catalog_input_receipt`：未声明本地根时选 `/home/dev/lsspace`；同一 workspace 加本地 `AGENTS.md` 后选 workspace，**1 passed／0.67s**。据此只在两处既有测试创建 Skill 前写本地指导文件，沿用已有 Resume fixture 的项目根约定。原 Product 算法、配置、安全检查和所有断言不改；新增指导内容本身是正常上下文输入，不能声称输入字节完全未变。

正式运行原五节点为 **5 passed／31 deselected／123.56s／exit0**。整个模块原 105 条 assert AST 相同；移除两个新增写文件表达式后，整文件 AST 等原。所有 1911 个生产源的文件集合与 SHA 仍同 A36，生产精简为零，Coding121249／系统638659不变。Ruff check 通过；整文件 format-check 仍有迁前已有格式差异，不为本修正重排无关源码或冒称全格式通过。

此结果只关闭这五项夹具失败，不能反写 A36 的 49过/5失败历史，也不等于整个测试模块、原 Catalog 十项或 Store/Session 两项已通过。

### 15.2 不采用小收益的装配闭包

三个独立视角继续核原 Product 初投影与 refresh 的 608 行混合池：原 Catalog/Session 已拥有发现、一次交接和刷新联合发布；Product runtime 的 live Desired/selected-manifest 检查也已被调用。SnapshotSource 的封存字节校验不能替代 live currentness，初投影与 refresh 的首错、clock、重新授权和 restart 政策不能抹平。608 行仍不是可删预算。

对最具体的候选实际构建了完整树外替代：两条 capability 准备块共130行，收敛原临时根、配置、两个既有 preparation 和成功 cleanup 凭据交接；两种失败清理分别保留。计入局部函数签名、nonlocal、分支、返回和调用适配，bootstrap **3531→3517，仅净减14行**；按同一 Ruff 格式比较仍净减14，额外51行是原格式差异。原先40–60行的粗估不成立。

实施owner不采用该候选：少量重复减少不足以支持增加捕获多项可变状态的闭包、可选结果/cast及相应证明成本。生产 bootstrap 字节不变；候选未运行，亦未接受运行兼容。五处 receipt getter/错误投影的个位至十余行潜在收益同样不升级为下一大专项。不把少量局部抽取或把整段搬进 Harness 当作本 Goal 的大幅精简。

树外 `p2-catalog-root-and-refresh` 保原/实际夹具、直接根观察、五项XML、断言与生产帧比较及三视角报告；`p2-product-capability-state` 保原代码、完整 raw/同格式候选与拒绝理由。后续选题转向未完成的完整业务簇，必须有原owner可替代程序、旧体退出及全部接收成本，避免继续在本池轮转小helper。重要待审图、15K与系统净减目标均不变。

## 16. A38：完整延迟 Component 子图候选未采用

Authority: observed experiment and rejected candidate；不是新增 accepted Target。

本轮对§13的另一完整线索实际构建候选：原 `CodingDeferredLspGeneration` 的 prepare→publish→dispose/失败重试程序进入 Session/plugin_lifecycle 的私有机制，Code 保原十九个 own dataclass 字段、类FQN、LSP exact Tool owner 检查、Consumer access 适配和政策/身份/诊断。Slot仍独占single-flight及close/retry；原ComponentHost、GraphPlanner/Binder、owner-generation stage/commit/dispose、assembly publication/cleanup均直接调用，没有新增第二状态对象、Slot或日志。

完整源码试算为：原Code文件331行→候选Code167行，减少164；接收源新增306行，合计473，**系统净增142行**。接收成本包括广Assembly协议、十九字段状态注解、身份/requirement及八项诊断绑定、三个虚方法。旧体原来就是一份生命周期协调；底层原语在迁前已经复用，不能将它们再次计为算法消除。未发现可直接一键替换整类的现成完整入口；Slot不接管子图退役和management债务，父Session主图准备及OwnerPublication也有不同参与者与失败语义，不能强套为等价替换。

三个独立设计视角均建议拒绝这一具体形状，实施owner `/root` 采纳：职责方向合理不足以证明这层泛化必要，没有实际第二算法退出或更小固定操作的成本依据。**候选不接入、不运行、不进行代码接受**，不为未采用方案扩故障矩阵。原生产源及1911源帧仍等A36，Coding121249／系统638659，新增生产减量为零。此决定不设“每片必须净减”或“单消费者一律不能共享”的新门槛；必要职责迁移仍可说明并接受明确成本，但不能仅凭Code行数下降采用不必要的泛化。

静态观察只证明候选默认路径的机械顺序、十九字段声明及装饰器同原；未执行构造、pickle、类型或运行比较，不能冒称兼容已验证。继承方法来源/MRO、部分政策常量早绑定、私有globals注入点均实际变化。Code的绑定钩子调用 `CodingLspToolOwner.bind`，会将原owner置为已绑定，属于一次性状态命令，不能误称纯值政策或提前到Component admission之前。原Slot已隔离普通caller取消，未把内部额外强制取消的未验证窗口称作已证用户泄漏，也未顺带改共同join。

原/完整候选、builder、全成本、原字段AST比较、三视角报告和拒绝决定保在树外 `p2-deferred-component-generation`。没有新重要环境组件关系，亦未接受A33/KD008/KD011的待审图。后续不再将单一协调体机械改为泛型mixin作为大幅精简路径；需寻找实际多处程序可由原owner统一承接的完整业务簇，或先证明更小的必要机制，完整Goal范围不变。


## 17. A50：双 managed Plugin source 的 helper 候选不接入

调查完整base与有序capability两入口：`_base_plugin.py`269–478与
`_capability_plugin_composition.py`829–1028约410行；这个控制/政策混合池不是可删量。
原Authority已发布source，原Materializer负责历史binding/不可变revision重开，原PM
迁移Coordinator与Session family负责持久迁移/租约，物理算法不能再写一份。

六类差异须保：base已有安装迁移在大try外、cap逐项在try内；base新源不显式reconcile、
cap每项都reconcile；disabled的runtime/单handle与state_cleanup不同；reopen异常
catch/code不同；lease先归原局部或mapping再验证；base即时lease/runtime/state清理
并加notes、cap聚合原current_package/前缀/leases留可重试custodian。普通opaque helper
若获取lease后核验失败才返回，将使原cleanup拿不到lease，不能据相似步骤统一事务。

树外R1仅为118行未完成source-holder草稿，未继续构建caller/未运行/未安装，不算候选
通过。完整R2保原各try和custody，只抽迁移请求展开、精确replay及revision投影三接缝；
Code两个模块1082→1041、1887→1850，共−78；新Core80，系统**+2**，全部适配/类型/
错误映射已计。它虽避免主要交接风险，仍把选择/lease/投影/清理厚体全部留Code。

三独立静态处置与Root一致拒绝独立接入。原因是没有完整owner退出，给已有共享leaf
再加Protocol、stage/error factory/差异开关的收益不足，不是每片必须净负的新门槛；
也不为把+2压成几行负数继续加helper或测试矩阵。两个真实Code模块及其余全部生产源
逐SHA仍同A49，新Core未进产品，新增生产收益**0**。只有候选Ruff/解析检查，没有
mypy、运行等价或设计/代码接受声明。

原/候选/全成本/六份独立报告与拒绝记录保产品树外`p2-assembly-existing-reuse`。
结构相似度扫描仅导航，未命中不证明无重复或15K不可达。后续必须比较完整固定程序
及原custody一起归原owner的成本，或直接保留原API调用；不继续本池三个helper轮转，
不复活A16字段/alias路线，不采用KD008等待用户的重要关系图。完整Goal/P1–P4不缩减。


## 18. A51：完整双程序试装通过有限对照，正式采用暂缓

A50之后以完整原件生成R3/R3.1：base与ordered两条snapshot/migration、publish/replay、
选择、lease先持有再核验及原失败清理的完整固定程序，归原Session plugin_lifecycle
内部候选；Code仅保原政策、错误、最终assembly与失败custodian外观。不是A50仅三
helper原型，但两个不同控制流仍分别存在，不能说已去掉第二套引擎。原PM/Resources/
Session事实与会员owner本来已共用，候选没有替换它们。

三独立设计视角允许有界试验或建议暂缓，Root仅接受旧源捕获与可逆试装，不预准
生产采用。原真实Code入口在受控lifecycle/materializer/authority/finalizer叶子下，
一个pytest节点内37场景冻结JSON；独占旧期望随后不改。精确R3.1临时安装后，同一
探针1节点通过（3.31秒），核两Code/Core实际路径与SHA、两个Core入口实际执行及
借用同一原lifecycle/materializer。trial只强化group在读lease属性前必须已入map
断言，未改旧输入/观察。成功、禁用、回放错误、lease不符、base清理notes和group
失败前缀/custodian重试的有限对照成立；37不是37个pytest节点。原业务套件、真实
存储/native/完整assembly未验证，不扩大或盲重跑来换采用。

全成本为Code−201/Core+403/系统+202；同formatter结构/适配差额+208，旧base格式
贡献−6。三独立实际源码视角均未见当前有限范围具体新阻断，但最终都建议暂缓此
形状：类型/七错误标签/有效果的source、贡献、finish、failure边界尚未换来充分
共同执行与简化。Root已读三全文，采纳暂缓而非“测试失败”或“每片必须净减”。
不以压行、第三假想调用方、更多flag/phase/context为该池辩护，不计入交付收益。

已精确恢复两原Code并移除唯一新增候选Core，原1932生产源逐SHA同试装前；当前
Coding **120932**、系统**641090**，本轮生产减量**0**。临时类型镜像/缓存已按本轮
自有范围清理。源切点HEAD/origin/main均38d87db31（本轮已fetch无变化）；源码、
冻结观察、两XML、六独立报告、Root处分及前后源帧保存树外
`architecture-analysis/coding-responsibility-goal-20261107/p2-managed-plugin-programs`。
本节关闭的是候选验证与采用取舍，不关闭P2或Goal，不接受KD008/A33/KD011等待用户
的重要图，不提交/发布任何改动。后续转向完整语义重复与原调用闭包，不继续本池
helper迭代；全库精确/形状扫描仅作导航，不能推导所有重复已查尽或15K不可达。


## 19. A58：恢复首输入提交与发布边界的完整候选

- Authority: accepted bounded internal design and implementation；历史A35/A51的拒绝不追认。
- Design status: R1.2与具体R3接口经三视角接受受控接通，实际三源代码已作有界技术接受；不扩大为完整P2。
- Implementation status: partial；本节指定完整操作已接通并有界接受，初候选/失败保历史，最终三视角及两项发现关闭见末尾补记。

再次核实际构造链后，整搬2196行bootstrap仍不成立：原构造、Graph、Catalog、
Artifacts已共享，LSP/Arch/工具/信任/路由政策必须留Coding。下一完整边界选择
`SessionManager`中的resume：确定intent→stage首输入→原Artifact-aware commit→
未知结果查询/本地proof→runtime publication fence→普通append及中性后缀guard。
11份原件与20方法跨度697行已冻结，仅为调查池，不是删除预算。

原ProductTranscriptSession/Factory、committer、fixed-ID lookup、JSONL和Artifacts
是复用输入，不能新建writer、事务表或恢复队列。候选在原Transcript子系统提供
私有可选continuation profile，运行在同一个Code SessionManager与同一生命周期/
committer上；普通ProductTranscriptSession缺省不变，没有新持久schema/能力门槛。
Code保原公开类、自身字段、原wire/codecs/V1V2/namespace、Plan来源与composition/
owner授权政策、neutral-record分类、public logical query与8行publication政策。

具体接口经三视角补齐两处，而非直接照搬字段：R1.1在staged首输入优先return、
persist/unsettled之后，guarded revision/path之前调用唯一普通输入政策接点，
Code原composition-if在该点执行；不能前置到外层append。记录codec用延迟
read_session_id，保prepare_binding及exact-type先于Header读取。Code publication
仍先coding-ready后pending=False，Core没有Coding-ready字段。

R1.2选择窄逻辑只读合同，而非大量predicate callback。Core仅借原对象读取
intent/session/leaf/ancestry/opaque Plan fingerprint及原Code history分类，做原值
相等、本地branch/commit/fence；它不是默认Transcript wire，也不读Plan status/
composition/source/owner或解析coding.*、计算Code hash。Code保历史版本分类来源
和8binding identity/type/V1V2 gate；history/lookup/Plan相等不授当前执行/重试权限。
不建镜像DTO、default protocol保证或第二缓存，具体类型与全部适配成本仍须复核。

完整两源候选已生成并解析/Ruff/格式检查，23个未改类/政策/状态声明结构观察
通过。首版成本Code−600/新接收+866/系统+266，均含逻辑读口、codec/类型/原字段/
薄适配；是候选，不计落地成果。最初构建器Code helper缩进错误及mypy新增source
路径未发现属于树外输入问题，原件/初输出保留，不能称Product失败或类型通过。
真正两源类型检查仍须收尾，实际试装/兼容运行与代码评审尚未开始。

产品仍Coding120393/系统643561；原八文件非live基线168过（229.99秒），未改
selector或原断言，不能预支到候选。后续沿完整场景验证，不为此另增native/付费/
平台/门禁，也不重开已共享的物理committer。全量Goal/P1–P4/≤15000未完成。
树外`p2-resume-transcript-convergence`保原件/合同/三视角/源码候选/真实工具结果。


A58实际接通补记：具体R3两源经三视角无源码阻断后试装，原20程序进入私有
Transcript可选profile，真实Code数据类/原Factory/committer不改。类型曾发现
Plan ancestry允许None及pending回调只读，已改视图而非原DTO；十个非dataclass
私有同值默认归Core单份定义。history属性直接返回原sync/async函数，无新协程
包装。候选−622/+890/系统+268不是最终交付差额，源指纹与各阶段成本树外保留。

首次实际168项为164过/4失败，四项在执行guard前因旧Code模块基类符号缺失
报错。恢复原`ProductTranscriptSession`真实Core类的显式reexport，业务AST不变，
四项同节点复验通过；不是把Code DTO改为Core别名。原架构采用测试整模块已
恢复原件，原本临时OR兼容路线未采用，不放宽门禁。

四原架构检查3过/1依赖环：前序Goal的Worker准备类型直接导入上层Product选定
manifest，Worker只原样传回store而不读取它。现以opaque SelectedT串联原协议，
所有运行函数体AST相同，去掉反向导入；同一未改图算法复现迁前已有环、修后
无环。原失败DAG与原采用断言复验通过，另原Worker交接5过。该全局图检查此前
漏覆盖，本轮修正缺陷，不把旧环写成新Transcript profile造成，也不遗留不管。

窄复验11过（4原失败+5Worker+2架构，105.07秒），已过164未重复跑；最终6显式
实际源类型过、Ruff/格式按最终源码收尾。原初失败与全部终态分别保存，不称
原168一次全绿。最终实际Code−620/接收+888/系统+268（含Worker去依赖−2与兼容
导入/格式），Coding119773/系统643829/1949源。其它1946生产源逐SHA不变；实际
代码三视角及Root有界接受另见收尾记录，完整P1–P4/≤15000仍未完成。


A58最终代码三视角：职责/复用、运行/失败、数据/兼容各自独立核三actualSHA、
原件/候选/真实callee与同节点XML，无本片剩余已识别阻断。Root逐份读三全文并
核actual-proof与终态，接受指定continuation程序及Worker去环/原符号兼容修复，
不接受完整P2/Goal。源指纹和全部范围见树外
`p2-resume-transcript-convergence/final-code-acceptance.json`；候选报告不回写为运行
通过。全局依赖环已按原门槛消除，原架构测试整字节保留，无新/放宽CI门禁。

## 20. A59：原Session接管live恢复协调程序

- Authority: bounded internal design accepted by Root after three independent candidate reviews; actual A59 implementation accepted within the reviewed scope after 103 original runtime cases passed.
- 方法：本地干净archmethod master `0f9bd3ff51afabeaaf76cc38dff1ceb279b7d37e`。沿用户已接受P2/KD009职责方向，不新增环境关系/公共协议或权限。

A58补的是原Transcript的固定ID提交/unknown/可读证明；本片补同一AgentSession中
Graph候选、首次输入准备与提交、当前发布检查、发布及一次驱动的完整固定程序。
新私有[Session profile](../../../../../src/loushang/harness/session/_resume_continuation.py)
直接继承原AgentProductSession，Coding AgentSession选择它。默认其它Product路径
不新增恢复门槛；不建controller、delegate状态、writer、队列或恢复引擎。

Core仍直调原candidate Graph、Prompt、evidence Router、Transcript continuation和
Host committed-input。Coding保两个真实DTO及其own fields/FQN/slots、当前selection、
receipt/原namespace fingerprint、input digest、owner claim/退休回执、Worker effect
准入、turn Tool激活与desired标记。只读Protocol借原对象；工厂仍造原Code类型。
两极小政策点保持独立，以保存tool激活→current重验→Manager publish→保存同一
publication→desired标记次序，不能为压行合成提前回调。

八状态只有同self一份，原构造点同步初始化，原实例Lock不共享。Graph await不跨
Writer operation scope；candidate基础可用性明确取原AgentProductSession，不取尚
受publication fence限制的Code readiness。preflight/commit/dispatch claim及各自
try边界、evidence丢弃、unknown不自动重放、Host claim内复查和单attempt options
的finally恢复均沿原程序。selection/claim/digest用同步薄绑定保持原动态查找。

七方法原跨度283不是净删预算。完整实物Code−194/Core+485/系统+291，含全部接口、
工厂及格式；Code119579/系统644120（1950源），其它1947旧生产源逐SHA同原点。
这是职责迁移，不称算法去重。四个原test仅同步派发状态观察属性名，40个assert
保留；coordinator仅一个candidate读点更名，正规化后整AST相同。私有MRO、方法
定义module及八状态字典键改变，不承诺任意反射/旧AgentSession pickle ABI。

三视角实际代码静态审查无所见本片阻断；原架构4项、实际3显式源mypy、Ruff3源和
format2源通过。加载见证只证明实际类/七方法和原DTO，不曾构造Writer或dispatch。
原22项迁前对照通过；实际六文件103项通过（640.70秒，exit0），包含原22同节点。
Root读三份实际代码报告并核完整XML后有界接受本片；详见
[执行记录](../coding-responsibility-convergence-progress.md#a59原session的live恢复完整程序接管)。
这批103在主线同步前完成；随后合入main四提交，A59三源及维护后的测试逐字不变，
两个AppHost重叠文件另按上游类型名/导入归并，24项专项集成及两源类型/Ruff
通过，代码字节与验证范围分别保存。
不增加门禁/平台/付费覆盖。完整P1–P4与15K目标不因此完成。

源码/原件/三阶段独立评审/类型修复和全部证据存产品树外
`p2-live-resume-convergence`；`actual-proof.json`区分当前安装与待验收状态。
