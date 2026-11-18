# osh-pgconvert

Convert a PostgreSQL dump to a different server major version.

```
osh db dump-convert [INPUT] [OUTPUT] [--to 16] [--image IMAGE]
                    [--container-db NAME] [--from-db NAME] [--filestore]
                    [--dry-run] [--allow-restore-errors]
```

The dump is restored into a throwaway `postgres:<version>` docker
container and re-dumped from that server, so the output is guaranteed to
be compatible with the target version — e.g. turning a PostgreSQL 18
dump into one a PostgreSQL 16 server (odoo.sh) can restore.

The conversion engine is the
[`pgdump-convert`](https://github.com/OdooEssentials/pgdump-convert)
package — install it into `osh`'s environment:

```bash
pipx inject osh "pgdump-convert @ git+https://github.com/OdooEssentials/pgdump-convert.git"
```

(For a venv or `uv tool` install of `osh`, use that environment's
installer instead — `pip install`/`uv tool install --with` with the same
spec.) If it's missing, the command says so and prints these
instructions.

## Sources

- **File** — an Odoo-format zip backup (`dump.sql` + `filestore/` +
  `manifest.json`) or a plain `pg_dump -Fp` `.sql` file. `-` reads the
  dump from stdin. The output is always an Odoo-format zip:
  `dump.sql` stays plain SQL (the format Odoo's zip restore feeds to
  `psql`), `\restrict`/`\unrestrict` lines are stripped for older
  `psql` clients, and `manifest.json`'s `pg_version` is updated to the
  target server version. Custom-format (`pg_dump -Fc`) files are
  rejected. `-` as OUTPUT writes the zip to stdout, so dumps can be
  piped: `cat dump.sql | osh db dump-convert - > backup-pg16.zip`.
- **Database** — `--from-db NAME`, or no arguments inside an osh
  project (exports the project's resolved database). `pg_dump` runs
  through the project's runtime; `--filestore` also bundles the
  project filestore when it is readable on the host (container
  runtimes keep it inside the container, so it is skipped with a
  warning). A manifest is synthesized with the installed module list
  from `ir_module_module`.

With `--from-db` the first positional argument is the output path.

Requires docker. The container is always removed afterwards. If the
in-container restore reports SQL `ERROR` lines the conversion fails —
the dump may be incomplete; pass `--allow-restore-errors` to re-dump
anyway.
