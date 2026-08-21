#!/usr/bin/env python3
"""Install a managed true-system prompt entrypoint for the local ZCode App.

The installer leaves the ZCode app bundle untouched. It installs a small wrapper
that ZCode can launch through its agent-server environment override. The wrapper
runs a cached copy of the bundled ZCode runtime with one narrow patch: when the
runtime builds its context, it reads the managed system-role.md as the main
runtime system prompt unless ZCode has already provided an explicit one.
"""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
import plistlib
import platform
import shutil
import stat
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

REPO_ROOT = Path(__file__).resolve().parent
__version__ = "0.1.1"
VERSION = __version__
DEFAULT_SOURCE_SYSTEM_FILE = REPO_ROOT / "examples" / "system-role.md"
DEFAULT_MANAGED_DIR = Path.home() / ".zcode-keysmith"
DEFAULT_SYSTEM_FILE_NAME = "system-role.md"
DEFAULT_CONFIG_FILE_NAME = "config.json"
DEFAULT_WRAPPER_NAME = "zcode-agent-wrapper.py"
DEFAULT_ENV_SCRIPT_NAME = "zcode-keysmith-env.sh"
DEFAULT_WINDOWS_ENV_SCRIPT_NAME = "zcode-keysmith-env.ps1"
DEFAULT_LAUNCH_AGENT_LABEL = "com.jia.zcode-keysmith.env"
DEFAULT_LAUNCH_AGENT_NAME = f"{DEFAULT_LAUNCH_AGENT_LABEL}.plist"
DEFAULT_ZCODE_APP = Path("/Applications/ZCode.app")
DEFAULT_ZCODE_RUNTIME = DEFAULT_ZCODE_APP / "Contents" / "Resources" / "glm" / "zcode.cjs"
DEFAULT_ZCODE_HELPER_NODE_COMMAND = DEFAULT_ZCODE_APP / "Contents" / "Frameworks" / "ZCode Helper.app" / "Contents" / "MacOS" / "ZCode Helper"
DEFAULT_ZCODE_NODE_COMMAND = DEFAULT_ZCODE_HELPER_NODE_COMMAND
FALLBACK_ZCODE_NODE_COMMAND = DEFAULT_ZCODE_APP / "Contents" / "MacOS" / "ZCode"
DEFAULT_AGENT_ARGS_JSON = '["app-server","--stdio"]'
PATCH_NEEDLE = "customSystemPrompt:this.config.systemPrompt,language:"
MANAGED_ENV_KEYS = (
    "ZCODE_AGENT_SERVER_COMMAND",
    "ZCODE_AGENT_SERVER_ARGS_JSON",
    "ZCODE_KEYSMITH_SYSTEM_FILE",
    "ZCODE_KEYSMITH_ORIGINAL",
    "ZCODE_KEYSMITH_NODE_COMMAND",
    "ZCODE_KEYSMITH_CACHE_DIR",
    "ZCODE_KEYSMITH_LOG_DIR",
)


class KeysmithError(Exception):
    """User-facing installer error."""


@dataclass(frozen=True)
class InstallPaths:
    managed_dir: Path
    system_file: Path
    config_file: Path
    wrapper: Path
    env_script: Path
    launch_agent: Path | None
    log_dir: Path
    cache_dir: Path
    wrapper_log: Path


@dataclass(frozen=True)
class InstallPlan:
    paths: InstallPaths
    source_system_file: Path
    zcode_runtime: Path
    node_command: Path
    activate: bool


def expand_path(value: str | Path) -> Path:
    return Path(value).expanduser().resolve()


def default_launch_agent_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / DEFAULT_LAUNCH_AGENT_NAME


def build_paths(managed_dir: Path, launch_agent: Path | None = None) -> InstallPaths:
    managed_dir = expand_path(managed_dir)
    bin_dir = managed_dir / "bin"
    is_windows = platform.system() == "Windows"
    return InstallPaths(
        managed_dir=managed_dir,
        system_file=managed_dir / DEFAULT_SYSTEM_FILE_NAME,
        config_file=managed_dir / DEFAULT_CONFIG_FILE_NAME,
        wrapper=bin_dir / DEFAULT_WRAPPER_NAME,
        env_script=bin_dir / (DEFAULT_WINDOWS_ENV_SCRIPT_NAME if is_windows else DEFAULT_ENV_SCRIPT_NAME),
        launch_agent=None if is_windows else (expand_path(launch_agent) if launch_agent else default_launch_agent_path()),
        log_dir=managed_dir / "logs",
        cache_dir=managed_dir / "cache",
        wrapper_log=managed_dir / "logs" / "wrapper-start.jsonl",
    )


def resolve_zcode_bundle_paths(zcode_app: Path) -> tuple[Path, Path]:
    app = expand_path(zcode_app)
    if app.is_file() and app.name.lower() == "zcode.exe":
        app = app.parent
    windows_runtime = app / "resources" / "glm" / "zcode.cjs"
    windows_node = app / "ZCode.exe"
    if windows_runtime.exists() or windows_node.exists() or platform.system() == "Windows":
        return windows_runtime.resolve(), windows_node.resolve()
    runtime = app / "Contents" / "Resources" / "glm" / "zcode.cjs"
    helper_node = app / "Contents" / "Frameworks" / "ZCode Helper.app" / "Contents" / "MacOS" / "ZCode Helper"
    main_node = app / "Contents" / "MacOS" / "ZCode"
    node_command = helper_node if helper_node.exists() else main_node
    return runtime.resolve(), node_command.resolve()


def windows_running_zcode_paths() -> list[Path]:
    """Return executable paths for running ZCode processes without extra dependencies."""
    if platform.system() != "Windows":
        return []

    from ctypes import wintypes

    TH32CS_SNAPPROCESS = 0x00000002
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.c_size_t),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", wintypes.LONG),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", wintypes.WCHAR * 260),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
    kernel32.Process32FirstW.restype = wintypes.BOOL
    kernel32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
    kernel32.Process32NextW.restype = wintypes.BOOL
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.QueryFullProcessImageNameW.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.LPWSTR,
        ctypes.POINTER(wintypes.DWORD),
    ]
    kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    snapshot = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snapshot == INVALID_HANDLE_VALUE or snapshot is None:
        return []
    paths: list[Path] = []
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(entry)
        has_entry = kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
        while has_entry:
            if entry.szExeFile.lower() == "zcode.exe":
                process = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, entry.th32ProcessID)
                if process:
                    try:
                        size = wintypes.DWORD(32768)
                        buffer = ctypes.create_unicode_buffer(size.value)
                        if kernel32.QueryFullProcessImageNameW(process, 0, buffer, ctypes.byref(size)):
                            paths.append(Path(buffer.value))
                    finally:
                        kernel32.CloseHandle(process)
            has_entry = kernel32.Process32NextW(snapshot, ctypes.byref(entry))
    finally:
        kernel32.CloseHandle(snapshot)
    return paths


def windows_registry_zcode_paths() -> list[Path]:
    if platform.system() != "Windows":
        return []
    import winreg

    paths: list[Path] = []
    locations = (
        (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\App Paths\ZCode.exe"),
        (winreg.HKEY_LOCAL_MACHINE, r"Software\Microsoft\Windows\CurrentVersion\App Paths\ZCode.exe"),
    )
    for hive, subkey in locations:
        try:
            with winreg.OpenKey(hive, subkey) as key:
                value, _ = winreg.QueryValueEx(key, None)
        except OSError:
            continue
        if isinstance(value, str) and value.strip():
            paths.append(Path(value.strip().strip('"')))
    return paths


def discover_zcode_app_path() -> Path:
    env_app = os.environ.get("ZCODE_APP_PATH")
    candidates: list[Path] = []
    if env_app:
        candidates.append(Path(env_app))
    if platform.system() == "Windows":
        candidates.extend(windows_running_zcode_paths())
        candidates.extend(windows_registry_zcode_paths())
        path_executable = shutil.which("ZCode.exe")
        if path_executable:
            candidates.append(Path(path_executable))
        local_app_data = os.environ.get("LOCALAPPDATA")
        program_files = os.environ.get("ProgramFiles")
        if local_app_data:
            candidates.extend([Path(local_app_data) / "Programs" / "ZCode", Path(local_app_data) / "ZCode"])
        if program_files:
            candidates.append(Path(program_files) / "ZCode")
    else:
        candidates.append(DEFAULT_ZCODE_APP)
    if platform.system() == "Darwin":
        completed = subprocess.run(
            ["mdfind", "kMDItemCFBundleIdentifier == 'dev.zcode.app'"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if completed.returncode == 0:
            candidates.extend(Path(line.strip()) for line in completed.stdout.splitlines() if line.strip())
    for candidate in candidates:
        expanded = candidate.expanduser()
        if expanded.is_file() and expanded.name.lower() == "zcode.exe":
            expanded = expanded.parent
        if expanded.exists() and expanded.is_dir():
            runtime, node = resolve_zcode_bundle_paths(expanded)
            if runtime.exists() and node.exists():
                return expanded.resolve()
    if platform.system() == "Windows":
        local_app_data = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local")))
        return (local_app_data / "Programs" / "ZCode").resolve()
    return DEFAULT_ZCODE_APP.resolve()


def zcode_app_from_runtime(runtime_path: Path) -> Path | None:
    runtime = expand_path(runtime_path)
    if runtime.parent.name.lower() == "glm" and runtime.parent.parent.name.lower() == "resources":
        windows_app = runtime.parent.parent.parent
        if (windows_app / "ZCode.exe").exists() or platform.system() == "Windows":
            return windows_app
    for parent in runtime.parents:
        if parent.name.endswith(".app"):
            return parent
    return None


def app_supports_agent_server_override(zcode_app: Path | None) -> bool:
    if not zcode_app:
        return False
    app_asar = (
        zcode_app / "resources" / "app.asar"
        if (zcode_app / "resources" / "app.asar").exists() or platform.system() == "Windows"
        else zcode_app / "Contents" / "Resources" / "app.asar"
    )
    if not app_asar.exists() or not app_asar.is_file():
        return False
    try:
        overlap = b""
        needle = b"ZCODE_AGENT_SERVER_COMMAND"
        with app_asar.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                data = overlap + chunk
                if needle in data:
                    return True
                overlap = data[-(len(needle) - 1) :]
    except OSError:
        return False
    return False


def is_zcode_running() -> bool:
    if platform.system() == "Windows":
        return bool(windows_running_zcode_paths())
    if platform.system() != "Darwin":
        return False
    completed = subprocess.run(["pgrep", "-x", "ZCode"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    return completed.returncode == 0


def normalize_system_prompt_content(content: str) -> str:
    """Normalize common exported system-prompt wrappers into prompt body text."""
    leading = content[: len(content) - len(content.lstrip())]
    text = content.lstrip()
    prefixes = [
        "<|im_start|>system:<project_instructions>",
        "<|im_start|>system:",
        "<|im_start|>system",
    ]
    for prefix in prefixes:
        if text.startswith(prefix):
            rest = text[len(prefix) :]
            if prefix.endswith("<project_instructions>"):
                text = "<project_instructions>" + rest
            else:
                text = rest.lstrip("\r\n")
            break
    stripped = text.rstrip()
    if stripped.endswith("<|im_end|>"):
        text = stripped[: -len("<|im_end|>")].rstrip() + "\n"
    return leading + text


def read_required_text(path: Path, label: str) -> str:
    if not path.exists():
        raise KeysmithError(f"{label} not found: {path}")
    if not path.is_file():
        raise KeysmithError(f"{label} is not a regular file: {path}")
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise KeysmithError(f"{label} must be UTF-8: {path}") from exc
    except OSError as exc:
        raise KeysmithError(f"Could not read {label}: {path}\nReason: {exc}") from exc
    if not text.strip():
        raise KeysmithError(f"{label} is empty: {path}")
    return text


def read_system_prompt_source(path: Path) -> str:
    text = normalize_system_prompt_content(read_required_text(path, "source system prompt"))
    if not text.strip():
        raise KeysmithError(f"source system prompt is empty after normalization: {path}")
    return text


def ensure_runtime_patchable(runtime_path: Path) -> None:
    runtime = read_required_text(runtime_path, "ZCode runtime")
    if PATCH_NEEDLE not in runtime:
        raise KeysmithError(
            "ZCode runtime entrypoint shape was not recognized.\n"
            f"Runtime: {runtime_path}\n"
            "The installer expected the runtime context builder anchor used by current ZCode releases."
        )


def build_system_prompt_expression(system_file: str) -> str:
    system_file_json = json.dumps(system_file, ensure_ascii=False)
    return (
        "(this.config.systemPrompt&&this.config.systemPrompt.trim()?this.config.systemPrompt:"
        "(()=>{try{let e=process.env.ZCODE_KEYSMITH_SYSTEM_FILE||"
        + system_file_json
        + ";let t=require(\"node:fs\");return t.existsSync(e)?t.readFileSync(e,\"utf8\"):void 0}catch{return void 0}})())"
    )


def build_patched_runtime_text(original_runtime: str, system_file: str) -> str:
    if PATCH_NEEDLE not in original_runtime:
        raise KeysmithError("ZCode runtime patch anchor not found")
    replacement = "customSystemPrompt:" + build_system_prompt_expression(system_file) + ",language:"
    return original_runtime.replace(PATCH_NEEDLE, replacement, 1)


def reserve_backup_path(path: Path) -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = path.with_name(f"{path.name}.bak_{stamp}")
    counter = 1
    while True:
        try:
            descriptor = os.open(backup, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            backup = path.with_name(f"{path.name}.bak_{stamp}_{counter}")
            counter += 1
            continue
        os.close(descriptor)
        return backup


def backup_existing(path: Path) -> Path | None:
    if not path.exists():
        return None
    backup = reserve_backup_path(path)
    try:
        path.replace(backup)
    except Exception:
        backup.unlink(missing_ok=True)
        raise
    return backup


@contextmanager
def operation_lock(paths: InstallPaths):
    paths.managed_dir.mkdir(parents=True, exist_ok=True)
    lock_path = paths.managed_dir / ".operation.lock"
    handle = lock_path.open("a+b")
    if lock_path.stat().st_size == 0:
        handle.write(b"0")
        handle.flush()
    try:
        if os.name == "nt":
            import msvcrt

            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (OSError, BlockingIOError) as exc:
        handle.close()
        raise KeysmithError(f"another zcode-keysmith operation is already running: {lock_path}") from exc
    try:
        yield
    finally:
        try:
            if os.name == "nt":
                import msvcrt

                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()


def atomic_write_text(path: Path, content: str, mode: int | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=str(path.parent),
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        handle.write(content)
        tmp = Path(handle.name)
    if mode is not None:
        tmp.chmod(mode)
    tmp.replace(path)
    if mode is not None:
        path.chmod(mode)


def atomic_write_plist(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "wb",
        dir=str(path.parent),
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        plistlib.dump(payload, handle, sort_keys=False)
        tmp = Path(handle.name)
    tmp.replace(path)


def rollback_replaced_files(replaced: list[tuple[Path, Path | None]]) -> list[str]:
    errors: list[str] = []
    for target, previous in reversed(replaced):
        try:
            if previous is None:
                target.unlink(missing_ok=True)
            else:
                previous.replace(target)
        except OSError as exc:
            errors.append(f"{target}: {exc}")
    return errors


def restore_replaced_files(replaced: list[tuple[Path, Path | None]]) -> None:
    errors = rollback_replaced_files(replaced)
    if errors:
        raise KeysmithError("file rollback failed:\n" + "\n".join(errors))


def install_managed_files(
    plan: InstallPlan,
    system_prompt: str,
    config: str,
) -> tuple[list[Path], list[tuple[Path, Path | None]]]:
    payloads: list[tuple[Path, str, int | None]] = [
        (plan.paths.system_file, system_prompt, None),
        (plan.paths.config_file, config, None),
        (plan.paths.wrapper, render_wrapper(plan), 0o755),
        (plan.paths.env_script, render_env_script(plan), 0o755),
    ]
    staged: list[tuple[Path, Path]] = []
    replaced: list[tuple[Path, Path | None]] = []
    backups: list[Path] = []
    try:
        for target, content, mode in payloads:
            target.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                "w",
                encoding="utf-8",
                dir=str(target.parent),
                prefix=f".{target.name}.",
                suffix=".install.tmp",
                delete=False,
            ) as handle:
                handle.write(content)
                tmp = Path(handle.name)
            if mode is not None:
                tmp.chmod(mode)
            staged.append((target, tmp))

        if plan.paths.launch_agent is not None:
            target = plan.paths.launch_agent
            target.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                "wb",
                dir=str(target.parent),
                prefix=f".{target.name}.",
                suffix=".install.tmp",
                delete=False,
            ) as handle:
                plistlib.dump(render_launch_agent(plan), handle, sort_keys=False)
                tmp = Path(handle.name)
            staged.append((target, tmp))

        for target, tmp in staged:
            previous = reserve_backup_path(target) if target.exists() else None
            if previous is not None:
                try:
                    target.replace(previous)
                except Exception:
                    previous.unlink(missing_ok=True)
                    raise
            replaced.append((target, previous))
            tmp.replace(target)
            if previous is not None:
                backups.append(previous)
        return backups, replaced
    except Exception as exc:
        rollback_errors = rollback_replaced_files(replaced)
        if rollback_errors:
            raise KeysmithError(
                f"{exc}\nFile rollback failed:\n" + "\n".join(rollback_errors)
            ) from exc
        raise
    finally:
        for _, tmp in staged:
            tmp.unlink(missing_ok=True)


def agent_server_command(plan: InstallPlan) -> str:
    if platform.system() == "Windows":
        return str(Path(sys.executable).resolve())
    return str(plan.paths.wrapper)


def agent_server_args_json(plan: InstallPlan) -> str:
    args = ["app-server", "--stdio"]
    if platform.system() == "Windows":
        args.insert(0, str(plan.paths.wrapper))
    return json.dumps(args, ensure_ascii=False, separators=(",", ":"))


def env_values(plan: InstallPlan) -> dict[str, str]:
    return {
        "ZCODE_AGENT_SERVER_COMMAND": agent_server_command(plan),
        "ZCODE_AGENT_SERVER_ARGS_JSON": agent_server_args_json(plan),
        "ZCODE_KEYSMITH_SYSTEM_FILE": str(plan.paths.system_file),
        "ZCODE_KEYSMITH_ORIGINAL": str(plan.zcode_runtime),
        "ZCODE_KEYSMITH_NODE_COMMAND": str(plan.node_command),
        "ZCODE_KEYSMITH_CACHE_DIR": str(plan.paths.cache_dir),
        "ZCODE_KEYSMITH_LOG_DIR": str(plan.paths.log_dir),
    }


def render_env_script(plan: InstallPlan) -> str:
    if platform.system() == "Windows":
        lines = [
            "$ErrorActionPreference = 'Stop'",
            "$values = [ordered]@{",
        ]
        for key, value in env_values(plan).items():
            lines.append(f"    {key} = {powershell_single_quote(value)}")
        lines.extend(
            [
                "}",
                "foreach ($entry in $values.GetEnumerator()) {",
                "    [Environment]::SetEnvironmentVariable($entry.Key, $entry.Value, 'User')",
                "}",
                "Write-Output 'zcode-keysmith Windows environment activated'",
                "",
            ]
        )
        return "\n".join(lines)
    lines = ["#!/bin/sh", "set -eu"]
    for key, value in env_values(plan).items():
        lines.append(f"launchctl setenv {key} {sh_single_quote(value)}")
    lines.append("")
    return "\n".join(lines)


def sh_single_quote(value: str) -> str:
    return "'" + value.replace("'", "'\\''") + "'"


def powershell_single_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def render_launch_agent(plan: InstallPlan) -> dict[str, object]:
    if plan.paths.launch_agent is None:
        raise KeysmithError("LaunchAgent is only available on macOS")
    return {
        "Label": DEFAULT_LAUNCH_AGENT_LABEL,
        "ProgramArguments": [str(plan.paths.env_script)],
        "RunAtLoad": True,
        "StandardOutPath": str(plan.paths.log_dir / "launchagent.out.log"),
        "StandardErrorPath": str(plan.paths.log_dir / "launchagent.err.log"),
    }


def render_config(
    plan: InstallPlan,
    previous_user_environment: dict[str, dict[str, object] | None] | None = None,
) -> str:
    payload = {
        "tool_version": VERSION,
        "mode": "zcode-app-wrapper",
        "system_file": str(plan.paths.system_file),
        "wrapper": str(plan.paths.wrapper),
        "env_script": str(plan.paths.env_script),
        "launch_agent": str(plan.paths.launch_agent) if plan.paths.launch_agent else None,
        "zcode_runtime": str(plan.zcode_runtime),
        "node_command": str(plan.node_command),
        "cache_dir": str(plan.paths.cache_dir),
        "wrapper_log": str(plan.paths.wrapper_log),
        "agent_server_command": agent_server_command(plan),
        "agent_server_args_json": agent_server_args_json(plan),
        "environment": env_values(plan),
        "app_bundle_modified": False,
    }
    if platform.system() == "Windows":
        payload["platform"] = "Windows"
        payload["previous_user_environment"] = previous_user_environment or {}
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def render_wrapper(plan: InstallPlan) -> str:
    runtime_json = json.dumps(str(plan.zcode_runtime), ensure_ascii=False)
    system_file_json = json.dumps(str(plan.paths.system_file), ensure_ascii=False)
    node_command_json = json.dumps(str(plan.node_command), ensure_ascii=False)
    cache_dir_json = json.dumps(str(plan.paths.cache_dir), ensure_ascii=False)
    log_dir_json = json.dumps(str(plan.paths.log_dir), ensure_ascii=False)
    patch_needle_json = json.dumps(PATCH_NEEDLE, ensure_ascii=False)
    return f'''#!/usr/bin/env python3
from __future__ import annotations

import datetime
import hashlib
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import time

ORIGINAL_RUNTIME = pathlib.Path(os.environ.get("ZCODE_KEYSMITH_ORIGINAL") or {runtime_json})
SYSTEM_FILE = pathlib.Path(os.environ.get("ZCODE_KEYSMITH_SYSTEM_FILE") or {system_file_json})
NODE_COMMAND = os.environ.get("ZCODE_KEYSMITH_NODE_COMMAND") or {node_command_json}
PATCH_NEEDLE = {patch_needle_json}
CACHE_DIR = pathlib.Path(os.environ.get("ZCODE_KEYSMITH_CACHE_DIR") or {cache_dir_json})
LOG_DIR = pathlib.Path(os.environ.get("ZCODE_KEYSMITH_LOG_DIR") or {log_dir_json})
LOG_FILE = LOG_DIR / "wrapper-start.jsonl"


def acquire_cache_lock(path: pathlib.Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a+b")
    if os.name == "nt":
        import msvcrt

        if path.stat().st_size == 0:
            handle.write(b"\\0")
            handle.flush()
        handle.seek(0)
        while True:
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                return handle
            except OSError:
                time.sleep(0.02)
    import fcntl

    fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
    return handle


def release_cache_lock(handle) -> None:
    try:
        if os.name == "nt":
            import msvcrt

            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    finally:
        handle.close()


def system_prompt_expression() -> str:
    system_file = json.dumps(str(SYSTEM_FILE), ensure_ascii=False)
    return (
        "(this.config.systemPrompt&&this.config.systemPrompt.trim()?this.config.systemPrompt:"
        "(()=>{{try{{let e=process.env.ZCODE_KEYSMITH_SYSTEM_FILE||"
        + system_file
        + ";let t=require(\\\"node:fs\\\");return t.existsSync(e)?t.readFileSync(e,\\\"utf8\\\"):void 0}}catch{{return void 0}}}})())"
    )


def patched_runtime_path() -> pathlib.Path:
    original = ORIGINAL_RUNTIME.read_text(encoding="utf-8")
    if PATCH_NEEDLE not in original:
        raise RuntimeError(f"ZCode runtime patch anchor not found: {{ORIGINAL_RUNTIME}}")
    replacement = "customSystemPrompt:" + system_prompt_expression() + ",language:"
    patched = original.replace(PATCH_NEEDLE, replacement, 1)
    digest = hashlib.sha256((str(ORIGINAL_RUNTIME) + "\\0" + original + "\\0" + replacement).encode("utf-8")).hexdigest()[:16]
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = CACHE_DIR / f"zcode-keysmith-runtime-{{digest}}.cjs"
    lock = acquire_cache_lock(path.with_name(f".{{path.name}}.lock"))
    try:
        if not path.exists() or path.read_text(encoding="utf-8", errors="ignore") != patched:
            tmp = None
            try:
                with tempfile.NamedTemporaryFile(
                    "w",
                    encoding="utf-8",
                    dir=str(CACHE_DIR),
                    prefix=f".{{path.name}}.",
                    suffix=".tmp",
                    delete=False,
                ) as handle:
                    handle.write(patched)
                    tmp = pathlib.Path(handle.name)
                tmp.replace(path)
            finally:
                if tmp is not None:
                    tmp.unlink(missing_ok=True)
    finally:
        release_cache_lock(lock)
    return path


def log_invocation(runtime: pathlib.Path, args: list[str]) -> None:
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        event = {{
            "started_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "pid": os.getpid(),
            "argv": sys.argv,
            "agent_args": args,
            "runtime": str(runtime),
            "original_runtime": str(ORIGINAL_RUNTIME),
            "system_file": str(SYSTEM_FILE),
            "node_command": NODE_COMMAND,
        }}
        with LOG_FILE.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\\n")
    except Exception:
        pass


def main() -> int:
    runtime = patched_runtime_path()
    args = sys.argv[1:] or ["app-server", "--stdio"]
    log_invocation(runtime, args)
    env = os.environ.copy()
    env["ELECTRON_RUN_AS_NODE"] = "1"
    if os.name == "nt":
        # Use Popen to inherit stdin/stdout/stderr directly for stable long-running JSON-RPC communication
        proc = subprocess.Popen(
            [NODE_COMMAND, str(runtime), *args],
            env=env,
        )
        return proc.wait()
    os.execve(NODE_COMMAND, [NODE_COMMAND, str(runtime), *args], env)
    return 127


if __name__ == "__main__":
    raise SystemExit(main())
'''


def get_windows_user_env_entry(key: str) -> dict[str, object] | None:
    if platform.system() != "Windows":
        return None
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as environment:
            value, registry_type = winreg.QueryValueEx(environment, key)
    except FileNotFoundError:
        return None
    if not isinstance(value, str):
        return None
    return {"value": value, "registry_type": int(registry_type)}


def windows_string_env_entry(value: str) -> dict[str, object]:
    import winreg

    return {"value": value, "registry_type": winreg.REG_SZ}


def set_windows_user_env_entry(key: str, entry: dict[str, object] | None) -> None:
    if platform.system() != "Windows":
        raise KeysmithError("Windows user environment is only available on Windows")
    import winreg

    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, "Environment", 0, winreg.KEY_SET_VALUE) as environment:
        if entry is None:
            try:
                winreg.DeleteValue(environment, key)
            except FileNotFoundError:
                pass
            os.environ.pop(key, None)
            return
        value = entry.get("value")
        if not isinstance(value, str):
            raise KeysmithError(f"invalid saved Windows environment value for {key}")
        registry_type = entry.get("registry_type", winreg.REG_SZ)
        if registry_type not in (winreg.REG_SZ, winreg.REG_EXPAND_SZ):
            registry_type = winreg.REG_SZ
        winreg.SetValueEx(environment, key, 0, int(registry_type), value)
        os.environ[key] = value


def broadcast_windows_environment_change() -> None:
    if platform.system() != "Windows":
        return
    from ctypes import wintypes

    HWND_BROADCAST = 0xFFFF
    WM_SETTINGCHANGE = 0x001A
    SMTO_ABORTIFHUNG = 0x0002
    result = ctypes.c_size_t()
    send_message = ctypes.windll.user32.SendMessageTimeoutW
    send_message.argtypes = [
        wintypes.HWND,
        wintypes.UINT,
        wintypes.WPARAM,
        ctypes.c_wchar_p,
        wintypes.UINT,
        wintypes.UINT,
        ctypes.POINTER(ctypes.c_size_t),
    ]
    send_message.restype = wintypes.LPARAM
    send_message(
        HWND_BROADCAST,
        WM_SETTINGCHANGE,
        0,
        "Environment",
        SMTO_ABORTIFHUNG,
        5000,
        ctypes.byref(result),
    )


def load_saved_config(paths: InstallPaths) -> dict[str, object] | None:
    if not paths.config_file.exists() or not paths.config_file.is_file():
        return None
    try:
        loaded = json.loads(paths.config_file.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return loaded if isinstance(loaded, dict) else None


def capture_previous_windows_environment(paths: InstallPaths) -> dict[str, dict[str, object] | None]:
    saved = load_saved_config(paths)
    if saved and saved.get("platform") == "Windows":
        previous = saved.get("previous_user_environment")
        if isinstance(previous, dict):
            return {
                key: previous.get(key) if isinstance(previous.get(key), dict) else None
                for key in MANAGED_ENV_KEYS
            }
    return {key: get_windows_user_env_entry(key) for key in MANAGED_ENV_KEYS}


def activate_current_session(plan: InstallPlan) -> list[str]:
    if platform.system() == "Windows":
        results = []

        previous = {key: get_windows_user_env_entry(key) for key in MANAGED_ENV_KEYS}
        changed: list[str] = []
        try:
            for key, value in env_values(plan).items():
                set_windows_user_env_entry(key, windows_string_env_entry(value))
                changed.append(key)
                results.append(f"user environment {key}: set")
            broadcast_windows_environment_change()
        except Exception as exc:
            rollback_errors: list[str] = []
            for key in reversed(changed):
                try:
                    set_windows_user_env_entry(key, previous[key])
                except Exception as rollback_exc:
                    rollback_errors.append(f"{key}: {rollback_exc}")
            try:
                broadcast_windows_environment_change()
            except Exception as rollback_exc:
                rollback_errors.append(f"broadcast: {rollback_exc}")
            detail = f"Windows environment activation failed: {exc}"
            if rollback_errors:
                detail += "\nEnvironment rollback failed:\n" + "\n".join(rollback_errors)
            raise KeysmithError(detail) from exc
        return results
    if platform.system() != "Darwin":
        return ["launchctl: skipped (non-macOS)"]
    results: list[str] = []
    previous = {key: launchctl_getenv(key) for key in MANAGED_ENV_KEYS}
    changed: list[str] = []
    try:
        for key, value in env_values(plan).items():
            completed = subprocess.run(
                ["launchctl", "setenv", key, value],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            if completed.returncode != 0:
                detail = (completed.stderr or completed.stdout).strip()
                raise KeysmithError(f"launchctl setenv failed for {key}: {detail}")
            changed.append(key)
            results.append(f"launchctl setenv {key}: ok")
    except Exception as exc:
        rollback_errors: list[str] = []
        for key in reversed(changed):
            command = ["launchctl", "setenv", key, previous[key]] if previous[key] is not None else ["launchctl", "unsetenv", key]
            completed = subprocess.run(
                command,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            if completed.returncode != 0:
                detail = (completed.stderr or completed.stdout).strip()
                rollback_errors.append(f"{key}: {detail or f'exit {completed.returncode}'}")
        detail = f"macOS launchctl activation failed: {exc}"
        if rollback_errors:
            detail += "\nEnvironment rollback failed:\n" + "\n".join(rollback_errors)
        raise KeysmithError(detail) from exc
    return results


def file_sha256(path: Path) -> str | None:
    if not path.exists() or not path.is_file():
        return None
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def install_lines(plan: InstallPlan, dry_run: bool, backups: list[Path], activation: list[str]) -> list[str]:
    lines = ["zcode-keysmith install preview" if dry_run else "zcode-keysmith install complete"]
    lines.extend(
        [
            f"source_system_file: {plan.source_system_file}",
            f"system_file: {plan.paths.system_file}",
            f"config_file: {plan.paths.config_file}",
            f"wrapper: {plan.paths.wrapper}",
            f"env_script: {plan.paths.env_script}",
            f"launch_agent: {plan.paths.launch_agent or 'not used on Windows'}",
            f"zcode_runtime: {plan.zcode_runtime}",
            f"node_command: {plan.node_command}",
            f"cache_dir: {plan.paths.cache_dir}",
            f"wrapper_log: {plan.paths.wrapper_log}",
            f"agent_server_command: {agent_server_command(plan)}",
            f"agent_server_args_json: {agent_server_args_json(plan)}",
            f"activate_current_session: {str(plan.activate).lower()}",
            "app_bundle_modified: false",
            "api_key: not read or stored",
            f"zcode_running: {str(is_zcode_running()).lower()}",
            "activation_note: reopen ZCode and start a fresh task",
            f"write: {str(not dry_run).lower()}",
        ]
    )
    if dry_run:
        lines.append("tip: rerun with install --yes to write these files")
    for backup in backups:
        lines.append(f"backup: {backup}")
    lines.extend(activation)
    if not dry_run:
        lines.append("effect: new ZCode agent-server processes will use the managed wrapper")
    return lines


def runtime_node_from_args(args: argparse.Namespace) -> tuple[Path, Path]:
    explicit_app = getattr(args, "zcode_app", None)
    if explicit_app:
        return resolve_zcode_bundle_paths(expand_path(explicit_app))
    if os.environ.get("ZCODE_APP_PATH"):
        return resolve_zcode_bundle_paths(expand_path(os.environ["ZCODE_APP_PATH"]))
    explicit_runtime = getattr(args, "zcode_runtime", None)
    explicit_node = getattr(args, "node_command", None)
    if explicit_runtime and explicit_node:
        return expand_path(explicit_runtime), expand_path(explicit_node)
    discovered_runtime, discovered_node = resolve_zcode_bundle_paths(discover_zcode_app_path())
    return (
        expand_path(explicit_runtime) if explicit_runtime else discovered_runtime,
        expand_path(explicit_node) if explicit_node else discovered_node,
    )


def build_install_plan(args: argparse.Namespace) -> InstallPlan:
    paths = build_paths(expand_path(args.managed_dir), expand_path(args.launch_agent) if args.launch_agent else None)
    source_system_file = expand_path(args.system_file)
    zcode_runtime, node_command = runtime_node_from_args(args)
    return InstallPlan(
        paths=paths,
        source_system_file=source_system_file,
        zcode_runtime=zcode_runtime,
        node_command=node_command,
        activate=not args.no_activate,
    )


def install(plan: InstallPlan, yes: bool, dry_run_flag: bool) -> list[str]:
    system_prompt = read_system_prompt_source(plan.source_system_file)
    ensure_runtime_patchable(plan.zcode_runtime)
    if not plan.node_command.exists():
        fallback = shutil.which(str(plan.node_command))
        if fallback:
            object.__setattr__(plan, "node_command", Path(fallback))  # type: ignore[misc]
        else:
            raise KeysmithError(f"node command not found: {plan.node_command}")

    dry_run = dry_run_flag or not yes
    if dry_run:
        return install_lines(plan, dry_run=True, backups=[], activation=[])

    with operation_lock(plan.paths):
        return install_locked(plan, system_prompt)


def install_locked(plan: InstallPlan, system_prompt: str) -> list[str]:
    previous_user_environment = (
        capture_previous_windows_environment(plan.paths) if platform.system() == "Windows" else None
    )
    for directory in (plan.paths.managed_dir, plan.paths.wrapper.parent, plan.paths.log_dir, plan.paths.cache_dir):
        directory.mkdir(parents=True, exist_ok=True)

    backups, replaced = install_managed_files(plan, system_prompt, render_config(plan, previous_user_environment))
    try:
        activation = activate_current_session(plan) if plan.activate else []
    except Exception as exc:
        if isinstance(exc, KeysmithError) and "Environment rollback failed:" in str(exc):
            raise KeysmithError(
                f"{exc}\nManaged files were kept at the new version because the environment rollback was incomplete."
            ) from exc
        rollback_errors = rollback_replaced_files(replaced)
        if rollback_errors:
            raise KeysmithError(
                f"{exc}\nFile rollback failed:\n" + "\n".join(rollback_errors)
            ) from exc
        raise
    return install_lines(plan, dry_run=False, backups=backups, activation=activation)


def launchctl_getenv(key: str) -> str | None:
    if platform.system() != "Darwin":
        return None
    completed = subprocess.run(["launchctl", "getenv", key], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if completed.returncode != 0:
        return None
    value = completed.stdout.strip()
    return value or None


def persistent_environment_value(key: str) -> str | None:
    if platform.system() == "Windows":
        entry = get_windows_user_env_entry(key)
        value = entry.get("value") if entry else None
        return value if isinstance(value, str) else None
    return launchctl_getenv(key)


def doctor_lines(paths: InstallPaths, zcode_runtime: Path, node_command: Path) -> list[str]:
    prompt_hash = file_sha256(paths.system_file)
    runtime_patchable = False
    if zcode_runtime.exists() and zcode_runtime.is_file():
        try:
            runtime_patchable = PATCH_NEEDLE in zcode_runtime.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            runtime_patchable = False
    expected_plan = InstallPlan(
        paths=paths,
        source_system_file=DEFAULT_SOURCE_SYSTEM_FILE,
        zcode_runtime=zcode_runtime,
        node_command=node_command,
        activate=False,
    )
    expected_env = env_values(expected_plan)
    lines = [
        "zcode-keysmith doctor",
        f"managed_dir: {paths.managed_dir}",
        f"system_file: {paths.system_file}",
        f"system_file_exists: {str(paths.system_file.exists()).lower()}",
        f"system_file_sha256: {prompt_hash or 'missing'}",
        f"config_file: {paths.config_file}",
        f"config_file_exists: {str(paths.config_file.exists()).lower()}",
        f"wrapper: {paths.wrapper}",
        f"wrapper_exists: {str(paths.wrapper.exists()).lower()}",
        f"env_script: {paths.env_script}",
        f"env_script_exists: {str(paths.env_script.exists()).lower()}",
        f"launch_agent: {paths.launch_agent or 'not used on Windows'}",
        f"launch_agent_exists: {str(bool(paths.launch_agent and paths.launch_agent.exists())).lower()}",
        f"zcode_runtime: {zcode_runtime}",
        f"zcode_runtime_exists: {str(zcode_runtime.exists()).lower()}",
        f"zcode_runtime_patchable: {str(runtime_patchable).lower()}",
        f"node_command: {node_command}",
        f"node_command_exists: {str(node_command.exists()).lower()}",
        "app_bundle_modified: false",
        "api_key: not read or stored",
    ]
    for key, expected in expected_env.items():
        current = os.environ.get(key)
        persistent_value = persistent_environment_value(key)
        lines.append(f"env.{key}: {'set' if current else 'not set'}")
        lines.append(
            f"persistent.{key}: "
            f"{'matches' if persistent_value == expected else 'not set' if not persistent_value else 'different'}"
        )
    return lines


def is_agent_server_invocation(event: dict[str, object]) -> bool:
    args = event.get("agent_args")
    return isinstance(args, list) and len(args) >= 2 and args[0] == "app-server" and args[1] == "--stdio"


def read_last_wrapper_invocation(paths: InstallPaths) -> dict[str, object] | None:
    if not paths.wrapper_log.exists() or not paths.wrapper_log.is_file():
        return None
    try:
        lines = [line.strip() for line in paths.wrapper_log.read_text(encoding="utf-8", errors="replace").splitlines() if line.strip()]
    except OSError:
        return None
    for line in reversed(lines):
        try:
            loaded = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(loaded, dict) and is_agent_server_invocation(loaded):
            return loaded
    return None


def run_wrapper_smoke(paths: InstallPaths, timeout: float = 10.0) -> tuple[bool, str]:
    if not paths.wrapper.exists():
        return False, "wrapper missing"
    command = [str(paths.wrapper), "--help"]
    if platform.system() == "Windows":
        command.insert(0, str(Path(sys.executable).resolve()))
    completed = subprocess.run(
        command,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=timeout,
    )
    if completed.returncode == 0:
        return True, "ok"
    detail = (completed.stderr or completed.stdout).strip().splitlines()
    return False, detail[0] if detail else f"exit {completed.returncode}"


def verify_lines(paths: InstallPaths, zcode_runtime: Path, node_command: Path, smoke: bool = True) -> list[str]:
    prompt_hash = file_sha256(paths.system_file)
    zcode_app = zcode_app_from_runtime(zcode_runtime)
    runtime_patchable = False
    if zcode_runtime.exists() and zcode_runtime.is_file():
        try:
            runtime_patchable = PATCH_NEEDLE in zcode_runtime.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            runtime_patchable = False
    smoke_ok, smoke_detail = run_wrapper_smoke(paths) if smoke else (False, "skipped")
    last_invocation = read_last_wrapper_invocation(paths)
    wrapper_invoked = last_invocation is not None
    lines = [
        "zcode-keysmith verify",
        f"system_file_exists: {str(paths.system_file.exists()).lower()}",
        f"system_file_sha256: {prompt_hash or 'missing'}",
        f"wrapper_exists: {str(paths.wrapper.exists()).lower()}",
        f"wrapper_smoke: {str(smoke_ok).lower()}",
        f"wrapper_smoke_detail: {smoke_detail}",
        f"wrapper_log: {paths.wrapper_log}",
        f"wrapper_invoked: {str(wrapper_invoked).lower()}",
        f"last_wrapper_start: {last_invocation.get('started_at') if last_invocation else 'missing'}",
        f"zcode_app: {zcode_app or 'unknown'}",
        f"zcode_agent_override_supported: {str(app_supports_agent_server_override(zcode_app)).lower()}",
        f"zcode_runtime_exists: {str(zcode_runtime.exists()).lower()}",
        f"zcode_runtime_patchable: {str(runtime_patchable).lower()}",
        f"node_command_exists: {str(node_command.exists()).lower()}",
        f"zcode_running: {str(is_zcode_running()).lower()}",
        "api_key: not read or stored",
    ]
    if is_zcode_running():
        lines.append("activation_note: reopen ZCode and start a fresh task")
    return lines


def uninstall_lines(paths: InstallPaths, dry_run: bool, removed: list[Path], activation: list[str]) -> list[str]:
    lines = ["zcode-keysmith uninstall preview" if dry_run else "zcode-keysmith uninstall complete"]
    targets = [paths.system_file, paths.config_file, paths.wrapper, paths.env_script]
    if paths.launch_agent is not None:
        targets.append(paths.launch_agent)
    for path in targets:
        lines.append(f"target: {path}")
    lines.append(f"write: {str(not dry_run).lower()}")
    for path in removed:
        lines.append(f"removed: {path}")
    lines.extend(activation)
    return lines


def restore_windows_user_environment(
    paths: InstallPaths,
    config: dict[str, object] | None = None,
) -> list[str]:
    config = config or load_saved_config(paths)
    if not config or config.get("platform") != "Windows":
        return ["user environment: unchanged (managed Windows config missing)"]
    installed = config.get("environment")
    previous = config.get("previous_user_environment")
    if not isinstance(installed, dict) or not isinstance(previous, dict):
        return ["user environment: unchanged (managed Windows environment backup missing)"]

    results: list[str] = []
    changes: list[tuple[str, dict[str, object] | None]] = []
    for key in MANAGED_ENV_KEYS:
        expected = installed.get(key)
        if not isinstance(expected, str):
            results.append(f"user environment {key}: unchanged (installed value unknown)")
            continue
        current = persistent_environment_value(key)
        if current != expected:
            results.append(f"user environment {key}: unchanged (modified after install)")
            continue
        saved_entry = previous.get(key)
        changes.append((key, saved_entry if isinstance(saved_entry, dict) else None))
    current_entries = {key: get_windows_user_env_entry(key) for key, _ in changes}
    changed: list[str] = []
    try:
        for key, saved_entry in changes:
            set_windows_user_env_entry(key, saved_entry)
            changed.append(key)
            results.append(f"user environment {key}: restored")
        if changed:
            broadcast_windows_environment_change()
    except Exception as exc:
        rollback_errors: list[str] = []
        for key in reversed(changed):
            try:
                set_windows_user_env_entry(key, current_entries[key])
            except Exception as rollback_exc:
                rollback_errors.append(f"{key}: {rollback_exc}")
        try:
            broadcast_windows_environment_change()
        except Exception as rollback_exc:
            rollback_errors.append(f"broadcast: {rollback_exc}")
        detail = f"Windows environment restore failed: {exc}"
        if rollback_errors:
            detail += "\nEnvironment rollback failed:\n" + "\n".join(rollback_errors)
        raise KeysmithError(detail) from exc
    return results


def unset_current_session_env(paths: InstallPaths) -> list[str]:
    if platform.system() == "Windows":
        return restore_windows_user_environment(paths)
    if platform.system() != "Darwin":
        return ["launchctl unsetenv: skipped (non-macOS)"]
    results: list[str] = []
    previous = {key: launchctl_getenv(key) for key in MANAGED_ENV_KEYS}
    changed: list[str] = []
    try:
        for key in MANAGED_ENV_KEYS:
            completed = subprocess.run(
                ["launchctl", "unsetenv", key],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            if completed.returncode != 0:
                detail = (completed.stderr or completed.stdout).strip()
                raise KeysmithError(f"launchctl unsetenv failed for {key}: {detail}")
            changed.append(key)
            results.append(f"launchctl unsetenv {key}: ok")
    except Exception as exc:
        rollback_errors: list[str] = []
        for key in reversed(changed):
            value = previous[key]
            if value is None:
                continue
            completed = subprocess.run(
                ["launchctl", "setenv", key, value],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            if completed.returncode != 0:
                detail = (completed.stderr or completed.stdout).strip()
                rollback_errors.append(f"{key}: {detail or f'exit {completed.returncode}'}")
        detail = f"macOS launchctl uninstall failed: {exc}"
        if rollback_errors:
            detail += "\nEnvironment rollback failed:\n" + "\n".join(rollback_errors)
        raise KeysmithError(detail) from exc
    return results


def uninstall(paths: InstallPaths, yes: bool, dry_run_flag: bool, activate: bool) -> list[str]:
    dry_run = dry_run_flag or not yes
    if dry_run:
        return uninstall_lines(paths, dry_run=True, removed=[], activation=[])
    with operation_lock(paths):
        return uninstall_locked(paths, activate)


def uninstall_locked(paths: InstallPaths, activate: bool) -> list[str]:
    removed = []
    targets = [paths.system_file, paths.config_file, paths.wrapper, paths.env_script]
    if paths.launch_agent is not None:
        targets.append(paths.launch_agent)
    config = load_saved_config(paths) if platform.system() == "Windows" else None
    moved: list[tuple[Path, Path]] = []
    try:
        for path in targets:
            if path.exists():
                backup = reserve_backup_path(path)
                try:
                    path.replace(backup)
                except Exception:
                    backup.unlink(missing_ok=True)
                    raise
                moved.append((path, backup))
                removed.append(backup)
        activation = (
            restore_windows_user_environment(paths, config)
            if activate and platform.system() == "Windows"
            else unset_current_session_env(paths) if activate else []
        )
    except Exception as exc:
        if isinstance(exc, KeysmithError) and "Environment rollback failed:" in str(exc):
            raise KeysmithError(
                f"{exc}\nManaged files remain in the listed backup paths because the environment rollback was incomplete."
            ) from exc
        rollback_errors: list[str] = []
        for path, backup in reversed(moved):
            try:
                backup.replace(path)
            except OSError as rollback_exc:
                rollback_errors.append(f"{path}: {rollback_exc}")
        if rollback_errors:
            raise KeysmithError(
                f"{exc}\nFile rollback failed:\n" + "\n".join(rollback_errors)
            ) from exc
        raise
    return uninstall_lines(paths, dry_run=False, removed=removed, activation=activation)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Install or inspect zcode-keysmith managed ZCode App system-role entrypoint.")
    parser.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")
    sub = parser.add_subparsers(dest="command")

    install_parser = sub.add_parser("install", help="Install managed ZCode App wrapper and system-role file")
    install_parser.add_argument("--system-file", default=str(DEFAULT_SOURCE_SYSTEM_FILE), help="Source Markdown system prompt. Default: examples/system-role.md")
    install_parser.add_argument("--managed-dir", default=str(DEFAULT_MANAGED_DIR), help="Managed install directory. Default: ~/.zcode-keysmith")
    install_parser.add_argument("--launch-agent", default=None, help="macOS LaunchAgent plist path (not used on Windows)")
    install_parser.add_argument("--zcode-app", default=None, help="ZCode app directory or macOS .app path; auto-detected by default")
    install_parser.add_argument("--zcode-runtime", default=None, help="Bundled ZCode runtime file; auto-detected by default")
    install_parser.add_argument("--node-command", default=None, help="ZCode executable used as Electron Node; auto-detected by default")
    install_parser.add_argument("--dry-run", action="store_true", help="Preview paths and checks without writing")
    install_parser.add_argument("--yes", action="store_true", help="Allow writing files. --dry-run wins if both are provided")
    install_parser.add_argument("--no-activate", action="store_true", help="Write files without activating the persistent environment")

    doctor_parser = sub.add_parser("doctor", help="Inspect managed install state")
    doctor_parser.add_argument("--managed-dir", default=str(DEFAULT_MANAGED_DIR))
    doctor_parser.add_argument("--launch-agent", default=None)
    doctor_parser.add_argument("--zcode-app", default=None)
    doctor_parser.add_argument("--zcode-runtime", default=None)
    doctor_parser.add_argument("--node-command", default=None)

    verify_parser = sub.add_parser("verify", help="Run local wrapper/runtime verification without sending model requests")
    verify_parser.add_argument("--managed-dir", default=str(DEFAULT_MANAGED_DIR))
    verify_parser.add_argument("--launch-agent", default=None)
    verify_parser.add_argument("--zcode-app", default=None)
    verify_parser.add_argument("--zcode-runtime", default=None)
    verify_parser.add_argument("--node-command", default=None)
    verify_parser.add_argument("--no-smoke", action="store_true", help="Skip local wrapper --help smoke test")

    uninstall_parser = sub.add_parser("uninstall", help="Back up managed files and unset current environment")
    uninstall_parser.add_argument("--managed-dir", default=str(DEFAULT_MANAGED_DIR))
    uninstall_parser.add_argument("--launch-agent", default=None)
    uninstall_parser.add_argument("--zcode-app", default=None)
    uninstall_parser.add_argument("--zcode-runtime", default=None)
    uninstall_parser.add_argument("--node-command", default=None)
    uninstall_parser.add_argument("--dry-run", action="store_true")
    uninstall_parser.add_argument("--yes", action="store_true")
    uninstall_parser.add_argument("--no-activate", action="store_true")

    return parser


def main(argv: Iterable[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        command = args.command or "doctor"
        if command == "install":
            plan = build_install_plan(args)
            print("\n".join(install(plan, yes=args.yes, dry_run_flag=args.dry_run)))
            return 0
        if command == "doctor":
            paths = build_paths(expand_path(args.managed_dir), expand_path(args.launch_agent) if args.launch_agent else None)
            zcode_runtime, node_command = runtime_node_from_args(args)
            print("\n".join(doctor_lines(paths, zcode_runtime, node_command)))
            return 0
        if command == "verify":
            paths = build_paths(expand_path(args.managed_dir), expand_path(args.launch_agent) if args.launch_agent else None)
            zcode_runtime, node_command = runtime_node_from_args(args)
            print("\n".join(verify_lines(paths, zcode_runtime, node_command, smoke=not args.no_smoke)))
            return 0
        if command == "uninstall":
            paths = build_paths(expand_path(args.managed_dir), expand_path(args.launch_agent) if args.launch_agent else None)
            print("\n".join(uninstall(paths, yes=args.yes, dry_run_flag=args.dry_run, activate=not args.no_activate)))
            return 0
        parser.print_help()
        return 1
    except KeysmithError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
