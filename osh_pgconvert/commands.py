"""``osh db dump-convert`` handler."""

from pathlib import Path

import click
from osh.cli_utils import handler_command
from osh.common import find_project_root
from osh.db import resolve_db_name
from osh.handlers import CommandHandler

from . import core


class DbDumpConvert(CommandHandler):
    """Convert a PostgreSQL dump to a different server major version.

    Restores the dump into a throwaway ``postgres:<version>`` docker
    container and re-dumps from that server, so the output is guaranteed
    compatible with the target version. Produces an Odoo-format zip
    backup (``dump.sql`` + ``filestore/`` + ``manifest.json``) that
    Odoo.sh and ``osh db restore`` accept; the manifest ``pg_version``
    is updated to the target server version.

    The source can be a backup zip, a plain ``pg_dump -Fp`` .sql file,
    stdin (``-``), or a database: pass ``--from-db NAME``, or run inside
    an osh project with no file argument to export the project's
    database. ``-`` as OUTPUT writes the zip to stdout. Requires the
    ``pgdump-convert`` package (see README).

    \b
      osh db dump-convert backup.zip
      osh db dump-convert dump.sql backup-pg16.zip --to 16
      osh db dump-convert --from-db minha-vinha --filestore
      osh db dump-convert                       # project's database
    """

    _cli_name = "db.dump-convert"

    input = None
    output = None
    to = "16"
    image = None
    db_name = "odoo"
    from_db = None
    filestore = False
    dry_run = False
    allow_restore_errors = False

    @click.argument(
        "input",
        required=False,
        type=click.Path(dir_okay=False),
    )
    @click.argument(
        "output",
        required=False,
        type=click.Path(dir_okay=False),
    )
    @click.option(
        "--to",
        default="16",
        metavar="VERSION",
        help="Target PostgreSQL major version (default: 16).",
    )
    @click.option(
        "--image",
        default=None,
        metavar="IMAGE",
        help="Full container image to use instead of postgres:<to>.",
    )
    @click.option(
        "--container-db",
        "db_name",
        default="odoo",
        help="Database name inside the throwaway container (default: odoo).",
    )
    @click.option(
        "--from-db",
        "from_db",
        default=None,
        metavar="NAME",
        help=(
            "Dump database NAME from the project's PostgreSQL environment "
            "instead of reading INPUT (requires an osh project)."
        ),
    )
    @click.option(
        "--filestore",
        is_flag=True,
        help=(
            "With a database source, also bundle the project's filestore "
            "into the zip (host-accessible runtimes only)."
        ),
    )
    @click.option(
        "--dry-run",
        is_flag=True,
        help="Report what would run without doing it.",
    )
    @click.option(
        "--allow-restore-errors",
        is_flag=True,
        help=(
            "Continue even if the in-container restore reports SQL errors "
            "(default: fail fast, since the dump may be incomplete)."
        ),
    )
    def run(self):
        base = find_project_root()
        if self.from_db:
            # No input is read, so the first positional is the OUTPUT.
            if self.output is not None:
                raise click.UsageError("with --from-db only one output path is allowed")
            src = None
            from_db = self.from_db
            if base is None:
                raise click.ClickException(
                    "--from-db requires an osh project (run 'osh init' "
                    "first or cd into the project)."
                )
            output = (
                Path(self.input)
                if self.input
                else Path.cwd() / f"{from_db}-pg{self.to}.zip"
            )
        else:
            src = self.input if self.input else None
            if self.filestore:
                raise click.UsageError(
                    "--filestore only applies to a database source "
                    "(--from-db or the project's database)"
                )
            if src is not None and src != "-" and not Path(src).is_file():
                raise click.ClickException(f"{src} is not a file")
            from_db = None
            if src == "-":
                # stdin → the zip goes to stdout unless OUTPUT is given.
                output = self.output or "-"
            elif src is None:
                if base is None:
                    raise click.ClickException(
                        "Nothing to convert: pass a backup file or "
                        "--from-db NAME, or run inside an osh project to "
                        "export its database."
                    )
                from_db = resolve_db_name(base, verbose=False)
                if not from_db:
                    raise click.ClickException(
                        "Could not resolve this project's database; pass "
                        "--from-db NAME explicitly."
                    )
                output = (
                    Path(self.output)
                    if self.output
                    else Path.cwd() / f"{from_db}-pg{self.to}.zip"
                )
            else:
                src_path = Path(src)
                output = (
                    Path(self.output)
                    if self.output
                    else src_path.with_name(f"{src_path.stem}-pg{self.to}.zip")
                )
        if from_db is not None:
            core.convert_db(
                self.ctx,
                base,
                from_db,
                output,
                image=self.image or f"postgres:{self.to}",
                db_name=self.db_name,
                include_filestore=self.filestore,
                dry_run=self.dry_run,
                allow_restore_errors=self.allow_restore_errors,
            )
        else:
            core.convert(
                src,
                output,
                image=self.image or f"postgres:{self.to}",
                db_name=self.db_name,
                dry_run=self.dry_run,
                allow_restore_errors=self.allow_restore_errors,
            )


dump_convert = handler_command("dump-convert", DbDumpConvert)
__all__ = ["DbDumpConvert", "dump_convert"]
