# Coding 全量剩余职责与保留成本复核

本页保留A72合同/候选与后续接受的历史来源；当前静态计量对齐A155源码
`4b3c2b1a5`及[逐文件清单](coding-responsibility-inventory.md)：434份Python源码、
112139行，距15K仍97139行。下面28组不是可删除预算或最终保留成本。
A155完整11类修复执行与runtime释放已归原ProductRuntime，A154退出waiter已归公开
Process，A150验证命令执行已归Session Bash；不得把这些已共享闭包重新列为待开发。
具体接受/验证边界见[执行记录](coding-responsibility-convergence-progress.md)。
完整P1–P4仍partial；本次只是交付事实协调，不新增Target、接口或精简收益。

- A146 普通启动和操作员查询共用 Provider 签发与选择，续期共用签发，Coding 减45行、系统增12行。见[A146](coding-responsibility-convergence-progress.md#a146共用worker-provider签发与选择)。
- A145 普通 Worker 待启动、实际 adapter 和操作员查询复用能力绑定或准入投影，Coding 减41行、系统减7行。见[A145](coding-responsibility-convergence-progress.md#a145共用普通worker能力绑定与准入投影)。
- A144 五类 Windows Worker 离线审阅共用静止锁与 GC 读锁，Coding 减15行、系统增4行。见[A144](coding-responsibility-convergence-progress.md#a144共用windows-worker离线审阅作用域)。
- A143 Windows Worker 历史身份与无副作用阶段校验归原 Worker History，Coding 减33行、系统增7行。见[A143](coding-responsibility-convergence-progress.md#a143共用windows-worker历史身份校验)。
- A142 四类 Windows 退休共用根删除意图写入和回读，Coding 减7行、系统增7行。见[A142](coding-responsibility-convergence-progress.md#a142共用windows根删除意图)。
- A141 四类 Windows 退休共用持久记录路径、读取与完成收据发布，Coding 减135行、系统减44行。见[A141](coding-responsibility-convergence-progress.md#a141共用windows退休记录与完成收据发布)。
- A140 四类 Windows 退休共用根枚举与冲突匹配，Coding 减50行、系统减42行。见[A140](coding-responsibility-convergence-progress.md#a140共用windows退休冲突扫描)。
- A139 四类 Windows 退休共用持久记录读取与 attempt 校验，Coding 减36行、系统减14行。见[A139](coding-responsibility-convergence-progress.md#a139共用windows退休记录读取)。

- A138 五条 Windows 退休及结算路径共用原 Product 根校验，Coding 净0行，系统增15行。见[A138](coding-responsibility-convergence-progress.md#a138统一windows退休根校验)。

- A137 三类 Windows Worker 日志共用绑定和追加，Coding 减19行，系统减12行。见[A137](coding-responsibility-convergence-progress.md#a137共用worker日志读取与追加)。

- A136 共用 Worker 授权重放与代次检查，Coding 减9行，Harness 增15行。见[A136](coding-responsibility-convergence-progress.md#a136共用worker授权重放与代次检查)。

- A135 两平台共用 Worker 回执与所有者校验，Coding 与系统源码各减10行。见[A135](coding-responsibility-convergence-progress.md#a135两平台共用worker回执复核)。

- A133 三个读取入口共用原 Plugin Management 的 GC 与 Desired 装配，Coding 减10行、Harness 增15行。见[A133](coding-responsibility-convergence-progress.md#a133共用gc与desired账本装配)。

- A132 统一25处 fenced runtime 布局映射，Coding 和系统源码各减少76行。见[A132](coding-responsibility-convergence-progress.md#a132共用fenced-runtime布局映射)。

- A131 合并 POSIX 与 Windows 的备份记录逻辑，Coding 和系统源码各减少16行。见[A131](key-designs/private-data-lifecycle-convergence.md#a131两平台备份记录共用)。

- A130：九个公开from_bytes转发直接复用原Decoder；Code−36/Core+2/系统−34，Data/Schema/IO原样，见[A130](key-designs/worker-history-responsibility-convergence.md#a130九个公开codec入口直接复用)。

- A128：Method提交Task与同一run的recording结清归原HarnessWork Session集成，Code保准备/Outcome/step与Session尾段；Code−79/Core+121/系统+42，本批已验收，完整Goal仍partial，见[A128](key-designs/method-plan-custody-convergence.md)。

- A127：普通/Resume托管Work共同观察、分发与结清归原AppHost集成；Code保两条策略边界，Code−93/AppHost+118/系统+25，完整Goal仍partial，见[A127](key-designs/hosted-work-custody-convergence.md)。

- A126：完整model Work配置寿命归原HarnessWork规划集成，Code保纯profile；Code−41/Core+71/系统+30，完整Goal仍partial，见[A126](key-designs/planning-work-configuration-custody-convergence.md)。

- A125：两平台expiry命名共享原Coding记录模块，四条真实调用链接通；Code/系统−24、Core0，完整Goal仍partial，见[A125](coding-convergence-system-cost-audit.md#a125两平台expiry命名同域去重)。

- A124：删除七个已退出主路且无消费者的私有薄壳，保留动态probe实际依赖；Code/系统−63、Core0，完整Goal仍partial，见[A124](key-designs/worker-history-responsibility-convergence.md#a124七个已退出主路的私有薄壳)。

- A123：完整无写入settings快照读取归原Config.store，复用原Resources消费器；Code−113/Core+158/系统+45，完整Goal仍partial，见[A123](key-designs/settings-snapshot-read-custody-convergence.md)。

- A122：完整Windows persisted-base读取/复读归原PackageProduct，Code−58/Core+107/系统+49；完整Goal仍partial，见[A122](key-designs/worker-history-responsibility-convergence.md#a122完整windows持久base读取与复读归原packageproduct)。

- A121：完整Windows live-stage重验证归原PackageProduct；Code−102/Core+111/系统+9，完整Goal仍partial，见[A121](key-designs/worker-history-responsibility-convergence.md#a121完整windows-live-stage验证归原packageproduct)。

- A120：完整Windows审批目录native创建与关闭归原Resources，Code−48/Core+59/系统+11；完整Goal仍partial，见[A120](key-designs/windows-approval-root-custody-convergence.md)。

- A119：协调A93/A107对应的两项旧C50库存限制，生产净0；不新增门禁或精简收益，见[A119](key-designs/worker-history-responsibility-convergence.md#a119协调两项c50旧消费者库存)。

- A118：POSIX完整收据持久事务归原ReceiptHistory，三个latest扫描合一；Code−45/Core+50/系统+5，完整Goal仍partial，见[A118](key-designs/worker-history-responsibility-convergence.md#a118收据持久事务与同义扫描收敛)。

- A94后续：H5原operator边界协调，生产净0；保留5项扩大Hosting基线欠账，完整P1–P4仍未完成，见[当前状态](coding-responsibility-convergence-progress.md)。

- Authority: descriptive audit under COD-RESP-GOAL-002；不替代已接受Target。
- Design status: current-gap review；A72历史候选在当时未接受，后续A73/A74/A75等接受见各片记录，不重新列为待开发。
- Implementation status: A155已提交；本次只同步当前计量与历史标记，不新增生产实现或精简收益。
- Owner: Coding及各原组件owner；三独立视角复核，实施owner综合事实。
- A117：完整Goal/Work来源冷读与原owner关闭归原GoalStore集成；C12整体仍未关闭，见[A117](key-designs/goal-work-source-custody-convergence.md)。
- A116：完整规划waiter/cache寿命归原Session；C17整体仍未关闭，见[A116](key-designs/session-planning-slot-custody-convergence.md)。
- A115：完整Windows临时cutover目录custody归原Resources；C09仍未关闭，见[A115](key-designs/windows-cutover-temporary-custody-convergence.md)。
- A114：已接受Catalog/Session依赖对应的3项旧RCP2库存失败经精确可选清单协调关闭；生产0，不关闭其它差距，见[KD009 §27](key-designs/startup-session-assembly-convergence.md#27-a114协调三项既有catalog依赖清单)。
- A113：captured Product声明完整中性投影归原Session，Code保信任/owner政策；不关闭C01，见[A113](key-designs/product-selected-contribution-projection.md)。
- A111：Arch缓存普通path发布与Transcript index共享同一Journal字节程序，Code保codec/政策；不关闭C14，见[A111](key-designs/cache-publication-convergence.md)。
- A110：原构造后selection读失败窗口已有回退/同Transcript重试证据，未证明需新增custody；其它早期构造问题未泛关，见[KD009 §25](key-designs/startup-session-assembly-convergence.md#25-a110构造后交接窗口的有界核实不新增清理机制)。
- A109：完整V2预检读协调归原PackageProduct，Code保政策与薄入口；不关闭C07，见[A109](key-designs/worker-history-responsibility-convergence.md#a109完整-v2-预检复用原-packageproduct-history-协调)。
- A107：初始Worker封口全Rooted程序归原Publication，复用原五锁环；不关闭C07/完整Goal，见[KD004 A107](key-designs/worker-history-responsibility-convergence.md#a107初始-v1-封口复用原-historypublication)。
- A106：历史读取完整Task/read/drain归原Session；Code保领域reader及关闭政策，不关闭C17，见[A106](key-designs/resume-history-task-custody-convergence.md)。
- A105：A104观察到的Catalog消费者清单失配已协调（生产增删0/原模块3过）；其它历史Catalog/Session欠账不销账，见[KD009 §24](key-designs/startup-session-assembly-convergence.md#24-a105协调两项已接受-catalog-消费者库存)。
- A104：native fallback整FD/根身份程序归原Resources，Code保政策/纯投影；不关闭C01，旧Catalog清单欠账保持，见[A104](key-designs/native-fallback-metadata-custody-convergence.md)。
- A103：普通 Session 孤儿恢复完整物理程序已归原 Product，Code 保资格政策/薄入口；不关闭整个 C10，见[A103](key-designs/ordinary-orphan-recovery-convergence.md)。
- A93后续：完整Windows backend review/install/read及approval current归原PackageProduct，Code保公开值/产品政策；不关闭整个P1。原H5规范/Session operator事实失配已在[A94](../hosting/harness-worker-adapter-h5.md#a94-reconciliation-evidence)协调，见[A93](key-designs/windows-backend-release-custody-convergence.md)。
- A92后续：原Continuity激活lease算法已直接复用，Code行数不变/系统−28；不关闭整个C04/P3，也不实施KD003 bytes输入。当前事实见[A92](key-designs/activation-lease-lifecycle-convergence.md)。
- 后续：A73关闭下文候选的完整审批协调，A74关闭三类payload恢复协调（当时不含registered，A78后已接管所述闭包），A75关闭prepared-operation任务custody、A76关闭备份拓扑完整存储依赖、A77关闭完整Linux history proof/strict GC，A78关闭完整registered/crash恢复、cleanup evidence及POSIX C5 Store custody，A79关闭完整Product selected revision输入与installed member/Wheel bytes程序，A80关闭完整canonical Catalog协调/候选custody与Managed探针程序（history/navigation原位）；A81关闭完整delegated Goal Work/Session轮次关联、Task/取消/清理及固定history取得（Coding保领域选择/证据）；当前计量与未关闭职责见[执行状态](coding-responsibility-convergence-progress.md)，除当前28组表外，保留账与候选窗口中的历史数值沿用A72审计切点。
- A72历史实物：`2c322a821`，专用delivery worktree；Coding430文件117115行，系统1958源645173行。
- 方法：本地干净master `0f9bd3ff51afabeaaf76cc38dff1ceb279b7d37e`。

## 覆盖及计量边界

A72原始快照对430份Code源码的SHA、物理行、顶层定义范围与显式imports作静态扫描，
按原28组重算，历史合计117115；全量清单仍是单一[逐文件表](coding-responsibility-inventory.md)。
完整原始frame/AST/接口筛查在树外`a72-full-remaining-audit`。本次静态全文件覆盖
不等于逐行语义接受；深核的普通构造、审批、payload和公开合同范围另列如下。
组量只是审计范围，不能作为可删预算或必要保留成本。该历史快照的生产源码与A71终帧相同。

波次按现行[Goal](coding-responsibility-convergence-goal.md#实施波次与第一项建议)：
P1 Worker、P2启动/Plugin/Session、P3托管/Continuity/执行适配、P4入口/存量。
最初proposal的旧P编号不覆盖已激活Goal；私有数据也继续在完整范围中。

## 全部28组的当前处置账

每行说明当前已复用事实和仍需完成的责任，**不是整组最终保留/迁移接受**。
数量按A155当前434源重计；A146/A72均为历史切点，前序减少不重复计入本次协调。
通用运行、IO、恢复归原组件；产品域实现不因换目录、插件或配置而退出归属计量。

| 组 | 文件/行 | 场景 | 已复用与Code实际保留面 | 剩余处置/退出义务 |
|---|---:|---|---|---|
| C01 启动、Plugin/资源装配 | 22/12,709 | P2 | 原Construction/Session、Catalog/Graph已实际接入；Code剩跨阶段选择、审批、刷新与交接 | 拆清领域选择和完整共用程序；不把bootstrap3561行或装配回调池当删除预算 |
| C02 托管与受管接入 | 31/8,478 | P3/P4 | 原AppHost/AppService桥接及managed owners已复用；Catalog/身份与部分CLI协调仍混合 | 严格Catalog读取不能用摘要API代替；KD011保待审，整lmux迁移拒绝 |
| C03 Resume与SessionManager | 15/4,132 | P2/P3 | 原Transcript/Session lifecycle、live恢复已复用；Code保版本化输入/装配与授权政策 | 按new/resume/fork/reopen完整合同再拆；不重建提交器或自动重试 |
| C04 Continuity | 2/2,956 | P3 | 原Continuity provider/runtime及A68 payload custody已接入；Code来源/导入/恢复桥仍在 | KD003 bytes import未实施；区分纯准入与读取/借用/abort寿命，不提前采用KD011 |
| C05 Canary及作者验证入口 | 6/3,565 | P1/P3/P4 | 原Worker attempt及托管owner已有接入；Code保真实SDK/CLI验证入口和产品场景 | 存在真实运行消费者，不能按canary/smoke命名删除；剩余协调须随实际场景替代 |
| C06 其余根入口与策略 | 26/4,460 | P2/P4 | 混合产品配置、模型/工具选择及既有薄绑定 | 逐具体声明/运行路径处置；不整体当领域保留或机械可删 |
| C07 插件Worker | 112/21,208 | P1 | 五流/Rooted/history/platform/native custody已共享；A118收据事务、A121 live-stage及A122持久base读协调归位，Code保准入与证据关联 | 已共享payload recovery不重计；继续核普通Session选择/停止/重开/结清的剩余政策与协调，尚无整簇完成证明 |
| C08 插件私有数据 | 31/6,691 | P4 | 原备份/删除/恢复/过期及A71 lineage已由原Plugin Management/Resources承接 | 保key/路径/确认与真实记录；继续核残留协调，前序成本不重复记收益 |
| C09 兼容迁移与快照证据 | 34/9,523 | P4 | 原capture/epoch/receipt等机制已共享；存量分类、准入与恢复政策仍在 | 逐受支持状态和恢复入口给退出证明；legacy命名与静态无调用都不足以删支持 |
| C10 包分发及Product管理 | 12/5,324 | P2/P4 | Package Product等已复用；A155修复执行/释放归原ProductRuntime，Code保该入口准入/DTO/parent关闭，其它兼容/fenced装配仍混合 | 保产品内容与信任/支持范围；核完整选择、恢复、factory release而非另建manager |
| C11 CLI | 26/9,507 | P4 | 大量命令调用原owner；语法、确认、选择、JSON/TUI及少量效果协调交织 | 同一业务接同一owner；lmux close须先证明输出/确认/CAS/期限屏障及全适配成本，未接受新形状 |
| C12 Goal/Work/证据适配 | 25/7,017 | P3/P4 | 原Work/Goal/Method、A117来源冷读及A150验证Bash完整执行已共享；Code保仓库/测试/评审策略与scope适配 | 按剩余领域判据/入口核保留或退出成本，不重开已共享cold reader/Task闭包；真实calculator/repository路线保持 |
| C13 LSP | 21/5,653 | P2/P4 | 语义查询/位置/结果及协议；进程端口已用Workspace/Hosting，A154退出waiter寿命归公开Process | 领域能力继续计Code；通用任务/IO仍可复用，不能用整目录量当必要下界 |
| C14 Arch | 13/3,608 | P2/P4 | Python AST/import分类/图查询及cache、读取适配 | 保编码分析；核cache/IO与原Workspace/Resources的边界，不把领域算法换目录 |
| C15 AgentSession产品绑定 | 2/2,042 | P2 | 原AgentProductSession/Graph/publication/retirement已实际复用 | 构造、选择见证/receipt及产品hooks仍混合；公开入口可薄化，不能声称整类是第二引擎 |
| C16 Native UI产品绑定 | 14/2,189 | P4 | 原HarnessTUI conversation/controller/surface为实际机制 | 保产品文案/主题/领域动作；以公共观察替代私有字段耦合，不复制UI状态权威 |
| C17 AgentSessionRuntime绑定 | 3/904 | P2/P3 | 原Session已承接A75 prepared、A106 history、A116 planning寿命；Code保Resume准入/Plan/fresh校验与关闭政策 | 按剩余领域与准入逐路径核实保留成本；不重开已共享Task机制，不据本片关闭整C17 |
| C18 交互命令与预热 | 5/874 | P4 | 原Command/Session/展示机制已共享 | 保语法与业务动作；公共控制/观察端口代替跨owner私有访问 |
| C19 压缩Profile | 4/440 | P4 | 原compaction runtime已接入 | 保编码摘要内容/标签；不为纯绑定再建抽象 |
| C20 诊断Profile | 3/233 | P4 | 原Diagnostics owner及序列化已共享 | 保产品投影与来源，不建第二诊断存储 |
| C21 Prompt | 3/132 | P4 | 编码内容和声明输入 | 保真实内容，移动至其它包仍计Code归属 |
| C22 内置Plugin内容 | 6/124 | P4 | 原Harness加载，Code内容/声明 | 保真实内容和支持路径；不把数据化实现当削减 |
| C23 呈现适配 | 4/109 | P4 | 原HarnessTUI提供机制 | 保最终产品投影，按具体私有访问再核 |
| C24 Scenario适配 | 2/82 | P4 | 实际使用原Harness scenario | 保模型/编码准备绑定，不另建执行器 |
| C25 Method domain/兼容入口 | 3/72 | P3/P4 | 实际使用原Method runtime | 保domain profile及必要转发，不新建harnessmethod |
| C26 配置/路径兼容导出 | 2/52 | P4 | 原Config owner已复用 | 保产品路径选择与支持中的导出，退出需合同证据 |
| C27 版本检查 | 2/50 | P4 | 产品更新选择与原公共机制绑定 | 保必要产品选择，不为50行再建服务 |
| C28 资源命名空间 | 5/5 | P4 | 支持中的Python布局标记 | 保真实加载/导出路径，空壳不是第二引擎 |
| 合计 | **434/112,139** | 完整P1–P4 | 全部纳入 | **未完成Goal** |

## A72保留合同与语法筛查（历史成本，非当前下界）

以下保留的是原用户能力/产品决定和兼容合同，不是整段当前操作体。尚未建立全树
不可削减下界，也未证明15K必定可达，因此不请求放宽目标、不宣布冲突、不按目录
预算直接删实现。移至Plugin、配置或别的产品包的Code专属实现仍须计归属成本。

| 具体合同/语义 | A72时点可定位成本 | 必须保持 | 可继续退出的机制及原owner |
|---|---:|---|---|
| LSP位置与范围转换 | `lsp/positions.py`104行；五函数体合计73行 | 公开CodePoint/UTF-16转换、边界与错误 | 通用过程/IO/任务不在这五函数内；整个LSP目录5668不是不可变下界 |
| Python import语义 | `arch/providers/python.py`的Visitor180行、TYPE_CHECKING判断9、dynamic import提取14，共203行操作体 | import分类、证据及语言规则 | 文件遍历/读取/cache由原Workspace/Resources复核；不是整个876行都保或都迁 |
| 仓库任务验收 | `_goal_repository.py` limits29、check结果40、Action25，共94行当前体 | 任务范围、完整测试覆盖/环境未知判定、动作与证据许可 | Goal/Work事实、运行/计划与Session执行沿原owner，不能把1423行全部当领域必要成本 |
| 产品选择 | `composition_sets.py`236行；两个值类与两个选择函数当前131行 | composition sets、LSP/Arch选择、pin/信任/预算策略与内容 | 具体构造、Graph、审批机制归原owner；当前排版/方法数不是下界 |
| 真实兼容值外观 | A69三个DTO、A70 Material及A71 Generation：26自身字段，类范围当前91行，另有decorator/import | 已验证FQN、字段/own annotations、slots/frozen、构造及指定classmethod/旧pickle合同 | Code真实字段+Core机制mixin已可行；没有合同要求旧执行body留Code，不能外推全部622类 |
| SDK入口 | 原`tests/coding/test_sdk_surface.py`冻结六入口参数；原`harness.sdk_surface`检查导出解析与参数 | 原导出、参数、能力及失败恢复语义 | 可保显式薄转发；参数检查不是实现必须留Code的证据 |
| calculator/repository产品路线 | calculator模块603、Goal适配组7517，均为当前审计面 | 支持中的真实Goal任务仍能执行、验证/评审/恢复 | 现有Work/Method/Session引擎继续复用；不能因“calculator”命名把已支持路线改成仅示例 |

全树另做可复验的**语法候选筛查**：非下划线顶层class/function（包括私有模块），
public或`__init__`方法，候选dataclass全部自身AnnAssign（含ClassVar/private）。
按token中括号depth0的冒号结束header，class header含其decorator，函数/方法不含
其decorator；逐文件取行集合去重。622类、347候选dataclass、2008注解、649函数、
1217方法。类header1080、注解2134、函数header3197、方法header3196，合计9607
A72时点行。这是需要查合同的语法范围，不是公开API认证、不可删成本或15K下界。
其中方法可继承，私有模块内类未必公开，AnnAssign也并非全是dataclass字段。
完整token脚本与逐文件结果在树外，避免把不明约9.7K估数写成硬事实。

另一个独立交叉检查：LSP/Arch9296 + Goal适配7517 + Native UI2179 + C18–C28
2173 =21165行。这些组仍含可共享机制，不证明15K不可能；即使其余95950行全退出，
这21165也还需减少6165，且其它产品政策/兼容成本不会实际归零。严格K旧标签仅
25文件1326行，更不是完整保留清单或领域下界。后续每个保留成本须落实到语义/
API，不能把标签、语法或现状当成结论。

## P1–P4仍缺的整体验收

| 波次 | 已共享事实不能重复计收益 | 尚未证明完成的整体路径 | 下一步证据/退出条件 |
|---|---|---|---|
| P1 Worker | history/Rooted/Windows基座、Supervisor、Storage/repair journal、A61 attempt与A69/A70 native custody | 普通Session Worker从选用/批准到停止、重开及资源结清的整体验收；不重开已共享的payload恢复 | 按实际policy/type绑定接原owner；原preview/intent/重验/清理/reopen/retry全闭合，原操作体退出，不把不同事实合并日志 |
| P2启动/Plugin/Session | Construction、Catalog交接/refresh、Graph/Registration、owner publication/retirement、cleanup、A59 live resume均已在调用链 | 普通new/resume、initial/refresh、失败构造和关闭重试尚无统一完整职责验收 | 拆产品选择和中性操作；对照真实现有owner与完整替代源，删除厚Code回调，保未结清依赖和重试凭据 |
| P3托管/Continuity/执行 | 标准Session控制桥、foreground host、Goal物理后端、payload custody已有接入 | 严格Catalog/恢复准入、Continuity导入及Goal scope仍混合；A75 prepared及A106/A116已共享寿命不重开 | 严格读不能用摘要替换；不复制Goal/Method/Work执行引擎；KD003/KD011未因此实施 |
| P4入口/存量 | managed/create/probe/stop和包/私有数据机制已实际复用；许多UI/配置入口已薄化 | CLI/SDK/UI、历史设置/状态/备份及公共导出未全部给最终保留/退出结果 | 每个退出需支持与消费者证据；canary/legacy/calculator名称不构成退出；最终逻辑Code归属与≤15K另审 |

仅以源码已用Core、若干场景green或局部成本下降，不足以把任一整波次标完成。
本次不扩大门禁/平台、不重新运行无关套件，先前实际验证的原边界保持。

## A72历史窗口与候选（不作为当前待开发清单）

以下12560行窗口、API缺口与候选排序记录A72当时实物；A73审批、A74 payload恢复、
A75 prepared任务等后续已接受内容以执行记录为准，不重复开发或计收益。
当前组量见上表；本节历史行数不能作当前值或可删预算。A72重点为
[bootstrap](../../../../src/loushang/coding/bootstrap.py)的普通构造与内部factory、
[AgentSession](../../../../src/loushang/coding/session/agent_session.py)构造/选择见证，
以及[capability composition](../../../../src/loushang/coding/_capability_plugin_composition.py)
的definition批准、workspace绑定、activation证据和失败custodian。现成的
AgentProductConstructionBinding、ProductPluginCompositionPreparation、Graph/
Registration及Session lifecycle必须继续用，不能再包一个composer。

A72窗口实物（历史物理行）：

| Code路径 | A72行 |
|---|---:|
| [bootstrap.py](../../../../src/loushang/coding/bootstrap.py) | 3531 |
| [session/agent_session.py](../../../../src/loushang/coding/session/agent_session.py) | 2101 |
| [_capability_plugin_composition.py](../../../../src/loushang/coding/_capability_plugin_composition.py) | 1887 |
| [_product_capability_plugin_composition.py](../../../../src/loushang/coding/_product_capability_plugin_composition.py) | 781 |
| [_base_product_composition.py](../../../../src/loushang/coding/_base_product_composition.py) | 747 |
| [_base_plugin.py](../../../../src/loushang/coding/_base_plugin.py) | 1082 |
| [_base_plugin_owners.py](../../../../src/loushang/coding/_base_plugin_owners.py) | 522 |
| [_plugin_lifecycle.py](../../../../src/loushang/coding/_plugin_lifecycle.py) | 1163 |
| [_resource_catalog_adapter.py](../../../../src/loushang/coding/_resource_catalog_adapter.py) | 445 |
| [_plugin_owner_generations.py](../../../../src/loushang/coding/_plugin_owner_generations.py) | 301 |
| **合计** | **12560** |

A72当时拟优先形成两条原owner的**完整审批程序**候选与全成本：

1. Definition：原PluginDeclarationHost首次resolve→仅pending时按原顺序调用
   同一Product issuer→原返回record类型和subject digest校验→第二次resolve。
   最多两次；Code保Resume parents、原journal/evaluator配置及denied notes映射。
   不给Definition新增exact-record检查，旧流程由第二次resolve自行查journal事实。
2. Activation：原ProductPluginCompositionAssembly/CapabilityComponentHost按原
   候选顺序subject→同一issuer→同journal exact record/subject→approved/AVAILABLE
   →decision IDs→bind_session_inputs。保原host recovery构造时点，不提前调用
   begin_admission、consume、创建Provider或改变Graph publication。

A72时这还不是已接受接口或已实现替代；后续A73已接受所述完整审批协调。
当时要求先证明现有配置/端口不能直接表达，再最小扩原
owner；Product审批权保留，错误/记录/时间/恢复行为固定，没有新状态、阶段表或
Code IO回借。具体Code/Core/薄外观成本由完整源实测，不预报1887行退出。

事实纠正：data-only Base当前不持有第二套Definition/Activation审批；Builtin
Base+Capability、Product Capability和legacy Capability已经共用上述Code helper。
不能假称将合并Base与Capability两套算法。Continuity确有相似resolve/issue/resolve，
但其issuer、校验与错误合同不同，不为制造去重强套。Host当前resolve及Assembly
bind_session_inputs各自保持“不自行签发/推断”的原合同；任何新增显式issuer方法
须在实物设计中说明权限与原方法边界，不能暗改已有方法。

备选完整闭包：Worker payload三类debt的preview/intent/Supervisor重验/物理清理/
reopen-read-retry，现成PayloadStorage、RepairJournal、值机制和RootedSupervisor
可直接承接；Code保公开DTO/错误/产品准入，Core不能回调Code扫描/删除/verify。
另一候选是AgentSessionRuntime prepared-operation的task/consume/abort/drain，原
SessionLifecycleRuntime已有候选状态却缺全部task/debt custody，仍须最小扩原
runtime，不能冒称已有整API。优先级随具体复用与全成本证据调整。

## A72独立复核的历史结论

职责/复用、运行/失败、数据/兼容三个原reviewer独立只读核源码与现行合同；未
运行pytest、未实施新接口。Root采用本次**差距与选题事实**，不把它当设计/代码
完成接受。静态全文件frame和token筛查支持覆盖/计量；深审支持上述具体候选，
不声称已经逐行认证430文件或找到全局最大/唯一方案。

上述A72复核当时生产仍为A71终帧，无新增精简；这不是当前源码状态。完整Goal及15K上限保持；没有可证数值冲突
就不申请放宽，也不保证尚未证明的可达性。KD011/A33原用户确认边界保持；KD003
bytes导入仍draft/not-started。继续无依赖的完整职责工作，不将待确认事项当作全
Goal阻塞或借分析停止执行。
