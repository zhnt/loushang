# HG-003 R1：设计走查与评审状态

- 对象：[专项设计](hosted-goal-budget-observation.md)与[ARD-020](../../decisions/accepted/ARD-020-hosted-goal-budget-and-observation.md)，2026-11-02。
- 源码基线：`497e386a3bbb8fd40810dd7d1be0db9f21e616eb`。
- 方法：本地master、干净工作区，`0f9bd3ff51afabeaaf76cc38dff1ceb279b7d37e`。
- 执行者：本轮设计作者。方式：源码静态核对、既有试验记录、合同与失败场景走查。
- R1设计提交时只有下文作者走查；用户于2026-11-02回复“同意，继续”后接受设计并开始实现。实现完成后，用户同意独立评审后收尾交付，已另行完成三名独立agent代码评审，见文末。设计走查与独立代码评审不是同一次活动；实际验证见[实施记录](hosted-goal-budget-observation-implementation.md)。

## 职责与复用

预算策略留在Coding Product；Invocation拥有唯一时间边界，PlanningCallAllowance保留原调用计数。模型快照不授予执行权限。AppService只鉴权和交付，HarnessWork沿原状态、录制、取消接口提供事实。

发现并修订：直接复用完整observe_work_run会重放历史步骤，违背轻量目标。专项§5改为复用原值类型及原内存读口，在原投影模块内分离构造，不增加进度缓存、run映射或独立服务。可选Product协议与原必需协议分开，避免旧port被迫实现新功能。

仍待独立核查：本owner每种初始化/终态下是否均可只凭原batch.run_receipt定位run；不能满足时应返回不可观察，不增加历史查找来掩盖缺口。

## 运行与失败

M限制模型阶段，D限制全部业务；预留时间不保证验收成功。原owner处理截止、取消和settle，重试清理不重置时间、不重新调用模型。迟到结果不授权下一条命令。

发现并修订：仅命令边界检查不能避免同步工作拖延timeout后启动下一次provider调用。专项§4.3补原stream入口同步询问同一owner的截止检查；不新增计时服务。同步IO、远端调用与取消无法硬抢占的限制继续写明。

已在专项§4.3固定原因优先级：已有latch优先，其后D先于M；R=0保留原总时限码。仍待独立核查业务阶段切换与停止latch的竞争，后续用可控时钟覆盖BV-03。任何试验预算都需另行冻结，不从此稿推导在线调用授权。

## 数据与兼容

静态配置写入新Goal的原metadata，时变值进入原准备材料；不迁移旧记录，不改prepared committer。progress复用DTO但明确not_checked和未展开steps；原query/wait保留完整验证。记录completed不等于工作区仍满足要求。

发现并修订：execution_unresolved=false容易被解释成已经停止。专项§5明确其仅表示未观察到结果不明，运行终态与业务验收分别读取，不能互相代替。旧port缺省不支持progress，不允许回退重查询。

仍待独立核查：有效limits投影与原输入来源证明是否完全相容；进度读取遇到receipt缺失、fenced或清理失败时，不得返回看似完整的状态。

## 验证与下一步

本轮没有运行产品测试或在线模型。专项BV-01至BV-07是后续离线验证计划，不是测试结果。已运行既有`check_docs.py --plan`：9项文档规则及本轮变更文件链接检查通过；`git diff --check`通过。这些检查不能证明运行合同或性能成立。

R1提交时建议独立复核再提交接受；此后用户直接接受并要求继续。用户的重要工作件评审已经发生，本作者走查仍不能表述为三视角独立评审通过。

## 实施期补充走查

职责与复用：确认原WorkRun是小型不可变身份/状态值，get_run和get_recording不重放日志。轻量分支先检查acknowledged及run一致，再取取消事实，缺口不增加历史查找。可选协议与旧port分离，原query默认展开步骤保持不变。

运行与失败：原timer仍由Invocation持有，模型阶段结束切到原绝对D，没有新增计时任务。总期限优先、已锁定停止原因保留；stream入口先检查再消费调用额度。预算绑定放在原run内，避免尚未由guard受理的构造失败占用一次性绑定。settlement不进入run、不重新绑定或延长时钟。

数据与兼容：静态预算用规范化JSON精确比较，避免Python中True与1相等造成版本绕过。旧Goal没有新字段时原只读profile仍保留旧解释；本轮不升级旧记录。progress只声明not_checked/unknown，完成记录后的工作区篡改仍由完整query发现。

本轮待核查项的作者核对结果：receipt缺失及loaded记录已用禁用历史查询的离线场景覆盖；M/D优先级、迟到repair、原Work取消与清理重试已覆盖；真实离线规划、Method实施材料及原来源路径完成闭环。1225项回归和补充迟到repair用例通过，详见实施记录。这些证据关闭作者发现的实现问题，但不转换为独立评审结论。

## 独立代码评审与关闭（2026-11-02）

用户同意“独立代码评审后收尾交付”后，安排三个独立agent。它们各自读取当前源码、R1合同和本地架构方法，未把既有走查/实施报告当作判断依据。方法版本仍为上述本地master SHA。

| 独立视角 / Reviewer | 初审发现 | 处理与复核 |
| --- | --- | --- |
| 职责与复用 / budget_progress_ownership | 无阻断；O-01指出progress复杂度上界不能把repository的6泛化到calculator | 文档改为O(B)，repository≤6、calculator≤8。独立两项真实离线集成检查2 passed（27.98秒）；最终代码修订仍无责任迁移 |
| 运行与失败 / budget_progress_runtime | RT-01 P2：已锁定M截止原因被迟到取消/普通异常覆盖；RT-02与D1同源 | 原run异常分支保留_stop_reason，仍传播取消。原评审者独立运行cancel/error竞争两例，2 passed；预算修订同步复核关闭 |
| 数据与兼容 / budget_progress_data | D1 P2：max_advances=4时模型limits为4，但remaining仍按Goal固定6计算 | 原Invocation快照传已计入当前命令数，remaining取两种权威剩余的较严值。独立真实_planning探针得到4/1/0→4、4/3/1→2、4/5/3→0（上限/已计命令/已有批次→剩余）；profile仍6 |

两项独立缺陷均已由原评审者复核关闭；RT-02与D1只计一次同源问题。阶段名额仍是自身名额，但材料明确还须满足总Work/command剩余；没有新增分配器或准入权威。最终专项离线回归21 passed（36.71秒）。

结论：三个独立视角均无未关闭阻断项，可以进入既有PR交付流程；这不等于在线Kimi成功或全平台CI已通过。完整独立报告、初审/复核文件摘要与reviewed-code.json保存在产品树外`architecture-analysis/hosted-goal-budget-observation-824-20261102/`。远程CI状态由PR记录，不在此预先宣称。
