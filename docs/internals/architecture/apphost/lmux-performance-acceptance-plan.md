# LMUX M4 Linux 性能验收增量

状态：accepted（2026-09-22）。`managed-mux`、首次 Product 使用、长历史
warm 与换代 restore 的正式 A/A 证据均已取得有效 pass，完整三视角评审无
未解决 P0/P1/P2。该结论关闭 M4 测量与回归资格门禁，不宣称性能提升；
ARD-004 的 30% 以下回归不可检出限制继续适用。历史失败、诊断和实施过程见
[推进记录](lmux-managed-output-capture.md)。

## 已取得冻结安装功能诊断：运行中真实 PTY 突然断连

生命周期专项复核建议在原测试 `PosixPtyDriver` 增加窄接口
`hangup_transport(timeout)`，不另建进程 owner，不使用 `terminate_tree`
作为断连刺激。原 driver 仍保管前台 Popen 与 reader，并负责最终结算。
此为真实 PTY transport hangup（slave EOF/EIO）而不是对 SSH 协议本身的
测试；当前启动方式没有建立 controlling terminal，不能声称一定发 SIGHUP。

实现约束：与 close 串行，先 fence write/resize、通知原 reader 停止，再
在期限内 join；不得持 writer lock 等待可能回应终端查询的 reader。reader
停止后单次关闭原 master，不保留 dup master。关闭失回执记录 unknown，
后续 close 不得再次关闭可能复用的 fd，也不得声称已干净结算。hangup
不提前设置整个 driver closed；前台退出和其余资源仍由原 driver 处理。

保持正常 `observed_terminal` 的终端模式/光标恢复门禁不变。突然断连使用
窄专用 context，要求原客户端自主退出、reader 结算、无 fallback termination；
最后 master 关闭后 termios 标记为不可观察，不伪造恢复成功。重新连接仍走
正常终端门禁。失败或超时可由原 close 回收，但样本必须保留为失败。

真实破坏传输与正常 detach 的退出码分开验收：master 关闭后客户端必须
在期限内自主退出/被原 owner 回收，但不强求退出0；记录实际非负退出码及
`client_exit_clean`。输出flush或termios对已销毁终端失败可能导致非零，
不能为满足测试吞异常。超时、信号终止、fallback及未知清理不能因此通过。
这只记录客户端结算，不表示客户端正常退出或后台任务成功；后续原任务/
实例连续性、中断/下一轮及精确stop事实必须独立满足。正常detach仍要求0。

验收顺序：delayed 任务已接纳且 producer 未结束 → 关闭原 PTY transport →
原客户端结算 → 认证查询同实例/成员/Session 仍 running，producer 未结束 →
另一 cwd 正常重连 → 中断原调用并验证 producer 结算 → 下一轮唯一回复 →
精确实例 stop、三事实与外层 owner 结算。另补单次关闭、fd 复用失回执、
reader 查询在途和 join 超时反例。原 driver 与独立 abrupt context 已实现，
入口为 `managed-product-hangup-interrupt-next-turn`，仅诊断、保持 valid=False。
driver/context 真实 EOF 及接线负测已通过。当前冻结安装的
`managed-product-hangup-interrupt-next-turn-673crff_` 已验证断连后重连、
中断与唯一下一轮回复；`managed-product-hangup-natural-completion-ypei8ch9`
已验证原任务断连后自然完成、异 cwd 取回结果且不重发原请求。两者均完成
精确实例 stop 和外层 owner 结算；原客户端自主退出120，如实标记
client_exit_clean=False，不宣称终端恢复成功。结果均为功能诊断、valid=False，
不能充当正式性能样本或完整 SSH 协议测试。证据位置见推进记录。

## 边界与复用

落实主设计 §9/V10，不以 pytest 总耗时或旧 G18 数字替代 lmux 数据。
沿用 `scripts/dev/measure_g18_native.py`、`tests/coding/_g18_native_probe.py`
及原安装槽、配对顺序、断点恢复、来源/字节核验和 PTY owner。
增加显式选择的 managed 场景；原 CASES 默认集合与已有报告含义不变。
观察器固定安装，与被测安装分离；不在 Product 加计时开关或跳过权限检查。

## 分开回答的问题

1. `managed-mux`：实际安装的短入口 `lmux new -s perf` 冷启空 Mux；
   首个完整可用空态帧、首次命令补全、`/new user_home` 成员可交互帧、
   第二个 Tab 建立、detach、从另一 cwd 暖 attach、重连首帧及最终停止。
   首帧不是 Session ready；本次 membership 成功完成，且输入后的完整当前
   帧显示预期新 member/session 才记 ready。pending 消失单独不足以证明成功。
2. `managed-product-first-use`：可信测试 Product 经真实受管启动/IPC 路径，
   分别记录首次合成模型回复、审批、工具效果与中断，不调用外部模型。
   必须确认现有启动合同能注入该测试 Product；不能偷换成 legacy serve。
   若现有合同不支持，明确缺口并评审最小测试组合，不能为测量开放任意启动路径。
3. 长历史：通过公开会话行为预置相同历史，记录输入规模与内容摘要；计时前
   完成种子准备。暖 attach 同时验证当前 viewport 历史可见、成员身份正确，
   不以空壳 footer 冒充历史同步完成。不编辑受管 registry 或伪造 receipt。

补全采用实际键盘输入与当前屏幕建议项的完整帧见证；不能仅测 provider
调用耗时。模型/工具采用确定性测试实现，报告明确不含网络服务延迟。

## 证据合同

- 所有用户动作使用观察器单调时钟，保留冷启动到首个成员 ready 的端到端值，
  同时拆分阶段；服务内部 ready 不由终端出现推断。
- 前台进程逐次记录精确 executable/argv/cwd；status 仅为 recorded_only
  登记补充，不证明存活。冻结原 service/instance，通过公共 probe 的精确
  实例认证只读查询核对 application/Mux 身份；成员另由原精确连接只读
  查询核验，不 attach/夺控制器。原 lease/journal 结算后才交付纯值证据。
  不将前台 spawn 数当作全部后台进程数。
- 跨 cwd 重连用实际不同目录并核验同一实例/成员；为新场景增加明确 cwd
  校验分支，不放松其他场景的固定 cwd 规则。
- 首次补全、成员、模型、工具必须基于输入后完整当前帧或确定性效果见证，
  排除历史输出命中。失败、超时、清理债务与预热均保留，不筛掉慢样本。
- detach 后认证确认服务存活；最终仅 stop 本样本私有命名空间，结算失败
  则样本无效，保留有界诊断。记录完整 termios/光标/粘贴模式恢复。
- 延续原 owner 的异常清理和总期限；不新增裸 PID kill 或无主后台进程。
- 最终成功要求原实例的退出、应用清理、native scope 结算三事实，以及原
  采集 owner 的物理结算。外层强制回收不能补成正常 stop；带债时不得换
  安装槽、删样本根或写可恢复检查点。首次 Product 场景必须先冻结可信
  受管测试组合；旧 legacy `_product/_serve` 不能作为它的替代证明。

## 比较与判定

先在同一冻结 wheel 做 A/A 验证采集稳定性，再做冻结版本的 A/B；两侧均须
支持被选 managed case，不对不含 lmux 的旧版本强行补入口。冷启与暖复用
是不同场景，可并列报告，但不能直接宣称为代码优化百分比。
实施前须补齐 managed 独立里程碑闭集、每项起终点、第二 Tab 暖 new、
spawn 至首次模型的累计值以及长历史规模/种子，作为本设计的评审增补。
原 comparison 现已接入 managed-mux 九指标的独立比较分支与拒绝测试，
旧 NATIVE_METRICS 七项保持不变；首次 Product 八指标闭集及组合校验已接入
（见下方增补），最新安装组合预验仍在进行。长历史正式比较接线及其限定
三视角复审已完成；首轮冻结 A/A 在首次预热失败，正式比较尚未取得有效结果。
不能直接把新 case 的诊断采集成功记为比较通过。
正式采集沿用原20对样本、稳定性与回归判定规则；小样本只作诊断，任一
失败/缺失/清理债务不允许通过过滤变成 pass。指标增补通过前不得关闭 V10。
沿用现有采集器预热、配对与恢复策略，报告均值、分位数、样本数、
失败率及逐样本原始里程碑。未冻结正式指标前不承诺提升百分比。
短入口、首次使用、长历史均有有效配对证据，且无首次使用成本迁移与终端/
生命周期回归，才可关闭 V10；单独完成 managed-mux 不等于 M4 完成。

## 实施门禁

三视角设计通过后修改原采集器，先补里程碑缺失、错误安装/cwd/实例、陈旧帧、
未结算与恢复配置漂移的拒绝测试，再跑真实安装采集。默认旧场景回归保持。
测量结果与本设计分离存放；三视角实现复审必须同时检查原始证据及采集代码。

## 第一个可实施增量：managed-mux 指标候选（待复核）

该增量只关闭真实短入口的测量接线缺口，不关闭整个 V10。单独的比较入口
仅接受本场景精确指标集合，调用原 `_g18_comparison._compare` 统计策略；
不扩充旧 `NATIVE_METRICS`，不改变原七项全量判断，也不另写统计实现。

| 指标（均为 seconds） | 起点 | 终点见证 |
| --- | --- | --- |
| cold_frame | spawn 短入口前 | 首次完整空态帧，perf Mux 名与可执行 /new 提示 |
| first_completion | 输入 /he 前 | 输入后的完整当前帧，补全面板候选行显示 /help；不匹配常驻 footer |
| first_member_ready | 提交 /new user_home First 前 | 成功新增的精确成员/Session 与当前帧一致 |
| cold_through_first_member | 同 cold_frame 起点 | 同 first_member_ready 终点，含首个补全操作 |
| warm_member_ready | 提交 /new user_home Second 前 | 第二个精确成员出现，第一成员身份不变 |
| detach_settlement | 输入 Ctrl+B d 前 | 原前台退出0且原 PTY 完整恢复 |
| warm_attach_frame | 不同 cwd spawn attach 前 | 同实例/Mux的两成员完整当前帧 |
| reattach_detach_settlement | 重连端 Ctrl+B d 前 | 重连前台退出0且其 PTY 完整恢复 |
| stop_settlement | 提交私有命名空间 stop 前 | 三事实 stopped 与样本采集 owner 物理结算 |

表中指标实际键统一添加 `_seconds`。两次会话命令均通过原作用域目录查询
取得其 scopeFingerprint；不能凭 First/Second 标题作为唯一身份见证。
认证探测安排在首成员终点之后；原终端收到并呈现成功结果才是终点，
额外探测用于判定样本真实性，不倒填时间。cold_through_first_member 是
连续墙钟窗口，不扣除中间探测、清空补全或其他操作的任何开销。
stop_settlement 由外层 collector 完成：probe 发布 stop 起点及三事实
观察，原 owner.run_python 成功返回并物理结算后，collector 补记终点，
再验证完整指标集合。probe 内不能声称自身已物理退出；异常/强制回收/
债务不能产生成功终点，也不得为取时间提前释放 owner。
补全后通过真实键盘取消建议并清空输入，再提交 /new；无固定 sleep。
每侧每块一对预热、十对正式样本，共两块20对；warm/absent 字节码条件
独立比较。原稳定性、回归阈值原样沿用，无额外提升目标；均值为描述统计，
不改变以配对完整性及原中位数规则作结论的合同。

首次模型/工具和长历史指标仍须独立补齐并评审；不以此表覆盖它们。
已检查 `_managed_product_child.py`：它能组合真实 ManagedChildBootstrap
与 CodingManagedLocalCommand，但 `_managed_starter.py` 消费预置 journal
与固定测试机器身份，且 Product tools=[]。因此不能直接拿该旧 fixture
证明短入口自动创建/发现或首次工具；后续复用组合点，不能复用伪造准入种子。

## 首次 Product 使用：可信测试组合候选

状态：固定测试组合与若干功能诊断已实施、局部评审并在冻结安装运行；
正式性能 case、指标闭集与完整配对仍未完成。具体实测项见推进记录，
不能以诊断 valid=False 的报告关闭本节。与 `managed-mux` 分开报告；
不能用本节测试组合替代安装短入口验收，也不能把合成模型耗时解释为在线
供应商延迟。生产入口不增加任意 executable、模型注入或测试环境开关。
本节结果标为“真实受管基础设施＋固定测试 Product”；测试父端启动到
回复的累计值不是生产 CLI 启动耗时。观察器、测试 helper 与被测安装分别
冻结来源，禁止从活跃工作树导入 Product。

测试父端从原 `resolve_managed_defaults` 得到真实机器与默认 namespace，
按 CLI 原有顺序执行 namespace admission、精确命名意图 reservation、
service admission 与 `ManagedMuxCreateOperationV1`，由原 Coordinator /
Starter 完成新服务登记和进程交接。使用已有
`ManagedLaunchRequestFactoryV1` 组合固定且冻结的测试 child，不预置
journal、实例 ID、native identity 或认证 receipt。
父端在首次 IO 前保管 namespace/journal/create operation；取消或丢失
回执仍结算原任务，不重发 create，也不提前关闭被借用的存储。
request_factory 使用被测安装的 Python，保留原 invocation、继承 descriptor、
cwd 和环境覆盖规则；固定 child 的摘要进入 helper 证据，不使用观察器
安装的 Coding 执行被测 Product。

父端实现同样复用原流程：固定测试入口只接受 `new -s perf`，核验被测
安装后，在专用测试进程内替换 `lmux_command` 的启动请求工厂名称并调用
原 `lmux.main`，finally 恢复。固定工厂先生成原生产 request，仅把 argv
入口换为同一被测 Python `-I` 和冻结 child 脚本；不复制准入、连接、退出
或清理代码。观察目录由驱动在计时前明确准备，不作为登记或权限事实。

child 复用 `ManagedChildBootstrapV1`，仅在
`CodingManagedLocalCommandV1(model=..., stream_fn=..., tools=...)` 选择
确定性模型与测试工具。保留生产配置的 store_state_root、managed Mux
binding、output capture factory 与 diagnostics；模型替换不能顺便删去
会话存储、输出管理或生命周期成本。测试工具走真实授权与执行接口，
拒绝审批时不得产生工具效果；成功效果必须与本次调用 ID 对应且只发生一次。
child 保留原 socket 收养及 `open → bind → run_process → close` 顺序，
保留原失败退出与永久 pending 处理，不另建简化的事件循环或清理 owner。
拒绝审批同时核验实际执行后端未进入、无附件及其他工具效果。

子端实现进一步收敛为固定测试脚本调用被测安装的
`coding.managed_process.main(argv)`，只在该测试进程内将模块中的
`CodingManagedLocalCommandV1` 构造名称替换为原类的固定 partial。
保存原类，原 launch/output_capture_factory 参数不变，返回真实原类实例；
不替换 bootstrap、journal、认证、授权或清理方法。以此复用生产全部
构造和异常出口，不复制子端生命周期。测试须覆盖正常及构造失败路径。
不能直接导入 `_hosted_product_child.py`：其顶层 `install()` 会修改生产
类方法。确定性模型/工具须独立且无导入副作用，固定 helper 摘要纳入来源。

候选观测窗口：

- 提交首条输入到当前帧完整预期回复可见且对应 turn 已完成；同时保留
  新服务启动到该终点的累计值。字符串命中或流式 draft 含全文均不足。
  本指标仅称“用户可见回复完成”：新Session、本轮唯一nonce，无额外
  输入或中断；同一完整当前帧核对回复与精确目标Tab非running，且无
  快照失效、错误或unknown。随后显式detach再用原public attach/snapshot
  核验同instance/Mux/member/Session、恰一正式预期assistant记录及
  running=False。快照需要控制器，不能在终端仍连接时偷偷attach观察。
  后验只能接受/否决，不修改先前时间戳，不证明该时刻native物理结算。
  必须用“完整文本已流出、最终消息仍阻塞”的负例验证不会提前记完成；
  无须强求快速请求曾实际渲染过running帧。
- 提交工具请求到待办提示可见、真实 F2 或 `/question` 打开详情到完整
  详情展示、确认审批到确定性工具效果和完成结果可见，三段分别记录。
  保留动作起终点，不把用户或观察器操作等待隐藏成模型/工具执行耗时。
- 提交可控长任务到接纳见证，再中断到执行槽可再次使用；接纳和清理必须
  有协议/效果证据并确认原 producer/task 结算，不能仅靠 idle 文案或 Ack。
  终点还须同一 Session 完成下一次唯一 ID 的调用，而不只是再次被接纳；
  下一次调用成功本身也不能替代原执行及 native IO 的清理见证。

观测均复用原 collector 时钟、PTY 当前帧与精确实例只读核对。先冻结
字段闭集、每项终点及负测，再扩展显式 case；不得放松原默认七项和
managed-mux 九指标合同。原理验证不直接进入正式性能比较。

长历史另作种子方案：通过公开会话调用生成固定规模与内容摘要，完成
种子后再计暖 attach；核对持久化的原 Session 身份与当前 viewport 中的
指定历史内容。诊断配方的条数、字节数、轮次与摘要已实现并取得旧安装单次
通过证据（见下）；正式配对及最新安装重验仍未完成。
暖重连与停止后重新加载分开测量；不通过直接填 JSONL 或复制 registry
替代公开种子流程。工具实际 handler 产生独立效果见证，模型回显相同
字符串不算执行成功；审批须经过真实待办、详情展示与回应。

### 长历史实施合同（已有局部复核与安装诊断，未完成正式验收）

采用固定测试Product，不连接网络模型；沿用受管启动、公开AppServer请求、
原evidence owner及PTY采集器，不新增存储写入接口。历史配方
`lmux-history-128x2048/v1`：128轮串行调用，每轮USER文本为
`history NNNN`（0000至0127，12个ASCII字节），ASSISTANT文本恰2048个
ASCII字节，含轮次、Markdown标题/列表/代码块及唯一尾标记，其余为确定性
正文。配方实现必须给出逐字节规范和测试向量后才冻结，不能采集后修改。
256条USER/ASSISTANT文本合计263680字节；不把序列化JSON或元数据计入该
文本规模。摘要为按顺序的`[kind,text]`数组，kind严格为`user`或`assistant`，
以UTF-8、`separators=(',', ':')`、`ensure_ascii=False`的JSON编码计算SHA-256，
编码末尾不加换行，文本内换行固定LF。配方须带独立已知摘要向量；记录
配方版本、轮次、记录数、文本字节数和摘要。此规模只代表约258KiB文本
及有界尾窗呈现，不声称全历史同时进入终端。

配方实现候选为`tests/coding/_lmux_history_recipe.py`：每轮正文重复
`history-NNNN deterministic evidence. `并按字节截到固定尾部之前；尾部为
空行、二级标题、带轮次列表项、text代码块和`LMUX_HISTORY_NNNN_END`。
换行及空行以该纯函数和独立固定向量测试为准。完整256条规范JSON的候选
SHA-256为`00e1c01bb0a4603b94f5fbd70ea802f24a9389471893e5883310ba7c0c0fbb41`。
已测精确规模/摘要及早期记录删改而尾窗不变的拒绝分支；公开 seed 接线、
真实终端尾窗与 Markdown、原服务干净停止后重新加载均已在 wheel
`79c3deda35aed72100c6658d52a725d581cae67ff3045a5e1c7f24bfff518990`
取得单次安装诊断通过。记录位于 `.artifacts/lmux-history-install.LWJpGM/`
下 `history-warm-gtf_wyxv` 与 `history-warm-1_8nc_ot`。它们仍是
valid=False 功能诊断，不是正式性能样本，也不覆盖后续生产修复。

种子准备不计入暖attach耗时，但单独记录真实耗时和终态。通过现有认证
连接attach取得controller generation，逐轮start_turn仅发送一次，必须先
await合法Ack，但Ack只代表请求应答。随后在同一controller和同一本轮
绝对期限内只读轮询snapshot，要求running=false、同一完整Session身份，
尾窗中本轮USER/ASSISTANT精确且唯一，才发下一轮；旧轮idle不能满足本轮。
实际Coding snapshot限制总文本16384字符、至多128条并可包含省略标记，
不能要求每轮返回完整前缀，不能为测试调大限额。完整历史摘要使用独立
公开`loushang.harness.transcript.load_agent_transcript_file(path,
read_only=True, max_bytes=2097152)`，通过原typed codec及
`AgentTranscriptProfile.default().replay(records).messages`核对完整消息。
从本样本明确私有canonical Session根定位，header与已认证完整Session
身份必须匹配，不按mtime最新文件或标题猜选。精确stop和本地owner结算
后才只读持久文件；超2MiB失败而不是临时放大上限。禁止默认repository
加载引入锁写入，不用bundle export，也不以测试私有JSONL解析兜底。
这是canonical持久化证据，不伪称AppServer全文导出；合法尾窗省略不等于
持久历史丢失。
丢回执、超时、重复/缺失/额外本轮记录直接
使样本失败，不重发，不修复JSONL，不复制registry或伪造运行状态。准备
完成必须detach并关闭原连接，才启动计时的真实PTY。原helper从attach前
即保管连接；失去attach/detach回执不能凭无attachment ID称clean。任何
seed/读取/关闭失败停止后续轮次及计时，保留失败并交原精确stop/outer结算。
候选实现预算：全seed最多600秒，每轮最多40秒并受全局剩余期限约束，
每轮最多80次snapshot，间隔0.1秒；初始fresh检查单独一次且计入全局预算。
每次轮询先沿同一attachment/generation读取事件，最多64次请求、每次请求
上限64条；协议可能每帧只返回1条，只有空批次才完成消费并读取snapshot，
短批次不能视为空队列，次数耗尽直接失败；
二者共用本轮绝对期限。事件只用于消费正常客户端mailbox及校验当前身份/
错误，不代替snapshot成功判据。失回执、取消、lagged或身份错误直接失败，
不重新attach、不重发turn、不扩大默认mailbox，且不新增后台读取任务。
所有操作含sleep均使用同一本轮绝对期限，poll不刷新期限。读取条数和文本
受现有snapshot上限约束。这些仅为测试侧seed预算，不放宽生产操作期限。
外层连接观察器的既有短deadline尚未接入该长流程，不能绕过原owner直接
宣称真实播种可用；需显式整合并复审总预算/关闭语义后再开启采集。

分开两个显式场景，均使用独立新根、同配方公开准备，不混合统计：

- `managed-history-warm`：服务保持运行，异cwd实际`lmux attach -t perf`。
  末轮结尾布局须冻结在100×30终端的指定viewport内，同一当前帧必须验证
  Markdown标题及列表/代码块的预期呈现、末轮尾标记、正确成员与idle；
  尾标记存在但Markdown退化原文不算完成。从实际spawn到该完整帧为
  `history_frame_seconds`；随后固定键盘补全到可见建议项为
  `history_completion_seconds`。正常detach、四类终端结算、同一原生进程
  身份及有界尾窗后验、独立canonical全史摘要、精确stop/原owner结束均是
  有效性前提。
- `managed-history-restore`：公开准备后先精确stop且原owner本地结算；
  保留原成员，使用`lmux start -t perf`后`lmux attach -t perf`，通过现有
  Hosted continuity/Catalog恢复原Session，不额外`/resume`已恢复会话。
  本场景恢复原continuity持久Mux/member引用，而非新建替代引用：
  `appservice/continuity.py`的原编码/解码保存`muxSpaceId`、`memberId`及
  Session完整身份，恢复收养后必须通过新代认证重新核对它们一致；不得
  跨代复用旧attachment/controller generation或旧服务连接。要求新
  service instance/native identity确实不同。从start实际spawn到attach历史
  完整可见帧记`restored_history_frame_seconds`，覆盖两进程及中间等待的
  连续墙钟时间，保留两个原owner；不得只测attach而称为重启恢复耗时。
  不把进程重启描述成原进程仍在。固定测试父入口白名单支持`new -s perf`
  与`start -t perf`，仍只替换原request factory，
  不加生产启动开关，不用私有存储注入代替恢复。
  old/new两代各自保留不可变身份和原stop/adopted owner；同一namespace、
  service配置及Session数据根不得切换。old停止三事实与全部连接本地结算
  后才spawn新代，不重置旧stop_attempted或复用旧owner。PID可复用，但
  完整native身份须变化；new代最终精确stop和外层结束不能由old成功替代。

两个场景复用原统计规则，独立A/A再A/B；完整单次预检不等于配对通过。
必须补负测：错轮次/摘要/字节规模、仅footer或旧帧可见、历史截断、Ack后
仍运行、身份替换、seed连接未关闭、终端未结算、重启后沿用旧进程身份。
在完整合同及实现评审通过前，不把这些case加入正式CLI可选集合。
另补正确尾标记但Markdown原文/布局错误，以及尾窗正确但早期canonical
记录被删改；必须分别由当前帧和独立全史摘要拒绝。

## 正式首次使用组合：字段闭集增补（三视角设计复核后修订）

架构、生命周期、UX 三视角确认该闭集可实施；复核指出的终端计数遗漏
已改为逐个实际终端验证。此处为设计结论，不表示实现或正式配对已完成。

沿用一个原 collector 样本及其外层 evidence owner，显式 case 为
`managed-product-first-use`。顺序执行 reply、approval、interrupt 三个独立
fresh 子场景，各自使用私有根、新服务及新 Session；前一场景精确停止且原
本地资源结算后才能进入下一场景。不把一次普通回复后的暖 Session 当作
首次工具，不将不同服务的分段耗时相加伪称连续墙钟时间。每个子场景保留
原 first_reply / observed_terminal / AdoptedLeader / exact_stop 生命周期。
既有诊断入口和 valid=False 含义不变，长历史另行验收。

候选精确八指标（键均加 `_seconds`）：

| 键 | 起点 → 终点 |
| --- | --- |
| visible_reply | 首条输入写入前 → 唯一回复及 idle 的完整当前帧 |
| fixed_entry_through_visible_reply | 固定测试入口 spawn 前 → 同一回复终点，包含成员创建和认证观察开销 |
| approval_pending | 工具请求写入前 → 同目标待办完整当前帧 |
| approval_details | 打开详情前 → 完整详情当前帧 |
| approved_tool_reply | 批准写入前 → 工具结果及 idle 完整当前帧 |
| interrupt_through_idle_and_producer | Ctrl+C 写入前 → idle 且原 producer 结算见证核验完成 |
| next_reply | 下一轮唯一输入写入前 → 该轮唯一回复完成当前帧 |
| interrupt_through_next_reply | 同 Ctrl+C 起点 → 同下一轮回复终点，包含中间核验和输入准备开销 |

八指标不包含在线模型延迟；固定入口累计不是未经测试替换的 CLI 启动
指标，中断终点也不是纯 idle 渲染时间。原始动作保留同一观察器单调时钟
的 started_at/finished_at，要求有限、非负、有序且 duration=end-start；
累计指标共享原始端点，禁止通过相加分段遗漏中间开销。

报告按三个命名子场景闭合，不接受任意诊断字段集合。每个子场景必须保存
实际 spawn 的 executable/argv/cwd/start、member/认证/输入/当前帧完成、
detach 结算、后验 snapshot、stop 观察的顺序和证据。身份闭集包含
instance/service/Mux/member/Session、请求 nonce 与原 native identity。
普通回复必须恰两条 USER(reply nonce)/ASSISTANT(expected)，不只数 assistant。
工具保存同一 call 的原效果证据和批准时刻，批准前零效果、stop 后恰一次，
且效果不早于批准；中断保存原 producer 的前未结算/后已结算与唯一 B。

所有实际创建的前台终端，包括 interrupt 初始端与异 cwd 重连端，均须
退出0、完整PTY恢复、reader结算且无fallback；按完整spawn/terminal列表
逐个验证，不按三个子场景只计三次终端（当前组合至少四次）。前一子场景
最终stop及本地资源结算终点不得晚于下一子场景首个spawn。精确实例stop
三事实及原外层owner物理结算也是整个样本的资格门槛，而非仅有duration
即通过。stop 起点及三事实观察时刻
需保留；只有 collector 的原 run_python 成功返回才能追加外层结算终点，
probe 不宣称自身已退出。后验只接受/否决，不能倒填可见帧时间。任何
子场景、后验或最终清理失败均使整样本无效，不换槽、不写可恢复检查点。

复用原精确 inventory 比较入口与统计策略，保持 managed-mux 九指标和
旧七场景不变。正式晋级负测至少覆盖缺失/额外/非有限字段、乱序/错duration、
早于detach的snapshot、错身份/nonce或额外记录、提前/重复工具效果、
提前producer结算、假stop、外层失败及已有成功字段后的晚清理失败。
先完成本增补复核，再实施接线与真实冻结安装 A/A；不得据此关闭全部M4。

## 长历史正式晋级增补（接线与限定复审完成，正式采集待通过）

沿用原两个诊断名称作为显式 optional case，不修改默认七场景、managed-mux
九指标或首次 Product 八指标。warm 比较 `history_frame_seconds`（真实 attach
spawn 到完整历史帧）和 `history_completion_seconds`（输入 `/he` 前到完整
补全帧）；seed 不计入两者。restore 只比较 `restored_history_frame_seconds`，
直接采用行式 start 的真实 spawn 与新代历史帧两个原端点，包含启动、认证和
attach 准备间隙，不相加分段；恢复补全仍必须成功，只是不进入该指标。

正式 validator 独立核对以下证据，而非信任 helper 内的断言：

- 原配方128轮、256消息、263680文本字节及固定摘要；近期15条尾窗严格是
  14条 USER/ASSISTANT 加1条 omitted STATUS，不将尾窗冒充完整历史。
- seed最后一轮完成 → detach Ack → 原连接/journal/namespace结算 → warm
  attach；旧代stop/local-owner结算 → canonical读取完成 → 新代spawn。
  新代也必须stop、canonical及原outer结算，不能用旧代回执顶替。
- 每代认证target、ready、snapshot与完整五字段Session身份相互绑定；同服务
  与Session，不同instance/native。canonical绑定实际读取的根和Session选择，
  不以另一次事后pathname stat冒充原读取身份。
- warm两个TUI；restore旧代两个TUI、新代一个行式start和一个TUI。每个真实
  终端独立核验PID/argv/cwd、退出0、termios、reader及无fallback。行式命令
  不要求也不伪造cursor/paste标记，TUI仍保留完整恢复门禁。

outer预算必须按串行阶段上界核算，覆盖原600秒seed、认证、全部终端、两代
停止与后验读取，不延长内部期限。原run_python返回后追加outer结算，再经
完整校验和固定槽来源复验才能valid=True；helper始终False。负测包括迟到
seed/连接结算、旧canonical未完成即重启、start关闭失败、错误服务/同代身份、
新旧摘要不一致、跨代回执串用、错误累计起点及任意stop/outer失败，均不得
晋级正式样本或checkpoint。仍沿用原20对与失败保留规则。

## 最终 M4 验收记录（2026-09-22）

冻结提交 `16c482e551859db89346b49c9a548adb128535c3` 和 wheel SHA-256
`ca27bba3f76c46ff1825c2c9419617bf2d4807ebe431c6f3e2c39f2654cf90f3`
完成两个新的不间断 A/A campaign：

- `managed-product-first-use`：44/44 valid（4 warmup + 40 measured），
  comparison pass；八个冻结指标、三个 fresh 子场景、至少四个真实终端、
  唯一工具效果、producer 结算和 exact stop 均通过 validator。
- `managed-product-history-restore`：44/44 valid（4 warmup + 40 measured），
  comparison pass；每个样本均验证 128 轮/256 消息历史、旧代停止、不同
  native identity 的新代启动、完整恢复帧和新代停止。

原 `managed-mux` 与 `managed-product-history-warm` campaign 由 ARD-004
只读工具重评为 pass；重评文件绑定原 report SHA-256，不改原数据，并声明
其不是新测量或独立性能验收。全部 verdict 的含义均是“在接受的统计合同下
未检出超过 30% 的回归”。它们不支持“没有回归”、低于该阈值的量化结论或
相对其他版本的提速声明。

先前 restore 的 `startup_failed` 报告保持原样。产品根因是共享 registry
目录描述符的瞬时关闭窗口与启动 fence 争用；窄修复只允许原 owner 在原
deadline 内让出一次最多 10 ms，持续/未知清理债仍失败。修复后的正式采集
跨过原固定失败点并完成全部样本。最终测试与三视角结果见
[M0 合同 §97](lmux-contract-m0.md#97-m0m4-正式验收收口2026-09-22)。
