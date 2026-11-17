# C07 Worker 大块迁移

- Authority: descriptive audit / execution evidence
- Design status: partial acceptance — history, recovery/retirement, payload/start-gate, registered-value, complete Windows crash-recovery and Provider candidate/Host-input slices reviewed by implementation owner; C07 majority and whole inventory acceptance pending
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
