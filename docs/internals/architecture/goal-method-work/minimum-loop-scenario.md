# Goal 最小闭环：首个场景与验收输入

- Authority: descriptive — 候选场景的实测输入，未接受为 Target。
- Design status: draft；Implementation status: not-applicable for this input record。
- Owner：Coding Product composition。
- 需求：[G-GOAL-MIN-01](../../plans/2026-10-25-goal-minimum-business-loop.md)。
- 设计：[架构 R2](minimum-loop-architecture.md)，其固定 hash 与用户 pending 状态不变。
- 评审：[三视角设计记录](minimum-loop-review.md)。
- 代码基线：`372cde4ade0fe026076c8fa5e8b4486774b09cc3`。

## 1. 本次新增的证据

本轮在产品树外固定了缺陷项目、测试数据及显式 Method，实际测量原始失败，并
通过现有 MethodDomainRuntime 生成两步 prepared turns。这是设计接受前的数据
准备，不是 Goal 运行时实现，也未调用模型或产生 Work/Goal 运行记录。

| 输入 | 实测结果 |
| --- | --- |
| `calculator.py` | `subtract` 错用加法；`clamp` 越界时返回另一端点，缺陷源码保留不变 |
| 固定测试 | 23 项：减法 9 项、clamp 14 项；原版 13 项失败、0 error、0 skip |
| 数值与用例 | 每项预期值用独立算术关系核对；函数签名、确切 int、输入/输出和用例数符合 R2 的界限 |
| 源码尺寸 | AST 40 节点、深度 6，低于 R2 的 128 节点/深度 16；该测量不等于完整 AST 准入实现 |
| 显式 Method | 原 loader 发现 `method:task:goal-calculator-repair`，原 runtime 准备 inspect、repair 两个 fixed 步骤 |
| 失败证据传入 | 两份 prepared prompt 均含本轮实际失败 id、观察值及源/测试摘要；未预设修复补丁 |
| 项目约束 | 探测前后四份项目文件的路径与字节摘要完全一致；R-FILES 的生产约束检查仍未实现 |

测量使用 stdlib unittest 对作者创建的固定缺陷数据运行，并调用现有 Method 的
纯准备接口；没有执行异步 Session/Host、真实 SDK 命令或模型。探测脚本信任这份
输入，不是处理任意不可信代码的未来 driver，不能把它挪作生产验收器。

## 2. 固定输入与指纹

材料目录为：
`/home/dev/lsspace/architecture-analysis/goal-minimum-business-loop-20261025/acceptance-fixture-v1/`。
`project/` 是保持缺陷状态的小项目；`probe_inputs.py` 为本次测量脚本，
`baseline-probe.json`、`method-preparation-probe.json` 和 `manifest.json` 保留实际结果。
当前材料未加入产品代码或 examples；实施时须按已接受的交付路径纳入可复现材料，
不能只靠这台机器的外部目录作为最终交付。

| 项目文件 | SHA256 |
| --- | --- |
| `calculator.py` | `4d47897f8b404b3b22dd4616658ee9e30aea0719b4617ec48487cd6fad8bccfb` |
| `TESTS.json` | `1fd53db853feb6f499777566d4226d102010ffd902d0424569cd4d43a1de12fe` |
| `README.md` | `1d0b6a1eda9cf23d1c0dc14a3b624b2ad15707c2be798ffb3a1bc3ab9c59677d` |
| `methods/task/goal-calculator-repair/SKILL.md` | `2471279d805224df10631955f03c227188cc6b2bc32550ad36cee3e7387da453` |

输入 manifest 的 SHA256 为
`934f85f9f19f0e5bd6926a9f8f4d3508d5882ad2237236bee5b91f325b3fa67a`。
其中明确记录模型调用 0、Work 创建 0、Goal 完成未验证及所有尚缺证据。修改这些
候选输入须生成新修订，不在未来运行后悄悄改变原始用例来追认通过。

## 3. 具体要求及验收责任

| requirement id | 原始要求 | 未来生产验收证据 |
| --- | --- | --- |
| R-SUB | 正确返回约定整数输入的差值，覆盖正负、零和输入边界 | 固定的 9 个 test id 全部实际执行，通过且返回确切 int；结果绑定实际受测源及要求版本 |
| R-CLAMP | 对合法闭区间返回最近端点或原值，包含负区间及单点区间 | 固定的 14 个 test id 全部实际执行，无 skip/替换/减少，符合原结果合同 |
| R-FILES | 只允许改变 calculator.py 内容，项目其他文件及类型/路径保持不变 | Product 对完整受控项目作修复后、验证前及完成前清单核对；不能用 23 项测试通过代替 |

Method 的两步实际可由现有准备机制表达：inspect 读取当前要求及失败，repair
用原文件工具做最小修改。指引文字不等于强制约束；R-FILES 和受测语法等仍需
由 R2 所选的 Product 准入及领域验收实现和验证。

## 4. 未来真实 SDK 的完整轨迹

以下是待实现/待执行的验收，不是本次探测产生的历史：

1. 创建持久 Goal，固定上述要求/测试/Method 以及实际模型、权限与有限批次配置。
2. 第一次 advance 经原 SDK 验证并形成真实失败 Work，取得原报告和 Blob 引用。
   本轮测量的 13 项失败不能冒充这次 Work 的执行证据。
3. 第二次 advance 将该真实失败、当前要求版本及源码依据传给显式 Method，
   经原 Coding/Agent/工具实际修复，保留两个步骤和原运行事实。
4. 后续 advance 重新核对完整项目约束、固定受测输入，再验证并读取证据。
   满足三项要求后才形成 Goal 完成决定；仍失败则引用新失败组织后续批次，
   达到显式批次上限或无法继续时暂停并给出原因。
5. 关闭后重开，只读取目标、关联及完成依据，不发起模型请求或重放旧操作。

模型未选定或权限尚未满足时，不能把固定回复、人工补丁或这份 Method 准备结果
替代真实 SDK 模型修复。配置应在实施前记录，但本轮没有为等待架构接受而探测
凭据、调用 provider 或改变用户环境。

## 5. 需要保留的反例

| 情形 | 未来必须观察到的结果 |
| --- | --- |
| 函数修好，同时改/删测试、Method、其他只读文件或增加链接 | 约束违规，Goal 不能完成；不自动更新原清单 |
| 打印 PASS、exit 0，或伪造缺少用例的领域结果 | 拒绝或保持未完成，不由 stdout 自报完成 |
| 源码试图 import/call/改 runner 或超出有限语法域 | 准入拒绝/needs_user，不降级为任意 Python 执行 |
| 正确旧报告用于新要求、不同 Goal 或后续被改动源码 | 依据过期或不匹配，不能完成当前要求 |
| 准备中暂停，或运行中修订/撤回要求 | 原 epoch/版本不再准入或完成；旧事实仍可查询 |
| 同 command id 重复或带不同内容重试 | 只读原回执或明确冲突，不重复产生 Work |
| intent 已保存但原 Work 为空/orphaned/效果未知 | 保持会话级 unresolved；resume/replace/改 Goal id 不绕过 |
| 必需 Blob 缺失、损坏、跨 authority，或 schema/stdio 不完整 | 阻止完成，保留原错误/诊断，不另选相同摘要材料绕过 |
| 完成后关闭/冷重开 | 原身份和证据可核验，模型调用与 Work 重执行均为 0 |

## 6. 状态与下一步

上一 goal turn 为 progress：已完成 R2 候选架构及独立评审；本 turn 也为 progress：
新增固定输入、原始失败实测及原 Method 准备证据，改变了真实场景的准备状态。
这些不代表 GM-01…08 的功能实现已完成，更不代表用户已接受 R2。

当前仍待用户对 R2 重要工作件的评审。按目标中“设计接受后实施”的要求，接受前
不写 Goal 运行时代码；已发出的评审问题继续有效，不把自动 continuation 或时间
经过当作确认。接受后继续前置集成、完整 Goal 实现及真实场景验收。
