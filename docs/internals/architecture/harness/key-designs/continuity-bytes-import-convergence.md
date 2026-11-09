# H-COD-KD-003 R2：Continuity 不可变输入复用原 Transcript 导入

- Authority: proposed key design。
- Design status: draft；R1 三视角确认方向但未通过实施就绪审查，R2 记录旧行为取证与剩余关闭项。
- Implementation status: not-started。
- Owner: 原 Transcript import 与 Session lifecycle；Coding 只选择来源、工作目录及 Product 限额。
- 需求：[Coding 全层职责收敛](../coding-convergence-progress.md)，用户允许越出 C08 清理整个 Coding；原 C08 数量与新增范围分账。
- 源码基线：`8ad6b6098f1c24c8cfb6f4d9d290e99bc74d618d` 加 A28 已冻结工作树；本切片参与的现有文件未在 A28 修改。
- 方法：本地干净 archmethod master `0f9bd3ff51afabeaaf76cc38dff1ceb279b7d37e`。

## 问题与事实

Coding Continuity 已持有 `ContinuityActivationPayload` 的内建不可变 bytes、媒体类型、SHA256 与 64 MiB 硬限制。`CodingContinuityActivationBridge.prepare` 仍写入临时 JSONL/ZIP，再通过 `prepare_restore_session_operation(path)` 重新读取，最后按身份删除临时文件。临时根/文件两个 FD、随机名称、完整写入、取消后回收及路径安全检查都因此留在 Coding。

原 Transcript 已拥有 `decode_agent_transcript_bytes`、`decode_agent_transcript_bundle`、Blob budget/read-only reader、`AgentTranscriptSessionFactory._import_frozen` 及 owned writer/Blob rollback。原 Session 已拥有 prepare-import candidate factory、未交付 transcript 清理、`PreparedSessionLifecycleOperation` 的 consume/abort 和 before-transition hook。它们不是待新建的存储或状态机。

原 JSONL 导入还会读取 source.parent 相邻的 SessionBlobStore；不能因为上游传 bytes 就忽略附件或另造 Blob reader。ZIP 已内含 blobs，仍必须沿原 ZIP decoder 的成员/压缩输入/解压总量/单 Blob/摘要规则。原两种限额和错误顺序不能用 Continuity 的 64 MiB 上限替代。

## 候选机制与职责

1. Transcript 内声明一个不可变 portable import 输入值，携带内建 bytes、显式 JSONL/bundle 格式、仅诊断用途的来源 label，以及 JSONL 可选的**调用方已选择**的 `jsonl_source_session_dir`。该字段是原 source.parent，即原桥接的 temporary_root，交给原 `resolve_session_blob_data_root` 得到其解析后的 parent，再绑定 header conversation 的 Blob authority；不是已解析的 data root，不能多取一次 parent。它不是文件路径、可执行 factory、Writer 或新 store。不得根据 label/digest 猜物理附件位置，不得把含 bytes 的 DTO repr 放进 transition metadata。
2. 现有 factory `import_transcript` 接受原 Path 或该输入值。Path 分支的稳定文件读取、authority fingerprint、后续解码/校验/持久化均保持；portable 分支直接进入同一解码及 `_import_frozen`。只扩输入，不复制导入主体。原 bundle codec、BlobStore、binding/header validator、owned preparation、rollback 与 unpublished 标记继续唯一。
3. 同一 ProductTranscriptSession 薄转发与原 prepare-import factory 接受该值。Session 在原 `_prepare_candidate` 中执行同一 before hook，复用同一 pending transcript owner、restored validator、build/dispose、交付标记和 prepared rollback。不能从 Coding 跨层直接调用 `_import_frozen`，也不能给任意 callback 一个绕过 before hook 的新入口。
4. Harness 原 lifecycle adapter 提供 portable prepare 的窄入口；它只绑定原 session_dir、Product cwd 解析、transition metadata 和 missing-cwd 错误投影。输入不是发现目录中的 Session，不执行目录发现或构造假文件来绕过 authority；也不赋予新建 store、替换当前 Session 或改变 Product binding 的额外权力。**不能仅因未装配 owned import factory 就认定原入口不支持**：原 transient／非 owned 恢复是现有成功路径。其 bytes 接续必须复用原 factory 能力并保持存储、引用与清理语义；在完整替代与成本证明之前，不实施 owned-only 替换，也不保留一套永久 Coding staging 作为虚假删旧成果。
5. Coding 验 target/source/provider、Product max bytes 与所选 fallback cwd，构造输入值，驱动原 prepared operation；仍不信任 payload 的 cwd 建议。`_CodingPreparedSessionSettlement`、原 Continuity lease 与 cleanup-debt 持有者继续存在，不把任务成功视为已交付。

不新增运行组件或环境关系；这是既有 Continuity→Session→Transcript 的输入表示与原装配端口收敛。既有文件导入、原有 Session、新/恢复/删除/Goal 等业务入口不改。

## 兼容与必须关闭的问题

| 事项 | 需要保留或明确的规则 |
| --- | --- |
| JSONL 附件来源 | Coding 的旧 `temporary_root` 相邻 Blob 位置必须先用原实现证明；若存在合法旧成功路径，新值须显式携带原位置并复用 read-only BlobStore，不可一概拒绝 references 或改用目标 Session 的库。缺失、外来或摘要错误按原 owner 拒绝，不能隐式创建源 Blob store。 |
| 临时目录参数 | 公开 constructor 的参数形状保留。它承载的附件来源仍有意义；新路径退出的只是 staging 写入/删除。原 nofollow/private-path 限制中，哪些保护实际附件来源，哪些仅保护将退出的临时文件写入，需分别取证。不能为削减数量默默放宽实际来源权限。 |
| 平台能力 | 本片不开放现有未支持平台。`supports_coding_continuity_secure_staging` 的公开名称、bootstrap 与 direct bridge 原支持门槛暂保持；原 direct bridge 自身也有平台检查，不能只保留 bootstrap 门槛。是否退出旧 capability 名另行处理。 |
| diagnostic/metadata | 原随机临时文件路径不是持久来源身份；新入口显式标记 portable source，label 只作诊断。不能伪造 physical authority fingerprint，或把 label 当附件根。原文件入口的 path/fingerprint/metadata 原样保留。 |
| cwd | Product fallback 与 missing-cwd 翻译保持，输入 header 与 payload 建议不越过 Product 校验。before hook 取消不得构造未等待 coroutine 或开始目标存储 IO。 |
| 取消 | 优先保留直接 await，且 prepare 返回后到 settlement／lease 返回之间无新增 await。原 `_prepare_candidate` 的 transition 退出同步 release，factory/store 已覆盖构造失败/取消；移除临时 cleanup await 可同时移除该旧交接窗口，不预建另一份 shield task/registry。若实际实现新增子任务或交付前 await，必须取回同一成功 prepared，并由原持有者保留 abort 失败的可重试凭据，不能只加 note 后遗失 candidate。 |
| 存储失败 | 原 admission、writer busy、Blob 部分发布、commit unknown、factory fence、unpublished rollback 保持；新 bytes 不能绕过 store identity 或 known-missing-store 拒绝。 |

本片不把 transient 文件的 mkdir/open/write/unlink 故障继续伪造为业务故障；这些只在对应 staging 实现退出且来源/目标存储责任已闭合时一并退出。测试应改到实际副作用 owner，继续覆盖真实来源、目标、取消和未交付清理负例，不以删除安全断言报绿。

## 删除清单与全替代预算

实际候选池是 `_PrivateContinuityPayload` 到临时 payload 原子写/删函数，以及 prepare 内 staging 清理分支。它们包含约 230 行定义及调用协调；其中仍需存在的来源路径校验、平台能力检查和 cancellation ownership 不能算消失。公开参数、必要 imports/类型/转发和文档兼容成本均须计入。

新输入值、factory 分流、Product/Session 端口、Coding 薄调用和取消持有合计应先做完整草拟 diff，再决定实施。原审计给出的系统净减 90–150 行只是预算；保留附件来源/取消债务后可能更少或为负，不能预支为收益。若净量不成立，撤回该替换，不能复制导入器或以迁移量冲抵。

## 验证与评审

实施前从旧真实桥接/owned import 固定 JSONL 无附件、有附件、缺失附件、ZIP 图片、Product cwd、before-hook 取消、prepare 失败/取消与清理重试的结果。固定预期不得取自新实现。目标是同一记录、Blob 身份和 bytes、原失败 authority 与可重试 ownership；不固化已退出的随机临时名称或 syscalls。

实施验证复用原 `test_continuity_import_bridge`、bootstrap、owned bundle/source/rollback 与 Session lifecycle 测试；补缺失的实际责任合同，不扩 PR gate，不运行付费模型。文件入口回归和 portable 入口都必须覆盖，Linux 证据不等于其它平台支持。

R1 的[三视角专项评审](continuity-bytes-import-convergence-review.md)已完成，但结论为尚未具备实施条件。R2 据旧行为修订，不冒称重新评审后已经通过。必须先关闭完整非 owned 接续、来源准入与全替代成本，再认定可实施；本稿不替代重要架构工作件的用户评审，也不宣称整个 Coding Goal 已完成。

## R2 已核实的旧行为与剩余事项

在任何相关产品代码修改前，新组合取证 **8 passed（1.89s）**：实际 Coding bridge 配合原 owned import／非 owned transient open/bundle 叶子，验证无附件 JSONL、带图 JSONL、初始缺失 temporary leaf 的合法相邻附件、两类 owned ZIP、两类无附件 transient 输入及 foreign Blob 根拒绝。输入数据和目标均为真实私有磁盘目录，Blob／unpublished retraction 为真实实现；薄 runtime 没有覆盖 Coding SDK 发现、Agent 构造和完整 lifecycle hooks，不以这些结果宣称 SDK 全链路已验证。

旧 transient JSONL 成功后还会留下 `continuity-*.jsonl.lock`。取证记录该实际残留，未更改产品来报绿；若 staging 退出，这个临时实现副产物无需伪造保留，但不能借此删除真实来源／目标的锁或清理凭据。

这些结果否定“没有 owned factory 就一律不支持”和“source 叶目录必须预先存在”两项错误收敛假设。JSONL 仍只走原 JSONL decoder，不套 ZIP 专属 portable ID／UTC header 规则。现有 factory、pending store 和 Prepared 各自的清理边界不能被合称为一个万能兜底。

下一步须提出同时覆盖原合法构造范围的完整接口／干差分并计全部成本；没有这份证据，不启动本候选的产品实现。系统净减 90–150 行不再作为可依赖的承诺或已发现收益。


## A60：完整 Product runtime 路由补证（仍未实施）

新增旧行为观察贯通实际 ProductSessionRuntime、ProductTranscriptSessionBinding、SessionLifecycleRuntime/Prepared 与原 Transcript/Blob IO，builder返回真实ProductTranscriptSession而非构造Agent；不是完整Coding bootstrap/SDK或编码工具证明。三份一次性观察器各1 passed（2.82s、2.43s、2.33s），共13次正/负观察，不能称13项业务成功。初始bare非owned factory与补有session_file_factory的配置分列；只补配置项不改产品、不覆写旧结果。输入有随机时间/操作名，未另逐进程记录module.__file__，不能冒称完整冻结的候选差分夹具。

| 实际旧分支 | 核实事实 | 对候选的约束 |
| --- | --- | --- |
| 非owned持久JSONL | 原stage_file_import先复制到目标Session目录；before hook已看到该文件；abort删JSONL但留下原lock/index，consume保留复制文件 | 不是直接_frozen import的同义入口；要复用原文件导入owner及Prepared清理，不新建staging服务 |
| 非owned JSONL（临时/配置后的持久）带图 | 可以准备成功并报告missing，不主动转存源图片对象 | 不得一概套用owned的源附件读取/严格拒绝或复制规则 |
| 非owned持久ZIP，file factory/cwd均有效 | 准备成功且附件available；abort仅删除复制的ZIP输入，规范JSONL及Blob仍留；consume保留输入ZIP及规范数据 | 原owned unpublished rollback不覆盖所有profile；不虚构统一撤销保证 |
| 配置相同ZIP但header cwd不存在并提供fallback | 首轮目标/Blob先建，后验cwd失败后重试，再因目标Blob authority已存在而失败，留首轮目标文件 | 旧副作用问题未修复；若新方案提前验cwd或只导一次，应作为原owner的行为修正单列评审，不称旧失败/副作用完全保持 |
| before-hook取消 | owned目标尚无IO；非owned持久路径已先复制目标文件，取消后cleanup | “取消前无目标IO”不能写成所有旧route的Current；目标方向和兼容代价须明确区分 |

R2的完整非owned接续不能简化为调用一次_frozen helper：应分别保留原owned import、legacy file import、detached restore的存储/引用/接受/清理合同。尚未决定新API、端口与完整替代成本；没有实现或新设计接受，不重新承诺90–150净减。若要改变普通Path分支、cwd重试或非owned rollback，必须明确列出该变化及验证，不借bytes入口隐改。

用户另明确要求：共享实现不可放Harness根目录，应放回Runtime文件导入、Transcript、Session、Resources等对应原子系统，保持窄输入、原依赖方向、高内聚低耦合。当前新增23个生产源码已检查，Harness根目录新增实现为0；该规则已写入[实施Goal](../coding-private-data-implementation-goal.md)。

## A65：复制扩展端口与非持久引用的补充约束

本轮仍未实现。一次性旧行为观察使用实际bridge／ProductSessionRuntime／Transcript、真实私有磁盘与同一冻结JSONL输入，九个实际模块路径及SHA在进程中记录；builder不构造Agent或模型。最终1 passed（2.21s），含三次prepare成功及一次原复制策略的预期拒绝，不称四次业务成功。观察脚本先后遗漏自身fixture父目录、错误使用parents默认权限，两次失败均保留；只修正脚本自身私有目录准备，没有改产品、放宽准入或改expected。

- **旧复制端口有行为合同。** 非owned持久路径实际调用Product注入的FileCopy，源Path真实存在且parent为temporary_root；复制端口可以在before hook／build之前拒绝。配置VerifiedFileCopy且discovery fingerprint存在时只走verified分支。新的bytes发布不能绕过旧拒绝政策，也不能用bytes摘要充当物理文件fingerprint；完整替代须说明兼容Path或等价内容端口及全部成本。
- **非持久JSONL仍有公开引用。** 实际`get_session_file()`在bridge.prepare返回后是已清理的源PosixPath；consume后原runtime当前引用仍是该路径字符串。无文件导入若返回None或另一种ref，是需要显式比较的行为变化；不能用`_import_frozen(persist=False)`直接推导等价，也不伪造physicalPath。是否保留旧兼容适配或演进引用仍未决，本轮没有接受任一方案。

普通Path、owned、legacy非owned与detached的职责、来源准入、before hook、fallback及清理范围继续分列。保留真实Path兼容适配时，不把旧staging原样搬入Harness当作算法复用；直接复用现成RootedFileIO也须注意其Linux限制不能收紧原POSIX支持。还没有完整替代diff、全成本或R3接受，R2继续draft/not-started，原Goal数量及完成条件不变。
