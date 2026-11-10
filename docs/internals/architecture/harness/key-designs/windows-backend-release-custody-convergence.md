# Windows backend release custody（A93）

- Authority: COD-RESP-GOAL-002 有界职责交付，不替代完整P1–P4验收。
- Design status: accepted R2；Root综合职责/复用、运行/失败、数据/兼容三个独立实物视角接受。
- Implementation status: complete within the selected custody program；原生平台与完整Goal不因此完成。
- Owner: 原Harness.PackageProduct完整程序；Resources/Worker/Hosting保实际机制，Coding保产品政策与公开值。
- 起点：`a3f5e1f842c5f7c5423803030adcff6c5f2935a2`，1967生产源与13资源树外冻结。
- 方法：本地干净archmethod master `0f9bd3ff51afabeaaf76cc38dff1ceb279b7d37e`，未声称上游同步。

## 原问题、接收者和退出

原两个Code backend模块205+234行，另approval owner108行。底层Wheel RECORD验证、
Windows ReceiptIO的ACL/ADS/stage/noreplace/flush/readback、Hosting材料/运行映像及
ApprovalRecords重放/CAS早已共享；本片不重记这些引擎的收益。剩余candidate全Wheel
成员/hash、material review、install/read协调和approval current整段资源程序现归
[原PackageProduct](../../../../../src/loushang/harness/package_product/_windows_worker_backend_release.py)。

Code真实3DTO保4/2/3自有字段、FQN、构造、frozen/slots/eq/hash/repr/pickle及原
Reader/closure接口。它们继承非dataclass、slots=()的私有方法提供者；没有init、
postinit、实例dict/状态/缓存/资源权威。私有classmethod只实现相关值的完整取得程序，
用Self/cls在原点构造真实Code类，不在多个DTO之间增加阶段状态机。新增私有MRO/
方法/merged私hint是明确实现差异，公共resolved field hints及实际值接口保持。

14个绑定保Code实际类型、3预算、receipt实例、错误/文件名和纯产品准入；三处原同
判据复用一个Code helper，没有Code扫描/材料/读写IO回借。5项框架固定技术事实
不再可变绑定：原Worker SHA256语法、Hosting原required名单、Loushang distribution/
prefix及Hosting profile成员路径，由原组件直接用。没有复制required名单或把Code
独有产品策略移入其它包。approve/revoke业务协调及其公开方法体保持。

Core approval-current完整持GC/epoch/前后currentness，调用实际journal.current窄
端口，复用原投影/codec，不重写末记录选择。R1曾内联这份投影、19绑定且Review
消费带Any；R2恢复原port、14绑定与只读Review字段。唯一Any限私review class未知
具体Approval子型的构造元数据，不贯穿消费数据；实际Code类绑定和运行类型另有证明。
这是原PackageProduct内部私文件，不新增运行组件、manager、Host反向依赖或环境actor。

## 原顺序与失败恢复合同

inert inspect接受原bytes isinstance，install仍要求exact非空bytes≤64MiB与exact str。
3预算及完整hash公式不改：全Wheel SHA、全package成员+映像+Wheel catalog、双映像
launcher与Hosting profile成员digest，再用原Review canonical JSON的SHA256生成review_id（无额外prefix）。
这是Windows完整Loushang Wheel及host Python合同，不能强套Linux4MiB native H6模式。

material可在没有审批/retained Wheel时成功；先capture映像，再调用原Hosting verifier
（其内前后还capture），共3次，不能缓存或合并；构造Review/Material时GC仍存活。
安装先核review_id，再独立读approval，首receipt read才允许unpublished stage；相同
bytes不写、不同bytes拒替换，随后必须普通readback。epoch退出后currentness重验，
再读approval generation相同才返回实际InstalledDTO，仍在原GC内。read拒stage、只读
一次approval，并每次重验material；Reader closure仍为Code原投影，不授予launch权。

read的_require_product及首次currentness在try外；try内只包原有序7类错误并from cause，
InstalledBackendError本身不包。install原异常直出。全部嵌套GC/epoch、构造时点与退出
优先级保持。write/fsync/rename后出错仍保stage或published事实，不自动rollback，
后续显式相同bytes可重试；原case固定的5类发布后失败与重试均保持。

## 原证据、候选与实际验证

Runtime old80场景只由冻结源码生成；真实Wheel inspector、Hosting verifier外层、
真实Code类型/approval current协调，Product/GC/epoch/native材料叶、journal read及
receipt端口受控。完整trace/错误cause/context、3次image、审批双读/单读、constructor
scope和发布后retry保存。原JSON873013B，SHA256
`fc6dd271d3748590b80ffc4f5b130756688514ea8096e60f703daebf03450d6f`；lossless gzip20360B，
SHA `293b0b3bbc26e24d107a67b11bc3ce543fca117392b6ffe2304a9f19ecc6be1d`。
首setup5节点表面通过，但driver对未初始化Product递归repr使4条成功路径变AttributeError；
raw/错误保留，修trace显式controlled token并加成功/拒绝/触发点前置assert后，才冻结
实际old80。hook仅按存在的旧/新实际owner定位，不留退出Code alias假验证；ctor始终
patch实际class.__init__，不以function proxy换公开type。兼容hook旧80重放仍通过。

独立值/API old16场景另存14个值×protocol0–5共84份pickle，含旧允许的bool/float/
None/list malformed值、真实Reader受控返回、public字段hint/签名/slots/matchargs/
repr/eq/hash/frozen/noDict；hash先校原input tuple公式，不锁随机hash整数。原JSON
559784B SHA `5dbe17cb1aef625f1352d0c9ef7b34fc07d570ce86507920d72a9bcd03f57751`；gzip20030B，
SHA `2ea8d0a77803014b43021824c3e6ac64e6e4ad51d3ba0857c09393f8e3451969`。原30节点fixed/
crossload通过；候选30与80分别过，纯cold import及全源/loaded-origin guard通过。

实际四源逐字同R2；old80+DTO30+原inert2+下游crash1联合113过11.55s（pytest summary），
XML suite另记。仓库同110显式探针过4.20s；不是又110个独立新场景。80载体入库仅
Ruff import空行+1，全AST同外稿；DTO376行/84pickle不改，两个fixture解压逐字同old。
932测试行和40390B binary与生产分列，无capture入口/未来生产SHA锁/默认CI发现扩张。
原Windows preB测试只将verify hook指向实际Core，全部assert AST同。完整原生preB
须Windows/envflag/实际Wheel，此机未执行；受控证据不冒充ACL/Job/native handles或
Task.cancel集成。旧观察/原失败/后续修正/4源AST映射与三视角审查树外保留。

## 成本及未关闭项

| 生产源 | 起点 | R2 | 净变化 |
| --- | ---: | ---: | ---: |
| Code backend release | 205 | 129 | −76 |
| Code installed backend | 234 | 148 | −86 |
| Code approval owner | 108 | 94 | −14 |
| 原PackageProduct新增私文件 | 0 | 312 | +312 |

Code−176/接收+312/系统+136，兼容绑定、类型、imports及格式均计。完整草拟源→Ruff
逐阶段重建得到结构+66/排版+70，四最终字节与接受R2全同；这是明确构建账，不是
唯一逻辑行最小值。除三处Code准入谓词归一外，本片主要为完整职责归位，不声称
算法去重或整体系统精简。当前430 Code源113579行、1968系统源647772行，其余
1964原源/13资源SHA同；相对Goal起点Code−24176/系统+12978，15K差距98579行。

Core不反向导入Coding、Harness无环两断言通过。额外H5断言失败来自原
Session/_worker_operator_query.py直接构造HostingManagedWorkerSessionAdapter；冻结
baseline同一断言亦失败，相同文件SHA/命中，A93新增Core无禁用3符号。
[A63已接受当前程序](worker-product-runtime-convergence.md#26-a63完整单次查询接通原session)
与[H5旧规范](../../hosting/harness-worker-adapter-h5.md)的default-dark/非Worker consumer
约束存在现存失配，须独立协调；本片没有放宽测试或冒充全绿。它仍是完整Goal的
未关闭架构事项。KD003未实施，KD011/A33待用户且未采用；P1–P4全量仍partial。

A119按本A93已接受依赖协调C50旧消费者库存，生产净0；具体可选边界与验证见
[A119](worker-history-responsibility-convergence.md#a119协调两项c50旧消费者库存)。
