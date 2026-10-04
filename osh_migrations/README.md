# osh_migrations

Collect Odoo module `migrations/` scripts across OCA version branches.

## The problem

Each OCA repository branch only keeps the migration scripts for its own
version — `17.0` has the scripts migrating to 17, `18.0` the ones
migrating to 18, and so on. When upgrading a database across several
versions (e.g. 17.0 → 19.0), the scripts for the versions in between are
missing from the checkout, and `odoo -u all` silently skips them.

## Usage

`osh collect-migrations` scans a directory for git repositories — OCA
clones or submodules — and checks out each `N.N` version branch in a
temporary `git worktree` (the clones' own checkouts are never touched).
Every `<module>/migrations/` directory found is copied into a
`migration/` tree mirroring the scanned layout:

```bash
osh collect-migrations external/ --from 18.0 --to 19.0
```

produces e.g.

```
migration/
└── OCA/
    └── server-tools/
        └── base_changes/
            └── migrations/
                ├── 18.0.1.0.0/
                └── 19.0.1.0.0/
```

Merge the collected tree over the scanned directory before running the
upgrade, so every intermediate script is present:

```bash
cp -r migration/* external/
osh odoo -- -u all --stop-after-init
```

## Options

- `TARGET` — directory to scan for repositories (default: `.`). `TARGET`
  itself is scanned too when it is a repository.
- `-o/--output DIR` — output root (default: `./migration`). Branches
  merge into each module's single `migrations/` directory.
- `--remote REMOTE` — the remote whose version branches are collected
  (default: `origin`). Local `N.N` branches are used only when the remote
  doesn't have them.
- `--from VERSION` / `--to VERSION` — inclusive bounds on the `N.N`
  branches collected (e.g. `--from 18.0 --to 19.0`). Without them every
  version branch found is collected.
- `--dry-run` — report what would be collected without copying.

## Requirements

- `osh` >= 1.7
- `git`
