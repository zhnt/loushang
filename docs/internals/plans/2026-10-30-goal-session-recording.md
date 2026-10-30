# Coding Goal 同 Session 记录与来源接入

- 设计：[GMW-KD-SESSION-01 R2.1](../architecture/goal-method-work/session-execution-recording.md)，已获用户接受，同 Session 第一切片。
- 源码基线：`2d6ed6d64`；实现提交 `00bee2be6`，清理重试修正 `2f257ca2e`。
- 范围：现有有限计算器 Coding SDK Goal，多批 Work 共用该 Goal 的原 Session。独立子会话及继承上下文子会话尚未接入。
- 状态：同 Session 第一切片已完成，实施三视角阻断关闭，既有本地检查通过。

## 已实现行为

`CodingGoal.open()` 默认配置原 WorkRuntime 的 recording v1 和持久记录要求，普通调用无需增加参数。不传来源保留期限时，Work 记录仍可读取，但不能宣称其 Transcript 来源已交接。

显式传入 `transcript_retained_until` 后，Product 用原 Session manager 的文件路径及同一平台的 store state root 绑定原 `TranscriptSourceReader`。期限必须含时区，且由 Product 承诺在期限内保留 Session、admission 及必要 Blob；关闭 owner 只释放资源，不清理这些文件。到期不会自动延长。

```python
from datetime import UTC, datetime, timedelta
from loushang.coding.adapters.goal import CodingGoal

# 一天只是调用方的策略示例，不是 SDK 缺省期限。
owner = await CodingGoal.open(
    workspace=workspace,
    data_root=data_root,
    model=model,
    model_planning=True,
    transcript_retained_until=datetime.now(UTC) + timedelta(days=1),
)
# 沿用原 create / advance / query / close 调用和资源保留责任。
```

共享 `prepare_session_work_source` 从原 Session bridge 提取同一套准备校验。Coding 在安装原权限/规划包装前绑定标准 executor，不新建 SessionWorkRuntime、Goal 调度器、队列或来源索引。模型规划保留原 planning step 和响应证明；Method 的每步及原 follow-up 使用原交接规则。静态检查和命令验证没有模型 prompt，不生成空的来源合同。

期限检查沿用原 source.check，分别在准备、Goal 两次候选确认、每次 prompt 前执行。过期按照原 PolicyStop、candidate_outdated、not_submitted 或 Work failed 路径处理；无来源的静态/验证工作不被全局期限阻断。

## 冷读与关闭

停止所有相关 writer 后，调用方从可信 Product 配置或原 Session 布局确定实际文件及平台根，创建并持有原 reader，再调用异步入口：

```python
from loushang.coding.adapters.goal import read_goal_work_sources
from loushang.harness.transcript.source_reader import TranscriptSourceReader

reader = TranscriptSourceReader(
    session_file=session_file,
    conversation_id=session_id,
    store_state_root=store_state_root,
)
views = await read_goal_work_sources(
    data_root=data_root, session_id=session_id, goal_id=goal_id, reader=reader,
)
# 此片段仅展示 API；实际调用方须在成功、失败及取消后关闭同一 reader。
await reader.aclose()
```

不从 Work 日志接受任意物理路径，不搜索其它库兜底，也不重建 SDK 或执行任务。每批返回原 WorkRecording 和 WorkTranscriptResolution，加上 Goal 批次/operation 关联；不新发持久视图格式。

| 状态 | 含义 |
| --- | --- |
| `not_submitted` | 原 Goal 已记录未提交，且没有矛盾的 Work |
| `unresolved` | 原批次找不到对应 Work，不能算未声明来源 |
| `not_declared` | 有效、关联核实的 Work 未声明来源合同，包括旧历史或纯静态工作 |
| `complete` / `incomplete` | 原共享来源核验后的交接完整性；不等于 Goal 完成或执行结果已确定 |

身份、格式、期限、损坏或读取错误直接报告，不降级为 `not_declared`。各 Work 分别使用自己的冻结期限。来源完整的历史 Work 仍可能为 orphaned，Goal 的 `validity` 与 `execution_unresolved` 继续由原业务查询判断。

reader 的关闭权始终归调用方；失败时保留该对象及依赖，以便重试 `aclose()`。函数自己打开的原 GoalJournal 若关闭失败，会抛 `GoalWorkSourceCleanupError`，保存 `owner`、`read_error`（含取消）及 `cleanup_error`；应保留异常，对同一个 `owner.close()` 重试成功后再打开日志。不能重建对象来绕过尚未释放的锁，也不能丢弃原读取错误。

运行中的 CodingGoal 按原 Work 收敛 → reader → Session → Goal → writer 的顺序关闭。reader 失败时保留原 owner 及 Session 依赖，后续 `owner.close()` 接着完成。

## 验证与实施评审

三位独立 reviewer 对 `00bee2be6` 实施复核；职责与运行视角发现冷读 GoalJournal 关闭失败时隐藏原 owner。`2f257ca2e` 增加上述保留异常及三场景测试，原 reviewer 均确认阻断关闭，数据视角确认历史合同未变。详见[评审记录](../architecture/goal-method-work/session-execution-recording-review.md)。reviewer 本轮仅静态复核，下列运行结果由主实施方执行。

| 验证 | 结果 |
| --- | --- |
| 首轮 Coding Work/Goal + HarnessWork 来源集成 | 157 passed，7 skipped |
| Method 多批、候选到期、关闭重试 | 4 passed；混合历史与 reader 清理补充后，受影响多批用例另行通过 |
| 冷读 GoalJournal 清理成功/失败/取消 | 3 passed；同对象清理前锁仍占用，重试后可重开 |
| 动态输入 / 执行中到期 | steer、follow、交接期间遗留输入三场景通过；prompt 前及 prompt 内到期两场景通过 |
| 原 Work / Method / TranscriptSourceReader | 232 passed |
| 真实 SDK 与独立新进程 | 同 Session 两批 Method、每批 `0:0` / `1:0`；只读重开通过，无模型/工具重执行 |
| 现有 change-aware PR-fast 路由 | Coding 3986 passed、20 skipped、64 deselected（33 分 44 秒）；HarnessWork 54 passed；离线 E2E smoke 2 passed |
| 修改源码静态检查 | Ruff、5 文件 mypy（`--follow-imports=silent`）、diff whitespace 通过 |
| 文档与架构 | 9 项既有文档不变量、变更文档链接及生成的架构依赖事实检查通过 |

以上路由有重叠，不累加为独立测试总数。真实 SDK 使用离线传输，未调用在线模型；普通模型规划的标准传输接缝、权限及响应证明未放宽。测试复用既有文件和路由，没有新增 PR gate 或平台矩阵。

GS-01—03/05—07 对应真实 SDK 规划/Method、共享准备校验、独立进程与混合历史用例；GS-04 复用原 append/取消/缺组测试，加期限跨越与 Product 清理注入；GS-08 由设计与源码复核确认子执行未启用；GS-09 覆盖借用 reader 和函数自有日志的清理；GS-10 补充真实 repair 中动态输入的来源和队列断言。

## 保留边界

这不是任意仓库任务适配器，也不迁移普通 TUI/AppHost 默认入口。子 agent Goal 接入、持久子 Transcript、完整审计、正文裁剪、自动重放副作用仍未交付。冷读仍可能逐 Work 扫描同一 Transcript，本切片没有性能 benchmark 或缓存优化承诺。
