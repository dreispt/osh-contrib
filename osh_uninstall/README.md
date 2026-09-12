# osh_uninstall

Uninstall Odoo modules from a database.

`osh uninstall` takes a comma-separated list of module technical names —
the same syntax as Odoo's `-u`/`--update` option — and removes them from
the target database. Modules that depend on them are uninstalled too:
the dependency cascade is computed by the ORM itself, via
`ir.module.module.button_immediate_uninstall()` executed inside
`osh odoo shell`.

## Usage

```bash
osh uninstall my_module             # uninstall, with confirmation
osh uninstall mod_a,mod_b           # comma-separated module list
osh uninstall mod_a,mod_b -d mydb   # target a specific database
osh uninstall my_module --yes       # skip the confirmation prompt
osh uninstall my_module --dry-run   # show the removal set, don't run
```

The execution target — including the Docker Compose file — comes from the
project's configured run target (`.osh`), so Docker Compose projects work
transparently.

## Behaviour notes

- **Validation:** before Odoo boots, every named module must exist in the
  database with state `installed` or `to upgrade`. Anything else —
  unknown, `uninstalled`, `to install` or `to remove` — fails fast with a
  clear error. To flush a module already pending removal, run
  `osh odoo -u base`.
- **Dependents:** the confirmation prompt lists every installed module
  that will also be removed because it (transitively) depends on the
  named ones.
- **Confirmation:** the command asks before removing anything; `--yes`
  skips the prompt for scripts and `--dry-run` shows the plan plus the
  exact `odoo shell` command without executing it.
- **Verification:** after the run the module states are re-checked, so a
  failure that doesn't produce a non-zero exit code (e.g. a tty-backed
  shell swallowing an exception) still reports an error instead of a
  false success.

## Requirements

A `psql` able to reach the target database using the project's configured
credentials (the same requirement `osh odoo` already has).
