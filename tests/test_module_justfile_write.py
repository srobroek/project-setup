"""End-to-end tests for the justfile-write module.

Verifies:
  - manifest parses and is valid
  - use_just=true (default): writes justfile with verbatim legacy content
  - use_just=false: no files written (explicit skip)
  - --inspect writes nothing
  - reconcile=false: second run skips existing justfile
  - justfile content matches the legacy heredoc verbatim

Run: uv run --with pytest pytest -q packages/project-setup/tests/test_module_justfile_write.py
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

_PKG = Path(__file__).resolve().parents[1]
_PLUGIN_ROOT = _PKG / "skills" / "project-setup"
_RUNNER = _PLUGIN_ROOT / "runner"
_MODULE_REL = "modules/justfile-write"

# Verbatim expected justfile content (must match module.py _JUSTFILE).
# test:/build:/dev: use failing stubs (exit 1) so CI is never green-while-
# doing-nothing; clean: keeps the harmless TODO echo.
_EXPECTED_JUSTFILE = """\
default:
    @just --list

# Run tests
test:
    @echo "ERROR: no test command configured — edit this justfile to add one (e.g. uv run pytest, bun test)" && exit 1

# Lint and format
lint:
    pre-commit run --all-files

# Build
build:
    @echo "ERROR: no build command configured — edit this justfile to add one" && exit 1

# Start dev server
dev:
    @echo "ERROR: no dev command configured — edit this justfile to add one" && exit 1

# Clean build artifacts
clean:
    @echo "TODO: configure clean command"
"""


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, _RUNNER / f"{name}.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _frozen_plan(tmp: Path, use_just: bool = True, language: str = "") -> Path:
    plan = {
        "schema_version": 1,
        "mode": "init",
        "order": ["justfile-write"],
        "modules": {
            "justfile-write": {
                "id": "justfile-write",
                "version": "1.0.0",
                "reconcile": False,
                "module_rel_root": _MODULE_REL,
                "answers": {"use_just": use_just, "language": language},
                "steps": [{"id": "write", "kind": "python"}],
            }
        },
    }
    p = tmp / "plan.json"
    p.write_text(json.dumps(plan))
    return p


def _run(project: Path, plan: Path, *, inspect: bool = False) -> subprocess.CompletedProcess:
    module_py = _PLUGIN_ROOT / _MODULE_REL / "module.py"
    cmd = ["uv", "run", str(module_py), "--plan", str(plan), "--step", "write"]
    if inspect:
        cmd.append("--inspect")
    env = {**os.environ, "PLUGIN_ROOT": str(_PLUGIN_ROOT), "PROJECT_DIR": str(project)}
    return subprocess.run(cmd, capture_output=True, text=True, env=env, cwd=str(project))


def test_manifest_parses_and_is_valid():
    manifest = _load("manifest")
    mani = manifest.parse_manifest(_PLUGIN_ROOT / _MODULE_REL / "module.toml")
    assert not mani.errors, mani.errors
    assert mani.id == "justfile-write"
    assert mani.default_enabled is False
    assert mani.reconcile is False
    assert any(s.id == "write" and s.kind == "python" for s in mani.steps)
    # No requires — justfile is independent
    assert mani.order["requires"] == []


def test_use_just_true_writes_justfile(tmp_path):
    project = tmp_path / "proj"
    project.mkdir()
    plan = _frozen_plan(tmp_path, use_just=True)
    proc = _run(project, plan)
    assert proc.returncode == 0, proc.stderr
    result = json.loads(proc.stdout)
    assert result["status"] == "ok"
    assert result["files_written"] == ["justfile"]

    written = (project / "justfile").read_text()
    assert written == _EXPECTED_JUSTFILE


def test_justfile_content_verbatim(tmp_path):
    """Byte-identical comparison with the expected legacy content."""
    project = tmp_path / "proj"
    project.mkdir()
    plan = _frozen_plan(tmp_path, use_just=True)
    _run(project, plan)
    written = (project / "justfile").read_bytes()
    assert written == _EXPECTED_JUSTFILE.encode("utf-8")


def test_use_just_false_skips(tmp_path):
    """use_just=false: no justfile written, files_written=[]."""
    project = tmp_path / "proj"
    project.mkdir()
    plan = _frozen_plan(tmp_path, use_just=False)
    proc = _run(project, plan)
    assert proc.returncode == 0, proc.stderr
    result = json.loads(proc.stdout)
    assert result["status"] == "ok"
    assert result["files_written"] == []
    assert not (project / "justfile").exists()


def test_inspect_writes_nothing(tmp_path):
    project = tmp_path / "proj"
    project.mkdir()
    plan = _frozen_plan(tmp_path, use_just=True)
    proc = _run(project, plan, inspect=True)
    assert proc.returncode == 0, proc.stderr
    result = json.loads(proc.stdout)
    assert result["diffs"][0]["kind"] == "create"
    assert not (project / "justfile").exists()


def test_inspect_equals_write_bytes(tmp_path):
    """Tier-1 guarantee: inspect preview content == real written bytes."""
    project = tmp_path / "proj"
    project.mkdir()
    plan = _frozen_plan(tmp_path, use_just=True)
    # Inspect first, nothing written
    _run(project, plan, inspect=True)
    assert not (project / "justfile").exists()
    # Real write
    _run(project, plan)
    written = (project / "justfile").read_text()
    assert written == _EXPECTED_JUSTFILE


def test_idempotent_second_run_skips(tmp_path):
    """reconcile=false: second run skips existing justfile."""
    project = tmp_path / "proj"
    project.mkdir()
    plan = _frozen_plan(tmp_path, use_just=True)
    _run(project, plan)
    proc2 = _run(project, plan)
    assert proc2.returncode == 0, proc2.stderr
    result = json.loads(proc2.stdout)
    assert result["diffs"][0]["kind"] == "skip"
    assert result["files_written"] == []
    # Content unchanged
    assert (project / "justfile").read_text() == _EXPECTED_JUSTFILE


# --------------------------------------------------------------------------- #
# Task B — language-aware recipes                                              #
# --------------------------------------------------------------------------- #

def test_manifest_has_language_input():
    """module.toml must declare a 'language' input with type=string, default=""."""
    manifest = _load("manifest")
    mani = manifest.parse_manifest(_PLUGIN_ROOT / _MODULE_REL / "module.toml")
    assert not mani.errors, mani.errors
    lang_inputs = [i for i in mani.inputs if i.key == "language"]
    assert lang_inputs, "No 'language' input found in module.toml"
    li = lang_inputs[0]
    assert li.type.value == "string", f"Expected type=string, got {li.type}"
    assert li.required is False
    assert li.default == "" or li.default is None or li.default == ""


def test_python_test_recipe_uses_uv_run_pytest(tmp_path):
    """language=python: test: recipe must contain 'uv run pytest', not the error stub."""
    project = tmp_path / "proj"
    project.mkdir()
    plan = _frozen_plan(tmp_path, language="python")
    proc = _run(project, plan)
    assert proc.returncode == 0, proc.stderr
    content = (project / "justfile").read_text()
    assert "uv run pytest" in content
    assert "ERROR: no test command configured" not in content


def test_python_build_recipe_uses_uv_build(tmp_path):
    """language=python: build: recipe must contain 'uv build', not the error stub."""
    project = tmp_path / "proj"
    project.mkdir()
    plan = _frozen_plan(tmp_path, language="python")
    proc = _run(project, plan)
    assert proc.returncode == 0, proc.stderr
    content = (project / "justfile").read_text()
    assert "uv build" in content
    assert "ERROR: no build command configured" not in content


def test_python_lint_preserved(tmp_path):
    """language=python: lint: must still use pre-commit run --all-files."""
    project = tmp_path / "proj"
    project.mkdir()
    plan = _frozen_plan(tmp_path, language="python")
    proc = _run(project, plan)
    assert proc.returncode == 0, proc.stderr
    content = (project / "justfile").read_text()
    assert "pre-commit run --all-files" in content


def test_python_dev_is_not_silent_pass(tmp_path):
    """language=python: dev: must NOT be a silent exit-0 echo (green-theater guard)."""
    project = tmp_path / "proj"
    project.mkdir()
    plan = _frozen_plan(tmp_path, language="python")
    proc = _run(project, plan)
    assert proc.returncode == 0, proc.stderr
    content = (project / "justfile").read_text()
    # dev recipe body must contain exit 1 (fail-loud) — not a bare TODO echo-and-pass
    dev_section = content.split("# Start dev server\ndev:\n")
    assert len(dev_section) == 2, "dev: section not found"
    dev_body = dev_section[1].split("\n\n")[0]
    assert "exit 1" in dev_body or "exit 1" in dev_body, (
        f"dev recipe must fail loud, got: {dev_body!r}"
    )


def test_empty_language_keeps_fail_loud_stubs(tmp_path):
    """language='': test/build/dev must all use the error-exit stubs (green-theater guard)."""
    project = tmp_path / "proj"
    project.mkdir()
    plan = _frozen_plan(tmp_path, language="")
    proc = _run(project, plan)
    assert proc.returncode == 0, proc.stderr
    content = (project / "justfile").read_text()
    assert "ERROR: no test command configured" in content
    assert "ERROR: no build command configured" in content
    assert "ERROR: no dev command configured" in content


def test_go_test_recipe_uses_go_test(tmp_path):
    """language=go: test: recipe must contain 'go test ./...'."""
    project = tmp_path / "proj"
    project.mkdir()
    plan = _frozen_plan(tmp_path, language="go")
    proc = _run(project, plan)
    assert proc.returncode == 0, proc.stderr
    content = (project / "justfile").read_text()
    assert "go test ./..." in content
    assert "ERROR: no test command configured" not in content


def test_rust_test_recipe_uses_cargo_test(tmp_path):
    """language=rust: test: recipe must contain 'cargo test'."""
    project = tmp_path / "proj"
    project.mkdir()
    plan = _frozen_plan(tmp_path, language="rust")
    proc = _run(project, plan)
    assert proc.returncode == 0, proc.stderr
    content = (project / "justfile").read_text()
    assert "cargo test" in content
    assert "ERROR: no test command configured" not in content


def test_unknown_language_keeps_fail_loud_stubs(tmp_path):
    """An unknown language string must fall back to the fail-loud stubs."""
    project = tmp_path / "proj"
    project.mkdir()
    plan = _frozen_plan(tmp_path, language="cobol")
    proc = _run(project, plan)
    assert proc.returncode == 0, proc.stderr
    content = (project / "justfile").read_text()
    assert "ERROR: no test command configured" in content
    assert "ERROR: no build command configured" in content
