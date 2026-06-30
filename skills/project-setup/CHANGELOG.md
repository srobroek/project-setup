# Changelog

## [0.4.0](https://github.com/srobroek/project-setup/compare/project-setup-v0.3.3...project-setup-v0.4.0) (2026-06-30)


### Features

* **project-setup:** --check-answers preflight + write-if-absent treats empty files as absent ([1706a92](https://github.com/srobroek/project-setup/commit/1706a92fdd066ad95414149ba3349981bba08c3f))


### Bug Fixes

* deterministic scaffolding — correct package identity, installable manifests, valid CI, enforced interview ([fed956f](https://github.com/srobroek/project-setup/commit/fed956f22f978804b5f4ffece839c85e4e8b9324))

## [0.3.3](https://github.com/srobroek/project-setup/compare/project-setup-v0.3.2...project-setup-v0.3.3) (2026-06-30)


### Bug Fixes

* pre-resolved deps now materialize, inert gate flags warn, version drift guarded ([710115b](https://github.com/srobroek/project-setup/commit/710115b0c9c08cce0b906b9db039c241497040f1))
* **project-setup:** inert gate flags warn instead of hard-erroring; sync apm.yml version; add drift guard ([cc776df](https://github.com/srobroek/project-setup/commit/cc776df90eb1d1ba50a5ba72a394fbc05c5ac1a6))

## [0.3.3](https://github.com/srobroek/project-setup/compare/project-setup-v0.3.2...project-setup-v0.3.3) (2026-06-30)


### Bug Fixes

* pre-resolved deps now materialize, inert gate flags warn, version drift guarded ([710115b](https://github.com/srobroek/project-setup/commit/710115b0c9c08cce0b906b9db039c241497040f1))
* **project-setup:** inert gate flags warn instead of hard-erroring; sync apm.yml version; add drift guard ([cc776df](https://github.com/srobroek/project-setup/commit/cc776df90eb1d1ba50a5ba72a394fbc05c5ac1a6))

## [0.3.2](https://github.com/srobroek/project-setup/compare/project-setup-v0.3.1...project-setup-v0.3.2) (2026-06-29)


### Bug Fixes

* answers-file consent flags were ignored, causing all gates to safe-skip ([010aed7](https://github.com/srobroek/project-setup/commit/010aed755ed5dd0a0ae00479204c5d32d522da56))
* **project-setup:** wire answers-file allow/skip flags into the pipeline gate resolver ([22d874c](https://github.com/srobroek/project-setup/commit/22d874cb54cbe04b3eeec1539175bf1965d66ef2))

## [0.3.1](https://github.com/srobroek/project-setup/compare/project-setup-v0.3.0...project-setup-v0.3.1) (2026-06-29)


### Bug Fixes

* project-local frozen plan, answers-file consent flags, PEP 508 pin rendering ([6533724](https://github.com/srobroek/project-setup/commit/6533724880c29cc46434c78add17c6a54df26d14))
* **project-setup:** project-local frozen plan path with unconditional wipe + generic consent flags ([10e15a0](https://github.com/srobroek/project-setup/commit/10e15a04fa5c2de2058396a3e6fd4feb3a6343be))

## [0.3.0](https://github.com/srobroek/project-setup/compare/project-setup-v0.2.0...project-setup-v0.3.0) (2026-06-29)


### Features

* initial standalone project-setup — agent-driven scaffolding runner + git-distributed add-on modules ([37a280a](https://github.com/srobroek/project-setup/commit/37a280a0174d5b85305b003f659cd9931d5e8821))


### Bug Fixes

* catalog points at real repo (overridable); fix git-missing test portability ([d2f70e9](https://github.com/srobroek/project-setup/commit/d2f70e9a472a248234019e79535a23012e65aeea))
* quote SKILL.md description so YAML frontmatter parses ([#26](https://github.com/srobroek/project-setup/issues/26)) ([5736e2b](https://github.com/srobroek/project-setup/commit/5736e2bd671e1f7af118f17e83230b733abfb563))
