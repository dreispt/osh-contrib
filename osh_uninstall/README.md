# osh_uninstall

Uninstall Odoo modules from a database.

`osh apps uninstall` takes a comma-separated list of module technical names —
the same syntax as Odoo's `-u`/`--update` option — and removes them from
the target database. Modules that depend on them are uninstalled too:
the dependency cascade is computed by the ORM itself, via
`ir.module.module.button_immediate_uninstall()` executed inside
`osh odoo shell`.

## Usage

```bash
osh apps uninstall my_module             # uninstall, with confirmation
osh apps uninstall mod_a,mod_b           # comma-separated module list
osh apps uninstall mod_a,mod_b -d mydb   # target a specific database
osh apps uninstall my_module --yes       # skip the confirmation prompt
osh apps uninstall my_module --dry-run   # show the removal set, don't run
```

The execution target — including the Docker Compose file — comes from the
project's configured run target (`.osh`), so Docker Compose projects work
transparently.

The former `osh db uninstall` spelling still works as a hidden deprecated
alias — it warns on use and will be removed in a later release.

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

- `osh` >= 1.9 (lazy plugin discovery and handler subclassing through
  `osh.handlers`). The command is declared under
  `[tool.osh.group_commands.apps]` and the deprecated spelling under
  `[tool.osh.group_commands.db]` in `pyproject.toml`, so the module
  imports only when `osh apps uninstall` (or `osh db uninstall`) actually
  runs. With `osh` >= 1.11 the deprecated spelling is also hidden from
  `osh db --help`.
- A `psql` able to reach the target database using the project's configured
  credentials (the same requirement `osh odoo` already has).
