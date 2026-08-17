<!-- markdownlint-disable MD013 MD033 MD041 -->

<p align="center">
  <img src="docs/assets/readme/zcode-keysmith-preview.png" alt="Illustrative zcode-keysmith install preview; actual paths and output vary" width="100%">
</p>
<p align="center"><em>Illustrative preview / 示意预览；实际路径与输出以本机 dry-run 为准。</em></p>

<h1 align="center">zcode-keysmith</h1>

<p align="center">先预览、再写入、可撤销的 ZCode App system-role 入口安装器，支持 macOS 与 Windows。</p>

<p align="center">
  <a href="#简体中文">简体中文</a> ·
  <a href="README.en.md">English</a> ·
  <a href="docs/reference.md">Reference</a> ·
  <a href="docs/agent-install.md">智能体安装</a> ·
  <a href="LICENSE">License</a>
</p>

## 简体中文

Keysmith 系列为本地 AI 工具**安全部署、验证和撤销**自定义指令。`zcode-keysmith` 在用户目录安装受管理的 `system-role.md`，经 agent-server wrapper 进入 ZCode runtime 的 system message 路径。**不是** `AGENTS.md` 安装器，也**没有** GitHub Release 或 Desktop 客户端。

> [!WARNING]
> 这会改本机 ZCode 的 **agent-server 入口**，影响之后新启动的会话。不改 App 原包，不读 API key / provider / MCP。支持 macOS 与 Windows 10/11。默认只预览，显式 `--yes` 才写入。先阅读 [`examples/system-role.md`](examples/system-role.md) 和 [`docs/reference.md`](docs/reference.md)。

### 选择哪个 Keysmith

| 项目 | 目标工具 | 部署面 | 稳妥安装 | Desktop |
| --- | --- | --- | --- | --- |
| [codex-keysmith](https://github.com/Jia-Ethan/codex-keysmith) | Codex | 全局 `~/.codex` 指令 | 稳定 CLI Release | 未签名 Beta |
| [claude-keysmith](https://github.com/Jia-Ethan/claude-keysmith) | Claude Code | 项目 / 用户 `CLAUDE.md` import | 源码 CLI | 未签名 Beta |
| [grok-keysmith](https://github.com/Jia-Ethan/grok-keysmith) | Grok Build | 全局 `~/.grok/rules`（不改 `AGENTS.md`） | 稳定 CLI Release | 未签名 Beta |
| **[zcode-keysmith](https://github.com/Jia-Ethan/zcode-keysmith)** | ZCode App | 用户目录 system-role + wrapper | 仅源码 | 无 |

### 安装方式

**只有源码安装。** clone 本仓库后运行 `python3 zcode-keysmith.py`。没有 Release 资产、没有 `pip` / npm、没有本仓库 GUI。

### Windows 快速开始

先完全退出 ZCode，在 PowerShell 中运行：

```powershell
py zcode-keysmith.py install --dry-run
py zcode-keysmith.py install --yes
py zcode-keysmith.py doctor
```

重新打开 ZCode，新建任务后运行：

```powershell
py zcode-keysmith.py verify
```

安装器会自动查找正在运行的 `ZCode.exe`、注册的 App Path 和常见安装目录。自定义安装目录也可以显式指定，例如：

```powershell
py zcode-keysmith.py install --zcode-app "D:\software\zcode" --dry-run
```

Windows 版把入口写入当前用户环境变量，不需要管理员权限；用 ZCode 自带的 Electron/Node 运行缓存 runtime，并用当前 Python 解释器启动受管理 wrapper。

### macOS 快速开始

```bash
git clone https://github.com/Jia-Ethan/zcode-keysmith.git
cd zcode-keysmith
python3 zcode-keysmith.py install --dry-run
python3 zcode-keysmith.py install --yes
python3 zcode-keysmith.py doctor
```

退出并重新打开 ZCode，新建任务后再运行 `python3 zcode-keysmith.py verify`。非默认 App 路径用 `--zcode-app` 或 `ZCODE_APP_PATH`。两端的 `install --dry-run` 都需要能读到可打补丁的本机 runtime。

### 会修改什么

| 路径 | 会发生什么 |
| --- | --- |
| `~/.zcode-keysmith/system-role.md` | 写入归一化后的源提示词 |
| `~/.zcode-keysmith/config.json`、`bin/*` | 受管理配置与 wrapper |
| `~/Library/LaunchAgents/com.jia.zcode-keysmith.env.plist` | macOS 用户 LaunchAgent |
| `HKCU\Environment` 的七个 `ZCODE_*` 值 | Windows 当前用户入口；不需要管理员权限 |
| `cache/`、`logs/` | 运行时缓存与 wrapper 日志；卸载不删 |

不写项目文件，不改 `ZCode.app`。原理见 [`docs/reference.md`](docs/reference.md)。

### 如何撤销

```bash
python3 zcode-keysmith.py uninstall --dry-run
python3 zcode-keysmith.py uninstall --yes
```

Windows 也可以把上面的 `python3` 换成 `py`。macOS 卸载把五个受管理文件改名为 `.bak_*` 并清空当前 launchd 环境；Windows 卸载备份四个受管理文件，并且只在注册表值仍属于本次安装时恢复安装前的用户环境，避免覆盖之后的人工修改。没有 `recover` / `restore`，完整步骤见 [`docs/reference.md`](docs/reference.md)。

### 平台与限制

文档化支持为 macOS + 本机 `ZCode.app`，以及 Windows 10/11 + 本机 `ZCode.exe`。无 Release、无签名包、无 Desktop Beta。推荐 Python 3.10+；Windows 运行期间不能删除安装时使用的 Python。

### 进阶文档 · 贡献 · 系列

原理、字段与卸载残留见 [`docs/reference.md`](docs/reference.md)；智能体安装见 [`docs/agent-install.md`](docs/agent-install.md)。提交前运行 `python3 -m py_compile zcode-keysmith.py` 与 `python3 -m pytest tests -q`。安装器不读取 API key。社区：[LINUX DO](https://linux.do)。核心系列只有对照表中的四个项目。
