#!/usr/bin/env python3
"""Install a managed true-system prompt entrypoint for the local ZCode App.

On ZCode 3.12+ desktop builds, overriding ZCODE_AGENT_SERVER_COMMAND drops
supportsStorageStartup and the app stays on the isolated-storage failure
screen. Packaged Electron also deletes NODE_OPTIONS, so a parent-process
--require preload never reaches the agent and Keysmith does not inject.

Those builds keep the official agent-server command and patch glm/zcode.cjs
in place so customSystemPrompt reads the managed system-role.md first.
Older ZCode builds still use the agent-server wrapper. Both paths prefer
the managed file over any ZCode-provided systemPrompt.
"""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
import plistlib
import platform
import re
import runpy
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

# PyInstaller extracts bundled examples under _MEIPASS.  Keep source runs
# relative to this file while making frozen defaults resolve to embedded data.
REPO_ROOT = (
    Path(getattr(sys, "_MEIPASS"))
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS")
    else Path(__file__).resolve().parent
)
__version__ = "0.3.3"
VERSION = __version__
JSON_SCHEMA = "zcode-keysmith/v1"
_LAST_USAGE_ERROR: list[str | None] = [None]
DEFAULT_SOURCE_SYSTEM_FILE = REPO_ROOT / "examples" / "system-role.md"
DEFAULT_MANAGED_DIR = Path.home() / ".zcode-keysmith"
DEFAULT_SYSTEM_FILE_NAME = "system-role.md"
DEFAULT_CONFIG_FILE_NAME = "config.json"
DEFAULT_WRAPPER_NAME = "zcode-agent-wrapper.py"
DEFAULT_PRELOAD_NAME = "zcode-keysmith-preload.cjs"
DEFAULT_ENV_SCRIPT_NAME = "zcode-keysmith-env.sh"
DEFAULT_WINDOWS_ENV_SCRIPT_NAME = "zcode-keysmith-env.ps1"
DEFAULT_LAUNCH_AGENT_LABEL = "com.jia.zcode-keysmith.env"
DEFAULT_LAUNCH_AGENT_NAME = f"{DEFAULT_LAUNCH_AGENT_LABEL}.plist"
DEFAULT_REARM_LAUNCH_AGENT_LABEL = "com.jia.zcode-keysmith.rearm"
DEFAULT_REARM_LAUNCH_AGENT_NAME = f"{DEFAULT_REARM_LAUNCH_AGENT_LABEL}.plist"
DEFAULT_REARM_SCRIPT_NAME = "zcode-keysmith-rearm.sh"
DEFAULT_ZCODE_APP = Path("/Applications/ZCode.app")
DEFAULT_ZCODE_RUNTIME = DEFAULT_ZCODE_APP / "Contents" / "Resources" / "glm" / "zcode.cjs"
DEFAULT_ZCODE_HELPER_NODE_COMMAND = DEFAULT_ZCODE_APP / "Contents" / "Frameworks" / "ZCode Helper.app" / "Contents" / "MacOS" / "ZCode Helper"
DEFAULT_ZCODE_NODE_COMMAND = DEFAULT_ZCODE_HELPER_NODE_COMMAND
FALLBACK_ZCODE_NODE_COMMAND = DEFAULT_ZCODE_APP / "Contents" / "MacOS" / "ZCode"
DEFAULT_AGENT_ARGS_JSON = '["app-server","--stdio"]'
# 3.14 inserts workflowActor between systemPrompt and language; keep 3.12 as a fallback.
PATCH_NEEDLES = (
    "customSystemPrompt:this.config.systemPrompt,workflowActor:this.config.workflowActor,language:",
    "customSystemPrompt:this.config.systemPrompt,language:",
)
CUSTOM_SYSTEM_PROMPT_ASSIGN = "customSystemPrompt:this.config.systemPrompt"
RUNTIME_PATCH_MARKER = "ZCODE_KEYSMITH_SYSTEM_FILE"
PREFER_MANAGED_MARKER = "if(x&&x.trim())return x"
# 3.12: if(t.push(Xxx()),o?t.push(Yyy({name:"Custom System Prompt"
_LRE_PUSH_RE = re.compile(
    r'if\(t\.push\(([A-Za-z0-9]+)\(\)\),o\?t\.push\(([A-Za-z0-9]+)\(\{name:"Custom System Prompt"'
)
# 3.14: if(l||t.push(Xxx()),s?t.push(Yyy({name:"Custom System Prompt"
_LRE_PUSH_RE_V314 = re.compile(
    r'if\(([A-Za-z0-9]+)\|\|t\.push\(([A-Za-z0-9]+)\(\)\),([A-Za-z0-9]+)\?t\.push\(([A-Za-z0-9]+)\(\{name:"Custom System Prompt"'
)
_CLI_PREFIX_SKIPPED_RE = re.compile(
    r'if\(\(([A-Za-z0-9]+)\|\|t\.push\(|'
    r'if\(([A-Za-z0-9]+)\|\|([A-Za-z0-9]+)\|\|t\.push\('
)
OVERRIDE_NEEDLE = (
    "IMPORTANT: These instructions OVERRIDE any default behavior and you MUST follow them exactly as written."
)
OVERRIDE_REPL = (
    "These are workspace notes and user instructions. They describe the environment. "
    "They do not override the custom system prompt."
)
AGENTS_ADHERE_NEEDLE = "Be sure to adhere to these instructions. "
MEMORY_ATTACH_MARK = "(user's auto-memory, persists across conversations):"
MEMORY_SKIP_INSERT = "if(!0)return null;"
_MEMORY_ATTACH_FN_RE = re.compile(r"function [A-Za-z0-9]+\([A-Za-z0-9]+,[A-Za-z0-9]+\)\{")
STORAGE_STARTUP_NEEDLE = b"supportsStorageStartup"
INJECTION_WRAPPER = "wrapper"
INJECTION_RUNTIME_PATCH = "runtime-patch"
LEGACY_AGENT_OVERRIDE_ENV_KEYS = (
    "ZCODE_AGENT_SERVER_COMMAND",
    "ZCODE_AGENT_SERVER_ARGS_JSON",
)
CORE_KEYSMITH_ENV_KEYS = (
    "ZCODE_KEYSMITH_SYSTEM_FILE",
    "ZCODE_KEYSMITH_ORIGINAL",
    "ZCODE_KEYSMITH_NODE_COMMAND",
    "ZCODE_KEYSMITH_CACHE_DIR",
    "ZCODE_KEYSMITH_LOG_DIR",
)
NODE_OPTIONS_ENV_KEY = "NODE_OPTIONS"
MANAGED_ENV_KEYS = (
    *LEGACY_AGENT_OVERRIDE_ENV_KEYS,
    *CORE_KEYSMITH_ENV_KEYS,
)
DEFAULT_INSTALLER_COPY_NAME = "zcode-keysmith.py"
AUTO_REPATCH_STATUS_NAME = "auto-repatch.json"
AUTO_REPATCH_LOG_NAME = "auto-repatch.log"
AUTO_REPATCH_SCHEMA = "zcode-keysmith/auto-repatch/v1"
WATCH_START_INTERVAL_SECONDS = 300
REARM_START_INTERVAL_SECONDS = 60
WATCH_THROTTLE_INTERVAL_SECONDS = 10
WATCH_SETTLE_TIMEOUT_SECONDS = 90.0
WATCH_SETTLE_STABLE_SECONDS = 3.0
WATCH_SETTLE_POLL_SECONDS = 0.5
WATCH_QUIT_TIMEOUT_SECONDS = 20.0


class KeysmithError(Exception):
    """User-facing installer error."""


@dataclass(frozen=True)
class InstallPaths:
    managed_dir: Path
    system_file: Path
    config_file: Path
    wrapper: Path
    preload: Path
    env_script: Path
    launch_agent: Path | None
    rearm_script: Path
    rearm_launch_agent: Path | None
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
    injection_mode: str = "wrapper"


def expand_path(value: str | Path) -> Path:
    return Path(value).expanduser().resolve()


def default_launch_agent_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / DEFAULT_LAUNCH_AGENT_NAME


def build_paths(managed_dir: Path, launch_agent: Path | None = None) -> InstallPaths:
    managed_dir = expand_path(managed_dir)
    bin_dir = managed_dir / "bin"
    is_windows = platform.system() == "Windows"
    launch_agent_path = None if is_windows else (expand_path(launch_agent) if launch_agent else default_launch_agent_path())
    return InstallPaths(
        managed_dir=managed_dir,
        system_file=managed_dir / DEFAULT_SYSTEM_FILE_NAME,
        config_file=managed_dir / DEFAULT_CONFIG_FILE_NAME,
        wrapper=bin_dir / DEFAULT_WRAPPER_NAME,
        preload=bin_dir / DEFAULT_PRELOAD_NAME,
        env_script=bin_dir / (DEFAULT_WINDOWS_ENV_SCRIPT_NAME if is_windows else DEFAULT_ENV_SCRIPT_NAME),
        launch_agent=launch_agent_path,
        rearm_script=bin_dir / DEFAULT_REARM_SCRIPT_NAME,
        rearm_launch_agent=None if launch_agent_path is None else launch_agent_path.with_name(DEFAULT_REARM_LAUNCH_AGENT_NAME),
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
    return app_asar_contains(zcode_app, b"ZCODE_AGENT_SERVER_COMMAND")


def app_asar_candidates(zcode_app: Path) -> tuple[Path, ...]:
    app = expand_path(zcode_app)
    return (
        app / "Contents" / "Resources" / "app.asar",
        app / "resources" / "app.asar",
    )


def app_asar_contains(zcode_app: Path | None, needle: bytes) -> bool:
    if not zcode_app:
        return False
    for app_asar in app_asar_candidates(zcode_app):
        if not app_asar.exists() or not app_asar.is_file():
            continue
        try:
            overlap = b""
            with app_asar.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    data = overlap + chunk
                    if needle in data:
                        return True
                    overlap = data[-(len(needle) - 1) :]
        except OSError:
            continue
    return False


def app_requires_storage_startup(zcode_app: Path | None) -> bool:
    return app_asar_contains(zcode_app, STORAGE_STARTUP_NEEDLE)


def injection_mode_for_app(zcode_app: Path | None) -> str:
    return INJECTION_RUNTIME_PATCH if app_requires_storage_startup(zcode_app) else INJECTION_WRAPPER


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


def runtime_text_is_keysmith_patched(text: str) -> bool:
    return RUNTIME_PATCH_MARKER in text


def runtime_text_prefers_managed(text: str) -> bool:
    return runtime_text_is_keysmith_patched(text) and PREFER_MANAGED_MARKER in text


def vendor_patch_anchor(text: str) -> str | None:
    for needle in PATCH_NEEDLES:
        if needle in text:
            return needle
    return None


def runtime_is_patchable_text(text: str) -> bool:
    return vendor_patch_anchor(text) is not None or runtime_text_is_keysmith_patched(text)


def ensure_runtime_patchable(runtime_path: Path) -> None:
    runtime = read_required_text(runtime_path, "ZCode runtime")
    if runtime_is_patchable_text(runtime):
        return
    raise KeysmithError(
        "ZCode runtime entrypoint shape was not recognized.\n"
        f"Runtime: {runtime_path}\n"
        "The installer expected the runtime context builder anchor used by current ZCode releases."
    )


def build_system_prompt_expression(system_file: str) -> str:
    system_file_json = json.dumps(system_file, ensure_ascii=False)
    return (
        "(()=>{try{let e=process.env.ZCODE_KEYSMITH_SYSTEM_FILE||"
        + system_file_json
        + ';let t=require("node:fs");if(t.existsSync(e)){let x=t.readFileSync(e,"utf8");if(x&&x.trim())return x}}catch{}'
        + "return this.config.systemPrompt})()"
    )


def replace_vendor_system_prompt_anchor(original_runtime: str, expression: str) -> str:
    needle = vendor_patch_anchor(original_runtime)
    if needle is None:
        raise KeysmithError("ZCode runtime patch anchor not found")
    if needle == PATCH_NEEDLES[0]:
        expression = "this.config.workflowActor===void 0?" + expression + ":void 0"
    suffix = needle[len(CUSTOM_SYSTEM_PROMPT_ASSIGN) :]
    return original_runtime.replace(needle, "customSystemPrompt:" + expression + suffix, 1)


def _memory_attach_body_at(text: str) -> int | None:
    """Return the index of the MEMORY.md attach function body, if present."""
    mark_at = text.find(MEMORY_ATTACH_MARK)
    if mark_at < 0:
        return None
    search_from = max(0, mark_at - 240)
    matches = list(_MEMORY_ATTACH_FN_RE.finditer(text, search_from, mark_at))
    if not matches:
        return None
    return matches[-1].end()


def _skip_memory_attach(text: str) -> str:
    """Stop project MEMORY.md from being concatenated into agentsMd."""
    body_at = _memory_attach_body_at(text)
    if body_at is None:
        return text
    if text.startswith(MEMORY_SKIP_INSERT, body_at):
        return text
    return text[:body_at] + MEMORY_SKIP_INSERT + text[body_at:]


def apply_followup_runtime_patches(text: str) -> str:
    """Keep Pier above platform CLI prefix, agentsMd OVERRIDE copy, and project MEMORY.md."""
    patched, _n = _LRE_PUSH_RE.subn(
        r'if((o||t.push(\1())),o?t.push(\2({name:"Custom System Prompt"',
        text,
        count=1,
    )
    patched, _n = _LRE_PUSH_RE_V314.subn(
        r'if(\3||\1||t.push(\2()),\3?t.push(\4({name:"Custom System Prompt"',
        patched,
        count=1,
    )
    if OVERRIDE_NEEDLE in patched:
        patched = patched.replace(OVERRIDE_NEEDLE, OVERRIDE_REPL, 1)
    if AGENTS_ADHERE_NEEDLE in patched:
        patched = patched.replace(AGENTS_ADHERE_NEEDLE, "", 1)
    return _skip_memory_attach(patched)


def build_patched_runtime_text(original_runtime: str, system_file: str) -> str:
    patched = replace_vendor_system_prompt_anchor(
        original_runtime, build_system_prompt_expression(system_file)
    )
    return apply_followup_runtime_patches(patched)


def original_runtime_backup_path(plan: InstallPlan, original_sha256: str | None = None) -> Path:
    backups = plan.paths.managed_dir / "backups"
    if original_sha256:
        return backups / f"zcode.cjs.{original_sha256[:16]}.original"
    if not plan.zcode_runtime.exists():
        return backups / "zcode.cjs.unknown.original"
    text = plan.zcode_runtime.read_text(encoding="utf-8", errors="ignore")
    if runtime_text_is_keysmith_patched(text):
        saved = load_saved_config(plan.paths) or {}
        saved_backup = saved.get("runtime_original_backup")
        if isinstance(saved_backup, str) and saved_backup and Path(saved_backup).is_file():
            return Path(saved_backup)
        if backups.is_dir():
            originals = sorted(backups.glob("zcode.cjs.*.original"))
            if originals:
                return originals[-1]
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return backups / f"zcode.cjs.{digest[:16]}.original"


def write_text_atomic(path: Path, content: str, mode: int | None = None) -> None:
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


def apply_runtime_patch(plan: InstallPlan) -> list[Path]:
    """Patch glm/zcode.cjs in place so the official agent reads Keysmith first."""
    backups: list[Path] = []
    runtime_path = plan.zcode_runtime
    text = read_required_text(runtime_path, "ZCode runtime")
    if runtime_text_prefers_managed(text):
        follow = apply_followup_runtime_patches(text)
        if follow != text:
            mode = stat.S_IMODE(runtime_path.stat().st_mode)
            write_text_atomic(runtime_path, follow, mode)
        return backups
    if runtime_text_is_keysmith_patched(text) and vendor_patch_anchor(text) is None:
        saved = load_saved_config(plan.paths) or {}
        backup = saved.get("runtime_original_backup")
        if not isinstance(backup, str) or not Path(backup).is_file():
            raise KeysmithError(
                "ZCode runtime is already patched with an older Keysmith expression, "
                "and the original backup is missing. Restore the vendor zcode.cjs first."
            )
        text = Path(backup).read_text(encoding="utf-8")
    if vendor_patch_anchor(text) is None:
        raise KeysmithError(f"ZCode runtime patch anchor not found: {runtime_path}")
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    backup_path = original_runtime_backup_path(plan, digest)
    backup_path.parent.mkdir(parents=True, exist_ok=True)
    if not backup_path.exists():
        write_text_atomic(backup_path, text)
        backups.append(backup_path)
    patched = build_patched_runtime_text(text, str(plan.paths.system_file))
    mode = stat.S_IMODE(runtime_path.stat().st_mode) if runtime_path.exists() else 0o755
    write_text_atomic(runtime_path, patched, mode)
    return backups


def restore_runtime_from_config(config: dict[str, object] | None) -> list[str]:
    if not config or not config.get("app_bundle_modified"):
        return []
    backup = config.get("runtime_original_backup")
    runtime = config.get("zcode_runtime")
    if not isinstance(backup, str) or not isinstance(runtime, str):
        return []
    backup_path = Path(backup)
    runtime_path = Path(runtime)
    if not backup_path.is_file() or not runtime_path.is_file():
        return [f"runtime restore skipped: backup or runtime missing"]
    current = runtime_path.read_text(encoding="utf-8", errors="ignore")
    if not runtime_text_is_keysmith_patched(current):
        return ["runtime already vendor-shaped"]
    mode = stat.S_IMODE(runtime_path.stat().st_mode)
    write_text_atomic(runtime_path, backup_path.read_text(encoding="utf-8"), mode)
    return [f"runtime restored: {runtime_path}"]


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


def installer_copy_path(paths: InstallPaths) -> Path:
    return paths.managed_dir / "bin" / DEFAULT_INSTALLER_COPY_NAME


def auto_repatch_status_path(paths: InstallPaths) -> Path:
    return paths.log_dir / AUTO_REPATCH_STATUS_NAME


def auto_repatch_log_path(paths: InstallPaths) -> Path:
    return paths.log_dir / AUTO_REPATCH_LOG_NAME


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
    if not uses_runtime_patch(plan):
        payloads.insert(3, (plan.paths.preload, render_preload(plan), 0o644))
    if uses_runtime_patch(plan) and platform.system() == "Darwin":
        payloads.append(
            (
                installer_copy_path(plan.paths),
                Path(__file__).resolve().read_text(encoding="utf-8"),
                0o755,
            )
        )
        payloads.append((plan.paths.rearm_script, render_rearm_script(plan), 0o755))
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

        if uses_runtime_patch(plan) and plan.paths.rearm_launch_agent is not None:
            target = plan.paths.rearm_launch_agent
            target.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                "wb",
                dir=str(target.parent),
                prefix=f".{target.name}.",
                suffix=".install.tmp",
                delete=False,
            ) as handle:
                plistlib.dump(render_rearm_launch_agent(plan), handle, sort_keys=False)
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


def uses_runtime_patch(plan: InstallPlan) -> bool:
    return plan.injection_mode == INJECTION_RUNTIME_PATCH


def uses_preload_injection(plan: InstallPlan) -> bool:
    # Kept as a compatibility alias for leftover NODE_OPTIONS cleanup.
    return False


def node_options_require_flag(plan: InstallPlan) -> str:
    return f"--require {plan.paths.preload}"


def merge_node_options(existing: str | None, require_flag: str) -> str:
    parts = [part for part in (existing or "").split() if part]
    flag_parts = require_flag.split()
    if len(flag_parts) >= 2:
        for index, part in enumerate(parts[:-1]):
            if part == flag_parts[0] and parts[index + 1] == flag_parts[1]:
                return " ".join(parts)
    parts.extend(flag_parts)
    return " ".join(parts)


def strip_node_options(existing: str | None, require_flag: str) -> str | None:
    parts = [part for part in (existing or "").split() if part]
    flag_parts = require_flag.split()
    if len(flag_parts) >= 2:
        filtered: list[str] = []
        skip = False
        for index, part in enumerate(parts):
            if skip:
                skip = False
                continue
            if part == flag_parts[0] and index + 1 < len(parts) and parts[index + 1] == flag_parts[1]:
                skip = True
                continue
            filtered.append(part)
        parts = filtered
    return " ".join(parts) or None


def node_options_value(plan: InstallPlan, existing: str | None = None) -> str:
    if existing is None:
        existing = os.environ.get(NODE_OPTIONS_ENV_KEY)
    return merge_node_options(existing, node_options_require_flag(plan))


def env_values(plan: InstallPlan) -> dict[str, str]:
    values = {
        "ZCODE_KEYSMITH_SYSTEM_FILE": str(plan.paths.system_file),
        "ZCODE_KEYSMITH_ORIGINAL": str(plan.zcode_runtime),
        "ZCODE_KEYSMITH_NODE_COMMAND": str(plan.node_command),
        "ZCODE_KEYSMITH_CACHE_DIR": str(plan.paths.cache_dir),
        "ZCODE_KEYSMITH_LOG_DIR": str(plan.paths.log_dir),
    }
    if not uses_runtime_patch(plan):
        values["ZCODE_AGENT_SERVER_COMMAND"] = agent_server_command(plan)
        values["ZCODE_AGENT_SERVER_ARGS_JSON"] = agent_server_args_json(plan)
    return values


def managed_env_keys_for_plan(plan: InstallPlan) -> tuple[str, ...]:
    return tuple(env_values(plan))


def all_managed_env_keys() -> tuple[str, ...]:
    return MANAGED_ENV_KEYS


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
    if uses_runtime_patch(plan):
        lines.append(
            "exec "
            f"{sh_single_quote(str(Path(sys.executable).resolve()))} "
            f"{sh_single_quote(str(installer_copy_path(plan.paths)))} "
            "watch "
            f"--managed-dir {sh_single_quote(str(plan.paths.managed_dir))} "
            f"--zcode-runtime {sh_single_quote(str(plan.zcode_runtime))} "
            f"--node-command {sh_single_quote(str(plan.node_command))} "
            "--yes"
        )
    lines.append("")
    return "\n".join(lines)


def sh_single_quote(value: str) -> str:
    return "'" + value.replace("'", "'\\''") + "'"


def powershell_single_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def render_launch_agent(plan: InstallPlan) -> dict[str, object]:
    if plan.paths.launch_agent is None:
        raise KeysmithError("LaunchAgent is only available on macOS")
    payload: dict[str, object] = {
        "Label": DEFAULT_LAUNCH_AGENT_LABEL,
        "ProgramArguments": [str(plan.paths.env_script)],
        "RunAtLoad": True,
        "StandardOutPath": str(plan.paths.log_dir / "launchagent.out.log"),
        "StandardErrorPath": str(plan.paths.log_dir / "launchagent.err.log"),
    }
    if uses_runtime_patch(plan):
        app = zcode_app_from_runtime(plan.zcode_runtime)
        watch_paths = [str(plan.zcode_runtime)]
        if app is not None and str(app) not in watch_paths:
            watch_paths.append(str(app))
        payload["StartInterval"] = WATCH_START_INTERVAL_SECONDS
        payload["ThrottleInterval"] = WATCH_THROTTLE_INTERVAL_SECONDS
        payload["ExitTimeOut"] = 180
        payload["WatchPaths"] = watch_paths
    return payload


def render_rearm_script(plan: InstallPlan) -> str:
    """Shell watchdog. It only calls launchctl, so a missing Python cannot silence it."""
    if plan.paths.launch_agent is None:
        raise KeysmithError("rearm LaunchAgent is only available on macOS")
    log_path = plan.paths.log_dir / "rearm.log"
    return "\n".join(
        [
            "#!/bin/sh",
            "# Re-load the auto-repatch agent if this GUI session dropped it.",
            "# Do not watch ZCode.app. A bundle swap must not be able to unload this job.",
            "set -u",
            f"PLIST={sh_single_quote(str(plan.paths.launch_agent))}",
            f"LOG={sh_single_quote(str(log_path))}",
            'DOMAIN="gui/$(id -u)"',
            f'TARGET="$DOMAIN/{DEFAULT_LAUNCH_AGENT_LABEL}"',
            "note() {",
            '  mkdir -p "$(dirname "$LOG")" 2>/dev/null || true',
            "  printf '%s %s\\n' \"$(date -u +%Y-%m-%dT%H:%M:%SZ)\" \"$*\" >> \"$LOG\" 2>/dev/null || true",
            "}",
            'if [ ! -f "$PLIST" ]; then',
            "  exit 0",
            "fi",
            'if launchctl print "$TARGET" >/dev/null 2>&1; then',
            "  exit 0",
            "fi",
            "status=0",
            'err=$(launchctl bootstrap "$DOMAIN" "$PLIST" 2>&1) || status=$?',
            'if [ "$status" -eq 0 ]; then',
            '  note "bootstrapped $TARGET"',
            "  exit 0",
            "fi",
            'note "bootstrap failed $TARGET: $err"',
            "exit 0",
            "",
        ]
    )


def render_rearm_launch_agent(plan: InstallPlan) -> dict[str, object]:
    if plan.paths.rearm_launch_agent is None or plan.paths.rearm_script is None:
        raise KeysmithError("rearm LaunchAgent is only available on macOS")
    # No WatchPaths. launchd does not reload ~/Library/LaunchAgents until the next
    # login, so this job only bootstraps the watcher again after the GUI session
    # drops it. It must not watch the app bundle.
    return {
        "Label": DEFAULT_REARM_LAUNCH_AGENT_LABEL,
        "ProgramArguments": [str(plan.paths.rearm_script)],
        "RunAtLoad": True,
        "StartInterval": REARM_START_INTERVAL_SECONDS,
        "ThrottleInterval": WATCH_THROTTLE_INTERVAL_SECONDS,
        "ExitTimeOut": 30,
        "StandardOutPath": str(plan.paths.log_dir / "rearm.out.log"),
        "StandardErrorPath": str(plan.paths.log_dir / "rearm.err.log"),
    }


def render_config(
    plan: InstallPlan,
    previous_user_environment: dict[str, dict[str, object] | None] | None = None,
) -> str:
    payload = {
        "tool_version": VERSION,
        "mode": "zcode-app-runtime-patch" if uses_runtime_patch(plan) else "zcode-app-wrapper",
        "injection_mode": plan.injection_mode,
        "system_file": str(plan.paths.system_file),
        "wrapper": str(plan.paths.wrapper),
        "preload": str(plan.paths.preload),
        "env_script": str(plan.paths.env_script),
        "launch_agent": str(plan.paths.launch_agent) if plan.paths.launch_agent else None,
        "rearm_script": str(plan.paths.rearm_script) if uses_runtime_patch(plan) and plan.paths.rearm_launch_agent else None,
        "rearm_launch_agent": str(plan.paths.rearm_launch_agent) if uses_runtime_patch(plan) and plan.paths.rearm_launch_agent else None,
        "zcode_runtime": str(plan.zcode_runtime),
        "node_command": str(plan.node_command),
        "cache_dir": str(plan.paths.cache_dir),
        "wrapper_log": str(plan.paths.wrapper_log),
        "agent_server_command": None if uses_runtime_patch(plan) else agent_server_command(plan),
        "agent_server_args_json": None if uses_runtime_patch(plan) else agent_server_args_json(plan),
        "node_options": None,
        "runtime_original_backup": str(original_runtime_backup_path(plan)) if uses_runtime_patch(plan) else None,
        "environment": env_values(plan),
        "app_bundle_modified": uses_runtime_patch(plan),
        "python_command": str(Path(sys.executable).resolve()),
        "auto_repatch_watch": uses_runtime_patch(plan) and platform.system() == "Darwin",
        "auto_repatch_rearm": uses_runtime_patch(plan) and platform.system() == "Darwin",
    }
    if platform.system() == "Windows":
        payload["platform"] = "Windows"
        payload["previous_user_environment"] = previous_user_environment or {}
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def render_preload(plan: InstallPlan) -> str:
    system_file_json = json.dumps(str(plan.paths.system_file), ensure_ascii=False)
    log_dir_json = json.dumps(str(plan.paths.log_dir), ensure_ascii=False)
    return (
        "\"use strict\";\n"
        "const fs = require(\"node:fs\");\n"
        "const path = require(\"node:path\");\n"
        f"const SYSTEM_FILE = process.env.ZCODE_KEYSMITH_SYSTEM_FILE || {system_file_json};\n"
        f"const LOG_DIR = process.env.ZCODE_KEYSMITH_LOG_DIR || {log_dir_json};\n"
        "const LOG_FILE = path.join(LOG_DIR, \"wrapper-start.jsonl\");\n"
        "const NEEDLES = [\n"
        "  \"customSystemPrompt:this.config.systemPrompt,workflowActor:this.config.workflowActor,language:\",\n"
        "  \"customSystemPrompt:this.config.systemPrompt,language:\"\n"
        "];\n"
        "\n"
        "function managedPromptExpression() {\n"
        "  const file = JSON.stringify(process.env.ZCODE_KEYSMITH_SYSTEM_FILE || SYSTEM_FILE);\n"
        "  return (\n"
        "    \"(this.config.systemPrompt&&this.config.systemPrompt.trim()?this.config.systemPrompt:\" +\n"
        "    \"(()=>{try{let e=process.env.ZCODE_KEYSMITH_SYSTEM_FILE||\" +\n"
        "    file +\n"
        "    \";let t=require(\\\"node:fs\\\");return t.existsSync(e)?t.readFileSync(e,\\\"utf8\\\"):void 0}catch{return void 0}})())\"\n"
        "  );\n"
        "}\n"
        "\n"
        "function patchSource(source) {\n"
        "  for (const needle of NEEDLES) {\n"
        "    if (!source.includes(needle)) continue;\n"
        "    const suffix = needle.slice(\"customSystemPrompt:this.config.systemPrompt\".length);\n"
        "    const expression = needle === NEEDLES[0]\n"
        "      ? \"this.config.workflowActor===void 0?\" + managedPromptExpression() + \":void 0\"\n"
        "      : managedPromptExpression();\n"
        "    return source.replace(needle, \"customSystemPrompt:\" + expression + suffix);\n"
        "  }\n"
        "  return source;\n"
        "}\n"
        "\n"
        "function logInvocation() {\n"
        "  try {\n"
        "    fs.mkdirSync(LOG_DIR, { recursive: true });\n"
        "    const event = {\n"
        "      started_at: new Date().toISOString(),\n"
        "      pid: process.pid,\n"
        "      argv: process.argv,\n"
        "      agent_args: process.argv.slice(1),\n"
        "      runtime: __filename,\n"
        "      original_runtime: process.env.ZCODE_KEYSMITH_ORIGINAL || null,\n"
        "      system_file: SYSTEM_FILE,\n"
        "      node_command: process.execPath,\n"
        "      injection_mode: \"preload\",\n"
        "    };\n"
        "    fs.appendFileSync(LOG_FILE, JSON.stringify(event) + \"\\n\");\n"
        "  } catch {\n"
        "    // Observability must not block agent-server startup.\n"
        "  }\n"
        "}\n"
        "\n"
        "function shouldAttach() {\n"
        "  const haystack = [process.execPath, ...process.argv].join(\" \\n\");\n"
        "  return /zcode\\.cjs|app-server/.test(haystack);\n"
        "}\n"
        "if (shouldAttach()) {\n"
        "  const Module = require(\"node:module\");\n"
        "  const originalCompile = Module.prototype._compile;\n"
        "  Module.prototype._compile = function (content, filename) {\n"
        "    if (typeof filename === \"string\" && filename.endsWith(\"zcode.cjs\")) {\n"
        "      const patched = patchSource(content);\n"
        "      if (patched !== content) logInvocation();\n"
        "      content = patched;\n"
        "    }\n"
        "    return originalCompile.call(this, content, filename);\n"
        "  };\n"
        "}\n"
    )


def render_wrapper(plan: InstallPlan) -> str:
    runtime_json = json.dumps(str(plan.zcode_runtime), ensure_ascii=False)
    system_file_json = json.dumps(str(plan.paths.system_file), ensure_ascii=False)
    node_command_json = json.dumps(str(plan.node_command), ensure_ascii=False)
    cache_dir_json = json.dumps(str(plan.paths.cache_dir), ensure_ascii=False)
    log_dir_json = json.dumps(str(plan.paths.log_dir), ensure_ascii=False)
    patch_needles_json = json.dumps(list(PATCH_NEEDLES), ensure_ascii=False)
    return f'''#!/usr/bin/env python3
from __future__ import annotations

import datetime
import hashlib
import json
import os
import pathlib
import runpy
import subprocess
import sys
import tempfile
import time

ORIGINAL_RUNTIME = pathlib.Path(os.environ.get("ZCODE_KEYSMITH_ORIGINAL") or {runtime_json})
SYSTEM_FILE = pathlib.Path(os.environ.get("ZCODE_KEYSMITH_SYSTEM_FILE") or {system_file_json})
NODE_COMMAND = os.environ.get("ZCODE_KEYSMITH_NODE_COMMAND") or {node_command_json}
PATCH_NEEDLES = {patch_needles_json}
CACHE_DIR = pathlib.Path(os.environ.get("ZCODE_KEYSMITH_CACHE_DIR") or {cache_dir_json})
LOG_DIR = pathlib.Path(os.environ.get("ZCODE_KEYSMITH_LOG_DIR") or {log_dir_json})
LOG_FILE = LOG_DIR / "wrapper-start.jsonl"


def _stdio_stream(stream):
    """Return the binary OS stream so Windows binds the parent's pipes."""
    return getattr(stream, "buffer", stream)


def _spawn_windows_node(command, env):
    streams = {{
        "stdin": _stdio_stream(sys.stdin),
        "stdout": _stdio_stream(sys.stdout),
        "stderr": _stdio_stream(sys.stderr),
    }}
    for name, stream in streams.items():
        try:
            stream.fileno()
        except (AttributeError, OSError, ValueError) as exc:
            raise RuntimeError("Windows %s stream is not available: %s" % (name, exc)) from exc
    # Keep Python's precise Windows handle-list inheritance while binding only
    # the three streams needed by the long-lived JSON-RPC child.
    return subprocess.Popen(command, env=env, close_fds=True, **streams)


def _frozen_self_dispatch() -> bool:
    # Windows points the agent-server command at the frozen CLI executable.
    # Re-enter the generated wrapper in-process instead of treating its path
    # as an argparse command-line token.
    if not getattr(sys, "frozen", False) or len(sys.argv) < 2:
        return False
    wrapper = pathlib.Path(sys.argv[1])
    if wrapper.name != "zcode-agent-wrapper.py" or not wrapper.is_file():
        return False
    sys.argv = [str(wrapper), *sys.argv[2:]]
    runpy.run_path(str(wrapper), run_name="__main__")
    return True


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
        "(()=>{{try{{let e=process.env.ZCODE_KEYSMITH_SYSTEM_FILE||"
        + system_file
        + ";let t=require(\\\"node:fs\\\");if(t.existsSync(e)){{let x=t.readFileSync(e,\\\"utf8\\\");if(x&&x.trim())return x}}}}catch{{}}return this.config.systemPrompt}})()"
    )


def patched_runtime_path() -> pathlib.Path:
    original = ORIGINAL_RUNTIME.read_text(encoding="utf-8")
    needle = next((item for item in PATCH_NEEDLES if item in original), None)
    if needle is None:
        raise RuntimeError(f"ZCode runtime patch anchor not found: {{ORIGINAL_RUNTIME}}")
    suffix = needle[len("customSystemPrompt:this.config.systemPrompt"):]
    expression = system_prompt_expression()
    if needle == PATCH_NEEDLES[0]:
        expression = "this.config.workflowActor===void 0?" + expression + ":void 0"
    replacement = "customSystemPrompt:" + expression + suffix
    patched = original.replace(needle, replacement, 1)
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
        # Bind all three parent OS handles explicitly. Python 3.14 otherwise
        # starts the child without Electron's redirected JSON-RPC pipes.
        proc = _spawn_windows_node([NODE_COMMAND, str(runtime), *args], env)
        return proc.wait()
    os.execve(NODE_COMMAND, [NODE_COMMAND, str(runtime), *args], env)
    return 127


if __name__ == "__main__":
    if not _frozen_self_dispatch():
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


def tracked_env_keys() -> tuple[str, ...]:
    return (*MANAGED_ENV_KEYS, NODE_OPTIONS_ENV_KEY)


def capture_previous_windows_environment(paths: InstallPaths) -> dict[str, dict[str, object] | None]:
    saved = load_saved_config(paths)
    if saved and saved.get("platform") == "Windows":
        previous = saved.get("previous_user_environment")
        if isinstance(previous, dict):
            return {
                key: previous.get(key) if isinstance(previous.get(key), dict) else None
                for key in tracked_env_keys()
            }
    return {key: get_windows_user_env_entry(key) for key in tracked_env_keys()}


def stale_env_keys(plan: InstallPlan) -> tuple[str, ...]:
    desired = set(env_values(plan))
    return tuple(key for key in tracked_env_keys() if key not in desired)


def activate_current_session(plan: InstallPlan) -> list[str]:
    desired = env_values(plan)
    stale = stale_env_keys(plan)
    if platform.system() == "Windows":
        results = []

        previous = {key: get_windows_user_env_entry(key) for key in tracked_env_keys()}
        changed: list[str] = []
        try:
            for key, value in desired.items():
                set_windows_user_env_entry(key, windows_string_env_entry(value))
                changed.append(key)
                results.append(f"user environment {key}: set")
            for key in stale:
                set_windows_user_env_entry(key, None)
                changed.append(key)
                results.append(f"user environment {key}: cleared")
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
    previous = {key: launchctl_getenv(key) for key in tracked_env_keys()}
    changed: list[str] = []
    try:
        for key, value in desired.items():
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
        for key in stale:
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
            f"preload: {plan.paths.preload}",
            f"env_script: {plan.paths.env_script}",
            f"launch_agent: {plan.paths.launch_agent or 'not used on Windows'}",
            f"rearm_launch_agent: {plan.paths.rearm_launch_agent or 'not used on Windows'}",
            f"zcode_runtime: {plan.zcode_runtime}",
            f"node_command: {plan.node_command}",
            f"cache_dir: {plan.paths.cache_dir}",
            f"wrapper_log: {plan.paths.wrapper_log}",
            f"injection_mode: {plan.injection_mode}",
            f"agent_server_command: {'not used' if uses_runtime_patch(plan) else agent_server_command(plan)}",
            f"agent_server_args_json: {'not used' if uses_runtime_patch(plan) else agent_server_args_json(plan)}",
            "node_options: not used",
            f"activate_current_session: {str(plan.activate).lower()}",
            f"app_bundle_modified: {str(uses_runtime_patch(plan)).lower()}",
            f"auto_repatch_watch: {str(uses_runtime_patch(plan) and platform.system() == 'Darwin').lower()}",
            f"auto_repatch_rearm: {str(uses_runtime_patch(plan) and platform.system() == 'Darwin').lower()}",
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
        if uses_runtime_patch(plan):
            lines.append("effect: official agent-server stays in place; glm/zcode.cjs customSystemPrompt reads the managed system-role first")
            if platform.system() == "Darwin":
                lines.append("effect: macOS LaunchAgent watches glm/zcode.cjs and re-applies the same patch after an official update")
                lines.append("effect: a second LaunchAgent with no WatchPaths bootstraps that watcher again if this GUI session drops it")
        else:
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
        injection_mode=injection_mode_for_app(zcode_app_from_runtime(zcode_runtime)),
    )


def build_watch_plan(args: argparse.Namespace) -> InstallPlan:
    paths = build_paths(expand_path(args.managed_dir), expand_path(args.launch_agent) if args.launch_agent else None)
    zcode_runtime, node_command = runtime_node_from_args(args)
    saved = load_saved_config(paths) or {}
    saved_mode = saved.get("injection_mode")
    if saved_mode in {INJECTION_RUNTIME_PATCH, INJECTION_WRAPPER}:
        mode = str(saved_mode)
    else:
        mode = injection_mode_for_app(zcode_app_from_runtime(zcode_runtime))
    if (
        isinstance(saved.get("zcode_runtime"), str)
        and saved["zcode_runtime"]
        and not getattr(args, "zcode_runtime", None)
        and not getattr(args, "zcode_app", None)
        and not os.environ.get("ZCODE_APP_PATH")
    ):
        zcode_runtime = expand_path(str(saved["zcode_runtime"]))
        if isinstance(saved.get("node_command"), str) and saved["node_command"]:
            node_command = expand_path(str(saved["node_command"]))
    return InstallPlan(
        paths=paths,
        source_system_file=paths.system_file,
        zcode_runtime=zcode_runtime,
        node_command=node_command,
        activate=False,
        injection_mode=mode,
    )


def summarize_auto_repatch(paths: InstallPaths) -> dict[str, object]:
    raw = load_auto_repatch_status(paths)
    if not raw:
        return {
            "last_auto_repatch": "none",
            "last_auto_repatch_status": "none",
            "last_auto_repatch_reason": "no auto-repatch has run yet",
            "last_auto_repatch_at": None,
            "last_auto_repatch_restarted": False,
        }
    status = str(raw.get("status") or "none")
    display = {"patched": "success", "skipped": "skip"}.get(status, status)
    return {
        "last_auto_repatch": display,
        "last_auto_repatch_status": status,
        "last_auto_repatch_reason": raw.get("reason") or "",
        "last_auto_repatch_at": raw.get("checked_at") or raw.get("logged_at"),
        "last_auto_repatch_restarted": bool(raw.get("restarted")),
    }


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
        lines = install_locked(plan, system_prompt)
    if plan.activate:
        lines.extend(bootstrap_launch_agent(plan))
    return lines


def install_locked(plan: InstallPlan, system_prompt: str) -> list[str]:
    previous_user_environment = (
        capture_previous_windows_environment(plan.paths) if platform.system() == "Windows" else None
    )
    for directory in (plan.paths.managed_dir, plan.paths.wrapper.parent, plan.paths.log_dir, plan.paths.cache_dir):
        directory.mkdir(parents=True, exist_ok=True)

    runtime_snapshot = None
    if uses_runtime_patch(plan) and plan.zcode_runtime.exists():
        runtime_snapshot = plan.zcode_runtime.read_text(encoding="utf-8")

    backups, replaced = install_managed_files(plan, system_prompt, render_config(plan, previous_user_environment))
    try:
        if uses_runtime_patch(plan):
            backups.extend(apply_runtime_patch(plan))
        activation = activate_current_session(plan) if plan.activate else []
    except Exception as exc:
        if runtime_snapshot is not None:
            try:
                write_text_atomic(plan.zcode_runtime, runtime_snapshot)
            except OSError:
                pass
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


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def runtime_stat_signature(path: Path) -> tuple[int, int] | None:
    try:
        st = path.stat()
    except OSError:
        return None
    return (st.st_size, int(getattr(st, "st_mtime_ns", int(st.st_mtime * 1_000_000_000))))


def wait_for_runtime_settle(
    path: Path,
    *,
    timeout: float = WATCH_SETTLE_TIMEOUT_SECONDS,
    stable_for: float = WATCH_SETTLE_STABLE_SECONDS,
    poll: float = WATCH_SETTLE_POLL_SECONDS,
    clock=time.monotonic,
    sleeper=time.sleep,
) -> bool:
    """Wait until runtime exists and size+mtime stay still, so ShipIt is done swapping."""
    deadline = clock() + timeout
    last: tuple[int, int] | None = None
    stable_since: float | None = None
    while True:
        now = clock()
        sig = runtime_stat_signature(path)
        if sig is None or sig[0] <= 0:
            last = None
            stable_since = None
        elif sig != last:
            last = sig
            stable_since = now
        elif stable_since is not None and now - stable_since >= stable_for:
            return True
        remaining = deadline - now
        if remaining <= 0:
            return False
        sleeper(min(poll, remaining))


def load_auto_repatch_status(paths: InstallPaths) -> dict[str, object] | None:
    status_file = auto_repatch_status_path(paths)
    if not status_file.is_file():
        return None
    try:
        loaded = json.loads(status_file.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return loaded if isinstance(loaded, dict) else None


def write_auto_repatch_status(paths: InstallPaths, payload: dict[str, object]) -> None:
    paths.log_dir.mkdir(parents=True, exist_ok=True)
    body = dict(payload)
    body.setdefault("schema", AUTO_REPATCH_SCHEMA)
    body.setdefault("keysmith_version", VERSION)
    body.setdefault("checked_at", utc_now_iso())
    previous = load_auto_repatch_status(paths)
    # Periodic already-patched polls must not hide a successful re-patch.
    if previous and body.get("status") == "skipped" and previous.get("status") == "patched":
        previous = dict(previous)
        previous["checked_at"] = body["checked_at"]
        body = previous
    write_text_atomic(auto_repatch_status_path(paths), json.dumps(body, ensure_ascii=False, indent=2) + "\n")


def append_auto_repatch_log(paths: InstallPaths, payload: dict[str, object]) -> None:
    paths.log_dir.mkdir(parents=True, exist_ok=True)
    event = dict(payload)
    event.setdefault("logged_at", utc_now_iso())
    with auto_repatch_log_path(paths).open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False) + "\n")


def persist_runtime_backup(paths: InstallPaths, backup: Path, runtime: Path) -> None:
    config = load_saved_config(paths) or {}
    config["runtime_original_backup"] = str(backup)
    config["zcode_runtime"] = str(runtime)
    config["app_bundle_modified"] = True
    paths.config_file.parent.mkdir(parents=True, exist_ok=True)
    write_text_atomic(paths.config_file, json.dumps(config, ensure_ascii=False, indent=2) + "\n")


def applescript_string(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def notify_user(title: str, message: str, runner=subprocess.run) -> bool:
    if platform.system() != "Darwin":
        return False
    script = f"display notification {applescript_string(message)} with title {applescript_string(title)}"
    try:
        completed = runner(
            ["osascript", "-e", script],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
    except OSError:
        return False
    return completed.returncode == 0


def quit_running_zcode(
    *,
    timeout: float = WATCH_QUIT_TIMEOUT_SECONDS,
    clock=time.monotonic,
    sleeper=time.sleep,
    runner=subprocess.run,
) -> bool:
    if platform.system() != "Darwin":
        return not is_zcode_running()
    try:
        runner(
            ["osascript", "-e", 'tell application "ZCode" to quit'],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
    except OSError:
        pass
    deadline = clock() + timeout
    while clock() < deadline:
        if not is_zcode_running():
            return True
        sleeper(min(0.25, deadline - clock()))
    try:
        runner(["pkill", "-x", "ZCode"], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    except OSError:
        pass
    sleeper(0.4)
    return not is_zcode_running()


def open_zcode_app(app: Path | None, runner=subprocess.run) -> bool:
    if platform.system() != "Darwin":
        return False
    command = ["open", str(app)] if app is not None and app.exists() else ["open", "-a", "ZCode"]
    try:
        completed = runner(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    except OSError:
        return False
    return completed.returncode == 0


def launchd_gui_target(label: str = DEFAULT_LAUNCH_AGENT_LABEL) -> str | None:
    getuid = getattr(os, "getuid", None)
    if not callable(getuid):
        return None
    try:
        uid = getuid()
    except OSError:
        return None
    return f"gui/{uid}/{label}"


def _launchctl(runner, args: list[str]) -> subprocess.CompletedProcess[str]:
    return runner(
        ["launchctl", *args],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def bootstrap_labeled_agent(label: str, plist: Path | None, runner=subprocess.run) -> list[str]:
    if platform.system() != "Darwin" or plist is None or not plist.is_file():
        return []
    target = launchd_gui_target(label)
    if target is None:
        return ["launchctl bootstrap skipped: no launchd user domain"]
    domain = target.rsplit("/", 1)[0]
    try:
        # Drop a stale registration, then load the plist that is on disk now.
        _launchctl(runner, ["bootout", target])
        completed = _launchctl(runner, ["bootstrap", domain, str(plist)])
    except OSError as exc:
        return [f"launchctl bootstrap skipped: {exc}"]
    if completed.returncode == 0:
        return [f"launchctl bootstrap {target}: ok"]
    detail = (completed.stderr or completed.stdout).strip() or f"exit {completed.returncode}"
    return [f"launchctl bootstrap {target}: {detail}"]


def bootout_labeled_agent(label: str, runner=subprocess.run) -> list[str]:
    if platform.system() != "Darwin":
        return []
    target = launchd_gui_target(label)
    if target is None:
        return ["launchctl bootout skipped: no launchd user domain"]
    try:
        completed = _launchctl(runner, ["bootout", target])
    except OSError as exc:
        return [f"launchctl bootout skipped: {exc}"]
    detail = (completed.stderr or completed.stdout).strip()
    if completed.returncode == 0 or "No such process" in detail or "not found" in detail.lower():
        return [f"launchctl bootout {target}: ok"]
    return [f"launchctl bootout {target}: {detail or f'exit {completed.returncode}'}"]


def bootstrap_launch_agent(plan: InstallPlan, runner=subprocess.run) -> list[str]:
    notes = bootstrap_labeled_agent(DEFAULT_LAUNCH_AGENT_LABEL, plan.paths.launch_agent, runner)
    if uses_runtime_patch(plan):
        notes.extend(bootstrap_labeled_agent(DEFAULT_REARM_LAUNCH_AGENT_LABEL, plan.paths.rearm_launch_agent, runner))
    return notes


def bootout_launch_agent(paths: InstallPaths, runner=subprocess.run) -> list[str]:
    # Rearm first. If it stayed loaded it would bootstrap the watch agent again
    # while uninstall is trying to remove that agent.
    notes: list[str] = []
    if paths.rearm_launch_agent is not None:
        notes.extend(bootout_labeled_agent(DEFAULT_REARM_LAUNCH_AGENT_LABEL, runner))
    if paths.launch_agent is not None:
        notes.extend(bootout_labeled_agent(DEFAULT_LAUNCH_AGENT_LABEL, runner))
    return notes


def launch_agent_loaded(label: str, runner=subprocess.run) -> str:
    if platform.system() != "Darwin":
        return "unchecked"
    target = launchd_gui_target(label)
    if target is None:
        return "unchecked"
    try:
        completed = _launchctl(runner, ["print", target])
    except OSError:
        return "unchecked"
    return "true" if completed.returncode == 0 else "false"


def classify_runtime_for_repatch(runtime_text: str) -> str:
    if runtime_text_prefers_managed(runtime_text):
        return "skipped"
    if vendor_patch_anchor(runtime_text) is not None:
        return "patchable"
    return "unknown_hook"


def auto_repatch_result(
    status: str,
    reason: str,
    *,
    runtime: Path | None = None,
    restarted: bool = False,
    notified: bool = False,
    write: bool = False,
    extra: dict[str, object] | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "status": status,
        "reason": reason,
        "runtime": str(runtime) if runtime is not None else None,
        "restarted": restarted,
        "notified": notified,
        "write": write,
    }
    if extra:
        payload.update(extra)
    return payload


def run_auto_repatch(
    plan: InstallPlan,
    *,
    yes: bool,
    dry_run_flag: bool,
    restart: bool = True,
    settle_timeout: float = WATCH_SETTLE_TIMEOUT_SECONDS,
    settle_stable: float = WATCH_SETTLE_STABLE_SECONDS,
    clock=time.monotonic,
    sleeper=time.sleep,
    notifier=notify_user,
    quitter=quit_running_zcode,
    opener=open_zcode_app,
) -> dict[str, object]:
    """Re-apply the known runtime patch after an official ZCode swap. Never guess new anchors."""
    dry_run = dry_run_flag or not yes
    runtime_path = plan.zcode_runtime
    if not uses_runtime_patch(plan):
        result = auto_repatch_result("skipped", "injection mode is wrapper; auto-repatch is for 3.12+ runtime-patch", runtime=runtime_path, write=not dry_run)
        if not dry_run:
            write_auto_repatch_status(plan.paths, result)
            append_auto_repatch_log(plan.paths, result)
        return result
    if not plan.paths.system_file.is_file():
        result = auto_repatch_result("error", f"managed system-role missing: {plan.paths.system_file}", runtime=runtime_path, write=not dry_run)
        if not dry_run:
            write_auto_repatch_status(plan.paths, result)
            append_auto_repatch_log(plan.paths, result)
        return result
    if not wait_for_runtime_settle(
        runtime_path,
        timeout=settle_timeout,
        stable_for=settle_stable,
        clock=clock,
        sleeper=sleeper,
    ):
        result = auto_repatch_result(
            "unsettled",
            "official runtime did not finish settling after a ZCode update",
            runtime=runtime_path,
            write=not dry_run,
        )
        if not dry_run:
            write_auto_repatch_status(plan.paths, result)
            append_auto_repatch_log(plan.paths, result)
        return result
    try:
        runtime_text = read_required_text(runtime_path, "ZCode runtime")
    except KeysmithError as exc:
        result = auto_repatch_result("error", str(exc), runtime=runtime_path, write=not dry_run)
        if not dry_run:
            write_auto_repatch_status(plan.paths, result)
            append_auto_repatch_log(plan.paths, result)
        return result
    kind = classify_runtime_for_repatch(runtime_text)
    if kind == "skipped":
        result = auto_repatch_result("skipped", "runtime already prefers the managed system-role", runtime=runtime_path, write=not dry_run)
        if not dry_run:
            write_auto_repatch_status(plan.paths, result)
            append_auto_repatch_log(plan.paths, result)
        return result
    if kind == "unknown_hook":
        digest = hashlib.sha256(runtime_text.encode("utf-8")).hexdigest()
        reason = (
            "ZCode runtime anchors changed; Keysmith needs an upgrade before it can patch this build. "
            "Auto-repatch did not modify the app."
        )
        previous = load_auto_repatch_status(plan.paths) or {}
        already_reported = previous.get("status") == "unknown_hook" and previous.get("runtime_sha256") == digest
        notified = False
        if not dry_run and not already_reported:
            notified = bool(notifier("zcode-keysmith", "Keysmith 需要升级：ZCode runtime 锚点已变，已跳过自动重打。"))
        result = auto_repatch_result(
            "unknown_hook",
            reason,
            runtime=runtime_path,
            notified=notified,
            write=not dry_run,
            extra={"runtime_sha256": digest},
        )
        if not dry_run:
            write_auto_repatch_status(plan.paths, result)
            append_auto_repatch_log(plan.paths, result)
        return result
    if dry_run:
        return auto_repatch_result(
            "patchable",
            "vendor runtime is a known 3.12/3.14 shape; would patch, backup, and restart if ZCode is running",
            runtime=runtime_path,
            write=False,
        )
    digest = hashlib.sha256(runtime_text.encode("utf-8")).hexdigest()
    backup_path = original_runtime_backup_path(plan, digest)
    was_running = is_zcode_running()
    apply_runtime_patch(plan)
    persist_runtime_backup(plan.paths, backup_path, runtime_path)
    restarted = False
    if restart and was_running:
        if quitter(clock=clock, sleeper=sleeper):
            restarted = bool(opener(zcode_app_from_runtime(runtime_path)))
        else:
            restarted = False
    result = auto_repatch_result(
        "patched",
        "reapplied the known runtime-patch after an official ZCode update",
        runtime=runtime_path,
        restarted=restarted,
        write=True,
        extra={
            "runtime_sha256": digest,
            "runtime_original_backup": str(backup_path),
        },
    )
    write_auto_repatch_status(plan.paths, result)
    append_auto_repatch_log(plan.paths, result)
    return result


def watch(plan: InstallPlan, yes: bool, dry_run_flag: bool, restart: bool = True, **kwargs) -> dict[str, object]:
    dry_run = dry_run_flag or not yes
    if dry_run:
        return run_auto_repatch(plan, yes=False, dry_run_flag=True, restart=restart, **kwargs)
    try:
        with operation_lock(plan.paths):
            return run_auto_repatch(plan, yes=True, dry_run_flag=False, restart=restart, **kwargs)
    except KeysmithError as exc:
        status = "busy" if "already running" in str(exc) else "error"
        result = auto_repatch_result(status, str(exc), runtime=plan.zcode_runtime, write=False)
        try:
            append_auto_repatch_log(plan.paths, result)
            if status != "busy":
                write_auto_repatch_status(plan.paths, result)
        except OSError:
            pass
        return result


def watch_lines(result: dict[str, object], dry_run: bool) -> list[str]:
    lines = ["zcode-keysmith watch preview" if dry_run else "zcode-keysmith watch complete"]
    status = result.get("status", "unknown")
    lines.append(f"status: {status}")
    lines.append(f"reason: {result.get('reason') or ''}")
    lines.append(f"runtime: {result.get('runtime') or 'missing'}")
    lines.append(f"restarted: {str(bool(result.get('restarted'))).lower()}")
    lines.append(f"notified: {str(bool(result.get('notified'))).lower()}")
    lines.append(f"write: {str(bool(result.get('write'))).lower()}")
    backup = result.get("runtime_original_backup")
    if backup:
        lines.append(f"backup: {backup}")
    return lines


def launchctl_getenv(key: str) -> str | None:
    if platform.system() != "Darwin":
        return None
    try:
        completed = subprocess.run(
            ["launchctl", "getenv", key],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
    except OSError:
        # Cross-platform probes may emulate Darwin on a host without launchctl.
        return None
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


def _runtime_cli_prefix_skipped(runtime_text: str) -> bool:
    return bool(_CLI_PREFIX_SKIPPED_RE.search(runtime_text)) and 'name:"Custom System Prompt"' in runtime_text


def _runtime_override_neutralized(runtime_text: str) -> bool:
    return OVERRIDE_NEEDLE not in runtime_text and OVERRIDE_REPL in runtime_text


def _runtime_memory_skipped(runtime_text: str) -> bool:
    body_at = _memory_attach_body_at(runtime_text)
    return body_at is not None and runtime_text.startswith(MEMORY_SKIP_INSERT, body_at)


def doctor_lines(paths: InstallPaths, zcode_runtime: Path, node_command: Path) -> list[str]:
    prompt_hash = file_sha256(paths.system_file)
    runtime_text = ""
    if zcode_runtime.exists() and zcode_runtime.is_file():
        try:
            runtime_text = zcode_runtime.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            runtime_text = ""
    runtime_patchable = runtime_is_patchable_text(runtime_text)
    runtime_patched = runtime_text_prefers_managed(runtime_text)
    expected_plan = InstallPlan(
        paths=paths,
        source_system_file=DEFAULT_SOURCE_SYSTEM_FILE,
        zcode_runtime=zcode_runtime,
        node_command=node_command,
        activate=False,
        injection_mode=injection_mode_for_app(zcode_app_from_runtime(zcode_runtime)),
    )
    expected_env = env_values(expected_plan)
    auto = summarize_auto_repatch(paths)
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
        f"preload: {paths.preload}",
        f"preload_exists: {str(paths.preload.exists()).lower()}",
        f"env_script: {paths.env_script}",
        f"env_script_exists: {str(paths.env_script.exists()).lower()}",
        f"launch_agent: {paths.launch_agent or 'not used on Windows'}",
        f"launch_agent_exists: {str(bool(paths.launch_agent and paths.launch_agent.exists())).lower()}",
        f"rearm_launch_agent: {paths.rearm_launch_agent or 'not used on Windows'}",
        f"rearm_launch_agent_exists: {str(bool(paths.rearm_launch_agent and paths.rearm_launch_agent.exists())).lower()}",
        f"rearm_loaded: {launch_agent_loaded(DEFAULT_REARM_LAUNCH_AGENT_LABEL) if paths.rearm_launch_agent else 'unchecked'}",
        f"zcode_runtime: {zcode_runtime}",
        f"zcode_runtime_exists: {str(zcode_runtime.exists()).lower()}",
        f"zcode_runtime_patchable: {str(runtime_patchable).lower()}",
        f"zcode_runtime_patched: {str(runtime_patched).lower()}",
        f"runtime_cli_prefix_skipped: {str(_runtime_cli_prefix_skipped(runtime_text)).lower()}",
        f"runtime_agentsmd_override_neutralized: {str(_runtime_override_neutralized(runtime_text)).lower()}",
        f"runtime_memory_skipped: {str(_runtime_memory_skipped(runtime_text)).lower()}",
        f"injection_mode: {expected_plan.injection_mode}",
        f"auto_repatch_watch: {str(uses_runtime_patch(expected_plan) and platform.system() == 'Darwin').lower()}",
        f"auto_repatch_rearm: {str(uses_runtime_patch(expected_plan) and platform.system() == 'Darwin').lower()}",
        f"last_auto_repatch: {auto['last_auto_repatch']}",
        f"last_auto_repatch_status: {auto['last_auto_repatch_status']}",
        f"last_auto_repatch_reason: {auto['last_auto_repatch_reason']}",
        f"last_auto_repatch_at: {auto['last_auto_repatch_at'] or 'none'}",
        f"node_command: {node_command}",
        f"node_command_exists: {str(node_command.exists()).lower()}",
        f"app_bundle_modified: {str(uses_runtime_patch(expected_plan) and runtime_patched).lower()}",
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
    for key in stale_env_keys(expected_plan):
        persistent_value = persistent_environment_value(key)
        if persistent_value:
            lines.append(f"persistent.{key}: leftover")
    return lines


def is_agent_server_invocation(event: dict[str, object]) -> bool:
    args = event.get("agent_args")
    if not isinstance(args, list):
        return False
    tokens = [item for item in args if isinstance(item, str)]
    return "app-server" in tokens and "--stdio" in tokens


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
    try:
        completed = subprocess.run(
            command,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return False, f"timeout after {timeout:g}s"
    except OSError as exc:
        return False, f"could not start wrapper: {exc}"
    if completed.returncode == 0:
        return True, "ok"
    detail = (completed.stderr or completed.stdout).strip().splitlines()
    return False, detail[0] if detail else f"exit {completed.returncode}"


def verify_lines(paths: InstallPaths, zcode_runtime: Path, node_command: Path, smoke: bool = True) -> list[str]:
    prompt_hash = file_sha256(paths.system_file)
    zcode_app = zcode_app_from_runtime(zcode_runtime)
    runtime_text = ""
    if zcode_runtime.exists() and zcode_runtime.is_file():
        try:
            runtime_text = zcode_runtime.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            runtime_text = ""
    runtime_patchable = runtime_is_patchable_text(runtime_text)
    runtime_patched = runtime_text_prefers_managed(runtime_text)
    smoke_ok, smoke_detail = run_wrapper_smoke(paths) if smoke else (False, "skipped")
    last_invocation = read_last_wrapper_invocation(paths)
    wrapper_invoked = last_invocation is not None
    injection_mode = injection_mode_for_app(zcode_app)
    lines = [
        "zcode-keysmith verify",
        f"system_file_exists: {str(paths.system_file.exists()).lower()}",
        f"system_file_sha256: {prompt_hash or 'missing'}",
        f"wrapper_exists: {str(paths.wrapper.exists()).lower()}",
        f"preload_exists: {str(paths.preload.exists()).lower()}",
        f"wrapper_smoke: {str(smoke_ok).lower()}",
        f"wrapper_smoke_detail: {smoke_detail}",
        f"wrapper_log: {paths.wrapper_log}",
        f"wrapper_invoked: {str(wrapper_invoked).lower()}",
        f"last_wrapper_start: {last_invocation.get('started_at') if last_invocation else 'missing'}",
        f"zcode_app: {zcode_app or 'unknown'}",
        f"injection_mode: {injection_mode}",
        f"zcode_agent_override_supported: {str(app_supports_agent_server_override(zcode_app)).lower()}",
        f"zcode_storage_startup_required: {str(app_requires_storage_startup(zcode_app)).lower()}",
        f"zcode_runtime_exists: {str(zcode_runtime.exists()).lower()}",
        f"zcode_runtime_patchable: {str(runtime_patchable).lower()}",
        f"zcode_runtime_patched: {str(runtime_patched).lower()}",
        f"node_command_exists: {str(node_command.exists()).lower()}",
        f"zcode_running: {str(is_zcode_running()).lower()}",
        "api_key: not read or stored",
    ]
    if is_zcode_running():
        lines.append("activation_note: reopen ZCode and start a fresh task")
    return lines


def rearm_managed_targets(paths: InstallPaths) -> list[Path]:
    if paths.rearm_launch_agent is None:
        return []
    return [paths.rearm_script, paths.rearm_launch_agent]


def uninstall_lines(paths: InstallPaths, dry_run: bool, removed: list[Path], activation: list[str]) -> list[str]:
    lines = ["zcode-keysmith uninstall preview" if dry_run else "zcode-keysmith uninstall complete"]
    targets = [paths.system_file, paths.config_file, paths.wrapper, paths.preload, paths.env_script, installer_copy_path(paths)]
    if paths.launch_agent is not None:
        targets.append(paths.launch_agent)
    targets.extend(rearm_managed_targets(paths))
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
    for key in tracked_env_keys():
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
    previous = {key: launchctl_getenv(key) for key in tracked_env_keys()}
    changed: list[str] = []
    try:
        for key in tracked_env_keys():
            if key == NODE_OPTIONS_ENV_KEY:
                current = previous.get(key)
                require_flag = None
                config = load_saved_config(paths) or {}
                installed_env = config.get("environment") if isinstance(config.get("environment"), dict) else {}
                installed_options = installed_env.get(NODE_OPTIONS_ENV_KEY) if isinstance(installed_env, dict) else None
                if isinstance(installed_options, str) and "--require " in installed_options:
                    require_flag = installed_options[installed_options.find("--require "):]
                    require_flag = " ".join(require_flag.split()[:2])
                if not require_flag:
                    continue
                restored = strip_node_options(current, require_flag)
                if restored is None:
                    completed = subprocess.run(
                        ["launchctl", "unsetenv", key],
                        text=True,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        check=False,
                    )
                else:
                    completed = subprocess.run(
                        ["launchctl", "setenv", key, restored],
                        text=True,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        check=False,
                    )
                if completed.returncode != 0:
                    detail = (completed.stderr or completed.stdout).strip()
                    raise KeysmithError(f"launchctl NODE_OPTIONS restore failed: {detail}")
                changed.append(key)
                results.append(f"launchctl restore {key}: ok")
                continue
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
    targets = [paths.system_file, paths.config_file, paths.wrapper, paths.preload, paths.env_script, installer_copy_path(paths)]
    if paths.launch_agent is not None:
        targets.append(paths.launch_agent)
    targets.extend(rearm_managed_targets(paths))
    config = load_saved_config(paths)
    bootout_notes = bootout_launch_agent(paths) if activate else []
    restore_notes = restore_runtime_from_config(config)
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
    lines = uninstall_lines(paths, dry_run=False, removed=removed, activation=activation)
    lines.extend(bootout_notes)
    lines.extend(restore_notes)
    return lines


class _ContractArgumentParser(argparse.ArgumentParser):
    """ArgumentParser that records usage errors so ``--json`` callers get JSON."""

    def error(self, message: str) -> None:
        _LAST_USAGE_ERROR[0] = message
        super().error(message)


def _json_dump(payload: dict[str, object]) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def version_report() -> dict[str, object]:
    return _json_report(
        "version",
        "preview",
        True,
        0,
        extra={"version": VERSION, "program": "zcode-keysmith.py"},
    )


def _json_report(
    operation: str,
    mode: str,
    ok: bool,
    exit_status: int,
    *,
    actions: list[dict[str, str]] | None = None,
    warnings: list[str] | None = None,
    blockers: list[str] | None = None,
    error: str | None = None,
    extra: dict[str, object] | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema": JSON_SCHEMA,
        "operation": operation,
        "mode": mode,
        "ok": ok,
        "actions": actions or [],
        "warnings": warnings or [],
        "blockers": blockers or [],
        "exit_status": exit_status,
        "error": error,
    }
    if extra:
        payload.update(extra)
    return payload


def _json_action(action: str, path: Path | str, detail: str = "") -> dict[str, str]:
    return {"action": action, "path": str(path), "detail": detail}


def list_backup_files(paths: InstallPaths) -> list[dict[str, str]]:
    if not paths.managed_dir.exists():
        return []
    backups = []
    for item in sorted(paths.managed_dir.rglob("*")):
        if item.is_file() and ".bak_" in item.name:
            backups.append({"path": str(item), "name": item.name})
    return backups


def install_report(plan: InstallPlan, dry_run: bool, backups: list[Path], activation: list[str]) -> dict[str, object]:
    action_name = "plan" if dry_run else "write"
    actions = [
        _json_action(action_name, plan.paths.system_file, "system_file"),
        _json_action(action_name, plan.paths.config_file, "config_file"),
        _json_action(action_name, plan.paths.wrapper, "wrapper"),
        _json_action(action_name, plan.paths.preload, "preload"),
        _json_action(action_name, plan.paths.env_script, "env_script"),
    ]
    if uses_runtime_patch(plan) and platform.system() == "Darwin":
        actions.append(_json_action(action_name, installer_copy_path(plan.paths), "installer_copy"))
    if plan.paths.launch_agent is not None:
        actions.append(_json_action(action_name, plan.paths.launch_agent, "launch_agent"))
    if uses_runtime_patch(plan):
        for path in rearm_managed_targets(plan.paths):
            kind = "rearm_launch_agent" if path == plan.paths.rearm_launch_agent else "rearm_script"
            actions.append(_json_action(action_name, path, kind))
    for backup in backups:
        actions.append(_json_action("backup", backup, "backup"))
    return _json_report(
        "install",
        "preview" if dry_run else "execute",
        True,
        0,
        actions=actions,
        extra={
            "managed_dir": str(plan.paths.managed_dir),
            "source_system_file": str(plan.source_system_file),
            "zcode_runtime": str(plan.zcode_runtime),
            "node_command": str(plan.node_command),
            "activate": plan.activate,
            "write": not dry_run,
            "activation": activation,
            "backups": [str(path) for path in backups],
            "injection_mode": plan.injection_mode,
            "zcode_running": is_zcode_running(),
            "auto_repatch_watch": uses_runtime_patch(plan) and platform.system() == "Darwin",
        },
    )


def doctor_report(paths: InstallPaths, zcode_runtime: Path, node_command: Path) -> dict[str, object]:
    prompt_hash = file_sha256(paths.system_file)
    runtime_text = ""
    if zcode_runtime.exists() and zcode_runtime.is_file():
        try:
            runtime_text = zcode_runtime.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            runtime_text = ""
    runtime_patchable = runtime_is_patchable_text(runtime_text)
    runtime_patched = runtime_text_prefers_managed(runtime_text)
    expected_plan = InstallPlan(
        paths=paths,
        source_system_file=DEFAULT_SOURCE_SYSTEM_FILE,
        zcode_runtime=zcode_runtime,
        node_command=node_command,
        activate=False,
        injection_mode=injection_mode_for_app(zcode_app_from_runtime(zcode_runtime)),
    )
    expected_env = env_values(expected_plan)
    env: dict[str, object] = {}
    for key, expected in expected_env.items():
        current = os.environ.get(key)
        persistent_value = persistent_environment_value(key)
        if persistent_value == expected:
            persistent = "matches"
        elif not persistent_value:
            persistent = "not_set"
        else:
            persistent = "different"
        env[key] = {
            "session": "set" if current else "not_set",
            "persistent": persistent,
            "expected": expected,
        }
    managed = {
        "dir": str(paths.managed_dir),
        "system_file": str(paths.system_file),
        "system_file_exists": paths.system_file.exists(),
        "system_file_sha256": prompt_hash,
        "config_file": str(paths.config_file),
        "config_file_exists": paths.config_file.exists(),
        "wrapper": str(paths.wrapper),
        "wrapper_exists": paths.wrapper.exists(),
        "preload": str(paths.preload),
        "preload_exists": paths.preload.exists(),
        "env_script": str(paths.env_script),
        "env_script_exists": paths.env_script.exists(),
        "launch_agent": str(paths.launch_agent) if paths.launch_agent else None,
        "launch_agent_exists": bool(paths.launch_agent and paths.launch_agent.exists()),
        "rearm_launch_agent": str(paths.rearm_launch_agent) if paths.rearm_launch_agent else None,
        "rearm_launch_agent_exists": bool(paths.rearm_launch_agent and paths.rearm_launch_agent.exists()),
        "rearm_loaded": launch_agent_loaded(DEFAULT_REARM_LAUNCH_AGENT_LABEL) if paths.rearm_launch_agent else "unchecked",
        "cache_dir": str(paths.cache_dir),
        "wrapper_log": str(paths.wrapper_log),
    }
    runtime = {
        "path": str(zcode_runtime),
        "exists": zcode_runtime.exists(),
        "patchable": runtime_patchable,
        "patched": runtime_patched,
        "cli_prefix_skipped": _runtime_cli_prefix_skipped(runtime_text),
        "agentsmd_override_neutralized": _runtime_override_neutralized(runtime_text),
        "memory_skipped": _runtime_memory_skipped(runtime_text),
        "injection_mode": expected_plan.injection_mode,
        "storage_startup_required": app_requires_storage_startup(zcode_app_from_runtime(zcode_runtime)),
        "node_command": str(node_command),
        "node_command_exists": node_command.exists(),
    }
    blockers: list[str] = []
    for label, present in (
        ("managed system file", paths.system_file.is_file()),
        ("managed config file", paths.config_file.is_file()),
        ("managed wrapper", paths.wrapper.is_file()),
        ("managed environment script", paths.env_script.is_file()),
    ):
        if not present:
            blockers.append(f"{label} missing: {paths.managed_dir}")
    if paths.launch_agent is not None and not paths.launch_agent.is_file():
        blockers.append(f"LaunchAgent missing: {paths.launch_agent}")
    elif (
        uses_runtime_patch(expected_plan)
        and paths.launch_agent is not None
        and paths.launch_agent.is_file()
        and paths.rearm_launch_agent is not None
        and not paths.rearm_launch_agent.is_file()
    ):
        blockers.append(f"rearm LaunchAgent missing: {paths.rearm_launch_agent}")
    if not zcode_runtime.is_file():
        blockers.append(f"ZCode runtime missing: {zcode_runtime}")
    elif not runtime_patchable:
        blockers.append(f"ZCode runtime is not patchable: {zcode_runtime}")
    if not node_command.is_file():
        blockers.append(f"ZCode node command missing: {node_command}")
    return _json_report(
        "doctor",
        "preview",
        not blockers,
        0 if not blockers else 1,
        blockers=blockers,
        extra={
            "managed": managed,
            "runtime": runtime,
            "env": env,
            "backups": list_backup_files(paths),
            "app_bundle_modified": uses_runtime_patch(expected_plan) and runtime_patched,
            "auto_repatch_watch": uses_runtime_patch(expected_plan) and platform.system() == "Darwin",
            "auto_repatch_rearm": uses_runtime_patch(expected_plan) and platform.system() == "Darwin",
            **summarize_auto_repatch(paths),
        },
    )


def verify_report(paths: InstallPaths, zcode_runtime: Path, node_command: Path, smoke: bool = True) -> dict[str, object]:
    prompt_hash = file_sha256(paths.system_file)
    zcode_app = zcode_app_from_runtime(zcode_runtime)
    runtime_text = ""
    if zcode_runtime.exists() and zcode_runtime.is_file():
        try:
            runtime_text = zcode_runtime.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            runtime_text = ""
    runtime_patchable = runtime_is_patchable_text(runtime_text)
    runtime_patched = runtime_text_prefers_managed(runtime_text)
    smoke_ok, smoke_detail = run_wrapper_smoke(paths) if smoke else (False, "skipped")
    last_invocation = read_last_wrapper_invocation(paths)
    injection_mode = injection_mode_for_app(zcode_app)
    blockers: list[str] = []
    if not paths.system_file.is_file():
        blockers.append(f"managed system file missing: {paths.system_file}")
    if not paths.wrapper.is_file():
        blockers.append(f"managed wrapper missing: {paths.wrapper}")
    if not zcode_runtime.is_file():
        blockers.append(f"ZCode runtime missing: {zcode_runtime}")
    elif injection_mode == INJECTION_RUNTIME_PATCH and not runtime_patched:
        blockers.append(f"ZCode runtime is not Keysmith-patched: {zcode_runtime}")
    elif injection_mode != INJECTION_RUNTIME_PATCH and not runtime_patchable:
        blockers.append(f"ZCode runtime is not patchable: {zcode_runtime}")
    if not node_command.is_file():
        blockers.append(f"ZCode node command missing: {node_command}")
    if smoke and not smoke_ok:
        blockers.append(f"wrapper smoke failed: {smoke_detail}")
    return _json_report(
        "verify",
        "preview",
        not blockers,
        0 if not blockers else 1,
        blockers=blockers,
        extra={
            "managed_dir": str(paths.managed_dir),
            "system_file_exists": paths.system_file.exists(),
            "system_file_sha256": prompt_hash,
            "wrapper_exists": paths.wrapper.exists(),
            "preload_exists": paths.preload.exists(),
            "wrapper_smoke": smoke_ok,
            "wrapper_smoke_detail": smoke_detail,
            "wrapper_log": str(paths.wrapper_log),
            "wrapper_invoked": last_invocation is not None,
            "last_wrapper_start": last_invocation.get("started_at") if last_invocation else None,
            "zcode_app": str(zcode_app) if zcode_app else None,
            "zcode_agent_override_supported": app_supports_agent_server_override(zcode_app),
            "zcode_storage_startup_required": app_requires_storage_startup(zcode_app),
            "injection_mode": injection_mode_for_app(zcode_app),
            "zcode_runtime_exists": zcode_runtime.exists(),
            "zcode_runtime_patchable": runtime_patchable,
            "zcode_runtime_patched": runtime_patched,
            "node_command_exists": node_command.exists(),
            "zcode_running": is_zcode_running(),
            "backups": list_backup_files(paths),
        },
    )


def watch_report(plan: InstallPlan, dry_run: bool, result: dict[str, object]) -> dict[str, object]:
    status = str(result.get("status") or "unknown")
    ok = status in {"patched", "skipped", "patchable", "busy"}
    extra = {
        "managed_dir": str(plan.paths.managed_dir),
        "runtime": result.get("runtime"),
        "status": status,
        "reason": result.get("reason"),
        "restarted": bool(result.get("restarted")),
        "notified": bool(result.get("notified")),
        "write": bool(result.get("write")),
        "runtime_original_backup": result.get("runtime_original_backup"),
        "last_auto_repatch": summarize_auto_repatch(plan.paths)["last_auto_repatch"] if not dry_run else {"patched": "success", "skipped": "skip", "patchable": "success"}.get(status, status),
    }
    return _json_report(
        "watch",
        "preview" if dry_run else "execute",
        ok,
        0 if ok else 1,
        extra=extra,
        blockers=[] if ok else [str(result.get("reason") or status)],
    )


def uninstall_report(paths: InstallPaths, dry_run: bool, removed: list[Path], activation: list[str]) -> dict[str, object]:
    action_name = "plan" if dry_run else "remove"
    targets = [paths.system_file, paths.config_file, paths.wrapper, paths.preload, paths.env_script, installer_copy_path(paths)]
    if paths.launch_agent is not None:
        targets.append(paths.launch_agent)
    targets.extend(rearm_managed_targets(paths))
    actions = [_json_action(action_name, path, "target") for path in targets]
    for path in removed:
        actions.append(_json_action("removed", path, "removed"))
    return _json_report(
        "uninstall",
        "preview" if dry_run else "execute",
        True,
        0,
        actions=actions,
        extra={
            "managed_dir": str(paths.managed_dir),
            "write": not dry_run,
            "removed": [str(path) for path in removed],
            "activation": activation,
            "backups": list_backup_files(paths),
        },
    )


def build_parser() -> argparse.ArgumentParser:
    parser = _ContractArgumentParser(description="Install or inspect zcode-keysmith managed ZCode App system-role entrypoint.")
    parser.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")
    parser.add_argument("--json", action="store_true", help="Emit stable JSON (zcode-keysmith/v1)")
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
    install_parser.add_argument("--json", action="store_true", help="Emit stable JSON (zcode-keysmith/v1)")

    doctor_parser = sub.add_parser("doctor", help="Inspect managed install state")
    doctor_parser.add_argument("--managed-dir", default=str(DEFAULT_MANAGED_DIR))
    doctor_parser.add_argument("--launch-agent", default=None)
    doctor_parser.add_argument("--zcode-app", default=None)
    doctor_parser.add_argument("--zcode-runtime", default=None)
    doctor_parser.add_argument("--node-command", default=None)
    doctor_parser.add_argument("--json", action="store_true", help="Emit stable JSON (zcode-keysmith/v1)")

    verify_parser = sub.add_parser("verify", help="Run local wrapper/runtime verification without sending model requests")
    verify_parser.add_argument("--managed-dir", default=str(DEFAULT_MANAGED_DIR))
    verify_parser.add_argument("--launch-agent", default=None)
    verify_parser.add_argument("--zcode-app", default=None)
    verify_parser.add_argument("--zcode-runtime", default=None)
    verify_parser.add_argument("--node-command", default=None)
    verify_parser.add_argument("--no-smoke", action="store_true", help="Skip local wrapper --help smoke test")
    verify_parser.add_argument("--json", action="store_true", help="Emit stable JSON (zcode-keysmith/v1)")

    uninstall_parser = sub.add_parser("uninstall", help="Back up managed files and unset current environment")
    uninstall_parser.add_argument("--managed-dir", default=str(DEFAULT_MANAGED_DIR))
    uninstall_parser.add_argument("--launch-agent", default=None)
    uninstall_parser.add_argument("--zcode-app", default=None)
    uninstall_parser.add_argument("--zcode-runtime", default=None)
    uninstall_parser.add_argument("--node-command", default=None)
    uninstall_parser.add_argument("--dry-run", action="store_true")
    uninstall_parser.add_argument("--yes", action="store_true")
    uninstall_parser.add_argument("--no-activate", action="store_true")
    uninstall_parser.add_argument("--json", action="store_true", help="Emit stable JSON (zcode-keysmith/v1)")

    watch_parser = sub.add_parser("watch", help="Re-apply the runtime patch after an official ZCode update (macOS LaunchAgent)")
    watch_parser.add_argument("--managed-dir", default=str(DEFAULT_MANAGED_DIR))
    watch_parser.add_argument("--launch-agent", default=None)
    watch_parser.add_argument("--zcode-app", default=None)
    watch_parser.add_argument("--zcode-runtime", default=None)
    watch_parser.add_argument("--node-command", default=None)
    watch_parser.add_argument("--dry-run", action="store_true")
    watch_parser.add_argument("--yes", action="store_true", help="Allow writing the runtime patch. --dry-run wins if both are provided")
    watch_parser.add_argument("--no-restart", action="store_true", help="Do not quit and reopen ZCode after a successful patch")
    watch_parser.add_argument("--json", action="store_true", help="Emit stable JSON (zcode-keysmith/v1)")

    return parser


def _usage_error_mode(argv: list[str]) -> str:
    return "preview" if "--yes" not in argv or "--dry-run" in argv else "execute"


def _operation_from_argv(argv: list[str]) -> str:
    for item in argv:
        if item in {"install", "doctor", "verify", "uninstall", "watch"}:
            return item
    return "unknown"


def _run_frozen_wrapper_dispatch() -> bool:
    """Run a generated wrapper when the Windows sidecar is self-dispatched."""
    if not getattr(sys, "frozen", False) or len(sys.argv) < 2:
        return False
    wrapper = Path(sys.argv[1])
    if wrapper.name != DEFAULT_WRAPPER_NAME:
        return False
    if not wrapper.is_file():
        raise SystemExit(f"zcode-keysmith wrapper not found: {wrapper}")
    sys.argv = [str(wrapper), *sys.argv[2:]]
    try:
        runpy.run_path(str(wrapper), run_name="__main__")
    except SystemExit:
        raise
    return True


def main(argv: Iterable[str] | None = None) -> int:
    parser = build_parser()
    argv_list = list(sys.argv[1:] if argv is None else argv)
    json_requested = "--json" in argv_list
    if "--version" in argv_list and json_requested:
        _json_dump(version_report())
        return 0
    if json_requested:
        operation = _operation_from_argv(argv_list)
        try:
            args = parser.parse_args(argv_list)
        except SystemExit as exit_request:
            status = exit_request.code if isinstance(exit_request.code, int) else 2
            if status == 0:
                raise
            _json_dump(
                _json_report(
                    operation,
                    _usage_error_mode(argv_list),
                    False,
                    status,
                    error=_LAST_USAGE_ERROR[0] or "argument validation failed",
                    blockers=[_LAST_USAGE_ERROR[0] or "argument validation failed"],
                )
            )
            return status
    else:
        args = parser.parse_args(argv_list)

    use_json = json_requested or bool(getattr(args, "json", False))
    try:
        command = getattr(args, "command", None)
        if command is None:
            if use_json:
                _json_dump(
                    _json_report(
                        "unknown",
                        "preview",
                        False,
                        1,
                        error="missing command",
                        blockers=["missing command"],
                    )
                )
                return 1
            command = "doctor"
        if command == "install":
            plan = build_install_plan(args)
            dry_run = args.dry_run or not args.yes
            lines = install(plan, yes=args.yes, dry_run_flag=args.dry_run)
            if use_json:
                backups = [Path(line.split(": ", 1)[1]) for line in lines if line.startswith("backup: ")]
                activation = [
                    line for line in lines
                    if line.startswith("launchctl ")
                    or line.startswith("user environment ")
                    or line.startswith("user environment:")
                ]
                _json_dump(install_report(plan, dry_run, backups, activation))
                return 0
            print("\n".join(lines))
            return 0
        if command == "doctor":
            paths = build_paths(expand_path(args.managed_dir), expand_path(args.launch_agent) if args.launch_agent else None)
            zcode_runtime, node_command = runtime_node_from_args(args)
            if use_json:
                report = doctor_report(paths, zcode_runtime, node_command)
                _json_dump(report)
                return int(report["exit_status"])
            print("\n".join(doctor_lines(paths, zcode_runtime, node_command)))
            return 0
        if command == "verify":
            paths = build_paths(expand_path(args.managed_dir), expand_path(args.launch_agent) if args.launch_agent else None)
            zcode_runtime, node_command = runtime_node_from_args(args)
            if use_json:
                report = verify_report(paths, zcode_runtime, node_command, smoke=not args.no_smoke)
                _json_dump(report)
                return int(report["exit_status"])
            print("\n".join(verify_lines(paths, zcode_runtime, node_command, smoke=not args.no_smoke)))
            return 0
        if command == "watch":
            plan = build_watch_plan(args)
            dry_run = args.dry_run or not args.yes
            result = watch(plan, yes=args.yes, dry_run_flag=args.dry_run, restart=not args.no_restart)
            if use_json:
                report = watch_report(plan, dry_run, result)
                _json_dump(report)
                return int(report["exit_status"])
            print("\n".join(watch_lines(result, dry_run=dry_run)))
            return 0 if str(result.get("status")) in {"patched", "skipped", "patchable", "busy"} else 1
        if command == "uninstall":
            paths = build_paths(expand_path(args.managed_dir), expand_path(args.launch_agent) if args.launch_agent else None)
            dry_run = args.dry_run or not args.yes
            lines = uninstall(paths, yes=args.yes, dry_run_flag=args.dry_run, activate=not args.no_activate)
            if use_json:
                removed = [Path(line.split(": ", 1)[1]) for line in lines if line.startswith("removed: ")]
                activation = [
                    line for line in lines
                    if line.startswith("launchctl ")
                    or line.startswith("user environment ")
                    or line.startswith("user environment:")
                ]
                _json_dump(uninstall_report(paths, dry_run, removed, activation))
                return 0
            print("\n".join(lines))
            return 0
        if use_json:
            _json_dump(
                _json_report(
                    "unknown",
                    "preview",
                    False,
                    1,
                    error="missing command",
                    blockers=["missing command"],
                )
            )
            return 1
        parser.print_help()
        return 1
    except KeysmithError as exc:
        if use_json:
            _json_dump(
                _json_report(
                    getattr(args, "command", None) or "unknown",
                    _usage_error_mode(argv_list),
                    False,
                    2,
                    error=str(exc),
                    blockers=[str(exc)],
                )
            )
            return 2
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    if not _run_frozen_wrapper_dispatch():
        raise SystemExit(main())
