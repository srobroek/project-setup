## Summary

<!-- 1-3 bullet points describing what this PR does and why. -->

- 

## Type of change

- [ ] `fix` — bug fix
- [ ] `feat` — new capability or module
- [ ] `docs` — documentation only (guide, README, AUTHORING.md, schema reference)
- [ ] `module` — new or updated bundled module (`skills/project-setup/modules/<id>/`)
- [ ] `chore` — maintenance (CI, deps, config; no functional change)
- [ ] `refactor` — internal restructuring; no observable behavior change

## Checklist

- [ ] Tests added or updated for any logic change; `uv run --with pytest pytest` is green
- [ ] Conventional-commit prefix is scoped to the right release-please component
  (e.g. `feat(lang-python):` bumps `lang-python`; `feat(project-setup):` or no
  scope bumps the core skill; `docs:` / `chore:` bump nothing — see below)
- [ ] `SKILL.md` updated if the agent contract changed (new flags, new gate
  behavior, new module added to the bundled set)
- [ ] `docs/publishing-modules.md` or `examples/AUTHORING.md` updated if the
  module schema or SDK API changed
- [ ] No new third-party runtime dependencies added to the runner core
  (`runner/` stays stdlib-only; use the `# dependencies = []` uv script header
  in `module.py` for module-level deps)
- [ ] `default_enabled` is NOT set on any new addon module (FR-035)

---

### Conventional commits and release-please components

This repo uses release-please in manifest mode. Each module and the core skill
are independent components with their own version. The commit scope drives
which component's version bumps:

| scope | component bumped | example |
|---|---|---|
| `lang-python` | `lang-python` module | `feat(lang-python): add PEP 723 support` |
| `project-setup` or no scope | core skill | `fix: validate-closed gate now reports all errors` |
| `docs` or `chore` | nothing | `docs: extend publishing guide` |

A PR that touches multiple components needs multiple conventional commits (one
per scope) or a single commit with a footer listing all affected scopes. Keep
each commit focused so the release PR picks up the right version bumps.
