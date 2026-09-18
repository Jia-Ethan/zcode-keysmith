from __future__ import annotations

import hashlib
import importlib.util
import zipfile
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "build_release.py"
spec = importlib.util.spec_from_file_location("zcode_build_release", MODULE_PATH)
assert spec and spec.loader
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

ROOT = Path(__file__).resolve().parents[1]


def test_release_zip_is_deterministic_and_excludes_gui(tmp_path):
    first = tmp_path / "first"
    second = tmp_path / "second"
    first_assets = mod.build(ROOT, first)
    second_assets = mod.build(ROOT, second)

    version = (ROOT / "VERSION").read_text(encoding="ascii").strip()
    zip_name = f"zcode-keysmith-v{version}.zip"
    first_zip = first / zip_name
    second_zip = second / zip_name
    assert [path.name for path in first_assets] == [zip_name, "SHA256SUMS"]
    assert first_zip.read_bytes() == second_zip.read_bytes()
    assert (first / "SHA256SUMS").read_text(encoding="ascii") == (
        f"{hashlib.sha256(first_zip.read_bytes()).hexdigest()}  {zip_name}\n"
    )
    assert (first / "SHA256SUMS").read_bytes() == (second / "SHA256SUMS").read_bytes()

    with zipfile.ZipFile(first_zip) as archive:
        names = archive.namelist()
    prefix = f"zcode-keysmith-v{version}/"
    assert names
    assert all(name.startswith(prefix) for name in names)
    assert f"{prefix}zcode-keysmith.py" in names
    assert f"{prefix}examples/system-role.md" in names
    assert f"{prefix}README.md" in names
    assert f"{prefix}docs/releases/v{version}.md" in names
    assert not any(name.startswith(f"{prefix}gui/") for name in names)
    assert not any("/.git/" in name or name.startswith(f"{prefix}.git/") for name in names)

    with zipfile.ZipFile(first_zip) as archive:
        script = archive.read(f"{prefix}zcode-keysmith.py").decode("utf-8")
        packed_version = archive.read(f"{prefix}VERSION").decode("ascii").strip()
    assert packed_version == version
    assert f'__version__ = "{version}"' in script


def test_docs_carry_the_current_prompt_hash():
    digest = hashlib.sha256(
        (ROOT / "examples" / "system-role.md").read_bytes().replace(b"\r\n", b"\n")
    ).hexdigest()
    reference = (ROOT / "docs" / "reference.md").read_text(encoding="utf-8")
    agent_install = (ROOT / "docs" / "agent-install.md").read_text(encoding="utf-8")
    assert digest in reference
    assert digest in agent_install
    assert digest not in {"73458b16bbb5c879e85c13d7beb6c4f99caab858a5b5b5e35ee367027111cfca"}
