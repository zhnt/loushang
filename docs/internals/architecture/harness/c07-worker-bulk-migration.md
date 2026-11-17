# C07 Worker 大块迁移

- Authority: descriptive audit / execution evidence
- Design status: partial acceptance — history/recovery/crash read, four stage-retirement, crash-settlement, payload/intent and POSIX custody/start-gate gated-recovery and Windows Provisioning slices reviewed by implementation owner; whole-chain closure pending
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

## 当前验证与限制

原有 preparation/checkpoint/history join/Package reference 回归16项通过；加入原 cutover record 与 persisted bases 消费者后25项通过。最后覆盖整组六流、Desired/GC、cutover 与持久化的14个既有文件为58 passed、1 skipped；三组覆盖有交叠不相加。导入边界及原C50/C54为181 passed，六源 scoped mypy、Ruff及生成依赖事实通过。
原 staged-publication 故障用例只将读写注入点移到实际 WindowsPrivateReceiptIO，既有断言和测试入口未改变。两份现有架构清单同步当前模块归属，不新增检查、路线、平台或 PR 门禁。
已与精确基线对照3个实际名义记录、6份原始 protocol4/5 pickle 字节、字段/slots/构造与公开方法签名及8个错误；全部一致。三个公开事务与原函数逐事件对照754组，其中688组实际注入故障，比较两次调用、锁/IO/构造顺序、异常链和剩余字节，一致；模型证据不代替原生 Windows。
测试沿用本会话已批准的 C07 私有目录，仅设置命令环境；运行时测试首次在 sandbox 外通过管理 wrapper 执行。
Windows 原生 LPAC/Job、真实崩溃路线尚未执行；合成事实和跨进程记录探针不作为原生平台证据。

## 剩余工作

继续收敛恢复总编排；复核证据 factory、Provisioning、回执及全部剩余文件，优先删除重复机制以降低系统成本。
全部112文件均须更新职责与处置，区分产品政策、必要名义入口、迁移、复用删除；重新审查旧轮次保留理由，Coding 类型或固定名称不单独构成保留整个实现的理由。
每批计入 Coding/Harness/Hosting/其他生产代码及系统总量，测试和文档单列；系统成本与实际重复删除、职责迁移分别报告。
本轮尚未达到多数退出目标，未提交 PR 或交付，不修改原轮次已完成的历史证据。
