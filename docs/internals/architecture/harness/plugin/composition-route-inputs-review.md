# D2 装配路线与共同输入准备：三视角独立设计评审

## 框架

- 对象：[专项设计](composition-route-inputs.md) R1 独立初评及 R2 定向复核；前半记录设计阶段，后半追加第一切片代码评审与实施验证。
- 基线：main `ff29a80e422ba296f1cc3711c51ffc68163a6e65`，Harness HEAD `0e2aeeb056fd855a6988638e3eec8a77ca4eaf65`，完整 tree 相同。
- 方法：本地干净 archmethod master `0f9bd3ff51afabeaaf76cc38dff1ceb279b7d37e`。
- 授权：用户要求推进 D2，先做专项设计；先前三视角独立评审和重要图/合同由用户审阅的要求继续适用。
- 视角：职责与复用；运行与失败；数据、兼容与验证。审核原 selector/实际交接与所选最小输入准备切片，不能为缺失机制补造解释。

三个视角分别由独立 `gpt-6.1-sol`、xhigh agent 执行。初评均读取实际源码与既有合同，未读取其他视角报告或预设结论；三份初评齐备后，作者统一修订 R2，再分别复核修订影响。没有运行产品、导入产品模块或执行 pytest/native/异步/付费模型试验。

## 固定版本与评审结论

| 版本 | SHA-256 | 用途 |
| --- | --- | --- |
| R1 | `3acacad56f802e1517dbbf49fb482e481ef8a93b0edab8df04564d39a1c325b3` | 三个视角的独立初评 |
| R2 | `6dd9d2fb21a60e92f5a756948a6a92df70295237b94ef6a1334897a5cca23c97` | 同批修订后的定向复核；状态更新前的固定设计快照 |

| 视角 / 独立评审者 | 初评 | R2 复核 |
| --- | --- | --- |
| 职责与复用 / `d2_ownership` | 无阻断；O1 建议明确显式注入旁路与公开 API 范围 | O1 关闭；私有 helper 的收窄保持职责与复杂度边界，无新增发现 |
| 运行与失败 / `d2_runtime` | 无发现；保留原异常顺序、当前性核对及不同关闭责任 | 无新增发现；原候选投影阶段和后续错误前缀保持 |
| 数据、兼容与验证 / `d2_data` | 无 P0/P1；D2-DATA-01 为 P2，需明确规范 kind 集合的真实用途 | D2-DATA-01 在设计层面关闭；身份、顺序和保护约束保持，无新增发现 |

结论：R2 可提交用户评审，未关闭发现为 0。此结论仅表明限定设计在静态核查下自洽，不代表实现已通过、重要图已获用户接受或 D2 全部完成。

## 建议处理与关闭依据

| ID | 原问题及源码依据 | R2 处理 | 关闭范围 |
| --- | --- | --- | --- |
| O1 | `bootstrap.py::create_agent_session` 允许显式 factory 绕过自动 selector；initial assembly 仅属于私有 `_create_agent_session` 输入。R1 图及措辞未充分区分 | §1/§2 明确自动选择、SDK 显式 factory、内部 initial assembly 三支；DI-1/DI-2 分别要求不重选、不重建 | 职责视角独立复核关闭；未扩公开 SDK API |
| D2-DATA-01 | `test_plugin_contribution_type_system.py:61–67` 要求 Coding 与 Harness 均消费规范 kind 集合；全部提取会与“原 gate 不变”冲突 | §3/§5 保留 Coding wrapper 原过滤和已有 Harness 候选投影，完整 tuple 才传 helper；无死 import、占位文字、重复新增检查或 gate 变更 | 数据视角独立复核关闭设计约束；尚未运行原 gate |
| 身份验收补充 | `ProductContributionOwnerBinding.authority` 为 `compare=False`，仅值比较会漏掉授权对象替换 | §4 要求直接核对 supplied binding 和 authority 对象身份；默认 owner 核对原全部政策字段与 TTL；原 plan 仍按值相等 | 三视角复核无新增发现；运行验收仍属后续工作 |

采纳的是有实际源码与保护依据的修订；没有为收敛而新增路线记录、统一 owner、授权缓存、政策引擎或第三个 composer。候选投影本来已由 Harness 共享，保留 Coding 的调用不构成第二套投影实现。

## 协同判断

- 路线权威留在原 Coding selector，direct-owned 与 application-borrowed 寿命分别保留；None 不等同于 legacy。原初始化/恢复/锁与平台分支不被包装成纯查询。
- 输入准备仅整理 owner 需求与 supplied 结构；Coding 继续决定 exact/default 政策，后续原 Harness admission/compiler 保留独立 provenance 与精确授权检查。前置二元分组键不能替代后续三元准入键。
- 原 workspace/epoch/manifest current recheck、pinned generation、deferred LSP、Resume 和 D1 关闭凭据不受此切片替代。helper 不取得资源、不清理、不创建任务或锁。
- 按当前限定范围，无需新增公开架构决策或公共 facade；若实施改变路线权威、公开协议、恢复语义或 owner 寿命，须先回到共同父级设计。
- 这次收益是现有混合职责的拆分，不是消除三套独立编译内核，也不声称启动速度或读取次数改善。更广泛的 bootstrap 收敛仍需另有重复语义证据。

## 设计阶段验证与局限

设计阶段已静态核对 16 份源码/测试文件的 SHA 与基线相同，Harness 提交 tree 与 main 相同；当时变更限于三份文档。轻量文档检查 9 项断言、变更文档链接和 `git diff --check` 通过；这些结果不代替 DI-1—DI-7 的后续实现差分或运行测试。

本轮不验证并发、取消、磁盘故障、hosted 运行或各平台原生行为；原测试的存在不等于本轮执行通过。首切片仍须验证异常优先级、完整对象身份与原外层 custodian/close 轨迹。不扩大现有 PR gate。

原始报告、冻结设计、源码清单及静态检查记录位于产品树外：`/home/dev/lsspace/architecture-analysis/plugin-harness-audit-20261104/d2-composition-route-inputs/`。最终报告摘要可由以下 SHA-256 复核：

| 原始报告 | SHA-256（含 R2 追加） |
| --- | --- |
| `review-ownership.md` | `723e6bf4e79673d108603eff041d86522f0b0114a174e9f0666045736a45ffa5` |
| `review-runtime.md` | `d6e660f1f68aadded53e901b862a1166b5689e5091960a0fbfaf4cc1a3649f8e` |
| `review-data.md` | `5b7dd73f03a24e39a729783627034af0380aaff6a15f1ffb2ef64aa2f822338b` |

## 设计阶段接受状态（历史）

Design status 仍为 proposed；Implementation status 为 not-started。用户明确要求“系统环境图等重要工作件需要我评审”，本轮也明确“先做专项设计”；因此把 R2 §2 环境图、§3—§5 职责/接口/交互合同作为用户评审对象，尚未启动代码实施。内部评审不替代用户接受，不记录虚构的批准。

## 第一切片实施与代码评审

2026-11-04，用户在收到上述设计和实施建议后明确指令：“实施 D2 第一切片：拆分共同输入准备与 Coding 策略”。据此接受和实施限定切片；没有据此接受 D2 的更广泛路线合并或升级公开合同。下列记录更新当前状态，前面的设计初评仍作为历史保留。

实现限于两份源码：

- 原 Harness `session/product_composition_assembly.py` 增加私有 completion helper、窄政策 callable 类型和四项结构拒绝类型。结构规则仍按原顺序执行，最终构造原 SelectionSeed。
- Coding `_resource_catalog_shadow.py` 保留原入口签名、前置检查及候选过滤/投影，委托结构准备；原 exact/default 分支拆为固定政策函数，单 reason 通过原异常 adapter 返回。原 `_owner_binding_covers` 完全保留。

两个文件的其它原定义 AST 不变；原 selector、bootstrap、两 composer、Session current recheck、D1 清理源文件保持原字节。未修改产品测试、PR gate、持久格式或运行平台。

| 代码评审视角 | 独立初评 | 修复窄复核 |
| --- | --- | --- |
| 职责与复用 / `d2_ownership`，xhigh | 无发现；机制/政策边界与原依赖保持 | 显式循环修复无职责、接口或复杂度新增影响 |
| 运行与失败 / `d2_runtime`，xhigh | 初评未发现；随后明确记录漏判 PEP 479 异常转换 | 更正初评，确认显式循环保留异常直传、失败前缀和原清理边界 |
| 数据、兼容与验证 / `d2_data`，xhigh | D2-CODE-DATA-01：生成器收集 callback 返回值会转换原 StopIteration，P2 | 该发现静态关闭；无新增发现，身份和政策合同保持 |

三份初评齐备后才统一反馈并修复，没有把一位初评结论提前提供给仍在初评的其他视角。三个视角只读取源码、基线和合同，不读其他代码评审报告，不运行产品或测试；运行结果由实施者另行记录。

D2-CODE-DATA-01 的修复：将 `tuple(resolve_owner(...) for ...)` 恢复为原显式 for/list.append，最后转 tuple，保持 sorted owner pair 和相同对象。树外与原函数差分独立复现修复前的两项异常类型/身份差异；修复后 33 项全部通过，覆盖 exact/default、完整 supplied binding/authority 身份、原 plan 值相等、全部原政策值/TTL、结构拒绝优先级、晚项投影失败、callback/构造器故障及非 Coding 政策适配。差分探针留在产品树外，不加入 PR gate。

第一切片验收时：两文件 Ruff 与 mypy 通过；14 份相邻源码/测试 SHA 与原基线一致，现有函数 AST 除 Coding completion 外均保持。原架构检查 241 passed / 1 failed：唯一失败为 `test_rcp0_discovery_and_projection_caller_inventory_is_exact`，清单遗漏既有 `SessionToolController.render_execution_prompt → get_resource_bundle` 调用；在干净 main `ff29a80e4` 上独立执行同一用例也失败，相关源码和测试在两树字节相同，非本切片引入。该阶段未调整该断言或产品行为；后续关闭见下节。

`make plan-checks` 选择文档、包依赖、较广 Coding 和 Harness 离线套件。实际 `check_changed.py` 的文档及包依赖检查通过；较广 Coding 在 645 passed / 62 deselected 后主动中断，原因是与最终源码直接回归重叠且没有必要重复执行全部跨包用例，后续 Harness 全包套件未启动。该较广检查在显式循环修复前启动，不能算作最终源码全套通过；完整跨包/Actions 检查仍未完成。

最终源码直接回归 **204 passed**，覆盖 `test_resource_catalog_shadow.py`、`test_base_plugin_owners.py`、`test_bootstrap.py`、`test_plugin_lifecycle.py`；与原函数差分 **33 passed**。所有 pytest 从首次尝试就在沙箱外执行，保留本地离线选择器；树外差分无 hosted/模型/网络场景。原架构检查结果及上述 main 复现单列，不将其写成全部通过。最终文档 9 项断言、相对链接与 diff 格式检查通过；不新增测试文件到产品树或调整 PR gate。

| 最终代码报告（树外 implementation 目录） | SHA-256（含修复复核） |
| --- | --- |
| `code-review-ownership.md` | `8a60e741c75a91b99ad841d29f15e4eda8a554918bb4f62f565d72379b014720` |
| `code-review-runtime.md` | `6e3e55241de55f710c034eff71828be4eaf4b3dc3f1e11c85e878794aa25b9de` |
| `code-review-data.md` | `4865bae283154ebd46fbaa95aeb2cf95c4d90026cd176cf3a594c922472a60ad` |

最终源码 SHA-256：Harness assembly `877772663490542da74bf39575e21f17d303894745fa9443b86b3b96721bc690`；Coding adapter `027d8fb02264df9e4b1e0e93f5b0b9c8d1ec1b721d7d9425b09515f4a57a1be6`。Design status 为 accepted（第一切片）；代码评审未关闭发现为 0。第一切片实现、直接验证与评审完成，D2 整体 Implementation status 仍为 partial。不扩大为完整 D2 已完成。本节记录本地验收切点，未验证 native/hosted 或远程 Actions；后续远程交付状态以 Git 提交和 PR 记录为准。

## 既有调用清单失败关闭

2026-11-05，用户授权完成建议第 1 项：核实既有调用职责，修正清单并复核。核查 `facade.py::configure_execution` 将原工具 renderer 传给 `execution_configuration.py::ExecutionConfiguration._publish`，仅在该次执行指定工具子集时使用；`tool_controller.py::render_execution_prompt` 核验当前活动工具，读取已注入的 Resource bundle，通过原 `_render_tool_prompt` 返回提示词，不写 Agent 的工具选择或提示词基线。标准 `ResourceLoader.get_resource_bundle` 返回当前 Catalog 兼容投影或已持有的 legacy snapshot，没有重新 discover、准入或发布。该调用属于现有受理执行的兼容投影消费，不构成新的 Resource 权威。

修订仅在原 `EXPECTED_CALL_SITES["get_resource_bundle"]` 增加这一个精确的文件/限定函数 pair，并同步 [RCP0 基线清单](resource-catalog-rcp0-baseline.md#get_resource_bundle) 的用途说明。局部静态复核确认：其它清单项未增删，扫描器及所有原断言 AST 完全不变，仍对完整调用集合做精确相等比较；所有运行时代码及原 D2 两源码 SHA 均保持。未新增检查、触发条件、测试路由或平台，也没有改为包含关系、增加忽略条件或豁免未知调用。

沙箱外复跑整个 `test_resource_catalog_rcp0_baseline.py` 的原 9 项，以及既有 `test_execution_tool_prompt_is_rendered_without_overwriting_live_selection`：**10 passed**。Ruff、文档轻量检查、相对链接及 diff 检查通过。此前架构组的 241 项通过结果保留，本轮仅复核受影响的清单和提示词行为，不宣称重新执行整组 242 项或完整跨包套件。主线已知清单失败在本地候选中关闭；204 项运行回归、33 项差分无需因未改变运行时代码而重复。

本次为实施者局部复核，不另称独立 agent 评审。原始日志、JUnit、单项清单差分及源码不变证据位于树外 `implementation/inventory-closure/`；后续远程交付状态以 Git 提交和 PR 记录为准。
