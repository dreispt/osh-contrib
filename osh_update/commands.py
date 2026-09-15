"""``osh addon update`` command implementation.

Detects which project modules changed since the last update — using
fingerprints stored in the target database's ``ir.config_parameter`` — and
runs ``odoo -u`` on the installed ones. On the first run it only records the
current fingerprints as a baseline without updating anything.
"""

import click
from osh import echo
from osh.common import find_project_root
from osh.db import resolve_db_name_for_run, sanitize_db_name

from . import core


@click.command(name="update")
@click.argument("modules", nargs=-1)
@click.option(
    "-d",
    "--db",
    "db_name",
    help="Database to update (default: the resolved branch database).",
)
@click.option(
    "--all",
    "update_all",
    is_flag=True,
    help="Update all installed third-party modules (excluding the "
    "odoo/enterprise/design-themes source trees), ignoring fingerprints. "
    "With --status, widens the report to include upstream modules.",
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
    help="Report installed modules and those needing an update; "
    "records the fingerprint baseline on first run. Never runs odoo -u.",
)
@click.option(
    "-1",
    "--per-line",
    is_flag=True,
    help="Print module lists one per line instead of comma-separated.",
)
@click.pass_context
def update(
    ctx,
    modules,
    db_name,
    update_all,
    dry_run,
    compose_file,
    skip_nested,
    status,
    per_line,
):  # noqa: D401
    """Update project modules whose code changed since the last update.

    Each project module is fingerprinted (code and data files; ``static/``
    is ignored) and compared against the fingerprints stored in the target
    database. Installed modules that changed are updated with ``odoo -u``.

    On the first run only a fingerprint baseline is recorded — no update is
    performed. Pass module names or ``--all`` to force an update.

    Examples:

    \b
      osh addon update
      osh addon update my_module other_module
      osh addon update --all
      osh addon update --status
      osh addon update -d otherdb --dry-run

    Runs on the project's active backend — see ``osh <backend> activate``.
    """
    if status and modules:
        raise click.ClickException("--status can't be combined with module names.")
    if modules and update_all:
        raise click.ClickException("Pass module names or --all, not both.")

    base = find_project_root(required=True)
    db_name = (
        sanitize_db_name(db_name) if db_name else resolve_db_name_for_run(base, ctx=ctx)
    )

    if modules:
        targets = sorted(set(modules))
    else:
        targets = core.detect_targets(
            base,
            db_name,
            update_all=update_all,
            status=status,
            dry_run=dry_run,
            skip_nested=skip_nested,
            per_line=per_line,
            ctx=ctx,
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
        compose_file=compose_file,
        dry_run=dry_run,
        skip_nested=skip_nested,
        per_line=per_line,
        ctx=ctx,
    )
