"""Tests for FIX 3: lang-python pin format — @ converted to == in pyproject.toml.

Verifies:
(a) runtime pins ["fastapi@0.115.0","uvicorn@0.32.0"] produce "fastapi==0.115.0" in pyproject
(b) same for dev group
(c) already-== pin passes through unchanged
(d) generated pyproject parses with tomllib and dep strings are valid PEP 508

Run: uv run --with pytest pytest -q tests/test_lang_python_pin_format.py
"""

from __future__ import annotations

import importlib.util
import sys
import tomllib
from pathlib import Path

import pytest

_PKG = Path(__file__).resolve().parents[1]
_PLUGIN_ROOT = _PKG / "skills" / "project-setup"
_MODULE_DIR = _PLUGIN_ROOT / "modules" / "lang-python"


def _load_module_py():
    """Load the lang-python module.py to access helpers."""
    spec = importlib.util.spec_from_file_location(
        "lang_python_module", _MODULE_DIR / "module.py"
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    # Don't register as 'lang_python_module' in sys.modules permanently;
    # just exec it for access to its functions.
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def lang_python():
    return _load_module_py()


# --------------------------------------------------------------------------- #
# Test _to_pep508 helper                                                       #
# --------------------------------------------------------------------------- #
def test_to_pep508_at_to_equals(lang_python):
    """name@version is converted to name==version."""
    assert lang_python._to_pep508("fastapi@0.115.0") == "fastapi==0.115.0"
    assert lang_python._to_pep508("uvicorn@0.32.0") == "uvicorn==0.32.0"


def test_to_pep508_already_equals(lang_python):
    """name==version passes through unchanged."""
    assert lang_python._to_pep508("ruff==0.6.9") == "ruff==0.6.9"


def test_to_pep508_bare_name(lang_python):
    """A bare name without version passes through unchanged."""
    assert lang_python._to_pep508("requests") == "requests"


def test_to_pep508_last_at(lang_python):
    """Splits on the LAST @ (handles unlikely scoped-like names)."""
    assert lang_python._to_pep508("some-pkg@1.2.3") == "some-pkg==1.2.3"


# --------------------------------------------------------------------------- #
# (a) runtime pins with @ produce == in pyproject.toml                         #
# --------------------------------------------------------------------------- #
def test_runtime_pins_written_as_pep508(tmp_path, lang_python):
    """Runtime pins with @ format produce == in [project].dependencies."""
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        '[project]\nname = "demo"\ndependencies = []\n',
        encoding="utf-8",
    )

    warnings: list[str] = []
    lang_python._patch_pyproject_deps(
        pyproject,
        runtime_pins=["fastapi@0.115.0", "uvicorn@0.32.0"],
        dev_pins=[],
        warnings=warnings,
    )

    content = pyproject.read_text(encoding="utf-8")
    assert "fastapi==0.115.0" in content
    assert "uvicorn==0.32.0" in content
    assert "@" not in content.split("dependencies")[1].split("]")[0]


# --------------------------------------------------------------------------- #
# (b) dev group pins with @ produce == in pyproject.toml                       #
# --------------------------------------------------------------------------- #
def test_dev_pins_written_as_pep508(tmp_path, lang_python):
    """Dev pins with @ format produce == in [dependency-groups].dev."""
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        '[project]\nname = "demo"\ndependencies = []\n\n'
        '[dependency-groups]\ndev = []\n',
        encoding="utf-8",
    )

    warnings: list[str] = []
    lang_python._patch_pyproject_deps(
        pyproject,
        runtime_pins=[],
        dev_pins=["ruff@0.6.9", "pytest@8.3.0"],
        warnings=warnings,
    )

    content = pyproject.read_text(encoding="utf-8")
    assert "ruff==0.6.9" in content
    assert "pytest==8.3.0" in content
    # No @ in the dev section
    dev_section = content.split("[dependency-groups]")[1]
    assert "@" not in dev_section.split("]")[0]


# --------------------------------------------------------------------------- #
# (c) already-== pin passes through unchanged                                  #
# --------------------------------------------------------------------------- #
def test_already_equals_pin_passes_through(tmp_path, lang_python):
    """Pins already using == format are not modified."""
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        '[project]\nname = "demo"\ndependencies = []\n',
        encoding="utf-8",
    )

    warnings: list[str] = []
    lang_python._patch_pyproject_deps(
        pyproject,
        runtime_pins=["httpx==0.27.0"],
        dev_pins=[],
        warnings=warnings,
    )

    content = pyproject.read_text(encoding="utf-8")
    assert "httpx==0.27.0" in content


# --------------------------------------------------------------------------- #
# (d) generated pyproject parses with tomllib and deps are valid PEP 508       #
# --------------------------------------------------------------------------- #
def test_generated_pyproject_is_valid_toml(tmp_path, lang_python):
    """The generated pyproject.toml parses with stdlib tomllib."""
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        '[project]\nname = "demo"\ndependencies = []\n\n'
        '[dependency-groups]\ndev = []\n',
        encoding="utf-8",
    )

    warnings: list[str] = []
    lang_python._patch_pyproject_deps(
        pyproject,
        runtime_pins=["fastapi@0.115.0", "uvicorn@0.32.0"],
        dev_pins=["ruff@0.6.9", "pytest@8.3.0"],
        warnings=warnings,
    )

    # Must parse without error
    with pyproject.open("rb") as f:
        data = tomllib.load(f)

    # Validate dep strings are PEP 508 (no @)
    for dep in data["project"]["dependencies"]:
        assert "@" not in dep, f"dep {dep!r} still contains @"
        assert "==" in dep or dep.isidentifier(), f"dep {dep!r} is not valid PEP 508"

    for dep in data["dependency-groups"]["dev"]:
        assert "@" not in dep, f"dev dep {dep!r} still contains @"
        assert "==" in dep or dep.isidentifier(), f"dev dep {dep!r} is not valid PEP 508"
