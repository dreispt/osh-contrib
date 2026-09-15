# osh_update

Update Odoo modules whose code changed since the last update.

`osh addon update` fingerprints every project module — hashing only code and
data files (`*.py`, `*.xml`, `*.csv`, `*.po(t)`, `*.yaml/.yml`, `*.sql` and the
manifest; `static/` assets are ignored) — and compares the result against the
fingerprints stored in the target database. Installed modules that changed are
then updated with `odoo -u`.

Fingerprints live in the database itself as the `ir.config_parameter` record
`osh.module_fingerprints` (visible under _Settings → Technical → System
Parameters_), so they follow the database across `osh db copy` and
`osh db restore`.

## Usage

```bash
osh addon update            # update installed modules that changed
osh addon update my_module  # force-update specific modules
osh addon update --all      # force-update all installed third-party modules
osh addon update -d mydb    # target a specific database
osh addon update --dry-run  # list the modules that would be updated + the odoo -u command
osh addon update --status   # report installed 3rd-party modules and pending updates
osh addon update --status --all  # same report, including upstream modules
osh addon update --status -1  # print module lists one per line
osh addon update --no-submodules  # skip modules inside nested git repos
```

Module lists are printed comma-separated (pasteable into `-u`); `-1` /
`--per-line` prints one module per line instead.

`osh addon update` runs on the project's active backend (`osh <backend>
activate` switches it); `--compose-file` is forwarded to `osh odoo`.

## Behaviour notes

- **First run:** no fingerprints stored yet — the command only records a
  baseline and performs no update. Use `osh addon update --all` if the database
  is not actually in sync.
- **Not installed:** modules not installed in the database are silently
  skipped (`osh addon update` never installs; use `osh odoo -i`).
- **Missing on disk:** a module that is installed in the database but no
  longer exists in the project triggers a warning.
- **Failure:** if the `odoo -u` run fails, fingerprints are not written, so
  the next `osh addon update` retries the same modules.
- **`--status`:** reports installed _third-party_ modules and the ones
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

- `osh` >= 0.8, which provides the core `addon` command group this plugin
  attaches to. On older cores the plugin loads but `osh addon update` never
  appears — check with `osh addon --help`.
- A `psql` able to reach the target database using the project's configured
  credentials (the same requirement `osh odoo` already has).
