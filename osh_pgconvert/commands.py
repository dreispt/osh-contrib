"""``osh db dump-convert`` handler."""

from pathlib import Path

import click
from osh.cli_utils import handler_command
from osh.handlers import CommandHandler

from . import core


class DbDumpConvert(CommandHandler):
    """Convert a PostgreSQL dump to a different server major version.

    Restores the dump into a throwaway ``postgres:<version>`` docker
    container and re-dumps from that server, so the output is guaranteed
    compatible with the target version. Works on Odoo-format zip backups
    (``dump.sql`` + ``filestore/`` + ``manifest.json``); the manifest
    ``pg_version`` is updated to the target server version.

    \b
      osh db dump-convert backup.zip
      osh db dump-convert backup.zip backup-pg16.zip --to 16
      osh db dump-convert backup.zip --image postgres:15-alpine
    """

    _cli_name = "db.dump-convert"

    input = None
    output = None
    to = "16"
    image = None
    db_name = "odoo"
    dry_run = False

    @click.argument(
        "input",
        type=click.Path(exists=True, dir_okay=False),
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
        "--db",
        "db_name",
        default="odoo",
        help="Database name inside the throwaway container (default: odoo).",
    )
    @click.option(
        "--dry-run",
        is_flag=True,
        help="Report what would run without doing it.",
    )
    def run(self):
        src = Path(self.input)
        output = self.output or str(src.with_name(f"{src.stem}-pg{self.to}.zip"))
        image = self.image or f"postgres:{self.to}"
        core.convert(
            src,
            output,
            image=image,
            db_name=self.db_name,
            dry_run=self.dry_run,
        )


dump_convert = handler_command("dump-convert", DbDumpConvert)
__all__ = ["DbDumpConvert", "dump_convert"]
