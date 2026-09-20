# lmux 无目标连接：公共只读探测接线

状态：公共 operation 首版及 CLI 接线已实现，定向验证/复核中，尚未验收。补足既有 managed-service 设计中的
“多候选中唯一在线 Mux 自动进入”，不替代完整交付验收。

## 边界

`ManagedDiscoveryV1` 仍只读登记事实，不把 COMMITTED 改称 ONLINE。
新增 AppHost 公共探测 operation，Coding CLI 只负责交互和 Product 过滤；
未来 GUI 可调用相同探测，不依赖 Coding 或 Harnesstui。

输入为已打开的 namespace/registry、Product、原绝对期限，以及由 composition
冻结的 runtime_root、endpoint 和 expected_application_id，不重新读取环境。
公共探测不硬编码 Coding
端点；认证后精确匹配 lease.application_id，read_mux 响应也须匹配冻结
Mux ID，Product 相同不等于任意 Application 均可信。使用现有
`snapshot_namespace()` 在一次事务内冻结完整有界候选，不跨分页推断唯一。
输出只携带冻结 reservation、instance、creation Mux ID 和封闭观察结果：

- `authenticated_present`：原实例连接认证成功，原 client 的 `read_mux`
  确认精确 Mux ID；不调用 attach，不取得 Tab 写入权。
- `recorded_ineligible`：登记事实证明不参与本次选择，例如干净停止。
- `not_present`：原实例给出精确 Mux 不存在的协议结果。
- `unknown`：争用、超时、鉴权失败、损坏、实例变化或证据不足。

无 instance 的 reservation、PROVISIONAL、未结算 ABORTING 均为 unknown，
不得据它们排除候选后判断唯一。Product 过滤在初次冻结和最终复核使用
同一冻结规则；同服务多个 Mux 共用一次探测认证，逐个精确 read_mux。

不得将任意连接失败统称 offline。探测不 spawn、start、stop、create、
恢复 Session 或修改名称登记；状态结论不是未来在线保证。

## 所有权和 CLI 接线

采用值返回的两阶段接线，避免同步选择器跨 loop 保管已认证客户端：

1. CLI 同步准备阶段保管原 probe operation；probe 在专属 Runner 内执行。
2. probe 在 open/prepare 前保管原 journal 和 connection，使用只读准入，
   全部依赖借用同一 registry。按服务顺序探测并及时结算，避免候选数扩大
   导致同时打开大量 fd。每次 IO 使用原总期限的剩余预算，不续期。
3. 返回同步选择器前，必须结算全部连接和 journal；只允许值跨 loop。
   取消、提交回执丢失或 close 失败仍由原 operation 保管，未结算不得
   关闭 namespace 或启动下一阶段。禁止用第二个 owner 掩盖未知清理。
   取消公开 waiter 后须在原 Runner 重新加入原 operation；原任务/原生
   回执未结算时禁止退出 Runner 上下文或调用 Runner.close，不能依靠其
   自动取消收尾。永久 unknown 沿已有专用 CLI cleanup_incomplete 进程
   终止策略处理，不带着未结算 owner 返回可复用的嵌入式调用方。
4. 唯一 present、其余候选无 unknown，且最终候选集合复核未变化时可
   自动选择；否则展示选择器。复核比较完整 reservation、instance、phase、
   stop_requested 和 cleanly_stopped，不因无关 trace
   回执版本变化误判集合变化。选择器 `n` 下一页、`r` 首页只遍历本次
   完整快照，不查询新页或追加探测；`f` 显式刷新才重新冻结并探测完整
   候选。刷新完成前旧 present 标签不可用于自动选择。
5. 最终原 CLI Runner 创建新的精确连接并重新认证，复核 reservation、
   instance 和 Mux ID，再启动 Harnesstui。失败不改选、不重启。

两阶段会增加一次认证，但能保留现有同步选择器，并明确清理边界。
后续复用连接必须将整个选择流程迁入同一 Runner，不允许跨 loop 转移。
探测和最终认证分别计时。总预算耗尽后未探测项标 unknown，不冒充已探测。
探测期限到达后不再开连接、发请求或复核。清理另用原 owner 首次关闭时
冻结的独立结算预算，超时保债；该预算不延长探测窗口。原生 IO 不可
抢占，因此不承诺无条件硬墙钟上限。公共 operation 本身不退出宿主进程，
宿主负责保管未结算任务；只有专用 CLI 外层可应用上述终止策略。
界面将 present 描述为“已认证确认 Mux 存在，尚未申请控制权”，不保证
最终可进入或取得写入权。

## 认证状态例外

只允许一次合法 trace 事实发布跨过认证：原 trace 为空、新 trace 非空、
revision 恰增加一，其余完整 state 不变。停止、身份变化、其他 revision
变化仍拒绝。该窄修已实现，相关回归待执行，不能据此认定探测完成。

## 验收

- 两真实服务一干净停止，异目录 attach 自动进入唯一在线 Mux，不读选择器。
- 两在线 Mux（包括同服务的两个 Mux）仍选择；pending/unknown 不误判唯一。
- 一 present 加一 pending/超时必须选择；同服务双 Mux 只认证一次，
  不影响另一个客户端的控制权；翻页无 IO，刷新不混入旧标签。
- Mux 不存在、认证失败、超时、候选增删/换代、分页容量边界均安全处理。
- 探测不 attach，不释放或取得其他客户端写入权，不改变 Session 数。
- 取消、原 prepare 未返回、close 失败、原生回执丢失：依赖保管与退出正确。
- 首项耗尽期限后后续服务零原生准入；取消 prepare/close waiter 不丢原
  任务；全部值已产生但末项 close 失败仍禁止进入选择器或最终 Runner。
- 最终认证失败不换目标；新旧入口、单候选流程和非 TTY 前置拒绝不回退。
- 设计/实现复核后，再以真实安装环境验证额外认证的首用成本。
