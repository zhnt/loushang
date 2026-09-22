# lmux M0：受管部署与共享会话接缝

[Proposal](../drafts/lmux-managed-service-design.md) · [AppHost](README.md) ·
[Hosting boundary](../hosting/key-designs/hosted-application-support-boundary.md)

## Status

- ID: `LMUX-M0`
- Authority: normative — accepted limited Linux managed-profile contract
- Design status: accepted
- Review status: three-perspective slice reviews passed through recovery/close and shared deferred input; final goal-wide review pending
- Implementation status: partial — managed CLI preview, Linux launch/lifetime, owned transcripts, discovery, exact-instance connections, close and shared Markdown/action/input binding; full M3/M4 acceptance pending
- Owner: AppHost managed deployment; sibling changes remain sibling-owned
- Tracking objective: active Linux lmux goal, branch `harness/lmux-managed-service`

## 1. 本地基线与推进记录

起点 `1286348e`，保留已评审 lmux 草案；独立任务分支。
该起点原为 `harness/linux-interactive-startup-v2` 的顶端。该 G18 phase-two
工作在 v2 文档中自述两个 20% 主目标未达成、仅本地交付，不属于 lmux 目标；
已由 `git rebase --onto main 1286348e` 从本分支剥离，交由 v2 单独决定去向。
剥离后本分支保留的 11 个提交经 `git range-diff` 逐项确认为机械等价（11/11 为 `=`），
基线随之改为剥离后的 `main`。
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

writer lease 放在 canonical session root 下的私有 owner namespace，逻辑授权
绑定 Product+conversation ID，物理互斥域为 root+conversation ID（见 §24）。读取/发现不取得 writer 权；持久创建/
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
| M0 合同 | 三视角修订后通过；纯值/状态/路径 56 项测试、Ruff/mypy 通过；后续实现见以下各行及 §20 | 完整 M1–M4 生产接线与最终验收 |
| M1 私有文件 owner | 文件准入、稳定锁、记录 CAS、deferred first admission 与不确定关闭债务；三视角复审通过 | 配额和公共发现/连接协调仍待接线 |
| M1 持久名称预留 | SQLite schema/namespace、名称与操作唯一、服务复用键、分页查询及崩溃恢复；三视角复审通过 | 操作结果对账与启动/停止编排尚未实现 |
| M2 代际协调 | per-service fence、持久 prepare/commit/abort/stop、三项结算事实及干净停止后换代 | 异常 retire/recovery admission 与生产启动/停止编排未完成 |
| M2 Linux 退出观察 | boot/PID/start-time/实际 UID/PID namespace 与保留 pidfd；原生回归、三视角复审通过 | 退出、进程树结算及异常恢复准入的生产编排仍待接线 |
| M2 持久交接接线 | 继承通道 + exact instance/attempt journal port；真实启动器退出和 EOF/CAS 竞争测试；实际 Coding 后台组合见 §19/20 | 生产 process entry/EnsureStarted、异常恢复及 SSH 验收未完成 |
| M2 Linux 创建 owner | 单次生产 Popen 创建、受管 FD/环境/工作区、复用 POSIX group 观察；真实父端退出和故障矩阵、三视角复审通过 | installed 编排、异常恢复和 CLI 激活仍待完成 |
| M2 birth binding | schema v3 原生身份登记、精确匹配的 commit/abort；117 项聚焦验证、三视角复审通过 | 异常退役恢复、Session writer lease 与完整前端接线仍待完成 |
| M2 应用准备/激活 | 原 AppServer/AppHost/Coding owner 的两步启动、共享截止时间和同步 fence；child owner 已在两步间接入 durable commit | 统一生产入口未完成；CLI 不自动启动 |
| M2 子端应用 owner | 实际 Coding prepare/commit/activate、独立 IO/stop/cleanup；启动器正常/骤退后任务续行、重连、认证 stop 已有真实进程证据 | installed composition、异常恢复与完整 SSH 验收仍待完成 |
| M2 子端 bootstrap | 公共 layout/deferred 资源装配、精确自身份绑定与依赖关闭顺序；bootstrap/实际后台/通道回归 57 passed | 生产 process entry、公共协调器和默认资源策略仍待接线 |
| 一条命令/后台/全局名/多 Tab/stop | 仅 G16 既有显式能力 | M1–M3 全部接线 |
| Session 唯一写入与默认历史 | 单根 writer primitive、真实进程/fork/崩溃 20 项验证及三视角复审通过（§24）；尚未接运行期 | 全写入口/附件联合占用 + canonical catalog + Embedded↔Hosted 验收 |
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

`apphost.managed._files` 只负责注入目录的 Linux 原生准入、有界小记录 IO
及原 owner 上的有界数据追加（§83），
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

## 14. M2 继承通道与持久交接接线

可选 `hosting.service_handoff` 拥有继承的 Unix stream socket，借用中性
handoff port；`apphost.managed.handoff` 将该端口绑定至精确 instance/attempt
的 journal。子端准备完成后提出 commit，父端只观察或提出 abort；消息字节
只用于唤醒，既不是 ready 证明，也不产生停止权限。父端退出后，子端仅在
持久结果为 ABORTING 时才能进行启动收口；UNKNOWN 保留所有权及待对账义务。

**竞争以持久 CAS 为准**：先看到 EOF 的子端提出 abort；存活检查后、CAS 前
父端退出时，commit 与 abort 都可能先赢。不能将物理退出瞬间等同于已持久
abort，不能因迟到 EOF 或丢失 ack 撤销 COMMITTED。stop fence 只阻止新的
commit，不伪造 ABORTING；应用 owner 还需显式 abort 或处理已提交服务停止。

三视角要求修复共享预算：同一 absolute monotonic deadline 贯穿 channel
mutex、端口、service/registry mutex、SQL progress 与失败后重查，耗尽后不
再开新 IO；timeout=0 返回 UNKNOWN 而不读库。已有同步 OS IO/fsync 不可由
Python 抢占，这只是协作式预算，不承诺内核调用硬超时；不引入无人接管的
后台线程，不因时间耗尽丢弃已接纳操作的结算责任。既有无 deadline 的存储
API 保持原语义。应用/UI 接线必须由专属启动 owner 执行这些同步操作。

测试分别覆盖：真实启动器退出前后，子进程在同一持久库确认 ABORTING 或
COMMITTED；独立测试控制通道负责释放子进程，不借此伪称应用清理完成。
确定性插入 EOF 到存活检查与 CAS 之间，覆盖两个 CAS 获胜顺序；另测错代、
ack 丢失、事务提交后错误对账、锁/SQL 预算耗尽、到期回滚与并发 close fence。
本切片仍不提供生产 spawn/daemon、公共连接协调、异常 recovery admission，
更不是 SSH/完整产品交互的交付证据；§12 异常退役 P2 仍为激活前置。

三视角复审通过；聚焦交接与受影响存储回归 102 passed。加固后的事务到期
回滚用例同步控制两个时钟，并要求确实执行 `_save`，避免在写入前就超时
产生假通过。Hosting 主回归 434 passed / 48 skipped，唯一失败为旧 PLC
精确消费者清单未登记新 adapter；显式登记模块和唯一公共导入 symbol 后，
对应失败节点复测 1 passed。不扩大对 Hosting 私有 launch profile 的准入。
Hosting Ruff/mypy 28 模块、AppHost Ruff/mypy 107 模块、文档 6 项和依赖图
新鲜度通过。较大范围 AppHost 主回归结束：1508 passed / 12 skipped，
两处失败均为旧 G9/G10 精确依赖清单只登记 foreground launcher；现为
managed handoff 单独登记唯一公共 Hosting 依赖，对应两个节点已在 §15
聚焦 69 项回归中通过。
最终 native/installed 和完整 change-aware/远端门禁仍在整体交付前完成，
不将本切片检查冒称全通过。

## 15. M2 Linux 原生创建接线

`LinuxServiceProcessV1` 在 native effect 前先成为调用者持有的 owner；只允许
一次创建，完整绝对 executable/argv/cwd/environment、独立 POSIX session、
标准流 `/dev/null`、仅继承一个显式 startup socket。不接受 pipe/capture 的
静默降级，不导入 Mux/AppServer，也不充当 H6 sealed plugin preparation
失败后的 fallback。该 local-managed profile 启动受信任的已安装服务入口。

采用同步 Popen 的专属 owner，避免父解释器关闭 asyncio transport 时终止
服务。保留原 `_PosixProcess` 进程组机制，通过结构协议接入自己的 Popen；
只有实际 reap 后才提供 returncode，不把 pidfd 的 exited 等同于已 reap。
创建错误不产生“证明未创建”的收据，禁止重复 spawn；身份捕获失败仍保留
已经附着的 Popen 与 scope。close 只回收父端句柄并封闭创建，不发信号。
进程组退出、父端句柄回收、应用 lease-last 成功仍为三个独立观察；逃逸出
受控 scope 的子资源需要自己的 owner，不扫描全机器猜测归属。

真实 durable-handoff 测试改用该启动器，覆盖父端正常解释器退出与骤退；
标准流/控制终端、完整环境、FD 白名单、close/spawn 竞争和 leader 退出而
后代仍存活单独测试。本机制尚未接入 CLI、Product 应用 owner、身份持久
登记与异常恢复准入；不是一键启动、真实 SSH 或完整 lmux 交付完成证据。

机制依据：[Python Popen](https://docs.python.org/3/library/subprocess.html#subprocess.Popen)
和 [setsid](https://man7.org/linux/man-pages/man2/setsid.2.html)。原生创建与 OS IO
不能承诺被 Python timeout 抢占；外层启动预算到期不能抛弃仍持有的 owner。

三视角复审通过。修复了 observer 关闭失败时跳过独立 socket 回收的问题：
各自尝试关闭，保留失败 owner 与未完成状态，支持重试而不发信号。真实
子进程测试补齐显式环境覆盖/空值/Unicode、父环境不继承及指定 cwd；取消
发生于 capture 后时，也验证了关闭故障、socket 释放与随后重试。

聚焦 69 passed，包含新启动器、既有 POSIX process、四种正常/骤退父端的
持久交接，以及 G9/G10/H0/current inventory。完整 `check-hosting` 通过：
457 passed / 48 skipped，Ruff 与 mypy 29 模块通过；文档 6 项与依赖图
新鲜度通过。未重复未改动的整套 AppHost 1508 项通过用例；其两个旧清单
失败已精准修复并复测。不将本机制结论扩展为完整 installed/SSH 验收。

## 16. M2 持久原生身份与提交准入

实例行升级为未激活 schema v3，新增有界、规范 JSON 编码的原生身份；
v1/v2 库显式拒绝，不自动迁移。直接复用 Hosting 的不可变 Linux 身份值，
不再复制一套 PID/start-time/boot/UID/namespace 字段协议。该依赖仅存在于
可选 Linux managed lifecycle/handoff 两个模块，核心 contracts 与根 facade
不增加 Hosting 依赖；架构清单按模块及 symbol 精确登记。

可信启动 owner 捕获身份后，以同一 instance/attempt 登记。首次登记要求
provisional 且没有 stop fence；同值重试幂等，不同值不得覆盖。commit 必须
携带子端自己的 native identity，并与持久登记完全匹配；仅有实例号、PID
文本或 ready 通知不足以提交。读到身份也不是 liveness、scope 结算或 signal
权限，新客户端仍须用 Hosting 重新验证。干净换代在同一事务中清空旧身份，
不会把旧原生观察沿用到新实例。

未绑定 native 的 starter port 可观察和按精确 attempt 提出 abort，不能
commit。绑定 native 的 child port 在登记出现后，observe/commit/abort 均
要求匹配；其中 abort 前置检查与状态变更必须在同一 fence 事务中，不能
先修改后再返回 UNKNOWN。登记前的 EOF 仍允许 provisional child 提出
abort，之后迟到的登记被拒绝。正常/骤退父端的四种真实测试均使用生产
launcher 的捕获值登记，子端独立捕获自身身份，验证两个观察与持久值一致。

这仅完成 birth binding 与交接准入，不代表应用自持 owner、异常退役恢复、
Session writer lease、公共发现/连接或 CLI 激活已经完成。

三视角指出并修复了 wrong-native abort 的事后拒绝问题：原生匹配检查
与修改在同一事务中完成，返回 UNKNOWN 不再掩盖已发生的状态修改。
三视角复审通过；聚焦生命周期/交接/registry/file 及精确 G9/G10/C50/current
inventory 共 117 passed，Ruff、managed 八模块 mypy、文档 6 项、依赖图
新鲜度通过。没有重复未改动的 Hosting 原生实现与 Product/UI 广泛套件，
完整 change-aware、真实安装/SSH/性能与最终三视角交付仍在整体目标内。

## 17. M2 应用准备与接客分离

现有 `CodingLocalCommandV1.start()` 会恢复 Product、启用 client scopes 并发布
可连接的服务，再由调用者宣告 ready。受管子端不能在这个已接客状态等待
持久 handoff，否则交接前已经可能接受无法归属的请求。公共协调器只检查
COMMITTED 也不够：旧显式连接入口仍可能直接读到 connection record。

采用同一部署 owner 的可选两步启动，而不是新建第二套 Coding runtime：

- AppServer 增加 `prepare()` 与 `activate()`：prepare 保留 endpoint reservation、
  绑定原生 listener，但不生成/发布当前实例 record、不开始 serving；
  activate 才生成认证 record、发布并开始 serving。原 `start()` 依次执行两步，
  默认行为不变。准备期间可能存在旧崩溃实例的残留 record；不为“不可发现”
  删除未知旧文件，旧 record 也不构成当前实例 ready 证明。
- AppHost `HostedLocalRuntimeV1.prepare()` 先准备 listener，保持 client scopes
  禁用；`activate()` 才启用 scopes 并激活 server。`accepting` 仅在 activate
  完成后为真。保留启动/关闭的单 owner、任务保留、取消不遗弃、lease-last
  和原有 G16 stop/EOF 语义。准备中的 stop 与 close 永远禁止迟到 activate。
- Coding trusted composition 暴露相同 prepare/activate 接缝，仍由原 attempt
  构造实际应用；旧 `start()/run()` 路径不需要调用者变更。两步共用一次启动
  预算，不能在 activate 重置 30 秒预算；显式 close 重试仍遵循原合同。
  Coding 在 Product 恢复前冻结 absolute monotonic deadline，原样向下传递为
  共同上限（各层既有更紧 profile 上限可以缩短，不能延长）。prepare 与
  activate 之间的外部交接时间计入预算；启用 scopes、发布、serving 前及
  ready 返回前均检查 fence 与期限。OS IO 不能被该预算硬抢占。

保留的是底层 prepare/activate 阶段任务，不是会在异常路径调用自身 close
  的公共 start/prepare/activate waiter。close 等待前者并接管迟到资源，避免
  环形等待；取消 waiter 不取消已拥有的阶段任务。API 顺序固定为一次
  prepare、随后一次 activate；prepare 重复、未完成 prepare 就 activate、
  重复 activate、prepare 后再 start、并发争用均拒绝后来的不合法调用，
  不撤销先前合法阶段、不恢复第二份 Product、不重新发布。close 在任何
  阶段均同步 fence；关闭后两步均拒绝，失败 owner 只能重试 cleanup。
  一步 start 在首次 await 前保留两个阶段；外来 split activate 不能抢占
  prepare 完成到原 start 恢复之间的窗口。绝对 deadline 只允许精确 int/float
  且 `0 < deadline <= 1e12`，拒绝 bool、NaN、无穷和巨大整数，校验前无 IO。

随后受管 child owner 将按“准备应用 → 子端精确身份的持久 commit → activate”
  执行。COMMITTED 是寿命交接，尚不是可连接确认；协调器需要重新认证后才
  返回连接 lease。提交与 activate 之间崩溃保留 committed/unclean，对账不得
  重新 spawn。activate 失败是服务自己的启动故障，需 graceful close 和精确
  stop 记录，而不是启动器因超时撤销 committed。准备期间 EOF/abort 时由该
  应用 owner 关闭已准备的 listener 与 Product，完整完成后才记录应用清理。

本接缝只实现两步应用启动，不宣称完整 child owner、公共协调器、writer lease
  或异常退役 P2 已完成。验收包括真实 loopback 的 prepare 无当前 record/不可用
  （同时测空目录和残留旧 record，旧地址/认证不能进入当前实例语义）、
  activate 后认证连接与旧 start 等价，以及 prepare/activate/close 的取消、
  故障、晚到结果、重复调用与共享预算。AppServer 仍不知道 managed/Hosting/
  Mux 生命周期；它只实现通用显式发布时序。

设计与代码分别三视角复审通过。代码复审修复三处 P2：一步 start 的第二
  阶段被外来 activate 抢占、Coding close 排队期间未同步 fence 已接管服务、
  巨大整数 deadline 的 float 转换异常。AppHost 新增纯同步 `fence()`，由
  Coding 在建立 close task 前调用；它不转移 cleanup 所有权，不丢已有 stop
  reply，也不自动创建任务。对应确定性竞争、task factory 失败和三层非法
  deadline 负测均已补齐。修复后本地阶段/认证/生命周期聚焦 76 passed。

G16 两个既有源码行数门禁按架构复审确认的精确增量更新：相对 `0351f8b0`，
  AppServer local 从 392 到 463 行（旧上限 450 + 71），AppHost local 从
  247 到 327 行（旧上限 300 + 80）。只计本次两阶段 owner/同步 fence 增量，
  保持原余量，不作文件豁免；额外锁定 prepare/activate/fence 的公开签名。
  既有依赖方向、native IO confinement、连接容量与默认入口断言全部保留。

广泛协议、真实 Product/CLI、旧 Mux 外壳与架构回归结果为 406 passed /
  10 skipped，两个失败仅为上述旧 G16 行数上限；更新后该文件连同新增
  签名检查复测 9 passed。没有将该聚焦复测写成整条广泛命令重跑通过。
  当前三份源文件 mypy、全部修改代码/测试 Ruff、文档 6 项与依赖图新鲜度
  均通过。首次残留 record 测试因 fixture 使用非法空 scope 而失败，补合法
  scope 后真实崩溃遗留/旧认证拒绝用例已包含在通过结果中。

本切片不发布自动后台入口，未运行整个完整目标的 installed/SSH/首用性能
  矩阵，也不替代最终 change-aware/远端门禁。完整 child owner、异常退役、
  唯一 writer、公共协调器、配额与 Harnesstui 接线仍为 active goal 的后续工作。

## 18. M2 受管子端应用 owner

受管子进程采用 AppHost 可选 `managed.child` owner，注入同一份实际应用
  的 prepare/activate/fence/close/wait_closed/cleanup_pending 中性端口，不导入
  Coding、Harnesstui 或 CLI。Coding 原 command 增加同步 fence，复用 §17
  同一 AppHost owner。原 foreground/G16 入口不选择本 owner。

owner 在准备前已被 child composition 持有。一次运行保留 Product prepare、
  activate、服务 wait_closed 和 cleanup 的精确任务；公开 run 的取消仅取消
  waiter，不终止该服务，不取消阶段任务。公开 close 是 child 自身的明确
  graceful-stop authority，不是 starter 取消或 client EOF 的传播入口。
  该调用同步 fence 已拥有的应用，保留未完成任务及失败清理，显式有界
  retry_timeout 才能更新已结束的 cleanup attempt 的预算。

启动循环先验证绑定的 instance/attempt/native，再准备应用，同时轮询继承
  通道。准备中确认 ABORTING 才因父端 EOF/启动取消回滚；UNKNOWN 时不另开
  应用，不重新 spawn，也不丢弃已准备 owner。starter 等待/交接观察期限耗尽
  只提出 abort，不能把超时变成已确认的 ABORTING。应用 prepare/activate
  自身失败（含其独立启动期限耗尽）属于下述 child 自主故障，可以自行关闭；
  不把原 §17 端口的自动清理错误解释成父端已获得 rollback authority。
  prepare 成功且应用启动 deadline 未耗尽后子端提出 durable commit；
  确认 COMMITTED 后才 activate，随后彻底忽略启动器通道 EOF。commit 后仍
  观察该精确实例 stop fence 与应用的 wait_closed，不将未知观察当作停止。
  应用 deadline 耗尽后不再新提 commit/activate；后续对账和 abort 使用单独
  有界 IO 预算，但绝不续应用启动期限。commit 已落盘而确认到达太晚时，
  子端按自身启动失败停止，不改写成父端回滚成功。

应用内部失败和显式 child close 是服务自己的终止原因，与“启动器因为
  未收到 ack 要回滚”分开。它们可同步 fence 自己的应用、执行 graceful
  cleanup，同时提交该实例 stop/abort；数据库不可用不能阻塞实际已拥有
  资源的安全关闭，但记录保持 unknown/unclean，不能返回已证明干净停止。
  cleanup_pending 为假且完整应用 close 成功后才能提交 application cleanup
  事实；子端绝不宣称自己已经 process_exited 或 scope_settled。记录失败
  保留本地完成事实和精确 owner，重试只补交事实，不重跑已成功的清理。

同步 channel/journal IO 由该 owner 持有的单工作线程串行执行，全部 job/future
  被保留并 shield；一次最多一个任务，不建立无界队列。取消 waiter、到期
  或 close 均不丢掉仍在 native IO 中的 future；仅在它完成后关闭 channel
  并回收 executor，借用的 journal/registry 由外层 composition 最后关闭。
  单次 absolute monotonic IO deadline 贯穿 channel、journal 与失败重查；
  不承诺抢占 OS fsync。不存在 native IO 从 UI/应用事件循环同步执行的路径。
  close 同步 fence 并立即启动应用自身 cleanup，不等待在途 journal job；
  只有控制句柄/executor 回收与持久事实提交等待该 job 结算。应用超时且
  journal unknown、commit 确认晚于应用 deadline 必须有单独负测。

可选 managed control adapter 对 child 的 stop/cleanup 写入同样使用原子
  native 匹配，不能先读匹配再按 instance-only 修改。登记前的同 attempt
  abort/cleanup 保持可结算，登记后的错 native 不能污染事实；父端/外部
  trusted stop observer 的旧 instance-only 方法保持原合同。

验收需覆盖实际 Coding prepare→commit→activate/认证、准备中父端 EOF、
  commit 后启动器退出与接受工作续行、stop/activate 竞争、未知提交后重查、
  取消 run waiter、应用/记录清理失败及重试、原生 IO 挂起时关闭不丢 future。
  本 owner 不等于公共 EnsureStarted、异常退役恢复或 CLI 激活；这些仍须
  满足完整目标既定准入后再组合发布。

设计与代码三视角复审通过。复审修复了内部调度异常绕过 cleanup、挂起
  native IO 阻挡应用自主终止，以及清理失败阻挡 stop 水位提交的问题。
  runner 保留异常边界；独立 observation task 与 prepare/activate/wait_closed/
  deadline 并列观察，激活完成后立即建立应用终止任务，不等控制读取完成。
  stop task 与应用 cleanup 独立启动，通过同一工作线程串行进入控制 IO，
  不覆盖旧 job/future；明确的新预算仅在旧 stop job 完成后补交。成功应用
  cleanup 不重跑，channel/executor 最后回收；journal/registry 仍由外层保留。

`request_child_stop` 和 `record_child_cleanup` 是两个窄写入口：前者在
  provisional 原子 abort+stop，committed 只 stop；后者只可写应用完成位，
  原生与 attempt 检查和修改共用事务。登记前可以结算 abort，之后禁止迟到
  登记；错 UID 在 control 接管 socket 前被拒绝。原 observer 的三事实接口
  没有变成任意 child 可调用的进程退出声明。child channel 还接收原 absolute
  deadline，防止计算 remaining 后的线程调度延长 commit 窗口；旧缺省调用
  不变，过期不进行 port IO。

当前验证：111 项 child/lifecycle/handoff/旧 Coding ownership 聚焦回归通过；
  真实 Coding 认证及对应精确架构/inventory 回归 54 passed；补齐实际 Coding
  自身超时且 journal unknown，以及绝对 deadline 后，相关回归 49 passed。
  三视角另确认上述 deadline 小修。Ruff、11 模块 mypy 与依赖图新鲜度通过。
  第一版真实 Coding fixture 缺少 attach 前置、超时 fixture 对 frozen attempt
  实例 patch 方法而失败，均修正为合法协议/类方法故障注入后通过；不把
  fixture 错误作为产品失败或隐藏跳过。末次 prebirth/错 UID 与持久状态聚焦
  回归 68 passed，文档 6 项通过。以上是不同范围的分次回归，不相加宣称
  全新覆盖量，也不是完整 change-aware 或最终 installed 门禁已经通过。

真实 Coding 用受控 synthetic model 挂住已接纳请求，关闭继承 startup socket
  与客户端连接，再以新认证连接读取同一 Session 的完成结果；模型调用
  计数为一次，最后通过认证 stop 完成应用清理。这里实际运行的是 Product、
  TCP 认证与 Session 工作 owner，但 application/controller 仍在测试解释器；
  不能把 socket EOF 测试称为已完成独立 daemon/SSH 验收。先前 Popen 父死
  原生用例也不能替代下一步实际 child entry 的组合验证。完整默认目录、
  writer、异常退役、配额、公共协调器、CLI、完整 Harnesstui 与 installed/SSH/
  性能矩阵仍在原 goal 内；本切片不提前 push/merge。

## 19. 实际 detached Product 组合证据

`tests/coding/test_managed_detached.py` 将实际 Coding command、managed child
  owner、认证 listener 和 Session 放进独立解释器；启动器使用既有
  LinuxServiceProcessV1，仅继承 startup socket，标准流为 DEVNULL。
  分别覆盖启动器正常关闭父端句柄后退出，以及直接 `os._exit(0)`。
  请求进入受控 synthetic model 后才退出启动器，再断开客户端、重新认证
  attach 同一 Mux，读取仍在运行的 Session，释放模型并确认调用次数为一。
  通过认证 stop 后观察 exact pidfd 退出，并检查持久 application cleanup
  位；不把该观察伪造成已持久登记 process/scope settled。

测试辅助子端 `_managed_product_child.py` 自行连接一个测试专用控制 socket，
  用于模型释放、计数及失败路径 graceful close，不增加启动器继承 fd。
  初版使用的启动登记 barrier 已由 §20 的公共 bootstrap 接线移除；迟到
  登记与受控真实锁竞争独立验证，测试观察字节不替代 durable commit。
  watchdog 强制退出只代表测试失败，绝非干净停止证明。此组合不是安装后
  CLI、真实 SSH/HUP、默认目录、writer、异常恢复或完整 Harnesstui 验收；
  上述完整 goal 的剩余项不变。

三视角复审通过，修正测试失败清理、投影唯一性和诊断证据缺口：
  重连前、运行中和完成后的 Session identity 相同，assistant records 精确
  为单条目标回复；helper 全部依赖清理成功后才发送完成回执，正常路径
  同时要求该回执、持久应用事实与实际进程退出。控制任务异常受到监督，
  专门负测要求 EOF 无完成回执、精确进程退出及私有诊断中的异常。
  子端自行建立 0600 测试诊断文件，记录阶段、异常和 watchdog；不新增
  继承 fd。测试失败时独立清理客户端和 observer，并等待子端 watchdog
  范围内的退出；测试自有 starter 的 terminate/kill/reap 兜底保留失败，
  不是生产 force-stop 能力，也不补写任何成功事实。

验证：最初正常/直接退出 2 passed；强化断言及已有实际 Coding child
  回归合跑 4 passed；最终新增 controller 故障负测后 detached 聚焦
  3 passed。Ruff、diff whitespace 检查与文档 6 项通过。未宣称完整
  change-aware 门禁或最终 installed 验收通过；生产入口与公共协调器
  等剩余项仍待实施。

## 20. 子端生产装配资源边界（bootstrap 已实施，生产入口待接线）

接缝为 AppHost `managed/bootstrap.py`：Product-neutral 子端资源 owner，
  不是命令解析器、服务发现、starter 或 Product 工厂。Coding 的后续 process
  entry 负责选择 Product 与 Session 配置，复用该 owner 打开公共控制资源。
  对外入口与默认策略仍须满足 writer/recovery/配额等原有准入条件。

输入为已规范化的 namespace/service/instance/attempt/runtime_root，全部
  路径只经现有 managed layout 推导，不接受调用者另填 registry/fence 路径。
  这些值不携带凭据，不构成权限。构造前做纯值、UID 和 socket 形状验证；
  成功构造后接管唯一继承 startup socket，且禁止它再次被继承。调用者在
  open 前保留这个 owner；构造不打开数据库、不创建 Product 或任务。

首次资源准入前提：PrivateManagedDirectory、ManagedDatabase、Registry 与
  Journal 增加显式 deferred-open 接缝，由正常构造器建立可保留的纯资源
  容器，不用外部 `__new__` 拼装。首次目录准入、锁、SQLite 检查及 journal
  读共享 bootstrap 冻结的 absolute deadline；原有 eager 构造调用兼容。
  deferred open 不在异常路径隐式销毁 owner；失败后必须显式结算已经
  接纳的资源，再由 bootstrap 在同一原始期限内分配新的 unopened 容器。
  无法确认已释放的句柄保持 cleanup debt，不能通过重复 close 返回成功
  清掉证据，也不盲目关闭可能已被重用的原生 fd。

`open(deadline=...)` 是专用后台子进程 bootstrap 阶段的同步操作，不在 UI
  或应用事件循环中调用。它只打开现有 registry/fence，不创建命名意图或
  代际；捕获自己的 native identity，核对 exact instance/attempt 及已登记
  native（如有），然后建立现有 child control。没有登记时仍可保留绑定，
  但只有后续 native 完全匹配且持久 commit 成功才能接客，不能靠 barrier
  或消息字节确认。失败保留已经接纳的资源，允许显式再次 open；不重复
  接管已打开的资源，不放宽首个绝对 deadline，也不自动重建或换代。

`bind(application)` 仅接纳已构造且尚未运行的中立 application port，发布
  一个既有 ManagedChildApplicationV1；成功一次后禁止替换。此后 socket
  的 close 归 child owner，通过它结算 control IO。bootstrap 不直接运行、
  取消或关闭应用，也不推断其进程退出。bootstrap.close 在 child owner
  仍 cleanup_pending 时拒绝，不提前关闭其借用的 journal/registry；应用
  owner 完成后按 control、native observer、journal、registry 顺序释放。
  未 bind 时允许直接回收控制资源。每项失败保留准确句柄供重试，独立
  observer 回收不阻挡其他安全的清理；journal 未关闭不得关闭 registry。
  不发布虚假的 cleanup 事实，不发信号，不采用 destructor 做服务终止。

调用矩阵：首次 open 成功后再次 open、bind-before-open、bind 后 open、
  重复 bind（包括同一 application）均拒绝，零新增 IO、零重复接管。
  构造失败时 socket 仍归调用者；bind 失败时 application 仍归调用者。
  “尚未运行的 application”是可信 composition 前置条件，不检查 Product
  私有字段。child pending 时拒绝 close 不进入终止状态；一旦获准 close
  就永久 fence open/bind，即使某项 close 失败也只能重试 close。未 bind
  也遵守相同的终止规则，不能 close 后复活。

这不是重建第二套异步生命周期状态机：应用任务、首次启动期限、控制
  worker、stop 和 cleanup 重试继续由已有 child owner 持有。bootstrap
  open 有独立的准备期限；产品 prepare/commit/activate 共用其原有期限。
  最终 EnsureStarted 的端到端 caller wait 另有观察预算，不能把任一个
  预算到期变成已交接服务的回滚权限。

验收覆盖默认 layout 的真实 registry 打开、迟到登记、不匹配身份/代际、
  重复 open/bind、open 失败后重试和期限冻结、应用在途时关闭拒绝，以及
  control/observer/journal/registry 的故障保留与依赖顺序。随后将真实
  detached Coding 用例换用此公共 owner，删除辅助程序里的手工装配；
  私有模型控制仍仅属于测试，不进入公共模块。

三视角设计复审已通过。首次资源准入前置已实施：四层正常构造器增加
  `defer_open=True` 与显式 `open(deadline=...)`，容器在首次 IO 前可保留；
  旧 eager 用法不变。每个容器只准入一次，失败需先关闭再由外层建立新
  容器；未成功准入不接受查询/修改，关闭后禁止复活。DB 与 journal 在
  完整收尾后也复查原 deadline，不把迟到结果发布为准入成功。

代码三视角复审修复首次锁、校验失败文件、读取、临时写入及 DB guard
  的 native close 不确定性遗漏；全部记在文件 owner，后续 close 不盲目
  重关原 fd 也不抹掉债务。SQLite connection 对象的已知未完成 close 则
  保留对象按其接口重试。对外新操作在 closing/uncertain debt 后拒绝，
  内部 pending unlink/fsync 清理走窄内部通道，仍能重试。OS fd close
  结果未知不能靠本进程重复 close 伪造确定性，留待整体异常退役合同。

新准入负测和 storage/lifecycle/child/实际 detached Coding 合跑 114 passed，
  精确 Hosting/AppHost/G9/G10/C50 架构回归 44 passed；9 模块 mypy、Ruff、
  文档 6 项、依赖图新鲜度与 diff whitespace 检查通过。以上是分次聚焦
  验证，不宣称完整 change-aware 最终交付门禁。中途一项新注入误伤了锁的前置校验，已限定为目标
  record；旧取消用例的“不再有临时文件即无债务”断言已更新为保留原始
  取消、临时文件删除且 unknown fd debt 不消失。复审结论仅覆盖此前置
  前置切片；bootstrap 的后续进展见下节，生产 process entry 和公共协调器
  仍未实现。

### 20.1 Bootstrap 接线证据

`ManagedChildBootstrapV1` 已实现本节装配合同；纯值路径推导后才接管
  已连接的 AF_UNIX stream socket，立即撤销再次继承，不在构造中打开
  数据库。同步 open/close 明确拒绝应用事件循环内调用，bind 仅发布
  现有 child owner。前置容器失败重试保留首个 absolute deadline，成功
  依赖不替换；首次准入观察到实例、attempt、已登记 native 任一不匹配
  均拒绝完成 open。open 不是长期授权，bind 后仍由 child 的持久检查
  决定能否 prepare/commit/activate。
  native capture 工厂失败无返回 owner 时保留 unknown，不重复捕获或
  宣称全部资源已结算；未移交 socket 和 native observer 的未知关闭
  同样保留债务，不重复关闭可能已复用的 fd。

复审补强 Hosting channel：只有取得 mutex、实际开始 socket close 后
  才锁定一次关闭尝试；获取 mutex 失败仍可重试，原生关闭结果未知则
  不能由第二次空 close 清掉债务。负测使用真实 socket 底层关闭后注入
  异常，并检查新分配的 fd 仍可用。构造测试先把被接管 endpoint 设置
  为 inheritable，再断言该端本身变为 non-inheritable；不是检查默认
  已不可继承的另一端。未连接/datagram/TCP 与错误 UID 拒绝后仍由原
  调用者持有 socket。

实际 Coding 子端已改用 bootstrap 及规范 application/connection layout，
  删除测试辅助程序的手工 registry/journal/native/control 装配和旧 S
  barrier。B 只报告 bootstrap 打开，不表示 Product 已准备或有接客权限。
  测试故意延迟登记，并跨进程持有 registry 锁直到启动器返回精确的
  `registration_busy` 测试回执才释放；等待受同一 gate deadline 限制，
  不靠固定 sleep 猜测竞争分支已经执行。确认同一原生创建
  的身份登记在固定期限内可完成；应用任务和最终回复仍不重放。
  子端 child.close、线程中的 bootstrap.close 全部完成后才返回测试
  清理回执，再由外部 exact pidfd 观察退出。

首轮迟到登记曾发生一次间歇失败；补 starter stderr 后，通过受控锁竞争
  复现同类提前退出并捕获 register_native 的 `managed_storage_busy`。
  测试 starter 改为同一冻结期限内重查 exact instance/attempt/native 后
  登记，不重 spawn；测试自身的观察也仅对 busy 做有界重查。未把先前
  单独三次重跑通过当成故障已经解决。确定性竞争回执补齐后聚焦回归
  57 passed；最终全部 managed 子系统、通道及实际 Coding 消费方合跑
  248 passed；精确架构 44 passed。11 模块 mypy、Ruff、文档 6 项及
  依赖图新鲜度通过，三视角复审通过。没有将这些分次聚焦结果宣称为
  完整 change-aware 交付门禁。这不是生产 EnsureStarted 的实现
  或完整 installed/SSH 验收；Session writer/default catalog、异常恢复、
  配额、全局名称操作协调、CLI 与完整 Harnesstui 均仍在完整 goal 范围。

## 21. 标准子端调用与 Coding 装配

`ManagedChildInvocationV1` 是 AppHost 纯值启动寻址消息，wire version 为
  `loushang.managed-child/v1`。closed flat JSON 只含 version、platformHome、
  userId、machineId、productId、workspace、profile、instanceId、attemptId、
  runtimeRoot；namespace/service key 由相同值派生，不接收冗余可分叉的 key。
  直接构造和 decode 共用既有 namespace/service/instance 与 layout 校验。
  校验成功不授权启动、commit 或连接，原有 self-native 与 durable birth
  检查不减少。

输入在 JSON 解析前按 UTF-8 限制为 64 KiB（含边界）；先限制字符数以免
  为无界文本分配编码副本。拒绝非法 Unicode、深度解析失败、重复/未知/
  缺少字段、未知版本、非标常量、bool 伪装整数、非规范值与路径。
  所有拒绝仅返回 bounded contract error，不回显输入；repr 不包含路径。
  输出使用规范排序与原生 Unicode，三个最长合法四字节字符路径也能
  round-trip。消息不含 fd、密钥、environment、模型或模块 factory。
  startup socket 作为独立继承参数，由既有 bootstrap 验证后接管；消息
  解析不打开数据库、不接管 fd、不构造 Product。

Coding 的 `create_coding_managed_launch` 只接受 product=coding；workspace、
  application root、connection root 从同一 invocation/layout 取得，调用者
  不能另传一份。application ID、endpoint、discovery 与显式 Session 两根
  沿用 G16 校验；Session 根额外与 managed durable/runtime 控制及临时根
  隔离。没有默认 Session 目录回退，也不借此激活默认共享库。可信调用者
  先保留 bootstrap，准入后才构造实际 Coding command，bind 失败仍由该
  调用者持有并结算 Product；模型测试注入仅留在可信库调用，不进入 wire。

真实 detached 辅助程序的 starter 负责编码，独立子端负责解码，替代旧
  instance/attempt 位置参数约定；继续测试正常/骤退启动器、迟到登记锁
  竞争、断连后唯一回复、显式 stop 与 exact 退出证据，不新增安装命令。

### 21.1 生产 runner 的评审前置

三视角设计评审允许上述消息与装配接线先实施，但生产 runner 激活前
  必须解决退出政策；禁止 `os._exit` 并不足够。`child.run` 可因失败返回，
  其 retained stage/native future 仍可能在清理，直接离开 `asyncio.run`
  同样会取消它们。进程顶层应保留同一事件循环与原 owner，普通 run waiter
  取消只脱离等待，不转换为服务 stop；显式 stop/服务内部故障才由既有
  child owner fence/close。正在运行的清理不替换，已结束且可重试的失败
  才按明确新预算委托同一个 child.close；不重复 prepare/commit/worker。

child pending 时不能关闭 bootstrap 或宣称成功退出。永久 native-close
  unknown 不靠第二次 close 消除，应保留 unclean 与 owner、不接客；允许
  异常退役退出的合同仍需 recovery 准入，不在本节默默采用“非零即安全”。
  顶层业务失败结果与资源完整结算是独立事实；子端不写 process/scope
  exited。本节未将受控测试 watchdog 作为生产退出策略。完整 goal 中的
  生产 runner、协调器、writer/default catalog、managed RPC、CLI、TUI 与
  installed/SSH/性能验证仍须完成，不能用本切片验收替代。

本节设计与代码三视角复审通过。标准消息、初版显式装配及四种真实
  detached 场景合跑 50 passed；扩展目录隔离与精确架构合跑 96 passed、
  1 failed，唯一失败为 inventory 文档已列 Coding 新模块而精确源码表
  漏项。补齐精确条目后该项单独重跑 1 passed，未重复其余通过项。
  两个生产模块 mypy、所有本节文件 Ruff、文档 6 项、依赖图新鲜度和
  diff whitespace 检查通过。最终 change-aware 全分支门禁仍待完整交付；
  以上不是完整安装、SSH 或首次使用性能的证明。

## 22. 子端结算等待接口

`ManagedChildBootstrapV1.run() -> int` 在成功 bind 后发布唯一 retained
  driver；实现细节放在可选 `managed/_lifetime.py`，不新增 facade/CLI
  激活。未 bind/已开始关闭而未建立 driver 的调用拒绝；并发调用加入
  同一任务，完成后再次加入仍返回同一结果，跨事件循环调用明确拒绝。
  首次任务发布沿用 child 的 publication gate，factory 失败时没有应用
  副作用，保留 bootstrap 后按退避重试调度。

driver 仅调用既有 child.run，并在其返回后委托 child.close 结算未完成
  部分，不复制准备、commit、激活、stop、worker 或阶段任务。重试初始
  等待 1 秒，每次倍增至 30 秒封顶；child.close 获得 30 秒协作重试预算，
  由 child 判断哪些已失败的阶段可以重试。这个预算不能强行中断 native
  IO，也不覆盖仍在运行任务的原期限。public waiter 取消只退出等待，
  不调用 stop、不记作服务错误；服务或清理出现的错误则保持为结果 1，
  即使后续结算成功也不会变成 0。

只有 child.cleanup_pending=False 才在线程中调用 bootstrap.close。
  offload task 保留在 driver，当前任务未结束不提交第二份；同步 callable
  完成后的正常关闭异常返回明确失败结果，再按同一 owner 合同重试。
  offload task 发布失败发生在 publication gate 前，可安全重试调度；
  offload 任务本身异常/取消则不能证明同步 callable 已结束，保留原任务
  与 unknown，不重发关闭。unknown 同时计入 bootstrap.cleanup_pending，
  即使原生资源后来为空，也不能靠该属性给出虚假的完整结算回执。

永久 native-close unknown 同样只进入有界频率维护等待，不再次关闭
  可能已复用的 fd，不接客、不返回退出状态。0 仅表示本驱动观察到的
  无错误完整结算；1 表示观察到错误但最终完整结算；有未结算资源或
  unknown 就不返回。两者都不证明 process/scope 已退出。进程外观察者
  仍负责这些事实，异常退役准入仍须后续实现。

这是 §21.1 的库级等待接口，不是已完成的进程 main/signal 策略。
  shield 不能阻止调用者关闭整个事件循环；最终 process composition
  必须保持同一 loop 存活直到 run 真正返回。真实 detached 测试的正常
  路径已改为等待此接口返回，再发 D 回执；不再由测试 finally 补 child
  与 bootstrap 清理。测试控制器故障仍有独立、明确的本地 stop 权限。

本节设计与代码三视角复审通过。9 项确定性 lifetime 回归覆盖调用矩阵、
  prepare/active/backoff/native-close 时取消 public waiter、清理迟到不替换、
  两处 publication failure、业务失败保持非零、退避封顶、真实原生关闭
  后 unknown 与复用 fd 保全，以及私有 offload task 取消后的回执债务。
  lifetime/bootstrap 合跑 33 passed，精确架构 44 passed；12 个 managed
  模块 mypy、Ruff、文档 6 项、依赖图新鲜度与 diff whitespace 通过。
  真实 detached Coding 在首次接线后 4 场景通过；回执债务语义补齐后
  重新执行其四种场景仍为 4 passed（52.20 秒）。无完整交付门禁或
  installed/signal/SSH 性能已完成的声明。

## 23. Linux 进程运行壳

`bootstrap.run_process()` 为已经 open、bind 的实例提供专用子进程的一次性同步进程
  运行壳，实现在可选 `_process.py`。创建 Runner 或改变 signal handlers
  之前，在同一 mutex 内拒绝非 Linux、非主线程、已有 running loop、未
  bind、closing、已有 lifetime 或已有 process owner；先发布 process
  owner，再进行原生初始化。不承担 open/bind 前置失败的资源所有权，
  这些仍由可信 composition 保留。它接管直到 OS 退出的信号策略，返回后
  可信 entry 仅做最终诊断和退出，不继续承载其他应用。可嵌入调用使用
  不改变信号的 async run()。没有默认路径发现或 CLI 激活。

分开两类结算：child＋控制资源由原 lifetime 驱动，Runner、进程等待任务
  与保护安装未知由 process 壳持有。lifetime 仅观察前者；对外
  cleanup_pending 同时包含二者，避免相互等待造成死锁，也不通过漏报
  进程债务来规避。通过受控 loop factory，loop 在返回 Runner 前已经
  登记到 process owner；初始化失败保留原 Runner/loop 与 unknown，
  不创建第二个 loop、不把 partial setup 当作已清理。

在 Runner 初始化之前逐项安装进程策略，不保存、不恢复旧 handlers。
  正常返回后保留该策略是刻意行为，不是未清理资源。HUP 忽略；INT/TERM handler 只记
  sticky stop 并唤醒 loop，不做阻塞清理。loop 最多保留一个 signal-close
  任务，调用既有 child.close；重复信号不升级、不刷新在途预算。
  此任务失败只记录失败，后续应用清理由既有 lifetime 重试。
  handler 在 loop 关闭窗口不再唤醒已关闭 loop。

首次 driver 前已收到停止信号，或 signal 安装部分失败时，先请求 child
  stop 再启动等待，不短暂接客。本节把“启动前终止”定义为返回 1（未达
  ready），已接客后的正常优雅停止返回 0。partial install failure 保留
  保护能力未知，先结算应用与 Runner，再进入维护，不返回退出回执；
  各项安装互相独立，不因其中一项失败跳过其余。

使用同一 retained loop 等待；不用 Runner.run 的缺省二次 SIGINT 升级
  行为。普通等待取消后重新加入同一 lifetime，不取消应用或关闭 loop。
  仅在 lifetime 返回且 signal-close 已结束之后，才关闭 Runner。
  等待 signal-close 的外层任务取消时，重新加入原在途任务，
  不把取消吞成可关闭 Runner 的结果。Runner.close 可能部分完成，失败
  不盲重试；初始化未知同样保持保护。进程策略持续到 OS 退出，没有
  短暂恢复默认终止行为的窗口，也不依赖只能屏蔽调用线程的
  pthread_sigmask。如果操作系统
  拒绝保护 setter 本身，不能承诺驻留保证，但仍不返回干净结果。
  应用已结算而壳未知时进入同步低频维护等待，不
  复活 loop、不返回成功；异常退役策略仍未获准。原生进程/scope 退出
  仍须由外部观察者确认，不由本返回值推导。

真实 Coding 辅助程序使用此同步入口运行真正的主线程事件循环，模型
  注入仍是可信库调用；测试控制独立在线程中，显式 join 后才发送 D。
  正常路径不由 helper finally 补 Product 清理；控制器故障用明确的
  自进程 TERM 请求停止，不新增生产测试 hook。测试用 exact pidfd 注入
  HUP、INT/TERM，不使用可能复用的数值 PID 对远端子进程发信号。
  当前 uv Python 未暴露 pidfd_send_signal，测试使用 libc 同一 API，
  没有将这一环境适配加入生产终止权限。

专用进程策略的设计经三视角同意，替代“暂借再恢复 handlers”的草案。
  确定性测试在挂起 close 内直接触发重复 handlers，验证同一任务、
  原预算与一次清理，不依赖标准信号是否合并；独立真实子进程保留
  未屏蔽信号的并存线程，在正常返回、初始化/关闭/安装故障后的状态
  下逐次注入 HUP、TERM、INT。测试退出码 7/9 仅用于结束测试控制器，
  不是生产结算或异常退役证明。

本节设计与实现三视角复审通过，关闭外层取消误吞、重复信号证据不足、
  多线程恢复默认 handlers 窗口三项问题。最终 process 确定性 12 项、
  并存线程真实信号 4 项、实际 Coding detached 6 项合跑 22 passed
  （60.15 秒）；13 个 managed 模块 mypy、相关 Ruff、文档 6 项与
  diff whitespace 通过。精确架构 44 项及依赖图新鲜度此前已通过，
  本次信号策略调整未增加模块依赖，未重复运行该批架构测试。
  随后 admission/bootstrap/child/files/invocation/lifetime/handoff 与
  Coding launch 相关回归合跑 183 passed（11.83 秒）。这些分组记录
  不替代完整 change-aware、安装或性能验收。

本节是可复用进程运行壳及真实信号组合证据，不是完整 installed CLI
  或 SSH 验收。内部 Coding 参数入口、默认目录/catalog/writer、公共
  EnsureStarted、管理协议、完整 TUI 与最终安装/性能门禁仍需完成。

## 24. Session writer 准入与接线顺序

现有源码复核：lifecycle.create/restore 在 Product runtime bind 后才创建/
  加载 UnitOfWork；_dispose_owned 在 Product dispose 成功后改变 owner
  状态。Graph construction/rollback 只转移该 lifecycle session，不需要
  重建锁。factory 的 import_bundle、fork、_create 在 lifecycle.create
  之前发布附件，Product.delete_session 则在 JSONL 删除之后清理附件。
  因而不能只在 create/restore 或 Hosted adapter 中加锁就启用共享默认库。

底层候选为 Harness transcript 可选 `writer_lease.py`，不导入 AppHost、
  Coding 或 Hosting；Linux first，其他平台显式 unsupported（现有非受管
  持久入口此时不接线，不改变其兼容性）。逻辑授权绑定规范化 Session root +
  Product ID + conversation ID，私有 `.transcript-writers` 下使用带版本的
  SHA-256 锁名；不使用 scope、Mux 名、文件 basename 或 PID 作为身份。
  物理锁仅按 conversation ID 散列：现有 JSONL、tombstone、附件均未按
  Product 分根，所以同根同会话即使 Product 不同也必须竞争。Product
  仍是权限校验的一部分，不能由竞争成功替代 header/runtime 校验。
  另一个物理冲突域是附件：resolve_session_blob_data_root 取 Session root
  的 parent，同父的兄弟 Session roots 可能共享 session-assets authority。
  本底层 lease 仅提供单根 transcript 排他，不宣称跨根附件互斥；完整
  接线须增加以实际附件 authority 为键的有序联合占用，或在明确受管
  profile 准入中拒绝未协调布局，不可静默改变旧入口合法布局。加入
  兄弟根同 ID 并发 import/fork/delete 的负测，未覆盖前不启默认共享库。

lease 对象先构造、保留，再 acquire；构造只做纯参数检查，acquire 才解析
  根并打开资源。不创建 Session root，不修改 transcript、header 或附件。
  根可为用户所有且不可被组/其他用户写入的 0755 目录，不擅自 chmod；
  私有 owner 目录严格 0700、普通单链接 lock 严格 0600。保留 root/owner
  dirfd，锁叶使用 no-follow/nonblocking/CLOEXEC；核对 UID、类型、模式、
  inode 及路径绑定。稳定锁文件不删除、不换名、不按 PID 清理。

Linux flock 为非阻塞独占，busy 不排队，最后一个继承/复制的原生 fd
  关闭才由 OS 释放锁，不能按父 PID 已退出推断；不占用
  journal 短期读写锁。acquire 原生效果失败时保留已取得的资源，只有明确
  未取得锁的 busy 允许 caller 关闭该 owner 后另开一次准入。check 在当前
  PID、已取得且未开始关闭、路径/原生身份仍匹配时成功；fork 后继承的
  Python 对象不能被当成新的 writer 权限。acquire/check/close 串行，
  一次准入、关闭永久 fence；上层先结算所有写任务，再关闭 lease。
  fork 子端普通方法拒绝；另提供仅子端主线程可调用的 close_inherited，
  不获取可能由消失线程持有的继承 mutex，只关闭本进程继承 fd 副本，
  绝不 LOCK_UN，不影响父进程继续持锁。CLOEXEC 只保证 exec 后不继承。
  该 disposal 仅支持已经成功 acquire 且尚未开始 close 的稳定 fork
  快照；acquire/close 在途时 fork 可能得到未登记 fd 或已复用的旧编号，
  子端保留 unknown 并拒绝盲关，不宣称清理完成。父端在途写任务也必须
  按上层 fork 准入约束处理，本 primitive 不把 fork 变成安全的 runtime 克隆。
  close 是 owner 的显式动作，
  只关闭保留句柄、不发送信号、不解锁后继续持有旧 fd；原生 close 抛错
  后保留 unknown，不盲重试可能已复用的 fd。持久改写只能使用同一已准入
  owner 的受限投影，不能把“知道锁路径”当作授权。

后续完整接线必须一起覆盖：恢复加锁后重读并校验 header；创建/导入/
  fork 在任何目标附件发布前持有目标 owner；runtime/Graph 全寿命连续
  持有；失败/取消结算后最后释放；delete、migration、低层 Store 改写与
  附件维护参与相同 writer 权限。只读快照不持独占锁，低层 repair load
  不能伪装为只读绕过准入。底层 lease 测试不替代这批全入口验收。

验收先覆盖同进程及两个真实进程竞争、不同身份并发、释放/进程退出后
  重开、fork 子端无写权限且关闭副本不解父锁、父退出但子尚留 fd 仍 busy、
  无 Session 文件修改、读锁不受影响、别名同锁、软/硬链接与目录
  替换拒绝、原生关闭未知及 fd 复用不误关。后续 Embedded↔Hosted 与
  Graph/附件/默认 catalog 激活矩阵仍按 §6，不缩减目标。

本切片已经实施到可选 writer_lease 模块，设计与代码三视角复审通过。
  纠正 Product 逻辑身份与物理互斥域混用、fork 继承描述符释放语义、
  在途关闭快照可能误关复用 fd，以及 sole-holder crash 证据缺口。
  15 项确定性回归加 5 项真实进程场景合跑 20 passed（1.06 秒），
  Ruff/mypy 通过。实施前 lifecycle/factory/Product-session 基线
  11 passed（1.59 秒）；这些入口未修改、未重复执行基线。初版路径
  替换测试因 fixture 默认目录权限含组写而提前被拒绝，改为显式 0700
  后验证预期路径替换，不放宽生产权限校验。底层模块未导出到 facade，
  未接普通持久入口，不据此声明全入口 writer 或默认共享目录已启用。

## 25. writer 接线前的 Store I/O 结算

实际 FileConversationStore 的 create/load/scan/page 直接 await to_thread；
  append/batch/delete 使用 shield，但取消 waiter 仍可先于 native callable
  结束返回。此时 lifecycle 的异常清理可能结束 runtime，未来再释放 writer
  就会与在途写入竞争。不能把 shield 本身当作线程结算证明。

先修 Store 的共同 I/O 等待边界：每次原生操作发布唯一受保留的任务，
  publication gate 成功后才允许进入 to_thread。调用者取消不取消这个任务，
  重复取消仍加入同一任务，待其结束后才传播取消；原生操作本身失败优先
  保留其错误。create/load/append/batch/delete/scan/page 走同一边界，不
  更改同步 journal 锁、数据格式、幂等 operation ID 或线程池配置。
  独立的原生完成回执不因内部 offload Task 被取消而失效；此时继续等
  原 callable 的回执，不重发、不把 Task.cancelled 当作线程完成。
  原生提交已开始但永远没有回执（包含内部提交结果未知）时保持 pending，
  不释放后续 writer。取消/timeout 均不是原生执行期限，不以忙循环等待。
  这是公共等待者取消的结算合同，不承诺在 event loop 被外部销毁时还能
  提供退出证明；上层仍必须保留 loop 直到所有受管调用结束。

聚焦验收以真实线程 barrier 覆盖上述七个入口，取消后调用尚未结束、
  同一 callable 不重发，释放 barrier 后才得到取消结果；另覆盖业务错误
  与取消竞争、publication 失败无原生效果，以及实际 JSONL 创建/追加
  的末次写入发生在生命周期 disposer 之前。通过后再实施 writer 的
  全寿命与全写入口接线，不将本修复当作默认共享库已经启用。

设计与实现三视角复审通过。原七入口 barrier 负测均复现失败，修改
  共同等待边界后七项通过；增加取消/业务失败优先级、独立原生回执、
  publication 失败、contextvars 与真实 JSONL 创建排序后，与原 Store/
  lifecycle 47 项基线合跑 60 passed（18.10 秒）。补齐实际追加排序后，
  聚焦文件 14 passed（0.85 秒），未重复未改变的 47 项基线。实际创建
  和追加均证明 write_complete → native_return → disposer，并保留已
  提交磁盘内容。Ruff、该 Store mypy 与文档 6 项通过；不将局部证据
  外推为整个生命周期取消安全或 writer 已全入口接线。
  追加排序测试也经交互/验收视角确认；直接受影响的 transcript session/
  factory/Product/runtime profile、Coding Session manager 与 Hosted local
  ownership 合跑 87 passed（6.41 秒），依赖图新鲜度通过。change-aware
  计划已重新生成，未把这些聚焦测试称为完整 check-changed 或最终交付
  门禁。原目标下一步仍是持久 writer 生命周期与全入口接线。

## 26. 显式 writer lifecycle 构造 owner

不能把 lease 仅挂到成功返回的 Session，也不能让同一已取得 lease 被两次
  create/restore 同时使用。新增可选 `lifecycle.prepare_writer(...)`：可信
  caller 传入已取得且精确绑定 root/Product/conversation 的 lease，先
  构造并保留 preparation owner，再调用其 create/restore。准备阶段只
  验证纯绑定和单一 claim，不创建 Product 或操作文件；claim 后普通
  lease.close 拒绝，释放权限归 preparation，失败资源不会只藏在异常里。
  preparation 先完整构造，claim 为末端提交；lease.claimed_owner 保留可
  取回的同一 preparation，交付失败也不丢释放入口。此接缝仅支持
  persist=True、显式 session_file 直属已 claim 的规范根；key 一致仍
  不能证明任意 Store 的物理映射，可信 binder 必须保证该 key 的全部
  改写落在该根，不能通过反射 Store 私有字段冒充验证。
  原 create/restore 和默认 factory 此时保持不变，不提前激活默认目录。

preparation 持有唯一构造任务、取得的 runtime binding、结果 Session 和
  分阶段清理任务；并发或被取消的 public waiter 只加入原任务，不重建
  runtime。创建/恢复模式第一次选择后冻结。准备与关闭跨 loop 拒绝，
  records、leaf_id、defer_materialization 在 prepare 时冻结，create/
  restore 不再接收可漂移参数；context 与纯 binding_input/records 复制为
  私有稳定快照，不接受需转移资源句柄的 binding_input。模式改变拒绝。
  dispose 同步 fence 新构造，再等已在途构造结束，不取消原生 IO。
  恢复在取得 writer 后重读 header，要求与原 Product 验证过的 context
  相同；load 后再核对实际 header。runtime key 必须精确匹配文件根和
  conversation，不把 Product header 校验转交给 neutral owner。

构造失败仍保留 runtime binding 与 lease，显式 dispose 按原阶段收口；
  若 binder 在开始后抛错却未返回可收口 binding，不能推断无副作用，
  保留 unknown 和 writer，不声称已清理。这一前置失败所有权仍须在
  最终 factory 默认接线时与实际 binder 合同闭环。成功结果仍为原
  AgentTranscriptLifecycleSession，Graph 转移它时同时转移同一 writer
  owner，不重新争锁；构造 root 不能绕过 Graph 对其进行释放。
  Graph 已持有结果时，root dispose 不得先 fence 再发现无权限；Graph
  接管与 dispose 共用 Session 的 ownership/fence。等待构造的 waiter
  返回结果前重验 closing，避免 dispose 已开始仍交付迟到 Session。

Session dispose 先等待同一 runtime disposer，成功阶段不重跑，已失败
  阶段可按原 port 的清理合同重试；public 取消不替换在途任务。runtime
  清理成功后才关闭 writer；原生关闭 unknown 或内部清理任务取消仍保留
  债务。关闭开始后拒绝再交给 Graph 或再次取得 Session。文件检查/关闭
  复用 §25 的相同 settled I/O 机制，提取为 Journal 私有共同 helper，
  不复制另一套线程任务机制，不改变线程池或增加高层依赖。

验收覆盖真实持久创建/恢复竞争、同 lease 重复构造拒绝、错误 root/
  Product/ID、header 变化拒绝且不修改历史、Graph ownership 连续转移、
  runtime disposer 失败/迟到/取消时第二 writer 仍 busy、最后释放后可
  恢复，以及构造失败 owner 保留和显式结算。后续附件联合锁、低层写入
投影及 Embedded/Hosted 全入口激活仍按 §6/24，不以本显式接缝替代。

本显式接缝已实施并通过三视角代码复审。首次聚焦验证含新 lifecycle、
  writer 原语/真实进程、Store 原生结算和原 lifecycle，53 passed（3.36
  秒）。复审发现内部 close Task 在原生关闭后被取消、fd 已清空时，
  cleanup_pending 可能假阴性；现直接将取消/失败的清理任务计入债务，
  不等下一次 dispose 才暴露 unknown。补齐这一真实线程屏障、内部
  runtime Task 取消、原生关闭未知且 fd 复用不误关、实际 Store load
  后 header 二次核验，新增 lifecycle 文件 17 passed（0.88 秒）。
  三视角确认修复闭环；Ruff、4 个源文件 mypy、文档 6 项与依赖图
  新鲜度检查通过。Graph 证据仅为原 Session 内部 ownership 状态
  转移，不称实际 Graph 组装已集成；低层独立 Store 引用和共享附件
  尚不受本接缝保护，可信 binder disposer 必须结算其全部已接纳工作。
  默认工厂、全入口 writer 与 lmux 开箱即用验收仍未完成，不能据此
  执行最终发布或把完整 goal 标记完成。

## 27. 标准 runtime 投影前收养

标准 AgentTranscriptProfileRuntime 已取得 RuntimeProfileBinding 后，
  selected_store/profile/key/snapshot 投影仍可能失败。显式 writer
  preparation 必须在投影前取得该 binding 的清理入口，而不是仅在
  异常里附上句柄，或尝试一次清理失败后丢弃资源。

在现有 lifecycle 增加可选 owned binder port：除原 context/input 外，
  接收同步的单次 retain_disposer 回调。标准 runtime 提供对应入口，
  raw binding 返回后立即把其原 binder.dispose 闭包交给回调，再调用
  共享的同步投影函数。§26 preparation 保留该 disposer；构造失败时
  若已收养，仍按原 runtime→writer 次序清理，可重试失败阶段，不
  重建 raw binding。正常返回仍为原 AgentTranscriptRuntimeBinding。
  回调只接纳一次且只能在当前 binder 调用内使用，不能晚到替换 owner。
  binder finally 使回调失效，覆盖成功、异常与取消。标准入口只构造
  一个 disposer，同步收养和最终返回共用该对象；漏掉收养或两者不
  一致时拒绝交付，保留两个清理引用及 unknown，不盲选其一释放 writer。
  旧 bind_lifecycle 和默认 create/restore 的返回合同不改变。

这个接缝解决“已返回 raw binding、投影尚未成功”的实际窗口；通用
  factory 未返回时的 partial acquisition 仍不能从异常推断无资源。
  后续应复用原 RuntimeProfileBinding 的逐项清理账本，不能从 Harness
  引入 AppHost 私有资源栈。当前标准四种工厂只构造 Store 配置/布局、
  profile、compaction 等值，不启动外部任务或取得长期原生资源；此
  源码事实不推广为任意替换工厂的 pure=True 承诺。

验收使用真实标准 runtime，注入投影错误和首次 disposer 失败，确认
  同一 raw binding 始终可恢复、第二 writer 在完成清理前仍 busy、
  重试完成后才释放 writer；覆盖取消 waiter 不重建 binding、非法或
  迟到回调不能覆盖现有清理 owner。默认工厂全入口接线仍是后续工作。

已完成本 owned 接缝实施和三视角代码复审。改前标准 runtime/factory
  基线 8 passed（1.18 秒）；新增接口负测先因 owned 方法不存在失败，
  实施后与 §26 和该基线合跑 26 passed（3.35 秒）。扩展缺失/冲突
  authority、重复/迟到回调和 public 取消后同 raw binding 重 join 后，
  writer runtime/lifecycle 合跑 23 passed（0.99 秒）。投影失败保留
  原错误且未创建 JSONL，首次 disposer 失败后的重试确实使用同一个
  RuntimeProfileBinding，未另造清理账本。Ruff、3 个源文件 mypy 与
  依赖图检查通过。旧 bind_lifecycle 路径没有因此得到 owned 保证，
  通用 partial factory 和默认 Session 工厂激活仍待完成。

## 28. 先保留现有 binding，再逐项构造

RuntimeProfileBinder 的可选 prepare_binding 返回尚未发布 generation
  的空 RuntimeProfileBinding；caller 先保留它，再 bind_prepared。
  bind_prepared 只执行一次，每个 factory 返回后立即记入该 binding
  的原 _bound 账本，不等整个 slot 完成。全部成功后才发布可读值。
  失败保留已返回 entries，显式 dispose 仍使用原逆序清理、失败项
  重试与 retained disposal Task，不创建第二套清理状态机。

新接缝的 prepared/building/failed 不能读取或 rebind；building 时
  dispose 拒绝，构造 owner 必须先加入原构造任务。准备后即关闭则
  不执行任何 factory；同一 binding 不接受第二次构造或其他 binder
  填充。此接缝只用 async dispose，避免混用同步/异步清理账本。
  原 bind/bind_sync/rebind 的发布和兼容行为不改。

标准 transcript owned binder 改为先 prepare_binding，立即通过 §27
  交出同一 disposer，再 bind_prepared 和投影。这样工厂后续失败也
  不丢先前 entries。Factory 在返回前仍拥有自身尚未交付的资源：
  异常/取消前必须结算它们，不得让未受管线程或任务逃逸；这不是把
  任意异常当作全局无资源证明。标准内置实现按实际源码没有长期原生
  资源取得，泛型接缝的测试 factory 显式遵守该 port 责任，不能用
  本机制为违反该合同的外部 factory 声明安全。已有独立 writer driver
  被私自取消仍保持 unknown，不据 canceled Task 推断底层工作完成。

验收：同 slot 第二个 factory 失败仍能逆序清理第一个；清理首次
  失败后的重试不重复已成功项；未完成 generation 不可读、构造不能
  重入/跨 binder、构造中不能清理。实际标准 transcript 在后续工厂
  失败后仍保留 writer，完成原 binding 清理后才释放。标准成功路径
  和旧 RuntimeProfileBinder 行为跑回归，不改 Product 恢复校验。

设计复审发现原 async disposer 先 fence closed 再创建任务，发布失败
  未保存 pending，下一次 dispose 可误报成功。已将待清理 entries
  先登记原 pending 账本，再 fence 和通过 publication gate 发布任务；
  失败不运行 disposer，不丢重试依据。未另建清理状态机。

本接缝及上述修复已通过三视角代码复审。改前 runtime profile 基线
  32 passed（0.33 秒）；新 prepared/profile/owned transcript 回归
  合跑 49 passed（2.60 秒）。实际标准 runtime 的后续 factory 失败、
  首次清理失败仅重试失败项，以及内部清理任务发布失败保持 writer
  busy 两项补测后，writer runtime/lifecycle 合跑 25 passed（2.52
  秒）。Ruff、2 个源文件 mypy、依赖图检查通过。初次定向负测因
  多值槽位 fixture 缺 variation semantic 而提前失败，修正 fixture
  后命中发布失败与重试断言，不把该初次失败称为原 bug 红测证据。
  默认持久 Session 工厂和底层写入口尚未接入，不外推为完整 writer
  保护或 lmux 开箱即用交付已完成。

## 29. 单 Session 写权限与跨 Session 只读查询

FileConversationStore 的普通 load 可通过 transcript loader 重建缓存，
  scan_page 又会读取多个 key；不能让整个 namespace 借用一个 Session
  的 writer。先将扫描的 snapshot loader 与普通 load 分开，保留同一
  Store 实现。Transcript 扫描和路径解析的 header 发现采用已有稳定
  no-follow 文件读取，不创建锁文件；分页使用同样只读的 snapshot。
  其允许复用已验证索引，miss/tail 只严格重放，不修复尾部或回写缓存。
  这是稳定字节快照，不承诺整个 namespace 的原子快照；并发变化仍
  按原 Store discovery/load diagnostic 合同报告。

Catalog 的独立 Store 同样采用 read_only 投影，覆盖 scan、page 及
  Catalog 后续逐 key 的 load，并在路径回调前拒绝所有 mutation。
  现有 index_writable 仍只决定 Catalog 自身聚合索引，不混同 Session
  内容/逐文件缓存写权限。普通单 key Session load 保留当前索引加速，
  后续在 offload 前通过中性 admission scope 借用精确 Session writer。
  dispose 顺序仍是 fence 新操作、join 构造、drain 已登记 IO、runtime
  清理、writer 关闭，不能只守 create/append 而漏缓存重建或删除。

只读验收要求 scan/page/load 不创建、改写或删除 Session JSONL、逐文件
  cache 或 lock，缺失/损坏索引均不自愈，有效索引仍复用；另一 Session
  处于写入生命周期时，跨 key 查询不取得它的 writer。readonly Store
  mutation 无路径回调；严格格式校验、诊断及原非只读 Store 合同保留。
  这一读投影是实际 writer 全入口接线的前置，不替代后续写入 admission。

本读投影已落到实际 Catalog/Directory 与 FileStore，并通过三视角
  代码复审。缓存命中、tail 与 miss 都注入稳定 no-follow source/cache
  reader 和不创建锁的策略，非单靠 write_index=False；只读 deferred
  Model Input 保留本次已验证 raw bytes，后续仍懒解码但不再重开路径。
  此处会将原始字节保留到该只读 snapshot 的 deferred source 释放，
  不改变普通可写 Session 的延迟读取行为。路径摘要/冲突发现也接入
  有预算的只读读取，Catalog 自身聚合索引仍由原 index_writable 管理。

复审补齐三个遗漏：延迟 payload 重开路径、公开路径发现仍创建锁、
  leaf-open 失败后 parent-close 再失败覆盖主异常。稳定 prefix/full
  读取也改为独立尝试两个 fd 关闭、保留读取主异常且不重试不确定 fd；
  leaf open 加 O_NONBLOCK，打开后身份复核拒绝 lstat 后的 FIFO 替换。

改前 Store/index 基线 50 passed（17.72 秒）。只读 Catalog 负测真实
  复现生成两份 lock 与两份 cache；修复后初 10 项与该基线合跑 60
  passed（23.42 秒）。直接受影响的 catalog/discovery/file-store 与
  Coding 消费者 116 passed（35.72 秒）。复审修复后 readonly/index/
  catalog/directory 合跑 75 passed（2.60 秒）；再补 FIFO 两项，聚焦
  readonly 文件 23 passed（2.52 秒）。验证包括有效缓存不严格重放、
  新完整尾部可见且不回写、残缺尾部诊断及字节不变、活跃 writer 下
  跨 key 读取、实际 Directory 查询全树不变、deferred load 后删除/
  symlink 替换仍无后续 IO，以及关闭双故障保留原异常。Ruff、受影响
  源文件 mypy 和依赖图检查通过。单 Session 写入 admission、附件
  联合权限及默认工厂激活仍未完成，不能据读投影声明 full goal 交付。

## 30. 实际 FileStore admission 与在途 IO 结算

Conversation 定义中性的 async operation_scope(target) port，target 为
  单 key 或只读 namespace。FileStore 七个 public IO 入口在 offload 前
  进入 scope，settled_io 真正返回或结算取消后才退出；read_only mutation
  仍在 scope/dispatch 前拒绝。Store 不导入 transcript writer、Product
  或 AppHost。namespace scan/page 沿 §29 的只读路径，不借单 Session
  writer 改写其他 key。

§26 preparation 同一 owner 负责 scope：只接受原 loop、精确根/Session
  key，namespace 只接受该根；先登记活动借用，再异步重验所持 writer，
  借用退出前不得释放 writer。关闭先 fence 新借用，join 原构造任务，
  drain 已登记 IO，再原 runtime disposer、writer close。被取消的关闭
  waiter 可重 join，不能使在途操作减计数或替换其 native task；关闭后
  晚到构造 IO 拒绝，不设置内部调用绕过 fence 的标志。runtime disposer
  不应在这个终止阶段新发 transcript 写入，最终内容保存须先完成。

owned binder 的第三个参数扩成一个可调用的中性绑定 owner 投影，
  保留原 retain_disposer 调用形状，同时明确携带 operation_scope；它
  不另有生命周期状态。标准 runtime 将该 scope 放在私有构造 context
  中交给实际 FileStore factory，Product context/input 仍是纯配置，不
  把 scope 混入 deepcopy。最终 transcript.store 与 Product binding
  中的 conversation.store 是同一受管 FileStore，不在外层包装副本，
  也不靠读取 Store 私有字段做权限认证。

验收使用真实标准 runtime 和 JSONL：普通主写、batch/delete、带缓存
  副作用的 load，以及 namespace scan/page 均受 admission/寿命约束。
  native barrier 下同时取消操作 waiter 与关闭 waiter，第二 writer
  仍 busy，IO 完成才运行 runtime disposer；关闭后的原 Store 引用和
  Product binding 暴露的同一引用均不能再操作，错误 key/namespace 在
  path/native IO 前拒绝。Graph 持有时 root dispose 不 fence 其操作。
  新接缝不等于独立未接线 Store、直接导出/维修/附件入口已被保护；
  完整默认激活仍需剩余入口与联合附件 authority 一起完成。

本节生命周期接线已实现。受管 writable load 的 deferred payload 也
  保留本次已验证 raw bytes：可写索引仍可更新，但 scope 退出及 owner
  释放后不再重开路径；普通未接线 Store 的延迟读取策略未变。
  writer/runtime/native-settlement 改前基线 39 passed（1.22 秒）；
  初次合跑 54 passed（3.92 秒），扩展后的独立 IO 文件 16 passed
  （1.41 秒）。覆盖七入口真实 native IO、原 Product binding 同一
  Store、创建/关闭双方 waiter 取消后真实首次 JSONL materialization、
  late binder 返回后拒绝新 materialization、Graph root 不提前 fence、
  重验成功/失败结算、runtime disposer 拒绝新 IO，以及 deferred source
  删除/symlink 替换后无重开。Ruff 和七个源文件 mypy 通过。

本节当时的三视角代码复审尚未整体通过（后续修复见 §31.2）：架构边界通过；测试视角指出原 create
  barrier 假调用不足，现已改为真实首次创建并补 owner.create 专项；
  生命周期视角另发现下面的物理 root 绑定 P2。这里的 scope 只已证明
  精确逻辑 key 与生命周期，不等于原生文件打开已绑定同一物理目录。

## 31. 实际 IO 与 retained root 的物理绑定（受管 Store P2 已修复）

writer.check 与 FileStore native IO 分属两次 offload。检查结束后若
  原 Session root 被 rename 并在原位置新建目录，新 writer 可成功
  锁住新 root；旧 Store 的 pathname 操作也会落入新 root，绕过原先
  的物理互斥。再多一次脱离实际打开的 pathname check 不能消除竞态。

修复前新增 test_writer_root_binding.py 使用独立临时 Session 树、真实标准
  runtime 和第二个 writer，确定性暂停在 check 已结束/native IO 未
  开始处，替换 root 后继续。append/delete 两项真实负测均失败
  （1.11 秒）：新 root 的 JSONL 分别被修改/删除。测试未标 xfail，
  保留为修复验收；最初夹具目录权限不合要求的失败不计作竞态证据。

该 P2 是默认激活和发布前的必修项，而非额外扩大功能。修复须让实际
  JSONL、journal lock、Store head/create metadata、tombstone、Model
  Input index 及其临时文件/replace/unlink/fsync 使用同一 retained root
  authority，所有打开/写副作用均不得重新解析到替换 root。不能只保护
  JSONL 或用 /proc 路径字符串重定向冒充完整 fd-relative 合同。
  既有逻辑 key/API 和 Session 默认策略保持不变，底层机制与 Product
  和 AppHost 解耦；§30 IO drain 保证这份物理 authority 的借用寿命。
  修复后需重新执行两项负测、七入口 IO 回归及受影响的 journal/index
  检查，再完成三视角复审。当前分支不得据前述 54/16 项局部通过而
  声明已可合并发布。

后续实现边界已按生命周期复审细化：从 writer 已持 root fd 派生中性
  descriptor-relative IO port，保留原 dev/ino，Store 仅借用、不关闭；
  scope drain 后才由原 owner 释放。相对 child name 必须校验，固定
  子目录逐级 no-follow 打开；Path 仅作逻辑映射和诊断，不再作受管
  分支实际 open/replace/unlink/mkdir/fsync 的授权。已经接纳的操作
  可在原 pinned root 完成，后续 admission 再拒绝失效 pathname。
  不使用 chdir、/proc 字符串或第二套 Store，也不改变未受管旧分支。

优先复用 journal_file_lock_at/read_journal_file_at 的 dirfd 打开规则，
  补齐普通 Journal append/load/write/repair 与 FileStore unlocked
  helpers 的显式传递。sidecar 原子写须在同一 retained parent 中以
  随机名 O_EXCL/O_NOFOLLOW 创建、写入/fsync、同目录 fd replace、
  parent fsync；临时清理也使用同一 authority。tombstone 的首次与
  幂等重试删除、index 命中/重建/尾部更新/删除、layout 发现与目录创建
  都在覆盖清单内。JSONL、锁、head、tombstone、index、replace 和
  临时清理前各自插入 root 替换 barrier，验证新 root 全树不变，而非
  仅检查 JSONL 内容。这是实现前边界说明，尚非已通过的新设计验收。

### 31.1 Rooted IO 与 Journal 首切片

本首切片经三视角设计评审后实现。journal/_rooted_io.py 提供 Linux
  RootedFileIO：借用现有 root fd，canonical Path 仅作词法映射，不
  close 借入 root、不 resolve/chdir，也不调用 pathname IO。一次
  bind 产生仅在该事务内有效的 RootedFile；锁、数据、rewrite 和
  partial-tail repair 共用同一个 pinned parent，不能各自再遍历
  子目录。Journal 增加显式可选 file_io，拒绝同时使用仅支持 Path
  的旧 lock_factory，默认旧入口不激活此分支；rooted 类型只做静态
  导入，避免普通启动多加载 native adapter。

原 operation ledger 记录自己打开的 fd、独占创建的临时名/原生身份、
  临时 unlink/replace 后待同步目录。close 先记 unknown 再调用，失败
  不重试数字 fd；每个独立 fd 均尝试关闭。临时清理失败保留 parent，
  unlink 成功后只重试 fsync，不能重删后来同名文件。该 ledger 的
  cleanup_pending/cleanup 供原生命周期 owner 在 native drain 后
  检查/结算，首切片时尚未接入 writer（后续见 §31.2），不能据单个原生异常推断已无清理债务。
  Port 没有后台任务、root 所有权或自动 admission；借用寿命仍必须
  由 §30 原 owner 管理。所有 bound-file 方法和 cleanup 均拒绝 fork
  子进程，不能利用继承引用绕过原 owner 的进程边界。

首轮已有 Journal 基线 19 passed（0.41 秒）；加入 rooted 首测合跑
  47 passed（0.56 秒）。代码复审修复临时删除缺 parent fsync、嵌套
  parent 替换时锁/数据分裂、新 bound reference 缺 fork 拒绝，以及
  测试树快照未覆盖 root 本身/mtime。补齐后 rooted+Journal 合跑
  56 passed（2.30 秒）；再加入真实 fork 负测，38 项 rooted 与直接
  FileStore/index/readonly/writer 消费者合跑 129 passed（3.50 秒）。
  另一次消费者命令路径拼错导致 no tests ran，不计验证证据。Ruff
  和两个源文件 mypy、文档轻检查及依赖图检查通过。三视角代码复审
  已确认本首切片 P2 闭环；这一结论不扩展到尚未接线的消费者。

验收覆盖真实 Journal load/append/batch/rewrite/repair；root 与加锁
  后 nested parent 替换；实际 open/write/replace/unlink/fsync/flock
  边界替换后新目录全树 bytes/mode/inode/mtime 不变；symlink/FIFO/
  hardlink 与越界拒绝；临时名冲突不取得清理权；写入/文件同步/
  replace/目录同步失败；unlink 后重试仅同步与 replace 成功后不能
  删除新同名临时文件；未知 close 保留主异常、独立回收且不重试；
  独立进程锁 busy→释放→acquired；真实 fork 拒绝继承引用而父继续
  工作。首切片时原 FileStore 根替换两项失败尚未修复：其 layout、unlocked
  helpers、head/tombstone/index 以及 writer 清理债务接线是下一步，
  本首切片通过不等于 §31 总 P2 已关闭或 lmux 已可发布。

### 31.2 实际 Store/Index/Layout 与 writer 清理接线

本次接线通过三视角代码复审，关闭 §31 所述受管 FileStore 的物理
  root 替换 P2。标准 owned binder 的实际 FileStore、layout 与索引
  都接入同一 RootedFileIO；JSONL、锁、head/create metadata 在同一
  bound Journal 事务内操作，unlocked helpers 显式传递 bound_file，
  不重新 bind/加锁。新的受管 Store 仅接受 root 的直接 JSONL child，
  与原 prepare_writer 对 session_file 的限制一致；不收紧旧未受管
  layout。Journal factory 若未返回同一 root IO 会拒绝，不默默回退。

路径映射不再 resolve 或 mkdir 替换根；stat/exists、预算内 namespace
  发现和 header prefix 都从保留 fd 读取。只读 scan/page 不写逐文件
  cache/lock。可写 keyed load 的有效索引、strict replay、tail 扩展
  和原子重建也共用同一 parent；deferred payload 仍保留已验证字节。
  cache 删除、tombstone 和各类临时清理不借助 Path 原生 IO。

delete 在整个操作内固定 tombstone parent。RootedFile.atomic_write
  成功返回前同步目录，确保新 tombstone 先持久化再删除正文；幂等
  分支也显式同步匹配的已有 tombstone parent。后一项修复复审提出
  的崩溃窗口：前进程可能停于 replace→fsync 之间，目录项可见不等于
  已持久化。同步失败以 unknown 结果保留正文及同步债务，不能继续
  unlink。已 unlink 的临时文件只重试目录同步，不删除同名 replacement。

标准 owned preparation 在最终 claim 前构造借用原 writer fd 的 port
  投影（不新增 root fd）；将它与 scope 一起传给原 runtime factory。
  原 owner 在 IO drain 后按 runtime→port cleanup→writer 收口，保留
  _io_cleanup_task，同一 waiter 取消后重 join；失败保留原 port/账本，
  不释放 writer。owned restore 的前置 header 检查也使用 fd 只读路径；
  此标准受管路径目前拒绝定制 pathname-only header_loader，不能用
  它绕开 root 授权。旧非 owned 工厂/定制路径未因此改变或自动激活。

新增预算目录扫描的 iterator 亦进入原 operation ledger：得到对象后
  立即保留，关闭前记 unknown，一次 close 失败不盲重试对象；其他
  fd 独立关闭，遍历主异常保留。未知 iterator 关闭债务可见于原 writer
  owner，重复 dispose 仍不能宣称释放。不是仅抛出异常后忘记资源。

修复初次原两项负测转绿，与 writer/rooted IO 合跑 56 passed
  （4.54 秒）。旧 FileStore/index/readonly/writer/Journal 消费者
  94 passed（2.35 秒）。三视角修复及增强负测后相关集合 167 passed
  （4.00 秒）；再补 owned restore 两项，root-binding 文件 21 passed
  （1.78 秒）。Ruff 和九个受影响源文件 mypy 通过。主要证据：

- 原两项不再忽略任意异常，严格校验成功回执、旧 root 记录/删除结果
  和新 root 全树 bytes/mode/inode/mtime。
- 七个实际 Store 入口在 native 前替换 root，禁用对应树的 Path
  原生 IO；返回值/diagnostics 及旧 root 内容准确，新 root 全树不变。
- 四种索引状态 missing/corrupt/valid/tail，验证重建次数、记录和新树
  不变；有效索引不重建，其他三种仅一次。
- 原生临时清理失败时实际 writer busy；修复后取消/rejoin 同一清理
  task，只清理原债务，不重放业务，最终才释放 writer。
- 首次/可见旧 tombstone × 同步成功/失败四组合证明先同步后删正文，
  同步失败正文保留；iterator-close unknown 多次 dispose 仍保锁。
- 标准 owned restore 正常恢复；在 header IO 前替换 root 时 header
  仍读原 fd，新 root 不变，随后的 Store admission 拒绝失效路径。

此 P2 关闭限定于已接线的标准受管 Store/Journal/Index/Layout 与
  preparation；不等于所有默认 Session factory、导入/迁移/维修/
  附件写入口都已有联合 writer authority，更不代表 lmux full goal
  已完成。默认激活、共享附件联合权限和完整交付门禁仍在剩余范围。

## 32. 图片发布的 Session 寿命与提交不确定性

调用链复核确认：ProductTranscriptSession 的 Agent/Application 图片
  发布原先早于 Store admission，Session 已关闭后仍可构造 BlobStore、
  读取 manifest 并发布图片。本轮复用原 writer preparation 的 scope，
  通过 LifecycleSession.operation_scope 从 BlobStore 构造前覆盖到
  正文提交或失败回滚结束。没有新建 owner；旧 unowned binding 为
  no-op，Graph 的真实 owner 仍决定关闭。内部 Store scope 不绕过
  closing：关停先于正文准入时可拒绝，在外层 scope 内回滚后才 drain。

三视角设计/代码复审同时关闭一项数据完整性 P2：正文已落盘但回执
  unknown，随后重试被关闭拒绝，原 UOW 会改抛 closed；Product 据此
  回滚图片可能破坏已持久化引用。append、batch、首次 materialize
  现在保留首次 unknown，直到恢复返回值完整校验通过。恢复抛错、
  取消或返回非法 revision/record ID/batch size/snapshot 都不把它
  降为未提交。未先收到 unknown 的非法提交回执同样表达 unknown，
  仍为 RuntimeError 子类。图片回滚遇到 unknown 或本地 transcript
  revision 已变化时保留字节并记录异常 note；后者覆盖提交已完成而
  observer 抛错的情况。revision 变化仅用于保守保留，不是删除授权。

普通 public cancel 沿用 UOW 已有 cancellation-atomic commit；没有
  再增加 Product task owner。确定未提交的等待取消/关停拒绝仍走原
  compare-and-rollback；其失败合同未改为自动强制清理。保留的图片
  不是已完成回收的临时文件，后续对账/显式维护仍需判断真实引用。

验证先跑已有基线 32 passed（1.85 秒）；新回归最初 5 failed，外层
  scope 后为 3 passed/2 failed，定位到 unknown 被 closing 覆盖。
  修复并扩充后，本文件 24 项与直接消费者合跑 98 passed（4.09 秒），
  四个源文件 mypy 与 Ruff 通过。一次新 fixture 使用默认 mkdir
  权限遭当前 umask 影响被安全准入拒绝，已改为隔离的 0700 Session
  子目录，不计为产品回归。最终三视角复审通过本切片，证据包括：

- Agent、Application 及转发入口关闭后，BlobStore 构造前即拒绝。
- 图片已发布、等待 commit 锁时关闭/重复取消；原 writer 保持 busy
  直至回滚完成，关闭 waiter 取消后可重新 join。
- 真实 native append 开始后取消，已接纳提交成功优先，持久图片可读。
- 真实写入后 unknown，关停阻止重试；正文与图片保留，异常仍 unknown。
- append/materialize 坏恢复回执六组合、batch 坏回执/拒绝四组合，
  验证原 unknown 对象、真实持久记录以及相关图片字节。
- observer 失败不删已提交图片；Graph 接管后 root dispose 不提前
  fence，重复 Application message 仅一条正文，真实 Graph dispose
  后才拒绝新图片入口。

### 32.1 下一步联合权限（设计约束，尚未接线）

本切片只证明附件操作的 fence/drain，不证明附件 IO 已 pinned，
  更不证明跨根互斥。SessionBlobStore 当前仍通过 pathname 访问；
  不能因此激活全部默认工厂。架构复审确定下一步两个物理锁域：
  transcript-root + 原 conversation ID，以及 data-root/session-assets
  + session_blob_authority_id(ID)。附件锁域不加入 Product 或 Session
  root，以覆盖兄弟 Session roots 的共享附件。

附件 lifetime 锁须独立于现有每操作 shared/exclusive 锁且位于不会
  被单 Session delete 删除的目录，避免自锁。原 preparation 保留
  两份 lease，固定顺序非阻塞准入，失败保留并结算已取得的资源；
  原 scope/drain/cleanup 完成后释放。实际 object/manifest/import/
  rollback/delete 还须接入借用 retained root 的 IO，不能只加锁再
  重复 §31 已修复的 pathname 替换窗口。导入/fork 在发布前取得联合
  权限，delete 持有到附件处理结束，工具输出/模型输入图片入口同样
  纳入后续接线；不从完整 lmux 目标中移除这些入口。

## 33. 共享附件 lifetime 锁与原 preparation 联合准入

本轮把 §32.1 的锁机制与原 owner 接线实现为显式可选路径，通过
  三视角设计及代码复审。没有更换 Session 默认目录或激活入口。

原 TranscriptWriterLease 的 Linux fd/锁/身份检查/one-shot close
  机制抽为 Journal 私有 DirectoryWriterLease。Transcript 薄层保留
  原参数名、错误类型/前缀、`.transcript-writers` 和完全相同的 hash
  输入字节；原生 flock 回归验证与旧锁互斥。Artifacts 的私有
  SessionBlobWriterLease 依赖同一中性机制，不反向依赖 Transcript。
  它锁定 data_root 下 `.session-blob-writers` 中的规范化 Session
  authority，不把 Product/owner 加入锁键；与现有短操作锁分离且
  不随单 Session 附件删除而消失。constructor 不做文件 IO，缺少
  data root 时准入失败，不隐式 mkdir 或修改已有权限。

`prepare_writer(..., manage_blobs=True)` 在原 preparation 纯构造
  阶段内部创建并独占保留第二 lease；不存在调用者共享的第二 owner。
  正文已持有后，原 build driver 在 binder 前通过 settled IO 执行
  blob acquire→借用 root port→claim。任一步失败均保留同一对象，
  第二次 create 加入原失败 driver，不重试获取或重建资源。外部取消
  不遗弃 native acquire；dispose join 原 driver 后再结算部分资源。

scope 通过同一次 settled IO 复核正文与附件两域。关停次序为
  drain→runtime→两个 root-port cleanup→blob lease→正文 lease。
  两个新增清理阶段各保留原 task，waiter 取消可重 join；成功阶段
  不重复，blob close unknown 不盲重试数字 fd，也不继续释放正文锁。
  原 claim/recovery/fork 语义保留在共用机制中。

验证：提取前 native writer/process 基线 20 passed（0.92 秒）。
  首次提取测试 53 passed/1 failed，失败是旧 fork helper 故障注入
  import 未同步到新 core，修正后该真实 fork 用例通过。机制、联合
  owner 和图片相关集合 83 passed（4.23 秒）；补 borrow/claim
  中途失败和 blob-port cleanup 重试后，与真实 Store/root IO/旧
  BlobStore 消费者合跑 58 passed（2.46 秒）。两集合存在重叠，不
  相加作为独立用例数。Ruff 与五个源文件 mypy 通过。

主要新增证据：实际 sibling Session roots 映射同一 data root，
  跨 Product、legacy/已规范化 ID、canonical 别名均互斥；不同 ID/
  data root 并存；独立进程 busy→close→held；持 lifetime 锁期间
  实际 BlobStore 构造/读写/rollback/delete 不自锁且保留锁 inode；
  目录/锁替换拒绝；第二锁 busy 或 borrow/claim 失败不调用 binder、
  不生成 JSONL；取消 acquire/close 后加入同一 driver；blob-port
  cleanup 失败保留两域，重试成功才释放；blob close 成功不重复；
  close receipt 丢失后的复用 fd 不被重关，正文 writer 保持 busy。

仍未完成：SessionBlobStore 的实际 manifest/object/rollback/delete
  尚未消费该 retained data-root port，`manage_blobs` 只提供联合
  lifetime 准入与结算，不能据此宣称 pathname 附件 IO 已安全。
  下一步须将 port 接到实际附件 IO，再接导入/fork/delete/工具输出/
  模型输入和默认 Session 工厂；完整 lmux 目标及最终交付门禁仍待
  完成。本轮不以仅有互斥锁替代这些要求。

## 34. 实际附件 IO 与原 owner 恢复账本

本轮推进 §33 的可选路径：SessionBlobStore 接受原 preparation 的
  retained data-root port，实际 Product 的两条图片写入路径在已有
  operation scope 中传递同一 port。未切换默认工厂，未改变 Session
  路径、manifest 格式或旧 pathname BlobStore 行为。

Artifacts 私有 BlobTransactionIO 负责 Session/manifest/object 语义；
  Journal 的 RootedDirectory/RootedFile 只提供 fd 相对操作及通用
  恢复账本。每次事务固定 assets、短锁目录、Session 和 objects，
  加锁后复核各层命名身份。整体 data root 改名后继续访问原树，
  已固定的内部子目录被替换则拒绝，不转向新树。

对象 O_EXCL 创建、写入与同步完成前，由原 operation 保留确切
  inode 收据。初始 manifest 独占发布，后续 manifest 原子替换。
  恢复先耐久还原旧 manifest，再删除本次未引用对象；恢复也失败
  时保留旧内容、原目录、对象收据与原短锁，不遗弃孤儿对象。
  批量对象及有界整树删除在第一次 unlink 前登记完整计划，成功
  unlink 后只重试父目录同步，不误删后来出现的同名对象。完成的
  manifest 恢复不因后续删除失败而重放。

恢复投影由每次回调独有 token 限制，只在原 cleanup 回调的同一
  线程有效；后续重试不会使之前回调的投影重新有效。原借用在退出事务、
  首次自动 cleanup 前即失效；drain 的 active 状态独立保留到原生
  清理结束。恢复不会重新激活旧引用，也不另造 owner。

三视角复审修复了双重发布失败时恢复收据丢失、批量首删失败时
  后续对象责任丢失，以及恢复期间释放短锁的问题。随后生命周期
  复审发现：B 阻塞等待 A 保留的短锁，会让 drain 阻止 A cleanup。
  Rooted 短锁因此统一非阻塞准入，busy 明确失败且不等于提交成功；
  `blocking` 仅保留通用调用形状，不承诺 rooted 无限等待。旧
  pathname Journal 锁语义不变。已有提交结果未知仍保持 sticky。

本轮验证覆盖实际 BlobStore 读写/检查/import/rollback/delete 的
  root 替换、加锁窗口子目录替换、符号链接与遍历预算拒绝、重复
  故障不累积对象、双重恢复失败、整批删除、删除后同步失败、独立
  进程短锁竞争，以及真实 Product 的两 lifetime lease 保留与清理。
  额外双线程回归固定 A 持锁→B 尝试→A 留恢复债务→B busy 退出→
  原 owner cleanup 完成的顺序。三视角局部复审通过，不扩大为
  完整 lmux 或默认激活通过。

最终相关集合（rooted BlobStore、旧 BlobStore、rooted Journal、
  实际 Product 图片/双 lease、writer IO/root binding、FileStore
  settlement）157 passed（5.01 秒）；补每回调 token 失效后同集合
  再次 157 passed（11.94 秒），两次不相加，也不作为性能比较。
  新增与修改文件 Ruff、四个
  源文件 mypy、轻量文档检查、当前包依赖图检查和 diff 空白检查
  通过。这是本切片证据，不替代最终 change-aware 全部适用门禁。

仍待完成：其它导入/fork/delete/工具输出/模型输入消费者与默认
  Session 工厂接线，生产服务入口/公共自动发现、完整 Harnesstui
  集成、真实安装/断连重连/首次使用性能及最终交付门禁。当前
  可选 BlobStore 的原语测试不替代这些消费者端到端验收。

## 35. 同步上下文与 Model Input 图片消费者

实际 Product 的 `build_session_context` 与 Model Input binary codec
  构造现在使用原 preparation 的 blob port；读取不再回退 pathname。
  Codec 只接受通用同步 context-manager factory，不依赖 writer
  preparation 类型，不保存 transaction-local 文件或目录引用。
  每次 externalize/hydrate 都重新准入，空 mapping 和缓存 references
  不绕过检查；构造成功的 codec 不等于长期获准使用已关闭会话。

原 writer 提取共享 admission（同 loop、closing、target、active
  计数与 drain）。异步调用仍通过 settled IO 检查两域 writer，
  同步调用直接检查，沿用同一 owner，不新建生命周期。显式 owned
  同步消费者只允许在原运行 loop 调用；无 loop、其它 loop/线程
  在触及文件 IO 前拒绝。旧 unowned 路径保留原行为。

准入覆盖 BlobStore 构造与完整 hydration，且在图片降级处理外部。
  关闭/失效绑定不被吞成图片缺失；短锁 busy 直接传播，不再伪装
  为缺失图片或完整性错误。普通损坏图片仍降级为占位文本。Graph
  接管后 root dispose 不 fence，真正 Graph close 才使旧 codec
  失效。同步接口仍可能占用 event loop，本切片没有性能提升承诺。

设计及代码三视角复审通过。评审修复了可选 scope factory 的
  falsey callable 被 `or nullcontext` 静默丢弃的问题，改为显式
  `is None` 并覆盖两个 codec 入口。测试另覆盖关闭前保存 codec、
  disposal 尚未完成、空 mapping、错误执行上下文、嵌套检查异常
  计数回落、Graph 转移、损坏降级和 busy 传播；目录替换区分准入
  前拒绝与准入后实际从原树恢复正确图片，验证投影确实替换一次。

基线 86 passed/1 skipped（7.62 秒）。首轮新增测试的两个失败是
  fixture 使用 `mime_type` 而非既有 wire 字段 `mimeType`，修正
  fixture 后 116 passed/1 skipped。补复审负测与联合 lease 回归
  后最终 129 passed/1 skipped（8.92 秒）；集合重叠，不相加。
  修改文件 Ruff、五源文件 mypy 通过。既有序列化格式、图片预算与
  默认策略未更改；这不是默认工厂或完整 lmux 验收完成。

下一步仍须接导入/fork/delete/工具输出与默认 Session 工厂，并
  完成 §34 列出的生产入口、UI、进程与真实安装性能验收及交付。

## 36. 首次获取前的原 owner 与恢复健康检查

修复实际 owned restore 的末端遗漏：原 `_lifecycle_session` 的
  附件健康检查也消费 retained blob port，并在原 operation scope
  内完成后才发布 Session。准入之后 data root 被替换仍检查原树，
  不重新按 pathname 打开附件。BlobStore 构造及逐对象 inspect 的
  busy 都直接传播；真实 missing/corrupt 仍生成健康状态，不重写
  JSONL。这是持 writer 的恢复检查，可能创建短锁元数据，不等同
  §29 的只读 catalog 无副作用保证。

新增显式 `prepare_owned_writer`：原 preparation 纯构造正文 lease，
  调用方在首次 await 前即可保留同一 owner。其原 build driver 执行
  acquire→borrow→claim→原 binding projection 更新，再进入已有
  blob acquire、binder、Store create/restore 链。失败不重新 acquire，
  不另建前置 owner；dispose 先 join 原 driver，再结算部分资源。
  只有本 preparation 独占构造且未 claim 的 lease 可普通 close；
  已 claim 必须归属于自身才可 claimed-close。原外部已持锁的
  `prepare_writer` 合同不变。没有自动创建根目录或切换默认入口。

三视角设计与代码复审通过；修复 claim 在后台从 None→self 变化
  时两次读值可能误判 closed 的竞态，统一使用一次快照。测试覆盖
  acquire/borrow/claim 前后六类失败、调用者取消时等待 native 获取、
  不获取即可 dispose、实际 create/restore，以及 A 持锁→B busy→
  B 清理不解锁 A→A 关闭后 C 可获取。恢复测试覆盖原 port、健康
  检查阶段禁止 pathname IO、真实缺失/损坏、实际附件短锁竞争与
  未交付 Session 的两域资源保留。

基线 36 passed（2.37 秒）。新 restore fixture 首轮因未设置
  `defer_materialization=True` 而被既有 restore 合同拒绝，修正
  fixture 后与内部准入集合 65 passed（3.77 秒）。最终扩展集合
  92 passed（3.94 秒）；集合重叠不相加。Ruff、四源文件 mypy
  通过。另补未包含在该集合中的 writer 进程/root binding/图片/IO
  与实际 detached Coding 回归，72 passed（78.86 秒）。轻量文档、
  包依赖图及 diff 检查通过。这是内部准入和恢复路径证据，不是
  工厂/default 验收。

### 36.1 已复核的工厂接线方向

四条入口应汇到工厂私有构造接缝，但资源算法仍在同一 preparation：
  new 执行 create；restore 执行加锁后 header 复核及 restore；import
  在两域获取后发布冻结 bundle 内容再 create；fork 在两域获取后
  克隆并改写引用再 create。现工厂先发布附件、后调用 lifecycle 的
  次序必须迁入原 driver；正文提交未知时不得回滚附件。

工厂仅保留尚未交付/待清理的原 preparation 句柄，不复制状态机。
  Session 已持有原 owner 后才能交付并移除待交付引用；失败/取消
  join 原 driver 后委托 dispose。清理债务须继续保留可恢复句柄，
  并接应用退出结算，不以异常 note 或全局集合替代责任。`fork_from`
  还须覆盖目标创建成功后源 dispose 失败/取消的交付窗口：源结算
  完成前目标仍被保留。Product 选择、header 校验和路径策略继续
  留在原工厂回调。该工厂集成仍待实施，未通过默认激活。

## 37. 工厂真实创建/恢复与未交付责任

§36.1 的首个工厂接线已实现：显式 `owned_product_id` 要求已有
  rooted runtime binder 与标准 header reader，公开 new、load/open、
  restore_context、continue_recent 接入同一 `_construct_owned`。
  工厂先保留纯构造 preparation，再 await 原 create/restore driver。
  Session 已持原 owner 且工厂仍接受交付时，同 loop 内同步移除
  pending 并返回，中间没有 await；不复制资源算法或另建 owner。

失败或取消委托原 preparation.dispose。清理失败不替换原错误，
  原 typed handle 留在只读 `pending_preparations` 中，可由工厂
  close 重试。close 首次 await 前 fence 全部未交付 preparation，
  再逐个 dispose；单项普通失败不跳过其它项，失败项不移除。close
  不处置已交付 Session，它们继续归原 Session/Graph owner 所有。
  工厂调用绑定原 event loop，错误 loop 不执行发现或 Product 回调。

设计复审修正公开 load 的预读边界：不再在 preparation 前使用
  会创建短锁的普通 header loader。现用既有 stable read_only
  预读，保留叶 nofollow，context 绑定后核对叶路径；预读仅供寻址，
  原 driver 取得 writer 后仍重新核验 header。关闭检查在预读及
  recent 扫描之前；recent 使用 `index_writable=False`。原文件锁
  与资源所有权检查未延后或删除。

阶段边界明确：显式 owned 模式目前只支持持久创建/恢复，transient、
  import_bundle、fork 与 fork_from 在最外层拒绝，不能先读取源或
  发布附件后回退旧路径。旧 unowned 默认及内存模式保持原行为。
  这些拒绝是尚未完成的接线，不是完整 lmux 的最终功能范围；导入/
  fork 必须按 §36.1 把冻结附件意图迁入原 driver 后再启用。

三视角设计及代码复审通过。基线 21 passed（1.85 秒），首轮新
  工厂集合 23 passed（1.62 秒）；补跨 loop、多个 pending 中首个
  清理失败、真实 recent 缺/坏缓存后，与旧 factory/Product/catalog
  消费者合跑 57 passed（3.47 秒）。集合重叠，不相加。证据覆盖
  真实图片 new→持久化→open→health、busy 预读不新建短锁/修改树、
  关闭前后交付、两次取消、全部 pending 先 fence、失败句柄原位
  恢复，以及已交付 Session 不受 factory.close 影响。Ruff、两个
  源文件 mypy 与 diff 检查通过。

下一步：在同一 preparation 中冻结并保留 import/fork 附件发布
  意图与回执，处理正文提交未知时的附件保留，以及 fork_from 的
  源清理完成前目标交付窗口；再接应用退出的 factory.close、默认
  工厂与生产 lmux 入口。当前不宣称四条入口或完整目标已完成。

## 38. Owned bundle 导入与提交尾部保护

显式 owned 工厂现已支持持久 `import_bundle`，不再属于 §37 的拒绝
  入口。原 preparation 在首次获取资源前冻结 records 与附件字节，
  取得正文及附件两域 writer 后才通过原 rooted blob port 发布附件，
  再创建正文。发布回执保留在同一 preparation；不另建资源 owner。
  旧默认工厂保持不变，owned transient 与 fork/fork_from 仍拒绝。

正文创建前失败，由原 preparation 回滚新附件；回滚身份冲突不删除
  替换目录，两域 lease 与待清理句柄继续保留。委托给原 rooted IO
  的恢复使用该 operation 的 settlement Event，全部 native 清理完成
  才置位。native 回滚完成不等于异步任务返回：dispose 重入必须等待
  同一 rollback task 成功返回才清空 publication，不能绕过在途回执。

正文可能已提交时保留附件。FileStore 的提交未知分类现覆盖实际写入、
  幂等成功、锁上下文退出及最终 snapshot 构造；UOW 的提交后本地投影
  失败也分类为 unknown。BlobStore 最后 publication 回执构造失败纳入
  同一恢复范围。失去 close 回执时继续 fail closed，不重试裸 fd。

三视角局部代码复审通过，修复提交尾部分类与回滚任务交付窗口两项
  问题。扩展集合 142 passed（5.34 秒）。随后新增真实目录替换负测，
  首轮因 fixture 缺有效 manifest 而先触发 manifest 错误；改为复制相同
  manifest、仅替换根 inode 后，最终导入集合 15 passed（6.14 秒）。
  集合重叠不相加；八源文件 mypy 通过。覆盖真实空/图片 bundle、busy
  无发布、冻结输入、重复取消、提交后重开、native close 丢回执、回滚
  债务重试与替换目录保全。测试恢复原 inode 仅为故障注入清理，不是
  生产恢复策略。

下一步仍是 owned fork/fork_from 的源生命周期与目标交付窗口，应用
  退出接线、默认工厂及 lmux 生产入口。本节不是完整目标验收或默认
  激活；完整验收后按用户最新授权提交、push、PR、merge 并同步本地。

## 39. Owned fork 与源先结算

显式 owned 工厂现接通 `fork` 和 `fork_from`。live-source fork 要求
  原正文 writer 和 blob port，不能把 unowned 的 noop scope 当作
  读取准入，也不能回退 pathname。选中记录的深拷贝、引用收集及严格
  附件字节读取在源同一同步 scope 内完成；退出后仅携带冻结值。目标
  规范化 authority 的引用改写是纯值操作，随后复用 §38 原 preparation
  的双域 publication/create/rollback。缺失或损坏源附件导致失败，
  不使用 restore 健康检查的降级语义。普通 fork 不关闭调用者的源。

设计复审简化 §36.1 的交付窗口：`fork_from` 改为先持久 owned restore
  源、冻结数据、完全结算源，再开始目标构造，而非先创建目标再 finally
  关闭源。私有源的原 preparation 从首次 await 前起一直在 pending；
  不先交付再收养，不新增资源 owner。源读取失败保留主错误；清理失败/
  取消保留同一句柄，factory.close 可重试，但不自动重放目标创建。源
  结算后再次检查 factory 接受状态。因此关闭竞争不会启动新目标。

该模式的 `fork_from(path)` 会获取源 writer，活动源返回 busy；已有
  live Session 应用 `fork(source)`。旧 unowned 两入口不变。owned
  transient 仍拒绝；当前不是默认 Session 工厂激活或完整 lmux 验收。

三视角设计与局部代码复审通过。修正一个测试证据缺口：冻结验证的
  屏障从目标 binder 移到真实双 lease 获取后、附件发布前；明确检查
  publication 为空、目标 authority 不存在，再关闭并移走源，放行后
  验证原图片可用。覆盖选中路径、空附件、busy、源清理失败/取消、
  无能力源、错误 loop、缺失/损坏、目标提交未知及工厂关闭竞争。
  Graph 测试仅覆盖内部 ownership 状态路径，不代表完整 Graph 集成。

基线 31 passed（3.40 秒）；首轮两项 fixture 错把已绑定对象作为绑定
  配置，修正后 42 passed（3.04 秒）。扩展目标故障测试曾误 patch 类
  方法而非模块函数，修正后与 factory/import/hydration/blob 合跑最终
  75 passed（4.39 秒）。集合重叠不相加；源文件 mypy、修改文件 Ruff
  与 diff 检查通过。

下一步仍需完成应用退出、默认工厂和剩余 Session 消费者接线，再进入
  公共服务发现、一命令生产入口、完整 Harnesstui 与真实安装验收。

## 40. 真实 Hosted 工厂保管与应用退出

`create_coding_hosted_attempt(..., owned_transcripts=True)` 显式接入每目录
  实例的 owned factory，默认仍为 False。目录直接消费 new/restore 的
  原 LifecycleSession，返回后、任何 manager/Binding/Candidate 包装前
  同步保管；包装、验证或关闭竞争失败时清理原 Session，失败句柄保留
  在 pending_sessions，工厂自身的未交付 preparation 仍在原工厂。
  Candidate 完整包装且关闭检查通过才移交，不接管已交付 Candidate。

工厂新增同步 fence，目录 close 在等待自己的互斥锁前先 fence 目录
  与工厂 pending。Coding 应用请求的可选 typed session_owner 接入
  原 PRODUCT 关闭阶段，正常 shutdown、启动失败与未转交 continuity
  attempt 都经过同一 Product owner。fence、Product 清理和独立目录
  清理分别尝试，普通单项失败不跳过其它域；总体仍未完成，不释放
  continuity lease。目录清理失败可由原 shutdown owner 重试。

真实 Agent/Graph 接线暴露此前单独工厂测试没有触及的启动失败：命令
  输出 adapter 构造旧 pathname BlobStore，journal 锁的 parents=True
  在 umask 002 下创建 0775 的 session-assets，随后 owned hydration
  拒绝该目录。修复两处 AgentProduct 组装，让输出 adapter 使用原 blob
  port、同步初始化 scope 与异步 execution scope。delegate、输出发布
  及 scratch 清理均在原 admission 内；取消时等待 delegate 协程退出，
  不替任意自定义 delegate 承诺其后台 native 工作结算。publication 失败
  即使返回 retention error，原 port recovery 债务仍阻止释放两域 writer。
  不 chmod 已有目录，不新增资源 owner。已包装 adapter 复用按规范化
  authority ID 比较，兼容 legacy:id。

临时边界仍明确：owned Hosted wrapper 不发布尚未受管的辅助聚合缓存，
  Hosted 发现仍读取 canonical header；实例 fork 显式拒绝，不能回退
  全局 unowned 工厂。Hosted 的 64 位 create identity/continuity envelope
  需要单独的 clone intent，不能冒用普通 32 位 fork 身份。该 opt-in
  要求调用方预备安全 Session 根；尚未接自动初始化、默认共享目录与
  一命令 CLI。旧 Hosted/default CLI 行为不变。

三视角设计和局部代码复审通过。修复 PRODUCT 首域清理失败跳过独立
  目录清理、规范化 ID 比较两项 P2。基线 18 passed（6.04 秒）；纵向
  首轮 38 passed/1 failed，mask 后的 session_unavailable 经原构造接缝
  捕获得到上述 0775 根因，修复后真实 Hosted/输出集合 13 passed。
  新输出测试的错误 ExecRequest 类型与非法 fixture 文件叶已修正。
  最终扩展集合 56 passed（17.96 秒），追加 publication recovery 债务
  后输出专项 4 passed（1.69 秒）；集合重叠不相加。包含真实 Product
  创建、首轮、shutdown、continuity 重开、独立进程 busy→释放→重开、
  包装失败保管、关闭竞争、取消期间双锁保留及连续性租约负测。

下一步继续受管服务的默认目录初始化与生产入口接线，并解决 Hosted
  clone 身份和剩余 Session 消费者；之后才是完整 Harnesstui、真实安装、
  断连与性能验收。此处不宣称默认激活或完整目标完成。

## 41. 新部署目录初始化与原句柄清理

新增显式 `ManagedLayoutPreparationV1`，从 namespace/service/instance 与
  注入的 runtime root 推导固定九个目录。纯构造预先保管九个原 directory
  owner，路径最多 64 层、4096 UTF-8 字节，聚合 fd 预算 512；open 消费
  同一绝对 deadline，最后一次身份复核后再次检查期限才发布 initialized。
  不读环境、不创建 Session 根、不登记服务或授予 recovery authority。

已有 PrivateManagedDirectory 增加显式 create_parents 选项，默认行为
  不变。逐层 nofollow 打开并绑定身份，再同步 parent、复核绑定；EEXIST
  也同步，不能假设另一初始化者已完成落盘。新建目录 0700，既有安全
  祖先权限不变；符号链接、文件及不安全可写祖先拒绝。同步失败保留
  原 parent fd，close 只重试同步，不重新 mkdir 或删除残留。

关闭前将原 fd 收据移入持久账本，native close 前标记不确定状态。
  即使真实 close 后被 KeyboardInterrupt 打断，其余独立 fd/目录仍尝试
  清理；未知数字 fd 永不重试，不能误关系统复用的 fd，也不能误报 clean。
  未完成初始化不允许原 owner 再 open；调用方负责保留并关闭原对象。
  异步组合仍必须等待原 native 工作结算，不以取消等待者替代清理。

三视角局部复审通过，修复最终复核超时、同步证据早于 inode 绑定及
  关闭中断丢失其余句柄三项问题。目录/路径/文件专项 57 passed（3.45 秒），
  直接消费者 registry/lifecycle/bootstrap/admission 82 passed（5.51 秒）。
  包含不同 umask、首次创建、既有权限不变、同步债务、确定性替换、
  mkdir 后超时、真实 fd 复用及独立 owner 中断。双进程测试仅证明同一
  布局的独立进程初始化兼容，不声称命中特定 mkdir/fsync 竞争窗口。
  两个源文件 mypy 与修改文件 Ruff 通过。

该接口仅供确认的新部署初始化，禁止借它重建既有或未知服务丢失的
  runtime/lifecycle fence。尚未接生产 coordinator、默认 Session catalog
  或一命令 CLI；不得用虚构 instance 初始化临时目录以引导 registry。
  完整目标及最终发布前置条件不变。

## 42. 同库 Session 发现视图与非破坏性历史适配

新增显式 `CodingManagedSessionCatalogV1(session_root=..., workspace=...)`。
  两个 scope 注入同一规范 Session 根，强制使用原 owned factory、候选
  保管与关闭路径；不另建 owner 或元数据索引。旧 Hosted 仍要求不同根。
  基类仅提取目录校验、记录读取、视图和打开前后准入钩子；旧打开准入
  保持 no-op，由原 Product validator 分类，managed 才增加严格检查。

普通 Coding 历史按 §6 算法导出稳定 continuity，保留 conversation ID、
  header、正文与附件。canonical identity 的 scope 固定 user_home；展示
  identity 使用当前已准入 scope，而 envelope/binding 不含选择视图。
  已有 coding.hosted v1 则按原 header scope 与 cwd 重建 fingerprint，
  执行完整字段/schema/create identity 校验并保留原身份。字段存在但
  null、畸形或错误时拒绝，绝不回退普通历史算法。读取不解析 header
  中 cwd 的物理路径，不要求历史工作区当前存在。

cwd 只展示同工作区，user_home 可展示其它工作区但不可打开。真实
  runtime/capability validator 判定不兼容时展示 unsupported/unavailable；
  open 在取得 writer 前拒绝，取得原双 writer 并恢复后再次校验完整
  header、revision、workspace 与 runtime。失败时原 Session 保管和清理
  债务不丢失。两个 scope 保留不同 selection reference、相同 envelope；
  这不代表尚未接线的 resolver 已完成 runtime 去重。

规范身份冲突检查先于工作区过滤：同一文件跨两个视图合法；不同文件
  声称相同 ID 必须拒绝，即便其中一个文件属于另一个工作区。新建仍
  使用 canonical header 中的 v1 create-operation，落盘后丢回执由原
  operation/continuity 对账恢复，不另建正文或 fallback 到 unowned。

三视角局部复审通过。修正旧 Hosted 打开语义被无意加强的问题，补充
  完整根/兄弟附件树的 mode/inode/mtime/bytes 只读证据、真实不兼容
  runtime header 与禁止 binder 调用、真实落盘后丢回执恢复，以及
  owned restore 返回后复核失败且首次清理失败的原 Session 保管测试。
  初轮 30 passed（7.44 秒）；最终 managed/旧 catalog/owned shutdown
  集合 37 passed（18.44 秒），包含两个视图顺序与隐藏冲突负测。
  旧 Hosted discovery/application/bootstrap 另 23 passed（8.03 秒）；两个
  源文件 mypy、修改文件 Ruff、轻量文档与 diff 检查通过。
  集合重叠不相加；本条只证明 catalog 切片，不是完整 lmux 验收。

下一步接 managed resolver/profile 的 selection-scope 与 canonical identity
  分离、默认 Session 根准备，以及普通 Embedded/维护写入入口的共同
  writer；生产 coordinator、一命令入口、完整 Harnesstui 与真实安装
  断连/性能验收仍待完成。不改变默认入口，不自动收养手工 G16 服务。

## 43. 显式 managed 应用与选择 scope 接线

新增 `CodingManagedApplicationLaunchV1` 与 `create_coding_managed_attempt`。
  使用独立 `coding.managed-mux` profile；managed_selection 必须显式开启，
  要求 exact canonical catalog、其完整 admitted scopes 和同一个 catalog
  shutdown owner。旧 G16 launch 继续要求不同根。两种启动方式复用原
  Product/bootstrap/continuity 装配，纯构造不打开 Session 或启动后台服务。
  新 launch 拒绝 application root 与 transcript 根、兄弟 session-assets、
  .session-blob-writers 的双向重叠，不 chmod 或迁移已有数据。

resolver 先验证 selection scope，并经原 catalog 的 workspace/runtime/
  canonical envelope 校验和原 AppHost 路由；再核对完整 Product、continuity、
  Session 核心身份，仅在返回 lease 的 wire view 上投影所选 scope 与
  fingerprint。Product binding、writer identity、header 不改，关闭仍委托
  原 lease/runtime owner。旧 resolver 仍要求完整 identity 严格匹配。
  可选 execution adapter 尚要求 owner 与 Product 的完整 identity 相同，
  因此本轮在 request 和直接 resolver 构造阶段拒绝 managed+execution，
  不在创建 Session 后才失败，也不删除 execution 的精确所有权校验。

保留现有应用规则：同 Session 不能重复加入多个 Mux。attach 已存在的
  Mux 直接复用已有 port，不调用 Session resolver；这与重复 open_member
  不同。当前 owned catalog 仍会在 AppHost live-runtime 去重前尝试 writer，
  本轮不宣称解决重复打开时的 runtime 复用，也不扩张多成员共享同一
  Session 的语义。失败不得新增成员或关闭正在执行工作的原 runtime。

三视角局部代码复审通过，修复 managed/execution 组合过晚失败与附件
  writer 锁域隔离遗漏。真实 ordinary（含图片）及两种 v1 scope 历史均
  从另一 scope 恢复，旧正文不变；detach/attach 的 Product 工厂计数保持
  一次。模型门闩确认已接纳工作运行中，跨 scope 重复 open 被拒，独立
  catalog 仍观察 writer busy；放行后唯一回复完成、再执行一轮成功。
  shutdown 与 fresh continuity 重开后再提交成功，验证回复文本及完整
  历史中的完成次数；模型响应为本地 synthetic，不是网络或性能证据。

首轮 3 failed/16 passed：测试在生产静态方法绑定后才安装观察器，导致
  工厂计数漏记；改为构造前 class 方法观察。增强测试曾误先等待整轮
  start_turn 再释放模型门闩，导致测试互等；已核实原进程并以 INT 中止，
  exit 2，不算通过。修正为独立 submit task 后 7 passed（26.39 秒）。
  最终 managed/旧 Hosted/application/bootstrap/shutdown/launch/execution
  合跑 56 passed（51.82 秒）；增加锁域隔离与重启后首轮证据后专项
  9 passed（29.07 秒）。集合重叠不相加。四个源文件 mypy 与修改文件
  Ruff 通过。

下一步继续默认 Session 根准备、Embedded/维护写入口共享 writer，及
  managed child/生产 coordinator 接线；一命令后台入口、完整 Harnesstui、
  有界日志/tmp 和真实安装/断连/性能验收仍未完成。此处不是默认激活。

## 44. Canonical 应用接入后台 Local listener

新增 `coding.managed_local` 的显式 launch/command 与 invocation 派生入口。
  `CodingManagedLocalCommandV1` 只覆盖 exact launch 校验和原 managed
  attempt 选择；prepare/activate/start/close、超时、失败保管、应用移交
  及重试全部继承 CodingLocalCommandV1。基类抽出两项钩子，仍拒绝新
  launch；新 command 也拒绝旧 launch，错误类型不构造目录或 attempt。

application/connection 根取自原 namespace/service/instance layout，
  Session 根仍由 Coding composition 显式注入，connection scopes 直接
  来自同一 canonical application 的两种视图。连接根与 application、
  Session、session-assets、.session-blob-writers 双向隔离；invocation
  派生入口另外拒绝 Session/附件/writer 域与持久或 runtime lmux 控制域
  重叠。未新增路径扫描、目录初始化、进程 owner 或单独清理路径。

三视角局部复审通过。新增纯构造/未启动 close 的完整树不变、错误
  Product 在 Path.resolve 前拒绝、exact launch 交叉拒绝时禁止目录与
  attempt 构造、根/后代/祖先重叠、管理控制域与封闭 endpoint 参数负测。
  局部准入与原 LocalCommand/ownership/launch 集合 57 passed（36.20 秒），
  三个源文件 mypy、修改文件 Ruff 通过。

真实 detached helper 新增 canonical 模式，走生产 managed LocalCommand、
  ManagedChildBootstrap.run_process 与原 LinuxServiceProcessV1。生产仍
  仅继承原 handoff fd；模型释放和故障观察使用 child 内新建的测试 socket，
  不进入生产启动接口。canonical 三项 3 passed（33.02 秒）：父正常退出、
  父 os._exit、迟到 birth+TERM；均在真实模型已进入时注入 HUP、断开
  原客户端并重连，身份不变、仅一次模型调用和唯一回复，最后明确 stop
  或 TERM 收口并获得原 owner 清理回执。只有 canonical Session 根出现
  一个 JSONL，不创建 cwd-sessions/home-sessions。调整 helper 参数后旧
  六项独立重跑 6 passed（51.07 秒），包括控制故障、迟到 birth、INT/TERM。

上述是本机真实进程与连接生命周期证据，不是实际 SSH 服务器登录配置
  或安装性能验收。父端 pidfd 退出观察仍不冒充持久 process-scope 结算；
  测试保留三事实证据区分。下一步仍需默认 Session 根准备及共享 writer
  完整接线、生产 coordinator、自动启动/复用入口、有界产物和完整 TUI。

## 45. 首次 Session 根初始化与不可重授的显式权限

`DirectoryWriterLease(create_root=True)` 在原 writer 账本中准备缺失的
  Session 根与父目录；默认仍为 False，不选择路径，不引入 AppHost
  依赖。新目录请求 0700，既有安全 0755 根保持不变。逐级 no-follow
  打开、检查可信父目录并绑定 child inode；mkdir 前登记父同步债务，
  包括 EEXIST 的路径也先绑定后同步。原 root fd 不按路径重开；祖先
  fd 全部结算后才获取 writer 锁，成功仍只持有原三个 fd。

创建、同步或关闭失败均留在同一 owner；close 只推进原父 fd 的同步
  与释放，不再次 mkdir、不删除部分创建的目录。未知 close 不重试
  已可能复用的数字 fd，也不允许 held/borrow/claim。可选参数通过
  原 transcript preparation/lifecycle/factory.new 传递，仅持久 owned
  create 可用；restore 在 native IO 前拒绝，外部已持有 lease 不能
  再补根创建权限。取消等待者不会取消原 native driver；dispose 等待
  它完成并统一释放已构造的 runtime，而非承诺取消后从未开始构造。

Managed catalog 的 `initialize_session_root` 是可信组合显式授予的
  一次性初始化权限，**新会话不等于新会话库**。默认、CLI、普通恢复
  和重试都不自动获得它。创建前消费一次；任何既有根观察都会撤销。
  三视角复审发现并修复一项 P2：仅在扫描前后检查路径存在性会漏掉
  “扫描曾见根、返回前根被移走”。现在目录 revision 与历史读取将
  正向/未知观察单调保存在 Event，后续路径缺失不会抹去该事实。
  跨进程的首次部署证明仍须由生产 coordinator 提供；本节不是缺失
  fence 的自动修复机制，也没有默认激活该权限。

本轮三视角局部代码复审通过。确定性覆盖新根与 umask、既有 0755、
  只读发现、无授权失败、旧根移走、扫描中出现再消失、部分初始化
  失败且原同步债务保留、symlink/替换、未知 close+fd 复用，以及
  native mkdir 门闩中的取消。真实独立子进程在 mkdir 后暂停，另一
  进程走 EEXIST 取得 writer，原进程继续后 busy；最后关闭后可重获。

首次局部 31 passed（2.97 秒）。取消扩展首轮 1 failed/33 passed：
  测试错误要求 binder 不得开始，改为核实原 driver 完成及 runtime
  清理完毕。修复后 writer/root/factory/lifecycle/blob/新旧 catalog 与
  shutdown 联合集合 127 passed（20.67 秒）；不重复累加重叠集合。
  七个相关源文件 mypy 与修改文件 Ruff 通过，扫描观察修复后的两项
  catalog 类型检查另行复核。没有网络模型、安装或性能验收结论。

下一步仍为 Embedded/维护写入口统一 writer、生产根初始化授权与
  coordinator 接线，再落地一命令启动/复用、完整 Harnesstui 及有界
  日志/tmp。全目标继续，不以本局部替代最终交付。

## 46. 原 writer 内的 transcript 删除与提交边界

新增 owned-only `AgentTranscriptSessionFactory.delete_transcript`。当前
  Session 检查和 factory closing 检查先于发现；缺文件返回 False 仅
  表示本次未删除，不是此前不确定操作或清理债务已结算的证据。
  readonly header 发现后沿原 `_owned_source` 保留 preparation，恢复
  取得同一 Session/blob writer，在原 operation scope 内调用 Store
  delete，最后沿原 disposer 收口。内部 Session 从不交付，未新增
  maintenance owner，也不在删除成功时先释放 writer 再清理。

该入口只删除 transcript 及 Store 原有 tombstone/index 派生物，明确
  保留附件。它不是 Product 完整 delete，不默认替换旧无锁入口；后续
  附件破坏性维护仍须在同一权限下取得唯一引用证明。活动 Session
  删除 busy；已提交后 runtime 清理失败，原 preparation 留 pending，
  双 writer 仍占用，调用者可继续关闭原工厂，不能换 owner 假装清理。

三视角局部复审修复两项 P2：

- Store 的 tombstone 写入、正文删除及整个 binding 退出由单调
  `may_have_committed` 状态覆盖；异常后不再读 tombstone 猜测是否
  提交，原 `StoreCommitOutcomeUnknown` 不被清理错误替换。
- factory 校验确切 DeletionReceipt 类型、revision 与本次稳定的
  operation_id 后才确认提交。非法回执按 unknown；确认回执后的
  disposer 失败抛 `TranscriptDeletionCleanupPending(receipt)`，区分
  “已提交但清理未结算”和普通删除失败，不自动重删。

扩展 Store conformance 发现此前 create 的一个回归：纯编码失败、
  尚未进入 native 写边界，也被标为 unknown。Journal 原编码块新增
  私有标记，仅 FileStore 写入启用，普通 Journal 调用仍抛原异常。
  FileStore 只在正文 `_write_unlocked` 编码失败时撤销提交推断；不
  重复编码，侧车发布和后续 native/退出失败仍保留 unknown。

首四项删除测试 4 passed（1.37 秒）。首轮删除/Store/factory 联合
  1 failed/74 passed（20.42 秒），失败为上述 codec 合同。修复后扩大
  到 Journal 集合 7 failed/129 passed（28.35 秒）：失败均为新增附件
  oracle 的测试根隔离问题，不同测试共用父级 data root 和 Session
  ID，导致 manifest 累积。改为隔离整个 data root 后删除专项
  10 passed（1.80 秒）；正文编码捕获进一步收窄后的 conformance 复核
  1 passed/40 deselected（0.53 秒）。成功、cleanup pending、unknown 均实际读取
  原图片，成功还比较 manifest；missing False 后原 pending 与 busy
  不变。集合交叠不累加。三个源文件 mypy 与修改文件 Ruff 通过。

默认 Embedded 接线前的边界已经明确：不把模块全局 `_FACTORY` 改为
  loop-bound owned 工厂。实际应用 owner 应在自身 loop 内持有、fence
  和 close 持久工厂，瞬态/只读预览单独选择；上下文引用不充当清理
  owner。还需修复 ProductTranscriptSession 的工厂返回与 `cls(...)`
  包装之间交付缺口，实例 fork 沿用创建工厂。当前尚未实施这些默认
  接线，也未完成一命令入口、完整 TUI 或安装性能验收。

## 47. Product 包装与原工厂交付收口

修复 factory 返回 LifecycleSession 与 ProductTranscriptSession `cls(...)`
  包装之间的清理责任缺口。owned 工厂支持私有同步 `_projection`：原
  `_construct_owned` 收到 Session 后先完成包装、绑定创建工厂引用并
  再查 accepting，全部成功后才从原 pending 移出 preparation。失败
  沿原 `_discard_failed_owned` 处理；disposer 暂时失败仍保留原对象和
  writer，不新建交付 owner、缓存或换工厂释放权限。

new/load/open/continue_recent/import_bundle/fork_from 和实例 fork 的
  Product 包装统一经过该接缝；内部 fork source 不执行目标投影。
  裸 LifecycleSession 的原调用没有 callback 时保持原交付行为。旧
  unowned Product 分支不传私有参数，内存工厂的选择与实际应用持有
  范围尚待后续接线。投影只允许同步包装，不得在 factory 交付前对外
  发布、启动异步工作或转移 Graph；这是内部调用合同，不宣称能隔离
  任意不合规构造器的副作用。

owned Product 实例保留创建工厂引用，fork 不重新读取变化后的类级
  工厂选择。三视角复审发现并修复一项 P2：引用判断使用显式 `is not
  None`，不把合法 falsey factory 当作缺失。其余局部复审通过。

首批 Product/原 factory 回归 26 passed（2.06 秒）。扩大到原 Coding
  Session、owned 导入/分支与 Hosted catalog 后 110 passed（11.06 秒）；
  集合交叠不累加。新增七入口单次投影、构造失败/工厂引用赋值失败/
  同步 fence 且 disposer 失败时原 pending 与 writer 保留、falsey
  factory 与类选择变更的 fork、legacy 严格无参数调用等证据。交付
  后 Graph ownership 状态测试确认 factory.close 不再 fence 已交付
  Session，仍可追加，最终只能由 Graph disposer 释放；这是状态边界
  测试，不替代完整 Graph 组装验收。两个源文件 mypy、修改文件 Ruff
  与 diff 检查通过。

接下来在实际应用 owner 内选择与持有持久 factory，瞬态预览保持
  单独的只读来源路径，再统一默认 Embedded/维护入口。尚未改模块
  全局 Coding 工厂，也未激活 managed 一命令入口；完整目标仍继续。

## 48. Product 构造失败与原生命周期关闭

`ProductTranscriptSessionLifecycleStore` 在 transcript 返回后立即保管
  原对象，直到验证、Product builder 与 Session 交付成功。构造失败
  且 disposer 失败时保留原异常、附加清理说明，并保留原 transcript
  供 close 重试；不通过重新打开文件或创建另一个 factory 回收写锁。
  close 先拒绝新构造、等待已接纳调用，再逐项清理未交付对象；一个
  普通清理异常不阻断其他独立对象的清理。取消仍保留未完成引用。

`ProductSessionRuntime.dispose_session_runtime` 先 fence 该 store，
  由原生命周期清理已交付 Session，再关闭未交付 transcript；两处
  失败均不丢失清理责任。已经开始的异步 builder 不在成功返回后
  单独销毁 transcript，而由原 transition lock 接纳并处置迟到的
  Session，避免丢失完整 Product/Graph 的责任。绑定层通过公开
  `runtime_disposed` 判断真实处置完成，不把 Graph compatibility
  disposer 的 no-op 误报为成功。

首轮含 Coding runtime 的回归 2 failed/115 passed（265.84 秒），两项
  失败为新增 fixture 漏传必需的 dispose_session hook，未进入被测
  路径。修复后构造清理专项 9 passed（2.08 秒）；补异步 builder
  竞态后真实 writer 文件 3 passed（1.46 秒）。集合交叠不累加。
  验证包含主异常保留、原 pending 与 writer busy、重试后锁可获取、
  独立清理、关闭拒绝新接纳以及迟到 Session 在关闭返回前清理。
  Graph 用例仅验证 ownership 状态与实际 writer，不替代完整 Graph
  组装。三源文件 mypy、六修改文件 Ruff 通过。
  三视角局部复审通过；生命周期与测试视角提出的迟到 builder 和
  独立 pending 清理证据已补齐，并经对应评审者再次只读确认。

此 store 只负责已经返回的 transcript；更早的 Product 包装失败仍
  由原 factory pending 保管，下一步需由实际应用同时持有并关闭该
  factory。尚未激活默认工厂、一命令启动或完整 Harnesstui。
  用户已追加最终交付授权：完整目标验收后 commit、push、PR、merge
  并同步本地 main/harness；本节不作为提前发布未完成目标的依据。

## 49. 实际 Coding runtime 持有工厂与只读预览

`AgentSessionRuntime(owned_transcripts=True)` 现在持有应用级持久
  factory，而非改变模块全局 `_FACTORY`。初始 Session 必须由该
  runtime 构造；关闭先校验原 loop、fence factory，再分别处理原
  Session 生命周期、factory 未交付 preparation 和 Coding continuity。
  首个失败保持为主异常，后续失败附注且原 owner 保留供重试。默认
  选项仍为 False，不宣称普通 CLI/Embedded 已激活此模式。

Product facade 增加兼容的 `_factory_for_persistence(persist)` 接缝，
  默认继续调用旧 `_session_factory()`。应用绑定类只是原 factory
  的引用，不另设生命周期。持久实例 fork 沿用原创建工厂；瞬态
  操作选择独立内存绑定，磁盘 header/snapshot 与 recent discovery
  均只读。factory 的 `index_writable` 选项保持旧默认，owned 工厂
  强制禁写，瞬态应用工厂也明确禁写。

三视角评审发现并修复可达的旧实现旁路：删除委托原 factory 的
  writer-owned transcript 删除，明确保留附件给显式维护；重命名
  在原 `_owned_source` 内完成包装、追加、summary 与清理，失败时
  不丢失原 preparation；辅助索引发布暂不调用 pathname cache。
  只返回路径、会丢失新 Session owner 的 `create_branched_session`
  在这个绑定类中明确拒绝，返回完整 Session 的 fork 路径保留。

含图片预览的构造健康检查曾仍创建 sibling 附件锁。修复后
  `SessionBlobStore(read_only=True)` 复用原稳定文件读取、完整性与
  manifest 检查，但 shared 操作不创建目录/锁，exclusive 操作拒绝
  写入。非持久 lifecycle 的附件健康检查选此路径；这是 advisory
  检查，不宣称跨文件原子快照。默认持久和 rooted writer 路径不变。

首轮实际接线测试 2 failed/15 passed（5.04 秒），失败为测试工厂
  将 keyword-only bootstrap 直接用作位置参数端口；修正测试适配
  后 3 passed（7.41 秒）。加入图片全 data-root 快照后 3 passed
  （6.65 秒）。维护与附件扩展回归 1 failed/37 passed（8.92 秒），
  失败为测试用空 import 验证 readonly，却先命中原空输入校验；改
  为合法 blob 输入后，与真实 Graph fork、legacy SessionManager、
  lifecycle/rooted blobs 合跑 91 passed（11.61 秒）。另补实际绑定
  进行中关闭、全局 factory 不被替换，2 passed/6 deselected（9.24
  秒）。交叠集合不累加。七源文件 mypy、九修改文件 Ruff 通过。
  三视角对各自所报问题修复后的局部只读复审均通过。
  修改实际 runtime 关闭路径后的原 Coding runtime/构造保管回归
  90 passed（297.17 秒）；进程已正常退出。文档、架构依赖生成物
  与 diff 检查通过。

当前实际 create/restore/fork 已验证 Graph 所有权、第二 runtime
  writer busy 与清理后可恢复同 conversation；维护覆盖 busy/成功/
  关闭拒绝、rename disposer 失败原 pending 保留。图片预览同时
  验证 open/recent/in_memory、missing/corrupt 聚合索引和完整 data
  root 不变，blob 独立测试检查无目录创建、拒绝写入与内容损坏。
  仍需默认入口首次根授权、旧维护/导入入口的统一接线、生产服务
  协调、一命令及完整 Harnesstui/真实安装验收，不能提前发布为完成。

## 50. 公共父端单次启动桥接

`ManagedServiceStarterV1` 将此前测试脚本中的父端启动流程接入公共
  AppHost 实现：借用已准入的原 journal，先 CAS 预留新代，再为该
  真实 instance 准备目录，保管原 socket 和 LinuxServiceProcessV1，
  单次 spawn 后登记原生身份。Product/composition 注入纯 request
  构造函数，持久锁外调用；不把启动命令选择下沉到 Hosting。

新增 `resolve_managed_service_paths`，在尚未预留 instance 时解析
  registry/lifecycle 等稳定位置，不再需要伪造 instance 来取得控制
  路径。原 Deployment 路径值与字段顺序保持兼容。新启动流程要求
  registry 与 lifecycle 根已经存在，丢失时不重建；实例目录只在
  journal.prepare 成功后创建。首次 namespace 初始化授权仍由后续
  生产协调器解决，此类不根据目录或进程缺失推断旧服务已停止。

每个对象只允许一次 prepare/spawn。prepare 回执丢失时可观察本
  attempt，但不会据此重放 native effect；spawn 后报错仍保留原
  process，register_birth 只重试身份登记。登记回执丢失时读取原
  journal 对账，不重新启动。close 只关父端句柄与目录资源；它不
  kill、等待或把原代标记 clean，committed child 的生命周期仍由
  既有子端协议负责。没有进程存活或 application ready 的返回承诺。

三视角发现并修复两类 P2：构造时拒绝异 UID namespace；加 mutex
  后与紧邻 spawn 的协作准入点重新检查原 deadline/closing。准入
  后 native spawn 不可抢占，原对象保持保管。确定性线程屏障验证
  check 与加锁之间、最后一次 journal read 期间发生 close 时，不
  再产生 prepare/register 或 Popen。全流程贯穿一个 absolute
  deadline，journal.prepare 的新可选参数不改变旧调用合同。

首轮 starter/path/layout/lifecycle 回归 55 passed（5.72 秒）。
  关闭竞态修复后 starter 专项 8 passed（1.62 秒）；增加异 UID、
  真实 spawn 后错误、独立资源清理、unknown socket close、callback
  失败/过期后最终 14 passed（2.16 秒）。先后竞争验证第二 starter
  不调用 request/spawn，不冒充同时并发压力验收。真实子进程只等
  EOF，不含 Product/模型或派生进程，均由测试显式回收。unknown
  socket 用例在真实关闭后注入错误，验证债务不被重试或伪报清理；
  不遗留实际 fd。集合交叠不累加。四源文件 mypy 与修改文件 Ruff
  通过，三视角对修订后的 starter 局部复审通过。

本节不等于完整 EnsureStarted/Discover/PrepareConnection：生产
  child entry、ready 身份验证、初始化/异常恢复协调及一命令仍需
  接线。原 registry 与 native/process 所有权未替换，Session、
  完整 Harnesstui、日志/临时配额及安装验收仍在完整目标范围内。

## 51. 生产 Coding 子进程入口与精确连接实例

`coding.managed_process` 提供真实模块入口和纯 launch request 构造。
  请求固定 `python -m loushang.coding.managed_process`，传递原
  invocation、显式 Session 根和唯一继承 fd，不接受任意模块/工厂
  名。环境拷贝冻结 `LOUSHANG_HOME` 与 `LOUSHANG_RUNTIME_DIR`，
  默认 Session 根仍是该平台 home 下的 `data/sessions`。此处只选
  路径，不创建或修复 Session/namespace 目录。

子端先严格解析 bounded invocation/参数，再收养原控制 fd，复用
  同一 bootstrap 与固定 15 秒 admission deadline。busy 只重试
  原 open；完成后绑定 CodingManagedLocalCommandV1 并进入既有
  run_process。绑定前失败非零退出、不宣称 clean stop；绑定后
  的长期运行、HUP、INT/TERM 和未知清理债务仍由原 process owner
  负责。失败输出固定代码，不打印原 argv、路径或异常详情。

为后续公共 PrepareConnection 接线，原 invocation.instance_id
  经 Coding managed launch、AppHost local、LocalAppServer 传入
  现有 connection record.instance，不增加 wire 字段。旧调用
  缺省仍生成随机 instance；认证密钥独立随机生成。客户端新增
  expected_instance，在读取原 record 后、创建 socket 前匹配，
  后续认证仍绑定该 record 的 instance/digest/key。此项只校验
  所选记录，不替代协调器对当前 journal/native/stop 状态的复核。

真实生产模块测试已验证：通过原 starter 启动 Coding 服务，认证
  后 create/list Mux，关闭父端启动 fd 和旧 client 后，fresh client
  找回相同 Mux 元数据；协议 stop 后 native 退出且原 journal
  application cleanup 成功，未伪造 process/scope stopped 事实。
  未创建 Session 或调用模型；这是同一父测试进程中的 fresh client，
  不冒充父进程退出、SSH、installed wheel 或首次模型调用验收。

首次真实测试已到 create/list，但测试误用 muxes 字段，1 failed
  （10.00 秒）；改为协议真实 mux_spaces 后 1 passed（16.98 秒）。
  扩大到入口纯值/错误脱敏、managed/legacy Coding local、AppServer
  local/record 后 92 passed（45.52 秒）。新 instance publication、
  stale client 零 socket、非法 instance 零记录负测 6 passed/31
  deselected（0.79 秒）。六源文件 mypy、九修改文件 Ruff 通过。
  三视角复审提出的测试清理 P2 已修复：setup 抛错时始终从原
  starter 收回 Popen/原 pidfd observer，真实丢失登记回复用例确认
  子进程被精确、有界回收；没有 broad PID scan 或假定 EOF 会停止
  committed child。入口与 instance 接线局部复审均通过。

后续接入公共服务选择/EnsureStarted/PrepareConnection、首次目录
  授权和异常恢复，然后完成 lmux 简短命令与完整 Harnesstui。
当前默认 CLI 仍未激活，日志/临时配额与完整安装/性能验收未完成。

## 52. 公共精确实例连接接线

AppHost 可选 `ManagedConnectionLeaseV1` 接收已准入 journal、namespace、
  service 与精确 instance reference，不发现或创建目录、不启动或停止
  服务。调用者先持有 lease，再 prepare，最后 close；journal 的寿命
  覆盖 lease。UI 不接触认证记录，只得到 AppServer 语义 client、可选
  discovery/execution client 和不含路径的 scope。缺省 CLI 尚未接入。

准入先读取当前 journal，要求同一 COMMITTED 且未 stop 的实例，然后
  通过 Hosting 重新验证原生身份并持有 pidfd observer。AppServer
  认证明确匹配 Product/instance；认证后再次检查相同 journal 状态、
  原 observer 与 stop fence，回到事件循环后再检查原绝对 deadline。
  stale reference 不自动重选；这只是连接准入观察，不承诺其后不会
  停止，服务端继续负责每次请求的权限与生命周期。

prepare/close 是同 loop 的原任务，公开 waiter 取消不取消这些任务。
  内部 native 调用使用独立实际完成回执，内部任务取消也不能以
  Task.done 冒充 native 完成。复用本包 child 的任务 publication gate，
  executor 另以准入 gate 保证提交回执失败时不执行未收养副作用。
  连接未结算前保留其借用的 directory；observer 独立关闭，任何路径
  都不 signal 后台。原生取得未返回 owner 或 close 回执未知时保债，
  不重新取得或重复 close，不将这些状态报告为 cleanup 完成。

真实 Coding 生产入口回归已改用此公共 lease 完成首次与 fresh client
  认证、Mux create/list、父端启动 fd 关闭后重新连接；停止仍使用原
  显式 stop 协议。首轮连接/生产入口 15 passed（11.76 秒）。评审补测
  后 20 passed、1 failed（12.44 秒），失败是迟到回执测试误用合同中
  不存在的 timeout 码；改为既有 busy 后该专项 1 passed/18 deselected
  （0.89 秒）。补齐前节未保留终态的旧 local/discovery/execution
  回归：34 passed（1.97 秒）。集合交叠不累加。新模块 mypy、修改
  文件 Ruff 通过。

三视角提出的 native 无返回句柄、内部取消提前结算、迟到 ready 三项
  P2 已修复，局部复审通过；负测覆盖对应窗口，也覆盖 task/executor 发布失败、stop
  发生于认证期间和清理重试。此处不等于 Discover/EnsureStarted、
  首次 namespace 授权、异常恢复、受管 Mux mutation 权限或完整 lmux
  交付；亦不将 source 环境同进程 fresh client 视作 installed/SSH、
  Session/模型或真实首次使用性能证据。后续仍按完整目标继续接线。

清单复核同时补回前序已记录的源码接缝：inventory 与精确 source 集合
  对齐，并列出 layout/starter/connection 三个可选 AppHost 模块。两个
  架构文件初跑 18 passed、1 failed（15.11 秒），唯一失败为反向
  consumer 清单遗漏已经落地的 managed_catalog/local/process；显式
  补齐后原失败项 1 passed/10 deselected（15.12 秒），未改放宽依赖
  断言。依赖图生成核对、文档轻门禁与 diff whitespace 检查通过。
  已生成 change-aware 检查计划；全目标门禁与安装验收仍待交付前执行。

## 53. 公共只读名称发现与解析

新增可选 `ManagedDiscoveryV1`，借用同用户、同 namespace 且位于规范
  registry 根的原 owner，不创建第二套目录或后台 broker。独立纯函数
  `resolve_managed_registry_root` 给出 namespace 级路径，无需临时伪造
  workspace/service/instance；既有 service 路径仍使用同一布局。

resolve 与 list_muxes 在一次短只读事务中 JOIN 名称保留、服务键和实例，
  不逐条打开生命周期目录、连接记录或 native observer。列表最多 64
  条，按大小写敏感全局名字分页，不按客户端 cwd 或 Product 过滤。
  每页是独立快照，不承诺跨页枚举一致性。原绝对 deadline 贯穿读取；
  busy/closed/corrupt 仍是错误，不能降级成“空列表/服务不存在”。

不可变 `ManagedMuxObservationV1` 保留名称意图、供显示/选择的服务信息、
  operation correlation、精确 instance 与原 recorded phase/revision/
  stop/cleanly-stopped 事实；不导出 PID、argv、密钥或连接记录路径。
  reservation 没有 instance 时不制造 ready；COMMITTED 也不是服务
  正在运行或已完成 Mux 创建的证明。调用者仍须经公共 connection lease
  重新准入，发现引用不会自动重选。完整受管 Mux mutation 权限待接入。

原 journal 的严格 durable state 解码提取为同包纯函数，发现与写入
  owner 共用，保留 phase/位值/instance/native canonical JSON/UID
  等校验。journal 的读写仍受原生命周期 fence 约束；复用解码不转移
  owner 或 lifecycle authority。

新增回归覆盖任意 cwd、跨工作区/Product 分页、只读字节/mtime 不变、
  无 instance、provisional/abort/committed-stop 的不可变旧观察、非法
  状态、过期/closed、异用户/namespace/root 和缺失根不初始化。真实
  Coding 生产入口先 resolve 全局保留名再连接，并在关闭启动 fd 后
  重新解析到同一实例；测试资源在 setup 失败时也由原 owner 清理。
  发现/原 lifecycle/paths/生产入口联合回归 50 passed（12.33 秒），
  三源文件 mypy 与修改文件 Ruff 通过。仍不冒充 installed/SSH/Session
  或首次使用性能验收；自动启动/复用、初始化与异常恢复继续待接线。

三视角局部复审通过，无新增 P1/P2。按非阻断建议补测完整根/子项的
  bytes/mode/inode/mtime 只读快照、三事实齐全后的换代与 frozen 旧引用、
  真实 65 条记录的 64 条截断及下一页：3 passed/14 deselected（1.18
  秒）。换代用例是显式注入停止事实的纯状态测试，不是 native 重启
  清理证据。两个相关精确架构门禁 2 passed/17 deselected（15.43 秒）；
  依赖图生成核对、文档轻门禁和 diff whitespace 检查通过。

## 54. 已准入存储上的启动/复用协调

`ManagedServiceCoordinatorV1` 把原 starter、journal 与公共连接 lease
  接成一次显式操作。调用者先持有 coordinator；原 starter 生成唯一
  operation ID，同一对象重复等待沿用原任务与 deadline。它借用已准入
  存储，不选择 Product、不初始化 namespace、不执行 Mux mutation，
  也不承诺跨进程/跨历史代次的持久操作去重或异常恢复。

没有实例或已有完整 clean stop 事实时最多调用一次 starter.start。
  CAS 竞争、busy 或未知启动回执后只读取 journal；有原 process/native
  identity 时仅重试该原生出生登记，绝不再次 spawn。选定 instance 后
  不自动换代；stop/abort、实例丢失或被替换均拒绝。已存在 COMMITTED
  服务经公共 lease 认证后才能返回。连接尚未就绪时，仅对 not-found/
  refused/closed 或短暂 busy 重试只读连接；先完整关闭前一 lease，
  cleanup 失败保留它并终止替换，corrupt 等错误不当作启动中的缺失。

close 在首个 await 前同步 fence 原 starter，随后等待原操作/native
  回执，独立清理连接和父端启动资源，不停止已提交服务。取消公开
  waiter 不取消原操作；同 deadline 可重新等待同一 lease。借用者
  显式关闭 lease 后再 join 会报告关闭，不隐式重连或交付失效 lease。

首轮 coordinator/starter 23 passed（2.82 秒）；真实生产模块的两个
  并发调用收敛到同一个 child，关闭客户端后第三个 warm 操作复用，
  专项 1 passed/2 deselected（10.72 秒）。三视角局部实现评审通过，
  随后补确定性冷态屏障，保证两方首次都读到 None 再竞争，并直接
  断言实际 Popen 数为一；再注入前两次 birth registration busy，
  验证原 process 重试登记后收敛。另补取消 waiter 后原任务/lease/
  deadline 重 join、借用 lease 关闭拒绝、connection close 失败仍
  清理 starter 且保留原 lease。补测及原生产入口合计 16 passed
  （20.97 秒），集合交叠不累加；增量复审通过，无新增 P1/P2。

两源文件 mypy、修改文件 Ruff 通过。这些真实 source 环境测试使用
  预先准入的 registry/lifecycle 和 Session 根，不冒充默认目录初次
  安装验收；它们没有启动 Session、调用模型或验证 SSH。下一步完成
  namespace 首次初始化/重新打开与目录缺失的准入边界，再连接简短
  lmux CLI。异常恢复、完整 Harnesstui、配额、真实安装/首次使用性能
  和完整交付仍在原 goal 范围中，不据本节将目标标为完成。

## 55. Namespace 首次准入：设计增量与实施约束

三视角对首次准入方向评审后按下列约束收紧设计。本文仍是 partial
  implementation：本节记录准入合同，不宣称干净 home 已可自动启动。

### 55.1 独立持久见证与范围

AppHost 在现有 `<platform_home>/state/managed-deployments/<namespace-key>/`
  保存有界 namespace admission 记录与稳定锁；主体 registry、日志、
  tmp 仍留在既定 lmux 布局。路径由已冻结 namespace 推导，不重复读取
  环境；不是 Hosting 的进程机制责任，也不改变 Foundation 全局目录
  缺省。Discover/list 只读，不创建任何准入目录或记录。

新增 `state/managed-deployments` 整个见证域是受保护控制域，涵盖其他
  namespace 的兄弟记录。runtime/tmp 的实际部署路径、Session 根与
  持久附件/写者域均不得与其相等、互为祖先或后代；在 native 准入前
  拒绝重叠。不能只保护既有 lmux 子树而把新见证域留给普通数据写入。

记录分 initializing 与 initialized。initialized 仅代表存储初始化
  完成，不叫 service ready。记录绑定版本、namespace、初始化 operation
  ID、一次性 deployment nonce，以及 registry 根、数据库文件、稳定
  registry lock 的设备/inode 身份；不以随事务变化的大小/mtime 代替
  部署身份。数据库需要同 nonce 的持久绑定，未知旧格式不自动迁移。

后续 §56 将记录升级为 v2，同时绑定 admission root 和稳定 admission
  lock，共五个原生身份。marker 本身是允许原子更新的记录载体，不绑定
  自身 inode：同字节副本可在五个身份/nonce 全部一致时只读重开，不能
  据此改变 phase、授权不同部署或恢复丢失的锁。损坏 marker 的测试不
  冒充“所有 marker inode 替换均拒绝”的证据。

外部删除 lmux 子树时，独立准入见证应阻止重新创建。必须明确边界：
  **全部独立身份见证丢失**（例如同时删掉该 namespace 的 admission
  子树及 lmux 数据）后，纯文件算法无法区分首次使用与曾有活服务。
  不把这种证据灭失判为旧服务已死亡，不承诺自动灾难恢复；仅保留
  一个 state 父目录并不足以恢复被删掉的身份见证。此范围不同于
  正常关闭/重启、单独 runtime 丢失或有见证的 registry 丢失。

### 55.2 首次、重开与未知的准入矩阵

- 真正首次：可信组合边明确发起初始化意图；没有 admission 记录，
  也无既有 registry/lifecycle/部署残留。新 identity root、稳定锁和
  数据库必须排他创建，不能用现有接纳 EEXIST 的 create=True 冒充
  fresh。保留原 owner 的确切创建回执后才能继续。
- 缺 marker/lock/identity root，但仍有任一 lmux/registry/fence 证据：
  拒绝自动接管，报告初始化不完整/不可用，不重建锁，不删除残留。
- initializing：先完成意图文件及父目录 fsync，才允许创建 registry。
  发布回执丢失、mkdir 后尚未记录 inode、数据库完成但 initialized
  未发布，均保留原意图和 unknown。原 owner 仅按已有阶段/回执继续；
  其他进程需要显式恢复，不能靠目录为空或实例表为空取得创建权。
- initialized：在同一 admission lock 下读取记录，open-only 打开
  registry 并匹配完整身份/nonce，再交付原 retained registry owner。
  根、数据库或任一稳定锁丢失/替换均失败，不补建，不刷新记录领养。

准入容器须在第一次 native IO 前保留。复用原 private directory 的
  descriptor 链、非阻塞锁、CAS 写、fsync/close 债务；不把其一次性
  open 改成失败后重新构造/重复 open。并发 initializer 遇 busy 有界
  重读/等待；持久 initializing 不是可无限等待的“正在启动”。

### 55.3 每服务 fence 的首次事实

registry 需记录 service-control initialization 事实，独立于 instance
  是否存在。先在短 registry 事务中提交初始化意图并退出事务，再
  排他创建/同步 lifecycle root 与稳定 lock，最后短事务发布完整身份。
  此事实未 initialized 前不得 journal.prepare；曾有控制意图却缺失
  fence 时不重建。这样覆盖“fence 已创建、prepare 尚未发生就中断”
  的窗口，不能仅凭 instances 中没有行来重新授权。

固定顺序是 namespace admission lock → 短 registry transaction；
  不持 registry 事务等待 service fence。ready coordinator 只借用已
  准入 journal，不复制这套初始化权威。旧手工 profile 不自动接管。

### 55.4 必需验收

干净 home、两个真实进程竞争、初始化意图/registry/最终发布各阶段
  故障与进程退出；initialized 后 marker/锁/root/数据库分别丢失或
  替换；符号链接、权限、fsync/close 失败和原债务保留；只读全树
  不变；新服务第一次创建与旧 fence 丢失的区分。不得 chmod 用户
  既有目录、用残留删除代替恢复，或建议用户直接删目录来消除未知。

本设计按三视角提出的排他创建、残留矩阵、完整身份、服务初始化事实
  和锁顺序修订；不引入常驻 broker、全机 PID 扫描或另一套 Session。

### 55.5 本轮实施与验证边界

已实现有界、严格解码的 `ManagedNamespaceAdmissionRecordV1` 纯合同，
  初始化中不能声称拥有完整身份，初始化完成必须绑定三个不同的
  dev/inode 身份；路径推导无 IO。runtime/tmp 和两个 managed Coding
  Session 入口共同保护整个见证域（含其他 namespace），不扩展旧
  手工 G16 profile 的权限。

`PrivateManagedDirectory` 增加 opt-in `exclusive_create`：只对最终
  身份叶进行真实排他 mkdir，稳定锁使用 O_CREAT|O_EXCL；已有对象
  报 conflict，不接纳或删除。新建前登记父目录同步债务，成功同步
  后核对原身份；失败后 close 只结算原 fsync/descriptor，不重放创建。
  默认 `create=True` 仍保留原接纳已有对象语义，不能据此证明首次。

验证结果（有交叠，不累加）：

- admission record、路径隔离及两个 Coding 入口：89 passed（5.71 秒）。
- files/layout/registry/lifecycle：101 passed（5.74 秒）。
- 两个真实进程经同一 gate 竞争目录/锁，各只有一个成功；进程退出后
  新排他申请仍 conflict，普通打开仍可用。另补 fsync 中替换目录/锁
  的身份复核：4 passed（1.68 秒）。
- 架构 exact module/current inventory：2 passed，17 deselected
  （15.42 秒）；相关五源文件 mypy、Ruff、依赖图生成校验通过。
- 三视角局部复审通过；建议的真实竞争及同步后替换负测已补齐。

这只交付合同、路径隔离和排他创建机制：独立持久见证 owner、数据库
  deployment nonce/service-control 初始化事实及其真实首次接线仍待
  实施，未将本节测试当作干净 home、完整 CLI 或安装验收。

## 56. Namespace 持久首次准入与数据库部署绑定

本节推进 §55 尚未实施的 namespace storage owner；service-control
  初始化、默认 Session 准入及 lmux CLI 仍为后续任务，不据此声称用户
  已可一条命令启动完整服务。

`ManagedNamespaceAdmissionV1` 在 IO 前持有所有目录容器，显式
  `create_if_missing=True` 才可初始化。已有 witness 只读打开；没有
  witness 但当前 machine 的持久部署目录或当前 namespace runtime
  仍存在（包括空目录），拒绝创建新 witness。无残留时才排他创建
  admission root/lock，持久化 initializing，再排他创建 registry
  root/DB/lock，最后 CAS 发布 initialized。每个 owner 只尝试 open
  一次；失败后只清理原持有资源，不重放初始化、不删除持久残留。

v2 witness 绑定 admission root/lock、registry root/DB/lock 五个身份
  以及 deployment nonce；SQLite schema 4 持久存储同 nonce，旧 schema
  1/2/3 均不静默迁移。registry 后续每次事务也固定已打开的 DB/lock
  身份及 nonce，不能只在首次重开时比较一次。普通显式 registry 创建
  仍可生成自己的 nonce；这不授予 namespace 首次初始化权限，也不会
  自动激活旧手工 profile。

重新打开在原 admission lock 下匹配记录、全部原生身份和 DB nonce，
  完成后返回该 owner 保留的原 registry。初始化中、缺失、损坏或被
  替换的控制对象均不补建。同字节 marker 原子替换允许重开，但不会
  改变五个绑定身份、nonce 或状态。服务是否 ready 仍由原 coordinator
  和精确连接 lease 验证。

复审发现“新 admission.lock 已创建、首次 creator 尚未 flock”的
  窗口：无 marker 的重开者可能抢锁，使双方都失败。因此重开者先做
  只读 negative precheck，marker 不存在就拒绝，不争抢初始化锁；
  marker 存在后仍必须在锁内重新读取并执行全部身份检查，锁外读取
  不是准入凭证。真实双进程测试在双方均确认缺失之后、首次排他创建
  之前设 gate，要求恰好一个 admitted、一个 conflict；另以确定性
  回调验证上述创建锁尚未 flock 的窗口，重开者不能阻断原 creator。

记录发布与 schema 首次提交的父目录 fsync 失败现在保留原同步债务；
  close 只结算原 fd，registry close 失败也继续独立清理 admission
  目录，保留失败的原 registry 供重试。全部独立证据灭失的灾难恢复
  限制仍按 §55，不使用 PID 扫描或目录删除猜测旧服务死亡。

本轮验证（交叠集合不累加）：

- namespace/admission record/files/registry/lifecycle：160 passed
  （9.77 秒），覆盖干净 home 存储初始化、含根目录的只读快照、五个
  身份缺失/同字节替换、真实骤退、丢回执、关闭失败和同步债。
- 锁抢占 P2 修复后，namespace 加原生产入口：37 passed（27.78 秒），
  包括严格双进程首次竞争和真实 start/reuse 子进程兼容回归。
- 精确模块及 current inventory：2 passed，17 deselected（14.89 秒）；
  五源文件 mypy、Ruff、依赖图生成检查、docs-light 和 diff-check 通过。
- 三视角复审提出的 marker 合同/测试 P2 与首次锁抢占 P2 均已修复并
  经对应视角复核关闭；局部通过不替代 service-control、完整 CLI、
  Session 首次使用、安装/SSH/性能或最终交付验收。

下一步沿原 goal 接入 service-control 初始化事实：先持久意图再排他
  创建每服务 fence，匹配后才允许 journal.prepare；然后将已完成的
  namespace owner 接入自动启动组合，不能退回手工预建控制目录。

## 57. 每服务控制准入及真实启动组合

`ManagedServiceAdmissionV1` 借用已打开的原 NamespaceAdmission registry，
  保管本服务的路径探测、排他目录与原 journal，关闭不停止服务、不
  删除 fence，也不关闭借用的 namespace。它只尝试一次 open；失败
  不把“实例表为空”或“operation ID 相同”当作重新创建资格。

SQLite schema 5 在 identity 中持久绑定 `service_admission`，以及与
  instances 独立的 `service_controls` 有界记录。NamespaceAdmission
  创建和重开均显式要求该标志为 true，后续事务继续固定，不允许把
  managed namespace 降级为手工模式；旧显式手工入口新建为 false，
  不自动激活此路径。旧 managed schema 1/2/3/4 不静默迁移。

服务准入先检查原控制记录。缺记录却已有 fence 残留，或实例已存在，
  均拒绝补建。真正首次须在短事务中 CAS 提交 initializing 并获得
  本次插入成功回执，退出事务后才排他创建 lifecycle root/lock；
  然后在 fence 下用短事务发布 initialized 与两个 inode 身份。
  发布遇共享 registry 短暂 busy 时，在原绝对 deadline 内保留同一
  fence，重试精确的发布/观察；已落盘的相同 completed 记录可结算
  丢失回执，绝不重做目录创建或延长预算。

managed journal 在任何目录 IO 前拒绝 `create=True`。每个 open、
  read、prepare、register、commit、abort、stop 和 evidence 更新都
  经原 `_read` 接缝，在与读取/更新相同的事务中核对 initialized、
  service ID 及 fence 根/锁身份。open 先用短只读事务拒绝缺失或
  initializing 控制事实，释放事务后才获取 fence，锁内仍完整复核：
  这是防止读者在“锁已创建并同步、creator 尚未 flock”窗口抢锁，
  不是锁外授予准入，也不持 registry 事务等待 fence。

真实生产测试新增 admitted 组合：从缺失的 platform home 开始，通过
  NamespaceAdmission 和 ServiceAdmission 创建控制存储，再交给原
  Coordinator/Starter 启动真正的 Coding 子进程，验证竞争仅一个
  子进程、warm reuse、精确 stop；原 manual 组合继续保留。该测试
  仍显式准备 Session 根，不冒充 Session 首次创建、CLI、安装、SSH
  或性能验收。下一步是接好默认 Session 根准入和一条命令的组合。

本轮验证（交叠集合不累加）：

- schema/mode 增量下 namespace/record/registry/lifecycle：117 passed
  （7.90 秒）；随后 service/namespace/lifecycle/bootstrap：100 passed
  （8.31 秒）。
- service 自身最后一轮：37 passed（6.76 秒）。包含真正 intent 已提交、
  root 已创建、lock 已创建/fsync 且持锁、initialized 已提交四阶段
  `os._exit(23)`；前三级只读拒绝接管，最后一级只读重开；还包含
  namespace 可继续使用的独立清理、坏记录不改实例行、before-flock
  竞争以及提交前/后 busy 的原 fence 发布结算。
- 最终 service 加真实 Coding process：43 passed（65.47 秒），包含
  manual/admitted 两种组合各自的普通及 birth-busy 并发启动与复用。
  这里是正确性测试耗时，不作为 startup 性能结论。
- 精确模块与 current inventory：2 passed，17 deselected（16.57 秒）；
  六源文件 mypy、Ruff、依赖图生成检查、docs-light 与 diff-check 通过。
- 三视角复审均通过；managed 降级防护、全部 mutation 同事务校验、
  raw journal 抢新锁的 P2 已关闭，要求的真实进程与清理负测已补齐。

仍未完成默认 Session 根首次准入、简短 CLI、完整 Harnesstui 接线、
  有界日志/临时文件的最终组合及安装/SSH/首次使用性能验收；不据本节
  将原 goal 标记完成，也不发布未完成的整体实现。

## 58. 共享 Session 存储的惰性首次写入准入

三视角设计复核确定：Session 根由多个工作区、Product 和服务共享，
  不能从“新服务”推导“新 Session 库”。启动、空 Mux、浏览和预览不
  初始化 Session 库；真正的持久 new/fork/import 目标写入才允许首次
  准入，restore 不创建缺失库。机制归 Harness transcript，Coding
  选择默认根和独立 state 根，AppHost 不拥有 Session 初始化政策。

`TranscriptStoreAdmission` 使用 UID 与 canonical Session 根的摘要
  作为共享键；默认见证放在 `<platform_home>/state/session-stores/`
  下，不按工作区、machine 或服务分区。它复用原目录 writer 的
  native fd/同步债务与 RootedFileIO，没有新增 Session 数据库或运行
  时 owner。排他首次 witness/root 创建及 open-only 已有锁是原目录
  机制的可选参数；旧 writer 默认语义不变。runtime/tmp 不得进入
  platform home 的共享持久 `state` 域，Session/blob 写入域也不得
  与准入见证交叠。

- 真正首次：缺见证、缺根且没有附件/附件 writer 残留，先排他创建
  见证并同步稳定锁，再发布 initializing，随后排他创建 Session 根，
  最后发布 initialized 与 root/data-parent/witness/lock 四项身份。
- Legacy：由原 root owner 在发布 intent **前** 打开并保管正文根和
  data parent，之后只复核同一对象；不改原历史、图片、权限或 mtime。
- 已准入：只读打开原见证和锁，精确匹配身份。缺根、同路径替换、
  缺锁、坏记录或 initializing 都不是重新创建许可；不自动接管。
- 同一 catalog 已观察到存在或未知的根，单调观察事实传至原准入
  owner，在创建前再次禁止重新建库。独立持久证据全部灭失仍属于
  无法区分全新状态的灾难恢复边界，不能声称自动恢复已有库。

原 `TranscriptWriterPreparation` 在其 retained driver 内完成上述
  准入，关闭短 store lock 后，将 root/data-parent 身份约束交给原
  正文/附件 writer，正文 writer 在创建其锁命名空间前检查身份。
  不将结果降格为可复用的 `create_root=True`。原 preparation 继续
  保管失败准入、取消、同步/关闭债务；清理失败仅附注原准入异常，
  不覆盖主错。两个不同 Session 可同时存活，初始化锁不延伸到运行
  时构造或整个 Session 生命周期。

专用 `coding.managed_process` 已选择公共默认 state 根。生产测试从
  干净 home 启动真正的子进程，空 Mux/warm reconnect 均不建 Session
  根或见证；首个 Tab 才创建存储，detach/reattach 后保留原 Session。
  此测试不调用模型，不是完整 PTY、SSH 或性能验收。原显式 launch
  可不启用此可选接缝；普通 Embedded 入口尚未切换。

本轮已有证据（交叠集合不累加，后续新改动仍需针对性复核）：

- 原 expected-root/parent 接缝：83 passed；正文/附件共享父身份约束、
  替换、缺失及构造前形状验证通过。
- 新 store/factory/owned admission/catalog/launch 参数集合：118 passed
  （7.75 秒）；原 factory 实际图片写入和恢复、两个 Session 同时持有
  writer 的补充场景通过。
- store/owned admission：41 passed（2.65 秒），包括真实双进程均在
  排他创建前 gated 后恰一成功、四阶段真实 `os._exit(23)`、取消期间
  等待原 native driver，以及 legacy root/parent 替换负测。
- 原目录/附件 writer、namespace/path 隔离、factory 和真实生产入口
  集合：145 passed（41.04 秒）。旧直接连接测试修正了“端点已发布
  即短 journal fence 必须空闲”的假设：仅 busy 时结算原失败 lease，
  在同一 deadline 内重试冻结的同一 instance，不重启或重选服务。
- 三视角已关闭 legacy 身份绑定时机和主错被 cleanup 覆盖两项 P2；
  局部通过不替代完整 CLI、Embedded、安装和最终交付评审。
- 单调观察接线后的 store/原 preparation/factory/managed catalog/真实
  production 集合：85 passed（47.72 秒）；随后补充同 inode witness
  符号链接替换拒绝，store 与精确模块检查通过。新增源模块同步加入
  架构 inventory 的精确登记，不放宽原集合断言。
- 十一源文件 mypy、相关 Ruff、依赖图生成检查、docs-light 和
  diff-check 通过。

下一步仍须让只读浏览识别持久已知库的缺失/替换，而非展示空库，
  完成 Embedded 共用准入和短 CLI 接线，再推进完整 Harnesstui、
  有界日志/临时文件组合及真实安装、SSH 和首次使用性能验收。

## 59. 已知 Session 库的只读浏览与关闭结算

公共 `TranscriptStoreAdmission.inspect()` 与持久写入共用原身份检查，
  但未知见证分支直接返回 unknown，绝不创建根、锁或登记 legacy 库；
  即使构造时允许首次写入，inspect 也不能激活创建。存在的见证只开
  原锁和原根，缺失、替换、损坏或 initializing 返回不可用。
  `check()` 核对同一保管对象，权限/IO 错误不当作不存在。

Managed catalog 在原目录 revision 采样中调用只读检查，且核对采样
  与原 root/data-parent 身份；发现接口与路由列表都不把已知库丢失
  表示为完整空列表。目录和已知 binding 的观察事实在同一 catalog
  内单调保留；持久见证后来消失也不会抹掉这份内存证据。新进程的
  全部独立持久证据已灭失仍受 §58 的灾难恢复限制。

原 catalog 在 native IO 前保管 probe，最多八个活动浏览及八个
  probe；清理债务未结算时拒绝新增 probe。初始化锁只覆盖短目录
  采样，不覆盖完整目录遍历。close 先 fence，活动 worker 的句柄
  不由另一路提前释放；worker 结束后的清理债务继续由原 catalog
  重试。取消浏览仍等待原完成回执，不以取消 offload Future 冒充
  native 完成。旧 Hosted discovery 的 executor 提交新增 publication
  gate：提交未成功返回时，晚到 worker 不获准开始真实读取。

本轮验证（交叠集合不累加）：

- 七项 inspect 新回归先确认在实现前失败；实现后 store/managed
  discovery/原 managed catalog 集合 72 passed（6.45 秒）。
- publication gate 修复与 inspect 后 root/parent 替换负测、旧 Hosted
  discovery/owned catalog 回归：77 passed（15.03 秒）。
- 真实专用生产子进程两种 admitted 启动：2 passed（26.79 秒）；
  空 Mux 浏览不建库，首个 Tab 后可列出会话，测试根暂移走不被重建，
  恢复原根后可继续列出。补精确 `SESSION_UNAVAILABLE` 断言和八读
  上限后的本地 Hosted/managed/生产集合：35 passed（58.00 秒）。
- 三视角复审关闭 executor 已提交但丢回执的 P2；只读性、原 owner
  清理及检查后替换负测通过局部复核，不代表完整交付验收。
- 最终 store/managed discovery/原 catalog/完整生产入口集合：86 passed
  （53.81 秒），包含整份见证消失后的同 catalog 身份记忆；三源
  mypy、相关 Ruff、依赖图检查、docs-light 和 diff-check 通过。

本节完成 managed 浏览诊断，不切换普通 Embedded writer，也没有
  安装简短 CLI。下一步仍是 Embedded 共用准入、`lmux` 自动启动与
  attach 接线，再完成 Harnesstui、日志/临时文件及安装/SSH/性能验收。

## 60. 受管 Mux 创建语义与持久回执

简短命令不能将 registry 的名字 intent 直接接到旧 `create_mux`。
本节增加中性的 `ManagedMuxCreateV1` 与创建事实回执：请求包含
  service、当前 instance、operation、名字及有界 opaque authority；
  不包含 AppHost 类型。回执保存原提交 instance、operation、名字
  与准确 Mux ID，不声明该 Mux 仍存活或在线，authority 不持久化。

部署 consumer 注入 `ManagedMuxServiceBindingV1`，其纯 prepare
  工厂先交出原 admission owner，再进行 acquire。consumer 必须
  实际校验名字预留、实例及 stop fence，并在准入后让停止/换代
  等待该操作结算；一次 `validate()->bool` 不能满足合同。
  AppService 在原 state lock 内保管 admission 直到原提交结算；
  acquire/commit/close 的 Task 发布前均不可进入真实副作用。
  caller 取消仍 join 原任务，清理失败保留原 admission，禁止新
  操作，service close 重试原对象并继续其他 Session 清理。

受管记录使用明确的 continuity/v2，新增 service ID 与最多 4096
  个创建回执，仍受整份 1 MiB 上限。新增 Mux 与回执在原 continuity
  lease 的一个提交内落盘；后续 Tab 变更必须保留全部回执。旧 v1
  编码字节不变；无 managed binding 不恢复 v2，managed binding
  不自动接管 v1，service 不匹配在打开任何 Session 前拒绝。
  相同 operation/相同名字返回原回执；不同意图冲突；同名不同
  operation 不隐式 attach。查询旧回执也必须重新授权，重启后的
  请求需绑定新 instance，但不改写原回执的提交 instance。

回执不按 TTL/FIFO 淘汰。名字被逻辑关闭后的旧 create 回执仍保留，
  重放不能复活 Mux。容量满时拒绝新创建，旧回执仍可查；完整编码
  的容量预检发生在 commit IO 前，不因超限误 fence 整个服务。
  实际提交异常可能发生在 replace 之后，此时拒绝继续依据旧内存
  写入，报告 unknown；不将一次 load 可见误报成持久提交成功。
  后续恢复从持久记录读取准确回执，不重新生成身份。

AppClientScope 的可选 managed creation capability 复用原应用级
  accepted-work owner；delivery waiter 取消、client EOF 不取消
  已接纳创建。受管 profile 的 legacy create/close 在发布任务、
  改 controller 或分配身份前拒绝。旧手工 profile 保持原语义。

本节只完成 create 语义内核和 scoped capability；真实 consumer
  admission、管理 wire profile、registry result CAS、ManagedClose
  及简短 CLI 尚未接通，不激活生产 profile，不代表可安装交付。
  下一步将以上公共合同接到原 managed registry/lifecycle owner，
  验证真实 stop 与创建的并发，再接管理 wire 和简短命令。

本节验证（交叠集合不累加）：初始测试先确认缺少 managed contract；
  实现后 create/legacy continuity 集合 34 passed（1.12 秒）。补
  publication gate、字节预检、lost-commit 与严格格式后，相关
  runtime/scoped/continuity 集合 82 passed（1.73 秒）；再加入
  scoped EOF、4096 条历史、双 Tab 变更/恢复，86 passed（2.12 秒）。
  最后加入 32 live Mux 边界后，完整 AppService 与架构基线集合
  178 passed、仅源码清单漏登失败（4.56 秒）；补齐两个新增模块
  后单独原断言 1 passed（20.12 秒），不重复已通过 AppService。
  三视角复审通过 create 语义与 scoped capability；六源 mypy、
  相关 Ruff、docs-light、依赖图与 diff-check 通过。回归证明不含
  真实部署 admission、管理 wire、安装或 SSH 整体验收。

## 61. 部署 consumer 的受管创建授权与停止串行化

`ManagedMuxManagerV1` 借用已准入的原 registry/journal 和精确
  namespace/service/instance，不自行发现、启动或停止服务。签发
  前在原 service fence 与短事务中核对 COMMITTED、未 stop、真实
  名称预留及 operation；持久随机 opaque token 后才返回请求。
  相同实例/相同 operation 签发重试返回原 token，不因失回执旋转。
  token 只进私有 registry 与请求，不进入 discovery、repr 或日志。

SQLite schema 6 新增最多 4096 行 `mux_authorities`，每行绑定
  一个真实 reservation。当前授权 instance/token 可随明确的新
  实例换发，但首次签发的 origin instance 和已登记创建结果不变。
  新行走普通增长额度；已有许可换发和结果收口走控制预留，普通
  增长额度不足不应封死这些操作。旧 schema 不做静默迁移。

服务端 prepare 是纯工厂，原 admission acquire 后释放全局 DB
  事务，仅保留该 service 的原 lifecycle lock 到 AppService 本地
  commit 结算。因此其他工作目录/名称仍可办理 registry 操作；
  同服务 stop 若先持久生效则 create 拒绝，create 若先获准则 stop
  返回 busy，须在原请求预算内继续等待/重试，不能越过原提交。
  caller 取消不是释放锁的证明，仍须 join 原 commit。

admission 的 native 进入/退出在同一 event-loop OS 线程直接执行，
  绑定原 loop/thread，不通过两次 to_thread 移交 RLock，也不占住
  child 单 worker 等待释放。这些短同步 IO 的预算是协作式检查，
  不是可抢占执行或 UI 响应时限的承诺；未来 GUI 不应照搬到 UI loop。
  admission 不关闭借用的 journal/registry，未知 native close 仍是
  原文件 owner 的债务，不能重新调用耗尽的 context generator 假报
  已清理，也不能关闭后来复用同一数字的 fd。

中性 admission 新增 `check_creation(previous)`：AppService 在返回
  replay 或新提交前核对已知结果。本地历史与已登记结果冲突/缺失
  时零提交拒绝；即使父端尚未登记结果，旧 origin 的请求在新实例
  中没有历史也不能当作首次创建，因为此前副作用可能已经发生。
  这类未知仍占名字，需显式恢复流程，不通过换 token 获得重做权。

`record_created` 消费原精确认证连接返回的可信结果，核对当前
  permit 与原 operation/name/origin，首次结果写入后不可变；同值
  重试可查回，冲突拒绝。原创建 instance 可以与当前授权 instance
  不同。stop 后仍可收口同实例已完成结果，旧实例 permit 不能更新
  新代。跨 registry 与 AppService 不制造伪原子事务：intent/permit
  落盘、RPC、精确结果 CAS 是三个步骤，未知不释放名字。

本节实现真实 SQLite/flock consumer 并与 AppService 创建内核组合
  验证，但管理 wire、专用生产 bootstrap 的 binding 注入与简短
  CLI 尚未激活；ManagedClose、Embedded 默认接线、完整 Harnesstui
  和整体安装/SSH/性能验收仍待完成。

本节验证（交叠集合不累加）：新测试先确认 consumer 模块尚缺；
  首批真实 registry + 原 lifecycle/registry/AppService 受管集合
  80 passed（5.53 秒）。补独立进程 stop、取消保锁、已登记/未登记
  结果换代与失回执，相关子集 39 passed（5.71 秒）。复审修复后
  文件 owner/consumer/lifecycle/registry/AppService 集合 133 passed，
  两条新 close 注入测试因尚未捕获目标 fd 而失败（7.31 秒）；将
  注入点移至实际 flock 后的校验，再运行这两个参数、精确清单、
  namespace/service admission 与专用真实生产 child 入口，82 passed
  （66.00 秒）。三视角复审关闭历史丢失重做与未知 close 两项 P2；
  五源 mypy、相关 Ruff、docs-light、依赖图和 diff-check 通过。

## 62. 可选管理创建协议与原本地连接接线

新增封闭 `loushang.managed-mux/v1` create 请求/结果编码，单帧最多
  4 KiB，独立于旧应用 algebra 和 execution wire。只传递部署层已
  签发的有界 authority，不把连接认证成功当作创建许可；响应和
  repr 不包含 authority，transport 不签发 token，也不重试操作。

本地 profile 明确支持 managed 与 discovery/execution 的四种组合。
  原私有 connection record 只在显式启用时加入 capability，旧
  record/hello 字节不变；认证摘要覆盖完整 capability 选择。启用
  管理能力后，原 LocalPeer 只获取一个 scope，先保管再借用全部
  能力；任何已声明能力缺失或 getter 失败均关闭原 scope，无降级
  或第二工厂回退。旧手工 profile 不隐式进入受管模式。

三类请求共用原连接的单调请求编号、16 个普通和 4 个控制槽位、
  request Task 与关闭流程。受管 create 占普通槽位；协议版本与
  request ID 必须共同匹配，包含同为 AppFailure 的响应。接收端
  在删除 pending、释放槽位和交付前校验创建 operation/name，
  因而调用方取消等待也不能绕过检查；只保留两个有界意图值，
  不延长 authority 保留。历史回执可以来自原提交 instance，
  不将其强制改为当前实例。未协商协议、重复跨协议编号及受管
  profile 的 legacy create/close 在语义副作用前拒绝。

已接纳创建仍归原 AppService accepted-work owner 管理；客户端
  EOF 只结束交付，原提交结算后重连可用同一 operation 查询原
  回执。真实 registry permit 经认证本地 wire、AppService 原
  admission、continuity 提交和父端精确 result CAS 的组合已有
  回归，不再只用模拟许可验证 transport。

本节不激活生产 AppHost/Coding bootstrap binding 或短 CLI。
  ManagedClose、默认命令/目录、Embedded 接线、完整 Harnesstui、
  日志/tmp 总量上限与安装/SSH/性能整体验收仍需后续实现。最新
  用户已要求整体完成后提交、推送、PR、合并并同步本地 main 与
  harness lane；本节局部通过不是提前发布未完成分支的依据。

本节验证（交叠集合不累加）：初始 wire/兼容集合 48 passed，
  四个新增 profile 测试缺少显式 capability 注入，补齐后扩展
  集合 49 passed（1.58 秒）。评审所见取消后错回执用两参数
  负测复现，28 passed、2 failed（1.42 秒）；将意图校验移到
  receiver 后，全 AppServer、真实 consumer 与精确清单集合
  414 passed、10 skipped（22.72 秒），剩余 36 个旧握手组合
  同样缺少 managed capability 注入，另有一处 source inventory
  漏登。修正这些测试/清单并补原始帧服务端超额零 dispatch，
  相关集合 101 passed（16.55 秒）。三视角静态复审通过当前
  wire 范围；八源 mypy、相关 Ruff、docs-light、依赖图与
  diff-check 通过。未将这些本地测试当作真实安装或 SSH 验收。

## 63. 专用生产 child 的受管创建绑定

`ManagedChildBootstrapV1.managed_mux_binding` 只在原 open 成功且
  application bind 之前可用，借用原 registry/journal 生成并保留
  一个 manager。纯绑定不签发许可、不进行新的 native admission，
  也不把 provisional 当作 COMMITTED。换 application ID 拒绝；
  bind/关闭后不再提供新绑定。已有绑定的 acquire 仍核对原 journal
  的当前状态，依赖关闭后不能继续创建。

中性 AppHost application/continuity 请求显式携带管理 binding；
  AppService recovery 使用原绑定和 continuity/v2。AppHost 与
  Coding 的 continuity 请求在构造时匹配 application ID，早于
  store acquire；两层非 continuity 工厂在构造任何 Product、
  catalog、runtime 前拒绝管理 binding，不因错误入口关闭调用者
  的 Session catalog。Coding 还要求 managed Session selection，
  invocation 的 service/instance/application 身份在路径 IO 前匹配。

HostedLocalRuntime 仅在显式 mux_management 且 connection instance
  等于已准入应用 binding 的 instance 时发布能力。专用
  `loushang.coding.managed_process` 接入该绑定；旧手工 Coding local
  command 默认仍关闭。ManagedConnectionLease 从原精确认证连接
  借用 managed capability，不改变发现、重定向、启动或停止语义。

没有新增生命周期 owner：bootstrap 保管控制资源直到原 child
  application 清理结算。原 control 的 off-loop stop 与 AppService
  commit 共用 service fence，锁序仍为 service fence 后短 DB。
  确定性测试让提交持锁、control 到达原锁入口，再由同一 event loop
  释放提交并验证停止结算；不通过另一套 journal 绕开争用。

真实源码环境 child 覆盖管理能力发布、伪造 authority 零创建、
  合法许可创建、registry 精确 result CAS、原客户端退出、新精确
  连接重查同一回执以及 warm coordinator 复用同一实例。测试侧
  对明确 native busy 只在原 deadline 内重试同一个控制操作；
  不重发 RPC，不分配新 operation/instance。短命令的管理请求
  协调器尚待实现，不能据此声称命令层已经支持可靠重试。

本节接通专用生产入口，但尚无短 `lmux` CLI、ManagedClose 名字
  释放、默认机器路径、完整 Harnesstui 复用或安装/SSH/性能整体验收。
  完整目标保持不变；按当前 goal 边界不自动推送或合并。

本节验证（交叠集合不累加）：真实生产入口先用负测确认旧记录
  mux_management=False（1 failed，9.02 秒）。接线后生产、managed
  local 与 bootstrap 集合 53 passed（50.81 秒）。非 continuity
  入口的评审 P2 先负测复现（1 failed，5.71 秒），修复为前置
  拒绝；扩大生产/旧手工入口/AppHost application/continuity 集合
  110 passed（104.31 秒），一条测试将 provisional 错写为 prepared，
  另一条未处理已定义的短暂 native busy。修正断言后，纯绑定、
  同 journal 竞态与前置 application ID 校验 3 passed（7.55 秒）；
  固定预算重试同控制操作后，生产 child 集合 6 passed（47.05 秒）。
  架构基线、旧 Coding application 和精确连接集合 36 passed
  （38.31 秒）。三视角复审通过本轮接线；十二源 mypy、相关 Ruff、
  docs-light、依赖图及 diff-check 通过。源码环境验收不替代安装、
  SSH 断线与完整首次使用性能验收。

## 64. 创建操作的命令侧统一协调

`ManagedMuxCreateOperationV1` 借用已准入的原 registry/journal 和
  完整 reservation，拥有一个原 ManagedServiceCoordinator 和一个
  带 publication gate 的操作 Task。构造前置校验 namespace、
  service、registry/journal 借用关系；Mux operation ID 来自固定
  reservation，不混用服务启动 attempt ID。首次 run 必须提供有效
  绝对 deadline，非法值在 Task/存储/启动前拒绝；重复 run 只 join
  原任务和原期限，不重新分配身份或续预算。

流程为：预留完整名字意图、原 coordinator 启动/复用、匹配原认证
  连接的 application ID、签发许可、一次 managed create RPC、
  原 manager 登记结果。LocalAppClientConnection 的 application_id
  来自同一次认证且完成 hello 的 record，未 ready/已 close 不可
  借用；不为核对身份重新读取可变路径。ManagedConnectionLease
  原样借用该事实。应用 ID 不符在签发许可和 RPC 前拒绝。

控制 IO 复用本包 `_settled_native` 原生回执，只有明确 busy 可在
  原期限内重试同一个控制操作；registry.reserve_mux 增加可选
  deadline，原调用保持兼容。全程不持全局事务跨 await/RPC。
  创建 RPC 只发送一次，超时取消交付 waiter 而不取消服务已接纳
  工作；断连、丢回执、重 join 均不自动重发，不释放名字或停止服务。

收到合法回执后立即保留 `created`，随后才做 result CAS；`result`
  只有对账成功后才赋值。两者均为历史创建事实，不声明 Mux 仍
  开启或服务在线。对账前或提交后失回执仍保留已知 created，不能
  伪装成尚未执行并重新创建；原登记提交后 busy 只重试相同事实。

close 先 fence 新工作，允许已返回回执在原预算内完成对账，再
  join 原操作并关闭 coordinator 的本地资源。借用 connection 不
  转移所有权，关闭后不可再借；清理失败保留原 coordinator 重试，
  不关闭 registry/journal，不停止后台服务，也不释放未知名字。

真实生产 child 回归覆盖该操作完成冷启动创建、操作 owner 关闭
  后服务仍存活、第二名字暖复用同一 child 且不产生第二次启动。
  这是短 CLI 的可调用创建链路；默认 namespace/path、CLI 语法、
  ManagedClose/名字释放及安装/SSH/完整性能验收仍需后续工作，
  未将创建协调单项通过当作完整 lmux 交付。

本节验证（交叠集合不累加）：初始负测确认缺少协调模块；首批
  创建、原 coordinator 与 registry 集合 38 passed（3.90 秒）。
  扩展故障测试先复现必填 deadline=None 与错误 application ID
  两项 P2，11 passed、2 failed（2.35 秒）；前置必填期限校验与
  原认证身份匹配修复后，创建操作、真实 child 冷/暖启动两种
  storage profile 和 LocalAppServer 集合 52 passed（22.82 秒）。
  再补登记提交后丢回执、相同事实 busy 重查、Task 实际发布后
  抛错，连同精确连接与源码清单，37 passed（19.78 秒）。三视角
  复审关闭两项 P2；五源 mypy、相关 Ruff、docs-light、依赖图与
  diff-check 通过。真实进程测试使用当前源码环境，不作安装验收。

## 65. 默认机器命名空间与实例临时目录

AppHost 可选 `managed.defaults` 复用 Foundation 的平台路径选择，
  Hosting 只负责读取 Linux OS 已配置的机器身份并生成域隔离键。
  默认解析不创建部署目录或 Session；Path 规范化可能查询符号链接，
  不承诺零文件系统读取。默认模块不从 AppHost core facade 激活。

机器键使用固定版本域 `loushang.managed.machine/v1`；只接受可信
  `/etc/machine-id`，以 no-follow/nonblocking/cloexec 打开，验证
  root owner、目录/普通文件类型、不可 group/other 写及读取前后
  身份/元数据稳定，最多读取 34 字节。拒绝空、未初始化、全零及
  非法 ID，不使用 hostname、boot ID、随机值或其他路径回退。
  原始 ID 不出现在返回值、异常或目录中，机器键仅作查找隔离，
  不授予进程权限。克隆机器仍需 OS 管理者提供不同 machine-id。
  清理显式跟踪本次主异常，两个 fd 分别尝试一次；未知关闭结果
  不重试数字 fd，也不以调用者外层 except 异常掩盖本次关闭失败。

默认 durable 管理根仍为 `$LOUSHANG_HOME/lmux/machines/<key>/`，
  admission witness 仍在平台 state；Session 仍走 Coding 默认策略。
  runtime 优先 LOUSHANG_RUNTIME_DIR，其次 XDG_RUNTIME_DIR/loushang，
  Linux managed fallback 明确为 `/tmp/loushang-<uid>`，不跟随各
  SSH shell 的 TMPDIR/TEMP，也不触发 tempfile 首次可写目录探测。
  有效高优先级覆盖遮蔽低优先级值；只有实际参与选择的根才校验，
  相对根拒绝，防止跨 cwd 改变服务命名空间。

无显式 LOUSHANG_TMPDIR 时，暂存采用服务器实例 tmp 叶子。
  显式覆盖保留为 `<override>/lmux/<namespace>/<service>/<instance>`。
  冲突按派生的管理子树判断，而非整个共同祖先目录；显式 `/tmp`
  可与默认 runtime 共存，真正与 durable/runtime 子树重叠仍拒绝。
  starter 构造时先做纯路径校验，早于 durable prepare/native spawn。
  原 layout、invocation、bootstrap 传递同一冻结选择，不新增 owner。

无覆盖的 managed-child/v1 字节保持兼容（64 KiB）；显式覆盖使用
  闭合 v2，必须有字符串 temporaryRoot（96 KiB，以容纳第四个最大
  Unicode 路径），不容许 v1 偷加字段或 v2 缺字段降级。Coding
  request 和 child entry 都以 invocation 派生的最终实例叶子覆盖
  LOUSHANG_TMPDIR；不将可变 inherited 环境当作路径权威。Session
  catalog、附件和 writer 目录继续拒绝与显式管理 scratch 交叠。

本轮三视角复审修复关闭失败被外层异常掩盖、共同祖先目录误拒、
  未生效低优先级配置误拒三项 P2。真实生产 child 回归增加默认与
  显式 scratch，跨手工/准入两种存储 profile，验证首次创建布局、
  父操作关闭后服务存活及第二名字复用原 child。此处没有激活短
  CLI；完整 Harnesstui、ManagedClose、日志/tmp 实际有界写入及
  安装/SSH/首次使用性能验收仍未完成，不能据本节宣称整体交付。

本节验证（交叠集合不累加）：默认/机器键/消息负测 74 passed、
  1 failed（1.08 秒，缺少 scratch 字段）；接线后扩大真实 child、
  coordinator、创建与架构集合 180 passed、1 failed（135.07 秒，
  另一架构清单漏登记此前 managed 模块，已补齐）。评审故障负测
  1 passed、2 failed（0.97 秒）；修复后默认/身份/bootstrap/
  Coding Session 隔离/架构集合 158 passed（11.09 秒）。补最大
  Unicode v2 payload、读取中变化及双 close 失败后 61 passed
  （1.03 秒）。十源 mypy 与相关 Ruff、docs-light、依赖图和
  diff-check 通过；本机 native 默认解析无创建探测也通过。沙箱
  中 `/etc` owner 映射为 65534 的同探测被安全拒绝，未放宽策略。

## 66. 短 CLI 创建、发现与重连预览

新增 `lmux` console script，保留 `loushang-mux` 显式旧语法。
  `coding.cli.lmux` 只解析参数及做 stdin/stdout TTY 前置检查，
  help 不解析默认目录；之后延迟导入 Coding 命令组合。当前支持
  `new -s <name> [--workspace ...]`、`attach [-t <name>]`、
  `ls [--after <name>]` 和裸命令，不将尚未实现的命令放入帮助。

同步 namespace/service/journal 准入和交互选择发生在 Runner 前，
  先保留 owner 再 open。所有准入在固定期限内；选择器等待用户
  期间不持事务/服务 fence，选择后才建立连接操作预算。CLI 只做
  Product 选择和组合，公共目录、名称、启动/连接权威仍留在原
  AppHost owners，不复制 runtime。工作区规范化在首次创建前。

new 先预留完整名字意图，再准入所属 service；原创建操作只重查
  这个相同 reservation，不另分配操作 ID。成功按创建回执中的
  Mux ID attach。同名冲突不静默 attach，也不创建另一工作区服务。
  attach 只用公共 discovery 选定 service/instance，再打开原
  journal 和精确连接，核对已认证 application ID，不调用 service
  admission、不启动或重选实例。名称回收/ManagedClose 尚未激活，
  后续接入时仍须补完整 reservation→Mux ID 的历史结果绑定。

裸命令在没有任何登记名称时创建 main；pending/unavailable 名字
  也保留在全局选择器中，不过滤后误判为空。当前选择器为有界文本
  列表，可取消；跨页使用显式 attach -t。无目标 attach 的在线
  唯一目标自动选择尚未实现，不能把此预览当作全部 CLI 合同。
  ls 使用只读分页，Tab 数为 null、状态 unknown，并单列 recorded
  lifecycle facts；不以持久记录声称在线。工作区输出经 ASCII JSON
  转义，不将控制字符送入终端。目录/Session 没有隐式迁移。

收紧公共 namespace open 的 not_found 合同：只有独立 witness
  及原 registry-parent/runtime 两个探测均缺席，才作为空部署。
  初始化 witness 已存在后依赖丢失报 unavailable；残留或未知
  身份不回退为空。CLI 不通过私有 pathname/exists 猜此分类。
  read-only 查询不重建丢失 registry、DB、锁或 witness。

run 的 finally 先结算 shell 与原创建操作/连接，再关闭借用的
  journal/service/namespace。Runner 未进入协程便失败时，idle
  pending 回调仍先释放同步准入句柄；async 活跃时不释放其借用。
  未结算 owner 沿用 process-only 非零退出语义，不报成功或自动
  stop/replay；命令正常结束只 detach，后台进程仍由服务拥有。

当前仍暂用 HostedMuxShell，真实 child 回归替换终端 runner，仅
  验证服务/协议 attach，不作 PTY/完整界面验收。完整 Harnesstui、
  ManagedClose、start/stop/status/logs、有界实际日志/tmp、并发
  首次命令争用、安装/SSH/首次使用性能等仍是完整 goal 的必达项。
  没有据此预览提前提交、推送或合并。

本节验证（交叠集合不累加）：初始测试确认缺少短入口模块；新旧
  CLI 首批 15 passed（6.03 秒）。扩大验证暴露 pytest setup/call
  重建捕获流使 TTY 模拟失效，修正为调用时绑定，未放宽生产 TTY
  检查。三视角识别并复核关闭 ls 损坏状态误报空库 P2；同时补
  Runner 未进入协程便失败的原句柄结算。CLI、namespace admission
  及 G9/基线架构集合 76 passed（45.26 秒）。裸首次创建、显式
  创建及 DB/锁丢失扩大集合 40 passed、3 failed（45.22 秒）；
  三项为旧 A0/G16 门禁未登记已受审 managed seams，精确同步
  consumer/value imports 后 15 passed（18.55 秒）。记录值模块
  已审 capability 扩展的单文件预算从 180 到 200，整体 1100 与
  stdlib/无 ambient IO 约束不变，经架构复核确认。损坏路径测试
  比较根及子树 inode/mode/mtime/完整字节，不仅比较目录名字。
  三源 mypy、相关 Ruff、docs-light、依赖图及 diff-check 通过。

## 67. 精确实例的停止观察与显式重启（实现复审待完成）

Linux group observation 借用原 pidfd observer，在 leader 存活时核对
PID/PGID/SID，查询与 close 串行化；仅以原进程退出及原进程组
不存在的实际观察补写 native stop evidence。它不发送终止信号，
不以超时、权限错误或 socket 消失声称完成应用清理。应用清理事实
仍由子进程通过原 journal 报告，三个事实齐备才返回 stopped。

ManagedServiceStopOperation 借用原 journal，保留原实例、deadline
及已接纳操作；取消调用者等待不会撤回停止意图。短 CLI 新增显式
start -t NAME，以及 stop --server SERVICE_ID；非交互 stop 要求
--yes，交互模式先预览受影响 mux 再确认。此切片暂不提供 --all
或服务别名。attach 不隐式重启已停止服务，显式 start 可恢复原 mux。

本轮修正 CLI 回归插入位置与 names 类型注解，停止确认前输出明确
标记为 stop_preview。底层 group/process/stopper/lifecycle 集合
64 passed（6.23 秒）；CLI 集合 22 passed（40.07 秒），涵盖真实
子进程停止、显式新实例重启及原 mux 恢复。六源 mypy、相关 Ruff
和 diff-check 通过。这不替代本切片实现三视角复审，也不代表完整
Harnesstui、真实安装、SSH 或性能验收完成。完成全部目标后按用户
最新授权提交、push、PR、合并并同步本地 main 与 harness lane。

## 68. 停止复审修复与原预算内的清理回执

三视角 §67 实现复审发现并关闭两个 P2：停止操作在 worker 实际入场
与成功回执公开交付前都要复查原 deadline；交互确认不得把截断的
`yes     no` 误接受为 yes。新增负测先复现三个失败，修复后通过；
stopper 集合 11 passed。确认行必须完整换行，空行/EOF/否定/截断
均不构造 stopper。原 native 事实不因迟到交付被抹掉，也不重跑 stop。

扩大真实 CLI 回归发现一次清理三事实齐备但子进程退出 1。随后以真实
bootstrap/journal，分别在首次 request_child_stop/record_child_cleanup
注入一次 busy，确定性复现正常停止被提前记为失败的两个窗口。修复
为原 close deadline 内，对已结算但未确认的控制观察有界重查；不换
worker、不替换 pending job、不重跑成功的 Application.close。永久
失败测试使用显式短预算，先 join 原 close task，再授予下一次预算，
继续验证真正超时/应用失败非零与已完成应用清理不重复。

该修复通过生命周期局部复审；没有把清理后退出码 1 一概清零。后续
扩大集合仍观察到 CLI attach 的瞬时 busy，不能据此声称整条 CLI
稳定性已验收。实际 traceback/错误码仍需结合原调用阶段定位。

## 69. 共享 Markdown 与会话操作 binding 增量

将原 Coding 默认 transcript theme 原样提取至
`harnesstui.conversation.theme`，Embedded 保留原工厂别名与内容；
三个 Hosted CLI composition 显式注入同一主题工厂。shell/screen
接受可选 theme，继续使用原 ScreenConversationApp、TranscriptRegion
及终端 owner 提供的 capabilities；无环境探测、无 Product 回退。

新增实际渲染对照覆盖宽/窄屏、流式/完成态、Markdown 标题/强调/
代码/链接、切 Tab 草稿与 renderer 保持。另验证 OSC/CSI 控制序列
过滤且原 transcript 不变；自定义 hyperlink 主题在终端能力关闭时
确实不输出 OSC8。共享视图/终端集合 25 passed，安全/详情/编辑器
集合 13 passed，不能把这些 fake-terminal 证据当成 SSH 验收。

`mux.conversation_binding` 实现已有 ConversationActionHost，接受
ConversationTextAction，借 AppClient 而不创建新 task owner。submit、
steer、follow-up、interrupt 均通过原 ShellActions；interrupt 仍用
control 保留槽。每 window 仅持有最新投递展示与本地 request ID，
结果和失败均核对 attachment/generation/member/session/request ID；
refresh 不搬移旧请求状态。中性 Screen state/frame 独立显示 running
与 pending/acknowledged/unknown；Ack 不冒充运行完成，idle 不清除
unknown，不自动重发。关闭后回执不再修改视图。

复审修复了输入验证被推迟至后台导致纯空白 prompt 清空/永久 pending，
以及 interrupt 遗留全局失败回调两项 P2：现在提交 task 前同步验证，
拒绝保持草稿，成功保管后才发布 pending；中断与文本统一隔离。
对应七个负例先失败，修复后纳入扩大回归；三视角局部复审均通过。
任务容量拒绝、附件前置拒绝、unknown 不重发等增量集合 23 passed。

独立评审确认 binding ≤150 行、中性 request presentation 与 theme
各 ≤60 行；新文件进入精确 inventory 及同一禁 native/Product 导入
扫描，原 shell 四文件 ≤950、原语义 controller ≤600 不变。
旧 G11 门禁另补齐 §60–63 已审的六个 managed 消费者。原 AppService
四个 core 文件继续全部计数；§60 ManagedCreate 净增 170 行后限额
由 1500 调整为 1700，managed_mux.py 单独进入 ≤80 行预算组。经
架构复核确认它们仍协调原 state lock/continuity 权威，不为压行数
拆出新的 owner；原 Product/process 禁依赖扫描保持。
这完成共享展示/操作端口接线的增量，不等于全部 M3：能力矩阵、审批
展示整合、ManagedClose/名称回收、Session 缺省全入口接入及真实安装/
SSH/首次使用性能、有界实际日志/tmp 仍待完成。

下一稳定性切口：不要通过重跑整个 CLI、namespace.open 或连接 prepare
掩盖瞬时 flock 竞争。锁等待必须显式选择，只允许同步准入或原 native
worker；不能仅因提供 deadline 就让所有 flock 同步等待。已有 Mux
admission 会在事件循环线程跨 await 持 service fence；同 loop 等待
会堵住释放者。此约束已做两视角设计核对，等待实现与跨进程/超时/
替换锁路径/事件循环 fail-fast 负例；尚未修改底层 flock 默认语义。

本轮末端复验：G11/G16 架构、全部请求隔离及 lifetime 集合
43 passed（35.59 秒）；前一轮 child/G11/G16 集合 37 passed、2 个
旧 G11 清单/预算失败，已按上述精确同步修复。相关 Ruff、mypy
与 diff-check 通过。真实 CLI 扩大集合曾出现 attach 的 lmux_busy／
local_operation_failed，因此未宣告完整稳定性通过，未提交/发布此
未完成目标；保留测试侧原异常以继续定位，不放宽成功退出断言。

## 70. 同步准入显式等待与事件循环 fail-fast

沿 §69 约束增加显式 `wait_for_lock`，默认 False；deadline 本身仍不
启用等待。只有短 CLI 的同步准入/发现/预留及连接原 native worker
显式选择等待。数据库与 journal 透传原预算，fresh namespace/service
创建保持原单次准入与失败关闭合同；不重跑整个 CLI、open、prepare、
业务事务或 RPC。竞争期间保留原 fd，逐次核对原命名身份；替换路径、
预算耗尽或无效记录均拒绝，不重新打开锁也不取得 unlink 权利。

复审另发现同一目录 owner 的 worker 持有本地 RLock 等待 flock 时，
loop 的默认调用仍可能在进入 flock 前阻塞。新增有/无 deadline 两个
负例先失败，再将 `_operation` 在运行中的事件循环上改为非阻塞获取；
worker 保留原期限和同一把锁。没有将跨 await 的 admission RLock 转交
其他线程。显式等待在 loop 上即使锁空闲也前置拒绝；非法/缺失 deadline
同样在打开 fd 前拒绝。

覆盖真实跨进程竞争释放、同 fd 保持、超时、路径替换、异 owner 与同
owner 事件循环竞争，并同步原服务崩溃注入 seam 的新增关键字参数。
扩大 files/connection/namespace/service/discovery/CLI 集合最终
194 passed（63.79 秒），包括原真实子进程启停、重启与跨 cwd attach。
先前扩大集合 180 passed、7 failed：两个运行进程载入修正前的 mutex
入口，五个旧崩溃注入 seam 不接受新增关键字，均已修复后复验。
三视角局部复审通过，九源 mypy 与相关 Ruff 通过。此证据关闭本次锁
竞争切口，不等于并发首次初始化、真实安装/PTY/SSH 或完整目标验收。

追加真实 lifecycle flock 等待期间取消连接的回归：调用者取消后仍保留
原 prepare/native worker，close 等待原回执，不提前关闭借用 journal，
不创建连接或重发准备。connection/lock-wait 集合 33 passed（3.95 秒）；
文档轻门禁及 diff-check 通过。

后续仍按完整目标推进 ManagedClose/名称回收、Session 缺省全入口、
完整会话能力绑定、有界实际日志/tmp 与安装/首次使用性能验证。完成
全部实现和最终复审后，按用户授权提交、push、PR、合并、同步本地；
不提前发布当前未完成目标。

## 71. ManagedClose：实现前的关闭与名称回收合同

Target，三视角设计复核通过；纯值/schema 已实现，运行能力尚未激活，
不代表当前 CLI 已提供 close。

关闭沿已有 AppHost 准入、AppService state lock/continuity 与原 Session
owner 收口，不新建平行 Mux runtime。新增独立可选关闭合同；旧 creation
协议和 legacy close 语义不扩权。请求绑定当前 service/instance、独立 close
operation ID、原 creation operation ID、精确 mux ID 与 name；AppHost
发放单独用途的关闭 authority，不接受创建 token 充当关闭许可。确认预览
冻结这组身份，不在确认之后按名字重新选择。Session 历史不删除。

AppService 在准入 fence 下先耐久提交 cleanup_pending 与原成员身份，
再撤销 attachment 和新增操作入口。原 Session owner 清理实际结算后，
才将同一关闭记录变为 closed，并从待关闭持久成员集合移除该 Mux。
关闭记录的原 committing instance、close/create operation、name、mux ID
不可变；cleanup_pending → closed 是唯一状态进展。请求返回超时/取消、
连接 EOF、停止服务或进程消失，都不自行生成 closed 事实。

持久记录必须区分活动与待关闭 Mux：cleanup_pending 仍保留准确的成员
恢复描述，closed 必须无对应持久 Mux；一个 creation/mux 只能有一个关闭
操作。已有历史 creation receipt 不删除、不重写为新 mux。新版本 continuity
闭集校验这组关系，保持旧 v1/v2 编码不变；旧消费者不得把新关闭状态当作
普通可恢复 Mux。恢复时 pending 不能重新出现在 list/attach/Tab；由原
AppHost 新实例准入提供旧实例清理/退出屏障，再沿既有 Session 恢复与关闭
端口结算残余，未证明屏障或结算失败则保持不可服务/cleanup_pending。

清理期间不持全局 registry 事务等待 RPC 或 Session.close。AppService
保持已接纳关闭与原成员 owner，调用者取消只取消等待；失败重试只处理
原未结算 owner，不重新关闭已完成成员。并发重复关闭按同一 operation
对账，另一个 operation 不接管原债务。服务停止必须 join 已接纳关闭，
成功关闭一个 Mux 不停止服务。

锁与任务结算分界：durable pending 后在原 state/mux lock 内同步摘除
可服务索引、登记原清理 owner；退出这两把锁及准入物理 fence 后，才
join Session.close。stop 也必须在 state lock 外 join 已接纳关闭，避免
阻塞其最终提交。stop 赢得准入 fence 后拒绝新 close，但已耐久接纳的
同实例关闭允许在 stop_requested 下提交结算；此结算重新取得原实例
fence，不能要求服务仍 accepting，更不能允许跨实例替换写入。

AppHost 只消费原认证连接上匹配全部身份的 closed 结果，在当前实例
fence 下 CAS 记录关闭事实并释放原名称引用；迟到旧 epoch 回复不得写入
新实例，迟到旧 operation 不得影响同名新 mux。索引写失败/丢回复保留
unknown 与原名称，通过只读关闭结果查询对账，不盲重发 close。历史关闭
记录有界且先预留容量，容量不足在关闭副作用前拒绝，不自动删除未知债务。

名称引用与历史意图分开：当前 muxes.name 主键和 authority 外键不能直接
删行冒充释放。后续 registry schema 必须保留不可重建的 creation/close
历史，仅 CAS 释放 active-name 引用；同名新建使用全新 creation operation。
关闭结果的 committing instance 是原历史事实，查询的 serving instance
是当前连接身份，二者不得混为一谈。新实例的认证查询可交付原 closed
事实，当前 fence 下对账原 name/create/mux/close 引用；旧连接迟到回复
仍拒绝。两次持久提交的未知结果均保留原 owner/名称，不退回 active。

本阶段恢复屏障只认现有 cleanly_stopped 三事实齐备的旧实例。异常退出
但缺应用清理或 native scope 证据时仍 unavailable，不借“恢复”伪造清理
完成，也不在本关闭功能内引入新的强制杀进程或异常接管权限。

实施顺序：闭集值与版本化持久校验 → 原 AppService 关闭/恢复收口 →
AppHost 用途隔离的许可与 CAS 名称释放 → 可选 wire/客户端/CLI 接线。
每步仅在对应能力完整后激活，不让半实现 close 绕过 legacy 禁止路径。
首个 schema 切片同步收紧 recovery 的版本白名单：无 managed binding
仅接纳 exact v1，当前仅支持 creation 的 binding 仅接纳 exact v2；新增
v3 在任何 Session resolver 构造前拒绝，直到关闭恢复能力显式接入。
验收覆盖有/无成员、活动 turn/审批、并发 close/stop、断线、取消、清理失败
与重试、两次写盘的未知回执、进程恢复、同名 ABA、真实 CLI 确认与历史保留。

CLI 继续遵守[原草案 §4](../drafts/lmux-managed-service-design.md#4-用户命令合同target非当前命令帮助)：
非 TTY 必须 --yes，交互确认必须完整行；离线 close 不启动服务。

本轮实现：新增独立 ManagedMuxClose 请求/phase/state 值，authority 不进入
repr 或持久记录；精确 close/create/mux 身份与两个 phase 严格验证。
continuity v3 纳入有界关闭历史，交叉核对 creation/name/mux 与 pending/
closed 的持久 Mux 关系；v1/v2 字节不变。恢复当前只准入 exact v1/v2，
在 resolver 前拒绝未激活的 v3，防止待关闭成员被旧算法重新开启。
摘要数值仍是保留状态计数（含清理债务），不冒充在线 Mux 数。

三视角设计修复补齐锁外 join、stop 后同代结算、origin/serving 分离、
active-name/历史意图分离与严格恢复白名单。纯值/schema 实现复审通过；
测试复审另补双合法目标的独立 close-operation 重复/跨 creation 别名
负测，避免重复目标提前拒绝而掩盖真正的 operation 唯一性规则。

架构复核接受 continuity 精确组 1250 → 1300（本次净增 59 行，当前
1258 行），仍在原模块校验 schema 与恢复合同，不另拆 owner；新 close
纯值 69 行进入独立 ≤80 行预算和原依赖扫描。原 core/protocol 预算
保持，三个旧精确源清单同步新增文件，无新 CLI 或 runtime 激活。

验证：原 creation/continuity/recovery 基线 51 passed；新增合同在实现前
34 failed（缺少新模块/字段），实现后扩大集合 92 passed，仅旧 continuity
预算 1 failed，按上述独立复核同步。补齐唯一性/容量负例后的功能集合
88 passed（1.96 秒）。真实 JsonFile store 的 pending、closed 分别写入/
释放 lease/重开保留完全相同身份；包含该测试及架构集合 38 passed、
2 个旧清单失败。补齐 close 值文档行和 §67 已审 stopper 遗漏后，两项
清单复验 2 passed（25.60 秒）。Ruff、三源 mypy、依赖图检查、文档轻
门禁及 diff-check 通过。此处没有调用实际 close，也没有验证其清理/名称
释放；下一步继续原 AppService 接纳、两次提交及原成员 owner 的运行接线。

## 72. 原 AppService 的关闭运行接线（仍未接入 Host/wire/CLI）

新增 default-None 的 managed closing binding；纯端口分别表示 ADMIT、
OBSERVE、SETTLE，不沿用创建 token。它由消费者提供原 acquire/check/
close admission，AppService 不负责发放授权。当前生产 AppHost 未提供
该 binding，旧入口仍不具有管理关闭能力，v3 恢复仍按 §71 拒绝。

运行逻辑留在原 AppService：在 state/mux lock 与原 admission 下提交
pending，同步隐藏 Mux/撤销 attachments，记录原成员引用和不可变 pending
snapshot；完整释放 admission 后才启动并保管 cleanup task。所有后续
continuity 提交均合入 pending snapshots，部分成员清理完成也不提前
释放其 Session ID 占用。原 SessionOwner 结算后，在 SETTLE 阶段提交
closed 并移除 pending snapshot；同 operation 的多个等待者加入原任务。
查询只鉴权读取已有记录，不开始清理或写入，不以无 Mux 推断 closed。

关闭服务先同步 fence execution/discovery/scopes 及新的 AppService
请求，再锁外 join 原关闭任务；预算耗尽不取消原任务，失败后显式收口
只重试未结算的原成员。已成功的 port.close 不重复执行。任一次持久写
回执未知都保持原 owner 和 unavailable/cleanup debt，不以成员已清理
推断 closed，也不由 service.close 宣称完整成功。没有引入强制回收。

三视角实现复审修复三项 P2：ADMIT 成功释放阶段的取消要延迟到原清理
任务发布后传播；部分清理成功的 Session 仍由 pending snapshot 占用；
已借出的发现/执行/scope 能力须在首个 drain await 前被同步撤销。三个
负例先确定性失败，再修复通过。真正的 admission 释放失败仍保留原
admission，禁止启动清理；不是把取消和释放失败混为一谈。

测试复审另纠正 stop 拒绝用例：原测试对已 pending 目标换 operation
会先触发冲突，不能证明 shutdown 拒绝。现预建另一合法目标，并在明确
shutdown 屏障后验证拒绝且无新增 commit/closure。双目标并发、同 intent
双等待者验证原 task 恒等，各成员只关一次；第一个目标 closed 时另一
目标的 pending record 与完整成员 snapshot 仍保持原值。

架构复核允许原 core 精确四文件预算 1700 → 1900（当前 1876 行），
两个 AppService managed 合同文件合计 103 行进入同组 ≤120；不拆平行
runtime、不隐藏新增文件。旧 protocol/continuity 与其他组预算保持。
这一增量尚不包含 v3 pending 恢复、AppHost 关闭许可与名称 CAS、管理
wire/client scope 接线或 CLI；完整目标继续，不以运行单测替代真实安装。

验证：新增端口后的旧创建/恢复基线 63 passed；四个运行负例先因缺失
close/read 方法失败，实现后相关集合 67 passed。两阶段丢回执、任务
工厂拒绝、提交中取消与目标鉴权集合 13 passed。复审三项精确负例先
3 failed（取消后清理未继续、Session 重开落到 ValueError、借出 discovery
未被 fence），修复后扩大集合 94 passed。补 admission 释放失败保持原
owner、完整并发 snapshot 后，AppService 全套、AppHost 原创建许可/
操作与架构集合 259 passed（80.72 秒）；Ruff、四源 mypy、依赖图检查、
文档轻门禁与 diff-check 通过。三视角局部复审已通过，没有据此宣布完整
ManagedClose 或整个 lmux goal 交付完成。

## 73. 原 RecoveryAttempt 的关闭恢复（可选接线，Host 未激活）

v3 恢复另需消费者显式提供 recovery admission factory；仅有 live-close
binding 仍拒绝 v3。许可分 ADMIT / SETTLE，输入是完整冻结 continuity
record，不伪造客户端关闭请求或 token。消费者必须在原实例 fence 内核对
当前启动实例及前代 cleanly_stopped 三事实；SETTLE 只允许同代已接纳恢复
结算，允许 stop_requested，但不允许跨实例。AppService 不判定 PID 存活。

沿用原 RecoveryAttempt、continuity lease 和 SessionOwner，不另设恢复
runtime。在任何 resolver 调用前完成 ADMIT 并完整释放原许可；只对 pending
Mux 的原成员恢复清理 owner，锁外结算。已结算成员留在本次 attempt 的
身份表，后续失败重试不重开、不重复关闭。原 admission 释放失败时保留
同一 owner，先解决释放再进入 Session 清理；调用者取消仍 join 原 open task。

全部 pending 成员清理完成后，重新取得 SETTLE 短许可，在原 lease 上单次
CAS 把 pending 历史改为 closed、删除相应 Mux snapshot，保留 active Mux
及不可变 origin/create/close 身份。持久提交成功并释放许可后才恢复 active
Sessions、发布服务；所以 pending 从不成为可见 Tab。closed-only 记录不
重写、不恢复历史成员，但仍需要消费者恢复许可。v2 原接线保持不变。

attempt 保留冻结原记录、原成员 owner、未释放 admission 与已确认提交
结果；重试必须匹配同一记录，不能悄悄改用新目标。提交回执未知则锁存
unavailable/cleanup debt，即使重新 load 看见 closed 字节也不能据此宣称
提交已确认。close 必须报告该债务；不关闭调用方借出的 continuity lease。

计划验证：旧消费者先拒绝、ADMIT 屏障前零 resolver、失败释放不启动清理、
部分失败只重试原 owner、SETTLE 前零 active Session、两阶段代际变化、
取消/超时仍保管原工作、未知提交不可转成功、真实文件 lease 重开、恢复
后查询保留 origin instance。生产 Host 尚未提供此许可，本节不宣称已激活。

实施沿上述边界完成。v3 必须同时具备 live-close 和 recovery binding；
收养入口拒绝残余 pending 并保留完整关闭历史，后续普通 mutation 不得
降级或丢失历史。原冻结记录与已确认 CAS 结果分开保存：CAS 确认后的
许可释放/active 恢复失败可沿同结果重试，回执未知则永不通过 reload
转成功。已成功的 pending 成员只保留原 owner，不重开、不重复关闭。

三视角设计/实现复审同时修复原 Attempt 两个 P2：open/close 等待者
同时取消时，已恢复成功的服务未被收养；以及关闭完成后的迟到 open
交付重新挂回已关闭对象。两个确定性负例均先失败。现在成功结果只由
原 _open_once 返回前收养，公开 waiter 不重复收养；open/close 复用原
publication gate，close 单任务串行清理，取消只影响等待者，不丢实际
任务或借用 lease。任务工厂 schedule 后抛错时无许可、resolver 或写盘。

测试覆盖非空 closed-only、ADMIT/SETTLE 释放门闩、两阶段取消与双等待者、
原成员部分清理失败、确认 CAS 后的释放失败和 active 恢复失败、未知
写回执、冻结记录替换、origin/serving 分离及后续 mutation 历史保留。
真实文件 lease 用三个不同 owner_epoch 重新获取，第一次恢复结算 pending，
再次恢复只开 active，closed-only 的文件 bytes/mtime 不变。

架构复核接受原 continuity 精确组预算 1300 → 1400（当前 1378 行），
两个 managed 合同 120 → 150（当前 134 行）；不新增 runtime、不隐藏
源文件，core 仍保持 1900。旧创建/关闭/恢复基线 59 passed；新增恢复
七项在实现前因缺合同失败，接线后相关集合 68 passed。扩展测试曾发现
一项测试 fixture 的 position 字段误写，已纠正，不计作产品缺陷。
扩大 AppService 全套、AppHost 管理创建/许可与架构集合 277 passed
（64.58 秒）；最后移除 close 的重复结果收养后，恢复集合复验 30 passed
（0.81 秒）。三视角局部复审通过；Ruff、三源 mypy、依赖图、文档轻门禁
及 diff-check 通过。

后续仍须实现生产 AppHost 的恢复/关闭许可与 active-name CAS、wire/
CLI 管理关闭，并继续完整 lmux 目标；本节不是生产恢复或最终交付声明。

## 74. AppHost 名称引用与管理关闭（设计及实施中）

原 registry 的 muxes 保持当前名称引用（name 主键），新增 mux_intents
保存不可变 name/service/creation operation，operation 主键。reserve_mux
在同一原 SQLite 事务内同时登记历史意图与 active 引用；重试原 active
intent 幂等，已释放的历史 intent 不能重新激活，同名新建必须全新 operation。
creation authority 外键改指历史意图；active 引用用复合外键保证其 name/
service/operation 和历史一致。只删除 active 引用，不删历史、Session 或
authority。历史仍受 4096 条和原数据库字节水位约束，不隐式 GC。

仅在管理关闭结果核对成功后由原 manager 执行 active-name CAS；registry
不增加一个任意按名删除的公开捷径。关闭许可与创建许可独立，close
operation 不得复用任何 creation operation；一个 creation 只接纳一个
close intent。issuer、只读结果查询和 trusted-result 结算均绑定精确服务/
当前实例，消费原 lifecycle fence 和短 registry 事务。RPC 仍在事务之外。
pending/未知结果保留名称；closed 才能释放精确旧引用，已释放后的重放不能
删除同名新引用。origin instance 是历史事实，serving instance 是当前鉴权。

本轮先落原数据库/registry 的历史分离基础，再接用途隔离的 close permit、
原 AppService admission 与结果 CAS；生产 closing binding 必须等恢复许可
同时具备后激活。恢复还需保留 journal.prepare 已验证的前代清理证据，
不能只看到新 PROVISIONAL 行就宣称前代清理完成；其证据传递单独复核。

格式采用新的严格 schema 7；这是尚未交付的 managed 原型格式，不自动
迁移、覆盖或清理 schema 6。遇到旧或不完整格式仍 bounded invalid_record，
旧 CLI 入口不改。测试包括 atomic reserve、历史 operation 不复活、同名
新 intent、复合外键、历史容量、回滚/重开与创建许可旧回归。

名称历史基础已落地：仍只有原数据库和 registry owner，发现/resolve/list
只读 active 表，无当前目录过滤变化。六个精确负例在实现前失败；修复后
registry、创建许可、发现与创建协调 83 passed（9.16 秒）。新增双写异常
分别在 history/active 插入成功后抛错，断言 service/history/active 全回滚；
真实子进程分别在这两个窗口退出，显式 writable reopen 后检查三表原计数。
原 hot-journal 测试仍证明未提交页实际落盘后恢复完整历史与 active 引用。
测试中的删 active 只是存储夹具，不是管理关闭或公开名称释放能力。
包含最新骤退用例、生命周期/namespace/service admission 与架构的扩大
集合 150 passed（52.43 秒）；Ruff、两源 mypy 与 diff-check 通过。

三视角局部实现复审通过；历史容量按 mux_intents 计数，满额的原 active
重试仍幂等、已释放历史不释放容量。后续同一 manager 的可信 closed 记录
与精确 active 删除必须在同一事务中，不得因这次历史分离而跳过鉴权。

恢复设计复核要求：原 journal.prepare 在同一 lifecycle fence/SQLite 事务
内保存“旧完整 cleanly_stopped 证据 → 新 instance/attempt”的本代不可变
换代凭证，再写新 PROVISIONAL；不需要平行 owner 或无限历史。首代不能
用空前代凭证恢复已有 managed continuity。生产恢复 ADMIT 必须绑定原
bootstrap 捕获的 self-native/attempt、未停止的 PROVISIONAL 及换代凭证，
不能复用只允许 COMMITTED 的 live 管理检查（application.prepare 先于
handoff commit）。SETTLE 重查同代已接纳恢复，允许 stop/abort 时结算，
但不能重新授予新的工作权限或把历史 origin 强行等同于直接前代。

## 75. 原 Manager 的关闭许可和可信结果 CAS（显式本地接线）

原 registry schema 8 新增有界 mux_close_authorities：一个 creation intent
只对应一个 close operation，保存当前授权实例、不可变 origin 实例、私有
token 和 nullable pending/closed 结果。close operation 与全部 creation
operation 双向排他，reserve/issue_close 都在原 SQLite 事务检查，防止
创建重用先前关闭 operation。关闭许可不接受创建 token。

issue_close 只针对已确认 creation receipt 的历史目标；首次签发要求原
active 引用仍存在。重试保留原 operation/origin，跨实例只更新当前 token。
ADMIT 拒绝停止和跨代未知意图的新接纳；OBSERVE 可读已有结果或 None，
不补写/不启动清理；SETTLE 只允许同实例已接纳 pending 的结算，包括
stop_requested 后。该接纳证据来自原 AppService 传入的精确 durable
pending，而不是 registry 的 phase：正常首次关闭时父端尚未收到结果，
registry phase 可以仍为 NULL；token 或 NULL 本身均不构成接纳证据，
也不增加第三次跨库写入。原 Manager 借用同一 lifecycle fence，公共的短许可
实现复用一个内部 fence 基类，不复制、搬移或重建 native lock owner。

record_close 只消费当前精确认证连接的可信 AppService 结果，核对完整
close/create/name/mux/origin 后，在同一事务保存 CLOSED 并 CAS 删除精确
active 引用；pending 保留引用。结果只能单调推进，重复 closed 只读原
事实，不触碰同名新引用。查询历史按 operation，不以现在名称查询替代。
任一步失败都不把未知结果解释为名称可用，数据库回滚与丢回执由同操作
重查结算。此能力先通过显式 closing_binding 接本地 AppService 测试，
默认 binding 仍无 closing；生产恢复证据、wire/CLI 后续接通才激活。

实现保持原 Manager、SQLite 事务与 native fence 所有权；内部 fence 基类
只复用原 acquire/exit 债务逻辑，既不新增 runtime，也不复制锁上下文。
三视角复审发现并修复跨代 pending 的 P2：仅换发新 token 不能让旧代
pending 获得 live ADMIT/SETTLE。两项确定性负例先失败，现两用途均要求
pending origin 等于 current；OBSERVE 可观察旧事实，可信旧 closed 仍可
由新实例对账，不要求历史 origin 等于 serving instance。

测试包括真实 AppService 清理和 registry NULL→closed、合法旧结果重放
不影响同名新 intent、独立目标的双向 operation 排他、用途 token 隔离、
无本地 pending 的 SETTLE 拒绝及换代缺历史拒绝。UPDATE closed 后和
DELETE active 后分别注入异常与真实子进程退出，两项写入必须一起回滚；
COMMIT 成功丢回执则用只读查询找到原 closed 事实，重放不碰新引用。
None/pending/closed 查询均断言 DB bytes/mtime 不变，pending 始终保名。

旧基线 51 passed（4.99 秒）；四项最初因缺接口失败，接线后相关 55 passed
（6.56 秒）。修复跨代权限并扩大到原创建/发现及架构集合后 110 passed
（45.60 秒）。三视角局部复审通过，生产 closing/recovery/wire/CLI 仍未
激活；本节不宣称完整命令交付完成。
最后用另一真实子进程在原 Session 清理门闩期间取得服务 fence 并请求
stop，确认不是同线程重入假象；独立合法目标的新 ADMIT 随后拒绝，原
pending 仍能结算。该补强及 schema 6/7 无迁移拒绝的相关集合 45 passed
（5.57 秒）。Ruff、三源 mypy、文档轻门禁及 diff-check 通过。
schema 8 的生命周期、namespace/service admission 消费者与当前清单
另验 101 passed（51.89 秒）；当前依赖图检查通过。

## 76. 原 Journal 的本代换代凭证（证据基础已实现）

生产恢复前先补不可省略的证据：schema 9 的 service_transitions 每个
service 仅保留本代一条凭证，绑定 successor instance/attempt、换代时
revision 与完整 previous ManagedServiceState（含原 native 身份及三项
清理事实）。真正首代显式 previous=NULL 且起始 revision=1，不能用作
已有 managed continuity 的恢复许可。该记录不表示当前进程存活。

journal.prepare 沿原 lifecycle fence 和同一 SQLite 事务，先核验旧状态
cleanly_stopped，随后原子写新 PROVISIONAL 和换代凭证。凭证本代不改，
普通 register/commit/stop/cleanup 不覆盖；下一次合法换代才原子替换。
复合外键绑定当前 instances 的 service/instance/attempt，延迟到同一事务
提交时核对，以允许上述成对换代，不允许半条凭证。无平行 owner/无限
历史、额外文件、自动旧格式迁移或新 native 判活/杀进程权限。

原严格 state codec 同时用于 previous，规范 JSON 有界 4 KiB；解码核对
previous 同 service/namespace、完整清理、不同实例/attempt、revision+1
等于起始 revision，当前 revision 不早于起始值。所有 fenced journal
读取/更新先校验本代凭证；缺失、损坏、错代均 fail closed，不由当前
PROVISIONAL 或内存补造。只读访问保持文件 bytes/mtime 不变。

本片先验证成对持久性、首次/多次换代、故障重试与原 journal 消费者。
随后生产 recovery admission 才使用该凭证，加上 bootstrap 原 self-native
身份和当前 startup attempt，区分 ADMIT 与已接纳 SETTLE；当前仍不激活
closing binding，也不把持久凭证单独当成完整恢复授权。

本轮实现保留原 Journal/数据库/codec，不新增 owner。previous 明确编码
namespace/service 和原九个状态字段，避免从别的服务复制前代状态后被
解码成当前服务。原 _read 包含凭证校验，read_transition 同样锁内读取
成对快照；不存在旧状态被读取为新鲜空白的回退分支。

原换代/关闭基线 38 passed（6.21 秒）；新增 11 项先因缺接口/表失败。
接线后 65 passed，一项旧发现损坏夹具被新外键提前拦截，现改为绕过
writer 的外部 SQLite 注入，继续验证真实磁盘损坏拒绝，不将其算作产品
缺陷。随后换代、原创建/关闭/发现、namespace/service admission 的扩大
集合 169 passed（22.89 秒）。三视角局部实现复审通过。

新增真实退出覆盖首代/后代的 instance 和 receipt 两次写入窗口，证明
事务成对回滚，不额外宣称这些小事务已 spill。测试另显式在 COMMIT
验证延迟外键、校验普通更新不改变原凭证、第三代保存无 native 但完整
清理的第二代状态，以及提交失回执后只读取得同一 successor。

补充深嵌套损坏 JSON 负测先复现 RecursionError，现归一为 invalid_record；
三项清理事实分别缺失、缺失凭证/错代/错服务/旧格式均拒绝。凭证基础不
等于已接生产恢复；下一步仍须消费原 bootstrap self-native、启动 attempt
及本代凭证实现 ADMIT/SETTLE，之后再激活管理 wire/CLI。
补强后的换代/registry/架构集合 70 passed（24.72 秒）；Ruff、两源 mypy、
文档轻门禁与 diff-check 通过。Linux 专属新增测试明确标注平台范围。

## 77. 生产恢复绑定（已接线并通过局部复审）

沿用原 ManagedMuxManager、Journal fence 与 AppService recovery attempt。
bootstrap 传入原 observer.identity 和 startup attempt 的只读值，配对启用
closing/recovery binding；不重新捕获 native owner。无该配对的直接绑定
保持创建专用兼容。Child 在 native 尚未登记时等待原控制循环，不提前
启动 application.prepare，也不改变 stop/abort 优先处理和启动总期限。

ADMIT 在原短事务内同时核对本代 instance/attempt/native、PROVISIONAL
且未 stop、§76 凭证和完整前代清理。已有 v2/v3 continuity 都走恢复屏障，
首代 previous=NULL 不能恢复已有记录。SETTLE 只允许同 manager 已接纳的
原记录与同一凭证，允许本代 stop/ABORTING，不允许换代或提前 COMMITTED。
ADMIT 重试仍检查未 stop；AppService 始终提交原 recovery intent 给许可，
并独立核对加载值等于原记录或本 attempt 已确认的 closed 投影。

恢复交叉核验不可变创建 intent、已签发许可的 origin 与可选确认结果，
关闭许可的创建目标、origin 和单调阶段，以及每个保留 Mux 的精确 active
引用。Registry 已确认结果不得从 continuity 消失；仅签发但未确认的操作
缺席仍为 unknown，不重放。Closed 历史不要求占有当前同名引用，不在
恢复核验中释放名字。多代关闭 origin 不必等于紧邻前代 instance。

上述读取与 SETTLE 的本地 continuity CAS 使用原 fence，Session 恢复/清理
在许可完全释放后执行。无第二恢复 owner、数据库版本变更或自动迁移。
本节测试需覆盖真实 Manager/AppService 的 v2、pending/closed、多代、
身份/历史篡改、stop、重试及 native 登记竞态，再检验 bootstrap 接线。

设计复审修订：生产配对模式连 load=None 也调用同一恢复许可（输入扩为
record | None）。None 仅在 registry 没有该服务已确认创建/关闭历史时
允许，不能因文件整体缺失发布空服务。仅签发未确认且缺席的 intent
继续保留 unknown 与名称占用，不释放、不重放。真正首代零历史 None
可冷启动；已有非空记录仍要求完整前代凭证。

并发准入补充：生产启动恢复会与 parent/control 的短只读观察竞争原锁。
仅 recovery admission 在原 5 秒 acquire 期限内异步重试明确 busy 的读准入；
每轮先确认原 context/数据库临时资源已完整释放，再重读全部身份和历史。
本轮读准入尚未产生 Session/CAS/ADMIT 记录效果才可重试；未知释放、非 busy、停止或
换代直接失败。正常 create/close admission 仍 fail-fast，不自动重放请求。

实现保留原 manager、fence 和 attempt；已有 v2 不改写格式，pending 成功
结算后的重试继续传原 intent，确认投影只用于避免重复清理/CAS。bootstrap
默认配对启用恢复，直接构造 manager 的旧路径仍 creation-only。首代 None
和整体索引缺失分别测试，后者还使用真实文件 lease 与移走保留副本验证。

设计复审的 None 绕过问题已修复；实现复审指出的外键提前拒绝夹具改成
独立 creation-only 目标，未登记观察改成第二轮驱动屏障。临时移除 native
门槛时该测试明确失败（1 failed，1.15 秒），随后恢复生产代码。

原相关基线 74 passed（10.26 秒）。初始新增测试一项缺接口，其余九项
先被夹具方法名错误拦截，未把它们冒充有效产品负测。修正接线与夹具后
71 passed，两项旧 bootstrap 测试更新为 prepare-before-commit 与登记前
不 prepare 的新约束。扩大集合 128 passed，其中一项新夹具被外键拦截，
另一项真实并发启动曾失败；修正夹具并单独复核后 49 passed（16.26 秒）。

确定性 fence/database 短 busy 两项随后复现提前中止（2 failed，1.50 秒），
现在只在原 recovery admission 内做有界异步读重试。退避期间 close/stop、
释放失回执均有独立回归；close 成功后不得重入，未知释放不得重试。
真实并发那次失败的具体内部点未被直接观测，不将单独重跑通过当作归因。
架构与生命周期最终局部复审通过；完整 lmux 的 wire/CLI、日志/tmp 有界
治理及真实安装/终端/性能验收仍按原目标推进。

最终扩大集合 154 passed（206.36 秒）：包括原创建/关闭、恢复、bootstrap/
child、真实生产子进程并发启动/重连，以及 Hosting/G11 架构约束；三视角
最终局部复审通过。最后按测试评审建议补固定期限假时钟测试，确认持续
busy 的五次尝试共享首次 5 秒期限，到期不再入场，公开 acquire 不可重用；
单测 1 passed（0.90 秒），未重复已通过的扩大集合。deadline 沿用原 busy
错误合同，不引入新错误分类。Ruff、五源 mypy、依赖图检查、文档轻门禁
及 diff-check 通过。本节没有执行提交、PR、推送或合并。

## 78. 关闭管理协议与生产连接（已接线并通过局部复审）

沿原 managed 创建连接增加显式可选关闭能力。关闭请求携带 §71 的完整
service/instance/close-operation/create-operation/name/Mux/token；查询结果
使用同一精确请求，但独立只读 operation，不重新调用关闭。返回仅为
pending/closed 历史事实；查询可返回 None（未知），关闭不得以 None 成功。
两者沿原 AppClientScope 的 accepted-work owner，EOF 只结束结果投递，
不取消已经接纳的清理。关闭用普通槽位，查询保留 control 槽位。

新增独立 loushang.managed-mux-close/v1 wire family，复用原管理 codec 的
4 KiB/严格字段和 requestId 规则；原 creation v1 字节不变。原 Remote
pending 记录核对 family、result type 与完整 close/create/name/Mux tuple，
即使投递 waiter 已取消仍验证；origin instance 由原 manager 对照历史
核验，不错误要求它等于当前 serving instance。无 token 回显或自动重放。

关闭需明确协商：本地记录追加 mux_closure 能力且必须同时 mux_management；
对应四种 managed semantic profile 使用 v2（discovery/execution 组合），
原 v1 profile/hello/record 保持不变。旧客户端拒绝未知能力，不能默默降级。
原 LocalPeer 仅从同一已保管的 managed scope 借 creation/close/discovery/
execution，不再创建第二 scope。AppHost 显式将已启用 closing binding
传到本地服务器；创建专用和手工旧入口仍不激活关闭。

完整生产连接需验证：错 profile/字段/响应目标在效果前拒绝；普通槽位满
时仍可查结果；EOF 后原清理继续、重连只读取得结果，原 manager 结算
精确名字引用；同名新 Mux 不受旧 closed 结果影响。CLI 随后使用该公共
能力完成冻结目标确认与结果查询，不在 TUI 内另造协调器。

实现沿原 managed_mux_wire 增加独立 close family，新增纯 client protocol，
不增加运行时 owner 或旧 AppClient 方法。原 creation-only scope protocol
不变；仅显式关闭分支借用额外 pure protocol，其 getter 失败仍关闭原 scope。
AppHost application/continuity 原边界暴露 closing 是否启用，由原 local
composition 选择 mux_closure；公共 ManagedConnectionLease 同样可借 close
client，CLI 后续不需要直接依赖传输细节。

原相关基线 101 passed（3.86 秒）；11 项新 codec 负测先因缺接口失败。
初步集合 124 passed，四项旧枚举全量夹具未传新增显式 close capability，
一项计数夹具试图覆写 slots 实例方法；现分别改成对应纯 protocol autospec
与测试范围内的类方法拦截，不把这些夹具失败当作产品缺陷。扩大到生产
子进程/架构后 121 passed（106.23 秒）。

三视角局部实现复审通过。补强测试覆盖 close 与 app/execution/create
六向 failure 串线、取消后的错完整目标/close-None、合法历史 origin、
getter None/抛错原 scope 回收，和真实服务端 16 个混合普通请求满槽时
查询仍可用。原 Manager/AppService/认证连接集成证明 EOF 后真实 Session
清理继续、新连接仅查询、pending 保名、closed 后精确释放，并实际创建
同名新 Mux 验证旧结果不误删；关停后的查询失败不折叠成 None。

最后补强集合 145 passed（13.76 秒），包括专用生产子进程：明确发布
mux_closure，经公共 lease 关闭、查询 closed、由原 manager 释放精确名字，
不调用模型。Ruff、相关 mypy、当前依赖图与 diff-check 通过。本节完成
公共协议/生产连接切片，未完成 CLI 关闭操作、日志/tmp 有界管理或整轮
安装/SSH/终端/性能验收，未提交、推送或合并。

## 79. 关闭命令与可追溯结果（冻结身份前置完成，命令实现见 §80）

`lmux close -t NAME [--yes]` 在原 namespace/manager 只读取得已确认 creation
与已有 close operation，打印 service/instance/create/Mux/name 的冻结预览；
确认前不发许可、不建连接、不关闭。确认后再核验原实例和精确 active 引用。
不存在旧 close intent 才签发一次新 operation，并在唯一 RPC 前输出关联 ID。
已有 intent 时只查询/对账该 operation，不重放 close（包括返回 None）。

`lmux close --server SERVICE --operation OP [--yes]` 精确重接历史操作，只查询
并对账，可沿原 issue_close 续签本代许可，但不再发 close RPC。它不按名字
重新选择目标，不自动启动服务。pending 保名；confirmed closed 才由原
record_close 原子释放原引用。None/传输失败/超时均报告 unknown 或 unavailable，
不把缺失 Mux 当成功。输出不含 token、PID、底层路径；只关闭 Mux 的运行
成员，不删除 Session 持久数据，也不停止其他 Mux 或服务。

`lmux close-status --server SERVICE --operation OP` 为只读查询，不签发或续签
许可、不写对账、不启动服务。原 registry 已确认 closed 可以直接显示历史
事实；未完成操作仅当原已签发许可属于当前实例时连接查询。跨代旧许可不
偷偷续签，提示使用上面的显式 close 重接路径进行查询/对账；查询不承诺
释放名字。无参数、格式错误在默认目录解析前拒绝。仅两个会签发/对账的
close 形式要求交互确认或非 TTY 的 --yes；close-status 是可脚本调用的
只读命令，不需要也不接受 --yes。

原 ManagedMuxManager 增加只读 inspection（creation、可选已签发 request、
已确认 result 的冻结值），与原 fence/registry 共用，不增加生命周期 owner。
原 ManagedMuxCommand 保管 inspection、manager、单个 connection 与请求；
短 native 调用仍 join 原 worker，唯一 RPC 受原绝对期限约束，finally 先关
连接再关借用 journal/namespace。不为 RPC 失败重新分配 operation 或重试
close；用户确认时间不计入随后启动的 30 秒动作期限。

本轮三视角设计复审指出两个联动问题：

- 名称释放后，原 attach 按 name 连接会在 A→同名 B 的竞态中进入 B。
  先在原 manager 增加 ManagedMuxInspectionV1 / inspect_mux /
  inspect_close_operation；attach 使用 confirmed creation 的精确 Mux ID，
  无确认 receipt 时拒绝，不退回名字查找。交互选择保留原页的 reservation
  和 instance，后续查找只用于核验，不替换用户选中的目标。
- close 许可已签发但 RPC 未发送时，两个只查询入口无法完成关闭。
  不能将 None 描述为“重连后即可收口”。显式继续原 operation 的用户入口
  尚需冻结合同：只在用户再次确认后向原完整目标提交，不自动重发、不换
  operation；同代使用原 AppService 的幂等关闭和原清理 owner。跨代且
  服务从未接纳的 intent 仍受 origin 校验拒绝，不能以续签 token 绕过。
  该恢复缺口未完成前不发布 close CLI，也不把本节记为关闭功能验收通过。

前置实现只增加冻结值与原 manager 的只读方法，无新表或生命周期 owner。
active inspection 要求当前实例及精确引用；historical operation inspection
验证原 journal 配对事实和历史归属，但不要求 COMMITTED/存活，保留旧请求
的 instance/token，不续签。许可字段不进入冻结值的 repr 或 CLI 输出。

用户最新交付授权为整轮完成后提交、推送、PR、合并并同步本地；它覆盖
早期 goal 的“仅本地提交”交付限制，不改变实现与最终验收范围。本节的
局部通过不触发提前合并。

前置验证：原管理器针对性基线 1 passed（0.70 秒）。新增三项 inspection
先因缺 API 失败；真实 CLI 竞态夹具先修正不支持的 resolve 参数，并仅对
已知 native busy 有界等待，随后在未修复 attach 上确实复现误连：关闭 A、
创建同名 B 后旧 attach 返回 0，负测失败（12.18 秒）。这些夹具错误不
计为产品缺陷证据。

实现后 inspection、关闭管理及原 CLI 集合 44 passed（42.52 秒）；另补
人工选择后 reservation/instance 改变的两项回归，2 passed（31.60 秒）。
真实 journal 换代回归证明新旧 manager 的历史只读查询保留原 token 与
instance，零写事务；运行 loop 不允许阻塞等待锁，相关测试改为等待
off-loop 只读调用完成，没有放松原合同。架构、生命周期、交互三视角
均通过此前置实现。Ruff、两个源文件 mypy 通过。关闭 CLI 及整轮交付
仍未完成；本节没有提交、推送、PR 或合并。

## 80. 显式继续未完成的关闭（设计通过，已接线并收口验证）

`close --server ID --operation OP --continue [--yes]` 是用户重新确认后的
显式继续，允许向同一个精确目标重送同一个幂等 operation；普通 close
历史重接和 close-status 仍只读查询，不自动重发。新 operation 的公开
关联 ID 必须在签发许可前输出，以覆盖许可提交成功但本地丢回执的窗口。
确认后 target、instance 或已有 operation 改变即冲突，不静默重新选择。

跨代未被 AppService 接纳的 intent，不能只删除旧 origin 校验。当前方案：
原 production manager 必须已经经过 startup recovery，原记录包含完整
confirmed creation 与 active Mux，且没有该 creation 的任何关闭记录；
当前 AppService 的 live ADMIT 仍为 previous=None 时才可显式继续。
permission 返回冻结的历史 origin，AppService pending 保留该 origin。
原 manager 仅保留有界的本代 admitted-operation 数据，记录这一次精确
ADMIT；跨 origin 的 SETTLE/重复 ADMIT 只对同一 manager 的已接纳记录
放行。重启后数据为空，已有跨代 pending 仍走独立 startup recovery。
不新增表、运行时 owner 或 wire 字段，也不改变 origin 的历史身份。

该方案经三视角设计收紧后通过；未知历史、缺失记录、stop、替换实例、
不确定写入和原 permission 清理债务继续拒绝新效果。实现必须证明未发送
失败可显式继续，同时不把已接纳任务变成重复清理或跨代 live 接管。

三视角要求现收紧如下：result.instance_id 是不可变的 operation origin
（首次签发实例），不是实际完成 pending 提交或清理的实例证明；当前
执行权限来自原 manager 的 instance/native、原 fence 与本代精确 ADMIT
记录。原 startup record 必须非空且不存在该 creation/Mux 的任何关闭
记录，registry phase 仍为 NULL。登记值保存完整 pending 身份，先验容量
限制且不驱逐，不能替代 AppService 原 pending owner 或清除未知提交/释放
债务。SETTLE 仍验证本代实例与 token；再次换代丢失本地登记，旧 pending
只能经恢复屏障。输出签发前的 ID 明确标为计划操作，不声称已经签发。

实际 CLI 使用原 Command/connection/manager，不增加 owner。确认前不签发
或连接；确认后复核冻结 target/instance/已有 operation，单次 RPC 前同步
检查原 deadline，响应、原只读验证及对账后的成功交付也复核期限。原 manager
提供 verify_close_result，与 record_close 共用 origin/单调结果核验；status
不能跳过验证直接显示服务端 phase。写入仍独立重新核验，不能拿只读检查
代替事务内授权。所有短 native 操作等待原 worker 完成再关闭借用存储。

unknown 明确输出需重新确认的精确 --continue 命令，不自动重放；旧 token
的 reauthorization_required 只提示普通历史查询/对账，不直接建议重送。
observedInstanceId 与 originInstanceId 分离；cached closed 是历史事实，
不证明服务仍可用。关闭后的 Session 持久文件不删除，同名新 Mux 不受旧
operation 的查询或对账影响。

验证过程中发现并定位实际竞争故障：关闭后同名重建间歇返回
operation_unavailable。单次重跑通过没有当作原因已消除；加固确认屏障
的 race_completed/真实 Mux 与实例变化断言后故障再次出现。测试专用
有界子进程探针（仅错误类型/代码/栈位置，无参数或密钥）在 8 轮序列
中记录原 _ManagedMuxFence 获取文件 owner 锁时的 ManagedStorageError
busy，发生在业务准入检查/提交之前。具体竞争线程身份未由探针确定。

三视角同意将原 recovery 的等待循环上提原 _ManagedMuxFence：同一个
公开 acquire、原始 5 秒绝对期限、原 loop/thread；仅重试 fence 和短
只读事务。每轮确认 DB/fence 释放且无债务，清除尚未交付的 _permit 或
_transition 后异步退让；关闭、stop、instance/token 每次重新核验。
check_*、本地 ADMIT 登记、RPC、continuity/CAS 与 Session 清理均不进入
循环，未知退出仍保留原 owner 并失败。这取代此前 live 准入对纯 busy
立即失败的行为，不改变用户明确继续与禁止自动重放的命令合同。

证据：原恢复/关闭基线 46 passed（6.37 秒）；两个跨代继续回归先失败。
首次扩大集合中的两项夹具问题为不存在的 Session.closed 字段及旧检查
拦截器未转发新增 origin 返回值，修正后未当作产品缺陷。中间集合
139 passed（89.32 秒）仍不足以覆盖间歇竞争；有界 8 轮探针复现为
1 failed（14.90 秒），随后四项 create/close × fence/DB 的确定性 busy
回归也先全部失败（3.02 秒）。修复后关闭/创建准入、恢复、真实 CLI
和架构集合 119 passed（124.22 秒），包括真实生产重启后的未发送操作
继续，以及 8 轮同名复用。门禁仅补记既有 manager 的 Hosting identity
与 stopper 的 service/group observation 精确依赖，没有放宽其他导入。

补充边界验证：recovery/create/close 三类准入的取消、stop、未知释放与
原始超时边界 12 passed（36 deselected，1.98 秒）；原管理器、关闭 wire
与 AppService 关闭运行时回归 58 passed（4.23 秒）。受影响源码 Ruff、
mypy、文档轻量检查（6 passed）、依赖图一致性及 git diff --check 通过。

三视角局部实现复审的问题已修复：RPC 前同步 deadline、只读 origin/
单调核验、明确恢复指引和确认竞态 oracle。整轮 lmux 的完整会话视图、
有界日志/tmp、安装/SSH/首次使用性能最终验收仍未完成，未提交或发布。

## 81. 共享会话输入与模态优先（局部复审与扩大验证通过）

本切片继续 M3 的完整会话视图复用，不新增 Hosted 输入控制器或任务 owner。
原 HostedMuxShellV1 改用已有 ConversationInputRouter；编辑、选择、补全、
换行和运行中提交策略与 Embedded 使用同一实现。原 router 的缺省
optimistic 行为不变；显式 deferred 模式仅产生现有 typed input result，
不先插入消息、清稿、增加历史、转移附件或消费本地显示队列。
deferred 是无附件端口：配置 image stager 或提交时 DraftStore 非空均拒绝；
不默默丢弃图片，也不将未确认远端队列变成本地可编辑队列。

Hosted 在每次输入前从当前 window 更新权威 running 展示事实，不依赖
上一帧是否 render：idle Enter 提交，running Enter steer、Alt+Enter follow-up；
Shift+Enter 换行，// 保留字面 slash。共享静态 SlashCommandCompletionProvider
只列既有外壳命令，不加载 Product 命令、插件、文件扫描或远端执行能力。
所有语义操作仍经过原 bounded ShellActions 和精确 attachment/generation/
member/session request binding；Ack 只表示请求确认，不修改权威运行事实。

原 router 完成本地编辑/补全后，先同步并校验窗口草稿，再做命令验证与
任务接纳。发布失败保留一致的本地草稿且不记历史；原同步接纳成功后才
清空并记一次历史。该次序修复复审发现的 P2：/inter 补全后入队失败曾让
composer 与 window.draft 不同，切 Tab 会回退。已有 task 的未知结果仍
只改变匹配请求的呈现，不恢复草稿、不自动重送。

详情和 Session picker 先消费普通 Tab、Enter、Ctrl+C、Ctrl+D 等按键；
仅明确的 Ctrl+B 外壳前缀例外，避免看审批时意外切 Tab、interrupt 或 detach。
审批仍使用原完整呈现回执/代际校验，不因共享路由绕过授权。按键 release
在原入口忽略，终端 EOF 与 view dispose 仍沿原关闭 owner，不停止应用。

保留原 G17 明确刷新时同 Mux/member/session 的光标、选择和 undo 合同；
这只是本地编辑状态，不能保留远端权限。每次绑定清补全与共享 router 的
jump 上下文，晚到结果仍检查完整 request key。清理释放原 router 的私有
DraftStore 并清 editor cache，不增加每 Tab 的事件循环或生命周期。

三视角设计收紧及实现复审通过。新增回归先复现模态穿透与未接入共享
路由；新增夹具误用只读 running 和不存在的 Composer.cursor 已修正，
不当作产品缺陷。共享输入/旧 Hosted 基线 45 passed；首轮 64 passed、
两项旧断言需按已接受 running Enter=steer 语义更新。扩大集合曾为
135 passed、4 failed，其中一项上述 cursor 夹具、三项是 §78 已审关闭
wire 接线遗漏的旧 G16 清单。架构复核后仅补 client_scope 的精确 close
值依赖和两个叶预算 201/244；原 aggregate 1100、shell 四文件 950 及
其他依赖/ambient 禁止不变。P2 修复后的输入/请求/编辑器集合 36 passed。
最终扩大集合 153 passed（46.13 秒），包括 Embedded 原剪贴板/启动、
Hosted 审批/编辑器/Markdown/terminal/settlement、旧 mux 命令和 G11/G16
架构边界。补充明确 action_queue_full 断言后，该项 1 passed（17 deselected，
1.46 秒）。三源 mypy、受影响 Ruff、文档轻量检查、依赖图一致性与
diff-check 通过。

完整 goal 的能力呈现、实际有界日志/tmp、剩余管理命令及真实安装/SSH/
首次使用性能验收仍待收口，本切片不作为最终交付完成证明。

## 82. 持久存储额度与文件身份（账本已实现，写入接线待完成）

现有日志/tmp 路径不是配额。原 registry 增加有界 allocation 账本，不新建
数据库、常驻 broker 或进程 owner；额度不是文件写权限。日志 slot 以
service/kind/slot 为稳定键、原子预留完整段容量：普通最多 5×10 MiB，
trace 最多 2×10 MiB，namespace 两者合计 200 MiB。已写和未用预留均
计费，跨实例退出/重启保留。临时分配另绑精确 instance，每实例 128 MiB、
namespace 512 MiB，单实例最多 256 个 slot，整个账本最多 4096 行。
临时容量按 4 KiB 单位预留，不能通过大量一字节分配绕过文件数量上限。

每个 allocation 冻结随机 ID、完整分配键、容量、实际根的路径摘要与
device/inode；创建前先持久收费，原文件 owner 成功创建并同步后，再
登记一次精确文件身份。不把 reserve 回执当写授权，不凭同名/大小认领
未登记残留。未知预留只查询/重入同一分配键，不另起一个分配；身份登记
丢回执仅对账原 ID/目标。同名不同容量/路径/inode 拒绝，不提供基于
“文件没看到”“进程重启”的退款入口。

三视角明确后续实际 writer 的门禁：固定 inode 上有界 append/轮转，
不使用未计费的 old+temporary 双份替换；部分写入/fsync 未知不能整条
重放或释放收费，暂停原 writer 并保留资源债务。未知目录条目阻止新的
受管写入；不同文件系统各自校验物理余量。tmp 的解码、复制、发布前后
同时存活的副本都必须预留，只有原 owner 确认精确删除并同步才可释放。

封闭生命周期事件不接任意文本或原始 stdout/stderr，原始流仍 DISCARD。
日志错误不能递归记录，额度/锁忙时丢弃；控制流程不等待日志写入重试。
这不承诺可抢占阻塞的 native IO，也不能在日志 IO/关闭债务未结算时
宣称整个进程 clean。数据 plane 与控制预留隔离，日志分配不消费原
registry control headroom。

本切片先验证账本；实际日志 writer、bootstrap 事件及 RuntimeScope 写入
消费者仍需后续接线。仅传 LOUSHANG_TMPDIR 不限制任意第三方写入，不把
受管 allocation 的上限宣称为操作系统级磁盘隔离。

账本实现采用 schema 10，旧 schema 9 与更早格式只读拒绝，不自动迁移或
重建。原事务内校验 namespace 总量、临时 instance 总量和 4096 行上限；
SQL 闭合值约束同时限制每 service 的 5/2 日志 slot 与每 instance 的
256 临时 slot。reserve 返回既有完整目标，否则冲突；bind_file 只登记
原 allocation 的单一文件身份。二者未知提交均可原目标对账，不退款。

原 registry/file 基线 80 passed（5.80 秒）；新 API 在实现前为缺少模块
的收集失败。首批账本/registry 52 passed（3.97 秒），与文件、transition、
namespace admission 扩大集合 162 passed（15.79 秒）。三视角实现复审
未发现账本代码阻断；按复审补强双方 child 完成 open 的 ready 屏障，
独立 slot=256 负测，以及 16 MiB 的 4096 行合法 fixture，验证行满时
新分配拒绝但原查询/幂等/绑定仍可用。补强与架构集合 43 passed、1 项
inventory 尚未列出新模块，已同步精确源清单，待重验。
单项清单重验 1 passed（10 deselected，17.82 秒）；两源 mypy、受影响
Ruff、文档轻量检查、依赖图一致性与 diff-check 通过。账本局部复审通过，
下一步是以这些收费/身份事实接通原文件 owner 的实际有界事件写入；
尚未启用日志 writer、trace 或 tmp 回收，整轮 goal 未完成或提交。

## 83. 原文件 owner 的有界追加与轮转

`PrivateManagedDirectory` 增加 `data_snapshot` / `append_data`，复用原目录
描述符、稳定锁和清理账本，不新建运行时或后台 owner。只读快照最多读取
16 KiB 尾部，记录 inode/device、大小、mtime/ctime；锁内比对完整快照后
才允许追加。整条编码字节先受 16 KiB 限制，文件容量为调用者注入的
已收费容量（最多 128 MiB），不能把容量参数或快照当实例写权限。

首次创建是 exclusive，日志消费者应先预留、创建空文件并同步、绑定精确
身份，然后追加事件。轮转需明确 `truncate=True`，先完成值与容量检查，
再在同一 inode 截断并追加；无临时副本峰值，也无旧段完整保留承诺。
本层不解释事件格式或认领未登记文件，上层仍须拒绝未知文件、不完整
尾部与失效实例授权；§82 的账本不变，不提供退款。

写入或截断前，原 owner 登记数据 fd 同步债务；短写、中断、零字节写、
同步或效果核验失败后封闭该 owner 的新追加。清理先同步原数据 fd，
再同步目录，最后关闭，不重发正文、不重做截断。同步再次失败继续保留
原 fd。关闭结果未知后，绝不再次操作该数字 fd，以免伤及复用句柄。
清理成功也不证明某事件完整写入；有限保留日志不是完整审计记录。

三视角复审发现并修复一项关闭错误传播 P2：原辅助函数使用环境
`sys.exception()`，可能把调用者外层异常误当本次 IO 主异常，吞掉正常
路径的关闭失败。现在各调用显式传递本次 primary，正常路径为 None。
测试复审还补强清理的实际顺序：再次 fsync 失败后身份/债务不变，恢复
后必须原 fd 同步成功再关闭；期间禁止 write 和 truncate。两项复核通过。

原文件/账本基线 66 passed（5.40 秒）；新增 API 实现前 15 failed，均为
缺少方法。首次实现与原文件/账本集合 81 passed（5.95 秒）。新增回归
另覆盖外部追加/截断/路径替换、读取时变化、编码字节先验上限、无锁
拒绝，以及外层 except 中真实 close 后 fd 复用。最终文件、账本、registry
和锁等待扩大集合 135 passed（10.53 秒）；Ruff、单源 mypy、文档轻量检查、
依赖图一致性与 diff-check 通过；原 AppHost baseline/G9 架构集合
23 passed（18.85 秒）。本切片完成底层 IO，不代表事件 logger、bootstrap 或 trace/tmp
消费者已接通；整体 goal 仍需实际接线与安装验收。

## 84. 封闭生命周期日志消费者（实际文件写入，尚未激活 bootstrap）

`ManagedLifecycleLogV1` 借用原目录 owner 与额度账本，无线程、任务、独立
close 或新运行时。固定 `lifecycle.lock` 和五个 `lifecycle-0..4.jsonl`
文件；每段持久收费 10 MiB，普通日志合计最多 50 MiB。测试可注入更低
物理段上限，但不能降低持久收费。满段选择下一段在原 inode 上截断轮转，
不产生临时双份副本，不另起 slot 绕过 namespace 配额。

事件字段闭集为版本、白名单 lifecycle event/code、instanceId 与 sequence，
不接任意 message、路径、token 或 stderr。编码整帧最多 256 字节；所有
传入纯值验证先于 IO。每次写入在原 logdir 锁内扫描全部五段，核对实际
根路径摘要/root identity、allocation 与 file identity，然后严格验证每段
最后一帧的 canonical bytes、真实换行边界及非零尾序号不重复。序号以
各段尾部最大值递增，满 2**63-1 拒绝而不回绕。这里只证明合法尾帧，
不声称整段历史无损或所有历史序号唯一；每段尾部读取至多 16 KiB。

首写遵循 exclusive reserve → exclusive 空文件创建/同步 → bind 精确
identity → append。账本的 `exclusive=True` 在原事务内拒绝已有行，
因此历史 unbound 即使文件缺失，也不能变成本次创建回执。所有段先验，
任一未知条目、已绑定文件缺失、未绑定残留或不完整尾行均拒绝，不跳过、
认领、修尾、退款或重放。已绑定空文件可以由后续已获授权的 consumer
写入新事件，但不证明前一调用成功；同一 consumer 的任何 IO 失败都会
在原目录 mutex 内封闭，等待中的并发调用也必须看到封闭结果。

目录扫描器也纳入原目录 owner：关闭未知时保留原 iterator 和债务，不
盲重试，不假报 clean。容量主异常不被关闭错误覆盖。日志 consumer
必须在 native worker 上调用；running event loop 在取 mutex 前直接
busy 拒绝，无 IO、不封闭 consumer，以免磁盘/锁等待阻塞 stop 或输入。
锁序保持 logdir → 短 registry 事务，禁止从服务/registry fence 反向取锁。

本切片尚未将日志接到 child/bootstrap；后续激活必须由原 journal/native
handoff 证明跨代资格，并让日志 IO 与原目录清理债务进入原生命周期，
不能以新任务逃避 join，也不能阻塞控制 worker。实际 trace/tmp 消费者、
物理余量检查与安全回收仍待接线；Session 的缺省持久策略不变。

基线文件/额度 41 passed（4.92 秒）；新事件模块实现前为缺模块收集失败。
首次事件/文件/账本集合 53 passed（4.98 秒）。复审修复扫描器保管、并发
封闭与 loop fail-fast，补充真实绑定/预留/创建丢回执、部分写入、空绑定
重开、坏/耗尽/重复尾序号、200 MiB 满额后原五段持续轮转且 inode 不变。
存储与原 baseline/G9 架构扩大集合 171 passed（37.53 秒）；最后 loop
准入修复后的事件集合 27 passed（4.45 秒）。三源 mypy、受影响 Ruff、
文档轻量检查、依赖图一致性与 diff-check 通过；三视角局部复审无剩余
阻断。完整 goal 未完成，尚未提交或推送。

## 85. 生产后台服务生命周期日志接线

生产 `coding.managed_process` 明确开启 bootstrap diagnostics，默认 lmux
后台服务使用既有 layout 的 logs 目录。底层 bootstrap/child 仍默认关闭
此选项，保留其他显式调用的原行为；不改变旧命令入口或 Session 存储。
bootstrap 先保管 deferred 日志目录，原 journal 的 instance/attempt/native
核验成功且已释放 fence 后，才准入目录、借用账本并写封闭事件。身份
读取在 native worker 上作有界锁等待；不持 service fence 跨越日志正文
写入。原进程仍活着时，scope 结算门槛继续阻止后继实例激活。

不新建日志 executor 或运行时：原 child pool 在开启诊断时有两个槽位，
原 `_io_lock` 保持一个控制 job，独立保管最多一个日志 Future。loop 只
入队五种 once 事件，依次异步投递。starting 发生于 native 已登记、准备
开始之前；ready 在 activate 成功且尚未 closing 时入队，晚到成功不
补记 ready。stopping 为关闭请求；stopped 仅表示应用及其阶段任务清理
完成，不是进程/group 退出或可换代证明。failed 只有封闭错误码。

每个日志 job 先保管 publication gate，再调用原 pool.submit。只有取得
Future 回执才能打开 gate。提交在入队前失败或入队后丢回执时，gate=False
禁止 callback 访问 journal/日志；不重发事件，也不等待可能根本不存在的
done 回执。已接纳的 native Future 则必须保留，取消等待任务不能丢弃它。
最终结算先同步关闭入队，等原日志任务，再 shutdown 原 pool；已完成的
控制清理用原标记保留，日志结算重试不重复成功的控制阶段。

日志是有限保留的 best-effort 诊断：格式、容量、目录或 IO 错误会丢弃并
封闭该 consumer，不向业务传播原异常。应用清理及 stop 发起不等待日志
正文；共享 registry 的短事务仍可能争用，不能承诺控制路径完全不受
共享存储影响。日志 Future/目录同步或关闭未知仍是资源债务，禁止整体
假报 clean。bootstrap 必须在 child 日志结算后才关闭日志目录，再释放
observer/journal/registry；日志缺失不能作为服务成功或失败的判断依据。

接线前基线 58 passed、1 项旧 lifetime 测试超时，定位为遗漏原 native
登记，已补夹具，不放松生产门槛。首轮 60 passed、2 failed：新日志 ready
时点竞争已移至 activate 完成包装内；旧测试直接读正在被控制任务持有的
fence 改为有界 offloop 只读等待。下一轮 62 passed、2 failed：日志超时
测试须先结算原 close task 再申请 retry budget；真实生产测试 registry
首次读取增加同样的有界只读等待，未重启或重发业务操作。

复审修复未入队日志的假债务，补入队前/后失回执、日志 waiter 取消、
迟到 activate，以及真实 bootstrap→writer→日志 fd fsync 屏障测试。
真实日志 fsync 挂起时，应用关闭与 stop/cleanup 事实仍推进，bootstrap
保留全部依赖；释放后原任务完成并收口。生产子进程启动、重连、停止与
这些故障专项 10 passed（23.94 秒）。三视角局部复审无剩余阻断；扩大
场景继续验证，完整 goal 的 trace/tmp、管理体验及安装性能验收仍待完成。

随后扩大到 child/bootstrap/lifetime、日志 writer、真实生产进程冷启动/
暖复用/并发与 baseline/G9 架构：129 passed、1 failed（139.87 秒）。
唯一失败为新 late-native 夹具与原控制轮询的合法 fence 竞争；改为原
instance/attempt/native、固定五秒预算的幂等登记重试，不换进程或身份。
只复验日志专项，已通过的其他集合不重复启动。三源 mypy、受影响 Ruff、
文档轻量检查与依赖图一致性通过。

late-native 夹具修正后的日志专项 11 passed（3.88 秒），包含真实默认日志
与 native gate、fsync 挂起、缺失/陌生目录、提交丢回执、取消和迟到激活。
本轮相关运行均已结束；整体 goal 继续，未提交或推送。

## 86. 只读服务状态与目录诊断入口

新增 `lmux status -t dev` / `lmux status --server <exact-service-id>`，非交互
可用，名称选择独立于调用 cwd。共享 `ManagedDiscoveryV1.inspect_service`
在原 registry 的一个只读事务中投影 service/instance，不要求该服务仍有
active mux 名称，不创建 journal、连接、coordinator 或 native observer。
缺失 namespace/目标只返回 not_found，不补目录、不启动或恢复服务。

输出明确标记 `observation=recorded_only`、`liveStatus=not_probed`；
recordedPhase、stopRequested 和 cleanlyStopped 是持久事实，不把
COMMITTED 当作当前 ready，不用日志推导进程退出。这里只做记录诊断，
实时探测、服务别名/无目标汇总及日志读取仍须后续完成。

同时显示该服务的稳定 logs/application 路径。临时目录只显示受管默认
base；实际 instance override 尚未持久记录，因此 actualRoot=null 并
给出原因，不使用当前 shell 的 LOUSHANG_TMPDIR 冒充历史实例路径。
路径输出经原 JSON 转义，观测不透出 native PID、认证材料或连接记录。

初测 23 passed、1 个“名称释放”夹具错误；改为删除 active mux 并验证
名称列表为空后，公共发现/CLI/原 baseline/G9 架构 47 passed（26.63 秒）。
新增端到端 journal 投影测试覆盖 PROVISIONAL、COMMITTED、stop，以及两项
清理事实不报 clean、三项齐全才报 clean；每一步禁止连接/启动并比较
整个测试目录树，名称释放后 exact ID 仍可查询。三源 mypy 与 Ruff 通过。
本入口不代表整体管理体验或完整 goal 已交付。

完整 journal 投影夹具初次绕过 service admission 被生产门槛正确拒绝；
改为通过原 ManagedServiceAdmissionV1 建立控制目录，未放宽门槛。
状态专项最终 7 passed（5.51 秒），包括全阶段投影及全树不变；三视角
局部复审通过，文档轻量检查与 diff-check 通过。运行均已结束，完整
goal 仍在进行，尚未提交或推送。

## 87. 有界只读日志入口

`lmux logs -t <mux>` 或 `lmux logs --server <service-id>` 共用原公共发现，
`--limit` 缺省 50、范围 1–100。缺失 namespace、目录或锁不创建资源；
日志读取不连接服务、不启动后台、不补配额、不修复文件。

在原日志锁内检查五个固定段的预算绑定和文件身份，每段最多读取末尾
16 KiB。丢弃被窗口截断的首帧，校验全部可见帧的 canonical 编码及
序号后才应用 limit；损坏帧即使不在输出范围也导致零事件输出。
完整释放锁后复验原绝对期限，再输出 JSON。输出明确标识
`observation=bounded_tail`、`completeHistory=false` 和扫描上限，
不承诺完整历史、实时存活或任务成功事实。

三视角复审发现并修复三项 P2：读锁竞争不应永久禁用后续诊断；锁退出
迟到不能交付成功结果；原 160 条夹具不足 16 KiB，未实际覆盖截断。
writer 现在仅对尚未准入、明确 busy 且无清理债务的初始锁竞争返回
None，丢弃当前事件、不重放；准入后的错误和未知释放仍封闭 writer。
新增真实 reader/writer 竞争、释放锁后到期，以及 220 条记录实际截断
断言。三视角局部复核通过。

初轮日志/状态/架构专项 75 passed（39.14 秒）；修复后 reader、writer、
child diagnostics 和 CLI logs 58 passed（28.41 秒）。三源 mypy 与
相关 Ruff 通过。此节只交付有界日志读取；trace/tmp 实际消费者、完整
CLI 体验和真实安装综合验收仍未完成，不代表整体 goal 可发布。

## 88. 全局选择器有界翻页

裸 `lmux` 和无目标 `attach` 的原选择器现在支持 `n` 下一页、`r` 回首页，
数字选择当前页，空输入取消。只保留一页，沿原公共发现的 name 游标读取；
不同页是独立快照，不承诺跨页枚举一致性。整页恰好为最后一页时，下一页
为空会明确取消，不触发默认 main 创建。人类输入等待后为下一次只读操作
建立新预算，不延长在途任务。选中后仍用原 reservation/instance 复核，
并经过原连接准入；记录字段继续显示 unknown，不暗示在线。

变更前命令基线 46 passed（120.26 秒）。新增下一页、回首页、空后继页、
取消及非法输入回归；三视角局部复核通过。改后原命令与首批分页回归
53 passed（116.77 秒），Ruff、mypy、文档轻量检查与 diff-check 通过。
评审建议补充的 bare 满页翻到空页、无创建/连接且资源关闭的完整命令链
回归另行补跑：最终分页专项 8 passed（5.64 秒），含此完整调用链验证。
唯一在线 Mux 自动连接仍未实现，此处不能替代在线探测和连接协调合同。

## 89. 批量管理前的公共 namespace 快照

`ManagedDiscoveryV1.snapshot_namespace` 在原 registry 的单一只读事务中
取得完整 services 和 muxes 两组持久观察，包括没有 Mux 名称及尚无
instance 的服务。分别读取 MAX_SERVICES/MAX_MUXES 加一条检测越界，
超限整体报 capacity，不把截断结果称为全部。服务投影与 inspect_service
共用；冻结值检查重复 service ID、重复名称及两组生命周期字段的一致性。
完整退出事务后复验原 deadline，不保留事务锁或增加资源 owner。

此快照仅用于冻结预览和后续协调，不证明在线、不授权停止。未来
`stop --all` 必须沿原 namespace owner 对确认时的精确 instance 逐项
准入；不得确认后重新发现目标集、追随换代或纳入新服务。

基线发现测试 18 passed（3.01 秒）；实现后发现、快照、status 回归
31 passed（10.09 秒）。覆盖无 Mux 服务、冻结/关联校验、两种上限独立
拒绝、真实第二 SQLite 连接写入受原读事务阻挡、损坏/关闭 owner 拒绝及
退出事务后的到期结果拒绝。Ruff、mypy 与 diff-check 通过。
本切片尚未接入 CLI 批量停止，不能据此宣称 stop --all 已交付。

三视角设计与局部代码复核通过。按建议将容量夹具加强为上限 1、实际
2 项（服务和 Mux 各自独立）；首次补跑 5 passed、1 个夹具 operation ID
复用冲突。改用独立 ID，未修改生产冲突检查，最终专项 6 passed（1.45 秒）。

## 90. stop --all 冻结确认与逐项结算

CLI 新增 `stop --all`，与 `--server` 互斥；非 TTY 必须 `--yes`，缺失
namespace 报 not_found、不创建目录。原公共快照一次性取得预览：namespace、
Product/workspace、精确 instance、全部 Mux 名称及共享预算说明。确认后
从 30 秒总预算开始按固定 service ID 顺序停止，不续期、不重新发现目标。
无 instance 项报告 skipped/no_instance_at_snapshot；剩余预算不足报告
not_attempted/deadline，不构造新停止操作。任何项失败，总退出状态非零。

每项继续原 ManagedServiceStopOperationV1 的精确实例检查和 graceful-only
语义。CLI 先保管原 journal/stopper 再进行 IO；用户取消不进入普通错误
继续路径。成功项释放本地资源后输出 stopped，不把 stop 请求当完成。
清理先发起并保管所有已有项的原 task，再作独立的 2 秒有界等待；此等待
不追加停止预算，不取消原清理。未结算时保留 journal/namespace，沿既有
cleanup_incomplete 退出路径处理。仅 terminal 失败/取消且仍有资源的
清理 task 可重建，继续原 owner 的 close，不重放 stop 或替换 owner。

设计复审收紧清理等待、取消及 no_instance 命名；代码复审进一步修复
failed close task 永久阻止原 owner 重试的问题。基线命令 46 passed
（117.78 秒）；首轮批量/命令回归 53 passed（143.52 秒）。新增确认期间
服务加入不纳入、同服务双 Mux 实际批量停止，以及原 journal 清理重试
专项正在验证。本节尚不代表全部 lmux goal 或真实安装综合验收完成。

三视角代码复审通过。最终集成初跑 31 passed、2 failed：同服务双 Mux
夹具未承担原 Popen 父进程的 wait/reap 责任，以及架构反向依赖清单未
登记新 CLI 组合模块。已沿既有单服务测试补原父进程回收，更新精确清单，
未弱化生产停止结算；另补取消 cleanup waiter 后仍保留原清理任务的回归。

补跑批量/G9/架构组合 33 passed（19.78 秒），剩余 1 项为文档源路径
精确集合漏登记；补齐后原 baseline 架构 11 passed（17.79 秒）。因此
本次最终 11 项批量功能回归均已通过，包含确认后新增服务排除、真实
同服务双 Mux 停止、取消与原任务保留。三源 mypy、相关 Ruff、文档轻量
检查及 diff-check 通过。本轮仍未提交或发布，完整 goal 保持进行中。

### 确认后换代的直接回归

补充真实 journal 状态转换的 CLI 验证：预览后、确认输入期间，将未启动
native 的旧 provisional 实例合法 abort/settle，再 prepare 新实例。原
batch 对旧 instance 返回 conflict；禁止 native admission/request_stop
的断言未触发，新实例完整状态保持不变，输出也不偷偷替换成新实例 ID。
另补空行、拒绝、缺少换行及过长确认输入均不创建 batch owner。
最终批量专项 16 passed（15.19 秒），相关 Ruff 通过。

## 91. 实际暂存消费者接线前的源码核对

当前 `coding/managed_process.py` 向子进程传入实例专属 LOUSHANG_TMPDIR，
但它不是强制文件系统配额，不能据此宣称全部暂存有界。已定位的关键路径：

| 消费者 | 当前行为 | 后续约束 |
| --- | --- | --- |
| `harness/session/output_artifacts.py` | 在注入或平台 temporary root 下创建 session-output 目录，发布为 Session blob 后清理 | 需要在实际 stdout/stderr 写入前取得预算，而不是发布后检查大小 |
| `harness/workspace/exec/service.py` | 在 artifact_dir 下创建输出文件；preview/rolling 的内存上限不等于磁盘文件上限 | 配额必须覆盖持续写入、并发 stdout/stderr、超额与取消清理 |
| `coding/bootstrap.py` 的 `_ExplicitTemporaryDirectory` | 使用无 dir 的 mkdtemp，独立显式清理 | 不能假定 LOUSHANG_TMPDIR 会影响 Python tempfile；需通过原组合注入实例暂存能力 |
| Session 索引/arch cache 的原地临时替换 | 暂存与最终文件属于各自存储 owner | 不因为后缀或 tempfile 名称就挪到 lmux gc；保持原子替换和 Session 默认策略 |
| 插件 revision quarantine、工具解包、git 临时 index | 属于各自 cache/workspace owner | 逐项确定 lifetime，不能用全进程 TMPDIR 覆盖来冒充统一治理 |

下一步应从 Session 命令输出这条实际字节写入链切入，以注入的中性预算/
暂存接口连接原 AppHost 配额，而非让 Harness 反向依赖 AppHost。必须验证
总磁盘上限与所有者清理，再接其余消费者；这项仍是完整 goal 的未完成项。

接线边界详见 [受管命令输出留存](lmux-managed-output-capture.md)。三视角
已对架构、生命周期和超额体验完成设计复审，具体接口/数值仍待冻结。
现有输出相关基线 26 passed（2.76 秒）；尚未修改实际 capture 写入路径。

## 92. 无 Mux 的显式服务启动（局部复审与扩大验证通过）

补齐草案 §4 高级服务入口的工作区启动部分：
`lmux server start [--workspace PATH]`，缺省工作区为 cwd，可非交互调用。
服务别名仍待公共登记层实现；当前返回精确 service ID，供现有 status/logs/stop
使用，不把工作区名或 Mux 名冒充服务别名。

工作区规范化及目录校验早于 namespace IO；依次保管原 namespace admission、
service admission 和 coordinator。无需预留 Mux，未进入 Harnesstui，也不创建
Session。认证连接成功才返回 `service_ready`、`serviceId` 和 `instanceId`；
重复调用相同工作区复用原实例，之后 new 仍走原 Mux 创建协调器。
关闭依次结算原 coordinator、service 和 namespace，不停止后台服务。
保留已有 `start -t NAME` 语义，不通过失败回滚删除 durable intent。

旧 CLI 基线 46 passed（159.97 秒）；新增非交互入口红测按预期在旧 parser
失败。接线后的新旧集合 52 passed（144.98 秒），三视角局部复审均未发现
新增 P1/P2。按建议补强真实非 TTY/禁止 stdin 和终端调用、认证空 Mux 查询、
默认 Session 根未创建，以及 coordinator 构造失败时原 owner 清理且保留
durable 登记的回归，补强集合 7 passed（12.42 秒），进程已正常退出。
Ruff、源文件 mypy、文档轻检通过。
这个入口不替代临时文件消费者、服务别名和整体验收等剩余工作。

## 93. 公共服务别名（局部复审与验证通过）

别名属于原机器 namespace 的 Registry，不属于 Coding/TUI 私有配置。
单独的 `service_aliases` 表绑定 name、service ID 和原 reservation operation ID；
最多 128 项，一个 service 至多一个别名。与 Mux 名称分域，不复制实例或权限。
第一版不提供重命名、删除、重绑定；stop 不释放别名。

名称使用现有 Mux 字符集和 64 字符上限，但排除完整 64 位十六进制串，
避免与精确 service ID 歧义。一次 reservation 在原写事务中同时登记缺失
service 和别名；相同完整 intent 可重试，任何不同 intent 的重名、同服务
第二别名、operation ID 复用均冲突。读取使用原短只读事务，不触发准入。
未知提交结果不删登记，不另分配 operation 自动重试。

`server start --name build [--workspace PATH]` 在 service admission/spawn 前
登记别名；已有同名且完整 service 相同则复用原 reservation。并发首次登记
发生已结算 conflict 时，在原期限内只读核对一次胜出记录，同 service 才继续，
不换 operation 重试。未知提交或清理债务不走此对账分支。
普通无 name 启动不要求别名。`stop/status/logs --server build`
先通过公共 Registry 解析为精确 service ID，后续使用原实例冻结和确认逻辑。
历史 close/close-status 的 operation 继续要求精确 service ID，避免改变
既有对账命令语义。GUI 可使用相同公共映射，无 CLI 专属解析数据库。

格式版本从 10 升到 11，继续既有严格拒绝旧版本、不自动迁移政策，
不删除或重建旧状态。旧 preview 状态需要明确后续迁移安排，不能将格式
拒绝误报为丢失服务并自动启动。正式发布前须在用户文档明确此兼容边界。

Registry 基线 36 passed（2.83 秒）；首轮别名与旧 Registry 52 passed
（3.51 秒）；扩大到别名、无 Mux 启动、status/logs/stop-all 共 100 passed
（44.32 秒）。架构与生命周期局部复审通过；UX 复审发现同映射首次竞争
未收敛，已按上述只读核对修复，新增确定性竞争插入与 CLI commit 失回执
回归。新增用例曾因漏写参数在收集阶段失败，修正后最终 8 passed
（22.19 秒），进程正常退出；UX 复核已关闭 P2。Ruff、相关源文件 mypy、
文档轻检和 diff 检查通过。此为别名增量证据，不是完整 goal 的验收结论。

## 94. 无目标服务状态汇总（局部复审与验证通过）

`lmux status` 使用原公共 `snapshot_namespace` 的单事务有界快照，列出
当前 namespace 全部登记服务，包括没有 Mux、没有实例的服务。附带的是
`reservedMuxes` 名称引用，不称作在线 Mux、活动 Tab 或真实进程数量。
顶层明确 `observation=recorded_only`、`liveStatus=not_probed`；完整快照
校验后才输出一个 JSON，不逐服务输出半份成功结果。

没有 namespace 返回空服务数组，不创建目录。不调用 service admission、
coordinator 或连接；不因调用者 cwd 改变服务范围。带 `-t` 或 `--server`
的原详细状态与路径诊断保持不变，logs 仍必须指定目标。别名已经能作选择器，
此增量汇总用精确 service ID 展示，不将额外事务的别名读取混成同一快照。

原详细状态基线 7 passed（6.65 秒）；汇总、详细状态、logs 和公共快照
集合 22 passed（8.96 秒）。三视角局部复审未发现新增 P1/P2，按建议补
数据库缺失/版本不支持拒绝空结果、真实 journal 的 provisional/committed/
stop/clean 序列投影，以及全数据树不变断言；补强集合 10 passed（5.86 秒），
测试进程正常退出。相关源文件
mypy、Ruff、文档轻检和 diff 检查通过。

## 95. 跨边界门禁与使用说明（进行中）

已运行 `make plan-checks`；完整变更仍需架构、相关子系统和安装等门禁，
不能用局部 CLI 通过替代。首次完整 `tests/architecture` 正在运行且已出现
失败。只读架构复核定位 A0/A0.2 两份精确 AppHost consumer 集合漏列相同
七个已批准可选 consumer：`coding/cli/lmux.py`、`lmux_command.py`、
`lmux_stop_all.py` 以及 `coding/managed_bootstrap.py`、`managed_catalog.py`、
`managed_local.py`、`managed_process.py`。已精确补入，不改为目录放行；
core/facade/adapter 禁入及 A0.3/A0.4 规则保持。原完整运行不会被这次编辑
追溯变成通过，两项修复仍需后续针对性验证，其余失败尚待终态报告。

新增 [中文预览使用说明](../../../zh-CN/user-guide/lmux.md) 与
[English preview guide](../../../en/user-guide/lmux.md)，覆盖现有命令、
目录、重连、detach/close/stop 区别、格式 11 拒绝旧版和未完成验收限制。
它们不是正式发布或自动迁移承诺；不引导删除未知实例的控制状态。

静态计数与职责复核还定位到旧 Coding wave-A 行数预算漂移。保留原 core
文件归属，精确记录原 AgentSessionRuntime +42、SessionManager +77、共享
theme 提取 −24，净许可 +95；不是按超限的 81 行反推许可，旧 14 行余量保留。
G12 +84 属于原 Product/catalog 清理与 managed 激活；G14 +205 属于原
catalog 的 factory/未交付会话保管、只读 hooks 和发现校验。对应旧分组预算
分别成为 34181、884、1505，不把这些原 owner 移到豁免分组。

新增上述七个 lmux 文件以完整相对路径组成独立 `LMUX_PRODUCT_SLICE`，
本次受审上限为当前 1579 行，仍参与全部文件互斥分区/计数；补未审
`managed_unreviewed.py` 和 `cli/lmux_unreviewed.py` 留在 core 的防扩散用例。
架构职责复核认可这些精确增量，Ruff 通过；完整测试仍运行，修复后的
针对性验证待原运行结束后执行。这些修改不用于宣布其他失败已解决。

完整架构运行还暴露本机内存压力：一次观测中测试约 599 MiB 常驻、
596 MiB 已换出，物理读取累计约 57 GiB。已将 PR0、CLA0 与统一插件
架构模块的源码缓存改为模块级自动 fixture 在 finally 中释放；模块内
仍复用缓存，CLA0 先清派生调用索引、再清 AST。扫描根、测试和断言均
不缩减。失败 traceback 仍可能持有 AST，此修改不承诺立即降低 RSS，
也不会改变已启动旧进程。该修改 Ruff、文档轻检和 diff 检查通过；
架构只读复核确认正常及失败 teardown 覆盖、无新增 P1/P2，运行验证
尚待完成。A0/A0.2 与 Coding budget 的窄范围修复验证已单独申请执行，
未重复启动全套架构测试。

## 96. 单登记候选自动尝试连接（已实现，运行验证待完成）

裸命令与无目标 attach 的首个公共列表页若恰好一条且未达分页容量，
该条属于 Coding、有 COMMITTED instance、无 stop/clean 标志，则省去
数字选择；仍冻结该观察并走原 resolve 身份复核、Mux inspection、认证
连接与 controller attachment。登记状态不是在线证明，失败不自动启动、
创建、切换候选或重试。多条（即使只有一条 COMMITTED）、pending、其他
Product 与停止状态继续选择器。此增量不代替多候选中唯一在线探测。

UX 设计复核无新增 P1/P2；新增两个真实服务回归要求裸命令及无目标
attach 从不同 cwd 重连且禁止调用选择器。回归先行请求因权限审核超时
未启动，未取得红灯证据。现已实现选择并更新预览说明，补资格矩阵及
裸命令/attach 下 reservation、instance、消失、stop 的确定性变化验证。
原 resolve/inspection/connection 和清理不变；架构与生命周期只读复核
无新增 P1/P2。原 lmux CLI owner 净增 13 行，精确纳入既有分组预算
1579 + 13，不添加路径豁免。扩大后的运行验证已申请，尚未通过验收。

A0/A0.2 与 Coding budget 窄范围运行已结束：19 passed、1 failed
（113.15 秒）。失败运行加载的是旧 1579 上限，但统计到了新 1592 行；
不是 consumer 边界失败。已申请只复验更新后的 Coding budget 模块，
不重复已经通过且未变更的 A0/A0.2 测试。

单候选增量最终 CLI/selector 集合正常结束：74 passed（369.64 秒），
包括两种入口跨 cwd 重连、资格矩阵、选择后的身份/停止变化及握手失败
不重启、不改选和清理。源码 mypy、Ruff、文档轻检与 diff 检查通过。
三视角局部复核无新增 P1/P2；UX 两处说明精度建议已修正：整个命名空间
恰有一条登记才适用，空 namespace 的无目标 attach 报 not_found。
这只证明单候选增量，不是完整 lmux goal 验收；全架构和预算复验仍待结果。

更新后的 Coding budget 独立复验正常结束：2 passed（0.57 秒）。
全架构原运行尚未结束，其余失败仍待完整报告。

## Shared data-root admission delta — candidate, not accepted

The default Embedded writer rollout exposes a compatibility defect: creating
`sessions/project-a` and then `sessions/project-b` is rejected because their
legitimate shared attachment directories are treated as orphaned residue.
Changing the layout or removing the residue check is not an acceptable fix.
The existing per-store v1 witness cannot distinguish a never-created sibling
from a sibling whose root and witness were both lost.

Proposed owner boundary:

- Harness owns a small data-root admission ledger, separate from Session data
  and the application registry. Products select roots; CLI/discovery cannot
  manufacture freshness from an absent pathname.
- Store the ledger under the already selected machine-local store-state root,
  keyed by canonical data-root path and UID. Bind the physical parent identity,
  ledger/lock identities, each admitted store key, and shared attachment-domain
  identities. Do not move transcripts, attachments, or change Session defaults.
- Reuse the existing retained rooted IO and stable nonblocking lease machinery.
  Acquire family admission before individual store admission. Release those
  short initialization locks before normal transcript/blob lifetime operation;
  never acquire them while already holding lifetime writer locks in reverse order.
- Publish a member intent durably before creating its root. A member remains
  recorded after deletion or failure; missing member root/witness is not a new
  admission. An incomplete member blocks that member, not unrelated initialized
  members. Concurrent additions must serialize without losing ledger entries.
- Attachment creation is a separate retained initialization phase: persist its
  intent before creation, then record identities before accepting sibling
  membership. Existing attachment directories cannot be adopted merely because
  their names or parent inode match. The original initializer must retain partial
  resources and report incomplete/unknown outcomes without silently recreating.
- Fresh automatic initialization requires an unregistered data root with no
  legacy store or attachment residue. Existing v1 stores continue their original
  validation; their witnesses alone do not authorize adding new family members.
  Enrolling a legacy family requires a separately specified explicit migration
  operation. Do not silently require migration just to restore a valid v1 store.
- Discovery remains read-only: no ledger repair, membership enrollment, root
  creation, or attachment initialization. Bound ledger decoding and member count;
  exhaustion returns a capacity error rather than evicting historical members.

Acceptance before implementation activation: real default bootstrap A→B succeeds
without layout changes; B root, B witness, and both missing remain rejected;
attachment injection/replacement is rejected; concurrent process additions keep
both members; crashes after intent remain incomplete; discovery creates nothing;
valid v1 restore remains usable without enrollment. Ledger loss/replacement must
also fail closed in the presence of old roots or attachment residue.

Open design checks: exact legacy enrollment authority and command; retained
attachment-initializer handoff; missing-parent creation sequence; capacity values
and lock-order proof. This proposal is not evidence that the sibling regression
or the complete lmux goal is resolved.

Review refinements (still candidate):

- Freshness inspection covers the selected data root itself, the reserved shared
  attachment/lock names, immediate child store directories and their bounded
  transcript/tombstone/owner markers, and matching machine-state witnesses.
  Use no-follow retained directory reads and existing discovery read budgets;
  a truncated or unreadable inspection is unavailable, not proof of absence.
  Do not recursively scan arbitrary workspace/home trees. Exact limits and the
  recognized marker set remain implementation-review inputs, not unspecified
  permission to skip unknown candidates.
- Family, member, and attachment initialization have separate phases. A member
  becomes usable only after its own root binding and the shared attachment-domain
  binding are confirmed. Unknown shared initialization blocks every writer in
  that family; unknown member-only initialization blocks that member. Fresh
  `new` performs all required phases automatically, with no setup command.
- Enrollment must durably upgrade the member witness to reference its family
  before making that member available. Such a witness must never fall back to
  standalone v1 if the family ledger is missing or invalid. An untouched valid
  standalone v1 witness remains usable under its original contract.
- Losing every independent witness together with all roots and attachment
  evidence is outside locally distinguishable recovery: this mechanism is not
  an external backup or an anti-rollback authority. Do not claim recovery from
  that state. Partial loss with surviving family/member evidence fails closed.
- Short-lock admission must hand its confirmed data-root, member-root, and
  attachment-domain identities plus family/member generation to the original
  lifetime acquisition owner. After acquisition and before any write, that
  owner must bind and check the expected objects; it cannot re-adopt whatever
  now occupies each pathname. Retain identity witnesses across the handoff where
  needed to prevent inode reuse. On mismatch, keep the original acquisition
  cleanup responsibility; never acquire the family lock in reverse order while
  holding lifetime locks to obtain a replacement admission.
- Family membership intent takes precedence over a standalone v1 witness,
  including a missing, not-yet-upgraded, or restored-old member witness. A valid
  v1 header is not permission to ignore a surviving family intent. Enrollment
  publication ordering must make this check possible after every crash point.
- Missing data-root creation belongs to the first retained family initializer:
  durable intent precedes no-follow directory creation and parent fsync. Once
  registered, a missing parent is unavailable and is never recreated implicitly.
  Fix lock order as family → member, release both, then transcript → blob;
  shared initialization must not wait on lifetime locks while holding admission
  locks. Unknown shared initialization blocks new admissions, not a claim that
  previously admitted writers have stopped; their original owners still settle.
- Split short admission-lock release from retained directory-witness cleanup.
  The original preparation keeps the confirmed root pins through lifetime
  acquisition and final cleanup. Reuse the original directory/descriptor ledger;
  do not create a second owner or close all admission resources before handoff.
- Every later attachment operation must consume the registered shared-domain
  identity, including the `session-assets` and `.locks` components. Existing
  `create=True` authority-lock paths cannot recreate an enrolled missing domain.
  Acquisition-time checks alone do not protect later deletion or replacement.
- Legacy v1 records contain hashed paths and physical identities, not enough
  information to reconstruct a vanished parent and its child names. Preserve
  v1's exact member-key/root/parent protection; do not retroactively interpret an
  unrelated valid v1 witness as a global prohibition on new workspaces. Ignoring
  an unrelated witness requires strict closed-schema and physical witness/lock
  validation, not a version-label check. Malformed, incomplete, unknown-version,
  or truncated evidence remains unavailable. A v1 parent identity matching the
  originally retained current data-root still forbids implicit enrollment, even
  if its old member disappeared and that parent is empty. A missing parent and
  a different member key cannot be globally attributed using v1 alone: this is
  an explicit format limit, not a recovered historical fact. All v2 family/path/
  member loss and replacement checks remain unchanged. Explicit enrollment is
  still required to migrate an existing legacy shared domain.
- Freeze publication order as family/shared intent → confirmed shared identity
  → member intent → v2 member witness → member root → member completion.
  Family incarnation and member admission ID are immutable identity components;
  the mutable ledger revision only serializes updates. Adding sibling B must
  not invalidate A's existing lease by changing its identity generation.

## LMUX default-owned and presentation budget supplement

Independent architecture review compared the current owners with the validated
`da820585` wheel. The following deltas supersede the earlier unchanged-cap claims
for these exact groups; file inventories and dependency prohibitions remain in
force. This is not acceptance of the overall LMUX implementation.

| Existing group | Reviewed delta | Updated cap |
| --- | --- | --- |
| Coding core | `bootstrap.py` +7, `runtime/agent_session_runtime.py` +5, `session_manager.py` +1 | 34248 → 34261 |
| G16 shell four files | `shell.py` +70, `_shell_screen.py` +22; other two unchanged | 950 → 1042 |
| G11 semantic mux six files | `projection.py` +41; other five unchanged | 600 → 641 |

Coding adds Linux default-owned composition and state-root/maintenance identity
wiring, not storage implementation. The shell adds capability-driven help and
completion, approval receipt revocation and stale-request result isolation, using
the same action and task owners. The semantic projection maps Hosted state into
neutral capabilities; it neither grants authority nor imports native or Product
implementations. No file moves or exclusions are used to reduce counted lines.
The Coding and semantic groups retain their previous six- and twenty-one-line
margins respectively; previously counted capability allowances are not repeated.

The subsequent Coding LMUX seven-file assertion exposed one further unrecorded
creation-receipt recovery composition delta: parser +14 and command +75, raising
1721 to 1810. Relative to the `da820585` wheel, parser is 102 → 116 and command
764 → 810; the command's net +46 includes the old selector's -29 already deducted
in the existing allowance. Do not deduct it twice. The other five files are
unchanged from that wheel. Independent review confirms that CLI only presents
and inspects the original operation, obtains confirmation and revalidates exact
identity through the existing creation owner. Durable history and authorization
remain in AppHost. Retain the exact seven-file group and boundary scans.
