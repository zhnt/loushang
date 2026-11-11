# H-COD-KD-006：记录字段与值校验复用

- Authority: accepted internal refinement of H-PD-KD-001 R3 within delegated implementation scope。
- Design status: 三视角候选审查无具体阻断，实施 owner 接受本片内部复用；不替代用户对重要架构工作件的评审。
- Implementation status: 已在本地接入，相关验证与三视角实际复核完成；完整 Goal 仍未完成。
- Owner: 既有 Harness Resources／Packages 的 RecordSchema 与 records 值 helper；各记录保留自身字段选择、领域校验、身份和版本责任。
- 方法：本地干净 archmethod master `0f9bd3ff51afabeaaf76cc38dff1ceb279b7d37e`。
- 来源：[实施 Goal](../coding-private-data-implementation-goal.md)的 C08 及全 Coding 扩围；不降低原八千行或系统净减少条件。

## A54 字段声明的事实与选择

原 RecordSchema 已提供字段遍历、编解码与 keys，dataclass 声明和 Schema 字段表却在多处重复列出相同字段。本片只准备这些静态元数据：既有 helper 增加 for_dataclass，在模块加载时按 dataclass 原字段顺序构造原 RecordField 元组。普通值保持原默认处理；特殊标签、嵌套转换、编码和解码继续显式覆盖。derive_labels 仅用于原标签恰好等于字段名下划线转空格的声明，不推断数据类型或改变校验。

选择的 51 处声明来自 20 份生产源码，包括 Coding 私有数据的八个 Schema。其字段与 dataclass 顺序逐项相同；其余 14 处继续使用原显式构造。RecordSchema 构造函数、encode／decode／keys 及全部记录方法保持原 AST。新 helper 不持有 Product／Session／文件／状态，不增加组件、记录协议或事实权威；环境与运行交互不变。反射只在模块加载时准备元数据，正常编解码仍执行原路径。

完整候选撤去 230 条重复声明，Coding 净减 54 行，Harness 净减 177 行（已含 helper 新增 25 行），系统净减 231 行。原 before 独立格式化为 +4 行，故结构减少 235 行、格式增加 4 行。首个同时改写更多序列化方法的候选系统反增 5 行，已放弃，未接入产品；本片不改写序列化方法。

## 数据、失败与演进合同

使用此 helper 即声明该类型的全部 dataclass 字段都是 wire 字段。增加字段属于记录合同变化，仍须按原版本和存量兼容要求处理；存在辅助字段、不同顺序或字段子集的记录使用原显式 RecordSchema。ClassVar／InitVar 按标准 dataclass 规则不作为字段，init=False 字段仍包含；不会根据实际输入对象动态发现字段。禁止把此方案解释为自动升级或放宽旧记录形状。

字段类型不推断，转换和错误标签不猜测；特殊项仍使用原 RecordField。重复或未知覆盖名在元数据准备时拒绝，避免悄悄忽略声明错误；此检查不接触存量数据或改变原读取准入。当前所有转换函数、partial 参数和绑定类、字段顺序及标签均须与原表相同。旧 wire、ID／hash、容量、bool／int 语义、异常投影、领域校验及 partial-tail 策略不变。

## 验证与接受边界

提取前先以 20 份原源码 SHA／canonical 路径守卫冻结原 65 份编译结果。观察包含 text decoder、字段属性／wire key／label、转换函数代码与绑定类、partial 参数。首次探针未支持既有 partial，尚未生成预期；修探针后只在未改原树首次冻结。候选在启动前限定的 20 模块加载器中逐项比较全部 65 份结果，通过后才考虑实际接入。

逐 AST 检查保证记录方法和原 Schema 执行方法不变。实际接入后另以普通 worktree PYTHONPATH、无候选加载器复核元数据、原 C08 字节／日志／业务和相关 Package 记录测试及联合类型检查。一次性元数据与函数指纹证据留在产品树外，不增加永久代码指纹测试、CI gate 或新测试路线。相关测试不能扩称原生 Windows、任意断电、完整依赖图或完整 Goal 证明。

三位独立 reviewer 从职责／复用、运行／失败、数据／兼容核对候选及实际增量。仅在具体阻断关闭且实际结果齐备后，由实施 owner 在原授权内接受本片；不制造用户接受新的重要架构工作件的记录。本片回退将 helper 与其全部调用声明一起恢复，持久事实不回滚或清空。


## A55：原字段遍历执行路径的直接消费

两个外部 Wheel 绑定记录直接使用既有 for_dataclass／encode／decode，Core 不变。这是 A54 元数据切片之后的独立实现增量：四个原 to_dict／from_dict 现在改调原 helper；其余记录方法及文件操作不变。两记录的 dataclass、原 dict 和 constructor 参数顺序完全相同，当前十字段全部都是 wire 字段。identity decoder 不转换或校验值，exact dict／keys 与原 __post_init__／hash 决策继续由原类型负责，不引入类型推断或通用 validator。

原函数既允许按固定基类 shape 构造派生类型，新路径继续向原 cls 传同序关键字，不按派生输入动态发现字段。新增、移除或重排字段仍须显式 wire／版本与存量兼容处理，不能将加载期反射解释为自动协议升级。原 Core 每记录循环与 identity 调用不被宣称为零性能成本；未建立新运行 owner 或公开 facade。完整成本、旧行为对照、实际业务与三视角接受见[推进记录](../coding-convergence-progress.md#两种外部-wheel-记录直接复用既有编解码a55)。


## A56 R3：原值校验 helper 的单份实现

共享 owner 进一步限定为原 Package records：只收敛完整 AST 与标准库依赖相同的叶子值函数，记录仍显式选择原 helper 家族。当前 54 定义分为 11 组，五份已有 records 函数直接复用，六份原合同没有等价现成函数，故最小迁入 records；49 旧名导入别名继续供原调用者使用，净退出 43 份重复体。别名不再包函数或产生独立状态，RecordSchema 与记录类／方法没有新增或改写。

各组严格保留是否 Mapping／dict、复制或返回原引用、非空／仅类型、bool／整数子类与检查顺序以及 TypeError／ValueError 文案；不同合同不靠新模式枚举合并。独立核对实际函数定义、标准库全局绑定及无业务闭包后才准入，不能只凭调用语法和同名判断。原 R1 正因漏核此项被行为回放拒绝，未进入产品；R2 泛型组合入口未采用，最终没有 decode_object 或新回调 API。

原导入名、有效签名及旧函数引用解析保持；函数真实 module／qualname、traceback、私有错误签名诊断可随归属改变，不冒称所有 Python 内省相同。没有产品依赖原模块的标准库 globals 热改写的证据，不将其变为新的运行配置合同。JSON 字节／ID／hash、类构造与领域规则仍沿原实现。纯函数共享不携带 Product／Session、权限、锁、清理凭据或原生资源；热路径仍为原一层 helper 调用，无新复制或解码循环，不宣称性能基准通过。

改动前的 1,134 组 helper 观察、54 原签名／pickle 与原 756 记录观察分别保留，在候选和实际加载路径对照；原有效记录／事务与实际类型检查另验证。三视角重新评审关闭同名误判及实际接入条件，由实施 owner 在已有 R3 授权内接受本增量，不替代完整 Goal 或重要架构工作件的用户评审。回退时将规范函数、原消费者 alias 一并恢复；本片没有持久数据迁移。完整成本及验证终态见[评审记录](record-field-metadata-convergence-review.md#a56-r3叶子值校验直接复用)。

## A71 R2：旧安装评审记录的标量前缀

四个评审记录直接调用原 RecordSchema 的 keys/encode/decode；Core 不扩充。三个 Coding 模块在加载时选择固定基类的连续标量字段，明确排除嵌套、版本、可选项及辅助字段。原 for_dataclass 包含全部字段，不适用于这些子集，故使用原显式 Schema 构造。原列表捕获和转换位置、字段校验、版本分支、审批与 hash 仍由记录负责；不增加中间记录或运行 owner。

字段选择是当前 wire 的声明，不是自动演进机制；未来新增或重排字段仍须显式保留旧键集、顺序和身份。遍历增加调用、getattr、循环及临时 dict，未声称性能改善。三源完整成本净减61行，含 builtin 源增加2行；原 C08 不计收益。实际验证、三视角代码接受与局限见[推进记录](../coding-convergence-progress.md#旧安装评审记录直接复用原字段遍历a71-r2)。


## A73：Package 恢复请求的既有遍历复用

原Resources/Packages四种恢复请求直接使用同模块已经采用的RecordSchema，不扩充helper，不增接口/运行owner或环境关系。显式四表只持当前基类43字段的原顺序、wire映射、decoder与label；计算ID不进表，完整准入键集在原_exact_dict处由schema.keys加原ID组成。原Mapping浅复制与逐字段验证后一次cls构造、__post_init__与计算ID比较均保持。__post_init__触发的identity编码也由原encode按相同getter顺序完成，没有新转换/默认值/版本选择。

四个旧identity字典体与四份解码遍历退出；完整成本含四表，净减139行。已有记录及授权/回放规则不改，公开子类不反射新字段；将来字段/wire变化仍须显式保留旧版本合同。私有helper加载绑定与运行热替换边界沿原Schema，不把它当动态配置；调用/循环/临时dict不是零成本。兼容观察、原业务、三视角与接受边界见[推进记录](../coding-convergence-progress.md#package-恢复请求直接复用原字段遍历a73)及[评审记录](record-field-metadata-convergence-review.md)。Coding及原C08无本片减量，不能据此宣告Goal完成。


## A74：既有恢复 Record 的共同 wire 封装

同一记录owner的一张七字段静态表复用原encode/keys，原各类最后的restart/decision和supersession条件追加保留；request/status通过实例to_dict动态分派。该表不用于decode，原预解码、构造、版本、授权和错误合同不合并。无需新的Schema API或运行组件，parent按既有设计裁剪，三独立实际代码视角验证后有界接受，完整证据见[推进记录](../coding-convergence-progress.md#四种恢复记录的共同封装复用a74)。未来字段仍显式维护，额外调用／临时字典不称零成本；净减44完整计账，Code／C08均0，非Goal完成。
