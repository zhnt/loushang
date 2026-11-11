# A87：Windows cleanup 当前调用链与真实剩余 IO

- Authority: COD-RESP-GOAL-002 当前事实复核；纠正A82审计判断，不是新迁移交付。
- Design status: 三独立视角静态复核；相邻stage capture接收方案仍是候选。
- Implementation status: 本片不修改生产实现；完整P1–P4/15K仍partial。
- Owner: 原PackageProduct、Worker、Hosting及Coding产品政策。
- 实物：`75a8b59578d01158d3367d4d54e513b3264f66aa`，1967生产源/13包资源SHA核对。

## 纠正A82的宽泛判断

A82把cleanup的`review_runtime`/`inspect_native`概括为仍回借Code厚IO，判断过宽。
当前两个Code入口已是准入/实参装配加对原Core程序的调用。A56早期未闭合的历史
不能证明当前仍未闭合；本片没有新迁移收益，也不把这些已共享程序再实现一次。
仍可讨论多层薄接线的成本，但effectful callback不等于Code持有另一份物理算法。

| 当前调用/事实 | 实际程序owner | Code保留 |
| --- | --- | --- |
| cleanup `current_tree_witness` | 原PackageProduct `capture_windows_product_worker_cleanup` | attempt准入、三字段实际Review构造 |
| orphan review | 原PackageProduct `capture_windows_product_worker_orphan_runtime` | 具体DTO及原调用绑定 |
| recovery inventory取得和联接 | 原PackageProduct `inspect_windows_product_worker_recovery_inventory` | Product/os准入、具体记录类型与既有owner绑定 |
| retirement目录 | 原PackageProduct读取 | 名称/范围政策及延迟导入绑定 |
| payload目录与成员 | 原Worker `WindowsStageInspection`及Resources IO | 产品准入与返回类型 |
| launch intent | 原WindowsProductWorkerIntentRecords/Resources receipt IO | 产品记录/标签 |
| provisioning | 原Worker journal | Product/os准入 |
| Supervisor、receipt、activation | 原history journals | 实际DTO/准入绑定 |
| 原生Job缺席观察 | 原Hosting Windows API | 具体证明政策 |

Code的较厚部分是authority身份、normal/crash/enrollment准入、fresh witness比较、
native/C5交叉证明及错误转布尔。这些产品判据不能为减目录行数整体放入通用层。
本静态核查不证明整个普通Worker或所有Windows恢复路径均已领域化。

## 不应合并的读取与锁边界

当前顺序是registry orphan读取完成并退出其锁，随后GC guard，再读retirement、
payload、intent、native、Supervisor、receipt和Job缺席，接着第二次独立读native、
C5 retained及成功末次currentness。不是持registry锁跨GC，也不能把GC guard替为
read_guard。第二次native读取是独立重验窗口，不能缓存第一次结果以“去重”。

repair入口另在registry.repair_orphan的validation_guard内嵌write-GC；它与普通
cleanup读取不是同一锁域，不能强套一个取得模板。

## 已确认的不同剩余场景

`windows_stage_review._capture_stage_bytes`仍有约110行完整物理程序：ACL、借root、
stage及多级child FD、marker/唯一成员、payload大小/SHA、末尾identity重验和反序
close。底层`_read_checked_file`、`_require_direct`、`_verify_marker`已经是共享
WindowsStageInspection的薄调用，不能把它们重复计作新共享收益。

这个capture是独立业务操作，不是上述cleanup callback里仍有厚IO的证据。可评估
由现有PackageProduct组件直接接actual Product和原WindowsStageInspection来承接
完整操作；Worker不得为此反向依赖PackageProduct，也不另造root-owner协议、
RecoveryBindings框架或采集器。Code保类型准入、实际Review/捕获值及原外层GC合同。

采用前仍须给完整替代源、全部端口/适配成本、原行为对照以及成功/读取失败/identity
变化/取消/close覆盖路径。尚未实施或证明净简化收益，不能提前计行数减少。
相邻offline snapshot、attempt-reference和stage retirement也须各自完整界定，
不能借它们把当前cleanup链重新标成未共享，亦不采用A33/KD011待用户范围。

## 验证边界与接续

三个独立视角均沿当前源码追到原物理owner并确认上述纠正。七份原实际源及完整
生产frame核对保存在树外`a87-worker-current-path`。本片未执行运行/native测试，
未修改源码、测试、fixture或gate，不把静态调用链当Windows原生证明。

下一实施范围优先上述完整stage capture的现有owner接入；若实际全成本证明只是
加层，则退回方案，不重启已经共享的cleanup采集。完整Goal保持active/partial。

## A88后续处置

以上候选/未实施描述为A87时点。A88完整capture已接通现有PackageProduct并获
三视角有界接受；Code保公开Review/Error与准入，私有临时captured值归接收owner。
实际157项通过，Code−90/接收+131/系统+41，不冒称系统净精简；原Worker primitives
保持字节相同。具体合同、失败修正及平台限制见[A88交付](windows-stage-capture-custody-convergence.md)。
其余cleanup当前事实及相邻未完成范围保持。
