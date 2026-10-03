# osh_dbstats

Diagnose an Odoo database from the command line: `osh db stats` renders a
dashboard of the database's size, bloat, index usage and live activity,
and `osh db vacuum` runs `VACUUM ANALYZE` on the findings.

## Commands

### `osh db stats`

```
osh db stats [-d DB] [--top N] [--no-filestore]
```

Read-only dashboard built from PostgreSQL's statistics catalogs:

```
DATABASE myproject-main ──────────────────────────────────────────────
4.2 GB + 12 GB filestore · 312 tables · ~18.4M rows · stats reset 32d ago
PostgreSQL 15.4 · Odoo 17.0

LARGEST TABLES ───────────────────────────────────────────────────────
mail_message       1.2 GB  ████████████████  890 MB data · 310 MB idx · ~4.1M rows
ir_attachment      800 MB  ███████████░░░░░  700 MB data · 100 MB idx · ~950k rows

TABLE HEALTH ─────────────────────────────────────────────────────────
mail_message  22% dead (~900k)     · vacuumed 12d ago · analyzed 3d ago

INDEXES ──────────────────────────────────────────────────────────────
2.1 GB across 512 indexes
mail_message_pkey              310 MB  mail_message · 12.4k scans
mail_message_message_id_idx    180 MB  mail_message · 0 scans

ACTIVITY ─────────────────────────────────────────────────────────────
connections: 14/100 (idle 9 · active 3 · idle in transaction 2)
autovacuum workers: 2 running
long-running queries:
  pid 1234 · 45s · UPDATE mail_message SET ...

QUERY STATS ──────────────────────────────────────────────────────────
12.4k calls ·    842s total ·   68ms avg · UPDATE mail_message SET ...
(when pg_stat_statements is enabled; otherwise a pointer to
'osh db stats --help', which documents how to enable it)

⚠ 1 bloated table(s) — see 'osh db vacuum'
```

### `osh db vacuum`

```
osh db vacuum [-d DB] [--table NAME]... [--no-analyze] [--dry-run]
```

Runs `VACUUM (VERBOSE, ANALYZE)` — the safe, non-destructive vacuum that
reclaims dead-tuple space for reuse and refreshes planner statistics. It
does **not** return space to the operating system.

## Requirements

- `psql` reachable through the project's active backend — Docker-backed
  projects run it inside the container automatically.
- `pg_stat_statements` (optional) for the top-queries section.

## Roadmap

Ideas for future commands in this plugin:

- `osh db purge` — age/size-based record pruning for the watchlist tables
  (`ir.logging`, `mail.mail`, done `queue.job`, `auditlog.log`, ...),
  with preview and confirmation.
- Space release back to the OS: `VACUUM FULL` / `pg_repack` per table,
  with lock warnings.
- Filestore hygiene: report and remove files with no matching
  `ir_attachment` row.
- `osh db stats --watch` — refresh the dashboard periodically.
