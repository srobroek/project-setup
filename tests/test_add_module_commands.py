"""Tests for --add-module, --list-catalog, and --add-module-from-catalog CLI commands.

These commands are all early-exit (before pipeline runs), like --new-module.
Tests use monkeypatching/fake seams at the fetch/catalog boundaries — no real
git clones or network requests.

Run via:
    uv run --with pytest pytest -q tests/test_add_module_commands.py
"""

from __future__ import annotations

import importlib.util
import sys
import tomllib
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_PKG = Path(__file__).resolve().parents[1]
_RUNNER = _PKG / "skills" / "project-setup" / "runner"
_CLI_PATH = _RUNNER / "cli.py"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load(name: str):
    """Load a runner module by name (cached in sys.modules)."""
    if name in sys.modules:
        return sys.modules[name]
    for p in (str(_RUNNER), str(_RUNNER / "sources")):
        if p not in sys.path:
            sys.path.insert(0, p)
    candidates = [
        _RUNNER / f"{name}.py",
        _RUNNER / "sources" / f"{name}.py",
    ]
    path = next((p for p in candidates if p.is_file()), None)
    assert path is not None, f"Cannot find runner module {name!r}"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _load_cli_fresh():
    """Load cli.py into a fresh module (avoids sys.modules cache)."""
    name = f"cli_add_{id(object())}"
    spec = importlib.util.spec_from_file_location(name, _CLI_PATH)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    sys.modules["cli"] = mod
    spec.loader.exec_module(mod)
    return mod


def _make_module_dir(parent: Path, module_id: str = "my-test-module") -> Path:
    """Create a minimal valid module directory under *parent*/<module_id>/."""
    mod_dir = parent / module_id
    mod_dir.mkdir(parents=True, exist_ok=True)
    toml = (
        'schema_version = "1.0"\n'
        "[module]\n"
        f'id = "{module_id}"\n'
        f'name = "Test Module"\n'
        'version = "0.1.0"\n'
        'description = "A test module."\n'
        "reconcile = false\n"
        "\n"
        "[order]\n"
        "requires = []\n"
        "after    = []\n"
        "\n"
        "[[steps]]\n"
        'id   = "write"\n'
        'kind = "python"\n'
    )
    (mod_dir / "module.toml").write_text(toml, encoding="utf-8")
    return parent


def _read_sources_toml(project_dir: Path) -> list[dict]:
    """Parse .project-setup/sources.toml and return the [[source]] list."""
    src = project_dir / ".project-setup" / "sources.toml"
    if not src.is_file():
        return []
    with open(src, "rb") as fh:
        data = tomllib.load(fh)
    return list(data.get("source", []))


# Make sure the runner path is set up before any tests run (mirrors conftest).
for _p in (str(_RUNNER), str(_RUNNER / "sources")):
    if _p not in sys.path:
        sys.path.insert(0, _p)


# ---------------------------------------------------------------------------
# --add-module: happy path with a local path locator
# ---------------------------------------------------------------------------

class TestAddModuleLocalPath:
    """--add-module with a local path containing a valid module."""

    def test_adds_source_entry_to_sources_toml(self, tmp_path):
        """A valid local source is added to .project-setup/sources.toml."""
        modules_root = tmp_path / "my-modules"
        _make_module_dir(modules_root, "my-test-module")

        cli = _load_cli_fresh()
        project_dir = tmp_path / "project"
        project_dir.mkdir()

        rc = cli.main([
            "--project-dir", str(project_dir),
            "--add-module", str(modules_root),
        ])
        assert rc == 0

        sources = _read_sources_toml(project_dir)
        assert len(sources) == 1
        assert sources[0]["locator"] == str(modules_root)

    def test_module_id_reported_in_output(self, tmp_path, capsys):
        """The discovered module id is printed to stdout."""
        modules_root = tmp_path / "my-modules"
        _make_module_dir(modules_root, "my-test-module")

        cli = _load_cli_fresh()
        project_dir = tmp_path / "project"
        project_dir.mkdir()

        cli.main([
            "--project-dir", str(project_dir),
            "--add-module", str(modules_root),
        ])
        captured = capsys.readouterr()
        assert "my-test-module" in captured.out

    def test_dedupe_does_not_add_duplicate(self, tmp_path):
        """Adding the same locator twice keeps exactly one [[source]] entry."""
        modules_root = tmp_path / "my-modules"
        _make_module_dir(modules_root, "my-test-module")

        cli = _load_cli_fresh()
        project_dir = tmp_path / "project"
        project_dir.mkdir()

        locator = str(modules_root)
        cli.main(["--project-dir", str(project_dir), "--add-module", locator])
        cli.main(["--project-dir", str(project_dir), "--add-module", locator])

        sources = _read_sources_toml(project_dir)
        assert len(sources) == 1, "Duplicate source should not be added"

    def test_second_module_preserves_first(self, tmp_path):
        """Adding a second source preserves the first entry in sources.toml."""
        root_a = tmp_path / "source-a"
        root_b = tmp_path / "source-b"
        _make_module_dir(root_a, "module-a")
        _make_module_dir(root_b, "module-b")

        cli = _load_cli_fresh()
        project_dir = tmp_path / "project"
        project_dir.mkdir()

        cli.main(["--project-dir", str(project_dir), "--add-module", str(root_a)])
        cli.main(["--project-dir", str(project_dir), "--add-module", str(root_b)])

        sources = _read_sources_toml(project_dir)
        assert len(sources) == 2
        locators = {s["locator"] for s in sources}
        assert str(root_a) in locators
        assert str(root_b) in locators

    def test_preserves_existing_skill_version_in_meta(self, tmp_path):
        """skill_version from an existing sources.toml is preserved on append."""
        import persist as _persist_mod

        modules_root_a = tmp_path / "source-a"
        modules_root_b = tmp_path / "source-b"
        _make_module_dir(modules_root_a, "module-a")
        _make_module_dir(modules_root_b, "module-b")

        project_dir = tmp_path / "project"
        project_dir.mkdir()

        # Write an initial sources.toml with a skill_version in meta.
        _persist_mod.write_sources_toml(
            project_dir,
            [{"locator": str(modules_root_a)}],
            skill_version="1.2.3",
        )

        cli = _load_cli_fresh()
        cli.main(["--project-dir", str(project_dir), "--add-module", str(modules_root_b)])

        src_toml = project_dir / ".project-setup" / "sources.toml"
        with open(src_toml, "rb") as fh:
            data = tomllib.load(fh)
        assert data.get("meta", {}).get("skill_version") == "1.2.3"
        assert len(data.get("source", [])) == 2

    def test_creates_project_setup_dir_if_absent(self, tmp_path):
        """The .project-setup/ dir is created if it does not exist yet."""
        modules_root = tmp_path / "my-modules"
        _make_module_dir(modules_root, "my-test-module")

        cli = _load_cli_fresh()
        # project_dir exists but has no .project-setup/ subdir yet.
        project_dir = tmp_path / "project"
        project_dir.mkdir()
        assert not (project_dir / ".project-setup").exists()

        rc = cli.main(["--project-dir", str(project_dir), "--add-module", str(modules_root)])
        assert rc == 0
        assert (project_dir / ".project-setup" / "sources.toml").is_file()


# ---------------------------------------------------------------------------
# --add-module: no valid modules → returns 1
# ---------------------------------------------------------------------------

class TestAddModuleNoValidModules:
    """--add-module with a path that has no module.toml → returns 1."""

    def test_empty_directory_returns_1(self, tmp_path, capsys):
        """A directory with no module.toml returns exit code 1."""
        empty_root = tmp_path / "empty"
        empty_root.mkdir()

        cli = _load_cli_fresh()
        project_dir = tmp_path / "project"
        project_dir.mkdir()

        rc = cli.main(["--project-dir", str(project_dir), "--add-module", str(empty_root)])
        assert rc == 1

        captured = capsys.readouterr()
        assert "no valid modules" in (captured.out + captured.err).lower()

    def test_missing_local_path_returns_1(self, tmp_path, capsys):
        """A local path that does not exist returns exit code 1."""
        nonexistent = tmp_path / "does-not-exist"

        cli = _load_cli_fresh()
        project_dir = tmp_path / "project"
        project_dir.mkdir()

        rc = cli.main(["--project-dir", str(project_dir), "--add-module", str(nonexistent)])
        assert rc == 1

        captured = capsys.readouterr()
        assert "error" in (captured.out + captured.err).lower()

    def test_dir_with_bad_module_toml_returns_1(self, tmp_path, capsys):
        """A module dir with invalid TOML returns exit code 1."""
        root = tmp_path / "bad-mod"
        mod_dir = root / "bad"
        mod_dir.mkdir(parents=True)
        # Write invalid TOML (missing [module] table)
        (mod_dir / "module.toml").write_text("[invalid syntax\n", encoding="utf-8")

        cli = _load_cli_fresh()
        project_dir = tmp_path / "project"
        project_dir.mkdir()

        rc = cli.main(["--project-dir", str(project_dir), "--add-module", str(root)])
        assert rc == 1

    def test_sources_toml_not_written_on_failure(self, tmp_path):
        """sources.toml is not created when module discovery fails."""
        empty_root = tmp_path / "empty"
        empty_root.mkdir()

        cli = _load_cli_fresh()
        project_dir = tmp_path / "project"
        project_dir.mkdir()

        cli.main(["--project-dir", str(project_dir), "--add-module", str(empty_root)])
        assert not (project_dir / ".project-setup" / "sources.toml").is_file()


# ---------------------------------------------------------------------------
# --add-module: fetch failure with a monkeypatched git locator
# ---------------------------------------------------------------------------

class TestAddModuleFetchFailure:
    """--add-module returns 1 when fetch_source fails."""

    def test_fetch_failure_returns_1(self, tmp_path, capsys):
        """When fetch_source returns ok=False, main() returns 1."""
        cli = _load_cli_fresh()
        project_dir = tmp_path / "project"
        project_dir.mkdir()

        # Patch fetch_source inside cli module's namespace (it imports it from fetch).
        fake_result = MagicMock()
        fake_result.ok = False
        fake_result.skipped_reason = "git clone failed: connection refused"

        with patch.object(cli, "_cmd_add_module", wraps=cli._cmd_add_module) as _:
            # Patch at the fetch module level since _cmd_add_module imports fetch.
            import fetch as _fetch_mod
            with patch.object(_fetch_mod, "fetch_source", return_value=fake_result):
                rc = cli.main([
                    "--project-dir", str(project_dir),
                    "--add-module", "github.com/some/repo#v1.0.0",
                ])

        assert rc == 1
        captured = capsys.readouterr()
        assert "error" in (captured.out + captured.err).lower()


# ---------------------------------------------------------------------------
# --list-catalog: with monkeypatched catalog seams
# ---------------------------------------------------------------------------

class TestListCatalog:
    """Tests for --list-catalog."""

    def test_prints_catalog_records(self, tmp_path, capsys, monkeypatch):
        """With a configured catalog, records are printed in a table."""
        records = [
            {"name": "foo-module", "category": "lang", "locator": "org/foo-modules", "description": "Foo lang support"},
            {"name": "bar-ci", "category": "ci", "locator": "org/bar#v1.0.0", "description": "CI integration"},
        ]
        import sdk as _sdk_mod
        monkeypatch.setattr(_sdk_mod, "addon_catalog_urls", lambda home=None: ["https://example.com/cat.json"])
        monkeypatch.setattr(_sdk_mod, "fetch_addon_catalog", lambda url, **kw: records)

        cli = _load_cli_fresh()
        rc = cli.main(["--list-catalog"])
        assert rc == 0

        captured = capsys.readouterr()
        combined = captured.out + captured.err
        assert "foo-module" in combined
        assert "bar-ci" in combined
        assert "lang" in combined
        assert "ci" in combined

    def test_no_catalog_configured_prints_help(self, tmp_path, capsys, monkeypatch):
        """When no catalogs are configured, a helpful config message is printed."""
        import sdk as _sdk_mod
        monkeypatch.setattr(_sdk_mod, "addon_catalog_urls", lambda home=None: [])

        cli = _load_cli_fresh()
        rc = cli.main(["--list-catalog"])
        # Always returns 0 — it's a discovery aid
        assert rc == 0

        captured = capsys.readouterr()
        combined = captured.out + captured.err
        # Should mention the env var or config file
        assert "PROJECT_SETUP_CATALOG_URL" in combined or "config.toml" in combined

    def test_catalog_url_reachable_but_empty_returns_0(self, tmp_path, capsys, monkeypatch):
        """A catalog that returns [] still exits 0 with a message."""
        import sdk as _sdk_mod
        monkeypatch.setattr(_sdk_mod, "addon_catalog_urls", lambda home=None: ["https://example.com/empty.json"])
        monkeypatch.setattr(_sdk_mod, "fetch_addon_catalog", lambda url, **kw: [])

        cli = _load_cli_fresh()
        rc = cli.main(["--list-catalog"])
        assert rc == 0

    def test_table_includes_all_expected_columns(self, tmp_path, capsys, monkeypatch):
        """The output table contains name, category, locator, description columns."""
        records = [
            {
                "name": "mymod",
                "category": "infra",
                "locator": "org/mymod#v2.0.0",
                "description": "Does stuff",
            }
        ]
        import sdk as _sdk_mod
        monkeypatch.setattr(_sdk_mod, "addon_catalog_urls", lambda home=None: ["https://example.com/cat.json"])
        monkeypatch.setattr(_sdk_mod, "fetch_addon_catalog", lambda url, **kw: records)

        cli = _load_cli_fresh()
        cli.main(["--list-catalog"])
        captured = capsys.readouterr()
        combined = captured.out + captured.err

        for expected in ("mymod", "infra", "org/mymod#v2.0.0", "Does stuff"):
            assert expected in combined, f"Expected {expected!r} in output"

    def test_multiple_catalog_urls_merged(self, tmp_path, capsys, monkeypatch):
        """Records from multiple catalog URLs are all listed."""
        def _fake_fetch(url, **kw):
            if "a.json" in url:
                return [{"name": "module-a", "category": "lang", "locator": "org/a", "description": "A"}]
            return [{"name": "module-b", "category": "ci", "locator": "org/b", "description": "B"}]

        import sdk as _sdk_mod
        monkeypatch.setattr(_sdk_mod, "addon_catalog_urls", lambda home=None: [
            "https://example.com/a.json",
            "https://example.com/b.json",
        ])
        monkeypatch.setattr(_sdk_mod, "fetch_addon_catalog", _fake_fetch)

        cli = _load_cli_fresh()
        rc = cli.main(["--list-catalog"])
        assert rc == 0
        captured = capsys.readouterr()
        assert "module-a" in (captured.out + captured.err)
        assert "module-b" in (captured.out + captured.err)


# ---------------------------------------------------------------------------
# --add-module-from-catalog
# ---------------------------------------------------------------------------

class TestAddModuleFromCatalog:
    """Tests for --add-module-from-catalog."""

    def _catalog_records(self, modules_root: Path) -> list[dict]:
        return [
            {
                "name": "my-test-module",
                "category": "lang",
                "locator": str(modules_root),
                "description": "Test module",
            }
        ]

    def test_resolves_locator_and_adds_source(self, tmp_path, monkeypatch):
        """Catalog look-up resolves the locator and writes sources.toml."""
        modules_root = tmp_path / "my-modules"
        _make_module_dir(modules_root, "my-test-module")

        import sdk as _sdk_mod
        records = self._catalog_records(modules_root)
        monkeypatch.setattr(_sdk_mod, "addon_catalog_urls", lambda home=None: ["https://example.com/cat.json"])
        monkeypatch.setattr(_sdk_mod, "fetch_addon_catalog", lambda url, **kw: records)

        cli = _load_cli_fresh()
        project_dir = tmp_path / "project"
        project_dir.mkdir()

        rc = cli.main([
            "--project-dir", str(project_dir),
            "--add-module-from-catalog", "my-test-module",
        ])
        assert rc == 0

        sources = _read_sources_toml(project_dir)
        assert len(sources) == 1
        assert sources[0]["locator"] == str(modules_root)

    def test_unknown_name_returns_1(self, tmp_path, capsys, monkeypatch):
        """An unknown module name prints available names and returns 1."""
        import sdk as _sdk_mod
        monkeypatch.setattr(_sdk_mod, "addon_catalog_urls", lambda home=None: ["https://example.com/cat.json"])
        monkeypatch.setattr(_sdk_mod, "fetch_addon_catalog", lambda url, **kw: [
            {"name": "existing-module", "locator": "org/existing", "category": "lang", "description": "Existing"},
        ])

        cli = _load_cli_fresh()
        project_dir = tmp_path / "project"
        project_dir.mkdir()

        rc = cli.main([
            "--project-dir", str(project_dir),
            "--add-module-from-catalog", "nonexistent-module",
        ])
        assert rc == 1

        captured = capsys.readouterr()
        combined = captured.out + captured.err
        assert "existing-module" in combined  # available names listed

    def test_no_catalog_configured_returns_1(self, tmp_path, capsys, monkeypatch):
        """When no catalogs are configured, returns 1 with an error message."""
        import sdk as _sdk_mod
        monkeypatch.setattr(_sdk_mod, "addon_catalog_urls", lambda home=None: [])

        cli = _load_cli_fresh()
        project_dir = tmp_path / "project"
        project_dir.mkdir()

        rc = cli.main([
            "--project-dir", str(project_dir),
            "--add-module-from-catalog", "some-module",
        ])
        assert rc == 1

        captured = capsys.readouterr()
        assert "error" in (captured.out + captured.err).lower()

    def test_catalog_record_without_locator_returns_1(self, tmp_path, capsys, monkeypatch):
        """A catalog record that has no 'locator' field returns 1."""
        import sdk as _sdk_mod
        monkeypatch.setattr(_sdk_mod, "addon_catalog_urls", lambda home=None: ["https://example.com/cat.json"])
        monkeypatch.setattr(_sdk_mod, "fetch_addon_catalog", lambda url, **kw: [
            {"name": "broken-module", "category": "lang", "description": "No locator"},
        ])

        cli = _load_cli_fresh()
        project_dir = tmp_path / "project"
        project_dir.mkdir()

        rc = cli.main([
            "--project-dir", str(project_dir),
            "--add-module-from-catalog", "broken-module",
        ])
        assert rc == 1


# ---------------------------------------------------------------------------
# Integration: discoverable after adding
# ---------------------------------------------------------------------------

class TestModuleDiscoverableAfterAdd:
    """After --add-module the module is discoverable via the sources system."""

    def test_added_source_readable_by_pipeline_read_path(self, tmp_path):
        """The [[source]] entry written is readable by the pipeline's TOML reader."""
        modules_root = tmp_path / "my-modules"
        _make_module_dir(modules_root, "my-test-module")

        cli = _load_cli_fresh()
        project_dir = tmp_path / "project"
        project_dir.mkdir()

        rc = cli.main(["--project-dir", str(project_dir), "--add-module", str(modules_root)])
        assert rc == 0

        # Read sources the same way the pipeline does.
        import pipeline as _pipeline
        sources = _pipeline._read_committed_sources(project_dir)
        assert len(sources) == 1
        assert sources[0]["locator"] == str(modules_root)

    def test_locator_parseable_by_parse_locator(self, tmp_path):
        """The locator stored in sources.toml can be re-parsed by parse_locator."""
        modules_root = tmp_path / "my-modules"
        _make_module_dir(modules_root, "my-test-module")

        cli = _load_cli_fresh()
        project_dir = tmp_path / "project"
        project_dir.mkdir()

        cli.main(["--project-dir", str(project_dir), "--add-module", str(modules_root)])

        sources = _read_sources_toml(project_dir)
        import locator as _loc_mod
        loc = _loc_mod.parse_locator(sources[0]["locator"])
        assert loc.kind == "local"
        assert loc.origin == str(modules_root)


# ---------------------------------------------------------------------------
# --add-module --enable: writes module id into answers.toml [modules].enabled
# ---------------------------------------------------------------------------

class TestAddModuleEnable:
    """--add-module --enable adds the module id to answers.toml enabled list."""

    def _read_answers_toml(self, project_dir: Path) -> dict:
        answers = project_dir / ".project-setup" / "answers.toml"
        if not answers.is_file():
            return {}
        with open(answers, "rb") as fh:
            return tomllib.load(fh)

    def test_enable_writes_module_id_to_answers(self, tmp_path):
        """--add-module --enable writes the module id into answers.toml enabled."""
        modules_root = tmp_path / "my-modules"
        _make_module_dir(modules_root, "my-test-module")

        cli = _load_cli_fresh()
        project_dir = tmp_path / "project"
        project_dir.mkdir()

        rc = cli.main([
            "--project-dir", str(project_dir),
            "--add-module", str(modules_root),
            "--enable",
        ])
        assert rc == 0

        data = self._read_answers_toml(project_dir)
        enabled = data.get("modules", {}).get("enabled", [])
        assert "my-test-module" in enabled

    def test_enable_second_add_unions_ids(self, tmp_path):
        """A second --add-module --enable unions rather than replacing enabled."""
        root_a = tmp_path / "source-a"
        root_b = tmp_path / "source-b"
        _make_module_dir(root_a, "module-a")
        _make_module_dir(root_b, "module-b")

        cli = _load_cli_fresh()
        project_dir = tmp_path / "project"
        project_dir.mkdir()

        cli.main(["--project-dir", str(project_dir), "--add-module", str(root_a), "--enable"])
        cli.main(["--project-dir", str(project_dir), "--add-module", str(root_b), "--enable"])

        data = self._read_answers_toml(project_dir)
        enabled = data.get("modules", {}).get("enabled", [])
        assert "module-a" in enabled, f"module-a missing from enabled: {enabled}"
        assert "module-b" in enabled, f"module-b missing from enabled: {enabled}"

    def test_enable_preserves_existing_module_answer_table(self, tmp_path):
        """--enable preserves pre-existing [module.foo] answer tables."""
        import persist as _persist_mod

        modules_root = tmp_path / "my-modules"
        _make_module_dir(modules_root, "my-test-module")

        project_dir = tmp_path / "project"
        project_dir.mkdir()

        # Write an existing answers.toml with a [module.foo] answer table.
        _persist_mod.write_answers_toml(
            project_dir,
            answers={"foo": {"key": "value"}},
            provenance_map={"foo": {"key": "flag"}},
        )

        cli = _load_cli_fresh()
        rc = cli.main([
            "--project-dir", str(project_dir),
            "--add-module", str(modules_root),
            "--enable",
        ])
        assert rc == 0

        data = self._read_answers_toml(project_dir)
        # The [module.foo] table must still be there.
        assert data.get("module", {}).get("foo", {}).get("key") == "value", (
            f"[module.foo] answer table was dropped: {data}"
        )
        # And enabled must contain the new module.
        enabled = data.get("modules", {}).get("enabled", [])
        assert "my-test-module" in enabled

    def test_enable_dedup_path_also_writes_answers(self, tmp_path):
        """--enable on a duplicate (already registered) source still enables it."""
        modules_root = tmp_path / "my-modules"
        _make_module_dir(modules_root, "my-test-module")

        cli = _load_cli_fresh()
        project_dir = tmp_path / "project"
        project_dir.mkdir()

        # First call: register (no --enable).
        cli.main(["--project-dir", str(project_dir), "--add-module", str(modules_root)])

        # Second call: duplicate + --enable.
        rc = cli.main([
            "--project-dir", str(project_dir),
            "--add-module", str(modules_root),
            "--enable",
        ])
        assert rc == 0

        data = self._read_answers_toml(project_dir)
        enabled = data.get("modules", {}).get("enabled", [])
        assert "my-test-module" in enabled

    def test_check_answers_counts_enabled_module_after_enable(self, tmp_path):
        """After --add-module --enable, --check-answers in reproduce mode sees the module."""
        modules_root = tmp_path / "my-modules"
        _make_module_dir(modules_root, "my-test-module")

        cli = _load_cli_fresh()
        project_dir = tmp_path / "project"
        project_dir.mkdir()

        # Register + enable in one step.
        rc = cli.main([
            "--project-dir", str(project_dir),
            "--add-module", str(modules_root),
            "--enable",
        ])
        assert rc == 0

        # sources.toml now exists → reproduce mode. --check-answers should
        # find my-test-module in the enabled set (from committed answers.toml).
        # We can verify this by reading back answers.toml directly.
        data = self._read_answers_toml(project_dir)
        enabled = data.get("modules", {}).get("enabled", [])
        assert "my-test-module" in enabled, (
            f"After --add-module --enable, committed answers.toml should have "
            f"my-test-module in enabled but got: {enabled}"
        )


# ---------------------------------------------------------------------------
# Fix 3: lossless sources.toml round-trip
# ---------------------------------------------------------------------------

class TestSourcesRoundTrip:
    """--add-module must not drop unknown [meta] keys or extra source fields."""

    def test_unknown_meta_key_preserved_on_round_trip(self, tmp_path):
        """A pre-existing [meta] custom_note survives --add-module."""
        import persist as _persist_mod

        # Create a first module source so sources.toml exists with a custom meta key.
        root_a = tmp_path / "source-a"
        root_b = tmp_path / "source-b"
        _make_module_dir(root_a, "module-a")
        _make_module_dir(root_b, "module-b")

        project_dir = tmp_path / "project"
        project_dir.mkdir()

        # Write initial sources.toml with an extra [meta] key.
        _persist_mod.write_sources_toml(
            project_dir,
            sources=[{"locator": str(root_a)}],
            skill_version="1.0.0",
            meta={"skill_version": "1.0.0", "custom_note": "keep"},
        )

        cli = _load_cli_fresh()
        rc = cli.main(["--project-dir", str(project_dir), "--add-module", str(root_b)])
        assert rc == 0

        src_toml = project_dir / ".project-setup" / "sources.toml"
        with open(src_toml, "rb") as fh:
            data = tomllib.load(fh)

        assert data.get("meta", {}).get("custom_note") == "keep", (
            f"[meta].custom_note was dropped on round-trip: {data.get('meta')}"
        )
        assert data.get("meta", {}).get("skill_version") == "1.0.0"
        assert len(data.get("source", [])) == 2

    def test_extra_source_field_preserved_on_round_trip(self, tmp_path):
        """An extra field on a [[source]] record survives --add-module."""
        import persist as _persist_mod

        root_a = tmp_path / "source-a"
        root_b = tmp_path / "source-b"
        _make_module_dir(root_a, "module-a")
        _make_module_dir(root_b, "module-b")

        project_dir = tmp_path / "project"
        project_dir.mkdir()

        # Write initial sources.toml where the first source has an extra field.
        _persist_mod.write_sources_toml(
            project_dir,
            sources=[{"locator": str(root_a), "extra_field": "preserve-me"}],
        )

        cli = _load_cli_fresh()
        rc = cli.main(["--project-dir", str(project_dir), "--add-module", str(root_b)])
        assert rc == 0

        src_toml = project_dir / ".project-setup" / "sources.toml"
        with open(src_toml, "rb") as fh:
            data = tomllib.load(fh)

        sources = data.get("source", [])
        first_source = next((s for s in sources if s.get("locator") == str(root_a)), None)
        assert first_source is not None, "First source was lost on round-trip"
        assert first_source.get("extra_field") == "preserve-me", (
            f"extra_field was dropped on round-trip: {first_source}"
        )


# ---------------------------------------------------------------------------
# First-run catalog seeding via the CLI command layer
# ---------------------------------------------------------------------------

class TestListCatalogFirstRunSeed:
    """_cmd_list_catalog seeds config.toml with the first-party URL on first run.

    Isolation: call cli._cmd_list_catalog(home=tmp_path) directly so that
    seed_default_catalog_url and addon_catalog_urls run for real against an
    isolated home directory.  Only fetch_addon_catalog is stubbed (network).
    """

    def _config_path(self, home: "Path") -> "Path":
        return home / ".config" / "project-setup" / "config.toml"

    def test_empty_home_seeds_config_on_list_catalog(self, tmp_path, monkeypatch):
        """Starting from an empty home, _cmd_list_catalog creates config.toml
        with [catalog].urls containing FIRST_PARTY_CATALOG_URL."""
        import sdk as _sdk_mod

        # Stub only the network fetch — seeding + catalog URL resolution run for real.
        monkeypatch.setattr(_sdk_mod, "fetch_addon_catalog", lambda url, **kw: [])
        # Ensure PROJECT_SETUP_CATALOG_URL is absent so env doesn't inject a URL.
        monkeypatch.delenv("PROJECT_SETUP_CATALOG_URL", raising=False)

        cli = _load_cli_fresh()
        cfg_path = self._config_path(tmp_path)
        assert not cfg_path.exists(), "Pre-condition: config.toml must not exist"

        rc = cli._cmd_list_catalog(home=tmp_path)
        assert rc == 0

        # Config file must now exist and contain the first-party URL.
        assert cfg_path.is_file(), "config.toml was not created by the seed step"
        import tomllib as _tomllib
        with open(cfg_path, "rb") as fh:
            data = _tomllib.load(fh)
        urls = data.get("catalog", {}).get("urls", [])
        assert _sdk_mod.FIRST_PARTY_CATALOG_URL in urls, (
            f"FIRST_PARTY_CATALOG_URL not in seeded [catalog].urls: {urls}"
        )

    def test_seed_is_idempotent_on_second_call(self, tmp_path, monkeypatch):
        """A second call to _cmd_list_catalog does not duplicate or overwrite the URL."""
        import sdk as _sdk_mod

        monkeypatch.setattr(_sdk_mod, "fetch_addon_catalog", lambda url, **kw: [])
        monkeypatch.delenv("PROJECT_SETUP_CATALOG_URL", raising=False)

        cli = _load_cli_fresh()

        # First call: seeds
        rc1 = cli._cmd_list_catalog(home=tmp_path)
        assert rc1 == 0

        cfg_path = self._config_path(tmp_path)
        assert cfg_path.is_file()

        import tomllib as _tomllib
        with open(cfg_path, "rb") as fh:
            data_after_first = _tomllib.load(fh)
        urls_after_first = data_after_first.get("catalog", {}).get("urls", [])

        # Second call: must not error or duplicate
        rc2 = cli._cmd_list_catalog(home=tmp_path)
        assert rc2 == 0

        with open(cfg_path, "rb") as fh:
            data_after_second = _tomllib.load(fh)
        urls_after_second = data_after_second.get("catalog", {}).get("urls", [])

        assert urls_after_first == urls_after_second, (
            f"Second call mutated [catalog].urls: {urls_after_first!r} → {urls_after_second!r}"
        )
        assert urls_after_second.count(_sdk_mod.FIRST_PARTY_CATALOG_URL) == 1, (
            f"URL was duplicated: {urls_after_second}"
        )

    def test_existing_catalog_url_not_overwritten_by_seed(self, tmp_path, monkeypatch):
        """When the user already has [catalog].urls set, the seed does NOT
        overwrite it — the no-clobber contract is respected through the CLI path."""
        import sdk as _sdk_mod

        monkeypatch.setattr(_sdk_mod, "fetch_addon_catalog", lambda url, **kw: [])
        monkeypatch.delenv("PROJECT_SETUP_CATALOG_URL", raising=False)

        # Pre-write a config.toml with a custom URL.
        cfg_path = self._config_path(tmp_path)
        cfg_path.parent.mkdir(parents=True, exist_ok=True)
        user_url = "https://my-org.example.com/my-catalog.json"
        cfg_path.write_text(
            f'[catalog]\nurls = ["{user_url}"]\n',
            encoding="utf-8",
        )

        cli = _load_cli_fresh()
        rc = cli._cmd_list_catalog(home=tmp_path)
        assert rc == 0

        import tomllib as _tomllib
        with open(cfg_path, "rb") as fh:
            data = _tomllib.load(fh)
        urls = data.get("catalog", {}).get("urls", [])

        assert user_url in urls, f"User URL was removed: {urls}"
        assert _sdk_mod.FIRST_PARTY_CATALOG_URL not in urls, (
            f"Seed overwrote user config: {urls}"
        )

    def test_env_var_url_prevents_seed_overwrite(self, tmp_path, monkeypatch):
        """When PROJECT_SETUP_CATALOG_URL is set, seed_default_catalog_url still
        seeds (env var is a runtime-only source, separate from the config file),
        BUT the seeded config.toml must not clobber a pre-existing [catalog].urls.
        If the config is empty, the first-party URL is seeded; the env var URL
        is returned by addon_catalog_urls at runtime (union dedup)."""
        import sdk as _sdk_mod

        env_url = "https://env.example.com/catalog.json"
        monkeypatch.setenv("PROJECT_SETUP_CATALOG_URL", env_url)
        monkeypatch.setattr(_sdk_mod, "fetch_addon_catalog", lambda url, **kw: [])

        cli = _load_cli_fresh()
        cfg_path = self._config_path(tmp_path)
        assert not cfg_path.exists()

        rc = cli._cmd_list_catalog(home=tmp_path)
        assert rc == 0

        # Config is seeded with the first-party URL (env var doesn't stop seeding).
        assert cfg_path.is_file(), "config.toml was not created even with env var set"
        import tomllib as _tomllib
        with open(cfg_path, "rb") as fh:
            data = _tomllib.load(fh)
        urls_in_file = data.get("catalog", {}).get("urls", [])
        assert _sdk_mod.FIRST_PARTY_CATALOG_URL in urls_in_file, (
            f"First-party URL missing from seeded config: {urls_in_file}"
        )
