# COD-RESP-GOAL-002：Coding 领域化与公共机制职责归一

## 状态与依据

- **现行成本准则（2026-11-09用户修订）：** 以职责分明、高内聚低耦合、优先复用已有组件为先。已有能力无法满足真实合同、最小扩充或必要薄适配确有必要时，允许系统总行数适度增加；不再把系统低于634,794行作为硬性完成条件。Coding归属≤15,000行、完整P1–P4、兼容与恢复义务保持。所有接收与适配成本仍全计账，迁移不冒称去重。下文A1–A54时点记录中的“系统严格净减”是当时要求，不覆盖本条新准则，也不追认历史被拒候选。

- Authority: accepted execution goal；用户2026-11-07将本描述设为active Goal。本文件不替代各组件的已接受架构合同。
- Design status: accepted goal scope；各波次专项架构仍须设计、评审及按原约定由用户审阅重要工作件。
- 当前实施摘要：A91完整partial capture归原PackageProduct并修复A89关闭异常链；A90完整owner receipt捕获已复用原Session publication；A89 Reserved完整重复capture已复用A88同一PackageProduct操作；A83–A86实际薄层/重复读取退出，A87纠正cleanup当前归属，A82完成系统增长账复核；此前各批成果保持。当前计量及欠账见下文“当前状态”。KD011/A33待用户工作件保持，KD003 bytes-import仍未实施；以下逐项保留各历史接受范围。
- Implementation status: partial（P1/P2/P3/P4）；指定五流/Rooted命令、payload、checkpoint/快照及A13–A15 Windows指定路径已获有界技术接受；A17图关系归原Session，A19本地启动阶段复用、A20托管Session桥接、A21 foreground Product所有权接缝、A22受控Wheel Source目录共享程序及A23依赖来源完整操作复用也已获有界接受。P2 R2.1职责方向已于2026-11-08获用户接受，D3完整兼容捕获路径获有界技术接受（181实际通过/5原skip），D1/D2的owner租约/证据账本与startup、D4完整成员/退役/关闭协同均已接入并获有界接受，P2启动装配首批owner publication亦已接通并获有界代码接受（75项实际回归及21组冻结观察对照），三种构造/发布前后清理路径也已复用Session共同程序并完成有界评审，原Loader回执至Catalog source specs完整交接也已接入（原47节点通过/失败集合不变，16固定观察通过，保留10项迁前失败），其余bootstrap/共同输入与刷新装配仍待收敛；KD010六Windows基线/join已整体接入Worker.history并取得实际有限验证，P4的F06 Goal记录后端亦已本地接通（14原节点及7固定IO观察通过，2项Session准入失败用旧后端复现），A24十三个Payload入口已复用原Storage根借用、删除重复根IO骨架（Code−71/系统净−48，实际48项通过及代码三视角有界接受），A25内置Source四个物理程序也已接入原Resources（Code−216/系统+4，65过/1原native skip，代码三视角有界接受）；A26 Windows Worker Source完整目录协调已归原Package Product（Code−204/系统+78，117过/1原native skip，代码三视角有界接受）；A27两平台候选事实联接及四条安装/更新共同程序已归原Package Product（Code−313/系统净−123，103过/2原skip，代码三视角有界接受）；其余Worker、其它托管/Continuity与P4剩余入口仍未完成，Coding≤15K及现行职责/复用/成本准则保持，实际测试与全成本见[执行记录](coding-responsibility-convergence-progress.md)。
- Owner: Coding与各接收组件原owner；跨组件决定由共同上级架构owner综合接受。
- 依据：[全量重构方案](coding-reconstruction-proposal.md)、[逐文件职责清单](coding-responsibility-inventory.md)、[Current Owner Map](current-owner-map.md)。方案与清单中的旧行数不是本轮当前事实。
- 前序：[COD-PD-GOAL-001](coding-private-data-implementation-goal.md)已完成本地技术接受，[A86记录](coding-convergence-progress.md#目录机制与接收层重复收尾a83a86)为本轮起点；其已有成果直接复用，不重开、不重复计收益。
- 方法：本地干净archmethod master `0f9bd3ff51afabeaaf76cc38dff1ceb279b7d37e`，按跨组件职责变更裁剪工作件，不复制方法正文。

A51历史事实：完整双managed插件程序已完成旧/新受控37场景对照与实际源码三视角，
但新增接口成本未获充分简化回报，Root暂缓采用并精确恢复全部1932生产源；本轮
新增生产精简0，实际Coding120932/系统641090。不是实施失败，也不计候选−201为
交付收益；原Code≤15000与系统严格净减条件均未达到。详见[KD009 §18](key-designs/startup-session-assembly-convergence.md#18-a51完整双程序试装通过有限对照正式采用暂缓)。

A52已完成下一整簇三视角源码审计与联合交接合同输入：下一外置候选聚焦普通
Session Worker两pending、Provider/Prepared及原Graph提交/失败释放的完整闭包。
尚无R5替代源/成本接受，生产计量不变；详见[KD008 §18](key-designs/worker-product-runtime-convergence.md#18-a52下一联合闭包收敛到普通-session-worker)。

A53已完成完整七源R5原型与三视角设计评审，因具体异常scope阻断、厚IO回借和
层间反跳及系统+483成本而拒绝当前形状，未安装，生产计量仍120932/641090。
下一版须按Session上层驱动Worker准备/资源交接重做完整候选，不预支净删或
接受；详见[KD008 §19](key-designs/worker-product-runtime-convergence.md#19-a53完整-ordinary-联合源码已构建r5-r2不采用)。

## 当前状态（2026-11-10，A91完整partial capture及关闭异常链修复）

Code完整partial-tree物理操作已退出，原PackageProduct直接复用WindowsStageInspection、
Product root借用与Worker现有whole-child close。公开Partial/Reserved DTO及产品准入
仍在Code；仅纯值构造函数进入原返回点，没有Code IO回借、新manager或四scope接口。
Core恢复原生with/try/finally：partial在children关闭前构造，full/reserved先关children
再做末次校验/构造。修复了A89扁平ExitStack遗漏的多重关闭异常链；旧失败未删。
本批Code−109、接收+137、系统+28（结构+47/格式−19）。当前Coding430源113755行，
系统1967源647664行，其余1963源及13资源SHA保持；相对Goal起点Code−24000、
系统+12870，不能把职责迁移说成全系统精简。原消费者271过，两个显式旧行为
探针118+90=208过；三视角评审及有限平台证据见
[A91](key-designs/windows-stage-capture-custody-convergence.md#a91完整partial-capture与原生关闭区域)。
完整P1–P4/领域化/≤15K仍active/partial，距15K尚98755行；KD011/A33待用户且未
采用，KD003仍未实施。下一批须从完整剩余场景核对实际原owner与重复机制；LSP
现有不同framing/生命周期不能用目录迁移或新通用RPC框架冒充复用成果。

## A90历史交付（2026-11-10，完整owner receipt捕获/发布接缝）

Code两套完整receipt捕获体已退出，原Session publication直接调用实际generation/
Resource candidate程序，复用已有三键identity作稳定排序。Code保产品选择、两个
纯字段projection和两个惰性facts getter；原target/fanout、flags/error、Graph准备/
提交与退休资格仍由原实例/调用方保持，没有新manager/Protocol/缓存或厚IO回调。
最终Code−91、原接收+71、系统−20（结构−18/格式−2），当前Coding430源113864行、
系统1967源647636行，其余1965源及13资源SHA同。三独立实物视角有界接受；原固定/
R2候选/实际source guard与56场景、145原消费者、14 SDK均有终态证据，见
[KD009 §21](key-designs/startup-session-assembly-convergence.md#21-a90原publication直接捕获完整receipt)。
R1补充集成78过/1 SDK目录准入失败保留；冻结旧源复现同unsafe，使用现有私有
tmp fixture后实际R2完整SDK14过，没有修改产品目录准入。完整P1–P4/≤15K仍
active/partial，距15K尚98864行；publication以外bootstrap/刷新/其它生命周期和
P1/P3/P4剩余保持，KD011/A33待用户且未采用，KD003仍未实施。

## A89历史交付（2026-11-10，完整Reserved capture实际复用）

Reserved、settled-unlaunched及retirement recapture的完整重复捕获体已退出Code，
直接复用A88原PackageProduct capture；complete/crash路径同批接入原标准ExitStack，
将真实公开Reserved DTO构造留在stage/root/ACL存活范围内。Core保持普通同步函数，
不增加generator/constructor callback/新manager；两类原错误域和独立payload预算保持。
Code−65、原接收侧−7、系统−72；A88+A89两片合计Code−155/接收+124/系统−31，
是两条完整程序合一的真实去重，不代表此前系统累计增长已经解决。
当前Code430文件113955行，系统1967源647656行，其余1964源及13资源SHA同。
原消费者/capture对照及新增Reserved全故障对照、三独立源码评审、mypy/Ruff/format/
文档和依赖图证据见[A89交付](key-designs/windows-stage-capture-custody-convergence.md#a89完整reserved捕获复用与共同寿命)。
验证是受控Windows端口上的真实POSIX文件/FD及同步异常，不外推原生Windows、
实际Task.cancel或全部进程crash。完整P1–P4/领域化/≤15K仍active/partial，尚差
98955行；下一步优先复核P2原publication owner的完整receipt捕获/发布重试接线
候选，尚未实施/接受。offline snapshot/attempt-reference等剩余范围保持，不能
把Code产品判据或已共享的cleanup再迁一次，也不为减少目录行数增加厚回调。

## A88历史交付（2026-11-10，完整Windows stage capture）

完整stage capture已归现有PackageProduct，直接复用原WindowsStageInspection与
实际Product root借用：ACL/root/stage/child寿命、marker与成员校验、payload大小/
SHA、末次identity及反序close一并接通，Code旧操作体删除。Code保精确intent
准入、公开Review/Error、外层GC及有真实消费者的薄helper；没有Worker反向依赖、
新manager、厚IO回调或第二份状态。私有临时captured值的实现owner改变已明确接受。
原61场景冻结观察及原有96消费者在实际源码共157过（10.02s），两源mypy/Ruff/
format通过；三独立视角获有界接受。原R4漏_identity导致的收集回归和一次重复
conftest注册的搭建失败均保留，不混为通过。Windows接口使用真实POSIX文件/FD
桥接，不代表原生Windows或实际Task.cancel验证。
Code434→344（−90），原接收源478→609（+131），系统+41；是职责归位，
不是系统净精简。当前Coding430文件114020行、系统1967源647728行，其余1965源
及13包资源保持。完整P1–P4/领域化/≤15K仍active/partial，距15K还差99020行；
下一步复核相邻offline snapshot、attempt-reference与stage retirement的完整闭包，
优先复用现有owner并消除重复操作，不重做A87已证实共享的cleanup链。
仓库完整可移植探针61过8.03s，原导入边界165过94.28s；探针首版预算表达的
25过/36失败及严格公式修正均保留。详情见[A88交付](key-designs/windows-stage-capture-custody-convergence.md)。

## A87历史交付（2026-11-10，Windows cleanup当前调用链复核）

对A82的‘厚Code IO回借’判断作实物纠正：当前cleanup的orphan/inventory/native
回调已是Code准入和薄装配，实际目录/FD/journal/Job操作均由原Core/Hosting执行。
三独立视角沿叶子核实，不能重新迁移或新增collector并冒称收益。registry与GC锁
边界、两次独立native读取和C5重验不可合并。Code的模式/身份/证明政策继续保留。
真实不同残留是windows_stage_review完整stage capture物理闭包，候选接收者为
现有PackageProduct结合原WindowsStageInspection；不使Worker反向依赖Product。
方案尚未实施/接受，须先冻结旧行为及证明全部接收/适配成本，不预支减量。
完整路径和限制见[当前链复核](key-designs/windows-worker-cleanup-current-path.md)。
本片生产/测试/fixture零变动，完整1967源及13资源SHA同；Code114110/系统647687。
只作静态审查，不声称运行或Windows原生验证。完整P1–P4/领域化/15K仍active/partial。

## A86历史交付（2026-11-10，retained receipt精确查找实际复用）

Code公开单条receipt读取与Core恢复的两处相同扫描，改为直接调用原ReceiptHistory
的find_retained_record。两入口原Product/type/hash校验保留在history构造前；原
read_records(retained_only=True)完整读取、guard/FD退出后按原顺序取首个匹配对象。
V1/V2/archived读取程序原AST保持，没有新索引/缓存/状态/回调。公开DTO/签名/wire
不变，未修改fixture/probe/断言。原恢复/清理固定观察、receipt访问及V2共155过
（19.82s），三源mypy/Ruff/format通过，三独立实际视角窄接受。最终正常格式下
Code890→883（−7）、Core恢复1402→1393（−9）、原ReceiptHistory425→436（+11），
接收侧合+2、系统−5；不是新增模块再包调用。其余1964源SHA及13资源相同。
当前Coding430文件114110行、系统1967源647687行，完整P1–P4/15K仍未完成。
下批继续处理完整效果回借/装配闭包，不把这一精确读取去重代替大范围剩余职责。

## A85历史交付（2026-11-10，Catalog实际factory/type绑定）

退出三个仅返回原factory/类的虚拟getter；Code构造时持有同一实际对象/类，Core
直接使用三个typedfields，不引入profile框架/新owner。owned raw先入pending再
构造wrapper、legacy构造在try外、create失败恢复和原close借用边界保持。既有
实例不再跟随私有module alias晚替换，这是明确接受的内部行为差异，不改公开
DTO/API/持久格式。两原故障hook仅改注入实际class.__init__，完整输入/断言/期望
保持。首64过/2挂点失效失败保留；纠正挂点后66固定及原三个Catalog模块共111过
（42.36s）。另一次测试路径误写导致未收集，也保留为搭建失败，不当生产故障。
Code931→919、Core721→713，分别−12/−8，系统−20；全部接口/格式计账。
当前Coding430文件114117行、系统1967源647692行；其余1965源SHA与13资源同。
两源mypy与Ruff、Core新增区format通过，Code原布局保留；三视角实际窄接受。
完整P1–P4/15K仍未完成。后续从已定位的少层收益继续推进完整效果回借/装配闭包，
不以这20行替代大范围剩余职责，KD011/A33及KD003边界保持。

## A84历史交付（2026-11-10，Catalog legacy-open单消费者间接层退出）

将唯一消费者的私有legacy-open helper并回同一原AppHost owner方法，删除中间
调用/五项callable参数搬运及泛型签名。入口仍依原顺序捕获五个boundcallable，
随后完整操作体AST与旧helper相同；构造/restore仍在try外，失败dispose及覆盖
边界保持。全模块逆向AST证明通过，公开API/DTO/持久字节/状态权威不变。
原31值与35完整custody观察共66过（27.36s），probe/fixture/断言未改；单源
mypy/Ruff/format通过，三视角实际窄接受。接收侧/系统−18，Code0，无新接口。
当前系统1967源647712行、Coding430文件114129行；其余1966源SHA与13资源同。
这是具体少一层调用，不代表系统累计增长或完整P1–P4/15K已经解决。后续继续
核A80实际构造绑定/虚拟getter、A78装配及A56效果回借，原兼容/恢复义务保持。

## A83历史交付（2026-11-10，cleanup authority私有转发退出）

按A82成本审计退出两个仅原样super调用的私有覆盖，直接继承原Core验证程序。
Code cleanup authority源153→113；公开方法/DTO/authority身份及Core源码保持，
普通、UnderGuard和Registered沿同MRO/同self执行，C5仍绑定原公开验证入口。
私有方法反射的实现位置/泛型注解随继承改变，不冒称所有内部metadata不变。
原值及恢复/清理完整固定回归143过（23.09s），fixture/probe/断言不改；三独立
视角窄接受。Code/系统各−40、接收侧0；其余1966源SHA及13包资源同。
当前Coding430文件114129行，系统1967源647730行，距15K仍99129行。
这是少一层调用的实际清理，不代表累计增长已解决；完整P1–P4保持partial。
下一步继续A82已定位的实际接口/装配与效果回借问题，保持公开和恢复合同。

## A82历史交付（2026-11-10，系统成本复核与无消费者适配退出）

对原1845源冻结基线和A81全部1967源逐文件核实：A81系统净增12986，
不是Harness单独增长；Harness本身+31195、Code−23576，其他接收/上游区域
+5367。同期原main提交树净增3583，余9403包含重构及合并适配，不冒称独占归因。
现有证据证明职责归位，未证明全系统更简单；已定位A56效果回借、A80接口层和
A78重复装配等复杂度债。下一实施优先少层/去重，不继续只按Code目录减量选题。
完整组件账、口径及可减/必要边界见[系统成本复核](coding-convergence-system-cost-audit.md)。

本片实际仅删除A81误保留的无消费者私有_HistorySource及import，Code/系统各−10，
接收侧0；其余7个顶层定义AST保持，真实shared builder/公开DTO/持久合同保持。
原67固定加原公开兼容模块77过（5.76s），单源mypy/Ruff/format通过，三视角窄核
无阻断。当前Coding430文件114169行、系统1967源647770行，距15K仍99169行。
这10行不代表全量增长已解决；完整P1–P4/领域化/15K和原兼容恢复义务继续。
必要适度增长仍须有具体职责/复用/全部适配成本依据，不新增或放宽PR gate。

## A81历史交付（2026-11-10，完整delegated Goal Work/Session轮次交接）

从A80 `a442f3c7a`接续；完整family选择/确认、Work创建/交付/完成、报告发布、
失败interrupt、取消/idle结清及release/close重试已接入原HarnessWork Session集成。
固定watermark历史回放/图片水合归原Harness Session集成；直接复用原MultiAgent
control/runtime、Transcript、BlobStore、ContextFactory及ModelCallAllowance。
Code保真实类、Product factory/SDK接缝及纯选择/冻结/报告/evidence政策。

实际Coding430文件114179行、系统1967源647780行：Code−327、Core+477、系统
净+150；其余1963原source SHA与13原资源字节同，全部兼容/policy/绑定/格式成本
计入。是职责迁移，不称系统去重；距15K仍99179，完整P1–P4保持partial。
相对本Goal原137755/634794基线，累计Code−23576（约17.1%），系统+12986；
不把接收增长冒称系统精简，原完整15K/职责及兼容条件保持。

迁前四原consumer模块83过（595.92s），R2原delegated/inherit/release12过；实际
R4同四模块83过（1083.99s），原共享MultiAgent/context/RunHandle与import boundaries
209过（351.83s）。原28值/API/wire及完整38 Task/round/失败/取消观察均已独立冻结，
旧固定及实际同观察通过；落盘显式探针67过（12.01s），六报告场景直接命中新Core
publisher并禁旧helper。三独立实际代码视角无本片具体阻断，Root作有界技术接受。
AI935测试通过，但原覆盖率阈值失败；旧A80同935过且79源完整逐行coverage完全同，
确认既有基线问题并保留，不称整条check-ai或全产品检查通过。
完整合同、候选修正与实际终态见[本片交付](key-designs/delegated-goal-session-convergence.md)。

后续继续普通Worker、启动/Plugin/Session、其余托管/Continuity及入口/存量职责；
原GoalCoordinator/ExecutionScope/PlanningWork直接复用不重复计益。
KD003未实施，KD011/A33仍待用户且不采用；本片不代表整个C12、P3/P4或全Goal完成。

## A80历史交付（2026-11-10，完整canonical Catalog custody）

从A79 `489929afd`接续；canonical create/find/list/display-discovery/open、owned
post-delivery candidate custody、claim/close及Managed Store探针/根观测整体归现有
AppHost/Harness集成与原Transcript owner。直接复用原scan/header/fingerprint、
Factory/Writer及StoreAdmission；不激活dark adapter，不另建catalog对象或状态机。
Code保真实类/公开签名、identity/metadata/compatibility/view政策及薄入口；history
preview/navigation五方法原AST保持，窄history currentness guard的原effects明确保留。

实际Coding430文件114506行，系统1966源647630行：Code−358、Core+947、系统
净+589；其余1961原source SHA同，13原package资源字节同。全部Protocol/泛型/
动态getter/构造/薄方法/import/格式计账，是职责迁移，不称系统净去重；距15K仍
99506，完整P1–P4/Goal保持partial/active。

原五consumer模块88过，R5同88过；原31值/三完整Header bytes对R5固定31+guard
32过，portable期望仅从原raw转换，原31及候选31+guard通过。原35运行场景完整
执行通过；固定重播按原公式约束路径/continuity/title/filename排序，同输入并发
仅允许两条实际旧完整trace。R5同35及直接复用原模块的portable35分别通过。
实际66固定+原88共154过（38.07s）；另外边界172过1旧精确事实失败保留，旧源
同节点复现两条原遗漏，仅RHS加三真实路径，原8func/单节点7assert/scanner保持，
同1节点修后通过。实际AppHost关闭/重开及发现到交互原consumer另14过1旧loader
挂点失败保留，旧源同节点通过；仅retarget实际Transcript loader后同1节点通过，
五func/29assert/原输入及超时全保持。实际5源mypy及源码/probe Ruff通过，完整来源、失败/修正、有限
边界和实际三视角接受见[本片交付](key-designs/canonical-transcript-catalog-custody-convergence.md)。

后续继续普通Worker、启动/Plugin/Session、其余托管/Continuity及入口/存量完整职责。
原summary/dark adapter/Factory._projection均有不同合同，不用较窄摘要代严格路由；
原已有机制直接复用不重复计益。KD003未实施，KD011/A33待用户且不采用；本片不
代表whole hosted_catalog/history、任一整波次或全Goal完成。

## A79历史交付（2026-11-09，完整Product selected revision输入）

从A78 `3e3af964e`接续；selected snapshot到live handle、builtin/external验证、
host distribution lock、package/binding/plugin/resolution及前缀失败关闭整体归原
PackageProduct；实际installed member读取与完整Wheel bytes归原ExactProductSourceFiles。
直接复用原currentness、Plugin DTO/resolution及distribution resolver；Code保真实
Artifact/spec、Product规则/metadata、纯位置值/原owner构造与薄入口，无Code IO厚回调。

当前Coding430文件114864行，系统1964源647041行：Code−280、Core+564、系统
净+284；其余1959原source SHA同，所有类型/绑定/适配/格式成本计入。是职责迁移，
不是系统净去重；距15K仍99864，完整P1–P4/Goal保持partial/active。

旧33值/完整Wheel字节观察先过，外置33加origin guard34过；独立完整source守卫
下的48协调/失败观察旧源和R2候选各48过。实际同81固定加30原消费者111过
（10.73s）；双关闭、前缀关闭首错停止/覆盖主异常、OR短路和两原模块root位置保持。
另原distribution/Resume/真实hosted消费者20过；原相邻架构63过5事实失败保留，
旧源复现既有3项后仅修现有RHS，同5失败节点修后5过（28.05s）；原68节点/
657assert/scanner保持。实际5源mypy、9目标Ruff及7源/probe format通过；统一架构
文件3处原format差异保留，三实际视角无本片阻断。具体相邻回归、
原失败/修正、有限边界与全成本见[本片交付](key-designs/product-selected-revision-custody-convergence.md)。

后续继续普通Worker、启动/Plugin/Session、托管/Continuity及入口/存量完整剩余职责。
原Catalog/Graph/approval/cleanup机制直接复用，不重复计益，不重启已拒managed包装。
KD003未实施，KD011/A33待用户且不采用；本片不代表全Goal完成。

## A78历史交付（2026-11-09，完整Linux恢复与cleanup evidence）

从A77 `9756a965d`接续；registered review/lease repair、payload repair、registered
C5与settled重开、顺序恢复driver、ordinary crash C5、cleanup evidence及POSIX C5
Store寿命整体归原PackageProduct。直接复用原Registry、Storage/RepairJournal、
C5 Coordinator及A77 proof/strict GC。Code保14/8字段真实DTO、公开Evidence/Store、
静态authority身份、wire政策和薄入口；不保扫描/修复/结清厚回调或第二状态机。

当前Coding430文件115144行，系统1963源646757行：Code−829、Core+1437、系统
净+608；其余1954原source SHA同。全部类型/绑定/薄外观/格式成本计入，是职责迁移，
不是系统净去重；距15K仍100144，完整P1–P4/Goal保持partial/active。

旧85 IO观察加reflection共86先过（36.73s），完整树外候选同86过（37.42s）；
另57原API/codec固定加9源origin guard共58过（2.60s），原A77固定121对候选通过。
原消费者迁前128过（279.24s）；实际143本片固定+121原history固定+128原消费者
共392过（502.63s），15原selector排除；相邻owner/import/V2/Windows原消费者
200过（355.40s），1原排除。UID夹具固定后143观察加真实Storage故障hook共144过
（20.65s），旧源同hook按原alias定位另1过；原392/200不因夹具修正重复计数。
原架构迁前24过3旧owner事实失败保留；仅修既有枚举，27节点/208assert/scanner
保持，原native测试唯一hook归实际Storage，1171assert/raises及selector均保持。
实际9源mypy、15目标Ruff、11源format、文档9项/links/freshness/plan/diff通过。
三独立方向/原型/实际代码视角有界接受，完整来源与验证限制见
[本片交付](key-designs/linux-worker-recovery-convergence.md)。

后续继续P1普通Worker整体路径、P2启动/Plugin/Session、P3托管/Continuity及P4
入口/存量的剩余职责；直接复用已有机制，不重复计本片或原引擎收益。KD003仍未
实施，KD011/A33待用户且不采用；本片不代表全Goal完成。

## A77历史交付（2026-11-09，完整Linux history proof）

从A76 `f2c7a6fe7`接续；retention、gated offline、committed V2与strict GC完整
程序归原PackageProduct，纯join/Review派生归Worker.history。直接复用原Journal、
Snapshot/Checkpoint/V2 Reader、PayloadStorage/RepairJournal、A70 native与A76
topology。Code保实际DTO8/41/5自有字段、公开签名/薄getter、政策与原外层锁，不
保Code history/scan/verify厚回调或第二执行器；两种判定及独立重读不合并。

当前Coding430文件115973行，系统1962源646149行：Code−768、Core+1232、系统
净+464；其余1954原source SHA同。全部适配/Protocol/构造/getter/import/格式成本
计入，是职责迁移；距15K仍100973，完整P1–P4/Goal保持partial/active。

旧121固定先过（18.00s）；完整树外候选含8源origin校验122过（33.12s）；真实
worktree同121加原27消费者148过（39.27s）。原型两具体阻断、夹具搭建与collect
失败及147过/1旧hook失败均保留；仅将旧root-swap hook移至实际owner，逆映射后
1171原assert/raises保持。相邻原preflight/commit/V2/checkpoint/receipt和架构
边界203过（114.62s）；8源mypy、10源Ruff、9源format通过，三实际视角有界接受。
全部来源/有限边界见[本片交付](key-designs/linux-worker-history-proof-convergence.md)。

下一批继续registered恢复driver与cleanup authority的完整闭包，直接使用已共享
proof/GC程序，不重复记原引擎收益。其他P2/P3/P4义务继续，单批不代表全Goal；
KD003未实施、KD011/A33待用户且不采用的边界保持，与本片无依赖。

## A76历史交付（2026-11-09）

从A75 `8e5a52229`接续；bootstrap、Arch writer与Worker无引用attestation共同使用
的完整topology read/create/reopen程序已归原PackageProduct。直接复用原RootedIO、
epoch与实际WindowsReceiptIO，无Code扫描/写入厚回调、新manager或重复存储体。
Code保closed kinds、动态wire、hash、准入/GC scope和实际4字段DTO。

Coding430文件116741行，系统1960源645685行：Code−50、Core+103、系统净+53，
其余1958旧源SHA同。全部接收/适配成本计入，是职责迁移；距15K仍101741，完整
P1–P4/Goal保持partial/active。A51同类managed候选继续暂缓，没有换包装重启。

固定79先在旧源全过（3.12s）；迁后同79加原33消费者共112过（19.08s）。POSIX
实际RootedIO/文件/FD；Windows receipt/epoch及GC准入端口受控，取消为同步异常，
close故障在真实关闭之后。三实际视角有界接受；两源mypy及Ruff/format3源通过。
补充原architecture/Product/GC为173过/1前序边界失败，原起点同节点复现；独立修正
A68两条精确primitive导入事实后该节点1过（1.92s），生产不变，不把原整批称全绿。
完整来源与限制见[本片交付](key-designs/backup-topology-custody-convergence.md)。

下一步继续registered恢复的完整history proof/GC revalidation及驱动闭包，不把
backup这一条依赖关闭当全部恢复完成。剩余P2/P3/P4仍按全量账推进，不重复计已有
机制。KD003未实施；KD011/A33原待用户边界与本片无依赖，保持不采用。

## A75历史交付（2026-11-09）

从A74 `20033880e`接续；准备Task/交付Task/未交付operation/cleanup debt/loop五份
状态及prepare/consume/abort/drain完整custody归同一原SessionLifecycleRuntime。
原_prepare_candidate与PreparedOperation状态机直接复用，Code保领域准入/build、
真实DTO与首输入，不留第二manager、镜像账本或完整Code.prepare厚回调。

Coding430文件116791行，系统1959源645632行：Code−88、原Core+160、系统净+72，
其余1957旧源SHA同。完整适配/Protocol/字段/格式计账，是职责迁移。距15K仍101791；
P1–P4和完整Goal仍partial/active，领域化及必要保留成本继续核实。

原真实55消费者先通过；固定37先在旧源全过，迁后同37加原55共92过（114.72s）。
真实Task.cancel/双取消与原native operation、失败候选/debt原对象重试均已观察；
probe的domain/Session/Product端口受控，3.11 completed Future不等于原生3.12 eager。
原test仅7处私有观察读新实际owner，逆映射后全模块AST同，97原断言/raises保持。
另原首输入/UI/Product/Transcript边界35过（174.86s），三个实际视角有界接受。
两源mypy及Ruff通过；原两源全文件format基线已失败，保原无关布局不泛化重排。
完整来源/限制/成本见[本片交付](key-designs/prepared-operation-task-custody-convergence.md)。

继续原全量职责剩余处置，下一批优先剩余启动/装配或Worker完整路径的直接复用。
不把已接入Construction/Graph/Catalog再次计益，不将薄壳行数当必要下界。KD011
仅是待用户的Transcript Continuity导航候选，与本片无依赖；A33待用户、KD003未
实施均保持，完整P1–P4继续，不以本片代替全Goal。

## A74历史交付（2026-11-09）

从A73 `039d787ed`接续；三类Linux payload debt的preview/review/list、repair、
read/reopen和retry完整程序已归原Worker payload组，直接复用Storage、RepairJournal
与RootedSupervisor。Code保13公开入口的真实DTO/type准入、原Product离线政策与根
借用scope，不提供扫描/验证/写日志/删除厚回调。Registered不同证据合同仍待处置。

Coding430文件116879行，系统1959源645560行：Code−129、Core351、系统净+222，
其余1957旧源SHA同；全部薄入口/cast/注解/格式计账，属于职责迁移。距15K仍101879；
P1–P4和完整Goal仍partial/active，领域化及必要保留成本继续核实。

旧113固定先在旧源全过；迁后同113加原消费者164过（107.02s）。首轮111过/2随机
head临时名trace失败保留，只修probe逐名归一并从原raw重算两trace hash。真实IO/
journal/DTO；补充边界16过/1旧依赖事实失败，更新精确模块事实后固定113+原断言114过；
原49架构及1171消费者断言AST保持，三实际视角有界接受、types/static通过。
Product准入端口受控；同步CancelledError不外推Task.cancel，close后
故障不证明close前泄露。当前实现与全成本见[本片交付](key-designs/worker-payload-recovery-convergence.md)。

下一步继续评估prepared-task寿命或剩余启动装配的完整场景，优先原Session lifecycle/
Construction/Graph复用；不把已共享机制再次计益，不将行数窗口当必要下界。KD003
未实施，KD011/A33原待用户工作件保持；完整P1–P4继续，不以本片代替全Goal。

## A73历史交付（2026-11-09）

从A72 `2dfe75fee`接续；Definition approved-resolve和Activation到Session inputs
的完整协调已归原DeclarationHost、ComponentHost及CompositionAssembly。Code保产品
Profile/路径/错误类型/原issuer与Resume准入，两薄入口均接实际消费者。既有Base、
Product及legacy Capability原已共用此程序，不重复计去重收益；Continuity不同合同未合并。

Coding430文件117008行，系统1958源645338行：Code−107，接收原三组件+272，系统
净+165，其余1954源SHA同。全部类型/适配/文档字符串/格式计入；这是职责迁移。
距15K仍102008；P1–P4及整个Goal仍partial/active，必要领域保留成本继续核实。
[本片设计、固定来源与验证限制](key-designs/product-approval-closure-convergence.md)。
固定56先在旧生产通过；迁后同56加原消费者138过（129.84s），原Resume/Session graph
及唯一入口断言31过（13.84s，1原warning）。三实际视角有界接受；原全SDK smoke
在迁前因祖先权限unsafe失败保留，不称全绿；四中断探针是KeyboardInterrupt，
不外推Task.cancel/真实Resume enrollment。

A72全量剩余账保留历史起点，本片只关闭其中审批协调程序；Worker payload recovery、
prepared-task寿命以及P2其他混合职责仍待完整场景处置。后续按复用/依赖/完整路径收益
选择，不把10文件窗口或当前声明语法行当可删预算/必要下界。KD003未实施，
KD011/A33原待用户确认边界保持，不自动采用。

## A72历史复核（2026-11-09）

生产停在已接受A71 `2c322a821`：Coding430文件117115行，系统1958源645173行，
本次新增生产精简0。430源码SHA/行/定义/import与28组处置已重核；领域语义、
公开兼容与当前实现分账，未发现可证的>15K必要下界，也未证明目标必可达。
9607当前语法候选行不是保留成本或删量；完整P1–P4、≤15K及兼容恢复要求保持。

[全量剩余职责与保留账](coding-responsibility-remaining-audit.md)明确全部组的原
owner、现成复用、残留义务和三视角限制。最大已定位P2十源交互窗口12560行，
不作为可删预算；下一候选是原owner的完整Definition approved-resolve及Activation
到Session inputs程序，接口/实物/成本尚待设计，不能重复计已有Base/Catalog/
Graph/cleanup收益。Worker完整payload recovery与prepared-task寿命为备选。
KD003未实施；KD011/A33原待确认边界保持，继续无依赖的整体职责工作。

## A71 已交付状态（2026-11-09）

A71 从`d86482c26`继续完整 P1–P4。Windows Installation root lineage 的完整
bind/inspect/restore intent/receipt publication、删除前驱重放、代际围栏、codec
及write-or-match归原Harness Plugin Management。直接复用原receipt IO、目录
组件及实际DeletionTransaction.events/close；Code不提供历史/读写厚IO回调。
Code保七字段真实DTO、key/path/epoch/runtime准入及九条薄入口，原restore事务
操作体不变。整lmux命令迁移因底层已复用且交互混合明确拒绝。

Code674→328（−346）、Core592、原restore857不增行，系统+246；当前Coding
430文件117115行、系统1958源645173行，其余1955旧源SHA相同，距15K仍102115。
这是职责迁移，含全部协议/绑定/薄入口/格式成本，不称系统净精简。

86固定旧观察在旧生产先86过；迁后同86加原4 lineage共90过（3.03s）。真实
receipt文件/FD/原deletion解码与sequence，native ACL/identity端口受控；fixture
保完整结果/异常/tree及全有序trace的条数/SHA，原raw/source guards留存树外，
expected不来自替代实现。旧30原消费者和capture90终态分别留存，不累加重叠。

更广原消费者117过、42原Windows skip、7原selector排除（45.55s）。两原测试
24/959 assert及raises AST、节点与参数/选择器不变，仅实际hook归新owner。
首mypy发现target缺只读root_path_digest；最小Protocol补足后2源通过，无Any/
ignore或运行检查。三个实际代码视角有界接受，原stage/重试/异常差异保持；Ruff/格式、文档9项、
依赖freshness、plan和diff检查通过。
完整来源、成本及限制见[本片交付](key-designs/windows-installation-root-lineage-convergence.md)。
完整Goal未完成，继续重核剩余P1–P4与必要领域保留成本；KD003、KD011/A33
原未实施/待确认边界不自动采用。

## A70 历史状态（2026-11-09）

A70 从`12f67b71a`继续完整 P1–P4。Linux H6 Product native release 的完整
review/install/repair、receipt/source 校验及当前 launch material 读取归原
Harness Package Product，复用既有 Posix Product owner、A67 verifier、A69
approval owner.current、Wheel inspector、noreplace 和 write_all。Coding 保留
公开 DTO/Reader 身份、精确签名和纯 Product profile/类型/版本绑定，无 Code
厚 IO 回调。原临时安装清理、repair 保留 debt、双审批/身份校验及不同 readback
次序保持；原 receipt/RECORD/source 数据无需迁移。

Code 两源735→225（−510）、新 Core688、系统+178；当前 Coding430文件117461行，
系统1957源644927行，其余1954旧源SHA不变，距15K仍102461，完整 Goal 未完成。
全部类型、profile、薄适配及格式均计账，不把职责迁移称作系统净精简。

123 固定旧观察在原源码下全部通过；迁后同123加原A67 reader112合计235过
（5.31s）。真实 inert ZIP/文件/FD、短写/零进展、取消/中断、fsync/close、
审批变化、stage/root 替换、rename 冲突、receipt/source 和六条同盘重试均有
原观察；原随机 stage 名归一漏项导致的100过/17 trace失败记录保留，只修
探针后在原source guard下另捕稳定观察，未用替代实现生成 expected。

原candidate-wheel/native CLI/C54与A69审批消费者148过、16原live/host节点
排除（297.21s）。三个独立设计及实际代码视角无本片阻断；3源mypy、Ruff及
格式通过。多stage快照归一的盲点用真实目录名断言补齐，同一节点在原12f干净
验证worktree和迁后各1过；fixture不变、不作为额外场景累加。验证worktree确认
干净且分支已被任务HEAD包含后安全删除。原消费者仅14行hook改动，1171原
assert/raises与选择器保持；C54只去过期import事实，49assert/全部test函数AST同。
文档/依赖/plan实绩及来源见[本片设计与交付](key-designs/linux-product-native-release-custody-convergence.md)。
KD003 bytes-import、KD011/A33 原待确认事项及其余 P1–P4 保持剩余，未自动采用。

## A69 历史状态（2026-11-09）

完整 P1–P4、Coding ≤15K、Harness 复用及兼容恢复目标保持。A69 将 native
approval 三值机制、完整history decoder和Rooted读写归原Worker.history，并让
Linux/Windows调用同一纯replay/CAS/absent/capacity/create程序。Code保真实公开
dataclass/四classmethod精确签名及Product准入/GC/currentness；两平台原字节、
锁、追加和cleanup差异保持。Code −206、原Core −48、新Core +432、系统 +178；
当前Coding430文件117971行、系统1956源644749行，距15K仍102971，Goal未完成。

101固定旧观察、原Rooted/Windows/引用checkpoint/native reader及边界首轮490过/
2源码归属事实失败；最小修正后原两节点2过（17.54s），未重复已过490。三独立
设计及实际代码视角有界接受，3源类型/Ruff/格式及文档/依赖/plan通过；全部成本
和原夹具失败/修正、来源、接受边界见[本片工作件](key-designs/native-approval-journal-convergence.md)。
版本bool接纳、浮点canonical拒绝及revoke duck追加后读失败的旧不对称均未隐改。
native install/repair、KD003及其余职责继续剩余，KD011/A33待用户事项未采用。

## A68 历史状态（2026-11-09）

完整 P1–P4、Coding ≤15K、Harness 复用及兼容恢复目标保持。A68 将临时
Continuity payload 的完整写入/双FD与inode固定/身份删除/取消结清归原Continuity，
复用原write_all及await_owned_task；Code保留Bridge准入、限额、来源/cwd和
restore/abort/lease业务，32原业务声明AST不变。Code −196、Core +219、系统 +23；
当前Coding430文件118177行、系统1955源644571行，距15K仍103177，Goal未完成。

43固定旧观察及17原Bridge消费者before/after各60过/1原skip；更广真实消费者、
边界与持久探针151过/1原skip（31.43s），不重叠累加。原安全规则拒绝本机
0775工作区祖先的失败记录保留；命令级私有输入fixture纠正，不改Product或runtime。
三个独立设计/实际代码视角有界接受，类型/Ruff/格式/文档/依赖/plan检查通过。
私有DTO定义模块与bound-method反射位置变化明确单列；无产品持久schema变化。
KD003 bytes-import仍draft/not-started，native install/repair及其余职责仍待收敛，
详见[本片设计及交付](key-designs/continuity-payload-custody-convergence.md)。

## A67 历史状态及独立清理修复（2026-11-09）

完整 P1–P4、Coding ≤15K、Harness 复用和兼容恢复目标保持。A67 将 generated/
installed Linux H6 release 完整惰性读取与校验归原 Worker，复用原 bounded-prefix
和 ELF 校验；Coding 保留产品回执/审批/GC/安装及修复。Code −295、Core +365、
系统 +70；当前 Coding 430 文件 118373 行，系统 1954 源 644548 行，距15K仍
103373。职责归位不冒称系统净精简，整个 Goal 未完成。

105 固定旧观察加 1 原 unit 的 before/after 各106过；持久探针及原消费者117过、
1 host-runtime 排除。设计及实际代码三独立视角均无本片新增阻断，静态/文档/依赖/
plan 检查通过。纯迁移提交 `b4f44cd6e`；独立关闭了原目录 fstat 失败泄漏，
原期望字节保留且仅显式调整一个清理差异。故障验证首轮111过/2探针定位失败，
修正后同2节点2过，生产修复未变；详见
[本片设计及交付](key-designs/linux-native-release-reader-convergence.md)。
KD011/A33 待用户事项仍未采用，完整安装/repair 与其余职责继续在剩余范围内。

## A66 历史状态（2026-11-09）

完整P1–P4及Coding≤15K目标保持，优先复用Harness现有组件、公共机制归原owner，
保持高内聚低耦合与架构简洁。A65已提交`b155b4b03`；A66把两平台candidate-update
完整重试证明/CAS/revoke/原lifecycle程序归一，Code−143/Core+120/系统净−23。
当前Coding430文件118668行、全系统1953源644478行，距15K仍103668，未完成Goal。

96固定旧对照+1原unit的before/after各97过，同96持久探针96过；原消费者83过/
1native skip/1host deselect，实际三代码视角无本片阻断。三源类型/Ruff/格式及既有
文档、依赖与plan检查通过，完整成本和限制见[执行记录](coding-responsibility-convergence-progress.md)。
KD011/A33明确待审事项不据整体Goal自动采用，继续推进无依赖的剩余完整职责簇。

## A64–A65续接历史（2026-11-09）

继续用户完整P1–P4及≤15K目标，补充优先复用Harness既有组件、公共机制归原owner、
高内聚低耦合与简洁架构要求。A63实物已保存为本地checkpoint `9a5285723`并复制
至专用`harness/coding-convergence-delivery`任务worktree，原lane与用户改动保留。
当前430个Coding文件118811行、完整系统1953源644501行，整个Goal未完成。

57份新增本地probe已显式化，原CI目录发现集合及catalog/workflow不扩大；计划
生成恢复，266节点执行通过、2538节点全部收集。完整builtin bootstrap两程序
已接通Harness并共享原历史证明，Code−176/Core240/系统+64；固定before/after
各32过，两源类型/Ruff通过。较广首轮240过/7架构事实失败/43原skip，七失败修正后同节点7过；实际三代码
视角复核后有界接受。既有check-ai937过/7deselect与原覆盖阈值通过。
逐文件R2与最新欠账见[执行记录](coding-responsibility-convergence-progress.md)。
KD011/A33仍待原明确确认，不据本次Goal自动接受其具体候选。

## A63历史计量（2026-11-09）

Coding **118987行**、系统 **644437行**（1952生产源），累计Code少**18768行
（13.62%）**，距≤15000仍差**103987行**；不是开发工作量完成率。完整P1–P4及
最终领域化未完成。原当前main已fresh fetch核HEAD/origin均2aa2f7deb、0/0，未发布。

完整operator查询的activate-through-dispose协调归原Session，实际复用Worker/
Hosting/C5/Graph/Provider及原Source适配；Code保领域选择/协议/配置与薄入口。
两Code845→721（−124）、接收320、系统+196，全部接口与适配计账，不冒称系统
去重。actual88对照通过、原架构4过、3源类型/Ruff/format通过；原existing59过/
1hostskip/1C54旧清单失败，唯一事实条目修正后同节点1过，首失败保留。

三代码视角及Root有界采用完成；旧期待未重录，private MRO/故障查找、受控值/
端口不证明真实native/完整授权等限制保留。其它1949原源逐SHA未变。KD011仍
独立未接通、不计候选收益。详见[执行记录A63](coding-responsibility-convergence-progress.md#a63完整operator-query协调归原session)。

## A61历史计量（2026-11-09）

Coding **119111行**、系统 **644241行**（1951生产源），较原Coding基线累计少
**18644行（13.53%）**，距≤15000仍差**104111行**。不是工作量完成率，完整Goal
及P1–P4未完成。R6 Continuity仍独立待用户，未接通、不计候选收益。

沿已接受KD008联合方向，复用已审旧完整候选并重新核当前采用条件，原Canary
construct/start/failed-reclaim/rollback/recover/normal-close归原Worker，同self/原锁/
原注入authority保持。Code保真实Status/Error/显式签名与binding/准入政策。当前
原五入口3191→2587→本片后2119，Operator513和Canary剩余binding验证未完成。

实际两源Code−468/接收569/系统+101，全成本归责任，不称去重。当前真实45原节点
加3既有树外兼容检查48过、四原架构过、两显式源类型及Ruff/format通过；原ABI/
旧Status pickle只读复用，实际Core/self/lock见证通过，三代码视角及Root有界接受。
全原生/取消/反射/性能等限制保留。详见[执行记录](coding-responsibility-convergence-progress.md#a61完整canary生命周期在当前联合条件下接通)。

## A59历史计量（2026-11-09）

Coding **119579行**、系统 **644140行**（1950生产源），较原Coding基线累计少
**18176行（13.19%）**，距≤15000仍差**104579行**。完整P1–P4及15K未完成。
本片原Session接管live恢复完整协调，Code保真实DTO/receipt/selection/Worker政策；
实际Code−194/Core+485/系统+291，所有接口与格式计入，职责迁移不称净去重。

原六文件业务103过、架构4过，实际3显式源类型/Ruff与两源格式通过；三视角代码
审查及Root正式有界接受完成。两真实Code数据类/原authority不复制，不增加controller/
日志/队列。四原测试观察名随唯一私有state更名，40个assert保留。全原生/取消交错/
反射及性能未证明。详见[执行记录](coding-responsibility-convergence-progress.md#a59原session的live恢复完整程序接管)。

同步前A59实物系统644120；随后已保存全部本地修改并快进合入main四提交至
`2aa2f7deb`，上游另加系统20/Code0，单独计账。两个AppHost重叠文件自动归并并保
原业务，A59三源/test逐字未变；同步后24项专项回归及两源类型/Ruff通过，不重报103整批。当前系统比
原起点多9346，按用户现行职责/复用/必要适度成本准则审，不把增长称为精简收益。
控制lane其它未提交工作保留，本任务无commit/push。

## A58历史计量（2026-11-09）

Coding **119773行**、系统 **643829行**（1949生产源）。比原Coding基线少
**17982行（13.05%）**，距≤15000仍差**104773行**；这不是开发工作量完成率。
本批完整恢复首输入提交/unknown/发布围栏/guard程序归原Transcript可选profile，
Code保wire/V1V2/Plan/owner/composition政策；实际Code−620/接收+888/系统+268，
含兼容导入与Worker去反向依赖。系统相对原起点多9035，按现行职责/复用/必要
适度成本准则计，不将迁移称净删除。完整P1–P4和15K仍未完成。

原168回归首轮164过/4失败，旧基类符号兼容修复后同4节点通过；另原Worker5及
DAG/采用2节点通过，初架构其它3过。不是最后整批168重跑或首次全绿。最终
6显式源类型、3源Ruff/格式通过，实际代码三视角无本片剩余已识别阻断。Core
profile源不改标准Transcript默认路径，不新增writer/日志/schema/权限，原生/
全取消/全ABI/性能等限制保留。详见[执行记录](coding-responsibility-convergence-progress.md#a58恢复首输入完整程序归原transcript及前序依赖环关闭)。

刚fetch远程main，任务HEAD/origin均`cfbe1286f`，0ahead/0behind，无新增主线待合；
控制lane其它未提交工作未动，本批无commit/push。下一步继续原完整Goal其它大
程序收敛，不重复已交付的writer/committer或恢复协议。

## A57历史计量（2026-11-09）

Coding **120393行**、系统 **643561行**（1948生产源），较原Coding基线累计减少
**17362行（12.60%）**，距≤15000仍差**105393行**；不是开发工作量完成比例。
本批完整Windows orphan/recovery取得、payload物理目录盘点及两实际reader的GC
程序已接入原Product/StageIO，Code−100/接收+255/系统+155为职责迁移成本。完整
P1–P4/15K仍未完成；必要适度系统增加按现行准则审，不以搬迁冒称去重。

最终145项相关测试通过；真实FD探针补POSIX标记后同25项复验通过，不重复累计。
7源类型/Ruff/格式通过，C54仅补一个精确依赖key且原失败节点复验通过。代码
三视角已检查实际源；最终接受及原生Windows/完整ABI等限制见
[KD008 §23](key-designs/worker-product-runtime-convergence.md#23-a57完整windows查询取得与同构reader复用)
与[执行记录](coding-responsibility-convergence-progress.md#a57完整查询取得归位与两reader的真实复用)。

## A56历史计量（2026-11-09）

用户已接受KD008原联合职责方向，15份实际源码已接通并完成代码三视角有界接受，
不是仅有树外候选。Coding **120493行**，系统 **643406行**，1948份生产源；相对
原基线Coding减少**17262行（12.53%）**，距≤15000仍差**105493行**。这些是物理
源码差额，不是开发工作量完成率；整个P1–P4与15K目标仍未完成。

本批职责迁移Code−620/接收+1777/系统+1157；实际项目导入排序另减10空行，最终
Code−629/接收+1776/系统+1147，格式不冒称去重。系统相对原起点增加8612行，按
用户最新准则逐项审复用与必要成本，不把严格净减重新设为门槛。同步主线带来的
+190 Code/+1169系统单独列账，不算本批迁移成本。

最终相关104项通过，原接收/架构26项中25过、1项C54精确消费者清单失败，维护
原Map后仅复查失败节点通过；原断言/扫描保持，没有新增平台、门禁或目录豁免。
15源Ruff/格式/类型检查通过，三视角无本批剩余已识别阻断。实际原生Windows、
物理故障/断电、全部取消交错与公开反射/旧pickle不因此验证。完整证据及职责见
[KD008 §22](key-designs/worker-product-runtime-convergence.md#22-a56联合方向接受实际接通与主线同步)。

本任务分支已合入当时远程main `cfbe1286f`；控制lane有其它未提交工作，未强行
同步或改动。下一步处理仍在Code的orphan/inventory及真实payload目录查询，
继续复用原Worker projector、Journal、Resources和Hosting；本批未commit/push。

## Goal 描述

A43历史局部实施将四类Windows stage review的纯记录reader归原Worker.history，直接复用Resources RecordSchema；Code保原公开数据类/42自身字段、全部原encoder与业务验证。当时Coding **120999行**、系统 **638590行**；本片Code−187/接收+107/系统−80（其中4行为导入空行），累计Coding减少16756行（12.16%），系统仍增加3796行，距15K仍105999行。按目标减量差额约13.65%，不是开发工作量完成比例，完整Goal未完成。12实际兼容/子类/冷导入节点通过，含784原读取观察及真实Core调用见证；首轮64原业务通过与4夹具表示失败历史分别保留，不能写成一次76最终全绿。五实际源类型/Ruff/格式通过，三独立代码视角无本片剩余阻断，实施owner已作有界接受；A33图及完整发布证明链未因此接受。详见[执行记录](coding-responsibility-convergence-progress.md); 前序实施与原Catalog/Session欠账均保留在原条目。

下一整簇已转入[Windows历史发布与持久重读的设计输入](key-designs/windows-worker-semantic-convergence.md#12-后续整簇选题历史发布与持久重读)：原9源2353行/59定义、原23业务及21组协调旧观察已固定。A31已完成[三个账本的必要前置归位](key-designs/windows-worker-semantic-convergence.md#13-a31三windows账本作为发布链必要依赖归位)，A32进一步完成[Supervisor/C5托管归位](key-designs/windows-worker-semantic-convergence.md#14-a32supervisor-与-c5-的完整-windows-托管路径)；真实GC/offline/Desired/backup/native获取与publication/persisted/cutover接点仍须闭合，九源整体尚无已接受替代，不以这批依赖或孤立搬DTO代替完整路径。 A33已否决Code−107/系统+100的小叶候选；[完整Product协调的R2职责图](key-designs/windows-worker-semantic-convergence.md#15-a33-r2完整历史协调的职责重定界待用户评审)经三视角方向审查后待用户评审，接口/完整成本与实施尚未接受；A34在原Source边界内独立推进，不采用该待审图。

A35已完成[完整Bootstrap的三视角审计](key-designs/startup-session-assembly-convergence.md#13-a35完整-session-构造路径审计与下一候选边界)：否决整搬2196行；A36完成真实计划/selection callee的内部收敛，尚不等于608/723行整场景收尾。A37随后[关闭五项测试项目根夹具失败并复核候选成本](key-designs/startup-session-assembly-convergence.md#15-a37五项资源夹具失败关闭与后续候选成本复核)：只补两处本地AGENTS.md，原五节点全过，105条断言和1911生产源不变。完整capability准备闭包试算仅净减14行，未采用；不再将608行混合池当大块删除预算或轮转小helper。A38的[完整延迟子图mixin候选](key-designs/startup-session-assembly-convergence.md#16-a38完整延迟-component-子图候选未采用)则Code−164/接收+306/系统+142，经三视角否决，不接入、不将单一协调体泛化计作去重。后续转向未完成完整业务簇，继续要求原owner复用、旧体退出与系统全成本证据，不重复已交付的构造、publication、cleanup或Catalog机制。

在保持楼上现有用户能力、存量数据、公开入口和失败恢复合同的前提下，对整个Coding层按职责进行重构和迁移，使Coding逐步收敛为编码领域能力、产品Profile与内容、必要的领域政策以及薄适配。对每项通用机制，先核对Harness及其它原组件已有的实现、配置和端口；能直接复用就删除Coding重复体，能通过现有配置表达差异就只保留产品输入，确有缺口才最小扩充原owner。将执行、存储、生命周期、托管协议和平台操作分别归回其正确子系统，避免Coding或接收层形成第二套引擎。以高内聚、低耦合、单一事实权威和可验证的端到端兼容为约束，按完整业务场景分波次替换、删旧和交付，最终使Coding不超过15,000物理行。持续消除系统重复实现；在优先复用、确有缺口且符合职责边界的条件下，允许必要且适度的系统源码增加，逐项解释收益与全部成本。5,000行作为进一步优化方向，不以删除能力、搬换目录或隐藏实现达到指标。

## A49历史计量（2026-11-09）

Coding **120932行**、系统 **641090行**（1932源）。原完整批停/清债机制归原AppHost
managed stop，Code仅保真实原类、显式构造和结果呈现；Code−91/Core+111/系统+20
为迁移成本，非净删。详见[专项边界](../apphost/managed-stop-batch-convergence.md)。
累计Code减少**16823行（12.21%）**，距15K仍**105932行**；系统仍比原起点多**6296行**。
按必要Code减量约13.70%，不是工作量完成率。8原检查和7架构过，六比较在1个树外
对照节点内通过；19项原失败/准入受限结果未绿。原G17在未改产品/原断言/超时下分别有
观测与无观测各1次通过，但历史超时根因未证，不称修复；完整P1–P4/15K/系统净减未完成。

A50静态复核：完整双source准备的helper候选经三独立处置后不接入；其Code−78/
接收+80/系统+2不入实绩。1932生产源逐SHA保持A49，新增生产精简0，不增接口层
换表面删量；见[KD009取舍](key-designs/startup-session-assembly-convergence.md#17-a50双-managed-plugin-source-的-helper-候选不接入)。

## A48历史计量（2026-11-09）

Coding **121023行**、系统 **641070行**（1932源）。本片Code−105/原AppHost+201/
系统+96为职责归位，非净删；原公共构造/字段/产品政策保持，完整外层应用寿命直接
复用原AppHost启动/phase/wait，详见[接受边界](../apphost/local-startup-convergence.md#a48完整外层应用寿命归原apphost2026-11-09)。
相对原基线Code净减少16732行（12.15%），距15K仍106023行；系统仍增加6276行。
按所需Coding减量约13.63%，不是工作量完成率；完整P1–P4及最终净减条件未完成。
原业务59过/1项G17迁前同失败，四当前原点对照及19架构检查通过；不写整批全绿。

## 主线再次同步时计量（A47，2026-11-09）

当时main与重构分支同步到`38d87db31`，Coding **121128行**、系统 **640974行**
（1932生产源）。相对A46的+278/+947全来自远程主线，不能计为本Goal新增迁移成本或
收益；原137755/634794基线及15K/系统净减条件不重设。A47载荷准备候选未安装，
其−217/+326/系统+109不入实绩，见[候选取舍](key-designs/worker-product-runtime-convergence.md#17-a47载荷准备候选不独立接入)。
完整P1–P4仍未完成；以下A46等数字保留为历史快照。

## A46历史计量（2026-11-09）

原C5 Resume parent登记/回读/封存/恢复证明已归原Worker Coordinator，Code只保领域
准入、原binding/同锁及错误薄适配。Code−106/Core+155/系统+49为明确职责迁移成本，
不称净去重；设计及实际代码三视角已完成有界接受。当前Coding **120850行**、系统
**640027行**（1927源）。97过/8原host-runtime skip；124原观察在两个对照节点内，
不冒称跳过的两个Host场景已验证。其余1925源同A45，完整Goal仍未完成，原15K/系统
净减条件与待用户重要图保持，详见[执行记录](coding-responsibility-convergence-progress.md#a46c5-resume-parent完整交接归原owner)。

A45保留为历史：五canonical reader复用Code−60/Core+16/系统−44，实际1040项与另1项
冷启动通过，三视角有界接受；不与A46的迁移成本混称净收益。

## 主线同步计量（2026-11-09，A45之前）

用户要求及时合并远程main，控制lane与当前任务分支均已从8ad6b6098快进到1665cff34。
原本地498条修改/新增路径已备份并恢复；唯一内容冲突保留Code薄入口，将上游模型列表
修复与事件投影去重接到原AppHost共享owner，未恢复旧重复体。同步当时Coding
**121016行**、四生产根**640022行/1927文件**；相对同步前分别+17/+1432行，不能记为
本Goal精简成果。原137755/634794基线及15K/系统净减目标不重设；A43/A44数字保留为
同步前历史快照。完整差异与验证见[执行记录](coding-responsibility-convergence-progress.md#主线同步2026-11-09)。

## 新基线与计量

2026-11-07静态复核：Coding **427文件、137,755行**；四生产根的多语言源码 **1,845文件、634,794行**。均包含当前未提交实物，不能只用HEAD `8ad6b6098f1c24c8cfb6f4d9d290e99bc74d618d`还原本轮基线。完整内容指纹保存在产品树外，基线清单SHA256为 `61d7c2a6f5ffb077bab403788ce7683ce0771f481641ff975ab505defe13ad77`。

实施前将前序交付保存为可追溯提交或源码归档，并固定本轮源/测试起点；不覆盖既有脏改动、不擅自发布。若合入更新改变起点，记录差异和新旧映射，不把其他交付的删除算成本Goal收益。

| 当前重点职责簇 | 当前文件 / 行数 | 本轮解释 |
| --- | ---: | --- |
| C07 Worker | 110 / 38,751 | 首选整簇；原Supervisor、分段历史及Windows provisioning已有共享成果，先排除已交付部分 |
| C01/C15/C17 启动与Session装配 | 27 / 18,781 | 核对原构造、Graph、Registration和生命周期端口，删除产品回调中的中性协调 |
| C02 托管接入 | 27 / 8,578 | 共享会话桥接归原AppService/AppHost边界，产品身份与投影留Coding |
| C03/C04 恢复与Continuity | 17 / 7,916 | 区分原Session/Transcript机制、来源和产品恢复政策；既有bytes候选仍未实施 |
| C09/C10 兼容、包与Product管理 | 46 / 17,094 | 按实际存量义务和原Package/管理能力处置，不据legacy命名删支持 |
| C11 CLI、C12 Goal/Work适配 | 50 / 17,332 | 薄入口和领域任务保留；只收敛尚未归位的共同机制 |
| C13/C14 LSP/Arch | 34 / 9,296 | 编码语义保留；通用进程、IO和寿命依实际owner复用 |
| C08 已交付私有数据 | 31 / 7,139 | 已接管机制不重做；本轮仍核残留声明/绑定归属，保留原数据与失败合同，不把前序收益重复记账 |
| 其余职责组 | 85 / 12,868 | 全量纳入处置；包含内容、UI、策略及验证入口，不推定都能迁移 |
| **合计** | **427 / 137,755** | 上述各组不重叠；组大小不等于可删除量 |

达到15,000行还需从Coding归属移除或精简122,755行，约89.1%。这是目标差额，不是已经证明的可删池或工作量估计。首轮架构收敛须验证目标可达性；若存在确切领域保留成本冲突，给出源码、用户价值和选项再评审，不静默提高上限或削弱原合同。

计量采用与A86相同的物理行和四生产根口径，分别报告：Coding归属净变化、各接收组件全成本、职责迁移量、真正消除的重复实现及系统净变化。移入其它产品包、Plugin、配置脚本或生成代码的Coding领域实现仍计入Coding归属；tests/examples/docs和声明资产另列，不能藏复杂度。前序8,087行收益不抵扣本轮目标差额。

## 职责与接收边界

| 稳定职责 | 优先复用的原owner | Coding保留 / 禁止迁入项 |
| --- | --- | --- |
| Worker状态、历史、恢复与租约 | Harness Worker；Journal负责物理日志；原Hosting/Workspace/Resources负责对应原生操作 | 编码插件的选用、批准与Profile；不同事实不合并成一份“万能日志” |
| Plugin选择、装配、安装与退役 | Harness Resources/Capabilities、Plugin Management、Package Product | 产品内容、信任选择和必要布局；不再造Product manager |
| Session构造、输入、生命周期与恢复 | Harness Session、Transcript、Runtime；Agent loop仍归Agent | 编码Profile、提示和恢复选择；不搬原Agent内核到Harness、不重建队列 |
| 配置、模型与调用机制 | 原Harness Config/Model Input及AI、Agent各自owner | Coding默认值与领域选择；provider/auth不塞入公共Harness |
| 嵌入式与托管适配 | Harness公共控制端口；AppService/AppHost承接其协议、租户与连接寿命 | Coding注册、身份和业务投影；Harness不持有托管线协议 |
| Goal/Work与Method | 原HarnessWork及Method，以及各自已有集成 | 编码任务、方法选择与仓库验收语义；不重写规划/Work引擎或新增harnessmethod |
| IO、内容传输和事实记录 | 原Resources、Artifacts、Journal、Transcript等各自owner | 原数据形状/路径政策；不复制底层存储或新建第二权威索引 |
| UI交互与终端呈现 | 原HarnessTUI/TUI | Coding最终文案、主题和领域命令；不将终端依赖塞入Harness |
| LSP/Arch与仓库工作 | Coding领域能力，通用资源通过已有声明依赖获得 | 保留真正编码语义；不为减目录行数伪装成通用组件 |

迁移实现必须放入对应子系统，**不新增Harness根目录工具堆**。Harness不反向依赖Coding、HarnessWork/Work、Method、AppService/AppHost、Channel或UI；上层集成依赖公共底座。装配根可协调依赖，运行期叶子只接收必要的窄端口和值，不传大Session/Product/context或service locator。

每个机制和持久事实有唯一权威，允许多个合法实例，不要求全局单例、统一锁或统一存储。Product策略变化应主要影响Profile/适配；通用机制修正应由原owner一次完成，不要求多个产品同步改相同算法。

## 实施波次与第一项建议

| 波次 | 要交付的完整场景 | 退出条件 |
| --- | --- | --- |
| P0 更新架构与删除预算 | 复用原427文件/28组清单，按当前调用关系确认迁入、复用、保留、退出；更新环境/组件/关键交互及重要决定 | 每个选中场景有唯一owner、既有能力对照、全部替代成本、旧体删除清单；重要工作件提交用户评审，完成专项三视角评审 |
| P1 Worker职责归一 | 已准入Worker从选用/批准、启动、状态查询，到停止、重开恢复与资源结清；按依赖顺序分可交付子切片 | 原Worker/Journal/平台实现真正承接机制，Coding只留产品决定；不重做已有分段历史或provisioning，不保留平行执行/恢复后端 |
| P2 启动、Plugin与Session装配 | 普通会话新建、恢复、失败构造、插件刷新/关闭及清理重试 | 共用原构造/Graph/生命周期，Code回调只给领域输入；子资源未关闭时依赖和重试凭据不丢 |
| P3 托管、Continuity与执行适配 | 嵌入式与AppService入口复用业务owner；原导入/恢复及Goal/Method/Work适配沿原权威执行 | 无第二桥接业务、队列、日志或状态投影；owned/non-owned与平台差异按原合同处理，不提前采纳未就绪bytes设计 |
| P4 入口与存量收敛 | CLI/SDK/UI声明和投影、包管理与兼容入口最终归位 | 无支持义务且无生产消费者的代码才退出；逐组完成保留/复用/迁移/删除说明，最终核算与整项代码评审 |

**首项建议：先做P1的Worker专项设计，选一条“既有Supervisor记录→查询→重开恢复→结清”的纵向路径。** 当前[产品Journal](../../../../src/loushang/coding/package_product_worker_supervisor_journal.py)已继承原[WorkerSupervisorJournal](../../../../src/loushang/harness/worker/journal.py)，[历史入口](../../../../src/loushang/coding/package_product_worker_history_segments.py)也已薄转发至原Worker；应从其余产品存储/恢复协调与实际callee入手，先证明哪些能由现成能力覆盖，再决定接口扩充，不把110文件整包搬家。

其它波次可因依赖或确定性调整顺序，但须记录理由。按一个业务职责簇交付，不为填数字长期追逐零散helper；某候选不能形成职责或净删收益时记录保留/拒绝，转向下一完整场景。新接口若实际需要改变既有合同，明确列为行为变更、单独设计验证，不冒称机械迁移。

## 每个切片必须给出的设计与证据

1. **现有能力对照：** 原调用点→已有组件/配置/端口→不能满足的具体合同→最小改动→删掉的旧体。只是名称相似或已有Protocol，不算实现可复用；也不能忽略已存在的实现。
2. **职责与交互：** 给出owner/协作者/非owner、必要接口和依赖方向；只更新受影响的上下文、组件与关键成功/失败/取消/恢复路径。组件边界不自动要求新进程、新服务或新持久日志。
3. **完整成本：** 编码层下降、接收方新增/删除、兼容适配、声明/代码生成和格式变化分别列账。纯职责搬迁可以有明确必要成本，须事先解释；它本身不记为重复消除或系统净减。
4. **兼容与失败：** 原格式/ID/路径/锁/权限/错误优先级/授权、partial与unknown结果保持；不能靠更严拒绝、盲重放、全局锁或清空状态使方案成立。
5. **删旧与回退：** 新旧调用者使用同一机制，切片交付时原重型操作体退出；必要公开兼容导出只薄转发。按完整切片回退，不同时维护两套事实与恢复逻辑。
6. **有边界的验证：** 实施前固定相关旧行为和输入，优先复用原测试，只补真实缺口；通过的检查没有新变化或未解疑问不重跑。必要对照说明其源与覆盖范围，不扩称完整基线。

高内聚/低耦合通过变化场景判断：改Coding策略不应修改共享内核；修共同机制不应在多个产品复制修复；嵌入式和托管入口消费同一业务合同；关闭失败保留原资源权威及可重试清理。涉及读取/回放的变化，不新增每次查询全史重解析或跨Session串行化；需要性能主张时用同工作负载前后比较，不虚构数值门槛或新矩阵。

## 验收与执行边界

| 验收项 | 本Goal完成条件 |
| --- | --- |
| 领域化 | 427文件全部有当前处置结果；Coding只保留编码领域、Profile/内容、产品政策和必要薄适配，混合文件按职责拆清，不据文件名一刀切 |
| 数量与成本 | Coding归属≤15,000物理行；全系统仍相对634,794行原基线完整报告。职责与复用准则成立时，允许必要且适度增加；全部接收/兼容/补偿成本计入，不把目录迁移计作去重 |
| 真正复用 | 已覆盖的算法直接调用原owner；必要扩充有合同差异证据和真实消费者；重复的执行/持久化/恢复机制退出，不另造框架掩盖 |
| 功能与演进 | 原支持场景、存量设置/插件/会话/Worker/Goal及公开入口继续可用；平台、owned/non-owned及失败恢复义务不削弱，退出支持须单独决定 |
| 架构 | 单一事实权威、窄接口、依赖方向和资源寿命明确；源码与组件/交互工作件一致，共享实现不堆Harness根目录 |
| 评审与收尾 | 先做职责/复用、运行/失败、数据/兼容三视角设计评审，再实施并做实际代码评审；关闭具体阻断，记录真实验证限制，达标后停止扩展本Goal |

用户已激活整个Goal及15K完成目标；可达性尚待P0实证，不能把目标接受写成所有具体组件/接口已经接受或实现完成，也不能把目标降成只做Worker或再减8K。系统去重的预期幅度应从实证重复池给出，不凭组大小编造。2026-11-09用户明确允许符合架构与复用准则的适度总量增加；因此不能只凭正增量拒绝职责归位，也不能只凭Coding下降采纳方案。必要增量须说明原组件为何不能直接覆盖、最小扩充及原厚体实际退出；泛化空接口、反向依赖、第二套机制和原样搬复杂度仍须修正。增量适度与否按完整业务簇的实际差异和收益评审，不自设用户未给出的数值额度或新增门禁。

保留A86已记录的Continuity可写祖先拒绝、既有广类型/技能检查及Windows candidate证据边界；不得用新目标冒称它们全绿，也不在无具体差异时把它们变成新平台/全仓门禁。重要架构工作件仍由用户评审，技术接受按原治理职责记录。本描述不授权新增CI gate、付费模型试验、平台开放、远程发布或直接批量迁移。

当前P0进展见[执行记录](coding-responsibility-convergence-progress.md)与[Worker专项设计](key-designs/worker-history-responsibility-convergence.md)。源/测试/架构起点已在产品树外保存可校验归档；后续按完整目标推进。
