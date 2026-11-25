# Windows 安装包拆分方向

当前 Windows x64 交付提供 NSIS 和 MSI 两种 Full 安装包。参见
[构建与安装指南](../../../scripts/build/README.md)和
[部署验收流程](../../../scripts/gui/check_windows_full.ps1)。
本页记录后续拆包方向，现阶段继续交付完整包。

## 安装包边界

| 安装包 | 组件 | 部署方式 |
| --- | --- | --- |
| 前端包 | TUI 客户端、桌面 GUI、`loushang-web`、Web 页面资源及 WebView2 | 连接已部署的 AppHost |
| 后端包 | AppHost、Mux 管理入口、Python 运行时及后端执行依赖 | 独立运行，供前端连接 |
| 完整包 | 前端和后端的全部组件 | 在同一台机器上启动并连接 |

`loushang-web` 提供浏览器页面并适配 AppServer 客户端调用，随 Web 页面资源一起交付。
AppHost 负责执行和会话持久化，Mux 管理入口负责后端生命周期。
相关边界见 [Web 共享适配器](gui-web-host-interface.md)。

## 后续实现与验收

- 同一版本每个组件构建一次，按三份组件清单组装 NSIS 安装包。完整包复用前端包和后端包的同版本组件。
- 当前 Windows TUI 二进制使用可本机执行的 `loushang` CLI 入口。拆包时评估现有
  `loushang-hosted-tui` 客户端入口，并分别验证 TUI、GUI、Web 连接独立部署的 AppHost。
- 验证完整包的本机启动与连接，以及先装独立包再补装另一部分的流程。升级和卸载须遵循
  [工作区升级兼容性要求](decisions/accepted/ARD-008-workspace-upgrade-compatibility.md)，
  保留已有工作区、连接配置和会话，明确共享组件和数据的归属。
