# zcode-keysmith

<p align="center">
  <strong>ZCode App managed true system-role entrypoint.</strong>
</p>

<p align="center">
  <a href="#简体中文">简体中文</a> ·
  <a href="#english">English</a> ·
  <a href="LICENSE">License</a>
</p>

<p align="center">
  <img alt="ZCode App" src="https://img.shields.io/badge/ZCode-App-111111">
  <img alt="system role" src="https://img.shields.io/badge/true-system--role-555555">
  <img alt="Python" src="https://img.shields.io/badge/Python-3.10%2B-3776AB">
  <img alt="License" src="https://img.shields.io/badge/license-MIT-6DB33F">
</p>

> **Status boundary / 状态边界**
>
> `zcode-keysmith` installs a managed `system-role.md` entrypoint for the local ZCode desktop app. It uses ZCode's agent-server environment entrypoint, runs a cached runtime copy, and routes the managed Markdown file into ZCode's runtime `customSystemPrompt` path, which is injected as a system message by the bundled runtime.
>
> `zcode-keysmith` 为本机 ZCode 桌面端安装一条受管理的 `system-role.md` 入口。它通过 ZCode 的 agent-server 环境入口启动 wrapper，运行缓存中的 runtime 副本，并把受管理的 Markdown 文件送入 ZCode runtime 的 `customSystemPrompt` 路径，由 runtime 作为 system message 注入。

## 复制给智能体安装

把下面这段话复制给 Codex、Claude Code、Cursor Agent、ChatGPT Agent 或其他本地智能体。执行流程只有一次确认：确认是否写入持久化入口文件。

```text
请使用 https://github.com/Jia-Ethan/zcode-keysmith 帮我安装 ZCode App 的 managed true system-role entrypoint。

执行要求：
1. 先阅读 README.md 和 zcode-keysmith.py。
2. 运行：python3 zcode-keysmith.py install --dry-run。
3. 向我展示将写入的准确路径，必须包括：
   - ~/.zcode-keysmith/system-role.md
   - ~/.zcode-keysmith/config.json
   - ~/.zcode-keysmith/bin/zcode-agent-wrapper.py
   - ~/.zcode-keysmith/bin/zcode-keysmith-env.sh
   - ~/Library/LaunchAgents/com.jia.zcode-keysmith.env.plist
4. 同时展示将使用的 ZCode runtime 路径、ZCode node command 路径、agent-server args，以及 app_bundle_modified: false。
5. API key、token、MCP 配置、ZCode provider 配置由 ZCode 自身管理；安装器不读取、不保存、不打印这些内容。
6. 只问我一次：是否确认写入以上持久化入口文件。
7. 我确认后，运行：python3 zcode-keysmith.py install --yes。
8. 写入后运行：python3 zcode-keysmith.py doctor。
9. 再运行：python3 zcode-keysmith.py verify。
10. 提醒我重新打开 ZCode，然后新建任务测试“你是谁”。测试后再次运行 verify，确认 wrapper_invoked: true。
```

## 友链 / Community

本项目接受 LINUX DO 社区佬友监督与反馈：[LINUX DO](https://linux.do)

同系列项目 / Same series:

- [codex-keysmith](https://github.com/Jia-Ethan/codex-keysmith) - Codex CLI 本地配置的版本化指令部署工具，支持预览、hook 隔离、中断恢复与分层卸载。 / Versioned instruction deployment for local Codex CLI configuration with preview, hook isolation, interruption recovery, and layered uninstall.
- [claude-keysmith](https://github.com/Jia-Ethan/claude-keysmith) - Claude Code `CLAUDE.md` 的受管理 import-block 安装器，用于本地 Markdown 指令文件。 / Managed Claude Code `CLAUDE.md` import-block installer for local Markdown instruction files.
- [zcode-keysmith](https://github.com/Jia-Ethan/zcode-keysmith) - ZCode App 的受管理 true system-role 入口，通过 agent-server wrapper 将 `system-role.md` 接入 runtime `customSystemPrompt` 的 system-message 路径。 / Managed true system-role entrypoint for ZCode App; an agent-server wrapper routes `system-role.md` into the runtime `customSystemPrompt` system-message path.
- [grok-keysmith](https://github.com/Jia-Ethan/grok-keysmith) - Grok Build 的全局 `AGENTS.md` 指令部署工具，支持 compat/hook 隔离、中断恢复与分层卸载。 / Global `AGENTS.md` instruction deployment for Grok Build with compat/hook isolation, interruption recovery, and layered uninstall.

---

## 简体中文

### 项目定位

`zcode-keysmith` 面向本机 ZCode App 的 system-role 持久化测试场景。

它的目标很直接：把仓库里的 `examples/system-role.md` 安装成用户目录里的受管理版本，然后让 ZCode 新启动的 agent-server 进程读取这份文件，进入 ZCode runtime 的 system 注入路径。

默认写入位置：

```text
~/.zcode-keysmith/system-role.md
~/.zcode-keysmith/config.json
~/.zcode-keysmith/bin/zcode-agent-wrapper.py
~/.zcode-keysmith/bin/zcode-keysmith-env.sh
~/Library/LaunchAgents/com.jia.zcode-keysmith.env.plist
```

安装时会对源提示词做一次格式归一化：如果 `examples/system-role.md` 来自 GLM ChatML 导出，外层 `<|im_start|>system:` / `<|im_end|>` 传输标记会被清理，写入 ZCode 的是 system prompt 主体。

ZCode App 原包保持完整。安装器只写用户目录和用户 LaunchAgent；ZCode 的 API key、provider、MCP、settings 和项目文件继续由 ZCode 自身管理。

### 原理

ZCode 桌面端启动 agent-server 时会读取两个环境变量：

```text
ZCODE_AGENT_SERVER_COMMAND
ZCODE_AGENT_SERVER_ARGS_JSON
```

`zcode-keysmith` 把 `ZCODE_AGENT_SERVER_COMMAND` 指向：

```text
~/.zcode-keysmith/bin/zcode-agent-wrapper.py
```

wrapper 做三件事：

1. 读取 ZCode 自带 runtime：

   ```text
   /Applications/ZCode.app/Contents/Resources/glm/zcode.cjs
   ```

2. 在用户目录缓存一份 runtime 副本，只替换一处 `customSystemPrompt` 入口，让它优先读取：

   ```text
   ~/.zcode-keysmith/system-role.md
   ```

3. 用 ZCode 自带的 Electron node 命令启动缓存 runtime。优先使用 Helper 可执行文件，避免 macOS Dock 把后端 agent-server 识别成另一个前台 ZCode：

   ```text
   /Applications/ZCode.app/Contents/Frameworks/ZCode Helper.app/Contents/MacOS/ZCode Helper <cached-runtime> app-server --stdio
   ```

   如果当前 ZCode 包没有 Helper 可执行文件，安装器才回退到主可执行文件：

   ```text
   /Applications/ZCode.app/Contents/MacOS/ZCode <cached-runtime> app-server --stdio
   ```

ZCode runtime 内部会把 `customSystemPrompt` 放进 `injectionTarget: "system"` 的上下文段。这样，`system-role.md` 进入的是 ZCode runtime 的 system message 路径，而不是普通项目说明文件。

### 安装

先看写入计划：

```bash
python3 zcode-keysmith.py install --dry-run
```

确认后写入：

```bash
python3 zcode-keysmith.py install --yes
```

写入后检查：

```bash
python3 zcode-keysmith.py doctor
python3 zcode-keysmith.py verify
```

安装器会备份已有受管理文件，备份格式为：

```text
<filename>.bak_YYYYMMDD_HHMMSS
```

`--dry-run` 优先级最高。即使同时传入 `install --yes --dry-run`，也只预览写入计划。

### 生效方式

安装器会更新当前 macOS launchd 环境，并写入用户 LaunchAgent，用于后续登录会话恢复同一组环境变量。

已经打开的 ZCode 主进程需要重新打开一次，才能继承新的 agent-server entrypoint。完成安装后按这个顺序验证：

1. 退出 ZCode；
2. 重新打开 ZCode；
3. 新建任务；
4. 输入：`你是谁`；
5. 回到终端运行：

   ```bash
   python3 zcode-keysmith.py verify
   ```

`verify` 里的 `wrapper_invoked: true` 表示 ZCode 已经实际启动过受管理 wrapper。

### 可观测性

`zcode-keysmith` 会记录 wrapper 启动日志：

```text
~/.zcode-keysmith/logs/wrapper-start.jsonl
```

每次 ZCode 通过 wrapper 启动 agent-server 时，日志会追加一行 JSON，包含启动时间、PID、agent-server 参数、缓存 runtime 路径和 system prompt 路径。日志不包含 API key、token、cookie 或 MCP secret。

本地链路检查：

```bash
python3 zcode-keysmith.py verify
```

重点字段：

| 字段 | 含义 |
|---|---|
| `wrapper_smoke` | wrapper 能否本地启动并进入 ZCode CLI help，不发送模型请求 |
| `wrapper_invoked` | 是否存在 wrapper 启动日志 |
| `last_wrapper_start` | 最近一次 wrapper 启动时间 |
| `zcode_agent_override_supported` | ZCode App 是否包含 agent-server 环境入口 |
| `zcode_runtime_patchable` | 当前 runtime 是否匹配 system prompt 入口形态 |
| `zcode_running` | 当前 ZCode 主进程是否正在运行 |

如果 `wrapper_smoke: true` 但 `wrapper_invoked: false`，通常表示受管理入口已经准备好，但 ZCode 还没有重新打开，或还没有新建会触发 agent-server 的任务。

### 状态检查

```bash
python3 zcode-keysmith.py doctor
```

`doctor` 会显示：

- 受管理目录是否存在；
- `system-role.md` 是否存在；
- wrapper 是否存在；
- LaunchAgent 是否存在；
- ZCode runtime 是否存在并匹配当前入口形态；
- launchd 环境变量是否指向受管理入口；
- API key 状态：固定显示为 `not read or stored`。

如果 ZCode 不在 `/Applications/ZCode.app`，可以指定 App 路径：

```bash
python3 zcode-keysmith.py install --zcode-app /path/to/ZCode.app --dry-run
python3 zcode-keysmith.py install --zcode-app /path/to/ZCode.app --yes
python3 zcode-keysmith.py verify --zcode-app /path/to/ZCode.app
```

也可以用环境变量：

```bash
ZCODE_APP_PATH=/path/to/ZCode.app python3 zcode-keysmith.py install --dry-run
```

### 卸载

预览卸载范围：

```bash
python3 zcode-keysmith.py uninstall --dry-run
```

确认后移除受管理入口：

```bash
python3 zcode-keysmith.py uninstall --yes
```

卸载会把受管理文件改名为 `.bak_YYYYMMDD_HHMMSS`，并清理当前 launchd 环境里的 keysmith entrypoint。ZCode App 原包保持完整。

### 项目结构

```text
zcode-keysmith/
├── zcode-keysmith.py
├── examples/
│   └── system-role.md
├── tests/
│   └── test_zcode_keysmith.py
├── .gitignore
├── README.md
└── LICENSE
```

### 验证

```bash
python3 -m py_compile zcode-keysmith.py
python3 -m pytest tests -q
python3 zcode-keysmith.py install --dry-run
python3 zcode-keysmith.py doctor
python3 zcode-keysmith.py verify
```

---

## English

### What this is

`zcode-keysmith` installs a managed true system-role entrypoint for the local ZCode desktop app.

It uses ZCode's agent-server environment entrypoint, runs a cached copy of the bundled runtime, and routes the managed Markdown prompt into ZCode's runtime `customSystemPrompt` path. The bundled runtime injects that section into the system context. On macOS, it prefers the bundled `ZCode Helper` executable as the Electron node command, so the background agent-server is not shown as another foreground ZCode app in the Dock.

Default managed files:

```text
~/.zcode-keysmith/system-role.md
~/.zcode-keysmith/config.json
~/.zcode-keysmith/bin/zcode-agent-wrapper.py
~/.zcode-keysmith/bin/zcode-keysmith-env.sh
~/Library/LaunchAgents/com.jia.zcode-keysmith.env.plist
```

During install, the source prompt is normalized once. If `examples/system-role.md` comes from a GLM ChatML export, the outer `<|im_start|>system:` / `<|im_end|>` transport markers are cleaned, and only the system prompt body is written for ZCode.

The ZCode app bundle remains untouched. API keys, provider settings, MCP settings, and project files stay under ZCode's own management.

### Install

Preview:

```bash
python3 zcode-keysmith.py install --dry-run
```

Write after confirmation:

```bash
python3 zcode-keysmith.py install --yes
```

Inspect state:

```bash
python3 zcode-keysmith.py doctor
python3 zcode-keysmith.py verify
```

After install, reopen ZCode and start a fresh task so the desktop app inherits the managed agent-server entrypoint. Run `verify` again after the fresh task; `wrapper_invoked: true` means ZCode has launched the managed wrapper.

### Agent handoff

Give this to Codex, Claude Code, Cursor Agent, ChatGPT Agent, or another local agent:

```text
Use https://github.com/Jia-Ethan/zcode-keysmith to install the managed true system-role entrypoint for my local ZCode App.

Requirements:
1. Read README.md and zcode-keysmith.py first.
2. Run: python3 zcode-keysmith.py install --dry-run.
3. Show the exact write targets:
   - ~/.zcode-keysmith/system-role.md
   - ~/.zcode-keysmith/config.json
   - ~/.zcode-keysmith/bin/zcode-agent-wrapper.py
   - ~/.zcode-keysmith/bin/zcode-keysmith-env.sh
   - ~/Library/LaunchAgents/com.jia.zcode-keysmith.env.plist
4. Also show the ZCode runtime path, ZCode node command path, agent-server args, and app_bundle_modified: false.
5. API keys, tokens, MCP config, and provider config stay managed by ZCode. The installer must not read, store, or print them.
6. Ask once whether to write the managed entrypoint files.
7. After confirmation, run: python3 zcode-keysmith.py install --yes.
8. Then run: python3 zcode-keysmith.py doctor.
9. Then run: python3 zcode-keysmith.py verify.
10. Tell me to reopen ZCode and test a fresh task with “Who are you?”. After the test, run verify again and confirm wrapper_invoked: true.
```

### Verification

```bash
python3 -m py_compile zcode-keysmith.py
python3 -m pytest tests -q
python3 zcode-keysmith.py install --dry-run
python3 zcode-keysmith.py doctor
python3 zcode-keysmith.py verify
```

### License

MIT
