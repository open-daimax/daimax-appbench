# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed
- Collect Web source-code ESLint, complexity and duplication metrics; expose missing lint prerequisites and reject empty/invalid ESLint reports instead of treating them as clean scans (#17).
- DevicePool now closes admission and wakes waiters safely, isolates slow teardown from state readers, rejects stale/duplicate leases, and cleans partial startup/failed clones without stopping reused devices.
- Aesthetics scoring no longer silently selects a provider/model or overrides environment values with config defaults. Incomplete configuration is explicitly skipped; local endpoints can omit authentication.

### Added
- QuickCheck for deployed Web URLs: dual-viewport evidence, ten quality submetrics, runtime/content checks and a local review UI.
- Real anonymized QuickCheck report examples and capability documentation in both READMEs.
- A reproducible standalone-core sync tool with source revision/file hashes and a drift regression check.

### Changed
- Keep `evalapp quickcheck` and `quickcheck-ui` through a thin framework adapter while maintaining one QuickCheck engine upstream.
- QuickCheck startup uses the bundled HTML by default; Node.js is needed only when rebuilding frontend source.
- Retired QuickCheck scoring branches and flat historical result layouts are no longer shipped; existing hierarchical snapshots/runs remain readable.

## [0.2.0] - 2026-08-24 (Initial Open Source Release)

### Added
- Open-sourced under Apache 2.0 license
- English README and documentation
- Detailed API reference documentation (`docs/API.md`)
- Quick Start guide (`docs/QuickStart.md`)
- Architecture documentation (`docs/Architecture.md`)
- GitHub Actions CI pipeline for automated testing
- Contributing guidelines (`CONTRIBUTING.md`)
- Security policy (`SECURITY.md`)
- NOTICE file with third-party attributions
- Sample configurations and example reports (`samples/`)
- GitHub Issue and PR templates
- Dependabot configuration for automated dependency updates

### Changed
- Decoupled default generator configuration (no longer hardcoded)
- Translated core API docstrings to English
- Restructured documentation into dedicated `docs/` directory
- README simplified with links to detailed documentation

### Fixed
- Removed internal brand references from public-facing code and documentation
