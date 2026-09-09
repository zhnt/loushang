# G18 Startup Performance Design Review

- Date: 2026-09-09 UTC
- Subject: [G18 Linux-first plan](startup-performance-plan.md)
- Source baseline: `9bc69361494293595ae424be225c61e3226a9996`
- Status: approved — all three views passed; blocking findings closed
- Scope: design and pilot evidence only; no product optimization implementation

Three independent read-only reviewers examine architecture/ownership, measurement
validity/isolation, and public compatibility/lifecycle. The Linux-first sequence
is intentional; external macOS/Windows acceptance remains pending, not waived.

## Findings And Disposition

| ID | View / priority | Finding | Revision and disposition |
| --- | --- | --- | --- |
| G18-R1 | Architecture + measurement, P2 | “Do not change HOME” did not explain child isolation; model lookup still uses Path.home, outside LOUSHANG_HOME | Restrict prohibition to parent/real home; child env mapping supplies private platform home/config/temp, with allowlist and synthetic ambient-home sentinel negative control. Both reviewers re-reviewed: closed. |
| G18-R2 | Measurement, P2 | A private task root alone permits prior samples/warmup to alter Session/mux recovery work | Every sample uses a fresh root or matching seed/hash; fresh/recovery cases split; setup excluded; failed roots not reused before settlement. Reviewer re-reviewed: closed. |
| G18-R3 | Compatibility, implementation prerequisite | Callable-default identity controls RPC/plan/plain routing, not just signatures | G18.2 must test omitted default, explicit original callable, and injected replacement; preserve extension collect_help_flags and approval-builder behavior. Added to compatibility rules. |

All three independent reviewers approve the revised design with no remaining
P1/P2: `g17_design_architecture` (architecture/ownership), `g17_design_contract`
(measurement/isolation/gates), and `g17_design_lifecycle` (compatibility/lifecycle).
These existing reviewers were assigned new G18-only tasks; this is not a reuse
of their earlier G17 verdicts. The first two views re-reviewed their corrections;
the lifecycle view approved after the callable-identity prerequisite was added.

## Evidence And Limits

- [Linux pilot](startup-performance-g18-linux-baseline.md): eight cases, five
  retained samples each, non-editable isolated environment; all child exits zero.
  High noise, inherited application environment, no wheel hash/output assertion,
  and lack of native readiness evidence are explicitly disclosed. It is not G18.0.
- Private-environment source baseline: 11 passed, zero failed/skipped; SDK surface,
  extension help/injection and import boundaries. No product files changed.
- Four static documentation invariants and links in all four affected documents
  pass via `scripts/ci/check_docs.py --plan .artifacts/g18-design/docs-plan.json`.
- Reviewers were independent and read-only; no tests were delegated or repeated
  concurrently with the timed pilot.

Approval covers staged Linux-first design only. At that design-review point, formal measurement tooling,
optimization commits, exact real-startup fixture inventory and frozen regression
limits remained G18.0+ work. macOS/Windows verification remains pending on external
machines; existing mandatory gates and the separate execution-lane G10
investigation are not waived. No push, merge or production activation is implied.

## Subsequent Measurement Work

After this design review the user authorized measurement/baseline freezing.
[G18-LINUX-INERT-AA-01](startup-performance-g18-linux-freeze.md) records the
subsequent collector and 400 valid timed samples. The collector has focused tests;
**the earlier design approval is not a code-review verdict** for that later implementation. Native and
external-platform acceptance remains pending.

## Implementation Review In Progress

本节是用户启动 G18.0B＋G18.1 goal 后的新一轮代码评审，不复用上面的设计批准。
Product source 仍未修改，原始 A/A 报告不覆盖或重算。

| Finding | Disposition |
| --- | --- |
| 实际 console wrapper 未绑定 RECORD、解释器和 wheel entry target | 修复：精确 Linux uv 模板、SHA256/size、前缀内非 symlink 文件及目录、wheel entry_points 一致；含重写 RECORD 后的 stub/target/shebang 负控。 |
| exit 0 后强制 group cleanup 可掩盖残留后代（生命周期视角 P1） | 修复：既有 run_python retained wrapper 内先 subreaper 再 Popen；正常只 reap root，残留由唯一 outer owner 回收并判失败。生命周期复审确认原 P1 关闭。 |
| collector tests 未真正被所选门禁执行；Coding facade 漏下游入口 | 修复：精确 AppService test/lint 清单及 additive facade consumer scopes；门禁视角确认原两项 P2 关闭。 |
| 取消或 receipt 异常可能丢失正在运行的 sample | 修复：spawn 前持久化 pending attempt；失败/取消保留身份及失败类型后传播。定向回归已覆盖。 |
| native receipt 可覆盖父层身份且没有 exact sample binding | 已修复并经架构复审关闭：closed schema、sample root identity、限定字段投影、spawn inventory/cwd/finite timestamps 及负控。 |
| recovery seed 未证明完整 continuity/mux/member 工作量 | 实现缺口经架构复审关闭：校验 revision/mux/member/canonical identity、唯一 UserMessage、replay index、Store head；规范化保留 profile metadata；两次准备启动 settled 后才测量。真实 CLI2/CLI3 seed 验收未完成，禁止冻结恢复基线。 |

已执行：最新工具、比较器、帧握手与 CI 定向组合 **127 passed in 16.45 s**，证据为
`.artifacts/g18-baseline/tooling-final-tests.xml`；包括 double-fork、zombie、失败/取消记录、
wrapper/native receipt、数值边界以及不支持终端控制的负控。

纯比较器只接受已冻结的十个 A 组 case＋`elapsed_seconds`：≥20 对、至少两批、variant 内
稳定性、30% help 目标及 no-regression 规则。以每个浮点输入的 round-trip 十进制表示做
精确有理数运算，中位数/MAD/阈值比较无 epsilon 和舍入放宽，输出统计才转回浮点。
原“精确边界被误拒”和“未知/native metric 默认套 A 政策”两项 P2 经修复、负控与测量
视角复审确认关闭。截至该轮尚未接入独立 A/B wheel/source provenance runner；
后续接线见下方 Immutable A/B Source And Fixed Observer Follow-Up。Native 政策仍待冻结。

Linux fresh native 预检保留三次失败，均已确认执行终止，输出目录不复用：

- `native-preflight-01`：Embedded 错用 `/help`（当前不是本地命令）；进入模型路径后因
  没有凭证而失败。已改为已定义的本地 `/hotkeys`，不允许以此调用 live model。
- `native-preflight-02`：Hotkeys 面板成功展示，随后退出输入时序失败；已增加完整面板
  frame / close 观察。后续使用既有 FakeScreen＋受限 test-only CSI→TerminalOperation
  适配确认 `›/idle` 主屏恢复且面板消失，未知 ESC/C0/C1/OSC 拒绝；增量生命周期复审
  确认输入和投影 P2 关闭，仍待真实 installed 复验。该较重投影位于首次命令计时之外，
  面板关闭观察另记 `panel_close_observation_seconds`，不称为纯 Product 执行耗时。
- `native-preflight-03`：在首个命令前触发原 35 s ready timeout，终端无输出。
  同窗口发现 execution-contract-576 的独立 Python 测试仍运行，占用约 52–58% CPU；
  失败样本 load 从 2.84 升到 4.54。负载是混杂因素，尚不能证明此次超时成因；不改 deadline，
  不重复 retry-until-green。等独立测试结束、测量条件复核后再收集正式样本。

恢复查询完成后的退出已去除裸 Esc，直接使用既有全局 Ctrl+B,d；定义为从打开的 picker
退出，由真实 Shell close 完成面板清理，消除 Esc 与 Ctrl+B 合并为另一个按键的输入歧义。
Native 环境的 COLUMNS/LINES 明确为 100/30，与 PTY 尺寸一致，避免继承 A 组的 80 列。
尚无正式 B 基线、A/B 收益或 G18.1 兼容结论。
外部平台、全量本地交付门禁及提交仍待完成；不推送或合并 main。

第四次真实 Embedded 预检（`native-preflight-04`）到达 ready（32.322 s）并打开
热键面板，随后屏幕回放器解析既有 `CSI ? u` 键盘查询失败，样本保持 failed；
不是 Product 提速或退步证据。当前观测器补入既有键盘/字符尺寸查询及
modify-other-keys 模式的无绘制处理和回归，仍需真实复验。失败时已使用既有 owner
回收，不把这种回收记为正常 settlement。宿主外部 execution lane 的 Python 测试
仍在运行，本次预检不用于冻结性能基线；没有停止该外部进程。

第五次预检（`native-preflight-05`，cwd 恢复）在首个准备启动即触发原 35 s ready
timeout，终端无输出；未获取 CLI2/CLI3 seed，退出码 1 且失败证据保留。
不由此推断 Product 根因或放宽预算，也不原样循环重跑。后续 seed 准备记录改为先登记
running/spawn，正常收口才写 settled_at，避免失败时丢失准备启动身份。
校验读取 canonical JSONL、replay index、Store metadata 和有关锁文件（包括
session-assets），不调用会自愈的 loader；Store head 校验含只读 stat。

本次 seed 收口定向验证：**44 passed in 12.08 s**，证据
`.artifacts/g18-baseline/native-seed-final-tests.xml`；覆盖 cwd/global 的只读验证、跨根
规范化 profile metadata、额外历史/成员/索引/Store metadata 拒绝、两次准备启动先后顺序。
过程中两轮定向测试暴露了漏计 `.store.json` 和 `session-assets/.locks` 的清单问题，
已补齐后通过；原失败 XML 保留。架构视角批准的是本代码切片，不是实际恢复性能验收。

`native-preflight-06` 在确认原外部测试 PID 已消失后执行：首个 Embedded warmup
正常完成（ready 16.406 s、首个本地命令 0.040 s、settlement 1.022 s），第二个独立安装
仍在原 35 s ready deadline 无终端输出而失败，整体 failed，其余场景未运行。
这证明查询/面板修复实际可用，但既不证明稳定性，也不能单凭原 PID 退出归因超时。
不继续原样循环采样；下一步独立 import/profile 归因与系统资源竞争检查。

G18.1 兼容前置：独立冻结的 48-export owner map，四种 fresh-process import order
下逐项 `is`、别名、dir/star、未知属性与适用的 type/function pickle 检查通过：
**3 passed, 5 deselected in 37.33 s**，`.artifacts/g18-baseline/facade-compat-baseline.xml`。
这是 source-mode 兼容基线；尚未覆盖 lazy-only 不导入、失败不缓存、TYPE_CHECKING
正负例和完整激活验收，也未实施 facade 优化。

### Baseline Import Attribution (Not A Timing Comparison)

在上述测试结束后，独立执行 installed baseline `import loushang.coding` 和真实
`loushang --help` 的 importtime 归因。使用 baseline install-a、相同 wheel/lock，
每个 case 新建私有 bytecode prefix；非 warm-bytecode 性能样本，无优化代码。
完整 profiler stderr、命令、wheel/工具/script hash 在
`.artifacts/g18-baseline/import-attribution-01/report.json`。

| 归因 case | importtime 记录行数 | profiled wall / child CPU | Coding facade inclusive | bootstrap inclusive |
| --- | ---: | ---: | ---: | ---: |
| import Coding | 989 | 9.008 / 7.399 s | 8.091 s | 4.505 s |
| installed CLI help | 1438 | 16.348 / 13.136 s | 9.154 s | 4.693 s |

这些是带 profiler/独立新 bytecode prefix 的描述值，不与 warm A/A 表相减、不声称
可直接节省这些秒数；inclusive 项包含嵌套导入，不能相加。Coding facade 确实提前
进入 arch、bootstrap、resource/session 依赖链，支持 G18.1 先缩小顶层导入图。
CLI root 自身还加载 UI/handler，是否继续优化 dispatch 留在 G18.2，不混入此次 facade 切片。

静态验证：Ruff、diff whitespace、四项文档 invariant 通过；Actions 使用仓库固定版本
actionlint v1.7.12 检查通过。初次找到的旧 v1.7.7 不识别既有 macos-15-intel 标签，未因此
更改工作流或放宽门禁；切换到已存在的正确版本完成验证。

### Immutable A/B Source And Fixed Observer Follow-Up

新增不可变来源接线的三项 P2，经负控及 `g17_design_contract` 只读复审关闭：

1. Git 读取清除 ambient `GIT_*`、禁用 replace 和外部 config；cwd 的 clean 检查也走
   相同读取边界。外部 GIT_DIR/config 和 commit/blob replacement 不能改写来源身份。
2. source 校验与安装校验分别在同一 wheel 字节快照上读取 ZIP 并生成 hash；已核验的
   source hash 固定贯穿初末安装检查，不能用后来重新读取的 hash 替代来源承诺。
   覆盖 source 快照读取后替换、安装检查前/中替换和不一致 receipt。
3. committed `tool.setuptools.package-data` 声明的资源必须完整存在；按路径层级匹配
   glob，不要求源码中未声明的 README。增加 missing-resource 及嵌套 glob 负控。

对应来源、inert/native 工具及 CI 定向验证：**137 passed in 35.36 s**，
`.artifacts/g18-baseline/provenance-fixes-tests.xml`。这不替代全量交付门禁。

Native observer 随 candidate 导入图改变的混杂也已单独修复并获测量视角批准：
第三套独立 wheel A 安装作为固定 observer，使用相同独立 observer cache；显式参数
选择 measured prefix，测试 fixture launcher 接线不改实际 `sys.executable`。
receipt 区分 observer origin/prefix 和 measured prefix；初末 observer 校验固定到
source A，并与两侧核对解释器、依赖和入口。此切片定向验证 **48 passed in 14.73 s**，
`.artifacts/g18-baseline/native-fixed-observer-tests.xml`；不代表 native timing 通过。

### Native Preflight 07: Failure Counters, Not A Baseline

固定 observer 和 failure-only `/proc` 计数器接入后，单独 foreground 预检在第一项
warmup、side B 仍触发原 **35 s** ready deadline，终端输出为空。未重试、未增加
deadline、未运行其余配对样本。外层 retained owner 回收失败路径残留后以 exit 1 结束。
报告 `.artifacts/g18-baseline/native-preflight-07/report.json` 与 scratch
`/tmp/loushang-g18-native-qoa0ycj6` 保留。

失败前捕获的 root 主线程 schedstat 显示约 **9.929 s** CPU 执行与 **16.870 s**
run-queue 等待；当时 CPU pressure some avg10 **98.44%**，I/O some avg10
**27.85%**、memory some avg10 **7.64%**。这些是同窗干扰证据，不是 Product 全树
CPU 统计，也不能单独证明只有环境原因。后续只读进程快照另见一个 Python 报告
62% CPU；确认 cwd 前该 PID 已消失，因此不将其归属任何 agent/lane。

不在相同压力下继续原样循环预检。真实 B 基线、recovery CLI2/CLI3、absent-bytecode
和 candidate 收益仍未验收；Product 源码尚未修改。

### Product First-Use Adapter And SDK Baseline Follow-Up

新增 `product-first-use` 直接调用既有 discovery-enabled G16/G17 workflow，分别记录
server-ready、review/dev/reattach frame、首次模型回复／approval／tool、interrupt
和最终 stop settlement；只在原 witness 成功后记时间，重附加历史不覆盖首次值。
Synthetic transport server 使用 measured Python，三次实际 mux attach 使用 measured
console，observer 仍固定 source A。该 server 不是 shipped-console 启动证据。

新增负控覆盖 missing tool milestone、错误 server script、原 tool/interrupt witness
失败不能记成功时间；并完成 SDK facade 全部测试，新增精确 export order、Harness-first
导入和两项 alias identity。**63 passed in 201.05 s**，
`.artifacts/g18-baseline/native-product-facade-tests.xml`。该运行包含 source-mode SDK
smoke，不是 installed/native 性能验收；较长 suite elapsed 不用于推导 startup。

`g17_design_lifecycle` 对 first-use 增量、`g17_design_architecture` 对本轮来源／固定
observer／first-use 边界完成只读复审，均无 P1/P2；测量视角已分别批准 provenance 和
固定 observer 接线。三者结论只覆盖所述代码切片，不批准 B 冻结或尚未实现的 G18.1。

### Native Preflight 08: Product First-Use Passed, Timing Not Frozen

上述测试完成后，使用固定 observer、两套相同 baseline wheel 安装单独执行
`product-first-use`：一个 block、一对样本，加上两侧各一次 warmup。
**四次完整流程均 valid=true，报告 complete-record-only，runner exit 0**；
初末三套安装核验一致，外层 retained owner 逐项批准。原始报告为
`.artifacts/g18-baseline/native-preflight-08/report.json`，独立 scratch 为
`/tmp/loushang-g18-native-1da4vka6`。Raw report SHA256：
`df8c41117f8cd7f943bf7b833c6a26852adb9d47ca9cb3f2936c76d563f7c0ed`。

这首次补上了真实 synthetic-transport Product 的模型、审批、工具、中断、三次
attach/detach 和最终 server/PTY/reader settlement 观测，不代表默认模型网络请求。
原 first-use/ready/exit 预算均未延长；前述 native07 失败保留，不由此覆盖。

只有一对非 warmup 样本，无独立 blocks，不能作稳定性或收益结论：例如 A/B 的
server-ready 为 11.629/11.317 s，但 dev attach 为 5.865/15.364 s；既不能挑选前者
判“稳定”，也不能把同一 wheel 的差异称为优化。需要继续实际 HOME 隔离负控、
恢复验收及正式基线校准，G18.1 Product 优化和本地交付提交仍未完成。

预检结束后，四组 G18 tooling 的精确 CI/test/lint ownership 清单验证 **43 passed
in 2.38 s**，`.artifacts/g18-baseline/g18-gate-inventory-tests.xml`；Ruff、四项纯文档
invariant、actionlint v1.7.12 和 diff whitespace 通过。全量交付门禁仍未执行。

### HOME Control Implementation And Temporary-Quota Failure

实现 default/hosted × leaked/private 四个真实安装态控制。默认 leaked 必须自主正数
非零退出并显示 poison 路径和 invalid JSON；hosted 两组必须实际 `/new cwd`，不能用
空 ready 代替服务创建。父环境和 synthetic ambient HOME 的目录/字节保持不变。
测量视角发现 root symlink P2，现用 lstat 拒绝非真实目录并在读取 poison 前取指纹；
生命周期视角发现晚到的相反结果 P2，现于 reader settlement 后再次检查完整结果。
两位原评审者增量复审均已关闭对应问题。

实际 `home-isolation-01` 在 foreground-leaked 的原 35 s ready 截止时间失败；随后
probe 的最终报告及 controller receipt 因 `OSError: [Errno 122] Disk quota exceeded`
无法发布。`/tmp` 为启用 `usrquota` 的 tmpfs，整体尚有空间不能证明用户配额充足。
此次样本无效，不能据缺失的中间凭据认定前序控制已通过。

将已完成 A/A scratch 从 `/tmp/loushang-g18-baseline-zvzkig52` 完整归档到
`.artifacts/g18-baseline/retained-scratch/loushang-g18-baseline-zvzkig52`，无活跃 cwd/fd
使用后才迁移。跨文件系统移动遇到只读插件目录，剩余 792 个文件逐一比对归档 SHA256
一致后，仅放开旧副本目录的 owner-write 并移除旧副本；原始报告、安装和归档均保留。
释放约 16 MiB 后原 retained owner 按既有协议完成回收，exec session 37545 exit 1，
对应 uv/runner/controller PID 均不存在；没有绕开 cleanup proof 或重写成功凭据。
最终失败报告 `.artifacts/g18-baseline/home-isolation-01/report.json` SHA256：
`8c27a781176cb767bbb1167b0907fca67ece3c2c1c66da35efb5373a7c43c6c9`。

修正控制的 bytecode 位置：使用 collector output 下的每安装/每控制独立缓存，
不再为四个控制各往临时状态根写约 20–26 MiB bytecode。HOME/state/cwd/temp 和
原 terminal 环境、Product deadline、退出/reader/child 证明不变。定向采样器/隔离
测试 **113 passed in 12.89 s**，`.artifacts/g18-baseline/home-isolation-cache-tests.xml`；
Ruff 和 diff check 通过。真实 HOME 控制重验及正式 B 冻结仍未完成。

架构增量复审发现默认 leaked 分支也必须等 reader settlement 才判最终输出，不能只等
进程退出。新增两例迟到输出回归先复现 **2 failed / 6 passed**，修复后默认分支
在 terminal context 退出后判 poison/invalid JSON/no Welcome；全组 **115 passed
in 11.05 s**，`.artifacts/g18-baseline/home-reader-regression-after.xml`。原架构评审者
只读复审关闭 P2，无剩余该切片 P1/P2。为修复此项，主动中断 `home-isolation-02`，
retained owner 正常返回，session 4558 exit 130；保留 failed 报告，SHA256
`8be335b871e2730d91711f97ed7b6e6116453caf8843b73df53bca03735f9bbf`。

### Real HOME Controls Passed

所有代码修复、定向回归及架构增量复审结束后独立执行 `home-isolation-03`，没有并行
测试/构建。两套安装各四个控制全部 settled；default leaked 自主退出 1 且 poison
错误成立，其余三项正常退出 0，hosted leaked/private 的首次 `/new` 分别得到
session-unavailable/member-opened。两份 ambient before/after 完全相等，wrapper 和
collector 环境不变，初末安装核验一致。报告 complete-record-only、两样本 valid=true，
retained owner 全部批准，exec session 73741 终态 exit 0。

Raw `.artifacts/g18-baseline/home-isolation-03/report.json` SHA256：
`532d9ae9f8f4a564680795632a0ddb2209c95cc9ae6011d96d46b6564e3d50a4`；
scratch `/tmp/loushang-g18-native-nz89bxfc`。本节关闭真实 HOME 隔离控制缺口，不计算
其时间收益，也不覆盖旧失败；恢复/native 正式基线、cache modes 与 G18.1 仍待完成。

### Recovery Preflight 09: Real CLI2 Reached, Seed Boundary Incorrect

在 HOME 控制通过后单独运行 cwd/global 预检，第一项 cwd B warmup 的 CLI1 创建/关闭、
CLI2 picker 选择历史与退出均 settled。CLI3 尚未启动，旧 seed validator 的
`len(sessions) == 1` 失败：递归扫描把 session-dir/plugin-state 下的 activation/
definition decision journals 也视作 canonical Session。样本仍失败；没有把 CLI1/2
的成功升级为完整恢复验收。Run session 11158 终态 exit 1，raw report
`.artifacts/g18-baseline/native-preflight-09/report.json` SHA256：
`865084f507da3cacb9765866b900dc369bc9a650de96f745bdc0a66033051818`。

实际现场还有 platform continuity journals、package lock 和 Plugin revisions；当前
合成 fixture 未覆盖这些恢复输入。43 KB Store head 包含真实 operation filter，不是
应裁剪的异常数据。不能只过滤 nested `.jsonl` 并跳过未知输入来修出一个绿色样本。

三视角增量设计讨论转向完整 opaque snapshot/reset（详见 scenario inventory），
减少性能工具对插件内部 journal 格式的耦合，目前只批准此方向，不是完整 A/B 方案：

- 架构：固定 Product 状态路径，全树 byte/mode/empty-directory manifest；coordinator、
  snapshots、owner registries、报告与 bytecode 在 reset 集之外；首次样本也必须 reset。
  inode/ctime 无法按字节恢复，不能继续宣称 Store head warm/current，也不能直接推定
  CLI3 会触发 Store append/commit fast-path 的回退；content-based replay index 另论。
- 契约 P2 待解：真实 package-lock sourceIdentity 包含绝对 measured install-b 路径。
  同一 snapshot 给不同 A/B 安装前缀会产生不对称来源匹配/reconcile；需固定 Product
  可见安装路径（切换和来源核验在计时外）或另证同工作量，不能篡改源记录消除此差异。
- 生命周期：生成 seed 的整个 retained observer 必须物理收口后才能复制；SDK 工作
  也可能持有进程级 durable startup lease。普通 lease/lock 文件原样保留，不复制 OS
  锁、不删除文件伪造干净态；reset 绝不包含 supervisor 的唯一 owner 证明。

新恢复条件及安装/bytecode 布局尚未完整批准或实现。原 G17 三次实际启动的非空历史
和正常 settlement 预检继续保留；旧恢复基线仍未通过，Product 优化仍未实施。

### Opaque Recovery State And Retained-Owner Stages

新增 test-side `_g18_recovery.py`，完整保存私有 subject 内的普通文件、目录、mode、
mtime 和字节 hash；不解码 Plugin journals，不重写 lease 或 Store head。控制目录、
owner registry、快照和 bytecode 均位于 reset 集之外。准备回调必须等既有 retained
owner 返回后才允许 capture；包括首次样本在内，每次 sample 都先从独立副本复位。
任何准备、复制或运行失败均保留现场并禁止继续复位；不新增进程 supervisor。

组件三视角复审的两项问题已修复：Linux-only 入口在创建目录前拒绝其他平台，实际
reset 测试在其他平台明确 skip；inode 回归只比较相邻两代仍有意义的身份，不假定
已删除 inode 永不复用。普通输入检查和平台拒绝测试仍跨平台执行。复审批准此组件
切片，不表示固定安装槽位、cache modes 或恢复 A/B 已获批准。

- 组件及精确 CI ownership：**59 passed**，
  `.artifacts/g18-baseline/recovery-state-reviewed-tests.xml`。
- prepare/restored 适配及协调器负控：**101 passed**，
  `.artifacts/g18-baseline/recovery-parent-stage-tests.xml`。覆盖 pending owner、
  缺少准备启动、错误被测入口、缺失 milestone 时禁止下一样本；这不是 native 证据。

`--restored-recovery-preflight` 限定同一 baseline wheel、固定 measured prefix A。
每个 scope 的 CLI1/CLI2 在独立 observer 内完成，外层 owner 返回后保存全树；随后
两个独立 observer 各自在复位后执行 CLI3。原 G17 `_picker_resume` 仅作函数提取，
history、member、`/sessions`、退出动作及原预算不变；原三次连续启动测试仍保留。
本模式只验 owner/reset/真实恢复接线，明确为 bytecode-as-found，不声称 Store head
warm，也不计算 A/B 性能收益。真实预检结果另记，失败不被上述单元测试覆盖。

`restored-recovery-preflight-01` 已完成两种 scope 的全部六个阶段，共八次实际 CLI
启动，外层 exec session 28834 终态 exit 0。每个 scope 的两次 CLI3 均在独立 reset
后恢复非空历史、完成首次 `/sessions` 并正常退出；初末三套安装 pin 相等。Raw report
`.artifacts/g18-baseline/restored-recovery-preflight-01/report.json` SHA256：
`7c23b1bf090610f39e8138601ea42fba3f0d1a0c67f3782806834e6107bf4ac5`。
该运行完成时，接线契约复审仍有 P2：prepare collector 仅接受任意 dict seed，未
完整检查 `settled_at` 及文件证据与外层快照的对应。它不是修正后的最终验收。

P2 已修复并通过契约复审：复用严格 scope/history/1 Session/文件哈希结构验证；
准备回执的字段和有限时间满足 `start < settled_at < next start`；外层 capture 后，
seed 的文件集合与完整 manifest 的 workspace 文件投影精确相等才允许 valid/下一样本。
新增负控在修复前 **12 failed, 6 passed**，修复后完整 native/state 工具测试
**114 passed**（`recovery-stage-review-before.xml`、`recovery-stage-review-after.xml`）。
原始成功/失败记录均保留；修正后的实际预检单独运行。固定安装槽位与缓存模式的
增量设计见 scenario inventory，尚不把同 prefix correctness 结果用于性能冻结。

修正后的 `restored-recovery-preflight-02` 两种 scope 全部六阶段通过，八次真实 CLI
启动完成，exec session 68040 终态 exit 0；每个 scope 的两次 restored CLI3 都来自
同一完整快照，完整 manifest 中均无 `.pyc` 文件。Raw report SHA256：
`2609550391570cd15bf1cb289690fcf1bbbf1a7f8253e0e6ea1f6beafa1354ea`，路径
`.artifacts/g18-baseline/restored-recovery-preflight-02/report.json`。
本次关闭 baseline 固定 prefix 的真实 owner/reset/receipt 接线缺口；不是切换两套
安装的验收，不冻结 cache modes、原 G17 live-seed 条件或 B 组性能阈值。

### Fixed Installation Slot: Reviewed Same-Wheel Native Switch Preflight Passed

三视角接受完整 venv 在单个固定真实路径构建和执行、同文件系统 rename 停放的方案，
条件见 scenario inventory。生命周期视角要求安装/验证也由既有 retained owner 管理，
且 busy/失败闭锁覆盖这些步骤；缓存另分 base Python shared-as-found、variant-owned
安装/外部缓存、recovery seed-preserved 三层，禁止将后者当作随 variant 保留的 warmup。
这些条件已进入设计和接线，不通过改变 journal 或 symlink 隐藏来源路径差异。

新增纯目录 `_g18_slot.py`，只负责 task-owned active/a/b 的 dev/inode、串行切换和
失败闭锁；生命周期代码复审无剩余 P1/P2。补充了 rename 已生效后中断的负控：仍
禁止再次激活，失败回执中的 active 仅是最后登记值，不是可恢复运行的物理位置证明。
协调器用既有 `capture` 执行离线 uv 安装，拒绝非零退出与强制 cleanup；每个运行阶段
在 slot guard 内 preverify → seed prepare/reset + 完整 owner → postverify。

目录、安装器、with-slot/without-slot 恢复负控及精确 CI ownership 共 **193 passed**，
`.artifacts/g18-baseline/slot-coordinator-tests.xml`。生命周期视角批准进程接线；契约
视角要求补 per-operation pre/post gate 的 mismatch/exception 负控。该 P2 已关闭并
复审通过：首个 restored 样本的前验证失配/异常均零启动；后验证失配/异常保留
observation 但 valid=false；二者均 slot.failed 且禁止切换 B。正向核对每个阶段的
pre/post 调用顺序及对应 wheel/hash。完整回归 **197 passed, 4 skipped**，
`.artifacts/g18-baseline/slot-operation-gates-tests.xml`；四个 skip 是 without-slot
组合不适用的 slot-only 校验，不是被跳过的原生验收。Ruff 和 diff check 通过。
`--slot-switch-recovery-preflight` 仅允许相同 wheel，两种 scope
分别 prepare A、restore A/B/A，明确 bytecode-as-found，不算 timing 或 cache-mode 验收。

真实 `slot-recovery-preflight-01` 已完成全部八阶段、十次 CLI 启动，exec session
83912 终态 exit 0。两个独立 venv 在相同绝对 active prefix 建立并通过来源/依赖/
console wrapper 核验；两种 scope 的六次 CLI3 恢复分别为 A/B/A，每次完整复位、
恢复非空历史、执行首次 `/sessions` 并正常退出。八个阶段的 pre/post 安装回执均
一致，最终 slot busy=false、failed=false；初末三套参考安装核验也通过。
目录切换没有重写任何 Product journal，也未执行 parked 路径。

Raw `.artifacts/g18-baseline/slot-recovery-preflight-01/report.json` SHA256：
`5edece2f2f7ceb8f899e4a3e8de4f31275aeed2a1e2bac600f3c2b88e2ab4c60`。
本结果关闭同 wheel 两环境固定路径切换的真实接线预检，不单独证明不同 wheel 的
恢复工作量相同。正式 warm/absent 条件、B 组重复基线/退步边界、A/B 比较负控、G18.1
产品优化、最终交付门禁和本地提交仍未完成。

### Explicit Cache Conditions: Coordinator Review And Regression Evidence

新增 `_g18_bytecode.py` 只处理当前 task-owned installation slot 和每个 variant 的
外部 `.pyc` 缓存；不执行解释器，不管理进程，不重置 Product 状态。完整清单先于任何
删除，拒绝未知 symlink、外部非缓存文件、身份变化及无对应常规源码的 installed
`.pyc`。后者可能就是程序本身：回归先复现误删，随后修复，相关 70 项测试通过。
真实独立 uv venv 的 `-I` 子进程见证确认：安装内相邻缓存仍可能产生，不能只清外部
`PYTHONPYCACHEPREFIX`。base Python/stdlib 保持 shared-as-found，recovery seed 保留。

`--fixed-slot --cache-mode warm|absent --requirements ...` 接入七个原有 native 场景。
每个样本都在 slot guard 内依次执行 prepin、fresh/reset、缓存准备、固定 observer
及既有 owner 完整返回、缓存后清单、postpin；完整返回后才置 valid。恢复的 baseline
seed 每个 scope 只准备一次，各 warmup/variant/block 都从同一快照开始。每轮清单独立
保存并以路径和 SHA256 关联，warmup 完成之前不接受正式样本，任一失败即停止。

接线三视角评审中，契约和生命周期未发现 P1/P2；架构指出 seed 年龄字段的命名误差，
已从 `age_at_launch_seconds` 改为 `age_before_observer_seconds`。该值在缓存处理和
observer 启动之前采样，不宣称是 Product Popen 时刻；prepare/restored 也记录
load_before/load_after。缓存模式只限定场景开始状态，多进程场景后续启动可能已被
同一场景的前序操作预热；不声称每个内层子进程都 absent。

完整工具定向回归 **267 passed, 4 skipped in 66.30 s**，
`.artifacts/g18-baseline/native-cache-integration-tests.xml`；字段更名后定向复测
**18 passed, 130 deselected in 11.35 s**，
`.artifacts/g18-baseline/native-cache-review-fixed-tests.xml`。负控覆盖 CLI 条件缺失/
互斥、prepin/cache/owner/postpin 失败、warmup 不能误计、逐轮缓存顺序及恢复输入一致。
此前 10 项 coordinator 回归和 sourceless 回归的原始记录一并保留。

真实 warm/absent 接线预检与正式重复基线仍独立验收，不以这些单元测试替代。当前
宿主机只读快照仍有 CPU pressure some avg10=92.91%、I/O some avg10=61.05%，
存在外部 Python/mux 工作负载；未停止外部进程，也不因此调整 Product 超时预算。

架构增量复审已确认上述字段 P2 关闭，三个视角均无剩余 P1/P2，批准限于接线。

真实 `native-fixed-warm-preflight-01` 已终止，exec session 20804 exit 1。两套安装
构建/校验成功；首次 `prepare:recovery-cwd` 的第一个 Product 在原有 ready 35 秒
预算内未输出首帧。失败发生在 seed 准备阶段，`samples=[]`，既不是 warm 缓存样本，
也不证明 absent 条件失败。已闭锁 slot（busy=false、failed=true），未启动后续
case 或重试。observer 及 Product 的已记录 PID 经宿主机只读 `ps` 核验均已不存在。

失败时 `/proc` 快照的 schedstat 为 CPU 执行 10.535 秒、run-queue 等待 22.174 秒，
CPU pressure some avg10=98.10%，I/O some avg10=24.01%。这些证据确认显著调度
竞争，不足以证明 Product 完全没有其他问题；保留原始 ready 失败，不将其改为通过。
原始报告 `.artifacts/g18-baseline/native-fixed-warm-preflight-01/report.json` 及
独立 observer receipt `/tmp/g18-recovery-eg56jk79/control/prepare-0.json` 均保留。
同环境不原样循环采样；先补不依赖稳定计时的类型/序列化兼容基线，再在负载条件发生
可核验变化后恢复 native 校准。正式 B 冻结和 G18.1 性能收益仍未完成。

本次 native raw report SHA256：
`de1560b80c6f8cc6309e09794a5ba5c3e5f1f8d001cb8dd3fd90ca3883ac2e42`；
observer receipt SHA256：
`ba86afa55873b81b4aca8efe2ab0082c15d7a739349d76af571f69e3dee045f1`。

### Transitive Helper Binding And Facade Compatibility Follow-Up

两个 collector 新增采样前/完成前的完整 scripts/tests 清单校验。范围保守覆盖 Git
tracked/nonignored 的辅助代码及 fixture，而非只列直接 import；校验 SHA256 和 mode，
拒绝 symlink/特殊文件/移出工作树。内容、增删或读取失败均禁止整体报告完成。
Ignored cache/build 文件不作为可信输入；这不是安全沙箱，不保证抵御恶意瞬时替换。
契约增量复审无 P1/P2，关闭普通开发场景的 transitive helper 前后绑定缺口。

实际工作树清单 **1,199 文件**，连续两次一致。新增内容/新增/删除/mode/symlink
负控及 native main 的前后清单门禁后，相关回归 **204 passed, 4 skipped in 24.11 s**，
`.artifacts/g18-baseline/helper-inputs-tests.xml`。该接线晚于上述失败预检，不能倒推为
历史报告已具备完整 helper provenance；后续正式采样使用新版工具。Ruff/diff check 通过。

G18.1 尚未修改 Product。四种 fresh import order 增补真实实例 pickle round-trip，
覆盖 ModelSelection、ContextUsageSnapshot 及两个 SDK 报告对象，保持具体 type 和值。
四项通过，记录于 `.artifacts/g18-baseline/facade-typing-pickle-baseline-tests.xml`；
同次新增的两项 mypy 正负控因继承项目 `files` 与 `-c` 冲突失败。显式隔离配置后的
第二次运行仍 **2 failed in 246.37 s**，均触发 120 秒静态检查上限，无类型结论，
见 `.artifacts/g18-baseline/facade-typing-baseline-fixed-tests.xml`。随后依据本地 mypy
参数实现改用 `--config-file=`，避免 `/dev/null` 缺少 `[mypy]` 的告警；此修正后
尚未再次验收。未跳过真实依赖、放宽检查上限或宣称类型兼容通过。

本轮 `/tmp` 再次触及用户配额。已结束的精确测试目录
`/tmp/pytest-of-dev/pytest-1/test_coding_facade_identity_st0` 已可恢复移动到
`.artifacts/g18-baseline/retained-scratch/facade-pickle-baseline-01`，释放约 13 MiB；
后续纯测试的 basetemp 放在新建任务 artifacts 目录。未清共享 `/tmp`，未删除
Product/用户状态，也未动其他 agent 的目录。所有已启动的本轮执行句柄均已终态。

### Native 41-Metric Policy And Incremental Review Closure

候选 Product 改动之前，三个视角审查了 [native comparison policy](startup-performance-g18-scenarios.md#native-comparison-policy--pre-candidate-review)。
每种缓存条件单独覆盖七个场景、两批各十对；初始 36 指标增补 local mux 的
spawn-through-first-command、Product 的 spawn-through-first-model，以及三次独立
detach/reader 收口，合计 41 项。累计区间不相加，不允许 ready 改善掩盖首次使用
或清理退步；此前 36 指标预检不因此升级。

纯比较器已实现这些规则和逐项退步负控。observer 只增加计时锚点，复用既有动作、
witness、owner 和 deadline。异常继续传播，未完成的 witness/上下文不会生成成功
收口指标。首轮回归 251 passed、4 skipped；随后代码评审发现两项 P2：

- Product context 进入前读取尚为空的 spawn 回执；修复为进入后读取原始 Popen 时间。
- native 复用了 A 组较宽的分组条件；修复为严格整数 2×10，A API 的兼容性不变。

更真实的延迟发布回执夹具和 4×5、20×1 分组负控先复现 **3 failed、2 passed**，
记录 `.artifacts/g18-baseline/native-review-before.xml`。修复后两组完整回归
**255 passed、4 skipped in 37.69 s**，见 `native-review-after.xml`；Ruff/diff check
通过。架构和契约增量复审确认各自 P2 关闭，生命周期视角已通过该计时切片。
这些结论不代表真实 native 校准通过；比较器与最终采集报告的接线仍待完成。

### Second Warm Preflight And G14 Diagnostic Evidence

宿主机新窗口 CPU pressure some avg10 降至 15.71%（此前 98.10%），但 I/O some
仍为 46.54%，因此不是无噪声环境。`native-fixed-warm-preflight-02` 两个恢复 seed
准备及 embedded/foreground/local-mux 的六次 warmup 完成，第七次 G14 stdio warmup
在既有 evidence owner 处失败。exec session 47763 已终态 exit 1，slot 闭锁；未继续
正式样本或把失败重试为通过。

内部 receipt 已观测 protocol ready 12.788601369 s、first command 0.020112437 s、
settlement 1.642717187 s，但外层报告 `status=1, leftovers=True, force_cleanup=True`。
结合 owner 在结果发布前的 `threading.enumerate()` 判定，可以推断当时存在未知
Python 线程；原始回执未记录线程名，具体线程和原因尚未确定。内部 observed 不能
代替外层完整收口。raw report SHA256：
`14b68458a2fc80175125d6a24075c73e1146c4ce51329b14a9dea7d91d53b310`。

一次诊断以及预先声明的四次独立诊断均未复现：结果发布边界仅见 MainThread 和已知
control reader。四次诊断在原 enumerate 决策点采集同一 snapshot 并原样返回，未因
记录延迟重新枚举而改变判定。仅记录线程/栈，不采局部变量，不改 owner、Product
或超时；这是 diagnostic-only，不是性能验收。exec sessions 79686、73448 均终态。
四次诊断报告 `native-g14-thread-diagnostic-02/report.json` SHA256：
`d714d4dd4052a3420e41a186b632097d6b5efdb296115a761eee5ade9d964e30`。
原始 G14 force-cleanup 失败仍未关闭，正式 warm/absent 基线及 G18.1 收益仍待验证。

### Comparison Report Wiring And Typing Baseline Closure

两类采集器现在从 `comparison.verdict=not-evaluated` 开始，仅在样本 owner 返回、
安装（native 包含固定 observer）最终校验和 helper 清单一致后调用纯比较器。
native 仅 fixed-slot、全七场景、精确 2×10 发布完整结论；小规模、局部场景、非固定槽
及未经批准的分组保持 not-evaluated，并写明原因。符合正式分组但样本缺失则失败，
不降格为成功预检。模式从已验证 wheel hash 决定，A/A 校准不要求 A/B 的提升目标。

已知退步、跨 block 噪声、目标未达、缺样、owner 失败、安装/helper 漂移及预检边界
共 38 项新集成负控，在接线前全部因缺失 comparison 字段失败，见
`.artifacts/g18-baseline/comparison-wiring-before.xml`。接线后三个测试文件完整回归
**331 passed、4 skipped in 26.45 s**，见 `comparison-wiring-after.xml`。
这些是确定性假采样输入的接线测试，不是 38 次真实性能采样。

保持既有 advisory CLI 语义：exit 0 / complete-record-only 只表示采集完成，不表示
比较通过；终端另外打印 advisory verdict。报告区分 pass、regression、inconclusive、
target-not-met 和 not-evaluated，未建立 blocking 性能 CI 门禁。
架构与契约增量复审均通过，无剩余 P1/P2；批准范围仅此报告接线。

此前 mypy 隔离配置修正后的正式复测已完成：SDK 类型正/负控 **2 passed、9 deselected
in 176.75 s**，`.artifacts/g18-baseline/facade-typing-config-03.xml`。保持每次 120 秒
上限，未用 stub/Any 替换实际依赖，未放宽错误预期。结合已通过的四种 fresh import
order / instance pickle 基线，G18.1 的类型兼容前置缺口关闭；Product 实现仍未修改。

文档四项 invariant 及当前 change plan 的链接检查通过；计划因 Makefile/CI scope
变更仍选择全量相关门禁，本轮未执行这些最终交付门禁，也未提交、推送或合并。
本轮所有测试执行句柄均已终态，不存在需要重启的未结束测量。

G14 后续取证应保留既有 owner 判定：同一次 enumerate 快照固定 unsafe 后，仅在
失败时收集有界线程身份和栈（不读 locals/源码、不重枚举后降为成功）；独立诊断
sidecar 必须在父 owner 物理回收后传入异常并由 native 失败样本持久化，诊断 IO
失败不能覆盖原失败或改变释放顺序/预算。生命周期只读复核确认 Python 3.11
ThreadedChildWatcher 发布退出回调与线程真正退出之间存在可验证的屏障差异，但
这仍不是 warm02 的已证实根因。尚未实施上述取证，也未据此修改 Product 或 owner。

### Failure-Only Thread Evidence Implementation

上述取证现已实施：owner 在同一次 enumerate 快照上固定 unknown/unsafe，仅失败时
写独立 sidecar；控制 receipt 的 code/force_cleanup 不变。最多 8 个线程、每个 8 帧，
字符串限长，最终 JSON ≤64 KiB；只读取代码文件/函数/行号，不读 locals 或源码。
父 owner 物理清理完成后，才把限长普通文件内容附到原异常；native run_sample
将其保存为 owner_threads，仍为 failed/valid=false。诊断 IO 失败不覆盖原失败，
没有新增 sleep/join、预算、成功放行条件或 Product 修改。

真实 live-thread、快照后 thread 已退出、诊断 IO 失败及采集器持久化负控先复现
**4 failed、1 passed**（`thread-evidence-before.xml`）。实现及有界/非普通文件负控后，
owner 与 native 两组完整回归 **247 passed、5 skipped in 50.63 s**，
`.artifacts/g18-baseline/thread-evidence-after.xml`。真实进程用例检查 attach 时 PID
已回收，临时控制目录移除后诊断仍在异常中；快照后的线程退出不能重判成功。
三个视角增量代码复审均通过、无剩余 P1/P2；Ruff/diff check 通过。
批准范围是失败取证，不是 warm02 根因已关闭或 native 性能校准通过。

### G18.1 Candidate Versus Overall Gain Target

warm 03 运行期间只读核对了阶段边界：当前 plan 明示本轮交付 G18.0B＋G18.1，
G18.2 dispatch 与 G18.3 外部验收不在授权范围。default console 仍指向 cli.__main__，
该模块直接 import bootstrap/UI 等，bootstrap 又 import arch._provider_api，因而
只 lazy Coding 祖先 facade 不能静态承诺 default help 降低 30%。hosted_client 顶层
主要为 stdlib、parse_args 早于函数内 Product 导入，但实际收益同样需配对测量。

架构只读复核确认：G18.1 候选要提供实现、兼容性、前后归因和真实无退步证据；
如整体 help comparison 为 target-not-met，必须保留原结果，不能宣称 G18-GAIN 或
整体 G18 已完成。后续为追求整体目标修改 dispatch 需另行授权 G18.2，不能顺带实施。
这不改写原 ≥30% 目标，不豁免 native 失败/退步，也不以静态 import 图宣称收益。

### Fixed-Slot Warm Preflight 03 — Complete, Not A Statistical Freeze

失败取证实现和三视角复审后，使用新 slot/新状态运行完整七场景 warm 接线预检，
1 block × 1 pair。宿主机起始 CPU pressure some avg10=21.37%、I/O some=48.12%，
并非无噪声环境；本任务没有并行运行其他测试或构建，没有更改任何受测输入。

exec session 69349 已终态 exit 0。两个恢复 seed 准备完成，**14 warmups＋14 配对
样本全部 complete/valid**，每场景各四次；41 个规定指标均在实际工作流中记录。
四次 G14 stdio 均完成，无 owner_threads 失败；这不解释或升级 warm02 的原始失败。
采样前后安装/固定 observer 校验一致、helpers_before/after 一致；slot 最终
active=b、busy=false、failed=false。报告正确保持 complete-record-only，comparison
为 not-evaluated（分组不足正式 2×10），不能以这 28 次预检替代重复基线或收益验收。

- Raw report：`.artifacts/g18-baseline/native-fixed-warm-preflight-03/report.json`
- SHA256：`5736d3e8c99584d490abe7f470e512c60c9ee7672404feae7a07d3264ed5687b`
- Scratch：`/tmp/loushang-g18-native-ymc03tgp`
- Slot：`.artifacts/g18-slots/g18-slot-xq_ey7yg`

原始报告和输入均保留，后续 absent 预检及正式校准使用新的输出/slot，不覆盖本轮。

### Absent Preflight 01 — Quota Failure, Not Accepted

`native-fixed-absent-preflight-01` 完成两个 seed 准备及 27/28 次样本（含 warmup），
最后一次 Product first-use 的内部指标已观测，但 owner 封存 observation registry 时
`flush()` 抛出 `OSError: [Errno 122] Disk quota exceeded`。控制结果 code=0、
force_cleanup=false；这不是 warm02 的未知线程证据，也不能以内部成功升级 owner 失败。
当时 sandbox 本身的 `/tmp/.git` mount 注册同样报 quota exceeded。

按既有协议保留 owner 与 sample-28；在释放本任务的部分旧临时空间后，核验 collector
PID/cwd/argv/output，再发送一次 SIGINT 触发既有 cleanup retry。exec session 37951
最终 exit 1：物理清理返回后仍重抛原始 sticky failure，没有重启 Product 或重试样本。
最终 slot busy=false、failed=true，comparison=not-evaluated，旧 PID 已不在宿主进程表。

- Raw report：`.artifacts/g18-baseline/native-fixed-absent-preflight-01/report.json`
- SHA256：`b92c679e44da2df050088e55b1971cf9c9bb9f86d1a1e1095c4b70e168ea2cdb`
- Scratch：`/tmp/loushang-g18-native-83tyi44b`
- Slot：`.artifacts/g18-slots/g18-slot-bvy3xiy_`

旧 warm03 scratch 的跨文件系统归档是**部分移动**：可恢复内容位于
`.artifacts/g18-baseline/retained-scratch/native-warm-preflight-03`（约 8.7 MiB），
移除阶段因只读 plugin snapshot 目录而失败，原目录仍有约 576 KiB 磁盘占用。
后续只读核验确认剩余 144 个普通文件共 167,728 bytes，内容与权限均与归档对应文件
一致；未强制 chmod/delete，也未删除其他 agent 的目录。计时报告仍保留在原 artifacts。

### Explicit Scratch Parent — Regression And Three-View Closure

两个 collector 新增 `--scratch-parent`，默认 `/tmp` 不变；共同 argparse validator
在 source/output/owner 操作前 strict resolve 并要求既有目录。主 scratch 及 fixed/restored
两种 RecoveryState 都接收该 parent，实际仍由 mkdtemp 分配新的私有主体。报告新增
scratch_parent、scratch_device；seed、证据、安装 slot/cache 和 owner/timeout 不变。

回归先复现 **6 failed、4 passed in 2.23 s**（`scratch-parent-before.xml`）；实现后
两个 collector 完整回归 **248 passed、4 skipped in 19.64 s**，见
`.artifacts/g18-baseline/scratch-parent-after.xml`。非法 parent 提前拒绝、CLI 参数与
报告绑定、fixed/restored allocator 传播均有覆盖；Ruff/diff check 通过。
三视角增量只读评审通过、无剩余 P1/P2，批准范围仅任务临时父目录可选。

宿主核验 `/tmp` 为 device 38 的配额 tmpfs，`/var/tmp` 与 artifacts 为磁盘 device
64770；检查时磁盘可用约 2.4 GiB。后续明确使用 `--scratch-parent /var/tmp`，独立
记录容量与负载，并从新输出/slot 开始。新存储条件需要重新采样，不与历史 `/tmp`
报告拼接，也不能把介质变化当作 G18.1 收益。正式基线及 Product 优化仍未完成。

### Formal Warm A/A On Disk 01 — Collection Started

在上述回归与三视角复审之后，启动新的正式 warm A/A：七场景、2 blocks × 10 pairs，
预期 28 warmups＋280 配对样本。两侧 source 显式绑定 `9bc69361494293595ae424be225c61e3226a9996`，
使用原独立 baseline wheel/lock、固定第三 observer 与新 slot，scratch parent 为 `/var/tmp`。
文档四项 invariant/当前计划链接检查通过，Product 工作树无变更。

- Collector：`scripts/dev/measure_g18_native.py --fixed-slot --cache-mode warm --scratch-parent /var/tmp --blocks 2 --pairs-per-block 10`
- Output：`.artifacts/g18-baseline/native-fixed-warm-aa-disk-01/report.json`
- Scratch：`/var/tmp/loushang-g18-native-_benfuk8`，device 64770
- Slot：`.artifacts/g18-slots/g18-slot-7vscvlz7`
- Exec session：52758（已核验 live；句柄本身不代替最终报告）

本任务采样期间不运行测试/构建、不修改 scripts/tests/Product。历史 warm03 的 cache
evidence 约 69 MiB/28 samples；结合固定安装/cache 估算单轮约需 1 GiB，起始可用约
2.4 GiB，仅承诺当前单轮有余量，不预支后续 absent/candidate 所需容量。宿主最近窗口
CPU some avg10=28.26%、I/O some=53.02%，仍有噪声；最终按已接受规则判断，不预判通过。
当前仅启动采集，尚无正式比较结论，也未提交或冻结该轮。

首个实际检查点：两个恢复 seed 均 complete/valid；block 0 的 14 次 warmup 全部
complete/valid，两侧各有 5/4/6/3/5/5/13 项场景指标（共 41 项），随后进入正式
pair 0。原 exec 52758 仍 live、无失败；这是新存储条件下的流程证据，不是完整校准。

### Disk Warm A/A 01 — Watcher Handoff Failure Identified

随后 exec 52758 终态 exit 1：20 次 complete/valid，第 21 次（block 0、pair 0、
G14 stdio、side A）失败，slot busy=false/failed=true，比较 not-evaluated。原始报告
SHA256 `ae5a63fd49df6dd9f2823a75830354267770949e743ad4cd9b56062f38b883e1`。
未重试失败样本，也未继续复用失败 slot。

此次失败诊断明确捕到唯一 daemon `asyncio-waitpid-0`，栈为
`selector_events._write_to_self:139 → base_events.call_soon_threadsafe:813 →
unix_events.ThreadedChildWatcher._do_waitpid:1422`。内部已观测 protocol ready
3.123847323 s、first command 0.002035046 s、settlement 0.444580899 s；外层仍为失败。
实际 CPython 3.11.15 源码确认通知回调先入 loop 队列，watcher 随后仍执行 self-pipe
通知；`asyncio.run` 的 Runner 不 join 该 watcher，watcher.close 本身是 no-op。
本次可确认为 observer 的线程退出交接未完成，不能把它等同于已发现 Product 泄漏，
也不能倒推 warm02 未记录的具体线程身份。

确定性复现使用真正 ThreadedChildWatcher，在后台通知完成后以 event 屏障保留线程，
证明 process.wait 已返回而 owner 仍须拒绝。初版夹具误拦主线程的二次通知，触发原
15 秒执行＋60 秒清理预算，**1 failed in 76.61 s**（`watcher-handoff-reproduction.xml`）；
限定屏障只作用于后台线程后，**1 passed in 1.45 s**，见
`watcher-handoff-reproduction-fixed.xml`。断言保留失败及诊断，controller/child 均物理
回收；未改变 owner 判定或预算，也未以 sleep 概率复现。

三视角只读修复设计通过：仅 G14 fresh observer 使用私有 DefaultEventLoopPolicy＋
公开 SafeChildWatcher，主线程、无 running loop、原 SIGCHLD 为 default，完整包住
原 asyncio.run，成功/错误/取消后关闭自有 watcher 并恢复原 policy/信号。它只等待
登记 PID，不使用 broad waitpid(-1) 或后台 waiter，不改 Product、原 fixture/owner/timeout。
实际解释器缺 os.pidfd_open，故不采用 PidfdChildWatcher，也不补 syscall 或私有线程 join。
必须补未登记子进程 exit 7、异常/取消、初始化失败、零 spawn 前置拒绝及未知线程负控；
回执绑定实际 watcher 与 observer Python。当前仅设计接受，实施和代码复审尚未完成。
更换 observer backend 后重新 AA/AB，旧 Threaded 结果不得拼入或算作 Product 收益。

### Scoped G14 Safe Watcher — Implementation Review Closure

方案 C 已实施。G14 分支的完整 asyncio.run/关闭 coroutine 位于私有 scope 内；
初始化失败留下的私有 loop 也关闭，嵌套 finally 恢复原 policy/SIGCHLD，关闭或恢复
失败不会发布 observed 成功。不读私有 watcher 线程表、不新增 join/sleep/deadline。
G14 receipt 的新增 stdio_observer 严格绑定 backend、实际 watcher 类型和已验证
observer_installation.python，并保存到 sample；其他 case 的 closed schema 不变。

实现前 16 项回归全失败（`stdio-scope-before.xml`，30.00 s）。实现后补齐三种
初始化/loop-attach/close 失败负控，两文件完整回归 **273 passed、5 skipped in
70.34 s**，见 `.artifacts/g18-baseline/stdio-scope-after.xml`。真实未登记 child 的
exit 7 保留给原 Popen；登记 child 正常退出、错误/取消时实际清理、额外未知线程
仍由原 supervisor 拒绝。root cause 的确定性后台通知屏障回归也在此套件通过。

测试恢复使用原 `scripts/dev/run_pytest.py` leased namespace，显式任务私有
LOUSHANG_RUNTIME_DIR 指向 `.artifacts/g18-baseline/pytest-runtime`，不覆盖 basetemp，
仍在 sandbox 外并保留 not-live/skip-host-runtime selectors。Ruff/diff check 通过。
三视角增量代码复审均批准、无剩余 P1/P2；批准范围是 observer 修复，真实安装 G14
预检与新的完整 native A/A 仍待验证，不升级 disk-01 或更早失败。

### Installed G14 Safe Watcher Preflight 01 — Complete

原独立 install A/B 与固定第三 observer 下，新 backend 的 2 warmups＋2 samples
均 complete/valid，exec 30337 终态 exit 0；所有回执均绑定实际
`asyncio.unix_events.SafeChildWatcher` 和 CPython 3.11.15 的完整 build 字符串。
初末安装/observer 校验及 helper 清单通过，owner 未报告未知线程或清理失败。
这是非 fixed-slot 的单场景接线预检，comparison 正确保持 not-evaluated，不是正式
七场景基线或性能收益；三个计时锚点及原 fixture/owner 预算没有改变。

- Report：`.artifacts/g18-baseline/native-g14-safe-watcher-preflight-01/report.json`
- SHA256：`7596d622f4d5b0c2115fc10291a3552e8d51495e91fb85cc7fd80d45b68a2884`
- Scratch：`/var/tmp/loushang-g18-native-7lddbkyq`

后续新 warm A/A 使用该相同 backend、原 baseline wheel/source 和新的 slot/output。
启动前磁盘可用约 2.2 GiB；最近 CPU some avg10=5.04%、I/O some=2.55%，仍按已接受
规则计算最终稳定性，不根据更低负载预判通过。文档四项 invariant/链接及 diff check 通过。

新正式轮已启动：`native-fixed-warm-aa-disk-02/report.json`，exec 49826 已核验 live；
2 blocks × 10 pairs、全部七场景、fixed-slot warm、显式 `/var/tmp`，两侧 source
仍为 `9bc69361494293595ae424be225c61e3226a9996`。Scratch 为
`/var/tmp/loushang-g18-native-p0n743yz`，slot 为 `.artifacts/g18-slots/g18-slot-8hijgm2a`。
当前在准备恢复 seed，无完整比较结论；Product 未修改。此轮继续执行期间不运行
本任务测试/构建、不修改受测 scripts/tests/Product；未提交、推送或合并。

### Formal Disk Warm A/A 02 — Complete, Overall Inconclusive

原 exec 49826 已终态 exit 0，未重启或补样：七场景、2 blocks × 10 pairs，
280 正式样本＋28 warmups 全部 complete/valid，失败 0。两侧仍为同一 baseline
source/wheel，初末安装/固定 observer 校验通过，全部 sample pre/post pins 相同，
1,199 个 helper 输入前后一致。最终 slot busy=false、failed=false。

原报告 SHA256 为 `51937c7ac046dd306e820d645d934f89db9d36946927e46191a296f8e77c869d`。
按已接受规则计算得到 **30/41 pass、11 inconclusive，整体 inconclusive**；exit 0
仅代表采集完整，不是性能验收通过。缺乏稳定性的指标与完整样本投影见
[参考冻结记录](startup-performance-g18-linux-freeze.md#supplement-fixed-slot-native-warm-aa-reference)。
不更改阈值、不删样本，也不从两侧相同 Product 的耗时差异宣称优化收益。

11 项涉及 embedded/foreground/G14 settlement、global recovery ready/history、
Product dev attach/first tool/interrupt/三种 detach settlement。尚未确认波动原因，
不能仅以环境噪声概括为已定位，也不能把 timing inconclusive 当作生命周期失败。
原三视角评审者正在只读复核证据与后续交付边界；当前不预判复审批准。

结束时磁盘余约 1.2 GiB；本轮 output 约 867 MiB，其中 cache-evidence 约 784 MiB。
下一轮 absent 采集前必须核验容量；本段不授权删除其他任务数据，也尚未删除或
压缩本轮证据。Product 未改、G18.1 未实施，当前 goal 仍未完成，未提交/推送/合并。

三视角只读复核随后均通过、无 P1/P2，批准范围仅本轮参考证据及受控流程的功能/
正常退出/物理清理断言，不是统计稳定性批准。合同视角独立使用精确 Fraction 复算
全部 41 项，与 raw/projection 完全一致；308 个样本身份无缺失/重复、所有 cache
回执 SHA 一致。生命周期视角另核验 308 份原始 observer 回执、两类恢复 seed 各
44 次连续 reset，以及 44 次相同 G14 backend。

11 项均有四组 median span 超限，7 项另有组内 MAD 超限；只有 foreground
settlement、global ready/history、Product dev attach 四项属于仅四组跨度不稳。
这不是统计计算错误，也尚未定位波动原因。未来真正 A/B 仍须遵守每个 variant
独立稳定与全 41 项无退步规则，不能改标本轮 phase 或用未来 A/B 追认本轮 A/A。

架构视角特别指出：当前计划仍要求完成 native 基线后才实施 facade，这一前置尚未
满足，absent 参考完成也不会自动消除 warm 的 11 项不确定。若后续允许先开发待验收
的本地 G18.1 候选，必须在 Product 修改前明确评审调度补充；不得静默将“基线完成”
改释为“有报告即可”，也不修改最终 goal、阈值、指标或无退步要求。当前没有实施该例外。

持久投影经过逐字段核对和原比较器全精度重算，308 个样本及 comparison 与 raw
一致；文档四项 invariant/link 检查和 git diff --check 通过。

随后在无采集/测试/构建运行时，无损压缩本轮 616 个 cache-evidence 普通文件，
GNU tar compare 校验内容与元数据 exit 0，才移除展开副本；归档约 143 MiB，净释放
约 641 MiB，可用空间回到约 1.8 GiB。raw SHA 不变，其 cache 路径需恢复归档后
读取；归档 SHA 与恢复命令见参考冻结记录。未删除 raw/observer/seed/安装或其他
任务文件，也未处理旧只读 snapshot 残留。下一轮仍单独创建输出/slot/scratch。

### Formal Disk Absent A/A 01 — Collection Started

完成本轮参考记录与容量核验后，已启动新的 absent-bytecode 正式 A/A，exec 89689
已核验运行中。两侧 source 仍为 `9bc69361494293595ae424be225c61e3226a9996`，使用
原 baseline wheel/lock、固定第三 observer/SafeChildWatcher，全部七场景、2 blocks
× 10 pairs，预期 280 正式样本＋28 warmups；不混入 warm 数据或旧 quota 失败样本。

- Output：`.artifacts/g18-baseline/native-fixed-absent-aa-disk-01/report.json`
- Scratch：`/var/tmp/loushang-g18-native-yl_b62gx`，device 64770
- Slot：`.artifacts/g18-slots/g18-slot-xbc8gcl3`
- 初始 comparison：not-evaluated，尚无完整比较结论。

采集期间不运行本任务测试/构建、不改 scripts/tests/Product；保留失败与完整样本。
warm 的 11 项不确定及 native 稳定基线前置仍未解除；G18.1 未实施，goal 保持 active，
未提交、推送或合并。

### Read-Only Timing-Boundary Check During Absent Collection

等待原 absent collector 时只读核对既有计时路径，未运行新 probe/test/build，也未改
受测输入。`NativeTerminalProcessBase.read_until` 的 50 ms 是 condition wait 上限；
`_record_output`、reader done/error 都 notify，因此不能断言每次 witness 固定迟 50 ms，
更不能从 first-tool/interrupt 数值中直接减去该常量。POSIX reader 的 select 也会在
可读时立即返回，其 50 ms timeout 不等于固定输出延迟。

实际 CPython 3.11.15 的 `Popen._wait(timeout)` 则使用 WNOHANG 和递增 sleep，
最大间隔 50 ms。终端 `wait` 之后还执行 tail-drain；close 包含 reader join，reader
完成可以提前结束 drain。既有 settlement/detach 锚点包含这些真实观测/清理环节，
不能移动锚点或删成本来使基线变绿。10 ms terminate-tree/_wait_exit 轮询主要属于
仍存活时的回收分支，不能未经回执证据归因到本轮正常退出样本。

这仅识别潜在的观测分辨率来源，未证明其贡献大小，也不能解释全部 11 项波动，
尤其不能解释多个启动/attach 指标。若后续需要拆分 Product 退出与观察器尾部清理
成本，应在当前采集终态后先设计有界诊断并评审，保留原整体计时和原始 A/A 结论；
本段没有授权改 owner、deadline、ready 或最终验收标准。

### Disk Absent A/A 01 — Ready Timeout, Collection Failed

原 exec 89689 已终态 exit 1；未重启或补样。此前 86 个样本 complete/valid，
第 87 个样本（foreground、block 0、pair 5、side B）在原 35 秒 ready 期限失败，
PTY output_tail 为空、尚无 milestones。整轮 failed、comparison=not-evaluated；
slot busy=false、failed=true。最终安装/固定 observer/helper 核验未执行，不能把
86 个单样本有效记录当作整轮接受。此失败与 warm A/A 的统计不确定分开保留。

- Raw：`.artifacts/g18-baseline/native-fixed-absent-aa-disk-01/report.json`
- Raw SHA256：`85c5734f55c6cfdc9793d82c18927134fbbae8ebddc7fda1cb75a3dfe4907d91`
- Native receipt：`/var/tmp/loushang-g18-native-yl_b62gx/sample-87/native.json`
- Native SHA256：`92a96c9890630473ca77edb5a933b0a1897969d5931afe0850209156f3c7d06d`
- [持久化诊断投影](startup-performance-g18-linux-absent-aa-failure.json)保留条件、来源、失败样本及进程快照。

失败当时 CPU pressure some avg10=82.64%、I/O some=42.12%、memory some=16.70%；
被测 PID 2821814 的 VmSwap=30,308 KiB，schedstat 记录 CPU 约 10.51 s、runqueue
等待约 12.93 s，快照处于 ep_poll。样本前 load 为 4.05/3.19/2.38，存在显著资源
争用；这只是观测证据，不能由单个进程快照证明所有超时均由环境导致。后续宿主
进程摘要仍有其他任务活动，未停止或修改这些任务；已异步询问安静测量窗口。

原 owner `_cleanup` 返回后才报告 status=1、leftovers=true、force_cleanup=false
并抛出 CalledProcessError；此处 leftovers 是清理时发现的残留，不是退出后仍保留。
没有 cleanup-pending 状态。宿主只读 ps 核验已知 controller/native PID 2821744、
2821814 均不存在；不把这两个 PID 检查单独扩大为任意进程树证明，也未发送信号。
失败输出、scratch、slot、cache 证据均保留，未扩大 deadline 或复用失败 slot。

### G18.1 Lazy-Only Regressions — Red Baseline, No Product Change

native collector 终态后新增 `tests/coding/test_lazy_facade.py`，只准备已授权 G18.1
的回归门禁：fresh `-I` 进程、显式源码 origin、私有 HOME/bytecode；导入/dir/未知名
不得加载任何 runtime owner；正常名和别名各覆盖 import/attribute 两阶段的
ModuleNotFoundError、AttributeError、KeyError、RuntimeError，要求原异常对象透传、
失败不缓存、成功后复用身份。注入 loader 仅存在于隔离测试子进程，不修改 Product
import machinery，也不执行真实 owner/模型/native 场景。

使用既有 leased pytest runner，在 sandbox 外保留 not-live/skip-host-runtime，
得到 **17 failed in 14.37 s**，见 `.artifacts/g18-baseline/facade-lazy-before.xml`。
均按预期在当前 eager facade 导入 `loushang.ai` 时被拒绝，不是初始化/超时失败；
尚未执行到未来 lazy facade 的成功/故障注入后半段，因此不能宣称那些回归已通过。
新文件 Ruff format/check 通过，Product 源码未改。这是 regression-first 红灯，
不满足提交完成条件，也不解除先完成 native 基线的计划前置；没有实施调度例外。

### Scheduling Addendum — Accepted Before G18.1 Product Edits

架构、合同、生命周期三视角只读复核均批准，无 P1/P2。计划文首与 Scheduling
Addendum 已同步：无 native 采集运行时，可先实现、验证及评审已授权的局部 Coding
facade 候选；代码门禁通过后可作明确标注 performance-pending 的原子本地提交。
不增加 G18.2、公共 API、生命周期、owner 或 timeout 变更，不授权 push/merge。

G18.0B 仍为 partial，旧失败与 inconclusive 原样保留。稳定 A/A、两种 cache、七场景
41 指标、真实无退步及原整体目标均未解除，未来候选收益不能追认旧 A/A。故障注入
设计获准，但 17 项旧红灯只证明 eager 前置边界；异常/缓存后半段须实现后实际转绿。
本轮批准不是 activation、完整兼容、安装态或性能验收，也不是 goal 完成。

### G18.1 Implementation And Corrective Code Review — Source Regressions Passed

唯一 Product 修改是 `src/loushang/coding/__init__.py`：保留原 48 项 __all__ 顺序、
逐项 owner/alias 和 TYPE_CHECKING 显式导入；runtime __getattr__ 只缓存成功取得的
原对象，owner import/attribute 异常原样传播。无 CLI dispatch、激活、锁、boot ID、
清理或 deadline 实现变更。

首轮 `.artifacts/g18-baseline/facade-candidate-after-01.xml` 为 **24 failed / 100 passed，
512.73 s**，exec 97330 已终态 exit 1。其中新进程 lazy 17 项和四种原 import order
通过；negative Mypy 只报 assignment/arg-type、漏掉 attr-defined，是实际实现缺陷。
已由别名 guard 改为标准 `TYPE_CHECKING`，并在 runtime else 删除该辅助名；同一修改
也使既有静态 import graph 正确识别 type-only 分支，不扩展 parser。

另外 23 个失败来自 bootstrap。回溯确认这些普通测试加载的是旧 private venv 中的
installed Product，并非候选 source；runner 在 pytest 设置 pythonpath 前已经导入
Foundation 和所属 regular package。原 leased root 又位于 checkout 的 .artifacts，
出现 workspace ceiling/祖先 AGENTS 与扩展发现差异，后半段另有 Errno 122 配额错误。
这组结果不能作为候选 activation 证据，也不能将所有失败笼统认定为资源争用；
保留原 XML，校正组合后逐项观察同一测试 inventory。

合同评审发现原 star/named 检查前已经缓存全部 exports（P2）。已补 cold-star 与
cold-named：新进程先断言 Coding 未入 sys.modules，首先执行对应 import，再执行原
48 导出 identity/alias/pickle 验证。另补 concurrent-bootstrap：owner 尚未导入、目标
尚未缓存时，四线程同步首次解析四个 exports，核对原对象、module、lock、boot ID。
线程池正常退出，外层原 60 s 子进程期限不变；30 s Barrier 仅防测试永久等待。

架构、合同、生命周期小闭环只读复审均通过，无剩余 P1/P2；批准仅代码与覆盖，
negative Mypy 三类诊断和实际 source-mode activation 仍须实跑确认。校正命令使用
env allowlist、启动前显式 PYTHONPATH=checkout/src 和 `/var/tmp/lg18-tests-SYx1qY`
私有 HOME/data/runtime/tmp；在真正 pytest 进程内断言 Coding/Foundation/bootstrap
均来自 checkout，再通过 runpy 执行原 leased runner，保留 not-live/skip-host-runtime。
exec 16474 随后终态 exit 1，输出为 `facade-candidate-after-02.xml`。
source-mode 不替代 wheel/native/performance，基线状态不变，尚未提交/推送/合并。

第二轮为 **52 failed / 75 passed，297.04 s**。逐项 XML 检查确认所有 52 个 failure
trace 均含 `A locked Plugin dependency source is outside its installation`。来源断言
已确认加载 checkout，但旧非 editable metadata 指向安装目录；现有 distribution
resolver 的 required_paths 检查因此拒绝真实插件激活。这不是准许绕过来源验证的理由。
Mypy 正反例（恢复全部三类诊断）、七种新进程导入顺序/并发以及 lazy 回归均已通过。

后续源码回归另建 `.artifacts/g18-source-tests/venv`，CPython 3.11.15、原 requirements
带 hash 离线安装，再以 offline/no-deps editable 安装本 checkout；build exec 25301
已终态 exit 0。Product 原先已明确允许自己的 editable checkout；未改该授权或 verifier。
第三轮须在实际 pytest 进程中同时核验 editable direct_url 与源码来源，使用新的外部
私有根并重跑同 inventory。旧 wheel/design/observer 安装不变；第二轮失败完整保留。

新环境的 40 个非 Product distribution 名称/版本与 baseline install-a 逐项一致，
uv pip check 验证全部 41 个安装包兼容。第一次启动 editable 校验时，构建生成的
`src/loushang.egg-info` 被显式 PYTHONPATH 优先发现，其 direct_url 为空，故在进入
pytest 前停止（根 `/var/tmp/lg18-tests-Od1LLt`，没有生成 after-03 XML、没有运行测试）。
该 Git-ignored、非 tracked 的构建元数据已完整移至
`.artifacts/g18-source-tests/build-metadata` 保留，可恢复；没有删除 Product 源码。
重新检查只存在一个可发现的 loushang distribution，direct_url 正确绑定 editable checkout。

exec 13816 已终态 exit 0：根 `/var/tmp/lg18-tests-X7LXBh` 的同一 127 项 source-mode
inventory **127 passed in 251.34 s**，无 skipped/error/failure，XML 为
`facade-candidate-after-04.xml`。实际 pytest 进程输出并断言新 sys.prefix、唯一 loushang
distribution、editable direct_url 和三个源码 origin。来源正确的候选已通过 SDK 实际
Session smoke、全部 bootstrap/composition 回归以及原 23 个 bootstrap 失败用例；
首次两轮失败报告保留，不追认旧结果。原超时和 safety selectors 不变，未修改 verifier
或 lifecycle 实现。此证据仅为源码功能/兼容性，不证明 wheel/native 或性能已通过。

三视角代码复审的修正项现已由真实回归闭合。后续仍须完成变更计划所选的更广泛
本地门禁、原子本地提交、不可变 wheel 候选与原性能验收；goal 保持 active。

### G18.1 Broader Local Gates — In Progress

最新变更计划仍选择全部 scopes（Makefile/CI 基础设施修改），不因 facade 定向回归
通过而缩小该计划。已完成的 CI 43 项、actionlint、文档 invariants/link 检查之外，
源码依赖图 `render_current_package_dependencies.py --check` 已通过（exec 1682 exit 0）。

原 `make check-ai` 在独立 source-tests venv 与 `/var/tmp/lg18-tests-zrkV8O` 私有根
执行，`UV_PROJECT_ENVIRONMENT` 显式绑定该 venv，UV_NO_SYNC/UV_OFFLINE 保证不替换
安装或联网，exec 76101 已终态 exit 0。Make 中旧 .venv activate 路径被 uv 明确忽略，
事先执行的同型命令已断言实际 sys.prefix 为 source-tests venv；未改普通 .venv。

- Ruff、76 个 AI source files 的 Mypy、catalog、import boundaries 通过。
- 13 个 offline examples 通过；examples pytest 为 **61 passed，88.30 s**。
- AI/protocol/examples coverage pytest 为 **851 passed / 7 deselected，33.88 s**；
  总覆盖率 **90.63%**，细分 coverage targets 全通过，原 90% 门槛未变。
- Coverage XML 为 `.artifacts/ai/coverage.xml`；两个 pytest inventory 有重叠，不相加
  宣称唯一用例总数。未运行 live 请求。

随后按共享 `scripts/ci/run_checks.py coding` 的原命令执行 Coding offline gate，
exec 29506 已终态 exit 1；新根 `/var/tmp/lg18-tests-Ih1djp`，XML 为
`.artifacts/g18-baseline/coding-offline-after.xml`，SHA256 为
`82f05f63c5cbbad3986276294909d94fa6226f94b28e76224c9e830e579ffe7f`。
保留既有 Coding UI 分流及全部安全 selectors，结果为 **1 failed / 2424 passed /
21 skipped / 20 deselected，1467.14 s**。唯一失败是
`test_coding_portable_activation_bridge_rejects_replaced_temporary_file`，预期的
identity-changed OSError 未发生；不是超时。该门禁未通过，详见下文有界诊断。
其他 selected 本地门禁和性能工作仍待完成。

后续五组 Make 门禁使用 ignored 的 `.artifacts/g18-source-tests/Makefile`，仅将原
`.venv/bin/` 和 `--cache-dir .uv-cache` 两个字面路径替换为本任务的 source-tests venv
与 design/uv-cache；不修改公共 runner。逆转换整个文件后与源 Makefile `cmp` 完全一致。
`check-harness`、`check-hosting`、`check-apphost`、`check-appservice`、
`test-tui-render-contract` 的 dry-run 共 41 行，逆转换后与原命令逐字一致，没有删减
inventory、flags 或 deadline。这五组目标没有递归 MAKE/include/MAKEFILE_LIST 依赖。

合同视角已独立复核 SHA、逆转换与目标边界，通过且无 P1/P2；批准仅上述五组门禁。
每次执行前须核对以下两份 SHA，源文件变化则重建并重新验证：

- 源 Makefile：`d3e0a2b84fbed724c42dcb2e26ca43ae39bfe944cb3855ce61768a2e72157837`。
- 任务内副本：`29fb009ce7b644b0fa0461c77d3c2b9346e243401062abea652e9c624b3a73e4`。

执行 cwd 保持 checkout，显式设置 `UV_PROJECT_ENVIRONMENT` 指向 source-tests venv；
offline/no-sync 本身不选择环境。使用既有外部私有 HOME/data/runtime/tmp 和安全
selectors，不并行运行 native 测量。此批准不覆盖 bootstrap/build/install；
`check-apphost` 的 G10 console smoke 在 editable 安装下仅算 source-mode，不替代
不可变 wheel 的 installed/native 验收。这里记录的是命令等价审查，不是五组门禁已通过。

Foundation 原离线门禁 exec 65821 终态 exit 1：**104 passed / 1 failed，29.75 s**，
根 `/var/tmp/lg18-tests-VXairv`，失败 XML `foundation-offline-after.xml` 保留。
唯一失败是 `test_sweep_uses_quota_only_for_runs_with_provably_inactive_leases`：测试设置
1024 B 上限却预期只删除一个目录，实际删除两个、合计 8400 B。既有 `_tree_usage`
包含目录自身 st_size，因此原测试对目录大小的假设不可跨文件系统成立；不是调整
Product 配额或清理策略的理由。

仅修改 `tests/foundation/test_runtime_scope.py` 的这个测试：以独立 lstat 统计 flat
fixture 的实际用量，参数化数量/字节配额，每次使另一项非限制；保留最旧优先和
无有效 lease 的 legacy 保留断言，新增精确 removed_bytes、skipped=1、failed=0。
不调用被测私有计量函数生成期望值，不修改运行时。架构视角复审通过，无 P1/P2；
Ruff lint/format 通过。两项定向回归 exec 79904 exit 0，**2 passed，0.54 s**，
根 `/var/tmp/lg18-tests-YAjUhi`，XML `foundation-quota-after.xml`。

随后原完整 Foundation offline gate exec 30703 exit 0，**106 passed，29.31 s**，
根 `/var/tmp/lg18-tests-rcf7Q6`，XML `foundation-offline-after-02.xml`。前后相同私有
editable 环境、外部测试根和 offline/host-runtime selectors，原失败不追认。新增一项
参数用例使总数从 105 变为 106；定向与完整结果不相加计数。测试文件 SHA256 为
`7371e8f641cb82fa50671aebd9c8252cb52f3ff4555797463bdf9fcf7a39a6df`。
变更计划已刷新且仍为全 scopes；本测试不是 AI 等已通过 inventory 的共享 fixture，
不因测试输入修正重复这些未受影响的既有通过结果。Coding cleanup 范围确认仍 pending。

Agent 原 offline gate exec 1892 exit 0：**153 passed，2.20 s**，根
`/var/tmp/lg18-tests-aP6ORM`，XML `agent-offline-after.xml`；使用相同 source-tests
环境与原完整 offline/host-runtime selectors。

AppService 门禁 exec 4357 已终态 exit 0，根 `/var/tmp/lg18-tests-4zIDiL`，XML 为
`appservice-source-after.xml`。执行前再次核验上述两个 Makefile SHA，使用已复核的
任务副本与显式 UV_PROJECT_ENVIRONMENT/offline/no-sync。全部 Ruff 检查与 70 个源文件
的 Mypy 通过；原 AppService pytest inventory 连同新增 G18 tooling 为 **1520 passed /
15 skipped，712.19 s**。本轮没有并行 native 性能采样，不修改采集器或 Product；
skips 不充当平台通过。它是 source-mode 门禁结果，不替代 wheel/native 性能验收。

Hosting 原门禁 exec 48823 exit 0，根 `/var/tmp/lg18-tests-Q9gekQ`，XML
`hosting-source-after.xml`：Ruff 和 26 个源文件的 Mypy 通过，pytest 为 **383 passed /
48 skipped，150.34 s**。使用相同已核验 Make 副本和独立 source-tests 安装；skip 不计为
Windows/macOS 等外部平台通过。本轮未修改 Hosting 或其他 Product 清理代码。

### G18.1 Wave A Budget Regression And Corrective Design

HarnessTUI 原门禁 exec 26470 exit 1，根 `/var/tmp/lg18-tests-CBvx6k`，XML 为
`harnesstui-source-after.xml`：Ruff 及 131 个源文件的 Mypy 通过，pytest 为
**870 passed / 1 failed / 8 deselected，288.39 s**。唯一失败是
`test_coding_package_stays_within_wave_a_budget`：core 33,929 > 33,800。初版 facade
从基线 114 行增为 257 行（+143），其余 core 未增长；该失败确属 G18 的预算回归。

在修改 Product 前，三视角独立复核同文件的 196 行原型并通过，无 P1/P2：

- 架构：public → owner 加唯一 alias，继续保留原静态导入和 literal `__all__`；
  不为 LOC 新增业务责任、类型文件或安装边界。批准 facade 独立上限 200。
- 类型/安装/测量合同：48 项 owner/name、类型声明和 `__all__` 顺序不变；不新增
  `.pyi`、项目配置或包路径，原 A/B project/lock/package-path 校验无需放宽。
- public/生命周期：仅映射 KeyError 转为 AttributeError，真实 import/getattr 异常
  原样传播、失败不缓存；沿用原导入锁和 bootstrap 对象，不修改激活或清理路径。

预算按基线 `9bc69361494293595ae424be225c61e3226a9996` 明算：非 facade core
33,672，保留上限 33,686（33,800 − 原 facade 114）和原 14 行余量；精确根 facade
上限 200。总上限 **33,886，比旧上限明确增加 86 行**，G10–G17 名单/上限不变。
要求 executable singleton、互斥、完备和未知 `.py` 仍计 core 的门禁。方案与预算批准
不代替落码后的原 facade/SDK/activation 回归；原失败和此前通过结果均保留其真实范围。

先落实预算测试而不改 Product：exec 61102 exit 1，根 `/var/tmp/lg18-tests-N5S0DP`，
**1 failed / 1 passed，0.62 s**；`facade-budget-before.xml` 的 SHA256 为
`80d651b3e0bfb81046e62accb034d4df5a57f09f4f76318670ab835a7712b7a7`。
唯一失败明确为原 facade **257 > 200**，未知文件/嵌套 facade 的分区测试通过。
测试进程核验 source-tests sys.prefix、唯一 editable distribution 与
Coding/Foundation/bootstrap 的 checkout origin；原 offline/host-runtime selectors 保留。

随后将已获批 196 行原型逐字落入原 Product 文件，cmp、Ruff lint/format、diff whitespace
均通过。源码 SHA256 为
`d153befdc62a0fee11e9918e8c4ac6543153674a72b39cc7cbab1ab5144ca9ae`，预算测试 SHA256 为
`bddf842642d5ed3c41ec705c8ab90df0cb04ec4fedbc41311526a6cac2eaf489`。
三视角再次检查实际差异并通过，无 P1/P2；确认原 owner/别名/静态/异常/并发合同保持，
分区不存在 basename 或目录豁免。此结论关闭本修正的源码评审项，执行结果仍须另行记录。
原 lazy/SDK 测试未改，保留全部原失败负控及冷启动/类型/并发/pickle 回归。

修正后的正控 exec 52092 已终态 exit 0，根 `/var/tmp/lg18-tests-mpjWSw`，原四文件
（lazy facade、SDK、composition sets、bootstrap）加预算测试为 **129 passed，272.25 s**。
XML `facade-candidate-after-05.xml` 解析为 129 tests、0 failures/errors/skips，SHA256 为
`aea45f515edc75824ba919c3e8406a246dfbb9f30d8bee1f0e152856f87cc22a`。
同进程再次核验源码和独立 editable 安装，使用新外部私有根及原安全 selectors；不覆盖
前一版 127 项报告。修正前后正负控闭合，后续原 HarnessTUI 完整门禁仍须以新结果验收。

随后原 HarnessTUI 完整门禁 exec 53607 已终态 exit 0，根 `/var/tmp/lg18-tests-DCXbI2`：
Ruff 和 131 个源文件 Mypy 通过，pytest **872 passed / 8 deselected，297.23 s**。
XML `harnesstui-source-after-02.xml` 解析为 872 tests、0 failures/errors/skips，SHA256 为
`f19814a624adbf4d10dba41cbff69f9864751ecd0e52193e46769b48f8617f34`。
使用原 `scripts/ci/run_checks.py harnesstui` 的完整命令和 selectors，仅替换私有环境及
新报告位置；没有删减 inventory 或修改 deadline。新增一个分区测试，故原 871 项变为
872 项；与定向 129 项有重叠，不相加宣称唯一用例总数。原预算失败现已由实际完整门禁
闭合；其他尚未完成的门禁、cleanup 范围确认、安装态和性能验收仍保持 pending。

修正后的 TUI unit 原离线门禁 exec 43627 exit 0，根 `/var/tmp/lg18-tests-g9hpoR`，
**1252 passed / 118 deselected，29.12 s**。XML `tui_unit-source-after.xml` 解析为
1252 tests、0 failures/errors/skips，SHA256 为
`7318430874fc245763daf2eea54766cfc0989e30dc24bc1f44e9d5cad3a1e92b`。
执行 `scripts/ci/run_checks.py tui_unit`，保留原 offline/host-runtime/native/playback
selectors；此结果不替代被分流的真实终端或 deterministic playback 门禁。

### Coding UI Playback Private-Temp Correction

Coding UI 原门禁 exec 13353 exit 1，根 `/var/tmp/lg18-tests-M8kBFs`：Ruff 和 22 个
源文件 Mypy 通过，pytest 为 **570 passed / 2 failed / 59 deselected，104.06 s**。
`coding_ui-source-after.xml` 的 SHA256 为
`825bd89d78edb4260c3f873a71b7eb1aea5fdb441d7f2ecced0d97bf2b4ee33e`。失败分别是
`test_screen_tui_playback_runs_multiagent_topology_matrix`（第八个场景 false）和
`test_screen_tui_playback_runner_writes_artifacts_for_all_default_scenarios`（exit 1）。
原断言不显示场景错误；pytest 正常终态时已按原 lease 清理 scratch，不能声称读取了
这些已清理场景的现场产物。

只给两个断言增加失败场景 name/error 及 CLI captured output，不改成功条件；随后
定向诊断 exec 66293 exit 1，根 `/var/tmp/lg18-tests-JI6SRx`，**2 failed，9.34 s**。
两项均显示 `multiagent-isolated-artifact` 在 `git init` 复制系统 Git 模板到
`/tmp/loushang-isolated-artifact-*/repo/.git/hooks/fsmonitor-watchman.sample` 时出现
`Disk quota exceeded`。`coding-ui-playback-diagnostic.xml` 的 SHA256 为
`aacf2dbac3dc995f8aa75479e7af419e7563d6c0eef1a1da32b207fa1fb36f08`。
这是独立诊断，不把诊断详细错误追写成原门禁已记录的信息。

`tests/coding/tui_support/scenarios/multiagent.py` 五处 `TemporaryDirectory(dir="/tmp")`
绕过标准 tempfile 选定的私有根。这里只承载文件、Git repo/worktree 和模拟审批，没有
固定 `/tmp` 或 Unix socket 短路径要求。三视角批准窄修正，并复审实际代码通过，无 P1/P2：

- fixture 仅删除五处显式 `dir`，保留 prefix、真实私有目录和 context 清理；不改
  Product/worktree、spawn/await/dispose、apply/discard、超时或配额，也不清共享 `/tmp`。
- 新五参数回归覆盖对应全部场景，以 monkeypatch 暂设字符串 `tempfile.tempdir`，
  包装场景绑定的真实 `TemporaryDirectory` 并原样转发参数。在 context 内验证实际父
  路径、成功返回后检查唯一目录已消失；不注入替代 dir、不增加兜底删除。
- 此回归证明不绕过 tempfile 选定根，不冒称测试了 TMPDIR 环境解析或其缓存刷新规则。

Regression-first 结果（每次独立 source-tests 环境/新外部根，原安全 selectors）：

| 阶段 | 终态、结果 | 根 / XML |
| --- | --- | --- |
| fixture 未修，五项路径负控 | exec 42036 exit 1；5 failed，2.52 s；全部因实际父路径 `/tmp` 不符，不是 quota 错误 | `/var/tmp/lg18-tests-dF2uM6` / `coding-ui-private-temp-before.xml` |
| 删除硬编码，五项正控及原两项失败 | exec 98630 exit 0；7 passed，10.92 s | `/var/tmp/lg18-tests-9iKABc` / `coding-ui-private-temp-after.xml` |

两份 XML 的 SHA256 分别为
`d90ce8dca8162fc2596414d662913636801667cc8243ac144769facee9f58935`、
`16db3125041f2e7e44e62ebca128db605e0c179ead6142077844cde19dff166d`。
修正后的 fixture SHA256 为
`56dc1e9223a1297541d5573396f3c021022bcca3498380878f660d0bb15e1938`，runner test 为
`0699a3b45d24a9d73a472e7036dfa049d4af18128c77ceb677c08cc81decf7d0`。
Ruff/diff 检查通过；原完整 Coding UI 门禁仍须以新结果验收。这个测试隔离修正不代表
性能收益、全机 quota 恢复或待用户授权的 Product cleanup P1 已解决。

随后完整 Coding UI 门禁 exec 40764 已终态 exit 0，根 `/var/tmp/lg18-tests-Ys5b3I`：
Ruff、22 个源文件 Mypy 通过，pytest **577 passed / 59 deselected，107.12 s**。
`coding_ui-source-after-02.xml` 解析为 577 tests、0 failures/errors/skips，SHA256 为
`b1f8b86a49a539c74e26c169de5d7c1d305906b694e95f4c28ff34f74ed378df`。
原完整 inventory/selectors 不变，五个新增参数使原 572 项变为 577 项；不与七项定向
回归相加计数。源码检查确认 HarnessTUI/TUI unit 已通过 inventory 不调用修改的
multiagent 场景或 Coding playback runner，故这次纯 fixture 修正不重复其独立通过结果。

独立分流的 deterministic playback 门禁 exec 88459 exit 0，根
`/var/tmp/lg18-tests-3XVZcT`：原 `test-tui-render-contract` 为 **179 passed / 4909 deselected，
27.62 s**，XML `tui-playback-source-after.xml`。使用既有已核验等价的私有 Make 副本；
执行前后两份 Makefile SHA 均与已批准值相同，没有删减 selector/inventory。这只验
deterministic playback，不代替真实 PTY/native、installed 或性能结果。

本修正收口后仍未提交、推送或合并。未执行的 Harness/AppHost 门禁、最终 facade 的
受影响 AppService 消费者验证及 Linux host/native/installed 证据继续待办；已复现的
Coding cleanup P1 仍须用户独立授权。稳定 native A/A、不可变候选与配对性能验收未完成，
goal 继续 active，不将上述 source-mode 绿灯解释为完整交付。

### Final Candidate AppService Coverage Plan

原完整 Harness 门禁 exec 74690 已返回 **exit 0**（根 `/var/tmp/lg18-tests-E87AJu`）：
Ruff 通过，681 个源文件 Mypy 通过，pytest 最终打印
**4,488 passed、66 skipped，2,446.29 秒**。生成的
`harness-source-after.xml` 可完整解析：4,554 个 testcase，0 failures、0 errors、
66 skipped（即 4,488 passed），报告时间 2,444.317 秒；SHA256 为
`a35119f5f8f9c27270109319707322a85545a2973527a9646ef4ef8bb3e19248`。
报告本身只证明用例结果；另已观察到本次 leased scratch 目录被清理，且原执行句柄
成功退出。结束后 XML、196 行 facade、预算测试和原/私有 Makefile 的 SHA 均复核未变。
逐项核对 66 个 skipped 的 reason，均为 Windows 专属合同/宿主语义；不宣称 Windows
已验收，也没有将 Linux 环境不足的跳过计作通过。

以下为终态之前的慢尾取证，不再表示进程仍在运行。sandbox 外只读检查确认
PID 2874416 当时仍活着，elapsed 52:05、
CPU 16:17、D 状态、单线程、VmSwap 878,044 KiB、read_bytes 70,483,955,712，
wchan 为 `folio_wait_bit_common`。较早约 37:40 的 read_bytes 为 46,683,422,720，
累计读取继续增加；当时主机约 1.6 GiB 内存、进程 VmSwap 约 1.16 GiB，系统内存和
I/O pressure 较高。这里的累计读取包含内核记账的 I/O，不能等同于源码文件读取量，
也不能据此定位 Python 栈或认定唯一根因。sandbox 内 PID 不可见是隔离边界，不是
进程已退出的证据。elapsed 60:05 时普通读取 rchar 相比 52:05 仅增加 16 字节，
read_bytes 却从 70,483,955,712 增至 83,134,054,400，CPU 从 16:17 增至 17:29，
wchan 仍为 `folio_wait_bit_common`；这更支持换页参与收尾迟缓，但不定位具体 Python
对象或唯一根因。整个门禁没有重启、信号、追踪或 deadline 变更。

合同视角另做静态审计：本 inventory 中 PR0 `_python_trees()` 和 CLA0
`_source_trees()` 各自用 `@cache` 保留整个 `src/loushang` 的 AST，当前各覆盖
1,291 个 Python 文件，没有 module teardown/cache_clear；两者执行后形成两份独立
的进程期保留集合。CLA0 `_tracked_call_sites()` 仅保留路径/作用域字符串计数，
不是第三套 AST。这是结构性重复保留风险，不是已经证明的无限泄漏或当前慢尾根因。
JUnit 中 CLA0 construction-site 检查为 195.257 秒，后续多项全源码扫描为
128–340 秒；保留为诊断线索，不据此更改测试清单、缓存生命周期或正式性能样本。
合同视角只读确认可考虑未来按模块释放这些测试缓存；本轮未实施，不计作性能优化。
Harness 成功终态已满足下面组合覆盖计划的一个前提，不等于 AppService 已完整覆盖。

随后原 AppHost 门禁命令 exec **63272** 已 **exit 0**，根 `/var/tmp/lg18-tests-1nrcil`；
启动前确认四个预期 XML 均不存在、source shadow egg-info 不存在，原/私有 Makefile
hash preflight 通过。沿用独立 editable source-tests 环境和原 leased runner，保留
G8/G9/G10 子门禁、XML/manifest 验证器及 G10 canary，全部成功退出。Ruff 通过，
Mypy 83 个源文件通过，主测试 **1,111 passed、11 skipped，805.04 秒**。
11 个 skips 分别为实际 Windows venv/Job admission（1）和 Windows security handles（10）。

| 报告 | 实际测试结果 | SHA256 |
| --- | --- | --- |
| `g18-baseline/apphost-source-after.xml` | 1,111 passed / 11 skipped | `f966344f470f76a31da12488213ceb72a3527ca69d70ebd81d92d195d43e6110` |
| `hosted-product-g8.xml` | 19 passed，1.12 秒 | `d7de48a248e4f2bb2fe00aca569a58a6502fbe4065d90c675b2fa90c1515cf4a` |
| `hosted-product-g9-linux.xml` | 16 passed，2.21 秒 | `cc41a97db599c70014cc698a8c797c39e4917c1d8ac2ddc967eb4743c7eff34c` |
| `hosted-product-g10-linux.xml` | 15 passed / 12 deselected，20.87 秒 | `f0c16dbde0fcf97051eefa8047043b7a9f0466a6266deef1000fc49ce9e403a0` |

四份报告均位于 checkout 的 `.artifacts/` 下，已完整解析且无 failures/errors；
G8/G9/G10 原 XML 及精确 manifest 验证器均通过。最后的 G10 canary 输出
`backend=posix-process-group-v1` 并成功退出。这里使用独立 editable source-tests 安装，
不能将脚本名称中的 installed 当作不可变 wheel 或正式性能样本验收。子门禁和主门禁
有重叠，不相加宣称唯一用例总数。后续实际覆盖审计发现该命令遗漏 11 个 AppHost
模块；上述命令终态和已执行用例仍为真实历史结果，不能称为完整 AppHost inventory
验收，详见下方收集修正。

为保留修正前证据，旧 G8/G9/G10 三份 XML 已复制至
`.artifacts/g18-baseline/apphost-before-collection-fix/`，文件名不变，复制件与原件 SHA
均匹配上表。修正后的完整 Make 门禁仍须写原 manifest 要求的标准路径；新运行开始后，
上表三份历史 SHA 应到保留目录取证。旧 `apphost-source-after.xml` 保持原位不覆盖。

当时基于两个命令的成功终态，随后启动下面的 15 文件精确补集 exec **56383**，
新根 `/var/tmp/lg18-tests-lS1idK`，报告为
`.artifacts/g18-baseline/appservice-complement-source-after.xml`。启动前原/私有 Makefile
hash preflight 通过，确认输出不存在、无 source shadow egg-info；沿用同一 source-tests
安装、原 runner 和原选择条件。补集已 **exit 0：472 passed、4 skipped，82.99 秒**，
XML SHA256 为 `ed1e8294885d8b5b01849a74c12773a1dc5705740c72601cf4e8fe994e6831cb`。
4 个 skips 的 reason 均为 per-operation installation gates 属于 slot mode；
不将它们算作实际安装态验收。补集本身通过，但 AppHost 实际收集前提被下述审计否定，
因此仍不能报告 AppService 组合覆盖完成。

196 行 facade 修正之后，原 257 行版本的 AppService 通过结果不能无条件作为最终
消费者验收。合同视角对当前 Makefile 的目录 inventory 做只读静态展开：AppService
共 102 个 `test_*.py` 文件；AppHost 覆盖其中 84 个，完整 Harness 另外覆盖 3 个
transcript 文件。接受以下组合覆盖计划，无 P1/P2；它保留原文件清单，不依赖
“导出表压缩语义等价”来省略消费者回归：

1. 本次完整 Harness 和完整 AppHost 门禁必须都达到成功终态，并以实际 JUnit/node IDs
   核对完整应执行范围；命令成功退出不是覆盖完整的充分条件。
2. 随后以相同独立 source-tests 安装、原 leased runner 和原 selectors（仅 `-q`，
   不增加 `-k`/`-m` 过滤）执行以下文件级精确补集：

```text
tests/coding/test_hosted_discovery.py
tests/coding/test_hosted_discovery_workflow.py
tests/dev/test_g18_bytecode.py
tests/dev/test_g18_comparison.py
tests/dev/test_g18_provenance.py
tests/dev/test_g18_recovery.py
tests/dev/test_g18_slot.py
tests/dev/test_measure_g18_native.py
tests/dev/test_measure_g18_startup.py
tests/architecture/test_detachable_local_workspace_g16.py
tests/architecture/test_detachable_local_workspace_g16_design.py
tests/architecture/test_foreground_hosted_tui_g15_design.py
tests/architecture/test_foreground_stdio_hosted_app_g14.py
tests/architecture/test_foreground_stdio_hosted_app_g14_design.py
tests/architecture/test_hosted_session_workflow_g17_design.py
```

Discovery 两文件实际消费 Coding catalog/Session，native collector 测试导入真实
probe 并创建 Session；G14/G17 架构测试读取 facade，G16 测试导入 bootstrap/CLI。
不因它们名字与 AppHost 中的测试相似而省略。其余 helper/文档项也保留在补集内，
不继续做依赖推断裁剪。

静态源码范围上，`APPHOST_SOURCES ∪ HARNESS_SOURCES` 完整包含 `APPSERVICE_SOURCES`；
原 AppService 专属工具 lint 输入未变，可复用已通过结果。只有上述所有终态和实际
source identity 齐备，才能报告“组合覆盖原 AppService inventory”；不能写成重新
运行并通过 `check-appservice`。条件不满足则该范围仍 pending，或重跑原门禁。

### AppHost Collection Coverage Correction — P2

最终按 XML classname 核对实际执行文件，而不是只展开 Make 路径，发现原 AppHost
102 文件 inventory 中仅 91 个模块有记录；`tests/apphost` 下只有 launcher 的 49 项，
其他 11 个文件没有执行。Harness 的 414 个 inventory 文件均有实际记录。AppService
在原 15 文件补集通过后，仍缺六个必需模块：application、client_scopes、continuity、
foreground、foreground_discovery、local；旧 257 行候选的 AppService 报告曾执行这些
模块，但不能充当最终 facade 的覆盖证明。

独立环境中的真实 collect-only 对照均成功退出，但不算测试通过：

- 原 `tests/apphost/test_launcher.py tests/apphost`：exec 82928，根
  `/var/tmp/lg18-tests-LBrz7O`，只收集 49 个 launcher node IDs，0.28 秒。
- 仅 `tests/apphost`：exec 76729，根 `/var/tmp/lg18-tests-wksTnH`，收集全部
  12 个模块、194 个 node IDs，1.46 秒。

合同视角读取实际 pytest 8.4.2 收集实现，确认显式子文件与父目录重复入口会使已缓存的
目录 collector 被跳过；仅交换排列也不能作为修复。仓库 collection hook 只对指定的
G17 installed selector 做精确分流，不过滤 AppHost，leased runner 原样传入测试路径。
该问题是门禁覆盖 P2，不是 Product facade 或清理语义故障。

三视角批准并已实施最小修正：只移除 `APPHOST_TEST_PATHS` 中冗余 launcher 单文件，
保留一次完整 `tests/apphost`；AppService 的 launcher 条目保留，因为其 inventory
没有该整个目录。新增三项 CI 静态回归，检查真实 AppHost 清单无路径重叠、双向排列
均被拒绝且相似字符串前缀不误报，以及全部 AppHost 模块和显式 AppService 消费者
路由保持。旧 Make 上先 **1 failed / 2 passed**，失败明确指出 launcher/父目录重叠；
修正后 **3 passed**，Ruff 与 diff 检查通过。三视角实际代码复审无 P1/P2。

修正后的源 Makefile SHA 为
`c8225af1ee2496017d73b96eadd21f0df80e4b71d4a6089d2d76ca50da03089a`，私有副本为
`6528c29dd47661e0cbf83e51c5a326a28c8fcefc2e24a5f3690698f14d78d310`；副本继续逐字
等于源文件的两项既定路径替换。没有改变 Product、selectors、超时、validator 或
cleanup P1 的范围。修正后的五目标 dry-run 继续严格两替换等价（当前 40 行输出）。
完整 `tests/ci` 在新私有根 `/var/tmp/lg18-tests-ezIf8X` 执行，exec 56459 **exit 0：
46 tests passed，0.962 秒**。其中 printed failure/cancelled/skipped 为 verifier 的
故意负控输入，不是远程任务状态；没有执行远程门禁。

遗漏 11 个完整文件已使用同一 source-tests 环境、原 runner、仅 `-q` 实际执行：
exec 98787 **exit 0：144 passed、1 skipped，2.96 秒**，根
`/var/tmp/lg18-tests-U7ieuC`。XML `apphost-missing-modules-after.xml` 的 SHA 为
`d7efddfece98bdc4cb2adc819022d0e3724c5f09064e2b04d41a62ff8c2194ce`；145 个 node IDs
无重复，11 个预期模块均有记录，唯一 skip 为 native Windows fail-closed gate。
旧 AppHost 报告的 1,122 个 node IDs 与本次 145 个互不重叠；修正后完整范围应核对
这 1,267 个 ID 的实际合并执行，而不只核对测试总数或目录清单。

随后启动修正后的完整 AppHost 门禁 exec **94898**，新根
`/var/tmp/lg18-tests-dD4fDU`，主报告 `apphost-source-after-02.xml`；启动前已核验旧
G8/G9/G10 原件及保留件、新 Make pins 和输出不存在。原 lint/typecheck、G8/G9/G10
测试、XML/manifest 验证器及 canary 全部保留。该执行仍在运行；完整顺序下的 AppHost
和最终组合覆盖尚未验收，不将单独补跑、静态绿灯或 collect-only 追认为完整通过。

### Corrected AppHost And Final AppService Coverage — Source Gates Accepted

上述完整 AppHost exec **94898** 随后自然返回 **exit 0**。Ruff、83 个源文件的 Mypy
通过，主测试 **1,255 passed、12 skipped，830.61 秒**。完整 XML 实际记录的
1,267 个唯一 `(classname, name)` 与旧 1,122 个及遗漏 145 个 ID 的并集精确一致，
所有 102 个 inventory 测试模块均有记录，收集缺口关闭。12 个 skips 分别为实际
Windows venv/Job admission（1）、native Windows fail-closed（1）和 Windows
security handles（10）；不是 Windows 平台验收。

| 报告（相对 `.artifacts/`） | 实际结果 | SHA256 |
| --- | --- | --- |
| `g18-baseline/apphost-source-after-02.xml` | 1,255 passed / 12 skipped | `f56041099123d37e579dd20a973251525c425928528d15f27d9bc52f1525ed08` |
| `hosted-product-g8.xml` | 19 passed，1.17 秒 | `72b09d961931b96fef59e07267c23c32eb58321becd3f15ef4c134b189581dc1` |
| `hosted-product-g9-linux.xml` | 16 passed，2.39 秒 | `f09c9b0c58e816640398767accbe9fd7144231d5b8bf1f1d1bebc3c4c444a164` |
| `hosted-product-g10-linux.xml` | 15 passed / 12 deselected，22.20 秒 | `89eb84d0a320e0817377fd2a8e29a901e564f8231953ee466017879002871772` |

G8/G9/G10 的原 XML/manifest 验证器均通过；最后 G10 canary 输出
`backend=posix-process-group-v1` 后成功退出。结束时 source、Make 和 CI 测试的 pins
未变。本段是完整 editable source-tests 门禁证据，仍不替代不可变 wheel 或性能验收。

随后在最终 Make/CI 清单下重跑同一 15 文件补集，exec **93880**，新根
`/var/tmp/lg18-tests-laEiNg`，自然 **exit 0：472 passed、4 skipped，88.95 秒**。
沿用原 runner、仅 `-q` 和同一 source-tests 安装；报告
`g18-baseline/appservice-complement-source-after-02.xml` 的 SHA256 为
`bc5ea9fd0f6d4f357ffcf81b3e015460aa3e60b050d13a3cf1d2bb1a1b16057c`。
4 个 skips 仍是 per-operation installation gates 属于 slot mode，不能充当安装态通过。
第一次补集报告原样保留，不覆盖历史证据。

最终组合审计逐项解析完整 Harness、修正后的 AppHost 和最终补集 XML，检查各份
报告无重复 ID、无 failures/errors；Harness 的 414 个与 AppHost 的 102 个 inventory
模块均有实际记录。按当前 `APPSERVICE_TEST_PATHS` 的 102 个模块取并集、去重后，
得到 **1,535 个唯一用例：1,520 passed、15 skipped**。这组 `(classname, name)`
与原完整 AppService 报告的预期 ID 清单精确相等，没有遗漏或新增 ID；旧报告仅用作
预期清单，不复用旧 facade 的通过结论。15 个 skips 为 Windows venv/Job（1）、
Windows security handles（10）、slot-mode installation（4）。

结合前述静态检查输入覆盖及未变输入，接受“组合覆盖原 AppService inventory”；
不写成重新运行 `check-appservice`，不把重叠测试的次数相加。剩余 Linux
host/native/installed、稳定 native A/A 和配对性能验收继续待办；独立 cleanup P1
仍待用户授权。本轮尚未提交、推送或合并。

### Linux Host And Native Source Gates — Follow-up Acceptance

AppHost/组合覆盖收口后串行运行下列既有 Linux 门禁，均自然 **exit 0**。每组使用
source-tests 的同一解释器/依赖与新私有根、原 leased runner；启动前检查报告不存在和
Make pins，未覆盖旧报告、未同时运行构建或性能采集，也没有修改 Product/采集器。

| 门禁 / exec | 实际结果（pytest 输出） | 私有根 |
| --- | --- | --- |
| host-runtime / 6338 | 13 passed、2 skipped、13,106 deselected；56.52 秒 | `/var/tmp/lg18-tests-tVIPcE` |
| terminal platform shared / 93466 | 103 passed；15.96 秒 | `/var/tmp/lg18-tests-F8dgwz` |
| terminal platform POSIX / 93466 | 7 passed；0.72 秒 | `/var/tmp/lg18-tests-vBl1jV` |
| native terminal POSIX PTY / 25638 | 12 passed；17.03 秒 | `/var/tmp/lg18-tests-mIXNdJ` |
| required tmux / 25638 | 3 passed；12.37 秒 | `/var/tmp/lg18-tests-jJaTy6` |
| PLC9B Linux native / 24516 | 124 passed；22.29 秒 | `/var/tmp/lg18-tests-d1Pbyj` |
| PLC9C5 C5.1 / 24516 | 72 passed；1.26 秒 | `/var/tmp/lg18-tests-tlrPNh` |
| PLC9C5 C5.2 Linux / 24516 | 27 passed；2.96 秒 | `/var/tmp/lg18-tests-B7XN5M` |
| PLC9C5 C5.4 Linux Product / 24516 | 28 passed；1.73 秒 | `/var/tmp/lg18-tests-N2ILHZ` |
| G16 native Linux / 6799 | 29 passed；2.02 秒 | `/var/tmp/lg18-tests-ZPbd2U` |

host-runtime 用当前 `select_checks.select([], full=True)` 的全部 21 scopes 生成
`CI_PLAN`，原 `run_checks.py host_runtime` 实际执行 `tests -m "requires_host_runtime
and not live" -q`，没有加 `--skip-host-runtime`。两个 skips 分别是 Windows ConPTY
CLI/native 合同；没有跳过 Linux 宿主不足项。terminal platform 的原严格 markers/config
及零跳过 XML 校验保留；native 设置 `LOUSHANG_REQUIRED_TERMINAL_BACKEND=posix-pty`
并通过原后端属性校验。tmux 设置 `LOUSHANG_REQUIRE_TMUX=1` 并通过零跳过校验。

PLC9B/C5 沿用原四个测试文件、`faulthandler_timeout=60`、固定报告路径和原验证器；
C5.1/C5.2/C5.4 的精确 case ID manifest 全部通过。不拿完整 Harness 的有跳过大报告
过滤成这些专用证据。使用已有 `/usr/bin/bwrap` 与 `/usr/bin/tmux`，没有安装软件、
执行 sysctl 或改变宿主安全配置。G16 使用原 `test_mux_native_evidence.py`、`-m "not
live"` 和 `G16-NATIVE-LINUX` manifest，平台属性、精确 ID、零跳过均通过。

| 报告（相对 `.artifacts/`） | SHA256 |
| --- | --- |
| `g18-baseline/host-runtime-source-after.xml` | `a7219aa8efeaba7f5d82713519e784d32f012e214efa645f0bc732d455787a86` |
| `g18-baseline/terminal-platform-shared-source-after.xml` | `cfa16c510825b4fa262c5fb5be44520c02da2f8cad9d001eebb0fc70f28fe8ff` |
| `g18-baseline/terminal-platform-posix-source-after.xml` | `29a6f6dd1ff53f6b5462d63f6e258dec710b4edb71ee796a2704aaa7279c9b82` |
| `g18-baseline/native-terminal-source-after.xml` | `5f79f0e213b1b7185a9c18b892d4b97b91fe6684511e03142d33c03d544d96e0` |
| `g18-baseline/tmux-scrollback-source-after.xml` | `4a269f0fdc58c0ce8435b614337aff331a2b468a238e90ff5b476dd85e71541c` |
| `plc9b-linux-native.xml` | `f54bbc7a647e5ce2709c05034b6c70a52ebf2b6c9a0451d2b217f82350c9ed86` |
| `plc9c5-c51-contract.xml` | `8625ca13b6e3c00c0ff158b98dd7ad901e326c6cdf4825ac061d3b469a49ae2d` |
| `plc9c5-c52-linux-native.xml` | `66dba20c89a6ddf9a9a5664008821ce6118dbbaff564ad3ad49dd8b1d36699ac` |
| `plc9c5-c54-linux-product.xml` | `f5c44bbc6885a4fcac86e7ea8ca3fdbb4f09ed0b68f0c07d18d78b4e36e089e7` |
| `g16-native-linux.xml` | `7073448a2a91040ab44a4577d21d898a2c7ec762f530a543fdd99466e648de90` |

这些是源码功能/本机 native 证据，存在用例重叠，不相加当作唯一测试数，也不替代
G16/G17 wheel 安装态或 G18 稳定 A/A、配对性能验收。macOS/Windows 仍待外部机器。

### Linux Install Compatibility And Selected Live Boundary

G16 native 终态后，在全新的 `.artifacts/g18-install-compat/venv` 执行原 Linux
install-compatibility 安装要求，exec cell **4267** 自然返回 exit 0，私有根
`/var/tmp/lg18-tests-P01qVn`。实际命令保留 `uv sync --locked --no-build-package
cryptography`，仅追加 `--offline`、显式同版 Python 和独立环境/cache：

```text
UV_PROJECT_ENVIRONMENT=<checkout>/.artifacts/g18-install-compat/venv
UV_PYTHON_DOWNLOADS=never
uv --cache-dir <checkout>/.artifacts/g18-design/uv-cache sync
  --offline --locked --no-build-package cryptography
  --python <checkout>/.artifacts/g18-source-tests/venv/bin/python
```

命令在前述 env allowlist/私有根内执行，解析 43 个 lock 条目，实际安装 30 个包。
随后 `uv pip check --python .artifacts/g18-install-compat/venv/bin/python` 检查 30 包
全部兼容；进程断言 Linux/x86_64、CPython 3.11.15 和精确 sys.prefix。
`cryptography==48.0.1` 的 WHEEL tag 是 `cp311-abi3-manylinux_2_34_x86_64`，没有从源码
构建它。Loushang 的 direct_url 指向当前 checkout 且 editable=true，符合此 sync
门禁，但不算 G18 不可变 wheel 安装验收。原 venv/基线安装未改，没有网络/下载；
结束时没有 source shadow egg-info，uv.lock、196 行 facade、continuity.py 的原 pins 均保持。

当前 Make/CI 基础设施修改仍选择全部 21 scopes，没有为本地结果缩小远程清单。
只读检查 `.github/workflows/coding-lsp-compatibility.yml` 及四个 integration 文件，
确认 Pyright、TypeScript、gopls、rust-analyzer 用例均显式标为 `pytest.mark.live`，
工作流另安装固定版本工具链。本轮不越过既有 not-live 边界，不运行它们、不安装或
切换全局工具链，状态为未执行，不能称为通过。后续授权的 live/远程验收仍需保留。

### First Local Atomic Commits — Test Infrastructure Only

所有当前测试终态后，复核已评审文件 SHA 与对应完整门禁 XML，再作两个本地原子提交：

- `7fc472c2708428eabdebcda5a9aa9176e0812809`：仅 Foundation quota fixture；完整 offline
  106 项通过，运行时不变。完整 XML SHA256
  `629f990884b660a4d84f39755551a127fc93abc2b71b59dae7736a41ed0f36b1`。
- `179edf3927969787e2d80e57659b7ea45845ae86`：仅 Coding playback 的五处私有临时根及
  测试/失败诊断；三视角评审与完整 Coding UI 577 项通过，原 59 deselected 保留。

两提交均 `Refs #578`，没有 Product、依赖/lock 或生命周期改动；没有 push/merge。
G16 native 门禁在这两个提交后执行，其余上述新门禁在提交前完成，文件内容未因此改变。
原 G18 baseline 仍是 `9bc69361`，不把这两个测试修正当成不可变优化候选。
G18 tooling/facade 仍未提交，独立 cleanup P1 待用户授权，稳定基线/安装态/性能仍未验收，
goal 保持 active。

### Warm A/A Attribution Review — Diagnostic Hypotheses Only

合同视角对原 `native-fixed-warm-aa-disk-02/report.json`、durable projection 和既有
等待代码做有界只读归因复核；没有重跑样本、编辑 helpers 或提出阈值调整。11 项仍全部
inconclusive，其中四组 median span 全部超界、七项同时 MAD 超界。未发现新的 P1/P2，
但这不是统计通过或原因已确定。

- Global ready/history 的 40 点相关系数约 0.999838；逐样本 history-ready 的四组
  median 约 20–24 ms。这两个累计指标主要反映同一段 spawn→ready 波动，不能当成
  两个独立慢点。A 的 block 1 比 block 0 快约 509 ms，B 则慢约 395 ms；Product
  dev-attach 的 A 在两块均比 B 慢约 295/320 ms。不存在所有场景统一变慢的块效应，
  side/block 差异仍只是描述，不能单凭 load average 归因 CPU、I/O 或缓存。
- 多项 PTY settlement 原始值有约 50 ms 梯级；原 PosixPtyDriver.wait 使用 CPython
  3.11 的 Popen.wait(timeout)，其轮询 sleep 上限为 50 ms，Product poll/render 也有
  50 ms 节拍。但 read_until 收到输出立即 notify，不强制等待 50 ms；不经 PTY wait
  的 G14 settlement 同样不确定。因此不能用一个轮询解释全部 11 项，也不能扣除
  假设的观察开销。

下一步仅有两个待验证假设，需在全部本任务测试/构建停止后单列诊断，不充当正式样本：

1. 启动段的 side/block 位移：保留原锚点，辅助观察 first-output、ready、对应进程
   CPU/调度及压力，区分变化是否发生于 ready 前、是否跟随 side 或执行时段。
2. 短交互/settlement 的节拍影响：记录原等待调用、输出到达与 reader 收口的边界，
   以 G14 为非 PTY 对照；只有实际退出/输出无梯级而等待返回有梯级，才支持观察量化
   解释。不替换等待实现、不改变 Product 生命周期、不移动锚点或重算旧结果。

本节记录诊断方向，不表示新增观测已实现或执行，不授权 retry-until-green。

### Bounded Settlement Diagnostic — Controls And Review Accepted

随后在 ignored `.artifacts/g18-diagnostics/` 实现独立诊断，不修改 Product、正式
collector 或原 probe。固定交替执行 foreground、G14 stdio 各四次，首次失败即停止；
保留原 owner、150 s 外层 deadline、ready/cleanup/assertions。使用同一 immutable
baseline install-a 与 observer，新的共享外部 bytecode cache 按每次现场状态记录，
不冒充正式 warm/absent 条件，也不绕过正式 collector 的 clean-source 要求。

hooks 仅在原调用发生时记录 wait、原 `_try_wait` 返回、输出/reader 通知、idle、close
及原 mark 的时点，不增加轮询、waitpid、信号、线程或 owner。每个 trace 最多 2048
事件、1 MiB；记录故障 sticky 标记失败，但不得跳过/重复原调用或替换原返回、异常、
取消。validator 必须核对原 PID、成对事件、必需阶段和原 settlement 锚点，原 owner
成功及原 observation 校验仍是前置。reader 通知不等于线程退出，原断言不能被 trace
替代。仅完整八次及安装/helper/self 前后 pins 一致才是完成的诊断证据。

回归过程保留全部结果：初轮 artifact 测试导入路径缺口 16 passed / 4 failed，补仅
测试作用域的 checkout-root 后 20 passed；记录透明性及 metadata/load-after 故障
负控先得到 28 failed / 20 passed，修复后新增事件校验负控先得到 6 failed / 49
passed。最终原私有 test runner（exec 44594，`/var/tmp/lg18-tests-LyErck`）终态
exit 0，**55 passed in 1.08 s**。单元测试中打印的八次完成来自 mock coordinator，
不是实际 native 观测。

架构、合同、生命周期三视角最终源码复审通过，记录透明性、缺失事件误接受和次级
错误掩盖原错误的 P2 均关闭；批准仅限诊断工具，尚不代表真实运行或正式性能验收。
冻结以下文件后才启动唯一预定系列，运行期间不并行本任务测试/构建或修改测量代码：

| Artifact | SHA256 |
| --- | --- |
| run_settlement_diagnostic.py | `c43f80455e184618fc3aef7786d162e89e6472cc1ee18dcf914d42cf7539feb6` |
| settlement_trace.py | `97b612515289d8864ac03cee3e290d8d7fb127c2fa0712bd0e3289985139ded4` |
| test_settlement_trace.py | `b013c7088cc9b217a4c0c8d550a92e1334a7e1b51c18ff11f14759fa4146f5ec` |
| settlement-diagnostic-controls-03.xml | `fad3387a7a9aacc8d9d998c8d25514fef469db28ad0eca1506823dc9ed2de22c` |

trace 本身会扰动调度；原 `_try_wait` 只能约束两次观察之间的退出窗口，不能给出精确
退出时刻或可从旧指标中扣除的“轮询税”。旧 warm A/A 的 11 项 inconclusive 和 absent
失败不因此改变。以下真实结果另行记录，不按成功补采或覆盖失败。

### Bounded Settlement Diagnostic — Eight Original Observations Completed

exec **30276** 终态 exit 0；controller 私有根 `/var/tmp/lg18-tests-YKWcfB`，原观察
根 `/var/tmp/lg18-observe-jgtr_csw`。唯一预定系列的八次原 owner 均成功返回、原观察
及 trace 校验通过，未补采。原报告
`.artifacts/g18-baseline/settlement-boundaries-diagnostic-01/diagnostic.json` SHA256
为 `8592d6893a46618b8e0664d0ff573e5f77a9597bb21fc82ac09f0dff139e27d1`。最终复核
measured/observer 安装前后一致，1200 个原 helper 与三个诊断文件前后 pins 完全一致。
状态为 `diagnostic-complete`、`formal_accepted=false`，不是性能 baseline accepted。

以下单位均为 ms；行号是实际交替运行的 1-based 次序。wait 为原 Popen.wait 或 G14
asyncio Process.wait 的单次区间，不将嵌套区间相加。idle 为 settlement 内两次原
idle-output 调用之和；close 含自身嵌套 idle，因此也不能再次相加作为分段总和。

| 次序 / 场景 | 原 settlement | 原 wait 区间 | idle 合计 | process-table | close |
| --- | ---: | ---: | ---: | ---: | ---: |
| 1 foreground | 1943.853 | 1925.305 | 0.029 | 16.310 | 0.606 |
| 2 G14 stdio | 488.845 | 488.036 | — | — | — |
| 3 foreground | 2157.616 | 2135.892 | 0.030 | 20.104 | 0.117 |
| 4 G14 stdio | 493.373 | 492.666 | — | — | — |
| 5 foreground | 1748.871 | 1724.452 | 0.038 | 21.803 | 0.176 |
| 6 G14 stdio | 482.856 | 481.858 | — | — | — |
| 7 foreground | 1450.203 | 1423.526 | 0.032 | 24.635 | 0.295 |
| 8 G14 stdio | 478.864 | 476.817 | — | — | — |

foreground trace 分别 180、192、172、160 事件；四次 G14 各 10 事件。均无丢弃或
记录失败。四次 foreground 的最后一次返回 PID=0 的原 `_try_wait` 调用开始，位于
settlement 后 1875.944、2086.817、1676.273、1374.747 ms；到随后首次返回目标 PID
的调用结束，窗口分别为 50.248、50.300、50.217、50.239 ms。这是保守的退出观察
窗口，不是精确退出时间，也不是应从 settlement 扣除的开销。

reader-done 通知返回到 Popen.wait 返回分别为 4.648、25.127、1.347、34.556 ms。
reader-done 不是物理退出证明；它仅帮助区分通知与原 wait 返回。这批 trace 支持：
主要耗时处于“原 wait 尚未观察到进程退出”的阶段，非 idle/close 长等待。50 ms 的
尾端观察窗口不能单独解释本批约 707 ms 的 foreground settlement 极差。尚不能区分
Product 内部收口、调度或 I/O 的贡献，也不能把它外推为旧 11 项不确定的统一根因。

G14 的本批四点较接近，仅是另一路径的描述性对照，不是其正式 A/A 已稳定；它不走
PTY polling。本轮不调整 poll/deadline/cleanup，不重算旧报告，不直接启动正式重采。
本批不支持尾端轮询窗口单独解释全部波动；旧 A/A 的归因仍未闭合。后续应保留整体
指标并在未退出阶段做有界只读归因，或明确改善受测环境后再按既定协议校准。

架构、合同、生命周期对本批原始报告的独立只读复核均通过，无 P1/P2；合同视角重新
计算表格及 707.414 ms 极差，生命周期视角核对八份原 observation/trace 与报告副本
逐项一致。原 observation 仍为 `observed / valid=false`，未被 trace 升格。批准仅限
诊断证据及以上有限结论，不关闭旧 A/A、absent 失败或独立 Product cleanup P1。

### Local Tooling Delivery After Diagnostic — Product Remains Pending

真实诊断及所有本任务测试均终态后，进一步作以下本地原子提交（均 `Refs #578`）：

- `2e5f47c5`：仅 AppHost collection 的 Make 单行删除与三项 CI 回归，2 文件、
  37 insertions / 1 deletion。暂存前逐 hunk 检查，不混入同文件内 G18 工具接线。
  对应当前源码组合的完整 AppHost 为 1255 passed / 12 platform skips、1267 IDs；
  完整 CI 为 46 tests passed。架构视角另确认该切片不依赖未提交 facade 或 G18 工具。
- `e85b20fe`：原 owner 的 failure-only 有界线程取证及回归，2 文件；对应完整
  AppHost XML 中该模块为 60 passed / 1 Windows platform skip。保持原失败判定与
  物理回收顺序，不修改 Product，三视角增量评审结论仍只覆盖失败取证。
- `d9e11a90`：测量工具、原 native/picker witness 复用、Make/CI additive 接线，
  19 文件。提交前逐项核对暂存 bytes 与 working bytes 以及本次诊断最终 helper
  pins；Make 单独匹配已验证 SHA。没有任何 `src/` 文件暂存。既有逐轮三视角评审
  与源码组合验收有效；这不是宣称当前源码已整体绿灯或每个独立提交已重跑全套门禁。

实际 XML 复核：七个 collector 测试模块分别为 bytecode 15、comparison 90、
provenance 19、recovery 16、slot 12、native 213、startup 54 项 passed，合计
**419 passed / 4 skipped**。四个 skips 均保留原 slot-mode 条件，不称安装态通过。
该数来自已完成的 AppService complement 476 用例中的相关子集，不是新增执行。
原 picker terminal 模块在完整 AppHost XML 中另有 7 项 passed。

上述三个提交均未改已测文件内容；原不确定/失败报告和不可变 baseline wheel 保留。
当前 Product facade、SDK/lazy/budget 切片尚未提交；Coding broad gate 的独立 cleanup
P1 仍未获修复授权。正式 collector 的 clean-Product 约束不变，未为脏源码增加豁免。
本地工具交付不等于 G18.0B 稳定基线、G18.1 不可变候选或性能验收完成；没有 push/merge。

### Existing Continuity Staging Identity Defect — Scope Decision Pending

上述失败所在的 `tests/coding/test_continuity_import_bridge.py` 及 Product
`src/loushang/coding/continuity.py` 均未在本轮修改。后者与 baseline install-a 的 wheel
文件逐字 hash 相同：`a4e6b9fc30ed9465c6b510b2154e415e602306ab28004e89731f6eb5c18e94d1`。
实现写入后只保存 `(st_dev, st_ino)` 并关闭文件 fd，保留目录 fd；稍后清理按保存的
身份比较当前路径，再 unlink。原测试在 prepare 返回前 unlink 原文件并写入 replacement。

为区分测试假设和真实清理缺陷，使用任务内诊断
`.artifacts/g18-source-tests/continuity_identity_probe.py`（SHA256
`f1afeab661c8a091030630ae2deba1510550b5f4b219de7b41da73ae4c978e45`），
预先固定每个环境八次、每次新私有目录。诊断使用真实 bridge、仅以测试 Runtime 在既有
prepare seam 执行原测试的替换动作；记录替换前后 dev/ino、实际错误、replacement 是否
保留及 abort 次数。不 monkeypatch 身份校验，不做性能计时或扩大原测试超时。

| 对照 | 环境、终态及来源断言 | 八次实际结果 |
| --- | --- | --- |
| 未修改 baseline | install-a；exec 33384 exit 0；根 `/var/tmp/lg18-tests-UKUV6Z`；origin 为该安装的 site-packages | 每次替换前后均为 `(64770, 1118872)`；未报错；replacement 被删除；abort_count=0 |
| G18.1 源码候选 | source-tests editable；exec 71195 exit 0；根 `/var/tmp/lg18-tests-UQHkQH`；origin 为 checkout/src | 每次替换前后均为 `(64770, 1118880)`；未报错；replacement 被删除；abort_count=0 |

两组都使用 `-I -B`、显式解释器与 env allowlist，实际进程断言 Product origin；
PYTHONDONTWRITEBYTECODE=1，不改 baseline 安装缓存。exit 0 只表示诊断完成，八次都是
缺陷重现，不能算测试通过。此证据确认既有 unlink/recreate 的 inode 重用会绕过当前
清理身份检查，不是仅凭一次测试失败推定，也不是本轮 lazy facade 新引入的问题。
原 Coding 门禁单次失败只记录了未抛异常，没有 inode 读数；身份重用机制来自上述
独立诊断，不能将诊断读数追写成原门禁现场取证。

不得通过改成 rename/replace 的测试场景、豁免失败或增加 timeout 来掩盖该缺陷。
潜在修复需在 staging 到 cleanup 期间保留原文件身份的有效引用，并验证全部成功、
错误和取消路径释放句柄；具体设计尚未实施或接受。它触及当前 G18 明确排除的 Product
cleanup，因此先请求独立范围确认。G18 goal 仍 active；本轮没有提交、推送或合并。

生命周期视角已只读核对实现与
[Phase 5B 既有合同](plugin/continuity-provider-phase5b-contract.md)，确认一个 P1：
replacement 被删除且 prepared 未 abort，违背原来的替换保护。评审同意需独立授权，
未批准直接扩大 G18；建议保留原 fd 并补缺失/替换/异常/取消路径的释放验证，同时明确
该修复不等于解决既有独立的 stat→unlink 并发窗口。评审未运行测试或修改文件。

### G18 Evidence Routing And Temporary Quota Recovery

两份新增 native JSON 精确加入既有 G18 AppService evidence 路由。新增覆盖先产生
2 个预期 subtest failures，修正后完整 tests/ci **43 tests passed**（exec 33659 exit 0）；
actionlint 1.7.12、四项文档 invariant 和 diff whitespace 检查通过。unknown→full 与
facade additive consumer scopes 保持；Makefile/CI 基础设施修改仍选择 full checks。

首轮测试之后 `/tmp` 配额又使 sandbox mount target 创建失败，标准补丁未能落盘。
为恢复编辑，仅迁移本任务已结束的旧 preflight `loushang-g18-native-83tyi44b` 中
两份普通回执（sample-27/28 的 native.json）以及两个无只读子目录的完整 sample-21/22。
新位置为 `.artifacts/g18-baseline/retained-scratch/native-preflight-83tyi44b/`，结构保留，
迁移前后 SHA 一致；这不是整个 scratch 已迁移。未 chmod/delete 只读 snapshot、未改
其他任务数据、没有重跑 native。原报告不改，其四个回执路径需从保留目录恢复后读取：

| Sample | native.json SHA256 |
| --- | --- |
| 21 | `666e5446711c83c0ace80d9d045c7a20d6a03a137d72f11398b54e2a9fef2806` |
| 22 | `a92e9821428ef79d72e184a636cf27e2cda9c372991329f2ceb347c18ce3b341` |
| 27 | `2570fb3193c1446180822058312f98902a41f486860b3a86f10fc86c0dcbc29e` |
| 28 | `39cc27c6c559b8b75d8dc2ce932a74ad2c101f093ea2935c1c21d448caa0600a` |

恢复须先核对 SHA/原目标不存在：21/22 可复制整个对应 sample 目录回原 scratch；
27/28 只复制 native.json 回仍存在的 sample 目录，不覆盖任何新文件。迁移释放了少量
空间/目录项后补丁已成功落盘；不宣称主机配额或性能噪声问题已整体解决。
