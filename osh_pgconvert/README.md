# osh-pgconvert

Convert a PostgreSQL dump to a different server major version.

```
osh db dump-convert [INPUT] [OUTPUT] [--to 16] [--image IMAGE]
                    [--container-db NAME] [--from-db NAME] [--filestore]
                    [--docker-test|--docker-import] [--dry-run]
                    [--allow-restore-errors]
```

The SQL is rewritten for the target PostgreSQL version by the
`pgdump-convert` package and repacked as an Odoo-format zip — e.g.
turning a PostgreSQL 18 dump into one a PostgreSQL 16 server (odoo.sh)
can restore. `--docker-test`/`--docker-import` optionally load the
converted SQL into a throwaway `postgres:<version>` container to prove
it restores.

The conversion engine is the
[`pgdump-convert`](https://github.com/OdooEssentials/pgdump-convert)
package — installed automatically as a dependency of `osh-pgconvert`.
If it's missing (e.g. an older install), the command says so and prints
the fix:

```bash
pipx inject osh "pgdump-convert @ git+https://github.com/OdooEssentials/pgdump-convert.git"
```

## Sources

- **File** — an Odoo-format zip backup (`dump.sql` + `filestore/` +
  `manifest.json`) or a plain `pg_dump -Fp` `.sql` file. `-` reads the
  dump from stdin. The output is always an Odoo-format zip:
  `dump.sql` stays plain SQL (the format Odoo's zip restore feeds to
  `psql`), `\restrict`/`\unrestrict` lines are stripped for older
  `psql` clients, and `manifest.json`'s `pg_version` is updated to the
  target version. Custom-format (`pg_dump -Fc`) files are rejected.
  `-` as OUTPUT writes the zip to stdout, so dumps can be piped:
  `cat dump.sql | osh db dump-convert - > backup-pg16.zip`.
- **Database** — `--from-db NAME`, or no arguments inside an osh
  project (exports the project's resolved database). `pg_dump` runs
  through the project's runtime; `--filestore` also bundles the
  project filestore when it is readable on the host (container
  runtimes keep it inside the container, so it is skipped with a
  warning). A manifest is synthesized with the installed module list
  from `ir_module_module`.

With `--from-db` the first positional argument is the output path.

Docker is optional: only needed for `--docker-test`/`--docker-import`.
Under `--docker-test` the container is always removed afterwards; if
the in-container restore reports SQL `ERROR` lines the conversion
fails — the dump may be incomplete; pass `--allow-restore-errors` to
accept them anyway.
