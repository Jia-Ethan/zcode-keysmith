from __future__ import annotations

import importlib.util
import json
import plistlib
import py_compile
import subprocess
import sys
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "zcode-keysmith.py"
spec = importlib.util.spec_from_file_location("zcode_keysmith", MODULE_PATH)
assert spec and spec.loader
mod = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = mod
spec.loader.exec_module(mod)


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
    assert str(paths.cache_dir) in wrapper_text


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


def test_resolve_zcode_app_path_derives_runtime_and_node_command(tmp_path):
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


def test_resolve_zcode_app_path_falls_back_to_main_executable_when_helper_missing(tmp_path):
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
    make_runtime(runtime)
    source = tmp_path / "source.md"
    source.write_text("# managed system\n", encoding="utf-8")
    node_command = tmp_path / "node"
    node_command.write_text("#!/bin/sh\necho node $@\n", encoding="utf-8")
    node_command.chmod(0o755)
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
    monkeypatch.setattr(mod, "set_windows_user_env_entry", lambda key, entry: restored.append((key, entry)))
    monkeypatch.setattr(mod, "broadcast_windows_environment_change", lambda: None)

    lines = mod.restore_windows_user_environment(paths)

    assert len(restored) == len(mod.MANAGED_ENV_KEYS) - 1
    assert restored[0][1] == previous[mod.MANAGED_ENV_KEYS[0]]
    assert all(key != changed_key for key, _ in restored)
    assert any("modified after install" in line for line in lines)
