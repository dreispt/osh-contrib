# osh-pgconvert

Convert a PostgreSQL dump to a different server major version.

```
osh db dump-convert backup.zip [output.zip] [--to 16] [--image IMAGE] [--db NAME] [--dry-run]
```

The dump is restored into a throwaway ``postgres:<version>`` docker
container and re-dumped from that server, so the output is guaranteed to
be compatible with the target version — e.g. turning a PostgreSQL 18
dump into one a PostgreSQL 16 server (odoo.sh) can restore.

Works on Odoo-format zip backups (``dump.sql`` + ``filestore/`` +
``manifest.json``): the filestore and manifest are preserved, and
``manifest.json``'s ``pg_version`` is updated to the target server
version. ``\\restrict``/``\\unrestrict`` lines are stripped so older
``psql`` clients can import the dump.

Requires docker. The container is always removed afterwards.
