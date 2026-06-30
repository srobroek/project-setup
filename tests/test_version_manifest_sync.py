"""Guard against release-please version-metadata drift.

The release-please typed `extra-files` updaters (yaml `$.version` for apm.yml,
toml `$.module.version` for each module) have historically failed to fire,
leaving `apm.yml` and the module `module.toml` files stuck at stale versions
while `.release-please-manifest.json` advanced (e.g. apm.yml=0.2.0 vs
component=0.3.2; modules=1.0.0 vs released 1.1.x).

This test fails the build if ANY tracked version string diverges from the
authoritative `.release-please-manifest.json`, so the drift can never silently
ship again — regardless of whether the release-please updater works.

Run: uv run --with pytest pytest -q tests/test_version_manifest_sync.py
"""

from __future__ import annotations

import json
import re
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
_MANIFEST = _REPO / ".release-please-manifest.json"


def _manifest() -> dict[str, str]:
    return json.loads(_MANIFEST.read_text(encoding="utf-8"))


def _apm_version() -> str | None:
    # Capture the bare version token; tolerate an optional trailing comment
    # (e.g. the `# x-release-please-version` annotation that drives the
    # release-please generic updater).
    m = re.search(
        r"^version:\s*[\"']?([^\s\"'#]+)", (_REPO / "apm.yml").read_text(encoding="utf-8"), re.M
    )
    return m.group(1).strip() if m else None


def _module_version(module_toml: Path) -> str | None:
    # version key under the [module] table only
    text = module_toml.read_text(encoding="utf-8")
    m = re.search(r"\[module\].*?^version\s*=\s*\"([^\"]+)\"", text, re.S | re.M)
    return m.group(1) if m else None


def test_apm_yml_version_matches_manifest():
    want = _manifest()["skills/project-setup"]
    assert _apm_version() == want, (
        f"apm.yml version drifted: file={_apm_version()!r} manifest={want!r}. "
        "release-please extra-files ($.version) did not sync — correct apm.yml."
    )


def test_all_module_versions_match_manifest():
    manifest = _manifest()
    drift: list[str] = []
    for path, want in manifest.items():
        if path == "skills/project-setup":
            continue  # apm.yml, covered above
        module_toml = _REPO / path / "module.toml"
        if not module_toml.exists():
            drift.append(f"{path}: module.toml MISSING (manifest wants {want})")
            continue
        got = _module_version(module_toml)
        if got != want:
            drift.append(f"{path}: file={got!r} manifest={want!r}")
    assert not drift, (
        "module.toml versions drifted from .release-please-manifest.json:\n  "
        + "\n  ".join(drift)
    )
