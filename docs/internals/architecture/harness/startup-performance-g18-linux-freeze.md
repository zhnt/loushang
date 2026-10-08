# G18 Linux Installed-Entry Baseline Freeze

## Status And Scope

- ID: `G18-LINUX-INERT-AA-01`
- Date: 2026-09-09 UTC
- Source: `9bc69361494293595ae424be225c61e3226a9996`
- Branch: `harness/g18-startup-performance`
- Status: **A 组入口参考数据与比较规则已冻结；9/10 场景满足稳定性标准**
- Authority: scoped measurement record, not a Product SLO or full G18.0 acceptance
- Plan: [G18 startup performance](startup-performance-plan.md)
- Cases and remaining native work: [scenario inventory](startup-performance-g18-scenarios.md)

本次按用户暂停并行生命周期工作后的环境重新测量。产品源码、配置和运行时预算没有改动，
因此不能把与[早期高噪声 pilot](startup-performance-g18-linux-baseline.md)的差异称为优化收益。
本文件原始 A 组只冻结 warm-bytecode 的 import/help/version。后续 fixed-slot warm
native A/A 已采齐并在下文单列：30/41 项稳定、11 项 inconclusive；不升级为完整
native 性能通过。G18.0 整体仍是 partial，不能以 help 结果代替 native 验收。

## Measured Reference

在同一 Linux 环境运行两个独立 venv，安装相同 wheel 和锁定依赖；两批各十对，
每个场景共 40 个正式样本，另有每个 case/install/block 一次 warmup。
共 **400 正式样本 + 40 warmups**，全部输出/退出校验通过，没有失败、丢弃 outlier 或重试。
安装文件、来源及 wheel 字节在测量前后复核一致。

单位为秒；p95 为 40 样本 nearest-rank 描述统计，不是 p95 SLO。CPU 为每次 child
user+system 的中位数，不能据此推导 RSS。Wall 包含进程启动、输出接收和退出。

| Case | Wall median | p95（仅描述） | Child CPU median | 稳定性 |
| --- | ---: | ---: | ---: | --- |
| import-harness | 0.055 | 0.072 | 0.047 | 稳定性检查通过 |
| import-coding | 3.658 | 4.051 | 3.355 | 稳定性检查通过 |
| import-cli | 5.211 | 5.927 | 4.680 | 稳定性检查通过 |
| cli-help | 8.415 | 9.251 | 7.757 | 稳定性检查通过 |
| cli-version | 5.396 | 5.996 | 4.811 | 稳定性检查通过 |
| tui-help | 8.258 | 9.330 | 7.572 | 稳定性检查通过 |
| hosted-help | 4.064 | 4.445 | 3.702 | 稳定性检查通过 |
| hosted-tui-help | 3.979 | 4.309 | 3.654 | 稳定性检查通过 |
| mux-help | 3.932 | 4.306 | 3.611 | 稳定性检查通过 |
| plugin-help | 0.712 | 0.862 | 0.654 | inconclusive |

十个场景每个都有四组 median（两批 × 两安装）。九个满足：
median span ≤ max(最小组 median × 10%, 20 ms)，且每组
MAD ≤ max(组 median × 10%, 10 ms)。

`plugin-help` 四组 median 约为 0.6941、0.7644、0.7109、0.6947；
span 约 70.31 ms，允许值约 69.41 ms，略超约 0.90 ms。
**仍标记 inconclusive，不把阈值改成能通过的数字**。其测量数据照常保留，
后续在启用该 case 的 blocking 比较前需要独立复核，不能把此次边界结果判为通过。

较重入口的 CPU 时间占 wall 的大部分，说明程序执行成本值得优先调查；
它不能单独证明某个模块的可移除成本，仍需独立 import/profile 归因。
仍有调度/系统负载变化，不声称本机完全无噪声。

## Frozen Comparison Policy

1. 本文件和 JSON 是**参考冻结**，不是直接用这些绝对秒数卡所有机器的 CI。
   后续必须在同机、同版本解释器、匹配依赖/缓存/fixture 条件下重新配对 baseline/candidate。
2. 优先目标：`cli-help` 与 `hosted-tui-help` median 至少改善 **30%**；
   当前数值对应约 **5.890 s** / **2.786 s**，
   仅用于理解目标量级，不是跨环境绝对 deadline。
3. 其他 A 组 case 的 median 退步不得超过
   `max(配对 baseline median × 10%, 20 ms)`。不满足稳定性条件时判 inconclusive。
4. Timing 仍 **record-only**。当前采集器已接入比较器及已知退步负控；
   `complete-record-only` / exit 0 只表示采集完成，必须另看 `comparison.verdict`。
   不能声称有 blocking 性能门禁；现有功能和 G10/G16/G17 门禁不弱化。
5. 真正 ready/first-use/settlement 与 absent-bytecode 的基线另行建立；
   macOS/Windows 在其他机器上验同一候选，不套用本机秒数。

后续比较器代码评审明确数值解释：使用输入的 round-trip 十进制表示进行精确有理数
中位数/MAD/阈值运算，无 epsilon、无舍入放宽；避免二进制浮点使恰好 30%/10%/20 ms
的边界被误拒。本节只冻结 A 组 elapsed；native 使用另行评审的
[41 指标政策](startup-performance-g18-scenarios.md#native-comparison-policy--pre-candidate-review)。
规则已实现不代表 native 重复基线已通过，也不升级本次历史报告的证据范围。

## Supplement: Fixed-Slot Native Warm A/A Reference

新存储与 G14 observer 条件下的正式轮 `native-fixed-warm-aa-disk-02` 已终态完成：
exec 49826 exit 0，`status=complete-record-only`。七场景、2 blocks × 10 pairs，
共 **280 正式样本＋28 warmups，全部 complete/valid，失败 0**。每个场景 40 个
正式样本与 4 个 warmups；两侧 source/wheel 相同，不是优化候选比较。

最终 verdict 为 **inconclusive**：41 个规定指标中 30 项满足既定稳定性规则，
下列 11 项不满足。样本、计时锚点及阈值均保留，不删 outlier、不重跑到绿。

| 场景 | 不确定指标（均为 `_seconds`） |
| --- | --- |
| embedded | settlement |
| foreground | settlement |
| g14-stdio | settlement |
| recovery-global | ready_frame、history_visible |
| product-first-use | dev_attach_frame、first_tool、interrupt、review_detach_settlement、dev_detach_settlement、reattach_detach_settlement |

例如 foreground settlement 的各侧自身分组均稳定，但四组 median 的跨度约
172.61 ms，大于允许的 146.72 ms；embedded settlement 的 B 侧第二批 MAD 约
126.03 ms，大于该组允许的 102.18 ms。不能仅看 pooled median 接近就改判通过，
也不能把清理耗时不稳定直接解释为未完成物理清理。原因归属尚未确认。

完整 308 个样本的 milestones、负载、41 项比较结果及来源摘要保存在
[native warm 参考 JSON](startup-performance-g18-linux-native-warm-aa-baseline.json)。
该文件是原报告的参考投影，保留数值精度，不替代 raw owner/cache/recovery/install
回执。原始报告仍位于 `.artifacts/g18-baseline/native-fixed-warm-aa-disk-02/report.json`，
SHA256 为 `51937c7ac046dd306e820d645d934f89db9d36946927e46191a296f8e77c869d`。

初末安装和固定第三 observer 校验通过；所有 sample pre/post installation 相同，
1,199 个 helper 输入前后一致。最终 slot busy=false、failed=false。G14 全部 44 次
使用同一 `cpython311-safe-child-watcher-v1`、实际 SafeChildWatcher 和已核验的
CPython 3.11.15。scratch parent 为 `/var/tmp`，device 64770；不与旧 `/tmp` 或旧
ThreadedChildWatcher 结果拼接。Product 源码仍为原基线，没有性能优化实现。

本轮只封存参考证据，不宣称 native 全稳定或 G18.0B/G18.1 已完成。absent-bytecode
参考及候选 A/B 仍待完成；这 11 项不确定结果不会豁免后续真实无退步验收。

后续 absent 正式轮在第 87 个 foreground 样本的原 35 秒 ready 期限失败，终端
尚无输出；86 个样本 complete/valid，但整轮 failed、comparison=not-evaluated，
最终安装/observer/helper 核验未执行。失败时有显著 CPU/I/O/memory pressure，
但不能据此证明环境是全部原因。失败不补样、不重跑到绿，详情及诊断快照见
[absent 失败记录](startup-performance-g18-linux-absent-aa-failure.json)与评审记录。

本轮终态及三视角复核后，仅将 616 个 cache-evidence 普通文件无损归档到同一 output
目录的 `cache-evidence.tar.gz`（约 143 MiB），GNU tar 内容/元数据 compare exit 0
后移除约 784 MiB 的展开副本。归档 SHA256 为
`0d325992c104a97b93fed7b3f5b3c4c4466ad4b93ab42e9093fb787dcaaaee8e`。
raw report 字节未改变，cache 路径仍记录原位置；按 raw 路径复核前需先恢复归档。
观察器回执、seed、安装及其他任务文件未删除。恢复时先确认目标不存在并核对归档 SHA：

```bash
test ! -e .artifacts/g18-baseline/native-fixed-warm-aa-disk-02/cache-evidence && \
  tar --extract --gzip --keep-old-files \
    --file=.artifacts/g18-baseline/native-fixed-warm-aa-disk-02/cache-evidence.tar.gz \
    --directory=.artifacts/g18-baseline/native-fixed-warm-aa-disk-02
```

## Reproduction And Provenance

- Window: `2026-09-09T01:48:47.217869+00:00` → `2026-09-09T02:21:41.589122+00:00`，约 32 分 54 秒
- Platform: `Linux-7.0.0-29-generic-x86_64-with-glibc2.43`
- Reported logical CPUs: 1; CPU affinity: `[0]`
- Interpreter: `3.11.15 (main, Mar 10 2026, 18:16:52) [Clang 21.1.4 ]`
- Load (1/5/15 min): 0.85/1.19/1.31 → 1.98/1.78/1.65
- Wheel SHA256: `c75ed7beaf3a0d10c3583bd181507d5cb6340f79d71971cea4a0cd986a44dd09`
- Lock SHA256: `556547755c39ef7063c8cb1c3624b322d13216fc8abe621daa6fe095d5b1146d`
- Collector SHA256: `8e384989408eff373a18b9b76c6eaecae0353480899a6da6cd7cbafab6d16554`
- Raw report SHA256: `2330dcf33e192457c8a98de183acb73baa117a6962c651fe7a81a05e98dfa485`

完整依赖、entry target、四组 median、全部 400 个计时样本及 CPU 时间见
[durable baseline JSON](startup-performance-g18-linux-aa-baseline.json)。
该 JSON 中样本保留六位小数；完整精度、stdout/stderr、每样本 cwd/load、warmups 和
安装元数据保留在 `.artifacts/g18-baseline/aa-01/report.json`。不要覆盖 aa-01；
复测使用新输出目录，并保留这份记录。

下列 build/install 是初次准备记录，只可在新的空任务前缀执行；不要覆盖本次已验证的
wheel 或安装。复用现有基线时仅执行最后一段 measurement，并换新的 output 目录。

```bash
uv --cache-dir .artifacts/g18-design/uv-cache build --wheel \
  --out-dir .artifacts/g18-baseline/wheels
uv --cache-dir .artifacts/g18-design/uv-cache export --locked --extra dev \
  --no-emit-project --format requirements-txt \
  --output-file .artifacts/g18-baseline/requirements.txt
uv --cache-dir .artifacts/g18-design/uv-cache venv \
  --python .artifacts/g18-design/venv/bin/python .artifacts/g18-baseline/install-a
uv --cache-dir .artifacts/g18-design/uv-cache venv \
  --python .artifacts/g18-design/venv/bin/python .artifacts/g18-baseline/install-b
uv --cache-dir .artifacts/g18-design/uv-cache pip install \
  --python .artifacts/g18-baseline/install-a/bin/python \
  --requirements .artifacts/g18-baseline/requirements.txt \
  .artifacts/g18-baseline/wheels/loushang-0.1.0-py3-none-any.whl
uv --cache-dir .artifacts/g18-design/uv-cache pip install \
  --python .artifacts/g18-baseline/install-b/bin/python \
  --requirements .artifacts/g18-baseline/requirements.txt \
  .artifacts/g18-baseline/wheels/loushang-0.1.0-py3-none-any.whl

uv --cache-dir .artifacts/g18-design/uv-cache run --no-project \
  --python .artifacts/g18-design/venv/bin/python scripts/dev/measure_g18_startup.py \
  --install-a .artifacts/g18-baseline/install-a \
  --install-b .artifacts/g18-baseline/install-b \
  --wheel .artifacts/g18-baseline/wheels/loushang-0.1.0-py3-none-any.whl \
  --output .artifacts/g18-baseline/aa-NEW --blocks 2 --pairs-per-block 10
```

安装和 build 在测量前完成。最初离线安装因缓存缺少索引信息失败；随后只安装锁定版本依赖，
未改变 lock。计时期间无联网场景、无本任务的其他构建/pytest。
父环境与真实用户 home 不变；子进程使用 allowlist/private HOME/config/temp，
cwd 在 checkout 外，每次为新空状态；private bytecode prefix 保留。
任务拥有的 scratch 为 `/tmp/loushang-g18-baseline-zvzkig52`，保留用于诊断，不与其他 lane 共用。

## Validation And Remaining Gates

后续代码评审发现此历史 collector 没有绑定实际 console wrapper 的字节/解释器，且
正常 root exit 后的无条件 group cleanup 可能掩盖残留后代。**历史样本不据此追认成
更强的安装/清理证明**；原始数据及 hash 保留。当前工具已增加 wrapper 验证，并在既有
retained supervisor 内使用 Linux subreaper 观察，残留回收必使样本失败。候选比较需使用
修正工具新采配对样本；不能只拿本表宣称优化通过。进展见[代码评审](startup-performance-g18-review.md#implementation-review-in-progress)。

- 新 collector 定向回归：14 passed in 0.45 s；涵盖环境隔离、状态分离、输出、
  非零退出、超时/输出上限、统计和 partial-report 持久化；在私有环境、sandbox 外运行。
- 实际预检：十个场景、两安装均正常；正式 400 个样本及 40 warmups 全部校验通过。
- Product 源码未变；此前 11 项 SDK/extension-help/import-boundary 基线仍保留为单独证据。
- 本次历史采样时尚未做工具三视角代码评审；后续代码评审和修复正在进行，既有设计结论不替代代码验收。
- Change-aware plan 当前把新增 collector/test 归为 unclassified，选择全量门禁；
  本轮仅执行定向工具验证和文档检查，**全量提交/合并门禁未执行**。
  后续评审已明确接入现有 AppService 的精确文件、实际 test/lint 清单；共享 Make/CI
  变更仍保留全量选择规则，不以缩小 selector 替代验证。
- 未修改产品行为、未提交、未推送或合并；外部平台和 native B 组验收仍待完成。
