# project-setup

Agent-driven project scaffolding runner with git-distributed add-on modules.

`project-setup` is a Claude Code / APM skill that scaffolds new repositories
through an answer-driven pipeline. The agent asks a short set of questions,
resolves a frozen execution plan, then runs a sequence of deterministic Python
steps — one per enabled module. Every decision is recorded in `.project-setup/`
and can be reproduced byte-for-byte later.

## Install

### Via APM (recommended)

```
apm install srobroek/project-setup
```

### As a Claude Code native plugin

```
/plugin install srobroek/project-setup
```

After install the `/project-setup` skill is available in any Claude Code session.

## Add-on modules

The skill ships 6 core modules bundled in `skills/project-setup/modules/`
(core-identity, dirs-scaffold, gitignore-generate, license-write, agents-md,
git-init). The remaining 18 addon modules live in `catalog/modules/` — they are
independently versioned, tagged (`<name>-v<version>`), and fetched on demand via
the addon catalog. See `skills/project-setup/addons/catalog.json` for the
first-party catalog.

For authoring guidance — writing new modules, custom steps, agent-steered
patterns — see [AUTHORING.md](skills/project-setup/examples/AUTHORING.md).

## Authoring modules

To write and publish your own module:

1. Scaffold a starter with `uv run .../runner/cli.py --new-module <id>`
2. Edit `module.toml`, `module.py`, and the test stub
3. Commit to a git repo and tag a release
4. Reference it from `.project-setup/sources.toml` with a pinned `ref`

See **[docs/publishing-modules.md](docs/publishing-modules.md)** for the
complete guide: `module.toml` schema, step-handler contract, SDK reference,
testing, and the `[[source]]` declaration format.

## Release model

This repo uses release-please in manifest mode. Each module and the core skill
are independent components:

- Module releases tag as `<name>-v<version>` (e.g. `lang-python-v1.2.0`)
- Core skill releases tag as `project-setup-v<version>`
- Conventional commit scopes drive which component bumps (e.g.
  `feat(lang-python): ...` bumps only the `lang-python` component)

The bundled `skills/project-setup/addons/catalog.json` is rebuilt and published
to gh-pages on every release via the `catalog-publish` workflow.

## License

Apache-2.0

<!-- addon modules are fetched from catalog/modules/ (thin-core, 2026-07) -->
