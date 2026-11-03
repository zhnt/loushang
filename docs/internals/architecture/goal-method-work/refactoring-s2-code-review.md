# S2共享执行切片代码评审

- Authority: descriptive；Implementation status: in-progress。
- 对象：[协同专项R2](session-goal-coordination.md)已获用户接受后的共享执行切片；不是S2全部、S3或双入口完成验收。
- 基线：3a5902637；方法沿用本地archmethod master 0f9bd3ff51afabeaaf76cc38dff1ceb279b7d37e。
- 最终运行代码独立复核：46个源码/测试文件的固定快照（不包含文档）；manifest SHA256 `49c5fc98e8333e7cd1d9bed0917c570595e0654614ea3a5bf3b51a57781c4924`。中立接口修正的前序48文件快照包含文档，SHA256为`5949a3ae4572a2c73c9561a070cff8c1995a787c0a7841ec3e03d296c9225b0b`。

## 范围与职责

Harness拥有原Session输入受理、明确任务委托、操作配置与关闭作用域；没有Work/Goal依赖。HarnessWork集成把原GoalController接到原SessionWorkRuntime prepared槽位和同步resolver提交点。同一Session后端复用而非新建第二runtime；不兼容的日志、来源或取消配置明确拒绝。

公开controller.advance与Product facade.advance汇入同一桥接，再调用原Core算法。普通prompt、命令、侧问及手动压缩参与原受理边界；严格规划期间的普通输入保留在原队列，不新增队列。配置仅撤销自己的overlay，不写回旧全局快照。

## 三视角发现与处置

| 视角 | 发现 | 修复与复核 |
| --- | --- | --- |
| 职责/复用 | 旧lazy factory重复构造与单后端冲突；next-turn未计入pending | 复用原后端并核对配置，增加原next-turn观察；已关闭 |
| 数据/兼容 | 原Goal取消期限None漂移至30秒；复用缺少期限/来源核对 | 显式保留None；既有后端核对原取消与来源合同，保留其clock；已关闭 |
| 数据/兼容 | 尚未投递的输入会被同文本规划输入误消费；投递后证据绑定失败可能重复入队 | 消费只匹配submitted输入；保留实际投递身份与原证据owner，重试不重复投递；已关闭 |
| 职责与运行 | 关闭期间一次异常永久锁存，无法重试原清理 | 首次报告后，重试仍须进入原quiesce/settle/release；未知事实继续由原owner阻断；已关闭 |
| 运行/失败 | 并发settle重复删除同一pending run | 幂等discard；两waiter复用原取消任务；已关闭 |
| 运行/失败 | Bash尚未启动时，命令空闲不代表已受理delegate退出 | 原domain取消成功后，桥接停止原WorkTask并只等待delegate finally边界，避免等待整个WorkTask形成环；finally异常仍失败；已关闭 |
| 既有架构检查 | 新配置模块和runtime引用具体Agent类，三视角初轮漏查 | 改为只读ExecutionAgentPort；保持原拒绝、任务身份和conformance边界，不扩大import白名单；三视角对最终delta复核无新增阻断 |
| 托管组合回归 | 纯同步review/inspection publisher没有取消端口，取消后只能保守保留unknown | 领域显式声明自身无独立执行资源；同一桥接仍必须停止并join实际调用，才由原Work记录settled；有delegate继续原端口，不把None/noport自动升级；三视角复核关闭 |

三位独立agent逐轮核对固定源码及摘要，未读取彼此报告、未运行测试或模型。最终复核均无本切片剩余阻断；该结论不替代执行回归。原报告保存在产品树外architecture-analysis/goal-refactor-20261103的三份s2-owner-review报告及修订附录。

## 取消与退休的明确变化

原Bash owner新增本次调用完成屏障，覆盖原native调用、进程清理和结果记录；等待方取消不丢原owner。验证执行器通过注入该原端口及已受理delegate退出证明报告settled。没有取消端口的standalone仍unsupported，旧journal不会被补写成settled。

因此，新执行具备真实收敛证据时，不再一律产生旧unsupported所派生的unknown。原仓库取消测试据此改为检查journal settled、缓存同operation不重放、唯一批次、零模型调用与Goal不冒称完成。这是明确的能力演进，不能概括为全部取消观察结果逐字不变。同步评审/快照publisher的声明仅限其当前无独立Task、transport或native worker的实现，不意味着Blob回滚、评审通过或外部reviewer停止。

Scope仅在原finalize成功后摘掉Session持有的精确引用；失败仍保留同一owner及依赖。父Session释放原后端引用前必须通过原settlement；unknown清理债务同时参与busy判据，同步close也不能绕过。

## 验证范围与剩余工作

精确回归已有98项、52项、37项通过；退休专项25项通过；命令启动前与执行中取消2项通过；托管评审取消原用例1项通过。中立接口最终位置的全部import boundary、Session与Agent专项224项通过（206.84秒）；文档9项通过。冻结收尾预算补充20项通过（181.77秒），托管失败点之后的进度/预算/撤权补充25项通过（63.28秒）。它们存在覆盖交集，不累加成独立用例总数。更广共享底座运行在560项通过后被具体Agent依赖阻断，已据此修复；托管组合45项通过后暴露publisher取消缺口，已精确修复。修复前被中断或失败的组合运行不作为最终通过依据；尚未将整仓check-changed或最终PR检查记为通过。

另用冻结的e1601d059源码读取本轮实际新写出的离线记录：11个Goal、30个Work、10份真实规划来源证明通过，Goal/Work日志读前后摘要相同。此核对在产品树外运行，直接断言实际导入旧源码；不调用模型、不重新生成旧fixture，不代表所有格式、平台和历史分支已穷举。最终46个变更源码/测试逐项匹配独立复核摘要，Ruff通过，受影响共享模块与领域两文件mypy通过；Agent全文件原有类型错误未据此宣称已修复。

普通当前Session公开接入、通用规划/方法集成的S3收敛、嵌入式与application-local AppService的S4等价仍未完成。真实lmux wire保持后续专项边界。当前无S2远程交付，不将中间切片复核当作整个重构Goal完成。
