# C07 Worker 大块迁移

- Authority: descriptive audit / execution evidence
- Design status: partial acceptance — preparation/checkpoint, source custody, reference proof and persisted/cutover read slices reviewed by implementation owner; whole-chain closure pending
- Implementation status: partial; majority exit target not achieved
- Owner: Coding / Harness Worker History / Package Product
- 执行基线：`06f8a3f6f7646176a489343d08dbc02b4d41fa10`；开始时已 fetch，main 与 lane/harness 均相同。
- 方法查阅：本机 archmethod clean `master`，commit `0f9bd3ff51afabeaaf76cc38dff1ceb279b7d37e`。

## 验收基线

本轮按新的大块迁移 Goal 执行，旧轮次 [C07 收敛记录](c07-worker-convergence.md) 仅作为既有能力和兼容基线，不代表本轮验收。
112 个 Coding 源文件重新冻结为20,266物理行，外部基线同时记录原 SHA、公开签名、名义字段及原始用户改动哈希。
“大部分”要求至少10,134行通过职责迁移或复用后的重复删除退出 Coding；新增 Coding 适配同样计入剩余量，不借改名或挪到相邻 Coding 模块隐藏成本。
同时核对实际实现体与完整事务接线；字段、注释、格式和单纯转发的变化不能充当主要收益。未达到规模和整链要求，不据文件复核完毕或局部测试通过关闭 Goal。

| 优先链 | 初始文件 | 初始物理行 | 当前状态 |
| --- | ---: | ---: | --- |
| Windows 历史、检查点、引用闭合与六流 bases | 18 | 3,379 | 实施中 |
| Windows 恢复、审阅、退休与失败清理 | 18 | 4,865 | 待迁移 |
| 两平台载荷、启动绑定及其直接入口 | 7 | 2,552 | 待迁移 |
| 其他 C07 回执、批准、Provisioning 与消费者 | 69 | 9,470 | 待重新审查 |

以上是互不重复的源码库存，包含必要兼容保留，不预先作为迁移收益。先前已共享的 Worker、Package Product、Journal、Resources 和 Hosting 能力不重计。

## 首批机制与边界

Codex implementation owner 在本任务授权内复核 Coding 名义兼容、Harness Worker History 纯证明和 Package Product 事务寿命三方边界，接受下列首批实现。该接受不扩展为整个 Windows 历史链或整 C07 已完成。

- `worker.history._windows_checkpoint` 持有 preparation/checkpoint 的固定校验、语义摘要、六流/批准/引用关联和规范编码；沿用已有 `_BaseWireMethods`、RecordSchema、原 history join 和 Native Approval 值。
- Coding 保留两个原名义 dataclass 的字段、slots、构造和公开签名、历史 wire Profile 与 `coding-product-backup-types:` 前缀，方法实现由共享零 slots 基类承接。基类不新增 dataclass 字段或实例状态，不引入动态类型注册器。
- `package_product._windows_worker_history` 持有 prepare/read/publish 三个完整协调体，按原顺序取得实际 Package quiescence/GC guard，捕获证据，校验暂存重试，调用原 WindowsPrivateReceiptIO 发布并复核 currentness。没有第二个账本、恢复器或 authority switch。
- Coding 入口保留准确 Product/type/platform 批准。GC 和根描述符权限仍来自原 Product；原 checkpoint 读取的 guard 模式也原样保留，共享读取操作不增加写入、修复或删除调用。
- 两个粗粒度输入口暂时调用 Coding 的 semantic capture 与 current checkpoint 读模型。它们是本批接线中间态，相关通用读取、关联和资源寿命仍须继续归位；不得因三个协调体已迁移就宣称首条整链完成。最终只允许真实产品授权和名义格式适配留在 Coding。

这是固定记录证明与已有 Product 操作的归位，不是以字段搬运为主线。不会把全部通用流程塞进既有 `_worker_windows_attempt`，也不另建 Worker 生命周期框架。

首批成本（本地提交 `1ec465967`）：Coding −359、Harness +631、Hosting/其他生产 0、系统生产 +272行；测试 +7、文档另计。C07 当前19,907行，尚需至少9,775行退出 Coding。增加主要来自显式共享事实类型、名义字段适配和新的固定事务接线；这属于整链收敛中间成本，后续继续复用和合并，不把 Coding 下降报告为系统精简。

## 来源与引用批次

实现 owner 继续接受来源捕获与只读引用证明的归位：Worker History 复用原 WindowsHistorySourceCapture，持有来源记录方法及固定存储名称；Package Product 持有原 root/ACL/GC/quiescence 寿命、source→recovery→Desired→source 复核顺序和 Desired/Package 引用闭合证明。Coding 保留原名义记录、动态配额和真实 Product 准入。没有增加写入或删除权限；无法观察的原生状态仍然不等于已确认不存在。

累计 Coding −958、Harness +1,655、Hosting/其他生产 0，系统生产 +697行；测试 +16、文档单列。C07 剩余19,308行，仍需至少9,176行退出。新增共享事实接口和兼容字段适配的成本仍然较高，尚无系统净删减收益。该批结束时 GC settled proof、恢复读取与检查点输入组装仍有 Coding 实现，故不声明整链完成。

本批历史/退休既有用例81 passed、1 skipped；修复既有探针消费者的固定名称别名后，来源 golden 单独31 passed，golden 数据不变；不是将原失败的合并运行宣称为全通过。架构边界181 passed，13源 scoped mypy 通过。9个实际记录、18份原始 pickle 字节、14个错误及公开签名/字段/slots 与精确基线一致；三个语义捕获入口57组逐事件对照，其中33组故障，结果一致。模型与模拟均不代替原生 Windows。

## 六流重建与完整读取复核批次

实现 owner 接受六流 reconstruction 与持久读取复核的归位。已有六条 Worker fold 保持原实现，不重复计为本轮迁移；共享 preparation 入口在原顺序逐流重验，原 join owner 负责真实 bound record family 的重建。Desired/Package/checkpoint 原来保留的组装体同步退出 Coding。普通零 slots binding 避免向原 dataclass 元数据引入 ClassVar 字段。

Package Product 持有引用输入 capture、外层 quiescence/GC 读取、当前 checkpoint 的 preparation/Native Approval 读取，以及 persisted 读取和 cutover 候选双重复读的完整协调体。回调边界是既有整项语义捕获、备份政策与完整读取操作，不将步骤或字段拆成 supplier；记录类不获得 IO authority。Worker History 的 persisted/cutover 证明复用原 checkpoint 和六流 owner，Coding 只绑定名义类型、配额、入口与实际 Product 准入。

清理一个已无生产或测试消费者的旧 Desired capture 私有转发，核对公开导出、记录字段/序列化中无函数引用和原消费者路径；原 digest 私有消费者沿用到共享函数的别名。保留来源 golden 使用的私有捕获入口和原固定名称别名，未仅凭静态无匹配退出这些兼容接线。

累计 Coding −1,226、Harness +2,222、Hosting/其他生产 0，系统生产 +996行；测试 +21，文档单列。C07 当前19,040行，还需至少8,908行退出。该批主要补齐已有链路的 owner 连续性，规模目标仍远未达到，也没有系统净精简收益。

本批最终历史 family/source golden 为89 passed、1 skipped；此前 persisted golden/架构边界352 passed，覆盖有交叠不累加。33源 scoped mypy 与 Ruff 通过。18个实际记录的字段、全部 dataclass 元数据、slots、构造和公开签名、36份原始 protocol4/5 pickle 字节及16个错误与精确基线一致。初次探针发现新增 ClassVar 泄漏到继承 dataclass 元数据，已通过普通零 slots binding 修复，最终对照一致。

四条读操作与基线原函数逐事件比较148组，112组实际注入故障，各含两次调用；source/preparation/reference 三条路线另57组、33组故障，顺序、返回值和异常链均一致。使用真实名义记录和合成 guard/IO，只证明所观察的事务路径，不代替 Windows 原生验证。GC settlement 与 offline recovery 的完整读依赖仍待迁移，因此首条历史链仍未完成。

## 当前验证与限制

原有 preparation/checkpoint/history join/Package reference 回归16项通过；加入原 cutover record 与 persisted bases 消费者后25项通过。最后覆盖整组六流、Desired/GC、cutover 与持久化的14个既有文件为58 passed、1 skipped；三组覆盖有交叠不相加。导入边界及原C50/C54为181 passed，六源 scoped mypy、Ruff及生成依赖事实通过。
原 staged-publication 故障用例只将读写注入点移到实际 WindowsPrivateReceiptIO，既有断言和测试入口未改变。两份现有架构清单同步当前模块归属，不新增检查、路线、平台或 PR 门禁。
已与精确基线对照3个实际名义记录、6份原始 protocol4/5 pickle 字节、字段/slots/构造与公开方法签名及8个错误；全部一致。三个公开事务与原函数逐事件对照754组，其中688组实际注入故障，比较两次调用、锁/IO/构造顺序、异常链和剩余字节，一致；模型证据不代替原生 Windows。
测试沿用本会话已批准的 C07 私有目录，仅设置命令环境；运行时测试首次在 sandbox 外通过管理 wrapper 执行。
Windows 原生 LPAC/Job、真实崩溃路线尚未执行；合成事实和跨进程记录探针不作为原生平台证据。

## 剩余工作

继续完成 GC settlement 和 offline recovery 的共同 owner 接线并删除旧机制，再依赖推进恢复/退休及载荷/启动。
全部112文件均须更新职责与处置，区分产品政策、必要名义入口、迁移、复用删除；重新审查旧轮次保留理由，Coding 类型或固定名称不单独构成保留整个实现的理由。
每批计入 Coding/Harness/Hosting/其他生产代码及系统总量，测试和文档单列；系统成本与实际重复删除、职责迁移分别报告。
本轮尚未达到多数退出目标，未提交 PR 或交付，不修改原轮次已完成的历史证据。
