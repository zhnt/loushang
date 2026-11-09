# COD-RESP-GOAL-002：Coding 领域化与公共机制职责归一

## 状态与依据

- **现行成本准则（2026-11-09用户修订）：** 以职责分明、高内聚低耦合、优先复用已有组件为先。已有能力无法满足真实合同、最小扩充或必要薄适配确有必要时，允许系统总行数适度增加；不再把系统低于634,794行作为硬性完成条件。Coding归属≤15,000行、完整P1–P4、兼容与恢复义务保持。所有接收与适配成本仍全计账，迁移不冒称去重。下文A1–A54时点记录中的“系统严格净减”是当时要求，不覆盖本条新准则，也不追认历史被拒候选。

- Authority: accepted execution goal；用户2026-11-07将本描述设为active Goal。本文件不替代各组件的已接受架构合同。
- Design status: accepted goal scope；各波次专项架构仍须设计、评审及按原约定由用户审阅重要工作件。
- 当前实施摘要：A56装配、A57查询取得、A58/A59恢复协调及A61完整Canary生命周期及A63完整operator query已接通并有界接受；A60/KD011 R6仍待用户图审。当前计量及欠账见下文“A63当前计量”。以下逐项保留各历史接受范围。
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

## 当前续接与交付状态（2026-11-09，A64–A65）

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
