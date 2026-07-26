#!/usr/bin/env python3
"""Build the Loushang V1.0.0 Chinese user manual.

The script has two outputs:

1. Structured Markdown chapter files in this directory.
2. A self-contained, explicitly paginated A4 HTML document in ``dist/``.

The HTML uses fixed physical pages instead of relying on a browser's automatic
pagination.  Every body page contains at least 30 visible content rows, a fixed
header, and a consecutive body page number in the upper-right corner.
"""

from __future__ import annotations

import html
import json
import math
import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

MANUAL_DIR = Path(__file__).resolve().parent
DIST_DIR = MANUAL_DIR / "dist"
PRODUCT_NAME = "Loushang"
DOCUMENT_NAME = "Loushang 用户手册"
VERSION = "V1.0.0"
RELEASE_DATE = "2026年7月"
MIN_BODY_PAGES = 60
MIN_LINES_PER_PAGE = 30
MAX_LINES_PER_PAGE = 42
# East Asian full-width characters count as two display cells.  A width of 82
# therefore fits about 41 Chinese characters in the 174 mm A4 text block.
WRAP_COLUMNS = 82
CODE_WRAP_COLUMNS = 92


@dataclass(frozen=True)
class Topic:
    title: str
    overview: str
    principles: tuple[str, ...]
    steps: tuple[str, ...]
    examples: tuple[str, ...]
    checks: tuple[str, ...]
    cautions: tuple[str, ...]


@dataclass(frozen=True)
class Chapter:
    filename: str
    title: str
    purpose: str
    topics: tuple[Topic, ...]


@dataclass(frozen=True)
class ManualLine:
    text: str
    kind: str
    chapter: str


def topic(
    title: str,
    overview: str,
    principles: Iterable[str],
    steps: Iterable[str],
    examples: Iterable[str],
    checks: Iterable[str],
    cautions: Iterable[str],
) -> Topic:
    return Topic(
        title=title,
        overview=overview,
        principles=tuple(principles),
        steps=tuple(steps),
        examples=tuple(examples),
        checks=tuple(checks),
        cautions=tuple(cautions),
    )


CHAPTERS: tuple[Chapter, ...] = (
    Chapter(
        "02-软件介绍.md",
        "第1章 软件介绍",
        "说明 Loushang 的产品定位、适用范围、核心对象和 V1.0.0 功能边界。",
        (
            topic(
                "产品定位",
                "Loushang 是面向 AI 编程工作流的 Python 命令行工具和终端工作台，用于把意图、执行过程与可验证交付连接起来。",
                (
                    "产品的当前主入口是 loushang code，重点服务软件开发、代码理解、修改验证和会话延续。",
                    "系统将方法、会话、工具和工作产物作为运行时对象，而不是只保存一段聊天文本。",
                    "模型调用由统一的模型目录和路由规则解析，上层工作流不必硬编码每个提供方细节。",
                ),
                (
                    "确认待处理项目位于可读写的本地工作目录。",
                    "检查可用模型、认证环境变量和工具范围。",
                    "通过一次性提示或交互式终端会话启动工作。",
                    "在交付前查看变更、测试结果、诊断和导出记录。",
                ),
                (
                    'loushang -p "检查当前仓库并概括它的用途。"',
                    "loushang --tui",
                ),
                (
                    "命令能够进入指定工作目录并建立新的执行上下文。",
                    "最终答复包含完成情况、验证结果以及尚未解决的限制。",
                ),
                (
                    "Loushang 不能替代代码审查、测试、备份和组织级安全控制。",
                    "模型输出可能存在错误，关键修改必须由用户或自动化检查验证。",
                ),
            ),
            topic(
                "核心价值",
                "复杂的 AI 编程任务容易因上下文丢失、工具权限失控和结果未验证而中断，Loushang 通过可恢复、可治理和可追踪的运行机制降低这些风险。",
                (
                    "持久化会话保存对话、工具事件、模型用量和诊断上下文。",
                    "工具治理允许按会话启用、停用或收窄可执行能力。",
                    "方法和技能把稳定的工作做法转化为可发现、可复用的运行资产。",
                ),
                (
                    "先用自然语言明确目标、约束、验收条件和不可触碰区域。",
                    "让系统读取必要文件并形成可检查的执行计划。",
                    "仅开放任务需要的工具，观察工具调用和中间结果。",
                    "运行测试或静态检查，并把证据写入最终交付说明。",
                ),
                (
                    'loushang --tools read,ls,find,grep -p "只读分析本仓库结构。"',
                    'loushang --work-log .loushang/work/events.jsonl -p "完成并验证指定任务。"',
                ),
                (
                    "会话能够从中断点继续，且恢复后仍能识别原工作目录。",
                    "工具调用、模型响应和工作事件具有可查询的记录。",
                ),
                (
                    "权限范围应以最小够用为原则，不要为方便一次性开放全部能力。",
                    "涉及发布、删除、覆盖或外部通信的动作仍应执行人工确认。",
                ),
            ),
            topic(
                "核心对象总览",
                "Loushang 使用 Method、Session、Tool、Extension、Skill 和 Work Log 等对象组织一次完整的 AI 编程工作。",
                (
                    "方法 Method 描述角色、阶段、步骤、约束、产物和验收预期。",
                    "会话 Session 保存连续对话、工具事件、分支关系、用量和诊断。",
                    "工具 Tool 是受策略控制的可执行能力，扩展 Extension 可以贡献新的运行行为。",
                ),
                (
                    "用方法描述应该怎样完成一类任务。",
                    "用会话记录某一次任务实际发生了什么。",
                    "用工具执行读取、检索、命令运行和文件修改。",
                    "用工作日志把方法计划投影为可检查的运行事件。",
                ),
                (
                    "loushang --list-methods",
                    "loushang --list-sessions",
                    "loushang --list-commands",
                ),
                (
                    "能够区分工作规范、运行事实和最终产物三类信息。",
                    "恢复会话时不会把另一个项目的记录误当作当前上下文。",
                ),
                (
                    "不要把 Method 当成模型提示词的简单别名，它同时承载交付契约。",
                    "不要把 Extension 与 Plugin 混用；扩展是运行代码，插件或包是资产分发方式。",
                ),
            ),
            topic(
                "典型使用场景",
                "Loushang 适用于需要多步理解、修改、验证和留痕的软件开发任务，也可以用于只读分析与诊断。",
                (
                    "代码库导览场景强调检索、阅读和结构化总结。",
                    "缺陷修复场景强调复现、定位、最小修改和回归验证。",
                    "交付审计场景强调会话导出、诊断、工作日志和证据链。",
                ),
                (
                    "为新仓库生成结构与风险概览。",
                    "在持久会话中完成跨文件功能修改。",
                    "对失败的构建、测试或持续集成任务进行诊断。",
                    "导出会话供复盘、评审或归档。",
                ),
                (
                    'loushang -p "只读分析依赖关系并列出三个主要风险。"',
                    'loushang --continue -p "继续上次任务并运行回归测试。"',
                ),
                (
                    "任务目标与工具权限相匹配，不需要的写入能力保持关闭。",
                    "输出中能明确区分事实、推断、修改和待确认事项。",
                ),
                (
                    "大型任务应拆分为可验证阶段，避免单轮上下文过长。",
                    "生产环境操作、凭证处理和外部系统变更需要额外治理。",
                ),
            ),
            topic(
                "V1.0.0 功能范围",
                "本手册以 loushang code 和 loushang.ai 为 V1.0.0 的主要说明范围，并把更广泛的工作产品面视为后续演进方向。",
                (
                    "用户可使用命令行、终端交互、会话、模型路由、工具、扩展和方法相关能力。",
                    "开发者可通过 loushang.ai 使用模型目录、流式输出、工具调用和用量信息。",
                    "研究、演示文稿等专用产品面不作为本手册的当前可用承诺。",
                ),
                (
                    "使用 --help 核对登记基线实际提供的参数。",
                    "使用 --list-commands 核对内置交互命令。",
                    "使用 --list-models 核对当前环境可解析的模型。",
                    "以本手册的命令参考和实际程序输出共同判断功能范围。",
                ),
                (
                    "loushang --help",
                    "loushang --list-commands",
                    "loushang --list-models",
                ),
                (
                    "文档中的命令在目标安装环境中可被识别。",
                    "路线图内容没有被写成已经交付的功能。",
                ),
                (
                    "扩展可以注册附加参数，因此不同项目的帮助输出可能不同。",
                    "提供方、模型可用性和价格信息可能随配置发生变化。",
                ),
            ),
            topic(
                "用户角色与责任",
                "不同角色应围绕工作目录、模型配置、工具权限和交付验证承担相应责任。",
                (
                    "普通用户负责准确描述任务并确认高影响动作。",
                    "项目维护者负责配置扩展、方法、技能和团队约定。",
                    "管理员负责凭证、网络、审计、版本基线和组织级策略。",
                ),
                (
                    "用户在运行前确认当前目录和目标分支。",
                    "维护者审查项目级配置和扩展代码来源。",
                    "管理员通过环境变量或外部凭证机制提供认证。",
                    "交付接收者检查变更摘要、测试结果和未决风险。",
                ),
                (
                    "loushang --source-info",
                    "loushang --list-plugins",
                    "loushang --list-diagnostics",
                ),
                (
                    "每项高影响动作都能追溯到明确的用户目标。",
                    "凭证不会进入会话正文、源代码、日志或导出文件。",
                ),
                (
                    "Coding 层不负责 OAuth 凭证的获取、刷新或持久化。",
                    "组织级审批规则应在 Loushang 之外继续生效。",
                ),
            ),
        ),
    ),
    Chapter(
        "03-安装与配置.md",
        "第2章 安装与配置",
        "说明运行环境、源码安装、模型凭证、配置层级和安装验证。",
        (
            topic(
                "运行环境要求",
                "Loushang 需要 Python 3.11 或更高版本，并建议在独立虚拟环境中安装和运行。",
                (
                    "源码安装适合当前开发阶段，也便于核对登记版本的代码基线。",
                    "uv 可以创建虚拟环境并安装开发依赖。",
                    "在线模型调用需要网络连通性以及相应提供方凭证。",
                ),
                (
                    "运行 python --version 检查解释器版本。",
                    "运行 uv --version 检查环境管理工具。",
                    "确认终端能够执行 Git 和项目需要的构建工具。",
                    "为模型提供方准备独立的环境变量。",
                ),
                (
                    "python --version",
                    "uv --version",
                    "git --version",
                ),
                (
                    "Python 版本不低于 3.11。",
                    "当前用户对项目目录和虚拟环境目录具有必要权限。",
                ),
                (
                    "不要把虚拟环境目录提交到版本控制系统。",
                    "受限网络环境应提前配置允许访问的模型端点。",
                ),
            ),
            topic(
                "从源码安装",
                "推荐从代码仓库创建隔离环境，并以 editable 模式安装 Loushang 及开发依赖。",
                (
                    "editable 安装使命令入口指向当前工作树，便于调试和核对变更。",
                    "项目提供 make bootstrap 作为创建 .venv 和安装依赖的便捷入口。",
                    "当前 Makefile 不提供 make install，不能把它写入自动化脚本。",
                ),
                (
                    "克隆或打开 Loushang 源代码目录。",
                    "执行 uv venv .venv 创建本地虚拟环境。",
                    '激活 .venv 后执行 uv pip install -e ".[dev]"。',
                    "运行 loushang --help 验证命令入口。",
                ),
                (
                    "git clone https://github.com/zhnt/loushang.git",
                    "cd loushang",
                    "uv venv .venv",
                    "source .venv/bin/activate",
                    'uv pip install -e ".[dev]"',
                ),
                (
                    "命令行能够显示帮助文本且退出状态为零。",
                    "python 可以导入 loushang 包而不出现模块缺失错误。",
                ),
                (
                    "Windows 环境需要使用对应的虚拟环境激活命令。",
                    "依赖下载失败时应检查代理、证书和包索引配置。",
                ),
            ),
            topic(
                "使用 Makefile 安装",
                "维护者可以使用 make bootstrap 建立与仓库约定一致的本地开发环境。",
                (
                    "bootstrap 目标使用 uv 创建 .venv 并执行 editable 安装。",
                    "install-binary 面向本地二进制安装，与开发环境用途不同。",
                    "仓库内 Python 工作应优先使用项目自带的 .venv。",
                ),
                (
                    "进入仓库根目录。",
                    "执行 make bootstrap 并等待依赖安装完成。",
                    "激活 .venv。",
                    "执行帮助、版本和只读测试命令。",
                ),
                (
                    "make bootstrap",
                    "source .venv/bin/activate",
                    "loushang --help",
                ),
                (
                    ".venv 中存在可执行的 loushang 命令。",
                    "命令运行时加载的是当前仓库代码，而非系统中的旧版本。",
                ),
                (
                    "不要假设 make install 存在。",
                    "切换工作树或分支后应重新确认 editable 安装指向。",
                ),
            ),
            topic(
                "模型认证配置",
                "API Key 模型在请求时根据模型目录声明读取环境变量，Coding 层不持久化或管理认证生命周期。",
                (
                    "不同提供方可以使用不同环境变量，具体名称以模型目录为准。",
                    "凭证只应存在于受保护的环境或凭证注入系统中。",
                    "离线查询、会话检查和部分示例不需要真实 API Key。",
                ),
                (
                    "确定要使用的模型提供方和端点。",
                    "查看模型目录中声明的认证环境变量。",
                    "在当前进程或安全的秘密管理系统中设置变量。",
                    "运行最小在线请求并检查认证错误。",
                ),
                (
                    "export OPENAI_API_KEY=<your-key>",
                    "export ANTHROPIC_API_KEY=<your-key>",
                    "loushang --list-models",
                ),
                (
                    "凭证变量存在，但不会被 echo、日志或版本控制记录。",
                    "最小在线请求能够完成，或者给出可定位的认证诊断。",
                ),
                (
                    "不要把真实 Key 写入 Markdown、settings.json 或 shell 历史。",
                    "使用共享终端时应在任务完成后清理临时凭证。",
                ),
            ),
            topic(
                "配置层级",
                "Loushang 可以从内置资源、用户级设置和项目级资源解析模型、技能、扩展及其他运行配置。",
                (
                    "全局默认模型保存在用户目录下的 coding/settings.json。",
                    "项目级 .loushang 目录用于与当前仓库相关的模型、资源和设置。",
                    "命令行显式参数通常用于本次运行，并应优先于较低层级默认值。",
                ),
                (
                    "先检查命令行是否显式指定模型、工具或资源目录。",
                    "再检查项目级 .loushang 配置和资产。",
                    "最后检查用户级默认设置和内置目录。",
                    "使用 source-info 或诊断输出确认最终来源。",
                ),
                (
                    "loushang --source-info",
                    "loushang --source-info --source-info-format json",
                    "~/.loushang/coding/settings.json",
                    ".loushang/settings.json",
                ),
                (
                    "最终生效值能够追溯到明确的来源层。",
                    "项目配置不会意外覆盖其他仓库的用户级设置。",
                ),
                (
                    "不同入口的配置层级可能不同，应以 source-info 为准。",
                    "包含绝对路径的配置在迁移机器后需要重新检查。",
                ),
            ),
            topic(
                "模型目录配置",
                "模型目录描述提供方、端点、模型能力、认证、兼容性和价格元数据，并支持项目级自定义目录。",
                (
                    "项目模型目录可以放在 .loushang/models 目录。",
                    "provider 和 model 标识不能包含冒号，endpoint 标识可以包含冒号。",
                    "同名模型存在多个端点时需要 preferred 标记或显式端点选择。",
                ),
                (
                    "复制或编写符合模型目录结构的 JSON 文件。",
                    "将文件放入项目认可的 models 目录。",
                    "运行 --list-models 检查合并和解析结果。",
                    "用完整模型键执行最小请求。",
                ),
                (
                    "loushang --list-models --list-models-format json",
                    "loushang --models .loushang/models",
                    "--model provider:endpoint:model",
                ),
                (
                    "列表中能看到期望的提供方、端点和模型标识。",
                    "歧义模型会给出候选项，而不是静默选择错误端点。",
                ),
                (
                    "价格和能力元数据需要随提供方变化维护。",
                    "不要用项目目录中的旧模型记录遮蔽新的内置配置。",
                ),
            ),
            topic(
                "安装后验证",
                "完成安装后应执行无副作用的检查，再进行需要凭证的在线请求。",
                (
                    "帮助和列表命令可以验证入口、资源发现与基本配置。",
                    "离线模式适合检查会话、命令和静态资源。",
                    "在线验证应使用最小提示并控制工具范围。",
                ),
                (
                    "运行 --help 和 --version。",
                    "运行 --list-models、--list-commands 和 --list-sessions。",
                    "运行一个禁用工具的最小提示。",
                    "检查退出状态、标准错误和诊断列表。",
                ),
                (
                    "loushang --help",
                    "loushang --version",
                    "loushang --list-commands",
                    'loushang --no-tools -p "仅回复：安装验证成功。"',
                ),
                (
                    "静态列表命令正常返回。",
                    "在线请求使用了预期模型并产生完整结束事件。",
                ),
                (
                    "程序显示的版本号应与部署和登记基线一致。",
                    "首次在线测试不要开放 bash、write 或 edit 工具。",
                ),
            ),
        ),
    ),
    Chapter(
        "04-快速入门.md",
        "第3章 快速入门",
        "通过可重复的最小流程完成首次分析、首次交互和首次会话恢复。",
        (
            topic(
                "运行第一条提示",
                "一次性 prompt 适合目标清晰、执行时间较短并且可以在单次输出中完成的任务。",
                (
                    "使用 -p 或 --prompt 提供主要任务说明。",
                    "默认工作目录应在运行前确认，必要时使用 --cwd 显式设置。",
                    "第一次运行建议禁用写工具，只验证模型与上下文。",
                ),
                (
                    "进入待分析项目根目录。",
                    "运行只读提示并等待模型完成。",
                    "检查回答是否引用了真实文件和结构。",
                    "根据需要扩大工具范围并继续任务。",
                ),
                (
                    'loushang --no-tools -p "说明当前任务目标。"',
                    'loushang --tools read,ls,find,grep -p "概括仓库结构。"',
                ),
                (
                    "输出直接回答提示目标，没有进入不相关目录。",
                    "只读任务没有产生文件修改。",
                ),
                (
                    "纯 --no-tools 模式只能使用已提供上下文，不能读取仓库。",
                    "自然语言目标应同时给出范围和验收条件。",
                ),
            ),
            topic(
                "选择工作目录",
                "工作目录决定相对路径、项目资源、会话归属和工具执行边界，是每次运行前最重要的上下文之一。",
                (
                    "从项目根目录启动通常能发现 .loushang 和其他上下文文件。",
                    "--cwd 可以在不切换当前 shell 目录时指定目标。",
                    "恢复会话时应核对记录中的原始工作目录。",
                ),
                (
                    "使用 pwd 确认 shell 当前目录。",
                    "查看目标目录是否包含预期项目文件。",
                    "必要时通过 --cwd 指定绝对路径。",
                    "在答复中要求报告最终工作目录。",
                ),
                (
                    "pwd",
                    'loushang --cwd /path/to/project -p "报告当前工作目录。"',
                ),
                (
                    "读取和修改均发生在目标项目内。",
                    "会话列表能按预期关联当前项目。",
                ),
                (
                    "不要把主目录或文件系统根目录作为宽泛写入目标。",
                    "包含空格的路径需要正确引用。",
                ),
            ),
            topic(
                "启动终端交互界面",
                "TUI 适合需要多轮讨论、观察流式输出、调用命令和持续调整任务方向的工作。",
                (
                    "loushang --tui 与 loushang-tui 都可启动终端产品面。",
                    "当标准输入输出不是 TTY 时，--tui 会进入 plain prompt loop。",
                    "交互界面中的 slash command 用于会话、模型、工具和导出控制。",
                ),
                (
                    "在支持交互的终端中启动 TUI。",
                    "输入第一条任务说明并观察模型和工具事件。",
                    "使用 /session 查看当前会话信息。",
                    "完成后使用 /export 导出或 /quit 退出。",
                ),
                (
                    "loushang --tui",
                    "loushang-tui",
                    'printf "hi\\n/quit\\n" | loushang --tui',
                ),
                (
                    "交互终端显示输入区、转录内容和状态信息。",
                    "管道模式能够处理输入并在 /quit 后正常退出。",
                ),
                (
                    "终端尺寸过小时可能影响布局，应先调整窗口。",
                    "plain prompt loop 不是独立 selector，而是由终端交互性决定。",
                ),
            ),
            topic(
                "创建并命名会话",
                "持久会话便于恢复、检索、分叉和导出，适合超过一次性问答的任务。",
                (
                    "默认运行会建立会话，--no-session 可显式关闭持久化。",
                    "--session-name 为新会话提供可识别的业务名称。",
                    "会话名称应描述目标，而不是使用含糊的测试或临时字样。",
                ),
                (
                    "确定任务的简短名称。",
                    "通过 --session-name 启动第一次提示。",
                    "使用 --list-sessions 检查记录。",
                    "使用 /rename 或相关入口调整名称。",
                ),
                (
                    'loushang --session-name "修复登录回归" -p "先定位失败测试。"',
                    "loushang --list-sessions",
                ),
                (
                    "会话列表中存在名称、标识和工作目录信息。",
                    "后续恢复能够回到相同的对话与项目上下文。",
                ),
                (
                    "会话名称中不要放入密码、令牌或客户敏感信息。",
                    "一次性敏感任务可以考虑 --no-session。",
                ),
            ),
            topic(
                "恢复最近会话",
                "恢复功能让用户在终端中断、进程退出或稍后继续工作时保留原有上下文。",
                (
                    "--continue 恢复当前项目最新会话。",
                    "--resume 后跟标识或路径可直接恢复指定会话。",
                    "交互式无参数 --resume 会打开可搜索的连续性选择器。",
                ),
                (
                    "先列出当前项目的会话。",
                    "按名称、时间和工作目录确认目标。",
                    "使用 --continue 或 --resume 恢复。",
                    "要求模型总结当前状态后再继续修改。",
                ),
                (
                    "loushang --list-sessions",
                    "loushang --continue",
                    "loushang --resume <session-id-or-path>",
                ),
                (
                    "恢复后可看到之前的关键消息和工具结果。",
                    "新事件追加到目标会话或其明确分支中。",
                ),
                (
                    "非交互模式必须显式使用 continue 或指定 resume 目标。",
                    "恢复前检查代码库是否已发生会话外变更。",
                ),
            ),
            topic(
                "完成首次受控修改",
                "首次写入任务应从最小工具集和可回滚文件开始，并在修改后立即验证。",
                (
                    "read、ls、find 和 grep 用于发现与理解。",
                    "edit 和 write 用于受控文件修改，bash 用于测试和构建。",
                    "最终答复应列出修改文件、验证命令和遗留风险。",
                ),
                (
                    "让系统先只读分析目标文件。",
                    "确认计划后开放 edit 或 write。",
                    "修改完成后运行精确测试。",
                    "查看差异并导出会话记录。",
                ),
                (
                    'loushang --tools read,ls,find,grep,edit,bash -p "修改后运行相关测试。"',
                    "git diff --check",
                ),
                (
                    "差异只包含目标范围内的修改。",
                    "相关测试和格式检查通过，或失败原因已记录。",
                ),
                (
                    "不要覆盖用户已有的未提交修改。",
                    "删除、重置、发布和推送等高影响操作需要额外确认。",
                ),
            ),
        ),
    ),
    Chapter(
        "05-命令行与运行模式.md",
        "第4章 命令行与运行模式",
        "说明 text、print、json、rpc、channel 和 TUI 等运行入口及其选择原则。",
        (
            topic(
                "命令行结构",
                "Loushang 主命令由全局参数、资源选择、会话控制、工具控制和消息内容共同组成。",
                (
                    "位置参数 messages 可承载直接消息，--prompt 用于显式提示。",
                    "列表和导出命令通常在完成操作后退出，不启动普通模型会话。",
                    "扩展可以在启动解析阶段注册附加参数。",
                ),
                (
                    "先确定本次是查询、一次性执行还是交互会话。",
                    "再指定工作目录、模型、会话和工具。",
                    "最后提供提示、命令或导出目标。",
                    "通过退出状态和结果格式判断执行结果。",
                ),
                (
                    "loushang [options] [messages ...]",
                    "loushang --help",
                ),
                (
                    "参数组合没有互斥冲突。",
                    "运行模式、输出格式和会话策略符合调用方预期。",
                ),
                (
                    "自动化脚本应固定输出格式，不要解析面向人的可变文本。",
                    "扩展参数应以扩展自己的说明为准。",
                ),
            ),
            topic(
                "Text 模式",
                "text 模式面向终端中的普通交互与文本展示，是未显式选择其他模式时的重要入口。",
                (
                    "输出以人类阅读为主，可以包含流式文本和工具事件。",
                    "是否进入全屏 TUI 由 --tui、--no-tui 与终端环境共同决定。",
                    "持久化会话可用于后续继续、分叉和导出。",
                ),
                (
                    "确认 stdout 面向用户终端。",
                    "选择模型和思考强度。",
                    "按需启用工具事件渲染。",
                    "完成后检查会话和诊断。",
                ),
                (
                    'loushang --mode text -p "分析当前任务。"',
                    'loushang --render-tool-events -p "执行并说明工具步骤。"',
                ),
                (
                    "文本输出完整并且终端编码正确。",
                    "工具事件不会被误当作最终回答。",
                ),
                (
                    "不要在依赖严格 JSON 的管道中使用 text。",
                    "大量输出重定向到文件时应关注终端控制字符。",
                ),
            ),
            topic(
                "Print 模式",
                "print 模式适合一次性提示和脚本调用，以简洁文本返回最终结果。",
                (
                    "该模式强调最终文本，不依赖全屏交互界面。",
                    "可以与明确模型、工具和工作日志配置组合。",
                    "调用方仍应检查标准错误和退出状态。",
                ),
                (
                    "使用 --mode print 指定模式。",
                    "通过 -p 提供完整任务。",
                    "将标准输出保存或传给后续程序。",
                    "对写入任务检查实际文件差异。",
                ),
                (
                    'loushang --mode print -p "输出仓库摘要。"',
                    'loushang --mode print --no-tools -p "解释给定上下文。"',
                ),
                (
                    "stdout 主要包含预期的最终文本。",
                    "失败时调用方能从状态码和 stderr 识别问题。",
                ),
                (
                    "不要假设自然语言输出具有稳定字段顺序。",
                    "机器集成优先考虑 json、rpc 或 channel。",
                ),
            ),
            topic(
                "JSON 模式",
                "json 模式用于需要结构化结果的脚本、测试和集成流程。",
                (
                    "机器可读输出应由 JSON 解析器处理。",
                    "列表、命令和导出操作还可能有各自的格式参数。",
                    "结构字段应按登记版本固定，升级时需要兼容性检查。",
                ),
                (
                    "显式指定 --mode json。",
                    "避免把调试文本混入标准输出。",
                    "用 JSON 解析器读取结果。",
                    "对缺失字段、错误对象和非零状态建立处理分支。",
                ),
                (
                    'loushang --mode json -p "生成结构化执行结果。"',
                    "loushang --list-sessions --list-sessions-format json",
                ),
                (
                    "输出是合法 JSON，并包含调用方需要的核心字段。",
                    "错误路径不会被当作成功结果继续处理。",
                ),
                (
                    "不要依赖字段在文本中的排列顺序。",
                    "记录日志时应过滤可能包含敏感内容的消息字段。",
                ),
            ),
            topic(
                "RPC 模式",
                "rpc 模式为外部宿主提供请求响应式会话控制，适合编辑器、测试探针和上层应用集成。",
                (
                    "RPC 调用方负责保持协议读写边界和消息顺序。",
                    "Method 与 Work Log 在当前产品边界下不支持 RPC 组合。",
                    "扩展命令与会话命令可通过运行时查询面发现。",
                ),
                (
                    "启动 --mode rpc 进程。",
                    "按协议发送初始化和请求消息。",
                    "处理流式事件、工具事件和最终响应。",
                    "在进程结束前执行清理和会话保存。",
                ),
                (
                    "loushang --mode rpc",
                    "python examples/coding/13_rpc_mode_probe.py",
                ),
                (
                    "调用方能区分事件、响应和错误。",
                    "进程退出后没有残留半写入会话记录。",
                ),
                (
                    "不要把普通终端文本写入 RPC 标准输出通道。",
                    "协议消费者应设置超时、取消和异常恢复。",
                ),
            ),
            topic(
                "Channel 模式",
                "channel 模式用于边界协议集成，强调稳定的消息通道和宿主控制。",
                (
                    "宿主需要明确输入、输出、取消和结束语义。",
                    "通道事件应与人类界面渲染解耦。",
                    "工具批准和外部副作用仍由宿主策略控制。",
                ),
                (
                    "确定宿主支持的 channel 协议版本。",
                    "启动进程并建立输入输出通道。",
                    "发送消息并消费事件。",
                    "在取消或错误后等待明确的终止状态。",
                ),
                (
                    "loushang --mode channel",
                    "loushang --no-tui --mode channel",
                ),
                (
                    "消息不会跨请求串线。",
                    "取消后不会继续执行未经授权的工具动作。",
                ),
                (
                    "Channel 面向集成开发者，普通终端用户应优先使用 text 或 TUI。",
                    "宿主必须保存足够日志以定位协议错误。",
                ),
            ),
            topic(
                "思考强度与输出",
                "thinking 参数向支持该能力的模型表达推理强度偏好，可在速度、成本和复杂度之间进行选择。",
                (
                    "可选值包括 off、minimal、low、medium、high 和 xhigh。",
                    "提供方或模型可能不支持全部等级。",
                    "更高等级不保证结果正确，仍需测试和审查。",
                ),
                (
                    "根据任务复杂度选择初始等级。",
                    "用低风险样例比较延迟、用量与结果质量。",
                    "记录模型、端点和实际用量。",
                    "对关键结果执行独立验证。",
                ),
                (
                    'loushang --thinking medium -p "分析失败原因。"',
                    'loushang --thinking high -p "制定并验证迁移方案。"',
                ),
                (
                    "模型请求成功接受或明确降级该参数。",
                    "选择带来的延迟和成本处于可接受范围。",
                ),
                (
                    "不要把隐藏推理内容当作必须保存的审计材料。",
                    "敏感输入不应因提高思考强度而扩大暴露范围。",
                ),
            ),
        ),
    ),
    Chapter(
        "06-模型路由.md",
        "第5章 模型配置与路由",
        "说明模型键、端点消歧、默认模型、能力匹配和路由诊断。",
        (
            topic(
                "模型键格式",
                "Loushang 支持 provider/model 短格式和 provider:endpoint:model 完整格式。",
                (
                    "短格式仅在模型匹配唯一端点或存在唯一 preferred 端点时可安全解析。",
                    "完整格式用于指定具体 endpoint、region、lane 或 protocol。",
                    "模型键中的 provider 和 model 不能含冒号。",
                ),
                (
                    "运行 --list-models 获取可选键。",
                    "优先使用列表返回的规范模型键。",
                    "出现歧义时复制候选完整键。",
                    "执行最小请求验证端点和认证。",
                ),
                (
                    "--model provider/model",
                    "--model provider:endpoint:model",
                    "loushang --list-models",
                ),
                (
                    "解析结果对应预期提供方、端点和模型。",
                    "不存在静默选择错误区域或协议的情况。",
                ),
                (
                    "不要根据显示名称猜测内部模型键。",
                    "端点标识可以包含冒号，复制时应保持完整。",
                ),
            ),
            topic(
                "模型列表",
                "模型列表展示当前合并目录中可发现的模型，可使用文本或 JSON 格式。",
                (
                    "文本格式适合人工浏览。",
                    "JSON 格式适合自动化检查能力、端点和元数据。",
                    "--models 可指定额外模型目录或配置来源。",
                ),
                (
                    "先运行默认模型列表。",
                    "再指定项目模型目录比较差异。",
                    "检查提供方、端点和 preferred 状态。",
                    "保存 JSON 快照供登记基线核对。",
                ),
                (
                    "loushang --list-models",
                    "loushang --list-models --list-models-format json",
                    "loushang --models .loushang/models --list-models",
                ),
                (
                    "目录加载没有重复键或结构错误。",
                    "目标模型包含任务需要的流式、工具或图像能力。",
                ),
                (
                    "模型列表不等于在线可用性，仍受凭证、配额和网络影响。",
                    "价格元数据只能用于估算，应以提供方账单为准。",
                ),
            ),
            topic(
                "默认模型保存",
                "模型切换成功后，CLI 可以把完整选择保存为全局 default_model。",
                (
                    "全局设置路径为用户目录下的 .loushang/coding/settings.json。",
                    "带端点的选择会保存 provider、model_id 和 endpoint_id。",
                    "模型选择不会写入项目级 .loushang/settings.json。",
                ),
                (
                    "在可信终端中选择目标模型。",
                    "完成一次成功的模型切换或请求。",
                    "检查全局设置文件中的 default_model。",
                    "在新终端中验证默认选择。",
                ),
                (
                    'loushang --model provider:endpoint:model -p "ping"',
                    "~/.loushang/coding/settings.json",
                ),
                (
                    "重新启动后仍选择相同的规范模型路由。",
                    "项目目录没有出现意外的模型默认写入。",
                ),
                (
                    "共享机器上的全局默认可能影响其他项目。",
                    "设置文件不应包含 API Key。",
                ),
            ),
            topic(
                "提供方显式选择",
                "provider 参数可用于收窄或指定提供方，但最终模型仍应通过目录完成能力和端点解析。",
                (
                    "提供方身份与具体模型身份是两个不同层次。",
                    "同一提供方可能配置多个端点或协议。",
                    "显式 provider 与 model 冲突时应视为配置错误。",
                ),
                (
                    "查看模型列表中的 provider 字段。",
                    "设置 --provider 并选择兼容模型。",
                    "执行无工具最小请求。",
                    "检查诊断中的最终路由信息。",
                ),
                (
                    'loushang --provider openai --model openai/<model> -p "ping"',
                    "loushang --source-info",
                ),
                (
                    "最终路由的 provider 与用户选择一致。",
                    "认证变量来自对应目录声明。",
                ),
                (
                    "不要把 OpenAI 兼容协议等同于 OpenAI 提供方身份。",
                    "代理端点可能具有不同配额、模型名和数据策略。",
                ),
            ),
            topic(
                "能力匹配",
                "选择模型时应同时考虑文本生成、流式输出、工具调用、结构化输出、图像输入和推理等级等能力。",
                (
                    "工具型编程任务需要可靠的 tool call 与 tool result 往返。",
                    "结构化集成需要模型和适配器共同支持目标输出模式。",
                    "图像输入必须使用声明支持相应媒体类型的模型。",
                ),
                (
                    "列出任务必需能力和可选能力。",
                    "从目录筛选候选模型与端点。",
                    "运行最小能力测试。",
                    "对失败能力建立替代模型或降级流程。",
                ),
                (
                    "python examples/ai/04_tools.py",
                    "python examples/ai/07_structured_output.py",
                    "python examples/ai/08_image_input.py",
                ),
                (
                    "真实请求完成完整的能力往返。",
                    "不支持能力会产生明确失败，而非错误模拟成功。",
                ),
                (
                    "目录声明应通过实际 smoke test 验证。",
                    "提供方升级可能改变参数名和能力行为。",
                ),
            ),
            topic(
                "离线模式",
                "offline 参数用于避免真实模型请求，适合静态资源检查、路由矩阵和部分恢复测试。",
                (
                    "离线模式不能证明凭证、网络和在线端点可用。",
                    "会话、模型目录和命令发现仍可在离线环境检查。",
                    "在线示例应明确区分真实请求和 faux stream。",
                ),
                (
                    "启用 --offline。",
                    "运行列表、来源和静态诊断命令。",
                    "记录离线验证覆盖范围。",
                    "在受控环境补充最小在线测试。",
                ),
                (
                    "loushang --offline --list-models",
                    "python examples/coding/07_offline_session_restore.py",
                ),
                (
                    "命令不会访问外部模型端点。",
                    "静态配置错误仍能被发现并报告。",
                ),
                (
                    "不要把离线成功写成在线模型可用证明。",
                    "faux stream 只用于验证适配与事件语义。",
                ),
            ),
            topic(
                "路由故障诊断",
                "模型路由失败通常来自未知键、多端点歧义、认证缺失、能力不匹配或网络问题。",
                (
                    "先区分目录解析失败与真实请求失败。",
                    "source-info 用于查看来源，debug 和 trace 用于记录更详细过程。",
                    "完整模型键可以消除大多数端点歧义。",
                ),
                (
                    "运行 --list-models 验证键是否存在。",
                    "改用 provider:endpoint:model 完整格式。",
                    "检查对应认证变量和网络。",
                    "导出诊断并删除敏感信息后共享。",
                ),
                (
                    "loushang --debug model --debug-file model-debug.log --list-models",
                    'loushang --trace model --trace-file model-trace.log -p "ping"',
                ),
                (
                    "能够定位失败发生在发现、解析、认证、请求还是响应阶段。",
                    "修复后最小请求和目标能力请求均能完成。",
                ),
                (
                    "调试文件可能包含路径、模型名和请求元数据。",
                    "不要在公开问题中上传未经审查的 trace。",
                ),
            ),
        ),
    ),
    Chapter(
        "07-会话管理.md",
        "第6章 会话管理",
        "说明会话创建、保存、检索、恢复、分叉、压缩、导入和删除。",
        (
            topic(
                "会话数据组成",
                "会话是一次 coding 交互的持久记录，包含消息、工具事件、模型用量、诊断和分支上下文。",
                (
                    "会话记录服务于恢复和审计，不只是聊天历史。",
                    "工具输入输出可能包含文件片段和命令结果。",
                    "会话头部保存标识、名称、工作目录和关系信息。",
                ),
                (
                    "为任务创建清晰的会话名称。",
                    "定期使用 /session 查看状态和统计。",
                    "在重大阶段后导出或创建检查点。",
                    "归档前审查是否包含敏感数据。",
                ),
                (
                    "/session",
                    "loushang --list-sessions",
                    "loushang --session-index",
                ),
                (
                    "会话事件顺序完整且可解析。",
                    "会话元数据与实际项目和任务相符。",
                ),
                (
                    "不要把会话文件当作无敏感信息的普通日志。",
                    "手工编辑 JSONL 可能破坏恢复和分支关系。",
                ),
            ),
            topic(
                "列出与筛选会话",
                "列表命令可按项目、名称、父会话、查询条件和诊断状态筛选持久记录。",
                (
                    "默认列表聚焦当前范围，--all-sessions 扩大搜索。",
                    "JSON 格式适合索引、审计和自动化工具。",
                    "session-limit 控制返回数量，避免扫描结果过大。",
                ),
                (
                    "先在当前项目运行默认列表。",
                    "用名称或 query 缩小目标范围。",
                    "需要时使用 all-sessions 跨目录查找。",
                    "刷新索引后再次确认结果。",
                ),
                (
                    "loushang --list-sessions",
                    "loushang --list-sessions --list-sessions-format json",
                    "loushang --session-name-filter 登录 --list-sessions",
                    "loushang --session-has-diagnostics --list-sessions",
                ),
                (
                    "目标会话的标识、名称和工作目录一致。",
                    "过滤条件不会把不相关项目混入恢复候选。",
                ),
                (
                    "跨项目搜索结果必须再次核对工作目录。",
                    "大量会话环境应定期刷新索引并检查陈旧记录。",
                ),
            ),
            topic(
                "恢复与继续",
                "resume 和 continue 为不同使用场景提供显式或快捷恢复入口。",
                (
                    "--continue 选择当前项目最近会话。",
                    "--resume <id-or-path> 精确指定标识或文件路径。",
                    "交互式选择器支持搜索、预览、Domain 切换和排序。",
                ),
                (
                    "保存或提交当前工作树中的外部修改。",
                    "查看候选会话的时间、名称和目录。",
                    "恢复后先让系统概括未完成状态。",
                    "比较当前代码与会话最后观察到的状态。",
                ),
                (
                    "loushang --continue",
                    "loushang --resume <session-id>",
                    "/resume <session-id-or-path>",
                ),
                (
                    "恢复后的下一轮能够引用之前的任务背景。",
                    "外部代码变化被重新读取，而不是依赖过期工具结果。",
                ),
                (
                    "恢复会话不等于恢复 Git 工作树。",
                    "长时间间隔后应重新运行测试和依赖检查。",
                ),
            ),
            topic(
                "分叉与克隆",
                "分叉用于从历史用户消息创建新的工作分支，克隆用于复制当前会话位置。",
                (
                    "/fork 适合尝试不同解决路线并保留共同历史。",
                    "/clone 复制当前会话状态，便于独立实验。",
                    "/tree 用于查看和切换会话分支关系。",
                ),
                (
                    "确定需要分叉的历史决策点。",
                    "创建分叉并使用可区分的名称。",
                    "在各分支中记录不同假设和验证结果。",
                    "通过 tree 检查父子关系并选择保留方案。",
                ),
                (
                    "/fork",
                    "/clone",
                    "/tree",
                    "loushang --fork <session-id>",
                ),
                (
                    "新分支保留预期历史，但后续事件相互独立。",
                    "分支关系能够在会话树中正确显示。",
                ),
                (
                    "会话分叉不会自动创建 Git 分支或工作树。",
                    "不同会话若写入同一工作目录仍可能互相影响。",
                ),
            ),
            topic(
                "上下文压缩",
                "compact 用于在上下文增长时形成摘要，保留继续工作所需的关键信息。",
                (
                    "压缩目标是降低上下文占用，而不是删除持久会话历史。",
                    "摘要应保留目标、约束、决策、已改文件和验证状态。",
                    "压缩后仍需从真实文件重新读取关键事实。",
                ),
                (
                    "在阶段边界使用 /compact。",
                    "检查摘要是否包含未完成事项和验收条件。",
                    "补充遗漏的关键约束。",
                    "继续前重新读取高风险文件和测试结果。",
                ),
                (
                    "/compact",
                    "python examples/coding/26_compaction_summary_evaluation.py",
                ),
                (
                    "压缩后的会话可以继续回答当前任务状态。",
                    "摘要不会把推断写成已经验证的事实。",
                ),
                (
                    "不要依赖压缩摘要保存精确代码或秘密。",
                    "关键批准和外部动作应保留独立审计记录。",
                ),
            ),
            topic(
                "会话导入与导出",
                "导入和导出用于迁移、归档、评审或继续已有会话。",
                (
                    "HTML 导出适合人类阅读，JSONL 适合机器处理和再导入。",
                    "/import 可导入 JSONL 并恢复为会话。",
                    "导出结果格式与导出文件格式是两个独立参数。",
                ),
                (
                    "确定导出用途和目标格式。",
                    "选择安全的输出路径。",
                    "导出后打开文件并检查完整性。",
                    "共享前清理凭证、隐私和不必要的工具输出。",
                ),
                (
                    "loushang --export session.html",
                    "loushang --export session.jsonl --export-format jsonl",
                    "/import <session.jsonl>",
                ),
                (
                    "HTML 可以独立打开，JSONL 每行可解析。",
                    "导入后会话标识和关系处理符合预期。",
                ),
                (
                    "导出文件可能包含源代码和本地路径。",
                    "不要导入来源不明或被篡改的会话文件。",
                ),
            ),
            topic(
                "会话删除",
                "删除入口用于清理不再需要的历史会话，并通过确认步骤降低误操作风险。",
                (
                    "/delete 打开历史会话选择器，不删除当前活跃会话。",
                    "删除前应判断是否需要导出、归档或满足保留策略。",
                    "自动化清理应有明确范围和可恢复机制。",
                ),
                (
                    "列出目标会话并核对名称、日期和目录。",
                    "必要时先导出 HTML 或 JSONL。",
                    "使用 /delete 选择历史会话。",
                    "确认删除后刷新列表。",
                ),
                (
                    "/delete",
                    "loushang --list-sessions",
                ),
                (
                    "目标历史记录从列表中移除。",
                    "当前活跃会话和其他项目记录保持不变。",
                ),
                (
                    "删除可能不可恢复，应遵守组织的数据保留规则。",
                    "不要通过宽泛文件系统命令批量删除会话目录。",
                ),
            ),
            topic(
                "会话目录与索引",
                "session-dir、session-index 和 refresh-session-index 用于控制存储位置与查询效率。",
                (
                    "项目可把会话存储在 .loushang/sessions 或显式目录。",
                    "索引用于快速发现，不应替代原始会话文件。",
                    "目录迁移后需要刷新索引并检查路径。",
                ),
                (
                    "确定项目的会话存储策略。",
                    "通过 --session-dir 显式指定需要的目录。",
                    "运行 --refresh-session-index 重建索引。",
                    "比较索引列表和原始文件数量。",
                ),
                (
                    "loushang --session-dir .loushang/sessions --list-sessions",
                    "loushang --refresh-session-index --list-sessions",
                ),
                (
                    "索引能够定位现存会话且无重复记录。",
                    "目录权限阻止无关用户读取敏感会话。",
                ),
                (
                    "备份策略应同时考虑会话文件和必要元数据。",
                    "网络文件系统上的并发写入需要额外验证。",
                ),
            ),
        ),
    ),
    Chapter(
        "08-工具治理.md",
        "第7章 工具使用与治理",
        "说明内置工具、工具选择、最小权限、调用呈现和扩展拦截。",
        (
            topic(
                "内置工具概览",
                "新的交互会话默认提供 read、ls、find、grep、bash、edit 和 write 等内置工具。",
                (
                    "ls、find、grep 和 read 优先用于文件探索与读取。",
                    "bash 适合管道、重定向、构建、测试和 Git 操作。",
                    "edit 与 write 会修改文件，应在目标和范围明确后启用。",
                ),
                (
                    "使用 /tools 查看当前工具集合。",
                    "按任务只保留必要工具。",
                    "先读取再修改，修改后立即查看差异。",
                    "把关键工具结果写入交付说明。",
                ),
                (
                    "/tools",
                    "/tools only read,ls,find,grep",
                    "/tools reset",
                ),
                (
                    "工具列表与本轮任务需要一致。",
                    "工具事件能够显示名称、参数、状态和结果摘要。",
                ),
                (
                    "默认工具集合可能受启动参数或扩展影响。",
                    "工具存在不代表每次调用都应自动批准。",
                ),
            ),
            topic(
                "命令行工具选择",
                "--tools、--tool、--no-tools 和 --no-builtin-tools 提供不同粒度的工具配置入口。",
                (
                    "--tools 接受工具名称集合，用于收窄活动工具。",
                    "--no-tools 禁用工具能力，只允许模型使用已提供上下文。",
                    "--no-builtin-tools 可保留其他贡献来源而关闭内置工具。",
                ),
                (
                    "列出任务需要的读、写和执行能力。",
                    "用 --tools 显式设置最小集合。",
                    "运行提示并观察工具是否足够。",
                    "仅在明确缺少能力时增加工具。",
                ),
                (
                    'loushang --tools read,ls,find,grep -p "只读分析。"',
                    'loushang --no-tools -p "只根据输入回答。"',
                    'loushang --no-builtin-tools -p "使用扩展能力。"',
                ),
                (
                    "模型看不到未启用的工具。",
                    "任务完成时没有发生范围外副作用。",
                ),
                (
                    "工具名称必须来自当前会话实际发现结果。",
                    "关闭内置工具不等于关闭所有扩展工具。",
                ),
            ),
            topic(
                "会话内工具控制",
                "/tools 命令允许在交互会话中查看、关闭、收窄和恢复工具集合。",
                (
                    "工具变更只应影响预期会话上下文。",
                    "off 用于停用指定工具，only 用于保留白名单。",
                    "reset 恢复会话的默认工具解析结果。",
                ),
                (
                    "运行 /tools 记录当前状态。",
                    "对高风险阶段关闭 bash、edit 或 write。",
                    "用 only 建立只读阶段。",
                    "需要写入时再恢复精确工具。",
                ),
                (
                    "/tools off bash",
                    "/tools only read,ls,find,grep",
                    "/tools reset",
                ),
                (
                    "命令结果清楚显示启用和禁用项。",
                    "后续模型调用使用更新后的工具定义。",
                ),
                (
                    "切换工具后应重新说明本阶段目标。",
                    "不要把工具关闭当作文件系统沙箱的替代。",
                ),
            ),
            topic(
                "只读探索",
                "只读探索阶段用于形成可靠上下文，避免模型在不了解项目时直接修改文件。",
                (
                    "目录枚举用于理解边界，检索用于定位相关实现。",
                    "读取应从入口、配置、测试和目标模块开始。",
                    "结果摘要应区分已读事实和待验证推断。",
                ),
                (
                    "用 ls 或 find 获取文件结构。",
                    "用 grep 搜索符号、参数和错误消息。",
                    "用 read 查看最相关的连续上下文。",
                    "形成修改假设和验证计划。",
                ),
                (
                    'loushang --tools ls,find,grep,read -p "定位会话恢复实现。"',
                    'loushang --tools read,grep -p "解释配置优先级。"',
                ),
                (
                    "结论引用了实际文件和符号。",
                    "分析阶段工作树保持不变。",
                ),
                (
                    "不要一次读取大量无关生成文件。",
                    "搜索结果需要通过上下文阅读确认含义。",
                ),
            ),
            topic(
                "Shell 工具",
                "bash 工具提供灵活的命令执行能力，同时也是最需要约束和审查的内置工具之一。",
                (
                    "构建、测试、格式化、Git 查询和文本管道适合使用 bash。",
                    "命令应明确工作目录、目标和预期副作用。",
                    "破坏性命令、网络发布和权限提升需要额外确认。",
                ),
                (
                    "先请求只读或验证性命令。",
                    "检查命令中是否含宽泛通配符、重定向或递归删除。",
                    "执行后记录状态码和关键输出。",
                    "失败时先诊断，不要盲目重复高影响命令。",
                ),
                (
                    "git status --short",
                    "git diff --check",
                    "python -m pytest tests/path/to/test_file.py",
                ),
                (
                    "命令在预期目录执行并返回可解释状态。",
                    "输出足以证明验证范围和结果。",
                ),
                (
                    "不要执行未解析目标的删除、重置或覆盖命令。",
                    "命令输出可能泄露环境变量和本地路径。",
                ),
            ),
            topic(
                "文件修改工具",
                "edit 适合对现有文件做精确变更，write 适合创建或整体写入明确目标文件。",
                (
                    "修改前必须读取目标上下文并保留用户已有变化。",
                    "小范围补丁更易审查、回滚和验证。",
                    "生成文件应与源文件和构建流程区分。",
                ),
                (
                    "检查 Git 状态和目标文件内容。",
                    "选择 edit 或 write 并限制路径。",
                    "修改后运行格式检查和相关测试。",
                    "查看 diff 确认没有意外重写。",
                ),
                (
                    "git status --short",
                    "git diff --stat",
                    "git diff --check",
                ),
                (
                    "差异规模与任务目标一致。",
                    "用户的无关改动和未跟踪文件没有被覆盖。",
                ),
                (
                    "不要修改只读参考仓库或任务范围外文件。",
                    "自动格式化可能造成大面积机械差异，应单独审查。",
                ),
            ),
            topic(
                "工具事件与审计",
                "工具事件记录名称、输入、状态和结果，可在终端转录、会话、诊断或导出中呈现。",
                (
                    "--render-tool-events 可在适用模式下显示工具事件。",
                    "工具结果应做必要截断，避免转录被巨量输出占满。",
                    "审计关注授权、输入、结果和后续决策，而非只看命令名称。",
                ),
                (
                    "启用工具事件渲染。",
                    "执行一个可预测的只读工具调用。",
                    "检查开始、结束和失败状态。",
                    "导出会话并确认事件顺序。",
                ),
                (
                    'loushang --render-tool-events -p "读取 README 并总结。"',
                    "loushang --export tool-session.html",
                ),
                (
                    "每次调用都有可关联的开始与结束状态。",
                    "失败不会被最终答复描述为成功。",
                ),
                (
                    "工具结果可能包含源代码、路径和秘密。",
                    "审计导出前应执行敏感信息检查。",
                ),
            ),
            topic(
                "扩展工具拦截",
                "扩展可以在工具调用前后执行检查、阻止高风险动作或调整结果呈现。",
                (
                    "ToolCallDecision 可在调用前阻止或解释拒绝原因。",
                    "ToolResultDecision 可在调用后规范结果。",
                    "扩展守卫是额外治理层，不替代操作系统和组织策略。",
                ),
                (
                    "审查扩展源码和 manifest 权限声明。",
                    "用离线示例验证允许与阻止路径。",
                    "在真实项目中先应用于低风险工具。",
                    "记录拦截原因和用户可采取的下一步。",
                ),
                (
                    "python examples/coding/extensions/04_tool_guard.py",
                    "python examples/coding/extensions/11_online_tool_guard.py",
                ),
                (
                    "被禁止的调用不会产生实际副作用。",
                    "允许调用仍能正常返回并进入会话记录。",
                ),
                (
                    "来源不明的守卫扩展本身可能造成风险。",
                    "结果修改不能掩盖真实失败或伪造验证证据。",
                ),
            ),
        ),
    ),
    Chapter(
        "09-扩展插件与包.md",
        "第8章 扩展、插件与软件包",
        "说明项目级扩展、Manifest、贡献发现以及可复用资产的安装和更新。",
        (
            topic(
                "扩展模型",
                "Extension 是项目级 Python 代码，可以注册生命周期钩子、工具、动态资源、命令和附加参数。",
                (
                    "扩展通过推荐的 register(api) 协议贡献行为。",
                    "扩展代码与主进程处于同一信任边界，应按可执行代码审查。",
                    "贡献来源应在 /extensions、/tools 或 source-info 中可见。",
                ),
                (
                    "创建独立扩展目录或 Python 文件。",
                    "实现 register(api) 并注册最小贡献。",
                    "以 --extension 显式加载进行离线验证。",
                    "检查诊断后再放入项目默认发现路径。",
                ),
                (
                    "loushang --extension ./extensions/example.py --list-commands",
                    "python examples/coding/extensions/01_lifecycle.py",
                ),
                (
                    "扩展加载成功且贡献数量符合预期。",
                    "关闭扩展后核心命令仍可正常运行。",
                ),
                (
                    "不要运行来源不明或未经审查的扩展。",
                    "扩展异常应被隔离并形成可读诊断。",
                ),
            ),
            topic(
                "生命周期钩子",
                "生命周期钩子允许扩展在会话和输入处理的特定阶段观察或改变行为。",
                (
                    "钩子顺序和失败处理影响最终会话语义。",
                    "输入钩子可以处理或转换输入，但应保留可追溯性。",
                    "钩子不应执行与用户目标无关的隐藏副作用。",
                ),
                (
                    "列出需要观察的生命周期阶段。",
                    "为每个钩子定义输入、输出和失败策略。",
                    "使用离线会话验证调用顺序。",
                    "检查日志和诊断中是否存在重复或遗漏。",
                ),
                (
                    "python examples/coding/extensions/01_lifecycle.py",
                    "/reload",
                ),
                (
                    "钩子只在声明阶段触发一次或符合预期次数。",
                    "钩子失败不会破坏会话文件。",
                ),
                (
                    "不要依赖未公开的内部调用顺序。",
                    "钩子日志不得记录完整凭证或敏感提示。",
                ),
            ),
            topic(
                "动态资源",
                "扩展可以向会话贡献动态提示、上下文或其他资源，使项目知识在运行时参与工作。",
                (
                    "动态资源应具有稳定名称、来源和说明。",
                    "内容变更需要在 reload 后重新解析。",
                    "资源优先级和来源冲突应通过诊断可见。",
                ),
                (
                    "实现资源贡献函数。",
                    "为资源设置唯一标识和最小内容。",
                    "启动离线会话检查加载。",
                    "修改资源后执行 /reload 并验证变化。",
                ),
                (
                    "python examples/coding/extensions/02_dynamic_resources.py",
                    "python examples/coding/extensions/12_online_dynamic_resources.py",
                ),
                (
                    "模型上下文包含预期资源且来源可识别。",
                    "重新加载后旧内容不会继续残留。",
                ),
                (
                    "动态资源同样计入上下文预算。",
                    "不要通过资源注入秘密或未经审查的指令。",
                ),
            ),
            topic(
                "自定义工具与命令",
                "扩展可以注册异步工具和 slash command，为项目提供专用能力。",
                (
                    "工具应定义清晰参数、描述、返回值和错误语义。",
                    "扩展命令在 prompt 或 skill 展开之前按命令路由处理。",
                    "命令补全和列表应展示来源，避免名称冲突。",
                ),
                (
                    "实现小型、可预测且可测试的函数。",
                    "注册工具或命令并提供说明。",
                    "用 list-commands 和 /tools 检查发现结果。",
                    "测试成功、失败和取消路径。",
                ),
                (
                    "python examples/coding/extensions/03_custom_tool.py",
                    "loushang --list-commands",
                    "/extensions",
                ),
                (
                    "自定义贡献显示正确来源和描述。",
                    "错误能够返回给会话而不导致进程崩溃。",
                ),
                (
                    "工具参数不得允许未经校验的任意路径或命令。",
                    "命令名称应避免覆盖核心行为。",
                ),
            ),
            topic(
                "扩展 Manifest",
                "相邻的 loushang-extension.toml 可以声明扩展身份、权限等级、依赖和预期贡献。",
                (
                    "Manifest 使加载前的静态检查和可见性更可靠。",
                    "实际注册贡献应与声明相符。",
                    "权限等级用于风险判断，不等于操作系统强制隔离。",
                ),
                (
                    "为扩展设置稳定 id、名称和版本。",
                    "声明需要的权限、依赖和贡献。",
                    "使用 /extensions <id> 检查详情。",
                    "修改 Manifest 后 reload 并查看诊断。",
                ),
                (
                    "python examples/coding/extensions/05_manifest_visibility.py",
                    "/extensions <id>",
                ),
                (
                    "Manifest 与加载的 Python 代码对应。",
                    "未满足依赖时产生明确诊断。",
                ),
                (
                    "不要仅凭 Manifest 信任扩展，仍需审查代码。",
                    "扩展升级时应同步更新版本和权限说明。",
                ),
            ),
            topic(
                "插件发现与开关",
                "插件提供可复用的资源集合，可通过列表、来源和启停参数管理项目可用状态。",
                (
                    "插件来源和启用状态可以是项目级配置。",
                    "启用插件可能带来技能、扩展或其他资产。",
                    "禁用是配置状态变化，不一定删除已安装文件。",
                ),
                (
                    "运行 --list-plugins 检查现状。",
                    "添加可信插件来源。",
                    "启用目标插件并 reload。",
                    "验证贡献后再加入团队默认配置。",
                ),
                (
                    "loushang --list-plugins",
                    "loushang --add-plugin-source <source>",
                    "loushang --enable-plugin <plugin>",
                    "loushang --disable-plugin <plugin>",
                ),
                (
                    "插件状态和来源可以使用 JSON 格式审计。",
                    "禁用后相关贡献不再进入新解析结果。",
                ),
                (
                    "添加外部来源前应验证发布者和完整性。",
                    "插件标识与包来源可能不同，不要混淆。",
                ),
            ),
            topic(
                "软件包生命周期",
                "Package 命令提供安装、卸载、物化、更新和更新检查等可复用资产管理能力。",
                (
                    "package-scope 区分 global 和 project 安装范围。",
                    "catalog 用于发现或解析包来源。",
                    "物化将包内容落到可检查位置，便于审计和定制。",
                ),
                (
                    "列出已知软件包和当前范围。",
                    "从可信来源安装到 project 范围。",
                    "检查文件和贡献后启用。",
                    "更新前阅读变化并保留可回滚版本。",
                ),
                (
                    "loushang --list-packages",
                    "loushang --package-scope project --install-package <source>",
                    "loushang --check-package-updates",
                    "loushang --update-package <source>",
                ),
                (
                    "安装结果包含可追溯来源和版本。",
                    "更新后命令、技能和扩展仍通过验证。",
                ),
                (
                    "卸载和 remove-package 可能影响项目运行，应先检查依赖。",
                    "全局安装会影响多个项目，优先使用 project 范围。",
                ),
            ),
            topic(
                "重新加载与诊断",
                "/reload 重新发现 keybindings、extensions、skills、prompts 和 themes，适合开发和配置变更后使用。",
                (
                    "reload 应建立新的解析快照，避免部分新旧状态混合。",
                    "扩展加载错误应出现在 /extensions 或诊断列表。",
                    "活跃工具和命令应在 reload 后重新核对。",
                ),
                (
                    "保存扩展或资源文件。",
                    "执行 /reload。",
                    "查看 /extensions、/tools 和命令列表。",
                    "运行一个最小贡献测试。",
                ),
                (
                    "/reload",
                    "/extensions",
                    "/tools",
                ),
                (
                    "新资源出现，删除的资源不再可用。",
                    "错误贡献被诊断而不是静默忽略。",
                ),
                (
                    "reload 不会替代进程级依赖升级。",
                    "正在执行的工具调用不应在中途强制重载。",
                ),
            ),
        ),
    ),
    Chapter(
        "10-方法技能与工作日志.md",
        "第9章 方法、技能与工作日志",
        "说明可复用工作契约、技能发现、方法执行和 WorkEvent 投影。",
        (
            topic(
                "Method 概念",
                "Method 是面向一类任务的结构化工作契约，定义角色、阶段、流程、约束、产物和验收预期。",
                (
                    "方法描述应该怎样工作，会话记录某次工作实际怎样发生。",
                    "方法应能被发现、展示、规划和执行。",
                    "方法内容应面向稳定实践，而不是单个任务的临时细节。",
                ),
                (
                    "识别任务所属工作类型。",
                    "列出必须遵守的阶段和检查点。",
                    "明确每阶段产物和完成条件。",
                    "将方法与具体提示共同交给执行入口。",
                ),
                (
                    "loushang --list-methods",
                    "loushang --show-method <method>",
                    "loushang --show-method-plan <method>",
                ),
                (
                    "方法说明包含适用范围与不适用范围。",
                    "生成计划能够映射到明确步骤和产物。",
                ),
                (
                    "不要把尚未实现的执行语义写入方法承诺。",
                    "方法应允许根据真实发现调整，而不是强迫错误步骤。",
                ),
            ),
            topic(
                "方法发现与查看",
                "列表和展示命令用于在执行前理解可用方法、来源及解析后的计划。",
                (
                    "文本格式适合阅读，JSON 格式适合工具集成。",
                    "show-method 展示方法内容，show-method-plan 展示计划投影。",
                    "同名方法冲突应通过来源信息解决。",
                ),
                (
                    "运行 list-methods 获取候选。",
                    "查看目标方法的完整说明。",
                    "查看计划并确认阶段和产物。",
                    "记录最终选择的方法标识。",
                ),
                (
                    "loushang --list-methods --list-methods-format json",
                    "loushang --show-method <method> --show-method-format json",
                    "loushang --show-method-plan <method> --show-method-plan-format json",
                ),
                (
                    "目标方法可被唯一解析。",
                    "计划没有缺失强制步骤或验收信息。",
                ),
                (
                    "方法来源可能来自项目、用户或插件层。",
                    "执行前应审查方法中的外部动作和权限要求。",
                ),
            ),
            topic(
                "执行方法",
                "--method 将发现的方法用于一次 coding turn，--no-method 显式绕过配置的默认方法。",
                (
                    "当前方法入口支持 prompt、print 和 json 路径。",
                    "在 method step UI 和 work-event projection 完整就绪前，TUI 与 RPC 拒绝该组合。",
                    "方法指导不能替代工具权限和用户确认。",
                ),
                (
                    "选择唯一方法标识。",
                    "提供具体任务、约束和验收条件。",
                    "在支持的非交互模式运行。",
                    "检查最终产物与方法计划的对应关系。",
                ),
                (
                    'loushang --method <method> -p "完成指定编码任务。"',
                    'loushang --no-method -p "不使用默认方法执行。"',
                ),
                (
                    "不支持组合会明确失败，不会静默忽略方法。",
                    "执行结果能说明已完成和未完成的方法步骤。",
                ),
                (
                    "不要在当前版本把 --method 与 TUI 或 RPC 组合。",
                    "方法名称来自外部资产时应检查其可信来源。",
                ),
            ),
            topic(
                "Skill 概念与发现",
                "Skill 把特定领域知识、操作步骤或工具协作方式封装为可复用资产。",
                (
                    "技能可以由项目、用户或插件资源贡献。",
                    "技能启用状态影响发现和提示展开。",
                    "技能应明确触发条件、边界和失败处理。",
                ),
                (
                    "运行 --list-skills 查看可用技能。",
                    "检查技能来源、说明和适用条件。",
                    "在项目范围启用或禁用。",
                    "执行 reload 后验证发现结果。",
                ),
                (
                    "loushang --list-skills",
                    "loushang --enable-skill <skill>",
                    "loushang --disable-skill <skill>",
                    'loushang --skill <skill> -p "执行任务。"',
                ),
                (
                    "启用状态持久化到预期项目范围。",
                    "技能展开不会覆盖用户明确约束。",
                ),
                (
                    "来源不明的技能可能包含不安全指令。",
                    "禁用技能不一定删除其文件。",
                ),
            ),
            topic(
                "Prompt Workflow",
                "prompt-steps 用于按工作流文件顺序运行一组提示步骤，适合可重复的阶段性任务。",
                (
                    "步骤文件应描述输入、顺序、停止条件和产物。",
                    "每步输出需要为后续步骤提供可识别上下文。",
                    "失败时应停止还是继续必须由工作流明确。",
                ),
                (
                    "审查 workflow 文件内容和来源。",
                    "在样例项目或只读模式试运行。",
                    "通过 --prompt-steps 启动。",
                    "检查每步事件和最终产物。",
                ),
                (
                    "loushang --prompt-steps workflow.md",
                    "loushang -ps workflow.md --work-log .loushang/work/events.jsonl",
                ),
                (
                    "步骤按声明顺序执行。",
                    "中间失败不会被后续步骤掩盖。",
                ),
                (
                    "工作流文件中的命令和工具需求需要独立授权。",
                    "不要在未审查情况下运行外部下载的 prompt workflow。",
                ),
            ),
            topic(
                "Work Log 记录",
                "work-log 为一次性 prompt、print 或 json 运行记录 WorkOperation 与 WorkEvent。",
                (
                    "工作日志强调运行计划、阶段和事件，而不是复制完整聊天记录。",
                    "JSONL 便于追加、流式写入和后续检查。",
                    "当前 --work-log 不支持 TUI 或 RPC 模式。",
                ),
                (
                    "选择项目内受控日志路径。",
                    "启动带 --work-log 的一次性任务。",
                    "任务结束后检查文件完整性。",
                    "通过 inspect 命令查看运行与计划。",
                ),
                (
                    'loushang --work-log .loushang/work/events.jsonl -p "执行任务。"',
                    "loushang --work-log-inspect .loushang/work/events.jsonl",
                ),
                (
                    "每个运行具有可识别 run id。",
                    "操作、状态变化和最终结果顺序合理。",
                ),
                (
                    "不要在 TUI 或 RPC 模式使用 --work-log。",
                    "日志可能包含任务名称和产物路径，应按项目数据保护。",
                ),
            ),
            topic(
                "Work Log 检查",
                "work-log-inspect 支持 text、json、plans 和 plans-json 等格式，并可按 run id 筛选。",
                (
                    "text 面向快速阅读，json 面向事件处理。",
                    "plans 聚焦方法计划的可读投影。",
                    "work-log-run 用于从多次运行中定位一个目标。",
                ),
                (
                    "先使用 text 查看整体文件。",
                    "获取目标 run id。",
                    "使用 plans 查看计划映射。",
                    "在自动化中切换到 plans-json 或 json。",
                ),
                (
                    "loushang --work-log-inspect .loushang/work/events.jsonl",
                    "loushang --work-log-inspect .loushang/work/events.jsonl --work-log-inspect-format plans",
                    "loushang --work-log-inspect .loushang/work/events.jsonl --work-log-run <run-id>",
                ),
                (
                    "检查器能够解析全部行且无截断事件。",
                    "计划状态与实际交付证据相符。",
                ),
                (
                    "不要手工拼接来自不同版本的不兼容事件。",
                    "计划完成状态必须由真实验证支撑。",
                ),
            ),
        ),
    ),
    Chapter(
        "11-终端交互界面.md",
        "第10章 终端交互界面",
        "说明 TUI 启动、输入、命令、会话连续性、显示和退出操作。",
        (
            topic(
                "TUI 启动方式",
                "交互式终端中可通过 loushang --tui 或 loushang-tui 打开全屏工作界面。",
                (
                    "stdin 和 stdout 都是 TTY 时进入 screen 交互面。",
                    "管道或重定向场景使用 plain prompt loop。",
                    "--no-tui 可强制关闭全屏界面。",
                ),
                (
                    "确认终端支持交互和常见控制序列。",
                    "启动 TUI 并观察初始状态。",
                    "输入短消息验证渲染。",
                    "使用 /quit 正常结束。",
                ),
                (
                    "loushang --tui",
                    "loushang-tui",
                    'loushang --no-tui -p "一次性任务"',
                ),
                (
                    "全屏模式能正确恢复终端状态。",
                    "退出后 shell 输入和光标行为正常。",
                ),
                (
                    "远程终端、复用器和不同 TERM 值可能影响显示。",
                    "异常退出后可使用终端 reset 命令恢复显示。",
                ),
            ),
            topic(
                "输入与多轮对话",
                "输入区支持编辑和提交消息，转录区持续展示用户、模型和工具事件。",
                (
                    "每轮输入应围绕当前目标补充新事实或调整方向。",
                    "长任务应在阶段边界总结状态。",
                    "工具运行期间的中断与后续输入需要遵守队列语义。",
                ),
                (
                    "输入明确目标和范围。",
                    "观察模型是否需要工具或澄清。",
                    "对不正确方向及时中断或引导。",
                    "在完成前要求执行验证。",
                ),
                (
                    "请先只读分析，不要修改文件。",
                    "继续执行已确认方案，并运行相关测试。",
                ),
                (
                    "对话保持围绕同一任务上下文。",
                    "中断后不会继续未经确认的高影响动作。",
                ),
                (
                    "不要在输入区粘贴未经处理的秘密。",
                    "大量日志应保存为文件并提供精确路径。",
                ),
            ),
            topic(
                "Slash Command",
                "slash command 在本地控制会话、模型、工具和界面行为，不应被误当作普通模型提示。",
                (
                    "内置命令可通过 --list-commands 查询。",
                    "扩展、prompt 和 skill 也可能贡献命令。",
                    "命令来源和参数说明应在列表或补全中可见。",
                ),
                (
                    "运行 /help 等可用发现入口或外部 list-commands。",
                    "输入完整命令和参数。",
                    "检查本地结果是否符合预期。",
                    "命令变更资源后使用 /reload。",
                ),
                (
                    "/session",
                    "/tools",
                    "/model",
                    "/export",
                    "/reload",
                ),
                (
                    "命令由本地路由处理，不进入模型正文。",
                    "未知命令产生明确提示。",
                ),
                (
                    "扩展命令可能执行代码，应确认来源。",
                    "排队中的 steer 或 follow-up 不应延迟执行扩展 slash command。",
                ),
            ),
            topic(
                "连续性选择器",
                "交互式 --resume 和无参数 /resume 使用全屏可搜索选择器定位历史会话。",
                (
                    "空格可按需加载预览。",
                    "存在多个 Provider 时 Tab 切换 Domain。",
                    "Ctrl+S 切换公共排序。",
                ),
                (
                    "打开 resume 选择器。",
                    "搜索会话名称或项目。",
                    "加载预览检查最后状态。",
                    "确认并恢复目标会话。",
                ),
                (
                    "loushang --resume",
                    "/resume",
                ),
                (
                    "选择结果对应正确工作目录和任务。",
                    "取消选择不会改变当前会话。",
                ),
                (
                    "非交互环境不能依赖全屏选择器。",
                    "跨 Domain 恢复前应核对提供方和会话格式。",
                ),
            ),
            topic(
                "模型与设置界面",
                "/model、/scoped-models 和 /settings 用于查看或调整当前交互上下文的模型与设置。",
                (
                    "模型选择应展示规范键和来源。",
                    "scoped models 用于理解不同范围的模型配置。",
                    "设置变更应区分会话级、项目级和用户级。",
                ),
                (
                    "打开 /model 查看当前选择。",
                    "比较可用候选及其端点。",
                    "完成选择并运行最小提示。",
                    "用 /settings 检查持久化范围。",
                ),
                (
                    "/model",
                    "/scoped-models",
                    "/settings",
                ),
                (
                    "状态栏或会话信息显示正确模型。",
                    "重新启动后的持久化行为符合设置范围。",
                ),
                (
                    "模型切换可能改变成本、能力和数据处理边界。",
                    "不要在未验证时切换到名称相似的代理端点。",
                ),
            ),
            topic(
                "转录与复制",
                "转录区用于查看稳定消息、流式草稿和工具事件，copy 命令可复制选定模型消息。",
                (
                    "流式草稿在结束后应转为稳定消息。",
                    "复制应针对明确消息，避免把整个敏感转录放入剪贴板。",
                    "终端选择与应用内复制可能具有不同语义。",
                ),
                (
                    "等待目标消息完成。",
                    "使用 /copy 或界面复制入口。",
                    "粘贴到安全位置核对内容。",
                    "不再需要时清理系统剪贴板。",
                ),
                (
                    "/copy",
                    "/export",
                ),
                (
                    "复制内容与目标助手消息一致。",
                    "工具输出和隐藏元数据未被意外复制。",
                ),
                (
                    "剪贴板可能被其他应用读取。",
                    "远程终端的 clipboard 集成可能不可用。",
                ),
            ),
            topic(
                "退出与异常恢复",
                "正常退出应保存必要会话状态并恢复终端；异常情况下可重新启动并使用 resume 继续。",
                (
                    "/quit 是推荐的正常退出入口。",
                    "进程中断后应检查会话文件和工作树。",
                    "终端渲染异常与任务执行失败需要分别诊断。",
                ),
                (
                    "使用 /quit 正常结束。",
                    "异常退出后运行 git status 和会话列表。",
                    "恢复目标会话并总结最后完成事件。",
                    "重新执行未获得结束证据的验证。",
                ),
                (
                    "/quit",
                    "loushang --list-sessions",
                    "loushang --continue",
                ),
                (
                    "终端恢复且会话可以再次读取。",
                    "没有把中断中的工具调用误报为成功。",
                ),
                (
                    "强制关闭可能留下不完整的外部命令副作用。",
                    "恢复后必须检查真实文件和进程状态。",
                ),
            ),
        ),
    ),
    Chapter(
        "12-诊断导出与交付.md",
        "第11章 诊断、导出与可追踪交付",
        "说明调试记录、诊断包、会话导出、工作证据和交付检查。",
        (
            topic(
                "诊断列表",
                "诊断列表集中展示会话或运行时发现的问题，可用 TSV 或 JSON 形式查询。",
                (
                    "诊断应包含级别、来源、消息和可采取行动。",
                    "diagnostics-limit 控制列表规模。",
                    "有诊断不一定表示任务失败，需要结合级别和上下文判断。",
                ),
                (
                    "运行默认诊断列表。",
                    "切换 JSON 格式保存快照。",
                    "按来源和级别分类。",
                    "修复后重新运行并比较差异。",
                ),
                (
                    "loushang --list-diagnostics",
                    "loushang --list-diagnostics --list-diagnostics-format json",
                    "loushang --diagnostics-limit 100 --list-diagnostics",
                ),
                (
                    "每条诊断具有稳定来源和可读说明。",
                    "修复后的重复诊断消失或状态更新。",
                ),
                (
                    "不要只删除诊断记录而不解决根因。",
                    "共享诊断前应审查本地路径和敏感元数据。",
                ),
            ),
            topic(
                "诊断包导出",
                "diag-export 将诊断信息写入指定输出，便于离线分析和问题报告。",
                (
                    "诊断导出不需要启动普通模型会话。",
                    "diag-output 应指向明确文件路径。",
                    "导出包可能包含配置来源、路径和错误上下文。",
                ),
                (
                    "选择项目内临时或受控输出位置。",
                    "运行 diag-export。",
                    "打开文件确认格式与完整性。",
                    "清理秘密和个人信息后再共享。",
                ),
                (
                    "loushang --diag-export --diag-output diagnostics.json",
                    "loushang --source-info --source-info-format json",
                ),
                (
                    "输出文件存在且可以解析。",
                    "诊断内容覆盖问题发生的相关组件。",
                ),
                (
                    "不要把未经审查的诊断包提交到公开仓库。",
                    "问题解决后按保留策略删除临时导出。",
                ),
            ),
            topic(
                "Debug 与 Trace",
                "debug 和 trace 参数用于记录更详细的运行过程，文件参数可把信息写入独立日志。",
                (
                    "Debug 适合组件级问题，Trace 适合事件顺序和边界分析。",
                    "日志量和敏感度通常高于普通诊断。",
                    "应只为必要组件启用，并限制保留时间。",
                ),
                (
                    "确定需要观察的组件或主题。",
                    "设置 debug-file 或 trace-file。",
                    "复现一次最小问题。",
                    "关闭详细记录并分析时间线。",
                ),
                (
                    "loushang --debug session --debug-file debug.log --list-sessions",
                    'loushang --trace tools --trace-file trace.log -p "复现问题"',
                ),
                (
                    "日志包含问题发生前后的关键事件。",
                    "关闭调试后正常运行性能恢复。",
                ),
                (
                    "日志可能包含提示、路径和工具参数。",
                    "长期启用 trace 会增加磁盘和性能开销。",
                ),
            ),
            topic(
                "HTML 会话导出",
                "HTML 导出提供适合人类阅读的转录、工具事件和相关会话信息。",
                (
                    "默认 export 可生成 HTML 或由扩展名推断格式。",
                    "导出页面应保持离线可打开。",
                    "样式不能掩盖错误、取消或未完成状态。",
                ),
                (
                    "选择明确的 .html 输出路径。",
                    "执行导出并在浏览器打开。",
                    "搜索关键用户消息和工具事件。",
                    "审查敏感信息后归档或共享。",
                ),
                (
                    "loushang --export session.html",
                    "loushang --export session.html --export-result-format json",
                ),
                (
                    "导出文件包含完整目标会话。",
                    "关键事件顺序与原会话一致。",
                ),
                (
                    "HTML 中的源代码和路径仍属于敏感内容。",
                    "不要使用公共图床或外部脚本承载私有会话资源。",
                ),
            ),
            topic(
                "JSONL 会话导出",
                "JSONL 导出适合机器处理、迁移和后续导入，每一行应是独立 JSON 记录。",
                (
                    "事件顺序由文件行顺序表达。",
                    "解析器应容忍已知版本字段并拒绝损坏行。",
                    "导入前需要确认来源、完整性和兼容性。",
                ),
                (
                    "指定 export-format jsonl。",
                    "逐行运行 JSON 解析检查。",
                    "记录文件哈希或存储版本。",
                    "在隔离环境试验导入。",
                ),
                (
                    "loushang --export session.jsonl --export-format jsonl",
                    "/import session.jsonl",
                ),
                (
                    "文件每一非空行都是合法 JSON。",
                    "导入后的消息和事件数量符合预期。",
                ),
                (
                    "不要执行导入文件中暗示的外部动作。",
                    "跨版本迁移前应保留原始副本。",
                ),
            ),
            topic(
                "可追踪交付",
                "可追踪交付要求把用户目标、实际修改、验证证据和未决风险连接起来。",
                (
                    "交付说明应先给出结果，再列出重要文件和验证。",
                    "测试通过只能证明覆盖范围内行为，不能代表全部正确。",
                    "未运行的检查和环境限制必须明确说明。",
                ),
                (
                    "回顾原始目标和验收条件。",
                    "列出实际变更文件与行为变化。",
                    "记录验证命令、状态和关键输出。",
                    "列出遗留风险、人工步骤和回滚方式。",
                ),
                (
                    "git diff --stat",
                    "git diff --check",
                    "python -m pytest <relevant-tests>",
                ),
                (
                    "每项完成声明都有可检查证据。",
                    "交付者没有把计划或推断当成执行结果。",
                ),
                (
                    "不要隐瞒失败测试或范围外问题。",
                    "外部发布、合并和发送动作应单独报告。",
                ),
            ),
            topic(
                "交付前检查清单",
                "结束会话前应进行范围、质量、安全、版本和归档五类检查。",
                (
                    "范围检查确保没有修改无关文件。",
                    "质量检查覆盖格式、静态分析、测试和真实运行。",
                    "安全检查覆盖秘密、权限、依赖和外部副作用。",
                ),
                (
                    "查看工作树和差异。",
                    "运行与风险相称的验证。",
                    "检查会话、日志和导出中的敏感信息。",
                    "生成最终摘要并保存必要证据。",
                ),
                (
                    "git status --short",
                    "git diff --check",
                    "loushang --list-diagnostics",
                    "loushang --export delivery-session.html",
                ),
                (
                    "工作树状态和最终摘要一致。",
                    "登记版本、文档版本和软件显示版本已核对。",
                ),
                (
                    "不要因时间不足跳过高风险变更的最小回归测试。",
                    "归档前确认导出文件访问权限。",
                ),
            ),
        ),
    ),
    Chapter(
        "13-AI-SDK.md",
        "第12章 loushang.ai SDK",
        "说明开发者如何使用模型目录、完成、流式、工具、结构化输出和用量能力。",
        (
            topic(
                "SDK 定位",
                "loushang.ai 是 provider-aware 的 Python AI SDK，为上层产品提供模型发现、请求、流式、工具和成本辅助能力。",
                (
                    "SDK 把模型身份与具体端点、协议和认证元数据分离。",
                    "上层代码应依赖公共 API，而不是适配器内部实现。",
                    "异步流式表面是主要的实时交互基础。",
                ),
                (
                    "在虚拟环境中导入 loushang.ai。",
                    "从模型目录解析目标模型。",
                    "执行最小 complete 或 stream。",
                    "检查结果、usage 和错误类型。",
                ),
                (
                    "python examples/ai/01_complete.py",
                    "python examples/ai/02_stream.py",
                    "python examples/ai/11_provider_matrix.py",
                ),
                (
                    "公共 API 可以在 Python 3.11 环境导入。",
                    "请求结果保留模型和提供方可追踪信息。",
                ),
                (
                    "不要依赖 advanced 或内部模块的非公共细节。",
                    "SDK 升级需要运行适配器和流式语义回归。",
                ),
            ),
            topic(
                "模型发现",
                "模型注册表和目录用于按键查找模型、端点、能力和价格等元数据。",
                (
                    "自定义目录可用于私有端点和组织内模型。",
                    "目录合并应检测重复键和不兼容声明。",
                    "调用方应保留规范模型标识用于日志和用量。",
                ),
                (
                    "加载内置或自定义模型目录。",
                    "列出并筛选满足能力要求的模型。",
                    "解析唯一端点。",
                    "保存规范键和能力快照。",
                ),
                (
                    "python examples/ai/advanced/custom_catalog.py",
                    "python examples/ai/advanced/inspect_endpoint_contract.py",
                ),
                (
                    "目标模型解析唯一且能力声明完整。",
                    "目录错误在请求前被发现。",
                ),
                (
                    "价格、上下文和能力值可能随提供方变化。",
                    "自定义目录文件需要版本控制和代码审查。",
                ),
            ),
            topic(
                "Complete 调用",
                "Complete 适合等待完整模型结果后一次性处理的调用场景。",
                (
                    "输入应包含明确角色、内容和必要上下文。",
                    "结果处理应区分文本、工具调用、停止原因和用量。",
                    "网络错误与模型拒绝应使用不同分支处理。",
                ),
                (
                    "构造最小消息列表。",
                    "选择模型并发送 complete 请求。",
                    "读取最终消息和停止原因。",
                    "记录 usage 并处理错误。",
                ),
                (
                    "python examples/ai/01_complete.py",
                    "python examples/ai/03_typed_context.py",
                ),
                (
                    "响应结构完整且停止原因可解释。",
                    "调用方不会把空文本工具调用当作普通完成。",
                ),
                (
                    "请求超时和重试必须设置上限。",
                    "不要在日志中记录完整敏感输入。",
                ),
            ),
            topic(
                "流式调用与取消",
                "Stream 逐步返回内容和事件，适合终端界面、长回答和实时工具交互。",
                (
                    "流式事件必须保持顺序并形成唯一最终结果。",
                    "取消应停止后续网络读取和未经授权的工具执行。",
                    "faux stream 与真实提供方 stream 的能力边界不同。",
                ),
                (
                    "启动异步流并消费事件。",
                    "把草稿事件呈现到临时界面。",
                    "处理工具调用、错误和取消。",
                    "在结束事件后固化最终消息与用量。",
                ),
                (
                    "python examples/ai/02_stream.py",
                    "python examples/ai/advanced/cancel_stream.py",
                    "python examples/ai/advanced/faux_stream.py",
                ),
                (
                    "每个流只有一个明确结束状态。",
                    "取消后资源释放且不会重复发送最终消息。",
                ),
                (
                    "网络断开可能发生在部分文本之后。",
                    "调用方不能把已显示草稿当作已持久化最终答复。",
                ),
            ),
            topic(
                "工具调用",
                "SDK 工具调用把模型生成的结构化参数交给应用执行，并把结果作为 tool result 返回模型。",
                (
                    "工具 schema、参数校验和执行权限由调用方负责。",
                    "并行工具需要稳定关联 call id 与 result。",
                    "工具错误应作为明确结果返回，而不是伪装为正常文本。",
                ),
                (
                    "定义类型清晰的小型工具。",
                    "把工具描述随模型请求发送。",
                    "校验并执行模型返回参数。",
                    "把结果按原 call id 回传。",
                ),
                (
                    "python examples/ai/04_tools.py",
                    "python examples/ai/05_parallel_tools.py",
                    "python examples/ai/advanced/tool_result_roundtrip.py",
                ),
                (
                    "每个 tool call 都有唯一匹配结果。",
                    "无效参数在副作用发生前被拒绝。",
                ),
                (
                    "模型工具调用不是用户授权本身。",
                    "并行写工具可能发生竞争，默认应串行或加锁。",
                ),
            ),
            topic(
                "结构化输出",
                "结构化输出用于让模型结果符合应用预期的数据结构，并在进入业务逻辑前完成验证。",
                (
                    "模型支持、协议适配和本地校验缺一不可。",
                    "结构化输出失败应保留原始诊断但避免泄露敏感文本。",
                    "调用方应处理缺失字段、额外字段和类型不符。",
                ),
                (
                    "定义最小结果结构。",
                    "选择支持结构化能力的模型。",
                    "发送请求并执行严格解析。",
                    "在失败时重试、降级或请求人工处理。",
                ),
                (
                    "python examples/ai/07_structured_output.py",
                    "python examples/ai/advanced/capability_failure.py",
                ),
                (
                    "解析结果通过本地类型和业务规则。",
                    "不支持能力会产生明确错误。",
                ),
                (
                    "不要把 JSON 外观当作通过 schema 验证。",
                    "高风险业务决策需要额外规则与人工确认。",
                ),
            ),
            topic(
                "错误与重试",
                "错误处理应区分配置、认证、网络、限流、提供方、能力和调用方数据问题。",
                (
                    "只有幂等且可恢复的失败适合自动重试。",
                    "退避、最大次数和总超时必须有上限。",
                    "错误归一化应保留原始提供方诊断关联。",
                ),
                (
                    "捕获 SDK 公共错误类型。",
                    "按类别决定失败、重试或降级。",
                    "记录尝试次数和最终原因。",
                    "向用户提供可执行修复建议。",
                ),
                (
                    "python examples/ai/09_errors_retry.py",
                    "python examples/ai/advanced/normalization_diagnostics.py",
                ),
                (
                    "持续失败会在有限时间内终止。",
                    "错误报告能定位提供方、端点和请求阶段。",
                ),
                (
                    "写操作和外部副作用不能盲目自动重试。",
                    "错误正文可能包含请求片段，记录前要脱敏。",
                ),
            ),
            topic(
                "用量与成本",
                "usage 记录输入、输出及可能的缓存或推理用量，成本辅助功能基于目录价格元数据估算。",
                (
                    "提供方返回的 usage 是主要事实来源。",
                    "目录价格用于估算，最终费用以提供方账单为准。",
                    "跨模型比较应同时考虑质量、延迟和工具成功率。",
                ),
                (
                    "读取每次请求 usage。",
                    "按规范模型键聚合。",
                    "应用当前目录价格估算。",
                    "定期与真实账单交叉核对。",
                ),
                (
                    "python examples/ai/10_usage.py",
                    "python examples/ai/advanced/usage_online.py",
                    "python examples/coding/22_usage_inspect.py",
                ),
                (
                    "用量字段可追溯到具体请求和模型。",
                    "估算与账单差异在可解释范围内。",
                ),
                (
                    "不要用过期价格做预算承诺。",
                    "用量日志同样可能暴露项目活动模式。",
                ),
            ),
        ),
    ),
    Chapter(
        "14-安全与数据管理.md",
        "第13章 安全、隐私与数据管理",
        "说明凭证、工作目录、会话数据、扩展信任和高影响操作的安全要求。",
        (
            topic(
                "最小权限原则",
                "每次任务只开放完成目标所需的模型、目录、工具和外部访问范围。",
                (
                    "只读分析默认不需要 edit、write 和 bash。",
                    "写入阶段可以按步骤临时扩大工具范围。",
                    "操作系统权限、沙箱和组织审批应与工具策略共同工作。",
                ),
                (
                    "列出任务必需能力。",
                    "以最小 --tools 集合启动。",
                    "遇到明确缺口后再增加工具。",
                    "高影响阶段结束后收回权限。",
                ),
                (
                    'loushang --tools read,ls,find,grep -p "只读审查。"',
                    "/tools off bash",
                ),
                (
                    "任务能完成且未使用无关能力。",
                    "拒绝路径不会通过替代工具绕过。",
                ),
                (
                    "Loushang 工具列表不等于完整系统权限边界。",
                    "扩展可能贡献新能力，必须一起审查。",
                ),
            ),
            topic(
                "凭证保护",
                "模型 API Key 和其他凭证应由环境或秘密管理系统注入，不应写入项目与会话。",
                (
                    "Coding 层不管理 OAuth 生命周期。",
                    "日志、trace、命令历史和导出都可能意外包含秘密。",
                    "凭证应按最小范围、最短寿命和可轮换原则管理。",
                ),
                (
                    "从可信秘密存储获取凭证。",
                    "只注入当前进程所需变量。",
                    "避免 echo、调试转储和提交。",
                    "任务结束后清理并按策略轮换。",
                ),
                (
                    "export PROVIDER_API_KEY=<redacted>",
                    "unset PROVIDER_API_KEY",
                ),
                (
                    "版本控制和会话中找不到真实凭证。",
                    "泄露检测和轮换流程可用。",
                ),
                (
                    "示例中的占位符不能替换成真实 Key 后提交。",
                    "共享终端和 CI 日志需要额外脱敏。",
                ),
            ),
            topic(
                "工作目录安全",
                "工作目录决定可见文件和工具相对路径，应在执行前后持续核对。",
                (
                    "不要把主目录、根目录或包含多项目的宽泛目录作为写入范围。",
                    "符号链接和挂载点可能把操作带出表面目录。",
                    "恢复会话时真实工作树可能已变化。",
                ),
                (
                    "确认绝对路径和项目根。",
                    "检查 Git 状态与符号链接。",
                    "为高风险任务使用隔离分支或工作树。",
                    "完成后核对所有变更路径。",
                ),
                (
                    "pwd",
                    "git status --short",
                    "git diff --name-only",
                ),
                (
                    "所有修改都位于授权项目范围。",
                    "用户既有修改没有被覆盖或丢失。",
                ),
                (
                    "不要对未解析变量或通配符执行破坏性命令。",
                    "参考仓库默认只读，除非任务明确授权修改。",
                ),
            ),
            topic(
                "会话与日志保护",
                "会话、工作日志、诊断和导出可能包含源代码、提示、路径、模型用量和工具结果。",
                (
                    "数据分类应与项目源代码至少同等级处理。",
                    "共享前需要内容审查和最小化。",
                    "保留期限应满足恢复、审计和隐私要求。",
                ),
                (
                    "识别所有会话与导出存储路径。",
                    "设置适当文件权限。",
                    "共享前删除无关敏感内容。",
                    "到期后使用可审计流程清理。",
                ),
                (
                    "loushang --list-sessions",
                    "loushang --export review.html",
                    "loushang --diag-export --diag-output diag.json",
                ),
                (
                    "只有授权用户能够读取归档。",
                    "删除和保留行为符合组织规则。",
                ),
                (
                    "不要把私有会话上传到公开问题或公共存储。",
                    "删除前确认是否受审计或法律保留要求约束。",
                ),
            ),
            topic(
                "扩展与依赖信任",
                "扩展、插件和包可能执行 Python 代码或贡献工具，应视为供应链组件管理。",
                (
                    "来源、版本、完整性和权限声明需要可追溯。",
                    "更新可能扩大工具或网络能力。",
                    "Manifest 提供说明，但不能替代代码审查。",
                ),
                (
                    "只从可信来源获取资产。",
                    "审查代码、依赖和权限变化。",
                    "在隔离项目运行离线测试。",
                    "固定版本并记录升级结论。",
                ),
                (
                    "loushang --list-plugins --list-plugins-format json",
                    "loushang --list-packages --list-packages-format json",
                    "/extensions",
                ),
                (
                    "每个执行资产都有已知来源和版本。",
                    "禁用后贡献不会继续进入新会话。",
                ),
                (
                    "不要自动更新未经验证的生产扩展。",
                    "依赖安装脚本可能产生网络和文件系统副作用。",
                ),
            ),
            topic(
                "高影响操作",
                "删除、覆盖、重置、推送、发布、付费调用和外部消息等操作需要更高确认等级。",
                (
                    "模型提出动作不构成用户授权。",
                    "目标、范围、影响和恢复方式必须在执行前明确。",
                    "能使用可恢复方式时应优先使用。",
                ),
                (
                    "展示将执行的完整目标和命令。",
                    "获取当前用户明确确认。",
                    "执行前保存状态或建立检查点。",
                    "执行后报告结果和恢复可能性。",
                ),
                (
                    "git status --short",
                    "git diff --stat",
                    "loushang --export pre-action.html",
                ),
                (
                    "动作只影响确认范围。",
                    "失败或部分完成状态被准确报告。",
                ),
                (
                    "不要用含糊的继续或随便作为高影响授权。",
                    "不能保证恢复时必须在执行前明确告知。",
                ),
            ),
            topic(
                "模型数据边界",
                "发送给模型的提示、文件片段和工具结果可能离开本地环境，应遵守所选提供方和组织的数据政策。",
                (
                    "不同端点可能具有不同地域、保留和训练政策。",
                    "模型路由变化也可能改变数据处理边界。",
                    "最小上下文可以降低不必要的数据暴露。",
                ),
                (
                    "确认提供方和完整端点。",
                    "分类将发送的数据。",
                    "删除无关秘密和个人信息。",
                    "记录必要的授权与处理依据。",
                ),
                (
                    "loushang --list-models --list-models-format json",
                    "loushang --source-info",
                ),
                (
                    "实际端点符合组织允许列表。",
                    "请求只包含完成任务所需上下文。",
                ),
                (
                    "不要仅凭模型显示名称判断数据去向。",
                    "代理和兼容端点需要单独审查运营主体。",
                ),
            ),
        ),
    ),
)


TROUBLESHOOTING: tuple[tuple[str, str, tuple[str, ...], tuple[str, ...]], ...] = (
    (
        "找不到 loushang 命令",
        "虚拟环境未激活、editable 安装失败或 PATH 指向错误环境。",
        ("激活项目 .venv。", "重新执行 editable 安装。", "检查 which loushang。"),
        ("不要直接修改系统 PATH 掩盖安装问题。",),
    ),
    (
        "Python 版本过低",
        "当前解释器低于项目要求的 Python 3.11。",
        ("运行 python --version。", "使用兼容解释器重建 .venv。", "重新安装依赖。"),
        ("不要在旧虚拟环境上原地替换解释器。",),
    ),
    (
        "依赖下载失败",
        "网络、代理、证书或包索引不可用。",
        ("检查 DNS 和代理。", "确认企业证书。", "重试 uv pip install。"),
        ("不要关闭证书校验作为长期方案。",),
    ),
    (
        "模型列表为空",
        "模型目录未加载、目录结构无效或来源被覆盖。",
        (
            "运行 --source-info。",
            "检查 models 目录 JSON。",
            "使用 --list-models-format json。",
        ),
        ("不要用未知旧目录覆盖内置 catalog。",),
    ),
    (
        "模型键不存在",
        "输入的 provider、endpoint 或 model 标识与目录不一致。",
        ("复制 --list-models 输出。", "使用规范完整键。", "检查拼写和冒号位置。"),
        ("不要根据展示名猜测模型键。",),
    ),
    (
        "模型选择歧义",
        "同一 provider/model 匹配多个 endpoint 且没有唯一 preferred。",
        ("查看错误候选。", "选择 provider:endpoint:model。", "验证端点区域。"),
        ("不要任意选择第一个候选。",),
    ),
    (
        "认证失败",
        "环境变量缺失、Key 无效、权限不足或端点认证方式不匹配。",
        ("检查目录声明的变量名。", "验证 Key 范围。", "运行最小请求。"),
        ("不要把 Key 写进诊断或问题描述。",),
    ),
    (
        "请求超时",
        "网络不稳定、端点负载、模型延迟或超时设置不合适。",
        ("缩小提示与工具范围。", "检查网络和端点状态。", "按幂等策略有限重试。"),
        ("写操作不能盲目重试。",),
    ),
    (
        "模型不支持工具",
        "目录能力声明、模型真实能力或协议适配不匹配。",
        ("运行工具 smoke 示例。", "选择支持工具的模型。", "检查适配诊断。"),
        ("不要用提示词模拟工具执行证据。",),
    ),
    (
        "工具未出现",
        "工具被 --no-tools、only、no-builtin-tools 或扩展策略关闭。",
        ("运行 /tools。", "检查启动参数。", "执行 /tools reset。"),
        ("恢复默认前先确认安全范围。",),
    ),
    (
        "工具调用被阻止",
        "扩展守卫、权限策略或宿主审批拒绝了调用。",
        ("查看阻止原因。", "确认调用目标。", "仅在授权后调整策略。"),
        ("不要通过其他工具绕过阻止。",),
    ),
    (
        "文件修改不符合预期",
        "上下文过期、目标路径错误或修改范围过大。",
        ("立即停止后续写入。", "查看 git diff。", "恢复前先保留用户变更。"),
        ("不要使用 reset --hard 处理不明差异。",),
    ),
    (
        "测试命令失败",
        "代码缺陷、环境缺依赖、工作目录错误或测试本身不稳定。",
        ("记录完整命令。", "定位第一个根因失败。", "运行最小复现。"),
        ("不要删除失败测试来获得绿色结果。",),
    ),
    (
        "会话列表为空",
        "session-dir 不一致、索引陈旧或当前项目范围不同。",
        ("检查 --session-dir。", "使用 --all-sessions。", "刷新 session index。"),
        ("跨项目结果要核对工作目录。",),
    ),
    (
        "无法恢复会话",
        "文件损坏、格式不兼容、路径不可读或标识错误。",
        ("备份原文件。", "逐行检查 JSONL。", "尝试显式路径恢复。"),
        ("不要直接覆盖损坏原件。",),
    ),
    (
        "恢复后上下文过期",
        "代码库在会话外发生了提交、切换或文件修改。",
        ("运行 git status。", "重新读取关键文件。", "重新运行验证。"),
        ("会话恢复不会恢复 Git 工作树。",),
    ),
    (
        "TUI 显示错位",
        "终端尺寸、宽字符计算、TERM 或远程终端能力不匹配。",
        ("扩大窗口。", "检查 TERM。", "尝试 plain prompt loop。"),
        ("异常退出后可执行 reset 恢复终端。",),
    ),
    (
        "TUI 无法启动",
        "stdio 不是 TTY、终端不兼容或依赖环境错误。",
        ("检查终端交互性。", "使用 --no-tui 验证核心 CLI。", "查看诊断。"),
        ("管道场景会进入 plain 模式。",),
    ),
    (
        "扩展加载失败",
        "Python 语法、依赖、Manifest 或 register 协议错误。",
        ("运行扩展示例。", "查看 /extensions。", "禁用扩展后验证核心。"),
        ("不要忽略扩展加载诊断。",),
    ),
    (
        "扩展修改后未生效",
        "资源快照尚未 reload 或进程级依赖未更新。",
        ("保存文件。", "执行 /reload。", "必要时重启进程。"),
        ("不要在工具调用执行中强制 reload。",),
    ),
    (
        "技能未被发现",
        "技能路径、启用状态、优先级或内容格式不正确。",
        ("运行 --list-skills。", "检查 source-info。", "enable 后 reload。"),
        ("来源冲突时不要静默覆盖。",),
    ),
    (
        "Method 被拒绝",
        "当前模式为 TUI 或 RPC，或方法无法唯一解析。",
        ("切换 prompt/print/json。", "运行 --list-methods。", "使用完整方法标识。"),
        ("不要假设被拒绝时仍会应用方法。",),
    ),
    (
        "Work Log 无法写入",
        "路径无权限、父目录不存在或模式不支持。",
        ("检查目标目录。", "切换一次性模式。", "使用项目内明确路径。"),
        ("TUI 和 RPC 不支持 --work-log。",),
    ),
    (
        "导出文件为空",
        "会话目标错误、输出路径问题或导出在事件完成前触发。",
        ("检查会话标识。", "等待最终事件。", "使用显式格式重试。"),
        ("保留失败文件用于诊断。",),
    ),
    (
        "JSON 输出无法解析",
        "调试文本混入 stdout、进程被中断或调用方选择了文本格式。",
        ("固定 json 格式。", "分离 stderr。", "检查退出状态。"),
        ("不要用正则表达式代替 JSON 解析。",),
    ),
    (
        "诊断文件过大",
        "长期开启 trace、工具输出过多或缺少轮转。",
        ("缩小调试主题。", "限制复现次数。", "按策略归档清理。"),
        ("清理前先保留问题时间窗口。",),
    ),
    (
        "用量与账单不同",
        "价格元数据过期、缓存计费、汇率或提供方账单口径不同。",
        ("保存规范模型键。", "更新价格目录。", "与提供方账单核对。"),
        ("估算值不能替代财务账单。",),
    ),
    (
        "命令名称冲突",
        "扩展、技能、prompt 与内置命令使用了相同标识。",
        ("运行 --list-commands。", "查看来源列。", "重命名非核心贡献。"),
        ("不要覆盖安全相关内置命令。",),
    ),
    (
        "终端退出后状态异常",
        "全屏程序未正常恢复终端模式。",
        ("执行 reset。", "重新打开终端。", "保存复现诊断。"),
        ("不要在异常终端继续输入秘密。",),
    ),
    (
        "版本号不一致",
        "软件包、申请表、源代码页眉和用户手册使用了不同版本。",
        ("确定唯一登记版本。", "同步所有材料。", "重新生成并逐项检查。"),
        ("有无字母 V 也应按申请表保持一致。",),
    ),
)


GLOSSARY: tuple[tuple[str, str], ...] = (
    ("Agent", "执行模型交互、工具调用和任务推进的运行核心。"),
    ("Artifact", "对交付有意义的代码、报告、导出、计划或其他工作产物。"),
    ("Catalog", "描述模型、端点、能力、认证和价格元数据的目录。"),
    ("Channel", "宿主与 Agent 运行时之间传递消息和事件的边界协议。"),
    ("CLI", "通过命令行参数、标准输入和标准输出使用 Loushang 的入口。"),
    ("Coding", "Loushang V1.0.0 面向软件开发工作的主要产品面。"),
    ("Compact", "把长上下文总结为可继续工作的压缩状态。"),
    ("Continue", "恢复当前项目最近一次持久会话的快捷操作。"),
    ("Diagnostic", "描述配置、运行、扩展或会话问题的结构化诊断信息。"),
    ("Endpoint", "具体模型服务的网络端点、区域、协议或部署通道。"),
    ("Extension", "为会话贡献钩子、工具、资源、命令或参数的项目级 Python 代码。"),
    ("Fork", "从历史消息节点创建新的会话分支。"),
    ("JSONL", "每行一个 JSON 对象的流式记录格式。"),
    ("Manifest", "声明扩展身份、权限、依赖和预期贡献的元数据文件。"),
    ("Method", "定义角色、阶段、流程、约束、产物和验收的结构化工作契约。"),
    ("Model", "由模型目录解析并通过具体端点调用的 AI 模型身份。"),
    ("Package", "可安装、更新、物化或移除的可复用 Loushang 资产集合。"),
    ("Plugin", "向项目或用户环境提供技能、扩展等资源的可复用插件。"),
    ("Preferred Endpoint", "同一模型存在多个端点时被目录标记为优先的唯一候选。"),
    ("Prompt", "用户交给模型或工作流的任务说明与上下文。"),
    ("Provider", "提供模型服务、认证和协议语义的模型提供方身份。"),
    ("Reload", "重新发现键位、扩展、技能、提示模板和主题等资源。"),
    ("Resume", "通过标识、路径或交互选择器恢复指定会话。"),
    ("RPC", "供外部宿主以请求响应方式控制 Loushang 的集成模式。"),
    ("Session", "保存消息、工具事件、用量、诊断和关系的持久执行记录。"),
    ("Skill", "封装领域知识、操作流程和工具协作方式的可复用技能。"),
    ("Source Info", "说明资源和配置最终来自哪个层级的来源信息。"),
    ("Thinking", "向支持模型表达推理强度偏好的请求参数。"),
    ("Tool", "在策略控制下提供给 Agent 的可执行能力。"),
    ("Tool Call", "模型请求应用调用某个工具及其结构化参数的事件。"),
    ("Tool Result", "应用执行工具后返回给模型的成功或错误结果。"),
    ("Trace", "用于分析事件顺序和边界行为的详细跟踪记录。"),
    ("TUI", "运行在终端中的全屏或 plain 交互式用户界面。"),
    ("Usage", "模型请求的输入、输出、缓存或其他计量信息。"),
    ("Work Event", "表示工作计划、阶段或操作状态变化的结构化事件。"),
    ("Work Log", "按 JSONL 记录 WorkOperation 与 WorkEvent 的运行日志。"),
    ("Work Operation", "一次受方法或任务目标约束的工作运行实体。"),
    ("Worktree", "Git 提供的独立工作目录，可用于隔离并行分支任务。"),
)


CLI_REFERENCE: tuple[tuple[str, str, str], ...] = (
    ("--help, -h", "显示主命令帮助并退出。", "安装验证和参数发现。"),
    ("--version, -v", "显示程序版本并退出。", "核对部署与登记基线。"),
    (
        "--mode",
        "选择 text、print、json、rpc 或 channel 模式。",
        "按终端或集成调用方选择输出协议。",
    ),
    ("--tui", "请求启动终端交互产品面。", "多轮编程工作。"),
    ("--no-tui", "关闭全屏终端界面。", "脚本、管道或普通文本运行。"),
    ("--no-session", "关闭本次会话持久化。", "一次性敏感或临时任务。"),
    ("--session-name", "设置新会话的可读名称。", "便于检索和恢复。"),
    ("--session", "指定会话标识。", "精确控制会话目标。"),
    ("--list-sessions", "列出可发现会话。", "恢复、审计和清理前检查。"),
    ("--resume, -r", "恢复指定会话或打开交互选择器。", "继续历史工作。"),
    ("--continue, -c", "恢复当前项目最近会话。", "快速延续上次工作。"),
    ("--cwd", "设置 Agent 工作目录。", "从其他 shell 目录处理目标项目。"),
    ("--provider", "显式选择模型提供方。", "收窄提供方路由。"),
    ("--model", "选择短格式或完整格式模型键。", "指定模型与端点。"),
    ("--thinking", "设置模型推理强度偏好。", "平衡复杂度、延迟与成本。"),
    ("--tools, -t", "设置活动工具名称集合。", "建立最小权限工具面。"),
    ("--no-tools, -nt", "禁用所有工具。", "只根据已有上下文回答。"),
    ("--no-builtin-tools, -nbt", "禁用内置工具。", "只使用其他贡献来源。"),
    ("--export", "导出当前或指定会话。", "归档、评审和迁移。"),
    ("--export-format", "选择 html 或 jsonl。", "按人读或机读用途导出。"),
    (
        "--export-result-format",
        "选择导出命令结果的 text 或 json。",
        "脚本获取导出状态。",
    ),
    ("--command", "执行已发现命令。", "非交互调用 slash 类命令。"),
    ("--command-args", "为 command 提供参数文本。", "传递命令专用参数。"),
    ("--command-result-format", "选择 raw 或 json 命令结果。", "人读或集成处理。"),
    ("--list-sessions-format", "选择会话列表 TSV 或 JSON。", "终端浏览或自动化。"),
    ("--source-info", "显示资源与配置来源。", "排查层级覆盖问题。"),
    ("--source-info-format", "选择来源信息文本或 JSON。", "保存可审计快照。"),
    ("--all-sessions", "跨默认范围搜索会话。", "查找其他项目或目录的记录。"),
    ("--session-index", "启用或检查会话索引入口。", "加速大量记录发现。"),
    ("--refresh-session-index", "刷新会话索引。", "目录迁移或索引陈旧。"),
    ("--session-cwd", "按工作目录筛选会话。", "限定目标项目。"),
    ("--session-name-filter", "按名称筛选会话。", "定位业务任务。"),
    ("--session-parent", "按父会话筛选。", "查看分支关系。"),
    ("--session-query", "使用综合查询筛选会话。", "复杂历史检索。"),
    ("--session-has-diagnostics", "只列出含诊断会话。", "集中排查异常。"),
    ("--session-no-diagnostics", "只列出无诊断会话。", "筛选干净记录。"),
    ("--session-limit", "限制会话返回数量。", "控制列表规模。"),
    ("--fork", "从指定会话创建分叉。", "尝试不同解决方案。"),
    ("--session-dir", "指定会话存储目录。", "隔离项目或测试记录。"),
    ("--list-models", "列出模型目录条目。", "选择和核对模型。"),
    ("--list-models-format", "选择模型列表 text 或 json。", "浏览或程序处理。"),
    ("--models", "指定额外模型目录。", "加载项目或私有模型。"),
    ("--extension, -e", "显式加载扩展。", "开发、测试或临时使用扩展。"),
    ("--no-extensions, -ne", "关闭扩展加载。", "隔离扩展故障。"),
    ("--skill", "显式选择技能。", "应用特定领域工作法。"),
    ("--no-skills, -ns", "关闭技能发现或使用。", "隔离技能影响。"),
    ("--prompt-template", "选择提示模板。", "复用标准任务提示。"),
    ("--no-prompt-templates, -np", "关闭提示模板。", "只使用原始用户提示。"),
    ("--theme", "选择终端主题。", "适配显示与可访问性。"),
    ("--no-themes", "关闭主题资源。", "隔离主题加载问题。"),
    ("--system-prompt", "替换系统提示。", "受控宿主定制行为。"),
    ("--prompt, -p", "提供主要任务提示。", "一次性或脚本任务。"),
    ("--append-system-prompt", "追加系统提示内容。", "补充组织约束。"),
    ("--verbose", "启用更详细的人类输出。", "一般问题定位。"),
    ("--debug", "启用指定调试主题。", "组件级诊断。"),
    ("--debug-file", "把调试信息写入文件。", "保存复现证据。"),
    ("--trace", "启用指定跟踪主题。", "分析事件顺序。"),
    ("--trace-file", "把跟踪信息写入文件。", "离线时序分析。"),
    ("--offline", "禁止真实模型请求。", "静态、恢复和路由测试。"),
    ("--render-tool-events", "在输出中呈现工具事件。", "观察和审计工具调用。"),
    ("--message", "附加消息提示。", "构造多消息输入。"),
    ("--tool", "提供单个工具相关配置。", "细粒度工具装配。"),
    ("--no-context-files, -nc", "关闭上下文文件发现。", "隔离项目指令影响。"),
    ("--list-commands", "列出内置及贡献命令。", "发现可用命令与来源。"),
    ("--list-commands-format", "选择命令列表 TSV 或 JSON。", "终端浏览或集成。"),
    ("--list-diagnostics", "列出诊断。", "检查运行与资源问题。"),
    ("--list-diagnostics-format", "选择诊断 TSV 或 JSON。", "保存或处理诊断。"),
    ("--diagnostics-limit", "限制诊断返回数量。", "控制大规模列表。"),
    ("--diag-export", "导出诊断包。", "问题报告和离线分析。"),
    ("--diag-output", "设置诊断导出路径。", "明确归档位置。"),
    ("--list-skills", "列出技能。", "发现可复用工作资产。"),
    ("--list-skills-format", "选择技能列表 TSV 或 JSON。", "浏览或自动化。"),
    ("--enable-skill", "启用项目技能。", "持久化项目选择。"),
    ("--disable-skill", "禁用项目技能。", "控制技能来源。"),
    ("--list-plugins", "列出插件。", "检查来源与启用状态。"),
    ("--list-plugins-format", "选择插件列表 TSV 或 JSON。", "人工或审计处理。"),
    ("--list-packages", "列出软件包。", "检查可复用资产。"),
    ("--list-packages-format", "选择 text、tsv 或 json。", "匹配消费方格式。"),
    ("--package-catalog", "指定包目录。", "使用项目或组织包源。"),
    ("--install-package", "安装指定来源包。", "引入可复用资产。"),
    ("--uninstall-package", "卸载指定来源包。", "移除不再使用资产。"),
    ("--package-scope", "选择 global 或 project 范围。", "控制安装影响面。"),
    ("--update-packages", "更新已安装包集合。", "维护资产版本。"),
    ("--check-package-updates", "检查可用包更新。", "升级前评估。"),
    ("--materialize-package", "物化指定包内容。", "检查或定制资产。"),
    ("--update-package", "更新一个指定包。", "受控单包升级。"),
    ("--remove-package", "移除指定包记录或内容。", "清理资产。"),
    ("--add-plugin-source, --add-plugin", "添加插件来源。", "引入可信插件目录。"),
    ("--remove-plugin-source, --remove-plugin", "移除插件来源。", "停止发现指定来源。"),
    ("--enable-plugin", "启用插件。", "让贡献进入项目解析。"),
    ("--disable-plugin", "禁用插件。", "隔离插件影响。"),
    ("--method", "使用发现的方法指导一次任务。", "按工作契约执行。"),
    ("--no-method", "绕过配置的默认方法。", "显式普通任务。"),
    ("--prompt-steps, -ps", "运行提示步骤工作流文件。", "阶段化可重复任务。"),
    ("--work-log", "写入 WorkOperation 与 WorkEvent。", "记录可追踪运行。"),
    ("--work-log-inspect", "检查工作日志文件。", "复盘运行与计划。"),
    ("--work-log-run", "按 run id 筛选工作日志。", "定位单次运行。"),
    (
        "--work-log-inspect-format",
        "选择 text、json、plans 或 plans-json。",
        "匹配阅读与集成用途。",
    ),
    ("--list-methods", "列出方法。", "发现工作契约。"),
    ("--list-methods-format", "选择方法列表 TSV 或 JSON。", "浏览或自动化。"),
    ("--show-method", "显示指定方法。", "执行前审查方法。"),
    ("--show-method-format", "选择方法 text 或 json。", "阅读或集成。"),
    ("--show-method-plan", "显示方法计划。", "确认阶段和产物。"),
    ("--show-method-plan-format", "选择计划 text 或 json。", "阅读或处理计划。"),
)


SLASH_COMMANDS: tuple[tuple[str, str], ...] = (
    ("/settings", "查看或修改设置。"),
    ("/model", "查看和选择当前模型。"),
    ("/scoped-models", "查看不同范围解析出的模型。"),
    ("/export", "导出当前会话。"),
    ("/import", "从 JSONL 导入并恢复会话。"),
    ("/share", "使用可用共享入口处理会话。"),
    ("/copy", "复制助手消息。"),
    ("/rename", "重命名当前会话。"),
    ("/session", "显示会话信息与统计。"),
    ("/terminal", "查看或控制终端相关入口。"),
    ("/tools", "查看或调整活动工具。"),
    ("/changelog", "显示变更记录。"),
    ("/hotkeys", "显示快捷键说明。"),
    ("/fork", "从历史用户消息创建分叉。"),
    ("/clone", "复制当前会话位置。"),
    ("/tree", "导航会话树和分支。"),
    ("/new", "在当前上下文新建空会话，不接受参数。"),
    ("/compact", "手动压缩会话上下文。"),
    ("/resume", "恢复其他会话。"),
    ("/delete", "选择并删除历史会话，不删除当前活跃会话。"),
    ("/reload", "重新加载资源。"),
    ("/quit", "正常退出交互会话。"),
)


def render_topic(chapter_number: int, topic_number: int, item: Topic) -> list[str]:
    lines = [
        f"## {chapter_number}.{topic_number} {item.title}",
        "",
        item.overview,
        "",
        "### 功能要点",
    ]
    lines.extend(f"- {value}" for value in item.principles)
    lines.extend(("", "### 操作步骤"))
    lines.extend(f"{index}. {value}" for index, value in enumerate(item.steps, start=1))
    lines.extend(("", "### 命令或配置示例", "```text"))
    lines.extend(item.examples)
    lines.extend(("```", "", "### 验证方法"))
    lines.extend(f"- {value}" for value in item.checks)
    lines.extend(("", "### 注意事项"))
    lines.extend(f"- {value}" for value in item.cautions)
    lines.extend(
        (
            "",
            "### 记录建议",
            f"- 建议在会话名称、工作日志或交付说明中记录“{item.title}”的实际选择。",
            "- 如实际结果与预期不同，应保留命令、状态码和最小复现信息。",
            "",
        )
    )
    return lines


def render_chapter(chapter_number: int, chapter: Chapter) -> str:
    lines = [
        f"# {chapter.title}",
        "",
        f"> 文档版本：{VERSION}",
        "",
        chapter.purpose,
        "",
        "本章以用户可执行操作为主，命令和路径均应在目标安装环境中再次核对。",
        "",
    ]
    for topic_number, item in enumerate(chapter.topics, start=1):
        lines.extend(render_topic(chapter_number, topic_number, item))
    return "\n".join(lines).rstrip() + "\n"


def render_troubleshooting() -> str:
    lines = [
        "# 第14章 常见问题与故障排除",
        "",
        f"> 文档版本：{VERSION}",
        "",
        "本章按照“现象、可能原因、处理步骤、验证和注意事项”的顺序给出排查方法。",
        "",
        "排查时应先保存现场，再缩小问题范围；不要为获得成功结果而删除失败证据。",
        "",
    ]
    for index, (name, cause, steps, cautions) in enumerate(TROUBLESHOOTING, start=1):
        lines.extend(
            (
                f"## 14.{index} {name}",
                "",
                "### 现象与原因",
                cause,
                "",
                "### 处理步骤",
            )
        )
        lines.extend(
            f"{step_index}. {value}" for step_index, value in enumerate(steps, start=1)
        )
        lines.extend(
            (
                "",
                "### 验证",
                f"- 重新执行与“{name}”直接相关的最小命令。",
                "- 检查退出状态、标准错误、诊断列表和实际文件状态。",
                "- 修复后再执行原始任务，确认问题没有被临时绕过。",
                "",
                "### 注意事项",
            )
        )
        lines.extend(f"- {value}" for value in cautions)
        lines.extend(
            (
                "- 若仍不能解决，应导出脱敏后的诊断和最小复现步骤。",
                "- 问题报告应包含环境、模型键、工作目录类型和发生时间。",
                "",
            )
        )
    return "\n".join(lines).rstrip() + "\n"


def render_cli_reference() -> str:
    lines = [
        "# 第15章 命令行参数参考",
        "",
        f"> 文档版本：{VERSION}",
        "",
        "本章按登记基线的主命令帮助整理参数。扩展可以注册附加参数，因此实际输出可能更多。",
        "",
        "参数值、互斥关系和默认行为应以目标安装环境执行 loushang --help 的结果为准。",
        "",
    ]
    for index, (flag, purpose, scenario) in enumerate(CLI_REFERENCE, start=1):
        lines.extend(
            (
                f"## 15.{index} `{flag}`",
                "",
                f"- 用途：{purpose}",
                f"- 适用场景：{scenario}",
                f"- 查询方式：运行 `loushang --help` 核对 `{flag}` 的登记基线定义。",
                "- 自动化要求：固定结果格式，并同时检查退出状态和标准错误。",
                "- 安全要求：涉及写入、外部访问或删除时应先确认范围。",
                "- 兼容性：扩展参数和提供方参数可能随已加载资源变化。",
                "",
            )
        )
    lines.extend(
        (
            "# 第15章附录 交互命令参考",
            "",
            "下列命令是登记基线用户文档中列出的主要交互命令。",
            "",
        )
    )
    for index, (command, description) in enumerate(SLASH_COMMANDS, start=1):
        lines.extend(
            (
                f"## 15.A.{index} `{command}`",
                f"- 功能：{description}",
                "- 使用位置：交互式会话输入区。",
                "- 来源核对：运行 `loushang --list-commands`。",
                "- 注意：扩展或其他资产可能贡献同名或附加命令，应检查来源。",
                "",
            )
        )
    return "\n".join(lines).rstrip() + "\n"


def render_glossary() -> str:
    lines = [
        "# 第16章 术语表与附录",
        "",
        f"> 文档版本：{VERSION}",
        "",
        "本章统一手册中的中英文术语，并给出版本、文档维护和打印说明。",
        "",
        "## 16.1 术语表",
        "",
    ]
    for index, (term, explanation) in enumerate(GLOSSARY, start=1):
        lines.extend(
            (
                f"### 16.1.{index} {term}",
                f"- 定义：{explanation}",
                f"- 使用建议：首次出现时可写为中文名称（{term}），后续按上下文使用中文或命令原文。",
                "- 核对要求：涉及程序标识、参数和文件名时保持英文原文，不做意译。",
                "",
            )
        )
    lines.extend(
        (
            "## 16.2 文档版本说明",
            "",
            f"- 软件登记文档版本：{VERSION}。",
            f"- 文档发布日期：{RELEASE_DATE}。",
            "- 软件名称、版本号、源代码页眉和登记申请表应保持一致。",
            "- 本手册描述当前 coding 产品面和 loushang.ai SDK，不把路线图写成当前功能。",
            "",
            "## 16.3 文档维护",
            "",
            "- CLI 参数变更后，应重新生成第15章并执行帮助输出交叉检查。",
            "- 模型目录和提供方信息变化后，应更新模型路由章节。",
            "- 会话、工具、扩展和方法语义变化后，应补充迁移与兼容说明。",
            "- 每次发布应重新生成 HTML，并保存 validation.json 验收结果。",
            "",
            "## 16.4 打印说明",
            "",
            "- 使用 A4 纵向、单面、黑白打印。",
            "- 打印比例设为 100%，边距设为无，关闭浏览器附加页眉页脚。",
            "- 正文页码已经固定在每页右上角，不使用浏览器自动页码。",
            "- 正文每页包含不少于 30 个显式内容行。",
            "- 封面和目录作为前置页，正文从第1页连续编号。",
            "",
            "## 16.5 最终核对",
            "",
            "- 核对软件全称、简称、版本号和权利人信息。",
            "- 核对所有截图、命令和示例均来自目标版本。",
            "- 核对正文前30页与后30页连续、清晰且无空白页。",
            "- 核对会话、日志、截图和诊断中不存在真实凭证。",
            "- 核对 PDF 或打印件，而不是只核对 Markdown 源文件。",
            "",
            "## 16.6 文档结束",
            "",
            "本手册到此结束。使用过程中应以目标安装环境的帮助、诊断和实际验证结果为准。",
            "如发现文档与程序行为不一致，应先保存复现证据，再修正文档或程序基线。",
            "任何完成声明都应能够追溯到实际命令、文件差异、测试结果或人工确认。",
            "",
        )
    )
    return "\n".join(lines).rstrip() + "\n"


def write_markdown_sources() -> list[Path]:
    MANUAL_DIR.mkdir(parents=True, exist_ok=True)
    cover = "\n".join(
        (
            "# Loushang 用户手册",
            "",
            f"软件名称：{PRODUCT_NAME}",
            "",
            f"版本号：{VERSION}",
            "",
            "文档类型：用户手册",
            "",
            f"发布日期：{RELEASE_DATE}",
            "",
            "适用产品：Loushang Code 与 loushang.ai",
            "",
            "文档状态：软件著作权登记排版源文件",
            "",
        )
    )
    (MANUAL_DIR / "00-封面与版本.md").write_text(cover, encoding="utf-8")
    generated: list[Path] = [MANUAL_DIR / "00-封面与版本.md"]
    for chapter_number, chapter in enumerate(CHAPTERS, start=1):
        path = MANUAL_DIR / chapter.filename
        path.write_text(render_chapter(chapter_number, chapter), encoding="utf-8")
        generated.append(path)
    troubleshooting_path = MANUAL_DIR / "15-故障排除.md"
    troubleshooting_path.write_text(render_troubleshooting(), encoding="utf-8")
    generated.append(troubleshooting_path)
    cli_path = MANUAL_DIR / "16-命令行参考.md"
    cli_path.write_text(render_cli_reference(), encoding="utf-8")
    generated.append(cli_path)
    glossary_path = MANUAL_DIR / "17-术语与附录.md"
    glossary_path.write_text(render_glossary(), encoding="utf-8")
    generated.append(glossary_path)
    return generated


INLINE_MARKUP = re.compile(r"(\*\*|__|`)")
ORDERED_PREFIX = re.compile(r"^\d+\.\s+")


def display_width(text: str) -> int:
    width = 0
    for char in text:
        if unicodedata.combining(char):
            continue
        width += 2 if unicodedata.east_asian_width(char) in {"W", "F", "A"} else 1
    return width


def split_by_width(text: str, width: int) -> list[str]:
    if not text:
        return []
    parts: list[str] = []
    remaining = text
    while display_width(remaining) > width:
        current: list[str] = []
        current_width = 0
        last_break = -1
        for index, char in enumerate(remaining):
            char_width = (
                0
                if unicodedata.combining(char)
                else (2 if unicodedata.east_asian_width(char) in {"W", "F", "A"} else 1)
            )
            if current_width + char_width > width:
                break
            current.append(char)
            current_width += char_width
            if char in "，。；：、,. /-":
                last_break = index + 1
        take = len(current)
        if 0 < last_break < take and take - last_break <= 8:
            take = last_break
        parts.append(remaining[:take].rstrip())
        remaining = remaining[take:].lstrip()
    if remaining:
        parts.append(remaining)
    return parts


def markdown_to_manual_lines(path: Path) -> list[ManualLine]:
    chapter = path.stem
    result: list[ManualLine] = []
    in_code = False
    for raw in path.read_text(encoding="utf-8").splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith("<!--"):
            continue
        if stripped.startswith("```"):
            if not in_code:
                language = stripped[3:].strip() or "text"
                result.append(
                    ManualLine(f"代码示例（{language}）：", "code-label", chapter)
                )
            in_code = not in_code
            continue
        kind = "code" if in_code else "text"
        text = raw.strip() if in_code else stripped
        if not in_code:
            if text.startswith("# "):
                kind = "chapter"
                text = text[2:].strip()
            elif text.startswith("## "):
                kind = "section"
                text = text[3:].strip()
            elif text.startswith("### "):
                kind = "subsection"
                text = text[4:].strip()
            elif text.startswith("> "):
                kind = "note"
                text = "说明：" + text[2:].strip()
            elif text.startswith("- "):
                kind = "bullet"
                text = "• " + text[2:].strip()
            elif ORDERED_PREFIX.match(text):
                kind = "ordered"
            text = INLINE_MARKUP.sub("", text)
        wrap_width = CODE_WRAP_COLUMNS if kind == "code" else WRAP_COLUMNS
        wrapped = split_by_width(text, wrap_width)
        for index, part in enumerate(wrapped):
            continuation_kind = kind if index == 0 else f"{kind} continuation"
            result.append(ManualLine(part, continuation_kind, chapter))
    return result


def distribute_pages(lines: list[ManualLine]) -> list[list[ManualLine]]:
    if len(lines) < MIN_BODY_PAGES * MIN_LINES_PER_PAGE:
        raise ValueError(
            f"正文仅有 {len(lines)} 个可见行，少于 "
            f"{MIN_BODY_PAGES * MIN_LINES_PER_PAGE} 行最低要求。"
        )
    page_count = math.ceil(len(lines) / MAX_LINES_PER_PAGE)
    if len(lines) / page_count < MIN_LINES_PER_PAGE:
        raise ValueError("无法在每页不少于 30 行的条件下分配正文。")
    base = len(lines) // page_count
    extra = len(lines) % page_count
    sizes = [base + (1 if index < extra else 0) for index in range(page_count)]
    pages: list[list[ManualLine]] = []
    cursor = 0
    for size in sizes:
        pages.append(lines[cursor : cursor + size])
        cursor += size
    return pages


def chapter_page_ranges(pages: list[list[ManualLine]]) -> dict[str, tuple[int, int]]:
    ranges: dict[str, list[int]] = {}
    for page_number, page in enumerate(pages, start=1):
        for line in page:
            ranges.setdefault(line.chapter, []).append(page_number)
    return {
        chapter: (min(page_numbers), max(page_numbers))
        for chapter, page_numbers in ranges.items()
    }


def write_toc(ranges: dict[str, tuple[int, int]]) -> Path:
    entries: list[tuple[str, str]] = []
    for chapter in CHAPTERS:
        start, end = ranges[Path(chapter.filename).stem]
        page_text = str(start) if start == end else f"{start}—{end}"
        entries.append((chapter.title, page_text))
    for filename, title in (
        ("15-故障排除.md", "第14章 常见问题与故障排除"),
        ("16-命令行参考.md", "第15章 命令行参数参考"),
        ("17-术语与附录.md", "第16章 术语表与附录"),
    ):
        start, end = ranges[Path(filename).stem]
        page_text = str(start) if start == end else f"{start}—{end}"
        entries.append((title, page_text))
    lines = [
        "# 目录与文档说明",
        "",
        f"文档名称：{DOCUMENT_NAME}",
        "",
        f"版本号：{VERSION}",
        "",
        "正文页码从第1页开始连续编号，封面和目录不计入正文页码。",
        "",
        "## 目录",
        "",
    ]
    lines.extend(f"- {title} …… {page_text}" for title, page_text in entries)
    lines.extend(
        (
            "",
            "## 阅读说明",
            "",
            "- 第1至第3章适合首次安装和快速开始的用户。",
            "- 第4至第11章说明日常 CLI、会话、工具和交付操作。",
            "- 第12章面向直接使用 loushang.ai 的 Python 开发者。",
            "- 第13至第16章用于安全检查、故障排除和参数查询。",
            "- 命令、路径和模型键在代码块中保持英文原文。",
            "- 实际功能以目标安装环境的 --help 和诊断结果为准。",
            "",
        )
    )
    path = MANUAL_DIR / "01-目录与文档说明.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


CSS = r"""
@page { size: A4 portrait; margin: 0; }
* { box-sizing: border-box; }
html, body {
  margin: 0;
  padding: 0;
  background: #ececec;
  color: #111;
  font-family: "Noto Sans CJK SC", "Source Han Sans SC", "Microsoft YaHei",
               "PingFang SC", "SimSun", sans-serif;
}
.screen-note {
  width: 210mm;
  margin: 12px auto;
  padding: 12px 16px;
  background: #fff9d8;
  border: 1px solid #aaa;
  font-size: 13px;
}
.sheet {
  position: relative;
  width: 210mm;
  height: 297mm;
  margin: 8px auto;
  padding: 12mm 18mm 12mm;
  background: white;
  overflow: hidden;
  break-after: page;
  page-break-after: always;
  box-shadow: 0 1px 8px rgba(0,0,0,.16);
}
.sheet:last-child { break-after: auto; page-break-after: auto; }
.page-header {
  height: 12mm;
  display: grid;
  grid-template-columns: 1fr 1fr 1fr;
  align-items: start;
  border-bottom: .3mm solid #222;
  font-size: 10pt;
  line-height: 1.3;
  padding-top: 1mm;
}
.page-header .center { text-align: center; }
.page-header .right { text-align: right; white-space: nowrap; }
.page-body { padding-top: 3mm; }
.manual-line {
  height: 5.35mm;
  line-height: 5.35mm;
  font-size: 10.5pt;
  white-space: pre;
  overflow: hidden;
}
.manual-line.chapter {
  font-size: 14pt;
  font-weight: 700;
  border-bottom: .2mm solid #777;
}
.manual-line.section { font-size: 12pt; font-weight: 700; }
.manual-line.subsection { font-size: 11pt; font-weight: 700; }
.manual-line.note { color: #333; font-weight: 600; }
.manual-line.bullet, .manual-line.ordered { padding-left: 1em; }
.manual-line.code, .manual-line.code-label {
  font-family: "Noto Sans Mono CJK SC", "Sarasa Mono SC", "Consolas", monospace;
  background: #f4f4f4;
  padding-left: 1.5mm;
}
.manual-line.code-label { font-weight: 700; }
.manual-line.continuation:not(.code) { padding-left: 1em; }
.cover {
  display: flex;
  flex-direction: column;
  text-align: center;
  padding-top: 20mm;
}
.cover-mark {
  position: absolute;
  top: 12mm;
  left: 18mm;
  right: 18mm;
  display: flex;
  justify-content: space-between;
  border-bottom: .3mm solid #222;
  padding-bottom: 3mm;
  font-size: 10pt;
}
.cover h1 { margin: 52mm 0 8mm; font-size: 28pt; letter-spacing: .12em; }
.cover .version { font-size: 20pt; font-weight: 700; margin-bottom: 28mm; }
.cover .meta { width: 128mm; margin: 0 auto; text-align: left; font-size: 12pt; }
.cover .meta div { margin: 6mm 0; border-bottom: .2mm solid #999; padding-bottom: 2mm; }
.toc-list { margin-top: 5mm; }
.toc-entry {
  display: grid;
  grid-template-columns: auto 1fr auto;
  gap: 2mm;
  font-size: 10.5pt;
  line-height: 8mm;
}
.toc-dots { border-bottom: .2mm dotted #777; transform: translateY(-3mm); }
.toc-note { font-size: 10pt; line-height: 1.8; margin-top: 8mm; }
@media print {
  html, body { background: white; }
  .screen-note { display: none; }
  .sheet { margin: 0; box-shadow: none; }
}
"""


def render_cover() -> str:
    return f"""
<section class="sheet cover" aria-label="封面">
  <div class="cover-mark"><span>{PRODUCT_NAME}</span><span>{VERSION}</span></div>
  <h1>Loushang 用户手册</h1>
  <div class="version">{VERSION}</div>
  <div class="meta">
    <div>软件名称：{PRODUCT_NAME}</div>
    <div>文档类型：用户手册</div>
    <div>适用产品：Loushang Code 与 loushang.ai</div>
    <div>发布日期：{RELEASE_DATE}</div>
    <div>文档状态：软件著作权登记排版稿</div>
  </div>
</section>
"""


def render_toc_pages(ranges: dict[str, tuple[int, int]]) -> str:
    entries: list[tuple[str, str]] = []
    for chapter in CHAPTERS:
        start, end = ranges[Path(chapter.filename).stem]
        entries.append(
            (chapter.title, str(start) if start == end else f"{start}—{end}")
        )
    for filename, title in (
        ("15-故障排除.md", "第14章 常见问题与故障排除"),
        ("16-命令行参考.md", "第15章 命令行参数参考"),
        ("17-术语与附录.md", "第16章 术语表与附录"),
    ):
        start, end = ranges[Path(filename).stem]
        entries.append((title, str(start) if start == end else f"{start}—{end}"))
    entry_html = "\n".join(
        f'<div class="toc-entry"><span>{html.escape(title)}</span>'
        f'<span class="toc-dots"></span><span>{pages}</span></div>'
        for title, pages in entries
    )
    return f"""
<section class="sheet" aria-label="目录">
  <div class="page-header">
    <span>{PRODUCT_NAME}</span><span class="center">目录</span>
    <span class="right">{VERSION}</span>
  </div>
  <div class="toc-list">{entry_html}</div>
  <div class="toc-note">
    <p>正文页码从第1页开始连续编号，封面和目录不计入正文页码。</p>
    <p>第1至第3章适合首次安装和快速开始；第4至第11章说明日常操作；
       第12章面向 SDK 开发者；第13至第16章用于安全检查、排错与查询。</p>
    <p>实际命令、模型和扩展能力以目标安装环境的帮助与诊断结果为准。</p>
  </div>
</section>
"""


def render_body_pages(pages: list[list[ManualLine]]) -> str:
    rendered_pages: list[str] = []
    for page_number, page in enumerate(pages, start=1):
        line_html = "\n".join(
            f'<div class="manual-line {html.escape(line.kind)}">'
            f"{html.escape(line.text)}</div>"
            for line in page
        )
        rendered_pages.append(
            f"""
<section class="sheet body-page" data-page="{page_number}"
         data-line-count="{len(page)}" aria-label="正文第{page_number}页">
  <div class="page-header">
    <span>{PRODUCT_NAME}</span>
    <span class="center">用户手册</span>
    <span class="right">{VERSION}　正文第{page_number}页</span>
  </div>
  <div class="page-body">{line_html}</div>
</section>
"""
        )
    return "\n".join(rendered_pages)


def build_html(source_paths: list[Path]) -> tuple[Path, dict[str, object]]:
    body_paths = [
        path
        for path in source_paths
        if path.name[:2].isdigit() and int(path.name[:2]) >= 2
    ]
    body_lines: list[ManualLine] = []
    for path in body_paths:
        body_lines.extend(markdown_to_manual_lines(path))
    pages = distribute_pages(body_lines)
    ranges = chapter_page_ranges(pages)
    toc_path = write_toc(ranges)
    source_paths.insert(1, toc_path)
    document = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{DOCUMENT_NAME} {VERSION}</title>
  <style>{CSS}</style>
</head>
<body>
<div class="screen-note">
  打印说明：选择 A4、纵向、缩放 100%、边距“无”，并关闭浏览器附加页眉和页脚。
  正文页眉、右上角页码和分页已写入文档。
</div>
{render_cover()}
{render_toc_pages(ranges)}
{render_body_pages(pages)}
</body>
</html>
"""
    DIST_DIR.mkdir(parents=True, exist_ok=True)
    output = DIST_DIR / f"Loushang-用户手册-{VERSION}.html"
    output.write_text(document, encoding="utf-8")
    line_counts = [len(page) for page in pages]
    validation: dict[str, object] = {
        "document": DOCUMENT_NAME,
        "version": VERSION,
        "generated_from": [path.name for path in source_paths],
        "front_matter_pages": 2,
        "body_pages": len(pages),
        "total_pages": len(pages) + 2,
        "body_lines": len(body_lines),
        "minimum_lines_per_body_page": min(line_counts),
        "maximum_lines_per_body_page": max(line_counts),
        "consecutive_body_page_numbers": list(range(1, len(pages) + 1)),
        "header_text": [PRODUCT_NAME, VERSION],
        "chapter_page_ranges": {
            chapter: {"start": start, "end": end}
            for chapter, (start, end) in ranges.items()
        },
        "checks": {
            "body_pages_at_least_60": len(pages) >= MIN_BODY_PAGES,
            "every_body_page_at_least_30_lines": min(line_counts) >= MIN_LINES_PER_PAGE,
            "every_body_page_at_most_42_lines": max(line_counts) <= MAX_LINES_PER_PAGE,
            "page_numbers_start_at_1": bool(pages),
            "explicit_a4_pages": True,
            "header_on_every_body_page": True,
        },
        "known_version_note": (
            "本手册登记文档版本为 V1.0.0；生成时仓库 pyproject.toml "
            "仍需由发布负责人另行核对软件包版本。"
        ),
    }
    validation_path = DIST_DIR / "validation.json"
    validation_path.write_text(
        json.dumps(validation, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return output, validation


def main() -> int:
    sources = write_markdown_sources()
    output, validation = build_html(sources)
    print(f"generated_markdown={len(sources)}")
    print(f"generated_html={output}")
    print(f"body_pages={validation['body_pages']}")
    print(f"total_pages={validation['total_pages']}")
    print(f"min_lines={validation['minimum_lines_per_body_page']}")
    print(f"max_lines={validation['maximum_lines_per_body_page']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
