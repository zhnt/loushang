# A82：系统源码增长与接收层复杂度复核

- Authority: COD-RESP-GOAL-002 的计量与当前差距记录，不是整套架构的质量验收。
- Design status: 三独立视角只读复核；本次不选择新的大规模迁移接口。
- Implementation status: A81增长账已逐文件核实；仅退出一处无消费者的私有兼容壳。
- Owner: Coding及共享层；Root综合职责、运行、数据三个独立视角。
- 切点：A81 `5b6e702d5b514b0ad90e6e929ea2ea1ac16ba220`。

## 12,986是系统净增长，不是Harness单独增长

采用原Goal冻结的1,845份生产源码清单，而非当时Git HEAD：该起点包含原未提交
实物。清单SHA为 `61d7c2a6f5ffb077bab403788ce7683ce0771f481641ff975ab505defe13ad77`。
对照A81全部1,967份当前生产源码逐路径/字节/物理行重算，结果如下。

| 生产区域 | 原Goal起点 | A81切点 | 净变化 |
| --- | ---: | ---: | ---: |
| Coding | 137,755 | 114,179 | −23,576 |
| Harness | 328,319 | 359,514 | +31,195 |
| AppHost | 16,654 | 18,424 | +1,770 |
| HarnessWork | 7,336 | 7,862 | +526 |
| GUI三生产根 | 8,008 | 10,974 | +2,966 |
| AppServer | 7,177 | 7,269 | +92 |
| AppService | 6,521 | 6,534 | +13 |
| 其他生产区域 | 123,024 | 123,024 | 0 |
| **系统合计** | **634,794** | **647,780** | **+12,986** |

Coding以外合计+36,562，抵消Coding的−23,576后才是+12,986。
口径为原四生产根及其已约定语言扩展；测试、文档、示例和声明资产另列。
这不是整个仓库所有文本文件的行数。

## 同期主线增长与重构成本分开

原主线 `8ad6b6098f1c24c8cfb6f4d9d290e99bc74d618d` 到当前主线
`2aa2f7deb8de9de5e79603f03627b3df115d0cf4` 的两个提交树，在同一生产口径下
净增3,583行：Code+512、GUI+2,966、AppServer+92、AppService+13，其余净零。

12,986−3,583=9,403，是扣除原上游提交树增量后的记账残差，包含本轮重构和
合并适配/交互。重叠的上游Code方法曾接入共享owner，不能把此残差再宣称为精确
独占归因，更不能用上游HEAD替代原未提交Goal基线。此前各同步阶段的实物增量
包含当时归并变化，与两个原提交树的纯差额也不应混用。

因此，主线同步只解释部分增长。扣除后仍有明显净增，不能用同步解释全部成本，
也不能把Coding目录减行等同于系统复杂度下降。

## Harness增长集中在哪里

| Harness区域 | 相对原Goal净变化 |
| --- | ---: |
| Worker | +17,502 |
| Package Product | +5,832 |
| Session | +3,760 |
| Transcript | +1,300 |
| 其他 | +2,801 |
| 合计 | +31,195 |

84个新增Harness模块共有28,725行，既有模块净增2,470行。新增模块中117个
Protocol声明占1,083物理行；它们不是全部可删成本，也不足以解释所有增长。
静态直接导入复核中，26个新增模块仅有Coding直接导入者，18个仅一个直接导入者。
该证据不包含所有动态导入、reexport和间接消费，不能直接推断owner错误；但也不能
据“移到Harness”就宣称跨产品复用或重复算法已消除。

对非小型完整函数体的精确AST筛查未发现这些新增模块之间的直接同体组。它只能
排除明显原样复制，不能证明语义去重、高内聚或接口成本合理。

## 已定位的复杂度欠账与必要合同

| 实物 | 已核实的问题或必要边界 | 后续处置 |
| --- | --- | --- |
| A56普通Worker/Windows准备 | 没有第二份生命周期权威；Graph失败释放的一次性guard有实际竞争场景。仍有effectful Product端口；Windows cleanup当前是Core→Code薄绑定→Core往返，物理IO已归Core（A87纠正） | 闭合真实操作程序，不能把所有callback标成纯值或再次加wrapper |
| A65 builtin bootstrap | 240行程序无新增Task/锁/缓存，真实install与enable共用历史证明；本片+64 | 认可职责归位，保留完整成本，不当系统净去重 |
| A78 Linux恢复 | Registry/RepairJournal/C5仍各自单一；1402行接收体和bindings/Code实际类构造增加阅读路径 | 核重复receipt精确查找、bindings反复装配和Core→Code薄构造→Core的必要性 |
| A80 canonical Catalog | Factory交付前pending与Catalog交付后custody保护不同资源阶段，不能简单合并。23个抽象政策方法、额外mixin、Code薄转发确有接口成本 | 先合并只有一个消费者的legacy-open转发，再核常量getter及构造绑定；不删失败资源保留 |
| A81 Goal history | 实际builder已经直接使用Core source；Code还留下没有消费者的私有 `_HistorySource` | 本片删除此壳及unused import，不改实际builder/DTO/codec |

A56/A65/A78/A80/A81五片自身系统净增合计2,558行，只是全量增长的一部分。
既有评审和测试证明了指定职责/行为合同，不自动证明系统整体更简单。

兼容视角还确认，新增A78反射probe把方法实现的module/qualname及是否存在于类
自身`__dict__`一起冻结，超过了已证明的公开合同。它不能反过来成为永久保留薄
覆盖层的理由：两处仅super转发的私有覆盖共38行定义没有外部消费者，原C5静态
属性检查也支持继承。后续应保留原raw和完整wire/failure/authority观察，明确区分
有效公开API/签名与偶然实现位置，再退出多余覆盖；不能顺势放宽真实公开DTO字段、
FQN、own annotations或持久合同。A80晚取私有类alias也不能直接等同于必要的
构造失败窗口；保持raw custody与实际constructor故障时点后，应减少这类接缝。

## 本片实物改动与验证

Code `_goal_execution_context.py` 从147降为137行：仅删除无生产或测试消费者的
私有 `_HistorySource` 及未用import。它不在公开导出/持久schema，原API fixture
和DTO pickle观察也不包含它；模块没有依赖它的动态分派或注册。
原七个其余顶层定义（两个DTO、五个函数）AST完全相同。
Code及Core两个真实context入口仍调用原共享builder，由其直接构造原Core source。

此前把“旧私有FQN曾存在”当成保留理由，缺少真实合同依据；本片纠正这一过度
兼容。公开API、三个公开DTO、实际读图/图片处理与Task/清理程序保持。
不把移除10行包装称为已经解决系统增长，更不通过紧凑格式或删必要cleanup换行数。

原67固定探针加原公开兼容模块共77项通过（5.76s），期望/断言/输入未改。
单源mypy、Ruff/format和其余定义AST核对通过；三独立视角无本次窄删除阻断。
完整四产品路线、平台与原AI覆盖率基线问题仍按各既有记录，不扩称全套检查通过。

本片Code−10、系统−10、接收侧0。当前Coding430文件114169行，系统1967源647770行；
其余1966原source SHA及13原包资源保持。相对原Goal累计Code−23586、系统+12976；
剔除同上游树增量后残差9393。原完整P1–P4/领域化/≤15K目标仍未完成。

原基线、逐路径/组件账、上游提交树账、结构分析、三独立审查、删除前源/AST证明
及实际终态在产品树外 `a82-system-cost-audit` 保存。

## 接下来的实施选择

优先削减当前共享层已定位的间接层、重复装配和效果回借，再选择新的职责迁移。
每批分别证明旧操作体退出、实际复用、接口/兼容全成本及状态/资源权威没有复制。
新增共享模块须有具体职责和成本依据；不以“Coding减少”单项接受架构收益。
必要、适度系统增长的原准则保持，不能把本审计擅自改成新PR门禁或无条件净减指标。


## A83后续：退出cleanup authority两私有转发

实际移除 `_complete_repair_verified` 与 `_verify_tree_review` 两原样super覆盖，
Code源153→113，接收侧无新增，整模块在仅移除两定义后的AST与原源完全一致。
公开入口/签名/DTO/authority身份不变，私有实现metadata随继承改变；Core正常、
UnderGuard/Registered分派及C5静态绑定均核实保持。原143固定观察通过（23.09s），
未改反射probe或任何期望。三个独立视角窄接受；不把40行解释为9k成本债已解决。
当前Coding114129/系统647730，完整Goal保持partial。


## A84后续：legacy-open转交层退出

原AppHost Catalog唯一调用的私有global helper并回原方法，739→721。保五个
boundcallable入口捕获顺序，随后操作体AST原样；整模块在逆变换后与旧源AST相同。
原构造在try外、restore/readback/候选失败和dispose覆盖合同不改。原66固定观察
通过（27.36s），测试/期望不改，单源静态检查及三实际视角窄接受。系统/接收侧
各−18、Code0，没有新增组件/接口；当前系统647712、Code114129，完整Goal继续。


## A85后续：实际factory/type绑定代三虚拟getter

原factory对象及两实际类在Code构造时绑定，Core直接引用，退出三getter及三
抽象hook，无新owner/profile。资源取得/异常catch/legacy借用关闭责任均不改；
不再支持构造后晚替私alias，并非削弱公开合同。两个完整故障场景改对实际类
__init__注入，原36个assert/raises及所有输入/期望保持；候选故障分支不动。
首64过/2挂点失效失败与一次错误测试路径的collection失败保留；最终66固定加
三个原消费者模块共111过（42.36s）。三独立实际视角接受，Code−12/Core−8/系统
−20；其他1965源与13资源同。当前Code114117/系统647692，完整Goal继续。


## A86后续：同一retained receipt读取程序复用

两个实际入口调用原ReceiptHistory新增精确查找，校验仍在各自构造history前，
完整读取/退出guard后首匹配的原顺序不变。原155回归通过（19.82s），测试/期望
不改；三源mypy/Ruff/format及三实际视角窄接受。正常格式全部计账后Code−7、
接收侧+2、系统−5；无新module/manager/state，当前Code114110/系统647687。
新共享能力由两个真实消费者使用，但不因此宣称整体复杂度或完整Goal已经完成。


## A87纠正：effectful薄绑定不等于Code厚IO程序

三独立视角重新沿当前cleanup调用到物理叶子，确认A82概括‘仍留Code厚IO’过宽，
属于审计判断纠正，不是新迁移成果。orphan/inventory/native/receipt/activation及
原生Job观察的实际程序均已归原Core/Hosting；保留的Code准入/绑定/证明政策有
多层接线成本，但不能据此重复实现采集器。两次独立native重读不能合并。真实
未共享stage capture是另一个完整场景；尚无采用或减量证明。详见
[当前路径](key-designs/windows-worker-cleanup-current-path.md)。本片生产源码零变化。

## A88后续：完整stage capture职责归位及接收成本

Code原完整capture物理操作退出，现有PackageProduct直接使用已有StageInspection、
actual Product与原native API；底层Worker源码不改。没有回借Code IO、constructor
factory callback、root-owner框架或新的模块/manager。保留真实partial/retirement
消费者需要的薄helper和_identity import，不能为减行数删掉真实合同。
最终Code−90/接收+131/系统+41，已计临时值类型、窄intent Protocol、所有import/
注释/格式。属于完整职责迁移及类型边界成本，不计去重或系统精简；全系统647728
相对Goal634794基线仍净增12934。三视角有界接受及实际157项通过见
[A88](key-designs/windows-stage-capture-custody-convergence.md)。整体15K与P1–P4未完成。

## A89后续：两条完整capture真正合一

Reserved旧完整操作直接复用A88原capture，Code447→376（−71），原complete薄适配
344→350（+6），接收609→602（−7），系统净−72，含全部ExitStack/import/error与
budget叶/格式。A88+A89从原complete434+reserved447+Core478=1359到350+376+602=
1328，两片合计Code−155/接收+124/系统−31；原生产重复退出，不是又加一份共享层。
Code113955/系统647656，相对Goal基线系统仍+12862；不能把这31行说成累计增长
已解决。R1 generator因实际StopIteration合同风险不采用，R2复用标准ExitStack
保持同步、真实DTO寿命及原错误域。完整成本/故障来源见
[A89](key-designs/windows-stage-capture-custody-convergence.md#a89完整reserved捕获复用与共同寿命)。

本片接收体重建为正常格式前618行（结构+9）→正常格式602（格式−16）；Code两源
−65没有本轮格式变化。故系统物理−72分为结构−56/格式−16，不把全部物理行差
冒称逻辑去重。另加404行显式测试及9102字节原观察fixture，测试/文档成本另列。

## A90后续：原publication直接完整捕获receipt

Code AgentSession2101→2010（−91），原publication168→239（+71），系统−20。
两个完整Code捕获程序退出，原state/fanout仍唯一；四Code getter仅纯数据投影。
R2直接复用已有三键identity，删除R1新增canonical wrapper；原四键Ledger不改。
接收体格式前241→239，故结构净−18/格式−2。当前Code113864/系统647636，仍较
Goal系统基线+12842；不把本片当整个系统简化完成。显式测试705行与14781字节
lossless原fixture另列，不扩PR gate。全合同/失败与输入修正见
[KD009 §21](key-designs/startup-session-assembly-convergence.md#21-a90原publication直接捕获完整receipt)。

## A91后续：partial物理职责归位及A89异常链纠正

Code三源合计−109，现有PackageProduct接收+137，全系统净+28；结构+47、格式−19。
这批完成partial捕获程序退出并恢复full/reserved原生关闭异常链，没有消除另一份
partial重复算法，不计系统精简。当前Code113755、系统647664，较Goal基线分别
−24000/+12870；整体增长问题仍在。复用既有StageInspection、Product root与whole-child
close，无新manager/模块；纯公开DTO构造保留原资源时点，scope不泄漏到Code。
四源、原R1/R2失败、pre-A89正确旧行为及完整有限验证见
[A91](key-designs/windows-stage-capture-custody-convergence.md#a91完整partial-capture与原生关闭区域)。
新增显式测试1071行、两压缩fixture34219字节与文档另列，不包含在生产源码增减。

## A92后续：原激活lease机制合一

这批没有Coding源码增删。Continuity原Callback机制149→168（+19），Generation所在
模块883→836（−47），系统净−28且没有格式减量；不是另迁一份Code领域算法。
两阶段必要lease实例保持，consume/abort/Event/共享Task算法只留一份。R1 Event
失败范围变化及R2新selfcycle均未交付，实际反例分别4失败/1失败保留，R3旧41项
全部通过。当前Code113755/系统647636，较Goal基线−24000/+12842，累计系统增长
仍未解决。新增482行显式probe、4627字节原41观察gzip及文档另列，不扩默认发现
或PR gate。完整源码、旧期望来源和验证限制见[A92](key-designs/activation-lease-lifecycle-convergence.md)。

## A93后续：完整Windows backend custody归位

Code release205→129（−76）、installed234→148（−86）、approval owner108→94（−14），
合计−176；现有PackageProduct组件增加312行私有完整程序，系统净+136。14个纯绑定、
3空slots方法提供者、窄类型端口、兼容转发/实际公开值、import及排版全部计入。
不是去重收益或又建一套Wheel/native/receipt引擎。原完整草拟源与常规Ruff逐阶段重建，
最终四源逐字同接受R2：结构+66/排版+70=物理+136；这是该构建过程的计量，不是
逻辑最小行数证明。Code三处产品准入谓词归一个Code helper，领域政策没有换目录。
当前Code113579/系统647772，相对Goal起点−24176/+12978，整体增长仍未解决。
新增932行显式探针、40390字节lossless原fixture、1处原native测试hook转接及文档
另列；原assert AST同，不扩gate。完整旧值/失败来源及H5旧失败见
[A93](key-designs/windows-backend-release-custody-convergence.md)。

## A94后续：H5既有显式operator边界协调

生产源码/资源零变化；1968源及13资源SHA与A93同。Coding113579/系统647772，
累计−24176/+12978；本批不计精简收益。成本仅为现有H5测试的精确一文件/一符号
减域及Current/History/交付文档协调，不增加gate或运行机制。三视角有界接受、
最终受影响25过、文档9过；扩大Hosting结果及仍开放5项基线问题见
[H5 A94证据](../hosting/harness-worker-adapter-h5.md#a94-reconciliation-evidence)。
原A93失败记录保历史，不回写旧结果；完整Goal仍未达标。

## A97后续：退出配置Continuity的重复迁移支路

Code/系统均−12：删除重复body/header15行，合并短路条件排版增加3行；接收组件与
兼容适配均0，不新增API/manager/gate。1609→1597的原文件逆变换后整AST同，
原30项配置bootstrap回归通过。当前Coding113567/系统647760，较Goal起点−24188/
+12966；仍有系统累计增长及完整15K差距，详见[当前执行记录](coding-responsibility-convergence-progress.md)。
A95缓存和A96普通Session候选不采用，生产收益0，避免重复此前不经济的适配方案。

## A98后续：未交付Session的原owner清理责任

已复现交付前注册失败持有实际Product租约且无可达完整清理owner；本片修复恢复
缺口，不计精简收益。Coding bootstrap+20（含薄getter/失败绑定）、原Session cleanup
+121、原TranscriptStore+29，兼容绑定已含Code不得重计，系统+170。测试两显式probe
527行另计、不进默认PR route；54原/18新本地检查合计72过，另原SDK14过。当前Coding113587/
系统647930，较Goal起点−24168/+13136；15K尚98587。完整边界、失败和证据限制见
[KD009 §22](key-designs/startup-session-assembly-convergence.md#22-a98完成构造后的session交付失败责任)。
