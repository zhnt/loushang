# C09 历史兼容、迁移与快照证据收敛

- Authority: descriptive audit / execution evidence
- Design status: proposed
- Implementation status: partial
- Owner: Coding / Harness Package Product / Resources
- 基线：`23912e28c7b2e71b3feeb04ad686f24084055ff6`，执行开始时已 fetch 并核实等于 `origin/main`。
- 本次仅处理 C09；旧 Coding 整体 Goal 的完成记录不构成本次验收。
- 方法查阅：本机 archmethod clean `master`，commit `0f9bd3ff51afabeaaf76cc38dff1ceb279b7d37e`；未声称已与方法上游同步。

## 范围与审计状态

基线清单为 34 个 Python 文件、8,925 个物理行，含空行、注释、docstring。
已逐文件建立声明、共享导入、源码与测试引用索引。下表“源码引用”是静态模块名引用文件数，
用于发现消费者，不等于调用次数，也不是完整的动态可达性证明。所有文件都有生产源码引用，
本轮没有仅凭 `legacy` 名称或静态搜索结果宣布整文件可删除。

下表明确区分初步归类与实施完成。接受、安装/启用、快照读取和成员清点已分别接通共享实现；其他混合项的完整语义审计和重构仍待完成；
尤其不能将“保旧格式”扩张为保留其中全部校验、codec 和通用协调。
A157 的移除重放、A168 的来源重捕获和 A199 的 local 接受/消费事务均为本次基线，不再计为新收益。

| Coding 文件 | 基线行 | 当前行 | 源码引用 | 职责 | 本轮处置与剩余项 |
| --- | ---: | ---: | ---: | --- | --- |
| `package_cutover_backup.py` | 147 | 147 | 1 | 备份状态 DTO 与 fence/快照关联 | 混合：状态投影保留；关联验证继续审计 |
| `package_epoch_layout.py` | 319 | 301 | 28 | Coding 私有布局、成员命名和 epoch 映射 | 两处成员清点已共享；保旧成员/路径 Profile；其余布局值校验继续审计 |
| `package_legacy_binding_catalog.py` | 391 | 391 | 3 | 接受记录约束下的本地来源目录 | 已复用共享 catalog；继续审计领域验证与 codec |
| `package_legacy_builtin_acceptance.py` | 275 | 200 | 2 | builtin 首次接受及读回 | 固定持久事务已共享；保领域复核与名义 DTO；值 codec 继续审计 |
| `package_legacy_builtin_adoption.py` | 185 | 185 | 2 | builtin 初始选择与重放 | 混合：保选择与历史 ID；bootstrap 协调继续审计 |
| `package_legacy_builtin_review.py` | 436 | 436 | 2 | 旧 builtin 状态审查和冻结 review | 保支持范围、旧格式；通用 review 机制继续审计 |
| `package_legacy_classification.py` | 203 | 203 | 9 | 旧配置键、作用域和状态分类 | 保历史格式映射；通用校验继续审计 |
| `package_legacy_configured_source.py` | 93 | 93 | 5 | 已配置旧 local 来源的匹配 | 保旧配置语义、作用域和匹配规则 |
| `package_legacy_data_trust.py` | 40 | 40 | 9 | 数据资源类型与信任类别映射 | 保产品信任及资源 owner 允许列表 |
| `package_legacy_desired_evidence.py` | 105 | 105 | 6 | 旧 Desired 证据的只读解析 | 保旧格式映射；通用字段/codec 继续审计 |
| `package_legacy_disabled_acceptance.py` | 264 | 185 | 4 | disabled 首次接受及读回 | 固定持久事务已共享；保领域复核与名义 DTO；值 codec 继续审计 |
| `package_legacy_disabled_review.py` | 184 | 184 | 2 | 旧 disabled-only 审查 | 保允许内置项与旧配置语义；公共流程继续审计 |
| `package_legacy_installation_inventory.py` | 514 | 514 | 9 | 旧安装、已移除安装与 builtin 意图清点 | 保状态映射与支持范围；重复聚合继续审计 |
| `package_legacy_instance_evidence.py` | 94 | 94 | 3 | 旧退役 instance 证据解析 | 保旧字节格式到共享事实的映射 |
| `package_legacy_local_acceptance.py` | 427 | 427 | 9 | local 精确 review 接受及重开 | A199 已共享固定事务；保 resource kind、领域复核，codec 待审 |
| `package_legacy_local_adoption.py` | 353 | 353 | 1 | local 接受到绑定/安装/启用的编排 | 混合：保产品顺序政策；共同协调/寿命继续审计 |
| `package_legacy_local_adoption_read.py` | 283 | 283 | 1 | 已采纳状态及 handoff 的只读验证 | 混合：保旧 ID 映射；跨账本投影继续审计 |
| `package_legacy_local_binding_owner.py` | 120 | 120 | 1 | 接受证据与重捕获 Wheel 的绑定 | 混合：保支持类型和批准；发布协调继续审计 |
| `package_legacy_local_installation.py` | 464 | 289 | 1 | 受审来源的安装、启用、精确重放 | 安装/启用整程序已接共享 owner；保来源信任、旧 ID、批准与名义回执 |
| `package_legacy_local_wheel.py` | 92 | 92 | 3 | 旧 local Wheel 重捕获的兼容入口 | A168 已复用来源重捕获；保历史类型及命名绑定 |
| `package_legacy_lock_evidence.py` | 183 | 183 | 3 | 旧 package-lock binding head 解析 | 保旧格式及历史语义；重复验证继续审计 |
| `package_legacy_operation_evidence.py` | 271 | 271 | 4 | 旧管理操作及退役捕获证据 | 保旧状态解释；通用记录机制继续审计 |
| `package_legacy_reacquisition.py` | 90 | 90 | 4 | 旧安装证据和 Wheel 的关联 | 已复用重捕获；保历史安装/资源准入关联 |
| `package_legacy_removed_acceptance.py` | 200 | 172 | 3 | removed 首次接受及读回 | 固定持久事务已共享；保领域复核与名义 DTO；值 codec 继续审计 |
| `package_legacy_removed_adoption.py` | 130 | 130 | 2 | 移除选择保留与 builtin 后续采纳 | A157 已复用移除重放；保历史 ID，bootstrap 协调待审 |
| `package_legacy_removed_review.py` | 788 | 788 | 2 | 已移除 local 与 builtin 的冻结审查 | 大块混合：旧形状/格式保留，通用 review 协调待审 |
| `package_legacy_review.py` | 409 | 409 | 3 | 活动 local 安装 review 与冻结身份 | 保历史 ID/格式/支持；公共验证和 DTO 机制待审 |
| `package_legacy_skill_cutover_admission.py` | 594 | 594 | 5 | Skill/Prompt/Theme 的首次 cutover 准入 | 保信任/资源支持范围；底层 Wheel 检查复用情况待审 |
| `package_legacy_snapshot_member.py` | 198 | 133 | 11 | 首个 B fence 的证据读取与枚举 | 完整快照绑定/读取/观察已共享；保证据域允许列表和布局适配 |
| `package_legacy_source_consumption.py` | 172 | 172 | 2 | 已接受来源配置的消费及恢复 | A199 已共享事务；保旧键、作用域、产品 receipt 格式 |
| `package_legacy_source_evidence.py` | 140 | 140 | 4 | 冻结 Source 配置的解析 | 保历史投影格式；通用校验继续审计 |
| `package_legacy_windows_receipt.py` | 67 | 67 | 18 | Windows 私有回执的兼容入口 | 底层已共享；保错误身份和历史 I/O Profile，不重复迁移 |
| `package_pre_b_snapshot.py` | 448 | 448 | 8 | 首个 B 快照/切换与重开编排 | 混合：原生 owner 已共享；保产品成员映射，残留寿命待审 |
| `package_source_snapshot.py` | 246 | 246 | 3 | 旧 Settings 冻结投影和 source 快照 | 混合：配置读取已复用；投影 codec/持锁与目录寿命待审 |

## 首批：三种非 local 接受事务

原 builtin、disabled、removed 接受入口共享同一固定机制：
先取得回执独占锁，读取并校验已有接受记录；首次接受时再取得 Desired 独占锁，
要求其尚未被采纳，使用原私有回执发布器持久化，然后验证 epoch。
此完整机制收敛到既有 `package_product._legacy_local_migration._FirstAcceptanceJournal`，
没有另建迁移框架，也没有引入 Protocol 或 supplier。

Coding 继续执行当前受认证 review 的生成、操作员 review ID 匹配、Store 关联、
支持范围检查以及读回时的领域复核。三个公开名义记录、声明字段、错误类型和导出入口保留。
三种记录的公共 codec/值验证仍在待审清单内，不能因此宣布这些文件已全部领域化。

必须保留的差异：

- POSIX 读取及 Desired 诊断原先共同使用 disabled 错误类型与标签；移除和 builtin 不得改成各自错误类型。
- removed 发布使用 combined 父目录后验检查；另外两条保留 separate，包含失败优先级差异。
- builtin 已接受重放会再次检查 epoch；另外两条原先没有该次额外检查。
- disabled 读回区分“文件不存在”和“空记录”；空文件仍触发领域 review 及冲突诊断。
- builtin 的 Windows 接受允许精确未发布 stage 恢复，普通读回禁止该恢复。
- Windows 继续借用原 `WindowsPrivateReceiptIO`，不改变 ACL、named stream、reparse point、大小上限及 rename 语义。

底层 byte I/O、根目录约束、文件锁与 JSONL 引擎直接复用现有 Journal / Resources。
新增内容是三条路径共用的固定接受事务及诊断 Profile；A199 的 local 专用事务不计为本轮迁移。

## 验证与成本

已完成的局部验证：

- 接受事务和既有导入边界：220 passed（最后清理五个无消费者的私有转发前）；初轮 55 项不重复累加为覆盖收益。
- 新安装/启用整程序：6 passed，26 deselected，既有用例覆盖 Prompt/Skill/Theme、重放与独立变更拒绝。
- 安装 runtime 生命周期本地差分：20 passed，逐项对照基线原 `_route_install` 的结果、调用顺序与异常链，包含 factory/create/activate/route 失败、无效 outcome 与清理失败。观察脚本在产品树外，不新增 PR 门禁。首次因未加载项目 conftest 的调用未收集用例，修正配置后实际执行通过。
- 首 B 快照、旧根变化、观察权限和恢复整场景：1 passed，31 deselected。
- 新目录清点及切换/bootstrap 回归：22 passed。
- 当前全部十个改动源码文件的 Ruff 和 mypy 均通过；`git diff --check` 通过。
- 文档约束 9 项和依赖事实检查为首批结果，当前新增改动及文档仍需复核。

最早启动的 CLI/安装清点/快照宽回归已结束：179 passed，1966.05 秒。
其收集时尚未包含后续安装与快照改动，不能作为后续候选的完整验证。
最终仍须运行完整 diff 的适用 PR 本地门禁。Windows 原生场景尚未在本机验证，
不以 Linux 纯编码或假对象故障观察代替原生平台验证。

当前相对基线：Coding −440，Harness +532，其他生产源码 0，生产 Python 合计 +92。
C09 当前 34 文件、8,485 行。以下分别列出每批净成本，不能把 Coding 净减少冒充系统精简或纯重复删除量：

| 批次 | Coding | Harness | 系统净变化 | 单一 owner 与去重 |
| --- | ---: | ---: | ---: | --- |
| 三种非 local 接受 | −143 | +174 | +31 | 三套接受循环合一；原 Journal / Windows receipt IO 直接复用 |
| 无消费者私有胶水清理 | −39 | 0 | −39 | 删除五个无调用者私有转发及失效常量，含必要格式净变化 |
| local 安装/启用及 runtime 寿命 | −175 | +218 | +43 | install/enable 共同初始历史校验合一；legacy 与 bootstrap 共用 runtime 生命周期 |
| 首 B 快照读取/观察 | −65 | +115 | +50 | 继续使用两原生 SnapshotEvidenceStore；Product 关联与读取后复核归 Legacy owner |
| 两种旧根成员清点 | −18 | +25 | +7 | 目录枚举/类型/硬链接检查合一；旧成员允许列表保 Coding |
| 合计 | −440 | +532 | +92 | 职责收敛，尚不是系统净精简 |

五个私有胶水删除是独立清理收益；通用程序迁入量与重复删除量尚未按每个物理行唯一归因，
因此不把迁出行数重复报为删除收益。已有 A157/A168/A199 能力均未重计。
测试源码未增加，本地故障观察脚本在树外；文档单列，不混入生产成本。

## 已接通的安装与快照链路

`_LegacyLocalInstallation` 借用现有 Product Desired、Management、handoff 和 factory。
Coding 先复核批准、资源类型与精确可信来源，再传入已选择的 installation key、历史操作 ID 和错误身份。
共享程序负责安装前状态、首次安装历史、精确两次启用历史、CAS 提交及最终复核，
Coding 在返回前保留原 epoch 复核和名义回执构造。没有替代 Desired、handoff 或 Package engine。
`_product_plugin_runtime` 同时用于原 bootstrap 与 legacy，保持创建失败时释放 unbound factory，
激活后所有退出释放 binding；清理失败对原失败的优先级未变。

`_LegacyFirstSnapshot` 从原两平台快照 owner 借用已认证的 first-B 证据，
负责 fence/store/control-root 关联、只读成员访问后的 epoch 复核以及 observation 关联。
Coding 仅保公开类型、证据域允许列表、布局解析和错误 Profile；旧私有 tuple helper 无外部消费者，已替换。
目录清点复用 `product_pre_b_snapshot.inspect_legacy_product_member_names`，
保留旧 lstat/listdir 顺序、成员类型与硬链接限制，不附加新的 ownership/权限准入规则。

## 后续验收

1. 完成表内所有混合项的语义审计与 disposition，按整链处理安装、启用和读取投影；不能只处理本批回执就关闭 Goal。
2. 收敛通用 review/记录机制、来源目录残留机制，以及 fence/快照/切换寿命；保留真实产品政策与旧格式映射。
3. 确认各完成链路单一 owner、旧实现与无效胶水已删除，说明每个 Coding 保留项的证据。
4. 对完整 diff 运行适用本地检查、远端平台检查，完成 commit/push/PR/merge/本地同步后按用户指令暂停 Goal。

整体逐文件清单见 [Coding 职责清单](coding-responsibility-inventory.md)。
