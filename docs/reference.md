<!-- markdownlint-disable MD013 -->

# 命令参考与可观测性字段 / Command reference and observability fields

日常使用只需要 [`README.md`](../README.md) 的快速开始；本页保存原理、字段表和验证步骤。

---

## 简体中文

### 原理

ZCode 桌面端启动 agent-server 时读取：

```text
ZCODE_AGENT_SERVER_COMMAND
ZCODE_AGENT_SERVER_ARGS_JSON
```

安装器把 `ZCODE_AGENT_SERVER_COMMAND` 指向 `~/.zcode-keysmith/bin/zcode-agent-wrapper.py`。wrapper 读取 ZCode 自带 runtime（默认 `/Applications/ZCode.app/Contents/Resources/glm/zcode.cjs`），在用户目录缓存一份副本，只替换一处 `customSystemPrompt` 入口，使其优先读取 `~/.zcode-keysmith/system-role.md`，再用 ZCode 自带 Electron node 启动缓存 runtime。优先使用 Helper 可执行文件，避免 Dock 把后端识别成另一个前台 ZCode。

ZCode runtime 会把 `customSystemPrompt` 放进 `injectionTarget: "system"` 的上下文段，因此这份文件走的是 system message 路径，不是项目说明文件。若源文件来自 GLM ChatML 导出，外层 `<|im_start|>system:` / `<|im_end|>` 会在写入前被清理。

本工具**没有** GitHub Release、Desktop 客户端、`pip` / npm 安装包、`--recover` / `--restore` 或分层卸载。安装面只有 clone 后运行 `zcode-keysmith.py`。目标平台是 macOS + 本机 `ZCode.app`；Linux / Windows 没有文档化支持。非 Darwin 会跳过 `launchctl` 注入。

`install --dry-run` 仍会读取源提示词并检查本机 runtime 是否可打补丁。本机找不到可识别的 `ZCode.app` 时，预览会失败。可用 `--zcode-app` 或 `ZCODE_APP_PATH` 指定路径。

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

### 卸载残留

`uninstall --yes` 把这五个受管理文件改名为 `.bak_YYYYMMDD_HHMMSS`：`system-role.md`、`config.json`、wrapper、env 脚本、LaunchAgent plist，并用 `launchctl unsetenv` 清空当前会话的 Keysmith 入口。它不删除 `~/.zcode-keysmith/` 目录本身，也不删除 `cache/`、`logs/` 或历史备份。

没有 `recover` / `restore` 子命令。手工回滚时，按卸载输出中的 `removed:` 路径恢复同一批 `.bak_*` 文件，然后运行恢复后的 `~/.zcode-keysmith/bin/zcode-keysmith-env.sh`（或退出登录后重新登录）以重新加载 launchd 环境；退出并重新打开 ZCode，新建任务后运行 `python3 zcode-keysmith.py verify`。只挪回文件不会恢复已被清空的当前 launchd 环境。

安装还会创建 `~/.zcode-keysmith/cache/` 与 `~/.zcode-keysmith/logs/`。wrapper 运行时另写缓存 runtime 副本和 `logs/wrapper-start.jsonl`。这些路径不在 install 的五个逐文件原子写入目标里，卸载也不清理它们；五个文件之间不是一个整体事务。

### 项目结构

```text
zcode-keysmith/
├── zcode-keysmith.py
├── examples/
│   └── system-role.md
├── tests/
│   └── test_zcode_keysmith.py
├── docs/
│   ├── reference.md
│   ├── agent-install.md
│   └── legacy/
├── .gitignore
├── README.md / README.en.md
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

### How it works

The ZCode desktop app reads these variables when starting agent-server:

```text
ZCODE_AGENT_SERVER_COMMAND
ZCODE_AGENT_SERVER_ARGS_JSON
```

The installer points `ZCODE_AGENT_SERVER_COMMAND` at `~/.zcode-keysmith/bin/zcode-agent-wrapper.py`. The wrapper reads the bundled ZCode runtime (default `/Applications/ZCode.app/Contents/Resources/glm/zcode.cjs`), caches a copy under the user directory, patches only the `customSystemPrompt` entrypoint so it prefers `~/.zcode-keysmith/system-role.md`, and launches that cached runtime with ZCode's own Electron node. It prefers the Helper executable so Dock does not treat the backend as another foreground ZCode.

The runtime places `customSystemPrompt` into a context segment with `injectionTarget: "system"`, so the file enters the system-message path rather than a project instruction file. GLM ChatML wrappers (`<|im_start|>system:` / `<|im_end|>`) are stripped before write.

This project has **no** GitHub Release, Desktop client, pip/npm package, `--recover` / `--restore`, or layered uninstall. The only install surface is cloning the repo and running `zcode-keysmith.py`. The documented platform is macOS plus a local `ZCode.app`; Linux / Windows are not documented. Non-Darwin hosts skip `launchctl` injection.

`install --dry-run` still reads the source prompt and checks that the local runtime is patchable. Preview fails if no recognizable `ZCode.app` is present. Pass `--zcode-app` or `ZCODE_APP_PATH` for a non-default location.

### Observability

`zcode-keysmith` records wrapper start events:

```text
~/.zcode-keysmith/logs/wrapper-start.jsonl
```

Every time ZCode launches agent-server through the wrapper, one JSON line is appended with the start time, PID, agent-server args, cached runtime path, and system prompt path. The log never contains an API key, token, cookie, or MCP secret.

```bash
python3 zcode-keysmith.py verify
```

Key fields:

| Field | Meaning |
|---|---|
| `wrapper_smoke` | Whether the wrapper can launch locally and reach ZCode CLI help, without sending a model request |
| `wrapper_invoked` | Whether a wrapper start log entry exists |
| `last_wrapper_start` | Timestamp of the most recent wrapper start |
| `zcode_agent_override_supported` | Whether the ZCode app bundle exposes the agent-server environment entrypoint |
| `zcode_runtime_patchable` | Whether the current runtime matches the expected system-prompt entrypoint shape |
| `zcode_running` | Whether the ZCode main process is currently running |

If `wrapper_smoke: true` but `wrapper_invoked: false`, the managed entrypoint is usually ready but ZCode has not been reopened yet, or no task has triggered agent-server since.

### Status check

```bash
python3 zcode-keysmith.py doctor
```

Shows whether the managed directory, `system-role.md`, wrapper, and LaunchAgent exist; whether the ZCode runtime matches the expected entrypoint shape; whether launchd environment variables point at the managed entrypoint; and API key status, always shown as `not read or stored`.

Custom app path:

```bash
python3 zcode-keysmith.py install --zcode-app /path/to/ZCode.app --dry-run
python3 zcode-keysmith.py install --zcode-app /path/to/ZCode.app --yes
python3 zcode-keysmith.py verify --zcode-app /path/to/ZCode.app
# or
ZCODE_APP_PATH=/path/to/ZCode.app python3 zcode-keysmith.py install --dry-run
```

### Uninstall leftovers

`uninstall --yes` renames these five managed files to `.bak_YYYYMMDD_HHMMSS`: `system-role.md`, `config.json`, the wrapper, the env script, and the LaunchAgent plist, then clears the current Keysmith entrypoint with `launchctl unsetenv`. It does not delete `~/.zcode-keysmith/` itself, nor `cache/`, `logs/`, or historical backups.

There is no `recover` / `restore` subcommand. For a manual rollback, restore one matching set of `.bak_*` files using the `removed:` paths printed by uninstall, then run the restored `~/.zcode-keysmith/bin/zcode-keysmith-env.sh` (or log out and back in) to reload the launchd environment. Quit and reopen ZCode, start a fresh task, and run `python3 zcode-keysmith.py verify`. Moving the files back alone does not restore the current launchd environment cleared by uninstall.

Install also creates `~/.zcode-keysmith/cache/` and `~/.zcode-keysmith/logs/`. The wrapper later writes a cached runtime copy and `logs/wrapper-start.jsonl`. Those paths are not among the five individually atomic install targets and are not cleaned by uninstall; the five files are not one cross-file transaction.

### Verification

```bash
python3 -m py_compile zcode-keysmith.py
python3 -m pytest tests -q
python3 zcode-keysmith.py install --dry-run
python3 zcode-keysmith.py doctor
python3 zcode-keysmith.py verify
```
