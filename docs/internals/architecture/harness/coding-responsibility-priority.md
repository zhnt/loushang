# Coding剩余职责实施优先级

## 2026-11-18 阶段交付后的候选评估

后续任务分支已合入 main `f3e75c93b`，包含历史源提交 `06eba4e85` 和当前 Provisioning 候选，Coding为442份Python源码、100,763物理行。上游新增8份文件及其它功能增长单列，不计入 C07 迁移收益。此前要求的阶段交付及本地同步已通过 PR #898/#899 完成；下列整体迁移顺序仍是候选建议，未启动 C13 等新组实施。原 C07 Goal 继续，当前13,104行，距离多数退出仍差2,972行，本批尚未合并，整组未完成。

排序依据是剩余完整机制、已有owner可接管程度、旧流程退出、系统净成本和兼容／验证负担。组行数仅表示审计范围；原型必须计入所有Code适配和Harness增长，不能预先承诺迁移行数或比例。

| 顺序 | 当前范围 | 首个完整候选链 | 已有能力与保留边界 |
| --- | ---: | --- | --- |
| 1．C13 LSP | 21文件／5,228行 | 协议初始化与有界请求→文档版本同步→运行实例诊断替换→退休释放；先核`client`、`supervisor`、`documents`、`diagnostics`、`positions`五文件，共1,278行，包含必要保留代码 | 已有JSON-RPC传输、`ProcessClientSupervisor`和授权启动／Workspace读取。保留Coding服务器选择、Plugin准入、只读／批准边界、Tool呈现与必要名义类型；原传输和进程寿命不重复计益 |
| 2．C04 Continuity | 2文件／2,809行 | 配置源获取→启动重放→准备／发布→失败交接 | 复用Continuity staging、binding lifetime、Plugin Management与RuntimeProfileBinder；Code保来源／限额／cwd和canonical restore政策，已共享shutdown／Task不重计，保真实Path／FileCopy／引用支持 |
| 3．C01 启动／Plugin／资源装配 | 22文件／12,145行 | 选一条准备根保管→审批／选择→构图→发布／失败交接 | 复用`PreparationRootCustody`、`SelectedProductPreparationScope`和原Construction／Product composition；Code保组合集、信任、模型／工具选择及Profile。不能把大`bootstrap`整体当机制，先前接口税过高的原型不重做 |
| 4．C10 Product runtime／C02托管接入 | 分别5,185／9,175行 | 剩余freshness／open／repair／release或普通／Resume交接 | 分别接既有Package Product／Session／Transcript或AppHost owner；已共享Catalog读取、factory release、托管进程控制不重计，不把AppHost职责塞进Harness |

首选C13的具体依据是：[`LspClient`](../../../../src/loushang/coding/lsp/client.py)已继承原[`ContentLengthJsonRpcProcessTransport`](../../../../src/loushang/harness/workspace/process/json_rpc.py)，而握手、LSP请求和协议关闭仍在Code；[`LspServerSupervisor`](../../../../src/loushang/coding/lsp/supervisor.py)已复用原[`ProcessClientSupervisor`](../../../../src/loushang/harness/workspace/process/supervision.py)，剩余文档／诊断关联可以沿同一实例审查。应由共享协议层承接完整链，不新增第二套传输、进程注册或生命周期管理。Harness当前通用DiagnosticsService是运行诊断服务，不能仅凭名称相同就替代带文档版本的LSP诊断收件箱。这个候选仍需端到端成本原型和兼容验证，尚不构成新增LSP组件的接受记录。

C08／C09的归档、恢复、接受事务已有共享owner，余量应优先证明具体旧流程可退出；C11／C12包含真实语法、呈现、仓库检查和评审政策，不按整目录行数排序。C07继续保留未完成清单，不能依靠字段搬运、压行或薄转发达到多数目标。

## 历史优先队列

以下保留2026-11-15的排序和当时“收尾交付后暂停Goal”的交付说明，供追溯；它不控制本轮状态，也不表示本轮收到新的暂停指令。

2026-11-15，按用户要求优先完整可迁移职责。排序依据是实际尚未共享的操作体、现有
owner能否完整承接、旧实现退出和全部适配成本；目录行数只作审计范围，不作可删除预算。
当前计量见[逐文件清单](coding-responsibility-inventory.md)，完整P1–P4范围见
[剩余责任账](coding-responsibility-remaining-audit.md)。

2026-11-15补充准则：优先直接复用已有组件，系统净减优先；若完整职责归属改善，
可接受必要且适度的共享通用化/Code适配增量，不要求必须另有重复机制退出。
历史否决保原证据；接口税过高、Code不减或未接完整旧体的实证仍有效，不能只因无去重
重下结论，也不按新准则机械重跑全部原型。

## 当前执行顺序：先完整大块，再局部精简

用户2026-11-15要求大块可迁移优先。下表列本批交付和剩余大块设计/成本审查队列，
不是已接受实施、预计删行或把目录换owner；验证无新完整接缝时跳到下一项，不回填字段小项。

| 顺序 | 完整交付边界与源码审查池 | 现有接收组件与Code保留 | 先解决的问题与退出条件 |
| --- | --- | --- | --- |
| 本次 A219整形不采用 | C07四源2460行池；Windows payload完整358span族及唯一mint registry试型 | 原PackageProduct attempt/authority；Code保名义/产品恢复政策 | 全税Code−228/Core+451/sys223 raw=uniform，8roles/7T/wide profile不值；1视角支持有限old-first、2建议整拒，Root整不采，无生产收益/pytest0 |
| 当前交付边界 | 用户要求完成本批后commit/push/PR/merge/sync local再暂停goal | 已接受A218及此前任务提交；A219仅拒绝记录 | 不开启下一批；必须验证发布/合并/本地同步后再标暂停，不提前称Goal完成或已暂停 |
| 已完成 A218 | C03整个应用级Transcript四操作绑定 | 原ProductTranscriptSession；Code保两个实际factory引用和配置/Resume政策 | Code−34/Harness+52/系统+18 raw=uniform，原/新同序111全过；16观察含在111内，0新T/Role/Task/gate，整C03未完成 |
| 已完成 A217 | 普通/Deferred Hosted完整审批展示与撤回两程序归一 | 原AppHost；Broker/Resolver权威复用，Code保原map接入与reply/close政策 | Code−58/AppHost+72/系统+14raw（uniform−75/−3），旧新89过/1原skip；32观察含在89内，非raw系统净减 |
| 已完成 A216 | C02 deferred control完整订阅/事件/激活委托/close-retry及同对象四状态 | 原AppHost Session control；Code保binding/identity/settings/model五政策成员和2纯profile | Code−82/AppHost+108/系统+26，uniform−84/+24；46不同节点/API/八旧观察通过，0新Protocol/T/Task、基类identity hook全计，非系统净减 |
| A215完整形状不采用 | C01捕获资源族169行池及external-only投影，完整五源原型 | 原Records/Snapshot/Session均接完整程序；Code保公共字段/工厂/错误薄桥 | 全税Code−111/Core+276/系统+165 raw=uniform；4roles/1T/3接收面分散，2视角价值否决、1支持有限old-first；Root整拒，生产收益0/pytest0，不救小片 |
| 已完成 A214 | C01三路线双root/preparation/legacy启动标记及outer失败消费 | 原Construction与cleanup family；四字段单一holder，Code保领域配置/工厂 | Code−86/Harness+139/系统+53，uniformCode−84/sys55；原202/14与九旧观察齐，实际202+24交集1，225不同节点过 |
| 已完成 A213 | C01两Product preparation253行的完整中性custody/第二capture/lineage/recheck | 原PackageProduct selected-revision family；Code在with内保领域体与nominal factory | Code−33/Harness+94/系统+61 raw=uniform；1T/0Role/所有薄口全计，实际验证见执行记录，不称全部253行迁出 |
| A209完整历史形状不采用 | C02三binding/source类+四catalog历史入口，并包含稳定snapshot读完整四源 | 原AppHost canonical family/Transcript源，Code保历史投影/名义构造/17公开方法属性入口 | 全税Code−20、接收+339、系统+319（uniformCode−38/sys301）；四源shadow静态过但成本不值，不安装/不跑矩阵，不摘close/fence |
| 已完成 A210 | C08 Windows retention snapshot原110行完整程序 | 原PackageProduct完整读/GC/目录/历史证据custody；Code保DTO/codec/构造薄绑定 | Code−72/Harness+151/系统+79（raw=uniform），原91/边界71及另31旧观察同；A184历史拒绝保留，不称去重 |
| 已完成 A211 | C01 managed Base208与Capability198完整装配池 | 原PM assembly直接执行两固定程序；Code保准入/领域选择与profile | Code−235/Harness+401/系统+166（uniform172），3roles/4T/错误数据与所有薄绑定全计；最终测试范围见执行记录，不计406为删行 |
| 已完成本批 A208 | C13/C14两完整reserved Tool owner准入/绑定/capture | 原Session tool_owner_binding，保Code五字段/域Consumer/工具工厂/nominal family | 六操作实例合三共享程序，Code−72/Harness+88/系统+16（raw=uniform）；原注册/释放机制复用不重计 |
| 已完成本批 A207 | C01公开SDK default完整137span三方法 | 原PM assembly及same desired/management；Code保原12字段/名义class/8profile事实 | 32次CAS、latest-own历史、command提交及部分commit原样；Code−128/Harness+181/系统+53（raw=uniform）；非活跃Base路线、未重造A51 |
| 已完成本批 A206 | C10完整factory/release家族，原3类8操作实例 | 原Package Product local Wheel runtime；Code保名义dataclass/Selection政策/构造桥 | 8→7实际执行体，两Worker lookup归一；Code−63/Harness+114/系统+51（raw=uniform）；原native机制与A155不重计 |
| 已完成本批 A205 | C11受管命令完整run/close/probe及native退出，原829行 | 原AppHost managed组件；Code保准入/选择/输出/UI/既有Runner | 39同self字段、8完整程序接入；Code−147/AppHost+439/系统+292（uniform192），原引擎不重计；A193静态拒绝保历史 |
| 已完成本批 A204 | C07完整双平台receipt authority及相邻Windows opt-in，13源 | 原Package Product/History/Windows Records/native readers；Code保DTO/codec/constructors/policy与八公开门面 | 按新准则接受完整职责价值，Code−514/Harness+944/系统+430（uniform+432）；五journal门面真实复用Core，原native机制不重计；A178历史静态拒绝保留 |
| 已完成本批 A203 | C02共享连接配置完整read/mutate/write/list，原173行文件 | 原AppHost client navigation与原Harness Config writer；Code保平台/临时工作区/请求政策与五公开绑定 | Code−107/AppHost+123/系统+16（uniform+14），无新对象/Role/T或gate；原40及另7局部对照通过，A149原writer不重计；Rust入口仍独立，不称Python dead |
| 已完成本批 A202 | C02完整多workspace集合协调，原183行文件 | 原AppHost canonical integration、WorkspaceRegistry与child Transcript；Code保构造/历史/平台/open政策和薄回复 | 同一实例完整接管集合/路由/retirement，Code−85/AppHost+170/系统+85（uniform+52），无新manager/Task/lock/gate；原native IO不重计，client_settings已有writer不再迁益 |
| 已完成本批 A199 | C09旧安装review→acceptance→binding catalog→source消费及崩溃恢复；原local_acceptance542/source_consumption397/binding_catalog391，共1330行原审查池 | 原Package Product/Resources、Journal/Config；Code保历史格式/产品支持范围、操作员选择与精确领域复核 | A199已完整接管accept/reopen/consume/consumed原双锁/parent身份/发布、prepared/settled重放、Settings事务及live source CAS；Code−340/Harness+480/系统+140，原74项实际过。1330并非迁出量，原分类/准入保Code；binding catalog已有_LegacyLocalSourceCatalog直接复用，A168已共享的Wheel重捕获不重做计益 |
| 已完成本批 A201 | C05 durable canary control Journal，567行完整文件为审查池 | 原Harness Journal持锁/严格读写；Code保G10启停/代际/历史/准入、路径与名义记录 | 已接完整neutral Journal scope，Code−148/Harness+284/系统+136，原34与另5本地对照过。Code状态/代际/历史仍原权威，scope保全部FNF/consumer异常差异和跨run锁；无新gate、无leaf IO重复收益 |
| A200完整形状不采用 | C03 Plan→隔离Writer→V1/V2 attempt→首输入commit→runtime publication及失败custody；continuation486/SessionManager783/activation_plan400，共1669行主要审查池 | 原Transcript/Session/Resume effects；Code保composition选择、授权和版本化产品记录 | 四源整原型raw Code+4/Core+277/系统+281，统一格式Code−54/系统+223；十个必要域/creation口及typing/facade税过高，无第二机制/依赖退出，不采用/不runtime/不摘fence。原97非pure领域构造保Code且寿命已Core，不重计397 |
| 后续条件设计 | C01/C15装配交接；先比较原Base/Capability两完整函数406行，不将bootstrap3626当预算 | 原Construction/Resources/Session | A183确认与A112同源，A51系统+202形状仍拒绝。只有新的完整事务接缝能显著减少适配才重开；无新接缝则继续下一未处置簇 |
| A205已接受 | ManagedMuxCommand完整驱动 | 原AppHost；Code保选择/输出/UI与既有Runner桥 | 13个值/效果/UI/Runner端口与2T/2roles全计，固定Core程序真实执行、无第二command/Task/state；A193历史不覆盖当前采用状态 |
| 后置 | 字段声明、薄公开adapter、prompt/profile | 保当前领域内容和必要兼容入口 | A196/A197已接受收尾；C19四源440行按A198源核执行已Core，不继续以局部十几行精简替代大块主线 |

A199已完成第1项的接受/消费固定事务，保原领域政策及catalog绑定；不是整C09完成。
A200已核完整outer handoff四源形状，所有适配后Coding raw+4/系统+281（uniform−54/+223），
静态通过但整形价值不足，不安装/不测；不是C03保留成本下界，也不重试同形参数压缩。
A201已完成C05中性lock/store整接缝，G10启停/代际/历史政策仍Code；实际Code−148而非567。
A202完成新原集合协调接缝，原183不是迁出量；Code保98行实际领域/兼容成本。
A209已实作完整历史custody/reader四源形状并按全税拒绝；不把其196行方法池作迁出预算，
后续先核下一完整Windows retention读，再从剩余完整职责选择，C01同形仍条件暂缓、A200不重试；不以小timeout/字段片代主线。
可迁移性排序优先于名义行数；完整剩余责任账中其余簇仍开放，不被本队列排除。

排序先比较能够整体退出的旧操作体和真实复用，再比较全部适配后Coding及系统的净值；
失败/取消/重试和资源交接必须一起替换。最近A171、A173、A174、A176合计Coding−680、
生产系统+422，属于职责收敛，不能作为系统净精简的证据。A179另Code−128/AppHost+224/
系统+96；A180完整前台控制另Code−116/AppHost+275/系统+159（统一格式+137）。
A181再Code−116/Harness+268/系统+152；A182再Code−76/Harness+115/系统+39；A185再Code−13/Harness+41/系统+28；A187再Code−88/HarnessWork+138/系统+50；A189再Code−71/Harness+102/系统+31；A190再Code−83/HarnessTUI+124/系统+41；A195四consumer整guard去重Code−29/Harness+21/系统−8；A196六流字段契约去重Code−46/Harness+12/系统−34；A197四类字段契约再Code−39/Harness+7/系统−32；A199完整接受/消费事务Code−340/Harness+480/系统+140；A201完整Journal scope再Code−148/Harness+284/系统+136；当前Coding107998行，距15K尚92998行，仍须按完整工作件推进。

| 顺序/状态 | 完整工作件 | 接收者及Coding保留边界 | 进入条件或实际处置 |
| --- | --- | --- | --- |
| 已完成 A171 | LSP进程传输完整生命周期 | 原Process拥有buffer/锁/Future/reader Task/request/cancel/close；Code保LSP初始化、诊断、服务器请求与优雅握手 | Code−274/Core+391/系统+117；126项通过；属于职责迁移，不是系统净精简 |
| 已完成 A173 | 配置兼容发布完整authority | 原Config LegacyProjection owner承接cache/issuer、writer与projection注册、聚合、Condition/deque、逐请求receipt和异常结算；Code保存量迁移政策/领域capture、guard和薄profile | 整物Code317→159（−158）/Core+246/系统+88；原135及固定旧29项覆盖通过，保持5原平台skip；不复用异常合同不同的普通Config通知队列，属于职责迁移 |
| 已完成 A174 | 根运行时关闭及Continuity完整绑定寿命 | 原Session Runtime接根关闭/两drain，原Continuity接composition/reservation/Task/identity-delete；Code保领域DTO、准入与薄profile | Code−153（含1行导入布局）/Core+301/生产系统+148（统一格式+139）；320项通过，持久55重放另验不重复累计；该片未含子Session113，后续见A176 |
| 已完成 A176 | Session profile完整失败保留链 | 原AgentProductSession接完整113退休程序，实际Slot/Registration/Publication/Assembly/Graph/Sandbox直接复用；Code保六字段/诊断绑定及两个纯状态hook | Code−95/Core+164/系统+69；原Core关闭Task/cancellation wrapper保原晚调用；BaseAssembly.close19仍Code，不据此关闭C01或C15整组 |
| 已完成 A179 | Hosted Continuity完整准备及失败清理 | 原AppHost Continuity共享两actual attempt的固定open/close；原Core ownership接完整清理，optional callers显式供应原join；Code保准入及薄profile | Code−128/AppHost+224/系统+96（统一格式+95）；原78+固定22+Core缓存1+既有join10过，原A0/G12–G14架构33项。两scope/14slots/失败债务保留；未关闭C02/KD011整组 |
| 已完成 A180 | G17 foreground CLI客户端完整启动/交接/关闭及Runner恢复 | 原AppHost optional integration接唯一控制状态，复用原launcher与terminal；Code保argv、准入、公开门面及两UI绑定 | Code−116/AppHost+275/系统+159；原135+旧观察6共141不同项过，显式portable6另重放不重复计。无另一算法退出，不称净精简；未关闭整C11 |
| 已完成 A181 | C13 LSP Supervisor完整实例寿命 | 原Process supervision显式子模块拥有同实例10事实，Code保LSP构造/initialize及状态诊断政策 | Code−116/Harness+268/系统+152（无格式差异）；原97+旧观察6共103不同项过。10hook/4T/2roles全计，无第二FSM退出，不称净精简或整C13完成 |
| 已完成 A182 / 仅中性投影闭包 | C10 Catalog→typed selection/admission/bundle evidence | 原current_preview直接使用既有Catalog/Input/Admission/Bundle与DTO；Code保产品选择/编译/open及中间复核/最终profile | 原84行两投影完整退出；Code−76/Harness+115/系统+39，35不同项过。单producer无第二算法退出；不是whole preview/open或整C10完成 |
| A183已核 / 当前形状暂缓 | C01 managed Base/Capability装配 | 原Resources/PM/Session机制已直接使用；剩余完整选择和失败custody仍在Code | 两完整函数208+198及整文件与A112逐字同；现有owner没有新整入口，不重做A51系统+202形状。重开须有不同整事务接缝及全成本 |
| A184完整原型不采用 | C08 Windows保留快照110行 | 既有PackageProduct backup family的stateless完整读入口；Code保实际typed/profile绑定 | 全税Code−72/Core+151/系统+79（raw=uniform），静态通过但无第二算法/实际依赖退出，不安装/不oracle；C08仍开放 |
| 已完成 A185 | C08 POSIX删除checkpoint | 原PrivateDataDeletionJournal完整27行phase统调，Code保确认/Desired准入和三窄绑定 | Code−13/Harness+41/系统+28（raw=uniform，含Code doc+1），同原14实际回归过；无新roles/T/锁，不重计physical remove或Windows去重 |
| A186已核 / 不造整类原型 | C12 Repository Goal command facade | 原Goal/Work/Delegation已接实际执行和取消；Code保trusted verification/review政策 | 204类/195方法/7methods完整核完；没有新Task/IO/关闭链可退出，busy与Core门控不等价，不摘busy helper或用宽政策callback整搬 |
| 已完成 A187 | C12 CodingGoal资源寿命 | 原Session Goal同self拥有18字段/9完整程序；原Scope Task/stages复用，Code保2SDK叶/tasklabel与领域准入 | Code−88/HarnessWork+138/系统+50（uniform42），同原163实际过/7deselect，1role/0T；Ctor私序/MRO/帧差异明示，C12仍开放 |
| A188已核 / 不重造A38 | C13 deferred LSP generation | 原Slot/Component/Graph/owner-generation/assembly机制已直接复用；Code保LSP选择/准入与原协调 | 19 own fields/230类/181方法；5源同throughA63生产切点，Process新API未替本层整路径。A38原型缺失，+142仅历史账，不假重新实核或该类不可迁 |
| 已完成 A189 | C12 workspace observation | 原Workspace Git家族；Code保GoalError/预算/消息与薄公开入口 | 两完整64/20程序退出，Code−71/Harness+102/系统+31；原118实际过，保不同观测合同，无第二算法退出 |
| 已完成 A190 | Screen SDK预热完整寿命 | 原HarnessTUI screen application host同self接timer/可见Task/切换/缓存/提示/关闭；Code保SDK政策及薄门面 | 六完整程序84span/8字段，Code−83/HarnessTUI+124/系统+41；130不同项129过/同1旧G11失败，无新gate，AI importTask不重计 |
| A191完整原型不采用 | systemd JSON控制/状态及通知信号寿命 | 原AppHost optional deployment adapter；Code保CLI/unit/错误与路径命名政策 | 两完整37+33程序全税Code−56/Core141/系统+85（uniform67）；逆AST/静态过但无第二机制或整依赖退出，短外壳税不足值。不安装/不测，不拆helper，非whole171/backend |
| A193历史拒绝 / A205已接受 | ManagedMuxCommand资源/失败完整驱动 | 同self接完整run/close/probe/原生父资源；Code保准入/选择/输出/UI | 全税Code−147/AppHost+439/系统+292（uniform192）；A193旧静态拒绝保留。A205按完整职责与必要增量准则接入并验证；13端口/2roles/2T均计，不重复计原机制，不判领域下界 |
| 已完成 A195 | 四消费者完整workspace身份协议 | 原Workspace.paths；Code保错误工厂/薄入口，原字段不变 | 原66span四kernel归一，Code−29/Harness+21/系统−8；原34实际过，不合CLI captureNone/Windows短路异合同，无新state/Role/T |
| 已完成 A196 | 六Windows semantic record中性字段 | 原Core空slots/schema基类；Code保原physicalslots/FQN/profile/peer types | Code−46/Harness+12/系统−34，原212实际过；constructor/fields/ownslots/wire/12旧pickle原期待不变，ownannotations/ClassVar字段dict演进有界披露，不增加DSL或影子槽 |
| 已完成 A197 | 四类中性record完整字段契约 | 原Core空slots/schema-only；Code保7名义类型覆写及原公开值类 | Code−39/Harness+7/系统−32，原1138实际过；37重复声明退出。另25类209字段有原ownannotations固定观察，不硬套 |
| A198源核 / 降低迁移优先级 | C19 compaction四源440行 | 四完整执行操作已直接Core，Code保266行内容profile与公开绑定 | 未发现新的整运行机制可退出；不造partial改公开签名，不计新增收益，不作永久保留下界 |
| A204已接受 / A169、A178为历史比较 | Worker Product完整收据authority | 原Package Product/Resources；Code保政策、验证与兼容DTO | A178原13源静态原型−512/+944/系统+432的否决保历史。A204按明确新准则核必要接口税，并将五Code journal门面接实际Core，完整−514/+944/系统+430（uniform432）接受；并非仅无第二引擎就永久拒绝，也不重计原native/History |

G17与C13本批实例寿命、C10两段中性证据投影已完成；后续核实顺序为：
**C09接受/消费固定事务按A199完成；A200完整Resume形状按成本拒绝，C05中性持锁/存储整链按A201完成，余大块继续重选**；A197已完成四类契约，停止连续挑字段和薄适配器作主线。C19按A198降优先级；固定ownannotations不能直接套A196。A188子图原接口未变；A187完成Goal寿命，A186命令门面无新替代；
C08 checkpoint按A185完成，
C01按A183暂缓，
Windows完整快照按A184全成本拒绝，systemd两程序按A191完整原型拒绝；
这是进入完整接缝验证的顺序，不是已接受迁移或
预计减量。A182确认preview/open其余主体为Code产品政策及既有Core IO接入，
不以厚compile/open回调强搬；A183实证C01与A112原件未变，不自动重试同池；C08先剔除已经共享的
restore/archive，不能再计搬迁收益。
Worker两次旧原型的否决保历史；A204已按新准则完成完整authority接受，其余Worker政策/平台工作仍按实际接缝排序。

其它较大操作体按下表保留比较；有阻断的范围不是排在小项之前无限等待的实施任务。
A178历史上完成Worker新接缝成本决策并拒绝接入；A204已按明确新准则完成接受及实际对照，非永久暂缓。A179曾完成202行审计范围的
完整prefix替代；A180完成foreground整控制，A181完成C13实例寿命，A182完成两段证据投影。
A183确认C01原成本阻断，A184完整快照形状不采用，A185完成POSIX checkpoint；
A186明确领域命令，A187完成Goal具体资源寿命；A188据当前及历史生产API不重启
A38同形原型，A189已完成两条Workspace实际IO观察完整合同及全成本，A190再完成Screen SDK整寿命，A191 systemd两条完整native程序全成本不采用，A193完整ManagedMuxCommand驱动当时不采用、A205重核后已接受，A195多消费者真实重复已消；A196六流标准字段契约已接受，A197四类已按真实注解/旧数据合同完成，后续改按大块混合职责重新排序，
不按目录总量承诺迁移收益。

A178核对A169最终原件确认，其POSIX authority已经继承ReceiptHistory；直接继承本身
不是新方案或收益。待比较的是实际初始化/新鲜历史读取绑定、Windows原Records公共
操作与构造、泛型不变量，以及双侧facade/profile的全部成本。原Code薄构造可以保留，
不为迁出几次字段赋值再增加一轮初始化回调；必要读取顺序优先于减少参数数量。

| 核实顺序与较大比较范围 | 当前完整范围实数 | 已有复用与不能立即迁移的原因 | 重新进入条件 |
| --- | --- | --- | --- |
| A183核实后暂缓 / C01 managed Base/Capability装配 | 两完整函数208+198=406行，函数/整文件与A112逐字同 | Resources、PM、Session已共享；try边界、显式reconcile、禁用关闭、replay异常和lease先持有/失败custody仍不同。A51完整形状系统+202已拒，无新整入口 | 原owner提供有据且全成本更小的整事务API；不恢复阶段回调Context，不把当前bootstrap3626行作可删预算 |
| 5 / C08私有数据三类owner | 三类合计549行/方法510：Read195/172、Restore170/161、WindowsBackup184/177 | 原DeletionCoordinator、POSIX archive及Windows事务已共享；RestoreOwner.restore83行已调用Core完整restore。31源扫描所见直接native调用多为路径/身份检查，不是未迁物理事务 | 先证明一条尚在Code的完整事务及窄codec边界；整组仍开放，不按当前6665行整包搬迁 |

A182审计原preview271/open122与462方法行：只有84行Catalog身份连接和admission/bundle
投影可在不吞Code编译/信任政策、无厚IO回调的前提下整体交给原证据owner；其余保留
并非最终不可压缩下界。完整字段/clock/复核顺序保留，不据方法总量承诺整类减量。

A181核对A38原件：其拒绝对象是另一类`CodingDeferredLspGeneration`延迟子图，
不是`LspServerSupervisor`。前版将该决定紧邻C13描述，只能表示泛化适配成本的风险，
不能作为当前Supervisor曾被拒绝的证据。本类已按A181独立完成完整接缝与成本验证。

A184已完整试算Windows snapshot110，保GC/Desired/state pin/staged debt/reappearance、
原FD关闭和晚权威/hash后，全接口税系统+79；没有第二机制或实际依赖退出，未采用。
不直接并POSIX snapshot63，也不摘小status切片挽救。expiry recovery102及preview91
仍主要是产品授权join，底层复制/rename/收据事务已Core，路径/身份读取仍在Code原点。
A185已完成POSIX delete_confirmed52中原27行checkpoint的Journal接管；Code准入/offline
和三个原窄端点保留，完成用terminal renamed。既有remove_started与restore83不重计；
Code净减13不是27，C08整组仍非最终领域下界。下一C12需先区别原Goal/Work协调与
Code领域verification/review准入；A117 cold事实已有owner，不重新搬迁或计益。

上述类/方法范围有包含关系，不能相加作可删量。跨簇扫描覆盖434份当前Code源码的
长函数/owner导航，并深核表列实际程序及Core调用，不等于全树语义重复证明或领域下界。
A179/A180/A181按不同完整接缝接续交付，不将其包含范围相加作可删预算；803方法行
Worker不同接缝已作完整原型并因全部成本不足以抵相称复用而拒绝，不承诺直接搬走
803行，也不回到零碎helper。

A175实查已确认activation policy/receipt/witness及多数manifest/candidate事实早已Core；
仅换剩余DTO不能消掉A169完整authority接口成本。A178曾连具体journal/最少中性facts、
generated/duck reader及整Windows opt-in事务作完整比较并保外部。A204在新价值准则下
将完整形状接入，并让五journal门面执行Core公共体；原A178历史证据不改写。

不再排作待整池搬迁的范围：A170核查的inventory/snapshot712行，其root/bundle/member/
list/recheck/finally已由SnapshotEvidenceStore拥有；Code保存量分类、支持政策与新鲜度时点。
A173核查的HostedCatalog943行，其canonical list/open/create/discovery/candidate custody已
在A80–A85的AppHost/Transcript实现。两者仍有未处置边界，但不能重搬或重复计益。
A172对C01/C15/C17共15720行的调查同样确认主构造、Task、Slot和历史读取寿命已共享；
没有证据可把整组判为可删除或永久保留。

每项先核真实消费者、旧操作体、失败/取消/重试/恢复与资源结清，再作完整替换。窄政策
接口可以保留，但Code领域capture/guard回调不冒称纯函数，也不把已共享IO重计为本片收益。
没有已证明可直接承接的更大完整替代程序时，继续设计下一完整接缝，不填虚构的大块
承诺，不连续以局部十几行去重替代主任务。

C04 Continuity的KD003、托管历史KD011等明确待确认边界保持原状态；其余C05/C06、C08、
C10、C12–C28继续在责任账中，不因排序退出P1–P4。领域能力、内容与产品政策换目录后
仍计Coding归属成本。未建立≤15K不可压缩下界；每批报告Coding、接收组件、兼容适配和
系统源码净值，新增测试/探针另列。完整Goal仍以领域化及≤15000行为验收条件。
