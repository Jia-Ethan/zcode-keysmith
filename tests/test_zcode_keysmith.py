from __future__ import annotations

import importlib.util
import json
import os
import plistlib
import py_compile
import subprocess
import sys
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).resolve().parents[1] / "zcode-keysmith.py"
spec = importlib.util.spec_from_file_location("zcode_keysmith", MODULE_PATH)
assert spec and spec.loader
mod = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = mod
spec.loader.exec_module(mod)


@pytest.fixture(autouse=True)
def isolate_zcode_environment(monkeypatch):
    for key in mod.MANAGED_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


def make_runtime(path: Path) -> None:
    path.write_text(
        "const x={customSystemPrompt:this.config.systemPrompt,language:this.config.language};\n",
        encoding="utf-8",
    )


def test_cli_reports_release_version():
    completed = subprocess.run(
        [sys.executable, str(MODULE_PATH), "--version"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    assert completed.returncode == 0
    assert completed.stdout.strip() == "zcode-keysmith.py 0.1.0"
    assert completed.stderr == ""
    assert mod.VERSION == (MODULE_PATH.parent / "VERSION").read_text(encoding="ascii").strip()


def test_normalizes_glm_chatml_system_wrapper_for_installed_prompt():
    raw = "<|im_start|>system:<project_instructions>\n# Body\n<|im_end|>\n"

    normalized = mod.normalize_system_prompt_content(raw)

    assert normalized == "<project_instructions>\n# Body\n"
    assert "<|im_start|>" not in normalized
    assert "<|im_end|>" not in normalized


def test_patch_rewrites_custom_system_prompt_to_managed_file():
    original = "const x={customSystemPrompt:this.config.systemPrompt,language:this.config.language};"

    patched = mod.build_patched_runtime_text(original, "/tmp/system-role.md")

    assert "customSystemPrompt:(this.config.systemPrompt" in patched
    assert "ZCODE_KEYSMITH_SYSTEM_FILE" in patched
    assert "readFileSync" in patched
    assert "customSystemPrompt:this.config.systemPrompt" not in patched


def test_patch_requires_known_runtime_anchor():
    try:
        mod.build_patched_runtime_text("const x = 1;", "/tmp/system-role.md")
    except mod.KeysmithError as exc:
        assert "anchor" in str(exc)
    else:
        raise AssertionError("patching should require the ZCode runtime anchor")


def test_install_dry_run_does_not_write(tmp_path, capsys):
    runtime = tmp_path / "zcode.cjs"
    make_runtime(runtime)
    source = tmp_path / "source.md"
    source.write_text("# system\n", encoding="utf-8")
    node_command = tmp_path / "node"
    node_command.write_text("#!/bin/sh\n", encoding="utf-8")
    node_command.chmod(0o755)
    managed = tmp_path / "managed"
    launch_agent = tmp_path / "agent.plist"

    code = mod.main([
        "install",
        "--system-file", str(source),
        "--managed-dir", str(managed),
        "--launch-agent", str(launch_agent),
        "--zcode-runtime", str(runtime),
        "--node-command", str(node_command),
        "--dry-run",
    ])

    out = capsys.readouterr().out
    assert code == 0
    assert "zcode-keysmith install preview" in out
    assert "write: false" in out
    assert not managed.exists()
    assert not launch_agent.exists()


def test_install_writes_wrapper_launch_agent_and_config(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(mod.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(mod, "is_zcode_running", lambda: False)
    runtime = tmp_path / "zcode.cjs"
    make_runtime(runtime)
    source = tmp_path / "source.md"
    source.write_text("# managed system\n", encoding="utf-8")
    node_command = tmp_path / "node"
    node_command.write_text("#!/bin/sh\n", encoding="utf-8")
    node_command.chmod(0o755)
    managed = tmp_path / "managed"
    launch_agent = tmp_path / "agent.plist"

    code = mod.main([
        "install",
        "--system-file", str(source),
        "--managed-dir", str(managed),
        "--launch-agent", str(launch_agent),
        "--zcode-runtime", str(runtime),
        "--node-command", str(node_command),
        "--yes",
        "--no-activate",
    ])

    out = capsys.readouterr().out
    assert code == 0
    assert "zcode-keysmith install complete" in out
    assert (managed / "system-role.md").read_text(encoding="utf-8") == "# managed system\n"
    wrapper = managed / "bin" / "zcode-agent-wrapper.py"
    env_script = managed / "bin" / "zcode-keysmith-env.sh"
    config = json.loads((managed / "config.json").read_text(encoding="utf-8"))
    plist = plistlib.loads(launch_agent.read_bytes())

    assert wrapper.exists()
    assert env_script.exists()
    assert "ZCODE_KEYSMITH_SYSTEM_FILE" in wrapper.read_text(encoding="utf-8")
    assert "launchctl setenv ZCODE_AGENT_SERVER_COMMAND" in env_script.read_text(encoding="utf-8")
    assert config["tool_version"] == mod.VERSION
    assert config["mode"] == "zcode-app-wrapper"
    assert config["app_bundle_modified"] is False
    assert plist["Label"] == "com.jia.zcode-keysmith.env"
    assert plist["ProgramArguments"] == [str(env_script)]


def test_rendered_wrapper_is_valid_python_and_uses_configured_cache_dir(tmp_path):
    runtime = tmp_path / "zcode.cjs"
    make_runtime(runtime)
    source = tmp_path / "source.md"
    source.write_text("# system\n", encoding="utf-8")
    node_command = tmp_path / "node"
    node_command.write_text("#!/bin/sh\n", encoding="utf-8")
    node_command.chmod(0o755)
    paths = mod.build_paths(tmp_path / "managed", tmp_path / "agent.plist")
    plan = mod.InstallPlan(
        paths=paths,
        source_system_file=source,
        zcode_runtime=runtime,
        node_command=node_command,
        activate=False,
    )

    wrapper_text = mod.render_wrapper(plan)
    wrapper_file = tmp_path / "wrapper.py"
    wrapper_file.write_text(wrapper_text, encoding="utf-8")

    py_compile.compile(str(wrapper_file), doraise=True)
    assert "\x00" not in wrapper_text
    assert "ZCODE_KEYSMITH_CACHE_DIR" in wrapper_text
    assert json.dumps(str(paths.cache_dir), ensure_ascii=False) in wrapper_text
    assert 'if os.name == "nt":' in wrapper_text
    assert "acquire_cache_lock" in wrapper_text
    assert "subprocess.Popen" in wrapper_text
    assert "proc.wait()" in wrapper_text
    # Popen inherits stdin/stdout/stderr directly for stable JSON-RPC communication
    assert "env=env" in wrapper_text


def test_rendered_wrapper_cache_write_is_safe_under_concurrent_start(tmp_path):
    runtime = tmp_path / "zcode.cjs"
    runtime.write_text(
        "MARKER = '''customSystemPrompt:this.config.systemPrompt,language:'''\n"
        + "# "
        + "x" * (4 * 1024 * 1024)
        + "\n",
        encoding="utf-8",
    )
    source = tmp_path / "source.md"
    source.write_text("# system\n", encoding="utf-8")
    node_command = Path(sys.executable)
    paths = mod.build_paths(tmp_path / "managed", tmp_path / "agent.plist")
    paths.wrapper.parent.mkdir(parents=True)
    plan = mod.InstallPlan(paths, source, runtime, node_command, False)
    paths.wrapper.write_text(mod.render_wrapper(plan), encoding="utf-8")

    processes = [
        subprocess.Popen(
            [sys.executable, str(paths.wrapper), "--help"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        for _ in range(24)
    ]
    results = [process.communicate(timeout=20) + (process.returncode,) for process in processes]

    assert all(returncode == 0 for _, _, returncode in results), results
    assert len(list(paths.cache_dir.glob("zcode-keysmith-runtime-*.cjs"))) == 1
    assert not list(paths.cache_dir.glob("*.tmp"))
    assert len(list(paths.cache_dir.glob(".*.lock"))) == 1


@pytest.mark.skipif(sys.platform != "win32", reason="Windows-only wrapper process semantics")
def test_windows_wrapper_inherits_stdio_and_propagates_exit_code(tmp_path):
    runtime = tmp_path / "zcode.cjs"
    runtime.write_text(
        "MARKER = '''customSystemPrompt:this.config.systemPrompt,language:'''\n"
        "import sys\n"
        "payload = sys.stdin.buffer.read()\n"
        "sys.stdout.buffer.write(payload.upper())\n"
        "sys.stdout.buffer.flush()\n"
        "raise SystemExit(23)\n",
        encoding="utf-8",
    )
    source = tmp_path / "source.md"
    source.write_text("# system\n", encoding="utf-8")
    paths = mod.build_paths(tmp_path / "managed")
    paths.wrapper.parent.mkdir(parents=True)
    plan = mod.InstallPlan(paths, source, runtime, Path(sys.executable), False)
    paths.wrapper.write_text(mod.render_wrapper(plan), encoding="utf-8")

    env = {
        **os.environ,
        "ZCODE_KEYSMITH_NODE_COMMAND": sys.executable,
    }
    completed = subprocess.run(
        [sys.executable, str(paths.wrapper), "app-server", "--stdio"],
        input=b"json-rpc-stdio",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        env=env,
    )

    assert completed.returncode == 23
    assert completed.stdout == b"JSON-RPC-STDIO"
    assert completed.stderr == b""


def test_doctor_reports_state_without_secret_values(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "TEST_OPENAI_KEY_REDACTED")
    runtime = tmp_path / "zcode.cjs"
    make_runtime(runtime)
    node_command = tmp_path / "node"
    node_command.write_text("#!/bin/sh\n", encoding="utf-8")
    node_command.chmod(0o755)
    managed = tmp_path / "managed"
    managed.mkdir()
    (managed / "system-role.md").write_text("# system\n", encoding="utf-8")
    launch_agent = tmp_path / "agent.plist"

    code = mod.main([
        "doctor",
        "--managed-dir", str(managed),
        "--launch-agent", str(launch_agent),
        "--zcode-runtime", str(runtime),
        "--node-command", str(node_command),
    ])

    out = capsys.readouterr().out
    assert code == 0
    assert "zcode-keysmith doctor" in out
    assert "zcode_runtime_patchable: true" in out
    assert "api_key: not read or stored" in out
    assert "TEST_OPENAI_KEY_REDACTED" not in out


def test_resolve_zcode_app_path_derives_runtime_and_node_command(tmp_path, monkeypatch):
    monkeypatch.setattr(mod.platform, "system", lambda: "Darwin")
    app = tmp_path / "ZCode.app"
    runtime = app / "Contents" / "Resources" / "glm" / "zcode.cjs"
    node = app / "Contents" / "MacOS" / "ZCode"
    helper = app / "Contents" / "Frameworks" / "ZCode Helper.app" / "Contents" / "MacOS" / "ZCode Helper"
    runtime.parent.mkdir(parents=True)
    node.parent.mkdir(parents=True)
    helper.parent.mkdir(parents=True)
    make_runtime(runtime)
    node.write_text("#!/bin/sh\n", encoding="utf-8")
    node.chmod(0o755)
    helper.write_text("#!/bin/sh\n", encoding="utf-8")
    helper.chmod(0o755)

    resolved_runtime, resolved_node = mod.resolve_zcode_bundle_paths(app)

    assert resolved_runtime == runtime.resolve()
    assert resolved_node == helper.resolve()


def test_resolve_zcode_app_path_falls_back_to_main_executable_when_helper_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(mod.platform, "system", lambda: "Darwin")
    app = tmp_path / "ZCode.app"
    runtime = app / "Contents" / "Resources" / "glm" / "zcode.cjs"
    node = app / "Contents" / "MacOS" / "ZCode"
    runtime.parent.mkdir(parents=True)
    node.parent.mkdir(parents=True)
    make_runtime(runtime)
    node.write_text("#!/bin/sh\n", encoding="utf-8")
    node.chmod(0o755)

    resolved_runtime, resolved_node = mod.resolve_zcode_bundle_paths(app)

    assert resolved_runtime == runtime.resolve()
    assert resolved_node == node.resolve()


def test_wrapper_logs_invocation_and_verify_reports_last_invocation(tmp_path, capsys):
    runtime = tmp_path / "zcode.cjs"
    runtime.write_text(
        "MARKER = '''customSystemPrompt:this.config.systemPrompt,language:'''\n"
        "import sys\n"
        "print('node', *sys.argv[1:])\n",
        encoding="utf-8",
    )
    source = tmp_path / "source.md"
    source.write_text("# managed system\n", encoding="utf-8")
    node_command = Path(sys.executable)
    managed = tmp_path / "managed"
    launch_agent = tmp_path / "agent.plist"

    install_code = mod.main([
        "install",
        "--system-file", str(source),
        "--managed-dir", str(managed),
        "--launch-agent", str(launch_agent),
        "--zcode-runtime", str(runtime),
        "--node-command", str(node_command),
        "--yes",
        "--no-activate",
    ])
    assert install_code == 0
    capsys.readouterr()

    wrapper = managed / "bin" / "zcode-agent-wrapper.py"
    completed = subprocess.run([sys.executable, str(wrapper), "--help"], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    assert completed.returncode == 0
    assert "node" in completed.stdout

    smoke_only_code = mod.main([
        "verify",
        "--managed-dir", str(managed),
        "--launch-agent", str(launch_agent),
        "--zcode-runtime", str(runtime),
        "--node-command", str(node_command),
        "--no-smoke",
    ])
    smoke_only_out = capsys.readouterr().out
    assert smoke_only_code == 0
    assert "wrapper_invoked: false" in smoke_only_out

    completed = subprocess.run(
        [sys.executable, str(wrapper), "app-server", "--stdio"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert completed.returncode == 0

    verify_code = mod.main([
        "verify",
        "--managed-dir", str(managed),
        "--launch-agent", str(launch_agent),
        "--zcode-runtime", str(runtime),
        "--node-command", str(node_command),
    ])
    out = capsys.readouterr().out

    assert verify_code == 0
    assert "zcode-keysmith verify" in out
    assert "wrapper_smoke: true" in out
    assert "wrapper_invoked: true" in out
    assert "last_wrapper_start:" in out


def test_install_reports_running_zcode_state_without_requiring_restart(tmp_path, capsys, monkeypatch):
    runtime = tmp_path / "zcode.cjs"
    make_runtime(runtime)
    source = tmp_path / "source.md"
    source.write_text("# managed system\n", encoding="utf-8")
    node_command = tmp_path / "node"
    node_command.write_text("#!/bin/sh\n", encoding="utf-8")
    node_command.chmod(0o755)
    managed = tmp_path / "managed"
    launch_agent = tmp_path / "agent.plist"
    monkeypatch.setattr(mod, "is_zcode_running", lambda: True)

    code = mod.main([
        "install",
        "--system-file", str(source),
        "--managed-dir", str(managed),
        "--launch-agent", str(launch_agent),
        "--zcode-runtime", str(runtime),
        "--node-command", str(node_command),
        "--dry-run",
    ])
    out = capsys.readouterr().out

    assert code == 0
    assert "zcode_running: true" in out
    assert "activation_note: reopen ZCode and start a fresh task" in out


def test_windows_bundle_paths_use_resources_and_executable(tmp_path, monkeypatch):
    monkeypatch.setattr(mod.platform, "system", lambda: "Windows")
    app = tmp_path / "ZCode"
    runtime = app / "resources" / "glm" / "zcode.cjs"
    executable = app / "ZCode.exe"
    runtime.parent.mkdir(parents=True)
    make_runtime(runtime)
    executable.write_bytes(b"MZ")

    resolved_runtime, resolved_node = mod.resolve_zcode_bundle_paths(app)

    assert resolved_runtime == runtime.resolve()
    assert resolved_node == executable.resolve()
    assert mod.zcode_app_from_runtime(runtime) == app.resolve()


def test_windows_environment_uses_python_and_wrapper_argument(tmp_path, monkeypatch):
    monkeypatch.setattr(mod.platform, "system", lambda: "Windows")
    paths = mod.build_paths(tmp_path / "managed")
    plan = mod.InstallPlan(
        paths=paths,
        source_system_file=tmp_path / "source.md",
        zcode_runtime=tmp_path / "ZCode" / "resources" / "glm" / "zcode.cjs",
        node_command=tmp_path / "ZCode" / "ZCode.exe",
        activate=True,
    )

    values = mod.env_values(plan)
    args = json.loads(values["ZCODE_AGENT_SERVER_ARGS_JSON"])

    assert values["ZCODE_AGENT_SERVER_COMMAND"] == str(Path(sys.executable).resolve())
    assert args == [str(paths.wrapper), "app-server", "--stdio"]
    assert paths.env_script.name == "zcode-keysmith-env.ps1"
    assert paths.launch_agent is None


def test_backup_path_reservation_is_unique_under_concurrency(tmp_path):
    target = tmp_path / "config.json"

    def reserve_once(_):
        return mod.reserve_backup_path(target)

    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=16) as executor:
        paths = list(executor.map(reserve_once, range(32)))

    assert len(set(paths)) == 32
    assert all(path.exists() for path in paths)
    assert all(path.name.startswith("config.json.bak_") for path in paths)


def test_second_operation_lock_is_rejected(tmp_path):
    paths = mod.build_paths(tmp_path / "managed", tmp_path / "agent.plist")

    with mod.operation_lock(paths):
        with pytest.raises(mod.KeysmithError, match="already running"):
            with mod.operation_lock(paths):
                pass


def test_windows_install_writes_managed_files_without_touching_app(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(mod.platform, "system", lambda: "Windows")
    monkeypatch.setattr(mod, "get_windows_user_env_entry", lambda key: None)
    monkeypatch.setattr(mod, "is_zcode_running", lambda: False)
    runtime = tmp_path / "ZCode" / "resources" / "glm" / "zcode.cjs"
    runtime.parent.mkdir(parents=True)
    make_runtime(runtime)
    node_command = tmp_path / "ZCode" / "ZCode.exe"
    node_command.write_bytes(b"MZ")
    source = tmp_path / "source.md"
    source.write_text("# Windows system\n", encoding="utf-8")
    managed = tmp_path / "managed"

    code = mod.main([
        "install",
        "--system-file", str(source),
        "--managed-dir", str(managed),
        "--zcode-runtime", str(runtime),
        "--node-command", str(node_command),
        "--yes",
        "--no-activate",
    ])

    out = capsys.readouterr().out
    config = json.loads((managed / "config.json").read_text(encoding="utf-8"))
    env_script = managed / "bin" / "zcode-keysmith-env.ps1"
    assert code == 0
    assert "zcode-keysmith install complete" in out
    assert env_script.exists()
    assert "SetEnvironmentVariable" in env_script.read_text(encoding="utf-8")
    assert config["platform"] == "Windows"
    assert config["launch_agent"] is None
    assert config["app_bundle_modified"] is False
    assert runtime.read_text(encoding="utf-8").startswith("const x=")


def test_windows_install_rolls_back_files_and_environment_on_activation_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(mod.platform, "system", lambda: "Windows")
    runtime = tmp_path / "ZCode" / "resources" / "glm" / "zcode.cjs"
    runtime.parent.mkdir(parents=True)
    make_runtime(runtime)
    node_command = tmp_path / "ZCode" / "ZCode.exe"
    node_command.write_bytes(b"MZ")
    source = tmp_path / "source.md"
    source.write_text("# new system\n", encoding="utf-8")
    paths = mod.build_paths(tmp_path / "managed")
    old_files = {
        paths.system_file: "old system",
        paths.config_file: "old config",
        paths.wrapper: "old wrapper",
        paths.env_script: "old env",
    }
    for path, content in old_files.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    original_entries = {
        key: {"value": f"original-{key}", "registry_type": 1} for key in mod.MANAGED_ENV_KEYS
    }
    registry = {key: dict(entry) for key, entry in original_entries.items()}
    calls = 0

    def get_entry(key):
        entry = registry.get(key)
        return dict(entry) if entry else None

    def set_entry(key, entry):
        nonlocal calls
        calls += 1
        if calls == 4:
            raise OSError("injected registry failure")
        if entry is None:
            registry.pop(key, None)
        else:
            registry[key] = dict(entry)

    monkeypatch.setattr(mod, "get_windows_user_env_entry", get_entry)
    monkeypatch.setattr(mod, "windows_string_env_entry", lambda value: {"value": value, "registry_type": 1})
    monkeypatch.setattr(mod, "set_windows_user_env_entry", set_entry)
    monkeypatch.setattr(mod, "broadcast_windows_environment_change", lambda: None)

    plan = mod.InstallPlan(paths, source, runtime, node_command, True)
    with pytest.raises(mod.KeysmithError, match="activation failed"):
        mod.install(plan, yes=True, dry_run_flag=False)

    assert registry == original_entries
    assert {path: path.read_text(encoding="utf-8") for path in old_files} == old_files
    assert not list(paths.managed_dir.rglob("*.bak_*"))


def test_windows_install_rolls_back_prior_files_when_file_commit_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(mod.platform, "system", lambda: "Windows")
    runtime = tmp_path / "ZCode" / "resources" / "glm" / "zcode.cjs"
    runtime.parent.mkdir(parents=True)
    make_runtime(runtime)
    node_command = tmp_path / "ZCode" / "ZCode.exe"
    node_command.write_bytes(b"MZ")
    source = tmp_path / "source.md"
    source.write_text("# new system\n", encoding="utf-8")
    paths = mod.build_paths(tmp_path / "managed")
    old_files = {
        paths.system_file: "old system",
        paths.config_file: "old config",
        paths.wrapper: "old wrapper",
        paths.env_script: "old env",
    }
    for path, content in old_files.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    monkeypatch.setattr(mod, "get_windows_user_env_entry", lambda key: None)
    original_replace = Path.replace

    def failing_replace(self, target):
        if Path(target) == paths.wrapper and self.name.endswith(".install.tmp"):
            raise OSError("injected file commit failure")
        return original_replace(self, target)

    monkeypatch.setattr(Path, "replace", failing_replace)
    plan = mod.InstallPlan(paths, source, runtime, node_command, False)

    with pytest.raises(OSError, match="file commit failure"):
        mod.install(plan, yes=True, dry_run_flag=False)

    assert {path: path.read_text(encoding="utf-8") for path in old_files} == old_files
    assert not list(paths.managed_dir.rglob("*.bak_*"))


def test_windows_install_keeps_new_files_when_environment_rollback_is_incomplete(tmp_path, monkeypatch):
    monkeypatch.setattr(mod.platform, "system", lambda: "Windows")
    runtime = tmp_path / "ZCode" / "resources" / "glm" / "zcode.cjs"
    runtime.parent.mkdir(parents=True)
    make_runtime(runtime)
    node_command = tmp_path / "ZCode" / "ZCode.exe"
    node_command.write_bytes(b"MZ")
    source = tmp_path / "source.md"
    source.write_text("# new system\n", encoding="utf-8")
    paths = mod.build_paths(tmp_path / "managed")
    for path, content in {
        paths.system_file: "old system",
        paths.config_file: "old config",
        paths.wrapper: "old wrapper",
        paths.env_script: "old env",
    }.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    monkeypatch.setattr(
        mod,
        "activate_current_session",
        lambda plan: (_ for _ in ()).throw(
            mod.KeysmithError("activation failed\nEnvironment rollback failed:\nkey: injected")
        ),
    )
    monkeypatch.setattr(mod, "get_windows_user_env_entry", lambda key: None)
    plan = mod.InstallPlan(paths, source, runtime, node_command, True)

    with pytest.raises(mod.KeysmithError, match="files were kept at the new version"):
        mod.install(plan, yes=True, dry_run_flag=False)

    assert paths.system_file.read_text(encoding="utf-8") == "# new system\n"
    assert json.loads(paths.config_file.read_text(encoding="utf-8"))["platform"] == "Windows"
    assert "ZCODE_KEYSMITH_SYSTEM_FILE" in paths.wrapper.read_text(encoding="utf-8")
    assert list(paths.managed_dir.rglob("*.bak_*"))


def test_macos_install_rolls_back_launchctl_and_files_on_activation_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(mod.platform, "system", lambda: "Darwin")
    runtime = tmp_path / "ZCode.app" / "Contents" / "Resources" / "glm" / "zcode.cjs"
    runtime.parent.mkdir(parents=True)
    make_runtime(runtime)
    node_command = tmp_path / "ZCode.app" / "Contents" / "MacOS" / "ZCode"
    node_command.parent.mkdir(parents=True)
    node_command.write_text("#!/bin/sh\n", encoding="utf-8")
    node_command.chmod(0o755)
    source = tmp_path / "source.md"
    source.write_text("# new system\n", encoding="utf-8")
    paths = mod.build_paths(tmp_path / "managed", tmp_path / "agent.plist")
    old_files = {
        paths.system_file: "old system",
        paths.config_file: "old config",
        paths.wrapper: "old wrapper",
        paths.env_script: "old env",
        paths.launch_agent: "old plist",
    }
    for path, content in old_files.items():
        assert path is not None
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    previous = {key: (f"old-{key}" if index == 0 else None) for index, key in enumerate(mod.MANAGED_ENV_KEYS)}
    current = dict(previous)
    set_calls = 0

    def fake_run(command, **kwargs):
        nonlocal set_calls
        if command[1] == "getenv":
            value = current.get(command[2])
            return subprocess.CompletedProcess(command, 0 if value is not None else 1, f"{value}\n" if value else "", "")
        if command[1] == "setenv":
            set_calls += 1
            if set_calls == 4:
                return subprocess.CompletedProcess(command, 1, "", "injected launchctl failure")
            current[command[2]] = command[3]
            return subprocess.CompletedProcess(command, 0, "", "")
        current.pop(command[2], None)
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    plan = mod.InstallPlan(paths, source, runtime, node_command, True)

    with pytest.raises(mod.KeysmithError, match="launchctl activation failed"):
        mod.install(plan, yes=True, dry_run_flag=False)

    assert all(current.get(key) == value for key, value in previous.items())
    assert {path: path.read_text(encoding="utf-8") for path in old_files} == old_files
    assert not list(tmp_path.rglob("*.bak_*"))


def test_install_reports_original_and_file_rollback_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(mod.platform, "system", lambda: "Windows")
    runtime = tmp_path / "ZCode" / "resources" / "glm" / "zcode.cjs"
    runtime.parent.mkdir(parents=True)
    make_runtime(runtime)
    node_command = tmp_path / "ZCode" / "ZCode.exe"
    node_command.write_bytes(b"MZ")
    source = tmp_path / "source.md"
    source.write_text("# new system\n", encoding="utf-8")
    paths = mod.build_paths(tmp_path / "managed")
    paths.system_file.parent.mkdir(parents=True)
    paths.system_file.write_text("old system", encoding="utf-8")
    monkeypatch.setattr(mod, "get_windows_user_env_entry", lambda key: None)
    monkeypatch.setattr(
        mod,
        "activate_current_session",
        lambda plan: (_ for _ in ()).throw(mod.KeysmithError("original activation failure")),
    )
    monkeypatch.setattr(mod, "rollback_replaced_files", lambda replaced: ["injected file rollback failure"])
    plan = mod.InstallPlan(paths, source, runtime, node_command, True)

    with pytest.raises(mod.KeysmithError) as raised:
        mod.install(plan, yes=True, dry_run_flag=False)

    assert "original activation failure" in str(raised.value)
    assert "injected file rollback failure" in str(raised.value)


def test_windows_uninstall_restores_only_environment_it_still_owns(tmp_path, monkeypatch):
    monkeypatch.setattr(mod.platform, "system", lambda: "Windows")
    paths = mod.build_paths(tmp_path / "managed")
    paths.managed_dir.mkdir(parents=True)
    installed = {key: f"installed-{key}" for key in mod.MANAGED_ENV_KEYS}
    previous = {
        key: ({"value": f"previous-{key}", "registry_type": 1} if index == 0 else None)
        for index, key in enumerate(mod.MANAGED_ENV_KEYS)
    }
    paths.config_file.write_text(
        json.dumps(
            {
                "platform": "Windows",
                "environment": installed,
                "previous_user_environment": previous,
            }
        ),
        encoding="utf-8",
    )
    current = dict(installed)
    changed_key = mod.MANAGED_ENV_KEYS[-1]
    current[changed_key] = "changed-later"
    restored = []
    monkeypatch.setattr(mod, "persistent_environment_value", lambda key: current.get(key))
    monkeypatch.setattr(
        mod,
        "get_windows_user_env_entry",
        lambda key: {"value": current[key], "registry_type": 1} if key in current else None,
    )
    monkeypatch.setattr(mod, "set_windows_user_env_entry", lambda key, entry: restored.append((key, entry)))
    monkeypatch.setattr(mod, "broadcast_windows_environment_change", lambda: None)

    lines = mod.restore_windows_user_environment(paths)

    assert len(restored) == len(mod.MANAGED_ENV_KEYS) - 1
    assert restored[0][1] == previous[mod.MANAGED_ENV_KEYS[0]]
    assert all(key != changed_key for key, _ in restored)
    assert any("modified after install" in line for line in lines)


def test_macos_uninstall_rolls_back_environment_and_files_on_unset_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(mod.platform, "system", lambda: "Darwin")
    paths = mod.build_paths(tmp_path / "managed", tmp_path / "agent.plist")
    contents = {
        paths.system_file: "system",
        paths.config_file: "config",
        paths.wrapper: "wrapper",
        paths.env_script: "env",
        paths.launch_agent: "plist",
    }
    for path, content in contents.items():
        assert path is not None
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    previous = {key: f"managed-{key}" for key in mod.MANAGED_ENV_KEYS}
    current = dict(previous)
    unset_calls = 0

    def fake_run(command, **kwargs):
        nonlocal unset_calls
        if command[1] == "getenv":
            value = current.get(command[2])
            return subprocess.CompletedProcess(command, 0 if value is not None else 1, f"{value}\n" if value else "", "")
        if command[1] == "unsetenv":
            unset_calls += 1
            if unset_calls == 4:
                return subprocess.CompletedProcess(command, 1, "", "injected unset failure")
            current.pop(command[2], None)
            return subprocess.CompletedProcess(command, 0, "", "")
        current[command[2]] = command[3]
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(mod.subprocess, "run", fake_run)

    with pytest.raises(mod.KeysmithError, match="launchctl uninstall failed"):
        mod.uninstall(paths, yes=True, dry_run_flag=False, activate=True)

    assert current == previous
    assert {path: path.read_text(encoding="utf-8") for path in contents} == contents
    assert not list(tmp_path.rglob("*.bak_*"))


def test_macos_uninstall_keeps_backups_when_environment_rollback_is_incomplete(tmp_path, monkeypatch):
    monkeypatch.setattr(mod.platform, "system", lambda: "Darwin")
    paths = mod.build_paths(tmp_path / "managed", tmp_path / "agent.plist")
    contents = {
        paths.system_file: "system",
        paths.config_file: "config",
        paths.wrapper: "wrapper",
        paths.env_script: "env",
        paths.launch_agent: "plist",
    }
    for path, content in contents.items():
        assert path is not None
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    current = {key: f"managed-{key}" for key in mod.MANAGED_ENV_KEYS}
    unset_calls = 0
    restore_calls = 0

    def fake_run(command, **kwargs):
        nonlocal unset_calls, restore_calls
        if command[1] == "getenv":
            value = current.get(command[2])
            return subprocess.CompletedProcess(command, 0 if value is not None else 1, f"{value}\n" if value else "", "")
        if command[1] == "unsetenv":
            unset_calls += 1
            if unset_calls == 4:
                return subprocess.CompletedProcess(command, 1, "", "injected unset failure")
            current.pop(command[2], None)
            return subprocess.CompletedProcess(command, 0, "", "")
        restore_calls += 1
        if restore_calls == 2:
            return subprocess.CompletedProcess(command, 1, "", "injected restore failure")
        current[command[2]] = command[3]
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(mod.subprocess, "run", fake_run)

    with pytest.raises(mod.KeysmithError, match="remain in the listed backup paths") as raised:
        mod.uninstall(paths, yes=True, dry_run_flag=False, activate=True)

    assert "Environment rollback failed:" in str(raised.value)
    assert all(not path.exists() for path in contents)
    backups = list(tmp_path.rglob("*.bak_*"))
    assert len(backups) == len(contents)


def test_windows_uninstall_rolls_back_files_when_environment_restore_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(mod.platform, "system", lambda: "Windows")
    paths = mod.build_paths(tmp_path / "managed")
    installed = {key: f"installed-{key}" for key in mod.MANAGED_ENV_KEYS}
    previous = {key: None for key in mod.MANAGED_ENV_KEYS}
    contents = {
        paths.system_file: "system",
        paths.config_file: json.dumps(
            {
                "platform": "Windows",
                "environment": installed,
                "previous_user_environment": previous,
            }
        ),
        paths.wrapper: "wrapper",
        paths.env_script: "env",
    }
    for path, content in contents.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    registry = {key: {"value": value, "registry_type": 1} for key, value in installed.items()}
    calls = 0

    def get_entry(key):
        entry = registry.get(key)
        return dict(entry) if entry else None

    def set_entry(key, entry):
        nonlocal calls
        calls += 1
        if calls == 3:
            raise OSError("injected environment restore failure")
        if entry is None:
            registry.pop(key, None)
        else:
            registry[key] = dict(entry)

    monkeypatch.setattr(mod, "get_windows_user_env_entry", get_entry)
    monkeypatch.setattr(mod, "persistent_environment_value", lambda key: registry[key]["value"])
    monkeypatch.setattr(mod, "set_windows_user_env_entry", set_entry)
    monkeypatch.setattr(mod, "broadcast_windows_environment_change", lambda: None)

    with pytest.raises(mod.KeysmithError, match="environment restore failed"):
        mod.uninstall(paths, yes=True, dry_run_flag=False, activate=True)

    assert {path: path.read_text(encoding="utf-8") for path in contents} == contents
    assert registry == {key: {"value": value, "registry_type": 1} for key, value in installed.items()}
    assert not list(paths.managed_dir.rglob("*.bak_*"))


def test_windows_uninstall_keeps_backups_when_environment_rollback_is_incomplete(tmp_path, monkeypatch):
    monkeypatch.setattr(mod.platform, "system", lambda: "Windows")
    paths = mod.build_paths(tmp_path / "managed")
    installed = {key: f"installed-{key}" for key in mod.MANAGED_ENV_KEYS}
    contents = {
        paths.system_file: "system",
        paths.config_file: json.dumps(
            {
                "platform": "Windows",
                "environment": installed,
                "previous_user_environment": {key: None for key in mod.MANAGED_ENV_KEYS},
            }
        ),
        paths.wrapper: "wrapper",
        paths.env_script: "env",
    }
    for path, content in contents.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    monkeypatch.setattr(
        mod,
        "restore_windows_user_environment",
        lambda paths, config: (_ for _ in ()).throw(
            mod.KeysmithError("restore failed\nEnvironment rollback failed:\nkey: injected")
        ),
    )

    with pytest.raises(mod.KeysmithError, match="remain in the listed backup paths"):
        mod.uninstall(paths, yes=True, dry_run_flag=False, activate=True)

    assert all(not path.exists() for path in contents)
    backups = list(paths.managed_dir.rglob("*.bak_*"))
    assert len(backups) == len(contents)
    assert sorted(path.read_text(encoding="utf-8") for path in backups) == sorted(contents.values())


def test_uninstall_reports_original_and_file_rollback_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(mod.platform, "system", lambda: "Windows")
    paths = mod.build_paths(tmp_path / "managed")
    paths.config_file.parent.mkdir(parents=True)
    paths.config_file.write_text("config", encoding="utf-8")
    monkeypatch.setattr(
        mod,
        "restore_windows_user_environment",
        lambda paths, config: (_ for _ in ()).throw(mod.KeysmithError("original restore failure")),
    )
    original_replace = Path.replace

    def failing_rollback(self, target):
        if ".bak_" in self.name and Path(target) == paths.config_file:
            raise OSError("injected file rollback failure")
        return original_replace(self, target)

    monkeypatch.setattr(Path, "replace", failing_rollback)

    with pytest.raises(mod.KeysmithError) as raised:
        mod.uninstall(paths, yes=True, dry_run_flag=False, activate=True)

    assert "original restore failure" in str(raised.value)
    assert "injected file rollback failure" in str(raised.value)


def test_windows_uninstall_rolls_back_prior_moves_when_file_backup_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(mod.platform, "system", lambda: "Windows")
    paths = mod.build_paths(tmp_path / "managed")
    contents = {
        paths.system_file: "system",
        paths.config_file: "config",
        paths.wrapper: "wrapper",
        paths.env_script: "env",
    }
    for path, content in contents.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    original_replace = Path.replace

    def failing_replace(self, target):
        if self == paths.wrapper and ".bak_" in Path(target).name:
            raise OSError("injected backup failure")
        return original_replace(self, target)

    monkeypatch.setattr(Path, "replace", failing_replace)

    with pytest.raises(OSError, match="backup failure"):
        mod.uninstall(paths, yes=True, dry_run_flag=False, activate=False)

    assert {path: path.read_text(encoding="utf-8") for path in contents} == contents
    assert not list(paths.managed_dir.rglob("*.bak_*"))
