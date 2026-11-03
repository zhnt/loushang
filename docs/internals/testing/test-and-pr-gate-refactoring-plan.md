# 重构与优化测试与 PR 门禁

- 文档修订：R19，2026-10-15。
- 状态：本轮缩减、去重、重组与 15 分钟验收已完成。六类长门禁仍保持暂停；AP-01 至 AP-11 是须另行审批的后续增量，不属于本轮已授权实施面。
- 范围：现有全部工作流、源 job、平台矩阵、测试清单、执行器及汇总检查的分类、去重、有效合并与迁移。
- 全量盘点：[16 个工作流、71 个源 job 的分析与去向](test-and-pr-gate-inventory.md)。
- 当前行为依据：[现行门禁说明](change-aware-quality-gates.md)、[选择器](../../../scripts/ci/select_checks.py)及其工作流。各项按阶段实现与验证；未交付项不作为当前配置，暂停项不自动恢复。
- 评审记录：[三视角评审](test-and-pr-gate-refactoring-review.md)。
- 审批边界：任何新增或扩大的门禁必须由审批方对具体方案明确批准；本 goal、普通开发任务、测试优化或文档修改的一般实施授权都不替代门禁增加审批。新增 required check、workflow/job、测试 route、平台或矩阵，扩大触发范围，恢复暂停门禁，把非阻塞检查改为阻塞，或让原本未执行的测试首次形成失败条件，均属于门禁增加。未获批时只允许删除重复、缩小现有选择、优化测试自身执行和记录待审批方案。

## 1. 目标与约束

以最小必要测试覆盖实际改动风险。全部模块的单元测试也逐项去重，受影响模块执行审查后保留的必要单元全集；集成与原生测试按能力和风险选择；同一平台、同一用例在一次候选验证中只执行一次。

| 场景 | 端到端目标 |
| --- | --- |
| 普通文档 PR | ≤2 分钟 |
| 纯单元测试代码及其单元专用夹具修改 | ≤5 分钟 |
| 普通源码 PR | ≤10 分钟 |
| 平台或高风险 PR 的必要阻塞集合 | ≤10 分钟 |
| 同代码内容、同执行计划的 main 结果复用 | ≤2 分钟 |

目标包含正常 runner 供给下的排队、准备、测试和汇总。异常排队保留在原始总耗时中，另列原因与执行耗时，不通过扣除排队制造达标数据。验收采用多次实际运行；一次成功样本不能证明长期保证。

其他约束：

- 不以删除必要断言、放宽校验或跳过必需用例换取速度。
- 单元回归与合同验证采用可控依赖，不调用真实大模型；真实供应商验证保持单独授权和执行。
- 保留一个必需 `quality-gate`，失败、取消、缺失任务、意外空跑不能误绿。
- 六类长门禁继续暂停，必要能力与当前覆盖缺口分别登记。文档评审通过不等于恢复执行。

## 2. 已知问题与依据

以下为已有运行与代码检查的基线，不是优化后的承诺：

| 证据 | 观察 |
| --- | --- |
| [PR #740](https://github.com/zhnt/loushang/pull/740) 最终运行 | PR 9 分 53 秒；合并后 main 核验复用结果 41 秒 |
| [该 PR 的运行](https://github.com/zhnt/loushang/actions/runs/38523545906) | 63 个任务；步骤时间累计约 84 runner 分钟，不能等同于 PR 墙钟时间或精确计费时间 |
| 同次 Coding 报告 | 16 个分片、4798 个报告用例；分片用例时间约 107–252 秒，平均约 172 秒，包含平台跳过用例 |
| AppHost/AppService 的 Makefile 清单 | 58 个相同清单条目，包括整个目录；不是 58 个精确重复 node ID |
| AppHost 工作流 | 主测试阶段运行 G8/G9/G10 文件，证据阶段再次执行相同文件 |
| Coding 离线回归 | 包含真实 CLI、安装与终端恢复用例；部分单例约 20–31 秒，离线不能直接归为单元 |
| 暂停前 Windows 报告 | direct Session 单例约 29.5 分钟；crash 恢复各约 22 分钟；GC 更新单例约 15.2 分钟 |

Windows direct 用例串行执行候选构建与安装、原生后端审核、直接 Session、工具调用、Worker 清退、print/text CLI。运行栈多次进入逐文件安装包校验、epoch 与状态日志校验。完整分阶段成本仍待测量；不能仅依据少量栈样本推定全部耗时原因。

参考设计归纳为：区分快速阻塞路径与扩展验证、一次构建供多个执行者使用、保留依赖与结果校验、测量分片尾部。采用现有 pytest/uv 实现这些原则。详细参考研究留在产品仓库外，产品文档只保留独立表述的设计结论。

## 3. 分类与唯一归属

分类依据验证行为，不依据文件名、是否联网或运行时间。每个 collected node ID 有一个主类别、一个执行归属；风险、平台和受影响能力可有多个标签。

| 主类别 | 定义 | PR 策略 |
| --- | --- | --- |
| 单元 | 局部逻辑与可控依赖；小型临时文件可作为夹具，不包含真实产品安装或启动链路 | 所属受影响模块完整执行 |
| 合同 | 接口、协议、序列化、错误语义、权限决策等约束 | 模块相关合同；公共接口变化补受影响消费者 |
| 集成 | 多个真实组件的安装、CLI、存储或服务协作 | 按能力与影响路径选择 |
| 核心冒烟 | 基本产品完整流程 | 源码 PR 保留经典流程，交互场景按路径选择 |
| 原生冒烟 | 真实终端、IPC、进程或平台隔离 | 对应平台或原生边界变化触发 |
| 故障 | 实际 crash、GC、异常退出、恢复与清理 | 对应风险路径触发；模拟故障决策仍可属于单元/合同 |
| 耐久 | 持续查询、真实重启、长期资源泄漏 | 独立专项、夜间或发布验证 |

需要多类别的测试文件拆分，或在 node ID 层逐项标记，不能将整个混合文件直接归为单元。共享夹具登记使用者及主类别；单元专用夹具无集成使用者时才适用免集成规则。

拟议登记字段：`node_id`、`category`、`owner`、`assertion_id`、`capabilities`、`platforms`、`source_paths`、`fixture_dependencies`、`workflow_dependencies`、`measured_duration`、`duplicate_group`、`execution_policy`。这些字段尚未实现为机器消费契约。

新增或变更用例必须完成分类。未知路径要补充影响与归属说明，不能静默略过；未能明确归属时使用现行受控回退或阻止候选通过分类检查。不得自动恢复暂停的大场景兜底。

### 全部单元测试的合并与必要性审查

范围包括全部模块、公共接口/消费者合同、共享测试助手、现有例子回归，以及当前归在“离线单元”入口下的混合集成。既审查同一用例被多个门禁重复执行，也审查不同测试文件是否覆盖同一行为。

“完整单元回归”指经审查确定的必要单元与合同集合，允许合并或删除有替代证明的冗余测试，不以维持历史测试数量为目标。完整性校验针对新的必要集合；迁移依据是行为与断言覆盖，而非旧 node ID 数量完全相同。

| 重复或成本类型 | 处理 | 保留条件 |
| --- | --- | --- |
| 同一用例被多个门禁执行 | 一个 owner、一次执行、多份报告 | 平台/配置不同的独有验证分别保留 |
| 同行为、前置条件、输入等价类和预期断言重复 | 合并为一个必要用例，记录替代映射 | 唯一错误语义、边界、状态/副作用和资源生命周期断言不可丢 |
| 不同模块重复验证共享工具内部行为 | 共享模块保留完整行为测试，调用方保留自己的接口与使用合同 | 调用方独有参数转换、授权、失败处理仍验证 |
| 重复准备/构建与测试代码 | 精简或合并测试助手，复用不可变夹具 | 可变状态、patch、会话和资源每例隔离 |
| 参数矩阵过大 | 按实际行为等价类保留代表值 | 边界、解析差异、平台/类型、拒绝策略和故障注入阶段分别保留 |
| 只验证实现细节或无有效断言 | 改成可观察行为验证，或经评审删除 | 不能以“已有覆盖率”或“另有 E2E”代替必要断言 |
| 名为单元、实际执行完整产品链路 | 重分类为集成/专项，按能力路径选择 | 真实边界行为有对应执行归属 |

去重判断必须核对前置状态、输入分区、可观察结果、错误/副作用、权限边界、平台与执行配置。参数化只减少重复代码，不自动减少运行次数；不同失败分支不能因共享测试主体而合成一个正常案例。

维护“旧用例 → 保留用例/参数 → 必要断言与输入分区”的覆盖映射。删除前由模块 owner 确认被替代的全部必要行为；未能证明重复的用例先保留，避免按文件名、相似代码或时长批量删测试。覆盖率作为辅助指标并保持既有有效要求，不能单独证明语义等价。

数量、总执行成本、重复率、必要断言与输入分区同时记录。合并后的单元仍独立、确定性、易定位失败，不把几十个断言串成难诊断且相互依赖的大测试。

## 4. 改动选择规则

以 diff 内容、文件角色和依赖关系共同选择。混合 PR 取并集，文件删除、重命名及夹具间接使用也要纳入。结果应解释为什么执行或不适用。

| 改动 | 必需验证 |
| --- | --- |
| 普通文档-only | 文档检查；无产品单元、集成或 E2E |
| 普通测试实现及包内测试夹具 | 已有模块或 targeted owner；不附加全局集成、消费者、原生或 E2E |
| 合同测试 | 受影响合同与所属模块回归；若合同描述跨组件行为，补必要消费者验证 |
| 集成/E2E/原生/故障用例及专用夹具 | 受影响用例与相关测试助手检查，不扩展到无关集成组 |
| 普通源码 | 受影响模块完整单元回归、适用静态检查、核心冒烟 A |
| 会话、Agent、工具、审批、交互控制源码 | 上述检查及核心冒烟 B |
| 公共接口或协议 | 上述检查及受影响消费者合同 |
| 平台实现、IPC、认证、进程/终端所有权 | 上述检查及对应平台必要原生/专项验证 |
| GC、crash、恢复实现 | 上述检查及对应失败模式验证 |
| 依赖与打包配置 | 受影响模块回归及真实安装验证 |
| 共享夹具、测试收集/选择/跳过机制 | 所有直接和间接使用者验证，包含必要集成，不适用纯单元测试豁免 |
| CI 编排、工作流与验证器 | 完整路由/聚合合同、语法检查及受影响执行机制的代表验证；无关业务集成不自动扩展 |

以下不属于普通文档-only：运行时 prompt/skill、机器消费配置、测试预期与夹具、证据清单、生成依赖事实等。改动虽只发生在 Markdown 或 JSON 文件，仍按实际消费者选择。

“测试-only”是选择输入，不是免测凭证。包内测试实现运行所属模块的完整离线回归；已登记 integration/platform 测试运行既有 targeted owner。跨类别共享助手、根级 pytest 配置及工作流变更必须追踪真实影响范围。纯 test-only 不默认附加全局 A/B、消费者或原生矩阵，但被修改的冒烟自身必须执行。

## 5. 目标门禁结构

删除按历史阶段设置的独立 job 与汇总门禁，包括 `g16-native-darwin`、`g17-darwin-native` 及同类 G8/G9/G10/G16/G17、PLC9C5 门禁。必要断言迁入能力分组；历史编号仅用于历史追溯。

| 分组 | 内容 | 选择依据 |
| --- | --- | --- |
| 模块回归 | 完整单元、模块/消费者合同、静态检查 | 模块及接口影响 |
| 核心冒烟 | A/B 两条经典流程 | 源码及交互影响 |
| 平台冒烟 | Linux/macOS/Windows 必要原生行为 | 对应平台与边界 |
| 专项回归 | IPC、认证、安装、权限、crash、GC、恢复 | 能力与风险影响 |
| 扩展验证 | 完整矩阵、持续运行、真实重启 | 审查后的专项、夜间、发布选择 |

同平台、同环境的原生场景可放在一个执行任务内，按清单选用例；构建一次，复用产物。不能因合并 job 就每次执行它包含的所有场景。IPC 与终端可共用环境，但断言、夹具生命周期和报告身份分别保留。

### 核心冒烟

- **A 会话工具与持久化：**创建会话 → 消息与真实 read 工具 → 关闭 → 从磁盘重建恢复 → 再发消息 → 关闭。三平台执行。
- **B 取消与继续：**受控工具开始 → Escape 取消 → 验证工具任务结束 → 再发消息并显示回复 → 退出。相关路径选择，适用三平台。

模型传输确定性模拟。A/B 验证真实会话、工具、存储和可控交互，不代表真实大模型、原生终端、IPC 认证和系统进程隔离已覆盖。

### 最小能力覆盖映射

| 必要断言 | 首选覆盖 | 还需的条件验证 |
| --- | --- | --- |
| 历史持久化、关闭后恢复、继续消息 | A；对应单元/合同 | 平台资源变化恢复按其路径补验证 |
| 工具取消、任务结束、下一条消息和退出 | B；取消状态机单元 | 原生子进程取消不能用模拟终端代替 |
| 会话接口、协议、错误码 | 完整相关合同 | 公共接口变化补消费者 |
| 真实 IPC 鉴权、断连仅关闭所属 scope | 对应协议/权限单元合同 | 实际本地请求与断连专项 |
| 终端模式/光标恢复、物理退出 | 终端单元/渲染合同 | 对应 PTY/ConPTY 原生冒烟 |
| 子进程所有权、隔离与拒绝越权 | 权限/生命周期合同 | 对应平台原生正负场景 |
| GC 只删除允许对象；旧 attempt/租约恢复正确 | GC/恢复决策单元合同 | 对应风险路径的实际故障验证 |
| wheel 内容、依赖、安装入口有效 | 打包合同 | 干净环境的真实安装与入口验证 |
| 长期稳定与真实重启恢复 | 独立耐久/恢复验证 | 不由 A/B 或短冒烟代替 |

原生最小集合必须包含相应边界的必要失败断言，不只证明正常启动。候选单例采用约 60–90 秒测试步骤预算、平台组约 2–3 分钟目标；达不到时继续优化或保留独立专项，不能截断等待或放宽 Product 校验。

## 6. 现有门禁迁移清单

本方案覆盖现有全部门禁，不限于 G16/G17、Windows 或 Coding。全量 job 盘点见关联清单；源 job 定义、平台矩阵展开实例和一次运行的任务数量分别记录。每个任务均要给出必要断言、重复候选、精确执行配置、触发、成本、报告消费者与处置证据。

现有 job 没有因名称较新、执行较快或位于汇总层而豁免审查。处置可为保留、合并、拆分、删除重复、移入专项或继续暂停；保留必须有必要性依据，删除必须有替代覆盖或重复证明。

| 当前门禁 | 迁移方向 |
| --- | --- |
| changes/docs/CI/quality-gate | 保留轻量检查与一个必需汇总入口 |
| Architecture | 源码依赖事实保留，优化独立环境准备成本 |
| units/packages/Coding regression (shard x) | 删除独立的固定 16 分片 Coding 任务组，迁入统一模块回归；完整 Coding 单元保留，离线集成按能力选择 |
| AI/Install | AI 离线回归、静态与现有覆盖率保留；安装按依赖/打包/发布独立选择 |
| Harnesstui/Coding UI | 确定共享用例唯一归属，消费者合同单独选择 |
| TUI | 单元、渲染、平台机制、PTY/ConPTY、tmux 分别选择 |
| AppHost | 消除主测试与 G8/G9/G10 证据重跑；真实 IPC 与生命周期专项迁入能力分组 |
| AppService（暂停） | G16/G17 原生/安装/回归拆回能力组，删除历史独立 job |
| Harness（暂停） | 保留模块回归；隔离/原生合同迁入对应能力与平台 |
| Hosting（暂停） | 保留模块回归；启动→查询→退出按后端选择；2049 次查询归耐久 |
| Host Runtime（暂停） | 拆回具体模块与能力，取消笼统跨包大组 |
| Windows Shell（暂停） | shell、安装、查询、清退、crash、GC/恢复分离；重新制作短原生场景 |
| Registered Worker Reboot（暂停） | 独立真实重启验证 |
| LSP | 对应适配选择对应服务；通用协议变化选择必要通信与合同验证 |

迁移每个旧 job 前建立“旧用例/断言 → 新 owner/类别/平台/触发 → 执行与报告”的映射。仅经证据确认完全重复的用例可删除；未迁移的必要断言留在缺口清单中，不能因旧 job 删除而隐失。

六个暂停工作流为 Windows Shell、Hosting、AppService、Host Runtime、Worker Reboot、Harness；暂停覆盖 PR、main、定时及手动全量。当前另有模块回归替代，具体范围仍以现行选择器为准。重组和恢复是两个独立动作：恢复一个必要场景不应顺带恢复原工作流的完整矩阵。

## 7. 执行、报告与结果复用

### 一次执行，多份证据

执行身份由 `候选 tree + 执行计划 + node ID + 平台 + 实际运行配置` 确定。不同平台、真实安装与源码运行、不同隔离后端不视为重复。

一个执行结果可派生多个能力或历史追溯报告。派生报告必须保留源 run/attempt、tree、实际用例、平台、配置及结果；不能拼入上一轮结果或将缺失场景填为成功。精确用例与零跳过校验针对当前必需集合，而非所有离线回归中不适用的平台用例。

### 分片与构建

- 先按历史耗时平衡现有分片，随后测量是否减少分片；评估排队、收集、准备、测试、上传与汇总总成本。
- 新用例默认分配及历史数据缺失必须有确定性规则。分片并集等于所选全集，交集为空；清单绑定提交和配置。
- 复用 wheel/编译产物，不复用 mutable 会话、Product state、租约或未经失效校验的授权状态。
- 产物绑定源码 tree、依赖锁、工具链、平台/架构及构建参数；实际安装测试在干净隔离目录执行，防止仓库源代码遮蔽安装产物。
- 保持现有完整性、锁、authority 与失效检查语义，不用跨 Product 读取缓存绕过校验。

### Coding 固定分片重组

基线中的 `Coding regression (shard x)` 是同一完整离线集合的确定性分片，不能将分片数量直接解释为重复用例。实现已删除这组独立任务及其固定 16 分片配置，把 Coding 的完整离线集合迁入统一模块回归；安装、CLI、终端恢复等真实集成继续按能力路径选择。

历史 16 分片样本的用例时间累计约 2755 秒（46 分钟），最初按 #740 的 4798 项报告选择 8 片。完成第一轮 owner 分类和去重后，PR #779 的 8 份报告并集为 3771 项、无身份交集，testcase 时间合计 640.406 秒。按生产所用 node ID 哈希重算，4 片为 918–975 项/片，最慢净用例时间 198.444 秒；相同集合的 8 片最慢为 100.718 秒。实现据此进一步选择 4 片，在最慢净用例只增加约 98 秒的同时，把 checkout、Python/uv 准备、依赖同步、收集、报告上传从 8 份减为 4 份。PR #780 同提交的手动 full 运行 `38630526974` 产出四份报告，实际为 918–975 项、净测试 140.647–190.205 秒、job 3 分 06 秒至 4 分 11 秒；新旧报告并集均为 3771 项，missing/added/新分片交集均为零。

迁移顺序：先明确完整单元/合同与集成集合，再去重，最后比较候选分片数量及实测尾部。当前 4 片是基于最新必要集合的候选配置；后续按真实总耗时与 runner 成本调整。若分类后所选单元规模继续缩小，允许进一步减少分片或单任务执行。

切换前证明审查后必要 Coding 单元/合同的行为与断言覆盖不缩减，旧用例到保留集合的映射可核对，消费者合同与对应集成有新归属，旧/新触发的正负路由均通过。原任务组仅在新路径验证后删除，不能先关闭全部 Coding 回归等待重建。

### main 复用

保留已实现的同 tree、同执行计划、成功 PR/run/attempt 证据核验；缺失、过期、错误、不同 tree/计划或不适用推送形态均正常回退。分类和选择策略的版本必须包含在执行计划，策略改变不能命中旧证据。main 复用不补足 PR 本身未执行的必要断言。

### 提交证据与合并加速

可复用的是候选代码已成功验证的证据，不是 commit 动作本身。证据必须关联实际受测 tree、完整必需计划、PR、成功 run/attempt 和真实平台配置。

- 合并前：必需 PR 检查仍必须通过，且证据覆盖本次合并候选。主分支推进导致候选内容变化时重新验证受影响范围，不能仅凭 PR head SHA 未变复用旧合成结果。
- 合并后：合并 commit SHA 可以不同；实际 tree 和执行计划匹配时复用成功 PR 的证据，只保留轻量核验与汇总。当前实现已经支持这一项，PR #740 的 main 验证耗时为 41 秒。
- 本地提交时的测试结果可作为诊断和开发证据；不能直接把本地结果文件当成成功远端必需检查。若以后引入可信本地执行证明，需要单独设计来源、完整性、环境和覆盖校验。
- 失败、取消、缺失或过期的证据，不同执行策略、平台或合并内容均不能用于减免必要验证。仓库保护规则保持有效。

## 8. 迁移次序、回退与职责

| 阶段 | 交付物 | 进入下一阶段的条件 |
| --- | --- | --- |
| P1 分类与选择 | 初始用例/夹具清单、正负路由合同 | doc/unit-only/集成-only/混合与间接使用选择正确 |
| P2 去重与报告 | 全部单元语义去重、唯一执行归属、报告派生、旧用例映射 | 必需断言并集不缩减，证据可追溯 |
| P3 执行优化 | 分片时长、构建复用、准备时间 | 分片完整且不重叠；产物一致且隔离有效 |
| P4 重组能力门禁 | 删除历史独立 job、迁入必要能力组 | 所有保留断言有归属；恢复的原生组通过对应平台和失败分支验证 |
| P5 真实验收 | 多类型 PR 及 main 耗时证据、最终说明 | 覆盖、选择、防误绿与时间目标同时满足 |

职责：CI 维护者负责选择与汇总，模块维护者负责分类和完整单元，平台能力维护者负责必要原生断言与预算，交付者负责迁移证据及缺口闭环。

实施时先生成对照清单，在影子选择或手动受控验证中比较集合；切换原子更新选择器、job ID、`needs`、聚合映射、验证器及文档。保留一个必需入口，不制造另一条同时阻塞的全量流水线。所有 `selected-checks` 与顶层汇总一并审查；若 root 只能观察 reusable workflow 总结果，删除子汇总前必须实现并验证对所选子 job、矩阵、必需用例结果的完整观察，否则暂保留防误绿校验。

回退可恢复此前已验证的选择与报告机制。暂停清单独立保留；回退不能默认重新启用六类长工作流。共享构建失败、报告缺失和分类不完整必须明确失败或采用受控回退，不能伪装为不适用。

## 9. 验收证据

1. 全部现有工作流、job、矩阵、执行器和汇总检查均有审查与处置记录，无遗漏；审查后必要单元/合同清单及其执行并集、旧用例到保留集合的语义覆盖映射；混合文件分类与共享夹具使用者可核对。
2. 路由正负场景：普通文档、机器消费文档、unit-only、integration-only、共享夹具、混合源码、公共接口、多模块、平台/风险、删除/重命名、未知路径、CI 编排。
3. 同场景下 selected job 失败、取消、缺失、空报告或必需用例跳过不能通过；合法不适用有可核验说明。
4. 旧历史门禁删除与新能力覆盖映射；报告去重后的必需断言集合保持，平台和执行配置不被误合并。
5. 对恢复的必要原生冒烟执行真实平台正负场景；未恢复项有 owner 和关闭条件，不宣称已覆盖。
6. 时间报告包括触发时间、排队、各执行阶段、最后必需结果及汇总完成；每类取至少三次有效运行建立初始基线，异常样本同样留存并解释。
7. main 的成功复用及证据不匹配回退，分类/策略升级使旧计划失配。
8. 最终源码、清单、工作流、测试和说明一致，完成提交/推送/PR/合并/本地同步。

## 10. 评审后的方案状态

R0 为此前对话草案；落盘 R1 经测试覆盖、执行性能、维护迁移三个视角检查；发现与修订见评审记录。R1 补充机器消费文档例外、共享夹具影响、能力覆盖缺口、去重身份、构建隔离、分片完整性、迁移原子性及证据失配规则。

R2 根据追加要求明确取消独立固定 Coding 分片组、保留完整单元与合同、按能力选择集成；对相关覆盖和性能约束补做复核。

R3 将范围明确为全部现有门禁，并增加 16 个工作流/71 个源 job 的逐项分析与去向；新增对子汇总移除时的完整观察约束。

R4 将全部单元测试的语义去重纳入范围，允许减少冗余用例数量，保留必要行为、边界和失败分支；补充参数矩阵、共享工具职责、夹具隔离与删除证明要求。

评审结论限定为文档方案可作为后续实施输入。所有分类清单、历史 job 删除、性能调整和原生恢复仍是待实施工作；当前配置及暂停状态未变化。

## 11. 新 goal 启动与实施记录

用户重新建立 goal 后开始实施，最终要求 PR 目标门禁控制在 10 分钟内。本节更新实施状态；原 R4 文档评审是历史方案评审，不能当作新增实现的验收。R4 方案快照保存在任务分支提交 `b2e33ff6`。

门禁增加审批规则适用于后续全部批次：新增 required check、workflow、job、
test route、平台/矩阵、路径触发或失败条件，恢复暂停项，或把 schedule/
nonblocking 覆盖移入阻塞 PR 路径，都须先提交包含触发、断言、平台、预计成本、
重复覆盖和回退的审批包并获得明确批准。即使方案称为覆盖等价重分类，只要某类
PR 因此多执行任务或多出失败条件，也不能自行实施。未获批准时只做审计、计时、
重复判定和方案记录。

第一批实现：

- 新增独立测试角色登记，区别于仅用于快速路由资格的旧 unit-tests 清单。
- Channel 六个文件、Resource 两个文件完成目录初审，角色为受控单元/合同；目录新增未分类文件或删除后的过期记录明确失败。
- 已审查目录的 test-only 修改只跑该模块完整已审查集合及 Ruff，不默认附加产品集成/E2E；混合源码、共享夹具和冒烟修改仍取并集。
- 未审查模块保持原完整离线覆盖，不能宣称全量分类或去重已经完成。
- 执行计划新增测试策略版本，避免复用旧计划的证据。

第一批本地验证：112 项 CI 合同检查通过；Channel 44 项通过（68.77 秒），Resource 初始 5 项通过（4.32 秒）；9 项文档检查、Ruff 和 Actions 语法检查通过。以上均为本地数据，不是 PR 总耗时验收。

已核对的单元语义去重映射：`tests/resource/test_frontmatter.py::test_harness_frontmatter_entrypoint_is_canonical` 合并到同文件 `test_legacy_resource_frontmatter_path_preserves_harness_owner_identity`。两者使用相同导入、无前置状态，均断言 `parse_frontmatter` 的 facade/canonical 对象身份；后者还验证其余导出和 canonical 类所属模块。仅删除被包含的单断言用例，保留解析行为、其他导出身份及错误类型归属。

全仓静态审计起点如下；函数定义数量包含静态 AST 中的 test_ 定义，并非参数化后收集的 node ID 数量。它用于定位审查工作，不代替完整收集与覆盖证明。

| 测试目录 | test_ 文件数 | test_ 函数定义数 | 状态 |
| --- | --- | --- | --- |
| agent | 7 | 126 | 角色完整初审；附属 examples 合同也纳入 |
| ai | 56 | 540 | 角色与完全重复初审完成；完整目录已执行 710 个受控合同与 2 个 loopback 集成节点，7 个 live vendor 场景显式排除；loopback 精确归类为 AP-04 |
| apphost | 64 | 693 | 角色、重复和成本初审完成；现有模块 runner 已执行完整 1217 项离线集合，unit/integration/platform 精确归属为 AP-05 |
| appserver | 22 | 168 | 完整初审；17 个 unit/contract，3 个 integration，2 个 platform |
| appservice | 16 | 187 | 完整初审；14 个 unit/contract，1 个 integration，1 个 platform |
| architecture | 62 | 654 | 角色与完全重复初审完成；654 项静态/内存合同 8 分 23 秒全绿，历史 owner 重叠与未归属路由仍待审批重组 |
| channel | 6 | 39 | 完整初审 |
| ci | 6 | 139 | 完整初审；选择、归属、证据、聚合及复用合同 |
| coding | 440 | 3959 | 增量角色与完整重复初审完成；68 个整文件 targeted owner、2 个混合文件的 32 个 node 已登记，333 个 Coding 文件与 1 个示例文件仍走保守模块集合；完整分类缺口未经审批不改路由 |
| dev | 45 | 406 | 角色、重复与成本初审完成；完整离线集合 1669 passed、5 skipped，19 个 G18/lmux 路径仍缺少活动执行 owner，列为 AP-10，未经审批不补齐 |
| examples | 6 | 49 | 角色完整初审；61 个模块所属示例合同实例 |
| foundation | 11 | 87 | Ubuntu 模块角色完整初审 |
| harness | 474 | 4106 | 增量角色、重复和远程成本初审完成；当前统一模块仍执行完整离线目录，5386 passed、121 个 Windows/native 条件 skip；完整 node 归属为 AP-07，未经审批不迁移 |
| harnesstui | 98 | 625 | 增量角色、重复和远程成本初审完成；共享 TUI/Harness 消费者文件仅在其包 owner 同时选择时去除重复执行，HarnessTUI-only 路径保持原集合 |
| harnesswork | 7 | 32 | 角色完整初审；两份专用 golden 夹具登记 |
| hosting | 28 | 309 | 角色与完全重复初审完成；454 个实例按受控合同、混合文件、POSIX/Windows 原生边界分类，恢复或补齐执行 owner 仍须审批 |
| integration | 7 | 10 | 角色完整初审；4 个 live LSP、5 个 Ontology 集成实例、33 个示例 smoke |
| method | 10 | 37 | 角色完整初审 |
| ontology | 21 | 152 | 角色完整初审；内存/临时 SQLite 与受控线程合同 |
| protocols | 4 | 101 | 完整初审；109 个收集实例，全部为受控协议单元/合同 |
| resource | 2 | 5 | 完整初审 |
| root | 1 | 1 | 完整初审；打包入口合同 |
| tui | 87 | 1336 | 增量角色、重复和远程成本初审完成；Ubuntu platform 的 114 个重复实例归并到既有 TUI unit owner，native backend/tmux 与 Windows platform 保留 |
| typing | 1 | 0 | 一个显式 mypy 类型合同；当前没有活动执行 owner，首次接入列为 AP-11，未经审批不实施 |
| work | 7 | 45 | 完整初审 |

后续仍须完成其他目录分类、全部单元语义去重、其余历史 job 迁移、按能力执行、原生预算、真实 PR 和 main 验收。当前局部实现不满足 goal 完成条件。

Protocols 目录完成角色与重复审查。4 个文件的 101 个静态函数收集为 109 个实例，分别覆盖 Anthropic Messages、OpenAI Chat Completions、OpenAI Responses 和 Faux adapter 的 wire payload、流式事件、资源关闭、typed capability/default、认证头及错误语义。SDK 均由内存 fake module 或合成事件替代，不访问真实网络；跨协议名称相似的 max-token、reasoning、auth 与 tool-call 用例断言各自不同的 wire contract，不能合并为一个协议的结果。未删除测试 node。三个真实协议文件完全重复的 context normalization、request mode 和 stream 启动驱动已合并到共享 `_runtime.py`，净减少 75 行测试支撑代码；109 项仍全部通过，1.36 秒。所属 AI 完整离线回归 858 项通过、7 项 live deselect，31.28 秒；总覆盖率 90.65% 及三个细分阈值、Ruff、mypy、catalog 和 import boundary 均通过。

Root、Examples 与 Integration 小目录完成角色初审。Root 唯一用例约束 `pyproject.toml` 的 console script。Examples 的 61 个收集实例分别归 Agent、AI/Auth、Coding 与 Harness 模块，覆盖公开导入、受控 fake 模型/认证、脚本 help/import 和独有示例输出；相似入口断言属于不同公开示例，未发现可删除的行为复本。Integration 的 42 个实例分为 4 个显式 live LSP Server 兼容用例、5 个 Ontology 内存/SQLite 产品组合实例和 33 个 manifest 示例进程 smoke。非 live 联合运行 97 项通过、3 项稳定失败、4 项 live deselect，3 分 58.95 秒；失败均为 `legacy-007/013/019` 在新建临时目录首次创建 Session 时得到 transcript writer `conflict/unavailable`，精确复跑仍为 3 项失败，12.89 秒。该 manifest smoke 目前没有正常 PR 执行 owner；直接修改会保守选择全量门禁却不会执行自身。为它新增 targeted route 属于门禁增加，未经审批不实施；现阶段也不能把这组失败且近 4 分钟的 33 场景加入阻塞 PR。

CI 目录完成角色与重复初审。6 个文件、139 个静态测试函数分别验证选择与暂停、
测试归属、JUnit 派生、模块报告完整性、主分支证据复用、导入事实缓存、顶层聚合、
Git diff 范围和工作流结构。全部使用临时 Git 仓库、合成 XML、fake GitHub API、
静态文件或 mock 执行器，不访问网络、不启动 Product。忽略名称的完整 AST 扫描
没有重复函数；相邻断言虽会触及同一计划字段，但分别约束触发、清单完整性、报告
真实性和 fail-closed 汇总，不能互相替代。本地 139 项全部通过，2.493 秒，因此
保留现有节点及文件内隔离夹具，不为减少少量测试代码引入跨文件共享状态。本批只
完成审计记录，不增加或扩大任何门禁。

Dev 目录启动分组审查。45 个文件包含 406 个静态测试函数，参数化后收集 1674 个
实例；完整 Linux 离线集合 1669 项通过、5 项平台条件跳过，耗时 243.10 秒。它并非
一个可直接归为快速单元的模块：既有纯比较/收据合同，也有真实子进程监督、进程树
回收、临时 Git/wheel、POSIX 行为和跨平台 observer 合同。完整 AST 扫描未发现
完全重复函数，后续仍须按执行边界和参数矩阵继续语义审查。

路由检查发现 18 个 `test_lmux_*` 文件和
`test_screen_first_probe_readiness.py` 直接复用 `test_measure_g18_native.py` 的 runner、
G18 comparison 或 Coding probe，却遗漏在现有 G18/AppService owner 清单之外。单独
修改任一文件都会落入未知路径全量回退，误选 Architecture、AI、TUI、AppHost、
LSP、E2E 和多个模块。现将这 19 个路径加入既有 G18/AppService 规则；它们原本已
由全量回退包含该 owner，本次只删除无关选择，不新增 check、workflow、job、route、
平台或失败条件。静态验证 19 个路径均从八类 workflow 收敛为既有 `units`/`e2e`
计划。AppService 当前仍暂停，且这些文件尚无直接 targeted 执行；新增直接执行会
形成新的 PR 失败条件，须另行审批，本批不实施。

Dev 首个执行成本去重保留全部测试身份：
`test_recovery_seed_rejects_changed_workload` 的 12 个故障参数原先各自创建一套完整
真实 Session seed，随后才分别改写 revision、member、identity、history、startup、
decision 或额外文件。现在模块级只创建一次与真实路径绑定的合法 cwd seed，并保存
只读文件快照；每个参数仍在测试前恢复到同一个原始路径，再独立注入原故障并执行
原拒绝断言。12 个 node ID、故障输入和隔离初态不变。该组从约 51 秒降到一次约
4.5--8.6 秒准备及每例约 0.01 秒；完整 `test_measure_g18_native.py` 为 250 项通过、
4 项平台跳过，55.86 秒；完整 Dev 回归仍为 1669 项通过、5 项平台跳过，总耗时由
194.89 秒降到 138.37 秒。本批只去重测试准备，不改变任何门禁或选择规则。

同批远程 PR 实况又证明 G18 test-only 路径仍被通用未审查路径规则附加 Ubuntu、
macOS、Windows 三平台 Resume E2E；这些任务不执行或验证被修改的 Dev 测试。G18
规则现显式声明其测试路径已审查，继续保留原 `appservice` owner、依赖和模块回归，
但不再附加通用产品 E2E。源码、非测试输入、未知 Dev 测试和其他风险路径不受影响。
这是既有任务的纯删减，不新增门禁或失败条件。

PR #763 的同分支远程对照验证该收敛：旧计划运行 `38588834269` 执行两个模块单元
和三平台 Resume E2E，首个 job 开始至汇总结束 84 秒；新计划运行 `38589276148`
只执行两个模块单元，E2E 明确 skipped，同口径 61 秒。旧三平台 E2E job 分别耗时
29、41、63 秒；本轮 `changes` 自身从 10 秒波动到 26 秒，因此端到端净减少 23 秒。

第二批本地实现：Work 全目录受控单元/日志合同已分类；5 个已确认冗余单元用例已有替代映射；AppHost Linux 的 join、composition、canary 从主回归派生报告，保留独有 Worker close 和 installed 验证。完整主集合离线验证 2646 项通过、11 项 Windows 条件跳过，518.16 秒；从完整报告派生后原 manifest 均通过。详见[测试去重实施记录](test-deduplication-review.md)。后续仍需优化实测缓慢的全仓静态扫描与原生执行分组，不把局部结果作为全仓验收。

Agent 的 7 个目录文件和现有 examples 合同完成角色初审，受控模型流/工具、fake HTTP/SSE、受控注册 adapter 均不执行真实网络或 Product 会话。完整回归 155 项通过，2.50 秒；其 test-only 修改走模块回归，不触发全局 E2E。模块附属测试清单统一归入分类校验，附属目录展开到文件、遗漏/失效路径明确失败，执行器不再重复追加已分类 extras。CI 合同 122 项通过。本批不删除 Agent 的层间调用/投影合同，也不宣称已完成全仓语义去重或远程验收。

目录型 extras 追加复核：完整分类后仅执行展开后的文件清单，不再追加其父目录；新增合同防止后续 AI protocols 分类时重复收集。CI 合同增至 123 项通过。Ruff、Actions 语法与文档检查通过。

模块报告门禁：原 blanket allow-skipped 改为按完整分类状态验证，已审查必要集合零跳过；实际 testcase 与声明数量、唯一身份及 owner 一致，未分片报告覆盖全部登记文件。未审查 legacy 集合仍保留平台 skip 兼容，不能因此宣称其必需跳过策略已全部审查。缺失产物上传改为 error。129 项 CI 合同通过；真实 Agent 报告 155 项、零跳过，通过新验证器；此前 AppHost legacy 报告 2657 项、11 项 Windows 条件跳过也通过兼容验证。分片并集和逐 node 必需集合的完整证明仍待后续迁移。

HarnessWork 分类与专用夹具：7 个文件为受控执行/事件投影、临时或只读 JSONL、公开符号/导入合同。名称包含 integrations 的两个文件不启动真实 Product 会话；CLI 文件直接调用 API，不运行 CLI 子进程。两份 golden 数据仅由 `test_plan_projection_golden.py` 读取，已登记 owner、用途和消费者；路径缺失、消费者缺失/重复/跨 owner 均失败。未知夹具、共享 conftest 和混合源码仍保守取并集。完整集合 32 项通过，1.61 秒；真实报告零跳过并覆盖全部登记文件，通过新门禁。CI 合同 130 项通过。声明消费者属于人工审查的明确归属，不替代全部动态 Python 依赖分析；真实集成-only 路由和其他目录仍待完成。

Method 的 10 个文件完成角色初审：不可变类型、内存 registry/selector、受控 runtime/settings、临时目录资源发现和静态包边界，不启动 Product 会话、外部进程或 live provider。完整集合 37 项通过，2.28 秒；真实报告零跳过并覆盖全部登记文件。test-only 修改走模块短路径。

AI 静态重复候选中的两组已经合并：两个名称声称 get-stream 的用例实际仍只调用 `register_api_adapter`，分别与同文件 legacy 和 optional-legacy 注册拒绝用例完全相同。去重后完整 `test_api_streaming.py` 51 项通过，1.22 秒；旧用例到保留集合映射见[测试去重实施记录](test-deduplication-review.md)。AI 全目录尚未完成角色分类，因此其他 AI 修改仍保持现有保守路由。

Foundation 的 11 个文件完成 Ubuntu 模块 runner 角色初审：严格 JSON、观测投影/上下文/临时 sink、临时 runtime scope 与真实本地文件锁、静态仓库边界及一个新 Python 解释器的 import 隔离。它们不启动 Product 会话、服务或 live 网络；POSIX 权限、symlink 与 ownership 断言在 Ubuntu 上属于必要合同。参数化后真实报告 110 项、零跳过、覆盖全部登记文件，38.41 秒，通过模块报告验证器。Foundation test-only 修改走模块短路径；Foundation 源码仍按共享公共依赖的消费者规则扩大验证，本批不缩小源码影响面。

固定 Coding 门禁重组：删除 `package-quality.yml` 和顶层 `packages` 调用；Agent、Coding、Foundation 的 selected check 统一映射到模块执行，风险与 full 计划也只执行一次对应离线集合。Coding 由固定 16 片降为基于 #740 真实 4,798 项报告选择的 8 片；当前哈希算法重算的最慢净用例时间 399 秒。顶层 `quality-gate` 同步删除旧调用依赖，仍对所有现存所选 workflow 的 failed/cancelled/missing/unexpected skip fail closed。CI 合同与 Actions 语法验证通过后，仍需真实 PR 墙钟验收。

Ontology 的 21 个文件完成角色初审：schema/action/fact/query/source/projection 合同使用内存或临时 SQLite，线程并发用受控 barrier/executor，不启动 Product 会话、外部进程、live 网络或原生平台。去除一项被 canonical schema v3 拒绝合同包含的重复用例后，完整模块 219 项、零跳过，6.16 秒并通过模块报告验证器；test-only 修改走模块短路径。

AppService 历史门禁重组：删除 `appservice-quality`、`g16-*`、`g17-*` 和 `selected-checks` 八个阶段 job，改为 `native-service` 与 `installed-service` 两个能力矩阵。离线 AppService/AppServer 回归继续由统一模块 runner 执行；native 按平台共享一次依赖准备，installed 按平台共享一次 wheel build，原 manifest 验证及 Windows 两项短冒烟保留。两个能力 job 与 caller 绑定同一 AppService 选择条件，最终结果进入唯一顶层汇总。该 workflow 继续暂停；installed 两个隔离环境仍可能超过 15 分钟，须进一步缩成必要场景并经真实平台计时后才能恢复。

统一汇总：删除其余十个 reusable workflow 内部的 `selected-checks` runner，只保留顶层 `quality-gate`。每个 reusable job 的 guard 必须是选择计划中的实际 owner boolean，静态 CI 合同要求 job 清单与 scope 一致；matrix/job failure 或 cancellation 由 reusable caller 传播，顶层 verifier 对所有 caller 执行 success/skipped 的 fail-closed 比对。动态模块矩阵、E2E 报告和测试身份继续由各自报告验证器证明，不以删除汇总 runner 代替用例完整性校验。

AI gate 的示例执行已收敛：删除先跑脚本、再跑整个 `tests/examples`、coverage 又跑 AI example 的三重路径；AI/Auth example tests 现与 AI/protocol tests 在 coverage 配置中各执行一次，不再把 Agent/Coding/Harness examples 纳入 AI gate。静态合同锁定两个 owned example 文件各出现一次。

新 AI 配置完整本地验证 858 项通过、7 项 deselect，45.18 秒；总覆盖率 90.65%，runtime core、provider adapters、production adapter modules 三个细分阈值通过，Ruff/mypy/catalog/import boundary 通过。该结果证明唯一执行未损失当前覆盖门槛，远程准备与排队仍待 PR 计时。

AppServer/AppService 完成整目录行为分类。AppServer 的 17 个受控 unit/contract 文件进入模块短路径；真实 loopback/stdio/崩溃写入者三个 integration 文件及 POSIX、Windows 两个 platform 文件保留风险路由。AppService 的 14 个受控状态机/合同文件进入模块短路径；真实 loopback 部署为 integration，跨进程 lease、权限及 symlink 的 continuity 文件为 platform。三个 AppServer 专用夹具也登记分类和唯一消费者；targeted 夹具本身不会取得 unit-only 豁免。AppServer 短路径 825 项通过，13.18 秒；AppService 短路径 224 项通过，4.77 秒；拆出的专项集合在 Linux 为 75 项通过、10 项 Windows 条件跳过，6.47 秒。以上是本地执行时间，平台工作流及 PR 墙钟仍须远程证明。

分类策略版本随 targeted 类别和 AppServer/AppService 目录加入从 v1 升至 v2，并在 targeted 直接执行进入计划后升至 v3。执行计划携带该版本；合并证据复用要求计划字段完全一致，因此旧分类策略生成的成功结果不能被新策略接受。

Targeted 文件不再只靠“扩大路由”间接覆盖：integration/platform 文件或其登记夹具被修改时，模块 workflow 按分类中受限的 runner 清单直接执行消费测试。当前 loopback/stdio/POSIX 测试在 Ubuntu 执行，Windows record 在 Windows 执行，continuity 同时覆盖 Ubuntu 与 Windows；integration 报告零 skip，platform 报告允许不适用用例但至少一项必须通过。路径通过环境变量加引号传递，artifact 使用内部数字 ID，不把变更文件名拼入 shell 或产物名。unit/contract 修改仍不会触发 targeted job，live 类别也不会自动访问外部服务。

远程基线运行 `38523545906`（旧 16 个 Coding shard）从创建到完成为 9 分 53 秒。该次全选路径中 AppHost 最慢 job 4 分 13 秒、Harnesstui 3 分、AI 1 分 3 秒、TUI 1 分 12 秒、LSP 57 秒，均并行且未形成 15 分钟尾部；Coding shard 最长约 5 分 5 秒，并受 runner 排队影响形成最终尾部。因此暂不扩大六类暂停清单，优先以本分支的 8 个实测均衡 Coding shard 做远程验收。运行 `38528465735` 的普通 UI PR 为 5 分 59 秒，其中旧 16 shard 最晚结束；这些结果只证明旧基线和瓶颈位置，不证明新配置已达标。

PR #742 的最终全选运行 `38548023281` 从创建到顶层汇总完成为 11 分 01 秒。跨平台恢复冒烟为 25–63 秒，除 Coding 外的必需任务约 3 分 30 秒内结束；8 个 Coding 分片为唯一尾部，最慢分片用例阶段为 7 分 48 秒。日志中的慢项集中于真实终端、已安装 wheel、跨进程服务、包切换/删除/GC CLI 和完整插件旅程，不能继续称为单元回归。

分类策略 v4 增加增量 targeted override：已用远程 slowest 报告和静态进程边界复核的 55 个 Coding 文件移出普通模块回归，修改这些文件或其专用入口时只执行登记平台上的精确文件；不附加模块全集或通用 E2E。其余 372 个 Coding 测试文件继续保守进入原模块回归，不能因局部分类而取得 unit-only 资格。初次候选中的 9 个混合文件含有参数解析、选择算法、注册表或纯计划等单元/合同用例，已从整文件 override 撤回，等拆文件或支持 node 级分类后再迁移。第一轮只移出 30 个文件后，本地原 2/8 慢分片仍需 9 分 18 秒，证明少数 top case 不足以解决混合集合；新增第二轮进程边界审查后须由远程全选重新计时。作为代表，`test_package_gc_cli.py` 两项真实 CLI 用例分别为 53.75 秒和 47.29 秒，整文件 1 分 47 秒，保留为 targeted integration。

55 文件版本复跑原 2/8 分片为 545 项通过、4 项跳过、1 项失败，耗时 7 分 29 秒，比 30 文件版本缩短 1 分 49 秒。失败项 `test_only_live_mux_among_multiple_services_attaches_without_selector` 单独复跑 14.89 秒通过，因此记录为顺序或环境敏感信号，不把该次分片当作绿色验收；远程 8 分片仍是合并前的正式耗时和稳定性证据。

PR #743 的完整远程全选运行 `38554483283` 在 6 分 04 秒内绿色完成；8 个 Coding job 为 2 分 09 秒至 3 分 30 秒，三平台恢复冒烟为 23–41 秒。合并 push `38555330728` 复用同树、同计划证据后 58 秒完成。因此当前活动门禁已满足 15 分钟目标，并验证了合并证据复用；后续优化不能以牺牲必要冒烟或混合文件中的单元合同换取更短数字。

第三轮从 #743 slowest 报告新增 13 个适合整文件 targeted 的真实执行/托管会话/持久化边界文件，总数为 68，剩余 359 个 Coding 文件继续保守回归。另修复部分分类后的显式路径与 `--ignore` 冲突：39 个已有 Harnesstui/Coding UI owner 的文件不再重复进入 Coding 后端。Windows 条件场景与 Ubuntu 集成混合的 `test_hosted_session.py` 已撤回候选，等 node 级分类后再迁移。修正后的本地 0/8 为 463 项通过、2 项跳过；新增 retained targeted 文件全部通过，正式收益仍以远程 PR 数据为准。

PR #744 的远程全选运行 `38557834260` 为 4 分 58 秒，Coding 8 个 job 为 2 分 04 秒至 2 分 57 秒，三平台恢复冒烟为 26–64 秒，全部通过。0/8 从 #743 的 3 分 30 秒降为 2 分 56 秒，证明重复 UI owner 已从 Coding 后端移除。

full validation 现在补回全部非 live catalog targeted owner。当前 76 个“文件 × 平台”执行按平台、类别和稳定路径哈希合成 19 个批次，同 runner 只安装一次依赖；普通 PR 仍只运行改动文件的批次。批处理报告除失败/错误/skip 规则外，还逐文件要求至少一个通过用例，防止平台文件全 skip 被其他文件遮蔽。该路径用于 schedule/manual 完整验证，不把完整集成集合重新放回普通 PR。

PR #745 的远程全选运行 `38559343364` 为 5 分 04 秒，Coding 8 个 job 为 2 分 16 秒至 2 分 58 秒，三平台恢复冒烟为 27–56 秒，全部通过；合并 push `38560055118` 在 50 秒内复用同树同计划证据完成。完整 targeted 批次在普通 PR 正确跳过，只在 schedule/manual full 计划运行。

分类策略 v5 支持混合文件的 node 级 targeted 角色。首批依据远程 slowest 证据，把 `test_agent_session_runtime.py` 中 27 个持久会话生命周期函数和 `arch/test_activation.py` 中 5 个真实产品组合函数登记为 Ubuntu integration；两个文件仍留在 Coding 模块回归，未登记的单元/合同节点继续执行，模块命令只用精确 `--deselect` 移出 32 个登记 node。修改混合文件会同时执行 Coding 回归和这些精确 node，不附加通用 E2E；定时 full 也纳入这些 node。catalog 用 AST 校验 node 真实存在并禁止与整文件 override 重叠；JUnit verifier 从逐文件要求提升为逐 node 身份要求，参数化 node 允许其具体参数实例匹配，不能由同文件的其他通过用例遮蔽。

首批 node 本地独立验证为会话运行时 29 个参数化实例全部通过、7 分 51 秒，Arch 5 项全部通过、1 分 44 秒。重新分类后的 Coding 0/8 代表分片为 459 项通过、3 项跳过、耗时 5 分 29 秒；本机明显慢于近期远程 runner，因此只证明剩余集合与 deselect 行为正确，实际 PR 墙钟收益仍以远程全选运行验收。

普通 test-only 路由随后收敛到已有 owner。PR #756 只修改 Harness 测试与测试说明，却因未分类测试路径继续触发 Hosting 模块和三平台 E2E；新规则令已知 `tests/<package>/` 下的 Python 测试实现与助手只运行该包现有模块回归，已登记 integration/platform 文件仍运行原 targeted owner，核心 smoke 文件仍运行 E2E。根级 `tests/conftest.py`、CI runner、未知非 Python fixture 及无 owner 路径继续保守取并集。以 #756 路径重算只选择 4 个 Harness 分片，移除 1 个 Hosting job 和 3 个 E2E job；不新增 job、route、平台、触发或失败条件。139 项 CI 路由合同、Ruff 和文档检查通过后仍需 PR 远程验收。

PR #757 验证普通 test-only 收敛时又暴露一处重复：已登记的 selector、catalog、JUnit/module report verifier 及其 CI 合同测试虽只选择 `ci` check，后处理仍无条件附加 Agent 模块与三平台产品 E2E。两者不验证路由文件的独有断言；现有 CI 合同已覆盖选择、聚合、Actions 语法、报告身份和 fail-closed 行为。因此 reviewed routing 文件改为只运行现有 CI 合同，不附加 Agent 或产品 E2E；未知 CI 脚本、主工作流、共享测试执行器及 scoped reusable workflow 保留完整或显式 owner。该变化只缩减既有选择，不新增门禁。

### 待审批门禁变更 AP-01：第二批混合文件 node 路由

状态：仅完成只读审计，未实现、未提交、未推送。曾在本地草稿工作树开始修改，
收到审批约束后已停止测试并完整撤销草稿，临时分支和 worktree 已删除。

| 项目 | 审批材料 |
| --- | --- |
| 目的 | 将 5 个混合 Coding 文件中的 32 个真实 Session/Product composition 节点从普通 Coding 分片移到精确 Ubuntu integration 路由；文件中未列出的解析、选择、状态机和合同节点继续归模块回归 |
| 触发变化 | 普通 Coding 源码 PR 少执行这 32 个节点；直接修改对应测试文件时由“一个模块 job”变为“模块 job + 一个 targeted job”，两者合计仍各执行一次；schedule/manual full 仍各执行一次 |
| 文件/节点数 | `test_agent_session_runtime.py` 8、`test_bootstrap.py` 11、`test_cli.py` 9、`test_continuity.py` 1、`test_control_services.py` 3 |
| 平台 | 仅 `ubuntu-24.04`；不新增 Windows/macOS 执行 |
| 唯一断言 | 持久会话索引/恢复、真实默认 runtime 与 capability composition、Session 级 policy/model/settings、transcript blob continuity、CLI 子进程入口 |
| #746 远程成本证据 | 32 个实例净 pytest 时间合计 111.10 秒；按文件为 24.16/38.84/32.32/4.30/11.48 秒，最慢单项 6.12 秒。环境安装另计；直接修改单文件仍低于 15 分钟 job 预算 |
| 重复关系 | 当前全部位于 Coding 4 分片；批准后使用精确 `--deselect` 与 targeted node ID 转移 owner，不新增测试用例，不与核心 E2E 合并 |
| 新增门禁面 | 对这 5 个测试文件的 test-only PR 新增一个并行 targeted job，属于 job/route 增加，必须审批；普通源码 PR 与 full 计划不增加用例数 |
| 失败语义 | targeted integration 零 skip、零 failure/error，JUnit 逐 node 证明；模块报告继续覆盖未登记节点 |
| 回退 | 删除这 5 个 node 登记，模块 runner 自动恢复整文件收集；分类策略版本随回退更新，旧证据不可复用 |

审批方未明确批准 AP-01 前，不实施该批或以其他名称拆分实施。

### 待审批门禁变更 AP-02：未归属 Architecture 合同精确执行

状态：完成路由、断言与本地成本审计；未修改 catalog、workflow、job 或执行路由。

| 项目 | 审批材料 |
| --- | --- |
| 目的 | 让 11 个目前只触发全量回退、却未被任何工作流执行的 Architecture 测试文件，在直接修改和 schedule/manual full 时由一个精确 Ubuntu contract 批次执行 |
| 触发变化 | 直接修改任一文件时，从“几乎全部活动 workflow + 7 个模块回归，但不执行改动文件”改为“轻量文档检查 + 一个 targeted contract job”；schedule/manual full 新增这 11 个文件的真实执行 |
| 文件/节点数 | continuity mutation 5D/5E、continuity provider 5C、current runtime ownership、owner component foundation、plugin contribution type system、PLC8、RCP0/RCP1/RCP2、unified plugin；合计 11 文件、107 个 collected node |
| 平台 | 仅 `ubuntu-24.04`；合同读取仓库源码与文档，不需要 Windows 或 macOS runtime |
| 唯一断言 | 连续性 owner/恢复顺序、当前 runtime 依赖方向、owner component 私有边界、plugin contribution/lifecycle、resource catalog 输入与发布边界、统一 plugin 架构库存 |
| 本地成本证据 | 同命令优化前 107 项通过、402.46 秒；三轮共享 import facts、只读 AST、候选过滤、单次函数节点扫描与精确 live-token 预筛选后 107 项通过、81.19 秒，减少 79.8%。依赖安装另计，单 job 预计仍在 15 分钟预算内，需 PR runner 实测确认 |
| 重复关系 | 当前没有 workflow 执行这些文件；全量回退启动的其他任务只产生无关覆盖。AP-02 会替换这次无效回退，不与现有测试 owner 重复 |
| 新增门禁面 | schedule/manual full 首次真实执行这 11 个文件；直接 test-only PR 首次让对应断言可阻断合并。属于新 route 与新失败条件，必须审批 |
| 失败语义 | 计划复用既有 targeted JUnit 验证：零 failure/error/skip，并要求每个登记文件至少一个通过项；不增加测试节点 |
| 回退 | 删除 11 个 catalog 登记并回退策略版本，恢复未知路径全量回退；旧策略产生的 PR 证据不可复用 |

审批方未明确批准 AP-02 前，只允许继续优化这些测试自身的执行成本，不实施精确路由。

### 待审批门禁变更 AP-03：Hosting 分类后的唯一执行 owner

状态：完成只读分类、重复与 Linux 成本审计；未修改 catalog、模块清单、触发或
执行路由。暂停的 Hosting workflow 内部可证明的重复执行已单独去除，但 workflow
仍保持暂停。

| 项目 | 审批材料 |
| --- | --- |
| 目的 | 将当前由 Ubuntu 完整目录统一执行的 Hosting 集合按真实边界分为 unit/contract、混合 node、POSIX/真实进程和 Windows platform owner，减少无关重跑并保持唯一归属 |
| 现状更正 | 28 个文件共 454 个实例；#711 后 `unit_hosting` 实际传入 `tests/hosting` 完整目录。历史 `unit-tests.json` 的 3 文件、44 项不限制 pytest 参数，普通 Hosting test-only PR 已执行被修改文件及整个目录 |
| 类别 | 137 个受控合同实例、113 个混合文件实例、160 个 POSIX/真实进程实例、2 个平台选择合同、42 个 Windows 专项实例；混合文件需 node 级 owner，不能整文件伪装成单元 |
| 平台 | 当前普通模块 owner 为 Ubuntu；POSIX 边界按 Linux/macOS 适用性；Windows native/LPAC/Job/pipe 仅 Windows。把节点移到新平台会增加失败条件，具体最小集合须在审批包中逐节点确认 |
| 本地成本证据 | Linux 全目录 401 passed、53 skipped，46.10 秒；去重及测试准备优化后，H6.2 的两个 POSIX 文件 31 passed、30.74 秒，其余目录 370 passed、53 skipped、9.29 秒 |
| 重复关系 | 完全 AST 函数体扫描无重复簇。暂停 workflow 原先在 Ubuntu 重跑两个 H6.2 文件、在 Windows 重跑四个专项文件；现改为同 job 一次执行、多份职责，不改变测试并集 |
| 待审批门禁面 | 把当前 Ubuntu owner 拆到 macOS/Windows targeted owner、增加平台失败条件，或恢复 Hosting workflow，均须明确审批；仅从普通模块集合移除重复或不适用节点属于缩减，但须与目标 owner 原子迁移 |
| 回退 | 若未来获批，回退分类登记和策略版本即可恢复当前 Ubuntu 完整目录执行与暂停状态 |

审批方未明确批准 AP-03 前，不把现有 Ubuntu owner 拆到新的 targeted 平台，不恢复暂停的
Hosting workflow，也不扩大平台矩阵。

### 已批准门禁变更 AP-04：AI loopback 节点显式归类

状态：完整目录执行缺口经复核已不存在；指定审批方于 2026-10-15 明确允许两个
loopback 节点登记为 Ubuntu targeted integration。实现不修改 `unit-tests.json`、
workflow、job、平台矩阵或 live/provider 执行范围。

| 项目 | 审批材料 |
| --- | --- |
| 目的 | 将两个真实本机 OAuth loopback 节点从普通 AI 模块集合中拆为精确 integration owner；7 个 vendor live 场景继续只允许显式授权执行 |
| 现状更正 | #711 已把 package runner 改为：存在包测试目录时直接执行完整目录。当前 `unit_ai` 实际执行 `tests/ai`、`tests/protocols` 和 AI/auth examples 合同；历史 7 文件 JSON 清单不再限制 pytest 参数，因此不存在“只执行 148 项”的覆盖缺口 |
| 类别 | 710 个受控 fake/in-memory/temp-file 单元与合同；`test_auth_api.py::test_login_returns_session_without_opening_browser` 和 `test_auth_oauth_lifecycle.py::test_real_authlib_login_store_resolve_refresh_lifecycle` 为本机 loopback HTTP 集成；7 个 vendor wrapper 为 live |
| 本地成本证据 | `tests/ai -m 'not live'` 为 712 passed、7 deselected，7.55 秒；最慢 loopback 生命周期 0.58 秒。完整现有 AI gate 还包含 protocols/examples、覆盖率、Ruff、mypy 与 catalog/import 检查 |
| 重复关系 | 忽略函数名称后的 AST 扫描只得到两组 live wrapper；每个 wrapper 调用不同 provider/protocol scenario，保留。此前两个错误命名但实际重复的 API register 用例已删除并有替代映射 |
| 已批准门禁面 | 两个 loopback 节点建立 Ubuntu targeted integration owner；AI 源码 PR 和相应 test-only PR 执行精确 loopback job，普通 AI 模块命令 deselect 两节点；全量 AI coverage 仍采集两节点，否则实测覆盖率为 89.68%、低于既有 90% 门槛；live 场景不自动启用 |
| 回退 | 回退 targeted-node 分类和策略版本即可恢复两个 loopback 节点随完整目录执行；live 环境变量与授权保持独立 |

本项只执行本机 loopback HTTP，不让普通 PR 访问真实 provider。

### 待审批门禁变更 AP-05：AppHost 目录必要集合完整执行

状态：完成全目录角色、重复和成本初审；未修改 `unit-tests.json`、分类 catalog、
workflow、job、平台矩阵、触发或失败条件。

| 项目 | 审批材料 |
| --- | --- |
| 目的 | 将当前由 Ubuntu 完整目录统一执行的 AppHost 集合按必要 unit/contract、真实进程和平台节点精确归属，避免把所有 1217 项长期视为同一种单元测试 |
| 现状更正 | 64 个文件共收集 1217 个实例；#711 后 `unit_apphost` 实际传入 `tests/apphost` 完整目录。历史 7 文件、165 项 JSON inventory 不限制 pytest 参数，普通 AppHost test-only PR 已执行被修改文件及整个目录 |
| 类别 | 7 个历史快速合同文件和其余 57 个文件当前均由完整目录 owner 执行；后者混合使用受控对象、临时私有目录、SQLite、锁、本机 socket、真实子进程与信号，不能整体标成纯单元 |
| 平台 | 本轮 Linux 离线集合 1216 passed、1 个 Windows native 条件 skip；把 Windows 或其他平台节点改为 targeted owner 会增加相应 test-only PR 的平台失败条件，须逐项审批 |
| 本地成本证据 | 安全选择器下完整目录优化前 103.74 秒，测试准备优化后 87.87 秒；最慢单项由 10.11 秒降至 2.02 秒。依赖安装另计 |
| 重复关系 | 忽略测试名称后的完整 AST 函数体扫描未发现重复簇；现有 AppHost workflow 的 G8/G9/G10 同配置重跑已另行改为一次执行派生报告，不扩大测试集合 |
| 待审批门禁面 | 为混合文件建立新的 targeted/platform owner、扩大平台或恢复额外 workflow 路径会改变失败条件，必须明确审批；从完整 Ubuntu 集合删除重复或不适用执行属于缩减，但不得留下无 owner 的必要断言 |
| 回退 | 若未来获批，回退 AppHost 分类登记和策略版本即可恢复当前 Ubuntu 完整目录执行；暂停状态与平台授权分别管理 |

审批方未明确批准 AP-05 前，不建立新的 AppHost targeted/platform owner、不扩大平台矩阵，
也不恢复任何暂停门禁。

### 待审批门禁变更 AP-06：Coding 剩余混合集合完整归属

状态：完成当前目录规模、实际远程执行、平台跳过、完全重复和热点初审；该材料尚未
达到逐 node 审批精度，未修改 classification catalog、模块清单、workflow、job、平台、
触发或失败条件。

| 项目 | 审批材料 |
| --- | --- |
| 目的 | 将 Coding 当前保守模块集合逐 node 分成必要单元/合同、真实集成、平台和 E2E owner，并消除 Ubuntu 模块中的平台 skip 与完全不收集的显式路径 |
| 当前规模 | 440 个测试文件、3959 个静态测试函数；已有 68 个整文件 targeted owner（53 integration、14 platform、1 E2E）和两个混合文件的 32 个 integration node |
| 当前模块集合 | 命令显式包含 333 个 Coding 文件和 1 个 Coding examples 文件；v5 远程报告为 3723 个实例，其中 3703 passed、20 skipped、0 failed，testcase 时间 530.29 秒 |
| 未证明路径 | 21 个显式路径在该 Ubuntu 报告中没有 testcase，主要是 Windows base、terminal marker、installed evidence、PR smoke 和 render contract；20 个 skip 来自 9 个 Darwin/Windows/secure-staging 混合文件。不能把“在命令参数中”当作已执行证据 |
| 热点 | `test_bootstrap.py` 138.79 秒、`test_cli.py` 50.74 秒、`test_lmux_command.py` 48.58 秒、`test_resume_runtime_publication.py` 33.61 秒；前者包含当前默认 Product composition，后两类包含真实 CLI/lmux 或逐故障状态隔离 |
| 重复关系 | 当前 440 文件忽略测试名称后的完整 AST 函数体扫描无重复簇；PR #779 的 8 个输入报告按 testcase 身份无分片重叠，4 片候选仅重新分配相同身份。相似恢复参数覆盖不同持久状态、撤销时点和恢复结果，不能按模板相似删除 |
| 现有性能 | PR #780 的四份远程报告为 918–975 项、净测试 140.647–190.205 秒、job 3 分 06 秒至 4 分 11 秒；与 #779 的八份报告相比 3771 项并集完全相同，减少 4 份 runner 准备 |
| 新增门禁面 | 将未执行的平台/marker 路径加入活动 owner、给混合文件增加 targeted node、改变平台或让 schedule/full 首次执行缺失路径，均会增加 route 或失败条件，必须逐项审批；本批不实施 |
| 审批前置 | 补齐每个拟迁移 node ID、唯一断言、现有 owner、目标平台、远程耗时和回退；与 AP-01 的 5 个文件去重后再提交，不以本初审直接视为批准 |

审批方未明确批准 AP-06 的具体 node 清单前，不完成 Coding catalog、不移动剩余节点、
不启用当前未执行路径，也不扩大平台矩阵。现有必要集合仅从 8 个执行分片合并为 4 个，testcase 身份不变。

同次手动 full 诊断没有作为成功证据：运行达到 15 分钟时按长任务停止原则取消，
唯一尾部 targeted integration #5 随后完成 pytest，报告为 92 passed、1 skipped、
835.20 秒，并被既有 integration 零 skip 校验拒绝。该组中
`test_package_worker_candidate_wheel.py` 占 711.327 秒；skip 是明确标记为专属 H6
耐久门禁的用例。优化重复 wheel 准备可以在不改门禁语义下继续；把该 node 移出
integration、允许 skip 或恢复 H6 都会改变 route/失败条件，必须经审批。

`test_explicit_worker_public_coding_session_reaches_installed_product` 内部原先分别以
`print`、`text` 参数构造两套 runtime，并对两套 runtime 执行完全相同的 Worker
选择、真实工具回合、启动 composition 和 tool result 断言。产品的
`default_runtime_builder` 对这两个值没有执行分叉，只共同检查 mode 属于
`{"print", "text"}`；text 的 mode adapter 行为已有独立合同测试。现保留 print
真实回合并删除第二套等价 runtime，本地原生单例 1 项通过、437.52 秒。该本地机器
明显慢于远程 runner，不能与 #780 的 204.969 秒直接计算加速比例。

同一 helper 的 disable、update、hosted 三个会话场景原先也重复执行公共
`build-coding-worker-candidate` CLI authoring。该 CLI 的产物字段、哈希与公开示例
路径已由保留的主 public-session 场景及专用 native CLI/author smoke 合同覆盖；两份
C Worker 源除注释外相同。三个场景现使用内部 candidate builder，把执行预算留给
各自独有的在线 Session fence、更新和 revoke 断言，公共 CLI 真实链路保留一次。
代表性的 disable 场景在改用内部 builder 后本地 1 项通过、163.30 秒。

### 待审批门禁变更 AP-07：Harness 完整角色与平台归属

状态：完成当前目录规模、统一模块执行、平台 skip、完全重复和热点初审；尚未形成
474 文件逐 node 的最终审批清单，未修改 classification catalog、模块清单、workflow、
job、平台、触发或失败条件。

| 项目 | 审批材料 |
| --- | --- |
| 目的 | 将 Harness 完整离线集合区分为受控单元/合同、本地进程/存储集成和平台原生 owner；保留所有必要断言并消除无效平台收集 |
| 当前规模 | 474 个文件、4106 个静态测试函数；Harness 尚无 whole-file 或 node targeted classification，也未声明 complete module catalog |
| 当前执行 | 统一 `unit_harness` 直接执行整个 `tests/harness` 和两个 Harness example 文件，再以 4 个稳定哈希分片运行；历史 `unit-tests.json` 的 13 文件清单不截断这条路径 |
| 当前远程证据 | PR #756 的 4 份 JUnit 共 5507 个实例：5386 passed、121 skipped、0 failed，testcase 时间 119.19 秒；分片 job 约 57–104 秒，PR 创建到汇总约 2 分 10 秒 |
| 平台缺口 | 121 个 skip 分布在 13 个文件，117 个为 Windows Product/Worker/epoch/lease/stream 合同，4 个要求 native Windows host；当前 Ubuntu 模块报告不能证明这些场景通过 |
| 热点 | `test_plc9b_adversarial.py` 52.69 秒，其中 checked-in wheel/Product composition 单例 27.95 秒；`test_exec_capture.py` 优化后 14.64 秒。前者本机隔离复核 55.75 秒通过，是真实重型集成，不按普通单元处理 |
| 重复关系 | 完整 AST 扫描只发现 POSIX/Windows epoch 并发收敛一组相同函数体；两者验证不同平台实现与布局，保留。4 个分片的 testcase 身份无重叠 |
| 已有优化 | reader fault 的 14 个 publication-point 组合保持原异常、进程退出和 transport 关闭断言，只把测试请求预算从 3 秒收紧到 1 秒；远程文件时间 42.57 秒降到 14.64 秒 |
| 新增门禁面 | 建立 targeted owner、启用当前只 skip 的 Windows 场景、恢复暂停 Harness workflow 或改变平台均可能增加 route/失败条件，必须逐 node 审批；本批不实施 |
| 审批前置 | 列出每个拟迁移 node、唯一断言、当前执行配置、目标平台、现有替代、实测成本和回退；确认与 Windows Shell、Hosting 和 Product Worker owner 不重复 |

审批方未明确批准 AP-07 的具体清单前，不完成 Harness catalog、不迁移本地进程或
Windows 节点、不恢复暂停 Harness workflow。现有 4 分片完整离线路径保持不变。

## HarnessTUI 增量审计与 AP-08

当前 `tests/harnesstui` 有 98 个 `test_*.py` 文件、625 个静态测试函数。该模块没有
complete module catalog、targeted whole-file override 或 targeted node；现有专用
workflow 使用维护在 Makefile 中的显式共享清单，并将 HarnessTUI core 与 Coding UI
分在同一 Ubuntu job 内顺序执行。两部分清单没有共同测试文件，Coding UI 的 39 个
Coding 文件也已从 Coding 后端模块集合排除。

PR #746 的全选运行 `38563194640` 中，旧 HarnessTUI core 报告为 1020 passed、零
skip、testcase 时间 143.47 秒，`tests.architecture.test_import_boundaries` 单类占
134.02 秒；Coding UI 为 588 passed、零 skip、30.89 秒，其中 UI import boundary
占 22.08 秒。既有 import-boundary 缓存优化后，PR #755 运行 `38575727132` 的 core
仍为 1020 passed、零 skip，testcase 时间降为 30.89 秒，合并 job 墙钟约 60 秒；
该 PR 从创建到顶层完成约 1 分 58 秒。优化改变的是重复静态扫描成本，没有删断言。

HarnessTUI core 的 16 个测试入口中，`tests/harnesstui` 与两个 Architecture 合同由
该 route 独有；另有 8 个 `tests/tui` 文件和 5 个 `tests/harness` 文件承担跨模块
消费者合同。当同一候选计划也选择 TUI unit owner 时，原配置会在相同 Ubuntu 源码
环境重复执行这 8 个完整文件；选择 Harness unit owner 时同理重复执行 5 个完整文件。
执行器现在读取已有选择计划，只在对应包 owner 同时被选择时从 HarnessTUI core
剔除这些完全相同的文件。单独修改 HarnessTUI 时仍保留原 16 个入口；TUI 候选为
8 个入口，Harness 候选为 11 个入口。该变化不新增 workflow、job、route、平台、
触发或失败条件，只消除同一候选、同一平台、同一配置下的整文件重复执行。

忽略函数名称并保留参数、decorator 与完整函数体的 AST 扫描没有发现
`tests/harnesstui` 内部完全相同函数体。本轮不删除测试 node。剩余逐 node 角色、
共享消费者合同的长期 owner 与 TUI 原生/渲染边界记为 AP-08；任何新增或扩大的
执行归属仍须先提交触发、独有断言、平台、墙钟、重复关系和回退材料并获得审批。

同一 Harnesstui job 同时选择 core 与 Coding UI 时，原实现虽然共享依赖准备，仍顺序
调用两次 runner，因而 Ruff、mypy 和 pytest 各启动两次。两组测试文件已经由 CI
合同证明互斥，静态源码清单也是现有 `check-harnesstui` 的完整并集；现在增加联合
runner scope，在双选时对去重后的源码和测试并集各执行一次。单选路径仍保持原
owner、报告和命令。完整 PR 计划的本地联合验证为 1516 passed、64 deselected，
精确等于远程顺序基线的 928+588 passed 与 5+59 deselected。

曾评估在同一 runner 并发启动两套完整命令；共享 mypy cache 触发 1.20 内部错误，
隔离 mypy/ruff cache 后虽消除竞态，但本机 CPU/IO 争用使 core 单组增至 214.92 秒，
因此否决并发方案。联合清单保持顺序工具执行和一次 pytest，不增加 job、route、平台、
触发或失败条件。PR #779 首轮运行 `38628254173` 的联合报告为 1516 passed、
64 deselected、零 skip/failure，pytest 62.64 秒，job 墙钟 1 分 32 秒；相对同类旧
运行的 2 分 24 秒缩短 52 秒（36%）。完整活动门禁从创建到汇总为 4 分 04 秒。

## TUI 增量审计与 AP-09

当前 `tests/tui` 有 87 个 `test_*.py` 文件、1336 个静态测试函数。忽略名称并保留
参数、decorator 与完整函数体的 AST 扫描没有完全重复簇。现有 TUI workflow 将
普通离线 unit、deterministic render、terminal platform、native PTY/ConPTY 与 tmux
按 marker、平台和 runner 分开；render、native backend/CLI、tmux 的 node 与 unit
集合互斥，Windows 平台执行也提供独立 OS 配置证据。

PR #775 的运行 `38620682467` 提供当前远程成本：TUI unit 在 Ubuntu 为 1273 passed、
118 deselected、13.83 秒，job 墙钟 30 秒；render 在 Ubuntu/Windows 各为 181 passed，
分别 36.56/26.84 秒，job 墙钟 56/66 秒；POSIX native job 为 48 秒，ConPTY job 为
78 秒。全部通过，暂停的 Windows Shell、Worker reboot 等 workflow 继续 skipped。

POSIX native job 原先先运行 9 个 shared platform 文件的 107 个实例（6.82 秒），
再运行 2 个 POSIX platform 文件的 7 个实例（0.27 秒）。这 11 个文件没有被 unit
marker 表达式排除，已在同一候选、Ubuntu、Python 3.11、源码 checkout 下由必选的
`tui-unit` job 完整执行；`tui_native -> tui_unit` 是现有选择依赖。因此 Linux native
job 删除这 114 个整文件重复实例，继续执行 12 个真实 PTY/backend/CLI 合同（14.43
秒）和 3 个 tmux 合同（4.71 秒）。Windows full 路径仍执行 107 个 shared、24 个
Windows platform 与 12 个 ConPTY 合同；普通路径的 ConPTY 短冒烟保持不变。

该变更只从现有 Linux native job 删除重复执行，不增加 workflow、job、route、平台、
触发、测试或失败条件。deterministic render 的 Windows 配置及剩余逐 node 角色记录为
AP-09；若拟缩减跨平台证据，须先证明平台输出等价。任何反向扩张仍须按工作区规则
提交触发、独有断言、平台、墙钟、重复关系与回退方案并获得审批。

## Dev 完整初审与 AP-10

`tests/dev` 的 45 个文件、406 个静态测试函数已完成角色、完全重复与成本初审。
该目录混合纯比较/证据合同、真实子进程监督、进程树回收、临时 Git/wheel、POSIX
行为、Windows observer 静态合同和 G17/G18 恢复验收，不能整体归为快速单元测试。
使用当前工作树源码和私有临时根执行完整 Linux 离线集合，结果为 1669 passed、
5 skipped，155.51 秒；5 项均为平台条件跳过。忽略测试名称并保留参数、decorator
和完整函数体的 AST 扫描没有完全重复簇。

现有 12 个恢复故障参数已经共享一份与原路径绑定的 seed，保留每个故障的独立恢复、
注入和拒绝断言。进一步尝试让正向恢复、shape 和 opaque 场景共享复制快照时，聚焦
验证出现 4 个 Store head 失败。原因是持久化 head 明确绑定 journal 的 device、inode、
mtime 和 ctime；复制后重写 head 会绕过这些场景需要验证的真实恢复证据。因此拒绝该
候选，不删除 node、不重写持久化证据，也不以共享可变 seed 换取数秒收益。

18 个 `test_lmux_*` 文件和 `test_screen_first_probe_readiness.py` 已收敛到既有
AppService 选择 owner，并去除无关 E2E，但 AppService workflow 仍处于暂停状态，
这些文件没有活动的直接执行 owner。让它们首次进入阻塞 PR、恢复暂停 workflow，
或增加新的 targeted job、平台矩阵和失败条件，均属于门禁增加。它们统一记为
AP-10：审批材料须逐文件列出独有断言、目标平台、现有与目标 owner、远程墙钟、
重复关系和回退方案；指定审批方明确批准前不实施。

本轮只形成审计和本地证据，没有新增或扩大 required check、workflow、job、test
route、平台/矩阵、触发条件或失败条件。

## 根测试资产审计与 AP-11

最终顶层目录核对补齐了 pytest 目录之外的测试资产。`tests/typing` 只有
`input_intent_contract.py`，它用 mypy 验证开放的 `InputIntent` kind、泛型协变和
`_prompt_input_intent` 的收窄边界。原实施计划要求显式运行该文件，但当前
`typecheck-tui` 只检查 `src/loushang/tui`，现有 workflow、Makefile 和执行器均没有
消费该类型合同。把它加入 PR 检查会让此前未执行的合同首次形成失败条件，属于门禁
增加，记为 AP-11；须由指定审批方批准具体触发、owner、成本和回退后才能实施。

根 `tests/fixtures` 不是独立测试模块。`worker/contained_query_worker.c` 由两个 Coding
package worker 测试消费，随 Coding owner 分类；`sessions/resume_overflow_with_thinking.jsonl`
在当前仓库没有源码、脚本、workflow 或文档消费者，是不产生执行成本的孤立数据清理
候选。删除它不会加速门禁，本批不借最终审计扩大变更范围。`tests/__pycache__` 是被
忽略的本地产物，不属于仓库测试库存。

本轮仍不修改 test catalog、Makefile、workflow、平台、触发或失败条件。AP-11 只是
审批材料入口，不构成批准。

## Worker sustained 路由修复

2026-10-15，指定审批方明确批准把 H6 sustained Worker 用例标记为 `live`。普通
targeted integration 已有 `-m not live`，因此该专用节点改为在收集阶段 deselect，
不再以 guaranteed skip 进入普通报告并触发零 skip 校验。既有 `worker-sustained`
工作流仍设置 `LOUSHANG_WORKER_SUSTAINED=1`，以不带 marker 排除的精确 node 命令运行
同一场景。该修复没有新增 required check、workflow、job、平台、矩阵或测试节点；
它按批准内容校正现有普通路径与专用途径的归属。

## Worker session 聚焦变体去重

Worker candidate 的 canonical `installed-protocol` 节点已经覆盖 deferred host 的成功、
admission 变化拒绝、清理历史，以及 selected ordinary Worker 的查询、续租后 payload
变化拒绝和资源投影。disable、update 与 hosted 三个聚焦 Session 变体此前在进入各自
独有状态转换前再次执行这两组公共回归。它们现在只复用相同的候选安装和授权准备，
随后直接验证 disable fence、update fence 或 hosted 首次会话与撤销。

完整 public-session 节点继续执行公共回归：它在 helper 返回后会消费多条 start-gate
历史验证 GC 保留与清理，不能按聚焦变体处理。一次把它一并缩短的候选运行在
`len(receipt_gates) > 1` 处失败，已据此收窄条件并重跑通过。最终本地证据为 disable
从 163.30 秒降至 120.80 秒，update 129.22 秒通过，hosted 聚焦路径通过，完整
public-session 511.00 秒通过。该批不改变测试 node、route、workflow、job、平台、
矩阵、触发或失败条件。PR #782 的远程 owner 为 49 passed、零 skip，pytest 净耗时
466.865 秒，targeted job 8 分 05 秒；相对 PR #781 的 574.865 秒和 9 分 52 秒，
分别缩短 108 秒（18.8%）和 1 分 47 秒（18.1%）。

同轮复核 scoped reusable workflow 的变更路由：每个已登记 workflow 修改都会运行
现有 CI 合同及自己的完整 owner，包括既有 full platform 分支；原选择器还统一附加
Agent unit 与产品 E2E，但二者不读取或验证该 workflow 的独有编排。现在只有未知或
共享 gate infrastructure 继续使用 Agent/E2E 保守回退，已登记 scoped workflow 不再
附加无关任务。该缩减不影响 workflow 自身 checks、Windows full 标志、host-runtime
完整模式或顶层 fail-closed 汇总。

## Full validation 报告假红修复与远程验收

定时运行 38652515258 的两个 Ubuntu targeted integration 批次分别完成
`92 passed, 1 skipped` 与 `103 passed, 5 skipped`，但旧 verifier 因批次存在任一 skip
而判失败。PR #786 将 integration/platform 的两条报告分支合为同一校验：允许条件性
skip，同时继续要求零 failure/error、整个报告至少一项通过，并要求每个登记文件或
精确 node 都存在通过 case。该修改只删除假红条件，不增加测试、job、route 或平台。

合并后的 `main` 手动 full validation 运行 38671220972 完成 60 个 job，结论 success，
总墙钟 631 秒（10 分 31 秒）。六类暂停长门禁保持 skipped；最长三个 targeted
integration job 为 568/524/499 秒，四个 Coding 分片为 189--248 秒。该运行证明现有
完整计划在 15 分钟预算内完成，也证明上述带条件 skip 的批次不再错误阻断，同时逐
owner 通过校验继续生效。

## 12. 本轮完成状态与终验

本轮按“不新增门禁”的授权边界完成：现有 workflow/job 全量盘点，重复执行与历史
子汇总删除，按改动分类的模块回归，必要三平台恢复冒烟，单一 fail-closed 顶层汇总，
Coding 与 HarnessTUI 分片/执行合并，Worker candidate 公共准备与回归去重，以及 full
targeted 重型文件隔离。普通 docs-only、test-only、模块源码和风险路径均有正负路由
合同；六类长工作流没有恢复。

PR #789 的首个实现 head 全量运行 38676143469 为 11 分 21 秒，54 个 job 成功、
6 个暂停项按计划跳过、零失败。合入同期 `main` 后，最终 head `c9689156` 的必需 PR
门禁运行 38677291922 为 4 分 53 秒；同一最终 head 的手动 full validation
38677731417 为 13 分 35 秒，仍为 54 success、6 expected skips、零失败。结合此前
`main` full validation 38671220972 的 10 分 31 秒，现有完整活动计划已有三次绿色
样本落在 15 分钟内；异常并发样本 38673724755 的 16 分 29 秒也保留并用于定位、隔离
三个重型文件，没有从统计中删除。

当前完成结论仅覆盖现有活动门禁的缩减、去重、执行优化与验收。AP-01 至 AP-11
包含首次接入、扩大 route/平台、恢复暂停 workflow 或新增失败条件，必须由指定审批方
对具体方案另行批准；这些候选保持待审批，不将未获授权的门禁扩张伪装成本轮缺口。
若未来批准其中任一项，应重新执行对应平台预算与至少三次有效运行，而不沿用本轮
完成结论自动恢复。
