# lmux M0：受管部署与共享会话接缝

[Proposal](../drafts/lmux-managed-service-design.md) · [AppHost](README.md) ·
[Hosting boundary](../hosting/key-designs/hosted-application-support-boundary.md)

## Status

- ID: `LMUX-M0`
- Authority: normative — accepted limited Linux managed-profile contract
- Design status: accepted
- Review status: three-perspective storage/lifecycle/observer slice reviews passed; recovery admission pending
- Implementation status: partial — storage, instance coordination and Linux exit observations; no activation
- Owner: AppHost managed deployment; sibling changes remain sibling-owned
- Tracking objective: active Linux lmux goal, branch `harness/lmux-managed-service`

## 1. 本地基线与推进记录

起点 `1286348e`，保留已评审 lmux 草案；独立任务分支。
最初仅授权本地提交；用户后续明确授权：完整目标验收、三视角评审修复后，
提交并推送任务分支、创建 PR，通过门禁后合并，最后同步本地 main 与
harness lane。此授权替代初始“不自动推送或合并”限制，不提前发布未完成切片，
不扩大 GUI、跨机器连接或非 Linux 自动后台范围。
基线命令为 `uv run --no-sync python scripts/dev/run_pytest.py`，目标包括
`tests/coding/test_mux_command.py`、`tests/coding/test_hosted_catalog.py`、
`tests/harnesstui/test_hosted_mux_profile.py`、`tests/harnesstui/test_hosted_mux_shell.py`，
使用 `-m 'not live' --skip-host-runtime -q`，沙箱外执行：30 passed。
独立测试 runtime 为 `/var/tmp/loushang-lmux-goal-tests`，不是用户 lmux 状态根。

完整目标仍包含 M0–M4、真实安装/断连/性能/三视角代码评审；合同测试不替代
这些验收。阶段交付记录只描述完成的切片，不缩小 goal。

## 2. 组件与候选准入

| 候选责任 | 决定 | 理由/约束 |
| --- | --- | --- |
| 用户级全局 Mux/服务目录及管理事务 | AppHost 可选 `managed` 组件组 | 跨 Product 部署编排；不放 Coding CLI/GUI；无需常驻 broker |
| 脱离终端并交接存活权 | Hosting 可选 service 机制 | 现有 ProcessLease/ChildSession 不具有交接后独立寿命，不修改其 close |
| 管理协议与认证 | AppServer 可选 managed local profile | 旧 G16 语义不变；只接 opaque 管理 port，不导入 AppHost/Hosting |
| Session scope/历史适配 | Coding trusted composition/catalog | Product 权威；不让部署索引成为 transcript 副本 |
| 唯一持久写入寿命 | Harness transcript lifecycle | Embedded/Hosted 同一写入口参与；只在 lmux 加锁不足 |
| 通用视图与 intent | Harnesstui conversation/bindings | UI 不持有 Product；保留 G16/G17/Embedded 各自终止语义 |

本合同仅准入 Linux graceful-managed profile 的 Target，不将 Hosting 的
候选 system-service/restart/跨平台自动后台全部提升为已接受能力。
目标源模块显式导入，不从 AppHost/Hosting 根 facade 自动导出/初始化。

## 3. 不可变值与公共端口

首批 `apphost.managed.contracts` 仅标准库值与纯状态转换，无 filesystem/env/
Product/GUI/asyncio 导入。验证值合法不等于赋予启动或连接 authority。

- `ManagedServiceKeyV1`：Product ID、规范化绝对 workspace、固定 managed profile；
  SHA-256 编码绑定三字段，生成稳定 service ID，不包含 Mux 名或启动实例。
- `ManagedNamespaceV1`：注入的规范化 platform home、用户 ID、机器身份；
  namespace key 区分同机器不同 home，也区分共享 home 的不同机器。
- `ManagedInstanceRefV1`：namespace key、service ID、instance ID；只供精确寻址，
  不含认证密钥、PID 或文件路径，不能独立作为启动/杀进程权限。
- `ManagedHandoffV1`：ref、attempt ID、provisional/committed/aborting 及 stop fence；
  commit 仅从未 stop 的 provisional 进入，已 committed 再 commit 为幂等观察，
  不是第二次交接；stop 后即使重试也拒绝 commit，abort 不可越过 committed。
- `ManagedStopEvidenceV1`：精确 instance ref、进程退出、应用完整结算与进程
  scope/句柄结算三种事实；stopped 必须全部为真，不能用 exit code 或
  socket 消失推断其余结算。

公共 Discover/Resolve 只返回只读摘要与 reference。EnsureStarted/ManagedCreate/
ManagedClose/Stop 必须显式 intent 与 operation ID。PrepareConnection 由 AppHost
连接协调器调用 AppServer client 重新认证，返回范围受限的 lease；不是 GUI
运行 CLI 的包装。所有 runtime error 为有界错误码，私有字段不进入 repr。
TTY 前置验证只在 lmux CLI，不进入公共端口。

## 4. Linux service 机制合同

外部输入：已准入完整 executable/argv/environment、私有控制根、attempt/instance、
单调启动预算与注入的中性 handoff/stop observation port。Hosting 不读 Mux 或
AppServer record，不解释 Product ready，只处理 owner 给出的判定。

机制提供：

1. shell=False、独立 POSIX session、stdin=/dev/null、close_fds 且仅保留白名单
   握手 fd；默认 stdout/stderr 不直接持久化原始内容。
2. 子端 provisional owner 检测启动握手 EOF；父端死亡时仍能自行清理。
3. 交接提交通过 consumer 的持久 CAS port，唯一提交点在子端；ack 丢失只
   进入 unknown。commit 后父进程退出不会向后台服务传播终止。
4. Linux 精确身份由 boot identity + PID start time + 可验证 pidfd 绑定；无法
   验证时不执行基于 PID 的终止。scope 退出清理只作用本次拥有的资源。
5. rollback 需 provisional→aborting 成功且有精确 OS 身份；committed/unknown
   不能被启动器超时清理。用户 stop 为 graceful-only，无自动 kill escalation。
6. 等待进程退出不证明应用成功收口；consumer 在 lease-last 成功后记录匹配
   实例的结算证明。异常退出/证据丢失返回 unclean/unknown，不能伪报 0。

进程树/句柄也是独立结算维度，pidfd 只绑定 leader，不能为裸 killpg 授权。
provisional 阶段由启动尝试持有 Hosting 的完整 scope/tree owner，服务内部
Product 已创建的 worker/tool 子进程仍由对应 Product/Hosting owner 持有；
handoff 提交将服务寿命交给自持 owner，但不销毁已存在的子资源 owner。
子端提交前 EOF 先通过应用 owner 收口子资源，再完成自身退出。rollback
必须验证当前实例 scope 身份，复用/扩展既有 `_posix_process` 的树/句柄
结算机制，不把一个单独 pidfd 当作整个 scope 的替代实现。若后代脱离已有
可验证 scope，必须保留债务并拒绝宣称已回收；支持该种后代需要先补受控
子资源 owner，不在底层扫描全机器进程猜测归属。

leader 先退出、后代仍持有 pipe、应用清理失败时 fence/配额债务仍保留。
干净 stop/rollback 的判定还要求 `process_scope_settled`，涵盖本次拥有的
后代与句柄。启动器死亡且子端无法继续结算时记录 unknown，由未来精确
reconcile 观察处理，不把超时或 leader 退出转换为 scope 回收成功。此点的
真实父死/后代存活测试是 M2 激活前置，不可只用已有 ProcessLease 类型代替。

系统 logout cleanup、runtime 目录被系统回收和机器重启不承诺续存；不自动
启用 linger/systemd。真实 Linux 安装+PTY 父死/EOF 是 M2/M4 必测，不以
subprocess mock 成功激活此 profile。

## 5. 存储、事务与锁权威

采用草案的 `$LOUSHANG_HOME/lmux/machines/<machine>/` 局部布局。平台纯路径
默认不修改；路径分类仍按 state/log/tmp/cache，不复制 Session 内容。
基础只读路径值不做 IO 准入：具体 private-directory owner 用 no-follow、
owner/mode、inode 验证和稳定锁，拒绝不支持可靠本地锁的布局后才启动。

全局 registry 用一个受限 SQLite 数据库承载服务描述、名称保留、operation
和配额；journal/数据库计入 80 MiB 上限。采用 DELETE journal + FULL 同步，
不制造无限 WAL；本地文件权限私有，路径/父目录已由 private owner 准入。
数据库 schema version 严格检查，不自动迁移未知版本，连接短寿命且有 deadline。

物理峰值准入：page_size=4096、max_page_count=8192（数据库最多 32 MiB）；
rollback journal 预留 34 MiB（含页头/段开销），事务辅助文件总计最多 8 MiB，
控制紧急预留 6 MiB，总计不超过 80 MiB。禁用 ATTACH/扩展加载、WAL、隐式
vacuum 与无界临时排序；temp_store=MEMORY 且查询结果/内存/操作批次有上限。
单写事务只处理一个有界 operation 或一个额度批次，并在进入前检查新增数据、
可能修改的现有页/索引页、journal 峰值与实际可分配空间，不能以 SQLite 的
max_page_count 代替文件总额治理。正常新增停止于 28 MiB 数据库水位，保留
控制记录更新余量；紧急预留禁止普通 create/log/tmp 消费。实际内核分配失败
仍可发生：停止新准入，现存实例认证 stop 通道不依赖 registry/log 写成功。
无法持久保存最终证明时报告 unknown/unclean，不伪造已确认的停止成功。

- UNIQUE(name) 与 UNIQUE(service key)；pending/停止状态继续占用名字。
- 长 RPC 不持有全局事务；intent 提交后释放事务，再调用服务，对账后 CAS。
- 每服务稳定的 lifecycle lock 序列化 epoch/start/stop/reconcile；不在释放时
  unlink。跨 runtime 根仍绑定同一持久 service fence。
- 子端 handoff commit、父端 abort/stop CAS 共用该序列。操作结果按 attempt/
  instance/operation 匹配，新代不能被旧回复更新。
- runtime 内只存当前实例机制/认证记录；持久 PID/最后观察不是存活 authority。
  runtime 丢失时拒绝另起实例，保留 unknown；不通过删除记录恢复“可用”。
- managed AppServer mutation 只接受 consumer-issued、实例与 operation 绑定
  的管理 authority；legacy create/close 直连拒绝。未登记的手工 G16 部署保持
  原语义，不自动接管。
- namespace 配额事务先预留后写入，日志/trace 共计 200 MiB，tmp 512 MiB；
  owner 确认退出后只可对账释放未使用预留。已落盘日志/tmp 跨退出/重启
  持续计费，直到存储 owner 验证删除/轮转才释放；未知文件和清理债务不当作
  空闲额度。控制收口保留额度，未知 pending 不删。

公共路径 resolver 接受可信平台根与临时覆盖，叶子不读环境；service/instance
ID 只接受固定小写十六进制，Mux 名不拼文件路径。显式 tmp 覆盖优先，默认
集中于服务器实例 tmp。Session 根不得与 control/runtime 交叠。

## 6. 默认 Session 适配与唯一写入

当前根分离和 `coding.hosted` v1 元数据属于旧显式 profile 合同，不删校验。
受管 profile 使用新 Product catalog/binding，CWD/user-home 为同库发现视图，
所有打开后身份归一到 canonical root + Product + conversation ID，不能因
选择了不同 scope 就制造第二个活跃 runtime 或第二把 writer lock。

准入过程：读取候选 header → 校验 Product/runtime profile/工作区 → 获取
规范 Session 的持久 writer lease → 重读身份/版本 → 打开现有 transcript。
已有普通 Coding transcript 保留 conversation ID、正文与附件引用，使用
**非破坏性 Product view adapter** 导出 hosted envelope：continuity 身份从
规范 Session 身份确定，不强制将旧 header 改写成 v1 create-operation 身份。
此选择细化草案的“受控适配”：不是跳过 Product 验证，也不在 registry
复制 Session 元数据。已有 v1 hosted 元数据需先验证其原合同再适配。

规范 binding identity 的冻结规则：已有合法 v1 hosted header 保留原 Product、
`continuityId` 和 `sessionId`，不按新算法改写；原 v1 create identity 校验仍
完整执行。普通 Coding 历史的 Session ID 保持 conversation ID，continuity
ID 为 `sha256(UTF-8(NUL.join(["coding.managed.continuity/v1", "coding",
canonical_session_root, conversation_id])))` 小写十六进制。路径经可信 native
resolver 规范化后注入；输入字段禁止 NUL/非法标量，不允许 scope/workspace/
service/instance 或当前时间参与。两种 scope 和 embedded 显式文件路径最终
必须映射到同一 root+conversation ID；root 被用户迁移是另一次显式存储
权威迁移，不伪装成普通 attach。UI selection scope 与 canonical envelope
分开校验，不能把 canonical identity 的 scope 反向用来扩大 discovery 权限。

新会话 create-operation 幂等信息保存在 Product 的 canonical transcript
metadata 中；失败/丢回复按 operation 与完整身份对账，不按名称猜测。
同工作区历史可恢复；跨工作区候选显示不可用原因，不能重绑定 cwd。
scope fingerprint 是发现准入约束，不是 Session 的唯一写入锁身份。

writer lease 放在 canonical session root 下的私有 owner namespace，稳定
身份由 Product+conversation ID 决定。读取/发现不取得 writer 权；持久创建/
恢复从统一 Harness transcript lifecycle 取得并保留到完整 Product runtime
dispose 成功。构造失败、Graph ownership 转移、取消和异常必须同一 owner
转移；清理失败继续持有 lease。既有短期 journal lock 保持，不能在整个会话
持有 journal 写锁阻塞合法 snapshot 读取。

所有规范 Session 的持久修改入口参加同一 writer owner：包括普通追加、
header/元数据维护、迁移、`delete_agent_transcript_jsonl`/Product delete 与
附件破坏性维护。删除另一进程的活跃 Session 必须 busy；同 owner 内部写入
使用受限现有 lease projection，不二次加锁自死锁。Graph 刷新/移交转移同一
owner，不先释放再竞争。纯读取不持 writer lease；fork 在 journal 读锁下
取得一致源快照，为新目标取得独立 writer lease，再复制/发布附件。

Embedded 与受管 Hosted 同时打开同会话时第二写者明确 busy；不同 Tab 指向
同一规范 Session 时不创建第二 runtime。测试必须跨两个真实进程，包括
embedded↔hosted 竞争，而非只测同一 asyncio.Lock。该变化涉及 Harness
持久会话生命周期，未通过其回归不得激活默认共享根。

激活矩阵补充：同一会话由 CWD/user-home/Embedded 显式文件三入口取得
相同规范身份与锁；Hosted 活跃期间 Embedded delete/维护拒绝；cleanup
失败第二 writer 仍 busy；释放后恢复成功。普通历史 discovery/失败 resume
不得改变 header/正文/附件引用；成功 resume 只追加正常会话记录。合法 v1
恢复保留身份，非法 v1 元数据拒绝；日志写入→崩溃→重启→续写仍受总额度。

实施入口 inventory（对应 writer 能力，不能只修一个 hosted 调用点）：

| 现有入口 | 需要接入的合同 |
| --- | --- |
| `harness.transcript.session_factory.AgentTranscriptSessionFactory.restore_context` | 恢复前取得规范 writer 并重验；persist=False 保持只读 |
| `harness.transcript.lifecycle.AgentTranscriptLifecycle` | 持久 create/restore 的统一 owner acquisition 与失败补偿 |
| `AgentTranscriptLifecycleSession._dispose_owned` | Product runtime 成功释放后再释放 writer；Graph owner 连续转移 |
| `harness.transcript.lifecycle.delete_agent_transcript_jsonl` | 非本 owner 的活跃会话删除 busy，不能只比较 current_session_file |
| `harness.transcript.product_session.ProductTranscriptSession.delete_session` | transcript 与附件清理使用同一被准入维护 authority |
| `harness.journal.jsonl.journal_file_lock[_at]` | 保留原短期读写锁，不替代 runtime writer lease |
| `coding.hosted_catalog` 与新的 managed catalog | 旧 profile 不放宽；新 profile canonical identity/scope 与 writer binding |

## 7. Harnesstui 与 wire 接缝

沿用已评审草案 §6.3–6.4。M3 共享完整 conversation view/presenter，分别
注入 Embedded binding 与 Hosted binding。中性端口不反向依赖这两个适配器；
Mux 外壳只负责成员/连接组合。主题与终端能力在客户端组合边注入。
输入 intent 不决定执行成功；请求投递、执行状态和 unknown 分别处理。
审批键包括 attachment/controller/member/Session/interaction/实际呈现内容，
不能跨 Tab 重用；总额与控制预留保持。工具富卡片/图片的协议增量不隐式启用。

## 8. 交付审计（持续更新，不代表已完成）

| 要求 | 当前证据 | 剩余工作 |
| --- | --- | --- |
| 独立分支与基线 | 分支已建立，30 个基线回归通过 | 后续增量相对基线验证 |
| M0 合同 | 三视角修订后通过；纯值/状态/路径 56 项测试、Ruff/mypy 通过 | native admission、持久 CAS、writer lease 等运行实现及验证 |
| M1 私有文件 owner | 文件准入、稳定锁、记录 CAS 与故障清理；三视角复审通过；文件测试 31 项通过 | 配额和公共发现/连接协调仍待接线 |
| M1 持久名称预留 | SQLite schema/namespace、名称与操作唯一、服务复用键、分页查询及崩溃恢复；三视角复审通过 | 操作结果对账与启动/停止编排尚未实现 |
| M2 代际协调 | per-service fence、持久 prepare/commit/abort/stop、三项结算事实及干净停止后换代 | native 启动交接、异常 retire/recovery admission、真实后台激活均未完成 |
| M2 Linux 退出观察 | boot/PID/start-time/实际 UID/PID namespace 与保留 pidfd；26 项原生回归、三视角复审通过 | 原生 spawn/handoff、进程树结算及异常恢复准入仍待接线 |
| 一条命令/后台/全局名/多 Tab/stop | 仅 G16 既有显式能力 | M1–M3 全部接线 |
| Session 唯一写入与默认历史 | 缺运行期跨进程合同实现 | writer lease + canonical catalog + 双进程测试 |
| 完整共享 Harnesstui/Markdown | 草案与本文接缝 | M3 代码与 Embedded 非回退 |
| 真实安装/断连/性能/三视角代码评审 | 未执行本目标验收 | M4 完整矩阵与本地提交 |

Goal 保持 active；当前尚未推送、创建 PR 或合并。最终交付包含用户后续
授权的推送、PR、合并及本地同步；跨平台自动后台仍不在范围内。

## 9. M0 具体合同与首个原子切片复审

三位独立 reviewer 对本文与首批未激活代码进行了只读评审：

- `lmux_arch_review`：通过；职责、SQLite/lock 权威、非破坏 adapter 保留
  v1 身份无冲突。纯值不执行 IO 或赋权，路径验证不冒充 native admission。
- `lmux_lifecycle_review`：修复原 2 项 P1（破坏性维护同 writer lease、leader
  与 scope 分离）和 2 项 P2（文件保留计费、SQLite 物理峰值）后通过。
- `lmux_ux_review`：修复原 2 项 P2（同步草案的 adapter 手段、continuity
  映射与合法 v1 身份规则）后通过。普通历史恢复目标保持完整。

首批代码 `src/loushang/apphost/managed/` 不导出根 facade、不安装命令、不
启动进程；`tests/apphost/test_managed_contracts.py` 与 `test_managed_paths.py`
共 56 passed。它们证明值/状态/布局，不证明并发数据库、真实进程、Session
唯一写入、终端或性能。本次后续运行阶段仍须三视角代码复审，不复用此结论
冒称整目标通过。

## 10. M1 私有文件 owner 切片

`apphost.managed._files` 只负责注入目录的 Linux 原生准入与有界小记录 IO，
不加载 Product、不激活 CLI、不解释认证或进程状态。逐级保留 no-follow
父目录 fd，先准入再相对创建；稳定 `.lock` 文件禁止被记录 write 替换，
每次操作与发布前复核持有锁的身份。锁只序列化遵循此协议的写入者，
不是针对同 UID 任意恶意进程的完整安全边界。

临时文件从 exclusive create 成功起由 owner 跟踪。发布前失败仅回收本次
可验证文件；发布后 fsync 失败报告 unknown，不能当作“没有写入”重放。
清理异常保留 primary 和有界诊断；unlink 后仍保留目录同步债务，完成
fsync 才结算。重试只同步目录，不删除后来出现的同名 replacement。

三位 reviewer 的原问题（父目录替换、锁替换后旧 owner 写入、锁/记录
命名混用、创建阶段临时文件遗漏、清理覆盖原始异常、同步债务提前释放）
均已修复并通过只读复审。此结论只覆盖文件切片，不覆盖后台进程或登记库。

最新聚焦运行：`test_managed_files.py`、`test_managed_contracts.py`、
`test_managed_paths.py`、`test_hosted_product_runtime_v1_baseline.py` 共
98 passed；其中新增文件测试 31 项，包含真实双进程 flock 与故障注入。
Ruff、managed 模块 mypy 通过。此前完整 AppHost 主测试 1431 passed / 12 skipped，
唯一失败是精确架构清单未登记新模块；清单已补齐并包含于上述 98 项复测。
不将这次聚焦成功写作完整 `check-apphost` 成功；剩余选中门禁单独补跑。
Hosting 主测试 384 passed / 48 skipped，唯一失败同样为另一份精确模块清单；
修复后该架构文件 8 passed。两处清单均只显式添加四个 managed 模块，
没有改成忽略新增模块。G8/G9/G10 pytest 与对应 manifest 验证分别为
19 / 16 / 15 passed，零跳过；G10 安装 canary 另外通过，后端为
`posix-process-group-v1`，不与上述计数混算。这是既有安装路径非回退证据，
不是 lmux 自动后台或 SSH 断连验收。文档 6 项、依赖图新鲜度与静态检查通过；
CI 计划提示的跨平台/host-runtime 验收仍不因这次本地切片而宣称完成。

## 11. M1 SQLite 名称预留切片

`ManagedRegistryV1` 接受已注入目录与 namespace，提供 `reserve_mux`、`resolve`
和有界 `list_muxes`。返回值是创建意图，不是已创建的 Mux 或运行实例，
不带 PID、连接凭据或 ready 状态。相同 operation 只可重查完整相同意图；
其他操作抢占同名或复用同 operation 则拒绝。服务键与名称在一个事务提交，
失败不留下孤儿服务记录。现有名称不因不可连接、进程退出或客户端 cwd 改变而删除。

实现采用固定 schema、namespace 身份和 DELETE/FULL SQLite，拒绝未知表、
索引、版本、关联损坏和未知/不安全 sidecar。服务 128、名称/意图 4096、分页
64 的边界独立于数据库物理容量检查；增长前保守预留现有全部页 journal、
新页、辅助与控制空间。不使用 WAL，也不把 journal_size_limit 当作运行期
总配额。日志/tmp 预留、实例表与停止控制紧急事务尚未实现。

普通观察以 `mode=ro` 打开数据库；需要 hot journal 恢复时失败且不改文件。
显式可写 owner 在稳定锁内恢复。每次连接短寿命，SQL deadline 与内容/列/
变量上限有界，不向公共客户端暴露 SQL。关闭失败保留 SQLite owner；检查
债务、重试和目录关闭使用同一 mutex，支持串行化的跨线程重试。

三视角复审修复并通过：满盘下相同意图仍可重查；连接关闭失败保留债务；
并发 close 不跳过刚产生的债务。真实进程死亡测试强制缓存溢写，先验证
主库确有未提交修改、只读观察不改 DB/journal，再证明显式恢复还原全部
数据库字节和 21 个名称，不能用内存事务消失代替热日志恢复。

此切片保持未组合/未安装，不修改旧 G16/G17 入口或现有 Session 读写。
验证以新增数据库/登记库与已有 managed 文件/合同、两份精确架构清单为范围；
后续完整运行接线仍须广泛门禁、真实 lmux 安装/断连与性能验收。
本次聚焦共 125 passed（其中登记库 19 项），Ruff、managed 六个模块 mypy、
依赖图新鲜度通过。未重复将未改动的 Product/终端路径广泛套件算作本切片
新证据；完整远端门禁仍是最终 PR 合并前置。

## 12. M2 持久代际协调切片

`ManagedServiceJournalV1` 借用 registry，拥有独立的每服务 lifecycle 目录；
锁顺序固定为服务 fence → 短 registry 事务，数据库提交前再次验证服务锁
身份。不持锁等待 RPC 或进程。组合入口必须保证同 namespace/service
恒映射同一个稳定 lifecycle 根，不能由 runtime 覆盖改变此根。

实例记录进入私有 SQLite schema v2；尚未激活的 v1 测试库显式拒绝，
不静默迁移。格式版本与公共 `V1` API 版本分离。记录包含完整 instance/
attempt、单调 revision、handoff phase、stop fence 和三项结算观察，不含
PID 或连接 authority。prepare 需完整匹配旧观察；commit 回复丢失只能读取
当前状态，不能因此重复 spawn 或 abort 已提交实例。迟到的旧实例请求不能
修改新代；停止事实按同一实例单调汇合，控制更新可使用保留容量。

三视角确认此事务/竞态切片通过，但生命周期评审保留一个 **P2 激活前置**：
当前 prepare 只允许干净停止后的复用。真实崩溃后即使精确确认 leader/scope
退出，也不能伪造 `application_cleanup_completed=True`。异常实例的
retire/recovery admission 必须另行实现：区分干净停止成功与安全恢复准入，
保留 unclean 诊断，取得旧资源及 Session 写入权安全回收证明后，才允许
进入 G13 恢复。该工作属于原完整目标，不能因当前严格拒绝换代就删去。

本切片不声称实现了 native 后台、服务崩溃后 start、真实 SSH 续存或进程
终止权限。下一阶段需将 native handoff 和异常恢复准入共同接入，再执行
父死/子死/后代存活/断连矩阵。

本次全部 managed 与两份精确架构清单共 137 passed，其中 lifecycle 12 项；
Ruff、managed 七模块 mypy、文档 6 项与依赖图新鲜度通过。三视角允许当前
未激活切片本地提交，异常恢复 P2 仍未关闭，不作为最终交付通过依据。

## 13. M2 Linux 身份与退出观察

可选 `hosting.service` 新增 `LinuxServiceIdentityV1` 与
`LinuxServiceObserverV1.capture/reopen/exited/close`。身份值只是定位事实；
reopen 必须重新验证 boot、PID/start-time、实际 UID、调用者 PID namespace，
在 pidfd 获取前后双观察并绑定 fdinfo PID。`/proc` 缺失或 PID 记录存在均
不能推断当前退出；只以保留 pidfd 的退出事件给出 leader/thread-group 事实。

实际 UID 从保留 proc 目录 fd 下的 status 读取，不能由目录 owner 替代；
该 same-user profile 要求 real/effective/saved/fs UID 一致且匹配调用者。
本机 standalone uv Python 没有 `os.pidfd_open`，但 libc 支持同一 API；
采用 Linux-only、lazy libc 适配，不猜系统调用号、不退回 PID 轮询。

等待预算包含 mutex 获取与 poll；关闭先设置 fence 阻止新等待，未及时取得
锁时保留句柄供重试。close 只关观察句柄，不发任何信号。主进程退出、后代
继续持有资源时不得宣称 scope 或应用已结算。此模块无 AppHost/AppServer/
Product 依赖，不从 Hosting 根 facade 激活，不改变既有 ProcessLease.close。

三视角指出并修复：真实 UID 与目录 owner 的区别、超大整数 timeout 的
封闭错误校验、mutex 等待预算及并发 close fence。26 项真实 Linux 测试
通过，含独立新客户端 reopen、身份变化拒绝与 fd 回收、主进程退出但后代
仍活、关闭不发信号、无效/巨大 timeout 和并发等待/关闭；Ruff/mypy 通过。
这不是 SSH 断连验收、后台 spawn 或异常恢复 P2 的完成证据。

原生语义依据：[pidfd_open](https://man7.org/linux/man-pages/man2/pidfd_open.2.html)、
[proc stat](https://man7.org/linux/man-pages/man5/proc_pid_stat.5.html) 与
[proc 所有者](https://man7.org/linux/man-pages/man5/proc_pid.5.html)。

完整 Hosting 主测试 410 passed / 48 skipped，唯一失败为 H0 精确模块清单
未登记可选 `service.py`。已显式补清单且新增不从根 facade 导入观察器的
断言，H0 与交付清单聚焦复测 15 passed；Hosting Ruff/mypy 27 模块、
文档 6 项与依赖图新鲜度通过。不将该聚焦修复标为完整 check-hosting 命令
重跑成功。CI 计划选中的更广泛消费者/跨平台门禁仍是最终集成前置。
