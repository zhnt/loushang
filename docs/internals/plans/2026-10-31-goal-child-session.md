# Goal 批次执行 Session：集成准备与实施检查点

- Authority: descriptive；状态：R3 独立三视角设计评审完成，用户已明确授权实施 R3；实现与离线验证完成，实施后三视角代码评审及修正复核均已完成；真实任务已按原规划额度暂停；在线完整验收未通过。
- 设计：[GMW-KD-SESSION-02 R3](../architecture/goal-method-work/delegated-session-execution.md)；[三视角关闭记录](../architecture/goal-method-work/delegated-session-execution-review.md)。
- 工作分支：feat/goal-child-session；代码 lane：.worktrees/code。未修改有历史脏资料的 Harness lane。

## 已有能力集成核查

2026-10-31 使用 git merge-tree 检查 Harness 修订 `3aac81d8e` 与已完成仓库 Goal 分支 `f024cb734` 的组合；该命令只生成候选 Git 对象，未修改工作树、分支或产品代码。此核查不是运行验证，也不构成新模式实施。

| 接缝 | 核查结果 / 实施时处理 |
| --- | --- |
| 原仓库 Goal profile | 保留 RepositoryTask/Profile、BatchPlanningPolicy、独立验证、可信评审和 detached 读取；不重写第二套仓库 Goal |
| _goal_planning.py | 唯一文本冲突是 prepare 已抽到 _goal_planning_shared.py，而主线后来在原 prepare 加入 Transcript 来源绑定。应将现有绑定逻辑移入原共享 prepare，不能简单选 ours/theirs 或保留重复 prepare |
| CodingGoal.open → _open | 自动文本合并会保留公开 transcript_retained_until 参数，却不传入新 _open，后者仍使用该变量。必须同步参数传递与校验；无文本冲突不代表接口兼容 |
| 规划 executor | 旧共享 prepare 仍使用 SessionTurnExecutor(turn=...)，主线已使用 turns=(turn,)；合并应采用当前合同，并保留 _bind_source |
| 仓库 profile 实施 executor | 同 Session 原路径也须协调现有来源准备；未来 child 委派路径明确不绑定父 Transcript。父规划来源与子实施报告分别验证 |
| 来源冷读 | 按 R3 接入受支持仓库 policy 的窄分支，保留未知 policy、错绑与损坏错误，不把这些情况改成 not_declared |
| 失败批次观察 | 原 delegate 失败时两种成功报告都可能缺失；仅新委派 operation 按 R3 区分局部失败轨迹与成功报告损坏，保护旧历史语义 |

## 授权后的有界实施顺序

1. 已完成：底座以 caaff3945 本地合入 main，并同步此任务分支；源代码修订为三视角复核的 3aac81d8e。Coding 3991、Harness 5959、TUI 单元 1322、render contract 317 项通过；详见[底座交付记录](2026-10-31-child-session-consolidation.md)。
2. 接续并协调原仓库 profile 与同 Session 来源记录，先验证旧公开入口、默认路径、原真实任务合同和冷读。历史 #125 修正不得再次作为新缺陷修复交付。
3. 按已接受 R3 实现 Product 私有委派适配，调用原 Harness/Method/Work；先接 reuse/fresh，验证 A→A→B，再接固定来源 inherit。按 DS-01—10 分别验证多 Session 身份、输入、取消、容量/清理、历史及证据，未启用模式明确拒绝。
4. 对冻结的原始缺陷工作树执行新模式验证；新模式需要自己的真实运行证据，不沿用旧成功结果。没有发生实质调整就如实保留未证明状态。
5. 完成独立评审、现有变更路由和交付记录；不扩 CI 门禁，不以设计完成声称实现完成。

2026-10-31 用户明确要求“请你开发实施R3”，随后补充“开发实施完毕R3后启动三视角评审代码”。已合入原仓库 profile f024cb734，合并提交 f410f10ce；原仓库 Goal 19 项离线测试通过。上述集成事实不代表新模式验收通过。

## 实施与代码评审进展

- `82864e9ad` 已实现私有仓库 profile 的 reuse/fresh/inherit，仍由原 Harness factory/runtime 驱动子 Session，由原 Method/Work/Blob 完成交接与验收。原公开默认同 Session 路径保留。
- 三位独立 xhigh 代码评审发现容量前置检查、取消释放的清理凭据、实际来源库身份、步骤证据关联、未知私有 schema 五类问题，已在 `2a046fa3b` 修正并增加回归，原三位 reviewer 独立复核全部关闭；见代码评审记录。
- 同步来源观察是现有 TranscriptSourceReader 的调用形式补充；同步冷读使用独立 reader，close 失败以保留 reader 的异常返回；活跃 Goal 仍由 owner 关闭 reader 后释放父 Session。没有另一套库身份算法或历史读取实现。
- 初轮目标兼容回归 175 passed / 7 skipped，修正回归 28 passed，取消释放和多 Session/冷读末轮 2 passed。尚未以此声称在线动态重规划已验证。
- 真实 #125 验证另建短期 worktree/分支 `validation/goal-r3-issue125`，从原缺陷基线 `5eadeb91c` 创建。任务包与运行资料置于产品树外；不回填旧成功记录。

## 固定实现的本地检查

以下检查针对 `2a046fa3b` 的代码，后续仅修改交付文档：

| 检查 | 结果 |
| --- | --- |
| repository Goal + Coding Work 初轮完整回归 | 175 passed / 7 skipped |
| 评审修正专项：容量、实际来源、固定历史及兼容 | 28 passed |
| 最后 SDK 合同：取消释放重试、多 Session 与冷读 | 2 passed |
| 既有 make check-harness（保留 not live / skip-host-runtime） | lint、778 个源码文件类型检查通过；6382 passed / 124 skipped，1302.83 秒 |
| 合入既有 read 修正的 Coding 集成回归 | 163 passed，21.92 秒 |
| 生成式架构依赖清单 | --check 通过 |

没有扩展 CI gate，也没有把跳过项写成通过。当前源码位于任务分支，尚未合入 main 或远程发布。三视角评审接受范围为本轮实现；真实模型的执行、计划变化和独立验收另按实际结果记录。

## 本轮真实 Kimi Coding 验证

运行固定在代码 `2a046fa3b`，隔离任务工作树使用 #125 原始缺陷基线 `5eadeb91c`。使用 Kimi Coding 认证；RC-01—06、允许修改的两个文件、独立 verifier、Method 和 8 次规划额度均在运行前冻结。模型没有修改验收器或额度。

1. 第一批 fresh A 实施后，独立检查发现 3 个合同失败；315 项原回归通过。
2. 模型根据失败，把剩余检查路线改成 reader/tests 修复；第二批 reuse A 实际执行，随后 21 项合同与 318 项回归通过，原 verify_all 也通过。
3. 可信宿主评审发现：已知 `is_file=False` 的分支仍调用 read_bytes，使原 IsADirectoryError 变成其他异常并增加副作用。以原 RC-03/05 拒绝候选，有独立反例，不是为了展示重规划而制造拒绝。
4. 模型据此新增 inspect，再安排修复；Product 选择 fresh B，第三批实施在新子 Session 完成。独立反例复测变为 IsADirectoryError、零次字节读取；范围审查确认只改约定两个文件，原有测试定义全部保留。
5. 第 8 次规划选择 check(regression)，该批成功。模型仍计划后续检查与 verify_all，但规划额度已用尽；第 18 次 advance 返回 paused，未再受理第 9 次规划；没有增加额度或补写完成证明。

这轮证明了真实 A→A→B、真实测试失败和评审拒绝进入后续规划并驱动修改。尚不能据这些局部成功声明本轮 Goal completed；尤其早一次 verify_all 针对被拒绝旧候选，不覆盖第三次修改后的新候选。在线 inherit 未在这轮执行，其证据来自离线 SDK 的固定父截点、多 Session、附件与损坏/错绑验证。

收敛结果：运行已退出并关闭 owner；冷读返回 `paused / not_satisfied / repository_verification_required`，planning_intents 为 8。最后 check 为 21 项合同和 318 项回归通过。该退出代表有界试验未达到完成条件，不是 R3 代码评审重新出现阻断。实验工作树和完整运行证据保留，后续若要继续在线验收，应先设计剩余额度如何约束计划收尾，不能在本轮悄悄提高固定预算。现有默认规划额度及提示合同不是本次 R3 Session 选择的改动范围。

本轮不重跑已验证的整个主线所有平台；本地结果仅限上表、专项回归和文档检查。变更路由已检查，跨平台/真实 LSP/host runtime 等未在本轮执行，不据此声明整个远程 CI 已通过。
