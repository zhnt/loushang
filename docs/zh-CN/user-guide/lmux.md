# Linux lmux 预览

[English](../../en/user-guide/lmux.md) | 中文

本文对应当前开发分支的 `lmux`，不代表完整交付验收已经通过。本文入库时
`lmux` 命令本身仍未提交，从本提交构建的版本尚无该入口；下文命令应按
目标接口理解，而非已发布能力。运行
`lmux --help` 确认安装版本提供哪些命令；旧安装可能尚无本文中的入口。
当前自动后台仅支持 Linux，不提供跨机器连接或 GUI。实际暂存配额接线、
完整 Harnesstui 能力对齐及最终安装/断连/性能验收仍在开发中。

重连时界面只呈现有界的近期历史尾窗，不会一次加载全部历史；未显示的早期
内容并未删除，持久化 Session 历史仍按原存储策略保留。

## 创建与重连

在要执行工作的目录运行：

```bash
lmux new -s dev
```

命令会启动或复用该工作区服务，创建名为 `dev` 的空 Mux 并进入终端。
在界面中用 `/new cwd 工作会话` 创建第一个 Tab；`/help` 显示当前支持的操作，
`/resume` 用于发现已有会话。空 Mux 不会自动调用模型。

输入 `/detach` 只离开客户端，不停止服务。重新 SSH 登录同一台机器后，
在任意目录运行：

```bash
lmux attach -t dev
```

Mux 名是当前机器和用户命名空间内的全局名字，不需要 `server:mux` 前缀。
同工作区的多个 Mux 共用服务，一个 Mux 可有多个 Session Tab。已有控制器
时不会抢占；断连权限释放前可能返回 busy。`attach` 不隐式重启离线服务，
需要重启时显式运行 `lmux start -t dev`；只有确认前代已干净停止，才允许
启动新实例。异常退出或清理证据不足时会拒绝，`start` 不绕过这些检查。

后台服务不依赖原 SSH 终端，已接纳任务按服务寿命继续执行；这不意味着
机器重启、进程崩溃或主机策略清理用户进程后仍能保住执行中的任务。
允许的服务重启恢复持久 Mux/Session 状态，不自动重放丢失回执的请求。

裸 `lmux` 在无 Mux 名称登记时于 cwd 创建默认 `main`，无目标
`lmux attach` 此时报告 not_found。整个命名空间恰有一条 Mux 登记，且
该条属于 Coding、已提交、未请求停止或干净停止时，两条命令直接尝试
认证连接；多个候选使用有界只读探测，按服务认证、逐个读取精确 Mux ID，
不 attach 或申请控制权。仅一项确认存在、无未知候选且集合未变化时自动
选择，否则显示冻结快照的选择器：`n` 下一页、`r` 首页、`f` 显式刷新并
重新探测；翻页不追加探测。探测连接先关闭，最终连接再次认证并核对实例
和 Mux ID。登记状态不保证在线，最终连接失败
不会自动重启或改选；pending 名称登记也不会被当作空列表。
进入终端的命令要求 stdin/stdout 都是 TTY，不支持把 prompt 管道送给 `lmux`。

### 恢复中断的创建

`new`（包括裸 `lmux`）在预留名称前输出 JSON `planned_creation`，包含原始
`serviceId` 和 `operationId`。它**不是成功回执**，也不证明名称预留已提交。
`lmux ls` 同时显示已保留名称的 `creationOperationId`，便于找回原操作。

```bash
lmux create-status --server SERVICE_ID --operation OPERATION_ID
lmux create --server SERVICE_ID --operation OPERATION_ID --continue --yes
```

请替换为原始精确 ID；这里不接受服务别名。`create-status` 和不带
`--continue` 的 `create` 只读取持久事实，不连接、不启动、不签发许可，也不重发创建。
`unknown`（退出码 1）不等于原请求未生效；`created` 只是历史回执，不证明 Mux
仍打开或服务在线。

显式 `--continue` 确认原名称、工作区和操作，可启动或复用同一服务，最多发送一次
同 ID 的幂等创建 RPC，不换新操作、不删除预留、不自动进入终端。非 TTY 继续须
加 `--yes`。已有回执时无需 RPC；否则继续成功后可用 `lmux attach -t NAME` 重连。
原有干净停止和恢复检查仍生效：前代许可缺少充分持久创建历史时拒绝继续，不猜测
可以重放；已关闭释放的操作不能重新占用复用名称。再次 `new -s NAME` 仍是冲突，
不是恢复动作。

## 提前启动服务

```bash
lmux server start --name build --workspace /absolute/path/to/project
lmux status
lmux status --server build
lmux logs --server build --limit 20
```

将示例路径替换为已有工作区。`server start` 不创建 Mux 或 Session，可在
非 TTY 中调用；`--name` 可省略。成功结果包含精确 `serviceId` 和 `instanceId`。
同别名、同工作区重复启动会复用；别名绑定其他工作区，或同服务使用第二个
别名时会报冲突，不自动改绑。服务别名和 Mux 名是两个独立名称空间。

显式限时诊断使用 `lmux server start --trace-for 60`，范围为 1–3600 秒。
期限从命令准备时计算，不从服务就绪时重新计算；仅本次新启实例能够应用，
复用服务不会替换或续期原 trace。内容限于有界耗时聚合和固定问题码，不含
提示词、回复、工具正文或凭据。

JSON 将服务 `service_ready` 与 `trace.status` 分开：`applied` 仅证明历史
配置成功，不保证持续写入；`expired` 表示该配置已到期；
`not_applied_reused_instance` 表示本次请求未配置被复用的实例；
`not_confirmed` 表示启动预算内未确认匹配事实；`observation_failed` 使用
独立安全 `errorCode` 报告观察失败，同时保留已认证的服务和实例结果。
`deadlineMs` 使用本机单调时钟，不是 Unix 时间。显式请求 trace 时，只有
`applied` 返回退出码 0，其余 trace 结果返回 1，即使服务已经就绪。
trace 失败不会停止已就绪服务。

`lmux ls` 列出 Mux 名称登记；`lmux status` 也能列出没有 Mux 的服务。
状态标注 `recorded_only` / `not_probed`，不是在线检测。日志读取只提供有界
生命周期尾部，不是完整历史，也不包含对话正文。诊断命令不会启动服务。

## 三种结束方式

| 操作 | 影响 |
| --- | --- |
| 界面 `/detach` | 只离开客户端，服务与会话继续存在 |
| `lmux close -t dev` | 确认后关闭该 Mux 及其活跃成员，保留 Session 历史 |
| `lmux stop --server build` | 确认后停止该服务，影响它承载的全部 Mux |

`lmux stop --all` 会先冻结本命名空间的目标并确认，不是停止机器上所有
Loushang 进程。非交互 close/stop 必须显式加 `--yes`；它不代表强杀或绕过
清理。无目标 stop 不会按 cwd 猜测。未完成关闭返回的 operation ID 和后续
命令应原样保留，不自行换 ID 重试。历史 close 对账命令仍要求精确 service ID。

## 默认目录与升级注意

- 管理状态及有界生命周期日志：默认 `~/.loushang/lmux/machines/<machine>/`，
  服务文件按精确 service ID 隔离；`lmux status --server build` 可查看实际路径。
- 认证连接与运行控制：平台 runtime 下的私有 `lmux` 命名空间。
  `LOUSHANG_RUNTIME_DIR` 可显式覆盖，不要把这里当作可随手清理的缓存。
- 持久准入见证：`$LOUSHANG_HOME/state/managed-deployments/` 中保留原部署
  身份与初始化记录（默认在 `~/.loushang/state/` 下），同样不是可清理缓存。
- 实例临时根：默认位于服务目录的 `tmp/<instance-id>`；显式
  `LOUSHANG_TMPDIR` 优先。当前这不等于所有工具输出都已受强制磁盘配额管理。
- Session：沿用原 Session 存储策略，默认 `$LOUSHANG_HOME/data/sessions`；
  `cwd` 和 `user_home` 是发现范围，不是迁移会话到 lmux 目录。

`LOUSHANG_HOME` 默认 `~/.loushang`。重连时须使用相同用户、机器及目录覆盖；
切换这些设置会选择不同命名空间，不能用于绕过旧实例的停止或清理。

当前开发版受管 Registry 格式为 **14**。旧预览格式会明确拒绝，当前没有
自动迁移命令。不要删除 registry、锁、runtime 或改版本号来“修复”此错误。
保留原状态，使用匹配旧格式的版本处理旧服务，并等待明确的升级方案。
这不影响旧 `loushang-mux` 显式参数入口；旧入口不会自动登记或接管为受管服务。

开发与验收状态见 [lmux 合同记录](../../internals/architecture/apphost/lmux-contract-m0.md)。
