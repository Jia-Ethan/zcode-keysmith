# zcode-keysmith GUI 客户端

面向普通用户的 zcode-keysmith 可视化客户端。基于 **Tauri 2 + React + Tailwind 4 + shadcn/ui + Motion**，复用根目录 `zcode-keysmith.py` 的部署、回滚与恢复逻辑，不在 GUI 中重实现文件操作。

> 技术方案与解析规范见 [SPEC.md](./SPEC.md)。

## 运行模式

- **正式安装包**：优先运行 PyInstaller 冻结的内置 CLI sidecar，不依赖系统 Python。
- **开发与高级覆盖**：内置 sidecar 不存在时，可从常见位置/PATH 探测 CLI 可执行文件，最后回退到用户指定的 `.py` 脚本；脚本模式才需要系统 Python。
- 所有参数均由 Rust 以数组传给子进程，不经过 shell；GUI 永不直接修改 `~/.zcode-keysmith`。

## 本地开发

```bash
cd gui
npm ci
npm run tauri dev
```

开发模式可通过环境变量指定根 CLI：

```bash
export ZCODE_KEYSMITH_CLI="$(pwd)/../zcode-keysmith.py"
npm run tauri dev
```

## Sidecar 与安装包

PyInstaller 是构建期依赖，不进入 Node/Rust 运行时依赖：

```bash
python3 -m venv src-tauri/target/sidecar-venv
src-tauri/target/sidecar-venv/bin/python -m pip install -r requirements-build.txt
PYTHON="$PWD/src-tauri/target/sidecar-venv/bin/python" npm run build:sidecar
npm run bundle
```

`npm run build:sidecar` 只支持原生构建，并按当前主机生成 Tauri external binary：

| 主机 | Sidecar | Tauri bundle |
|---|---|---|
| macOS Apple Silicon | `zcode-keysmith-cli-aarch64-apple-darwin` | `.app` + ARM64 `.dmg` |
| Windows x64 | `zcode-keysmith-cli-x86_64-pc-windows-msvc.exe` | current-user NSIS `.exe` |

首版 GUI 为 `0.1.0-beta.1`。Windows 安装器使用 WebView2 download bootstrapper、禁止降级，当前不生成 MSI。

图标以 `src-tauri/icons/source.png` 为唯一源文件。修改后运行：

```bash
npm run tauri icon src-tauri/icons/source.png
```

该命令会同步更新 `.icns`、`.ico`、Windows Square/Store 图标和其他平台尺寸，避免不同安装包使用旧图标。

## 验证

```bash
npm test
npm run build
cargo fmt --manifest-path src-tauri/Cargo.toml -- --check
cargo test --manifest-path src-tauri/Cargo.toml --locked
cargo check --manifest-path src-tauri/Cargo.toml --locked
```

安装包验收还需验证目标架构、GUI/CLI 版本、设置页 source commit 与发布标签 peeled commit 一致、sidecar `--version`、全流程临时目录测试、关闭窗口后无 GUI/sidecar 驻留进程、最终图标、签名和公证状态。Windows candidate CI 会额外隔离用户配置目录与 Codex Desktop 运行目录，验证自动发现只报告包含配置证据的目录、活动 sidecar 进程树完成后排队退出、二次启动回到现有窗口，并通过原生关闭请求和截止时间轮询验证无托盘退出语义。

## 功能

- **状态总览**：CLI 版本、运行时类型、`doctor --json`（managed / wrapper / runtime / env）与 `.bak_` 备份列表。
- **部署向导**：`install --dry-run` 预览后 `install --yes` 确认执行。
- **管理**：`uninstall` 预览/执行。无 recover。无 Scenarios。
- **窗口生命周期**：单实例运行；CLI 调用使用生命周期租约，写操作使用全局互斥锁。
- **设置**：可选 CLI 路径覆盖、默认托管目录、中英双语和主题。GUI 调用不带 `--lang`。

## 目录结构

```text
gui/
├── scripts/build-sidecar.mjs       # 原生 PyInstaller sidecar 构建与版本冒烟
├── requirements-build.txt          # 固定的构建期 PyInstaller 版本
├── src/                            # React 前端与解析器测试
└── src-tauri/
    ├── binaries/                   # 构建时生成，Git 忽略
    ├── tauri.conf.json             # 公共配置、CSP、版本和图标
    ├── tauri.macos.conf.json       # app + dmg
    ├── tauri.windows.conf.json     # NSIS + WebView2
    └── src/cli_runner.rs           # sidecar 优先、脚本回退的进程边界
```

## 核心约束

1. GUI 不直接写 `~/.zcode-keysmith`，所有写操作都由 CLI 完成。
2. 所有 CLI 调用带 `--json`，解析 `zcode-keysmith/v1`；不传 `--lang`。
3. 安装与卸载必须先 `--dry-run` 预览再 `--yes` 确认。
4. 测试与烟雾探测必须使用 `--dry-run` 或临时目录，不得触碰本机活跃 LaunchAgent。
7. 应用不提供托盘驻留：空闲关闭会先建立退出屏障并立即销毁主窗口；任何 Keysmith 后端调用仍在运行时，关闭请求会排队，并在最后一个租约完成后自动退出。
8. 应用只允许一个 GUI 实例；重复启动会复用、恢复并显示现有主窗口，同时请求系统聚焦，不得并行运行第二个桌面进程。
9. 部署和管理操作共用的确认弹窗必须以固定定位居中显示在模糊遮罩上方；玻璃表面样式不得声明布局定位。
