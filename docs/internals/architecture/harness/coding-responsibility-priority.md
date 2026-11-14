# Coding剩余职责实施优先级

2026-11-14，按用户要求优先完整可迁移职责。排序依据是实际尚未共享的操作体、现有
owner能否完整承接、旧实现退出和全部适配成本；目录行数只作审计范围，不作可删除预算。
当前计量见[逐文件清单](coding-responsibility-inventory.md)，完整P1–P4范围见
[剩余责任账](coding-responsibility-remaining-audit.md)。

| 顺序/状态 | 完整工作件 | 接收者及Coding保留边界 | 进入条件或实际处置 |
| --- | --- | --- | --- |
| 已完成 A171 | LSP进程传输完整生命周期 | 原Process拥有buffer/锁/Future/reader Task/request/cancel/close；Code保LSP初始化、诊断、服务器请求与优雅握手 | Code−274/Core+391/系统+117；126项通过；属于职责迁移，不是系统净精简 |
| 已完成 A173 | 配置兼容发布完整authority | 原Config LegacyProjection owner承接cache/issuer、writer与projection注册、聚合、Condition/deque、逐请求receipt和异常结算；Code保存量迁移政策/领域capture、guard和薄profile | 整物Code317→159（−158）/Core+246/系统+88；原135及固定旧29项覆盖通过，保持5原平台skip；不复用异常合同不同的普通Config通知队列，属于职责迁移 |
| 已完成 A174 | 根运行时关闭及Continuity完整绑定寿命 | 原Session Runtime接根关闭/两drain，原Continuity接composition/reservation/Task/identity-delete；Code保领域DTO、准入与薄profile | Code−153（含1行导入布局）/Core+301/生产系统+148（统一格式+139）；320项通过，持久55重放另验不重复累计；子Session113未迁 |
| 1 / 待设计 | Session关闭的完整失败保留链 | 原Session/Graph/resource owner；Code剩deferred LSP、worker lease、publication与证据的释放政策，A174已接根75，剩113行实际子Session关闭程序 | 原cleanup group并非直接替代：首个子关闭失败须保留父能力，后续清理又有不同错误屏障；必须证明完整复合寿命与取消/重试，计算所有阶段端口，不拆十几行helper当主线 |
| 2 / 待核 | 剩余托管/CLI跨入口控制与交接 | 原AppHost/AppService/Session；Code保产品身份、Resume/历史领域合同及严格源准入 | A156托管控制、A158review fence已共享；先定位尚未共享的完整程序，禁止用摘要API代替严格Catalog读取；无新的可删量承诺 |
| 后续开放 / 当前形状拒绝 A169 | Worker Product完整收据authority | 原Package Product/Resources已有candidate验证、receipt witness、history、native/source custody；Code保政策和DTO | 四源完整原型Code−543/Core+1123/系统+580，14结构端口等接口税未带来相称复用，已拒；须不同完整接缝，不能用同形状小mixin重新进入 |

不再排作待整池搬迁的范围：A170核查的inventory/snapshot712行，其root/bundle/member/
list/recheck/finally已由SnapshotEvidenceStore拥有；Code保存量分类、支持政策与新鲜度时点。
A173核查的HostedCatalog943行，其canonical list/open/create/discovery/candidate custody已
在A80–A85的AppHost/Transcript实现。两者仍有未处置边界，但不能重搬或重复计益。
A172对C01/C15/C17共15720行的调查同样确认主构造、Task、Slot和历史读取寿命已共享；
没有证据可把整组判为可删除或永久保留。

每项先核真实消费者、旧操作体、失败/取消/重试/恢复与资源结清，再作完整替换。窄政策
接口可以保留，但Code领域capture/guard回调不冒称纯函数，也不把已共享IO重计为本片收益。
没有已证明可直接承接、且比剩余关闭链更大的新程序时，继续设计下一完整接缝，不填虚构的大块
承诺，不连续以局部十几行去重替代主任务。

C04 Continuity的KD003、托管历史KD011等明确待确认边界保持原状态；其余C05/C06、C08、
C10、C12–C28继续在责任账中，不因排序退出P1–P4。领域能力、内容与产品政策换目录后
仍计Coding归属成本。未建立≤15K不可压缩下界；每批报告Coding、接收组件、兼容适配和
系统源码净值，新增测试/探针另列。完整Goal仍以领域化及≤15000行为验收条件。
