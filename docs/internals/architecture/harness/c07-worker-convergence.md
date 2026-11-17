# C07 Worker 职责收敛与删减

- Authority: descriptive audit / execution evidence
- Design status: accepted — implementation-owner review within C07 scope
- Implementation status: delivered — task PR #894 and integration PR #895 merged; CI, synchronization and cleanup verified
- Owner: Coding / Harness Worker / Package Product / Hosting
- 执行基线：`cb54b4b6d13e82d7cb9043862ab67c20293e7b9f`；开始时 fetch 后 main 与 lane/harness 相同。
- 方法查阅：本机 archmethod clean `master`，`0f9bd3ff51afabeaaf76cc38dff1ceb279b7d37e`；不声称与方法上游同步。

## 范围、事实与验收

按 Coding 原职责清单重新定位 112 个 C07 Python 文件，基线为 20,533 个物理行（含空行、注释、docstring）。
已冻结逐文件 SHA、模块说明、声明位置、Harness/Hosting 导入及 src/tests 的静态引用路径，外部记录为本次任务的 `baseline-audit.json`。
引用是模块名静态匹配，不证明动态消费者不存在。函数体精确 AST 匹配未发现长度至少 13 行的完全相同体；这不排除带类型、错误标签、平台或步骤差异的语义重复。

本轮验收范围为全部 C07，不以先完成某一链代替整组完成。先前迁移均是基线；已有 Worker storage/history、Package Product authority 和 Hosting 原生执行不重计收益。
每个文件均已给出具体保留或退出理由；本地适用断言已验证。Windows 原生及未选中的平台路线未执行，见最终验证限制；远端交付已由 PR #894/#895 完成。

| 要求 | 完成证据 | 当前状态 |
| --- | --- | --- |
| 112 文件的调用方、共享实现、支持及存量依赖 | 逐文件静态清点 + 具体源码/测试复核 + 最终处置 | 112项职责与17项争议处置已接受；本地验证完成，原生平台限制单列 |
| 完整链路归已有 owner，旧实现退出 | 实际调用路径、替代实现、差分与失败路径验证 | 四批实际接线和旧流程退出已核实；未搬迁项按第5项明确保留 |
| 先复用、再删除，核实动态与兼容消费者 | 基线对照、公开/名义契约及原测试 | 已核实；公开名义契约和历史格式保留 |
| 无平行框架或大量回调搬运 | 原 owner 接入与新增成本复核 | 四批及保留项已审查和本地验证；未新增框架/Protocol/账本 |
| 系统成本与纯去重分别报告 | Coding/Harness/Hosting/其他/总量，测试和文档单列 | 已记录迁移/去重成本，累计生产 +42 |
| 正常、失败、恢复、退休兼容 | 现有适用本地检查及远端平台实际结果 | 本地适用断言已验证；未执行的原生平台路线单列 |
| PR→lane/harness→main、同步与清理 | 已合并 PR、实际 CI、提交树及清理核验 | PR #894/#895 已合并；本地与远端已同步，原实现任务 worktree 已清理 |

## 实施顺序与已有 owner

1. **载荷、待启动身份与请求绑定**：POSIX 的物化/规划/绑定已用 `worker.payload._selected_payload`，存储和债务修复已用 `_storage/_recovery/_repair`。Windows 的原生 stage 创建、检查和物理退休已用 `_windows_stage_io/_windows_stage_retirement`；Coding 的 Windows pending/materialize/bind 仍有较长组合流程。先明确 Product 准入与中性机制的边界，保留持锁下观察顺序及阶段创建失败留下债务的语义。
2. **回执与启动意图**：复用 `package_product._worker_product_authority`、`worker.history._receipt_store/_windows_record_journals` 及原 `WindowsProductWorkerIntentRecords`。核实两平台选定 Session 的关联证明、原生证据与 kill switch；不能重复搭建 receipt owner。
3. **历史关联与恢复**：复用 `_linux_worker_history/_linux_worker_recovery`、`_worker_windows_attempt`、原六流 semantic bases 与既有 Journal。核实 retained attempt、GC、备份、Job absence 与 orphan lease 的关联，明确无法观察不等于不存在。
4. **停止、退休与清理**：保留独立 Supervisor/native/C5/lease/payload 事实；优先合并确实重复的协调。完整、partial、unlaunched、crash 四种 stage 的允许状态不同，不能仅因函数形状相似合并批准政策。

普通 Session 启动、Resume、pending host、provider 和 query 为真实消费者，必须与上述四链一同验收；此前 `_ordinary_prepare`、Session provider、history publication 的共享寿命不重新实现。

## 成本与设计约束

Windows payload 的直接函数搬迁尚未采用：该模块目前 498 行，主要三条流程为 pending 规划、物化和请求绑定。若通过库存、Supervisor、marker、错误及值构造的多组回调照搬，会产生额外接口成本，不能据迁出行数宣称删减。
已比较现有 owner 的直接复用、同域去重与迁移成本；Windows payload 的额外 scope 包装已否决，具体保留理由见原17项处置。

当前生产变化：Coding −267、Harness +309、Hosting 0、其他 0、系统总量 +42。测试净 −2 行：故障注入接缝适配 +3、两份架构清单删除已退出依赖 −5；无新增 case、断言或 PR 门禁。文档当前净增281行，测试和文档均不计入生产成本。尚未实现系统净删减，不将 Coding 迁出量计为系统收益。

## 兼容与验证义务

- 公开 API、名义类的模块路径/字段/slots/pickle、历史 wire 与错误身份保持基线；动态探针和故障注入接缝必须核实实际消费者。
- 锁顺序、观察次数/顺序、发布后复核、异常优先级、持有句柄期间的最后复核及失败留下的恢复债务不可随迁移改变。
- Windows pending 要求 exact type，POSIX 某些入口接受 isinstance；不得机械统一。只读 review 不得授予写入、修复或删除权限。
- 本地 pytest 使用管理 wrapper、工作树 PYTHONPATH、non-live/skip-host-runtime，并从第一次就在 sandbox 外执行。用户已明确批准本轮测试临时使用私有磁盘目录 `/home/dev/.cache/loushang-tests-c07`；仅测试环境覆盖，不修改正常 Product/AppHost runtime 或其他 lanes 的规则。
- 使用现有 change-aware 计划决定本地与远端路线，不新增或扩大 PR 门禁。未执行的平台路线单列，既有绿灯不作为本轮变更的替代证据。

## 首批实现与证据

本批设计由 Codex 实现 owner 在 C07 授权范围内接受；仅接受下列边界，不据此关闭整 C07。

- **Windows 崩溃原生清理**：在原 `_worker_windows_attempt` 增加固定清理操作，直接复用原 native profile bridge、Hosting Job 观察和 `WindowsWorkerProvisioningStateJournal`。stage/root 句柄及 pinned Journal 一直保持到最终 authority 复核和原名义结果构造；没有第二份账本、恢复器或物理执行回调。Coding 保留 Package orphan→GC 锁内的批准、跨历史关联和原生后端选择。
- **五条退休/结算的离线写入寿命**：complete、partial、unlaunched、crash stage 及 reserved native settlement 共用同一原 owner 的 Package quiescence→active lease 拒绝→writable GC→authority 复核作用域。五个产品政策体和各自错误类/文本原样保留；不增加退出时复核，不改变 early return 的资源释放。

职责迁移按两组机制统计；纯去重仅可核实为五个相同写入作用域合一、退出四个重复作用域体。原生清理是 owner 归位，不冒称重复删除。两组成本分别为 Coding −78/Harness +102/系统 +24，以及 Coding −10/Harness +19/系统 +9；累计 +33，尚未实现系统净删减。作用域抽取的成本仍需结合后续实际复用复核，不以 Coding 下降作为保留方案的充分理由。

局部验证：

- 现有 native cleanup、stage review 和导入边界组合：169 passed。
- 五条退休/结算及 native cleanup 现有回归：32 passed。
- 7 个变更生产源 mypy（沿用 `--follow-imports=silent`）及 Ruff 通过。
- 112 个模块的公开函数签名、公开类声明与显式 `__all__` AST 保持基线；这不是全部运行时兼容性的证明。
- 仓库外原场景故障差分：34 组观察一致，其中 19 组实际触发故障；五个原作用域对照 70 组一致，覆盖活跃租约、正文返回及锁/正文/退出故障，五个产品政策体 AST 未变。
- 原 native 测试仅调整 mock/故障注入目标，既有断言语义保留；没有将模拟结果当作 Windows 原生执行证据。

此处为首批验证快照；整组本地结果及实际远端交付证据见下文。

## 第二批：复用既有删除 owner，退出重复目录程序

本批由 Codex 实现 owner 在 C07 授权范围内接受。原 `WindowsStageRetirement` 与 `PartialWindowsStageRetirement` 的目录链复核、可执行文件删除和逆序清理父目录重复；现在共用原 `WindowsStageRetirement` 的两段固定程序。保留完整/partial 各自的 root/marker 准入与错误 Profile，不合并退休批准或根删除意图。

共用程序的输入是原已验证记录：完整 review 明确要求目录路径等于 entrypoint 的逐级父链；partial review 要求同一有界连续链。两者均继续调用原 parent owner，保留 partial 与完整的 directory error 类型差异；不创建新的 callback/Protocol/恢复器。原审阅器的字段、构造、wire 与拒绝条件未改。

本批 Coding 0、Harness −17、Hosting/其他 0、系统净 −17；其中包含常规格式变化，不将 17 个物理行全部归为纯算法去重。实际退出的是两份重复的目录程序体：剩余目录链检查、文件及父目录清理。与首批累计生产 +16，尚未实现全系统净删减。

- 现有四角色协议黄金探针及退休回归 102 passed，原黄金文件未改。
- 基于原 NativeModel、精确 main 原实现与候选，在 0/1/2/4/16 层有效目录和 complete/partial/unlaunched/crash 四角色的全部原场景中，300 组事件、异常、句柄、根意图及重试结果相同；这属于合成原生模型证据，不冒称 Windows 原生执行。
- 变更 owner 的 mypy 与 Ruff 通过；更广平台/调用链检查仍属最终验收义务。

### 已否决的物化范围包装原型

尝试将 Windows payload 的 ACL/root/inventory/create scope 再包入 `_worker_windows_attempt`，原型 27 组差分相同（17 组触发故障），但 Coding 仅 −21、Harness +59、系统 +38，并增加单消费者的参数/回调装配。实际 native stage 创建原本就直接复用 `_windows_stage_io`，该额外包装的成本不足以由复用收益支持，已完整撤回，生产收益记 0。此原型结果不是当前候选的验证凭据；Windows 物化职责的最终保留边界见原17项处置。

## 第三批：Linux 历史发布整链归既有 Product owner

本批由 Codex 实现 owner 在 C07 授权范围内接受。六项操作（preflight、stage、rollback、commit、retire、seal）的 runtime/GC、固定根及发布协调转入原 `_linux_worker_history`，直接调用原 `HistoryProofBindings`、实际 `PreparationHistory`、`HistoryPublication` 和 reader，不新增绑定记录、账本、恢复器或物理 I/O 回调。Coding 保留名义 DTO/错误、公开及必要 under-guard 入口、Product/平台准入和实时配额。

这是一条完整发布生命周期的职责归位，而非六份算法去重：原 preparation/publication 引擎本已共享。四段相同的固定根绑定程序现共用一个上下文；其他旧协调体随接线删除。保留各操作真实差异：stage/preflight 将活跃租约交证据 owner 拒绝；rollback 不新增拒绝；已存在 owner 的 commit 重试跳过 V1 重证，可在活跃租约下继续；retire/seal 在 GC 之前拒绝。保持两次 index 配额读取的原时点、发布后的 authority 复核，以及锁/绑定退出异常的优先级。

本批 Coding −94、Harness +205、系统 +111；累计 +127。成本主要来自显式名义类型/错误/配额适配和六项独立操作入口，避免用布尔分派或统一活跃租约规则压缩差异。接受理由是同一既有 Product owner 现在持有整条发布链的锁与根寿命，Coding 不再协调物理发布；不是为了行数下降。对单消费者 scope 包装的拒绝仍有效，不把此次归位宣称为系统精简。

- 现有五组历史发布回归：31 passed，覆盖真实 Product、五流发布、部分写入、回滚、重试和退休。
- 现有 publication compatibility 与 import boundaries：173 passed。两组结果有覆盖重叠，不相加声称独立用例总数。
- 仓库外对照精确基线原程序：114 组比较一致，其中 72 组实际注入故障。六操作的事件/异常链、真实 rooted fixture 文件字节、两次重试及剩余文件一致；覆盖 runtime/GC/root/bind/写入/删除/退出故障、活跃租约、非法 cutoff、已提交 owner 重试和中途配额改变。锁及 review 事实使用现有合成模型，不替代原生平台验证。
- 112 个模块的公开函数签名、公开类完整 AST 和显式 `__all__` 保持基线。两个改动测试文件的 46 条既有 assert、14 个测试函数的签名/参数化完全未变，只调整故障注入目标及 fake 的 bindings 参数。
- 六个生产源 scoped mypy、八文件 Ruff 通过；此处为当批快照，整组本地回归与实际远端 CI 结果见最终验证记录。

## 第四批：直接复用、重复读取程序与无效胶水退出

本批由 Codex 实现 owner 在 C07 授权范围内接受。只使用既有 source、payload、checkpoint 和格式 owner；不新增 Harness 接口、Protocol、账本、恢复器或生命周期框架。

| 去重/退出单位 | 实际接线与兼容边界 | 本批系统物理行 |
| --- | --- | ---: |
| 三处 guarded source→recovery→Desired→source 复读程序 | `history_sources` 中只留一份，三条真实产品路线调用；原有 bounded capture 仍属 Harness | −33 |
| 两处 gated recovery 根打开/校验/关闭 | 直接调用既有 `PayloadStorage.open_root`，保留两次路径读取及原异常/关闭优先级 | −10 |
| checkpoint 的空包装 `_CapturedStoreIdentity` | 三个原命令直接接既有 registry；原 commands 只读取其 store_id，不序列化或比较包装身份 | −10 |
| 四个无消费者 alias、validator 和空 TYPE_CHECKING | 核实 __all__、支持的动态/故障入口、历史 JSON 字段和 canonical pickle identity 后删除；实际有测试消费者的 `_fold_opt_in_events` 保留 | −24 |
| empty-debt 指纹的重复字段编码 | 直接用原 `empty_fields`；名义类、字段/slots/构造、wire 和 pickle 不变 | −8 |
| 合计 | Coding −85、Harness/Hosting/其他 0 | −85 |

这是生产系统实际净删减，未将字段迁出 Coding 当作收益。与前三批累计 Coding −267、Harness +309、Hosting/其他 0、系统 +42；C07 原 112 文件当前 20,266 行。完整发布生命周期的通用化和名义错误/配额适配成本尚高于删减 42 行，不宣称整轮系统净减少。

semantic 捕获函数只返回一个延迟的纯名义值构造器，没有外部 I/O 回调参数。普通语义读取原来在 GC/runtime 退出后构造，preparation/reference 则在原 guard 内构造；保留这一差异及 store_id/owner_revision 的原读取次数/顺序，不能为了缩行改变失败优先级。三个原公开记录类不新增字段。

局部证据（覆盖有交叠，不相加声称独立用例总数）：

- 现有 Windows preparation/reference/checkpoint/source 探针：45 passed；原唯一故障注入测试改指真实 source owner，断言未改。
- 精确基线三条原程序对照：57 组一致，33 组实际触发故障，比较两次重试、观察/锁/构造顺序、错误链及 retained bytes；使用实际名义证明值及合成 custody，不替代 Windows 原生验证。
- 现有 checkpoint、历史公开值/slots/pickle、注册与 payload 恢复：1,251 passed。随后纯 empty codec 改动的受影响黄金场景补验 45 passed；黄金文件未改。
- 两个精确基线 gated 程序：161 组一致、129 组触发故障；原 root 路径、打开/校验/关闭、Supervisor 转换及重试顺序相同。这是合成观察，不等于真实进程崩溃验证。
- 四个 alias 的原 pickle 指向原 Harness canonical 名称，删除 alias 后仍能解出原对象。empty-debt 的 27 组值指纹和 54 份原始 protocol4/5 pickle 字节一致。
- 112 模块的公开函数签名、显式 __all__ 和公开类声明保持基线；唯一有意的方法体变化是 empty-debt fingerprint，已单独与精确原类对照。其他公开类完整 AST 未变。
- 10 个变更生产源 scoped mypy、Ruff 和依赖事实检查通过；empty codec 后单源 mypy 通过。真实 Linux Product 事务 1 passed；该组合中 Windows 原生 42 skipped、host-runtime 7 deselected，明确不计为原生平台通过。

## 最终验证、交付与平台限制

生产候选为 `e0a382e27c8682b958537cf176e3c9891000903c`；后续收尾只同步架构清单和文档，生产源码字节未变。按同一基线重新生成的现有检查计划未增加路线、平台或门禁。

| 既有检查 | 实际结果 |
| --- | --- |
| Coding 完整离线路线 | 4,240 passed、24 skipped、76 deselected，3024.62秒 |
| Harness（含运行支持与架构） | 首次 6,357 passed、110 skipped、2 failed，922.43秒；两项失败均为已退出依赖仍列在精确架构清单 |
| 受影响的 C50/C54 两个架构文件 | 删除过时清单的5行，保持原边界断言；全部16 passed，47.66秒 |
| Hosting（含消费者/架构） | 517 passed、56 skipped，131.20秒 |
| unit 严格收集与额外示例 | Harness 6,049/6,052选中、3未选；Hosting 453/457选中、4未选；额外示例3 passed |
| 静态与文档 | Harness 909源、Hosting 36源类型检查、既有 Ruff、生成依赖事实及9项文档不变量通过 |

本地采用执行去重，不声称原 `check_changed` 脚本整体返回0：该脚本在上述两份旧架构清单处终止，修正后复跑受影响文件并单独完成原计划尚未运行的 Hosting。Coding 完整命令覆盖 `unit_coding`，两者仅后者额外排除 e2e_smoke。Harness/Hosting 的完整路线包含其 unit 路线全部目录；unit 的严格收集另验，Harness 两个额外示例文件另跑。没有通过修改 CI、跳过失败断言或重复整套已通过的数千测试获得结果。各结果覆盖交叠，不相加为唯一测试数。

支持的 `python -m loushang.coding.cli --help` smoke 已通过；完整 Coding 回归包含既有真实 Session/tool/persistence/resume 等行为。原实现差分及名义契约核对是补充证据，不代替这些实际消费者。

平台限制：本机未运行 Windows Worker 原生 LPAC、Job/句柄和真实崩溃路线；`harness_native`、`host_runtime`、`windows_shell` 对应平台路线未选中。PR #894/#895 的现有 CI 均实际通过 architecture、Coding/Harness/Hosting 模块回归及 Ubuntu/Windows/macOS Resume E2E，没有扩大门禁或额外 dispatch。Linux 真实 Product 事务已通过；三平台 Resume、Windows 合成模型及跳过项目不代替 Worker 原生验证。

交付证据：[任务 PR #894](https://github.com/zhnt/loushang/pull/894) 合入 `lane/harness`（`2209e8bbdac19ecfb33ec78e82969c78c90ae457`），[集成 PR #895](https://github.com/zhnt/loushang/pull/895) 于 2026-11-17 合入 `main`（`0e116370f748dd730bcca6bd9cf32348a567d475`）；两者全部现有检查通过。原交付时本地/远端 main 与 lane/harness 均同步到该提交，三处用户改动的差异哈希不变；原实现的两个任务 worktree 及本地分支在 clean、无独有提交核验后安全清理。

## 原 17 项 mixed 的职责处置与保留成本

Codex 实现 owner 按本任务第5项接受下列具体保留边界；不是用户另行架构批准。17 项的逐文件结论在下表，本地适用断言已验证，不将其等同于 Windows 原生执行证据。

- **payload、start gate 与 gated recovery**：已有 selected payload/storage/recovery/Hosting capture 是通用执行 owner。Product 持有唯一 gate 写端并先记录 bound 再批准释放；单一 `_offline` 决定产品读/写权限和特有复核顺序。两处确实重复的根程序与 empty 字段编码已退出；不以回调/mixin 拆散批准事务。
- **POSIX checkpoint 与两平台 native approval**：实际持久化/CAS/重放已是原 CheckpointCommands/RootedNativeApprovalRecords/WindowsNativeApprovalRecords。保留的是 closure、独立审批/撤销及原错误/型别准入，空 store 包装已删；再增加 writer/分派层不能删除第二套物理实现。
- **Windows crash C5、lease、Supervisor**：实际 C5/Journal/Package/原生 IO 均由原 owner 执行。保留 contract2、只读 stage pin 跨 Package append、精确 Job absence 和 phase/failure 政策；cleanup writer 不能替代只读 validation guard。POSIX 与 Windows 的幂等/absence 前提不同，不创建带标志的统一恢复器。
- **Windows preparation/checkpoint/bases/cutover/reference/source**：重复的来源捕获合一；全部底层 IO 仍复用既有 receipt/source/attempt owner。六种 Code base、native approval/Desired/backup 承诺及不切换 authority 的批准是具体产品模型。Linux V2 owner-index/segment 发布与这些 Windows 历史格式不同，不能直接拿来接管；也不另建平行 publication 框架。
- **Windows payload 与 recovery inventory**：物理 stage 创建/验证及多源 inventory/admission 已在原 Harness。保留私有铸造请求、跨 Code receipt/backup 的批准和准确错误/类型适配；单 scope 包装实测系统 +38 已否决。更多 factories/多源 bindings 没有额外中性消费者，不为减少 Coding 行数增加装配层。

后续可因新的真实消费者或协议需求重新评估这些保留项；本轮不预设迁移比例，也不承诺对原公开名义格式做破坏式压缩。本轮没有未处置的源码职责项；本地完整路线与受影响检查已验证，未执行的平台路线和实际远端 PR 交付证据另列。

## 逐文件源码职责清点

下表记录基线实物，所属链仅用于复核排序。全部文件已静态清点，112 个已完成源码职责复核，0 个待复核；原 17 项 mixed 已逐项给出处置及必要产品边界/适配保留理由。保留结论依据实际委托、名义/格式/产品职责及消费者；不因为文件短而保留，也不据静态无引用删除。源码职责复核与本地回归已完成；原生平台限制及实际交付证据见最终验证记录。

| 文件（相对 Coding） | 基线行 | 源码引用文件 | 测试引用文件 | 复核链 | 当前语义处置 |
| --- | ---: | ---: | ---: | --- | --- |
| `package_product_worker_activation_base_v2.py` | 32 | 3 | 5 | 历史/状态/证据 | 保留公开 C5 replay/base 名义类、字段和原类型绑定；重放及 wire schema 用现有 _activation_base。 |
| `package_product_worker_activation_history.py` | 53 | 15 | 10 | 历史/状态/证据 | 保留公开 retained-attempt 名义字段及 decode/validate 兼容名；fold/project 均用原 _activation；无消费者私有 fold alias 已退出，原 canonical identity 保留。 |
| `package_product_worker_activation_state.py` | 113 | 5 | 12 | 历史/状态/证据 | 保留候选信任类/Product 准入、名义 Store 和公开 typed 入口；POSIX CAS 用原 ProductActivationStateStore，Windows 用原 Journal，无第二 CAS 实现。 |
| `package_product_worker_activation_state_journal.py` | 88 | 3 | 9 | 历史/状态/证据 | 保留名义 Journal、动态配额/record codec/Profile、Coding retained type 与 stream_index=2 的 checkpoint 来源绑定；物理存储/重放用原 SegmentedActivationJournal。 |
| `package_product_worker_capability.py` | 151 | 4 | 4 | Session/Provider 消费者 | 保留 Coding receipt/request 与独立 Capability owner 的准入关系、只读 facet 批准及失效错误政策；实际 owner policy/grant/decoder 均用既有 FacetOwnerPolicy，不发布额外 Capability。 |
| `package_product_worker_cleanup_evidence.py` | 113 | 3 | 3 | 恢复/退休/清理 | 保留 Coding authority ID/fingerprint、名义继承关系与 typed 兼容方法；实际重开/树结算/跨 boot absence/注册租约证明用原 CleanupEvidenceAuthority。 |
| `package_product_worker_crash_c5_settlement.py` | 102 | 3 | 6 | 恢复/退休/清理 | 保留名义错误、typed evidence authority 继承/构造和公开及必要 under-guard 兼容入口；crash C5 事务用原 _linux_worker_recovery；无消费者私有 alias 已退出，原 canonical identity 保留。 |
| `package_product_worker_discovery.py` | 95 | 2 | 3 | Session/Provider 消费者 | 保留 Coding SessionManager 实例、持久化 Session/路径一致性准入、Profile codec 与选择错误；发现/附着读取算法在原 _AttachedDiscoveryMethods，无 activation 权限。 |
| `package_product_worker_gc_references.py` | 45 | 1 | 2 | 历史/状态/证据 | 保留带 Coding 名称的只读 GC 查询入口与签名；匹配算法用原 _retention，不新增账本或删除授权。 |
| `package_product_worker_history_checkpoint.py` | 288 | 9 | 23 | 历史/状态/证据 | 保留名义 checkpoint/backup/stream Profile 与 publish/repair/rollback 的产品 closure 准入；全部物理发布/修复由原 CheckpointCommands 执行。本轮删除无效 CapturedStoreIdentity，直接传 registry；再包同一作用域需额外 review/命令分派接口，保留当前最小产品适配。 |
| `package_product_worker_history_checkpoint_anchor.py` | 66 | 4 | 14 | 历史/状态/证据 | 保留 checkpoint anchor 名义记录/错误类型；原 _anchor 完成读写与固定根操作。 |
| `package_product_worker_history_commit_v2.py` | 138 | 0 | 13 | 历史/状态/证据 | 保留公开 API、名义错误、cutoff/Product 准入和原 HistoryPublication 实例/配额；完整持锁提交与 owner 重试转入原 _linux_worker_history，旧协调体删除。 |
| `package_product_worker_history_cutover_v2.py` | 99 | 2 | 9 | 历史/状态/证据 | 保留 stream-cutover/index 名义字段、实际 Coding 类型绑定与历史 wire；解析/共同校验用原 _StreamCutoverMethods/_IndexMethods。 |
| `package_product_worker_history_deletion_v2.py` | 34 | 1 | 13 | 历史/状态/证据 | 保留 V2 deletion-ledger 字段及实际 Coding prepared 类型绑定；解析/债务关联用原 _DeletionLedgerMethods。 |
| `package_product_worker_history_preflight_v2.py` | 93 | 2 | 4 | 历史/状态/证据 | 保留公开/必要私有签名及名义 preflight 错误、Product 准入；cutoff 机制和 runtime/GC 下证据准备由原 _linux_worker_history 唯一执行。 |
| `package_product_worker_history_prepared_v2.py` | 112 | 5 | 9 | 历史/状态/证据 | 保留 prepared 名义字段及五种实际 Coding base 类型绑定；两个证明入口委托原 _PreparedMethods/retained reference closure，不新增证明引擎。 |
| `package_product_worker_history_read_v2.py` | 98 | 9 | 19 | 历史/状态/证据 | 保留五种 replay union、retained-history 名义字段、错误及实际 preparation/checkpoint/ledger 类型绑定；读/预提交证明唯一由原 RetainedHistoryReader 执行。 |
| `package_product_worker_history_retention.py` | 364 | 8 | 6 | 历史/状态/证据 | 保留 retained review/reference 名义字段、Coding文件命名/备份/真实类型/Profile绑定；大块跨历史读取/引用闭合/判据已用原 LinuxWorkerHistory/RetentionReviewMethods。27项lazy绑定是此前基线，不重计迁移。 |
| `package_product_worker_history_retire_v2.py` | 88 | 0 | 6 | 恢复/退休/清理 | 保留 Linux/Product 准入、名义错误、原 publication 与实时配额 Profile；退休锁/根文件寿命转入原 _linux_worker_history，旧协调体删除。 |
| `package_product_worker_history_retirement_preview.py` | 71 | 2 | 10 | 恢复/退休/清理 | 保留 anchor/checkpoint/snapshot/错误类型 Profile 和公开 preview；结构校验/投影用原 _PreviewMethods，默认不授予删除。 |
| `package_product_worker_history_rotate_v2.py` | 75 | 0 | 5 | 历史/状态/证据 | 保留 Linux/Product 准入、名义错误、封存配额和公开入口；空 Supervisor checkpoint 证明及完整封存协调转入原 _linux_worker_history，实际封存仍用原 HistoryPublication。 |
| `package_product_worker_history_segments.py` | 18 | 7 | 37 | 历史/状态/证据 | 保留既有历史存储兼容命名空间、公开及必要私有转发；实际存储只在原 _segmented_history，无第二实现。 |
| `package_product_worker_history_stage_v2.py` | 178 | 5 | 23 | 历史/状态/证据 | 保留 preparation intent 名义字段/schema、公开 under-guard 入口、Product 准入与配额；完整 stage/rollback 由原 _linux_worker_history 调用实际 PreparationHistory。 |
| `package_product_worker_history_stream_snapshot.py` | 120 | 5 | 24 | 历史/状态/证据 | 保留 snapshot 名义字段、准确 Product/五流顺序准入、配额与 V2 reader 绑定；物理读/捕获/prefix extension 用原 SnapshotHistory。 |
| `package_product_worker_history_v2_names.py` | 4 | 4 | 17 | 历史/状态/证据 | 保留固定 V2 格式兼容导出；名称事实源仅为原 _v2_names。 |
| `package_product_worker_installed_native.py` | 154 | 7 | 6 | 载荷/原生材料/待启动 | 保留 launcher/closure 名义字段、reader 兼容入口、Coding approval/版本/信任/配额绑定；安装材料/收据复核及 native custody 均由原 LinuxWorkerNativeReleaseCustody/Verifier 执行。 |
| `package_product_worker_native_approval.py` | 242 | 8 | 10 | 回执/意图/批准 | 保留真实独立批准/撤销、候选 trust、名义类型和命令准入；物理 root/JSONL/CAS/重放用原 RootedNativeApprovalRecords。其 current/change 是批准政策与持有既有根端口的产品组合，不新建批准管理器或 journal。 |
| `package_product_worker_native_install.py` | 74 | 1 | 2 | 历史/状态/证据 | 保留已批准发行物入口、发行版本选择和必要验证/写 stage 兼容名；执行/修复均用原 native custody。 |
| `package_product_worker_native_release.py` | 77 | 2 | 9 | 历史/状态/证据 | 保留显式生成发行物候选的来源路径、GC 绑定和错误 Profile；字节/closure 验证只在原 _LinuxNativeReleaseVerifier。 |
| `package_product_worker_no_effect_archive_v2.py` | 74 | 3 | 3 | 历史/状态/证据 | 保留 no-effect proof/archive 名义字段、Coding 产品 ID 和实际记录类型；共同证明、codec、bound archive 读取用原 owner。 |
| `package_product_worker_no_effect_closure.py` | 31 | 0 | 4 | 历史/状态/证据 | 保留公开 typed no-effect 判据入口与 Coding product_id；共同关系证明仅在原 is_no_effect_closure。 |
| `package_product_worker_operator_query.py` | 342 | 1 | 6 | Session/Provider 消费者 | 保留显式operator action、Coding SessionManager加载/查询契约/无模型执行政策、实际Provider/authority接线；完整执行和清理用原 session.worker_operator_query，selected payload/profile适配与普通入口共享。 |
| `package_product_worker_opt_in.py` | 208 | 16 | 18 | 回执/意图/批准 | 保留 nominal decision/projection/error、Coding opt-in 类型、codec/配额及公开 Journal 绑定；CAS/分段历史/重放均用原 OptInJournal/OptInDecisionMethods；无消费者 validator/空 TYPE_CHECKING 已退出，原有测试直接消费的 _fold_opt_in_events 保留。 |
| `package_product_worker_opt_in_base_v2.py` | 49 | 3 | 8 | 回执/意图/批准 | 保留公开 replay/base 字段及实际 decision/error/replay 类型绑定；解析/重放/schema 用原 _opt_in。 |
| `package_product_worker_opt_in_owner.py` | 169 | 3 | 2 | 回执/意图/批准 | 保留批准当前 selection/native platform、操作重放冲突政策、kill generation 及实际 opt-in 类型；共享 _capture_worker_opt_in_selection 已复用，POSIX/Windows 均复用同一个 Code _plan_worker_allow。 |
| `package_product_worker_ordinary_bootstrap.py` | 288 | 1 | 2 | Session/Provider 消费者 | 保留Coding持久化Session、startup provenance、coding.base与query Worker的显式选用/历史选择一致性及平台路由；候选/Provider选择、图合成和native准备均调用既有owner。 |
| `package_product_worker_ordinary_error.py` | 12 | 2 | 1 | Session/Provider 消费者 | 保留普通 Worker 显式选用的名义错误及 code 契约；没有通用执行或持久化。 |
| `package_product_worker_payload.py` | 789 | 9 | 13 | 载荷/原生材料/待启动 | 保留名义 payload/debt/lease、错误及必要兼容接口；物化/绑定/债务恢复直接用原 selected_payload/recovery/storage。本轮删除无消费者 identity alias，empty fingerprint 直接复用既有 empty_fields。单一 _offline 保留产品读/写授权及其特有 authority 复核次序，避免另设 scope 回调层。 |
| `package_product_worker_pending_host.py` | 207 | 1 | 5 | 载荷/原生材料/待启动 | 保留选定 query contract、Code base policy/resume绑定、名义pending与错误/相关ID；异步准备、失败清理、发布和释放已用原 ordinary_prepare/session worker_provider，剩余为真实产品接线。 |
| `package_product_worker_policy.py` | 319 | 12 | 13 | 回执/意图/批准 | 保留真实Coding候选trust/allowed platform/profile/无fallback/requiredness/opt-in/Session路由政策及名义值；manifest候选验证和native policy fingerprint已共享；该批准政策应留产品。 |
| `package_product_worker_posix_gc_history.py` | 60 | 1 | 6 | 历史/状态/证据 | 保留 Linux/准确 Product 准入及只读 GC authority 门面；整条 retained-history 证明用原 _linux_worker_history，不授予裁剪。 |
| `package_product_worker_provider.py` | 288 | 7 | 6 | Session/Provider 消费者 | 保留 coding.base及选定capability/data政策一致性、local-worker-candidate信任和实际query Provider提案；底层selected candidate验证复用原Product owner，不能让Harness替产品批准。 |
| `package_product_worker_provider_host.py` | 237 | 4 | 4 | Session/Provider 消费者 | 保留Code receipt/capability/provider候选一致性、名义prepared DTO和兼容release类；prepare/commit/abort/require current 均用原 session.worker_provider，未新增Host执行器。 |
| `package_product_worker_query_consumer.py` | 159 | 9 | 5 | Session/Provider 消费者 | 保留 coding.worker.query 实际 capability/Provider/owner 政策、symbol/text 产品契约与 Session consumer；bounded facet proxy/owner admission 均复用既有 Harness。 |
| `package_product_worker_receipt.py` | 602 | 26 | 20 | 回执/意图/批准 | 保留 Coding SessionManager/Transcript 附着与 selected-root 一致性、native/opt-in 信任准入、Profile、名义字段及 typed API；共同 witness/issue/kill-switch 和持久化用原 ProductReceiptAuthority/ReceiptHistory。 |
| `package_product_worker_receipt_base_v2.py` | 44 | 3 | 3 | 回执/意图/批准 | 保留公开 receipt replay/base 字段、名义 replay 与原 segment codec 绑定；共同行为用 _ReceiptBaseMethods。 |
| `package_product_worker_registered_c5_settlement.py` | 102 | 1 | 3 | 恢复/退休/清理 | 保留名义错误及 registered evidence authority 继承、实际 Code review/bindings 和兼容签名；witness/重开/结算均用原 _linux_worker_recovery。 |
| `package_product_worker_registered_payload_repair.py` | 273 | 2 | 7 | 载荷/原生材料/待启动 | 保留准确名义 plan/intent、历史wire/错误及 no-effect批准适配；完整intent读/物化债务修复均由原 LinuxRecovery/RepairJournal 执行，Coding无物理删除引擎。 |
| `package_product_worker_registered_recovery.py` | 199 | 5 | 6 | 恢复/退休/清理 | 保留 registered/no-effect 的产品批准、contract1/跨boot/未出现Supervisor等条件及名义 review；审阅/lease修复/恢复完整事务已用原 RecoveryBindings/LinuxRecovery owner。 |
| `package_product_worker_resume.py` | 196 | 5 | 5 | Session/Provider 消费者 | 保留 CodingActivationAttemptV2/effect_owner集合及恢复所需状态映射、名义settlement binding；parent scope/enroll/seal/settlement判据用原 ActivationCoordinator，Code不维护第二Resume账本。 |
| `package_product_worker_session_composition.py` | 343 | 5 | 7 | Session/Provider 消费者 | 保留Code query contract/owner、single-worker closure和receipt/trust/admission产品准入、名义ordinary binding；图编译/ordinary合成复用原ProductCompositionCompiler/WorkerSessionComposition。 |
| `package_product_worker_start_gate.py` | 159 | 14 | 14 | 历史/状态/证据 | 保留 Product 独占写端、receipt/native closure/child witness 批准及 journal bound 先于释放的信任事务。原 Harness gated_start/Hosting 已负责 child 身份与读取端；仅有的 pipe 分配/释放是该 Product 写端适配，另建通用 gate/mixin 需跨回调拆开批准事务，未采用。 |
| `package_product_worker_start_gate_base_v2.py` | 53 | 3 | 5 | 历史/状态/证据 | 保留公开 start-gate replay/base 及实际记录类型；first_revision 适配后的解析/重放均在原 _start_gate。 |
| `package_product_worker_start_gate_journal.py` | 230 | 9 | 12 | 历史/状态/证据 | 保留 start-gate 名义字段/错误、紧凑 JSON Profile、候选 trust 准入及 activation journal 首次初始化政策；锁/追加/回放和checkpoint fence用原 StartGateHistory；无消费者私有 fold alias 已退出，原 canonical identity 保留。 |
| `package_product_worker_start_gate_recovery.py` | 350 | 2 | 4 | 恢复/退休/清理 | 保留同 boot/跨 boot absence、精确 review/plan/receipt/lease 批准及 Supervisor phase 政策；gated 事实由原 LinuxWorkerHistory、状态CAS由原Journal负责。本轮两处根句柄直接复用原 PayloadStorage.open_root，旧打开/校验/关闭程序退出。 |
| `package_product_worker_supervisor_base_v2.py` | 57 | 3 | 5 | 历史/状态/证据 | 保留 key/replay/base 三个名义类、字段和互相类型绑定；共同重放和 wire 规则均在原 _supervisor。 |
| `package_product_worker_supervisor_journal.py` | 42 | 1 | 8 | 历史/状态/证据 | 保留 POSIX/Product 准入、路径/配额及原 history-reader 绑定；原 RootedSupervisorJournal 持有根/锁/重放机制。 |
| `package_product_worker_turn_tool.py` | 73 | 2 | 3 | Session/Provider 消费者 | 保留真实 Coding symbol 查询工具内容、参数、一次绑定和结果投影；执行仍用原 Harness Tool/Session facet。 |
| `package_product_worker_windows_activation_state_journal.py` | 59 | 8 | 6 | 历史/状态/证据 | 保留 Windows/准确 Product 准入、配额、retained 名义类型及公开方法签名；原 WindowsActivationStateJournal 控制 IO/CAS。 |
| `package_product_worker_windows_backend_release.py` | 129 | 3 | 5 | 载荷/原生材料/待启动 | 保留 candidate/material 名义字段、Coding 候选 trust 准入、配额和实际 approval/review 类型绑定；Wheel/运行镜像机制用原 WindowsBackendCandidateMethods/MaterialMethods。 |
| `package_product_worker_windows_base_files.py` | 25 | 5 | 0 | 历史/状态/证据 | 保留磁盘存量对应的固定 v1 base/cutover 文件名及支持中的导出；纯布局 Profile，不是第二个存储。 |
| `package_product_worker_windows_c5_base.py` | 91 | 2 | 4 | 历史/状态/证据 | 保留 C5 base/replay 名义字段、实际 StateRecord decoder、配额及 preparation 类型/semantic 准入；重放用原 _WindowsC5BaseMethods。 |
| `package_product_worker_windows_checkpoint.py` | 466 | 3 | 6 | 历史/状态/证据 | 保留名义 checkpoint/wire、native approval/Desired/backup/six-base 的具体产品承诺及预验/重读批准。底层 staged receipt 使用既有私有 receipt owner；Linux HistoryPublication 具有不同 owner-index/segment 格式，不能拿来切换此仍不切换 authority 的 Windows 记录，也不另建平行 publisher。 |
| `package_product_worker_windows_cleanup_evidence.py` | 387 | 3 | 5 | 恢复/退休/清理 | 保留Coding authority ID、runtime incarnation/contract2、normal/enrollment/crash批准模式和跨native/Supervisor/C5/receipt的产品结清判据；实际捕获用原attempt owner，原生witness类型来自Harness，不重新探测或清理。 |
| `package_product_worker_windows_crash_c5_settlement.py` | 180 | 1 | 4 | 恢复/退休/清理 | 保留精确 contract2/authority/Job/process/native/payload/lease 全结清后的产品批准；实际 C5 转换/重放仅在原 ActivationCoordinator。关闭 fresh admission 是产品政策，Linux 同形类的产品类型和拒绝语义不同；不为一个短闭锁适配新增跨平台恢复基类。 |
| `package_product_worker_windows_crash_cleanup_review.py` | 246 | 9 | 7 | 恢复/退休/清理 | 保留精确orphan/debt/native/spec/Job absence及前后历史一致性的只读批准、名义review/错误；native phase/witness序列算法已共用原WindowsRecovery owner，spec重建和Job观察来自原Harness/Hosting。 |
| `package_product_worker_windows_crash_lease_repair.py` | 199 | 1 | 4 | 恢复/退休/清理 | 保留 Package repair 的只读验证 guard：精确已结清身份、Job absence，并将现有 Resources 提供的只读 stage 句柄保持到 Package append 后。原 cleanup owner 执行写清理且不提供这种跨 yield 只读寿命，不能以复用为由扩大权限；不增加通用 pin 回调接口。 |
| `package_product_worker_windows_crash_native_settlement.py` | 203 | 1 | 4 | 恢复/退休/清理 | 保留 orphan→GC 批准、跨 provisioning/receipt/request/profile 的精确一致性与实际 backend 选择、名义结果；原生清理完整 scope/Job/Journal/释放已迁入本轮原 attempt owner。 |
| `package_product_worker_windows_crash_recovery.py` | 154 | 1 | 1 | 恢复/退休/清理 | 保留产品决定恢复顺序、精确当前 C5 authority/host/boot/receipt 及 cleanup contract2 准入；每步重新 review，并由各原 settlement/lease/payload owner 执行，无第二物理恢复器。 |
| `package_product_worker_windows_crash_stage_retirement.py` | 278 | 2 | 6 | 恢复/退休/清理 | 保留先repair lease再批准crash stage删除、native/spec/intent一致性、冲突退休路径拒绝与receipt重试政策；共用本轮offline scope、原RetirementRecords及complete stage物理删除，无单独删除引擎。 |
| `package_product_worker_windows_crash_stage_review.py` | 287 | 2 | 5 | 恢复/退休/清理 | 保留crash review名义字段/历史wire、repaired lease record与quiescence revision准入、跨native/intent身份一致性；离线读及stage bytes捕获均复用原attempt owner。 |
| `package_product_worker_windows_crash_supervisor_settlement.py` | 154 | 1 | 4 | 恢复/退休/清理 | 保留 exact review/intent/Job absence 批准及写后复读；Windows 允许已 process_settled 重试并拒绝其他 phase，POSIX 需先证实精确 payload。共同状态CAS本已由 Worker Journal唯一实现；phase/failure选择留产品，不新增带标志的统一状态推进器。 |
| `package_product_worker_windows_desired_references.py` | 230 | 1 | 3 | 历史/状态/证据 | 保留 Coding/workspace/scope 的 Desired selection 与 receipt历史包含关系、名义review/格式和具体来源准入；不读取/改写Desired账本。投影只服务该产品证明，包装成多工厂新引擎无实际复用。 |
| `package_product_worker_windows_gc_history.py` | 239 | 3 | 6 | 历史/状态/证据 | 保留真实产品GC批准：全部尝试已退休、opt-in/receipt/C5 contract2引用闭合及禁止未知/staged状态；WindowsHistoryNames/账本/观察来自原共享owner，只读检查本身不获取GC删除权限。 |
| `package_product_worker_windows_history_bases.py` | 184 | 0 | 1 | 历史/状态/证据 | 保留六种实际 semantic base 与 checkpoint/review/preparation 承诺、先全部验证再发布及不切换 authority 的产品政策；物理读/原子stage发布由原私有 receipt IO。Linux V2发布模型不同；强行合并需新增平行格式/多组工厂，保留本组合，不重写底层发布。 |
| `package_product_worker_windows_history_cutover_preflight.py` | 76 | 0 | 1 | 历史/状态/证据 | 保留 marker 必须缺席、checkpoint/source/两次 persisted 读取必须相同的无效力 cutover review；persisted物理读取已用原 attempt owner，current checkpoint沿原产品证明。它不发布marker或授予退休；为单一这一批准流加通用恢复接口成本无实际复用。 |
| `package_product_worker_windows_history_cutover_record.py` | 148 | 2 | 5 | 历史/状态/证据 | 保留六个固定 base 键、checkpoint/source/record digest 的名义 cutover 格式与 persisted 关系；wire decode 已用原 BaseWireMethods/RecordSchema，无写入或切换权限。 |
| `package_product_worker_windows_history_join.py` | 93 | 3 | 6 | 历史/状态/证据 | 保留六种实际 base 类型、join 名义字段与 preparation 准入/组合；跨账本关系证明由原 _WindowsHistoryJoinMethods 唯一实现。 |
| `package_product_worker_windows_history_preparation.py` | 267 | 10 | 17 | 历史/状态/证据 | 保留 preparation 名义格式、semantic digest、staged retry 对当前来源的产品批准及不切换authority政策。三处重复语义捕获已合入既有 history_sources 单一程序；底层读取/私有stage发布继续用原Harness组件，无新账本/恢复器。 |
| `package_product_worker_windows_history_sources.py` | 498 | 11 | 17 | 历史/状态/证据 | 保留 Code source/snapshot/semantic 名义值、文件集合/Desired/GC/backup 产品准入与 Product authority bookend；全部有界物理来源捕获用原 WindowsHistorySourceCapture。本轮 source→recovery→Desired→source 只剩一个程序供三条真实路线使用，纯结果构造保留各自锁内/外时点。 |
| `package_product_worker_windows_installed_backend.py` | 148 | 5 | 4 | 载荷/原生材料/待启动 | 保留名义 backend/reader/错误、native_closure 产品 Profile 与审批/receipt IO/容量/错误集绑定；安装/读取/运行材料复核用原 WindowsBackendInstalledMethods。 |
| `package_product_worker_windows_launch_intent.py` | 315 | 14 | 15 | 回执/意图/批准 | 保留名义intent字段/wire、请求确由Coding铸造与receipt/lease/identity一致性批准、配额/错误Profile；持锁创建/读取/库存/原子意图发布均复用原WindowsProductWorkerIntentRecords。 |
| `package_product_worker_windows_launch_intent_base.py` | 113 | 2 | 4 | 回执/意图/批准 | 保留 intent base/replay/retained-intent 名义字段与实际历史 decoder；preparation 类型及 semantic match 后，共同行为用原 _WindowsLaunchIntentBaseMethods。 |
| `package_product_worker_windows_native_approval_journal.py` | 92 | 2 | 4 | 回执/意图/批准 | 保留 approval/decision 名义类型、历史 decoder、错误/配额/文件名 Profile 及 typed 入口；锁/追加/回放由原 WindowsNativeApprovalRecords 唯一实现。 |
| `package_product_worker_windows_native_approval_owner.py` | 94 | 2 | 3 | 回执/意图/批准 | 保留 review ID 比对后 approve、backend 丢失仍可 revoke 的产品批准；current和底层持久化均使用原owner。两个写入端的最小Product根适配若再次抽取，需引入命令/approval 类型与错误配置，不能消除底层实现，未另建writer框架。 |
| `package_product_worker_windows_opt_in_base.py` | 98 | 2 | 4 | 回执/意图/批准 | 保留 decision/replay/error Profile、名义字段与 preparation 准入；共同重放/schema 用原 _WindowsOptInBaseMethods。 |
| `package_product_worker_windows_opt_in_journal.py` | 97 | 3 | 3 | 回执/意图/批准 | 保留实际 opt-in/decision、插件 ID 产品约束、历史 decoder、配额/错误 Profile 与 typed 入口；读写/CAS/重放用原 WindowsOptInRecords。 |
| `package_product_worker_windows_opt_in_owner.py` | 126 | 2 | 2 | 回执/意图/批准 | 保留 Coding 候选 trust/平台准入、名义 owner、backend 与实际决策规划绑定和 typed API；current/allow/revoke 完整事务复用原 WindowsWorkerProductOptInAuthority。 |
| `package_product_worker_windows_orphan_review.py` | 191 | 10 | 5 | 恢复/退休/清理 | 保留 clean-exit lease 修复批准、跨 receipt/runtime/epoch/root 一致性及无法证明Job缺席的 missing_proofs；捕获已用原 attempt owner，实际修复用 Package registry 原 validation_guard。 |
| `package_product_worker_windows_package_references.py` | 333 | 2 | 5 | 历史/状态/证据 | 保留 Package/Desired/backup/repaired lease 与六base的具体产品引用闭合及名义 review；本轮重复source/semantic捕获已接同一现有source owner，Package/源文件IO未重写，不授予任何删除或切换权限。 |
| `package_product_worker_windows_partial_stage_retirement.py` | 255 | 1 | 5 | 恢复/退休/清理 | 保留无launch/native/Supervisor/marker的精确partial债务、跨其他退休路径冲突拒绝及保存review/receipt重试批准；离线scope、RetirementRecords和partial物理树删除已共享，目录程序本轮去重。 |
| `package_product_worker_windows_partial_stage_review.py` | 257 | 1 | 7 | 历史/状态/证据 | 保留partial名义字段/路径链校验/wire及未启动债务准入；离线捕获与no-follow成员检查用原attempt owner/WindowsStageInspection，review不授予删除。 |
| `package_product_worker_windows_payload.py` | 498 | 5 | 8 | 载荷/原生材料/待启动 | 保留准确 owner/lease 准入、receipt选择/跨历史批准、私有铸造请求和 retained attempt 的拒绝政策。物理stage创建/live marker验证用原Harness；额外 materialize scope 原型实测系统+38且增加单消费者装配已撤回。保留现有必要产品适配，不将 fields/参数包装当作迁移。 |
| `package_product_worker_windows_payload_inventory.py` | 86 | 2 | 5 | 载荷/原生材料/待启动 | 保留只读 Product/平台/固定根准入、名义库存记录、错误及名称/配额 Profile；库存由原 stage IO 执行，Product root 由原 attempt owner 持有，不授予启动或删除。 |
| `package_product_worker_windows_pending_host.py` | 256 | 1 | 5 | 载荷/原生材料/待启动 | 保留Windows准确owner/回执/base一致性及未结清C5禁止新Host政策、名义pending；native异步准备/清理/图发布用原共享owner，保留两平台原有准入差异。 |
| `package_product_worker_windows_persisted_bases.py` | 257 | 2 | 4 | 历史/状态/证据 | 保留六种准确 base/retired引用关系、名义 persisted DTO、cutover codec 和 type/Product准入；物理 persisted读已用原 attempt owner；单消费者外层 quiescence 包装保留，避免新的 reader 回调层。 |
| `package_product_worker_windows_provisioning.py` | 318 | 14 | 11 | 历史/状态/证据 | 保留Coding选定runtime/manifest/receipt/LPAC profile/intent的批准，以及stale selection仅允许精确清理phase的政策；持久化和原子CAS寿命用原WindowsProductWorkerProvisioningAccess，原生执行不在Code。 |
| `package_product_worker_windows_provisioning_base.py` | 106 | 2 | 4 | 历史/状态/证据 | 保留 retained-attempt/base/replay 名义字段、实际类型工厂与 preparation 准入；from_dict/重放用原 _WindowsProvisioningBaseMethods。 |
| `package_product_worker_windows_provisioning_journal.py` | 37 | 7 | 7 | 历史/状态/证据 | 保留公开 provisioning 名称及已接受私有转发；所有实际 Journal/错误/attempt 类型均直接来自原 Worker owner。 |
| `package_product_worker_windows_receipt.py` | 252 | 16 | 10 | 回执/意图/批准 | 保留 Windows exact type/候选信任类与持久化 Coding Session 一致性、实际 installed backend/opt-in owner、名义错误/API；共同 receipt authority/kill-switch/payload witness 已用原 WindowsProductReceiptAuthority。 |
| `package_product_worker_windows_receipt_base.py` | 93 | 3 | 5 | 回执/意图/批准 | 保留 receipt/opt-in/native Profile、Coding Session scope 派生及 preparation 准入；共同基线/回执重放用原 _WindowsReceiptBaseMethods。 |
| `package_product_worker_windows_receipt_journal.py` | 69 | 4 | 4 | 回执/意图/批准 | 保留 receipt 字段家族、错误标签、配额、历史 decoder 和公开 typed 方法；原 WindowsReceiptRecords 唯一持有锁/追加/读回。 |
| `package_product_worker_windows_recovery_inventory.py` | 571 | 17 | 23 | 恢复/退休/清理 | 保留恢复/GC/Backup 的实际产品投影、退休排除批准与名义类型；跨 payload/intent/native/Supervisor 的 inventory及 current/native/terminal admission 都在原 attempt/WindowsRecovery owner。余下 receipt/reference/backup 组合是产品保留政策，无法观察始终不等于absence；不新增多源 bindings/账本。 |
| `package_product_worker_windows_reserved_review.py` | 338 | 2 | 9 | 历史/状态/证据 | 保留reserved或settled-unlaunched的真实no-effect批准与名义字段/wire；共同phase/intent关系用原semantic contracts，离线及stage捕获复用原attempt owner，不把reserved等同于process settled。 |
| `package_product_worker_windows_reserved_settlement.py` | 147 | 0 | 2 | 恢复/退休/清理 | 保留仅 revision1/reserved/no witness 的无副作用结算政策、review/intent/实际 journal identity 复核及 CAS；离线写 scope 已共用本轮原 attempt owner，无第二原生执行机制。 |
| `package_product_worker_windows_stage_retirement.py` | 446 | 8 | 10 | 恢复/退休/清理 | 保留正常stopped/native-settled删除批准、名义retirement receipt/格式、跨历史/冲突路径及root-intent重试政策；本轮共用离线scope、原RetirementRecords和WindowsStageRetirement，实际树算法唯一且已去重。 |
| `package_product_worker_windows_stage_review.py` | 345 | 9 | 9 | 历史/状态/证据 | 保留正常clean-stop准入、名义review/校验/wire与实际intent/error/ACL Profile；物理stage/marker/file检查及Product root/离线scope已委托原attempt owner和WindowsStageInspection。 |
| `package_product_worker_windows_supervisor_base.py` | 95 | 2 | 4 | 历史/状态/证据 | 保留 replay/base 名义字段、实际 WorkerAttemptRecord 和 preparation 准入；重放用原 _WindowsSupervisorBaseMethods。 |
| `package_product_worker_windows_supervisor_journal.py` | 50 | 4 | 3 | 历史/状态/证据 | 保留 Windows/准确 Product 准入、固定名称和动态配额 Profile；唯一 Supervisor IO/重放为原 WindowsSupervisorJournal。 |
| `package_product_worker_windows_unlaunched_stage_retirement.py` | 315 | 1 | 5 | 恢复/退休/清理 | 保留revision2/no-effect/无Supervisor的删除批准、准确intent/native/receipt匹配、其他退休artifact冲突拒绝及历史重试入口；offline/RetirementRecords/complete stage删除均共用现有owner。 |
| `_worker_history_access.py` | 54 | 9 | 2 | 历史/状态/证据 | 保留实际 Product 到既有 history access port 的最小适配：scope/store/root、GC guard 和 borrowed root；没有第二套存储或清理算法。 |
| `_worker_preparation_inputs.py` | 348 | 3 | 4 | Session/Provider 消费者 | 保留真实Code Receipt/Session/批准/cleanup authority来源适配和平台profile构造接线；PosixSelectedWorkerSource已供普通与operator共用；无调度、图发布、IO/backend或第二资源寿命管理。 |
