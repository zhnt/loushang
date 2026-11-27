# Loushang Full 安装包

在仓库根目录运行对应平台的脚本。每次从当前工作树编译 GUI 和 Web，再组装 TUI、Mux、AppHost、锁定的 Python 依赖和私有 CPython。未提交的源码可以正常打包。同一产品版本可以重复构建，校验通过的新包会替换同名产物。

| 目标 | 原生构建环境 | 目标系统与验证边界 | Actions |
| --- | --- | --- | --- |
| Linux x86_64 DEB | Ubuntu 24.04+ | Ubuntu 24.04 Runner 安装、运行及卸载验收 | `ubuntu-24.04` |
| Linux aarch64 DEB | Ubuntu 24.04+ ARM64 | Ubuntu 24.04 ARM64 Runner 安装、运行及卸载验收，DEB 架构名为 `arm64` | `ubuntu-24.04-arm` |
| Linux x86_64 RPM | Fedora 43+ x86_64 | Fedora 43 容器，通过 Managed Service 运行后端，使用 Xvfb 检查 GUI | `ubuntu-24.04` |
| Linux aarch64 RPM | Fedora 43+ ARM64 | Fedora 43 ARM64 容器，通过 Managed Service 运行后端，使用 Xvfb 检查 GUI | `ubuntu-24.04-arm` |
| Windows x86_64 NSIS | Windows x64，MSVC | Windows Server 2022 静默安装、运行及卸载验收 | `windows-2022` |
| Windows x86_64 MSI | Windows x64，MSVC、WiX | Windows Server 2022 静默安装、同版本修复、运行及卸载验收 | `windows-2022` |
| macOS x86_64 PKG | 原生 Intel Mac，Xcode | macOS 15 Intel 安装、运行及卸载验收，Mach-O 审计目标为 macOS 12 | `macos-15-intel` |
| macOS aarch64 PKG | 原生 Apple Silicon Mac，Xcode | macOS 15 Apple Silicon 安装、运行及卸载验收，Mach-O 审计目标为 macOS 12 | `macos-15` |

Windows ARM64 的 NSIS 和 MSI 暂缓。当前锁定的 `cryptography==48.0.1` 缺少可用的官方 Windows ARM64 wheel。进展和原生预检记录见 [#939](https://github.com/zhnt/loushang/issues/939)。

### 准备构建环境

安装 Git、uv、Node 24、npm 11、Rust 1.98.1。脚本使用仓库配置、`uv.lock`、npm 和 Cargo 锁文件，按 `.python-version` 准备 CPython。重复构建继续使用 uv、npm 下载缓存及 Cargo 增量产物。

- Ubuntu 使用 `build-essential desktop-file-utils dpkg-dev file libayatana-appindicator3-dev libssl-dev librsvg2-dev libwebkit2gtk-4.1-dev libxdo-dev pkg-config xdg-utils`。
- Fedora 使用 `gcc gcc-c++ make rpm-build desktop-file-utils pkgconf-pkg-config webkit2gtk4.1-devel gtk3-devel openssl-devel librsvg2-devel libayatana-appindicator-gtk3-devel libxdo-devel`。
- Windows 安装 Visual Studio Build Tools 的 C++ 桌面开发组件及 Windows SDK。选择原生 MSVC Rust 工具链。Tauri 准备对应 NSIS / WiX 3 工具。MSI 需要系统启用 VBScript。
- macOS 安装并选择 Xcode 或命令行工具。编译目标为当前架构，部署目标设为 12.0。

### 本地构建

```sh
uv run --no-project --python 3.11 python scripts/build/build_full_linux.py
uv run --no-project --python 3.11 python scripts/build/build_full_linux.py --format rpm
uv run --no-project --python 3.11 python scripts/build/build_full_windows.py
uv run --no-project --python 3.11 python scripts/build/build_full_windows.py --format msi
uv run --no-project --python 3.11 python scripts/build/build_full_windows.py --format all
uv run --no-project --python 3.11 python scripts/build/build_full_macos.py
```

Linux 和 macOS 可显式指定 `--arch x86_64` 或 `--arch aarch64`，须与构建机一致。Windows Full 构建要求原生 x86_64。`--output` 默认是仓库的 `dist/packages/`。`--help` 显示平台参数。产物含安装包与 `.sha256`，PKG 额外输出原生依赖清单。安装包版本使用 `pyproject.toml` 中的 `major.minor.patch`，包内 manifest 记录实际源码提交、工作树状态和构建时间。

| 格式 | 文件名示例 |
| --- | --- |
| DEB | `loushang_0.1.0_amd64.deb`、`loushang_0.1.0_arm64.deb` |
| RPM | `loushang-0.1.0-1.fc43.x86_64.rpm`、`loushang-0.1.0-1.fc43.aarch64.rpm` |
| NSIS | `loushang-0.1.0-x64-setup.exe` |
| MSI | `loushang-0.1.0-x64.msi` |
| PKG | `loushang-0.1.0-x64.pkg`、`loushang-0.1.0-arm64.pkg` |

将安装包与同名 `.sha256` 文件放在同一目录。Linux 用 `sha256sum -c <文件名>.sha256`，macOS 用 `shasum -a 256 -c <文件名>.sha256`。Windows 用 `Get-FileHash -Algorithm SHA256 <文件名>` 计算并与文件中的摘要比对。

### 安装与重新安装

先退出 GUI、TUI 和 Web，再执行 `loushang-mux service stop`。更换文件前应确认这些进程已退出。用户配置、认证和 Session 数据独立于程序目录。升级和标准卸载会保留这些数据。NSIS 卸载时应保留默认的数据保留选项。

- **DEB** 用 `sudo apt install ./loushang_0.1.0_amd64.deb` 安装，用 `sudo apt install --reinstall ./loushang_0.1.0_amd64.deb` 同版本重装。卸载用 `sudo apt remove loushang`。缺失的 WebKitGTK 等由 APT 安装。此前的 `0.1.0+gui.<commit>` 预览包在 APT 中高于 `0.1.0`。如需覆盖旧预览包，先停服务，再显式使用 `apt install --allow-downgrades ./loushang_0.1.0_amd64.deb`。
- **RPM** 选择本机架构的文件。例如 x86_64 用 `sudo dnf install ./loushang-0.1.0-1.fc43.x86_64.rpm` 安装，用 `sudo rpm -U --replacepkgs ./loushang-0.1.0-1.fc43.x86_64.rpm` 同版本重装。卸载用 `sudo dnf remove --no-autoremove loushang`。
- **Windows** 同一格式重复运行安装器，MSI 可在提升权限的终端用 `msiexec /i loushang-0.1.0-x64.msi REINSTALL=ALL REINSTALLMODE=amus` 强制刷新同版本文件。NSIS 默认安装到当前用户目录，MSI 默认安装到 Program Files。卸载可在 Windows「已安装的应用」中选择 Loushang，也可对 MSI 使用 `msiexec /x .\loushang-0.1.0-x64.msi`。更换格式前先卸载现有版本，两种安装器均会阻止静默覆盖同一套程序。缺少 WebView2 时安装器会从微软下载。离线机器可先安装[微软 Evergreen Standalone Runtime](https://developer.microsoft.com/microsoft-edge/webview2/#download-section)。未签名的 Loushang 安装器可能触发 SmartScreen。
- **macOS** 用安装器打开 PKG，或执行 `sudo installer -pkg ./loushang-0.1.0-x64.pkg -target /`。同版本重装重复此步骤。应用使用 ad-hoc 签名，PKG 未签名及公证，受 Gatekeeper 与管理策略限制。卸载时先停进程，再删除 `/Applications/loushang-gui.app` 及指向其 `Contents/MacOS` 的 `/usr/local/bin/loushang{,-gui,-web,-mux,-host}` 链接，最后执行 `sudo pkgutil --forget ai.loushang.full`。参见[安装验收](../gui/macos-package.md)。

从旧 Linux 安装版升级前，先用旧版 `loushang-mux service stop`，并执行
`systemctl --user disable --now loushang-host.service`。升级移除旧 unit 后执行
`systemctl --user daemon-reload`。旧版 macOS 同样先用旧版命令停止并注销
launchd 作业，再换包。新版通过现有 Managed Service 启动 AppHost，并沿用用户配置和会话。

### GitHub Actions

使用 `--ref` 选择包含当前工作流定义的分支，用 `source_ref` 指定待构建的 Branch、Tag 或 Commit。一次工作流只解析一次源码 Commit，所有 Runner 构建同一 SHA。

```sh
gh workflow run gui-package.yml --repo zhnt/loushang --ref main \
  -f source_ref=main -f target=linux-aarch64-deb

gh workflow run gui-package.yml --repo zhnt/loushang --ref main \
  -f source_ref=main -f target=all
```

`target` 接受表中各个目标，例如 `linux-x86_64-rpm`、`windows-x86_64-msi`、`macos-aarch64-pkg`。`all` 构建表中的八个安装包。Windows x64 的两个安装器在 `all` 模式共享组件编译与运行时准备，各自验收并上传产物。每份安装器 Artifact 含安装包、校验文件和验收日志，保留 14 天。

Fedora 的构建容器和验收容器均运行在与目标相同架构的 Runner 上。验收环境使用独立的 D-Bus 会话和 Xvfb 检查 GUI，并通过 Managed Service 启停后端。RPM 的验证范围为 Fedora 43，真实桌面交互以及其他 RPM 发行版待验证。

在 Actions 运行详情的 Artifacts 区域选择目标及源码 SHA 对应的产物，也可将运行编号及 40 位源码 SHA 赋给 `run_id` 和 `source_sha`，再用 GitHub CLI 下载。

```sh
gh run download "$run_id" --repo zhnt/loushang \
  --name "loushang-linux-aarch64-deb-$source_sha" --dir dist/downloads
```

[GitHub 托管 Runner 列表](https://docs.github.com/en/actions/reference/runners/github-hosted-runners) · [Tauri Windows 安装选项](https://v2.tauri.app/distribute/windows-installer/#webview2-installation-options)

### Linux 本地验收

切换默认管理入口前，在 Ubuntu 26.10 x86_64 构建，在独立 Ubuntu 26.04.1 x86_64 桌面虚机验收。已验证首次安装、含未提交源码的同版本重建和重装，从低版本测试包升级、进程运行时拦截替换与卸载，以及停机后卸载保留用户数据。GUI 窗口、TUI 命令入口、systemd Host 启停、Web 和 AppHost 连接均通过基本运行验证。
