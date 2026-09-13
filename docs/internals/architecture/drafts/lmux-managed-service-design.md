# lmux：命名多 Tab 与自动后台服务设计

[Drafts](README.md) · [AppHost](../apphost/README.md) ·
[G16 Local Deployment](../appserver/detachable-local-workspace-g16.md) ·
[Named Mux Proposal](harnesstui-named-mux-daemon-attach-design.md) ·
[Machine-Local Storage](../harness/machine-local-runtime-storage.md)

## Status

- ID: `LMUX-DP-MANAGED-SERVICE`
- Scope: Coding entry / AppHost deployment / Hosting service mechanism / Harnesstui
- Authority: proposed target; does not override accepted sibling contracts
- Design status: proposed
- Review status: base and shared-client/Harnesstui reuse revision both passed
  three-perspective re-review as M0 design input, 2026-09-13
- Implementation status: partial; M0 values and M1 private-file owner only, no activation
- Owner: Loushang application architecture
- Delivery objective: active local Linux lmux baseline; implementation tracked by LMUX-M0

本文收口短入口、全局命名、工作区隔离、默认目录和 SSH 重连讨论。
按架构方法区分 Facts、Target 与 Delta；并非新建一个顶层 `loushang.lmux`
子系统，也不宣称现有命令已经支持自动后台启动。最初设计阶段为 docs-only；
后续合同准入与代码切片见 [M0 交付审计](../apphost/lmux-contract-m0.md)，
本草案不替代其中更具体的已接受合同，不代表已发布。

## 1. 问题、目标与非目标

用户应能创建一个具名、多会话的终端工作界面，断开 SSH 后从任意目录
重新进入，而不需要记住连接目录、端点、应用 ID、会话根和后台 PID。

核心不变量：

1. 名字定位 Mux，不定位工作区或服务进程；一个 Mux 包含多个 Tab。
2. 连接入口全局可见，执行与配置按服务绑定的工作区隔离。
3. 客户端断开不等于应用停止；已接纳执行由应用持有。
4. 服务实例、应用恢复状态、会话数据、客户端草稿是四种不同寿命。
5. 方便启动不得绕过权限、认证、独占写入、版本或清理 fence。

第一版以 Linux 本机用户为范围，连接只走现有认证本地通道；SSH 只是
用户进入该机器的方式，不增加 SSH/网络代理协议。不是 shell/PTY 通用复用器，
不提供任意进程重启恢复、机器重启后自动运行、热升级、跨用户共享、跨工作区
Tab、跨 Product Mux、读写多控制器或自动重放工具调用。macOS/Windows 的
现有显式入口不受影响；自动后台 profile 必须各自验收后才开启。

本机 GUI 是公共发现/连接能力的另一个预期消费者，不是 lmux CLI 的调用者。
本轮明确可接入合同和无 UI 客户端验证；完整 GUI 界面与远程 GUI 传输仍不在
第一版交付范围，不把“可复用接口”写成“已有 GUI 接入”。

## 2. Current：已有事实与必须补齐的缺口

| 事实 | 代码或合同依据 | 对本设计的约束 |
| --- | --- | --- |
| 显式 `loushang-mux serve/list/create/attach/close/stop` | `src/loushang/coding/cli/mux.py` | 当前不发现、不自动启动服务；stop 回复是 requested，不是退出证明 |
| G16 应用拥有执行，客户端 EOF 不停止应用 | `src/loushang/apphost/local.py`、`src/loushang/appservice/client_scope.py` | 复用此生命周期，不使用 G14 EOF-terminal profile |
| G13 持久协调记录和应用独占 lease | `src/loushang/apphost/continuity.py` | Mux 成员真相继续由 AppService/G13 管理 |
| 多成员、控制器、切换与终端 shell 已存在 | `src/loushang/harnesstui/mux/` | Tab 是成员视图，不是额外进程 |
| Hosted screen 复用共享会话组件，但未注入 transcript theme | `src/loushang/harnesstui/mux/_shell_screen.py`、`src/loushang/tui/transcript.py` | 当前助手消息走纯文本回退，不能声称已与普通 TUI Markdown 等价 |
| 前台客户端拥有子进程 | `src/loushang/coding/cli/hosted_client.py` | 不可把 A0.5 改名为 daemon 并忽略 close |
| 纯路径根解析 | `src/loushang/foundation/platform_paths.py` | 一次解析后注入，不让叶子重新读 home/cwd/env |
| 普通 Coding 默认全局会话根、cwd 筛选 | `src/loushang/coding/cli/multiagent.py`、Machine-Local Storage | `.loushang/sessions` 是兼容发现，不重新作为默认写根 |
| G16 launch 要求 application/cwd/home 三个根互异且不嵌套 | `src/loushang/coding/hosted_bootstrap.py` | 不能把同一默认会话根直接填两遍；必须先设计 scope/catalog 适配 |
| Hosting 通用服务控制仍是候选，M0 已接受有限 Linux managed Target | [Hosted Application Support Boundary](../hosting/key-designs/hosted-application-support-boundary.md) | Linux 自动后台仍待实现与验收，不能把合同准入当作已实现 |

手工 Linux 验证已观察到 ready、新会话、真实模型回复、detach/reattach 和
显式 stop 后服务返回 Shell。它不是 SSH 异常断连、自动后台、机器重启或
性能验收证据。另有 `request_pending` 状态残留和退出终端残留待专项修复。

## 3. 术语与身份

```text
本机用户 + LOUSHANG_HOME（一个命名空间）
  Mux 名称索引：dev ───────────────┐
                                  v
  服务 A（coding、workspace A、profile）
    Mux dev：Tab 1 → Session X；Tab 2 → Session Y
    Mux review：Tab 1 → Session Z
  服务 B（coding、workspace B、profile）
    Mux docs：Tab 1 → Session W
```

- Mux 名 `dev` 在该本机用户命名空间内唯一，离线时也保留，不使用 `dev:main`。
  第一版名字为 1–64 字符 ASCII `[A-Za-z0-9][A-Za-z0-9_-]*`，区分大小写；
  名称不直接拼文件路径，存储键是摘要或生成 ID。
- Mux ID 是 AppService 身份。全局索引只存名称到 service ID / Mux ID 的引用，
  不复制成员列表、会话正文或执行状态。
- 默认服务复用键为规范化工作区绝对路径 + Product ID + deployment profile，
  在用户命名空间内唯一。不自动上溯 Git 根，不因 attach 的 cwd 改变工作区。
- service ID 为机器本地稳定 ID，instance ID 为每次启动新随机值；重启不换
  服务 ID，但必须换实例与认证材料。可选服务别名用于管理，不是日常 attach 目标。
- 相同工作区的多个 Mux 共用服务。第一版拒绝同工作区/相同 profile 的额外
  服务实例；可在不同工作区新建多个服务。独立配置实例以后显式扩展。
- 同一 Mux 的所有 Session 必须匹配服务工作区与 Product。全局发现会话不
  赋予跨工作区执行权限。第一版同一 Session 只允许一个活跃宿主写入。
- Tab 的选中位置属于客户端；服务持久保存成员顺序，不保存全局选中 Tab。
  一个 Mux 同时只允许一个控制器；已有控制器时第二次 attach 明确返回 busy，
  不抢占。断连释放旧代 authority 后才接纳新控制器。

## 4. 用户命令合同（Target，非当前命令帮助）

| 命令 | 行为 | 是否启动服务 |
| --- | --- | --- |
| `lmux` | 有 Mux 时显示全局选择器；无 Mux 时在 cwd 创建默认 Mux `main` 并进入 | 仅显式选择新建或第一次无目标时 |
| `lmux new -s dev` | 全局保留名称，在 cwd 对应服务创建空 Mux 并 attach；Tab 显式 `/new cwd [标题]` 创建 | 必要时启动/复用 |
| `lmux new -s docs --workspace ~/docs` | 同上，显式工作区 | 必要时 |
| `lmux attach -t dev` | 任意目录连接该名字；离线时提示 start，不隐式重启 | 否 |
| `lmux ls` | 全局名称、工作区、服务、Tab 数、可验证状态；离线字段标记 cached/unknown | 否 |
| `lmux start -t dev` | 显式重启所属服务，恢复该服务的全部持久 Mux；说明影响范围 | 是 |
| `lmux close -t dev` | 确认后关闭该 Mux 与其活跃成员，保留 Session 历史 | 否 |
| `lmux server start --name build --workspace ~/build` | 高级：显式创建/复用服务，不强制创建 Mux | 是 |
| `lmux stop --server build` | 请求并等待这个服务退出；显示受影响全部 Mux | 否 |
| `lmux stop --all` | 当前机器/用户/LOUSHANG_HOME 的已登记服务，冻结目标列表后确认 | 否 |
| `lmux status [--server build]` / `lmux logs --server build` | 诊断、实际路径、版本、受限日志读取 | 否 |

`attach` 无 `-t`：唯一在线 Mux 直接进入，否则交互选择。所有进入终端的命令
（裸 `lmux`、`new`、有/无目标的 `attach`）必须在任何写入/占名/spawn/连接
IO 前检查 stdin/stdout TTY；非 TTY 直接拒绝，不会因为有 `-t` 就绕过。
本版不提供 detached new；`start`/`server start`/`status`/`ls` 可脚本调用。
`new` 同名报冲突，不静默 attach/覆盖。服务别名重名
也拒绝；`stop --server` 可接受 status 输出的精确 service ID。

无目标 `stop` 报需要目标，不根据 cwd 猜测，更不全停。`close`/`stop` 交互
确认，非交互必须 `--yes`。`--yes` 不允许绕过 busy/fence 或强制杀进程。
第一版不提供隐式 force/kill。离线 `close` 不假装已执行 AppService close：
提示先 start 后 close；历史名称不会因超时或宕机自动释放。

用户使用 `lmux`；保留 `loushang-mux` 原有显式语法和参数兼容，新旧入口共用
内部 client/bootstrap，而非两套 runtime。旧入口手工部署不自动登记为受管服务，
其服务内名称不冒充全局 lmux 名；导入/接管不在第一版范围。

空 Mux 显示服务绑定的工作区及可直接执行的 `/new cwd [标题]`、
`/new user_home [标题]` 和 `/resume`，不把裸 `/new` 当现有有效语法。
新 scope adapter 下两者仍共用 Session 权威存储；区别是显式选择/发现语义，
不改变服务工作区。后台入口不得等待 stdin 配置模型/凭证或弹信任确认。
服务级前提缺失则启动失败并给安全诊断；仅会话级前提缺失则保留空 Mux，
首次 Tab 创建明确报错，提示通过现有配置入口完成准备后显式重试。

## 5. 默认目录与配置边界

采用用户提出的管理文件集中方案，根为 `$LOUSHANG_HOME/lmux`，默认
`~/.loushang/lmux`，不是项目 `.loushang/lmux`。机器本地子键 `<machine>`
区分共享 home 中不同机器；从安全本地身份解析器注入，不用 hostname 充当
进程权限。共享文件系统上的可靠锁与身份不满足时拒绝自动启动，不降级无锁。

```text
~/.loushang/lmux/
  machines/<machine>/
    registry/                     # 有界服务描述、名称引用与未完成操作意图
    lifecycle/                    # 每服务稳定 fence/lock，不在 release 时 unlink
    servers/<service-id>/
      descriptor.json             # 版本、工作区、profile；不含密钥/完整环境
      state/application/          # G13 应用协调与 lease
      state/control/              # 机制操作意图、最后观察；不证明当前存活
      logs/                       # 有界日志与显式 trace
      tmp/<instance-id>/          # 可丢弃且有 owner lease 的暂存
    cache/                        # 需要时才创建，不复制现有插件缓存

<PlatformPaths.runtime>/lmux/<namespace-key>/<service-id>/
  connection/                     # 现有 AppServer 私有连接记录与认证材料
  control/                        # 唯一当前实例机制 authority 与启动协调

<现有 Session 权威根>/             # 历史、持久附件；不迁移到 lmux
```

namespace key 绑定用户身份和规范化 LOUSHANG_HOME，避免同一 runtime 下
两个隔离 home 冲突。临时目录显式设置 `LOUSHANG_TMPDIR` 时优先落到该根下
`lmux/<namespace-key>/<service-id>/<instance-id>`；否则使用上面的集中 tmp。
`LOUSHANG_RUNTIME_DIR` 仍有效。路径覆盖冲突、不同服务重用同一控制目录、
连接目录与持久根交叠、符号链接替换或不安全所有者必须在启动前拒绝。

Hosting 机制 owner 同时维护两种不同记录：durable control 仅存操作意图、
已完成交接的历史和最后观察，runtime control 是当前实例机制 authority。
AppServer 独立拥有 connection 认证记录，不把它复制进 durable control。
runtime 丢失时进入 unknown，历史 PID/epoch 或 durable 副本不能证明进程
死亡、授权重建凭据或另起实例；必须由精确身份探测/显式维护完成协调。

跨启动互斥使用 AppHost 部署协调器拥有的持久 `lifecycle/<service-id>` fence，
其锁文件身份稳定，不因 release、runtime 丢失或换根而 unlink/recreate。
runtime 保存当前可达性/机制证据，持久 fence 决定是否允许新代启动，二者
不互相冒充。换 runtime 覆盖值仍须取得同一持久 fence；若旧实例可能存活
但不能认证，报告 `instance_unreachable`，保留名称和状态，拒绝自动启动。
这不是可由 age/PID 判断绕过的锁。精确维护能力未提供时，只报告人工处理，
不暗中 kill 或删除；不同 runtime 根不能成为重复启动同一服务的后门。

这是相对现有 Machine-Local Storage 的**局部目标变更**：lmux 管理文件集中，
内部仍按 lifetime 分层；不修改 Foundation 全局 data/state/cache/tmp 缺省。
实施前需要在该决策及 Hosting consumer storage 合同显式接纳此布局；本文
不把 `$LOUSHANG_HOME/lmux` 谎称为已被接受的 `PlatformPaths.state`。

Session 遵循现有可信配置覆盖与默认 `$LOUSHANG_HOME/data/sessions`：cwd 和
user-home 是发现/选择 scope，不是两份默认写库。旧项目会话目录只做兼容发现；
恢复与迁移继续由 Product owner 执行。新 scope/catalog adapter 必须保留规范
Session 身份、过滤、准入与独占写入；不可简单删除 G16 三根校验绕过边界。
同一全局会话被多个工作区服务或 embedded CLI 请求时，跨进程独占写入是
启用共享默认存储的硬门禁，未证明支持时拒绝第二个打开者。

第一版目标包含同工作区既有普通 Coding 会话，但发现不等于可直接 hosted
resume：当前 `coding.hosted_catalog` 还要求 `coding.hosted` 元数据与 scope
fingerprint。[M0 合同](../apphost/lmux-contract-m0.md) 选择 Product-owned
非破坏性 view adapter：发现只读投影，实际打开先取得跨进程写入权并重验，
保留规范 Session ID/正文/附件引用；普通历史无需补写 hosted header，已有
v1 hosted 身份通过原校验后保留。它替代此前“转换/补齐元数据”的实施手段，
不改变支持普通历史的目标，不修改工作区来迎合服务。未通过适配或不兼容的候选在 picker 明确禁用并
说明原因，不能删除校验强行打开。该适配未交付前不得宣称普通历史已可恢复。

配置仍由 Product 使用现有全局/项目可信规则解析；lmux 不再新建配置文件体系。
服务描述只记录获准绑定事实，不允许 registry 任意路径/argv/env 直接变成
执行授权。启动使用当前可信安装入口；安装版本变化与当前服务不兼容则拒绝
复用并要求显式停服升级。attach 不把客户端当前目录配置灌进旧服务。
服务启动环境是快照；新会话的配置刷新只走既有 Product 规则，不宣称自动热载入。

私有目录 `0700`、文件 `0600`，Windows 用等价受限 ACL 后验收。
已提交图片使用既有 Session 附件策略；客户端尚未发送的草稿/粘贴图不是
持久会话，SSH 断线可能丢失。当前 Hosted shell 图片粘贴未支持，不能随本设计
宣称已支持；服务不会为了保存图片接管客户端临时目录。

### 日志、trace 与清理

默认只记录脱敏生命周期/错误码/实例身份，不记录提示词、回复、工具正文、
token 或原始环境。必须区分结构化安全日志与第三方原始 stderr：原始输出
默认不能直接落盘；边界做限长和脱敏，不能保证安全的正文丢弃并记录计数。
详细 trace 显式开启、有期限；不因此允许记录认证材料。

建议首版可配置上限：普通日志每服务合计 50 MiB（单份 10 MiB，含当前共 5 份），
trace 每服务 20 MiB，全部受管服务日志总计 200 MiB；跨重启仍共享额度。
暂存每实例 128 MiB、命名空间总计 512 MiB；超额拒绝新暂存，不删活跃文件。
满盘时不得把“日志写入成功”作为执行/清理前提；启动必要状态写入失败必须
失败关闭，现有服务维持可达的停止路径。日志失败显示有界警告，禁止递归刷日志。

清理只由对应存储 owner 执行，必须检查 lease、实例、所有者和文件身份，
锁住后隔离再删除，不跟随符号链接；只凭时间、PID 或目录名字不能删除。
未知/旧格式残留只报告，不自动回收。永远不把 Session 根纳入 lmux gc。
活跃日志通过写入 owner 轮转/限流，汇总清理不得直接截断其他实例的打开文件。

全局 200 MiB 包含普通日志与 trace。命名空间额度协调由 AppHost consumer
侧存储管理组件负责（不由 Hosting/日志叶子自行推导），锁下写入前预留有界
额度，实际落盘后结算，跨进程并发不能各自读余额后独立写满；可按小块预留
减少争用，但未使用预留也计入总额。崩溃重启对账只回收确认为失效实例的
预留，不把未知实例配额释放给新进程。无需新增常驻 broker。
初始 registry 上限拟为 128 个服务、4096 个 Mux 名/意图、单记录 16 KiB，
含事务 journal 总计 80 MiB；已停止服务和 pending 也计入。满额拒绝新建，
停止与完成既有意图使用预留控制空间，不能靠删除未知 pending 腾出名字。

## 6. 核心组件与边界

| 组件 | 所属 | 拥有 | 不拥有 |
| --- | --- | --- | --- |
| Product entry/composition | Coding | CLI 语法、路径策略、可信安装/Product/workspace 绑定 | 通用进程控制实现、会话真相 |
| Managed deployment coordinator | AppHost 可选部署边 | 用户级服务发现、名称路由、协调意图、启动/复用编排 | Session 执行实现、终端渲染、OS 细节 |
| Service instance mechanism | Hosting 新的受限候选组件 | 脱离终端、精确实例证据、进程启动/退出观察、机制 lease | Mux 名称/列表、认证协议、日志保留、Product 配置 |
| Local connection | AppServer | 本地认证、record、协议、连接与背压 | 创建后台进程、发现全局工作区 |
| Application owner | AppHost/G13/G16 | 应用创建/恢复、admission、依赖顺序关闭和 lease-last | UI 生命周期、Session 内容复制 |
| Mux/Session coordination | AppService | Mux 成员、控制器、已接纳执行的生命周期 | OS 后台化、用户 home 推导 |
| Session/storage/policy | Product/Harness | 会话、资源、权限、工具和持久附件 | 用户级服务目录索引 |
| Client shell | Harnesstui/TUI | Tab、输入、选择器、状态、终端进入与恢复 | 服务 stop、全局 registry 写入 |

CLI 将管理操作交给 AppHost 可选编排边；后者消费 Hosting 机制，调用 AppServer
client，或组合 AppService。Hosting 不导入 AppHost/AppServer/AppService；
AppServer 不导入 Hosting。全局 registry 不需要一个额外常驻 broker。
UI 内创建/关闭 Mux 若影响全局名字，必须走同一管理编排入口；不能留下绕过
全局保留的写路径。普通 Tab 创建仍走 AppService，不触碰全局名字。

此限制必须在**受管服务端**强制，而不是仅靠新 CLI 约定。managed profile
的 create/close Mux 只接受与名称保留和 operation ID 绑定的管理 authority，
现有不携带该 authority 的 legacy mutation 返回明确的 profile/upgrade 错误。
即使用户用旧 `loushang-mux` 显式指定受管 connection root，也不能绕开索引。
原有手工 G16 profile 不激活此限制，兼容语义保持不变。

### 6.1 公共发现与连接协调：终端和本机 GUI 共用

公共合同由 AppHost 的可选部署边提供，AppServer 继续拥有认证连接与协议；
不建 `lmux` 专属后端 API，不让 GUI 导入 `coding.cli` 或 Harnesstui，不通过
执行 lmux 命令和解析 stdout 连接服务。具体 GUI 产品组合入口注入可信
Product/工作区/路径策略，GUI 组件只消费通用端口。Hosting 不因此依赖 GUI。

公共操作面（逻辑职责，M0 冻结版本化类型与错误，不是已存在的 Python API）：

| 操作面 | 输入/结果 | 副作用与权限 |
| --- | --- | --- |
| Discover / Resolve | 不可变命名空间绑定、可选 Mux 名；返回有界摘要和 opaque target reference | 只读；不启动、不回收、不把 PID/缓存状态当 authority |
| EnsureStarted / Reconcile | 显式启动意图、可信 deployment binding / operation reference | 唯一协调器执行；GUI 打开选择器不等于授权启动 |
| PrepareConnection | opaque target reference；返回受限且实例绑定的连接 lease | 重新认证/校验，stale reference 不自动 retarget；无终端依赖 |
| ManagedCreate / ManagedClose / Stop | 精确目标、确认后的操作意图、operation ID | 走同一服务端管理 admission 与生命周期 fence，无 GUI 特权路径 |

只读摘要可展示名称、工作区、Product、profile、兼容版本与有时效的状态，
不得暴露原始认证密钥、内部记录路径或可执行 argv。受限连接 lease 内部保留
必要凭据，展示层不接触；引用仅是定位信息，不能扩大权限或绕过重新准入。
取消发现或连接只清理本次读/连接 owner，不停止已存在或已交接的服务；
创建或启动丢回复仍返回可对账 operation，不由 GUI 自动重试 mutation。

TTY 检查属于 lmux 的交互入口，不属于公共服务 API；无终端的 GUI 可正常
调用这些端口。GUI 不直接读写 registry/descriptor，也不复制目录算法。
`~/.loushang/lmux/` 是此受管 deployment profile 的存储布局，不代表 TUI
所有权；TUI 与 GUI 通过注入的同一 namespace binding 找到同一服务，不因
GUI 接入搬迁目录、创建另一套索引或另起 Session。该路径不强制成为所有
未来 Hosted profile 的全局缺省。

一个 Mux 仍只有一个控制器：终端持有时 GUI attach 返回 busy；终端 detach
完成、旧代 authority 撤销后 GUI 可取得新代，反向同理。不同 Mux 可分别
连接。只接管成员和会话状态，不承诺转移客户端未发送草稿、选中 Tab、
旧审批 token 或未确认请求。GUI 关闭/断连也不隐式 stop。
浏览器 GUI、远端桌面 GUI 与 SSH 隧道需要独立传输/认证边界，本文不扩展。

### 6.2 Mux 的会话渲染：复用，但不混淆 Current 与 Target

Current 调用链：`HostedMuxScreenV1` 继承 `ScreenConversationApp`，
`project_active_conversation` 把 ASSISTANT 记录/流式草稿投影到共享会话状态，
最终交给 TUI transcript 组件。渲染不在后台服务执行，协议不传终端 ANSI
作为会话真相；控制字符净化作用于客户端显示副本。

但当前 Hosted screen 构造没有传 `transcript_theme`，共享默认值为 None；
`src/loushang/tui/transcript.py` 中助手记录仅在 theme 非空时调用 Markdown
渲染，否则是带 `* ` 前缀的纯文本。因此“复用组件”不等于当前已经启用完整
Markdown。底层 Markdown renderer 已支持 CommonMark 与 table/strikethrough，
应复用其现有能力，不新建 Mux Markdown 解析器。

Target：M3 在客户端组合边注入共享主题和终端能力，接通已有 Markdown
渲染与流式路径，保留标题、列表、强调、引用、代码块和表格等共享能力；
颜色/代码高亮按实际终端能力降级，不将不支持颜色等同于丢掉 Markdown
结构。不同 Tab、重连 snapshot、未闭合代码围栏和窗口缩放需防止串缓存、
错位或重复输出。GUI 独立渲染相同语义内容，不复用终端组件或接收终端样式。

能力边界：当前 Hosted transcript 协议的记录种类只有 USER/ASSISTANT/
STATUS/ERROR，不能凭共享组件宣称已支持工具富卡片/diff 等完整结构化展示；
现有 Hosted 图片粘贴也明确 unavailable。工具结构化投影、图片、全部普通
Coding 命令与 UI 扩展的等价性需要另列协议/交互增量，不搭本轮自动后台
顺带承诺。本轮只增加 M3 Markdown 接线与不回退要求，不修改渲染代码。

### 6.3 复用单元：完整 Harnesstui 会话视图，不只是 TUI 控件

Target 明确为：**一个共享会话视图，两种会话接入方式，一个可选 Mux 外壳。**
“完整视图”指共享的展示与交互实现，不表示 Hosted 已有 Embedded 的全部
数据/操作能力。不能仅因继承同一个 Screen 类就宣告功能等价。

```text
Embedded 产品外壳                 Hosted Mux 外壳
  单会话入口/产品退出               Tab/切换/新建关闭成员/attach/detach
            \                       /
             Harnesstui 共享会话视图
          消息/Markdown/输入/操作状态/能力可用时的工具与审批展示
                       |
             TUI 布局、主题、控件、终端渲染

会话视图需要的中性端口 ← Embedded binding ← 本进程 Product
会话视图需要的中性端口 ← Hosted binding   ← AppClient / AppServer
```

该图不是把本地 Product 经远程协议传回 UI，也不新增顶层包。共享单元位于
`harnesstui.conversation`，Mux 外壳位于 `harnesstui.mux`；在现有
`ScreenConversationApp`、projection、action presentation 上渐进提炼组合
端口，不复制整套 Hosted composer/transcript/approval 逻辑，也不大改 Embedded。
现有 `conversation.agent_binding` 是可选的本地 Agent 适配，并非 Hosted 可直接
复用的纯中性实现；Hosted 不为获得某个组件而引入 live Agent/Product 对象。

| 层 | 唯一职责 | 明确排除 |
| --- | --- | --- |
| 共享会话视图与交互 presenter | 记录/流式草稿/输入/历史视窗/详情/错误与 pending 显示；能力驱动的操作入口 | 服务发现、RPC 重试、Session 创建、权限决策、进程或应用关闭 |
| Embedded binding | 本地事件转为中性视图输入，用户 intent 映射到 Product 的受限操作端口 | 在共享视图注入完整 Session/工具执行器；改变原有退出/清理合同 |
| Hosted binding | snapshot/event/cursor 投影、动作请求和结果协调、连接/controller 代际隔离 | 通过本地 Product 补远端能力；合成不存在的工具事件；丢回复自动重发 |
| Mux 外壳 | 名称/成员切换、窗口级绑定选择、新建/恢复/关闭成员、连接提示与 detach | 另一套消息 renderer；持有服务关闭权作为 view.dispose 的副作用 |
| 客户端组合/终端 owner | 主题/终端能力/键位/操作与生命周期端口注入；一个终端循环 | 每 Tab 创建终端会话/事件循环/后台服务；共享视图自行探测 cwd/home |

M0 须冻结的中性接缝（先复用现有结构，只有现有端口无法表达时才扩展）：

- **视图输入**：Session/member 身份、绑定 generation、不可变记录窗口、
  snapshot/cursor、流式草稿及权威运行状态；UI 不把渲染速度当作操作完成。
  它们是客户端 view model，不直接成为 wire schema；Hosted adapter 转换
  已校验的 AppServer 值，Embedded adapter 转换本地投影。
- **操作端口**：提交、steer、follow-up、interrupt、审批等有类型 intent 与结果。
  区分 submitting、accepted、running、completed、failed、unknown；不能套用
  本地“await 返回表示 turn 完成”的假设。执行状态与请求投递状态分别显示，
  `idle` 不足以把未知请求标为成功；terminal outcome 到达时按 operation/
  generation 清除对应 pending，不覆盖更新操作的状态。客户端 action owner
  必须保留既有总额上限与 interrupt/清理等控制操作的预留，不因多 Tab
  共用 presenter 放大每 Tab 独立队列到无界，也不能让普通提交饿死控制操作。
- **能力描述**：只读且随绑定代际失效的支持矩阵，区分可用、不可用、只读及
  原因；协议未提供的数据不能靠 UI 猜测。界面可用性不是授权，服务端仍须
  对每次请求检查 scope/controller/policy；旧能力快照不赋予旧 token 新权限。
- **呈现与交互 binding**：主题、文案、命令/补全来源、只读工具详情及审批
  呈现回执。Product 提供受限展示数据，不让共享视图调用本地工具或加载任意
  服务端可执行插件。Hosted 未协商的 Product 命令/图片入口明确禁用。
- **视图生命周期**：view.dispose 仅释放视图缓存、草稿、订阅/显示资源；
  detach/close-member/stop-app 是外壳不同的显式 intent，不能统一成一个
  模糊 close 回调。Embedded 产品退出仍由原 Product owner 结算；G16 detach
  不结算应用；现有 G17 前台 Hosted 的退出结束应用合同仍独立保留。

Tab 状态按 `(attachment generation, member ID, Session ID)` 隔离，保存
编辑草稿、历史锚点与有界渲染缓存；一个共享 renderer/view 可以重绑定当前
Tab，无需每 Tab 克隆整套 Screen/终端循环。切换前保存本地视图状态，切换后
恢复目标状态，晚到消息只更新匹配的后台成员，不能写到新 Tab 或复活已关闭
成员。重连以新 attachment 为边界，不自动搬移旧审批回执或未确认操作；草稿
迁移不在第一版保证中。缓存与订阅必须有总界限，关闭 Tab 完成后释放其资源。

输入路由只能有一个 owner：详情/选择器/补全等当前上下文优先，未消费的
Tab/Shift+Tab 才由 Mux 切换成员；Ctrl+B 前缀由外壳处理，普通文本与会话
intent 委派共享交互层。审批展示回执绑定 attachment ID、controller generation、
member ID、Session ID、interaction ID 与实际呈现内容，不能因另一个 Tab
曾打开详情就允许当前审批。输入焦点、
剪贴板暂存与终端恢复仍沿用各自 owner，不因视图复用扩大授权。

### 6.4 能力与交付范围，不把架构复用等同全功能迁移

| 能力 | 共享复用目标 | 本轮后续实施边界 |
| --- | --- | --- |
| 消息/Markdown/输入/流式显示/历史窗口 | 复用同一 Harnesstui 会话视图及 TUI renderer | M3 接线与回归，保留 Embedded 的既有行为 |
| Tab 切换/成员管理/连接与 detach | Mux 外壳组合视图 | 不进入单会话核心，不产生每 Tab 服务 |
| 运行状态/请求状态/interrupt/steer/follow-up | 共享呈现与 intent，binding 解释执行语义 | M3 覆盖已支持的 Hosted 操作，不修改旧协议含义 |
| 审批 | 能复用的详情/呈现组件统一；授权由各 binding/服务端处理 | 必须保留 G16 已呈现检查与旧 generation 撤销，不能为复用而削弱 |
| 工具富卡片/diff/用量/扩展详情 | 有中性数据时复用现有 Harnesstui presenter | 未覆盖 wire 字段的能力继续禁用；另立版本化协议增量 |
| 图片粘贴/全部 Product 命令与补全 | 用能力 binding 接入，不复制产品工作流 | Hosted 未支持项不随此设计自动启用；Embedded 不受其限制 |
| GUI | 公共发现/连接/应用语义可复用 | GUI 不依赖 Harnesstui 的终端视图，保持自己的呈现层 |

§6.3 的逻辑复用目标不要求 M3 同时迁移全部 Product 功能；先接通已有
Hosted 语义与共享 presentation/action 接缝，并逐项证明非回退。任何需要新
wire 语义、持久草稿或新授权合同的能力列入独立后续增量，不借“完整视图”
名义绕过既有 M0/协议评审门禁。

## 7. 启动、命名事务与恢复

启动状态：`absent → starting → ready → stopping → stopped`；失败可进入
`failed` 或 `cleanup_pending`。`starting`/`cleanup_pending` 不是可 attach 的 ready。

1. 只解析 CLI 必要模块，解析并准入不可变 deployment spec；检查私有根、
   用户/机器身份、Product、工作区、安装/协议版本与权限。
2. 全局名称锁下写入有界 pending 意图（operation ID、name、service ID），
   释放锁。名称保留必须排斥跨工作区同名创建。
3. start/stop/reconcile 共用 service key 的持久 lifecycle fence 与 epoch CAS，
   不只是 start 单飞。状态更新在短锁下完成，长等待释放物理锁但保留操作
   所有权/代际意图；锁顺序固定，禁止持有全局 registry 锁等待 ready/RPC/退出。
   stop 若遇到 starting，为该 attempt/epoch 登记停止意图，禁止其随后发布
   ready 或提交 create；服务与启动器均检查该 fence。竞争新 start 返回
   stopping/busy，不在同次调用中悄悄排队启动下一代。
4. 先认证探测已有实例，再判断是否启动。活跃 lease、认证失败、版本不兼容、
   状态未知都不是“旧垃圾”；禁止覆盖并另起进程。
5. Hosting 机制启动完整可信服务入口，脱离控制终端/SSH 进程组，stdin 关闭，
   输出接有界诊断 owner；不得遗留连接 SSH 管道的描述符。
6. service 自持有服务寿命的机制 owner；启动器仅持有此次启动尝试。
   用实例绑定的就绪握手完成交接，不能“泄漏一个前台 ProcessLease”来续命。
   **唯一提交点**是子端在持久 lifecycle fence 下，将匹配 attempt/instance
   的交接从 provisional CAS 为 committed（且无 stop 意图），提交事实必须
   可认证对账；其后才回父端 ack。子端提交前 EOF 自行收口，提交后 EOF
   不改变服务寿命。父端未收到 ack/超时只代表 unknown，查询该事实，不得
   以本地未见 ack 推断未提交或直接 kill。M0 冻结序列化/耐久握手细节。
7. ready 必须意味着认证通过、G13 恢复完成且 G16 accepting。随后按 operation
   ID 创建 Mux，确认真实 Mux ID 后 CAS 提交索引；完成后才 attach。最终
   返回成功前在同一生命周期序列复核 epoch/accepting/stop fence。若 stop
   先线性化则本次启动/创建不得报成功；若 create 先提交，随后 stop 必须
   将它纳入收口，不留下“没有被停止的新 Mux”。
8. RPC 丢回复时保留 pending/unknown，以认证查询对账，不盲目重发 create、
   close、start_turn。已有协议未提供足够对账信息时，新增版本化管理合同，
   不凭一个碰巧同名的 Mux 判断本次操作成功。

全局索引是路由引用，AppService 是成员真相。保留/提交/关闭采用可对账意图，
不得以两个不相关文件更新假装原子事务。索引写盘失败不得默默丢弃已创建 Mux；
启动恢复 pending 并只在证明确认未创建后释放名称。关闭只有 AppService
settlement 成功后才释放全局名称，旧 epoch 的响应不得覆盖新实例记录。
停服不释放名字；重启从原 G13 记录恢复所有 Mux，不重新生成一套身份。

每次启动共享一个单调 deadline（拟议默认 30 秒，允许显式配置），排队、
spawn、恢复、ready 均计入；每个步骤不得重新给满额。超时仅清理此次确切
拥有的未交接实例，不能终止已复用或已交接服务。清理另有共享的有界预算，
超时保留可诊断 owner/证据和 busy fence，不宣称成功且不释放名称重新开跑。
启动回滚的强制回收仅限持有精确 OS 实例权且 fence 下成功将 provisional
改为 aborting 的本次实例；CAS 失败/已 committed/状态未知均不得回收。
无可靠 OS 身份终止能力时保留债务，不退化成按 PID 发信号。

## 8. 断连、停止与恢复保证

- SSH EOF/断线只关闭该 AppClient scope；已接纳 turn 继续由应用持有。
  未确认接纳的请求显示 unknown，不自动重试。工具是否跨断连存活仍须受
  Product 生命周期保证约束，不承诺任意外部进程永久运行。
- 待审批交互遵循现有 scope/controller 撤销策略，不自动授权，也不把旧审批
  token 转交新控制器；可以取消当前交互/相关执行，这不等于停止整个服务。
- reattach 验证实例、profile、Mux/controller generation 后重新取得 snapshot
  与 cursor；Tab 列表和历史恢复不重放工具效果。
- SSH 断开续存的前提是 Linux 用户进程仍获系统保留。systemd 注销清理、
  runtime 目录回收、管理员终止、机器重启均可能使其不可用；不暗中启用
  linger、不修改用户服务配置。需要这些保证时另行设计 supervisor profile。
- `stop` 先 fence 新准入，再请求 G16 应用关闭，按依赖顺序收口，最后释放
  lease。首版用户 stop 为有界 graceful-only，超时不自动升级 terminate/kill；
  这是对 Hosting 候选默认 escalation 的显式 profile 裁剪，须 M0 单独接纳。
  启动失败且确切未交接实例的 rollback 回收与用户 stop 是不同 authority。
  客户端区分 stop_requested、stopping、stopped、cleanup_pending、exited_unclean。
  `process_exited` 和 `application_cleanup_completed` 是两个独立事实；
  必须同时具有精确实例退出证据与匹配实例的可信完整清理结算证明，才能打印
  stopped/返回 0。异常或强制退出、缺少结算证明，只能报告 exited_unclean/
  unknown 并保留诊断；PID/端口消失不足以授权杀进程或宣称清理成功。
  [M0](../apphost/lmux-contract-m0.md) 进一步把 native scope/后代/句柄结算
  单独列为第三项必要证据：精确 leader 退出仍不等于整个 scope 已回收。
- `stop --all` 仅作用确认时的实例快照，不追杀之后启动的新实例；逐个报告
  结果，任何失败给非零总退出状态。默认没有空闲自动停服；最后一个 Mux
  关闭后服务可以保持 ready，避免意外改变后台生命周期。
- 服务死亡后的 start 是当前安装重新准入的持久会话恢复，不是进程复活。
  历史配置不提供启动任意旧 executable 的授权；不兼容状态应拒绝并给出诊断。

## 9. 性能假设与验收场景

常驻服务可能省进程启动、模块导入和公共初始化，但每次新会话仍须权限/注册/
存储/上下文准备。这里不增加共享可变 Session、不删除安全扫描、不冻结新性能
百分比。复用既有 Linux 采集器分别采集冷启、新 Tab、暖 attach、SSH 重连、
长历史同步及首次命令/工具/补全；记录均值、分位数、样本数与首屏/ready 区别。
自动后台不是先显示首屏的替代品；早屏可编辑属于后续独立优化，不自动发送草稿。

实施验收矩阵：

| ID | 场景 | 必须证明 |
| --- | --- | --- |
| V1 | 并发两次 new 同名/不同名同工作区/不同工作区、旧入口直连受管端点 | 全局唯一、单服务单飞、无孤儿 Mux；legacy 名称 mutation 不能绕过管理 admission |
| V2 | reserve/spawn/ready/create/commit 各阶段崩溃或丢回复；交接 commit 后 ack 丢失 | 对账可收敛，不重复启动/创建/执行；unknown 不误杀 committed 实例 |
| V3 | SSH-like PTY 关闭与启动父进程死亡前/后交接，每个握手消息丢失或延迟 | 后台有精确 owner，已接纳任务续存，重连不重复执行 |
| V4 | 多 Tab、新控制器、旧 generation、pending approval | 成员正确、第二控制器 busy、旧授权不复活 |
| V5 | close/stop/stop all；stop 在 spawn 前、ready 后交接前、create/commit 中途 | 范围准确；无 ready-after-stop；退出不冒充清理；历史保留 |
| V6 | 两个 LOUSHANG_HOME、共享 home 两机器、runtime 活跃时删除/换根、不安全目录/符号链接 | 稳定持久 fence；不重复启动；命名隔离；无凭据泄露与越界删除 |
| V7 | cwd/user-home 同库、embedded/hosted 同 Session 竞争 | 规范身份与过滤、唯一写入者、旧根兼容、无静默迁移 |
| V8 | 满盘、并发日志/tmp 预留、重启保留用量、registry 满额、cleanup 超时、未知旧记录 | 全局有界、保持停止能力、活跃内容不被 gc |
| V9 | 真实安装、版本不兼容、不同 cwd attach、工作区已移动 | 重连不换工作区、不执行旧路径/配置、不隐式升级 |
| V10 | 暖新会话/连接性能、长历史、首次使用、终端退出 | 配对证据；无残留 pending/终端覆盖；不转移首次使用成本 |
| V11 | 无 TTY 的 lmux/new/attach、干净 home、无配置/凭证、首次空 Mux/Tab | 无 TTY 零副作用；后台不等待 stdin；空态命令可执行，失败明确 |
| V12 | 旧显式入口、旧客户端访问 managed profile、真实 wheel 双入口 | 旧帮助/参数/确认/JSON 与不自动启动语义兼容；managed mutation 不绕过 registry |
| V13 | 终端与无 UI 公共客户端交替 attach，同 Mux 并发 attach、stale reference、取消连接 | 无 coding.cli/Harnesstui/TTY 依赖；同 registry/服务；单控制器 busy；断连不 stop，不继承旧审批 |
| V14 | Mux Markdown 稳定消息/流式围栏/表格/窄屏/Tab 切换/重连 | 复用共享 renderer；主题与终端能力正确注入；无纯文本误回退、串缓存或重复输出 |
| V15 | 同一会话视图分别接 Embedded/Hosted binding，命令与能力缺失 | 同一 fixture 的呈现/intent 等价；Hosted 不持有本地 Product、不偷偷回退执行；Embedded 不被能力裁剪 |
| V16 | Tab 切换时流式/审批/操作回复晚到、补全占用 Tab、关闭/断连/前台退出 | generation 隔离；pending 按操作清理；审批不能串用；view.dispose 不等于 stop；缓存/订阅释放 |

现有证据只复用其已证明的范围：

| 现有测试 | 可复用 | 新增缺口 |
| --- | --- | --- |
| `tests/coding/test_mux_command.py` | 显式参数、TTY 前置拒绝、错误输出 | lmux 新语法及零副作用非 TTY 检查 |
| `tests/coding/test_mux_subprocess.py` | 显式服务 stdin EOF 后继续运行 | 真实进程组脱离、交接、父死与 SSH-like PTY 关闭 |
| `tests/coding/test_mux_terminal_process.py` | 真实 attach、建成员、detach | 全局跨 cwd 名称、自动后台、首次空态与终端残留 |
| `tests/coding/test_mux_installed_evidence.py` | 原有安装入口证据约束 | 真实隔离 wheel 同时安装/运行 lmux 与 loushang-mux |

source/editable 环境成功不能替代 installed wheel 验收；不以旧 EOF 测试
冒充 SSH 生命周期隔离或后台交接验证。

V13 使用无 UI 的独立客户端消费者验证公共合同，不要求本阶段实现 GUI；
完整 GUI 的“终端 detach → GUI attach → GUI detach → 终端重连”留给 GUI
接入时验收。V14 验证现有 Markdown 能力的接线，不作为完整工具/图片 UI
等价性的证据；静态架构测试需禁止公共发现/连接模块依赖终端/产品 CLI。

V15/V16 基于现有 Harnesstui projection/action、Hosted shell 与 fake-terminal
测试扩展：共享输入数据驱动同一 presenter，分别注入本地/远端适配器。
同时保留 G16 客户端断开继续与 G17 前台退出结束的相反生命周期回归；
不以把两者改成相同退出行为换取“统一实现”。缺失协议能力的测试应断言
明确不可用，而不是编造一份远端数据证明完整功能等价。

V3 必须使用真实 Linux 进程/PTY 隔离测试，测试清理只终止自身创建并验证身份的
进程组，不能全局 pkill。真实 SSH 可补手工证据，但不作为默认联网测试。
测试从首次就在 sandbox 外运行，保留 not-live 等选择器，限额 scratch 并清理。

## 10. Delta 与分步实施门禁

| 阶段 | 交付 | 进入下一阶段的条件 |
| --- | --- | --- |
| M0 合同 | 接纳局部存储变更；Hosting service context/requirements/组件发现；Session scope/跨进程写入适配设计；公共发现/连接、管理对账、Harnesstui 双 binding 接缝与能力合同 | 三视角设计无阻塞项；不得只删旧校验 |
| M1 发现与路径 | `lmux` 短入口、UI 无关公共端口、私有布局、用户级索引、全局唯一名称、只读 status/ls、兼容旧入口 | V1/V2/V6 的静态与确定性测试；V13 接口/依赖边界 |
| M2 Linux 后台 | service mechanism、单飞启动、交接、ready/stop、失败证据与诊断限额 | V2/V3/V5/V8，无 PID-only 杀进程 |
| M3 会话与交互 | scope 适配和独占写入、全局 new/attach/close、共享 Harnesstui 会话视图双 binding、Mux 外壳、Markdown 接线、终端问题收口 | V4/V7/V9/V11–V16，全局名字写路径受控；Embedded/Hosted 各自非回退 |
| M4 交付 | 安装环境测试、SSH 手工脚本、性能采集、实现三视角复审 | Linux 全矩阵通过；macOS/Windows 自动后台仍显式未验收 |

M1–M3 中间能力保持 explicit/default-dark，不用尚未通过 V7 的默认共享库启动
真实会话。实施前按高风险工作流建立追踪目标和独立任务分支、测基线；本轮仅
文档设计，不创建远端 issue、不提交/推送，不把设计评审当运行验证。

## 11. 设计评审记录

2026-09-13：三位独立子 agent 先审初稿，主 agent 修订，再由原 reviewer
复核当时修订全文。该基线三视角均通过，无剩余 P1/P2 阻塞项。通过仅表示本方案可作为
后续 M0 设计输入，不代表 Hosting service、局部存储变更或默认 Session
scope 适配已经被接受/实现。Design status 保持 proposed，M0 仍需独立接纳。

| Reviewer / 视角 | 初轮发现与修复位置 | 复审结论 |
| --- | --- | --- |
| `lmux_arch_review` / 架构边界 | §6 服务端封闭 legacy mutation；§5 control 单一权威分工；普通 Coding transcript 受控适配与稳定身份 | 通过，无新增阻塞项 |
| `lmux_lifecycle_review` / 生命周期与安全 | §7 start/stop/reconcile 线性化、子端交接 commit/丢 ack；§8 graceful-only 与退出/结算双证据；§5 runtime 丢失仍保留 fence、跨进程配额 | 通过，原 3 项 P1、2 项 P2 在设计层闭合 |
| `lmux_ux_review` / 交互、兼容与验收 | §6 legacy 直连负测；§4 非 TTY 零副作用、完整空态命令；§9 V11/V12、旧证据到新缺口映射与 wheel 双入口 | 通过，原 1 项 P1、3 项 P2 在设计层闭合 |

验证：本轮相对 HEAD 的 change-aware plan 仅选 docs；文档轻量门禁 6 项
通过，本文相对链接与引用的 source/test 路径存在性检查通过，`git diff --check`
通过。没有运行 Product/runtime/性能测试，reviewer 结论均为只读设计评审。
原有性能分支已提交内容不属于本次改动，不因本轮文档重复执行其已通过门禁。

### GUI 公共能力与 Harnesstui 完整视图复用复审

同日按用户要求新增 §6.1–6.4、V13–V16 和 M0/M3 映射：公共端口不依赖
CLI/TTY，客户端复用同一部署目录；共享完整 Harnesstui 会话视图，由
Embedded/Hosted binding 接入，Mux 外壳只组合成员与连接职责。Hosted theme
未接入仍是 Current 缺口；工具/图片等 wire 未支持能力不宣称完成。

三位原 reviewer 独立核对本次新增章节、相关源码与全文一致性后均通过：

| 视角 | 复审结论与收口 |
| --- | --- |
| 架构 `lmux_arch_review` | 无 P1/P2；GUI 公共接口、共享视图/双 binding/Mux 外壳边界成立；修复重复标题 |
| 生命周期 `lmux_lifecycle_review` | 无 P1/P2；view.dispose 不扩大清理权，G16/G17 退出不同，unknown/代际隔离保持；补明审批完整身份键与 action 总额/控制预留 |
| 交互与验收 `lmux_ux_review` | 无 P1/P2；Markdown 现状有源码依据，能力矩阵不冒称全功能等价，V13–V16 与实施阶段一致 |

本轮通过范围仍为 M0 设计输入，不等于接受具体 API 或实现验收。只读源码
核对与文档检查，不实现 GUI、公共 API、共享视图重构或 Markdown 修复；
不提交、不推送。后续 M0 冻结类型与 owner 后，实施仍需对应回归及实现评审。
