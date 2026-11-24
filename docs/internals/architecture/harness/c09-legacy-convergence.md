# C09 历史兼容、迁移与快照证据收敛

- Authority: descriptive audit / execution evidence
- Design status: accepted — implementation-owner review within C09 scope
- Implementation status: implemented; locally validated
- Owner: Coding / Harness Package Product / Resources / Plugin Management / Resource Item Authoring
- 基线：`23912e28c7b2e71b3feeb04ad686f24084055ff6`，执行开始时已 fetch 并核实等于 `origin/main`。
- 本次仅处理 C09；旧 Coding 整体 Goal 的完成记录不构成本次验收。
- 方法查阅：本机 archmethod clean `master`，commit `0f9bd3ff51afabeaaf76cc38dff1ceb279b7d37e`；未声称已与方法上游同步。

## 范围与逐文件结论

基线为 34 个 Python 文件、8,925 个物理行，含空行、注释、docstring。
本轮已逐文件核对声明、共享导入、源码消费者、迁移支持范围和旧数据依赖。
下表引用数是当前 `src` Python 文件的静态模块名匹配，不是调用次数或完整动态可达性证明。
完整引用路径与 SHA 在本地审计记录中；未因 `legacy` 名称删除整文件，也未因 Coding 类名保留通用机制。

保留格式规则不是默认保留 DTO 的全部实现：共同 envelope、备份值约束、Wheel 字段/惰性检查已共享。
其余规则对应 Coding 的旧 v1/v2/v3 字段、允许的状态组合、资源范围、作用域和身份配方；
JSON/Journal/Schema/Snapshot 引擎仍复用既有组件，不在产品层另建持久化或恢复实现。
A157、A168、A199 为本轮基线，不再计为新收益。

| Coding 文件 | 基线行 | 当前行 | 当前源码引用 | 明确保留项 | 通用机制/边界核实 |
| --- | ---: | ---: | ---: | --- | --- |
| `package_cutover_backup.py` | 147 | 73 | 1 | 共享机制已收敛；保名义 DTO、旧展示字段及 Coding 错误标签 | 备份关联和通用值约束归 Legacy Runtime；不在产品输出中冒称 expiry 已知 |
| `package_epoch_layout.py` | 319 | 301 | 28 | 保 Coding 根几何、旧文件到域的映射及对应格式约束 | 两套目录枚举/成员类型检查已共享；路径名、workspace/store 前缀和旧成员分类属于产品 Profile |
| `package_legacy_binding_catalog.py` | 391 | 391 | 3 | 保旧 binding v1/v2/v3 格式、资源类型/信任及批准匹配 | 既有 _LegacyLocalSourceCatalog 承担 Journal、重放、发布；保名义记录、构造 Profile 和公开类型转发 |
| `package_legacy_builtin_acceptance.py` | 275 | 179 | 2 | 保 builtin review 类型、批准选择、Store 匹配和名义记录 | V1 envelope/identity/锁/读写/重放已共享；to_dict 是既有字段映射 |
| `package_legacy_builtin_adoption.py` | 185 | 131 | 2 | 保显式 Windows 候选准入、已审 builtin 选择与移除 ID | 原 bootstrap owner 统一执行历史复核和采纳；保应用 owner 适配及 finally 归还 |
| `package_legacy_builtin_review.py` | 436 | 436 | 2 | 保旧 builtin 状态、removed/disabled 支持范围及冻结格式 | 文件和证据读取复用共享 Snapshot；各版本字段/选择约束是旧 Coding 数据语义 |
| `package_legacy_classification.py` | 203 | 203 | 9 | 保旧配置键、作用域、过滤器和 workspace 分类 | 纯格式/政策映射；无持久化、事务重放或原生文件控制实现 |
| `package_legacy_configured_source.py` | 93 | 93 | 5 | 保 local:/ 来源、最多 16 项、单作用域及 builtin disable 准入 | 纯冻结配置匹配；不消费 Settings、不授予 Source 发布权限 |
| `package_legacy_data_trust.py` | 40 | 40 | 9 | 保 skill/prompt/theme 与允许 owner/trust class 的产品表 | 显式产品信任政策；不移动到基础设施或在检查器中授予权限 |
| `package_legacy_desired_evidence.py` | 105 | 105 | 6 | 保旧 Desired 字段/版本及其到共享事实的映射 | 读取复用共享首 B Snapshot，journal/记录解析器沿用现有组件 |
| `package_legacy_disabled_acceptance.py` | 264 | 164 | 4 | 保 scoped disable 的 builtin 允许列表、批准和名义 DTO | 共同 envelope 与完整接受事务已共享；保历史错误身份 |
| `package_legacy_disabled_review.py` | 184 | 184 | 2 | 保 disabled-only 形状、合法旧配置与 review 字段 | 无通用 I/O 引擎；冻结 snapshot 观察已共享，版本/字段约束属于旧格式 |
| `package_legacy_installation_inventory.py` | 514 | 455 | 9 | 保旧 installed/removed/builtin 选择、支持集合和 lock head 的产品匹配 | 底层 Desired/Journal/Snapshot 与最后 install/update/remove epoch 证明已共享；仅保旧安装选择及绑定匹配 |
| `package_legacy_instance_evidence.py` | 94 | 59 | 3 | 保字节配额、Coding 名义输入与旧 lifecycle 路径映射 | graceful retirement/无 open family 证明归原 Instance Runtime；不重建原生 runtime 或日志引擎 |
| `package_legacy_local_acceptance.py` | 427 | 427 | 9 | 保 resource kind、旧 review/receipt 格式及 live/frozen 领域复核 | A199 的 local 固定事务直接复用；不重计为本轮迁移 |
| `package_legacy_local_adoption.py` | 353 | 338 | 1 | 保逐项明确批准、资源类型、绑定/安装/启用的产品顺序 | 安装/启用和 builtin 采纳已共享；短程应用 owner 借用属于产品集成，不复制 close 实现 |
| `package_legacy_local_adoption_read.py` | 283 | 176 | 1 | 保资源类型/可信 Wheel 匹配、旧 ID 配方及已审选择 | handoff/Desired 关联和稳定捕获归共享读模型；不将读路径升级为可写 owner |
| `package_legacy_local_binding_owner.py` | 120 | 120 | 1 | 保批准 review 与重捕获来源/manifest/lock/资源类型的精确匹配 | 只调用已有 Catalog 发布/append；不自持字节 I/O、锁或发布恢复引擎 |
| `package_legacy_local_installation.py` | 464 | 289 | 2 | 保 POSIX 迁移准入、批准选择、信任来源、旧 ID 和名义回执 | 安装/启用/历史复核/runtime 生命周期均已共享；不创建第二个 Package engine |
| `package_legacy_local_wheel.py` | 92 | 95 | 3 | 保名义 candidate 九字段、公开签名及旧输入/平台准入 | A168 重捕获仍用原 Core；空 slots 字段契约和惰性检查复用原 producer 模块 |
| `package_legacy_lock_evidence.py` | 183 | 183 | 3 | 保旧 package-lock/binding head 字段和支持版本 | 从共享 snapshot 读入，只做旧格式与状态关联；字段遍历复用 RecordSchema 等既有能力 |
| `package_legacy_operation_evidence.py` | 271 | 149 | 4 | 保旧管理文件组合、名义 capture、输入配额与错误 Profile | operation/Desired/retirement 一致性证明归原 Management service；不在 Coding 重放、持久化或判定通用终态 |
| `package_legacy_reacquisition.py` | 90 | 90 | 4 | 保已选旧安装、原 Source 来源与前后冻结证据一致性 | 实际重捕获、私有 capture 和清理用 A168；两行标准库暂存 scope 是调用方集成，不复制引擎 |
| `package_legacy_removed_acceptance.py` | 200 | 153 | 3 | 保已移除 review、批准 ID、名义记录和旧诊断 | V1 envelope 和固定接受事务已共享；combined 发布检查差异保留 |
| `package_legacy_removed_adoption.py` | 130 | 127 | 2 | 保 local/builtin 旧移除选择及各版本 operation ID 配方 | A157 tombstone 直接复用；共同 builtin 采纳已接原 bootstrap owner |
| `package_legacy_removed_review.py` | 788 | 788 | 2 | 保旧移除快照形状、v1/v2、retained roots、head/operation 语义 | 读取/通用 snapshot 证明已共享；这些跨字段规则是历史格式与产品支持范围，非因 Coding 类名保留 |
| `package_legacy_review.py` | 409 | 409 | 3 | 保活动 local review 冻结格式、批准字段和旧移除 ID | 现有 Core adoption evidence 与 Snapshot 观察直接复用；保公开 DTO 和历史身份配方 |
| `package_legacy_skill_cutover_admission.py` | 594 | 451 | 5 | 保最多 16 个数据资源、允许类型/old shape 与 Product 首次准入 | 完整惰性 Wheel 检查归既有 Resource Item authoring owner；保 nominal gate 和原拒绝/批准语义 |
| `package_legacy_snapshot_member.py` | 198 | 133 | 11 | 保公开观察者/类型别名、证据域允许列表及 Coding 布局适配 | first-B fence/store/snapshot 关联、读后复核与观察投影全部共享 |
| `package_legacy_source_consumption.py` | 172 | 172 | 2 | 保冻结来源映射、作用域、旧 receipt 内容及产品消费者入口 | A199 事务和恢复直接复用；稳定 Settings 复核沿用本轮共享 Profile |
| `package_legacy_source_evidence.py` | 140 | 140 | 4 | 保 coding Source 投影 v1、两作用域路径与旧键解析 | 读取共享 Snapshot；纯历史格式解释，不新建 Settings/store owner |
| `package_legacy_windows_receipt.py` | 67 | 67 | 18 | 保错误类型、大小上限、stage/rename 兼容 Profile | WindowsPrivateReceiptIO 已共享，原样复用；不重计早先迁移收益 |
| `package_pre_b_snapshot.py` | 448 | 380 | 8 | 保 fresh/Windows 候选/产品批准、根与域映射和公开准备 DTO | 原生根准备、临时目录、投影读取与 cutover owner 已共享；保领域 snapshot_admission 回调 |
| `package_source_snapshot.py` | 246 | 123 | 3 | 保旧键、key markers、文件名/产品标签和兼容入口 | Settings 锁、稳定读取、投影/临时目录和清理由原 Package Product/Config/Resources 组合承担 |

C09 中已无 `os.open/fdopen`、原生目录枚举/修改或自定义文件发布、锁、持久化实现。
静态核实仍有两处直接 `TemporaryDirectory` 调用：review 和 pre-fence 的一次性 staging。
它们借用现有标准库组件后调用原 Harness 重捕获；这是领域调用方的短程集成，没有复制清理算法。
没有为消除这两行调用再增加一层无职责包装或把批准逻辑回调进底层。

## 首批：三种非 local 接受事务

原 builtin、disabled、removed 接受入口共享同一固定机制：
先取得回执独占锁，读取并校验已有接受记录；首次接受时再取得 Desired 独占锁，
要求其尚未被采纳，使用原私有回执发布器持久化，然后验证 epoch。
此完整机制收敛到既有 `package_product._legacy_local_migration._FirstAcceptanceJournal`，
没有另建迁移框架，也没有引入 Protocol 或 supplier。

Coding 继续执行当前受认证 review 的生成、操作员 review ID 匹配、Store 关联、
支持范围检查以及读回时的领域复核。三个公开名义记录、声明字段、错误类型和导出入口保留。
三种记录的共同 V1 envelope、identity 与失败包装已共享；保留的 create 检查和 wire 字段映射是产品准入/旧格式适配。

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

最终 28 个变更生产源的 mypy、29 个 Python 文件的 Ruff 均通过；34 个 Coding 模块的公开导出及 172 组公开签名/名义字段声明保持基线契约。既有 CLI 的 636 个断言 AST、45 个测试入口及参数化未变；测试源码净增 9 行，仅适配已迁至真实共享 bootstrap owner 的故障注入点，没有新增 case、断言、测试路线或 PR 门禁。

使用原 `scripts/ci/check_changed.py --base origin/main` 选出的全部可本地执行路线，原脚本顺序执行并返回 0：

| 既有路线 | 通过 | 跳过 | 未选中 |
| --- | ---: | ---: | ---: |
| Coding | 4,240 | 24 | 76 |
| Harness（含原架构/运行支持检查） | 6,356 | 113 | 0 |
| Hosting（含原消费者检查） | 513 | 60 | 0 |
| unit_coding | 4,238 | 24 | 78 |
| unit_harness | 5,939 | 110 | 3 |
| unit_hosting | 397 | 56 | 4 |

各路线存在覆盖重叠，不将表中数字相加宣称唯一测试数。文档不变量 9 项、生成依赖事实、Harness 909 源及 Hosting 36 源的既有类型检查亦通过。完整 Coding 路线包含现有 session/tool/persistence/resume 与取消/退出 smoke；不以仅静态导入代替真实会话行为证据。

补充的局部兼容观察覆盖安装/启用故障、首 B 快照、接受记录、备份、源码重捕获、配置投影、管理/退休/Instance 证明及公开值类型的字段、slots、pickle；完整导入边界/Resource Item/Wheel/名义 ABI 组合为 211 passed。惰性检查逐语句 AST 对照中，仅分离名义入口/返回适配，其余校验语句及三类路径 regex 与基线相同。本地差分脚本位于产品树外，不进入 PR 门禁，也不重复计入表中唯一覆盖。

本机原固定 runtime 目录的祖先 775 权限及 AGENTS.md 会影响安全准入与 context 发现；用户在目录例外请求后指示继续，本轮仅测试命令临时使用 `/home/dev/.cache/loushang-tests-c09`。不改变工作区权限、正常 Product/AppHost runtime 路径或其他 lanes 规则。安全选择器显式传给外层 pytest，Make 使用既有 `PYTEST_RUNNER` 变量；不把项目专用 `--skip-host-runtime` 写入全局 `PYTEST_ADDOPTS`，避免污染测试内临时仓库的独立验证。39 个受该调用问题影响的现有场景复跑全部通过，随后完整原检查计划通过，没有修改 Product 语义或测试断言。

相对基线的生产源码变化：Coding −1,301，Harness +1,721，其他 0，合计 +420 行。
C09 当前 34 文件、7,624 行。职责收敛已完成实现候选，但不冒称系统净精简。

| 批次 | Coding | Harness | 系统净变化 | 归属/实际去重 |
| --- | ---: | ---: | ---: | --- |
| 首批三类接受 | −143 | +174 | +31 | 三套接受循环合一，继续用原 Journal/Windows IO |
| 无消费者私有胶水 | −39 | 0 | −39 | 五个私有转发和失效常量清理，含格式净变化 |
| local 安装/启用与 runtime | −175 | +218 | +43 | 共同历史验证和 runtime 生命周期合一 |
| 首 B 快照读取/观察 | −65 | +115 | +50 | 原 SnapshotEvidenceStore 上统一关联与复核 |
| 两种旧根清点 | −18 | +25 | +7 | 枚举/类型/硬链接检查合一 |
| 剩余整链收敛（相对 a25a77e91） | −861 | +1,189 | +328 | 配置投影、读模型、共同 envelope、三种 builtin 采纳、备份关联、原生 cutover、惰性检查及通用跨账本证明 |
| 合计 | −1,301 | +1,721 | +420 | 字段契约和薄适配增加，系统源码略增 |

通用程序迁入量与纯重复删除量未按每个物理行做唯一归因，因此不把 Coding 减少量再报成重复删除收益。
实际去重单位包括三套接受循环、两套目录清点、三条 builtin 采纳循环、共同 envelope、重复初始历史证明和 runtime 生命周期。
保留原错误/Profile/名义类型所需的适配和空 slots 字段契约均计入总成本，文档与测试单列。

职责迁移量按完整机制分组统计为 12 组：非 local 接受事务、接受 envelope、local 安装/启用、runtime 寿命、已审 builtin 采纳、首 B 快照观察、备份关联、原生 cutover/旧根资源处理、配置投影、只读采纳证明、惰性 Wheel 检查、管理/退休/Instance 证据证明。分组用于说明职责覆盖，不代表迁移百分比或可相加的行数收益。

重复删除量单独按旧流程体统计，下表给出保守可核实的 8 个重复体退出；其余迁移不强行归为重复删除。

| 共同机制 | 原流程体 | 当前共享流程体 | 重复体退出 |
| --- | ---: | ---: | ---: |
| builtin / disabled / removed 固定接受事务 | 3 | 1 | 2 |
| 三条已审 builtin 采纳循环 | 3 | 1 | 2 |
| 三类接受记录共同 envelope 校验 | 3 | 1 | 2 |
| 两种旧根成员枚举与类型检查 | 2 | 1 | 1 |
| bootstrap 与 legacy 安装的共同 runtime 寿命 | 至少 2 | 1 | 至少 1 |
| 保守合计 | 至少 13 | 5 | 至少 8 |

这些是机制实现体的计数，保留的产品调用入口不计为重复体。另退出 5 个无消费者私有转发及失效常量，按胶水清理单列；它们不增加上述重复流程计数。通用化、Profile 和兼容适配的新增行已全额计入生产系统 +420，未将按流程计数的去重换算为未经证明的行数。


测试净变化 +9 行；文档净变化 +173 行（含本文与职责清单），均不计入生产源码 +420。

## 共享 owner 与兼容边界

- `_legacy_local_migration`：固定接受/消费事务、安装/启用、配置投影和只读采纳证明；既有 Config、Journal、Desired、Management、handoff 和原生 Resources 继续承担实际工作。
- `_plugin_bootstrap`：原 bootstrap、移除保留、共同 runtime scope 和已审 builtin 采纳；严格 first-adoption 与 active-local plugin-only 历史语义分别保留。
- `_legacy_runtime`：原 startup/liveness、首 B snapshot 借用及备份关联。普通备份查询仍可关联任意当前 fence，不错误套用 first-epoch-only 条件。
- `product_pre_b_snapshot`：原快照/cutover owner、旧根清点、根准备、临时投影与字节读写。继续调用既有私有目录链和 Windows 原生目录 owner。
- `product_legacy_source_wheel`：保原重捕获/构建及空 slots 字段契约，不改变 Coding candidate 自有字段、构造、冻结、pickle。完整惰性检查归既有 `plugin_authoring.resource_item`，直接使用该 owner 原有的 Resource Item payload codec；Coding 调用共享函数，candidate 子类不能覆盖检查。Resources 不反向依赖 Authoring。
- `plugin_management.retirement/service/instance_runtime/retirement_sets`：在原 capture decoders 上承接最后闭合 epoch、终态操作关联及 graceful Instance 证明；Code 保单个 Installation 的已验证历史选择、旧绑定匹配和错误 Profile，不另造 decoder。
- `_local_source_catalog`、原 Resource/Journal/Config 组件：已共享能力直接复用，没有第二个 catalog/store/ledger 或通用迁移框架。

保留的重要差异：POSIX 读取/Desired 诊断原先共用 disabled 错误类型；removed 用 combined 父目录后验检查；
builtin 重放额外复核 epoch；disabled 空文件不是不存在；Windows 接受可完成精确 stage 重试，普通读回不修复。
原生 cutover 不改写已有不安全目录权限，所以没有替换成会 chmod 既有目录的另一套私有树准备器。
配置投影保留原 json.dumps 语义，未盲目替换成额外收紧输入的 canonical_json_bytes。
Coding 的公开记录仍保自身声明字段、slots、模块路径和名义类型；共享空 slots 基类只承接既有值规则。

## 完成审计与保留义务

34 个文件已逐一核对调用方、支持范围、旧数据依赖和共享 owner；旧通用实现及无消费者胶水同步退出。Coding 剩余 7,624 行的具体保留理由见逐文件表，包括产品信任/批准、旧版本字段与允许组合、操作员选择、资源/作用域准入和必要名义入口；不以类型名含 Coding、legacy 字样或任意迁移百分比替代判断。

各通用链路沿现有 owner 收敛，没有第二个 catalog/store/ledger、并行迁移框架或大量 Protocol/回调/supplier 拼接。A157、A168、A199 是本轮基线，已共享机制不重复计为收益。清单中的退出候选需要真实存量与消费者证据，不能据此删除未证实可退出的历史支持。

职责边界复核由 Codex 实现 owner 在本任务授权范围内完成；以实际单一 owner、公开契约与无环依赖、兼容差分和完整本地检查作为接受证据，不声称用户另行批准架构或协议修订。macOS/Windows 原生、安装/真实 LSP、Host Runtime 等平台检查沿用既有 Actions 路线，本机结果不替代这些平台证据；交付检查及合并记录以关联 PR 为准。

整体清单见 [Coding 职责清单](coding-responsibility-inventory.md)。

## pre-B 准入复核

实施 agent `/root` 在 `4f3a7899e` 上复核并接受 Package Product 与 Coding 的
准入边界，采用本地架构方法 `0f9bd3f`。现有 Source 投影先检查内存设置，再按
默认路径和显式路径的原顺序读取磁盘；旧状态检查先观察生命周期根，再观察
Package 根。允许缺失目录的入口只跳过直接观察为不存在的根。Coding 绑定旧字段、
路径和目录清单。中断启动复用已认证快照的 Source 分类结果，删除对同一设置的二次检查。

本批 Coding −49 行、Harness +46 行，系统生产 Python −3 行。Linux 上与 cutover
和普通会话相关的 161 项通过，4 个 Windows 原生用例跳过。旧字段库存检查通过。
