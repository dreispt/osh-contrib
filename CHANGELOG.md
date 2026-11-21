# Changelog

All notable changes to `osh-contrib` are documented in this file. The
`Unreleased` section collects release notes for the next tag; at release
time its entries move under a `## vX.Y.Z — YYYY-MM-DD` heading — the tag
mirrors the `osh` version it is tested against (see
[DEVELOP.md](DEVELOP.md#releasing)).

## Unreleased

### Changed

- Use `osh db stats DATABASE` and `osh db vacuum DATABASE` to select a
  database. The old `-d` and `--db` options still work with a deprecation
  warning and are scheduled for removal in osh 3.0.
- Use `osh db sanitize --db DATABASE` to select a database. The old `-d`
  and `--database` options still work with a deprecation warning and are
  scheduled for removal in osh 3.0.
- Both restore spellings run the sanitization and module fingerprint
  hooks. A failure in explicitly requested sanitization exits nonzero
  and keeps the restored database.
- Partial masking keeps recognizable hints in partner names, email,
  phone, address, and bank details for matching against production.
  Stored payment tokens retain only display hints; known live provider
  references are replaced and tokens are archived where supported.
- Sanitization preserves internal user logins and account display names
  so developers can keep using their existing credentials; portal user
  logins are masked like emails. Sanitized copies may still contain
  identifying information.
- The bundle and the `osh_dbstats`, `osh_sanitize`, and `osh_update`
  plugins now require osh 2.1.0 or later.

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
