# Work → Transcript 引用闭环交付

- 范围：用户授权“先收尾第一切片，再实现 Transcript 引用闭环”。第一切片收尾提交 `d1bfefcea` 已本地合入 main；本切片分支 `feat/work-transcript-references` 基于该提交。
- 设计：[HW-KD-004 R2.2](../architecture/harnesswork/key-designs/transcript-references.md)，协同 [HW-KD-003](../architecture/harnesswork/key-designs/fact-retention-replay.md) / ARD-019。未改变 Goal、Method、Work 的权威与执行器归属。
- 状态：引用闭环已实现，三视角独立评审阻断全部关闭。完整审计、正文裁剪及各 Product 默认入口迁移仍未交付。

## 可用行为

Product 提供原 Session 文件、原 store state root、稳定逻辑 binding_id 和明确保留截止时刻，建立 `TranscriptSourceReader` 与 `WorkTranscriptSource`。新 Session 的 JSONL 可尚未生成：`inspect_identity()` 只验证已登记库并携带预期会话；消息交接必须读取真实文件，验证 header、目标记录与父链。没有创建额外 Session、锁、记录库或索引。

`create_coding_work_runtime(..., transcript_source=source)` 把配置交给共享 Session bridge，自动启用 recording v1；可用 `recording_policy` 强化持久要求。普通未绑定调用维持原默认行为。标准 bridge 在受理时冻结每步、每次 prompt 的交接清单，提交后收集的 record_id 只是定位信息，持久读成功才产生引用和完成事实。

`get_recording` 或受控冷读的 `project_work_recording` 提供记录依据；`project_work_transcript` 核对预期交接，`resolve_work_transcript` 使用原授权 reader 一次批量读取同源引用。固定 record_id 和原字节父链摘要不依赖当前 head。少一整组、部分引用、缺完成、错误版本/身份/摘要、超过期限均不能冒称来源完整。失败或取消不改写已有历史，也不重发模型或工具调用。

共享机制位于 Harness Transcript / HarnessWork；Coding factory 只透传配置。Product 持续负责留存与清理，必须在截止前保留原存储和 admission。首个示例使用任务专属目录，未接入普通 Session 自动删除；不提供提前终止承诺的接口。

## 手工复现

使用本项目 Python，在私有磁盘目录下选择一个尚不存在的输出目录。该示例使用真实 Coding SDK、真实 Session/Transcript 与 Work JSONL，但模型传输为确定性离线回复，不访问网络或凭据。

```bash
cd /home/dev/lsspace/loushang
GOAL_PY=/home/dev/lsspace/loushang/.venv/bin/python
GOAL_BASE="$(mktemp -d /var/tmp/loushang-transcript-demo.XXXXXX)"
PYTHONPATH=src "$GOAL_PY" examples/coding/28_work_transcript_references.py --output-dir "$GOAL_BASE/run"
PYTHONPATH=src "$GOAL_PY" examples/coding/28_work_transcript_references.py --output-dir "$GOAL_BASE/run" --reopen
```

首条命令创建两步骤、三次 prompt，并在关闭 writer 后读取；第二条命令由独立进程冷读，只使用 Product 自身保存的 `binding.json`，不打开 SDK、执行模型或恢复 Work。绑定清单是可信 Product 配置，Work 引用不能自行指定物理路径。示例保留承诺为一天，过期后读取会明确失败；运行目录在承诺期内应保留。

本次真实产物：42 条 Work entries，预期组 `0:0 / 1:0 / 1:1`；6 条唯一消息引用。独立进程返回 `cold_read_verified`、`handoffs_complete: true`，一次内容读取 7,449 字节，7 个不同祖先参与摘要。数字是这次小场景观察，不是吞吐或大历史性能承诺；每次仍完整解码一份来源文件，默认上限 64 MiB。

## 独立评审关闭

方法：本地干净 archmethod master `0f9bd3ff51afabeaaf76cc38dff1ceb279b7d37e`。三个独立 xhigh agent 先审固定设计，再审实现，不读取彼此报告。接受角色为获得本任务实施授权的 agent，不冒称用户逐项评审。

| 视角 | 发现与修订 | 关闭证据 |
| --- | --- | --- |
| 职责与复用 | 实例级取消标记可能污染复用 executor 的后续 Work；改为按 run_id 隔离。交接读取期间后续消息会改变集合；改为限定 prompt 捕获窗口并冻结快照 | 原 reviewer 独立复现并验证两项修订；直接 WorkRuntime 复用及读取中插入 message_end 回归通过 |
| 运行与失败 | 阶段取消正常返回会误记 WorkStepCompleted；改走原 CancelledError，覆盖最后 after_turn。检查直接读原同步取消受理状态，关闭 driver 尚未调度的窗口 | 原 reviewer 独立探针覆盖 prompt 前、source read、after_turn：均只有 WorkStepCancelled 和一个 WorkRunCancelled；139 项相关测试通过 |
| 数据与兼容 | 补 canonical 冷读 API 导出；区分延迟文件的 store identity 与记录验证；确认原字节摘要、预期组与确认截点 | 原 reviewer 独立重算真实持久产物全部摘要，并使用旧基线 reader 核对真实 SDK 事件及三个投影，无差异 |

三视角均无未关闭阻断。R2.2 的延迟文件身份观察、按 run_id 隔离及集合冻结已纳入独立实施复核；不新增系统组件或改变旧生命周期合同。

## 验证

| 验证 | 结果 |
| --- | --- |
| Work / HarnessWork / Method / Coding Work-Goal / SourceReader 离线回归 | 413 passed，7 skipped（既有非 host 选择器） |
| 后续冻结/延迟文件定向回归 | 31 passed |
| 最终取消修订与原 Runtime / Session 回归 | 139 passed，覆盖计划步骤取消不会被记完成 |
| 修改核心 5 个源码文件 mypy | `--follow-imports=silent` 通过；普通全依赖检查仍有既有依赖类型错误，未声称全包无错误 |
| Ruff / diff whitespace | 通过 |
| 真实 Coding SDK 与新进程冷读 | 两步骤三次 prompt、6 条引用全部通过 |
| 固定旧 reader / 混合历史 | `scripts/dev/probe_work_recording_compatibility.py` 使用 `5eadeb91c`，旧→来源 v1→回退的全部事件及 Run/Plan/取消投影等价；不重执行 |
| 第一切片容量故障重跑 | Coding 565 个失败项全部通过；与首轮 3382 个通过项合计 3947。原失败为 164 MiB runtime tmpfs ENOSPC，使用既有 `LOUSHANG_RUNTIME_DIR` 切换到私有磁盘目录，未改产品或选择器 |

pytest / 异步 SDK 探针均按项目规则在沙箱外运行。没有新增 CI workflow、触发器、平台矩阵或合并门禁，也没有为示例新增单元测试。已通过且不受新修订影响的 AI/Agent/Coding 未重复运行。

## 广泛检查与交付限制

既有 change-aware fallback 选中的剩余离线路由已处理。下表计数属于各自路由，存在重叠，不相加宣称独立测试总数。

| 路由 | 结果 |
| --- | --- |
| HarnessTUI / Coding UI | 1070 / 613 passed，各自 lint、typecheck 通过 |
| TUI unit / playback | 1322 / 317 passed |
| Harness / Hosting | 6361 passed、121 skipped / 517 passed、53 skipped |
| CI / Foundation / AppServer unit / e2e smoke | 144 / 110 / 825 / 2 passed，AppServer lint 通过 |
| Architecture（引用切片） | 653 passed、1 failed；唯一失败为既有 wheel RECORD 读取者未登记。补齐既有 owner 清单后该项复测通过，未扩大扫描或门禁范围 |
| AppHost（引用切片之前的基线） | 473 passed、1 skipped、2 failed；发现失败后主动中断，余项未完成 |
| AppService（引用切片之前的基线） | 1154 passed、5 skipped、10 failed；发现失败后主动中断，余项未完成 |

因此本次专项交付通过，不宣称全仓检查全绿。AppHost / AppService 未完成部分、其他平台和在线模型路径不在已验证范围。广泛检查日志分别保存在本机 `/tmp/work-closeout-<scope>.log`，机器临时日志不作为长期交付保证。

失败后续项（不放宽恢复校验来绕过）：

1. **V2 Resume 的 dormant LSP owner 集合不一致。** stdio 恢复实测捕获 `CodingResourceCatalogAdmissionError(reasons=["resume_plugin_participation_changed"])`，且不含引用切片的 main 可复现失败。`embedded_resume._capability_plugins_enabled` 将 on-demand LSP 计入参与者，Hosted 据此冻结两项插件 owner；bootstrap 按历史 startup receipt 将未选中 LSP 的会话延迟装配，期望集合为空，严格比较拒绝。应在独立修复中统一 Hosted / Embedded 与 bootstrap 的 receipt 判定，保留严格匹配，覆盖 dormant、历史 eager/无 receipt、disabled、输入只提交一次及清理。比较依据变化来自已有提交 `1f5d9d129`（#798）。
   2026-10-30 后续：本项的参与判定已由共享代码规则修复，原 stdio 恢复失败用例通过；范围和验证见[修复记录](2026-10-30-resume-dormant-lsp.md)。以下两项并未据此关闭。
2. **终端恢复与首次创建异常。** `test_G17_TERMINAL_START_CANCEL_durable_recovery_reclaims_and_can_relaunch` 在首次创建时遇到 `snapshot_required`；`test_G16_PRODUCT_TERMINAL_process_death_recovers_history_not_execution` 的 cwd/user_home 两项恢复等待超时。首次创建也在 main 重现；这些失败尚未证明与上项同因。
3. **恢复样本检查的 startup decision roots 预期。** `test_measure_g18_native.py` 六项失败，表现为根集合为空及解包失败；发生在引用切片之前的检查中，尚未完成根因分析，不归类为容量故障。

第一切片 Coding 的 ENOSPC 已经通过磁盘目录重跑关闭；不能用那次环境故障解释上述失败。引用功能仍为显式接入，未修改 Hosted 恢复装配路径。

边界：来源消息可读不等于附件字节可读，不等于完整审计，也不等于 Goal 当前验收通过。附件继续由原 Blob reader 核验；后续删除来源不会使历史完成自动变成当前有效。
