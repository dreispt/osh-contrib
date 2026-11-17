# Changelog

All notable changes to `osh-contrib` are documented in this file. The
`Unreleased` section collects release notes for the next tag; at release
time its entries move under a `## vX.Y.Z — YYYY-MM-DD` heading — the tag
mirrors the `osh` version it is tested against (see
[DEVELOP.md](DEVELOP.md#releasing)).

## Unreleased

## v2.0.1 — 2026-11-17

First tagged release, matched to `osh` 2.0.1. Six plugins:

### Added

- `osh db stats` shows database size and table statistics, and
  `osh db vacuum` vacuums and analyzes tables.
- `osh db sanitize` scrubs personal data and trims low-value rows, and
  `osh db restore --anonymize --trim` runs the same steps after a
  restore.
- `osh odoo --open` opens the Odoo URL in your browser once it's ready.
- `osh collect-migrations` gathers module migration scripts across OCA
  version branches.
- `osh apps install`, `update`, `list`, `fingerprint` and `uninstall`
  manage modules — install new ones, update the ones whose code
  changed, and remove modules with their dependents.

## v2.0.0 — 2026-11-14

Matched to `osh` 2.0.0. Same plugins as v2.0.1 except `osh_sanitize`,
which requires `osh` 2.0.0's layered SQL scripts and arrived with
v2.0.1:

### Added

- `osh db stats` shows database size and table statistics, and
  `osh db vacuum` vacuums and analyzes tables.
- `osh odoo --open` opens the Odoo URL in your browser once it's ready.
- `osh collect-migrations` gathers module migration scripts across OCA
  version branches.
- `osh apps install`, `update`, `list`, `fingerprint` and `uninstall`
  manage modules — install new ones, update the ones whose code
  changed, and remove modules with their dependents.
