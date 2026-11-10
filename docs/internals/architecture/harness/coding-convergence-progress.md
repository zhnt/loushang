# Coding 全层职责收敛：扩围推进记录

- Authority: descriptive progress；候选方案不构成已经接受的组件实现。
- Design status: partial；复用[全量职责方案](coding-reconstruction-proposal.md)与[逐文件清单](coding-responsibility-inventory.md)，每个新切片按原组件合同补足设计及评审。
- Implementation status: partial（全层总体方案）；本轮COD-PD-GOAL-001已完成本地技术接受，见A86记录。
- Owner: Coding 及 Harness、HarnessWork、AppService 等各原组件 owner；不设新的总 manager。
- 用户范围调整：2026-11-06 明确允许 C08 遇到削减瓶颈时跳到整个 Coding 层，将公共机制归原组件，使 Coding 只保留领域代码与薄适配。
- 源码核算基线：`8ad6b6098f1c24c8cfb6f4d9d290e99bc74d618d`；方法沿用本地 archmethod master `0f9bd3ff51afabeaaf76cc38dff1ceb279b7d37e`。

A83–A85已实现两处收尾机制并删除接收层同体值校验，见[收尾记录](#目录机制与接收层重复收尾a83a86)。下表为A86当前源码账目，包含全部接收成本；三视角整项代码评审已完成，实施owner接受本轮Goal的本地交付，保留下述非全绿及平台边界。A82及更早小节中的数量与待办是各检查点历史。

## 目标与账目

继续以领域与机制分离、高内聚低耦合、直接复用既有组件为原则。顺序不再强制以 C08 完成作为其他组的前提；也不能为了减 Coding 的行数复制一套公共执行、存储或装配框架。新切片同时计算 Coding 的下降、接收组件的新增及系统净量，兼容、授权、寿命和失败恢复均需证据。

| 统计范围 | 基线 | A86 当前 | 净变化 |
| --- | ---: | ---: | ---: |
| 全 Coding Python，427 文件 | 145,842 | 137,755 | −8,087 |
| 其中原 C08，31 文件 | 11,771 | 7,139 | −4,632 |
| Harness 生产源码 | 320,250 | 328,319 | +8,069 |
| Foundation 生产源码 | 3,076 | 3,171 | +95 |
| AppHost / AppService / Hosting | 37,264 | 37,161 | −103 |
| 其余未变生产源码 | 128,388 | 128,388 | 0 |
| 受影响生产源码合计 | 634,820 | 634,794 | **−26** |

本表按原基线与活树独立核算，包含未提交源码。用户2026-11-07确认8K按整个Coding层验收：当前累计减少8,087行，数量条件已达到；原C08减少4,632行仅继续分账，不再有独立8K最低线。切片的历史增量见下文及[交付记录](private-data-convergence-delivery.md)，同一文件可能参与多片，不能把各片文件集合当作互不重叠集合相加。A46的Coding减少87行中，仅`package_product_backup_types.py`的3行属于原C08，其余84行属于扩围；10行格式整理也计入物理行，但不称为算法删除。完整场景仍按[专项 Goal](coding-private-data-implementation-goal.md)验收，全系统物理总量现净减26行；数量条件达成不代替最终业务及整项代码接受。

## 目录机制与接收层重复收尾（A83–A86）

| 实际切片 | 归原组件与保留边界 | Coding / Harness / 系统物理变化 |
| --- | --- | ---: |
| A83 Windows目录观察 | 原Resources `_private_tree_windows`单份ACL/FD托管，七真实消费者含原Core接入；借用ACL、仅成功复验、两次短路枚举各保持。status保留外层ACL，使有副作用的Product.state_root仍在原时点求值 | −33 / +48 / +15 |
| A84 目录准备 | 原Resources/Packages内私有leaf承接两Code原mkdir/lstat/uid/reparse/chmod/samestat算法；Code只留路径选择、lexical base/逐级layout薄装配与各自OSError领域投影。原create_private_directory_chain及Artifact合同不同，不强套、不新增链策略接口 | −24 / +23 / −1 |
| A85 接收层值校验 | 十原PM文件同体guard直接复用原records；其原SHA先nonempty的错误合同保留，七直接digest同体另用同owner的窄函数。enablement其余不同错误guard不合并；没有新schema/manager/模块 | 0 / −108 / −108 |

三片合计Coding−57、Harness−37、系统−94，接收成本及格式全计，故此前系统+68现为−26；不是把迁移行数算成算法删除。A83三独立代码视角已无阻断并有界接受；63原scope观察相同、七完整文件120 passed、六实际源silent-import窄类型通过。A84两原leaf的38顺序/错误观察相同、三实际源窄类型通过；A85原8720记录观察/29公开类型与构造顺序相同、十实际源窄类型通过。私有函数反射位置与旧私有hot-patch不承诺为公共兼容合同。operations中一个原无Load消费者的私有nonempty helper直接退役，其余22处导入沿原调用名复用；不承诺全部旧私有名或函数pickle保持。

A84/A85实际代码及整项职责/复用、运行/失败、数据/兼容三个独立视角最终均无剩余具体R3阻断；实施owner在原授权内完成本地技术接受。fresh最终46文件组合实际421 passed/1 failed（777.07s），在Continuity节点停止，不能称46文件全绿。A84较早五文件组合在A85修改前启动，不能冒称最终源码组合证明；最终以源码稳定后新进程的结果为准。最终source/test守卫300项、四生产根全语言计数及实际frame在产品树外`final-acceptance-a86/`；三片原源码/预期及各自证据也在产品树外。Windows仍为原candidate/未原生证明范围，无新平台/CI/模型验证要求。COD-PD-GOAL-001完成本地实施与技术接受；全Coding总体收敛仍partial，未进行远程交付。

较早业务进程实际为76 passed/1 failed（435.62s），失败在Continuity恢复准备。单节点当前17741与只读装入两冻结原leaf的62107均失败，完整nested error逐项相同：原Continuity暂存检查拒绝非sticky可写祖先，本机工作区0775。该对照仅替换两原leaf及其原stat绑定，其他源码当前；不是完整Git基线通过或全部Continuity已验证。第一次对照漏旧stat导入的诊断搭建失败另存，不作产品证据。未放宽产品检查、测试断言或祖先权限，未绕过managed pytest wrapper/固定磁盘runtime；不将此结果称全绿。

最终源码上另用fresh进程补六个相关兼容完整文件，154 passed（13.17s）；这些文件也在46文件命令中，不相加为独立覆盖数量。长组合的非零结果保留，不把该154项扩称为整个组合通过。A85另将十份冻结before原样交同仓Ruff格式化作独立成本对照：物理−108由同格式结构−96与格式−12构成，不把108全称算法减少。

最终接受记录SHA `e360d8d432cf6e095a1281a6d346d1e9c674689415f5d34890a32bab8411e0a1`，绑定source frame `dad4bed8a6c350a3ebc289cf9eaa1d45855da23d71a7f2b8cb3d5f93f56317b2`。三独立最终报告分别核对PD-A/B/C/D、300守卫、原31文件callee闭环、数量及真实失败边界。A82两个具体余项由A83/A84关闭，旧POSIX R02不再作为新增引擎任务。原报告与终态补核各自保留，不回写历史pending。只接受本Goal当前范围，不把Coding净减8,087或系统净减26夸成整个Coding已成为薄适配，也没有性能/内存提速主张。

## 数量范围确认与收尾审计（A82）

用户于2026-11-07明确选择“按整个 Coding 层验收 8,000 行”。[实施Goal](coding-private-data-implementation-goal.md)已据此修订当前数量条件；旧检查点的C08独立缺口/待澄清是历史，不回写旧评审。当前A81源码数量不变：全Coding−8,030，原C08−4,599，所有生产源码仍+68。仅数量子条件达成，R3全31文件的职责归一/旧体退出、原合同、系统整体净减和整项三视角代码验收继续有效。

三位独立reviewer已按整项R3职责、运行失败、数据兼容核对31叶子及实际callee，不能仅凭旧partial标签断言未完成，也不能把119项本地回归扩称为全Goal验收。源检查点仍为A81，A82不产生新代码减量；原始审计、范围补充和重判留产品树外 `final-scope-a82/`，旧报告不回写。

| 收尾项 | 实际处置 |
| --- | --- |
| Windows目录观察/ACL/FD寿命 | 原Code root代际查询、restore no-stage、archive-free recovery与status仍有机械scope，原Core也有相同消费者；下一完整切片在原Resources内收敛，保留借用/自建ACL、正常退出复验及listdir短路差异 |
| 相邻目录prepare | Archive retain/restore回调仍执行Code `_plugin_lifecycle._prepare_private_tree/_prepare_private_directory` 的链/mkdir/chmod/uid/reparse/samestat算法；须归原Resources，不能拿不同合同的create_private_directory_chain直接替换 |
| 全系统净减少 | 当前+68尚未达；后续全部接收成本计入，再删至少69行只是当前无新成本时的下界。接收层纯值重复候选还未实测采纳，不预支收益 |

PD-A已接管capture/copy/verify/publish，但相邻prepare使整个callee closure尚未结束；PD-B的原OwnerPort集成/Journal/native职责可接受；PD-C/D仍有上述两类具体收尾。运行初审提出的POSIX删除调用编排，经R3§3和原OwnerPort durable-replay合同复核，已撤销完成阻断：Code仅调用原Journal和物理后端，没有第二scan/phase/append/rename引擎，不能为表面一致再加一个callback执行器。根代际字段/前驱/ID/布局、DTO、Desired/确认政策及原reader/writer/status分流可保留，不再整块列作必须迁出。

原Windows保持candidate及未原生证明范围；不增加平台开放/CI/付费模型要求。下一步先关闭目录观察寿命整簇，再做精确目录prepare，实际净减及最后三视角验收均保持原要求。

## 首个扩围切片

选择 Base/LSP/Arch 的 Tool 注册桥接作为首个跨 C08 切片：两套 LSP/Arch generation 的注册与生命周期、三份 Port/Slot 有直接源码重复证据；原 RegistrationScope、SessionCapabilityOwnerGenerationBinding 与 Tool controller 已具备所需执行权威。具体方案见 [H-COD-KD-002 R2](key-designs/session-tool-pack-binding-convergence.md)，R2 已由用户明确要求实施，[三视角独立设计评审](key-designs/session-tool-pack-binding-convergence-review.md)已完成，R2 的原 owner 身份映射缺口已关闭，无剩余内部设计阻断，用户已于 2026-11-06 接受 R2 实施。该切片现已完成本地代码实现、相关验证和三视角代码复核；Coding 的工具定义/Consumer/精确准入与 Base 特殊清理保持原归属。实际净减 132 行，未达到争取 200 行的预算，不能按预计行数记账。

## 其他候选与已共享部分

| 候选 | 原组件复用路径 | 当前结论与限制 |
| --- | --- | --- |
| C09 接受凭据与兼容源读取 | 原 Journal / RootedFileIO / RootedFile，以及原 accepted migration owner | A23 已关闭三个 POSIX writer 的共同发布与五处原格式化；只读 reader、local/source 的不同锁及文件准入仍保留原实现，不能把默认 Rooted 权限当私有权限或把剩余候选当已实现 |
| C04 Continuity 临时载荷 | 原 Transcript frozen import、SessionLifecycleRuntime 和 PreparedSessionLifecycleOperation | 次选：研究以已有 frozen/bytes 输入直接导入，删除纯转接用的临时文件寿命；仍需保留 ZIP/Blob 限额、cwd、回滚与取消后的 prepared cleanup，不能简单改为普通 to_thread |
| C01/C15/C17 装配与恢复 | 原 ProductPluginComposition、AgentProductConstructionRuntime、RuntimePlan 和 Session 生命周期 | 首选 Tool 注册桥接已单列设计；selection-plan 编排列次级候选。D1/D2 与 CH01 已交付部分从待办排除，不再建 composer 或取消等待器 |
| C12 Goal 适配 | 原 GoalRecordStore、Work codecs、Journal 及可选 HarnessWork integration | 当前物理 backend 已复用这些原语，无等价第二后端；归属整理不能算算法消除或系统净减，不作为首个减量切片 |
| C10 受控外部 Wheel 文件操作 | 原 Resources local Source、文件描述符寿命和 Journal 完整写入 | A26 收敛三种已准入源的文件操作；epoch、目录准入、绑定记录和依赖包元数据判据仍留原 Coding owner |

上表是本轮选切片的候选，不能据此宣称已删除数百行。三位独立 reviewer 已从职责/复用、运行/失败、数据/兼容视角完成扩围机会审计；完整报告与源码基线置于产品树外。先确定真实复用接口、仍需保留的领域政策、旧体删除池和全部替代成本，再实施相应完整场景。

## 保留与禁止

Coding 保留编码能力、内置内容、方法选择、仓库与测试/评审政策、产品身份/准入，以及必要的协议/呈现投影。通用机制分别归 Session、Resources、Journal、Worker、Continuity、HarnessWork 或 AppService 的原职责 owner；Harness 核心不反向依赖产品、Work 或托管协议。

旧存量、公开 API、明确失败恢复路径与支持范围继续有效。不能因为文件名包含 legacy/canary 就删入口或恢复依据；不能拿另一套更严格或更弱的准入掩盖不等价；不能把重复测试数、文件搬迁量、格式压缩或未执行的收益预算当作完成证据。


## Tool-pack R2 本地交付（A22）

[共享桥接](../../../../src/loushang/harness/session/tool_owner_binding.py) 位于原 Harness Session 内部。它直接组合原 RegistrationScope、SessionCapabilityOwnerGenerationBinding 与 Tool controller，不新增 registry、manager、generation 日志或状态机。LSP/Arch 的重复注册与 lifecycle 操作体已删除；Base/LSP/Arch 三份 Slot 同用一个实现，原公开类名和构造形状由薄类型声明保持。

| 生产源码 | 原行数 | A22 行数 | 净变化 |
| --- | ---: | ---: | ---: |
| Coding LSP Tool owner | 292 | 153 | −139 |
| Coding Arch Tool owner | 287 | 150 | −137 |
| Coding Base owner（仅替换 Port/Slot） | 554 | 522 | −32 |
| Harness Session 共享桥接 | 0 | 176 | +176 |
| 合计 | 1,133 | 1,001 | **−132** |

Coding 实际减少 308 行；接收组件全部新增 176 行计入成本，没有把搬迁作为系统删除。LSP/Arch 的 admission、Consumer 和工具定义方法，以及 Base 除 Port/Slot 外的正文，经 AST 对照保持原样；Base operation_set 失效和 Command 路径未改。

实现前从未修改的原三个文件固定了 7 组 identity/source/receipt/family/retry 结果；后续另 7 组失败/Slot 和 13 组时点结果使用已逐字核对 Git 基线的原存档模块生成。生成器在独立进程安装原 canonical module，预期、原源码、loader、执行记录与 hash 均保存在产品树外；测试只读取固定预期，不生成新预期。数据样本与 inert port 不代表真实插件或工具执行授权。

A21 三视角评审发现 bind 提前固定了可变字段：原逻辑在完整定义投影后读取 admission/scope，逐工具读取 mode，并在 receipt 时重读 contribution id。A22 用三个只读属性的窄输入端口恢复这些时点，Binding 元信息仍按原 bind 时点固定；没有改成冻结 Coding owner 或新增拒绝合同。原 13 组样本在修复前全部失败（2.93s），修复后通过。O-A21-01、RT-A21-01 与 fixture 来源记录缺口均经独立增量复核关闭，三视角没有剩余代码阻断。

验证：

- 最终原 LSP opt-in、Arch provider、Base owner 组合：**41 passed（80.40s）**。
- 27 组固定合同与原 Session generation 组合：**39 passed（2.09s）**。两组覆盖范围各自记录，不累计为新能力数量。
- 4 个变化源码 mypy、所有冻结 Python Ruff、87 个 source/test hash 与 diff 检查通过；文档另按原静态检查验证。
- 较广的实际 Session 装配选择为 2 passed、2 failed。只读加载原三套 Tool owner、保持其他活树不变的对照，也重现同两失败：`transcript_writer:unsafe` 与工作区 `review` skill 未发现。此对照只说明它们在原 owner 路径也存在，不能冒称完整原始基线或全量回归通过；后续需单独处理，未改测试断言掩盖。

本切片未增加 CI gate、远程发布、平台开放或模型调用。完整 Coding/私有数据 Goal 仍未完成：C08 原 8,000 行削减条件仍未达到，截至 A22 的全任务生产源码净增 1,141 行。R2 本地交付不能替代整个 Goal 的数量、完整业务场景及最终验收。


## C09 不可覆盖回执发布收敛（A23）

沿用本记录的全层扩围与既有 Journal/RootedFileIO 归属，本片只消除 disabled-only、builtin-only、removed-local 三个接受回执 writer 的同形物理外壳。它不是新的生命周期架构，不增加 Manager、记录格式、确认权威、锁或平台支持，也不替代用户对重要架构工作件的评审。

- 三个 Coding writer 保留原函数签名、codec、错误类与目录标签，委托原 Journal 内部的 `publish_private_bytes`。共同实现打开并固定私有父目录，复用原 `RootedFileIO.bind` 与 `atomic_write(exclusive=True)`，执行原 cleanup、后验和 close。原 native class/ledger/发布算法 AST 保持一致，没有用最终文件名的 create-new 替代完整无覆盖发布。
- 两种后验明确分开：disabled/builtin 先检查 FD identity，再查路径及私有权限；后者失败仍报 unsafe。removed 先查路径，再组合检查，失败报 changed。父目录仍拒绝全部 group/other 权限，不能以默认 RootedFileIO 的 non-writable 准入替代。
- Journal 的 `encode_jsonl_record` 与原 Journal 共用纯 formatter；五处 Code 使用原 codec、sorted Unicode、默认空格、单 LF。原 Journal 的 Mapping/`require_json_mapping` 验证留在原位置，Code 不新增该验证；local 在原锁内编码，Windows builtin 仍调用原 Windows receipt owner。
- 三类接受决策、desired/epoch/锁、只读缺失处理与文件准入都留在原 owner。四文件其余非 import AST、local 单编码表达式以外的整函数 AST 均与本片冻结前一致。

| 本片生产源码 | 原行数 | A23 | 净变化 |
| --- | ---: | ---: | ---: |
| Coding 四个 acceptance 模块 | 1,483 | 1,369 | −114 |
| 原 Journal 三个模块（计全部接收成本） | 2,449 | 2,532 | +83 |
| 合计 | 3,932 | 3,901 | **−31** |

三视角实施前核查已识别上述权限、格式及后验顺序差异，代码评审独立核对被冻结的 95 个 source/test/fixture，职责/复用、运行/失败、数据/兼容三个视角均无新增阻断。实际收益小于候选簇的审计预算：本片没有迁移 reader、catalog 或 source-consumption，不宣称达成整簇净减 200，也不把接收组件新增排除。

验证：

- 27 组原始观测在六份源码未修改时生成；18 组编码与双重失败优先级使用冻结的原四个 Code 模块按 canonical 名称加载后生成，同时证明当前 native 三类 AST 与原版一致。保留原源码、loader、probe、输出、hash 和执行来源，当前测试不生成 expected。
- 初轮为 101 passed、49 skipped、3 failed：三项均为 EEXIST 文本中的随机 staging token。测试仅同时归一化新旧结果的 24 位十六进制 token；原 raw fixture 不改，错误类型、其他文案、字节、清理与 trace 断言保留。
- 最终实际执行 **155 passed、49 skipped（85.56s）**，包含固定原行为、Windows builtin 纯编码、原 disabled/local adoption、Windows pre-B 的适用场景及 Journal/Rooted IO/publication。原 49 个平台跳过不算 native Windows 证据。
- 六个变化源码 mypy 与本片 Python Ruff 通过。没有运行模型、联网实验或新增 CI gate。

截至 A23，两项较广 Session 失败尚未完成私有输入路径对照，不能用本片回归覆盖它们；A25 的后续环境诊断见下节。截至 A23，完整 Goal 保持 partial：C08 减少 2,136 行，全 Coding 减少 2,780 行；全任务生产源码 634,820→635,930，净增 1,110 行，没有满足原 8,000 行和系统净减少的目标。


## C07 Windows Worker 原生日志 IO 收敛（A25）

在用户扩围授权内，实施者依据三视角独立预审，在原 Resources 原生操作内部采用一份[WindowsJournalFileIO](../../../../src/loushang/harness/resources/packages/_windows_journal_file.py)。这是既有组件的内部文件适配：原 `journal_file_lock_at(create=False)` 继续负责锁，原 Worker/Code 负责业务事实、授权和提交判定，系统环境与部署边界沿用整体方案。此项技术接受不冒称用户另行接受了一份新架构工作件。

原五文件六类方法的 AST 覆盖池为 773 行；计入保留的业务前验、全部配置和接收成本后，实际结果如下：

| Coding 模块 | 原行数 | A25 | 净变化 |
| --- | ---: | ---: | ---: |
| Windows native approval journal | 416 | 268 | −148 |
| Windows opt-in journal | 427 | 291 | −136 |
| Windows receipt journal | 358 | 227 | −131 |
| Windows supervisor journal | 403 | 288 | −115 |
| Windows activation-state journal | 452 | 358 | −94 |
| Coding 合计 | 2,056 | 1,432 | **−624** |
| Resources 共享实现 | 0 | 202 | +202 |
| 系统合计 | 2,056 | 1,634 | **−422** |

共享体复用原 Windows open/ACL/stream/flush 原语和原 `write_all`，仅将 BinaryIO 的 None 结果适配为原 no-progress 错误。它持有文件名、上限和错误工厂，不持有句柄或运行状态。原锁文件 0→1、借用 handle 不关闭、单次 `max+1` 读取、expected=None 与空字节的区别、短写和原 flush 顺序均保留；创建或追加失败仍保留原残留，不自动回滚。各日志原 4/32/32/16/32 MiB 上限分别保留。

Coding 保留原 prepare-lock 的 missing/history/C5 no-state 前验、Root/GC 关系、业务 codec/history/replay、Supervisor 特殊 marker ValueError，以及 C5 的成功 raw 拼接和 256 字节 head 单次写入。其余四日志不新增历史拼接。五类其余方法在逆转 IO callee 后 AST 与原版全等；模块常量、public 构造签名和导出保持原样。上述旧物理操作体已删除，没有新旧双路径。

评审与验证：

- 五源码逐字等于 Git 基线时冻结 180 组旧行为；其后从归档五模块按 canonical 名称加载，记录 10 组 fdopen 接管前失败的原泄漏。原源码、probe、loader、输出、hash 均保留；固定旧 probe 已在稳定状态下只读重放，结果逐项相等，没有重写 expected。
- A24 初稿在 fdopen 失败时盲目 close。运行评审 RT-A24-01 指出 wrapper 可能已经自行关闭 FD；两个真实 FD 反例在 A24 上均失败：覆盖原错误或误关复用的 FD。原广组合 372 passed、50 skipped 不能排除此问题，A24 源码和拒绝结论保留。
- A25 使用 `closefd=False`，wrapper 借用原 FD，Resources 在 finally 中负责唯一 native close。旧 wrapper 隐式关闭改为显式 owner close；测试只明确增加该关闭事件，其余旧字节、错误、marker、文件和事件断言保留。原 fdopen 接管前泄漏及评审指出的两种晚失败均由[实际 FD 回归](../../../../tests/harness/resources/packages/probe_windows_journal_stream_ownership.py)验证。
- 最终 A25 **205 passed（5.92s）**，包含 180 组原协议、10 组旧泄漏、2 组真实构造失败反例和原 Worker 核心检查；六个源文件 mypy、冻结 Python Ruff、105 个 source/test/fixture hash 通过。A24 原较广选择的导入边界没有新跨组件依赖，A25 只改变 helper 所有权与相应回归。
- 职责/复用、运行/失败、数据/兼容三视角增量复核已关闭 RT-A24-01，无新增代码阻断。没有 native Windows 运行证据，50 个原平台跳过也不算该证据；未增加平台、模型调用或 CI gate。

A24 净减 426 行，A25 修复增加的 4 行全部计入，最终净减 422 行。完整 Goal 仍 partial：全 Coding 累计 −3,404；原 C08 仍 −2,136；全任务生产源码 634,820→635,508，仍净增 688 行，原 8,000 行与系统净减少目标尚未达成。

## Continuity bytes 路线与原验证环境的核查

本轮也检查了以原 Transcript import 消除 Continuity 临时文件转接的方案，尚未实施。三视角发现预算须补齐的合同：owned/non-owned 与 persist=False 原接受范围不同；JSONL 可读取原 temporary_root 相邻只读 Blob 库，不能丢失其叶链接和祖先控制；prepare 成功后取消且 abort 失败，需要实际强引用及关闭/重试入口，原关联表不是该 owner。公共平台 probe 还有真实 bootstrap 消费者。上述条件未闭合，不把 192 行候选声明体计为已删除或现成可复用能力。

未改动的原 Continuity/owned import 选择在规定磁盘 runtime 下出现 15 failed、40 passed、1 skipped；Continuation 的路径前验实际拒绝了 0775 的工作区祖先。外置只读测试 placement 插件保留原 wrapper/RunLease/runtime 和全部断言，仅将所选输入放到私有磁盘 home 临时目录后，原选择加其他 composition 检查为 90 passed、1 skipped、1 deselected（119.54s）；剩余被单列的 review skill 检查为 1 passed（72.17s）。原 CLI builder 及 review skill 失败因此均获得了私有输入路径下的成功对照；默认测试路径的祖先问题没有被产品补丁“修好”。测试输入目录已自动清理，无全局 chmod、Product 权限放宽或普通运行目录变更。

## C10 受控外部 Wheel 文件操作（A26）

在全 Coding 扩围授权内，三视角预审确认：data、dependency、Worker 三个外部源目录各自负责原准入与授权，但包含同形的受控文件发布、读取和七字段身份比较。原 `RootedFileIO.atomic_write` 的随机 staging、EEXIST 传播、清理账本与后验不同；原 Local Source proof 的授权及分块读取也不同，不能直接替换。采用原 Resources Local Source 内部的[窄文件操作](../../../../src/loushang/harness/resources/packages/plugin_lifecycle/_controlled_source_io.py)，复用 `open_regular_no_follow`、Journal `write_all` 与现有 `closing_descriptor`，没有新增 manager、registry、记录格式、锁或执行引擎。

- 发布借用已准入目录 FD，保留原固定 staging 名称、0600、短写循环、文件 fsync/close，以及 link 的 EEXIST 抑制。写入阶段失败保留 staging；只有进入原 link 阶段才 finally 清 staging 并同步目录。原调用者关闭目录后才核验正式目标，不能提前在仍有两条硬链接时检查 nlink。
- 读取保留原单次 `read(max+1)`、before/after 七字段身份和摘要判定，不增加路径可见性或长度等于 metadata 的后验。三个原 `_file_identity` 使用同一纯函数别名；原 capture 与 Windows 方法其余 AST 不变。正式绑定记录为 frozen/slots 值，helper 接受其已校验摘要，不扩展私有方法为任意可变对象接口。
- 读取器复用已有 FD 关闭范围并使用 `fdopen(closefd=False)`，避免 Python wrapper 构造失败泄漏已取得的 FD。独立加载三份原源码的真实 FD 探针证实，原三个 early 失败均泄漏；新早失败、晚失败及另一个 FD 仍打开的场景单列回归。该修复是明确行为差分，不称所有故障路径逐事件相同。
- Coding 保留原根目录与 epoch、绑定/记录唯一性、只读政策、原预算，以及 dependency 子目录前验和 `_verify_wheel_body`。原旧文件操作体已删除；其余非 import AST 与归档原版相等。

| 本片生产源码 | 原行数 | A26 | 净变化 |
| --- | ---: | ---: | ---: |
| Coding external data | 462 | 421 | −41 |
| Coding external dependency | 581 | 537 | −44 |
| Coding external Worker | 868 | 827 | −41 |
| Resources 内部操作 | 0 | 98 | +98 |
| 合计 | 1,911 | 1,883 | **−28** |

实际净减 28 行，低于预审的 41–90 行估计；全部接收成本均已入账。另一个 Journal 构造/读取 helper 候选在实测后总源码增加 16 行，已经完整撤回，未计入交付或删除量；完整泛型过期动作也尚未证明净收益，没有实施。

最终原目录业务与固定合同组合 **89 passed（481.03s）**，包含原 data/dependency/Worker 场景、69 组固定观测及 3 个真实 FD 故障回归；另一个选择为 **13 passed、2 skipped（1.66s）**，包括 6 个实际 EEXIST 后核验及原 Local Source。两组分别记录，不用重复测试数量表示新增能力。4 个变化源码 mypy、冻结 Python Ruff、112 个 live hash、9 项文档检查和 diff 检查通过。职责/复用、运行/失败、数据/兼容三视角代码评审均无剩余阻断；实施 owner 在既有授权内接受这一有界技术切片，不替代用户的重要架构工作件评审。112 个源码/测试/fixture 的冻结清单保存在产品树外，SHA256 `26d65eaf7141e0b6bebd8f29ffa45c8387e2a70a396799bce35f7df7cf26ea1b`。69 组原观测在改动前固定，原 raw fixture 不改；归档三原模块按 canonical 名称独立重放全部相等，记录加载路径、源码和探针 hash、命令及 exit code。对照仅在两边剔除因磁盘 RunLease 路径深度变化而增加的祖先 open/close 事件，保留文件字节、模式、错误、目标操作序列和 FD 存活检查。

完整 Goal 仍 partial：全 Coding 累计减少 3,530 行，原 C08 仍只减少 2,136 行；全产品生产源码 634,820→635,480，仍净增 660 行。没有完成原 8,000 行、系统净减少或全部私有数据场景验收；本片不增加平台支持、模型试验、CI gate 或远程发布。


## 立即拒绝 JSON 重复键的唯一算法（A27）

原 27 个正常包内顶层 hook 的循环共 195 行，Coding 有 9 处，Harness 有 18 处。它们规范 AST 相同，只有局部变量名和原错误文案不同；Journal codec 中的相同循环还持有动态文案。新增的[Foundation 内部 hook 构造](../../../../src/loushang/foundation/json.py)提取这一个原算法，27 个原名字保留为 callable 薄绑定，Journal 使用同一闭包并在重复键处才求值原消息。它不解释 schema、不新增 parser/manager/工作流，Foundation 公开 `__all__` 保持原样。

原 `json.loads`、UTF-8、`parse_constant`、canonical bytes、外层异常和权限/账本路径均不变：不把 plain JSON 的 NaN/Infinity 改成统一拒绝，也不把 Journal 的延迟重复键观察变为立即失败。独立 `Python -I -S` 验证器、类/嵌套 hook、不同异常类及其它域未纳入。私有 hook 的函数反射名字与 pickle 能力会变化；源码/测试未发现对此的真实消费者，模块原属性名和正常调用/monkeypatch 入口仍保留。

| 本片生产源码 | 净变化 |
| --- | ---: |
| Coding 9 个调用方 | −26 |
| Harness 18 个调用方及 Journal codec | −58 |
| Foundation 完整接收成本 | +20 |
| 合计 | **−64** |

上述 26 行有 6 行来自原 C08、3 行来自已列 C07，余下 17 行单列；不把本片重复累计到其它切片。实际净减小于较大候选的预算，不能把 195 行旧循环池当作实减。

验证与评审：

- 27 个旧真实模块在源码修改前加载，270 组原观察已冻结；当前真实模块/hook 加原 stdlib parser 的结果逐项相等，未重写 expected。它们不是全部外层业务端到端证明；27 个调用者其余非 import AST 相同，补足原 parse/catch/schema 次序核查。
- Foundation、Journal、既有私有数据格式/错误、backup 和 source/legacy evidence 选择 **95 passed（28.54s）**；新增一个 Label 格式化回归，确认有效 JSON 不求值错误文本，重复时保留原 cause 与两次格式化顺序。
- 另一个 Harness capture/corruption 选择为 **15 passed、1 failed、179 deselected（3.39s）**。失败在 StoreAdmission 创建之前拒绝 0775 的工作区祖先，尚未到 JSON hook；仅恢复原 hook 的对照也失败（0.41s），相同当前实现仅将测试输入放到自动清理的私有磁盘 home 后 **1 passed（0.26s）**。原 runtime、RunLease、断言和产品权限不改；不把默认路径选择冒称全通过。
- 原有 import 边界选择 **165 passed（69.62s）**；冻结 Python Ruff、137 个 live hash、9 项文档不变量/变更链接及 diff 检查通过。
- 29 源码 mypy 含 `package_source_snapshot` 的 3 条既有 `object.stat/open` 诊断。全部 29 源码用归档 shadow-file 对照得到相同诊断（忽略位置），其余 28 源码通过；未增忽略、cast 或权限绕过来报绿。
- 冻结 137 个 source/test/fixture，清单 SHA256 `6f9d6feb6ae033e33c644488c9ea4276e068adaccddb7597f3a08890389feb20`；职责/复用、运行/失败、数据/兼容独立代码评审均无阻断。此有界切片由实施 owner 在已有授权内接受，不代替重要架构工作件用户评审或整个 Goal 验收。

在本片修改前，A26 冻结源码的原私有数据整链路选择另有 **85 passed（307.21s）**，覆盖原备份、确认删除、恢复、过期、root lineage 与 CLI/SDK；它是明确的前置证据，不当作 A27 全量/native Windows 验收。三类较大候选的专项复核也已完成：两次 tombstone 验证跨 durable checkpoint，不能删除或强套 deletion；expiry record/numbered Journal 新层尚未证明净收益；C01 cleanup 统一持有需要保持分阶段 retirement 与兼容构造，尚未接受/实施，不计候选删除池。

全产品源码 634,820→635,416，仍净增 596 行；全 Coding 已减少 3,556 行，原 C08 减少 2,142 行。原 8,000 行和系统净减少均未达到，PD-A/B/C/D 及整体 Goal 继续 partial；没有新 gate、付费模型、平台开放或远程发布。


## Windows 归档动作归原备份组件（A28）

Windows 的 retain/read/verify 协调回到原 Plugin Management 备份组件内部的 `WindowsPrivateArchiveIO`。这是原组件的显式平台实现，复用已有 `PrivateArchiveCodec`、`PrivateWindowsTreeIO`、树捕获、bounded prefix、句柄 scope 与原生 ACL/rename/flush；不把两平台不同的发布和失败顺序硬套成一个算法，不新增 manager、账本、事务引擎或后台工作。

Coding 保留原 Product/Installation/Desired/offline 准入、root lineage、source/receipt/hash、Windows 编解码、布局和限额声明；恢复、过期与查询仍消费原私有 read/verify 入口及 native/logical 薄绑定。只有字节读取归 Resources；它不识别 Coding 记录。源重捕获的短路、现存归档的快路径、ACL 建立时点和存活范围、stage 残留、close 后路径核对及其异常优先级均保持原语义。Windows 的 duplicate/canonical/identity 与 POSIX 不同，未借收敛更改格式。

| 本片生产源码 | 实际净变化 |
| --- | ---: |
| Coding Windows backup，635→431 | −204 |
| 原备份组件内 Windows 动作，完整新增 | +276 |
| 原 Windows tree IO 的 manifest bytes 读取 | +46 |
| 原 tree observation 的逻辑内容投影 | +15 |
| 系统合计 | **+133** |

本片是职责归位，**不是系统净删成果**；所有 codec/端口/import/兼容入口已纳入计数，不能把旧替换池或迁移行数作为重复删除量。`snapshot`、retained receipts、过期与恢复的其余厚流程尚未退出，PD-A 及整体 Goal 继续 partial。全产品 634,820→635,549，净增 729；原 C08 减少 2,346，距原 8,000 行最低线仍差 5,654 行。

本片固定证据与验证：

- 冻结清单覆盖 143 个 source/test/fixture，10 个增量路径，SHA256 `417ba04ff5ad0a35364de678cbe6bdf12a85b34bb2a5b0be9c17a43b859a346d`。旧观察来自归档前真实 Coding 实现；23 组 retain、14 组 public verify 的原边界观察和 5 组真实 POSIX 文件句柄结果均逐项相等，未按新实现重写 expected。
- 定向回归 **114 passed、49 skipped（22.55s）**，包含上述 42 组观察及原备份、archive/native IO 相关选择。49 项按原平台规则跳过，portable native stub 与 POSIX FD 都不能证明原生 Windows DACL、ADS、共享标志、无覆盖发布或断电耐久。
- Windows codec 的 decode 尾段、encode 表达式、逻辑成员投影、public 准入/ACL scope、源变化短路与其它原 Coding 方法 AST 均等同；Resources 原 collector/copy/write/delete 方法 AST 不变。原 Windows 场景仅将两个故障注入点改到真实新 owner，原断言保持。
- 4 个增量生产模块的 `mypy --follow-imports=silent` 通过。普通 follow-imports 调用在依赖中报出 237 条诊断、涉及 8 文件；本轮未做其完整原基线对照，不宣称宽范围类型检查通过。没有通过 ignore/cast 或删断言规避诊断。

下游恢复、过期、root lineage、CLI、confirmation 与既有 import 边界选择另有 **182 passed（136.84s）**；它与首组分别记录，不把 Linux 上无 skip 推导为原生 Windows 通过。职责/复用、运行/失败、数据/兼容三位独立代码评审均无本增量阻断，143 个 live hash、121 个 Python 文件 Ruff、9 项文档不变量及变更链接/diff 检查通过。实施 owner 在已有 R3 授权内接受这一有界职责切片；不替代重要架构工作件用户评审、原生 Windows 或整个 Goal 验收。没有新平台开放、PR gate、付费模型试验或远程发布。


## Task 等待原算法单份实现（A29）

[H-COD-KD-004 R2](key-designs/owned-task-join-convergence.md)把十五处原 Task 等待副本归为三组，每组只留一份真实原算法。Hosting 的首 caller 取消优先、CH-01 的底层失败优先／counter 清零后 return、Continuity 的 counter 清零后 break 是不同合同；150 个原实际 Task 观察证实不能合为一种取消语义。共同 stdlib 原语在既有 Foundation 内部，Harness 原 API 薄绑定；Task 创建、取消请求、Session／Host／cleanup-debt 与 retry owner、原调用点都不迁移。

| 本片实际生产源码 | 净变化 |
| --- | ---: |
| Coding hosted Continuity | −12 |
| Harness 六个原模块 | −81 |
| AppHost | −39 |
| AppService | −10 |
| Hosting | −54 |
| Foundation 完整新模块 | +75 |
| 系统 | **−121** |

外置完整 R2 原型是净减 112 行；实际包路径整理九处 imports／空行后另减九行，不能把排版变化称为新增算法删除。257 行原定义池不等于净量，所有新模块、imports 和十五个兼容绑定都计入。Coding 的十二行属于扩围，**不增加原 C08 削减量**。

验证与[三视角代码评审](key-designs/owned-task-join-convergence-review.md)：

- 原十四模块 SHA 守卫后冻结 150 项实际 Task 结果；原 pytest 150 passed（3.76s）。外置 R2 按真实 `__file__` 映射独立重放全等，没有按新实现生成或重写 expected。
- 代码应用后首组 195 passed（9.60s），原启停关闭调用链另 337 passed（115.96s）。后组启动早于最终 import 排序，仅作相同 body 的调用链证据；不把重叠组合简单相加。
- **最终 A29 冻结源码**的固定 Task、原 CH-01、Extension 清理、Continuity 真实旧 IO、AppService 取消交付与原 import 边界为 **360 passed（97.98s）**。15 个增量生产模块的 `mypy --follow-imports=silent`、138 个冻结 Python 文件 Ruff、161 个 live hash 通过。
- 三位独立代码 reviewer 核同一清单，职责／复用、运行／失败、数据／兼容均无阻断；报告写作时的最后回归待回收状态保留，终态由实施 owner 补记。A29 清单 SHA256 `3dbf01dd6313deafa3a957ac9f3aae7120e985468716f93a01b0b84ec4525a53`。有界技术接受不代替整体 Goal 或原生平台验收。

全产品 634,820→635,428，仍净增 **608**；全 Coding 145,842→142,070（−3,772）；原 C08 11,771→9,425（−2,346）。C08 最低八千行线仍差 5,654，完整 PD-A/B/C/D 与系统净负仍未达到，Goal 保持 active。没有新增 gate、平台开放、付费模型或远程发布。

## Continuity bytes 候选的旧行为审查（KD-003）

[R2 草案](key-designs/continuity-bytes-import-convergence.md)尚未接受实施。[三视角审查](key-designs/continuity-bytes-import-convergence-review.md)指出：旧 JSONL 会读取 temporary Session-dir 相邻的真实 Blob，缺失 leaf 也可能合法，非 owned／transient 成功入口不能以新 owned-only 接口拒绝；direct bridge 也有原平台门槛。原 factory／pending store／Prepared 的持有阶段各异，不能用其名字补造成功交付后的兜底。

产品未改时补充真实桥接与 Transcript 叶子组合 8 passed（1.89s），证实上述合法输入及 foreign-root 拒绝，并记录旧 transient JSONL 临时锁残留。该薄 runtime 不代表 SDK／Agent／lifecycle hooks 全链路。保留直接 await 且交付前不新增 await 可避免新造任务 registry；完整非 owned 接续与来源准入／替代成本仍待关闭。原 90–150 净减不能继续作为承诺；本候选没有生产削减成果，不混入上表。


## 全 C08 审计及 Arch 缓存资源归属（A30／A31）

A30 按原 31 文件逐类／函数重审职责、场景覆盖及剩余成本。PD-A/B/C/D 仍为 partial；root lineage、恢复发布、过期阶段与删除状态不是已被原组件完整覆盖的重复代码，不能将整段搬迁计为净删。该审计未证明 8,000 行可达，也没有证明理论不可达；原数量线保持。修复前原 C08 功能选择 78 passed（335.86s），原 Plugin Management 独立确认／删除另有 7 passed（0.81s）。这 85 项是 A29 源码证据，不冒充 A31 最终回归。

审计发现原 Arch 缓存写入器有两个资源归属缺陷：`fdopen` 部分构造后抛错可能覆盖原异常或误关被复用的无关 FD；独占创建临时文件失败后可能删除并非自己创建的碰撞文件。原源码先复现为 3 failed、9 passed（0.92s），包含三个流构造案例及九个成功／阶段失败案例；其中两项 FD 与一项碰撞回归是预期的旧缺陷失败，原 8 个正常／其它错误顺序案例通过。旧源码、红测和错误证据保存在产品树外，不使用新实现生成预期。

A31 将该缓存公开函数保留为 20 行 Coding 薄绑定：平台错误文案、公开导出、字节输入与产品调用点不变。原 Resources `windows_snapshot_io` 接收局部单文件写入，复用原 Windows ACL／native open、`closing_descriptor`。原 Windows Journal 的 `closefd=False` 包装原语提到既有 `_file_consumption`，Journal 与缓存共用；原 FD owner 仍负责唯一关闭。只有成功 exclusive create 后才取得临时路径清理权。ACL 在构造流之前，原 buffered write／flush／fsync、关闭后 replace、父 FD 关闭后清理未发布临时文件的顺序保留，不套用 Package 整树发布、prefix 校验或新增锁。

本片不是纯语义等价迁移：以上两个错误清理行为有意修复。原 native open 在实际创建文件之后、返回 FD 之前也可能失败；调用方没有取得归属证明时不再猜测并删除该路径，因此可能保留未发布临时文件。原 native 层只承诺关闭已开 handle，不在本片新增扫描或恢复管理器。该分支没有原生 Windows 故障注入证据，不能称所有失败都无残留或完整恢复合同已验收。未改变持久格式、缓存内容、Product 政策或原候选平台范围；没有新 manager／存储／事务系统。实际费用为 Coding 55→20（−35）、Resources 新增 46，**系统 +11**，不得称为系统净删。原 C08 累计 −2,381，仍距 8,000 行差 5,619；全 Coding 累计 −3,807，全部受影响生产源码仍 **+619**。完整 Goal 保持 active／partial。

A31 当前定向回归 207 passed、49 原生 Windows skipped（6.90s），四个增量生产模块 `mypy --follow-imports=silent` 通过。测试使用真实 Linux FD 与文件，Windows native open／ACL 为明确的边界替身；不构成原生 Windows ACL、reparse 或断电耐久证明。原树／回执／外部 Wheel／安装及 import 边界的下游选择另为 **326 passed（155.28s）**。163 个源／测试／fixture live hash、140 个冻结 Python 文件 Ruff、9 项文档不变量及 14 份改动文档相对链接、diff 检查均通过。三份独立代码评审均已完成，职责／复用、运行／失败、数据／兼容无本增量阻断；RT-A30-01 关闭。实施 owner 在已有授权内接受该有界增量，不代表整个 Goal、所有失败清理或原生平台验收。冻结 A31 清单 SHA256 `958f94ee9158414ceccfdadcd60026904a5861ab7274cf7ef0a707e9aa4f2ca8`。本轮没有提交或远程发布。


## Windows PD-B 完整替换的成本试验（A32，未进入产品）

本轮把确认、删除阶段／查证及物理删除串成外置可执行替换原型，避免把 94 行 native body 搬迁便当作整条链路完成。原型直接使用原 PM Event、原编号扫描／codec、Resources receipt／tree／native IO，保留 Product gate、根代际、Arch 布局与 hash 声明；没有新存储、锁、索引或任意 phase graph。全部候选源码和旧源保存在产品树外，活树仍是 A31。

| 外置候选范围 | 活树原行数 | 候选行数 | 候选净变 |
| --- | ---: | ---: | ---: |
| Coding Windows confirmation | 225 | 214 | −11 |
| Coding Windows deletion journal | 628 | 385 | −243 |
| Coding Windows deletion owner | 263 | 156 | −107 |
| 原 PM 接收层（新增 Windows 固定阶段实现及两个原组件有限扩充） | 748 | 1,358 | +610 |
| 总计 | 1,864 | 2,113 | **+249** |

这是完整接收代码、端口、类型、导入及公开外观的真实 dry diff，超出此前静态预算，**没有计入已经交付的 Coding／C08 削减量**。本片失败的判断不建立在“每个中间切片必须净负”这个额外条件上；原 Goal 只要求最终整体净负。问题在于它主要迁移原唯一 Windows 阶段体，再增加绑定，而没有证明更大的重复机制退出。

实际候选六模块的覆盖路径经过 `__file__`／hash 核对；现有 7 项 portable canonical／phase／closed-transaction／subset 测试通过（3.12s），显式候选与 worktree `MYPYPATH` 下的六源窄 mypy 通过。它们不覆盖完整 Product 准入、确认与消费、native 删除、staged／append 部分失败或全格式兼容。原 103 组 record-file fixture 的故障注入 seam 仍指旧 Code module 函数／可变限额；候选转为实际 receipt owner／ClassVar 后，必须先把注入指向真实 owner，保留原 expected，再谈接管验证。七项通过不是整条链路验收。

职责／复用、运行／失败、数据／兼容三份独立可行性报告均已完成，当前原型不能直接进入产品。审查还指出：共享层残留三处 Arch 专属错误文案和原 4 MiB 写限额声明（当前值兼容，声明归属仍不正确）；五方法 proof 端口虽有限，却仍把部分 parent／ACL／list／capture 机械体留在 Coding。不能把修正几条文案、或 callback 名称变窄视为 PD-B 完成。运行视角未确认默认绑定下的新时点／阶段顺序反例，但同样不认定七项检查足以进入产品。

实施 owner 决定**当前 R1 不进入产品，保留为成本与边界证据**；不扩大其验证来制造交付，不修改原 R3 或数量线。冻结候选清单 SHA256 `0fe598d03fc282f4ffd636618291abb2f2cb19ec1c2377a44e3042d1b38502e3`。本轮没有新增产品源码，原 A31 的 163 项源／测试／fixture 指纹继续核验。

另有全 Coding／Harness 的整函数候选扫描：保留常量值的 AST 形状仅提名五组，忽略常量值则七组，最大单组按保留一体计算的名义跨度为 42 行（不是已证等价或净删量）。它只排除“尚有现成数百行原样整函数副本可直接删除”的简单假设，**不覆盖跨函数／组件的语义重复，不是不存在大块去重的证明，更不是 8,000 行理论不可达证明**。不为这些小候选单独引入管理层；后续继续沿既有装配与原组件责任找完整可删除操作体。

产品计数不变：C08 仍减少 2,381 行，全 Coding 减少 3,807 行，全系统仍净增 619；原 8,000 行及完整场景条件均保持，Goal active／partial。本轮未提交或发布远程变更。


## Windows 确认与删除的实际接管（A33／A34）

A32 的外置 R1 保留原拒绝结论。A33/R2 补足原行为证据、修正共享层声明与 tombstone 物理边界，三视角候选代码评审后，A34 将七份实现接入实际工作树。范围沿用已接受 R3 的原 Plugin Management、Resources 组件，不新增运行服务、存储、锁、索引或可配置阶段图；不改变系统环境图、公开入口、持久格式或 Windows candidate 范围。

- 原 PM confirmation 接收 Windows 不可覆盖保存／读回程序；Coding 保留原确认权限、plan／key、记录内容、16 KiB 读／业务限制，并显式提供原 4 MiB 写限制。没有将两种限额合并。
- PM 内部固定 Windows transaction 接收原 started／renamed／completed、staged／replay、codec、编号扫描与追加。POSIX JSONL 和 Windows 不可变编号回执的动作合同不同，保留明确平台实现，底层仍用原 Journal 扫描及 Resources receipt IO。
- 原 PM deletion 接收 Windows 删除和 replay／start／effect／receipt／complete 程序；原 Coordinator 及 Product 完整 gate、quiescence、GC、借用 FD 与关闭顺序保持。Coding 只提供原身份、根代际、Arch 布局／hash／确认判据和有限 proof 端口。
- 原 Resources tree IO 接收 tombstone 的 parent／ACL／list／capture／前后身份复核。命名在原 list 后求值，不套用会新增准入的更强 directory 检查。该组件不解释 Product plan、generation 或确认。
- 三个 Coding 模块被替换的操作体同步删除；原公开类名、构造形状、dataclass 字段和真实消费者保留。恢复／expiry 仍调用的成员 helper 不是无用兼容壳，未盲删。

| 本片实际生产源码 | A31 | A34 | 净变化 |
| --- | ---: | ---: | ---: |
| Coding Windows confirmation | 225 | 216 | −9 |
| Coding Windows deletion journal | 628 | 363 | −265 |
| Coding Windows deletion owner | 263 | 156 | −107 |
| PM 固定 Windows transaction | 0 | 422 | +422 |
| 原 PM confirmation | 242 | 271 | +29 |
| 原 PM deletion | 506 | 666 | +160 |
| 原 Resources Windows tree IO | 586 | 630 | +44 |
| **合计** | **2,450** | **2,724** | **+274** |

Coding 减少 381、Harness 增加 655；其中一行是实际包路径下的 import 排版。候选原成本为 +275，接入后为 +274，差异不是新增算法收益。这是职责归位成本，不能称为系统净删。独立全源码重算包含全部未跟踪生产文件：634,820→635,713（+893）；全 Coding 145,842→141,654（−4,188）；原 C08 11,771→9,009（−2,762），距离原 8,000 行最低线仍差 5,238。原 Goal 数量与完整场景条件保持。

实施前冻结原源码结果：22 项物理后果／重试、9 项 tombstone 查证、15 项确认保存／查询、16 项实际 owner／transaction／codec／append／query，共 62 项。前两组使用真实 POSIX 文件与 FD，Windows ACL／handle／部分 capture 和删除叶子为明确的 inert 端口；后两组替换 Product authority／fence／native／存储端口，不代表真实受信 Product 装配或原生 Windows。

确认样本第一版的碰撞输入路径缺少原 hash 域，冻结时即发现没有命中碰撞；在产品修改前，使用原 `_record_path` 修正输入并冻结 v2。错误输入、旧预期及修正过程留在产品树外，没有从新实现生成 expected。原 103 项 record-file 与 56 项 sequence fixture 字节未改；故障注入改到真实 receipt owner／PM native 模块／transaction ClassVar。只有先断言显式写 cap 等于原 writer 默认值后，才归一非持久 trace 的 default／显式调用拼写；不归一错误、字节、阶段或副作用。

接入后的最终冻结源码验证：**151 passed、49 native Windows skipped（9.59s）**，包含上述四组兼容、原 confirmation／deletion、下游 root-lineage／restore／expiry 与 native tree 的相关选择。七个增量源码窄 mypy 通过；171 个 live hash、144 个 Python Ruff 通过。候选另有 77 passed、49 skipped（10.74s），范围与最终选择不同，不叠加成独立能力数量。原生 ACL、stream、reparse、共享标志及断电恢复仍未被这些替代端口证明。

A34 冻结清单 SHA256：`63715c4332afbae23df0292d16ae41bfe971e04b7a29651470caa45b70c1becc`；唯一接入差异为 journal import 排序／空行，非 import AST 与绑定集合相同。三视角的实际接入增量复核另记于[专项评审记录](key-designs/private-data-lifecycle-convergence-review.md)。不以候选评审或测试数认定完整 PD-B／Goal 交付；本轮未提交或远程发布。

职责／复用、运行／失败、数据／兼容三位 reviewer 均已完成实际接入复核，无新增阻断。实施 owner 在已有 R3 授权内接受这一有界增量，完整 Goal 与原生平台仍未验收。三份独立报告只读核查实现并引用已回收测试终态，未重复运行测试；不能把三份静态复核称为三轮独立运行验证。


## 原 GC 日志复用单次快照解析（A35）

在全 Coding 扩围及原组件复用范围内，检查接收层自身的重复：原 Plugin Management 四模块的五条读取路径（GC claim／binding／result、dependency repair／review），均在原 `load_jsonl` 完成 schema 与尾部处理后，再开文件解析一次 JSON 以查重复键。它们现直接使用原 Journal 已有的 `collect_duplicate_keys`，在原后置检查点调用 `snapshot.require_unique_keys`，随后才进入未改的 history 投影。第二遍读取、解析体及无消费者私有 hook 已删除；没有新增组件、存储、协议、锁或 Journal 实现。

保留默认 repair 与 binding 显式只读 raise／create_lock=False，重复键仍后于整份 schema／load／repair、先于 phase／revision。原 codec、记录、路径、公开构造与错误文案保持。Worker 的 `str.splitlines` 以及 frozen capture 的 duplicate-first 合同不同，均未套用此方案。消除第二次读取也消除了第一次成功后第二次开文件失败的机会，不为这种冗余 IO 故障保留另一条路径。

| 原接收层模块 | A34 | A35 | 净变化 |
| --- | ---: | ---: | ---: |
| GC binding（含 claim） | 643 | 632 | −11 |
| GC results | 487 | 474 | −13 |
| dependency repair | 603 | 593 | −10 |
| dependency repair review | 335 | 325 | −10 |
| **合计** | **2,068** | **2,024** | **−44** |

本片没有 Coding 削减量。全 Coding 仍 −4,188，原 C08 仍 −2,762；Harness 净增从 5,089 降到 5,045，全系统实算 634,820→635,669，仍净增 **849**。这是接收层的真实重复消除，不能替代 C08 原最低线或完整生命周期验收。

- 改源前用原两个真实 GC 场景取得原 codec 记录，2 passed（8.10s）；再从 SHA 守卫的原源码冻结 96 项完整加载结果、cause／code 与尾修复后的文件字节。记录中的临时身份仅作历史 codec 样本，不赋予当前 Store／Product 操作权。
- 原兼容测试 96 passed，另五项“不要重新读取”检查按预期失败；改源后最终 102 passed（1.70s），含 96 原结果、五项一次读取断言与一个原 Journal 尾部诊断检查。原 fixture 不从新实现重建。
- 实际 Product GC 准入、崩溃后 claim／删除／settlement／独立修复复核、重放及只读回归另为 41 passed（25.35s）。四源窄 mypy、173 live hash、145 Python Ruff 通过；两组范围分别记录，不累加为独立能力数量。新增测试 65 行，固定 JSON 样本约 505 KB，不计入生产源码削减。

A35 清单 SHA256 `99590a790476629e55c4fe277441d69a6f6e678c4506ce7776621aecc429ef2e`；三视角代码复核结果见[专项评审记录](key-designs/private-data-lifecycle-convergence-review.md)。本片未扩展平台、门禁或远程发布；整体 Goal 保持 active／partial。

职责／复用、运行／失败、数据／兼容三份报告均已完成，无本片新增阻断，实施 owner 接受有界直接复用。评审没有将重复开文件的故障或两次读取间的外部变化保留为合同：现在解码与重复键诊断来自同一次原 Journal 快照；原锁范围不变，不宣称处理任意外部写者。


## Windows 恢复记录阶段归原组件（A36／A37）

原 Plugin Management Restore 接管固定 Windows start／completion、发布凭据和恢复结果确认程序，直接使用原 numbered scan、history validator、receipt／tree IO。它是原组件内的私有平台实现；五个类型参数描述原有记录形状，不产生新的运行角色或任意阶段图。Code 原 transaction 保留相同 dataclass 构造字段与作用域，由无实例状态的基类提供原操作；借用 state FD 仍由原 Product wrapper 负责，不由基类关闭。

Coding 继续保留原 Publication／Plan／Event／Confirmation 具体类型、wire/hash/限额/前缀声明、完整 Q→GC→borrowedFD wrapper、Desired/deletion/root-generation 判据和 root/capture 薄绑定。原记录和 Product current-policy AST 没有变化；被迁出的阶段／扫描／发布操作体同步退出。没有新建存储、索引、锁、解析器或线协议。

归档查证同时直接复用原 `WindowsPrivateArchiveIO`：原 retained 验证与恢复源查询共用一份 parent pin→read→binding→verify→close→parent postcheck。窄记录谓词只比较已解码源的身份；外持 ACL 与局部 ACL 的寿命、stage／binding 不同错误保留。恢复查证的原机械体不再留在 Code callback 内；native/tree/codec 原语仍为既有实现。

| 实际生产源码 | A35 | A37 | 净变化 |
| --- | ---: | ---: | ---: |
| Coding Windows restore journal | 817 | 331 | −486 |
| PM 内固定 Windows restore | 0 | 706 | +706 |
| 原 PM Windows archive IO | 276 | 339 | +63 |
| **合计** | **1,093** | **1,376** | **+283** |

A36 外置候选为 Code −496／Harness +722／系统 +226。实际接入后按仓库 Ruff 完整格式化三源，另增加 57 行（Code 10、共享层 47），非 import AST 与导入绑定均等价；全部算入上表，不靠紧缩签名或少计空行兑现目标。这是职责归位及有限真实归档复用，不能称为系统净删。全 Coding 累计 −4,674，原 C08 累计 −3,248、距离 8,000 行最低线仍差 4,752；全产品实算 634,820→635,952（**+1,132**）。

验证与证据边界：

- 改产品前 SHA 守卫原七源，固定 31 项真实事务方法、发布前／后错误及查询、确认／恢复阶段、父查证和归档查证结果。使用真实 POSIX parent FD，Product current-source／Windows ACL、metadata、effect 和 receipt 为明确惯性端口，不授予当前 Product 或文件系统权威。
- 首轮候选 23 passed、1 failed：复用归档的 backup label 缺少原恢复的 Windows 前缀。旧源与失败快照保留；改为显式原 label 后 31 项一致，未改 expected。原 103 record-file、56 sequence、42 archive 观察 fixture 均保留原字节，故障注入改指实际 receipt／core／ClassVar，先核对原有效 4 MiB writer cap 才归一调用拼写。
- 外置候选组合 87 passed（1.82s），下游 23 passed、49 native Windows skipped（5.23s）；原产品上的同注入组合 45 passed（3.92s）。这些结果不替代实际复制后的验证，也不按内部样本数累加 pytest 数。
- 最终实际 A37 源码、不使用覆盖层：**110 passed、49 skipped（8.16s）**；三源窄 mypy、177 live hash、148 Python Ruff 通过。原生 Windows ACL、stream、sharing、发布与掉电行为不由 POSIX FD／替代端口或 skip 证明。

A37 清单 SHA256 `585481d9daccf07737ff910d1951a5cf11bd0b9dfc3f2629d59d5d2ae160ff5e`。候选三视角均支持有界实施，实际接入增量结论另记于[专项评审](key-designs/private-data-lifecycle-convergence-review.md)。Windows restore owner 的物理 stage/copy/publish、root lineage、expiry 及入口仍有待处理内容；PD-C 和完整 Goal 保持 partial，不以这一事务类的退出代替整个流程收敛。本轮未提交或远程发布。

实际接入三份增量代码报告也均已完成，无新增职责、运行或数据阻断。实施 owner 接受这一有界 R3 内部实现；重要架构工作件用户评审与完整 Goal 验收没有被替代。


## Windows 恢复物理流程归原组件（A38）

原恢复 owner 的复制、stage 发布与重试程序接入已有 PM Restore transaction；Archive IO 接管归档到 stage 的有界复制，直接复用原 capture 与 `copy_members`；Resources Tree IO 接管句柄发布和发布后物理查证。未新建 manager、存储、执行器或第二套树算法。Coding 保留原公开入口、具体记录／结果、路径和根代际政策，通过三处窄绑定在原时点参与。

执行顺序保持：关闭 stage FD → 根代际意图 → 发布记录 → 句柄重命名 → 根收据 → 父目录后验 → 恢复完成。原 Q／GC／借用 state FD 作用域未变；公开结果仍在原 transaction 内构造，未知副作用不会清空或重建 stage。保留 stage 身份／内容、archive 前后捕获、无覆盖与已完成重入的不同核查。

| 本片生产源码 | A37 | A38 | 净变化 |
| --- | ---: | ---: | ---: |
| Coding 恢复 owner | 349 | 79 | −270 |
| Coding 恢复 transaction 适配 | 331 | 370 | +39 |
| 原 PM Windows Restore | 706 | 862 | +156 |
| 原 Archive IO | 339 | 400 | +61 |
| 原 Resources Tree IO | 630 | 692 | +62 |
| 合计 | 2,355 | 2,403 | **+48** |

这是一片有完整接收成本的职责迁移，Coding 实减 231 行，不是系统算法净删除。累计全 Coding 为 140,937 行（−4,905）；原 C08 为 8,292 行（−3,479），距离原最低 8,000 行削减线仍差 4,521；受影响生产源码累计 **+1,180**。完整 PD-C、其他完整场景和最终数量要求均未完成。

实现前从原五源冻结 23 组物理效果、故障及三次重试观察，覆盖复制／flush／意图／发布／rename／根收据／完成的中断前后，以及 foreign stage、无归属 root、身份／内容变化和发布残留。旧实现另经实际导入路径与 SHA 守卫只读重放，23 组逐项相等，冻结器已退役，预期不会由候选生成。测试使用真实 POSIX FD／本地文件效果及惯性 Windows／Product 准入端口，不代表原生 Windows 权限或可信 Product 接受。

最终在实际工作树、普通 PYTHONPATH、无覆盖层验证：**111 passed／49 native Windows skipped（13.64s）**，五源码窄 mypy 通过。原 native 故障注入分别指向实际 Resources rename 与 Code journal 的根收据绑定，其余故障恢复断言保持。三视角独立代码评审及最终静态核查另列[代码评审记录](key-designs/private-data-lifecycle-convergence-review.md#a38-windows-恢复物理流程代码评审)。完整原源码、冻结预期、导入证明、测试结果和清单保存在产品树外 A38 证据目录。未增加门禁、平台范围或远程发布。

## 过期阶段共同判定：完整干差分未采用（A39）

实施前为两平台全部四阶段 history 与 confirm／begin／advance 重放判定制作完整候选差分，保留原具体事件、锁／repair／staged receipt 和构造时点。按项目 Ruff 排版并计入全部类型、导入、共享函数与调用适配后，两 Code 文件从 751 行降为 694 行（−57），新增 PM 固定判定函数 131 行，系统 **+74**。本候选的直接目的是消除重复并降低总代码量；该目的未达到，故未接入产品。它不同于此前 +16 的 storage-wrapper 原型，没有重建或采纳旧壳。

三位独立 reviewer 核实计数与不接入事实，支持拒绝；此结论不是运行兼容验收，也不为其它有必要的职责接管增设“每片都必须净负”的门槛。运行视角另指出原 `==`／`!=` 分支的机械互换，不能仅凭 Protocol 或 lint 认为对所有输入等价；被拒候选没有进入运行验证，不冒称已经证明安全。

实际产品／测试／fixture 的 179 项仍逐字等 A38 清单，新 PM 候选模块不存在；原 C08、全 Coding 和系统计数均保持 A38。完整差分、源指纹、成本与三份拒绝复核在产品树外 A39 证据目录。该测量排除了独立抽取这组判定函数的当前方案，未证明原 8,000 行目标不可达，也未修改任何完成条件。后续应核对完整职责边界与已有组件接管的实际收益，不继续叠加这套小型阶段抽象。


## Windows 过期完整执行程序接管（A40）

本片接通整个 Windows `expire` 执行程序，区别于未采用的 A39 纯判定抽取。原 PM 家族内的私有平台实现承担固定执行／重入；同一 Code expiry transaction 继承它，构造字段仍为 layout／product／restore，无新增状态或事实存储。Archive IO 接管 files／manifest envelope 的子集查证和清理，复用原 capture、Tree IO 成员删除及目录核验。Coding 保留公开校验、原 tombstone 哈希、具体记录、预览和恢复授权政策；具体 receipt 的一次类型 cast 只连接原 Code record 返回合同，不发放授权。

严格保留 scan／staged／父目录／ACL 顺序、开始记录先于重命名、重命名后 flush 先于 renamed 记录、跨 renamed 记录的两次子集观察，以及 completed 追加前后的两次 settle。根、files 和 manifest 的身份／残留与精确重试没有合并或增加拒绝。原借用 restore／state FD 的关闭范围不变。

manifest 的 exact ACL、single-link、stream、完整五元身份与错误顺序不同于通用 `require_file`，不能直接套用更强检查。Tree IO 的最小补充分开保留这些事实，字节／摘要循环直接使用原 `consume_file`；其可选 `size_error` 工厂仅保留原溢出 ValueError，无额外异常链，缺省错误和 quota 优先级不变。没有第二个 reader、遍历器、Journal、阶段表或 manager。

| 本片生产源码 | A38 | A40 | 净变化 |
| --- | ---: | ---: | ---: |
| Coding Windows expiry owner | 436 | 103 | −333 |
| Coding Windows expiry Journal／政策绑定 | 405 | 476 | +71 |
| 原 Archive IO | 400 | 555 | +155 |
| 原 Resources Tree IO | 692 | 727 | +35 |
| 原文件消费 | 98 | 99 | +1 |
| PM 私有 Windows expiry 执行 | 0 | 214 | +214 |
| 合计 | 2,031 | 2,174 | **+143** |

Code 实减 262 行，完整接收成本为 Harness +405、系统 +143，属于完整执行职责归位成本，不称为净删除。累计原 C08 −3,741（8,030 行，距原最低线仍差 4,259），全 Coding −5,167（140,675 行），系统仍 **+1,323**。原 Code expiry Journal 的编号 IO／history、归档完整 snapshot 捕获中的原生主体、POSIX 过期、其他厚查询／入口及完整 PD-C／Goal 仍未完成，不能把这一动作接管扩称为整个切片通过。

在产品改动前，以原五源实际导入路径／SHA 守卫冻结并只读重放 25 组完整动作观察。原编号记录的 codec／scan／append 是真实实现；POSIX FD、rename／unlink 为真实效果，Windows／Product／成员删除是无授权效力的测试端口。覆盖 started／renamed／completed 追加前后、重命名与各层删除前后、残留重试、manifest 同身份篡改／hardlink、额外成员及完成后重新出现。原 frozen bytes 未由新构造器重生成。

候选回归 88 passed／49 native Windows skipped（8.14s）；实际普通 PYTHONPATH、无覆盖层回归 **142 passed／49 native Windows skipped（14.24s）**，六源码窄 mypy 通过。四个文件消费错误合同检查覆盖缺省、原异常身份／无链、quota 优先和成功路径。原 native 故障注入转到真实 PM rename、Archive 删除和删除后报错方法，所有原断言保留。最后仅测试 import 排序变化，非 import AST／导入绑定相同，没有宣称重跑最后测试字节。

三视角候选及实际接入复核均无剩余阻断，184 份 source／test／fixture 与 153 个 Python Ruff 已核，独立源码统计一致。[评审记录](key-designs/private-data-lifecycle-convergence-review.md#a40-windows-过期执行程序代码评审)限定接受范围；原生 Windows／可信 Product／整个 Goal 均未验收。证据保存在产品树外 A40 目录，未新增门禁、平台支持或远程发布。


## Windows 归档快照捕获归原组件（A41）

Code 归档快照的完整原生捕获主体接入现有 Archive IO；Code 保留原具体 DTO／字段／ID／hash、公开签名和两个不可变记录投影。成员和最终快照仍在原 manifest／archive FD 范围内构造，构造失败不改变关闭及父目录后验优先级。原两次完整 archive verify 和文件捕获时点保持，不将不同时间的检查当作重复删除。

Tree IO 接管 manifest 原生观察，直接使用原 `read_bounded_prefix` 的 64 KiB／max+1 消费；保持 ACL／类型／single-link／stream、after／visible metadata 及原字节比较顺序。R1 重复写了清单格式表达式；职责评审核实原 Windows `codec.encode` 正是同一表达式且无额外 key 校验，R2 删除该重复与外部格式回调，在原后验 metadata 之后延迟调用同一 codec。O-A41-01 已关闭，未套用 POSIX 的额外 key 检查。

原 Archive IO 的 retain、retained／restore 读取及新 snapshot 捕获共用一份私有父目录作用域，保留 inspect 在 ACL 构造之前、原 open／ACL／held identity／close／路径后验顺序。消息来自当前实际 frozen Tree IO 的 Code 内置字符串，此证明不推广任意可变 label。没有新增运行组件、store、元数据引擎或控制回调。

| 本片生产源码 | A40 | A41 | 净变化 |
| --- | ---: | ---: | ---: |
| Coding Windows archive snapshot | 263 | 123 | −140 |
| 原 Archive IO | 555 | 660 | +105 |
| 原 Resources Tree IO | 727 | 775 | +48 |
| 合计 | 1,545 | 1,558 | **+13** |

真实去重包括原 manifest 读循环、重复格式表达式及三个实际消费者的父目录 scope；全部类型、作用域及 DTO 投影成本计入后，系统仍 +13，不称为净删除。累计 Code −5,307、原 C08 −3,881（7,890 行，距最低线仍差 4,119），系统仍 +1,336。完整 PD-A/B/C/D、厚 Journal／POSIX 动作／查询／入口、原至少 8,000 行及系统净负要求继续未完成。

在原三源 canonical 导入路径／SHA 守卫下固定 20 组完整观察，再只读重放：20 passed（0.39s）。真实 POSIX FD、原 Archive verify／read／codec 与记录校验运行；Windows／metadata／形状捕获为测试端口，不代表可信 Product／原生 Windows 验收。覆盖双故障异常 context、关闭失败后验、两类投影拒绝、先验与后发 hardlink／stream／篡改等。固定原 raw 未从候选生成。

R2 候选回归 152 passed／49 native Windows skipped（8.09s）；实际正常 worktree PYTHONPATH、无覆盖层为 **152 passed／49 native Windows skipped（10.92s）**，三源窄 mypy 通过。186 份 source／test／fixture 与 154 Python Ruff 核查，五候选文件实际逐字一致，之后无源或测试改动。三视角 R2 与实际增量复核无剩余阻断，详见[评审记录](key-designs/private-data-lifecycle-convergence-review.md#a41-归档快照及共同作用域代码评审)。R1 原稿和评审保留于产品树外，未提交或远程发布。


## Windows 过期 Journal 与两平台历史校验归位（A42）

实施外置完整接管候选的 R2：原 `WindowsPrivateExpiryTransaction` 现在负责扫描、规范字节校验、追加后查证、确认重放与固定阶段推进，直接复用既有 `WindowsPrivateReceiptIO`、编号扫描和 JSON codec。Coding 原机械主体删除，保留原记录类型／ID／hash／存量字节、Product 与 Restore scope、公开构造形状和最先执行的类型／计划准入。三个相同的 current-plan 预览体收敛为一个领域方法，各次调用的原时点保持。

两平台在原校验位置调用同一份四阶段历史判据；POSIX JSONL 的锁、修复与重复键优先级，Windows 的编号收据与 staging 恢复仍各自保持。共享组件只读取原 Restore 的 FD／active 窄视图，不读取 Product／layout；数据构造绑定原 record class 和原 create classmethod，不引入执行回调或第二套存储。物理过期程序及归档删除在本片没有改变。

| 本片生产源码 | A41 | A42 | 净变化 |
| --- | ---: | ---: | ---: |
| Coding POSIX expiry Journal | 346 | 324 | −22 |
| Coding Windows expiry Journal | 476 | 323 | −153 |
| 原 PM Windows expiry 组件 | 214 | 378 | +164 |
| PM 共用历史校验内部模块 | 0 | 58 | +58 |
| 合计 | 1,036 | 1,083 | **+47** |

R1 的完整成本为 +76，R2 删除冗余工厂／scope 转接后为 +47；不能称系统净删。A39 的四助手候选与单独存储外壳仍未采用。本片 Coding 减少 175 行，全部接收成本 +222 行计入；累计全 Coding 145,842→140,360（−5,482），原 C08 11,771→7,715（−4,056，8,000 行最低线仍差 3,944），全生产源码 634,820→636,203（仍 +1,383）。完整 Goal、PD-A/B/C/D 和系统净减少要求没有完成。

验证及效力边界：

- 产品修改前在原源码 SHA／canonical import 守卫下冻结 13 组完整 Journal 行为与原构造字段／slots／签名。包含确认／各阶段重放、staging、不同 actor、写入前后失败、关闭及预览优先级、旧 bool 版本和与存量 int 相等的 live float prior 到新记录默认整数版本；不声称 float wire 可存储，原 canonical JSON 仍拒绝浮点。旧的 103／56／25 组文件、序列、完整动作固定预期未改。
- 实际源码定向回归 **52 passed（10.65s）**；相邻记录、恢复、归档快照与过期投影另 **94 passed（12.49s）**。路径 trace 从 `str(path)` 改为 `as_posix()` 关闭独立评审的跨平台测试问题，旧预期无需改变；该新测试 14 项随后单独复验。真实记录／codec／阶段逻辑与 inert Windows／Product 端口不构成原生 Windows 或可信 Product 验收。
- 四份变化源码的窄 mypy 通过。默认 follow-imports 扩查依赖时仍报 237 errors／8 files，不能称全量类型检查通过；首次并行窄检查进程退出 139，停止并发后以独立 cache 完成四源检查，没有据此修改 Product。实际冻结与静态结果在产品树外独立记录。

本片技术实施沿用已接受 R3 的原组件职责，不扩大平台、协议、写授权、CI gate 或模型预算；内部代码评审不冒称用户另行接受新架构，也不关闭整个 Goal。


## POSIX 过期固定动作归原归档组件（A43）

原 `private_data_backup` 组件接管 POSIX 过期的固定执行、无覆盖 rename、两次 tombstone 子集查证与删除后的 completion；直接复用原 Journal、`PrivatePosixTreeIO`、metadata／subset 核验及原 no-replace／fsync。Coding 的旧 execute／rename／subset／remove 主体已退出，原公开命令准入、offline 作用域、领域预览／恢复权威、记录／hash／路径政策保持。原 dataclass 继承、字段、slots 与构造形状不变，未增加运行角色、存储或步骤注册框架。

首个继承／abstract 接口草稿净增 135 行，固定函数版净增 98 行；按独立运行评审建议放回已有归档组件，共用原 IO／类型／原生操作导入，最终净增 71 行。先前两个草稿逐字保留在产品树外，没有把其预算当实际收益。原归档组件已有 class／function 的 AST 与本片前逐一全等。

| 本片生产源码 | A42 | A43 | 净变化 |
| --- | ---: | ---: | ---: |
| Coding POSIX expiry owner | 448 | 309 | −139 |
| 原 PM private_data_backup | 167 | 377 | +210 |
| 合计 | 615 | 686 | **+71** |

共享函数只消费原 Journal、树 IO、原两方法权威窄视图及四个延迟的路径／名字／捕获映射；不读取 Product／layout，不提前计算原来在 history／open 后才查询的值。events→父路径→open→tombstone→try/finally、五元与三元身份核验、跨 renamed checkpoint 的两次子集观察、清理后 completion 均保持。旧 tombstone 名字计算若在进入 try 前失败会留下 FD 的边界也未在此次迁移中偷改；本片不宣称修复该旧分支。

验证及效力边界：

- 修改产品前，15 组真实 POSIX 文件／Journal 动作结果经原 Code 源码 SHA 与 canonical import 守卫固定，覆盖成功重放、每个写 checkpoint 前后失败、rename／remove 前后失败、部分成员删除、恢复拒绝、额外成员和完成后 archive 重现。真实每 run 的 Plan／Confirmation／Receipt 身份有独立等值断言；没有把随机 inode／mtime 导出的 wire bytes 当作跨 run 常量。
- 独立运行评审发现初版 FD 断言只追踪 `os.open`，未含 `os.dup`。补齐后使用原 canonical 存档源码只读重放同一预期 **1 passed（3.02s）**，实际动作 **15 passed（2.98s）**；固定预期不变。最初 freezer 只核验 Code 源，原 PM 源 guard 是后补成本／AST 对照，不冒称初次 freeze 已执行后增条目。
- 最后直接归原组件的实际源码、普通 worktree PYTHONPATH／无覆盖层验证为 **27 passed（36.39s）**，含 15 动作及原 12 项保留→删除→恢复→确认→过期集成。旧 integration 只把 whole-remove 故障注入转到真正执行的 PM 函数，stub 接收真实 IO／capture kwargs，其余原断言保持。原动作探针的 Product 准入仍是 inert port；原集成测试实际执行 Product 装配，但不推导原生 Windows 或整个 Goal 已验收。
- 最后两份变更源码窄 mypy 通过。此前两版结果分列、不与最后 27 重复累计；A42 默认全依赖类型检查未绿的限制仍保留。混合外置／仓库测试入口曾在 collection 前重复注册 conftest option，拆成独立进程后通过，没有修改 Product 来绕过。

独立全量实算为全 Coding 145,842→140,221（−5,621），原 C08 11,771→7,576（−4,195，8,000行最低线仍差3,805），全生产源码634,820→636,274（仍+1,454）。本片只关闭 POSIX 过期执行动作的厚体；`_expiry_preview` 的原生观察段、POSIX Journal 及其它原场景继续单列，不声称完整 POSIX expiry owner 或整个 Goal 收尾。未新增平台、门禁、模型调用、提交或远程发布。


## 两平台归档枚举归原 Archive owner（A44）

POSIX／Windows 的完整 retained-receipt 枚举移交原归档组件，Code 的 `_retained_receipts` 保留原签名／返回类型及薄调用；原循环、读验与 Native scope 主体已退出。Windows 为原 `_parent_scope` 的第四个真实消费者，复用同一 open／ACL／held identity／close／路径后验；没有再写一套 scope、reader、store 或 manager。原两个归档组件的已有方法／函数 AST 保持，格式／DTO／ID／hash 没有改变。

R1 误将 Windows 的 SHA64 名称规则内置于通用 ArchiveIO；独立职责评审指出后关闭。R2 从 Code 传入原 `len`→`any` 短路表达式，未采用会新增 `strip`／类型校验的 `_digest`；POSIX 仍使用原 `_digest`，并显式传入原 `.staging` 值，不依赖另一份 codec 配置的变化。Windows 不忽略 staging，原 allowed-tombstone／pending 碰撞判定、缺失祖先的 inspect／lstat 区分与惰性 package-root 查询保持。没有加强 POSIX 后验或将 Windows 路径改成无创建读准入。

| 本片生产源码 | A43 | A44 | 净变化 |
| --- | ---: | ---: | ---: |
| Coding POSIX backup | 351 | 343 | −8 |
| Coding Windows backup | 431 | 384 | −47 |
| 原 PM POSIX archive | 377 | 411 | +34 |
| 原 PM Windows archive | 660 | 731 | +71 |
| 合计 | 1,819 | 1,869 | **+50** |

R1 完整成本 +43，修正产品规则归属和保持原求值／接受边界后为 +50；不能按旧稿数字记账或称为净删。另一条记录编解码静态筛选在严格保留原字段求值顺序条件下没有找到直接替换对，没有因此新造 schema 顺序框架或计入源码成果；该筛选也不是“无其它重复”或“8K不可能”的证明。

验证与局限：

- 原四份磁盘源码 SHA 守卫下先固定25组完整枚举／scope／错误结果；再对四个 canonical 模块路径与 SHA 做只读重放（**1 passed，2.79s**），固定预期未改。额外名称子类断言复用旧 valid 预期，验证无新增 strip。缺失目录、重复名称、tombstone、读失败及关闭／后验错误优先级保持；这些新观察使用 inert Native／codec，不能当实际 wire 或 Windows 平台证明。
- 首轮实际回归 **67 passed／1 failed（40.43s）**，失败是原 FD 测试向已经退出的 Code.os 注入。只为该退休 Code 绑定增加条件，原真正执行的 PM／Native／file-consumption 始终注入；原断言与 fixed expected 保持，未补回 dead Code shim。
- 同一实际范围修后 **93 passed（17.27s）**，含原保留／删除／恢复／过期 Product 集成、POSIX 过期、Windows 归档动作／真实 FD、快照及投影。实际四源窄 mypy 通过。第二次 manifest 读取由原 verify 实现与相邻原例支撑，不把新 stub verify 称为双读证据。A42 全依赖类型检查未绿、原生 Windows 未验收的限制继续保留。

独立全量实算：全 Coding145,842→140,166（−5,676）；原 C0811,771→7,521（−4,250，最低8,000行还差3,750）；全生产源码634,820→636,324（仍+1,504）。整个 Goal、PD-A/B/C/D 的其它观察／协调及最终数量／净负要求继续未完成。未新增 CI gate／平台／模型调用，未提交或远程发布。


## Worker Journal 父目录作用域复用（A45）

[专项设计](key-designs/private-journal-parent-binding.md)将四个原 Journal 的父目录打开／身份准入／绑定／cleanup／后验／关闭归原 Journal 单份 scope，直接复用原 `_private_parent_matches`、RootedFileIO 和锁。Code 的锁选择、V2、缺失锁诊断和首次 head 初始化原体保留；原四套重复 scope 退出。Code −97／Harness +32／系统 −65，新增成本全部计入，不将扩围收益混入原 C08。

原五源 SHA 与 canonical 导入守卫冻结的 256 惰性观察在原树重放，通过后才接入。实际最终生产回归76项通过（160.22s）；数据评审发现新测试应限定 Linux，仅补标记后又4项通过（3.76s），expected 未改，两组不累计为独立能力。三视角实际代码无剩余阻断，五源窄 mypy 在更换缓存方式后通过；测试与类型检查的来源、局限及终态见[评审证据](key-designs/private-journal-parent-binding-review.md)。类型检查器缓存提交故障未被隐去。

本轮还独立核实了 Resource Catalog、Capability cleanup 和旧 private-state scope：原组件尚不能直接承接各自的 receipt 完整性、BaseException／重试凭据、Windows 最小访问掩码和 pin 次序。未把这些主体搬进新框架，未计虚假删除；该有限审查也不证明整体目标不可达。累计全 Coding 减少5,773行，原C08仍减少4,250行（原最低线差3,750），系统仍净增1,439。完整Goal未完成，未提交或远程发布。


## 原 RootedFileIO 词法清理与回执读取归一（A46）

[H-COD-KD-005 R2](key-designs/private-journal-parent-binding.md#r2原-rootedfileio-的显式词法清理a46)由原RootedFileIO提供标准词法上下文，21处原局部try/finally清理直接复用；另一处完整回执读取复用R1父目录scope。原cleanup算法、清理债务、Product／GC／锁及存量格式不变，长期Transcript／lease持有的IO不纳入。原22处重复清理控制体退出，没有新增manager、状态表或回调框架。

候选及实际代码均经过三视角复核，15生产＋2测试逐字匹配。真实FD／原scope与publication合同99项通过（8.74s），原业务调用链92项通过（94.14s），15源窄类型检查通过。212hash、176Python Ruff及17变化Python格式检查通过；旧expected不改，惰性256观察与新真实FD例的效力分开，见[实际评审](key-designs/private-journal-parent-binding-review.md#r2a46原-io-词法清理与完整回执读取)。

本片Code−87／Harness−5／系统−92，其中格式−10单列。原A30的31文件交集只有backup_types，原C08实际减3，其余84属扩围；预审的C08不变概括已更正。当前累计Code−5,860／C08−4,253（仍差3,747）／系统仍+1,347，完整Goal继续未完成。未提交或远程发布。


## POSIX 过期 Journal 完整接管（A47）

Code原events／confirm／begin／advance／append／load协调体已退出，原PM过期组件直接复用JsonlJournal、path admission、锁和历史判据；Code保留路径准入、原DTO／codec、限额与工厂。Windows原advance成为同组件内唯一无状态算法体，两平台只适配原scan／append，未合并不同的存储或confirm／begin合同。

原3源SHA/canonical守卫冻结24项真实POSIX Journal行为；候选canonical映射对照39项通过，实际43项Journal与52项原业务／过期动作回归通过，三源窄mypy通过。三视角实际代码无剩余阻断，字节／四实例字段／动态工厂与限额／尾修复及未知append结果保持。惰性archive元数据、真实Journal与native Windows效力分开，见[专项评审](key-designs/private-data-lifecycle-convergence-review.md#a47-posix-过期-journal-与共同推进终审)。

完整成本Code−130／Harness+207／系统+77，是职责接管及类型适配的中间成本，不称净删。累计Code−5,990／原C08−4,383（仍差3,617）／系统仍+1,424，原Goal数量与最终系统净负及其它残留场景条件不变。未提交或远程发布。


## POSIX 恢复固定协调归原 Archive（A48）

原 Code restore 的转存、预检、开始／重放、完成和归档身份复核主体归既有 PM Archive；直接组合原 Tree IO、Restore Journal、metadata identity 和 FD scope。Code 保留 Product removed／offline、删除凭据、备份绑定、计划类型／版本／身份准入、路径／阶段命名、具体记录和结果投影。两个旧物理协调 helper 已退出；预览及完成结果确认仍使用原入口，不能据此称其全部收敛。

| 本片生产源码 | A47 | A48 | 净变化 |
| --- | ---: | ---: | ---: |
| Code POSIX restore | 446 | 376 | −70 |
| 原 PM private_data_backup | 411 | 505 | +94 |
| 合计 | 857 | 881 | **+24** |

原顺序保留：files FD 关闭→archive 持有与可见身份复核→Journal complete→在 archive／parent FD 仍打开时构造结果→逐层关闭。失败不提前完成或清理共享备份；replay 不取写入器。验证／准备／ID／结果工厂保留原调用时点，写入器在第二次 prepare 后进入原 Tree IO 前只取得一次，避免把一次传输变成逐文件选择策略。计划仅投影 frozen DTO 的 target_state；不迁移 Windows 的完整计划协议，没有新 store、index、queue、动作框架或平台保证。

候选静态检查和独立评审关闭了缺失导入、固定 files 名称、钩子提前绑定及逐文件重取 writer 问题；试制脚本曾误替原 retainer 的写参数，Ruff 在采用前发现，复核所有原 PM 函数／类 AST 与 before 完全相等后修复。所有试制版本成本不能替代本表末版成本。

改产品前，两份原 canonical 源 SHA 守卫固定22组惯性端口观察；补充第23组 writer 反例时重新核验旧22组相等，旧 fixture 字节保留，只将新增观察写入第二版本。覆盖成功／completed replay、existing 缺 start、same-bytes 计划与 absent 冲突、各恢复时点失败、close 失败及双异常优先级。候选23组＋来源校验 **24 passed（5.23s）**；实际 worktree 无映射层执行新23组及原12项 Product 集成，共 **35 passed（16.48s）**。随后产品配置 Ruff 发现候选目录默认配置未检查的导入排序 I001；仅调整 import 顺序后，最后实际源码同范围 **35 passed（16.46s）**、两源窄 mypy 通过。候选 shadow mypy 通过记录仍保留，但不替代最后实际验证。最初 freezer 使用无效测试 scope 而失败，修正后原22冻结1项通过（2.46s）、第23补充冻结1项通过（2.42s）；未据此修改 Product。

新观察以惯性 native／Product 准入端口验证顺序，不能证明实际 inode／权限；原12集成单独执行真实 Product 和 POSIX 文件操作，也不替代原生 Windows。A42 全依赖类型检查237错误／8文件尚未关闭，本片窄检查通过不代表所有检查通过。三视角实际复核与接受边界见[专项评审](key-designs/private-data-lifecycle-convergence-review.md#a48-posix-恢复协调终审)。全量独立核算为 Code−6,060、原C08−4,453（最低线差3,547）、系统仍+1,448；本片是有成本的职责接管，不是系统净删。完整 Goal 仍未完成，未提交或远程发布。


## Windows Worker 三类只读历史作用域复用（A49）

从整个 Coding 查找真实重复，逐函数同体扫描没有发现可直接替换的大块；本片选取三个保留原数据的完整只读场景，而非再迁入一份执行体。Worker receipt.records、native approval.history_read_only、opt-in.history_read_only 的共同 ACL／缺锁／标记／共享锁／读取／成功后根检查程序交给原 Resources WindowsJournalFileIO.read_snapshot。它直接复用原 Journal shared lock、validate_lock、read 和 ACL／native stat；Code 在 with 体内继续调用原 decoder，原 Product／GC／root入口、写入和领域错误不下移。没有新 manager、record、store 或锁协议。

| 本片生产源码 | A48 | A49 | 净变化 |
| --- | ---: | ---: | ---: |
| Code Windows receipt Journal | 227 | 200 | −27 |
| Code Windows native approval Journal | 268 | 239 | −29 |
| Code Windows opt-in Journal | 291 | 263 | −28 |
| 原 Resources WindowsJournalFileIO | 203 | 243 | +40 |
| 合计 | 989 | 945 | **−44** |

三个 Code 文件的既有空白经 Ruff 整理减少15行，剔除后流程结构 Code−69／Harness+40／系统−29；不把排版叫作算法删除。本片所有补偿代码和修改后的 adapter 文档均计入成本。它是扩围切片，原31源 C08 数字保持不变。

改产品前，以四份原源码 SHA 和 canonical import 固定3类×22分支共66个原流程结果：缺锁且缺文件、缺锁有文件、initialized orphan、uninitialized empty、corrupt、入口／ACL／stat／lock／读取／decode／根后验失败及双退出异常。freeze **1 passed（3.00s）**；候选同66观察与来源校验 **67 passed（6.24s）**、四源 shadow mypy通过。原固定fixture字节未改。

实际接入后，普通worktree PYTHONPATH／无overlay的 **265 passed（6.80s）**，覆盖新66观察、原五类文件IO兼容及实际本地FD寿命、原Windows历史语义；实际四源窄mypy通过。终审发现新测试的 /inert 在 Windows 无盘符，改为当前平台真正绝对的惯性构造路径；生产源和expected字节未变，修后新66项 **66 passed（4.37s）**，不与前265重复累计。新观察的ACL／Native／锁／域准入为惯性端口，旧FD用本机真实描述符，均不替代原生Windows权限、stream或durability验证，不开放原candidate平台。A42默认依赖扩查237错误／8文件仍未解决或充分归因。专项设计和三视角实际接受证据见[H-COD-KD-005](key-designs/private-journal-parent-binding.md#r3windows-worker-只读作用域a49)及[评审](key-designs/private-journal-parent-binding-review.md#a49windows-worker-只读作用域终审)。

独立全量核算：Code145,842→139,698（−6,144）；原C0811,771→7,318（仍−4,453，8K缺3,547）；全生产源码634,820→636,224（仍+1,404）。虽然本片系统净减少，整体Goal仍未完成；未提交或远程发布。


## Windows 预览与删除屏障直接复用原组件（A50）

两处归档父目录scope和两处删除凭据屏障直接调用原Plugin Management实现，没有为此次接管扩充Harness。恢复预览与过期预览使用原Archive._parent_scope作为第五、第六个调用点；同一原Native IO identity、open、ACL、close及关闭后inspect保持。暂存债务的两个原错误分支分别保留。恢复Journal的ID查询与过期恢复权限检查使用原latest_deleted_target_receipt，不再复制“只认最新同Installation事件”的循环；后续确认的deletion_receipt_id仍与这一receipt绑定，不回退到较旧deleted事实。

| 本片生产源码 | A49 | A50 | 净变化 |
| --- | ---: | ---: | ---: |
| Windows restore preview | 157 | 149 | −8 |
| Windows expiry preview | 172 | 164 | −8 |
| Windows restore Journal | 370 | 365 | −5 |
| Windows expiry recovery | 160 | 152 | −8 |
| 合计 | 859 | 830 | **−29** |

全部四源都在原31文件内，Code／原C08／系统各真减29；原两个Core文件逐字未变。未新增runtime、manager、协议、日志、锁或平台，没有将Root lineage政策、SDK语法和已共享DTO搬到Core。

原2Code＋Archive SHA/canonical守卫先冻结两种公开preview的44观察，1passed/3.39s，含具体旧Plan DTO的字段／fingerprint与close／postcheck双异常。扩充查询候选前，原4Code＋2Core守卫另外冻结9个删除屏障／完整恢复权限走查，1passed/2.83s。Native／Product事实为惯性输入，不当可信权威；两个旧fixture字节保持。原阶段2源候选45passed/5.86s、2源shadow通过单列；最终4源候选54passed/3.11s含来源检查，4源shadow通过，不合并为独立覆盖。

实际普通worktree PYTHONPATH／无overlay：**97 passed（4.50s）**，含新53观察、原Windows恢复交易和具体删除事实合同；实际四源窄mypy通过。原4源码除指定四方法外AST保持，Core native/record算法不变。测试准备阶段只整理新probe的imports／多语句格式，未改变observe逻辑或旧expected；未发生生产测试失败。原生Windows的ACL／stream／durability及完整Goal不由这些惯性走查证明，A42默认依赖扩查237错误／8文件仍未解决或充分归因。实际三视角接受见[专项评审](key-designs/private-data-lifecycle-convergence-review.md#a50windows-预览与删除屏障直接复用终审)。

同时对原7318行C08做三视角下一步复核（外部next-c08-a50-review-ownership/data与next-coding-a50-review-runtime）：本地11个serializer DTO类701行、9张schema181行均不等于可删池；8/11 from_dict及平台共用Restore/Expiry DTO已经复用，Core同名Protocol不是真值实现。根代际681行主要保留Product规则；原borrowed state root入口有prepare/create，不能替换status的无创建读。原4个replay循环总116行而非数百，5个append整尾224行扣除完整helper/适配后粗估仅净减21–66，不启动新通用engine。以上是有范围的源码证据／粗估，不证明8K不可达，也不改完成线。

独立原基线全源核算：Code145,842→139,669（−6,173）；原C0811,771→7,289（−4,482，最低线差3,518）；全生产634,820→636,195（仍+1,375）。整体Goal继续active／incomplete；未提交或远程发布。


## 五流固定追加协调去重（A51）

C5、receipt、start gate、Supervisor、opt-in 的五份 seal→append→head commit 固定尾部归原 history_segments 单份函数，继续使用原 seal、_segment_name、commit 与 Harness append_jsonl_record。Code保留授权／CAS、单条容量、记录生成、V2／checkpoint分支及返回值；追加端口只提供原编码／目标绑定，seal_error端口只映射原seal错误，不捕append／commit，也不修复或回滚未知写入。两个端口是现有差异，不是任意阶段／hook或新backend。

| 本片生产源码 | A50 | A51 | 净变化 |
| --- | ---: | ---: | ---: |
| Code activation state Journal | 550 | 530 | −20 |
| Code receipt | 1,242 | 1,220 | −22 |
| Code start gate Journal | 766 | 745 | −21 |
| Code Supervisor Journal | 541 | 525 | −16 |
| Code opt-in | 885 | 866 | −19 |
| 原 Code history_segments | 730 | 778 | +48 |
| 合计 | 4,714 | 4,664 | **−50** |

完整成本含新增函数、两个端口及五个调用适配；原before独立Ruff格式化为+1行，因此结构净减51／格式净增1，实际系统净减50，不按旧224行全额报收益。Harness零新增。本片属于全Coding扩围，原31 C08交集为空。原物理段组件仍在Code；这里只关闭五份重复协调，不把中性机制的最终归位写成已完成，也没有把730行搬入Harness计作净删。

原6份源码 SHA/canonical 守卫后，直接从原实际尾部语句提取并固定5流×15组共75个观察，freeze80026 **1passed/5.43s**，记录原语句范围及生成程序hash。覆盖generation0／后续代、原始basename、数量／字节触发封段、seal三类错误、目标错误、append前／后失败、commit前／后失败、seal后配置及重编码漂移；控制端口为惯性，不代表Product准入或真实IO。首次候选93254为3pass/1fail，原因是探针误选start gate外层public append；仅修最近nesteddef选择后，原6源／原生成程序hash／75旧expected只读复放76070 **1passed/7.57s**，最终候选87031 **76passed/8.29s**，fixture未改。候选六源shadow mypy通过。

真实RootedIO三例独立验证跨代重开及写后异常／重编码漂移保留head债务。最初85726使用默认locking策略与已有bound transaction冲突，仅按原caller的已持锁unlocked durability修正测试，24200 **3passed/0.50s**；未修改Product策略或产品代码来绕过。实际普通worktree PYTHONPATH／无overlay，59377 **107passed/30.55s**，包括新75观察、原段协议／五流业务及checkpoint和新真实文件例；实际六源窄mypy通过。随后仅新真实测试按Ruff B023明确绑定循环record，生产六源与expected不变，68731 **3passed/0.77s**复验修改范围；两组重叠不相加，不称107运行了后改测试字节。

新惯性观察与真实本机RootedIO证据分列，不替代所有Product授权、原生Windows或断电耐久验证；原V1/V2／编码空格风格／锁／文件格式和错误边界保持。A42较宽依赖类型检查237错误／8文件仍未解决或充分归因。实际三视角结论见[专项评审](key-designs/private-journal-parent-binding-review.md#a51五流追加协调终审)。

原基线独立全源实算：Code145,842→139,619（−6,223）；原C08仍11,771→7,289（−4,482，8K缺3,518）；全生产634,820→636,145（仍+1,325）。Goal继续active／incomplete，原完成线不变，未提交或远程发布。

## 相关生产源码联合类型核对（A52）

将本任务全部 137 份修改／新增生产 Python 一起显式交给 mypy，发现 `package_source_snapshot.py` 的局部平台 adapter 被推断为 object，产生三个 stat／open 属性错误。其读取函数与原 Git 基线 AST 相同，不能把它描述为本轮重构引入的运行缺陷。只导入标准库 AbstractContextManager，并为该局部变量补充两个实际平台类型的联合注解；没有新增 Protocol、断言、拒绝条件或执行分支。去除此注解和新增导入后整模块 AST 相同，读取函数字节码也相同。

修正后 137 源联合检查通过；再加入原 C08 中未修改的 POSIX SDK 和 Windows candidate client，**139 份显式生产源码联合检查通过**，覆盖原 31 文件全部集合。采用原 `--follow-imports=silent` 策略、非 SQLite 的独立磁盘缓存；不能据此宣称默认追踪整个依赖图的检查通过，A42 的 237 错误／8 文件记录仍保留。运行器元数据曾误把 argv 前缀计成五项，已按可执行程序及三个选项共四项修正数量；执行命令、原 stdout 和实际源集合未改。

本片没有执行语义变化，没有新增或重复运行 pytest。229 份实际 hash、187 Python Ruff、改源格式及 diff 检查通过。生产源码物理行数不变，A52 数量与 A51 相同，不计新的删除收益。独立复核及接受范围见[专项评审](key-designs/private-data-lifecycle-convergence-review.md#a52-联合类型合同与无运行变化复核)；完整 Goal 仍未完成，未提交或远程发布。

## Worker 分段历史原语归原 Harness 组件（A53）

A51 已消除五份追加尾部重复，但公共分段原语仍留在 Coding。原 Harness Worker 的平面历史与原 Journal IO 不能直接解释已有 manifest／head／未提交尾部协议；本片将单份机制归 Worker 内部模块，继续复用原 RootedFile 与原 canonical JSON，不新建 backend、恢复权威、路径配置或执行器。编码记录解码、Product 准入、锁／GC 寿命与封段政策继续留在原消费者。全部非文档 AST 与原实现相同。

Code 原模块只保留同一对象的兼容导出，原 13 个公开符号、追加 helper 及 V2 所用的三个命名函数继续可导入，没有执行包装或第二份类型。历史 Coding 前缀及 error code 为兼容标识；真实定义模块与 traceback 文件转到 Harness。旧 import、签名、JSON 及旧对象引用保持，不承诺旧版本读取新模块路径的 pickle。

迁移前用原实际模块 SHA／canonical 路径守卫固定公开符号、签名、manifest 字节及四种旧对象样本，61584 **1 passed（0.44s）**。原 75 项观察的 expected 未改，只把故障注入指向实际 Harness owner。首轮新增测试漏传原 from_bytes 必需的 stream_id，28448 为 80 passed／1 failed；仅修测试输入，生产与两份固定样本不变。同组实际复验 70876 **174 passed（41.83s）**，包含旧路径同对象、旧引用、原 JSON、五流及 V1/V2 checkpoint／read／stage／commit／rotate／retire 等历史语义。140 份显式生产源码联合 silent mypy 通过，不扩称默认全依赖、原生 Windows 或断电验证。

完整生产成本：Code 778→18（−760），Harness 新原语 779 行，**系统净增 19**。这是职责接管及兼容成本，不是算法删除；原 C08 路径交集为空，仍缺 3,518 行。三视角及兼容边界见[终审](key-designs/private-journal-parent-binding-review.md#a53分段原语实际归属与兼容终审)。累计 Coding 减少 6,983 行，系统仍净增 1,344，原整体 Goal 未完成，未提交或发布。

## 原 Schema 字段声明的实际复用（A54）

51 处原 Schema 声明复用 dataclass 已有字段顺序，撤去 230 条重复字段声明。原 RecordSchema 增加 25 行加载期元数据准备；特殊标签、decoder／encoder、partial 参数和绑定类继续显式覆盖。记录所有方法及原 encode／decode／keys 的 AST 保持，14 张未选表仍用原构造，存量读取与数据校验不增加拒绝条件。采用边界和未来字段演进合同见[H-COD-KD-006](key-designs/record-field-metadata-convergence.md)。

最初同时改写序列化方法的 15 源候选系统反增 5 行，已拒绝且未接入。本片采用完整候选实算 Code／原 C08 六源 −54、Harness −177（含 helper +25）、系统 **−231**；原 before 独立格式化 +4，结构净减 235／格式净增 4，不把压行当算法删除。所有记录方法保持原样，减少的是重复字段声明及其结构。

20 份未改原源 SHA／canonical 路径守卫后，74961 **1 passed（2.43s）** 首次固定原 65 份编译元数据。此前 1143 因探针未支持既有 partial 失败，未输出预期，未改产品。候选冷加载 80257 **1 passed（2.58s）**、149 源 shadow mypy 通过；实际普通路径／无 overlay 的 76072 **1 passed（5.89s）**，全部字段序、wire key、label、转换函数与 bound class、partial 递归参数均与原冻结相同。

实际原 C08 字节／日志／业务和相关 Package 记录／事务组合 84073 **196 passed（46.63s）**，149 份实际显式生产源码联合 silent mypy 通过。一次性函数指纹证据仅留产品树外，没有新增永久指纹测试、测试路线或 PR gate；不累计重叠检查数量，也不扩大为原生 Windows、任意断电或默认全依赖图通过。A42 广依赖 237 错误／8 文件的记录仍保留。三视角实际复核见[专项评审](key-designs/record-field-metadata-convergence-review.md)。

累计 Code 138,805（−7,037），原 C08 7,235（−4,536，八千行仍差 3,464），系统仍 +1,113。整体 Goal 保持 active／incomplete，原完成条件不变，未提交或发布。


## 两种外部 Wheel 记录直接复用既有编解码（A55）

两种原 Wheel 绑定记录的字段、wire key、字典求值与构造参数顺序完全相同，原四个手写字段遍历方法直接改用已有 RecordSchema。原 exact dict／keys 检查、__post_init__、身份哈希、领域错误、Product 准入、catalog、Journal 及受控文件操作保留；Core 没有新增代码。与 A54 仅替换元数据不同，本片确实改写四个编解码方法；不能把 A54 的“全部记录方法 AST 不变”扩称到本片。除这四方法、新 import 与两声明外，两个完整模块 AST 相同。

完整成本：data 421→427（+6），dependency 537→509（−28），Coding／系统净减 **22 行**，Harness 0。原 before 单独 Ruff 格式化为 +30，因此结构减少 52／格式增加 30 分列。两文件属于全 Coding 扩围，不增加原 C08 减量。累计 Code −7,059、原 C08 −4,536／八千行缺口 3,464，系统仍 +1,091；独立全源核算包含未跟踪生产源，完整 Goal 未完成。

在改动前以原两个实际路径与 SHA 守卫，首次独占冻结旧结果；每类型 131 组观察包含有效记录、反序字典、shape／缺项／十类字段值、getter 中断与构造参数顺序。旧预期 SHA256 为 `cf496f17e672a8049d8c1b5c990553906e31f5b431dff23977729bb2e01626da`。实际普通 worktree 路径、无 overlay 的一次性回放 **1 passed（2.15s）**；getter／constructor spy 仅补充顺序观察，不代表 Product 权限。旧冻结为 1 passed（0.75s），不与回放相加为独立能力覆盖；预期与探针仅留产品树外，没有新增永久测试／gate。实际两源 silent mypy、Ruff／格式／diff 通过。全部 A54 241 路径仅选定两源码发生预期变化。

原三文件选择在 **51 passed／1 failed（840.44s）** 后 fail-fast：技能 preview 缺少 `local-review`，后续案例未执行。仅还原原两模块的受限对照，同一案例同断言失败（30.69s）；干净原主线 `8ad6b609`、普通主线 PYTHONPATH 再独立复现（16.21s），其测试文件与活树逐字相同，证明此失败早于整个重构 Goal，不冒称全量回归通过。此前未执行的 dependency Wheel／IO 兼容两文件另以实际源码补跑 **81 passed（42.49s）**；与前 51 分列，不将被截断选择写成三文件全绿。三视角实际代码审查无具体阻断；实施 owner 接受当前有界复用，保留干净原基线已存在的技能目录断言失败。详见[评审补证](key-designs/record-field-metadata-convergence-review.md#a55两种-wheel-记录的实际执行复用)。现有 RecordSchema 的 all-fields-wire 显式选择及未来版本／字段变化责任保持。Core 循环替代内联表达式产生的热路径调用成本没有基准，不冒称性能严格不变；原生 Windows／断电／默认全依赖图仍未证明。记录与原结果、before／实际 source、计数及评审保存在产品树外 direct-record-codec-a55，未提交或远程发布。


## Package 叶子值校验直接复用（A56 R3）

本片减少原共享层接管后的重复成本。19 个 Package 模块的 54 个叶子值校验定义按完整 AST 及真实依赖分为 11 组：只允许标准 builtins、同一 Mapping／cast 绑定，没有领域状态、间接 helper 或回调被带进共享函数。五份原 records 实现直接复用，六份确有不同合同的规范函数最小归入原 records owner；49 个原模块名称成为同对象导入别名，净退出 43 份重复函数定义。不是新建解析器、记录基类或模式引擎，RecordSchema、记录类、构造、from_dict／to_dict 及原调用顺序均保持 AST。

Mapping 与 dict、浅复制与原引用、整数／bool／子类、检查顺序、字符串非空与错误类型／文案按原合同分组，不把同名当作等价。原私有名称和调用参数保持，真实 helper 的定义模块／函数名／traceback 随 owner 调整，旧函数 pickle 引用经旧名解析；不承诺旧发行版读取新私有路径生成的 pickle。原 JSON／ID／hash 算法、存储与文件授权不变。

原 R1 拟把 42 处 `_exact_dict`→decode 组合统一。候选行为重放发现各模块同名 helper 的真实合同不同，R1 已拒绝且未进入产品；三份较早静态意见不足以证明行为等价。其原源码、失败结果和报告保留。另一带函数参数的 R2 原型亦未采用；R3 按实际函数体与依赖直接复用，没有新增 decode_object 或回调入口。此前漏核函数绑定的问题由原行为观察发现，并经修订、重新三视角评审及实际回归关闭，不能冒称 R1 从未失败。

改动前在原 19 源 SHA／规范路径和原函数 module／首行守卫后，首次独占冻结 54 个函数的 1,134 组观察、原签名及旧 pickle；候选与实际分别对照这些原结果和此前不变的 42 种记录 756 组观察。实际正常工作树无覆盖层回放 **1 passed（3.40s）**；原记录／事务组合 **217 passed（16.55s）**，涵盖 Package、一个真实 settlement 恢复案例及原 C08 记录边界；19 显式源码实际 silent mypy 通过。观察、有效记录与事务各有范围，不叠加为独立能力数，也不推导原生 Windows、断电、默认全依赖图或整个 Goal 已通过。

三视角候选和实际代码复核均无本增量阻断；终态由实施 owner 补录，原 reviewer 写作时 pending 的记录保留。完整证据见[专项补证](key-designs/record-field-metadata-convergence-review.md#a56-r3叶子值校验直接复用)。19 源全成本净减 **132 行**（records +36，其余合计 −168）；结构 −143／原 before 排版 +11，Coding／原 C08 本片均为 0。独立全源核算为 Code 138,783／累计 −7,059，C08 7,235／距八千行差 3,464，系统仍 +959，完整 Goal 未完成。没有新增永久测试／指纹门禁、模型调用、平台或远程发布。


## 既有等待原语的两个 Coding 消费者（A57）

[原 KD004](key-designs/owned-task-join-convergence.md) 的三种等待算法已交付，本片只追加两个真实消费者，不重写算法或追溯扩大原排除 void 的接受范围。AppHost 构造失败仍创建一次原 settlement Task，关闭 catalog 后再关闭 product factory、累计失败并抛原领域错误；重复等待循环改用既有公开 `Harness Runtime.await_owned_task` 的私有别名。Hosted Continuity 保留 `_join_void` 名字/签名和明确丢弃成功值的薄适配，调用原已导入的 preserving-cancellation 原语。真实 producer 均只有 None 或 raise，三类取消政策未强合；任务持有、重试、清理债及资源权威仍归原 Coding owner。

两处旧循环已删除，Coding／系统实际净减 **22 行**，Harness/Foundation 零新增。583+296→568+289，结构−21、原文件独立格式整理−1；原31文件C08本片无变化。四历史流读取另做完整候选，只能 Coding−45/Harness+42/系统−3 且需回调适配，未采用；不将其收益提前入账。

改前按实际 source SHA/规范路径固定40项真实Task观察，expected未改。旧普通路径复放1 passed（2.37s），双模块候选overlay 1 passed（5.95s），实际普通路径无overlay 1 passed（8.34s）。原两个完整业务测试文件 **22 passed（19.08s）**；实际两个显式源 silent mypy、Ruff/format与源指纹通过。三视角分别完成候选与实际代码复核，无本片阻断，实施owner接受有界追加；评审报告写作时pending保留，真实终态独立补于[KD004评审记录](key-designs/owned-task-join-convergence-review.md)。

40观察不穷尽uncancel/同到调度，惰性关闭口不证明真实权限；首次freeze终态因输出截断不可用，不能以存在文件推导成功，旧路径复放另有可追溯终态。原A42默认广依赖237错误/8文件未关闭，窄类型通过不抵销；A55已在完整干净原main复现的skill断言失败未修复，本片未重复无关验证。全Coding累计减少7,081行，全生产仍净增937行；原C08距8,000仍差3,464行，整个Goal继续active/partial。


## 整项改动的类型依赖归因（A58）

本轮未改产品源码、测试或fixture，数量维持A57；进展是完成此前未能归因的类型依赖核实，避免把共享venv的静默行为或窄检查当作全面通过。

首次实际两过期Journal入口默认依赖展开为234错/7文件，而干净原main相同两入口0错。这个比较不等价：mypy1.20.0把共享venv中的editable main视为已安装包，自动静默其依赖；实际worktree依赖不受相同静默。源码与cache元数据中的ignore_all差异已核实，没有修改mypy、依赖、配置或用ignore设置隐藏错误。两边同加`--no-silence-site-packages`后，原main883错/74文件、实际880错/73文件；其中project237→234，第三方646相同。

两入口cache只覆盖127/151个已改生产Python文件，故进一步显式检查全部151；原main对应存在128路径，23个新源码在原提交不存在，不虚构同数基线。最终结果：

| 选择 | 完整结果 | 边界 |
| --- | --- | --- |
| 实际151个改动源 | **918 errors/78 files，exit 1，97.73s** | 所有151显式源SHA及cache ignore_all=False核对，自身0错误；不是整条命令通过 |
| 原main对应128源 | **921 errors/79 files，exit 1，88.11s** | 原提交8ad6b609，main前后干净；另23个新文件无原路径 |
| 完整结构化错误差分 | **新增0、删除3** | 原始ErrorTuple保留完整消息、起止位置、code、severity和多重性，仅归一相同checkout/venv路径前缀；cache计数必须等于CLI |

实际依赖中的272个project错误分布于12个源码，均逐字等于main与原Git对象；原main同范围275错。第三方646项相同。删除的三项均为`package_source_snapshot.py`原object上的stat/open注解问题，与A52已交付类型修正对应。没有为消除原Agent、Work、CLI或第三方错误改本次业务代码、安装新依赖或放宽检查。

旧A42原逐项输出缺失，未声称重建其历史237项；A58提供当前完整改动范围与真实原提交的可复核对照。现有错误仍未修复、默认未检查的无注解函数体也不因此获证；不能把这个归因当整仓严格类型、功能/授权、取消、原生平台或完整Goal验收。六个检查进程终态均已回收，补齐范围后串行执行，未增加CI门禁或重复无源变化的pytest。独立证据复核与实际终态另补于[交付记录](private-data-convergence-delivery.md)。

同期写循环外置候选仅在7模块中选出11处可直接复用，结构−17而格式整理+56，整体+39，未采用；没有产品变更或运行接受，不计净减。目录准备的现成组件只创建缺失级，不等价于Coding对既有目录的权限收紧与身份后验，也没有强行替换。上述有界分析不证明全层已无重复或原8K不可能。全Coding累计−7,081、原C08缺口3,464、系统仍+937，整体Goal继续active/partial。


## Continuity 完整路由差异补证与子系统归位（A60）

本轮源/数量没有变化。[KD003](key-designs/continuity-bytes-import-convergence.md)补齐真实ProductSessionRuntime链的旧profile观察后，已确认不能用单一frozen importer概括非owned持久文件导入、临时JSONL及ZIP导入的不同接受/附件/rollback/cwd语义。原普通路径成功、missing health、before-hook目标复制和ZIP fallback既有副作用分列；候选仍draft/not-started，完整干差分/成本未成立，不先实现owned-only或伪造统一撤销。

用户明确新增“不得将共享实现放在Harness根目录”的放置约束，已写入[实施Goal](coding-private-data-implementation-goal.md)。151改动源中的23个新增生产源码逐项检查，Harness根目录新增实现为0；当前分别归Foundation、Journal、Plugin Management、Resources/Packages、Session与Worker。位置正确不等于算法复用充分，原owner复用、窄端口、无反向依赖及删除旧体仍必须逐项证明。累计Code−7,081、原C08−4,536/缺口3,464、系统+937保持，整体Goal未完成。

## Windows 日志旧测试转发层退役（A61）

沿 R3 删除与接管同时完成的要求，三个 Coding 日志模块移除五个仅被测试引用、未公开导出的转发函数：Windows deletion/restore 各自的 `_decode_event` 与 `_validate_sequence`，以及 Windows expiry 的 `_validate_sequence`。生产 transaction 早已调用原 Harness Plugin Management 的实现；此次不改它们的生产方法，也不新增桥接、执行路线或实现文件。

四个现有测试文件直接调用相同的原 Harness callee，显式传入旧 record 类型、owner_id、label 和 receipt_id。逆转此调用重定向后，四测试的非 import AST 与修改前完全相同，全部断言、异常负例与固定 expected 保留。三个生产源除退出的五个函数及 unused import 外，所有类、方法、公开导出和配置 AST 相同；其他148个已改生产源以及原防护中的239项 source/test/fixture SHA 均保持。

同四份完整原测试修改前 **15 passed（4.16s）**、修改后 **15 passed（4.19s）**，不合计覆盖数量；三个显式源码的 silent-import mypy、七文件 Ruff/format 与 diff 检查通过。它们是便携 Windows 逻辑验证，不是 native Windows、整个仓库或全依赖检查通过。本片三视角代码评审及接受结果见[交付记录](private-data-convergence-delivery.md)。

Coding、原 C08 和系统各净减 **40行**，Harness 新增 **0**。重新按原 Git 对象、多语言四根目录及全部未提交源核算：全 Coding −7,121，原 C08 −4,576/缺口3,424，全生产仍 **+897**。初始仅统计 Python 的辅助输出与原完整口径不同，已保留并显式纠正，不用于 Goal 数量。该片退役五个适配，不称为删掉五套日志算法，不代替后续大额收敛或原 Goal 完成条件。

## 候选成本复核与原业务组合回归（A62–A64）

当前生产源码仍为A61，本轮净变0。按模块解析相对／绝对import、别名及可识别属性链，检查当前1,812个Python源、427个Coding模块，未发现可批量退役的大顶层私有函数池。五个静态候选包含三个Python隐式消费的模块回调，不能删除；另两项共17行函数体仅待人工核实，不计减量。另八组体长至少12行的字面同形声明也含接口签名，不能当八套相同算法。上述有界扫描不证明没有语义重复或8K目标不可达。

四个Worker legacy分段历史循环的外置完整替代稿，计入全部适配及原Worker组件新增、按产品Ruff配置核算，Coding−45／Harness+41／系统仅−4。收益不足以引入新的解码、校验与错误回调接口，未采用、未安装、未作类型／运行接受，不计削减。原V2、存储和Product代码保持。

为核实较晚收敛后完整入口及失败恢复的组合行为，实际执行21份原私有数据／安装根完整测试文件：**78 passed（352.86s）**。使用原managed wrapper、实际worktree绝对PYTHONPATH、磁盘runtime、沙箱外、`not live`和`skip-host-runtime`。测试前后1,812个生产Python源、21份测试及A61原246个source/test/fixture守卫一致，未改断言或expected。没有重复模型试验或新增gate。

原CLI生命周期测试的三组参数分别走CLI、CLI含过期、SDK含过期；另有缺锁不补锁、partial状态不修复、workspace替换拒绝及started动作恢复等独立测试。Windows文件验证的是Linux上的原便携逻辑／mock端口，不能据78项通过声称nativeWindows或所有故障时序通过。21份文件的结果不替代整仓测试、A58广依赖错误修复、职责收敛或数量验收；三视角验证证据复核见[交付记录](private-data-convergence-delivery.md)。完整Goal仍active/partial，原C08缺口3,424、全系统+897保持。

## Continuity 新补事实与完整残留复核（A65–A66）

本轮生产源码净变0，未采用新替代。检查原接收层时，动作Journal的外锁仍覆盖领域阶段判定与append；不能把有意复用的存储组合当成可随意删除的重复锁或另增通用动作引擎。

[KD003](key-designs/continuity-bytes-import-convergence.md)补两项原事实：自定义FileCopy及VerifiedFileCopy确实参与非owned持久输入，保留真实Path、原拒绝及verified优先级；非持久JSONL的公开文件／当前runtime引用则可能仍指向bridge已清理的临时Path。真实原组件四次观察最终1 passed（2.21s），三成功加一次预期拒绝；九实际模块路径／SHA与同一输入另存。新bytes方案不能静默绕过端口或把引用变更当成已经等价，仍无完整替代成本／新接受，继续draft/not-started。

为避免反复做微型适配抽取，重新冻结原C08全部31文件、7,195行的当前声明与原接收组件，启动职责／复用、运行／失败、数据／兼容三个独立架构缺口审查。审查要给出成段旧体退出与全部接收／配置／兼容成本，不以同形函数池、目录搬迁或更严格拒绝记收益；不是重复A64日志复核，也不是已接受新架构或实现。原C08距8K缺3,424、系统+897及重要工作件用户评审边界均保持。

三份独立审查现已完成。它们确认树处理、Journal、物理恢复及过期执行已有实际复用，也指出根代际、恢复事实查询和读取装配尚未完全收敛；目前没有证明一个可直接落地、全成本净减数百行的剩余切片。Windows归档已删除后的恢复查证不能直接套用仍要求归档存在的普通恢复入口；两平台status的锁、读取和异常边界也不能强合。这些是后续替代必须保留的合同，不是新运行故障，也不证明原目标不可达。本轮仅接受这些有界审查发现，没有接受或实施新方案。

后续实现仍遵守[Goal的子系统归位约束](coding-private-data-implementation-goal.md#必须满足的架构约束)：Journal、Transcript、Session、Resources、Plugin Management、Worker各自承接本职责，必要扩充回原owner；不向Harness根目录或跨领域杂项包集中实现。当前22个新增Harness源码均在子系统内，根目录新增为0。Coding退出量与共享层接收成本继续分账，不把搬迁记为重复算法删除。

## 既有 Epoch 工作流的重开查证去重（A67）

POSIX与Windows的`reopen_fenced`原有两份94行流程。两者早已共用`_PackageEpochCutoverWorkflow`，Windows Request／Switch／Result也已经是POSIX记录的类型别名。本片将共同的输入检查、记录重建、两轮根身份查证及最终Journal重查归回原Resources/Packages工作流；两个公开静态入口保留原签名、平台准入和具体owner派发。句柄打开、原生身份、错误与平台拒绝仍由各后端负责，没有新增组件、记录、锁、线程或根目录模块。

两份旧业务体退出为一份，完整成本POSIX+23／Windows−71，系统净减**48行**；Coding及原C08均为0，不以这48行填补原8K目标。按原Git对象和原四根目录／多语言口径重新核算，全系统仍+849，原C08仍差3,424。247个最新source/test/fixture守卫一致，A64冻结的1,812个Python源中只有这两个目标源发生变化。

原50项流程观察先冻结为1 passed（0.65s），原真实POSIX替换／恢复观察1 passed（0.77s）；实际普通工作树对照与真实POSIX观察合计**2 passed（1.63s）**，输入和expected未改，实际模块路径／SHA与评审稿一致。原三份完整Epoch/Coding快照业务文件**34 passed、18 skipped（38.50s）**；跳过为Windows原生合同，Linux惰性端口对照也不证明Windows ACL／reparse／句柄／断电行为。类型检查为两个完整候选源的silent-import shadow检查，实际安装与候选逐字相同；不冒称默认全依赖检查通过。

首次mypy缓存写入触发配额错误；关闭缓存写入后通过。首次安装命令因沙箱挂载配额未启动，紧随其后的2 passed仍使用旧源码，已另存且不作为候选证据。仅清理本轮已终止进程的临时缓存后，按原源指纹重新安装，并重新验证实际模块；没有修改Product来绕过环境错误。原模块私有global热重绑与既有类native端口绑定并非任意等价；实际故障观察同时命中原模块及接收类端口，公开合同保持，私有动态替换边界明确保留。三视角实际代码复核的最终结论见[交付记录](private-data-convergence-delivery.md)。本片不是整个PD切片或完整Goal完成。

## Legacy Source Catalog 直接复用既有组件（A68）

原Catalog仍包含一份Wheel暂存／短写／硬链接发布／落盘／清理流程。现有受控Source IO已经被data、dependency、worker三类Wheel使用，本片将Catalog接为第四类真实消费者，删除本地发布操作体；原公开入口的批准、epoch、目录、锁、摘要、真实来源及事后验证保留。记录的十八个共同wire字段改用既有RecordSchema遍历，V1省略resourceKind、V2/V3按原判据追加、原构造／跨字段校验／ID及错误包装仍归Coding。Schema只在导入时编译；不新建codec、版本引擎或共享运行组件。

完整源码741→675，Coding／系统净减**66行**，Harness零新增，没有新增文件或根目录实现。新imports、Schema及全部薄适配已计入成本；不是把代码迁入共享层。该文件属于全Coding扩围，原C08仍为7,195行、距8K差3,424；全系统仍+783，整个Goal未完成。

原代码先冻结755项记录观察及15项真实POSIX文件发布观察，原冻结**2 passed（4.03s）**；实际普通工作树对照**2 passed（2.33s）**，固定输入／expected与实际模块SHA均核对。记录观察包含V1/V2/V3、逐字段负例、精确dict准入及公开子类的getter／构造参数顺序；发布观察包含短写／零写、预存stage／target和单点故障后的bytes／mode／link count／操作顺序。两轮不累计成更多覆盖，不证明任意并发、双失败、Windows或断电行为。

原Catalog、真实Source发布后策略重开、安装清单三份完整业务文件**40 passed（79.60s）**，无跳过／失败；原测试、断言和预期未改。单显式候选源silent-import shadow类型检查通过，实际源码与候选逐字相同；不是全依赖检查绿。原有artifact读取及独立duplicate-key查验合同保留，没有为减少代码强合。三个独立视角的实际代码评审无本片阻断，限定接受见[交付记录](private-data-convergence-delivery.md)。

私有发布helper由原frozen候选读取两次filename改为消费一次确定值；真实生产者提供稳定string，公开类型／摘要／epoch准入不收紧。不承诺恶意可变伪候选、强改冻结字段或旧模块私有OS热替换的逐次行为全等；探针注入真正接收组件，未靠失效注入换绿。记录公开getter和构造顺序则已明确保留。元数据遍历有循环、调用和临时dict成本，未作基准，不声称性能提升；未来字段变化仍须显式保持旧版本wire合同。

## 原C08归档删除后恢复查证的完整成本试算（A69）

本轮回到原C08，对Windows普通恢复与归档已删除后的过期重试完成两份整模块替代稿。尝试在既有Restore transaction中共用native捕获，保留原Desired／删除／confirmation政策和两种查证合同：普通路径仍核归档，过期重试允许归档缺席；一次names set与两次条件读取、parent／debt错误边界分别保留。

按产品Ruff配置计算全部参数、分支、适配及imports：原Core 862→930（+68），C08 recovery 152→99（−53），全生产**增加15行**。该原型未安装、不计减量，当前实际源码仍A68。它补充了A66的粗略预算，不能以Code少53行就称精简；后续需要整个单元的可证净收益，不能继续拆成小包装计数。

候选仅完成外置完整源码与Ruff检查，未作类型／运行／三视角接受。新增方法对原structural测试接缝、值读取时点及错误／cause的影响尚未证明，不借A68评审或测试结果为其背书。本轮247项最新source/test/fixture守卫一致，生产源码／测试／expected零变化，未重复Product回归。此结果只拒绝当前候选，不证明8K不可达，不改变原目标；C08仍差3,424行，全系统仍+783，Goal继续active/partial。

## 旧安装评审记录直接复用原字段遍历（A71 R2）

A70三处计划构造的外置稿，物理净减70行中44行来自原文件格式整理，结构仅减26行且需要三类回调，未采用、未安装、不计收益。上一轮只确认目录约束，没有推进代码；本轮转向直接消费既有组件。

Local、Builtin、Removed Entry和Removed Set四记录的连续标量字段改调原Resources/Packages RecordSchema，删除重复keys/identity/构造映射。三完整Coding源1694→1633，系统／Coding净减**61行**：结构59、原格式2；Builtin单源增加2行也已计入。Harness零新增、根目录零新增、无新模块。嵌套列表、版本、可选项、原guard/try/cause及审批/hash保留；未采用将嵌套转换移入Schema的R1候选。

未改源先冻结**1,637项观察**，原普通路径1 passed（3.41s）；实际普通工作树无overlay对照1 passed（3.51s），固定输入／expected未改，三模块actors指纹核对。观察包括wire/canonical、缺失／错值／组合优先级及公开子类getter/kwargs顺序，不是1,637个独立pytest场景或全部输入证明。三完整shadow源silent-import mypy通过，实际源码同字节；Ruff/format通过，不称广依赖全绿。

三视角实际代码评审均无具体阻断。两个原完整迁移业务文件最终**157 passed（1364.16s／22分44秒）**，无跳过或失败；两文件与原Git对象逐字相同，原断言未改，未增加测试路线或gate。测试范围是旧安装清单与完整离线迁移CLI，不能称全仓或native Windows通过。250项source/test/fixture守卫一致，实际源在记录对照、评审与业务回归后未再修改。

实际评审frame SHA256为`2c5c50dee5d63c2d5c365febe0aa9cbee017154751fc03325e2aba007a3bbd34`；评审稿里的业务pending保持历史，真实终态单独保存，SHA256为`ee809ed734c4d5fe11666006b827f1f9eb11b1779ff26abf3439ea41aac965bf`。实施owner据原授权接受本片直接复用，不代替用户接受新架构或整个Goal。静态Schema新增字段仍须显式核对旧wire/version；循环／临时dict成本未作基准。累计全Coding−7,248、原C08仍差3,424、全系统仍+722，完整Goal未完成。


## Windows Worker provisioning 日志归属与 IO 复用（A72 R2）

完整 provisioning Journal、CAS 和库存读取的中性实现归入原 [Harness Worker 内部模块](../../../../src/loushang/harness/worker/_windows_provisioning_journal.py)。Coding 保留五个公开与三个既有私有消费者的同对象兼容导出；Product 的选择、epoch／GC、根目录和启动批准仍由原 owner 负责。物理文件操作直接复用原 Resources 的 WindowsJournalFileIO，没有复制另一套读写器、日志引擎或根目录模块。

| 本片生产源码 | 原行数 | 实际行数 | 净变化 |
| --- | ---: | ---: | ---: |
| Coding 原模块 | 759 | 37 | −722 |
| Harness Worker 接收实现 | 0 | 636 | +636 |
| 原 Resources 文件适配 | 243 | 261 | +18 |
| Hosting 材料清单 | 299 | 299 | 0 |
| 合计 | 1,301 | 1,233 | **−68** |

接收成本全部计入，实际结构净减68行；Code退出722行主要是职责接管，不称为删除722行重复算法。原 JSON／canonical／身份／限额和 CAS、回放合同保持。新 consumer 在元数据之后检查 lock stream，保留原错误顺序；现有五日志继续原缺省顺序。append 在同次重读观察上执行原历史解码，再定位写入；不以简单 bytes 比较替换 corrupt／changed 优先级。任一 native 提交异常仍设置原同 owner 的 uncertain 围栏，读回成功不构成继续提交的授权。

两项明确修复与兼容保持分开：原单次写可能短写或零写仍返回成功，现复用原完整写入原语；原 fdopen 构造失败可能泄漏 FD，现复用原借用 wrapper／唯一 raw FD owner。真实 POSIX FD 故障验证覆盖构造前、构造后关闭再抛错、foreign FD 复用；Windows ACL／stream／flush 端口仍为模拟，未作原生 Windows 验收。旧 DTO／错误／_Record pickle 可解析，不承诺活 Journal owner pickle、任意私有 globals 热改写或旧发行版读取新 owner 模块名。

验证及范围：

- 初版种子0644导致旧准入提前拒绝，不能证明其标签所称 CAS／库存分支；原失败材料保留。Product未改时按0600与显式分支断言重新冻结有效旧预期，原输入／旧pickle未改。实际普通工作树专项 **6 passed（17.52s）**，覆盖修正合同、故障修复、旧pickle和真实Wheel；不是每项内部观察一个独立业务测试。
- 原业务组合 **309 passed、2 native skipped、1架构清单失败（22.65s）**；失败是漏登记A53已交付的分段历史兼容入口。只补原C50／C54事实清单，原谓词和断言保留，两个完整架构文件随后 **16 passed（22.94s）**。保留初次非零结果，不将两轮数量相加或称初轮全绿。
- 实际四源silent-import mypy **exit0（29.78s）**。早先89119句柄的终态输出已不可得，不追认该次通过；上述结果由独立有记录的重查取得。A58广依赖非零、native与全仓限制不关闭。
- 真实Wheel经既有PEP517 backend离线构建，实际四源成员、兼容导出和原RECORD篡改拒绝均验证；critical仍八项，引用实际Worker body而非空兼容壳。旧审批不授权新镜像，未开放平台、模型调用、网络或CI gate。

实际评审frame SHA256为`4aebec637810bdefaf82f68c759396281818e2fd8e139772f9b135faceb180fc`；三视角最终结果与实施接受单独记入[交付记录](private-data-convergence-delivery.md)。256项source/test/fixture守卫匹配；新增Harness模块都在原子系统，根目录新增实现为0。累计全Coding−7,970，原C08仍差3,424，全生产仍+654；完整Goal保持active／incomplete。


## Package 恢复请求直接复用原字段遍历（A73）

原Resources/Packages的Restart、Rebind、PinnedAdoption、StagingAdoption四请求，仍各自重复完整字段键集、identity dict与from_dict标量遍历。本片在原[记录模块](../../../../src/loushang/harness/resources/packages/plugin_lifecycle/records.py)内直接调用已经使用的RecordSchema，删除八份旧遍历主体；四份静态表包含43项原字段/decoder/label，没有新Schema API、运行组件、IO或根目录模块。原类型/公开构造、Mapping接受与浅复制、__post_init__、版本、hash域/计算ID及后验比较保持。表顺序同时等于原getter和cls关键字参数顺序，positive/nonnegative与各自错误label不合并。

整模块2,107→1,968，Harness／系统净减**139行**，格式0；Coding及原C08为0。这是原接收组件消除重复，没有搬迁或把声明成本排除。除四个_identity_dict、四个from_dict及四份新表外，整个原模块AST一致。私有_wire helper改为沿原Schema在加载时绑定，不承诺任意运行时热替换；公开子类getter／构造参数顺序有原观察对照。新循环/getattr/临时dict成本未作性能基准，不声称更快。

原模块未改时exclusive冻结682项观察，原冻结1 passed（0.60s），候选对照1 passed（0.55s）；实际普通路径、无overlay对照**1 passed（1.11s）**，预期未改且实际actor为新源码SHA。它覆盖有效wire/canonical/ID、字段错误与相邻双错优先级、公开子类getter/kwargs；不是682个独立业务测试，也不穷尽任意Mapping回调。完整单源shadow窄mypy通过，实际源与候选逐字相同；Ruff/format通过，广依赖限制不改变。

原五文件选择初轮为**19 passed、1 failed（19.78s）**，在插件装配期待review skill而只见standard处停止；仅加载本次改动前原记录模块的同一node也**1 failed（18.25s）**，核对了原actor路径与SHA。该对照只定位本次记录改动不是新增原因，不冒称整个干净main或全组通过。其余四份尚未运行的完整生命周期／重绑定／阶段日志／adoption事务文件，实际普通源码最终**102 passed（42.35s）**，无跳过/失败；五测试文件全部与原Git逐字一致，原失败与断言均保留。

三视角实际代码评审及有界技术接受见[交付记录](private-data-convergence-delivery.md)。实际frame SHA256 `d348329b12c6acf82dc17ffd1115d0569ed768461dc4f20b2b22b06f4c54add1`，业务终态独立保存，SHA256 `d6713e0067f6de584b5a5451329b5d9c44480a737daaea3ea8134f75c69f5279`，不覆写原pending。累计全Coding仍−7,970，原C08仍差3,424，全生产仍+515；完整Goal未完成，未提交或发布，未新增模型调用、平台或gate。


## 四种恢复记录的共同封装复用（A74）

同一Resources/Packages记录owner继续复用原RecordSchema，将Restart/Rebind/PinnedAdoption/StagingAdoption四Record的七共同wire字段和重复键集声明归为一份静态表。表只用于encode/keys，不是完整decoder；原Mapping复制、request预解码与v2要求、字段decoder／构造、ID／授权及supersession分支保持原处，request/status仍按原getter顺序动态调用实例to_dict。原Schema runtime零扩充，无新模块或根目录实现；整模块1,968→1,924，系统／Harness净减**44行**，格式0，Coding／原C08为0。

原完整阶段日志21 passed（2.00s），外置只观察wrapper原样返回结果，记录16份有效DTO并选六种kind（含两类supersession）作固定输入；原源未改时独占冻结642项观察。实际普通路径对照1 passed（1.61s），四原完整生命周期业务文件**102 passed（32.64s）**，无跳过／失败，测试与原Git逐字相同。单完整候选源shadow窄mypy及实际Ruff/format通过，actual与候选逐字相同；旧A73 adversarial技能断言未重跑或宣称修复。

本片沿用原已接受Schema关系，由实施owner完成同组件有界设计核查，再进行三份独立实际代码评审，不声称另做三份独立候选设计审查。三视角无本片剩余阻断，实施owner在原授权内有界接受；frame SHA256 `2cded92235ec891cdf7ccf92b78ee25bdfd174ef30404b23ccbf17ccbb67afd8`，详细成本、证据和局限见[交付记录](private-data-convergence-delivery.md)。表不自动演进版本，不承诺私有热替换或性能提升。261项守卫一致；累计Code仍−7,970、原C08仍差3,424、全生产仍+471，完整Goal未完成，未提交／发布或新增gate／平台／模型。


## LSP／Arch 领域查询契约归一（A75）

直接Tool与Provider各自声明了相同的领域Protocol。LSP原公共InspectSymbolRuntime整类AST归入已有[ports](../../../../src/loushang/coding/lsp/ports.py)，tools保留同对象旧名导出；LSP／Arch两个exact-version私有Provider名称改为原领域契约别名。Arch契约仍在原tool，Provider原先已依赖其输入类型／校验；LSP选择ports避免Provider依赖具体Tools实现。领域契约留Coding，Harness零扩充、无新模块；四源其余运行主体／DTO／limits／授权／取消／资源寿命AST保持。

兼容边界明确：public LSP的真实定义module从tools变为ports；两私有Provider Protocol不再拥有独立类身份／name／module／doc／可变type元数据。保留四个旧import出口、原签名／resolved模型类型／async与Protocol行为以及旧class/method pickle前向解析；不承诺元信息全等、第三方私有注册／热改隔离或旧发行版读取新ports路径pickle。不设置伪__module__隐藏真实归属，运行准入仍检查原concrete View／owner，而非通过Protocol身份授权。

四完整源1,926→1,889，Coding／系统净减**37行**，包括ports接收28行；结构−42、原格式+5均计入。收益是声明去重，不称查询算法减少或性能提升。修改前独占冻结旧四出口与十份class/method pickle；实际普通源码接口对照1 passed（13.07s），两种冷进程导入顺序通过，四actor均为工作树路径／新SHA。原五完整直接Tool／Provider／generation／fake-LSP业务**69 passed（84.03s）**，无跳过／失败，五测试与原Git逐字相同。四完整候选shadow源窄mypy及实际Ruff／format通过，actual逐字等候选；不是广依赖或真实LSP／模型／全平台证明。

三视角实际代码审查无本片剩余阻断，实施owner在原扩围授权内有界接受，不冒称另做三份新设计审查或用户接受新架构。frame SHA256 `e7cbe6491a3e9010a511ed91a7c4b16f12c4c3ea08e4bf98df5c620fe126d2d3`，270项source/test/fixture守卫一致，原A73技能断言未宣称修复。全Coding累计−8,007仅是扩围指标，**不抵扣原C08仍差3,424**；系统仍+434，完整Goal未完成。用户对扩围后8K验收范围的澄清尚待答复，在明确答复前维持原C08独立条件。未提交／发布或新增gate／平台／网络／模型。


## Plugin Management 持久记录读取归一（A77）

原六个 Plugin Management 记录模块的29种 `from_dict`，完整复用既有 Resources/Packages `RecordSchema.for_dataclass/decode`。原 owner 保留严格 JSON 投影、字段/版本/判别检查、异常翻译、构造与跨字段不变量；预解析值只写原 Foundation 产生的独占副本，成员解码仍在原构造字段位置。全部 `to_dict`、公开签名、ID/hash、Journal/IO与授权不变；原 Schema API/算法零扩充，无新源码模块或 Harness 根目录实现。六完整源5,902→5,644，净减258，其中结构211、原格式47；operations增长11、retirement增长1均已计入，Coding/C08为0。

修改前六原完整组件测试94 passed，外置观察器原样返回旧结果，采集29类型79份有效wire；冻结8,720项输出、错误/显式cause、优先级、输入不变及子类构造顺序。候选和实际普通路径均匹配同一预期；实际八完整业务文件113 passed/无跳过失败（29.44s）。其中六组件与core删除测试等于原Git字节，Coding backup包含前片已接受的兼容案例且受原守卫保护，本片没有改测试或断言。六完整候选源窄silent-import mypy通过，实际逐字相同；不是全依赖图证明。

三视角独立实际代码评审无本片阻断，由实施owner在原授权内有界接受；parent同组件设计核查不冒称另做三份独立设计评审。实际frame SHA256 `a50eeec05afc7e5aef850f15668aaa479752ac5b8d50473e75f01df94f63718e`，接受记录SHA256 `88fdddd9602a745e7fe35ac2d0797b125917687c5e058d78c73a481b707cce7e`。表在import时编译，部分嵌套decoder静态绑定；不承诺私有热替换等价，未来dataclass新增辅助字段不能自动视为wire兼容。A77一次性本机纯解码样本中位2.4528→2.6021s、区间重叠，记录真实遍历成本，不称性能提升、精确产品回归率或后续A78性能证明。A76仅净减4行的外置候选未采用、不入账。


## 持久记录共同受理归原记录owner（A78）

同六模块的29个入口进一步复用原[records](../../../../src/loushang/harness/plugin_management/records.py)内部 `_record_document`，退役六套 `_wire_object/_wire_exact_fields/_wire_version`。共用原 Foundation JSON投影和既有Schema keys，单份执行“对象→精确字段→版本”受理；各领域仅通过六个窄partial适配给出原错误函数和每次新建的版本异常，记录给原label、schema、版本常量与字段。它不拥有Product/Session、状态、IO或动作；其余字段decoder、serde、构造、异常catch及业务保持。新增依赖仍指向原底层记录owner，没有新组件、公共API或根目录模块。

六完整源5,644→5,495，净减149，格式0；包含全部接收函数/适配/import，Coding/C08为0。直接复用A77修改前的79份wire与8,720项固定预期，未用新构造器生成期望。候选与实际普通路径对照通过；实际同八完整业务文件113 passed/无跳过失败（28.23s），所有测试与本片修改前逐字相同。六完整候选源窄mypy通过且实际同字节，实际Ruff/format/diff及281项守卫一致。

本片三视角独立实际代码评审无剩余阻断，实施owner在原授权内有界接受；接受SHA256 `0e3fd76405ee1580b30528948d5d447b6a33fcd5b6489c0e0eaf66dcc5358908`。实际frame SHA256 `a7b89af60f968267461a05f9bf6f4f7753ad4d9f72d71790a1192766ac879256`，独立业务终态SHA256 `e4ec10f9701c2753cc0902934992c173910c62dbd392aaf8c12cd0d1afefc7e7`；旧pending frame不覆写。私有helper直接导入/运行中重绑及traceback栈帧不承诺原样，公开错误类/code/消息/显式cause和准入顺序保持；不作新平台或性能承诺。

A77/A78合计净减407（结构360/格式47），同一组29模型不重复计为58种；当前全生产634,847，相对原基线仍+27。全Coding仍137,835/累计−8,007，原C08仍7,195/累计−4,576、距8K差3,424。完整Goal继续active/incomplete，原C08独立验收线与范围澄清待答复状态保持。未提交或远程发布，无新gate、网络、模型或Native Windows证明。


## 持久记录空值解码收尾与当前场景复核（A79）

三个原Plugin Management模块的14处调用直接复用既有 `RecordSchema.decode_nullable(value, decoder=...)`，删除三份相同空值分支和无用私有TypeVar；原语/API不扩充，不增加包装、模块或根目录实现。原value与callback属性仍各求值一次、按原顺序先于None判断，非None仅调用一次，异常不重译；逆还原14处调用后其余三整模块AST相同。完整3,215→3,186，净减29、格式0，Coding/C08为0。

原A77输入与8,720项预期逐字复用，候选和实际普通路径均通过，实际六actor指向工作树当前SHA。三完整候选shadow源窄silent-import mypy通过，actual逐字一致；不等于默认全依赖检查。三视角独立实际代码审查及终态补核无本片剩余阻断，旧pending报告保留，实施owner有界接受；接受SHA256 `35c4b4b5278f6823452bdae20c6100f47abab3e4cecb93ed7b7088150323ff26`，frame SHA256 `d0cf5c63988b9b44650f07474c98ac3b4abe470e175a4d88df45044593c55345`。原私有helper直接导入/反射、traceback位置与任意热替换不承诺不变，公开类/签名、字段/版本/错误、serde/ID、IO/权限保持。

共享记录路径改变后，按R3原合同补核当前组合：原A64的21份完整C08文件（path/SHA全部相同）与七份不重叠组件文件，**179 passed/无skip/fail（368.84s）**；原四份Package生命周期文件**102 passed（33.95s）**；既有旧记录/Journal优先级及JSONL三文件**41 passed（2.55s）**。三批分别记录，不把静态声明数、8,720观察或历史通过累计为覆盖率；28文件中20份等HEAD原字节，八份保留前片已接受兼容/seam变化，本片测试/断言零改。Package原已归因的A73 adversarial技能断言未宣称修复，Windows仍只提供原便携逻辑证据，不代替native ACL/stream/reparse/flush证明；没有新增矩阵、gate或模型试验。

294项当前源码/测试/fixture守卫一致（A78的281项加本次完整范围中13份原未纳入守卫的测试），152份受影响原子系统源的静态ordinary/relative/literal-dynamic import核查未见Harness→Coding依赖；不把静态核查扩大为所有动态导入。当前全生产634,818/物理净减2，全Coding仍137,835/累计−8,007，原C08仍7,195/累计−4,576、距最低线差3,424。物理总量刚转负不等于实质大规模瘦身或完整Goal完成：O-A8-N01中性查证协调、残留装配与原数量/平台条件仍须分项关闭，四个PD切片保持partial。未采用Package root receipt或普通私有目录创建替换根代际/叶目录合同；这项源码核查不算新实现或删除收益。Goal active/incomplete；未提交/发布，无新源码模块、根目录实现或门禁。

## 查询职责复核与原行为基线（A80）

O-A8-N01 原先把“查询还在 Coding”作为一个整体跟进项，现按三份独立的职责/复用、运行/失败、数据/兼容源码审查分解。三份报告均反对直接把整个查询簇搬进 Harness；本轮没有候选源码、代码交付或新架构组件，不把设计分析记作删除收益。

| 子项 | 当前证据与处置 |
| --- | --- |
| 只读/写入入口各有查询操作体 | 已收敛：两入口共用 `_current_completed_restore`、`_restore_preview`、`_expiry_preview` 三个函数，不再将调用方方法各算一份重复程序 |
| 归档、树核验、日志解析及最新删除回执的算法 | 已复用原 PM Archive、Resources Tree IO、Journal 与 `latest_deleted_target_receipt`；这些底层算法不重新列为待开发 |
| Product 身份、路径/hash、Desired removal/revision、原具体 DTO 和错误文案 | 保留 Coding；只读与 writer 的不同 guard、snapshot 接口和后验也是原合同，不要求合并为一个 owner |
| 固定的归档证据协调、恢复完成记录选择及确认匹配 | 仍待职责收敛；必须给出可用的原组件替代和全部配置成本，不因底层原语已共享就宣布这一项完成 |

原三查询完整函数跨度只有48、49、60行，共157行，而且包含上述必须保留的产品语义；前后两个树/stage薄适配另24行。它们不是数百行可直接净删池。三位 reviewer 的完整接口粗估均未证明系统净减，可能因窄端口、晚读取、具体 DTO 与错误适配而净增；这些只是预算，未做候选 drydiff，不作为实测或目标不可达证明。本轮不新增 QueryManager、持有 Product/layout/Journal 的大 context、策略分发器或重复存储。完整 O-A8-N01、PD-C/PD-D 和原数量条件继续未关闭。

运行与兼容核查明确了后续实现的限制：preview 先 capture 目标再 verify，完成查询先 verify 再 capture；expiry preview 需要再次读取 Desired 和归档，不能缓存早先观察；过期 recovery 可在原归档已 rename/删除后执行，不能改调要求原归档存在的完成查询；原 confirmation 的 `any` 授权也不能强化为 preview 的 latest/full-binding 判据。不能用新增拒绝条件让共享看似成立。

为这些此前未完整表达的顺序补了树外原行为基线：在七份当前原源码 SHA 守卫下，冻结24个 preview/completed/expiry 成功与双故障观察，记录具体返回 DTO/wire、调用轨迹、异常类别/文案/cause/context及 parent/archive 关闭优先级。探针使用惯性文件操作和日志端口，仅证明被替换端口之间的查询控制流，不证明真实 IO、Product 授权或 native Windows。原完整业务测试的证据仍按 A79 范围解释；本次不重复运行已通过的广泛组合，也不新增产品测试或 PR gate。

A80 的三份审查、原源码快照、冻结预期和探针均在产品树外 `architecture-analysis/private-data-lifecycle-design-20261106/query-convergence-a80/`。本轮只修正当前职责与待办的解释，源码和数量仍为 A79：Coding −8,007、原C08 −4,576／距最低线差3,424、全生产物理净减2。下一候选必须先证明整簇旧体退出与全部接收成本，再作为规模削减路线；不以新 helper 数量或文档条目关闭原 Goal。

## 固定查询证据归原 Archive/Journal（A81）

沿已接受R3与A80拆分结果，本片仅将三个固定中性程序归原owner：原[Archive](../../../../src/loushang/harness/plugin_management/private_data_backup.py)的 `read_deleted_restore_source` 供preview/完成查询共用归档与最新删除证据核验，`inspect_private_expiry_archive` 负责原expiry的FD/可见路径/关闭后快照比较；原[RestoreJournal](../../../../src/loushang/harness/plugin_management/private_data_restore_journal.py)的 `completed_for` 通过自身原events加载并选择确切完成记录，保留整个历史末项started的屏障。没有新组件、模块、日志、锁、状态机或query context。原read/verify、latest-deleted、Tree IO、五元metadata与Journal加载直接复用。

Coding保留digest/支持范围、Desired removal与第二次snapshot、路径/hash、具体DTO、确认与recovery授权、原guard及目标/stage政策。两个晚回调仅用于在manifest身份成功后读取deletion.events、在两个FD关闭后重新捕获archive；未缓存旧证据。恢复的identity计算、Journal构造和目标验证仍发生在原时点。过期recovery没有改调要求原archive仍存在的查询，不增加拒绝条件。

| 完整生产源 | 前 | 后 | 净变化 |
| --- | ---: | ---: | ---: |
| Coding restore | 376 | 366 | −10 |
| Coding expiry | 309 | 296 | −13 |
| PM Archive | 505 | 583 | +78 |
| PM RestoreJournal | 354 | 369 | +15 |
| 合计 | 1,544 | 1,614 | **+70** |

其中格式净增2、结构净增68，所有窄协议、泛型、签名、错误文本和装配均计入。A80“不作为规模净删路线”的判断仍成立；本片完成职责接管，**没有交付系统减量**。原Code两份归档证据程序及独立物理expiry/完成选择旧体已退出，未保留双实现。未改公开Owner/DTO/构造/signature/__all__、wire/version/ID/hash、存储路径或权限。

部分Code私有物理别名/包装接缝退出；新接口取得原固定io/codec实例，不承诺执行中任意重绑模块私有全局或traceback位置仍相同。原action兼容测试仅删除一条已无执行作用的Code `_verify_archive` patch，真正PM verify的故障注入、原expected及所有断言保留；移除该单条旧Expr后整测试AST相同。其余四源除三个Code查询替换、新增固定程序与imports以外AST保持，confirmation源逐字未改。

验证分开记录：

- 原A80的24项查询预期逐字保留。实际路径首版通过1项差分（2.51s）；补同进程6个actor源码路径/co_filename/SHA和Code→Core同对象断言后，仍1项通过（6.35s）。移入程序和继承的completed_for真实执行，惯性IO/Journal仅替换叶依赖；不称真实授权/native证据。
- 原21份完整C08业务文件，加3份历史/恢复与过期action兼容文件：**119 passed，0failed/skip，340.03s**。包含原实际Product/CLI/SDK的成功、失败、恢复和no-create读取路径；不扩大为全Product、所有故障组合或Windows native。
- 四个实际完整变化源 `--follow-imports=silent` mypy通过；非默认完整依赖图。修改源Ruff/format、294项先前source/test/fixture守卫与diff核查保持；此范围之外的旧广依赖/skill及native限制未宣称修复。

实际frame SHA256 `9843e2a90d7a8f0c1e0dbe1af42fc39ce306f64e56a8a7976cf06250037d29d4`，三份实际代码评审、终态、原源码/探针/预期和完整成本置产品树外 `query-owners-a81/`。O-A8-N01仅关闭这三个中性程序的归位，目标/stage、具体确认/产品授权及其余装配仍分项审视；四完整PD切片/原C08最低线/系统净减及Goal未完成。当前全Coding累计−8,030，原C08−4,599／差3,401，全生产仍+68。未提交/发布、新增gate、联网或调用模型。
