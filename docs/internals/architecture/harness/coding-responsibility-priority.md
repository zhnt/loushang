# Coding剩余职责实施优先级

2026-11-14，按用户要求优先完整可迁移职责。排序依据是实际尚未共享的操作体、现有
owner能否完整承接、旧实现退出和全部适配成本；目录行数只作审计范围，不作可删除预算。
当前计量见[逐文件清单](coding-responsibility-inventory.md)，完整P1–P4范围见
[剩余责任账](coding-responsibility-remaining-audit.md)。

排序先比较能够整体退出的旧操作体和真实复用，再比较全部适配后Coding及系统的净值；
失败/取消/重试和资源交接必须一起替换。最近A171、A173、A174、A176合计Coding−680、
生产系统+422，属于职责收敛，不能作为系统净精简的证据。A179另Code−128/AppHost+224/
系统+96；A180完整前台控制另Code−116/AppHost+275/系统+159（统一格式+137）。
A181再Code−116/Harness+268/系统+152；A182再Code−76/Harness+115/系统+39；当前Coding110571行，距15K尚95571行，仍须按完整工作件推进。

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
| 5 / 下一整物设计与成本验证 | C08私有数据残余事务 | 比较既有Deletion/Archive/Expiry/Restore owner及实际产品政策 | 先核尚在Code的完整操作，三owner549/510为合计，不把已共享restore/archive重算收益 |
| 后续开放 / A169、A178完整形状均拒绝 | Worker Product完整收据authority | 原Package Product/Resources；Code保政策、验证与兼容DTO | 892行类范围/803行方法定义已作A178完整13源原型。真实Records/MRO/3必要reader改善成立，但计入4事实契约、6TypeVar、8必要公开门面后Code−512/Core+944/系统+432（统一格式+434），仅静态通过，未采用。相比A169系统+580减少148，仍无另一authority/运行重复退出，不为已付原型成本启动大矩阵或摘叶救收益 |

G17与C13本批实例寿命、C10两段中性证据投影已完成；后续核实顺序为：
**C08残留事务**。C01已按A183核完当前接缝并暂缓；这是进入完整接缝验证的顺序，不是已接受迁移或
预计减量。A182确认preview/open其余主体为Code产品政策及既有Core IO接入，
不以厚compile/open回调强搬；A183实证C01与A112原件未变，不自动重试同池；C08先剔除已经共享的
restore/archive，不能再计搬迁收益。
Worker两次完整原型已拒绝，单列暂缓，不排成自动重试任务。

其它较大操作体按下表保留比较；有阻断的范围不是排在小项之前无限等待的实施任务。
A178已完成Worker新接缝的整物成本决策并拒绝接入；A179随后完成202行审计范围的
完整prefix替代；A180完成foreground整控制，A181完成C13实例寿命，A182完成两段证据投影。
A183确认C01完整接缝仍受原成本阻断，现转C08残余事务，
不按目录总量承诺迁移收益。

A178核对A169最终原件确认，其POSIX authority已经继承ReceiptHistory；直接继承本身
不是新方案或收益。待比较的是实际初始化/新鲜历史读取绑定、Windows原Records公共
操作与构造、泛型不变量，以及双侧facade/profile的全部成本。原Code薄构造可以保留，
不为迁出几次字段赋值再增加一轮初始化回调；必要读取顺序优先于减少参数数量。

| 核实顺序与较大比较范围 | 当前完整范围实数 | 已有复用与不能立即迁移的原因 | 重新进入条件 |
| --- | --- | --- | --- |
| A183核实后暂缓 / C01 managed Base/Capability装配 | 两完整函数208+198=406行，函数/整文件与A112逐字同 | Resources、PM、Session已共享；try边界、显式reconcile、禁用关闭、replay异常和lease先持有/失败custody仍不同。A51完整形状系统+202已拒，无新整入口 | 原owner提供有据且全成本更小的整事务API；不恢复阶段回调Context，不把当前bootstrap3626行作可删预算 |
| 5 / C08私有数据三类owner | 三类合计549行/方法510：Read195/172、Restore170/161、WindowsBackup184/177 | 原DeletionCoordinator、POSIX archive及Windows事务已共享；RestoreOwner.restore83行已调用Core完整restore。31源扫描所见直接native调用多为路径/身份检查，不是未迁物理事务 | 先证明一条尚在Code的完整事务及窄codec边界；全成本未知，不按6691行整包搬迁 |

A182审计原preview271/open122与462方法行：只有84行Catalog身份连接和admission/bundle
投影可在不吞Code编译/信任政策、无厚IO回调的前提下整体交给原证据owner；其余保留
并非最终不可压缩下界。完整字段/clock/复核顺序保留，不据方法总量承诺整类减量。

A181核对A38原件：其拒绝对象是另一类`CodingDeferredLspGeneration`延迟子图，
不是`LspServerSupervisor`。前版将该决定紧邻C13描述，只能表示泛化适配成本的风险，
不能作为当前Supervisor曾被拒绝的证据。本类已按A181独立完成完整接缝与成本验证。

C08下一整候选先核Windows备份snapshot110；expiry recovery102及preview91主要是
Desired/deletion/confirmation/restore-publication的产品授权连接，底层复制/rename/收据
事务已Core；Code仍在原点调用路径/身份读取。
110的GC/Desired历史/state pin/staged debt/renamed reappearance合同须全计，不能直接
并入POSIX snapshot63。POSIX delete_confirmed52中约30行检查点调度仍Code，另列
其后；remove_started物理算法与restore83已Core，不能重计。两候选均无已证完整接管
API或全成本结论，先核整物，不以单项跨度承诺减量。

上述类/方法范围有包含关系，不能相加作可删量。跨簇扫描覆盖434份当前Code源码的
长函数/owner导航，并深核表列实际程序及Core调用，不等于全树语义重复证明或领域下界。
A179/A180/A181按不同完整接缝接续交付，不将其包含范围相加作可删预算；803方法行
Worker不同接缝已作完整原型并因全部成本不足以抵相称复用而拒绝，不承诺直接搬走
803行，也不回到零碎helper。

A175实查已确认activation policy/receipt/witness及多数manifest/candidate事实早已Core；
仅换剩余DTO不能消掉A169完整authority接口成本。A178已连具体journal/最少中性facts、
generated/duck reader及整Windows opt-in事务作完整替代比较，仍保外部、不采用；今后重新
进入须证明实际owner/API/重复机制退出带来不同的整物价值，不复刻已拒形状。

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
