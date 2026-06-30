# Changelog

## [0.5.4](https://github.com/srobroek/project-setup/compare/project-setup-v0.5.3...project-setup-v0.5.4) (2026-06-30)


### Bug Fixes

* make addon catalog fetch work + ship a default catalog ([8cd3a1b](https://github.com/srobroek/project-setup/commit/8cd3a1b6b5035694792866fd9a33f2dd0f43996d))
* make addon catalog fetch work and ship a default catalog ([235587b](https://github.com/srobroek/project-setup/commit/235587bef3d38226ba9c8b906185998b7cbd3ac4))

## [0.5.3](https://github.com/srobroek/project-setup/compare/project-setup-v0.5.2...project-setup-v0.5.3) (2026-06-30)


### Bug Fixes

* ship bundled lang-go cmd/&lt;binary&gt; layout fix in a project-setup release ([7abdaa9](https://github.com/srobroek/project-setup/commit/7abdaa994f2f023887ddc00b933efefacd613fcd))
* ship bundled lang-go go build fix in a project-setup release ([a4d2438](https://github.com/srobroek/project-setup/commit/a4d243876d12bb69c5b4990416a420991556c728))

## [0.5.2](https://github.com/srobroek/project-setup/compare/project-setup-v0.5.1...project-setup-v0.5.2) (2026-06-30)


### Bug Fixes

* fill AGENTS.md, language-aware justfile, optional initial git commit ([b884adc](https://github.com/srobroek/project-setup/commit/b884adcdd473f882d04fa27ee161f3c839bb638f))

## [0.5.1](https://github.com/srobroek/project-setup/compare/project-setup-v0.5.0...project-setup-v0.5.1) (2026-06-30)


### Bug Fixes

* --add-module works for git sources, gains --enable, preserves sources.toml ([ef8e51b](https://github.com/srobroek/project-setup/commit/ef8e51bac923bbe37141c004b08ccfdcb7cb48bd))
* **project-setup:** repair git --add-module, add --enable, lossless sources.toml round-trip ([d6249df](https://github.com/srobroek/project-setup/commit/d6249df6e9ead851b6a64b46668c4ac56680f568))

## [0.5.0](https://github.com/srobroek/project-setup/compare/project-setup-v0.4.1...project-setup-v0.5.0) (2026-06-30)


### Features

* add/install external modules (--add-module, --list-catalog) ([1f6a2b2](https://github.com/srobroek/project-setup/commit/1f6a2b21da64ee363d5b5cac7d94f50d5762b305))
* **project-setup:** add/install external modules (--add-module, --list-catalog) ([b1a9d6b](https://github.com/srobroek/project-setup/commit/b1a9d6b39103518ede8747f1e82a22bf94d7cd78))

## [0.4.1](https://github.com/srobroek/project-setup/compare/project-setup-v0.4.0...project-setup-v0.4.1) (2026-06-30)


### Bug Fixes

* document bundled module distribution and refresh the project-setup umbrella ([ca63df6](https://github.com/srobroek/project-setup/commit/ca63df61a8e498656b8225e7b900a12daeed91ce))
* **project-setup:** document bundled module distribution + refresh umbrella tree ([6d00c08](https://github.com/srobroek/project-setup/commit/6d00c08fa544def12501c7eba10108c3c59a5fcf))

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
