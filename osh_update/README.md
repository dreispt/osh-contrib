# osh_update

Update Odoo modules whose code changed since the last update.

`osh db update` fingerprints every project module — hashing only code and
data files (`*.py`, `*.xml`, `*.csv`, `*.po(t)`, `*.yaml/.yml`, `*.sql` and the
manifest; `static/` assets are ignored) — and compares the result against the
fingerprints stored in the target database. Installed modules that changed are
then updated with `odoo -u`.

Fingerprints live in the database itself as the `ir.config_parameter` record
`osh.module_fingerprints` (visible under _Settings → Technical → System
Parameters_), so they follow the database across `osh db copy` and
`osh backup restore`.

On `osh backup restore`, the plugin also runs a post-restore hook: when the
restored dump carries no fingerprint map, the local modules' fingerprints
are recorded right away so later `osh db update` runs diff from the
restore point. Dumps that do carry fingerprints keep them — they describe
the code the database was last updated against, so real diffs are still
detected.

## Usage

```bash
osh db update            # update installed modules that changed
osh db update my_module  # force-update specific modules
osh db update --all      # force-update all installed third-party modules
osh db update -d mydb    # target a specific database
osh db update --dry-run  # list the modules that would be updated + the odoo -u command
osh db update --status   # report tracked 3rd-party modules and pending updates
osh db update --status --all  # same report, including upstream modules
osh db update --status -1  # print module lists one per line
osh db update --no-submodules  # skip modules inside nested git repos
```

Module lists are printed comma-separated (pasteable into `-u`); `-1` /
`--per-line` prints one module per line instead.

The plugin also provides `osh db installed` — a listing of the modules
recorded in a database's `ir_module_module` table, with their installed
version and state (`installed`, `to upgrade`, `to remove`, ...):

```bash
osh db installed               # module, version, state
osh db installed -l            # long listing — include the manifest summary
osh db installed -d mydb       # target a specific database
```

`osh db update` runs on the project's active backend (`osh <backend>
activate` switches it); `--compose-file` is forwarded to `osh odoo`.

## Behaviour notes

- **First run:** no fingerprints stored yet — the command only records a
  baseline and performs no update. Use `osh db update --all` if the database
  is not actually in sync.
- **Restores:** a database restored with `osh backup restore` gets a baseline
  recorded automatically when the dump has none (see above); the
  `backup.restore` extension needs osh >= 1.9 — the plugin requires it anyway. The restore baseline always uses the default scope
  (nested repos included), since `osh backup restore` has no `--no-submodules`
  flag to forward.
- **Not installed:** modules not installed in the database are silently
  skipped (`osh db update` never installs; use `osh odoo -i`).
- **Missing on disk:** a module that is installed in the database but no
  longer exists in the project triggers a warning.
- **Failure:** if the `odoo -u` run fails, fingerprints are not written, so
  the next `osh db update` retries the same modules.
- **`--status`:** reports _tracked third-party_ modules and the ones
  whose fingerprints differ, without running `odoo -u`. Add `--all` to
  include upstream modules in the report. On first run it still records
  the fingerprint baseline — which always covers all installed modules —
  and `--dry-run` reports without writing it.
- **`--all`:** force-updates all installed _third-party_ modules — those
  outside the `odoo`, `enterprise` and `design-themes` source trees.
  To update everything including upstream code, `osh odoo -- -u base` is
  simpler and faster.
- **Scope:** all discovered modules are tracked by default, including those
  inside nested git repositories such as `odoo`/`enterprise` source
  checkouts or submodules — so pulling new Odoo code also triggers updates.
  Pass `--no-submodules` to restrict tracking to the project's own
  repository.

## Requirements

- `osh` >= 1.9 (lazy plugin discovery and handler subclassing through
  `osh.handlers`). The `db` commands are declared under
  `[tool.osh.group_commands.db]` and the post-restore hook via
  `extends = ["backup.restore"]` in `pyproject.toml`, so the module
  imports only when `osh db update`, `osh db installed` or
  `osh backup restore` actually runs.
- A `psql` able to reach the target database using the project's configured
  credentials (the same requirement `osh odoo` already has).
