# A123：完整settings快照读取归原Config

- Authority: accepted bounded implementation decision under COD-RESP-GOAL-002.
- Design status: accepted for this operation only.
- Implementation status: partial for the full P1–P4 Goal.
- Owner: Config / Resources / Coding; implementation owner accepts three independent views.
- Method: local clean archmethod master `0f9bd3ff51afabeaaf76cc38dff1ceb279b7d37e`.

## 职责与复用

原Config.store新增私有完整stable JSON patch读取；普通JsonConfigStore.load/save
整类AST不变，它的exists/read_text/宽松JSON读取不能覆盖本快照合同。Code原public
签名及路径guard保留，传Source诊断与动态4MiB预算；Source字段、事务、projection、
legacy政策保Code，其余十个Code操作AST同。五私有reader/identity/native helper及
strict hooks退出Code，没有外部消费者需要兼容壳。

直接复用原Resources.consume_file与无限DescriptorReader，BytesIO接收、hash关闭，
64KiB整块至EOF及每非空chunk重新读cap保持；read_bounded_prefix因提前限制请求
不是drop-in。没有新增生产模块、manager、Protocol或Code IO阶段回调。Config内Resources/
Windows导入仅在使用点执行，实际cold Config仍原20模块；子系统依赖图不变。

## 合同与成本

首adapter进入/首stat的FileNotFound才返回missing；后续open/read/stat/close缺失
仍抛出。原regular/singlelink/UID/size和完整八字段identity保持，不新增0600/ACL
检查。FD关闭在Windows parent assert_visible/close之前；全部scope成功退出才
strict UTF8/重复键/constant JSON、object检查和raw SHA。原native flags/defaults及
清理异常链保持；普通finite float仍合法，不借重构升级JSON规则。

Code359→246（−113），Config52→210（+158），系统+45；额外成本来自完整typed
native adapters和入口参数/lazy imports。原旧循环由已有consume_file实际替代；本批
是完整职责归位，非全系统净压缩。430 Coding源112352，1969系统源648381；其余
1967源和13资源SHA同。完整Goal仍active/partial，Coding距15K97352。

## 验证与限制

原实物`48617b42f`冻结77条观察，旧capture1/新进程旧replay77通过。新实现77与
持久probe77分别重放同原233237B观察，gzip5537B逐字解压相等；observe整函数及
每条replay断言AST同，仅移除树外capture/source-frame/setup辅助并改fixture加载。
原消费者21与import边界165通过；Ruff/format/mypy2、cold20模块及依赖图通过，AI
未选中。初两次observer setup错误完整保留，非Product失败。

首轮新replay在私有tmp插件下目录size40而旧磁盘root4096，另外76项逐项同；按原
磁盘root重跑全部77与持久77通过。未擦字段、重录oracle或改Product掩盖差异。
POSIX文件/FD实际读取；Windows parent/native metadata端口受控，文件仍真实POSIX
FD。八字段按实际先验身份anchor作部分delta，mode/nlink/size显式保留；该fixture
要求等价Linux文件系统，持久probe显式限Linux运行。覆盖39fault case/42触发事件、opened八字段漂移、after/
visible漂移、open竞态、latecap、strictJSON和多重close异常。同步CancelledError
不是Task.cancel，无原生Windows内核/跨进程race或OOM证明；overflow先检查再写
私有buffer的分配时点不同，不承诺任意非bytes fake端口或MemoryError时序。

三视角设计/实际及原脚本、旧观察、失败、源码SHA位于树外
`coding-convergence-continue/a123-settings-snapshot-reader`。未扩PR gate/平台/覆盖门槛。
Hosting/AI覆盖率/构造等旧差距，KD003未实施、KD011/A33待用户未采用保持。
