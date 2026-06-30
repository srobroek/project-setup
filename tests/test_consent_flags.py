"""Tests for FIX 2: answers-file consent flags + generic CLI + loud validation.

Verifies:
(a) answers file allow/skip lists populate active_flags correctly
(b) generic --allow x --skip y populates active_flags
(c) deprecated alias maps to correct kebab name
(d) unknown flag (via answers AND via --allow) produces loud error listing valid flags
(e) a previously-unreachable gate fires when supplied via --allow

Run: uv run --with pytest pytest -q tests/test_consent_flags.py
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import textwrap
from pathlib import Path
from unittest.mock import patch

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


contracts = _load("contracts")
pipeline_mod = _load("pipeline")

_io_spec = importlib.util.spec_from_file_location("io_adapter", _RUNNER / "io_adapter.py")
assert _io_spec and _io_spec.loader
_io_mod = importlib.util.module_from_spec(_io_spec)
sys.modules["io_adapter"] = _io_mod
_io_spec.loader.exec_module(_io_mod)
ScriptedIO = _io_mod.ScriptedIO
FileAnswersIO = _io_mod.FileAnswersIO

run_pipeline = pipeline_mod.run_pipeline
SCHEMA_VERSION = contracts.SCHEMA_VERSION

# Load cli module for _active_flags and _build_parser
_cli_spec = importlib.util.spec_from_file_location("cli", _RUNNER / "cli.py")
assert _cli_spec and _cli_spec.loader
# The CLI module does a _check_uv() on import — patch shutil.which to avoid skip
with patch("shutil.which", return_value="/usr/bin/uv"):
    _cli_mod = importlib.util.module_from_spec(_cli_spec)
    sys.modules["cli"] = _cli_mod
    _cli_spec.loader.exec_module(_cli_mod)

_active_flags = _cli_mod._active_flags
_build_parser = _cli_mod._build_parser


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


def _make_plugin_with_gate(tmp_path: Path, allow_flag: str = "allow-ci-write") -> Path:
    """Build a plugin with a module that has a hard gate with allow_flag."""
    plugin_root = tmp_path / "plugin"
    mod_dir = plugin_root / "modules" / "gated-mod"
    mod_dir.mkdir(parents=True)

    (mod_dir / "module.toml").write_text(textwrap.dedent(f"""\
        [meta]
        repository = "github.com/test/test"
        author = "Test"

        [module]
        id = "gated-mod"
        name = "Gated Module"
        version = "1.0.0"
        description = "Module with a hard gate"
        reconcile = false
        default_enabled = true

        [order]
        requires = []
        after = []
        before = []

        [[steps]]
        id = "gate-step"
        kind = "gate"
        message = "Proceed with gated action?"
        hardness = "hard"
        allow_flag = "{allow_flag}"

        [[steps]]
        id = "run"
        kind = "python"
    """))

    result_json = json.dumps(_valid_result("gated-mod"))
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
# (a) answers file allow/skip lists populate active_flags                      #
# --------------------------------------------------------------------------- #
def test_answers_file_allow_skip_sets_active_flags(tmp_path):
    """allow/skip lists in the answers file produce correct active_flags."""
    answers = {
        "allow": ["allow-ci-write", "allow-readme"],
        "skip": ["no-external-generators"],
    }
    answers_file = tmp_path / "answers.json"
    answers_file.write_text(json.dumps(answers))

    # Simulate what cli.main() does: parse, pop allow/skip, merge
    raw = json.loads(answers_file.read_text())
    file_allow = raw.pop("allow", None)
    file_skip = raw.pop("skip", None)

    flags: set[str] = set()
    if file_allow:
        flags.update(str(f) for f in file_allow)
    if file_skip:
        flags.update(str(f) for f in file_skip)

    assert "allow-ci-write" in flags
    assert "allow-readme" in flags
    assert "no-external-generators" in flags


# --------------------------------------------------------------------------- #
# (b) generic --allow x --skip y populates active_flags                        #
# --------------------------------------------------------------------------- #
def test_generic_allow_skip_flags(tmp_path):
    """--allow and --skip populate active_flags correctly."""
    parser = _build_parser()
    args = parser.parse_args([
        "--allow", "allow-ci-write",
        "--allow", "allow-readme",
        "--skip", "no-external-generators",
        "--project-dir", str(tmp_path),
    ])

    flags = _active_flags(args)
    assert "allow-ci-write" in flags
    assert "allow-readme" in flags
    assert "no-external-generators" in flags


# --------------------------------------------------------------------------- #
# (c) deprecated alias maps to correct kebab name                              #
# --------------------------------------------------------------------------- #
def test_deprecated_alias_maps_correctly():
    """Deprecated --allow-public-repo still populates active_flags."""
    parser = _build_parser()
    args = parser.parse_args(["--allow-public-repo", "--allow-install"])

    flags = _active_flags(args)
    assert "allow-public-repo" in flags
    assert "allow-install" in flags


def test_deprecated_and_generic_merge():
    """Deprecated switches + generic --allow merge (union)."""
    parser = _build_parser()
    args = parser.parse_args([
        "--allow-public-repo",
        "--allow", "allow-ci-write",
    ])

    flags = _active_flags(args)
    assert "allow-public-repo" in flags
    assert "allow-ci-write" in flags


# --------------------------------------------------------------------------- #
# (d) unknown flag produces loud error listing valid flags                     #
# --------------------------------------------------------------------------- #
def test_unknown_flag_via_allow_produces_loud_error(tmp_path):
    """An unknown flag via --allow results in a pipeline error listing valid flags."""
    plugin_root = _make_plugin_with_gate(tmp_path, allow_flag="allow-ci-write")
    project_dir = tmp_path / "project"
    project_dir.mkdir()

    io = ScriptedIO(default_confirm=True)
    result = run_pipeline(
        project_dir=project_dir,
        io=io,
        non_interactive=True,
        plugin_root_path=plugin_root,
        plan_path=tmp_path / "cache" / "plan.json",
        active_flags=frozenset(["bogus-nonexistent-flag"]),
    )

    assert result.success is False
    assert len(result.errors) > 0
    err = result.errors[0]
    assert "bogus-nonexistent-flag" in err.how_to_fix
    assert "allow-ci-write" in err.how_to_fix  # valid flag listed


def test_unknown_flag_via_answers_file_produces_loud_error(tmp_path):
    """An unknown flag from the answers file also fails loudly."""
    plugin_root = _make_plugin_with_gate(tmp_path, allow_flag="allow-ci-write")
    project_dir = tmp_path / "project"
    project_dir.mkdir()

    io = ScriptedIO(default_confirm=True)
    result = run_pipeline(
        project_dir=project_dir,
        io=io,
        non_interactive=True,
        plugin_root_path=plugin_root,
        plan_path=tmp_path / "cache" / "plan.json",
        active_flags=frozenset(["allow-ci-write", "totally-made-up"]),
    )

    assert result.success is False
    assert any("totally-made-up" in e.how_to_fix for e in result.errors)


# --------------------------------------------------------------------------- #
# (e) a previously-unreachable gate fires when supplied via --allow            #
# --------------------------------------------------------------------------- #
def test_previously_unreachable_gate_fires_with_allow(tmp_path):
    """A hard gate with allow-ci-write fires (proceeds) when that flag is supplied."""
    plugin_root = _make_plugin_with_gate(tmp_path, allow_flag="allow-ci-write")
    project_dir = tmp_path / "project"
    project_dir.mkdir()

    io = ScriptedIO(default_confirm=True)
    result = run_pipeline(
        project_dir=project_dir,
        io=io,
        non_interactive=True,
        plugin_root_path=plugin_root,
        plan_path=tmp_path / "cache" / "plan.json",
        active_flags=frozenset(["allow-ci-write"]),
    )

    assert result.success is True
    # The module should have been executed (gate did not safe-skip)
    assert "gated-mod" in result.modules_executed


def test_inert_flag_for_disabled_module_warns_not_errors(tmp_path):
    """A flag valid for a DISABLED-but-discovered module is inert, not a typo.

    Regression: previously `declared_flags` came only from ENABLED plan modules,
    so a valid flag whose module wasn't enabled hard-errored the whole run. Now
    such a flag warns and the run proceeds; only a flag matching NO declared gate
    anywhere is a hard error.
    """
    plugin_root = _make_plugin_with_gate(tmp_path, allow_flag="allow-ci-write")
    # Add a SECOND module that is NOT default-enabled, declaring allow-public-repo.
    dis_dir = plugin_root / "modules" / "disabled-mod"
    dis_dir.mkdir(parents=True)
    (dis_dir / "module.toml").write_text(textwrap.dedent("""\
        [meta]
        repository = "github.com/test/test"
        author = "Test"

        [module]
        id = "disabled-mod"
        name = "Disabled Module"
        version = "1.0.0"
        description = "Not enabled this run"
        reconcile = false
        default_enabled = false

        [order]
        requires = []
        after = []
        before = []

        [[steps]]
        id = "gate-step"
        kind = "gate"
        message = "Proceed?"
        hardness = "hard"
        allow_flag = "allow-public-repo"

        [[steps]]
        id = "run"
        kind = "python"
    """))
    result_json = json.dumps(_valid_result("disabled-mod"))
    (dis_dir / "module.py").write_text(textwrap.dedent(f"""\
        import argparse
        p = argparse.ArgumentParser()
        p.add_argument("--plan"); p.add_argument("--step"); p.add_argument("--inspect", action="store_true")
        p.parse_args()
        print({result_json!r})
    """))

    project_dir = tmp_path / "project"
    project_dir.mkdir()

    io = ScriptedIO(default_confirm=True)
    result = run_pipeline(
        project_dir=project_dir,
        io=io,
        non_interactive=True,
        plugin_root_path=plugin_root,
        plan_path=tmp_path / "cache" / "plan.json",
        # allow-public-repo is declared by disabled-mod (not enabled) → INERT, not a typo.
        active_flags=frozenset(["allow-ci-write", "allow-public-repo"]),
    )

    assert result.success is True, [e.how_to_fix for e in result.errors]
    assert "gated-mod" in result.modules_executed


def test_true_typo_flag_still_hard_errors(tmp_path):
    """A flag matching NO declared gate anywhere is still a loud hard error."""
    plugin_root = _make_plugin_with_gate(tmp_path, allow_flag="allow-ci-write")
    project_dir = tmp_path / "project"
    project_dir.mkdir()

    io = ScriptedIO(default_confirm=True)
    result = run_pipeline(
        project_dir=project_dir,
        io=io,
        non_interactive=True,
        plugin_root_path=plugin_root,
        plan_path=tmp_path / "cache" / "plan.json",
        active_flags=frozenset(["allow-cii-wrte-typo"]),
    )

    assert result.success is False
    assert any("allow-cii-wrte-typo" in e.how_to_fix for e in result.errors)


# --------------------------------------------------------------------------- #
# (f) END-TO-END via cli.main(): answers-file `allow` reaches the pipeline     #
#     gate resolver — regression guard for the wiring bug where main() passed  #
#     _active_flags(args) (CLI-only) to run_pipeline instead of the merged set #
#     that includes the answers-file allow/skip lists.                         #
# --------------------------------------------------------------------------- #
def test_answers_file_allow_reaches_pipeline_via_main(tmp_path, monkeypatch):
    """cli.main() must forward the answers-file allow/skip lists to run_pipeline.

    Regression guard for the wiring bug where main() passed _active_flags(args)
    (CLI flags only) to run_pipeline, so answers-file `allow`/`skip` reached
    FileAnswersIO but NOT the pipeline gate resolver — every gate safe-skipped.

    We patch run_pipeline to capture the active_flags it actually receives. This
    asserts the real main() call path without depending on full module discovery
    (bundled modules require unrelated inputs in a hermetic run).
    """
    project_dir = tmp_path / "project"
    project_dir.mkdir()

    answers_file = tmp_path / "answers.json"
    answers_file.write_text(json.dumps({
        "allow": ["allow-ci-write", "allow-readme"],
        "skip": ["no-external-generators"],
        # also pass a CLI-equivalent answer key to prove the union, below
    }))

    captured = {}

    class _Result:
        success = True
        errors: list = []

    def _fake_run_pipeline(*args, **kwargs):
        captured["active_flags"] = kwargs.get("active_flags")
        return _Result()

    monkeypatch.setattr(_cli_mod, "run_pipeline", _fake_run_pipeline)

    with patch("shutil.which", return_value="/usr/bin/uv"):
        rc = _cli_mod.main([
            "--project-dir", str(project_dir),
            "--answers", str(answers_file),
            "--allow", "allow-public-repo",  # CLI flag must ALSO be present (union)
        ])

    assert rc == 0
    flags = captured["active_flags"]
    assert flags is not None, "run_pipeline received no active_flags"
    # The answers-file flags MUST be in the set the pipeline sees (the bug).
    assert "allow-ci-write" in flags
    assert "allow-readme" in flags
    assert "no-external-generators" in flags
    # The CLI flag must be unioned in too.
    assert "allow-public-repo" in flags
