# A104：本地 metadata fallback 归原文件系统发现组件

- Authority: accepted bounded implementation record；完整 Goal 仍 active/partial。
- Design status: accepted；Implementation status: implemented for the existing fallback path。
- Owner: Harness Resources 原文件系统发现组件；Coding 保投影与政策。
- Method: 本地 archmethod master `0f9bd3ff51afabeaaf76cc38dff1ceb279b7d37e`。

## 复用与职责

Catalog 失败时，原 Coding 私有 fallback 以固定深度列出已声明根中的 Skill、Prompt、
Theme 名称。普通 NativeFilesystemResourceSource 和原 descriptor helpers 会读 author
bytes、递归或排序，不能等价替换这条只读 metadata 路径。采用原
_loader_discovery_filesystem，复用其 Resources 文件系统发现职责，再最小扩充完整
FD/根身份/枚举/关闭程序。不是第二套 Catalog、Source identity 或 selection proof。

Coding 只保原16键纯字典投影、名称正则、500预算、诊断前缀和原异常类身份，调用
原 Harness 操作；没有 Code IO 回借、状态机、manager 或新持久格式。纯 row_factory
在原 rows.append 的实参位置执行：skill 子 FD 已关闭，directory/root 仍开启；不将
投影移到资源释放之后。私有兼容函数及调用者的 query/filter/fail-closed 协调保持。

## 边界修正与资源合同

R1 候选直接注解 ResourceCatalogInputReceipt，会使普通 loader 依赖 Catalog 迁移
私有类型，违反现有精确消费者清单；未安装。R2 改为仅两个只读 Path 属性的结构
Protocol。现有组件没有这个窄端口；它只描述声明根，不构造 adapter、不读取属性、
不做 runtime admission，避免提前展开 roots 而改变 NOFOLLOW 缺失时的早返回。
Core 没有 Catalog import/TYPE_CHECKING 依赖或绕过扫描的 alias；原架构 gate 未改。

保留 root16上限、all/per-directory500预算、原枚举次序与不跟随链接；不读内容、
不增加根权限准入或复用更强的 RootedFileIO 门槛。before→open→fstat→目录/child
检查及 opened=before 的失败后验保持。skill child close 在 entry OSError catch 内，
其错误仍可记 entry_skipped；root finally 先 close，再 after-lstat/resolve，close
抛错时仍跳过后验；未统一为 ExitStack。ELOOP/ENOTDIR/ENOENT 的原分支及异常
cause/context 保持。16键含 not_checked/无指纹等原保守语义，不把 fallback 说成选择证据。

## 全成本

| 范围 | 原行数 | 当前行数 | 变化 |
| --- | ---: | ---: | ---: |
| Coding plugin_local_discovery | 669 | 559 | −110 |
| 原 Resources filesystem discovery | 503 | 681 | +178 |
| 全系统 | 647978 | 648046 | +68 |

全 Coding430源113393行；相对 Goal−24362，全系统相对 Goal+13252；距15K尚98393行。
其余1966生产源及13资源 SHA 相同。全部参数、Protocol/TypeVar、imports、纯投影与
格式均计入。收益是完整物理职责退出，不是重复算法消除或系统净精简。新增显式
probe202行、冻结JSONL243行（777286 bytes）另计，不进默认 PR route；原测试只改
两个 monkeypatch 目标为已导入的同一 os singleton，原5节点/65断言及实际效果保持。

## 验证与有界接受

旧真实消费者5过；旧源进程内路径/SHA守卫捕获243记录，11基础与232故障（good
trace中58个操作点各4 errno），旧回放243过。初探针将 open_handles 的 tuple 统一为
JSON list 后再回放；原 raw oracle 不改，R1观察器保留。包括不支持NOFOLLOW时零
receipt访问、根替换/非目录、无内容读取、原次序、预算截断及关闭错误/后验掩盖。

候选243过；持久化探针逐record等原oracle。恢复旧源后同进程来源/SHA守卫再过243，
恢复候选后同守卫联合原5节点共248过。另原 Loader 两模块39过，原 Catalog 模块
2过/1失败：失败涉及未改的 product_composition_assembly 与 _loader_inputs 两原
消费者遗漏，旧源同节点同失败。该旧清单欠账未关闭，不据此宣称架构全绿，也未
为通过而改 gate。两源及探针/原测试 Ruff、两源限定 mypy follow-imports=silent、
当前依赖图检查通过；文档9项通过，不外推全库类型或全产品回归。

控制模型不是原生 Windows、真实 FD/锁/ACL 证明，未覆盖 scandir.next、pattern
逐调用故障、所有预算相邻值、双重cleanup故障全集、row_factory分配故障或 Task
取消。源码完整操作体回绑纯政策/原字典后 AST 同，原 Code 其它操作及原 Core
13个顶层定义 AST 不变；真实根替换与 malformed sibling 由原消费者验证。
交付前仅删接收文件尾部1空行，完整 AST 同；最终来源守卫243回放再过。
三独立职责/运行/数据兼容评审及 Root 综合技术接受有界针对本片；源码全帧、旧
oracle、原失败与修正、运行和 review 证据保留在树外 A104。

## 剩余范围

本片不关闭 C01、P1–P4 或15K目标。优先核剩余完整业务路径对已有 owner 的直接
复用，而非再提单消费者 proof 基类或重复开发已共享的 payload/恢复程序。五项
Hosting、AI coverage、早期部分构造/Package绑定与本次复现的 Catalog 清单欠账均
保持；KD003 未实施，KD011/A33 待用户且未采用。
