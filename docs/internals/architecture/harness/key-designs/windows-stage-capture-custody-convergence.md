# Windows stage capture 职责收敛（A88–A91）

- Authority: COD-RESP-GOAL-002 有界职责交付；不替代完整P1–P4验收。
- Design status: accepted，Root按现有授权综合职责/复用、运行/失败、数据/兼容三独立视角接受实际A88/R5及A89/R2的原有界范围；A91/R4补充并纠正其关闭异常链缺口。
- Implementation status: complete within the capture operation；完整Goal仍partial。
- Owner: 原PackageProduct与Worker物理能力；Coding产品准入、公开Review/Error及领域政策。
- 方法：本地干净archmethod master `0f9bd3ff51afabeaaf76cc38dff1ceb279b7d37e`，没有声称与上游同步。
- 起点：`642a3529fade8ffa5d7b87d222c1d990c69b5b0c`；完整1967生产源与13包资源冻结于树外A88证据目录。

## 问题、复用和真实消费者

[A87](windows-worker-cleanup-current-path.md)已证明cleanup采集的物理操作本来就在
Core；本片不再迁移它。不同的Code `_capture_stage_bytes`原有完整约110行物理
程序，由complete及crash stage review真实调用。原Worker `WindowsStageInspection`
已提供成员/流/文件读取/marker验证，但没有承接实际Product root的完整capture。

扩充原PackageProduct `_worker_windows_attempt.py`，直接使用actual Product、原
StageInspection和原native API。ACL、root借用、stage及多级child FD、marker/
目录唯一成员、payload长度/SHA、末次identity及反序close整条操作一起接通。
Code删除旧操作体，只保初始精确intent类型准入与一次实际调用。没有新增模块、
manager、状态、索引、锁、Code IO callback或root-owner框架；Worker不依赖Product。

原较宽LaunchIntent协议不扩张。接收源局部 `_StageCaptureIntent`只声明这条操作
确需的stage_identity。原底层Worker源字节保持。三薄helper仍供retirement、partial
review及现有probe消费；`_identity`也有实际partial消费者，不能当无用兼容壳删除。

## 合同及有限内部差异

Code先执行原exact intent type guard，随后才构造inspection/读取Product配置。
外层GC/currentness、Product/os准入、公开Review/Error与wire不变。接收程序保持
ACL enter→root borrow→root ACL/stat→stage open/try；child取得后先登记再验证；
原bounded真实读取、marker语义、SHA和末次stage验证；child逆序close、stage finally、
root/ACL退出。构造captured值仍在stage try内，构造失败也走原清理路径。

私有临时captured dataclass归原PackageProduct，Code保私有import别名；6字段顺序、
值、frozen/slots保持，实现FQN/name/repr/私有pickle位置不承诺保持。没有公开/持久
消费者依赖它，不能为私有反射增加constructor callback。原公开Review/Error AST
保持。inspection不可变配置每次capture提前物化一次，非原每个薄helper重新构造；
不把私有配置重绑定时序冒称公开兼容合同。

没有趁机修复原close异常行为：child close异常可跳过剩余child close，随后stage/
root/ACL按原finally覆盖。三原故障场景在observer清理前仍显示真实dir0 FD债务。
这是保留旧合同的故障对照，非所有kernel close失败下资源安全证明。

## 完整成本

| 范围 | 原行 | 实际行 | 净变化 |
| --- | ---: | ---: | ---: |
| Code stage_review | 434 | 344 | −90 |
| 原PackageProduct接收源 | 478 | 609 | +131 |
| 全系统 | 647687 | 647728 | +41 |

类型、局部Protocol、真实兼容alias、import、注释及格式均计入。新框架/厚回调成本0，
新增文件0；其余1965生产源与13资源SHA保持。Coding430文件114020行，距15K尚差
99020行。这是完整IO职责归位，不能称系统净精简，也不把原共享primitive再次计收益。
允许这项有限增加是为了actual Product和Worker平台操作在正确的已有owner内闭合，
没有把Coding领域政策搬入Harness。全系统相对Goal634794基线仍增加12934行。

## 原始行为证据及实际结果

树外证据目录：`/home/dev/lsspace/.runtime/coding-convergence-continue/a88-stage-capture`。
baseline、R1–R5完整候选、原raw观察、源码/加载origin校验、失败日志和三评审均保留。
`before-frame.json`继承旧计量元数据，不能把其中旧head/candidate标签当本批起点；
实际父提交和逐源冻结以installation、源码SHA及最终frame为准。

原61场景observer执行完整旧capture及原Inspection，使用真实POSIX文件/FD/读取/
SHA与注入的Windows ACL/attribute/stream/root端口。覆盖平/多级成功、intent拒绝、
ACL/root失败、stage/marker/tree/leaf变化、大小/摘要/短读/1025字节真实overflow、
构造失败及body/child/stage/root close异常组合；保全异常type/message/cause/context、
完整有序trace和FD债务。同步注入CancelledError/KeyboardInterrupt验证BaseException
展开，不代表实际Task.cancel、原生Windows/LPAC、进程crash或全部并发交换。

原运行先冻结每case真实物理输入及raw观察，再重放原实现；候选不参与期望生成。
私有captured结果仅投影精确6字段，其他公开值/错误/trace不因此归一化。初次对照
使用完全相同的真实inode/dev/mtime输入，不抹掉身份字段。完整source/resource和
loaded-origin guard避免pytest路径配置导致误测旧源码。

| 验证 | 终态 |
| --- | --- |
| 原完整捕获与原固定重放 | 各61过（4.92s、9.07s） |
| 不可变R5固定61与原消费者96 | 61过6.13s；96过10.77s |
| 实际工作区固定61及原消费者96联合 | 157过10.02s |
| 仓库可移植完整61项探针，真实新临时输入 | 61过8.03s |
| 原导入边界测试 | 165过94.28s |
| 实际两源focused mypy（follow-imports=silent）、Ruff、format | 通过 |
| 固定实际src的普通mypy（不限导入范围） | 1322模块，0错误 |

实际测试完整输入/断言保持。R1身份局部名冲突、R2缺import/mypy失败、R3较宽协议
及R4漏真实_identity alias的两个收集回归均保留，R5只恢复实际alias。原freezer
误把mypy三个目标当三源变化的guard失败保留，纠正为实际两源，没有改旧观察。
第一次联合实际测试因重复注册tests.conftest未收集；去掉重复插件注册后同157范围
通过，不把搭建失败当生产失败或掩盖成绿色。

补充普通mypy第一次未设PYTHONPATH，报告未改Agent等5源231错；共享venv的Python
find_spec指向控制lane安装源，而非本任务源。原冻结树使用其src作PYTHONPATH的
同两目标普通检查通过，不能把它写成同样失败。实际树也固定PYTHONPATH为本任务
src后，verbose完整检查1322模块、0错误；实际Agent/proxy等加载路径均在任务树，
日志没有控制lane src路径。保留未固定来源的失败，不用修改无关Product代码掩盖。
普通与focused检查、原基线结果均分别归档；不把混合源码的失败当本片类型回归。

## 持续复跑及可移植性修正

显式本地探针`tests/coding/probe_windows_stage_capture_compatibility.py`保留全部61项，
不加入默认收集或新PR gate。冻结fixture仅由原raw生成，压缩SHA256为
`88ff663a6127268d6a9d063618c592cb32555bad8560db39d9bfa9cbd30d8263`。
每次新输入先取得真实stat/bytes；每一观察identity先精确验证等于该先验输入及
原故障offset，再转一一对应的物理role。每段读取先验证真实input bytes/offset/
EOF；marker独立输入公式不调用被测marker生成器。保留全部错误图、trace和FD债务。

首版在其外部临时输入61过，但接入仓库新/tmp输入25过/36失败：真实dev/inode
数字位数影响marker长度，第二次read.requested预算随之变化。完整失败、原fixture
和转换proof保留。修正版分离实际cursor与已返回字节数，逐次严格核验
`requested=min(chunk_size, maximum+1-consumed)`后才转换预算表达式，字段不删除；
short-read的seek-to-EOF不改变consumed。仅重新转换原raw，不使用候选输出更新期望。
错inode/dev/bytes、漏字段、错误预算、删stat/调close序及抹FD债务的变异对照均不能
通过，原源码与固定观察不改。新版外部同/tmp输入61过14.17s，最终仓库61过8.03s。

探针762行与6229字节gzip fixture单独记账，不属于上述生产源码口径。它们补本条
完整物理闭包的旧行为回归缺口，没有扩展CI路径、平台或merge阻断条件。运行入口
及同平台限制见[本地探针说明](../../../testing/coding-convergence-local-probes.md)。

## 接受边界和后续

三个独立评审均核实际R5源码、完整成本及相应证据，无本操作剩余技术阻断。Root
综合接受仅本capture闭包及注明的私有实现差异；测试平台限制不变。完整Worker、
Windows恢复/cleanup、P1–P4和15K均未完成。KD011/A33仍待用户工作件且未采用，
KD003仍未实施。下一步复核相邻offline snapshot、attempt-reference及retirement的
完整寿命和可复用机制，避免只减目录行数或继续叠加薄层。

## A89完整Reserved捕获复用与共同寿命

A89实施起点为`88bde6cd571dd41f17de73b4df4b62b83134884e`。
A88后仍有一条真正重复的完整程序：Reserved review的`_capture_reserved_stage`。
Reserved、settled-unlaunched review及unlaunched retirement重捕获实际共用此入口。
它与原capture的目录/marker/payload/SHA/末次验证/关闭程序一致，区别是公开
Reserved DTO必须在原stage try内构造，且原语与操作诊断分属两类错误。

R1曾构造完整generator context候选；运行评审指出yield前StopIteration会被PEP479
转成RuntimeError。三个原反例实际2失败/1通过（10.41s）：marker read和root fstat
均改变异常，叠stage-close的一项保持原异常链；原失败保留，R1未采用。R2保持原同步函数，
借用标准ExitStack：Code薄入口在原准入之后进入栈，Core按原顺序enter ACL、root，
stage取得后登记原close；children仍原局部finally。Code在同栈体内返回captured或
构造真实Reserved DTO，随后按stage→root→ACL关闭。没有新manager、generator、
构造factory callback、Code IO回借或另一份物理操作。

原native_revision `not in (1, 2)`保持：bool/float可过初guard，但在完整IO之后的
公开DTO严格校验才拒；不提前强化。Complete的exact Intent guard也保持在scope前。
Inspection仍原StageReview错误域，Reserved自身root/stage/tree/payload检查另绑
Reserved错误class/prefix两个纯值；各原Code payload读取上限独立传入。Code全部
真实公开类/字段/metadata/wire及其它函数AST保持。实际Intent冻结字段和私有配置
在调用入口取值，不承诺任意duck getter或私有alias中途替换的时点。标准stack
在取得stage时绑定实际close；真实root/ACL端口均不抑制异常，不额外模拟任意
suppression替身或增加适配框架。

| A89实际范围 | 原行 | 当前行 | 净变化 |
| --- | ---: | ---: | ---: |
| Code Reserved review | 447 | 376 | −71 |
| Code complete capture薄入口 | 344 | 350 | +6 |
| 原PackageProduct接收源 | 609 | 602 | −7 |
| 系统生产源码 | 647728 | 647656 | −72 |

所有scope/import/三个纯诊断与预算叶/格式计入，Code合计−65。A88+A89原三源
434+447+478=1359→350+376+602=1328，两片Code−155/接收+124/系统−31；完整重复
真正退出，非目录搬迁。Coding430源113955行、系统1967源647656行，其余1964源
及13资源SHA同。系统相对Goal基线仍+12862，距Code≤15K还差98955行。

格式贡献单列：按完整变换重建的接收源在正常格式前618行（结构+9），Ruff扁平化
后602行（格式−16）；Code两源未再格式改动。因此本片结构净−56、格式净−16，
合计实际物理−72。两片合计−31也是物理口径，不把全部行差说成逻辑程序消除。

树外`a89-reserved-stage-reuse`保存原1967源/13资源、完整R1/R2、75原观察及冻结证明。
75项复用A88相同物理fault程序中Reserved适用的60项（独立expected-stage输入仅属
complete，原A88完整61仍保），另补native revision、lease边界、public构造错误/
StopIteration与stage/root/ACL关闭覆盖，以及IO叶StopIteration。成功返回保公开
FQN、完整10字段、逐字wire与fingerprint，失败保完整错误图/trace/FD债务；期望
仅来自原实现。真实文件/FD和原Inspection运行在受控Windows端口的POSIX模型上，
不是原生Win32/Task.cancel/进程crash或任意kernel close失败的全面证明。

原完整75捕获通过9.94s；R2原消费者及A88完整capture回归204过6.66s。实际R2同
75固定观察与204消费者联合279过17.82s，全部原值/输入/断言保持，逐源及加载
origin guard通过。实际普通mypy三源、Ruff/format、生成package依赖图通过。
三独立视角已核完整三源及全部成本，Root按授权接受本完整重复退出；完整Goal
仍active/partial。KD011/A33与KD003原边界保持，不将此片当整个Windows收敛。

持续回归新增显式`probe_windows_reserved_capture_compatibility.py`，404行；直接复用
A88原Observer/OsPort/seeded与严格身份/读取预算校验，不再复制完整观察器。75项
fixture只由原raw转换，gzip9102字节，SHA256
`899068b773f04b12526c7533a1e9208365965ee73a8f7ff6f20d75208040b531`。
四成功形状先用独立先验input和原LaunchIntent schema/domain生成意图指纹，再
逐十字段、公开FQN、原Reserved schema的canonical bytes/domain指纹严格校验，
之后才转物理role/派生表达式。没有忽略公共类型或只比较六个私有字段。首次独立
输入公式漏Intent domain即被原native-revision-two拒绝，原稿/失败保留，按原源码
补domain后仅重转原raw，没有改原值或从候选输出生成期望。

外部新/tmp75过（XML 3.730s），仓库新75与共享原61联合136过2.08s；字段/FQN/bytes/
domain hash/身份/预算的错误变异均被拒，抹FD债务仍完整比较不同。两条原架构
边界断言2过19.70s，文档9项静态规则与改变文件链接通过。测试和fixture另列成本，
不计生产净减；probe命名保持显式本地执行，不增加CI route/gate/platform。

## A91完整partial capture与原生关闭区域

### 当前职责和选择

起点为A90 `2516c77cd2416ad36a14ce48d191da18d652de92`，冻结1967生产源与13资源。
原partial `_review_partial_tree`完整物理操作由现有PackageProduct接管，实际消费者
仍为公开partial review及partial retirement的fresh review；Code保原7字段公开DTO、
FQN、wire、产品准入/lease/GC政策。Worker原StageInspection及既有`close_opened`
直接复用，后者反序关闭且首错停止；没有新增模块、manager、存储、状态或IO回调。
原StageReview `_identity`唯一真实partial消费者退出后删其3行别名；其余真实helper保留。

先比较两个完整替代形状：R3A四个标准lexical ExitStack，Code−93/Core+122/系统+29；
R3B普通同步with/try/finally加纯值factory，Code−104/Core+134/系统+30。采用后者的
资源区域内聚方式，再在R4修复邻接full/reserved；没有为少1行向Code暴露四scope。
同一个泛型返回类型/Callable只承接实际公开结果构造，不接IO、目录遍历或寿命控制。
这与A88不必要保留未消费私有临时类型FQN的factory不同：公开DTO构造时点是真实合同。

full/reserved先执行原whole-child close，再做stage末次校验并构造结果；partial则在
child try内构造公开DTO后才close。complete factory仅返回原私有捕获值，外层公开
complete/crash DTO时点保持。Core的ACL/root with及stage/child finally恢复原生嵌套，
同步StopIteration不经过generator/PEP479。expected_stage=None仍在打开和验证stage
之后拒绝；空文件、16层边界、短路顺序、marker形状、primitive/operation两错误域及
独立读取预算保持。这里只是读取证明，不授予退休、删除或发布权威。

### 真实失败、修正和旧行为来源

R1单ExitStack原有限消费者271过仍不足：原73+guard实际72过/2失败，child+stage及
all-close异常context丢失。R2双栈通过原74节点后，新增原stage+ACL/root+ACL组合
仍有2真实失败。两候选均不接受，不能抹去context或用最后错误类型/文本相同解释。
扩展partial到原118观察：原73原值不改，补45项normal/ValueError/StopIteration与
15种非空child/stage/root/ACL错误mask。原数据先于R4冻结，绝不从候选生成期望。

进一步用正确pre-A89普通lexical原源验证full/reserved，R2邻接smoke 1guard过/4失败，
证明A89已有同类真实回归。本批必须一并修复；完整邻接90项来自pre-A89原full程序，
不是已回归的A89扁平栈。full/reserved构造在child关闭之后，child失败mask下不会
执行构造，90项保持原真实fired顺序和异常图。旧失败、原输入及各候选均保存在树外。
首次R1观察器错误地强制patch已退出Code alias，1guard过/73 setup失败；仅重定向
实际操作owner的hook后暴露上述2个真实错误。一次R2消费者PYTHONPATH配置失败也
保留，修正为task src和root后通过，未改Product或原fixture。

### 最终成本和验证

| 生产源 | 原行 | R4行 | 净变化 |
| --- | ---: | ---: | ---: |
| Code partial review | 357 | 256 | −101 |
| Code reserved review | 376 | 373 | −3 |
| Code complete stage review | 350 | 345 | −5 |
| 原PackageProduct attempts | 602 | 739 | +137 |

Code−109/Core+137/系统+28，所有factory、类型、临时5字段值、错误/budget绑定、import
及格式均计入。接收正常格式前758→739，故结构+47/格式−19；不是系统净减或第二次
重复退出收益。当前Code113755/系统647664，相对Goal起点Code−24000/系统+12870。
其余1963源和13资源字节不变。完整Goal距15K尚98755行，P1–P4保持partial。

R4候选partial118+guard119过12.83s，实际fresh partial119过8.96s；正确pre-A89
邻接90+guard实际91过6.22s，fresh carrier91过6.88s；原消费者候选271过11.80s、
实际271过5.71s。持久化到仓库的两个显式probe联合208过10.82s。四实际源SHA匹配
接受R4，原公开类型/字段/codec及非目标操作AST保持；mypy四源、Ruff/format通过。
三个独立视角对完整R4形状无剩余已识别阻断，Root按授权接受本片，不接受R1/R2。
原两条架构边界2过43.97s、生成package图fresh、9项文档规则与改变文档链接通过。
同时修正8个早期test→probe重命名后遗留的文档链接；没有改变测试发现或PR条件。

持续载体为两个显式probe：partial 777行、邻接294行；复用既有A88/A89观察器，
不是再复制整套driver。partial gzip21728字节、邻接gzip12491字节；原raw先严格
核全部公开字段/FQN/canonical wire/domain hash、先验物理身份与原读取预算，再做
可移植角色投影；完整错误cause/context、顺序与未关闭FD债务保留。strict JSON数值
类型避免bool/float蒙混。测试/fixture/文档成本另列，不计生产行或增加默认CI发现、
route、gate、平台。参见[显式执行](../../../testing/coding-convergence-local-probes.md)。

验证使用真实POSIX文件/FD和受控Windows ACL/attributes/root/stream端口；覆盖同步
CancelledError、KeyboardInterrupt、StopIteration及多关闭故障，不外推native Windows/
LPAC、真实Task.cancel或所有OS crash。LSP另经原owner审计：现有Worker/Host framing
与LSP Content-Length及correlation寿命不等价，本批未另建通用RPC或挪走LSP领域政策。
