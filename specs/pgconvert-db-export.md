# dump-convert: project-DB export, filestore, plain-SQL input — spec

**Status:** in progress
**Date:** 2026-02-14
**Scope:** `osh_pgconvert` plugin in osh-contrib; consumes `osh.db` helpers
(`run_in_runtime`, `psql_rows`, `db_exists`, `filestore_path`,
`resolve_db_name`, `find_project_root`).

## Context

`osh db dump-convert` converts an Odoo zip backup (PG18 → PG16 etc.).
The SQL version conversion is delegated to the standalone
`pgdump-convert` package; this plugin owns the Odoo layer — zip
extract/repack, `manifest.json`, `filestore/`, and dumping project
databases through the osh runtime. Gaps addressed:

- Users must first produce a backup zip; exporting straight from the
  project's database is the common case ("my dev DB is on PG18, odoo.sh
  runs PG16").
- Plain `.sql` dumps (e.g. `pg_dump -Fp`, `osh db backup` SQL output)
  are rejected even though they feed the same pipeline.
- The converted zip drops `filestore/` unless the input zip carried it;
  a DB export should be able to bundle the project filestore.

## Spec

Command surface:

```
osh db dump-convert [INPUT] [OUTPUT] [--to 16] [--image IMAGE]
                    [--container-db NAME] [--from-db NAME] [--filestore]
                    [--docker-test|--docker-import] [--dry-run]
                    [--allow-restore-errors]
```

- `INPUT` becomes optional. Exactly one source is used:
  1. `INPUT` file (existing behavior, extended — see below).
  2. `--from-db NAME` — dump database `NAME` from the project's
     PostgreSQL environment.
  3. Neither `INPUT` nor `--from-db`, inside an osh project — dump the
     project's resolved database (`resolve_db_name`).
- Positionals under `--from-db`: there is no input, so the first
  positional is the OUTPUT path; a second positional is a usage error.
  (`INPUT` therefore cannot keep `exists=True` — an output path usually
  does not exist yet; file existence is validated in `run()` instead.)
- No `INPUT`, no `--from-db`, outside a project → error telling the
  user to pass a file or run inside a project.
- `--from-db` and the implicit project-DB mode require an osh project
  (the runtime/`PG*` config comes from `.osh`). Outside-project DB
  export is a possible follow-up once osh's no-project `db` support
  lands.
- `--filestore` with file input → usage error (it only applies to a
  database source).

Input file handling:

- Zip input (`zipfile.is_zipfile`): unchanged — extract `dump.sql`,
  `manifest.json`, `filestore/`.
- Non-zip input: treated as a plain SQL dump. It becomes `dump.sql`
  verbatim; no manifest/filestore. If the file starts with the custom
  format magic `PGDMP`, fail with a clear error — checked before
  `--dry-run` returns so the error surfaces in both modes.

DB export (`convert_db`):

- `pg_dump -Fp --no-owner -d <db>` run via `osh.db.run_in_runtime`,
  streamed to `work/dump.sql` — same format Odoo's `dump.sql` uses.
- Missing database → `db_exists` check, clean `ClickException`.
- `--filestore`: copy `filestore_path(base, db)` into `work/filestore/`
  when it is a host-readable directory; otherwise warn and continue
  without it (Docker/Kiri runtimes keep the filestore inside the
  container — document the limitation).
- `manifest.json` is synthesized:
  `{"odoo_dump": "1", "db_name": <src>, "modules": {name: latest_version
for installed modules}}` — modules queried via `psql_rows` on
  `ir_module_module`; if the query fails (non-Odoo DB) `modules` stays
  `{}`. `version`/`major_version` are NOT invented.
- The synthesized manifest then flows through `_write_zip`, which
  stamps `pg_version` with `--to` (the filter engine does not verify
  against a server; `--docker-test` proves the dump loads but does not
  change the stamped version).

Output naming:

- File input, no `OUTPUT`: `<input-stem>-pg<to>.zip` (unchanged).
- DB mode, no `OUTPUT`: `<db>-pg<to>.zip` in the current directory.

`--db` is renamed `--container-db` (it names the scratch DB inside the
throwaway container, not the source) — clearer next to `--from-db`.

Compatibility notes:

- `dump.sql` stays plain SQL everywhere: `pg_dump -Fp` in, `psql -f`
  restore, `pg_dump -Fp` out — the format Odoo's zip restore requires.
- `\restrict`/`\unrestrict` stripping already applies on both input
  paths.
- PG18 → PG16 conversion path: PG18 `dump.sql` (or live DB) →
  `pgdump_convert` filter rules → Odoo.zip. `--docker-test` /
  `--docker-import` optionally restore the converted SQL into a
  throwaway `postgres:<to>` container (verify / leave running).

## Alternatives considered

- **`pg_dump -Fc` custom format as intermediate** — rejected:
  `pg_restore` refuses dumps written by newer `pg_dump` majors
  ("unsupported version in file header"), which is exactly the
  downgrade case this command exists for. Plain SQL is the only format
  both directions tolerate.
- **Bundle filestore via `docker cp` for container runtimes** — deferred:
  needs per-runtime plumbing; warn-and-skip ships first.
- **Require `--from-db` explicitly (no implicit project DB)** — rejected:
  "convert my project DB" is the dominant use case; implicit keeps the
  command to one word.

## Tasks

- [x] Spec
- [x] Failing tests: plain-SQL input, `PGDMP` rejection, `--from-db`,
      implicit project DB, `--from-db`+`INPUT` conflict, outside-project
      errors, `--filestore` inclusion/skip, manifest `modules`,
      `--container-db` rename, dry-run for DB mode
- [x] `core.convert` accepts zip/SQL/stdin; `core.convert_db` added
- [x] `commands.py` new options and source resolution
- [x] README + this spec updated; tests green; pre-commit clean
- [x] Delegate SQL conversion to `pgdump-convert` package; plugin owns
      zip/manifest/filestore; `--docker-test`/`--docker-import` pass-through
