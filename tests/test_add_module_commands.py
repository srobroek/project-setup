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
