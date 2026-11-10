# A88：完整 Windows stage capture 归原 PackageProduct

- Authority: COD-RESP-GOAL-002 有界职责交付；不替代完整P1–P4验收。
- Design status: accepted，Root按现有授权综合职责/复用、运行/失败、数据/兼容三独立视角接受实际R5。
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
