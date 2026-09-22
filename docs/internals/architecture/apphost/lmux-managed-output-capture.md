# lmux 受管命令输出留存

状态:执行侧实现与验证中,完整受管接线未完成;补充 lmux M0 的实际暂存消费者。

## 目标与边界

把命令 stdout/stderr 的实际暂存写入接入既有实例 128 MiB、namespace
512 MiB 配额。不是任意工具的磁盘/内存沙箱,不涵盖工具自行写入 workspace
或绕过接口写入 TMPDIR。Session 持久根与旧非 managed 执行语义不变。

端口属于 `harness/workspace/exec`,Session adapter 负责组合和 blob 发布,
AppHost 实现配额与受管文件 owner。Harness 不反向导入 AppHost 类型。
捕获句柄仅由可信本地组合注入,不进入 wire、工具参数、可复制配置或 repr。
不支持该端口的 delegate 必须在 spawn 前拒绝,不回退旧暂存路径。

### 执行端口(设计复审通过,接线验证中)

在 `harness.workspace.exec` 定义中性 `ExecCaptureSink`,提供
`async append(chunk: ExecOutputChunk) -> None` 与同步、幂等、无 IO 的
`stop_accepting() -> None`(只封闭新增写入,不关闭文件或退额)。另设显式
`execute_captured(request, *, capture, signal=None, on_update=None)` 路径;
不把 capture 塞进 `ExecRequest`,也不复用可选 `on_update` 作为能力证明。
原 `execute` 和两套后端的普通调用语义不变。受管组合只接受明确实现
captured 路径的 delegate;不支持时在任何 reserve/create/spawn 之前拒绝。
方法存在只表达可信本地实现的合同承诺,不宣称能约束任意恶意插件。

候选的职责划分如下:

- Session adapter 在 prepare 前把新 capture 收进原 pending 生命周期,
  负责 prepare、调用 captured 执行、双流 seal、发布和最终清理;后端
  只借用 append 与封闭写入准入,不拥有 reserve、seal、退款、Session blob
  或目录权限。
- 本地与授权执行后端都将 stdout/stderr 的增量送入同一 sink,等待每次
  append 结算后再继续该流读取;最多两路在途,不另建无界队列。sink
  串行化原 native 写入并保管任务,调用者取消不能遗失实际写入的结果。
  同一流按读取顺序提交;跨流不承诺操作系统级全序。正常 append 等待
  自身写入结算;取消则先 stop_accepting,允许取消中的 reader 返回,
  但原 capture 继续强引用保管 native 任务及未知回执。decoder finally
  flush 不得重新打开写入准入。进程终止必须先发起,不能等 native 写入
  结算才终止;adapter 之后仍负责独立检查 native 债务,不以 reader
  已返回或已取消冒充 capture 完成。
- captured 路径强制三种输出缓冲 rolling、禁用旧文件留存及 artifact_dir。
  候选每个缓冲最多 100 KiB;preview 上限不大于该值;读取与文本分块
  最多 16 KiB 字节/字符,编码最坏单块 64 KiB。授权 handle 必须遵守
  `read_stdout/read_stderr(max_bytes)` 合同;不能把请求里的更大上限带入。
  sink 将最多 64 KiB 的编码块有界拆成 native append 允许的 ≤16 KiB
  写入,不把编码块大小与底层 record 上限混为一谈。
- 日常留存失败由 sink 记录双流共享 sticky 状态,后续 append 为有界
  无写入操作,仍让后端完成 drain。合同错误或无法结算的 native IO
  不是普通 quota failure,不用吞异常冒充留存失败;保留原执行清理路径。
- captured 运行期必须同时监督原 stdout/stderr reader、进程退出及
  abort/timeout 任务。不能仅在 `_publish` 插入 await 后继续先等进程
  退出:reader 因 sink 合同错误结束时,子进程可能堵满管道而永不退出。
  任一 reader 异常立即进入原进程终止、排水和 join 清理;正常 EOF 不
  等于进程退出。复用原任务和 owner,不增加第二个进程管理者;普通
  quota sticky 返回仍属于正常 drain,不触发该异常分支。
  监督从取得原进程 handle 后、开始写 stdin 前就生效:stdin 写入和
  close_stdin 也是原执行拥有的任务,不能先无限等待 stdin drain 再开始
  监督。覆盖子进程不读 stdin、持续输出且 sink 首次失败的交叉管道场景。
- 后端结束仅证明原读取任务已结算,不证明磁盘完整。adapter 只有在
  sink seal 返回双流完整回执、`stdio_complete=True` 且无留存失败时
  才有发布资格。普通 preview 的 stdout/stderr_truncated 不取消资格。
  等待者取消、执行异常或正常返回的 `cancelled=True` 均跳过发布,继续
  保管 capture 清理。`timed_out=True` 但非 cancelled、stdio 完整且 seal
  成功时允许保留截止终止前的完整输出;结果仍明确超时,不能改成成功。

能力获取候选签名为 `ExecService.capture_executor() -> CapturedExecExecutor
| None`;`CapturedExecExecutor.execute(request, *, capture, signal=None,
on_update=None) -> Awaitable[ExecResult]` 绑定获取时的原后端,不在调用时
重新挑选后端。获取为无 IO 操作,在 Session capture prepare 前完成。
执行能力负责 materialize 原请求、钳制 captured 参数并校验返回结果。
两套后端实现独立 `execute_captured`,不让调用者直接用普通 execute
加 on_update 伪造该能力。

默认获取器必须核对实际后端是否实现 captured 合同,不能只检查
ExecService 上继承来的方法。另有自定义 execute 的包装器,若未显式
实现 captured 策略则返回 None,不返回内部后端能力绕过包装层。
现有 SessionOutputPersistingExecService 也不能因基类默认建立了一个
未使用 LocalExecBackend 而被误认支持。显式受管 Session 分支会调用
其原 delegate 的获取器,不调用自身继承的默认获取器。

Session prepare/seal 回执与可重复 cleanup 的具体类型仍待冻结;
此执行侧能力并不宣称整个 capture 生命周期接口已完成。

这些数值限定捕获层的新增缓冲,不是整个 Python 进程的 RSS 上限;
已有回调、工具、Session blob 发布和并发执行另按各自合同计量。
先评审并实现两后端的真实 captured 路径及无旁路回归,再接 AppHost
capture/精确删除退额;仅增加 Protocol 或给后端打支持标记不算完成。

执行侧修订经三视角复审可作为实现输入;上述 reader/stdin 监督、
取消准入和结果资格问题已在设计中关闭。首个实现为私有
`exec/_capture_supervision.py`:借用原 stdin、双 reader、exit 和 abort
任务,返回 exit/abort/timeout 或传播 IO 异常;正常 EOF 仅移出观察集合。
不创建第二个进程 owner,也不取消借用任务。已补 8 个确定性 asyncio
用例;仅该辅助函数通过静态检查,不足以证明真实子进程接线正确,
还需以下后端验证。

后续已实现中性 capture 接口、绑定原后端的获取器,以及两后端显式
captured 路径。两后端使用上述监督,并禁止旧 artifact 文件路径。
代码复审发现并修复:内置后端子类隐式继承绕过普通策略、封闭回调抛错
阻止授权进程清理、本地清理二次取消跳过后续结算。新增本地借用准入
保护仅记录封闭错误、阻止后续 append,不取得存储清理或退款权限。

首轮监督测试因误用仓库未安装的 pytest-asyncio 失败(8 failed),已
改用现有 asyncio.run 风格。首轮两后端与旧 execute 集合 50 passed
(6.78 秒),但运行与最后修复重叠,不作为最终修复验收。已追加后端
策略包装、封闭双异常和二次取消/native 仍 pending 回归并申请最终验证。
Session prepare/seal/发布、AppHost capture 和精确退额尚未接线。

复核进一步要求清理任务不能经外部 task factory 发布。captured 本地
强制清理改用可信内置 asyncio.Task、绑定当前 loop 并立即保管引用,
之后 cancellation-atomic join;不新增资源 owner,普通 execute 不经过
此新任务。生命周期复核认可该边界,补 before/after-schedule 外部工厂
故障均不得命中 cleanup 的定向验证。内置 Task 构造器被猴补或 OOM
不在该外部工厂合同内;新增验证仍待实际运行结果。

修复后的监督、两后端和普通执行集合正常结束:62 passed(6.89 秒)。
后续内置 Task 的最终修改及新增工厂故障用例另行针对性验证,不计入
这次 62 项结论;源码类型检查通过。整体受管 capture 仍未交付。

最终本地清理的外部工厂隔离与二次取消定向验证正常结束:3 passed、
6 deselected(0.83 秒),不重复此前未变更的普通执行检查。

## 捕获与发布合同

### Session 租约(设计已复核,适配器待接线)

实现进度:`SessionOutputPersistingExecService` 已新增显式
`capture_factory` 分支,内部 `_output_capture.SessionOutputCapture` 保管
8 个 pending 租约、封存后顺序读取/导入双流、独立清理诊断与 close。
原 scratch 分支保持兼容;已有包装器不允许静默更换 capture authority,
非持久 Session 显式传 factory 会拒绝。首次异步使用绑定原 event loop。
并发清理等待者只能清除自己加入的原 task 引用,不覆盖后续阶段。
新增发布与清理交叉、迟到 prepare、容量债务、factory/loop 隔离和
多等待者清理回归。`test_output_capture.py` 与旧
`test_output_artifacts.py` 配对验证共 **29 passed in 1.74s**;包括
发布/清理双失败、限额预检、超时与取消及后继清理回执竞态。
AgentProduct 已增加可信
`output_capture_factory` 注入,并在进入 Graph/runtime profile 处置前按
对象身份去重,先同步 fence 两个执行适配器,再取消并 join 原
side-question 生产者,之后逐个 close;不持有 model-call bind lock
等待执行;任一清理失败则保留原 Session
authority 供重试。该生命周期接线待复审及实际 Product 全链路验证。
`tests/coding/test_owned_capture_shutdown.py` 已新增实际 Coding runtime、
Graph-owned transcript writer 与假 capture/backend 的交叉回归:blob
已发布但 close 失败时原 writer 必须仍 busy,原 capture close 重试成功
后才能重新获取 writer。该测试运行待返回,不等于实际 AppHost native
删除/退额验收。Graph 准备失败的独立回滚路径仍在复核,正常退出
前移 close 不足以单独证明所有失败路径的 authority 释放顺序。
底层 Session provider disposer 已加入同步 retirement guard:捕获仍有
pending/active 时在任何释放动作前拒绝,由原 Graph 保留 retirement。
外层 prepare except 此时仅 fence、保留原局部 generations/components、
标记必须 retire 后抛回原错,不持锁等待;正常 dispose 在锁外完成
capture 后重接原 Graph/catalog 回滚。此增量仍待复审及故障运行验证。
生命周期局部复核已关闭所报问题;排队 prepare 在获得原 model lock
后再次检查 retirement latch,防止早期失败尚无 Graph pending 时继续
构造。实际 Coding writer、capture 与 shutdown 三模块回归合计
**24 passed in 10.65s**,包括该锁屏障和原 provider retirement guard。
此验证仍使用假 capture/native backend,不证明 AppHost 删除/退额。
此前退出
helper 与清理诊断/命令/协议投影组合 **26 passed in 5.24s**,不用于
证明本次新增 guard 和排队检查已运行通过。
真实 AppHost factory 尚未接线,因此尚未激活实际 lmux 受管输出。
本次三视角局部代码评审报告的 factory 忽略、跨 loop 操作及迟到
cleanup waiter 竞态已修复;架构与生命周期修复复核通过。成功移除
pending 同样要求当前 cleanup task 身份匹配,不能仅依据 lease 的
pending=False 提前放弃仍未返回的后继回执。新增回归同时覆盖后继
回执成功/失败;尚不能以静态复核代替这些运行结果。

可信组合注入 `ExecCaptureFactory.new_capture() -> ExecCaptureLease`,此步骤
无 IO。adapter 在构造时先获取并保存原 delegate 的 captured executor;
不支持则拒绝,不让继承的备用后端或旧 TemporaryDirectory 接管。
受管分支不预建旧 scratch root。每次执行把新 lease 加入原 pending
集合后才调用 `prepare()`;失败或取消也不丢失这份原对象。

lease 除执行侧 sink 两个方法外,候选接口为:

- `async prepare() -> CapturePreparation`:只有 READY 或
  RETENTION_UNAVAILABLE 两种已结算结果。后者仅由原双槽零效果容量
  拒绝产生,明确使用不写盘的 sink;未知 commit/create/close 回执抛错
  并留在 pending,不能变成该降级结果。不自动换 lease 重试。
- `async seal() -> SealedExecCapture | None`:封闭新增 append,核对原
  双流及全部 native 债务。完整才返回同一 lease 绑定的两个只读 source;
  已知 sticky 留存失败返回 None,未知 native 债务不伪装成完整或普通
  配额不足。source 不携带可传输凭据,不是清理/退款许可。
- source 提供 `size_bytes` 与 `async read_bytes(max_bytes=...) -> bytes`,
  必须核对 seal 时的原文件身份、长度、变更戳;读取由 lease 保管 native
  任务,不暴露可由 caller 改写的路径。adapter 在读取前核对双流总量
  和 Session 每 blob 限额,继续既有 hash/blob import,不引入第二份
  Session manifest。两个 source 必须同属本次 lease,不接受后端结果里
  的旧 artifact path/ref 代替这份封存结果。
- `async close() -> None` 与 `cleanup_pending: bool`:继续结算原任务、
  精确删除、父目录同步、原文件句柄关闭及原 allocation ID 退额。
  允许在同一 lease 上继续未结算阶段,不重新执行已完成或未知的删除;
  仅 close 成功且 pending=False 才从 adapter 集合移除。

正常执行但无法完整留存时,清除两路物理路径/ref 并设置原
artifact_retention_error;process exit_code、timeout、cancelled 不改写。
发布失败和清理失败分开记录:暂存已清理不能证明 blob 未发布,blob
已发布也不能证明暂存已释放。Session/runtime 的退出路径必须等待原
adapter pending 集合结算,不能只结束 execute 局部 finally。

以下规则已纳入设计复核;它不代表精确删除回执或退款实现已经具备。
中立接口已落在 Harness 的 `workspace/exec/capture_lease.py`:
`ExecCaptureFactory`、`ExecCaptureLease`、`CapturePreparation` 与只读
`SealedExecCapture`/`SealedExecSource`。双流均为必填 source,空流使用
长度为零的 source,不以缺席表示完整。接口本身不执行 IO、不验证具体
实现的所有权,也不代表 Session adapter 或 AppHost capture 已接线。
接口落地后架构局部复核通过,无新增 P1/P2;Ruff 与该模块 mypy 通过。
这不替代实现阶段的并发、取消和删除/退额验证。

接线位置已核对:`AgentProductSession` 当前分别组合命令与工具执行
适配器,两者可能为同一对象;退出走 `_dispose_session_runtime_profile`
及原 `base_dispose`。实现时需对适配器按对象身份去重收尾,并在释放
Session 原 blob/writer 权限前结算其 pending;构造失败也须保留已创建
适配器,不能只在正常 dispose 中添加 close。

复审收紧的阶段与容量规则:adapter 同时最多保管 8 个 pending lease,
满额在新 lease/prepare 前明确拒绝,清理债务同样占位。首次 close 同步
fence 新执行,join 已接纳执行及原 prepare,再逐 lease 收尾;prepare
返回后、进入 executor 前复核 closing,迟到 READY 不得启动进程。
execute.finally 与 runtime close 必须 join 同一 lease cleanup 任务,
不得并行启动两份清理。重复 prepare/seal 只重接原阶段;重复 close
只 join pending 原任务,原任务已失败结束时才续未完成阶段。

source 的大小是 seal 时冻结值。read 在 lease 同一准入域登记后才
启动 native,单 source 至多一份在途 read,额外并发请求明确 busy;
取消 waiter 不取消原 native。close 同步禁止新增 append/read,并等待
已准入读取结算后才删除。closing/closed 后旧 source 一律拒绝,不重开
路径。adapter 顺序读取 stdout、stderr;读取前核对两流合计不超过
128 MiB 和各自 Session blob 限额,读取中仍检查上限及最终长度。
这限定本次双流 payload 合计,不宣称是整个进程 RSS 上限;现有 blob
import 所需副本、native 分块及其他并发活动不能从测量中排除。

结果交付候选:blob 已确认发布但临时清理/退额失败时,保留真实
exit_code 和已确认 refs,lease 继续占 pending;不把它写成"输出未留存",
不因这项收尾错误重跑命令。拟新增兼容的 keyword-only
`ExecResult.artifact_cleanup_error` 区分清理债务与 retention error,相关
工具结果投影同步传达该诊断。发布回执未知但暂存清理成功时,仍由原
Session blob owner 保管未知发布,不由暂存状态推断成功或重新发布。
该兼容字段及工具/协议/命令结果投影已实现,默认 None 时不增加工具
输出字段;当前只允许 temporary_cleanup_pending 固定代码,不接受原始
异常、路径或凭据。三条投影复用同一封闭校验,两个别名冲突一律拒绝。
值表示结果交付时的清理诊断,不是随后重试后的实时状态;pending owner
仍是清理依据。已补字段兼容、refs/exit 保留、双错误及 raw/别名冲突
回归,运行结果待返回。尚未连接真实 lease 发布/清理交叉故障流程。

修订后的 Session 租约阶段与容量设计经架构、生命周期复核可进入实现;
精确 native 删除/退额不在此次设计通过范围内。

- managed 分支先收养 capture,再做任何 reserve/create,不先创建原
  TemporaryDirectory。原 adapter/runtime 保管 pending capture,不能只
  依靠 execute 局部变量和 finally。
- 一个 capture 覆盖 stdout、stderr 和合并输出的全部状态。两套执行后端
  都使用硬钳制的 rolling 内存上限;用户参数不能重新开启 full capture。
  禁止 `_build_preview` 再走 `_write_output_artifact` 形成旁路。
  纯内存降级需要显式无文件 capture 路径:现有 capture_full_output=False
  单独设置仍创建文件,不能仅翻转此布尔值就宣称无暂存效果。基础修复后
  与 retain_output_artifacts=False 组合可真正纯内存捕获,后续受管组合
  必须同时强制两者,并明确记录配额导致的留存失败。
- 追加按 UTF-8 + surrogateescape 实际字节计费,编码 chunk 和排队容量
  均有界。双流共用总预算,不各自领取整份实例额度。磁盘 IO 放在原有
  生命周期保管的 offloop 执行中,等待者取消不取消原 IO 或丢弃回执。
- quota/写入失败是双流共享的 sticky retention failure。运行中失败后
  停止两路落盘,继续有限内存捕获和 drain;原 timeout、取消、stop 仍有效。
  真实 exit_code 不变,使用既有 artifact_retention_error 明确说明完整
  输出未保留,不将进程成功冒充留存成功。
- 发布前必须取得双流 seal 且全部 append 结算、没有 retention failure 的
  完整回执。任何一路失败,跳过整个双流发布并清除物理路径投影;不得把
  partial 文件发布成完整 blob。blob 发布未知回执仍由原 Session blob owner
  保管,不以暂存清理推断未发布。
- 发布期间暂存与最终 blob 共存。暂存额度直到真实释放前持续收费;blob
  计入 Session 存储策略,不能声称 512 MiB 限制包含全部持久历史。复制峰值
  和两路 payload 内存必须另行有界;不能无限 read/join 后再检查。

### 当前发布路径的已有界限与剩余成本

源码复核:现有 `SessionBlobPolicy.max_blob_bytes` 默认 128 MiB。
`read_stable_artifact_source` 在读取前检查文件大小,读取中按最多 1 MiB
分块并检测超限,之后才 join;因此它并非无限读完后才检查。但 Session
adapter 的 `prepared` 会同时保留两路完整 payload(默认上限合计 256 MiB),
单路 join 期间还会暂存分块与新连续 bytes。这不是整个过程的峰值上界,
后续 blob import、已有引用校验和并发执行也需计入。

受管接线应继续使用现有稳定读取/Session 发布身份校验,并显式限定本次
capture 双流发布预算;不能把现有每 blob 限额当作实例级内存或磁盘配额,
也不因 managed 需求修改旧非 managed 的 Session 默认存储策略。

## 启动前失败的区分

双流必须使用原子预算准入,避免第一路成功、第二路不足造成半准入。
接口必须返回与本次准入绑定的明确"零效果容量拒绝"结果,不能仅捕获
通用 capacity 异常后推断无效果。该结果允许退化为纯 rolling 捕获并运行命令,报告
留存失败。若已有 create/预留未知回执或清理债务,则不得在未结算状态下
把它当成零效果失败继续 spawn;先保管、结算或失败退出。端口不支持、
身份错误等合同失败同样不得静默降级。预算 COMMIT 未知不属于零效果拒绝。

## 精确释放与复用

现有 ManagedStorageBudgetV1 只有 reserve/bind,不能直接用于可循环暂存。
新增 release 只允许 temporary,并遵循:

1. 封闭追加,join 双流原 native 任务与发布读取。
2. 校验精确文件/目录身份,unlink,父目录 fsync,原句柄全部关闭成功。
3. 原 registry 短事务按完整 allocation/reservation ID CAS 退额。

Linux unlink 后仍打开的文件继续占盘;未知 close/delete/sync 一律保留
收费。旧 allocation ID 的重复 release 不得碰同 slot 新 allocation。
COMMIT 回执丢失只能核对原 ID 收费状态,不重复删除。历史 unbound、路径
不存在、PID 消失不是退款证据;只有原 owner 能证明 create 从未准入时,
才可释放本次未绑定预留。slot 复用必须产生新 allocation ID。

## 实施与验收顺序

1. 冻结中性 capture/完整回执接口、可信注入与 capability 检查;覆盖两后端
   和三种缓存,不启用 managed fallback 旁路。
2. 实现精确 temporary 退额和 slot 复用,补 COMMIT 丢回执、旧 ID 重试及
   unknown-close 不退款的确定性验证。
3. 实现受管 capture 和 Session adapter 接线,纳入原 pending 生命周期;
   同时验证 spawn/取消/发布/清理失败。
4. 真实子进程双流超额后仍完成可验证最终动作并返回指定 exit_code;并发
   最后一份额度竞争、长行/无换行/分块 UTF-8、磁盘与内存峰值、满盘和短写。
5. 验证正常命令重复执行不会累计耗尽已释放配额,异常原件不被误删;旧
   非 managed 路径兼容。再接插件等其他实际消费者。

三视角初审提出的关键缺口已纳入本稿:实际写入旁路、未支持端口的拒绝、
双流失败一致性、发布资格、强引用保管及精确退额。接口与启动前降级细节
仍待具体类型/数值冻结;三视角边界复审通过,可作为接口实施输入。
现有 Session 输出、owned 输出与 exec service 基线 26 passed(2.76 秒)。
本稿不是功能完成或整体 goal 验收记录。

## 已验证的前置实现:禁用留存不写盘

共享 `_StreamCapture.append` 现在仅在 retain_output_artifact=True 时创建
和追加文件。rolling 模式关闭留存后只更新原计数和有界缓冲;full-capture
关闭留存的预览路径原本就不写文件,但仍保留完整内存,不能作为 managed
有界模式使用。没有新增配置、资源 owner 或 AppHost 依赖。

先加强原测试禁止 mkstemp,复现 rolling 模式 1 failed、full-capture
1 passed;修复后本地/授权执行、Session 输出及 owned 输出等 59 passed
(6.10 秒)。新授权后端测试验证双流多字节、真实退出码、无临时文件和
三种 rolling 结果的留存大小,不作为整个执行过程内存峰值证明。三视角
局部复核、Ruff、源码 mypy 通过。此处仅为无文件降级基础,
尚未完成配额准入、原子双流预留、完整 capture 回执及安全退额接线。

## 原子双流账务准入

原 `ManagedStorageBudgetV1.reserve_temporary_pair` 已实现排他双槽事务。
输入必须是同 service/instance/root 的两个 temporary allocation、不同
slot,并要求调用方在事务前保管两个不同 allocation ID。任一 slot 或
ID 已存在均先报 conflict,不认领旧记录、不把冲突包装成容量不足。

事务统一检查行数加二、namespace 与实例的两路容量合计,成功一起插入;
逻辑额度不足且完整事务/锁退出成功、期限仍有效时,才返回独立的
`ManagedTemporaryPairCapacityRefusedV1`,绑定 namespace、原有序 pair 和
原 ID。物理增长准入、COMMIT、关闭或其他 capacity 异常均不转换成此值。

该值只证明本次账务未新增两槽,不是 native 零效果或文件创建权限。
提交回执未知时仍收费,后续必须在原 capture 保管下按原 pair/ID 原子
对账;不能仅看两个目的相同就收养另一调用者的记录,不能重新选择 slots
或补插半对。原子查询、native capture 与退额尚未接线。

原账务基线 21 passed(2.77 秒);首轮新旧回归 33 passed(4.44 秒)。
三视角局部复核通过;按建议继续补 namespace 最后额度竞争、已占用 ID
用于新 slots、非法 ID 零 IO,以及事务退出后到期不交付成功/拒绝结果。
最终双流账务专项 20 passed(1.09 秒),相关 Ruff、源码 mypy、文档轻量
检查及 diff-check 通过。实际命令输出 capture 的配额接线仍未完成。

## 原 pair 的只读精确对账

新增 `lookup_temporary_pair`,按原有序目的与调用方保管的两个 allocation
ID,在同一只读事务中查询。两个槽位均无对应记录且两个 ID 也未被占用时
返回 None;完整原 pair 返回当前 reservation/binding;半对、其他 ID、
原 ID 被移到其他 slot/root 等情况均报 conflict。不写入、不补插、不退款。

绑定状态只是观察值,不是文件创建资格。None 同样不能证明此前没有
native 效果;未知 COMMIT 后仅可由原 capture 使用其既有身份继续对账。
完整退出事务后复验 deadline,成功和空结果均不得在期限后交付。

三视角局部复核通过;新旧账务回归 49 passed(3.73 秒),涵盖提交回执
丢失、部分存在、ID 替换、目标重定向、已有 binding 与退出后超时。
此处补齐了账务对账,实际 capture、原 owner 结算和安全退额仍待实现。

## 删除完成凭据:实现前约束

源码复核发现,`PrivateManagedDirectory._cleanup_pending` 允许原文件已
missing 时继续清理。这符合一般临时残留清理语义,但不能证明原文件空间
已经释放,因此不能直接把 `_pending` 清空当作 temporary 退款资格。

保留原 directory owner,新增其内部小型 removal tracker,而非新 runtime
或清理控制器。capture 在首次 IO 前保管 tracker;tracker 冻结目录身份、
完整 expected snapshot、文件名和本次操作身份,拒绝 lock 文件,未结算
数量有界。它必须独立于允许 missing 的普通 pending 清理。

开始删除前,原 capture 封闭追加与新借用,并 join 原双流 IO 和发布读取。
以原 inode 的验证 fd 贯穿隔离、删除和同步,禁止用重新打开的同名文件
替换原句柄。沿既定"先隔离后删除"原则,在原私有目录中隔离后再次核验
身份;隔离或身份回执未知时保留原件/隔离件,不销毁可能的替代文件。

阶段单调推进:

1. 尚未删除:核验原路径/隔离路径、原 fd 身份及单链接文件条件。
2. 删除已准入但回执未知:保持 unknown,不以当前 missing 补成功,不能
   再删同名替代文件。
3. unlink 明确返回:通过原验证 fd 核验 st_nlink == 0。正常 unlink 返回
   不足以证明删除的是原 inode;核验失败不能退款。
4. 仅待目录同步/关闭:重试只续原 fsync 和尚未进入 close 的原句柄,不再
   按名字 unlink。未知 close 沿原 `_uncertain_closes` 保债,不重关 fd 数字。
5. complete:父目录同步、所有受管文件句柄与借用均已结算,才形成绑定
   原 tracker 的完成凭据。不是可任意构造的 complete=True 配置值。

该完成事实只覆盖原受管资源域,不声称能发现任意外部进程持有的 fd。
capture 还须核对原 allocation ID、root/file identity,才能做 temporary
专用退款 CAS。重启后无原 tracker 的残留继续收费,不由路径不存在恢复
为成功;退款回执未知只对账原 ID,不重新删除。两路可分别结算,但失败
一路的原 tracker 和费用必须保留。

三视角设计复审要求的故障矩阵:删除前失败;隔离后身份替换;unlink
成功后丢回执;unlink 后目录 fsync 失败且同名新文件出现;close 未知后
fd 复用;预先 missing/symlink/hardlink;原 append/发布读取未结算;旧
退款 ID 遇新 slot 分配;同一完成回执重复使用零新 native 效果。

删除 tracker 初始实现已加入原 `PrivateManagedDirectory`,退款接口尚未
实现。`prepare_data_removal` 无 IO 登记最多 8 个原对象;`remove_data`
保管同一 fd 经过隔离、unlink、目录同步和关闭。未知 rename/unlink/close
不重放;isolated 阶段保存并复核完整快照。可恢复 tracker 未结算时
directory.close 拒绝改变关闭状态;只有未知阶段时可回收尚未尝试关闭
的原 fd,但保留 removal 债务并报 unavailable,绝不据此形成 complete。
新入口在事件循环内前置拒绝,供原 offloop owner 调用。该初始实现仍在
局部评审/测试中,不能作为退款凭据或宣称实际 capture 已完成接线。
初始删除/隔离组合 **15 passed in 0.61s**。之后新增单调
`abandon_data_removal`:保留原 phase、封闭进一步删除,允许目录回收
已知句柄,但保留 tracker 债务并报 unavailable。new/opened 永久冲突
和 isolated 内容变化不再迫使原句柄永远打开;该修复静态复核通过,
新增放弃、完整快照变化、事件循环拒绝、unknown-close 加 fd 复用
交叉回归已补齐并运行;删除与隔离组合 **20 passed in 0.81s**。
该结果不包含尚未实现的退款或实际 capture factory。

### 下一接缝:删除完成与原账务绑定(待评审)

退款不能只接收公开 snapshot 或 caller 可改的 tracker.phase。计划由
原 native owner 在所有阶段成功后铸造只读完成对象,原 tracker 保管
该对象身份;重复取得只返回同一对象,不再做 native IO。

删除前的可信组合必须绑定原 budget/database 实例及完整的已绑定
reservation(allocation ID、root key/identity、file identity、slot、
capacity)。该绑定作为本次原操作的不可变上下文进入 tracker,不在
完成后才按 inode 推导:同 inode 数字被新文件复用也不能匹配新账务。
native 层只保存不解释这个不透明绑定,不导入 storage_budget。
仅保存不透明 reservation 不足以证明目标一致:budget 侧必须在绑定及
退款时,把原 native owner 自身冻结的 root key/identity、expected file
identity、capacity 与 reservation 双向核对。native 目标不能从该
reservation 回填,需来自原目录/文件 owner;应以两个合法文件和两份
合法 reservation 的交叉绑定负测,证明"删除 A,释放仍存在的 B"被拒绝。

temporary 专用 release 在任何事务前验证原绑定和原完成对象身份,
仅按原 allocation ID 及完整 reservation CAS 删除收费行。已无原 ID
可返回已释放,但不按 slot 删除新行;原 ID 仍存在却内容不符则冲突。
未知 COMMIT 后,只重复同一 CAS/原 ID 对账,不调用 native 删除。
log/trace、unbound、abandoned/unknown 或仅路径 missing 全部拒绝。
allocation ID 不能在退款后复用。永久保存每次退款 tombstone 会随正常
采集无限增长,不适合可循环暂存。候选采用 namespace 单行持久高水位:
temporary ID 由递增序号编码成现有 32 位 hex;原账本提供只读的下一对
候选 ID,reserve 在原双槽事务中核验它们恰为当前下一对,并同时推进
高水位。并发旧观察明确 conflict,不重新选择 ID/slot 或自动重跑命令。
逻辑零效果容量拒绝不推进高水位;COMMIT 未知仍按原 pair 对账。退款
仅删 allocation,不回退高水位;序号耗尽拒绝而不回绕。单槽 temporary
reserve 也须使用同一序号源,不能保留可绕过的不受约束 ID 入口。
此候选需要严格存储格式升级及相应旧格式拒绝测试;不会自动迁移数据。
设计复核通过后,该 ID 准入已实现为格式 12:固定前缀
`74656d7000000000` 加 63 位正序号的 16 位 hex,高水位存在原 identity
单行;单/双槽统一来源,active 行还须通过域及高水位一致性校验。
原双槽调用者需先读取候选 ID,尚无生产调用方。新增序号及竞争回归、
旧格式 11 拒绝测试;结果待返回。删除完成凭据与真正退款 API 仍未实现。
原未创建文件的零效果退款需另一种由创建 owner 证明的完成事实,
不借用本删除凭据;这一分支也必须在启用实际 capture 前实现。

初始实现进度:native owner 已提供冻结 `ManagedRemovalTarget`、删除前
不透明绑定及完成校验入口;完成时由原 owner 创建内部 marker,不能仅
传 phase 字符串取得完成目标。budget 的 `prepare_temporary_release`
双向核对原目标并绑定原 database,`release_temporary` 复核完成/绑定
后只删除原 ID 对应且完整一致的收费行。已有原 ID 缺失则不改新 slot。
DELETE 仍需要原 `admit_growth` 的物理峰值准入,不消费 stop/control
保留区;空间不足保留收费和原完成事实供重试。相关跨绑定、重复释放、
未知 COMMIT 和物理准入失败回归已补,运行结果待返回。该原型还未接
实际 capture,也未实现未创建文件的零效果退额。
退款与删除组合 **12 passed in 1.39s**。随后补齐同一 absolute deadline
覆盖 native 完成校验 mutex:进入前、取得锁后均复验,超时不进入数据库。
新增到期/锁忙负测与 format 12 原始行 fixture 修正的定向验证合计
**9 passed in 1.48s**;完成 marker、原ID、物理准入不因超时而消费。

### 未创建文件的退额接缝(待评审)

不能以 unbound row 或当前 missing 证明没有创建。计划在原 directory
owner 中增加轻量 creation tracker,capture 在 reserve/create 的首次
native IO 前保管它;它冻结原根、文件名、capacity 和不可变账务绑定。
真实创建只能通过该 tracker:在进入 open/create 前单调标记 admitted。
任意已 admitted 的错误均不发"未创建"凭据,交给原 native debt 结算。

只有仍未 admitted 的原 tracker 能同步 fence 创建并铸造"从未准入"
完成事实;之后任何创建调用都拒绝。budget 侧独立校验原 database、
完整 unbound reservation 以及 native 冻结目标,再走同一原ID精确退额。
已绑定文件的 reservation 不接受此凭据。原 create 任务尚未开始但已经
排队也要受同一 fence:不能先退额、随后排队任务迟到创建文件。
该分支只退明确的零效果预留,不从未知 COMMIT/close 或文件缺失恢复
成成功;正常 created 路径仍须走原删除完成凭据。

生命周期评审补充的强制身份合同:unbound reservation 尚无 inode,
因此仅比较 root 与 capacity 不足以证明同一分配。必须在首次创建前,
将原 allocation ID、slot、严格由 allocation ID 派生的 native filename
与原 tracker 建立不可换绑的一对一关系。原 owner 不得为同一目标重建
第二个未准入 tracker;capture 只使用该次 reserve 所对应的原 tracker。
创建准入检查及 admitted 置位与 fence 必须持同一原 mutex 完成,禁止
检查后释放锁、在原操作真正准入前允许 fence 退额。已排队任务也不例外。

实现验收必须包含同根同额的交叉负测:B 已创建但尚未绑定 inode(包括
bind 回执丢失),不能借未准入 A 的完成事实退还 B;重复注册同 target
不能重新获得零效果凭据;fence 先赢时排队创建无 native effect,创建
先赢时 fence 不生成退款资格。这些要求目前仅为设计约束,尚未实现或
通过测试,不作为实际 capture 已有安全退额能力的证据。

生命周期补充复审确认以上身份约束可作为实现输入。避免长期服务保存
无界 tombstone 的实现约束:原 owner 保留单调 high-water,原 mutex 下
仅接受更大的 format 12 序号;完成、放弃或退款均不得回退。两流 tracker
必须成对原子注册(容量不足不留半对),或对整个 owner 的注册串行化,
不能仅对单个 capture 串行。high-water 与有界在途 tracker 独立保存,
结算后移除 tracker 不恢复旧 ID 的注册资格。该 high-water 只防同一
owner 生命周期内重注册,不是重启恢复凭证:新 owner 不得从历史 unbound
行重新生成 never-admitted 事实,零效果退额始终要求原 reserve 尝试与
原 tracker 的来源绑定。未知 reservation 提交须先查询原 ID 的精确结果,
不能通过新 owner、新 tracker 或新 ID 把未知状态转为零效果。

当前实现增量:`PrivateManagedDirectory` 已加入原 owner 创建 tracker,
两流原子登记、八个在途上限与不回退 high-water;native 文件名由传入
allocation ID 严格派生。原 binding 身份与 owner 双重检查,fence 和
admitted 置位共用原 mutex。创建回执丢失保留 unknown,不重放创建,
close 释放已知资源后仍报告未结清;未准入 tracker 须先 fence 才能关闭
owner。这是 native 原型,不是退额实现:尚需 budget 绑定原 reserve
尝试、检查完整 reservation 与冻结 native 根身份,禁止新 owner 根据
历史行生成凭据,之后才能接入 capture。创建/删除定向测试已发起待收取;
源码 Ruff、mypy 和 diff-check 已通过。新增原 owner/原 binding 交叉负测
在测试启动请求之后加入,须核对实际采集数量再计入通过证据。

创建/删除组合已返回 **12 passed in 0.69s**(四项创建、八项删除)。
随后修复局部评审 P2:`cleanup_pending` 计入所有在途 creation,而
内部 append 准入只检查实际 IO/unknown/removal 债务,避免隐藏尚需
fence 的 new tracker。生命周期静态复审确认该 P2 关闭。新增 Event
控制的双线程竞争覆盖 fence 先赢与 admitted 先赢;另外补创建 fd 真实
关闭后失回执、立刻复用数字 fd 的测试,要求原 close 不伤替代句柄。
这些新增验证尚待运行结果,不能计入上述十二项通过证据。

随后创建专项返回 **7 passed in 0.51s**,含双线程两种先赢和创建 close
回执丢失后的 fd 复用。下一增量为 native 冻结 `ManagedCreationTarget`
(原根 hash/identity、allocation ID、派生名称、capacity),由原 owner
生成,不从 unbound 行复制。`creation_target(require_fenced=True)` 仅在
同原 binding、原完成 marker 和 fenced 状态下返回该目标;完整 deadline
覆盖原 mutex 等待及取得后的复验。创建/fence 前也复验当前 tracker 与
冻结目标一致。该增量及其新增负测尚待专项结果;budget 的原 reserve
来源绑定与精确零效果退额仍未实现,不能仅凭此 target 释放收费。

native 创建目标专项已返回 **8 passed in 0.48s**。当前新增 budget 接线
原型:`prepare_temporary_creation` 先选原候选 ID 并登记双流 tracker,
冻结原 database、allocations 与 owner 上下文;`reserve_temporary_creation`
只允许原尝试调用一次,不接收历史 reservation。成功回执后才进入 reserved,
逻辑拒绝为 refused,其余未知保持 unknown。`release_uncreated_temporary`
同时检查该原成功尝试、指定流的 native 冻结目标与 fenced marker,再按
原 ID 及完整 unbound reservation 删除原收费行,仍经过物理峰值准入。
原 ID 已缺失时重复调用不触碰新 slot;已创建但未 bind 的另一流没有
fenced 凭据,不能借用第一流资格。退款提交失回执仅重试原账务,不重放
native 操作。相关跨流与未知提交测试待返回,局部评审已发起。

此原型尚不完整:未知 reserve 提交目前保留债务,尚未接原事务来源证明
与只读核对;不能将该状态冒充容量拒绝或生成退款资格。实际 capture 还
必须保持 prepare/reserve/create 的先后次序与原任务生命周期,不得在
预留成功前调用 native create。本次接线尚未激活任何 Product 路径。

原未创建/删除退额组合已返回 **9 passed in 1.33s**。局部复审发现并修正
两项 P2:容量拒绝后 native high-water 已前进而 DB 未前进,下一次候选
供给会停滞;现在候选取两端 high-water 的较大值之后一对,reserve 允许
安全跳号,要求首序号严格大于 DB high-water、第二为首加一,仍校验固定
prefix 与 63 位范围,成功后 DB high-water 置为第二序号。这里更新此前
"恰为 DB 下一对"的合同:要求单调不复用,不要求无空洞。拒绝仍不收取
配额、不推进 DB;原 owner 不回退、不重用旧 tracker。新测试使用原
删除/退额释放其他占用后,验证同 owner 可再次预留。

另一项修正贯穿原 absolute deadline 至 native 注册及 high-water 读取
mutex,锁前和取得后复验;超时不登记半对、不消费 native high-water。
这些修正的专项与 pair 合同回归已发起,源码 Ruff/mypy 已通过。
未知 reserve 核对仍待实现:仅保存"事务曾 INSERT"的内存 marker 不足,
因为 rollback 后别的 owner 可能成功使用相同候选;不能据此认领后来的行。

跳号/同 owner 恢复/锁期限/pair 合同组合返回 **46 passed in 2.40s**,两项
P2 静态复审关闭。下一增量采用经生命周期设计复核的来源表:Registry
**format 13** 增加 `storage_creation_origins`,allocation ID 为主键并以
`ON DELETE CASCADE` 引用收费行,origin 为原 attempt 在首次 reserve 前
生成并保管的 32 hex 随机 ID。两个来源 INSERT 与两个收费 INSERT 和
high-water 更新处于同一原事务,经过原物理峰值准入;来源行上限 4096,
禁止孤儿及非 temporary 来源,没有永久 tombstone。不自动迁移旧格式。

`reconcile_temporary_creation` 持原 attempt 锁,在同一只读事务核对两条
完整 unbound 收费与原 origin;事务完整退出、deadline 复验后才更新本地
状态。原提交成功但失回执可恢复 reserved;回滚后其他 origin 用相同候选
则冲突并保留 unknown;两 ID 都缺失只置 unreserved,不允许再次 reserve,
不生成 native 完成资格。半对、已绑定或错来源仍拒绝。来源记录不是重启
恢复权限,调用方必须继续保管原 attempt,不能从历史行重建它。

该 format13 增量与新测试(含第二来源 INSERT 失败整体回滚、删除级联)
已发起验证及局部复审,尚不能计入此前 46 项通过证据;实际 capture
仍待接入,不能把账户状态核对当作 native 文件生命周期已结算。

format13 局部静态复审通过,无新增 P1/P2。Registry/配额/来源组合返回
64 passed、3 failed(并有三项派生 teardown error),失败均为新增事务内
OSError 注入测试误期待原异常,实际按既有 native 边界转换成
`managed_storage_unavailable`;已只修正这三处异常类型断言,定向重跑
来源模块。尚未取得重跑结果,不把此次失败集合计为通过。

为实际 capture 补入 `PrivateManagedDirectory.read_data`:调用前验证
封存长度不超过 max_bytes/capacity,再持原 fd 以不超过 16 KiB 的 native
读取块读取全文,前后核对原完整 snapshot。原 close 失回执仍沿用既有
句柄债务,不重新打开路径或收取替代文件。相关空文件/多块/超限预拒绝/
读取中改写和路径替换测试已发起;native worker 的取消保管与源的并发
准入仍由下一步实际 capture lease 实现,不能由该同步方法替代。

有界读取/创建组合已返回 **16 passed in 0.66s**。新增私有同步组合
`_capture_native.NativeOutputCapture`,借用原目录和 budget,不拥有共享
根目录的关闭权:原 pair 预留后逐流创建/绑定,追加使用原 snapshot;容量
溢出置双流 sticky loss,封存不再交付残缺源。close 将未创建流 fence 并
精确退额,已创建流保管原 removal/release 完成删除后退额,重复 close
不选择新路径。bind 回执未知时依据原创建身份重复核对绑定;写入效果
未知仍保留未结清状态,不凭较旧 snapshot 删除退款。

该同步 owner 必须由后续 lease 的单个原生 worker 串行调用;本身不承担
async waiter 取消、任务工厂故障及并发读写准入。其端到端存储测试与局部
评审已发起,Ruff/mypy 通过,尚未接 Product。先前来源断言修正的测试
审批超时,已按工具允许一次重试,与该同步 owner 专项一同收取结果。

该重试返回 9 passed、1 failed(及一项派生 teardown error):来源模块
七项通过,同步 owner 的两项普通流程通过;bind 故障注入同样应期待既有
边界转换后的 unavailable,已修正测试预期。同步 owner 局部复审新增
两项 P2 已修:helper 在首次 native 登记前通过 retain 回调把原 attempt
交给 capture;登记后核验和 fence 双重失败不再误报 clean。原登记返回
丢失时,只在原 owner 的有界在途列表按原 binding 找回 pair,不读历史
记录、不重建 tracker。另保存完整退出删除锁后的 deleted 阶段,之后
仅退款回执未知的重试不再打开 native lock。对应双重失败、禁止再次
native lock 的回归已发起,尚待结果及局部复核。异步 lease 未实现。

同步 owner 修复专项 **5 passed in 1.22s**,两项 P2 静态复核关闭。
下一增量 `managed.output_capture.ManagedOutputCapture` 实现异步 lease:
原 loop 内部 Task 保管每个 offload,公共等待使用 shield;有界八项登记,
原 async lock 串行 native 操作。close 同步关闭新读写准入,等待已接纳
任务后才执行 native close;内部任务被取消不是 native 完成证明,保留
unknown,不重新调度原操作。逐源只允许一个在途读取,prepare/seal 保管
原任务供重复等待,成功关闭后释放读结果任务引用。明确容量拒绝仍允许
命令预览,不再追加保留输出,seal 返回 None。

异步双流完整交付及 prepare/read 公共等待取消后的原任务保管测试已发起,
局部复审待结果;源码 Ruff/mypy 通过。该增量尚缺 factory/实际 Product
接线、进一步并发及退出故障验证,不表示 Linux 整体验收通过。

异步首轮局部评审未通过:P1 为 to_thread awaiter 不能单独证明 native
完成,P2 为 prepare/seal 等待后可能迟到交付。源码已改为复用现有
`connection._settled_native` 的 executor publication gate 与独立 callable
receipt,串行锁取得后再查 unknown;prepare/seal 在 await 后、返回或
发布 source 前再查 closing。该修复尚待提交后丢回执、内部任务取消及
迟到 waiter 的确定性回归和复审,不得当作 P1 已验收关闭。

上述异步故障专项已返回 **7 passed in 2.44s**,生命周期静态复核确认
本次 P1/P2 修复关闭。下一增量 `ManagedOutputCaptureFactory` 借用同一
instance 的打开目录与 budget,无 IO 分配原 lease,最多保管八个槽位;
未启动 lease 也必须明确 close 后才可回收槽位。factory.close 先 fence
全部 lease,再逐个等待清理;不关闭借用根目录,不丢弃失败 lease。
其无 IO 分配/槽位复用专项已发起,源码 Ruff/mypy 通过。真实 Product
仍未接线,安装环境和 SSH 整体验收仍未进行。

factory 无 IO 分配与槽位复用专项 **1 passed in 1.21s**。当前继续打通
显式 Product 接线:`create_coding_managed_attempt` → 共享 hosted 构造 →
`CodingRealHostedSessionFactoryV1` → `create_agent_session` → `AgentSession`
→ Harness AgentProduct,以可选 `ExecCaptureFactory` 参数传递。Coding
构造只引用 Harness 中立 port,不引用 AppHost 的实际存储实现;旧入口
缺省 None 保持兼容。新增真实 Coding owned Session + 本机 Python 命令
验证,要求 stdout 进入原 Session blob、临时文件与配额清理后 blob 仍可
读取。该测试及原 writer shutdown 回归已发起,结果尚待返回。

当前这是显式注入接线,尚未在 managed child 默认 composition 创建并
持有 factory;共享目录/registry 的关闭须晚于所有 Session 及 capture
结算,下一步完成该顶层生命周期后才能称为 lmux 实际激活。

真实 Coding Session + 本机命令以及原 writer 关闭回归 **2 passed in
6.70s**。当前新增默认顶层接线:managed process 在 bind 前向 bootstrap
请求原 capture factory;bootstrap 保管已准入实例 scratch 目录,Coding
managed command 注入该 factory,应用及 Session 关闭后再关闭 factory。
command.cleanup_pending 包含 factory,bootstrap 仅在 child 与 factory
均结算后关闭 scratch;scratch 关闭失败保留 journal、registry 和 observer。
尚未进入任何 loop 的未用 factory 有显式 close_unstarted 零 IO 清理,
已入 loop 者必须等待原 async close 的 settled 回执。

bootstrap/managed process 真入口/managed local 组合已发起验证,顶层
接线三视角局部复审已发起;源码 Ruff/mypy 通过。此处已改默认构造代码,
但测试与复审结果未收齐,尚不能宣称默认激活验收通过。

顶层组合返回 **62 passed、1 failed in 85.34s**;失败为旧测试要求 close
与父类函数 identity 相同,新增 factory 清理使该约束不再适用。保留
prepare/activate/start 原继承约束,将 close 改为实际行为回归:先完成
父应用关闭,factory 首次清理失败保留 cleanup_pending,重试同 owner
结算;另补 factory 已构造、bind 前失败的无 loop 早退清理。定向运行待
结果,生命周期静态复核未发现新增关闭顺序或循环依赖阻断。

行为/架构复审发现并修正非 UTF-8 P2:sink 以 `surrogateescape` 对称
编码后端增量解码的文本,保留原字节而不抛 UnicodeEncodeError 中止命令。
实际 Coding 命令测试增加双流二进制、容量拒绝和运行中溢出,检查命令
执行到末尾 marker、指定 exitcode、有限预览及降级无双流残缺 refs,正常
保留的 blob 在临时清理后按原 bytes 回读。这组测试已发起,尚待结果。

真实 Coding 命令四场景返回 **4 passed in 8.24s**,已向行为评审提交
两项 P2 的闭环复核。两个 capture 模块已加入 hosted-product 与 hosting
精确模块清单,inventory 更新为 schema13 及已接线的命令输出生命周期,
明确一般 trace 和其他 tmp 消费者仍待治理;文档轻量检查通过,两项
精确架构验证已发起。关闭顺序三项定向测试审批超时,按工具允许重试
一次,尚未拿到结果,不计为已验证。

行为复核已确认非 UTF-8 与真实降级两项 P2 关闭。关闭顺序三项定向
验证的允许重试也发生审批超时,尚未实际执行,不能继续重复提交同一
请求或记录为通过。精确架构验证仍在等待原工具句柄。已重新运行
`make plan-checks`,更新 `.artifacts/check-plan.json`;由于本分支包含
共享构建/依赖及跨模块改动,最终门禁范围仍广,不能以采集专项替代。
原文件 owner 基线 45 passed(2.83 秒),文档轻量检查与 diff-check 通过。

精确 hosted-product inventory 与 hosting optional-module 验证随后返回
**2 passed in 16.00s**;仅证明模块清单一致,不替代其余架构门禁。

### 默认写入路径复核

受管 Hosted catalog 构造 `persist=True` 的 Session;Coding bootstrap
的三处 `_ExplicitTemporaryDirectory` 分支均要求非持久化 Session,
不是该默认路径上的暂存消费者。命令输出注入 capture factory 后绕过
`SessionOutputPersistingExecService._execute` 的旧 `TemporaryDirectory`。
真实命令四场景新增 consumer 级禁止旧临时目录分配的断言,尤其约束容量
拒绝和溢出不得回退到无配额 spool;验证结果仍须单独收集。

新增禁止回退断言后的真实命令四场景返回 **4 passed in 8.17s**。
这证明上述持久化构造与命令执行路径未分配旧暂存目录,不覆盖任意第三方
插件自行写入文件的行为,也不替代真实安装与 SSH 断连验收。

默认 managed process 未接入 CLI 的 startup/session observability context;
Foundation router 默认 debug/trace sink 为 None。现有生命周期日志已单独
接入,但不能把"默认未启用 trace"计作显式 trace 能力交付。现有通用
TraceJSONLSink 的单文件轮转也不提供 lmux 命名空间共享额度与期限;后续
显式 trace 应通过受管 consumer 接入,而非仅设置日志路径或环境变量。

### 显式 trace 接线候选(设计复审中,未实现)

- 配置是部署诊断请求,不进入 Session storage 或 Product identity。
  必须给出有限持续时间;复用已有服务不得静默声称新请求已生效。
  启用入口及冻结/复用语义由本次三视角设计复审确定。
- Foundation 同步 sink 仅投递有限大小、白名单字段的结构化记录;不允许
  原始异常、提示词、回复、工具正文、环境或认证字段进入队列。队列按条数
  和字节双限,丢弃仅累加有界计数,禁止递归写诊断。
- 一个 AppHost 原 owner 持有队列、到期 fence、native worker 及 borrowed
  directory/budget;event loop 不执行同步文件 IO。到期/关闭禁止新投递,
  已接纳工作必须按原 worker 结算后才能释放目录与 registry。
- trace 使用既有两个 10 MiB trace 槽,与普通日志共用 namespace 200 MiB
  额度,重启不清零;未知写入不重放。只读读取和失败降级不得取得写权限。
- 不能直接把 trace 文件塞进当前 lifecycle logs 目录:现有 writer 严格
  拒绝其六个已知名称之外的条目。需评审共享目录协议或独立受管子目录,
  保留未知条目拒绝、原目录身份与并发写入互斥,不能放宽为接受任意文件。

验收至少包括到期与关闭竞态、队列满、满盘、跨实例共享额度、写入回执丢失、
关闭重试、字段脱敏、与 lifecycle logs 共存,以及旧启动消息/入口兼容。

三视角局部设计复审已返回,按意见冻结以下实现约束(非整目标验收):

1. 首个入口为 `lmux server start --trace-for <seconds>`,范围 1-3600,
   不增加环境变量默认值。只适用于本请求实际启动的新实例;既有实例复用
   明确报告 `trace_not_applied_existing_instance`,不重启、不静默忽略。
   服务成功与 trace 应用结果独立投影;请求未满足返回非零并说明服务状态。
   无 trace 请求保留旧 invocation 字节,带请求使用版本化启动消息。
2. 原启动请求冻结有限截止时间与可信实例关联,锁等待、重查、连接重试均
   不续期。到期关闭队列准入,也禁止开始新的 native 写入;尚未写入的队列
   内容丢弃并计数。已开始的 native IO 不抢占,必须收齐原回执。这消解了
   "到期后继续排空"与"到期停止写入"的歧义:入队不是持久化承诺。
3. 同步入口只读取封闭字段,不调用 record.to_dict/asdict,不遍历任意嵌套
   data/details。单帧、条数、总字节以及唤醒通知均有上限;跨线程最多保留
   一个待处理通知。复用原诊断执行通道,lifecycle/control 优先,trace 不
   新建 executor 或平行应用 owner。
4. 保留同一个原日志目录 owner,将已知名称精确扩展为原六项加
   `trace.lock`、`trace-0.jsonl`、`trace-1.jsonl`;两种格式仅操作自身固定
   槽,各自核验账本与 inode。仍拒绝任何其他名称,不接受 trace* 通配符。
5. Foundation 通过公开 runtime context 的显式 sink 注入接缝组合,不让
   AppHost 依赖私有 router;不复用会同步写完整正文的 TraceJSONLSink。
   原 child 管理在途诊断工作,bootstrap 保管借用目录和 registry。
6. 关闭先 fence sink,应用停止先行,再结算有限诊断工作和真实 native
   回执,随后关闭目录及账本依赖。普通 trace 失败不得阻断应用 stop;
   未知 IO/close 仍保留原债务,不能把"允许停止"表述为保证安全 clean exit。

实现前尚需把上述期限/结果投影接入现有 coordinator 的原启动回执,不能
仅回显 CLI 参数作为已启用证据。运行中动态启用不在该首个入口内,后续
若提供需走版本化管理协议,不能借启动参数假装控制既有实例。

首个公共接缝已实现:Foundation `observability_runtime_context` 增加
keyword-only `trace_sink=None`,与 trace_path 在配置变更前互斥;注入时
不构造文件 sink,正常/异常退出恢复旧配置,不关闭借用 sink。明确这是
进程级绑定,不能在并发 Session 内用作隔离。源码 Ruff/mypy 通过,架构
局部复核无新增 P1/P2;包含旧 debug 路径和三项新增行为的定向测试仍待
原执行句柄结果。该接缝尚未安装到 managed process,不表示 trace 已启用。

公共接缝定向验证已返回 **4 passed in 0.30s**。新增 `managed/trace_buffer.py`
作为原诊断 owner 的借用 sink:仅固定 turn aggregate 数值和封闭错误码投影,
单帧 512 bytes、最多 128 条/64 KiB;原 owner 轮询取单帧,不由生产者调度
回调。生产者非阻塞锁争用直接丢弃,丢弃计数明确为下界;到期不再交付队列
内容,fence 后已准入帧仅可在期限内取出。该缓冲还未接 native writer/CLI,
不得宣称服务 trace 已生效。源码 Ruff/mypy 检查及局部生命周期复核/测试
进行中;精确模块 inventory 已纳入该模块,仍待新增后的门禁结果。

缓冲局部生命周期静态复核无 P1/P2。已继续落实共存布局:paths 提供九个
固定名称,lifecycle writer 的有界目录扫描改用该精确集合,不开放通配符,
不读取/修改 trace 格式内容。新增所有九项共存读写及 trace 额外名称拒绝
回归,原 event-log 测试组合与缓冲测试均仍等待各自执行结果;没有据此
宣称 native trace writer 已实现。更新了人工 inventory 的 uncomposed 状态。

缓冲运行验证返回 **10 passed in 0.40s**。新增同步 `managed/trace_log.py`:
借用原 directory 与 budget,两个固定 10 MiB trace 槽,同 inode 轮转,
重新校验封闭 payload schema、序号及原绑定;写入前复核期限,已准入失败
封闭当前 writer,不重放、不退款、不接管 unbound 残留。Ruff/mypy 通过;
轮转/共存/期限/配额拒绝/失回执测试与局部生命周期复核已发起,待结果。
原 lifecycle-log 共存组合审批超时,已按提示重试一次。native writer 已有
实现但尚未接原 child 诊断工作与 CLI,不算显式 trace 激活交付。

写入器局部评审 P2(原 mutex 无界等待)已改为按剩余期限 acquire,取得后
复验、finally 释放;准入前超时不封闭无债务 writer。真实持锁线程负测与
其余写入器回归返回 **5 passed in 3.04s**,静态复核关闭该 P2。
lifecycle-log 共存组合的允许重试再次审批超时,未实际执行,不继续重复提交。

原 child 新增可选成对 trace_buffer/trace_write 接线,复用原诊断 task、
publication gate、Future 与独立诊断执行槽;原循环轮询,不新增 executor
或应用 owner。每条记录后重新考虑 lifecycle 优先级,trace 失败单独停用,
close 先 fence 生产者,应用停止先行,随后结算已有 native 及有限尾部。
trace-only 配置也显式安排最后一次排空。源码静态检查通过;新增 trace
线程/失败/阻塞关闭场景与旧 child logging 组合、局部复核待结果。bootstrap
生产 composition 和 CLI 仍未安装该可选接线,显式 trace 激活尚未交付。

child 接线原组合返回 **14 passed in 6.41s**,不包含随后新增三个关闭边界
用例。局部评审新增 P2:最终排空任务尚未放行 native 的发布失败不应污染
正常 close;已改为停用 trace、丢弃队列尾部并继续结算既有 Future/实际回执,
不吞掉在途 native 债务。before/after-schedule task factory 与最后一次
poll 后入队立即 close 的三项补充验证单独发起,待结果。

bootstrap 现有 `prepare_trace` 可选接缝冻结原期限,bind 借出 buffer 与
写入回调;同一个原日志目录通过共享 once-only admission 供两种格式使用,
任一格式 open 失败后另一格式不得重新 open。每次 trace 写入仍核验原实例、
attempt 与 native identity,再释放 journal fence 后进日志 IO。bootstrap
close 仍晚于 child 结算,丢弃尚在队列的内容,保留目录失败债务。Ruff/mypy
通过;先 trace/先 lifecycle 共存、期限不可续期、open 失败不跨格式重试三项
bootstrap 回归已发起。生产 CLI/invocation 尚未接入,不宣称显式启用完成。

bootstrap 复核 P2(由目录存在误推 lifecycle 启用)已修复:独立保留显式
diagnostics bool,bind 仅据此安装 lifecycle callback。包含真实 trace-only
child、无 lifecycle 文件及仅 trace 收费的组合返回 **4 passed in 1.92s**,
静态复核关闭该 P2。最终 drain 三项补充回归首次审批超时,已按提示重试
一次,尚无结果。

启动消息新增闭合 v3 `traceDeadlineMs`(同机单调时钟的绝对毫秒期限),
可与显式 temporaryRoot 同时使用;未请求 trace 时仍编码原 v1/v2 字节。
严格拒绝 bool/float/空值/缺字段及旧版本夹带 trace 字段;只传冻结期限,
不在反序列化时重新计算时长。当前仅完成值协议与静态检查,兼容性回归
进行中;starter/coordinator、生产 process 和 CLI 尚未安装该选项。

消息兼容性与 trace-only 组合返回 **51 passed in 3.45s**。starter/coordinator
新增可选冻结 trace_deadline_ms,原启动请求仅透传,不在等待或重查时续期;
专用 managed process 在 bind 前准备尚未过期的 buffer,再以公共 runtime
context 安装借用 sink,run_process 结算后恢复配置。无请求路径不安装 sink;
到达时已过期则不启用,不因此重启或延长。当前没有 CLI 生效回执,不能
把服务 ready 或回显请求当作 trace 已开启。

启动参数与原真实 starter 的期限传递回归已发起,静态检查通过。最终 drain
三个补充用例的允许重试再次审批超时,未实际运行,不继续重复提交同一请求。
CLI 与实际启用/拒绝状态投影仍待实现,整体 goal 未完成。

启动链路组合返回 **18 passed in 7.00s**。回执落点经局部架构复核选定为
原 ManagedServiceJournal/instances 的可选版本化 trace_application fact,
不新增 AppServer RPC、独立状态文件或 Hosting 应用协议。事实需绑定精确
instance/attempt、原始 traceDeadlineMs 和固定配置版本,并由原 native
identity 与 stop fence 核验后同事务发布;同值幂等,不同值冲突,旧状态
更新及 predecessor 编码不得丢弃该字段。此 schema 扩展尚未实现。

发布晚于真实 sink 安装、child 消费/结算路径绑定,以及 trace 双槽账务和
文件实际准入;发布前再次验期限。父端只读匹配回执后报告"曾成功应用",
不承诺持续写入成功;到期单独标记,别的 attempt 复用报告本次未应用,
自己的启动缺回执报告 not_confirmed,而非推断确定未生效。

为此新增 writer.prepare 真实准入两个收费槽,不生成虚假 trace 事件;
旧 write 与 prepare 共用原 slot 创建逻辑。首次 bind 前失败/提交后丢回执
补充回归,以及双槽准入后的完整 writer 回归均已发起,待结果。该 prepare
不单独构成 applied 回执,尚未连接发布切点。

包含双槽准入、首次 bind 两种失败及轮转的 writer 组合返回 **8 passed in
2.43s**。原实例新增 trace_application 可选事实,Registry 升为 schema14,
与当前状态/只读发现/predecessor 共用严格 codec。首次发布核对 instance、
attempt、native、stop/abort 与期限,同值幂等、异值冲突;生命周期 replace
保留事实,新实例不继承旧事实。首次写入使用普通 admit_growth,不消耗
停止/清理专用 control headroom。文档标明旧 schema13 仍拒绝、不自动迁移。
状态/发现/Registry 与新增事实回归组合已发起,局部架构复核待结果;原
bootstrap 发布切点和 CLI 读取反馈尚未安装,不据值/存储接缝声称 trace
已获得实际 applied 确证。

状态/Registry/发现组合返回 **95 passed in 9.87s**。局部架构复核 P2:
首次发布只在 update 回调内验 trace 期限,后续容量准入/SQL/COMMIT 可能
越过期限。已改为先只读识别历史同值,首次写事务整体使用 caller/trace
较早截止时间,并在原写 fence 内重新核对实例。历史同值允许到期后重查,
不存在事实时过期不能首次提交。新增容量检查后到期、SQL 保存后到期的
回滚负测及过期同值重查,定向组合待结果;不使用提交后报错冒充未持久化。

回执期限定向组合返回 **13 passed in 1.33s**。现已接实际发布切点:专用
process 在公共 observability context 内向原 bootstrap 确认同一 buffer 已
安装;此确认不生成回执。原 child 在 committed 后通过同一诊断执行槽先
执行 trace initializer,再消费帧;initializer 核验原身份/stop、真实准入
两个 trace 槽,退出目录锁后经原 journal 发布事实。失败只停 trace,原
native 债务仍由共享目录/child 结算保管,不占应用控制工作槽。

安装确认缺失/存在的真实 bootstrap 测试分别要求无事实/无槽与精确事实/
双槽收费,联合 child/专用进程回归已发起;Ruff/mypy 通过,局部生命周期
复核待结果。父端只读分类和 CLI 尚未接入,不把内部发布代码当整目标完成。

后续 bootstrap/child/专用进程组合返回 **27 passed in 7.19s**,覆盖实际
sink 安装确认、双槽准入发布和最终排空故障用例。现父端已接原 journal
只读观察,CLI 新增 `server start --trace-for 1..3600`;原命令准备时冻结
期限,不续期、不重启复用实例。JSON 独立报告服务就绪与 trace 状态,
显式 trace 未应用/未确认/过期均返回非零。中英文使用说明已补充。
新增真实 CLI 首启应用、再次请求复用和非法期限回归,执行尚待返回;
新接线 Ruff 与 diff-check 通过,用户语义局部复核进行中。不据此声明
完整 trace 交付或整目标验收完成。

真实 CLI 首轮返回 **12 passed / 1 failed(45.36s)**:首次请求能得到
service_ready,但 trace 在原 30 秒启动预算内仅为 not_confirmed。这是
未解决的真实进程集成失败,不能用底层通过覆盖。已补 diagnostics=True
与 trace 同时运行的 bootstrap 场景;与更新后的 CLI 回归组合待返回。

体验复核另报 P2:ready 后观察异常会丢失尚未输出的启动事实。现保留
精确服务/实例 JSON,以 observation_failed 和独立闭集 errorCode 返回1;
非领域异常只输出 unavailable,不泄漏正文、不重启/停止服务。新增过期、
未确认和观察抛错的六参数真实服务测试;文档注明 deadlineMs 为本机单调
时钟。Ruff/diff-check 通过,执行与局部复核尚待返回。

下一轮组合返回 **24 passed / 1 failed(86.77s)**,包括六种观察结果与
diagnostics+trace 组合,但真实 CLI 首启仍未确认。失败现场只有
lifecycle.lock;只读查询确认 storage_allocations 为空、trace_application
为空,定位到诊断早期准入路径,而非双槽创建后的发布阶段。

发现生命周期日志在原 child/父端并发观察 Registry 时仍 fail-fast,一次
busy 会封闭共享诊断消费。现 bootstrap 为单条日志冻结2秒预算,writer
在同一原期限内等待 mutex、文件锁及 lookup/reserve/bind;trace 同样为
lookup/reserve/bind 与最后 journal 发布使用原期限等待。无事务重放、
无期限续期,未知副作用仍封闭保债。新增两格式全链路期限传递回归;
局部生命周期复核确认无新增 P1/P2,Ruff/diff-check 通过。组合验证已
发起但尚待返回,不提前声称真实首启故障已解决。

修复后组合返回 **75 passed / 4 failed(111.50s)**。真实 CLI 首次应用、
复用不续期、六种观察结果以及 trace/budget/journal 组合通过,首次请求
不再耗尽预算返回 not_confirmed。六个相关源码文件 mypy 通过。
四项失败均是尚未运行过的外来文件夹具直接调用 append_data:该受管接口
要求持有锁,且不允许拿 data API 创建 trace.lock。现改为测试自行构造
权限0600的外来文件,以验证生命周期消费者拒绝/忽略对应名称;没有修改
生产校验。生命周期专项重新验证中,并纳入新加的 mutex 期限负测。
这仍不是完整 lmux 真实安装/SSH/性能验收或整目标完成。

生命周期专项返回 **33 passed in 5.05s**,覆盖修正后的外来文件夹具和
mutex 截止负测;原四项夹具失败已关闭。下一项恢复多服务选择工作:新增
真实双服务、一干净停止、异目录无目标 attach 的验收用例,要求不进入
选择器、不重新启动任一服务。当前实现多登记项总走选择器,验证待返回;
不能把这项新增测试当作功能已经实现。公共只读探测的所有权/同 loop
连接保管方案正在局部架构复核,仍需真实认证和 Mux 存在性验证。

新增双服务验收返回 **1 failed(46.14s)**,失败发生在 stop 步骤,尚未
到达自动选择断言;不能宣称已得到该选择行为的完整红灯证据。已补原
command.failure 诊断,保留该验收,不通过跳过 stop 掩盖集成问题。

另修复探测前的连接假阴性:允许唯一一次合法 trace 发布跨过认证,其余
完整状态不变且 revision 恰增加一;原停止/身份/存活检查保持。连接组合
**26 passed in 4.78s**,局部架构复核通过。多候选公共探测方案见
[接线计划](lmux-live-probe-plan.md),三视角复核反馈修正中,尚未实现。

停止失败的进一步源码对照发现测试缺少父进程回收:该测试本身持有原
Popen,子进程退出后若不 wait,进程组消失判定仍为否。现沿用既有
test_stop_and_explicit_restart_restore_mux_without_recreating_it 的模式,
原父进程并发 wait 自己启动的目标,stop CLI 保持原进程组/清理判定。
未改生产 stopper,也未把 pidfd exited 冒充进程组结算。新用例复验待返回。

复验 **1 failed(21.58s)** 已走过真实正常停止,失败确实位于唯一在线
Mux 仍进入选择器的断言。现新增公共 mux_probe operation 首版:完整快照、
按服务认证复用、精确 read_mux、unknown 保守分类、最终集合复核、原任务
取消保管及先清理再返回值。尚未接 CLI,不能据此声明红灯关闭。新增五项
定向测试等待执行,局部生命周期复核中;初版 mypy 通过,后续值验证仍需
复查。新模块架构 inventory 和最终完整验收尚未更新/完成。

公共 probe 初始五项 **5 passed in 1.68s**,主要使用替身认证,不能替代
真实验证;局部生命周期静态复核未发现明确 P1/P2。已接 CLI 多候选路径,
专属 Runner 关闭全部探测资源后只带值返回;最终重新认证并比较冻结 Mux
ID。选择器翻页遍历冻结结果,f 显式刷新;pending 取消不新建 main。
新旧两个源码 mypy 通过,真实双服务回归与冻结选择器专项待返回。后续
仍需期限耗尽/发布故障/候选变化等回归及完整门禁,不能宣称选择功能已验收。

真实双服务验收 **1 passed in 16.87s**:正常停止并由原测试父进程回收
一个服务后,异目录无目标 attach 自动进入唯一在线 Mux,不打开选择器、
不重启服务。冻结选择器专项审批发生终止性超时,按规则仅重试一次,尚
待结果;新增候选增删、首服务耗尽期限、关闭超时保管专项也在验证中。
两处精确架构模块 inventory 已显式加入 mux_probe,文本 inventory 补公共
探测并修正 trace 已接线状态;门禁仍待执行。实现的架构/体验局部复审
已发起,不用单个真实场景替代整体验收。

公共 probe 扩展组合 **8 passed in 2.87s**,覆盖候选变化、首服务预算耗尽
后不准入第二服务、关闭等待超时保管原任务/依赖。该运行早于随后交付
期限 P2 的修复,不用它证明最新改动。架构复核发现结果交付/rejoin 时
需复验期限:现过期值仅展示,candidates_unchanged=False 禁止自动选择;
closing 后不交付。体验 P2 的末页 n 误报也已修复并补回归,两项静态
复核均关闭。新增负测与两处精确架构 inventory 检查已发起。

冻结分页/刷新/pending 专项原审批及唯一一次重试均终止性超时,未执行,
仍是缺失证据,不继续重复同一请求;新增末页用例作为新改动单独验证。

最新负测及两项精确模块架构检查 **6 passed in 29.11s**,覆盖结果到期
交付/rejoin、closing 后不交付、末页 n 及新增模块 inventory。已刷新
make plan-checks:整变更仍要求较广门禁,不能用这六项替代。

进入真实安装准备:专用 .artifacts/lmux-installed.6hVazq/venv 已创建,
不修改原开发 venv/用户工具安装。离线 wheel 构建缺 setuptools;两个缓存
的锁定依赖安装分别缺 joserfc/mypy,尚未构建/安装成功。已申请下载声明
依赖;构建审批首轮终止性超时后仅重试一次,依赖同步另待执行。空间检查
为根分区约3.1GiB、/tmp约207MiB,安装产物留在工作区而非扩大tmpfs占用。

旧插件聚合架构门禁静态诊断确认 extra58/missing0/changed0,相关四源码
根均无本轮改动。评审定位其聚合inventory停留PLC8而源码已有后续PLC9B
边界;正在逐组件归属核对,尚未修改该门禁的准入名单或排除目录。

### 已实现:同 owner 的不覆盖隔离

`PrivateManagedDirectory.isolate_data` 在原稳定锁下验证完整 snapshot,
通过 Linux renameat2/RENAME_NOREPLACE 隔离到 removed- 名称;无原子
不覆盖能力时拒绝,不降级成存在性检查加 rename。目标已有文件不覆盖。
rename 后始终用原 fd 核验目标身份、大小、mtime 与尾部内容;目录同步
后再比较 rename 后的精确 snapshot,包括 ctime,避免交付过期结果。

调用方在进入前保管原/隔离名称。未知 rename、同步或关闭会封闭该 owner
的 data 写入;原 close 只结算原同步和 fd,不重放 rename、不删除源路径
上的 replacement。此接口只隔离,不删除、不生成退款凭据,完整 removal
tracker 与 capture 仍待实现。

首轮隔离及原文件回归 53 passed(4.78 秒)。三视角复审发现并修复同步后
缺少目标复核的 P2;补 fsync 期间目标替换/改写、rename 前源替换负测。
最终隔离专项 11 passed(0.78 秒),Ruff、源码 mypy、文档轻量检查和
diff-check 通过。目录隔离成功仍不是删除完成或可退额证明。

补强验证:真实 close 原验证 fd 后,立即打开另一个测试文件复用其数字,
再抛失回执。两次 owner.close 均保留 unknown,不再次关闭该 fd;替代文件
仍可写、隔离原件保持完整。测试自行关闭替代 fd,不修改原 owner 的未知
债务。生命周期局部复审通过,隔离集合 12 passed(0.71 秒),Ruff 通过。
这只验证隔离的关闭故障边界,不把 unknown 转为清理完成或退款资格。

### 验收续接:安装工件与 PLC9B 聚合清单

隔离 wheel 已构建完成,路径为
`.artifacts/lmux-installed.6hVazq/dist/loushang-0.1.0-py3-none-any.whl`,
SHA256 为 `da82058508cfa922a3e938a3c993953c9b0cf939ddc285eb868ad24c0043f9f2`。
现有 G17 wheel/source verifier 已验证包模块集合和文件字节一致;包含
`lmux` 及旧入口。此证据不是安装运行通过:隔离依赖同步的首次审批已
终止性超时,目前只提交一次重试,未替换用户工具或开发环境。

架构评审逐组件核对后,将 PLC9B 遗漏的 58 个 function/operation 项
(48 个函数、64 次调用)加入静态期望清单,说明见
[边界清单归属](../harness/plugin/plugin-boundary-sinks-plc9b.md)。不从扫描
结果生成期望,不排除源码目录,保留精确计数和 synthetic 绕过负测。
修改后的 Ruff 检查通过;专项 pytest 已提交执行,尚无通过结果。

后续安装结果:一次重试后锁定的 40 项依赖同步成功,wheel 已离线安装到
上述独立 venv。复用 G17 verifier 验证安装来源、SHA256、所有安装包文件
与 wheel 字节一致;补验 lmux/mux_probe 导入均来自独立 venv。从 `/tmp`
调用安装后的 `lmux --help` 返回成功。未改动用户工具安装。冷/暖服务及
跨 cwd 重连专项已在该安装环境提交执行,禁止 `src` 进入 pytest pythonpath;
结果未回收前不声称运行验收通过。

mux_probe/lmux_command 两源码 mypy 通过;文档轻量检查 6 项通过。
新增 journal 关闭失败回归:连接已结算时仍保管原 journal,再次 run 只
重接原失败 task,不重新认证、不交付结果;显式 close 结算后才解除清理
责任。Ruff 通过,更新后的探测故障矩阵执行结果待回收。

探测故障矩阵已完成:`test_managed_mux_probe.py` 共 11 passed(3.10 秒),
包含新增 journal-close 故障、取消重接、超时清理和过期结果禁止自动选择。
聚合架构专项首次和唯一一次重试均在审批阶段终止性超时,未运行,不能
记作通过。安装启动/复用/跨 cwd 专项仍待结果。

另提交已安装包的 canonical-parent-exit / canonical-parent-crash 两项:
通过真实子进程、精确 pidfd SIGHUP、合成模型闸门验证已接纳任务持续运行
及同 Session 重连。测试 helper 是测试组合入口,不是远端 SSH 客户端;
不会将其结果称为跨机器 SSH 实测,亦不代替完整 PTY 交互验收。

### 交互复核:剩余 M3/M4 必须分开举证

原交互评审员只读复核确认:短命令 CLI 场景替换了
`run_hosted_mux_shell`;现有真实终端场景仍是旧 `loushang-mux`
serve/create/attach。因此,安装 CLI 回归不能替代短命令真实 PTY 验收。
下一项须复用 `terminal_process_support`,覆盖 `lmux new -s dev`、两个
Tab、切换草稿、detach 后跨 cwd 重连,以及正常/EOF/取消的终端恢复。
Markdown/resize 还需真实终端证据,不能只凭替身 client 投影用例通过。

M3 仍需按绑定代际投影 available/read-only/unavailable 与原因;切 Tab
和重连不能沿用旧能力或审批资格。当前 Hosted 的固定命令补全、图片禁用
和 unsupported 分支不等于该矩阵已交付。工具富卡片、diff、用量、Product
命令及图片流程也不能由共享文字 renderer 推断等价;须按原设计逐项实现
或核实原有明确延期边界,不因当前测试容易通过而自行缩小目标。

PLC9B 清单局部复审通过,无 P1/P2;不是整目标评审通过。

已安装 wheel 的 canonical-parent-exit / canonical-parent-crash 实测通过:
2 passed(32.37 秒)。两场景都在合成模型已进入时发送精确 SIGHUP,
启动器退出后重新连接同一运行中 Session,放行后只生成一次预期回复。
这证明上述 Linux 子进程/连接场景,不证明真实 SSH 登录策略或完整 PTY。

新增 `tests/coding/test_lmux_terminal_process.py`,复用现有 native PTY driver,
直接调用安装后的短 lmux 入口,覆盖两 Tab/各自草稿、resize、detach 与
跨 cwd 重连。清理仅对测试私有 namespace 发 graceful stop,不按裸 PID
杀后台服务。Ruff 通过,已提交安装环境执行;尚未取得结果,也尚未覆盖
真实 Markdown 回复与 EOF/取消终端恢复。

边界复核:草案 §6.2 已明确将工具富卡片/diff/图片/全部 Coding 命令等价
排除于本轮;"完整视图"指共享实现,不是协议能力等价。本轮继续完成
既定能力投影及代际失效,不新增工具/图片远程协议。安装 CLI 非 PTY
专项第二次审批仍超时,未执行,不再重复同一请求。

PTY 首轮实际执行 1 failed(70.02 秒):第二成员已成功创建,footer 为
`*1 2`,用例却假设自动选择 `*2`;清理 stop 成功后的多行 JSON 又被单值
decoder 错读。已修正为显式切换第二 Tab、按 JSON 行读取 batch stop。
没有为满足测试改变产品选择语义。

局部复审指出两处假阳性,已补强:草稿断言复用 G18 ANSI→FakeScreen
回放,只检查完整同步帧的当前 viewport、精确 composer 行且排除另一份
草稿;resize 等待其后的完成重绘。重连前后比较 `status --server` 的非空
instanceId,而非由不含实例字段的 ls 推断无重启。修订后专项已提交,
结果待回收;原失败不计通过。

修订后的真实安装 PTY 专项通过:1 passed(53.76 秒)。短入口直接启动,
两成员真实创建;当前 viewport 的两份完整草稿隔离、resize 后重绘、detach
与另一 cwd 重连通过;前后精确 service 的非空 instanceId 一致,测试私有
namespace graceful batch stop 成功。此结果不覆盖 Markdown 回复或异常
终端恢复,也不充当统计性能数据。

共享能力投影实施方案见 [能力投影计划](lmux-capability-projection-plan.md)。
已提交三视角设计评审,架构视角通过,其余待回收;文档轻量检查 6 项通过。
实施时保留旧绑定未提供矩阵与明确 unavailable 的差别,不以展示矩阵替换
原有 controller/scope/approval receipt 授权检查。

能力设计三视角已完成,修复 approve/deny/details 资格差异,以及同一绑定
内资格改变不能接受旧投影的问题。选择同步重算,不新增异步 owner/cache。
首批中性不可变能力值已加入既有 input_policy,封闭 operation/status/reason
集合并检查完整矩阵、重复项及绑定不匹配;值测试已提交。尚未接入 Hosted
与 Embedded 呈现消费者,不能视为该能力功能完成。

此前安装 wheel 仍是记录的冻结 SHA256;本次源码新增能力值后,它不再代表
当前全部源码。正在回收的终端恢复两参数用例只验证该冻结安装,最终源码
需重新构建并核验。终端恢复新增断言比较打开 PTY 前保存的完整 termios,
以及最后 cursor/paste 模式关闭;空 Ctrl+D 是逻辑退出键,不称作物理 EOF。

冻结安装的终端恢复两参数测试通过:2 passed(127.14 秒),含完整 termios
恢复与最后 cursor/paste 模式断言。能力值验证 4 passed(0.87 秒)。

当前源码已将同步能力投影接入 Hosted shell、共享 screen state 的可选字段
和帮助页;资格变化独立于 transcript 缓存刷新,批准/拒绝/详情分别表达。
新增同绑定内 closing/snapshot/membership/content 变化的实际帮助渲染回归,
以及跨 Tab 快照失效验证,已提交执行。命令补全及 Embedded richer adapter
尚未接线;默认 None 保持原输入能力路径,不能将这一增量标为全矩阵交付。

后续源码将 Hosted 补全接入同一当前矩阵:输入分发和渲染前同步检查,
矩阵改变时替换补全 provider 并取消旧候选;切 editor 强制绑定当前 provider。
详情/拒绝不依赖批准回执,批准仅在当前准确详情展示后进入建议。手工命令
仍经过原 target/receipt/server 校验。补确定性 complete() 与帮助渲染断言。
前版四源 mypy 通过;本版 Ruff/diff-check 通过,运行结果仍待回收,已请求
局部生命周期/交互代码复审。Embedded richer adapter 仍是下一项。

前版 Hosted 能力/原 shell 集合 13 passed(1.63 秒)。局部复审另发现
A→B→A 会复活已关闭详情的旧批准回执,不能以该集合通过宣告安全闭环。
修复:显式 rebind/refresh 与已接纳 membership 撤销回执;普通 Esc 仅关闭
详情。资格观察即使详情已关闭也会撤销不匹配回执,poll 后同步观察失效。
新增真实 Ctrl+B 往返、直接 /approve 不发送以及 snapshot True→False
不恢复资格断言。修复后能力/请求安全集合已提交执行,结果待回收。

审批修复后能力/请求集合通过:20 passed(1.39 秒),包含真实快捷键
A→B→A、snapshot 恢复不复活资格及原请求投递隔离回归。

Embedded 中性 prepared-screen 接缝增加可选 capability_provider;共享
screen 在 render 时同步读取精确不可变值,不从 Product 反射推断能力。
provider 与当前投影只借用到本次 interaction 结束,正常/失败退出均恢复
原值;缺省 None 不改变原输入能力。正常/异常退出及原 host 集合已提交
验证,尚无结果。实际 Coding/Agent composition 的事实供应仍需接线,
不能仅凭新增可选接缝宣告完整 Embedded 适配完成。

Prepared host/screen app 两源 mypy 通过。AgentScreenConversationApplicationBinding
增加 keyword-only 可选 capability_provider,原样传入 prepared run,不在
prepare 阶段读取动态资格,既有位置参数不变;新增透传断言,Ruff 通过。
实际 Coding 供应矩阵前,正在复核既有 typed operations/审批 surface 的
资格事实来源,不以对象存在性推断可批准或开放原本未声明的能力。

Embedded 接缝及原 prepared host 回归 10 passed(2.30 秒)。实际 Coding
组合现在提供声明投影:输入组及 steer/follow-up 元数据、中断所需 lifecycle
和 queue、标准 clipboard profile 与原 Coding 命令 dispatch。读取元数据
不调用 operations resolver;绑定 Session 改变时使用新的局部投影代次。
原本地审批 port 没有资格快照,显式 not_projected,不虚构无 pending 或
不支持,也不以该值禁用原审批 surface。自定义 clipboard profile 同样不
猜测支持。新增声明负测与 Agent 透传验证已提交,运行结果待回收。

Coding 声明投影/Agent 透传两项通过:2 passed(4.21 秒);Coding/Agent
三源 mypy 通过。生命周期及交互局部代码复审均通过,原审批 ABA P2 已
闭环。按建议扩展 provider 恢复测试,包含已有非空 provider、正常/异常/
取消退出,修订集合待执行。当前 Embedded 是声明接线与旧行为兼容,不
据此声称新增完整能力帮助界面。最新 plan-checks 仍要求广门禁与原生/
安装平台门禁,不能用这些局部结果替代全目标验收。

能力投影增量的架构局部复审也通过;三视角局部均无未关闭 P1/P2,不是
完整 goal 复审。生成依赖图 --check 成功,与当前源码一致。

当前 wheel 构建目录为 `.artifacts/lmux-current.g5DrJs/dist`;离线构建缺
setuptools,已提交声明构建依赖下载/构建,尚未成功产出。旧 wheel 保留。
扩展 provider 恢复测试首次审批超时,已仅重试一次,结果待回收。

新增真实 Product/IPC/终端 Markdown 回归,复用既有 synthetic model helper
与 G18 屏幕回放,检查当前 viewport 无原始强调/代码围栏标记且包含完整
回复、idle footer,再 detach/重连验证持久 snapshot 渲染。不使用外部模型,
不等同 managed 短命令启动证明;后者已有单独 PTY 场景。新用例 Ruff 通过,
待更新安装包验证。

更新 wheel 已构建并核验源码集合/字节,SHA256
`e53fb545f3ed09562b8db0f13529647b934c86ef3463bc04d0fde07b1ec08e63`。
已安装到原任务专用 venv(未改用户工具),G17 安装来源/digest/全部文件
字节核验通过。新包的 Markdown 与短 lmux PTY/终端恢复集合已提交执行。
旧 wheel 文件仍保留用于证据对照,原 venv 当前已更新,不能再称为旧包。
扩展 provider 取消恢复集合两次审批均超时未执行;不记为通过、不继续重复
同一请求。Coding/G12 规模门禁亦待执行结果。

Coding/G12 规模检查结果 1 failed、2 passed(0.48 秒):G12 与精确文件
分区通过,Coding core 为34242,高于旧34181。与旧已验证 wheel 逐文件
比较,能力组合仅 mode.py +17、screen_input.py +50,共67行。架构复审
确认均为 Product 组合责任;单列17+50专项预算,两文件仍计core,原扫描
与其他阈值不变,新上限34248保留6行余量。修订预算测试已提交验证;
不是按超额61行倒推扩容,也不将原失败记成通过。

修订 Coding 预算复验结果为 1 failed、1 passed(0.42 秒):core 检查已
通过,继续暴露 lmux 专项实计1750、预算1592的差异。尚未复核该158行
差额的责任归属,不直接扩大预算,也不宣告规模门禁通过。
当前 wheel 的 Markdown/短命令 PTY 集合首次及唯一重试均因执行审批
超时未运行,不能记为产品测试失败或通过,不再重复提交同一执行请求。
用户再次确认完整验收后提交、push、PR、merge并同步本地;发布顺序授权
不替代尚未完成的安装验收、首次使用性能验证与全目标三视角复审。

继续复核规模差额:架构 reviewer 确认 process +23、local +20、bootstrap
+3、parser +4、command +108 均为 capture/trace/probe 的 Product/CLI 组合,
但 command 仍保留无生产调用的旧 `_select`。已删除该29行,旧分页/非法
输入/取消测试迁移到实际 `_select_probe`,单候选测试也改为拦截实际选择器。
专项记录经评审净增129行(1592+129=1721),不排除文件或额外增加余量。
Ruff 与 diff-check 通过;规模/选择器/命令回归已提交,尚未回收执行结果。
因产品源码删除了旧函数,e53fb545 wheel 现在仅代表该删除前基线,后续
最终安装证据须重新构建并核验,不宣称它与当前源码逐字节相同。

新增 `lmux-performance-acceptance-plan.md`,完成三视角初审并修订:status
只证明登记事实,活体复用另走原公共认证只读查询;成员 ready 须本次操作
成功及精确身份当前帧;三事实 clean stop 与采集 owner 结算缺一不可。
正式 managed 指标闭集/比较器分支、长历史种子、可信受管测试 Product
仍是采集前门禁。未将"有效配对"或旧七项 comparison 冒充 V10 已通过。

性能首个 managed-mux 九指标候选经架构与交互复核可实施;生命周期指出
stop终点须由外层采集 owner 物理结算后补记,已修订,等待原 reviewer
确认。补全限定面板候选行而非常驻 footer;累计冷启为连续墙钟不扣中间
开销。文档轻量检查6项通过。完整首次模型/工具和长历史仍为独立缺口。

生命周期 reviewer 已确认 stop 外层结算及累计墙钟修订,首个managed-mux
采集设计三视角局部通过。开始实现纯比较接缝:独立九指标清单与
compare_managed,原七项 compare_native 保持原清单,复用同一统计实现。
新增25项独立清单、逐指标回退、失败/缺失/债务拒绝测试;Ruff通过,测试
待执行。交互局部代码审查通过,不代表真实采集或性能验收。

规模/选择器/命令集合结果78 passed、1 failed(202.31秒);规模门禁通过。
唯一失败为旧pending测试将 `_execute` 模拟持续到后续bare调用,截断新增
真实probe及其清理回调。已把模拟限定于首次创建,补probe结果/无债/原生
关闭断言;单项复验待执行,不改变产品清理策略或将原失败记为通过。

比较器新旧集合115 passed(4.07秒),仅证明纯统计合同,不是实际性能
数字。pending名称单项首次审批超时,已提交唯一重试,结果待回收。
原 G18 probe 新增 managed_completion_frame,真实短命令PTY场景在空
composer输入/he,要求新完整当前帧有独立/help建议行,再以退格清空,
不提交该文本。新增旧帧、未完成帧、常驻footer、历史清屏误命中的拒绝
测试;Ruff通过,执行结果待回收。未将该接线宣称为已完成九指标采集。

为后续真实安装验证重建当前wheel:
`.artifacts/lmux-current.5V7UFs/dist/loushang-0.1.0-py3-none-any.whl`,SHA256
`58d140e2d17e6fa4d1d08c4dd93ef12176d49329187a0db257aee192ce741158`。
原G17源码模块/字节核验和隔离解释器/来源/digest/全部安装字节核验均通过;
任务专用venv更新至该wheel,用户安装未变。包含首次补全的新PTY集合与
Markdown安装验证已提交执行,结果尚未返回。pending单项复验首次及唯一
重试均审批超时未执行,不继续重复同一请求,也不记为通过。

补全当前帧见证拒绝测试2 passed(5.29秒),证明其拒绝旧帧/未完成帧/
footer误命中;实际终端首次补全能否呈现仍以安装PTY结果为准。

原采集器新增外层 complete_managed_stop 接缝:只在原owner.run_python
成功返回后补停止耗时,输入须为observed/valid=False,stop结果为与认证
instance匹配的stopped,起点处于原观察器寿命内。拒绝子端预填stop耗时;
取消/原owner失败不走补记分支。新增16项纯转换/原owner失败测试,Ruff
通过,执行结果待回收。该函数不替代来源/活体/成员校验;完整managed
probe与receipt validator尚未启用,原CASES默认集合不变,未开放正式采集。

当前58d140e2 wheel的真实PTY集合结果2 passed、1 failed(206.33秒)。
两项短命令流程通过,包含新首次补全面板、两Tab、草稿切换/resize、不同
cwd重连、同登记实例、detach/空CtrlD及完整termios恢复。Markdown失败
是测试错误要求围栏消失;实际输出已含样式标题、正文和高亮代码,而原
共享renderer._render_code_block明确保留styled围栏。已改为检查原始标题/
强调标记消除、标题bold/颜色及围栏/代码颜色,保留当前帧与idle要求。
仅测试修订,产品源码/wheel未变;单项安装复验待执行。原失败不记为通过。

外层停止计时接缝及原采集owner成功边界回归21 passed(0.58秒),包含
原owner失败/取消不补记终点。局部生命周期静态复审无新P1/P2;完整
managed回执校验与真实九指标采集仍未完成。

新增managed值回执校验:四次认证只读观察值固定为first-member、second-
member、detached、reattached,同instance/service/Mux,成员/Session唯一且
原成员前缀不变;前台spawn为精确new/attach argv与不同cwd。外层补stop后
才进入完整验证并保存这些观察值。局部复审发现时长可脱离实际查询时序,
已补五项managed_actions起终点与严格时长对应、冷启至最终stop连续顺序;
修复后生命周期复核通过。新增巨大attach时长、late首帧、缺动作、时长
不符、late detach等拒绝测试;Ruff/diff-check通过,集合执行待回收。
这里仍是trusted observer回执的结构/关系校验,不自行认证。真实managed
probe及显式case开关未接入,原默认CASES不变,不据合成回执宣称实测。
Markdown单项首次审批超时,已仅重试一次,结果待回收。

时序修订后的managed回执/外层结算/原owner集合47 passed(0.58秒)。
新增真实managed_read_observation:原namespace/journal只读准入、冻结
历史Mux ID、原connection lease精确实例认证后read_mux;不attach或夺
控制器,原lease/native全部结算后返回纯值。接入短命令PTY首/第二成员、
detach后、重连后四阶段,比较实例/service/Mux/成员前缀身份,Ruff通过;
生命周期局部复审与新增PTY运行尚待完成。未改变产品源码或当前wheel。
Markdown修订单项首次及唯一重试都审批超时未执行,不继续重复同一请求。

只读观察器新增7类故障回归:成功、prepare/read取消、connection.close
超时、journal/namespace关闭失败、Runner启动失败;拦截硬退出但保留原
Runner供测试finally收口,断言连接未结算时不关闭借用依赖。Ruff通过,
集合执行待回收。当前真实认证短PTY集合正在运行,不能提前记整组通过。
原probe新增managed_mux九指标真实body,复用现有PTY/当前帧/认证观察/
精确service停止,失败清理仅私有namespace且不补正常stop指标。产品源码
与wheel不变;body暂未加入dispatch/collector选项,局部复审与实测待完成。

当前wheel的四阶段真实认证短PTY集合2 passed(126.50秒),只读查询未
夺控制器,成员与实例在detach/跨cwd重连后相同。采集body局部复审指出
兜底失败覆盖主错、后续观察未即时核对first身份;已保留原异常并另记有界
cleanup类型,逐次核对first实例/service/Mux与second完整双成员,修复
后生命周期/交互复核通过。新增7项body失败/替换/第九指标边界负测,待
结果;read observer故障集合首次审批超时,已仅重试一次。
已接probe dispatch与collector显式 `--cases managed-mux`,禁止混入旧
场景/旧诊断模式,默认七项不变;固定槽20对时走独立managed比较器。
单安装共享observer的单样本链路smoke已提交,仅诊断接线,不是正式
配对/隔离observer性能证据;结果待回收。产品源码及58d140e2 wheel未变。

采集body的7项故障/身份替换/第九指标边界测试通过(6.97秒),仍不替代
真实链路smoke或正式配对采集。

新增9项collector选项/比较路由测试:旧默认不变、managed显式选择、混合
campaign在source/installation IO前拒绝、完整各走原策略、小样本/非固定
槽/子集不进入比较;回归集合待执行。统计结果增加描述性均值,使用原
精确Fraction样本计算,不参与或改变中位数/稳定性/退化判定。Ruff与
diff-check通过。观察器故障集合首次及唯一重试均审批超时未执行;smoke
首次审批超时,已仅重试一次,结果待回收。不能把未执行计作通过或产品失败。

选择/比较回归124 passed(5.21秒),含描述性均值。单安装smoke的唯一
重试同样审批超时未执行,不再重复同一请求。
新建任务专用`.artifacts/lmux-paired-envs.dakNYx/{observer,reference-b}`,
均为CPython3.11.15,离线按原uv.lock安装40项dev/runtime依赖和58d140e2
wheel;两者原G17来源/digest/全部安装字节核验通过。原用户环境未改变。
正式采集仍需原source_pair的clean Product与不可变Git来源校验;当前lane
dirty,不能用HEAD冒充来源。已请架构reviewer评估独立任务证据快照repo
冻结当前源码/辅助文件并运行原门禁的方案;尚未创建快照、未绕过该检查,
也未将这些环境准备当作正式性能结果。

证据快照现已冻结于 `.artifacts/lmux-source-snapshot.GdsdbX/repo`;独立
证据提交 `f25a4189f955694b692e7dda237747a106f56192`,不是任务分支交付
提交。原 lane 的 2778 个选定文件(35050213 bytes)复制前后路径、内容
SHA256、完整权限一致;副本一致,提交后的 Git archive 字节及执行权限
逐项一致。未改写原 lane HEAD,也未放松原 clean Product 校验。
从该冻结 repo 离线构建 wheel,原 `verify_wheel_at_commit` 与 clean
Product 检查通过;wheel SHA256 为
`ea66a3cb4228173383d7c31e12a2f7fb4404f570f55d628a539b3ae48ad7cba0`。
`origin-before.json` 和 `verified-source.json` 保留原来源、快照 tree、
辅助文件清单及 setuptools 84.0.0 构建标识。原锁导出的带哈希依赖清单
`requirements.txt` SHA256 为
`4ef76f53bd65b228247a08341571eb393937c0b5f1f109aed1cf1b16a17f34c0`。
快照仍 clean;后续采集必须运行快照内 collector,并重新安装/核验该
wheel,不能沿用旧 wheel 的安装通过记录。正式交付前必须核对最终源码
与测量来源差异;相关修改需要重验。尚无真实九指标或正式 A/A 结果。

冻结 wheel 已分别安装到任务专用 observer、reference-b 与原 reference-a
venv;三个环境均通过原 G17 隔离解释器的 origins/direct_url/digest/全部
安装包字节核验。它们当前指向上述 ea66a3cb wheel,不再是 58d140e2;
该安装验证不替代新 wheel 的运行场景结果,也未改变用户 tool 环境。

源码回归 `test_lmux_read_observer.py`、`test_lmux_selector.py` 与
`test_lmux_command.py` 合计 84 passed(230.72 秒),包含此前因审批超时
未执行的观察器故障覆盖与 pending-name 测试修订。未运行 live/host-runtime
测试;本集合不替代 installed Markdown、首次模型/工具或正式性能验收。

首次 Product 使用测试组合已补入性能计划,并经架构/生命周期/交互局部
复核修订:复用原 request_factory 与真实新准入,不预置 journal;保留
生产子端存储、capture、diagnostics 和原进程清理链。补充被测解释器/
固定 child 来源、取消不重发、真实工具效果、原任务清理及下一调用完成
见证;回复完成须有 turn 完成事实,审批拆待办提示/详情展示/批准后结果。
此复核只允许继续实现可信测试组合,未冻结正式字段或长历史规模,不是
完整 M4/goal 评审通过。

冻结 repo 的三安装 `managed-mux` 单块单对诊断已启动,报告位于
`.artifacts/lmux-source-snapshot.GdsdbX/diagnostic-aa/report.json`。
这是非固定槽小样本,比较必须保持 not-evaluated,尚未完成采集,不据此
宣称性能提升。新 wheel 的 installed Markdown 单项审批超时未执行,
未将超时算作产品失败;为减少采集噪声,待本次诊断结束后再唯一重试。

上述诊断已终止失败:首个 B 侧预热 `lmux new` 输出 lmux_unavailable,
退出1,无首帧指标;原 owner 同样返回失败,保留完整 report/scratch,
comparison 仍 not-evaluated。目录检查发现 workspace 虽为0700,sample
父目录及 workspace lane/.artifacts 为0775;原 managed `_validate_parent`
明确拒绝此祖先,不能通过放宽产品权限解决。collector 现先显式创建
managed sample root 为0700,避免 `mkdir(parents=True)` 仅对叶子应用
mode 的陷阱;新增 umask002 下原 owner 启动前检查两级0700的回归。
Ruff/diff-check通过,回归执行待结果。后续需使用安全磁盘临时父目录
(如原测试用 /var/tmp 下任务私有根),不能继续将运行状态放在该 lane
树下;安装包与报告仍可留在 workspace。新 helper 尚未重新冻结,旧
证据提交保留不改写;此失败不产生任何有效性能值。

目录修复经生命周期局部复核通过:仅新 sample 目录受0700保障,
exist_ok 不会修复已有目录,必须换安全的新 scratch,不能 chmod 旧树
或放松生产准入。修订后的 collector 和回归已追加冻结为证据提交
`0baba3bc7db39bdf8aaf918bf2aea6e72de16680`(非 lane 交付提交)。
旧失败对应 f25a418 提交保持可追溯。原 ea66a3cb wheel 在新提交的
`verify_wheel_at_commit` / clean Product 检查通过,完整 helper manifest
与当前 lane 一致;证据保存在 `verified-source-private-samples.json`。
产品未变,无需重建 wheel;不得将旧失败样本改记为成功。

目录修复及 managed 停止/回执回归 43 passed(0.63秒),包含 umask002
新增覆盖。安全 `/var/tmp` 任务根创建首次审批超时,已唯一重试,尚待
结果;没有开始第二次采集。首次 Product 子端组合经架构进一步复核,
选择固定测试进程内 partial 原构造名称并调用生产 main,保留原 launch/
capture 和异常清理;明确禁止直接导入含顶层 install() 的旧 hosted
fixture。该小节设计已同步,实际组合与端点回归仍待实现。

安全磁盘临时根 `/var/tmp/loushang-lmux-measure.aUibmj` 已由 mktemp 创建;
第二次单块单对诊断使用该根与0baba3bc冻结 helper,报告目标为
`diagnostic-private-aa/report.json`,已提交执行,尚无结果。未覆盖旧失败。
新增无导入副作用的 `_lmux_synthetic_product.py`:固定模型与真实
AuthorizedExecution工具定义,仅handler发工具效果见证,hold使用原流
producer/task及finally结算见证;见证不是授权或native清理权威。
三项局部回归验证请求不执行、模型回显不算效果、producer取消结算;
Ruff/diff-check通过,执行与局部复审待结果。尚未接专用child、有界独立
见证sink或真实审批链路。新fixture不在现有0baba3bc快照中,不参与本次
短入口诊断;首次Product采集前须另行冻结其完整来源。

fixture局部复审发现可插拔 task factory 在调度后抛错可使producer失去
收养句柄;已改为内置 asyncio.Task 显式保管再同步 attach_task,不经过
外部factory。hold测试扩为无factory/调度前抛错/调度后抛错三种条件,
断言factory不被调用,并保留测试故障兜底取消。共五项fixture用例,
Ruff通过,运行仍待结果;尚未宣称P2运行验证完成。

第二次诊断已终止失败:安全目录修复后首屏、补全、两Tab、detach和
跨cwd重连均经过真实PTY,四次认证的实例/Mux/成员一致,取得八项
局部时长;最终 stop 输出 preview 后 local_operation_failed,因此全部
样本仍无效,comparison not-evaluated。只读数据库显示
process_exited=1/application_cleanup_completed=1/process_scope_settled=0。
生命周期复核定位旧 `_guarded` 包装器为 subreaper,却只在 operation
结束后的 finally 才回收 adopted leader;operation 内 stop 正在等待其
进程组消失,形成循环。日志 stopped 只代表应用侧,不是完整三事实。
拟保留原包装器,在 stop 等待窗口用原精确pidfd回收已收养leader,
不 waitpid(-1)、不抢PTY/Popen状态、不写journal,不将强制回收算成功;
具体实现、非零退出/其他Popen隔离回归及重新冻结均尚待完成。

fixture新增 run_product:仅测试进程构造名称 partial 原类并调用原
production main,finally恢复;增加三项原launch/capture传参、失败和
中断恢复覆盖,当前共八项。首次审批超时未执行,已唯一重试;Ruff与
diff-check通过。此处mock main测试不证明真实服务构造失败清理。

新增测试侧 `_lmux_adopted_process.AdoptedLeader`:原 observer.reopen
绑定精确pidfd,收养前后检查存活和PPid;仅借用原锁/句柄执行
waitid(P_PIDFD,WEXITED|WNOHANG),只接受该leader正常0退出,缓存失败
不能重试成成功。不发信号、不写journal、不抢其他Popen状态。两项真实
子进程测试验证0/7退出和另一Popen的23退出码;Ruff/diff-check通过,
执行及局部复核待结果。尚未接stop等待窗口,也未重新冻结/采集。
原失败进程组4037344的沙箱外只读ps检查已完成,无匹配进程;这是失败
包装器结束后的现状,不补成先前正常stop成功证据。
synthetic Product八项回归唯一重试仍审批超时未执行,不继续重复相同请求。

AdoptedLeader局部复核指出关闭未知债务及测试清理跳过后续资源两项P2;
已保留close-unknown、拒绝重试假成功,构造失败清理保留primary;测试
finally独立尝试owner/两个Popen/stdin清理,新增相应负测。首次执行
结果4 skipped(0.65秒),不是通过:当前standalone CPython缺少
os.P_PIDFD(也缺少pidfd_open,后者原Hosting已有libc适配)。已核对本机
Linux UAPI头文件P_PIDFD=3;测试helper仍用原os.waitid精确pidfd等待,
仅为缺失的常量名称选Linux ABI值,不退化P_PID或扫描。移除Linux上
该名称缺失的skip,内核不支持须失败。新四项回归已提交,结果待回收;
stop接线和完整采集仍未完成。

精确回收四项回归4 passed(0.62秒),确认当前standalone Python可执行
Linux P_PIDFD等待。随后已接入probe:reattached认证后读取同实例native
identity,原connection/native清理完成才交付;持有AdoptedLeader,在
stop前台Popen的communicate轮询间履行精确wait职责,仍要求原stopper
返回精确stopped。关闭pidfd与前台管道失败均保留失败,不信号服务。
局部复核指出sys.exception可能误取外层旧异常、原生read不应阻塞事件
循环;已改本次显式primary,并通过原_settled_native/原deadline/
wait_for_lock=True读取和结算。新增外层except关闭故障、缺失/替换身份
及工作线程断言,静态检查通过,接线集合运行待结果。
精确回收测试另加stop前台等待原进程组消失的正常流程、管道关闭失败
负测;先前4 passed不覆盖这些后加断言。新helper仍未冻结,不重跑旧
快照来冒充本次修复验收。

上述接线集合17 passed(5.72秒),包括外层异常下的leader.close失败
传播及native身份缺失/替换/工作线程读取。前次两项P2经生命周期复核
确认关闭,无新局部阻断。完整当前helpers已追加冻结为证据提交
`7b5a5a44ee0c8985a97e5ddfc20c65a985456b0e`;与lane完整helper manifest
一致,原ea66a3cb wheel对该提交的来源/clean Product核验通过,记录于
`verified-source-adopted-wait.json`。这仍不是任务分支交付提交。
新增真实stop/group等待及外层异常下管道关闭回归已单独提交执行,尚待
结果;未开始第三次采集。既有安全scratch父目录仍为0700,后续采集器
在其下创建全新样本根,不复用失败样本的运行状态。

新增停止等待集合5 passed(0.80秒),覆盖原进程组消失等待与管道关闭
失败不被外层异常掩盖。第三次诊断已提交,使用7b5a5a44冻结版本,报告
目标 `diagnostic-adopted-aa/report.json`;结果待回收,仍为非固定槽小样本。
新 `_lmux_product_child.py` 提供固定测试request factory(只替换argv入口,
保留原invocation/session-root/descriptor/cwd/env/streams),子端核验被测
安装来源与预建私有观察目录,再调用固定run_product。复用原BoundaryTrace
类而不调用其install,避免修改生产类。五项child局部测试及八项synthetic
依赖测试已提交,尚待结果;Ruff/diff-check通过。未接真实首次Product
父端准入或正式指标;这些新文件不在本次短入口冻结快照中。

第三次诊断已完整成功退出0:`diagnostic-adopted-aa/report.json` 为
complete-record-only,2预热+1对诊断样本全为valid,九项指标齐全、精确
实例stop与原外层owner结算成功,helpers_before/after一致。非固定槽、
仅一对,comparison按原规则not-evaluated;耗时波动明显,不声明改善
百分比、稳定性或正式性能通过。前两次失败证据未删改。

首次Product父端按架构复核进一步收敛为 `_lmux_product_entry.py`:只接受
固定new -s perf,校验安装来源,暂换固定child request factory并调用
原lmux.main,finally恢复,不复制准入/认证/清理。新增五项参数/来源/
失败/中断恢复局部回归。此前child与synthetic集合审批超时未执行;结合
新父端的18项依赖集合已唯一重试,待结果。父端仍未在真实PTY验收,
新文件尚未冻结,不与上述短入口诊断结果混用。

固定Product父/子/模型组合18项回归通过(4.53秒)。首次回复终点经
交互局部复核:保留PTY的用户可见完成帧,显式detach后再由原控制器
attach/snapshot核验正式记录与非running,不为观察抢占活动终端。
当前协议snapshot_session需要attachment/generation,不能当匿名只读
观察口。计划已补nonce、错误/unknown拒绝、后验不倒填时间与不宣称
native结算的边界。synthetic fixture新增唯一回复和delayed完整文本但
无final的负例,静态检查通过,新增回归待执行;18项旧通过不覆盖本次
增补。真实首次Product PTY驱动、审批和长历史仍未完成。

唯一回复与delayed负例增补后的synthetic集合10 passed(4.30秒)。新增
当前完整帧判定:唯一回复、空输入、精确目标Tab和正常idle状态须同帧
出现;运行、审批、错误、未知、旧回复及composer回显不计完成。11项
帧回归已提交执行,结果待回收;Ruff与diff-check通过。这不替代真实
PTY或detach后的认证snapshot核验。完整验收后再按已授权顺序提交、
推送、PR、合并及同步本地分支,当前尚未发布。

新增测试侧 `_lmux_product_snapshot.confirm_reply`:调用方须先完成终端
detach并持有原认证connection;使用公共attach/snapshot核验精确Mux、
唯一member/Session、FirstUse标题、非running和恰好一条预期正式回复,
拒绝ERROR记录,finally释放此次attachment。借用connection的原owner
仍负责异常/超时后清理;不新增匿名snapshot接口,不回填PTY时间戳。
八项局部负测已提交执行(5615),生命周期局部复核已请求;Ruff与
diff-check通过。完成帧集合5606仍在等待审批,未重启。两组均不能
代替尚未接入的真实受管Product首次使用场景。

完成帧集合11 passed(7.06秒)。snapshot局部复核发现deadline P2:
asyncio.timeout(0)不能阻止无挂起点方法同步完成。已改有限期限校验、
操作工厂延迟构造、派发前及返回后复验绝对期限,增加过期/NaN/inf与
迟到snapshot负测。生命周期复核确认该P2关闭;外层失attach回执或
取消后的原connection关闭接线仍待实现和验收,不算关闭。5615仍待
审批,文件已增至12项,最终以实际collection结果为准。已安装Markdown
PTY在原ea66a3cb安装上提交唯一重试5620,尚无运行结果;不声明渲染
验收通过。静态Ruff与diff-check通过。

5615首次审批超时未执行,当前12项snapshot集合已唯一重试5622。
新增 `managed_reply_observation` 接入原采集器connection owner:原只读
入口委托同一私有body且不传verify,行为不变;新入口仅在终端已结算
后使用,精确比较既有instance/service/mux/member目标后调用公共
attach/snapshot确认。异常仍由原connection finally close及原process-only
runner/pending结算;没有第二套生命周期。read-observer新增正常核验、
失attach回执、snapshot取消三项路径,共12项提交5626待结果;局部复核
已请求。真实PTY调用端仍待接入,不能把mock故障覆盖当成端到端证明。
Ruff及diff-check通过;5620已安装Markdown与5622尚在审批等待。

5620已安装Markdown集合实际通过:1 passed(24.93秒),包括真实样式
渲染、detach后snapshot显示与原服务退出;使用ea66a3cb隔离安装,不是
新受管首次Product场景证明。5622唯一重试仍审批超时未执行,不重复
该12项请求。5626读观察接线集合仍待结果;局部生命周期评审确认
原connection/pending路径无新增阻断,模拟attach-lost不替代真实回执丢失。

新增 `_lmux_product_probe.first_reply`:固定安装入口启动真实PTY,唯一
nonce回复由完整当前帧计时,显式detach并离开原terminal owner上下文
后才进行公共记录核验;原身份/native owner精确stop后交付场景记录。
复用原观察器与精确回收helper,没有新增采集框架或生产配置开关。
当前仅静态Ruff通过,局部评审待结果;尚未接原guarded入口、冻结或
实际执行,也未加入正式性能比较。审批、延迟结束负例及长历史场景
仍未完成。后续必须保留来源校验及外层物理结算,不单独调用来冒充验收。

首次回复驱动局部生命周期复核无阻断;按建议新增snapshot失败、
leader.close失败、stop失回执及fallback失败测试(连同正常路径共5项)。
fallback失败类型写入有界字段,防止外层仅序列化主异常时遗漏note;
不写异常敏感详情。probe主入口增加诊断case managed-product-first-reply,
沿用原measured_entries和_guarded,不自行发布valid=True;正式协调器
尚不选择或比较此case,仍待严格receipt校验及冻结。5626首次审批超时
未执行,与新增驱动5项合并唯一重试5636(预计17项)待结果。Ruff通过。

本轮14个helper/test差异已冻结到独立证据仓库提交
`46bb4ab50e798633eaee5ad2b6cb833cca8f479a`。原require_clean_product与
verify_wheel_at_commit通过,仍匹配ea66a3cb wheel、1392个包文件,
完整helper manifest与当前lane一致;此提交不是lane交付提交。首次
回复诊断尚未运行,5636仍待结果。下一步使用该冻结入口和原外层
evidence owner,在安全私有runtime下运行;未增加正式有效性声明。

5636集合实际17 passed(5.18秒):原连接观察器12项、首次回复编排
5项,覆盖失attach回执/取消清理及失败不发布成功。冻结46bb4ab的
真实首次回复诊断已提交5646,复用原owner.run_python及probe _guarded,
新建安全runtime与独立报告目录,执行前重验wheel与helper清单,执行后
保留原始receipt和helper清单。当前等待审批/启动;即使正常退出仍仅
标记owner-settled-diagnostic、valid=False,不跳过后续严格验收。

继续轮询5646确认仍为同一活跃请求,未重复启动。等待期间已运行
make plan-checks,更新.artifacts/check-plan.json;当前跨包源码与
pyproject改动仍选择广泛门禁,部分新tests/dev路径为未分类,不擅自
缩减检查范围。make check-docs-light实际6项通过;这不是源码门禁或
首次回复验收。正式跨包门禁及完整三视角复审仍未完成。

当前全部312个变更/新增Python文件Ruff通过。5646已获准实际运行,
原进程session3459仍活跃,报告为
`.artifacts/lmux-source-snapshot.GdsdbX/diagnostic-first-reply-z6fhwaaf/report.json`,
runtime为`/var/tmp/loushang-lmux-measure.aUibmj/first-reply-vlur4rls`。
已观察到原native receipt的running状态及正确隔离安装来源;尚无终态,
不重启、不过早判定服务失败或完成。

3459实际失败退出1,helper前后相同。PTY尾部已出现本次唯一回复与
idle/*1,但状态为`submit: request_acknowledged; cwd / user_home; /help`,
原精确完成帧漏掉该正常文案导致40秒误超时。仅测试predicate新增这个
精确idle组合,并保持running/pending/unknown/failed拒绝;12项回归5668
待结果,不把原失败样本改判成功。
fallback普通stop随后超时;只读registry显示实例
f6a4e844b7a2ad6c1e1c5cc3246aa8b5三事实为1/1/0,native PID4054573,
当前ps无该PID或原终端4054552。与此前正常stop已修复的subreaper回收
等待环路一致,失败分支尚未接精确回收;需补齐后再冻结重跑。原报告、
清理失败字段和外层leftovers失败保留,不据当前进程消失声称原停止通过。

完成帧修复集合12 passed(4.88秒)。失败清理已按局部评审方向改为
首次认证read冻结native identity;终端上下文退出后,正常/失败路径
共用一次exact_stop/AdoptedLeader,stop_attempted在构造前置位,原owner
已消费或close-unknown时不重新reopen。认证前失败/收养前原leader已
退出交外层原owner结算,不放宽身份准入,不重新选实例。普通阻塞
subprocess stop fallback已移除;清理失败有界字段保留首因,正常路径
再次比对冻结身份。八项正常/故障回归5678及局部复核待结果;Ruff与
diff-check通过。新修复尚未冻结或再次真实运行,旧失败证据保留。

失败清理修复局部复审通过,无新增阻断。四个变更helper/test已冻结为
证据提交`2104c81ab2062473b34be9233df4893186d7acbc`,原wheel来源、
clean Product与完整helper一致性重新核验通过;仍使用ea66a3cb安装,
未更改生产包。修复版真实诊断5683已提交,使用新建私有样本/报告目录,
等待审批/启动;八项故障回归5678仍在等待,不重复请求。没有把上一轮
屏幕回复或当前冻结校验当成完整成功证据。

失败清理八项实际8 passed(5.45秒)。Hosting Makefile所列源码及适配层
类型检查通过(31 source files),使用--no-incremental和/dev/null缓存,
未扩大mypy缓存。5683审批超时未执行,冻结2104c81真实诊断唯一重试
5691已提交,尚待结果;仍不把测试耗时当性能指标。

按Makefile typecheck-apphost原源码范围执行静态类型检查,通过137个
source files;同样使用--no-incremental与/dev/null缓存。5691仍是同一
等待请求,尚无启动/终态结果;暂不叠加其他重型检查,保持诊断噪声较低。

5691已实际运行(session45209)并失败退出1,报告
`diagnostic-first-reply-cxmrcu8v`,runtime `first-reply-qyew5iq9`。
失败发生在初始perf界面前:前台退出1,输出operation_unavailable;
后台同实例c61da1350c6ac1647b69245a293fc218有starting/ready日志及
fixed_product_selected见证。尚未到首次认证读取,不能选择新实例做
fallback;原外层报告leftovers失败。helpers前后一致。不能把ready日志
当完整启动成功,也不能据此断言超时根因;下一步定位前台创建/连接
失败边界,前次回复完成帧与失败回收修复尚未获真实成功样本证明。

原失败registry只读检查:instance rev3/committed、stop_requested=0,
perf reservation及对应create permit已有,但created_instance_id与
mux_space_id均NULL。范围缩小到受管create RPC阶段,尚无完整创建事实。
AppServer _execute_managed将内部Exception统一映射OPERATION_UNAVAILABLE,
AppService的binding.prepare/check_creation也隐藏内部原因;现有记录
不能区分权限准备、acquire、校验或commit失败,不能直接断言期限原因。
已请求局部评审最小测试侧有界admission诊断代理,要求只委托原owner/
权限/时限,不新增重试、不输出authority或异常文本,诊断不纳入perf。
此观测尚未实现;不通过重新启动旧样本猜测根因。

局部评审认可固定child构造点的admission代理方向,强调预建代理再
取得原owner、每次close原样委托、日志失败不得破坏原生命周期。
新增测试侧 `_lmux_admission_diagnostic`:只替换binding.prepare,原
字段/closing不变;代理逐次委托prepare/acquire/check/close,记录固定
阶段及白名单错误类型/code,无消息/路径/authority。sink失败禁用后续
诊断而不替换原异常或丢失owner;缺失阶段不能当成功证据。12项日志
故障/原异常/取消回归5721待执行,Ruff通过。尚未接固定child或冻结,
不影响当前2104c81快照;诊断同步IO会扰动耗时,必须排除性能样本。

诊断已接固定测试入口:专用managed-product-admission-diagnostic case
向固定父/子脚本传固定标志,子脚本移除标志后仍交原三个production
arguments;原Product构造点仅替换launch.managed_mux.prepare,保留其余
事实及output capture。普通first-reply默认不启用代理,报告另标
admission-proxy-not-for-performance。父/子参数与恢复矩阵已扩充,连同
synthetic基础回归5727待执行;代理集合5721仍待结果。Ruff通过,尚未
冻结或实际运行诊断,新构造代理还需补集成断言与局部复核。

代理12项实际通过(0.55秒),包括sink写失败、取消、原异常与每次close
委托。新增构造集成三项:仅替换binding.prepare,保留launch其他事实和
capture identity,原异常/中断不被替换且恢复原构造入口。父子/模型组合
5727仍待结果,最终以实际collection为准;局部实现复核已请求。Ruff与
diff-check通过,尚未将本轮诊断接线冻结或运行到真实服务。

诊断接线局部复核通过;父子/模型组合实际31 passed(8.32秒),包括
新增三项构造保留/异常恢复。十个helper/test差异已冻结证据提交
`40c9dd36dfeddfec78fbe1cea58325abc176ab06`,原wheel来源/clean Product/
完整helper一致性校验通过。专用admission诊断5734已提交,独立新建
runtime与报告目录,仍用原owner.run_python/_guarded,固定标为
admission-proxy-not-for-performance。当前待审批/启动,不宣称原因已
定位;阶段缺失只能视作诊断不完整,不能据此判定commit失败。

5734实际运行(session99119)后失败,报告diagnostic-admission-0pf_p_pp,
runtime admission-diagnostic-0wj82gy8。本次prepare/acquire/check/close
阶段均有return,continuity中已存在perf及FirstUse成员;前次创建错误
未复现,不能据此判定已解决。本次已通过可见回复和终端退出,失败
发生在后验managed_reply_observation,原runner将内部异常折成
local_operation_failed,外层只收到一般RuntimeError。测试observer现
保留原operation_failure作显式cause,原清理与失败判定不变;尚未验证
该增补或重跑。不把fixed_product_returned=0或已有创建记录当样本成功。
生成包依赖文档的--check检查实际退出0。

后验核验发现测试混淆了两个标题合同:Mux 成员标题为 FirstUse,
Coding Product 未设置 session_name 时快照标题默认为 Coding。
现将 FirstUse 断言移至成员,快照仍严格验证完整 Session identity、
唯一正式 assistant 回复、无 ERROR、running=False;没有放宽完成判定。
新增错误成员标题负例,观察器测试也使用独立的 Coding 快照标题,
并验证 attach 响应丢失与 native identity 错误保留原始 cause。
局部 Ruff 通过;快照与观察器回归执行请求 5760 尚待结果。
尚未冻结这些 helper 或完成真实重跑,不能据此认定此前失败已解决。

UX 原评审视角完成本次标题修正的局部只读复核:协议与 Product 源码
确认两种标题独立,未发现新增 P1/P2;身份、正式回复及清理核验均
保留。评审未运行测试,不替代请求 5760 的实际结果或全目标复审。

5760 实际启动 session80342,终态退出0:25 passed in 5.76s。
四个 helper/test 差异冻结为独立证据提交
`82fd3b66e191b61dcae5974d528b50331c9db19f`,helper 全量一致,
原 ea66a3cb wheel 的源码/清洁 Product 校验通过;不是 lane 交付提交。
普通 managed-product-first-reply 真实诊断请求 5773 已提交,沿用
原 owner/_guarded 与新私有 runtime,不启用 admission 代理。
目前尚待结果,报告保持 valid=False,不当正式配对性能验收。

继续验收时复核 5773,工具仍报告 running,未重新启动诊断。
PLC9B 架构 inventory 定向检查另提交请求 5779,尚无执行结果。
这两项均不得计为通过;首次 Product 的延迟完成负例、真实审批/工具、
中断再调用、长历史,以及正式配对和全目标三视角复审仍未完成。

5773 实际运行 session6613 并退出0,报告
`diagnostic-first-reply-title-bxng36an/report.json`,runtime
`first-reply-title-prh7prwp`。原 owner 返回 owner-settled-diagnostic,
helper 前后一致;receipt 的正式回复后验确认成功,同实例
`0d7fa22cba3a43cdf0d6416b9a1333ea` 精确 stop 返回 stopped。
可见回复 1.3374 秒,固定测试父端 spawn 至可见回复累计 16.8381 秒。
该单次普通诊断未启用 admission 代理;保留 valid=False,既不是正式
配对比较,也不说明此前间歇性 create 错误已经根治。快照标题修正后
首次回复/后验/正常 stop/外层物理结算闭环已有实际成功证据。
5779 审批终止性超时,测试未运行,不能写作架构门禁通过。
成功样本 registry 经 mode=ro 只读核验:上述同一 instance 的
process_exited/application_cleanup_completed/process_scope_settled 均为1,
与原 stop receipt 及外层 owner 成功返回一致。

新增尚待验证的 managed-product-delayed-final 测试 case:沿用原固定
Product 的 delayed nonce(完整 delta 后不发送 done)、原 PTY/owner/
精确 stop。当前帧必须呈现本轮全文与 FirstUse running,采样时若
reply_completed 提前为真即失败。detach 后借原 public attach/snapshot
确认同身份仍 running、唯一 delayed nonce user 且没有正式 assistant;
随后 detach,stop 前后核对同实例同 call 的 producer_started/settled。
生成任务观察文件有大小/条数/顺序边界,不作为服务权限或停止凭据;
仍以原 stop 与外层物理结算决定通过。负例不发布首次回复性能指标。
当前 Ruff 通过,回归请求5799已提交,三视角局部复核已请求;尚未
冻结 helper、未实际运行负例,也未纳入正式比较或声明验收成功。

三视角局部静态复核中,生命周期视角发现验收 P2:首个正确 running
帧之后至终端退出之间可能出现迟到错误 completed 帧。已修复为 PTY
context 完全结算后扫描输入后的所有完整帧,任何 completed 都失败;
原始输出前缀不匹配则拒绝截断窗口。新增 running→completed→running
及截断负测,生命周期复核确认关闭;架构/UX 局部无其他 P1/P2。
增补 pending observer 返回 pendingConfirmed 而非 replyConfirmed 的回归。
最新 Ruff 通过,5799 仍待实际结果;不以替身测试或局部评审代替真实
安装负例与全目标复审。

5799 实际运行 session83648,退出0:73 passed in 8.26s,包含本轮
迟到完成帧与 pending observer 增补。八个 helper/test 差异冻结为
`6c00cfd79fe409f4d5069a97f31683603c7ef0b8`,与 lane 全量 helper
一致且原 wheel 来源校验通过。真实 delayed-final 请求5808已提交,
仅使用该冻结版本和新私有 runtime;尚待结果,不发布性能指标。
最新 make plan-checks 实际退出0,仍选择广泛门禁以及 Actions 的平台/
安装/真实 LSP 检查;本轮定向73项不能替代这些交付要求。

5808 复核仍为 running,保持冻结 helper 不变。并行执行 Makefile 原
typecheck-harnesstui 的完整源码范围(原 follow-imports=silent,额外
no-incremental 与 cache-dir=/dev/null,使用现有 uv 环境),session66622
尚待结果。该静态检查不是首次工具/中断的真实验收,也不影响正式性能
结论;本次 delayed-final 本身不采集性能指标。

Harnesstui 类型检查 session66622 终态退出0:160 source files 无问题。
5808 已启动真实诊断 session90548,当前仍运行,未重启该样本。

5808/session90548 最终退出1,报告 diagnostic-delayed-final-c7k0t1rz,
runtime delayed-final-fd7og57u。失败为 running frame predicate 超时:
原始终端尾帧已包含完整 nonce、Hosted FirstUse running、perf *1~,
状态为 submit: request_pending; cwd / user_home; /help。此状态未被
streaming 白名单接受;不是观察到了 completed,也未走到后验快照。
已仅为 streaming 见证增补该精确 running+pending 状态,completed 的
pending 拒绝保持不变;新增 idle pending/unknown/failed 拒绝测试。
Ruff 通过,5826定向回归待结果、UX局部复核已请求;未重新标记旧样本,
未冻结该修正或运行新负例,原外层 leftovers 失败仍保留。

UX局部复核确认 running+pending 增补未弱化完成判定。该两文件修正已
冻结独立证据提交 `6c22acac49b53b4bc1322796126869806c99f611`,冻结时
helper 与 lane 一致、原 wheel 来源校验通过。5826 回归仍待结果;新
独立安装诊断请求5830已提交,使用该精确冻结源码,不修改旧失败样本。
本次 coordinator 仅消费冻结 repo(其前后 helper 摘要仍核验),不从
后续可编辑的 lane 导入 Product/helper;证据冻结不是功能交付或验收。

5826 实际启动 session54216,终态退出0:20 passed in 8.86s。
5830 仍待执行结果,未重复启动。中断后再调用的后续核验需注意:
Agent 流式 message_start/update 只更新 streaming_message,message_end
才进入正式消息列表;被中断的运行可留下空的 aborted assistant,
因此不能直接复用"新 Session 恰一 assistant"的完成断言。

5830 审批终止性超时未执行,仅重试一次为5838,仍使用冻结6c22aca,
不改其 repo。并行在 lane 实现下一增量的快照合同:中断后新 nonce B
必须与 A 不同,完整记录顺序严格为 delayed A user、一个空 assistant、
reply B user、唯一 B assistant;仍核验完整身份、running=False 和 detach。
仅接受 Agent 当前固定 abort 路径的一个空记录,不把它自身当中断原因
证明;原 producer 结算与真实中断/下一轮完成接线仍待实施。新增九项
顺序/重复/空记录/身份/运行态负测,Ruff通过,5840回归待结果。

5838 实际运行 session86152,退出0。报告
`diagnostic-delayed-pending-y1zd5757/report.json`,runtime
`delayed-pending-vtzuvam4`,冻结6c22aca helper前后一致。完整流出文字
未触发 completed,detach 后同实例/会话仍 running 且没有正式回复,
同 producer 于 stop 后 settled;原 owner 成功返回。registry mode=ro
核验实例 `1d9cbec0bfc53f217df24e6ddc6ef156` 的 process_exited、
application_cleanup_completed、process_scope_settled 均为1。本项真实
负例已有成功证据,仍标 valid=False(不是正式配对性能采集)。

lane 已接显式 managed-product-interrupt-next-turn case:复用原 delayed
与精确 stop,elsewhere 重连后核对身份/native、单次 Ctrl+C,再确认
idle及原 producer settled,单次提交不同nonce B,完整回复后 detach
再核验精确四条记录。原终端/连接/stop owner不变,不发布fresh首次
回复指标;工具子进程/输出捕获的中断清理不在此模型负例的声明范围。
架构与UX局部通过;生命周期发现重连可能先取消任务的因果P2,已在
身份核验后、Ctrl+C紧前复核 producer 尚未settled,并要求既有trace
settled monotonic_ns不早于此次中断动作。补提前结算与时间边界负测,
局部复核待返回。5846接线组合仍待结果;5840审批超时未运行,仅重试
一次为5850。最新Ruff通过,尚未冻结或真实运行中断case。

5846 实际运行 session57577,终态退出0:74 passed in 7.68s,包含
中断因果补强后的接线、当前帧与原观察器回归。5850严格快照测试仍待
结果,生命周期P2最终复核亦待返回;不据此宣称真实中断已验收。

生命周期静态复核确认中断因果P2关闭。七个helper/test差异冻结为
`528734d70226caac404d21d4572a571f5450e47a`,冻结时lane/helper一致,
原wheel来源核验通过;真实中断诊断请求5858已提交,仍待结果。
5840及唯一重试5850均审批终止性超时,严格快照测试未执行;不再重复
同一请求,仍记作缺失证据。该冻结与诊断提交不等于快照回归通过。
Makefile原typecheck-harness完整范围使用现有uv、no-incremental、
cache-dir=/dev/null实际运行session33468并退出0:694 source files
无问题;原follow-imports=silent不变,不替代运行时验收或全量门禁。

5858 已启动真实中断诊断 session33880,目前仍运行,冻结528734d不变。
lane 并行准备首次工具验收:复用有界固定Product trace读取,新增工具
effect见证只接受真实handler写出的同实例 lmux-call-1,审批前计数0、
成功后恰1;回显、重复、错误call/instance与提前效果均拒绝。新增六项
负测,Ruff通过,5866回归待结果。尚未接真实审批界面或声明工具验收。

5858/session33880 最终退出1,报告 diagnostic-interrupt-next-turn-kzbxmolz,
runtime interrupt-next-turn-sxxayuz7。初始delayed/detach后验已完成,
重连当前帧有FirstUse running与perf *1~,notice为原shell.py明确提供的
"running; earlier partial output is not in the v1 snapshot"。测试白名单
遗漏该合法提示而超时,尚未发送Ctrl+C。仅target_state_visible的running
分支增补精确提示,仍拒绝错目标/idle、不当完成(负测包含完整nonce)。
UX局部复核通过,Ruff通过,5871回归待结果;旧失败与leftovers结论保留,
修正未冻结,真实中断尚未通过。

四个helper/test差异(重连提示及共用有界trace/tool效果检查)冻结为
`ee36b9494c24fa7f08564448e79230ca7b271677`,lane一致性与原wheel
来源校验通过。新真实中断诊断请求5875已提交,独立新目录、原owner,
尚待结果。5866实际运行session29382,退出0:44 passed in 8.02s,
覆盖工具效果见证和共享producer/清理编排;5871重连帧回归仍待结果。
本证据提交不是lane功能提交,工具真实审批与中断实际成功仍未证明。

5888/session3240 已退出0:141 passed in 6.65s,覆盖工具审批接线、
当前完整帧、严格快照及原只读观察器,含最新审批因果与详情目标负测。
审批紧前记录 monotonic_ns,完成及 exact stop 后均核验真实工具效果
恰好一次且不早于批准;详情帧必须同时呈现正确 Mux/活动 Tab footer。
生命周期、架构、UX 三个局部复核均确认对应 P2 关闭,Ruff通过;不等于
完整目标复审或真实工具调用已验收。审批到回复的时间包含工具后的模型
回复及显示,不解释为纯工具执行时间。

5871、5875 及真实中断诊断的唯一重试5889均审批终止性超时、未启动。
其中重连帧回归已由上述141项覆盖;真实中断成功仍缺证据,不重复提交
相同请求。七个工具审批helper/test冻结为
`4d858444c3e495a0435f3c640f71703cdf08f5ea`,冻结时helper一致、Product
和原wheel来源校验通过。新工具审批诊断5899已提交,使用固定本地模型、
独立私有目录和原owner,结果待确认;该证据提交仍不是lane功能提交。

5899 实际启动 session74027,最终退出1。报告
`diagnostic-tool-approval-3yg52yh2/report.json`,runtime
`tool-approval-_fpcw4w3`。已进入同目标审批界面,但当前状态行同时带
`submit: request_pending; Approval pending: F2 details; /approve /deny`,
footer为`perf | *1! | /help /detach`。采集器只允许无submit前缀,故
等待超时,尚未发送批准;原失败及leftovers分类保留,不计验收通过。
仅审批待处理帧增加精确submit pending/ack前缀,仍要求正确目标和审批
footer,未知/失败回执不接受,完成帧规则不变。新增四项组合负测,Ruff
通过,5923回归及UX局部复核待结果,尚未冻结新修复。

UX局部复核已通过该实际帧修正:审批待办与submit回执可并存,但不扩大
完成条件。5923回归仍待结果;修复后真实工具验收尚未运行。

5923/session88898 实际退出1:36 passed、1 failed。新增ack状态行超过
固定100列夹具,不能作为完整单行展示证据;修正为仅接纳实际观察到的
pending组合,无前缀正常审批帧继续支持,超宽ack负例保持拒绝。该修正
回归5940待结果;不以放宽到截断文本或子串匹配来掩盖失败。

拒绝工具快照新增独立入口,仅接受固定真实策略错误回显
`Tool lmux_evidence requires approval`,严格核对同会话、idle、原user、
空tool-call assistant及唯一最终回显;成功与拒绝回显不能互换,错误
期望在attach前拒绝。该消息来自原policy engine、原异常转tool result
和固定模型回显,不修改Product。新增十项快照分支/输入回归5928待结果,
Ruff通过;仅为后验记录校验,真实拒绝UI接线及停服后零效果检查仍待实现。

lane已接`managed-product-tool-denial`独立诊断:固定新Session、原ask
策略,等待同目标审批帧后单次`/deny`,不打开详情、不发送approve;仅在
拒绝回显且idle后detach,原后验快照/身份检查/exact stop完成后再核对
实际handler效果为0。拒绝回显不是零执行证明,仍依赖有界真实效果trace;
不发布成功工具耗时。新增拒绝帧及五项交互故障测试,并扩展八项原停服
失败编排;Ruff通过,生命周期局部评审与5946接线/快照/观察器回归待结果。
5928单独快照请求审批终止性超时、未运行;5946覆盖新增接线后的快照。
5940帧回归仍待结果。未冻结上述拒绝接线,未宣称真实拒绝验收通过。

5940/session40658已退出0:38 passed in 11.15s,含最新拒绝帧负测。
生命周期评审发现拒绝因果P2仍开放:若`/deny`丢失而pending因其他原因
结束,相同policy回显与零效果不足以证明本次拒绝生效。须补精确interaction
的原DENY接纳回执见证及丢弃deny负测,再冻结/真实运行拒绝case。原停服
与最终零效果顺序未发现新增阻断;5946回归仍待结果,不能代替此P2关闭。

拒绝因果修复已接固定父进程的显式`--interaction-diagnostic`:仅包装原
RemoteAppClientV1.respond_interaction,一次调用原方法,收到原AckV1才写
accepted,退出恢复原方法;独立私有有界trace,不改Product。原AppService
要求session port返回True才允许Ack,否则报operation_unavailable。停服后
要求sent/accepted精确两条、同attachment/generation/member/interaction、
DENY及不早于本次按键的时间下界,再核对零效果。没有回执或回显相同均不
足以通过。新增八项回执/丢失deny负测,Ruff通过,5956回归及生命周期复核
待结果。5946已审批终止性超时、未执行;严格拒绝快照运行证据仍缺失。
该观察为诊断开销,不用于宣称未经插桩的首次工具性能。

生命周期复核确认DENY因果P2关闭:原RPC仅一次、原服务实际接纳才有
Ack、精确请求配对及本次时间下界、stop后回执和零效果共同验证。5956
回归仍待结果。新增诊断入口成功/异常/中断恢复测试,5962待结果;5946
超时请求的唯一重试5958(接线/快照/只读观察器)亦待结果。上述等待均
不计通过。最新make plan-checks退出0,因跨包源代码、pyproject及未分类
测试仍选广泛门禁,Actions平台/安装/真实LSP检查也仍需执行;未缩减交付
范围,不因本地窄回归而宣称全门禁已完成。

5956/session96115退出0:81 passed in 8.54s,覆盖原DENY回执观察与工具
接线、失败清理。当前全部改动/新增Python文件Ruff通过,git diff --check
通过。5958唯一重试也审批终止性超时,严格拒绝快照仍未实测;5962入口
恢复测试与5967当前架构门禁仍待结果。

11个helper/test冻结为`3ee561e91717a3e4773a9ac6510236091a915be1`,
冻结时helper一致、Product及原wheel来源验证通过。冻结仅固定输入,不
代表所有回归通过。新真实审批诊断5971已提交,验证实际pending帧修正,
使用原批准case、不启用拒绝RPC观察器,新私有目录/原owner,结果待确认。
本次仍为证据快照提交而非lane功能交付。

5962入口恢复与5967架构门禁均审批终止性超时、未启动;各自唯一重试
为5974与5973。5971真实审批诊断原调用仍待返回,不重复启动。已启动
完整目标的架构、生命周期/安全、UX/覆盖三视角只读代码复审,覆盖当前
Product与设计边界,不限于最新采集helper。复审不能替代尚缺的真实
运行、长历史、正式性能及广泛门禁证据,当前仍不可交付。

完整三视角复审不通过,当前合并去重问题为:P1默认Embedded未启用同库
writer、P1公开delete仍绕过保留型维护owner、P1进程启动后的辅助task发布
失败可跳过清理;P2 owned import准入前staging、P2失败创建保名无精确继续
入口、P2审批晚失败污染其他Tab。均需修复,不以旧局部评审覆盖。

已为真实Embedded bootstrap补同库restore/rename/delete busy及释放后恢复
回归(5981待结果),并在Linux新建应用runtime组合点启用原owned factory、
注入原platform state/session-stores;非Linux与低层借用构造默认不变,
不增加unowned fallback。Ruff通过。此接线尚不能关闭公开delete/import
问题,也不能替代真实两进程默认入口验收。生命周期worker负责原exec后端
task发布P1及窄回归,与本入口修复文件分离。

5973架构及5974入口的唯一重试也审批终止性超时,均未执行。5971已实际
启动session42599,仍使用冻结3ee561e和原wheel;它只验证该冻结诊断,
不代表最新Embedded产品改动已经安装验收,最终须重建冻结并补验。

5971/session42599随后退出0,报告`diagnostic-tool-pending-4x93cm1n/report.json`,
helpers_unchanged=True、owner-settled-diagnostic。首次待审批1.1439s、详情
0.1513s、批准到工具后最终回复0.3480s;同instance/member/session后验确认,
真实handler lmux-call-1恰一次且不早于批准,exact stop返回stopped,原owner
结算。单次固定模型诊断仍valid=False,不代表正式性能配对或最新Product
通过,也不覆盖拒绝/工具子进程中断。

exec任务发布P1实施完成:仅captured路径全部进程辅助任务采用可信Task,
普通路径保留原task factory;原缺陷四项确定性失败,修复后94项相关回归、
23项原Local回归通过,Ruff/mypy通过,独立架构复核待返回。

5981默认Embedded回归审批超时未执行;新增平台选择/无目录创建检查,
5997实际bootstrap/owned集合待结果。公开delete入口新增窄
TranscriptDeletionOwner参数,复用原retained factory.delete_transcript;
Linux未传owner在任何路径访问前拒绝,Product默认delete前置同样处理,
不再先读缓存或按pathname回收附件。ApplicationSessionManager坚持原factory。
这是Linux底层公开API兼容收紧:调用方须持有并结算owned维护factory,
正常应用runtime沿既有override;非Linux暂保持旧行为。六项前置拒绝/原错误
保留测试6004待结果,旧公开API调用点和测试仍需迁移、实际busy验证仍需补齐。
owned import尚未修复,须沿原prepared restore candidate直接消费冻结源意图,
不能先staging再恢复。UX worker另负责审批晚失败代际门控。

5997/session17333退出1:16 passed、1 failed、80 deselected。新同库夹具
将platform state放入会话root.parent下,违反已有state/data互斥规则,实际
先报invalid而非busy;改夹具为data/sessions与platform/state兄弟域,未放宽
Product校验。6008复验真实默认入口及平台选择,尚待结果。

审批晚失败P2已修:原control owner内捕获回复,完整目标/interaction内容和
请求代际匹配才发布错误,Tab ABA/refresh撤销旧交付。78项相邻及32项补强
窄回归通过,Ruff/mypy/diff-check通过;独立复核仍需安排。
公开delete新增真实owned factory竞争、释放后删除及附件保留两项测试,
6004仍待结果;独立生命周期复核已请求。import由架构worker实施,保留主侧
delete更改。尚未迁移完旧无owner删除测试,不能宣称全门禁通过。

6004及6008审批超时未执行,唯一重试分别6016、6019待结果。公开删除
边界文档已写明Linux无owner即使missing也拒绝、调用方保管原factory清理
债务及附件保留语义;原SessionManager稳定锁删除测试开始显式owner迁移,
Ruff通过,尚未执行此迁移测试,其余旧调用迁移未完成。
审批代际修复通过独立生命周期复核。创建恢复P2按显式create-status与
create --continue原operation设计推进:只读查询不启动/重放,继续不更换
ID、不自动attach,历史unknown仍保守;UX worker负责实现和窄验证。

旧SessionManager删除相关测试进一步迁移:Linux显式持有并结算原owned
维护factory,保留锁/索引断言;附件删除预期调整为可恢复保留,重复authority
的删除应拒绝(该预期待实测核验),非Linux保留原语义。6026针对性回归
已提交,Ruff通过,不以跳过Linux测试替代迁移。6019唯一重试也审批超时、
未启动;Embedded同库修复仍缺新夹具的运行结果。6016删除集合原调用待返回。
owned import修复已请求独立生命周期复核,实现agent继续扩展原prepared/
外部恢复及冻结指纹、失败保管测试;尚不计完整import验收通过。

6016/session34059退出0:8 passed in 2.50s,公开删除的前置owner要求、
原错误保留、真实busy/释放后删除/附件保留已有运行证据。Harness目录与
生命周期旧删除调用也迁移到测试范围显式retained owner,6032回归待结果。
6026审批终止性超时未执行,Coding删除迁移仍缺运行结果。

UX测试确认并发pytest共享临时根可在执行中被其他运行清理;后续每次命令
使用独立mktemp --basetemp,不修改Product超时、不重启已有live handle。
6032使用独立根。owned import复核未发现新增生命周期阻断,但JSONL正文
81MiB与ZIP正文64MiB边界须明确,构造失败债务新测试尚有失败待实现agent
核对;创建恢复已开始独立生命周期复核,真实启动间歇失败仍保留为未闭环。

6026未运行请求的唯一重试6034使用独立basetemp提交;6032仍待结果。
默认bootstrap/SessionManager及共享delete相关五源mypy session70090仍运行,
不计通过。当前内存available约338MiB、swap使用约3474MiB、根分区余2.1GiB;
暂停增加大型并发测试,已有运行不重启,不以压力指标解释startup_failed。

导入兼容合集session96159已退出:107 passed/10 failed。两项新增夹具未
materialize源正文,实施agent已修夹具待复验;其余包括五项默认目录/index
行为、一个discovery源替换、两个import兼容/缺cwd案例。原失败保留:目录
索引由主侧跟进,导入agent处理源绑定与cwd准入前校验,不能只调整旧预期。
创建恢复独立生命周期静态复核未发现新P1/P2,建议追加确认后更晚ABA及
旧代permit无回执换代后继续拒绝两负测,UX已接手。

五源mypy session70090退出0。6032在pytest启动前因外加--basetemp被原
run_pytest包装器拒绝(exit4),不计测试失败或通过;包装器本身已有带租约
独立scratch,修正命令6042不再外加basetemp。直接pytest才需显式独立根。
6034审批超时未执行,6040仍待返回(也带错误basetemp,须等终态后修正)。

创建恢复新增28项分批通过、独立复核及两晚边界负测通过;兼容3例现场已
分开:两例child提交前startup_failed,一例COMMITTED后许可持久化前失败,
三者无mux_authorities,三事实0/1/0。既有stopped日志不足以证明结算,需
利用原异常/测试probe补诊断,不能统一归因内存或创建RPC。

owned import额外8项窄回归通过,缺cwd前置和源替换已覆盖。但prepared
abort保留可见已导入会话不满足旧取消语义,此项仍开放:拟在原writer
preparation/Graph disposer内对本次已确认create执行精确撤销,未知结果
保留双lease/附件债务,绝不pathname unlink或重开factory。原prepared
abort过早closed也须联修,取消只rejoin原task。设计已请求独立生命周期
评审,尚未实施该撤销,不把已有import测试当完整P2关闭。

续验:6040 handle 已不存在,不据此声称测试执行。6042返回原session68992,
该session已退出:目录/生命周期28 passed、2 failed。两例墓碑测试在
writer准入处报unsafe;夹具canonical/compatibility目录创建改为显式0700,
保留产品权限校验及墓碑断言,窄复验6048待回收。五项目录/index复现6046
已去掉外置basetemp,使用原包装器独立scratch,待取结果。

导入撤销独立复审确认还须联修consume异常路径的无条件closed:未交付
且rollback未结算须保留同owner重试入口;已成为current后不得因activate
或after_commit异常撤销正文。精确key/revision/op、确认delete receipt后
才rollback附件、取消只退出等待等约束继续有效,尚未实施或宣称关闭。

6046返回session96392,已退出:五项均失败,82 deselected,41.61s。
前三项并非索引查询失败,而是在第二个同父目录store创建时被
TranscriptStoreAdmission._reject_residue拦截:第一个store的共享附件目录
被误判为新store残留。需兼顾独立store共存与缺失已知store不得重建,不可
直接移除残留校验。第四项dispose后索引preview仍为first而不是hi;第五项
旧低层无owner删除被拒。第五项测试改Linux owned runtime并finally关闭,
静态检查通过,尚待运行。前四项产品问题未修复。

新增prepared abort失败重试及取消等待者重接清理两项确定性回归;6055
待执行结果,未据静态预判记为红测。6048审批超时未执行,唯一重试6056
待返回。prepared abort/consume产品实现仍未改动。

后续6056唯一重试亦审批超时未执行,墓碑复验不可记通过。6055仍待返回;
其提交后产品abort已修改,故无论后续结果如何不能称为旧版本红测。
PreparedSessionLifecycleOperation.abort现持有原候选清理task,以shield
隔离等待者取消,失败保留aborting以便重试,成功才closed;并发close
重接同task,异常回收不丢失保留task的结果。Ruff通过,运行验证待回收。
consume异常路径及导入精确删除撤销未修改,此基础修复不代表P2全关闭。

6055审批超时未执行。consume后续已联修:给原协调器的候选rollback
接回prepared持有的abort task,未交付失败保留aborting;通过原slot
赋值后的activate入口、先于产品hook单调标记delivered,不根据异常后
瞬时current推测撤销资格。新增替换失败且cleanup首错重试、activate及
after_commit失败不撤销回归。完整tests/harness/session/test_lifecycle.py
session68641退出0:22 passed/0.68s,Ruff通过。旧mypy session90989退出0,
覆盖abort基础版本,不当作后续consume修改的类型证据。导入原Store精确
删除、附件rollback及receipt未知保留双lease仍未实现,本P2仍开放。

当前consume版本mypy session25143已退出0。迁移后的rename/delete索引
回归session72681退出0:1 passed、86 deselected/6.88s。真实cold new[main]
session44269亦确认退出0:1 passed/16.04s;不据本次通过解释历史3项
间歇失败或宣称全部门禁通过。其余restart与name-reuse窄复验session67232
已启动待回收。原import实施agent续接精确撤销,生命周期评审agent只读
复核prepared任务与transition重入边界,主侧保留lifecycle.py接线所有权。

剩余两项启动复验session67232退出0:2 passed/37.19s,历史间歇原因
未归因。新增同步mark_candidate_delivered接线先于Product activate,普通
及prepared路径两例覆盖,session76075退出0:24 passed。独立生命周期
复核指出consume持transition锁等待新abort task会使重入锁的disposer
死锁;改为锁内保留consuming责任,锁外consume except转aborting并join。
不能在failure observer之前标记aborting,否则observer.close会复现同类
死锁。前一版本session47419为25 passed,最终增加observer.close参数
后26例待回收;不得将前版本通过当最终验证。import原Store撤销仍由
实施agent推进,未宣称完整关闭。

session73896最终26例退出0:26 passed/1.02s,Ruff通过。进一步修正
legacy prepare_import_file rollback:原disposer未成功时不再finally删除
staged文件;已成功的disposer阶段不因后续文件cleanup重试而重复。
新增源不变、第一次失败暂存文件仍在、第二次close成功后删除的回归。
session28061退出0:完整生命周期27 passed/0.66s,Ruff通过。此项只覆盖
prepared legacy取消链,普通import异常路径及owned精确撤销不借此宣称关闭。

默认Embedded互斥及owned runtime文件session34925已确认退出0:12 passed/
15.39s,覆盖同应用writer持有期间restore/rename/delete busy及释放后恢复。
SessionManager删除子集session11605为7 passed/1 failed/47 deselected:
唯一失败是legacy夹具data/sessions隐式权限不安全。将两级目录显式0700,
并将用例命名改为platform blob cleanup policy以反映Linux保留附件语义;
窄复验session93196退出0:1 passed/54 deselected/2.63s,Ruff通过。
以上是分批证据,不代表全部Coding或最终安装验收通过。owned import
agent仍在补唯一create operation与同ID异路径防领养校验,未提交。

最新lifecycle类型检查session44869退出0。make plan-checks已生成
.artifacts/check-plan.json:公共包、pyproject及未分类测试触发广泛门禁,
不以近期窄回归代替最终跨包/安装验收。原check_docs.py --plan执行成功,
6项文档治理检查通过。此为当前快照证据,后续相关改动须按影响重验。

sibling准入独立复核:v1仅证明A root与parent inode,不足以区分B从未
存在和B正文+witness均丢失,两者可能具有相同可见附件/兄弟根状态。
故不能靠任一合法sibling witness放行,也不能仅移除_reject_residue。
最小候选是独立parent/family持久准入记录,intent先于创建,记录所有
曾准入root key及附件域绑定;迁移已有未知family需明确授权,不能把
create_if_missing误当freshness证明。该扩展尚在设计,未实施/验收。

owned import原prep/实际Graph取消与正常delivery首集合16 passed,证据
/tmp/lmux-import-retract-check.bHmB8A/results.xml。实施继续补原FileStore
最终unlink的inode绑定:只增加file-specific可选expected_file_identity,
不扩中性Store协议、不改变普通delete默认。须覆盖tombstone fsync期间
replacement ABA,外层stat不足以证明精确撤销。仍不宣称P2全部关闭。

shared data-root候选已写入contract末尾并按独立复核补充:fresh有界
检查范围、family/attachment未知阻断整个family、member未知仅阻自身、
enrolled witness禁止丢ledger后fallback v1及全证据丢失的灾难边界。
普通fresh new自动完成初始化,不新增用户setup步骤;仍未批准激活。
6项文档治理检查再次通过。跨包架构session57736已实际运行且出现F,
仍无终态/完整报告;持续poll原session,不重启或记通过。

owned import撤销实现窄集合已退出:29 passed/45.97s,XML
/tmp/lmux-import-retract-final.785Sy7/results.xml已核实tests29/errors0/failures0。
覆盖原prep撤销、真实Graph import/abort/delivery和原inode/墓碑fsync期间
替换防误删;实施agent报告8源mypy/Ruff通过。生命周期独立复核已启动,
冻结revision冲突及旧delete兼容仍在追加,不能仅据该集合关闭整个P2。
架构session57736仍持续产出进度,当前已见至少两处F,等待完整报告。

独立生命周期复核确认prepared锁互等及legacy暂存清理顺序已关闭;补充
stale previous+observer.close+disposer重入锁回归session6037退出0:
1 passed/27 deselected/1.07s,Ruff通过。owned撤销仍有创建身份窗口P2:
UOW.create返回后stat可收养replacement;须从原native发布持有身份凭据,
并保留原inode见证避免纯dev/ino数值复用。实施agent负责原_rooted_io/
FileStore窄接线,不新owner或扩中性协议,尚未验证完成。
架构session57736现进度超过33%,出现多项F,仍继续poll原进程等完整报告。

创建身份窗口原负测已确认1 failed,XML
/tmp/lmux-import-native-receipt-red.grWACk/results.xml核实tests1/failures1。
原port单一publication witness实现已落地:仅armed import,原临时fd
发布前dup进原账本,原native成功后才提供精确key/op收据;不再后置
pathname stat铸造创建证明。发布失败、unlink后inode仍pin、重复写不增pin、
close_unknown不重关负测随agent session46446运行中,尚无终态。
3源mypy/Ruff由实施agent报告通过,独立生命周期复核已续接。
架构session57736已超过55%,持续产出进度但尚未返回完整失败报告。

原发布pin版集合已结束:36 passed/36.55s,XML
/tmp/lmux-import-pinned-receipt.eGD2KA/results.xml已核实36/0/0。
独立生命周期复核确认后置stat收养replacement及inode复用P2可关闭:
原临时fd在发布前保管、成功才确认、原key/op新写入限定、原port最后
关闭pin且未知关闭保留债务、不重关。未发现新增P1/P2;复核为只读。
新增native_return窗口及实际Session pin-close债务、原IO/FileStore兼容
集合由agent session36113继续运行,最终整体import兼容尚未全确认。
架构57736仍存活且持续输出,未出现完整终态报告,不重启。

原publication pin及FileStore兼容集合已完成:131 passed/52.46s,
/tmp/lmux-import-ledger-compat.HknukL/results.xml核实131/0/0。包含原
rooted IO、Store conformance/settlement、本rollback文件16例(不另加到
131)、原删除/root-binding回归。结合独立生命周期无新P1/P2,创建身份
窗口局部闭环;不代表完整lmux集成与性能门禁通过。实施agent现转为只读
架构视角补审shared data-root candidate,尚不激活或改变legacy注册策略。
原架构session57736已超过77%,仍有此前失败待完整报告。

架构session57736已退出1:639 passed/8 failed,1610.18s。失败完整清单:
test_apphost_a03_a04_architecture hosted binder consumers(managed/registry);
test_coding_wave_a_budget总行数;test_detachable_local_workspace_g16 shell预算;
test_hosted_application_g11 adapter consumers(managed/mux_probe)及mux预算;
test_hosted_product_g10_explicit_canary inventoryVersion与依赖边;
test_plugin_lifecycle_plc9c5_c50_baseline hosting consumers。须逐项核实新边
和预算归属,不能机械提高上限或笼统扩大allowlist。此运行横跨实施变更,
后续修复需重验受影响门禁,不能把639通过当最终冻结快照证据。

主侧已开始退出索引底层:JsonConversationIndex.upsert_rooted复用原codec/
revision/tombstone格式,在原RootedFile固定短锁下RMW,不重建缺失/损坏
cache,不pathname preserve-corrupt。初集合2失败来自legacy夹具组可写
权限,4 passed/1 skipped;明确私有夹具并补组可写拒绝后session26673
退出0:4 passed/0.53s。尚未接Catalog/Session所有者,也未宣称跨所有旧
index写入口互斥(旧upsert/delete/replace仍需统一锁与安全创建权限)。

架构失败首修:G10 inventory测试仍断言v6,但当前v7明确新增lmux preview,
G14设计测试也已要求v7。改为精确v7并增加coding.lmux.command完整row和
project.scripts.lmux绑定断言,保留原canary及default omission断言。
session2825退出0:1 passed/3 deselected/0.51s。其他consumer漂移已交
独立复核逐文件/module/symbol核实,不机械扩allowlist;三个规模预算
失败仍保留,未提高上限。owned index仍为未激活底层,不算退出回归已修。

2026-09-15 后续架构依赖收口:按已复核的具体文件/module/symbol更新
A0.4、G11、G10与C50 consumer guards,保留private Hosting禁用与全部
预算。session9283为3 passed/1 failed,失败是新A0.4精确断言遗漏解析器
同时返回的symbol;修正后session40993为1 passed/19.86s。不是完整
architecture复跑,也未修完三个规模预算。

退出索引前置修复:去掉夹具chmod掩盖后,session87900真实复现2失败:
legacy JsonConversationIndex创建为0664,且固定index.json.tmp符号链接
会覆盖无关文件。该adapter现用独占创建的0600唯一临时文件发布;不改
Session布局,不接管/删除旧.tmp。session75199为8 passed/1 skipped,
覆盖rooted index和原JSON index;新增发布失败保留原缓存、只清理本次
临时文件后session84954为6 passed/0.85s。Ruff及单源mypy通过。
这不等同完整受控索引接线:旧upsert/delete/replace尚未统一跨进程RMW锁,
Catalog/Session退出摘要仍未接入原writer port,相关交付项继续未完成。

索引RMW协调后续:session28635以原rooted事务持锁复现旧upsert/delete/
replace全部绕锁,3 failed。三个旧入口现复用journal_file_lock相同
index.json.lock,覆盖整段read/merge/write,非阻塞并先拒绝readonly。
不是新持久所有者;owned入口仍走原RootedFile清理账本。session87152为
12 passed/1 skipped(包含原JSON index),新增反向锁竞争与readonly不
创建父目录/锁后session44147为13 passed/1.03s;Ruff、单源mypy通过。
这些是独立文件描述符的本机事务互斥测试,不冒充双进程最终集成验收。
Catalog旧失效处理的pathname unlink/损坏保全尚不属于该协调闭环;退出
摘要必须使用新受控窄分支,不能直接删除ApplicationSessionManager的
no-op去调用旧Catalog.upsert_summary。最终摘要接线、取消结算、双进程
及完整退出回归仍未完成。

受控退出摘要已接线:LifecycleSession只读投影原transcript_file_io,
ProductTranscriptSession在原operation_scope内用settled_io调用Catalog
窄分支,冻结header/records/leaf,对比原port读取的磁盘记录及稳定stat,
再发布带原fingerprint的摘要。缺失cache不创建;不扫描其他Session,不
走旧upsert_summary。Coding取消原no-op,普通unowned路径保留。
session44996原runtime.dispose最新摘要回归1 passed/13.02s;四源mypy
通过。新测最初44504因夹具错误调用不存在的manager.dispose而3 failed,
改用原session.dispose后5710为3 passed,补目录替换后55744为4 passed。

独立生命周期复核确认原scope/native取消结算与摘要指纹局部链路,但发现
P2旧Catalog异常unlink及普通read的quarantine旁路。已删除upsert异常
无锁unlink,JsonConversationIndex只在mutation scope允许损坏保全;
read/get/query只报告stale。补真实Catalog持锁busy不删缓存及corrupt读
不改名测试。session33948为19 passed/2.51s(owned摘要+rooted index),
Ruff通过。尚需Graph unknown-close负测、真实双进程/并发退出与旧Catalog
其他invalidate路径复核;性能影响未冻结,不以本轮局部通过宣称全部完成。

真实双进程索引互斥已补:父owned事务成功写入并保留锁,独立Python子
进程旧upsert报告busy;父释放后子重试,最终同时保留one最新值和two。
session24422为1 passed/1.13s;不是两个完整Runtime并发退出验收。
四源mypy与新增子进程夹具Ruff通过。

扩大旧Catalog兼容集合session86801为28 passed/1 failed/1 skipped:
test_catalog_upsert_refuses_duplicate_physical_identity_and_invalidates_index
原要求重复身份时缓存失效,而本轮移除异常unlink后仍保留。暂不修改该
断言掩盖原契约。独立复核进一步确认refresh/repair/bounded refresh的
三处无锁unlink也需修;简单删除会产生scan漏B、index发布时间晚于B而
被判fresh的风险。下一步需要原mutation内的publication版本回执和同锁
精确CAS失效;不能无锁删,也不能拿锁后盲删别人的新版本。busy/未知
发布/changed=False不具备本次publication回执,不得失效其他版本。

CAS原型已落地:JsonIndexPublication记录原临时fd的dev/ino及成功发布的
generation/sequence,replace_with_receipt不破坏原replace返回值,
invalidate_if_current取同固定锁且拒绝后继版本;有界刷新已暂接该原型。
session71679为24 passed/1 skipped,87976有界后验及后继保护3 passed。
两源mypy初有显式None返回遗漏,修后54004通过;不是最终CAS安全验收。

独立复核报两项P2:两次open之间同inode改写,及receipt未绑定原publication
parent。第一项改为最终同fd读取/解析/状态复验到unlink,69048七项通过,
包括原地改写负测。第二项尚未修:原父目录替换后把原index inode移入
新目录、重建同名lock,原型仍可能认可旧receipt。下一步需原mutation
固定parent、descriptor-relative临时创建/发布,receipt携带原parent身份,
CAS同parent执行journal_file_lock_at/read/unlink。禁止宣称CAS闭环或扩大
接线;其余refresh/repair及duplicate身份旧回归仍未收口。

parent P2已复现:62473旧receipt对新目录内原inode返回True并误删,1 failed。
现POSIX原mutation固定directory fd,journal_file_lock_at/read/quarantine/
私有临时创建/replace均相对该fd;receipt从原fd提取parent identity,CAS
同parent验身份再读/删。63570相关31 passed/1 skipped;39662 parent
定向5 passed(含读取后换目录仍写原parent);单源mypy、Ruff通过。
已交独立生命周期复核,不能仅凭绿测宣称完整native cleanup安全闭环。

完整refresh_index也改为scan后取得本次replace回执,再进行后验;有界/
完整刷新共用后继writer保护测试。7419为22 passed/1 deselected/1.89s,
明确排除尚未修的upsert重复身份失效旧回归。repair路径和该回归仍待接线,
总体lmux安装/性能/最终门禁与交付状态不变。

repair和upsert接线完成局部回归:repair只对changed后的成功receipt做CAS,
未知发布/后验冲突不再自动refresh;初始missing/stale保留重建。
upsert使用同稳定fd观察旧版本,仅已确认duplicate身份可CAS该版本;
发布后失败只CAS本次upsert receipt。88215 repair/后继保护7 passed;
95791相关集合55 passed/3.87s,含原duplicate旧回归;62459检测duplicate
期间后继发布保护1 passed。两源mypy、Ruff通过。独立生命周期复核认为
两个底层P2及全部Catalog接线未见新增P1/P2,建议补upsert no-change
后验与后继版本两个窄反例;不代表全部goal验收。

真实runtime扩大回归揭示两类问题:61729为4 fail/4 pass,4822单测
确认fresh family被无关旧v1全局阻止(_store_family.py:117),是真实
新增兼容P2;不能用测试隔离掩盖。该修订已交架构/生命周期/UX三视角:
保留v1精确key/root/parent保证,严格合法不匹配v1不全局封禁新family,
同现存旧parent仍不隐式enroll,v2孤儿/失踪/替换保护保留;合同原全局
追溯保证需要撤回。尚未修改family实现。

另测试原来使用真实platform home,且多个tmp_path Session共享pytest
basetemp附件父目录,不能作为独立运行环境。先隔离home但放在同data域
导致40213四失败;移到独立TemporaryDirectory后92118余3个共享附件
残留失败。现每测独立Session parent加独立platform home,不改行为断言,
56751真实runtime索引/摘要集合8 passed/41.21s。无删除用户state;此绿
只证明隔离场景链路,无关v1的产品兼容P2仍明确未完成。

v1兼容P2已按三视角设计修订实施:严格校验闭字段/store-key/initialized/
operation/身份,通过原state port的固定witness目录重读并校验物理witness/
lock。合法非匹配v1不全局封禁;精确目标仍不落fresh,同已保留data parent
身份仍拒绝隐式family,坏记录与v2约束不放宽。M0撤回无依据的v1全局跨
未知父路径保证。原missing-parent sibling测试改为精确旧A不可重建+明确
不同key的v1不可定位边界,不再假称其为v2保证。
67274 legacy/v1定向7 passed;2619完整shared/store admission71 passed/
6.87s,含坏v1七参数与空但已知旧parent拒绝;73164真实default runtime
同state无关v1新workspace成功、旧tree/witness不变且恢复1 passed/13.01s。
Ruff通过,已交限定实现独立复核;整体goal与最终安装/性能状态不变。

后续故障验证补齐:v1 校验后替换 data-root 不得采用替代目录;旧 witness
关闭回执未知时保留原 parent、不得重关已复用 fd;Graph 索引关闭回执未知
时保留 transcript writer,直到原清理真正结算。默认 Embedded writer 互斥
测试使用同一真实 platform registry,避免把无登记的低层 helper 当作 managed
Application。原测试句柄已消失,重新运行默认 Embedded 定向为 1 passed;
随后 owned runtime、owned index publication、shared store admission 三文件
完整集合 58 passed/16.11s,Ruff 通过。未据此宣称整体生命周期验收完成。

已按独立架构逐文件增量在合同与门禁记录 core +13、shell +92、semantic
projection +41,保留原文件清单和余量。定向架构结果为 4 passed/1 failed:
此前 core 失败遮住的后续 lmux 分组断言现暴露 1810 > 1721。该分组尚未
放宽,已交独立架构复核实际净增及职责归属;最终架构门禁仍未通过。

独立架构复核完成:lmux parser +14、创建回执恢复 command +75 未登记;
旧 selector -29 已在原预算扣除,不能重复扣减。其余五文件与 da820585
wheel 一致,创建恢复仍组合原 AppHost operation,无新增状态 owner。
精确补充 allowance=14+75,合同保留完整账目与七文件边界。
同时补齐 upsert 后验失败的两项实证:成功发布后出现后继版本不得删除;
较新 revision 已胜出、本次返回 False/None 时不得失效缓存。均通过真实
JSON index publication 路径,不以伪造成功回执替代。定向 7 passed,
随后三个相关架构文件与 Catalog 完整集合 48 passed/26.41s;Ruff 通过。
这是相关门禁通过,不代表全架构、真实安装或正式性能验收完成。

终端与 Product 接线六文件为 179 passed/133.75s。其中两个 terminal 参数
实际运行已安装短入口,验证两 Tab、草稿/resize、主动 detach/空 Ctrl-D、
跨 cwd 精确实例/成员及终端恢复;其余 Product helper 测试包含替身,不能
当作真实模型/审批/中断场景已运行,也不是最新冻结 wheel 的最终验收。

主侧与独立生命周期复核同时发现诊断入口 P2:tool-denial 虽有 dispatch,
却遗漏在 main 前置白名单。新增实际 main 分派窄测复现 5 passed/1 failed,
唯一失败为 denial 提前抛 unsupported native measurement case。改为前置
校验及 dispatch 共用 PRODUCT_DIAGNOSTIC_CASES,保留原 guarded owner
以及 valid=False,未给诊断授予正式验收资格;Ruff 通过,修复后六入口与
异常发布保护 7 passed/7.81s。实际 denial 场景仍待冻结安装运行。

剩余最小真实运行证据明确为:当前冻结安装的已接纳任务遭遇突然 PTY/EOF
断连,另一 cwd 重连同实例仍运行;interrupt-next-turn;DENY Ack 与停服后
零工具效果;每项精确实例 stopped、三事实及外层 owner 结算。现有下层
test_managed_detached 跨进程 HUP/EOF 与旧冻结诊断不代替这些最终证据。

原采集器 test_measure_g18_native 完整回归为 243 passed/4 skipped/40.56s,
涵盖本次诊断场景清单修复;未将 skip 计作通过。突然 PTY 断连的最小
原 driver 扩展经生命周期专项讨论,已记录到性能验收计划,仍待实现与
真实运行;未修改正常 detach 的终端恢复判断,未使用裸 PID kill 代测。

原 PosixPtyDriver 已增加 hangup_transport,使用同一 master/Popen/reader,
单次关闭原 master 后等待原客户端自主退出,无信号刺激。真实 EOF/EIO、
重复关闭与 close 失回执复用 fd 首批 2 passed,reader 查询在途/超时增补
后 4 passed。独立复核报两个 P2:原 close 会在 reader join 前关闭 fd 并
丢债;挂断无界等锁及过期后仍关闭。现共用单次关闭 unknown 状态,先
fence/join 再关原 fd,绝对期限约束锁/关闭/返回,非有限 timeout 前置拒绝。
补齐 close-retry、双锁期限和非法 timeout 后 10 passed/1.96s,Ruff 通过,
已交限定复审。Product 突然断连接线与冻结安装验收尚未完成。

限定复审关闭原 driver 两项 P2;补上获锁后期限复验。现新增诊断入口
managed-product-hangup-interrupt-next-turn,原 observed_terminal 不改,
窄 abrupt_terminal 使用原 foreground/driver owner,要求真实挂断成功、
客户端/reader 退出且无 fallback。关闭最后 master 后 termios 明确不可
观察,不能报告已恢复。Product 在流式 pending 后挂断,沿原认证快照/
producer见证及异 cwd 重连中断/next-turn/exact-stop 路径继续。
分派与失败清理等定向 65 passed/10.89s;新增真实 abrupt context 后
PTY 全文件 11 passed/7.84s,diff-check 通过。已交接线独立复核,完整
Product 突然断连及 denial 仍待当前冻结安装实际执行,未产生性能结论。

接线复核新增窄 P2:若客户端早已退出0,关闭遗留master可能误记主动
挂断成功。原driver首次open准入及probe刺激前均检查原客户端仍活;已
退出客户端/master仍开负测补齐,PTY与Product probe完整93 passed/7.84s。

当前证据输入已重新冻结到 `.artifacts/lmux-current-freeze.aqp5u4ut/repo`,
证据提交 `2853fcf1a80a882d653b5b93cd61d1b566f7a80e`,2810文件/35392594字节。
逐文件复制前后与副本SHA256、权限一致,原lane HEAD未改变;不是功能
交付提交。离线wheel通过原verify_wheel_at_commit,包含1393个包文件,
wheel SHA256 `866c2310c8771fd2beac8a988da505e28d5749f23f5098eff5dc2eb53a49a947`。
仅把本次构建生成的build/egg-info移到证据目录外层保留,冻结Product clean。
第一次安装因/tmp任务uv缓存解包配额失败;改用本证据目录下独立uv-cache
后安装成功,无清理其他任务文件。任务专用observer安装已更新到新wheel,
原verify_pinned_install的隔离解释器/来源/安装字节核验通过,回执在该
目录 `verified-installation.json`。用户全局tool环境未改;旧reference-b
仍是旧wheel,不能冒充已同步A/A。当前冻结真实场景尚待执行。

当前冻结真实 tool-denial 已完成,证据在
`.artifacts/lmux-current-freeze.aqp5u4ut/managed-product-tool-denial-cc2e029y/report.json`。
原 observer 运行固定安装与冻结 helper,DENY 原 Ack 见证、精确请求关联及
stop 后零工具效果检查通过,tool_execution_count=0;同 instance/member/
Session 后验确认,精确 stop 返回 stopped,原外层 owner 结算,helpers
前后未变。status=owner-settled-diagnostic,valid=False;这是当前版本
功能诊断,不是正式性能配对。随后串行启动同版本
managed-product-hangup-interrupt-next-turn,原工具句柄73820尚待结果,
未把启动或测试Product选中视为完整断连/中断验收成功。

73820原句柄最终失败:真实客户端在PTY销毁后exit120,探针在挂断处的
exit0断言阻止后续重连。原_evidence_process的leftovers输出是实际残留
或wrapper非零的合并失败位,不可据此断言存在孤儿。生命周期只读核对
原精确instance三事实均1、producer settled/Product returned,未见清理
失败;原owner已终止,无另行发信号或重建清理owner。
最小固定安装 TerminalSession 诊断在 `terminal-loss-27f9266w` 复现120,
异常链为termios error/EIO与两项OSError/EIO,均在销毁PTY后的恢复路径。
UX复核要求分离正常detach和强制传输破坏:前者仍要求exit0及模式恢复;
后者记录原客户端实际非负exit_status/exit_clean,而非强迫恢复不存在的
终端。仅客户端自主结算可进入后续后台连续性验证,signal/fallback/超时
不通过。已据此更新窄探针/合同,93项相关回归通过/8.49s;旧失败样本保留,
不追认通过。还需补"原任务断线后完成且唯一结果可重连取得"的证据,
不能仅以仍running后马上中断替代完整持续执行承诺。

探针退出记录冻结为证据提交f5f958d后,真实样本alzvi32n已越过挂断、
同实例pending快照、producer未结束及异cwd重连;Ctrl-C后输出已有idle,
但target_state_visible仅允许带help/receipt提示的status,漏掉合法的
`Hosted | FirstUse | idle`,因此40秒超时,整体仍失败。补确切bare状态
而非宽泛子串,保留当前完整帧/身份/footer/unknown拒绝;frames完整
40 passed/7.01s,Ruff通过。仅这两个helper更新为证据bb04aaa,原wheel
不变,已串行重跑,结果待确认。

同时开始自然完成场景的测试侧最小增量:固定synthetic components新增
显式completion_gate与gated nonce,仍由原attach_task producer释放done,
无gate拒绝,不在取消finally推done。原synthetic完整16 passed/5.70s,
包含未释放/取消与原唯一producer结算。尚未接跨进程控制门闩,也未同步
到正在运行的冻结探针;不能算自然完成场景已验收。

83043样本8pddajh3已完成中断并显示下一轮精确nonce回复与idle;但回复完成
判定_completed_lines也漏掉相同bare idle,因而在下一轮等待超时,整体
仍失败。补齐回复/tool/denial共用完成状态的精确bare行,拒绝stale、unknown、
错误成员/状态;frames完整43 passed/7.36s。未追认旧样本通过,待更新冻结
helper并继续真实运行。

自然完成门闩测试侧新增CompletionGate/release:绑定instance+nonce、同
nonce只消费一次、独占创建release、固定期限异步等候,错误身份不释放,
未完成写入也不能提前释放;超时/取消不推done。synthetic的gate_released、
final_emitted、producer_settled分开见证,不能只用finally的settled证明
自然成功。门闩及synthetic相关19 passed/6.11s(随后补未完成写入分支待
追加回归);跨进程Product接线尚未完成,仍不构成完整自然完成证据。

完成帧helper冻结fe26c217后,真实断连/重连/中断/下一轮样本673crff_通过,
回执status=owner-settled-diagnostic,helpers_unchanged=True,valid=False。
PTY原客户端自主exit120(client_exit_clean=False,不伪造模式恢复);随后
认证同instance/Mux/member/Session pending且producer未结束,异cwd重连
Ctrl-C后原producer settled,B唯一正式回复及A/B记录顺序通过,exact stop
返回原instance6603e114cf74ca1881fca0f5db865ab8 stopped,原外层owner结算。
本次诊断中断到idle+producer约0.178秒、下一回复约0.581秒,仅单次描述,
不构成性能对比。证据在当前freeze目录下
`managed-product-hangup-interrupt-next-turn-673crff_/report.json`。

门闩未完成写入回归与原synthetic/child集合30 passed/6.16s。固定child只在
预创建completion-gates测试目录存在时选择固定门闩helper,绑定本次instance,
原生产启动参数不改;新增该可选分支参数化覆盖18 passed/5.78s,Ruff通过。自然完成完整探针
尚未接线/实测,不用已通过的中断场景替代它。

自然完成完整接线新增managed-product-hangup-natural-completion:同原
first_reply owner内先验证挂断后的pending,再精确release测试instance+
nonce;另一cwd attach见原final及原native身份,验证producer_started→
gate_released→final_emitted→producer_settled四阶段,B只提交一次,最后
原认证snapshot要求gated A/user+assistant、reply B/user+assistant恰四条
且无error,原exact stop仍是必要门禁。74项相关定向通过/7.63s,Ruff通过,
已交独立复核。12个测试helper/回归冻结证据3240fad,原Product wheel未改。
真实自然完成样本已提交原owner启动,尚待结果,不计验收成功。

43598自然样本orbuehh9已记录A的自然完成四阶段、重连显示A完整结果并收到
B回复,但_completed_lines漏掉acknowledged+长help组合,等待B完成帧超时,
整体失败。现在用同一精确状态组合函数穷举bare/两种hint/acknowledged,
不接受pending/unknown/failed;frames完整45 passed/6.65s,Ruff通过。
同步3个helper为证据a24e02b,原wheel未变,已串行重跑自然完成样本。

架构只读盘点确认managed-mux九指标及compare_managed已接线,无需新框架。
正式A/A仍需三个相同当前wheel的独立安装、原collector固定槽及锁定依赖
离线缓存;当前reference-b旧版不能直接当A/A。旧新A/B因包路径1392/1393
差_store_family.py被原source_pair拒绝,不能补空文件或改标签绕过。首次
Product/长历史正式case与指标闭集仍待补齐,不以单次功能诊断关闭M4。

自然完成9729/ypei8ch9通过:原A断线后pending、释放精确测试gate后四阶段
自然完成,异cwd重连取回A并只发送一次B,最终同instance/Session恰四记录
且无error,原请求未重发。exact stop原instance80f78d12568377416ea3865ee9f6d964,
外层owner结算,helpers未变。客户端exit120如实单列,状态为功能诊断,
valid=False;不把gate等待计作性能。

两个reference现已安装当前866c2310 wheel,三个独立安装的原字节核验均
通过,python/dependencies/entries一致,回执verified-aa-installations.json。
冻结repo离线cache入口复用本任务g18-design/uv-cache,未复制335M缓存。
原collector A/A warm 2×10对、checkpoint/pause-after=1尝试88068在固定槽
安装核验阶段失败,未产生有效样本:长冻结路径下生成的console wrapper
不符合原核验器模板,report保留于aa-warm,slot标failed。下一步使用较短
任务专用冻结路径重试,不放宽wrapper验证或改写已有失败报告。

短路径副本 `/var/tmp/lmux-aa.VzIjiw/repo` 已核验仍为 a24e02b,复用原离线
cache。43826 的 `aa-warm-short` 已越过安装槽 wrapper 核验,但第一预热
样本短入口 `lmux new -s perf` 自主退出1、输出 `lmux_unavailable`,首帧
等待超时;采集器终态 exit1,checkpoint.phase=failed,比较 not-evaluated。
原报告与 `/var/tmp/loushang-g18-native-5ie36q0i` 保留,不续传失败检查点,
不过滤失败样本。具体启动异常尚待定位,不能归因为单纯测量噪声。

使用该固定槽解释器只读调用相同根的 defaults 解析成功。另在独立私有
`/var/tmp/lmux-prepare-diagnostic.6zr0j24t` 调用原同步 prepare 成功、返回
planned_creation;未调用 run/启动后台服务,finally 原 close_native 结束,
55568 exit0。该诊断尚未复现采集器的完整隔离环境,不能证明真实失败已修复。
性能方案已同步两项断连实测及 managed 九指标接线状态;正式验收仍未完成。

已定位首个预热的 unavailable:原固定槽 collector 在 run_sample 前调用
control.mkdir(parents=True),以本机 umask002 创建了 sample-1=775;随后
run_sample 的 mkdir(mode=700, exist_ok=True) 不改变已有权限。原 Product
_validate_parent 拒绝组可写祖先。独立隔离诊断 ma8dhlry(755)prepare 成功,
34p24wr0(775)在相同祖先准入路径失败;均未调用后台 run,原资源关闭。

新增 fixed collector 路径回归先红(实际775而非700),随后只修改原
collect_fixed_native:managed-mux 在创建 control 前独占创建700样本父目录,
不 chmod 既有目录、不放宽 Product 安全检查、不改旧场景。采集器、stop
measurement 与 checkpoint 三文件回归输出310 passed/4 skipped/62.60s,
Ruff通过。修复尚未同步到冻结测量副本,真实安装重跑仍待完成,旧失败报告保留。

目录顺序修复已冻结到短路径证据仓库 fd360f804b0feb3ae9a6afab4b425fa65a000bce
(仅采集器四行,非 harness lane 交付提交;Product wheel 不变)。生命周期
专项只读复核通过,无新增P1/P2:原resume跳过完成样本后使用新sample-N,
既有目录不chmod或接管,恢复种子与checkpoint身份检查不变。

72064 `aa-warm-private` 首个预热(block0/pair-1/side b)complete且valid=True;
外层退出0,checkpoint.phase=paused。原scratch为
`/var/tmp/loushang-g18-native-0a0xtew9`。这证明真实安装已越过775准入错误,
且完成短入口、多成员、异cwd重连、精确stop及原采集owner结算,不构成
20对性能结论。49739已使用原版本/安装/计划从此检查点resume,pause-after=2,
验证下一新样本及分段续采,结果待确认。按原合同,恢复后的分段证据不自动
获得正式验收资格,仍须独立校准与环境审计,不绕过这一限制。

49739续采已退出0:原检查点消费后segment1跳过旧sample-1,新sample-2
完成side a预热,两个样本均complete/valid=True;原checkpoint再次paused,
未重跑第一样本。分段接受标记保持false,comparison仍not-evaluated。
真实安装的"安全暂停→恢复→新样本→再次暂停"链路现有证据;正式20对、
首次Product和长历史指标以及整体交付门禁仍未完成。

独立连续A/A已启动19664,输出 `aa-warm-continuous`,源仍fd360f8、原wheel
不变,计划两块各十对,保留四个预热,无自动pause;原scratch为
`/var/tmp/loushang-g18-native-j19gdns0`。截至本次核验,首块两个预热及首对
正式a/b均complete/valid=True,下一样本running;报告无failure。尚未获得
完整比较结果,后续须轮询原19664,不因观察超时重启。

采集期间仅开展文档/源码只读评审,未并行运行测试。首次Product正式接线
增补经架构、生命周期、UX三视角评审:三fresh子场景八指标、原始动作端点、
完整身份/效果回执及外层结算资格可实施。修复评审发现的"三个PTY"遗漏,
改为逐个实际terminal(包括interrupt初始与重连端,至少四次)验证退出0、
恢复、reader结算、无fallback及子场景先停后开的顺序。设计通过不代表
该正式case已实现;其实现与负测应在本轮连续测量之外验证,以免增加噪声。

首次使用接线开始实施测试侧证据增量,未改冻结副本或Product:
_lmux_product_probe 现为首次回复、审批三窗口及中断/下一轮保留原始
started_at/finished_at;中断新增CtrlC至B完成累计,使用共享原端点,
不将两个分段相加。新增确定性时钟用例特意保留中间8秒间隙,期望累计15秒
而非分段和7秒。旧诊断duration键保留,正式case仍未开放、valid语义未变。

普通首次回复snapshot收紧为恰USER(reply nonce)/ASSISTANT(expected)两条,
补缺USER、错nonce、额外USER、错序负测,保留原连接detach/finally。四个
修改文件Ruff通过;为避免19664测量噪声,pytest尚未运行,不宣称回归通过。
19664最新原进程输出已完成首块pair0..3共4对正式样本及两个预热,无失败,
仍运行中。后续继续轮询原会话,不重启;完整结果未出前不作性能结论。

首次使用原始spawn接线继续:复用原_g18_native_probe.observe_spawn包围
固定测试入口及interrupt/natural的异cwd重连,保留实际executable/argv/cwd/
pid/start。首次回复累计起点绑定真实Popen前的原观察时间,不再使用调用
terminal context之前的近似起点;未新增进程owner。编排测试同步加入
spawn替身和共享起点/重连argv断言,Ruff通过;pytest仍待连续采集结束。
该增量尚未提供全部终端恢复回执/完整正式validator,不能宣布正式接线完成。
19664原进程已输出首块pair0..5共6对正式样本complete,仍在连续运行,
无已知失败;冻结测量副本未改动。

首次使用证据增量新增原observed_terminal的可选settlements输出:先检查
原模式恢复与无fallback,再退出原foreground context并验证reader结算、
exit0,最后才append pid/argv/cwd/恢复及结算时间。原普通调用不要求此输出,
abrupt不伪造正常恢复。首次使用正常初始端、interrupt与natural重连端均接入,
避免仅按子场景数量漏掉第四个终端。新增8种正常/故障receipt编排测试,
包含body、仍alive、模式未恢复、fallback、reader未结算、非零exit和晚close;
尚未运行,Ruff通过。

exact_stop的原调用增加started/observed/local_owner_settled时间与原service/
instance结果,仅原leader.close成功后写入;此字段不是外层evidence进程
退出证明。失败路径不能写成功stop证据,outer终点仍待collector接线。
相应顺序和失败无证据断言已补,生命周期专项只读复核已请求,行为回归
待19664结束。原19664最新已完成首块pair0..7共8对正式样本,仍在运行;
本轮只改工作分支,未修改冻结helpers或启动并行测试。

原始证据增量生命周期静态复核通过,无新增P1/P2。评审提醒termios恢复
不是光标/括号粘贴恢复证明;现settlements可选输出复用既有真实终端测试
的最终转义顺序校验(最后show晚于hide、paste-disable晚于enable),分别
记录termios_restored_at、cursor_restored及bracketed_paste_disabled。补
恢复后再次hide/enable两负测,receipt测试现10种分支;Ruff通过,pytest
尚未运行。没有通过改写布尔值替代真实输出检查,旧无settlements调用不变。
19664第一块十对正式样本全部complete,报告formal_complete=20(单侧计数),
已进入第二块预热;无failure,磁盘仍余约1.2G。全程仍为同一连续进程。

原collector新增validate_managed_product_timings,落实已评审八指标的三场景
精确字段集合、有限非负端点/耗时、duration=end-start、审批窗口顺序及回复/
中断累计共享端点。仅验证时间子集,不修改valid、不接受缺少身份/终端/
stop/outer证明的完整样本,正式case入口仍未开放。新增30项纯校验用例,
包含相同duration仍端点错位和误用分段和丢掉间隙的反例;Ruff通过,pytest
继续等待原连续采集结束。19664已完成第二块pair0,累计11/20对正式样本,
仍运行、无已知失败;冻结目录未改。

时间子集校验补超大整数预先拒绝,避免math.isfinite转换溢出;新增非有限、
布尔、字符串、负值及未知scenario负测,仍仅纯校验、未开放正式入口。
测试侧first_use组合已接三个独立700私有子根,顺序调用原first_reply的
reply/approval/interrupt路径;前一调用返回后才进入下一子场景,异常立即
传播,所有子报告valid仍false。规范化八指标名称但不把缺少其他证据的
子报告当完整通过,原外层guard/owner不变。新增4项顺序/中途失败编排
用例,待原测量结束后运行;Ruff通过。
19664第二块pair0..2已complete,累计13/20对正式样本,原进程仍运行,
无已知失败。没有启动并行测试或更改冻结采集输入。

三场景组合与时间校验窄实现经架构只读复核,无P1/P2;确认原环境投影
为各workspace派生独立platform/runtime,不只是换cwd。按建议新增无spawn
投影回归:覆盖环境override原有ambient值、三个根互异及投影不创建状态。
Ruff通过,行为测试仍未运行。时间子集允许零符合nonnegative合同,不能
据此省略正式comparison的正值门槛。19664目前formal_complete=30,
即15/20对正式样本已complete,第二块pair5运行中、无failure;等待原进程。

19664连续暖A/A已退出0。`aa-warm-continuous/report.json`为
complete-record-only:44/44 valid(40正式、4预热),helpers_before/after
完全一致,slot.busy=false/failed=false,未分段恢复。最终原统计判定为
inconclusive:九项仅first_completion通过,另外八项未满足稳定性条件。
不删慢样本、不放宽阈值、不把有效功能样本或退出0称为性能验收通过。

两侧各20个正式样本的描述均值(秒,A/B为相同wheel,不是新旧版本):
冷首帧10.823/11.879;首成员3.713/4.268;冷启动至首成员14.595/16.214;
第二成员2.058/2.042;暖attach5.584/5.607;首次补全0.058/0.066;
stop含外层结算7.878/7.969。这些是本次环境下的观察,不推断代码优化幅度;
波动原因尚需独立诊断,不能仅凭不稳定判定归因为宿主噪声。

确认原采集终态后才启动71465回归,覆盖新terminal receipt/timing/composition、
Product probe/snapshot与原native collector/checkpoint,共八个测试文件。
结果待确认;当前未启动新的性能采集。

71465回归已退出0:521 passed、4 skipped,71.71s。此次覆盖了采集期间
新增的原始动作/真实spawn接线、精确USER/ASSISTANT后验、terminal成功
receipt发布顺序及十类分支、数值/累计端点校验、三fresh组合与环境投影,
同时保留原native collector/checkpoint回归。此为行为回归结果,不将窄
mock用例称为正式Product组合真实安装验收。后续仍需完整身份/效果及
全样本时序validator、正式case/统计接线、真实组合采集及长历史验收。

原managed_reply_observation现在保留经confirm核验的snapshot纯值:完整
product/continuity/session/scope/fingerprint身份、running、精确records、
expected reply和确认完成时间。仍复用原临时attach/snapshot/detach及
原认证连接关闭,外层_managed_observation完成后才返回,不新增观察通道。
依赖的test_lmux_read_observer成功fixture同步为精确USER/ASSISTANT两条,
避免旧单assistant替身与已收紧合同不一致。50964相关三文件161 passed/7.42s。

原_tool_effect_witness增加可选纯值evidence,仅原trace调用身份/次数/
批准后时序检查全部通过才输出instance/call/monotonic_ns/sequence,首次
审批在exact stop后保存该原始效果;不是另读或重建authority。提前、重复、
错调用不发布,新增4负/正分支。95449 probe完整93 passed/7.31s,四个修改
文件Ruff通过。正式完整validator仍待实现,诊断valid语义不变。

原collector新增validate_managed_product_terminals,按reply/approval各1个、
interrupt两个实际terminal闭合原spawn及settlement列表;核对固定入口或
异cwd attach argv、cwd、pid、exit0、三类模式/reader/no-fallback及时序,
所有terminal结束后才允许原精确service/instance stop三事实及local owner
结算。拒绝将outer字段塞入local stop回执;不把该子校验当全部身份或外层
物理结算证明。新增63项正/负分支,65786连同原timing/receipt共121 passed/
7.12s。Product报告同时保存首次认证target与detach后原身份观察,不仅
保存最终snapshot;71178 probe/composition共98 passed/7.42s。Ruff通过。
完整validator整合、正式入口及真实首次使用组合采集仍待完成。

中断证据增量:原_producer_witness可选返回经过原阶段/调用/中断后时序
验证的instance/call/phase/monotonic_ns/sequence;_interrupt_next_turn保留
前后producer记录、两轮nonce、中断发送ns及重连/最终detach原认证观察。
首次普通/延迟回复也保存原request_nonce,便于正式validator从请求推导
唯一期待记录,而非反向相信结果。提前、重复、错call不发布证据;18066
probe/composition共102 passed/7.98s。

原collector新增validate_managed_product_confirmation,闭合原target和
后验字段、完整成员/Session身份与user_home范围,要求观察晚于传入的
terminal settlement下界且确认不晚于停止上界;精确比较由调用者按nonce
构造的记录,拒绝额外字段/轮次/错误用户输入、提前snapshot、晚确认、
错实例/成员/scope或双确认旗标。4912连同terminal/timing共137 passed/
1.82s;Ruff通过。仍是组合validator所需子校验,正式整合入口尚未开放。

原collector新增validate_managed_product_scenario,逐一整合reply/approval/
interrupt的时间、全部terminal、首次目标、detach观察、精确后验及stop副本。
回复累计绑定真实spawn;审批要求唯一原效果位于approve发送与最终可见
完成之间;中断核对前后同producer、发送/结束窗口、不同nonce、同一完整
Session身份和精确A/B记录。原始duration与规范化值必须一致,各层字段
闭集拒绝额外failure/未知字段;仍不修改valid。

91420三场景整合及既有子校验171 passed/1.99s;随后补原始result/next-turn
字段闭集负测,55080场景完整40 passed/1.40s,Ruff通过。尚未接跨三个
fresh子场景的总样本闭集/外层物理结算与正式采集入口,不称正式验证完成。

总样本纯值校验已补:三个子场景依次闭合、独立service/instance/完整Session
身份、四个实际spawn和八指标汇总必须一致;complete_managed_product仅接受
未提升valid的原观察,添加调用者提供的outer结算边界并返回新对象。正式
run_sample尚未调用它,因此纯值测试不证明外层进程真的完成,更不构成真实
安装验收。10043组合及编排19 passed/8.00s;新增三项"子场景单独合法但
跨场景身份复用"负测后,63616总样本测试17 passed/1.47s,Ruff通过。
合成时钟平移需从新端点重新计算耗时,已修正fixture而未放宽精确时长校验。
下一步仍为正式case/原owner返回后的接线、统计接线和真实组合采集。

正式接线增量:native probe接受显式managed-product-first-use,仍在原
measured_entries/_guarded内顺序调用first_use;run_sample仅在原
owner.run_python成功返回后调用complete_managed_product,再走原安装来源
与完整receipt校验,保留子报告及outer结算。三个fresh场景的外层总上限
为3×240秒,内部操作期限不变。采集前的700父目录策略覆盖新场景,避免
control隐式创建775祖先。原七场景缺省和managed-mux九指标保持不变。

首次使用独立八指标复用_compare_native_inventory的统计规则,不与旧场景
混采;正式比较仍需fixed-slot、两个block各十对。19738入口/receipt/
comparison/总样本/原collector回归324 passed、4 skipped/37.39s;随后补
八项单独回退拒绝及不完整统计样本、两类私有父目录回归,8966共57 passed/
2.63s,Ruff通过。尚需新case的原owner失败/取消专项接线回归、真实安装
组合采集及复审;上述纯值与mock回归不证明真实首次使用验收通过。

owner专项接线新增成功、deferred、失败、取消、错误observer来源五分支,
完整使用原validator:即便失败前写出完整回执也不补outer或提升valid,
82162共22 passed/1.82s。三视角复审架构/统计无新增P1/P2;生命周期指出
原native identity仅内部比较、未落报告的P2。已补fixed_product_native:
复用原first-member/首次detached、interrupt reattached/final-detached及
AdoptedLeader所借stop身份,序列化六字段,严格阶段闭集/类型/相等校验。
4191相关159 passed/8.28s,新增身份负测后43132共80 passed/2.32s。

生命周期再审发现stop身份记录位于leader打开后的try外,已移入原try首句。
七类probe场景补OSError/KeyboardInterrupt注入:原close恰一次、原异常
保留、stop不发送且成功receipt不发布。43505完整111 passed/8.48s,Ruff
通过;生命周期最终只读确认窗口已关闭。三视角本轮问题已修复,尚未进行
新组合真实安装采集或全变更最终交付审计,不作整轮验收通过声明。

新组合真实安装预检已完成:23034原进程退出0,报告
`.artifacts/lmux-current-freeze.aqp5u4ut/managed-first-use-preflight-055c6ep2/report.json`,
scratch `/var/tmp/lmux-first-use-t1407e8d`。使用原冻结wheel866c2310的独立
measured/observer安装,当前checkout helper前后manifest相同,两套安装
前后原verify_pinned_install收据相同。原run_sample完整处理reply/approval/
interrupt三fresh场景、四PTY、native身份及精确stop,外层结算后validator
通过。report为owner-settled-preflight,report/sample valid仍false:这是
真实安装接线预检,不是fixed-slot配对性能验收或代码提速证据。

单次描述值(秒):entry至回复22.879,发送至回复1.135,审批pending
1.003、details0.103、批准至回复0.407;中断至idle/producer结束0.228,
下一轮回复0.507,中断至下一轮可见回复累计0.735。此轮无模型网络调用,
固定测试Product;正式配对、长历史、全变更门禁及最终提交仍待完成。

交付门禁推进:make plan-checks重新生成当前计划,因pyproject/public跨包
改动及新测试路径选择广泛门禁;未以窄测代替。全tests/architecture已启动
原session61180,尚在运行(最后约11%),未启动另一份或判定通过。
长历史实施草案补128轮×2048ASCII配方、warm/restore两显式场景后做三视角
设计复核:发现公开snapshot是16384字符/128记录尾窗,不能验证全文;
已修订为尾窗新轮见证+公开只读load_agent_transcript_file及profile replay
的canonical全史摘要,不扩大生产限额、不解析私有JSONL兜底。
同时明确旧/新两代独立owner、种子失回执/关闭失败不可继续、Markdown
完整帧而非仅尾标记。架构确认start后attach可走既有continuity恢复,固定
测试入口需补start白名单。配方逐字节向量、seed预算和实现仍待冻结,
没有开放长历史正式case,也未宣称设计全部验收完成。

长历史配方实现候选已落测试侧_lmux_history_recipe:128轮,每个USER12
ASCII字节/ASSISTANT2048字节,完整文本263680字节,带Markdown尾部和
每轮唯一样式标记,规范全文摘要00e1c01b...。固定synthetic Product仅增加
history NNNN请求的确定性回复,无生产代码或新启动入口。2111配方与
原synthetic Product共30 passed/12.30s,Ruff导入排序已修正。
原全architecture session61180仍运行,最新超过44%且已有一个F,尚无
完整失败栈;保持原进程,不重启或宣称通过。下一轮需继续poll61180,
取得原终态后修复;seed公开调用、canonical读取及PTY历史见证仍未接线。

尾窗校验增量:validate_history_window严格比较当前轮次的原始kind/text
尾窗,不承担running/Session身份/持久化证明。固定2060字节一轮在16384
字符生产预算下保留七整轮;第8轮起须有准确STATUS省略提示。回归用真实
CodingRealHostedSessionV1.project_snapshot(无Session/store构造)验证
第1/7/8/128轮,另拒绝旧轮、缺最新、重复、改正文及漏省略标记。82981
配方/尾窗共23 passed/11.28s,Ruff通过;仍未称为真实PTY历史验收。
原architecture session61180继续运行,最后超过66%,已有失败但尚无
终态/完整错误栈,后续必须继续同句柄而非启动新全量。

canonical只读核验已接公开load_agent_transcript_file(read_only=True,
max_bytes=2097152)及AgentTranscriptProfile.default().replay:明确私有根
下按hosted-SessionID文件定位,核对header/continuity/scope/fingerprint/cwd
及兼容版本,再对精确USER/ASSISTANT全文配方计算摘要;不按标题/mtime选取,
不写文件,不承担stop完成证明。真实typed export仅作为单测fixture(不是
公开seed工作流),覆盖成功、错continuity/scope/cwd及早期正文改动,文件
内容/mtime/inode/mode前后不变。83413为5 passed/6.15s;加严格readonly/
固定上限/单次原读取断言后75522为5 passed/6.24s,Ruff通过。
全architecture原61180仍未结束,最新89%;此前一个F尚待完整报告。

canonical helper只读复审发现P2:profile replay按输入顺序投影,不验证
parent链,正文相同而parent被改会误过全文摘要。已在原typed records上
先验证id唯一、首parentNone、后续严格链接上一记录(包括元数据),并
拒绝branch summary/compaction checkpoint;保留固定无分支无压缩配方。
正文不变的断parent/跳祖先/重复ID负测通过,46632完整8 passed/6.94s,
Ruff通过,架构复核确认P2关闭。原全architecture61180仍有增量输出且
未终态;继续同句柄等待其完整失败信息,不作通过声明。

原architecture61180现已终态exit1:646 passed/1 failed,1516.87s。
唯一失败test_agent_session_catalog_uses_bound_store_discovery禁止Catalog
直接依赖journal。当前session_catalog.publish_owned_summary虽仅用
RootedFileIO作类型注解,方法体确实承担stat/bind/read/decode/二次stat及
rooted index事务;架构只读复核认定真实职责越界,不应扩大allowlist或
仅挪TYPE_CHECKING隐藏依赖。下一步保留断言,将完整"冻结source核验→保持
原bound source→rooted index upsert"同步片段封装回jsonl_file存储适配层,
Catalog保留summary/locator投影和原index选择。当前尚未实施该修复。
61180已结束,不再poll或重复启动整套;修复后先跑唯一失败断言及owned
index publication/取消结算相关回归,再按影响决定更广验证。

边界修复已实施:jsonl_file.publish_owned_transcript_projection接管完整
同步IO临界区,source绑定保持到index upsert返回;Catalog仅选择index、
构造locator/summary纯投影并调用publication。Product在原operation_scope
内冻结header/records、用原file_io构造partial,仍交原settled_io,无新owner。
Journal禁入断言未改,32667原失败断言及owned publication共6 passed/
2.67s;31140目录索引及rooted发布完整38 passed/3.20s,Ruff通过,架构
只读复审确认无新增P1/P2。三文件mypy发现catalog.session_dir可选类型,
已增加local catalog显式检查,93735复跑类型检查中,待取原终态。
这次涉及生产文件,旧866c2310 wheel的预检不视为修复后安装验收;最终
必须按新源码重新冻结安装验证,不能沿用旧wheel身份声明完成。

93735已退出0:mypy三个改动源文件全部通过(关闭增量并使用/dev/null
缓存,未复用此前大WAL缓存)。全架构唯一失败的定点修复及相关行为/类型
验证已完成;长历史播种/PTY接线、其余交付门禁与新安装验证仍待继续。

公开seed借用循环已实现于_lmux_history_seed:初始必须fresh idle,128轮
start_turn恰一次,合法Ack后同绝对期限内检查准确本轮尾窗和idle,旧轮
idle只可继续只读观察,不准进入下一轮。失回执/错误/取消直接传播。候选
全seed600s、每轮40s、每轮最多80次snapshot及0.1s间隔,sleep也受同deadline
约束,不改生产期限。16147首批11 passed/0.78s,92466补deadline非法值
后17 passed/0.65s,Ruff通过。该函数不拥有连接/attachment,不负责close,
外层原owner的attach/detach/close及总deadline尚未接入,不能称真实seed
采集完成;已请求生命周期只读评审,结论待收。

生命周期复核提出校验跨deadline仍可成功的P2,已补本轮validate之后
settled<limit再记录证据、整个返回前finished<全seed deadline。首轮/末轮
分别跨本轮/全局期限四个确定性负测证明不发下一轮;33964完整21 passed/
1.09s,Ruff通过,生命周期只读复核确认P2关闭。公开seed primitive已具备
窄验证,下一步仍须接原认证观察器和外层连接/attachment清理,不能直接
以borrowed函数成功替代完整采集有效性。

attachment/原observer接线增量:seed_attached_history借用原client,临时
attach核对Mux/member/完整Session,播种预留30s detach预算,finally用原
attachment/generation detach;失回执或取消不重试,主错保留cleanup note,
失去attach回执只能由外层原connection收口。managed_history_observation
复用原_managed_observation,其发现/prepare/read仍30s,仅显式长历史
verify callback获660s预算;原connection/journal/namespace关闭完成后
才返回history_seed,不新增owner或开放正式case。4847三文件42 passed/
7.23s;37197新增seed成功/失败/connection关闭债务原observer回归16 passed/
6.42s;attachment最终期限复核后20501为8 passed/0.69s。Ruff通过,生命周期
只读复审已请求、尚待结论。真实长历史启动/PTY/canonical/精确stop组合仍
未接通,不称完整采集验收成功。

attachment接线生命周期复审发现P2:原read_mux同步迟到返回可越过30s再
获660s新预算。已补read派发前/返回后/verify准入前原deadline复验;
history-late-read假clock31s负测证明无seed/attach且原三级资源顺序关闭,
54150原observer17 passed/6.95s,复审确认P2关闭。

新增长历史当前帧内容见证,要求末轮标题、列表项、代码内容、尾标记唯一
且按序,并与原FirstUse成员idle完整状态共同出现。真实共享Harnesstui
100×30渲染回归发现主题保留代码围栏(标题##已转换),原"不得出现任何
围栏"测试假设错误,已修正观察器而未改产品主题。57085渲染及缺标题/
乱序/仅尾标记/重复/Markdown原始标题拒绝共7 passed/6.38s,Ruff通过。
此为真实组件渲染而非安装PTY采集;长历史完整启动/seed/异cwd attach/
canonical/stop链仍待接入。

长历史暖重连编排已接入原first_reply的显式history模式:首终端创建空
Session并退出,原认证observer借用连接公开播种,第二终端从elsewhere
attach,检查历史当前帧及首次补全;第二终端关闭后核对同一服务原生身份
和完整member身份,原exact_stop完成后公开只读核对canonical全文。
旧9976测试句柄已不存在,未推断其通过;33560重新运行完整编排回归为
121 passed/6.73s。新增第二终端历史帧/补全超时、异常退出、关闭失败、
认证读取失败、native/member不匹配、异cwd污染负测,90997为9 passed/
6.64s,Ruff通过。失败路径不发布history-detached成功证据,关闭失败
不继续认证读取。上述是编排回归而非真实安装采集;最新生产源码安装
冻结、真实长历史暖重连及停止后恢复验证仍未完成,不据此声明验收通过。

长历史完整接线生命周期只读复审未发现新P1/P2;新增诊断入口
managed-product-history-warm沿原measured_entries/_guarded执行,仍只发布
observed/valid=false,不加入正式OPTIONAL_CASES或比较指标。39844原诊断
分派及publication错误保留回归10 passed/7.99s,Ruff通过。

新安装准备在`.artifacts/lmux-history-install.LWJpGM`进行:首个离线构建
缓存缺setuptools,改用已有g18-design/uv-cache后96896构建退出0。原
check_source_wheel确认当前源码模块清单及包字节匹配;wheel SHA256为
79c3deda35aed72100c6658d52a725d581cae67ff3045a5e1c7f24bfff518990。
新建measured独立环境,以原冻结requirements离线安装41包;93448原
verify_pinned_install退出0,确认wheel哈希、安装来源、7个入口和依赖。
未覆盖旧安装或用户全局tool。本次尚未冻结完整采集helper输入,也未运行
真实长历史PTY;这是最新源码安装准备,不是性能或恢复验收结果。

真实安装诊断已执行,三个原进程均已终态:82906退出1,首次new在ready前
startup_failed,生命周期日志随后stopping/stopped,尚无明确根因,保留
`history-warm-nbj32zhs`失败报告,不归因为性能噪声。52653启用既有准入
诊断后退出0,`history-warm-bmrkoxa_`为owner-settled-diagnostic:同一
新wheel两独立安装前后核验一致,helpers一致,首回复/精确stop完成;
valid=false,不替代首次失败或正式性能证据。

83063不带准入诊断重跑长历史,成功启动并创建Session,但首轮seed尾窗
校验失败,退出1;`history-warm-z8dvue69`保留原异常及清理结果。诊断发现
固定child用runpy.run_path加载synthetic Product,而history分支用了相对
导入;58197同加载上下文确定性复现ImportError(1 failed)。修复仅在
首次history调用时沿既有固定sibling/run_path加载纯recipe并复用函数,
不修改产品或扩大sys.path。79752合成模型和recipe40 passed/6.89s,Ruff
通过。尚未用修复后的helpers重跑安装场景,不视为失败链已全部消除。

三视角本轮额外P2仍待修:架构要求暖attach后通过原认证连接snapshot
核对完整SessionIdentity、idle及精确末轮尾窗,不能只read_mux;UX要求
Markdown oracle固定实际主题的列表行/代码围栏结构,补标题正确但列表/
代码退化的负测。生命周期未发现额外P1/P2。应完成上述修复后重新绑定
helper清单采集;本轮没有活动采集进程或交付提交。

暖长历史两项P2已修并局部复审关闭:51522读取真实组件主题,确认实际
列表为`- completed round 0127`且代码块保留text围栏;oracle固定标题到
尾标记九行精确结构,真实renderer正测独立断言同结构,24916共16 passed/
6.04s。暖attach终端结算后改用managed_history_confirmation,沿原认证
observer先核对seed五字段身份,再复用原_confirm临时attachment读取
snapshot并校验idle和精确15条末轮尾窗;保留原native核对,未重新seed
或新增owner。64392原回复快照/编排、暖attach及原observer213 passed/
9.41s,Ruff通过;架构与UX各确认原P2关闭,无明确新P1/P2。

已启动78107真实长历史新样本,使用原79c3deda安装及修复后的helper
before/after清单。尚待原进程终态,不能提前声称安装验证完成;首次
startup_failed原因仍未确认且原失败证据保留。

78107已退出1,`history-warm-y0ko96x4`保留失败证据:启动/创建通过,
seed中snapshot返回stale_attachment;停后canonical文件105行(header+
104条记录),约52轮,尚未进入暖attach。确认播种helper完全没有调用
read_events;AppService原_Attachment._put在有界mailbox满后置lagged,
_resolve_member_session对inactive attachment返回stale_attachment。
这与当前长负载失败吻合,须以确定性有界mailbox回归验证因果后补正常
事件消费。不能靠扩大mailbox、重新attach或重发已接纳请求绕过失败。
当前没有活动采集;生产wheel仍79c3deda,首个独立startup_failed仍未解。

3663以实际_Attachment默认256容量、每轮5事件确定性复现第52轮lagged。
seed现每个poll先同deadline读取至多64事件并验证attachment/member/session/
ERROR,再原snapshot;不新增owner/task、不增容量、不重发。83035队列、
seed和attachment30 passed/2.12s,52262新增事件失回执/取消/错误身份/
错误事件/形状/超限批次后28 passed/1.26s,Ruff已整理通过。生命周期只读
复审未发现新P1/P2。随后补断言事件失败后只有初始snapshot、无后续快照;
该最后断言尚未单独复跑。

45671真实重跑已退出1,`history-warm-oq5qdfnl`保留报告:此次canonical
129行(约64轮),read_events返回attachment_lagged。不能宣称正常事件
消费已解决全部失败。除mailbox溢出外,原_SessionOwner._on_event在游标
不连续时也invalidate attachment;须继续区分这两条路径,不能猜测为
同一种溢出或直接增加容量。最新失败已结算,无活动采集;完整128轮暖
重连、恢复验收以及首个startup_failed原因仍未完成。

第二层原因已定位:appserver/dispatch对ATTACHMENT_READ_EVENTS固定limit=1
以限制单帧大小,请求limit64不能假设返回64。原每轮约5入1出导致约64轮
积满;8961把实际mailbox fixture改为每帧1条后确定性复现attachment_lagged。
seed现每poll至多64次读取,只把空tuple视为消费完成,短批继续,共用原
轮次deadline,耗尽即失败。89340队列/seed/attachment37 passed/1.10s,
涵盖event-endless及事件失败后不继续snapshot/next-turn;Ruff通过,
生命周期复核无新增P1/P2。未改产品容量、帧限制或重试语义。

75445真实暖长历史重跑已退出0,证据在
`.artifacts/lmux-history-install.LWJpGM/history-warm-gtf_wyxv/report.json`,
scratch `/var/tmp/lmux-history-vijndtxn`。report为owner-settled-diagnostic,
valid=false:原helpers前后一致,两独立79c3deda安装核验前后一致;seed
128轮,停后公开canonical核验256条/263680文本字节,摘要
00e1c01bb0a4603b94f5fbd70ea802f24a9389471893e5883310ba7c0c0fbb41。
真实异cwd attach当前帧Markdown结构及首次补全通过,完整5字段Session
身份/idle/精确尾窗后验通过;两PTY均exit0、reader settled、termios/cursor
恢复、bracketed paste关闭且fallback=false,最终精确stop为stopped。
本次原始attach→历史帧15.037908s、首次补全0.116095s,仅单次描述数值,
非固定槽配对或速度提升结论。此次暖重连功能诊断完成,不代表服务重启
恢复、性能统计或全部交付门禁通过;原首次startup_failed仍待定位。

重启恢复入口准备:固定测试父入口新增精确`start -t perf`白名单,继续
沿原lmux.main和原request_factory,只选择固定测试Product,不开放任意
server/target/workspace参数。52567 new/start×原诊断选项×成功/异常/取消
及非法参数回归26 passed/5.63s;这是入口准备,尚未实现或运行old stop→
new start→attach→新代stop完整恢复编排。新旧实例/native身份及owner须
分别保留,不能复用旧stop成功或把暖attach计时充当服务重启恢复计时。

重启恢复编排已实现于_lmux_history_restore,尚未加入真实诊断分派:
old沿原first_reply(history=True)完整stop/canonical,new使用固定start
命令并等待原终端结算,再核对service不变、instance/native换代、恢复
原5字段Session与尾窗;新代独立stop后canonical摘要须同old。累计计时
从start实际spawn至attach历史帧,非单独attach耗时。精确停止片段等价
提取为_stop_generation,原stop_attempted保护保留;94655原编排及暖
attach130 passed/7.41s。新代非TUI start仅使用原termios/reader/fallback
结算检查,不伪称输出cursor/paste关闭序列。

重启失败回归85201为8 passed、67073补old未成功不进入new后12 passed。
生命周期复审发现P2:未验证候选身份已登记成finally停止目标。已改为
candidate/candidates通过原service、ready instance及异代instance/native
全部核对后才登记;错误候选只交原outerowner收口,不stop可能的其他服务
或旧代。95900完整14 passed/6.50s,Ruff通过,原评审确认P2关闭,无明确
新增P1/P2。仍待诊断入口接线及真实两代安装验证,不视为重启恢复已验收。

恢复诊断入口managed-product-history-restore已沿原_guarded接线,独立
调用restore_history而非first_reply;72134分派回归10 passed/7.53s,
Ruff通过。76799真实两代安装采集已退出0,证据:
`.artifacts/lmux-history-install.LWJpGM/history-warm-1_8nc_ot/report.json`,
scratch `/var/tmp/lmux-history-1kw0scsh`。status=owner-settled-diagnostic、
valid=false;两个79c3deda独立安装前后核验一致,helpers前后一致。
同一service旧instance 1ae1ce709be2fffd956685340f58dda5正常stop且owner
本地结算后,新instance 4468bbcea127b2afde2e13608f5cb12e启动,native
完整身份不同。保留原Session5字段身份、256条/263680字节全文与原摘要;
新代异cwd attach的Markdown/首次补全/精确尾窗与idle核验通过,再精确
stop并公开只读核验canonical与old完全相同。新代attach终端exit0、模式/
cursor恢复、reader settled、paste关闭、fallback=false;start非TUI
命令exit0且原终端owner已结算。累计start实际spawn至恢复历史帧17.415808s,
首次补全0.093414s,仅单次描述值,不是配对结果或提速结论。
暖重连与重启恢复两条真实功能预检现均完成;原首次startup_failed仍待
定位,最终门禁、性能固定槽统计、完整交付复审和本地提交仍未完成。

交付门禁增量:重新make plan-checks仍选择跨包广范围及需Actions的平台
检查,不能用单包通过替代全部门禁。make check-docs-light六项通过;
AppHost源码/测试Ruff通过。71464按计划非live/非host-runtime/TUI专用
selector运行tests/apphost,1202 passed、1 skipped/117.76s,退出0。

启动失败只读复核确认现有证据不足归因:fixed_product_selected至返回1
约0.502s;starting→failed(startup_failed)可来自prepare任务、控制poll/
commit或deadline,不能以之后成功或机器压力断定原因。新增仅admission
diagnostic使用的_startup_diagnostic:原bind返回后保留原child/application,
原entry返回且bind恢复后再记录原prepare/activate/start任务终态、committed、
白名单错误类型/code及deadline_elapsed。不读取异常消息/locals,不新建/
取消/等待task,不在控制锁内写日志,诊断失败不替代业务结果。72243该
helper及合成Product25 passed/6.42s,Ruff通过;独立复审已请求,真实
安装带此取证重跑尚未执行,不能据此声明历史启动失败已定位。

该启动取证独立复核无明确P1/P2。deadline_elapsed仅为entry返回后的
观察,不能独立证明故障发生时超时,必须结合原failure/task错误判因。

17155真实带新增取证的admission诊断已退出0,证据
`history-warm-niplz9h1/report.json`(同lmux-history-install.LWJpGM目录),
scratch `/var/tmp/lmux-history-7_zzgmh8`。原任务post_return显示committed=true、
failure=null、prepare/activate/start均done且无error、deadline_elapsed=false;
随后fixed_product_returned=0。报告owner-settled-diagnostic/valid=false,
未复现旧startup_failed,不能推断其历史根因。

37404 AppHost完整47源文件mypy通过(无增量、/dev/null缓存)。96571
AppService/AppServer非live回归751 passed、10 skipped、52 failed/23.82s。
52项均是profile mismatch矩阵夹具未为新增managed/v2 close profile注入
显式ManagedMuxCloseClientV1,在构造函数准入即失败,未进入原握手断言。
已仅补夹具按supports_managed_mux_close注入autospec,并断言不匹配握手
不调用close capability;生产能力准入不变。23046完整该文件191 passed/
3.70s,Ruff通过。其余先前通过项未无故重跑,不宣称重新跑过整个协议套件。

### 收口复审:控制 IO 提交回执与实际完成

三视角复审发现控制 IO 在 submit 返回后才登记,排队后回执丢失可能让
未登记 callable 进入借用依赖。已在原控制 pool 增加 publication gate:
提交异常关闭准入,登记独立 completion receipt 后才放行;receipt 预置
running,不能因取消等待者而变为已取消。关闭路径仍经原串行 IO 锁等待
实际 callable 完成,不增加执行器或清理 owner。

新增提交后抛错零控制副作用、内部 waiter 取消后 close 等待实际完成负测,
并扩展原调度失败用例。首次回归 40 passed、2 failed,原因是诊断故障注入
按 deliver 函数名误命中新控制包装;改名 deliver_control 后,75340 原三文件
test_managed_child / logging / trace 完整复验 42 passed / 11.22s。
修复已交回生命周期视角复核。当前 wheel 的既有安装验证不覆盖本次生产修改。

复审仍待修复 Hosting 关闭 unknown 状态和界面帮助命令不一致;历史首次
startup_failed 尚无根因。共享界面门禁 9284 本轮轮询仍运行,不宣称通过。
AppService/AppServer 源码与测试 Ruff(88384)通过。尚未提交或完成目标。

后续生命周期复核静态确认原控制提交 P1 关闭,另指出旧 receipt 已完成但
携带 BaseException 时重入无法清引用。现已在等待 finally 中仅对 done receipt
清引用,保留未完成 IO;增加 native CancelledError、取消 waiter 后 close 重试
的负测,60428 完整 child 文件 26 passed / 5.27s。

Hosting 关闭 P2 初修:_close_fd 显式接收本次 primary,临时描述符路径分别
记录本次异常,不借用调用者无关的 sys.exception;observer 在关闭 native fd
前锁存 unknown,只有收到成功回执才清除。process 分别记录 observer 和 child
endpoint 的 unknown;spawn 与 close 共用 endpoint 关闭状态,未知关闭不再重试,
其他已知独立句柄仍可关闭。8319 两个完整 observer/process 测试文件 49 passed /
4.93s,Ruff 通过。负测包含外层 except 内真实 close 后抛错、数字 fd 复用保护、
process 二次 close 不清债;原假定关闭异常可重试的夹具已改为实际失回执场景。
两处修复已交回生命周期复核;仍需进一步故障覆盖、安装重冻与最终验收。

复核确认上述两项静态闭环,追加 capture 分配 pidfd 后尚未收养即失败的
相邻 P2。现 process 在 capture 前锁存 adoption unknown,仅成功收养后解除;
未知时仍关闭独立 endpoint,但不发布 handles_closed。测试覆盖真实 capture
分配后失败、临时 pidfd 实际 close 后失回执,并覆盖 cleanup KeyboardInterrupt
保留本次 primary。32101 observer/process/帮助测试 56 passed / 5.29s。
进一步补 socket 实际 close 后失回执、重复调用不得清债的负测。

帮助改为实际 lmux new/ls/attach/close/stop 命令,create --continue 单独说明
原操作恢复;中文指南说明重连有界历史尾窗不删除持久历史。实际 render 断言
精确命令,94469 process/帮助两文件 29 passed / 3.52s,相关 Ruff 通过。
生命周期与 UX 修复均已交回复核。9284 原共享门禁仍在运行,本轮未重启。

生命周期与 UX 复核均确认原发现静态关闭,本轮无新增明确 P1/P2。42328
本次修改的 service/service_process/managed.child 三源文件 mypy 通过。
8035 完整 Hosting/AppHost 离线回归 1583 passed、49 skipped / 164.57s,保留
not live、requires_host_runtime 等离线选择与 --skip-host-runtime。

9284 共享门禁仍未结束:只读核对原 wrapper PID 50273、pytest PID 50484,
后者仍处于 ep_poll,持有原 pytest lease deaaf9b15b1f4464a9e7cdfecaa2a58e;
没有终止、重启或宣称通过。接下来需定位其具体等待用例。根盘剩余约 561 MB,
尚未创建另一套完整安装环境或覆盖旧 wheel,最新生产修改仍需重新冻结验证。

共享门禁挂起定位:39486 独立 loading surface 13 passed / 3.20s,37157
conversation 子集 336 passed、3 deselected / 7.48s,不能替代原门禁。
对已核实的原 pytest PID 50484 单次 SIGINT 后,9284 终态 exit1:704 passed、
8 deselected / 1610.50s,取消中的 mux owned_task 残留,不能算通过。
按原收集顺序定位第705项 test_G17_PICKER_loading_controls_and_cancel_resistant_query_remain_owned。
66657 独立限时复现 exit124;栈处于 asyncio.run 的 _cancel_all_tasks。

夹具添加 finally 释放抗取消查询后,10325 显露真实错误:等待 Ctrl+C 中断超时。
旧用例期待选择弹窗内 Ctrl+C 穿透,而当前 modal 输入合同禁止此操作;不是
已证明的生产清理死锁。现先验证弹窗内不发 interrupt,再退出弹窗,设置真实
running 状态后验证控制槽位。79040 两文件42 passed、1 failed,第二个饱和
控制夹具具有同样过时假设,已同样对齐;未改生产输入规则或降低控制槽位断言。

74038 修正后完整 picker/shared-input 两文件 43 passed / 2.41s。
87754 原共享门禁测试范围重跑中,已越过旧等待点;出现一个帮助旧文案断言
失败,test_G17_EXIT_copy_matches_the_selected_application_lifetime 仍检查
create/list/attach/close/stop。已对齐实际 new 与 create --continue 帮助,68835
完整 settlement 文件 15 passed / 3.39s;87754 尚未终态,不宣称整体通过。

58376 新 wheel 离线构建完成,存于 .artifacts/lmux-final-wheel.IWWosv/
loushang-0.1.0-py3-none-any.whl,SHA256
2b904bec07f9d13c2179da715be0dd07778bd5ec912216ba5bab0e66d59cc607。
原 check_source_wheel 已核对模块清单和全部包字节。独立 measured/observer
安装槽复用原冻结 requirements,41 包通过缓存硬链接安装,未覆盖旧环境;
78163 原 verify_pinned_install 两槽通过,7 个可执行入口、包字节、依赖已核对。
仅此证明安装来源和入口,不是最新行为/性能验收;新 wheel 还未运行真实场景。
创建后根盘剩约521 MB。旧 wheel、环境和失败样本均保留。

87754 原共享范围最终 exit1:994 passed、1 failed、8 deselected / 421.63s。
唯一失败为已记录的旧帮助文案断言,68835 修复后完整文件15项通过;原picker
挂起未再出现。按变更感知规则,不重复未受后续修改影响的994项通过测试;
如实保留原运行失败与针对修复回归,不伪称一次全绿。

最新wheel真实启动诊断已由原采集器启动,97347仍在运行;报告为
.artifacts/lmux-final-wheel.IWWosv/managed-product-admission-diagnostic-kul12waa/report.json。
任务私有 run_case.py 仅组合原 helper_manifest、verify_pinned_install、
private_environment、run_python 与 _g18_native_probe,不新增产品计时机制。
只在原owner返回且前后包/依赖/helper校验相同后发布 owner-settled-diagnostic;
当前未终态,不据启动日志宣布通过。

随后97347终态exit1:最新安装 admission 诊断在 perf 首屏之前失败,前台
planned_creation 后 local_operation_failed;原采集器报告首屏等待超时、
fixed_product_cleanup_failure=RuntimeError、leftovers=True/force_cleanup=False。
scratch /var/tmp/lmux-final-6_3rd3ft,原native.json和报告均保留。生命周期只见
starting → failed(startup_failed) → stopping,尚无 stopped 回执。不能把旧wheel
成功诊断作为本次通过,也不能未经根因核实归因于本次关闭修复或机器负载。
暂停新增采集,下一步读取阶段诊断并核实该实例原owner的清理情况。

只读检查本次前台64096/后台64208均已不存在;这不补足 stopped/application
cleanup 回执。原 boundary-64208-e9cdfaa4586d4886ba98cace046a9cf1.jsonl 只有
fixed_product_selected,说明 post-return 诊断未获得执行机会,不能推断 prepare
具体错误或期限。测试专用 observe_startup 现增加原 _drive 失败边界快照,
在原 close 之前记录原任务状态/脱敏错误类型;不创建任务、不重试、不更改预算,
原方法恢复和诊断sink失败不替换原异常均有负测。45042 诊断与synthetic完整
两文件27 passed / 5.76s,Ruff通过。使用同wheel新私有根发起一次增强诊断复现,
不把复现成功与否当作先前失败根因,也不进入正式性能采样。

99381增强诊断终态exit0:报告 managed-product-admission-diagnostic-o3ipt44y/
report.json,scratch /var/tmp/lmux-final-yxf3biiv。原owner已返回,前后helper和
两安装槽字节/依赖一致,status=owner-settled-diagnostic/valid=false。当前帧唯一
回复之后detach,后验同Session仅一USER/ASSISTANT且idle;PTY退出0、termios/
cursor/paste恢复、reader结算、无fallback,精确实例098ade3f8990dbbf4ab01b83a681deb1
stop=stopped。startup_post_return显示committed=true、各阶段done无error、
deadline_elapsed=false。未复现旧错误,故仍不声称旧startup_failed根因已解决。
启动诊断原始visible_reply约1.385s、fixed-entry累计约16.536s;受诊断与单样本
限制,不是正式性能结论。随后在同wheel新私有根启动真实PTY断连自然完成用例。

79809原断连采集器已完整返回,但任务私有run_case.py错误期待
fixed_product_first_reply,实际为fixed_product_natural_completion,导致汇总
AssertionError、未执行后验安装校验。保留ksd_bz0y/report.json为failed,不改写。
已同步修正工具批准/拒绝与断连中断的精确报告键,未修改生产或原采集器。

45377修正后完整重验exit0:managed-product-hangup-natural-completion-pxzd3jl0/
report.json,scratch /var/tmp/lmux-final-t44godj9,owner-settled-diagnostic,
valid=false;前后helper/安装一致。真实PTY master关闭后旧客户端自主退出120,
client_exit_clean=false、模式恢复不可观察,未伪称正常detach。原producer有
started→gate_released→final_emitted→settled,异cwd原lmux attach取得同Session
结果并完成下一轮,重连终端退出0、模式/光标/paste恢复、reader结算、fallback=false。
精确实例21fa3e08f1b971343c80538233b5cc90 stop=stopped。不是完整SSH协议验收
或正式性能结论,旧startup_failed仍未解释。

为控制磁盘,已核对并删除三次已结束采集kul12waa/o3ipt44y/ksd_bz0y下共五个
measured-pyc/observer-pyc目录(约121MB),仅含可再生.pyc;未删除报告、wheel、
安装或Session数据,未触碰活动采集目录。回收后根盘约441MB可用。

75672最新wheel首次工具批准诊断exit0:managed-product-tool-approval-l_748br_/
report.json,scratch /var/tmp/lmux-final-j61t5obx,owner-settled-diagnostic、
valid=false。原采集器核对批准前零效果、详情展示与批准后恰一次工具效果,
tool_call_id=lmux-call-1、tool_execution_count=1。精确实例
5f06863238e620e1634b2bd4c2cdec15 stop=stopped;PTY退出0、模式/光标/paste恢复、
reader结算、fallback=false。前后helper与两安装槽核验一致。随后启动工具拒绝
负向场景,尚未结果;此单场景成功仍不替代正式first-use组合或配对验收。

89675拒绝路径终态exit0:managed-product-tool-denial-1m5x1w5b/report.json,
scratch /var/tmp/lmux-final-6mik8if5,owner-settled-diagnostic、valid=false。
原真实拒绝交互后tool_execution_count=0,后验同Session idle,精确实例
c361c6235d8cd1b2068fef5901a8e4c3 stop=stopped;PTY退出0、模式/光标/paste恢复、
reader结算、fallback=false,前后helper与两安装槽一致。
随后64105启动最新wheel真实PTY断连、中断原producer并完成下一轮用例,报告
managed-product-hangup-interrupt-next-turn-y5qcspkv/report.json,尚未终态。

64105终态exit0:上述report与scratch /var/tmp/lmux-final-y4xz9vom,
owner-settled-diagnostic、valid=false。原producer确认结算,next_turn包含
中断前后producer事实和下一轮唯一回复后验;异cwd attach退出0、模式/光标/
paste恢复、reader结算、fallback=false。原PTY突然断连客户端退出120,模式
恢复不可观察,如实保留;精确实例74384c5e64692be27033dec85cbc25e8 stopped,
前后helper与两安装槽一致。随后17138在同wheel启动history-restore,报告
managed-product-history-restore-7g_392vk/report.json,尚未结果。

根盘降至296MB时,仅回收已完成批准l_748br_、拒绝1m5x1w5b两报告目录的
四个measured-pyc/observer-pyc;预检仅含.pyc,均可再生。安装、报告和原会话
保留;未清理正在运行的历史采集,也未据磁盘压力降低历史规模。

17138最新wheel长历史恢复终态exit0,报告7g_392vk/report.json,scratch
/var/tmp/lmux-final-3dw9mxxt,owner-settled-diagnostic/valid=false。原公开种子
128轮、256消息、263680文本字节,恢复后canonical摘要
00e1c01bb0a4603b94f5fbd70ea802f24a9389471893e5883310ba7c0c0fbb41,
精确恢复实例10ddb4b386f0dce1cc101138c151ecca stop=stopped。前后helper和两安装
槽一致。完整原case包含暖attach、旧实例干净停止、新实例加载与当前尾窗验证;
未将此单次诊断提升为正式性能样本。

随后通过任务私有run_first_use.py调用原measure_g18_native.run_sample,
启动最新wheel单次first-use组合预验;原complete_managed_product与
validate_observation照常执行,仅defer_validation保留valid=false,不冒充
不可变来源正式配对。前后安装/helper校验仍必须完成,尚未结果。

64448最新first-use组合预验exit0:first-use-preflight-oev447nq/report.json,
scratch /var/tmp/lmux-first-use-3xktan0l,validated-composition-preflight,报告与
样本valid均false。原完整八指标/身份/顺序/终端/效果/物理清理校验通过;三个
fresh子场景reply/approval/interrupt均observed,各自精确stopped,共四个终端。
外层owner起止3576053.875521905→3576147.560589302,前后helper/安装一致。
原始八指标秒:reply1.37475、fixed-entry累计15.33229、approval_pending0.91156、
details0.09986、approved_reply0.37030、interrupt至idle+producer0.17037、
next_reply0.43617、interrupt至next_reply0.60654。单次预验,不是均值或性能提升。
准备任务专用不可变源码快照用于原正式采集来源门禁;不提交或改写lane HEAD。

1547快照来源核验通过:.artifacts/lmux-evidence-source.uWyAgm,独立证据提交
6eeb9aa964e3f3e25720cc828936590126da3067(不是lane交付提交)。原helper_manifest
逐文件内容/权限核验与lane相同;require_clean_product通过,原
verify_wheel_at_commit验证1393包文件、project/lock及wheel2b904bec一致。
lane仍在harness/lmux-managed-service且未交付提交。创建后根盘约221MB,正式
固定槽采集前需核对空间与原slot的复制策略,不能无视容量继续堆叠环境。

长历史正式比较缺口已获架构视角只读建议,生命周期/UX设计复核已请求:
warm两个指标history_frame/history_completion,restore仅累计restored_history_frame;
复用原owner,补逐代start/attach/stop和seed/canonical的可审计时间与身份回执,
collector独立校验后才可晋级。当前仅设计复核,未宣称正式长历史接线完成。

生命周期/UX复核同意原框架最小增量,并补全串行时序、行式start区别与
canonical读取身份约束;已写入性能plan正式晋级增补。首个实现只补原
observed_terminal的独立line_settlements输出,在原foreground/reader真实结算
后记录PID/argv/cwd/exit/termios/reader/fallback;与TUI settlements互斥,不
伪造cursor/paste标记。restore的start使用该回执列表。
63444行式终端与restore两完整文件20 passed / 6.36s,含真实PTY和exit/reader/
fallback/modes/close失败不发布回执的负测;Ruff通过。helper变更尚未进入此前
6eeb9aa证据快照,正式采集须更新冻结来源;生产wheel字节未改。

下一增量补可审计时序与身份:read_history在原公开只读调用与完整摘要验证
成功后才发布canonical_read(精确root/path/workspace、完整五字段Session、
started/completed和canonical),不另做事后stat冒充原读取身份。warm与restore
均保存此回执;新实例真实spawn不得早于旧stop/local-owner结算及旧canonical
读取完成。新代保存已认证fixed_product_target及authenticated_at;原seed观察
返回后记录connection_settled_at,仍由原连接/journal/namespace关闭路径负责。
67484 canonical/restore/product-probe/read-observer四完整文件169 passed /
9.57s,包含canonical读取在stop前、完成时间倒序禁止进入新代及失败不发布
读取回执的负测;Ruff通过。正式collector独立validator/比较接线仍待实现,
不能仅凭helper新字段晋级样本。

原collector新增独立validate_managed_history_canonical子校验,固定核对128轮/
256消息/263680字节摘要、完整五字段身份、实际公开读取root/path/workspace,
以及外部owner结算→读取开始/结束→后续阶段的有限非负时间顺序。严格字段
清单与数值类型拒绝额外/缺失回执、浮点消息数及bool/NaN/巨整数时间。
39478独立回执负测与原Product计时回归97 passed / 1.52s;Ruff及diff-check
通过。该子校验尚未接入整体history样本晋级,不改变valid/checkpoint规则;
终端、认证、尾窗及两代outer结算的整体接线仍需完成后才能正式采集。

计时子校验validate_managed_history_timings复用原精确duration/有序区间校验,
绑定warm帧起点到真实attach spawn;restore累计值必须从真实service spawn
到同一个历史帧终点,认证位于service spawn与attach spawn之间。不能用
attach起点或相加分段规避启动/认证间隙;恢复后的首次补全仍须正确且在
历史帧之后。72955三个子校验回归161 passed / 1.94s;54820原采集器完整
回归247 passed、4 skipped / 38.36s。Ruff与diff-check通过。仍未开放正式
history case晋级;这两项子校验不是完整生命周期或性能验收证明。

新增seed独立子校验:128轮序号/读次数、Ack→idle、40秒单轮与600秒总seed
严格界限,初始终端结算→seed→detach→connection结算→warm spawn顺序。
35733相关三个子校验187 passed / 1.93s。三视角子集复审:架构与UX无新增
P1/P2;生命周期指出仅排序未独立证明attach/detach期限。已让原helper记录
实际dispatch与deadline,validator核对min(原deadline,dispatch+30),并增加
detached=1000而后续顺延的拒绝测试。64223相关83 passed / 1.73s。
原verify总deadline来源与outer整体绑定尚待接线,未宣称该P2整体关闭。
另补尾窗确认confirmed_at及原连接返回后的connection_settled_at,8503原
read-observer/history-attach两文件33 passed / 5.55s;Ruff与diff-check通过。
所有新增仍为完整history validator的组成部分,未开放formal/checkpoint晋级。

期限P2后续闭环:原_managed_observation在实际verify准入冻结started+660
deadline,超期回调返回抛TimeoutError并走原connection清理;成功才保存
verification起止/截止。seed validator强制引用同一deadline,校验初始终端
结算→verify准入→attach/seed/detach→verify完成→connection结算→计时spawn。
36730相关126 passed / 6.38s;94813迟到回调定向1 passed / 6.34s(只替换
observer时钟,未更改asyncio时钟);Ruff、diff-check通过。生命周期复核确认
该期限P2已闭环、无新增P1/P2;这是子合同结论,不覆盖整体sample/outer接线。

终端子校验validate_managed_history_terminals按真实清单区分warm两个TUI与
restored一个行式start加一个TUI,绑定每次spawn的PID/argv/cwd、退出0、
termios/reader/无fallback与有序结算;行式只接受presentation=line,不伪造
cursor/paste标记。59639新旧终端校验回归114 passed / 1.59s,Ruff与
diff-check通过。只读重验旧安装证据7g_392vk中的warm代两个真实终端回执
也通过;原报告保持valid=False,不修改旧证据或据此提升正式样本。

尾窗子校验validate_managed_history_confirmation绑定原target六字段、单一member、
完整Session五字段、idle、确认及connection结算时间;独立固定15条尾窗
(1条omitted STATUS+121..127轮14条消息)的有序内容摘要,不复用生产投影
作为预期,也不冒充全256条canonical。82502尾窗/canonical回归101 passed /
1.40s,Ruff与diff-check通过。整体接线下一步需把这些子校验与各代native、
精确stop及原outer回执串联,禁止仅凭尾窗、计时或某个子集成功晋级样本。

暖代组合validate_managed_history_warm已连接精确字段清单、seed/verification、
两次终端、原native四阶段、完整Session尾窗确认、精确stop及stop后canonical;
85490组合正负测20 passed / 1.18s。架构定点复核无新增P1/P2,提醒outer
envelope应由可信组合层显式投影,不能整份report忽略未知字段接受。
4128最新wheel真实安装warm诊断退出0,报告managed-product-history-warm-zyxngfy2/
report.json,scratch /var/tmp/lmux-final-g9wr6bap。安装及helpers前后相同、
原outer结算后,当前组合validator只读复验通过:128轮/256条/263680字节
固定canonical一致,instance b4cba82141cb6209c815d8cfaf50fbf9精确stopped。
单次原始history_frame=13.521948030218482s、completion=0.07102343672886491s;
报告仍owner-settled-diagnostic、valid=False。不是正式配对或性能提升证明。
未修改旧报告。恢复代及正式dispatch/outer/checkpoint接线仍待完成。

恢复代组合及正式接线完成:99231 warm/restore组合42 passed / 1.74s;
90601最新安装restore诊断退出0(managed-product-history-restore-90tp2up9,
scratch /var/tmp/lmux-final-ps1xqmk4),两代分别精确停止、原owner结算、
安装/helper前后相同。新组合validator通过,原累计18.454965352080762s;
old instance 992b3426573af6faab1fb1697dc48207,new 7ce4b69106e28502f47cbadd5fe5d820。
报告仍valid=False,不作为配对或性能提升结论。

正式两个history case已显式opt-in:原默认七场景不变,warm两指标/restore
一指标使用原20对统计策略。complete_managed_history仅在原run_python成功
返回后追加outer事实,严格envelope与全部代际回执通过后派生指标;原raw
回执预填指标或owner、失败/取消留下完整文件均不能晋级。外层预算1380/
1980秒=原verify660+每代terminal/auth/stop/read保留600+outer保留120,
不延长内部操作期限。run_sample延迟晋级与原固定槽/来源后验流程保持。
18528曾暴露字段集合原地扩展污染旧场景;已改为独立集合并补不变性回归。
89871受影响回归110 passed / 2.97s;74284原采集器完整/新入口回归305 passed、
4 skipped / 42.66s,Ruff与diff-check通过。上述最新warm/restore实际报告只读
经过新complete+validate_observation完整路径均通过,未改报告或提升valid。
三视角正式接线复核无剩余P1/P2;原性能文档误称Mux/member为进程内ID的P2
已依据continuity持久编码/原收养修正并复核关闭。正式配对仍待更新冻结来源
后执行,未将功能/回执验证等同于性能验收。

正式配对准备:本轮warm zyxngfy2及restore90tp2up9原进程已退出0,仅清理
其measured-pyc/observer-pyc内可重建.pyc约100MB;报告、Session、wheel及
安装均保留。冻结目录.artifacts/lmux-history-frozen.UTdPIJ独立Git快照
05701143bfaf29195d1ed63be75b33ad0e11b641(不是lane交付提交)。5257原来源
验证通过:1441个helper与lane逐字相同,1393个package文件仍对应最新wheel
2b904bec07f9d13c2179da715be0dd07778bd5ec912216ba5bab0e66d59cc607,产品树未变。
另建reference-b独立venv,离线hash锁定安装并以hardlink复用缓存,19391原
verify_pinned_install确认Python3.11.15、41依赖与7入口;不改用户uv tool。
磁盘余量约184MB,正式固定槽及可恢复A/A采集尚未启动,先确保路径长度与
空间容量合适;没有正式性能结果或lane提交。

固定槽A/A已启动:冻结副本为避免可执行路径过长,移动到
/var/tmp/lmux-paired.hTF3Iy/repo,commit仍05701143;7147来源/helper复验通过。
仅链接复用本任务uv缓存,未改冻结helper。另回收已结束pxzd3jl0/y5qcspkv
断连诊断的.pyc约100MB,原始报告/Session/安装保留。
5268原collector运行中,output /var/tmp/lmux-paired.hTF3Iy/aa-history-warm;
--fixed-slot --cache-mode warm --cases managed-product-history-warm --blocks 2
--pairs-per-block 10 --checkpoint --pause-after 2。两个slot构建均complete,
首个block0/pair-1/side b预热running、valid=False;comparison尚not-evaluated。
后续仅在原进程退出且checkpoint确认安全暂停后以--resume续采,不另起替代
campaign,也不把预热或部分样本当20对正式结论。当前磁盘余量约2.6GB。

5268已终止exit1,首个预热失败,非安全暂停:aa-history-warm/report.json
status=failed、slot.failed=true、comparison=not-evaluated,不能--resume。
原first-screen _see期限30秒;frontend90618真实spawn3580554.601905537,
child90734 fixed_product_selected3580587.022267429(约32.42秒后)、
fixed_product_returned3580588.060850363/status0。私有lifecycle同一instance
99f3ceadd70a6f23f85743b1aacb7c47仅记录stopping/stopped;前端尚未认证target,
helper fallback报RuntimeError、原outer记录leftovers,故仍是无效采集,不能
用后来stopped改写原owner失败。
失败现场frontend schedstat记录约8.57秒CPU与10.75秒调度等待;CPU pressure
some avg10=86.21,IO some=45.67,memory some=14.20。当前只读检查见其他
loushang活动进程及约2.8GB swap占用,不擅自停止其他任务。证据将超时定位
到Product选择之前的启动阶段,但尚不能仅凭压力判定历史startup_failed根因。
保留完整失败campaign,不放宽30秒期限、不覆盖失败为新一轮成功;先诊断
资源/启动阶段,再决定新的独立采集。正式性能验证未完成。

启动依赖边界修复:managed_process 不再在模块导入时加载 managed_local,
改在真实 child 的原 try 内、bootstrap 构造和 15 秒 admission 预算之前导入。
已接管 endpoint 的 finally 保持不变;请求构造、argv、环境冻结与安全检查不变。
synthetic Product 改为 patch 实际 managed_local 构造符号并在 finally 恢复。
4016 两文件回归 36 passed / 11.03s,包括 fresh 前端/request 后台导入隔离、
导入失败关闭 endpoint、正常/异常 synthetic 恢复;Ruff 通过,68555 targeted
mypy 通过。架构、生命周期、测试/用户行为三视角限定复审无新增 P1/P2。
这些证据仅证明边界与失败清理,不证明原 30 秒冷启动超时已修复。

77204 新候选 wheel 离线构建完成:.artifacts/lmux-lazy-wheel.k30n4c/
loushang-0.1.0-py3-none-any.whl,SHA256
70d6d1bdda17a57814b9c67f546ef784997fd1425ec446cfecf05e06cbfa5ea3。
41770 原 check_source_wheel 核对包模块清单及全部字节通过。独立 measured
安装槽沿用 Python 3.11.15 和原 hash 锁定的 40 项依赖,离线硬链接安装;
旧 wheel、冻结来源、失败 campaign 均未改写。候选真实行为/性能尚待验证,
当前没有正式性能达标结论或本轮交付提交。

51426 新候选 pristine 安装 admission 诊断退出0:
.artifacts/lmux-lazy-wheel.k30n4c/managed-product-admission-diagnostic-pzijyq38/
report.json,scratch /var/tmp/lmux-final-imfm6s7c。原 source/wheel、measured/
observer 安装和 helper 前后校验相同;原 owner 正常结算,总诊断40.284秒。
固定测试 Product 首次启动至回复可见19.403240702115秒,发送至回复可见
1.3726405892521143秒;instance a09bd68ed8161c194bb6dea83818f584 已精确停止。
本次没有触发原30秒首屏期限。报告仍 owner-settled-diagnostic、valid=False,
不是正式配对、不证明改善百分比或冷启动超时根因已排除;原失败仍保留。

35483 新候选 history-warm 诊断退出0:managed-product-history-warm-5uhow0ef/
report.json,scratch /var/tmp/lmux-final-keyft81s。原 owner 81.831秒正常结算,
安装和 helper 前后相同;原 complete_managed_history + validate_observation
只读完整复验通过,未改报告 valid=False。128轮历史帧10.558838586788625秒、
补全0.17382399225607514秒;instance a15f35c773972ccfebcd7ef143e21432 精确停止。
仅为本候选诊断成功,不与旧单次数字相除作为正式性能改善结论。

91016 新候选 history-restore 诊断退出0:managed-product-history-restore-65zzfk58/
report.json,scratch /var/tmp/lmux-final-scvvwblz。原 owner 65.975秒正常结算;
安装和 helper 前后相同。91433 通过原 complete_managed_history 和
validate_observation 只读完整复验,恢复累计历史帧12.084731846116483秒。
仍为 valid=False 的单次诊断,不是正式 A/A 或 A/B。三个新候选安装诊断均
已结束,无留在运行中的本轮采集。随后才编辑架构预算 helper,精确补记已
三视角复核的 child-only import 净增3行,不扩大模块分区或通用豁免。
28106 架构预算完整文件2 passed / 0.61s,Ruff通过。后续正式采集必须重新
冻结包含此 helper 变更的来源,不能复用旧快照声称与当前 helper 一致。

新正式采集准备:原离线 uv cache 已缺失(磁盘余量同期增加),reference-b
首次离线安装按锁失败;随后仅按原 requirements 的精确版本及 SHA256 联网
补回40项依赖,不升级。70858 本地新 wheel 安装完成,52360 原 pinned-install
复验通过:Python3.11.15、41包及7入口。已有 measured/observer 未重装。

独立冻结目录 /var/tmp/lmux-lazy-paired.JK8DMb/repo,快照提交
82a936ce8cd1b35a3005048d5a77afbff8985c28(不是 harness 交付提交)。16190 原
verify_wheel_at_commit 通过:1393包文件对应候选70d6d1bd wheel,产品树
dd57395b7994f33d8b51fc0d64b85cef7413f565;1441 helper 与 lane 完全一致。
只在 ignored artifacts 下链接原任务缓存。长历史 warm A/A 已申请启动,
output /var/tmp/lmux-lazy-paired.JK8DMb/aa-history-warm,原2块各10对、
--fixed-slot --cache-mode warm --checkpoint --pause-after 2;尚无正式结果。

71047 新 A/A 第一段退出0且安全暂停:report.status=paused、checkpoint.phase=
paused,slot.busy=false、failed=false。block0 两侧各一条预热 complete/valid=True,
共2条;原后验和检查点提交完成。首个冷预热本次已走通,但尚无正式 measured
样本,comparison=not-evaluated;不宣称稳定性或优化达标。后续只从此原
campaign 的已提交 checkpoint 续采,不重建安装槽或替换失败样本。

### 110167 长历史 warm campaign 审计:安全暂停未保持,不可 --resume

上文 "第一段退出0且安全暂停" 只描述 segment 0,且该记录写于 13:07:56。
此后又发生一次**未记录的第二次续采**,它没有回到安全暂停而是中途死亡。
只读审计(未执行 --resume,未改写任何 report/checkpoint/证据)结论如下。

时间线(同目录 mtime 与 /proc/uptime 重建):

- 13:04:59 建立 checkpoint.lock;13:05:05 segment 0 起,13:07:30 安全暂停。
  report.status=paused、checkpoint.phase=paused、next_index=2,2条预热 valid=True。
- 13:09:01.522811 segment 1 起(report.segments[1]),即一次 --resume。
  `begin()` 把 phase 置回 inflight、status 置回 running,segmented_acceptance.
  eligible_for_automatic_acceptance=false,并新增第3个观测(block0/pair0/side a)。
- 13:09:34.8 建 sample-3 scratch;13:09:38.9 起真实 PTY/observer owner;
  13:09:42.5 写 pytest-controller-result `{"code": 130, "force_cleanup": false}`。
- 13:09:38.9 之后采集器**未再结算**:report.json 最后写于 13:09:38.883,
  checkpoint.json 最后写于 13:09:01.464。第3条样本停在中途。

证据一致性与资源完整(均只读复验,全部通过):

- 源/轮子/身份一致:report.source_commit=82a936ce8cd1b35a3005048d5a77afbff8985c28,
  两侧 wheel_sha256=70d6d1bdda17a57814b9c67f546ef784997fd1425ec446cfecf05e06cbfa5ea3,
  runner_sha256=9b3d4dd5... 与冻结 repo、本 lane 的 scripts/dev 完全一致;冻结 repo
  工作树 clean。
- checkpoint 记录的 output_identity / lock_identity / scratch_identity 与实际
  dev:ino 完全一致(aa-history-warm=64770:1108328、checkpoint.lock=64770:1108329、
  scratch=64770:1108331);machine(boot_id/node/platform/python/interpreter/
  affinity/uid)与当前记录一致。
- checkpoint.evidence 全部 6 项 SHA256 复验通过;resources.trees 全部 6 棵
  (measured、reference-b、observer、slot active、slot b、observer-bytecode)
  tree_manifest 复验**无差异**;scratch identity 一致;InstallationSlot.reopen()
  只读试开成功(active=a、busy=false、failed=false)。

不可安全恢复的硬阻断(`Campaign.__enter__` resume 路径按序判定):

1. `checkpoint.phase` 当前为 **inflight**,不是 paused -- 直接 `ValueError:
   checkpoint is not a compatible safe pause`(_g18_checkpoint.py:224-228)。
2. `report.status` 当前为 **running**,不是 paused(同一门禁亦拒绝非 paused report)。
3. `report_sha256` 记录值 `87fdb541d1a6efdc...` 与实际 report.json
   `48f92fd2b321697a...` **不匹配**,即 report/checkpoint 不是同一次提交。
4. `validate_prefix()`(_g18_checkpoint.py:134-152)要求前缀每条样本
   status=complete、valid=True 且 failure 为空;第3条为 status=running、valid=false,
   因此 `checkpoint contains an incomplete or non-prefix observation`。
5. cursor 不一致:checkpoint.next_index=2,而 report.samples 已有 3 条,
   `checkpoint cursor mismatch`。

一个已用真实门禁做的**非破坏性**验证确认:直接以 `resume=True` 进入
`Campaign`(不调用 `begin()`,因此不写任何字节)在第一条即被拒
`ValueError: checkpoint is not a compatible safe pause`。复验前后 checkpoint.json/
report.json 的 SHA256 逐字节不变(05297a77...、48f92fd2...)。

另有两点必须记录、不得掩盖:

- **未结算 owner 残留**:PID 102482(PPID=1,已 reparent 到 init)是 13:09:38
  由该次死亡续采启动的 `scripts/dev/_evidence_process.py` observer owner,
  arg 仍指向 sample-3/native.json(该文件不存在)、slot active、observer-bytecode。
  它从不存在的 stdin pipe 读取,状态 Ss、wchan=futex_do_wait,已存活约44小时,
  CPU 13102/3241 ticks。它不持 flock(`/proc/locks` 无其条目)、不占任何
  campaign/slot 文件 fd,因此**不是**当前 resume 被拒的原因,但它是本次中断的
  真实未结算证据,按证据合同必须保留而不删除、不重写。
- **segmented_acceptance 语义**:一旦发生任何 --resume,report 会被永久标记
  `eligible_for_automatic_acceptance=false`,理由为 "resumed segments require
  separately declared calibration and environment audit"(_g18_checkpoint.py:301-307)。
  但 `_g18_comparison.py` 的 verdict **不读取** 该字段:`_compare()` 只看
  20 对/warmup 是否齐全、valid/failure、配对、指标有限与 A/A 稳定性。
  因此"comparison=pass"与"可作为正式验收"并不等价;即使将来把本 campaign
  续完,也只能得到 descriptive 结果,不能据此宣布性能通过。

按验收计划"只从已提交 checkpoint 续采"的前提已不成立,本轮**不执行 --resume**,
停在诊断阶段,不重建安装槽、不替换失败样本、不改写 report/checkpoint。
`managed-product-history-warm` 与 `managed-product-history-restore` 均无正式
结果:无 20 对 measured 样本、无 comparison verdict。

下一次独立采集所需的清理与修复方案(均待人工确认后执行,本轮未做):

1. 保留 `/var/tmp/lmux-lazy-paired.JK8DMb/aa-history-warm` 原样作为失败证据;
   新采集必须用**新 output 目录**,不能复用、清理或覆盖本目录
   (`Campaign.__enter__` 非 resume 路径要求 output 目录不存在)。
2. 先审计并结算 PID 102482:确认它无在途写、无 flock 后,经其原 owner 路径
   终止并记录事实;不得以 kill -9 掩盖未结算状态,也不得把它当作其他
   loushang 任务处理。
3. 仍以冻结源 `/var/tmp/lmux-lazy-paired.JK8DMb/repo`
   (82a936ce8cd1b35a3005048d5a77afbff8985c28) 与候选 wheel
   `70d6d1bdda17a57814b9c67f546ef784997fd1425ec446cfecf05e06cbfa5ea3` 为准;
   若需要新的 slot/scratch,走 collector 自身的 provision 路径新建,
   不复用 `g18-slot-oddi551g`(其 active 仍停在旧次的 a 面)。
4. ~~离线 uv cache 已失效~~ **此条已自查驳回,不成立**。
   `repo/.artifacts/g18-design/uv-cache` 是一个 **symlink**,指向
   `harness/.artifacts/g18-design/uv-cache`;后者完好(196M、6354 文件,
   `wheels-v6`/`archive-v0`/`simple-v20` 齐备)。此前"0 文件"是
   `du`/`find` 默认不跟随符号链接造成的**误判**,不是 cache 真丢失。
   已验证离线可重建:用 collector 自己的三条命令(`uv venv` →
   `uv pip install --require-hashes --no-deps -r requirements.txt` →
   `uv pip install --no-deps <wheel>`),全程 `--offline`,**均退出0**;
   并以 `verify_pinned_install` 实探针比对,得到 python=
   3.11.15 (main, Mar 10 2026, 18:16:52) [Clang 21.1.4]、41 依赖、
   7 入口,与原 report.installations.a **逐字段一致**。
   因此无需联网补回,也**不需要**重建 cache;采集前只做一次离线 dry-run 即可。
5. 明确冻结分段策略:若确实需要暂停,必须在同一 segment 内一路采完同一
   A/A 的 2×10 对,避免跨越 A/B 面或改变 seed 年龄;并把
   `eligible_for_automatic_acceptance` 的说明与正式 verdict 分开报告。
6. 每条样本仍须独立满足:真实 PTY、attach/detach、canonical history、
   精确 stop 三事实、原 owner 结算,以及 warm 的 128 轮/256 消息/263680 字节/
   固定 SHA256 与异 cwd viewport 校验、restore 的 instance/native identity
   确实换代。任何身份错配、摘要错配、历史截断、旧回执串用或晚到清理失败,
   一律使样本无效并保留证据。

### 110445 长历史正式采集结果:warm 结构完整但 comparison=inconclusive;restore 在样本27失败

审计后按下文修正案重开两次**单段不暂停**采集(新 output 目录、无
`--checkpoint`/`--pause-after`),仍用同一冻结源
82a936ce8cd1b35a3005048d5a77afbff8985c28 与候选 wheel
70d6d1bdda17a57814b9c67f546ef784997fd1425ec446cfecf05e06cbfa5ea3。
两者都不含 `segments`/`segmented_acceptance`,即**确认没有发生任何 --resume**,
不受"续采需另行校准审计"限制。

**warm:`/var/tmp/lmux-lazy-paired.JK8DMb/aa-history-warm-r1`**

采集完整:44 行 = 2块×(1预热+10对)×2侧,40 measured + 4 预热,
全部 status=complete、valid=True,0 失败。用冻结 runner 的
`validate_observation`(先按 `complete_managed_history` 语义补记原 owner 的
`outer_settlement` 与派生 milestones)逐样本复验:**44/44 通过**。

已满足的正式事实:

- canonical 全史:全部 40 条 measured 样本一致为 `lmux-history-128x2048/v1`、
  128 轮、256 记录、263680 字节、SHA256
  `00e1c01bb0a4603b94f5fbd70ea802f24a9389471893e5883310ba7c0c0fbb41`。
- 异 cwd attach 当前 viewport:40/40 精确通过 `validate_history_window(...,127)`,
  即与 Product 尾窗逐字节一致;末轮含 Markdown 二级标题 `## History 0127`、
  列表项、`text` 代码块及唯一尾标记 `LMUX_HISTORY_0127_END`。不是空壳 footer,
  也不是 Markdown 退化原文。有界尾窗(15 条)是设计行为,非历史截断。
- 每样本含完整 Session 五字段 scope 身份、target 六字段、detach/connection
  结算、精确 stop 三事实、原 owner 结算与外层结算。
- 采集期间无其他采集器;load_before 均值 1.56(1 vCPU)。

**但 comparison verdict = `inconclusive`,不是 pass**(`history_frame_seconds`
单独为 `pass`,improvement -2.4%、回归上限 0.17s,两侧 stable)。判为
inconclusive 的是 `history_completion_seconds`:

| 组 | median | MAD | 上限 max(median/10, 1/100) | 结论 |
| --- | --- | --- | --- | --- |
| a block0 | 89.53 ms | 14.17 ms | 10.00 ms | 超 4.17 ms |
| a block1 | 83.96 ms | 6.41 ms | 10.00 ms | 通过 |
| b block0 | 77.73 ms | 8.19 ms | 10.00 ms | 通过 |
| b block1 | 73.63 ms | 10.51 ms | 10.00 ms | 超 0.51 ms |

该指标量级仅 74-90 ms,而规则对它的绝对下限是 **10 ms**(`median/10` 只在
median > 100 ms 时才超过该下限),因此两组在其量级的自然抖动下越界
(0.51-4.17 ms)。对照同一批数据的 `history_frame_seconds` 量级 1.7-1.8 s,
上限为 173-180 ms,四组全部稳定通过。**判定按原规则原样执行,未放宽阈值、
未剔除样本、未改写 report**;本 campaign 的结论就是 inconclusive。

**必须避免一个错误的"修复":把 10 ms 下限拿掉并不能让它变 pass。**实测
将规则换成纯相对上限(`mad ≤ median/10`)后:

| 组 | MAD | 现上限 | 纯相对上限 | 纯相对下结论 |
| --- | --- | --- | --- | --- |
| a block0 | 14.17 ms | 10.00 ms | 8.95 ms | **仍越界** |
| b block1 | 10.51 ms | 10.00 ms | 7.36 ms | **仍越界** |

即四个组里有三个在纯相对规则下同样越界。因此该不稳定是**指标本身的真实
抖动**,不是绝对下限造成的假阴性;"降低/取消下限"不构成合格修复。
是否需要为该毫秒级指标另行评审校准(而不是在本次结果上放宽),超出本轮范围,
且不得用"环境噪声"作为宣布 pass 的理由。

**restore:`/var/tmp/lmux-lazy-paired.JK8DMb/aa-history-restore-r1`**

前 26 个样本(含 4 预热)全部 complete/valid=True,随后在**样本27**(block1
pair1 side a)失败并终止:report.status=failed、该行 valid=False、
comparison=not-evaluated。失败按原合同**原样保留、未改写、未替换**。

根因取证(只读):

- 失败点在第一代 `probe.first_reply` 的 `_see(driver, "perf |")` 首屏等待
  超时(30s 内未出现);前台 `lmux new -s perf` 随后 exit 1,stderr 为
  `local_operation_failed`(`coding/cli/mux.py` 的兜底分支)。
- 生命周期日志只有 `starting → failed(startup_failed) → stopping → stopped`,
  即应用自身启动预算内未提交,属 **`startup_failed`**。
- registry 该实例 `phase=aborting`、`stop_requested=1`、
  `process_exited=0`、`application_cleanup_completed=1`、
  `process_scope_settled=0`:stop 三事实**不完整(2/3 不成立)**,
  故该样本即便想用也不合格。
- observer 边界记录 `fixed_product_selected → fixed_product_returned(status=1)`,
  fallback 清理抛 RuntimeError、`leftovers=True`、`force_cleanup=False`。
- 失败实例的原生 pid 173367 已不存在,无人持有该 sample-27 的任何 fd,
  槽 receipt 为 `busy=false`/`failed=true`。未见活动残留进程。

必须如实记录、不得掩盖的两点:

1. 该 `startup_failed` 是本仓库**已有记录、且此前明确"仍未解释"**的签名
   (见上文 admission 诊断与"旧 startup_failed 仍未解释"各条)。
   本轮**不能**声称已定位根因,也不能把它记成关闭修复之后的回归。
2. 采集期间机器上存在**非本任务启动**的并发负载:`tmux new -s loushang`
   会话于 10:58:25 起、其 `loushang --resume` 于 10:58:34 起持续占用约
   48-58% CPU(1 vCPU 机器)。失败样本27 落在 11:00:06-11:00:44,
   与该负载时间重叠。该进程非本任务所有,**未触碰、未停止**。
   但必须如实指出这与"纯负载致因"相抵触的一面:**样本25、26 在该负载已
   启用的情况下分别于 10:58:53(+19s)与 11:00:00(+86s)成功完成**,
   只有样本27(+130s)失败。因此不能声称"有该负载就必然失败",也不能把
   时间重叠当作已证实的根因;但仅 2 个样本也不足以排除负载贡献。
   该负载不能作为宣布样本有效或无效的依据,不能用来解释或推诿
   `startup_failed` 本身。

warm 侧无此负载(09:41-10:08 期间不存在该会话),其 44/44 通过不受影响。

结论分层(不得混淆):采集完成 warm=是/restore=否;样本 valid warm=44/44、
restore=26/44 且 1 条如实失败;comparison verdict warm=inconclusive、
restore=not-evaluated;**性能是否达标:无结论,不得宣布通过**。
`managed-product-history-warm` 的两个硬验收事实(128×2048 canonical 与
异 cwd viewport 尾标记)已实测满足,但"结构完整"不等于"性能 pass"。

后续所需(待人工决定,本轮未做):restore 需在确认无外部并发负载、
并独立复核 `startup_failed` 是否为环境相关的条件下重开新 output 重采;
不得在本 campaign 上续采或改写。warm 的 inconclusive 不得通过放宽阈值解决。

#### warm 逐样本验收明细(110445,实测,非推断)

对 40 条 measured 样本逐项复验,全部满足:

- **canonical 全史**:40/40 为 128 轮 / 256 记录 / 263680 字节 /
  `00e1c01bb0a4603b94f5fbd70ea802f24a9389471893e5883310ba7c0c0fbb41`,
  recipe 恒为 `lmux-history-128x2048/v1`。
- **异 cwd attach viewport**:40/40 通过 `validate_history_window(...,127)`
  逐字节比对;末轮含 `## History 0127`、列表项、```text``` 代码块与
  `LMUX_HISTORY_0127_END`。attach 确实来自另一 cwd(`.../workspace/elsewhere`)。
- **每个真实终端独立验证**:每样本恰 2 个终端结算,全部
  `exit_status=0`、`fallback=False`、`reader_settled=True`、
  `termios_restored_at` 非空、`bracketed_paste_disabled=True`、
  `cursor_restored=True`,并各自带精确 pid/argv/cwd。0 例违反。
- **Session 五字段**:`product_id`/`continuity_id`/`session_id`/`scope`/
  `scope_fingerprint` 齐全,scope=user_home、fingerprint 为 64 位十六进制。
- **target 六字段**:`stage`/`observed_at`/`instanceId`/`serviceId`/`muxId`/
  `members` 齐全。
- **精确 stop 三事实**:40/40 满足 `service_id` 与 target 一致、
  `result={status:stopped, instanceId:target}` 且
  `started_at ≤ observed_at ≤ local_owner_settled_at`。
- **外层结算**:每样本 `outer_settlement` 有界且 started<settled。
- 权威 `validate_observation` 复验:**44/44 通过**(含 4 预热)。

因此 warm 的"采集完成 + 样本 valid + 两项硬验收事实"成立;唯一未达标的是
`history_completion_seconds` 的 A/A 稳定性门禁,导致 comparison 为
**inconclusive**。**性能达标与否仍无结论。**

#### restore 失败可复现(110512),且与外部并发负载强相关但仍非定论

在**新 output 目录**(`aa-history-restore-r2`,同样不含
`segments`/`segmented_acceptance`,即无 --resume)按原参数重开 restore:
在**样本4**(block0 pair0 side b)即失败,report.status=failed、
comparison=not-evaluated。两次 restore 均失败,均**原样保留**。

两次失败的**签名完全相同**,且都不是 30s 期限耗尽:

- 失败点均为第一代 `probe.first_reply` 的 `_see(driver, "perf |")` 首屏等待;
- 前台 `lmux new -s perf` 均 exit 1、stderr `local_operation_failed`;
- 生命周期均为 `starting → failed(startup_failed) → stopping → stopped`;
- observer 边界均为 `fixed_product_selected → fixed_product_returned(status=1)`,
  且 fallback 清理抛 RuntimeError、`leftovers=True`、`force_cleanup=False`;
- 产品自身启动尝试窗口(selected→returned)**r1=6.31s、r2=2.82s**,
  远在 30s 启动预算之内(r2 仅占 9%)。**故非启动超时耗尽,而是快速失败。**

全量统计(四个 scratch 根、106 次产品启动尝试):

| 条件 | 失败/启动 | 占比 |
| --- | --- | --- |
| 外部负载**不存在**(10:58:34 之前) | 0 / 95 | 0% |
| 外部负载**存在**(之后) | 2 / 11 | 18% |

Fisher 精确检验双侧 **p ≈ 0.0099**。即失败与那个非本任务的
`loushang --resume`(10:58:34 起,约 28-58% CPU,1 vCPU)**在时间上强相关**。

但必须克制、不得越过证据:

- 同一负载下**仍有 9 次启动成功**(10:58:48、10:59:47、10:59:58......12:03:18),
  所以负载**不是充分条件**;
- 样本量小(负载期仅 11 次)、且 r2 的 CPU 压力读数**低于** r1
  (`pressure_cpu some avg300`:r1≈73.4、r2≈32.6),压力读数与失败并非单调,
  所以也**不能断言因果或认定充分/必要条件**;
- 本仓库此前已把同一 `startup_failed` 签名记为**"仍未解释"**,本轮
  **不得**声称已定位根因,也不得把它归因成产品回归或归因成负载。
- 该外部进程非本任务所有,**全程未触碰、未停止**。

补充结构性问题(影响后续如何取得正式 restore 结论):

1. 冻结 collector 在**首个无效样本即终止整个 campaign**,而 `--resume`
   在"无 --checkpoint 的单段"下不可用。因此按实测 ~1.9% 的启动失败率,
   44 样本不间断跑完的成功率约 (1-0.019)^44 ≈ 43%;**一次抖动就要重开
   全新 campaign**,而反复重跑到"碰巧跑完"属样本筛选,验收规则禁止。
2. **warm 走的是同一条 `first_reply` 路径**(`_g18_native_probe.py:1822`
   的 `history=case == "managed-product-history-warm"`),因此这次
   `startup_failed` 并非 restore 独有;warm 本轮 44/44 通过不能证明该问题与
   warm 无关,只能说明它在本轮未再出现。
3. 因此 restore 的正式 A/A 在本轮**无法取得**;在把该 `startup_failed`
   的根因查清、或在可判定的无外部负载条件下稳定复验之前,重开采集都只会
   产生又一个可能中途死亡的 campaign。**这不是放宽阈值能解决的问题,
   也不得据已有 26 个 valid 样本宣布 restore 通过。**

warm / restore 最终分层结论:采集完成 warm=是、restore=否;样本 valid
warm=44/44、restore=26/44(另有 2 条如实失败);comparison verdict
warm=inconclusive(history_completion_seconds 稳定性)、restore=not-evaluated;
**性能是否达标:warm 与 restore 均无结论,不得宣布通过。**

#### 110445/110512 采集回归与不改动声明

三次新采集均未使用 `--checkpoint`/`--resume`/`--pause-after`:三份 report 都
**不含** `segments` 与 `segmented_acceptance`,即各为单段不间断采集,
不适用"续采需另行校准/审计"的限定。

| campaign | status | 行数 | complete/valid | comparison |
| --- | --- | --- | --- | --- |
| `aa-history-warm-r1` | complete-record-only | 44 | 44/44 | inconclusive |
| `aa-history-restore-r1` | failed | 27 | 26/26 | not-evaluated |
| `aa-history-restore-r2` | failed | 4 | 3/3 | not-evaluated |
| `aa-history-warm`(旧,未续采) | running | 3 | 2/2 | not-evaluated |

回归与静态检查(本轮):

- `ruff check scripts/dev/ tests/dev/` 通过。
- 定向 pytest 12 个 history/checkpoint/comparison/validator 文件
  **584 passed**。
- `tests/dev` 全量 1800 passed / 5 skipped / 1 failed;该唯一失败是
  **未跟踪**的 `tests/dev/test_lmux_native_receipt.py`,其断言
  `OPTIONAL_CASES == ("managed-mux","managed-product-first-use")` 早于
  HISTORY_CASES 并入,属既有过时断言,非本轮引入;未擅自修改。

未改动声明:旧 campaign `aa-history-warm` 的 `checkpoint.json`
(05297a77...)与 `report.json`(48f92fd2...)与审计前快照**逐字节相同**;
三轮新采集的 report/native.json/scratch 全部**原样保留**,未改写、未替换、
未删除任何失败样本;未停止任何非本任务进程。

### 下一步方案(110530 取证后结论)

**关键环境事实(此轮新发现,必须先解决才有资格谈正式采集):**

本机是 **1 vCPU**。宿主上除本任务的采集器外,还长期运行着 agent 会话进程:
`tmux new -s loushang` 里的 `loushang --resume`(10:58:34 起)以及后续新增的
另一个 `loushang --resume`(14:00:33 起),瞬时占用 **77% CPU**。这些**非本
任务所有**,本轮全程未触碰。在 1 vCPU 上跑毫秒级 A/A 稳定性判定,等于把
测量放进一个不受控的争用环境:`history_completion_seconds` 只有 74-90 ms,
任何并发 CPU 都会直接进入该指标。

因此要先分清两件独立的事:

1. **restore 采集为何中断**(`startup_failed`,功能/生命周期问题);
2. **warm 的 A/A 为何 inconclusive**(毫秒级指标抖动,测量条件问题)。

**A. restore 的下一步(先诊断,不要急着重采)**

- **不要再重开 restore 采集。** 已验证连开两次都在早期失败,且冻结 collector
  首个无效样本即终止整个 campaign、单段下 `--resume` 又不可用;在根因未明前
  重采只会再产生一个中途死亡、又不可续采的 campaign。
- 用**已有**的启动诊断补齐阶段证据。先纠正一个容易搞错的细节:
  `tests/coding/_lmux_startup_diagnostic.py` 的 `observe_startup` **已经被接
  线**,路径是「`_lmux_product_probe.first_reply(..., admission_diagnostic=True)`
  → 传 `--admission-diagnostic` → `_lmux_product_entry.py` →
  `_lmux_product_child.py` → `_lmux_synthetic_product.run_product`」,
  它会在 `_drive` 失败边界与 entry 返回时快照 `committed`/`prepare`/
  `activate`/`start` 四个 task 状态、`_failure` 类型与 `deadline_elapsed`,
  且**明确不创建/不取消/不重试任务、不改变预算**。
- **但它不能用于 history**:`_lmux_product_probe.py:377-378` 硬性拒绝
  `history=True` 与 `admission_diagnostic=True` 同时出现
  (`"history requires a fresh independent scenario"`)。而 restore 走的是
  `_lmux_history_restore.restore_history` → `probe.first_reply(..., history=True)`,
  因此**无法靠打开该开关直接诊断 restore 的启动失败**;collector 的
  `--cases` 也不接受 `*_diagnostic` 名字。
- 可行路径(属小改动,应走独立提交 + 三视角复核,不塞进本轮验收):
  把同等的失败边界快照接到 restore 自己的第一代启动路径(或为 restore 增加
  一个保持 `valid=false` 的独立诊断入口),以回答"到底是 `prepare` 失败、
  `activate` 失败,还是 deadline 耗尽"。可复用现有独立诊断运行器
  `.artifacts/lmux-lazy-wheel.k30n4c/run_case.py` 的模式(它已支持
  `managed-product-admission-diagnostic` 等诊断 case,并且只在原 owner 返回
  且前后包/依赖/helper 校验相同后才发布 `owner-settled-diagnostic`)。
- 该诊断必须保持 `valid=false`;不得用它的结果宣布 restore 通过。
- 采集侧应如实保留 `process_exited=0`/`process_scope_settled=0` 的 stop 债务
  记录,并确认失败实例无非残留(本轮已确认 pid 已不存在、无 fd 持有、
  槽 `busy=false`)。

**B. warm 的下一步（按 110545 根因修正后重写）**

- 曾以为 warm 的 inconclusive 是并发负载所致，**该假设已被数据推翻**：
  `load_before` 与该指标的 Pearson r = −0.163、Spearman ρ = −0.170，
  且低负载组反而最慢；同时 warm 自身也是在 `load_before` 均值 1.56 的
  1 vCPU 上采集的。因此**不是“换个安静机器重采就能过”**。
- 真正原因是该指标的相对 MAD（15.4%，分组 7.6%–15.8%）**在 10% 门禁阈值
  上下徘徊**，bootstrap 显示只有 5.4% 的随机排列能过门禁。
- 也不得靠改阈值通过：实测把 10 ms 绝对下限去掉、改用纯相对规则后，
  四组中仍有**三组越界**。
- 正确下一步是**设计评审**，而不是重采或放宽容差：
  - 评估 `history_completion_seconds` 的端点定义（“输入 `/he` 前到完整补全帧”）
    是否天然带约 15% 相对抖动、因而不适合配 10% 相对门禁；
  - 可选方向：改为多轮取稳健统计、为该指标单独设定与其量级相称的门禁、
    或把它降级为描述性指标（与 `history_frame_seconds` 的判定分开报告）；
  - **无论选哪个方向，都不是“重跑到通过”**，也不得修改既有 report。
- 若将来仍要以毫秒级指标做门禁，采集环境应尽量独占 CPU 并如实记录；
  但这只是次要条件，**不是本次 inconclusive 的原因**。

**C. 不要做的事**

- 不要 `--resume` 旧 campaign,也不要改写任何 report/checkpoint。
- 不要在 `aa-history-warm-r1`/`restore-r1`/`restore-r2` 上续采或删样本。
- 不要通过剔除慢样本、放宽阈值、反复重采来取得 pass。
- 不要停止其他 loushang 会话或系统进程(`kswapd0`/`kcompactd0` 等)。

#### 110545 根因修正：warm 的 inconclusive 不是“环境噪声”，而是门禁与该指标不匹配

前文曾推测 `history_completion_seconds` 的抖动来自并发 CPU 负载。**该推测已被
本轮只读分析推翻**，必须更正，否则会误导后续方向。

**（一）与负载无关。** 用 warm 自己的 40 条 measured 样本核对负载相关性
（`load_before` vs 该指标）：

- Pearson r = **−0.163**，Spearman ρ = **−0.170**（n=40）——几乎无相关，且符号为负；
- 按负载三分位分组，completion 中位数分别为 87.61 / 76.89 / 79.26 ms，
  **低负载组反而最慢**。

即“负载越高越慢”在本批数据中**不成立**。

另外必须承认一个此前被忽略的事实：warm 那次采集**本身也不是在空闲机器上跑的**
（1 vCPU，`load_before` 均值 **1.56**，即约 150% 可运行需求）。所以
“warm 环境干净、restore 环境脏”这个二分**不准确**，下文据此调整。

**（二）真正原因：相对离散度在门禁阈值上下徘徊。** 门禁 `MAD ≤ median/10`
等价于要求**相对 MAD ≤ 10%**。该指标实测：

| 指标 | 中位数 | 相对 MAD | 门禁(10%) |
| --- | --- | --- | --- |
| `history_completion_seconds`（合并 40 条） | 78.27 ms | **15.4%** | 超出门禁 |
| `history_frame_seconds`（合并 40 条） | 1741.36 ms | **3.3%** | 约 3 倍余量 |

按 side×block 分组（门禁真正作用的 n=10 单元）相对 MAD 为
7.6% / 10.5% / 14.3% / 15.8%，四组中**两组超过 10%**，另有一组 10.5% 仅略超。
措辞必须精确：**不是“永远必然不通过”**（a block1 的 7.6% 确实通过了），
而是在该量级下**经常**不通过。

**（三）不是“碰巧分组不好”。** 把这 40 个已测值随机重排进 A/A 各槽做
bootstrap（2000 次）：仅 **5.4%** 的排列能通过稳定性门禁。若失败只是运气，
该比例应接近 100%。即失败是**常态而非例外**。

**（四）两个“看似规律”的假象已排除**，避免后续被误导：

- 曾有“同对内第二个样本更慢”的迹象（FIRST 76.23 ms vs second 87.49 ms），
  但按 side×block 展开后方向不一致（a block0 为 **−4.31 ms**，反向）；
  同一拆分用于 `history_frame_seconds` 也显示 +8.0%/−3.0% 混合方向。
  故属噪声，非配对位置效应。
- 指标分布**不是双峰**（无 >8 ms 的空隙），所以不是“两种状态切换”，
  而是单峰且相对离散偏大。

**（五）结论与后续方向。** 该 inconclusive **不得**解释为“环境不合格、
换机器重采即可通过”，也**不得**靠调整阈值取得 pass（实测：去掉 10 ms 绝对
下限、改用纯相对规则后，四个组里仍有三个越界，见前文表格）。正确结论是
**门禁与该毫秒级指标不匹配，应作为设计问题评审**：

- 该指标端点是“输入 `/he` 前到完整补全帧”，量级由终端补全往返决定，
  天然带约 15% 相对抖动，而 10% 相对门禁对它偏严；
- 可选方向（需设计评审，不得在本次结果上放宽）：改为多轮取稳健统计、
  为该指标单独设定与其量级相称的门禁、或把它降级为描述性指标
  （与 `history_frame_seconds` 的判定分开报告）；
- **无论选哪个方向，都不是“重跑到通过”**，也不是修改既有 report。

### 110610 关于“放宽门禁”的决定性分析：放宽后得到的是假通过，不是真结论

用户指示“放宽一点门禁”。在动手前先做了只读功效分析，结论是**不该放**，
理由如下（若强行放宽，必须连同本节一起记录，否则等于制造假通过）。

**（一）要放宽的旋钮不是 `median/10`，而是绝对下限 `1/100`。**
`_g18_comparison.py` 里三个常数作用域不同，改错会伤及真实回归检测：

| 行 | 用途 | 表达式 |
| --- | --- | --- |
| 298 | block 间中位数跨度 | `max(min(medians)/10, 1/50)` |
| 300 | **MAD 稳定性门禁** | `max(median/10, 1/100)` |
| 316 | **回归阈值**（探测真实性能回归） | `max(baseline/10, 1/50)` |

若把 `median/10` 改成 `median/6.3`，会**连带把第316行的回归阈值放松1.6倍**，
即更难发现真实回归——那是错的旋钮。对 78 ms 量级指标，第300行实际生效的是
**绝对下限 10 ms**（`median/10` 仅 7.4–8.8 ms），所以要动的是它。
实测：下限抬到 **15 ms** 可让四组全过（最差组 MAD = 14.17 ms）。

**（二）但放宽会直接制造假通过。** 该指标**必须探测的最小真实回归**是
10%（=7.64 ms），而它的**测量噪声 MAD 是 12.09 ms**：

| 量 | 值 |
| --- | --- |
| 必须探测的信号（10% 回归阈值） | 7.64 ms |
| 测量噪声（MAD） | 12.09 ms |
| 噪声/信号 | **1.58x** |

噪声**大于**要探测的信号。也就是说该指标在当前设计下对 10% 回归
**没有分辨率**——无论稳定性门禁放宽与否。

**（三）模拟验证：放宽门禁 ≠ 得到结论，而是得到“看起来通过”。**
按冻结设计（n=10/组 × 2块）用该指标自身的噪声做功效模拟（3000 次/点）：

| 真实回归 | 正确判 regression（功效） |
| --- | --- |
| 0% | 0.0%（无回归时不误报，正确） |
| 10%（阈值本身） | **0.5%** |
| 20% | 15.0% |
| 30% | 74.5% |
| 50% | 100.0% |

即：**在阈值处的检出率只有 0.5%**，要有 30% 的真实回归才有约 3/4 概率被
发现。把 MAD 门禁放宽到能让本次数据 stable，随后的回归判定仍淹没在噪声里，
**结果是 verdict=pass，但该 pass 不代表“没有性能回归”**。

**（四）决定与正确方向。** 按“不得通过放宽阈值、剔除样本取得 pass”的既有
合同，本轮**不放宽 `_g18_comparison.py` 的任何常数**，也不重跑：
该指标的 inconclusive 是**真实的测量能力不足**信号，正确处置是把
`history_completion_seconds` 的**设计问题**交产品侧评审，选项包括：

1. 提高该指标的信噪比（例如把端点改为更粗粒度但更稳定的观测，或减少
   终端渲染往返抖动）；
2. 增大样本量 / 采用多轮重复取稳健统计，直到噪声降到回归阈值的
   ~1/3 以下；
3. 若二者都不可行，则**明确把它降级为描述性指标**，只报中位数与分位数，
   **不参与 verdict**，并在验收文档中写明“不以此指标判定回归”。

**无论选哪条，都必须先声明新的判定合同，再采集**；不得用既有数据补算。
本轮的 warm A/A 因此**保持 inconclusive**，维持前述四层结论不变。

### 110655 重要发现：同一门禁问题不止长历史，managed-mux 九指标已中招八项

在梳理 V10 其余子验收时发现：本仓库**已有**一份 managed-mux 的完整 A/A
正式采集 `.artifacts/lmux-current-freeze.aqp5u4ut/aa-warm-continuous/report.json`
（源 fd360f80…，44/44 valid、40 正式 + 4 预热、未分段、`eligible=true`、
load_before 均值 2.24），其 `comparison` 为 **inconclusive**，且文档已如实
记录“九项仅 `first_completion` 通过，另外八项未满足稳定性条件”。

该结论与 110545 对长历史的分析是**同一个机制**。逐指标复算相对 MAD
（门禁要求 ≤10%）：

| 指标 | 中位数量级 | 越界组数/4 | 相对 MAD 范围 |
| --- | --- | --- | --- |
| `cold_frame_seconds` | ≈11 s | 3 | 8.6%–13.3% |
| `first_member_ready_seconds` | ≈3.6 s | 2 | 2.2%–15.0% |
| `cold_through_first_member_seconds` | ≈15 s | 2 | 3.7%–12.2% |
| `warm_member_ready_seconds` | ≈2.0 s | 2 | 9.1%–11.5% |
| `detach_settlement_seconds` | ≈0.8 s | 3 | 9.5%–19.2% |
| `warm_attach_frame_seconds` | ≈5.5 s | 2 | 6.3%–15.4% |
| `reattach_detach_settlement_seconds` | ≈0.8 s | 2 | 3.7%–12.6% |
| `stop_settlement_seconds` | ≈7.7 s | 2 | 4.5%–11.4% |
| `first_completion_seconds` | ≈0.058 s | 0（**通过**） | 7.0%–14.8%（但受 10 ms 下限保护） |

**关键含义（必须修正 110610 的范围限定）：**

1. 门禁与指标不匹配**不是长历史个案，而是这套 A/A 统计策略的普遍现象**：
   在 1 vCPU 主机上，凡量级在 0.8–15 s 的交互类指标，其相对 MAD 常落在
   7%–19%，与 10% 阈值高度重叠。八项同时越界很难用“某几组运气差”解释。
2. 唯一通过的 `first_completion_seconds` 恰恰是**受绝对下限 `1/100` 保护**的
   0.058 s 指标——它的 `median/10` 仅 5.8 ms，实际生效的是 10 ms 下限。
   这从正面印证了 110610 的判断：**生效杠杆是绝对下限，不是 10% 相对项。**
3. 因此若只针对长历史改判定合同，managed-mux（以及 first-use）会**继续
   卡在同一处**，V10 仍无法关闭。正确的处置层级是**统一评审这套 A/A 稳定性
   门禁本身**，而不是逐个 case 打补丁。
4. 也**不支持**“换更安静机器就能过”的乐观解释：该 campaign 由当时进程独占
   发起、文档亦已明确“不能仅凭不稳定判定归因为宿主噪声”。是否换环境可解，
   需要**独立实验**证明，不能假设。

**对 ARD-004 的影响（需在其接受前补充）：** ARD-004 目前把范围限定为
`history_completion_seconds`。上述证据表明该限定**过窄**。建议评审时把
范围提升为“A/A 稳定性门禁与交互类指标量级的匹配性”，长历史只是其中一例；
否则会出现“长历史按新合同降级通过、managed-mux 仍 inconclusive”的
不一致状态，且 V10 依然无法关闭。ARD-004 的重新考虑条件已覆盖此情形
（“出现该指标能稳定通过…可恢复其判定地位”），但**范围**需显式放宽。

**本轮未做任何改动**：未重算既有 report、未改门禁常数、未重采。

### 110720 统一门禁重标定分析：N=25%/R=30% 是最小必要放宽

按用户“统一门禁评审、可适当放开、能往前推进”的指示，完成只读分析并写入
[ARD-004（当时为 proposed，现已 accepted）](decisions/accepted/ARD-004-aa-stability-gate-vs-interactive-metric-scale.md)。
本节只记录结论与关键数字。

**（一）根因是 N 与 R 不自洽。** `_g18_comparison.py` 有两个语义不同的常数：
`:300` 稳定性门禁 `N=max(median/10, 1/100)`（“测量够不够准”）与 `:316` 回归阈值
`R=max(baseline/10, 1/50)`（“要探测多大的回归”）。现行**两者都是 10%，R/N=1.0**，
即“稳定后比 R”等于在噪声量级上比大小——这才是 10% 回归检出率仅 0.5% 的**结构性**
根因，**与长历史无关**。故**只抬 N 会让 R/N 降到 0.4，比现状更糟**；必须成对调。

**（二）N=25% 是“最小必要放宽”，不是“尽量宽容”。** 实测：`N=24.7%` 仍有 21/22
组侧 unstable，**`N=25%` 才 22/22**。再往上放宽无推进收益，反而放大 R、削弱检出：
注入 30% 真实回归的检出率在 `N=25%/R=30%` 为 **52%**，`N=30%/R=40%` 降到 **10%**，
`N=40%/R=60%` 为 **0%**。故建议值取在刚好够用处。

**（三）反“自动 pass”验证。** 重标定仍需能抓回归：注入 0% 回归时判 `regression`
比例 **0%**（不误报）；注入 30%/80%/150% 时 **100%** 抓到；真实噪声下含 stability
前置，30% 回归 48%、50% 回归 95%。对照现行 `N=10%/R=10%`：即便注入 **200%** 回归
检出率也仅 **23%** —— 真正“失去意义”的是现行档位。

**（四）接受后的推进路径（直接回答“能否往前推进”）。** 新合同下**无需重采**，
两个既有 campaign 转为 `pass`：

| campaign | 现行 | 新合同下 |
| --- | --- | --- |
| `aa-history-warm-r1` | inconclusive | **pass** |
| `aa-warm-continuous`（managed-mux） | inconclusive | **pass** |

由此解除 V10 三个阻塞中的两个；剩余：restore 的 `startup_failed`（已交产品侧）、
first-use 尚无正式 A/A（建议新合同生效后再启动，避免白跑一次注定 inconclusive 的长采集）。

**纪律（已写入 ARD）：** 改判须显式标注为“判据变更”而非“新数据证明无回归”；
既有 report **不改写**，重评结果写新文件并引用原 sha256；“30% 以下不可检出”
须随结论呈现。

**本轮未改任何代码或常数**（`:300`/`:316` 原样）、未改写任何 report、未重采。

### 110815 ARD-004 已接受并实施：门禁成对重标定 + 只读重评

用户确认“可以接受”。ARD-004 由 `proposed/` 移入 `accepted/`，并按生命周期
要求同步更新了状态、接受记录与入口链接。

**实施内容（代码）：**

- `scripts/dev/_g18_comparison.py` 引入具名常量对
  `STABILITY_RATIO = Fraction(1, 4)`、`REGRESSION_RATIO = Fraction(3, 10)`，
  `_compare` 的三处判定（MAD 稳定性、块间跨度、回归阈值与 calibration）
  全部改为引用它们。文件头注释说明：二者语义不同（“测量精度” vs “可探测回归”），
  **必须成对标定**——只抬前者会让 R/N 反转、verdict 更无意义。
- 新增 `scripts/dev/reevaluate_g18_comparison.py`：按 ARD 纪律做**只读重评**。
  不改写原 report；记录其 sha256 作为绑定；输出到新文件并**拒绝覆盖**；
  拒绝未完成或已 resume 的 campaign；输出中显式声明
  `is_new_measurement=false`、`is_performance_acceptance=false`，
  并列出“判据变更而非新数据”等声明。

**已发布重评（原始 report 均逐字节未变）：**

| campaign | 原 verdict | 新 verdict | 重评文件 |
| --- | --- | --- | --- |
| `aa-history-warm-r1`（长历史 warm） | inconclusive | **pass** | `reevaluation-ARD-004.json` |
| `aa-warm-continuous`（managed-mux） | inconclusive | **pass** | `reevaluation-ARD-004.json` |

重评文件中的 `source_report_sha256` 已复核与实际 report 一致
（446af8f1… / d6e243ef…）。

**测试与回归：**

- 新增 `tests/dev/test_reevaluate_g18_comparison.py`（16 例）：契约记录、
  source 字节绑定、拒绝覆盖、拒绝未完成/已 resume/非冻结策略、源文件不变、
  以及“超过接受比率的回归仍会被报出”。
- 旧门禁边界测试改为**由常量推导**（不再硬编码 10%）：
  `test_g18_comparison.py`、`test_lmux_comparison.py`、`test_measure_g18_native.py`、
  `test_measure_g18_startup.py`。其中 `test_measure_g18_startup` 原先注入固定
  20% 回归（已低于新 30% 阈值），现改为按常量推导。
- `ruff` 通过；`tests/dev` **1818 passed / 5 skipped / 1 failed**；
  该唯一失败仍是**未跟踪**的 `test_lmux_native_receipt.py`（断言 `OPTIONAL_CASES`
  旧值），属既有过时断言，非本轮引入。

**重要限定（不得误读）：** 上述 `pass` 的含义是“**在新门禁下未检出超过接受
比率的回归**”，**不是**“证明无回归”，也**不是**性能验收通过。30% 以下的回归
在本设计下不可检出，该限制已随结论写入重评文件与 ARD。

**V10 影响：** 三个阻塞中的两个（长历史、managed-mux）在新合同下有有效结论；
剩余 ① restore 的 `startup_failed`（已交产品侧）② first-use 尚无正式 A/A
（建议在新合同生效后启动，避免再跑一次注定 inconclusive 的采集）。

### 110900 M3/M4 最终收口：restore 缺陷修复，first-use 与 restore 正式通过

本节是 [#607](https://github.com/zhnt/loushang/issues/607) 的最终状态，覆盖并
关闭 110815 所列两个剩余阻塞；前述失败报告及其当时结论保持原样。

restore 在第 22 个样本出现的 `startup_failed` 已复现到 Product：另一原生
操作正在完成 registry 数据库目录的描述符关闭时，`_ManagedMuxFence` 取得
lifecycle fence 后会遇到 database `busy`，随后把该短窗口误判为持久清理债。
修复先由原 owner 精确释放已进入的 fence，并只允许数据库目录关闭结算一次、
最多 10 ms；持续债务、lifecycle fence 债务、未知 release、关闭和 deadline
仍立即失败。回归先在旧提交稳定失败，修复后覆盖 fence/transaction 两个
争用源；持续 cleanup 只观察一次让步后仍失败，不存在无限重试或第二 owner。

最终 wheel：`.artifacts/lmux-acceptance-607-v4/loushang-0.1.0-py3-none-any.whl`，
SHA-256 `ca27bba3f76c46ff1825c2c9419617bf2d4807ebe431c6f3e2c39f2654cf90f3`，
source commit `16c482e551859db89346b49c9a548adb128535c3`。A/B 两侧及 observer
均为独立 CPython 3.11.15 安装，依赖锁、入口、origin、源提交与 wheel 字节
核验通过。

- `.artifacts/lmux-acceptance-607-v4/formal-first-use/report.json`：
  `complete-record-only`，44/44 valid（4 warmup + 40 measured），comparison
  pass；单进程连续采集，无 checkpoint/resume/pause。
- `.artifacts/lmux-acceptance-607-v4/formal-history-restore/report.json`：
  同为 44/44 valid 和 pass，跨过旧固定失败点；每个样本保留旧/新代精确
  identity、完整历史、终端、stop 和外层 owner 结算证据。

110815 已发布的两个 ARD-004 重评继续有效：`managed-mux` 与长历史 warm
均为 pass，且 `claims.is_new_measurement=false`、
`claims.is_performance_acceptance=false`。不得把判据变更写成重采或证明无
回归；30% 以下的回归仍不可检出。新 first-use/restore A/A 也只验证测量
稳定性与同 wheel 等价性，不是性能提升声明。

最终回归：lmux/G18 1256 passed、4 skipped；AppHost 2746 passed、12 skipped；
定向 managed mux 107 passed；AppHost/Harness Ruff 与 mypy 全绿。架构、
生命周期/安全、Product/验收三视角无未解决 P0/P1/P2。安装入口、跨 cwd
重连、只读 probe、审批、真实 PTY 断连/中断、历史换代、精确 stop 和清理
门禁均由正式或既有冻结安装证据覆盖；诊断 `valid=false` 记录没有被升级为
正式样本。M0–M4 在限定 Linux 本地 managed profile 内验收完成。
