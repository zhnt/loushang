# Work 默认记录与确认查询：第一交付切片

- 状态：第一切片已实施，相关离线验证通过；已本地合入 main（收尾提交 `d1bfefcea`）。分支 `feat/work-recording-defaults`。
- 依据：[HW-KD-003 R3.1](../architecture/harnesswork/key-designs/fact-retention-replay.md)、[ARD-019](../architecture/decisions/accepted/ARD-019-work-facts-and-transcript-sharing.md)。用户已授权继续实施；本切片不改变已接受语义。
- 基线：产品 `5eadeb91c`，已接受设计提交 `a253869fc`。

## 范围与接口

`WorkRuntime(recording_version=1, event_log=..., executor=...)` 一次启用新记录入口，无需自定义策略。省略 `recording_version` 保持旧行为；启用参数只接受整数 1，拒绝 bool 与未知版本。

Product 可传 `recording_policy=WorkRecordingPolicy(require_persistence=True)`；单 Work 可在 `WorkRunSpec.recording_policy` 提出要求。省略继承 Product 下限，显式削弱下限则在解析 executor、追加及执行前拒绝。合同受理时冻结，运行中不改写。第一切片没有事件筛选参数：保留所有已发布事实，未知领域事实也保留，不自动序列化 executor 返回值。

内置 backend 的只读 `recording_retention` 声明分别为 `memory` / `persistent`。第三方 backend 可实现此可选属性；未声明为 `unknown`，默认仍可使用，但不能满足持久要求。它是装配能力声明，不是底座对任意第三方的物理验证；persistent 不承诺 fsync、单 writer、跨库事务或无限保留。Product 负责唯一 writer 和删除生命周期；一个 backend 的追加由一个 Runtime owner 独占，不支持绕过 Runtime 直接追加后仍把其缓存当作完整确认视图。

## 冻结格式与兼容矩阵

同一 operation entry 的 `payload._harnesswork.recording`：

```json
{"version": 1, "capture": "published_facts", "retention": "persistent", "require_persistence": true}
```

完整字段必需且不接受未知字段；版本须精确整数。合同不包含资源路径、策略树或业务身份副本。生命周期和事实正文不变，不修改 JSONL 外层 schema。后续若裁剪事实或替换正文，必须另定 capture/版本及迁移合同，不能暗改本合同。

| reader / 历史 | 行为及失败范围 |
| --- | --- |
| 新确认入口 / 旧历史 | `contract=None` 表示 legacy 未声明；不补造审计保证 |
| 新确认入口 / v1 历史 | 返回冻结合同和已确认状态；仍不等于目标验收 |
| 旧 reader / v1 历史 | 可解码全部原事实及生命周期，忽略嵌套合同；不宣称理解新合同 |
| 新 reader / 混合旧、v1、未知版本 | 生命周期按原规则；确认查询仅对未知/非法合同所属 run 报错，其余 run 可查询 |
| 回退旧装配后新 Work | 新 Work 无合同标记；既有 v1 历史保持原样 |

混写仅允许本切片这种保留全部原事实的 v1；这不是对未来来源引用格式的兼容承诺。未知版本抛 `WorkRecordingVersionError`，已知版本非法字段抛 `WorkRecordingFormatError`。旧二进制忽略合同的能力须以基线 projector 实测，而不是只测当前 reader。

## 确认依据与失败

`get_recording(run_id)` 返回不可变 `WorkRecording`：`run`、`contract`、`basis`（`acknowledged` / `loaded`）、`observed_sequence`、`source_event_id`。新入口必须启用 recording v1。旧 `get_run` 继续为运行观察；不改 Goal 的领域验收入口。

共享的增量 run 投影器复用原生命周期校验，记录观察仅在 append 返回后推进；不保存第二份事件正文。历史加载按原投影把未完成 run 标成 orphaned，该值是读取派生状态，不补写终态。确认读取按 run 查小型投影，不扫描日志、Transcript 或 Blob。

进入 backend.append 后任意异常，使该 Runtime owner 的全部新确认查询抛 `WorkRecordingUnavailable`，后续成功也不解除。追加前拒绝参数不污染确认。不得把旧 get_run 的 completed 或新分配 sequence 当作成功追加证明；也不新增停止执行/重试写入机制。投影或合同解释失败只影响确认读取，不在已成功追加之后冒充写入失败。

冷读由 Product 确认原 writer 停止，再新开原日志与 reader；按实际可见记录判断，可能看到写后抛错的记录。loaded 不证明外部动作成功、断电耐久或可以自动续跑。不得用同一个 backend 的内存缓存冒充重新读盘。

## 验证与后续

本次验证：默认/匿名/未知事实，Product 下限及单 Work 强化，内存/JSONL/未声明 backend，受理和终态追加写前/写后失败，成功追加不能解除错误，旧/新/混合/非法合同读入，热查询无扫描，以及原 Work/取消/Goal 相关回归。优先复用已有测试路由，不新增 CI 门禁。

本次不切换 Coding/Session 默认装配、不删流式历史、不加入 Transcript 引用、共享 reader 或来源等待。来源绑定及保留承诺、Session bridge 消费者迁移、真实 SDK 默认来源闭环仍需第二切片落实。第一切片不据此宣称 HW-KD-003 全部完成。


## 实施与验证记录（2026-10-29）

实现位于 [recording.py](../../../src/loushang/harnesswork/recording.py) 与 [runtime.py](../../../src/loushang/harnesswork/runtime.py)。Codec 和确认观察在记录模块内部；原 run reducer 提取为共享增量实现，不新增执行器、存储文件或领域事件分支。异常缓存仅保留错误类型与短消息，避免 traceback 长期引用事件正文。

```python
runtime = WorkRuntime(event_log=event_log, executor=executor, recording_version=1)
run = await runtime.accept(operation)
await runtime.wait(run.run_id)
record = runtime.get_recording(run.run_id)
# record.run 是有依据的记录状态，仍不能代替 Goal 的领域验收。
```

Product 的持久要求可在构造时配置；单 Work 的强化要求由 `WorkRunSpec(recording_policy=WorkRecordingPolicy(require_persistence=True))` 提交。新增记录读取 API 从 canonical `loushang.harnesswork` 导出；原 `loushang.work` 根导出集合保持不变，已有转发模块继续保持同一对象身份。

| 验证 | 结果 / 范围 |
| --- | --- |
| Work 原测试路由 | 第一轮 181 项通过；追加两个领域事实写入故障用例后，受影响的 runtime 与 canonical API 复测 117 项通过；相关集合共 183 项 Work 测试 |
| HarnessWork、Method、Coding Work/Goal | 首轮 202 项通过，1 项公共 API 清单需同步；修订后该文件全部通过（含在 117 项复测中），7 项按非 live/非 host 选择器排除 |
| 基线 reader 兼容实验 | 使用 `5eadeb91c` 的原 JSONL reader 及 Run/Plan/取消 projector，读取旧→v1→回退旧的 3 个 run、每 run 两步骤；与当前投影一致，无重执行。原临时日志在产品树外；可复现探针已保存至 `scripts/dev/probe_work_recording_compatibility.py`，固定基线 SHA、临时生成输入并比较全部事件及三个投影 |
| Ruff / 修改源码类型 | Ruff 通过；本次修改的 6 个源码文件 mypy 通过 |
| 文档与架构 | 既有 9 项文档不变量、架构依赖图检查通过；本轮文档同步后另行复核链接 |
| 全仓 change-aware 入口 | 已实际运行，文档/架构/AI lint 通过；初次因共享 venv 的 mypy 启动脚本指向已删除目录而停止；修复本机启动脚本后 AI 全检查通过（937 passed）、Agent 154 passed。Coding 首轮 3382 passed / 565 failed，失败起点为 164 MiB runtime tmpfs ENOSPC，使用既有 LOUSHANG_RUNTIME_DIR 在私有磁盘目录重跑，565 项全部通过（382 deselected）；与首轮已通过的 3382 项合计 3947 项 Coding 用例通过。剩余路由结果已记录于 Transcript 引用切片交付文档；AppHost / AppService 有失败及未完成项，不宣称全绿。未改检查触发器或新增路由 |
| 包级 mypy 补充检查 | 完整 HarnessWork 检查另有 cli / agent_session 共 20 项既有错误；与 main 同命令输出逐字相同。本次 6 文件检查通过，不声称整个包类型检查全绿 |

全部 pytest 在沙箱外运行，不调用在线模型。热查询测试禁止 backend.query 后仍可按 run 获取确认状态；这是访问范围证据，不是吞吐/延迟 benchmark。受理、领域事实、终态各自覆盖写前/写后异常，后续成功写入不能解除原 owner 的不可确认状态。

初始实施自查之后，已完成三名独立 xhigh agent 的实现评审。发现并修复 ACK 后 observer 普通异常隔离缺口，115 项 runtime 回归通过，原 reviewer 确认关闭；同时补 API 冷读前提和可复现兼容探针。详见[评审与关闭记录](../architecture/harnesswork/key-designs/fact-retention-replay-review.md)。

当前可交付范围是显式启用的底座切片。后续[Transcript 引用切片](2026-10-29-work-transcript-references.md)已落实来源绑定、等待与取消、独立进程引用读取；普通 Coding 默认入口迁移、完整审计及流式裁剪仍未交付。广泛检查最终结果及尚未关闭的 Hosted 基线失败统一见该交付记录，不能据专项通过宣称全仓检查全绿。


收尾复现命令：`PYTHONPATH=src /home/dev/lsspace/loushang/.venv/bin/python scripts/dev/probe_work_recording_compatibility.py`。按仓库异步验证规则在沙箱外运行；只产生临时日志，不访问网络或重放工具副作用。

观察器内部普通异常的最终合同：backend 已 ACK 后，原控制必须照常收尾；新确认视图持续不可用。不能把观察器错误伪装成 append 失败，也不能返回旧 running 截点冒充完整确认。BaseException 系统退出/中断不在这个普通错误隔离承诺内。
