# H-PD-KD-001 R3：三视角独立评审与综合结论

## 状态和评审框架

- Authority: descriptive review evidence。
- Design status: accepted for implementation；下文保留 R3 原技术评审结论，后续用户接受见 [交付记录](../private-data-convergence-delivery.md)。
- Implementation status: partial；本记录的静态评审证据不替代实施验收。
- 评审对象：[插件私有数据生命周期收敛](private-data-lifecycle-convergence.md)，**R3**。
- 对象 SHA256：`f79fcfcdcb381803e544aae457d3e3adf2e6410f153c210495260872c68713aa`。
- 源码基线：`8ad6b6098f1c24c8cfb6f4d9d290e99bc74d618d`，2026-11-06；工作分支 `harness/private-data-lifecycle-design`。
- 方法：本地干净 archmethod master `0f9bd3ff51afabeaaf76cc38dff1ceb279b7d37e`。
- 范围：C08 全部 31 个文件/11,771 物理行及必要入口；复用优先、旧体退出、平台准入、生命周期和存量兼容。
- 证据：静态源码、独立场景走查、源码指纹和文档检查。未运行 Product、pytest、模型或实际维护动作；未验证 Windows 原生行为。

**综合结论：R3 三视角技术评审通过，可提交用户架构评审；剩余设计阻断为 0。** 这不是用户接受、实现完成、行数达标或 Windows 发布声明。本轮没有修改源码、测试或 CI。

## 独立性与修订过程

三个 reviewer 使用分别创建的上下文，不读取其他 reviewer 的报告，直接访问冻结源码与方法。作者负责修订和综合，不冒充第四份独立评审。首次 R1 过程因会话中断没有形成三份完整结论；R2 重新发起三视角独立审查，不能从 R1 推导通过。

R2 的三份结果均保留为“不就绪”，没有覆盖掉历史发现。作者将共同的动作准入问题与单独的 JSON 错误兼容问题修正为 R3，再交回原三位 reviewer 定点复核，并检查修改条款之间的相互影响。没有通过运行代码来掩盖设计矛盾。

| 视角 | 独立 reviewer | R2 结论 | R3 复核 |
| --- | --- | --- | --- |
| 职责、复用、复杂度 | `/root/pd_r2_ownership` | O-R2-03 阻断；其余边界方向成立 | O-R2-03 关闭；无新阻断；可提交用户评审 |
| 运行、失败、权限、物理路径 | `/root/pd_r2_runtime` | RT-R2-01 阻断 | RT-R2-01 关闭；无新阻断；可提交用户评审 |
| 数据、兼容、演进、验证 | `/root/pd_r2_data` | D-R2-01、D-R2-02 阻断 | 两项关闭；无新阻断；可提交用户评审 |

原始报告及每版工作件、完整 SHA 保存在产品树外的本地证据目录：`/home/dev/lsspace/architecture-analysis/private-data-lifecycle-design-20261106/`。文件名为 `review-{ownership,runtime,data}-r2.md` 与对应 `-r3.md`；本文件是产品文档内的综合记录，不复制原始研究和整份逐函数报告。

## 发现、修订与关闭

### 1. 原查询路径不能统一冒称无创建

R1 将 preview/verify 的无创建读取过度概括。POSIX 原公共只读路径与 Windows 显式 candidate 实际装配不同：后者也打开完整 Product，registry coordination 可创建原锁。作者源码核实后在 R2 分开，R3 继续保持平台差异。

关闭依据：设计 PD-06、§2、§4.1 和 §4.2；现有 `coding/package_private_data_windows_backup_client.py` 的 `_owner()` 与 `harness/resources/packages/plugin_lifecycle/windows_lease_registry.py` 的 `_coordination()`。本次不新建 Windows no-create reader、不默认开放普通 Windows 管理入口。

### 2. 共同动作锁模板与 Current 不一致

关联发现：O-R2-03、RT-R2-01、D-R2-01，属于同一个设计问题。

R2 仍把 Windows preview/verify 归为读 guard，并概括了所有查询的 quiescence→GC 顺序。源码显示：恢复确认 verify、过期 preview 进入原恢复 Q→W 事务；Windows status 只有动作级 GC read guard，没有动作级 Q；POSIX status 使用只读 epoch 与 BackupReadSource 直接投影，也不进入 Q/GC。统一模板可能改变准入、给 status 新增拒绝，或重复获取已有事务的锁。

R3 §3、§4.1、§4.2 改为逐公开动作对照，明确：

- 13 个 Windows candidate 动作的完整 Product 准入与其内部 Q/R/W 作用域分别保留。
- POSIX status、ReadOwner 查询、原已有 offline writer、独立确认入口分别保持原调用边界。
- Windows restore-preview 直接构造内层观察 transaction，expiry 复用原 restore transaction，不重复进 wrapper。
- journal 原短临界段与 native handles 沿原顺序交错，不新增包住整个动作的日志锁。

三位 reviewer 分别核对原调用链并在各自 R3 报告中关闭关联发现。这是文档合同纠正，不是加强锁定或扩大权限。

### 3. 单次 JSON 解析不能改变原错误优先级

关联发现：D-R2-02。

原 POSIX journal 先完成整份 `load_jsonl`/codec，再检查重复键，最后投影 phase/revision。直接在 parser 内提前抛重复键错误，会使重复键与非法 schema 共存时的对外 code 变化，也会改变“前行重复键、后行 schema 错误”的全文件优先级。

R3 §4.1.1/EV-05 明确原 Journal 的最小扩充：同一 raw snapshot 单次解析只收集重复键诊断，mapping 保持原末值覆盖；沿原整份 load/codec/load-policy 执行；原 load 成功后，才抛原调用方的 duplicate 异常，随后才进入原 owner 投影。原有 manifest/Windows 立即拒绝模式与 Journal 缺省不变；诊断不是新的持久日志或事实权威。

数据与运行 reviewer 核对后关闭该矛盾。部分尾修复/丢弃的内容仍沿原 load policy，不因诊断收集而解析本来跳过的尾段或提升其错误优先级。此项尚未编码，必须以固定基线异常类别/code/行序样本验证，不能把设计复核当作行为测试。

## 综合场景检查

| 场景 | 合并设计后的约束 | 结果与证据边界 |
| --- | --- | --- |
| 带空目录与正确 partial prefix 的备份 | 原 tree/file/native 内核补精确缺口；原 archive/manifest/ID；保留原 stage；不调用会拒绝/删除 stage 的 Package 整树生命周期 | 职责与运行视角支持可实施方向，未执行复制 |
| 有 active runtime 时查询 status | 不套需要静止期的 mutation 模板；保留两平台原准入与保守投影 | 不新增 Q/拒绝条件；不承诺 status 是强一致事务快照 |
| Windows 恢复确认 verify/过期 preview | 仍进入原 Q→W restore transaction，保持完整 candidate 准入；不按“查询”降低/替换准入 | 三视角来源一致；没有 Windows native 实测 |
| 日志重复键与后行 schema/tail 错误并存 | 原整份 load 错误优先；无二次开文件/解析；只在原 load 成功后发出 duplicate 异常 | 数据与运行复核无矛盾；待实现固定样本验证 |
| rename 成功、完成记录不明后重试 | 原 started/renamed/publication/identity 与精确确认查证；不从“目录不存在”猜成功，不自动重放 | 保留原可恢复/可诊断分支，不提升任意崩溃自动恢复承诺 |
| 源码切片回退 | 共享实现、全部消费者、值/错误适配与兼容导出一起回退；格式不变，无反向数据迁移 | 与旧格式/ID/错误合同一致；实际回退验证待实施 |

## 非阻断实施责任

| 责任项 | Owner / 时点 | 关闭证据 |
| --- | --- | --- |
| O-R2-01：中性内核与原 Package 值/错误解耦 | Harness Resources + Plugin Management；PD-A | 两个消费者调用同一算法，无假 Package 对象/receipt；原缺省/abort/reuse 及错误保持；Coding 旧操作体同步删除 |
| O-R2-02：Product topology 政策留下 | Coding + Package Product；PD-D 前 | 原闭集、缺失 topology 与 Worker history、kind/owner revision/引用政策逐项映射；底层不硬编码 Coding 含义 |
| D-R2-A01：固定旧字节/ID/错误样本 | 切片实施者；PD-A 提取前起按相关切片冻结 | 基线样本独立于新构造器；比较异常类别/code/路径和适用行序；原生身份另以真实对象建立，不拿静态 inode 当权威 |
| D-R2-A02：完整切片回退证明 | 切片实施者；各切片交付前 | 相关源码版本与同一兼容样本一致；不删除已写事实，不要求清空状态，不混用两个版本维护同一 scope |

这些是已规定的实现验收责任，不是未关闭设计阻断。若实现发现无法保持合同，应修订设计并复核受影响场景；不得以原评审结论批准语义扩大或静默降低兼容。

## 提交范围与下一步

方案与处置表已经覆盖 31 文件/11,771 行；统计证明覆盖，不能作为未来净减少量。文档检查通过不证明 Product/runtime/native 成功。

评审形成时用户尚未接受本 R3；此后用户明确要求实施引用它的 Goal，本专项已进入实施，整体其它重构范围仍为 proposed。依照此前“系统环境图等重要工作件需要用户评审”的指令，本记录保留评审时的结论和指纹；实际接受与实施进度另见交付记录。首个代码切片是 **PD-A：备份与核验纵向闭环**，先冻结相关旧样本，复用已有组件，只补明确缺口，并在同一切片删除被替换旧体。后续依次为确认删除、恢复与过期、入口/声明收尾。

## A34 Windows 确认／删除的三视角代码复核

本次为已接受 R3 内部职责落位，不改变系统环境、公开 API、持久格式或平台支持范围。A32 外置 R1 的共享 Product 文案／cap 声明、残留 Coding 物理查证及行为证据不足问题，经 A33/R2 修正并独立评审；A34 实际接入后再次做增量复核。原候选、拒绝与后续修复分别留存，不回写先前结论。

| 视角 | 实际核查 | A34 结论 |
| --- | --- | --- |
| 职责／复用 | 原 PM Confirmation／Deletion 接管固定 Windows 程序，Resources 接管 tombstone 物理查证；原 Coordinator、Journal／receipt／tree/native 原语及 Product 准入仍各归原 owner；旧 Code 操作体退出 | 无新增阻断；可以接受七份源码的有界接入 |
| 运行／失败 | 实际与候选的执行体、配置、动态读取点及关闭／重试时序一致；未引入额外锁、任务持有者或更强目录准入；先前部分失败／查询／重试证据仍适用 | 无新增阻断；不推导原生平台或完整恢复验收 |
| 数据／兼容 | 171 个冻结／live hash，七源与候选仅一文件 import 排版不同；原构造、codec／ID／hash／cap、103／56 原 fixture 保持；独立实算全部生产源码成本 | 无新增阻断；系统仍净增，原 Goal 未完成 |

三位独立 reviewer 未互读报告、未修改产品或重新执行测试。最终实际源码回归由实施者执行并回收终态：151 passed、49 native Windows skipped（9.59s）；七源窄 mypy、144 Python Ruff、171 live hash 通过。62 项原行为观察中的 Product／native 替代端口不构成可信装配或原生 Windows 证明。实际变动为 Coding −381／Harness +655／系统 +274，包含一行 import 排版；全任务系统仍 +893，C08 距原最低线仍差 5,238。

A34 源／测试清单 SHA256 `63715c4332afbae23df0292d16ae41bfe971e04b7a29651470caa45b70c1becc`。三份报告及原源码、运行结果、成本和来源证据位于产品树外同任务 A34 检查点。实施 owner 据已有授权接受此有界增量；不是用户接受新的重要架构工作件，不关闭完整 PD-B、PD-A/B/C/D 或 COD-PD-GOAL-001。完整 Goal 保持 active／partial；未提交或远程发布。

## A35 接收层 GC 快照的三视角代码复核

三位独立 reviewer 已核对 A35 同一 173 路径清单，SHA256 `99590a790476629e55c4fe277441d69a6f6e678c4506ce7776621aecc429ef2e`，均无新增阻断：职责视角确认五条读取路径直接复用原 Journal，没有新存储壳；运行视角确认 schema／load／repair→重复键→history 及原只读锁策略；数据视角确认原 codec／记录及 96 项预期字节不变、修复后的文件后果一致。四模块其它领域方法 AST 未变，旧二次读取体及无消费者私有 hook 退出。

单次快照明确不再观察旧第二次 open 独有故障或两次读取间的外部改写，不冒称所有文件系统故障 trace 相同；schema 与重复键诊断现在来自同一原 Journal 快照。新逻辑不扩大锁或 native 权限，不迁移 Worker/capture 的不同 framing／错误次序。

实施者运行的最终结果为 102 项定向通过（1.70s）、41 项实际 Product／Materialization 通过（25.35s）、四源窄 mypy 通过；reviewer 未重复执行测试或互读报告。173 live hash、145 Python Ruff 通过。本片 Harness −44、Coding 0；全任务仍净增 849，C08／全 Coding 的原数字不变。实施 owner 接受这一有界直接复用，不关闭完整 Goal 或原生平台验收。三份报告、旧源与原结果保存在产品树外 A35 检查点；详见[实施进展](../coding-convergence-progress.md#原-gc-日志复用单次快照解析a35)。

## A36／A37 Windows 恢复组件代码评审

A36/R2 的三份独立代码报告均支持有界实施；A37 复制实际工作树并完整格式化后，三视角分别做增量复核，均无新增阻断。职责视角核实原 PM／Resources 复用和旧 Code 操作体退出；运行视角核实阶段、未知写入查询、ACL／借用 FD／关闭后验；数据视角核实原具体 DTO、构造字段、codec／ID／hash／caps／sequence 与原固定预期保持。归档 retained／restore 查证确有两个实际消费者，复用有限父目录作用域，不是未消费的通用壳。

三源实际与候选的非 import AST、导入绑定一致；格式整理新增 57 行全部计费。A37 源／测试清单 SHA256 `585481d9daccf07737ff910d1951a5cf11bd0b9dfc3f2629d59d5d2ae160ff5e`。实施者在普通 worktree PYTHONPATH、无覆盖层执行最终 110 passed／49 native Windows skipped（8.16s），三源窄 mypy 通过；177 live hash／148 Python Ruff 通过。reviewer 只读核查实际与候选增量，未重跑测试、互读报告或修改产品。

实施 owner 在已有 R3 授权内接受这一有界接管。Code −486、Harness +769、系统 +283；完整任务系统仍 +1,132，原 C08 最低线仍差 4,752。惯性 Product／native／receipt 端口、POSIX parent FD 及原平台 skip 不构成可信 Product/native Windows 或完整 PD-C／Goal 验收。范围、原 label 发现及其修复、成本和剩余项见[实施进展](../coding-convergence-progress.md#windows-恢复记录阶段归原组件a36a37)；三份实际复核和候选报告均在产品树外 A36／A37 证据目录。未提交或远程发布。

## A38 Windows 恢复物理流程代码评审

三份独立代码评审分别核查职责复用、运行失败与数据兼容。原 PM Restore 固定动作、Archive IO 与 Resources Tree IO 分工合理；三处 Code 绑定仅承载原路径和根代际政策，旧复制／发布／查证厚体已退出。记录／ID／hash／布局／caps、Q／GC／借用 FD、stage 关闭和根代际写入顺序保持。未新增 manager、存储、通用步骤引擎或公共 facade。

两项接入证据问题已关闭：原 native 测试的 rename／root 收据注入转向实际 Resources／Code journal，其他原断言保持；23 组原行为预期经原五源导入路径／SHA 守卫只读重放，原 frozen bytes 不变，生成器退役。最后仅 native 测试 import 排序及新 POSIX FD 测试的显式平台 marker 发生测试差异，算法 AST／绑定对照、完整成本与独立增量复核均保留在产品树外。

实际工作树五源的定向检查为 111 passed、49 native Windows skipped（13.64s），五源窄 mypy 通过。179 份 source／test／fixture hash 与 149 个 Python Ruff 已核。最终实际清单文件 SHA256 为 `fd9007f44e0b30216cd31f7c83e9743572094e2408bb0ca07d2fab100dce416e`；候选清单的 files-payload ID 与清单文件 digest 分开记录，不将两者混用。reviewer 只读独立核查，未修改产品或重跑测试。

实施 owner 在原 R3 授权内接受这一有界接入。Code −231、Harness +279、系统 +48；任务累计系统 +1,180、原 C08 削减仍差 4,521 行。惯性 Windows／Product 端口与真实 POSIX FD 不构成可信 Product／native Windows 或完整 Goal 验收；完整 PD-C 及其余原场景和最终净减条件保持未完成。完整成本、顺序、验证和后续范围见[推进记录](../coding-convergence-progress.md#windows-恢复物理流程归原组件a38)。


## A40 Windows 过期执行程序代码评审

三份独立候选报告及三份实际接入增量报告均无剩余阻断。职责视角核实固定执行与 Archive／Tree 的原 owner 分工、原体退出、四个 Code 窄绑定和单次 receipt 类型 cast；运行视角核实跨 renamed 记录的两次 subset、completed 前后 settle、ACL／FD／未知结果的原顺序；数据视角核实具体 DTO／schema／ID／hash／caps、原 transaction 形状、history／编号 IO 与 native 断言保持。无消费者的旧 chunk 常量已删除，原 profile 仍为 1 MiB。

原 25 组观察具有 canonical 原模块路径／SHA 守卫及固定 raw，实际 Code record codec／scan／append 和 POSIX 文件效果运行；Product／Windows／成员删除的测试端口不授予真实操作权。候选验证为 88 passed／49 skipped；实际普通 worktree PYTHONPATH、无 overlay 验证 142 passed／49 native Windows skipped（14.24s）与六源窄 mypy。随后唯一差异为 native 测试 imports 排序，非 import AST／绑定相等，未冒称重跑最终测试字节。

实际清单文件 SHA256 `750fb057c62148405b5016e84ac7fe84b44fd15814044a63197f83a29785907a`，184 份 source／test／fixture、153 Python Ruff 与独立计数核查。实施 owner 在原 R3 授权内接受这一有界接管；Code −262／Harness +405／系统 +143，只记职责成本。当前全系统仍 +1,323、原 C08 最低线仍差 4,259 行；原 Code expiry Journal 的中性 IO／history、完整 PD-C、Goal 和原生 Windows 尚未验收。reviewer 仅只读复核，没有修改产品或重跑测试。完整原始报告／快照和差异存于产品树外 A40 目录，范围见[实施进展](../coding-convergence-progress.md#windows-过期完整执行程序接管a40)。


## A41 归档快照及共同作用域代码评审

职责 R1 发现 O-A41-01：新增 expected-manifest 格式回调重复原 Windows codec。R2 核实该 codec 的完整返回 AST 正是旧字节表达式、无额外 key 校验，删除外部回调与 Code 重复编码，仍由 Native 在原 after／visible metadata 之后延迟求值。两种 Code DTO 构造投影不变。R1 原稿及原报告逐字保留，三视角 R2 与实际接入增量复核均无剩余阻断。

运行视角将 parent_scope 内联后核对原 retain／read 完整 AST，确认 inspect／ACL／open／close／postinspect、投影异常与 close 失败优先级保持；提前消息读取只针对当前 Code 配置的 frozen 字符串。数据视角核实 DTO 整 AST、公开 args／return／exports、原 4 MiB、64 KiB／max+1、manifest／files／root 五元身份及求值／构造 scope。没有第二格式器、reader、store 或阶段引擎。

实际 frame 文件 SHA256 `9f41095ec7bc13b1f0f1a421551800f405a07aa6f2bcbe22e11e26a25ee291e0`，186 份 source／test／fixture 与 154 Python Ruff 核查；五候选文件与实际逐字一致，之后无源或测试改动。原 20 观察经三 canonical 源路径／SHA 守卫只读重放，R2 为 152 passed／49 skipped，实际普通 PYTHONPATH／无 overlay 为 152 passed／49 native Windows skipped（10.92s），三源窄 mypy 通过。reviewer 只读，未重新运行测试或修改产品。

实施 owner 在原 R3 授权内接受这一有界接管。Code −140／Harness +153／系统 +13；累计系统 +1,336、原 C08 最低线仍差 4,119 行，完整 PD-A/B/C/D 与 Goal 未验收。真实 POSIX FD／Archive codec／记录校验及 Windows／metadata／形状端口替身不构成 native／可信 Product 接受。范围、实测成本和后续项见[推进记录](../coding-convergence-progress.md#windows-归档快照捕获归原组件a41)，原证据位于产品树外 A41 目录。


## A42 过期 Journal 与历史判据代码评审

三份独立候选及实际增量报告分别核查职责／复用、运行／失败、数据／兼容，无本增量生产源码阻断。旧测试的注入点转向实际 PM／收据 IO，并保留原断言、原固定预期和 expiry 显式 16 MiB 写上限。新探针以 `as_posix()` 统一两处显示路径，关闭跨平台测试表示问题，不改变存储路径或放宽原预期。

原 DTO、构造字段／slots／签名、ID／hash／wire 与固定物理动作保持；共用历史校验只在两平台原位置执行。记录工厂直接绑定原类型／create，fresh record 仍使用原默认版本。Code 的具体类型／当前计划校验先于 Journal，原 scope active、阶段重入与 staging 优先级保留；共享组件不接收 Product 或新执行控制。

实际清单文件 SHA256 `c6f9c74023a4019facff981a081c82d0e526d186fde20292d85b107abb637cfe`，190 份 source／test／fixture，157 Python Ruff 与 9 份变化 Python 格式检查通过。52 项定向／94 项相邻回归分列，新探针路径修正后14项复验与前者重叠、不累计。四源窄 mypy 通过；默认依赖扩查仍报237错误／8文件，首次并行窄检查退出139原因未建立，独立 cache 顺序重跑通过。不能据此宣称全量类型检查通过或归因全为主线既存。

实施 owner 在原 R3 授权内接受这一有界职责增量，未制造用户另行接受声明。Code −175／Harness +222／系统 +47；累计全系统仍 +1,383，原 C08 减少4,056、8,000行最低线尚差3,944。完整 PD-A/B/C/D、原生 Windows／可信 Product 及整个 Goal 继续未完成；具体成本、来源和限制见[推进记录](../coding-convergence-progress.md#windows-过期-journal-与两平台历史校验归位a42)。未提交或远程发布。


## A43 POSIX 过期执行归原归档组件代码评审

三份独立预审和实际终审分别核查职责／复用、运行／失败、数据／兼容。继承＋abstract 草稿和新平台模块已退役，固定动作最终直接归既有 private_data_backup 组件；原 PM 既有 class／function AST 全等，Coding 原 dataclass 形状、公开准入／offline 及领域权威方法保持。四个延迟映射和两方法权威视图只表达原固定观察点，不创建任意步骤框架，双 subset 及清理后 completion 次序保留。无本增量剩余代码阻断。

探针只跟踪 open 而遗漏 dup 的证据缺口已关闭：加入 dup 跟踪后，原 canonical 存档源码只读重放同一固定预期通过，再运行实际迁移源码。原 name-failure 在 try 前可能留下 FD 的旧边界未在迁移中改写，因此无泄露断言只覆盖实际15场景，不扩大为所有失败。最初freeze只校验Code源，后补PM guard明确分开；真实每run记录身份断言不冒称随机inode／mtime wire可跨run固定。

最后实际清单文件 SHA256 `65d0fa48f2857517bafca2b212724d826ab112e43420b6e9949482bcefb7852f`，192份 source／test／fixture 与158 Python Ruff 已核；五份 final candidate 与实际逐字一致，之后无源／测试改动。末版27passed（36.39s）含15动作与原12真实Product集成，两源窄mypy通过；前版30／12／15分别记录，不累加。A42默认宽依赖类型检查未绿的限制保留，原生Windows及完整Goal不据此验收。

实施owner依原R3授权接受这一有界接入，不冒称用户另行接受。Code−139／Harness+210／系统+71；累计原C08−4,195、最低线尚差3,805，全系统仍+1,454。Code `_expiry_preview`原生观察段、POSIX Journal及其余原场景未关闭，数量／净负条件保持。原始报告与预算存产品树外A43目录，范围见[推进记录](../coding-convergence-progress.md#posix-过期固定动作归原归档组件a43)。未提交或远程发布。


## A44 两平台归档枚举代码评审

三份独立实际评审均无剩余阻断。职责发现 O-A44-01：R1 把 Code 的 Windows 名称规则放进通用 ArchiveIO，已修正为 Code 传原 len→any 短路判据；POSIX 的原 digest／.staging 保持独立。没有新 validator／profile／manager。Windows 原父目录scope成为第四消费者；将其内联后与旧控制流核对，open／ACL／held identity／close／post及错误优先级保持，原两个Archive组件的既有方法／函数不改。Code其它类、政策及公开形状保持。

原25观察是inert enumeration／scope／error端口，不冒称wire或native平台证明；两遍manifest读取由原verify调用链及相邻真实FD例支撑。原4模块canonical路径／SHA只读重放99447通过，最初磁盘SHA freeze10362与62136旧case重放单独记录，不混会话，不重生成expected。新名称子类断言复用旧valid结果，证明没有新增strip。原FD测试对退休Code.os的注入已改为只在该Code绑定存在时执行，实际Native／PM／file-consumption始终注入，原全部assert／fixture保持；没有为测试补dead shim。

实际frame文件SHA256 `f8bf827a55d105ba187cde0ec845e76057c0b2edf1ea4ec61eebd64e99a1d056`，194份source／test／fixture，159 Python Ruff与6份变化Python格式／diff检查通过。六candidate文件与actual逐字一致，唯一额外测试seam有独立delta复核。最终同一路由93passed（17.27s）与四源窄mypy通过；首轮67／1因退休seam失败保留，不累加为新覆盖。A42宽依赖类型检查未绿与native Windows未验收限制仍保留。

实施owner沿原R3授权接受这一有界增量，不代替用户重要架构评审或完整Goal接受。Code−55／Harness+105／系统+50，累计C08−4,250、原最低线仍差3,750，全系统仍+1,504；PD-A/B/C/D其它残留及最终条件继续未完成。原始报告与源快照在产品树外A44目录，范围见[推进记录](../coding-convergence-progress.md#两平台归档枚举归原-archive-ownera44)。未提交或远程发布。
## A47 POSIX 过期 Journal 与共同推进终审

本节为追加的实施证据，不改R3的原接受切点和完整Goal条件。三视角独立候选／实际评审无剩余阻断，实际清单SHA256 `76d19f87afdc77414db19a3512d307b004f22a21231fcf147cde5e863d104677`，214份source／test／fixture。实施owner在原职责收敛授权内有界接受，不代替用户重要架构、原生平台或整体Goal验收。

原Code整个POSIX expiry Journal协调类归PM过期组件，Code仅保Path准入、DTO／codec、工厂和限额绑定。原Windows `_advance_current` 成为同PM内空slots、无状态的共享体；scan／append仍平台所有。POSIX仍先验phase→parent→exclusive lock→repair load，读者仍shared/create_lock=False/partial-tail raise；全load/schema之后unique→cap→history的原顺序不变。confirm／begin原相等方向和文案保留，没有借Windows staged判据强化POSIX。

共享推进的POSIX scan明确staged=None，append忽略原返回并返回原event；Windows保留stage／active／发布复查和append返回值。所有新event调用原构造器取默认版本1，不用replace(prior)继承旧float/bool版本。五getter按原点取工厂与64MiB／4096限额，原四实例字段及初始化顺序保持；DTO／codec／schema和原history validator AST不改。

- 65338：改源前3原SHA与canonical导入守卫，冻结24项真实POSIX Journal观察，1 passed（2.42s），拒绝覆盖已有fixture。
- 75791：仅三模块canonical候选映射，24原POSIX／13原Windows／shape与实际导入来源检查合计39 passed（7.43s）。原scope字节、异常链、动态cap、尾修复、append前后失败和版本重放保持。候选三源shadow-mypy通过。
- 实际源码88916：43 passed（8.71s）；原Product备份／删除／恢复／确认／过期及两平台动作6700：52 passed（17.25s）。各组单独报告，不相加为独立能力数量。实际三源窄mypy通过。
- 最后仅共同模块docstring澄清包含POSIX adapter；可逆恢复到已审SHA，执行AST和成本不变。实际回归覆盖最终字节。214 live hash、177 Python Ruff、四份变化Python格式及diff检查通过。

新增probe使用有效固定归档DTO元数据和真实本地Journal，不能冒称真实archive／Product授权或native Windows。原Windows13例也是inert native/preview合同，原生平台限制保留。原freezer／probe、旧raw fixture、候选及最终三源与报告存在产品树外A47目录。预审后docstring快照通过唯一首句逆替换重建并校验旧SHA，明确是运行后重建，不冒称运行前抓取。原expected从未以新实现重生。

完整成本Code−130／Harness+207／系统+77，为职责接管而非系统净删。原31源交集仅该POSIX Journal；累计C08−4,383（8K缺口3,617）、全Code−5,990、系统仍+1,424。原数量、完整业务收尾及最终系统净减少条件继续未达到；A42宽依赖类型检查的既有未通过记录仍不被本次窄检查覆盖。未提交或远程发布。



## A48 POSIX 恢复协调终审

实施 owner 在原 R3 和 COD-PD-GOAL-001 授权内接受本次有界内部接管。三个独立 agent 从职责／复用、运行／失败、数据／兼容检查最终实际源码；无剩余具体阻断。接受对象为 Code POSIX restore 和既有 PM Archive 的固定程序组合，不关闭预览、确认、完整 PD-C 或整体 Goal，也不改变重要架构工作件的用户评审边界。

最终实际快照 code-checkpoint-a48/frame.json SHA256 `61ee3930ff4f9f883746e66a7c1ccf7a03b76cc78b7ea0b79a471c4af71cb261`，216源／测试／fixture路径，178 Python；两份生产源码与最终候选逐字相同。旧协调主体与两个 helper 退出，原 Tree IO／Journal／metadata／FD scope 直接复用；Code Product、计划类型／身份、删除凭据和具体记录权威保留。文件关闭→归档身份复核→complete／结果构造→归档关闭的原错误优先级保持。

三视角初版发现缺失运行时导入、固定 files 名称、提前绑定及逐文件重取 writer。最终导入原定义、使用原 codec.files_name、窄 target_state 值和延迟工厂；writer只在第二次prepare后的原native调用实参处取得一次。Windows 原完整计划协议留原处。试制 retainer 误替经 Ruff 在采用前发现并修复，原 PM 全部函数／类 AST 独立核对与 before 相同。缺陷历史、反例和关闭过程保留于各独立报告，不把初版写成可运行末版。

原 canonical／SHA 守卫22组观察和追加第23组 writer 反例在修改 Product 前固定；旧22字节及结果保持。候选来源核验＋23观察24项通过；最后实际普通PYTHONPATH／无overlay **35 passed（16.46s）**，含新23观察与原12项真实Product／POSIX集成；最后两源窄mypy通过。仓库Ruff的import排序修正后重验最后字节，排序前结果另列不累计。216hash、178Python Ruff、3format、diff和9静态文档不变量通过。

新23观察使用惯性native／准入／Journal端口，不替代原生FD／权限或可信Product证据；原12集成单列，不扩张到Windows。A42默认依赖扩查237错误／8文件未消除或归因，不能称全类型检查通过。本片Code−70／Harness+94／系统+24，是接管成本；累计Code−6,060、原C08−4,453（8K最低线差3,547）、系统仍+1,448。原完成条件不降低，Goal保持active／incomplete。三份最终报告、固定fixture、运行来源和全源码独立计数在外部code-checkpoint-a48归档；未提交、未发布。


## A50：Windows 预览与删除屏障直接复用终审

实施 owner 在原 R3／COD-PD-GOAL-001 内接受本次四调用点的有界直接复用。职责／复用、运行／失败、数据／兼容三个独立 agent 均检查实际源码及证据，当前无剩余具体阻断。原两个Core不改，没有新增接口、引擎、持久格式或系统环境角色，不代替用户重要架构或完整Goal验收。

实际code-checkpoint-a50/frame.json SHA256 `8753095cf1ed818a5516cdd98c68eb26f337184b64661afee72a3f72da29faa0`，222路径／181Python。四份Code逐字等于已审候选；Archive及PM deletion Core与原值逐字相同。两个preview复用同一_parent_scope，首次inspect／ACL先后、身份／暂存错误、close失败跳过postinspect、body失败仍postinspect的优先级保持。两查询只使用最新同Installation事件，不回借旧deleted；后续confirmation仍绑定该receipt_id。全部正式字段／计划／记录／写入和Root lineage权威保持，未因复用提升拒绝强度。

原44预览观察由2Code＋Archive SHA／canonical守卫固定，原9屏障及完整恢复权限走查由4Code＋2Core守卫另固定；原fixture字节保持。原阶段2源45pass／2shadow与最终四源54pass／4shadow分列，不混执行来源。实际普通PYTHONPATH／无overlay **97 passed（4.50s）**，含53固定观察及原Windows恢复交易／具体PM删除事实合同；实际四源窄mypy通过。新probe只做imports／多语句格式整理，observe AST与原件相同；没有生产测试失败或expected重写。

最终222hash、181Python Ruff、六文件format、diff及9静态文档不变量通过。新53的Native／Product为惯性输入；真实Code Plan DTO字段／fingerprint被观察，不据此授予权威或宣称nativeWindows ACL／stream／durability验证。A42默认依赖扩查237错误／8文件仍未解决或充分归因，窄mypy不能称全面绿。三个最终报告、前置候选／冻结／具体来源及独立全源计数在外部code-checkpoint-a50归档。

四完整Code源859→830（−29），Harness新增0，且四源均属于原C08，因此C08／Code／系统各净减29。累计Code−6,173／C08−4,482（8K最低线差3,518）／系统仍+1,375。三视角另对较大残留完成源码复核：已共享DTO／领域记录不是重复可删池，原Protocol不提供同格式值实现，现有无创建读／Root lineage合同不能强套其它owner；append／replay粗估不当交付量。这些有范围的证据不证明8K不可达，也不降低完成线。本片不能替代规模目标，Goal保持active／incomplete；未提交或远程发布。

## A52 联合类型合同与无运行变化复核

职责／复用、运行／失败、数据／兼容三位独立 reviewer 复核实际增量，无剩余阻断。实施 owner 在原授权内接受这项局部类型修正；没有新架构、组件、数据协议或平台保证。

实际 `code-checkpoint-a52/frame.json` SHA256 为 `2e6a4a66c69604f4bedf000362ae47bcd1742fb0c8c8b33016acd0a5d24cf40a`，229 路径、187 Python。唯一生产修改是 settings adapter 的局部类型注解及同值引号格式。去新 import 项与注解后整模块 AST 与 before 相同；原读取函数与 Git 基线相同。运行 reviewer 另独立编译、未执行模块，确认该函数字节码、名字和常量相同。原平台分支、FD 寿命、准入、读取和错误次序不变；所有旧 fixture 字节保持。

三人独立核实实际命令及 stdout：补注解后 137 源通过，加入两个原未改 SDK 后 **139 源通过**。139 集合覆盖全部当前修改生产 Python 及原 C08 的 31 文件，无遗漏；两个额外 SDK 与原 Git 基线逐字相同，不算新增实现。运行器最初计数表达式误减五，实际 argv 前缀为可执行程序与三个选项共四项；已修正元数据而未改命令或结果文本。三份报告均只读取证据，没有代替实施者重跑 mypy 或 pytest。

采用 `--follow-imports=silent`，故结论限上述显式源码，不关闭 A42 默认广依赖 237 错误／8 文件的未解决记录；没有把未运行的 pytest、原生 Windows 或断电场景写成通过。本片生产物理行数净变 0，不计删减收益；原 C08 八千行缺口 3,518、全系统净增 1,325 与完整 Goal 未完成状态不变。实际 229 hash、187 Python Ruff、改源格式、diff 和后续文档核对通过；原命令、输出、整模块 AST 对照、三份报告及其 SHA 保存在产品树外 A52 目录。未提交或远程发布。

## A61：退役旧测试转发层的三视角代码复核

实施 owner 在既有 R3 与 COD-PD-GOAL-001 授权内，接受三个日志模块的有界退役增量；没有接受新架构、协议或平台保证。最终外置 `obsolete-journal-forwarders-a61/frame.json` SHA256 为 `8780df8dda035681bde3add72c31610771127b9fe5ef275302748a5910376b97`，冻结38项对象。职责／复用、运行／失败、数据／兼容三个独立 agent 分别检查该对象、原调用与实际源码，均无具体阻断；完整报告另存产品树外，旧报告与原 expected 未覆盖。

删除的是 Windows deletion／restore 各自的模块级 `_decode_event`、`_validate_sequence`，以及 Windows expiry 的模块级 `_validate_sequence`，不是生产 transaction 的同名方法。五项均未公开导出、没有当前生产消费者。原 transaction、继承方法、配置、公开 API 与存储／清理程序的 AST 保持；Harness 新增0，根目录新增实现0。它们是已由原 Harness owner 接管后残留的测试转发，退役不代表新增或删除五套业务算法，也不承诺第三方继续导入内部私有名称。

四现有测试的18处调用直接接入原 Harness callee，原具体 record、owner_id、label、receipt_id 保持；独立逆转后，非 import AST、全部断言／异常负例及固定预期比较不变。修改前同四完整文件15 passed（4.16s），修改后15 passed（4.19s），不累加数量；三显式源 silent mypy、七文件 Ruff／format 与 diff 通过。三个 reviewer 只读核查，没有冒称自己重跑测试，也未将便携 Windows 逻辑扩大为 native、并发／断电或全依赖通过。

三个完整 Coding 源1,051→1,011，本片原C08／Coding／全系统净减40，原Harness不变。初版辅助计数仅Python，已明确拒用；重新从原Git对象与多语言四根目录独立核算，并由职责和数据 reviewer 各自重算一致。累计原C08−4,576／8K缺口3,424、全Coding−7,121、全生产仍+897，整个Goal保持active／incomplete。其它148个已改生产源与239项原source/test/fixture防护不变；A58广依赖非零退出、原主线skill故障及既有平台验证局限没有因此关闭。

## A81：固定归档证据与完成记录查询的三视角代码复核

在R3原组件关系内，Archive接管确切归档/最新删除证据与expiry物理查证，RestoreJournal接管自身completed记录选择。Product继续持有支持/Desired/路径/ID/DTO/guard及恢复授权；没有引入查询context、第二存储或新逻辑组件，不将A80“非规模净删路线”意见改写为已证明净收益。

职责/复用、运行/失败、数据/兼容三个独立reviewer分别核实际frame与活树、前后完整源码、调用关系及数据/失败次序。原三份静态报告保留，另三份终态补充关闭查询加载来源与完整业务pending：24项旧观察保持，带同进程六函数actor及Code→Core同对象证明的进程60581 exit0；实际24文件业务进程26373 exit0，119 passed、0failed/skip、340.03s；四实际完整源silent-import窄类型exit0。三视角无本片未关闭阻断，实施owner有界接受；不接受整个N01、Goal、默认全依赖图或native Windows。

实际frame SHA256 `9843e2a90d7a8f0c1e0dbe1af42fc39ce306f64e56a8a7976cf06250037d29d4`，接受记录SHA256 `246d1561d5a607369fbc2366b3ff1b2e651b637ec9fc75a53f6d9f287bef6612`。原expected未改，唯一测试变化是退役无实际作用的Code私有patch；原PM故障注入及余AST/全部断言保留。Code−23/Harness+93/系统+70（格式+2）完整计入，任务系统仍+68，原C08最低线差3,401。具体成本、私有接缝边界和剩余项见[推进记录](../coding-convergence-progress.md#固定查询证据归原-archivejournala81)，原始材料在产品树外A81检查点。完整Goal保持active/incomplete，未发布。

## A82：全量职责审计与用户数量口径确认

用户2026-11-07明确选择按整个Coding层验收8K，原C08继续分账但不再有独立8K条件；[实施Goal](../coding-private-data-implementation-goal.md)及当前账目已对齐。历史评审/检查点的原C08缺口不回写，也不再用作当前完成阻断。A81源码未因A82审计改变：Coding净减8,030已达量，系统仍净增68未达整体净减。

三份独立整项审计逐31文件及原接收组件核事实，另以相邻实际prepare callee补全调用边界。父侧已阅读三份报告和三份独立范围补充/重判，综合记录SHA256 `f78e9d791a5f10d9db96bfd1871bba246b5fa93d6f1c488ba48a1768348cd4df`；原材料位于产品树外`final-scope-a82/`。已实现的collector、传输、归档、Journal及动作后端按实际证据确认，不依旧partial文字重复判未开发；合法DTO、根代际前驱/ID/布局、Desired/确认及读写分流不要求整块迁走。

剩余必须关闭的是：Windows目录观察的共同ACL/FD寿命；Archive prepare端口仍回到Coding目录链/mkdir/chmod/uid/reparse/samestat算法；全生产源码最终严格净减少。两个职责余项分别归原Resources收敛，保留实际旧scope及错误顺序，不套更严目录API、不新增context/manager。运行初审的POSIX删除编排R02经R3§3/原OwnerPort durable-replay合同复核后，已撤销完成阻断：原Journal持phase/幂等/append，原native持physical operation，Code的领域集成不等于第二引擎，不为对称强建callback执行器。

PD-A主体及PD-B职责已有可接受事实；PD-A实际prepare closure、PD-C/D上述目录职责与最终系统净量仍未完成。原Windows保留candidate/未原生证明边界，不新增平台开放、CI矩阵、全库测试或付费模型要求。A82不接受完整Goal完成，不预记后续候选净删收益。具体处置见[A82收尾清单](../coding-convergence-progress.md#数量范围确认与收尾审计a82)。

## A83：七处目录观察的三视角实际代码接受

实施owner在R3原Resources边界内接受本次目录scope收敛。三个独立视角实际核六源与三处测试fault-seam重定向，原报告及运行补核分别保留，均无本片阻断。实际frame SHA `fd477e697bf32326f147dc7e7f15b45062f9f57ab89adad8c8cc0483cc851f86`；原63观察保持，七完整文件120 passed，六实际源silent-import窄类型通过。新scope不增加目录准入，旧原Core消费者也使用同一体；status外层ACL保持有副作用的state_root求值时点，recovery仍为0/1/2次短路枚举。Code−33/Harness+48/系统+15全计，不声称净删或native Windows证明。原材料在产品树外`windows-directory-scope-a83/`。本段不接受整个Goal。

## A84–A86：实际收尾与整项技术接受

三个独立agent完成A84目录prepare、A85同体值检查的实际源码及终态复核，另基于A82全31文件/callee审计、A83–A85实际增量与300项未变守卫给出整项判断：职责/复用、运行/失败、数据/兼容均无剩余具体R3阻断。实施owner综合三个正式结论，在既有Goal实施授权内接受PD-A/B/C/D与本Goal本地完成；没有替用户制造新架构/平台接受，未远程发布。

最终source frame SHA `dad4bed8a6c350a3ebc289cf9eaa1d45855da23d71a7f2b8cb3d5f93f56317b2`；实际接受记录SHA `e360d8d432cf6e095a1281a6d346d1e9c674689415f5d34890a32bab8411e0a1`。全Coding145,842→137,755（−8,087），系统634,820→634,794（−26），原C08仅分账7,139（−4,632）。A83+15/A84−1/A85−108全成本计入；A85独立格式分账为结构−96/格式−12，不夸称系统大额净删或性能收益。

真实终态保留：fresh46文件命令421 passed/1 failed（777.07s），因-x未全执行；另外六完整兼容文件154 passed（13.17s），与计划范围重叠不累加。唯一Continuity节点拒绝由独立当前与两原prepare leaf控制得到相同nested writable-ancestor错误；本机工作区0775。该控制不是完整原Git基线，长进程本身未装context插件；未放松原权限/测试/行为、未绕managed wrapper。旧静态pending/初诊stat遗漏及非绿历史均保留，终态补核另存。

原Windows explicit candidate/未native证明、窄silent-import类型而非默认广图绿、既有其他检查限制均不升级承诺，也不作为无具体差异的新门禁。完整报告在产品树外`final-acceptance-a86/`，本轮不再追加无关重构/重复验证；全Coding总体5K–15K计划仍未完成。
