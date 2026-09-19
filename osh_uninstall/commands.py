"""``osh addon uninstall`` handler.

Removes installed modules — and their installed dependents — from a
database by piping a ``button_immediate_uninstall`` call into
``osh odoo shell``. A dependency preview is shown for confirmation, and
the module states are re-checked afterwards so a silently swallowed
failure never reports success.
"""

import time

import click
from osh import echo
from osh.cli_utils import handler_command
from osh.common import find_project_root
from osh.db import resolve_db_name_for_run, sanitize_db_name
from osh.handlers import CommandHandler

from . import core, store


class AddonUninstall(CommandHandler):
    """Uninstall Odoo modules from a database.

    MODULES is a comma-separated list of module technical names, like the
    ``-u``/``--update`` option. Installed modules depending on them are
    uninstalled too — Odoo handles the dependency cascade.

    Examples:

    \b
      osh addon uninstall my_module
      osh addon uninstall mod_a,mod_b
      osh addon uninstall my_module -d otherdb --yes
      osh addon uninstall my_module --dry-run
    """

    _cli_name = "addon.uninstall"

    modules = ""
    db_name = None
    yes = False
    dry_run = False

    @classmethod
    def get_options(cls):
        return [
            *super().get_options(),
            click.Argument(["modules"]),
            click.Option(
                ["-d", "--db", "db_name"],
                help="Database to uninstall from "
                "(default: the resolved branch database).",
            ),
            click.Option(
                ["--yes"],
                is_flag=True,
                help="Do not ask for confirmation before uninstalling.",
            ),
            click.Option(
                ["--dry-run"],
                is_flag=True,
                help="Show the removal set and the odoo shell command "
                "without executing it.",
            ),
        ]

    def run(self):
        names = sorted({n.strip() for n in self.modules.split(",") if n.strip()})
        if not names:
            raise click.ClickException("No module names given.")

        base = find_project_root(required=True)
        db_name = (
            sanitize_db_name(self.db_name)
            if self.db_name
            else resolve_db_name_for_run(base, ctx=self.ctx)
        )

        states = store.get_module_states(base, db_name, ctx=self.ctx)
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

        removal = store.get_removal_set(base, db_name, names, ctx=self.ctx)
        dependents = [n for n in removal if n not in names]
        echo.info("Will uninstall: " + ", ".join(names))
        if dependents:
            echo.warning(
                "Dependents will also be uninstalled: " + ", ".join(dependents)
            )

        if self.dry_run:
            echo.info("Script piped to 'osh odoo shell':")
            click.echo(core.uninstall_script(names))
            core.run_uninstall(names, db_name, dry_run=True)
            return

        if not self.yes and not click.confirm(
            f"Uninstall {len(removal)} module(s) from '{db_name}'?",
            default=False,
            err=True,
        ):
            self.ctx.exit(0)

        start = time.monotonic()
        returncode = core.run_uninstall(names, db_name)
        elapsed = time.monotonic() - start
        if returncode != 0:
            raise click.ClickException(
                f"odoo shell uninstall failed (exit {returncode})."
            )

        # The shell's exit code cannot be trusted on every backend (a
        # tty-backed REPL swallows exceptions), so re-check the states.
        after = store.get_module_states(base, db_name, ctx=self.ctx) or {}
        remaining = [n for n in names if after.get(n) != "uninstalled"]
        if remaining:
            raise click.ClickException(
                "Modules were not uninstalled: " + ", ".join(remaining)
            )
        echo.success(
            f"Uninstalled {len(removal)} module(s) from '{db_name}' "
            f"in {elapsed:.1f} seconds."
        )


#: Standalone ``uninstall`` command — used by tests; the CLI wires the same
#: handler through the ``[group_commands.addon]`` declaration.
uninstall = handler_command("uninstall", AddonUninstall)
