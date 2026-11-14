# Coding剩余职责实施优先级

2026-11-14，按用户要求优先完整可迁移职责。排序依据是实际尚未共享的操作体、现有
owner能否完整承接、旧实现退出和全部适配成本；目录行数只作审计范围，不作可删除预算。
当前计量见[逐文件清单](coding-responsibility-inventory.md)，完整P1–P4范围见
[剩余责任账](coding-responsibility-remaining-audit.md)。

排序先比较能够整体退出的旧操作体和真实复用，再比较全部适配后Coding及系统的净值；
失败/取消/重试和资源交接必须一起替换。最近A171、A173、A174、A176合计Coding−680、
生产系统+422，属于职责收敛，不能作为系统净精简的证据。当前Coding111007行，距15K
尚96007行；继续以十几行局部抽取推进不足以说明大块优先已经落实。

| 顺序/状态 | 完整工作件 | 接收者及Coding保留边界 | 进入条件或实际处置 |
| --- | --- | --- | --- |
| 已完成 A171 | LSP进程传输完整生命周期 | 原Process拥有buffer/锁/Future/reader Task/request/cancel/close；Code保LSP初始化、诊断、服务器请求与优雅握手 | Code−274/Core+391/系统+117；126项通过；属于职责迁移，不是系统净精简 |
| 已完成 A173 | 配置兼容发布完整authority | 原Config LegacyProjection owner承接cache/issuer、writer与projection注册、聚合、Condition/deque、逐请求receipt和异常结算；Code保存量迁移政策/领域capture、guard和薄profile | 整物Code317→159（−158）/Core+246/系统+88；原135及固定旧29项覆盖通过，保持5原平台skip；不复用异常合同不同的普通Config通知队列，属于职责迁移 |
| 已完成 A174 | 根运行时关闭及Continuity完整绑定寿命 | 原Session Runtime接根关闭/两drain，原Continuity接composition/reservation/Task/identity-delete；Code保领域DTO、准入与薄profile | Code−153（含1行导入布局）/Core+301/生产系统+148（统一格式+139）；320项通过，持久55重放另验不重复累计；该片未含子Session113，后续见A176 |
| 已完成 A176 | Session profile完整失败保留链 | 原AgentProductSession接完整113退休程序，实际Slot/Registration/Publication/Assembly/Graph/Sandbox直接复用；Code保六字段/诊断绑定及两个纯状态hook | Code−95/Core+164/系统+69；原Core关闭Task/cancellation wrapper保原晚调用；BaseAssembly.close19仍Code，不据此关闭C01或C15整组 |
| 1 / 整物设计及成本验证；A169形状仍拒绝 | Worker Product完整收据authority | 原Package Product/Resources；优先比较真实ReceiptHistory、WindowsReceiptRecords/WindowsOptInRecords及原authority的直接复用，Code保政策、验证与兼容DTO | 四类共892行类范围、803行方法定义，均非净删预算。旧四源原型Code−543/Core+1123/系统+580、14结构端口，未采用；新方案须连真实journal/构造和facade一起重切，不能只删视图定义再包装同一形状 |
| 2 / 完整原型对照；暂缓接入 | Hosted Continuity构造前缀及失败清理 | 原AppHost Continuity/Application；Code保请求准入、产品注册/Resolver构造与Workspace加载资格 | outer owner176行及失败清理26行；三真实入口共用。需复用原inner attempt的open/close控制，同时保两作用域不同的缓存/交接/清理合同。78项原测试基线通过；候选净成本及兼容对照未接受，不计迁移收益 |

其它较大操作体按下表保留比较；有阻断的范围不是排在小项之前无限等待的实施任务。
先完成Worker新接缝的一份整物原型和成本接受/拒绝，再进入下一可行完整场景。

| 较大比较范围 | 当前完整范围实数 | 已有复用与不能立即迁移的原因 | 重新进入条件 |
| --- | --- | --- | --- |
| C01 managed Base/Capability装配 | 两完整函数208+198=406行 | Resources、Plugin lifecycle、Kernel已共享；剩余reconcile差异、严格/延迟源解析和失败顺序仍混合。A51完整形状系统+202已拒，A112未找到更小接缝 | 原owner有能替换完整程序的新API；不恢复阶段回调Context，不把bootstrap2210行作预算 |
| C08私有数据三类owner | 类范围549行，方法定义510行 | 原DeletionCoordinator、POSIX archive及Windows事务已共享；RestoreOwner.restore83行已调用Core完整restore。31源扫描所见直接native调用多为路径/身份检查，不是未迁物理事务 | 先证明一条尚在Code的完整事务及窄codec边界；全成本未知，不按6691行整包搬迁 |
| C10只读Product preview | 类范围479行，方法定义462行；主preview271、open122行 | 原Product/Resources capture、catalog与composition已共享；仍有Coding插件选择、编译、身份/新鲜度和诊断政策，没有已证完整中性API | 证明capture→catalog→recheck→close完整合同及全部政策适配成本；不回调整条Code preview或以摘要替代严格catalog |
| C13 LSP Supervisor | 类范围400行，方法定义384行；生命周期方法206行 | Process launcher及A171传输已共享；原Process不提供保留当前合同的keyed protocol-runtime池，start含LSP初始化/设置/诊断政策；A38宽泛形状已拒 | 先找到正确现有owner及最小完整接口，不另建通用RPC/服务管理框架或回借整条初始化 |

上述类/方法范围有包含关系，不能相加作可删量。跨簇扫描覆盖434份当前Code源码的
长函数/owner导航，并深核表列实际程序及Core调用，不等于全树语义重复证明或领域下界。
没有找到比202行prefix更大且已可直接替换的完整程序；因此先验证803方法行的Worker
不同接缝，而不是承诺直接搬走803行，或回到零碎helper。

A175实查已确认activation policy/receipt/witness及多数manifest/candidate事实早已Core；
仅换剩余DTO不能消掉A169完整authority接口成本。新方案须先证明具体journal/最少中性facts
确实能退出原适配层，并保generated/duck reader及整Windows opt-in事务；当前只调查，未采用。

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
