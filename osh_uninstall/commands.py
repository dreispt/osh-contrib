"""``osh uninstall`` command implementation.

Removes installed modules — and their installed dependents — from a
database by piping a ``button_immediate_uninstall`` call into
``osh odoo shell``. A dependency preview is shown for confirmation, and
the module states are re-checked afterwards so a silently swallowed
failure never reports success.
"""

import time

import click
from osh import echo
from osh.common import find_project_root
from osh.db import resolve_db_name_for_run, sanitize_db_name

from . import core, store


@click.command(name="uninstall")
@click.argument("modules")
@click.option(
    "-d",
    "--db",
    "db_name",
    help="Database to uninstall from (default: the resolved branch database).",
)
@click.option(
    "--yes",
    is_flag=True,
    help="Do not ask for confirmation before uninstalling.",
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="Show the removal set and the odoo shell command without executing it.",
)
@click.pass_context
def uninstall(ctx, modules, db_name, yes, dry_run):  # noqa: D401
    """Uninstall Odoo modules from a database.

    MODULES is a comma-separated list of module technical names, like the
    ``-u``/``--update`` option. Installed modules depending on them are
    uninstalled too — Odoo handles the dependency cascade.

    Examples:

    \b
      osh uninstall my_module
      osh uninstall mod_a,mod_b
      osh uninstall my_module -d otherdb --yes
      osh uninstall my_module --dry-run
    """
    names = sorted({n.strip() for n in modules.split(",") if n.strip()})
    if not names:
        raise click.ClickException("No module names given.")

    base = find_project_root(required=True)
    db_name = sanitize_db_name(db_name) if db_name else resolve_db_name_for_run(base)

    states = store.get_module_states(base, db_name)
    if states is None:
        raise click.ClickException(
            f"Database '{db_name}' is not initialized. Install modules "
            f"first (e.g. 'osh odoo -i base -d {db_name}')."
        )

    bad = [n for n in names if states.get(n) not in store.REMOVABLE_STATES]
    if bad:
        details = ", ".join(f"{n} ({states.get(n) or 'unknown'})" for n in bad)
        raise click.ClickException(
            f"Cannot uninstall: {details}. Only installed modules can "
            "be uninstalled."
        )

    removal = store.get_removal_set(base, db_name, names)
    dependents = [n for n in removal if n not in names]
    echo.info("Will uninstall: " + ", ".join(names))
    if dependents:
        echo.warning("Dependents will also be uninstalled: " + ", ".join(dependents))

    if dry_run:
        echo.info("Script piped to 'osh odoo shell':")
        click.echo(core.uninstall_script(names))
        core.run_uninstall(names, db_name, dry_run=True)
        return

    if not yes and not click.confirm(
        f"Uninstall {len(removal)} module(s) from '{db_name}'?",
        default=False,
        err=True,
    ):
        ctx.exit(0)

    start = time.monotonic()
    returncode = core.run_uninstall(names, db_name)
    elapsed = time.monotonic() - start
    if returncode != 0:
        raise click.ClickException(f"odoo shell uninstall failed (exit {returncode}).")

    # The shell's exit code cannot be trusted on every backend (a
    # tty-backed REPL swallows exceptions), so re-check the states.
    after = store.get_module_states(base, db_name) or {}
    remaining = [n for n in names if after.get(n) != "uninstalled"]
    if remaining:
        raise click.ClickException(
            "Modules were not uninstalled: " + ", ".join(remaining)
        )
    echo.success(
        f"Uninstalled {len(removal)} module(s) from '{db_name}' "
        f"in {elapsed:.1f} seconds."
    )
