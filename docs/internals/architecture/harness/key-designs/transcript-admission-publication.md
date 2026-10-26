# Transcript admission：完整登记发布与受控恢复

- Authority: normative — 用户于 2026-10-26 同意定点修复的范围。
- Design status: accepted within the authorized repair；Implementation status: implemented and verified locally for Linux。
- Owner: Harness Transcript；复用 Journal 的 retained writer 和 rooted I/O。
- Baseline: e92988cf5；方法为本地 archmethod master 0f9bd3ff51afabeaaf76cc38dff1ceb279b7d37e。
- 授权范围：初始化窗口、可定位错误、从已核验备份恢复缺失登记；不清理历史、不扩大 Goal。

## 问题与边界

原实现先建立正式 witness 目录和锁，再写 admission.json。进程在两者之间退出，
会留下无身份记录的正式目录。新 family 检查历史登记时遇到该目录，只得到
unavailable。直接忽略它会失去识别旧库丢失的依据；既有损坏 v1 拒绝合同保留。

admission.json 是物理身份凭据，不是默认配置。没有记录的旧目录不能证明从未
初始化；仅有锁也不能排除“已提交的记录随后丢失”。本修复不自动认领、删除或
重置这种旧状态，也不承诺从缺失身份重建原历史。

## 选择及交互

1. 新 witness 使用同一 state 父目录下随机命名的私有 staging 目录；原 lease
   持有目录和锁 fd，原 rooted I/O 写完整 initializing 记录并持久化。
2. 用 Linux 不覆盖目标的原子目录重命名发布到正式 key；父目录 fsync 成功后，
   acquire 才返回。随后原逻辑才创建数据目录并提交 initialized。
3. staging 不具有数据库创建权限。发布前退出只能留下非权威的 staging；新 reader
   识别准确的保留名称并略过，未知正式名称仍校验。失败 staging 保留，不自动清理。
   staging 身份发布后沿原 v1/v2/family schema 读取，不引入第二份状态权威。
4. 原始目录、lock、rooted I/O 和同步/关闭未知状态由同一 retained owner 保留；
   重命名后更新原 lease 的路径并重新核绑定。发布异常不能继续创建数据。
5. 缺失/坏记录提供本地异常属性和 traceback note：阶段、路径、恢复提示。
   原异常基类及有界 str(code) 保持；远程普通错误字符串不新增物理路径。
6. restore_record_from_backup 接受明确 root/state_root 和已保存的完整备份字节。
   首版仅恢复 v1 或 v2 member 的缺失 admission.json；不覆盖现存记录、创建库、
   重建 family、补默认值或把 initializing 转成 initialized。
7. 恢复借用原 inspect 校验链，核 witness/lock、data root/parent、family/member
   等身份及 initialized 阶段；全部成功后在原锁下独占发布原备份字节，持久确认。
   无备份、身份变化或检查失败一律不写；失败时调用者保留 owner 并执行原 close。

诊断恢复位于 Transcript，Goal 不引入新队列、执行器或存储特例。
有效 v1/v2/family 正式记录格式不变，普通 prompt 和旧库恢复沿原路径。
新旧版本同时参与新库初始化不作新增保证；旧 reader 看到崩溃 staging 可保守拒绝，
已登记库读取不依赖扫描 staging。全局未知旧登记仍保守阻断；无法核归属时不声称
故障已被安全隔离。更宽的历史状态恢复需要另有身份来源。

## 三视角设计复核

本轮由实施代理分别走查三个视角，不称为三个独立 agent 评审。

| 视角 | 发现与关闭条件 |
| --- | --- |
| 职责与复用 | 直接复用 lease/rooted I/O；窄 native no-replace 发布是现有机制的 Transcript 私有适配，无 Goal 或 Product 导入 |
| 运行与失败 | 原子发布必须不覆盖空目标；同步账本必须在 rename 之前登记；失败后不得创建数据；需进程退出与并发证据 |
| 数据与兼容 | 记录 schema 不变；旧未知目录不能自动跳过；恢复只接受 initialized 的原身份并独占发布；需错 root/parent/lock/family 反例 |

实施代理按已授权修复范围接受上述内部机制。用户已同意的三步建议是本范围依据，
本记录不制造额外用户接受或独立评审结论。后续如改变旧身份恢复承诺，另行评审。

## 验证与剩余限制

验证覆盖新 family 和旧 v1 创建、发布前/后进程退出、并发不覆盖、同步失败、
有备份的恢复和失败无写入、原损坏登记/目录替换保护、原 SDK 普通 Session。
不新增 CI gate 或测试路由。

无备份旧 orphan 在本机仍应拒绝，错误必须可定位；修复不等于已经恢复该机器
残留所属库，也不以测试用的隔离状态域作为生产恢复成功。

## 实施复核与实际证据

生产改动限于 Transcript：私有 AdmissionWitnessLease 发布适配、原 admission/family
装配以及本地错误属性；Journal 原实现、Goal、输入队列和执行器未改。原正式记录
schema 保持。恢复入口要求调用者明确目标库并提供保留的 initialized 备份；它校验
当前物理绑定，不证明备份来源，不覆盖现存记录或修复缺失的 family。

三视角实施复核由同一实施代理完成，未派独立 agent。复核发现及处置如下：

| 发现 | 处置及证据 |
| --- | --- |
| 新 member 的首次发布不能暂用 v1 格式 | factory 在发布前纳入原 family/member 身份；测试在原子 rename 边界核 v2 记录 |
| 初始登记到初始化完成不能更换 operation/incarnation | 后续写入使用首次发布的同一记录；正式发布与完成记录身份保持断言 |
| 有 family 时不能从 v1 备份降级 | 恢复前拒绝版本不匹配；已有记录、错误 family/member/lock/root/parent 等反例无写入 |
| 恢复失败不能保留内存备份作为读取权威 | finally 清除临时读取来源；失败后原 check 仍报告缺失，整个库快照未变 |
| rename 效果/持久回执未知不能继续建库 | 父同步债在 rename 前登记；效果有/无、父 fsync 失败和关闭清理反例通过 |

实际检查使用隔离 Python 和既有 scripts/dev/run_pytest.py，不改变共享安装。
产品树外证据目录为
`/home/dev/lsspace/architecture-analysis/transcript-admission-repair-20261026/`。

| 验证 | 实际结果与边界 |
| --- | --- |
| Transcript + Journal 完整离线组合 | 阶段版本 890 passed；首次直接 pytest 运行遇临时目录消失，改用原 leased scratch runner 后通过，未为此修改产品代码 |
| 最终准入/family/writer 交接 | 112 passed，包含原子发布、真实子进程退出、并发、同步未知、备份恢复和身份保持 |
| 准入 + 架构导入边界 | 阶段版本 219 passed；与准入组合有重叠，不累加为独立用例数量 |
| Coding SDK/Goal | 阶段组合 12 passed/74 deselected；最终源码再次运行真实 SDK 初始检查、关闭及冷读用例 1 passed；均离线、不调用模型 |
| 原 AI 检查 | make check-ai 通过，936 passed/7 deselected，90.77% 覆盖率；未扩 CI route/gate |
| 静态检查 | 最终 4 源 mypy、改动 Python Ruff、依赖事实图检查、文档规则和 diff 检查通过 |
| 真实机器只读诊断 | 默认 v1 库 inspect 成功；新独立库准确报告旧缺失记录的路径及 read_record 阶段；隔离新库初始化成功；原 83 个状态文件内容未改 |

完整组合之后，最后的身份保持及临时备份来源清理修正用上述最终定向组合核验；
不声称所有平台、完整 check-changed 或真实模型执行已在最终修订重跑。
首次工具入口配置问题已在专用临时环境修正，没有更改生产依赖或测试标准。

### 使用匹配备份恢复缺失记录

这是维护入口，调用者应先使目标库写入静止，明确原 session root 和 state root，
并保留本 owner 直到 close 成功。方法只持原短准入锁，不负责停止所有 Session。

```python
from pathlib import Path
from loushang.harness.transcript.store_admission import TranscriptStoreAdmission

owner = TranscriptStoreAdmission(session_root, state_root=state_root)
try:
    binding = owner.restore_record_from_backup(Path(backup_path).read_bytes())
finally:
    owner.close()
```

session_root/state_root/backup_path 必须由维护调用者明确指定；无匹配备份时不执行
该步骤。失败需保留原异常及 cleanup owner，不能以重新构造 owner 掩盖关闭债。
已发布旧记录丢失但没有备份的机器仍可能阻断新库创建；本次修复不会静默解除。
