# M1 跨平台验收：已有证据、真实缺口与最小补验方案

## 状态与结论

- Authority: descriptive — 既有运行证据核对；§5 补验方案为 proposed，不改变已接受机制。
- Design status: evidence-inventory-complete；一次性原生补验已完成，结论限冻结源码与本次 Windows 环境，不重新设计 M1。
- Implementation status: verification-complete；产品源码/测试和主线 workflow/gate 未变；临时分支已删除，原生结果见 §7。
- Owner: Harness Package lifecycle 验证；执行者 Codex，2026-11-05。
- 固定源码：main `66a74974989f7e4e957d7f0cc89a3cd0631dda22`；方法为本地干净 archmethod master `0f9bd3ff51afabeaaf76cc38dff1ceb279b7d37e`，未核对方法 upstream。

**已有 Linux/POSIX 结果已复用，后续 Windows 原生补验 28 项全部通过。** 本轮直接下载并核对 PR #872 的 JUnit：33 项 POSIX materialization 与 12 项 verified-tree transfer 通过；27 项 Windows materialization 全部跳过。Windows 的其他绿色报告不代替这 27 项。

后续在真实 Windows 环境执行既有完整 27 项，并以一个树外场景验证部分删除后重试，已独立核对全部通过；原始盘点与计划保留如下，当前关闭证据见 §7。没有重新开发 M1。tree abort/删除规则收敛、关闭结果不明机制修正和性能测量继续排除。

适用合同：[平台 Adapter](materialization-platform-adapter.md)、[树核验](materialization-tree-validation.md)、[文件写入](materialization-file-sinks.md)、[升级兼容约束](../../decisions/accepted/ARD-008-workspace-upgrade-compatibility.md)。沿用既有 owner、native handles、journal/身份和异常合同；只按验证方法核对版本、平台、节点、结果及局限，不新增总体架构或 ARD。

## 1. 版本绑定与核查范围

| 已交付范围 | PR / 受测 head | 核查结果 |
| --- | --- | --- |
| M1a receipt 核验、M1b finish/reuse | [#854](https://github.com/zhnt/loushang/pull/854)，`6f1338a638bb8a8eb8448a5a0374ed13f93259fb` | 原 [run 41779057427](https://github.com/zhnt/loushang/actions/runs/41779057427) 为绿色；完整 43 job 清单中 `windows-shell` 为 skipped |
| M1c 树读取/核验 | [#859](https://github.com/zhnt/loushang/pull/859)，`cf083ef61944eb8d8cce485bd6a7d34ff8c4e707` | 原 [run 41786722997](https://github.com/zhnt/loushang/actions/runs/41786722997) 的 24 job 中 `windows-shell` 为 skipped |
| M1c 文件写入/reuse | [#863](https://github.com/zhnt/loushang/pull/863)，`8972e6bf875259364b55b4da5991d416dc5d5ae9` | 原 [run 41794404665](https://github.com/zhnt/loushang/actions/runs/41794404665) 的 24 job 中 `windows-shell` 为 skipped |
| 最新已查完整回归 | [#872](https://github.com/zhnt/loushang/pull/872)，`0dea5cf2b9300af8f6f76ed8fb192716b2440ec8` | [run 41963120951](https://github.com/zhnt/loushang/actions/runs/41963120951) 共 36 success / 7 skipped；其中 `windows-shell` skipped；下节直接核对报告内容 |

从 Git 对象读取比较，以下五份 M1 源文件及三份相关测试，在 #863 head、#872 head 和当前 main **逐字相同**。因此 #872 的实际节点结果可以绑定到本轮 M1 源码，无需重跑已有 POSIX 用例。这是八份文件的版本证据，不声称所有传递依赖或任意外部环境相同。

| 当前实现 | 当前 SHA-256 前 12 位 |
| --- | --- |
| [_materialization_shared.py](../../../../../src/loushang/harness/resources/packages/plugin_lifecycle/_materialization_shared.py) | `204df8476b4c` |
| [_tree_validation.py](../../../../../src/loushang/harness/resources/packages/plugin_lifecycle/_tree_validation.py) | `53fdc378fb7e` |
| [_file_sinks.py](../../../../../src/loushang/harness/resources/packages/plugin_lifecycle/_file_sinks.py) | `d820047064fd` |
| [posix_materialization.py](../../../../../src/loushang/harness/resources/packages/plugin_lifecycle/posix_materialization.py) | `26ca6b162e01` |
| [windows_materialization.py](../../../../../src/loushang/harness/resources/packages/plugin_lifecycle/windows_materialization.py) | `bc107718d861` |

三份测试是 [POSIX](../../../../../tests/harness/resources/packages/test_plc9b_posix_materialization.py)、[Windows](../../../../../tests/harness/resources/packages/test_plc9b_windows_materialization.py)和 [verified-tree transfer](../../../../../tests/harness/resources/packages/test_plc9b_verified_tree_transfer.py)。完整 SHA、Git 对象来源及逐节点结果保存在产品树外归档，不在产品树中复制源码或原始 CI 报告。

## 2. 可直接复用的实际结果

下载 #872 的四个 `module-harness-{0,1,2,3}-pytest-report`，按 `(classname, name)` 合并并检查无重复；以下 72 个相关节点身份唯一：

| 测试模块 | 平台 / passed / skipped / failed | 可证明的范围 |
| --- | --- | --- |
| `test_plc9b_posix_materialization.py` | Linux；33 / 0 / 0 | 当前 POSIX Store 的 receipt、发布/reuse、只读、身份拒绝、恢复、GC 和失败清理原场景 |
| `test_plc9b_verified_tree_transfer.py` | Linux；12 / 0 / 0 | 原传输协议与验证规则；不是 Windows OS 原语验证 |
| `test_plc9b_windows_materialization.py` | Linux；0 / 27 / 0 | 测试文件、参数化节点仍被收集；skip 原因为 Windows-native contract，不是原生通过 |

模块 workflow [package-unit-quality.yml](../../../../../.github/workflows/package-unit-quality.yml) 的 runner 是 `ubuntu-latest`。Windows 模块的 [模块级 skip](../../../../../tests/harness/resources/packages/test_plc9b_windows_materialization.py#L61) 明确为 `os.name != "nt"`；不能把 Linux job 绿色写成这 27 项已通过。

另下载 #872 的 `apphost-harness-windows-junit` 与 `resume-turn-windows-2022-pytest-report`，其中六份 XML 共 97 个 passed 节点，零失败/跳过。它们验证各自的 AppHost/G8/G9/G10/G13/Resume 合同，**没有上述 Windows materialization 测试模块的节点身份**。这不证明执行期间绝未间接调用 M1 代码，也不足以替代 M1 对象级断言。

原切片的树外验证继续作为各自限定版本的补充证据：M1a 六项、M1b 十项、树 scanner 十七项、file sinks 六十八项。其范围和源码绑定见原评审记录；阶段间可能重叠，不合并成“额外原生覆盖”。特别是模拟 Windows reader/Writer 的 fault 轨迹不能称为真实 Windows handles 已验证。

## 3. 四个切片与已有 Windows 节点的对应

下列名称均指同一既有 `test_plc9b_windows_materialization.py`，只是举出代表节点；最小方案执行完整 27 项，不按此表截取子集。

| 切片 / 实现机制 | 既有代表节点 | 当前证据判定 |
| --- | --- | --- |
| M1a `validate_receipt_at_root`，只读 journal 与 native tree 身份 | `test_windows_read_only_root_store_preserves_journals_and_file_bytes`、`test_windows_read_only_dependency_store_binds_settlement_and_bytes`、`test_windows_read_only_root_store_refuses_partial_journal_without_repair` | POSIX 同类结果及原静态/差分证据可用；这些 Windows 节点当前均 skip，需原生执行 |
| M1b `finish_verified_tree`，授权先于发布、精确 reuse、lost receipt 恢复 | `test_windows_role_stores_publish_exact_trees_and_reuse_same_receipts`、`test_windows_dependency_store_reuses_content_tree_and_ref_wide_tombstone`、`test_windows_store_recovers_renamed_tree_when_receipt_delivery_is_lost` | 现有用例已表达目标行为，不需要重写执行机制；缺当前原生结果 |
| M1c scanner，full/partial 观察、真实 reader/identity/reparse | `test_windows_read_only_root_store_refuses_file_swap_after_tree_validation`、`test_windows_store_rejects_nested_reparse_before_namespace_rename`、`test_windows_store_gc_deletes_exact_root_and_replays_absence` | 全量核验/普通 GC 的原生场景待执行；部分删除后重试需另列，见 G2 |
| M1c file sinks，真实 Writer、flush/close、完成通知与 abort | `test_windows_role_stores_publish_exact_trees_and_reuse_same_receipts`、`test_windows_store_rejects_staging_handle_swap_and_closes_every_handle`、`test_windows_rejection_aborts_partial_tree_and_releases_handles` | 原生发布/reuse/失败清理场景待执行；细粒度短写、flush/close/callback 故障已有树外对照，不据此新增一套原生矩阵 |

## 4. 原盘点缺口与排除项（执行前记录）

| ID | 类型与依据 | 关闭条件 |
| --- | --- | --- |
| G1 | **缺执行证据**：已有 27 项 Windows 原生用例，在所查最新报告中全部 skip；四次已查 PR 的 `windows-shell` 都 skipped | 同源码/测试身份的 Windows 原生运行，27 项身份精确匹配、全部 passed、零 skipped/error/failure；保留环境及结果 |
| G2 | **缺专门场景**：Windows 现有 GC 用例测试完整删除和再次删除得到 already_absent；未在首次删掉文件后注入失败再重试。POSIX 的 `test_posix_store_gc_retries_after_partial_file_removal` 实际通过，但不能替代 Windows 路径 | 树外一个 Windows-native 场景：真实删除第一项后失败；保留 tombstone/原身份，恢复协作者，再由同一 settlement 重试成功；第三次查询/删除为 already_absent，并核对句柄释放及范围 |

G2 对应已有 `_collect_tree(..., allow_partial=True)` 的消费者；只验证现有恢复语义，不改 GC 授权或增加删除能力。“partial journal tail”“建树失败后 abort”与“GC 已删一部分后重试”不是同一场景，不因名字含 partial 就认为覆盖。

原 file close 报错后的句柄结果不明机制、tree abort/删除算法共享、legacy 退出与性能测量仍按原专项排除。没有把这些事项追加为本轮必须实现的缺陷，也没有发现或复现新的产品 bug。G1 是未知运行结果，G2 是证据场景缺口，两者均不能写成“当前代码已失败”。

## 5. 最小补验方案（历史计划；执行结果见 §7）

### A. 一次既有 Windows 模块运行

首选已有 Windows x64 开发/验收环境、Python 3.11 和现有项目依赖，checkout 固定受测版本，记录上述八个文件 SHA。保留原 non-live/skip-host-runtime 选择；不重跑已取得的 45 个 Linux/POSIX 节点，不启动整个 Windows Shell/Worker/GC 恢复大矩阵。

PowerShell 示例（在仓库根目录、依赖已就绪时；只作为后续执行说明，本轮未执行）：

```powershell
$M1Python = Join-Path $PWD '.venv\Scripts\python.exe'
$M1Evidence = Join-Path $env:TEMP ('loushang-m1-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $M1Evidence | Out-Null
$env:PYTHONPATH = Join-Path $PWD 'src'
git rev-parse HEAD | Set-Content (Join-Path $M1Evidence 'commit.txt')
& $M1Python scripts/dev/run_pytest.py `
  tests/harness/resources/packages/test_plc9b_windows_materialization.py `
  -m 'not live and not requires_host_runtime' --skip-host-runtime --strict-markers `
  -q --junitxml="$M1Evidence\windows-materialization.xml"
if ($LASTEXITCODE -ne 0) { throw 'M1 Windows tests did not pass; preserve the evidence.' }
& $M1Python scripts/dev/verify_pytest_xml.py `
  "$M1Evidence\windows-materialization.xml" --require-tests-count 27
if ($LASTEXITCODE -ne 0) { throw 'M1 Windows report did not meet the existing report rules.' }
```

还须将 XML 的完整节点集合与树外 `windows-existing-nodeids.json` 比较，27 的数量相等本身不证明身份匹配。记录 Python/OS/架构、源码/测试 SHA、真实执行/skip 和用例时长；source 不匹配先重新评估，不沿用本清单自动关闭 G1。

预算边界：只做一个 Windows 环境的一次模块运行，不并列平台/版本矩阵、不自动重试、不调用模型。Windows 实际耗时尚未取得，不能用 POSIX 的 testcase 时长外推。环境不具备时保留 G1，不在 Linux 把 skip 改成 pass 或安装模拟层来代替 native。

### B. 一个树外部分删除重试场景

A 通过后，仅在同一隔离环境用原 request/candidate/settlement 夹具补 G2；脚本保存在产品树外，不扩 PR gate。流程：真实 Windows Store stage → 获取原 settlement → 在原 `windows_unlink_at` 返回后仅首次抛错 → 确认首次操作失败且 tombstone 保留 → 恢复原函数 → 用原 settlement 重试并检查 deleted/物理树不存在 → 再次删除为 already_absent → 核对仅原 owned 目录受影响、root/文件句柄可释放。不得用纯假 reader/删除函数代替第一次实际 native 删除。

本项尚未编写或运行，不将“方案已列出”写成 Windows partial retry 已验证。若现有语义不满足预期，先形成具体复现，再决定是否需要修复或调整原合同；不直接开发新的恢复状态机。

### 执行入口选择与 gate 边界

现有 [Windows Shell workflow](../../../../../.github/workflows/windows-shell-compatibility.yml#L343) 已列出这个模块，根 [暂停策略](../../../../../scripts/ci/select_checks.py#L53)明确暂停该路线。当前绿色 PR 的 skip 与此一致，不能简单点击重跑来取得缺失证据。

现有 Windows 环境手动执行 A/B 可保留所有 gate 不变。若只能借助 Actions，需要另行提出并取得工作区明确要求的授权，写清一次性触发、精确覆盖、Windows 环境、实际预算、与原 gate 的重叠及撤回方式；本轮没有新增 workflow/job/test route、恢复暂停项或绕过 pause selector，也没有发起该审批。

## 6. 证据保存、静态复核与局限

树外根目录：`architecture-analysis/plugin-harness-audit-20261104/m1-platform-evidence-20261105/`。保存：

- `pr-provenance.json`、四个完整 `jobs-<run>.json`：PR/head/merge/run 与暂停结果；查询包含全部 job 数，不只读取连接器第一页。
- `selected-artifact-metadata.json`、六个下载 artifact 下十份 XML、`downloaded-xml-sha256.json`：绑定 run/head、artifact ID 和解析内容。API 返回的 ZIP digest 仅记录，未冒称重算过原 ZIP；实际下载后 XML 字节另算 SHA。
- `source-provenance.json` 与八份源码/测试快照：三个切点的完整 SHA 比较。
- `junit-inventory.json`、`windows-existing-nodeids.json`：72 个唯一相关节点及完整 27 项 Windows 身份，区分 pass/skip，便于后续精确核对。

盘点阶段只读查询 GitHub、读取现有归档、解析源码/XML并静态核查，未执行产品或 native 实验；其后按用户要求做的一次性原生补验见 §7。按平台/版本/身份、真实断言、范围/门禁三个方面由同一实施者复核，不称为三位独立 agent 评审。没有穷尽其他所有历史手工运行或仓外 Windows 记录；若找到同源码同场景的新证据，先复用，再缩减 G1/G2。该盘点时的 native 待验证状态已由下节对应结果更新；未覆盖环境的支持结论不随之扩大。


## 7. 一次性 Actions 执行、验收与入口退出（2026-11-05）

用户要求“actions 可否执行一次然后删掉”“不要让后面变成门禁”。实际采用现有 `quality.yml` 的[手动指定 ref 机制](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/manually-run-a-workflow)：仅在临时分支 `validation/m1-windows-once-20261105` 替换为单一 `workflow_dispatch` job，不创建 PR、不合入 main、不改变暂停 selector 或 required-check 配置。一个 `windows-2022` runner、Python 3.11、job 上限 10 分钟，测试步骤上限 5 分钟；权限只有 contents read，无 push/PR/schedule 触发和 quality-gate job。

执行记录须区分启动失败与实际测试，不能把两次 dispatch 写成一次：

| 记录 | 结果 |
| --- | --- |
| [首轮 41977319704](https://github.com/zhnt/loushang/actions/runs/41977319704)，临时提交 `7c824450ff6ad38e2a98e2c7b69dd338a66241f6` | 准备脚本误用系统 Python；依赖装在项目 `.venv`，import 报 `ModuleNotFoundError: packaging`。用例未启动，无 JUnit，不是产品测试失败；日志已归档 |
| [修正后 41977801531](https://github.com/zhnt/loushang/actions/runs/41977801531)，临时提交 `ca41ac081d40d88b42c7a91ec3b122965277df78` | 三个 Python 步骤统一使用 `uv run --no-sync python`。全部 28 项 passed，零 failed/error/skipped；pytest 2.35 秒；完整环境/源码/节点验证步骤通过 |

因此共有两次手动 dispatch，**原生 suite 实际执行一次**，没有重跑已完成的用例。第二轮环境为 Windows Server 2022（10.0.20348，AMD64）、项目 CPython 3.11.15。记录不把 setup-python 的系统 3.11.9 当作实际受测解释器。

### 独立复核与缺口关闭

实施者下载 artifact `m1-windows-oneoff-20261105`（ID `13392581784`）后再次解析 JUnit/JSON，并核对：

- 27 个原 Windows 节点与盘点保存的完整集合精确一致；另一个节点为树外 `test_windows_gc_retries_after_real_partial_delete`；共 28 个唯一 passed，零跳过/错误/失败。
- 八份原源码/测试的 SHA 在 runner 执行前逐字匹配 §1 版本，五份实际加载的 M1 模块路径在 checkout 内且 SHA 匹配；产品源码及测试未修改。
- 树外场景真实删除首个文件后注入 OSError，首次操作失败且 tombstone 保留；恢复原函数后用原 settlement 重试得到 deleted，随后为 already_absent；剩余内容/树外哨兵保持，owned 根可移动并移除。
- 树外脚本在 Windows 写出时自然转成 CRLF。artifact 的原始字节 SHA 单独保存；LF 归一化后与模板字节完全相同。runtime provenance 中该脚本 hash 是 LF 模板 hash，不冒称它是 CRLF 文件的字节 hash；八份产品源码/测试的匹配没有做此归一化。

**G1、G2 在冻结源码、该 Windows x64/Python 3.11 环境与上述场景范围内关闭。** 与既有 POSIX/传输证据共同支持当前 M1a/M1b、scanner、file sink 的限定验收；不声称所有 Windows 版本、所有故障组合、macOS 或整个 Store 架构均已验收。tree abort/删除算法收敛、关闭结果不明修正与性能仍在原排除范围。

### 删除与证据留存

JUnit、日志、执行命令、源码证明、workflow/树外脚本原文以及含两个临时提交的 Git bundle 已先保存到产品树外 `oneoff-actions/`。随后已删除远程临时分支，私有临时 clone 和本次 Go 校验缓存也已移除；原控制/长期 lane 无临时 workflow 提交。远程 main 保持 `66a74974989f7e4e957d7f0cc89a3cd0631dda22`，主线 `quality.yml` 字节未变。

该临时 ref 已不存在，不能再从该 ref 手动触发。Actions 运行历史继续作为证据保留，它不构成 required check 或未来触发入口。没有新增常驻 workflow/job/平台矩阵，没有恢复暂停 gate。原始失败记录没有删除或伪装为通过。

树外 `oneoff-actions/result.json`、`artifact/verification.json`、`artifact/provenance.json`、`artifact/windows-materialization.xml`、`successful-job.log`、`attempt1-job.log` 和 `remote-after-cleanup.txt` 固定实际结果、字节身份与清理事实。本节由实施者核对现有结果，不称为重新进行三位独立代码评审，也未改动原已审实现。
