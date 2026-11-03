# HG-003：有效预算与进度观察实施记录

- Design authority：[已接受R1](hosted-goal-budget-observation.md)、[ARD-020](../../decisions/accepted/ARD-020-hosted-goal-budget-and-observation.md)。用户于2026-11-02回复“同意，继续”。
- 源码起点：`497e386a3bbb8fd40810dd7d1be0db9f21e616eb`；本地分支`design/hosted-goal-budget-observation-824`。
- Implementation status: implemented — offline verified and independently reviewed; integration is recorded by the associated Git/PR state。
- 本轮未调用在线模型。用户已同意独立评审后收尾交付；三视角代码评审及修订已完成，见[记录](hosted-goal-budget-observation-review.md)。远程CI与合并状态以实际PR为准，不由本地验证推定。

## 实际变更与责任

| 需求 | 实现位置 | 行为 |
| --- | --- | --- |
| BO-01 有效预算 | `coding/adapters/_goal_planning_limits.py`、`_goal_planning_shared.py`、`_goal_repository.py` | 原Allowance提供只读快照；规划与Method实施材料包含有效调用、输出和时间限额。批内工具往返不重写快照 |
| BO-01 配置证据 | `coding/adapters/goal.py`、`_goal_repository.py` | 新Goal原metadata记录hosted_execution_limits；原规划profile不改写；受理按规范化JSON核对，未知版本不执行 |
| BO-02 时限及预留 | `coding/_hosted_goal_config.py`、`_hosted_repository_config.py`、`_hosted_goal_work.py`、`_hosted_repository_work.py` | repository显式T/R、原timer切换模型M与业务D；repair完成并通过截止检查后进入收尾；stream入口在计数前检查同一owner |
| BO-03 进度读取 | `coding/hosted_goal.py`、`_hosted_work_observation.py` | 原run_receipt/get_run/get_recording/get_cancellation；不查询Work正文、不读取工作区；steps不展开、validity不为current |
| BO-04 权限及兼容 | `appserver/goal.py`、`appservice/goal.py` | 缺省false能力、独立可选Product协议；绑定解析检查；交付前重新核验同一scope/owner/handle；原query/wait不变 |

没有新增运行时组件、调度器、队列、索引或事实日志。原Work/Goal、Session/Transcript仍分别拥有执行、完成依据与调用事实。progress要求本owner的acknowledged记录；遇到loaded或缺receipt不以日志扫描补齐。初始化和清理仍由原guard/Invocation负责。

## SDK使用方式

可信宿主在创建`CodingHostedRepositoryGoalV1`时选择`deadline_seconds=T`和`closeout_reserve_seconds=R`，要求有限值且`0 <= R < T`。缺省仍为120秒和0秒；calculator原120秒上限不变。具体任务需依据模型与完整验证/评审耗时冻结T/R，此文不选定下一次在线试验预算。

在已有授权scope和Goal handle上：

```python
capability = await client.capability(control, client.service_instance_id)
if capability.supports_progress:
    progress = await client.progress(control, submitted.handle)
    # progress.observation.validity == "not_checked"，或不确定时为"unknown"。
    # 查看execution/work状态；不能据此宣布代码当前验收通过。

result = await client.wait(control, submitted.handle)
# wait仍执行原完整查询；按execution、validity和原业务判据解释结果。
```

旧Product能力缺省false，调用progress返回unsupported，不自动回退完整query。旧query/wait调用方无需修改，但若要降低轮询成本，需要主动改用progress。本轮未改原试验存档或启动新试验。

## 验证范围

新增`tests/coding/test_hosted_goal_budget_progress.py`覆盖配置、真实离线Session/工具/Method/验证/评审闭环、两类模型材料、进度无历史/业务访问、未知记录和缺receipt、权限撤回、时钟边界、原Work取消及只清理重试。真实离线闭环使用有限240/60配置检验新行为，不构成线上预算建议。

离线结果（2026-11-02）：

- 新增预算/进度、本地repository Goal、全部AppService/AppServer及相关三组架构检查：1225 passed、10 skipped，479.85秒。选择器为`not live and not requires_host_runtime`并保留`--skip-host-runtime`；跳过项不计为通过。
- 另补“repair完成但返回时已过M”：1 passed，9.78秒；确认仅两个Work、3次模型调用，保留completed repair，Goal停止且执行结果已收敛。
- 最后配置边界复核：12 passed、7 deselected，4.29秒；覆盖极大整数、非有限值、bool、R≥T和calculator旧上限。与前述回归存在重叠，不相加计算独立用例总数。
- 首轮新旧托管Goal回归：64 passed、1 failed，失败来自新测试误写`core.basis`；改为实际`core._basis`后已在上述1225项中通过。原托管calculator/repository案例在首轮通过，没有将初次红灯隐藏为全绿。
- 变更Python文件Ruff、AppService/AppServer两个接口文件mypy、生成包依赖图检查、9项文档规则及变更链接检查通过。
- 独立评审后修订：宿主命令余额与原Goal余额取较严值；已锁定截止原因不被迟到取消/普通异常覆盖。最终专项21 passed（36.71秒）；职责视角独立两项集成2 passed，运行视角独立竞争两例2 passed，数据视角三组真实规划材料窄探针通过。完整记录见上链评审文件。

这是针对本次边界的分批验证，不是全仓全平台门禁通过。未运行完整Coding/AppHost、原生平台或在线路由，也未新增或扩展PR门禁。涉及本地仓库规划的兼容由既有repository suite覆盖；原prepared输入及Transcript来源链沿既有路径验证。

局限：无在线Kimi结果、无物理硬截止或跨进程恢复承诺；性能验证以禁止重路径调用和有限批次数为依据，未声明固定毫秒性能。完整query仍保留原复核成本，ContentDelta记录策略未改。

## 后续规划输入修正（2026-11-03）

一次另行授权的有限在线试验停在规划阶段：首次响应把当前operation ID当成证据引用，第二次响应触及单次输出上限并以length结束。两次规划名额耗尽后停止；没有进入实施、完整验证或评审，不证明线上业务闭环成功，也不是总时限到期或已证实的服务商配额耗尽。冻结材料及原始响应保留在产品树外。

本轮只在RepositoryDomain新生成的规划input.material中增加response_guidance：证据引用只能取当前input.evidence的id；无证据时返回空数组，operation ID、输入摘要、要求编号与预期输出类型都不能代替证据编号。要求理由各用一句短句，不复述要求、文件或实现代码；路线仍由模型选择，必要时只提出下一步。

指导复用原input Blob和Transcript来源链；不改prompt构造、Proposal v1、准入校验、调用/输出预算或重试次数。历史输入没有该字段时，仍按原字节重建提示并核对来源。新指导是表达建议，不是新增硬限额，也不自动删除错误引用或补全被截断的JSON。

离线专项6项通过：operation引用被拒绝、length即使携带完整JSON也被拒绝、部分JSON加length被拒绝；每种路径都验证后续简短合法计划可读取，并分别覆盖新输入和不带指导的旧输入在恢复当前producer后冷读。使用确定性离线provider，未执行线上调用。首轮测试误把文本块列表当作字符串，修正测试读取后通过，产品运行机制未为此调整。

原始996字节失败响应在现有解析器中保持拒绝；手写352字节候选可解析。字节数不是token数，手写候选和离线provider不证明真实模型遵循提示，更不证明1024输出额度下的线上成功率。验证目的仅为保留拒绝边界、输入交付和历史兼容；没有增加PR门禁。

变更选择检查中的文档9项与生成依赖图检查通过，变更Python文件Ruff通过。广泛Coding回归在运行目录所在的164 MB tmpfs上出现明确的ENOSPC，后续存储错误级联；人工中断时为2050 passed、350 failed、41 errors、13 skipped、62 deselected，不能声明广泛回归通过，也不将所有失败未经逐项核查都归为同一原因。通过现有LOUSHANG_RUNTIME_DIR配置将后续相关回归放在磁盘目录，不修改产品存储策略或测试门禁。

磁盘目录回归另遇Transcript目录安全拒绝：该目录祖先工作区为0775，原AdmissionWitnessLease要求私有祖先；中断时为43 failed、40 passed、7 deselected。未修改该安全规则或工作区权限。同一首例在默认私有/tmp测试目录单独运行1 passed（34.64秒），随后相关回归使用该路径继续验证。

最终相关离线回归：`test_repository_goal.py`、`test_hosted_repository_goal.py`、`test_hosted_goal_budget_progress.py`及`test_work_shell.py`共271 passed、7 deselected（770.76秒），保留`not live and not requires_host_runtime`与`--skip-host-runtime`。文档检查、Ruff和diff空白检查通过。本轮线上模型调用为0；广泛Coding回归仍为上述环境失败后中断，未声明全仓通过。
