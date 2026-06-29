"""Tests for FIX 1: project-local frozen plan path + unconditional wipe.

Verifies:
(a) frozen_plan_path(p) is under p/.project-setup/.cache/
(b) plan file gone after a successful run
(c) plan file gone after a FAILED run (force a step error)
(d) two different project dirs produce two distinct plan paths
(e) .project-setup/.gitignore exists and contains .cache/

Run: uv run --with pytest pytest -q tests/test_frozen_plan_local.py
"""

from __future__ import annotations

import importlib.util
import json
import sys
import textwrap
from pathlib import Path

import pytest

_RUNNER = Path(__file__).resolve().parents[1] / "skills" / "project-setup" / "runner"


def _load(name: str):
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, _RUNNER / f"{name}.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


paths = _load("paths")
contracts = _load("contracts")
persist = _load("persist")
pipeline_mod = _load("pipeline")

_io_spec = importlib.util.spec_from_file_location("io_adapter", _RUNNER / "io_adapter.py")
assert _io_spec and _io_spec.loader
_io_mod = importlib.util.module_from_spec(_io_spec)
sys.modules["io_adapter"] = _io_mod
_io_spec.loader.exec_module(_io_mod)
ScriptedIO = _io_mod.ScriptedIO

run_pipeline = pipeline_mod.run_pipeline
SCHEMA_VERSION = contracts.SCHEMA_VERSION


# --------------------------------------------------------------------------- #
# Helpers                                                                      #
# --------------------------------------------------------------------------- #
def _valid_result(module_id, step_id="run"):
    return {
        "schema_version": SCHEMA_VERSION,
        "module_id": module_id,
        "step_id": step_id,
        "status": "ok",
        "files_written": [],
        "diffs": [],
        "answers_to_persist": {},
        "warnings": [],
        "message": "",
        "error": None,
    }


def _make_plugin_root(tmp_path: Path, module_id: str = "test-mod", *, fail: bool = False) -> Path:
    """Build a minimal plugin root with one module that succeeds or fails."""
    plugin_root = tmp_path / "plugin"
    mod_dir = plugin_root / "modules" / module_id
    mod_dir.mkdir(parents=True)

    (mod_dir / "module.toml").write_text(textwrap.dedent(f"""\
        [meta]
        repository = "github.com/test/test"
        author = "Test"

        [module]
        id = "{module_id}"
        name = "Test Module"
        version = "1.0.0"
        description = "Test"
        reconcile = false
        default_enabled = true

        [order]
        requires = []
        after = []
        before = []

        [tools]
        required = []

        [[steps]]
        id = "run"
        kind = "python"
    """))

    if fail:
        result_json = json.dumps({
            "schema_version": SCHEMA_VERSION,
            "module_id": module_id,
            "step_id": "run",
            "status": "error",
            "files_written": [],
            "diffs": [],
            "answers_to_persist": {},
            "warnings": [],
            "message": "forced error",
            "error": {"error_code": "STEP_ERROR", "how_to_fix": "test forced error"},
        })
    else:
        result_json = json.dumps(_valid_result(module_id))

    (mod_dir / "module.py").write_text(textwrap.dedent(f"""\
        # /// script
        # requires-python = ">=3.11"
        # ///
        import argparse, sys
        p = argparse.ArgumentParser()
        p.add_argument("--plan"); p.add_argument("--step"); p.add_argument("--inspect", action="store_true")
        p.parse_args()
        print({result_json!r})
    """))

    return plugin_root


# --------------------------------------------------------------------------- #
# (a) frozen_plan_path(p) is under p/.project-setup/.cache/                    #
# --------------------------------------------------------------------------- #
def test_frozen_plan_path_is_project_local(tmp_path):
    """frozen_plan_path returns a path under the project's .project-setup/.cache/."""
    project_dir = tmp_path / "my-project"
    project_dir.mkdir()
    fp = paths.frozen_plan_path(project_dir)
    assert str(fp).startswith(str(project_dir / ".project-setup" / ".cache"))
    assert fp.name == "plan.json"


# --------------------------------------------------------------------------- #
# (b) plan file gone after a successful run                                    #
# --------------------------------------------------------------------------- #
def test_plan_file_cleaned_after_success(tmp_path):
    """After a successful pipeline run, the plan file is removed."""
    plugin_root = _make_plugin_root(tmp_path)
    project_dir = tmp_path / "project"
    project_dir.mkdir()

    io = ScriptedIO(default_confirm=True)
    result = run_pipeline(
        project_dir=project_dir,
        io=io,
        non_interactive=True,
        plugin_root_path=plugin_root,
    )

    assert result.success is True
    plan_path = paths.frozen_plan_path(project_dir)
    assert not plan_path.exists(), "plan.json must be cleaned up after success"


# --------------------------------------------------------------------------- #
# (c) plan file gone after a FAILED run                                        #
# --------------------------------------------------------------------------- #
def test_plan_file_cleaned_after_failure(tmp_path):
    """After a failed pipeline run, the plan file is still removed."""
    plugin_root = _make_plugin_root(tmp_path, fail=True)
    project_dir = tmp_path / "project"
    project_dir.mkdir()

    io = ScriptedIO(default_confirm=True)
    result = run_pipeline(
        project_dir=project_dir,
        io=io,
        non_interactive=True,
        plugin_root_path=plugin_root,
    )

    # The run may or may not report success depending on error handling,
    # but the plan file must be gone either way.
    plan_path = paths.frozen_plan_path(project_dir)
    assert not plan_path.exists(), "plan.json must be cleaned up even after failure"


# --------------------------------------------------------------------------- #
# (d) two different project dirs produce two distinct plan paths               #
# --------------------------------------------------------------------------- #
def test_distinct_plan_paths_for_different_projects(tmp_path):
    """Two project dirs yield two independent plan paths."""
    proj_a = tmp_path / "project-a"
    proj_b = tmp_path / "project-b"
    proj_a.mkdir()
    proj_b.mkdir()

    fp_a = paths.frozen_plan_path(proj_a)
    fp_b = paths.frozen_plan_path(proj_b)

    assert fp_a != fp_b
    assert "project-a" in str(fp_a)
    assert "project-b" in str(fp_b)


# --------------------------------------------------------------------------- #
# (e) .project-setup/.gitignore exists and contains .cache/                    #
# --------------------------------------------------------------------------- #
def test_gitignore_cache_entry_created(tmp_path):
    """.project-setup/.gitignore is created with .cache/ entry."""
    project_dir = tmp_path / "project"
    project_dir.mkdir()

    result = persist.ensure_gitignore_cache_entry(project_dir)
    assert result is True

    gi = project_dir / ".project-setup" / ".gitignore"
    assert gi.exists()
    content = gi.read_text()
    assert ".cache/" in content


def test_gitignore_cache_entry_idempotent(tmp_path):
    """Calling ensure_gitignore_cache_entry twice does not duplicate."""
    project_dir = tmp_path / "project"
    project_dir.mkdir()

    persist.ensure_gitignore_cache_entry(project_dir)
    result = persist.ensure_gitignore_cache_entry(project_dir)
    assert result is False

    gi = project_dir / ".project-setup" / ".gitignore"
    content = gi.read_text()
    assert content.count(".cache/") == 1
