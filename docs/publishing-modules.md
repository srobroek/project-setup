# Authoring and Publishing Modules

This guide covers everything you need to write a new module, test it locally,
distribute it via a git repository, and keep it versioned with the same
release model the bundled modules use.

See also the [examples directory](../skills/project-setup/examples/) for
copy-pasteable demonstrator modules, and
[AUTHORING.md](../skills/project-setup/examples/AUTHORING.md) for the SDK
public API reference.

---

## What is a module?

A module is a self-contained directory that teaches the runner one new
scaffolding capability. Every module has:

- `module.toml` — the manifest: metadata, inputs, and step declarations
- `module.py` — one or more step handlers invoked by the runner as a subprocess
- `test_*.py` — tests that verify the manifest parses and the module works in isolation
- `templates/` (optional) — vendored file templates read by `module.py`
- `steering/` (required for `agent` steps) — steering docs consumed by the
  Tier-2 agent subsystem

The runner discovers modules from multiple roots in order of descending
precedence:

1. `PROJECT_SETUP_MODULES_DIR` environment variable
2. `.project-setup/modules/` inside the target project
3. `~/.config/project-setup/modules/` in the user's home directory
4. Fetched git sources declared in `.project-setup/sources.toml`
5. Bundled modules shipped with the skill

A module at a higher-precedence root silently shadows a lower-precedence module
with the same id. This lets you override a bundled module with a local fork
for a specific project without changing global config.

---

## Quickstart: scaffold a new module

The runner's `--new-module` flag generates a valid starter directory:

```bash
# Writes .project-setup/modules/<id>/ in the current project dir
uv run /path/to/runner/cli.py --new-module my-module

# Write to a custom destination (e.g. a standalone repo)
uv run /path/to/runner/cli.py --new-module my-module --new-module-dest /path/to/dir
```

The scaffold creates:

```
my-module/
  module.toml       # valid manifest skeleton
  module.py         # minimal working step handler
  test_my_module.py # test stub (parse_manifest + compile check)
```

All three files need editing to implement your module's logic. The scaffold
is intentionally minimal — it gives you a working baseline, not a finished
implementation.

**Module ids must be lowercase kebab-case** (e.g. `my-module`, `lang-elixir`,
`org-policy`). The runner rejects ids that do not match `^[a-z][a-z0-9-]*$`.

---

## `module.toml` schema

Every field below is derived from the real manifests shipped in this repo.
Only fields that actually exist are documented here.

```toml
schema_version = "1.0"       # required; always "1.0" for now

[meta]
repository = "github.com/owner/repo"   # required; points at the module's home repo
author     = "Your Name"               # required

[module]
id          = "my-module"              # required; lowercase kebab-case
name        = "My Module"             # required; human-readable label
version     = "0.1.0"                 # required; semver
description = "One sentence."         # required
reconcile   = false                   # required bool
                                       #   false = write-if-absent (never clobber)
                                       #   true  = overwrite-to-match on every run
# default_enabled: NEVER set this on an addon module (see below)

[order]                                # all optional; default []
requires = ["core-identity"]           # hard dep: must be enabled and run first
after    = ["dirs-scaffold"]           # soft ordering: run after if both enabled
before   = []                          # soft ordering: run before if both enabled

[tools]
required = ["git"]                     # missing tool -> MISSING_REQUIRED_TOOL error
```

### `default_enabled`

`default_enabled = true` is **forbidden on addon modules** (FR-035). Only
modules bundled inside this repository may declare it. The scaffold omits it
deliberately — never add it to a module you publish in an external repo. Addon
modules are opt-in; the user enables them during the interview.

### `[[inputs]]`

Each `[[inputs]]` block declares one interview question. The runner generates
the prompt from `prompt`, freezes the answer into the plan, and makes it
available to `module.py` via `sdk.load_frozen_inputs`.

```toml
[[inputs]]
key      = "framework"       # required; the answer key; used in module.py as
                              #   inputs.get_str("framework")
type     = "string"          # required; see type table below
prompt   = "Framework name?" # required
default  = "fastapi"         # optional
required = false             # optional; default false
                              #   true = missing answer is a hard error at
                              #   the validate-closed gate

# For type="choice" or "multichoice" only:
choices  = ["fastapi", "django", "flask"]
```

Valid `type` values:

| type | accessor | description |
|---|---|---|
| `string` | `inputs.get_str(key)` | Single-line string |
| `text` | `inputs.get_str(key)` | Multi-line string |
| `int` | `inputs.get_str(key)` | Integer (returned as string) |
| `bool` | `inputs.get_bool(key)` | Boolean |
| `choice` | `inputs.get_choice(key)` | Exactly one option from `choices` |
| `multichoice` | `inputs.get_multichoice(key)` | Zero or more options from `choices` |
| `path` | `inputs.get_str(key)` | A file-system path |
| `list` | `inputs.get_list(key)` | Ordered list of strings |

There is no `secret` type. Secrets are rejected at the interview boundary (G8)
regardless of type.

### `[[steps]]`

Steps are declared in execution order. The runner dispatches each step by its
`kind`:

```toml
[[steps]]
id   = "write"    # required; matches a key in STEP_HANDLERS in module.py
kind = "python"   # required; see below

# Gate-only fields (kind = "gate"):
hardness   = "hard"              # "hard" (default) | "soft" | "informational"
allow_flag = "allow-my-action"   # flag that opts into this hard gate in CI
skip_flag  = "no-my-action"      # flag that opts out of this soft gate in CI
init_only  = true                # gate only fires at init, not on reproduce
message    = "About to do X. Proceed?"
```

`kind` values:

| kind | who handles it | when to use |
|---|---|---|
| `python` | `module.py` STEP_HANDLERS | Deterministic writes; same answers → byte-identical output |
| `agent` | Runner Tier-2 subsystem | The agent researches and records a decision (e.g. picks dependency versions) |
| `gate` | Runner gate subsystem | A confirm checkpoint before a consequential action |

**Gate hardness** controls what happens in non-interactive / CI mode:

| hardness | TTY | `--non-interactive` / CI |
|---|---|---|
| `hard` (default) | prompt `[y/N]`, default No | SAFE-skip unless `allow_flag` is passed |
| `soft` | prompt `[Y/n]`, default Yes | proceed unless `skip_flag` is passed |
| `informational` | print, no prompt | print, proceed |

**Consent flags** (`allow_flag` / `skip_flag`): each gate step declares the
name of its consent flag. The flag name is the author's choice — by convention
use `allow-<verb>` for hard gates and `no-<verb>` for soft gates. At runtime,
a user grants consent by including the flag name in the `allow` list of their
answers file (see the sibling branch `fix/plan-local-consent-redesign-pin-format`
for the canonical forward-compatible form); the runner also accepts the
equivalent `--allow-<verb>` CLI flag for scripted invocations. Step authors
should document what the gated action does and what the flag enables, so users
can make an informed decision.

---

## `module.py` step-handler contract

The runner invokes each `python` step as:

```bash
uv run module.py --plan /path/to/plan.json --step <step-id> [--inspect]
```

Every `module.py` follows the same structure:

1. Parse `--plan`, `--step`, `--inspect` with `argparse`.
2. Load the SDK via the `_load_sdk()` shim (copy it verbatim from the scaffold).
3. Load frozen inputs: `inputs = sdk.load_frozen_inputs(args.plan, module_id="my-module")`.
4. Dispatch to a step handler from `STEP_HANDLERS`.
5. Call `sdk.emit_result(...)` — **this is the only output allowed on stdout**.

Minimal example:

```python
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
from __future__ import annotations
import argparse, importlib.util, os, sys
from pathlib import Path

def _load_sdk():
    try:
        import sdk
        return sdk
    except ModuleNotFoundError:
        pass
    plugin_root = os.environ.get("PLUGIN_ROOT") or os.environ.get("CLAUDE_PLUGIN_ROOT")
    if plugin_root:
        sdk_path = Path(plugin_root) / "runner" / "sdk.py"
    else:
        sdk_path = Path(__file__).resolve().parents[2] / "runner" / "sdk.py"
    spec = importlib.util.spec_from_file_location("sdk", sdk_path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["sdk"] = mod   # register BEFORE exec_module
    spec.loader.exec_module(mod)
    return sdk

def _do_write(sdk, inputs, args):
    greeting = inputs.get_str("greeting", "Hello, world!")

    diff = sdk.idempotent_write(
        "greeting.txt",
        f"{greeting}\n",
        reconcile=inputs.reconcile,
        inspect=args.inspect,
    )

    sdk.emit_result(sdk.ModuleResult(
        module_id="my-module",
        step_id=args.step,
        status="ok",
        files_written=[] if args.inspect else [diff.path],
        diffs=[diff],
    ))
    return 0

STEP_HANDLERS = {"write": _do_write}

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", required=True)
    ap.add_argument("--step", required=True)
    ap.add_argument("--inspect", action="store_true")
    args = ap.parse_args()
    sdk = _load_sdk()
    inputs = sdk.load_frozen_inputs(args.plan, module_id="my-module")
    handler = STEP_HANDLERS.get(args.step)
    if handler is None:
        print(f"Unknown step: {args.step!r}", file=sys.stderr)
        return 1
    return handler(sdk, inputs, args)

if __name__ == "__main__":
    raise SystemExit(main())
```

### Key SDK calls

| Call | Purpose |
|---|---|
| `sdk.load_frozen_inputs(plan_path, module_id)` | Load typed inputs from the frozen plan |
| `sdk.idempotent_write(rel_path, body, *, reconcile, inspect)` | Write a file; returns a `Diff` |
| `sdk.emit_result(sdk.ModuleResult(...))` | Emit the structured result to stdout |
| `sdk.run_tool(args, cwd, warnings, label)` | Run an external tool; non-fatal on failure |
| `sdk.append_if_absent(path, marker, block, warnings, label)` | Append a block if a marker is absent |
| `sdk.verify_pins(pins, "pypi"|"npm")` | Verify `name@version` pins against a registry |

`sdk.ModuleResult` fields: `module_id`, `step_id`, `status` (`"ok"` or
`"error"`), `files_written` (list of repo-relative paths), `diffs` (list of
`sdk.Diff`), `warnings`, `message`, `error`.

`sdk.Diff(path, kind, preview)`: `kind` is `"create"`, `"modify"`, or `"skip"`.

**Do not print anything else to stdout.** The runner parses stdout as the
result JSON. Use `warnings` for non-fatal messages; use `status="error"` with
an `error` dict for failures.

The full SDK reference is in
[examples/AUTHORING.md](../skills/project-setup/examples/AUTHORING.md).

---

## Testing a module

Run the bundled test stub:

```bash
cd path/to/my-module
uv run --with pytest pytest -q test_my_module.py
```

The generated stub checks two things: that `module.toml` parses without errors,
and that `module.py` is syntactically valid Python. Add your own functional
tests by constructing a frozen plan and calling a step handler directly. See
`examples/multi-step-python/` for a complete integration test pattern.

To test a step end-to-end with a real plan:

```bash
# 1. Generate a frozen plan (dry-run — writes nothing to the project)
uv run /path/to/runner/cli.py --project-dir /tmp/test-project \
    --answers answers.json --dry-run

# 2. Run a specific step against that plan
uv run module.py --plan ~/.cache/project-setup/plan.json --step write --inspect
```

---

## Publishing a module for others to use

Publishing a module means committing it to a git repository and pointing users
at it with a `[[source]]` entry. The runner's source-fetch pipeline handles
the rest.

### Step 1: commit to a git repo

Place your module directory at a known path in any git-hosted repository.
Common layouts:

```
# Standalone module repo
my-module/
  module.toml
  module.py
  test_my_module.py

# Multi-module repo (use subdir= to reference individual modules)
modules/
  my-module/
    module.toml
    ...
  another-module/
    module.toml
    ...
```

### Step 2: tag a release

Tag the commit with a release tag. The runner's `ORG_SOURCE_UNPINNED` gate
rejects sources with no explicit ref, so every user must pin to a tag or SHA —
branch refs are rejected.

If you use release-please (as this repo does), conventional commit scopes
drive component bumps automatically. See the "Versioning" section below.

### Step 3: declare the source in `sources.toml`

Users add the module by declaring it in their project's
`.project-setup/sources.toml`:

```toml
[[source]]
locator = "github.com/owner/my-module-repo"
ref     = "v1.2.0"          # tag or commit SHA — never a branch

# If your module lives in a subdirectory of the repo:
# subdir = "modules/my-module"
```

Fields:

| field | required | description |
|---|---|---|
| `locator` | yes | `github.com/owner/repo` or `gitlab.com/owner/repo` |
| `ref` | yes | Tag or commit SHA. Branch refs are rejected by the unpinned-source gate. |
| `subdir` | no | Subdirectory within the repo that contains the module (or multiple modules). If omitted, the repo root is used. |

The runner clones the source into `~/.cache/project-setup/` on first use. On
subsequent runs it uses the cached clone; pass `--refresh` to force a re-fetch.

Sources declared in `~/.config/project-setup/config.toml` act as personal
defaults; sources in `.project-setup/sources.toml` are committed alongside the
project and are authoritative for reproducing the setup on a fresh clone.

### Step 4: enable the module

During the project-setup interview, enabled modules are listed by id in
the `enabled` key of the answers file:

```json
{
  "enabled": ["core-identity", "dirs-scaffold", "my-module"],
  "my-module.greeting": "Hello from my org!"
}
```

The runner discovers the module from the declared source, validates its
manifest, runs its inputs, and executes its steps in topological order.

---

## Versioning

This repository uses release-please in manifest mode. Each module and the core
skill are independent release-please components. Component tags follow the
pattern `<component>-v<version>` (e.g. `lang-python-v1.2.0`,
`project-setup-v0.3.0`).

Conventional commit scopes drive which component bumps:

```
feat(lang-python): add support for PEP 723 inline deps
```

bumps only the `lang-python` component. A commit with no scope (or scope
`project-setup`) bumps the core skill. Use `docs:` or `chore:` prefixes for
changes that should not bump any component version.

For modules published in an external repo, apply the same release-please
manifest approach: add a `packages` entry per module in
`release-please-config.json` and an `extra-files` entry pointing at the
`module.toml` `$.module.version` field. See this repo's
`release-please-config.json` for a concrete example.

When you publish a new tag, update any `sources.toml` `ref` entries that pin
your module to re-pin to the new tag.

---

## Checklist before publishing

- [ ] Module id is lowercase kebab-case
- [ ] `module.toml` parses without errors (`uv run --with pytest pytest test_*.py`)
- [ ] `default_enabled` is **not** set (addon modules are always opt-in)
- [ ] `reconcile` is set deliberately (`false` = write-once, `true` = overwrite)
- [ ] All `sdk.idempotent_write` calls use relative paths within the project dir
- [ ] All consent gates (`allow_flag` / `skip_flag`) are documented in the module's README or description
- [ ] The published ref is a tag or SHA, not a branch
- [ ] Network calls (if any) are guarded so the module degrades gracefully offline
- [ ] `uv run --with pytest pytest -q` is green
