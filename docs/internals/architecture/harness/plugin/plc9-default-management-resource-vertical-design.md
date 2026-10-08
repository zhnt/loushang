# PLC9 增量设计：管理状态闭环与本地 Resource/Skill 插件纵切

状态：三视角设计与实现评审通过；P0/P1 增量已实现。不表示默认切换。

## 目标与边界

在现有 PLC0–PLC9 合同上交付两个连续增量：

1. **P0 管理查询闭环**：Coding 的 `--list-plugins --list-plugins-format json` 用只读组合呈现现有管理 Owner 实际可提供的状态，保留旧 JSON 字段及 TSV；明确未接入或不属于 A1 的维度。现有 `enable`/`disable` 的 legacy 命令行为保持。
2. **P1 首个外部插件纵切**：在全新、已显式 cutover 的 Coding workspace 中，让一个本地、数据型 Resource/Skill wheel 完成作者产物、显式 Source 准入、安装、启用、Session 使用、更新、停用和退休。每一步用正确 Owner 的证据解释，不要求单一列表覆盖所有阶段。

这里的“默认管理”只指 Coding 已有管理入口使用同一管理应用及读模型。它**不**等于把新 Package 生命周期设为默认执行模式。正式默认切换需独立决策和验收。

本次不新增能力图节点、Owner、持久化时钟、通用 PluginContext、Profile 机制或管理状态副本。允许在现有 Product/Package Owner 内增加一条**有界本地 wheel 准入记录与只读证据适配**，仅服务这个纵切。不做 marketplace、MCP 动态接入、远端服务、UI/SDK 管理入口、第三方 Tool/Command/Provider 作者扩面、legacy workspace 迁移、自动 GC、跨 Owner 原子替换。内置 `coding.base` 的 Tool/Command 行为仅作回归哨兵。PLC9 已接受的第三方 worker 准入主题保留原计划，不进入这个纵切。

## 增量依据

- [插件架构 V2](architecture.md) 固定 Product Kernel、Runtime Profile、Capability Graph、Policy/Approval/Authorization/Sandbox 与各 Owner 的职责边界。
- [PLC 协调计划](plugin-lifecycle-coding-pluginization-plan.md) 已交付 `coding.base` 的 Tool/Command/Resource 路径；Tool/Command pack 仍由确切 Owner 准入，不能推断为公共外部作者 API。
- [PLC9A1](plugin-lifecycle-plc9a1-contract.md) 已实现传输无关的命令/查询端口和合并 Desired State、Source、Package、Instance、Retirement 的 V1 投影；CLI 已接入列举及启停。
- [PLC9A2](plugin-lifecycle-plc9a2-contract.md) 已定义 `legacy`、`dark`、`enforced` 的 Product 路由及精确 epoch 准入；当前 Coding 默认仍是 `legacy`，不能因 P1 演示而暗改。
- [PLC9B](plugin-lifecycle-plc9b-contract.md) 规定有界 Source、隔离、仅 wheel 验证、不可变发布及崩溃恢复；本设计复用这些约束，不引入源码构建或安装钩子。
- [RCP5](resource-catalog-rcp5-contract.md) 已规定默认 Coding Resource Catalog 的 v4 mount、同代 Skill 消费及来源回执；P1 验证这条现有链路，不另造 Skill Owner。
- 当前 `loushang.plugin` 公共包作者入口接收 `CapabilityProviderSpec` 与 `ResourceItemSpec`；`resource.skill` 是本纵切唯一新增的外部作者样例，不宣称 Tool/Command pack 已开放给第三方。

## P0：复用管理读模型，补足状态解释

`PluginManagementReadModelProjector` 仍是 A1 管理事实的唯一汇聚点。CLI 通过 `PluginManagementCliBinding.query()` 获取 V1 投影；不直接读各 Journal/Store，不推导新的“真实状态”，也不写修复记录。当前 Coding binding 只注入 Desired、Management operations、Migration 和 Source；Instance、Package、Retirement 尚未接入，因此仅追加 JSON 字段无法显示实际收敛。P0 将已有 Owner 的只读快照接入同一 projector；确实无 Owner 数据的维度保持 `unknown`/`unsupported`，不能显示为空即正常。

在现有 JSON **数组**的每个记录中只追加 `management` 对象，原 `name`、`source` 字符串、`desiredState` 等字段及 TSV 均不改义。`management` 内用 V1 `InstallationView.to_dict()` 的字段名/空值形状承载安装键、Source 可用性、选中 revision、操作摘要、退休/清理债务及 unknown dimensions；全局 Owner revisions 与按安装键筛出的 skew 也在此对象内明确标为投影级元数据。空数组不能承载全局诊断，P0 不宣称它能报告无安装记录时的 Owner 故障；完整 V1 查询端口保留这份证据。这里不把 V1 的 `source` 对象覆盖旧 CLI 的 `source` 字符串，也不新增命令。

展示原则：Source 存在、Desired State 为 `installed_enabled`、Package 已发布、Instance 被选中、Resource 已挂载、Session 正在使用，都是不同事实；不能把其中一个显示为其余事实。未知、缺失 Owner、revision skew、退役中和清理债务必须如实呈现。A1 management operation id 可在 V1 投影中关联；**A2 Package acquisition/验证/发布前失败**及 quarantine cleanup 不属于现有 A1 operation/cleanup 字段，须保留 A2 outcome 与 Package Owner 的独立证据，不以空数组冒充无债务。RPC 如需同等状态，复用同一查询端口并按其既有协议适配；不在 P0 新造 Harness RPC 合同。

现有 CLI binding 启动时会执行 `management.recover()` 并协调 legacy settings，可能写入；因此 P0 将 **list 的查询组合**与恢复/命令组合分开。完整 `--list-plugins` 路径不执行插件 Python、不恢复 pending operation、不发布 compatibility settings；命令路径仍按原合同恢复。先读各 Owner 的一致快照，再格式化；如果无法获取某 Owner 的可信快照，显示其维度未知，不跨时点拼接成 `active`。

P0 验收：对含 pending operation 的磁盘快照执行真实 CLI list，操作日志和领域状态不变且仍看见 pending；JSON 旧字段与 TSV 兼容；已有 Owner 能提供的 revision/skew/退休/清理债务可见，未接入维度明确未知。以现有 A1 合同测试为基线，另测 Coding 真实绑定，不只测 projector 单体。

## P1：本地数据型 Resource/Skill 插件纵切

固定样例是外部作者的本地 wheel，仅含 `document` 来源的 Resource/Skill 声明与无 actions 的 `SKILL.md`，无 `in_process` 声明、运行入口、额外依赖或可执行贡献。作者在构建环境使用公开 `loushang.plugin` 的 `resource.skill`/`package()` 生成 manifest 与声明文件，补上 `SKILL.md`，先对目录做不执行插件代码的 `loushang-plugin validate`，再打 wheel 并按 PLC9B 检查 wheel。目录验证不等于 wheel 准入，也不等于运行时 Approval。

现有 Coding Product policy 只绑定内置 wheel 和 legacy 迁移来源，普通外部路径无法分类；现有 Source authority 还要求 binding 位于 Product 的私有 Source root。P1 将**这个样例**限制为规范 wheel 文件名与目录布局：Plugin ID 等于规范化 distribution name，`requested_package` 由文件名中的 distribution/version 得出，manifest locator 固定为 `<distribution_package>/plugin.json`。这些只是待核对的外部声明，不从归档内容推定事实，也不推广为任意作者包规则。调用方因此只需传绝对 wheel 路径。**已 fenced 的 Product Owner** 用有界、no-follow 的安全采集固定 wheel 字节与 digest，原路径仅作 provenance，把字节放入既有私有 Source root 的受控路径。将上述预期身份、受控路径和 digest 作为 epoch 绑定的 Product-owned 授权记录，再以**受控路径**生成现有 `PackageProductLocalWheelBindingV1`。此步不自行解析不可信归档。wheel 成员白名单、实际身份、无依赖/运行入口的检查复用 PLC9B 隔离验证后的候选及证据，必须在 publication/handoff/enable 前匹配授权记录；安装时重新核对同一 digest 与当前 epoch。Source 授权失败不得进入 A2；内容检查失败在既有 Package 阶段终止，均不能退回 legacy。不得通过修改 Product 源码中的内置 binding 或预埋测试 binding 来验收外部包。

全新 workspace 显式执行现有 cutover 后使用 PLC9A2 Product 路由；未通过 cutover 的 workspace 不参与本纵切。**artifact acquisition/publication 走 A2 Package intent，Desired State 启停/移除走 A1 management command**；Product handoff 在原有 Owner 中执行。现有 A2 仅有首次 install handoff，不能把第二次 install 当 update。P1 单独补齐 Product 更新到既有 staged update/retention handoff 的窄接缝，保留当前启停状态、前任 revision CAS 与中断恢复；不增加通用更新框架。

Coding CLI 的现有管理 binding 指向 pre-B layout，启停还强制 legacy migration 阶段。P1 必须按已激活 epoch 选择**同一组 fenced B Owner** 来绑定查询与命令，并用 Product 安装/准入证据代替 fresh B 的 migration 门槛；legacy 路径保持原门槛和回执。不能在 B 路径注册 legacy runtime、触碰 pre-B journal 或复用旧 settings 兼容发布。Resource Catalog 接收被准入的精确 Resource revision；Skill 在 Session 捕获的同一代 Catalog 中可见，Model Input 记录其精确来源。

固定用户命令映射，不另开一般性的插件管理 CLI：

| B 模式操作 | CLI 入口与 Owner 路由 |
| --- | --- |
| 首次安装 | `--install-package /abs/path/plugin.whl --package-scope project`：Coding Product 先把输入 wheel 授权并采集到私有 Source root，再以受控 source identity 发 A2 `install`。 |
| 查询、启停 | `--list-plugins --list-plugins-format json`、`--enable-plugin <plugin-id>`、`--disable-plugin <plugin-id>`：只绑定当前 fenced B Owner；启停写 A1。 |
| 更新 | `--update-package /abs/path/new-plugin.whl --package-scope project`：P1b 复用同一安全采集，走补齐后的 Product staged update 与 retention handoff。 |
| 移除安装 | `--uninstall-package <plugin-id> --package-scope project`：P1a 的 B 专用适配把 ID 解析为唯一已安装记录，提交 A1 `absent`；不调用当前 install-only A2 路由，不删除 Source 文件。 |

上述 B 专用映射只在已 fenced、显式 Package Product 模式生效；legacy 参数语义不变。`--remove-plugin` 仍只移除 legacy settings Source，不能作为 Product 卸载。用户层验收必须执行这些命令，不能以测试直接调用 Owner 代替。

更新必须保留旧 revision 到消费方释放或既有退休规则允许清理；移除先表达 Desired State `absent`，不等于立即物理删除 Source、包或审计记录。新 Session 捕获新 generation；未刷新 Session 保持已捕获的快照和历史 Model Input 来源，但旧 Catalog Consumer 退休后不得继续发起加载，必要时报告 `restart_required`。紧急 revoke 按现有语义阻断后续使用，不能由 graceful disable 代替。验证失败、Source 丢失、发布中断、准入失败、退休未完成时，不宣称新 revision 已生效。A1 投影解释 Desired/Instance/Retirement；A2 outcome 与 Package Owner 的只读 operation/quarantine cleanup 证据解释发布前失败。P1 仅补这条只读关联，不把 A2 事件写进 A1 operation journal。

纵切验收点：

| 阶段 | 必须看到的证据 |
| --- | --- |
| 作者与准入 | 从未预埋绑定的 fresh workspace 构建目录、验证、打 wheel；Product 显式记录原路径 provenance、受控 Source 路径/digest、预期 Plugin ID/manifest locator；混入执行贡献、actions、依赖，以及畸形、超限或路径替换的 wheel，均经真实外部准入入口拒绝且不得启用。 |
| 安装与使用 | 真实 cutover → 上表 CLI install/list/enable → 新 Session Skill/Model Input；A2 与 A1 operation id 各有来源，可关联但不混同。 |
| 更新与停用 | 上表 CLI update/uninstall 经 Product staged update/A1 absent；更新保持启停状态并执行 CAS；新 Session 选新 revision；旧 Session 的快照/历史证据与退休 Consumer 规则一致；CLI disable 后新 Session 不再获取 Skill；退休状态可见。 |
| 失败与恢复 | 验证/发布/准入故障、Source 不可用和中断恢复沿对应既有 Owner 路径；A2/Package 证据呈现 pre-handoff 失败及 quarantine 债务；A1 投影不误报 active。 |
| 回归 | `coding.base` 的 Tool/Command 与现有 Resource/Skill 行为不因外部数据包路径改变；`legacy` 默认模式不变。 |

## 实施切片与停点

1. **准备**：以 PLC9 现有 issue/合同确认交付范围，记录基线测试；核对当前公开作者 API、Coding 模式与 Resource Catalog mount。若当前代码与上述合同不一致，先修正设计，不直接补新抽象。
2. **P0**：拆出真实 CLI list 的只读组合，接入已存在 Owner 的快照，追加兼容 JSON 字段；用 pending、unknown、skew、退休/债务的真实绑定验证。不能在 CLI 猜测缺失事实。
3. **P1a 首次安装**：加入一个 Product-owned、epoch 绑定的本地数据 wheel 准入记录；按 B Owner 绑定 Coding 管理 CLI，走真实 cutover → install → list → enable → Session → disable → absent 路径，补 A2/Package 只读失败证据。
4. **P1b 更新与退休**：仅补当前 install-only Product 与既有 staged update/retention 的接缝，验证 CAS、Session pin/Consumer 退休和中断恢复。P1a 不通过时不启动 P1b。
5. **停点**：P0/P1 证据齐全后评估是否另起默认模式切换或其他插件作者类型；本设计不预授权切换。

实施按 workspace 的高风险变更方法使用跟踪 issue #509、隔离 worktree、基线和回归。默认模式切换及其他作者类型仍需独立设计和验收。

## 实施记录（2026-09-26）

- P0 的 legacy 管理列表接入实际 Instance、Package 与 Retirement 快照；JSON 仅追加 `management`，TSV 保持原形。list 采用只读组合，不触发 pending management recovery。fenced B 列表从当前 B Desired、Source 与 Retirement Owner 组合；无可信 Instance/Package 快照的维度明确为 `unknown`，不推断运行中状态。
- P1 的 Product-owned 外部 Source 采集在 fenced epoch 内固定本地 wheel 字节、digest、受控私有路径及来源 provenance。已验证候选只接受一个 `resource.skill` 文档声明和无 actions 的 `SKILL.md`，拒绝额外执行成员与依赖。拒绝清理失败沿现有 Package cleanup journal 记债。
- Coding 已 fenced CLI 的 install/update 使用 A2 Product 路由；enable/disable/absent 使用 A1 管理命令；list 为一次性 B 只读查询。更新交给既有 staged update、前任 revision CAS 和 retention handoff，并在相同 GC 引用门闩下从 Package 路由持续保护到 Desired commit。CLI 失败返回可定位的 Package operation id；发布前失败和 cleanup 证据仍由 Package Owner 持有，不伪装成 A1 操作。
- 新 Session 将已启用的本地数据 Skill 与 `coding.base` 放在同一 Product 编排中，使用已选 Store 的精确 Resource body。内置 Capability 插件启用与停用两种分支都覆盖；旧 Session 保有其已捕获的 revision，新 Session 选取更新 revision，Catalog refresh 对选择变化要求重启。
- 针对性测试覆盖真实 cutover/CLI/Session 命令链、pending 只读列表、恶意及畸形 wheel、Source 丢失、cleanup 债务、更新代际及 retention handoff 中断恢复。实现评审和合并后验证结果另记于交付记录。

## 三视角评审记录（2026-09-26）

| 视角 | 初审阻断 | 收敛结果 |
| --- | --- | --- |
| 架构与 Owner | pre-B/B 管理绑定混用、A1/A2 职责合并、install-only 路径被误写为支持更新、A1 无法覆盖发布前失败。 | 明确 P0 只读组合、P1 fenced B 绑定、A2 安装与 A1 Desired 分工、P1b 更新接缝和独立 Package 证据；复核无剩余阻断。 |
| 安全与恢复 | 查询启动会写入、现有投影漏掉隔离清理债务、数据型声明缺准入约束，且初次修订曾在 PLC9B 验证前解析 wheel。 | list 查询与恢复分离；数据 wheel 白名单在 PLC9B 已验证候选上检查；Source 授权仅安全采集，失败不回落 legacy；复核无剩余阻断。 |
| 产品与作者体验 | fresh B 无法走旧 CLI 绑定；外部 wheel 缺 Product Source 路径与用户命令；现有 flags 的 scope/移除语义不符。 | 受控 Source root、受限文件名/布局、B 专用命令映射及 `project` scope 明确；真实命令链成为验收条件；复核无剩余阻断。 |

评审只确认上述设计中的增量接缝与验收边界，未评审实现代码，也未扩大到其他插件类型或默认模式切换。

## 三视角实现复核（2026-09-26）

评审范围限于本纵切，三位独立评审使用 `gpt-6-astra xhigh`。发现与修复如下；三视角复核均无剩余阻断：

| 视角 | 复现的问题 | 有界修复 |
| --- | --- | --- |
| 架构与 Owner | 中断更新在另一更新完成后恢复会回退 Desired；同一应用缓存的 Product policy 漏掉新 Source；已拒绝的旧 handoff 可能阻断后续启动。 | 更新接受前在既有 GC binding Owner 持久绑定前任和 inventory revision，handoff 使用原 CAS；新 Session 重捕获外部 Source policy 并保留旧 Session owner；启动恢复承认经过精确验证的 `aborted` 终态。 |
| 安全与恢复 | 深层 JSON 抛出裸 `RecursionError`，使 A2 操作停在 active；管理 list 对残缺日志尾部执行修复写入。 | 严格 JSON 解码转为有限诊断并走候选终态拒绝；legacy 与 fenced B 查询 Owner 使用只读、遇残缺尾部报错的加载策略，完整 CLI list 在运行时准备前返回。 |
| 产品与作者体验 | 数据 wheel 曾可声明 managed actions；准入总量高于新 Session 捕获上限，导致可安装但不可使用。 | 准入要求空 reservation configuration、仅 `SKILL.md`，并把已验证文件树总量限定在同一 1 MiB 预算内。 |

回归采用真实 cutover、CLI、Session 和中断恢复路径；没有扩展默认模式、其他作者类型或远端安装。

## 合并前验证（2026-09-26）

- 外部 wheel、管理端口、严格 JSON、PLC9A2/B Product 与 handoff、列表合同：`130 passed, 5 skipped`（保留 `not live` 与 host-runtime 排除）。
- 最终更新前任与应用缓存回归：`2 passed`；真实 legacy CLI 列表：`3 passed`。
- PLC9 架构合同批量验证：`226 passed`，两项源码清单因新增的显式入口和 Product 只读适配发生增量；核对边界后更新清单，两项聚焦重跑 `2 passed`。
- Ruff、所改核心文件的 mypy、`git diff --check` 通过。旧 Wave A 静态行数预算在未改动的 `main` 上已失败（`41274 > 39041`），未借本纵切提高预算阈值。
