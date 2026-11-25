# Coding剩余职责实施优先级

## Worker 历史读写入口的 Product 校验

检查点读取、发布和修复，V2 预检、暂存、提交、轮换和退休，以及只读 GC 证明复用 Package Product 对原生 owner 类型、产品标识和 Linux 限制的检查。Coding 保持原入口、错误和记录类型。历史审阅直接绑定已加载的 owner，V2 读取器、暂存、按需检查点和注册修复继续在使用时加载。锁、回放、读写权限和实际变更由原来的执行体管理。

相对 `69e8c2a93`，Coding 减少 46 行，Harness 增加 12 行，Hosting、其他生产 Python 和测试均变化 0 行，系统生产 Python 减少 34 行。Coding 为 77,880 行。67 项 Linux 既有用例通过，包含回收拒绝、中断后重放和保留历史复核。Ruff 与 mypy 通过，读取型绑定生成时未新增加载模块。

后续 C54 架构清单移除了已由 Package Product 接管的 Windows 批准依赖。修正涉及 3 行测试代码，C54 的 7 项既有断言均通过。

## Worker 原生操作入口和历史识别

Harness Worker CLI 先核实原生平台，再解析工作区并持有相应的 Product。Linux 续用只读候选状态入口，Windows 续用精确的原生 owner 类型检查。Linux 发布的审阅、批准、安装和修复由共享命令实现调用原有 Package Product 权限。Windows 共用 Wheel 读取、审阅身份校验与批准回执投影，平台自身的后端安装与恢复保留各自的合同。

Linux 历史审阅、准备、GC 检查和恢复直接使用 Harness 持有的已知文件名和暂存规则。故障注入仍作用于相应的实际读写 owner，Coding 保留产品授权、原记录类型和命令兼容。

相对 `a06aec91e`，Coding 减少 79 行，Harness 增加 132 行，Hosting 与其他生产 Python 变化 0 行，系统生产 Python 增加 53 行，测试减少 3 行。共享入口和执行归属的变化以此成本计入，文件识别规则停用旧转发的收益计入本批。

Linux 上 262 项既有用例通过，涵盖已安装原生 CLI、发布修复、准备与 GC 关联、固定历史和批准记录。Windows 平台关闭和错误优先级由既有测试在 Linux 验证，1 项原生 Windows 用例跳过。

## 能力 Provider 与工作区授权去重

Arch 与 LSP 共用 Harness 对 Provider 配置字段、Facet 接口和运行时所有权的校验及释放。两个内置插件分别从各自的 Provider 定义生成声明。工作区路径由 Harness Workspace 核验。LSP 共用查询与提纲的服务选择、协议能力检查和文档打开。Coding 保留分析语义、协议请求与结果、Provider 错误及产品配置类型。

文件工具和进程共用 Harness 的实时授权选择。Git 根目录解析集中到现有 Workspace Git 实现，沿用普通文件工具和链接工作树进程各自的范围。Coding 执行授权类型保留原字段及 slots。

以 `de9a7a7d8` 为基线，Coding 减少 207 行，Harness 增加 119 行，Hosting 变化 0 行，其他生产 Python 增加 25 行，增量位于插件声明实现。系统生产 Python 减少 63 行。测试代码变化 0 行。

Linux 上通过 399 项不同的既有用例。最终授权候选复验链接工作树、只读约束、恢复首条输入、真实 LSP 启动和 Arch、LSP 共用的 Session Graph。两项跨能力用例在两组回归中均通过。

## 受管服务的启动、接管与退出

AppHost 管理已安装受管子进程的参数与端点接管、就绪发布、中断重放和退出清理。Hosting 管理系统通知、原生进程证明、systemd 与 launchd 的查询及控制。普通 Mux、受管 Mux、Hosted 服务与 Canary 接入各自的现有 owner。Coding 提供产品标识、入口、状态路径、环境白名单和错误映射。

以 `9a9333ca5` 为基线，Coding 减少 460 行，Harness 变化 0 行，Hosting 增加 193 行，其他生产 Python 增加 519 行，增量均在 AppHost。系统生产 Python 增加 252 行。此次候选的 Coding 为 78,212 行，比 `546b209f6` 少 8,728 行，系统生产 Python 多 235 行。测试代码增加 98 行，沿用原有门禁与测试用例集合。

Linux 上共有 129 项不同的既有用例通过。真实子进程回归覆盖启动、复用、注册失败后回收，以及 Canary 安装入口。普通 Mux 和 systemd 通知模式验证实际子进程的就绪及退出，使用测试自有的通知套接字。launchd 通过现有模拟验证。原生 Windows、原生 macOS 和真实 systemd 用户管理器的路线待验证。

## 启用迁移的日志回放

Harness Plugin Management 用同一次已校验的日志投影支持读取、继续迁移和幂等重放。旧设置写入与原迁移日志入口共用接受后封锁规则。Coding 保留工作区与存量路径的绑定。快照捕获、写锁、日志版本以及迁移错误的类型和优先级沿用原合同。

以 `4f22c95b6` 为基线，Coding 减少 11 行，Harness 增加 6 行，Hosting 和其他生产代码变化均为 0 行，系统生产 Python 减少 5 行。Linux 共 39 项现有用例通过，涵盖迁移中断后重试、旧写入封锁、未来版本拒绝、普通 Session 的禁用状态以及架构边界。测试代码增量为 0。

## 前台与协作命令交付候选

以 `5c60d3a9a` 为基线。AppHost 管理本地 Mux 的连接、附着范围与资源关闭，以及受管 Mux 的工作区证据复核、创建恢复与停止交接。Mux 和 Hosted stdio 共用进程退出及错误输出处理。两个 Mux 入口共用 Coding 的产品接线，直接构造原 HarnessTUI Shell。Harness CLI 执行协作配方、处理失败并释放临时 Session。Coding 保留命令选择、输出合同、批准、默认模型与工具策略。合并时沿用当前 systemd 启动入口。

本批 Coding 减少 527 行，Harness 增加 182 行，Hosting 变化 0 行，其他生产 Python 增加 576 行，增量均在 AppHost。系统生产 Python 增加 231 行。以 `546b209f6` 为对照，八批候选合计 Coding 减少 8,257 行，系统生产 Python 减少 12 行。统计范围为 Git 跟踪的 `src/loushang` Python 文件，按物理行计数。测试源码增加 24 行。

Linux 共 155 项不同用例通过，覆盖真实 Mux 冷启动、停止后重启、创建与关闭恢复、协作命令、Hosted stdio 和精确架构约束。最后用本工作树的锁定依赖复验 17 项，覆盖 Arch 子会话的源信任以及两条 Mux 接线。原生 Windows 与 macOS 验证待完成。

下一轮沿普通 Session 的旧管理态和已围栏 Product Store 核对插件准备、Catalog 发布与失败回收。优先查找可删的第二套实现，复用 `SessionStartupCustody` 和 `AgentProductConstructionBinding`。两条路径已经共用能力计划编译，贡献选择也已合并，这些成果在本轮基线内。后续保留各自的信任证明、历史恢复和产品准入。

## Package 制品与作者验证交付候选

以 `9c5d21ec1` 为基线。Package Product 持有只读预览的已安装清单、围栏复核与句柄交接，统一外部 Wheel 捕获和依赖 Wheel 归档校验。现有 Worker 批准事务共用原生发行记录的读取与结算机制。Harness Plugin Authoring 承接一次性 Product 生命周期与离线会话取证。Coding 保留批准政策、产品来源选项和公开记录类型。基线已有的 Worker 候选离线证明直接复用。

本批 Coding 减少 251 行，Harness 增加 405 行，系统生产 Python 增加 154 行。接收端增量包括预览权限与失败清理、实际制品校验，以及作者 CLI 和 SDK 共用的会话证据流程。七批候选比 `546b209f6` 的 Coding 少 7,730 行，系统生产 Python 少 243 行。

## Hosted 执行与 Goal 交付候选

以 `c3581c798` 为基线。AppHost 持有显式应用准入与失败交接、Hosted 工作区目录和资源权限、交互选择恢复、会话标题请求，以及 Goal 命令与断线后的任务寿命。HarnessWork 处理工作计划准备、验证证据投影、事务关闭与历史回放。Coding 保留仓库验证和批准规则、产品默认值、会话及工作区的具体绑定。合并时保留 Windows 与 macOS 原生存储的检查路径，执行提交和资源字节保管沿用基线已有实现。

本批 Coding 减少 1,892 行，Harness 增加 140 行，AppHost 增加 1,425 行，HarnessWork 增加 790 行，AppServer 增加 4 行，系统生产 Python 增加 467 行。共享的命令、资源与工作记录机制在现有组件内实现。六批候选比 `546b209f6` 的 Coding 少 7,479 行，系统生产 Python 少 397 行。

Linux 定向回归通过 41 项，覆盖交互选择、资源权限、启动与失败交接、Goal 计划，以及保留原始会话日志的只读回放和历史工作区隔离。回放与隔离的三项复验保持原超时和断言。原生 Windows 与 macOS 路线仍需验证。

## C01 启动装配与 Continuity 交付候选

以旧版切换候选 `12fc10042` 为基线。Harness Session 接管已围栏、历史和初始工作区的 Catalog 准备、刷新与失败交接，并统一能力插件的已批准输入绑定。Harness Package Product 负责已安装来源的身份与工厂交接。Harness Continuity 接管已安装 Provider 的启动、发布、状态复原与关闭。Coding 保留 CompositionSet、产品默认值、批准和工作区执行上限。只读资源预览沿用基线的围栏复核和句柄寿命，并复用 Harness Plugin Management 的资源编译。

本批 Coding 减少 838 行，Harness 增加 886 行，系统生产 Python 增加 48 行。接收端增量用于复用三条 Catalog 启动路径、刷新和 Continuity 发布及清理。五批候选合计比 `546b209f6` 的 Coding 少 5,589 行，系统生产 Python 少 867 行。职责复核采用本地架构方法 `0f9bd3f`。

## 旧版插件首次切换交付候选

以合并候选 `b4aff3388` 为基线。Harness Package Product 接管冻结 Source 准入、首次快照与围栏的资源寿命、审阅证据校验、接受回执及已提交事务重放。离线迁移和普通会话启动共用围栏与重试机制。Coding 保留迁移允许范围、历史成员映射、具体命令、批准要求及公开记录类型。

本批 Coding 减少 576 行，Harness 增加 431 行，系统生产 Python 减少 145 行。首次围栏的投影清理由离线命令与 Session 两个入口复用，其额外代码已计入 Harness 成本。四批候选合计比 `546b209f6` 的 Coding 少 4,751 行，系统生产 Python 少 915 行。

## 历史索引与会话恢复交付候选

以私有数据生命周期候选 `a61f5b431` 为基线。Harness Session 接管历史索引和预览投影、恢复准入、运行时准备与发布。Harness Transcript 接管存量恢复记录的编解码与校验、首条输入的历史证明以及分离会话的模型选择落盘。嵌入式与 Hosted 入口共用准备和提交规则，Coding 保留批准、产品选择、记录的公开类型和历史错误语义。

本批 Coding 减少 700 行，Harness 增加 667 行，系统生产 Python 减少 33 行。基线已有的 Hosted 首条消息元数据绑定继续复用。三批候选合计比 `546b209f6` 的 Coding 少 4,175 行，系统生产 Python 少 770 行。

## 私有数据生命周期交付候选

以合并候选 `baab116f7` 为基线，集中交付备份归档、独立确认删除、恢复与备份过期。Harness Plugin Management 接管归档操作、存量记录编码、已完成事务选择和失败回放。两平台继续各自使用原生读写权限与回执；Coding 保留 Arch Installation、操作员准入、产品路径及命令合同。

本批 Coding 减少 749 行，Harness 增加 420 行，系统生产 Python 减少 329 行。基线中已接入的 POSIX 恢复事务单独计在原交付。移植共享 Product 打开逻辑时保留基线中的首次启动事务，复用统一的已安装版本和协议参数。

## 2026-11-25 本地插件发现

普通 Catalog 和备用原生扫描由 Harness Plugin Management 统一投影资源身份。备用扫描沿用 Resources 的目录检查、预算和关闭顺序。Coding 保留产品范围、预算和原错误类型。两条路线各自保留能够证明的选择与诊断字段。

这一步让 Coding 减少 37 行，Harness 增加 32 行，系统生产 Python 减少 5 行。

## 2026-11-18 阶段交付后的候选评估

阶段交付已通过任务 PR #901、集成 PR #902 合入 main `4100b4f65` 并同步本地；该提交下 Coding 为442份Python源码、100,763物理行。上游功能增长单列，不计入 C07 迁移收益。原 C07 Goal 继续：已交付版本剩余13,104行，距离多数退出仍差2,972行，整组未完成。以下为后续独立大块的候选顺序，不表示已开始 C01 或结束 C07。

2026-11-18按用户反馈调整：**C01 → C04 → C10／C02 → C13**。优先考虑职责是否通用、跨产品复用价值、完整机制能否退出 Coding，再比较已有 owner、系统净成本和兼容／验证负担。此前将 C13 排首位，过于看重已有传输接缝；LSP 的领域归属应降低其迁移优先级。组行数仅表示审计范围，不能预先当作迁移预算；所有适配和 Harness 增长均计入成本。

| 顺序 | 当前范围 | 首个完整候选链 | 已有能力与保留边界 |
| --- | ---: | --- | --- |
| 1．C01 启动／Plugin／资源装配 | 22文件／12,145行 | 准备根保管→产品审批／选择→依赖构图与装配→发布→失败交接与资源释放 | 优先复用 `PreparationRootCustody`、`SelectedProductPreparationScope` 和现有 Construction／Product composition。Harness 持有通用装配事务；Code 保留默认组合集、信任／批准、模型／工具选择及 Profile。历史高成本原型作为约束，不重复同形搬运 |
| 2．C04 Continuity | 2文件／2,809行 | 配置源获取→启动重放→准备／发布→失败交接 | 复用 Continuity staging、binding lifetime、Plugin Management 与 RuntimeProfileBinder；Code 保来源／限额／cwd和 canonical restore 政策，已共享 shutdown／Task 不重计，保真实 Path／FileCopy／引用支持 |
| 3．C10 Product runtime／C02托管接入 | 分别5,185／9,175行 | 剩余 freshness／open／repair／release 或普通／Resume交接 | 分别接既有 Package Product／Session／Transcript 或 AppHost owner；已共享 Catalog 读取、factory release、托管进程控制不重计，不把 AppHost 职责塞进 Harness |
| 4．C13 LSP | 21文件／5,228行 | 只审查仍有明确跨产品消费者的进程、传输或通用实例寿命机制 | JSON-RPC 传输及 `ProcessClientSupervisor` 已共享，不重复计益。LSP 初始化／请求语义、文档版本与诊断关联、服务器选择和 Tool 呈现可保留 Coding；不因协议代码量大就新增 Harness LSP 框架 |

C01 首轮应围绕一条真实启动链核实政策与机制边界，复用既有接收组件接管完整事务，实际调用方接入后同步删除旧协调体。不能把整个 `bootstrap` 文件都视为通用机制，也不能以大量回调把原函数拆散搬迁。若完整迁移的通用化成本过高，应记录具体边界和替代方案，而非用薄转发充作大块收益。

C13 已有 [`LspClient`](../../../../src/loushang/coding/lsp/client.py) 复用 [`ContentLengthJsonRpcProcessTransport`](../../../../src/loushang/harness/workspace/process/json_rpc.py)，[`LspServerSupervisor`](../../../../src/loushang/coding/lsp/supervisor.py) 复用 [`ProcessClientSupervisor`](../../../../src/loushang/harness/workspace/process/supervision.py)。这些事实支持继续复用底层能力，不足以说明其余 LSP 领域实现都应下沉。Harness 通用 DiagnosticsService 与带文档版本的 LSP 诊断收件箱也不能仅凭名称合并。

C08／C09的归档、恢复、接受事务已有共享owner，余量应优先证明具体旧流程可退出；C11／C12包含真实语法、呈现、仓库检查和评审政策，不按整目录行数排序。C07继续保留未完成清单，不能依靠字段搬运、压行或薄转发达到多数目标。

## 历史优先队列

以下保留2026-11-15的排序和当时“收尾交付后暂停Goal”的交付说明，供追溯；它不控制本轮状态，也不表示本轮收到新的暂停指令。

2026-11-15，按用户要求优先完整可迁移职责。排序依据是实际尚未共享的操作体、现有
owner能否完整承接、旧实现退出和全部适配成本；目录行数只作审计范围，不作可删除预算。
当前计量见[逐文件清单](coding-responsibility-inventory.md)，完整P1–P4范围见
[剩余责任账](coding-responsibility-remaining-audit.md)。

2026-11-15补充准则：优先直接复用已有组件，系统净减优先；若完整职责归属改善，
可接受必要且适度的共享通用化/Code适配增量，不要求必须另有重复机制退出。
历史否决保原证据；接口税过高、Code不减或未接完整旧体的实证仍有效，不能只因无去重
重下结论，也不按新准则机械重跑全部原型。

## 当前执行顺序：先完整大块，再局部精简

用户2026-11-15要求大块可迁移优先。下表列本批交付和剩余大块设计/成本审查队列，
不是已接受实施、预计删行或把目录换owner；验证无新完整接缝时跳到下一项，不回填字段小项。

| 顺序 | 完整交付边界与源码审查池 | 现有接收组件与Code保留 | 先解决的问题与退出条件 |
| --- | --- | --- | --- |
| 本次 A219整形不采用 | C07四源2460行池；Windows payload完整358span族及唯一mint registry试型 | 原PackageProduct attempt/authority；Code保名义/产品恢复政策 | 全税Code−228/Core+451/sys223 raw=uniform，8roles/7T/wide profile不值；1视角支持有限old-first、2建议整拒，Root整不采，无生产收益/pytest0 |
| 当前交付边界 | 用户要求完成本批后commit/push/PR/merge/sync local再暂停goal | 已接受A218及此前任务提交；A219仅拒绝记录 | 不开启下一批；必须验证发布/合并/本地同步后再标暂停，不提前称Goal完成或已暂停 |
| 已完成 A218 | C03整个应用级Transcript四操作绑定 | 原ProductTranscriptSession；Code保两个实际factory引用和配置/Resume政策 | Code−34/Harness+52/系统+18 raw=uniform，原/新同序111全过；16观察含在111内，0新T/Role/Task/gate，整C03未完成 |
| 已完成 A217 | 普通/Deferred Hosted完整审批展示与撤回两程序归一 | 原AppHost；Broker/Resolver权威复用，Code保原map接入与reply/close政策 | Code−58/AppHost+72/系统+14raw（uniform−75/−3），旧新89过/1原skip；32观察含在89内，非raw系统净减 |
| 已完成 A216 | C02 deferred control完整订阅/事件/激活委托/close-retry及同对象四状态 | 原AppHost Session control；Code保binding/identity/settings/model五政策成员和2纯profile | Code−82/AppHost+108/系统+26，uniform−84/+24；46不同节点/API/八旧观察通过，0新Protocol/T/Task、基类identity hook全计，非系统净减 |
| A215完整形状不采用 | C01捕获资源族169行池及external-only投影，完整五源原型 | 原Records/Snapshot/Session均接完整程序；Code保公共字段/工厂/错误薄桥 | 全税Code−111/Core+276/系统+165 raw=uniform；4roles/1T/3接收面分散，2视角价值否决、1支持有限old-first；Root整拒，生产收益0/pytest0，不救小片 |
| 已完成 A214 | C01三路线双root/preparation/legacy启动标记及outer失败消费 | 原Construction与cleanup family；四字段单一holder，Code保领域配置/工厂 | Code−86/Harness+139/系统+53，uniformCode−84/sys55；原202/14与九旧观察齐，实际202+24交集1，225不同节点过 |
| 已完成 A213 | C01两Product preparation253行的完整中性custody/第二capture/lineage/recheck | 原PackageProduct selected-revision family；Code在with内保领域体与nominal factory | Code−33/Harness+94/系统+61 raw=uniform；1T/0Role/所有薄口全计，实际验证见执行记录，不称全部253行迁出 |
| A209完整历史形状不采用 | C02三binding/source类+四catalog历史入口，并包含稳定snapshot读完整四源 | 原AppHost canonical family/Transcript源，Code保历史投影/名义构造/17公开方法属性入口 | 全税Code−20、接收+339、系统+319（uniformCode−38/sys301）；四源shadow静态过但成本不值，不安装/不跑矩阵，不摘close/fence |
| 已完成 A210 | C08 Windows retention snapshot原110行完整程序 | 原PackageProduct完整读/GC/目录/历史证据custody；Code保DTO/codec/构造薄绑定 | Code−72/Harness+151/系统+79（raw=uniform），原91/边界71及另31旧观察同；A184历史拒绝保留，不称去重 |
| 已完成 A211 | C01 managed Base208与Capability198完整装配池 | 原PM assembly直接执行两固定程序；Code保准入/领域选择与profile | Code−235/Harness+401/系统+166（uniform172），3roles/4T/错误数据与所有薄绑定全计；最终测试范围见执行记录，不计406为删行 |
| 已完成本批 A208 | C13/C14两完整reserved Tool owner准入/绑定/capture | 原Session tool_owner_binding，保Code五字段/域Consumer/工具工厂/nominal family | 六操作实例合三共享程序，Code−72/Harness+88/系统+16（raw=uniform）；原注册/释放机制复用不重计 |
| 已完成本批 A207 | C01公开SDK default完整137span三方法 | 原PM assembly及same desired/management；Code保原12字段/名义class/8profile事实 | 32次CAS、latest-own历史、command提交及部分commit原样；Code−128/Harness+181/系统+53（raw=uniform）；非活跃Base路线、未重造A51 |
| 已完成本批 A206 | C10完整factory/release家族，原3类8操作实例 | 原Package Product local Wheel runtime；Code保名义dataclass/Selection政策/构造桥 | 8→7实际执行体，两Worker lookup归一；Code−63/Harness+114/系统+51（raw=uniform）；原native机制与A155不重计 |
| 已完成本批 A205 | C11受管命令完整run/close/probe及native退出，原829行 | 原AppHost managed组件；Code保准入/选择/输出/UI/既有Runner | 39同self字段、8完整程序接入；Code−147/AppHost+439/系统+292（uniform192），原引擎不重计；A193静态拒绝保历史 |
| 已完成本批 A204 | C07完整双平台receipt authority及相邻Windows opt-in，13源 | 原Package Product/History/Windows Records/native readers；Code保DTO/codec/constructors/policy与八公开门面 | 按新准则接受完整职责价值，Code−514/Harness+944/系统+430（uniform+432）；五journal门面真实复用Core，原native机制不重计；A178历史静态拒绝保留 |
| 已完成本批 A203 | C02共享连接配置完整read/mutate/write/list，原173行文件 | 原AppHost client navigation与原Harness Config writer；Code保平台/临时工作区/请求政策与五公开绑定 | Code−107/AppHost+123/系统+16（uniform+14），无新对象/Role/T或gate；原40及另7局部对照通过，A149原writer不重计；Rust入口仍独立，不称Python dead |
| 已完成本批 A202 | C02完整多workspace集合协调，原183行文件 | 原AppHost canonical integration、WorkspaceRegistry与child Transcript；Code保构造/历史/平台/open政策和薄回复 | 同一实例完整接管集合/路由/retirement，Code−85/AppHost+170/系统+85（uniform+52），无新manager/Task/lock/gate；原native IO不重计，client_settings已有writer不再迁益 |
| 已完成本批 A199 | C09旧安装review→acceptance→binding catalog→source消费及崩溃恢复；原local_acceptance542/source_consumption397/binding_catalog391，共1330行原审查池 | 原Package Product/Resources、Journal/Config；Code保历史格式/产品支持范围、操作员选择与精确领域复核 | A199已完整接管accept/reopen/consume/consumed原双锁/parent身份/发布、prepared/settled重放、Settings事务及live source CAS；Code−340/Harness+480/系统+140，原74项实际过。1330并非迁出量，原分类/准入保Code；binding catalog已有_LegacyLocalSourceCatalog直接复用，A168已共享的Wheel重捕获不重做计益 |
| 已完成本批 A201 | C05 durable canary control Journal，567行完整文件为审查池 | 原Harness Journal持锁/严格读写；Code保G10启停/代际/历史/准入、路径与名义记录 | 已接完整neutral Journal scope，Code−148/Harness+284/系统+136，原34与另5本地对照过。Code状态/代际/历史仍原权威，scope保全部FNF/consumer异常差异和跨run锁；无新gate、无leaf IO重复收益 |
| A200完整形状不采用 | C03 Plan→隔离Writer→V1/V2 attempt→首输入commit→runtime publication及失败custody；continuation486/SessionManager783/activation_plan400，共1669行主要审查池 | 原Transcript/Session/Resume effects；Code保composition选择、授权和版本化产品记录 | 四源整原型raw Code+4/Core+277/系统+281，统一格式Code−54/系统+223；十个必要域/creation口及typing/facade税过高，无第二机制/依赖退出，不采用/不runtime/不摘fence。原97非pure领域构造保Code且寿命已Core，不重计397 |
| 后续条件设计 | C01/C15装配交接；先比较原Base/Capability两完整函数406行，不将bootstrap3626当预算 | 原Construction/Resources/Session | A183确认与A112同源，A51系统+202形状仍拒绝。只有新的完整事务接缝能显著减少适配才重开；无新接缝则继续下一未处置簇 |
| A205已接受 | ManagedMuxCommand完整驱动 | 原AppHost；Code保选择/输出/UI与既有Runner桥 | 13个值/效果/UI/Runner端口与2T/2roles全计，固定Core程序真实执行、无第二command/Task/state；A193历史不覆盖当前采用状态 |
| 后置 | 字段声明、薄公开adapter、prompt/profile | 保当前领域内容和必要兼容入口 | A196/A197已接受收尾；C19四源440行按A198源核执行已Core，不继续以局部十几行精简替代大块主线 |

A199已完成第1项的接受/消费固定事务，保原领域政策及catalog绑定；不是整C09完成。
A200已核完整outer handoff四源形状，所有适配后Coding raw+4/系统+281（uniform−54/+223），
静态通过但整形价值不足，不安装/不测；不是C03保留成本下界，也不重试同形参数压缩。
A201已完成C05中性lock/store整接缝，G10启停/代际/历史政策仍Code；实际Code−148而非567。
A202完成新原集合协调接缝，原183不是迁出量；Code保98行实际领域/兼容成本。
A209已实作完整历史custody/reader四源形状并按全税拒绝；不把其196行方法池作迁出预算，
后续先核下一完整Windows retention读，再从剩余完整职责选择，C01同形仍条件暂缓、A200不重试；不以小timeout/字段片代主线。
可迁移性排序优先于名义行数；完整剩余责任账中其余簇仍开放，不被本队列排除。

排序先比较能够整体退出的旧操作体和真实复用，再比较全部适配后Coding及系统的净值；
失败/取消/重试和资源交接必须一起替换。最近A171、A173、A174、A176合计Coding−680、
生产系统+422，属于职责收敛，不能作为系统净精简的证据。A179另Code−128/AppHost+224/
系统+96；A180完整前台控制另Code−116/AppHost+275/系统+159（统一格式+137）。
A181再Code−116/Harness+268/系统+152；A182再Code−76/Harness+115/系统+39；A185再Code−13/Harness+41/系统+28；A187再Code−88/HarnessWork+138/系统+50；A189再Code−71/Harness+102/系统+31；A190再Code−83/HarnessTUI+124/系统+41；A195四consumer整guard去重Code−29/Harness+21/系统−8；A196六流字段契约去重Code−46/Harness+12/系统−34；A197四类字段契约再Code−39/Harness+7/系统−32；A199完整接受/消费事务Code−340/Harness+480/系统+140；A201完整Journal scope再Code−148/Harness+284/系统+136；当前Coding107998行，距15K尚92998行，仍须按完整工作件推进。

| 顺序/状态 | 完整工作件 | 接收者及Coding保留边界 | 进入条件或实际处置 |
| --- | --- | --- | --- |
| 已完成 A171 | LSP进程传输完整生命周期 | 原Process拥有buffer/锁/Future/reader Task/request/cancel/close；Code保LSP初始化、诊断、服务器请求与优雅握手 | Code−274/Core+391/系统+117；126项通过；属于职责迁移，不是系统净精简 |
| 已完成 A173 | 配置兼容发布完整authority | 原Config LegacyProjection owner承接cache/issuer、writer与projection注册、聚合、Condition/deque、逐请求receipt和异常结算；Code保存量迁移政策/领域capture、guard和薄profile | 整物Code317→159（−158）/Core+246/系统+88；原135及固定旧29项覆盖通过，保持5原平台skip；不复用异常合同不同的普通Config通知队列，属于职责迁移 |
| 已完成 A174 | 根运行时关闭及Continuity完整绑定寿命 | 原Session Runtime接根关闭/两drain，原Continuity接composition/reservation/Task/identity-delete；Code保领域DTO、准入与薄profile | Code−153（含1行导入布局）/Core+301/生产系统+148（统一格式+139）；320项通过，持久55重放另验不重复累计；该片未含子Session113，后续见A176 |
| 已完成 A176 | Session profile完整失败保留链 | 原AgentProductSession接完整113退休程序，实际Slot/Registration/Publication/Assembly/Graph/Sandbox直接复用；Code保六字段/诊断绑定及两个纯状态hook | Code−95/Core+164/系统+69；原Core关闭Task/cancellation wrapper保原晚调用；BaseAssembly.close19仍Code，不据此关闭C01或C15整组 |
| 已完成 A179 | Hosted Continuity完整准备及失败清理 | 原AppHost Continuity共享两actual attempt的固定open/close；原Core ownership接完整清理，optional callers显式供应原join；Code保准入及薄profile | Code−128/AppHost+224/系统+96（统一格式+95）；原78+固定22+Core缓存1+既有join10过，原A0/G12–G14架构33项。两scope/14slots/失败债务保留；未关闭C02/KD011整组 |
| 已完成 A180 | G17 foreground CLI客户端完整启动/交接/关闭及Runner恢复 | 原AppHost optional integration接唯一控制状态，复用原launcher与terminal；Code保argv、准入、公开门面及两UI绑定 | Code−116/AppHost+275/系统+159；原135+旧观察6共141不同项过，显式portable6另重放不重复计。无另一算法退出，不称净精简；未关闭整C11 |
| 已完成 A181 | C13 LSP Supervisor完整实例寿命 | 原Process supervision显式子模块拥有同实例10事实，Code保LSP构造/initialize及状态诊断政策 | Code−116/Harness+268/系统+152（无格式差异）；原97+旧观察6共103不同项过。10hook/4T/2roles全计，无第二FSM退出，不称净精简或整C13完成 |
| 已完成 A182 / 仅中性投影闭包 | C10 Catalog→typed selection/admission/bundle evidence | 原current_preview直接使用既有Catalog/Input/Admission/Bundle与DTO；Code保产品选择/编译/open及中间复核/最终profile | 原84行两投影完整退出；Code−76/Harness+115/系统+39，35不同项过。单producer无第二算法退出；不是whole preview/open或整C10完成 |
| A183已核 / 当前形状暂缓 | C01 managed Base/Capability装配 | 原Resources/PM/Session机制已直接使用；剩余完整选择和失败custody仍在Code | 两完整函数208+198及整文件与A112逐字同；现有owner没有新整入口，不重做A51系统+202形状。重开须有不同整事务接缝及全成本 |
| A184完整原型不采用 | C08 Windows保留快照110行 | 既有PackageProduct backup family的stateless完整读入口；Code保实际typed/profile绑定 | 全税Code−72/Core+151/系统+79（raw=uniform），静态通过但无第二算法/实际依赖退出，不安装/不oracle；C08仍开放 |
| 已完成 A185 | C08 POSIX删除checkpoint | 原PrivateDataDeletionJournal完整27行phase统调，Code保确认/Desired准入和三窄绑定 | Code−13/Harness+41/系统+28（raw=uniform，含Code doc+1），同原14实际回归过；无新roles/T/锁，不重计physical remove或Windows去重 |
| A186已核 / 不造整类原型 | C12 Repository Goal command facade | 原Goal/Work/Delegation已接实际执行和取消；Code保trusted verification/review政策 | 204类/195方法/7methods完整核完；没有新Task/IO/关闭链可退出，busy与Core门控不等价，不摘busy helper或用宽政策callback整搬 |
| 已完成 A187 | C12 CodingGoal资源寿命 | 原Session Goal同self拥有18字段/9完整程序；原Scope Task/stages复用，Code保2SDK叶/tasklabel与领域准入 | Code−88/HarnessWork+138/系统+50（uniform42），同原163实际过/7deselect，1role/0T；Ctor私序/MRO/帧差异明示，C12仍开放 |
| A188已核 / 不重造A38 | C13 deferred LSP generation | 原Slot/Component/Graph/owner-generation/assembly机制已直接复用；Code保LSP选择/准入与原协调 | 19 own fields/230类/181方法；5源同throughA63生产切点，Process新API未替本层整路径。A38原型缺失，+142仅历史账，不假重新实核或该类不可迁 |
| 已完成 A189 | C12 workspace observation | 原Workspace Git家族；Code保GoalError/预算/消息与薄公开入口 | 两完整64/20程序退出，Code−71/Harness+102/系统+31；原118实际过，保不同观测合同，无第二算法退出 |
| 已完成 A190 | Screen SDK预热完整寿命 | 原HarnessTUI screen application host同self接timer/可见Task/切换/缓存/提示/关闭；Code保SDK政策及薄门面 | 六完整程序84span/8字段，Code−83/HarnessTUI+124/系统+41；130不同项129过/同1旧G11失败，无新gate，AI importTask不重计 |
| A191完整原型不采用 | systemd JSON控制/状态及通知信号寿命 | 原AppHost optional deployment adapter；Code保CLI/unit/错误与路径命名政策 | 两完整37+33程序全税Code−56/Core141/系统+85（uniform67）；逆AST/静态过但无第二机制或整依赖退出，短外壳税不足值。不安装/不测，不拆helper，非whole171/backend |
| A193历史拒绝 / A205已接受 | ManagedMuxCommand资源/失败完整驱动 | 同self接完整run/close/probe/原生父资源；Code保准入/选择/输出/UI | 全税Code−147/AppHost+439/系统+292（uniform192）；A193旧静态拒绝保留。A205按完整职责与必要增量准则接入并验证；13端口/2roles/2T均计，不重复计原机制，不判领域下界 |
| 已完成 A195 | 四消费者完整workspace身份协议 | 原Workspace.paths；Code保错误工厂/薄入口，原字段不变 | 原66span四kernel归一，Code−29/Harness+21/系统−8；原34实际过，不合CLI captureNone/Windows短路异合同，无新state/Role/T |
| 已完成 A196 | 六Windows semantic record中性字段 | 原Core空slots/schema基类；Code保原physicalslots/FQN/profile/peer types | Code−46/Harness+12/系统−34，原212实际过；constructor/fields/ownslots/wire/12旧pickle原期待不变，ownannotations/ClassVar字段dict演进有界披露，不增加DSL或影子槽 |
| 已完成 A197 | 四类中性record完整字段契约 | 原Core空slots/schema-only；Code保7名义类型覆写及原公开值类 | Code−39/Harness+7/系统−32，原1138实际过；37重复声明退出。另25类209字段有原ownannotations固定观察，不硬套 |
| A198源核 / 降低迁移优先级 | C19 compaction四源440行 | 四完整执行操作已直接Core，Code保266行内容profile与公开绑定 | 未发现新的整运行机制可退出；不造partial改公开签名，不计新增收益，不作永久保留下界 |
| A204已接受 / A169、A178为历史比较 | Worker Product完整收据authority | 原Package Product/Resources；Code保政策、验证与兼容DTO | A178原13源静态原型−512/+944/系统+432的否决保历史。A204按明确新准则核必要接口税，并将五Code journal门面接实际Core，完整−514/+944/系统+430（uniform432）接受；并非仅无第二引擎就永久拒绝，也不重计原native/History |

G17与C13本批实例寿命、C10两段中性证据投影已完成；后续核实顺序为：
**C09接受/消费固定事务按A199完成；A200完整Resume形状按成本拒绝，C05中性持锁/存储整链按A201完成，余大块继续重选**；A197已完成四类契约，停止连续挑字段和薄适配器作主线。C19按A198降优先级；固定ownannotations不能直接套A196。A188子图原接口未变；A187完成Goal寿命，A186命令门面无新替代；
C08 checkpoint按A185完成，
C01按A183暂缓，
Windows完整快照按A184全成本拒绝，systemd两程序按A191完整原型拒绝；
这是进入完整接缝验证的顺序，不是已接受迁移或
预计减量。A182确认preview/open其余主体为Code产品政策及既有Core IO接入，
不以厚compile/open回调强搬；A183实证C01与A112原件未变，不自动重试同池；C08先剔除已经共享的
restore/archive，不能再计搬迁收益。
Worker两次旧原型的否决保历史；A204已按新准则完成完整authority接受，其余Worker政策/平台工作仍按实际接缝排序。

其它较大操作体按下表保留比较；有阻断的范围不是排在小项之前无限等待的实施任务。
A178历史上完成Worker新接缝成本决策并拒绝接入；A204已按明确新准则完成接受及实际对照，非永久暂缓。A179曾完成202行审计范围的
完整prefix替代；A180完成foreground整控制，A181完成C13实例寿命，A182完成两段证据投影。
A183确认C01原成本阻断，A184完整快照形状不采用，A185完成POSIX checkpoint；
A186明确领域命令，A187完成Goal具体资源寿命；A188据当前及历史生产API不重启
A38同形原型，A189已完成两条Workspace实际IO观察完整合同及全成本，A190再完成Screen SDK整寿命，A191 systemd两条完整native程序全成本不采用，A193完整ManagedMuxCommand驱动当时不采用、A205重核后已接受，A195多消费者真实重复已消；A196六流标准字段契约已接受，A197四类已按真实注解/旧数据合同完成，后续改按大块混合职责重新排序，
不按目录总量承诺迁移收益。

A178核对A169最终原件确认，其POSIX authority已经继承ReceiptHistory；直接继承本身
不是新方案或收益。待比较的是实际初始化/新鲜历史读取绑定、Windows原Records公共
操作与构造、泛型不变量，以及双侧facade/profile的全部成本。原Code薄构造可以保留，
不为迁出几次字段赋值再增加一轮初始化回调；必要读取顺序优先于减少参数数量。

| 核实顺序与较大比较范围 | 当前完整范围实数 | 已有复用与不能立即迁移的原因 | 重新进入条件 |
| --- | --- | --- | --- |
| A183核实后暂缓 / C01 managed Base/Capability装配 | 两完整函数208+198=406行，函数/整文件与A112逐字同 | Resources、PM、Session已共享；try边界、显式reconcile、禁用关闭、replay异常和lease先持有/失败custody仍不同。A51完整形状系统+202已拒，无新整入口 | 原owner提供有据且全成本更小的整事务API；不恢复阶段回调Context，不把当前bootstrap3626行作可删预算 |
| 5 / C08私有数据三类owner | 三类合计549行/方法510：Read195/172、Restore170/161、WindowsBackup184/177 | 原DeletionCoordinator、POSIX archive及Windows事务已共享；RestoreOwner.restore83行已调用Core完整restore。31源扫描所见直接native调用多为路径/身份检查，不是未迁物理事务 | 先证明一条尚在Code的完整事务及窄codec边界；整组仍开放，不按当前6665行整包搬迁 |

A182审计原preview271/open122与462方法行：只有84行Catalog身份连接和admission/bundle
投影可在不吞Code编译/信任政策、无厚IO回调的前提下整体交给原证据owner；其余保留
并非最终不可压缩下界。完整字段/clock/复核顺序保留，不据方法总量承诺整类减量。

A181核对A38原件：其拒绝对象是另一类`CodingDeferredLspGeneration`延迟子图，
不是`LspServerSupervisor`。前版将该决定紧邻C13描述，只能表示泛化适配成本的风险，
不能作为当前Supervisor曾被拒绝的证据。本类已按A181独立完成完整接缝与成本验证。

A184已完整试算Windows snapshot110，保GC/Desired/state pin/staged debt/reappearance、
原FD关闭和晚权威/hash后，全接口税系统+79；没有第二机制或实际依赖退出，未采用。
不直接并POSIX snapshot63，也不摘小status切片挽救。expiry recovery102及preview91
仍主要是产品授权join，底层复制/rename/收据事务已Core，路径/身份读取仍在Code原点。
A185已完成POSIX delete_confirmed52中原27行checkpoint的Journal接管；Code准入/offline
和三个原窄端点保留，完成用terminal renamed。既有remove_started与restore83不重计；
Code净减13不是27，C08整组仍非最终领域下界。下一C12需先区别原Goal/Work协调与
Code领域verification/review准入；A117 cold事实已有owner，不重新搬迁或计益。

上述类/方法范围有包含关系，不能相加作可删量。跨簇扫描覆盖434份当前Code源码的
长函数/owner导航，并深核表列实际程序及Core调用，不等于全树语义重复证明或领域下界。
A179/A180/A181按不同完整接缝接续交付，不将其包含范围相加作可删预算；803方法行
Worker不同接缝已作完整原型并因全部成本不足以抵相称复用而拒绝，不承诺直接搬走
803行，也不回到零碎helper。

A175实查已确认activation policy/receipt/witness及多数manifest/candidate事实早已Core；
仅换剩余DTO不能消掉A169完整authority接口成本。A178曾连具体journal/最少中性facts、
generated/duck reader及整Windows opt-in事务作完整比较并保外部。A204在新价值准则下
将完整形状接入，并让五journal门面执行Core公共体；原A178历史证据不改写。

不再排作待整池搬迁的范围：A170核查的inventory/snapshot712行，其root/bundle/member/
list/recheck/finally已由SnapshotEvidenceStore拥有；Code保存量分类、支持政策与新鲜度时点。
A173核查的HostedCatalog943行，其canonical list/open/create/discovery/candidate custody已
在A80–A85的AppHost/Transcript实现。两者仍有未处置边界，但不能重搬或重复计益。
A172对C01/C15/C17共15720行的调查同样确认主构造、Task、Slot和历史读取寿命已共享；
没有证据可把整组判为可删除或永久保留。

每项先核真实消费者、旧操作体、失败/取消/重试/恢复与资源结清，再作完整替换。窄政策
接口可以保留，但Code领域capture/guard回调不冒称纯函数，也不把已共享IO重计为本片收益。
没有已证明可直接承接的更大完整替代程序时，继续设计下一完整接缝，不填虚构的大块
承诺，不连续以局部十几行去重替代主任务。

C04 Continuity的KD003、托管历史KD011等明确待确认边界保持原状态；其余C05/C06、C08、
C10、C12–C28继续在责任账中，不因排序退出P1–P4。领域能力、内容与产品政策换目录后
仍计Coding归属成本。未建立≤15K不可压缩下界；每批报告Coding、接收组件、兼容适配和
系统源码净值，新增测试/探针另列。完整Goal仍以领域化及≤15000行为验收条件。
