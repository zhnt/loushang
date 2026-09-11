# G18 Linux-first Startup Performance Plan

## Status And Authority

- ID: `STARTUP-PERFORMANCE-G18`
- Design status: accepted — three-view design review and corrective re-review passed
- Historical G18.0 collection status — Linux inert-path A/A reference frozen (9/10 stable);
  fixed-slot warm native A/A collected (308 valid; 30/41 stable, overall inconclusive);
  absent-bytecode collection stopped on sample 87 ready timeout (86 valid, not accepted);
  stable native baseline and candidate comparison remain pending
- Attribution status: bounded foreground/G14 diagnostic completed all eight original
  observations with final installation/helper pins intact; 55 diagnostic controls and
  three-view tool review passed. Foreground time was concentrated in original process
  wait, not idle-output/close; this is not a stable baseline or a performance gain.
- G18.1 status: corrective 196-line facade and independent LOC budgets passed three-view
  code review and 129 fresh source-mode compatibility/activation/budget regressions;
  Harness (4488), HarnessTUI (872),
  TUI unit (1252), Coding UI (577) and deterministic playback (179) gates
  passed; Coding UI fixture temp-root correction also passed three-view review;
  independent repair of the pre-existing Coding cleanup identity failure was explicitly
  authorized on 2026-09-10; retained file ownership and failure cleanup are implemented;
  focused bridge passed (17, one original platform skip), full Coding offline passed
  (2430, 21 unchanged skips), and Linux CLI host-runtime passed (2, one Windows skip);
  this closes the independent cleanup blocker, not the G18 performance acceptance;
  AppHost collection P2 corrected and reviewed; the full gate passed (1255, 12 platform skips),
  with all 102 inventory modules and 1267 expected case IDs recorded; G8/G9/G10 gates,
  their validators and the G10 canary passed;
  the final 15-file AppService complement passed (472, 4 slot-mode skips); actual combined
  Harness/AppHost/complement evidence covers all 102 AppService modules and exactly
  1535 expected case IDs (1520 passed, 15 skipped), not a rerun of check-appservice;
  Linux host-runtime, terminal platform, POSIX PTY/tmux and PLC9B/C5 native source gates
  passed; G16 Linux native exact-case evidence passed (29, zero skips);
  Linux offline install compatibility passed (30 packages; cryptography binary wheel);
  immutable wheel/performance work pending; selected LSP live checks not run under this scope;
  no accepted wheel/performance result;
  reviewed fixture corrections committed locally (7fc472c2, 179edf39), followed by
  AppHost collection correction (2e5f47c5), failure-only thread evidence (e85b20fe),
  and G18 measurement tooling/gate wiring (d9e11a90);
  Product facade independently committed as 537cc910 after three-view pre-review;
  new shared-cleanup baseline 5f7346bb and candidate wheels/installations identity-verified;
  first shared-cleanup inert A/A completed 440 valid observations, nine of ten cases stable,
  with hosted-help inconclusive; its bounded diagnosis did not establish a root cause;
  after a recorded controller/resource condition change, one reviewed full inert A/A
  completed another 440 valid observations: nine of ten cases stable, plugin-help
  inconclusive on both four-group median span and block-0/b MAD; raw evidence and
  comparator independently audited in three views, no P1/P2; the old and new reports
  remain separate, with no pooling, automatic retry or A/B authorization;
  next-step three-view review closed further speculative plugin profiling;
  user subsequently confirmed a complete exclusive Linux measurement window;
  the reviewed exclusive-03 inert A/A completed 440 valid observations and all ten
  cases passed original stability gates; source/installation/helper/raw comparison
  audits and three-view result reviews passed, no P1/P2; inert A/A accepted for
  this independent report only, without attributing the outcome to facade gains;
  new HOME isolation and fixed-slot recovery correctness controls pass;
  new native warm A/A completed 308 valid observations, 16/41 metrics stable and
  25/41 inconclusive, independently reproduced;
  new native absent A/A completed 308 valid observations, 28/41 metrics stable and
  13/41 inconclusive, with raw evidence audited and the comparison independently reproduced;
  native warm and absent stability remain unaccepted; all A/B remain pending;
  safe-boundary native checkpoint support is committed as d7545673, with three-view
  re-review, 466 scoped regression passes (four platform skips), and a real warm
  pause/resume smoke retaining its original observation prefix and seed state;
  after capacity was restored, the reviewed uninterrupted checkpoint-enabled warm
  A/A attempt exited 1 during first recovery seed preparation (original 35-second
  TUI ready timeout, zero observations); three-view read-only audit confirms this
  is execution failure, not accepted calibration or a resumable paused generation;
  automatic full reruns/A/B stopped for a separately reviewed bounded diagnosis;
  the reviewed single-seed diagnosis subsequently completed its two original CLI
  workflows with zero formal observations and no failure-tree capture; this
  non-reproduction result does not establish the old timeout cause or stability,
  and automatic formal reruns remain stopped pending a reviewed condition decision;
  resumed segments do not automatically qualify for performance acceptance;
  installed readiness/stability/performance acceptance pending; no push or merge;
  current progress: [Linux local delivery](startup-performance-g18-linux-delivery.md)
- Authority: delivery plan; accepted runtime boundaries and public contracts take precedence
- Tracking: [G18 #578](https://github.com/zhnt/loushang/issues/578)
- Historical baseline: `9bc69361494293595ae424be225c61e3226a9996` (G17 promotion; retained)
- Current paired baseline: `5f7346bb93c0b58203f60450a50cbf54c5713cec` (shared cleanup fix)
- Current facade candidate: `537cc91099a1a48bf16ec15f9d20772a6204737a`
- Branch: `harness/g18-startup-performance`, in the existing isolated Harness lane
- Owner: Harness lane coordinates delivery; code stays in its owning package.
  Performance tooling is not a new responsibility of the Harness runtime.

本稿替换早期未接受的 startup proposal。旧稿的 6.1 s、1,365 modules 等历史数字
不能代表当前基线；G16/G17 hosted/mux 已交付，不能再作为未来假设。设计轮已完成方案、
隔离试测与评审；用户随后授权继续测量和冻结基线，并激活 **G18.0B＋G18.1 Linux
候选、评审修复及本地提交** goal。依据下文已接受的 Scheduling Addendum，可在无 native
采集运行时先实施待性能验收的 Coding facade 候选；稳定 native 基线与配对验收仍须完成。
不激活 execution 新行为、不 merge/push。G18.2 dispatch 与 G18.3 外部平台
验收不包含在本次本地候选的交付范围，整体 G18 的提升目标不因此改写。

继承 [governance profile](../governance-profile.md)、
[architecture method](../../architecture-method/README.md)、
[current owner map](current-owner-map.md) 和
[runtime provenance boundary](runtime-provenance-boundary.md)。
Current 由源码和测试说明；下文 Target 不等于已实现。

## Problem, Current And Target

用户启动进程是为了调用某个能力；为未选能力提前导入整个运行时属于可避免工作。
但把成本推迟到首帧之后不等于消除成本：ready、首次使用、错误和清理必须一起观察。

当前源码事实：

- 基线 `src/loushang/coding/__init__.py` eagerly imports arch/tool-pack、bootstrap、
  runtime、SDK、Session。当前已独立提交的 G18.1 候选改为显式类型导入与按需 runtime exports；
  定向兼容性及上述广泛源码门禁已通过，安装态与性能验收仍待完成。任何 Coding 子模块仍先执行祖先 facade，
  hosted client 也不例外。
- `src/loushang/coding/cli/__main__.py` 在 dispatch 前加载多个 handler 和运行时。
  `run_cli` 在函数定义时绑定可注入 callable defaults；现有签名和路由顺序不能随意改。
- `src/loushang/harness/__init__.py` 已有 lazy facade，Session/transcript 同样如此。
  应复用已成立的方式，但不能规定所有包的 `__init__.py` 一律 lazy。
- `src/loushang/coding/cli/hosted_client.py` 已有局部延迟导入；祖先 facade 是候选优化点，
  不意味着必须修改 AppHost。
- `pyproject.toml` 已定义 `loushang`、`loushang-tui`、`loushang-hosted`、
  `loushang-hosted-tui`、`loushang-mux`、`loushang-plugin`；本方案不改入口 target。
- `TurnStartPerformanceRuntime` 是 turn 观测，不承接进程 startup benchmark。

Target：仅为所选路径加载所需依赖，同时保持公开符号身份、激活时机和生命周期。
首先优化 Coding facade 和 CLI dispatch；其他包必须有归因证据和 owner 同意再扩展。
不增加顶层包、运行时公共协议、后台导入线程或常驻加速进程。

## System Boundary And Responsibilities

Benchmark 是运行时之外的开发工具：启动已安装命令、记录观测、比较证据。
命令仍负责解析与 Product composition，AppHost/Hosting 仍负责 ready 和进程清理。
Benchmark timeout 不成为运行时的取消策略。

| 职责 | Owner / 边界 | 不负责 |
| --- | --- | --- |
| 场景与 provenance | 计划放在 `scripts/dev` 的 tooling；固定 case manifest、安装身份 | Product 缺省行为、用户配置 |
| 测量与归因 | tooling 启动单个 case、收集有界结果、管理自己的子进程 | Session 生命周期、全局缓存策略、ready 定义 |
| 比较与门禁 | tooling 比较匹配证据；tests 验证导入及行为契约 | 修改 deadline、隐藏失败样本 |
| Lazy facade / dispatch | 现有 owning package，先 Coding | 把 Product 逻辑搬入 Harness/Foundation |
| Ready / attach / first use / settlement | 既有 AppHost / AppService / Product / UI owner | 另造一套性能专用生命周期 |

前三项是工具内部职责，不是三个运行时包。数据流为场景/provenance → 观测 → 比较；
运行时不依赖 benchmark。Hosting、AppHost、AppService、Harness、Product 依赖方向不变。

## Scope And Invariants

范围：已安装进程启动、导入图收缩、按命令加载、公共 facade 兼容及可复现证据。
先 Linux 优化稳定，再在其他机器验证 macOS/Windows。

不含：execution registry/deduplication、Product execution adapter、wire/GUI 新能力、
Session 存储改造、先首帧后 ready 重排、修改启动/清理预算、自动 daemon、共享预热池、
compileall 部署、tmpfs/全局字节码策略、升级 Python 或承诺统一亚秒 SLO。无 live 模型请求。

| Requirement | 验收证据 |
| --- | --- |
| `G18-ISOLATION` | 独立分支/解释器/lock/安装 origin/artifacts；不改其他 lane 环境与缓存 |
| `G18-MEASURE` | fresh process 与 profiling 分离；明确 case/cache mode；保留失败和无效记录 |
| `G18-COMPAT` | export identity、导入行为、CLI 输出/退出/错误/扩展路由和注入 seams 保持 |
| `G18-READINESS` | Linux 真实 launch/ready/first-use/settlement；不加 deadline、不重排 ready、不减清理 |
| `G18-GAIN` | 配对比较达到事先冻结的提升目标，其他路径无实质退步 |
| `G18-PARALLEL` | execution 线可独立测试；共享文件单 owner；组合后复验两条线 |
| `G18-PORTABLE` | Linux 阶段与同一候选的后续 macOS/Windows 验收明确分开 |

### Compatibility Rules

1. 保持 `__all__`、documented imports、from/star import、dir、符号 identity、
   unknown-name AttributeError、类型检查表面，以及适用的 pickle/module identity。
   Star import 仍可能加载所有 exports，不把它当成 help fast path；不得吞掉导入错误。
2. 用新进程测支持的 import orders、重复访问、循环依赖和能力首次使用。
   注册等必要副作用仍在原生命周期点发生。若导入时机本身是受支持契约，保留它；
   改契约必须另行评审，不能用“延迟”掩盖。
3. 保留 CLI 解析、extension help/flags、legacy rejection、
   apphost/resource/workspace/lsp/multiagent 路由、依赖注入、退出码和诊断。
   不以未经评审的 sentinel 替换 `run_cli` defaults，不靠更换入口 target 绕过测试。
   `harness/cli/agent_host.py` 使用 callable identity (`is`) 判定 RPC/plan/plain 路由：
   G18.2 必测省略默认、显式传原函数、注入替身三种形式，不能只比较 inspect.signature。
   Extension `collect_help_flags` 仍属于真实 early operation，保留发现与审批 builder 回归。
4. 不做 optional-dependency 静默降级、import machinery monkeypatch、计时绕过，
   或用占位屏掩盖首次使用延迟。

## Isolated Linux Environment

本轮环境为 `.artifacts/g18-design/venv`，独立 uv cache 为
`.artifacts/g18-design/uv-cache`。以显式 `UV_PROJECT_ENVIRONMENT` 执行
`uv sync --locked --extra dev --no-editable --python 3.11`，非 editable 安装当前基线，
不复用普通 `.venv`。Pilot 从任务内 empty cwd 用该解释器的 `-I` 启动，
校验 sys.prefix、包 origin、distribution non-editable metadata。

G18.0 另建 baseline/candidate wheel 安装，解释器与依赖版本一致，记录 wheel hash，
不覆盖运行中的安装。已安装 CLI 验证必须离开 checkout、移除 PYTHONPATH 并核验 origin；
source-mode pytest 单列。真实启动使用既有 seams 提供任务私有 synthetic 配置/cache/data。
不修改父会话/其他 lane 的环境或真实 home 内容。每个被测子进程通过显式 env mapping
获得私有 HOME，Windows 后续同时映射 USERPROFILE 等平台 home 字段，并指定私有
LOUSHANG 配置/数据及临时根；不能只依赖 LOUSHANG_HOME，因为模型目录仍使用 Path.home()。
采用可审计的 env allowlist，保留启动所需平台字段，排除 ambient provider credentials、
plugin/config/Git 注入等影响。不访问真实 Session、不清共享缓存、不 drop OS cache、
不终止其他 agent。G18.0 必须用 synthetic ambient-home poison/sentinel 负控证明 default
和 hosted 启动不读取外部用户模型配置，且父环境与外部 sentinel 文件不变。

两个采集器支持 `--scratch-parent`，默认仍为 `/tmp`；显式值必须是已存在的目录，
只在其下创建新的任务私有根，不修改父目录权限或复用已有主体。Linux 后续采样显式
使用经容量核验的 `/var/tmp`，避免本机 `/tmp` 的用户配额限制，同时保持短 socket 路径。
报告记录解析后的 parent 和实际 scratch device；恢复主体随同迁移，seed archive、
证据、固定安装 slot 和 bytecode 的既有独立位置不变。存储位置属于测量条件，必须在
同条件下重新采集 A/A、A/B；不得将旧 `/tmp` 耗时与新目录耗时之差归因于 Product 优化。
目录存在不保证容量或可写性，分配/写入失败仍按原失败策略保留，不自动换盘重试。

本机 G14 observer 显式采用已评审的 CPython 3.11 `SafeChildWatcher` 私有 scope，
避免默认 ThreadedChildWatcher 的退出通知早于线程退出。仅观察器选择 backend：
真实 CLI、协议、三个计时边界、Product 与外层 owner 均不变。回执绑定实际 watcher
及已核验的 observer Python；旧默认 watcher 的报告不与新条件混比。其他平台与
Python 版本不自动 fallback，须在其后续验收中另行确认。

源码测试用 `scripts/dev/run_pytest.py` 及其 leased scratch root，不覆盖 --basetemp。
必须在解释器启动前显式设置 checkout `src` 的 PYTHONPATH；runner 会在 pytest 处理
pythonpath 配置前导入 Foundation，不能仅依赖 pyproject 的 pythonpath 来替换已加载的
installed package。实际 pytest 进程内核验 Coding/Foundation/bootstrap origin。
测试进程使用 env allowlist 与新的 `/var/tmp` 短私有 HOME/data/runtime/tmp 根；不把
leased 根放入 checkout 子目录，避免祖先 AGENTS/settings/workspace 被测试项目继承。
这属于 source-mode 测试组合，不改变 installed/native 的隔离方式和验收身份。
源码 activation 使用独立 `.artifacts/g18-source-tests/venv` editable 开发安装，原锁定
requirements 离线带 hash 安装、Python 与 baseline 相同。不能将 checkout 源码与旧
non-editable wheel metadata 混用；现有 Plugin distribution 校验会正确拒绝这种组合。
实际测试进程同时核验 direct_url 的 editable 标记及 checkout URL。原 design、baseline、
observer 安装不变，editable 环境不得用于 installed/native 性能验收。
pytest 首次即在 managed sandbox 外运行，保留 not live 和适用的 host-runtime selectors。
真正 native host 验收单列命令；被 skip 的 host cases 不能充当 ready 证据。无 live/network 场景。

## Measurement Contract

### Cases And Milestones

| Case group | 观测 | 含义 |
| --- | --- | --- |
| Direct imports | harness、coding、CLI root 的新进程 import | 归因输入，不等于用户 ready |
| Read-only entries | 各入口实际支持的 help/version；覆盖 default、TUI、hosted、hosted TUI、mux、plugin | parent spawn → exit；验证预期输出/状态 |
| Real startup | Embedded CLI/TUI、explicit hosted/mux 的既有确定性验收 fixtures | 外部 spawn → 原有 ready/attach/first-frame；保留各自含义 |
| Deferred first use | 启动后首次相关 command/capability | 发现延迟到 checkpoint 之后的成本 |
| Settlement | 退出/中断及 owned-child 清理 | 原有正确性和清理耗时，不定义新 deadline |

G18.0 在接受基线前确定支持的 argv、fixture IDs、milestones、first-use actions。
具体分组与现有 fixture 映射见 [G18.0 Scenario Inventory](startup-performance-g18-scenarios.md)。
已安装只读入口 A 组可独立冻结参考基线；不代表真实启动 B 组或整个 G18.0 完成。
不能给所有命令假设 --version，也不能把调用 Python main 的 help 当成完整 console-script 覆盖。
本轮 design pilot 刻意只是子集，不是 real-startup baseline。

每个 baseline/candidate 样本（包括 warmup）使用新 runtime/session/mux 根，或从相同
受控 seed/hash 恢复；fixture setup 不计时。Fresh 与 recovery 分成独立 case，固定
初始会话数/内容、索引及恢复工作量，不让上一轮结果成为下一轮输入。此状态契约与
bytecode/page-cache 模式正交。失败后未经 owned-child settlement 确认不得复用根。
G18.0 的 fixture manifest/reset 测试必须覆盖此契约，不能只证明“目录属于本任务”。

父进程以 monotonic clock 计 wall time；进程内 milestones 使用明确定义的时钟和边界，
嵌套 cumulative 时间不能相加。`-X importtime` / cProfile / module-count 归因独立运行，
不混入计时样本，更不能累加 importtime cumulative 列当 total。
采 RSS 必须明确进程范围和平台单位；不能相减 RUSAGE_CHILDREN.ru_maxrss 当单子进程增量。
不能根据 import wall time 推定内存或 first-use 同时改善。

Cache modes 显式标注：

- **Fresh process, warm bytecode**：每个 case/install 固定一次不计时 warmup；
  每个正式样本为新进程，OS page cache 不受控。
- **Fresh process, absent bytecode**：独立任务拥有的 install/cache setup，
  每个配对样本前核验，记录创建/写入策略；setup 不计时。不称为 OS cold。
- Pilot 的 **cache as found** 不代表以上正式 cache-mode 验收。不复用常驻解释器计时。

记录 schema version、source commit/product tree clean、lock、wheel hash/origin、
解释器/build、OS/kernel/CPU、load before/after、scenario/argv/cwd/TTY/config fixture、
cache condition、样本数/顺序/raw elapsed/status/output assertions、timeout/failure/invalid 原因。
报告不写凭证或真实用户内容。

### Comparison, Goals And Failure Policy

G18.0 在同机同条件下，对优先 case 至少采 20 对 baseline/candidate 样本，交替运行顺序；
每个原子优化前后均比较。保留全部样本，不 retry-until-green、不选择性删除 outlier、
不混比有/无 profiler 的数据。报告 median、raw distribution 和 nearest-rank p95；
20 个样本的尾部置信度有限，p95 只作描述，不是 SLO。另跑独立 blocks 区分调度噪声。
同一 benchmark window 不并行运行本任务的 Product tests/build；不可控外部负载记录在案。

计划目标是：warm-bytecode fresh-process 下 default CLI help 和 hosted-TUI help
的 median **至少降低 30%**。这是待 G18.0 校准的计划目标，不是已取得收益。
G18.0 在优化前，以重复 baseline blocks 冻结 cases、噪声边界和 no-regression limits；
若目标不适用，必须在观察 candidate 收益前修订并复审。
Ready/first-use/settlement 及其他已发布入口不得超过冻结的退步边界；只有 help 提升不能收口。

功能/import-boundary checks 立即 strict。Timing initially record-only，直到可复现且
能识别已知退步后再转 blocking。噪声过大的比较是 **inconclusive**，不是通过，
更不是放宽运行时 timeout 的理由。Product errors/timeouts 仍是失败，区别于 provenance 无效。
Tooling timeout 必须清理自己拥有的进程树、留下 partial evidence，不能遗留后台进程或误杀。
Linux 性能验收需重复有效比较达到冻结目标，不能仅依赖 advisory CI 显示 green。

当前 A/A 校准预先采用保守的可判定性检查：每个 case 的四个 block/install median
之间差值不超过 `max(最小 median × 10%, 20 ms)`；每组 MAD 不超过
`max(该组 median × 10%, 10 ms)`。这是稳定性检查，不是 Product SLO；越界标记
inconclusive 并保留所有样本。未来候选同机配对时，优先 help 仍须达到 30% 改善，
其他 A 组 case 的 median 退步不超过 `max(baseline median × 10%, 20 ms)`。
首次启用 blocking 比较前仍需 A/B runner、已知退步负控和代码评审。

## Delivery Slices

| Slice | 工作及退出条件 | 平台 |
| --- | --- | --- |
| G18.0 — evidence baseline | accepted design；checked-in scenario/provenance/measurement tooling + tests；独立 wheel 安装；real-startup/first-use fixture map；重复基线及冻结 limits | Linux；本轮 pilot 不等于完成 |
| G18.1 — facade hot path | 先 Coding 小范围 lazy exports；before/after attribution + compatibility；不改 public identity/activation | Linux |
| G18.2 — selected dispatch | 只减已归因的无关导入；保留 injection/help/error 路由；验 ready/first-use/settlement；稳定检查进入 scoped gates | Linux 候选验收 |
| G18.3 — portability/promotion | 其他机器同候选的配对测量 + 既有 G16/G17 installed/native gates；评审后另行授权 promotion | Linux/macOS/Windows |

G18.1/2 使用小步可回滚提交、定向回归和评审。工具需通过故意注入退步的测试，
才可承担 blocking timing 决策。场景归属和依赖路径未 executable/reviewed 前不扩 CI selectors。
回滚 revert 原子优化，不增加 fallback importer、不减超时要求。公共/生命周期边界变更
退出本方案，交其 owner 做增量设计。

macOS/Windows 不阻塞 Linux 设计和优化，但验收状态是 pending，不是免测；
既有 mandatory 跨平台门禁不删除、不弱化。使用同 source/lock、各平台构建的 wheel hashes；
各平台以当地 baseline/candidate 配对，不直接比较 Linux 秒数。
外部验收后若代码变化，最终候选必须重跑受影响证据及既有 mandatory gates。
Linux-only success 不等于多平台完成，也不自动授权 main promotion。

### Accepted Scheduling Addendum — Performance Acceptance Unchanged

warm A/A 已完整留存但 11 项统计不确定，absent A/A 则在 86 个有效样本后出现
ready timeout；都不能作为已接受的完整 native 基线。架构、合同、生命周期三视角已
批准以下调度调整，无 P1/P2；它替代原先“基线完成后才实施 facade”的编写顺序，
不改变最终验收条件：

1. 在没有 native 采集运行时，允许推进用户已授权的 G18.1 局部 facade 实现、
   regression-first、兼容性、静态归因和代码评审，得到待性能验收的本地候选。
   不增加 G18.2 dispatch、公共 API、生命周期、owner 或 timeout 变更。
2. 原 baseline wheel/安装/报告保持不可变；候选使用新 source commit/wheel/安装。
   不改变或追认原失败/inconclusive，不混合旧 cache/backend/storage 条件。失败 slot
   不复用；没有新证据或已声明的诊断方案，不启动 retry-until-green。
3. 调整只解除“编写 Product 代码”的先后限制，不解除 G18.0B 稳定基线、两种 cache
   条件、七场景/41 指标、既定比较规则和真实无退步验收。原整体 G18 的 help 目标及
   G18.1 与 G18.2 的目标边界不变。环境/测量问题仍属本 goal 必须解决的工作。
4. 可在对应代码门禁通过后做明确标注“性能验收待完成”的原子本地提交，以取得
   候选 wheel 所需的不可变 source；不能称完整候选已验收、不能关闭 goal、push 或
   merge main。最终交付仍须原目标的全部必要证据，不以仅兼容/静态测试替代。

本调整已生效；当前红灯测试仍不是可提交的完成实现。三方批准只覆盖调度与测试
设计，不代表功能、安装态或性能验收通过，详见评审记录。

### Accepted G18.1 Facade Budget Addendum

原 HarnessTUI 门禁发现初版 lazy facade 为 257 行，导致 Wave A core 达到 33,929 行，
超过原 33,800 上限。这是 G18 引入的预算回归，不是其他 Product core 增长。基线
`9bc69361494293595ae424be225c61e3226a9996` 的 facade 为 114 行，非 facade core 为
33,672 行。架构、合同、兼容性三视角接受以下窄修正：

- 同文件导出表从 public → (owner, original-name) 简化为 public → owner，仅将唯一
  不同名的 `DefaultResourceLoader` 放入 alias 表；保留原标准 `TYPE_CHECKING` 导入和
  literal `__all__` 及顺序。196 行原型经 Ruff lint/format 检查，不新增 `.pyi`、包文件、
  业务 owner 或项目配置，不改变 A/B 的 package-path/project 冻结条件。
- 仅精确的 `G18_FACADE_SLICE = {"__init__.py"}` 独立限 200 行；其余 Wave A core
  上限为 **33,686 = 33,800 − 114**，保留原 14 行余量。G10–G17 的名单和上限不变。
- 两项上限合计 **33,886**，相较原 33,800 **明确增加 86 行**，不是总预算不变。
  该增量仅供 facade 使用，不能把原 114 行再次释放给其他 core。
- 门禁须检查精确 singleton、分区互斥且完备；所有未批准的新 `.py` 文件（包括嵌套的
  `__init__.py`）仍计入 core。保留原导入、静态正负控、cold-star/named、并发 bootstrap
  和 pickle 回归；旧 257 行版本的通过结果不能替代本修正的回归。

批准只涵盖修正方案及预算；不追认原红灯，不代表实际实现、安装态或性能验收通过。

## Parallel Work With Execution Contract / PLC

Execution-contract 线负责 Product invocation、登记/去重、取消/quiescence、
cleanup-before-slot-release 及后续 protocol/GUI。G18 负责 benchmark 与已归因的 import/dispatch。
互不相关的开发无需互等。

性能线不编辑 execution modules、Product execution adapters、AppHost launcher、
Session cleanup 或 deadline。共享 Coding facade/bootstrap/CLI composition/test inventory
同一时刻只有一个 editor；接入前明确 files/base commit，不能拷贝另一 lane 未提交内容，
也不能测身份不清的混合安装。

另一线报告的 G10 `G10-EPHEMERAL-NO-SESSION-IO` timeout 与同环境 main control 差异，
仍归原回归调查；G18 不证明其成因或修复。组合激活前同步商定的 main，
保留失败 branch/control 证据，定位仍存在的差异，再复验组合 G10/G16/G17 及 execution/cleanup。
导入变快不能豁免该调查，也不增加原 runtime timeout。

## Evidence And Review

本轮 Linux pilot / 环境见
[G18 Linux Design Baseline](startup-performance-g18-linux-baseline.md)；
后续 400 样本入口测量及冻结规则见
[G18 Linux Installed-Entry Freeze](startup-performance-g18-linux-freeze.md)；
三视角评审及处理见 [G18 Design Review](startup-performance-g18-review.md)。

评审视角：(1) 架构/ownership/并行边界；(2) 测量有效性/隔离/门禁；
(3) public compatibility/ready/lifecycle/跨平台覆盖。
阻断项修复并复审通过后才接受设计；accepted 不表示工具、优化或外部平台验收已交付。
