# COD-RESP-A23 R2：依赖 Wheel 来源完整操作复用

- Authority: accepted implementation design。
- Design status: accepted（R2）；三独立设计视角无剩余实质阻断，构造TypeError前缀边界已澄清，实施owner `/root`在原职责内接受。
- Implementation status: implemented（有界）；四实际源已接通，157项实际回归通过，三视角实码无剩余具体阻断，终态及全成本另记。完整Goal仍partial。
- Owner: 原 Package Product 来源目录；Journal 管原持久事实与锁；Resources 管原来源 IO。
- 需求：[完整 Coding Goal](../coding-responsibility-convergence-goal.md) P1/P4，承接[A22](local-wheel-source-catalog-convergence.md)，不接受 P2/KD-008 新环境方向。
- 方法：本地干净 archmethod master `0f9bd3ff51afabeaaf76cc38dff1ceb279b7d37e`，未核上游。

## 1. 当前事实与场景

A22 已共享三类 POSIX 来源目录查询、链检查，以及 data/Worker 的捕获提交；dependency 仍在 Coding 承担稳定读取、锁内重复判断、原子发布、追加记录、目录句柄清理与策略扩展。其普通名称/Version 比较和 Wheel 内存元数据校验是必要差异，不表示必须另留一整份来源提交程序。

本片覆盖同一现有操作的完整路径：已通过各原入口检查的来源 → 稳定读取 → 原数据核验 → 锁内重验 epoch/查记录 → 重复或新绑定 → 发布与验证 → 追加原 Journal → 当前性核对 → 重开/只读查询 → 扩展原 Product policy。没有新的安装、执行、目录 authority 或后台任务。

已有 `PackageProductLocalWheelPolicy` 管解析政策、`Inventory` 管已安装/desired 状态、controlled Source IO 管受控字节，均不能代替完整来源登记。直接扩充 A22 的私有目录协作程序；不新建通用 Repository/Source manager、日志、原语或公共 facade。

## 2. 原职责与内部结构

环境参与者与 A22 相同：Coding 原公开目录 → Package Product 私有来源操作 → 原 Journal / Resources / epoch owner。部署仍是同一实例、同一原路径的同步调用，不新增组件、连接、进程或持久记录。细化的是该原模块内部实现，不是提交用户的新系统环境方向。

| 现有责任 | R2 处理 |
| --- | --- |
| 来源稳定读取、锁内重复/限额/发布/追加/current | 原 `_PluginWheelSourceCatalog` 的共同程序提为 `_WheelSourceCatalog`；data/Worker 与 dependency 同用一份主体 |
| Plugin id/admission 与 bindings 扩展 | 原 Plugin 特化保留，125 上限不扩给 dependency |
| dependency 子目录/128 上限/异常范围/dependencies 扩展 | 同模块私有 dependency 特化；根目录打开与原私有 metadata 检查复用父类，子目录创建/打开/关闭保原顺序 |
| 记录、codec、hash、Version、metadata、预算与目录名 | 原 Coding 值和纯 hook；无 Code 物理 IO callback、大 Product/context 或 locator |
| 三个重复的构造转发 | 删除无额外逻辑的原覆写，继承已有基类**相同实参签名及解析 hints**的构造方法；不用动态签名伪装 |
| dependency policy 纯转发 | 继承返回同一 `PackageProductLocalWheelPolicy` 的原特化方法；没有 TypeVar 返回污染 |
| records/read_records 与 capture/verify | 原具体返回类型薄入口保持，不能只为减行令公开返回注解变成未绑定 TypeVar |
| Windows Worker 与 legacy bindings | 本片不动；不能把 POSIX FD 或 Source 名称规则套入这些不同合同 |

Code 的三真实类/FQN、实例字段、record/codec/错误类及 Windows 整个类保持。构造方法及 dependency extend_policy 的定义位置、qualname、继承链变化；不承诺私有 __dict__/完整反射或故障注入全局位置等价。原 A22 显式构造覆写在此由 R2 明确改为相同公开签名的继承，须经独立兼容评审后接受。 构造缺参/多参等 Python 参数绑定 TypeError 会显示继承函数的 qualname（`_PosixSourceCatalog.__init__`），不保证旧 Coding 构造名前缀；这与程序内部原错误/cause保持分开，未发现既有稳定该解释器前缀的合同。

## 3. 必须保持的顺序与失败合同

1. 各原 capture wrapper 的 read-only → epoch → 原来源/admission 检查保留，不增加 Path 类型拒绝、输入权限/UID 限制或 fallback。
2. dependency 在原 try 内先检查 Wheel 名称，再 open/fdopen、前 fstat/大小、一次有界 read、后 fstat、关闭、lstat。其 catch 仍为 OSError/ValueError，Code RuntimeError 预算拒绝不被误包装；data/Worker 仍仅 catch OSError。无效名称不能变成先读取文件后拒绝。
3. 非空、读长和三份 identity 核对后才计算摘要；dependency 内存 Wheel metadata 核验仍先于获取目录记录锁。纯 hook 不得执行 Code 文件 IO，原 `inspect_package_wheel_bytes` 直接复用。
4. 锁内仍依次为 epoch → 原 load → 文件名重复与原 digest/source/admission 比较 → 验证已有受控字节并返回；新记录才走原限额、原具体 create、dependency 规范化 Version 冲突检查、publish/verify、原 append、epoch current。
5. Plugin 125 与 dependency 128 保各原固定特化，既有记录的提前返回仍发生在限额检查前。dependency Version 等价冲突保持原 `any` 短路和调用点，不改为字符串判重或提前规范化所有记录。
6. dependency 先打开/检查原 source 根，按 create 决定是否 mkdir，打开 dependencies 后在 finally 关闭根，再检查子目录，错误时关子 FD。读取先打开/检查并关闭该目录，再读原受控路径并做 metadata 校验。只共享原等价的根打开/检查，不能新增 whole-chain pin 或放宽权限。
7. 发布仍由原 controlled Source IO 完成；失败保留原痕迹与异常/cause，先前发布成功不代表 Journal 已提交。不新增跨 Store 回滚、盲重试或清理共享字节。
8. dependency policy 仍在原 authority 检查后读记录、逐个验证、按原(project_name,version)排序合并；data/Worker 仍核 Plugin id 碰撞、原 bindings 排序。查询、修复策略、durability、各原 TypeError catch 差异保持 A22。

程序增加固定纯值 hook 调用，不声称零成本或性能改善；没有额外 payload 复制、来源读取、解码、锁或异步工作。无新公开策略开关或任意步骤引擎，固定 specializations 只表达三个既有调用者的实际差异。

## 4. 选项、成本与回退

| 选项 | 判断 |
| --- | --- |
| dependency 整体另搬一份 capture | 保持重复，不能复用 A22，未选 |
| 所有来源强套同一限额/验证/目录 | 改变当前能力与失败先序，未选 |
| 原共享主体加固定特化，Code 保具体值/纯政策 | 选择；同时删除无逻辑转发，不增加运行 owner |
| 不改 | 合理回退；如实际成本或兼容不成立，不为减 Coding 强制增加总复杂度 |

R1 首次生成在 `_DIRECTORY` 文本替换时错误触及 O_DIRECTORY，候选类型检查抓到两项；已在树外修正，没有产品代码或测试弱化。修正后 R1 overlay110 passed/56.47s，四源 silent-import mypy 通过，但 Code−114/Core+119、系统+5；该候选独立保留，不采用为最终交付。R2 进一步删除原无逻辑构造/策略转发，依然保留具体类型必要的 records/read_records。

| 完整 R2 成本 | A22实际 | R2候选 | 差额 |
| --- | ---: | ---: | ---: |
| Code data | 241 | 229 | −12 |
| Code dependency | 445 | 308 | −137 |
| Code Worker（含完整Windows） | 652 | 640 | −12 |
| 同一 Package Product 私有模块 | 336 | 455 | +119 |
| **合计** | **1,674** | **1,632** | **Code−161，系统−42** |

上表包含全部 hooks/Protocol、导入及实际格式，不称 Core+119 全是真正新增复杂度，也不把迁出161当系统净删。最终以实际完整生产 manifest 为准；当前仍 Coding127139/系统636965，候选收益0。15K/系统净减和完整 P1–P4 不变。

回退为四源整体恢复 A22，持久记录/路径/格式未变，无数据迁移、旧 fallback 或 workspace 重建要求。不修改原测试的断言、timeout、selector、gate/矩阵/平台。

## 5. 验证与接受计划

原实际基线18375：81 passed/27.60s，含原75个来源发布/读取故障例和 dependency 整文件六节点。后者覆盖真实 Product bootstrap/admit/reopen/解析与只读预览、Version 等价冲突、symlink 及三种 metadata 反例，非模型/live 试验。

继续复用 A22 的24组旧观察及完整性节点、原公开面/record-codec/Windows AST和Core冷导入检查。旧 root/recordId 规范化局限沿用，不重录期望。R2 构造签名及解析 hints 由原公开面比对；候选与实际分开跑，不累加重复节点。实际受影响 Product/目录路径和原架构检查定向验证；mypy 仅四显式源 silent imports，不称全图或 Windows native/性能。

职责/复用、运行/失败、数据/兼容三独立设计视角关闭实质发现后再接入；实码另三视角核查及实际测试、全成本闭合。实施 owner 可在原组件内部职责下接受本接缝，不据此接受 P2/KD-008 新方向。源码/原观察/报告/终态在产品树外 a23-dependency-source-operation，完整 Goal 保持 active。


## 6. R2设计接受与实际接入

三独立设计报告绑定原冻结对象b3e46ee5c1116531d427d975a9183f83bb8252982e185743fa5e379447034e87；数据视角提出的构造TypeError前缀边界已补入窄澄清对象fa62288e3b466c3b55db7f26900a46e2fbb21c368a9b90127ac4e747a1849e52并核实，无未关闭实质阻断。实施owner `/root`接受本内部接缝，不把它当新环境方向接受。

86660 R2 overlay110 passed/71.16s，43244四源silent-import类型检查通过；R1原结果/候选单列，不累加。额外来源异常探针最初未匹配dir_fd组件路径，31328的10项失败是探针注入错误，原失败和脚本保留；仅修basename注入后，旧实际12470独占捕获10 passed/3.87s，候选45130对照10 passed/3.68s。未修改产品使探针通过、未重录旧期望；它只证明九组来源open异常/cause/提前停止，非授权或并发证明。

四实际源按冻结指纹接入，全部等R2；其余1,881生产源与A22逐字相同，仍1,885文件。当前Coding126,978/系统636,923，本片Code−161/Core+119/系统−42。实际验证与代码三视角待回收后才能接受交付，原源码/候选/报告在树外；完整Goal继续active。P2基线43099同时仅核其原八源未变的生命周期合同，A23不冒称该批验证了P2新实现。


## 7. 实际验收终态

97444实际无overlay回归exit0：157 passed/372.41s，XML为157 cases/0failure/error/skip。它包含与A22同范围的实际来源IO、dependency整文件、data Product/两个cross-runtime、三个原架构文件及A22旧观察/公开面，再加A23十个固定异常前缀节点；不是全仓或原180项完整重跑，不把原/候选/实际重复结果累加。原源码、初次探针失败与后续正确捕获均保留。

32701四实际源silent-import mypy、34979原生成新鲜度及实际Ruff通过；不称全图类型或native/性能验证。三独立实码视角核实际四源/原记录及Windows、构造继承边界、既有Journal/IO复用和完整成本，无剩余具体静态阻断；原pending由真实终态及运行/数据补件关闭，不覆盖原报告为首轮全绿。实施owner `/root`有界接受本片。

最终Code126,978/系统636,923，累计Code−10,777，系统仍较634,794起点+2,129，距离15K还需111,978行。完整Goal、职责归一与系统净减目标保持active。P2另批43099原八源/三测试70 passed/523.25s为其改动前基线，不能混入本片或称P2已实现；用户对P2职责方向的接受另记于KD-007。
