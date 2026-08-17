# 快速开始

[English](../../en/getting-started/) | 中文

本指南帮助你从新 clone 的仓库运行第一条 `loushang code` prompt。

## 环境要求

- Python 3.11 或更新版本。
- 在线运行时需要模型 provider 凭证。
- 可运行 Python 虚拟环境的终端环境。

## 从源码安装

```bash
git clone https://github.com/zhnt/loushang.git
cd loushang

uv venv .venv
source .venv/bin/activate
uv pip install -e ".[dev]"
```

等价的 Makefile 便捷命令：

```bash
make bootstrap
source .venv/bin/activate
```

`make bootstrap` 会用 `uv` 创建 `.venv/` 并以 editable development mode 安装项目。当前没有 `make install` 目标；`make install-binary` 用于构建并安装本地二进制。

## 检查 CLI

```bash
loushang --help
loushang --list-models
loushang --list-commands
```

## 运行第一条 Prompt

```bash
loushang -p "Inspect this repository and summarize what it does."
```

需要选择具体模型路线时，可以使用 `--model` 或 provider 相关环境变量。`--model provider:model` 是短写（也接受 `provider/model`）：只有该 provider/model 恰好匹配一个 endpoint 时才可用。如果同一个 provider/model 存在多个 endpoint，CLI 会报告歧义并列出可显式选择的 `provider:endpoint:model` 候选。需要指定具体 endpoint、region、lane 或 protocol 时，使用 `--model provider:endpoint:model`。模型切换成功后，CLI 会把完整选择保存为全局 `default_model`，路径是 `~/.loushang/coding/settings.json`；带 endpoint 的选择会保留 `provider`、`model_id` 和 `endpoint_id`，不会写入项目级 `.loushang/settings.json`。catalog key 中 `provider` 和 `model` id 不能包含 `:`，endpoint id 可以包含 `:`。项目与示例模型 catalog 可以放在 `.loushang/models/`，也可以在支持的入口显式传入。

## 下一步

- 阅读[使用手册](../user-guide/)，了解会话、命令、工具、扩展、方法和诊断。
- 阅读[示例](../examples/)，查找可运行的 coding 和 AI SDK 场景。
- 阅读[参考手册](../reference/)，查询准确的 CLI 与配置入口。
