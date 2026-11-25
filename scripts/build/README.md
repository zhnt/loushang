# Loushang Full 安装包

在仓库根目录运行对应平台的脚本。每次从当前工作树编译 GUI 和 Web，再组装 TUI、Mux、AppHost、锁定的 Python 依赖和私有 CPython。未提交的源码可以正常打包。同一产品版本可以重复构建，校验通过的新包会替换同名产物。

| 目标 | 原生构建环境 | 目标系统与验证边界 | Actions |
| --- | --- | --- | --- |
| Linux x86_64 DEB | Ubuntu 24.04+ | 已验收 Ubuntu 26.04.1 x86_64。更早版本的可安装性取决于构建机产生的 ABI 和包依赖 | `ubuntu-24.04` |
| Linux aarch64 DEB | Ubuntu 24.04+ ARM64 | 有构建入口，待原生构建及安装验收 | `ubuntu-24.04-arm` |
| Linux x86_64 / aarch64 RPM | Fedora 43+，原生架构 | 有构建入口，待同版本 Fedora 原生构建及安装验收。尚未证明兼容 RHEL | 无标准 Fedora runner |
| Windows x86_64 NSIS | Windows x64，MSVC | 旧入口已通过 Windows 11 x64 安装验收。新入口待原生构建与验收。Windows 10 未验收为支持下限 | `windows-2022` |
| Windows x86_64 MSI | Windows x64，MSVC、WiX | 有构建入口，待原生构建及安装验收 | `windows-2022` |
| Windows aarch64 NSIS / MSI | Windows ARM64 | 锁定的 `cryptography==48.0.1` 缺少原生可用轮子，构建前拒绝 | 未启用 |
| macOS x86_64 / aarch64 PKG | 原生 Intel / Apple Silicon Mac，Xcode | PKG 与 Mach-O 审计目标为 macOS 12。此前 Intel 包已构建；新入口和 Apple Silicon 安装待验收 | `macos-15-intel` / `macos-15` |

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
uv run --no-project --python 3.11 python scripts/build/build_full_macos.py
```

可显式指定 `--arch x86_64` 或 `--arch aarch64`，须与构建机一致。`--output` 默认是仓库的 `dist/packages/`。`--help` 显示平台参数。产物含安装包与 `.sha256`，PKG 额外输出原生依赖清单。安装包版本使用 `pyproject.toml` 中的 `major.minor.patch`，包内 manifest 记录实际源码提交、工作树状态和构建时间。

### 安装与重新安装

先退出 GUI、TUI 和 Web，再执行 `loushang-mux service stop`。更换文件前应确认这些进程已退出。用户配置、认证和会话放在独立用户目录，升级或卸载时保留。

- **DEB** 用 `sudo apt install ./loushang_0.1.0_amd64.deb` 安装，用 `sudo apt install --reinstall ./loushang_0.1.0_amd64.deb` 同版本重装。卸载用 `sudo apt remove loushang`。缺失的 WebKitGTK 等由 APT 安装。更新 unit 后可执行 `systemctl --user daemon-reload`。此前的 `0.1.0+gui.<commit>` 预览包在 APT 中高于 `0.1.0`。如需覆盖旧预览包，先停服务，再显式使用 `apt install --allow-downgrades ./loushang_0.1.0_amd64.deb`。
- **RPM** 用 `sudo dnf install ./loushang-0.1.0-1*.rpm` 安装，用 `sudo rpm -U --replacepkgs ./loushang-0.1.0-1*.rpm` 同版本重装。卸载用 `sudo dnf remove loushang`。
- **Windows** 同一格式重复运行安装器，MSI 可在提升权限的终端用 `msiexec /i loushang-0.1.0-x64.msi REINSTALL=ALL REINSTALLMODE=amus` 强制刷新同版本文件。NSIS 默认当前用户目录，MSI 默认 Program Files。更换格式前先卸载现有版本，保持同一套程序文件只由一个安装器管理，勿把两种格式指向同一安装目录。缺少 WebView2 时安装器会从微软下载。离线机器可先安装[微软 Evergreen Standalone Runtime](https://developer.microsoft.com/microsoft-edge/webview2/#download-section)。未签名的 Loushang 安装器可能触发 SmartScreen。
- **macOS** 用安装器打开 PKG，或执行 `sudo installer -pkg ./loushang-0.1.0-x64.pkg -target /`。同版本重装重复此步骤。应用使用 ad-hoc 签名，PKG 未签名及公证，受 Gatekeeper 与管理策略限制。卸载时先停进程，再删除 `/Applications/loushang-gui.app` 及指向其 `Contents/MacOS` 的 `/usr/local/bin/loushang{,-gui,-web,-mux,-host}` 链接，最后执行 `sudo pkgutil --forget ai.loushang.full`。参见[安装验收](../gui/macos-package.md)。

### GitHub Actions

手动工作流沿用 GitHub 已注册的 `gui-package.yml`。使用 `--ref` 选择包含新版
工作流的分支，用 `source_ref` 指定待构建的 Branch、Tag 或 Commit。默认分支上的
旧版定义仍接受旧参数。

```sh
gh workflow run gui-package.yml --repo zhnt/loushang --ref feature/gui-package-verification \
  -f source_ref=feature/gui-package-verification -f target=all
```

`target` 可选 `linux-x86_64-deb`、`windows-x86_64-nsis`、`macos-x86_64-pkg`
及 `all`。三个任务使用同一解析后的 Commit，分别安装、覆盖安装、使用安装后的
程序验证并卸载。每个 Artifact 含对应安装包、校验文件和验收日志，保留 14 天。
其他平台入口仍可在原生机器上使用，远程验收留到下一阶段。

[GitHub 托管 Runner 列表](https://docs.github.com/en/actions/reference/runners/github-hosted-runners) · [Tauri Windows 安装选项](https://v2.tauri.app/distribute/windows-installer/#webview2-installation-options)

### Linux 本地验收

在 Ubuntu 26.10 x86_64 构建，在独立 Ubuntu 26.04.1 x86_64 桌面虚机验收。已验证首次安装、含未提交源码的同版本重建和重装，从低版本测试包升级、进程运行时拦截替换与卸载，以及停机后卸载保留用户数据。GUI 窗口、TUI 命令入口、systemd Host 启停、Web 和 AppHost 连接均通过基本运行验证。
