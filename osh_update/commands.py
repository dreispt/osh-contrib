"""``osh apps`` module lifecycle commands.

``osh apps update`` detects which project modules changed since the last
update — using fingerprints stored in the target database's
``ir.config_parameter`` — and runs ``odoo -u`` on the installed ones. On
the first run it only records the current fingerprints as a baseline
without updating anything.

``osh apps install`` installs modules with ``odoo -i``, and ``osh apps
list`` lists the modules recorded in a database with their installed
version and state.

The former ``osh db update``/``osh db installed`` spellings remain
available as hidden deprecated aliases that warn on use.
"""

import click
from osh import echo
from osh.cli_utils import handler_command
from osh.common import find_project_root
from osh.db import db_exists, resolve_db_name_for_run, sanitize_db_name
from osh.handlers import CommandHandler

from . import core, store


class AppsUpdate(CommandHandler):
    """Update project modules whose code changed since the last update.

    Each project module is fingerprinted (code and data files; ``static/``
    is ignored) and compared against the fingerprints stored in the target
    database. Installed modules that changed are updated with ``odoo -u``.

    On the first run only a fingerprint baseline is recorded — no update is
    performed. Pass module names or ``--all`` to force an update.

    Examples:

    \b
      osh apps update
      osh apps update my_module other_module
      osh apps update --all
      osh apps update --status
      osh apps update -d otherdb --dry-run
    """

    _cli_name = "apps.update"

    modules = ()
    db_name = None
    update_all = False
    dry_run = False
    compose_file = None
    skip_nested = False
    status = False
    per_line = False

    @click.argument("modules", nargs=-1)
    @click.option(
        "-d",
        "--db",
        "db_name",
        help="Database to update " "(default: the resolved branch database).",
    )
    @click.option(
        "--all",
        "update_all",
        is_flag=True,
        help="Update all installed third-party modules (excluding the "
        "odoo/enterprise/design-themes source trees), ignoring "
        "fingerprints. With --status, widens the report to include "
        "upstream modules.",
    )
    @click.option(
        "--dry-run",
        is_flag=True,
        help="Show the diff and the odoo -u command without executing it.",
    )
    @click.option(
        "--compose-file",
        default=None,
        envvar="OSH_COMPOSE_FILE",
        help="Docker Compose file to use (e.g. devel.yaml for Doodba).",
    )
    @click.option(
        "--no-submodules",
        "skip_nested",
        is_flag=True,
        help="Skip modules inside nested git repositories "
        "(e.g. odoo/enterprise source checkouts).",
    )
    @click.option(
        "--status",
        is_flag=True,
        help="Report tracked modules and those needing an update; "
        "records the fingerprint baseline on first run. "
        "Never runs odoo -u.",
    )
    @click.option(
        "-1",
        "--per-line",
        is_flag=True,
        help="Print module lists one per line instead of comma-separated.",
    )
    def run(self):
        if self.status and self.modules:
            raise click.ClickException("--status can't be combined with module names.")
        if self.modules and self.update_all:
            raise click.ClickException("Pass module names or --all, not both.")

        base = find_project_root(required=True)
        db_name = (
            sanitize_db_name(self.db_name)
            if self.db_name
            else resolve_db_name_for_run(base, ctx=self.ctx)
        )
        if not db_exists(base, db_name, ctx=self.ctx):
            raise click.ClickException(f"Database '{db_name}' does not exist.")

        if self.modules:
            targets = sorted(set(self.modules))
        else:
            targets = core.detect_targets(
                base,
                db_name,
                update_all=self.update_all,
                status=self.status,
                dry_run=self.dry_run,
                skip_nested=self.skip_nested,
                per_line=self.per_line,
                ctx=self.ctx,
            )
            if targets is None:
                return

        if not targets:
            echo.success("All modules up to date.")
            return

        core.update_and_record(
            base,
            db_name,
            targets,
            compose_file=self.compose_file,
            dry_run=self.dry_run,
            skip_nested=self.skip_nested,
            per_line=self.per_line,
            ctx=self.ctx,
        )


class AppsList(CommandHandler):
    """List the modules recorded in a database, with version and state.

    Reads ``ir_module_module`` — every module whose state is not
    'uninstalled' — and prints each module's technical name, installed
    version and state. ``-l``/``--long`` appends the manifest summary.

    Examples:

    \b
      osh apps list
      osh apps list -l
      osh apps list -d otherdb
    """

    _cli_name = "apps.list"

    db_name = None
    long = False

    @click.option(
        "-d",
        "--db",
        "db_name",
        help="Database to list modules for " "(default: the resolved branch database).",
    )
    @click.option(
        "-l",
        "--long",
        is_flag=True,
        help="Long listing — include each module's manifest summary.",
    )
    def run(self):
        base = find_project_root(required=True)
        db_name = (
            sanitize_db_name(self.db_name)
            if self.db_name
            else resolve_db_name_for_run(base, ctx=self.ctx)
        )
        if not db_exists(base, db_name, ctx=self.ctx):
            raise click.ClickException(f"Database '{db_name}' does not exist.")
        rows = store.get_module_registry(base, db_name, ctx=self.ctx)
        if rows is None:
            raise click.ClickException(
                f"Database '{db_name}' is not an initialized Odoo database."
            )
        if not rows:
            echo.info(f"No modules installed in '{db_name}'.")
            return
        width = 3 + bool(self.long)
        headers = ("module", "version", "state", "description")[:width]
        table = [row[:width] for row in rows]
        widths = [max(len(row[i]) for row in (headers, *table)) for i in range(width)]
        echo.output("  ".join(h.ljust(w) for h, w in zip(headers, widths)))
        for row in table:
            echo.output("  ".join(v.ljust(w) for v, w in zip(row, widths)))


class AppsInstall(CommandHandler):
    """Install Odoo modules in a database.

    MODULES is a comma-separated list of module technical names, like the
    ``-i``/``--init`` option — dependencies are installed automatically.
    The database does not need to be initialized: ``odoo -i`` bootstraps
    it (``base`` included).

    Modules already installed are reported and skipped — update them with
    ``osh apps update`` instead. After the run the module states are
    re-checked, so a module Odoo silently skipped reports an error
    instead of a false success. On success the fingerprints of the
    installed project modules are recorded, so a later ``osh apps
    update`` does not update them again.

    Examples:

    \b
      osh apps install my_module
      osh apps install mod_a,mod_b
      osh apps install my_module -d otherdb
      osh apps install my_module --dry-run
    """

    _cli_name = "apps.install"

    modules = ""
    db_name = None
    dry_run = False
    compose_file = None

    @click.argument("modules")
    @click.option(
        "-d",
        "--db",
        "db_name",
        help="Database to install into " "(default: the resolved branch database).",
    )
    @click.option(
        "--dry-run",
        is_flag=True,
        help="Show the module list and the odoo -i command " "without executing it.",
    )
    @click.option(
        "--compose-file",
        default=None,
        envvar="OSH_COMPOSE_FILE",
        help="Docker Compose file to use (e.g. devel.yaml for Doodba).",
    )
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
        if not db_exists(base, db_name, ctx=self.ctx):
            raise click.ClickException(f"Database '{db_name}' does not exist.")

        core.install_and_record(
            base,
            db_name,
            names,
            compose_file=self.compose_file,
            dry_run=self.dry_run,
            ctx=self.ctx,
        )


class DbInstalled(AppsList):
    """Deprecated alias of ``osh apps list``, kept for compatibility."""

    _cli_name = "db.installed"
    _cli_hidden = True

    def run(self):
        echo.warning(
            "'osh db installed' is deprecated — use 'osh apps list'.",
            err=True,
        )
        super().run()


class DbUpdate(AppsUpdate):
    """Deprecated alias of ``osh apps update``, kept for compatibility."""

    _cli_name = "db.update"
    _cli_hidden = True

    def run(self):
        echo.warning(
            "'osh db update' is deprecated — use 'osh apps update'.",
            err=True,
        )
        super().run()


#: Standalone commands — used by tests; the CLI wires the same handlers
#: through the ``[group_commands.apps]``/``[group_commands.db]``
#: declarations.
install = handler_command("install", AppsInstall)
list_modules = handler_command("list", AppsList)
update = handler_command("update", AppsUpdate)
db_installed = handler_command("installed", DbInstalled)
db_update = handler_command("update", DbUpdate)
