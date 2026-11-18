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

## 历史与恢复内部入口直接复用

本批删除八个 Code 模块中十三个纯转发函数，原名称直接引用已有 CheckpointHistory、RetainedHistoryReader、Prepared／Preview classmethod、GC revision join、Windows crash-history predicate 和历史名称函数。既有机制此前已属于 Harness，本批只计重复胶水删除，不重计完整机制迁移。保留三个有明确冻结签名约束的候选：普通 Session compose、Windows backend candidate／material inspection。当前执行代理在已授权职责内接受精确十三项内部 callable 变化，范围不扩大到稳定 SDK、记录或其他入口。

这些内部名字的参数位置／关键字／默认值形状不变，运行时注解、module／qualname、Python 参数绑定错误前缀和新 callable pickle 编码跟随实际 owner。引用在模块初始化时绑定到原固定实例／Code class／函数，不再每次重查 Code 的对应私有绑定；未发现这十三项的配置替换或实际故障注入口，底层 IO／quota／事务故障点保持。所有原 import 名称仍可访问，必要的失去本文件注解消费者的类型改为显式同名 re-export；不删除隐式模块属性。Prepared archive 名称在原 Code class 创建后绑定，真实初始化与消费者通过。十三项绑定／参数／规范化操作说明、二十六条旧 protocol4／5 全局 lookup 和原无效输入或纯结果核对通过；不宣称 callable 新旧编码相同。没有新增写参数，GC 与恢复观察仍无删除或修复权限。

源码检查确认：除十三个明确函数与别名及同名 import 拼写外，八个模块的全部原程序／类／字段／__all__ 和 import 绑定保持；所有 Harness／Hosting 与测试文件相对上批均无修改。精确例外清单现在包含前两批十二项及本批十三项，其余66份 Code 公开声明／字段、原测试入口／断言和用户改动保持。既有历史／checkpoint／prepared／preview／crash／实际候选为17 passed、7 skipped；GC 名称、历史证明及冻结 Session composition／backend DTO 为211 passed、1 skipped，十个生产／消费源 mypy 和 Ruff 通过。最初测试命令引用了不存在的 Windows GC 文件，未执行测试，改用已发现的真实 gc_names 路线后通过；未改变 Product 或测试。

本批 Coding −87、Harness／Hosting／其他生产0，系统生产净 −87 行，所有原操作说明已经保留在真实 Harness owner，不靠删注释取得收益；测试无新增。累计 Coding −6,171、Harness +9,241、系统生产仍 +3,070 行，测试仍 +70，文档单列。C07 剩余14,095行，距过半退出还差3,963行；这不是整链或整组完成，全部112文件最终语义处置和正确 PR 基线全量交付验证仍未完成。原生 Windows／H6 未执行。

## 批准输入与原生闭合事实的完整校验归原 facts

已有 ProductWorkerOptInFacts 与 ProductWorkerNativeClosureFacts 接管两项完整值校验。批准输入依次核实三个身份、artifact digest、平台、owner／kill-switch generation 与 bool requiredness；原生闭合事实依次核实平台／catalog identity 和两个 digest。原短路顺序与错误文本保持。Coding 保留原名义 frozen dataclass、全部字段／slots／MRO／构造和公开方法签名、原 RecordSchema 编解码、平台 profile 清单及规则／错误标签，__post_init__ 只调用既有 facts 上的对应完整校验。未新增类、Protocol、callbacks、Schema 或第二份校验状态，也不向普通 H facts 自动注入构造准入；只由原 Code 构造显式调用。这些是 authority-free 数据，不授予启动或批准权。

当前执行代理在已授权 Product／Harness 范围内接受一次构造内固定规则引用的边界：私有 max-text／regex 引用从原 Code 每一步全局查找改为每次校验调用时绑定，调用前覆盖仍生效；平台映射仍是原 live 对象。无需支持验证中途替换私有模块标量／pattern 来改变剩余步骤；不声称此类模块重绑定完全等价。实际顺序、pattern／membership 故障和取消仍在原字段检查点触发，不引入更早的规则有效性校验或平台写权限。保留这项明确差异，避免为几个私有常量引入字段 suppliers。

固定规则展开后，两项原完整校验体 AST 一致；其余 Code 程序、类型声明、公开函数签名、字段和 H 原 facts／candidate／生命周期程序不变，既有25项内部 callable 例外范围没有增加。原／当前6174组构造对照中5915组为无效输入、259组成功，覆盖调用前文本限额／regex／平台映射覆盖及组合错误优先级；另20组 pattern／membership 事件对照中12组实际故障或取消，一致。两个真实 Code 记录的字段元数据、slots、MRO、构造签名、wire 及四份原 protocol4／5 pickle 字节与读取一致。模型只验证数据，不作为平台原生证据。既有 opt-in／Windows semantic base／backend DTO／真实候选为43 passed、7 skipped，六个实际生产／消费源 mypy 和 Ruff 通过。

本批 Coding −27、Harness +60、Hosting／其他生产0，系统生产 +33 行，含明确的校验入口类型和 Code 规则适配成本。累计 Coding −6,198、Harness +9,301、系统生产仍 +3,103 行；测试仍 +70，文档单列。C07 剩余14,068行，距过半退出还差3,936行；两个完整校验归位不等于完整执行链验收或整组完成，全部112文件最终处置与整组交付验证继续保留。原生 Windows／H6 未执行。

## 崩溃清理证据的完整历史工厂归原 evidence owner

既有 WindowsWorkerCleanupEvidence 接管完整 crash factory：调用原只读 orphan-runtime review→关联原 receipt→检查 request／identity fingerprints、Supervisor 的严格 True/process_settled 及 payload 已退出→分配同一个 Code authority→按原顺序保存原七项字段。一次完整 review 命令仍由原 Product reader 执行，未拆成字段 suppliers。Code 的 for_crash_recovery 公开 classmethod、原 OS／准确 Product／receipt 类型／product-id 准入和错误顺序保留，既有恢复程序继续调用同一 Code 入口。没有新恢复器、evidence class、生命周期或持久状态；H 只保存原 Product 不透明引用，没有导入 Product 层或获得原生／删除权限。

正常构造和 Resume enrollment 当前保留：它们的准入后主体主要是必要字段绑定，单独移动字段不是本批机制收益。原 host／boot identity 域、current_tree_witness 接线及 changed-boot／expired-lease 返回 False 的边界不变。H 的空 slots、Code 字段／实例布局／MRO／公开签名／pickle 路径保留；Code 正常构造仅补同一 Product 引用的准确类型注解。初次 mypy 指出 Self 工厂不能直接向空 slots 抽象基类写入子类字段，已使用七个固定 builtin setattr，保留原虚拟 __setattr__ 调度、顺序和失败行为；没有移除 slots、使用 object.__setattr__ 绕过 setter 或压制类型检查。

源码完整展开新工厂并规范化固定 setattr 后，原 Code 全模块 AST 一致（另一个差异仅为上述局部类型注解）；全部原 H 算法、准入、构造与读取程序不变。现有25项内部别名例外没有扩大，其余66份 Code 声明／名义字段、原测试入口／断言和用户改动保持。540组原／当前对照中150组实际触发读取／字段／分配／setter 故障或取消，每组两次调用；实际 Code/Product/receipt/review/attempt/record 名义 envelope 的读取、错误、部分对象字段和重试轨迹一致。原 Code authority 的 dict／weakref offsets、MRO、公开 classmethod 签名和两份原 protocol4／5 pickle 字节／读取一致。完整 Product review IO 与 Product 构造受控，不能代替真实准入或原生 Windows。

既有 Windows cleanup／crash cleanup／native settlement／Supervisor settlement／C5／Resume 为17 passed、1 skipped，三个实际 owner／消费源 mypy 和 Ruff 通过。本批 Coding −16、Harness +36、Hosting／其他生产0，系统生产 +20 行；累计 Coding −6,214、Harness +9,337、系统生产仍 +3,123 行。测试仍 +70，文档单列；C07 剩余14,052行，距过半退出还差3,920行，全部112文件最终处置与完整交付验证仍未完成。原生 Windows／H6 未执行，不把本工厂完成视为整条生命周期或整组完成。

## 首组18文件的当前职责处置

本次逐项复核首组冻结库存和真实共享 owner，详见下表。文件列统一省略 `package_product_worker_windows_` 前缀；H owner 省略 `loushang.harness`，路径中的 `history` 指 `worker.history`。基线3,379行，当前1,879行，累计退出1,500行；此累计含此前各批，不当作本次新迁移。本次仅退出三个私有残留常量和无消费者 re 导入，净减3行，Harness／Hosting／其他生产和测试无增长。

| Code 文件 | 基线→当前 | 实际共享 owner | Code 保留与未完成 |
| --- | ---: | --- | --- |
| `base_files.py` | 25→22 | `worker/history/_windows_sources:WINDOWS_WORKER_BASE_FILES` | 保留原四个名称与旧模块导出，实际文件集合直接引用 H；无第二份命名规则。 旧显式 __all__ 不增加 cutover 名称；存在的模块属性仍保留。 |
| `c5_base.py` | 91→80 | `worker/history/_windows_c5_base:_WindowsC5BaseMethods` | 保留 Code C5 replay 名义字段、retained-attempt 类型、wire profile／动态容量及公开签名；完整状态与 tombstone 重放在 H。 Code 的 RecordSchema 只绑定真实 Code 记录 codec，不另写重放器。 |
| `checkpoint.py` | 466→212 | `package_product/_windows_worker_history:publish_windows_product_worker_checkpoint` | 保留 checkpoint 名义字段、批准／join 类型、备份域和容量、Code Product 准入及真实 IO／journal 接线。 H 持有完整读／发布／阶段重试事务；Code 的 _current_checkpoint_under_guard 只是实际家族绑定。 |
| `desired_references.py` | 230→56 | `package_product/_windows_worker_references:_WindowsDesiredReferenceMethods` | 保留 Code 名义字段、workspace／coding 政策和 receipt-base／preparation 类型绑定。 Desired 历史／当前引用关联与摘要完整程序在 H，不因字段类型把证明留回 Code。 |
| `gc_history.py` | 239→89 | `package_product/_windows_worker_recovery:require_windows_product_worker_settled_history` | 保留真实 Code Product 准入、借用 Product 属性和实际 Code journal／inventory／job-observer 接线。 H 统一已退休历史、C5 与严格原生不存在证明；只读能力不获得退休／修复权。 |
| `history_bases.py` | 184→79 | `package_product/_windows_worker_history:guard_windows_product_worker_history_bases` | 保留 read／publish 两个显式入口与 Code Product 准入、实际 checkpoint/references/IO/容量绑定。 完整六流发布及精确字节重试归 H；publish bool 仍由原两个入口固定选择。 |
| `history_cutover_preflight.py` | 76→48 | `package_product/_windows_worker_history:review_windows_product_worker_history_cutover_candidate` | 保留 Code Product 准入和原 inert marker 类型、持久化／checkpoint 实际读入口。 H 负责 quiescence／GC／双重读取关联；本入口没有 marker writer，不声称已经实现真正读写 owner 切换。 |
| `history_cutover_record.py` | 148→80 | `worker/history/_windows_persisted:_WindowsHistoryCutoverMethods` | 保留 Code record 字段、persisted 名义类型、RecordSchema、4KiB 动态限额及公开入口。 require_persisted_bases 仍有通用相等性复核，应评估与现有 H cutover owner 合并；不把整份文件当永久产品政策。 |
| `history_join.py` | 93→70 | `worker/history/_windows_history_join:_WindowsHistoryJoinMethods` | 保留六个 Code base 字段与准确家族／preparation 名义绑定、公开 from_semantic_read 签名。 完整跨六流关联与校验归 H；没有 Code 第二份 join。 |
| `history_preparation.py` | 232→111 | `package_product/_windows_worker_history:prepare_windows_product_worker_history` | 保留 Code preparation 字段／嵌套 snapshot codec／动态8MiB限额、Product 准入和 IO 接线。 H 持有捕获、stage／published 比较、原子发布与重试的完整事务；公开 create／require 签名兼容。 |
| `history_sources.py` | 530→260 | `worker/history/_windows_sources:_WindowsHistorySourceSnapshotMethods` | 保留四个 Code 名义记录、真实 Code recovery family、Product 准入与 source/file/total 容量 getter。 H Sources 负责文件／摘要校验与捕获，H Product history 负责 quiescence／GC／语义捕获；容量和 Code reader 故障口仍 live。 |
| `launch_intent_base.py` | 113→102 | `worker/history/_windows_launch_intent_base:_WindowsLaunchIntentBaseMethods` | 保留 Code replay／intent 字段、准确 Code intent codec 和错误类、wire profile／动态16MiB容量、公开签名。 完整源身份、intent retained/replay 关联归 H；Code codec 调用既有 intent.from_bytes，非第二份 decoder。 |
| `opt_in_base.py` | 98→87 | `worker/history/_windows_opt_in_base:_WindowsOptInBaseMethods` | 保留 Code replay／decision 字段、准确 decision/error/replay 类型、wire profile／动态32MiB容量、公开签名。 完整 opt-in retained/replay 机制归 H；不把 stricter scope 语义与其他基类混用。 |
| `package_references.py` | 303→129 | `package_product/_windows_worker_history:capture_windows_product_worker_reference_inputs_under_guard` | 保留 Code reference 字段、准确 Desired／join／backup 类型、Product 准入和实际 backup observer。 完整 Package lease／backup／Desired 闭合归 H Product references 与 history，observer 仍是产品证明。 |
| `persisted_bases.py` | 257→195 | `package_product/_worker_windows_attempt:read_windows_product_worker_persisted_bases` | 保留 Code 七个值字段、真实六流类型／codec、Product／root 准入、live limits 和循环打断的 marker decoder。 H 持有 ACL／源字节／head／六流读取复核；Code decoder 中 from_bytes→require_persisted_bases 以及 marker 非空后置条件仍待评估，不能整份默认保留。 |
| `provisioning_base.py` | 106→93 | `worker/history/_windows_provisioning_base:_WindowsProvisioningBaseMethods` | 保留 Code retained／base 名义字段、Code native record codec、wire profile／动态32MiB容量及公开签名。 H 完整验证 native phase/witness／retained attempts；Code 只绑定实际 record.from_dict。 |
| `receipt_base.py` | 93→82 | `worker/history/_windows_receipt_base:_WindowsReceiptBaseMethods` | 保留 Code receipt/replay 类型、准确 Windows profile／coding Session namespace 政策、wire profile／动态32MiB容量和签名。 H 持有 receipt sequence／历史 allow／tombstone 关联；平台／Session 域由产品绑定，不能按统一 opaque 校验代替。 |
| `supervisor_base.py` | 95→84 | `worker/history/_windows_supervisor_base:_WindowsSupervisorBaseMethods` | 保留 Code replay 字段、实际 WorkerAttemptRecord codec、wire profile／动态32MiB容量和公开签名。 H 持有 Supervisor revision／retained attempts／tombstone 重放，Code 无第二份状态机。 |

这次退役的两个 `_DIGEST` 与一个 `_BASE_KEYS` 已不被实际 Code 类或 H profile 读取；真实验证器直接使用原 H semantic-contract digest／base-files，未换校验规则。源 quota、RecordSchema decoder、JSON 故障入口与公开 record 方法仍保留；`WINDOWS_WORKER_BASE_FILES` 的原模块属性显式同名 re-export。删除依据包括真实继承校验体／profile 绑定、显式导出、存量 wire／pickle 字段与现有故障注入口，静态零匹配只作辅助。

当前17条既有测试路径为272 passed、1 skipped，包含六流旧 wire／原 pickle、来源故障与 persisted IO golden；此为受控平台事实和真实文件/codec，不代替原生 Windows。切换预检只返回 inert marker，不宣称实现真正读写 owner 切换或获得删除权。残留 Code persisted 比较／marker 后置条件明确列为待处理，不把所有具名类型文件整体判为产品政策。当前接受角色为本任务执行代理，接受范围为本次逐文件职责事实与私有残留删除；全部112文件和整链／过半目标尚未验收。

普通 Session 的约196行协调体也已重读：原 selection proof、candidate、provider selection 和图合成实际已在各现有 H owner，剩余真实 Product／平台／Session 工厂接线不能通过大量阶段 callbacks 机械搬运或重复计为共享机制收益。此结论不阻止继续抽取其中独立的通用关联证明。当前累计 Code −6,217、Harness +9,337、系统生产仍 +3,120行；C07 余14,049行，距过半退出还差3,917行，不降低验收标准。

## 六流 semantic-base 创建入口复用公共 owner

六种 Code semantic base 的 from_semantic_read 不再各保留相同的单调用方法，改由原 _WindowsPreparedSourceMethods 提供一份公共入口。该入口仍调用 cls._from_prepared_history，原各流类型检查、prepared.require、source/recovery 关联、记录构造与错误均由原方法执行；没有复制已有机制，不重计为新事务迁移。Code 的 C5／intent／opt-in／provisioning／receipt／Supervisor 名义类型、准确 preparation／replay／codec profile、字段／slots／MRO／record 路径和 replay 方法全部保留，原导入名称显式同名 re-export。

这保留了原虚拟调用，而不是把私有 helper 函数对象直接另挂一个名字；公共 base、Code class、Code subclass 对 _from_prepared_history 的覆盖、原 _from_source_read 分派都继续生效。入口在同一已经存在的 H base 上，没有新基类、Protocol、配置容器、callbacks、状态或生命周期。Self 使实际静态结果继续推导为对应 Code 类；九个真实生产／消费源 mypy 通过。

当前执行代理在已授权 Coding／Harness 职责内接受精确六项 leaf 方法的继承与反射变化：Code 属性和调用参数位置／关键字／默认值形状保持，函数 module／qualname、运行时注解和 Python 错误参数绑定前缀属于 H 入口，Code class.__dict__ 不再重复持有方法。它们不属于顶层 Coding 稳定 SDK；不改变原必要数据身份和构造签名，也不扩大前25个模块 callable 例外。旧记录 wire／pickle 和旧 bound classmethod pickle 分开验证，不宣称所有方法反射信息相同。首组表中的方法签名保留理由在本批限定为实际参数形状与数据构造身份。

原六份方法体与新入口的一次虚拟调用 AST 一致；除六份重复方法与同名 import 拼写外，六个 Code 模块全部原 AST 保持；所有原 H prepared/source 程序也不变。现有 first-history 家族272 passed、1 skipped，含原六流 wire／历史 record pickle、source IO 与 persisted IO golden；Ruff 通过。独立探针使用现有实际六流语义样本、Code 和空 slots 子类，132组行为对照一致，其中54组 hook 实际故障或取消；公共／Code／子类三层 helper 覆盖与重复调用保持，十二份原 bound classmethod protocol4／5 pickle 字节与读取一致。探针初次构造不一致 semantic fixture 时被原数据校验正确拒绝，修正探针设置后重跑；未修改 Product 或既有测试。

本批 Coding −48、Harness +7、Hosting／其他生产0，系统生产净 −41 行；测试无新增。累计 Coding −6,265、Harness +9,344、系统生产仍 +3,079 行；测试仍 +70，文档单列。C07 余14,001行，距过半退出还差3,869行；首组表更新为当前1,879行，历史 prefix31 的18文件证据保留为当时的1,927行，不把重算差额重复计收益。全部112文件处置、整链与过半退出验收及原生 Windows／H6／完整交付检查仍未完成。

## 双平台 opt-in 与审阅入口直接复用

POSIX／Windows opt-in owner 不再各声明 current／allow／revoke 的同参数 super 转调，直接继承已有 Package Product authority 的完整操作。Code 仍保留原 Product／trust／平台准入、journal 接线、原生闭合与 backend 选择；原共享锁、currentness、选中版本、批准关联和 CAS 程序完全不改。已有 Generic 返回参数保持六项静态结果为实际 Code decision；未增加 H 方法、Protocol、回调或实例状态，也不将旧共享事务重复计作本批迁移。

删除 reserved review 的三个测试专用私有候选校验转发，以及 stage review 的两个测试专用私有 IO／marker 转发。既有消费者直接调用真实 Code-profiled review 类方法和 WindowsStageInspection；原用例、参数化、断言、错误期待和 IO golden 数据保持。原 ACL 模块属性显式同名 re-export。旧 facade 不属于顶层稳定 SDK 或持久化记录字段；生产恢复 owner 本来就直接使用上述真实实现。

当前执行代理在本任务授权职责内接受精确六项 opt-in leaf 方法的继承变化：参数位置／关键字／默认值和名义 owner 不变，函数 module／qualname、运行时泛型注解、错误参数绑定前缀及 class.__dict__ 归属变化；不宣称这些反射值相同。36组原方法分派／实际 owner 故障观察和十二份原 bound-method protocol4／5 pickle 字节／读取一致，涵盖中间 MRO 覆盖；原生批准 DTO 的四项具体返回签名受既有兼容探针约束，本批保留。

四条既有消费者／兼容测试路径退出0，247项进度全部通过，包含原 stage IO golden；五源 mypy（含六项具体返回类型断言）及 Ruff、限定源码 AST／测试断言审计通过。测试不替代原生 Windows。冻结的 aa6d4ae7c 整批检查仍在原 worktree 运行，本批在独立后续 worktree 验证；旧整批结果不作为本批最终交付检查。

本批 Coding −111、Harness／Hosting／其他生产0，系统生产净 −111行；测试因真实 owner 的显式参数接线 +16行，文档另列。累计 Coding −6,376、Harness +9,344，系统生产仍 +2,968行；C07 余13,890行，距离过半退出仍差3,758行。收益为重复适配删除，不计为新完整事务迁移，整个 Goal 仍未完成。

## Linux 检查点完整写事务接入现有 owner

发布、修复和回滚的外层事务由现有 Package Product Linux history owner 持有：原 runtime quiescence、GC writer、历史复读、闭合判断、检查点根绑定及原 CheckpointCommands 的 publish／repair／rollback 调用完整迁入。实际 Journal、锚点、五流 snapshot、重试和尾部修复继续由原组件执行；未新增协调器、状态、Protocol、账本或阶段回调。Code 公开入口保留原精确 Product／attempt 准入、具体签名／结果类型及错误身份，原 dataclass／字段／slots／wire／pickle 路径不变。只读入口不因迁移获得写入或修复权限。

沿用原 HistoryProofBindings，纯 Profile 装配提前到兼容入口：仅创建原内部函数、lambda 和字符串／正则常量并构造原无自定义方法的 dataclass，不读 Product 或历史。其实际组件、配额读取、锁内事实复核和 IO 仍在原位置；closure-error factory 保留错误类型的延迟读取。不宣称与私有模块 Profile 常量在调用途中被重绑定的行为完全相同。当前执行代理在已授权职责内接受该有限装配时机变化和三个完整事务的 owner 归属。现有 BackupObservation 补齐真实记录已有的 owner_revision 类型事实，未增加数据字段；五源 mypy 通过。

原检查点／snapshot／commit／backup 与 IO golden 的五条测试路径102 passed；原断言和 fixtures 未变，仅把 review 故障口移到实际共享 owner。494组原执行体对照一致，其中482组实际注入 OSError 或取消，每组两次调用，覆盖 Product／registry／锁／review／闭合／命令／确认及退出顺序，包含 cause／context 和错误优先级。该探针使用受控事实和命令口，真实文件结果由原 golden 单独覆盖；不替代 Windows 原生或全候选验证。限定 AST 证明三个迁移执行体及原公开准入／签名保持，原 H 已有程序不变；原架构门禁、断言和 Worker import 清单保持。

本批 Coding −25、Harness +89、Hosting／其他生产0，系统生产 +64行，测试 −1行、文档单列。新增成本来自完整通用入口的参数／返回约束和必要适配，而非平行机制；Code 的泛型结果适配占用行数，同步计入。累计 Coding −6,401、Harness +9,433、系统生产仍 +3,032行；C07 余13,865行，距过半退出还差3,733行。仅验收这三条写事务，不宣称全部112文件、整组链路或多数退出完成。

## 整批检查的依赖清单修正

固定 aa6d4ae7c 的首次整批本地检查已结束：Coding 4240 passed／24 skipped／76 deselected；HarnessTUI 1078 passed／87 deselected；Coding UI 614 passed／68 deselected；render contract 319 passed／8152 deselected。Harness Ruff／916源 mypy 通过，回归为6357 passed／110 skipped／2 failed，因而整批未通过，后续 Hosting 路线未执行。上述各路线覆盖有交叠，不相加，也不作为后续提交的最终交付结论。

两项失败均为早期架构库存未随已接受的职责迁移同步：三个 Worker history 文件使用原 Resources 的 lease／record／quiescence 不可变事实，四个 Windows Package Product history／references／recovery／retirement owner 已成为 Worker 消费者。已核对真实导入、类型定义及读事实用途。当前执行代理在已授权迁移职责内接受这些实际边界；PLC9b 按精确文件、模块和符号限定，原共同原语许可不扩大；PLC9c0 仅补齐四个具体 owner，继续使用原精确集合相等断言。没有通配路径、断言跳过、门禁／触发器／平台变更，也没有新生产依赖。

两项原失败测试在后续提交上定向重跑2 passed；完整受影响 Harness 与此前未执行的 Hosting 路线仍待通过。该修正仅改变测试库存与验证记录，不计为迁移或生产代码删减收益；C07仍余13,865行，系统生产仍净增3,032行。

## Session Worker 完整入口校验并入编译 owner

原 prepare_coding_product_worker_session_inputs 的整段类型／时钟／直接与 deferred 输入形状校验已进入现有 Session _prepare_worker_session_inputs，紧接其后执行原 provider 闭合、当前选择复读和图编译。Code 保留实际允许的 receipt-owner／capability-authority 名义类、错误文案、查询 owner 政策与公开入口；名义类在每次公开调用时传入，不增加持久状态、Protocol、阶段回调或新的校验器。原 Code 数据声明、公开参数／返回类型、图关系／选中证据验证及所有原 H 执行体保持。通用类型名由所属 H 模块解析，不承诺继续支持 monkeypatch Code 对这些通用类型的导入别名；实际类型对象与数据身份不变。

61项既有 composition golden、Supervisor／graph handoff 和 Resume 消费者通过，五源 mypy 和 Ruff 通过；未改用例、断言或 fixtures。与原完整公开操作2112组对照一致，包含2074个错误、38次成功请求及470组实际故障／取消，比较真实 resolver／admission／compiler／请求事实、事件顺序、cause／context 及两个 async graph generation。受控 native／Product 端口不作为原生平台证据。源码审计证明原整段 guard 仅替换 Code 名义类／错误文案为 Policy 参数，原共享编译体及其他 Code／H 声明不变；当前执行代理在已授权职责内接受该归属与限定类型别名变化。

本批 Coding −29、Harness +31，系统生产 +2行，Hosting／其他生产／测试0，文档单列。累计 Coding −6,430、Harness +9,464、系统生产仍 +3,034行，C07余13,836行，距过半退出还差3,704行。收益是完整通用入口校验与既有执行 owner 合并，不重复计算此前已共享的编译流程。固定7f7dce52b的Hosting已517 passed／56 skipped，Harness整批仍在独立工作树运行；它们不验证本批后续源码，最终正确 base 的完整候选检查和全部112文件／过半验收仍待完成。

## 注册修复记录完整解码与 opt-in Journal 复用

原 Code _decode_repair_record 的 JSON 读取、虚拟 from_dict、attempt 关联、规范字节比较和错误完整归现有 RegisteredPayloadRepairIntentMethods.from_repair_record。Code 私有名称直接绑定该类方法，原 RepairJournal 消费者接线不变；原 JSON／canonical 原语已存在于该 H owner，不新增框架、状态、Protocol 或修复协调器。Code 名义记录的字段、slots、所有原公开方法和具体签名保持；57个原值／API／codec 观察及15组真实虚拟钩子故障／取消对照一致。四条原函数和 Journal protocol4／5 pickle 路由继续加载并解码真实 Code 值，正常记录 pickle 保持；探针首次因 AST 位置字段缺失未执行，修正探针后通过，未改 Product 或测试。

私有解码器的 module／qualname／运行时注解、错误参数绑定前缀及新 callback pickle 发出格式随 bound classmethod 改变；receiver 为固定 Code 名义类，不承诺替换该模块类变量后仍重选 receiver。原类的 from_dict／to_dict／attempt_id 覆盖保持虚拟调用。当前执行代理在已授权职责内接受这一项私有 alias 变化；全局 callable 精确例外由25项增为26项，本批新增项仅为本解码器，不扩大公开记录／SDK 兼容例外。无实际消费者的两个旧 import 同步退出。

CodingWorkerOptInJournal.change 的单次 super 转调也退出，直接继承原 OptInJournal 完整写入／重放操作。具体静态结果仍为 Code decision，原构造签名、调用参数形状、两份旧 bound-method pickle 字节及六组普通／MRO／失败／取消分派一致；原 H 程序、Code Profile 和数据声明不变。该 internal leaf 的反射 module／qualname／泛型运行时注解／class.__dict__ 归属变化在本次接受范围内；三个 registered review 属性与修复 intent 公开方法仍受原 API golden 精确约束，不能类推删除。

既有 registered recovery／历史公开值1082 passed；opt-in／V2／append-tail／private binding87 passed，原断言与 fixtures 未改。四源 mypy及 journal／具体返回类型断言二源 mypy、Ruff、依赖图通过。两组测试覆盖有交叠，不相加；模型与纯值证据不替代原生 Windows。

本批 Coding −30、Harness +10，系统生产净 −20行；Hosting／其他生产／测试0，文档单列。累计 Coding −6,460、Harness +9,474、系统生产仍 +3,014行；C07余13,806行，距过半退出仍差3,674行。完整 decoder 迁移与原有写机制的重复转调删除分别计数，不将旧 H 操作再次算作迁移收益；全组与最终完整候选验证未完成。

## Session 图组合直接绑定已有 owner

普通 Session 的 compose／validate 两个入口直接绑定原不可变配置的 WorkerSessionComposition 方法。实际参数签名、解析后的类型注解和操作文档均与原入口相同；既有61项 composition／handoff／Resume 测试及五源 mypy 通过，四条旧全局函数 pickle 路由仍可加载。原 Code 数据／政策／其他声明、H 实现及测试均不变。当前执行代理在已授权职责内接受这两个内部 facade 的 module／qualname、callable 类型、错误参数绑定前缀及新 pickle 发出格式变化；固定 receiver 不承诺调用途中替换私有配置对象后重新绑定。

本批为已共享机制的重复转发删除，不计为新事务迁移。Coding −29、Harness／Hosting／其他生产／测试0，系统生产 −29行；文档单列。累计 Coding −6,489、Harness +9,474、系统生产仍 +2,985行；C07余13,777行，距过半退出仍差3,645行。整组多数退出和最新完整候选验证仍未完成。

## Windows Journal 完整接口直接复用与剩余边界复核

Windows opt-in 的 current／history_read_only／change、receipt 的 records／issue 及 C5 的 retained_attempts_read_only 六个纯 super 转发退出，调用方沿用原 Code nominal journal，直接继承现有泛型 H owner。原构造、Product／平台准入、字段、codec／错误／配额及所有 H 执行体不变，未新增 owner、状态或 callback。六项具体静态返回类型断言、四源 mypy、Ruff 与限定 AST 审计通过；十二份旧 bound-method protocol4／5 pickle 字节及加载路由保持，72组普通／中间 MRO／空历史／失败／取消分派对照一致。当前执行代理在已授权职责内接受这六项 internal leaf 的 own-method 归属、module／qualname、泛型运行时注解和 Python 参数绑定错误前缀变化，不扩大记录或稳定 SDK 的兼容例外。

原生批准 Journal 的三个入口不是同类纯 super 转发。尝试迁到基类后，差分探针观察到新增中间 MRO 拦截，已完整撤回该部分及 H 增量；保留原虚拟分派，不计迁移或删减收益。首次探针还曾把 public 调用的关键字／位置转调形状当作底层 Journal 端口观察，已改为观察实际读写端口并显式绑定中间方法参数；最终证明仅覆盖上述六项纯转发，原 native approval 与 H 文件均逐字不变。

最终源码的既有 Windows IO golden、read-scope、C5、checkpoint、opt-in／receipt base 六条路径267 passed／1 skipped，测试、断言、fixtures 及门禁未变。模型和本地 FD 证据不替代原生 Windows。此批 Coding −58、Harness／Hosting／其他生产／测试0，系统生产 −58行，文档另列；累计 Coding −6,547、Harness +9,474、系统生产仍 +2,927行，C07余13,719行，距过半退出还差3,587行。旧完整回归不验证最新候选，最终整体验证仍待完成。

补齐剩余24份文件的源码与真实静态消费者路由复核后，冻结112份文件均有 SHA 限定的部分职责记录；这不等于112份文件最终验收或主要链路闭合。新核对的 V2 base／archive／cutover／deletion 文件主要是必要名义记录和既有 H 执行体的类型／wire Profile；不能靠搬字段计为机制收益。仍明确标出需继续处理的通用部分：_worker_history_access 的两平台借用适配，以及 provider_host 的完整准备／回执构造接线。回执 owner 构造仍混有通用关联校验和真实产品准入，须按实际失败顺序与原 owner 接管，不把类型或文件名当作整段保留理由。

## Provider 完整准备程序与同一 prepared 值交接

原 prepare_coding_worker_provider_binding 整段程序及 prepared 的 commit／abort／current 操作归现有 Session _worker_provider 内的私有方法基类，Coding 名义 dataclass 直接绑定其准备入口。原输入关联、candidate 重读、grant／facet／Graph binding、发布确认、退休及同一 release_once 仍沿用原组件和实际交接顺序；未增加实例状态、阶段 Protocol、修复器或平行生命周期。两平台 pending 与直接 Session 调用方继续使用同一 Code prepared 类型，原 H native 准备程序及失败清理执行体未改。

Code 保留原六字段、默认／比较／repr 配置、frozen／slots、错误类、release 名义类和实际 Product／Capability 类型／candidate／指纹域 Profile。新增基类 __slots__ 为空，不引入 dict 或 weakref 存储；原构造签名、字段元数据、repr、冻结保证、两份原值 pickle 字节及加载路径保持。六份原 bound-method pickle 字节与两条旧全局函数 pickle 路由保持，入口参数位置／关键字／默认形状不变，具体静态返回仍为 Code prepared；未暴露 Profile 覆写参数。

当前执行代理按已授权职责接受这一内部入口的函数→bound classmethod、module／qualname、泛型运行时注解及参数绑定错误前缀变化，以及 Code prepared 新增无状态基类／方法继承归属。实际记录类名／模块／字段不变，不声称 MRO 或全体反射值不变。Profile 固定绑定原名义 owner、输入校验 callable 与 candidate reader，不承诺继续重绑定旧 Code 模块私有 helper 别名；真实 owner 状态仍在原时点重读，H 的实际故障端口保持。该入口未进入 Coding 顶层稳定 SDK；不据此放宽其它公开记录的兼容要求。

原 composition／handoff／Resume61 passed；真实 Product 事务和候选选择17 passed／7个 host-runtime skip。198组原完整程序与三生命周期操作对照一致，含180组实际故障／取消、两个 event-loop generation、并发双 abort／重试及幂等释放；28个实际两平台名义非法输入结果一致。输入／candidate／binding 端口对照为受控观察，不代替真实权限、H6 或原生 Windows；Product 事务由原测试另证。探针先纠正 Field 对象身份比较和重建模块的名义错误绑定，再通过，未改 Product 来迁就探针。六源 mypy、具体返回类型二源断言、Ruff、依赖图及限定 AST 证明通过。

C51 精确消费者检查发现上批 Windows receipt journal 和本批 provider_host 已退出直接 activation 依赖，两项旧库存同步删除；原扫描与集合相等断言及其它 AST 保持，无门禁／平台／触发器扩展。首轮四项边界通过、一项库存失败的结果保留，原失败库存项修正后重跑1 passed。

本批 Coding −83、Harness +117、Hosting／其他生产0，系统生产 +34行；测试 −2行，文档单列。H 成本含完整方法入口、静态类型／无状态布局约束，Code 原协调体及三个操作方法同步退出 Coding，H 方法继续复用原 helpers；此批记职责迁移，不记系统重复删除。未搬动字段或将旧 grant／release 再计迁移收益。累计 Coding −6,630、Harness +9,591、系统生产仍 +2,961行；C07余13,636行，距过半退出还差3,504行。全组与最新完整候选验证仍未完成。

## 两平台回执 owner 构造与 Windows 历史查询完整接管

两平台原构造中的完整关联校验、Session／selected current 复核和原组件装配归现有 ProductReceiptAuthority；Windows 的 GC 锁内 current 复核、Journal 创建、根描述符借用、只读 records 和首项匹配也归同一现有 owner。Code 保留 product_id、Windows candidate trust 类别、具体组件与错误／类型 Profile，以及精确公开构造和查询入口。原 POSIX 同对象 _CodingReceiptHistory 初始化、Windows opt-in／native／receipt 组件继续使用，未实例化第二个 owner，未引入新 Protocol、字段 supplier、修复器或生命周期框架。撤销决策和旧公开当前值方法保持原位置／合同。

Code 原公开构造的参数、默认值、运行时解析后的 hints、module／qualname 和具体静态结果保持；构造兼容入口仅调用一次完整 H 操作。直接 __init__ 别名草稿被具体返回断言发现会退化为 Any，已撤回该方案，不以普通源码 mypy 通过代替调用方类型证明。原 Code 类的基类与数据声明不变，private _opt_in 类型标注和组件 Profile 不新增实例字段；四份原名义类、四份原 unbound constructor pickle 字节及加载路由保持。当前执行代理在已授权职责内接受固定 Profile 对既有组件／同对象 history initializer 的绑定，不承诺旧 Code 私有 os 导入别名重绑或插入私有 history 初始化 MRO hook；实际 Code 基类不变。H 仍在原位置读取真实 owner 状态，未把只读查询扩成修复／删除入口。

两个原构造执行体、整个 Windows 读作用域、所有其它原 H 程序／合同、Code 其它数据声明与公开查询 guard 均由限定 AST 证明保持。582组原／新程序对照一致，含462组真实故障／取消，使用实际 Product／runtime／selected／opt-in 名义类和受控事实／authority／native 组件，检查实例部分写入顺序、错误链、GC／根释放和首项匹配；这些有意构造的惰性事实不代表真实 Product 或原生平台准入。真实 Product 构造另由原候选事务测试验证，POSIX V2 history 初始化原路线保持。

首轮扩展 Product 回归16 passed／7 skipped／2 failed，失败来自本批把 OptInJournal 三个类型参数误写成两个，已纠正注解和运行时 cast；原失败路线与回执合同后续304 passed。恢复构造签名时，源码／类型审计还发现误插入旧异常 tuple 的 RuntimeBinding，已删除，最终原异常 tuple AST 不变。最终兼容入口／原失败 Product 路线／回执合同再次304 passed；六源 mypy（含两平台构造／查询具体结果断言）、582组对照、Ruff、依赖图和四项中立／无环边界通过。不抹除先前失败，也不以本机模型代替 Windows／H6。

本批 Coding −71、Harness +148、Hosting／其他生产／测试0，系统生产 +77行，文档另列。增长包含两个完整 typed 操作入口、组件绑定和必要公开兼容构造；全部适配成本计入，未搬动记录字段、删注释或重复计算原 Journal／native 机制。累计 Coding −6,701、Harness +9,739、系统生产仍 +3,038行；C07余13,565行，距过半退出还差3,433行。此批为完整程序职责迁移，不计系统去重收益；整组多数退出及最终完整候选验证未完成。

## 两平台 pending 请求装配合并与旧 C5 拒绝策略退出

两个公开 pending-session 入口在原产品准入后，原本各自执行相同的 base current 复核、identity 读取、Worker binding／admission 构造、原 pending host 创建及 deferred Session 输入调用。现由现有 Session _worker_provider 的单个完整程序持有，直接使用原 _binding_for_worker／_admission_for_worker、实际 Code host 类和原公开 Session 入口。Code 的精确／isinstance 差异、Resume 关联、receipt／Base identity、query definition／owner policy 决策保持原 AST；原 native prepare 方法和两平台真实差异完全未改。新增一个仅声明 prepare 方法的借用 port，不增字段、运行对象、阶段表、supplier 或生命周期 owner。

共同程序仍在原时点复核实际 Base owner，再构造相同 DTO，直到原 Code host.prepare 被 Session 调用才允许 native 效果。Code host 名义类、所有字段／slots／方法和公开函数签名／注解保持；四份原惰性 pending 值 pickle 字节及加载路径保持。产品提供的 host 类／Session callable 在共享调用开始时绑定；当前执行代理在已授权职责内接受这一固定组件接线，不承诺中途重绑 Code 私有模块 aliases。policy-revision lambda 仍由原 binding builder 立即调用、不存入返回值，不影响持久化路径。

删除已无真实生产路线的 _require_uncoupled_windows_host_c5_absent。实际 native prepare 早已使用 _require_windows_host_c5_recovered；前者未进 __all__／路由注册，也未进入已核实的历史记录／callback 字段。原生测试只有“owner 缺失”和“owner 存在但 state 未完成”两次调用，与现行 guard 在这两种观测下结果／错误及读操作相同，已将三处 import／调用名称接到真实 guard，其余测试 AST、断言、case、host-runtime／平台 selector 均不变。不是仅凭静态无调用删除，也不声称两种策略在已结清历史等其它状态全域等价；未新增或扩大门禁。

300组完整原／新装配对照一致，含112组实际故障／取消、两个 event-loop generation，使用原 binding／admission builder 与真实 DTO 字典／指纹，并核对 deferred 的原 host 接收者及 graph generation。旧 native 测试两个状态另有12组正常／构造失败／读取失败／取消对照。current／Session compile／native 端口受控，不能作为 Product／Windows／H6 准入证明。树外探针首次因 tests 搜索路径未设置而未执行，修正后通过，未改 Product。

既有组合／handoff／Resume／C5 路线61 passed／1个 native skip；两条现有 Product 候选事务2 passed。四源 mypy、Ruff、依赖图和限定 AST 证明通过；所有旧 H 程序及 Code 名义数据／native prepare 原体保持，原 native 测试未在此机器执行。该批 Coding −54、Harness +68、Hosting／其它生产／测试净0，系统生产 +14行，文档单列。共同装配部分 Code −40／H +68，系统 +28；旧 guard 整体退出 −14（声明12行、相邻分隔2行），合计系统 +14。类型／调用接线成本已全部纳入，不将职责迁移冒充系统净删减。

累计 Coding −6,755、Harness +9,807、系统生产仍 +3,052行；C07余13,511行，距离过半退出还差3,379行。整组与最终完整候选检查未完成。

## 二十七项重复声明退出，直接继承已有机制

activation state、POSIX cleanup evidence、history retention、native approval、POSIX receipt、registered payload repair、registered recovery、Windows receipt 八份 Code 文件共删除27项重复方法／属性声明，直接继承原 Harness 方法。Harness 生产源码零变化；本批属于既有共享机制的重复删除，不重复计为新的事务迁移。保留原 Code 名义类、字段／slots、构造、Profile 和其余执行体；current_tree_witness 的 cast 转发也由具体返回类型检查证明可退出。

27项具体静态返回断言及六源 mypy 通过；原有消费者回归1,509 passed，反射覆盖修正后57 passed。162组普通／中间 MRO／失败／取消分派对照、21份旧 classmethod／bound pickle 字节与路由和24条旧 unbound function pickle 路由通过。受控 leaf 探针只证明分派及旧 callable 加载，不代替真实 Product 或原生 Windows。限定 AST 审计证明仅删除选定声明和失效 imports，原三份业务 golden 逐字不变。

当前执行代理按已授权内部职责接受方法归属、module／qualname、泛型运行时注解和参数绑定错误前缀跟随 Harness；不宣称所有 callable 反射值不变。新增固定元数据 fixture 只逐项记录这些内部方法的 owner／签名变化；原值、错误、wire、字段／slots 和 pickle 观测继续使用原固定 fixture。反射测试同时检查原有方法名和当前 Code 自有公共方法，避免继承后漏检，也仍可发现意外新增 API。原测试入口、业务断言和平台 selectors 不扩展。

C51 首轮10 passed／1 failed，失败仅为 Windows receipt 已退出直接 activation 依赖而库存未同步；仅删除该条精确库存，原扫描和集合相等断言保持，失败节点修正后1 passed。不扩展门禁，也不将初始失败记为通过。

本批 Coding／系统生产 −210行，Harness／Hosting／其它生产0；测试及文档单列。累计 Coding −6,965、Harness +9,807，系统生产仍 +2,842行；C07余13,301行，距离过半退出仍差3,169行。整组多数退出和最新完整候选验证尚未完成。

## Windows 载荷三个完整入口由原 owner 接管

规划 pending、物化 payload 和绑定 launch request 三个 Coding 公共入口直接绑定现有 WindowsProductWorkerPayload 的三个操作。原平台／名义类型／attempt grammar 校验移到同一 owner，规划和物化复用同一校验；绑定仍先检查原名义 lease，再进入原 request 关联。Code 只保留原 nominal records、错误、容量／名称／异常 Profile 和必要 IO helper。原锁、弱引用 request registry、回执读取、持久化债务、失败清理及三段完整 H 执行体 AST 不变，未新增生命周期组件、状态账本或阶段 callback。

固定 Profile 在模块导入时绑定原组件与值；原限额 lambda 仍实时读取 Code 容量值。当前执行代理按授权职责接受这三个内部 facade 的函数→bound method、module／qualname、运行时泛型 hints 和新 callable pickle 格式变化，以及不再承诺重绑旧 Code 私有 import aliases／_payload_program；实际 H／Hosting IO 故障端口未改。三个入口的参数名／关键字限制／默认值、操作文档、具体静态返回类型及六条旧全局函数 pickle 加载路由保持。Code 原 nominal dataclass／字段／slots／__all__ AST 不变。

源码审计通过；68组原／新入口对照覆盖 POSIX／Windows 平台门、精确类／子类、非法 attempt、lease、错误及先后顺序，实际执行体以原 AST 和现有消费者另证。探针首次对 bind 的模块 os 绑定不完整，已修正探针并通过，未为探针修改 Product。五源 mypy 含三个具体返回断言通过，既有 Windows stage IO／live verification／intent／reserved／recovery 路线245 passed；测试、golden、selectors 和门禁零改动。本机模型不替代原生 Windows。

本批 Coding −70、Harness +43、Hosting／其它生产／测试0，系统生产 −27行；文档单列。多数收益是既有完整操作入口接管和原重复外壳退出，不把原 H 物化／恢复 body 再计为新迁移。累计 Coding −7,035、Harness +9,850，系统生产仍 +2,815行；C07余13,231行，距离过半退出仍差3,099行。此交付是明确未完成的阶段成果，整组验收目标不降低。

发布兼容补查发现，六条旧全局 callable 加载路由通过，并不能证明新 bound 入口仍可序列化：原限额 lambda 会使当前三个入口 pickle 失败。已将这一纯 Profile 限额绑定改为模块函数，保留同一时点读取两项 Code 限额；三入口的六次 protocol4／5 当前 pickle 往返、同一执行方法／等值 Profile、恢复后的动态限额及原 registry／lock 身份复核通过。原执行体、记录和测试不变。该修复 Code／系统 +4行，累计 Coding −7,031、Harness +9,850、系统生产仍 +2,819行；C07余13,235行，距过半退出还差3,103行。此前候选的并发检查出现 Session 一秒／两秒 deadline 失败，其中原 compaction 失败节点单独复跑通过；这些初始失败保留，不能当作最终完整候选通过。最终修复按原检查路线串行验证，不扩大 timeout、selector 或门禁。

后续串行检查在Hosted Goal族出现16 failed／1,441 passed／13 skipped后提取失败，原因定位到执行代理额外全局设置的`PYTEST_ADDOPTS`：其`--skip-host-runtime`被保护包目录中的合同pytest继承，该目录不加载工作区注册选项的conftest。原Hosted Repository用例不带该全局覆盖时两项通过（54.12秒），恢复唯一这一环境覆盖后同一`False`用例复现失败（19.68秒）。这是验证运行器的环境污染，未修改Product、测试断言或超时；后续将安全选择器限定在各命令参数及Make的`PYTEST_RUNNER`，完整检查重新验证。初始并发deadline失败与本次环境错误分别保留，不归并为产品回归，也不将中断的检查记作通过。

## 交付回归中的精确边界库存收敛

移除全局 pytest 环境覆盖后，完整 Coding 回归4,240 passed／24 skipped／76 deselected，Harnesstui 1,078 passed／87 deselected，Coding UI 614 passed／68 deselected，TUI 回放319 passed／8,152 deselected；各组有交叠，不相加。当前候选的真实 Coding console `--help` 入口正常输出并以0退出。上述通过不等于整组 C07 验收或原生 Windows 验证。

Harness 首轮静态检查通过（mypy 916源文件），测试6,354 passed／113 skipped／2 failed；两项失败均是 C50／C54 精确消费者集合仍包含已经退出直接 Worker 依赖的 Windows receipt。修正首层集合后，C54 暴露被首个断言遮蔽的三条过期边：provider_host 的 capability_query／product_activation，以及 Windows receipt journal 的 product_activation。静态全清单差异核实只有这些旧边退出，没有新增依赖边。同步删除过期固定库存及不再能进入的 receipt 特例，保留原扫描、集合相等、私有 Profile 与其它边界断言；不是放宽生产边界或增加门禁。

首轮两项节点复核1 passed／1 failed（发现上述旧边），最终相同两项节点2 passed（21.79秒）。失败结果保留；这次修正不改任何生产源码、业务 golden、平台选择器、超时或工作流。已通过且输入未变的 Coding／界面路线保留证据，更新文档重新检查，Harness 完整受影响检查及尚未执行的 Hosting／包级检查继续验证，未将局部复跑当作最终完整检查通过。

修正后的完整 Harness 检查6,356 passed／113 skipped，Hosting 513 passed／60 skipped，Harness 包级5,939 passed／110 skipped／3 deselected，Hosting 包级397 passed／56 skipped／4 deselected，全部以0退出；文档检查通过。最终候选9777f24的生产源码、脚本及 Coding／界面测试与此前通过候选587e590逐文件无差异，保留这些输入未变的通过证据；各组重叠不相加。该记录支持当前部分迁移交付，不证明多数退出目标或未执行的原生平台路线完成。

任务 PR #898 首次 Linux 定向原生检查47 passed／2 failed／1 deselected：清理竞态仍访问已经退出的 Code `os` 别名，GC 互斥证据仍注入旧 preflight 工厂而非当前 staging 入口。测试改为替换同一实际标准库 `os.unlink`，并在当前 staging 适配入口注入原 history bindings；实际 Harness 存储和锁内读取程序不改。限定 AST 对照证明只变更这两个既有注入位置及对应 import，所有断言、场景、标记、等待时限和其它测试 AST 保持；未恢复无消费者 Code 别名或增加故障 hook。受影响文件保留原非 live／skip-host-runtime 选择器，本地35 passed／14 skipped／1 deselected；原生结果按既有 PR 路线复核，不将本地跳过视为原生通过。

## 历史源读取六个入口由原 Package Product 统一持有

以已交付 `1a0aaa6ca` 为本批基线，原 Windows history 模块通过不可变配置 `WindowsProductWorkerHistorySources` 持有捕获、静止结算审阅、语义读取及锁内两个捕获操作。Coding 六个原函数直接绑定该组件；原平台、精确 Product 类型和产品身份校验在原时点执行。四个 Coding 名义记录的完整 AST、字段、slots、容量 getter、wire 和导出保持；无字段迁移、新 Protocol、账本、恢复器或平行生命周期组件。

删除同一 Harness 私有模块中被替代的三个函数 `capture_windows_product_worker_history_sources`、`read_windows_product_worker_history_semantics`、`capture_windows_product_worker_history_semantics_under_guard`，将其原执行体直接纳入同一组件。原底层 source IO 函数及其它历史程序保持；读取、锁、恢复关联、Desired 校验和 guard 退出后构造的顺序不变。不把已经在 Harness 的执行体重复计为新迁移；本批收益是操作归属收敛和重复转接退出。

当前执行代理在已授权 Coding／Harness 内部职责内接受这六个非顶层 SDK 入口由函数变为 bound method，以及其 module／qualname、泛型运行时 hints、新 callable pickle 格式和固定组件接线的变化；不承诺重绑旧 Coding 私有 import aliases 后更换 owner。参数名称、位置／关键字限制、默认值和操作文档保持，六个具体静态返回类型通过检查。十二条旧 protocol4／5 全局 callable 路由可加载，十二次当前 bound callable 往返保持同一操作和等值配置，容量仍读取原实时 getter。四份原记录布局和原 IO golden 不变；此接受不扩大其它公开数据契约的例外。

原 IO 契约探针只把 GC 故障注入从旧 Coding 工厂 alias 移到实际既有 GC 组件的构造和 require_settled 方法，原场景、断言、标记和固定 golden 保持。既有消费者30 passed／1个原生 Windows skipped，原 IO 探针31 passed；三段操作体的限定 AST 等价及其它 Harness 程序、四个 Coding 类的原 AST 通过。六个具体返回断言的 scoped mypy 和 Ruff 通过。本机未执行原生 Windows；模型和源码证据不代替原生验证，没有新增或扩大 PR 门禁。

本批 Coding −95、Harness +67、Hosting／其它生产0，系统生产净 −28行；测试 +2行，文档单列。累计从原 Goal 基线 Coding −7,126、Harness +9,917、系统生产仍 +2,791行，C07余13,140行，距多数退出仍差3,008行。该候选尚未合并，整组目标保持未完成。

## Provisioning 准入与绑定由原 owner 完整持有

后续任务分支以历史源提交 `06eba4e85` 为起点，无冲突合入远端 main `f3e75c93b`，合并点为 `7079ad0ba`；前一 worktree 的固定候选回归因候选已被新主线及实际断链修复取代而主动中断，实际退出2、已执行1,416 passed／7 skipped／76 deselected，整套未完成，不计为完整通过；原输入、日志与中断原因保留。控制目录的三份用户改动未进入任务分支。

原 Coding Windows Provisioning 构造器的精确平台／类型、runtime 活动与 Session／incarnation 关联校验，现直接由既有 `WindowsProductWorkerProvisioningAccess.__init__` 执行，并继续原 `_bind_provisioning_attempt`，随后使用原 intent 校验、Journal CAS 和 stale cleanup。唯一通用化是原 `coding` runtime 身份使用已有 `_product_id` Profile。没有新增字段、Protocol、callback 或生命周期组件；Code 名义子类、原 Profile、恢复 owner 接线及公开 factory 保持。

当前执行代理按已授权 Coding／Harness 职责接受构造方法的继承归属、module／qualname 和 Python 参数绑定错误前缀变化；构造参数形状及解析后的全部类型注解相同，原两条 unbound callable pickle 加载及当前两次往返通过。10,206组受控原／新准入与交接对照覆盖平台、精确类／子类、runtime 身份与活动、下游失败／取消；原绑定／CAS／IO 程序 AST 保持。该探针不执行 Product 或原生 Windows，也不代替原生验证。

扩展静态检查发现前一载荷迁移留下两处真实断链：launch intent 发布和 provisioning stale recovery 仍 lazy-import 已删除的 `_payload_program`。已改为直接使用当前 `_PAYLOAD_PROGRAM`，与规划、物化和 request 绑定共用同一实际 owner；未恢复旧工厂或增加转发。新增两项回归在修复前固定源码上均复现 ImportError，修复后原 launch-intent 文件8项通过，既有 provisioning／intent 消费者首次8项通过。原两项故障日志保留；初次 scoped mypy 的缺失符号错误已修正，全部112份 C07 加两个 Harness owner 的 mypy（114源）通过。进一步将 owner 断言限定为同一对象身份后，两项回归再次通过。最新主线候选架构边界181 passed，依赖事实与文档检查通过；原路由、平台选择器和 PR 门禁未扩大，原生 Windows 当前未在本机执行，交付前的完整候选回归仍待执行。

本批 Coding −36、Harness +36、Hosting／其它生产0，系统生产净0；测试 +30行、文档 +23行单列。加上未交付历史源批，较最新上游 main 的任务差异为 Coding −131、Harness +103、系统生产 −28行。从原 Goal 切点归属 C07 的累计差异为 Coding −7,162、Harness +9,953、系统生产 +2,791行；C07余13,104行，多数退出仍差2,972行，目标没有降低。

计量口径继续采用 tracked `src/loushang/**/*.py` 物理行，含空行／注释；测试、文档和 GUI Rust／TS 不在这一生产 Python 数字内。最新候选实际为 Coding 100,763／Harness 379,200／Hosting 14,235／其它154,008，共648,206行。相对原 Goal 切点的实际整树变化分别为 −5,667／+10,022／+32／+1,808，共+6,195；其中上游 PR #900 等功能变化为 +1,495／+69／+32／+1,808，共+3,404，明确排除于 C07 迁移收益和成本之外，不隐去实际整树增长。

## Windows C5 清理证据完整绑定归既有恢复 owner

上批历史源／Provisioning 已通过任务 PR #901、集成 PR #902 合入 main `4100b4f65`，本地同步完成。本批以该提交为阶段基线，原 Goal 的 `06f8a3f6`／20,266行基线不变。

现有 Package Product Windows recovery 组件接管正常、Resume 父级登记、崩溃三种绑定，以及完整 current-tree 证据关联。新产品集成基类继承原 `WindowsWorkerCleanupEvidence`，直接使用原 crash history join 和 `capture_windows_product_worker_cleanup`；不另建恢复器、账本、锁、原生观察或清理权限。四个原 Code 方法的执行体退出；原 Harness 捕获、读历史、锁序、缺失／歧义处理和 settlement 证明执行体保持 AST 不变，不重复计为新迁移。

Coding 保留原名义 live review dataclass、三个字段／slots、authority ID／fingerprint、产品身份前缀，以及 changed-boot／registered-lease-expired 两项返回 False 的政策。固定 Profile 只接入原 receipt 类型、三个读取组件和原 orphan reader。仍先读取 registry orphan，再进入原 GC guard、current 复核、runtime／native／activation 只读读取、第二次 current 复核后释放；无法观察或多个匹配继续不构成唯一证据。没有把只读检查变成修复、删除或启动授权。

当前执行代理按已授权内部实施职责接受继承层级、方法定义归属、module／qualname、泛型运行时 hints 和参数绑定错误前缀随 Harness 改变；不承诺运行中重绑旧 Code 私有 import aliases。四个方法的参数名／种类／默认值、文档和具体静态返回类型保持。真实实例 basicsize／dict／weakref offsets、名义记录布局保持，八份修改前 protocol4／5 callable 路由和当前八次 callable pickle 往返通过；另以精确原类 AST 重建的旧实例验证两种协议的前向加载，不将重建字节称为修改前采样或任意存量对象兼容证明。

38组原／新实现受控对照覆盖三种绑定、精确 receipt owner／子类、平台门、失效 current、缺少 crash 历史、缺失／歧义关联、读取失败和取消。有效路径另断言确实成功及完整读锁事件序列，避免同样失败被误判兼容。这些使用真实 receipt／request／名义 review 和原 Harness capture 程序，Product current／读取端口受控，不替代原生 Windows。外置脚本首次因临时子目录未创建失败，修正探针目录准备后通过，未为此修改产品实现。

原有清理／崩溃恢复八份业务文件37 passed（5.28秒）；首次注入迁移前的旧 module alias 产生的1个失败，已将同一测试的三个原 lambda 改接实际固定 Profile，以 staticmethod 保持调用形状，其余测试 AST、断言、参数和 selectors 不变。导入／C50／C51／C54 首轮189 passed／3 failed（204.57秒）；三项均只因同一 Code 模块已退出直接 Worker 依赖而固定库存未同步。仅删除三份清单的对应精确项，原扫描和集合相等断言不变，三个节点复核3 passed（48.50秒）；限定源码对照通过。原失败保留，不将首轮记为全通过。

112份 C07 源码、一个修改的 Harness owner 和具体返回断言共114源限定 mypy通过；Ruff／format、生成依赖事实及文档检查通过。未运行本候选的全量 Coding／Harness 回归或原生 Windows LPAC／Job、真实 crash／reboot 路线，不沿用上批全量通过来宣称当前候选已满足最终交付检查。本批为本地候选，尚未合并，整组验收未完成。

本批 Coding −101、Harness +142、Hosting／其它生产0，系统生产 +41行；测试净−2行，文档单列。这是完整证据绑定职责迁移，接收侧增加了泛型、类型和固定 Profile 接线成本，没有重复算法删除收益，也不是系统净精简。累计归属 C07：Coding −7,263、Harness +10,095、系统生产 +2,832行；C07余13,003行，距离多数退出仍差2,871行。全量逐文件当前行／SHA重新核对442份 Coding 源码，当前100,662行；Harness379,342／Hosting14,235／其它154,008，共648,247生产 Python 行。

## POSIX 六个载荷入口直接复用原 custody

物化、pending 规划、请求绑定及完整／空／未标记三种修复入口，现直接接入原 `PosixProductWorkerPayloadCustody`。六个 Code 函数外壳和多余 imports 退出；原名义值类与字段、容量及错误 Profile 留 Code。仅用一个零 slots 的固定产品子类绑定原 receipt owner 类型和产品文案，不增加 Protocol、回调、实例字段、账本或生命周期 owner。已有 custody 的物化、锁内复核、实际 IO、恢复与清理执行体 AST 保持，不重复计为新迁移。

六处原入口准入移到相同操作之前：仍保留 receipt／lease／repair-plan 的 `isinstance` 语义、规划只接受精确 str 而物化接受 str 子类，以及相同错误身份／文案和检查顺序。物化仍在进入 context 时才校验和执行；退出少一层原 Code 转发 context，不承诺 traceback 帧一致。当前执行代理按已授权职责接受函数转 bound method、定义归属／泛型运行时 hints／参数绑定错误前缀和新 callable pickle 格式变化，不承诺重绑旧 Code 私有 aliases。

42组精确原类／函数重建对照通过，覆盖相关名义类／子类、非法输入、进入时机、失败和取消，并另断言有效路线成功。12份修改前全局 callable pickle 加载路径、12次当前入口往返（同方法、等值 Profile）及20份既有 bound 操作加载与重新序列化通过；原 custody 的 fields／slots／实例 offsets 和全部 Code 名义记录 AST 保持。初次外置断言把两个等值 Profile 上的 bound method 当作同一 callable，已按实际同方法／等值 Profile 合同纠正，原失败日志保留。

原载荷恢复／修复固定 golden 两文件153 passed（8.99秒），保留原 IO、字节、异常及失败交接断言；116源限定 mypy及六入口具体返回断言通过。Code payload 唯一退出的直接 Worker 边为 `product_activation`，只删除 C54 对应精确库存项，其余扫描与相等断言逐字不变，原节点1 passed（45.85秒）。原 wheel 完整消费者35 passed／14 skipped／1 deselected（303.69秒），保留原 host-runtime selectors；依赖事实与文档检查通过。本批为本地候选，尚未合并；未执行原生 containment、真实进程崩溃或 reboot，不用受控探针替代这些证据。

本批 Coding −87、Harness +47、Hosting／其它生产0，系统生产净−40行；测试−1行、文档单列。收益是同一已有 owner 接管六个完整入口、原重复外壳退出，没有把原物化／修复算法重计为新下沉。连同前一本地清理证据提交，本阶段 Coding −188／Harness +189／系统生产 +1行。自原 Goal 切点归属 C07 累计 Coding −7,350、Harness +10,142、系统生产 +2,792行；C07余12,916行，距多数退出仍差2,784行，整组仍未完成。

## Windows 恢复读取族统一由原 Journal family 接管

原 `WindowsProductWorkerHistoryJournals` 接管库存、引用、GC 观察及离线快照四条公开读取链，连同 guarded 入口和 Job 观察共八个 Code 函数退出。真实调用方直接绑定该组件的操作；原读取／关联／快照内核、锁序和原 Code 退休验证绑定 AST 保持，不重复计为新的大块事务迁移。Code 保名义事实类型、错误命名空间及固定产品组件选择；现有四个 TypeVar 与只读 reference Protocol 仅重排使用，没有新增 Protocol、恢复器、账本或生命周期状态。

Codex 实施者按已授权职责接受这条只读组件边界及固定接线。内部 Journal 配置从5字段扩展到17字段，新增12项为产品标识、名义工厂和原读取组件等配置，不是迁出的 Code DTO 字段，也不计为迁移收益。公开 Code 入口参数形状、操作文档及具体静态返回类型保持；函数变 bound method、定义归属／泛型运行时 hints／参数绑定错误前缀及固定组件导入时绑定属于已记录的内部变化。不承诺任意旧5字段内部配置实例的构造／pickle 兼容，必要 Code 名义记录的字段／slots／历史 wire 不变。

八个原／新执行体在固定组件替换和统一 Product guard 展开后 AST 一致；全部旧 Harness 内核及 Code 记录／退休绑定 AST 保持。16份修改前全局 callable 路径和16次当前往返通过；重建原全局回调的六份历史源 bound callable 加载及重新序列化通过，后者不是修改前采样。40组原／新入口对照覆盖类型／平台／产品短路、只读锁边界、失败及同步注入的取消、active runtime、未知／不存在 Job 和未提供／显式空 native 事实；有效路径另断言成功。这些受控读取端口证据不代替真实 Product、原生 IO、Task.cancel 或 crash／reboot。

原库存／值／查询消费者首轮121 passed／9 failed，失败均为旧 module alias 注入点已退出；仅将两个平台口及四个读取工厂接到实际 owner，保原 lambda、固定预期和断言，复核130 passed（9.37秒）。历史源／准备／检查点／引用／持久 bases 八文件67 passed／1 skipped（5.32秒）。导入／C50／C51／C54首轮190 passed／2 failed；一条是本批退出的 Hosting 观察依赖，另一条为上批 `b66447096` 退出的 POSIX activation 依赖。只删对应精确库存项，原扫描和集合相等断言不变，两节点复核2 passed（22.40秒）。五份测试的限定源码变换已逐项核对；原 native pre-B 脚本仅更换一个观察注入路径，本机未执行该原生路线。

117源限定 mypy含八入口具体返回断言通过；三种冷导入顺序、Ruff／format及依赖事实通过。首轮类型检查暴露离线读取的宽协议返回，已将原 Code cast 随固定 snapshot 工厂绑定移入 Harness；外置 AST 探针仅归一化函数移入类导致的多行文档缩进，操作文档另逐项比对。原失败日志保留。最新 fetch 后 origin/main 仍为 `4100b4f65`，GUI lane 更新未混入本任务；本批为本地候选，完整交付检查和原生平台验证仍待完成，整组未验收。

本批 Coding −117、Harness +173、Hosting／其它生产0，系统生产 +56行；测试+4行、文档单列。增长包含全部固定配置、泛型及入口接线成本；收益是已有组件的读取族与入口归位，不宣称重复算法删除或系统净精简。自原 Goal 切点累计 Coding −7,467、Harness +10,315、系统生产 +2,848行；C07余12,799行，距多数退出仍差2,667行，目标不降低。逐文件当前行／SHA再次核对442份 Coding 源码，当前100,458行；Harness379,562／Hosting14,235／其它154,008，生产 Python 共648,263行。

## POSIX 批准 Journal 作用域与已知状态识别

独立后续候选基于 `9af1400a5`，不修改正在整体验证的上批 worktree。Codex 实施者在原授权内接受此局部边界：既有 Package Product native-release 模块中的 `_ProductRootedNativeApprovalRecords` 复用原 `RootedNativeApprovalRecords`，持有 current/change 的完整 GC、绑定根目录、currentness 与释放作用域。Coding 保留候选来源信任准入、原构造赋值、名义 approval/review/decision、codec 和错误政策。没有第二份 Journal、重放器或资源状态；Windows Journal 借用调用方 pinned root 的不同寿命保持。

既有 `_linux_worker_history` 持有完整已知状态文件名识别及正则；Coding 保留原 matcher 入口、实际 repair 正则端口及 live history-proof 绑定。公开三项导出不变。识别旧名称不等于证明语义有效、物理不存在或获得删除权限。已审查23处显式引用和两处模块别名传递；动态 hasattr／故障注入仅针对原 native group 观察端口。删除无消费者私有别名还结合1,206组原／新语法对照、历史 pickle 与实际历史读取证据，不只依赖搜索无匹配；不承诺任意外部动态私有属性访问。

真实后续 worktree 的既有批准／完整历史证明／状态准备组合229 passed（82.10秒），固定观察和期望未变；四源 mypy、Ruff、format 与 diff 检查通过。原批准 Journal 的10条旧 callable／惰性实例 pickle 路径及10次新往返、三项参数形状／原实例字段和属性访问通过；原 matcher／正则12条旧路径及12次新往返通过。后者验证真实 Harness 实现，不是只运行旧源码。惰性实例不证明活跃 Product 权限／lease 可序列化；泛型运行时注解与方法定义归属会变化。既有 journal IO、GC currentness、失败优先级与释放另由原固定探针覆盖，不将受控 Windows 端口当原生验证。

本批 Coding −85、Harness +101、Hosting／其它生产0、系统生产 +16行；测试0、文档另计。Code DTO 字段不搬运，旧 Rooted IO 和 native-release 内核不重计收益。C07当前12,714行，自原 Goal 累计 Coding −7,552、Harness +10,416、系统 +2,864，多数退出仍差2,582行。全部442份 Coding 当前行／SHA重核为100,373行；Harness379,663／Hosting14,235／其它154,008，生产 Python 共648,279行。前两批现已由 PR #903/#904、#905/#906 交付至 main `19ab72fd5`，各自任务／集成及 main push CI 成功；接受仍限声明的局部范围，不代表整组完成。

## Windows C5 待启动恢复资格归位候选

本候选基于已交付 main `19ab72fd5`，不修改仍在回归的独立退休入口工作树。现有 `WindowsActivationStateJournal.require_recovered` 持有完整的 owner presence／当前 state／保留尝试结算检查。复用现有 `_RetainedAttemptFields` 类型边界，没有新增 Protocol、日志、持久状态或恢复管理器。Coding 保留原 Pending Host、Product journal 构造及错误政策，原 helper 参数和文档不变。

两个 Journal 仍在原读取点分别构造；缺失 owner 不触发第二次读取，空锁而无 state 保守拒绝，存在 state 时在首个未结算尝试处短路。原日志工厂和错误构造都在使用点惰性读取；不固定捕获旧错误类、不缓存 journal、不获得修复／写入／删除权限。31个既有 Harness 函数及两份 Coding 类体 AST 未改，新增检查不改变原记录字段、slots 或历史 codec。

原函数与实际候选 helper 的1,540组逐事件对照一致，其中736组实际触发注入错误；覆盖构造、presence、保留读取、迭代、phase／比较故障及读取后替换 callable journal factory／错误类。既有 C5／激活回归83 passed、1 skipped，跳过项是原生 Windows backend review，未用模拟替代。两源 mypy、Ruff 和 format 通过；完整 change-aware 验证仍待执行，不新增或扩大门禁。

完整 Coding 回归4,307 passed／24 skipped／77 deselected（6,153.28秒）。Harness初轮6,355 passed／116 skipped／1 failed（1,562.55秒）；唯一失败是C54精确依赖库存未同步 Windows Pending Host 新增的 `_windows_product_journals` 导入。只向原表补记该实际 owner，原集合相等断言、用例和路线不改，完整C54文件复核7 passed（19.12秒）。其它选中检查尚未完成；本分支与 Provider／Receipt 注解修复合为后续串行完整候选，不将局部复核当作整组或完整 Harness 重跑成功。

本候选 Coding −7、Harness +24、Hosting／其它生产0，系统 Python 生产 +17；测试 +1，文档单列。这是残留机制归位，不是系统净精简，也不重计已共享的读取、折叠或 CAS 内核。上段 +17行仅为 C5 切片成本。当前组合工作树同时包含退休入口批次，合计 Coding −42、Harness +82、系统 +40；C07 原文件12,668行，加邻组回执适配4行，有效剩余12,672行，归因累计 Coding −7,594、Harness +10,498、系统 +2,904，多数退出仍差2,540行。独立退休冻结验证未被修改；整组及全部文件最终处置仍未验收。

以下另列从原 Goal 切点到本工作树的**整个 Python 生产代码**变化，包含同期其它 main 交付；不等于 C07 收益，也不含 GUI 前端／Rust 等其它语言：

| 范围 | 原 Goal 切点 | 当前工作树 | 全局变化 |
| --- | ---: | ---: | ---: |
| Coding | 106,430 | 100,331 | −6,099 |
| Harness | 369,178 | 379,745 | +10,567 |
| Hosting | 14,203 | 14,235 | +32 |
| 其它 Python 生产 | 152,200 | 154,008 | +1,808 |
| Python 生产合计 | 642,011 | 648,319 | +6,308 |

C07 归因与上述全局变化之间的同期主线差额为 Coding +1,495、Harness +69、Hosting +32、其它 Python 生产 +1,808，共 +3,404；该差额不计为 C07 迁移成本或删减收益。

## 三个 Windows 退休公开入口归既有 operation owner

后续独立候选基于 `fe61edcee`。Codex 实施者按已授权职责接受此局部实现边界：完整、partial、unlaunched 三个原退休 owner 接管原公开入口的前置 platform／Product／名义 review 校验；unlaunched 的 native revision2门槛保持，全部校验仍先于任何 offline／GC／根目录操作。Coding 仅配置实际 product_id、原错误信息、名义记录及原组件，公开名称直接绑定原 owner；没有新增退休器、账本、owner 或 Protocol。crash 公开入口继续经原 recovery program 复核，不把它直接替换成 raw retirement owner。

三个私有 Harness 配置各追加两个可选准入字段，原调用者未配置时保持原行为，旧构造参数仍有效；不承诺任意旧私有配置实例的 pickle／slots 兼容。五个 Coding 名义类体、字段／slots／wire schema 原样保持。公开参数名／kind／default及文档保持；定义归属、运行时泛型注解和 Python 参数绑定错误前缀随 bound method 归位变化。

原四个公开 callable 在协议4／5往返通过，而直接绑定原 owner 首轮8份新 pickle 全失败，具体阻碍为既有 Receipt IO 的 late rename lambda。候选仅将该端口及三个 review 容量 getter改为具名函数，继续逐次读取原模块端口／限额；不增加序列化注册器。真实 worktree 的8条旧路径恢复、8次新往返、四项公开参数形状／文档和四个动态端口通过。首轮对 owner 的 `__eq__` 断言失败，差异来自反序列化后的嵌套组件方法绑定；原记录保留，随后逐类型、状态、函数身份及共享引用关系核对整份配置图通过，未删除配置验证。

184组原／新入口对照覆盖非 Windows、错误 Product／子类／缺失或抛错 policy、错误 review／子类及原 native revision 比较语义；有效路径到同一第一副作用边界即截断。27个原 Harness 方法体在排除新增准入前缀后 AST一致，真实三文件既有测试20 passed（17.86秒）。五源 shadow mypy通过，实际五源与其字节及项目配置相同。Ruff／format／diff通过。该证据不代替真实 Windows ACL、删除、reboot、LPAC 或 Task.cancel 路线；整批检查仍待执行。

本批 C07 −39、相关 C09 Coding +4，全部 Coding 净 −35；Harness +58、Hosting／其它生产0，系统生产 +23行，测试0、文档另计。112份 C07实物余12,675行，但相关额外4行适配同时计入本 Goal，等效剩余12,679行；累计 Coding净 −7,587、Harness +10,474、系统 +2,887，多数退出仍差2,547行，不把适配挪出清单作为收益。442份 Coding当前行／SHA全部重核为100,338行；Harness379,721／Hosting14,235／其它154,008，生产 Python共648,302行。当前候选未交付，原 Goal不关闭。

## Prepared Worker Profile 直接复用候选

在独立分支复用现有 `_PreparedWorkerProviderMethods`，将原私有原生交接函数作为其 `_prepare_native` 操作，直接使用既有 release/error/prefix/fingerprint Profile 与具体 `Self` 构造。两个真实 Pending Host 调用方直接接入，删除两份重复实参、无消费者的 `_PreparedFactory` Protocol 及三个 TypeVar；没有新增 Owner、Protocol、实例状态或转发层。原生执行内核本来已在 Harness，本次不重计其整段为新迁移收益。

四项 Profile 在首次 await 前快照，之后保留原 try／handoff／失败释放流程；规范化源对照仅替换配置绑定与具体类构造后，内核执行体 AST 一致。两平台 Code Host 的字段、slots、构造、prepare 参数／返回和文档保持。5个既有交接／取消／原生交接前失败用例通过；仅将探针入口移至实际既有 owner，所有断言、参数化及场景不改，不新增门禁。三源 mypy、Ruff、format、diff 检查通过。

原实现的12条惰性公开值／绑定入口 protocol4/5 pickle 路径及12次新往返、字节、全部 dataclass 字段与元数据、slots、MRO、公开签名和导出一致。它们不是活动 Product／lease 或原生平台序列化证明。原私有自由函数只有两平台调用和该探针使用；真实 Session 保存的是 Code Host.prepare，必要公开 pickle 不引用旧私有函数。不承诺任意外部私有 helper-global pickle 或私有导入别名的重绑定时点。

本切片 Coding −16、Harness −20、Hosting／其它生产0，系统 Python 生产净减少36行；测试 +4，文档单列。相对已交付 main `19ab72fd5`，连同退休／C5候选合计 Coding −58、Harness +62、系统 +4。当前 C07 原文件12,652行，邻组适配4行全计入，有效剩余12,656行，归因退出7,610行；多数目标还差2,524行。局部验证已通过，完整 change-aware 检查及交付尚待完成，不据这次去重关闭整组。

整个 Python 生产代码从原 Goal 切点到本工作树为 Coding 106,430→100,315（−6,115）、Harness 369,178→379,725（+10,547）、Hosting +32、其它 Python 生产 +1,808，总量642,011→648,283（+6,272）。其中 C07 任务归因系统 +2,868，同期其它主线差额 +3,404；GUI 前端／Rust 等其它语言不在该 Python 表内。上节表保留上一个组合切点，不当成本切片当前总量。

## 全部 C07 公开接口反射复核与 Receipt 注解修复候选

从原 Goal 提交独立提取完整 `src`，逐一匹配原112份 C07 源码哈希，再分别在原始源码和冻结候选中导入同一112模块、观察349个原公开入口。所有模块的实际来源路径均已核对；没有构造 Product、执行原生操作或调用公开工厂。原始快照保留，未以候选重新生成旧期望。

参数名／kind／default、dataclass 字段与元数据、slots、match_args及导出未发现差异。迁移引入的44处 MRO、82处 callable 定义身份及泛型注解差异仍按各批兼容证据接受，本次反射不自动批准这些变化，也不替代 pickle、wire、锁序、异常优先级和原生平台验证。两个 frozenset 的 repr 顺序经仅解析字面字符串集合归一化后内容一致，不当作行为差异。

复核发现两个公开 Receipt 工厂的新缺陷：原实现可解析运行时注解，迁移后的 bound entry 调用 `get_type_hints()` 则因 `_AttachedTranscriptReadPort` 仅在 `TYPE_CHECKING` 内导入而抛出 NameError。独立候选将已有 Transcript read port 改为普通导入，无新增类型、状态或 IO。修复后349项再次反射，无新增解析错误；对比修复前，仅两项 hints 由错误变为可解析，其余公开观察保持。

两个平台公开工厂的纯反射回归及既有 Receipt checkpoint 用例合计3 passed（36.26秒），两源 mypy、Ruff／format／diff通过。没有新增 workflow、job、selector、平台或合并条件。父 Provider 候选的完整 Coding 回归出现4个超时失败；为正常退出已确认失败的调用并释放并发资源，发送一次 SIGINT，最终保留4 failed／2,442 passed／15 skipped／77 deselected（4,230.23秒）的中断结果，不作完整通过。4个失败节点单独复现为2个20秒等待评审超时、2项通过；未含 Provider 迁移的冻结 C5 版本同一用例也超时，任务栈仍在 verification 子进程等待，尚未进入 review。该对照不能证明具体资源成因，也不能据此认定 Provider 已通过。本修复不消除该失败。C5 原检查其后也以C54库存不同步失败终结，精确补记及7项复核见上段。三项未交付改动现合为同一串行完整候选，旧失败结果归档；保持原超时、选择器和门禁。本候选完整 change-aware 检查和交付均未完成。

补充原公开引用对照：335项类／callable（含别名）在 protocol4／5下共670条旧路径，原版自身对照及当前候选的加载、保存和往返均通过，未发现恢复后的配置字段缺失。引用可能指向相同实现，不当作670个独立机制或活动 Product 序列化证明。首轮对同一 GenericAlias 的2项对象身份断言在原版自身也失败，且原／新别名声明 AST相同；保留两份失败证据后，仅将该别名改为精确类型、origin和名义参数比较，真实类／函数身份断言不变，旧 pickle 字节不重新采样。

旧并发检查全部终结后，合并候选单独串行复核原4个超时用例、3项 Receipt 回归、完整C54的7项及原5项交接探针，19 passed（82.11秒），原10／20秒期限、断言和选择器均未改。该结果说明本次串行条件下未复现原超时，不将资源竞争推测写成已证根因；完整选中检查仍须执行。最新 fetch 后 main／origin/main／lane/harness／origin/lane/harness仍同为 `ca7091aa8`，原三份用户改动的二进制 diff哈希保持。

本修复 Coding／Hosting／其它生产0，Harness及系统 Python 生产 −4行；新增回归测试单列，文档另计。这是兼容缺陷修复，不计任何新的 C07 迁移退出。当前 Coding100,315／Harness379,721／Hosting14,235／其它154,008，生产 Python共648,279行；相对已交付 main `ca7091aa8` 的 C5／Provider／本修复候选合计 Coding−23、Harness0、系统−23。原 Goal 归因 Coding−7,610、Harness+10,474、系统+2,864；同期其它主线+3,404仍另计，整库 Python较原基线+6,268。C07有效剩余12,656，多数目标仍差2,524，不因349项反射通过宣称整组完成。

## C5、Provider 与 Receipt 修复合并候选的完整本地检查

上述候选冻结在 `e7fcea589d7a5b9e912b4b31ef2e073c8eb51b35`，相对最新已交付 main `ca7091aa8` 串行执行既定 change-aware 检查；运行器核对全部受版本控制输入的哈希，最终全部选中本地检查通过。此节仅追加执行结果，不修改该次验证的生产源码或测试输入。

Coding 4,309 passed／24 skipped／77 deselected；HarnessTUI 1,078 passed；Coding UI 614 passed；回放319 passed；Harness 6,356 passed／116 skipped；Hosting 515 passed／61 skipped；独立 unit Harness 5,939 passed／113 skipped；unit Hosting 399 passed／57 skipped。各范围有交叠，数量不累加；unit Coding 经收集证明为 Coding 的既有子集，去重执行。文档与依赖事实检查也通过。原并发运行的失败及对照证据保留，不因串行通过推断其根因。

原有选择器、超时、断言、平台和门禁不变；`harness_native`、`host_runtime`、`windows_shell` 保留为 Actions／平台路线，本次本地结果不代替原生 Windows 验证。公开引用670条旧 pickle 路径及112模块／349入口反射的范围与限制沿用上一节。生产总量、归因和多数目标缺口均不变：有效退出7,610行，仍差2,524行。

本地检查完成，远端交付待推送允许时段执行。C07 整组仍未完成，后续优先项为 C01 启动／插件装配；LSP 的领域职责留 Coding，通用进程和生命周期能力按实际复用另评估。

## Receipt owner 直接接入两平台准备及 operator query 候选

本批由原 Package Product Receipt owner 直接承担准备输入职责，真实两平台 Pending Host 与 POSIX operator query 接入，删除 Coding 的五个临时 source／activation 类及一个 operator source 类。已有 Receipt owner 本来持有选择事实、原生材料和启动规划，现在直接调用原 Payload、Journal、Cleanup、StartGate 与 Provisioning 操作；不新增 owner、Protocol、TypeVar、实例字段、缓存、资源管理器或另一执行框架。每次调用显式传入 receipt／pending，避免在共享 owner 上保存每次 attempt 状态。原生执行程序本来已在 Harness，不重复计为本次迁移收益；本批主要收益是临时适配对象退出和共享 owner 接线归一。

Coding 保留原查询政策、批准与 Profile：八种私有构造／操作 Profile 共十三处平台绑定。原公开工厂及其内部晚绑定构造继续使用，未通过重新创建 recovery bindings 提前捕获事实。POSIX ordinary 与 operator 复用同一材料投影；Windows 直接复用原 `current_selected_manifest`／`plan_current_native_attempt`。父恢复证据仍走 `for_resume_parent_enrollment`，request 已有时才构造请求清理证据；未混入崩溃恢复证据。operator bind 原来省略的 pending 参数仍省略。

边界复核接受该方向，整批完整回归尚待执行。原六类仅在 prepare 的临时输入中创建，不属于公开导出、记录 wire 或 Host 的持久字段；真实 Session 保存的仍是原 Code Host.prepare。源核也检查了历史公开类型和持有链，而非仅凭搜索零匹配删除。私有模块中导入别名的任意重绑定时点不作为公开承诺：现在操作 Profile 在装配模块导入时绑定，原公开工厂内的动态构造仍保持。三个冷启动导入顺序与实际 Code 工厂身份检查通过。

原有交接／资源持有／完整C54合计49 passed（36.43秒）；原断言、场景、参数化和 golden 不变，交接探针仅同步实际 owner 方法名和显式 receipt 参数，C54仅删除三个退出的导入项。八源 mypy 通过，另两项负向 mypy 明确拒绝跨平台 owner。Ruff、diff 与生成依赖事实检查通过，无门禁变化。原普通两平台准备、coordinator 与 operator query 四个完整函数在明确列出的端口／参数替换后 AST 一致；另以真实 Code owner 子类和受控工厂进行三条路线44组对照、41组故障注入，组件调用／构造顺序、值和异常身份一致。该对照不等于完整原生执行证明。

相对上一冻结候选的112模块／349公开入口反射，公开参数、默认、字段、slots、导出和原方法元数据不变；两类 Receipt owner 的 `get_type_hints` 新增十三项继承的私有 ClassVar，明确接受此反射差异，不声称完全一致。原基线335项公开引用的670条 protocol4／5加载与新往返全部通过，无恢复后配置字段缺失；不覆盖活动 Product、lease 或任意私有类的 pickle。

本批 Coding −219、Harness +241、Hosting／其它生产0，系统 Python生产 +22；测试 −1，文档单列。必要端口和十三处 Profile 绑定的成本全部计入，不能报告为系统净删减。Coding100,096／Harness379,962／Hosting14,235／其它154,008，系统648,301行。相对已交付 main `ca7091aa8`，全部未交付候选合计 Coding−242、Harness+241、系统−1；不同切片收益不混算。

C07 原文件12,433行，邻组适配4行全计，有效剩余12,437，归因退出7,829，多数目标仍差2,305。原 Goal 归因 Harness+10,715、系统+2,886；同期其它主线+3,404另计。原生 Windows LPAC／Job、真实崩溃及远端平台路线未由上述局部验证证明；完整选中检查、整组112文件处置和多数退出验收均未完成。

## 两平台 Product 历史访问适配归位原型

逐文件清单明确 `_worker_history_access` 的两个借用适配不是 Coding 产品政策。本原型将整对原 frozen/slots dataclass 归 `package_product._worker_history_access`，Coding 只保留两个原私有名称的别名；原 Receipt、Supervisor、checkpoint、snapshot 与 Windows C5 消费者使用同一对象，没有额外适配实例。现有 Worker History ports 和 Journal/Snapshot/Rooted IO owners 保持，不新增 Protocol、账本、锁、读写算法或权限。

两个完整类的 AST 仅更改类名，字段与全部方法体保持。POSIX guard 仍显式传 `require_write`；Windows 默认/False 仍省略参数，仅 True 显式传入。POSIX pin 和 Windows borrowed descriptor 继续使用各自原 Product 方法，不将 Windows 读取变成 root 修复或创建入口。Ruff、格式、diff、生成依赖事实与两源 mypy 已通过；扩大 scoped mypy 的11个源文件也通过，覆盖八个真实调用模块和三种既有访问 port 的显式类型关系。为避免与上一候选完整回归争用，不并发启动新的运行时验证。

原型 Coding −43、Harness +54、系统生产 +11，测试0，文档单列。它消除残留中性适配的职责错位，不是新的物理 IO／恢复机制，也不将原已共享 Journal 内核重计。本原型尚未运行时验收、未计入7,829行退出或2,305行目标缺口。

原私有类的模块/名称/repr和新保存的 pickle 路径会变化，Code 别名保留旧查找。从精确前序源码 `6d695024e` 独立捕获两类及假 Product 字段实例的 protocol4/5原字节，共8条旧路径；源码/字节哈希核对后，当前加载、字段元数据、slots、match_args及新保存往返全部通过，旧期望不重采样。它们仅是惰性类/字段对象，不证明活动 Product 的序列化。

另以两个切点的112份源码哈希核对原349个公开入口，除源路径/哈希及等值 frozenset 的显示顺序外，公开反射观察无差异；原 Goal 335项公开引用的670条旧 pickle 路径及新往返通过，无恢复后的字段缺失。惰性核对以低优先级独立运行，异步/原生生命周期及 pytest 继续串行；真实消费者和完整选中回归仍待执行，43行尚未计入已验证迁移量。若必要兼容成本抵消收益，应调整或撤回；不能因只剩43行就放松原 Goal 的整链和多数要求。上一份112文件表仍准确描述它所标明的冻结源码 `6d695024e`，不将本候选冒充已交付状态。

## 三条完整读取作用域归位原型

继续拆开真实产品准入和通用资源协调：POSIX checkpoint 完整读取及其原 bound context，由既有 `_linux_worker_history` 持有；Windows intent 的公开读取和枚举，由既有 `_worker_windows_attempt` 持有 GC read guard。真实 Code 入口直接接入，保留原 Product/OS/attempt 准入、名义记录、格式与限额配置；未改造现有 IO、Journal 或 Scope owner，没有新增 Protocol、TypeVar、manager、实例字段或写入/修复操作。

每条路线只借用原完整 Commands/Records 组件工厂。checkpoint 仍在原两个位置分别构造 Commands，第一次 bound 和第二次 read 使用当时的配置；传入惰性 getter 保留锁内 quota/构造器变化。Windows Records 仍在 GC read guard 内构造，读取仍显式传原 `allow_unpublished_stage=False`。旧 under-guard intent 入口保留，原恢复消费者继续使用；Code `_bound_checkpoint` 保留原全局查找名称，改为返回 Harness 的同一形状 context manager，其私有返回注解和 `__wrapped__` 实现元数据有变化，不能声称任意私有反射完全一致。

四个相关源文件 mypy、Ruff/格式/diff 通过。两份 Code 文件的全部类及公开参数/返回/装饰器 AST 保持；只改变四个作用域入口。对精确前序 `9e54f0338` 的原函数 AST 与当前真实入口/Harness 操作进行260组受控对照，其中252组故障，覆盖六种 primary exception、构造器/配额替换、进入/读取/退出和二次清理失败；事件、返回、异常身份/因果/notes一致。使用真实名义 Product 类型和假的 Commands/Records/guard，不读取实际磁盘，不替代真实消费者或原生/异步生命周期验证。

本批 Coding +5、Harness +46、Hosting/其它0，系统 Python生产 +51；测试0，文档另计。它清除 Code 的读取作用域协调，属于职责归位成本，不能报告为删减；少量适配增长也不改变多数目标。连同尚未完成消费者验收的访问适配候选，合计 Coding−38、Harness+100、系统+62；这些未验收变化不计入7,829行已复核退出或2,305行缺口。

前一冻结 `6d695024e` 完整检查的 Coding、HarnessTUI、Coding UI、回放及文档/依赖事实通过；Harness 为6,355 passed、116 skipped、1 failed，唯一失败是C52清单仍把 native binder消费者记为 Code preparation，实际 owner已归 Package Product。`30170b10a`仅替换原双消费者集合的一条路径，原断言逻辑/场景/门禁不变，C52原6项复核通过。生产源码未变，已通过范围保留证据，受影响 Harness 和未执行 Hosting/unit 范围串行补跑；旧失败日志保留，不记作整轮通过。当前读取原型的真实消费者及完整选中检查仍未完成。

## 当前验证与限制

原有 preparation/checkpoint/history join/Package reference 回归16项通过；加入原 cutover record 与 persisted bases 消费者后25项通过。最后覆盖整组六流、Desired/GC、cutover 与持久化的14个既有文件为58 passed、1 skipped；三组覆盖有交叠不相加。导入边界及原C50/C54为181 passed，六源 scoped mypy、Ruff及生成依赖事实通过。
原 staged-publication 故障用例只将读写注入点移到实际 WindowsPrivateReceiptIO，既有断言和测试入口未改变。两份现有架构清单同步当前模块归属，不新增检查、路线、平台或 PR 门禁。
已与精确基线对照3个实际名义记录、6份原始 protocol4/5 pickle 字节、字段/slots/构造与公开方法签名及8个错误；全部一致。三个公开事务与原函数逐事件对照754组，其中688组实际注入故障，比较两次调用、锁/IO/构造顺序、异常链和剩余字节，一致；模型证据不代替原生 Windows。
测试沿用本会话已批准的 C07 私有目录，仅设置命令环境；运行时测试首次在 sandbox 外通过管理 wrapper 执行。
本轮本地验证未执行 Windows 原生 LPAC/Job、真实崩溃路线；合成事实和跨进程记录探针不作为原生平台证据，远端平台结果另见交付 PR。

## 剩余工作

当前112文件的源码行数、SHA、共享接缝及具体保留/待处理边界已更新到 [逐文件处置](c07-worker-current-dispositions.md)，切点为 `6d695024e`；97份源码沿用同哈希的有界旧复核，15份变化项更新，完整原生/多数/交付验收仍未完成。继续复核证据 factory、回执/批准记录与 Provider/Session 消费者，优先复用已有能力并删除重复机制以降低系统成本。
全部112文件均须更新职责与处置，区分产品政策、必要名义入口、迁移、复用删除；重新审查旧轮次保留理由，Coding 类型或固定名称不单独构成保留整个实现的理由。
每批计入 Coding/Harness/Hosting/其他生产代码及系统总量，测试和文档单列；系统成本与实际重复删除、职责迁移分别报告。
本轮尚未达到多数退出目标；当前清单是部分迁移的阶段性交付记录，不代表整组 C07 验收完成，不修改原轮次已完成的历史证据。
