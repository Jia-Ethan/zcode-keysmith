<!-- markdownlint-disable MD013 -->

# 命令参考与内部机制 / Command reference and internals

日常使用只需要 [`README.md`](../README.md) 的「快速开始」；本页是完整字段、入口机制和维护者验证细节。

机器契约：`--json` 输出 `zcode-keysmith/v1`，字段为 schema / operation / mode / ok / actions / warnings / blockers / exit_status / error。`install` / `uninstall` 在没有 `--yes` 时只预览；`--dry-run` 与 `--yes` 同时出现时 `--dry-run` 优先。

> README 只保留用户面的快速开始与撤销入口。wrapper 原理、可观测性字段、卸载残留与手工回滚，统一在本页维护。

---

## 简体中文

### 安装面

- 稳妥安装使用 GitHub Release `v0.3.1` 的 `zcode-keysmith-v0.3.1.zip`，先用同级 `SHA256SUMS` 校验，再确认 `--version` 为 `0.3.1`。该版本把指令写到 `~/.zcode-keysmith/system-role.md`，进入 ZCode agent-server 的 system message 路径。ZCode 3.12+ 不劫持 agent-server command，改为备份并补丁 `glm/zcode.cjs`（`app_bundle_modified: true`，卸载还原）；更早版本仍走 wrapper，不改原包。`v0.3.0` 的 wrapper 路径对 3.12 不可用。
- 稳定版是源码压缩包：没有独立二进制、没有 `pip` / npm、没有已发布 Desktop 安装包。
- 内置提示词来源为 [`examples/system-role.md`](../examples/system-role.md)，SHA-256 `a62de09eb5d918e649f997c4fb18c3447f6f246bc284250ca04d4c6532c5a0a0`。

### 原理

ZCode 3.12 桌面端启动时会先做独立 session storage 准备。官方配套 Agent 带 `supportsStorageStartup`；一旦设置 `ZCODE_AGENT_SERVER_COMMAND`，这条标记会丢失，启动页停在「当前配置的 Agent 不支持独立存储准备」。

因此安装器按本机 App 选择注入方式：

- **ZCode 3.12+（asar 含 `supportsStorageStartup`）**：不覆盖 agent-server command，也不设置 `NODE_OPTIONS`。打包 Electron 会删掉父进程 `NODE_OPTIONS`，preload 进不了 agent，破甲会掉。安装器备份 vendor `glm/zcode.cjs`，原地把 `customSystemPrompt` 改成 **优先读** `~/.zcode-keysmith/system-role.md`，官方 runtime 仍负责 `--prepare-storage`。安装时清掉旧的 `ZCODE_AGENT_SERVER_COMMAND` / `ZCODE_AGENT_SERVER_ARGS_JSON` / Keysmith `NODE_OPTIONS`。卸载把 runtime 从备份还原。
- **更早的 ZCode**：仍读取

```text
ZCODE_AGENT_SERVER_COMMAND
ZCODE_AGENT_SERVER_ARGS_JSON
```

macOS 把 command 指向 `~/.zcode-keysmith/bin/zcode-agent-wrapper.py`。Windows 把 command 指向当前 Python，并把 wrapper 路径作为第一个参数。wrapper 缓存一份 runtime 副本，只替换 `customSystemPrompt` 入口。Windows wrapper 显式绑定父进程 stdin/stdout/stderr。

ZCode runtime 会把 `customSystemPrompt` 放进 `injectionTarget: "system"` 的上下文段，因此这份文件走的是 system message 路径，不是项目说明文件。若源文件来自 GLM ChatML 导出，外层 `<|im_start|>system:` / `<|im_end|>` 会在写入前被清理。

当前公开树版本 `0.3.1` 的安装面是 Release zip：`zcode-keysmith-v0.3.1.zip` + `SHA256SUMS`。没有独立二进制、Desktop 客户端、`pip` / npm 安装包。目标平台是 macOS + 本机 `ZCode.app`，或 Windows 10/11 + 本机 `ZCode.exe`。macOS 通过 `launchctl` 激活；Windows 写入 `HKCU\Environment` 并广播环境变更，不需要管理员权限。Linux 没有文档化支持。

`install --dry-run` 仍会读取源提示词并检查本机 runtime 是否可打补丁。本机找不到可识别的 ZCode 安装时，预览会失败。可用 `--zcode-app` 或 `ZCODE_APP_PATH` 指定路径。

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
- macOS LaunchAgent 或 Windows 持久用户环境是否存在；
- ZCode runtime 是否存在并匹配当前入口形态；
- macOS launchd 或 Windows `HKCU\Environment` 是否指向受管理入口；
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

Windows 自定义路径示例：

```powershell
py zcode-keysmith.py install --zcode-app "D:\software\zcode" --dry-run
```

### 卸载残留

macOS 的 `uninstall --yes` 把受管理文件改名为 `.bak_YYYYMMDD_HHMMSS`：`system-role.md`、`config.json`、wrapper、preload、env 脚本、LaunchAgent plist，并清掉当前会话的 Keysmith 入口。若本次安装补丁过 `glm/zcode.cjs`，先从 `runtime_original_backup` 还原。残留的 Keysmith `NODE_OPTIONS --require` 会 unset。Windows 备份对应受管理文件，并按 `config.json` 保存的安装前状态恢复当前用户环境；若某个值在安装后被其他工具或用户改过，则保持该值不动。两端都不删除 `~/.zcode-keysmith/` 目录本身，也不删除 `cache/`、`logs/` 或历史备份。

没有 `recover` / `restore` 子命令。macOS 手工回滚时，按卸载输出中的 `removed:` 路径恢复同一批 `.bak_*` 文件，然后运行恢复后的 `~/.zcode-keysmith/bin/zcode-keysmith-env.sh`（或退出登录后重新登录）以重新加载 launchd 环境。Windows 正常卸载已经自动恢复安装前的环境；如需手工恢复文件，可运行恢复后的 `~/.zcode-keysmith/bin/zcode-keysmith-env.ps1` 重新激活 Keysmith。最后退出并重新打开 ZCode，再运行 `verify`。

安装还会创建 `~/.zcode-keysmith/cache/` 与 `~/.zcode-keysmith/logs/`。wrapper / preload 运行时另写缓存 runtime 副本和 `logs/wrapper-start.jsonl`。这些路径不在 install 的逐文件原子写入目标里，卸载也不清理它们；受管理文件之间不是一个整体事务。

### 验证

```bash
python3 -m py_compile zcode-keysmith.py
python3 -m pytest tests -q
python3 zcode-keysmith.py install --dry-run
python3 zcode-keysmith.py doctor
python3 zcode-keysmith.py verify
python3 scripts/build_release.py --output-dir dist
```

`scripts/build_release.py` 产出 `zcode-keysmith-v<VERSION>.zip` 与 `SHA256SUMS`，不含 GUI / Desktop。打 tag 后把这两份文件挂到对应 GitHub Release。

---

## English

### Install surface

- Install from GitHub Release `v0.3.1`: download `zcode-keysmith-v0.3.1.zip`, verify it with the matching `SHA256SUMS`, then confirm `--version` is `0.3.1`. That version writes `~/.zcode-keysmith/system-role.md` into ZCode agent-server's system-message path. ZCode 3.12+ does not hijack the agent-server command; it backs up and patches `glm/zcode.cjs` (`app_bundle_modified: true`, restored on uninstall). Older builds still use the wrapper and leave the vendor runtime untouched. The `v0.3.0` wrapper path is incompatible with 3.12.
- The stable package is a source zip: no standalone binary, no pip/npm package, no published Desktop.
- Bundled prompt: [`examples/system-role.md`](../examples/system-role.md), SHA-256 `a62de09eb5d918e649f997c4fb18c3447f6f246bc284250ca04d4c6532c5a0a0`.

### How it works

ZCode 3.12 desktop startup prepares isolated session storage first. The official agent carries `supportsStorageStartup`. Setting `ZCODE_AGENT_SERVER_COMMAND` drops that flag and leaves the app on “the configured Agent does not support isolated storage preparation.”

The installer therefore chooses an injection mode from the local app:

- **ZCode 3.12+ (asar contains `supportsStorageStartup`)**: do not override the agent-server command, and do not set `NODE_OPTIONS`. Packaged Electron deletes parent `NODE_OPTIONS`, so a preload never reaches the agent and Keysmith does not inject. The installer backs up vendor `glm/zcode.cjs` and patches `customSystemPrompt` so it **prefers** `~/.zcode-keysmith/system-role.md`. The official runtime still handles `--prepare-storage`. Install clears leftover `ZCODE_AGENT_SERVER_COMMAND` / `ZCODE_AGENT_SERVER_ARGS_JSON` / Keysmith `NODE_OPTIONS`. Uninstall restores the runtime from the backup.
- **Older ZCode**: still reads

```text
ZCODE_AGENT_SERVER_COMMAND
ZCODE_AGENT_SERVER_ARGS_JSON
```

On macOS the command is `~/.zcode-keysmith/bin/zcode-agent-wrapper.py`. On Windows the command is the current Python interpreter and the wrapper path is the first argument. The wrapper caches a runtime copy and patches only `customSystemPrompt`. The Windows wrapper binds the parent stdin/stdout/stderr handles.

The runtime places `customSystemPrompt` into a context segment with `injectionTarget: "system"`, so the file enters the system-message path rather than a project instruction file. GLM ChatML wrappers (`<|im_start|>system:` / `<|im_end|>`) are stripped before write.

The current public tree `0.3.1` ships as a Release zip: `zcode-keysmith-v0.3.1.zip` plus `SHA256SUMS`. There is no standalone binary, Desktop client, or pip/npm package. Documented platforms are macOS with a local `ZCode.app`, and Windows 10/11 with a local `ZCode.exe`. Windows activation uses current-user environment values under `HKCU\Environment` and requires no administrator access. Linux is not documented.

`install --dry-run` still reads the source prompt and checks that the local runtime is patchable. Preview fails if no recognizable ZCode installation is present. Pass `--zcode-app` or `ZCODE_APP_PATH` for a non-default location.

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

Shows whether the managed directory, `system-role.md`, wrapper, and platform activation state exist; whether the ZCode runtime matches the expected entrypoint shape; whether persistent environment values point at the managed entrypoint; and API key status, always shown as `not read or stored`.

Custom app path:

```bash
python3 zcode-keysmith.py install --zcode-app /path/to/ZCode.app --dry-run
python3 zcode-keysmith.py install --zcode-app /path/to/ZCode.app --yes
python3 zcode-keysmith.py verify --zcode-app /path/to/ZCode.app
# or
ZCODE_APP_PATH=/path/to/ZCode.app python3 zcode-keysmith.py install --dry-run
```

Windows custom path:

```powershell
py zcode-keysmith.py install --zcode-app "D:\software\zcode" --dry-run
```

### Uninstall leftovers

On macOS, `uninstall --yes` restores a patched `glm/zcode.cjs` from `runtime_original_backup` when `app_bundle_modified` is true, then renames the managed files (`system-role.md`, `config.json`, wrapper, preload, env script, LaunchAgent) and clears the current Keysmith entrypoint, including leftover Keysmith `NODE_OPTIONS`. On Windows, it backs up the managed files and restores pre-install user environment values only where the current value is still owned by Keysmith; later manual or third-party changes are preserved. Neither platform deletes `~/.zcode-keysmith/`, `cache/`, `logs/`, or historical backups.

There is no `recover` / `restore` subcommand. On macOS, manual rollback restores one matching `.bak_*` set and runs the restored `zcode-keysmith-env.sh`. Windows normal uninstall already restores pre-install environment values; a manually restored install can be reactivated with `zcode-keysmith-env.ps1`. Quit and reopen ZCode, start a fresh task, and run `verify` afterward.

Install also creates `~/.zcode-keysmith/cache/` and `~/.zcode-keysmith/logs/`. The wrapper or preload later writes a cached runtime copy and `logs/wrapper-start.jsonl`. Those paths are outside the individually atomic managed-file writes and are not cleaned by uninstall; the managed files do not form one cross-file transaction.

### Verification

```bash
python3 -m py_compile zcode-keysmith.py
python3 -m pytest tests -q
python3 zcode-keysmith.py install --dry-run
python3 zcode-keysmith.py doctor
python3 zcode-keysmith.py verify
python3 scripts/build_release.py --output-dir dist
```

`scripts/build_release.py` writes `zcode-keysmith-v<VERSION>.zip` and `SHA256SUMS`. It does not include GUI / Desktop. After tagging, attach those two files to the matching GitHub Release.
