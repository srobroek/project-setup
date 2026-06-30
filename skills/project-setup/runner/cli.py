#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""CLI entry point for the project-setup runner.

Usage::

    uv run cli.py [--project-dir <path>] [--non-interactive] [--dry-run]

The runner core is dependency-free (stdlib only); TOML is read with stdlib
``tomllib`` and written with a small stdlib emitter in ``persist.py``. The only
hard requirement is ``uv`` itself (checked in preflight). Individual capability
modules declare their own deps via their own PEP 723 headers and run under
``uv run module.py``.

Preflight: the FIRST thing done (before any import from the runner) is a
``shutil.which("uv")`` check.  If ``uv`` is absent the process exits non-zero
with a clear installation instruction.  This is a hard requirement — there is
no stdlib fallback path (see shared-contracts.md, plan.md §Technical Context).
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import shutil
import sys
import tomllib
from pathlib import Path

# --------------------------------------------------------------------------- #
# uv preflight — MUST be the first check (before any runner imports)          #
# --------------------------------------------------------------------------- #
def _check_uv() -> None:
    """Exit immediately with a helpful message if ``uv`` is not on PATH."""
    if shutil.which("uv") is None:
        print(
            "Error: 'uv' is required but was not found on PATH.\n"
            "\n"
            "Install uv:\n"
            "  curl -LsSf https://astral.sh/uv/install.sh | sh\n"
            "  # or: brew install uv  (macOS)\n"
            "  # or: pip install uv   (fallback)\n"
            "\n"
            "See https://docs.astral.sh/uv/getting-started/installation/\n"
            "\n"
            "project-setup requires uv to provision per-module Python deps.\n"
            "There is no stdlib fallback path.",
            file=sys.stderr,
        )
        sys.exit(1)


_check_uv()  # Hard-fail before any other code runs

# --------------------------------------------------------------------------- #
# Runner library bootstrap (sys.path seam — spec 005 OQ-2)                     #
# --------------------------------------------------------------------------- #
# Put the runner dir (and its sources/ sub-package dir) on sys.path so every
# runner module resolves its siblings with a plain ``import <name>`` instead of
# the old per-file ``_load_sibling`` importlib bootstrap. This is the one place
# the path is established for the CLI entry; pytest does the same via conftest.py,
# and the ``uv run module.py`` subprocess path is covered by the executor's
# PYTHONPATH injection (spec 005 FR-001). A real import also registers the module
# in ``sys.modules`` before its body runs, so the ``@dataclass(Exception)`` footgun
# the old pattern guarded against cannot occur.
_RUNNER = Path(__file__).resolve().parent
for _p in (str(_RUNNER), str(_RUNNER / "sources")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import pipeline  # noqa: E402
import io_adapter  # noqa: E402

run_pipeline = pipeline.run_pipeline
TerminalIO = io_adapter.TerminalIO
FileAnswersIO = io_adapter.FileAnswersIO


# --------------------------------------------------------------------------- #
# Argument parser                                                              #
# --------------------------------------------------------------------------- #
def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="project-setup",
        description=(
            "Modular, config-driven project bootstrapper.  "
            "Runs a manifest-driven interview, validates constraints, "
            "then executes each enabled module to scaffold the project."
        ),
    )
    p.add_argument(
        "--project-dir",
        default=".",
        metavar="DIR",
        help="Project directory to set up (default: current working directory).",
    )
    p.add_argument(
        "--non-interactive",
        action="store_true",
        default=False,
        help="Skip all prompts and use defaults + committed answers only.",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help=(
            "Run the interview and build the frozen plan but do NOT execute "
            "modules or write .project-setup/ files."
        ),
    )
    p.add_argument(
        "--check-answers",
        action="store_true",
        default=False,
        help=(
            "Preflight only: discover + resolve modules and verify EVERY required "
            "input for the enabled module set is present in --answers, then exit "
            "WITHOUT planning or executing. Reports all missing required inputs / "
            "tools / order errors at once (exit 1 if any). Run this before the real "
            "--answers run so the interview can't silently skip required questions."
        ),
    )
    p.add_argument(
        "--skill-version",
        default="",
        metavar="VERSION",
        help="Advisory version string written to sources.toml [meta] section.",
    )
    p.add_argument(
        "--refresh",
        action="append",
        default=None,
        metavar="MODULE[.KEY]",
        help=(
            "Reproduce mode only: re-research the named Tier-2 agent decision(s). "
            "Pass a module id (e.g. 'lang-python') or a module.key. Repeatable. "
            "Each refreshed decision is shown as an old-vs-new diff and applied "
            "only on confirm; all other agent steps replay their committed "
            "decision with zero network. Ignored in init mode."
        ),
    )
    p.add_argument(
        "--answers",
        default=None,
        metavar="FILE",
        help=(
            "Path to a JSON or TOML file of pre-collected answers "
            "(format: {\"module_id.key\": value, ..., \"enabled\": [\"module-id\", ...]}). "
            "Drives the runner non-interactively; the agent collects answers up front "
            "(interview + agent-steered decisions) and passes them here. "
            "Example: {\"core-identity.project_name\": \"my-app\", "
            "\"core-identity.license\": \"mit\", "
            "\"enabled\": [\"lang-python\"]}. "
            "On parse error the runner exits 1 — it does NOT fall back to stdin."
        ),
    )

    # ── Generic gate flags (spec 004 §3) ─────────────────────────────────────── #
    # Hard gates SAFE-skip in --non-interactive unless opted in by a SPECIFIC flag;
    # soft gates proceed unless opted out. There is deliberately NO global
    # "--yes"/"--confirm-all" (spec 004 FR-005 / anti-pattern 5): a blanket toggle
    # would auto-approve the public repo, the install, and the stack write together.
    gate = p.add_argument_group(
        "gate opt-in/opt-out flags",
        "Per-action consent for hard gates in --non-interactive runs (no global yes-to-all). "
        "Use generic --allow/--skip for any declared gate flag.",
    )
    gate.add_argument(
        "--allow", action="append", default=None, dest="allow", metavar="FLAG",
        help=(
            "Opt-in to a named hard gate (repeatable). Example: --allow allow-public-repo. "
            "The flag name must match an allow_flag declared in a module's [[steps]]."
        ),
    )
    gate.add_argument(
        "--skip", action="append", default=None, dest="skip", metavar="FLAG",
        help=(
            "Opt-out of a named soft gate (repeatable). Example: --skip no-external-generators. "
            "The flag name must match a skip_flag declared in a module's [[steps]]."
        ),
    )

    # ── Deprecated per-flag switches (kept for backward compat) ────────────── #
    dep_gate = p.add_argument_group(
        "deprecated gate flags",
        "Legacy per-action switches. Use --allow/--skip instead.",
    )
    dep_gate.add_argument(
        "--allow-public-repo", action="store_true", default=False,
        help="(deprecated: use --allow allow-public-repo) CI opt-in: create a PUBLIC GitHub repo (G3 hard gate).",
    )
    dep_gate.add_argument(
        "--allow-install", action="store_true", default=False,
        help="(deprecated: use --allow allow-install) CI opt-in: run the batched 'apm install' (G2 supply-chain gate).",
    )
    dep_gate.add_argument(
        "--allow-stack-write", action="store_true", default=False,
        help="(deprecated: use --allow allow-stack-write) CI opt-in: write agent-researched dependency pins (G6 gate).",
    )
    dep_gate.add_argument(
        "--no-external-generators", action="store_true", default=False,
        help="(deprecated: use --skip no-external-generators) CI opt-out: skip external scaffolders like 'nuxi init' (G4 soft gate).",
    )

    # ── New-module scaffold (FR-C5) ──────────────────────────────────────────── #
    p.add_argument(
        "--new-module",
        default=None,
        metavar="ID",
        help=(
            "Scaffold a new addon module directory with starter module.toml, "
            "module.py, and test stub. Writes to "
            ".project-setup/modules/<id>/ in --project-dir (or --new-module-dest). "
            "Exits immediately after scaffolding without running the pipeline."
        ),
    )
    p.add_argument(
        "--new-module-dest",
        default=None,
        metavar="DIR",
        help=(
            "Destination directory for --new-module (overrides the default "
            ".project-setup/modules/<id>/ placement). The <id> subdirectory "
            "is created inside this dir."
        ),
    )

    # ── Add external module source ────────────────────────────────────────────── #
    p.add_argument(
        "--add-module",
        default=None,
        metavar="LOCATOR",
        help=(
            "Fetch an external module source and register it in "
            ".project-setup/sources.toml so it is available on the next run. "
            "LOCATOR may be a GitHub shorthand (owner/repo, owner/repo/subdir, "
            "owner/repo#ref), a full HTTPS/SSH git URL, or a local path. "
            "Exits after updating sources.toml without running the pipeline."
        ),
    )
    p.add_argument(
        "--ref",
        default=None,
        metavar="REF",
        help=(
            "Git ref (tag, branch, SHA) for --add-module. Overrides any ref "
            "embedded in the locator string via '#ref'."
        ),
    )
    p.add_argument(
        "--subdir",
        default=None,
        metavar="PATH",
        help=(
            "Subdirectory within the repository for --add-module. Overrides "
            "any subdir embedded in the locator string."
        ),
    )
    p.add_argument(
        "--enable",
        action="store_true",
        default=False,
        help=(
            "with --add-module: also add the discovered module id(s) to the "
            "committed .project-setup/answers.toml [modules].enabled list so "
            "they take effect on the next run (writing sources.toml flips the "
            "project to reproduce mode, where the --answers `enabled` list is "
            "ignored)."
        ),
    )

    # ── List addon catalog ────────────────────────────────────────────────────── #
    p.add_argument(
        "--list-catalog",
        action="store_true",
        default=False,
        help=(
            "List available addon modules from configured catalogs "
            "(PROJECT_SETUP_CATALOG_URL env var or ~/.config/project-setup/config.toml "
            "[catalog] urls). Exits after printing without running the pipeline."
        ),
    )

    # ── Add module from catalog ───────────────────────────────────────────────── #
    p.add_argument(
        "--add-module-from-catalog",
        default=None,
        metavar="NAME",
        help=(
            "Look up NAME in the configured addon catalogs, resolve its locator, "
            "and register it in .project-setup/sources.toml (same as --add-module "
            "but driven by catalog name rather than a raw locator). "
            "Exits after updating sources.toml without running the pipeline."
        ),
    )
    return p


# Map argparse dest → the gate flag name carried in active_flags. The flag NAME
# (kebab) is what gate steps reference via [[steps]].allow_flag / .skip_flag.
# These are the DEPRECATED switches; kept for backward compat.
_DEPRECATED_GATE_FLAGS = {
    "allow_public_repo": "allow-public-repo",
    "allow_install": "allow-install",
    "allow_stack_write": "allow-stack-write",
    "no_external_generators": "no-external-generators",
}


def _active_flags(args: argparse.Namespace) -> frozenset[str]:
    """Collect the gate flag names the user activated into the set the resolver reads.

    Sources (unioned):
    1. Generic --allow / --skip (primary CLI path).
    2. Deprecated per-flag switches (backward compat).
    """
    flags: set[str] = set()
    # Generic repeatable flags
    if args.allow:
        flags.update(args.allow)
    if args.skip:
        flags.update(args.skip)
    # Deprecated switches
    for dest, flag in _DEPRECATED_GATE_FLAGS.items():
        if getattr(args, dest, False):
            flags.add(flag)
    return frozenset(flags)


# --------------------------------------------------------------------------- #
# New-module scaffold (FR-C5)                                                  #
# --------------------------------------------------------------------------- #

_MODULE_TOML_TEMPLATE = """\
schema_version = "1.0"

[meta]
repository = "github.com/owner/repo"   # replace with your repo URL
author     = "Your Name"

[module]
id          = "{id}"
name        = "{name}"
version     = "0.1.0"
description = "TODO: describe what this module does."
reconcile   = false
# default_enabled is FORBIDDEN on non-bundled (addon) modules — do not add it.

[order]
requires = []
after    = []

# Input declarations drive the interview and are frozen into the plan.
# Remove or customise this example input.
[[inputs]]
key      = "greeting"
type     = "string"
prompt   = "What greeting should {name} write?"
default  = "Hello, world!"
required = false

# Steps are listed in execution order.
[[steps]]
id   = "write"
kind = "python"
"""

_MODULE_PY_TEMPLATE = '''\
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Starter module for {id}.

Run standalone:
    uv run module.py --plan /path/to/plan.json --step write [--inspect]
"""
from __future__ import annotations

import argparse
import importlib.util
import os
import sys
from pathlib import Path


def _load_sdk():
    # Fast path: executor puts runner dir on PYTHONPATH (spec 005).
    try:
        import sdk
        return sdk
    except ModuleNotFoundError:
        pass
    # Fallback: file-path load for direct invocation outside the executor.
    plugin_root = os.environ.get("PLUGIN_ROOT") or os.environ.get("CLAUDE_PLUGIN_ROOT")
    if plugin_root:
        sdk_path = Path(plugin_root) / "runner" / "sdk.py"
    else:
        sdk_path = Path(__file__).resolve().parents[2] / "runner" / "sdk.py"
    spec = importlib.util.spec_from_file_location("sdk", sdk_path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["sdk"] = mod   # register BEFORE exec_module (sys.modules footgun)
    spec.loader.exec_module(mod)
    return mod


def _do_write(sdk, inputs, args):
    """Step: write — write a placeholder file."""
    greeting = inputs.get_str("greeting", "Hello, world!")
    body = f"{{greeting}}\\n"

    diff = sdk.idempotent_write(
        "{id}/greeting.txt",
        body,
        reconcile=inputs.reconcile,
        inspect=args.inspect,
    )

    sdk.emit_result(sdk.ModuleResult(
        module_id="{id}",
        step_id=args.step,
        status="ok",
        files_written=[] if args.inspect else [diff.path],
        diffs=[diff],
    ))
    return 0


STEP_HANDLERS = {{
    "write": _do_write,
}}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", required=True)
    ap.add_argument("--step", required=True)
    ap.add_argument("--inspect", action="store_true")
    args = ap.parse_args()

    sdk = _load_sdk()
    inputs = sdk.load_frozen_inputs(args.plan, module_id="{id}")

    handler = STEP_HANDLERS.get(args.step)
    if handler is None:
        print(f"Unknown step: {{args.step!r}}", file=sys.stderr)
        return 1
    return handler(sdk, inputs, args)


if __name__ == "__main__":
    raise SystemExit(main())
'''

_TEST_TEMPLATE = '''\
"""Stub tests for the {id} module.

Run:
    uv run --with pytest pytest -q test_{id_safe}.py
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_MODULE_DIR = Path(__file__).resolve().parent


def _load_parse_manifest():
    """Load parse_manifest from the runner (two levels up from modules/<id>/)."""
    runner = _MODULE_DIR.parents[2] / "runner"
    for dep in (
        "contracts", "paths", "manifest",
    ):
        for cand in (runner / f"{{dep}}.py", runner / "sources" / f"{{dep}}.py"):
            if cand.is_file() and dep not in sys.modules:
                spec = importlib.util.spec_from_file_location(dep, cand)
                assert spec and spec.loader
                mod = importlib.util.module_from_spec(spec)
                sys.modules[dep] = mod
                spec.loader.exec_module(mod)
                break
    manifest_path = runner / "manifest.py"
    if "manifest" not in sys.modules:
        spec = importlib.util.spec_from_file_location("manifest", manifest_path)
        assert spec and spec.loader
        mod = importlib.util.module_from_spec(spec)
        sys.modules["manifest"] = mod
        spec.loader.exec_module(mod)
    return sys.modules["manifest"].parse_manifest


def test_manifest_parses_without_errors():
    """module.toml must be accepted by parse_manifest with no errors."""
    parse_manifest = _load_parse_manifest()
    manifest = parse_manifest(_MODULE_DIR / "module.toml")
    assert manifest.errors == [], (
        f"module.toml has parse errors: {{[e.how_to_fix for e in manifest.errors]}}"
    )
    assert manifest.id == "{id}"


def test_module_py_compiles():
    """module.py must be importable (syntax-valid Python)."""
    import py_compile
    py_compile.compile(str(_MODULE_DIR / "module.py"), doraise=True)
'''


def _scaffold_new_module(module_id: str, dest_dir: Path) -> int:
    """Write the starter module directory for *module_id* under *dest_dir*.

    Creates *dest_dir*/<module_id>/ containing:
    - module.toml  — valid manifest skeleton
    - module.py    — minimal working Tier-1 handler
    - test_<id>.py — stub test that calls parse_manifest

    Returns 0 on success, 1 on error (with message already printed to stderr).
    """
    import re

    # Validate id: must be non-empty, lowercase, kebab-case
    if not module_id or not re.match(r"^[a-z][a-z0-9-]*$", module_id):
        print(
            f"Error: --new-module id must be lowercase kebab-case (e.g. 'my-module'), "
            f"got: {module_id!r}",
            file=sys.stderr,
        )
        return 1

    module_dir = dest_dir / module_id
    if module_dir.exists():
        print(
            f"Error: destination already exists: {module_dir}\n"
            "Remove it first or choose a different id.",
            file=sys.stderr,
        )
        return 1

    # Derive a human name from the id (kebab → Title Case)
    name = " ".join(part.title() for part in module_id.split("-"))
    # Safe Python identifier for the test file name
    id_safe = module_id.replace("-", "_")

    try:
        module_dir.mkdir(parents=True, exist_ok=False)

        (module_dir / "module.toml").write_text(
            _MODULE_TOML_TEMPLATE.format(id=module_id, name=name),
            encoding="utf-8",
        )
        (module_dir / "module.py").write_text(
            _MODULE_PY_TEMPLATE.format(id=module_id),
            encoding="utf-8",
        )
        (module_dir / f"test_{id_safe}.py").write_text(
            _TEST_TEMPLATE.format(id=module_id, id_safe=id_safe),
            encoding="utf-8",
        )
    except OSError as exc:
        print(f"Error: could not scaffold module: {exc}", file=sys.stderr)
        return 1

    print(
        f"Scaffolded module '{module_id}' at {module_dir}\n"
        f"  module.toml   — edit metadata, inputs, steps\n"
        f"  module.py     — implement step handlers\n"
        f"  test_{id_safe}.py — add tests\n"
        f"\n"
        f"To use locally, add .project-setup/modules/{module_id}/ to your project\n"
        f"(or declare it as a [[source]] in .project-setup/sources.toml for git dist).",
    )
    return 0


# --------------------------------------------------------------------------- #
# Add-module helpers (CLI commands --add-module / --add-module-from-catalog)  #
# --------------------------------------------------------------------------- #

def _read_sources_toml(project_dir: Path) -> tuple[list[dict], str, dict]:
    """Read existing .project-setup/sources.toml.

    Returns ``(sources, skill_version, meta)`` where:
    - *sources* is the full list of [[source]] records (all fields preserved).
    - *skill_version* is the ``[meta].skill_version`` string (or "").
    - *meta* is the full ``[meta]`` dict (preserves unknown keys for round-trip).

    Returns ``([], "", {})`` when the file is absent or unreadable.  Never raises.
    """
    import tomllib as _tomllib

    src_toml = project_dir / ".project-setup" / "sources.toml"
    if not src_toml.is_file():
        return [], "", {}
    try:
        with open(src_toml, "rb") as fh:
            data = _tomllib.load(fh)
    except Exception:
        return [], "", {}
    meta: dict = data.get("meta", {}) or {}
    skill_version = meta.get("skill_version", "") or ""
    raw_sources = data.get("source", [])
    sources = [s for s in raw_sources if isinstance(s, dict)]
    return sources, skill_version, meta


def _sources_dedup_key(source: dict) -> tuple[str, str, str]:
    """Return a tuple used to detect duplicate [[source]] records.

    Two records are duplicates when they share the same (locator, ref, subdir).
    The locator is normalised to the canonical origin form so that different
    URL forms (https vs shorthand) for the same repo do not create duplicates.
    """
    import locator as _loc_mod

    raw = source.get("locator", "")
    ref = source.get("ref", "") or ""
    subdir = source.get("subdir", "") or ""
    try:
        loc = _loc_mod.parse_locator(raw)
        # Normalise: for git use origin+ref+subdir; for local use origin only.
        if loc.kind == "git":
            return (loc.origin, ref or loc.ref, subdir or loc.subdir)
        return (loc.origin, "", subdir or loc.subdir)
    except Exception:
        # If unparseable just use the raw string.
        return (raw, ref, subdir)


def _enable_modules_in_answers(project_dir: Path, module_ids: list[str]) -> None:
    """Add *module_ids* to the committed answers.toml [modules].enabled list.

    Unions with any existing enabled set (preserving order-independence via the
    helper's sort) and preserves [module.*] answer tables. Used by --add-module
    --enable so a just-registered source's module is actually enabled on the next
    (reproduce-mode) run — writing sources.toml flips the project to reproduce
    mode, where the enabled set is read from committed answers.toml, NOT from a
    --answers file's `enabled` list.
    """
    import tomllib as _tomllib
    import persist as _persist_mod

    answers_path = project_dir / ".project-setup" / "answers.toml"
    existing_enabled: list[str] = []
    if answers_path.is_file():
        try:
            with open(answers_path, "rb") as fh:
                existing = _tomllib.load(fh)
            cur = existing.get("modules", {}).get("enabled", [])
            if isinstance(cur, list):
                existing_enabled = [str(x) for x in cur]
        except Exception:
            pass
    merged = sorted(set(existing_enabled) | set(module_ids))
    _persist_mod.write_modules_enabled(project_dir, merged, provenance="flag")


def _cmd_add_module(
    project_dir: Path,
    locator_str: str,
    ref: str | None,
    subdir: str | None,
    enable: bool = False,
) -> int:
    """Implement --add-module: fetch, validate, register in sources.toml.

    When *enable* is True, also add the discovered module id(s) to the committed
    answers.toml [modules].enabled list so they take effect on the next run.

    Returns 0 on success, 1 on error (messages printed to stderr).
    """
    import locator as _loc_mod
    import fetch as _fetch_mod
    import discover as _discover_mod
    import persist as _persist_mod

    # ── 1. Parse the locator ──────────────────────────────────────────────── #
    try:
        loc = _loc_mod.parse_locator(locator_str)
    except ValueError as exc:
        print(f"Error: invalid locator {locator_str!r}: {exc}", file=sys.stderr)
        return 1

    # Apply --ref / --subdir overrides.
    if ref:
        loc = _loc_mod.Locator(kind=loc.kind, origin=loc.origin, subdir=loc.subdir, ref=ref)
    if subdir:
        loc = _loc_mod.Locator(kind=loc.kind, origin=loc.origin, subdir=subdir, ref=loc.ref)

    # ── 2. Fetch ──────────────────────────────────────────────────────────── #
    print(f"Fetching {locator_str!r} …", flush=True)
    result = _fetch_mod.fetch_source(loc)
    if not result.ok:
        print(
            f"Error: fetch failed for {locator_str!r}: {result.skipped_reason}",
            file=sys.stderr,
        )
        return 1

    # ── 3. Discover modules in the fetched root ────────────────────────────── #
    from discover import build_discovery_roots, discover_modules, _RootEntry, RootKind

    fetched_root = result.root_path
    # Build a minimal roots list: only the fetched source (no project/bundled)
    # so we validate JUST what's in this source, not the whole merged graph.
    root_entry = _RootEntry(path=fetched_root, kind=RootKind.FETCHED)
    # discover_modules accepts the roots list; pass an empty bundled_root so the
    # default_enabled constraint is not enforced (no bundled root in scope).
    modules, report = discover_modules([root_entry], bundled_root=fetched_root / "__nonexistent__")
    if not modules:
        error_detail = ""
        if report.hard_errors:
            error_detail = " (" + "; ".join(e.how_to_fix for e in report.hard_errors) + ")"
        print(
            f"Error: no valid modules found at {locator_str!r}{error_detail}.\n"
            f"  Checked path: {fetched_root}\n"
            f"  A valid module directory contains a module.toml with a [module] id.",
            file=sys.stderr,
        )
        return 1

    module_ids = sorted(modules.keys())
    print(f"Found {len(module_ids)} module(s): {', '.join(module_ids)}")

    # ── 4. Read existing sources.toml + dedupe + write ─────────────────────── #
    project_dir.mkdir(parents=True, exist_ok=True)
    existing_sources, skill_version, existing_meta = _read_sources_toml(project_dir)

    # Build the new source record.
    new_record: dict = {"locator": locator_str}
    # Store non-default ref explicitly so sources.toml is self-describing.
    effective_ref = loc.ref if loc.ref and loc.ref != "HEAD" else ""
    if effective_ref:
        new_record["ref"] = effective_ref
    if loc.subdir:
        new_record["subdir"] = loc.subdir

    # Dedup: skip if a record with the same normalised key already exists.
    new_key = _sources_dedup_key(new_record)
    for existing in existing_sources:
        if _sources_dedup_key(existing) == new_key:
            print(
                f"Source {locator_str!r} is already registered in "
                f".project-setup/sources.toml — no change needed.\n"
                f"Available module ids from this source: {', '.join(module_ids)}",
            )
            if enable:
                _enable_modules_in_answers(project_dir, module_ids)
                print(
                    f"Module id(s) added to .project-setup/answers.toml [modules].enabled: "
                    f"{', '.join(module_ids)}\n"
                    f"They will run on the next invocation (reproduce mode).",
                )
            return 0

    merged = existing_sources + [new_record]
    _persist_mod.write_sources_toml(project_dir, merged, skill_version=skill_version, meta=existing_meta)

    sources_path = project_dir / ".project-setup" / "sources.toml"
    if enable:
        _enable_modules_in_answers(project_dir, module_ids)
        print(
            f"\n"
            f"Registered source in {sources_path}\n"
            f"Available module ids: {', '.join(module_ids)}\n"
            f"\n"
            f"Module id(s) added to .project-setup/answers.toml [modules].enabled: "
            f"{', '.join(module_ids)}\n"
            f"They will run on the next invocation (reproduce mode — sources.toml is now present).",
        )
    else:
        print(
            f"\n"
            f"Registered source in {sources_path}\n"
            f"Available module ids: {', '.join(module_ids)}\n"
            f"\n"
            f"Next steps:\n"
            f"  Writing sources.toml has flipped this project to reproduce mode.\n"
            f"  In reproduce mode the enabled set is read from the COMMITTED\n"
            f"  .project-setup/answers.toml [modules].enabled — the --answers\n"
            f"  file's 'enabled' list is ignored.\n"
            f"\n"
            f"  To enable the module(s) either:\n"
            f"    a) Re-run with --enable:  --add-module {locator_str!r} --enable\n"
            f"    b) Add the id(s) manually to .project-setup/answers.toml:\n"
            f"       [modules]\n"
            f"       enabled = {module_ids!r}\n"
            f"\n"
            f"  Tip: use --add-module-from-catalog to browse available modules in\n"
            f"  configured catalogs, or --list-catalog to see the full catalog.",
        )
    return 0


def _cmd_list_catalog(home: Path | None = None) -> int:
    """Implement --list-catalog: print table of available addon modules.

    Returns 0 always (discovery aid; never hard-fails).
    """
    import sdk as _sdk_mod

    urls = _sdk_mod.addon_catalog_urls(home=home)
    if not urls:
        print(
            "No addon catalogs configured.\n"
            "\n"
            "To configure a catalog, set one of:\n"
            "  • Environment variable: PROJECT_SETUP_CATALOG_URL=<url>\n"
            "    (comma- or space-separated for multiple URLs)\n"
            "  • Home config file: ~/.config/project-setup/config.toml\n"
            "    [catalog]\n"
            "    urls = [\"https://example.com/catalog.json\"]\n"
            "\n"
            "A catalog is a JSON file containing an array of module records:\n"
            "  [{\"name\": \"...\", \"description\": \"...\", \"locator\": \"...\", \"category\": \"...\"}]\n"
            "\n"
            "Once a catalog is configured, use:\n"
            "  --list-catalog                 list available modules\n"
            "  --add-module-from-catalog NAME install a module by name",
        )
        return 0

    all_records: list[dict] = []
    for url in urls:
        records = _sdk_mod.fetch_addon_catalog(url)
        all_records.extend(records)

    if not all_records:
        print(
            f"Catalogs configured ({len(urls)} URL(s)) but no records returned.\n"
            "The catalog URL(s) may be unreachable or the catalog may be empty.",
        )
        return 0

    # Print a table: name | category | locator | description
    # Compute column widths for alignment.
    headers = ("name", "category", "locator", "description")
    rows = [
        (
            str(r.get("name", "")),
            str(r.get("category", "")),
            str(r.get("locator", "")),
            str(r.get("description", "")),
        )
        for r in all_records
        if isinstance(r, dict)
    ]

    col_widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            col_widths[i] = max(col_widths[i], len(cell))

    sep = "  "
    header_line = sep.join(h.ljust(col_widths[i]) for i, h in enumerate(headers))
    divider = sep.join("-" * col_widths[i] for i in range(len(headers)))

    print(f"Addon modules ({len(rows)} total from {len(urls)} catalog(s)):\n")
    print(header_line)
    print(divider)
    for row in rows:
        print(sep.join(cell.ljust(col_widths[i]) for i, cell in enumerate(row)))

    print(
        f"\nTo add a module:\n"
        f"  project-setup --add-module-from-catalog <name> --project-dir <dir>\n"
        f"  project-setup --add-module <locator> --project-dir <dir>",
    )
    return 0


def _cmd_add_module_from_catalog(
    project_dir: Path,
    name: str,
    ref: str | None,
    subdir: str | None,
    home: Path | None = None,
) -> int:
    """Implement --add-module-from-catalog: look up NAME, then run --add-module.

    Returns 0 on success, 1 on error.
    """
    import sdk as _sdk_mod

    urls = _sdk_mod.addon_catalog_urls(home=home)
    if not urls:
        print(
            "Error: no addon catalogs configured.\n"
            "Use --list-catalog to see configuration instructions.",
            file=sys.stderr,
        )
        return 1

    # Fetch all records and find the first matching name.
    all_records: list[dict] = []
    for url in urls:
        records = _sdk_mod.fetch_addon_catalog(url)
        all_records.extend(records)

    matched = next(
        (r for r in all_records if isinstance(r, dict) and r.get("name") == name),
        None,
    )
    if matched is None:
        available = sorted({str(r.get("name", "")) for r in all_records if isinstance(r, dict) and r.get("name")})
        print(
            f"Error: module {name!r} not found in any configured catalog.\n"
            f"Available names: {', '.join(available) if available else '(none)'}",
            file=sys.stderr,
        )
        return 1

    locator_str = matched.get("locator", "")
    if not locator_str:
        print(
            f"Error: catalog record for {name!r} has no 'locator' field.",
            file=sys.stderr,
        )
        return 1

    # Inline ref from catalog record if the caller did not override it.
    catalog_ref = matched.get("ref") or None
    effective_ref = ref or catalog_ref

    return _cmd_add_module(project_dir, locator_str, ref=effective_ref, subdir=subdir)


# --------------------------------------------------------------------------- #
# Main                                                                        #
# --------------------------------------------------------------------------- #
def main(argv: list[str] | None = None) -> int:
    """Parse arguments, construct IO + Pipeline, return POSIX exit code."""
    parser = _build_parser()
    args = parser.parse_args(argv)

    # ── --new-module: scaffold and exit (no pipeline run) ───────────────────── #
    if args.new_module:
        project_dir = Path(args.project_dir).expanduser().resolve()
        if args.new_module_dest:
            dest_dir = Path(args.new_module_dest).expanduser().resolve()
        else:
            dest_dir = project_dir / ".project-setup" / "modules"
        return _scaffold_new_module(args.new_module, dest_dir)

    # ── --list-catalog: print catalog table and exit ─────────────────────────── #
    if args.list_catalog:
        return _cmd_list_catalog()

    # ── --add-module: fetch + register in sources.toml and exit ──────────────── #
    if args.add_module:
        project_dir = Path(args.project_dir).expanduser().resolve()
        return _cmd_add_module(
            project_dir,
            locator_str=args.add_module,
            ref=args.ref,
            subdir=args.subdir,
            enable=args.enable,
        )

    # ── --add-module-from-catalog: catalog look-up + register and exit ────────── #
    if args.add_module_from_catalog:
        project_dir = Path(args.project_dir).expanduser().resolve()
        return _cmd_add_module_from_catalog(
            project_dir,
            name=args.add_module_from_catalog,
            ref=args.ref,
            subdir=args.subdir,
        )

    project_dir = Path(args.project_dir).expanduser().resolve()
    if not project_dir.exists():
        print(
            f"Error: project directory does not exist: {project_dir}",
            file=sys.stderr,
        )
        return 1

    # ── IO construction (FR-001/002/006) ─────────────────────────────────────── #
    # Priority: --answers (agent path) > --non-interactive > TerminalIO (human).
    non_interactive = args.non_interactive
    # Gate consent flags start from CLI --allow/--skip (+ deprecated aliases); the
    # --answers path extends this with the file's allow/skip lists. This SAME set
    # must reach run_pipeline() — the pipeline's active_flags is what actually
    # drives the gate resolver, so the answers-file flags must be merged in here,
    # not just handed to FileAnswersIO.
    active_flags = _active_flags(args)
    if args.answers:
        answers_path = Path(args.answers).expanduser().resolve()
        try:
            if answers_path.suffix.lower() == ".toml":
                with answers_path.open("rb") as _f:
                    raw_answers: dict = tomllib.load(_f)
            else:
                with answers_path.open("r", encoding="utf-8") as _f:
                    raw_answers = json.load(_f)
        except Exception as exc:
            print(
                f"Error: could not read --answers {args.answers}: {exc}",
                file=sys.stderr,
            )
            return 1
        # Pull the optional top-level "enabled" list out of the dict; the rest
        # are answer entries keyed as "module_id.key" (or bare "key").
        enabled: list[str] | None = raw_answers.pop("enabled", None)
        if enabled is not None and not isinstance(enabled, list):
            print(
                f"Error: 'enabled' in --answers file must be a list of module ids, got {type(enabled).__name__}",
                file=sys.stderr,
            )
            return 1

        # Pull optional allow/skip lists from the answers file (primary consent path).
        file_allow = raw_answers.pop("allow", None)
        file_skip = raw_answers.pop("skip", None)
        if file_allow is not None and not isinstance(file_allow, list):
            print(
                f"Error: 'allow' in --answers file must be a list of flag names, got {type(file_allow).__name__}",
                file=sys.stderr,
            )
            return 1
        if file_skip is not None and not isinstance(file_skip, list):
            print(
                f"Error: 'skip' in --answers file must be a list of flag names, got {type(file_skip).__name__}",
                file=sys.stderr,
            )
            return 1

        # Merge answers-file flags into the active set (union with CLI flags).
        if file_allow:
            active_flags = active_flags | frozenset(str(f) for f in file_allow)
        if file_skip:
            active_flags = active_flags | frozenset(str(f) for f in file_skip)

        io = FileAnswersIO(
            answers=raw_answers,
            enabled=enabled,
            active_flags=active_flags,
        )
        non_interactive = True  # answer-driven implies non-interactive semantics
    elif args.non_interactive:
        io = TerminalIO()
    else:
        io = TerminalIO()

    try:
        result = run_pipeline(
            project_dir=project_dir,
            io=io,
            skill_version=args.skill_version,
            non_interactive=non_interactive,
            dry_run=args.dry_run,
            check_only=args.check_answers,
            refresh=args.refresh,
            active_flags=active_flags,
        )
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if not result.success:
        for err in result.errors:
            print(f"[ERROR] {err.how_to_fix}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
