<!-- markdownlint-disable MD013 -->

# 命令参考与内部机制 / Command reference and internals

日常使用只需要 [`README.md`](../README.md) 的「快速开始」；本页是完整字段、入口机制和维护者验证细节。

机器契约：`--json` 输出 `zcode-keysmith/v1`，字段为 schema / operation / mode / ok / actions / warnings / blockers / exit_status / error。`install` / `uninstall` / `watch` 在没有 `--yes` 时只预览；`--dry-run` 与 `--yes` 同时出现时 `--dry-run` 优先。

> README 只保留用户面的快速开始与撤销入口。wrapper 原理、可观测性字段、卸载残留与手工回滚，统一在本页维护。

---

## 简体中文

### 安装面

- 目前可下载的是 GitHub Release `v0.3.3` 的 `zcode-keysmith-v0.3.3.zip` 与同级 `SHA256SUMS`，支持 ZCode 3.12 与 3.14。安装器把指令写到 `~/.zcode-keysmith/system-role.md`，进入 ZCode agent-server 的 system message 路径。ZCode 3.12+ 不劫持 agent-server command，改为备份并补丁 `glm/zcode.cjs`（`app_bundle_modified: true`，卸载还原）；更早版本仍走 wrapper，不改原包。`v0.3.1` 无法识别 ZCode 3.14 的 runtime 锚点；`v0.3.0` 的 wrapper 路径对 3.12 不可用。
- 目前公开的稳定入口仍是源码压缩包：没有独立二进制、没有 `pip` / npm。仓库里有第一份 unsigned 桌面候选（GUI `0.1.0-beta.1`）；`desktop-v0.1.0-beta.1` tag 尚未打，不要把它当成已发布安装包。
- 内置提示词来源为 [`examples/system-role.md`](../examples/system-role.md)，SHA-256 `30e7de01b1a453d38cb1fa38bc8f4bb26eeaf8eccafada1aa178df1a1cf1c9e1`。

### 原理

ZCode 3.12 桌面端启动时会先做独立 session storage 准备。官方配套 Agent 带 `supportsStorageStartup`；一旦设置 `ZCODE_AGENT_SERVER_COMMAND`，这条标记会丢失，启动页停在「当前配置的 Agent 不支持独立存储准备」。

因此安装器按本机 App 选择注入方式：

- **ZCode 3.12+（asar 含 `supportsStorageStartup`）**：不覆盖 agent-server command，也不设置 `NODE_OPTIONS`。打包 Electron 会删掉父进程 `NODE_OPTIONS`，preload 进不了 agent，破甲会掉。安装器备份 vendor `glm/zcode.cjs`，原地把 `customSystemPrompt` 改成 **优先读** `~/.zcode-keysmith/system-role.md`，官方 runtime 仍负责 `--prepare-storage`。3.14 的配置对象在 `systemPrompt` 和 `language` 之间插入了 `workflowActor`，CLI-prefix 守卫也改了形态；安装器同时识别 3.12 / 3.14 锚点，且仅在无 `workflowActor` 时注入受管提示词，保留原生互斥守卫和 workflow 上下文。安装时清掉旧的 `ZCODE_AGENT_SERVER_COMMAND` / `ZCODE_AGENT_SERVER_ARGS_JSON` / Keysmith `NODE_OPTIONS`。卸载把 runtime 从备份还原。macOS 的 LaunchAgent 在登录时仍 `setenv`，并监视 `glm/zcode.cjs` / `ZCode.app`：官方 Squirrel/ShipIt 换包、文件稳定后，用同一套已知锚点重打补丁并备份新的官方原文件；若 ZCode 已用未打补丁的进程起来，打完后退出并再打开一次。锚点不认识时不硬打，写 `logs/auto-repatch.json` 并通知升级 Keysmith。监视用的 LaunchAgent 如果离开当前 gui 会话，launchd 要到下次登录才重新加载 `~/Library/LaunchAgents`。因此同一安装再放一个没有 `WatchPaths` 的 `com.jia.zcode-keysmith.rearm`：每 60 秒 `launchctl print` 监视进程，不在就 `bootstrap` 它的 plist；挂回去时 `RunAtLoad` 立刻再跑一次 `watch`。这个任务不 `bootout` 监视进程，也不监视 App 包。`doctor` 报告 `rearm_loaded`。Windows 监视不在本版。
- **更早的 ZCode**：仍读取

```text
ZCODE_AGENT_SERVER_COMMAND
ZCODE_AGENT_SERVER_ARGS_JSON
```

macOS 把 command 指向 `~/.zcode-keysmith/bin/zcode-agent-wrapper.py`。Windows 把 command 指向当前 Python，并把 wrapper 路径作为第一个参数。wrapper 缓存一份 runtime 副本，只替换 `customSystemPrompt` 入口。Windows wrapper 显式绑定父进程 stdin/stdout/stderr。

ZCode runtime 会把 `customSystemPrompt` 放进 `injectionTarget: "system"` 的上下文段，因此这份文件走的是 system message 路径，不是项目说明文件。若源文件来自 GLM ChatML 导出，外层 `<|im_start|>system:` / `<|im_end|>` 会在写入前被清理。

当前源码版本 `0.3.3`，公开 zip 安装面是 `zcode-keysmith-v0.3.3.zip` + `SHA256SUMS`。没有独立 CLI 二进制、没有 `pip` / npm。桌面客户端源码在 `gui/`，本轮目标是 unsigned `desktop-v0.1.0-beta.1`，tag 尚未存在。目标平台是 macOS + 本机 `ZCode.app`，或 Windows 10/11 + 本机 `ZCode.exe`。macOS 通过 `launchctl` 激活；Windows 写入 `HKCU\Environment` 并广播环境变更，不需要管理员权限。Linux 没有文档化支持。

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
- 上次因官方更新自动重打的结果：`last_auto_repatch` 为 `success` / `skip` / `unknown_hook` / `none`（以及 `last_auto_repatch_status`、`last_auto_repatch_reason`）；
- API key 状态：固定显示为 `not read or stored`。

macOS 上也可手动跑一次监视路径：

```bash
python3 zcode-keysmith.py watch --dry-run
python3 zcode-keysmith.py watch --yes
```

`watch` 等 runtime 文件稳定后再动手；已打过补丁则 `skip`；认识 3.12/3.14 锚点则重打并备份；不认识则 `unknown_hook` 且不改 App。监视 LaunchAgent 在 `WatchPaths` 变化和每 5 分钟 `StartInterval` 时调用同一条命令。`com.jia.zcode-keysmith.rearm` 没有 `WatchPaths`，每 60 秒确认监视进程仍在本次登录的 launchd 里，不在就重新 `bootstrap`。

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

macOS 的 `uninstall --yes` 先 `bootout` rearm LaunchAgent，再 `bootout` 监视 LaunchAgent，把受管理文件改名为 `.bak_YYYYMMDD_HHMMSS`：`system-role.md`、`config.json`、wrapper、preload、env 脚本、安装器副本、两个 LaunchAgent plist、rearm 脚本，并清掉当前会话的 Keysmith 入口。若本次安装补丁过 `glm/zcode.cjs`，先从 `runtime_original_backup` 还原。残留的 Keysmith `NODE_OPTIONS --require` 会 unset。Windows 备份对应受管理文件，并按 `config.json` 保存的安装前状态恢复当前用户环境；若某个值在安装后被其他工具或用户改过，则保持该值不动。两端都不删除 `~/.zcode-keysmith/` 目录本身，也不删除 `cache/`、`logs/` 或历史备份。

`recover` 预览或修复当前 runtime-patch 安装：ShipIt 换包后的未打补丁 `glm/zcode.cjs`、缺失的 CLI-prefix / OVERRIDE / MEMORY skip follow-up，以及 plist 仍在但已离开本次 GUI 会话的 LaunchAgent。默认只预览；`--yes` 才写入。锚点不认识或 plist 缺失时失败关闭，需要 `install --yes`。卸载回滚仍按下面的 `.bak_*` 路径手工恢复。

macOS 手工回滚时，按卸载输出中的 `removed:` 路径恢复同一批 `.bak_*` 文件，然后运行恢复后的 `~/.zcode-keysmith/bin/zcode-keysmith-env.sh`（或退出登录后重新登录）以重新加载 launchd 环境。Windows 正常卸载已经自动恢复安装前的环境；如需手工恢复文件，可运行恢复后的 `~/.zcode-keysmith/bin/zcode-keysmith-env.ps1` 重新激活 Keysmith。最后退出并重新打开 ZCode，再运行 `verify`。

runtime-patch 模式下 `verify` 默认跳过 wrapper `--help` smoke（wrapper 不参与启动）。判据是 `zcode_runtime_patched` 与 `competing_context`。需要检查 leftover wrapper 时加 `--smoke`。

安装还会创建 `~/.zcode-keysmith/cache/` 与 `~/.zcode-keysmith/logs/`。wrapper / preload 运行时另写缓存 runtime 副本和 `logs/wrapper-start.jsonl`。这些路径不在 install 的逐文件原子写入目标里，卸载也不清理它们；受管理文件之间不是一个整体事务。

### 验证

```bash
python3 -m py_compile zcode-keysmith.py
python3 -m pytest tests -q
python3 zcode-keysmith.py install --dry-run
python3 zcode-keysmith.py doctor
python3 zcode-keysmith.py verify
python3 zcode-keysmith.py recover --dry-run
python3 scripts/build_release.py --output-dir dist
```

`scripts/build_release.py` 产出 `zcode-keysmith-v<VERSION>.zip` 与 `SHA256SUMS`，不含 GUI / Desktop。打 CLI tag 后把这两份文件挂到对应 GitHub Release。桌面候选由 `.github/workflows/desktop-candidate.yml` 产出 unsigned DMG / NSIS artifact，不在本脚本里。

---

## English

### Install surface

- The published GitHub Release is `v0.3.3` (`zcode-keysmith-v0.3.3.zip` and `SHA256SUMS`), which supports ZCode 3.12 and 3.14. The installer writes `~/.zcode-keysmith/system-role.md` into ZCode agent-server's system-message path. ZCode 3.12+ does not hijack the agent-server command; it backs up and patches `glm/zcode.cjs` (`app_bundle_modified: true`, restored on uninstall). Older builds still use the wrapper and leave the vendor runtime untouched. `v0.3.1` does not recognize the ZCode 3.14 runtime anchors; the `v0.3.0` wrapper path is incompatible with 3.12.
- The published entry is still a source zip: no standalone CLI binary, no pip/npm package. The tree also carries a first unsigned desktop candidate (GUI `0.1.0-beta.1`); the `desktop-v0.1.0-beta.1` tag does not exist yet.
- Bundled prompt: [`examples/system-role.md`](../examples/system-role.md), SHA-256 `30e7de01b1a453d38cb1fa38bc8f4bb26eeaf8eccafada1aa178df1a1cf1c9e1`.

### How it works

ZCode 3.12 desktop startup prepares isolated session storage first. The official agent carries `supportsStorageStartup`. Setting `ZCODE_AGENT_SERVER_COMMAND` drops that flag and leaves the app on “the configured Agent does not support isolated storage preparation.”

The installer therefore chooses an injection mode from the local app:

- **ZCode 3.12+ (asar contains `supportsStorageStartup`)**: do not override the agent-server command, and do not set `NODE_OPTIONS`. Packaged Electron deletes parent `NODE_OPTIONS`, so a preload never reaches the agent and Keysmith does not inject. The installer backs up vendor `glm/zcode.cjs` and patches `customSystemPrompt` so it **prefers** `~/.zcode-keysmith/system-role.md`. The official runtime still handles `--prepare-storage`. 3.14 inserts `workflowActor` between `systemPrompt` and `language` and changes the CLI-prefix guard; the installer matches both anchors but injects only when `workflowActor` is absent, preserving the native mutex and workflow context. Install clears leftover `ZCODE_AGENT_SERVER_COMMAND` / `ZCODE_AGENT_SERVER_ARGS_JSON` / Keysmith `NODE_OPTIONS`. Uninstall restores the runtime from the backup. On macOS the LaunchAgent still `setenv`s at login and also watches `glm/zcode.cjs` / `ZCode.app`. After Squirrel/ShipIt swaps the bundle and the files settle, it re-applies the same known-anchor patch and backs up the new official original. If ZCode is already running unpatched, it quits and reopens the app. Unknown anchors are left untouched; `logs/auto-repatch.json` records the skip and a notification asks you to upgrade Keysmith. If the watch LaunchAgent leaves the current GUI session, launchd does not reload `~/Library/LaunchAgents` until the next login. The same install adds `com.jia.zcode-keysmith.rearm` with no `WatchPaths`: every 60 seconds it runs `launchctl print` on the watcher and `bootstrap`s its plist when the job is gone. `RunAtLoad` on that watcher then runs `watch` immediately. The rearm job never `bootout`s the watcher and does not watch the app bundle. `doctor` reports `rearm_loaded`. Windows watching is out of scope for this version.
- **Older ZCode**: still reads

```text
ZCODE_AGENT_SERVER_COMMAND
ZCODE_AGENT_SERVER_ARGS_JSON
```

On macOS the command is `~/.zcode-keysmith/bin/zcode-agent-wrapper.py`. On Windows the command is the current Python interpreter and the wrapper path is the first argument. The wrapper caches a runtime copy and patches only `customSystemPrompt`. The Windows wrapper binds the parent stdin/stdout/stderr handles.

The runtime places `customSystemPrompt` into a context segment with `injectionTarget: "system"`, so the file enters the system-message path rather than a project instruction file. GLM ChatML wrappers (`<|im_start|>system:` / `<|im_end|>`) are stripped before write.

The current source version is `0.3.3`. The published zip is `zcode-keysmith-v0.3.3.zip` plus `SHA256SUMS`. There is no standalone CLI binary or pip/npm package. Desktop source lives in `gui/`; this round targets unsigned `desktop-v0.1.0-beta.1`, but that tag is not cut yet. Documented platforms are macOS with a local `ZCode.app`, and Windows 10/11 with a local `ZCode.exe`. Windows activation uses current-user environment values under `HKCU\Environment` and requires no administrator access. Linux is not documented.

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

Shows whether the managed directory, `system-role.md`, wrapper, and platform activation state exist; whether the ZCode runtime matches the expected entrypoint shape; whether persistent environment values point at the managed entrypoint; the last auto-repatch after an official update (`success` / `skip` / `unknown_hook` / `none`); and API key status, always shown as `not read or stored`.

On macOS you can also run the watcher by hand:

```bash
python3 zcode-keysmith.py watch --dry-run
python3 zcode-keysmith.py watch --yes
```

`watch` waits for the runtime file to settle, skips an already-patched runtime, re-patches known 3.12/3.14 anchors (and backs up the new original), and leaves unknown hooks untouched. The watch LaunchAgent runs the same command on `WatchPaths` changes and every 5 minutes via `StartInterval`. `com.jia.zcode-keysmith.rearm` has no `WatchPaths`; every 60 seconds it checks that the watcher is still loaded in this login session and bootstraps it again when it is not.

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

On macOS, `uninstall --yes` boots the rearm LaunchAgent out first and then the watch LaunchAgent, restores a patched `glm/zcode.cjs` from `runtime_original_backup` when `app_bundle_modified` is true, then renames the managed files (`system-role.md`, `config.json`, wrapper, preload, env script, installer copy, both LaunchAgent plists, and the rearm script) and clears the current Keysmith entrypoint, including leftover Keysmith `NODE_OPTIONS`. On Windows, it backs up the managed files and restores pre-install user environment values only where the current value is still owned by Keysmith; later manual or third-party changes are preserved. Neither platform deletes `~/.zcode-keysmith/`, `cache/`, `logs/`, or historical backups.

`recover` previews or repairs a runtime-patch install: an unpatched `glm/zcode.cjs` after ShipIt, missing CLI-prefix / OVERRIDE / MEMORY follow-ups, and LaunchAgents whose plists are still on disk but have left this GUI session. Preview is the default; `--yes` writes. Unrecognized anchors or missing plists fail closed and need `install --yes`. Uninstall rollback still uses the `.bak_*` paths below.

On macOS, manual rollback restores one matching `.bak_*` set and runs the restored `zcode-keysmith-env.sh`. Windows normal uninstall already restores pre-install environment values; a manually restored install can be reactivated with `zcode-keysmith-env.ps1`. Quit and reopen ZCode, start a fresh task, and run `verify` afterward.

In runtime-patch mode `verify` skips wrapper `--help` smoke by default (the wrapper is unused). Success is `zcode_runtime_patched` plus `competing_context`. Pass `--smoke` to exercise a leftover wrapper.

Install also creates `~/.zcode-keysmith/cache/` and `~/.zcode-keysmith/logs/`. The wrapper or preload later writes a cached runtime copy and `logs/wrapper-start.jsonl`. Those paths are outside the individually atomic managed-file writes and are not cleaned by uninstall; the managed files do not form one cross-file transaction.

### Verification

```bash
python3 -m py_compile zcode-keysmith.py
python3 -m pytest tests -q
python3 zcode-keysmith.py install --dry-run
python3 zcode-keysmith.py doctor
python3 zcode-keysmith.py verify
python3 zcode-keysmith.py recover --dry-run
python3 scripts/build_release.py --output-dir dist
```

`scripts/build_release.py` writes `zcode-keysmith-v<VERSION>.zip` and `SHA256SUMS`. It does not include GUI / Desktop. After tagging a CLI release, attach those two files to the matching GitHub Release. Desktop candidates come from `.github/workflows/desktop-candidate.yml` as unsigned DMG / NSIS artifacts, not from this script.
