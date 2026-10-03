"""``osh collect-migrations`` handler.

Scans a directory for git repositories — OCA clones or submodules — and
collects each module's ``migrations/`` scripts from every version branch
into a ``migration/`` tree mirroring the scanned layout.
"""

import click
from osh.cli_utils import handler_command
from osh.handlers import CommandHandler

from . import core


class CollectMigrations(CommandHandler):
    """Collect module migrations/ scripts across version branches.

    Every OCA branch ships only the migration scripts for its own version,
    so upgrading a database across several versions (e.g. 17.0 → 19.0) is
    missing the scripts from the versions in between. This command checks
    out each ``N.N`` branch of every git repository below TARGET in a
    temporary ``git worktree`` — the clones' own checkouts are never
    touched — and copies each module's ``migrations/`` directory into a
    ``migration/`` tree mirroring the scanned layout.

    Merge the collected tree over the scanned directory before running
    ``odoo -u all`` so all intermediate migration scripts are present:

    \b
      osh collect-migrations external/ --from 18.0 --to 19.0
      cp -r migration/* external/

    Repositories are discovered like ``osh switch`` finds them: any git
    checkout below TARGET counts, whether a submodule or a plain clone.
    Branches are collected from REMOTE (``origin`` by default); local
    version branches are used only when the remote doesn't have them.
    """

    _cli_name = "collect-migrations"

    target = "."
    output = "migration"
    remote = "origin"
    from_version = None
    to_version = None
    dry_run = False

    @click.argument(
        "target",
        required=False,
        default=".",
        type=click.Path(exists=True, file_okay=False),
    )
    @click.option(
        "-o",
        "--output",
        default="migration",
        type=click.Path(file_okay=False),
        help="Directory to write the collected tree into (default: ./migration).",
    )
    @click.option(
        "--remote",
        default="origin",
        metavar="REMOTE",
        help="Remote whose version branches to collect (default: origin).",
    )
    @click.option(
        "--from",
        "from_version",
        metavar="VERSION",
        help="Oldest version branch to collect (e.g. 17.0).",
    )
    @click.option(
        "--to",
        "to_version",
        metavar="VERSION",
        help="Newest version branch to collect (e.g. 19.0).",
    )
    @click.option(
        "--dry-run",
        is_flag=True,
        help="Report what would be collected without copying anything.",
    )
    def run(self):
        core.collect(
            self.target,
            self.output,
            remote=self.remote,
            from_version=self.from_version,
            to_version=self.to_version,
            dry_run=self.dry_run,
        )


#: Standalone ``collect-migrations`` command — used by tests; the CLI wires
#: the same handler through the ``[commands]`` declaration.
collect_migrations = handler_command("collect-migrations", CollectMigrations)
