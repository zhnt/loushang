# C07 Worker 大块迁移

- Authority: descriptive audit / execution evidence
- Design status: partial acceptance — history, recovery/retirement, payload/start-gate, registered-value, complete Windows crash-recovery, Provider candidate/Host-input, opt-in, selected-policy, Session-input and discovery-binding slices reviewed by implementation owner; C07 majority and whole inventory acceptance pending
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
| Windows 恢复、审阅、退休与失败清理 | 18 | 4,865 | 实施中 |
| 两平台载荷、启动绑定及其直接入口 | 7 | 2,552 | 实施中；库存范围仍须复核 |
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

## GC、离线恢复与 stage 读取批次

Codex implementation owner 在原授权内接受本批归位；本机 archmethod 仍为 clean master `0f9bd3ff51afabeaaf76cc38dff1ceb279b7d37e`。再次 fetch 后，main/lane 的本地与远端引用仍均为执行基线，没有新增待集成提交。本批不宣称首条整链、第二条退休链或 C07 已完成。

Package Product 的 `_windows_worker_recovery` 接管完整 GC settlement 读取证明、offline semantic capture、attempt reference 投影读取、GC observation 和历史退休分派。沿用原 opt-in/receipt/Supervisor/C5 Journal，仅用一组静态惰性构造绑定保留名义值；构造绑定本身不读取、不缓存 root 或新建账本。实际 Journal 仍在原词法 guard/root 位置创建和读取。备份支持与 Product/type/platform 准入留在 Coding，已有 Job 观察器的不可观察状态仍为 None。

Worker recovery 复用已有 C5/opt-in/receipt facts，持有原 C5 retirement closure、Windows attempt reference 关联与 offline snapshot 派生属性。四类 stage review 的字段、slots、构造、公开入口和历史 fingerprint domain 保留在 Coding；原 RecordSchema 现在复用三份重复 JSON 编码与指纹实现，Worker 同时持有语义 admission。公开 full review 的 to_dict 插入顺序单独保留，原动态 payload/depth 限制仍由兼容 Profile getter 在原验证位置读取。

Package Product 也接管完整 full stage、partial stage 和 reserved/settled-unlaunched 的 guarded read 协调，包括库存、阶段匹配、intent、退休冲突、原 physical capture、实际名义记录构造及 currentness 复核。输入口是已有完整 inventory/intent/physical capture 能力，不把字段或事务阶段拆成 supplier。旧完整-stage 中间组装体与四种已替代的 Code 校验/编码体同步退出；旧 identity/directory 私有函数已由 Worker sole owner 使用，核对过导出、真实调用、记录字段和序列化，没有保留无消费者转发；四份已无消费者的 digest pattern 常量也随校验 owner 迁移退出。

本批 Coding −742、Harness +1,113、系统生产 +371行；累计 Coding −1,968、Harness +3,335、Hosting/其他生产 0、系统生产 +1,367行。C07 剩余18,298行，还需至少8,166行退出。生产总量仍增加，不能报告为净精简；本批 stage wire 的重复编码去重与职责迁移分开看待，不重计早已共享的 Journal、fold 或物理 capture。

最后 stage review/四条退休消费者/physical golden 为339 passed；最终 bounded import、recovery/GC 与 source golden 为134 passed、1 skipped；先前 import/C50/C54 为181 passed，各组有重叠，不累加。现有断言、参数化和 golden 数据未改，仅同步两个实际 owner import inventory 项；未新增门禁。24个实际记录、48份原始 protocol4/5 pickle 字节、字段/slots/全部 dataclass 元数据/公开方法与属性及20个错误和原配额行为与精确基线一致。

四条 GC/offline/reference 路线与原函数194组对照、130组实际故障；full/partial/reserved/settled-unlaunched 读取另82组、54组实际故障，均各调用两次，事件、值/字节及异常链一致。使用真实名义值与受控 guard/IO，原生 Windows 未执行，不将这些模型当作 native 证据。

仍待迁移：四条 completed-retirement 具体 validator、崩溃 stage 的 native identity 协调与退休写事务。它们仍有 Coding 通用实现，因此 GC 分派接通不意味着依赖闭合；后续须由现有 Package Product/Worker/Resources/Hosting owners 连同真实消费者一起接管。多数退出目标未达到，尚未 push/PR 或交付。

## 崩溃复核、孤儿修复与完整 stage 退休批次

实现 owner 接受本批现有 Worker History、Package Product、Resources 与 Hosting 之间的职责归位。Worker recovery 持有原 orphan review 的派生证明、crash cleanup/settled 判据、修复记录关联与 stage retirement receipt 值方法；Coding 保留原 dataclass 字段/slots/pickle 路径、错误身份、wire Profile 与真实产品批准。清洁退出修复的初始产品资格判断仍留在 Coding，锁内复读、比较、registry repair 与释放顺序由 Package Product 持有。

Package Product 的现有 recovery owner 接管完整 crash cleanup/stage 原生身份关联：orphan/receipt、修复 lease、intent、Provisioning phase/witness、spec rebuild、Job 观察及来源重读均在原 guard 与构造点执行。复用原 Hosting observer 和 Worker native bridge，不把未知当成 Job 已消失，不产生新的清理授权。静态对照表明四条原 guarded crash/orphan 函数在声明的 owner/value 绑定替换后，执行体 AST 完全一致；这是源码证据，不是原生平台验证。

完整 stage 退休由 Package Product 的固定 command 接管，持有原 runtime→GC→root guard、start record、精确重试、history 复核、root-delete intent、物理清理和 receipt 发布。实际记录 IO 仍为 WindowsWorkerRetirementRecords/WindowsPrivateReceiptIO，实际成员删除仍为 WindowsStageRetirement。固定 command 仅组合原组件与完整事实读取能力，不新增生命周期账本、状态机或修复管理器，也不把事务阶段回调给 Coding。completed-history 验证和退休库存解析同步归位；Code 中已替代协调体、重复常量及无效私有转发退出，仍有真实消费者的私有名称直接绑定共享方法。

本批 Coding −558、Harness +761、Hosting/其他生产 0，系统生产 +203行；累计 Coding −2,526、Harness +4,096、系统生产 +1,570行，测试和文档另列。C07 剩余17,740行，还需至少7,608行退出。主要收益是完整职责迁移与旧流程退出；生产总量仍增加，没有系统净删减收益，也未达到过半目标。

现有 crash/lease/native/query/value 回归120 passed；最终完整退休、其余退休消费者、物理 IO golden 和 recovery value 为187 passed；import/C50/C54 为181 passed，覆盖有重叠不累加。现有断言、参数化与 golden 数据未改，只把故障输入口改到实际共享 read/write/spec owner，并同步实际 import inventory。27个真实值、54份原始 protocol4/5 pickle 字节及20个错误、字段/slots/全部 dataclass 元数据、公开方法/属性和配额与精确基线一致。

完整退休与原执行体64组对照，其中52组实际注入故障，各含两次调用；使用真实 review/intent/receipt 编解码，比较 guard、读写、丢失确认、删除、回执重放、文件字节、阶段剩余状态及异常链，均一致。物理 native IO 用原 golden 模型另验证；Windows 原生路线尚未执行。

仍未完成：partial、settled-unlaunched 和 crash 三条退休事务及其 completed-history validators，以及后续两平台载荷/启动与其他 C07 文件。不能把完整 stage 退休接通当作整个恢复/退休链已完成。

## 三类退休事务与六流发布批次

实现 owner 接受 partial、settled-unlaunched 与 crash 三个固定退休 command 归原 Package Product retirement owner。原完整 command 的物理删除能力被未启动与崩溃链直接复用；partial 继续使用原 PartialWindowsStageRetirement。三条链的 history/currentness、root intent、删除、回执发布和 completed-history 校验同步迁移，Coding 保留原类型、Product/type/platform/revision 准入、错误与 Profile。旧协调体、债务常量和校验体退出；有实际消费者的私有名称绑定共享方法。没有新增账本、生命周期状态机或阶段 supplier。

六流 bases 的 guarded read/publication 也由现有 Package Product history owner 接管：quiescence→GC→checkpoint→reference join→六摘要→暂存校验→缺失发布→bases/checkpoint 复读。仍使用原 IO、记录、配额和故障注入路径，未增加 cutover 或历史删除权限。

本批 Coding −650、Harness +807、系统生产 +157行；累计 Coding −3,176、Harness +4,903、Hosting/其他生产 0、系统生产 +1,727行。测试累计 +59行，文档单列。C07 剩余17,090行，仍需至少6,958行退出；系统净删减与过半目标均未实现。

最终现有退休/物理 IO golden/value 用例187 passed，架构181 passed，历史消费者66 passed、1 skipped，各组覆盖有交叠不累加。48源 scoped mypy 通过。现有测试入口、参数、断言和 golden 不扩展，只将旧 mock 改绑真实记录、IO、固定 command 和物理 owner。27实际记录、54原始 protocol4/5 pickle、20错误及字段/slots/全部 dataclass 元数据和公开方法对照一致。

17个原退休/history/deletion 函数体在明确绑定替换后 AST 一致。三个退休 command 与基线174组逐事件对照、144组实际故障；六流 read/publication 另144组、126组实际故障，均包含两次调用。使用真实 codec 及受控 guard/IO、删除与重试效果，不代替原生 Windows。剩余恢复、清理证据和结算协调仍在 Coding，整链未完成；载荷/启动和其余文件尚待推进。

## 崩溃结算与清理证据批次

实现 owner 接受 Supervisor 结算、原生清理、带 stage pin 的崩溃 lease 修复、C5 结算和无副作用 reservation 结算归现有 Package Product recovery owner。真实入口仍由 Coding 执行原 Product/type/platform/记录准入；原 registry/GC/root 锁与复核、Journal 和 native-cleanup owners 在共享完整操作内保持原调用顺序。三项 lease 操作共用一个固定 record/runtime/native 绑定，没有新增账本或恢复管理器。

Worker 持有 receipt/native/Supervisor/C5 的完整只读结算证明和 native witness 构造，Coding 保留 authority 身份、信任绑定、运行时 incarnation Profile 和原名义记录。reservation 文档证明归现有 stage wire owner，真实 CAS 仍由原 Provisioning Journal 承担。原 Supervisor 状态转换也归现有 Windows Journal owner；既有失败码和已结算幂等返回保持原样。Windows 与 Linux 的关闭 admission 串行实现合并到现有 Product authority owner，Linux 原名义类、构造签名与平台错误保留，未共享平台特有的 cleanup 证明。

本批 Coding −642、Harness +891、Hosting/其他生产 0，系统生产 +249行；累计 Coding −3,818、Harness +5,794、系统生产 +1,976行（测试和文档单列）。C07 剩余16,448行，仍需至少6,316行退出。新增成本主要为完整能力口、名义适配和证据基类边界；生产净删减和过半退出尚未实现。

既有恢复/证据/结算与 Linux 恢复兼容221 passed、1 skipped；架构181 passed；最终 stage wire/证据和 C51/C54 消费者30 passed，覆盖有交叠不累加。公开入口及名义字段、原有测试入口/参数/断言不变，仅改绑已迁移的故障输入和同步实际 import inventories，未扩大 PR 门禁。27个原记录、54份原始 pickle 与20错误继续一致；新增对照3个结算/证据记录和 authority 的公开签名、字段及8份 pickle 字节也一致。

15个原完整执行体/校验体经声明的 owner 绑定替换后 AST 一致，公共准入判据保持原样。C5/reservation 与原函数76组逐事件对照，60组实际故障，每组两次调用，顺序、状态、重试和异常链一致；使用真实 receipt/记录/settlement 值和受控 coordinator/IO 效果，只证明协调，不证明 native IO 或替代既有 coordinator 验证。初次收集暴露只为注解引入的循环依赖，已将 reservation 证明归原 stage wire owner，最终消费者通过。原生 Windows 仍未运行。

这批未关闭整条恢复链；恢复总编排和证据 factory 中的历史证明仍须复核，随后推进两平台载荷/启动与剩余清单。

## 载荷规划、物化、绑定与 intent 批次

实现 owner 接受 Windows pending planning→物化→request binding→launch intent 的完整机制归原 Package Product attempt/receipt owner。沿用原 recovery admission、retirement/currentness reader、Supervisor Journal、private ReceiptIO、stage creator 和 live-stage verifier。原单一弱引用 bound-request 表和锁迁到该 owner，没有平行登记器；Product 的精确类型、平台、信任域准入、原错误类型和配额 Profile 保留在 Coding。通用 epoch、receipt/runtime/stage 关联、绑定回调的新鲜度复查及 intent 构造退出 Coding；静态 Profile 构造提前到通用匹配前，不读取 Product/receipt 或执行 IO。

POSIX 原物化/请求绑定和物理修复已由 Harness 持有，本轮不重计这些既有共享实现。四类 POSIX payload/debt 值的原语义证明、指纹和 member 编码归已有 Worker payload value owner；名义字段/slots/构造仍留在 Coding，动态 depth/path 配额仍在原验证位置读取。两平台 pending 值共用一个校验实现，同时保留 POSIX 的 isinstance 与 Windows 的精确 identity 差异。Windows intent 值复用已有 RecordSchema 编码，保留 to_dict 的排序/list 形状、to_bytes 对 to_dict 的原动态分派、原无输出配额语义、wire/domain 和 from_bytes 配额。

本批 Coding −456、Harness +704、Hosting/其他生产 0，系统生产 +248行；累计 Coding −4,274、Harness +6,498、系统生产 +2,224行。测试累计 +58行，文档单列。C07 剩余15,992行，仍需至少5,860行退出。通用完整操作及名义适配带来新增成本，尚未取得系统净删减收益；不能把已有共享物化重新计为本轮去重，也不将 private 转发退出当作主要收益。

既有 payload repair/recovery/live-stage 与真实 POSIX candidate 消费者312 passed、14 skipped、1 deselected；intent/value/stage IO 消费者296 passed；import/C50/C51/C54 为192 passed，各组有交叠不累加。38个 Coding 文件的公开函数及名义字段保持原样；现有测试入口/参数/断言和 golden 不增加，只同步 intent 真实 import edge，并将原 native flush 故障口从已失效 Coding 名称改绑实际 stage IO owner。该原生路线仍未执行，不以更新 mock 作为 native 通过证据。

14个原机制/值校验体在明确的 owner/限额/错误 Profile 绑定后 AST 一致，Product/名义准入保留。Windows plan/materialize/bind/intent 与原函数168组逐事件对照，其中149组实际故障，每组两次调用，guard/authority 顺序、阶段残留、字节、发布丢失确认、重试和异常链均一致；还比较真实 request 验证和伪造 validator 的拒绝。使用真实 request/receipt/intent 值及原记录 IO 程序，物理效果和 guard 为受控模型，不代替 Windows 原生验证。

9个 payload/pending/intent 值的字段、全部 dataclass 元数据、slots、公开签名、wire 与18份原始 pickle、16项错误/配额观察与基线一致。该对照曾发现迁移将非法 member 错误并入非法 review，已恢复两种错误身份，最终一致。Linux lease 仅验证记录形状与 pickle，不把未验证的合成 runtime 数据当作真实物化证据。

剩余 POSIX offline/recovery 资源寿命协调、start gate、恢复总编排及全部112文件的处置仍须推进；本批不声明整个第三组或 C07 完成。

## POSIX payload 寿命与 start gate 批次

实现 owner 接受 POSIX payload 的 Product quiescence/GC/root 寿命归原 Package Product recovery owner。物化、pending planning、绑定和十三类恢复/读取/修复入口调用原 Worker programs；没有复制它们早已共享的物理机制。统一根借用 helper 只由固定命名动作选择完整既有 Worker 操作，Coding 不提供中间阶段或事实 supplier。review DTO 构造仍在原 guard/root 内；动态 root getter、原 GC write/read 区分、异常/取消与关闭顺序不变。Code 只保留名义值、Product/type 准入、错误/Profile、兼容入口和实际仍有消费者的别名。

同一既有 Product authority owner 也持有完整 POSIX start gate：精确 receipt/request 关联、当前 witness/closure 重读、原 Journal intent、原 pipe 分配、bound 记录、单字节 release、失败关闭及幂等 close。原实例状态和 pipe 仍为唯一 owner，不增加 gate 管理器或生命周期状态。Code 保留原名义类、构造的 Product receipt-owner 准入、错误 Profile 和原 public receipt_owner 返回类型。共享实现用完整 receipt authority/Journal 能力口，未把每一步回调给 Coding；没有新增实例字段，普通 class 的 dict/slots 外观和公开签名对照不变。

本批 Coding −296、Harness +535、Hosting/其他生产 0、系统生产 +239行；累计 Coding −4,570、Harness +7,033、系统生产 +2,463行。测试累计 +57行，文档另计。C07 剩余15,696行，仍需至少5,564行退出。主要收益是完整权限/资源寿命归位；typed ports、兼容适配和具名共享操作带来成本，仍无系统生产净删减，也没有达到过半退出。

首轮既有回归136 passed、62 failed、14 skipped、1 deselected；失败均来自恢复 golden 的旧删除注入点，原断言/数据保持不变，改绑实际 Worker Storage 后同份113项恢复 golden 全通过。136与113存在交叠，不能相加或将首轮宣称全绿。既有 import/C50/C51/C54 为192 passed，64源 mypy 和 Ruff 通过。C54 仅同步真实退出的 Code import edges；测试未扩展断言、参数、路线或 PR 门禁。

27个原完整执行体经显式名义/Profile/类型绑定和统一 root helper 展开后 AST 一致；构造、异常优先级和 root getter 位置被单独检查。start gate 与原类34组逐事件对照，26组实际故障，使用本进程独占的真实 POSIX pipe，比较 public 签名、dict 字段顺序、读/写句柄、Journal 事件、失败后的开放句柄与 close 顺序，全部一致。Journal/Product freshness 为受控能力，没有启动子进程，不替代原生 H6/Windows 路线。初始观察器漏接原 witness 符号，只修复观察器绑定，最终对照通过。

原类型字段、slots/pickle 值实现本批未改；39个 Code 文件的公开函数/名义字段与既有测试入口/参数/断言契约继续一致。start-gate activation-history 协调、gated settlement、恢复总编排和剩余文件尚待审查，不将 pipe owner 接通当作整条启动/恢复链已完成。

## Gated 恢复与 activation-history 协调批次

实现 owner 接受原 gated/orphan review、repair 和 settlement 完整操作归既有 Package Product recovery owner。它复用原 HistoryProofBindings、PayloadStorage、POSIX custody、registry 和 Supervisor Journal，保持 orphan 预读、GC/root guard、锁内重读、plan/receipt 关联、failed→process_settled CAS 和 lease 修复顺序。原名义 review 字段/slots/pickle 入口及真实 Product/type 准入留在 Coding；Worker history 持有五个派生证明属性。历史 owner 仍在原读取位置惰性绑定，避免提前读取及 Coding 历史模块循环依赖。

原 StartGateHistory 持有 append-position→C5 初始化检查→gate append 全部作用域。Coding 保留候选 trust 准入、错误 Profile 和原 activation Journal 构造；构造仍在 append-position 内执行，不预取路径或授予新的写权限。不存在第二个恢复器、账本或逐阶段回调。

本批 Coding −155、Harness +377、Hosting/其他生产 0，系统生产 +222行；累计 Coding −4,725、Harness +7,410、系统生产 +2,685行。C07 剩余15,541行，距过半退出仍需5,409行。测试累计 +57行，文档单列；新增类型边界、兼容适配及完整操作入口带来成本，尚未实现系统净删减。

既有 gate append/checkpoint/registered recovery/candidate 消费者188 passed、14 skipped、1 deselected；import/C50/C51/C54 为192 passed，68源 mypy 和 Ruff 通过。测试只同步实际 import inventory 与 receipt 故障注入 owner，不增加断言、参数、golden 或 PR 门禁。10个原执行体经明确绑定及 activation 构造 hook 展开后 AST 一致；4个真实名义值、8份原始 protocol4/5 pickle、全部字段/slots/元数据/公开签名及56组证明判据与基线完全一致。外部观察器起初组合了不合法 phase/failure 数据，修正观察器后两侧通过，未改 Product 验证。

上述为现有消费者、静态执行体和兼容值证据，未执行原生 Windows/H6，不证明全部故障路线。恢复总编排、证据 factory、其余112文件处置及全量交付检查仍未完成。

## Windows Provisioning 绑定与失效清理批次

实现 owner 接受完整 provisioning 绑定、intent 关联和失效选择后的 native cleanup 复核归原 WindowsProductWorkerProvisioningAccess。候选/receipt/request/原生计划关联、原 GC 内 intent 校验、身份构造、唯一 Journal 绑定和最后 currentness 检查按原顺序执行；Coding 保留平台/精确类型、活动 Coding runtime 准入、session scope Profile、实际 Journal/intent reader 及原公开构造入口。原 Journal 类、路径、state/receipt/request 引用不变，没有第二个 provisioning store。

失效选择的 cleanup 复核直接使用已有 WindowsProductWorkerPayload 的 inventory、completed-retirement/currentness 和原 WindowsRecoveryAdmission；只在原异常路线构造该纯 Profile，不预取历史或在只读检查执行清理。仍拒绝非 cleanup phase 写入，并保持 stale 异常及原因链。删除 Code 的 load/CAS 薄转发，公开方法从同一原共享 owner 继承；path 读取也归该 owner，签名和实际 Journal 无变化。

本批 Coding −166、Harness +197、Hosting/其他生产 0、系统生产 +31行；其中负担主要为原完整关联体迁移，另有12行净薄转发退出。累计 Coding −4,891、Harness +7,607、系统生产 +2,716行；测试 +59行，文档单列。C07 剩余15,375行，仍需至少5,243行退出，系统尚无净删减收益。

既有 snapshot/backend/native-bridge/cleanup-evidence 与 import/C50/C51/C54 为234 passed、51 skipped，原生 Windows 路线仍跳过。该结果在随后移除纯 load/CAS 转发前取得，最终直接继承另核对构造/path/load/CAS 的公开签名及48组双次调用，Journal/guard/失败事件和实例引用顺序与基线完全一致。70源 mypy、Ruff 通过。三段原完整执行体与声明的 owner/Profile 绑定后 AST 一致，原 public constructor 三个准入 guard 原样保留。失效清理与基线756组逐事件/异常链对照，其中436组实际故障，每组两次调用；使用受控 owner 效果验证原共享方法，不是 Windows 原生证据。测试只补齐真实导入 inventory，没有新增断言、路线或门禁。

## 注册态恢复证明与修复记录批次

实现 owner 接受 registered/no-effect 链中残留的三个 review 判据和修复 intent 的完整校验/编解码归原 Worker retention/payload value owners。原 Package Product recovery 已持有 lease、payload intent/重试/删除及 C5 结算，本批不重计那些既有共享执行体。Coding 保留全部名义字段、slots/pickle 路径、精确 plan 类型/Profile、错误和原公开入口；未移动字段来计算收益。注册态 gate/C5/receipt/lease/boot 关联及修复记录 envelope/version/字段/plan 的语义校验不再由 Coding 实现。

complete 与 registered repair 两个 codec 复用同一份七字段 plan 构造。两条路线各自保留原 envelope 和 version 校验位置；complete 在构造后检查 nested version，registered 在构造前检查，错误优先级不合并。没有新 Journal、恢复器或阶段回调，也未授予额外删除/修复权限。

原固定反射契约要求若干公开方法仍在 Code 类字典中，因此保留五个必要名义适配和 from_dict 原返回注解。它们仅调用共享方法，dataclass slots 使用显式 super 避免替换 class 的 __class__ cell 问题。完整实现仍已退出 Code，不能将这些兼容入口当成重复业务实现删除，也不能以此宣布整组迁移完成。

本批 Coding −117、Harness +188、Hosting/其他生产 0，系统生产 +71行；其中共用 plan 构造删除了一份重复的七字段构造体，其余主要为职责迁移及名义/类型成本。累计 Coding −5,008、Harness +7,795、系统生产 +2,787行；测试 +60行、文档单列。C07 剩余15,258行，距过半仍需5,126行。没有系统净删减收益。

首轮实际存在的恢复/修复 golden 和架构消费者为487 passed、1 failed；失败为原反射 API 形状，补回必要入口后受影响的57项 golden 全通过，其余已通过项不重跑且两组不可相加。初次命令另有一个不存在的测试路径，未执行测试，修正为实际 payload recovery 路径后才取得上述结果。3个真实记录的字段/dataclass 字段清单/slots/公开签名、6份原始 protocol4/5 pickle 字节及57项原 API/值/错误观察与精确基线一致；8个原完整执行体在明确 Profile/名义绑定及共用 plan helper 展开后 AST 一致。73源 mypy、Ruff 通过，既有断言/参数/fixtures 不变。

Windows 总编排仍未迁移：它当前调用八个分散 Code 入口，直接转换成阶段回调集合不符合本 Goal。后续需让现有 history、retirement、lease/native/C5 owners 提供完整操作并收拢实际绑定，再接总编排；本批未引入该回调方案，也未降低过半标准。原生 Windows/H6 与全量交付验证仍未执行，所有受控/源码证明均不替代 native 证据。

## Windows 完整崩溃恢复 owner 批次

实现 owner 接受原 lease-pinning/repair owner 扩展并更名为 WindowsProductWorkerCrashRecovery，收拢同模块现有 cleanup review、Supervisor/native/C5 结算程序，直接持有恢复总编排。原四个自由函数和原三字段 lease owner 已退出，没有同时保留第二套恢复实现。总入口按原顺序反复读取 orphan→验证 C5 authority→Supervisor→复读→native→复读→lease repair→复读→stage retirement→C5 settle；实际 stage proof/intent/删除/重放仍交给原 WindowsProductWorkerCrashStageRetirement。

Coding 仅构造一个无状态 Profile，绑定实际的 nominal record factories、Journal、完整事实读取能力、installed backend、C5 evidence/state-store 和已有 retirement 对象。它没有提供八个 action/stage 回调，没有缓存 root/事实或新增账本/恢复器。完整操作的原 platform/Product/type/attempt/review 准入随执行体在原首个 guard 位置运行；公开 Coding 函数、返回注解、名义 DTO/错误/slots/pickle 仍保留。九个动作复用同一原 platform/Product 三项检查，宏展开仍与原短路顺序一致；registry→GC→pinned root 的锁、原 Job 不可观察状态及每次重新读取/复核不变。

本批 Coding −207、Harness +211、Hosting/其他生产 0、系统生产 +4行；既有共享执行体的改组不重计为迁移收益，新增收益主要是完整总编排及重复绑定退出 Code。累计 Coding −5,215、Harness +8,006、系统生产 +2,791行。测试 +70行，文档单列；C07 剩余15,051行，距过半退出仍差4,919行。仍未实现系统净删减，也未达到整组验收。

首轮既有六类 crash 消费者、原恢复 value golden、CLI snapshot、import/C50/C51/C54 为289 passed、49 skipped、1 failed。失败来自 Code 为类型注解直接引用 Worker 私有 Profile；已将具体类型别名留在 Package Product 边界，Code 仅引用其 owner 类型，未扩大原 C50 白名单或门禁。受影响 C50/C54 复验16 passed；统一九处准入检查后的六类消费者及原 value golden 复验98 passed。各组有交叠，不累加。测试只把原故障口从已退出的 Code 变量改绑实际 shared/canonical fact owner，Windows snapshot 中两个暂停点改到实际完整 command，断言/参数化/fixtures 不变。74源 mypy、最后改动的 Core 单源复核和 Ruff 通过。

19个原完整执行体、公开及嵌套准入经明确 owner/Profile 绑定后 AST 一致；真实 Profile 中14个原 owner 身份及 evidence/domain/stage-reader 身份逐一核实。27个名义记录、54份原始 protocol4/5 pickle 字节、20项错误及字段/slots/元数据/公开签名与精确基线一致。总编排与原函数12,480组逐事件/结果/剩余状态对照，1,536组实际故障，每组连续尝试三次，覆盖操作前后失败、丢失确认及已完成边的重试。使用受控的有状态完整组件，不执行 native IO，不替代内层 command 和原生平台验证。

本批关闭原 Windows crash 总编排仍在 Code 的具体缺口；不代表全部112文件、其余恢复/批准/Session/Profile 边界或 C07 大部分退出已完成。Windows 原生路线、H6 与全量正确基线交付检查仍未执行，49项跳过用例不计为 native 验证。

## Provider 候选关联与回执 owner 批次

实现 owner 接受完整 Provider 候选证明归原 _ProductWorkerReceiptAuthority，直接复用原 POSIX/Windows serialized_admission、current_witness、manifest、payload 和 worker owner 读取能力。锁内顺序仍为 Base policy 复核→receipt witness→manifest/payload→候选验证→trust/reservation/declaration/executable/Provider 关联→既有 binding spec/envelope 构造→receipt witness 复核。真实 Provider Host 与 ordinary Session 的候选调用已接入，没有新增 Worker、候选账本、Provider 发布器或生命周期管理器。

Coding 保留原精确 receipt-owner/receipt/definition/provider/Base-binding 名义准入、query Provider 政策、Coding Base 选择及其 currentness 决策和公开函数签名。平台 Profile 在原 payload 读取之后取自 owner 的固定 class；两个 Code 名义 owner 与原 type dispatch 一致，instance 字段不能覆盖平台。该候选仍是 inert fact envelope，授予/发布仍由原 Capability/Graph owners 决定。原 Code 类、fields/slots/pickle 和错误身份未变，未用移动字段或压行计算收益。

本批 Coding −90、Harness +124、Hosting/其他生产 0，系统生产 +34行；累计 Coding −5,305、Harness +8,130、系统生产 +2,825行。测试仍 +70行，文档单列。C07 剩余14,961行，距过半退出还需4,829行。新增成本主要为原 common owner 的三项平台能力声明和一个完整 Base policy guard 类型边界；不是系统净删减，也不是整个 Provider/Host 链已完成。

既有两平台 candidate/Provider、CLI snapshot 与 import/C50/C51/C54 为227 passed、63 skipped、1 deselected，未修改测试/fixtures/参数/门禁。该回归之后仅将固定平台读取限定为 class Profile；两真实 Code 名义 owner 的独立对照证明结果与原 dispatch 一致，instance 覆盖被忽略，原正常路径不变。75源 mypy及最后 Core 单源复核、Ruff通过。完整原候选执行体和公开准入经明确 owner/error/platform 绑定后 AST 一致；原 Base policy 类及所有既有 authority 执行体 AST 均保持原样。平台、字段/版本与错误假设不以该源码证明替代原生验证；Windows/H6 路线仍未执行。

相邻 Capability bridge 的新基类草案未采用：实测 Code 仅减少57行、Harness增加124行、系统增加67行，主要来自新增类型/状态声明和必要名义转发，尚无已有组件复用收益。已恢复原 Code 实现并移除草案，不将其计入收益。该 identity/currentness/facet-grant bridge 仍是明确未完成项，后续应扩展现有 receipt/facet owner 的完整能力，避免再引入适配基类；本轮不因保留而降低过半目标。

## Provider Host 完整输入复核批次

实现 owner 接受原 _read_coding_worker_provider_inputs 的完整输入复核归既有 Session _worker_provider 组件。复用原 _QueryAuthority、candidate reader、原 Provider/worker admission 和后续 _prepare_worker_provider_binding；没有新增 Protocol、适配基类、状态对象、发布器或生命周期管理器。完整操作按原顺序执行名义输入/graph/callback 检查→binding spec 检查→Code 候选政策读取→current authority/binding 读取→候选、policy/revocation、native platform、receipt、binding、adapter/admission 关联→adapter freshness 检查。它不执行 grant、publication、release 或 native 操作。

Coding 的私有调用名仍作为原 Session 机制的政策绑定存在，绑定实际 Code receipt-owner family、capability authority 名义类型、完整候选政策、原平台类型政策及错误身份。两个真实调用方（公开 Host prepare 与 ordinary/native preparation policy capture）继续接入同一入口；既有公开 prepare、Code Prepared/Release/error 类及其 fields/slots/方法执行体 AST 完全未变。私有名不属于 __all__，实际调用方均使用原 keyword 形状；它没有进入持久化 JSON/wire 或新建接口分发器。

本批 Coding −64、Harness +82、Hosting/其他生产 0，系统生产 +18行；累计 Coding −5,369、Harness +8,212、系统生产 +2,843行。测试仍 +70行，文档单列。C07 剩余14,897行，距过半退出仍需4,765行。此次复用已有完整 authority 接口，未重复上轮弃用的 Capability 适配基类；该 Capability bridge 及其余 C07 工作仍未完成，系统尚未净删减。

既有两平台 candidate/Provider、CLI snapshot、共享 native-to-graph handoff 与 import/C50/C51/C54 为232 passed、63 skipped、1 deselected；未修改测试、参数、fixtures 或门禁。77源 mypy、Ruff 通过。完整原输入执行体和政策绑定、所有既有 Session 程序及公开 Code entry/classes 的 AST 均一致；使用原两平台 Code 名义类，对原私有 keyword 入口的28组无效输入观察，类型、消息及错误身份完全一致，未构造 Product 或执行 native 效果。原生 Windows/H6 路线仍未执行，上述证据不替代原生验证。

## 批准重放规划与 POSIX 完整操作批次

实现 owner 接受批准重放／代次规划归现有 Package Product authority 家族，原 Windows authority 直接继承同一实现；POSIX authority 持有完整 current、allow、revoke 操作，继续使用原 OptInJournal、候选选择和 installed native reader。Coding 保留真实 Product／trust 构造准入、requiredness／错误与名义值 Profile、原公开入口及 installed reader 的产品绑定。原 Code planner 和 Windows 私有转发同步退出，没有新建账本、恢复器、平台模式开关或阶段回调集合。

POSIX current 仍只调用原 journal；allow 保持 writable GC→候选／批准事实→native closure→平台复核→历史→重放规划→journal.change 顺序；revoke 保持 writable GC→root currentness→journal.change。Windows 原 current／allow／revoke 的 pinned descriptor 和前后 currentness 检查执行体保持原样，没有将平台差异抹平。重放返回原 opt-in 对象；错误身份、生成顺序和失败优先级不变。两平台此前已共用同一 Code planner，因此本次不是删除两份 planner；收益主要是完整机制归属和原私有转发退出。

本批 Coding −93、Harness +123、Hosting／其他生产 0，系统生产 +30 行；累计 Coding −5,462、Harness +8,335、系统生产 +2,873 行。测试仍 +70 行，文档单列；C07 剩余14,804行，距过半退出仍差4,672行。新增成本来自共享 authority 的显式类型／平台绑定及保留的公开名义入口，未将其称为系统净删减。

既有 candidate、两平台批准／V2、CLI snapshot 和 import／C50／C51／C54 回归336 passed、63 skipped、1 deselected；未改测试、断言、参数、fixtures 或门禁。累计80个源文件 mypy、Ruff、9项文档不变量及生成依赖事实检查通过；累计50份 Coding 公开契约／名义字段检查通过。九个原完整执行体、构造及 Windows scope 的源码对照一致；对两个真实 Code owner Profile 的640组规划观察，与迁移前完整 planner 的 JSON、原始 protocol4／5 pickle、错误类型／消息／code／异常链一致，其中474组错误、6组返回原对象。该探针使用受控 binding／admission 事实，不执行 native 操作，不替代原生 Windows／H6 验证。整组112文件处置、过半目标和完整正确基线交付检查仍未完成。

## 完整选中 Worker 策略证明批次

实现 owner 接受原策略派生完整机制归现有 Package Product receipt／activation authority 组件。它按原顺序执行 runtime／selected／opt-in／native 名义及身份关联→依赖闭合→trust→绑定唯一性及 admission→原候选验证→Session locator→runtime currentness→native closure 与 policy revision 指纹→原 ActivationPolicy 构造；沿用原候选验证和 authority-free policy 值，没有额外读取、发布、激活或清理效果。

Coding 保留 Product identity、信任类别、原名义 opt-in／native 类型、原生 Profile 映射、Session scope／指纹规则，以及 enabled、allowed products、requested owner、no-fallback 的明确构造政策。这些以固定 pure policy 绑定接入完整机制，不提供步骤／字段读取回调，不新增 Profile 数据类、注册器、管理器或执行状态。公开函数及其默认参数／返回类型、两原 nominal DTO 的字段／slots／方法、scope 算法不变。两平台 receipt authority 原来的真实政策调用已接入；原来它们就共用一个 Code 策略函数，此次只计一次机制迁移，不声称删除两份策略实现。

本批 Coding −98、Harness +154、Hosting／其他生产 0，系统生产 +56 行；累计 Coding −5,560、Harness +8,489、系统生产 +2,929 行。测试仍 +70 行，文档单列；C07 剩余14,706行，距过半退出还差4,574行。新增成本来自通用函数的显式政策边界、零状态事实方法声明和必要兼容入口；仍无系统净删减收益，不把固定政策绑定或已经共享的候选验证重计为整链收益。

完整原执行体经明确 Product／错误／scope／指纹及固定 constructor policy 绑定后 AST 一致；两原 Code DTO、scope 函数及其余既有 Package Product 程序 AST 保持原样。672组原完整函数与当前公开入口对照覆盖两平台、requiredness、新建／selected route、28种输入及正常／候选失败／currentness失败，观察640组错误、8个实际 ActivationPolicy，JSON、原始 protocol4／5 pickle、异常图及效果顺序一致；使用真实名义 envelope 和受控嵌套事实／候选效果，不执行物理或 native 操作。首个探针因 fixture 把只读 authority_revision 当可写字段而失败，已改用真实属性和完整字段；未修改 Product 掩盖该 fixture 错误。原生 Windows／H6 及整组交付验证仍未执行。

首轮既有回归326 passed、63 skipped、1 deselected、1 failed；唯一失败为 C51 精确 consumer 清单，候选模块新增了 activation policy 依赖。完整机制已调整到原本持有该依赖的 receipt／activation authority，继续复用原 candidate verifier；未扩大白名单或修改测试。移动调用点时曾误删 partial 的函数实参，fresh-import 对照立即失败，已补回并加强绑定检查，最终672组对照复验通过。原候选 owner 的通用程序保持原样，不保留两份机制。

最终 owner 调整后的真实 Product 事务、Windows receipt base 与 import／C50／C51／C54 为212 passed；与首轮覆盖有交叠，不累加。累计81源 mypy 通过，最终调整的3个源复核通过；Ruff、51份 Coding 公开契约／字段及原测试入口／断言／用户改动哈希检查通过。9项文档不变量和生成依赖事实通过。已重新生成全部112文件当前行数／类基类／静态引用事实；它不是112份职责已验收的证明，策略文件剩余通用 DTO 校验也明确列为未完成项。完整正确 PR 基线的 check-changed 仍须在交付前执行，当前只核对了适用检查计划。

## 完整 Session 输入组装批次

实现 owner 接受原 selected-Worker Session 输入的完整通用组装体归已有 Session _worker_provider 组件。它按原顺序执行 Provider 闭合／Worker spec→实际候选政策读取→owner snapshot→receipt owner 的完整 selected-manifest 读取→候选／trust／时效／admission／Product revision 关联→真实产品 Consumer 决策→原 Compiler→原 Worker request 构造。原嵌套异步 prepare 随操作归位，立即路径仍调用原 Host 完整命令，延迟路径仍 await 原 callback；没有提前启动、发布或另建清理寿命。

Coding 保留原 closed nominal 输入 guard、错误身份和查询 definition／owner policy 批准块；批准块仍在 stale 检查之后、Compiler 之前运行。三个真实入口（两平台 pending Host 和显式 operator query）仍调用同一个公开 Coding 函数，其通用协调体已退出。共享实现复用原 _QueryAuthority、PreparedSessionWorkerCapabilityComponent、Compiler 和 request 类型，仅新增一个完整 manifest 读取事实口；候选／Host 的粗粒度命令与真正的产品 Consumer 政策是固定绑定，没有阶段或字段 supplier。既有 _WorkerSessionComposition 的 select／compose／validate 保持原样，不重计为新共享收益。

本批 Coding −77、Harness +153、Hosting／其他生产 0，系统生产 +76 行；累计 Coding −5,637、Harness +8,642、系统生产 +3,005 行。测试仍 +70 行，文档单列。C07 剩余14,629行，距过半退出仍差4,497行；新增显式类型／事实读取口及必要公开转发成本仍高于迁出量，没有系统净删减收益。剩余 ordinary binding 的纯关联校验等仍须复核，不因名义 DTO 或此批通过就宣布整份文件或整 C07 完成。

既有两平台候选／CLI、原 composition golden、共享 Provider handoff／graph inputs 与 import／C50／C51／C54 为293 passed、63 skipped、1 deselected；测试、参数、fixtures、断言及门禁均未修改。82源 mypy、Ruff、52份 Coding 公开契约／字段及原测试／用户改动检查通过。原 Code 名义 guard、真实查询政策块、完整组装体（含嵌套 prepare）经固定政策绑定后 AST 一致；其余 Code 及原 Session 程序 AST 未变。

1,472组原公开函数与当前入口对照中，1,446组错误、418组实际到达注入失败点、26组成功请求；两平台×查询／非查询×立即／延迟的8条正常路线均明确成功。真实 resolver／admission／Compiler／request 值的 composition fingerprints、效果顺序、连续两次 callback generation、错误及取消异常图一致；候选／manifest／native prepare 和纯产品政策是受控完整口，故不替代真实 Product/native 准入。独立冷导入禁止 Coding，亦确认 type-only Product runtime 未加载；局部 callback 原本即为不可 pickle 的本地闭包，持久记录和公开 DTO 字段不变。Windows／H6 原生路线及整组交付检查仍未执行。

## 既有载荷事实契约复用与残留胶水删减

本批复用现有 PayloadPlan／EmptyPayloadPlan／PayloadMember／PayloadReview 只读事实接口，删除四个普通零 slots 方法基类里重复的21项事实字段声明；方法通过同一对象的 identity cast 读取已存在的事实契约。没有让名义 DTO 继承 Protocol，没有新增 ABC、字段、注册器或状态；真实 Code dataclass 的声明、slots、MRO 和实例形状不变。Registered repair 的私有 factory 类型也改为现有 PayloadPlan 事实接口，避免继续把无状态方法基类当作完整数据形状。

同步删除已退出真实链路的三个私有转发 _owner_bytes、_plan_fields、_unmarked_repair_fields，以及无消费者的 _WorkerOptInReader。现有 publication／Product commit 已直接调用 HistoryPublication.owner_bytes；载荷指纹、marker 和 repair codec 已直接使用 Harness 的 plan_fields／unmarked_fields。旧轮次中这些 Code helpers 曾有真实消费者，当前接线已改变，不重复计旧机制迁移收益。公开 __all__、无 __all__ 模块的默认公开名称集、实际 codec／quota／故障绑定保持原样；原 canonical plan_fields／unmarked_fields 以显式 re-export 保留，严格数据记录和原值持久化中不包含这些私有函数；删除依据同时包括真实 owner 接线和原记录／回归证据。回执 decoder、segment parser 及 _linux_receipt_line 仍有 Windows／V2／原固定探针消费者，全部保留；read_backend 的晚绑定故障口也未改成静态捕获。

本批 Coding −15、Harness −13、Hosting／其他生产 0，系统生产净 −28 行；累计 Coding −5,652、Harness +8,629，系统仍净 +2,977 行。测试仍 +70 行，文档单列。这里的 Coding 删减包括三个退出的转发、一个退出的 Protocol 及一个随之消失的 import 及相应分隔；保留的两个 re-export 也计入成本；Harness 删减是重复类型声明扣除8项 identity cast 的净额。没有新增完整机制迁移，不能靠这批胶水／类型整理宣称过半目标达成。C07 剩余14,614行，距至少10,134行退出仍差4,482行。

原固定值／载荷修复／完整恢复、owner commit、receipt base 和 prepared consumers 为224 passed；84源 mypy、Ruff、54份 Coding 公开契约／字段及原测试／用户改动检查通过。八个完整载荷方法在仅消除 identity cast／局部同对象别名后 AST 与原样一致；其余 codec／fact interface、Code 剩余函数／类及模块级绑定完整 AST 不变。与冻结基线对照9个载荷／intent／lease 值和3个 registered 值，24份原始 protocol4／5 pickle 字节、字段／slots／元数据／公开签名、16项错误／配额及57项原值观察一致。初次 scoped mypy 发现方法基类的旧 factory 注解仍假定完整事实字段，已以既有事实接口纠正；不新增接口或改变数据验证。原生 Windows／H6、全部112文件处置和整组交付验证仍未完成。

## Discovery 构造与选中 Session 归属证明

实现 owner 接受完整发现读取器构造归已有 Transcript _AttachedDiscoveryMethods：原 directory／GC 类型准入、Session／路径验证、原借用 owner／缓存字段初始化、标准 record codec 创建及 attached-owner 准入／capture 按原顺序执行。Coding 保留原构造签名，以固定 GC／Session 名义类型接入，并保留原错误身份、公开 getter 和动态读取配额。没有新增 Reader、注册器、继承层、记录或寿命管理器；此前已共享的实际 discovery／固定／复读程序保持原样，不重计迁移收益。

两个回执工厂中完全相同的选中 Session 证明也归现有 Package Product authority：读取当前文件→persisted→Header／runtime Session→cwd resolve／workspace→authority／discovery membership。复用现有 attached read port，仅补充实际 owner 已有的 persisted／cwd 只读方法。helper 接收原 Session、directory、runtime 和 Product 对象，在原位置读取其属性，避免把字段提前求值或拆成 suppliers。POSIX 随后的 bound-root 证明和 Windows 的更强 runtime currentness 检查保持原位置；没有统一两平台准入强度。Windows discovery 的 nullable Session 注解以 identity cast 在原参数读取点衔接，没有提前加校验或缓存该值。

本批 Coding −44、Harness +96、Hosting／其他生产 0，系统生产 +52 行；累计 Coding −5,696、Harness +8,725、系统生产 +3,029 行。测试仍 +70 行，文档单列。新增成本来自原构造入口兼容、明确名义政策参数和通用事实类型边界；完整构造迁移与一份重复 Session 证明删除分别计，不把此前共享读取程序算作新收益。C07 剩余14,570行，距过半退出仍差4,438行，系统尚未净精简。

原真实 discovery／attached append、native reader 与两平台 receipt golden、candidate／CLI、import／C50／C51／C54 回归509 passed、63 skipped、1 deselected；测试、参数、fixture、断言和门禁未改。原完整构造体经两项固定名义政策绑定后 AST 一致；两个工厂宏展开 shared proof 后完整执行体一致，余下 Code／Transcript／authority 程序未变。216组原构造／完整 Session 证明与当前实现对照比较部分实例字典、原对象引用、codec、效果顺序及错误图，含14组成功；使用真实 Code 名义 envelope 和受控整项 discovery／capture／Profile 口，Session 证明使用受控读取口和真实 Path.resolve，不代替 native 或 Product 准入。两原名义 gate／Session type 是固定参数，实例字段不能替换政策。

Scoped mypy 初次发现公共 Windows ctor 原有的 optional Session 值不再由本地条件流窄化，已在原读取点以 identity cast 解决；未改变该值的读取时刻或错误优先级。87源 mypy、Ruff 和56份 Coding 公开契约／字段、原测试／用户改动检查通过。共享 owner 冷导入禁止 Coding。原生 Windows／H6、全部112文件最终处置及正确 PR 基线全量交付检查仍未完成。

## Windows 原生批准写事务归现有 Backend owner

现有 Package Product backend owner 接管 approve／revoke 的完整写事务：写 GC gate→首次 currentness→借用同一 Product root→实际 journal.change→root 释放→再次 currentness→返回原 decision。Coding 保留真实 Wheel 审阅、review ID 批准判断、公开入口及原 owner 构造；current 与原 journal／CAS／IO 程序未变。操作接收原 owner 和完整 review，在原锁内位置读取 owner 属性与 approval，实际 Coding journal.change 覆盖仍是故障入口；不提前读取字段、不绕过覆盖，也没有增加生命周期管理器或账本。

一次不采用的 mixin 草案会改变 owner MRO 且增加无状态绑定，已退出；当前原 class bases、构造、current、公开签名及默认值保持不变。最初回归404 passed、49 skipped、1 failed，C50 指出 backend 对私有具体 journal 的新增依赖；已删除该依赖，通过一个完整 change 命令结构口调用真实 journal，不修改检查或白名单。最终批准／backend／C50 消费者222 passed、49 skipped，单独原失败项亦复测通过；两组覆盖不相加。两源 mypy 和 Ruff 通过，57份 Coding 公开契约／字段、原测试入口／断言及用户改动哈希检查通过；10项现有文档检查和依赖事实 renderer 通过。

两个原公开操作与当前入口324组对照，每组连续三次调用；225组实际触发注入，315组包含成功返回。使用真实 Code approval／decision 和原纯 replay／CAS，比较事件、完整记录、返回对象归属、错误图、写后丢失回执及幂等重试、嵌套清理、取消类异常、上下文抑制及原字段晚读取；GC/root 与 journal 为受控完整口，不代替 Windows 原生验证。完整旧写作用域经固定动作与原 owner 绑定后 AST 一致，其余原 backend 与整个 journal 模块 AST 未变。

本批 Coding −13、Harness +40、Hosting／其他生产0，系统生产 +27 行；累计 Coding −5,709、Harness +8,765、系统生产 +3,056 行。测试仍 +70，文档单列。这是完整操作归属收敛及两份原写作用域复用，新增明确命令类型边界和兼容入口成本仍超过退出量；不是系统净删减，也不足以作为大块迁移验收。C07 剩余14,557行，距至少10,134行退出仍差4,425行；后续须集中完整大块与实际重复删除。原生 Windows／H6、全部112文件最终处置和正确 PR 基线完整交付验证仍未完成。

## 源身份校验复用与退出的 Windows 私有转发

五个 Windows C5／receipt／Supervisor／launch intent／Provisioning 语义基类复用现有 _SourceBoundBaseWireMethods 的同一组七项源身份前置校验。方法仍按原次序逐项读取同一对象的 scope／store／source digest，不增加状态、Schema、Protocol 或字段 supplier；各流的 live digest pattern、密码运算、版本／记录／历史语义校验留在原位置。Opt-in 在 scope 中间多一项 OPAQUE 规则，未强行统一；C5 原有 last-record 预验证仍先于身份校验。三项新增类型声明只属于现有普通方法基类，原五份 dataclass 方法基类和公开 Code 记录的字段、顺序、slots 均保留。

同时删除 _require_coding_windows_product_bound_request 与 _require_retirement_root 两个已退出的私有转发及后者唯一使用的 import。精确基线中，前者由 Code launch-intent commit 使用，后者由 Code stage retirement 使用；当前真实 intent owner 已直接调用 payload_program.require_bound，四种退休与 orphan review 已直接调用原 Harness root verifier。两私有名不在明确 __all__、公开记录字段或 pickle 类中，也没有固定故障探针／动态注册消费者；不是仅凭搜索无匹配就删除。仍有测试消费者的 uncoupled C5 guard、真实 marker／file 读取口及公开入口全部保留。此前已迁移的主流程不重计收益。

本批 Coding −28、Harness −15、Hosting／其他生产0，系统生产净 −43 行；累计 Coding −5,737、Harness +8,750、系统生产仍 +3,013 行。测试仍 +70，文档单列。C07 剩余14,529行，距过半退出还差4,397行；本批是实际复用去重和死胶水退出，没有新增完整链路迁移，不能作为大块目标达成依据。对两平台回执构造的直接抽取已做成本审查：会新增多项 factory／初始化转接，当前不采用该方案，不因缩小 Code 文件就增加另一层协调。

既有五流、launch intent、四种退休／stage review 及原恢复值兼容为136 passed，8源 mypy、Ruff及57份 Code公开声明／原测试入口／断言／用户改动哈希检查通过。宏展开一处共享前置校验后，五个完整 validator 模块 AST 与原样一致；两个 Code 模块除指定私有定义／import 外 AST 不变。冻结基线的18个实际值、36份原 protocol4／5 pickle 字节、16项错误、全部字段／dataclass 元数据／slots／公开签名／历史 wire 完全一致。原生 Windows／H6、全部112文件最终处置及整组交付检查仍未完成。

## Resume 结算绑定归原 C5 组件

现有 Worker product_activation 接管原绑定对象的完整通用构造／匹配、读取原 C5 snapshot 后的锁内绑定，以及持锁捕获 coordinator 后的原 C5 settlement 检查。原 Coding 公开类和构造／bind／require_current 签名保留，matches 从私有方法基类继承原签名。对象仍只有原 receipt、context、coordinator、RLock 四个字段；原 C5 Coordinator 是唯一实际状态／结算 owner，没有第二个绑定实例、账本、恢复器或生命周期管理器。Code 继续在原位置执行准确的 Coding v2 intent 类型、effect owner 集合及 parent-context 判断，保留原产品错误身份与入口。公开 enroll／seal 和其原失败工厂不变；原私有 _snapshot 薄转发退出，绑定在原读取点直接调用其唯一的固定 C5 命令。

私有方法基类采用普通实例字典继承，公开 Code 类的原实例字典／weakref 布局、字段名／顺序、receipt/context 对象引用和 canonical RLock 类型不变；MRO 明确增加该私有基类。初始空 slots 草案被 mypy 指出不能写入原字典字段，已以原字典存储方式解决，未压制检查或增加字段容器。绑定原本因 RLock 不可 pickle，原公开类路径和相同 TypeError 保持；不宣称该活对象具有持久化契约。原记录／intent／context 的类和 C5 原程序未修改。

首轮原 Resume／Coordinator／import／C50／C51／C54 为284 passed；最终字典基类及错误工厂调整后，直接受影响的原 Resume／C5 路线19 passed，覆盖有交叠不相加。最终两源 mypy、Ruff、58份 Coding 公开声明／字段、原测试入口／断言及用户改动哈希检查通过；10项既有文档检查和依赖事实 renderer 通过。构造／matches／锁内 bind／currentness 的完整旧程序经固定错误与原直接 snapshot 命令展开后 AST 一致，准确 Code intent 政策块及其他 Code／C5 原程序 AST 不变。

9组原构造输入、72组原公开绑定行为对照（48组实际触发故障）及40次原／当前双线程竞争通过；比较字段／布局、公开签名、错误图、未知 parent、重复／换 owner 绑定、未知或过期 settlement、锁进入／退出失败及异常，竞争始终只有一个实际 owner 成功。使用真实 Code receipt／v2 attempt／context 与原错误类，C5 snapshot／settlement 为受控完整命令，锁和线程为真实 Python 对象，不替代平台原生恢复。外部探针首次因未加入工作树 tests 路径而导入失败，补齐探针路径后通过；未修改 Product 处理该探针环境错误。

本批 Coding −45、Harness +73、Hosting／其他生产0，系统生产 +28 行；累计 Coding −5,782、Harness +8,823、系统生产仍 +3,041 行。测试仍 +70，文档单列。通用绑定完整方法与真实消费者归位，但新增兼容公开转发和明确错误边界仍有成本；不将其算作系统净删减。C07 剩余14,484行，距过半退出还差4,352行；全部112文件最终处置、原生 Windows／H6 和正确 PR 基线整组交付验证仍未完成。

## 完整 Product Capability authority 归现有 owner

原 Package Product _worker_product_authority 接管完整 Capability authority：request／receipt／binding／owner policy 的身份闭合→保存原五个引用字段→原虚拟 current_authority 检查；后续每次 currentness 仍先执行 request validator、再核实 receipt witness／Worker owner、再读取实际 facet owner；facet 发行仍先核对当前 authority，再委托原 CapabilityWorkerFacetOwnerPolicy 取得原 grant 和固定 decoder。原调用／异常作用域和失败优先级保持。Code 的公开类、构造签名及完整闭合名义准入保留，原准确 owner policy 仍由产品提供；不搬走批准决策。Provider Host、operator query、composition 和准备适配仍引用同一 Code 公共类，真实候选已接通原操作。

通用方法位于原 Product owner，而非给底层 Worker facet owner 增加 Product 生命周期依赖；既有 C51 consumer 边界保持，未修改白名单。实例只是原 Code 对象，新增泛型方法基类进入 MRO，原五项字段／引用、dict／weakref offsets、公开 getter／方法签名和 Code 类 pickle 路径不变。一个固定静态错误工厂在原失败点读取 Code 错误类型；没有按阶段或字段注入 callback、额外 authority 容器或生命周期管理器。初次 mypy 指出 ClassVar Callable 的描述符推断不符合 staticmethod，已改为准确的静态方法契约，未压制检查。

既有完整候选（test-facts）、Capability query 与 import／C50／C51／C54 为204 passed、7 skipped；跳过的 host-runtime 路线不计作原生验证。最终两源 mypy、Ruff 及59份 Code 公开声明／字段、原测试入口／断言和用户改动哈希检查通过。固定错误工厂展开后，完整构造机制、getter、currentness 和 facet 发行 AST 与旧实现一致；原 Code 名义 guard、其他 Code 声明／__all__ 和全部原 Product owner 程序 AST 不变。

原／当前1080组对照覆盖两种真实 Code receipt-owner 名义类型及30种准入／身份／currentness／facet 情形，162组实际触发故障、36组构造成功；每个成功对象连续调用 currentness 与发行两轮。真实 receipt／runtime／request／binding／grant 值和固定 decoder，受控整项 receipt／facet-policy 命令；比较事件、错误图、原五项引用及布局、公开签名和原 protocol4／5 authority pickle 字节，一致。探针使用名义 owner／policy envelope，不具有实际准入或执行效果；原生 Windows／H6 仍未执行。

本批 Coding −73、Harness +102、Hosting／其他生产0，系统生产 +29 行；累计 Coding −5,855、Harness +8,925、系统生产仍 +3,070 行。测试仍 +70，文档单列。完整通用 authority 机制归位，Code 的名义准入及兼容构造入口和明确静态错误契约仍有适配成本，没有系统净删减收益。C07 剩余14,411行，距过半退出还差4,279行；全部112文件最终处置和正确 PR 基线全量交付验证未完成。

## Base 当前性与完整启动版本关联归原 Product owner

原 _worker_product_authority 接管完整 Base currentness 操作：原 receipt owner serialized admission→原 runtime getter→按原 Base／Capability／External Data 顺序逐个 assert-current 和 bounded reread→receipt witness；三种原读取错误仍在原作用域转换，其他异常与取消原样传播。一个三属性只读 base facts 接口读取实际 Code compilation，对象和选择不复制。Code 的准确 Base 名义类型、coding.base 名称、product／scope／runtime 准入与 policy_revision 保留；原公开 frozen slots dataclass 仅继承空 slots 泛型方法提供者，原字段、字段元数据及 pickle 类路径保留。共享 receipt authority 补充实际已存在的 product_runtime 只读契约，两个现有 POSIX／Windows getter 的执行体不变。

同一 owner 还持有完整新选中版本关联操作：原 runtime capture→原 receipt digest 对齐→历史 startup 的 package fingerprint／instance revision 和完整 worker policy identity 对齐→返回同一 selected 对象。Code 历史记录读取、receipt 发放、可选 Resume binding、真实 query／Consumer／平台命令仍按原顺序运行，capture budget 和错误身份由原入口绑定。没有把字段拆成 suppliers，没有增加启动管理器、Schema 或第二份协调状态；字段名和历史格式由通用关联操作解释，不能因此把整段证明视作产品批准。

既有实际候选、原 composition 兼容及 import／C50／C51／C54 为242 passed、7 skipped；host-runtime 跳过项不作原生验证。三源 mypy、Ruff 和公开契约／原测试／用户改动检查通过。完整 Base 复核程序经固定错误工厂展开后 AST 与原样一致；完整普通 Session bootstrap 在展开新 capture 入口后 AST 一致，包括 receipt／Resume／读取／后续产品决策顺序。其他原 Code／Product 程序及两个真实 runtime getter AST 不变。

720组原／当前 Base 对照中570组实际触发故障、90组构造成功；240组完整 startup 对照中160组实际触发故障。使用真实 Code nominal compilation／binding／receipt-owner envelope 与原 receipt／package／instance revision 值，runtime／GC／读取为受控完整口；比较连续调用的事件、错误图、源版本缺失／改变、读错误优先级、锁进入／退出及抑制，全部一致。Code binding 的三项字段／元数据／slots／公开签名／冻结行为和原 protocol4／5 pickle 字节一致，新 startup proof 返回原 selected 对象。模型不替代实际 Product 准入和原生 Windows／H6。

本批 Coding −56、Harness +122、Hosting／其他生产0，系统生产 +66 行；累计 Coding −5,911、Harness +9,047、系统生产仍 +3,136 行。测试仍 +70，文档单列。新增成本包含强类型事实边界、原名义记录适配、完整入口及原文件格式归一的增长；没有删注释或压行取得收益。两个完整证明归位，未迁出的 bootstrap 产品接线和其余 C07 处置仍须核实，不能据此宣布整链／整组完成。C07 剩余14,355行，距过半退出还差4,223行；全部112文件最终处置和整组交付验证未完成。

## 载荷内部入口直接复用已有方法

按 Coding SDK 接口约定，顶层 loushang.coding.__all__ 是稳定 Python SDK 边界；本批十个 C07 内部载荷名称不在该边界。当前实现代理在受委托的 Coding／Harness 重构职责内，接受下述精确十项内部 callable 变化；接受范围不扩大到 SDK、数据契约或其他入口。它们原本只有相同参数的一次 _PAYLOAD_CUSTODY 方法调用，现保留原模块名称，直接绑定同一既有 Product custody 实例的方法。删除的是十个重复函数层；原 Code 类型准入、materialize contextmanager、repair 的名义 guard 和全部其他 Code 执行体不变。真实旧入口名称继续可调用，参数位置／关键字／默认值形状不变，静态类型仍由配置了 Code 记录类型的原泛型实例推导。未新增适配器、运行时对象或转发层，也未移动字段来凑迁移比例。此前完整载荷机制已经属于 Harness，本批不重计为新机制迁移。

这是明确的内部 callable 元数据变化：名称现在指向绑定方法，__module__／__qualname__、运行时泛型 hints 及 Python 参数绑定错误前缀随 Harness 方法；不宣称这些信息或新绑定方法的 pickle 编码与旧函数相同。原全局函数 pickle 的模块／名称 lookup 仍解析到同一实际方法，二十条 protocol4／5 路径验证通过；必要 Code 数据类型、slots、wire／pickle 类路径未变。私有 _PAYLOAD_CUSTODY 为一次构造、固定寿命的模块 profile，原 _offline 也已经是该实例的方法；未发现替换该私有实例的配置或故障入口，原 lower IO／quota／Supervisor 故障口保持 live。只读 review／preview／list／reopen 直接使用原只读方法，未增加写参数或修复／删除权限。

原恢复故障轨迹、完整候选及冻结 SDK 身份／导出／签名／类型／pickle／smoke 为128 passed、7 skipped；四个真实 Code 消费源 mypy 和 Ruff 通过。原操作说明保留到九个实际 owner 方法，另一个 owner 已有同样说明；规范化文档文本保持，初次外部探针把函数和方法的原始 docstring 缩进一律视作字节契约而失败，已改为比较规范化文本，未修改 Product 处理该探针错误。十个实际 bound self／function、参数形状、旧 global pickle lookup 和无效 Product 域错误一致。

显式 alias 清单的源码审计确认：除指定十个函数声明退出及对应别名外，原 Code 模块 AST 不变；除操作说明外，全部原 Harness 执行体 AST 不变。其余60份 Code 声明／字段、原测试入口／断言与用户改动哈希保留。原 audit_public_contracts 工具仍保留，其“所有内部模块函数声明必须不变”的假设不适用于这十项已记录变化；新审计仅允许精确十项别名，稳定 SDK 用既有独立冻结测试核实，不修改测试或门禁。

本批 Coding −64、Harness +13、Hosting／其他生产0，系统生产净 −51 行；累计 Coding −5,975、Harness +9,060、系统生产仍 +3,085 行。Harness 增长仅是保留操作说明，测试仍 +70，文档单列；不是靠删说明取得净收益。C07 剩余14,291行，距过半退出还差4,159行。本批属于真实复用后的重复胶水删除，未完成的完整链、全部112文件处置和整组交付验证仍保留。

## 两平台完整回执创建归现有 authority

原 Product Worker receipt authority 接管两个完整选中回执创建操作：原名义 Product／runtime／Plugin／Session 准入→原 Session-file 所有权证明→平台 runtime／root 关联校验→原16文件／16MiB manifest 读取→原 opt-in／discovery owner 构造→同一个 Code receipt owner。POSIX 原 session_id 缺失检查与 selected-root 六项关联保留；Windows 的准确类型准入及更强 runtime 当前性检查保持在原位置，不把 nullable session_id 提前改为另一种失败。已有 Session 证明不重计为本批新能力，没有新建账本、恢复器或状态容器。

Code 的真实构造函数、字段和 MRO 不变，公开 Product-native 入口仍先从产品托管读取批准的原生 release，再调用原模块入口；不会接受新增的调用方 digest／profile／launcher 参数。两个入口名称直接绑定原 Code 类在既有 Harness authority 上的创建方法；与前一批一样，它们不属于顶层稳定 SDK。当前执行代理在已授权 Coding／Harness 职责内接受精确两项内部 callable 元数据变化：参数位置／关键字／默认值形状保留，运行时注解、module／qualname、Python 参数绑定错误前缀和新 callable pickle 编码随共享方法。原四条 protocol4／5 全局函数 lookup 仍可读取；不宣称新旧 callable 编码相同。必要的 Code 数据 pickle 类路径不变。

五个静态 getter 只在原查找时机返回两平台模块中实际的 Session／Discovery／OptIn 类型，保留晚绑定和先查构造器、再求参数的求值顺序；不按字段或阶段传入 callbacks。固定错误标签、Session 产品名称和原 capture budget 由 Code profile 绑定；预算与后续64文件复核预算独立，不合并故障或配额入口。完整流程由已有 Harness owner 持有，原 Code 协调体删除。

既有完整候选、discovery、原 receipt access／issue ordering／Windows receipt 兼容及冻结 SDK 为85 passed、7 skipped；六个实际生产／消费源 mypy 和 Ruff 通过。现有 import／C50／C51／C54 为192 passed，文档10 passed，依赖事实 renderer --check 通过；没有改测试或门禁。源码证明展开固定类型和配置后两段完整操作体与原实现一致；原 Code 构造、Product-native wrapper、其余 Code 与所有原 Harness 程序 AST 不变。公开声明审计仅为既有十项载荷别名加这精确两项创建别名设例外，其他60份 Code 声明／名义字段、原测试入口／断言及用户改动哈希保持。

原／当前1776组逐事件对照中464组实际触发故障，每组两次调用，覆盖真实名义 Product／runtime／root／Session／directory envelope、原 Session-file 完整证明、平台差异、active／detached、缺失或错配 Session／root、读取与构造故障和取消。原校验错误身份、优先级、事件、原对象传递一致。实际构造副作用、manifest／opt-in／discovery 为受控完整操作，不能代替真实 Product 准入或原生 Windows／H6。外部探针初次遗漏迁出 Code 的历史注解导入，补齐探针命名空间后通过，未修改 Product 来处理探针问题。

本批 Coding −109、Harness +181、Hosting／其他生产0，系统生产 +72 行；累计 Coding −6,084、Harness +9,241、系统生产仍 +3,157 行。增长包括明确的强类型创建入口、名义类型绑定和保留错误／预算契约，不作净精简收益。测试仍 +70，文档单列；C07 剩余14,182行，距过半退出仍差4,050行。全部112文件最终语义处置、完整链路验收和整组交付检查未完成。

## 当前验证与限制

原有 preparation/checkpoint/history join/Package reference 回归16项通过；加入原 cutover record 与 persisted bases 消费者后25项通过。最后覆盖整组六流、Desired/GC、cutover 与持久化的14个既有文件为58 passed、1 skipped；三组覆盖有交叠不相加。导入边界及原C50/C54为181 passed，六源 scoped mypy、Ruff及生成依赖事实通过。
原 staged-publication 故障用例只将读写注入点移到实际 WindowsPrivateReceiptIO，既有断言和测试入口未改变。两份现有架构清单同步当前模块归属，不新增检查、路线、平台或 PR 门禁。
已与精确基线对照3个实际名义记录、6份原始 protocol4/5 pickle 字节、字段/slots/构造与公开方法签名及8个错误；全部一致。三个公开事务与原函数逐事件对照754组，其中688组实际注入故障，比较两次调用、锁/IO/构造顺序、异常链和剩余字节，一致；模型证据不代替原生 Windows。
测试沿用本会话已批准的 C07 私有目录，仅设置命令环境；运行时测试首次在 sandbox 外通过管理 wrapper 执行。
Windows 原生 LPAC/Job、真实崩溃路线尚未执行；合成事实和跨进程记录探针不作为原生平台证据。

## 剩余工作

继续复核证据 factory、回执/批准记录、Provider/Session 消费者及全部112文件的当前处置，优先复用已有能力并删除重复机制以降低系统成本。
全部112文件均须更新职责与处置，区分产品政策、必要名义入口、迁移、复用删除；重新审查旧轮次保留理由，Coding 类型或固定名称不单独构成保留整个实现的理由。
每批计入 Coding/Harness/Hosting/其他生产代码及系统总量，测试和文档单列；系统成本与实际重复删除、职责迁移分别报告。
本轮尚未达到多数退出目标，未提交 PR 或交付，不修改原轮次已完成的历史证据。
